"""Les dépôts Maven déclarés (E33) : ``<repositories>`` des ``pom.xml``, ``~/.m2/settings.xml``
de la personne (miroirs, serveurs, profils actifs), et ``repositories { }`` des scripts Gradle.

Ni Maven ni Gradle ne sont installés ici (choix de l'utilisateur) : les formats sont lus d'après
leur documentation (« Settings Reference », « Guide to Mirror Settings », « Declaring
repositories » de Gradle), sans vérification par l'outil.

**Maven** : les dépôts des profils actifs de ``settings.xml`` (``activeByDefault``,
``<activeProfiles>``), puis ``<repositories>`` et ``<pluginRepositories>`` du ``pom.xml`` et de
ses parents du dépôt (``${propriété}`` remplacée par celles des ``<properties>``), puis Maven
Central (``central``). Un ``<mirror>`` remplace chaque dépôt que désigne son ``mirrorOf`` (son id
exact d'abord, puis ``*``, ``external:*``, ``external:http:*``, une liste, ``!id``). Les dépôts
autres que Central sont demandés d'abord, dans l'ordre, et le premier qui a l'artefact l'emporte ;
Central en dernier, s'il n'a pas de miroir.

Les identifiants : ``<server>`` (``username``, ``password`` ; ``${env.NOM}`` développé ; un mot de
passe chiffré ``{…}`` n'est pas lu), rattaché à un *id* : il ne part que vers une adresse que
``settings.xml`` donne à cet id (un miroir, un dépôt d'un profil), jamais vers celle qu'un
``pom.xml`` lui donnerait (un dépôt pourrait sinon recevoir les identifiants de la personne en
déclarant le même id).

**Gradle** : les blocs ``repositories { }`` des scripts du projet, de ses dossiers parents et de
``settings.gradle(.kts)`` (``dependencyResolutionManagement``, ``pluginManagement``), lus en
jetons (jamais exécutés) : ``mavenCentral()``, ``google()``, ``gradlePluginPortal()`` sont publics ;
``maven("…")``, ``maven { url = uri("…") }``, ``maven { url "…" }``, ``setUrl("…")`` déclarent un
dépôt ; ``content { includeGroup("…") }`` (ou ``exclusiveContent``) lui réserve des groupes,
**privés par leur nom**. Les identifiants d'un dépôt Gradle viennent de propriétés ou de
l'environnement, que le script lit en s'exécutant : ils ne sont pas lus (dit).
"""

import posixpath
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from forceupdate import userfiles
from forceupdate.models import Dependency, Notice, Project
from forceupdate.net.auth import Credential, basic, bound_or_none, is_loopback, split_userinfo
from forceupdate.parsers.base import ParseError, ReadText
from forceupdate.parsers.gradle import SCRIPTS
from forceupdate.parsers.gradle_spans import Token, tokens
from forceupdate.parsers.maven import MANIFEST, pom_chain
from forceupdate.parsers.xml_spans import Element, parse
from forceupdate.routing import PUBLIC, Declared, Reading, Route, Router, User

CENTRAL_ID = "central"
CENTRAL_HOSTS = frozenset({"repo.maven.apache.org", "repo1.maven.org", "central.sonatype.com"})
PUBLIC_HOSTS = CENTRAL_HOSTS | {"dl.google.com", "maven.google.com", "plugins.gradle.org"}
SETTINGS = "~/.m2/settings.xml"
SETTINGS_FILES = ("settings.gradle", "settings.gradle.kts")
_PROPERTY = re.compile(r"\$\{([^}]+)\}")


@dataclass(frozen=True, kw_only=True)
class Repository:
    """Un dépôt : son id, son adresse, le fichier qui le déclare, et s'il vient de la personne."""

    id: str
    url: str
    file: str
    personal: bool = False
    groups: tuple[str, ...] = ()
    """Gradle : les groupes qui lui sont réservés (``includeGroup``)."""

    @property
    def public(self) -> bool:
        return (urlsplit(self.url).hostname or "").lower() in PUBLIC_HOSTS

    def declared(self) -> Declared:
        return Declared(url=self.url.rstrip("/"), file=self.file)


@dataclass(kw_only=True)
class Settings:
    """Ce que dit ``settings.xml`` : miroirs, serveurs, dépôts des profils actifs."""

    mirrors: list[tuple[str, str, str]] = field(default_factory=list)
    """(id, adresse, mirrorOf)."""
    servers: dict[str, tuple[str, str]] = field(default_factory=dict)
    repositories: list[Repository] = field(default_factory=list)
    credentials: list[Credential] = field(default_factory=list)
    """Ceux écrits dans une adresse (``https://nom:secret@hôte/…``)."""
    notices: list[Notice] = field(default_factory=list)


def read(project: Project, read_text: ReadText, user: User) -> Reading | None:
    """L'aiguillage des artefacts Maven de ``project`` : Maven pour ceux d'un ``pom.xml``, Gradle
    pour les autres."""
    names = {posixpath.basename(p): p for p in project.manifests}
    maven: Router | None = None
    credentials: list[Credential] = []
    notices: list[Notice] = []
    if MANIFEST in names:
        settings = user.memo("maven.settings", _settings)
        maven = _maven(names[MANIFEST], read_text, settings, credentials, notices)
    gradle: Router | None = None
    if any(posixpath.basename(p) in SCRIPTS for p in project.manifests):
        gradle = _gradle(project, read_text, notices)
    if maven is None and gradle is None:
        return None

    def route(dependency: Dependency) -> Route:
        if dependency.file.endswith(MANIFEST) and maven is not None:
            return maven(dependency)
        if gradle is not None:
            return gradle(dependency)
        return PUBLIC if maven is None else maven(dependency)

    return Reading(router=route, credentials=credentials, notices=notices)


# -- Maven -----------------------------------------------------------------------------


def _settings() -> Settings:
    settings = Settings()
    text = userfiles.read(userfiles.home() / ".m2" / "settings.xml")
    if text is None:
        return settings
    try:
        root = parse(text)
    except ParseError:
        return settings

    def value(element: Element, tag: str) -> str | None:
        raw = element.child_text(tag)
        return userfiles.expand(raw) if raw else None

    for mirror in root.path("mirrors", "mirror"):
        mirror_id, url, of = value(mirror, "id"), value(mirror, "url"), value(mirror, "mirrorOf")
        if mirror_id and url and of:
            url = _without_userinfo(url, SETTINGS, settings.credentials)
            settings.mirrors.append((mirror_id, url, of))
    for server in root.path("servers", "server"):
        server_id = server.child_text("id")
        username, password = value(server, "username"), value(server, "password")
        if not server_id or not username or password is None:
            continue
        if password.startswith("{") and password.endswith("}"):
            message = (
                f"le mot de passe du serveur « {server_id} » est chiffré : forceupdate ne le lit "
                "pas (le dépôt est demandé sans lui)."
            )
            settings.notices.append(Notice(file=SETTINGS, message=message))
            continue
        settings.servers[server_id] = (username, password)
    active = {p.text for p in root.path("activeProfiles", "activeProfile") if p.text}
    for profile in root.path("profiles", "profile"):
        by_default = profile.find("activation")
        on = by_default is not None and by_default.child_text("activeByDefault") == "true"
        if not on and profile.child_text("id") not in active:
            continue
        for kind in (("repositories", "repository"), ("pluginRepositories", "pluginRepository")):
            for repository in profile.path(*kind):
                repo_id, url = repository.child_text("id"), value(repository, "url")
                if repo_id and url:
                    url = _without_userinfo(url, SETTINGS, settings.credentials)
                    settings.repositories.append(
                        Repository(id=repo_id, url=url, file=SETTINGS, personal=True)
                    )
    return settings


def _maven(
    pom: str,
    read_text: ReadText,
    settings: Settings,
    credentials: list[Credential],
    notices: list[Notice],
) -> Router:
    declared = list(settings.repositories)
    credentials += settings.credentials
    chain = pom_chain(pom, read_text)
    properties: dict[str, str] = {}
    for ancestor in reversed(chain):
        properties.update({name: p.value for name, p in ancestor.properties.items()})
    unreadable: str | None = None
    for ancestor in chain:
        for repo_id, url in _pom_repositories(ancestor.path, read_text):
            resolved = _PROPERTY.sub(lambda m: properties.get(m.group(1), m.group(0)), url)
            if "${" in resolved:
                unreadable = unreadable or ancestor.path
                message = (
                    f"l'adresse du dépôt « {repo_id} » ne se lit pas (une propriété) : pas lu."
                )
                notices.append(Notice(file=ancestor.path, message=message))
                continue
            clean = _without_userinfo(resolved, ancestor.path, credentials)
            declared.append(Repository(id=repo_id, url=clean, file=ancestor.path))
    declared.append(Repository(id=CENTRAL_ID, url="https://repo.maven.apache.org/maven2", file=""))
    effective: list[Repository] = []
    for repository in declared:
        mirrored = _mirror(repository, settings.mirrors)
        if all(r.url.rstrip("/") != mirrored.url.rstrip("/") for r in effective):
            effective.append(mirrored)
    notices += settings.notices
    _server_credentials(effective, declared, settings, credentials, notices)
    first = tuple(r.declared() for r in effective if r.id != CENTRAL_ID and not r.public)
    public = any(r.public for r in effective)

    def route(dependency: Dependency) -> Route:
        if unreadable is not None:
            return Route(
                public=False,
                unchecked=(
                    f"Non vérifié : l'adresse d'un dépôt de {unreadable} ne se lit pas ; il "
                    "pourrait servir cet artefact"
                ),
            )
        if not first:
            return PUBLIC
        return Route(registries=first, public=public)

    return route


def _without_userinfo(url: str, source: str, credentials: list[Credential]) -> str:
    """``url`` sans les identifiants écrits dedans, qui vont dans ``credentials``, liés à elle."""
    clean, userinfo = split_userinfo(url)
    if userinfo is not None and userinfo[0] and not userfiles.unexpanded(userinfo[1]):
        credential = bound_or_none(clean, value=basic(*userinfo), source=source)
        if credential is not None:
            credentials.append(credential)
    return clean


def _pom_repositories(path: str, read_text: ReadText) -> list[tuple[str, str]]:
    try:
        text = read_text(path)
        root = parse(text) if text is not None else None
    except (ValueError, ParseError):
        root = None
    if root is None:
        return []
    found = []
    for kind in (("repositories", "repository"), ("pluginRepositories", "pluginRepository")):
        for repository in root.path(*kind):
            repo_id, url = repository.child_text("id"), repository.child_text("url")
            if repo_id and url:
                found.append((repo_id, url.strip()))
    return found


def _mirror(repository: Repository, mirrors: list[tuple[str, str, str]]) -> Repository:
    """Le dépôt, ou le miroir qui le remplace (son id exact d'abord, puis un motif)."""
    for mirror_id, url, of in mirrors:
        if of.strip() == repository.id:
            return Repository(id=mirror_id, url=url, file=SETTINGS, personal=True)
    for mirror_id, url, of in mirrors:
        if _mirror_of(of, repository):
            return Repository(id=mirror_id, url=url, file=SETTINGS, personal=True)
    return repository


def _mirror_of(pattern: str, repository: Repository) -> bool:
    """``mirrorOf`` désigne-t-il ``repository`` ? (``DefaultMirrorSelector`` de Maven)."""
    parts = urlsplit(repository.url)
    host = parts.hostname or ""
    external = bool(host) and not is_loopback(host) and parts.scheme != "file"
    accepted = {"*", repository.id}
    if external:
        accepted.add("external:*")
        if parts.scheme == "http":
            accepted.add("external:http:*")
    words = [word.strip() for word in pattern.split(",")]
    if f"!{repository.id}" in words:
        return False
    return any(word in accepted for word in words)


def _server_credentials(
    effective: list[Repository],
    declared: list[Repository],
    settings: Settings,
    credentials: list[Credential],
    notices: list[Notice],
) -> None:
    """Les identifiants des ``<server>``, liés aux adresses que ``settings.xml`` donne à leur id."""
    personal = {r.id: r.url for r in effective if r.personal}
    for repository in declared:
        if repository.personal:
            personal.setdefault(repository.id, repository.url)
    for server_id, (username, password) in settings.servers.items():
        url = personal.get(server_id)
        if url is None:
            if any(r.id == server_id for r in effective):
                message = (
                    f"les identifiants du serveur « {server_id} » ne partent pas vers l'adresse "
                    "qu'un pom.xml donne à cet id : la déclarer dans settings.xml (un miroir)."
                )
                notices.append(Notice(file=SETTINGS, message=message))
            continue
        credential = bound_or_none(url, value=basic(username, password), source=SETTINGS)
        if credential is not None:
            credentials.append(credential)


# -- Gradle ----------------------------------------------------------------------------


def _gradle(project: Project, read_text: ReadText, notices: list[Notice]) -> Router:
    repositories: list[Repository] = []
    public = False
    seen_block = False
    for path in _gradle_files(project, read_text):
        try:
            text = read_text(path)
        except ValueError:
            text = None
        if text is None:
            continue
        try:
            found = tokens(text)
        except ParseError:
            continue
        for kind, repository, credentials in _repositories_blocks(found, path):
            seen_block = True
            if kind == "public":
                public = True
            elif repository is not None and all(r.url != repository.url for r in repositories):
                if repository.public:
                    public = True
                else:
                    repositories.append(repository)
            if credentials:
                message = (
                    "les identifiants d'un dépôt Gradle viennent de propriétés ou de "
                    "l'environnement, que le script lit en s'exécutant : forceupdate ne les lit "
                    "pas (le dépôt est demandé sans eux)."
                )
                notice = Notice(file=path, message=message)
                if notice not in notices:
                    notices.append(notice)
    if not seen_block:
        public = True
    reserved = [r for r in repositories if r.groups]
    others = tuple(r.declared() for r in repositories if not r.groups)

    def route(dependency: Dependency) -> Route:
        group = dependency.name.partition(":")[0]
        mine = tuple(r.declared() for r in reserved if group in r.groups)
        if mine:
            return Route(registries=mine, public=False, private=True)
        if not others and not public:
            return Route(
                public=False,
                unchecked="Non vérifié : aucun dépôt lu dans repositories { } (mavenLocal ?)",
            )
        if not others:
            return PUBLIC
        return Route(registries=others, public=public)

    return route


def _gradle_files(project: Project, read_text: ReadText) -> Iterator[str]:
    """Les scripts du projet, puis ceux de ses dossiers parents et leurs ``settings.gradle``."""
    yield from (p for p in project.manifests if posixpath.basename(p) in SCRIPTS)
    directory = project.path or "."
    first = True
    while True:
        for name in (*SETTINGS_FILES, *([] if first else SCRIPTS)):
            yield name if directory == "." else posixpath.join(directory, name)
        first = False
        if directory == ".":
            return
        directory = posixpath.dirname(directory) or "."


_PUBLIC_CALLS = frozenset({"mavenCentral", "google", "gradlePluginPortal", "jcenter"})


def _repositories_blocks(
    found: list[Token], path: str
) -> Iterator[tuple[str, Repository | None, bool]]:
    """Les dépôts des blocs ``repositories { }`` : (``"public"`` ou ``"maven"``, le dépôt, s'il a
    des identifiants)."""
    blocks: list[str] = []
    index = 0
    while index < len(found):
        token = found[index]
        if token.kind == "op" and token.value == "{":
            previous = found[index - 1] if index else None
            blocks.append(
                previous.value if previous is not None and previous.kind == "ident" else ""
            )
        elif token.kind == "op" and token.value == "}":
            if blocks:
                blocks.pop()
        elif token.kind == "ident" and blocks and blocks[-1] == "repositories":
            following = found[index + 1] if index + 1 < len(found) else None
            if token.value in _PUBLIC_CALLS:
                yield "public", None, False
            elif token.value in ("maven", "exclusiveContent") and following is not None:
                end = _block_end(found, index + 1)
                repository, credentials = _maven_repository(found[index + 1 : end], path)
                yield "maven", repository, credentials
                index = end
                continue
        index += 1


def _block_end(found: list[Token], start: int) -> int:
    """L'index après l'appel qui commence en ``start`` (``( … )`` puis éventuellement ``{ … }``)."""
    index = start
    for opening, closing in (("(", ")"), ("{", "}")):
        if index < len(found) and found[index].kind == "op" and found[index].value == opening:
            depth = 0
            while index < len(found):
                token = found[index]
                if token.kind == "op" and token.value == opening:
                    depth += 1
                elif token.kind == "op" and token.value == closing:
                    depth -= 1
                    if depth == 0:
                        index += 1
                        break
                index += 1
    return index


def _maven_repository(found: list[Token], path: str) -> tuple[Repository | None, bool]:
    """Le dépôt d'un appel ``maven(…) { … }`` : sa première adresse, ses groupes réservés, et
    s'il déclare des identifiants."""
    url = next(
        (t.value for t in found if t.kind == "string" and re.match(r"https?://", t.value)), None
    )
    groups = []
    credentials = False
    for position, token in enumerate(found):
        if token.kind != "ident":
            continue
        if token.value in ("includeGroup", "includeGroupAndSubgroups", "includeModule"):
            argument = next((t for t in found[position + 1 :] if t.kind == "string"), None)
            if argument is not None:
                groups.append(argument.value)
        elif token.value in ("credentials", "authentication"):
            credentials = True
    if url is None or "$" in url:
        return None, credentials
    return Repository(id=url, url=url, file=path, groups=tuple(groups)), credentials
