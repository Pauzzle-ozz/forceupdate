"""Les serveurs de gems (E33, E34) : la source globale d'un ``Gemfile``, ses blocs ``source "…" do``
et l'option ``source:``, avec les miroirs et les identifiants de Bundler.

Vérifié le 2026-11-02 avec Bundler 4.0.20 et un serveur local à index compact qui exige un
identifiant :

- Bundler demande à chaque source son index compact (``/versions``, puis ``/info/{gem}``) ; une gem
  d'un bloc ``source "…" do`` ou d'une option ``source:`` n'est demandée qu'à ce serveur, jamais à
  rubygems.org, même s'il ne l'a pas ; les autres, à la source globale (une seule : Bundler 4 refuse
  un ``Gemfile`` qui en a plusieurs) ;
- le ``Gemfile.lock`` range chaque gem dans la section ``GEM`` de son serveur (``remote:``) : une
  indirecte tirée par une gem privée y est avec elle ;
- un miroir (``bundle config set --global mirror.https://rubygems.org https://…`` :
  ``BUNDLE_MIRROR__HTTPS://RUBYGEMS__ORG/``) remplace une source : Bundler demande le miroir, et le
  lockfile garde l'adresse de la source ;
- les identifiants d'une source, ``nom:mot de passe`` envoyés en Basic : ceux écrits dans son
  adresse (``https://nom:secret@hôte``), sinon la clé de son adresse exacte (``bundle config set
  --global https://gems.corp.example/ …`` : ``BUNDLE_HTTPS://GEMS__CORP__EXAMPLE/``), sinon celle de
  son hôte (``BUNDLE_GEMS__CORP__EXAMPLE`` : tous ses ports, tous ses chemins). Chaque clé est
  cherchée dans la configuration du projet (``.bundle/config``, ou ``$BUNDLE_APP_CONFIG/config``),
  puis l'environnement, puis celle de la personne (``BUNDLE_CONFIG``, ``BUNDLE_USER_CONFIG``,
  ``$BUNDLE_USER_HOME/config``, sinon ``~/.bundle/config``). Dans une clé, ``.`` s'écrit ``__`` et
  ``-`` ``___``.

L'aiguillage (``routing``) :

- une gem d'un bloc, d'une option ``source:`` ou d'une autre section ``GEM`` du lockfile que celle
  de la source globale est **privée par son nom** : demandée à son serveur seul (son index compact,
  ``registries.rubygems.GemServer``), jamais à rubygems.org ni à OSV ;
- les autres, à la source globale : rubygems.org, ou le serveur qui le remplace (un miroir de la
  configuration, une autre source globale), à qui elles sont demandées, et à OSV (un miroir sert les
  gems publiques).

Une source qui n'est pas une adresse http(s) (un dossier) n'est pas lue.
"""

import dataclasses
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote_plus, urlsplit, urlunsplit

from forceupdate import userfiles
from forceupdate.models import Dependency, Notice, Project
from forceupdate.net.auth import Credential, basic, bound_or_none, may_carry_secret, split_userinfo
from forceupdate.parsers import ruby
from forceupdate.parsers.base import ParseError, ReadText
from forceupdate.parsers.lockfiles import join
from forceupdate.routing import Declared, Reading, Route, Router, User

GEMFILES = tuple(ruby.MANIFESTS)
LOCKFILES = tuple(ruby.MANIFESTS.values())
USER_CONFIG = "~/.bundle/config"
RUBYGEMS = "https://rubygems.org/"

_LINE = re.compile(
    r"""^(?P<key>[^#\s][^#]*?):(?=\s|$)[ ]?(?P<quote>['"]?)(?P<value>.*)(?P=quote)$"""
)
"""Une ligne ``CLÉ: "valeur"`` de la configuration de Bundler (``Gem::YAMLSerializer``)."""
_MIRROR = re.compile(r"^mirror\.(?P<uri>all|.+?)(?P<fallback>\.fallback_timeout)?/?$")


@dataclass(frozen=True, kw_only=True)
class Setting:
    """Une valeur de la configuration de Bundler, et d'où elle vient (pour les remarques)."""

    value: str
    source: str


@dataclass(kw_only=True)
class BundlerSettings:
    """La configuration de Bundler, par ordre de priorité : celle du projet, l'environnement, celle
    de la personne. Les clés comme Bundler les range (``BUNDLE_GEMS__CORP__EXAMPLE``)."""

    layers: list[tuple[str, dict[str, str]]] = field(default_factory=list)
    """(d'où, {clé: valeur}) ; pour l'environnement, ``d'où`` est vide : la variable le dit."""

    def get(self, name: str) -> Setting | None:
        """La valeur de ``name`` (``gems.corp.example``, ``https://gems.corp.example/``)."""
        key = settings_key(name)
        for source, values in self.layers:
            if key in values:
                return Setting(value=values[key], source=source or key)
        return None

    def mirror(self, url: str) -> Setting | None:
        """Le miroir de la source ``url`` (``mirror.<adresse>``, ``mirror.<hôte>``,
        ``mirror.all``) ; ``None`` sans miroir."""
        mirrors: dict[str, Setting] = {}
        for source, values in reversed(self.layers):
            for key, value in values.items():
                match = _MIRROR.match(_setting_name(key))
                if match is None or match.group("fallback"):
                    continue
                uri = match.group("uri")
                if uri != "all" and "://" in uri:
                    uri = _normalize(uri)
                mirrors[uri] = Setting(value=value, source=source or key)
        if "all" in mirrors:
            return mirrors["all"]
        normalized = _normalize(url).lower()
        return mirrors.get(normalized) or mirrors.get(urlsplit(normalized).hostname or "")


def settings_key(name: str) -> str:
    """La clé de ``name`` dans la configuration de Bundler (``Settings.key_for``) : une adresse
    finie par ``/``, ``.`` → ``__``, ``-`` → ``___``, en majuscules, après ``BUNDLE_``."""
    if name.lower().startswith(("http", "mirror.http")):
        name = _normalize(name)
    return "BUNDLE_" + name.replace(".", "__").replace("-", "___").upper()


def _setting_name(key: str) -> str:
    """Le nom d'une clé (``Settings#all``) : ``BUNDLE_MIRROR__HTTPS://RUBYGEMS__ORG/`` →
    ``mirror.https://rubygems.org/``."""
    return key.removeprefix("BUNDLE_").replace("___", "-").replace("__", ".").lower()


def _normalize(url: str) -> str:
    """Une adresse finie par ``/`` (``URINormalizer.normalize_suffix``)."""
    return url if url.endswith("/") else f"{url}/"


def parse_settings(text: str) -> dict[str, str]:
    """Les clés d'un fichier de configuration de Bundler, comme ``Settings#load_config`` les range :
    les valeurs telles qu'écrites entre leurs guillemets (coupées à un ``#``), une adresse finie par
    ``/``, ``.`` → ``__``, ``-`` → ``___``."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        match = _LINE.match(line)
        if match is None:
            continue
        key, value = match.group("key").strip(), match.group("value")
        if not value and not match.group("quote"):
            continue  # une table : pas une valeur
        if "#" in value and not value.startswith("#"):
            value = value.split("#", 1)[0].strip()
        if re.search(r"https?:", key, re.IGNORECASE) and not key.endswith("/"):
            key += "/"
        found[key.replace(".", "__").replace("-", "___")] = value
    return found


def read(project: Project, read_text: ReadText, user: User) -> Reading | None:
    """L'aiguillage des gems de ``project`` (voir la docstring du module)."""
    manifest = next((m for m in project.manifests if posixpath.basename(m) in GEMFILES), None)
    lock = next((p for p in project.lockfiles if posixpath.basename(p) in LOCKFILES), None)
    gemfile = _gemfile(read_text, manifest)
    remotes = _remotes(read_text, lock)
    if gemfile is None and not remotes:
        return None
    reader = _Reader(
        project=project,
        settings=_settings(project, read_text, user),
        manifest=manifest or "",
        lock=lock or "",
    )
    sources = dict(gemfile.sources) if gemfile is not None else {}
    found = gemfile.global_sources if gemfile is not None else ()
    if len(found) > 1:
        reader.notices.append(
            Notice(
                file=reader.manifest,
                message=(
                    f"{len(found)} sources globales : Bundler n'en accepte qu'une (les autres "
                    "doivent avoir un bloc do) ; la première est prise."
                ),
            )
        )
    global_url = found[0] if found else None
    urls = [*sources.values(), *remotes.values(), *([global_url] if global_url else [])]
    if (
        all(ruby.is_rubygems(url) for url in urls)
        and reader.settings.mirror(RUBYGEMS) is None
        and not reader.notices
    ):
        return None
    return Reading(
        router=reader.router(sources, remotes, global_url),
        credentials=reader.credentials,
        notices=reader.notices,
    )


@dataclass(kw_only=True)
class _Reader:
    project: Project
    settings: BundlerSettings
    manifest: str
    lock: str
    credentials: list[Credential] = field(default_factory=list)
    notices: list[Notice] = field(default_factory=list)
    _declared: dict[str, Declared] = field(default_factory=dict)

    def router(
        self, sources: dict[str, str], remotes: dict[str, str], global_url: str | None
    ) -> Router:
        global_route = self.global_route(global_url)

        def source_route(name: str) -> Route:
            url, file = sources.get(name), self.manifest
            if url is None:
                url, file = remotes.get(name), self.lock
            if url is None or (global_url is not None and _same(url, global_url)):
                return global_route
            if ruby.is_rubygems(url):
                return self.rubygems_route()
            declared = self.declared(url, file)
            if declared is None:
                return Route(
                    public=False,
                    private=True,
                    unchecked=(
                        f"Non vérifié : la source de {name} dans {file} n'est pas un serveur "
                        "http(s)"
                    ),
                )
            return Route(registries=(declared,), public=False, private=True, attached=True)

        def route(dependency: Dependency) -> Route:
            found = source_route(dependency.name)
            if dependency.unverifiable_reason not in (None, ruby.REASON_OTHER_SOURCE):
                # Une gem git, locale, d'une autre plateforme : son serveur dit seulement si elle
                # est privée (OSV n'a pas à apprendre son nom).
                return dataclasses.replace(found, attached=False, unchecked=None)
            return found

        return route

    def global_route(self, url: str | None) -> Route:
        if url is None or ruby.is_rubygems(url):
            return self.rubygems_route()
        declared = self.declared(url, self.manifest)
        if declared is None:
            return Route(
                public=False,
                unchecked=(
                    f"Non vérifié : la source de {self.manifest} n'est pas un serveur http(s) ; "
                    "forceupdate ne demande pas rubygems.org à sa place"
                ),
            )
        return Route(registries=(declared,), public=False, attached=True)

    def rubygems_route(self) -> Route:
        mirror = self.settings.mirror(RUBYGEMS)
        if mirror is None:
            return Route(attached=True)
        declared = self.declared(RUBYGEMS, self.manifest)
        if declared is None:
            return Route(
                public=False,
                unchecked=(
                    f"Non vérifié : le miroir de rubygems.org ({mirror.source}) n'est pas un "
                    "serveur http(s) ; forceupdate ne demande pas rubygems.org à sa place"
                ),
            )
        return Route(registries=(declared,), public=False, attached=True)

    def declared(self, url: str, file: str) -> Declared | None:
        """Le serveur à demander pour la source ``url`` (son miroir s'il en a un), avec ses
        identifiants ; ``None`` si ce n'est pas une adresse http(s)."""
        if url in self._declared:
            return self._declared[url]
        target, where = url.strip(), file
        mirror = self.settings.mirror(split_userinfo(target)[0])
        if mirror is not None:
            target, where = mirror.value.strip(), mirror.source
        clean, userinfo = split_userinfo(target)
        if urlsplit(clean).scheme.lower() not in ("http", "https"):
            return None
        declared = Declared(url=clean.rstrip("/"), file=where)
        self._declared[url] = declared
        self.credential(clean, userinfo, where)
        return declared

    def credential(self, url: str, userinfo: tuple[str, str] | None, file: str) -> None:
        """L'identifiant de la source ``url`` : celui de son adresse, sinon de la configuration
        (son adresse exacte, sinon son hôte)."""
        url = _normalize(url)
        host = (urlsplit(url).hostname or "").lower()
        if userinfo is not None and userinfo[0]:
            value, source, bound = basic(*userinfo), file, True
        else:
            setting = self.settings.get(_without_query(url))
            bound = setting is not None
            if setting is None:
                setting = self.settings.get(host)
            if setting is None:
                return
            username, _, password = setting.value.partition(":")
            value, source = basic(unquote_plus(username), unquote_plus(password)), setting.source
        if not may_carry_secret(url):
            self.notices.append(
                Notice(
                    file=file,
                    message=(
                        f"L'identifiant de Bundler pour {host} n'est pas envoyé : la source est en "
                        "http, forceupdate n'envoie un identifiant qu'en https (ou vers la machine "
                        "elle-même)."
                    ),
                )
            )
            return
        if bound:
            credential = bound_or_none(url, value=value, source=source)
        else:
            credential = Credential(host=host, any_port=True, value=value, source=source)
        if credential is not None:
            self.credentials.append(credential)


def _same(first: str, second: str) -> bool:
    """Vrai pour deux écritures de la même source (identifiants, ``/`` final, casse de l'hôte)."""

    def key(url: str) -> str:
        clean = split_userinfo(url.strip())[0]
        parts = urlsplit(_normalize(clean))
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, "", ""))

    return key(first) == key(second)


def _without_query(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _gemfile(read_text: ReadText, path: str | None) -> ruby.Gemfile | None:
    text = _read(read_text, path)
    return None if text is None or path is None else ruby.read_gemfile(path, text)


def _remotes(read_text: ReadText, path: str | None) -> dict[str, str]:
    text = _read(read_text, path)
    if text is None or path is None:
        return {}
    try:
        return dict(ruby.parse_gemfile_lock(path, text).remotes)
    except ParseError:
        return {}


def _read(read_text: ReadText, path: str | None) -> str | None:
    if path is None:
        return None
    try:
        return read_text(path)
    except ValueError:
        return None


def _settings(project: Project, read_text: ReadText, user: User) -> BundlerSettings:
    """La configuration de Bundler pour ``project`` : la sienne, l'environnement, la personne."""
    layers: list[tuple[str, dict[str, str]]] = []
    app_config = userfiles.env("BUNDLE_APP_CONFIG")
    if app_config is not None and Path(app_config).is_absolute():
        local = user.memo(f"bundler:{app_config}", lambda: _personal(Path(app_config) / "config"))
        layers.append(("$BUNDLE_APP_CONFIG/config", local))
    else:
        path = join(project.path, posixpath.join(app_config or ".bundle", "config"))
        text = _read(read_text, path)
        layers.append((path, parse_settings(text) if text else {}))
    environment = {k: v for k, v in userfiles.environ().items() if k.startswith("BUNDLE_") and v}
    layers.append(("", environment))
    label, personal = user.memo("bundler:global", _global_settings)
    layers.append((label, personal))
    return BundlerSettings(layers=layers)


def _global_settings() -> tuple[str, dict[str, str]]:
    """La configuration de Bundler de la personne (``Settings#global_config_file``)."""
    for variable in ("BUNDLE_CONFIG", "BUNDLE_USER_CONFIG"):
        configured = userfiles.env(variable)
        if configured is not None:
            return f"${variable}", _personal(Path(configured))
    user_home = userfiles.env("BUNDLE_USER_HOME")
    if user_home is not None:
        return "$BUNDLE_USER_HOME/config", _personal(Path(user_home) / "config")
    return USER_CONFIG, _personal(userfiles.home() / ".bundle" / "config")


def _personal(path: Path) -> dict[str, str]:
    text = userfiles.read(path)
    return parse_settings(text) if text else {}
