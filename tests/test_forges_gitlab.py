"""Le client GitLab (``forges.gitlab``, E19) : le compte et ses portées, les projets (groupes et
sous-groupes, drapeaux, droit de push), l'arborescence paginée et les fichiers, les erreurs, le
token renouvelé quand GitLab le refuse ; pour les MR : le clone et le push par git, la branche
de forceupdate et son arbre recalculé (``tree_id``), la MR ouverte puis mise à jour ; OAuth :
PKCE sans secret, refresh token à usage unique, révocation. GitLab est simulé
(``fake_gitlab``), git clone et pousse vers des dépôts « bare » du dossier du test."""

import asyncio
import threading
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import parse_qs, urlsplit

import pytest
import respx
from fake_forge import FakePull, FakeRepo, git, make_remote, push_commit, remotes_url
from fake_gitlab import FakeGitLab, FakeToken

from forceupdate import processes
from forceupdate.forges import git as forge_git
from forceupdate.forges import gitlab
from forceupdate.forges.base import (
    Access,
    AccessDenied,
    EmptyRepository,
    ForgeError,
    NotFound,
    Repository,
    TokenRefused,
    challenge_of,
)
from forceupdate.forges.gitlab import GitLab, OAuthApp, tree_id
from forceupdate.net import HttpClient

T = TypeVar("T")
TOKEN = "glpat-jeton-de-test"
BRANCH = "forceupdate/dependencies"
APP = OAuthApp(client_id="app-gitlab-de-test")

needs_git = pytest.mark.skipif(not forge_git.available(), reason="git n'est pas installé")


async def _no_sleep(_: float) -> None:
    pass


def run(work: Callable[[HttpClient], Awaitable[T]]) -> T:
    async def main() -> T:
        async with HttpClient(sleep=_no_sleep) as http:
            return await work(http)

    return asyncio.run(main())


@pytest.fixture
def remotes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "distants"
    monkeypatch.setattr(gitlab, "GIT_URL", remotes_url(root))
    return root


def projects() -> list[FakeRepo]:
    return [
        FakeRepo(
            full_name="renard/app",
            files={"requirements.txt": b"flask==0.12\n", "src/app.py": b"print()\n"},
            private=True,
        ),
        FakeRepo(full_name="atelier/web/site", files={"package.json": b"{}\n"}, push=False),
        FakeRepo(full_name="atelier/ancien", archived=True, files={"a.txt": b"a\n"}),
        FakeRepo(full_name="renard/copie", fork=True, files={"a.txt": b"a\n"}),
        FakeRepo(full_name="renard/neuf", empty=True),
        FakeRepo(full_name="ailleurs/public", member=False, files={"a.txt": b"a\n"}),
    ]


@pytest.fixture
def lab() -> Iterator[FakeGitLab]:
    fake = FakeGitLab(repos=projects(), tokens={TOKEN: FakeToken()}, page_size=2)
    with respx.mock(assert_all_called=False) as router:
        fake.routes(router)
        yield fake


def repo_of(work: Callable[[GitLab], Awaitable[T]], token: str | None = TOKEN) -> T:
    return run(lambda http: work(GitLab(http, token)))


# -- le compte ----------------------------------------------------------------------


def test_whoami_with_a_personal_token(lab: FakeGitLab) -> None:
    lab.tokens = {TOKEN: FakeToken(scopes=("api",), expires_at="2027-01-31")}
    identity = repo_of(lambda forge: forge.whoami())
    assert identity.login == "renard"
    assert identity.name == "Renard Roux"
    assert identity.url == "https://gitlab.com/renard"
    assert identity.host == "gitlab.com"
    assert identity.access is Access.WRITE
    assert identity.scopes == ("api",)
    assert identity.email == "4242-renard@users.noreply.gitlab.com"
    assert identity.warnings == ("Ce token expire le 31/01/2027 : il faudra en coller un nouveau.",)


def test_whoami_with_an_oauth_token(lab: FakeGitLab) -> None:
    lab.tokens = {TOKEN: FakeToken(kind="oauth")}
    identity = repo_of(lambda forge: forge.whoami())
    assert identity.access is Access.WRITE
    assert identity.scopes == ("api",)
    assert identity.warnings == ()


@pytest.mark.parametrize(
    ("scopes", "access", "warning"),
    [
        (("read_api",), Access.READ, "Portée read_api"),
        (("read_user",), Access.READ, "Sans la portée api"),
    ],
)
def test_whoami_says_what_is_missing(
    lab: FakeGitLab, scopes: tuple[str, ...], access: Access, warning: str
) -> None:
    lab.tokens = {TOKEN: FakeToken(scopes=scopes)}
    identity = repo_of(lambda forge: forge.whoami())
    assert identity.access is access
    assert identity.warnings[0].startswith(warning)


def test_a_self_hosted_instance() -> None:
    fake = FakeGitLab(host="git.example.com:8443", tokens={TOKEN: FakeToken()})
    with respx.mock(assert_all_called=False) as router:
        fake.routes(router)
        identity = run(lambda http: GitLab(http, TOKEN, host="git.example.com:8443").whoami())
    assert identity.host == "git.example.com:8443"
    assert identity.url == "https://git.example.com:8443/renard"
    assert identity.email == "4242-renard@users.noreply.git.example.com"
    assert all(str(r.url).startswith("https://git.example.com:8443/") for r in fake.requests)


def test_a_refused_token(lab: FakeGitLab) -> None:
    with pytest.raises(TokenRefused, match=r"GitLab refuse le token \(401\)"):
        repo_of(lambda forge: forge.whoami(), token="faux")
    assert all("faux" not in str(request.url) for request in lab.requests)


def test_the_token_is_renewed_once_when_refused(lab: FakeGitLab) -> None:
    lab.tokens = {"ancien": FakeToken(kind="oauth", valid=False), "neuf": FakeToken(kind="oauth")}
    asked: list[str | None] = []

    async def renew(http: HttpClient, refused: str | None) -> str:
        asked.append(refused)
        return "neuf"

    identity = run(lambda http: GitLab(http, "ancien", renew=renew).whoami())
    assert identity.login == "renard"
    assert asked == ["ancien"]

    async def still_refused(http: HttpClient, refused: str | None) -> str:
        raise TokenRefused("GitLab ne renouvelle plus le token")

    with pytest.raises(TokenRefused, match="ne renouvelle plus"):
        run(lambda http: GitLab(http, "ancien", renew=still_refused).whoami())


# -- les projets ----------------------------------------------------------------------


def test_list_repos_with_groups_subgroups_and_flags(lab: FakeGitLab) -> None:
    found = {repo.full_name: repo for repo in repo_of(lambda forge: forge.list_repos())}
    assert sorted(found) == [
        "atelier/ancien",
        "atelier/web/site",
        "renard/app",
        "renard/copie",
        "renard/neuf",
    ]
    app, site = found["renard/app"], found["atelier/web/site"]
    assert app.private and app.can_push and not app.archived and not app.fork
    assert app.default_branch == "main"
    assert app.url == "https://gitlab.com/renard/app"
    assert app.clone_url == "https://gitlab.com/renard/app.git"
    assert app.pushed_at is not None
    assert (site.owner, site.name) == ("atelier/web", "site")
    assert not site.can_push and not site.private
    assert found["atelier/ancien"].archived
    assert found["renard/copie"].fork
    assert found["renard/neuf"].empty and found["renard/neuf"].default_branch is None
    # Deux listes paginées (tous les projets, puis ceux où l'on pousse), deux par page.
    pages = [r for r in lab.requests if r.url.path == "/api/v4/projects"]
    assert len(pages) == 3 + 2


def test_a_project_by_its_full_path(lab: FakeGitLab) -> None:
    site = repo_of(lambda forge: forge.repository("atelier/web/site"))
    assert site.full_name == "atelier/web/site"
    assert not site.can_push
    assert lab.requests[-1].url.raw_path.decode() == "/api/v4/projects/atelier%2Fweb%2Fsite"
    public = repo_of(lambda forge: forge.repository("ailleurs/public"), token=None)
    assert public.full_name == "ailleurs/public"
    with pytest.raises(NotFound, match="Introuvable sur GitLab"):
        repo_of(lambda forge: forge.repository("renard/app"), token=None)


def test_the_tree_is_paged_without_sizes_symlinks_or_submodules(lab: FakeGitLab) -> None:
    app = lab.projects["renard/app"]
    app.symlinks = ("lien",)
    app.submodules = ("vendor/module",)

    async def work(forge: GitLab) -> Any:
        repo = await forge.repository("renard/app")
        return await forge.tree(repo)

    tree = repo_of(work)
    assert tree.commit == app.commit
    assert [(entry.path, entry.size) for entry in tree.entries] == [
        ("requirements.txt", None),
        ("src/app.py", None),
    ]
    assert not tree.truncated


def test_a_tree_too_long_is_truncated(lab: FakeGitLab, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gitlab, "MAX_TREE_PAGES", 1)

    async def work(forge: GitLab) -> Any:
        return await forge.tree(await forge.repository("renard/app"))

    tree = repo_of(work)
    assert tree.truncated
    assert len(tree.entries) <= 2


def test_read_file(lab: FakeGitLab) -> None:
    app = lab.projects["renard/app"]

    async def work(forge: GitLab) -> Any:
        repo = await forge.repository("renard/app")
        return (
            await forge.read_file(repo, "src/app.py", app.commit),
            await forge.read_file(repo, "absent.txt", app.commit),
        )

    assert repo_of(work) == (b"print()\n", None)
    assert lab.files() == ["renard/app:src/app.py", "renard/app:absent.txt"]


def test_an_empty_project_has_no_tree(lab: FakeGitLab) -> None:
    async def work(forge: GitLab) -> Any:
        return await forge.tree(await forge.repository("renard/neuf"))

    with pytest.raises(EmptyRepository):
        repo_of(work)


def test_error_messages(lab: FakeGitLab) -> None:
    lab.tokens = {TOKEN: FakeToken(scopes=("read_api",))}

    async def work(forge: GitLab) -> Any:
        await forge.request("GET", "/projects/inconnu%2Fprojet")

    with pytest.raises(
        NotFound, match=r"Introuvable sur GitLab \(404\) : /projects/inconnu/projet"
    ):
        repo_of(work)


def test_gitlab_messages_in_every_shape() -> None:
    def message(body: Any) -> str:
        import json

        from forceupdate.net.http import Response

        response = Response(
            url="https://gitlab.com/api/v4/x",
            status_code=400,
            headers=__import__("httpx").Headers(),
            content=json.dumps(body).encode(),
        )
        return gitlab._message(response)

    assert message({"message": "403 Forbidden"}) == "403 Forbidden."
    assert message({"message": ["Another open merge request already exists: !3"]}) == (
        "Another open merge request already exists: !3."
    )
    assert message({"message": {"title": ["can't be blank"]}}) == "title can't be blank."
    assert message({"error": "insufficient_scope"}) == "insufficient_scope."
    assert message([]) == "pas de détail."


# -- tree_id ---------------------------------------------------------------------------


@needs_git
def test_tree_id_matches_git(tmp_path: Path) -> None:
    """L'arbre recalculé depuis la liste de la racine est celui que git calcule (dossiers triés
    comme s'ils finissaient par ``/``, modes, liens)."""
    work = tmp_path / "travail"
    (work / "a").mkdir(parents=True)
    (work / "a" / "x.txt").write_text("x", encoding="utf-8")
    (work / "a-b.txt").write_text("ab", encoding="utf-8")
    (work / "a.txt").write_text("a", encoding="utf-8")
    (work / "script.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (work / "zé.txt").write_text("accent", encoding="utf-8")
    git(work, "init", "--quiet")
    git(work, "add", "--all")
    git(work, "update-index", "--chmod=+x", "script.sh")
    git(work, "commit", "--quiet", "-m", "arbre")
    entries = []
    for line in git(work, "-c", "core.quotepath=off", "ls-tree", "-z", "HEAD").split("\0"):
        if line:
            meta, _, name = line.partition("\t")
            mode, kind, oid = meta.split()
            entries.append(("040000" if kind == "tree" else mode, name, oid))
    assert tree_id(entries) == git(work, "rev-parse", "HEAD^{tree}").strip()
    assert tree_id([("100644", "a", "pas-un-sha")]) is None
    assert tree_id([]) is None


# -- la mise à jour : git, la branche, la MR ---------------------------------------------


@pytest.fixture
def remote_lab(remotes: Path) -> Iterator[FakeGitLab]:
    app = FakeRepo(full_name="renard/outils/app", files={"requirements.txt": b"flask==0.12\n"})
    make_remote(app, remotes)
    lecture = FakeRepo(full_name="atelier/lecture", push=False, files={"a.txt": b"a\n"})
    make_remote(lecture, remotes)
    fake = FakeGitLab(repos=[app, lecture], tokens={TOKEN: FakeToken()})
    with respx.mock(assert_all_called=False) as router:
        fake.routes(router)
        yield fake


def clone_commit_push(
    forge: GitLab, repo: Repository, workdir: Path, content: str, *, expected: str | None
) -> Awaitable[None]:
    async def work() -> None:
        checkout = workdir / "clone"
        await forge.clone(repo, checkout)
        (checkout / "requirements.txt").write_text(content, encoding="utf-8", newline="\n")
        author = forge_git.Author(name="Renard Roux", email="4242-renard@users.noreply.gitlab.com")
        await asyncio.to_thread(
            forge_git.commit,
            checkout,
            ["requirements.txt"],
            "Mise à jour\n\nGenerated-by: forceupdate 0\n",
            author=author,
        )
        await forge.push_branch(repo, checkout, BRANCH, expected=expected)

    return work()


@needs_git
def test_clone_push_branch_and_merge_request(remote_lab: FakeGitLab, tmp_path: Path) -> None:
    app = remote_lab.projects["renard/outils/app"]
    assert app.remote is not None

    async def first(http: HttpClient) -> Any:
        forge = GitLab(http, TOKEN)
        repo = await forge.repository("renard/outils/app")
        assert await forge.branch(repo, BRANCH) is None
        assert await forge.find_open_request(repo, BRANCH) is None
        await clone_commit_push(forge, repo, tmp_path / "un", "flask==2.3.3\n", expected=None)
        branch = await forge.branch(repo, BRANCH)
        request = await forge.open_or_update_request(repo, branch=BRANCH, title="T", body="B")
        return branch, request

    branch, request = run(first)
    assert branch is not None
    assert branch.ahead == 1 and not branch.commits[0].merge
    assert "Generated-by: forceupdate" in branch.commits[0].message
    # L'arbre recalculé est celui du commit poussé : relancer sans changement ne poussera rien.
    assert branch.tree == git(app.remote, "rev-parse", f"{branch.head}^{{tree}}").strip()
    assert request.number == 1
    assert request.url == "https://gitlab.com/renard/outils/app/-/merge_requests/1"
    assert (request.branch, request.base) == (BRANCH, "main")
    assert git(app.remote, "show", "main:requirements.txt") == "flask==0.12\n"

    async def again(http: HttpClient) -> Any:
        forge = GitLab(http, TOKEN)
        repo = await forge.repository("renard/outils/app")
        found = await forge.branch(repo, BRANCH)
        assert found is not None
        await clone_commit_push(
            forge, repo, tmp_path / "deux", "flask==3.0.0\n", expected=found.head
        )
        return await forge.open_or_update_request(repo, branch=BRANCH, title="T2", body="B2")

    updated = run(again)
    assert updated.number == 1  # la même MR, mise à jour
    assert [(p.title, p.body) for p in app.pulls] == [("T2", "B2")]
    assert git(app.remote, "show", f"{BRANCH}:requirements.txt") == "flask==3.0.0\n"


@needs_git
def test_the_lease_refuses_a_branch_moved_in_between(
    remote_lab: FakeGitLab, tmp_path: Path
) -> None:
    app = remote_lab.projects["renard/outils/app"]
    other = push_commit(app, BRANCH, {"autre.txt": "x\n"}, "Correction à la main")

    async def work(http: HttpClient) -> Any:
        forge = GitLab(http, TOKEN)
        repo = await forge.repository("renard/outils/app")
        found = await forge.branch(repo, BRANCH)
        assert found is not None and found.head == other
        assert [c.message for c in found.commits] == ["Correction à la main"]
        await clone_commit_push(forge, repo, tmp_path / "w", "flask==2.3.3\n", expected="0" * 40)

    with pytest.raises(forge_git.GitError) as caught:
        run(work)
    assert caught.value.failure is forge_git.GitFailure.STALE


@needs_git
def test_never_on_the_default_branch_nor_without_the_right(
    remote_lab: FakeGitLab, tmp_path: Path
) -> None:
    async def work(http: HttpClient) -> Any:
        forge = GitLab(http, TOKEN)
        repo = await forge.repository("renard/outils/app")
        with pytest.raises(ForgeError, match="jamais sur la branche par défaut"):
            await forge.push_branch(repo, tmp_path, "main", expected=None)
        with pytest.raises(ForgeError, match="Une MR se propose"):
            await forge.open_or_update_request(repo, branch="main", title="t", body="b")
        lecture = await forge.repository("atelier/lecture")
        with pytest.raises(AccessDenied, match="403"):
            await forge.open_or_update_request(lecture, branch=BRANCH, title="t", body="b")

    run(work)


@needs_git
def test_a_merge_request_opened_in_between_is_updated(
    remote_lab: FakeGitLab, tmp_path: Path
) -> None:
    app = remote_lab.projects["renard/outils/app"]
    push_commit(
        app, BRANCH, {"requirements.txt": "flask==2.3.3\n"}, "x\n\nGenerated-by: forceupdate"
    )
    calls = 0
    original = remote_lab._merge_requests

    def racing(repo: FakeRepo, rest: str, query: Any, request: Any) -> Any:
        nonlocal calls
        if request.method == "GET" and calls == 0:
            calls += 1  # la première recherche ne la voit pas encore…
            app.pulls.append(
                FakePull(number=7, title="t", body="b", head=BRANCH, base="main", state="opened")
            )
            return remote_lab._json(200, [])
        return original(repo, rest, query, request)

    remote_lab._merge_requests = racing  # type: ignore[method-assign]

    async def work(http: HttpClient) -> Any:
        forge = GitLab(http, TOKEN)
        repo = await forge.repository("renard/outils/app")
        return await forge.open_or_update_request(repo, branch=BRANCH, title="T", body="B")

    request = run(work)
    assert request.number == 7
    assert [(p.number, p.title) for p in app.pulls] == [(7, "T")]


def test_the_last_merge_request_closed_without_merge_is_found(remote_lab: FakeGitLab) -> None:
    """``closed_request`` : la dernière MR de la branche, si elle est ``closed`` (E31) ; une
    ``merged`` après elle efface le refus."""
    app = remote_lab.projects["renard/outils/app"]

    def closed() -> Any:
        async def work(http: HttpClient) -> Any:
            forge = GitLab(http, TOKEN)
            repo = await forge.repository("renard/outils/app")
            return await forge.closed_request(repo, BRANCH)

        return run(work)

    assert closed() is None
    app.pulls.append(
        FakePull(
            number=2,
            title="T",
            body="B",
            head=BRANCH,
            base="main",
            state="closed",
            closed_at="2026-10-12T09:30:00.000Z",
        )
    )
    found = closed()
    assert (found.number, found.branch) == (2, BRANCH)
    assert found.url.endswith("/renard/outils/app/-/merge_requests/2")
    assert found.closed_at == datetime(2026, 10, 12, 9, 30, tzinfo=UTC)
    app.pulls.append(
        FakePull(number=3, title="T", body="B", head=BRANCH, base="main", state="merged")
    )
    assert closed() is None


@needs_git
def test_git_never_sees_the_token(
    remote_lab: FakeGitLab, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[list[str], dict[str, str]]] = []
    spawn = forge_git._spawn

    def watch(command: list[str], **options: Any) -> Any:
        seen.append((command, dict(options.get("env") or {})))
        return spawn(command, **options)

    monkeypatch.setattr(forge_git, "_spawn", watch)

    async def work(http: HttpClient) -> None:
        forge = GitLab(http, TOKEN)
        await forge.clone(await forge.repository("renard/outils/app"), tmp_path / "c")

    run(work)
    assert seen
    for command, _ in seen:
        assert all(TOKEN not in part for part in command)
    clone = next(env for command, env in seen if "clone" in command)
    assert clone[forge_git.USERNAME_VARIABLE] == "oauth2"


@needs_git
def test_a_clone_stops_with_the_server(remote_lab: FakeGitLab, tmp_path: Path) -> None:
    """``Forge.cancel`` levé (l'arrêt du serveur, E31) : git n'est pas lancé, ou il est tué."""
    stop = threading.Event()
    stop.set()

    async def work(http: HttpClient) -> None:
        forge = GitLab(http, TOKEN)
        forge.cancel = stop
        await forge.clone(await forge.repository("renard/outils/app"), tmp_path / "c")

    with pytest.raises(processes.Interrupted):
        run(work)
    assert not (tmp_path / "c").exists()


# -- OAuth -------------------------------------------------------------------------------


def test_the_authorization_url_uses_pkce_without_a_secret() -> None:
    url = APP.authorization_url(
        redirect_to=APP.redirect_uri(54321), state="etat", verifier="v" * 50
    )
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == "https://gitlab.com/oauth/authorize"
    assert parse_qs(parts.query) == {
        "client_id": ["app-gitlab-de-test"],
        "redirect_uri": ["http://127.0.0.1:54321/oauth/gitlab/callback"],
        "response_type": ["code"],
        "scope": ["api"],
        "state": ["etat"],
        "code_challenge": [challenge_of("v" * 50)],
        "code_challenge_method": ["S256"],
    }
    assert APP.web_flow
    assert not OAuthApp(client_id="").web_flow


def test_the_default_application(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(gitlab.ENV_CLIENT_ID, raising=False)
    assert OAuthApp.default().client_id == gitlab.CLIENT_ID
    monkeypatch.setenv(gitlab.ENV_CLIENT_ID, "autre-application")
    assert OAuthApp.default().client_id == "autre-application"


def test_exchange_refresh_and_revoke() -> None:
    fake = FakeGitLab(client_id=APP.client_id, tokens={})
    with respx.mock(assert_all_called=False) as router:
        fake.routes(router)
        code = fake.authorize("v" * 50)
        grant = run(
            lambda http: APP.exchange_code(
                http, code=code, redirect_to=APP.redirect_uri(1), verifier="v" * 50
            )
        )
        assert grant.access_token.startswith("glo-acces-")
        assert grant.refresh_token is not None
        assert grant.expires_at is not None
        assert "secret" not in str(fake.requests[-1].content)
        # Un code ne sert qu'une fois ; un mauvais verifier est refusé.
        with pytest.raises(ForgeError, match="a expiré ou a déjà servi"):
            run(
                lambda http: APP.exchange_code(
                    http, code=code, redirect_to=APP.redirect_uri(1), verifier="v" * 50
                )
            )
        # Renouvelé : nouveaux tokens, les anciens ne marchent plus.
        fresh = run(lambda http: APP.refresh(http, grant.refresh_token or ""))
        assert fresh.access_token != grant.access_token
        assert fake.tokens is not None and not fake.tokens[grant.access_token].valid
        with pytest.raises(TokenRefused, match="ne renouvelle plus"):
            run(lambda http: APP.refresh(http, grant.refresh_token or ""))
        assert run(lambda http: APP.revoke(http, fresh.access_token))
        assert fake.revoked == [fresh.access_token]
    assert APP.authorization_error("access_denied") == "Autorisation refusée sur GitLab."
