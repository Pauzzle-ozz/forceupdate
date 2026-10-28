"""Le garde-fou de ``forceupdate update`` : les fichiers que git n'a pas en commit
(``update.git``)."""

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from forceupdate.update.git import uncommitted

MakeTree = Callable[..., Path]

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git absent")


def git(root: Path, *args: str) -> None:
    command = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]
    command += ["-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args]
    subprocess.run(command, cwd=root, check=True, capture_output=True, timeout=60)


@pytest.fixture
def repo(make_tree: MakeTree) -> Path:
    """Un dépôt avec un commit : un projet dans ``app/`` (dont un dossier ``[x]``), et un
    README."""
    root = make_tree(
        {
            "README.md": "x\n",
            "app/package.json": "{}\n",
            "app/requirements.txt": "flask\n",
            "app/[x]/package.json": "{}\n",
        }
    )
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "départ")
    return root


FILES = ["app/package.json", "app/requirements.txt", "app/[x]/package.json"]


@needs_git
def test_a_clean_repository(repo: Path) -> None:
    assert uncommitted(repo, FILES) == []


@needs_git
def test_modified_staged_and_untracked_files(repo: Path, make_tree: MakeTree) -> None:
    make_tree({"app/package.json": '{"a": 1}\n', "app/requirements.txt": "flask==3.1\n"}, repo)
    git(repo, "add", "app/requirements.txt")  # dans l'index, sans commit
    make_tree({"app/[x]/package.json": "[]\n", "README.md": "y\n", "new/package.json": "{}"}, repo)
    assert uncommitted(repo, [*FILES, "new/package.json"]) == [*FILES, "new/package.json"]
    # Seuls les fichiers demandés comptent : le README modifié n'y est pas.
    assert uncommitted(repo, ["app/package.json"]) == ["app/package.json"]


@needs_git
def test_a_renamed_file(repo: Path) -> None:
    git(repo, "mv", "app/requirements.txt", "app/requirements.in")
    assert uncommitted(repo, ["app/requirements.in", "app/package.json"]) == ["app/requirements.in"]


@needs_git
def test_paths_are_relative_to_the_analysed_folder(repo: Path, make_tree: MakeTree) -> None:
    """La source est un sous-dossier du dépôt : git, lui, parle depuis la racine du dépôt."""
    make_tree({"app/package.json": '{"a": 1}\n'}, repo)
    assert uncommitted(repo / "app", ["package.json", "requirements.txt"]) == ["package.json"]


def test_outside_a_repository(tmp_path: Path) -> None:
    assert uncommitted(tmp_path, ["package.json"]) is None


def test_without_git(tmp_path: Path, no_git: None) -> None:
    assert uncommitted(tmp_path, ["package.json"]) is None
