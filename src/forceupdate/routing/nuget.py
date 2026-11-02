"""Les sources NuGet déclarées (E33) : ``nuget.config`` du projet, ``NuGet.Config`` de la personne.

Comme NuGet (vérifié le 2026-11-02 avec le SDK .NET 10.0.403, ``dotnet nuget list source``) :

- les fichiers ``nuget.config`` (ou ``NuGet.config``, ``NuGet.Config``) du dossier du projet et de
  ses parents (ici, dans la source), du plus proche au plus lointain, puis celui de la personne
  (``%APPDATA%\\NuGet\\NuGet.Config`` sous Windows, ``~/.nuget/NuGet/NuGet.Config`` ailleurs ; sans
  lui, nuget.org) : les sources du plus proche viennent d'abord ; ``<clear />`` écarte celles
  des fichiers plus lointains (et celles écrites avant lui) ; une même clé : la plus proche ;
- ``disabledPackageSources`` désactive une source ; une source qui n'est pas en http(s) (un
  dossier) n'est pas lue ;
- ``packageSourceMapping`` : chaque paquet ne va qu'aux sources du motif le plus précis qui lui
  correspond (``Contoso.*``, ``*``) ; un paquet que ses motifs envoient ailleurs qu'à nuget.org est
  **privé par son nom** : jamais demandé à nuget.org ni à OSV ;
- sans ``packageSourceMapping``, NuGet demande toutes les sources ; ici, les sources autres que
  nuget.org d'abord, et la première qui connaît le paquet l'emporte.

Les identifiants : ``packageSourceCredentials``, un élément par nom de source (``_x0020_`` pour une
espace), ``Username`` et ``ClearTextPassword`` (``%NOM%`` développé dans le fichier de la personne
seulement) ; un ``Password`` chiffré (DPAPI) n'est pas lu. Rattachés à un *nom* : ceux du fichier de
la personne ne partent que vers l'adresse que ce même fichier donne à la source, jamais vers celle
qu'un fichier du projet donnerait au même nom.

Un flux v2 (pas d'index de services ``…/index.json``) n'est pas lu : un paquet qu'il pourrait servir
est « non vérifié » ; celui de nuget.org (``www.nuget.org/api/v2``) est nuget.org.
"""

import posixpath
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from forceupdate import userfiles
from forceupdate.models import Dependency, Notice, Project
from forceupdate.net.auth import Credential, basic, bound_or_none, origin, split_userinfo
from forceupdate.parsers.base import ParseError, ReadText
from forceupdate.parsers.xml_spans import Element, parse
from forceupdate.routing import PUBLIC, Declared, Reading, Route, Router, User

CONFIG_NAMES = ("nuget.config", "NuGet.config", "NuGet.Config")
PUBLIC_HOSTS = frozenset({"api.nuget.org", "www.nuget.org", "nuget.org"})
USER_CONFIG = "NuGet.Config (de la personne)"


@dataclass(frozen=True, kw_only=True)
class Source:
    """Une source de paquets : son nom, son adresse, le fichier qui la donne."""

    key: str
    url: str
    file: str
    personal: bool
    protocol: str = ""

    @property
    def public(self) -> bool:
        return (urlsplit(self.url).hostname or "").lower() in PUBLIC_HOSTS

    @property
    def http(self) -> bool:
        return origin(self.url) is not None

    @property
    def v2(self) -> bool:
        return self.protocol == "2" or not urlsplit(self.url).path.lower().endswith(".json")


@dataclass(kw_only=True)
class NuGetConfig:
    """Les sources actives, dans l'ordre, la correspondance des paquets, et les identifiants."""

    sources: list[Source] = field(default_factory=list)
    mapping: dict[str, list[str]] = field(default_factory=dict)
    """Par nom de source, ses motifs (``packageSourceMapping``)."""
    credentials: list[Credential] = field(default_factory=list)
    notices: list[Notice] = field(default_factory=list)


def user_config_path() -> Path:
    if sys.platform == "win32":
        return userfiles.config_home() / "NuGet" / "NuGet.Config"
    return userfiles.home() / ".nuget" / "NuGet" / "NuGet.Config"


def read(project: Project, read_text: ReadText, user: User) -> Reading | None:
    """L'aiguillage des paquets NuGet de ``project``."""
    files = _project_configs(project, read_text)
    personal = user.memo("nuget.config", _personal_config)
    config = merge(files, personal)
    if not files and personal is None:
        return None
    only_public = all(source.public for source in config.sources) and not config.mapping
    if only_public and config.sources and not config.notices:
        return None
    return Reading(router=_router(config), credentials=config.credentials, notices=config.notices)


def _project_configs(project: Project, read_text: ReadText) -> list[tuple[str, Element]]:
    found = []
    directory = project.path or "."
    while True:
        for name in CONFIG_NAMES:  # sous Windows, les trois noms désignent le même fichier
            path = name if directory == "." else posixpath.join(directory, name)
            try:
                text = read_text(path)
            except ValueError:
                text = None
            if text is None:
                continue
            element = _parse(text)
            if element is not None:
                found.append((path, element))
            break
        if directory == ".":
            return found
        directory = posixpath.dirname(directory) or "."


def _personal_config() -> tuple[str, Element] | None:
    text = userfiles.read(user_config_path())
    element = _parse(text) if text is not None else None
    return None if element is None else (USER_CONFIG, element)


def _parse(text: str) -> Element | None:
    try:
        root = parse(text)
    except ParseError:
        return None
    return root if root.tag.lower() == "configuration" else None


def _section(root: Element, name: str) -> tuple[list[Element], bool]:
    """Les ``<add>`` (ou autres enfants) d'une section après son dernier ``<clear />``, et s'il y
    en a un."""
    section = next((c for c in root.children if c.tag == name), None)
    if section is None:
        return [], False
    children = section.children
    cleared = [i for i, child in enumerate(children) if child.tag == "clear"]
    if cleared:
        return children[cleared[-1] + 1 :], True
    return children, False


def merge(files: list[tuple[str, Element]], personal: tuple[str, Element] | None) -> NuGetConfig:
    """La configuration des fichiers ``files`` (du plus proche au plus lointain) et de la
    personne."""
    layers = [(path, root, False) for path, root in files]
    if personal is not None:
        layers.append((personal[0], personal[1], True))
    config = NuGetConfig()
    sources: dict[str, Source] = {}
    disabled: dict[str, bool] = {}
    mapping: dict[str, list[str]] = {}
    mapping_done = sources_done = disabled_done = False
    for path, root, is_personal in layers:
        if not sources_done:
            adds, cleared = _section(root, "packageSources")
            for add in adds:
                key, value = add.attributes.get("key"), add.attributes.get("value")
                if add.tag == "add" and key and value and key.lower() not in sources:
                    protocol = add.attributes.get("protocolVersion", "")
                    url = _source_url(key, value, path, is_personal, config)
                    if url is not None:
                        sources[key.lower()] = Source(
                            key=key, url=url, file=path, personal=is_personal, protocol=protocol
                        )
            sources_done = cleared
        if not disabled_done:
            adds, cleared = _section(root, "disabledPackageSources")
            for add in adds:
                key = add.attributes.get("key")
                if add.tag == "add" and key and key.lower() not in disabled:
                    disabled[key.lower()] = add.attributes.get("value", "").lower() == "true"
            disabled_done = cleared
        if not mapping_done:
            entries, cleared = _section(root, "packageSourceMapping")
            for entry in entries:
                key = entry.attributes.get("key")
                if entry.tag == "packageSource" and key and key.lower() not in mapping:
                    mapping[key.lower()] = [
                        pattern.attributes["pattern"]
                        for pattern in entry.findall("package")
                        if pattern.attributes.get("pattern")
                    ]
            mapping_done = cleared
    if personal is None and not sources_done:
        url = "https://api.nuget.org/v3/index.json"
        sources.setdefault("nuget.org", Source(key="nuget.org", url=url, file="", personal=True))
    config.sources = [s for k, s in sources.items() if not disabled.get(k) and s.http]
    config.mapping = mapping
    _credentials(layers, sources, config)
    return config


def _source_url(key: str, value: str, file: str, personal: bool, config: NuGetConfig) -> str | None:
    """L'adresse de la source ``key``, sans les identifiants écrits dedans (liés à elle)."""
    if personal:
        expanded = userfiles.expand(value, style="windows")
        if expanded is None:
            return None
        value = expanded
    elif userfiles.unexpanded(value):
        message = (
            f"l'adresse de la source « {key} » utilise une variable d'environnement : pas lue."
        )
        config.notices.append(Notice(file=file, message=message))
        return None
    clean, userinfo = split_userinfo(value)
    if userinfo is not None and userinfo[0]:
        credential = bound_or_none(clean, value=basic(*userinfo), source=file)
        if credential is not None:
            config.credentials.append(credential)
    return clean


_ENCODED = re.compile(r"_x([0-9A-Fa-f]{4})_")


def _decoded(tag: str) -> str:
    """Un nom de source écrit en nom d'élément XML (``My_x0020_Feed`` : ``My Feed``)."""
    return _ENCODED.sub(lambda m: chr(int(m.group(1), 16)), tag)


def _credentials(
    layers: list[tuple[str, Element, bool]], sources: dict[str, Source], config: NuGetConfig
) -> None:
    """Les identifiants de ``packageSourceCredentials``, chacun lié à l'adresse de sa source (voir
    la docstring du module)."""
    seen: set[str] = set()
    for path, root, is_personal in layers:
        section = next((c for c in root.children if c.tag == "packageSourceCredentials"), None)
        for entry in section.children if section is not None else []:
            name = _decoded(entry.tag).lower()
            if name in seen or entry.tag == "clear":
                continue
            seen.add(name)
            values = {
                add.attributes.get("key", "").lower(): add.attributes.get("value", "")
                for add in entry.findall("add")
            }
            username = values.get("username")
            password = values.get("cleartextpassword")
            if "password" in values and password is None:
                message = (
                    f"le mot de passe de la source « {_decoded(entry.tag)} » est chiffré "
                    "(Password) : forceupdate ne lit que ClearTextPassword."
                )
                config.notices.append(Notice(file=path, message=message))
                continue
            if not username or password is None:
                continue
            if is_personal:
                username = userfiles.expand(username, style="windows")
                password = userfiles.expand(password, style="windows")
            elif userfiles.unexpanded(username) or userfiles.unexpanded(password):
                message = (
                    f"les identifiants de la source « {_decoded(entry.tag)} » utilisent une "
                    "variable d'environnement : forceupdate ne développe jamais celles d'un "
                    "fichier du projet. Les mettre dans le NuGet.Config de la personne."
                )
                config.notices.append(Notice(file=path, message=message))
                continue
            if username is None or password is None:
                continue
            source = sources.get(name)
            if source is None:
                continue
            if is_personal and not source.personal:
                own = _url_in(root, name)
                if own is None or origin(own) != origin(source.url):
                    message = (
                        f"les identifiants de la source « {source.key} » ne partent pas vers "
                        "l'adresse qu'un fichier du projet lui donne : la déclarer aussi dans le "
                        "NuGet.Config de la personne."
                    )
                    config.notices.append(Notice(file=path, message=message))
                    continue
            credential = bound_or_none(source.url, value=basic(username, password), source=path)
            if credential is not None:
                # L'index de services et l'API « registration » sont sur le même hôte.
                config.credentials.append(
                    Credential(
                        host=credential.host,
                        port=credential.port,
                        path="/",
                        scheme=credential.scheme,
                        value=credential.value,
                        source=path,
                    )
                )


def _url_in(root: Element, name: str) -> str | None:
    adds, _ = _section(root, "packageSources")
    for add in adds:
        if add.tag == "add" and (add.attributes.get("key") or "").lower() == name:
            return userfiles.expand(add.attributes.get("value", ""), style="windows")
    return None


def _best(mapping: dict[str, list[str]], package: str) -> list[str]:
    """Les sources du motif le plus précis qui correspond à ``package`` (sans tenir compte de la
    casse) ; aucune si rien ne correspond."""
    package = package.lower()
    scores: dict[str, int] = {}
    for source, patterns in mapping.items():
        for pattern in patterns:
            lowered = pattern.lower()
            if lowered.endswith("*"):
                matched = package.startswith(lowered[:-1])
            else:
                matched = package == lowered
            if matched:
                score = len(lowered) + (1 if not lowered.endswith("*") else 0)
                scores[source] = max(scores.get(source, -1), score)
    if not scores:
        return []
    top = max(scores.values())
    return [source for source, score in scores.items() if score == top]


def _router(config: NuGetConfig) -> Router:
    def declared(source: Source) -> Declared:
        return Declared(url=source.url, file=source.file)

    def route(dependency: Dependency) -> Route:
        sources = config.sources
        private = False
        if config.mapping:
            wanted = set(_best(config.mapping, dependency.name))
            sources = [s for s in sources if s.key.lower() in wanted]
            if not sources:
                return Route(
                    public=False,
                    unchecked=(
                        "Non vérifié : aucune source de packageSourceMapping ne sert ce paquet "
                        "(NuGet le refuserait)"
                    ),
                )
            private = not any(s.public for s in sources)
        legacy = [s for s in sources if s.v2 and not s.public]
        if legacy:
            return Route(
                public=False,
                private=private,
                unchecked=(
                    f"Non vérifié : la source « {legacy[0].key} » est un flux NuGet v2, que "
                    "forceupdate ne lit pas ; elle pourrait servir ce paquet"
                ),
            )
        others = tuple(declared(s) for s in sources if not s.public)
        public = any(s.public for s in sources)
        if not others and public:
            return PUBLIC
        return Route(registries=others, public=public, private=private)

    return route
