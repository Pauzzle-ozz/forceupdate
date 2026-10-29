"""GitHub : le client REST (droits d'un token, pagination, erreurs), la connexion (OAuth avec
PKCE, device flow, révocation) et le token de ``gh`` (``forges.github``). GitHub est simulé par
``respx``, ``gh`` par de faux ``_which`` et ``_run``."""

import asyncio
import json
import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

from forceupdate.forges import FORGES, client, github
from forceupdate.forges.base import (
    Access,
    AccessDenied,
    Forge,
    ForgeError,
    ForgeKind,
    NotFound,
    RateLimited,
    Repository,
    TokenRefused,
)
from forceupdate.forges.github import DeviceCode, DeviceExpired, GitHub, OAuthApp
from forceupdate.net import HttpClient, NetworkError

T = TypeVar("T")

TOKEN = "gho_jeton-de-test"
APP = OAuthApp(client_id="Ov23-test", client_secret="secret-de-test")
USER = {"login": "octo", "name": "Octo Cat", "html_url": "https://github.com/octo", "id": 1}


async def _no_sleep(_: float) -> None:
    pass


def run(work: Callable[[HttpClient], Awaitable[T]]) -> T:
    """``work(http)`` avec un client qui n'attend pas entre ses reprises."""

    async def main() -> T:
        async with HttpClient(sleep=_no_sleep) as http:
            return await work(http)

    return asyncio.run(main())


def whoami(token: str = TOKEN) -> Callable[[HttpClient], Awaitable[Any]]:
    return lambda http: GitHub(http, token).whoami()


# -- whoami et droits ---------------------------------------------------------------


@respx.mock
def test_whoami_reads_the_account_and_its_scopes() -> None:
    route = respx.get("https://api.github.com/user").respond(
        200,
        json=USER,
        headers={
            "X-OAuth-Scopes": "repo, read:org",
            "X-RateLimit-Limit": "5000",
            "X-RateLimit-Remaining": "4999",
            "X-RateLimit-Reset": "1793208000",
        },
    )
    identity = run(whoami())
    assert identity.forge is ForgeKind.GITHUB
    assert identity.host == "github.com"
    assert (identity.login, identity.name, identity.url) == (
        "octo",
        "Octo Cat",
        "https://github.com/octo",
    )
    assert identity.access is Access.WRITE
    assert identity.scopes == ("repo", "read:org")
    assert identity.warnings == ()
    request = route.calls.last.request
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert request.headers["Accept"] == "application/vnd.github+json"
    assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"
    assert TOKEN not in str(request.url)


@pytest.mark.parametrize(
    ("header", "access", "warnings"),
    [
        ("repo, read:org, workflow", Access.WRITE, []),
        ("admin:org, repo", Access.WRITE, []),
        ("repo", Access.WRITE, ["read:org"]),
        ("public_repo, read:org", Access.PUBLIC, ["dépôts privés"]),
        ("", Access.READ, ["Sans la portée repo", "read:org"]),
        ("gist", Access.READ, ["Sans la portée repo", "read:org"]),
        (None, Access.UNKNOWN, ["fine-grained"]),
    ],
)
@respx.mock
def test_what_a_token_allows(header: str | None, access: Access, warnings: list[str]) -> None:
    headers = {} if header is None else {"X-OAuth-Scopes": header}
    respx.get("https://api.github.com/user").respond(200, json=USER, headers=headers)
    identity = run(whoami())
    assert identity.access is access
    assert identity.scopes == (None if header is None else github._scopes(httpx.Headers(headers)))
    assert len(identity.warnings) == len(warnings)
    for text, expected in zip(identity.warnings, warnings, strict=True):
        assert expected in text


@respx.mock
def test_the_rate_limit_of_the_last_response_is_kept() -> None:
    respx.get("https://api.github.com/user").respond(
        200,
        json=USER,
        headers={
            "X-RateLimit-Limit": "5000",
            "X-RateLimit-Remaining": "4321",
            "X-RateLimit-Reset": "1793208000",
        },
    )

    async def work(http: HttpClient) -> Any:
        forge = GitHub(http, TOKEN)
        await forge.whoami()
        return forge.rate_limit

    rate = run(work)
    assert (rate.limit, rate.remaining) == (5000, 4321)
    assert rate.reset_at.timestamp() == 1793208000


# -- Erreurs ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "headers", "body", "error", "message"),
    [
        (401, {}, {"message": "Bad credentials"}, TokenRefused, "GitHub refuse le token (401)"),
        (
            403,
            {"X-RateLimit-Limit": "5000", "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "0"},
            {"message": "API rate limit exceeded"},
            RateLimited,
            "Limite de l'API GitHub atteinte (5000 requêtes par heure) : elle se lève à",
        ),
        (
            403,
            {"Retry-After": "30"},
            {"message": "You have exceeded a secondary rate limit."},
            RateLimited,
            "limite secondaire) : réessayer dans 30 s.",
        ),
        (
            403,
            {
                "X-GitHub-SSO": "required; url=https://github.com/orgs/acme/sso?authorization_request=1"
            },
            {"message": "Resource protected by organization SAML enforcement."},
            AccessDenied,
            "SSO (SAML) : https://github.com/orgs/acme/sso?authorization_request=1.",
        ),
        (
            403,
            {},
            {"message": "Resource not accessible by integration"},
            AccessDenied,
            "GitHub refuse l'accès (403) à /user : Resource not accessible by integration.",
        ),
        (
            404,
            {},
            {"message": "Not Found"},
            NotFound,
            "Introuvable sur GitHub (404) : /user n'existe pas, ou le token n'y a pas accès.",
        ),
        (422, {}, {}, ForgeError, "GitHub refuse la requête (HTTP 422) sur /user : pas de détail."),
    ],
)
@respx.mock
def test_errors_say_what_happened(
    status: int, headers: dict[str, str], body: Any, error: type[Exception], message: str
) -> None:
    respx.get("https://api.github.com/user").respond(status, json=body, headers=headers)
    with pytest.raises(error) as caught:
        run(whoami())
    assert message in str(caught.value)
    assert TOKEN not in str(caught.value)


@respx.mock
def test_a_response_that_is_not_json_is_an_error() -> None:
    respx.get("https://api.github.com/user").respond(200, text="<html>")
    with pytest.raises(ForgeError, match="pas du JSON"):
        run(whoami())


@respx.mock
def test_a_server_error_is_a_network_error_after_the_retries() -> None:
    route = respx.get("https://api.github.com/user").respond(502)
    with pytest.raises(NetworkError, match=r"api\.github\.com en erreur"):
        run(whoami())
    assert route.call_count == 4


# -- Pagination ---------------------------------------------------------------------


@respx.mock
def test_paginate_follows_the_link_header() -> None:
    base = "https://api.github.com/user/repos"
    respx.get(f"{base}?affiliation=owner&per_page=100").respond(
        200,
        json=[1, 2],
        headers={"Link": f'<{base}?page=2>; rel="next", <{base}?page=3>; rel="last"'},
    )
    respx.get(f"{base}?page=2").respond(
        200,
        json=[3],
        headers={"Link": f'<{base}?page=1>; rel="prev", <{base}?page=3>; rel="next"'},
    )
    respx.get(f"{base}?page=3").respond(200, json=[4], headers={"Link": f'<{base}>; rel="first"'})

    async def work(http: HttpClient) -> list[Any]:
        forge = GitHub(http, TOKEN)
        return [item async for item in forge.paginate("/user/repos?affiliation=owner")]

    assert run(work) == [1, 2, 3, 4]


@respx.mock
def test_paginate_refuses_a_page_that_is_not_a_list() -> None:
    respx.get("https://api.github.com/user/repos?per_page=100").respond(200, json={"a": 1})

    async def work(http: HttpClient) -> list[Any]:
        return [item async for item in GitHub(http, TOKEN).paginate("/user/repos")]

    with pytest.raises(ForgeError, match="Réponse inattendue de GitHub pour /user/repos"):
        run(work)


# -- L'interface --------------------------------------------------------------------


def test_the_forge_interface_is_fixed() -> None:
    assert {name for name in Forge.__abstractmethods__} == {
        "whoami",
        "list_repos",
        "repository",
        "tree",
        "read_file",
        "clone",
        "push_branch",
        "find_open_request",
        "open_or_update_request",
    }

    class Partial(Forge):
        async def whoami(self) -> Any:
            return None

    with pytest.raises(TypeError):
        Partial()  # type: ignore[abstract]


def test_what_github_does_not_do_yet_says_when_it_comes(tmp_path: Path) -> None:
    repo = Repository(
        forge=ForgeKind.GITHUB,
        host="github.com",
        full_name="octo/demo",
        default_branch="main",
        private=False,
        archived=False,
        fork=False,
        can_push=True,
        url="https://github.com/octo/demo",
        clone_url="https://github.com/octo/demo.git",
    )

    async def calls(http: HttpClient) -> list[str]:
        forge = GitHub(http, TOKEN)
        found = []
        for call in (
            forge.clone(repo, tmp_path),
            forge.push_branch(repo, tmp_path, "forceupdate/dependencies"),
            forge.find_open_request(repo, "forceupdate/dependencies"),
            forge.open_or_update_request(repo, branch="b", title="t", body="d"),
        ):
            try:
                await call
            except NotImplementedError as err:
                found.append(str(err))
        return found

    found = run(calls)
    assert len(found) == 4
    assert all(" E18" in text for text in found)


def test_the_forges_and_their_client() -> None:
    assert [(f.kind, f.name, f.available) for f in FORGES] == [
        (ForgeKind.GITHUB, "GitHub", True),
        (ForgeKind.GITLAB, "GitLab", False),
        (ForgeKind.BITBUCKET, "Bitbucket", False),
    ]

    async def work(http: HttpClient) -> Any:
        return client(ForgeKind.GITHUB, http, TOKEN)

    forge = run(work)
    assert isinstance(forge, GitHub)
    assert TOKEN not in repr(forge)
    with pytest.raises(NotImplementedError, match="GitLab"):
        client(ForgeKind.GITLAB, None, TOKEN)  # type: ignore[arg-type]


# -- OAuth --------------------------------------------------------------------------


def test_pkce_challenge_follows_rfc_7636() -> None:
    # L'exemple de l'annexe B de la RFC 7636.
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert github.challenge_of(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    verifiers = {github.new_verifier() for _ in range(10)}
    assert len(verifiers) == 10
    assert all(43 <= len(v) <= 128 for v in verifiers)


def test_the_authorization_url() -> None:
    url = github.authorization_url(
        APP, redirect_to=github.redirect_uri(54321), state="etat", verifier="v" * 50
    )
    parts = urlsplit(url)
    assert (
        f"{parts.scheme}://{parts.netloc}{parts.path}" == "https://github.com/login/oauth/authorize"
    )
    assert parse_qs(parts.query) == {
        "client_id": ["Ov23-test"],
        "redirect_uri": ["http://127.0.0.1:54321/oauth/github/callback"],
        "scope": ["repo read:org"],
        "state": ["etat"],
        "code_challenge": [github.challenge_of("v" * 50)],
        "code_challenge_method": ["S256"],
    }


@respx.mock
def test_exchange_code_sends_the_code_the_secret_and_the_verifier() -> None:
    route = respx.post("https://github.com/login/oauth/access_token").respond(
        200, json={"access_token": TOKEN, "token_type": "bearer", "scope": "repo,read:org"}
    )
    token = run(
        lambda http: github.exchange_code(
            http, APP, code="code-1", redirect_to="http://127.0.0.1:1/cb", verifier="vérif"
        )
    )
    assert token == TOKEN
    request = route.calls.last.request
    assert request.headers["Accept"] == "application/json"
    assert json.loads(request.content) == {
        "client_id": "Ov23-test",
        "client_secret": "secret-de-test",
        "code": "code-1",
        "redirect_uri": "http://127.0.0.1:1/cb",
        "code_verifier": "vérif",
    }


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"error": "bad_verification_code"}, "Le code d'autorisation a expiré ou a déjà servi"),
        ({"error": "redirect_uri_mismatch"}, "http://127.0.0.1/oauth/github/callback"),
        ({"error": "incorrect_client_credentials"}, "client id ou secret"),
        (
            {"error": "other", "error_description": "Something odd."},
            "GitHub refuse l'échange du code : Something odd.",
        ),
        ({}, "GitHub refuse l'échange du code : pas de détail."),
    ],
)
@respx.mock
def test_exchange_code_errors(body: dict[str, str], message: str) -> None:
    respx.post("https://github.com/login/oauth/access_token").respond(200, json=body)
    with pytest.raises(ForgeError, match=message.replace("(", r"\(").replace(".", r"\.")):
        run(lambda http: github.exchange_code(http, APP, code="c", redirect_to="r", verifier="v"))


@respx.mock
def test_a_code_is_never_sent_twice() -> None:
    route = respx.post("https://github.com/login/oauth/access_token").respond(500)
    with pytest.raises(NetworkError):
        run(lambda http: github.exchange_code(http, APP, code="c", redirect_to="r", verifier="v"))
    assert route.call_count == 1


def test_authorization_errors_returned_to_the_callback() -> None:
    assert github.authorization_error("access_denied") == "Autorisation refusée sur GitHub."
    assert (
        github.authorization_error("application_suspended", "Your application has been suspended.")
        == "GitHub refuse l'autorisation : Your application has been suspended."
    )


def test_the_oauth_app_can_be_replaced(monkeypatch: pytest.MonkeyPatch) -> None:
    default = OAuthApp.default()
    assert default.client_id == github.CLIENT_ID
    assert default.web_flow
    assert github.CLIENT_SECRET not in repr(default)
    monkeypatch.setenv(github.ENV_CLIENT_ID, "Ov23-autre")
    assert OAuthApp.default() == OAuthApp(client_id="Ov23-autre", client_secret="")
    assert not OAuthApp.default().web_flow
    monkeypatch.setenv(github.ENV_CLIENT_SECRET, "s")
    assert OAuthApp.default().web_flow


# -- Révocation ---------------------------------------------------------------------


@pytest.mark.parametrize(("status", "revoked"), [(204, True), (404, True), (422, False)])
@respx.mock
def test_revoke(status: int, revoked: bool) -> None:
    route = respx.delete("https://api.github.com/applications/Ov23-test/token").respond(status)
    assert run(lambda http: github.revoke(http, APP, TOKEN)) is revoked
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Basic T3YyMy10ZXN0OnNlY3JldC1kZS10ZXN0"
    assert json.loads(request.content) == {"access_token": TOKEN}


@respx.mock
def test_revoke_is_never_blocking() -> None:
    respx.delete("https://api.github.com/applications/Ov23-test/token").mock(
        side_effect=httpx.ConnectError("coupé")
    )
    assert run(lambda http: github.revoke(http, APP, TOKEN)) is False
    no_secret = OAuthApp(client_id="Ov23-test", client_secret="")
    assert run(lambda http: github.revoke(http, no_secret, TOKEN)) is False


# -- Device flow ----------------------------------------------------------------------

DEVICE = DeviceCode(
    device_code="code-appareil",
    user_code="WDJB-MJHT",
    verification_uri="https://github.com/login/device",
    expires_in=900,
    interval=5,
)


@respx.mock
def test_start_device() -> None:
    route = respx.post("https://github.com/login/device/code").respond(
        200,
        json={
            "device_code": "code-appareil",
            "user_code": "WDJB-MJHT",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 899,
            "interval": 5,
        },
    )
    device = run(lambda http: github.start_device(http, APP))
    assert device == DEVICE.__class__(**{**DEVICE.__dict__, "expires_in": 899})
    assert "code-appareil" not in repr(device)
    assert json.loads(route.calls.last.request.content) == {
        "client_id": "Ov23-test",
        "scope": "repo read:org",
    }


@respx.mock
def test_start_device_when_the_device_flow_is_disabled() -> None:
    respx.post("https://github.com/login/device/code").respond(
        200, json={"error": "device_flow_disabled"}
    )
    with pytest.raises(ForgeError, match="Le device flow n'est pas activé"):
        run(lambda http: github.start_device(http, APP))


class Clock:
    """Une horloge qui n'avance qu'avec les attentes."""

    def __init__(self) -> None:
        self.now = 0.0
        self.waits: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.now += seconds


def wait_device(clock: Clock, device: DeviceCode = DEVICE) -> Callable[[HttpClient], Any]:
    return lambda http: github.wait_device(http, APP, device, sleep=clock.sleep, clock=clock)


@respx.mock
def test_wait_device_polls_until_the_code_is_entered() -> None:
    route = respx.post("https://github.com/login/oauth/access_token").mock(
        side_effect=[
            httpx.Response(200, json={"error": "authorization_pending"}),
            httpx.Response(200, json={"error": "slow_down", "interval": 10}),
            httpx.Response(200, json={"error": "authorization_pending"}),
            httpx.Response(200, json={"access_token": TOKEN}),
        ]
    )
    clock = Clock()
    assert run(wait_device(clock)) == TOKEN
    assert clock.waits == [5, 5, 10, 10]
    assert json.loads(route.calls.last.request.content) == {
        "client_id": "Ov23-test",
        "device_code": "code-appareil",
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }


@respx.mock
def test_slow_down_without_interval_adds_five_seconds() -> None:
    respx.post("https://github.com/login/oauth/access_token").mock(
        side_effect=[
            httpx.Response(200, json={"error": "slow_down"}),
            httpx.Response(200, json={"access_token": TOKEN}),
        ]
    )
    clock = Clock()
    run(wait_device(clock))
    assert clock.waits == [5, 10]


@respx.mock
def test_wait_device_stops_when_the_code_expires() -> None:
    respx.post("https://github.com/login/oauth/access_token").respond(
        200, json={"error": "authorization_pending"}
    )
    clock = Clock()
    short = DeviceCode(**{**DEVICE.__dict__, "expires_in": 12})
    with pytest.raises(DeviceExpired, match="Le code a expiré avant d'être saisi"):
        run(wait_device(clock, short))
    assert clock.waits == [5, 5, 5]


@pytest.mark.parametrize(
    ("error", "kind", "message"),
    [
        ("access_denied", ForgeError, "Autorisation refusée sur GitHub."),
        ("expired_token", DeviceExpired, "Le code a expiré"),
        (
            "incorrect_device_code",
            ForgeError,
            "GitHub refuse la connexion : incorrect_device_code.",
        ),
    ],
)
@respx.mock
def test_wait_device_errors(error: str, kind: type[Exception], message: str) -> None:
    respx.post("https://github.com/login/oauth/access_token").respond(200, json={"error": error})
    with pytest.raises(kind, match=message.replace(".", r"\.")):
        run(wait_device(Clock()))


@respx.mock
def test_wait_device_never_polls_faster_than_the_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    respx.post("https://github.com/login/oauth/access_token").respond(
        200, json={"access_token": TOKEN}
    )
    clock = Clock()
    run(wait_device(clock, DeviceCode(**{**DEVICE.__dict__, "interval": 0})))
    assert clock.waits == [github.MIN_INTERVAL]


# -- gh ---------------------------------------------------------------------------------


class FakeGh:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, outcome: Any) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self.outcome = outcome
        monkeypatch.setattr(github, "_which", lambda program: f"/outils/{program}")
        monkeypatch.setattr(github, "_run", self.run)

    def run(self, command: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
        self.calls.append((command, options))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        code, out, err = self.outcome
        return subprocess.CompletedProcess(command, code, out, err)


def test_gh_token(monkeypatch: pytest.MonkeyPatch) -> None:
    gh = FakeGh(monkeypatch, (0, b"gho_du-gh\r\n", b""))
    assert github.gh_installed()
    assert github.gh_token() == "gho_du-gh"
    ((command, options),) = gh.calls
    assert command == ["/outils/gh", "auth", "token", "--hostname", "github.com"]
    assert options["capture_output"] is True
    assert options["stdin"] is subprocess.DEVNULL
    assert options["timeout"] == github.GH_TIMEOUT
    assert options["env"]["GH_PROMPT_DISABLED"] == "1"


@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        (
            (1, b"", b"no oauth token found for github.com\n"),
            "gh n'est pas connecté à github.com (no oauth token found for github.com) : lancer",
        ),
        ((1, b"", b""), "gh n'est pas connecté à github.com : lancer « gh auth login »"),
        ((0, b"", b""), "gh n'a pas rendu de token."),
        ((0, b"deux mots", b""), "gh n'a pas rendu de token."),
        (subprocess.TimeoutExpired(["gh"], 15), "gh ne répond pas (plus de 15 s)."),
        (FileNotFoundError(2, "introuvable"), "gh n'a pas pu être lancé (introuvable)."),
    ],
)
def test_gh_token_failures(monkeypatch: pytest.MonkeyPatch, outcome: Any, message: str) -> None:
    FakeGh(monkeypatch, outcome)
    with pytest.raises(ForgeError) as caught:
        github.gh_token()
    assert message in str(caught.value)


def test_gh_not_installed() -> None:
    assert not github.gh_installed()
    with pytest.raises(ForgeError, match=r"GitHub CLI \(gh\) n'est pas installé\."):
        github.gh_token()
