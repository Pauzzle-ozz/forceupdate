"""La régénération des lockfiles, juste après la réécriture des manifestes (brief, décision n°11).

Un lockfile est régénéré par l'outil de son format, jamais réécrit par forceupdate. L'outil est
trouvé par ``shutil.which`` (sous Windows, ``npm`` est ``npm.cmd``), lancé sans shell, dans le
dossier du lockfile (la racine d'un workspace : une fois pour tous ses membres), avec un délai
maximal, sans entrée standard, et sans les scripts du projet quand il le permet :

============================  ===========================================================
Lockfile                      Commande de base
============================  ===========================================================
``package-lock.json``         ``npm install --package-lock-only --ignore-scripts``
``pnpm-lock.yaml``            ``pnpm install --lockfile-only --ignore-scripts --ignore-pnpmfile``
``yarn.lock`` (Yarn 1)        ``yarn install --ignore-scripts``, ``node_modules`` dans un
                              dossier temporaire (Yarn 1 n'a pas de mode « lockfile seul »)
``yarn.lock`` (Yarn 2+)       ``yarn install --mode=update-lockfile`` (rien n'est installé)
``uv.lock``                   ``uv lock``
``poetry.lock``               ``poetry lock`` (``--no-update`` avant Poetry 2)
``pdm.lock``                  ``pdm lock --update-reuse``
``Pipfile.lock``              ``pipenv lock``
``.txt`` compilé (pip-tools)  la commande de son en-tête : ``pip-compile …`` ou
                              ``uv pip compile …``, avec les options connues
============================  ===========================================================

Vérifié avec npm 11.6, pnpm 12.15, Yarn 1.22 et 4.18, uv 0.10, Poetry 1.8 et 2.5, PDM 2.29,
pipenv 2026.10 et pip-tools 7.6 (voir les notes de E11 dans ``PLAN.md``).

**Viser la version choisie.** Régénérer garde les versions déjà figées qui satisfont les
contraintes : une mise à jour par le lockfile seul (la contrainte accepte déjà la version) ne
bougerait pas. Chaque outil a sa façon de viser un paquet :

- uv, pip-compile : ``--upgrade-package x==V``, une contrainte ferme ;
- npm, pnpm, Poetry et PDM gardent une version figée qui satisfait la contrainte : la version
  exacte est écrite à la place de la contrainte (``update.writers.rewrite``) le temps d'une
  première régénération, puis la contrainte est remise et l'outil relancé. Une version forcée
  réécrite est épinglée de la même façon. Une indirecte : ``npm update x``, ``pnpm update x
  --no-save``, ``poetry update --lock x``, ``pdm update --no-sync x``, qui la montent aussi
  haut que le permet ce qui la tire. Si l'épinglage échoue (un pair qui exige autre chose…),
  on régénère sans, comme pour une indirecte ;
- Yarn et pipenv reprennent la plus haute version que permet la contrainte : ``yarn up -R x``
  (Yarn 2+), l'entrée du paquet retirée du ``yarn.lock`` (Yarn 1, dont ``yarn upgrade``
  réordonne le ``package.json``), et ``pipenv lock``, qui re-résout tout.

Un ``.txt`` de pip-tools qui cite (``-r``, ``-c``) un fichier réécrit ou un autre ``.txt``
régénéré est recompilé aussi, après lui.

**Ensuite**, le projet est relu (``engine.inventory``) : chaque mise à jour dit la version
installée (``Installed``) ; une version restée en dessous de la cible dit quels paquets la
retiennent (``parsers.lockfiles.dependents``). Les autres versions que le lockfile a changées sont
rendues aussi.

**Échec** (conflit de versions, délai dépassé, outil qui plante, ou Ctrl-C) : les fichiers du
projet sont remis comme avant, manifestes réécrits compris (``FileChange.before``), avec les
lockfiles qui dépendent des mêmes fichiers, et l'erreur de l'outil est rapportée.

**Outil absent** : les manifestes restent réécrits, et le résultat donne la commande à lancer.
"""

import dataclasses
import enum
import itertools
import logging
import os
import posixpath
import re
import shlex
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from forceupdate import engine, parsers, versions
from forceupdate.detect.manifests import ecosystem_for_manifest
from forceupdate.models import (
    Dependency,
    Ecosystem,
    Edit,
    EditKind,
    Event,
    EventKind,
    Project,
    Report,
    Update,
    UpdateOption,
)
from forceupdate.parsers import python
from forceupdate.parsers.base import ParseError, ReadText
from forceupdate.parsers.lockfiles import Lockfile, dependents, dirname, join
from forceupdate.sources.local import LocalSource
from forceupdate.update import writers
from forceupdate.update.writers import Changes, Choice, FileChange, Refused, Target
from forceupdate.update.writers.npm import PNPM_WORKSPACE, catalog_target

logger = logging.getLogger(__name__)

__all__ = [
    "LOCK_TIMEOUT",
    "Installed",
    "Job",
    "LockKind",
    "LockStatus",
    "Reach",
    "Regenerated",
    "plan",
    "regenerate",
]

LOCK_TIMEOUT = 600.0
"""Délai maximal de chaque commande, en secondes."""

_OUTPUT_LINES = 12
"""Lignes de la sortie de l'outil gardées dans le message d'erreur."""


class LockKind(enum.StrEnum):
    """Le format d'un lockfile, donc l'outil qui le régénère."""

    NPM = "npm"
    PNPM = "pnpm"
    YARN_1 = "yarn1"
    YARN = "yarn"
    """Yarn 2 et plus (Berry)."""
    UV = "uv"
    POETRY = "poetry"
    PDM = "pdm"
    PIPENV = "pipenv"
    PIP_COMPILE = "pip-compile"
    UV_PIP_COMPILE = "uv-pip-compile"
    """Un ``.txt`` compilé par ``uv pip compile`` (son en-tête le dit)."""


_TOOL_NAMES = {
    LockKind.NPM: "npm",
    LockKind.PNPM: "pnpm",
    LockKind.YARN_1: "Yarn 1",
    LockKind.YARN: "Yarn",
    LockKind.UV: "uv",
    LockKind.POETRY: "Poetry",
    LockKind.PDM: "PDM",
    LockKind.PIPENV: "pipenv",
    LockKind.PIP_COMPILE: "pip-compile",
    LockKind.UV_PIP_COMPILE: "uv pip compile",
}

_PROGRAMS = {
    LockKind.NPM: "npm",
    LockKind.PNPM: "pnpm",
    LockKind.YARN_1: "yarn",
    LockKind.YARN: "yarn",
    LockKind.UV: "uv",
    LockKind.POETRY: "poetry",
    LockKind.PDM: "pdm",
    LockKind.PIPENV: "pipenv",
    LockKind.PIP_COMPILE: "pip-compile",
    LockKind.UV_PIP_COMPILE: "uv",
}
"""Le programme de chaque outil, cherché par ``shutil.which``."""

_UV_BUILDS = (
    "uv construit les paquets publiés sans wheel dont il lit les dépendances, et le projet si "
    "elles sont dynamiques : leur code de construction s'exécute."
)
"""``--no-build`` l'empêcherait, mais il change la résolution : un paquet sans wheel pour une
seule plateforme la rend impossible (``sslyze`` dans Argos). Il n'est donc pas passé."""

_RUNS_CODE = {
    LockKind.UV: _UV_BUILDS,
    LockKind.UV_PIP_COMPILE: _UV_BUILDS,
    LockKind.POETRY: (
        "Poetry construit les paquets publiés sans wheel pour lire leurs dépendances : leur "
        "code de construction s'exécute."
    ),
    LockKind.PDM: (
        "PDM construit les paquets publiés sans wheel (leur code s'exécute), et crée le "
        "virtualenv du projet (.venv) s'il n'en a pas."
    ),
    LockKind.PIPENV: (
        "pipenv construit les paquets publiés sans wheel (leur code s'exécute), et crée le "
        "virtualenv du projet s'il n'existe pas."
    ),
    LockKind.PIP_COMPILE: (
        "pip-compile construit les paquets publiés sans wheel pour lire leurs dépendances : "
        "leur code de construction s'exécute."
    ),
}
"""Ce que l'outil exécute quand même, faute d'option pour l'en empêcher (brief, piège
« Régénérer un lockfile peut exécuter du code du projet »)."""


class LockStatus(enum.StrEnum):
    """Ce qu'il est advenu d'un lockfile."""

    REGENERATED = "regenerated"
    """Régénéré par son outil."""
    TOOL_MISSING = "tool_missing"
    """L'outil n'est pas installé : les manifestes restent réécrits, la commande est à lancer à
    la main."""
    FAILED = "failed"
    """L'outil a échoué : les fichiers sont remis comme avant."""
    UNDONE = "undone"
    """Pas régénéré, ou remis comme avant : un lockfile qui dépend des mêmes fichiers a
    échoué."""


class Reach(enum.StrEnum):
    """Où en est une mise à jour, une fois le lockfile relu."""

    EXACT = "exact"
    """La version choisie est installée."""
    ABOVE = "above"
    """Une version plus haute : l'outil a pris la plus haute que permet la contrainte."""
    BELOW = "below"
    """Une version en dessous reste : quelque chose la retient."""
    UNKNOWN = "unknown"
    """Le paquet n'est plus retrouvé dans le lockfile."""


@dataclass(frozen=True, kw_only=True)
class Job:
    """Un lockfile à régénérer, et comment."""

    lockfile: str
    """Relatif à la racine de la source."""
    kind: LockKind
    program: str | None
    """L'exécutable trouvé (``shutil.which``) ; ``None`` si l'outil n'est pas installé."""
    command: str
    """La commande à lancer à la main dans ``directory`` : celle que la personne lancerait."""
    choices: tuple[Choice, ...] = ()
    """Les mises à jour appliquées qu'il porte ; aucune pour un ``.txt`` de pip-tools recompilé
    parce qu'un fichier qu'il cite a changé (``reason``)."""
    inputs: tuple[str, ...] = ()
    """Les fichiers réécrits, et les lockfiles régénérés avant lui, dont il dépend : s'il
    échoue, ils sont remis comme avant."""
    options: tuple[str, ...] = ()
    """Ce que sa commande prend en plus : ``--no-update`` (Poetry 1), les options reprises de
    l'en-tête d'un ``.txt`` compilé."""
    sources: tuple[str, ...] = ()
    """pip-tools : les fichiers sources, relatifs au dossier du lockfile."""
    workspace: bool = False
    """Le lockfile d'un workspace : npm et pnpm visent alors tous ses projets."""
    reason: str | None = None
    """Pourquoi il est régénéré sans mise à jour à lui (pip-tools)."""
    warnings: tuple[str, ...] = ()
    """Ce qu'il faut savoir avant : ce que l'outil exécute, une option d'en-tête pas reprise."""

    @property
    def tool(self) -> str:
        """Le nom de l'outil, pour le dire."""
        return _TOOL_NAMES[self.kind]

    @property
    def program_name(self) -> str:
        """Le programme à installer pour régénérer le lockfile (``uv`` pour ``uv pip
        compile``)."""
        return _PROGRAMS[self.kind]

    @property
    def directory(self) -> str:
        """Le dossier où l'outil est lancé : celui du lockfile."""
        return dirname(self.lockfile)


@dataclass(frozen=True, kw_only=True)
class Installed:
    """La version qu'une mise à jour a donnée, une fois le lockfile relu."""

    update: Update
    option: UpdateOption
    versions: tuple[str, ...]
    """Les versions installées du paquet (plusieurs pour une indirecte npm)."""
    reach: Reach
    held_by: tuple[str, ...] = ()
    """Pour ``BELOW`` : les paquets qui la retiennent (``debug 4.3.1``)."""


@dataclass(frozen=True, kw_only=True)
class Regenerated:
    """Ce qu'il est advenu d'un lockfile."""

    job: Job
    status: LockStatus
    error: str | None = None
    """``FAILED`` : ce que l'outil a dit ; ``UNDONE`` : quel lockfile a échoué."""
    restored: tuple[str, ...] = ()
    """Les fichiers remis comme avant."""
    installed: tuple[Installed, ...] = ()
    """``REGENERATED`` : chaque mise à jour, relue."""
    changed: tuple[str, ...] = ()
    """``REGENERATED`` : les autres paquets que le lockfile a changés (``h11 0.16.0 → 0.14.0``)."""
    warnings: tuple[str, ...] = ()
    """Ce qui s'est passé en route (versions exactes refusées…)."""


# ---------------------------------------------------------------------------
# Le plan : quels lockfiles, avec quelle commande
# ---------------------------------------------------------------------------


def plan(source: LocalSource, report: Report, changes: Changes) -> tuple[Job, ...]:
    """Les lockfiles à régénérer après ``changes`` (``writers.prepare``), sans rien lancer :
    ceux des options appliquées, puis les ``.txt`` de pip-tools, dont ceux qui citent un fichier
    réécrit ou un autre ``.txt`` régénéré. Dans l'ordre où les régénérer.

    ``report`` est l'analyse qui a donné ``changes``. Lève ``ValueError`` pour un lockfile que
    forceupdate ne sait pas régénérer."""
    by_lockfile: dict[str, list[Choice]] = {}
    for choice in changes.applied:
        project, update, option = choice
        if option.lockfile and writers.constraints_file(project, update, option) is None:
            by_lockfile.setdefault(option.lockfile, []).append(choice)
    changed = {change.path for change in changes.files}
    compiled = _compiled_files(source, report)
    jobs = [
        _job(source, report, path, choices, changed, None, None)
        for path, choices in sorted(by_lockfile.items())
        if path not in compiled
    ]
    regenerated: set[str] = set()
    for path in _pip_tools_order(compiled, set(by_lockfile), changed):
        reason = None
        if path not in by_lockfile:
            cited = sorted(compiled[path].closure & (changed | regenerated))
            reason = f"{', '.join(cited)} {'a' if len(cited) == 1 else 'ont'} changé"
        jobs.append(
            _job(source, report, path, by_lockfile.get(path, []), changed, compiled[path], reason)
        )
        regenerated.add(path)
    return tuple(jobs)


def _job(
    source: LocalSource,
    report: Report,
    path: str,
    choices: Sequence[Choice],
    changed: set[str],
    compiled: "_Compiled | None",
    reason: str | None,
) -> Job:
    projects = _projects_of(report, path)
    warnings: list[str] = []
    options: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    if compiled is not None:
        kind, options, sources = compiled.kind, compiled.options, compiled.sources
        warnings += compiled.warnings
        inputs = compiled.closure - {path}
    else:
        kind = _kind(source, path)
        inputs = _manifests_of(report, path)
    inputs &= changed | (compiled.lockfiles if compiled is not None else set())
    program = _which(_PROGRAMS[kind])
    if kind is LockKind.POETRY and program is not None and _poetry_major(program) == 1:
        options = ("--no-update",)
    if kind is LockKind.PNPM:
        workspace = (source.root / dirname(path) / PNPM_WORKSPACE).is_file()
    else:
        workspace = len(projects) > 1 or any(p.path != dirname(path) for p in projects)
    if kind in _RUNS_CODE:
        warnings.append(_RUNS_CODE[kind])
    elif kind in (LockKind.YARN, LockKind.YARN_1):
        warnings += _yarn_runs_code(source.read_text, dirname(path))
    job = Job(
        lockfile=path,
        kind=kind,
        program=program,
        command="",
        choices=tuple(choices),
        inputs=tuple(sorted(inputs)),
        options=options,
        sources=sources,
        workspace=workspace,
        reason=reason,
        warnings=tuple(warnings),
    )
    return dataclasses.replace(job, command=shlex.join(_DRIVERS[kind].manual(job)))


def _kind(source: LocalSource, path: str) -> LockKind:
    """Le format du lockfile ``path``, d'après son nom (et son contenu pour ``yarn.lock``)."""
    name = posixpath.basename(path)
    if name == "yarn.lock":
        content = _read_quietly(source.read_text, path) or ""
        berry = re.search(r"^__metadata:", content, re.MULTILINE) is not None
        return LockKind.YARN if berry else LockKind.YARN_1
    kind = _KINDS.get(name)
    if kind is None:
        raise ValueError(f"forceupdate ne sait pas régénérer {path}")
    return kind


_KINDS = {
    "package-lock.json": LockKind.NPM,
    "npm-shrinkwrap.json": LockKind.NPM,
    "pnpm-lock.yaml": LockKind.PNPM,
    "uv.lock": LockKind.UV,
    "poetry.lock": LockKind.POETRY,
    "pdm.lock": LockKind.PDM,
    "Pipfile.lock": LockKind.PIPENV,
}


def _yarn_runs_code(read_text: ReadText, directory: str) -> list[str]:
    """Ce que Yarn exécutera du projet : la version de Yarn qu'il déclare (``yarnPath``,
    ``yarn-path``), ses extensions (``plugins``)."""
    declared = []
    for name, keys in ((".yarnrc.yml", ("yarnPath", "plugins")), (".yarnrc", ("yarn-path",))):
        content = _read_quietly(read_text, join(directory, name)) or ""
        declared += [key for key in keys if re.search(rf"^{key}\b", content, re.MULTILINE)]
    if not declared:
        return []
    return [f"Yarn lance du code du projet : {', '.join(declared)} (fichiers .yarnrc)."]


def _projects_of(report: Report, lockfile: str) -> list[Project]:
    return [project for project in report.projects if lockfile in project.lockfiles]


def _manifests_of(report: Report, lockfile: str) -> set[str]:
    """Les manifestes que fige ``lockfile`` : ceux de son écosystème dans les projets qui
    l'ont, plus le ``pnpm-workspace.yaml`` de son dossier pour npm (catalogues, versions
    forcées). Un projet qui a aussi un ``requirements.txt`` ne le mêle pas à son
    ``package-lock.json``."""
    ecosystem = ecosystem_for_manifest(lockfile)
    found = {
        manifest
        for project in _projects_of(report, lockfile)
        for manifest in project.manifests
        if ecosystem_for_manifest(manifest) is ecosystem
    }
    if ecosystem is Ecosystem.NPM:
        found.add(join(dirname(lockfile), PNPM_WORKSPACE))
    return found


def _read_quietly(read_text: ReadText, path: str) -> str | None:
    try:
        return read_text(path)
    except ValueError:
        return None


def _poetry_major(program: str) -> int | None:
    """La version majeure de Poetry (« Poetry (version 2.5.1) ») ; ``None`` si on ne la lit
    pas."""
    try:
        result = _spawn(
            [program, "--version"],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            env=_environment(),
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    found = re.search(r"(\d+)\.\d+", _decode(result.stdout))
    return int(found.group(1)) if found else None


# -- pip-tools ----------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class _Compiled:
    """Un ``.txt`` compilé par pip-tools : son outil, ses options et ses sources."""

    kind: LockKind
    options: tuple[str, ...]
    """Les options reprises de son en-tête."""
    sources: tuple[str, ...]
    """Ses fichiers sources, relatifs à son dossier."""
    closure: frozenset[str]
    """Ses sources et les fichiers qu'elles citent par ``-r`` et ``-c``, de proche en proche
    (relatifs à la source)."""
    lockfiles: frozenset[str] = frozenset()
    """Les autres ``.txt`` compilés de ``closure`` : régénérés avant lui."""
    warnings: tuple[str, ...] = ()


_HEADER_COMMAND = re.compile(r"^#\s+(?P<command>(?:uv pip compile|pip-compile)\s.*)$")

_FLAGS = frozenset(
    {
        "--generate-hashes",
        "--allow-unsafe",
        "--no-allow-unsafe",
        "--strip-extras",
        "--no-strip-extras",
        "--all-extras",
        "--emit-index-url",
        "--no-emit-index-url",
        "--emit-trusted-host",
        "--no-emit-trusted-host",
        "--emit-find-links",
        "--no-emit-find-links",
        "--emit-options",
        "--no-emit-options",
        "--emit-build-options",
        "--emit-index-annotation",
        "--annotate",
        "--no-annotate",
        "--header",
        "--no-header",
        "--reuse-hashes",
        "--no-reuse-hashes",
        "--pre",
        "--no-index",
        "--universal",
        "--no-deps",
        "--no-strip-markers",
        "--no-build",
    }
)
"""Les options sans valeur reprises de l'en-tête d'un ``.txt`` compilé : la forme du fichier et
ce qui est résolu. Une autre (``--pip-args``…) n'est pas reprise, et le plan le dit."""

_VALUED = frozenset(
    {
        "--extra",
        "--annotation-style",
        "--index-url",
        "-i",
        "--extra-index-url",
        "--default-index",
        "--index",
        "--find-links",
        "-f",
        "--trusted-host",
        "--unsafe-package",
        "--resolver",
        "--newline",
        "--python-version",
        "--python-platform",
        "--resolution",
        "--prerelease",
        "--index-strategy",
        "--no-emit-package",
        "--only-binary",
        "--no-binary",
    }
)
"""Les options à valeur reprises de l'en-tête. Les index en sont : sans eux, un paquet privé
serait cherché sur PyPI."""

_GIVEN = frozenset({"-o", "--output-file", "-P", "--upgrade-package"})
"""Les options à valeur que forceupdate donne lui-même."""

_IGNORED = frozenset({"-U", "--upgrade", "-q", "--quiet", "-v", "--verbose"})

_NEWER = frozenset({"--exclude-newer"})
"""Une date au-delà de laquelle rien n'est pris : elle écarterait les versions choisies. Pas
reprise, et le plan le dit."""


def _compiled_files(source: LocalSource, report: Report) -> dict[str, _Compiled]:
    """Les ``.txt`` compilés par pip-tools de la source : un lockfile d'un projet, avec un ``.in``
    du même nom parmi ses manifestes."""
    found = {}
    for project in report.projects:
        sources = {m.lower(): m for m in project.manifests if m.endswith(".in")}
        for path in project.lockfiles:
            source_in = sources.get(path[: -len(".txt")].lower() + ".in")
            if path.endswith(".txt") and source_in is not None and path not in found:
                found[path] = _compiled(source, path, source_in)
    return {
        path: dataclasses.replace(item, lockfiles=frozenset(item.closure & (found.keys() - {path})))
        for path, item in found.items()
    }


def _compiled(source: LocalSource, path: str, source_in: str) -> _Compiled:
    """Lit l'en-tête du ``.txt`` ``path`` : l'outil qui l'a écrit, ses options, ses sources."""
    directory = dirname(path)
    header = None
    for line in (_read_quietly(source.read_text, path) or "").split("\n")[:30]:
        found = _HEADER_COMMAND.match(line.strip())
        if found is not None:
            header = found.group("command")
            break
    kind = LockKind.PIP_COMPILE
    options: list[str] = []
    sources: list[str] = []
    warnings: list[str] = []
    if header is not None:
        try:
            words = shlex.split(header)
        except ValueError:
            words = []
        if words[:3] == ["uv", "pip", "compile"]:
            kind = LockKind.UV_PIP_COMPILE
        words = words[3:] if kind is LockKind.UV_PIP_COMPILE else words[1:]
        options, sources, dropped = _header_options(words, source.root / directory)
        newer = [item for item in dropped if item.split(" ")[0] in _NEWER]
        others = [item for item in dropped if item not in newer]
        if newer:
            warnings.append(
                f"Pas repris de l'en-tête de {path} : {', '.join(newer)}, qui écarterait les "
                "versions choisies."
            )
        if others:
            warnings.append(f"Pas repris de l'en-tête de {path} : {' '.join(others)}.")
    if not sources:
        sources = [posixpath.basename(source_in)]
    closure = _closure(source.read_text, [join(directory, s) for s in sources])
    return _Compiled(
        kind=kind,
        options=tuple(options),
        sources=tuple(sources),
        closure=frozenset(closure),
        warnings=tuple(warnings),
    )


def _header_options(
    words: Sequence[str], directory: Path
) -> tuple[list[str], list[str], list[str]]:
    """Dans la commande de l'en-tête : les options reprises, les fichiers sources (relatifs à
    ``directory``) et ce qui n'est pas repris."""
    options: list[str] = []
    sources: list[str] = []
    dropped: list[str] = []
    items = iter(words)
    for word in items:
        if not word.startswith("-"):
            relative = word.replace("\\", "/")
            inside = not relative.startswith("/") and ":" not in relative
            if inside and ".." not in relative.split("/") and (directory / relative).is_file():
                sources.append(relative)
            else:
                dropped.append(word)
            continue
        name, has_value, value = word.partition("=")
        if name in _FLAGS and not has_value:
            options.append(word)
        elif name in _VALUED:
            options.extend((name, value if has_value else next(items, "")))
        elif name in _NEWER:
            dropped.append(f"{name} {value if has_value else next(items, '')}".strip())
        elif name in _GIVEN:
            if not has_value:
                next(items, None)
        elif name not in _IGNORED:
            dropped.append(word)
    return options, sources, dropped


def _closure(read_text: ReadText, paths: Iterable[str]) -> set[str]:
    """``paths`` et les fichiers qu'ils citent par ``-r`` et ``-c``, de proche en proche."""
    found: set[str] = set()
    stack = list(paths)
    while stack:
        path = stack.pop()
        if path in found:
            continue
        found.add(path)
        content = _read_quietly(read_text, path)
        if content is not None:
            stack.extend(python.requirements_references(path, content))
    return found


def _pip_tools_order(
    compiled: Mapping[str, _Compiled], wanted: set[str], changed: set[str]
) -> list[str]:
    """Les ``.txt`` compilés à régénérer : ceux de ``wanted``, ceux qui citent un fichier de
    ``changed``, et ceux qui citent un ``.txt`` régénéré. Un ``.txt`` cité passe devant."""
    todo = {path for path, item in compiled.items() if path in wanted or item.closure & changed}
    while more := {p for p, item in compiled.items() if p not in todo and item.lockfiles & todo}:
        todo |= more
    order: list[str] = []
    pending = sorted(todo)
    while pending:
        ready = [p for p in pending if not compiled[p].lockfiles & set(pending)] or pending[:1]
        order += ready
        pending = [p for p in pending if p not in ready]
    return order


# ---------------------------------------------------------------------------
# La régénération
# ---------------------------------------------------------------------------


class _Failed(Exception):
    """Une commande a échoué : le message, en français, dit laquelle et ce que l'outil a dit."""


def regenerate(
    source: LocalSource,
    report: Report,
    changes: Changes,
    jobs: Sequence[Job],
    *,
    on_event: Callable[[Event], None] | None = None,
) -> tuple[Regenerated, ...]:
    """Régénère les lockfiles de ``jobs`` (``plan``), une fois les fichiers de ``changes``
    écrits (``writers.write``), puis relit le projet. ``report`` est l'analyse d'avant.

    Les lockfiles qui dépendent des mêmes fichiers vont ensemble : si l'un échoue, tous leurs
    fichiers sont remis comme avant (``Regenerated.restored``). Dans l'ordre de ``jobs``.

    ``on_event`` reçoit un ``Event`` ``REGENERATING`` avant chaque outil lancé : l'interface
    montre ainsi lequel tourne (un outil peut tourner plusieurs minutes)."""
    total = sum(1 for job in jobs if job.program is not None)
    if not total:
        return tuple(Regenerated(job=job, status=LockStatus.TOOL_MISSING) for job in jobs)
    started = itertools.count()

    def announce(job: Job) -> None:
        if on_event is not None:
            event = Event(
                kind=EventKind.REGENERATING, name=job.lockfile, done=next(started), total=total
            )
            on_event(event)

    written = {change.path: change for change in changes.files}
    current = {project.path: project for project in engine.inventory(source).projects}
    outcome: dict[str, Regenerated] = {}
    locks_before: dict[str, str | None] = {}
    for group in _groups(jobs):
        saved = _snapshot(source.root, report, group)
        for job in group:
            locks_before[job.lockfile] = _read_quietly(source.read_text, job.lockfile)
        try:
            failure = _run_group(source, group, current, outcome, announce)
        except BaseException:  # Ctrl-C : rien ne doit rester à moitié fait
            _restore(source.root, saved, written, group)
            raise
        if failure is not None:
            failed, message = failure
            restored = _restore(source.root, saved, written, group)
            for job in group:
                if job is failed:
                    status, error = LockStatus.FAILED, message
                else:
                    status, error = LockStatus.UNDONE, f"{failed.lockfile} a échoué"
                outcome[job.lockfile] = Regenerated(
                    job=job, status=status, error=error, restored=restored
                )
    if any(r.status is LockStatus.REGENERATED for r in outcome.values()):
        after = {project.path: project for project in engine.inventory(source).projects}
        for path, result in outcome.items():
            if result.status is LockStatus.REGENERATED:
                outcome[path] = _read_back(source, result, after, locks_before)
    return tuple(outcome[job.lockfile] for job in jobs)


def _run_group(
    source: LocalSource,
    group: Sequence[Job],
    current: Mapping[str, Project],
    outcome: dict[str, Regenerated],
    announce: Callable[[Job], None],
) -> tuple[Job, str] | None:
    """Régénère les lockfiles du groupe, dans l'ordre, jusqu'au premier qui échoue : rend
    celui-là et son erreur. ``announce`` est appelé avant chaque outil lancé."""
    for job in group:
        if job.program is None:
            outcome[job.lockfile] = Regenerated(job=job, status=LockStatus.TOOL_MISSING)
            continue
        announce(job)
        context = _Context(source, job, current)
        try:
            _DRIVERS[job.kind].run(context)
        except _Failed as failed:
            return job, str(failed)
        outcome[job.lockfile] = Regenerated(
            job=job, status=LockStatus.REGENERATED, warnings=tuple(context.warnings)
        )
    return None


def _groups(jobs: Sequence[Job]) -> list[list[Job]]:
    """Les lockfiles qui dépendent des mêmes fichiers, ou l'un de l'autre, ensemble ; dans
    l'ordre de ``jobs``."""
    groups: list[tuple[set[str], list[Job]]] = []
    for job in jobs:
        paths = {job.lockfile, *job.inputs}
        merged = (paths, [job])
        for group in [g for g in groups if g[0] & paths]:
            groups.remove(group)
            merged = (merged[0] | group[0], group[1] + merged[1])
        groups.append(merged)
    order = {job.lockfile: index for index, job in enumerate(jobs)}
    found = [sorted(jobs_, key=lambda j: order[j.lockfile]) for _, jobs_ in groups]
    return sorted(found, key=lambda g: order[g[0].lockfile])


def _snapshot(root: Path, report: Report, group: Sequence[Job]) -> dict[str, bytes | None]:
    """Le contenu actuel des fichiers que les outils du groupe peuvent toucher : les lockfiles,
    leurs entrées, et les manifestes de leurs projets (``None`` pour un fichier absent)."""
    paths: set[str] = set()
    for job in group:
        paths |= {job.lockfile, *job.inputs, *_manifests_of(report, job.lockfile)}
    saved: dict[str, bytes | None] = {}
    for path in sorted(paths):
        try:
            saved[path] = (root / path).read_bytes()
        except FileNotFoundError:
            saved[path] = None
        except OSError as err:
            logger.debug("%s illisible avant la régénération : %s", path, err)
    return saved


def _restore(
    root: Path,
    saved: Mapping[str, bytes | None],
    written: Mapping[str, FileChange],
    group: Sequence[Job],
) -> tuple[str, ...]:
    """Remet les fichiers du groupe comme avant la mise à jour : ses manifestes réécrits comme
    avant leur réécriture, le reste comme avant la régénération. Rend ceux qui ont changé."""
    inputs = {path for job in group for path in job.inputs}
    restored = []
    for path, data in saved.items():
        wanted = written[path].before.encode("utf-8") if path in inputs & written.keys() else data
        full = root / path
        try:
            current = full.read_bytes()
        except FileNotFoundError:
            current = None
        except OSError:
            current = b""  # illisible : on tente de le remettre
        if current == wanted:
            continue
        try:
            if wanted is None:
                full.unlink()
            else:
                writers.replace_file(full, wanted)
        except OSError as err:
            logger.warning("%s n'a pas pu être remis comme avant : %s", path, err)
            continue
        restored.append(path)
    return tuple(sorted(restored))


# -- relire ---------------------------------------------------------------------


def _read_back(
    source: LocalSource,
    result: Regenerated,
    after: Mapping[str, Project],
    locks_before: Mapping[str, str | None],
) -> Regenerated:
    """``result``, avec ce que donne chaque mise à jour et ce qui a changé d'autre."""
    job = result.job
    lock_after = _lockfile(job.lockfile, _read_quietly(source.read_text, job.lockfile))
    lock_before = _lockfile(job.lockfile, locks_before.get(job.lockfile))
    installed = tuple(_installed(choice, after, lock_after) for choice in job.choices)
    names = {update.name for _, update, _ in job.choices}
    return dataclasses.replace(
        result, installed=installed, changed=_changed(lock_before, lock_after, names)
    )


def _lockfile(path: str, content: str | None) -> Lockfile | None:
    if content is None:
        return None
    try:
        return parsers.parse_lockfile(path, content)
    except (ParseError, ValueError) as err:
        logger.debug("%s illisible après la régénération : %s", path, err)
        return None


def _installed(choice: Choice, after: Mapping[str, Project], lock: Lockfile | None) -> Installed:
    """La version qu'a donnée la mise à jour ``choice``, dans le projet relu."""
    project, update, option = choice
    fresh = after.get(project.path)
    files = {d.file for d in update.dependencies}
    found = {
        d.installed
        for d in (fresh.dependencies if fresh is not None else [])
        if d.name == update.name
        and d.direct == update.direct
        and d.installed
        and (not update.direct or d.file in files)
    }
    scheme = versions.for_ecosystem(update.ecosystem)
    installed = sorted((v for v in found if v), key=scheme.sort_key)
    base = {"update": update, "option": option, "versions": tuple(installed)}
    if not installed:
        return Installed(**base, reach=Reach.UNKNOWN)
    target = option.version
    current = update.current_version or target
    below = [
        v
        for v in installed
        if scheme.compare(v, target) < 0 and (update.direct or scheme.compare(v, current) >= 0)
    ]
    if below:
        held = [
            f"{parent.name} {parent.version}".strip()
            for version in below
            for parent in (dependents(lock, update.name, version) if lock is not None else [])
        ]
        return Installed(**base, reach=Reach.BELOW, held_by=tuple(dict.fromkeys(held)))
    if target in installed and (not update.direct or installed == [target]):
        return Installed(**base, reach=Reach.EXACT)
    return Installed(**base, reach=Reach.ABOVE)


def _changed(before: Lockfile | None, after: Lockfile | None, skip: set[str]) -> tuple[str, ...]:
    """Les paquets du lockfile dont les versions ont changé, sauf ceux de ``skip`` : ``x 1.0 →
    1.1``, ``x : ajouté (1.0)``, ``x : retiré (1.0)``."""
    if before is None or after is None:
        return ()
    old, new = _versions_by_name(before), _versions_by_name(after)
    lines = []
    for name in sorted(old.keys() | new.keys()):
        was, now = old.get(name), new.get(name)
        if name in skip or was == now:
            continue
        if was is None:
            lines.append(f"{name} : ajouté ({', '.join(now or ())})")
        elif now is None:
            lines.append(f"{name} : retiré ({', '.join(was)})")
        else:
            lines.append(f"{name} {', '.join(was)} → {', '.join(now)}")
    return tuple(lines)


def _versions_by_name(lock: Lockfile) -> dict[str, tuple[str, ...]]:
    scheme = versions.for_ecosystem(lock.ecosystem)
    found: dict[str, set[str]] = {}
    for package in lock.packages:
        if not package.local and package.version:
            found.setdefault(package.name, set()).add(package.version)
    return {name: tuple(sorted(found[name], key=scheme.sort_key)) for name in found}


# ---------------------------------------------------------------------------
# Lancer les outils
# ---------------------------------------------------------------------------


_DROPPED_ENV = frozenset(
    {
        "VIRTUAL_ENV",
        "VIRTUAL_ENV_PROMPT",
        "PIPENV_ACTIVE",
        "POETRY_ACTIVE",
        "UV_FROZEN",
        "UV_LOCKED",
    }
)
"""Ce qui, hérité de l'environnement de forceupdate, ferait viser un autre projet à l'outil (le
virtualenv activé, que pipenv et Poetry prendraient pour celui du projet), ou lui interdirait
d'écrire le lockfile."""

_ADDED_ENV = {
    "NO_COLOR": "1",
    "FORCE_COLOR": "0",
    "NO_UPDATE_NOTIFIER": "1",
    "npm_config_update_notifier": "false",
    "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0",
    "YARN_ENABLE_IMMUTABLE_INSTALLS": "false",
    "YARN_ENABLE_TELEMETRY": "0",
    "YARN_ENABLE_PROGRESS_BARS": "false",
    "UV_NO_PROGRESS": "1",
    "POETRY_NO_INTERACTION": "1",
    "PIPENV_YES": "1",
    "PIPENV_NOSPIN": "1",
    "PIPENV_VERBOSITY": "-1",
    "PYTHONIOENCODING": "utf-8",
}
"""Ni couleurs, ni questions ; en CI, Yarn refuserait sinon de changer son lockfile."""

_BATCH_UNSAFE = re.compile(r'["%!&|<>^()\r\n]')
"""Ce que ``cmd.exe`` interpréterait dans un argument d'un ``.cmd`` (``npm.cmd``…)."""

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _which(program: str) -> str | None:
    """L'exécutable de ``program`` sur le ``PATH`` (``npm.CMD`` sous Windows) ; ``None`` s'il
    n'y est pas. Les tests le remplacent : jamais de vrai outil hors des tests ``network``."""
    return shutil.which(program)


def _spawn(command: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
    """``subprocess.run``, sans shell. Les tests le remplacent."""
    return subprocess.run(command, shell=False, **options)


def _environment() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key.upper() not in _DROPPED_ENV}
    env.update(_ADDED_ENV)
    return env


def _decode(data: bytes) -> str:
    return _ANSI.sub("", data.decode("utf-8", errors="replace"))


class _Context:
    """Ce dont un outil a besoin pour régénérer un lockfile."""

    def __init__(self, source: LocalSource, job: Job, current: Mapping[str, Project]) -> None:
        self.source = source
        self.root = source.root
        self.job = job
        self.current = current
        """Les projets relus après la réécriture des manifestes : les emplacements des pins."""
        self.warnings: list[str] = []

    def run(self, *arguments: str) -> None:
        """Lance le programme de l'outil avec ``arguments``, dans le dossier du lockfile. Lève
        ``_Failed``."""
        program = self.job.program
        assert program is not None
        shown = shlex.join([_PROGRAMS[self.job.kind], *arguments])
        if program.lower().endswith((".cmd", ".bat")):
            unsafe = next((a for a in arguments if _BATCH_UNSAFE.search(a)), None)
            if unsafe is not None:
                raise _Failed(f"« {shown} » : argument refusé ({unsafe}).")
        logger.debug("%s (dans %s)", shown, self.job.directory)
        try:
            result = _spawn(
                [program, *arguments],
                cwd=self.root / self.job.directory,
                env=_environment(),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=LOCK_TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired as err:
            raise _Failed(f"« {shown} » n'a pas fini en {LOCK_TIMEOUT:.0f} s.") from err
        except OSError as err:
            raise _Failed(f"« {shown} » n'a pas pu être lancé ({err.strerror or err}).") from err
        if result.returncode != 0:
            output = _decode(result.stderr).strip() or _decode(result.stdout).strip()
            lines = [line for line in output.splitlines() if line.strip()][-_OUTPUT_LINES:]
            said = "\n".join(lines) or "(rien)"
            raise _Failed(f"« {shown} » a échoué (code {result.returncode}) :\n{said}")

    def names(self, *, direct: bool | None = None) -> list[str]:
        """Les paquets des mises à jour, sans doublon ; seulement les directes, ou seulement les
        indirectes."""
        found = (u.name for _, u, _ in self.job.choices if direct is None or u.direct == direct)
        return list(dict.fromkeys(found))

    def run_pinned(self, exact: Callable[[str], str], *arguments: str) -> bool:
        """Lance ``arguments`` avec, à la place des contraintes, la version choisie écrite par
        ``exact`` (``pins``), puis remet les contraintes. Faux s'il n'y a rien à épingler, ou si
        l'épinglage échoue : la raison va dans ``warnings``."""
        targets = self.pins(exact)
        if not targets:
            return False
        try:
            files = writers.rewrite(self.root, targets)
            writers.write(self.root, Changes(files=files))
        except (Refused, writers.WriteError) as err:
            self.warnings.append(f"Versions exactes pas écrites ({err}) : régénéré sans.")
            return False
        try:
            self.run(*arguments)
        except _Failed as failed:
            first = str(failed).split("\n", 1)[0]
            self.warnings.append(f"Versions exactes refusées : {first}")
            return False
        finally:
            for change in files:
                writers.replace_file(self.root / change.path, change.before.encode("utf-8"))
        return True

    def pins(self, exact: Callable[[str], str]) -> list[Target]:
        """Les contraintes des directes, et les versions forcées réécrites, remplacées par la
        version choisie."""
        targets: list[Target] = []
        for project, update, option in self.job.choices:
            fresh = self.current.get(project.path)
            if fresh is None:
                continue
            new = exact(option.version)
            if update.direct:
                files = {d.file for d in update.dependencies}
                for dependency in fresh.dependencies:
                    if (
                        dependency.direct
                        and dependency.name == update.name
                        and dependency.file in files
                    ):
                        targets += self._pin(dependency, new)
            else:
                for edit in option.edits:
                    if edit.kind is EditKind.OVERRIDE:
                        targets += _override_pins(fresh, edit, new)
        return targets

    def _pin(self, dependency: Dependency, new: str) -> list[Target]:
        if dependency.resolved_constraint is not None:  # un catalogue pnpm
            edit = Edit(
                kind=EditKind.CATALOG,
                file=dependency.file,
                location=None,
                old=dependency.resolved_constraint,
                new=new,
            )
            try:
                target = catalog_target(edit, [dependency], self.source.read_text)
            except Refused:
                return []
            return [target] if target.old != new else []
        if dependency.location is None or dependency.constraint == new:
            return []
        return [
            Target(
                path=dependency.file,
                location=dependency.location,
                old=dependency.constraint,
                new=new,
            )
        ]


def _override_pins(project: Project, edit: Edit, new: str) -> list[Target]:
    """La version forcée réécrite par ``edit``, relue dans ``project``, à épingler."""
    wanted = edit.override
    if wanted is None:
        return []
    return [
        Target(path=found.file, location=found.location, old=found.constraint, new=new)
        for found in project.overrides
        if (found.file, found.section, found.key) == (wanted.file, wanted.section, wanted.key)
        and found.location is not None
        and found.constraint != new
    ]


def _lockfile_only(job: Job) -> list[str]:
    """Les paquets des mises à jour qu'une régénération seule ne fait pas bouger : les directes
    dont la contrainte accepte déjà la version, et les indirectes."""
    found = (u.name for _, u, o in job.choices if not u.direct or not o.edits)
    return list(dict.fromkeys(found))


def _upgrades(job: Job) -> list[str]:
    """``-P x==V`` pour chaque mise à jour (uv, pip-compile)."""
    pinned = {update.name: option.version for _, update, option in job.choices}
    return [word for name, version in pinned.items() for word in ("-P", f"{name}=={version}")]


# -- un pilote par outil ------------------------------------------------------


class _Driver:
    """Comment un outil régénère son lockfile."""

    def manual(self, job: Job) -> list[str]:
        """La commande à lancer à la main."""
        raise NotImplementedError

    def run(self, context: _Context) -> None:
        """Régénère le lockfile. Lève ``_Failed``."""
        raise NotImplementedError


class _Npm(_Driver):
    _ARGS = ("--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund")

    def manual(self, job: Job) -> list[str]:
        names = _lockfile_only(job)
        if names:
            return ["npm", "update", *names, "--package-lock-only", "--ignore-scripts"]
        return ["npm", "install", "--package-lock-only", "--ignore-scripts"]

    def run(self, context: _Context) -> None:
        base = ("install", *self._ARGS)
        names = context.names(direct=False)
        if not context.run_pinned(lambda version: version, *base):
            names = _lockfile_only(context.job)
        if names:
            everywhere = (
                ("--workspaces", "--include-workspace-root") if context.job.workspace else ()
            )
            context.run("update", *names, *everywhere, *self._ARGS)
        context.run(*base)


class _Pnpm(_Driver):
    _ARGS = ("--lockfile-only", "--ignore-scripts", "--ignore-pnpmfile")

    def manual(self, job: Job) -> list[str]:
        names = _lockfile_only(job)
        if names:
            recursive = ["-r"] if job.workspace else []
            return ["pnpm", "update", *recursive, *names, "--no-save", *self._ARGS]
        return ["pnpm", "install", *self._ARGS]

    def run(self, context: _Context) -> None:
        base = ("install", *self._ARGS, "--no-frozen-lockfile")
        names = context.names(direct=False)
        if not context.run_pinned(lambda version: version, *base):
            names = _lockfile_only(context.job)
        if names:
            recursive = ("-r",) if context.job.workspace else ()
            context.run("update", *recursive, *names, "--no-save", *self._ARGS)
        context.run(*base)


class _Yarn1(_Driver):
    def manual(self, job: Job) -> list[str]:
        names = _lockfile_only(job)
        if names:
            return ["yarn", "upgrade", *names, "--ignore-scripts"]
        return ["yarn", "install", "--ignore-scripts"]

    def run(self, context: _Context) -> None:
        path = context.root / context.job.lockfile
        old = {(update.name, update.current_version) for _, update, _ in context.job.choices}
        text = path.read_bytes().decode("utf-8")
        dropped = drop_yarn1_entries(text, old)
        if dropped != text:
            writers.replace_file(path, dropped.encode("utf-8"))
        # Yarn 1 n'a pas de mode « lockfile seul » : il installe, mais ailleurs que dans le
        # node_modules du projet, qui garderait sinon des paquets dont les scripts n'ont pas tourné.
        with tempfile.TemporaryDirectory(prefix="forceupdate-", ignore_cleanup_errors=True) as tmp:
            context.run(
                "install",
                "--ignore-scripts",
                "--ignore-engines",
                "--non-interactive",
                "--no-progress",
                "--modules-folder",
                tmp,
            )


def drop_yarn1_entries(text: str, packages: set[tuple[str, str | None]]) -> str:
    """``text`` (un ``yarn.lock`` de Yarn 1) sans les entrées des paquets ``(nom, version)`` :
    ``yarn install`` les résout à nouveau, à la plus haute version que permet chaque plage."""
    lines = text.split("\n")
    kept: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line[:1].strip() or line.startswith("#") or not line.rstrip().endswith(":"):
            kept.append(line)
            index += 1
            continue
        end = index + 1
        while end < len(lines) and lines[end].strip() and lines[end][:1].isspace():
            end += 1
        if _yarn1_entry(lines[index:end]) in packages:
            if end < len(lines) and not lines[end].strip():
                end += 1  # la ligne vide qui sépare les entrées
        else:
            kept += lines[index:end]
        index = end
    return "\n".join(kept)


def _yarn1_entry(block: Sequence[str]) -> tuple[str, str | None]:
    """Le paquet et la version d'une entrée de ``yarn.lock`` (Yarn 1)."""
    descriptor = block[0].rstrip().removesuffix(":").split(",")[0].strip().strip('"')
    at = descriptor.rfind("@")
    name = descriptor[:at] if at > 0 else descriptor
    for line in block[1:]:
        found = re.match(r'\s+version\s+"?([^"\s]+)"?', line.rstrip("\r"))
        if found is not None:
            return name, found.group(1)
    return name, None


class _Yarn(_Driver):
    def manual(self, job: Job) -> list[str]:
        names = _lockfile_only(job)
        if names:
            return ["yarn", "up", "-R", *names, "--mode=update-lockfile"]
        return ["yarn", "install", "--mode=update-lockfile"]

    def run(self, context: _Context) -> None:
        names = context.names()
        if names:
            context.run("up", "-R", *names, "--mode=update-lockfile")
        else:
            context.run("install", "--mode=update-lockfile")


class _Uv(_Driver):
    def manual(self, job: Job) -> list[str]:
        return ["uv", "lock", *_upgrades(job)]

    def run(self, context: _Context) -> None:
        context.run("lock", *_upgrades(context.job))


class _Poetry(_Driver):
    def manual(self, job: Job) -> list[str]:
        names = _lockfile_only(job)
        if names:
            return ["poetry", "update", "--lock", *names]
        return ["poetry", "lock", *job.options]

    def run(self, context: _Context) -> None:
        base = ("lock", *context.job.options, "--no-interaction")
        names = context.names(direct=False)
        if not context.run_pinned(lambda version: f"=={version}", *base):
            names = _lockfile_only(context.job)
        if names:
            context.run("update", "--lock", "--no-interaction", *names)
        context.run(*base)


class _Pdm(_Driver):
    def manual(self, job: Job) -> list[str]:
        names = _lockfile_only(job)
        if names:
            return ["pdm", "update", "--no-sync", "--update-reuse", *names]
        return ["pdm", "lock", "--update-reuse"]

    def run(self, context: _Context) -> None:
        base = ("lock", "--update-reuse")
        names = context.names(direct=False)
        if not context.run_pinned(lambda version: f"=={version}", *base):
            names = _lockfile_only(context.job)
        if names:
            context.run("update", "--no-sync", "--update-reuse", *names)
        context.run(*base)


class _Pipenv(_Driver):
    def manual(self, job: Job) -> list[str]:
        return ["pipenv", "lock"]

    def run(self, context: _Context) -> None:
        context.run("lock")


class _PipCompile(_Driver):
    def manual(self, job: Job) -> list[str]:
        return ["pip-compile", *self._arguments(job), *_upgrades(job)]

    def run(self, context: _Context) -> None:
        context.run("--quiet", *self._arguments(context.job), *_upgrades(context.job))

    @staticmethod
    def _arguments(job: Job) -> list[str]:
        """Les options et les sources ; ``--output-file`` seulement s'il ne va pas de soi
        (``requirements.in`` s'écrit dans ``requirements.txt``) : l'en-tête n'en change pas."""
        output = posixpath.basename(job.lockfile)
        if job.sources == (output.removesuffix(".txt") + ".in",):
            return [*job.options, *job.sources]
        return [*job.options, "--output-file", output, *job.sources]


class _UvPipCompile(_Driver):
    def manual(self, job: Job) -> list[str]:
        return ["uv", "pip", "compile", *self._arguments(job), *_upgrades(job)]

    def run(self, context: _Context) -> None:
        job = context.job
        context.run("pip", "compile", *self._arguments(job), "--quiet", *_upgrades(job))

    @staticmethod
    def _arguments(job: Job) -> list[str]:
        return [*job.sources, "-o", posixpath.basename(job.lockfile), *job.options]


_DRIVERS: dict[LockKind, _Driver] = {
    LockKind.NPM: _Npm(),
    LockKind.PNPM: _Pnpm(),
    LockKind.YARN_1: _Yarn1(),
    LockKind.YARN: _Yarn(),
    LockKind.UV: _Uv(),
    LockKind.POETRY: _Poetry(),
    LockKind.PDM: _Pdm(),
    LockKind.PIPENV: _Pipenv(),
    LockKind.PIP_COMPILE: _PipCompile(),
    LockKind.UV_PIP_COMPILE: _UvPipCompile(),
}
