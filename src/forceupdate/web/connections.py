"""La connexion des comptes aux forges, côté serveur : ce qui dure le temps d'une autorisation.

- **OAuth** : ``start_oauth`` tire un ``state`` (contre les requêtes forgées) et un secret PKCE,
  gardés ici, jamais dans un cookie ; le navigateur part vers la page d'autorisation de la
  forge, qui le renvoie sur l'adresse de retour (``web.routes.oauth``). ``by_state`` y retrouve
  la connexion, ``finish_oauth`` échange le code contre le token. Un ``state`` ne sert qu'une
  fois, et expire après ``OAUTH_TTL``.
- **Device flow** : ``start_device`` demande un code à la forge, puis une tâche de la boucle du
  serveur attend que la personne l'ait tapé (``github.wait_device``).

Dans les deux cas, le token obtenu est vérifié par la forge (``whoami``) puis rangé dans le
trousseau (``forges.accounts.connect``) ; le navigateur suit la connexion par son identifiant.
Tout se passe dans la boucle du serveur ; rien n'est gardé sur le disque.

``Connections`` porte aussi ce dont ont besoin les routes des comptes : le magasin des comptes,
le ``HttpClient`` qui parle aux forges, l'application OAuth.
"""

import asyncio
import logging
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from forceupdate.forges import accounts as accounts_module
from forceupdate.forges import github, info
from forceupdate.forges.accounts import Account, Accounts, AccountsError, ConnectMethod
from forceupdate.forges.base import ForgeError, ForgeKind
from forceupdate.forges.github import DeviceCode, DeviceExpired, OAuthApp
from forceupdate.net import HttpClient, NetworkError
from forceupdate.web.schemas import AccountConnection, ConnectionStatus

logger = logging.getLogger(__name__)

OAUTH_TTL = timedelta(minutes=10)
"""Le temps laissé pour autoriser sur la forge et revenir."""
MAX_CONNECTIONS = 20
"""Connexions gardées en mémoire (les finies sont oubliées au-delà)."""


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(eq=False, kw_only=True)
class Connection:
    """Une connexion lancée par l'interface."""

    id: str
    forge: ForgeKind
    method: ConnectMethod
    expires_at: datetime
    created_at: datetime = field(default_factory=_now)
    status: ConnectionStatus = ConnectionStatus.PENDING
    state: str | None = field(default=None, repr=False)
    """OAuth : le ``state`` attendu au retour ; effacé dès qu'il a servi."""
    verifier: str | None = field(default=None, repr=False)
    """OAuth : le secret PKCE."""
    redirect_to: str | None = None
    authorize_url: str | None = None
    device: DeviceCode | None = field(default=None, repr=False)
    task: asyncio.Task[None] | None = field(default=None, repr=False)
    error: str | None = None
    account: Account | None = None

    def document(self) -> AccountConnection:
        return AccountConnection(
            id=self.id,
            forge=self.forge,
            method=self.method,
            status=self.status,
            created_at=self.created_at,
            expires_at=self.expires_at,
            authorize_url=self.authorize_url if self.pending else None,
            user_code=self.device.user_code if self.device else None,
            verification_uri=self.device.verification_uri if self.device else None,
            interval=self.device.interval if self.device else None,
            error=self.error,
            account=self.account,
        )

    @property
    def pending(self) -> bool:
        return self.status is ConnectionStatus.PENDING

    def end(
        self, status: ConnectionStatus, error: str | None = None, account: Account | None = None
    ) -> None:
        self.status = status
        self.error = error
        self.account = account
        self.state = self.verifier = None


class Connections:
    """Les connexions de la session, et ce qu'il faut pour connecter un compte. À créer et à
    fermer dans la boucle du serveur."""

    def __init__(self, *, accounts: Accounts, port: int, app: OAuthApp | None = None) -> None:
        self.accounts = accounts
        self.port = port
        self.app = app or OAuthApp.default()
        self.http = HttpClient()
        self._items: dict[str, Connection] = {}

    async def close(self) -> None:
        """Arrête les device flows en attente, ferme le client."""
        tasks = [c.task for c in self._items.values() if c.task is not None and not c.task.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.http.aclose()

    def get(self, connection_id: str) -> Connection | None:
        connection = self._items.get(connection_id)
        if connection is not None:
            self._expire(connection)
        return connection

    def pending(self, forge: ForgeKind) -> Connection | None:
        """La connexion en attente pour ``forge``, s'il y en a une."""
        for connection in reversed(self._items.values()):
            self._expire(connection)
            if connection.forge is forge and connection.pending:
                return connection
        return None

    def cancel(self, connection: Connection) -> None:
        if connection.pending:
            connection.end(ConnectionStatus.CANCELLED)
            if connection.task is not None:
                connection.task.cancel()

    # -- OAuth ---------------------------------------------------------------------

    def start_oauth(self, forge: ForgeKind) -> Connection:
        """Une connexion par la page d'autorisation de la forge ; ``authorize_url`` dit où
        envoyer le navigateur."""
        connection = self._add(forge, ConnectMethod.OAUTH, _now() + OAUTH_TTL)
        connection.state = secrets.token_urlsafe(32)
        connection.verifier = github.new_verifier()
        connection.redirect_to = github.redirect_uri(self.port)
        connection.authorize_url = github.authorization_url(
            self.app,
            redirect_to=connection.redirect_to,
            state=connection.state,
            verifier=connection.verifier,
        )
        return connection

    def by_state(self, forge: ForgeKind, state: str) -> Connection | None:
        """La connexion OAuth qui attend ce ``state`` au retour ; ``None`` s'il n'est pas
        connu (déjà servi, ou jamais donné)."""
        if not state:
            return None
        given = state.encode()
        for connection in self._items.values():
            expected = connection.state
            if (
                connection.forge is forge
                and connection.method is ConnectMethod.OAUTH
                and expected is not None
                and secrets.compare_digest(given, expected.encode())
            ):
                return connection
        return None

    async def finish_oauth(
        self, connection: Connection, *, code: str, error: str = "", description: str = ""
    ) -> None:
        """Le retour de la forge : échange le code contre le token, puis range le compte."""
        verifier, redirect_to = connection.verifier, connection.redirect_to
        connection.state = None  # un state ne sert qu'une fois
        self._expire(connection)
        if not connection.pending:
            return
        if error:
            connection.end(ConnectionStatus.FAILED, github.authorization_error(error, description))
            return
        if not code or verifier is None or redirect_to is None:
            connection.end(ConnectionStatus.FAILED, "GitHub n'a pas rendu de code d'autorisation.")
            return
        try:
            token = await github.exchange_code(
                self.http, self.app, code=code, redirect_to=redirect_to, verifier=verifier
            )
            account = await accounts_module.connect(
                self.accounts, self.http, connection.forge, token, ConnectMethod.OAUTH
            )
        except (ForgeError, NetworkError, AccountsError) as err:
            connection.end(ConnectionStatus.FAILED, failure(err, connection.forge))
            return
        if connection.pending:  # pas annulée pendant l'échange
            connection.end(ConnectionStatus.DONE, account=account)

    # -- Device flow ---------------------------------------------------------------

    async def start_device(self, forge: ForgeKind) -> Connection:
        """Demande un code à la forge, et attend qu'il soit tapé (tâche de fond). Lève
        ``ForgeError`` ou ``NetworkError`` si la forge ne donne pas de code."""
        device = await github.start_device(self.http, self.app)
        expires_at = _now() + timedelta(seconds=device.expires_in)
        connection = self._add(forge, ConnectMethod.DEVICE, expires_at)
        connection.device = device
        connection.task = asyncio.create_task(self._wait_device(connection, device))
        return connection

    async def _wait_device(self, connection: Connection, device: DeviceCode) -> None:
        try:
            token = await github.wait_device(self.http, self.app, device)
            account = await accounts_module.connect(
                self.accounts, self.http, connection.forge, token, ConnectMethod.DEVICE
            )
        except DeviceExpired as err:
            connection.end(ConnectionStatus.EXPIRED, str(err))
        except (ForgeError, NetworkError, AccountsError) as err:
            connection.end(ConnectionStatus.FAILED, failure(err, connection.forge))
        except asyncio.CancelledError:
            if connection.pending:
                connection.end(ConnectionStatus.CANCELLED)
            raise
        else:
            if connection.pending:
                connection.end(ConnectionStatus.DONE, account=account)

    # -- interne -------------------------------------------------------------------

    def _add(self, forge: ForgeKind, method: ConnectMethod, expires_at: datetime) -> Connection:
        """Une nouvelle connexion ; celle qui attendait pour la même forge est annulée."""
        for other in self._items.values():
            if other.forge is forge:
                self.cancel(other)
        connection = Connection(
            id=secrets.token_hex(6), forge=forge, method=method, expires_at=expires_at
        )
        self._items[connection.id] = connection
        while len(self._items) > MAX_CONNECTIONS:
            oldest = next((c for c in self._items.values() if not c.pending), None)
            if oldest is None:
                break
            del self._items[oldest.id]
        return connection

    def _expire(self, connection: Connection) -> None:
        if connection.pending and _now() >= connection.expires_at:
            if connection.task is not None:
                connection.task.cancel()
            connection.end(ConnectionStatus.EXPIRED, _EXPIRED[connection.method])


_EXPIRED = {
    ConnectMethod.OAUTH: "La demande de connexion a expiré (10 min) : recommencer.",
    ConnectMethod.DEVICE: "Le code a expiré avant d'être saisi : en demander un autre.",
}


def failure(error: Exception, forge: ForgeKind) -> str:
    """Le message d'un échec de connexion, en phrase."""
    if isinstance(error, NetworkError):
        return f"{info(forge).name} ne répond pas : {error}"
    return str(error)
