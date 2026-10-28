"""Les mini-projets Python de ``tests/projects/`` : directes, versions installées, transitives.

Leurs lockfiles ont été produits par les vrais outils (voir ``tests/projects/README.md``).
"""

from pathlib import Path

import pytest

from forceupdate import engine
from forceupdate.models import Notice, Project, Scope
from forceupdate.parsers.python import REASON_GIT, REASON_WORKSPACE
from forceupdate.sources.local import LocalSource

PROJECTS = Path(__file__).parent / "projects"

RUNTIME, DEV, OPTIONAL, BUILD = Scope.RUNTIME, Scope.DEV, Scope.OPTIONAL, Scope.BUILD


def scan(name: str) -> dict[str, Project]:
    report = engine.inventory(LocalSource(PROJECTS / name))
    return {project.path: project for project in report.projects}


def directs(project: Project) -> list[tuple[str, str, str | None, Scope, str]]:
    return [
        (d.name, d.constraint, d.installed, d.scope, d.file)
        for d in project.dependencies
        if d.direct
    ]


def transitives(project: Project) -> dict[str, tuple[str | None, Scope]]:
    return {d.name: (d.installed, d.scope) for d in project.dependencies if not d.direct}


@pytest.mark.parametrize("name", ["pip", "pip-tools", "poetry", "uv", "pipenv", "setuptools"])
def test_every_location_points_at_its_constraint(name: str) -> None:
    source = LocalSource(PROJECTS / name)
    report = engine.inventory(source)
    located = 0
    for project in report.projects:
        for dependency in project.dependencies:
            if dependency.location is not None:
                text = source.read_text(dependency.file)
                assert text is not None
                assert dependency.location.extract(text) == dependency.constraint, dependency
                located += 1
    assert located > 0


def test_pip() -> None:
    project = scan("pip")["."]
    assert project.lockfiles == []
    assert directs(project) == [
        ("pytest", "==8.0.0", None, DEV, "requirements-dev.txt"),
        ("ruff", "", None, DEV, "requirements-dev.txt"),
        ("flask", "==2.0.1", None, RUNTIME, "requirements.txt"),
        ("requests", ">= 2.25, < 3", None, RUNTIME, "requirements.txt"),
        ("django-rest-framework", "~=3.14", None, RUNTIME, "requirements.txt"),
        ("uvicorn", ">=0.20.0", None, RUNTIME, "requirements.txt"),
        # La version vient de constraints.txt (« -c »).
        ("numpy", "", "1.26.4", RUNTIME, "requirements.txt"),
        ("mylib", "", None, RUNTIME, "requirements.txt"),
    ]
    mylib = next(d for d in project.dependencies if d.name == "mylib")
    assert mylib.unverifiable_reason == REASON_GIT
    certifi = [d for d in project.dependencies if not d.direct]
    assert [(d.name, d.constraint, d.installed, d.file) for d in certifi] == [
        ("certifi", "==2024.2.2", "2024.2.2", "constraints.txt")
    ]
    assert project.notices == []


def test_pip_tools() -> None:
    project = scan("pip-tools")["."]
    assert project.manifests == ["requirements-dev.in", "requirements.in"]
    assert project.lockfiles == ["requirements-dev.txt", "requirements.txt"]
    assert directs(project) == [
        ("pytest", ">=8", "9.1.1", DEV, "requirements-dev.in"),
        ("flask", ">=2.0", "3.1.3", RUNTIME, "requirements.in"),
        ("requests", "", "2.34.2", RUNTIME, "requirements.in"),
    ]
    assert transitives(project) == {
        "blinker": ("1.9.0", RUNTIME),
        "certifi": ("2026.10.23", RUNTIME),
        "charset-normalizer": ("3.5.2", RUNTIME),
        "click": ("8.5.0", RUNTIME),
        "idna": ("3.20", RUNTIME),
        "itsdangerous": ("2.2.0", RUNTIME),
        "jinja2": ("3.1.6", RUNTIME),
        "markupsafe": ("3.0.4", RUNTIME),
        "urllib3": ("2.8.0", RUNTIME),
        "werkzeug": ("3.1.9", RUNTIME),
        "colorama": ("0.4.6", DEV),
        "iniconfig": ("2.3.1", DEV),
        "packaging": ("26.3", DEV),
        "pluggy": ("1.7.0", DEV),
        "pygments": ("2.21.0", DEV),
    }
    # Le .txt compilé garde l'emplacement de ses « == » : il est réécrivable.
    werkzeug = next(d for d in project.dependencies if d.name == "werkzeug")
    assert (werkzeug.file, werkzeug.constraint) == ("requirements.txt", "==3.1.9")
    assert werkzeug.location is not None


def test_poetry_1_8_lock_without_category() -> None:
    project = scan("poetry")["."]
    assert directs(project) == [
        ("requests", "^2.31", "2.34.2", RUNTIME, "pyproject.toml"),
        ("click", "^8.1", "8.5.0", OPTIONAL, "pyproject.toml"),
        ("pyyaml", "6.0.2", "6.0.2", RUNTIME, "pyproject.toml"),
        ("pytest", "^8.0", "8.4.2", DEV, "pyproject.toml"),
        ("poetry-core", "", None, BUILD, "pyproject.toml"),
    ]
    # Ni « category » ni « groups » dans ce poetry.lock : le scope vient du graphe.
    assert transitives(project) == {
        "certifi": ("2026.10.23", RUNTIME),
        "charset-normalizer": ("3.5.2", RUNTIME),
        "idna": ("3.20", RUNTIME),
        "urllib3": ("2.8.0", RUNTIME),
        "colorama": ("0.4.6", DEV),
        "iniconfig": ("2.3.1", DEV),
        "packaging": ("26.3", DEV),
        "pluggy": ("1.7.0", DEV),
        "pygments": ("2.21.0", DEV),
    }


def test_uv_workspace() -> None:
    projects = scan("uv")
    assert list(projects) == [".", "packages/legacy", "packages/lib", "tools/script"]

    root = projects["."]
    assert directs(root) == [
        ("httpx", ">=0.27", "0.28.1", RUNTIME, "pyproject.toml"),
        ("demo-lib", "", "0.1.0", RUNTIME, "pyproject.toml"),
        ("rich", ">=13", "15.0.0", OPTIONAL, "pyproject.toml"),
        ("pytest", ">=8", "9.1.1", DEV, "pyproject.toml"),
        ("hatchling", "", None, BUILD, "pyproject.toml"),
    ]
    demo_lib = next(d for d in root.dependencies if d.name == "demo-lib")
    assert demo_lib.unverifiable_reason == REASON_WORKSPACE
    assert transitives(root) == {
        "anyio": ("4.15.1", RUNTIME),
        "certifi": ("2026.10.23", RUNTIME),
        "h11": ("0.16.0", RUNTIME),
        "httpcore": ("1.0.9", RUNTIME),
        "idna": ("3.20", RUNTIME),
        "packaging": ("26.3", RUNTIME),  # tiré par le membre demo-lib
        "typing-extensions": ("4.16.0", RUNTIME),
        "markdown-it-py": ("4.2.0", OPTIONAL),
        "mdurl": ("0.1.2", OPTIONAL),
        "pygments": ("2.21.0", OPTIONAL),  # rich (optional) passe avant pytest (dev)
        "colorama": ("0.4.6", DEV),
        "iniconfig": ("2.3.1", DEV),
        "pluggy": ("1.7.0", DEV),
    }

    member = projects["packages/lib"]
    assert member.lockfiles == ["uv.lock"]
    assert directs(member) == [
        ("packaging", ">=24", "26.3", RUNTIME, "packages/lib/pyproject.toml"),
        ("hatchling", "", None, BUILD, "packages/lib/pyproject.toml"),
    ]
    assert transitives(member) == {}

    # Exclu (« exclude ») ou hors des « members » : le uv.lock n'est pas à eux.
    for path, name, constraint in [
        ("packages/legacy", "requests", "<2"),
        ("tools/script", "typer", ""),
    ]:
        assert projects[path].lockfiles == []
        assert directs(projects[path]) == [
            (name, constraint, None, RUNTIME, f"{path}/pyproject.toml")
        ]


def test_pipenv() -> None:
    project = scan("pipenv")["."]
    assert directs(project) == [
        ("requests", "*", "2.34.2", RUNTIME, "Pipfile"),
        ("flask", ">=2.0", "3.1.3", RUNTIME, "Pipfile"),
        ("pytest", "==8.3.3", "8.3.3", DEV, "Pipfile"),
    ]
    found = transitives(project)
    assert len(found) == 15
    assert found["python-dotenv"] == ("1.2.4", RUNTIME)  # flask[dotenv]
    assert found["pluggy"] == ("1.7.0", DEV)


def test_setuptools() -> None:
    project = scan("setuptools")["."]
    assert directs(project) == [
        ("setuptools", ">=64", None, BUILD, "pyproject.toml"),
        ("setuptools-scm", ">=8", None, BUILD, "pyproject.toml"),
        ("requests", ">=2.25", None, RUNTIME, "setup.cfg"),
        ("click", "", None, RUNTIME, "setup.cfg"),
        ("setuptools-scm", "", None, BUILD, "setup.cfg"),
        ("pytest", ">=8", None, DEV, "setup.cfg"),
        ("pyyaml", ">=6", None, OPTIONAL, "setup.cfg"),
    ]
    assert project.notices == [
        Notice(
            file="setup.py",
            message="pas lu : il faudrait l'exécuter pour connaître ses dépendances.",
        )
    ]


def test_no_duplicate_declaration_in_a_file() -> None:
    for name in ("pip", "pip-tools", "poetry", "uv", "pipenv", "setuptools"):
        for project in scan(name).values():
            keys = [(d.file, d.location, d.name, d.installed) for d in project.dependencies]
            assert len(keys) == len(set(keys)), name


@pytest.mark.parametrize(
    ("name", "pinned_by"),
    [
        ("pip", {"numpy": "constraints.txt", "certifi": "constraints.txt"}),
        ("pip-tools", {}),
        ("poetry", {}),
        ("uv", {}),
        ("pipenv", {}),
    ],
)
def test_every_installed_version_names_its_lockfile(name: str, pinned_by: dict[str, str]) -> None:
    """La version installée d'une dépendance vient d'un lockfile du projet : celui qu'une mise
    à jour régénère (E11). Une indirecte vient de son lockfile. Un fichier de contraintes
    (``-c constraints.txt``) n'est pas un lockfile, mais c'est lui qui fige la version."""
    named = 0
    for project in scan(name).values():
        for dependency in project.dependencies:
            if dependency.installed is None:
                assert dependency.lockfile is None, dependency
                continue
            expected = pinned_by.get(dependency.name)
            if expected is not None:
                assert dependency.lockfile == expected
            else:
                assert dependency.lockfile in project.lockfiles, dependency
            if not dependency.direct:
                assert dependency.lockfile == dependency.file
            named += 1
    assert named > 0


def test_without_lockfile_no_version_and_no_lockfile() -> None:
    for dependency in scan("setuptools")["."].dependencies:
        assert (dependency.installed, dependency.lockfile) == (None, None)
