"""git pour les forges (``forges.git``) : le token passé par un credential helper éphémère,
jamais dans les arguments ni dans un message ; le clone superficiel, le commit au nom du
compte, le push qui ne remplace la branche que si elle n'a pas bougé (``--force-with-lease``) ;
le dossier de travail effacé. Avec le vrai git, sur des dépôts « bare » du dossier du test."""

import os
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fake_forge import FakeRepo, git, make_remote, push_commit, remotes_url

from forceupdate.forges import git as forge_git
from forceupdate.forges.git import Author, Credentials, GitError, GitFailure, Workspace

TOKEN = "gho_secret_du_test"
AUTHOR = Author(name="Octo Cat", email="1+octo@users.noreply.github.com")

pytestmark = pytest.mark.skipif(not forge_git.available(), reason="git n'est pas installé")


@pytest.fixture
def remote(tmp_path: Path) -> tuple[FakeRepo, str]:
    """Un dépôt « bare » (``octo/app``, branche ``main``) et son adresse ``file://``."""
    repo = FakeRepo(
        full_name="octo/app",
        files={"requirements.txt": b"flask==0.12\r\n", "app.py": b"print(1)\n"},
    )
    make_remote(repo, tmp_path / "distants")
    return repo, f"{remotes_url(tmp_path / 'distants')}/octo/app.git"


class Spy:
    """Note chaque commande git lancée, et son environnement."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[tuple[list[str], dict[str, str]]] = []
        self._spawn = forge_git._spawn
        monkeypatch.setattr(forge_git, "_spawn", self.spawn)

    def spawn(self, command: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
        self.calls.append((list(command), dict(options["env"])))
        return self._spawn(command, **options)


def test_the_token_reaches_git_by_the_helper_never_by_the_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = Spy(monkeypatch)
    said = forge_git._git(
        ["credential", "fill"],
        credentials=Credentials("x-access-token", TOKEN),
        stdin=b"protocol=https\nhost=github.com\npath=octo/app.git\n\n",
        action="tester",
    )
    # Le helper a répondu : git rend ce qu'il a reçu, le token masqué dans ce qui remonte.
    assert "username=x-access-token" in said
    assert "password=***" in said
    assert TOKEN not in said
    command, env = spy.calls[0]
    assert all(TOKEN not in argument for argument in command)
    assert env[forge_git.PASSWORD_VARIABLE] == TOKEN
    # Les helpers configurés (le gestionnaire de Windows) sont écartés : il ne garde rien.
    assert command[command.index("credential.helper=") - 1] == "-c"
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_without_credentials_no_helper_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(GitError) as raised:
        forge_git._git(
            ["credential", "fill"],
            credentials=None,
            stdin=b"protocol=https\nhost=github.com\n\n",
            action="tester",
        )
    assert raised.value.failure is GitFailure.AUTH


def test_the_inherited_environment_cannot_redirect_git(
    monkeypatch: pytest.MonkeyPatch, remote: tuple[FakeRepo, str], tmp_path: Path
) -> None:
    spy = Spy(monkeypatch)
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "ailleurs"))
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Quelqu'un d'autre")
    monkeypatch.setenv(forge_git.PASSWORD_VARIABLE, "vieux-token")
    _, url = remote
    forge_git.clone(url, tmp_path / "clone", branch="main", credentials=None)
    _, env = spy.calls[0]
    assert "GIT_DIR" not in env
    assert "GIT_AUTHOR_NAME" not in env
    assert forge_git.PASSWORD_VARIABLE not in env


def test_a_shallow_clone_of_the_default_branch(
    remote: tuple[FakeRepo, str], tmp_path: Path
) -> None:
    repo, url = remote
    checkout = tmp_path / "clone"
    commit = forge_git.clone(
        url, checkout, branch="main", credentials=Credentials("x-access-token", TOKEN)
    )
    assert commit == repo.commit
    # Le contenu tel qu'il est dans le dépôt : pas de conversion des fins de ligne.
    assert (checkout / "requirements.txt").read_bytes() == b"flask==0.12\r\n"
    assert git(checkout, "rev-list", "--count", "HEAD").strip() == "1"
    assert (checkout / ".git" / "shallow").is_file()
    # Ni le token ni d'identifiants dans la configuration du clone.
    assert TOKEN not in (checkout / ".git" / "config").read_text(encoding="utf-8")


def test_a_clone_refuses_an_address_with_credentials(tmp_path: Path) -> None:
    with pytest.raises(GitError, match="identifiants"):
        forge_git.clone(
            "https://octo:secret@github.com/octo/app.git",
            tmp_path / "clone",
            branch="main",
            credentials=None,
        )


def test_a_missing_repository_is_said(tmp_path: Path) -> None:
    url = f"{(tmp_path / 'rien.git').as_uri()}"
    with pytest.raises(GitError) as raised:
        forge_git.clone(url, tmp_path / "clone", branch="main", credentials=None)
    assert raised.value.failure is GitFailure.NOT_FOUND
    assert "git n'a pas pu cloner" in str(raised.value)


def test_a_missing_git_is_said(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(forge_git, "_which", lambda program: None)
    assert not forge_git.available()
    with pytest.raises(GitError) as raised:
        forge_git.clone("file:///x.git", tmp_path / "clone", branch="main", credentials=None)
    assert raised.value.failure is GitFailure.MISSING


def test_commit_in_the_name_of_the_account(remote: tuple[FakeRepo, str], tmp_path: Path) -> None:
    _, url = remote
    checkout = tmp_path / "clone"
    base = forge_git.clone(url, checkout, branch="main", credentials=None)
    (checkout / "requirements.txt").write_bytes(b"flask==0.12.5\r\n")
    (checkout / "app.py").write_text("print(2)\n", encoding="utf-8")
    message = "Mise à jour des dépendances\n\n- flask 0.12 → 0.12.5\n"
    commit = forge_git.commit(checkout, ["requirements.txt"], message, author=AUTHOR)
    assert commit is not None and commit != base
    assert git(checkout, "log", "-1", "--format=%an <%ae>|%cn <%ce>").strip() == (
        "Octo Cat <1+octo@users.noreply.github.com>|Octo Cat <1+octo@users.noreply.github.com>"
    )
    assert git(checkout, "log", "-1", "--format=%B") == f"{message}\n"
    # Seul le fichier demandé est dans le commit.
    assert git(checkout, "show", "--name-only", "--format=", "HEAD").split() == ["requirements.txt"]
    assert forge_git.tree(checkout) == git(checkout, "rev-parse", "HEAD^{tree}").strip()


def test_nothing_changed_nothing_committed(remote: tuple[FakeRepo, str], tmp_path: Path) -> None:
    _, url = remote
    checkout = tmp_path / "clone"
    base = forge_git.clone(url, checkout, branch="main", credentials=None)
    assert forge_git.commit(checkout, ["requirements.txt"], "rien", author=AUTHOR) is None
    assert forge_git.commit(checkout, [], "rien", author=AUTHOR) is None
    assert forge_git.head(checkout) == base


def _changed_clone(url: str, directory: Path, content: bytes) -> Path:
    forge_git.clone(url, directory, branch="main", credentials=None)
    (directory / "requirements.txt").write_bytes(content)
    forge_git.commit(directory, ["requirements.txt"], "Mise à jour", author=AUTHOR)
    return directory


def test_push_creates_then_replaces_the_branch_only_if_it_did_not_move(
    remote: tuple[FakeRepo, str], tmp_path: Path
) -> None:
    repo, url = remote
    assert repo.remote is not None
    branch = "forceupdate/dependencies"
    first = _changed_clone(url, tmp_path / "un", b"flask==0.12.4\r\n")
    forge_git.push(first, url, branch, credentials=None, expected=None)
    pushed = git(repo.remote, "rev-parse", f"refs/heads/{branch}").strip()
    assert pushed == forge_git.head(first)

    # Elle existe : la créer de nouveau est refusé, rien n'est remplacé.
    second = _changed_clone(url, tmp_path / "deux", b"flask==0.12.5\r\n")
    with pytest.raises(GitError) as raised:
        forge_git.push(second, url, branch, credentials=None, expected=None)
    assert raised.value.failure is GitFailure.STALE
    # Elle pointe toujours là où on l'a vue : elle est remplacée, depuis un clone superficiel
    # qui n'a pas ce commit.
    forge_git.push(second, url, branch, credentials=None, expected=pushed)
    replaced = git(repo.remote, "rev-parse", f"refs/heads/{branch}").strip()
    assert replaced == forge_git.head(second)

    # Quelqu'un l'a changée depuis qu'on l'a vue : rien n'est poussé.
    push_commit(repo, branch, {"app.py": "print(3)\n"}, "Correction à la main")
    third = _changed_clone(url, tmp_path / "trois", b"flask==0.12.6\r\n")
    with pytest.raises(GitError) as raised:
        forge_git.push(third, url, branch, credentials=None, expected=replaced)
    assert raised.value.failure is GitFailure.STALE
    # La branche par défaut n'a jamais bougé.
    assert git(repo.remote, "rev-parse", "refs/heads/main").strip() == repo.commit


@pytest.mark.parametrize(
    ("said", "failure"),
    [
        ("fatal: Authentication failed for 'https://github.com/octo/app.git/'", GitFailure.AUTH),
        (
            "fatal: could not read Username for 'https://github.com': terminal prompts disabled",
            GitFailure.AUTH,
        ),
        (
            "remote: Permission to octo/app.git denied to octo.\nfatal: unable to access "
            "'https://github.com/octo/app.git/': The requested URL returned error: 403",
            GitFailure.DENIED,
        ),
        (
            "remote: error: GH006: Protected branch update failed for refs/heads/main.",
            GitFailure.PROTECTED,
        ),
        (" ! [rejected]        HEAD -> forceupdate/dependencies (stale info)", GitFailure.STALE),
        (
            "remote: Repository not found.\nfatal: repository 'https://github.com/x/y.git/' not "
            "found",
            GitFailure.NOT_FOUND,
        ),
        ("fatal: Remote branch main not found in upstream origin", GitFailure.NOT_FOUND),
        (
            "fatal: unable to access 'https://github.com/': Could not resolve host: github.com",
            GitFailure.NETWORK,
        ),
        ("fatal: quelque chose d'autre", GitFailure.OTHER),
    ],
)
def test_what_git_said_is_understood(said: str, failure: GitFailure) -> None:
    assert forge_git._diagnose(said) is failure


def test_secrets_are_masked() -> None:
    text = "fatal: https://x-access-token:gho_abc@github.com/octo/app.git et gho_abc encore"
    masked = forge_git.redact(text, ["gho_abc"])
    assert "gho_abc" not in masked
    assert "https://x-access-token:***@github.com" in masked
    assert forge_git.redact("https://octo:pass@example.com/x") == "https://octo:***@example.com/x"


def test_the_workspace_is_removed_even_with_read_only_files() -> None:
    with Workspace() as workspace:
        path = workspace.path
        locked = path / "objets" / "pack"
        locked.parent.mkdir()
        locked.write_text("x", encoding="utf-8")
        os.chmod(locked, stat.S_IREAD)
        assert path.is_dir()
    assert not path.exists()
    assert workspace.cleaned
    workspace.cleanup()  # une deuxième fois : rien


def test_the_workspace_is_removed_after_an_error() -> None:
    with pytest.raises(RuntimeError), Workspace() as workspace:
        (workspace.path / "fichier").write_text("x", encoding="utf-8")
        raise RuntimeError("échec")
    assert not workspace.path.exists()


def test_git_never_reaches_github_in_the_tests(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match=r"git vers https://github.com"):
        forge_git.clone(
            "https://github.com/octo/app.git", tmp_path / "clone", branch="main", credentials=None
        )
