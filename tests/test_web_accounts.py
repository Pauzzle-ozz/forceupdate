"""L'API des comptes (``web.routes.accounts``), l'adresse de retour d'OAuth
(``web.routes.oauth``) et les connexions en cours (``web.connections``). GitHub est simulé
(``FakeGitHub``), le trousseau est en mémoire (``conftest.keychain``)."""

import json
import re
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import keyring.backend
import keyring.core
import keyring.errors
import pytest
import respx
from conftest import API_PORT, MemoryKeyring
from fastapi.testclient import TestClient

from forceupdate.forges import bitbucket, github, gitlab
from forceupdate.forges.base import ForgeKind
from forceupdate.net import http as http_module
from forceupdate.web.connections import Connections

GOOD = "gho_bon"
FINE = "github_pat_fin"
OAUTH_TOKEN = "gho_oauth"
DEVICE_TOKEN = "gho_device"
GH_TOKEN = "gho_du_gh"
KEY = ("forceupdate", "github:github.com")
CROSS_SITE = {
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
}


class FakeGitHub:
    """GitHub simulé : ``/user`` selon le token, l'échange du code, le device flow, la
    révocation."""

    def __init__(self, router: respx.MockRouter) -> None:
        self.scopes: dict[str, str | None] = {
            GOOD: "repo, read:org",
            OAUTH_TOKEN: "repo, read:org",
            DEVICE_TOKEN: "repo, read:org",
            GH_TOKEN: "repo, read:org, gist",
            FINE: None,
        }
        self.codes = {"code-bon": OAUTH_TOKEN}
        self.device_answers: list[dict[str, Any]] = [
            {"error": "authorization_pending"},
            {"access_token": DEVICE_TOKEN},
        ]
        self.device_code: dict[str, Any] = {
            "device_code": "code-appareil",
            "user_code": "WDJB-MJHT",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 0,
        }
        self.revoked: list[str] = []
        self.user = router.get("https://api.github.com/user").mock(side_effect=self._user)
        self.token = router.post("https://github.com/login/oauth/access_token").mock(
            side_effect=self._token
        )
        self.device = router.post("https://github.com/login/device/code").mock(
            side_effect=lambda request: httpx.Response(200, json=self.device_code)
        )
        self.revoke = router.delete(
            f"https://api.github.com/applications/{github.CLIENT_ID}/token"
        ).mock(side_effect=self._revoke)

    def _user(self, request: httpx.Request) -> httpx.Response:
        token = request.headers["Authorization"].removeprefix("Bearer ")
        if token not in self.scopes:
            return httpx.Response(401, json={"message": "Bad credentials"})
        scopes = self.scopes[token]
        headers = {} if scopes is None else {"X-OAuth-Scopes": scopes}
        return httpx.Response(
            200,
            json={"login": "octo", "name": "Octo Cat", "html_url": "https://github.com/octo"},
            headers=headers,
        )

    def _token(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "device_code" in body:
            answer = self.device_answers.pop(0) if len(self.device_answers) > 1 else None
            return httpx.Response(200, json=answer or self.device_answers[0])
        token = self.codes.get(body.get("code"))
        if token is None:
            return httpx.Response(200, json={"error": "bad_verification_code"})
        return httpx.Response(200, json={"access_token": token, "scope": "repo,read:org"})

    def _revoke(self, request: httpx.Request) -> httpx.Response:
        self.revoked.append(json.loads(request.content)["access_token"])
        return httpx.Response(204)


@pytest.fixture
def fake_github(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeGitHub]:
    monkeypatch.delenv(github.ENV_CLIENT_ID, raising=False)
    monkeypatch.delenv(github.ENV_CLIENT_SECRET, raising=False)
    monkeypatch.setattr(github, "MIN_INTERVAL", 0.01)
    monkeypatch.setattr(http_module, "_backoff", lambda attempt: 0.0)  # reprises sans attente
    with respx.mock(assert_all_called=False) as router:
        yield FakeGitHub(router)


def connections(api: TestClient) -> Connections:
    found: Connections = api.app.state.connections  # type: ignore[attr-defined]
    return found


def settled(api: TestClient, connection_id: str) -> dict[str, Any]:
    """L'état de la connexion, une fois qu'elle n'attend plus (5 s au plus)."""
    deadline = time.monotonic() + 5
    while True:
        state: dict[str, Any] = api.get(f"/api/accounts/connections/{connection_id}").json()
        if state["status"] != "pending":
            return state
        assert time.monotonic() < deadline, "la connexion attend encore"
        time.sleep(0.02)


def github_status(api: TestClient) -> dict[str, Any]:
    forges = api.get("/api/accounts").json()["forges"]
    found: dict[str, Any] = forges[0]
    assert found["forge"] == "github"
    return found


def no_token_in(*responses: httpx.Response) -> None:
    for response in responses:
        for token in (GOOD, OAUTH_TOKEN, DEVICE_TOKEN, GH_TOKEN, FINE):
            assert token not in response.text


# -- Lister -------------------------------------------------------------------------


def test_the_forges_without_any_account(api: TestClient, fake_github: FakeGitHub) -> None:
    response = api.get("/api/accounts")
    assert response.status_code == 200
    assert response.json() == {
        "keyring": None,
        "forges": [
            {
                "forge": "github",
                "name": "GitHub",
                "host": "github.com",
                "available": True,
                "methods": ["oauth", "device", "token"],
                "scopes": ["repo", "read:org"],
                "token_scopes": ["repo", "read:org"],
                "token_url": github.TOKEN_SETTINGS_URL,
                "revocable": True,
                "applications_url": github.APPLICATIONS_URL,
                "self_hosted": False,
                "request": "PR",
                "account": None,
                "instances": [],
                "connection": None,
            },
            {
                "forge": "gitlab",
                "name": "GitLab",
                "host": "gitlab.com",
                "available": True,
                "methods": ["oauth", "token"],
                "scopes": ["api"],
                "token_scopes": ["api"],
                "token_url": gitlab.token_settings_url(),
                "revocable": True,
                "applications_url": "https://gitlab.com/-/user_settings/applications",
                "self_hosted": True,
                "request": "MR",
                "account": None,
                "instances": [],
                "connection": None,
            },
            {
                "forge": "bitbucket",
                "name": "Bitbucket",
                "host": "bitbucket.org",
                "available": True,
                "methods": ["oauth", "token"],
                "scopes": ["account", "email", "repository:write", "pullrequest:write"],
                "token_scopes": list(bitbucket.API_TOKEN_SCOPES),
                "token_url": bitbucket.TOKEN_SETTINGS_URL,
                "revocable": False,
                "applications_url": bitbucket.APPLICATIONS_URL,
                "self_hosted": False,
                "request": "PR",
                "account": None,
                "instances": [],
                "connection": None,
            },
        ],
    }
    assert fake_github.user.call_count == 0  # lister ne demande rien à GitHub


def test_gh_is_offered_when_installed(
    api: TestClient, fake_github: FakeGitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(github, "_which", lambda program: f"/outils/{program}")
    assert github_status(api)["methods"] == ["oauth", "device", "token", "gh"]


def test_without_the_secret_oauth_is_not_offered(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    connections(api).apps[ForgeKind.GITHUB] = github.OAuthApp(
        client_id="Ov23-autre", client_secret=""
    )
    assert github_status(api)["methods"] == ["device", "token"]
    response = api.post("/api/accounts/github/oauth")
    assert response.status_code == 409
    assert "device flow" in response.json()["detail"]


class BrokenKeyring(keyring.backend.KeyringBackend):
    priority = 1  # type: ignore[assignment]

    def get_password(self, service: str, username: str) -> str | None:
        raise keyring.errors.NoKeyringError("pas de trousseau")

    def set_password(self, service: str, username: str, password: str) -> None:
        raise keyring.errors.NoKeyringError("pas de trousseau")

    def delete_password(self, service: str, username: str) -> None:
        raise keyring.errors.NoKeyringError("pas de trousseau")


def test_a_broken_keyring_is_said(
    api: TestClient, fake_github: FakeGitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(keyring.core, "_keyring_backend", BrokenKeyring())
    listing = api.get("/api/accounts").json()
    assert "Aucun trousseau du système n'est utilisable" in listing["keyring"]
    for path in ("/api/accounts/github/oauth", "/api/accounts/github/device"):
        response = api.post(path)
        assert response.status_code == 409
        assert "trousseau" in response.json()["detail"]
    response = api.post("/api/accounts/github/token", json={"token": GOOD})
    assert response.status_code == 409
    assert fake_github.user.call_count == 0


# -- Token collé, gh ------------------------------------------------------------------


def test_connect_with_a_pasted_token(
    api: TestClient, fake_github: FakeGitHub, keychain: MemoryKeyring
) -> None:
    response = api.post("/api/accounts/github/token", json={"token": f"  {GOOD}\n"})
    assert response.status_code == 201
    account = response.json()
    assert account["login"] == "octo"
    assert account["name"] == "Octo Cat"
    assert account["access"] == "write"
    assert account["scopes"] == ["repo", "read:org"]
    assert account["method"] == "token"
    assert account["warnings"] == []
    assert account["problem"] is None
    assert keychain.passwords == {KEY: GOOD}
    listing = api.get("/api/accounts")
    assert listing.json()["forges"][0]["account"] == account
    no_token_in(response, listing)


def test_a_fine_grained_token_has_unchecked_rights(
    api: TestClient, fake_github: FakeGitHub
) -> None:
    account = api.post("/api/accounts/github/token", json={"token": FINE}).json()
    assert account["access"] == "unknown"
    assert account["scopes"] is None
    assert "fine-grained" in account["warnings"][0]


@pytest.mark.parametrize("token", ["", "   ", "deux mots", "x" * 1025])
def test_not_a_token(api: TestClient, fake_github: FakeGitHub, token: str) -> None:
    response = api.post("/api/accounts/github/token", json={"token": token})
    assert response.status_code == 400
    assert response.json()["detail"].startswith("Ce n'est pas un token")
    assert fake_github.user.call_count == 0


def test_a_refused_token_is_a_400_not_a_401(
    api: TestClient, fake_github: FakeGitHub, keychain: MemoryKeyring
) -> None:
    response = api.post("/api/accounts/github/token", json={"token": "gho_faux"})
    assert response.status_code == 400
    assert response.json()["detail"] == (
        "GitHub refuse le token (401) : révoqué, expiré, ou mal copié. Se reconnecter."
    )
    assert keychain.passwords == {}
    no_token_in(response)
    assert "gho_faux" not in response.text


def test_github_unreachable_is_a_502(api: TestClient, fake_github: FakeGitHub) -> None:
    fake_github.user.mock(side_effect=httpx.ConnectError("coupé"))
    response = api.post("/api/accounts/github/token", json={"token": GOOD})
    assert response.status_code == 502
    assert response.json()["detail"].startswith("GitHub ne répond pas : api.github.com")


def test_a_rate_limit_is_a_409(api: TestClient, fake_github: FakeGitHub) -> None:
    fake_github.user.mock(
        return_value=httpx.Response(
            403,
            json={"message": "API rate limit exceeded"},
            headers={
                "X-RateLimit-Limit": "60",
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": "1793208000",
            },
        )
    )
    response = api.post("/api/accounts/github/token", json={"token": GOOD})
    assert response.status_code == 409
    assert "Limite de l'API GitHub atteinte (60 requêtes par heure)" in response.json()["detail"]


def test_connect_with_gh(
    api: TestClient,
    fake_github: FakeGitHub,
    keychain: MemoryKeyring,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def run(command: list[str], **options: Any) -> Any:
        calls.append(command)
        return type("Done", (), {"returncode": 0, "stdout": f"{GH_TOKEN}\n".encode()})()

    monkeypatch.setattr(github, "_which", lambda program: f"/outils/{program}")
    monkeypatch.setattr(github, "_run", run)
    response = api.post("/api/accounts/github/gh")
    assert response.status_code == 201
    assert response.json()["method"] == "gh"
    assert keychain.passwords == {KEY: GH_TOKEN}
    assert calls == [["/outils/gh", "auth", "token", "--hostname", "github.com"]]
    no_token_in(response)


def test_gh_not_installed(api: TestClient, fake_github: FakeGitHub) -> None:
    response = api.post("/api/accounts/github/gh")
    assert response.status_code == 400
    assert response.json()["detail"] == "GitHub CLI (gh) n'est pas installé."


def test_bitbucket_has_neither_device_flow_nor_gh(api: TestClient) -> None:
    response = api.post("/api/accounts/bitbucket/device")
    assert response.status_code == 400
    assert "pas de connexion par code" in response.json()["detail"]
    assert api.post("/api/accounts/bitbucket/gh").status_code == 400
    response = api.post(
        "/api/accounts/bitbucket/token", json={"token": GOOD, "url": "https://bb.example.com"}
    )
    assert response.status_code == 400
    assert "pas d'instance auto-hébergée" in response.json()["detail"]


def test_github_has_no_self_hosted_instance(api: TestClient, fake_github: FakeGitHub) -> None:
    response = api.post(
        "/api/accounts/github/token", json={"token": GOOD, "url": "https://ghe.example.com"}
    )
    assert response.status_code == 400
    assert "pas d'instance auto-hébergée" in response.json()["detail"]


def test_an_unknown_forge(api: TestClient) -> None:
    assert api.post("/api/accounts/sourceforge/oauth").status_code == 422


# -- Vérifier, déconnecter ------------------------------------------------------------


def test_verify(api: TestClient, fake_github: FakeGitHub) -> None:
    connected = api.post("/api/accounts/github/token", json={"token": GOOD}).json()
    fake_github.scopes[GOOD] = "public_repo"
    response = api.post("/api/accounts/github/verify")
    assert response.status_code == 200
    account = response.json()
    assert account["access"] == "public"
    assert account["checked_at"] >= connected["checked_at"]
    assert account["connected_at"] == connected["connected_at"]


def test_verify_says_when_the_token_was_revoked(api: TestClient, fake_github: FakeGitHub) -> None:
    api.post("/api/accounts/github/token", json={"token": GOOD})
    del fake_github.scopes[GOOD]  # révoqué sur github.com
    response = api.post("/api/accounts/github/verify")
    assert response.status_code == 200
    assert "GitHub refuse le token (401)" in response.json()["problem"]
    assert "GitHub refuse le token" in github_status(api)["account"]["problem"]


def test_verify_without_an_account_or_without_github(
    api: TestClient, fake_github: FakeGitHub
) -> None:
    assert api.post("/api/accounts/github/verify").status_code == 404
    api.post("/api/accounts/github/token", json={"token": GOOD})
    fake_github.user.mock(side_effect=httpx.ConnectError("coupé"))
    response = api.post("/api/accounts/github/verify")
    assert response.status_code == 502
    assert github_status(api)["account"]["login"] == "octo"  # le compte reste


def test_disconnect_a_pasted_token_does_not_revoke_it(
    api: TestClient, fake_github: FakeGitHub, keychain: MemoryKeyring
) -> None:
    api.post("/api/accounts/github/token", json={"token": GOOD})
    response = api.delete("/api/accounts/github")
    assert response.status_code == 200
    assert response.json() == {
        "forge": "github",
        "host": "github.com",
        "login": "octo",
        "revoked": None,
        "message": "Déconnecté de GitHub : token effacé de cet ordinateur. Il reste valable "
        "sur GitHub (il n'appartient pas à forceupdate).",
    }
    assert keychain.passwords == {}
    assert fake_github.revoked == []
    assert github_status(api)["account"] is None
    assert api.delete("/api/accounts/github").status_code == 404


def test_disconnect_revokes_a_token_given_to_forceupdate(
    api: TestClient, fake_github: FakeGitHub, keychain: MemoryKeyring
) -> None:
    connection = api.post("/api/accounts/github/device").json()
    assert settled(api, connection["id"])["status"] == "done"
    response = api.delete("/api/accounts/github")
    assert response.json()["revoked"] is True
    assert response.json()["message"] == (
        "Déconnecté de GitHub : token effacé de cet ordinateur et révoqué."
    )
    assert fake_github.revoked == [DEVICE_TOKEN]
    assert keychain.passwords == {}
    no_token_in(response)


def test_disconnect_when_github_cannot_revoke(
    api: TestClient, fake_github: FakeGitHub, keychain: MemoryKeyring
) -> None:
    connection = api.post("/api/accounts/github/device").json()
    settled(api, connection["id"])
    fake_github.revoke.mock(side_effect=httpx.ConnectError("coupé"))
    response = api.delete("/api/accounts/github")
    assert response.status_code == 200
    assert response.json()["revoked"] is False
    assert "https://github.com/settings/applications" in response.json()["message"]
    assert keychain.passwords == {}  # effacé quand même


# -- OAuth ----------------------------------------------------------------------------


def start_oauth(api: TestClient) -> tuple[dict[str, Any], str]:
    response = api.post("/api/accounts/github/oauth")
    assert response.status_code == 201
    connection = response.json()
    query = parse_qs(urlsplit(connection["authorize_url"]).query)
    return connection, query["state"][0]


def callback(api: TestClient, query: str) -> httpx.Response:
    """Le retour de github.com : une navigation d'un autre site, sans le jeton de session."""
    return api.get(
        f"/oauth/github/callback?{query}",
        headers={**CROSS_SITE, "Authorization": ""},
        follow_redirects=False,
    )


def test_start_oauth(api: TestClient, fake_github: FakeGitHub) -> None:
    connection, state = start_oauth(api)
    assert connection["method"] == "oauth"
    assert connection["status"] == "pending"
    parts = urlsplit(connection["authorize_url"])
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == github.AUTHORIZE_URL
    query = parse_qs(parts.query)
    assert query["redirect_uri"] == [f"http://127.0.0.1:{API_PORT}/oauth/github/callback"]
    assert query["client_id"] == [github.CLIENT_ID]
    assert query["code_challenge_method"] == ["S256"]
    assert len(state) >= 43
    expires = datetime.fromisoformat(connection["expires_at"])
    assert timedelta(minutes=9) < expires - datetime.now(UTC) <= timedelta(minutes=10)
    assert github_status(api)["connection"]["id"] == connection["id"]


def test_oauth_needs_the_127_0_0_1_address(api: TestClient, fake_github: FakeGitHub) -> None:
    response = api.post("/api/accounts/github/oauth", headers={"Host": f"localhost:{API_PORT}"})
    assert response.status_code == 409
    assert f"http://127.0.0.1:{API_PORT}" in response.json()["detail"]


def test_the_oauth_return_connects_the_account(
    api: TestClient, fake_github: FakeGitHub, keychain: MemoryKeyring
) -> None:
    connection, state = start_oauth(api)
    response = callback(api, f"code=code-bon&state={state}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    target = f"/comptes?connexion={connection['id']}"
    assert f'<meta http-equiv="refresh" content="0; url={target}">' in response.text
    assert f'<a href="{target}">' in response.text
    assert "code-bon" not in response.text
    exchange = json.loads(fake_github.token.calls.last.request.content)
    assert exchange["code"] == "code-bon"
    assert exchange["redirect_uri"] == f"http://127.0.0.1:{API_PORT}/oauth/github/callback"
    assert re.fullmatch(r"[A-Za-z0-9_-]{43,128}", exchange["code_verifier"])
    assert keychain.passwords == {KEY: OAUTH_TOKEN}
    done = api.get(f"/api/accounts/connections/{connection['id']}").json()
    assert done["status"] == "done"
    assert done["account"]["method"] == "oauth"
    assert done["authorize_url"] is None
    assert github_status(api)["connection"] is None
    no_token_in(response)


def test_a_state_serves_once(api: TestClient, fake_github: FakeGitHub) -> None:
    _, state = start_oauth(api)
    callback(api, f"code=code-bon&state={state}")
    again = callback(api, f"code=code-bon&state={state}")
    assert again.status_code == 400
    assert "Lien de connexion inconnu ou déjà utilisé." in again.text
    assert 'url=/comptes"' in again.text
    assert fake_github.token.call_count == 1


@pytest.mark.parametrize("query", ["code=code-bon&state=faux", "code=code-bon", ""])
def test_an_unknown_state_does_nothing(
    api: TestClient, fake_github: FakeGitHub, keychain: MemoryKeyring, query: str
) -> None:
    connection, _ = start_oauth(api)
    response = callback(api, query)
    assert response.status_code == 400
    assert fake_github.token.call_count == 0
    assert keychain.passwords == {}
    assert api.get(f"/api/accounts/connections/{connection['id']}").json()["status"] == "pending"


def test_an_authorization_refused_on_github(api: TestClient, fake_github: FakeGitHub) -> None:
    connection, state = start_oauth(api)
    response = callback(api, f"error=access_denied&error_description=The+user+denied&state={state}")
    assert response.status_code == 200
    failed = api.get(f"/api/accounts/connections/{connection['id']}").json()
    assert failed["status"] == "failed"
    assert failed["error"] == "Autorisation refusée sur GitHub."
    assert fake_github.token.call_count == 0


def test_a_code_github_refuses(api: TestClient, fake_github: FakeGitHub) -> None:
    connection, state = start_oauth(api)
    callback(api, f"code=code-perime&state={state}")
    failed = api.get(f"/api/accounts/connections/{connection['id']}").json()
    assert failed["status"] == "failed"
    assert failed["error"].startswith("Le code d'autorisation a expiré ou a déjà servi")


def test_a_late_return_is_expired(api: TestClient, fake_github: FakeGitHub) -> None:
    connection, state = start_oauth(api)
    pending = connections(api).get(connection["id"])
    assert pending is not None
    pending.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    response = callback(api, f"code=code-bon&state={state}")
    assert response.status_code == 200
    expired = api.get(f"/api/accounts/connections/{connection['id']}").json()
    assert expired["status"] == "expired"
    assert expired["error"] == "La demande de connexion a expiré (10 min) : recommencer."
    assert fake_github.token.call_count == 0


def test_a_new_connection_replaces_the_pending_one(
    api: TestClient, fake_github: FakeGitHub
) -> None:
    first, first_state = start_oauth(api)
    second, _ = start_oauth(api)
    assert api.get(f"/api/accounts/connections/{first['id']}").json()["status"] == "cancelled"
    assert callback(api, f"code=code-bon&state={first_state}").status_code == 400
    assert github_status(api)["connection"]["id"] == second["id"]


# -- Device flow ----------------------------------------------------------------------


def test_the_device_flow(api: TestClient, fake_github: FakeGitHub, keychain: MemoryKeyring) -> None:
    response = api.post("/api/accounts/github/device")
    assert response.status_code == 201
    connection = response.json()
    assert response.headers["location"] == f"/api/accounts/connections/{connection['id']}"
    assert connection["method"] == "device"
    assert connection["user_code"] == "WDJB-MJHT"
    assert connection["verification_uri"] == "https://github.com/login/device"
    assert connection["interval"] == 0
    assert "code-appareil" not in response.text
    done = settled(api, connection["id"])
    assert done["status"] == "done"
    assert done["account"]["method"] == "device"
    assert keychain.passwords == {KEY: DEVICE_TOKEN}
    no_token_in(response, api.get(f"/api/accounts/connections/{connection['id']}"))


def test_a_pending_device_flow_is_listed_and_can_be_cancelled(
    api: TestClient, fake_github: FakeGitHub, keychain: MemoryKeyring
) -> None:
    fake_github.device_answers = [{"error": "authorization_pending"}]
    connection = api.post("/api/accounts/github/device").json()
    listed = github_status(api)["connection"]
    assert (listed["id"], listed["user_code"]) == (connection["id"], "WDJB-MJHT")
    cancelled = api.delete(f"/api/accounts/connections/{connection['id']}")
    assert cancelled.json()["status"] == "cancelled"
    assert settled(api, connection["id"])["status"] == "cancelled"
    assert github_status(api)["connection"] is None
    assert keychain.passwords == {}


@pytest.mark.parametrize(
    ("answer", "status", "error"),
    [
        ({"error": "access_denied"}, "failed", "Autorisation refusée sur GitHub."),
        ({"error": "expired_token"}, "expired", "Le code a expiré avant d'être saisi"),
    ],
)
def test_a_device_flow_that_ends_badly(
    api: TestClient, fake_github: FakeGitHub, answer: dict[str, str], status: str, error: str
) -> None:
    fake_github.device_answers = [answer]
    connection = api.post("/api/accounts/github/device").json()
    ended = settled(api, connection["id"])
    assert ended["status"] == status
    assert ended["error"].startswith(error)


def test_a_device_code_that_expires(api: TestClient, fake_github: FakeGitHub) -> None:
    fake_github.device_code["expires_in"] = 0
    connection = api.post("/api/accounts/github/device").json()
    assert settled(api, connection["id"])["status"] == "expired"


def test_a_device_code_github_refuses(api: TestClient, fake_github: FakeGitHub) -> None:
    fake_github.device_code = {"error": "device_flow_disabled"}
    response = api.post("/api/accounts/github/device")
    assert response.status_code == 400
    assert response.json()["detail"].startswith("Le device flow n'est pas activé")
    fake_github.device.mock(side_effect=httpx.ConnectError("coupé"))
    response = api.post("/api/accounts/github/device")
    assert response.status_code == 502


def test_an_unknown_connection(api: TestClient) -> None:
    assert api.get("/api/accounts/connections/abc").status_code == 404
    assert api.delete("/api/accounts/connections/abc").status_code == 404


def test_device_flows_stop_with_the_server(web_settings: Any, fake_github: FakeGitHub) -> None:
    from conftest import API_BASE, API_TOKEN

    from forceupdate.web import create_app

    fake_github.device_answers = [{"error": "authorization_pending"}]
    with TestClient(
        create_app(web_settings),
        base_url=API_BASE,
        headers={"Authorization": f"Bearer {API_TOKEN}"},
    ) as client:
        connection = client.post("/api/accounts/github/device").json()
        pending = connections(client).get(connection["id"])
    assert pending is not None
    assert pending.task is not None and pending.task.done()
    assert pending.status.value == "cancelled"


def test_account_responses_follow_the_exported_schema(
    api: TestClient, fake_github: FakeGitHub
) -> None:
    from test_web_server import conforms

    from forceupdate.web import openapi

    schema = json.loads(openapi.OPENAPI_JSON.read_text(encoding="utf-8"))
    components = schema["components"]["schemas"]

    def check(value: Any, name: str) -> None:
        assert conforms(value, {"$ref": f"#/components/schemas/{name}"}, components) == []

    fake_github.device_answers = [{"error": "authorization_pending"}]
    device = api.post("/api/accounts/github/device").json()
    check(device, "AccountConnection")
    check(api.get("/api/accounts").json(), "AccountList")
    check(api.post("/api/accounts/github/oauth").json(), "AccountConnection")
    check(api.post("/api/accounts/github/token", json={"token": FINE}).json(), "Account")
    check(api.get("/api/accounts").json(), "AccountList")
    check(api.post("/api/accounts/github/verify").json(), "Account")
    check(api.delete("/api/accounts/github").json(), "Disconnection")
    check(api.get(f"/api/accounts/connections/{device['id']}").json(), "AccountConnection")
