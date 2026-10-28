"""La sécurité du serveur local : jeton de session, ``Host``, ``Origin``, ``Sec-Fetch-Site``, pas
de CORS, en-têtes de réponse (``web.security``)."""

import pytest
from conftest import API_BASE, API_PORT, API_TOKEN
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from forceupdate.web import security

ROUTES = [
    ("GET", "/api/fs"),
    ("GET", "/api/scans"),
    ("POST", "/api/scans"),
    ("GET", "/api/scans/abc"),
    ("GET", "/api/scans/abc/events"),
    ("DELETE", "/api/scans/abc"),
    ("POST", "/api/updates/plan"),
    ("POST", "/api/updates/apply"),
    ("GET", "/api/updates/abc"),
    ("GET", "/api/updates/abc/events"),
    ("GET", "/api/updates/abc/files/package.json"),
    ("POST", "/api/files?name=package.json"),
    ("GET", "/"),
    ("GET", "/une/page"),
]

COOKIE = security.cookie_name(API_PORT)


@pytest.fixture
def anonymous(api: TestClient) -> TestClient:
    """Le même serveur, sans le jeton."""
    del api.headers["Authorization"]
    return api


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_every_route_refuses_a_request_without_the_token(
    anonymous: TestClient, method: str, path: str
) -> None:
    response = anonymous.request(method, path, json={"path": "/", "scan": "x", "plan": "x"})
    assert response.status_code == 401
    assert response.json() == {
        "detail": "Jeton de session manquant ou invalide : ouvrir l'adresse que donne "
        "« forceupdate ui »."
    }


def test_nothing_starts_without_the_token(anonymous: TestClient, tmp_path: object) -> None:
    anonymous.post("/api/scans", json={"path": str(tmp_path)})
    anonymous.headers["Authorization"] = f"Bearer {API_TOKEN}"
    assert anonymous.get("/api/scans").json() == []


@pytest.mark.parametrize(
    "authorization",
    [f"Bearer {API_TOKEN}x", "Bearer", f"Basic {API_TOKEN}", API_TOKEN, "Bearer jéton".encode()],
)
def test_a_wrong_authorization_is_refused(
    anonymous: TestClient, authorization: str | bytes
) -> None:
    response = anonymous.get("/api/scans", headers={"Authorization": authorization})
    assert response.status_code == 401


def test_the_bearer_scheme_ignores_case(anonymous: TestClient) -> None:
    response = anonymous.get("/api/scans", headers={"Authorization": f"bearer {API_TOKEN}"})
    assert response.status_code == 200


def test_the_entry_address_sets_the_cookie_and_drops_the_token(anonymous: TestClient) -> None:
    response = anonymous.get(f"/?token={API_TOKEN}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    cookie = response.headers["set-cookie"]
    assert cookie == f"{COOKIE}={API_TOKEN}; HttpOnly; SameSite=Strict; Path=/"
    # Le client garde le cookie : l'API répond.
    assert anonymous.get("/api/scans").status_code == 200
    page = anonymous.get("/")
    assert page.status_code == 200
    assert "l'interface n'est pas encore construite" in page.text


def test_the_entry_address_keeps_the_other_parameters(anonymous: TestClient) -> None:
    response = anonymous.get(f"/rapport?id=3&token={API_TOKEN}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/rapport?id=3"


def test_a_wrong_entry_token_sets_nothing(anonymous: TestClient) -> None:
    response = anonymous.get("/?token=faux", follow_redirects=False)
    assert response.status_code == 401
    assert "set-cookie" not in response.headers
    assert anonymous.get("/api/scans").status_code == 401


def test_the_token_is_never_taken_from_an_api_address(anonymous: TestClient) -> None:
    response = anonymous.get(f"/api/scans?token={API_TOKEN}", follow_redirects=False)
    assert response.status_code == 401
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize(
    ("cookie", "status"),
    [
        (f"{COOKIE}={API_TOKEN}", 200),
        (f"autre=1; {COOKIE}={API_TOKEN}", 200),
        (f"{COOKIE}=faux", 401),
        (f"forceupdate-9999={API_TOKEN}", 401),  # le cookie d'un serveur sur un autre port
    ],
)
def test_the_session_cookie(anonymous: TestClient, cookie: str, status: int) -> None:
    assert anonymous.get("/api/scans", headers={"Cookie": cookie}).status_code == status


@pytest.mark.parametrize(
    "host", ["evil.example", f"evil.example:{API_PORT}", "127.0.0.1:9999", "127.0.0.1", ""]
)
def test_a_foreign_host_is_refused_even_with_the_token(api: TestClient, host: str) -> None:
    response = api.get("/api/scans", headers={"Host": host})
    assert response.status_code == 400
    assert response.json() == {"detail": "Hôte refusé : le serveur ne répond qu'à 127.0.0.1."}


def test_localhost_is_accepted(api: TestClient) -> None:
    assert api.get("/api/scans", headers={"Host": f"localhost:{API_PORT}"}).status_code == 200


@pytest.mark.parametrize(
    "origin",
    ["https://evil.example", "http://127.0.0.1:9999", "null", f"https://127.0.0.1:{API_PORT}"],
)
def test_a_foreign_origin_is_refused_even_with_the_token(api: TestClient, origin: str) -> None:
    for method in ("GET", "POST", "DELETE"):
        response = api.request(method, "/api/scans", headers={"Origin": origin})
        assert response.status_code == 403
        assert response.json() == {"detail": "Requête venue d'un autre site : refusée."}


@pytest.mark.parametrize("origin", [API_BASE, f"http://localhost:{API_PORT}"])
def test_the_server_origin_is_accepted(api: TestClient, origin: str) -> None:
    assert api.get("/api/scans", headers={"Origin": origin}).status_code == 200


@pytest.mark.parametrize(
    ("site", "status"),
    [("same-origin", 200), ("none", 200), ("same-site", 403), ("cross-site", 403)],
)
def test_sec_fetch_site(api: TestClient, site: str, status: int) -> None:
    assert api.get("/api/scans", headers={"Sec-Fetch-Site": site}).status_code == status


def test_no_cors(api: TestClient) -> None:
    preflight = api.options(
        "/api/scans",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert preflight.status_code == 403
    for response in (preflight, api.get("/api/scans")):
        assert not [name for name in response.headers if name.lower().startswith("access-control")]


@pytest.mark.parametrize("authorized", [True, False])
def test_security_headers_on_every_response(api: TestClient, authorized: bool) -> None:
    if not authorized:
        del api.headers["Authorization"]
    response = api.get("/api/scans")
    assert response.status_code == (200 if authorized else 401)
    for name, value in security.SECURITY_HEADERS:
        assert response.headers[name] == value


def test_websockets_are_refused(api: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect), api.websocket_connect("/api/scans"):
        pass


def test_tokens_are_random() -> None:
    tokens = {security.new_token() for _ in range(20)}
    assert len(tokens) == 20
    assert all(len(token) >= 43 for token in tokens)
