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
``script.py.lock``            ``uv lock --script script.py`` (le lockfile d'un script à bloc
                              PEP 723, E28)
``poetry.lock``               ``poetry lock`` (``--no-update`` avant Poetry 2)
``pdm.lock``                  ``pdm lock --update-reuse``
``Pipfile.lock``              ``pipenv lock``
``.txt`` compilé (pip-tools)  la commande de son en-tête : ``pip-compile …`` ou
                              ``uv pip compile …``, avec les options connues (sa source peut
                              être un ``pyproject.toml``, E32)
``requirements.txt`` exporté  ``uv export …`` (son en-tête), ``pdm export …``, ``poetry export
                              …``, après le lockfile dont il vient (E32)
``Cargo.lock``                ``cargo update --workspace`` (ne résout que ce qui ne colle
                              plus au manifeste ; ``build.rs`` ne tourne pas)
``go.sum``                    ``go mod tidy`` (``go.mod`` déjà réécrit ; rien n'est compilé)
``composer.lock``             ``composer update x:V… -W --no-install --no-scripts
                              --no-plugins`` (rien n'est installé ni exécuté du projet)
``Gemfile.lock``              ``bundle lock`` (rien n'est installé ; le ``Gemfile`` et les
                              ``.gemspec`` sont évalués : c'est du Ruby)
``packages.lock.json``        ``dotnet restore <projet> --force-evaluate -noAutoResponse
                              -p:RestoreLockedMode=false`` (MSBuild évalue le projet ; les
                              paquets vont dans le cache de NuGet, ``obj/`` est écrit)
============================  ===========================================================

Vérifié avec npm 11.6, pnpm 12.15, Yarn 1.22 et 4.18, uv 0.10, Poetry 1.8 et 2.5, PDM 2.29,
pipenv 2026.10, pip-tools 7.6 (voir les notes de E11 dans ``PLAN.md``), cargo 1.99 (E21), Go 1.27
(E22), Composer 2.11 (E23), Bundler 4.0 (E24) et le SDK .NET 10.0.403 (E26).

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
- Cargo de même : ``=V`` le temps d'un ``cargo update --workspace``. Une indirecte : ``cargo
  update -p x@actuelle --precise V``. Pas ``--precise`` pour une directe : Cargo l'ignore dès que
  la contrainte réécrite n'accepte plus la version figée (il prend alors la plus haute) ;
- Go : rien à viser, ``go.mod`` dit déjà la version (directes et indirectes, réécrites par
  ``update.writers``). ``go mod tidy`` la garde, refait ``go.sum``, et fait monter ce que la
  sélection minimale exige (une dépendance de la nouvelle version qui en demande plus : la
  version relue le dit). Pas ``go get x@V`` : pour descendre, il retire les modules qui
  demandent plus (vérifié avec Go 1.27) ;
- Composer : ``composer update x:V``, une contrainte de plus le temps du passage, pour une directe
  comme pour une indirecte ; ``-W`` laisse bouger ce que la nouvelle version exige (une autre
  directe comprise), ``COMPOSER_MINIMAL_CHANGES`` rien d'autre. Pas ``update --lock`` : il garde
  une version que la contrainte réécrite n'accepte plus, et refait quand même le ``content-hash``
  (vérifié avec Composer 2.11) ;
- Bundler de même : ``= V`` à la place de la contrainte (du ``Gemfile`` ou du ``.gemspec``), et
  ``gem "x", "= V"`` ajouté à la fin du ``Gemfile`` pour une indirecte, le temps d'un ``bundle
  lock`` ; puis le ``Gemfile`` remis et ``bundle lock`` relancé, qui garde les versions (il ne
  défait que ce qui ne colle plus au ``Gemfile``). Sans épinglage, ``bundle lock --update x``
  prend la plus haute version permise, dépendances de x comprises ; ``--conservative`` ne bouge
  pas celles qu'une autre gem partage. Sous une autre plateforme que celles du lockfile (Windows
  pour un projet Linux), Bundler ajoute la sienne : elle est retirée ensuite (``--remove-platform``,
  qui ne change aucune version). Vérifié avec Bundler 4.0.20 ;
- NuGet : rien à viser, il prend la plus basse version qui convient, donc la borne basse que
  ``update.writers`` a réécrite (une version centrale, une propriété comprises) ; ``dotnet restore``
  refait alors le lockfile de lui-même (vérifié). ``--force-evaluate`` fait monter une version
  flottante (``1.*``), et ne change rien d'autre. Une indirecte ne monte pas ainsi : le
  planificateur la propose à la main. Le lockfile d'un autre projet qui lit une version réécrite
  (``Directory.Packages.props``) est régénéré aussi ;
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

**En plus** (``Job.extra``, E32), une case du plan cochée d'office : régénérer un
``package-lock.json`` avec le npm qu'attend le projet (``update.project_npm`` : ``npx -y npm@10``,
puis sa relecture par ``npm ci --dry-run``), refaire le ``vendor/`` d'un module Go (``go mod
vendor``, remis comme avant sur un échec). Décochée : ``decline``.
"""

import dataclasses
import enum
import itertools
import json
import logging
import os
import posixpath
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from forceupdate import engine, parsers, processes, versions
from forceupdate.detect.manifests import decode_text, ecosystem_for_manifest, match_dependency_file
from forceupdate.models import (
    Dependency,
    Ecosystem,
    Edit,
    EditKind,
    Event,
    EventKind,
    Project,
    Report,
    Scope,
    Update,
    UpdateOption,
)
from forceupdate.parsers import go, php, python, ruby
from forceupdate.parsers.base import ParseError, ReadText
from forceupdate.parsers.json_spans import BOM
from forceupdate.parsers.lockfiles import Lockfile, dependents, dirname, join
from forceupdate.parsers.python import is_script
from forceupdate.sources.local import LocalSource
from forceupdate.update import project_npm, writers
from forceupdate.update.writers import Changes, Choice, FileChange, Refused, Target
from forceupdate.update.writers.npm import PNPM_WORKSPACE

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_TOOLS",
    "LOCK_TIMEOUT",
    "Extra",
    "ExtraKind",
    "Installed",
    "Job",
    "LockKind",
    "LockStatus",
    "Reach",
    "Regenerated",
    "Tools",
    "Verified",
    "decline",
    "plan",
    "regenerate",
]

LOCK_TIMEOUT = 600.0
"""Délai maximal de chaque commande, en secondes, par défaut (``Tools.timeout``)."""


@dataclass(frozen=True, kw_only=True)
class Tools:
    """Comment lancer les outils : les réglages de la personne (E29, ``preferences``)."""

    timeout: float = LOCK_TIMEOUT
    """Le délai maximal de chaque commande, en secondes."""
    rust_default_toolchain: bool = False
    """Lancer cargo avec la chaîne d'outils par défaut de la personne (``rustup default``),
    pas celle d'un ``rust-toolchain.toml`` du projet, que rustup installerait."""


DEFAULT_TOOLS = Tools()

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
    UV_SCRIPT = "uv-script"
    """Le lockfile d'un script à bloc PEP 723 (``uv lock --script script.py`` écrit
    ``script.py.lock``, E28)."""
    POETRY = "poetry"
    PDM = "pdm"
    PIPENV = "pipenv"
    PIP_COMPILE = "pip-compile"
    UV_PIP_COMPILE = "uv-pip-compile"
    """Un ``.txt`` compilé par ``uv pip compile`` (son en-tête le dit)."""
    UV_EXPORT = "uv-export"
    """Un ``requirements.txt`` écrit par ``uv export`` : refait après ``uv.lock`` (E32)."""
    POETRY_EXPORT = "poetry-export"
    """Un ``requirements.txt`` exporté de ``poetry.lock`` (``poetry export``, sans en-tête)."""
    PDM_EXPORT = "pdm-export"
    """Un ``requirements.txt`` écrit par ``pdm export``."""
    CARGO = "cargo"
    GO = "go"
    COMPOSER = "composer"
    BUNDLER = "bundler"
    NUGET = "nuget"


_TOOL_NAMES = {
    LockKind.NPM: "npm",
    LockKind.PNPM: "pnpm",
    LockKind.YARN_1: "Yarn 1",
    LockKind.YARN: "Yarn",
    LockKind.UV: "uv",
    LockKind.UV_SCRIPT: "uv",
    LockKind.POETRY: "Poetry",
    LockKind.PDM: "PDM",
    LockKind.PIPENV: "pipenv",
    LockKind.PIP_COMPILE: "pip-compile",
    LockKind.UV_PIP_COMPILE: "uv pip compile",
    LockKind.UV_EXPORT: "uv export",
    LockKind.POETRY_EXPORT: "poetry export",
    LockKind.PDM_EXPORT: "pdm export",
    LockKind.CARGO: "Cargo",
    LockKind.GO: "Go",
    LockKind.COMPOSER: "Composer",
    LockKind.BUNDLER: "Bundler",
    LockKind.NUGET: "dotnet",
}

_PROGRAMS = {
    LockKind.NPM: "npm",
    LockKind.PNPM: "pnpm",
    LockKind.YARN_1: "yarn",
    LockKind.YARN: "yarn",
    LockKind.UV: "uv",
    LockKind.UV_SCRIPT: "uv",
    LockKind.POETRY: "poetry",
    LockKind.PDM: "pdm",
    LockKind.PIPENV: "pipenv",
    LockKind.PIP_COMPILE: "pip-compile",
    LockKind.UV_PIP_COMPILE: "uv",
    LockKind.UV_EXPORT: "uv",
    LockKind.POETRY_EXPORT: "poetry",
    LockKind.PDM_EXPORT: "pdm",
    LockKind.CARGO: "cargo",
    LockKind.GO: "go",
    LockKind.COMPOSER: "composer",
    LockKind.BUNDLER: "bundle",
    LockKind.NUGET: "dotnet",
}
"""Le programme de chaque outil, cherché par ``shutil.which`` (sous Windows, ``composer`` est le
``composer.bat`` de son installateur, qui lance ``php composer.phar`` ; ``bundle``, le
``bundle.bat`` de RubyInstaller)."""

_UV_BUILDS = (
    "uv construit les paquets publiés sans wheel dont il lit les dépendances, et le projet si "
    "elles sont dynamiques : leur code de construction s'exécute."
)
"""``--no-build`` l'empêcherait, mais il change la résolution : un paquet sans wheel pour une
seule plateforme la rend impossible (``sslyze`` dans Argos). Il n'est donc pas passé."""

_RUNS_CODE = {
    LockKind.UV: _UV_BUILDS,
    LockKind.UV_SCRIPT: _UV_BUILDS,
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
    LockKind.BUNDLER: (
        "Bundler exécute le Gemfile (c'est du Ruby), ce qu'il charge (eval_gemfile) et les "
        ".gemspec du projet, de ses gems path: et git: ; aucune option ne l'en empêche."
    ),
    LockKind.NUGET: (
        "dotnet restore évalue le projet avec MSBuild : une cible du projet ou de ses "
        "Directory.Build.targets accrochée à la restauration s'exécute, comme un SDK de projet "
        "venu de NuGet ; il écrit aussi le dossier obj/ du projet."
    ),
}
"""Ce que l'outil exécute quand même, faute d'option pour l'en empêcher (brief, piège
« Régénérer un lockfile peut exécuter du code du projet »)."""


class ExtraKind(enum.StrEnum):
    """Ce que forceupdate propose de faire en plus pour un lockfile (``Extra``)."""

    PROJECT_NPM = "project-npm"
    """Régénérer avec le npm qu'attend le projet (``npx -y npm@10``), pas celui de la machine, puis
    vérifier le lockfile avec lui (``npm ci --dry-run``) : ``update.project_npm``."""
    GO_VENDOR = "go-vendor"
    """Refaire ``vendor/`` après ``go mod tidy`` (``go mod vendor``) : sinon ``go build`` refuse un
    ``vendor/modules.txt`` périmé. ``vendor/`` est remis comme avant si une commande échoue."""


@dataclass(frozen=True, kw_only=True)
class Extra:
    """Ce que forceupdate propose de faire en plus pour un lockfile : une case du plan, cochée
    d'office (décidé avec l'utilisateur, session 29) ; décochée, ``decline``."""

    kind: ExtraKind
    label: str
    """La case, en quelques mots : « Régénérer avec npm 10, celui du projet »."""
    detail: str
    """Pourquoi, et ce que ça fait."""


@dataclass(frozen=True, kw_only=True)
class Verified:
    """Le lockfile régénéré, relu par l'outil qu'attend le projet (``ExtraKind.PROJECT_NPM`` :
    ``npm ci --dry-run`` de son npm, qui n'installe rien)."""

    command: str
    """La commande, à lancer dans le dossier du lockfile pour reproduire."""
    error: str | None = None
    """``None`` : accepté ; sinon, ce que l'outil reproche (« Missing: zod@3.25.76 from lock
    file »). Le lockfile reste régénéré."""


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
    timeout: float = LOCK_TIMEOUT
    """Le délai maximal de chaque commande, en secondes (``Tools.timeout``)."""
    toolchain: str | None = None
    """Cargo : la chaîne d'outils par défaut de la personne, passée par ``RUSTUP_TOOLCHAIN``
    (``Tools.rust_default_toolchain``) ; ``None`` : celle que choisit rustup."""
    extra: Extra | None = None
    """Ce que forceupdate propose en plus (le npm du projet, ``go mod vendor``) : fait si
    ``accepted``."""
    accepted: bool = True
    """La case de ``extra`` est cochée (d'office ; ``decline`` la décoche)."""
    launcher: tuple[str, ...] = ()
    """Ce qui lance l'outil à la place de ``program`` : ``npx -y npm@10`` (le npm du projet,
    ``ExtraKind.PROJECT_NPM`` accepté) ; vide, ``program``."""

    @property
    def doing(self) -> ExtraKind | None:
        """Ce que forceupdate fait en plus : ``extra``, s'il est accepté."""
        return self.extra.kind if self.extra is not None and self.accepted else None

    @property
    def refreshes(self) -> tuple[str, ...]:
        """Les dossiers que l'outil refait en plus du lockfile (``vendor/`` de ``go mod vendor``),
        relatifs à la racine de la source : à remettre s'il échoue, à commiter sinon."""
        if self.doing is ExtraKind.GO_VENDOR:
            return (join(self.directory, "vendor"),)
        return ()

    @property
    def tool(self) -> str:
        """Le nom de l'outil, pour le dire ; ``npm 10`` lancé par ``launcher``."""
        if self.launcher:
            return f"{_TOOL_NAMES[self.kind]} {self.launcher[-1].rpartition('@')[2]}"
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
    verified: Verified | None = None
    """``REGENERATED`` avec le npm du projet : ce qu'en dit ``npm ci --dry-run`` de ce npm."""


# ---------------------------------------------------------------------------
# Le plan : quels lockfiles, avec quelle commande
# ---------------------------------------------------------------------------


def plan(
    source: LocalSource, report: Report, changes: Changes, tools: Tools = DEFAULT_TOOLS
) -> tuple[Job, ...]:
    """Les lockfiles à régénérer après ``changes`` (``writers.prepare``), sans rien lancer :
    ceux des options appliquées, ceux de NuGet qui lisent une version réécrite ailleurs
    (``_readers``), puis les ``.txt`` de pip-tools, dont ceux qui citent un fichier réécrit ou un
    autre ``.txt`` régénéré. Dans l'ordre où les régénérer, lancés selon ``tools`` (les réglages
    de la personne).

    ``report`` est l'analyse qui a donné ``changes``. Lève ``ValueError`` pour un lockfile que
    forceupdate ne sait pas régénérer."""
    by_lockfile: dict[str, list[Choice]] = {}
    for choice in changes.applied:
        project, update, option = choice
        if option.lockfile and writers.constraints_file(project, update, option) is None:
            by_lockfile.setdefault(option.lockfile, []).append(choice)
    changed = {change.path for change in changes.files}
    compiled = _compiled_files(source, report)
    cargo = any(PurePosixPath(path).name == "Cargo.lock" for path in by_lockfile)
    rust = _rustup_default() if tools.rust_default_toolchain and cargo else None
    probes = _Probes()

    def job(
        path: str, choices: Sequence[Choice], compiled_file: "_Compiled | None", reason: str | None
    ) -> Job:
        return _job(
            source, report, path, choices, changed, compiled_file, reason, tools, rust, probes
        )

    jobs = [
        job(path, choices, None, None)
        for path, choices in sorted(by_lockfile.items())
        if path not in compiled
    ]
    for path, reason in _readers(report, changes, set(by_lockfile)):
        jobs.append(job(path, [], None, reason))
    regenerated: set[str] = set()
    for path in _pip_tools_order(compiled, set(by_lockfile), changed):
        reason = None
        if path not in by_lockfile:
            cited = sorted(compiled[path].closure & (changed | regenerated))
            reason = f"{', '.join(cited)} {'a' if len(cited) == 1 else 'ont'} changé"
        jobs.append(job(path, by_lockfile.get(path, []), compiled[path], reason))
        regenerated.add(path)
    planned = {job.lockfile for job in jobs}
    for path, export in sorted(_exports(source, report, compiled).items()):
        if export.base in planned and path not in planned:
            jobs.append(_export_job(path, export, tools))
    return tuple(jobs)


def _job(
    source: LocalSource,
    report: Report,
    path: str,
    choices: Sequence[Choice],
    changed: set[str],
    compiled: "_Compiled | None",
    reason: str | None,
    tools: "Tools",
    rust_toolchain: str | None,
    probes: "_Probes",
) -> Job:
    projects = _projects_of(report, path)
    warnings: list[str] = []
    options: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    extra: Extra | None = None
    launcher: tuple[str, ...] = ()
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
    elif kind is LockKind.CARGO:
        warnings += _cargo_runs_code(source.read_text, dirname(path), tools, rust_toolchain)
    elif kind is LockKind.GO:
        warnings += _go_warnings(source.read_text, dirname(path))
        extra = _go_vendor(source.read_text, dirname(path))
    elif kind is LockKind.COMPOSER:
        version = probes.version(program, _COMPOSER_VERSION) if program is not None else None
        warnings += _composer_warnings(source.read_text, dirname(path), version)
    elif kind is LockKind.NPM and program is not None:
        found = _project_npm(source.read_text, path, projects, program, probes)
        if isinstance(found, str):
            warnings.append(found)
        elif found is not None:
            extra, launcher = found
    if kind is LockKind.BUNDLER:
        warnings += _bundler_warnings(source.read_text, path)
    if kind is LockKind.NUGET:
        warnings += _dotnet_warnings(source.read_text, dirname(path))
        options = _dotnet_project(projects, path)
        if program is not None and not _dotnet_sdk(program):
            program = None  # le dotnet des runtimes seuls : pas de SDK, pas de restore
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
        timeout=tools.timeout,
        toolchain=rust_toolchain if kind is LockKind.CARGO else None,
        extra=extra,
        launcher=launcher,
    )
    return dataclasses.replace(job, command=shlex.join(_DRIVERS[kind].manual(job)))


def decline(jobs: Sequence[Job], lockfiles: Iterable[str]) -> tuple[Job, ...]:
    """``jobs``, la case de ``Job.extra`` décochée pour les lockfiles ``lockfiles`` : le npm de
    la machine plutôt que celui du projet, pas de ``go mod vendor``. La commande à lancer à la main
    suit."""
    refused = set(lockfiles)
    found = []
    for job in jobs:
        if job.lockfile in refused and job.extra is not None and job.accepted:
            job = dataclasses.replace(job, accepted=False, launcher=())
            job = dataclasses.replace(job, command=shlex.join(_DRIVERS[job.kind].manual(job)))
        found.append(job)
    return tuple(found)


class _Probes:
    """La version des outils de la machine, demandée une fois par plan (``npm --version``…) : un
    outil ne change pas pendant qu'on prépare un plan."""

    def __init__(self) -> None:
        self._found: dict[tuple[str, ...], str | None] = {}

    def version(self, program: str | None, pattern: re.Pattern[str]) -> str | None:
        """La version que ``program --version`` écrit (le premier groupe de ``pattern``) ;
        ``None`` sans programme, ou si on ne la lit pas."""
        if program is None:
            return None
        key = (program, pattern.pattern)
        if key not in self._found:
            self._found[key] = _tool_version(program, pattern)
        return self._found[key]


def _tool_version(program: str, pattern: re.Pattern[str]) -> str | None:
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
    if result.returncode != 0:
        return None
    found = pattern.search(_decode(result.stdout))
    return found.group(1) if found else None


_PLAIN_VERSION = re.compile(r"^\s*v?(\d+\.\d+\.\d+\S*)\s*$", re.MULTILINE)
"""``npm --version`` : « 11.6.2 » ; ``node --version`` : « v24.12.0 »."""
_COMPOSER_VERSION = re.compile(r"Composer (?:version )?(\d+\.\d+\.\d+)")
"""``composer --version`` : « Composer version 2.9.8 2026-05-13 09:28:38 »."""


def _project_npm(
    read_text: ReadText,
    lockfile: str,
    projects: Sequence[Project],
    program: str,
    probes: _Probes,
) -> tuple[Extra, tuple[str, ...]] | str | None:
    """Le npm qu'attend le projet du lockfile, s'il n'est pas celui de la machine
    (``update.project_npm``) : la case du plan et ce qui lance ce npm (``npx -y npm@10``) ; un
    avertissement seul quand forceupdate ne peut pas le lancer ; ``None`` si rien n'est attendu,
    ou si le npm de la machine convient. ``npm --version`` (et ``node --version`` pour
    ``engines.node``) n'est demandé que si le projet dit quelque chose."""
    directory = dirname(lockfile)
    content = _read_quietly(read_text, join(directory, "package.json"))
    try:
        manifest = json.loads((content or "").removeprefix(BOM))
    except ValueError:
        manifest = None
    runtimes = [runtime for project in projects for runtime in project.runtimes]
    if not project_npm.declared(manifest, runtimes):
        return None
    installed = probes.version(program, _PLAIN_VERSION)
    if installed is None:
        return None

    def node() -> str | None:
        return probes.version(_which("node"), _PLAIN_VERSION)

    expected = project_npm.expected(manifest, runtimes, installed, node)
    if expected is None:
        return None
    major = expected.major
    risk = (
        f"npm {installed} ici ; le projet attend npm {major} : {expected.source}. Un lockfile "
        "écrit par un autre npm risque d'être refusé par « npm ci » de sa CI"
    )
    if major < project_npm.MIN_NPM:
        return (
            f"{risk}. forceupdate ne lance pas un npm si ancien : il réécrirait le lockfile dans "
            "un format plus ancien."
        )
    npx = _which("npx")
    if npx is None:
        return f"{risk}, et npx n'est pas là pour lancer npm {major}."
    detail = (
        f"{risk} : forceupdate le régénère avec npm {major}, par npx, sans toucher au npm de cet "
        f"ordinateur, puis le fait relire par npm {major} (npm ci, à blanc)."
    )
    extra = Extra(
        kind=ExtraKind.PROJECT_NPM,
        label=f"Régénérer avec npm {major}, celui du projet",
        detail=detail,
    )
    return extra, (npx, "-y", f"npm@{major}")


def _go_vendor(read_text: ReadText, directory: str) -> Extra | None:
    """La case « refaire vendor/ » d'un module qui en a un (``vendor/modules.txt``)."""
    if _read_quietly(read_text, join(directory, "vendor/modules.txt")) is None:
        return None
    return Extra(
        kind=ExtraKind.GO_VENDOR,
        label="Refaire vendor/ (go mod vendor)",
        detail=(
            "Le module a un dossier vendor/ : après go mod tidy, go build refuse un "
            "vendor/modules.txt périmé. forceupdate lance go mod vendor, et remet vendor/ comme "
            "avant si une commande échoue."
        ),
    )


def _readers(report: Report, changes: Changes, known: set[str]) -> list[tuple[str, str]]:
    """Les lockfiles NuGet d'autres projets qui lisent une version réécrite (une version centrale
    de ``Directory.Packages.props``, une propriété de ``Directory.Build.props``), et pourquoi : sans
    être régénérés, ils ne diraient plus ce que restaure ``dotnet``."""
    rewritten = {
        (edit.file, edit.location)
        for _, _, option in changes.applied
        for edit in option.edits
        if edit.location is not None
    }
    # Une version centrale ajoutée (E32 : EditKind.REFERENCE), et l'épinglage des indirectes avec
    # elle : tout projet qui lit ce Directory.Packages.props peut en changer.
    referenced = any(
        edit.kind is EditKind.REFERENCE for _, _, option in changes.applied for edit in option.edits
    )
    centrals = {
        change.path
        for change in changes.files
        if referenced and posixpath.basename(change.path) == "Directory.Packages.props"
    }
    found: dict[str, set[str]] = {}
    for project in report.projects:
        for dependency in project.dependencies:
            lockfile = dependency.lockfile
            if (
                lockfile is not None
                and lockfile not in known
                and dependency.ecosystem is Ecosystem.NUGET
                and (
                    (dependency.file, dependency.location) in rewritten
                    or dependency.file in centrals
                )
            ):
                found.setdefault(lockfile, set()).add(dependency.file)
    return [
        (path, f"{', '.join(sorted(files))} {'a' if len(files) == 1 else 'ont'} changé")
        for path, files in sorted(found.items())
    ]


def _kind(source: LocalSource, path: str) -> LockKind:
    """Le format du lockfile ``path``, d'après son nom (et son contenu pour ``yarn.lock``)."""
    name = posixpath.basename(path)
    if name == "yarn.lock":
        content = _read_quietly(source.read_text, path) or ""
        berry = re.search(r"^__metadata:", content, re.MULTILINE) is not None
        return LockKind.YARN if berry else LockKind.YARN_1
    if name.endswith(".lock") and is_script(name.removesuffix(".lock")):
        return LockKind.UV_SCRIPT
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
    "Cargo.lock": LockKind.CARGO,
    "go.sum": LockKind.GO,
    "composer.lock": LockKind.COMPOSER,
    "Gemfile.lock": LockKind.BUNDLER,
    "gems.locked": LockKind.BUNDLER,
    "packages.lock.json": LockKind.NUGET,
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


_CARGO_TOOLCHAIN = ("rust-toolchain.toml", "rust-toolchain")
_CARGO_CONFIG = (".cargo/config.toml", ".cargo/config")


def _cargo_runs_code(
    read_text: ReadText, directory: str, tools: "Tools", default: str | None
) -> list[str]:
    """Ce que cargo, et rustup derrière lui, prennent du projet : la chaîne d'outils de
    ``rust-toolchain.toml``, la configuration de ``.cargo/config.toml``. Cherchés dans le
    dossier du lockfile et ses parents, comme les lisent rustup et cargo. Le ``rustc`` et les
    « wrappers » qu'y désignerait la configuration, eux, sont écartés (``_cargo_environment``).
    Avec ``tools.rust_default_toolchain``, la chaîne d'outils par défaut de la personne
    (``default``, ``_rustup_default``) passe devant celle du projet (``RUSTUP_TOOLCHAIN``)."""
    found: dict[str, str] = {}
    for folder in [directory, *_parents(directory)]:
        for name in (*_CARGO_TOOLCHAIN, *_CARGO_CONFIG):
            if name not in found and _read_quietly(read_text, join(folder, name)) is not None:
                found[name] = join(folder, name)
    warnings = []
    toolchain = next((found[name] for name in _CARGO_TOOLCHAIN if name in found), None)
    if toolchain is not None and default is not None:
        warnings.append(
            f"{toolchain} n'est pas suivi : cargo tourne avec la chaîne d'outils par défaut, "
            f"{default} (réglage « chaîne d'outils Rust ») ; plus ancienne que ce que demande le "
            "projet, la régénération peut échouer."
        )
    elif toolchain is not None:
        absent = " (réglage « chaîne d'outils Rust » : rustup n'en a pas par défaut)"
        warnings.append(
            f"rustup lit {toolchain} : il installe s'il le faut, puis lance, la chaîne d'outils "
            "qu'il désigne, même un dossier du projet"
            + (absent if tools.rust_default_toolchain else "")
            + "."
        )
    config = next((found[name] for name in _CARGO_CONFIG if name in found), None)
    if config is not None:
        warnings.append(
            f"cargo lit {config} : les registres et les sources qu'il désigne, et les programmes "
            "d'identification (credential-provider) qu'il lance pour un registre privé."
        )
    return warnings


def _go_warnings(read_text: ReadText, directory: str) -> list[str]:
    """Ce que ``go mod tidy`` ne fera pas, ou fera autrement que ne le demande le module : la
    chaîne d'outils de la directive ``toolchain`` (``GOTOOLCHAIN=local``). Le dossier ``vendor/``
    est une case du plan (``_go_vendor``)."""
    warnings = []
    content = _read_quietly(read_text, join(directory, go.MANIFEST))
    try:
        parsed = go.parse_go_mod_file(join(directory, go.MANIFEST), content or "")
    except ParseError:
        parsed = None
    if parsed is not None and parsed.toolchain is not None:
        warnings.append(
            f"go.mod demande {parsed.toolchain} : forceupdate lance le go installé, sans en "
            "télécharger un autre (GOTOOLCHAIN=local) ; plus ancien que la directive go, il "
            "échoue, et rien ne change."
        )
    return warnings


_VENDOR_LEFT = (
    "vendor/ n'est pas refait : lancer go mod vendor après la mise à jour (go build refuse un "
    "vendor/modules.txt périmé)."
)


def _composer_warnings(read_text: ReadText, directory: str, version: str | None) -> list[str]:
    """Ce que fera ``composer update`` autrement que ne le demande le projet, ou ce qu'il ne fera
    pas : le blocage des versions à faille levé (Composer 2.10 et plus ; ``version`` est celle du
    Composer installé, ``None`` si on ne la connaît pas) ou pas (Composer 2.9), le PHP de la
    machine pris faute de ``config.platform.php``, ``vendor/`` laissé tel quel
    (``--no-install``)."""
    warnings = []
    config = _composer_config(read_text, directory)
    release = _numbers(version)
    if _composer_unblocks(config) and release[:2] == (2, 9):
        warnings.append(
            f"Composer {version} refuse toute version qui garde une faille connue, et ce blocage "
            "ne se lève que dans composer.json (config.audit.block-insecure à false) : "
            "forceupdate n'y touche pas. Une version visée qui en garde une fait échouer la "
            "régénération (tout est remis) ; Composer 2.10 et plus le lève de lui-même le temps "
            "du passage."
        )
    elif _composer_unblocks(config) and not (release and release < (2, 9)):
        warnings.append(
            "Composer ne refuse pas, le temps de la régénération, une version qui a encore une "
            "faille connue (COMPOSER_POLICY_ADVISORIES_BLOCK=0, Composer 2.10 et plus) : "
            "forceupdate montre celles qui restent. Les logiciels malveillants restent bloqués."
        )
    platform = config.get("platform")
    if not (isinstance(platform, dict) and isinstance(platform.get("php"), str)):
        warnings.append(
            "Sans config.platform.php dans composer.json, Composer choisit les versions pour le "
            "PHP de cette machine."
        )
    if _read_quietly(read_text, join(directory, "vendor/composer/installed.json")) is not None:
        warnings.append(
            "vendor/ n'est pas mis à jour : lancer composer install après la mise à jour."
        )
    return warnings


def _numbers(version: str | None) -> tuple[int, ...]:
    """Les nombres d'une version (``2.9.8`` → ``(2, 9, 8)``) ; vide pour ``None``."""
    return tuple(int(part) for part in re.findall(r"\d+", version or ""))


def _composer_config(read_text: ReadText, directory: str) -> dict[str, Any]:
    """La table ``config`` du ``composer.json`` de ``directory`` ; vide s'il n'y en a pas."""
    content = _read_quietly(read_text, join(directory, php.MANIFEST))
    try:
        data = json.loads((content or "").removeprefix(BOM))
    except ValueError:
        return {}
    config = data.get("config") if isinstance(data, dict) else None
    return config if isinstance(config, dict) else {}


def _composer_unblocks(config: Mapping[str, Any]) -> bool:
    """Vrai si forceupdate lève le blocage des versions à faille : ni le projet (``config``) ni la
    personne (``COMPOSER_POLICY_ADVISORIES_BLOCK`` déjà là) ne le règlent."""
    return "COMPOSER_POLICY_ADVISORIES_BLOCK" not in os.environ and not _composer_sets_blocking(
        config
    )


def _composer_sets_blocking(config: Mapping[str, Any]) -> bool:
    """Vrai si le projet règle lui-même le blocage des versions à faille : ``config.policy`` (tout,
    ou ``advisories``), ou l'ancien ``config.audit.block-insecure`` (Composer 2.9). forceupdate le
    respecte alors."""
    policy = config.get("policy")
    if isinstance(policy, bool) or (isinstance(policy, dict) and "advisories" in policy):
        return True
    audit = config.get("audit")
    return isinstance(audit, dict) and "block-insecure" in audit


def _bundler_warnings(read_text: ReadText, lockfile: str) -> list[str]:
    """Ce que Bundler fera autrement que ne le demande le plan : écarter les versions trop
    récentes (``cooldown``, Bundler 4 : dans le ``Gemfile``, la configuration du projet ou
    ``BUNDLE_COOLDOWN``), que forceupdate respecte."""
    directory = dirname(lockfile)
    gemfile = _read_quietly(read_text, join(directory, _bundler_gemfile(lockfile))) or ""
    config = _read_quietly(read_text, join(directory, ".bundle/config")) or ""
    configured = os.environ.get("BUNDLE_COOLDOWN", "").strip() not in ("", "0")
    if not (configured or "BUNDLE_COOLDOWN" in config or re.search(r"\bcooldown:", gemfile)):
        return []
    return [
        "Bundler écarte les versions publiées depuis peu (cooldown) : une version visée trop "
        "récente n'est pas prise, la plus haute permise plus ancienne l'est à sa place."
    ]


def _dotnet_warnings(read_text: ReadText, directory: str) -> list[str]:
    """Ce que ``dotnet restore`` fera autrement que ne le demande le plan : le SDK que demande un
    ``global.json`` (s'il n'est pas installé, il échoue), les sources de paquets d'un
    ``nuget.config`` (forceupdate a regardé nuget.org)."""
    warnings = []
    for folder in [directory, *_parents(directory)]:
        content = _read_quietly(read_text, join(folder, "global.json"))
        if content is None:
            continue
        try:
            data = json.loads(content.removeprefix(BOM))
        except ValueError:
            data = None
        sdk = data.get("sdk") if isinstance(data, dict) else None
        version = sdk.get("version") if isinstance(sdk, dict) else None
        if isinstance(version, str):
            warnings.append(
                f"{join(folder, 'global.json')} demande le SDK .NET {version} : dotnet échoue "
                "s'il n'est pas installé (rien ne change alors)."
            )
        break
    for folder in [directory, *_parents(directory)]:
        found = next(
            (
                join(folder, name)
                for name in _NUGET_CONFIGS
                if _read_quietly(read_text, join(folder, name)) is not None
            ),
            None,
        )
        if found is not None:
            warnings.append(
                f"{found} : dotnet restaure depuis ses sources de paquets (celles où forceupdate "
                "a cherché les versions), avec leurs identifiants."
            )
            break
    return warnings


_NUGET_CONFIGS = ("nuget.config", "NuGet.Config", "NuGet.config")


def _dotnet_project(projects: Sequence[Project], lockfile: str) -> tuple[str, ...]:
    """Le projet MSBuild à restaurer, dans le dossier du lockfile : à nommer, un dossier peut
    aussi avoir une solution (``dotnet`` refuse alors de choisir)."""
    found = sorted(
        posixpath.basename(manifest)
        for project in projects
        for manifest in project.manifests
        if dirname(manifest) == dirname(lockfile)
        and posixpath.splitext(manifest)[1].lower() in (".csproj", ".fsproj", ".vbproj")
    )
    return tuple(found[:1])


def _dotnet_sdk(program: str) -> bool:
    """Vrai si ``dotnet`` a un SDK (``dotnet --list-sdks`` en cite un) : celui des runtimes
    seuls ne sait pas restaurer."""
    try:
        result = _spawn(
            [program, "--list-sdks"],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            env={**_environment(), **_dotnet_environment()},
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and bool(_decode(result.stdout).strip())


def _bundler_gemfile(lockfile: str) -> str:
    """Le nom du ``Gemfile`` d'un lockfile de Bundler : ``gems.rb`` pour ``gems.locked``."""
    name = posixpath.basename(lockfile)
    return next((m for m, lock in ruby.MANIFESTS.items() if lock == name), "Gemfile")


def _parents(directory: str) -> list[str]:
    """Les dossiers parents de ``directory`` dans la source, du plus proche à la racine."""
    if directory == ".":
        return []
    parts = directory.split("/")
    return ["/".join(parts[:i]) for i in range(len(parts) - 1, 0, -1)] + ["."]


def _projects_of(report: Report, lockfile: str) -> list[Project]:
    return [project for project in report.projects if lockfile in project.lockfiles]


def _manifests_of(report: Report, lockfile: str) -> set[str]:
    """Les manifestes que fige ``lockfile`` : ceux de son écosystème dans les projets qui
    l'ont, plus le ``pnpm-workspace.yaml`` de son dossier pour npm (catalogues, versions
    forcées), et le ``go.mod`` d'un ``go.sum`` (que le projet n'a pas toujours encore). Un
    projet qui a aussi un ``requirements.txt`` ne le mêle pas à son ``package-lock.json``."""
    ecosystem = ecosystem_for_manifest(lockfile)
    found = {
        manifest
        for project in _projects_of(report, lockfile)
        for manifest in project.manifests
        if ecosystem_for_manifest(manifest) is ecosystem
    }
    if ecosystem is Ecosystem.NPM:
        found.add(join(dirname(lockfile), PNPM_WORKSPACE))
    if posixpath.basename(lockfile) == go.LOCKFILE:
        found.add(join(dirname(lockfile), go.MANIFEST))
    if ecosystem is Ecosystem.NUGET:
        # Les versions écrites ailleurs : Directory.Packages.props, Directory.Build.props.
        found |= {
            dependency.file
            for project in _projects_of(report, lockfile)
            for dependency in project.dependencies
            if dependency.file != lockfile
        }
    return found


def _read_quietly(read_text: ReadText, path: str) -> str | None:
    try:
        return read_text(path)
    except ValueError:
        return None


def _rustup_default() -> str | None:
    """La chaîne d'outils par défaut de rustup (« stable-x86_64-pc-windows-msvc (default) »,
    vérifié avec rustup 1.29) ; ``None`` sans rustup, ou sans chaîne d'outils par défaut.
    ``rustup default`` ne lit pas le ``rust-toolchain.toml`` du dossier."""
    program = _which("rustup")
    if program is None:
        return None
    try:
        result = _spawn(
            [program, "default"],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            env=_environment(),
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    words = _decode(result.stdout).split()
    if result.returncode != 0 or not words or words[0].startswith(("error", "no")):
        return None
    return words[0]


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
    du même nom parmi ses manifestes, ou dont l'en-tête compile un manifeste (``pip-compile
    pyproject.toml``, E32)."""
    found = {}
    for project in report.projects:
        sources = {m.lower(): m for m in project.manifests if m.endswith(".in")}
        for path in project.lockfiles:
            if not path.endswith(".txt") or path in found:
                continue
            source_in = sources.get(path[: -len(".txt")].lower() + ".in")
            if source_in is not None or _compiles_a_manifest(source, path):
                found[path] = _compiled(source, path, source_in)
    return {
        path: dataclasses.replace(item, lockfiles=frozenset(item.closure & (found.keys() - {path})))
        for path, item in found.items()
    }


def _compiles_a_manifest(source: LocalSource, path: str) -> bool:
    """Vrai pour un ``.txt`` dont l'en-tête compile un manifeste (``pip-compile pyproject.toml``,
    ``uv pip compile setup.cfg``) : le lockfile de ce manifeste (``parsers.python``)."""
    found = python.generated(_read_quietly(source.read_text, path) or "")
    if found is None or found.tool not in ("pip-compile", "uv pip compile"):
        return False
    names = [posixpath.basename(s) for s in found.sources]
    return any(name in python.MANIFEST_SOURCES for name in names)


def _compiled(source: LocalSource, path: str, source_in: str | None) -> _Compiled:
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
    if not sources and source_in is not None:
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


@dataclass(frozen=True, kw_only=True)
class _Export:
    """Un ``requirements.txt`` exporté d'un lockfile du projet (E32 : ``uv export``, ``poetry
    export``, ``pdm export``) : refait après lui, par la commande de l'outil."""

    kind: LockKind
    base: str
    """Le lockfile dont il est l'export (``uv.lock``…)."""
    options: tuple[str, ...]
    warnings: tuple[str, ...] = ()


_EXPORT_BASES = {
    "uv.lock": LockKind.UV_EXPORT,
    "poetry.lock": LockKind.POETRY_EXPORT,
    "pdm.lock": LockKind.PDM_EXPORT,
}

_UV_EXPORT_FLAGS = frozenset(
    {
        "--no-hashes",
        "--no-dev",
        "--only-dev",
        "--dev",
        "--all-groups",
        "--no-default-groups",
        "--all-extras",
        "--no-emit-project",
        "--no-emit-workspace",
        "--no-emit-local",
        "--no-header",
        "--no-annotate",
        "--all-packages",
        "--no-editable",
    }
)
_UV_EXPORT_VALUED = frozenset(
    {
        "--format",
        "--group",
        "--no-group",
        "--only-group",
        "--extra",
        "--no-extra",
        "--no-emit-package",
        "--package",
        "--prune",
    }
)
"""Les options de ``uv export`` reprises de l'en-tête : ce qui est exporté, et la forme du
fichier. Une autre n'est pas reprise, et le plan le dit."""


def _exports(
    source: LocalSource, report: Report, compiled: Mapping[str, _Compiled]
) -> dict[str, _Export]:
    """Les exports de la source : les ``requirements*.txt`` qu'un projet range parmi ses
    lockfiles (``parsers.python``) sans qu'ils soient compilés par pip-tools, avec le lockfile
    dont ils viennent (``uv.lock``, ``poetry.lock``, ``pdm.lock``)."""
    found: dict[str, _Export] = {}
    for project in report.projects:
        base = next((p for p in project.lockfiles if posixpath.basename(p) in _EXPORT_BASES), None)
        if base is None:
            continue
        for path in project.lockfiles:
            match = match_dependency_file(path)
            if path in compiled or path in found or match is None:
                continue
            if match.pattern not in ("requirements*.txt", "requirements/*.txt"):
                continue
            content = _read_quietly(source.read_text, path) or ""
            found[path] = _export(source, project, path, content, base)
    return found


def _export(source: LocalSource, project: Project, path: str, content: str, base: str) -> _Export:
    """Comment refaire l'export ``path`` (son contenu, ``content``) du lockfile ``base`` : la
    commande de son en-tête (``uv export``), sinon d'après ce qu'il contient (empreintes,
    paquets de dev)."""
    header = python.generated(content)
    kind = _EXPORT_BASES[posixpath.basename(base)]
    if header is not None and header.tool == "pdm export":
        kind = LockKind.PDM_EXPORT
    elif header is not None and header.tool == "uv export":
        kind = LockKind.UV_EXPORT
    hashed = re.search(r"(?:^|\s)--hash\b", content) is not None
    name = posixpath.basename(path)
    warnings: list[str] = []
    if kind is LockKind.UV_EXPORT and header is not None and header.command is not None:
        options, dropped = _uv_export_options(header.command, name)
        if dropped:
            warnings.append(f"Pas repris de l'en-tête de {path} : {' '.join(dropped)}.")
    elif kind is LockKind.UV_EXPORT:
        options = ["--format", "requirements-txt", "--no-header", "-o", name]
        options += [] if hashed else ["--no-hashes"]
        options += [] if "# via" in content else ["--no-annotate"]
    else:
        dev = _exported_dev(source, project, base, content)
        if kind is LockKind.PDM_EXPORT:
            options = ["-o", name, *([] if hashed else ["--no-hashes"])]
            options += [] if dev else ["--prod"]
        else:
            options = ["-f", "requirements.txt", "-o", name]
            options += [] if hashed else ["--without-hashes"]
            options += ["--with", "dev"] if dev else []
            warnings.append(
                "poetry export demande le plugin poetry-plugin-export (Poetry 2) : sans lui, la "
                "commande échoue, et le lockfile est remis comme avant avec ses manifestes."
            )
    return _Export(kind=kind, base=base, options=tuple(options), warnings=tuple(warnings))


def _uv_export_options(command: str, name: str) -> tuple[list[str], list[str]]:
    """Les options de l'en-tête ``uv export …`` reprises telles quelles, dans leur ordre (uv recopie
    sa commande dans l'en-tête : il ne change pas), le fichier écrit donné par ``-o name`` ; et ce
    qui n'est pas repris."""
    try:
        words = shlex.split(command)[2:]
    except ValueError:
        words = []
    options: list[str] = []
    dropped: list[str] = []
    output = False
    items = iter(words)
    for word in items:
        option, has_value, _ = word.partition("=")
        if option in ("-o", "--output-file"):
            if not has_value:
                next(items, None)
            options += [f"{option}={name}"] if has_value else [option, name]
            output = True
        elif option in _UV_EXPORT_FLAGS and not has_value:
            options.append(word)
        elif option in _UV_EXPORT_VALUED:
            options += [word] if has_value else [option, next(items, "")]
        elif option not in ("--frozen", "--locked", "-q", "--quiet"):
            dropped.append(word)
    if not output:
        options += ["-o", name]
    return options, dropped


def _exported_dev(source: LocalSource, project: Project, base: str, content: str) -> bool:
    """Vrai si l'export a des paquets de dev seulement (une directe de dev du projet, ou ce que le
    lockfile ``base`` dit de dev ; un ``poetry.lock`` de Poetry 1.8 ne le dit pas) : il a été fait
    avec les dépendances de dev (``pdm export`` les met par défaut, ``poetry export`` non)."""
    dev = {d.name for d in project.dependencies if d.direct and d.scope is Scope.DEV} - {
        d.name for d in project.dependencies if d.direct and d.scope is not Scope.DEV
    }
    lock = _lockfile(base, _read_quietly(source.read_text, base))
    if lock is not None:
        dev |= {p.name for p in lock.packages if p.scope is Scope.DEV}
    exported = {
        d.name for d in python.parse_pinned_requirements("requirements.txt", content).packages
    }
    return bool(dev & exported)


def _export_job(path: str, export: _Export, tools: "Tools") -> Job:
    """Le travail qui refait l'export ``path`` après son lockfile (il en dépend : un échec de
    l'un remet l'autre)."""
    job = Job(
        lockfile=path,
        kind=export.kind,
        program=_which(_PROGRAMS[export.kind]),
        command="",
        inputs=(export.base,),
        options=export.options,
        reason=f"{export.base} a changé",
        warnings=export.warnings,
        timeout=tools.timeout,
    )
    return dataclasses.replace(job, command=shlex.join(_DRIVERS[export.kind].manual(job)))


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
    cancel: threading.Event | None = None,
) -> tuple[Regenerated, ...]:
    """Régénère les lockfiles de ``jobs`` (``plan``), une fois les fichiers de ``changes``
    écrits (``writers.write``), puis relit le projet. ``report`` est l'analyse d'avant.

    Les lockfiles qui dépendent des mêmes fichiers vont ensemble : si l'un échoue, tous leurs
    fichiers sont remis comme avant (``Regenerated.restored``). Dans l'ordre de ``jobs``.

    ``on_event`` reçoit un ``Event`` ``REGENERATING`` avant chaque outil lancé : l'interface
    montre ainsi lequel tourne (un outil peut tourner plusieurs minutes).

    Interrompue (Ctrl+C, ou ``cancel`` levé : l'outil en cours est tué, ``processes``), elle
    remet comme avant les fichiers du groupe en cours, et les manifestes réécrits des groupes
    qui n'ont pas encore tourné ; ceux des groupes finis restent, avec leurs lockfiles. Puis
    l'interruption remonte (``KeyboardInterrupt``, ``processes.Interrupted``)."""
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
    groups = _groups(jobs)
    try:
        current = {project.path: project for project in engine.inventory(source).projects}
    except BaseException:  # Ctrl+C
        _undo_written(source.root, written, groups)
        raise
    outcome: dict[str, Regenerated] = {}
    locks_before: dict[str, str | None] = {}
    for index, group in enumerate(groups):
        saved = _snapshot(source.root, report, group)
        for job in group:
            locks_before[job.lockfile] = _read_quietly(source.read_text, _versions_path(job))
        folders = _SavedFolders(source.root, [p for job in group for p in job.refreshes])
        try:
            if cancel is not None and cancel.is_set():
                raise processes.Interrupted("mise à jour arrêtée")
            failure = _run_group(source, group, current, outcome, announce, cancel)
        except BaseException:  # Ctrl+C, arrêt : rien ne doit rester à moitié fait
            _restore(source.root, saved, written, group)
            folders.restore()
            folders.discard()
            _undo_written(source.root, written, groups[index + 1 :])
            raise
        if failure is None:
            folders.discard()
        else:
            failed, message = failure
            restored = _restore(source.root, saved, written, group) + folders.restore()
            folders.discard()
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
    cancel: threading.Event | None,
) -> tuple[Job, str] | None:
    """Régénère les lockfiles du groupe, dans l'ordre, jusqu'au premier qui échoue : rend
    celui-là et son erreur. ``announce`` est appelé avant chaque outil lancé."""
    for job in group:
        if job.program is None:
            outcome[job.lockfile] = Regenerated(job=job, status=LockStatus.TOOL_MISSING)
            continue
        announce(job)
        context = _Context(source, job, current, cancel)
        try:
            _DRIVERS[job.kind].run(context)
        except _Failed as failed:
            return job, str(failed)
        outcome[job.lockfile] = Regenerated(
            job=job,
            status=LockStatus.REGENERATED,
            warnings=tuple(context.warnings),
            verified=context.verified,
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


class _SavedFolders:
    """Les dossiers que refont les outils d'un groupe (``Job.refreshes`` : le ``vendor/`` de ``go
    mod vendor``), copiés avant de les lancer, pour les remettre tels quels si l'un échoue. La
    copie va dans un dossier temporaire, effacé ensuite (``discard``)."""

    def __init__(self, root: Path, paths: Sequence[str]) -> None:
        self.root = root
        self.copies: dict[str, Path | None] = {}
        """Chaque dossier, et sa copie ; ``None`` pour un dossier qui n'existait pas."""
        self.temporary: Path | None = None
        if not paths:
            return
        self.temporary = Path(tempfile.mkdtemp(prefix="forceupdate-"))
        for index, path in enumerate(dict.fromkeys(paths)):
            folder = root / path
            if not folder.is_dir():
                self.copies[path] = None
                continue
            copy = self.temporary / str(index)
            shutil.copytree(folder, copy, symlinks=True)
            self.copies[path] = copy

    def restore(self) -> tuple[str, ...]:
        """Remet chaque dossier comme il était ; rend ceux qui l'ont été."""
        restored = []
        for path, copy in self.copies.items():
            folder = self.root / path
            try:
                if folder.exists():
                    shutil.rmtree(folder)
                if copy is not None:
                    shutil.copytree(copy, folder, symlinks=True)
            except OSError as err:
                logger.warning("%s n'a pas pu être remis comme avant : %s", path, err)
                continue
            restored.append(path)
        return tuple(restored)

    def discard(self) -> None:
        if self.temporary is not None:
            shutil.rmtree(self.temporary, ignore_errors=True)
            self.temporary = None


def _undo_written(
    root: Path, written: Mapping[str, FileChange], groups: Sequence[Sequence[Job]]
) -> None:
    """Remet comme avant leur réécriture les manifestes que lisent les outils de ``groups``, qui
    n'ont pas tourné : un manifeste réécrit sans son lockfile serait à moitié fait. Un fichier
    changé depuis (par quelqu'un d'autre) est laissé."""
    inputs = {path for group in groups for job in group for path in job.inputs}
    for path in sorted(inputs & written.keys()):
        change = written[path]
        full = root / path
        try:
            if full.read_bytes() != change.after.encode("utf-8"):
                continue
            writers.replace_file(full, change.before.encode("utf-8"))
        except OSError as err:
            logger.warning("%s n'a pas pu être remis comme avant : %s", path, err)


# -- relire ---------------------------------------------------------------------


def _read_back(
    source: LocalSource,
    result: Regenerated,
    after: Mapping[str, Project],
    locks_before: Mapping[str, str | None],
) -> Regenerated:
    """``result``, avec ce que donne chaque mise à jour et ce qui a changé d'autre."""
    job = result.job
    path = _versions_path(job)
    lock_after = _lockfile(path, _read_quietly(source.read_text, path))
    lock_before = _lockfile(path, locks_before.get(job.lockfile))
    installed = tuple(_installed(choice, after, lock_after) for choice in job.choices)
    names = {update.name for _, update, _ in job.choices}
    return dataclasses.replace(
        result, installed=installed, changed=_changed(lock_before, lock_after, names)
    )


def _versions_path(job: Job) -> str:
    """Le fichier où relire les versions après la régénération : le lockfile ; pour Go, le
    ``go.mod`` (``go.sum`` garde des empreintes, pas les versions choisies)."""
    if job.kind is LockKind.GO:
        return join(job.directory, go.MANIFEST)
    return job.lockfile


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
    # Une indirecte NuGet ajoutée au projet (E32) en devient une directe.
    added = any(edit.kind is EditKind.REFERENCE for edit in option.edits)
    found = {
        d.installed
        for d in (fresh.dependencies if fresh is not None else [])
        if d.name == update.name
        and (d.direct == update.direct or added)
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
        "COMPOSER",
        "COMPOSER_NO_DEV",
        "COMPOSER_PREFER_LOWEST",
        "COMPOSER_PREFER_STABLE",
        "COMPOSER_WITH_DEPENDENCIES",
        "COMPOSER_WITH_ALL_DEPENDENCIES",
        "COMPOSER_IGNORE_PLATFORM_REQ",
        "COMPOSER_IGNORE_PLATFORM_REQS",
        "BUNDLE_FORCE_RUBY_PLATFORM",
    }
)
"""Ce qui, hérité de l'environnement de forceupdate, ferait viser un autre projet à l'outil (le
virtualenv activé, que pipenv et Poetry prendraient pour celui du projet ; ``COMPOSER``, l'autre
fichier que lirait Composer), lui interdirait d'écrire le lockfile, ou lui ferait choisir
d'autres versions que celles du plan (``COMPOSER_PREFER_LOWEST`` fait descendre : vérifié avec
Composer 2.11 ; ``BUNDLE_FORCE_RUBY_PLATFORM`` ajoute la plateforme ``ruby`` au lockfile :
vérifié avec Bundler 4.0.20). ``BUNDLE_GEMFILE`` et ``BUNDLE_LOCKFILE`` sont remplacés
(``_bundler_environment``)."""

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
    """``processes.run`` : sans shell, et tout l'arbre de l'outil tué à son délai. Les tests le
    remplacent."""
    return processes.run(command, **options)


def _environment() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key.upper() not in _DROPPED_ENV}
    env.update(_ADDED_ENV)
    return env


def _decode(data: bytes) -> str:
    return _ANSI.sub("", data.decode("utf-8", errors="replace"))


def _output_lines(result: subprocess.CompletedProcess[bytes]) -> list[str]:
    """Les lignes non vides de ce qu'a écrit l'outil : sa sortie d'erreur, sinon sa sortie."""
    output = _decode(result.stderr).strip() or _decode(result.stdout).strip()
    return [line for line in output.splitlines() if line.strip()]


_NPM_PREFIX = re.compile(r"^npm (?:error|ERR!)\s?")
_NPM_MISMATCH = re.compile(r"^(?:Missing|Invalid): ")


def _npm_complaint(lines: Sequence[str]) -> str:
    """Ce que ``npm ci`` reproche au lockfile, en une phrase : ses lignes « Missing: … from lock
    file » et « Invalid: … » (suivies de l'aide de la commande, qu'on laisse) ; sinon ses dernières
    lignes."""
    said = [_NPM_PREFIX.sub("", line).strip() for line in lines]
    found = [line for line in said if _NPM_MISMATCH.match(line)]
    if not found:
        found = [line for line in said if line and not line.startswith("A complete log")][-3:]
    text = " ; ".join(found) or "(rien)"
    return text if text.endswith(".") else f"{text}."


class _Context:
    """Ce dont un outil a besoin pour régénérer un lockfile."""

    def __init__(
        self,
        source: LocalSource,
        job: Job,
        current: Mapping[str, Project],
        cancel: threading.Event | None = None,
    ) -> None:
        self.source = source
        self.root = source.root
        self.job = job
        self.current = current
        """Les projets relus après la réécriture des manifestes : les emplacements des pins."""
        self.cancel = cancel
        """Levé, l'outil en cours est tué (``processes.run``) : l'arrêt du serveur."""
        self.warnings: list[str] = []
        self.env: dict[str, str] = {}
        """Ce que l'outil reçoit en plus de ``_environment()`` (Cargo : ``_cargo_environment``)."""
        self.verified: Verified | None = None

    def shown(self, *arguments: str) -> str:
        """La commande telle qu'on la taperait : ``npm install …``, ``npx -y npm@10 install …``."""
        if self.job.launcher:
            return shlex.join(["npx", *self.job.launcher[1:], *arguments])
        return shlex.join([_PROGRAMS[self.job.kind], *arguments])

    def run(self, *arguments: str) -> None:
        """Lance le programme de l'outil avec ``arguments`` (par ``Job.launcher`` s'il y en a un),
        dans le dossier du lockfile. Lève ``_Failed``."""
        result = self._execute(arguments)
        if result.returncode != 0:
            lines = _output_lines(result)[-_OUTPUT_LINES:]
            said = "\n".join(lines) or "(rien)"
            shown = self.shown(*arguments)
            raise _Failed(f"« {shown} » a échoué (code {result.returncode}) :\n{said}")

    def verify(self, *arguments: str) -> None:
        """Relit le lockfile régénéré avec ``arguments`` (``ci --dry-run``) : ce qu'en dit
        l'outil va dans ``verified``, sans faire échouer la régénération. Un arrêt (Ctrl+C)
        remonte."""
        command = self.shown(*arguments)
        try:
            result = self._execute(arguments)
        except _Failed as failed:
            self.verified = Verified(command=command, error=str(failed))
        else:
            error = _npm_complaint(_output_lines(result)) if result.returncode != 0 else None
            self.verified = Verified(command=command, error=error)

    def _execute(self, arguments: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
        """Lance la commande ; lève ``_Failed`` si elle ne se lance pas ou ne finit pas à temps."""
        program = self.job.program
        assert program is not None
        command = [*self.job.launcher, *arguments] if self.job.launcher else [program, *arguments]
        shown = self.shown(*arguments)
        if command[0].lower().endswith((".cmd", ".bat")):
            unsafe = next((a for a in command[1:] if _BATCH_UNSAFE.search(a)), None)
            if unsafe is not None:
                raise _Failed(f"« {shown} » : argument refusé ({unsafe}).")
        logger.debug("%s (dans %s)", shown, self.job.directory)
        try:
            return _spawn(
                command,
                cwd=self.root / self.job.directory,
                env={**_environment(), **self.env},
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=self.job.timeout,
                check=False,
                cancel=self.cancel,
            )
        except subprocess.TimeoutExpired as err:
            raise _Failed(f"« {shown} » n'a pas fini en {self.job.timeout:.0f} s.") from err
        except OSError as err:
            raise _Failed(f"« {shown} » n'a pas pu être lancé ({err.strerror or err}).") from err

    def names(self, *, direct: bool | None = None) -> list[str]:
        """Les paquets des mises à jour, sans doublon ; seulement les directes, ou seulement les
        indirectes."""
        found = (u.name for _, u, _ in self.job.choices if direct is None or u.direct == direct)
        return list(dict.fromkeys(found))

    def run_pinned(
        self,
        exact: Callable[[str], str],
        *arguments: str,
        appended: Mapping[str, str] | None = None,
    ) -> bool:
        """Lance ``arguments`` avec, à la place des contraintes, la version choisie écrite par
        ``exact`` (``pins``), et le texte de ``appended`` ajouté à la fin de ses fichiers (des
        indirectes épinglées : ``gem "x", "= V"`` pour Bundler), puis remet les fichiers. Faux
        s'il n'y a rien à épingler, ou si l'épinglage échoue : la raison va dans ``warnings``."""
        targets = self.pins(exact)
        if not targets and not appended:
            return False
        try:
            files = _appended(self.root, writers.rewrite(self.root, targets), appended or {})
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
        if dependency.resolved_constraint is not None:  # catalogue pnpm, workspace Cargo
            edit = Edit(
                kind=EditKind.CATALOG,
                file=dependency.file,
                location=None,
                old=dependency.resolved_constraint,
                new=new,
            )
            try:
                target = writers.catalog_target(edit, [dependency], self.source.read_text)
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


def _appended(
    root: Path, files: Sequence[FileChange], appended: Mapping[str, str]
) -> tuple[FileChange, ...]:
    """``files``, avec le texte de ``appended`` à la fin de ses fichiers (après une fin de ligne,
    celles du fichier). Lève ``Refused`` pour un fichier illisible."""
    changes = {change.path: change for change in files}
    for path, text in appended.items():
        change = changes.get(path)
        if change is None:
            try:
                before = (root / path).read_bytes().decode("utf-8")
            except (OSError, UnicodeDecodeError) as err:
                raise Refused(f"{path} : illisible ({err}).") from err
            change = FileChange(path=path, before=before, after=before, diff="")
        newline = "\r\n" if "\r\n" in change.after else "\n"
        after = change.after
        if after and not after.endswith("\n"):
            after += newline
        after += text.replace("\n", newline)
        changes[path] = dataclasses.replace(change, after=after)
    return tuple(changes.values())


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
    _VERIFY = ("ci", "--dry-run", "--ignore-scripts", "--no-audit", "--no-fund")
    """``npm ci`` relit le lockfile et refuse s'il ne colle pas au ``package.json`` (« Missing: …
    from lock file ») ; ``--dry-run`` n'installe rien (vérifié avec npm 10 et 11)."""

    def manual(self, job: Job) -> list[str]:
        npm = ["npx", *job.launcher[1:]] if job.launcher else ["npm"]
        names = _lockfile_only(job)
        if names:
            return [*npm, "update", *names, "--package-lock-only", "--ignore-scripts"]
        return [*npm, "install", "--package-lock-only", "--ignore-scripts"]

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
        if context.job.doing is ExtraKind.PROJECT_NPM:
            context.verify(*self._VERIFY)


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


class _UvScript(_Driver):
    """``uv lock --script`` : le script, dans le dossier de son lockfile (``script.py.lock``)."""

    def manual(self, job: Job) -> list[str]:
        return ["uv", "lock", "--script", _script_of(job), *_upgrades(job)]

    def run(self, context: _Context) -> None:
        context.run("lock", "--script", _script_of(context.job), *_upgrades(context.job))


def _script_of(job: Job) -> str:
    """Le script d'un lockfile ``script.py.lock`` : ``script.py``, dans le même dossier."""
    return posixpath.basename(job.lockfile).removesuffix(".lock")


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


class _UvExport(_Driver):
    """``uv export`` avec les options de son en-tête : relu dans ``uv.lock``, sans résoudre
    (``UV_FROZEN`` : ``--frozen`` passerait dans l'en-tête, vérifié avec uv 0.10)."""

    def manual(self, job: Job) -> list[str]:
        return ["uv", "export", *job.options]

    def run(self, context: _Context) -> None:
        context.env["UV_FROZEN"] = "1"
        context.run("export", *context.job.options)


class _PoetryExport(_Driver):
    def manual(self, job: Job) -> list[str]:
        return ["poetry", "export", *job.options]

    def run(self, context: _Context) -> None:
        context.run("export", *context.job.options, "--no-interaction")


class _PdmExport(_Driver):
    def manual(self, job: Job) -> list[str]:
        return ["pdm", "export", *job.options]

    def run(self, context: _Context) -> None:
        context.run("export", *context.job.options)


class _Cargo(_Driver):
    def manual(self, job: Job) -> list[str]:
        """Une mise à jour dont la contrainte n'a pas changé : ``--precise V``. Sinon, les
        paquets visés montent à la plus haute version que permet leur contrainte réécrite (Cargo
        ignore ``--precise`` quand elle n'accepte plus la version figée)."""
        if len(job.choices) == 1:
            _, update, option = job.choices[0]
            if not (update.direct and option.edits):
                return ["cargo", "update", "-p", _cargo_spec(update), "--precise", option.version]
        specs = dict.fromkeys(_cargo_spec(update) for _, update, _ in job.choices)
        packages = [word for spec in specs for word in ("-p", spec)]
        return ["cargo", "update", *(packages or ["--workspace"])]

    def run(self, context: _Context) -> None:
        context.env.update(_cargo_environment())
        if context.job.toolchain is not None:
            # Devant le rust-toolchain.toml du projet, sans rien installer (rustup 1.29).
            context.env["RUSTUP_TOOLCHAIN"] = context.job.toolchain
        pinned = context.run_pinned(lambda version: f"={version}", "update", "--workspace")
        for _, update, option in context.job.choices:
            if update.direct and pinned:
                continue
            # Une même indirecte de deux membres, ou un paquet qu'un épinglage a déjà déplacé :
            # « -p x@actuelle » ne désignerait plus rien, et cargo échouerait.
            if not _cargo_locks(context, update):
                continue
            context.run("update", "-p", _cargo_spec(update), "--precise", option.version)
        context.run("update", "--workspace")


def _cargo_locks(context: _Context, update: Update) -> bool:
    """Vrai si le ``Cargo.lock`` fige encore ``update`` à sa version actuelle (ou si on ne la
    connaît pas)."""
    if update.current_version is None or update.current_is_approximate:
        return True
    path = context.job.lockfile
    lock = _lockfile(path, _read_quietly(context.source.read_text, path))
    if lock is None:
        return True
    return any(
        p.name == update.name and p.version == update.current_version and not p.local
        for p in lock.packages
    )


def _cargo_spec(update: Update) -> str:
    """Le paquet visé par ``cargo update -p`` : ``nom@version`` (le lockfile peut en figer
    plusieurs versions), ``nom`` seul si sa version n'est pas connue."""
    if update.current_version is None or update.current_is_approximate:
        return update.name
    return f"{update.name}@{update.current_version}"


def _cargo_environment() -> dict[str, str]:
    """Le ``rustc`` installé, et aucun « wrapper », quoi que dise le ``.cargo/config.toml`` du
    projet : ``cargo update`` lance ``rustc -vV`` quand le résolveur 3 doit connaître sa version
    (édition 2024 sans ``rust-version``). Vide, ``RUSTC_WRAPPER`` défait celui d'une
    configuration (vérifié avec cargo 1.99)."""
    return {
        "RUSTC": _which("rustc") or "rustc",
        "RUSTC_WRAPPER": "",
        "RUSTC_WORKSPACE_WRAPPER": "",
        "CARGO_TERM_COLOR": "never",
        "CARGO_TERM_PROGRESS_WHEN": "never",
    }


class _Go(_Driver):
    def manual(self, job: Job) -> list[str]:
        """``go mod tidy`` ; puis ``go mod vendor`` avec ``vendor/`` (la case le dit)."""
        return ["go", "mod", "tidy"]

    def run(self, context: _Context) -> None:
        context.env.update(_go_environment())
        path = context.root / context.job.directory / go.MANIFEST
        before = _go_lines(path)
        context.run("mod", "tidy")
        after = _go_lines(path)
        for (label, was), (_, now) in zip(before, after, strict=True):
            if was != now and now is not None:
                context.warnings.append(
                    f"go mod tidy a changé la directive {label} : {was or 'absente'} → {now}"
                    + (" (le go installé)." if was is None and label == "go" else ".")
                )
        if context.job.doing is ExtraKind.GO_VENDOR:
            # Refait vendor/ d'après go.mod et go.sum, sans rien compiler (vérifié avec Go 1.27) ;
            # s'il échoue, vendor/ est remis comme avant (``_SavedFolders``).
            context.run("mod", "vendor")
        elif context.job.extra is not None and context.job.extra.kind is ExtraKind.GO_VENDOR:
            context.warnings.append(_VENDOR_LEFT)


def _go_lines(path: Path) -> list[tuple[str, str | None]]:
    """Les directives ``go`` et ``toolchain`` du ``go.mod`` ``path``, telles qu'écrites."""
    try:
        parsed = go.parse_go_mod_file(path.name, decode_text(path.read_bytes()))
    except (OSError, ParseError):
        return [("go", None), ("toolchain", None)]
    return [("go", parsed.go), ("toolchain", parsed.toolchain)]


def _go_environment() -> dict[str, str]:
    """Le go installé, sans télécharger celui que demande ``go.mod`` (``GOTOOLCHAIN=local`` : il
    échoue plutôt) ; ``GOFLAGS`` remplacé par une valeur sans effet sur ``go mod tidy`` :
    ``-modfile=`` lui ferait refaire un autre fichier, et une valeur vide retomberait sur celle de
    ``go env -w`` ; hors de tout workspace (``GOWORK=off``), comme l'est déjà ``go mod tidy``.
    Vérifié avec Go 1.27. ``GOPROXY``, ``GOPRIVATE``, ``GONOSUMDB``… restent ceux de la personne :
    un module privé en a besoin."""
    return {"GOTOOLCHAIN": "local", "GOFLAGS": "-mod=mod", "GOWORK": "off"}


class _Composer(_Driver):
    _ARGS = ("--with-all-dependencies", "--no-install", "--no-scripts", "--no-plugins")

    def manual(self, job: Job) -> list[str]:
        return ["composer", "update", *_composer_specs(job), "-W", "-m", *self._ARGS[1:]]

    def run(self, context: _Context) -> None:
        context.env.update(_composer_environment(context))
        context.run(
            "update",
            *_composer_specs(context.job),
            *self._ARGS,
            "--no-interaction",
            "--no-progress",
            "--no-ansi",
            "--ignore-platform-req=ext-*",
            "--ignore-platform-req=lib-*",
        )


def _composer_specs(job: Job) -> list[str]:
    """``nom:version`` pour chaque mise à jour : une mise à jour partielle de ces paquets, chacun
    à sa version, qu'il soit direct ou indirect."""
    specs = (f"{update.name}:{option.version}" for _, update, option in job.choices)
    return list(dict.fromkeys(specs))


def _composer_environment(context: _Context) -> dict[str, str]:
    """Rien que le nécessaire changé dans le lockfile (``COMPOSER_MINIMAL_CHANGES``, Composer 2.7
    et plus ; ``-m`` ferait échouer un Composer plus ancien), sans l'audit de fin, et sans le
    blocage des versions à faille (Composer 2.10 et plus) : c'est la sélection vérifiée par
    forceupdate qui s'applique. Un réglage du projet (``config.policy``) ou de la personne
    (``COMPOSER_POLICY_ADVISORIES_BLOCK`` déjà là) l'emporte. Vérifié avec Composer 2.11."""
    env = {
        "COMPOSER_MINIMAL_CHANGES": "1",
        "COMPOSER_NO_AUDIT": "1",
        "COMPOSER_NO_INTERACTION": "1",
    }
    if _composer_unblocks(_composer_config(context.source.read_text, context.job.directory)):
        env["COMPOSER_POLICY_ADVISORIES_BLOCK"] = "0"
    return env


class _Bundler(_Driver):
    def manual(self, job: Job) -> list[str]:
        """Une mise à jour dont la contrainte n'a pas changé, ou une indirecte : ``bundle lock
        --update x --conservative`` (la plus haute version permise). Sinon ``bundle lock``, qui
        défait ce qui ne colle plus au ``Gemfile`` réécrit."""
        names = _lockfile_only(job)
        if names:
            return ["bundle", "lock", "--update", *names, "--conservative"]
        return ["bundle", "lock"]

    def run(self, context: _Context) -> None:
        job = context.job
        context.env.update(_bundler_environment(context.root, job))
        before = _bundler_lock(context)
        gemfile = join(job.directory, _bundler_gemfile(job.lockfile))
        indirect = {u.name: o.version for _, u, o in job.choices if not u.direct}
        text = _read_quietly(context.source.read_text, gemfile) or ""
        appendable = re.search(r"^__END__\s*$", text, re.MULTILINE) is None and all(
            _GEM_NAME.fullmatch(name) and _GEM_VERSION.fullmatch(version)
            for name, version in indirect.items()
        )
        lines = "".join(f'gem "{name}", "= {version}"\n' for name, version in indirect.items())
        appended = {gemfile: lines} if lines and appendable else {}
        if context.run_pinned(lambda version: f"= {version}", "lock", appended=appended):
            names = [] if appended or not indirect else list(indirect)
        else:
            names = _lockfile_only(job)
        if names:
            context.run("lock", "--update", *names, "--conservative")
        context.run("lock")
        after = _bundler_lock(context)
        if before is None or after is None:
            return
        added = [platform for platform in after.platforms if platform not in before.platforms]
        if added:
            context.run("lock", "--remove-platform", *added)
        for label, was, now in (
            ("BUNDLED WITH", before.bundled_with, after.bundled_with),
            ("RUBY VERSION", before.ruby_version, after.ruby_version),
        ):
            if was != now and now is not None:
                context.warnings.append(
                    f"Bundler a changé {label} dans le lockfile : {was or 'absent'} → {now}."
                )


_GEM_NAME = re.compile(r"[A-Za-z0-9._-]+")
"""Un nom de gem (``Gem::Specification::VALID_NAME_PATTERN``) : rien qu'une ligne ajoutée au
``Gemfile`` puisse exécuter. Une indirecte au nom plus étrange passe par ``--update``."""
_GEM_VERSION = re.compile(r"[0-9]+(?:\.[0-9A-Za-z]+)*")


def _bundler_lock(context: _Context) -> ruby.GemfileLock | None:
    """Le lockfile de Bundler du travail, relu ; ``None`` s'il est absent ou illisible."""
    path = context.job.lockfile
    content = _read_quietly(context.source.read_text, path)
    if content is None:
        return None
    try:
        return ruby.parse_gemfile_lock(path, content)
    except ParseError:
        return None


def _bundler_environment(root: Path, job: Job) -> dict[str, str]:
    """Le ``Gemfile`` et le lockfile du projet, quoi que disent ``BUNDLE_GEMFILE`` et
    ``BUNDLE_LOCKFILE`` hérités : sinon Bundler en lirait ou en écrirait d'autres (vérifié avec
    Bundler 4.0.20). ``BUNDLE_FROZEN`` et ``BUNDLE_DEPLOYMENT`` n'empêchent pas ``bundle lock``
    d'écrire ; ``BUNDLE_COOLDOWN``, les miroirs et les identifiants d'un serveur privé restent
    ceux de la personne."""
    directory = root / job.directory
    return {
        "BUNDLE_GEMFILE": str(directory / _bundler_gemfile(job.lockfile)),
        "BUNDLE_LOCKFILE": str(root / job.lockfile),
    }


class _NuGet(_Driver):
    def manual(self, job: Job) -> list[str]:
        return ["dotnet", "restore", *job.options, "--force-evaluate"]

    def run(self, context: _Context) -> None:
        context.env.update(_dotnet_environment())
        context.run(
            "restore",
            *context.job.options,
            "--force-evaluate",
            "-noAutoResponse",
            "-p:RestoreLockedMode=false",
        )


def _dotnet_environment() -> dict[str, str]:
    """Ni bannière, ni télémétrie, ni certificat de développement créé au premier lancement, ni
    processus MSBuild laissé en arrière-plan. ``-noAutoResponse`` écarte le
    ``Directory.Build.rsp`` du projet (ses options, ses loggers) ; ``-p:RestoreLockedMode=false``
    lève le mode verrouillé du projet ou de l'environnement, qui refuserait de changer le
    lockfile (NU1004). Vérifié avec le SDK .NET 10.0.403."""
    return {
        "DOTNET_NOLOGO": "1",
        "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
        "DOTNET_GENERATE_ASPNET_CERTIFICATE": "false",
        "DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE": "1",
        "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
        "MSBUILDDISABLENODEREUSE": "1",
        "DOTNET_CLI_DO_NOT_USE_MSBUILD_SERVER": "1",
    }


_DRIVERS: dict[LockKind, _Driver] = {
    LockKind.NPM: _Npm(),
    LockKind.PNPM: _Pnpm(),
    LockKind.YARN_1: _Yarn1(),
    LockKind.YARN: _Yarn(),
    LockKind.UV: _Uv(),
    LockKind.UV_SCRIPT: _UvScript(),
    LockKind.POETRY: _Poetry(),
    LockKind.PDM: _Pdm(),
    LockKind.PIPENV: _Pipenv(),
    LockKind.PIP_COMPILE: _PipCompile(),
    LockKind.UV_PIP_COMPILE: _UvPipCompile(),
    LockKind.UV_EXPORT: _UvExport(),
    LockKind.POETRY_EXPORT: _PoetryExport(),
    LockKind.PDM_EXPORT: _PdmExport(),
    LockKind.CARGO: _Cargo(),
    LockKind.GO: _Go(),
    LockKind.COMPOSER: _Composer(),
    LockKind.BUNDLER: _Bundler(),
    LockKind.NUGET: _NuGet(),
}
