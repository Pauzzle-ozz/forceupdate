"""Un fichier de code choisi seul (E28) : la source remonte les dossiers jusqu'au premier
manifeste de son écosystème, en s'arrêtant à la racine git, à celle du disque, ou avant le
dossier personnel."""

from collections.abc import Callable
from pathlib import Path

import pytest

from forceupdate.sources import local
from forceupdate.sources.base import ChosenCode
from forceupdate.sources.local import LocalSource

MakeTree = Callable[..., Path]


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Le dossier personnel : celui au-dessus du dossier du test, pour que la remontée s'arrête
    là, quoi qu'il y ait plus haut sur la machine."""
    above = tmp_path.parent.resolve()
    monkeypatch.setattr(local, "_home", lambda: above)
    return above


def chosen(source: LocalSource) -> ChosenCode | None:
    return source.code_file


def test_project_of_the_same_ecosystem(make_tree: MakeTree, no_git: None) -> None:
    root = make_tree(
        {
            "backend/pyproject.toml": "[project]\n",
            "backend/api/main.py": "import flask\n",
        }
    )
    source = LocalSource(root / "backend" / "api" / "main.py")
    assert source.root == (root / "backend").resolve()
    assert chosen(source) == ChosenCode(path="api/main.py", project=".")
    assert source.file == "api/main.py"


def test_a_manifest_of_another_ecosystem_is_passed(make_tree: MakeTree, no_git: None) -> None:
    root = make_tree(
        {
            "pyproject.toml": "[project]\n",
            "tools/package.json": "{}\n",
            "tools/build.py": "import os\n",
            "tools/notes.md": "# notes\n",
        }
    )
    assert chosen(LocalSource(root / "tools" / "build.py")) == ChosenCode("tools/build.py", ".")
    # Un fichier d'un autre langage : le premier manifeste, quel qu'il soit.
    assert chosen(LocalSource(root / "tools" / "notes.md")) == ChosenCode("notes.md", ".")


def test_the_git_root_is_the_source(make_tree: MakeTree, no_git: None) -> None:
    root = make_tree(
        {
            ".git/HEAD": "ref: refs/heads/main\n",
            "uv.lock": "version = 1\n",
            "pyproject.toml": "[tool.uv.workspace]\nmembers = ['backend']\n",
            "backend/pyproject.toml": "[project]\n",
            "backend/api/main.py": "import flask\n",
        }
    )
    source = LocalSource(root / "backend" / "api" / "main.py")
    assert source.root == root.resolve()
    assert chosen(source) == ChosenCode(path="backend/api/main.py", project="backend")
    assert {f.path for f in source.files()} >= {"uv.lock", "backend/pyproject.toml"}


def test_the_walk_stops_at_the_git_root(make_tree: MakeTree, no_git: None) -> None:
    root = make_tree(
        {
            "pyproject.toml": "[project]\n",
            "repo/.git/HEAD": "ref: refs/heads/main\n",
            "repo/src/run.py": "import requests\n",
        }
    )
    source = LocalSource(root / "repo" / "src" / "run.py")
    assert chosen(source) == ChosenCode(path="run.py", project=None)
    assert source.root == (root / "repo" / "src").resolve()


def test_the_walk_stops_before_the_home_folder(
    make_tree: MakeTree, no_git: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_tree({"package.json": "{}\n", "Downloads/index.js": "require('x')\n"})
    monkeypatch.setattr(local, "_home", lambda: root.resolve())
    assert chosen(LocalSource(root / "Downloads" / "index.js")) == ChosenCode("index.js", None)


def test_a_requirements_folder_is_a_manifest(make_tree: MakeTree, no_git: None) -> None:
    root = make_tree({"proj/requirements/base.txt": "flask\n", "proj/app.py": "import flask\n"})
    assert chosen(LocalSource(root / "proj" / "app.py")) == ChosenCode("app.py", ".")


def test_a_lockfile_alone_is_not_a_project(make_tree: MakeTree, no_git: None) -> None:
    root = make_tree({"proj/uv.lock": "version = 1\n", "proj/app.py": "import flask\n"})
    assert chosen(LocalSource(root / "proj" / "app.py")) == ChosenCode("app.py", None)


def test_a_project_in_node_modules_is_its_own_root(make_tree: MakeTree, no_git: None) -> None:
    root = make_tree(
        {
            ".git/HEAD": "ref: refs/heads/main\n",
            "package.json": "{}\n",
            "node_modules/left-pad/package.json": '{"name": "left-pad"}\n',
            "node_modules/left-pad/lib/index.js": "module.exports = 1\n",
        }
    )
    source = LocalSource(root / "node_modules" / "left-pad" / "lib" / "index.js")
    assert source.root == (root / "node_modules" / "left-pad").resolve()
    assert chosen(source) == ChosenCode("lib/index.js", ".")


def test_alone_has_no_project(make_tree: MakeTree, no_git: None) -> None:
    root = make_tree({"pyproject.toml": "[project]\n", "run.py": "import flask\n"})
    source = LocalSource(root / "run.py", alone=True)
    assert chosen(source) == ChosenCode("run.py", None)


def test_files_of_a_lone_script(make_tree: MakeTree, no_git: None) -> None:
    root = make_tree(
        {"run.py": "# /// script\n# ///\n", "run.py.lock": "version = 1\n", "other.py": "x = 1\n"}
    )
    source = LocalSource(root / "run.py")
    assert [f.path for f in source.files()] == ["run.py", "run.py.lock"]


def test_a_manifest_is_not_a_code_file(make_tree: MakeTree, no_git: None) -> None:
    root = make_tree({"setup.py": "from setuptools import setup\n", "README.md": "# x\n"})
    source = LocalSource(root / "setup.py")
    assert source.code_file is None
    assert source.file == "setup.py"


def test_a_folder_is_not_a_code_file(tmp_path: Path) -> None:
    assert LocalSource(tmp_path).code_file is None
