"""Les parseurs Rust : ``Cargo.toml``, ``Cargo.lock``, et le lien entre les deux.

``TestParseCargoLock`` est repris de ``reference/argos_sca_parsers_tests.py`` ; le reste couvre ce
que la reprise a corrigé ou ajouté (``workspace = true``, plateformes, renommages, git et chemins,
membres de workspace, graphe du lockfile).
"""

import pytest

from forceupdate import parsers
from forceupdate.detect.manifests import find_projects
from forceupdate.models import Dependency, Ecosystem, Location, Notice, Project, Scope
from forceupdate.parsers.base import REASON_GIT, REASON_LOCAL, ParseError
from forceupdate.parsers.rust import (
    REASON_OTHER_REGISTRY,
    WORKSPACE_CONSTRAINT,
    parse_cargo_lock,
    parse_cargo_toml,
    parse_workspace,
    read_workspace_root,
)

RUNTIME, DEV, BUILD, OPTIONAL = Scope.RUNTIME, Scope.DEV, Scope.BUILD, Scope.OPTIONAL
CRATES_IO = 'source = "registry+https://github.com/rust-lang/crates.io-index"'


def parse(files: dict[str, str], path: str = ".") -> Project:
    """Le projet ``path`` de ``files``, avec ses dépendances lues."""
    projects, _ = find_projects(files, include_tests=True)
    project = next(p for p in projects if p.path == path)
    parsers.parse_project(project, files.get)
    return project


def directs(project: Project) -> list[tuple[str, str, str | None, Scope]]:
    return [(d.name, d.constraint, d.installed, d.scope) for d in project.dependencies if d.direct]


def transitives(project: Project) -> list[tuple[str, str | None, Scope]]:
    return [(d.name, d.installed, d.scope) for d in project.dependencies if not d.direct]


def lock(*packages: tuple[str, str, list[str]] | tuple[str, str, list[str], str | None]) -> str:
    """Un ``Cargo.lock`` (format 4) : ``(nom, version, dépendances)``, et une source (crates.io
    par défaut ; ``None`` pour un crate local)."""
    blocks = ["version = 4\n"]
    for name, version, deps, *rest in packages:
        source = rest[0] if rest else "registry+https://github.com/rust-lang/crates.io-index"
        lines = ["[[package]]", f'name = "{name}"', f'version = "{version}"']
        if source is not None:
            lines.append(f'source = "{source}"')
        if deps:
            lines.append("dependencies = [")
            lines += [f' "{dep}",' for dep in deps]
            lines.append("]")
        blocks.append("\n".join(lines) + "\n")
    return "\n".join(blocks)


# ---------------------------------------------------------------------------
# Repris de reference/argos_sca_parsers_tests.py
# ---------------------------------------------------------------------------


class TestParseCargoLock:
    def test_package_list(self) -> None:
        content = """\
[[package]]
name = "serde"
version = "1.0.189"

[[package]]
name = "tokio"
version = "1.35.0"
"""
        found = parse_cargo_lock("Cargo.lock", content).lockfile
        assert {p.name for p in found.packages} == {"serde", "tokio"}


# ---------------------------------------------------------------------------
# Cargo.toml
# ---------------------------------------------------------------------------


class TestCargoToml:
    def test_every_form_of_a_dependency(self) -> None:
        content = """\
[package]
name = "demo"
version = "0.1.0"

[dependencies]
serde = "1.0"
rand = { version = " 0.8 ", features = ["small_rng"] }
my-log = { package = "log", version = "0.4.14" }
time = { version = "0.1", optional = true }
itoa = { git = "https://github.com/dtolnay/itoa", tag = "1.0.11" }
local = { path = "../local" }
both = { path = "../both", version = "1.2" }
private = { version = "2", registry = "maison" }
explicit = { version = "3", registry = "crates-io" }
indexed = { version = "4", registry-index = "sparse+https://exemple.test/index/" }

[dependencies.anyhow]
version = "1.0"

[dev-dependencies]
pretty_assertions = "1"

[build-dependencies]
cc = "1.0"

[target.'cfg(windows)'.dependencies]
winapi = { version = "0.3", features = ["winuser"] }

[target.x86_64-unknown-linux-gnu.build-dependencies]
pkg-config = "0.3"
"""
        found = parse_cargo_toml("Cargo.toml", content)
        assert [(d.name, d.constraint, d.scope, d.unverifiable_reason) for d in found] == [
            ("serde", "1.0", RUNTIME, None),
            ("rand", "0.8", RUNTIME, None),
            ("log", "0.4.14", RUNTIME, None),
            ("time", "0.1", OPTIONAL, None),
            ("itoa", "", RUNTIME, REASON_GIT),
            ("local", "", RUNTIME, REASON_LOCAL),
            ("both", "1.2", RUNTIME, REASON_LOCAL),
            ("private", "2", RUNTIME, "vient du registre « maison », pas de crates.io"),
            ("explicit", "3", RUNTIME, None),
            ("indexed", "4", RUNTIME, REASON_OTHER_REGISTRY),
            ("anyhow", "1.0", RUNTIME, None),
            ("pretty_assertions", "1", DEV, None),
            ("cc", "1.0", BUILD, None),
            ("winapi", "0.3", RUNTIME, None),
            ("pkg-config", "0.3", BUILD, None),
        ]
        assert all(d.ecosystem is Ecosystem.CRATES_IO and d.file == "Cargo.toml" for d in found)

    def test_every_location_points_at_its_constraint(self) -> None:
        content = """\
[dependencies]
serde = "1.0"
rand = { version = " 0.8 ", features = ["small_rng"] }
'quoted' = { version = '=1.2.3' }
escaped = "\\u003e=1.2"

[dependencies.anyhow]
version = "1.0"

[target."cfg(unix)".dev-dependencies]
libc = "0.2"
"""
        found = parse_cargo_toml("Cargo.toml", content)
        located = [d for d in found if d.location is not None]
        assert [d.name for d in located] == ["serde", "rand", "quoted", "anyhow", "libc"]
        for dependency in located:
            assert dependency.location is not None
            assert dependency.location.extract(content) == dependency.constraint
        assert found[1].location == Location(line=3, column=21, end_column=24)  # sans espaces
        assert next(d for d in found if d.name == "escaped").location is None

    def test_old_underscore_sections_and_project_table(self) -> None:
        content = """\
[project]
name = "ancien"

[dev_dependencies]
a = "1"

[build_dependencies]
b = "2"
"""
        assert [(d.name, d.scope) for d in parse_cargo_toml("Cargo.toml", content)] == [
            ("a", DEV),
            ("b", BUILD),
        ]

    def test_workspace_true_has_no_constraint_of_its_own(self) -> None:
        content = """\
[dependencies]
serde = { workspace = true, features = ["derive"] }
log.workspace = true
tokio = { workspace = true, optional = true }
"""
        found = parse_cargo_toml("Cargo.toml", content)
        assert [(d.name, d.constraint, d.location, d.scope) for d in found] == [
            ("serde", WORKSPACE_CONSTRAINT, None, RUNTIME),
            ("log", WORKSPACE_CONSTRAINT, None, RUNTIME),
            ("tokio", WORKSPACE_CONSTRAINT, None, OPTIONAL),
        ]

    def test_invalid_toml(self) -> None:
        with pytest.raises(ParseError, match="TOML invalide"):
            parse_cargo_toml("Cargo.toml", "[dependencies\nserde = '1'")

    def test_an_unreadable_dependency_gives_a_notice(self) -> None:
        project = parse({"Cargo.toml": "[dependencies]\nserde = 1\nlog = '0.4'\n"})
        assert directs(project) == [("log", "0.4", None, RUNTIME)]
        assert project.notices == [
            Notice(file="Cargo.toml", message="« serde » : dépendance illisible.")
        ]


class TestWorkspaceTable:
    def test_members_exclude_and_dependencies(self) -> None:
        content = """\
[workspace]
members = ["crates/*", "tools/cli"]
exclude = ["crates/old"]

[workspace.package]
version = "0.2.0"

[workspace.dependencies]
serde = { version = "1.0.150", features = ["derive"] }
anyhow = "1.0.50"
my-log = { package = "log", version = "0.4" }
helper = { path = "crates/helper" }
"""
        workspace = parse_workspace("Cargo.toml", content)
        assert workspace is not None
        assert workspace.members == ["crates/*", "tools/cli"]
        assert workspace.package_version == "0.2.0"
        assert [(e.key, e.name, e.constraint, e.reason) for e in workspace.dependencies] == [
            ("serde", "serde", "1.0.150", None),
            ("anyhow", "anyhow", "1.0.50", None),
            ("my-log", "log", "0.4", None),
            ("helper", "helper", "", REASON_LOCAL),
        ]
        assert workspace.dependencies[0].location == Location(line=9, column=21, end_column=28)
        assert workspace.lists("crates/app") and workspace.lists("tools/cli")
        assert workspace.lists(".") and not workspace.lists("tools/other")
        assert workspace.excludes("crates/old") and workspace.excludes("crates/old/sub")
        assert not workspace.excludes("crates/older")

    def test_no_workspace_table(self) -> None:
        assert parse_workspace("Cargo.toml", "[package]\nname = 'a'\n") is None

    def test_the_nearest_root_above(self) -> None:
        files = {
            "Cargo.toml": "[workspace]\n",
            "crates/Cargo.toml": "pas du TOML",
            "crates/app/Cargo.toml": "[package]\nname = 'app'\n",
        }
        assert read_workspace_root("crates/app", files.get) == ("Cargo.toml", "[workspace]\n")
        assert read_workspace_root(".", {"Cargo.toml": "[package]\n"}.get) is None


# ---------------------------------------------------------------------------
# Cargo.lock
# ---------------------------------------------------------------------------


class TestCargoLock:
    def test_graph_with_two_versions_of_a_crate(self) -> None:
        content = lock(
            ("demo", "0.1.0", ["rand 0.8.5", "rand 0.9.2", "serde"], None),
            ("rand", "0.8.5", ["rand_core 0.6.4"]),
            ("rand", "0.9.2", ["rand_core 0.9.3"]),
            ("rand_core", "0.6.4", []),
            ("rand_core", "0.9.3", []),
            ("serde", "1.0.229", []),
        )
        found = parse_cargo_lock("Cargo.lock", content)
        packages = {p.node: p for p in found.lockfile.packages}
        assert found.lockfile.graph and found.lockfile.shared
        assert packages["demo 0.1.0"].local
        assert [node for node, _ in packages["demo 0.1.0"].dependencies] == [
            "rand 0.8.5",
            "rand 0.9.2",
            "serde 1.0.229",
        ]
        assert [node for node, _ in packages["rand 0.9.2"].dependencies] == ["rand_core 0.9.3"]

    def test_sources(self) -> None:
        content = lock(
            ("a", "1.0.0", []),
            ("b", "1.0.0", [], "sparse+https://index.crates.io/"),
            ("c", "1.0.0", [], "git+https://github.com/x/c?tag=v1#0123abc"),
            ("d", "1.0.0", [], "registry+https://maison.test/index"),
            ("e", "1.0.0", [], "sparse+https://maison.test/index/"),
            ("f", "1.0.0", [], None),
        )
        found = {p.name: p for p in parse_cargo_lock("Cargo.lock", content).lockfile.packages}
        assert [found[n].unverifiable_reason for n in "abcdef"] == [
            None,
            None,
            REASON_GIT,
            REASON_OTHER_REGISTRY,
            REASON_OTHER_REGISTRY,
            None,
        ]
        assert [found[n].local for n in "abcdef"] == [False] * 5 + [True]

    def test_format_1(self) -> None:
        """Cargo 1.0 à 1.40 : la source dans chaque dépendance, les sommes dans ``[metadata]``,
        et parfois le crate du projet dans ``[root]``."""
        content = """\
[root]
name = "demo"
version = "0.1.0"
dependencies = [
 "libc 0.2.66 (registry+https://github.com/rust-lang/crates.io-index)",
]

[[package]]
name = "libc"
version = "0.2.66"
source = "registry+https://github.com/rust-lang/crates.io-index"

[metadata]
"checksum libc 0.2.66 (registry+https://github.com/rust-lang/crates.io-index)" = "d515b1"
"""
        project = parse(
            {
                "Cargo.toml": "[package]\nname = 'demo'\nversion = '0.1.0'\n"
                "[dependencies]\nlibc = '0.2'\n",
                "Cargo.lock": content,
            }
        )
        assert directs(project) == [("libc", "0.2", "0.2.66", RUNTIME)]

    def test_same_version_from_two_sources(self) -> None:
        git = "git+https://github.com/x/a#0123abc"
        content = lock(
            (
                "demo",
                "0.1.0",
                [
                    "a 1.0.0 (registry+https://github.com/rust-lang/crates.io-index)",
                    f"a 1.0.0 ({git})",
                ],
                None,
            ),
            ("a", "1.0.0", []),
            ("a", "1.0.0", [], git),
        )
        packages = parse_cargo_lock("Cargo.lock", content).lockfile.packages
        nodes = [node for node, _ in packages[0].dependencies]
        assert len(set(nodes)) == 2
        assert {p.node for p in packages[1:]} == set(nodes)

    def test_invalid_toml(self) -> None:
        with pytest.raises(ParseError):
            parse_cargo_lock("Cargo.lock", "[[package]\n")

    def test_parse_lockfile_knows_it(self) -> None:
        found = parsers.parse_lockfile("Cargo.lock", lock(("serde", "1.0.229", [])))
        assert [(p.name, p.version) for p in found.packages] == [("serde", "1.0.229")]
        assert found.ecosystem is Ecosystem.CRATES_IO


# ---------------------------------------------------------------------------
# Un projet : manifeste et lockfile reliés
# ---------------------------------------------------------------------------

DEMO = """\
[package]
name = "demo"
version = "0.1.0"

[dependencies]
rand = "0.8"
rand09 = { package = "rand", version = "0.9" }
local = { path = "vendor/local" }

[dev-dependencies]
pretty_assertions = "1"

[build-dependencies]
cc = "1.0"
"""

DEMO_LOCK = lock(
    ("demo", "0.1.0", ["cc", "local", "pretty_assertions", "rand 0.8.5", "rand 0.9.2"], None),
    ("local", "0.1.0", ["memchr"], None),
    ("memchr", "2.7.4", []),
    ("rand", "0.8.5", ["libc"]),
    ("rand", "0.9.2", ["libc"]),
    ("libc", "0.2.170", []),
    ("pretty_assertions", "1.4.1", ["diff", "libc"]),
    ("diff", "0.1.13", []),
    ("cc", "1.2.0", ["shlex"]),
    ("shlex", "1.3.0", []),
)


class TestProject:
    def test_installed_versions_and_transitives(self) -> None:
        project = parse({"Cargo.toml": DEMO, "Cargo.lock": DEMO_LOCK})
        assert directs(project) == [
            ("rand", "0.8", "0.8.5", RUNTIME),
            ("rand", "0.9", "0.9.2", RUNTIME),
            ("local", "", None, RUNTIME),
            ("pretty_assertions", "1", "1.4.1", DEV),
            ("cc", "1.0", "1.2.0", BUILD),
        ]
        assert all(d.lockfile == "Cargo.lock" for d in project.dependencies if d.installed)
        # libc vient de rand (runtime) et de pretty_assertions (dev) : runtime l'emporte. Les
        # dépendances de build passent avant celles de dev.
        assert transitives(project) == [
            ("diff", "0.1.13", DEV),
            ("libc", "0.2.170", RUNTIME),
            ("memchr", "2.7.4", RUNTIME),
            ("shlex", "1.3.0", BUILD),
        ]
        assert project.notices == []

    def test_a_crate_patched_from_git_is_not_verifiable(self) -> None:
        content = lock(
            ("demo", "0.1.0", ["serde"], None),
            ("serde", "1.0.229", [], "git+https://github.com/serde-rs/serde#0123abc"),
        )
        manifest = "[package]\nname = 'demo'\nversion = '0.1.0'\n[dependencies]\nserde = '1'\n"
        project = parse({"Cargo.toml": manifest, "Cargo.lock": content})
        (serde,) = project.dependencies
        assert serde.unverifiable_reason == REASON_GIT
        assert serde.installed == "1.0.229"

    def test_without_the_crate_of_the_project_in_the_lockfile(self) -> None:
        """Le lockfile ne connaît pas le crate (renommé depuis) : la plus haute version du nom
        qui respecte la contrainte."""
        manifest = "[package]\nname = 'neuf'\n[dependencies]\nrand = '0.8'\n"
        content = lock(("rand", "0.8.5", []), ("rand", "0.9.2", []))
        project = parse({"Cargo.toml": manifest, "Cargo.lock": content})
        assert directs(project) == [("rand", "0.8", "0.8.5", RUNTIME)]
        assert transitives(project) == []

    def test_a_lockfile_without_manifest_is_all_transitive(self) -> None:
        project = parse({"Cargo.lock": lock(("serde", "1.0.229", []), ("x", "0.1.0", [], None))})
        assert transitives(project) == [("serde", "1.0.229", RUNTIME)]

    def test_an_unreadable_lockfile_gives_a_notice(self) -> None:
        project = parse({"Cargo.toml": DEMO, "Cargo.lock": "[[package]\n"})
        assert [d.installed for d in project.dependencies] == [None] * 5
        assert [n.file for n in project.notices] == ["Cargo.lock"]


ROOT = """\
[workspace]
members = ["crates/*"]
exclude = ["crates/excluded"]

[workspace.package]
version = "0.2.0"

[workspace.dependencies]
serde = { version = "1.0.150", features = ["derive"] }
my-log = { package = "log", version = "0.4" }
itoa = { git = "https://github.com/dtolnay/itoa" }
"""

APP = """\
[package]
name = "app"
version.workspace = true

[dependencies]
serde = { workspace = true }
my-log.workspace = true
itoa.workspace = true
core = { path = "../../core" }
"""

WORKSPACE_LOCK = lock(
    ("app", "0.2.0", ["core", "itoa", "log", "serde"], None),
    ("core", "0.1.0", ["serde"], None),
    ("itoa", "1.0.11", [], "git+https://github.com/dtolnay/itoa#0123abc"),
    ("log", "0.4.17", []),
    ("serde", "1.0.160", []),
)


class TestWorkspace:
    def test_a_member_takes_its_constraints_from_the_root(self) -> None:
        files = {"Cargo.toml": ROOT, "Cargo.lock": WORKSPACE_LOCK, "crates/app/Cargo.toml": APP}
        project = parse(files, "crates/app")
        assert project.lockfiles == ["Cargo.lock"]
        found = [
            (d.name, d.constraint, d.resolved_constraint, d.installed, d.unverifiable_reason)
            for d in project.dependencies
            if d.direct
        ]
        assert found == [
            ("serde", WORKSPACE_CONSTRAINT, "1.0.150", "1.0.160", None),
            ("log", WORKSPACE_CONSTRAINT, "0.4", "0.4.17", None),
            ("itoa", WORKSPACE_CONSTRAINT, None, "1.0.11", REASON_GIT),
            ("core", "", None, None, REASON_LOCAL),
        ]
        assert all(d.location is None for d in project.dependencies)
        assert project.notices == []

    def test_the_virtual_root_has_no_dependency(self) -> None:
        files = {"Cargo.toml": ROOT, "Cargo.lock": WORKSPACE_LOCK, "crates/app/Cargo.toml": APP}
        root = parse(files)
        assert root.dependencies == [] and root.notices == []

    def test_an_excluded_crate_keeps_neither_lockfile_nor_workspace(self) -> None:
        files = {
            "Cargo.toml": ROOT,
            "Cargo.lock": WORKSPACE_LOCK,
            "crates/excluded/Cargo.toml": "[package]\nname = 'x'\n"
            "[dependencies]\nserde.workspace = true\n",
        }
        project = parse(files, "crates/excluded")
        assert project.lockfiles == []
        (serde,) = project.dependencies
        assert serde.resolved_constraint is None and serde.installed is None
        assert project.notices == [
            Notice(
                file="crates/excluded/Cargo.toml",
                message="« serde » : workspace = true, mais pas de workspace au-dessus : "
                "contrainte inconnue.",
            )
        ]

    def test_a_path_dependency_is_a_member_even_outside_members(self) -> None:
        files = {
            "Cargo.toml": ROOT,
            "Cargo.lock": WORKSPACE_LOCK,
            "crates/app/Cargo.toml": APP,
            "core/Cargo.toml": "[package]\nname = 'core'\nversion = '0.1.0'\n"
            "[dependencies]\nserde.workspace = true\n",
        }
        project = parse(files, "core")
        assert project.lockfiles == ["Cargo.lock"]
        assert directs(project) == [("serde", WORKSPACE_CONSTRAINT, "1.0.160", RUNTIME)]

    def test_a_crate_outside_the_workspace_loses_the_lockfile(self) -> None:
        files = {
            "Cargo.toml": ROOT,
            "Cargo.lock": "[[package]\n",  # illisible : la remarque ne vaut pas pour lui
            "tools/other/Cargo.toml": "[package]\nname = 'other'\n[dependencies]\nlog = '0.4'\n",
        }
        project = parse(files, "tools/other")
        assert project.lockfiles == []
        assert directs(project) == [("log", "0.4", None, RUNTIME)]
        assert project.notices == []

    def test_a_single_crate_does_not_lend_its_lockfile(self) -> None:
        """Sans ``[workspace]`` à la racine, un crate plus bas n'en fait pas partie : Cargo lui
        ferait son propre lockfile."""
        files = {
            "Cargo.toml": "[package]\nname = 'root'\n"
            "[dependencies]\nhelper = { path = 'libs/helper' }\n",
            "Cargo.lock": lock(("root", "0.0.0", ["helper"], None), ("helper", "0.0.0", [], None)),
            "libs/helper/Cargo.toml": "[package]\nname = 'helper'\n",
        }
        assert parse(files, "libs/helper").lockfiles == []

    def test_a_key_absent_from_the_root(self) -> None:
        files = {
            "Cargo.toml": ROOT,
            "crates/app/Cargo.toml": "[package]\nname = 'app'\n"
            "[dependencies]\ntokio.workspace = true\n",
        }
        project = parse(files, "crates/app")
        (tokio,) = project.dependencies
        assert tokio.resolved_constraint is None
        assert project.notices == [
            Notice(
                file="Cargo.toml",
                message="« tokio » absent de [workspace.dependencies] : contrainte inconnue.",
            )
        ]

    def test_the_root_crate_takes_its_own_workspace_dependencies(self) -> None:
        content = ROOT.replace(
            "[workspace]",
            "[package]\nname = 'racine'\nversion = '0.1.0'\n\n"
            "[dependencies]\nserde.workspace = true\n\n[workspace]",
        )
        project = parse({"Cargo.toml": content})
        assert [(d.name, d.resolved_constraint) for d in project.dependencies] == [
            ("serde", "1.0.150")
        ]

    def test_an_explicit_workspace_key(self) -> None:
        files = {
            "ws/Cargo.toml": ROOT,
            "app/Cargo.toml": "[package]\nname = 'app'\nworkspace = '../ws'\n"
            "[dependencies]\nserde.workspace = true\n",
        }
        project = parse(files, "app")
        assert [d.resolved_constraint for d in project.dependencies] == ["1.0.150"]


def test_dependency_fields() -> None:
    project = parse({"Cargo.toml": "[dependencies]\nserde = '1.0'\n"})
    assert project.dependencies == [
        Dependency(
            ecosystem=Ecosystem.CRATES_IO,
            name="serde",
            constraint="1.0",
            file="Cargo.toml",
            location=Location(line=2, column=9, end_column=12),
        )
    ]
