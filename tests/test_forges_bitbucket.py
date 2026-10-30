"""Le client Bitbucket Cloud (``forges.bitbucket``, E20) : le compte, ses portées et son adresse,
les dépôts workspace par workspace (droit de push, drapeaux), l'arborescence en largeur (tailles,
liens et sous-modules écartés, tronquée trop profonde, trop longue ou trop lente), les fichiers,
les erreurs, le token renouvelé quand Bitbucket le refuse ; pour les PR : le clone et le push par
git, la branche de forceupdate et son arbre lu par git, la PR ouverte puis mise à jour (relecteurs
gardés) ; OAuth : l'application par ``Basic`` en formulaire, l'adresse de retour redonnée, le
refresh token renouvelé à chaque usage, pas de révocation. Bitbucket est simulé
(``fake_bitbucket``), git clone et pousse vers des dépôts « bare » du dossier du test."""

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import parse_qs, urlsplit

import pytest
import respx
from fake_bitbucket import FakeBitbucket, FakeToken
from fake_forge import FakePull, FakeRepo, git, make_remote, push_commit, remotes_url

from forceupdate.forges import bitbucket
from forceupdate.forges import git as forge_git
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
from forceupdate.forges.bitbucket import Bitbucket, OAuthApp
from forceupdate.net import HttpClient

T = TypeVar("T")
TOKEN = "bbo-jeton-de-test"
API_TOKEN = "ATATT3xFfGF0-jeton-d-api"
BRANCH = "forceupdate/dependencies"
APP = OAuthApp(client_id="app-bitbucket-de-test", client_secret="secret-bitbucket-de-test")

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
    monkeypatch.setattr(bitbucket, "GIT_URL", remotes_url(root))
    return root


def repositories() -> list[FakeRepo]:
    return [
        FakeRepo(
            full_name="ecureuil/app",
            files={
                "requirements.txt": b"flask==0.12\n",
                "src/app.py": b"print()\n",
                "src/web/package.json": b"{}\n",
            },
            private=True,
            language="Python",
        ),
        FakeRepo(full_name="ecureuil/lecture", files={"a.txt": b"a\n"}, push=False),
        FakeRepo(full_name="ecureuil/copie", fork=True, files={"a.txt": b"a\n"}),
        FakeRepo(full_name="ecureuil/neuf", empty=True),
        FakeRepo(full_name="equipe/site", files={"package.json": b"{}\n"}, push=False),
        FakeRepo(full_name="ailleurs/public", member=False, files={"a.txt": b"a\n"}),
    ]


@pytest.fixture
def cloud() -> Iterator[FakeBitbucket]:
    fake = FakeBitbucket(
        repos=repositories(),
        tokens={TOKEN: FakeToken(), API_TOKEN: FakeToken(kind="api")},
        page_size=2,
        administrator=frozenset({"equipe"}),
    )
    with respx.mock(assert_all_called=False) as router:
        fake.routes(router)
        yield fake


def forge_of(work: Callable[[Bitbucket], Awaitable[T]], token: str | None = TOKEN) -> T:
    return run(lambda http: work(Bitbucket(http, token)))


# -- le compte ----------------------------------------------------------------------


def test_whoami_with_an_oauth_token(cloud: FakeBitbucket) -> None:
    identity = forge_of(lambda forge: forge.whoami())
    assert identity.login == "ecureuil"
    assert identity.name == "Écureuil Roux"
    assert identity.url.startswith("https://bitbucket.org/")
    assert identity.host == "bitbucket.org"
    assert identity.access is Access.WRITE
    assert identity.scopes == ("account", "pullrequest:write")  # comme les écrit Bitbucket
    assert identity.warnings == ()
    # Pas d'adresse « noreply » sur Bitbucket : l'adresse principale, confirmée.
    assert identity.email == "ecureuil@example.org"


def test_whoami_with_an_api_token(cloud: FakeBitbucket) -> None:
    identity = forge_of(lambda forge: forge.whoami(), token=API_TOKEN)
    assert identity.access is Access.UNKNOWN
    assert identity.scopes is None
    assert "write:pullrequest:bitbucket" in identity.warnings[0]
    assert identity.email == "ecureuil@example.org"


def test_whoami_says_what_is_missing(cloud: FakeBitbucket) -> None:
    cloud.tokens = {TOKEN: FakeToken(scopes=("account", "repository"))}
    identity = forge_of(lambda forge: forge.whoami())
    assert identity.access is Access.READ
    assert identity.warnings[0].startswith("Sans les dépôts et les pull requests en écriture")
    cloud.tokens = {TOKEN: FakeToken(scopes=("pullrequest:write",))}  # ni account ni email
    identity = forge_of(lambda forge: forge.whoami())
    assert identity.access is Access.WRITE
    assert identity.email is None
    assert identity.warnings[0].startswith("L'adresse du compte ne se lit pas")


def test_a_refused_token(cloud: FakeBitbucket) -> None:
    with pytest.raises(TokenRefused, match=r"Bitbucket refuse le token \(401\)"):
        forge_of(lambda forge: forge.whoami(), token="faux")
    assert all("faux" not in str(request.url) for request in cloud.requests)


def test_the_token_is_renewed_once_when_refused(cloud: FakeBitbucket) -> None:
    cloud.tokens = {"ancien": FakeToken(valid=False), "neuf": FakeToken()}
    asked: list[str | None] = []

    async def renew(http: HttpClient, refused: str | None) -> str:
        asked.append(refused)
        return "neuf"

    identity = run(lambda http: Bitbucket(http, "ancien", renew=renew).whoami())
    assert identity.login == "ecureuil"
    assert asked == ["ancien"]

    async def still_refused(http: HttpClient, refused: str | None) -> str:
        raise TokenRefused("Bitbucket ne renouvelle plus le token")

    with pytest.raises(TokenRefused, match="ne renouvelle plus"):
        run(lambda http: Bitbucket(http, "ancien", renew=still_refused).whoami())


# -- les dépôts -------------------------------------------------------------------------


def test_list_repos_workspace_by_workspace(cloud: FakeBitbucket) -> None:
    found = {repo.full_name: repo for repo in forge_of(lambda forge: forge.list_repos())}
    assert sorted(found) == [
        "ecureuil/app",
        "ecureuil/copie",
        "ecureuil/lecture",
        "ecureuil/neuf",
        "equipe/site",
    ]
    app = found["ecureuil/app"]
    assert app.private and app.can_push and not app.archived and not app.fork
    assert app.default_branch == "main"
    assert app.url == "https://bitbucket.org/ecureuil/app"
    assert app.clone_url == "https://bitbucket.org/ecureuil/app.git"  # sans identifiants
    assert app.language == "Python"  # « python » pour Bitbucket
    assert app.pushed_at is not None
    assert not found["ecureuil/lecture"].can_push
    assert found["ecureuil/copie"].fork
    assert found["ecureuil/neuf"].empty and found["ecureuil/neuf"].default_branch is None
    # Administrateur du workspace « equipe » : il y pousse partout.
    assert found["equipe/site"].can_push
    paths = [r.url.path for r in cloud.requests]
    assert "/2.0/repositories" not in paths  # retiré par Bitbucket en avril 2026
    assert paths.count("/2.0/repositories/ecureuil") == 2  # deux par page


def test_a_repository_by_its_name(cloud: FakeBitbucket) -> None:
    app = forge_of(lambda forge: forge.repository("ecureuil/app"))
    assert app.full_name == "ecureuil/app" and app.can_push
    assert not forge_of(lambda forge: forge.repository("ecureuil/lecture")).can_push
    public = forge_of(lambda forge: forge.repository("ailleurs/public"), token=None)
    assert public.full_name == "ailleurs/public" and not public.can_push
    with pytest.raises(NotFound, match="Introuvable sur Bitbucket"):
        forge_of(lambda forge: forge.repository("ecureuil/app"), token=None)


def tree_of(name: str) -> Any:
    async def work(forge: Bitbucket) -> Any:
        return await forge.tree(await forge.repository(name))

    return forge_of(work)


def test_the_tree_with_sizes_without_symlinks_or_submodules(cloud: FakeBitbucket) -> None:
    app = cloud.repositories["ecureuil/app"]
    app.symlinks = ("lien",)
    app.submodules = ("vendor/module",)
    tree = tree_of("ecureuil/app")
    assert tree.commit == app.commit
    assert sorted((entry.path, entry.size) for entry in tree.entries) == [
        ("requirements.txt", 12),
        ("src/app.py", 8),
        ("src/web/package.json", 3),
    ]
    assert not tree.truncated
    listing = [r for r in cloud.requests if "/src/" in r.url.path]
    assert all(parse_qs(r.url.query.decode())["max_depth"] == ["12"] for r in listing)


def test_a_tree_too_deep_too_long_or_too_slow_is_truncated(
    cloud: FakeBitbucket, monkeypatch: pytest.MonkeyPatch
) -> None:
    with monkeypatch.context() as patched:
        patched.setattr(bitbucket, "MAX_TREE_DEPTH", 2)
        deep = tree_of("ecureuil/app")
    assert deep.truncated  # src/web n'a pas été parcouru
    assert "src/web/package.json" not in [entry.path for entry in deep.entries]
    with monkeypatch.context() as patched:
        patched.setattr(bitbucket, "MAX_TREE_PAGES", 1)
        assert tree_of("ecureuil/app").truncated
    cloud.slow_tree = True
    before = len(cloud.requests)
    slow = tree_of("ecureuil/app")
    assert slow.truncated and slow.entries == ()
    # Sans reprise : le 555 n'est demandé qu'une fois.
    assert len([r for r in cloud.requests[before:] if "/src/" in r.url.path]) == 1


def test_read_file(cloud: FakeBitbucket) -> None:
    app = cloud.repositories["ecureuil/app"]

    async def work(forge: Bitbucket) -> Any:
        repo = await forge.repository("ecureuil/app")
        return (
            await forge.read_file(repo, "src/app.py", app.commit),
            await forge.read_file(repo, "absent.txt", app.commit),
        )

    assert forge_of(work) == (b"print()\n", None)
    assert cloud.files() == ["ecureuil/app:src/app.py", "ecureuil/app:absent.txt"]


def test_an_empty_repository_has_no_tree(cloud: FakeBitbucket) -> None:
    with pytest.raises(EmptyRepository):
        tree_of("ecureuil/neuf")


def test_error_messages(cloud: FakeBitbucket) -> None:
    async def unknown(forge: Bitbucket) -> Any:
        await forge.request("GET", "/repositories/inconnu/depot")

    with pytest.raises(NotFound, match=r"Introuvable sur Bitbucket \(404\) : /repositories/"):
        forge_of(unknown)

    async def elsewhere(forge: Bitbucket) -> Any:
        await forge.request("GET", "https://exemple.org/2.0/user")

    with pytest.raises(ForgeError, match="hors de l'API de Bitbucket"):
        forge_of(elsewhere)  # jamais le token ailleurs que sur l'API


def test_bitbucket_messages_in_every_shape() -> None:
    import json

    import httpx

    from forceupdate.net.http import Response

    def message(body: Any) -> str:
        response = Response(
            url="https://api.bitbucket.org/2.0/x",
            status_code=400,
            headers=httpx.Headers(),
            content=json.dumps(body).encode(),
        )
        return bitbucket._message(response)

    assert message({"type": "error", "error": {"message": "Bad request"}}) == "Bad request."
    assert message(
        {"type": "error", "error": {"message": "Invalid", "fields": {"source": ["main"]}}}
    ) == ("Invalid ; source : main.")
    assert message({"error": "invalid_grant", "error_description": "expired"}) == "expired."
    assert message([]) == "pas de détail."


# -- la mise à jour : git, la branche, la PR ---------------------------------------------


@pytest.fixture
def remote_cloud(remotes: Path) -> Iterator[FakeBitbucket]:
    app = FakeRepo(full_name="ecureuil/app", files={"requirements.txt": b"flask==0.12\n"})
    make_remote(app, remotes)
    lecture = FakeRepo(full_name="ecureuil/lecture", push=False, files={"a.txt": b"a\n"})
    make_remote(lecture, remotes)
    fake = FakeBitbucket(repos=[app, lecture], tokens={TOKEN: FakeToken()})
    with respx.mock(assert_all_called=False) as router:
        fake.routes(router)
        yield fake


def clone_commit_push(
    forge: Bitbucket, repo: Repository, workdir: Path, content: str, *, expected: str | None
) -> Awaitable[Path]:
    async def work() -> Path:
        checkout = workdir / "clone"
        await forge.clone(repo, checkout)
        (checkout / "requirements.txt").write_text(content, encoding="utf-8", newline="\n")
        author = forge_git.Author(name="Écureuil Roux", email="ecureuil@example.org")
        await asyncio.to_thread(
            forge_git.commit,
            checkout,
            ["requirements.txt"],
            "Mise à jour\n\nGenerated-by: forceupdate 0\n",
            author=author,
        )
        await forge.push_branch(repo, checkout, BRANCH, expected=expected)
        return checkout

    return work()


@needs_git
def test_clone_push_branch_and_pull_request(remote_cloud: FakeBitbucket, tmp_path: Path) -> None:
    app = remote_cloud.repositories["ecureuil/app"]
    assert app.remote is not None

    async def first(http: HttpClient) -> Any:
        forge = Bitbucket(http, TOKEN)
        repo = await forge.repository("ecureuil/app")
        assert await forge.branch(repo, BRANCH) is None
        assert await forge.find_open_request(repo, BRANCH) is None
        checkout = await clone_commit_push(
            forge, repo, tmp_path / "un", "flask==2.3.3\n", expected=None
        )
        branch = await forge.branch(repo, BRANCH)
        assert branch is not None
        tree = await forge.branch_tree(repo, checkout, branch)
        request = await forge.open_or_update_request(repo, branch=BRANCH, title="T", body="B")
        return branch, tree, request

    branch, tree, request = run(first)
    assert branch.ahead == 1 and not branch.commits[0].merge
    assert "Generated-by: forceupdate" in branch.commits[0].message
    assert branch.tree is None  # l'API ne le donne pas…
    # … mais git le lit : relancer sans changement ne poussera rien.
    assert tree == git(app.remote, "rev-parse", f"{branch.head}^{{tree}}").strip()
    assert request.number == 1
    assert request.url == "https://bitbucket.org/ecureuil/app/pull-requests/1"
    assert (request.branch, request.base) == (BRANCH, "main")
    assert git(app.remote, "show", "main:requirements.txt") == "flask==0.12\n"

    pull = remote_cloud.pull("ecureuil/app")
    pull.reviewers = [{"uuid": "{relecteur}", "display_name": "Relecteur"}]  # type: ignore[attr-defined]

    async def again(http: HttpClient) -> Any:
        forge = Bitbucket(http, TOKEN)
        repo = await forge.repository("ecureuil/app")
        found = await forge.branch(repo, BRANCH)
        assert found is not None
        await clone_commit_push(
            forge, repo, tmp_path / "deux", "flask==3.0.0\n", expected=found.head
        )
        return await forge.open_or_update_request(repo, branch=BRANCH, title="T2", body="B2")

    updated = run(again)
    assert updated.number == 1  # la même PR, mise à jour
    assert [(p.title, p.body) for p in app.pulls] == [("T2", "B2")]
    assert pull.reviewers == [{"uuid": "{relecteur}"}]  # type: ignore[attr-defined]
    assert git(app.remote, "show", f"{BRANCH}:requirements.txt") == "flask==3.0.0\n"


@needs_git
def test_the_lease_refuses_a_branch_moved_in_between(
    remote_cloud: FakeBitbucket, tmp_path: Path
) -> None:
    app = remote_cloud.repositories["ecureuil/app"]
    other = push_commit(app, BRANCH, {"autre.txt": "x\n"}, "Correction à la main")

    async def work(http: HttpClient) -> Any:
        forge = Bitbucket(http, TOKEN)
        repo = await forge.repository("ecureuil/app")
        found = await forge.branch(repo, BRANCH)
        assert found is not None and found.head == other
        assert [c.message.strip() for c in found.commits] == ["Correction à la main"]
        await clone_commit_push(forge, repo, tmp_path / "w", "flask==2.3.3\n", expected="0" * 40)

    with pytest.raises(forge_git.GitError) as caught:
        run(work)
    assert caught.value.failure is forge_git.GitFailure.STALE


@needs_git
def test_never_on_the_default_branch_nor_without_the_right(
    remote_cloud: FakeBitbucket, tmp_path: Path
) -> None:
    async def work(http: HttpClient) -> Any:
        forge = Bitbucket(http, TOKEN)
        repo = await forge.repository("ecureuil/app")
        with pytest.raises(ForgeError, match="jamais sur la branche par défaut"):
            await forge.push_branch(repo, tmp_path, "main", expected=None)
        with pytest.raises(ForgeError, match="Une PR se propose"):
            await forge.open_or_update_request(repo, branch="main", title="t", body="b")
        lecture = await forge.repository("ecureuil/lecture")
        with pytest.raises(AccessDenied, match="403"):
            await forge.open_or_update_request(lecture, branch=BRANCH, title="t", body="b")

    run(work)


@needs_git
def test_a_pull_request_opened_in_between_is_updated(
    remote_cloud: FakeBitbucket, tmp_path: Path
) -> None:
    app = remote_cloud.repositories["ecureuil/app"]
    push_commit(
        app, BRANCH, {"requirements.txt": "flask==2.3.3\n"}, "x\n\nGenerated-by: forceupdate"
    )
    calls = 0
    original = remote_cloud._pullrequests

    def racing(repo: FakeRepo, rest: str, query: Any, request: Any) -> Any:
        nonlocal calls
        if request.method == "GET" and rest == "/pullrequests" and calls == 0:
            calls += 1  # la première recherche ne la voit pas encore…
            app.pulls.append(
                FakePull(number=7, title="t", body="b", head=BRANCH, base="main", state="OPEN")
            )
            return remote_cloud._page(request, [], query)
        if request.method == "POST":  # … Bitbucket refuse de la créer une deuxième fois
            return remote_cloud._error(400, "Pull request already exists")
        return original(repo, rest, query, request)

    remote_cloud._pullrequests = racing  # type: ignore[method-assign]

    async def work(http: HttpClient) -> Any:
        forge = Bitbucket(http, TOKEN)
        repo = await forge.repository("ecureuil/app")
        return await forge.open_or_update_request(repo, branch=BRANCH, title="T", body="B")

    request = run(work)
    assert request.number == 7
    assert [(p.number, p.title) for p in app.pulls] == [(7, "T")]


@needs_git
def test_git_never_sees_the_token(
    remote_cloud: FakeBitbucket, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote_cloud.tokens = {TOKEN: FakeToken(), API_TOKEN: FakeToken(kind="api")}
    seen: list[tuple[list[str], dict[str, str]]] = []
    spawn = forge_git._spawn

    def watch(command: list[str], **options: Any) -> Any:
        seen.append((command, dict(options.get("env") or {})))
        return spawn(command, **options)

    monkeypatch.setattr(forge_git, "_spawn", watch)

    async def work(http: HttpClient) -> None:
        for token, folder in ((TOKEN, "a"), (API_TOKEN, "b")):
            forge = Bitbucket(http, token)
            await forge.clone(await forge.repository("ecureuil/app"), tmp_path / folder)

    run(work)
    assert seen
    for command, _ in seen:
        assert all(TOKEN not in part and API_TOKEN not in part for part in command)
    clones = [env for command, env in seen if "clone" in command]
    assert [env[forge_git.USERNAME_VARIABLE] for env in clones] == [
        "x-token-auth",
        "x-bitbucket-api-token-auth",
    ]


# -- OAuth -------------------------------------------------------------------------------


def test_the_authorization_url() -> None:
    url = APP.authorization_url(
        redirect_to=APP.redirect_uri(54321), state="etat", verifier="v" * 50
    )
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == (
        "https://bitbucket.org/site/oauth2/authorize"
    )
    assert parse_qs(parts.query) == {
        "client_id": ["app-bitbucket-de-test"],
        "response_type": ["code"],
        "redirect_uri": ["http://127.0.0.1:54321/oauth/bitbucket/callback"],
        "state": ["etat"],
        "code_challenge": [challenge_of("v" * 50)],
        "code_challenge_method": ["S256"],
    }
    assert "secret" not in url
    assert APP.web_flow
    assert not OAuthApp(client_id="x", client_secret="").web_flow
    assert not OAuthApp.revocable


def test_the_default_application(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(bitbucket.ENV_CLIENT_ID, raising=False)
    default = OAuthApp.default()
    assert (default.client_id, default.client_secret) == (
        bitbucket.CLIENT_ID,
        bitbucket.CLIENT_SECRET,
    )
    monkeypatch.setenv(bitbucket.ENV_CLIENT_ID, "autre-application")
    monkeypatch.setenv(bitbucket.ENV_CLIENT_SECRET, "autre-secret")
    other = OAuthApp.default()
    assert (other.client_id, other.client_secret) == ("autre-application", "autre-secret")
    assert "autre-secret" not in repr(other)


def test_exchange_refresh_and_no_revocation() -> None:
    fake = FakeBitbucket(client_id=APP.client_id, client_secret=APP.client_secret, tokens={})
    redirect = APP.redirect_uri(4321)
    with respx.mock(assert_all_called=False) as router:
        fake.routes(router)
        code = fake.authorize(redirect)
        grant = run(
            lambda http: APP.exchange_code(http, code=code, redirect_to=redirect, verifier="v")
        )
        assert len(grant.access_token) > 2000  # comme ceux de Bitbucket
        assert grant.refresh_token is not None and grant.expires_at is not None
        exchange = fake.requests[-1]
        assert exchange.headers["authorization"].startswith("Basic ")
        assert "secret" not in exchange.content.decode()  # le secret passe par Basic seulement
        # Un code ne sert qu'une fois ; l'adresse de retour doit être la même.
        with pytest.raises(ForgeError, match="a expiré ou a déjà servi"):
            run(lambda http: APP.exchange_code(http, code=code, redirect_to=redirect, verifier="v"))
        other = fake.authorize(redirect)
        with pytest.raises(ForgeError, match="adresse de retour"):
            run(
                lambda http: APP.exchange_code(
                    http, code=other, redirect_to=APP.redirect_uri(1), verifier="v"
                )
            )
        # Renouvelé : un nouveau token et un nouveau refresh token ; l'ancien ne sert plus.
        fresh = run(lambda http: APP.refresh(http, grant.refresh_token or ""))
        assert fresh.access_token != grant.access_token
        assert fresh.refresh_token not in (None, grant.refresh_token)
        with pytest.raises(TokenRefused, match="ne renouvelle plus"):
            run(lambda http: APP.refresh(http, grant.refresh_token or ""))
        # Une autre application (secret faux) : refusée.
        wrong = OAuthApp(client_id=APP.client_id, client_secret="faux")
        with pytest.raises(ForgeError, match="ne reconnaît pas l'application"):
            run(
                lambda http: wrong.exchange_code(http, code="c", redirect_to=redirect, verifier="v")
            )
        assert not run(lambda http: APP.revoke(http, fresh.access_token))
    assert APP.authorization_error("access_denied") == "Autorisation refusée sur Bitbucket."
