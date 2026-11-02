"""GitHub : le client REST (``GitHub``), et la connexion d'un compte.

**Connexion** (E16) : forceupdate est enregistré auprès de GitHub comme OAuth App
(``CLIENT_ID``), une fois, par son auteur ; chaque personne y connecte son propre compte :

- **OAuth** (``authorization_url`` puis ``exchange_code``) : la page d'autorisation de GitHub
  renvoie vers le serveur local, ``http://127.0.0.1:<port>/oauth/github/callback`` (GitHub
  accepte n'importe quel port pour une adresse de retour en 127.0.0.1). ``state`` contre les
  requêtes forgées, PKCE (``S256``) en plus du secret ;
- **device flow** (``start_device`` puis ``wait_device``) : un code à taper sur
  github.com/login/device, sans retour vers le serveur ;
- **un token collé** (classic ou fine-grained), ou **celui de gh** (``gh_token``).

Portées demandées : ``repo`` (lire les dépôts privés, pousser une branche, ouvrir une PR) et
``read:org`` (lister les organisations, pour signaler celles qui restreignent l'accès des OAuth
Apps, E17). Les tokens n'expirent pas (case « Expire user access tokens » décochée dans les
réglages de l'application) ; se déconnecter révoque le token obtenu par OAuth (``revoke``).

**Client REST** : ``Authorization: Bearer``, version d'API fixée, pagination par l'en-tête
``Link``, requêtes restantes (``rate_limit``) et envoyées (``requests``), et une ``ForgeError``
au message clair pour 401, 403 (limite atteinte, SSO, accès des applications restreint, droits),
404 et 409 (dépôt vide). Le token n'est jamais dans une URL, un message ni un journal. Sans
token, le client lit les dépôts publics (60 requêtes par heure au lieu de 5 000).

**Dépôts** (E17) : ``list_repos`` (``/user/repos``, les siens, ceux où le compte collabore, ceux
de ses organisations), ``repository`` (un dépôt par son nom, même d'un autre compte),
``restrictions`` (les organisations qui restreignent l'accès des applications OAuth, ou exigent
le SSO), ``tree`` (l'arborescence d'un commit, en un appel) et ``read_file`` (le contenu brut
d'un fichier, ``application/vnd.github.raw`` : l'API « contents » en JSON s'arrête à 1 Mo).

**Mise à jour** (E18) : ``clone`` (superficiel, par git, le token passé par un credential
helper éphémère : ``forges.git``), ``branch`` (la branche de forceupdate et ses commits propres,
par ``git/ref`` puis ``compare``), ``push_branch`` (avec ``--force-with-lease``, jamais sur la
branche par défaut), ``find_open_request`` et ``open_or_update_request`` (``pulls`` : la PR
ouverte depuis la branche vers la branche par défaut, mise à jour plutôt que doublée).
"""

import asyncio
import base64
import os
import re
import shutil
import subprocess
import time
import urllib.parse
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import httpx

from forceupdate import processes
from forceupdate.forges import git
from forceupdate.forges.base import (
    Access,
    AccessDenied,
    AppRestricted,
    Branch,
    BranchCommit,
    ChangeRequest,
    EmptyRepository,
    Forge,
    ForgeError,
    ForgeKind,
    Grant,
    Identity,
    NotFound,
    OAuthFlow,
    RateLimit,
    RateLimited,
    Repository,
    Restriction,
    RestrictionKind,
    SsoRequired,
    TokenRefused,
    Tree,
    TreeEntry,
    challenge_of,
)
from forceupdate.net import HttpClient, NetworkError
from forceupdate.net.http import Response

HOST = "github.com"
API_URL = "https://api.github.com"
WEB_URL = "https://github.com"
AUTHORIZE_URL = f"{WEB_URL}/login/oauth/authorize"
TOKEN_URL = f"{WEB_URL}/login/oauth/access_token"
DEVICE_URL = f"{WEB_URL}/login/device/code"
GIT_URL = WEB_URL
"""D'où git clone et où il pousse (``{GIT_URL}/owner/nom.git``). Les tests le font pointer vers
un dossier de dépôts « bare » (``fake_forge.remotes_url``)."""
API_VERSION = "2022-11-28"

SCOPES = ("repo", "read:org")
"""Les portées demandées à la connexion."""

CALLBACK_PATH = "/oauth/github/callback"
"""Le chemin de l'adresse de retour : celui enregistré auprès de GitHub
(``http://127.0.0.1/oauth/github/callback``), sur le port du serveur."""

TOKEN_SETTINGS_URL = (
    f"{WEB_URL}/settings/tokens/new?scopes={','.join(SCOPES)}&description=forceupdate"
)
"""Où créer un token classic, portées pré-cochées."""

CLIENT_ID = "Ov23lihqeEYz35ddy5Pm"
CLIENT_SECRET = "6a2170a499fc479d8c9018859228b5aff8d75663"
"""L'OAuth App « forceupdate », enregistrée par l'auteur de l'outil (E16). Le secret d'une
application installée chez les gens ne peut pas rester secret (``gh`` fait de même) : il permet
seulement de présenter une page d'autorisation au nom de forceupdate, jamais d'obtenir un token
sans l'accord de la personne. ``FORCEUPDATE_GITHUB_CLIENT_ID`` et ``…_CLIENT_SECRET`` le
remplacent (une autre application, un fork)."""

ENV_CLIENT_ID = "FORCEUPDATE_GITHUB_CLIENT_ID"
ENV_CLIENT_SECRET = "FORCEUPDATE_GITHUB_CLIENT_SECRET"

AFFILIATION = "owner,collaborator,organization_member"
"""Les dépôts listés : les siens, ceux où le compte collabore, ceux de ses organisations."""

APPLICATIONS_URL = f"{WEB_URL}/settings/applications"
"""Les applications OAuth autorisées par le compte : c'est là qu'un membre demande à une
organisation d'en autoriser une."""

GH_TIMEOUT = 15.0
"""Délai maximal de ``gh auth token``, en secondes."""

MIN_INTERVAL = 1.0
"""Attente minimale entre deux demandes du device flow, en secondes, quoi que dise GitHub."""

GIT_USERNAME = "x-access-token"
"""Le nom que git présente avec un token, sur GitHub (le token est le mot de passe)."""

_JSON = "application/vnd.github+json"
_RAW = "application/vnd.github.raw"
_SHA_ONLY = "application/vnd.github.sha"
_COMMIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_LINK = re.compile(r'<([^>]+)>\s*;\s*rel="([^"]+)"')


@dataclass(frozen=True, kw_only=True)
class OAuthApp(OAuthFlow):
    """L'application auprès de qui on se connecte."""

    kind: ClassVar[ForgeKind] = ForgeKind.GITHUB
    callback_path: ClassVar[str] = CALLBACK_PATH

    client_id: str
    client_secret: str = field(repr=False)
    """Vide : seul le device flow marche (il n'en a pas besoin)."""

    @classmethod
    def default(cls) -> "OAuthApp":
        """Celle de forceupdate, ou celle des variables d'environnement."""
        client_id = os.environ.get(ENV_CLIENT_ID, "").strip()
        if client_id:
            return cls(client_id=client_id, client_secret=os.environ.get(ENV_CLIENT_SECRET, ""))
        return cls(client_id=CLIENT_ID, client_secret=CLIENT_SECRET)

    @property
    def web_flow(self) -> bool:
        """L'autorisation par la page de GitHub est possible (il faut le secret)."""
        return bool(self.client_secret)

    def authorization_url(self, *, redirect_to: str, state: str, verifier: str) -> str:
        return authorization_url(self, redirect_to=redirect_to, state=state, verifier=verifier)

    async def exchange_code(
        self, http: HttpClient, *, code: str, redirect_to: str, verifier: str
    ) -> Grant:
        token = await exchange_code(
            http, self, code=code, redirect_to=redirect_to, verifier=verifier
        )
        return Grant(access_token=token)

    def authorization_error(self, error: str, description: str = "") -> str:
        return authorization_error(error, description)

    async def revoke(self, http: HttpClient, token: str) -> bool:
        return await revoke(http, self, token)


# -- Client REST ----------------------------------------------------------------------


class GitHub(Forge):
    """GitHub, vu avec un token."""

    kind: ClassVar[ForgeKind] = ForgeKind.GITHUB

    def __init__(
        self,
        http: HttpClient,
        token: str | None,
        *,
        api_url: str = API_URL,
        git_url: str | None = None,
    ) -> None:
        self.host = HOST
        self._http = http
        self._token = token
        """``None`` : sans compte, les dépôts publics seulement."""
        self._api = api_url.rstrip("/")
        self._git = (git_url or GIT_URL).rstrip("/")
        """D'où git clone : ``GIT_URL`` par défaut."""
        self.rate_limit: RateLimit | None = None
        self.requests = 0

    def __repr__(self) -> str:
        return f"GitHub({self._api})"

    async def request(
        self, method: str, path: str, *, json: Any = None, accept: str = _JSON
    ) -> Response:
        """``method path`` (un chemin de l'API, ou une URL complète de l'API) ; lève une
        ``ForgeError`` pour une réponse d'erreur."""
        url = path if path.startswith(("https://", "http://")) else f"{self._api}{path}"
        headers = {"Accept": accept, "X-GitHub-Api-Version": API_VERSION}
        if self._token is not None:
            headers["Authorization"] = f"Bearer {self._token}"
        self.requests += 1
        response = await self._http.request(method, url, headers=headers, json=json)
        self.rate_limit = _rate_limit(response.headers) or self.rate_limit
        if response.status_code >= 400:
            raise _error(response, path)
        return response

    async def get(self, path: str) -> Any:
        """``GET path``, en JSON."""
        return _json(await self.request("GET", path))

    async def paginate(self, path: str) -> AsyncIterator[Any]:
        """Les éléments de toutes les pages de ``path`` (une liste JSON par page), en suivant
        l'en-tête ``Link`` (``rel="next"``), 100 par page."""
        separator = "&" if "?" in path else "?"
        url: str | None = f"{path}{separator}per_page=100"
        while url is not None:
            response = await self.request("GET", url)
            page = _json(response)
            if not isinstance(page, list):
                raise ForgeError(f"Réponse inattendue de GitHub pour {_path(path)}.")
            for item in page:
                yield item
            url = _next_link(response.headers)

    async def whoami(self) -> Identity:
        response = await self.request("GET", "/user")
        user = _json(response)
        if not isinstance(user, dict) or not isinstance(user.get("login"), str):
            raise ForgeError("Réponse inattendue de GitHub pour /user.")
        scopes = _scopes(response.headers)
        access = access_of(scopes)
        user_id = user.get("id")
        return Identity(
            forge=ForgeKind.GITHUB,
            host=self.host,
            login=user["login"],
            name=user.get("name") or None,
            url=user.get("html_url") or f"{WEB_URL}/{user['login']}",
            access=access,
            scopes=scopes,
            warnings=warnings_of(access, scopes),
            email=(
                f"{user_id}+{user['login']}@users.noreply.github.com"
                if isinstance(user_id, int)
                else None
            ),
        )

    async def list_repos(self) -> list[Repository]:
        """Les dépôts du compte, par nom. GitHub ne dit pas qu'un dépôt est vide : ceux de
        taille nulle (``size``, en Ko, arrondie : un petit dépôt peut l'avoir aussi) sont
        vérifiés un par un."""
        listed: list[tuple[Repository, bool]] = []
        async for item in self.paginate(f"/user/repos?affiliation={AFFILIATION}&sort=full_name"):
            found = self._repository(item)
            if found is not None:
                listed.append(found)
        return list(await asyncio.gather(*(self._check_empty(*item) for item in listed)))

    async def repository(self, full_name: str) -> Repository:
        found = self._repository(await self.get(f"/repos/{_quote(full_name)}"))
        if found is None:
            raise ForgeError(f"Réponse inattendue de GitHub pour /repos/{full_name}.")
        return await self._check_empty(*found)

    async def restrictions(self) -> list[Restriction]:
        """Les organisations du compte (``/user/orgs``, portée ``read:org``) dont la liste des
        dépôts est refusée : accès des applications OAuth restreint, ou SSO exigé. Sans
        ``read:org``, GitHub ne dit rien : aucune."""
        try:
            organizations = [
                item["login"]
                async for item in self.paginate("/user/orgs")
                if isinstance(item, dict) and isinstance(item.get("login"), str)
            ]
        except AccessDenied:
            return []
        found = await asyncio.gather(*(self._restriction(org) for org in organizations))
        return [restriction for restriction in found if restriction is not None]

    async def _restriction(self, organization: str) -> Restriction | None:
        try:
            await self.request("GET", f"/orgs/{_quote(organization)}/repos?per_page=1")
        except AppRestricted:
            return Restriction(
                organization=organization, kind=RestrictionKind.APP_ACCESS, url=APPLICATIONS_URL
            )
        except SsoRequired as err:
            return Restriction(organization=organization, kind=RestrictionKind.SSO, url=err.url)
        except (AccessDenied, NotFound):
            pass
        return None

    async def tree(self, repo: Repository, ref: str | None = None) -> Tree:
        """L'arborescence du dernier commit de ``ref`` : le commit d'abord (les fichiers se
        liront à ce commit, même si la branche avance entre-temps), puis son arbre en un
        appel. Sans les liens symboliques, les sous-modules à part ; GitHub la tronque au-delà de
        100 000 entrées."""
        branch = ref or repo.default_branch
        if repo.empty or branch is None:
            raise EmptyRepository(_EMPTY)
        base = f"/repos/{_quote(repo.full_name)}"
        response = await self.request("GET", f"{base}/commits/{_quote(branch)}", accept=_SHA_ONLY)
        commit = response.content.decode("ascii", errors="replace").strip()
        if not _COMMIT.fullmatch(commit):
            raise ForgeError(f"Réponse inattendue de GitHub pour {base}/commits/{branch}.")
        body = await self.get(f"{base}/git/trees/{commit}?recursive=1")
        items = body.get("tree") if isinstance(body, dict) else None
        if not isinstance(items, list):
            raise ForgeError(f"Réponse inattendue de GitHub pour {base}/git/trees.")
        listed = [
            item for item in items if isinstance(item, dict) and isinstance(item.get("path"), str)
        ]
        entries = tuple(
            TreeEntry(path=item["path"], size=_size(item.get("size")))
            for item in listed
            if item.get("type") == "blob" and item.get("mode") != "120000"  # lien symbolique
        )
        submodules = tuple(item["path"] for item in listed if item.get("type") == "commit")
        return Tree(
            commit=commit,
            entries=entries,
            truncated=bool(body.get("truncated")),
            submodules=submodules,
        )

    async def read_file(self, repo: Repository, path: str, ref: str) -> bytes | None:
        """Le contenu brut (``application/vnd.github.raw``), jusqu'à 100 Mo : en JSON,
        l'API « contents » ne donne plus le contenu au-delà de 1 Mo."""
        url = f"/repos/{_quote(repo.full_name)}/contents/{_quote(path)}?ref={_quote(ref)}"
        try:
            response = await self.request("GET", url, accept=_RAW)
        except NotFound:
            return None
        return response.content

    def _repository(self, item: Any) -> tuple[Repository, bool] | None:
        """Un dépôt de l'API, et s'il est de taille nulle (peut-être vide)."""
        if not isinstance(item, dict) or not isinstance(item.get("full_name"), str):
            return None
        full_name: str = item["full_name"]
        permissions = item.get("permissions")
        language = item.get("language")
        repo = Repository(
            forge=ForgeKind.GITHUB,
            host=self.host,
            full_name=full_name,
            default_branch=item.get("default_branch") or None,
            private=bool(item.get("private")),
            archived=bool(item.get("archived")),
            fork=bool(item.get("fork")),
            can_push=isinstance(permissions, dict) and bool(permissions.get("push")),
            url=item.get("html_url") or f"{WEB_URL}/{full_name}",
            clone_url=item.get("clone_url") or f"{WEB_URL}/{full_name}.git",
            language=language if isinstance(language, str) else None,
            pushed_at=_date(item.get("pushed_at")),
        )
        return repo, item.get("size") == 0

    async def _check_empty(self, repo: Repository, maybe_empty: bool) -> Repository:
        """Le dépôt, marqué vide si GitHub le dit (409 sur ses commits)."""
        if not maybe_empty:
            return repo
        try:
            await self.request("GET", f"/repos/{_quote(repo.full_name)}/commits?per_page=1")
        except EmptyRepository:
            return replace(repo, empty=True, default_branch=None)
        except (AccessDenied, NotFound):
            pass
        return repo

    # -- mise à jour : git, puis la PR ------------------------------------------------

    async def clone(self, repo: Repository, destination: Path) -> None:
        """Un clone superficiel de la branche par défaut, par git (dans un thread)."""
        if repo.empty or repo.default_branch is None:
            raise EmptyRepository(_EMPTY)
        try:
            await asyncio.to_thread(
                git.clone,
                self._clone_url(repo),
                destination,
                branch=repo.default_branch,
                credentials=self._credentials(),
                cancel=self.cancel,
            )
        except git.GitError as err:
            raise self._git_error(err, repo, "lire") from None

    async def branch(self, repo: Repository, name: str) -> Branch | None:
        """Le dernier commit de la branche (``git/ref``), puis ses commits qui ne sont pas sur
        la branche par défaut (``compare``, 100 au plus)."""
        base = f"/repos/{_quote(repo.full_name)}"
        try:
            ref = await self.get(f"{base}/git/ref/heads/{_quote(name)}")
        except NotFound:
            return None
        target = ref.get("object") if isinstance(ref, dict) else None
        head = target.get("sha") if isinstance(target, dict) else None
        if not isinstance(head, str) or not _COMMIT.fullmatch(head):
            raise ForgeError(f"Réponse inattendue de GitHub pour {base}/git/ref/heads/{name}.")
        if repo.default_branch is None:
            return Branch(name=name, head=head, tree=None, commits=(), ahead=0)
        compared = await self.get(
            f"{base}/compare/{_quote(repo.default_branch)}...{head}?per_page=100"
        )
        items = compared.get("commits") if isinstance(compared, dict) else None
        if not isinstance(items, list):
            raise ForgeError(f"Réponse inattendue de GitHub pour {base}/compare.")
        commits = tuple(_branch_commit(item) for item in items if isinstance(item, dict))
        ahead = compared.get("ahead_by")
        last = items[-1] if items and isinstance(items[-1], dict) else {}
        tree = None
        if last.get("sha") == head:
            found = (last.get("commit") or {}).get("tree") or {}
            tree = found.get("sha") if isinstance(found.get("sha"), str) else None
        return Branch(
            name=name,
            head=head,
            tree=tree,
            commits=commits,
            ahead=ahead if isinstance(ahead, int) else len(commits),
        )

    async def push_branch(
        self, repo: Repository, checkout: Path, branch: str, *, expected: str | None
    ) -> None:
        if repo.default_branch is None or branch == repo.default_branch:
            raise ForgeError(
                f"Push refusé : forceupdate ne pousse jamais sur la branche par défaut "
                f"({repo.default_branch or 'inconnue'})."
            )
        try:
            await asyncio.to_thread(
                git.push,
                checkout,
                self._clone_url(repo),
                branch,
                credentials=self._credentials(),
                expected=expected,
                cancel=self.cancel,
            )
        except git.GitError as err:
            raise self._git_error(err, repo, "pousser une branche dans") from None

    async def find_open_request(self, repo: Repository, branch: str) -> ChangeRequest | None:
        """La PR ouverte depuis ``branch`` (du dépôt même) vers la branche par défaut."""
        if repo.default_branch is None:
            return None
        query = urllib.parse.urlencode(
            {
                "state": "open",
                "head": f"{repo.owner}:{branch}",
                "base": repo.default_branch,
                "per_page": "10",
            }
        )
        items = await self.get(f"/repos/{_quote(repo.full_name)}/pulls?{query}")
        if not isinstance(items, list):
            raise ForgeError(f"Réponse inattendue de GitHub pour /repos/{repo.full_name}/pulls.")
        found = [_change_request(item) for item in items]
        return next((request for request in found if request is not None), None)

    async def closed_request(self, repo: Repository, branch: str) -> ChangeRequest | None:
        """La dernière PR créée depuis ``branch`` (``state=all``), si elle est fermée sans
        ``merged_at``."""
        if repo.default_branch is None:
            return None
        query = urllib.parse.urlencode(
            {
                "state": "all",
                "head": f"{repo.owner}:{branch}",
                "base": repo.default_branch,
                "sort": "created",
                "direction": "desc",
                "per_page": "1",
            }
        )
        items = await self.get(f"/repos/{_quote(repo.full_name)}/pulls?{query}")
        if not isinstance(items, list):
            raise ForgeError(f"Réponse inattendue de GitHub pour /repos/{repo.full_name}/pulls.")
        last = items[0] if items and isinstance(items[0], dict) else None
        if last is None or last.get("state") != "closed" or last.get("merged_at"):
            return None
        request = _change_request(last)
        return None if request is None else replace(request, closed_at=_date(last.get("closed_at")))

    async def open_or_update_request(
        self, repo: Repository, *, branch: str, title: str, body: str
    ) -> ChangeRequest:
        if repo.default_branch is None or branch == repo.default_branch:
            raise ForgeError(
                "Une PR se propose depuis une autre branche que la branche par défaut."
            )
        pulls = f"/repos/{_quote(repo.full_name)}/pulls"
        found = await self.find_open_request(repo, branch)
        if found is None:
            fields = {"title": title, "body": body, "head": branch, "base": repo.default_branch}
            try:
                created = await self.request("POST", pulls, json=fields)
            except ForgeError as err:
                # Ouverte entre-temps (une autre fenêtre, un autre outil) : la mettre à jour.
                if "already exists" not in str(err).lower():
                    raise
                found = await self.find_open_request(repo, branch)
                if found is None:
                    raise
            else:
                return self._parsed_request(_json(created), pulls)
        updated = await self.request(
            "PATCH", f"{pulls}/{found.number}", json={"title": title, "body": body}
        )
        return self._parsed_request(_json(updated), pulls)

    def _parsed_request(self, item: Any, path: str) -> ChangeRequest:
        request = _change_request(item)
        if request is None:
            raise ForgeError(f"Réponse inattendue de GitHub pour {path}.")
        return request

    def _clone_url(self, repo: Repository) -> str:
        """L'adresse du dépôt pour git, construite ici : jamais celle d'une réponse ni de la
        personne. Sans identifiants (ils passent par ``forges.git``)."""
        return f"{self._git}/{repo.full_name}.git"

    def _credentials(self) -> git.Credentials | None:
        return git.Credentials(GIT_USERNAME, self._token) if self._token else None

    def _git_error(self, err: git.GitError, repo: Repository, action: str) -> ForgeError:
        """L'erreur de git, en erreur de la forge quand elle en est une."""
        if err.failure is git.GitFailure.AUTH:
            return TokenRefused(
                "GitHub refuse le token (git) : révoqué, expiré, ou mal copié. Se reconnecter."
            )
        if err.failure is git.GitFailure.DENIED:
            return AccessDenied(
                f"GitHub refuse de {action} {repo.full_name} (403) : le compte n'y a pas le "
                "droit d'écriture, ou l'organisation restreint l'accès des applications OAuth."
            )
        return err


def access_of(scopes: tuple[str, ...] | None) -> Access:
    """Ce que permettent les portées d'un token classic ou OAuth ; ``None`` (pas
    d'``X-OAuth-Scopes`` : token fine-grained, ou d'une GitHub App) : non vérifié."""
    if scopes is None:
        return Access.UNKNOWN
    if "repo" in scopes:
        return Access.WRITE
    if "public_repo" in scopes:
        return Access.PUBLIC
    return Access.READ


def warnings_of(access: Access, scopes: tuple[str, ...] | None) -> tuple[str, ...]:
    """Ce qui manquera avec ces droits."""
    if access is Access.UNKNOWN:
        return (
            "Token fine-grained : GitHub ne dit pas ses droits. Pour les dépôts à mettre à "
            "jour, il lui faut « Contents » et « Pull requests » en écriture, et « Metadata » "
            "en lecture.",
        )
    found: list[str] = []
    if access is Access.READ:
        found.append(
            "Sans la portée repo, seuls les dépôts publics sont lus, et aucune PR ne peut "
            "être ouverte."
        )
    elif access is Access.PUBLIC:
        found.append("Portée public_repo : les dépôts privés ne sont pas accessibles.")
    if scopes is not None and not {"read:org", "write:org", "admin:org"} & set(scopes):
        found.append(
            "Sans la portée read:org, les organisations qui restreignent l'accès des "
            "applications ne pourront pas être signalées."
        )
    return tuple(found)


def _scopes(headers: httpx.Headers) -> tuple[str, ...] | None:
    value = headers.get("x-oauth-scopes")
    if value is None:
        return None
    return tuple(scope.strip() for scope in value.split(",") if scope.strip())


def _rate_limit(headers: httpx.Headers) -> RateLimit | None:
    try:
        return RateLimit(
            limit=int(headers["x-ratelimit-limit"]),
            remaining=int(headers["x-ratelimit-remaining"]),
            reset_at=datetime.fromtimestamp(int(headers["x-ratelimit-reset"]), UTC),
        )
    except (KeyError, ValueError):
        return None


def _next_link(headers: httpx.Headers) -> str | None:
    for url, relation in _LINK.findall(headers.get("link", "")):
        if relation == "next":
            return str(url)
    return None


def _json(response: Response) -> Any:
    try:
        return response.json()
    except ValueError:
        raise ForgeError(
            f"Réponse illisible de GitHub (HTTP {response.status_code}, pas du JSON)."
        ) from None


def _path(path: str) -> str:
    """Le chemin d'une requête, sans l'adresse de l'API ni ses paramètres."""
    return urllib.parse.urlsplit(path).path or path


def _error(response: Response, path: str) -> ForgeError:
    """La ``ForgeError`` d'une réponse d'erreur de GitHub."""
    status = response.status_code
    message = _message(response)
    headers = response.headers
    if status == 401:
        return TokenRefused(
            "GitHub refuse le token (401) : révoqué, expiré, ou mal copié. Se reconnecter."
        )
    if status in (403, 429):
        rate = _rate_limit(headers)
        if rate is not None and rate.remaining == 0:
            when = rate.reset_at.astimezone().strftime("%H:%M")
            return RateLimited(
                f"Limite de l'API GitHub atteinte ({rate.limit} requêtes par heure) : elle se "
                f"lève à {when}.",
                reset_at=rate.reset_at,
            )
        wait = headers.get("retry-after", "").strip()
        if wait.isdigit() or "rate limit" in message.lower():
            delay = f"dans {wait} s" if wait.isdigit() else "dans quelques minutes"
            return RateLimited(f"GitHub limite le débit (limite secondaire) : réessayer {delay}.")
    if status == 403:
        sso = headers.get("x-github-sso", "")
        if sso.startswith("required"):
            url = sso.partition("url=")[2].strip() or None
            where = f" : {url}" if url else ""
            return SsoRequired(
                f"Cette organisation exige d'autoriser le token pour son SSO (SAML){where}.",
                url=url,
            )
        if "oauth app access restrictions" in message.lower():
            return AppRestricted(
                "Cette organisation restreint l'accès des applications OAuth : ses dépôts "
                "privés ne sont lisibles qu'après l'accord d'un de ses propriétaires "
                f"({APPLICATIONS_URL})."
            )
        return AccessDenied(f"GitHub refuse l'accès (403) à {_path(path)} : {message}")
    if status == 404:
        return NotFound(
            f"Introuvable sur GitHub (404) : {_path(path)} n'existe pas, ou le token n'y a "
            "pas accès."
        )
    if status == 409 and "empty" in message.lower():
        return EmptyRepository(_EMPTY)
    return ForgeError(f"GitHub refuse la requête (HTTP {status}) sur {_path(path)} : {message}")


_EMPTY = "Dépôt vide : aucun commit, rien à analyser."


def _quote(value: str) -> str:
    """Un nom, un chemin ou une branche dans un chemin d'URL (les ``/`` restent)."""
    return urllib.parse.quote(value, safe="/")


def _size(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _date(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _message(response: Response) -> str:
    """Le message d'erreur de GitHub (en anglais), en une phrase ; avec le détail d'une
    validation refusée (422 : « A pull request already exists… »)."""
    try:
        body = response.json()
    except ValueError:
        body = None
    text = body.get("message") if isinstance(body, dict) else None
    if not isinstance(text, str) or not text.strip():
        return "pas de détail."
    errors = body.get("errors") if isinstance(body, dict) else None
    details = [
        item["message"]
        for item in (errors if isinstance(errors, list) else [])
        if isinstance(item, dict) and isinstance(item.get("message"), str)
    ]
    if details:
        text = f"{text.rstrip('.')} : {' ; '.join(details)}"
    text = " ".join(text.split())
    return text if text.endswith(".") else f"{text}."


def _branch_commit(item: dict[str, Any]) -> BranchCommit:
    commit = item.get("commit") if isinstance(item.get("commit"), dict) else {}
    message = commit.get("message")
    parents = item.get("parents")
    return BranchCommit(
        sha=str(item.get("sha") or ""),
        message=message if isinstance(message, str) else "",
        merge=isinstance(parents, list) and len(parents) > 1,
    )


def _change_request(item: Any) -> ChangeRequest | None:
    """Une PR de l'API ; ``None`` si la réponse n'en est pas une."""
    if not isinstance(item, dict):
        return None
    number, url = item.get("number"), item.get("html_url")
    head, base = item.get("head"), item.get("base")
    if not isinstance(number, int) or not isinstance(url, str):
        return None
    return ChangeRequest(
        number=number,
        url=url,
        title=str(item.get("title") or ""),
        branch=str(head.get("ref") or "") if isinstance(head, dict) else "",
        base=str(base.get("ref") or "") if isinstance(base, dict) else "",
    )


# -- Connexion : OAuth ----------------------------------------------------------------


def redirect_uri(port: int) -> str:
    """L'adresse de retour vers le serveur local."""
    return f"http://127.0.0.1:{port}{CALLBACK_PATH}"


def authorization_url(app: OAuthApp, *, redirect_to: str, state: str, verifier: str) -> str:
    """La page d'autorisation de GitHub, où envoyer la personne."""
    parameters = {
        "client_id": app.client_id,
        "redirect_uri": redirect_to,
        "scope": " ".join(SCOPES),
        "state": state,
        "code_challenge": challenge_of(verifier),
        "code_challenge_method": "S256",
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(parameters)}"


_EXCHANGE_ERRORS = {
    "bad_verification_code": "Le code d'autorisation a expiré ou a déjà servi : recommencer.",
    "incorrect_client_credentials": (
        "GitHub ne reconnaît pas l'application forceupdate (client id ou secret)."
    ),
    "redirect_uri_mismatch": (
        "GitHub refuse l'adresse de retour : elle doit être celle enregistrée pour "
        "l'application (http://127.0.0.1/oauth/github/callback)."
    ),
    "access_denied": "Autorisation refusée sur GitHub.",
}


async def exchange_code(
    http: HttpClient, app: OAuthApp, *, code: str, redirect_to: str, verifier: str
) -> str:
    """Le token, contre le code que GitHub a donné au retour."""
    body = await _token_request(
        http,
        {
            "client_id": app.client_id,
            "client_secret": app.client_secret,
            "code": code,
            "redirect_uri": redirect_to,
            "code_verifier": verifier,
        },
        retry=False,  # un code ne sert qu'une fois
    )
    token = body.get("access_token")
    if isinstance(token, str) and token:
        return token
    raise ForgeError(_oauth_error(body, _EXCHANGE_ERRORS, "l'échange du code"))


def authorization_error(error: str, description: str = "") -> str:
    """Le message d'une erreur renvoyée par GitHub sur l'adresse de retour."""
    return _oauth_error(
        {"error": error, "error_description": description},
        _EXCHANGE_ERRORS,
        "l'autorisation",
    )


async def revoke(http: HttpClient, app: OAuthApp, token: str) -> bool:
    """Révoque auprès de GitHub un token obtenu par l'application (OAuth ou device flow).
    Rend ``False`` si GitHub n'a pas pu le faire (réseau, secret absent…)."""
    if not app.web_flow:
        return False
    credentials = base64.b64encode(f"{app.client_id}:{app.client_secret}".encode()).decode()
    url = f"{API_URL}/applications/{app.client_id}/token"
    headers = {
        "Authorization": f"Basic {credentials}",
        "Accept": _JSON,
        "X-GitHub-Api-Version": API_VERSION,
    }
    try:
        response = await http.request("DELETE", url, headers=headers, json={"access_token": token})
    except NetworkError:
        return False
    # 404 : le token n'existe déjà plus (révoqué sur github.com).
    return response.status_code in (204, 404)


# -- Connexion : device flow ------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class DeviceCode:
    """Un code à taper sur github.com (``start_device``)."""

    device_code: str = field(repr=False)
    user_code: str
    verification_uri: str
    expires_in: int
    """Secondes."""
    interval: int
    """Secondes entre deux demandes du token."""


class DeviceExpired(ForgeError):
    """Le code a expiré avant d'être saisi."""


_DEVICE_ERRORS = {
    "access_denied": "Autorisation refusée sur GitHub.",
    "device_flow_disabled": (
        "Le device flow n'est pas activé pour l'application forceupdate sur GitHub."
    ),
    "incorrect_client_credentials": "GitHub ne reconnaît pas l'application forceupdate.",
    "expired_token": "Le code a expiré avant d'être saisi : en demander un autre.",
}


async def start_device(http: HttpClient, app: OAuthApp) -> DeviceCode:
    """Demande un code à GitHub."""
    body = await _token_request(
        http, {"client_id": app.client_id, "scope": " ".join(SCOPES)}, url=DEVICE_URL
    )
    try:
        return DeviceCode(
            device_code=str(body["device_code"]),
            user_code=str(body["user_code"]),
            verification_uri=str(body["verification_uri"]),
            expires_in=int(body.get("expires_in", 900)),
            interval=int(body.get("interval", 5)),
        )
    except (KeyError, TypeError, ValueError):
        raise ForgeError(_oauth_error(body, _DEVICE_ERRORS, "la demande de code")) from None


async def wait_device(
    http: HttpClient,
    app: OAuthApp,
    device: DeviceCode,
    *,
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    """Le token, une fois le code saisi et l'accès autorisé sur github.com. Demande toutes les
    ``interval`` secondes (5 de plus à chaque ``slow_down``) ; lève ``DeviceExpired`` quand le
    code expire, ``ForgeError`` si la personne refuse."""
    deadline = clock() + device.expires_in
    interval = float(device.interval)
    while True:
        await sleep(max(interval, MIN_INTERVAL))
        if clock() >= deadline:
            raise DeviceExpired(_DEVICE_ERRORS["expired_token"])
        body = await _token_request(
            http,
            {
                "client_id": app.client_id,
                "device_code": device.device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            retry=True,  # demander de nouveau ne change rien
        )
        token = body.get("access_token")
        if isinstance(token, str) and token:
            return token
        error = body.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            given = body.get("interval")
            interval = float(given) if isinstance(given, int | float) else interval + 5
            continue
        message = _oauth_error(body, _DEVICE_ERRORS, "la connexion")
        raise DeviceExpired(message) if error == "expired_token" else ForgeError(message)


async def _token_request(
    http: HttpClient, fields: Mapping[str, str], *, url: str = TOKEN_URL, retry: bool = False
) -> dict[str, Any]:
    """Un ``POST`` aux points d'OAuth de GitHub, réponse en JSON. GitHub y répond 200 même
    pour une erreur, décrite par ``error``."""
    response = await http.request(
        "POST", url, headers={"Accept": "application/json"}, json=dict(fields), retry=retry
    )
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise ForgeError(f"Réponse inattendue de GitHub (HTTP {response.status_code}).")
    return body


def _oauth_error(body: Mapping[str, Any], known: Mapping[str, str], what: str) -> str:
    error = str(body.get("error") or "")
    if error in known:
        return known[error]
    detail = str(body.get("error_description") or error or "pas de détail").strip()
    return f"GitHub refuse {what} : {detail.rstrip('.')}."


# -- Le token de gh ---------------------------------------------------------------------


def gh_installed() -> bool:
    """GitHub CLI (``gh``) est sur le ``PATH``."""
    return _which("gh") is not None


def gh_token(host: str = HOST) -> str:
    """Le token avec lequel ``gh`` est connecté à ``host`` (``gh auth token``). Il arrive par la
    sortie de gh, jamais par des arguments ; il n'est jamais écrit dans un message."""
    program = _which("gh")
    if program is None:
        raise ForgeError("GitHub CLI (gh) n'est pas installé.")
    env = {**os.environ, "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1", "GH_NO_UPDATE_NOTIFIER": "1"}
    try:
        result = _run(
            [program, "auth", "token", "--hostname", host],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=GH_TIMEOUT,
            env=env,
        )
    except subprocess.TimeoutExpired:
        raise ForgeError(f"gh ne répond pas (plus de {GH_TIMEOUT:.0f} s).") from None
    except OSError as err:
        raise ForgeError(f"gh n'a pas pu être lancé ({err.strerror or err}).") from None
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip().splitlines()
        reason = f" ({detail[0].strip()})" if detail else ""
        raise ForgeError(
            f"gh n'est pas connecté à {host}{reason} : lancer « gh auth login », ou se "
            "connecter autrement."
        )
    token = result.stdout.decode("utf-8", errors="replace").strip()
    if not token or any(character.isspace() for character in token):
        raise ForgeError("gh n'a pas rendu de token.")
    return token


def _which(program: str) -> str | None:
    """L'exécutable de ``program`` sur le ``PATH``. Les tests le remplacent : jamais de vrai
    ``gh`` dans les tests."""
    return shutil.which(program)


def _run(command: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
    """``processes.run``, sans shell. Les tests le remplacent."""
    return processes.run(command, check=False, **options)
