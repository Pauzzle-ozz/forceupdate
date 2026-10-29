"""GitLab dans l'interface (E19) : la connexion d'un compte gitlab.com par OAuth (PKCE, sans
secret), son token renouvelé quand il expire, la déconnexion qui le révoque ; une instance
auto-hébergée par son adresse et un token ; plusieurs comptes à la fois ; puis les dépôts de
GitHub et de GitLab listés, analysés dans un même lot, et un même récapitulatif qui ouvre une PR
sur GitHub et une MR sur GitLab, mise à jour en relançant.

GitHub et GitLab sont simulés (``fake_forge``, ``fake_gitlab``) ; git clone et pousse vers des
dépôts « bare » du dossier du test ; npm et uv sont simulés ; les registres et OSV répondent
avec les réponses enregistrées ; le trousseau est en mémoire."""

import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from conftest import API_PORT, FakeTools, MemoryKeyring, recorded_responses
from fake_forge import (
    FakeGitHubRepos,
    FakeRepo,
    from_directory,
    git,
    make_remote,
    remotes_url,
)
from fake_gitlab import FakeGitLab, FakeToken
from fastapi.testclient import TestClient
from test_update_forge import tools
from test_web_repositories import Finished, connect

from forceupdate.forges import git as forge_git
from forceupdate.forges import github as github_module
from forceupdate.forges import gitlab
from forceupdate.forges.base import ForgeKind
from forceupdate.net import http as http_module
from forceupdate.update.forge import BRANCH
from forceupdate.web import openapi
from forceupdate.web.connections import Connections

PROJECTS = Path(__file__).parent / "projects"
GITHUB_TOKEN = "gho_depots"
PAT = "glpat-instance"
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
) -> Iterator[tuple[FakeGitHubRepos, FakeGitLab, FakeGitLab]]:
    """GitHub, gitlab.com et une instance (``git.example.com``), chacun avec ses dépôts."""
    monkeypatch.setattr(http_module, "_backoff", lambda attempt: 0.0)
    remotes = tmp_path / "distants"
    hub = FakeGitHubRepos(
        [from_directory("octo/vulnerable", PROJECTS / "vulnerable", private=True)],
        tokens={GITHUB_TOKEN},
        user={"login": "octo", "id": 583231, "name": "Octo Cat"},
    )
    lab = FakeGitLab(
        repos=[
            from_directory("renard/outils/vulnerable", PROJECTS / "vulnerable", private=True),
            FakeRepo(full_name="renard/a-jour", files={"requirements.txt": b"werkzeug==3.1.9\n"}),
        ],
        tokens={},
    )
    instance = FakeGitLab(
        host="git.example.com",
        repos=[FakeRepo(full_name="equipe/app", files={"requirements.txt": b"flask==0.12\n"})],
        tokens={PAT: FakeToken(expires_at="2027-03-01")},
    )
    for repo in [*hub.repos.values(), *lab.projects.values()]:
        make_remote(repo, remotes)
    monkeypatch.setattr(github_module, "GIT_URL", remotes_url(remotes))
    monkeypatch.setattr(gitlab, "GIT_URL", remotes_url(remotes))
    connections(api).apps[ForgeKind.GITLAB] = gitlab.OAuthApp(client_id=lab.client_id)

    def routes(router: Any) -> None:
        hub.routes(router)
        lab.routes(router)
        instance.routes(router)

    with recorded_responses(extra=routes):
        yield hub, lab, instance


@pytest.fixture
def npm_uv(fake_tools: Callable[..., FakeTools]) -> FakeTools:
    return tools(fake_tools, "npm", "uv")


def gitlab_status(api: TestClient) -> dict[str, Any]:
    found: dict[str, Any] = api.get("/api/accounts").json()["forges"][1]
    assert found["forge"] == "gitlab"
    return found


def connect_by_oauth(api: TestClient, lab: FakeGitLab) -> dict[str, Any]:
    """Se connecte à gitlab.com par OAuth : la page d'autorisation, puis le retour."""
    started = api.post("/api/accounts/gitlab/oauth")
    assert started.status_code == 201, started.text
    query = parse_qs(urlsplit(started.json()["authorize_url"]).query)
    code = lab.code_for(query["code_challenge"][0])
    response = api.get(
        f"/oauth/gitlab/callback?code={code}&state={query['state'][0]}",
        headers={**CROSS_SITE, "Authorization": ""},
        follow_redirects=False,
    )
    assert response.status_code == 200
    done: dict[str, Any] = api.get(f"/api/accounts/connections/{started.json()['id']}").json()
    assert done["status"] == "done", done
    return done


# -- les comptes ------------------------------------------------------------------------


def test_connect_gitlab_by_oauth(api: TestClient, forges: Any, keychain: MemoryKeyring) -> None:
    _, lab, _ = forges
    started = api.post("/api/accounts/gitlab/oauth").json()
    parts = urlsplit(started["authorize_url"])
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == gitlab.AUTHORIZE_URL
    query = parse_qs(parts.query)
    assert query["redirect_uri"] == [f"http://127.0.0.1:{API_PORT}/oauth/gitlab/callback"]
    assert query["scope"] == ["api"]
    assert query["code_challenge_method"] == ["S256"]

    done = connect_by_oauth(api, lab)
    account = done["account"]
    assert (account["forge"], account["host"], account["login"]) == (
        "gitlab",
        "gitlab.com",
        "renard",
    )
    assert account["access"] == "write"
    assert account["method"] == "oauth"
    stored = json.loads(keychain.passwords[("forceupdate", "gitlab:gitlab.com")])
    assert set(stored) == {"access_token", "refresh_token", "expires_at"}
    exchange = next(r for r in lab.requests if r.url.path == "/oauth/token")
    assert "client_secret" not in json.loads(exchange.content)  # PKCE, pas de secret
    status = gitlab_status(api)
    assert status["account"]["login"] == "renard"
    assert status["instances"] == []
    assert stored["access_token"] not in api.get("/api/accounts").text


def test_an_expired_token_is_renewed_then_revoked_at_disconnection(
    api: TestClient, forges: Any, keychain: MemoryKeyring
) -> None:
    _, lab, _ = forges
    connect_by_oauth(api, lab)
    first = json.loads(keychain.passwords[("forceupdate", "gitlab:gitlab.com")])
    lab.expire(first["access_token"])  # 2 h ont passé
    checked = api.post("/api/accounts/gitlab/verify")
    assert checked.status_code == 200
    assert checked.json()["problem"] is None
    second = json.loads(keychain.passwords[("forceupdate", "gitlab:gitlab.com")])
    assert second["access_token"] != first["access_token"]
    assert second["refresh_token"] != first["refresh_token"]
    # Le refresh token, une fois servi, ne sert plus : un refus est dit sur le compte.
    lab.expire(second["access_token"])
    lab.grants[-1].used = True
    refused = api.post("/api/accounts/gitlab/verify").json()
    assert "se reconnecter" in refused["problem"]

    response = api.delete("/api/accounts/gitlab")
    assert response.status_code == 200
    assert response.json()["host"] == "gitlab.com"
    assert response.json()["revoked"] is True
    assert lab.revoked == [second["access_token"]]
    assert ("forceupdate", "gitlab:gitlab.com") not in keychain.passwords


def test_a_self_hosted_instance_by_its_address(
    api: TestClient, forges: Any, keychain: MemoryKeyring
) -> None:
    _, _, instance = forges
    response = api.post(
        "/api/accounts/gitlab/token", json={"token": PAT, "url": "https://Git.Example.com/"}
    )
    assert response.status_code == 201, response.text
    account = response.json()
    assert (account["host"], account["method"]) == ("git.example.com", "token")
    assert account["warnings"] == [
        "Ce token expire le 01/03/2027 : il faudra en coller un nouveau."
    ]
    assert keychain.passwords[("forceupdate", "gitlab:git.example.com")] == PAT
    status = gitlab_status(api)
    assert status["account"] is None
    assert [a["host"] for a in status["instances"]] == ["git.example.com"]
    verified = api.post("/api/accounts/gitlab/verify", params={"host": "git.example.com"})
    assert verified.status_code == 200
    assert api.post("/api/accounts/gitlab/verify").status_code == 404  # pas de gitlab.com
    gone = api.delete("/api/accounts/gitlab", params={"host": "git.example.com"})
    assert gone.json()["revoked"] is None  # un token collé n'est jamais révoqué
    assert instance.revoked == []


@pytest.mark.parametrize(
    "url",
    [
        "http://git.example.com",
        "https://git.example.com/gitlab",
        "https://moi:secret@git.example.com",
        "https://git.example.com/?a=b",
        "https://git.example.com:huit",
    ],
)
def test_an_instance_address_refused(api: TestClient, forges: Any, url: str) -> None:
    response = api.post("/api/accounts/gitlab/token", json={"token": PAT, "url": url})
    assert response.status_code == 400
    assert "Adresse d'instance refusée" in response.json()["detail"]


def test_no_device_flow_on_gitlab(api: TestClient, forges: Any) -> None:
    response = api.post("/api/accounts/gitlab/device")
    assert response.status_code == 400


def test_without_its_application_gitlab_oauth_is_not_offered(api: TestClient, forges: Any) -> None:
    connections(api).apps[ForgeKind.GITLAB] = gitlab.OAuthApp(client_id="")
    assert gitlab_status(api)["methods"] == ["token"]
    response = api.post("/api/accounts/gitlab/oauth")
    assert response.status_code == 409
    assert "avec un token" in response.json()["detail"]


# -- les dépôts des deux forges -------------------------------------------------------------


def connect_all(api: TestClient, lab: FakeGitLab) -> None:
    connect(api, GITHUB_TOKEN)
    connect_by_oauth(api, lab)
    assert (
        api.post(
            "/api/accounts/gitlab/token", json={"token": PAT, "url": "https://git.example.com"}
        ).status_code
        == 201
    )


def key(forge: str, host: str, name: str) -> dict[str, str]:
    return {"forge": forge, "host": host, "full_name": name}


HUB = key("github", "github.com", "octo/vulnerable")
LAB = key("gitlab", "gitlab.com", "renard/outils/vulnerable")
INSTANCE = key("gitlab", "git.example.com", "equipe/app")


def wait(api: TestClient, url: str, done: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    deadline = time.monotonic() + 30
    while True:
        document: dict[str, Any] = api.get(url).json()
        if done(document):
            return document
        assert time.monotonic() < deadline, f"{url} tourne encore"
        time.sleep(0.05)


def test_the_repositories_of_every_account(api: TestClient, forges: Any) -> None:
    _, lab, _ = forges
    connect_all(api, lab)
    document = api.get("/api/repositories").json()
    assert [(a["forge"], a["host"], a["repositories"]) for a in document["accounts"]] == [
        ("github", "github.com", 1),
        ("gitlab", "gitlab.com", 2),
        ("gitlab", "git.example.com", 1),
    ]
    rows = {(row["host"], row["full_name"]): row for row in document["repositories"]}
    nested = rows[("gitlab.com", "renard/outils/vulnerable")]
    assert (nested["owner"], nested["name"]) == ("renard/outils", "vulnerable")
    assert nested["url"] == "https://gitlab.com/renard/outils/vulnerable"
    assert nested["can_push"]
    assert all(row["state"] == "not_scanned" for row in rows.values())


def test_one_batch_then_one_proposal_across_forges(
    api: TestClient, forges: Any, finished: Finished, npm_uv: FakeTools
) -> None:
    _, lab, _ = forges
    connect_all(api, lab)
    api.get("/api/repositories")
    started = api.post("/api/repositories/batches", json={"repositories": [HUB, LAB, INSTANCE]})
    assert started.status_code == 202, started.text
    batch = started.json()
    for scan_id in batch["scans"]:
        finished(f"/api/scans/{scan_id}")
    batch = api.get(f"/api/repositories/batches/{batch['id']}").json()
    assert (batch["total"], batch["failed"]) == (3, 0)
    rows = {
        (r["host"], r["full_name"]): r for r in api.get("/api/repositories").json()["repositories"]
    }
    assert rows[("gitlab.com", "renard/outils/vulnerable")]["state"] == "to_update"
    assert rows[("git.example.com", "equipe/app")]["state"] == "to_update"
    # Seuls les fichiers de dépendances ont été téléchargés de GitLab.
    assert {item.split(":")[1] for item in lab.files()} == {
        "package.json",
        "package-lock.json",
        "requirements.txt",
        "requirements.in",
    }

    wanted = [{**HUB, "selection": None}, {**LAB, "selection": None}]
    proposal = api.post("/api/proposals", json={"repositories": wanted})
    assert proposal.status_code == 201, proposal.text
    items = {item["forge"]: item for item in proposal.json()["repositories"]}
    assert items["github"]["state"] == items["gitlab"]["state"] == "ready"
    assert items["gitlab"]["request"] is None

    def send() -> dict[str, Any]:
        url = f"/api/proposals/{proposal.json()['id']}"
        response = api.post(f"{url}/send", json={"repositories": [HUB, LAB]})
        assert response.status_code == 202, response.text
        return wait(api, url, lambda d: d["status"] == "done")

    done = send()
    sent = {item["forge"]: item for item in done["repositories"]}
    assert sent["github"]["state"] == "opened"
    assert sent["gitlab"]["state"] == "opened", sent["gitlab"]["error"]
    assert sent["gitlab"]["request"]["number"] == 1
    assert sent["gitlab"]["request"]["url"].endswith("/renard/outils/vulnerable/-/merge_requests/1")
    project = lab.projects["renard/outils/vulnerable"]
    assert project.remote is not None
    author = git(project.remote, "log", "-1", "--format=%an <%ae>", BRANCH).strip()
    assert author == "Renard Roux <4242-renard@users.noreply.gitlab.com>"
    request = lab.request("renard/outils/vulnerable")
    assert "Relancer forceupdate met à jour cette MR" in request.body
    pushed = git(project.remote, "rev-parse", BRANCH).strip()

    # Relancer : la même MR, rien de poussé (même contenu : l'arbre recalculé le dit).
    again = api.post("/api/proposals", json={"repositories": [{**LAB, "selection": None}]}).json()
    assert again["repositories"][0]["request"]["number"] == 1
    url = f"/api/proposals/{again['id']}"
    assert api.post(f"{url}/send", json={"repositories": [LAB]}).status_code == 202
    redone = wait(api, url, lambda d: d["status"] == "done")["repositories"][0]
    assert redone["state"] == "updated", redone["error"]
    assert not redone["pushed"]
    assert git(project.remote, "rev-parse", BRANCH).strip() == pushed
    assert len(project.pulls) == 1
    listing = api.get("/api/repositories").json()
    assert listing["synthesis"]["open_requests"] == 2


def test_a_public_gitlab_project_by_its_address(
    api: TestClient, forges: Any, finished: Finished
) -> None:
    _, lab, _ = forges
    lab.projects["renard/a-jour"].member = False
    response = api.post(
        "/api/repositories/scans",
        json={"repository": "https://gitlab.com/renard/a-jour/-/tree/main"},
    )
    assert response.status_code == 202, response.text
    done = finished(f"/api/scans/{response.json()['id']}")
    assert done["repository"]["forge"] == "gitlab"
    assert done["repository"]["full_name"] == "renard/a-jour"
    assert all("authorization" not in r.headers for r in lab.requests)


def test_responses_follow_the_exported_schema(api: TestClient, forges: Any) -> None:
    from test_web_server import conforms

    _, lab, _ = forges
    schema = json.loads(openapi.OPENAPI_JSON.read_text(encoding="utf-8"))
    components = schema["components"]["schemas"]

    def check(value: Any, name: str) -> None:
        assert conforms(value, {"$ref": f"#/components/schemas/{name}"}, components) == []

    connect_all(api, lab)
    check(api.get("/api/accounts").json(), "AccountList")
    check(api.get("/api/repositories").json(), "RepositoryList")
    check(
        api.delete("/api/accounts/gitlab", params={"host": "git.example.com"}).json(),
        "Disconnection",
    )
