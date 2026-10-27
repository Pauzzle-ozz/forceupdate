"""La source locale : dossier (avec ou sans git), fichier seul, chemin inexistant."""

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from forceupdate.detect.manifests import DEFAULT_MAX_FILE_SIZE
from forceupdate.sources.base import SourceError, SourceFile
from forceupdate.sources.local import LocalSource

MakeTree = Callable[..., Path]

requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git n'est pas installé")


def git_init(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, capture_output=True)


def paths(source: LocalSource) -> list[str]:
    return [file.path for file in source.files()]


def test_missing_path_raises_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(SourceError, match="n'existe pas"):
        LocalSource(tmp_path / "absent")


@pytest.mark.usefixtures("no_git")
class TestFolderWithoutGit:
    def test_lists_files_with_sizes_sorted(self, make_tree: MakeTree) -> None:
        root = make_tree({"src/app.py": "print(1)\n", "README.md": "# x\n"})
        source = LocalSource(root)
        assert source.files() == [SourceFile("README.md", 4), SourceFile("src/app.py", 9)]
        assert source.origin == root.resolve().as_posix()

    def test_skips_ignored_folders(self, make_tree: MakeTree) -> None:
        root = make_tree(
            {
                "app.py": "",
                "node_modules/left-pad/package.json": "{}",
                ".venv/lib/site.py": "",
                "pkg/__pycache__/app.cpython-312.pyc": "",
                "src/forceupdate.egg-info/PKG-INFO": "",
                ".git/config": "",
            }
        )
        assert paths(LocalSource(root)) == ["app.py"]

    def test_empty_folder(self, tmp_path: Path) -> None:
        assert LocalSource(tmp_path).files() == []

    def test_skips_symlinks(self, make_tree: MakeTree, tmp_path: Path) -> None:
        root = make_tree({"real/app.py": "x"}, root=tmp_path / "root")
        try:
            os.symlink(root / "real" / "app.py", root / "link.py")
            os.symlink(root / "real", root / "linkdir", target_is_directory=True)
        except OSError:
            pytest.skip("pas le droit de créer des liens symboliques ici")
        assert paths(LocalSource(root)) == ["real/app.py"]


@requires_git
class TestFolderWithGit:
    def test_respects_gitignore(self, make_tree: MakeTree, tmp_path: Path) -> None:
        git_init(tmp_path)
        make_tree({".gitignore": "data/\n*.log\n", "app.py": "", "data/package.json": "{}"})
        make_tree({"debug.log": "", "vendor/lib/package.json": "{}"})
        assert paths(LocalSource(tmp_path)) == [".gitignore", "app.py"]

    def test_a_subfolder_lists_its_own_files(self, make_tree: MakeTree, tmp_path: Path) -> None:
        git_init(tmp_path)
        make_tree({"app.py": "", "web/package.json": "{}", "web/src/index.ts": ""})
        assert paths(LocalSource(tmp_path / "web")) == ["package.json", "src/index.ts"]

    def test_an_ignored_folder_chosen_on_purpose_is_walked(
        self, make_tree: MakeTree, tmp_path: Path
    ) -> None:
        git_init(tmp_path)
        make_tree({".gitignore": "data/\n", "data/package.json": "{}"})
        assert paths(LocalSource(tmp_path / "data")) == ["package.json"]

    def test_nested_repo_in_a_plain_folder_keeps_its_gitignore(
        self, make_tree: MakeTree, tmp_path: Path
    ) -> None:
        git_init(tmp_path / "inner")
        make_tree(
            {
                "other/requirements.txt": "",
                "inner/.gitignore": "out/\n",
                "inner/package.json": "{}",
                "inner/out/package.json": "{}",
            }
        )
        assert paths(LocalSource(tmp_path)) == [
            "inner/.gitignore",
            "inner/package.json",
            "other/requirements.txt",
        ]

    def test_nested_repo_in_a_repo_is_listed(self, make_tree: MakeTree, tmp_path: Path) -> None:
        git_init(tmp_path)
        git_init(tmp_path / "clone")
        make_tree({"app.py": "", "clone/Cargo.toml": ""})
        assert paths(LocalSource(tmp_path)) == ["app.py", "clone/Cargo.toml"]


class TestSingleFile:
    def test_manifest_comes_with_its_lockfiles(self, make_tree: MakeTree) -> None:
        root = make_tree(
            {
                "package.json": "{}",
                "package-lock.json": "{}",
                "yarn.lock": "",
                "index.js": "",
                "sub/package-lock.json": "{}",
            }
        )
        source = LocalSource(root / "package.json")
        assert paths(source) == ["package-lock.json", "package.json", "yarn.lock"]
        assert source.root == root.resolve()
        assert source.origin == (root / "package.json").resolve().as_posix()

    def test_code_file_comes_alone(self, make_tree: MakeTree) -> None:
        root = make_tree({"app.py": "print(1)\n", "requirements.txt": ""})
        assert LocalSource(root / "app.py").files() == [SourceFile("app.py", 9)]

    def test_lockfile_comes_alone(self, make_tree: MakeTree) -> None:
        root = make_tree({"uv.lock": "", "pyproject.toml": ""})
        assert paths(LocalSource(root / "uv.lock")) == ["uv.lock"]

    def test_requirements_folder_keeps_its_folder(self, make_tree: MakeTree) -> None:
        root = make_tree({"requirements/dev.txt": "pytest\n"})
        source = LocalSource(root / "requirements" / "dev.txt")
        assert source.root == root.resolve()
        assert paths(source) == ["requirements/dev.txt"]


class TestReadText:
    def test_reads_a_file_of_the_source(self, make_tree: MakeTree) -> None:
        root = make_tree({"backend/requirements.txt": "flask==3.0.0\n"})
        assert LocalSource(root).read_text("backend/requirements.txt") == "flask==3.0.0\n"

    def test_unreadable_gives_none(self, tmp_path: Path) -> None:
        assert LocalSource(tmp_path).read_text("absent.txt") is None

    @pytest.mark.parametrize("path", ["../outside.txt", "a/../../outside.txt"])
    def test_refuses_paths_outside_the_source(self, tmp_path: Path, path: str) -> None:
        (tmp_path / "outside.txt").write_text("secret", encoding="utf-8")
        root = tmp_path / "root"
        root.mkdir()
        with pytest.raises(ValueError, match="hors de la source"):
            LocalSource(root).read_text(path)

    def test_refuses_absolute_paths(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="hors de la source"):
            LocalSource(tmp_path).read_text((tmp_path.parent / "x").as_posix())

    def test_lockfiles_get_a_higher_size_limit(self, make_tree: MakeTree) -> None:
        big = "x" * (DEFAULT_MAX_FILE_SIZE + 1)
        root = make_tree({"uv.lock": big, "pyproject.toml": big})
        source = LocalSource(root)
        assert source.read_text("uv.lock") == big
        assert source.read_text("pyproject.toml") is None
