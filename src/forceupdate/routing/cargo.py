"""Les registres de Cargo (E34) : ``registry = "…"`` d'une dépendance, les sources d'un
``Cargo.lock``, et crates.io remplacé par un miroir, avec les jetons de Cargo.

Vérifié le 2026-11-02 avec cargo 1.99.1 et un registre « sparse » local qui exige un jeton :

- un registre se déclare par son nom : ``[registries.<nom>] index = "sparse+https://…/"`` d'un
  ``.cargo/config.toml`` (celui du dossier du projet et de ses parents, puis celui de la personne,
  ``$CARGO_HOME/config.toml`` ; le plus proche l'emporte), ou ``CARGO_REGISTRIES_<NOM>_INDEX`` de
  l'environnement, qui passe devant ; dans un ``Cargo.toml``, ``registry = "<nom>"`` ;
- Cargo demande ``config.json`` à l'index, sans jeton : sur un 401, il renvoie la requête avec
  ``Authorization: <jeton>`` (le jeton seul, sans « Bearer »), puis lit le fichier du crate
  (``ac/me/acme-lib``, le chemin de l'index de crates.io) ;
- le jeton d'un registre : ``CARGO_REGISTRIES_<NOM>_TOKEN``, ``$CARGO_HOME/credentials.toml``
  (``[registries.<nom>] token``, ce qu'écrit ``cargo login``) ; Cargo 1.99 exige que le
  fournisseur ``cargo:token`` soit configuré (``[registry] global-credential-providers``) ;
- le ``Cargo.lock`` dit la source de chaque crate : ``source = "sparse+https://…/"`` pour un
  registre « sparse », celle de crates.io même derrière un miroir ;
- crates.io remplacé (``[source.crates-io] replace-with = "<nom>"``) : par un registre de
  ``[registries]`` (avec son jeton), une autre source (``[source.<nom>] registry = "…"``, sans
  jeton : Cargo refuse d'y en envoyer), ou des fichiers locaux (``directory``, ``local-registry`` :
  ceux de ``cargo vendor``, copies de crates.io).

L'aiguillage (``routing``) :

- une dépendance d'un registre nommé, ou d'une autre source que crates.io dans le lockfile, est
  **privée** : demandée à son index seul (``registries.crates.Crates`` à son adresse), jamais à
  crates.io ni à OSV. Un index git (``registry+…``, une adresse sans ``sparse+``) ne se lit pas
  sans le cloner : « non vérifié » ;
- les autres, à crates.io, ou au registre qui le remplace (et à OSV : un miroir sert des crates
  publics) ; des fichiers locaux à sa place ne changent rien (Cargo tient leur contenu pour
  celui de crates.io).

**Les jetons** sont rattachés à un *nom* : celui de la personne (l'environnement,
``credentials.toml``, son ``config.toml``) ne part que vers l'adresse que donne à ce nom un fichier
de la personne (son ``config.toml``, ``CARGO_REGISTRIES_<NOM>_INDEX``), jamais vers celle qu'un
fichier du projet lui donnerait ; un jeton écrit dans un fichier du projet, vers l'adresse que ce
fichier donne. Les jetons des autres fournisseurs (``cargo:wincred``, ``cargo:libsecret``, le
trousseau de macOS) ne sont pas lus.
"""

import posixpath
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from forceupdate import userfiles
from forceupdate.models import Dependency, Notice, Project
from forceupdate.net.auth import Credential, bound_or_none, split_userinfo
from forceupdate.parsers import rust
from forceupdate.parsers.base import ReadText
from forceupdate.parsers.lockfiles import dirname, join
from forceupdate.routing import PUBLIC, Declared, Reading, Route, Router, User

CONFIG_NAMES = ("config", "config.toml")
"""Les fichiers de configuration d'un dossier ``.cargo`` : Cargo prend ``config`` s'il y a les
deux."""
USER_CONFIG = "$CARGO_HOME/config.toml"
USER_CREDENTIALS = "$CARGO_HOME/credentials.toml"
CRATES_IO = "crates-io"


@dataclass(frozen=True, kw_only=True)
class _Index:
    """L'index d'un registre : son adresse telle qu'écrite, le fichier qui la donne, et s'il est à
    la personne."""

    url: str
    file: str
    personal: bool

    @property
    def sparse(self) -> str | None:
        """Son adresse sans ``sparse+`` ni identifiants ; ``None`` pour un index git ou local."""
        if not self.url.startswith("sparse+"):
            return None
        clean = split_userinfo(self.url.removeprefix("sparse+"))[0]
        return clean if urlsplit(clean).scheme.lower() in ("http", "https") else None


@dataclass(kw_only=True)
class CargoConfig:
    """Ce que les configurations de Cargo disent des registres d'un projet."""

    layers: list[tuple[str, bool, dict[str, Any]]] = field(default_factory=list)
    """(fichier, de la personne, contenu), du plus proche au plus loin."""
    notices: list[Notice] = field(default_factory=list)
    credentials: list[Credential] = field(default_factory=list)

    def index(self, name: str, *, personal_only: bool = False) -> _Index | None:
        """L'index du registre ``name`` : l'environnement, puis le fichier le plus proche."""
        variable = f"CARGO_REGISTRIES_{_env_name(name)}_INDEX"
        value = userfiles.env(variable)
        if value is not None:
            return _Index(url=value.strip(), file=variable, personal=True)
        for file, personal, data in self.layers:
            if personal_only and not personal:
                continue
            found = _get(data, "registries", name, "index")
            if isinstance(found, str):
                return _Index(url=found.strip(), file=file, personal=personal)
        return None

    def source(self, name: str) -> dict[str, Any] | None:
        """La table ``[source.<name>]`` la plus proche."""
        for _, _, data in self.layers:
            found = _get(data, "source", name)
            if isinstance(found, dict):
                return found
        return None

    def source_file(self, name: str) -> str:
        return next((file for file, _, data in self.layers if _get(data, "source", name)), "")

    def names(self) -> set[str]:
        """Les registres que nomment les fichiers (``[registries]``, ``credentials.toml``)."""
        found = set((_credentials().get("registries") or {}).keys())
        for _, _, data in self.layers:
            found |= set((_get(data, "registries") or {}).keys())
        return {name for name in found if isinstance(name, str)}

    def token(self, name: str) -> tuple[str, str, bool] | None:
        """Le jeton du registre ``name`` : (jeton, d'où, de la personne). L'environnement, puis
        ``credentials.toml``, puis les fichiers de configuration (du plus proche au plus loin)."""
        variable = f"CARGO_REGISTRIES_{_env_name(name)}_TOKEN"
        value = userfiles.env(variable)
        if value is not None:
            return value, variable, True
        table = _get(_credentials(), "registries", name)
        if isinstance(table, dict) and isinstance(table.get("token"), str) and table["token"]:
            return table["token"], USER_CREDENTIALS, True
        for file, personal, data in self.layers:
            token = _get(data, "registries", name, "token")
            if isinstance(token, str) and token:
                return token, file, personal
        return None


def _env_name(name: str) -> str:
    """Le nom d'un registre dans une variable d'environnement (``my-reg`` → ``MY_REG``)."""
    return name.upper().replace("-", "_")


def _token_key(name: str) -> str:
    return f"CARGO_REGISTRIES_{_env_name(name)}_TOKEN"


def read(project: Project, read_text: ReadText, user: User) -> Reading | None:
    """L'aiguillage des crates de ``project`` (voir la docstring du module)."""
    config = CargoConfig(layers=_layers(project, read_text, user))
    sources = _lock_sources(project, read_text)
    # Lu avant que l'aiguillage ne rende ces dépendances vérifiables (``routing.apply`` efface leur
    # raison) : le crate → le nom de son registre.
    attached = {
        dependency.name: name
        for dependency in project.dependencies
        if (name := rust.registry_of(dependency.unverifiable_reason)) is not None
    }
    named = set(attached.values())
    private = {s for s in sources.values() if s not in rust.CRATES_IO_SOURCES and _registry(s)}
    replaced = config.source(CRATES_IO)
    if not (named or private or replaced):
        return None
    reader = _Reader(config=config, project=project)
    target = replaced.get("replace-with") if replaced is not None else None
    reader.read_tokens(named | ({target} if isinstance(target, str) else set()))
    return Reading(
        router=reader.router(attached, sources),
        credentials=config.credentials,
        notices=config.notices,
    )


def _registry(source: str) -> bool:
    return source.startswith(("sparse+", "registry+"))


@dataclass(kw_only=True)
class _Reader:
    config: CargoConfig
    project: Project

    def read_tokens(self, used: set[str]) -> None:
        """Les jetons de la personne et du projet, chacun lié à son adresse (voir la docstring du
        module) ; une remarque pour le jeton d'un registre utilisé qui ne peut pas partir."""
        config = self.config
        for name in sorted(config.names() | used):
            found = config.token(name)
            if found is None:
                continue
            token, source, personal = found
            effective = config.index(name)
            index = config.index(name, personal_only=True) if personal else effective
            url = index.sparse if index is not None and index.personal == personal else None
            if url is not None:
                credential = bound_or_none(_slash(url), value=token, source=source)
                if credential is not None:
                    config.credentials.append(credential)
            sent = url is not None and effective is not None and effective.sparse == url
            if name in used and personal and not sent:
                config.notices.append(Notice(file=source, message=_unbound(name)))

    def router(self, attached: dict[str, str], sources: dict[tuple[str, str], str]) -> Router:
        by_name: dict[str, str] = {}
        for (name, _), source in sources.items():
            by_name.setdefault(name, source)
        crates_io = self.crates_io()

        def route(dependency: Dependency) -> Route:
            reason = dependency.unverifiable_reason
            name = attached.get(dependency.name)
            if name is not None:
                return self.named(name)
            source = sources.get((dependency.name, dependency.installed or "")) or by_name.get(
                dependency.name
            )
            if source is not None and source not in rust.CRATES_IO_SOURCES and _registry(source):
                found = self.locked(source)
                if reason not in (None, rust.REASON_OTHER_REGISTRY):
                    return Route(public=False, private=True)
                return found
            return crates_io if reason is None else PUBLIC

        return route

    def named(self, name: str) -> Route:
        if name == CRATES_IO:
            return self.crates_io()
        index = self.config.index(name)
        if index is None:
            return Route(
                public=False,
                private=True,
                attached=True,
                unchecked=(
                    f"Privé : non vérifié : le registre « {name} » n'est déclaré dans aucun "
                    ".cargo/config.toml ni par CARGO_REGISTRIES_"
                    f"{_env_name(name)}_INDEX"
                ),
            )
        url = index.sparse
        if url is None:
            return Route(
                public=False, private=True, attached=True, unchecked=_git_index(name, index)
            )
        declared = Declared(url=url.rstrip("/"), file=index.file)
        return Route(registries=(declared,), public=False, private=True, attached=True)

    def locked(self, source: str) -> Route:
        lock = next(iter(self.project.lockfiles), rust.LOCKFILE)
        if not source.startswith("sparse+"):
            return Route(
                public=False,
                private=True,
                attached=True,
                unchecked=(
                    f"Privé : non vérifié : sa source dans {lock} est un index git, que "
                    "forceupdate ne lit pas (seulement les index « sparse »)"
                ),
            )
        url = _Index(url=source, file=lock, personal=False).sparse
        if url is None:
            return Route(public=False, private=True, attached=True, unchecked="Privé : non vérifié")
        declared = Declared(url=url.rstrip("/"), file=lock)
        return Route(registries=(declared,), public=False, private=True, attached=True)

    def crates_io(self) -> Route:
        """La route de crates.io : lui, ou ce qui le remplace (``replace-with``)."""
        name, seen = CRATES_IO, set()
        file = ""
        while (table := self.config.source(name)) is not None and name not in seen:
            seen.add(name)
            file = self.config.source_file(name) or file
            target = table.get("replace-with")
            if isinstance(target, str):
                name = target
                continue
            break
        if name == CRATES_IO:
            return PUBLIC
        table = self.config.source(name)
        if table is None:
            index = self.config.index(name)
        else:
            if "directory" in table or "local-registry" in table:
                return PUBLIC  # cargo vendor : des copies de crates.io
            registry = table.get("registry")
            index = (
                _Index(url=registry.strip(), file=file, personal=False)
                if isinstance(registry, str)
                else None
            )
        url = index.sparse if index is not None else None
        if url is None:
            return Route(
                public=False,
                unchecked=(
                    f"Non vérifié : crates.io est remplacé par « {name} » ({file}), un index que "
                    "forceupdate ne lit pas (seulement les index « sparse ») ; il ne demande pas "
                    "crates.io à sa place"
                ),
            )
        declared = Declared(url=url.rstrip("/"), file=index.file or file)
        return Route(registries=(declared,), public=False)


def _git_index(name: str, index: _Index) -> str:
    return (
        f"Privé : non vérifié : l'index du registre « {name} » ({index.file}) n'est pas un index "
        "« sparse » (un dépôt git), que forceupdate ne lit pas"
    )


def _unbound(name: str) -> str:
    return (
        f"Le jeton du registre « {name} » ne part que vers l'adresse que donne à ce nom un fichier "
        f"de la personne (son {USER_CONFIG}, ou CARGO_REGISTRIES_{_env_name(name)}_INDEX) : jamais "
        "vers celle d'un fichier du projet. L'y déclarer pour qu'il soit envoyé."
    )


def _slash(url: str) -> str:
    return url if url.endswith("/") else f"{url}/"


def _layers(
    project: Project, read_text: ReadText, user: User
) -> list[tuple[str, bool, dict[str, Any]]]:
    """Les configurations de Cargo, du plus proche au plus loin : le ``.cargo`` du dossier du
    projet et de ses parents dans la source, puis celui de la personne."""
    layers: list[tuple[str, bool, dict[str, Any]]] = []
    directory = project.path
    while True:
        for name in CONFIG_NAMES:
            path = join(directory, posixpath.join(".cargo", name))
            data = _toml(_read(read_text, path))
            if data is not None:
                layers.append((path, False, data))
                break
        if directory in (".", ""):
            break
        directory = dirname(directory)
    personal = user.memo("cargo:config", _personal_config)
    if personal is not None:
        layers.append((USER_CONFIG, True, personal))
    return layers


def cargo_home() -> Path:
    configured = userfiles.env("CARGO_HOME")
    return Path(configured) if configured else userfiles.home() / ".cargo"


def _personal_config() -> dict[str, Any] | None:
    for name in CONFIG_NAMES:
        data = _toml(userfiles.read(cargo_home() / name))
        if data is not None:
            return data
    return None


def _credentials() -> dict[str, Any]:
    for name in ("credentials.toml", "credentials"):
        data = _toml(userfiles.read(cargo_home() / name))
        if data is not None:
            return data
    return {}


def _lock_sources(project: Project, read_text: ReadText) -> dict[tuple[str, str], str]:
    """La source de chaque crate du ``Cargo.lock`` : (nom, version) → source."""
    lock = next((p for p in project.lockfiles if posixpath.basename(p) == rust.LOCKFILE), None)
    data = _toml(_read(read_text, lock)) if lock is not None else None
    found: dict[tuple[str, str], str] = {}
    for entry in (data or {}).get("package") or []:
        if not isinstance(entry, dict):
            continue
        name, version, source = entry.get("name"), entry.get("version"), entry.get("source")
        if isinstance(name, str) and isinstance(source, str):
            found[name, version if isinstance(version, str) else ""] = source
    return found


def _read(read_text: ReadText, path: str) -> str | None:
    try:
        return read_text(path)
    except ValueError:
        return None


def _toml(text: str | None) -> dict[str, Any] | None:
    if text is None:
        return None
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None


def _get(data: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data
