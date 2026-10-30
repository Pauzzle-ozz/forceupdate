"""Bitbucket Cloud dans l'interface (E20) : la connexion par OAuth (l'application et son secret,
l'adresse de retour redonnée), le token de plus de 2 000 caractères rangé en morceaux dans le
trousseau et renouvelé quand il expire (un nouveau refresh token à chaque fois), la déconnexion
qui ne peut pas le révoquer et le dit ; un token d'API Atlassian collé ; puis les dépôts de GitHub
et de Bitbucket listés, analysés dans un même lot, et un même récapitulatif qui ouvre une PR sur
chacune, la PR de Bitbucket mise à jour en relançant sans rien pousser (l'arbre lu par git).

GitHub et Bitbucket sont simulés (``fake_forge``, ``fake_bitbucket``) ; git clone et pousse vers
des dépôts « bare » du dossier du test ; npm et uv sont simulés ; les registres et OSV répondent
avec les réponses enregistrées ; le trousseau est en mémoire (et refuse, comme Windows, un secret
de plus de 1 280 caractères)."""

import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from conftest import API_PORT, FakeTools, MemoryKeyring, recorded_responses
from fake_bitbucket import FakeBitbucket, FakeToken
from fake_forge import FakeGitHubRepos, FakeRepo, from_directory, git, make_remote, remotes_url
from fastapi.testclient import TestClient
from test_update_forge import tools
from test_web_repositories import Finished, connect

from forceupdate.forges import bitbucket
from forceupdate.forges import git as forge_git
from forceupdate.forges import github as github_module
from forceupdate.forges.accounts import Accounts
from forceupdate.forges.base import ForgeKind
from forceupdate.net import http as http_module
from forceupdate.update.forge import BRANCH
from forceupdate.web import openapi
from forceupdate.web.connections import Connections

PROJECTS = Path(__file__).parent / "projects"
GITHUB_TOKEN = "gho_depots"
API_TOKEN = "ATATT3xFfGF0-jeton-colle"
KEY = ("forceupdate", "bitbucket:bitbucket.org")
CROSS_SITE = {
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
}

pytestmark = pytest.mark.skipif(not forge_git.available(), reason="git n'est pas installé")


def connections(api: TestClient) -> Connections:
    found: Connections = api.app.state.connections  # type: ignore[attr-defined]
    return found


@pytest.fixture
def forges(
    api: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[tuple[FakeGitHubRepos, FakeBitbucket]]:
    """GitHub et Bitbucket, chacun avec ses dépôts (et leur dépôt « bare »)."""
    monkeypatch.setattr(http_module, "_backoff", lambda attempt: 0.0)
    remotes = tmp_path / "distants"
    hub = FakeGitHubRepos(
        [from_directory("octo/vulnerable", PROJECTS / "vulnerable", private=True)],
        tokens={GITHUB_TOKEN},
        user={"login": "octo", "id": 583231, "name": "Octo Cat"},
    )
    cloud = FakeBitbucket(
        repos=[
            from_directory("ecureuil/vulnerable", PROJECTS / "vulnerable", private=True),
            FakeRepo(full_name="ecureuil/a-jour", files={"requirements.txt": b"werkzeug==3.1.9\n"}),
        ],
        tokens={API_TOKEN: FakeToken(kind="api")},
    )
    for repo in [*hub.repos.values(), *cloud.repositories.values()]:
        make_remote(repo, remotes)
    monkeypatch.setattr(github_module, "GIT_URL", remotes_url(remotes))
    monkeypatch.setattr(bitbucket, "GIT_URL", remotes_url(remotes))
    connections(api).apps[ForgeKind.BITBUCKET] = bitbucket.OAuthApp(
        client_id=cloud.client_id, client_secret=cloud.client_secret
    )

    def routes(router: Any) -> None:
        hub.routes(router)
        cloud.routes(router)

    with recorded_responses(extra=routes):
        yield hub, cloud


@pytest.fixture
def npm_uv(fake_tools: Callable[..., FakeTools]) -> FakeTools:
    return tools(fake_tools, "npm", "uv")


def bitbucket_status(api: TestClient) -> dict[str, Any]:
    found: dict[str, Any] = api.get("/api/accounts").json()["forges"][2]
    assert found["forge"] == "bitbucket"
    return found


def connect_by_oauth(api: TestClient, cloud: FakeBitbucket) -> dict[str, Any]:
    """Se connecte à Bitbucket par OAuth : la page d'autorisation, puis le retour."""
    started = api.post("/api/accounts/bitbucket/oauth")
    assert started.status_code == 201, started.text
    query = parse_qs(urlsplit(started.json()["authorize_url"]).query)
    code = cloud.authorize(query["redirect_uri"][0])
    response = api.get(
        f"/oauth/bitbucket/callback?code={code}&state={query['state'][0]}",
        headers={**CROSS_SITE, "Authorization": ""},
        follow_redirects=False,
    )
    assert response.status_code == 200
    done: dict[str, Any] = api.get(f"/api/accounts/connections/{started.json()['id']}").json()
    assert done["status"] == "done", done
    return done


def stored_grant(api: TestClient) -> dict[str, Any]:
    """Les tokens du compte Bitbucket, tels que les relit le magasin des comptes."""
    store: Accounts = connections(api).accounts
    grant = store.grant(ForgeKind.BITBUCKET, "bitbucket.org")
    assert grant is not None
    return {"access_token": grant.access_token, "refresh_token": grant.refresh_token}


# -- les comptes ------------------------------------------------------------------------


def test_connect_bitbucket_by_oauth(api: TestClient, forges: Any, keychain: MemoryKeyring) -> None:
    _, cloud = forges
    started = api.post("/api/accounts/bitbucket/oauth").json()
    parts = urlsplit(started["authorize_url"])
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == bitbucket.AUTHORIZE_URL
    query = parse_qs(parts.query)
    assert query["redirect_uri"] == [f"http://127.0.0.1:{API_PORT}/oauth/bitbucket/callback"]
    assert "scope" not in query  # celles de l'application
    assert "secret" not in started["authorize_url"]

    done = connect_by_oauth(api, cloud)
    account = done["account"]
    assert (account["forge"], account["host"], account["login"]) == (
        "bitbucket",
        "bitbucket.org",
        "ecureuil",
    )
    assert (account["access"], account["method"]) == ("write", "oauth")
    # Plus de 2 000 caractères : en morceaux dans le trousseau, chacun sous la limite.
    assert keychain.passwords[KEY].startswith("forceupdate-parts:")
    assert all(len(value) <= MemoryKeyring.MAX_SECRET for value in keychain.passwords.values())
    grant = stored_grant(api)
    assert len(grant["access_token"]) > 2000
    exchange = next(r for r in cloud.requests if r.url.path == "/site/oauth2/access_token")
    assert parse_qs(exchange.content.decode())["redirect_uri"] == query["redirect_uri"]
    status = bitbucket_status(api)
    assert status["account"]["login"] == "ecureuil"
    assert status["methods"] == ["oauth", "token"]
    assert grant["access_token"] not in api.get("/api/accounts").text


def test_an_expired_token_is_renewed_and_cannot_be_revoked(
    api: TestClient, forges: Any, keychain: MemoryKeyring
) -> None:
    _, cloud = forges
    connect_by_oauth(api, cloud)
    first = stored_grant(api)
    cloud.expire(first["access_token"])  # 2 h ont passé
    checked = api.post("/api/accounts/bitbucket/verify")
    assert checked.status_code == 200
    assert checked.json()["problem"] is None
    second = stored_grant(api)
    assert second["access_token"] != first["access_token"]
    assert second["refresh_token"] != first["refresh_token"]  # un nouveau, à chaque fois
    # Un refresh token refusé (403 chez Bitbucket) est dit sur le compte.
    cloud.expire(second["access_token"])
    cloud.grants[-1].used = True
    refused = api.post("/api/accounts/bitbucket/verify").json()
    assert "se reconnecter" in refused["problem"]

    response = api.delete("/api/accounts/bitbucket")
    assert response.status_code == 200
    gone = response.json()
    assert gone["revoked"] is False
    assert "ne permet pas de le révoquer" in gone["message"]
    assert "applications autorisées" in gone["message"]
    assert bitbucket_status(api)["applications_url"] == bitbucket.APPLICATIONS_URL
    assert keychain.passwords == {}  # morceaux compris


def test_an_api_token_pasted(api: TestClient, forges: Any, keychain: MemoryKeyring) -> None:
    response = api.post("/api/accounts/bitbucket/token", json={"token": API_TOKEN})
    assert response.status_code == 201, response.text
    account = response.json()
    assert (account["login"], account["method"], account["access"]) == (
        "ecureuil",
        "token",
        "unknown",
    )
    assert "write:pullrequest:bitbucket" in account["warnings"][0]
    assert keychain.passwords[KEY] == API_TOKEN
    gone = api.delete("/api/accounts/bitbucket").json()
    assert gone["revoked"] is None  # un token collé n'est jamais révoqué


def test_without_its_application_bitbucket_oauth_is_not_offered(
    api: TestClient, forges: Any
) -> None:
    connections(api).apps[ForgeKind.BITBUCKET] = bitbucket.OAuthApp(client_id="", client_secret="")
    assert bitbucket_status(api)["methods"] == ["token"]
    response = api.post("/api/accounts/bitbucket/oauth")
    assert response.status_code == 409
    assert "avec un token" in response.json()["detail"]


# -- les dépôts des deux forges -------------------------------------------------------------


def key(forge: str, host: str, name: str) -> dict[str, str]:
    return {"forge": forge, "host": host, "full_name": name}


HUB = key("github", "github.com", "octo/vulnerable")
CLOUD = key("bitbucket", "bitbucket.org", "ecureuil/vulnerable")


def wait(api: TestClient, url: str, done: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    deadline = time.monotonic() + 30
    while True:
        document: dict[str, Any] = api.get(url).json()
        if done(document):
            return document
        assert time.monotonic() < deadline, f"{url} tourne encore"
        time.sleep(0.05)


def test_one_batch_then_one_proposal_with_bitbucket(
    api: TestClient, forges: Any, finished: Finished, npm_uv: FakeTools
) -> None:
    _, cloud = forges
    connect(api, GITHUB_TOKEN)
    connect_by_oauth(api, cloud)
    document = api.get("/api/repositories").json()
    assert [(a["forge"], a["repositories"]) for a in document["accounts"]] == [
        ("github", 1),
        ("bitbucket", 2),
    ]
    rows = {(row["forge"], row["full_name"]): row for row in document["repositories"]}
    row = rows[("bitbucket", "ecureuil/vulnerable")]
    assert row["url"] == "https://bitbucket.org/ecureuil/vulnerable" and row["can_push"]
    assert document["accounts"][1]["rate_limit"] is None  # Bitbucket ne dit rien

    started = api.post("/api/repositories/batches", json={"repositories": [HUB, CLOUD]})
    assert started.status_code == 202, started.text
    for scan_id in started.json()["scans"]:
        finished(f"/api/scans/{scan_id}")
    rows = {
        (r["forge"], r["full_name"]): r for r in api.get("/api/repositories").json()["repositories"]
    }
    assert rows[("bitbucket", "ecureuil/vulnerable")]["state"] == "to_update"
    assert {item.split(":")[1] for item in cloud.files()} == {
        "package.json",
        "package-lock.json",
        "requirements.txt",
        "requirements.in",
    }

    wanted = [{**HUB, "selection": None}, {**CLOUD, "selection": None}]
    proposal = api.post("/api/proposals", json={"repositories": wanted})
    assert proposal.status_code == 201, proposal.text
    items = {item["forge"]: item for item in proposal.json()["repositories"]}
    assert items["bitbucket"]["state"] == "ready" and items["bitbucket"]["request"] is None

    url = f"/api/proposals/{proposal.json()['id']}"
    assert api.post(f"{url}/send", json={"repositories": [HUB, CLOUD]}).status_code == 202
    done = wait(api, url, lambda d: d["status"] == "done")
    sent = {item["forge"]: item for item in done["repositories"]}
    assert sent["github"]["state"] == "opened"
    assert sent["bitbucket"]["state"] == "opened", sent["bitbucket"]["error"]
    assert sent["bitbucket"]["request"]["number"] == 1
    assert sent["bitbucket"]["request"]["url"].endswith("/ecureuil/vulnerable/pull-requests/1")
    repo = cloud.repositories["ecureuil/vulnerable"]
    assert repo.remote is not None
    author = git(repo.remote, "log", "-1", "--format=%an <%ae>", BRANCH).strip()
    assert author == "Écureuil Roux <ecureuil@example.org>"
    assert "Relancer forceupdate met à jour cette PR" in cloud.pull("ecureuil/vulnerable").body
    pushed = git(repo.remote, "rev-parse", BRANCH).strip()

    # Relancer : la même PR, rien de poussé (même contenu : l'arbre lu par git le dit).
    again = api.post("/api/proposals", json={"repositories": [{**CLOUD, "selection": None}]})
    assert again.json()["repositories"][0]["request"]["number"] == 1
    url = f"/api/proposals/{again.json()['id']}"
    assert api.post(f"{url}/send", json={"repositories": [CLOUD]}).status_code == 202
    redone = wait(api, url, lambda d: d["status"] == "done")["repositories"][0]
    assert redone["state"] == "updated", redone["error"]
    assert not redone["pushed"]
    assert git(repo.remote, "rev-parse", BRANCH).strip() == pushed
    assert len(repo.pulls) == 1
    assert api.get("/api/repositories").json()["synthesis"]["open_requests"] == 2


def test_a_public_bitbucket_repository_by_its_address(
    api: TestClient, forges: Any, finished: Finished
) -> None:
    _, cloud = forges
    cloud.repositories["ecureuil/a-jour"].member = False
    response = api.post(
        "/api/repositories/scans",
        json={"repository": "https://bitbucket.org/ecureuil/a-jour/src/main/"},
    )
    assert response.status_code == 202, response.text
    done = finished(f"/api/scans/{response.json()['id']}")
    assert done["repository"]["forge"] == "bitbucket"
    assert done["repository"]["full_name"] == "ecureuil/a-jour"
    assert all("authorization" not in r.headers for r in cloud.requests)


def test_responses_follow_the_exported_schema(api: TestClient, forges: Any) -> None:
    from test_web_server import conforms

    _, cloud = forges
    schema = json.loads(openapi.OPENAPI_JSON.read_text(encoding="utf-8"))
    components = schema["components"]["schemas"]

    def check(value: Any, name: str) -> None:
        assert conforms(value, {"$ref": f"#/components/schemas/{name}"}, components) == []

    connect_by_oauth(api, cloud)
    check(api.get("/api/accounts").json(), "AccountList")
    check(api.get("/api/repositories").json(), "RepositoryList")
    check(api.delete("/api/accounts/bitbucket").json(), "Disconnection")
