"""Les comptes connectés aux forges.

- **Le token** est rangé dans le trousseau du système (``keyring`` : le Gestionnaire
  d'identification de Windows, le trousseau de macOS, Secret Service sous Linux), au service
  ``forceupdate``, sous le nom ``<forge>:<hôte>`` (``github:github.com``). Il n'en sort que pour
  parler à la forge : jamais affiché, jamais dans un journal ni un message, jamais envoyé au
  navigateur. Un token qui expire (GitLab et Bitbucket, par OAuth : 2 h) y est rangé avec son
  refresh token et son heure d'expiration, en JSON ; ``renewer`` le renouvelle quand il le faut,
  un seul renouvellement à la fois pour un compte, d'où qu'il vienne (boucle du serveur, boucle
  des analyses) : le refresh token ne sert qu'une fois. Un secret trop long pour une entrée du
  trousseau (Windows : 1 280 caractères ; un token de Bitbucket en a plus de 2 000) est découpé
  en morceaux (``MAX_PART``).
- **Le reste** (identifiant, nom, droits, façon de se connecter, dates) est dans
  ``accounts.json``, dans le dossier d'état de l'utilisateur, sans aucun secret.

Un compte n'existe que si son token est dans le trousseau : un token effacé à la main du
trousseau fait disparaître le compte. Se déconnecter efface les deux. Un compte par forge et
par hôte : un compte gitlab.com et un compte de chaque instance GitLab auto-hébergée.
"""

import asyncio
import contextlib
import enum
import json
import logging
import os
import threading
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import keyring
import keyring.errors

from forceupdate.forges import HOSTS, client, label
from forceupdate.forges.base import (
    Access,
    ForgeKind,
    Grant,
    Identity,
    OAuthFlow,
    Renew,
    TokenRefused,
)
from forceupdate.models import to_dict
from forceupdate.net import HttpClient

logger = logging.getLogger(__name__)

SERVICE = "forceupdate"
"""Le service des tokens dans le trousseau."""

RENEW_MARGIN = timedelta(minutes=5)
"""Un token qui expire dans moins de ce temps est renouvelé avant de servir."""
WAIT_STEP = 0.05
"""Secondes entre deux essais de prendre le verrou du renouvellement d'un compte."""
MAX_PART = 1000
"""Caractères au plus d'une entrée du trousseau. Le Gestionnaire d'identification de Windows
refuse un secret de plus de 2 560 octets, soit 1 280 caractères en UTF-16 (vérifié à E20 :
erreur 1783), et un token d'OAuth de Bitbucket en a plus de 2 000 : au-delà, le secret est
rangé en morceaux (``<forge>:<hôte>#1``, ``#2``…), l'entrée du compte disant combien."""
_PARTS = "forceupdate-parts:"
"""Ce par quoi commence l'entrée d'un compte dont le secret est en morceaux (un token ne
commence jamais ainsi)."""


class ConnectMethod(enum.StrEnum):
    """Comment un compte a été connecté."""

    OAUTH = "oauth"
    """Par la page d'autorisation de la forge."""
    DEVICE = "device"
    """Par un code tapé sur la forge (device flow)."""
    TOKEN = "token"
    """Un token collé."""
    GH = "gh"
    """Le token de GitHub CLI."""

    @property
    def from_app(self) -> bool:
        """Le token a été donné à forceupdate : se déconnecter le révoque auprès de la forge.
        Un token collé ou celui de gh appartiennent à la personne, ou à gh : jamais révoqués."""
        return self in (ConnectMethod.OAUTH, ConnectMethod.DEVICE)


@dataclass(frozen=True, kw_only=True)
class Account:
    """Un compte connecté. Jamais son token."""

    forge: ForgeKind
    host: str
    login: str
    name: str | None
    url: str
    """Son profil, sur la forge."""
    access: Access
    scopes: tuple[str, ...] | None
    """Les portées du token ; ``null`` si la forge ne les dit pas (``access`` : ``unknown``)."""
    warnings: tuple[str, ...]
    """Ce qui manquera, avec ces droits."""
    method: ConnectMethod
    connected_at: datetime
    checked_at: datetime
    """La dernière fois que la forge a accepté le token."""
    problem: str | None
    """Ce qui n'allait pas au dernier contrôle (token refusé…) ; ``null`` si rien."""


class AccountsError(Exception):
    """Le trousseau du système ne marche pas. Le message, en français, le dit."""


class Accounts:
    """Les comptes connectés : tokens dans le trousseau, le reste dans ``path``
    (``accounts.json``).

    Les routes l'appellent depuis plusieurs threads (``asyncio.to_thread``) : le fichier n'est lu
    et réécrit que sous un verrou. Sans lui, deux réécritures se marchent dessus, et sous Windows
    un fichier lu pendant son ``os.replace`` fait échouer l'un ou l'autre (trouvé à E16 : le compte
    disparaissait de l'écran le temps d'une relecture des droits)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._renewing: dict[tuple[ForgeKind, str], threading.Lock] = {}

    def unavailable(self) -> str | None:
        """Pourquoi le trousseau ne peut pas servir ; ``None`` s'il marche."""
        try:
            keyring.get_password(SERVICE, "forceupdate:essai")
        except keyring.errors.KeyringError as err:
            logger.warning("trousseau indisponible : %s", type(err).__name__)
            return (
                "Aucun trousseau du système n'est utilisable : les tokens ne peuvent pas être "
                "gardés. Sous Linux (serveur, WSL), installer un service de trousseau (GNOME "
                "Keyring, KWallet), ou en choisir un autre par PYTHON_KEYRING_BACKEND : voir la "
                "documentation."
            )
        return None

    def connected(self) -> list[Account]:
        """Les comptes dont le token est dans le trousseau, par forge (le service en ligne
        avant les instances)."""
        return [account for account in self._load() if self._token(account) is not None]

    def get(self, forge: ForgeKind, host: str) -> Account | None:
        found = next((a for a in self._load() if (a.forge, a.host) == (forge, host)), None)
        return found if found is not None and self._token(found) is not None else None

    def token(self, forge: ForgeKind, host: str) -> str | None:
        """Le token du compte, pour parler à la forge ; ``None`` s'il n'y en a pas. Il peut
        avoir expiré : ``renewer`` le renouvelle."""
        grant = self.grant(forge, host)
        return None if grant is None else grant.access_token

    def grant(self, forge: ForgeKind, host: str) -> Grant | None:
        """Le token du compte, avec son refresh token et son expiration s'il en a."""
        account = self.get(forge, host)
        if account is None:
            return None
        stored = self._token(account)
        return None if stored is None else _grant(stored)

    def renewed(self, forge: ForgeKind, host: str, grant: Grant) -> None:
        """Range les tokens qui remplacent ceux du compte (renouvelés)."""
        self._keep(forge, host, grant)

    def renewing(self, forge: ForgeKind, host: str) -> threading.Lock:
        """Le verrou du renouvellement du token d'un compte."""
        with self._lock:
            return self._renewing.setdefault((forge, host), threading.Lock())

    def save(self, identity: Identity, token: str | Grant, method: ConnectMethod) -> Account:
        """Range le token d'``identity`` et son compte ; remplace celui qui était connecté à
        la même forge, sur le même hôte."""
        now = _now()
        account = Account(
            forge=identity.forge,
            host=identity.host,
            login=identity.login,
            name=identity.name,
            url=identity.url,
            access=identity.access,
            scopes=identity.scopes,
            warnings=identity.warnings,
            method=method,
            connected_at=now,
            checked_at=now,
            problem=None,
        )
        self._keep(account.forge, account.host, token)
        self._store(account)
        return account

    def _keep(self, forge: ForgeKind, host: str, token: str | Grant) -> None:
        try:
            self._write_secret(_key(forge, host), _stored(token))
        except keyring.errors.KeyringError as err:
            raise AccountsError(
                f"Le trousseau du système refuse de garder le token ({type(err).__name__})."
            ) from None

    def _read_secret(self, key: str) -> str | None:
        """Le secret rangé sous ``key``, remis bout à bout s'il est en morceaux ; ``None`` s'il
        n'y en a pas (ou qu'un morceau manque)."""
        with self._lock:
            stored = keyring.get_password(SERVICE, key)
            count = _part_count(stored)
            if count is None:
                return stored
            parts = [keyring.get_password(SERVICE, f"{key}#{n}") for n in range(1, count + 1)]
        if any(part is None for part in parts):
            logger.warning("trousseau : un morceau du token de %s manque", key)
            return None
        return "".join(part or "" for part in parts)

    def _write_secret(self, key: str, secret: str) -> None:
        """Range ``secret`` sous ``key``, en morceaux s'il est trop long : les morceaux d'abord,
        puis l'entrée qui dit leur nombre ; ceux d'avant qui ne servent plus sont effacés. Sous
        le verrou : jamais un mélange de deux secrets."""
        parts = [secret[i : i + MAX_PART] for i in range(0, len(secret), MAX_PART)]
        with self._lock:
            before = _part_count(keyring.get_password(SERVICE, key)) or 0
            if len(parts) <= 1:
                keyring.set_password(SERVICE, key, secret)
                kept = 0
            else:
                for n, part in enumerate(parts, start=1):
                    keyring.set_password(SERVICE, f"{key}#{n}", part)
                keyring.set_password(SERVICE, key, f"{_PARTS}{len(parts)}")
                kept = len(parts)
            for n in range(kept + 1, before + 1):
                with contextlib.suppress(keyring.errors.PasswordDeleteError):
                    keyring.delete_password(SERVICE, f"{key}#{n}")

    def _delete_secret(self, key: str) -> None:
        """Efface le secret de ``key`` et ses morceaux."""
        with self._lock:
            count = _part_count(keyring.get_password(SERVICE, key)) or 0
            for n in range(1, count + 1):
                with contextlib.suppress(keyring.errors.PasswordDeleteError):
                    keyring.delete_password(SERVICE, f"{key}#{n}")
            keyring.delete_password(SERVICE, key)

    def checked(self, account: Account, identity: Identity) -> Account:
        """Le compte, après un contrôle accepté par la forge : droits relus."""
        updated = replace(
            account,
            login=identity.login,
            name=identity.name,
            url=identity.url,
            access=identity.access,
            scopes=identity.scopes,
            warnings=identity.warnings,
            checked_at=_now(),
            problem=None,
        )
        self._store(updated)
        return updated

    def refused(self, account: Account, problem: str) -> Account:
        """Le compte, quand la forge refuse son token."""
        updated = replace(account, problem=problem)
        self._store(updated)
        return updated

    def remove(self, forge: ForgeKind, host: str) -> tuple[Account | None, str | None]:
        """Efface le token du trousseau et le compte ; rend le compte et son token (pour le
        révoquer auprès de la forge : le token, pas son refresh token), ou ``(None, None)``
        s'il n'y en avait pas."""
        account = next((a for a in self._load() if (a.forge, a.host) == (forge, host)), None)
        token = None
        with contextlib.suppress(keyring.errors.KeyringError):
            token = self._read_secret(_key(forge, host))
        if token is not None:
            try:
                self._delete_secret(_key(forge, host))
            except keyring.errors.PasswordDeleteError:
                pass
            except keyring.errors.KeyringError as err:
                raise AccountsError(
                    f"Le trousseau du système refuse d'effacer le token ({type(err).__name__})."
                ) from None
        with self._lock:
            self._write([a for a in self._load() if (a.forge, a.host) != (forge, host)])
        if token is None:
            return None, None
        return account, _grant(token).access_token

    def _token(self, account: Account) -> str | None:
        try:
            return self._read_secret(_key(account.forge, account.host))
        except keyring.errors.KeyringError as err:
            raise AccountsError(
                f"Le trousseau du système ne répond pas ({type(err).__name__})."
            ) from None

    def _store(self, account: Account) -> None:
        with self._lock:
            key = (account.forge, account.host)
            others = [a for a in self._load() if (a.forge, a.host) != key]
            self._write(sorted([*others, account], key=_order))

    def _load(self) -> list[Account]:
        try:
            with self._lock:
                document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        items = document.get("accounts") if isinstance(document, dict) else None
        found = []
        for item in items if isinstance(items, list) else []:
            account = _account(item)
            if account is not None:
                found.append(account)
        return found

    def _write(self, accounts: list[Account]) -> None:
        """Réécrit le fichier ; à appeler sous ``_lock``."""
        document = {"version": 1, "accounts": [to_dict(account) for account in accounts]}
        text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(text, encoding="utf-8", newline="\n")
        os.replace(temporary, self.path)


async def connect(
    accounts: Accounts,
    http: HttpClient,
    forge: ForgeKind,
    token: str | Grant,
    method: ConnectMethod,
    *,
    host: str | None = None,
) -> Account:
    """Vérifie ``token`` auprès de la forge (``whoami``, sur ``host`` : par défaut son service
    en ligne), puis range le compte. Lève ``TokenRefused`` (ou une autre ``ForgeError``) si la
    forge le refuse, ``NetworkError`` si elle ne répond pas, ``AccountsError`` si le trousseau
    ne le garde pas."""
    access = token.access_token if isinstance(token, Grant) else token
    identity = await client(forge, http, access, host=host).whoami()
    return await asyncio.to_thread(accounts.save, identity, token, method)


async def verify(
    accounts: Accounts, http: HttpClient, account: Account, *, renew: Renew | None = None
) -> Account:
    """Redemande à la forge qui est connecté et avec quels droits (le token renouvelé s'il a
    expiré). Un token refusé est noté dans ``problem`` (le compte reste, pour qu'on le voie et
    qu'on se reconnecte) ; une forge injoignable lève ``NetworkError``."""
    token = await asyncio.to_thread(accounts.token, account.forge, account.host)
    if token is None:
        raise AccountsError("Le token n'est plus dans le trousseau : se reconnecter.")
    try:
        if renew is not None:
            token = await renew(http, None)
        forge = client(account.forge, http, token, host=account.host, renew=renew)
        identity = await forge.whoami()
    except TokenRefused as err:
        return await asyncio.to_thread(accounts.refused, account, str(err))
    return await asyncio.to_thread(accounts.checked, account, identity)


def renewer(accounts: Accounts, account: Account, flow: OAuthFlow) -> Renew:
    """Ce qui renouvelle le token d'``account`` (connecté par l'application ``flow``) : avant
    qu'il expire, ou quand la forge refuse celui qu'on lui passe. Un seul renouvellement à la
    fois pour un compte : celui qui attend son tour relit le trousseau, et prend le token que
    l'autre vient d'obtenir. Lève ``TokenRefused`` si le token ne se renouvelle pas (refresh
    token refusé, ou absent : un token qui n'expire pas a été révoqué)."""
    key = (account.forge, account.host)
    name = label(account.forge, account.host)
    gone = f"{name} : le token n'est plus dans le trousseau, se reconnecter."

    async def renew(http: HttpClient, refused: str | None) -> str:
        grant = await asyncio.to_thread(accounts.grant, *key)
        if grant is None:
            raise TokenRefused(gone)
        if not _stale(grant, refused):
            return grant.access_token
        lock = accounts.renewing(*key)
        while not lock.acquire(blocking=False):  # sans bloquer la boucle, ni rester pris
            await asyncio.sleep(WAIT_STEP)
        try:
            grant = await asyncio.to_thread(accounts.grant, *key)
            if grant is None:
                raise TokenRefused(gone)
            if not _stale(grant, refused):
                return grant.access_token  # renouvelé par un autre pendant l'attente
            if grant.refresh_token is None:
                raise TokenRefused(f"{name} refuse le token : révoqué, ou expiré. Se reconnecter.")
            fresh = await flow.refresh(http, grant.refresh_token)
            await asyncio.to_thread(accounts.renewed, *key, fresh)
            logger.info("%s : token renouvelé", name)
            return fresh.access_token
        finally:
            lock.release()

    return renew


def _stale(grant: Grant, refused: str | None) -> bool:
    """Le token est à renouveler : la forge vient de le refuser, ou il expire bientôt."""
    if refused is not None and grant.access_token == refused:
        return True
    return grant.expires_at is not None and grant.expires_at - _now() < RENEW_MARGIN


def _key(forge: ForgeKind, host: str) -> str:
    return f"{forge.value}:{host}"


def _part_count(stored: str | None) -> int | None:
    """Le nombre de morceaux d'un secret rangé en morceaux ; ``None`` s'il est d'un seul
    tenant (ou absent)."""
    if stored is None or not stored.startswith(_PARTS):
        return None
    count = stored.removeprefix(_PARTS)
    return int(count) if count.isdigit() and int(count) > 0 else None


def _order(account: Account) -> tuple[int, bool, str]:
    """Par forge, le service en ligne avant les instances, puis par hôte."""
    return list(ForgeKind).index(account.forge), account.host != HOSTS[account.forge], account.host


def _stored(token: str | Grant) -> str:
    """Ce qui va dans le trousseau : le token seul, ou en JSON avec son refresh token et son
    expiration."""
    if isinstance(token, str):
        return token
    if token.refresh_token is None and token.expires_at is None:
        return token.access_token
    return json.dumps(
        {
            "access_token": token.access_token,
            "refresh_token": token.refresh_token,
            "expires_at": token.expires_at.isoformat() if token.expires_at else None,
        }
    )


def _grant(stored: str) -> Grant:
    """Ce qu'on a lu dans le trousseau (un token seul n'est jamais du JSON)."""
    if not stored.startswith("{"):
        return Grant(access_token=stored)
    try:
        document = json.loads(stored)
        expires = document.get("expires_at")
        refresh = document.get("refresh_token")
        return Grant(
            access_token=str(document["access_token"]),
            refresh_token=refresh if isinstance(refresh, str) else None,
            expires_at=datetime.fromisoformat(expires) if isinstance(expires, str) else None,
        )
    except (ValueError, KeyError, TypeError, AttributeError):
        return Grant(access_token=stored)


def _now() -> datetime:
    return datetime.now(UTC)


def _account(item: Any) -> Account | None:
    """Un compte lu dans ``accounts.json`` ; ``None`` s'il est illisible."""
    if not isinstance(item, dict):
        return None
    try:
        scopes = item.get("scopes")
        return Account(
            forge=ForgeKind(item["forge"]),
            host=str(item["host"]),
            login=str(item["login"]),
            name=item.get("name") if isinstance(item.get("name"), str) else None,
            url=str(item["url"]),
            access=Access(item["access"]),
            scopes=None if scopes is None else tuple(str(scope) for scope in scopes),
            warnings=tuple(str(text) for text in item.get("warnings") or ()),
            method=ConnectMethod(item["method"]),
            connected_at=datetime.fromisoformat(item["connected_at"]),
            checked_at=datetime.fromisoformat(item["checked_at"]),
            problem=item.get("problem") if isinstance(item.get("problem"), str) else None,
        )
    except (KeyError, TypeError, ValueError):
        return None
