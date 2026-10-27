"""Les parseurs Python : manifestes, lockfiles, et le lien entre les deux.

Manifestes lus :

- ``requirements*.txt`` et ``requirements*.in`` (pip, pip-tools), avec les
  ``-r autre.txt`` et ``-c contraintes.txt`` suivis ;
- ``pyproject.toml`` : PEP 621 (``[project]``), PEP 735 (``[dependency-groups]``),
  Poetry, ``[build-system] requires``, et les dépendances de dev de uv et PDM ;
- ``Pipfile`` et ``setup.cfg``.

``setup.py`` n'est pas lu : il faudrait l'exécuter. Le projet reçoit une remarque.

Lockfiles lus : ``uv.lock``, ``poetry.lock``, ``pdm.lock``, ``Pipfile.lock``, et le
``requirements*.txt`` compilé par pip-tools à partir du ``.in`` du même nom.

Pour un projet (``parse_project``) :

- les dépendances directes sont celles des manifestes, avec leur contrainte telle
  qu'écrite et son emplacement exact (``Location``) ;
- leur version installée vient du lockfile qui va avec leur manifeste ;
- le reste du lockfile donne les transitives (``direct=False``). Le graphe de
  ``uv.lock`` et de ``poetry.lock`` dit leur scope : une transitive tirée par une
  dépendance de dev est en ``dev``.

Les noms sont normalisés selon PEP 503 (``Django_REST.framework`` →
``django-rest-framework``). Une dépendance git, locale, par URL, membre du
workspace ou tirée d'un autre index que PyPI est « non vérifiable », avec la raison.

Repris de ``reference/argos_sca_parsers.py`` (L389-645), puis adapté :
``Dependency`` au lieu de ``SCAComponent``, contraintes gardées telles qu'écrites au
lieu d'une version devinée, emplacements, lockfiles reliés aux manifestes, et un
fichier invalide signalé (``ParseError``) au lieu d'une liste vide.
"""

import dataclasses
import json
import logging
import posixpath
import re
import tomllib
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name

from forceupdate.detect.manifests import match_dependency_file
from forceupdate.models import Dependency, Ecosystem, Location, Notice, Project, Scope
from forceupdate.parsers.base import (
    REASON_GIT,
    REASON_LOCAL,
    REASON_URL,
    REASON_WORKSPACE,
    ParseError,
    ReadText,
)
from forceupdate.parsers.lockfiles import (
    Declared,
    Edge,
    LockedPackage,
    Lockfile,
    dirname,
    graph_starts,
    in_workspace,
    join,
    relative_to,
    transitives,
    with_installed,
)
from forceupdate.parsers.toml_spans import StringSpan, TomlPath, string_spans
from forceupdate.versions.pypi import PYPI

logger = logging.getLogger(__name__)

_REQUIREMENTS_PATTERNS = (
    "requirements*.txt",
    "requirements/*.txt",
    "requirements*.in",
    "requirements/*.in",
)


# ---------------------------------------------------------------------------
# Scopes et raisons
# ---------------------------------------------------------------------------

_DEV_WORDS = frozenset({"lint", "linting", "doc", "docs", "typing", "types", "ci", "qa", "check"})


def _looks_dev(name: str) -> bool:
    """Vrai si un nom de fichier, de groupe ou d'extra désigne des outils de développement.

    ``requirements-dev.txt``, ``test``, ``docs``, ``lint`` le sont ; ``docker`` non.
    """
    words = re.split(r"[^a-z0-9]+", name.lower())
    return any(word.startswith(("dev", "test")) or word in _DEV_WORDS for word in words)


def _group_scope(name: str) -> Scope:
    """Le scope d'un extra ou d'un groupe : ``dev`` pour les outils, sinon ``optional``."""
    return Scope.DEV if _looks_dev(name) else Scope.OPTIONAL


def _file_scope(path: str) -> Scope:
    """Le scope d'un fichier ``requirements`` d'après son nom (``requirements-dev.txt``…)."""
    return Scope.DEV if _looks_dev(posixpath.basename(path)) else Scope.RUNTIME


def _url_reason(url: str) -> str:
    """Pourquoi une dépendance par URL ou par chemin n'est pas vérifiable.

    La raison ne cite jamais l'URL : elle peut contenir un token.
    """
    lowered = url.strip().lower()
    for vcs in ("git", "hg", "svn", "bzr"):
        if lowered.startswith(f"{vcs}+"):
            return f"dépendance {vcs}"
    if lowered.startswith("file:") or not re.match(r"[a-z][a-z0-9+.-]*://", lowered):
        return REASON_LOCAL
    if lowered.endswith(".git"):
        return REASON_GIT
    return REASON_URL


def _index_reason(index: str) -> str:
    return f"vient de l'index « {index} », pas de PyPI"


# ---------------------------------------------------------------------------
# PEP 508
# ---------------------------------------------------------------------------

_NAME_AND_EXTRAS = re.compile(
    r"\s*(?P<name>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)\s*(?:\[(?P<extras>[^\]]*)\]\s*)?"
)

Locate = Callable[[int, int], Location | None]
"""Donne l'emplacement dans le fichier des caractères ``start`` à ``end`` d'un texte lu."""


@dataclass(frozen=True)
class _Pep508:
    """Une dépendance PEP 508 découpée (``httpx[http2] >=0.27 ; python_version >= "3.11"``)."""

    name: str
    extras: frozenset[str]
    constraint: str
    span: tuple[int, int] | None
    """Position de la contrainte dans le texte ; ``None`` si on ne l'a pas retrouvée."""
    url: str | None


def _split_pep508(text: str) -> _Pep508 | None:
    """Découpe une dépendance PEP 508 ; ``None`` si elle n'est pas valide.

    Sans contrainte, ``span`` est vide, juste après le nom et les extras : c'est là
    qu'une contrainte s'ajouterait.
    """
    try:
        requirement = Requirement(text)
    except InvalidRequirement:
        return None
    head = _NAME_AND_EXTRAS.match(text)
    if head is None:
        return None
    name = canonicalize_name(requirement.name)
    extras = frozenset(canonicalize_name(extra) for extra in requirement.extras)
    if requirement.url is not None:
        return _Pep508(name, extras, "", None, requirement.url)
    start = head.end()
    if text.startswith("(", start):
        start += 1
        end = text.index(")", start)
    else:
        semicolon = text.find(";", start)
        end = len(text) if semicolon == -1 else semicolon
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    constraint = text[start:end]
    try:
        found = SpecifierSet(constraint) == requirement.specifier
    except InvalidSpecifier:
        found = False
    if not found:
        return _Pep508(name, extras, str(requirement.specifier), None, None)
    return _Pep508(name, extras, constraint, (start, end), None)


def _edge_from_requirement(text: str) -> Edge | None:
    """Le nom et les extras au début d'une dépendance écrite (``PySocks (>=1.5.6)``)."""
    head = _NAME_AND_EXTRAS.match(text)
    if head is None:
        return None
    extras = head.group("extras") or ""
    return (
        canonicalize_name(head.group("name")),
        frozenset(canonicalize_name(e.strip()) for e in extras.split(",") if e.strip()),
    )


# ---------------------------------------------------------------------------
# Dépendances déclarées
# ---------------------------------------------------------------------------


def _declare_pep508(text: str, *, file: str, scope: Scope, locate: Locate) -> Declared | None:
    parsed = _split_pep508(text)
    if parsed is None:
        return None
    dependency = Dependency(
        ecosystem=Ecosystem.PYPI,
        name=parsed.name,
        constraint=parsed.constraint,
        scope=scope,
        file=file,
        location=locate(*parsed.span) if parsed.span is not None else None,
        unverifiable_reason=_url_reason(parsed.url) if parsed.url is not None else None,
    )
    return Declared(dependency, parsed.extras)


def _declare_constraint(
    name: str,
    value: str,
    span: StringSpan | None,
    *,
    file: str,
    scope: Scope,
    reason: str | None = None,
    extras: frozenset[str] = frozenset(),
) -> Declared:
    """Une dépendance dont la contrainte est une chaîne TOML (Poetry, Pipfile)."""
    start = len(value) - len(value.lstrip())
    end = len(value.rstrip())
    dependency = Dependency(
        ecosystem=Ecosystem.PYPI,
        name=canonicalize_name(name),
        constraint=value[start:end],
        scope=scope,
        file=file,
        location=span.location(start, end) if span is not None else None,
        unverifiable_reason=reason,
    )
    return Declared(dependency, extras)


def _declare_unversioned(
    name: str, *, file: str, scope: Scope, reason: str | None, extras: frozenset[str]
) -> Declared:
    """Une dépendance sans contrainte écrite (dépendance git, chemin local…)."""
    dependency = Dependency(
        ecosystem=Ecosystem.PYPI,
        name=canonicalize_name(name),
        scope=scope,
        file=file,
        unverifiable_reason=reason,
    )
    return Declared(dependency, extras)


def _span_locator(span: StringSpan | None) -> Locate:
    if span is None:
        return lambda start, end: None
    return span.location


def _line_locator(line: int, offset: int, limit: int) -> Locate:
    """Les caractères d'un texte qui commence à la colonne ``offset`` de la ligne ``line``.

    Au-delà de ``limit``, le texte continue sur la ligne suivante (``\\`` en fin de
    ligne) : on ne donne pas d'emplacement.
    """

    def locate(start: int, end: int) -> Location | None:
        if offset + end > limit:
            return None
        return Location(line=line, column=offset + start, end_column=offset + end)

    return locate


def _extras(value: Any) -> frozenset[str]:
    if not isinstance(value, list):
        return frozenset()
    return frozenset(canonicalize_name(extra) for extra in value if isinstance(extra, str))


# ---------------------------------------------------------------------------
# requirements.txt
# ---------------------------------------------------------------------------

_COMMENT = re.compile(r"(?:^|\s)#")
_INLINE_OPTION = re.compile(r"\s--?[A-Za-z]")
_OPTION = re.compile(r"(?P<name>--[A-Za-z][\w-]*|-[A-Za-z])\s*=?\s*(?P<argument>.*)")
_EGG = re.compile(r"[#&]egg=(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)")
_ARCHIVE_SUFFIXES = (".whl", ".zip", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz")


@dataclass
class _RequirementsFile:
    """Un ``requirements*.txt`` lu, avec ses ``-r`` et ``-c``."""

    path: str
    declared: list[Declared] = field(default_factory=list)
    includes: list[str] = field(default_factory=list)
    """Fichiers inclus avec ``-r``, en chemins relatifs à la source."""
    constraints: list[str] = field(default_factory=list)
    """Fichiers de contraintes donnés avec ``-c``."""
    notices: list[Notice] = field(default_factory=list)


def parse_requirements_txt(path: str, content: str) -> list[Dependency]:
    """Les dépendances écrites dans un ``requirements*.txt`` ou un ``.in`` de pip-tools.

    Les ``-r`` et ``-c`` ne sont pas suivis ici (``parse_project`` le fait), ni les
    autres options (``--index-url``…). ``-e .`` et les chemins locaux sans nom de
    paquet sont le code du projet : ils sont sautés. Le scope vient du nom du
    fichier (``requirements-dev.txt`` → ``dev``).
    """
    parsed = _parse_requirements(path, content, _file_scope(path))
    return [declared.dependency for declared in parsed.declared]


def _parse_requirements(path: str, content: str, scope: Scope) -> _RequirementsFile:
    parsed = _RequirementsFile(path)
    for number, text, first_length in _logical_lines(content):
        comment = _COMMENT.search(text)
        if comment is not None:
            text = text[: comment.start()]
        body = text.strip()
        if not body:
            continue
        if body.startswith("-"):
            _requirements_option(parsed, body, scope)
            continue
        indent = len(text) - len(text.lstrip())
        option = _INLINE_OPTION.search(text, indent)
        requirement = text[indent : option.start() if option else len(text)].rstrip()
        declared = _declare_pep508(
            requirement,
            file=path,
            scope=scope,
            locate=_line_locator(number, indent, first_length),
        ) or _declare_egg(requirement, file=path, scope=scope)
        if declared is not None:
            parsed.declared.append(declared)
        elif not _looks_like_path_or_url(requirement):
            parsed.notices.append(
                Notice(
                    file=path,
                    message=f"ligne {number} : « {requirement} » n'est pas une dépendance valide.",
                )
            )
    return parsed


def _logical_lines(content: str) -> Iterator[tuple[int, str, int]]:
    """Les lignes logiques d'un ``requirements.txt`` : ``(numéro, texte, longueur de la 1re)``.

    Une ligne finie par ``\\`` continue sur la suivante, comme pour pip. Le texte
    commence en colonne 0 de la ligne ``numéro`` ; au-delà de la longueur de la
    première ligne, il vient des lignes suivantes.
    """
    start = 0
    parts: list[str] = []
    first_length = 0
    for number, raw in enumerate(content.split("\n"), start=1):
        line = raw.rstrip("\r")
        if line.endswith("\\") and not _COMMENT.match(line.lstrip()):
            if not parts:
                start, first_length = number, len(line) - 1
            parts.append(line[:-1])
            continue
        if parts:
            parts.append(line)
            yield start, "".join(parts), first_length
            parts = []
        else:
            yield number, line, len(line)
    if parts:
        yield start, "".join(parts), first_length


def _requirements_option(parsed: _RequirementsFile, body: str, scope: Scope) -> None:
    """Traite une ligne d'option : ``-r``, ``-c`` et ``-e`` ; les autres sont ignorées."""
    match = _OPTION.match(body)
    if match is None:
        return
    name = match.group("name")
    words = match.group("argument").split()
    argument = words[0] if words else ""
    if name in ("-e", "--editable"):
        declared = _declare_egg(argument, file=parsed.path, scope=scope)
        if declared is not None:
            parsed.declared.append(declared)
        return
    if name not in ("-r", "--requirement", "-c", "--constraint") or not argument:
        return
    target = _include_path(parsed.path, argument)
    if target is None:
        parsed.notices.append(
            Notice(
                file=parsed.path,
                message=f"« {name} {argument} » : hors du dossier analysé, pas suivi.",
            )
        )
    elif name in ("-r", "--requirement"):
        parsed.includes.append(target)
    else:
        parsed.constraints.append(target)


def _include_path(including: str, argument: str) -> str | None:
    """Le chemin, relatif à la source, d'un fichier donné à ``-r`` ou ``-c``.

    Relatif au dossier du fichier qui l'inclut, comme pour pip. ``None`` pour une
    URL, un chemin absolu, ou un chemin qui sort de la source.
    """
    argument = argument.replace("\\", "/")
    if "://" in argument or argument.startswith("/") or re.match(r"[A-Za-z]:/", argument):
        return None
    path = posixpath.normpath(posixpath.join(posixpath.dirname(including), argument))
    if path == ".." or path.startswith("../"):
        return None
    return path


def _declare_egg(text: str, *, file: str, scope: Scope) -> Declared | None:
    """Une dépendance par URL ou chemin nommée par ``#egg=`` (``-e git+https://…#egg=nom``)."""
    egg = _EGG.search(text)
    if egg is None:
        return None
    return _declare_unversioned(
        egg.group("name"), file=file, scope=scope, reason=_url_reason(text), extras=frozenset()
    )


def _looks_like_path_or_url(text: str) -> bool:
    """Vrai pour un chemin local ou une URL sans nom de paquet (``./libs/x``, ``https://…``)."""
    return (
        "://" in text
        or text.startswith((".", "/", "~", "\\"))
        or re.match(r"[A-Za-z]:[\\/]", text) is not None
        or text.lower().endswith(_ARCHIVE_SUFFIXES)
    )


# ---------------------------------------------------------------------------
# pyproject.toml, Pipfile, setup.cfg
# ---------------------------------------------------------------------------


def _load_toml(content: str) -> dict[str, Any]:
    try:
        return tomllib.loads(content)
    except tomllib.TOMLDecodeError as err:
        raise ParseError(f"TOML invalide ({err}).") from err


def _table(data: Any, *keys: str) -> dict[str, Any]:
    """La table ``data[k1][k2]…`` ; une table vide si elle n'existe pas ou n'en est pas une."""
    for key in keys:
        if not isinstance(data, dict):
            return {}
        data = data.get(key)
    return data if isinstance(data, dict) else {}


@dataclass
class _Pyproject:
    """Un ``pyproject.toml`` lu."""

    declared: list[Declared]
    notices: list[Notice]
    tools: frozenset[str]
    """Les outils qui ont une table ``[tool.x]`` : ``poetry``, ``pdm``, ``uv``…"""


def parse_pyproject_toml(path: str, content: str) -> list[Dependency]:
    """Les dépendances d'un ``pyproject.toml``.

    Dans l'ordre : ``[project]`` (dépendances, puis extras), ``[dependency-groups]``,
    les dépendances de dev de uv et PDM, Poetry (``[tool.poetry.dependencies]``,
    ``dev-dependencies``, groupes), et enfin ``[build-system] requires``. Le projet
    qui se cite lui-même (``app[all]`` dans les extras de ``app``) est sauté.

    Lève ``ParseError`` si le TOML est invalide.
    """
    return [declared.dependency for declared in _parse_pyproject(path, content).declared]


def _parse_pyproject(
    path: str, content: str, *, inherited_sources: Mapping[str, Any] | None = None
) -> _Pyproject:
    data = _load_toml(content)
    spans = string_spans(content)
    declared: list[Declared] = []
    notices: list[Notice] = []

    def pep508_list(keys: TomlPath, values: Any, scope: Scope) -> None:
        if not isinstance(values, list):
            return
        for index, value in enumerate(values):
            if not isinstance(value, str):
                continue  # {include-group = "…"} : ses dépendances sont lues avec son groupe
            item = _declare_pep508(
                value, file=path, scope=scope, locate=_span_locator(spans.get((*keys, index)))
            )
            if item is None:
                notices.append(
                    Notice(file=path, message=f"« {value} » n'est pas une dépendance valide.")
                )
            else:
                declared.append(item)

    project = _table(data, "project")
    pep508_list(("project", "dependencies"), project.get("dependencies"), Scope.RUNTIME)
    for extra, values in _table(project, "optional-dependencies").items():
        pep508_list(("project", "optional-dependencies", extra), values, _group_scope(extra))
    for group, values in _table(data, "dependency-groups").items():
        pep508_list(("dependency-groups", group), values, _group_scope(group))
    uv_dev = _table(data, "tool", "uv").get("dev-dependencies")
    pep508_list(("tool", "uv", "dev-dependencies"), uv_dev, Scope.DEV)
    for group, values in _table(data, "tool", "pdm", "dev-dependencies").items():
        pep508_list(("tool", "pdm", "dev-dependencies", group), values, Scope.DEV)

    poetry = _table(data, "tool", "poetry")
    pep621_names = {item.dependency.name for item in declared}
    sections: list[tuple[tuple[str, ...], Scope]] = [
        (("tool", "poetry", "dependencies"), Scope.RUNTIME),
        (("tool", "poetry", "dev-dependencies"), Scope.DEV),
    ]
    for group in _table(poetry, "group"):
        scope = Scope.RUNTIME if group == "main" else _group_scope(group)
        sections.append((("tool", "poetry", "group", group, "dependencies"), scope))
    poetry_reasons: dict[str, str] = {}
    for keys, scope in sections:
        for raw_name, spec in _table(data, *keys).items():
            name = canonicalize_name(raw_name)
            if name == "python":
                continue
            items = _poetry_dependency(raw_name, spec, keys, spans, file=path, scope=scope)
            if scope is Scope.RUNTIME and name in pep621_names:
                # Poetry 2 : l'entrée complète une dépendance de [project] (source…).
                for item in items:
                    if item.dependency.unverifiable_reason is not None:
                        poetry_reasons[name] = item.dependency.unverifiable_reason
                continue
            declared.extend(items)

    build = _table(data, "build-system").get("requires")
    pep508_list(("build-system", "requires"), build, Scope.BUILD)

    names = (project.get("name"), poetry.get("name"))
    own = {canonicalize_name(name) for name in names if isinstance(name, str)}
    sources = {canonicalize_name(key): value for key, value in (inherited_sources or {}).items()}
    sources.update(
        (canonicalize_name(key), value)
        for key, value in _table(data, "tool", "uv", "sources").items()
    )
    result = []
    for item in declared:
        if item.dependency.name in own:
            continue
        reason = poetry_reasons.get(item.dependency.name) or _uv_source_reason(
            sources.get(item.dependency.name)
        )
        if reason is not None and item.dependency.scope is not Scope.BUILD:
            item = Declared(
                dataclasses.replace(item.dependency, unverifiable_reason=reason), item.extras
            )
        result.append(item)
    return _Pyproject(
        declared=result,
        notices=notices,
        tools=frozenset(_table(data, "tool")),
    )


def _poetry_dependency(
    raw_name: str,
    spec: Any,
    keys: TomlPath,
    spans: Mapping[TomlPath, StringSpan],
    *,
    file: str,
    scope: Scope,
) -> list[Declared]:
    """Une dépendance Poetry : ``"^2.31"``, ``{version = "^8.1", optional = true}``, ou une
    liste de ces tables (une contrainte par version de Python)."""
    if isinstance(spec, str):
        return [
            _declare_constraint(
                raw_name, spec, spans.get((*keys, raw_name)), file=file, scope=scope
            )
        ]
    if isinstance(spec, dict):
        tables = [(spec, (*keys, raw_name))]
    elif isinstance(spec, list):
        tables = [
            (item, (*keys, raw_name, i)) for i, item in enumerate(spec) if isinstance(item, dict)
        ]
    else:
        return []
    items = []
    for table, table_keys in tables:
        item_scope = (
            Scope.OPTIONAL if table.get("optional") is True and scope is Scope.RUNTIME else scope
        )
        reason = _poetry_reason(table)
        extras = _extras(table.get("extras"))
        version = table.get("version")
        if isinstance(version, str):
            span = spans.get((*table_keys, "version"))
            items.append(
                _declare_constraint(
                    raw_name,
                    version,
                    span,
                    file=file,
                    scope=item_scope,
                    reason=reason,
                    extras=extras,
                )
            )
        else:
            items.append(
                _declare_unversioned(
                    raw_name, file=file, scope=item_scope, reason=reason, extras=extras
                )
            )
    return items


def _poetry_reason(table: Mapping[str, Any]) -> str | None:
    if "git" in table:
        return REASON_GIT
    if "path" in table:
        return REASON_LOCAL
    if isinstance(table.get("url"), str):
        return _url_reason(table["url"])
    source = table.get("source")
    if isinstance(source, str) and source.lower() != "pypi":
        return _index_reason(source)
    return None


def _uv_source_reason(source: Any) -> str | None:
    """Pourquoi une source de ``[tool.uv.sources]`` rend la dépendance non vérifiable."""
    entries = source if isinstance(source, list) else [source]
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("workspace") is True:
            return REASON_WORKSPACE
        if "git" in entry:
            return REASON_GIT
        if "path" in entry:
            return REASON_LOCAL
        if isinstance(entry.get("url"), str):
            return _url_reason(entry["url"])
        if isinstance(entry.get("index"), str):
            return _index_reason(entry["index"])
    return None


_PIPFILE_RESERVED = frozenset({"source", "requires", "pipenv", "scripts"})


def parse_pipfile(path: str, content: str) -> list[Dependency]:
    """Les dépendances d'un ``Pipfile`` : ``[packages]``, ``[dev-packages]``, et les
    autres catégories de pipenv (``[docs]``…).

    Lève ``ParseError`` si le TOML est invalide.
    """
    return [declared.dependency for declared in _parse_pipfile(path, content)]


def _parse_pipfile(path: str, content: str) -> list[Declared]:
    data = _load_toml(content)
    spans = string_spans(content)
    declared = []
    for section, packages in data.items():
        if section in _PIPFILE_RESERVED or not isinstance(packages, dict):
            continue
        if section == "packages":
            scope = Scope.RUNTIME
        elif section == "dev-packages":
            scope = Scope.DEV
        else:
            scope = _group_scope(section)
        for raw_name, spec in packages.items():
            if isinstance(spec, str):
                span = spans.get((section, raw_name))
                declared.append(_declare_constraint(raw_name, spec, span, file=path, scope=scope))
                continue
            if not isinstance(spec, dict):
                continue
            reason = _pipfile_reason(spec)
            extras = _extras(spec.get("extras"))
            version = spec.get("version")
            if isinstance(version, str):
                span = spans.get((section, raw_name, "version"))
                declared.append(
                    _declare_constraint(
                        raw_name,
                        version,
                        span,
                        file=path,
                        scope=scope,
                        reason=reason,
                        extras=extras,
                    )
                )
            else:
                declared.append(
                    _declare_unversioned(
                        raw_name, file=path, scope=scope, reason=reason, extras=extras
                    )
                )
    return declared


def _pipfile_reason(spec: Mapping[str, Any]) -> str | None:
    for vcs in ("git", "hg", "svn", "bzr"):
        if vcs in spec:
            return f"dépendance {vcs}"
    if "path" in spec:
        return REASON_LOCAL
    if isinstance(spec.get("file"), str):
        return _url_reason(spec["file"])
    index = spec.get("index")
    if isinstance(index, str) and index.lower() != "pypi":
        return _index_reason(index)
    return None


_CFG_SEPARATOR = re.compile(r"[=:]")


def parse_setup_cfg(path: str, content: str) -> list[Dependency]:
    """Les dépendances d'un ``setup.cfg`` : ``install_requires``, ``extras_require``,
    ``tests_require`` (dev) et ``setup_requires`` (build).

    Comme setuptools : une dépendance par ligne quand la valeur est sur plusieurs
    lignes, sinon séparées par des ``;``.
    """
    return [declared.dependency for declared in _parse_setup_cfg(path, content)[0]]


def _parse_setup_cfg(path: str, content: str) -> tuple[list[Declared], list[Notice]]:
    declared: list[Declared] = []
    notices: list[Notice] = []
    lines = [line.rstrip("\r") for line in content.split("\n")]
    section = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")) or line[0] in " \t":
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip().lower()
            continue
        separator = _CFG_SEPARATOR.search(line)
        if separator is None:
            continue
        key = line[: separator.start()].strip().lower().replace("-", "_")
        values = [(index, separator.end())]  # (numéro de ligne, colonne de début)
        while index < len(lines):
            following = lines[index]
            if (
                following.strip()
                and following[0] not in " \t"
                and not following.lstrip().startswith(("#", ";"))
            ):
                break
            values.append((index + 1, 0))
            index += 1
        scope = _setup_cfg_scope(section, key)
        if scope is None:
            continue
        for number, column, text in _setup_cfg_items(lines, values):
            item = _declare_pep508(
                text,
                file=path,
                scope=scope,
                locate=_line_locator(number, column, len(lines[number - 1])),
            )
            if item is None:
                notices.append(
                    Notice(
                        file=path,
                        message=f"ligne {number} : « {text} » n'est pas une dépendance valide.",
                    )
                )
            else:
                declared.append(item)
    return declared, notices


def _setup_cfg_scope(section: str, key: str) -> Scope | None:
    if section == "options":
        return {
            "install_requires": Scope.RUNTIME,
            "tests_require": Scope.DEV,
            "setup_requires": Scope.BUILD,
        }.get(key)
    if section == "options.extras_require":
        return _group_scope(key)
    return None


def _setup_cfg_items(
    lines: Sequence[str], values: Sequence[tuple[int, int]]
) -> Iterator[tuple[int, int, str]]:
    """Les dépendances d'une valeur de ``setup.cfg`` : ``(ligne, colonne, texte)``."""
    texts = [(number, column, lines[number - 1][column:]) for number, column in values]
    filled = [text for _, _, text in texts if text.strip() and not text.strip().startswith("#")]
    if len(filled) > 1:
        pieces = texts  # une dépendance par ligne
    else:
        number, column, text = next(
            ((n, c, t) for n, c, t in texts if t.strip() and not t.strip().startswith("#")),
            (0, 0, ""),
        )
        pieces = []
        offset = 0
        for piece in text.split(";"):
            pieces.append((number, column + offset, piece))
            offset += len(piece) + 1
    for number, column, text in pieces:
        stripped = text.strip()
        if not stripped or stripped.startswith("#"):
            continue
        yield number, column + len(text) - len(text.lstrip()), stripped


# ---------------------------------------------------------------------------
# Lockfiles
# ---------------------------------------------------------------------------


def installed_version(lock: Lockfile, name: str) -> str | None:
    """La version figée de ``name`` dans ``lock`` ; la plus haute selon PEP 440 s'il y en a
    plusieurs (fourches par marqueurs de ``uv.lock``), la première si aucune n'est lisible."""
    versions = [p.version for p in lock.packages if p.name == name and p.version]
    return PYPI.highest(versions) or next(iter(versions), None)


def parse_uv_lock(path: str, content: str) -> Lockfile:
    """Un ``uv.lock``. Il couvre tout le workspace ; ses membres sont ``local``."""
    data = _load_toml(content)
    packages = []
    for entry in _entries(data.get("package")):
        source = _table(entry, "source")
        packages.append(
            LockedPackage(
                name=canonicalize_name(entry["name"]),
                version=str(entry.get("version", "")),
                dependencies=_uv_edges(entry.get("dependencies")),
                extras={
                    canonicalize_name(extra): _uv_edges(items)
                    for extra, items in _table(entry, "optional-dependencies").items()
                },
                local="editable" in source or "virtual" in source,
                unverifiable_reason=_uv_lock_reason(source),
            )
        )
    return Lockfile(
        path=path, ecosystem=Ecosystem.PYPI, packages=tuple(packages), graph=True, shared=True
    )


def _entries(value: Any) -> list[dict[str, Any]]:
    """Les ``[[package]]`` qui ont un nom."""
    if not isinstance(value, list):
        return []
    return [
        entry for entry in value if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    ]


def _uv_edges(items: Any) -> tuple[Edge, ...]:
    if not isinstance(items, list):
        return ()
    return tuple(
        (canonicalize_name(item["name"]), _extras(item.get("extra")))
        for item in items
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    )


def _uv_lock_reason(source: Mapping[str, Any]) -> str | None:
    if "git" in source:
        return REASON_GIT
    if source.keys() & {"path", "directory", "editable", "virtual"}:
        return REASON_LOCAL
    if "url" in source:
        return REASON_URL
    return None


def parse_poetry_lock(path: str, content: str) -> Lockfile:
    """Un ``poetry.lock``.

    Le scope de chaque paquet vient de ``category`` (Poetry ≤ 1.4) ou de ``groups``
    (Poetry 2) ; entre les deux, Poetry n'écrit ni l'un ni l'autre, et c'est le
    graphe, suivi depuis les groupes du ``pyproject.toml``, qui le donne.
    """
    data = _load_toml(content)
    packages = []
    for entry in _entries(data.get("package")):
        dependencies = []
        for raw_name, spec in _table(entry, "dependencies").items():
            specs = spec if isinstance(spec, list) else [spec]
            tables = [item for item in specs if isinstance(item, dict)]
            if (
                tables
                and len(tables) == len(specs)
                and all(t.get("optional") is True for t in tables)
            ):
                continue  # tirée seulement par un extra
            extras = frozenset().union(*(_extras(t.get("extras")) for t in tables))
            dependencies.append((canonicalize_name(raw_name), extras))
        extras_edges = {
            canonicalize_name(extra): tuple(
                edge
                for requirement in requirements
                if isinstance(requirement, str) and (edge := _edge_from_requirement(requirement))
            )
            for extra, requirements in _table(entry, "extras").items()
            if isinstance(requirements, list)
        }
        packages.append(
            LockedPackage(
                name=canonicalize_name(entry["name"]),
                version=str(entry.get("version", "")),
                dependencies=tuple(dependencies),
                extras=extras_edges,
                scope=_poetry_lock_scope(entry),
                unverifiable_reason=_poetry_lock_reason(_table(entry, "source")),
            )
        )
    return Lockfile(path=path, ecosystem=Ecosystem.PYPI, packages=tuple(packages), graph=True)


def _poetry_lock_scope(entry: Mapping[str, Any]) -> Scope | None:
    category = entry.get("category")
    if category in ("dev", "test"):
        return Scope.DEV
    if category == "main":
        return Scope.RUNTIME
    groups = entry.get("groups")
    if isinstance(groups, list) and groups:
        return Scope.RUNTIME if "main" in groups else _group_scope(str(groups[0]))
    return None


def _poetry_lock_reason(source: Mapping[str, Any]) -> str | None:
    kind = source.get("type")
    if kind == "git":
        return REASON_GIT
    if kind in ("directory", "file"):
        return REASON_LOCAL
    if kind == "url":
        return REASON_URL
    return None  # « legacy » : un autre index, mais un index quand même


def parse_pdm_lock(path: str, content: str) -> Lockfile:
    """Un ``pdm.lock``. Le scope vient de ``groups`` (``default`` → ``runtime``)."""
    data = _load_toml(content)
    packages = []
    for entry in _entries(data.get("package")):
        groups = entry.get("groups")
        scope = None
        if isinstance(groups, list) and groups:
            scope = Scope.RUNTIME if "default" in groups else _group_scope(str(groups[0]))
        reason = None
        if "git" in entry:
            reason = REASON_GIT
        elif "path" in entry:
            reason = REASON_LOCAL
        elif "url" in entry:
            reason = REASON_URL
        packages.append(
            LockedPackage(
                name=canonicalize_name(entry["name"]),
                version=str(entry.get("version", "")),
                scope=scope,
                unverifiable_reason=reason,
            )
        )
    return Lockfile(path=path, ecosystem=Ecosystem.PYPI, packages=tuple(packages))


def parse_pipfile_lock(path: str, content: str) -> Lockfile:
    """Un ``Pipfile.lock`` : ``default`` (``runtime``), ``develop`` (``dev``), et les autres
    catégories de pipenv.

    Lève ``ParseError`` si le JSON est invalide.
    """
    try:
        data = json.loads(content)
    except ValueError as err:
        raise ParseError(f"JSON invalide ({err}).") from err
    if not isinstance(data, dict):
        raise ParseError("JSON inattendu : un objet est attendu.")
    sections = sorted(
        (key for key in data if key != "_meta"),
        key=lambda key: (key != "default", key != "develop", key),
    )
    packages = []
    for section in sections:
        bucket = data[section]
        if not isinstance(bucket, dict):
            continue
        if section == "default":
            scope = Scope.RUNTIME
        elif section == "develop":
            scope = Scope.DEV
        else:
            scope = _group_scope(section)
        for raw_name, info in bucket.items():
            if not isinstance(info, dict):
                continue
            packages.append(
                LockedPackage(
                    name=canonicalize_name(raw_name),
                    version=str(info.get("version", "")).lstrip("="),
                    scope=scope,
                    unverifiable_reason=_pipfile_reason(info),
                )
            )
    return Lockfile(path=path, ecosystem=Ecosystem.PYPI, packages=tuple(packages))


def _requirements_lock(parsed: _RequirementsFile, scope: Scope) -> Lockfile:
    """Un ``.txt`` compilé par pip-tools, ou un fichier de contraintes (``-c``), vu comme
    un lockfile : la version figée est celle d'un ``==``."""
    packages = []
    for declared in parsed.declared:
        dependency = declared.dependency
        packages.append(
            LockedPackage(
                name=dependency.name,
                version=_pinned_version(dependency.constraint) or "",
                scope=scope,
                unverifiable_reason=dependency.unverifiable_reason,
                constraint=dependency.constraint,
                location=dependency.location,
            )
        )
    return Lockfile(path=parsed.path, ecosystem=Ecosystem.PYPI, packages=tuple(packages))


def _pinned_version(constraint: str) -> str | None:
    """La version d'une contrainte exacte (``==2.0.1``) ; ``None`` sinon."""
    try:
        specifiers = list(SpecifierSet(constraint))
    except InvalidSpecifier:
        return None
    if len(specifiers) != 1:
        return None
    specifier = specifiers[0]
    if specifier.operator in ("==", "===") and "*" not in specifier.version:
        return specifier.version
    return None


# ---------------------------------------------------------------------------
# Lien manifeste ↔ lockfile
# ---------------------------------------------------------------------------


def _with_installed(declared: Iterable[Declared], locks: Sequence[Lockfile]) -> list[Dependency]:
    """Les dépendances directes, avec la version du premier lockfile qui les connaît."""

    def installed(item: Declared) -> str | None:
        name = item.dependency.name
        return next((v for lock in locks if (v := installed_version(lock, name))), None)

    return with_installed(declared, installed)


def _transitives(lock: Lockfile, declared: Sequence[Declared], names: set[str]) -> list[Dependency]:
    """Les paquets du lockfile qui ne sont pas des directes : une version de plus d'une
    directe (fourche de ``uv.lock``) n'en est pas une."""
    return transitives(lock, graph_starts(declared), lambda package: package.name in names)


# ---------------------------------------------------------------------------
# Un projet
# ---------------------------------------------------------------------------

_LOCK_PARSERS: dict[str, Callable[[str, str], Lockfile]] = {
    "uv.lock": parse_uv_lock,
    "poetry.lock": parse_poetry_lock,
    "pdm.lock": parse_pdm_lock,
    "Pipfile.lock": parse_pipfile_lock,
}

_PYPROJECT_LOCKS = ("uv.lock", "poetry.lock", "pdm.lock")
"""Les lockfiles d'un ``pyproject.toml``, par ordre de préférence quand l'outil n'est pas
connu. Avec ``[tool.poetry]`` ou ``[tool.pdm]``, le lockfile de cet outil passe devant."""


def parse_project(project: Project, read_text: ReadText) -> None:
    """Lit les fichiers Python de ``project`` et remplit ses dépendances.

    Ajoute à ``project.dependencies`` les directes (dans l'ordre des manifestes)
    puis les transitives, et à ``project.notices`` ce qui n'a pas pu être lu. Le
    ``uv.lock`` d'un workspace dont le projet n'est pas membre est retiré de
    ``project.lockfiles``.
    """
    _ProjectParser(project, read_text).run()


class _ProjectParser:
    """Lit les fichiers Python d'un projet et relie manifestes et lockfiles."""

    def __init__(self, project: Project, read_text: ReadText) -> None:
        self.project = project
        self.read_text = read_text
        self.notices: list[Notice] = []
        self.directs: list[Dependency] = []
        self.transitives: list[Dependency] = []
        self.used_locks: set[str] = set()
        self.pinned_files: dict[str, Lockfile | None] = {}
        """Les ``.txt`` compilés et fichiers de contraintes déjà lus (voir ``_pinned_file``)."""
        self.manifests = self._python_files(project.manifests)
        self.locks = self._python_files(project.lockfiles)

    def run(self) -> None:
        if "pyproject.toml" in self.manifests:
            self._pyproject(self.manifests["pyproject.toml"][0])
        if "Pipfile" in self.manifests:
            self._pipfile(self.manifests["Pipfile"][0])
        if "setup.cfg" in self.manifests:
            self._setup_cfg(self.manifests["setup.cfg"][0])
        for path in self.manifests.get("setup.py", []):
            self.notices.append(
                Notice(
                    file=path,
                    message="pas lu : il faudrait l'exécuter pour connaître ses dépendances.",
                )
            )
        self._requirements()
        self._orphan_locks()

        order = {path: index for index, path in enumerate(self.project.manifests)}
        self.directs.sort(key=lambda d: order.get(d.file, len(order)))
        self.transitives.sort(key=lambda d: (d.file, d.name, PYPI.sort_key(d.installed or "")))
        self.project.dependencies.extend(self.directs + self.transitives)
        self.project.notices.extend(self.notices)

    # -- lecture ------------------------------------------------------------

    @staticmethod
    def _python_files(paths: Iterable[str]) -> dict[str, list[str]]:
        """Les fichiers Python de ``paths``, par motif reconnu (``pyproject.toml``…)."""
        found: dict[str, list[str]] = defaultdict(list)
        for path in paths:
            match = match_dependency_file(path)
            if match is not None and match.ecosystem is Ecosystem.PYPI:
                found[match.pattern].append(path)
        return found

    def _read(self, path: str) -> str | None:
        try:
            content = self.read_text(path)
        except ValueError:
            content = None
        if content is None:
            self.notices.append(
                Notice(file=path, message="introuvable, illisible ou trop gros : pas lu.")
            )
        return content

    def _lock(self, path: str, parser: Callable[[str, str], Lockfile]) -> Lockfile | None:
        self.used_locks.add(path)
        content = self._read(path)
        if content is None:
            return None
        try:
            return parser(path, content)
        except ParseError as err:
            self.notices.append(Notice(file=path, message=str(err)))
            return None

    def _lock_named(self, name: str) -> str | None:
        paths = self.locks.get(name)
        return paths[0] if paths else None

    # -- manifestes ---------------------------------------------------------

    def _pyproject(self, path: str) -> None:
        inherited: dict[str, Any] = {}
        uv_lock = self._lock_named("uv.lock")
        if uv_lock is not None and dirname(uv_lock) != self.project.path:
            member, inherited = self._uv_membership(uv_lock)
            if not member:
                logger.debug("%s n'est pas membre du workspace de %s", self.project.path, uv_lock)
                self.project.lockfiles.remove(uv_lock)
                del self.locks["uv.lock"]
        content = self._read(path)
        if content is None:
            return
        try:
            parsed = _parse_pyproject(path, content, inherited_sources=inherited)
        except ParseError as err:
            self.notices.append(Notice(file=path, message=str(err)))
            return
        self.notices.extend(parsed.notices)

        preferred = [name for name in ("poetry", "pdm") if name in parsed.tools]
        candidates = [f"{name}.lock" for name in preferred] + list(_PYPROJECT_LOCKS)
        lock_path = next((p for name in candidates if (p := self._lock_named(name))), None)
        lock = None
        if lock_path is not None:
            lock = self._lock(lock_path, _LOCK_PARSERS[posixpath.basename(lock_path)])
            for name in _PYPROJECT_LOCKS:
                other = self._lock_named(name)
                if other is not None and other != lock_path:
                    self.used_locks.add(other)
                    self.notices.append(
                        Notice(
                            file=other,
                            message=f"pas lu : {lock_path} est le lockfile pris pour {path}.",
                        )
                    )
        self._link(parsed.declared, lock)

    def _uv_membership(self, lock: str) -> tuple[bool, dict[str, Any]]:
        """Vrai si le projet est membre du workspace uv de ``lock`` ; et les sources de la
        racine, dont les membres héritent."""
        root = dirname(lock)
        content = self._read(join(root, "pyproject.toml"))
        if content is None:
            return False, {}
        try:
            data = _load_toml(content)
        except ParseError:
            return False, {}  # la remarque vient avec le projet racine
        workspace = _table(data, "tool", "uv", "workspace")
        members = [m for m in workspace.get("members", []) if isinstance(m, str)]
        excluded = [m for m in workspace.get("exclude", []) if isinstance(m, str)]
        member = in_workspace(relative_to(self.project.path, root), members, excluded)
        return member, _table(data, "tool", "uv", "sources")

    def _pipfile(self, path: str) -> None:
        content = self._read(path)
        if content is None:
            return
        try:
            declared = _parse_pipfile(path, content)
        except ParseError as err:
            self.notices.append(Notice(file=path, message=str(err)))
            return
        lock_path = self._lock_named("Pipfile.lock")
        lock = self._lock(lock_path, parse_pipfile_lock) if lock_path is not None else None
        self._link(declared, lock)

    def _setup_cfg(self, path: str) -> None:
        content = self._read(path)
        if content is None:
            return
        declared, notices = _parse_setup_cfg(path, content)
        self.notices.extend(notices)
        self._link(declared, None)

    def _link(self, declared: list[Declared], lock: Lockfile | None) -> None:
        locks = [lock] if lock is not None else []
        self.directs.extend(_with_installed(declared, locks))
        if lock is not None:
            # Une dépendance de build (hatchling…) n'est pas installée avec le projet :
            # le même paquet, tiré à l'exécution, reste une transitive.
            names = {d.dependency.name for d in declared if d.dependency.scope is not Scope.BUILD}
            self.transitives.extend(_transitives(lock, declared, names))

    # -- pip et pip-tools ---------------------------------------------------

    def _requirements(self) -> None:
        """Les ``requirements*.txt`` et ``.in``, avec leurs ``-r`` et ``-c``.

        Un fichier tiré par ``-r`` depuis un fichier ``runtime`` est ``runtime`` ;
        sinon ``dev``. La version installée vient du ``.txt`` compilé par pip-tools
        (pour un ``.in``), puis des fichiers de contraintes.
        """
        roots = [p for pattern in _REQUIREMENTS_PATTERNS for p in self.manifests.get(pattern, [])]
        roots.sort(key=self.project.manifests.index)
        if not roots:
            return
        files: dict[str, _RequirementsFile] = {}
        queue = list(roots)
        while queue:
            path = queue.pop(0)
            if path in files:
                continue
            content = self._read(path)
            if content is None:
                continue
            files[path] = _parse_requirements(path, content, Scope.RUNTIME)
            self.notices.extend(files[path].notices)
            queue.extend(files[path].includes)

        closures = {root: _closure(root, files) for root in roots if root in files}
        runtime = set().union(
            *(closure for root, closure in closures.items() if _file_scope(root) is Scope.RUNTIME)
        )

        def scope_of(path: str) -> Scope:
            return Scope.RUNTIME if path in runtime else Scope.DEV

        # Le .txt compilé de chaque .in (pip-tools), puis les fichiers de contraintes.
        compiled = {
            path[: -len(".txt")].lower(): path
            for pattern in ("requirements*.txt", "requirements/*.txt")
            for path in self.locks.get(pattern, [])
        }
        pairs: dict[str, Lockfile] = {}
        for path in files:
            target = compiled.get(path[: -len(".in")].lower()) if path.endswith(".in") else None
            if target is not None and (lock := self._pinned_file(target, scope_of(path))):
                pairs[path] = lock
        constraints: dict[str, Lockfile] = {}
        for path in dict.fromkeys(c for parsed in files.values() for c in parsed.constraints):
            users = [p for p, parsed in files.items() if path in parsed.constraints]
            scope = Scope.RUNTIME if any(scope_of(p) is Scope.RUNTIME for p in users) else Scope.DEV
            if lock := self._pinned_file(path, scope):
                constraints[path] = lock

        declared: list[Declared] = []
        for path, parsed in files.items():
            reaching = [root for root, closure in closures.items() if path in closure]
            locks = [pairs[p] for p in (path, *reaching) if p in pairs]
            locks += [
                constraints[c]
                for root in reaching
                for member in closures[root]
                for c in files[member].constraints
                if c in constraints
            ]
            items = [
                Declared(dataclasses.replace(item.dependency, scope=scope_of(path)), item.extras)
                for item in parsed.declared
            ]
            declared.extend(items)
            self.directs.extend(_with_installed(items, locks))

        names = {item.dependency.name for item in declared}
        # Un même .txt peut être à la fois compilé et donné à « -c » : lu une fois.
        locks_by_path = {lock.path: lock for lock in [*pairs.values(), *constraints.values()]}
        for lock in locks_by_path.values():
            self.transitives.extend(_transitives(lock, declared, names))

    def _pinned_file(self, path: str, scope: Scope) -> Lockfile | None:
        """Un ``.txt`` compilé ou un fichier de contraintes, lu une seule fois.

        Le scope de ses paquets est celui de la première lecture : les ``.txt``
        compilés sont lus avant les contraintes.
        """
        if path not in self.pinned_files:
            self.used_locks.add(path)
            content = self._read(path)
            lock = None
            if content is not None:
                parsed = _parse_requirements(path, content, scope)
                self.notices.extend(parsed.notices)
                lock = _requirements_lock(parsed, scope)
            self.pinned_files[path] = lock
        return self.pinned_files[path]

    # -- lockfiles seuls ----------------------------------------------------

    def _orphan_locks(self) -> None:
        """Les lockfiles qu'aucun manifeste n'a pris : tout leur contenu est transitif."""
        for pattern, paths in self.locks.items():
            for path in paths:
                if path in self.used_locks:
                    continue
                if pattern in _LOCK_PARSERS:
                    lock = self._lock(path, _LOCK_PARSERS[pattern])
                else:  # un .txt compilé dont le .in n'a pas pu être lu
                    lock = self._pinned_file(path, _file_scope(path))
                if lock is not None:
                    self.transitives.extend(_transitives(lock, [], set()))


def _closure(root: str, files: Mapping[str, _RequirementsFile]) -> set[str]:
    """``root`` et les fichiers qu'il inclut avec ``-r``, de proche en proche."""
    found: set[str] = set()
    stack = [root]
    while stack:
        path = stack.pop()
        if path in found or path not in files:
            continue
        found.add(path)
        stack.extend(files[path].includes)
    return found
