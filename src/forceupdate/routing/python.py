"""Les index Python déclarés (E33) : ceux de uv, de Poetry, de PDM, de Pipenv et de pip.

L'outil du projet décide de la configuration lue :

- **uv** (un script PEP 723, ``uv.lock``, ``[tool.uv]``, ``uv.toml``) : ``[[tool.uv.index]]``
  (``name``, ``url``, ``default``, ``explicit``) du ``pyproject.toml``, du ``uv.toml`` du projet
  ou du bloc d'un script, et les anciennes clés ``index-url``, ``extra-index-url`` ; puis
  l'environnement (``UV_INDEX``, ``UV_EXTRA_INDEX_URL``, ``UV_DEFAULT_INDEX``, ``UV_INDEX_URL``) et
  le ``uv.toml`` de la personne. Comme uv : les index dans l'ordre, le premier qui a le paquet
  l'emporte, PyPI (ou l'index ``default``) en dernier ; un index ``explicit`` ne sert que les
  paquets qui lui sont rattachés (``[tool.uv.sources]``, ``{ index = … }``) ;
- **Poetry** (``[tool.poetry]``) : ``[[tool.poetry.source]]`` (``priority`` : ``primary``,
  ``supplemental``, ``explicit`` ; les anciennes ``default`` et ``secondary``) et ``source =`` d'une
  dépendance ; une source ``primary`` retire PyPI, sauf une source nommée ``PyPI`` ;
- **PDM** (``[tool.pdm]``) : ``[[tool.pdm.source]]`` (``include_packages`` réserve des paquets à la
  source ; ``type = "find_links"`` n'est pas un index) ; une source nommée ``pypi`` remplace PyPI ;
- **Pipenv** (``Pipfile``) : ``[[source]]``, la première est l'index par défaut, les autres en
  plus ; ``index =`` d'un paquet ;
- **pip** (des ``requirements``) : ``--index-url``, ``--extra-index-url``, ``--no-index`` des
  fichiers, puis ``PIP_INDEX_URL``, ``PIP_EXTRA_INDEX_URL``, et le ``pip.ini`` ou ``pip.conf`` de la
  personne (``PIP_CONFIG_FILE``, ou son dossier de configuration).

Un paquet rattaché à un index (uv, Poetry, Pipenv, ``include_packages`` de PDM) est **privé par
son nom** : demandé à cet index seul, jamais à PyPI ni à OSV. Le parseur le dit « venu de
l'index … » (``parsers.python.attached_index``) ; l'aiguillage le rend vérifiable
(``Route.attached``). Un index nommé ``pypi`` (ou à l'adresse de PyPI) est PyPI.

Les identifiants : ceux écrits dans l'adresse d'un index (``https://nom:secret@hôte/simple``) et
``.netrc`` (uv et pip le lisent). ``UV_INDEX_<NOM>_USERNAME`` et ``_PASSWORD`` vont à l'adresse que
la personne donne à ce nom (``UV_INDEX``, son ``uv.toml``), jamais à celle d'un fichier du projet
(une remarque le dit). Ceux de Poetry (``http-basic.<nom>``) ne sont pas utilisés.
"""

import configparser
import posixpath
import re
import sys
import tomllib
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from packaging.utils import canonicalize_name

from forceupdate import userfiles
from forceupdate.models import Dependency, Notice, Project
from forceupdate.net.auth import Credential, basic, bound_or_none, split_userinfo
from forceupdate.parsers import python
from forceupdate.parsers.base import ParseError, ReadText
from forceupdate.routing import PUBLIC, Declared, Reading, Route, Router, User
from forceupdate.routing.netrc import netrc_credentials

PYPI_HOSTS = frozenset({"pypi.org", "pypi.python.org"})


@dataclass(frozen=True, kw_only=True)
class Index:
    """Un index déclaré : son nom (s'il en a un), son adresse, le fichier qui le déclare."""

    name: str | None
    url: str
    file: str
    explicit: bool = False
    personal: bool = False
    """Déclaré par la personne (son environnement, son ``uv.toml``), pas par le projet."""

    @property
    def pypi(self) -> bool:
        parts = urlsplit(self.url)
        return (parts.hostname or "").lower() in PYPI_HOSTS or (self.name or "").lower() == "pypi"

    def declared(self) -> Declared:
        return Declared(url=self.url, file=self.file)


@dataclass(kw_only=True)
class PythonConfig:
    """Les index d'un projet : ceux à demander d'abord (dans l'ordre), celui qui remplace PyPI,
    ceux qui ne servent que les paquets rattachés, et ce qu'il faut en dire."""

    indexes: list[Index] = field(default_factory=list)
    default: Index | None = None
    named: dict[str, Index] = field(default_factory=dict)
    """Tous les index nommés, par nom en minuscules (``explicit`` compris)."""
    include: list[tuple[tuple[str, ...], str]] = field(default_factory=list)
    """PDM : des motifs de paquets, et la source qui leur est réservée."""
    pypi: bool = True
    """PyPI reste-t-il (une source ``primary`` de Poetry le retire) ?"""
    no_index: str | None = None
    """Le fichier qui dit ``--no-index`` (pip : aucun index, des fichiers locaux)."""
    unreadable: str | None = None
    """Un index dont l'adresse ne se lit pas (une variable) : rien n'est demandé."""
    credentials: list[Credential] = field(default_factory=list)
    notices: list[Notice] = field(default_factory=list)

    def add(self, index: Index | None) -> None:
        if index is None:
            return
        if index.name:
            self.named.setdefault(index.name.lower(), index)
        if not index.explicit and all(i.url != index.url for i in self.indexes):
            self.indexes.append(index)

    def index(
        self,
        url: str,
        file: str,
        *,
        name: str | None = None,
        personal: bool,
        explicit: bool = False,
    ) -> Index | None:
        """L'index d'adresse ``url`` (ses identifiants écrits dedans deviennent un identifiant lié
        à lui) ; ``None`` si l'adresse ne se lit pas (dit)."""
        url = url.strip()
        if personal:
            url = userfiles.expand(url) or ""
        clean, userinfo = split_userinfo(url)
        if userfiles.unexpanded(urlsplit(clean).netloc) or urlsplit(clean).scheme not in (
            "http",
            "https",
        ):
            self.unreadable = self.unreadable or file
            what = f"de l'index « {name} »" if name else "d'un index"
            message = f"l'adresse {what} ne se lit pas (une variable ?)."
            self.notices.append(Notice(file=file, message=message))
            return None
        if userinfo is not None and userinfo[0]:
            if not personal and (
                userfiles.unexpanded(userinfo[0]) or userfiles.unexpanded(userinfo[1])
            ):
                message = (
                    f"les identifiants de l'index « {name or urlsplit(clean).hostname} » utilisent "
                    "une variable d'environnement : forceupdate ne développe jamais celles d'un "
                    "fichier du projet. Les mettre dans ~/.netrc."
                )
                self.notices.append(Notice(file=file, message=message))
            else:
                credential = bound_or_none(clean, value=basic(*userinfo), source=file)
                if credential is not None:
                    self.credentials.append(credential)
        return Index(
            name=name, url=clean.rstrip("/"), file=file, explicit=explicit, personal=personal
        )


def read(project: Project, read_text: ReadText, user: User) -> Reading | None:
    """L'aiguillage des paquets Python de ``project``."""
    files = {posixpath.basename(path): path for path in project.manifests}
    pyproject = _toml(read_text, files.get("pyproject.toml"))
    tool = pyproject.get("tool") if isinstance(pyproject.get("tool"), dict) else {}
    config = PythonConfig()
    script = next((p for p in project.manifests if python.is_script(p)), None)
    if script is not None:
        _uv(config, _script_tool(read_text, script).get("uv"), script, read_text, project, user)
    elif "poetry" in tool:
        _poetry(config, tool["poetry"], files["pyproject.toml"])
    elif "pdm" in tool:
        _pdm(config, tool["pdm"], files["pyproject.toml"])
    elif "Pipfile" in files:
        _pipfile(config, _toml(read_text, files["Pipfile"]), files["Pipfile"])
    elif _uses_uv(project, tool, read_text):
        _uv(config, tool.get("uv"), files.get("pyproject.toml", ""), read_text, project, user)
    else:
        _pip(config, project, read_text, user)
    attached = _attached(project)
    declared = config.indexes or config.default or config.named or config.include
    if not (declared or attached or config.no_index or config.unreadable or config.notices):
        return None
    if config.indexes or config.default or config.named:
        config.credentials += netrc_credentials(user)
    return Reading(
        router=_router(config, attached), credentials=config.credentials, notices=config.notices
    )


def _attached(project: Project) -> dict[str, str]:
    """Les paquets que les manifestes rattachent à un index (nom normalisé → nom de l'index)."""
    found = {}
    for dependency in project.dependencies:
        index = python.attached_index(dependency.unverifiable_reason)
        if index is not None:
            found.setdefault(canonicalize_name(dependency.name), index)
    return found


def _router(config: PythonConfig, attached: dict[str, str]) -> Router:
    def route(dependency: Dependency) -> Route:
        if config.unreadable is not None:
            return Route(
                public=False,
                unchecked=(
                    f"Non vérifié : l'adresse d'un index de {config.unreadable} ne se lit pas ; il "
                    "pourrait servir ce paquet"
                ),
            )
        name = canonicalize_name(dependency.name)
        wanted = attached.get(name)
        if wanted is not None:
            index = config.named.get(wanted.lower())
            if index is None:
                # L'index n'est pas déclaré : la dépendance reste « Non vérifiable : vient de
                # l'index … » (le parseur), et privée : son nom ne part pas chez OSV (E35 : le
                # message « non vérifié » d'ici ne pouvait pas sortir).
                return Route(public=False, private=True)
            if index.pypi:
                return Route(attached=True)
            return Route(registries=(index.declared(),), public=False, private=True, attached=True)
        for patterns, source in config.include:
            if any(fnmatchcase(name, re.sub(r"[-_.]+", "-", p.lower())) for p in patterns):
                index = config.named.get(source.lower())
                if index is not None and not index.pypi:
                    return Route(registries=(index.declared(),), public=False, private=True)
        if config.no_index is not None:
            return Route(
                public=False,
                unchecked=(
                    f"Non vérifié : {config.no_index} dit --no-index, pip prend les paquets dans "
                    "des fichiers locaux"
                ),
            )
        first = tuple(i.declared() for i in config.indexes if not i.pypi)
        default = config.default
        public = config.pypi and (default is None or default.pypi)
        if default is not None and not default.pypi:
            first += (default.declared(),)
        if not first:
            return PUBLIC
        return Route(registries=first, public=public)

    return route


# -- lecture des fichiers --------------------------------------------------------------


def _toml(read_text: ReadText, path: str | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        text = read_text(path)
        return tomllib.loads(text) if text is not None else {}
    except (ValueError, tomllib.TOMLDecodeError):
        return {}


def _script_tool(read_text: ReadText, path: str) -> dict[str, Any]:
    try:
        text = read_text(path)
        block = python.script_block(text or "")
        data = tomllib.loads(block.toml) if block is not None else {}
    except (ValueError, ParseError, tomllib.TOMLDecodeError):
        return {}
    tool = data.get("tool")
    return tool if isinstance(tool, dict) else {}


def _uses_uv(project: Project, tool: dict[str, Any], read_text: ReadText) -> bool:
    if "uv" in tool or any(posixpath.basename(p) == "uv.lock" for p in project.lockfiles):
        return True
    return _toml(read_text, _join(project.path, "uv.toml")) != {}


def _join(directory: str, name: str) -> str:
    return name if directory in (".", "") else posixpath.join(directory, name)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return value.split()
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


# -- uv --------------------------------------------------------------------------------


def _uv(
    config: PythonConfig,
    table: Any,
    file: str,
    read_text: ReadText,
    project: Project,
    user: User,
) -> None:
    """La configuration de uv : l'environnement, le projet (``table``, puis ``uv.toml``), la
    personne. Les premiers déclarés sont demandés d'abord."""
    environment = userfiles.environ()
    for variable in ("UV_INDEX", "UV_EXTRA_INDEX_URL"):
        for entry in (environment.get(variable) or "").split():
            name, separator, url = entry.partition("=")
            if not separator or "://" in name:
                name, url = None, entry
            config.add(config.index(url, variable, name=name, personal=True))
    for variable in ("UV_DEFAULT_INDEX", "UV_INDEX_URL"):
        if environment.get(variable) and config.default is None:
            config.default = config.index(environment[variable], variable, personal=True)
    tables = [(table, file, False)]
    project_uv = _toml(read_text, _join(project.path, "uv.toml"))
    if project_uv:
        tables.append((project_uv, _join(project.path, "uv.toml"), False))
    personal = user.memo("python.uv", _personal_uv)
    if personal:
        tables.append((personal, "uv.toml (de la personne)", True))
    for data, source, is_personal in tables:
        if not isinstance(data, dict):
            continue
        for entry in data.get("index") if isinstance(data.get("index"), list) else []:
            if not isinstance(entry, dict) or not isinstance(entry.get("url"), str):
                continue
            name = entry.get("name") if isinstance(entry.get("name"), str) else None
            index = config.index(
                entry["url"],
                source,
                name=name,
                personal=is_personal,
                explicit=entry.get("explicit") is True,
            )
            if index is not None and entry.get("default") is True:
                config.default = config.default or index
                if index.name:
                    config.named.setdefault(index.name.lower(), index)
            else:
                config.add(index)
        for url in _strings(data.get("extra-index-url")):
            config.add(config.index(url, source, personal=is_personal))
        default = data.get("index-url")
        if isinstance(default, str) and config.default is None:
            config.default = config.index(default, source, personal=is_personal)
    _uv_named_credentials(config, environment)


def _personal_uv() -> dict[str, Any]:
    candidates = [userfiles.xdg_config_home() / "uv" / "uv.toml"]
    if sys.platform == "win32":
        candidates.insert(0, userfiles.config_home() / "uv" / "uv.toml")
    for path in candidates:
        text = userfiles.read(path)
        if text is not None:
            try:
                return tomllib.loads(text)
            except tomllib.TOMLDecodeError:
                return {}
    return {}


def _uv_named_credentials(config: PythonConfig, environment: Any) -> None:
    """``UV_INDEX_<NOM>_USERNAME`` et ``_PASSWORD``, rattachés au nom d'un index : envoyés à
    l'adresse que la personne donne à ce nom (son environnement, son ``uv.toml``), comme Cargo ;
    jamais à celle d'un fichier du projet (un dépôt recevrait sinon l'identifiant en déclarant
    ce nom avec l'adresse de son choix) : dit (E35 : jamais envoyés)."""
    for name, index in config.named.items():
        key = re.sub(r"[^A-Za-z0-9]", "_", name).upper()
        variable = f"UV_INDEX_{key}_PASSWORD"
        password = environment.get(variable)
        if not password:
            continue
        if not index.personal:
            message = (
                f"{variable} est rattaché au nom « {name} », dont l'adresse vient d'un fichier du "
                "projet : pas envoyé. Déclarer cet index aussi chez soi (UV_INDEX, son uv.toml), "
                "ou mettre l'identifiant de cet hôte dans ~/.netrc."
            )
            config.notices.append(Notice(file=index.file, message=message))
            continue
        username = environment.get(f"UV_INDEX_{key}_USERNAME") or ""
        credential = bound_or_none(index.url, value=basic(username, password), source=variable)
        if credential is not None:
            config.credentials.append(credential)


# -- Poetry, PDM, Pipenv -------------------------------------------------------------------


def _poetry(config: PythonConfig, table: Any, file: str) -> None:
    sources = table.get("source") if isinstance(table, dict) else None
    primary_seen = False
    pypi_named = False
    supplemental = []
    for entry in sources if isinstance(sources, list) else []:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            continue
        name = entry["name"]
        priority = entry.get("priority")
        if priority is None:
            priority = (
                "default"
                if entry.get("default") is True
                else "supplemental"
                if entry.get("secondary") is True
                else "primary"
            )
        if name.lower() == "pypi":
            pypi_named = True
            continue
        if not isinstance(entry.get("url"), str):
            continue
        explicit = priority == "explicit"
        index = config.index(entry["url"], file, name=name, personal=False, explicit=explicit)
        if index is None:
            continue
        if priority == "default":
            config.default = config.default or index
            config.named.setdefault(name.lower(), index)
        elif priority == "supplemental":
            supplemental.append(index)
            config.named.setdefault(name.lower(), index)
        else:
            primary_seen = primary_seen or priority == "primary"
            config.add(index)
    for index in supplemental:
        config.add(index)
    if primary_seen and not pypi_named:
        config.pypi = False  # une source « primary » retire PyPI


def _pdm(config: PythonConfig, table: Any, file: str) -> None:
    sources = table.get("source") if isinstance(table, dict) else None
    for entry in sources if isinstance(sources, list) else []:
        if not isinstance(entry, dict) or not isinstance(entry.get("url"), str):
            continue
        if entry.get("type") == "find_links":
            continue
        name = entry.get("name") if isinstance(entry.get("name"), str) else None
        index = config.index(entry["url"], file, name=name, personal=False)
        if index is None:
            continue
        include = tuple(_strings(entry.get("include_packages")))
        if (name or "").lower() == "pypi":
            config.default = index
            config.named.setdefault("pypi", index)
        elif include:
            config.named.setdefault((name or index.url).lower(), index)
            config.include.append((include, name or index.url))
        else:
            config.add(index)


def _pipfile(config: PythonConfig, data: dict[str, Any], file: str) -> None:
    sources = data.get("source")
    for position, entry in enumerate(sources if isinstance(sources, list) else []):
        if not isinstance(entry, dict) or not isinstance(entry.get("url"), str):
            continue
        name = entry.get("name") if isinstance(entry.get("name"), str) else None
        index = config.index(entry["url"], file, name=name, personal=False)
        if index is None:
            continue
        if position == 0:
            config.default = index
            if name:
                config.named.setdefault(name.lower(), index)
        else:
            config.add(index)


# -- pip -------------------------------------------------------------------------------


def _pip(config: PythonConfig, project: Project, read_text: ReadText, user: User) -> None:
    """pip : les options des ``requirements`` (et des fichiers qu'ils citent), puis
    l'environnement, puis la configuration de la personne."""
    seen: set[str] = set()
    todo = [p for p in project.manifests if p.endswith((".txt", ".in"))]
    todo += [p for p in project.lockfiles if p.endswith(".txt")]
    while todo:
        path = todo.pop(0)
        if path in seen:
            continue
        seen.add(path)
        try:
            text = read_text(path)
        except ValueError:
            text = None
        if text is None:
            continue
        for option, argument in python.requirements_options(text):
            if option == "--index-url" and argument:
                index = config.index(argument, path, personal=False)
                config.default = config.default or index
            elif option == "--extra-index-url" and argument:
                config.add(config.index(argument, path, personal=False))
            elif option == "--no-index":
                config.no_index = config.no_index or path
        todo += python.requirements_references(path, text)
    environment = userfiles.environ()
    if environment.get("PIP_INDEX_URL") and config.default is None:
        config.default = config.index(environment["PIP_INDEX_URL"], "PIP_INDEX_URL", personal=True)
    for url in (environment.get("PIP_EXTRA_INDEX_URL") or "").split():
        config.add(config.index(url, "PIP_EXTRA_INDEX_URL", personal=True))
    personal = user.memo("python.pip", _personal_pip)
    if personal.get("index-url") and config.default is None:
        config.default = config.index(personal["index-url"], "pip.conf", personal=True)
    for url in personal.get("extra-index-url", "").split():
        config.add(config.index(url, "pip.conf", personal=True))


def _personal_pip() -> dict[str, str]:
    """``index-url`` et ``extra-index-url`` du fichier de configuration de pip de la personne
    (``[global]``, puis ``[install]``)."""
    configured = userfiles.env("PIP_CONFIG_FILE")
    if configured:
        candidates = [Path(configured)]
    elif sys.platform == "win32":
        candidates = [userfiles.config_home() / "pip" / "pip.ini"]
    else:
        candidates = [
            userfiles.xdg_config_home() / "pip" / "pip.conf",
            userfiles.home() / ".pip" / "pip.conf",
        ]
        if sys.platform == "darwin":
            candidates.insert(0, userfiles.config_home() / "pip" / "pip.conf")
    found: dict[str, str] = {}
    for path in candidates:
        text = userfiles.read(path)
        if text is None:
            continue
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read_string(text)
        except configparser.Error:
            continue
        for section in ("global", "install"):
            for key in ("index-url", "extra-index-url"):
                if parser.has_option(section, key):
                    found[key] = parser.get(section, key)
        if found:
            return found
    return found
