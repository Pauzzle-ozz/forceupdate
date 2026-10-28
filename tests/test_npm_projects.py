"""Les mini-projets npm de ``tests/projects/`` : directes, versions installées, transitives.

Leurs lockfiles ont été produits par les vrais outils (voir ``tests/projects/README.md``) ;
les versions attendues ont été relues dans ces lockfiles.
"""

from pathlib import Path

import pytest

from forceupdate import engine
from forceupdate.models import Project, Scope
from forceupdate.parsers.base import REASON_LOCAL, REASON_WORKSPACE
from forceupdate.sources.local import LocalSource

PROJECTS = Path(__file__).parent / "projects"
NAMES = ["npm", "yarn1", "yarn4", "pnpm9", "npm-workspace"]

RUNTIME, DEV, PEER, OPTIONAL = Scope.RUNTIME, Scope.DEV, Scope.PEER, Scope.OPTIONAL


def scan(name: str) -> dict[str, Project]:
    report = engine.inventory(LocalSource(PROJECTS / name))
    return {project.path: project for project in report.projects}


def directs(project: Project) -> list[tuple[str, str, str | None, Scope]]:
    return [(d.name, d.constraint, d.installed, d.scope) for d in project.dependencies if d.direct]


def transitives(project: Project) -> list[tuple[str, str | None, Scope]]:
    return [(d.name, d.installed, d.scope) for d in project.dependencies if not d.direct]


def reasons(project: Project) -> dict[str, str]:
    return {
        d.name: d.unverifiable_reason
        for d in project.dependencies
        if d.unverifiable_reason is not None
    }


@pytest.mark.parametrize("name", NAMES)
def test_every_location_points_at_its_constraint(name: str) -> None:
    source = LocalSource(PROJECTS / name)
    report = engine.inventory(source)
    located = 0
    for project in report.projects:
        assert project.notices == [], project.path
        for dependency in project.dependencies:
            if dependency.location is not None:
                text = source.read_text(dependency.file)
                assert text is not None
                assert dependency.location.extract(text) == dependency.constraint, dependency
                located += 1
    assert located > 0


@pytest.mark.parametrize("name", NAMES)
def test_no_duplicate_declaration_in_a_file(name: str) -> None:
    for project in scan(name).values():
        keys = [(d.file, d.location, d.name, d.installed) for d in project.dependencies]
        assert len(keys) == len(set(keys)), project.path


# Les mêmes directes pour npm et Yarn 1, sauf react : Yarn 1 n'installe pas les pairs du
# projet lui-même.
NPM_DIRECTS = [
    ("chalk", "^4.1.0", "4.1.2", RUNTIME),
    ("debug", "~4.3.1", "4.3.7", RUNTIME),
    ("is-number", "7.x", "7.0.0", RUNTIME),
    ("is-odd", ">=3 <4", "3.0.1", RUNTIME),
    ("lodash", "4.17.15", "4.17.15", RUNTIME),
    ("ms", "2.0.0", "2.0.0", RUNTIME),  # l'alias « my-ms »: « npm:ms@2.0.0 »
    ("@sindresorhus/is", "^4.0.0", "4.6.0", RUNTIME),
    ("local-lib", "", None, RUNTIME),
    ("@types/ms", "*", "2.1.0", DEV),
    ("semver", "^6.0.0 || ^7.0.0", "7.8.5", DEV),
    ("react", "^18.0.0", "18.3.1", PEER),
    ("fsevents", "^2.3.3", "2.3.3", OPTIONAL),
]
CHALK_TREE = [
    ("ansi-styles", "4.3.0", RUNTIME),
    ("color-convert", "2.0.1", RUNTIME),
    ("color-name", "1.1.4", RUNTIME),
    ("has-flag", "4.0.0", RUNTIME),
]


def test_npm() -> None:
    project = scan("npm")["."]
    assert project.lockfiles == ["package-lock.json"]
    assert directs(project) == NPM_DIRECTS
    assert reasons(project) == {"local-lib": REASON_LOCAL}
    assert transitives(project) == [
        *CHALK_TREE,
        ("is-number", "6.0.0", RUNTIME),  # node_modules/is-odd/node_modules/is-number
        ("js-tokens", "4.0.0", PEER),  # tirés par react, un pair
        ("loose-envify", "1.4.0", PEER),
        ("ms", "2.1.3", RUNTIME),  # tiré par debug ; l'alias, lui, est le 2.0.0
        ("supports-color", "7.2.0", RUNTIME),
    ]


def test_yarn1() -> None:
    project = scan("yarn1")["."]
    assert project.lockfiles == ["yarn.lock"]
    expected = [d if d[0] != "react" else ("react", "^18.0.0", None, PEER) for d in NPM_DIRECTS]
    assert directs(project) == expected
    assert transitives(project) == [
        *CHALK_TREE,
        ("is-number", "6.0.0", RUNTIME),
        ("ms", "2.1.3", RUNTIME),
        ("supports-color", "7.2.0", RUNTIME),
    ]


def test_yarn4_workspace() -> None:
    projects = scan("yarn4")
    assert list(projects) == [".", "packages/lib"]

    root = projects["."]
    assert directs(root) == [
        ("chalk", "^4.1.0", "4.1.2", RUNTIME),
        ("is-odd", ">=3 <4", "3.0.1", RUNTIME),
        ("lib", "", None, RUNTIME),
        ("ms", "2.0.0", "2.0.0", RUNTIME),
        ("typescript", "^5.4.0", "5.9.3", DEV),  # et pas une deuxième fois pour son « patch: »
        ("fsevents", "^2.3.3", "2.3.3", OPTIONAL),
    ]
    assert reasons(root) == {"lib": REASON_WORKSPACE}
    found = transitives(root)
    # Tirés par le membre lib, ou par chalk et is-odd.
    assert [t for t in found if t[2] is RUNTIME] == [
        *CHALK_TREE[:3],
        ("debug", "4.3.7", RUNTIME),
        ("has-flag", "4.0.0", RUNTIME),
        ("is-number", "6.0.0", RUNTIME),
        ("is-number", "7.0.0", RUNTIME),
        ("ms", "2.1.3", RUNTIME),
        ("supports-color", "7.2.0", RUNTIME),
    ]
    # Yarn ajoute node-gyp aux dépendances de fsevents, qui se compile : tout ça est facultatif.
    optional = {name for name, _, scope in found if scope is OPTIONAL}
    assert {"node-gyp", "tar", "which", "semver"} <= optional
    assert len(found) == 29

    lib = projects["packages/lib"]
    assert lib.lockfiles == ["yarn.lock"]
    assert directs(lib) == [
        ("debug", "~4.3.1", "4.3.7", RUNTIME),
        ("is-number", "^7.0.0", "7.0.0", RUNTIME),
        ("react", "^18.0.0", None, PEER),  # un pair : Yarn ne l'installe pas
    ]
    assert transitives(lib) == [("ms", "2.1.3", RUNTIME)]


def test_pnpm9_workspace() -> None:
    projects = scan("pnpm9")
    assert list(projects) == [".", "packages/app", "packages/excluded", "packages/lib"]

    root = projects["."]
    assert directs(root) == [
        ("chalk", "^4.1.0", "4.1.2", RUNTIME),
        ("is-odd", ">=3 <4", "3.0.1", RUNTIME),
        ("ms", "2.0.0", "2.0.0", RUNTIME),
        ("semver", "^6.0.0 || ^7.0.0", "7.8.5", DEV),
        ("fsevents", "^2.3.3", "2.3.3", OPTIONAL),
    ]
    assert transitives(root) == [
        *CHALK_TREE,
        ("is-number", "6.0.0", RUNTIME),
        ("supports-color", "7.2.0", RUNTIME),
    ]

    app = projects["packages/app"]
    assert directs(app) == [
        ("lib", "", None, RUNTIME),
        ("react", "^18.2.0", "18.3.1", RUNTIME),
        ("react-dom", "^18.2.0", "18.3.1", RUNTIME),  # « 18.3.1(react@18.3.1) » dans le lock
    ]
    assert reasons(app) == {"lib": REASON_WORKSPACE}
    assert transitives(app) == [
        ("is-number", "7.0.0", RUNTIME),  # tiré par le membre lib
        ("js-tokens", "4.0.0", RUNTIME),
        ("loose-envify", "1.4.0", RUNTIME),
        ("scheduler", "0.23.2", RUNTIME),
    ]

    lib = projects["packages/lib"]
    assert directs(lib) == [
        ("is-number", "^7.0.0", "7.0.0", RUNTIME),
        ("react", "^18.0.0", "18.3.1", PEER),  # pnpm installe les pairs (autoInstallPeers)
    ]
    assert transitives(lib) == [("js-tokens", "4.0.0", PEER), ("loose-envify", "1.4.0", PEER)]

    # Exclu par « !packages/excluded » dans pnpm-workspace.yaml.
    excluded = projects["packages/excluded"]
    assert excluded.lockfiles == []
    assert directs(excluded) == [("lodash", "^4.17.21", None, RUNTIME)]


def test_pnpm_catalogs() -> None:
    """Les plages des catalogues (« catalog: », « catalogs: ») sont lues dans
    pnpm-workspace.yaml ; la contrainte écrite reste « catalog: »."""
    projects = scan("pnpm-catalog")
    assert list(projects) == [".", "packages/app"]

    def catalogs(project: Project) -> list[tuple[str, str, str | None, str | None]]:
        return [
            (d.name, d.constraint, d.resolved_constraint, d.installed)
            for d in project.dependencies
            if d.direct
        ]

    root, app = projects["."], projects["packages/app"]
    assert root.notices == app.notices == []
    assert catalogs(root) == [
        ("is-number", "catalog:", "^7.0.0", "7.0.0"),
        ("ms", "catalog:default", "^2.1.0", "2.1.3"),  # « my-ms »: « npm:ms@^2.1.0 »
    ]
    assert transitives(root) == []
    assert catalogs(app) == [
        ("is-odd", "catalog:legacy", "^2.0.0", "2.0.0"),
        ("is-number", "catalog:", "^7.0.0", "7.0.0"),
    ]
    assert transitives(app) == [("is-number", "4.0.0", RUNTIME)]  # tiré par is-odd
    assert all(d.location is None for p in projects.values() for d in p.dependencies)


def test_npm_workspace() -> None:
    projects = scan("npm-workspace")
    assert list(projects) == [".", "packages/a", "packages/b", "tools/script"]

    root = projects["."]
    assert directs(root) == [
        ("is-number", "^7.0.0", "7.0.0", RUNTIME),
        ("semver", "^7.6.0", "7.8.5", DEV),
    ]
    assert transitives(root) == []  # le reste du lockfile est aux membres

    a = projects["packages/a"]
    assert a.lockfiles == ["package-lock.json"]
    assert directs(a) == [
        ("is-number", "^6.0.0", "6.0.0", RUNTIME),  # packages/a/node_modules/is-number
        ("debug", "~4.3.1", "4.3.7", RUNTIME),
    ]
    assert transitives(a) == [("ms", "2.1.3", RUNTIME)]

    b = projects["packages/b"]
    assert directs(b) == [("a", "^1.0.0", None, RUNTIME), ("chalk", "^4.1.0", "4.1.2", RUNTIME)]
    assert reasons(b) == {"a": REASON_WORKSPACE}
    assert transitives(b) == [
        *CHALK_TREE[:3],
        ("debug", "4.3.7", RUNTIME),  # tirés par le membre a
        ("has-flag", "4.0.0", RUNTIME),
        ("is-number", "6.0.0", RUNTIME),
        ("ms", "2.1.3", RUNTIME),
        ("supports-color", "7.2.0", RUNTIME),
    ]

    # Hors des « workspaces » du package.json racine : le lockfile n'est pas à lui.
    script = projects["tools/script"]
    assert script.lockfiles == []
    assert directs(script) == [("ms", "^2.1.0", None, RUNTIME)]


@pytest.mark.parametrize("name", NAMES)
def test_every_installed_version_names_its_lockfile(name: str) -> None:
    """La version installée d'une dépendance vient d'un lockfile du projet : celui qu'une mise
    à jour régénère (E11). Une indirecte vient de son lockfile."""
    named = 0
    for project in scan(name).values():
        for dependency in project.dependencies:
            if dependency.installed is None:
                assert dependency.lockfile is None, dependency
                continue
            assert dependency.lockfile in project.lockfiles, dependency
            if not dependency.direct:
                assert dependency.lockfile == dependency.file
            named += 1
    assert named > 0
