"""Trouver les fichiers de dépendances d'une source, et les regrouper en projets.

Un fichier de dépendances est un manifeste (``package.json``, ``pyproject.toml``…),
où les dépendances sont déclarées, ou un lockfile (``package-lock.json``,
``uv.lock``…), où leurs versions sont figées.

Un dossier qui en contient au moins un est un projet ; un monorepo en donne
plusieurs. Les lockfiles d'un projet sont dans son dossier, ou à la racine du
workspace dont il fait partie (npm, Yarn, pnpm, uv, Cargo).

Tout se fait sur des chemins POSIX relatifs à la racine de la source, sans lire
les fichiers : ça marche pareil en local et sur une forge (E17).

Repris de ``reference/argos_sca_parsers.py`` (L51-185, L221-381, L1388-1401), puis
adapté : des motifs au lieu de noms exacts, les lockfiles séparés des manifestes,
des chemins relatifs au lieu de ``Path``, ``logging`` au lieu de ``loguru``.
"""

import fnmatch
import logging
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path, PurePath
from typing import NamedTuple

from forceupdate.models import Ecosystem, Project

logger = logging.getLogger(__name__)

DEFAULT_MAX_FILES = 2000
"""Plafond de fichiers de dépendances par analyse, contre l'explosion mémoire sur un
monorepo géant."""

DEFAULT_MAX_FILE_SIZE = 2_000_000
"""Taille maximale d'un fichier lu (2 Mo), sauf les lockfiles."""

DEFAULT_MAX_LOCKFILE_SIZE = 50_000_000
"""Taille maximale d'un lockfile lu (50 Mo) : un ``package-lock.json`` ou un ``uv.lock``
de gros projet dépasse souvent 2 Mo."""

IGNORED_DIRS: frozenset[str] = frozenset(
    {
        # Gestion de versions
        ".git",
        ".svn",
        ".hg",
        # Caches d'outils
        ".tox",
        ".nox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".hypothesis",
        ".cache",
        ".parcel-cache",
        ".turbo",
        ".angular",
        ".gradle",
        ".dart_tool",
        ".terraform",
        "__pycache__",
        # Environnements et dépendances installées
        ".venv",
        "venv",
        "env",
        ".eggs",
        "site-packages",
        "node_modules",
        "bower_components",
        "jspm_packages",
        ".pnpm-store",
        ".yarn",
        "Pods",
        "vendor",
        "third_party",
        "third-party",
        # Sorties de build
        ".next",
        ".nuxt",
        ".output",
        ".svelte-kit",
        "dist",
        "build",
        "target",
        "coverage",
        "htmlcov",
    }
)
"""Dossiers jamais parcourus : gestion de versions, caches, environnements virtuels,
dépendances installées, sorties de build. Leurs manifestes sont ceux des
dépendances, pas ceux du projet. Les dossiers ``*.egg-info`` aussi (voir
``is_ignored_dir``)."""


def is_ignored_dir(name: str) -> bool:
    """Vrai si un dossier de ce nom n'est jamais parcouru."""
    return name in IGNORED_DIRS or name.endswith(".egg-info")


def is_ignored_path(path: str) -> bool:
    """Vrai si l'un des dossiers du chemin POSIX ``path`` n'est jamais parcouru."""
    return any(is_ignored_dir(part) for part in path.split("/")[:-1])


_TEST_DIRS: frozenset[str] = frozenset(
    {
        "tests",
        "test",
        "__tests__",
        "spec",
        "specs",
        "fixtures",
        "fixture",
        "examples",
        "example",
        "demo",
        "demos",
        "mocks",
        "mock",
        "stubs",
    }
)

_TEST_FILE_SUFFIXES: tuple[str, ...] = (
    "_test.py",
    "_test.js",
    "_test.ts",
    "_test.tsx",
    "_test.go",
    "_test.rb",
    "_test.java",
    "_test.cs",
    "_test.php",
    ".test.js",
    ".test.ts",
    ".test.jsx",
    ".test.tsx",
    ".spec.js",
    ".spec.ts",
    ".spec.jsx",
    ".spec.tsx",
    ".spec.rb",
)
"""Fins de noms de fichiers de tests, comparées en minuscules."""

_TEST_CLASS_SUFFIXES: tuple[str, ...] = ("Test.java", "Tests.java", "Test.cs", "Tests.cs")
"""Fins de noms de classes de tests, comparées avec la casse : ``Contest.java`` n'en est pas."""

_TEST_FILE_PREFIXES: tuple[str, ...] = ("test_", "tests_", "conftest")


def is_test_path(path: str | PurePath) -> bool:
    """Vrai pour un fichier de tests, ou rangé dans un dossier de tests, de fixtures ou d'exemples.

    ``path`` est relatif à la racine de la source : si on choisit d'analyser
    ``tests/`` lui-même, ce qu'il contient n'est plus « dans un dossier de tests ».
    Les séparateurs ``\\`` sont acceptés.
    """
    parts = str(path).replace("\\", "/").split("/")
    if any(part.lower() in _TEST_DIRS for part in parts[:-1]):
        return True
    name = parts[-1]
    lowered = name.lower()
    return (
        lowered.endswith(_TEST_FILE_SUFFIXES)
        or name.endswith(_TEST_CLASS_SUFFIXES)
        or lowered.startswith(_TEST_FILE_PREFIXES)
    )


def safe_read_text(path: Path, *, max_size: int = DEFAULT_MAX_FILE_SIZE) -> str | None:
    """Lit un fichier en UTF-8, sans échouer : ``None`` s'il est trop gros ou illisible.

    Les octets qui ne sont pas de l'UTF-8 valide deviennent ``\\ufffd``.
    """
    try:
        if path.stat().st_size > max_size:
            logger.debug("fichier de plus de %d octets, ignoré : %s", max_size, path)
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as err:
        logger.debug("lecture impossible de %s : %s", path, err)
        return None


DEPENDENCY_MANIFESTS: dict[str, Ecosystem] = {
    # Python
    "requirements*.txt": Ecosystem.PYPI,
    "requirements*.in": Ecosystem.PYPI,
    "requirements/*.txt": Ecosystem.PYPI,
    "requirements/*.in": Ecosystem.PYPI,
    "pyproject.toml": Ecosystem.PYPI,
    "Pipfile": Ecosystem.PYPI,
    "setup.py": Ecosystem.PYPI,
    "setup.cfg": Ecosystem.PYPI,
    # JavaScript / TypeScript
    "package.json": Ecosystem.NPM,
    # Ruby
    "Gemfile": Ecosystem.RUBYGEMS,
    # Go
    "go.mod": Ecosystem.GO,
    # Rust
    "Cargo.toml": Ecosystem.CRATES_IO,
    # PHP
    "composer.json": Ecosystem.PACKAGIST,
    # Java : Maven, Gradle
    "pom.xml": Ecosystem.MAVEN,
    "build.gradle": Ecosystem.MAVEN,
    "build.gradle.kts": Ecosystem.MAVEN,
    "gradle/libs.versions.toml": Ecosystem.MAVEN,
    # .NET
    "*.csproj": Ecosystem.NUGET,
    "*.fsproj": Ecosystem.NUGET,
    "*.vbproj": Ecosystem.NUGET,
    "Directory.Packages.props": Ecosystem.NUGET,
    "packages.config": Ecosystem.NUGET,
}
"""Motifs des manifestes, et leur écosystème. Comparés sans tenir compte de la casse.
Un motif avec un dossier (``requirements/*.txt``) porte sur les derniers éléments du
chemin, et le projet est le dossier au-dessus (``requirements/dev.txt`` est un
manifeste du projet ``.``)."""

LOCKFILES: dict[str, Ecosystem] = {
    "Pipfile.lock": Ecosystem.PYPI,
    "poetry.lock": Ecosystem.PYPI,
    "uv.lock": Ecosystem.PYPI,
    "pdm.lock": Ecosystem.PYPI,
    "package-lock.json": Ecosystem.NPM,
    "npm-shrinkwrap.json": Ecosystem.NPM,
    "yarn.lock": Ecosystem.NPM,
    "pnpm-lock.yaml": Ecosystem.NPM,
    "Gemfile.lock": Ecosystem.RUBYGEMS,
    "go.sum": Ecosystem.GO,
    "Cargo.lock": Ecosystem.CRATES_IO,
    "composer.lock": Ecosystem.PACKAGIST,
    "packages.lock.json": Ecosystem.NUGET,
}
"""Noms des lockfiles, et leur écosystème. Comparés sans tenir compte de la casse."""

MANIFEST_LOCKFILES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "package.json",
        ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml"),
    ),
    ("pyproject.toml", ("uv.lock", "poetry.lock", "pdm.lock")),
    ("Pipfile", ("Pipfile.lock",)),
    ("Gemfile", ("Gemfile.lock",)),
    ("go.mod", ("go.sum",)),
    ("Cargo.toml", ("Cargo.lock",)),
    ("composer.json", ("composer.lock",)),
    ("*.csproj", ("packages.lock.json",)),
    ("*.fsproj", ("packages.lock.json",)),
    ("*.vbproj", ("packages.lock.json",)),
)
"""Motif de manifeste → lockfiles qui peuvent l'accompagner dans son dossier."""

WORKSPACE_LOCKFILES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "package.json",
        ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml"),
    ),
    ("pyproject.toml", ("uv.lock",)),
    ("Cargo.toml", ("Cargo.lock",)),
)
"""Manifestes dont le lockfile peut être à la racine d'un workspace, plus haut :
workspaces npm, Yarn et pnpm, uv, Cargo. Poetry, Pipenv, Bundler ou Composer n'en ont
pas."""

PIP_TOOLS_SOURCES = ("requirements*.in", "requirements/*.in")
"""Motifs des fichiers sources de pip-tools. ``pip-compile requirements.in`` écrit
``requirements.txt`` : ce ``.txt`` compilé, posé à côté de son ``.in``, est le
lockfile du ``.in`` (voir ``compiled_requirements``)."""

_PIP_TOOLS_OUTPUTS = ("requirements*.txt", "requirements/*.txt")


class DependencyFile(NamedTuple):
    """Un fichier de dépendances reconnu dans une source."""

    path: str
    """Son chemin POSIX, relatif à la racine de la source."""
    project: str
    """Le dossier du projet auquel il appartient (``.`` pour la racine)."""
    pattern: str
    """Le motif reconnu (``requirements*.txt``, ``package.json``…)."""
    ecosystem: Ecosystem
    lockfile: bool


_PATTERNS: tuple[tuple[str, Ecosystem, bool], ...] = tuple(
    sorted(
        [(pattern, eco, False) for pattern, eco in DEPENDENCY_MANIFESTS.items()]
        + [(name, eco, True) for name, eco in LOCKFILES.items()],
        # Les motifs avec un dossier d'abord : « requirements/requirements.txt » appartient
        # au projet du dessus, pas au dossier « requirements ».
        key=lambda entry: -entry[0].count("/"),
    )
)


def match_dependency_file(path: str) -> DependencyFile | None:
    """Reconnaît un manifeste ou un lockfile d'après son chemin POSIX ; ``None`` sinon."""
    parts = path.split("/")
    for pattern, ecosystem, lockfile in _PATTERNS:
        depth = pattern.count("/") + 1
        if len(parts) < depth:
            continue
        tail = "/".join(parts[-depth:]).lower()
        if fnmatch.fnmatchcase(tail, pattern.lower()):
            project = "/".join(parts[:-depth]) or "."
            return DependencyFile(path, project, pattern, ecosystem, lockfile)
    return None


def ecosystem_for_manifest(path: str | PurePath) -> Ecosystem | None:
    """L'écosystème d'un manifeste ou d'un lockfile ; ``None`` si ce n'en est pas un."""
    match = match_dependency_file(PurePath(path).as_posix())
    return match.ecosystem if match else None


def lockfile_candidates(manifest: str) -> list[str]:
    """Les lockfiles qui peuvent accompagner ``manifest`` dans son dossier (chemins POSIX).

    Pour un ``.in`` de pip-tools, c'est le ``.txt`` du même nom.
    """
    match = match_dependency_file(manifest)
    if match is None or match.lockfile:
        return []
    if match.pattern in PIP_TOOLS_SOURCES:
        return [manifest[: -len(".in")] + ".txt"]
    names = dict(MANIFEST_LOCKFILES).get(match.pattern, ())
    return [_join(match.project, name) for name in names]


def compiled_requirements(paths: Iterable[str]) -> set[str]:
    """Parmi ``paths``, les ``requirements*.txt`` compilés par pip-tools.

    Un ``.txt`` est compilé quand un ``.in`` du même nom est à côté de lui
    (``requirements-dev.in`` → ``requirements-dev.txt``). C'est alors un lockfile :
    les dépendances directes sont celles du ``.in``, les versions celles du ``.txt``.
    """
    matches = [match for path in paths if (match := match_dependency_file(path)) is not None]
    sources = {m.path[: -len(".in")].lower() for m in matches if m.pattern in PIP_TOOLS_SOURCES}
    return {
        m.path
        for m in matches
        if m.pattern in _PIP_TOOLS_OUTPUTS and m.path[: -len(".txt")].lower() in sources
    }


def max_read_size(path: str) -> int:
    """Taille maximale à lire pour ``path`` : plus grande pour un lockfile."""
    match = match_dependency_file(path)
    if match is not None and match.lockfile:
        return DEFAULT_MAX_LOCKFILE_SIZE
    return DEFAULT_MAX_FILE_SIZE


def discover_dependency_manifests(
    paths: Iterable[str],
    *,
    max_files: int = DEFAULT_MAX_FILES,
    include_test_paths: bool = True,
) -> list[str]:
    """Les manifestes et lockfiles parmi ``paths``, des chemins POSIX relatifs, triés.

    Les dossiers de ``IGNORED_DIRS`` sont écartés ; ceux de tests aussi quand
    ``include_test_paths`` est faux (voir ``is_test_path``). Au-delà de
    ``max_files`` fichiers trouvés, la liste est coupée.
    """
    collected: list[str] = []
    for path in paths:
        if is_ignored_path(path) or match_dependency_file(path) is None:
            continue
        if not include_test_paths and is_test_path(path):
            continue
        if len(collected) >= max_files:
            logger.warning("limite de %d fichiers de dépendances atteinte", max_files)
            break
        collected.append(path)
    return sorted(collected)


def group_projects(paths: Iterable[str]) -> list[Project]:
    """Regroupe des manifestes et lockfiles en projets : un projet par dossier.

    Un projet sans lockfile dans son dossier prend celui de la racine du workspace :
    le plus proche dossier parent qui a le même manifeste et un lockfile qui va
    avec (voir ``WORKSPACE_LOCKFILES``). Que le projet soit bien membre du
    workspace, seul le contenu des fichiers le dit : ce sont les parseurs qui le
    vérifient (E03, E04).

    Un ``requirements*.txt`` compilé par pip-tools (un ``.in`` du même nom est à
    côté) compte comme un lockfile, pas comme un manifeste.
    """
    by_dir: dict[str, list[DependencyFile]] = defaultdict(list)
    for path in paths:
        match = match_dependency_file(path)
        if match is not None:
            by_dir[match.project].append(match)

    projects = []
    for directory in sorted(by_dir, key=_dir_sort_key):
        files = by_dir[directory]
        compiled = compiled_requirements(f.path for f in files)
        manifests = {f.path for f in files if not f.lockfile} - compiled
        lockfiles = {f.path for f in files if f.lockfile} | compiled
        lockfiles.update(_workspace_lockfiles(directory, files, by_dir))
        ecosystems = {f.ecosystem for f in files}
        projects.append(
            Project(
                path=directory,
                ecosystems=[e for e in Ecosystem if e in ecosystems],
                manifests=sorted(manifests),
                lockfiles=sorted(lockfiles),
            )
        )
    return projects


def find_projects(
    paths: Iterable[str],
    *,
    include_tests: bool = False,
    max_files: int = DEFAULT_MAX_FILES,
) -> tuple[list[Project], list[str]]:
    """Les projets d'une source, et les fichiers de dépendances écartés.

    Par défaut, un manifeste rangé dans un dossier de tests, de fixtures ou
    d'exemples ne fait pas un projet : ce sont des mini-projets de démonstration,
    souvent figés exprès sur de vieilles versions. Ils sont rendus à part.
    """
    found = discover_dependency_manifests(paths, max_files=max_files)
    ignored = [] if include_tests else [path for path in found if is_test_path(path)]
    skipped = set(ignored)
    return group_projects(path for path in found if path not in skipped), ignored


def _workspace_lockfiles(
    directory: str,
    files: list[DependencyFile],
    by_dir: dict[str, list[DependencyFile]],
) -> set[str]:
    """Les lockfiles de workspace des manifestes de ``directory`` qui n'en ont pas sur place."""
    names_here = {f.path.rsplit("/", 1)[-1].lower() for f in files if f.lockfile}
    found: set[str] = set()
    for pattern, candidates in WORKSPACE_LOCKFILES:
        wanted = {name.lower() for name in candidates}
        if not any(f.pattern == pattern for f in files) or names_here & wanted:
            continue
        for ancestor in _ancestors(directory):
            above = by_dir.get(ancestor, [])
            if not any(f.pattern == pattern for f in above):
                continue
            lockfiles = {
                f.path for f in above if f.lockfile and f.path.rsplit("/", 1)[-1].lower() in wanted
            }
            if lockfiles:
                found |= lockfiles
                break
    return found


def _ancestors(directory: str) -> list[str]:
    """Les dossiers parents de ``directory``, du plus proche à la racine ``.``."""
    if directory == ".":
        return []
    parts = directory.split("/")
    return ["/".join(parts[:i]) for i in range(len(parts) - 1, 0, -1)] + ["."]


def _dir_sort_key(directory: str) -> tuple[str, ...]:
    """Trie les dossiers comme une arborescence : ``.`` d'abord, puis par chemin."""
    return () if directory == "." else tuple(directory.split("/"))


def _join(directory: str, name: str) -> str:
    return name if directory == "." else f"{directory}/{name}"
