"""Les comptes connectés aux forges.

- **Le token** est rangé dans le trousseau du système (``keyring`` : le Gestionnaire
  d'identification de Windows, le trousseau de macOS, Secret Service sous Linux), au service
  ``forceupdate``, sous le nom ``<forge>:<hôte>`` (``github:github.com``). Il n'en sort que pour
  parler à la forge : jamais affiché, jamais dans un journal ni un message, jamais envoyé au
  navigateur.
- **Le reste** (identifiant, nom, droits, façon de se connecter, dates) est dans
  ``accounts.json``, dans le dossier d'état de l'utilisateur, sans aucun secret.

Un compte n'existe que si son token est dans le trousseau : un token effacé à la main du
trousseau fait disparaître le compte. Se déconnecter efface les deux. Un compte par forge et
par hôte.
"""

import asyncio
import contextlib
import enum
import json
import logging
import os
import threading
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import keyring
import keyring.errors

from forceupdate.forges import client
from forceupdate.forges.base import Access, ForgeKind, Identity, TokenRefused
from forceupdate.models import to_dict
from forceupdate.net import HttpClient

logger = logging.getLogger(__name__)

SERVICE = "forceupdate"
"""Le service des tokens dans le trousseau."""


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

    def unavailable(self) -> str | None:
        """Pourquoi le trousseau ne peut pas servir ; ``None`` s'il marche."""
        try:
            keyring.get_password(SERVICE, "forceupdate:essai")
        except keyring.errors.KeyringError as err:
            logger.warning("trousseau indisponible : %s", type(err).__name__)
            return (
                "Aucun trousseau du système n'est utilisable : les tokens ne peuvent pas être "
                "gardés. Sous Linux, installer un service de trousseau (GNOME Keyring, "
                "KWallet)."
            )
        return None

    def connected(self) -> list[Account]:
        """Les comptes dont le token est dans le trousseau, par forge."""
        return [account for account in self._load() if self._token(account) is not None]

    def get(self, forge: ForgeKind, host: str) -> Account | None:
        found = next((a for a in self._load() if (a.forge, a.host) == (forge, host)), None)
        return found if found is not None and self._token(found) is not None else None

    def token(self, forge: ForgeKind, host: str) -> str | None:
        """Le token du compte, pour parler à la forge ; ``None`` s'il n'y en a pas."""
        account = self.get(forge, host)
        return None if account is None else self._token(account)

    def save(self, identity: Identity, token: str, method: ConnectMethod) -> Account:
        """Range le token d'``identity`` et son compte ; remplace celui qui était connecté à
        la même forge."""
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
        try:
            keyring.set_password(SERVICE, _key(account.forge, account.host), token)
        except keyring.errors.KeyringError as err:
            raise AccountsError(
                f"Le trousseau du système refuse de garder le token ({type(err).__name__})."
            ) from None
        self._store(account)
        return account

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
        révoquer auprès de la forge), ou ``(None, None)`` s'il n'y en avait pas."""
        account = next((a for a in self._load() if (a.forge, a.host) == (forge, host)), None)
        token = None
        with contextlib.suppress(keyring.errors.KeyringError):
            token = keyring.get_password(SERVICE, _key(forge, host))
        if token is not None:
            try:
                keyring.delete_password(SERVICE, _key(forge, host))
            except keyring.errors.PasswordDeleteError:
                pass
            except keyring.errors.KeyringError as err:
                raise AccountsError(
                    f"Le trousseau du système refuse d'effacer le token ({type(err).__name__})."
                ) from None
        with self._lock:
            self._write([a for a in self._load() if (a.forge, a.host) != (forge, host)])
        return (account if token is not None else None), token

    def _token(self, account: Account) -> str | None:
        try:
            return keyring.get_password(SERVICE, _key(account.forge, account.host))
        except keyring.errors.KeyringError as err:
            raise AccountsError(
                f"Le trousseau du système ne répond pas ({type(err).__name__})."
            ) from None

    def _store(self, account: Account) -> None:
        with self._lock:
            key = (account.forge, account.host)
            others = [a for a in self._load() if (a.forge, a.host) != key]
            self._write(sorted([*others, account], key=lambda a: list(ForgeKind).index(a.forge)))

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
    accounts: Accounts, http: HttpClient, forge: ForgeKind, token: str, method: ConnectMethod
) -> Account:
    """Vérifie ``token`` auprès de la forge (``whoami``), puis range le compte. Lève
    ``TokenRefused`` (ou une autre ``ForgeError``) si la forge le refuse, ``NetworkError`` si
    elle ne répond pas, ``AccountsError`` si le trousseau ne le garde pas."""
    identity = await client(forge, http, token).whoami()
    return await asyncio.to_thread(accounts.save, identity, token, method)


async def verify(accounts: Accounts, http: HttpClient, account: Account) -> Account:
    """Redemande à la forge qui est connecté et avec quels droits. Un token refusé est noté
    dans ``problem`` (le compte reste, pour qu'on le voie et qu'on se reconnecte) ; une forge
    injoignable lève ``NetworkError``."""
    token = await asyncio.to_thread(accounts.token, account.forge, account.host)
    if token is None:
        raise AccountsError("Le token n'est plus dans le trousseau : se reconnecter.")
    try:
        identity = await client(account.forge, http, token).whoami()
    except TokenRefused as err:
        return await asyncio.to_thread(accounts.refused, account, str(err))
    return await asyncio.to_thread(accounts.checked, account, identity)


def _key(forge: ForgeKind, host: str) -> str:
    return f"{forge.value}:{host}"


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
