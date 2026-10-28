"""Parseurs npm : package.json, lockfiles de npm, Yarn et pnpm, lien manifeste ↔ lockfile.

Les lockfiles écrits ici sont des extraits de fichiers produits par les vrais outils
(npm 11, Yarn 1.22 et 4.18, pnpm 7.33, 8.15 et 9.15), raccourcis à la main.
"""

import json
from pathlib import Path

import pytest

from forceupdate import parsers
from forceupdate.detect.manifests import DEFAULT_MAX_FILE_SIZE, find_projects
from forceupdate.models import Dependency, Ecosystem, Notice, Project, Scope
from forceupdate.parsers.base import (
    REASON_GIT,
    REASON_LOCAL,
    REASON_URL,
    REASON_WORKSPACE,
    ParseError,
)
from forceupdate.parsers.npm import (
    REASON_PATCH,
    CatalogEntry,
    nearest_pnpm_workspace,
    parse_overrides,
    parse_package_json,
    parse_package_lock_json,
    parse_pnpm_lock_yaml,
    parse_pnpm_workspace,
    parse_yarn_lock,
)
from forceupdate.sources.local import LocalSource

RUNTIME, DEV, PEER, OPTIONAL = Scope.RUNTIME, Scope.DEV, Scope.PEER, Scope.OPTIONAL


def parse(files: dict[str, str], path: str = ".") -> Project:
    """Le projet ``path`` de ``files``, avec ses dépendances lues."""
    projects, _ = find_projects(files, include_tests=True)
    project = next(p for p in projects if p.path == path)
    parsers.parse_project(project, files.get, [p.path for p in projects])
    return project


def directs(project: Project) -> list[tuple[str, str, str | None, Scope]]:
    return [(d.name, d.constraint, d.installed, d.scope) for d in project.dependencies if d.direct]


def transitives(project: Project) -> list[tuple[str, str | None, Scope]]:
    return [(d.name, d.installed, d.scope) for d in project.dependencies if not d.direct]


def assert_locations(dependencies: list[Dependency], content: str) -> None:
    """Chaque emplacement donné retombe exactement sur la contrainte."""
    for dependency in dependencies:
        if dependency.location is not None:
            assert dependency.location.extract(content) == dependency.constraint, dependency


def package_json(**sections: dict[str, str]) -> str:
    return json.dumps({"name": "demo", **sections}, indent=2) + "\n"


# ---------------------------------------------------------------------------
# Repris de reference/argos_sca_parsers_tests.py, adaptés : plus de « version »
# devinée ni de « pinned », mais la contrainte telle qu'écrite ; les paquets d'un
# lockfile sont dans NpmLockfile.lockfile.packages.
# ---------------------------------------------------------------------------


class TestParsePackageJson:
    def test_all_sections(self) -> None:
        content = json.dumps(
            {
                "dependencies": {"express": "4.18.2"},
                "devDependencies": {"jest": "^29.0.0"},
                "peerDependencies": {"react": ">=18.0.0"},
            }
        )
        deps = parse_package_json("package.json", content)
        assert [(d.name, d.constraint, d.scope) for d in deps] == [
            ("express", "4.18.2", RUNTIME),
            ("jest", "^29.0.0", DEV),
            ("react", ">=18.0.0", PEER),
        ]
        assert all(d.ecosystem is Ecosystem.NPM and d.direct and d.installed is None for d in deps)
        assert all(d.location is not None for d in deps)
        assert_locations(deps, content)


class TestParsePackageLockJson:
    def test_v2_packages_section(self) -> None:
        content = json.dumps(
            {
                "lockfileVersion": 2,
                "packages": {
                    "": {},
                    "node_modules/express": {"name": "express", "version": "4.18.2"},
                    "node_modules/lodash": {"name": "lodash", "version": "4.17.21", "dev": True},
                },
            }
        )
        lock = parse_package_lock_json("package-lock.json", content)
        packages = {p.name: p for p in lock.lockfile.packages if not p.local}
        assert set(packages) == {"express", "lodash"}
        assert packages["lodash"].scope is DEV

    def test_v1_fallback(self) -> None:
        content = json.dumps(
            {
                "lockfileVersion": 1,
                "dependencies": {"express": {"version": "4.18.2"}},
            }
        )
        lock = parse_package_lock_json("package-lock.json", content)
        packages = [p for p in lock.lockfile.packages if not p.local]
        assert [(p.name, p.version) for p in packages] == [("express", "4.18.2")]


class TestParseYarnLock:
    def test_basic(self) -> None:
        content = """\
express@^4.18.0:
  version "4.18.2"
  resolved "https://..."

lodash@^4.17.21:
  version "4.17.21"
"""
        lock = parse_yarn_lock("yarn.lock", content)
        assert {p.name for p in lock.lockfile.packages} == {"express", "lodash"}


# ---------------------------------------------------------------------------
# Contraintes et emplacements
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "name", "constraint", "located"),
    [
        ("^1.2", "x", "^1.2", "^1.2"),
        ("1.x", "x", "1.x", "1.x"),
        (">=1 <2", "x", ">=1 <2", ">=1 <2"),
        ("^1.0.0 || ^2.0.0", "x", "^1.0.0 || ^2.0.0", "^1.0.0 || ^2.0.0"),
        ("1.2.3 - 2.3.4", "x", "1.2.3 - 2.3.4", "1.2.3 - 2.3.4"),
        ("4.17.15", "x", "4.17.15", "4.17.15"),
        ("*", "x", "*", "*"),
        ("latest", "x", "latest", "latest"),
        ("  ~1.2.3 ", "x", "~1.2.3", "~1.2.3"),
        # Sans contrainte : un emplacement vide, là où l'écrire.
        ("", "x", "", ""),
        # Un alias est vérifié sous le vrai nom, avec la plage après le « @ ».
        ("npm:lodash@^4.17.0", "lodash", "^4.17.0", "^4.17.0"),
        ("npm:@scope/pkg@1.0.0", "@scope/pkg", "1.0.0", "1.0.0"),
        ("npm:^4.1.0", "x", "^4.1.0", "^4.1.0"),  # Yarn 2+ : le même paquet
        ("npm:lodash", "lodash", "", None),
        # Catalogue pnpm : la vraie plage est dans pnpm-workspace.yaml.
        ("catalog:", "x", "catalog:", None),
        ("catalog:react18", "x", "catalog:react18", None),
    ],
)
def test_constraints_are_kept_as_written(
    value: str, name: str, constraint: str, located: str | None
) -> None:
    content = package_json(dependencies={"x": value})
    [dependency] = parse_package_json("package.json", content)
    assert (dependency.name, dependency.constraint) == (name, constraint)
    assert dependency.unverifiable_reason is None
    if located is None:
        assert dependency.location is None
    else:
        assert dependency.location is not None
        assert dependency.location.extract(content) == located


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("git+https://github.com/u/r.git#v1.0.0", REASON_GIT),
        ("git+ssh://git@github.com:u/r.git", REASON_GIT),
        ("git://github.com/u/r.git", REASON_GIT),
        ("github:u/r#main", REASON_GIT),
        ("gitlab:u/r", REASON_GIT),
        ("u/r#semver:^1.0", REASON_GIT),
        ("https://github.com/u/r.git", REASON_GIT),
        ("https://user:token@example.com/x-1.0.0.tgz", REASON_URL),
        ("file:../lib", REASON_LOCAL),
        ("../lib", REASON_LOCAL),
        ("link:../lib", REASON_LOCAL),
        ("portal:../lib", REASON_LOCAL),
        ("workspace:*", REASON_WORKSPACE),
        ("workspace:^1.2.0", REASON_WORKSPACE),
        ("patch:lodash@npm%3A4.17.21#./lodash.patch", REASON_PATCH),
    ],
)
def test_unverifiable_dependencies(value: str, reason: str) -> None:
    [dependency] = parse_package_json("package.json", package_json(dependencies={"x": value}))
    assert dependency.unverifiable_reason == reason
    # Ni contrainte ni emplacement : une URL peut contenir un token.
    assert (dependency.constraint, dependency.location) == ("", None)


def test_escaped_constraint_has_no_location() -> None:
    content = '{"dependencies": {"a": "\\u005e1.0", "b": "^2.0"}}'
    a, b = parse_package_json("package.json", content)
    assert (a.constraint, a.location) == ("^1.0", None)
    assert b.location is not None
    assert_locations([a, b], content)


def test_crlf_and_bom_keep_exact_locations() -> None:
    content = "﻿" + package_json(dependencies={"lodash": "^4.17.21"}).replace("\n", "\r\n")
    [dependency] = parse_package_json("package.json", content)
    assert dependency.location is not None
    assert dependency.location.line == 4
    assert_locations([dependency], content)


def test_same_package_in_two_sections_gives_two_dependencies() -> None:
    content = package_json(devDependencies={"react": "^18.2.0"}, peerDependencies={"react": ">=17"})
    deps = parse_package_json("package.json", content)
    assert [(d.name, d.constraint, d.scope) for d in deps] == [
        ("react", "^18.2.0", DEV),
        ("react", ">=17", PEER),
    ]
    assert len({d.location for d in deps}) == 2


def test_values_that_are_not_strings_are_skipped() -> None:
    content = json.dumps({"dependencies": {"a": 1, "b": "^1"}, "devDependencies": ["c"]})
    assert [d.name for d in parse_package_json("package.json", content)] == ["b"]


@pytest.mark.parametrize("content", ["{", "[]", '"x"'])
def test_invalid_package_json_raises(content: str) -> None:
    with pytest.raises(ParseError):
        parse_package_json("package.json", content)


# ---------------------------------------------------------------------------
# package-lock.json
# ---------------------------------------------------------------------------

NPM_PACKAGE_JSON = package_json(
    dependencies={
        "debug": "~4.3.1",
        "is-odd": ">=3 <4",
        "my-ms": "npm:ms@2.0.0",
        "local-lib": "file:./vendor/local-lib",
    },
    devDependencies={"@types/ms": "*"},
)

PACKAGE_LOCK_V1 = json.dumps(
    {
        "name": "demo",
        "lockfileVersion": 1,
        "requires": True,
        "dependencies": {
            "@types/ms": {"version": "2.1.0", "dev": True},
            "debug": {"version": "4.3.7", "requires": {"ms": "^2.1.3"}},
            "is-number": {"version": "7.0.0"},
            "is-odd": {
                "version": "3.0.1",
                "requires": {"is-number": "^6.0.0"},
                "dependencies": {"is-number": {"version": "6.0.0"}},
            },
            "local-lib": {
                "version": "file:vendor/local-lib",
                "requires": {"is-number": "^6.0.0"},
                "dependencies": {"is-number": {"version": "6.0.0"}},
            },
            "ms": {"version": "2.1.3"},
            "my-ms": {"version": "npm:ms@2.0.0"},
        },
    }
)


def test_package_lock_v1_tree() -> None:
    project = parse({"package.json": NPM_PACKAGE_JSON, "package-lock.json": PACKAGE_LOCK_V1})
    assert directs(project) == [
        ("debug", "~4.3.1", "4.3.7", RUNTIME),
        ("is-odd", ">=3 <4", "3.0.1", RUNTIME),
        ("ms", "2.0.0", "2.0.0", RUNTIME),  # l'alias my-ms
        ("local-lib", "", None, RUNTIME),
        ("@types/ms", "*", "2.1.0", DEV),
    ]
    # is-number 7.0.0 n'est tiré par aucune directe : le lockfile n'étant pas celui d'un
    # workspace, il est listé quand même. Celui que tirent is-odd et local-lib est le 6.0.0.
    assert transitives(project) == [
        ("is-number", "6.0.0", RUNTIME),
        ("is-number", "7.0.0", RUNTIME),
        ("ms", "2.1.3", RUNTIME),
    ]
    assert project.notices == []


GIT_PACKAGE_JSON = package_json(
    dependencies={"is-number": "github:jonschlinkert/is-number#7.0.0", "ms": "^2.1.0"}
)
SHA = "98e8ff1da1a89f93d1397a24d7413ed15421c139"
CODELOAD = f"https://codeload.github.com/jonschlinkert/is-number/tar.gz/{SHA}"

GIT_LOCKFILES = {
    "package-lock.json": json.dumps(
        {
            "lockfileVersion": 3,
            "packages": {
                "": {
                    "dependencies": {
                        "is-number": "github:jonschlinkert/is-number#7.0.0",
                        "ms": "^2.1.0",
                    }
                },
                "node_modules/is-number": {
                    "version": "7.0.0",
                    "resolved": f"git+ssh://git@github.com/jonschlinkert/is-number.git#{SHA}",
                },
                "node_modules/ms": {
                    "version": "2.1.3",
                    "resolved": "https://registry.npmjs.org/ms/-/ms-2.1.3.tgz",
                },
            },
        }
    ),
    "yarn.lock": f"""\
# yarn lockfile v1


"is-number@github:jonschlinkert/is-number#7.0.0":
  version "7.0.0"
  resolved "{CODELOAD}"

ms@^2.1.0:
  version "2.1.3"
  resolved "https://registry.yarnpkg.com/ms/-/ms-2.1.3.tgz#574c8138ce1d2b5861f0b44579dbadd60c6615b2"
""",
    "pnpm-lock.yaml (format 6)": f"""\
lockfileVersion: '6.0'

dependencies:
  is-number:
    specifier: github:jonschlinkert/is-number#7.0.0
    version: github.com/jonschlinkert/is-number/{SHA}
  ms:
    specifier: ^2.1.0
    version: 2.1.3

packages:

  /ms@2.1.3:
    dev: false

  github.com/jonschlinkert/is-number/{SHA}:
    resolution: {{tarball: {CODELOAD}}}
    name: is-number
    version: 7.0.0
    dev: false
""",
    "pnpm-lock.yaml (format 9)": f"""\
lockfileVersion: '9.0'

importers:

  .:
    dependencies:
      is-number:
        specifier: github:jonschlinkert/is-number#7.0.0
        version: {CODELOAD}
      ms:
        specifier: ^2.1.0
        version: 2.1.3

packages:

  is-number@{CODELOAD}:
    resolution: {{tarball: {CODELOAD}}}
    version: 7.0.0

  ms@2.1.3:
    resolution: {{integrity: sha512-x}}

snapshots:

  is-number@{CODELOAD}: {{}}

  ms@2.1.3: {{}}
""",
}


@pytest.mark.parametrize("lockfile", GIT_LOCKFILES)
def test_git_dependency(lockfile: str) -> None:
    name = lockfile.split(" ")[0]
    project = parse({"package.json": GIT_PACKAGE_JSON, name: GIT_LOCKFILES[lockfile]})
    assert directs(project) == [
        ("is-number", "", "7.0.0", RUNTIME),
        ("ms", "^2.1.0", "2.1.3", RUNTIME),
    ]
    assert project.dependencies[0].unverifiable_reason == REASON_GIT
    assert transitives(project) == []
    assert project.notices == []


# ---------------------------------------------------------------------------
# yarn.lock
# ---------------------------------------------------------------------------


def test_yarn_v1_quoting_and_crlf() -> None:
    lock = """\
# yarn lockfile v1


"@babel/code-frame@^7.0.0", "@babel/code-frame@^7.10.4":
  version "7.12.13"
  dependencies:
    "@babel/highlight" "^7.12.13"

"@babel/highlight@^7.12.13":
  version "7.13.10"

"is-odd@>=3 <4":
  version "3.0.1"
""".replace("\n", "\r\n")
    content = package_json(
        dependencies={"@babel/code-frame": "^7.10.4", "is-odd": ">=3 <4"},
        devDependencies={"@babel/code-frame": "^7.0.0"},
    )
    project = parse({"package.json": content, "yarn.lock": lock})
    assert directs(project) == [
        ("@babel/code-frame", "^7.10.4", "7.12.13", RUNTIME),
        ("is-odd", ">=3 <4", "3.0.1", RUNTIME),
        ("@babel/code-frame", "^7.0.0", "7.12.13", DEV),
    ]
    assert transitives(project) == [("@babel/highlight", "7.13.10", RUNTIME)]


def test_yarn_v1_unreadable_line_raises() -> None:
    with pytest.raises(ParseError, match="ligne 3"):
        parse_yarn_lock("yarn.lock", 'lodash@^4:\n  version "4.17.21"\n  what is this\n')


YARN_V1_WORKSPACE = {
    "package.json": json.dumps(
        {"private": True, "workspaces": ["packages/*"], "dependencies": {"ms": "^2.1.0"}}
    ),
    "packages/a/package.json": package_json(dependencies={"ms": "2.0.0", "is-number": "^7"}),
    "tools/x/package.json": package_json(dependencies={"ms": "^2.1.0"}),
    "yarn.lock": """\
# yarn lockfile v1


is-number@^7:
  version "7.0.0"

ms@2.0.0:
  version "2.0.0"

ms@^2.1.0:
  version "2.1.3"
""",
}


class TestYarnV1Workspace:
    """Yarn 1 n'écrit pas les projets dans son lockfile : l'appartenance vient des
    ``workspaces`` du package.json racine, les versions des descripteurs."""

    def test_member_uses_the_root_lockfile(self) -> None:
        project = parse(YARN_V1_WORKSPACE, "packages/a")
        assert project.lockfiles == ["yarn.lock"]
        assert directs(project) == [
            ("ms", "2.0.0", "2.0.0", RUNTIME),
            ("is-number", "^7", "7.0.0", RUNTIME),
        ]
        assert transitives(project) == []

    def test_the_root_only_gets_what_it_pulls(self) -> None:
        project = parse(YARN_V1_WORKSPACE)
        assert directs(project) == [("ms", "^2.1.0", "2.1.3", RUNTIME)]
        assert transitives(project) == []

    def test_non_member_loses_the_lockfile(self) -> None:
        project = parse(YARN_V1_WORKSPACE, "tools/x")
        assert project.lockfiles == []
        assert directs(project) == [("ms", "^2.1.0", None, RUNTIME)]
        assert project.notices == []

    def test_dependency_on_a_member(self) -> None:
        """Yarn 1 n'écrit pas ``b@^1.0.0`` dans son lockfile : ``b`` est le membre, pas le
        paquet ``b`` du registre, et ce qu'il tire revient à ceux qui en dépendent."""
        files = {
            **YARN_V1_WORKSPACE,
            "packages/a/package.json": json.dumps(
                {"name": "a", "dependencies": {"b": "^1.0.0"}, "devDependencies": {"ms": "2.0.0"}}
            ),
            "packages/b/package.json": json.dumps(
                {"name": "b", "version": "1.0.0", "dependencies": {"is-number": "^7"}}
            ),
        }
        project = parse(files, "packages/a")
        assert directs(project) == [("b", "^1.0.0", None, RUNTIME), ("ms", "2.0.0", "2.0.0", DEV)]
        assert project.dependencies[0].unverifiable_reason == REASON_WORKSPACE
        assert transitives(project) == [("is-number", "7.0.0", RUNTIME)]


TYPESCRIPT_PATCH = "typescript@patch:typescript@npm%3A5.9.3#optional!builtin<compat/typescript>"


def test_yarn_berry_builtin_patch_is_not_a_transitive() -> None:
    lock = f"""\
# This file is generated by running "yarn install" inside your project.
# Manual changes might be lost - proceed with caution!

__metadata:
  version: 8
  cacheKey: 10c0

"debug@npm:~4.3.1":
  version: 4.3.7
  resolution: "debug@npm:4.3.7"
  dependencies:
    ms: "npm:^2.1.3"
  linkType: hard

"demo@workspace:.":
  version: 0.0.0-use.local
  resolution: "demo@workspace:."
  dependencies:
    debug: "npm:~4.3.1"
    typescript: "npm:^5.4.0"
  languageName: unknown
  linkType: soft

"ms@npm:^2.1.3":
  version: 2.1.3
  resolution: "ms@npm:2.1.3"
  linkType: hard

"typescript@npm:^5.4.0":
  version: 5.9.3
  resolution: "typescript@npm:5.9.3"
  linkType: hard

"typescript@patch:typescript@npm%3A^5.4.0#optional!builtin<compat/typescript>":
  version: 5.9.3
  resolution: "{TYPESCRIPT_PATCH}::version=5.9.3&hash=5786d5"
  linkType: hard
"""
    content = package_json(
        dependencies={"debug": "~4.3.1"}, devDependencies={"typescript": "^5.4.0"}
    )
    project = parse({"package.json": content, "yarn.lock": lock})
    assert directs(project) == [
        ("debug", "~4.3.1", "4.3.7", RUNTIME),
        ("typescript", "^5.4.0", "5.9.3", DEV),
    ]
    assert transitives(project) == [("ms", "2.1.3", RUNTIME)]


# ---------------------------------------------------------------------------
# pnpm-lock.yaml
# ---------------------------------------------------------------------------

PNPM_WORKSPACE = {
    "package.json": package_json(dependencies={"is-odd": ">=3 <4", "my-ms": "npm:ms@2.0.0"}),
    "pnpm-workspace.yaml": "packages:\n  - packages/*\n",
    "packages/app/package.json": package_json(
        dependencies={"lib": "workspace:*", "react": "^18.2.0", "react-dom": "^18.2.0"}
    ),
    "packages/lib/package.json": package_json(dependencies={"is-number": "^7.0.0"}),
    "pnpm-lock.yaml": """\
lockfileVersion: 5.4

importers:

  .:
    specifiers:
      is-odd: '>=3 <4'
      my-ms: npm:ms@2.0.0
    dependencies:
      is-odd: 3.0.1
      my-ms: /ms/2.0.0

  packages/app:
    specifiers:
      lib: workspace:*
      react: ^18.2.0
      react-dom: ^18.2.0
    dependencies:
      lib: link:../lib
      react: 18.3.1
      react-dom: 18.3.1_react@18.3.1

  packages/lib:
    specifiers:
      is-number: ^7.0.0
    dependencies:
      is-number: 7.0.0

packages:

  /is-number/6.0.0:
    dev: false

  /is-number/7.0.0:
    dev: false

  /is-odd/3.0.1:
    dependencies:
      is-number: 6.0.0
    dev: false

  /js-tokens/4.0.0:
    dev: false

  /loose-envify/1.4.0:
    hasBin: true
    dependencies:
      js-tokens: 4.0.0
    dev: false

  /ms/2.0.0:
    dev: false

  /react-dom/18.3.1_react@18.3.1:
    peerDependencies:
      react: ^18.3.1
    dependencies:
      loose-envify: 1.4.0
      react: 18.3.1
      scheduler: 0.23.2
    dev: false

  /react/18.3.1:
    dependencies:
      loose-envify: 1.4.0
    dev: false

  /scheduler/0.23.2:
    dependencies:
      loose-envify: 1.4.0
    dev: false
""",
}


class TestPnpmV5Workspace:
    def test_member_pulls_through_its_workspace_link(self) -> None:
        project = parse(PNPM_WORKSPACE, "packages/app")
        assert directs(project) == [
            ("lib", "", None, RUNTIME),
            ("react", "^18.2.0", "18.3.1", RUNTIME),
            ("react-dom", "^18.2.0", "18.3.1", RUNTIME),
        ]
        assert transitives(project) == [
            ("is-number", "7.0.0", RUNTIME),  # tiré par le membre lib
            ("js-tokens", "4.0.0", RUNTIME),
            ("loose-envify", "1.4.0", RUNTIME),
            ("scheduler", "0.23.2", RUNTIME),
        ]

    def test_root_alias_and_nested_version(self) -> None:
        project = parse(PNPM_WORKSPACE)
        assert directs(project) == [
            ("is-odd", ">=3 <4", "3.0.1", RUNTIME),
            ("ms", "2.0.0", "2.0.0", RUNTIME),
        ]
        assert transitives(project) == [("is-number", "6.0.0", RUNTIME)]


def test_pnpm_scoped_package_keys() -> None:
    v5 = "lockfileVersion: 5.4\npackages:\n  /@types/ms/2.1.0:\n    dev: true\n"
    v9 = (
        "lockfileVersion: '9.0'\nsnapshots:\n  '@types/react-dom@18.3.1(@types/react@18.3.3)': {}\n"
    )
    [a] = parse_pnpm_lock_yaml("pnpm-lock.yaml", v5).lockfile.packages[1:]
    assert (a.name, a.version, a.scope) == ("@types/ms", "2.1.0", DEV)
    [b] = parse_pnpm_lock_yaml("pnpm-lock.yaml", v9).lockfile.packages[1:]
    assert (b.name, b.version) == ("@types/react-dom", "18.3.1")


def test_pnpm_11_lockfile_with_an_environment_document() -> None:
    """pnpm 11 et plus écrivent d'abord un document qui fige pnpm lui-même."""
    lock = """\
---
lockfileVersion: '9.0'

importers:

  .:
    configDependencies: {}
    packageManagerDependencies:
      pnpm:
        specifier: 12.4.1
        version: 12.4.1

packages:

  pnpm@12.4.1:
    resolution: {integrity: sha512-x}

snapshots:

  pnpm@12.4.1: {}

---
lockfileVersion: '9.0'

settings:
  autoInstallPeers: true
  excludeLinksFromLockfile: false

importers:

  .:
    dependencies:
      ms:
        specifier: ^2.1.0
        version: 2.1.3

packages:

  ms@2.1.3:
    resolution: {integrity: sha512-y}

snapshots:

  ms@2.1.3: {}
"""
    project = parse(
        {"package.json": package_json(dependencies={"ms": "^2.1.0"}), "pnpm-lock.yaml": lock}
    )
    assert directs(project) == [("ms", "^2.1.0", "2.1.3", RUNTIME)]
    assert transitives(project) == []


def test_pnpm_invalid_yaml_raises() -> None:
    with pytest.raises(ParseError, match="YAML invalide"):
        parse_pnpm_lock_yaml("pnpm-lock.yaml", "importers:\n  .: [\n")


# ---------------------------------------------------------------------------
# Un projet : choix du lockfile, remarques
# ---------------------------------------------------------------------------

ROOT = {"dependencies": {"ms": "^2.1.0"}}
"""L'entrée ``""`` d'un package-lock.json : npm y recopie les dépendances déclarées."""

SIMPLE_LOCKS = {
    "package-lock.json": json.dumps(
        {
            "lockfileVersion": 3,
            "packages": {"": ROOT, "node_modules/ms": {"version": "2.1.3"}},
        }
    ),
    "npm-shrinkwrap.json": json.dumps(
        {
            "lockfileVersion": 3,
            "packages": {"": ROOT, "node_modules/ms": {"version": "2.1.2"}},
        }
    ),
    "yarn.lock": 'ms@^2.1.0:\n  version "2.1.1"\n',
    "pnpm-lock.yaml": (
        "lockfileVersion: '9.0'\nimporters:\n  .:\n    dependencies:\n      ms:\n"
        "        specifier: ^2.1.0\n        version: 2.1.0\nsnapshots:\n  ms@2.1.0: {}\n"
    ),
}


@pytest.mark.parametrize(
    ("manager", "chosen", "installed"),
    [
        (None, "npm-shrinkwrap.json", "2.1.2"),  # npm ignore package-lock.json à côté
        ("yarn@4.5.0", "yarn.lock", "2.1.1"),
        ("pnpm@9.15.9", "pnpm-lock.yaml", "2.1.0"),
        ("npm@11.6.2", "npm-shrinkwrap.json", "2.1.2"),
    ],
)
def test_package_manager_chooses_the_lockfile(
    manager: str | None, chosen: str, installed: str
) -> None:
    manifest = {"dependencies": {"ms": "^2.1.0"}}
    if manager is not None:
        manifest["packageManager"] = manager
    project = parse({"package.json": json.dumps(manifest), **SIMPLE_LOCKS})
    assert directs(project) == [("ms", "^2.1.0", installed, RUNTIME)]
    assert project.notices == [
        Notice(file=path, message=f"pas lu : {chosen} est le lockfile pris pour package.json.")
        for path in sorted(SIMPLE_LOCKS)
        if path != chosen
    ]


def test_a_lockfile_alone_gives_transitives() -> None:
    project = parse({"yarn.lock": 'ms@^2.1.0:\n  version "2.1.3"\n'})
    assert transitives(project) == [("ms", "2.1.3", RUNTIME)]


def test_invalid_files_give_notices() -> None:
    project = parse({"package.json": "{", "package-lock.json": SIMPLE_LOCKS["package-lock.json"]})
    assert [n.file for n in project.notices] == ["package.json"]
    assert project.notices[0].message.startswith("JSON invalide")
    # Sans package.json lisible, tout le lockfile est transitif.
    assert transitives(project) == [("ms", "2.1.3", RUNTIME)]

    project = parse(
        {"package.json": package_json(dependencies={"ms": "^2"}), "yarn.lock": "x y z\n"}
    )
    assert project.notices == [
        Notice(file="yarn.lock", message="yarn.lock illisible à la ligne 1.")
    ]
    assert directs(project) == [("ms", "^2", None, RUNTIME)]


def test_unreadable_lockfile_gives_a_notice() -> None:
    files = {"package.json": package_json(dependencies={"ms": "^2"}), "package-lock.json": "{}"}
    projects, _ = find_projects(files, include_tests=True)
    project = projects[0]
    parsers.parse_project(project, lambda path: files[path] if path == "package.json" else None)
    assert project.notices == [
        Notice(file="package-lock.json", message="introuvable, illisible ou trop gros : pas lu.")
    ]


def test_member_known_by_the_lockfile_even_without_globs() -> None:
    files = {
        "package.json": package_json(dependencies={"local-lib": "file:./libs/local"}),
        "libs/local/package.json": package_json(dependencies={"ms": "^2.1.0"}),
        "package-lock.json": json.dumps(
            {
                "lockfileVersion": 3,
                "packages": {
                    "": {"dependencies": {"local-lib": "file:./libs/local"}},
                    "libs/local": {"name": "local-lib", "dependencies": {"ms": "^2.1.0"}},
                    "libs/local/node_modules/ms": {"version": "2.1.3"},
                    "node_modules/local-lib": {"resolved": "libs/local", "link": True},
                },
            }
        ),
    }
    member = parse(files, "libs/local")
    assert member.lockfiles == ["package-lock.json"]
    assert directs(member) == [("ms", "^2.1.0", "2.1.3", RUNTIME)]
    root = parse(files)
    assert directs(root) == [("local-lib", "", None, RUNTIME)]
    assert transitives(root) == [("ms", "2.1.3", RUNTIME)]  # tiré à travers le lien


def test_big_package_lock_is_read(tmp_path: Path) -> None:
    """Un package-lock.json de plus de 2 Mo (le plafond des autres fichiers) est lu."""
    packages = {"": {"dependencies": {"pkg-0": "^1.0.0"}}}
    packages.update(
        {
            f"node_modules/pkg-{i}": {
                "version": "1.0.0",
                "resolved": f"https://registry.npmjs.org/pkg-{i}/-/pkg-{i}-1.0.0.tgz",
                "integrity": "sha512-" + "A" * 86 + "==",
            }
            for i in range(12_000)
        }
    )
    content = json.dumps({"lockfileVersion": 3, "packages": packages}, indent=2)
    assert len(content) > DEFAULT_MAX_FILE_SIZE
    (tmp_path / "package.json").write_text(
        package_json(dependencies={"pkg-0": "^1.0.0"}), encoding="utf-8"
    )
    (tmp_path / "package-lock.json").write_text(content, encoding="utf-8")
    source = LocalSource(tmp_path)
    projects, _ = find_projects([file.path for file in source.files()])
    parsers.parse_project(projects[0], source.read_text)
    assert projects[0].notices == []
    assert directs(projects[0]) == [("pkg-0", "^1.0.0", "1.0.0", RUNTIME)]
    assert len(transitives(projects[0])) == 11_999


def test_transitives_of_the_same_name_are_in_version_order() -> None:
    """9.0.0 avant 10.0.0 : en texte, « 10.0.0 » passerait devant."""
    lock = {
        "lockfileVersion": 3,
        "packages": {
            "": {"dependencies": {"a": "^1.0.0", "b": "^1.0.0"}},
            "node_modules/a": {"version": "1.0.0", "dependencies": {"x": "^10.0.0"}},
            "node_modules/a/node_modules/x": {"version": "10.0.0"},
            "node_modules/b": {"version": "1.0.0", "dependencies": {"x": "^9.0.0"}},
            "node_modules/x": {"version": "9.0.0"},
        },
    }
    files = {
        "package.json": package_json(dependencies={"a": "^1.0.0", "b": "^1.0.0"}),
        "package-lock.json": json.dumps(lock),
    }
    assert transitives(parse(files)) == [("x", "9.0.0", RUNTIME), ("x", "10.0.0", RUNTIME)]


# ---------------------------------------------------------------------------
# Catalogues pnpm
# ---------------------------------------------------------------------------

CATALOG_WORKSPACE = """\
packages:
  - packages/*

catalog:
  react: ^18.2.0
  my-ms: npm:ms@^2.1.0
  lib: github:me/lib

catalogs:
  legacy:
    react: ^17.0.2
"""


def catalog_deps(project: Project) -> list[tuple[str, str, str | None, str | None]]:
    return [
        (d.name, d.constraint, d.resolved_constraint, d.unverifiable_reason)
        for d in project.dependencies
        if d.direct
    ]


def test_catalog_ranges_are_read_in_pnpm_workspace_yaml() -> None:
    files = {
        "pnpm-workspace.yaml": CATALOG_WORKSPACE,
        "package.json": package_json(
            dependencies={"react": "catalog:", "lodash": "^4.17.0"},
            devDependencies={"my-ms": "catalog:default", "lib": "catalog:"},
        ),
        "packages/old/package.json": package_json(dependencies={"react": "catalog:legacy"}),
    }
    root = parse(files)
    assert root.notices == []
    assert catalog_deps(root) == [
        ("react", "catalog:", "^18.2.0", None),
        ("lodash", "^4.17.0", None, None),
        ("ms", "catalog:default", "^2.1.0", None),  # un alias dans le catalogue
        ("lib", "catalog:", None, REASON_GIT),
    ]
    # La contrainte écrite reste « catalog: », sans emplacement dans package.json.
    catalogued = [d for d in root.dependencies if d.constraint.startswith("catalog:")]
    assert [d.location for d in catalogued] == [None, None, None]
    assert [d.effective_constraint for d in root.dependencies] == [
        "^18.2.0",
        "^4.17.0",
        "^2.1.0",
        "catalog:",
    ]
    # Un membre lit le pnpm-workspace.yaml de la racine.
    old = parse(files, "packages/old")
    assert old.notices == []
    assert catalog_deps(old) == [("react", "catalog:legacy", "^17.0.2", None)]


def test_catalogs_default_is_the_default_catalog() -> None:
    files = {
        "pnpm-workspace.yaml": "catalogs:\n  default:\n    react: ^18.2.0\n",
        "package.json": package_json(dependencies={"react": "catalog:"}),
    }
    assert catalog_deps(parse(files)) == [("react", "catalog:", "^18.2.0", None)]


def test_a_missing_catalog_entry_gives_a_notice() -> None:
    files = {
        "pnpm-workspace.yaml": CATALOG_WORKSPACE,
        "package.json": package_json(dependencies={"vue": "catalog:", "react": "catalog:nope"}),
    }
    project = parse(files)
    assert catalog_deps(project) == [
        ("vue", "catalog:", None, None),
        ("react", "catalog:nope", None, None),
    ]
    assert project.notices == [
        Notice(
            file="pnpm-workspace.yaml",
            message="vue absent du catalogue « default » : plage inconnue.",
        ),
        Notice(
            file="pnpm-workspace.yaml",
            message="react absent du catalogue « nope » : plage inconnue.",
        ),
    ]


def test_a_catalog_without_pnpm_workspace_yaml_gives_a_notice() -> None:
    project = parse({"package.json": package_json(dependencies={"react": "catalog:"})})
    assert catalog_deps(project) == [("react", "catalog:", None, None)]
    assert project.notices == [
        Notice(
            file="package.json",
            message="catalog: : aucun pnpm-workspace.yaml lisible, plage inconnue.",
        )
    ]


def test_an_invalid_pnpm_workspace_yaml_gives_one_notice() -> None:
    files = {
        "pnpm-workspace.yaml": "catalog: [\n",
        "package.json": package_json(dependencies={"react": "catalog:", "vue": "catalog:"}),
    }
    project = parse(files)
    assert catalog_deps(project) == [
        ("react", "catalog:", None, None),
        ("vue", "catalog:", None, None),
    ]
    assert [n.file for n in project.notices] == ["pnpm-workspace.yaml"]
    assert project.notices[0].message.startswith("YAML invalide")


# ---------------------------------------------------------------------------
# Versions forcées : overrides (npm), resolutions (Yarn), pnpm.overrides
# ---------------------------------------------------------------------------

OVERRIDES = """{
  "name": "demo",
  "dependencies": {"lodash": "^4.17.0"},
  "overrides": {
    "dompurify": "^3.4.13",
    "foo": {".": "1.0.0", "bar": "2.0.0"},
    "baz@2": {"qux": "npm:autre@3.1.0"},
    "lodash": "$lodash",
    "local": "file:../local"
  },
  "resolutions": {"**/minimist": "1.2.8", "a/@scope/b": "~1.4.0", "c@npm:1.0.0": "1.0.1"},
  "pnpm": {"overrides": {"ms": "^2.1.3", "debug@<3": "3.2.7", "express>qs": "6.11.0"}}
}
"""


def test_overrides_are_read_with_their_location() -> None:
    found = parse_overrides("package.json", OVERRIDES)
    assert [(o.section, o.key, o.name, o.constraint) for o in found] == [
        ("overrides", "dompurify", "dompurify", "^3.4.13"),
        ("overrides", "foo", "foo", "1.0.0"),
        ("overrides", "foo>bar", "bar", "2.0.0"),
        ("overrides", "baz@2>qux", "qux", "3.1.0"),
        ("overrides", "lodash", "lodash", "$lodash"),
        ("overrides", "local", "local", ""),
        ("resolutions", "**/minimist", "minimist", "1.2.8"),
        ("resolutions", "a/@scope/b", "@scope/b", "~1.4.0"),
        ("resolutions", "c@npm:1.0.0", "c", "1.0.1"),
        ("pnpm.overrides", "ms", "ms", "^2.1.3"),
        ("pnpm.overrides", "debug@<3", "debug", "3.2.7"),
        ("pnpm.overrides", "express>qs", "qs", "6.11.0"),
    ]
    for override in found:
        assert override.ecosystem is Ecosystem.NPM
        assert override.file == "package.json"
        if override.constraint:
            assert override.location is not None
            assert override.location.extract(OVERRIDES) == override.constraint
        else:  # un chemin local : pas de contrainte, pas d'emplacement
            assert override.location is None


def test_a_project_keeps_its_overrides() -> None:
    project = parse({"package.json": OVERRIDES})
    assert [o.key for o in project.overrides][:2] == ["dompurify", "foo"]
    # Une version forcée n'est pas une dépendance.
    assert directs(project) == [("lodash", "^4.17.0", None, RUNTIME)]


def test_package_json_without_overrides() -> None:
    assert parse_overrides("package.json", package_json(dependencies={"a": "1.0.0"})) == []


# ---------------------------------------------------------------------------
# pnpm-workspace.yaml : catalogues et versions forcées, avec leur emplacement (E10)
# ---------------------------------------------------------------------------

WORKSPACE_OVERRIDES = """\
packages:
  - packages/*
catalog:
  react: ^18.2.0
overrides:
  dompurify: ^3.4.13
  "debug@<3": 3.2.7
  express>qs: '6.11.0'
  local: link:../local
"""


def test_pnpm_workspace_is_read_with_locations() -> None:
    workspace = parse_pnpm_workspace("pnpm-workspace.yaml", CATALOG_WORKSPACE)
    assert workspace.packages == ["packages/*"]
    assert [(e.catalog, e.key, e.name, e.constraint, e.reason) for e in workspace.catalogs] == [
        ("legacy", "react", "react", "^17.0.2", None),
        ("default", "react", "react", "^18.2.0", None),
        ("default", "my-ms", "ms", "^2.1.0", None),
        ("default", "lib", "lib", "", REASON_GIT),
    ]
    for entry in workspace.catalogs:
        if entry.reason is None:
            assert entry.location is not None
            assert entry.location.extract(CATALOG_WORKSPACE) == entry.constraint
        else:
            assert entry.location is None
    assert workspace.catalog_entry("default", "my-ms") == CatalogEntry(
        catalog="default",
        key="my-ms",
        name="ms",
        constraint="^2.1.0",
        location=workspace.catalogs[2].location,
    )
    assert workspace.catalog_entry("default", "vue") is None


def test_pnpm_workspace_overrides() -> None:
    found = parse_pnpm_workspace("pnpm-workspace.yaml", WORKSPACE_OVERRIDES).overrides
    assert [(o.section, o.key, o.name, o.constraint) for o in found] == [
        ("overrides", "dompurify", "dompurify", "^3.4.13"),
        ("overrides", "debug@<3", "debug", "3.2.7"),
        ("overrides", "express>qs", "qs", "6.11.0"),
        ("overrides", "local", "local", ""),
    ]
    for override in found:
        assert override.file == "pnpm-workspace.yaml"
        if override.constraint:
            assert override.location is not None
            assert override.location.extract(WORKSPACE_OVERRIDES) == override.constraint
        else:
            assert override.location is None


def test_pnpm_workspace_overrides_come_first() -> None:
    """pnpm 10 fait passer celles de pnpm-workspace.yaml devant celles du package.json ; pnpm
    11+ ne lit plus que celles-là."""
    files = {
        "pnpm-workspace.yaml": WORKSPACE_OVERRIDES,
        "package.json": json.dumps(
            {"dependencies": {"a": "1.0.0"}, "pnpm": {"overrides": {"dompurify": "^3.0.0"}}}
        ),
    }
    project = parse(files)
    assert [(o.file, o.key) for o in project.overrides] == [
        ("pnpm-workspace.yaml", "dompurify"),
        ("pnpm-workspace.yaml", "debug@<3"),
        ("pnpm-workspace.yaml", "express>qs"),
        ("pnpm-workspace.yaml", "local"),
        ("package.json", "dompurify"),
    ]
    # Un membre n'a que les siennes : seules celles de la racine comptent.
    files["packages/app/package.json"] = package_json(dependencies={"b": "1.0.0"})
    assert parse(files, "packages/app").overrides == []


def test_an_invalid_pnpm_workspace_yaml_gives_one_notice_for_its_overrides() -> None:
    files = {"pnpm-workspace.yaml": "overrides: [\n", "package.json": package_json()}
    project = parse(files)
    assert project.overrides == []
    assert [n.file for n in project.notices] == ["pnpm-workspace.yaml"]


def test_nearest_pnpm_workspace() -> None:
    files = {"pnpm-workspace.yaml": "packages: []\n", "a/b/package.json": "{}"}
    assert nearest_pnpm_workspace("a/b", files.get) == ("pnpm-workspace.yaml", "packages: []\n")
    assert nearest_pnpm_workspace("a/b", {}.get) is None
