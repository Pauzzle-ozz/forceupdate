"""Les parseurs Go : ``go.mod``, ``go.work``, et le lien avec les workspaces.

``TestParseGoMod.test_require_block`` est repris de ``reference/argos_sca_parsers_tests.py`` ; le
reste couvre ce que la reprise a corrigé ou ajouté (``// indirect``, emplacements, ``replace``,
``exclude``, ``retract``, dépréciation, chaînes, workspaces). ``TestParseGoSum`` n'est pas repris :
``go.sum`` n'est plus une source de versions.
"""

import pytest

from forceupdate import parsers
from forceupdate.detect.manifests import find_projects
from forceupdate.models import Ecosystem, Location, Notice, Project
from forceupdate.parsers.base import REASON_LOCAL, REASON_WORKSPACE, ParseError
from forceupdate.parsers.go import (
    is_directory_path,
    locked_versions,
    parse_go_mod,
    parse_go_mod_file,
)


def parse(files: dict[str, str], path: str = ".") -> Project:
    """Le projet ``path`` de ``files``, avec ses dépendances lues."""
    projects, _ = find_projects(files, include_tests=True)
    project = next(p for p in projects if p.path == path)
    parsers.parse_project(project, files.get)
    return project


def summary(project: Project) -> list[tuple[str, str, bool, str | None]]:
    return [(d.name, d.constraint, d.direct, d.unverifiable_reason) for d in project.dependencies]


class TestParseGoMod:
    def test_require_block(self) -> None:
        content = """\
module example.com/app

go 1.21

require (
    github.com/gin-gonic/gin v1.9.1
    github.com/gorilla/mux v1.8.1 // indirect
)

require github.com/stretchr/testify v1.8.4
"""
        comps = parse_go_mod("go.mod", content)
        names = {c.name for c in comps}
        assert "github.com/gin-gonic/gin" in names
        assert "github.com/gorilla/mux" in names
        assert "github.com/stretchr/testify" in names

    def test_directs_then_indirects_with_their_versions(self) -> None:
        content = """\
module example.com/app

go 1.21

require (
\tgithub.com/gin-gonic/gin v1.9.1
\tgithub.com/gorilla/mux v1.8.1 // indirect
\tgolang.org/x/text v0.3.7 // indirect; sert à gin
)

require github.com/stretchr/testify v1.8.4
"""
        found = parse_go_mod("svc/go.mod", content)
        assert [(d.name, d.constraint, d.installed, d.direct) for d in found] == [
            ("github.com/gin-gonic/gin", "v1.9.1", "v1.9.1", True),
            ("github.com/stretchr/testify", "v1.8.4", "v1.8.4", True),
            ("github.com/gorilla/mux", "v1.8.1", "v1.8.1", False),
            ("golang.org/x/text", "v0.3.7", "v0.3.7", False),
        ]
        assert {d.lockfile for d in found} == {"svc/go.sum"}
        assert {d.file for d in found} == {"svc/go.mod"}
        assert all(d.ecosystem is Ecosystem.GO for d in found)

    def test_locations_are_exact(self) -> None:
        content = (
            "module m\n\nrequire (\n\tgithub.com/a/b v1.2.3 // indirect\n)\n\n"
            'require "c.io/d" "v0.1.0"\n'
        )
        found = {d.name: d for d in parse_go_mod("go.mod", content)}
        assert found["github.com/a/b"].location == Location(line=4, column=16, end_column=22)
        assert found["c.io/d"].location == Location(line=7, column=18, end_column=24)
        for dependency in found.values():
            assert dependency.location is not None
            assert dependency.location.extract(content) == dependency.constraint

    def test_a_string_with_escapes_has_no_location(self) -> None:
        found = parse_go_mod("go.mod", 'module m\nrequire c.io/d "v0.1\\x2e0"\n')
        assert [(d.constraint, d.location) for d in found] == [("v0.1.0", None)]

    @pytest.mark.parametrize("suffix", ["// indirect", "//indirect", "// indirect; why"])
    def test_indirect_marks(self, suffix: str) -> None:
        found = parse_go_mod("go.mod", f"module m\nrequire a.io/b v1.0.0 {suffix}\n")
        assert [d.direct for d in found] == [False]

    @pytest.mark.parametrize("suffix", ["// indirection", "// not indirect", "// indirect why"])
    def test_other_comments_are_not_indirect(self, suffix: str) -> None:
        found = parse_go_mod("go.mod", f"module m\nrequire a.io/b v1.0.0 {suffix}\n")
        assert [d.direct for d in found] == [True]

    def test_replace_by_a_local_path(self) -> None:
        content = """\
module m

require (
\texample.com/local v0.0.0
\texample.com/win v1.0.0
)

replace example.com/local => ./third_party/local

replace example.com/win v1.0.0 => C:\\src\\win
"""
        found = parse_go_mod("go.mod", content)
        assert [(d.name, d.installed, d.lockfile, d.unverifiable_reason) for d in found] == [
            ("example.com/local", None, None, REASON_LOCAL),
            ("example.com/win", None, None, REASON_LOCAL),
        ]

    def test_replace_by_a_module_checks_the_replacement(self) -> None:
        content = """\
module m

require (
\tgithub.com/google/uuid v1.3.0
\tgithub.com/orig/pkg v1.0.0
\tgithub.com/other/pkg v1.0.0
)

replace github.com/google/uuid => github.com/google/uuid v1.4.0

replace (
\tgithub.com/orig/pkg v1.0.0 => github.com/fork/pkg v1.0.5
\tgithub.com/other/pkg v0.9.0 => github.com/fork/other v0.9.1
)
"""
        found = parse_go_mod("go.mod", content)
        assert [(d.name, d.constraint, d.installed) for d in found] == [
            ("github.com/google/uuid", "v1.4.0", "v1.4.0"),
            ("github.com/fork/pkg", "v1.0.5", "v1.0.5"),
            ("github.com/other/pkg", "v1.0.0", "v1.0.0"),  # le replace vise une autre version
        ]
        uuid = found[0]
        assert uuid.location == Location(line=9, column=57, end_column=63)
        assert uuid.location.extract(content) == "v1.4.0"

    def test_a_versioned_replace_wins(self) -> None:
        content = (
            "module m\nrequire a.io/b v1.0.0\n"
            "replace a.io/b => a.io/b v1.0.1\nreplace a.io/b v1.0.0 => a.io/b v1.0.2\n"
        )
        assert [d.constraint for d in parse_go_mod("go.mod", content)] == ["v1.0.2"]

    def test_excluded_versions(self) -> None:
        content = """\
module m

require github.com/BurntSushi/toml v1.2.0

exclude (
\tgithub.com/BurntSushi/toml v1.6.0
\tgithub.com/BurntSushi/toml v1.5.0
)

exclude golang.org/x/text v0.3.9
"""
        found = parse_go_mod("go.mod", content)
        assert [d.excluded for d in found] == [("v1.6.0", "v1.5.0")]

    def test_pseudo_versions_and_incompatible(self) -> None:
        content = (
            "module m\nrequire (\n"
            "\tgopkg.in/yaml.v3 v3.0.0-20200313102051-9f266ea9e77c // indirect\n"
            "\tgithub.com/go-chi/chi v4.1.2+incompatible\n)\n"
        )
        found = parse_go_mod("go.mod", content)
        assert [d.constraint for d in found] == [
            "v4.1.2+incompatible",
            "v3.0.0-20200313102051-9f266ea9e77c",
        ]

    def test_crlf(self) -> None:
        content = "module m\r\n\r\nrequire (\r\n\ta.io/b v1.0.0 // indirect\r\n)\r\n"
        found = parse_go_mod("go.mod", content)
        assert [(d.name, d.direct, d.location) for d in found] == [
            ("a.io/b", False, Location(line=4, column=8, end_column=14))
        ]

    @pytest.mark.parametrize(
        "content",
        ["module m\nrequire (\n\ta.io/b v1.0.0\n", 'module m\nrequire a.io/b "v1.0.0\n'],
    )
    def test_invalid_files(self, content: str) -> None:
        with pytest.raises(ParseError):
            parse_go_mod("go.mod", content)


class TestGoModFile:
    def test_directives(self) -> None:
        content = """\
// Deprecated: use example.com/mod/v2 instead.
module example.com/mod

go 1.21.0

toolchain go1.22.4

godebug (
\tdefault=go1.21
)

tool golang.org/x/tools/cmd/stringer

ignore ./node_modules

retract (
\tv1.0.0 // Published accidentally.
\t// Contains a backwards incompatible change.
\t[v1.1.0, v1.1.5]
)

retract v0.9.0
"""
        parsed = parse_go_mod_file("go.mod", content)
        assert parsed.module == "example.com/mod"
        assert parsed.deprecated == "use example.com/mod/v2 instead."
        assert (parsed.go, parsed.toolchain) == ("1.21.0", "go1.22.4")
        assert [(r.low, r.high, r.rationale) for r in parsed.retracts] == [
            ("v1.0.0", "v1.0.0", "Published accidentally."),
            ("v1.1.0", "v1.1.5", "Contains a backwards incompatible change."),
            ("v0.9.0", "v0.9.0", ""),
        ]
        assert parsed.notices == []
        assert parsed.pruned

    def test_deprecation_after_module_and_paragraphs(self) -> None:
        assert parse_go_mod_file("go.mod", "module m // Deprecated: gone\n").deprecated == "gone"
        content = "// Notes.\n//\n// Deprecated: use m/v2.\n//\n// More.\nmodule m\n"
        assert parse_go_mod_file("go.mod", content).deprecated == "use m/v2."
        content = "// Not Deprecated: really.\nmodule m\n"
        assert parse_go_mod_file("go.mod", content).deprecated is None

    def test_block_comments_give_the_rationale(self) -> None:
        content = "module m\n// Bad releases.\nretract (\n\tv1.0.0\n\tv1.0.1 // Own reason.\n)\n"
        parsed = parse_go_mod_file("go.mod", content)
        assert [r.rationale for r in parsed.retracts] == ["Bad releases.", "Own reason."]

    def test_a_proxy_go_mod_of_a_module_without_one(self) -> None:
        parsed = parse_go_mod_file("go.mod", "module github.com/pkg/errors\n")
        assert (parsed.module, parsed.go, parsed.pruned) == ("github.com/pkg/errors", None, False)

    def test_unreadable_directives_give_notices(self) -> None:
        content = "module m\nrequire a.io/b\nreplace a.io/c => a.io/d\nfrobnicate x\n"
        parsed = parse_go_mod_file("go.mod", content)
        assert [n.message.split(" : ")[0] for n in parsed.notices] == [
            "ligne 2",
            "ligne 3",
            "ligne 4",
        ]
        assert "inconnue" in parsed.notices[2].message

    def test_locked_versions(self) -> None:
        content = (
            "module m\nrequire (\n\ta.io/b v1.0.0\n\ta.io/c v0.1.0 // indirect\n"
            "\tl.io/x v0.0.0\n)\nreplace l.io/x => ../x\n"
        )
        lock = locked_versions("go.mod", content)
        assert [(p.name, p.version) for p in lock.packages] == [
            ("a.io/b", "v1.0.0"),
            ("a.io/c", "v0.1.0"),
        ]
        assert parsers.parse_lockfile("app/go.mod", content).packages == lock.packages


@pytest.mark.parametrize(
    ("path", "directory"),
    [
        ("./x", True),
        ("../x", True),
        (".", True),
        ("/abs/x", True),
        ("C:\\x", True),
        (".\\x", True),
        ("github.com/a/b", False),
        ("example.com", False),
    ],
)
def test_directory_paths(path: str, directory: bool) -> None:
    assert is_directory_path(path) is directory


class TestProject:
    def test_a_module(self) -> None:
        project = parse(
            {
                "go.mod": "module m\n\ngo 1.21\n\nrequire a.io/b v1.0.0\n",
                "go.sum": "a.io/b v1.0.0 h1:x=\n",
            }
        )
        assert project.ecosystems == [Ecosystem.GO]
        assert (project.manifests, project.lockfiles) == (["go.mod"], ["go.sum"])
        assert summary(project) == [("a.io/b", "v1.0.0", True, None)]
        assert project.notices == []

    def test_before_go_1_17(self) -> None:
        project = parse({"go.mod": "module m\n\ngo 1.16\n\nrequire a.io/b v1.0.0\n"})
        assert [n.message.split(" : ")[0] for n in project.notices] == ["go 1.16"]
        project = parse({"go.mod": "module m\nrequire a.io/b v1.0.0\n"})
        assert project.notices[0].message.startswith("sans directive go : avant Go 1.17")

    def test_invalid_go_mod(self) -> None:
        project = parse({"go.mod": "module m\nrequire (\n"})
        assert project.dependencies == []
        assert project.notices == [
            Notice(file="go.mod", message="bloc « require ( » de la ligne 2 jamais fermé.")
        ]

    def test_workspace_members_and_replaces(self) -> None:
        files = {
            "go.work": (
                "go 1.21\n\nuse (\n\t./app\n\t./lib\n)\n\n"
                "replace golang.org/x/text => golang.org/x/text v0.3.8\n"
            ),
            "app/go.mod": (
                "module example.com/ws/app\n\ngo 1.21\n\nrequire (\n\texample.com/ws/lib v0.0.0\n"
                "\tgolang.org/x/text v0.3.7\n\tgithub.com/google/uuid v1.3.0\n)\n"
            ),
            "lib/go.mod": "module example.com/ws/lib\n\ngo 1.21\n",
            "tools/go.mod": (
                "module example.com/ws/tools\n\ngo 1.21\n\nrequire example.com/ws/lib v0.0.0\n"
            ),
        }
        root = parse(files)
        assert (root.manifests, root.dependencies) == (["go.work"], [])
        app = parse(files, "app")
        assert summary(app) == [
            ("example.com/ws/lib", "v0.0.0", True, REASON_WORKSPACE),
            ("golang.org/x/text", "v0.3.8", True, None),
            ("github.com/google/uuid", "v1.3.0", True, None),
        ]
        text = app.dependencies[1]
        assert (text.file, text.installed, text.lockfile) == ("go.work", "v0.3.8", None)
        assert text.location == Location(line=8, column=47, end_column=53)
        assert text.location.extract(files["go.work"]) == "v0.3.8"
        # tools n'est pas dans « use » : hors du workspace, son require cherche le module.
        assert summary(parse(files, "tools")) == [("example.com/ws/lib", "v0.0.0", True, None)]

    def test_the_workspace_builds_the_highest_version_of_its_members(self) -> None:
        """E34 : ``go`` construit chaque module à la plus haute version que demandent les membres
        (vérifié avec Go 1.27 : x/text v0.3.0 chez a, v0.14.0 chez b, v0.14.0 pour les deux)."""
        files = {
            "go.work": "go 1.22\n\nuse (\n\t./a\n\t./b\n)\n",
            "a/go.mod": (
                "module example.com/a\n\ngo 1.22\n\nrequire (\n\tgolang.org/x/text v0.3.0\n"
                "\tgithub.com/google/uuid v1.6.0\n)\n"
            ),
            "b/go.mod": (
                "module example.com/b\n\ngo 1.22\n\nrequire (\n\tgolang.org/x/text v0.14.0\n"
                "\tgithub.com/google/uuid v1.3.0 // indirect\n)\n"
            ),
        }
        a = parse(files, "a")
        text, uuid = a.dependencies
        assert (text.constraint, text.installed) == ("v0.3.0", "v0.14.0")
        assert (uuid.constraint, uuid.installed) == ("v1.6.0", "v1.6.0")
        (notice,) = a.notices
        assert notice.message == (
            "Dans le workspace go.work, go construit 1 module dans une version plus haute que "
            "celle de go.mod, demandée par un autre membre : golang.org/x/text v0.14.0. C'est "
            "elle qui est vérifiée."
        )
        b = parse(files, "b")
        assert [d.installed for d in b.dependencies] == ["v0.14.0", "v1.6.0"]
        assert b.notices[0].message.endswith(
            ": github.com/google/uuid v1.6.0. C'est elle qui est vérifiée."
        )
        # Hors du workspace (GOWORK=off), le go.mod seul.
        alone = {k: v for k, v in files.items() if k != "go.work"}
        assert [d.installed for d in parse(alone, "a").dependencies] == ["v0.3.0", "v1.6.0"]

    def test_the_nearest_go_work_decides(self) -> None:
        files = {
            "go.work": "go 1.21\nuse ./a/b\n",
            "a/go.work": "go 1.21\nuse ./c\n",
            "a/b/go.mod": "module b\nrequire c v0.0.0\n",
            "a/c/go.mod": "module c\n",
        }
        # a/go.work est le plus proche de a/b, et ne le cite pas : a/b n'est dans aucun workspace.
        assert summary(parse(files, "a/b")) == [("c", "v0.0.0", True, None)]
