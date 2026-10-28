"""Le client HTTP commun : un ``httpx.AsyncClient`` partagé, ses délais, ses reprises et ses
limites par hôte.

Tout ce qui parle au réseau passe par ``HttpClient`` :

- un User-Agent qui dit qui on est (crates.io l'exige, E21) ;
- des délais maximaux : 10 s pour se connecter, 30 s sans rien recevoir, 2 min pour un
  essai entier (un serveur qui envoie un octet toutes les 29 s ne le fait pas durer) ;
- des reprises sur 429, 5xx, coupures et délais dépassés, en attendant ce que demande
  ``Retry-After`` ; s'il demande plus d'une minute, on abandonne ;
- au plus 8 requêtes à la fois par hôte ;
- un hôte resté injoignable après ses reprises (ou qui limite le débit) n'est plus
  interrogé pendant une minute (ou le temps que demande ``Retry-After``) : sans réseau, chaque
  paquet attendrait sinon ses reprises. Pas plus longtemps : le client de l'interface web sert
  des heures, le réseau peut revenir ;
- une réponse de plus de 128 Mo est refusée (le document npm de ``next`` en fait 32).

Une requête qui n'aboutit pas lève ``NetworkError``, avec un message en français fait pour
le rapport. Un statut final (200, 404, 403…) n'est pas une erreur du client : c'est à
l'appelant de dire ce qu'il veut dire.
"""

import asyncio
import email.utils
import json
import logging
import random
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from forceupdate import __version__

logger = logging.getLogger(__name__)

USER_AGENT = f"forceupdate/{__version__} (+https://github.com/Pauzzle-ozz/forceupdate)"

TIMEOUT = httpx.Timeout(30.0, connect=10.0)
"""Les délais d'httpx : 10 s pour se connecter, 30 s pour le reste (entre deux octets…)."""
DEADLINE = 120.0
"""Durée maximale d'un essai, en secondes, réponse lue en entier."""
RETRIES = 3
"""Reprises après le premier essai, pour une requête qu'on peut rejouer."""
MAX_PER_HOST = 8
"""Requêtes simultanées par hôte."""
MAX_BODY = 128 * 1024 * 1024
"""Taille maximale d'une réponse, décompressée, en octets."""
MAX_RETRY_AFTER = 60.0
"""Attente maximale demandée par ``Retry-After``, en secondes : au-delà, on abandonne."""
DOWN_FOR = 60.0
"""Durée, en secondes, pendant laquelle un hôte abandonné n'est plus interrogé (plus, si
``Retry-After`` demande plus)."""

_BACKOFF = 0.5
"""Première attente entre deux essais sans ``Retry-After`` ; elle double à chaque reprise."""
_IDEMPOTENT = frozenset({"GET", "HEAD", "OPTIONS"})
_RETRYABLE = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError, TimeoutError)
"""Les échecs qui peuvent passer en réessayant : délai dépassé, connexion refusée ou coupée."""
_DIGITS = re.compile(r"[0-9]+")


class NetworkError(Exception):
    """Une requête n'a pas abouti : réseau coupé, délai dépassé, serveur en erreur, mode hors
    ligne… Le constat qui en dépend est « non concluant ».

    Le message, en français, est fait pour être montré tel quel dans le rapport. Il cite
    l'hôte, jamais l'URL (une URL peut contenir un token).
    """


@dataclass(frozen=True, kw_only=True)
class Response:
    """Une réponse HTTP, lue en entier."""

    url: str
    """L'URL finale, après les redirections."""
    status_code: int
    headers: httpx.Headers
    content: bytes
    """Le corps, décompressé."""

    @property
    def media_type(self) -> str:
        """Le type du corps sans ses paramètres, en minuscules (``application/json``)."""
        return self.headers.get("content-type", "").partition(";")[0].strip().lower()

    def json(self) -> Any:
        """Le corps lu en JSON ; lève ``ValueError`` s'il n'en est pas."""
        return json.loads(self.content)


class _TooLarge(Exception):
    pass


class HttpClient:
    """Le client HTTP d'une session : une analyse en ligne de commande, ou l'interface web.

    Un seul par session, pour garder les connexions ouvertes et que les limites par hôte
    vaillent pour tout le monde. À fermer après usage : ``async with HttpClient() as http``.

    ``offline`` : aucune requête ne part, chacune lève ``NetworkError`` ; les registres se
    contentent alors du cache. ``sleep`` et ``clock`` servent aux tests, pour ne pas attendre les
    reprises ni la fin d'un abandon.
    """

    def __init__(
        self,
        *,
        offline: bool = False,
        retries: int = RETRIES,
        max_per_host: int = MAX_PER_HOST,
        max_body: int = MAX_BODY,
        deadline: float = DEADLINE,
        down_for: float = DOWN_FOR,
        sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.offline = offline
        self._retries = retries
        self._max_per_host = max_per_host
        self._max_body = max_body
        self._deadline = deadline
        self._down_for = down_for
        self._sleep = sleep
        self._clock = clock
        self._slots: dict[str, asyncio.Semaphore] = {}
        self._down: dict[str, tuple[str, float]] = {}
        """Les hôtes abandonnés, avec le message de leur échec et l'heure (``clock``) jusqu'à
        laquelle ils le restent."""
        self._client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=32),
        )

    async def __aenter__(self) -> "HttpClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> Response:
        """``GET url`` ; voir ``request``."""
        return await self.request("GET", url, headers=headers)

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json: Any = None,
        retry: bool | None = None,
    ) -> Response:
        """Envoie la requête et rend la réponse, quel que soit son statut final.

        Réessaie sur 429, 5xx, coupure ou délai dépassé, si la requête peut être rejouée :
        par défaut ``GET``, ``HEAD`` et ``OPTIONS`` ; ``retry=True`` pour une autre qui ne
        change rien (une recherche en ``POST``). ``json`` est envoyé en corps JSON.

        Lève ``NetworkError`` quand la requête n'aboutit pas, ou que le statut reste 429 ou
        5xx après les reprises.
        """
        host = httpx.URL(url).host
        if self.offline:
            raise NetworkError(f"mode hors ligne : {host} n'est pas interrogé.")
        down = self._down.get(host)
        if down is not None:
            message, until = down
            if self._clock() < until:
                raise NetworkError(message)
            del self._down[host]
        if retry is None:
            retry = method.upper() in _IDEMPOTENT
        attempts = 1 + (self._retries if retry else 0)
        for attempt in range(attempts):
            final = attempt == attempts - 1
            try:
                response = await self._send(host, method, url, headers, json)
            except _TooLarge:
                limit = self._max_body // 2**20
                raise NetworkError(f"réponse de {host} trop grosse (plus de {limit} Mo).") from None
            except _RETRYABLE as error:
                logger.debug(
                    "%s %s : %r (essai %d sur %d)", method, url, error, attempt + 1, attempts
                )
                if final:
                    message = _failure(host, error)
                    self._abandon(host, message)
                    raise NetworkError(message) from error
                await self._sleep(_backoff(attempt))
                continue
            except httpx.HTTPError as error:
                raise NetworkError(
                    f"requête vers {host} impossible ({type(error).__name__})."
                ) from error
            status = response.status_code
            if status != 429 and status < 500:
                return response
            wait = _retry_after(response.headers)
            logger.debug(
                "%s %s : HTTP %d (essai %d sur %d)", method, url, status, attempt + 1, attempts
            )
            if final or (wait is not None and wait > MAX_RETRY_AFTER):
                message = _status_failure(host, status, wait)
                if status == 429:
                    self._abandon(host, message, wait)
                raise NetworkError(message)
            await self._sleep(_backoff(attempt) if wait is None else wait)
        raise AssertionError("inaccessible : le dernier essai rend ou lève")

    async def _send(
        self, host: str, method: str, url: str, headers: Mapping[str, str] | None, body: Any
    ) -> Response:
        async with (
            self._slot(host),
            asyncio.timeout(self._deadline),
            self._client.stream(method, url, headers=headers, json=body) as response,
        ):
            declared = response.headers.get("content-length", "")
            if _DIGITS.fullmatch(declared) and int(declared) > self._max_body:
                raise _TooLarge
            chunks = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > self._max_body:
                    raise _TooLarge
                chunks.append(chunk)
            return Response(
                url=str(response.url),
                status_code=response.status_code,
                headers=response.headers,
                content=b"".join(chunks),
            )

    def _abandon(self, host: str, message: str, wait: float | None = None) -> None:
        """N'interroge plus ``host`` pendant ``down_for`` secondes, ou ``wait`` si c'est plus."""
        self._down[host] = (message, self._clock() + max(self._down_for, wait or 0.0))

    def _slot(self, host: str) -> asyncio.Semaphore:
        slot = self._slots.get(host)
        if slot is None:
            slot = self._slots[host] = asyncio.Semaphore(self._max_per_host)
        return slot


def _backoff(attempt: int) -> float:
    """L'attente avant la reprise n° ``attempt + 1`` : 0,5 s, 1 s, 2 s…, un peu au hasard
    pour que les requêtes en échec ne reviennent pas toutes ensemble."""
    return _BACKOFF * 2**attempt + random.uniform(0, _BACKOFF)


def _retry_after(headers: httpx.Headers) -> float | None:
    """L'attente demandée par ``Retry-After``, en secondes (un nombre, ou une date HTTP) ;
    ``None`` sans en-tête lisible."""
    value = headers.get("retry-after", "").strip()
    if _DIGITS.fullmatch(value):
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def _failure(host: str, error: BaseException) -> str:
    if isinstance(error, httpx.TimeoutException | TimeoutError):
        return f"{host} ne répond pas (délai dépassé)."
    return f"{host} injoignable ({type(error).__name__})."


def _status_failure(host: str, status: int, wait: float | None) -> str:
    if status != 429:
        return f"{host} en erreur (HTTP {status})."
    if wait is not None and wait > MAX_RETRY_AFTER:
        return f"{host} limite le débit (HTTP 429) : réessayer dans {round(wait / 60) or 1} min."
    return f"{host} limite le débit (HTTP 429)."
