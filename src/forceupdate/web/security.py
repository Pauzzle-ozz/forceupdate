"""La sécurité du serveur local (brief, « Interface web » des pièges) : il lit le disque,
réécrit des fichiers, lance des outils, et détiendra les tokens des forges. Une page web
ouverte dans le même navigateur ne doit rien pouvoir lui demander.

- Il n'écoute que sur ``127.0.0.1`` (``app.serve``).
- **Jeton de session** : aléatoire, tiré à chaque démarrage. ``forceupdate ui`` ouvre
  ``http://127.0.0.1:<port>/?token=<jeton>`` ; cette adresse pose le jeton en cookie
  (``HttpOnly``, ``SameSite=Strict``) et renvoie vers la même page sans lui, pour qu'il ne reste
  ni dans la barre d'adresse ni dans l'historique. Ensuite, toute requête doit porter ce cookie,
  ou l'en-tête ``Authorization: Bearer <jeton>`` (curl, scripts) ; sinon : 401. Le jeton n'est
  jamais accepté dans l'adresse d'une route de l'API (une adresse finit dans les journaux).
- **``Host``** : ``127.0.0.1:<port>`` ou ``localhost:<port>``, sinon 400. Un site qui ferait
  pointer son propre nom sur 127.0.0.1 (« DNS rebinding ») ne peut donc pas parler au serveur.
- **``Origin``** : s'il y en a un, l'adresse du serveur ; **``Sec-Fetch-Site``** : s'il y en a
  un, ``same-origin`` ou ``none`` (une adresse ouverte telle quelle). Sinon : 403. Un cookie
  ``SameSite`` ne suffit pas : pour un navigateur, une page servie par un autre port de
  127.0.0.1 est du même « site », et elle recevrait le cookie.
- **Pas de CORS** : aucun en-tête ``Access-Control-*`` n'est envoyé, une requête de contrôle
  (``OPTIONS``) venue d'ailleurs est refusée comme les autres.
- **En-têtes de réponse** : rien en cache, pas de ``Referer`` (la première adresse porte le
  jeton), pas d'affichage dans un cadre, pas de devinette du type.

Le cookie porte le port dans son nom : les cookies ne distinguent pas les ports, deux serveurs
lancés en même temps garderaient sinon le même.
"""

import json
import secrets
from collections.abc import Iterable

from starlette.datastructures import URL, Headers, QueryParams
from starlette.types import ASGIApp, Message, Receive, Scope, Send

TOKEN_PARAMETER = "token"

SECURITY_HEADERS = (
    ("cache-control", "no-store"),
    ("referrer-policy", "no-referrer"),
    ("x-content-type-options", "nosniff"),
    ("x-frame-options", "DENY"),
    ("cross-origin-opener-policy", "same-origin"),
    ("cross-origin-resource-policy", "same-origin"),
    (
        "content-security-policy",
        "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'",
    ),
)
"""Ajoutés à toutes les réponses, refus compris."""

_SAME_ORIGIN = frozenset({"same-origin", "none"})


def new_token() -> str:
    """Un jeton de session : 32 octets aléatoires, en base64 pour URL."""
    return secrets.token_urlsafe(32)


def cookie_name(port: int) -> str:
    return f"forceupdate-{port}"


class Guard:
    """Le middleware ASGI qui applique ces règles à chaque requête (voir la docstring du
    module)."""

    def __init__(self, app: ASGIApp, *, token: str, port: int) -> None:
        self.app = app
        self._token = token.encode()
        self._cookie = cookie_name(port)
        self._hosts = frozenset({f"127.0.0.1:{port}", f"localhost:{port}"})
        self._origins = frozenset(f"http://{host}" for host in self._hosts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        send = _with_headers(send)
        if scope["type"] != "http":  # pas de WebSocket : le serveur n'en a pas
            await send({"type": "websocket.close", "code": 1008})
            return
        headers = Headers(scope=scope)
        if headers.get("host", "") not in self._hosts:
            await _refuse(send, 400, "Hôte refusé : le serveur ne répond qu'à 127.0.0.1.")
            return
        origin = headers.get("origin")
        site = headers.get("sec-fetch-site")
        if (origin is not None and origin not in self._origins) or (
            site is not None and site not in _SAME_ORIGIN
        ):
            await _refuse(send, 403, "Requête venue d'un autre site : refusée.")
            return
        url = URL(scope=scope)
        given = QueryParams(scope.get("query_string", b"")).get(TOKEN_PARAMETER)
        if given is not None and scope["method"] == "GET" and not _is_api(url.path):
            await self._enter(send, url, given)
            return
        if not self._authorized(headers):
            await _refuse(
                send,
                401,
                "Jeton de session manquant ou invalide : ouvrir l'adresse que donne "
                "« forceupdate ui ».",
            )
            return
        await self.app(scope, receive, send)

    def _authorized(self, headers: Headers) -> bool:
        authorization = headers.get("authorization", "")
        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() == "bearer" and self._matches(credentials.strip()):
            return True
        return any(
            self._matches(value)
            for name, value in _cookies(headers.getlist("cookie"))
            if name == self._cookie
        )

    def _matches(self, value: str) -> bool:
        return secrets.compare_digest(value.encode(), self._token)

    async def _enter(self, send: Send, url: URL, given: str) -> None:
        """L'adresse d'entrée (``/?token=…``) : pose le cookie, puis renvoie vers la même page,
        sans le jeton."""
        if not self._matches(given):
            await _refuse(send, 401, "Jeton de session invalide.")
            return
        target = url.remove_query_params(TOKEN_PARAMETER)
        location = target.path + (f"?{target.query}" if target.query else "")
        cookie = f"{self._cookie}={self._token.decode()}; HttpOnly; SameSite=Strict; Path=/"
        await send(
            {
                "type": "http.response.start",
                "status": 303,
                "headers": [(b"location", location.encode()), (b"set-cookie", cookie.encode())],
            }
        )
        await send({"type": "http.response.body", "body": b""})


def _is_api(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def _cookies(values: Iterable[str]) -> Iterable[tuple[str, str]]:
    for value in values:
        for pair in value.split(";"):
            name, _, content = pair.strip().partition("=")
            yield name, content


def _with_headers(send: Send) -> Send:
    """``send``, qui ajoute ``SECURITY_HEADERS`` au début de chaque réponse."""

    async def sender(message: Message) -> None:
        if message["type"] == "http.response.start":
            headers = [
                (name, value)
                for name, value in message.get("headers", [])
                if name.lower() not in _SECURITY_NAMES
            ]
            headers += [(name.encode(), value.encode()) for name, value in SECURITY_HEADERS]
            message = {**message, "headers": headers}
        await send(message)

    return sender


_SECURITY_NAMES = frozenset(name.encode() for name, _ in SECURITY_HEADERS)


async def _refuse(send: Send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}, ensure_ascii=False).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
