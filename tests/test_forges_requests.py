"""La mise à jour d'un dépôt GitHub (E18) : le clone par git, la branche de forceupdate et ses
commits, le push (jamais sur la branche par défaut), la PR ouverte ou mise à jour sans jamais
en ouvrir une deuxième (``forges.github``). GitHub est simulé (``fake_forge``), git clone et
pousse vers des dépôts « bare » du dossier du test."""

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

import pytest
import respx
from fake_forge import (
    FakeGitHubRepos,
    FakePull,
    FakeRepo,
    git,
    make_remote,
    push_commit,
    remotes_url,
)

from forceupdate.forges import git as forge_git
from forceupdate.forges.base import (
    AccessDenied,
    ChangeRequest,
    EmptyRepository,
    ForgeError,
    Repository,
    TokenRefused,
)
from forceupdate.forges.github import GitHub
from forceupdate.net import HttpClient

T = TypeVar("T")
TOKEN = "gho_requetes"
BRANCH = "forceupdate/dependencies"

pytestmark = pytest.mark.skipif(not forge_git.available(), reason="git n'est pas installé")


async def _no_sleep(_: float) -> None:
    pass


@pytest.fixture
def remotes(tmp_path: Path) -> Path:
    return tmp_path / "distants"


@pytest.fixture
def github(remotes: Path) -> Iterator[FakeGitHubRepos]:
    app = FakeRepo(full_name="octo/app", files={"requirements.txt": b"flask==0.12\n"})
    make_remote(app, remotes)
    lecture = FakeRepo(full_name="atelier/lecture", push=False, files={"a.txt": b"a\n"})
    make_remote(lecture, remotes)
    fake = FakeGitHubRepos(
        [app, lecture, FakeRepo(full_name="octo/neuf", empty=True)],
        tokens={TOKEN},
        user={"login": "octo", "id": 583231, "name": "Octo Cat"},
    )
    with respx.mock(assert_all_called=False) as router:
        fake.routes(router)
        yield fake


def run(work: Callable[[GitHub], Awaitable[T]], remotes: Path, token: str | None = TOKEN) -> T:
    async def main() -> T:
        async with HttpClient(sleep=_no_sleep) as http:
            return await work(GitHub(http, token, git_url=remotes_url(remotes)))

    return asyncio.run(main())


def repository(remotes: Path, name: str = "octo/app") -> Repository:
    return run(lambda forge: forge.repository(name), remotes)


def test_whoami_gives_the_noreply_address_of_the_account(
    github: FakeGitHubRepos, remotes: Path
) -> None:
    identity = run(lambda forge: forge.whoami(), remotes)
    assert identity.email == "583231+octo@users.noreply.github.com"


def test_clone_the_default_branch(github: FakeGitHubRepos, remotes: Path, tmp_path: Path) -> None:
    repo = repository(remotes)
    checkout = tmp_path / "clone"
    run(lambda forge: forge.clone(repo, checkout), remotes)
    assert (checkout / "requirements.txt").read_bytes() == b"flask==0.12\n"
    assert forge_git.head(checkout) == github.repos["octo/app"].commit


def test_an_empty_repository_is_not_cloned(
    github: FakeGitHubRepos, remotes: Path, tmp_path: Path
) -> None:
    repo = repository(remotes, "octo/neuf")
    with pytest.raises(EmptyRepository):
        run(lambda forge: forge.clone(repo, tmp_path / "clone"), remotes)


def _commit(checkout: Path, content: str, message: str) -> None:
    (checkout / "requirements.txt").write_text(content, encoding="utf-8")
    author = forge_git.Author(name="Octo Cat", email="octo@example.com")
    forge_git.commit(checkout, ["requirements.txt"], message, author=author)


def test_push_a_branch_then_read_it_back(
    github: FakeGitHubRepos, remotes: Path, tmp_path: Path
) -> None:
    repo = repository(remotes)
    assert run(lambda forge: forge.branch(repo, BRANCH), remotes) is None
    checkout = tmp_path / "clone"
    run(lambda forge: forge.clone(repo, checkout), remotes)
    _commit(checkout, "flask==0.12.5\n", "Mise à jour\n\nGenerated-by: forceupdate 0.1.0\n")
    run(lambda forge: forge.push_branch(repo, checkout, BRANCH, expected=None), remotes)

    branch = run(lambda forge: forge.branch(repo, BRANCH), remotes)
    assert branch is not None
    assert branch.head == forge_git.head(checkout)
    assert branch.tree == forge_git.tree(checkout)
    assert branch.ahead == 1
    assert [c.message for c in branch.commits] == ["Mise à jour\n\nGenerated-by: forceupdate 0.1.0"]
    assert not branch.commits[0].merge


def test_a_commit_pushed_by_someone_else_is_seen(github: FakeGitHubRepos, remotes: Path) -> None:
    fake = github.repos["octo/app"]
    push_commit(fake, BRANCH, {"requirements.txt": "flask==1.0\n"}, "Correction à la main")
    repo = repository(remotes)
    branch = run(lambda forge: forge.branch(repo, BRANCH), remotes)
    assert branch is not None
    assert [c.message for c in branch.commits] == ["Correction à la main"]


def test_never_push_on_the_default_branch(
    github: FakeGitHubRepos, remotes: Path, tmp_path: Path
) -> None:
    repo = repository(remotes)
    checkout = tmp_path / "clone"
    run(lambda forge: forge.clone(repo, checkout), remotes)
    _commit(checkout, "flask==9\n", "x")
    with pytest.raises(ForgeError, match="jamais sur la branche par défaut"):
        run(lambda forge: forge.push_branch(repo, checkout, "main", expected=None), remotes)
    assert git(github.repos["octo/app"].remote, "rev-parse", "main").strip() != (  # type: ignore[arg-type]
        forge_git.head(checkout)
    )


def test_a_push_that_moved_is_refused(
    github: FakeGitHubRepos, remotes: Path, tmp_path: Path
) -> None:
    repo = repository(remotes)
    fake = github.repos["octo/app"]
    push_commit(fake, BRANCH, {"requirements.txt": "flask==1.0\n"}, "Correction à la main")
    checkout = tmp_path / "clone"
    run(lambda forge: forge.clone(repo, checkout), remotes)
    _commit(checkout, "flask==0.12.5\n", "x")
    with pytest.raises(forge_git.GitError) as raised:
        run(lambda forge: forge.push_branch(repo, checkout, BRANCH, expected=None), remotes)
    assert raised.value.failure is forge_git.GitFailure.STALE


def test_git_refusing_the_token_is_a_refused_token(
    github: FakeGitHubRepos, remotes: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = repository(remotes)

    def refuse(arguments: list[str], **options: object) -> str:
        raise forge_git.GitError("non", failure=forge_git.GitFailure.AUTH)

    monkeypatch.setattr(forge_git, "_git", refuse)
    with pytest.raises(TokenRefused, match="refuse le token"):
        run(lambda forge: forge.clone(repo, tmp_path / "clone"), remotes)

    def deny(arguments: list[str], **options: object) -> str:
        raise forge_git.GitError("non", failure=forge_git.GitFailure.DENIED)

    monkeypatch.setattr(forge_git, "_git", deny)
    with pytest.raises(AccessDenied, match="pousser une branche dans octo/app"):
        run(lambda forge: forge.push_branch(repo, tmp_path, BRANCH, expected=None), remotes)


def test_open_then_update_the_same_request(
    github: FakeGitHubRepos, remotes: Path, tmp_path: Path
) -> None:
    repo = repository(remotes)
    assert run(lambda forge: forge.find_open_request(repo, BRANCH), remotes) is None
    checkout = tmp_path / "clone"
    run(lambda forge: forge.clone(repo, checkout), remotes)
    _commit(checkout, "flask==0.12.5\n", "x")
    run(lambda forge: forge.push_branch(repo, checkout, BRANCH, expected=None), remotes)

    opened = run(
        lambda forge: forge.open_or_update_request(
            repo, branch=BRANCH, title="Mise à jour", body="Première"
        ),
        remotes,
    )
    assert (opened.number, opened.branch, opened.base) == (41, BRANCH, "main")
    assert opened.url == "https://github.com/octo/app/pull/41"
    found = run(lambda forge: forge.find_open_request(repo, BRANCH), remotes)
    assert found == opened

    again = run(
        lambda forge: forge.open_or_update_request(
            repo, branch=BRANCH, title="Mise à jour 2", body="Seconde"
        ),
        remotes,
    )
    assert again.number == 41
    pull = github.pull("octo/app")
    assert (pull.title, pull.body) == ("Mise à jour 2", "Seconde")


def test_a_request_opened_meanwhile_is_updated_not_doubled(
    github: FakeGitHubRepos, remotes: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = repository(remotes)
    fake = github.repos["octo/app"]
    push_commit(fake, BRANCH, {"requirements.txt": "flask==0.12.5\n"}, "x")
    calls = 0
    original = GitHub.find_open_request

    async def late(self: GitHub, repo: Repository, branch: str):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 1:  # une autre fenêtre l'ouvre juste après qu'on a regardé
            fake.pulls.append(FakePull(number=7, title="t", body="b", head=BRANCH, base="main"))
            return None
        return await original(self, repo, branch)

    monkeypatch.setattr(GitHub, "find_open_request", late)
    request = run(
        lambda forge: forge.open_or_update_request(repo, branch=BRANCH, title="T", body="B"),
        remotes,
    )
    assert request.number == 7
    assert len(fake.pulls) == 1
    assert fake.pulls[0].body == "B"


def test_the_last_request_closed_without_merge_is_found(
    github: FakeGitHubRepos, remotes: Path
) -> None:
    """``closed_request`` : la dernière PR de la branche, si elle est fermée sans fusion (E31).
    Une PR fusionnée ou ouverte après elle efface le refus."""
    repo = repository(remotes)
    pulls = github.repos["octo/app"].pulls

    def closed() -> object:
        return run(lambda forge: forge.closed_request(repo, BRANCH), remotes)

    assert closed() is None  # jamais de PR
    pulls.append(
        FakePull(
            number=3,
            title="T",
            body="B",
            head=BRANCH,
            base="main",
            state="closed",
            closed_at="2026-10-12T09:30:00Z",
        )
    )
    pulls.append(FakePull(number=4, title="T", body="B", head="autre", base="main", state="closed"))
    found = closed()
    assert isinstance(found, ChangeRequest)
    assert (found.number, found.branch, found.base) == (3, BRANCH, "main")
    assert found.url == "https://github.com/octo/app/pull/3"
    assert found.closed_at == datetime(2026, 10, 12, 9, 30, tzinfo=UTC)
    pulls.append(
        FakePull(
            number=5,
            title="T",
            body="B",
            head=BRANCH,
            base="main",
            state="closed",
            merged=True,
            closed_at="2026-10-20T09:30:00Z",
        )
    )
    assert closed() is None  # fusionnée depuis
    pulls.append(FakePull(number=6, title="T", body="B", head=BRANCH, base="main"))
    assert closed() is None  # une ouverte


def test_a_request_on_a_read_only_repository_is_refused(
    github: FakeGitHubRepos, remotes: Path
) -> None:
    repo = repository(remotes, "atelier/lecture")
    push_commit(github.repos["atelier/lecture"], BRANCH, {"a.txt": "b\n"}, "x")
    with pytest.raises(AccessDenied):
        run(
            lambda forge: forge.open_or_update_request(repo, branch=BRANCH, title="T", body="B"),
            remotes,
        )


def test_a_request_from_the_default_branch_is_refused(
    github: FakeGitHubRepos, remotes: Path
) -> None:
    repo = repository(remotes)
    with pytest.raises(ForgeError, match="autre branche"):
        run(
            lambda forge: forge.open_or_update_request(repo, branch="main", title="T", body="B"),
            remotes,
        )
