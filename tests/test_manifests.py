"""Fichiers de dépendances : reconnaissance, chemins de tests, lecture, regroupement en projets."""

import logging
from pathlib import Path

import pytest

from forceupdate.detect.manifests import (
    DEFAULT_MAX_FILE_SIZE,
    DEFAULT_MAX_LOCKFILE_SIZE,
    DependencyFile,
    compiled_requirements,
    discover_dependency_manifests,
    ecosystem_for_manifest,
    find_projects,
    group_projects,
    is_ignored_path,
    is_test_path,
    lockfile_candidates,
    match_dependency_file,
    max_read_size,
    safe_read_text,
)
from forceupdate.models import Ecosystem, Project


class TestEcosystemMapping:
    """Repris de ``reference/argos_sca_parsers_tests.py`` (L367), plus les noms ajoutés."""

    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("requirements.txt", "PyPI"),
            ("package.json", "npm"),
            ("Gemfile.lock", "RubyGems"),
            ("go.sum", "Go"),
            ("Cargo.lock", "crates.io"),
            ("composer.json", "Packagist"),
            ("pom.xml", "Maven"),
            ("packages.config", "NuGet"),
            ("readme.md", None),
            # Ajoutés à E02
            ("requirements-dev.txt", "PyPI"),
            ("requirements_test.in", "PyPI"),
            ("uv.lock", "PyPI"),
            ("Pipfile", "PyPI"),
            ("PACKAGE.JSON", "npm"),
            ("build.gradle", "Maven"),
            ("build.gradle.kts", "Maven"),
            ("App.csproj", "NuGet"),
            ("Lib.fsproj", "NuGet"),
            ("Directory.Packages.props", "NuGet"),
            ("packages.lock.json", "NuGet"),
            ("requirements.md", None),
            ("libs.versions.toml", None),
        ],
    )
    def test_ecosystem(self, tmp_path: Path, filename: str, expected: str | None) -> None:
        fp = tmp_path / filename
        fp.touch()
        assert ecosystem_for_manifest(fp) == expected


@pytest.mark.parametrize(
    ("path", "project", "lockfile"),
    [
        ("pyproject.toml", ".", False),
        ("backend/requirements.txt", "backend", False),
        ("requirements/dev.txt", ".", False),
        ("backend/requirements/prod.in", "backend", False),
        ("requirements/requirements.txt", ".", False),
        ("gradle/libs.versions.toml", ".", False),
        ("android/gradle/libs.versions.toml", "android", False),
        ("src/App/App.csproj", "src/App", False),
        ("frontend/package-lock.json", "frontend", True),
        ("uv.lock", ".", True),
    ],
)
def test_match_dependency_file_finds_the_project(path: str, project: str, lockfile: bool) -> None:
    match = match_dependency_file(path)
    assert match is not None
    assert (match.path, match.project, match.lockfile) == (path, project, lockfile)


@pytest.mark.parametrize("path", ["notes.txt", "src/app.py", "docs/requirements.md", "gradle.toml"])
def test_match_dependency_file_ignores_other_files(path: str) -> None:
    assert match_dependency_file(path) is None


def test_lockfile_candidates_are_next_to_the_manifest() -> None:
    assert lockfile_candidates("api/pyproject.toml") == [
        "api/uv.lock",
        "api/poetry.lock",
        "api/pdm.lock",
    ]
    assert lockfile_candidates("App.csproj") == ["packages.lock.json"]
    assert lockfile_candidates("requirements.txt") == []
    assert lockfile_candidates("uv.lock") == []


def test_lockfile_candidate_of_a_pip_tools_source_is_its_compiled_txt() -> None:
    assert lockfile_candidates("requirements.in") == ["requirements.txt"]
    assert lockfile_candidates("api/requirements-dev.in") == ["api/requirements-dev.txt"]
    assert lockfile_candidates("requirements/prod.in") == ["requirements/prod.txt"]


def test_compiled_requirements_have_a_source_next_to_them() -> None:
    paths = [
        "requirements.in",
        "requirements.txt",
        "requirements-dev.txt",
        "requirements/prod.in",
        "requirements/prod.txt",
        "api/Requirements.IN",
        "api/requirements.txt",
        "other/requirements.txt",
    ]
    assert compiled_requirements(paths) == {
        "requirements.txt",
        "requirements/prod.txt",
        "api/requirements.txt",
    }


def test_lockfiles_may_be_bigger() -> None:
    assert max_read_size("uv.lock") == DEFAULT_MAX_LOCKFILE_SIZE
    assert max_read_size("web/package-lock.json") == DEFAULT_MAX_LOCKFILE_SIZE
    assert max_read_size("pyproject.toml") == DEFAULT_MAX_FILE_SIZE
    assert max_read_size("src/app.py") == DEFAULT_MAX_FILE_SIZE


@pytest.mark.parametrize(
    "path",
    [
        "tests/projects/npm/package.json",
        "pkg/test/data/go.mod",
        "web/__tests__/x.js",
        "spec/fixtures/Gemfile",
        "examples/app/package.json",
        "Tests/Fixture/App.csproj",
        "src\\tests\\requirements.txt",
        "test_app.py",
        "conftest.py",
        "pkg/server_test.go",
        "src/Button.spec.tsx",
        "src/FooTest.java",
    ],
)
def test_is_test_path(path: str) -> None:
    assert is_test_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "package.json",
        "src/app.py",
        "requirements-test.txt",
        "testcharms/app/requirements.txt",
        "packages/ui-test/package.json",
        "latest/package.json",
        "src/Contest.java",
        "src/contest.py",
    ],
)
def test_is_not_test_path(path: str) -> None:
    assert not is_test_path(path)


def test_is_ignored_path_looks_at_directories_only() -> None:
    assert is_ignored_path("node_modules/x/package.json")
    assert is_ignored_path("app/.venv/lib/pyproject.toml")
    assert is_ignored_path("src/forceupdate.egg-info/PKG-INFO")
    assert not is_ignored_path("src/build.py")
    assert not is_ignored_path("build")


class TestSafeReadText:
    def test_reads_utf8(self, tmp_path: Path) -> None:
        fp = tmp_path / "requirements.txt"
        fp.write_text("flask==3.0.0  # légère\n", encoding="utf-8")
        assert safe_read_text(fp) == "flask==3.0.0  # légère\n"

    def test_replaces_invalid_bytes(self, tmp_path: Path) -> None:
        fp = tmp_path / "requirements.txt"
        fp.write_bytes(b"flask \xe9\n")
        assert safe_read_text(fp) == "flask �\n"

    def test_too_big_gives_none(self, tmp_path: Path) -> None:
        fp = tmp_path / "package-lock.json"
        fp.write_text("x" * 11, encoding="utf-8")
        assert safe_read_text(fp, max_size=10) is None
        assert safe_read_text(fp, max_size=11) == "x" * 11

    def test_missing_gives_none(self, tmp_path: Path) -> None:
        assert safe_read_text(tmp_path / "absent.txt") is None


class TestDiscoverDependencyManifests:
    PATHS = (
        "src/app.py",
        "pyproject.toml",
        "uv.lock",
        "frontend/package.json",
        "frontend/node_modules/left-pad/package.json",
        ".venv/lib/site-packages/x/pyproject.toml",
        "tests/projects/npm/package.json",
        "README.md",
    )

    def test_finds_manifests_and_lockfiles_sorted(self) -> None:
        assert discover_dependency_manifests(self.PATHS) == [
            "frontend/package.json",
            "pyproject.toml",
            "tests/projects/npm/package.json",
            "uv.lock",
        ]

    def test_can_leave_out_test_paths(self) -> None:
        found = discover_dependency_manifests(self.PATHS, include_test_paths=False)
        assert "tests/projects/npm/package.json" not in found

    def test_stops_at_max_files(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            found = discover_dependency_manifests(self.PATHS, max_files=2)
        assert found == ["pyproject.toml", "uv.lock"]
        assert "limite de 2" in caplog.text


class TestGroupProjects:
    def test_monorepo_gives_one_project_per_folder(self) -> None:
        projects = group_projects(
            [
                "frontend/package.json",
                "frontend/package-lock.json",
                "backend/pyproject.toml",
                "backend/uv.lock",
                "backend/requirements/dev.txt",
            ]
        )
        assert projects == [
            Project(
                path="backend",
                ecosystems=[Ecosystem.PYPI],
                manifests=["backend/pyproject.toml", "backend/requirements/dev.txt"],
                lockfiles=["backend/uv.lock"],
            ),
            Project(
                path="frontend",
                ecosystems=[Ecosystem.NPM],
                manifests=["frontend/package.json"],
                lockfiles=["frontend/package-lock.json"],
            ),
        ]

    def test_root_comes_first_and_mixed_ecosystems_are_ordered(self) -> None:
        projects = group_projects(["web/package.json", "package.json", "pyproject.toml"])
        assert [p.path for p in projects] == [".", "web"]
        assert projects[0].ecosystems == [Ecosystem.PYPI, Ecosystem.NPM]

    def test_workspace_members_share_the_root_lockfile(self) -> None:
        projects = group_projects(
            [
                "package.json",
                "pnpm-lock.yaml",
                "packages/ui/package.json",
                "packages/own/package.json",
                "packages/own/package-lock.json",
            ]
        )
        lockfiles = {p.path: p.lockfiles for p in projects}
        assert lockfiles == {
            ".": ["pnpm-lock.yaml"],
            "packages/own": ["packages/own/package-lock.json"],
            "packages/ui": ["pnpm-lock.yaml"],
        }

    def test_uv_and_cargo_workspaces(self) -> None:
        projects = group_projects(
            [
                "pyproject.toml",
                "uv.lock",
                "libs/core/pyproject.toml",
                "Cargo.toml",
                "Cargo.lock",
                "crates/cli/Cargo.toml",
            ]
        )
        lockfiles = {p.path: p.lockfiles for p in projects}
        assert lockfiles["libs/core"] == ["uv.lock"]
        assert lockfiles["crates/cli"] == ["Cargo.lock"]

    def test_poetry_lockfile_is_not_shared(self) -> None:
        projects = group_projects(["pyproject.toml", "poetry.lock", "docs/pyproject.toml"])
        assert {p.path: p.lockfiles for p in projects}["docs"] == []

    def test_workspace_root_needs_the_same_manifest(self) -> None:
        projects = group_projects(["yarn.lock", "app/package.json"])
        assert projects == [
            Project(path=".", ecosystems=[Ecosystem.NPM], lockfiles=["yarn.lock"]),
            Project(path="app", ecosystems=[Ecosystem.NPM], manifests=["app/package.json"]),
        ]

    def test_nearest_workspace_root_wins(self) -> None:
        projects = group_projects(
            [
                "package.json",
                "yarn.lock",
                "apps/package.json",
                "apps/package-lock.json",
                "apps/web/package.json",
            ]
        )
        assert {p.path: p.lockfiles for p in projects}["apps/web"] == ["apps/package-lock.json"]

    def test_other_files_are_ignored(self) -> None:
        assert group_projects(["src/app.py", "README.md"]) == []

    def test_pip_tools_compiled_txt_is_a_lockfile(self) -> None:
        projects = group_projects(
            [
                "requirements.in",
                "requirements.txt",
                "requirements-dev.in",
                "requirements-dev.txt",
                "requirements-docs.txt",
            ]
        )
        assert projects == [
            Project(
                path=".",
                ecosystems=[Ecosystem.PYPI],
                manifests=["requirements-dev.in", "requirements-docs.txt", "requirements.in"],
                lockfiles=["requirements-dev.txt", "requirements.txt"],
            )
        ]


def test_find_projects_sets_test_folders_aside() -> None:
    paths = ["pyproject.toml", "tests/projects/npm/package.json", "examples/demo/go.mod"]
    projects, ignored = find_projects(paths)
    assert [p.path for p in projects] == ["."]
    assert ignored == ["examples/demo/go.mod", "tests/projects/npm/package.json"]

    projects, ignored = find_projects(paths, include_tests=True)
    assert [p.path for p in projects] == [".", "examples/demo", "tests/projects/npm"]
    assert ignored == []


def test_dependency_file_is_a_tuple() -> None:
    match = match_dependency_file("backend/uv.lock")
    assert match == DependencyFile("backend/uv.lock", "backend", "uv.lock", Ecosystem.PYPI, True)
