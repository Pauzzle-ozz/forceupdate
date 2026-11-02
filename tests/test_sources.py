"""La source locale : dossier (avec ou sans git), fichier seul, chemin inexistant."""

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from forceupdate.detect.manifests import DEFAULT_MAX_FILE_SIZE
from forceupdate.forges.base import ForgeKind, Repository
from forceupdate.sources import forge as forge_source
from forceupdate.sources import local as local_module
from forceupdate.sources.base import SourceError, SourceFile
from forceupdate.sources.forge import ClonedSource
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

    def test_code_file_comes_with_its_project(self, make_tree: MakeTree, no_git: None) -> None:
        # E28 : un fichier de code est analysé à travers son projet (tests/test_sources_code.py).
        root = make_tree({"app.py": "print(1)\n", "requirements.txt": ""})
        assert LocalSource(root / "app.py").files() == [
            SourceFile("app.py", 9),
            SourceFile("requirements.txt", 0),
        ]

    def test_a_lone_code_file_comes_alone(self, make_tree: MakeTree) -> None:
        root = make_tree({"app.py": "print(1)\n", "README.md": ""})
        assert LocalSource(root / "app.py", alone=True).files() == [SourceFile("app.py", 9)]

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


# -- Robustesse (E30) ----------------------------------------------------------------------

windows_only = pytest.mark.skipif(os.name != "nt", reason="les jonctions sont propres à Windows")


def junction(link: Path, target: Path) -> None:
    """Une jonction Windows, comme ``mklink /J`` (vérifié : ``os.walk`` et git la suivent)."""
    import _winapi

    _winapi.CreateJunction(str(target), str(link))


@windows_only
class TestJunctions:
    def test_a_junction_is_not_walked(self, make_tree: MakeTree, tmp_path: Path, no_git: None):
        outside = make_tree({"package.json": "{}"}, root=tmp_path / "dehors")
        root = make_tree({"requirements.txt": ""}, root=tmp_path / "racine")
        junction(root / "lien", outside)
        assert (root / "lien" / "package.json").is_file()
        assert paths(LocalSource(root)) == ["requirements.txt"]

    @requires_git
    def test_git_lists_what_a_junction_holds_and_it_is_skipped(
        self, make_tree: MakeTree, tmp_path: Path
    ) -> None:
        outside = make_tree({"package.json": "{}", "deep/Cargo.toml": ""}, root=tmp_path / "dehors")
        root = tmp_path / "depot"
        git_init(root)
        make_tree({"requirements.txt": "", "src/app.py": ""}, root=root)
        junction(root / "src" / "lien", outside)
        listed = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        assert "src/lien/package.json" in listed  # git la suit : c'est à nous de la sauter
        assert paths(LocalSource(root)) == ["requirements.txt", "src/app.py"]

    def test_a_junction_loop_ends(self, make_tree: MakeTree, tmp_path: Path, no_git: None):
        root = make_tree({"requirements.txt": ""}, root=tmp_path / "racine")
        junction(root / "boucle", root)
        assert paths(LocalSource(root)) == ["requirements.txt"]


@requires_git
class TestSubmodules:
    @staticmethod
    def parent_with_submodule(tmp_path: Path, make_tree: MakeTree) -> Path:
        library = tmp_path / "bibliotheque"
        git_init(library)
        make_tree({"package.json": '{"dependencies": {"left-pad": "1.0.0"}}'}, root=library)
        commit = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"]
        subprocess.run(["git", "add", "."], cwd=library, check=True, capture_output=True)
        subprocess.run(commit, cwd=library, check=True, capture_output=True)
        parent = tmp_path / "parent"
        git_init(parent)
        make_tree({"requirements.txt": "flask==3.0.0\n"}, root=parent)
        add = ["git", "-c", "protocol.file.allow=always", "submodule", "add", "-q"]
        subprocess.run(
            [*add, str(library), "libs/sub"], cwd=parent, check=True, capture_output=True
        )
        subprocess.run(["git", "add", "."], cwd=parent, check=True, capture_output=True)
        subprocess.run(commit, cwd=parent, check=True, capture_output=True)
        return parent

    def test_an_initialized_submodule_is_listed(self, make_tree: MakeTree, tmp_path: Path):
        parent = self.parent_with_submodule(tmp_path, make_tree)
        source = LocalSource(parent)
        assert paths(source) == [".gitmodules", "libs/sub/package.json", "requirements.txt"]
        assert source.notices == []

    def test_an_uninitialized_submodule_is_said_not_walked_forever(
        self, make_tree: MakeTree, tmp_path: Path
    ) -> None:
        parent = self.parent_with_submodule(tmp_path, make_tree)
        clone = tmp_path / "clone"
        subprocess.run(
            ["git", "clone", "-q", str(parent), str(clone)], check=True, capture_output=True
        )
        assert list((clone / "libs" / "sub").iterdir()) == []
        source = LocalSource(clone)
        # Avant E30 : git répond « ./ » dans le dossier vide, et la liste y entrait sans fin.
        assert paths(source) == [".gitmodules", "requirements.txt"]
        assert [(n.file, n.message) for n in source.notices] == [
            (
                "libs/sub",
                "sous-module git non initialisé : pas analysé (git submodule update --init).",
            )
        ]

    def test_the_submodule_of_a_cloned_repository_is_said_like_on_the_forge(
        self, make_tree: MakeTree, tmp_path: Path
    ) -> None:
        """Le clone d'un dépôt d'une forge (E31) : fait sans ses sous-modules ; la remarque est
        celle d'un dépôt lu par l'API, pas « git submodule update --init »."""
        parent = self.parent_with_submodule(tmp_path, make_tree)
        clone = tmp_path / "clone"
        subprocess.run(
            ["git", "clone", "-q", str(parent), str(clone)], check=True, capture_output=True
        )
        repo = Repository(
            forge=ForgeKind.GITHUB,
            host="github.com",
            full_name="octo/parent",
            default_branch="main",
            private=False,
            archived=False,
            fork=False,
            can_push=True,
            url="https://github.com/octo/parent",
            clone_url="https://github.com/octo/parent.git",
        )
        source = ClonedSource(repo, "0" * 40, clone)
        assert paths(source) == [".gitmodules", "requirements.txt"]
        assert [(n.file, n.message) for n in source.notices] == [
            ("libs/sub", forge_source.SUBMODULE)
        ]


class TestLimits:
    @pytest.mark.parametrize("git", [True, False])
    def test_the_listing_stops_at_max_files_and_says_so(
        self, make_tree: MakeTree, monkeypatch: pytest.MonkeyPatch, git: bool
    ) -> None:
        if git and shutil.which("git") is None:
            pytest.skip("git n'est pas installé")
        files = {f"p{n}/requirements.txt": "" for n in range(6)}
        root = make_tree(files)
        if git:
            git_init(root)
        else:
            monkeypatch.setattr(shutil, "which", lambda name: None)
        monkeypatch.setattr(local_module, "MAX_FILES", 4)
        source = LocalSource(root)
        assert len(source.files()) == 4
        assert [n.file for n in source.notices] == ["."]
        assert source.notices[0].message.startswith("plus de 4 fichiers : la liste s'arrête là")


class TestEncodings:
    def test_powershell_utf16_requirements_are_read(self, tmp_path: Path) -> None:
        # « pip freeze > requirements.txt » sous PowerShell 5.1 : UTF-16 LE avec BOM, CRLF.
        (tmp_path / "requirements.txt").write_bytes(
            "requests==2.0.0\r\nflask==1.0\r\n".encode("utf-16")
        )
        assert (
            LocalSource(tmp_path).read_text("requirements.txt") == "requests==2.0.0\nflask==1.0\n"
        )

    def test_a_utf8_bom_is_removed(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_bytes(b"\xef\xbb\xbf[project]\r\nname = 'x'\r\n")
        assert LocalSource(tmp_path).read_text("pyproject.toml") == "[project]\nname = 'x'\n"

    def test_cp1252_bytes_are_replaced_the_rest_is_read(self, tmp_path: Path) -> None:
        (tmp_path / "requirements.txt").write_bytes(
            "# dépendances\rrequests==2.0.0\n".encode("cp1252")
        )
        text = LocalSource(tmp_path).read_text("requirements.txt")
        assert text == "# d\N{REPLACEMENT CHARACTER}pendances\nrequests==2.0.0\n"
