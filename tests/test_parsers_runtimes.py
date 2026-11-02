"""La version des runtimes d'un projet, lue sans rien exécuter (E27) : ``parsers.runtimes``, et les
fichiers de runtime que ``detect.manifests`` rattache à chaque projet."""

import pytest

from forceupdate import parsers
from forceupdate.detect.manifests import find_projects, is_runtime_file
from forceupdate.models import Project
from forceupdate.parsers.runtimes import dockerfile, target_framework


def projects(files: dict[str, str], *, include_tests: bool = False) -> dict[str, Project]:
    """Les projets de ``files`` (chemin → contenu), lus, par dossier."""
    found, _ = find_projects(list(files), include_tests=include_tests)
    for item in found:
        parsers.parse_project(item, files.get)
    return {item.path: item for item in found}


def runtimes(files: dict[str, str], path: str = ".") -> list[tuple[str, str, bool, str, str]]:
    """Les runtimes du projet ``path`` : produit, version, borne basse, fichier, ce qui est lu."""
    return [
        (r.product, r.version, r.approximate, r.file, r.source)
        for r in projects(files)[path].runtimes
    ]


# ---------------------------------------------------------------------------
# Les fichiers de runtime, rattachés aux projets
# ---------------------------------------------------------------------------


class TestRuntimeFiles:
    @pytest.mark.parametrize(
        "path",
        [
            ".python-version",
            "runtime.txt",
            ".nvmrc",
            ".node-version",
            ".ruby-version",
            ".tool-versions",
            "global.json",
            "Dockerfile",
            "docker/Dockerfile.prod",
            "app.Dockerfile",
            "dockerfile",
            "Containerfile",
        ],
    )
    def test_recognized(self, path: str) -> None:
        assert is_runtime_file(path)

    @pytest.mark.parametrize("path", ["Dockerfile.dockerignore", ".dockerignore", "versions.txt"])
    def test_not_recognized(self, path: str) -> None:
        assert not is_runtime_file(path)

    def test_the_nearest_of_each_name_in_the_folder_or_above(self) -> None:
        found = projects(
            {
                ".nvmrc": "16\n",
                "global.json": "{}",
                "web/package.json": "{}",
                "web/.nvmrc": "20\n",
                "api/package.json": "{}",
                "api/deep/package.json": "{}",
            }
        )
        assert found["web"].runtime_files == ["global.json", "web/.nvmrc"]
        assert found["api"].runtime_files == [".nvmrc", "global.json"]
        assert found["api/deep"].runtime_files == [".nvmrc", "global.json"]

    def test_a_dockerfile_goes_to_the_nearest_project_at_or_above(self) -> None:
        found = projects(
            {
                "package.json": "{}",
                "docker/Dockerfile": "FROM node:20\n",
                "api/pyproject.toml": "[project]\nname = 'api'\n",
                "api/Dockerfile": "FROM python:3.12\n",
            }
        )
        assert found["."].runtime_files == ["docker/Dockerfile"]
        assert found["api"].runtime_files == ["api/Dockerfile"]

    def test_without_project_above_a_dockerfile_goes_to_those_below(self) -> None:
        found = projects(
            {
                "Dockerfile": "FROM python:3.8\n",
                "app/requirements.txt": "flask==3.0\n",
                "front/package.json": "{}",
            }
        )
        assert found["app"].runtime_files == ["Dockerfile"]
        assert found["front"].runtime_files == ["Dockerfile"]
        # Le FROM python d'un autre dossier ne vaut que pour le projet Python.
        assert [r.product for r in found["app"].runtimes] == ["python"]
        assert found["front"].runtimes == []

    def test_test_folders_and_ignored_folders_are_skipped(self) -> None:
        files = {
            "package.json": "{}",
            "node_modules/x/.nvmrc": "12\n",
            "examples/Dockerfile": "FROM node:12\n",
        }
        assert projects(files)["."].runtime_files == []
        found, _ = find_projects(list(files), include_tests=True)
        assert found[0].runtime_files == ["examples/Dockerfile"]

    def test_a_version_file_of_another_folder_needs_the_ecosystem(self) -> None:
        files = {
            ".nvmrc": "16\n",
            ".python-version": "3.12\n",
            "pyproject.toml": "[project]\nname = 'root'\n",
            "api/requirements.txt": "flask\n",
        }
        # À la racine, ses propres fichiers comptent tous ; dans api/, seul Python.
        assert {r.product for r in projects(files)["."].runtimes} == {"nodejs", "python"}
        assert runtimes(files, "api") == [("python", "3.12", False, ".python-version", "3.12")]


# ---------------------------------------------------------------------------
# Les manifestes
# ---------------------------------------------------------------------------


class TestManifests:
    def test_python(self) -> None:
        files = {
            "pyproject.toml": (
                '[project]\nname = "a"\nrequires-python = ">=3.8"\n'
                '[tool.poetry.dependencies]\npython = "^3.9"\n'
            ),
            "Pipfile": '[packages]\n[requires]\npython_version = "3.10"\n',
            "setup.cfg": "[options]\npython_requires = >=3.7\n",
        }
        assert runtimes(files) == [
            ("python", "3.8", True, "pyproject.toml", 'requires-python = ">=3.8"'),
            (
                "python",
                "3.9",
                True,
                "pyproject.toml",
                '[tool.poetry.dependencies] python = "^3.9"',
            ),
            ("python", "3.10", False, "Pipfile", '[requires] python_version = "3.10"'),
            ("python", "3.7", True, "setup.cfg", "python_requires = >=3.7"),
        ]

    def test_a_constraint_without_lower_bound_says_nothing(self) -> None:
        files = {
            "pyproject.toml": '[project]\nname = "a"\nrequires-python = "<4"\n',
            "package.json": '{"engines": {"node": "*"}}',
        }
        assert runtimes(files) == []

    def test_node(self) -> None:
        files = {
            "package.json": (
                '{"engines": {"node": "^16.13.0 || >=18"}, "volta": {"node": "16.20.2"}}'
            )
        }
        assert runtimes(files) == [
            ("nodejs", "16.13", True, "package.json", 'engines.node = "^16.13.0 || >=18"'),
            ("nodejs", "16.20.2", False, "package.json", 'volta.node = "16.20.2"'),
        ]

    def test_go(self) -> None:
        files = {"go.mod": "module example.com/a\n\ngo 1.21.0\n\ntoolchain go1.22.3\n"}
        assert runtimes(files) == [
            ("go", "1.22.3", False, "go.mod", "toolchain go1.22.3"),
            ("go", "1.21.0", True, "go.mod", "go 1.21.0"),
        ]

    def test_php(self) -> None:
        files = {
            "composer.json": (
                '{"require": {"php": "^8.1", "monolog/monolog": "^3.0"},'
                ' "config": {"platform": {"php": "8.1.30"}}}'
            )
        }
        assert runtimes(files) == [
            ("php", "8.1.30", False, "composer.json", 'config.platform.php = "8.1.30"'),
            ("php", "8.1", True, "composer.json", 'require.php = "^8.1"'),
        ]

    def test_ruby(self) -> None:
        files = {
            "Gemfile": 'source "https://rubygems.org"\nruby "~> 3.2"\ngem "rack", "~> 2.2"\n',
            "Gemfile.lock": (
                "GEM\n  remote: https://rubygems.org/\n  specs:\n    rack (2.2.3)\n\n"
                "PLATFORMS\n  ruby\n\nDEPENDENCIES\n  rack (~> 2.2)\n\n"
                "RUBY VERSION\n   ruby 3.2.2p53\n\nBUNDLED WITH\n   2.4.10\n"
            ),
        }
        assert runtimes(files) == [
            ("ruby", "3.2", True, "Gemfile", 'ruby "~> 3.2"'),
            ("ruby", "3.2.2", False, "Gemfile.lock", "RUBY VERSION ruby 3.2.2p53"),
        ]

    def test_maven_properties_of_the_pom_and_its_parents(self) -> None:
        parent = (
            "<project><groupId>g</groupId><artifactId>parent</artifactId><version>1</version>"
            "<properties><java.version>1.8</java.version></properties></project>"
        )
        child = (
            "<project><parent><groupId>g</groupId><artifactId>parent</artifactId>"
            "<version>1</version></parent><artifactId>app</artifactId>"
            "<properties><maven.compiler.release>${java.version}</maven.compiler.release>"
            "</properties></project>"
        )
        files = {"pom.xml": parent, "app/pom.xml": child}
        assert runtimes(files, "app") == [
            (
                "eclipse-temurin",
                "8",
                True,
                "app/pom.xml",
                "<maven.compiler.release>${java.version}</maven.compiler.release>",
            )
        ]
        assert runtimes(files) == [
            ("eclipse-temurin", "8", True, "pom.xml", "<java.version>1.8</java.version>")
        ]

    @pytest.mark.parametrize(
        ("script", "expected"),
        [
            (
                "java {\n  toolchain {\n    languageVersion = JavaLanguageVersion.of(17)\n  }\n}\n",
                ("17", False, "JavaLanguageVersion.of(17)"),
            ),
            ("kotlin {\n    jvmToolchain(21)\n}\n", ("21", False, "jvmToolchain(21)")),
            (
                "sourceCompatibility = JavaVersion.VERSION_1_8\ntargetCompatibility = '11'\n",
                ("11", True, "targetCompatibility = '11'"),
            ),
            (
                "// jvmToolchain(8)\nsourceCompatibility = 17\n",
                ("17", True, "sourceCompatibility = 17"),
            ),
        ],
    )
    def test_gradle(self, script: str, expected: tuple[str, bool, str]) -> None:
        version, approximate, source = expected
        assert runtimes({"build.gradle": script}) == [
            ("eclipse-temurin", version, approximate, "build.gradle", source)
        ]

    def test_dotnet_target_frameworks(self) -> None:
        files = {
            "src/App/Directory.Build.props": (
                "<Project><PropertyGroup><TargetFramework>net8.0</TargetFramework>"
                "</PropertyGroup></Project>"
            ),
            "src/App/App.csproj": '<Project Sdk="Microsoft.NET.Sdk"></Project>',
            "src/Lib/Lib.csproj": (
                "<Project><PropertyGroup><TargetFrameworks>netstandard2.0;net48;netcoreapp3.1"
                "</TargetFrameworks></PropertyGroup></Project>"
            ),
            "legacy/Old.csproj": (
                "<Project><PropertyGroup><TargetFrameworkVersion>v4.7.2</TargetFrameworkVersion>"
                "</PropertyGroup></Project>"
            ),
        }
        assert runtimes(files, "src/App") == [
            (
                "dotnet",
                "8.0",
                False,
                "src/App/Directory.Build.props",
                "<TargetFramework>net8.0</TargetFramework>",
            )
        ]
        written = "<TargetFrameworks>netstandard2.0;net48;netcoreapp3.1</TargetFrameworks>"
        assert runtimes(files, "src/Lib") == [
            ("dotnetfx", "4.8", False, "src/Lib/Lib.csproj", written),
            ("dotnet", "3.1", False, "src/Lib/Lib.csproj", written),
        ]
        assert [r[:2] for r in runtimes(files, "legacy")] == [("dotnetfx", "4.7.2")]

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("net8.0", ("dotnet", "8.0")),
            ("net10.0-windows10.0.19041", ("dotnet", "10.0")),
            ("netcoreapp2.1", ("dotnet", "2.1")),
            ("net48", ("dotnetfx", "4.8")),
            ("net481", ("dotnetfx", "4.8.1")),
            ("net35", ("dotnetfx", "3.5")),
            ("netstandard2.1", None),
            ("monoandroid10", None),
        ],
    )
    def test_target_framework(self, value: str, expected: tuple[str, str] | None) -> None:
        runtime = target_framework(value, file="a.csproj", source=value)
        assert (None if runtime is None else (runtime.product, runtime.version)) == expected


# ---------------------------------------------------------------------------
# Les fichiers de version
# ---------------------------------------------------------------------------


class TestVersionFiles:
    @pytest.mark.parametrize(
        ("name", "content", "expected"),
        [
            (".python-version", "3.8.10\n", ("python", "3.8.10")),
            (".python-version", "# pyenv\n3.12\n3.11\n", ("python", "3.12")),
            (".python-version", "3.13t\n", ("python", "3.13")),
            (".python-version", "cpython-3.11.4\n", ("python", "3.11.4")),
            (".python-version", "pypy3.9-7.3.11\n", None),
            (".python-version", "system\n", None),
            ("runtime.txt", "python-3.8.10\n", ("python", "3.8.10")),
            ("runtime.txt", "ruby-2.7\n", None),
            (".nvmrc", "16\n", ("nodejs", "16")),
            (".nvmrc", "v16.20.2\n", ("nodejs", "16.20.2")),
            (".nvmrc", "lts/gallium\n", ("nodejs", "16")),
            (".nvmrc", "lts/*\n", None),
            (".nvmrc", "node\n", None),
            (".node-version", "20.11.1\n", ("nodejs", "20.11.1")),
            (".ruby-version", "ruby-3.2.2\n", ("ruby", "3.2.2")),
            (".ruby-version", "3.1.4p223\n", ("ruby", "3.1.4")),
            (".ruby-version", "jruby-9.4.5.0\n", None),
            ("global.json", '{"sdk": {"version": "8.0.100"}}', ("dotnet", "8.0.100")),
            ("global.json", '{"sdk": {"rollForward": "latestMajor"}}', None),
        ],
    )
    def test_one_file(self, name: str, content: str, expected: tuple[str, str] | None) -> None:
        manifest = "requirements.txt" if expected is None else _manifest(expected[0])
        found = runtimes({manifest: _empty(manifest), name: content})
        assert [(product, version) for product, version, *_ in found] == (
            [] if expected is None else [expected]
        )

    def test_tool_versions(self) -> None:
        content = (
            "nodejs 16.20.2\npython 3.8.10 3.9.1\nruby 3.2.2\ngolang 1.21.0\nphp 8.1.2\n"
            "java temurin-17.0.2+8\ndotnet-core 8.0.100\nterraform 1.5.0\n# rien\n"
        )
        files = {".tool-versions": content, "package.json": "{}"}
        assert [(p, v, source) for p, v, _, _, source in runtimes(files)] == [
            ("nodejs", "16.20.2", "nodejs 16.20.2"),
            ("python", "3.8.10", "python 3.8.10"),
            ("ruby", "3.2.2", "ruby 3.2.2"),
            ("go", "1.21.0", "golang 1.21.0"),
            ("php", "8.1.2", "php 8.1.2"),
            ("eclipse-temurin", "17", "java temurin-17.0.2+8"),
            ("dotnet", "8.0.100", "dotnet-core 8.0.100"),
        ]


def _manifest(product: str) -> str:
    return {
        "python": "requirements.txt",
        "nodejs": "package.json",
        "ruby": "Gemfile",
        "dotnet": "App.csproj",
    }[product]


def _empty(manifest: str) -> str:
    return {
        "requirements.txt": "",
        "package.json": "{}",
        "Gemfile": "",
        "App.csproj": "<Project></Project>",
    }[manifest]


# ---------------------------------------------------------------------------
# Les Dockerfile
# ---------------------------------------------------------------------------


class TestDockerfiles:
    def test_from_lines(self) -> None:
        content = (
            "# syntax=docker/dockerfile:1\n"
            "ARG NODE_VERSION=16\n"
            "ARG PY=3.8\n"
            "FROM --platform=$BUILDPLATFORM node:${NODE_VERSION}-alpine AS assets\n"
            "ARG LATER=9\n"
            "FROM docker.io/library/python:${PY:-3.11}-slim@sha256:abc AS app\n"
            "FROM assets AS other\n"
            "FROM golang:1.21 \\\n    AS build\n"
            "FROM eclipse-temurin:17-jre-jammy\n"
            "FROM amazoncorretto:8u392\n"
            "FROM mcr.microsoft.com/dotnet/aspnet:8.0-bookworm-slim\n"
            "FROM mcr.microsoft.com/dotnet/framework/runtime:4.8-windowsservercore-ltsc2022\n"
            "FROM node:hydrogen-alpine\n"
            "FROM ruby:latest\n"
            "FROM php:8.1-fpm\n"
            "FROM python:3\n"
            "FROM node:${LATER}\n"
        )
        found = [
            (r.product, r.version, r.approximate, r.source)
            for r in dockerfile("Dockerfile", content)
        ]
        assert found == [
            ("nodejs", "16", False, "FROM node:16-alpine"),
            ("python", "3.8", False, "FROM docker.io/library/python:3.8-slim@sha256:abc"),
            ("go", "1.21", False, "FROM golang:1.21"),
            ("eclipse-temurin", "17", False, "FROM eclipse-temurin:17-jre-jammy"),
            ("amazon-corretto", "8", False, "FROM amazoncorretto:8u392"),
            ("dotnet", "8.0", False, "FROM mcr.microsoft.com/dotnet/aspnet:8.0-bookworm-slim"),
            (
                "dotnetfx",
                "4.8",
                False,
                "FROM mcr.microsoft.com/dotnet/framework/runtime:4.8-windowsservercore-ltsc2022",
            ),
            ("nodejs", "18", False, "FROM node:hydrogen-alpine"),
            ("php", "8.1", False, "FROM php:8.1-fpm"),
            ("python", "3", False, "FROM python:3"),
        ]

    def test_in_a_project(self) -> None:
        files = {
            "requirements.txt": "flask\n",
            "Dockerfile": "FROM python:3.9-slim\nRUN pip install -r requirements.txt\n",
        }
        assert runtimes(files) == [("python", "3.9", False, "Dockerfile", "FROM python:3.9-slim")]


def test_the_eol_mini_project() -> None:
    from pathlib import Path

    from forceupdate import engine
    from forceupdate.sources.local import LocalSource

    root = Path(__file__).parent / "projects" / "eol"
    (project,) = engine.inventory(LocalSource(root)).projects
    assert project.runtime_files == [".nvmrc", ".python-version", "Dockerfile"]
    assert [(r.product, r.version, r.approximate, r.file) for r in project.runtimes] == [
        ("python", "3.8", True, "pyproject.toml"),
        ("nodejs", "16", True, "package.json"),
        ("nodejs", "16", False, ".nvmrc"),
        ("python", "3.8", False, ".python-version"),
        ("nodejs", "16", False, "Dockerfile"),
        ("python", "3.8", False, "Dockerfile"),
    ]


# ---------------------------------------------------------------------------
# La CI (E32)
# ---------------------------------------------------------------------------

WORKFLOW = """\
env:
  NODE: "20.10"
jobs:
  test:
    strategy:
      matrix:
        node: [18, 22.x]
        include:
          - node: lts/jod
    container: node:24-alpine
    steps:
      - uses: actions/setup-node@v4
        with:
          node-version: ${{ matrix.node }}
      - uses: actions/setup-node@v4
        with:
          node-version: ${{ env.NODE }}
      - uses: actions/setup-node@v4
        with:
          node-version: lts/*
"""


class TestCi:
    def test_a_github_workflow_gives_its_node(self) -> None:
        """``actions/setup-node`` (chaque valeur de la ``matrix``, ``include`` compris, ``env``
        remplacé), l'image d'un ``container`` ; ``lts/*`` ne dit rien. Il vaut pour les projets de
        tout le dépôt, comme ``.gitlab-ci.yml``."""
        files = {
            "web/package.json": '{"name": "web"}',
            ".github/workflows/ci.yml": WORKFLOW,
            ".gitlab-ci.yml": 'variables:\n  NODE_VERSION: "22"\nimage: node:$NODE_VERSION\n',
        }
        assert is_runtime_file(".github/workflows/ci.yml")
        assert not is_runtime_file("docs/workflows/ci.yml")
        workflow = ".github/workflows/ci.yml"
        setup = "actions/setup-node : node-version"
        assert runtimes(files, "web") == [
            ("nodejs", "24", False, workflow, "container: node:24-alpine"),
            ("nodejs", "18", False, workflow, f"{setup} 18"),
            ("nodejs", "22", False, workflow, f"{setup} 22.x"),
            ("nodejs", "22", False, workflow, f"{setup} lts/jod"),
            ("nodejs", "20.10", False, workflow, f"{setup} 20.10"),
            ("nodejs", "22", False, ".gitlab-ci.yml", "image: node:22"),
        ]

    def test_a_workflow_is_read_for_an_npm_project_only(self) -> None:
        """Un projet Python ne lit pas les workflows de GitHub (une requête de moins par fichier à
        la source d'une forge) ; les ``image`` de GitLab et Bitbucket valent pour tous."""
        read: list[str] = []
        files = {
            "pyproject.toml": '[project]\nname = "x"\nversion = "1"\n',
            ".github/workflows/ci.yml": "jobs:\n  t:\n    container: python:3.9\n",
            "bitbucket-pipelines.yml": "image: python:3.10\n",
        }
        found, _ = find_projects(list(files))
        (project,) = found

        def read_text(path: str) -> str | None:
            read.append(path)
            return files.get(path)

        parsers.parse_project(project, read_text)
        assert ".github/workflows/ci.yml" not in read
        assert [(r.version, r.file) for r in project.runtimes] == [
            ("3.10", "bitbucket-pipelines.yml")
        ]
