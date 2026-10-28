"""Le moteur sur une source locale : langages, projets et dépendances."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from forceupdate import engine
from forceupdate.models import (
    Dependency,
    Ecosystem,
    Language,
    Location,
    Project,
    Scope,
    to_dict,
)
from forceupdate.sources.base import SourceError
from forceupdate.sources.local import LocalSource

MakeTree = Callable[..., Path]

MONOREPO = {
    "backend/pyproject.toml": '[project]\nname = "api"\n',
    "backend/uv.lock": "version = 1\n",
    "backend/api/main.py": "print('api')\n",
    "frontend/package.json": '{"name": "web"}\n',
    "frontend/package-lock.json": "{}\n",
    "frontend/src/main.ts": "console.log('web');\n",
    "README.md": "# Monorepo\n",
}


def test_dependencies_are_read(make_tree: MakeTree) -> None:
    root = make_tree(
        {
            "backend/pyproject.toml": '[project]\nname = "api"\ndependencies = ["flask>=3"]\n',
            "backend/uv.lock": (
                '[[package]]\nname = "flask"\nversion = "3.1.0"\n'
                'source = { registry = "https://pypi.org/simple" }\n'
            ),
        }
    )
    report = engine.inventory(LocalSource(root))
    assert report.projects[0].dependencies == [
        Dependency(
            ecosystem=Ecosystem.PYPI,
            name="flask",
            constraint=">=3",
            installed="3.1.0",
            lockfile="backend/uv.lock",
            scope=Scope.RUNTIME,
            file="backend/pyproject.toml",
            location=Location(line=3, column=22, end_column=25),
        )
    ]


def test_monorepo_gives_two_projects(make_tree: MakeTree) -> None:
    report = engine.inventory(LocalSource(make_tree(MONOREPO)))
    assert report.languages == [
        Language(name="TypeScript", bytes=20, ecosystem=Ecosystem.NPM),
        Language(name="Python", bytes=13, ecosystem=Ecosystem.PYPI),
    ]
    assert report.projects == [
        Project(
            path="backend",
            ecosystems=[Ecosystem.PYPI],
            manifests=["backend/pyproject.toml"],
            lockfiles=["backend/uv.lock"],
        ),
        Project(
            path="frontend",
            ecosystems=[Ecosystem.NPM],
            manifests=["frontend/package.json"],
            lockfiles=["frontend/package-lock.json"],
        ),
    ]
    assert report.ignored_manifests == []


def test_node_modules_and_venv_are_ignored(make_tree: MakeTree) -> None:
    root = make_tree(
        {
            **MONOREPO,
            "frontend/node_modules/left-pad/package.json": "{}",
            "frontend/node_modules/left-pad/index.js": "x" * 5000,
            "backend/.venv/lib/site-packages/flask/__init__.py": "x" * 5000,
            "backend/.venv/pyvenv.cfg": "",
        }
    )
    report = engine.inventory(LocalSource(root))
    assert [p.path for p in report.projects] == ["backend", "frontend"]
    assert [(language.name, language.bytes) for language in report.languages] == [
        ("TypeScript", 20),
        ("Python", 13),
    ]


def test_single_manifest(make_tree: MakeTree) -> None:
    root = make_tree(MONOREPO)
    report = engine.inventory(LocalSource(root / "frontend" / "package.json"))
    assert report.source == (root / "frontend" / "package.json").resolve().as_posix()
    assert report.languages == []
    assert report.projects == [
        Project(
            path=".",
            ecosystems=[Ecosystem.NPM],
            manifests=["package.json"],
            lockfiles=["package-lock.json"],
        )
    ]


def test_single_code_file(make_tree: MakeTree) -> None:
    root = make_tree(MONOREPO)
    report = engine.inventory(LocalSource(root / "backend" / "api" / "main.py"))
    assert report.languages == [Language(name="Python", bytes=13, ecosystem=Ecosystem.PYPI)]
    assert report.projects == []


def test_empty_folder(tmp_path: Path) -> None:
    report = engine.inventory(LocalSource(tmp_path))
    assert report.source == tmp_path.resolve().as_posix()
    assert (report.languages, report.projects, report.ignored_manifests) == ([], [], [])


def test_missing_path(tmp_path: Path) -> None:
    with pytest.raises(SourceError):
        engine.inventory(LocalSource(tmp_path / "absent"))


def test_test_projects_are_set_aside(make_tree: MakeTree) -> None:
    root = make_tree(
        {
            "pyproject.toml": "",
            "tests/projects/npm/package.json": "{}",
            "tests/projects/npm/package-lock.json": "{}",
        }
    )
    report = engine.inventory(LocalSource(root))
    assert [p.path for p in report.projects] == ["."]
    assert report.ignored_manifests == [
        "tests/projects/npm/package-lock.json",
        "tests/projects/npm/package.json",
    ]

    report = engine.inventory(LocalSource(root), include_tests=True)
    assert [p.path for p in report.projects] == [".", "tests/projects/npm"]


def test_report_is_plain_json(make_tree: MakeTree) -> None:
    data = to_dict(engine.inventory(LocalSource(make_tree(MONOREPO))))
    assert json.loads(json.dumps(data)) == data
    assert data["languages"][0] == {"name": "TypeScript", "bytes": 20, "ecosystem": "npm"}
    assert data["projects"][0]["ecosystems"] == ["PyPI"]
