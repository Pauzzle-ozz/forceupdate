"""L'interface commune des forges : GitHub (E16 à E18), GitLab (E19), Bitbucket Cloud (E20).

Le reste de l'outil ne connaît que ``Forge`` et les types de ce module (PLAN, phase E). Une
forge se pilote avec le token d'un compte connecté (``forges.accounts``) ; elle parle par l'API
REST de la forge, avec le ``HttpClient`` commun, et par git pour cloner et pousser.

Ce que fait chaque méthode, et à quelle étape elle arrive :

- ``whoami`` : qui est connecté, et ce que le token permet (E16) ;
- ``list_repos``, ``repository``, ``restrictions``, ``tree``, ``read_file`` : les dépôts (et
  les organisations dont ils ne sont pas tous lisibles), et de quoi les analyser sans les
  cloner (E17) ;
- ``clone``, ``branch``, ``push_branch`` : cloner pour mettre à jour, voir où en est la branche
  de forceupdate sur la forge, la pousser (E18) ;
- ``find_open_request``, ``open_or_update_request`` : la PR (MR sur GitLab), idempotente (E18).

Une réponse d'erreur de la forge lève une ``ForgeError`` (message en français, fait pour être
montré) ; une requête qui n'aboutit pas lève ``net.NetworkError``.
"""

import abc
import base64
import enum
import hashlib
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from forceupdate.net import HttpClient


class ForgeKind(enum.StrEnum):
    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"


class Access(enum.StrEnum):
    """Ce que permet un token, d'après ses droits."""

    WRITE = "write"
    """Lire les dépôts, publics et privés, pousser une branche, ouvrir une PR."""
    PUBLIC = "public"
    """La même chose, sur les dépôts publics seulement."""
    READ = "read"
    """Lire les dépôts, rien de plus : les publics seulement sur GitHub, ceux du compte aussi
    sur GitLab (portée ``read_api``)."""
    UNKNOWN = "unknown"
    """Droits non vérifiés : la forge ne les dit pas (token « fine-grained » de GitHub, qui n'a
    pas d'en-tête ``X-OAuth-Scopes``). Ce qu'il permet ne se saura qu'en essayant."""


@dataclass(frozen=True, kw_only=True)
class Identity:
    """Le compte d'un token (``Forge.whoami``)."""

    forge: ForgeKind
    host: str
    """``github.com`` ; l'hôte d'une instance GitLab auto-hébergée."""
    login: str
    name: str | None
    """Le nom affiché du compte, s'il en a un."""
    url: str
    """Son profil, sur la forge."""
    access: Access
    scopes: tuple[str, ...] | None
    """Les portées du token, telles que la forge les donne ; ``None`` si elle ne les donne
    pas (``Access.UNKNOWN``)."""
    warnings: tuple[str, ...]
    """Ce qui manquera, avec ces droits (une portée absente…)."""
    email: str | None = None
    """L'adresse des commits faits au nom du compte : son adresse ``noreply`` (GitHub
    ``{id}+{login}@users.noreply.github.com``, GitLab ``{id}-{login}@users.noreply.{hôte}``),
    qui les rattache au compte sans dévoiler la vraie."""


@dataclass(frozen=True, kw_only=True)
class Grant:
    """Les tokens qu'une forge donne à la connexion d'un compte (OAuth, device flow), ou un
    token collé."""

    access_token: str = field(repr=False)
    refresh_token: str | None = field(default=None, repr=False)
    """De quoi en obtenir un nouveau quand il expire (GitLab : à usage unique, il est remplacé
    à chaque renouvellement) ; ``None`` : il n'expire pas, ou ne se renouvelle pas."""
    expires_at: datetime | None = None
    """Quand l'``access_token`` expire (GitLab : 2 h après sa création) ; ``None`` : jamais,
    ou on ne le sait pas."""


Renew = Callable[[HttpClient, str | None], Awaitable[str]]
"""Ce qui donne à une forge un token à jour : renouvelé s'il expire bientôt, ou si c'est
celui qu'on lui passe (que la forge vient de refuser). Il reçoit le ``HttpClient`` de la forge
(celui de sa boucle). Lève ``TokenRefused`` si le renouvellement est refusé."""


@dataclass(frozen=True, kw_only=True)
class RateLimit:
    """Les requêtes d'API restantes, d'après la dernière réponse de la forge."""

    limit: int
    remaining: int
    reset_at: datetime


@dataclass(frozen=True, kw_only=True)
class Repository:
    """Un dépôt accessible au compte (``Forge.list_repos``)."""

    forge: ForgeKind
    host: str
    full_name: str
    """``owner/nom`` (sur GitLab, le chemin complet du projet, groupes compris)."""
    default_branch: str | None
    """``None`` pour un dépôt vide."""
    private: bool
    archived: bool
    fork: bool
    can_push: bool
    url: str
    """La page du dépôt, sur la forge."""
    clone_url: str
    """L'adresse HTTPS pour cloner, sans identifiants."""
    empty: bool = False
    """Aucun commit : rien à analyser."""
    language: str | None = None
    """Le langage principal, d'après la forge ; l'analyse donne les autres."""
    pushed_at: datetime | None = None
    """Le dernier push."""

    @property
    def owner(self) -> str:
        """Le propriétaire : compte, organisation, ou groupe (GitLab)."""
        return self.full_name.rpartition("/")[0]

    @property
    def name(self) -> str:
        return self.full_name.rpartition("/")[2]


class RestrictionKind(enum.StrEnum):
    """Pourquoi les dépôts d'une organisation ne sont pas tous lisibles."""

    APP_ACCESS = "app_access"
    """L'organisation restreint l'accès des applications OAuth (GitHub) : ses dépôts privés
    n'apparaissent qu'après l'accord d'un de ses propriétaires."""
    SSO = "sso"
    """L'organisation exige que le token soit autorisé pour son SSO (SAML)."""


@dataclass(frozen=True, kw_only=True)
class Restriction:
    """Une organisation dont le compte est membre, mais dont les dépôts ne sont pas tous
    lisibles avec ce token (``Forge.restrictions``) : à dire, pas à cacher."""

    organization: str
    kind: RestrictionKind
    url: str | None
    """Où demander l'accès, ou autoriser le token."""


@dataclass(frozen=True, kw_only=True)
class TreeEntry:
    """Un fichier de l'arborescence d'un dépôt."""

    path: str
    """Chemin POSIX, depuis la racine du dépôt."""
    size: int | None
    """En octets ; ``None`` si la forge ne la donne pas (GitLab)."""


@dataclass(frozen=True, kw_only=True)
class Tree:
    """L'arborescence d'une branche (``Forge.tree``) : les fichiers, pas les dossiers."""

    commit: str
    """Le commit lu : les fichiers se lisent à ce commit (``read_file``)."""
    entries: tuple[TreeEntry, ...]
    truncated: bool
    """La forge n'a pas tout rendu (GitHub, au-delà de 100 000 entrées ; GitLab, au-delà de
    ``gitlab.MAX_TREE_PAGES`` pages) : cloner."""


@dataclass(frozen=True, kw_only=True)
class ChangeRequest:
    """Une pull request (merge request sur GitLab)."""

    number: int
    """``#41`` sur GitHub et Bitbucket, ``!12`` sur GitLab."""
    url: str
    title: str
    branch: str
    """La branche proposée (``forceupdate/dependencies``)."""
    base: str
    """La branche visée (celle par défaut)."""


@dataclass(frozen=True, kw_only=True)
class BranchCommit:
    """Un commit d'une branche, qui n'est pas sur la branche par défaut."""

    sha: str
    message: str
    merge: bool
    """Un commit de fusion (plusieurs parents) : « Update branch » de GitHub (« Merge » de
    la branche visée sur GitLab), qui ne fait qu'apporter la branche par défaut."""


@dataclass(frozen=True, kw_only=True)
class Branch:
    """Une branche d'un dépôt, sur la forge (``Forge.branch``)."""

    name: str
    head: str
    """Son dernier commit."""
    tree: str | None
    """L'arbre de son dernier commit ; ``None`` si elle n'a aucun commit à elle (déjà fusionnée,
    ou en retard sur la branche par défaut)."""
    commits: tuple[BranchCommit, ...]
    """Ses commits qui ne sont pas sur la branche par défaut, du plus ancien au plus récent
    (la forge peut n'en rendre qu'une partie : ``ahead`` dit combien il y en a)."""
    ahead: int
    """Le nombre de ses commits qui ne sont pas sur la branche par défaut."""


class ForgeError(Exception):
    """La forge a refusé une requête. Le message, en français, dit ce qui s'est passé et quoi
    faire ; il ne contient jamais de token."""


class TokenRefused(ForgeError):
    """401 : le token est révoqué, expiré ou faux."""


class AccessDenied(ForgeError):
    """403 : le token n'a pas le droit (portée, organisation, SSO)."""


class AppRestricted(AccessDenied):
    """403 : l'organisation restreint l'accès des applications OAuth (GitHub)."""


class SsoRequired(AccessDenied):
    """403 : l'organisation exige d'autoriser le token pour son SSO (SAML)."""

    def __init__(self, message: str, *, url: str | None = None) -> None:
        super().__init__(message)
        self.url = url


class NotFound(ForgeError):
    """404 : la ressource n'existe pas, ou le token ne la voit pas. Un dépôt privé que le
    token ne voit pas rend aussi 404 (pas 403) sur GitHub."""


class EmptyRepository(ForgeError):
    """Le dépôt n'a aucun commit : rien à lire."""


class RateLimited(ForgeError):
    """La limite de requêtes de l'API est atteinte."""

    def __init__(self, message: str, *, reset_at: datetime | None = None) -> None:
        super().__init__(message)
        self.reset_at = reset_at


class Forge(abc.ABC):
    """Une forge, vue avec le token d'un compte."""

    kind: ClassVar[ForgeKind]
    host: str

    @abc.abstractmethod
    async def whoami(self) -> Identity:
        """Le compte du token, et ce que le token permet. Lève ``TokenRefused`` si la forge
        le refuse."""

    requests: int
    """Les requêtes d'API envoyées par ce client, pour dire ce qu'une analyse consomme."""
    rate_limit: RateLimit | None
    """Les requêtes d'API restantes, d'après la dernière réponse ; ``None`` avant la
    première, ou si la forge ne les dit pas."""

    @abc.abstractmethod
    async def list_repos(self) -> list[Repository]:
        """Tous les dépôts accessibles : les siens, ceux où le compte est collaborateur, ceux
        de ses organisations ou groupes."""

    @abc.abstractmethod
    async def repository(self, full_name: str) -> Repository:
        """Un dépôt par son nom (``owner/nom``), même d'un autre compte s'il est public. Lève
        ``NotFound`` s'il n'existe pas ou que le token ne le voit pas."""

    async def restrictions(self) -> list[Restriction]:
        """Les organisations du compte dont les dépôts ne sont pas tous lisibles avec ce
        token. Aucune par défaut : seul GitHub a ces restrictions."""
        return []

    @abc.abstractmethod
    async def tree(self, repo: Repository, ref: str | None = None) -> Tree:
        """L'arborescence de ``ref`` (par défaut, la branche par défaut). Lève
        ``EmptyRepository`` pour un dépôt sans commit."""

    @abc.abstractmethod
    async def read_file(self, repo: Repository, path: str, ref: str) -> bytes | None:
        """Le contenu de ``path`` à ``ref`` (un commit) ; ``None`` s'il n'existe pas."""

    @abc.abstractmethod
    async def clone(self, repo: Repository, destination: Path) -> None:
        """Un clone superficiel de la branche par défaut dans ``destination``. Le token passe
        à git sans jamais apparaître dans ses arguments ni dans un message."""

    @abc.abstractmethod
    async def branch(self, repo: Repository, name: str) -> Branch | None:
        """La branche ``name`` sur la forge, avec ses commits qui ne sont pas sur la branche
        par défaut ; ``None`` si elle n'existe pas."""

    @abc.abstractmethod
    async def push_branch(
        self, repo: Repository, checkout: Path, branch: str, *, expected: str | None
    ) -> None:
        """Pousse ``HEAD`` du clone ``checkout`` sur ``branch``, en la remplaçant si elle pointe
        toujours sur ``expected`` (``None`` : elle ne doit pas exister) ; si quelqu'un l'a
        changée entre-temps, rien n'est poussé. Jamais sur la branche par défaut : lève
        ``ForgeError``."""

    @abc.abstractmethod
    async def find_open_request(self, repo: Repository, branch: str) -> ChangeRequest | None:
        """La PR ouverte depuis ``branch``, s'il y en a une."""

    @abc.abstractmethod
    async def open_or_update_request(
        self, repo: Repository, *, branch: str, title: str, body: str
    ) -> ChangeRequest:
        """Ouvre la PR de ``branch`` vers la branche par défaut, ou met à jour celle qui est
        déjà ouverte (titre, description) : relancer l'outil n'en ouvre jamais une
        deuxième."""


class OAuthFlow(abc.ABC):
    """La connexion d'un compte par la page d'autorisation d'une forge (OAuth 2, avec PKCE) :
    forceupdate y est enregistré une fois, par son auteur (``client_id``), et chaque personne
    y autorise son propre compte. La forge renvoie le navigateur vers le serveur local
    (``redirect_uri``, sur 127.0.0.1 : les deux forges acceptent n'importe quel port)."""

    kind: ClassVar[ForgeKind]
    callback_path: ClassVar[str]
    """Le chemin de l'adresse de retour, celui enregistré auprès de la forge."""
    client_id: str

    @property
    @abc.abstractmethod
    def web_flow(self) -> bool:
        """L'autorisation par la page de la forge est possible (l'application est connue)."""

    @abc.abstractmethod
    def authorization_url(self, *, redirect_to: str, state: str, verifier: str) -> str:
        """La page d'autorisation de la forge, où envoyer la personne."""

    @abc.abstractmethod
    async def exchange_code(
        self, http: HttpClient, *, code: str, redirect_to: str, verifier: str
    ) -> Grant:
        """Les tokens, contre le code que la forge a donné au retour. Lève ``ForgeError``."""

    @abc.abstractmethod
    def authorization_error(self, error: str, description: str = "") -> str:
        """Le message d'une erreur renvoyée par la forge sur l'adresse de retour."""

    @abc.abstractmethod
    async def revoke(self, http: HttpClient, token: str) -> bool:
        """Révoque un token obtenu par l'application ; ``False`` si la forge n'a pas pu."""

    async def refresh(self, http: HttpClient, refresh_token: str) -> Grant:
        """De nouveaux tokens, contre le ``refresh_token`` (qui ne sert plus ensuite). Lève
        ``TokenRefused`` s'il n'est plus valable."""
        raise TokenRefused("Ce token ne se renouvelle pas : se reconnecter.")

    def redirect_uri(self, port: int) -> str:
        """L'adresse de retour vers le serveur local."""
        return f"http://127.0.0.1:{port}{self.callback_path}"


def new_verifier() -> str:
    """Le secret PKCE d'une connexion (``code_verifier``)."""
    return secrets.token_urlsafe(48)


def challenge_of(verifier: str) -> str:
    """Le ``code_challenge`` (S256) d'un ``code_verifier``."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
