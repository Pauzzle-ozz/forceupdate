"""Bitbucket Cloud : le client REST (``Bitbucket``), et la connexion d'un compte (E20).

**Connexion** : chaque personne connecte son propre compte :

- **par OAuth** (``OAuthApp`` : ``authorization_url`` puis ``exchange_code``) : forceupdate est
  enregistré, une fois, par son auteur, comme « OAuth client » d'un workspace (``CLIENT_ID``,
  ``CLIENT_SECRET``), **public** (pas « private ») : Bitbucket n'a ni PKCE ni client sans
  secret, le secret est donc embarqué, comme celui de GitHub (il ne permet pas d'obtenir un token
  sans l'accord de la personne). La page d'autorisation renvoie vers
  ``http://127.0.0.1:<port>/oauth/bitbucket/callback`` (Bitbucket accepte n'importe quel port sur
  127.0.0.1), ``redirect_uri`` redonné à l'identique à l'échange du code. Les portées sont celles
  de l'application, pas de la demande. **Ses tokens expirent après 2 h** (``expires_in``) :
  ``OAuthApp.refresh`` en donne de nouveaux, **et un nouveau refresh token** (l'ancien cesse de
  marcher peu après). Bitbucket n'a pas de révocation par l'API : se déconnecter efface le token
  de l'ordinateur, la personne retire l'accès dans ses réglages (``APPLICATIONS_URL``) ;
- **un token d'API Atlassian collé** (``id.atlassian.com``, avec les portées Bitbucket de
  ``API_TOKEN_SCOPES`` : elles ne s'impliquent pas entre elles), passé en ``Bearer`` comme un
  token d'OAuth. Les « app passwords » ne marchent plus depuis le 28/07/2026.

**Client REST** : API 2.0 (``https://api.bitbucket.org/2.0``, la seule adresse acceptée),
``Authorization: Bearer``, pagination par le champ ``next`` (jamais suivi hors de l'API), une
``ForgeError`` au message clair pour 401, 403, 404, 410 et 429. Un token refusé (401) est
renouvelé une fois (``renew``, pour un token d'OAuth) avant d'abandonner. Bitbucket ne dit pas
les requêtes restantes (1 000 par heure sur les dépôts). Le token n'est jamais dans une URL, un
message ni un journal.

**Dépôts** : depuis avril 2026, Bitbucket ne liste plus les dépôts de tous les workspaces d'un
coup : ``list_repos`` lit les workspaces du compte (``/user/workspaces``), puis les dépôts de
chacun (``/repositories/{workspace}?role=member``), et ceux où il peut pousser (administrateur du
workspace, ou droit ``write`` ou ``admin`` sur le dépôt). Pas de dépôt « archivé » sur Bitbucket.
``tree`` : l'arborescence d'un commit par ``src`` (``max_depth`` : tout jusqu'à
``MAX_TREE_DEPTH`` niveaux, paginé), avec les tailles ; plus profonde, trop longue, ou trop lente
pour Bitbucket (555), elle est tronquée et le dépôt cloné. ``read_file`` : le fichier brut
(``src/{commit}/{chemin}``).

**Mise à jour** : ``clone`` et ``push_branch`` par git (``forges.git``, nom ``x-token-auth``),
``branch`` (``refs/branches``, puis ses commits qui ne sont pas sur la branche par défaut :
``commits?include=…&exclude=…``). L'API ne donne pas l'arbre d'un commit : ``branch_tree`` le lit
par git (``git.remote_tree``). ``find_open_request`` et ``open_or_update_request``
(``pullrequests`` : la PR ouverte depuis la branche vers la branche par défaut, mise à jour plutôt
que doublée, ses relecteurs gardés). Bitbucket n'a pas d'adresse « noreply » : les commits sont
faits avec l'adresse principale du compte (portée ``email``), qui les lui rattache.
"""

import asyncio
import base64
import logging
import os
import re
import urllib.parse
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import httpx

from forceupdate.detect.languages import known_name
from forceupdate.forges import git
from forceupdate.forges.base import (
    Access,
    AccessDenied,
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
    Renew,
    Repository,
    TokenRefused,
    Tree,
    TreeEntry,
    challenge_of,
)
from forceupdate.net import HttpClient, NetworkError
from forceupdate.net.http import Response

logger = logging.getLogger(__name__)

HOST = "bitbucket.org"
API_URL = "https://api.bitbucket.org/2.0"
WEB_URL = f"https://{HOST}"
AUTHORIZE_URL = f"{WEB_URL}/site/oauth2/authorize"
TOKEN_URL = f"{WEB_URL}/site/oauth2/access_token"
"""Le point des tokens : sur ``bitbucket.org``, pas sur ``api.bitbucket.org``."""
GIT_URL = WEB_URL
"""D'où git clone et où il pousse (``{GIT_URL}/workspace/depot.git``). Les tests le font pointer
vers un dossier de dépôts « bare » (``fake_forge.remotes_url``)."""

SCOPES = ("account", "email", "repository:write", "pullrequest:write")
"""Les portées de l'application (cochées dans ses réglages sur Bitbucket : la demande ne les
choisit pas) : le compte et son adresse (l'auteur des commits), lire les dépôts et y pousser une
branche, ouvrir une PR (``pullrequest:write`` comprend ``repository:write``)."""

API_TOKEN_SCOPES = (
    "read:user:bitbucket",
    "read:workspace:bitbucket",
    "read:repository:bitbucket",
    "write:repository:bitbucket",
    "read:pullrequest:bitbucket",
    "write:pullrequest:bitbucket",
)
"""Les portées d'un token d'API Atlassian pour forceupdate (aucune n'en comprend une autre)."""

CALLBACK_PATH = "/oauth/bitbucket/callback"
"""Le chemin de l'adresse de retour : celui enregistré auprès de Bitbucket
(``http://127.0.0.1/oauth/bitbucket/callback``), sur le port du serveur."""

TOKEN_SETTINGS_URL = "https://id.atlassian.com/manage-profile/security/api-tokens"
"""Où créer un token d'API Atlassian (« Create API token with scopes », application Bitbucket)."""

APPLICATIONS_URL = f"{WEB_URL}/account/settings/app-authorizations/"
"""Les applications autorisées par le compte : c'est là qu'on retire l'accès de forceupdate."""

CLIENT_ID = "jKVO7paKuMZ08X40tf1Hr7vXZXga0Nqc"
CLIENT_SECRET = "ATOAFtv_-OdLef9omjj8tSvbqJuUdhBHseTHzwThmVkfNEBfIndteE3cGW_a2fr1YMVI521CD0C2"
"""L'« OAuth client » « forceupdate », enregistré par l'auteur de l'outil dans son workspace
(E20), public : le secret d'une application installée chez les gens ne peut pas rester secret
(Bitbucket n'a pas de client sans secret ; Git Credential Manager fait de même). Il permet
seulement de présenter la page d'autorisation au nom de forceupdate, jamais d'obtenir un token
sans l'accord de la personne. ``FORCEUPDATE_BITBUCKET_CLIENT_ID`` et ``…_CLIENT_SECRET`` le
remplacent (une autre application, un fork)."""

ENV_CLIENT_ID = "FORCEUPDATE_BITBUCKET_CLIENT_ID"
ENV_CLIENT_SECRET = "FORCEUPDATE_BITBUCKET_CLIENT_SECRET"

GIT_USERNAME = "x-token-auth"
"""Le nom que git présente avec un token d'OAuth, sur Bitbucket (le token est le mot de passe)."""
API_TOKEN_USERNAME = "x-bitbucket-api-token-auth"
"""Le nom que git présente avec un token d'API Atlassian."""
API_TOKEN_PREFIX = "ATAT"
"""Ce par quoi commence un token d'API Atlassian."""

PAGE_LENGTH = 100
"""Éléments par page (le plus que permet Bitbucket)."""
MAX_TREE_DEPTH = 12
"""Niveaux de dossiers lus d'un coup par ``tree`` ; un dossier plus profond : l'arborescence est
tronquée, et le dépôt cloné."""
MAX_TREE_PAGES = 100
"""Pages d'arborescence lues au plus (100 entrées chacune, dossiers compris) ; au-delà, elle est
tronquée et le dépôt est cloné."""
MAX_BRANCH_COMMITS = 30
"""Commits propres d'une branche lus au plus (forceupdate n'en fait qu'un)."""
TIMEOUT_STATUS = 555
"""Ce que répond Bitbucket quand une arborescence lui prend trop de temps."""

_COMMIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


# -- Client REST ----------------------------------------------------------------------


class Bitbucket(Forge):
    """Bitbucket Cloud, vu avec un token (``None`` : les dépôts publics seulement)."""

    kind: ClassVar[ForgeKind] = ForgeKind.BITBUCKET

    def __init__(
        self,
        http: HttpClient,
        token: str | None,
        *,
        renew: Renew | None = None,
        api_url: str = API_URL,
        git_url: str | None = None,
    ) -> None:
        self.host = HOST
        self._http = http
        self._token = token
        self._renew = renew
        """Pour un token d'OAuth : le renouveler quand il expire."""
        self._api = api_url.rstrip("/")
        self._git = (git_url or GIT_URL).rstrip("/")
        self.rate_limit: RateLimit | None = None
        """Toujours ``None`` : Bitbucket ne dit pas les requêtes restantes."""
        self.requests = 0
        self._permissions: dict[str, tuple[bool, frozenset[str]]] = {}
        """Par workspace : le compte l'administre, et les dépôts où il peut pousser."""

    def __repr__(self) -> str:
        return f"Bitbucket({self._api})"

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        accept: str = "application/json",
        renew: bool = True,
        retry: bool | None = None,
    ) -> Response:
        """``method path`` (un chemin de l'API, ou une adresse complète de l'API) ; lève une
        ``ForgeError`` pour une réponse d'erreur. Un token refusé est renouvelé une fois
        (``renew``), puis la requête rejouée."""
        url = path if path.startswith(("https://", "http://")) else f"{self._api}{path}"
        if not url.startswith(f"{self._api}/"):
            raise ForgeError(f"Adresse refusée : hors de l'API de Bitbucket ({_path(url)}).")
        response = await self._send(method, url, json, accept, retry)
        if (
            response.status_code == 401
            and renew
            and self._renew is not None
            and self._token is not None
        ):
            self._token = await self._renew(self._http, self._token)
            response = await self._send(method, url, json, accept, retry)
        if response.status_code >= 400:
            raise _error(response, url)
        return response

    async def _send(
        self, method: str, url: str, json: Any, accept: str, retry: bool | None
    ) -> Response:
        headers = {"Accept": accept}
        if self._token is not None:
            headers["Authorization"] = f"Bearer {self._token}"
        self.requests += 1
        return await self._http.request(method, url, headers=headers, json=json, retry=retry)

    async def get(self, path: str, **options: Any) -> Any:
        """``GET path``, en JSON."""
        return _json(await self.request("GET", path, **options))

    async def paginate(
        self, path: str, *, limit: int | None = None, retry: bool | None = None
    ) -> AsyncIterator[Any]:
        """Les éléments de toutes les pages de ``path`` (``values``), en suivant ``next``,
        ``PAGE_LENGTH`` par page ; ``limit`` pages au plus (lève alors ``_Truncated``)."""
        separator = "&" if "?" in path else "?"
        url: str | None = f"{path}{separator}pagelen={PAGE_LENGTH}"
        pages = 0
        while url is not None:
            if limit is not None and pages >= limit:
                raise _Truncated
            page = await self.get(url, retry=retry)
            pages += 1
            values = page.get("values") if isinstance(page, dict) else None
            if not isinstance(values, list):
                raise ForgeError(f"Réponse inattendue de Bitbucket pour {_path(path)}.")
            for item in values:
                yield item
            following = page.get("next")
            url = following if isinstance(following, str) and following else None

    async def whoami(self) -> Identity:
        response = await self.request("GET", "/user")
        user = _json(response)
        if not isinstance(user, dict) or not isinstance(user.get("account_id"), str):
            raise ForgeError("Réponse inattendue de Bitbucket pour /user.")
        login = _text(user.get("username")) or _text(user.get("nickname")) or user["account_id"]
        scopes = _scopes(response.headers)
        access = access_of(scopes)
        email = await self._email()
        return Identity(
            forge=ForgeKind.BITBUCKET,
            host=self.host,
            login=login,
            name=_text(user.get("display_name")),
            url=_link(user, "html") or f"{WEB_URL}/{login}/",
            access=access,
            scopes=scopes,
            warnings=warnings_of(access, email=email is not None),
            email=email,
        )

    async def _email(self) -> str | None:
        """L'adresse principale et confirmée du compte (portée ``email``) : Bitbucket rattache un
        commit au compte par son adresse, et n'a pas d'adresse « noreply ». ``None`` si le token
        ne permet pas de la lire."""
        try:
            found = [item async for item in self.paginate("/user/emails")]
        except ForgeError:
            return None
        for item in found:
            if isinstance(item, dict) and item.get("is_primary") and item.get("is_confirmed"):
                email = _text(item.get("email"))
                if email:
                    return email
        return None

    async def list_repos(self) -> list[Repository]:
        """Les dépôts de chaque workspace du compte, et parmi eux ceux où il peut pousser."""
        workspaces = [
            slug
            # Sans ``sort`` : Bitbucket refuse ``workspace.slug`` (400, vérifié à E20).
            async for item in self.paginate("/user/workspaces")
            if (slug := _workspace_slug(item)) is not None
        ]
        listed = await asyncio.gather(*(self._workspace_repos(slug) for slug in workspaces))
        return [repo for repos in listed for repo in repos]

    async def _workspace_repos(self, workspace: str) -> list[Repository]:
        items = [
            item
            async for item in self.paginate(
                f"/repositories/{_segment(workspace)}?role=member&sort=slug"
            )
        ]
        administrator, writable = await self._workspace_permissions(workspace)
        found = [self._repository(item) for item in items]
        return [
            _with_push(repo, administrator or repo.full_name.lower() in writable)
            for repo in found
            if repo is not None
        ]

    async def _workspace_permissions(self, workspace: str) -> tuple[bool, frozenset[str]]:
        """Le compte administre le workspace (il peut alors pousser partout), et les dépôts où
        il a le droit ``write`` ou ``admin`` ; rien si Bitbucket ne le dit pas."""
        known = self._permissions.get(workspace)
        if known is not None:
            return known
        base = f"/user/workspaces/{_segment(workspace)}"
        administrator = False
        try:
            found = await self.get(f"{base}/permission")
            administrator = isinstance(found, dict) and found.get("permission") == "owner"
        except (AccessDenied, NotFound):
            pass
        writable: set[str] = set()
        query = urllib.parse.urlencode({"q": 'permission>"read"'})
        try:
            async for item in self.paginate(f"{base}/permissions/repositories?{query}"):
                repository = item.get("repository") if isinstance(item, dict) else None
                name = _text(repository.get("full_name")) if isinstance(repository, dict) else None
                if name and item.get("permission") in ("write", "admin"):
                    writable.add(name.lower())
        except (AccessDenied, NotFound):
            pass
        self._permissions[workspace] = (administrator, frozenset(writable))
        return self._permissions[workspace]

    async def repository(self, full_name: str) -> Repository:
        workspace, _, slug = full_name.partition("/")
        item = await self.get(f"/repositories/{_segment(workspace)}/{_segment(slug)}")
        found = self._repository(item)
        if found is None:
            raise ForgeError(f"Réponse inattendue de Bitbucket pour /repositories/{full_name}.")
        if self._token is None:
            return found
        administrator, writable = await self._workspace_permissions(found.owner)
        return _with_push(found, administrator or found.full_name.lower() in writable)

    async def tree(self, repo: Repository, ref: str | None = None) -> Tree:
        """L'arborescence du dernier commit de ``ref`` : le commit d'abord (les fichiers se
        liront à ce commit, même si la branche avance), puis ses fichiers, ``MAX_TREE_DEPTH``
        niveaux d'un coup, page par page. Sans les liens symboliques ; les sous-modules à part."""
        branch = ref or repo.default_branch
        if repo.empty or branch is None:
            raise EmptyRepository(_EMPTY)
        commit = await self._commit(repo, branch)
        entries: list[TreeEntry] = []
        submodules: list[str] = []
        truncated = False
        url = f"{_repo(repo)}/src/{commit}/?max_depth={MAX_TREE_DEPTH}"
        try:
            # Sans reprise : une arborescence trop lente pour Bitbucket (555) le restera.
            async for item in self.paginate(url, limit=MAX_TREE_PAGES, retry=False):
                if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                    continue
                path: str = item["path"]
                if item.get("type") == "commit_directory":
                    if path.count("/") + 1 >= MAX_TREE_DEPTH:
                        truncated = True  # ce dossier n'a pas été parcouru
                    continue
                if item.get("type") != "commit_file":
                    continue
                found = item.get("attributes")
                attributes = {str(a) for a in found} if isinstance(found, list) else set()
                if "subrepository" in attributes:
                    submodules.append(path)
                elif "link" not in attributes:
                    entries.append(TreeEntry(path=path, size=_size(item.get("size"))))
        except _Truncated:
            truncated = True
        except NetworkError as err:
            if err.status != TIMEOUT_STATUS:
                raise
            logger.info("Bitbucket : arborescence de %s trop lente (555)", repo.full_name)
            truncated = True
        return Tree(
            commit=commit,
            entries=tuple(entries),
            truncated=truncated,
            submodules=tuple(submodules),
        )

    async def read_file(self, repo: Repository, path: str, ref: str) -> bytes | None:
        """Le contenu brut (``src/{commit}/{chemin}``)."""
        url = f"{_repo(repo)}/src/{_segment(ref)}/{_quote(path)}"
        try:
            response = await self.request("GET", url, accept="*/*")
        except NotFound:
            return None
        return response.content

    async def _commit(self, repo: Repository, branch: str) -> str:
        """Le dernier commit de ``branch`` ; ``EmptyRepository`` si elle n'en a pas."""
        try:
            found = await self.get(f"{_repo(repo)}/refs/branches/{_quote(branch)}")
        except NotFound:
            raise EmptyRepository(_EMPTY) from None
        commit = _target(found)
        if commit is None:
            raise ForgeError(f"Réponse inattendue de Bitbucket pour la branche {branch}.")
        return commit

    def _repository(self, item: Any) -> Repository | None:
        """Un dépôt de l'API (sans le droit de push : ``_with_push``)."""
        if not isinstance(item, dict):
            return None
        workspace = item.get("workspace")
        slug = _text(item.get("slug"))
        owner = _text(workspace.get("slug")) if isinstance(workspace, dict) else None
        full_name = f"{owner}/{slug}" if owner and slug else _text(item.get("full_name"))
        if not full_name or "/" not in full_name:
            return None
        main = item.get("mainbranch")
        default = _text(main.get("name")) if isinstance(main, dict) else None
        language = _text(item.get("language"))
        return Repository(
            forge=ForgeKind.BITBUCKET,
            host=self.host,
            full_name=full_name,
            default_branch=default,
            private=bool(item.get("is_private")),
            archived=False,  # Bitbucket Cloud n'a pas de dépôt archivé
            fork=isinstance(item.get("parent"), dict),
            can_push=False,
            url=_link(item, "html") or f"{WEB_URL}/{full_name}",
            clone_url=f"{WEB_URL}/{full_name}.git",
            empty=default is None,
            language=known_name(language) if language else None,
            pushed_at=_date(item.get("updated_on")),
        )

    # -- mise à jour : git, puis la PR ------------------------------------------------

    async def clone(self, repo: Repository, destination: Path) -> None:
        """Un clone superficiel de la branche par défaut, par git (dans un thread)."""
        if repo.empty or repo.default_branch is None:
            raise EmptyRepository(_EMPTY)
        credentials = await self._credentials()
        try:
            await asyncio.to_thread(
                git.clone,
                self._clone_url(repo),
                destination,
                branch=repo.default_branch,
                credentials=credentials,
                cancel=self.cancel,
            )
        except git.GitError as err:
            raise self._git_error(err, repo, "lire") from None

    async def branch(self, repo: Repository, name: str) -> Branch | None:
        """Le dernier commit de la branche, puis ses commits qui ne sont pas sur la branche par
        défaut (les ``MAX_BRANCH_COMMITS`` plus récents). Sans l'arbre : ``branch_tree``."""
        try:
            found = await self.get(f"{_repo(repo)}/refs/branches/{_quote(name)}")
        except NotFound:
            return None
        head = _target(found)
        if head is None:
            raise ForgeError(f"Réponse inattendue de Bitbucket pour la branche {name}.")
        if repo.default_branch is None:
            return Branch(name=name, head=head, tree=None, commits=(), ahead=0)
        query = urllib.parse.urlencode(
            {"include": head, "exclude": repo.default_branch, "pagelen": MAX_BRANCH_COMMITS}
        )
        page = await self.get(f"{_repo(repo)}/commits?{query}")
        values = page.get("values") if isinstance(page, dict) else None
        if not isinstance(values, list):
            raise ForgeError(f"Réponse inattendue de Bitbucket pour les commits de {name}.")
        newest_first = [_branch_commit(item) for item in values if isinstance(item, dict)]
        commits = tuple(reversed(newest_first))
        more = 1 if page.get("next") else 0  # d'autres encore : au moins un de plus
        return Branch(name=name, head=head, tree=None, commits=commits, ahead=len(commits) + more)

    async def branch_tree(self, repo: Repository, checkout: Path, branch: Branch) -> str | None:
        """L'arbre du dernier commit de ``branch``, lu par git dans le clone (l'API de Bitbucket
        ne le donne pas) ; ``None`` si elle n'a pas de commit à elle, si elle ne part pas du
        même commit que celui du clone (``HEAD``, le commit de forceupdate), ou si git n'a pas pu
        le lire (on poussera, sans risque : le bail protège la branche).

        Une branche faite sur une branche par défaut qui a avancé depuis n'a pas le contenu du
        clone : on pousse sans la lire. Le ``fetch`` coûte alors le plus (tout ce qui a changé
        depuis : 20 Mo pour cpython à 300 commits de ``main``, mesuré le 2026-11-02), pour rien."""
        if not branch.commits:
            return None
        if branch.ahead == len(branch.commits):  # tous ses commits sont là : le premier dit d'où
            ours = await asyncio.to_thread(git.parents, checkout)
            if not set(ours) & set(branch.commits[0].parents):
                return None
        credentials = await self._credentials()
        try:
            return await asyncio.to_thread(
                git.remote_tree,
                checkout,
                self._clone_url(repo),
                branch.name,
                credentials=credentials,
                cancel=self.cancel,
            )
        except git.GitError as err:
            if err.failure is git.GitFailure.AUTH:
                raise self._git_error(err, repo, "lire") from None
            logger.info("Bitbucket : arbre de %s non lu (%s)", branch.name, err.failure)
            return None

    async def push_branch(
        self, repo: Repository, checkout: Path, branch: str, *, expected: str | None
    ) -> None:
        if repo.default_branch is None or branch == repo.default_branch:
            raise ForgeError(
                f"Push refusé : forceupdate ne pousse jamais sur la branche par défaut "
                f"({repo.default_branch or 'inconnue'})."
            )
        credentials = await self._credentials()
        try:
            await asyncio.to_thread(
                git.push,
                checkout,
                self._clone_url(repo),
                branch,
                credentials=credentials,
                expected=expected,
                cancel=self.cancel,
            )
        except git.GitError as err:
            raise self._git_error(err, repo, "pousser une branche dans") from None

    async def find_open_request(self, repo: Repository, branch: str) -> ChangeRequest | None:
        """La PR ouverte depuis ``branch`` (du dépôt même, pas d'un fork) vers la branche par
        défaut."""
        if repo.default_branch is None:
            return None
        condition = (
            f"source.branch.name={_bbql(branch)} AND "
            f"destination.branch.name={_bbql(repo.default_branch)}"
        )
        query = urllib.parse.urlencode({"q": condition, "state": "OPEN", "pagelen": "10"})
        page = await self.get(f"{_repo(repo)}/pullrequests?{query}")
        values = page.get("values") if isinstance(page, dict) else None
        if not isinstance(values, list):
            raise ForgeError(f"Réponse inattendue de Bitbucket pour les PR de {repo.full_name}.")
        for item in values:
            request = _change_request(item)
            if request is not None and _source_repository(item) in (None, repo.full_name.lower()):
                return request
        return None

    async def closed_request(self, repo: Repository, branch: str) -> ChangeRequest | None:
        """La dernière PR créée depuis ``branch`` (du dépôt même), tous états confondus, si elle
        est ``DECLINED`` ; sa date est celle de sa dernière modification (Bitbucket ne donne pas
        celle de la fermeture)."""
        if repo.default_branch is None:
            return None
        condition = (
            f"source.branch.name={_bbql(branch)} AND "
            f"destination.branch.name={_bbql(repo.default_branch)}"
        )
        states = [("state", state) for state in ("OPEN", "MERGED", "DECLINED", "SUPERSEDED")]
        query = urllib.parse.urlencode(
            [("q", condition), *states, ("sort", "-created_on"), ("pagelen", "10")]
        )
        page = await self.get(f"{_repo(repo)}/pullrequests?{query}")
        values = page.get("values") if isinstance(page, dict) else None
        if not isinstance(values, list):
            raise ForgeError(f"Réponse inattendue de Bitbucket pour les PR de {repo.full_name}.")
        last = next(
            (
                item
                for item in values
                if isinstance(item, dict)
                and _source_repository(item) in (None, repo.full_name.lower())
            ),
            None,
        )
        if last is None or last.get("state") != "DECLINED":
            return None
        request = _change_request(last)
        if request is None:
            return None
        return replace(request, closed_at=_date(last.get("updated_on")))

    async def open_or_update_request(
        self, repo: Repository, *, branch: str, title: str, body: str
    ) -> ChangeRequest:
        if repo.default_branch is None or branch == repo.default_branch:
            raise ForgeError(
                "Une PR se propose depuis une autre branche que la branche par défaut."
            )
        pulls = f"{_repo(repo)}/pullrequests"
        found = await self.find_open_request(repo, branch)
        if found is None:
            fields = {
                "title": title,
                "description": body,
                "source": {"branch": {"name": branch}},
                "destination": {"branch": {"name": repo.default_branch}},
            }
            try:
                created = await self.request("POST", pulls, json=fields)
            except (AccessDenied, NotFound, TokenRefused, RateLimited):
                raise
            except ForgeError:
                # Ouverte entre-temps (une autre fenêtre, un autre outil) : la mettre à jour.
                found = await self.find_open_request(repo, branch)
                if found is None:
                    raise
            else:
                return self._parsed_request(_json(created))
        # Les relecteurs déjà demandés restent : la PR entière est relue d'abord.
        current = await self.get(f"{pulls}/{found.number}")
        reviewers = current.get("reviewers") if isinstance(current, dict) else None
        kept = [
            {"uuid": person["uuid"]}
            for person in (reviewers if isinstance(reviewers, list) else [])
            if isinstance(person, dict) and isinstance(person.get("uuid"), str)
        ]
        updated = await self.request(
            "PUT",
            f"{pulls}/{found.number}",
            json={"title": title, "description": body, "reviewers": kept},
        )
        return self._parsed_request(_json(updated))

    def _parsed_request(self, item: Any) -> ChangeRequest:
        request = _change_request(item)
        if request is None:
            raise ForgeError("Réponse inattendue de Bitbucket pour une PR.")
        return request

    def _clone_url(self, repo: Repository) -> str:
        """L'adresse du dépôt pour git, construite ici : jamais celle d'une réponse ni de la
        personne. Sans identifiants (ils passent par ``forges.git``)."""
        return f"{self._git}/{repo.full_name}.git"

    async def _credentials(self) -> git.Credentials | None:
        """Ce que git présentera : un token à jour (git dure : pas de 401 à rattraper)."""
        if self._token is None:
            return None
        if self._renew is not None:
            self._token = await self._renew(self._http, None)
        api_token = self._token.startswith(API_TOKEN_PREFIX)
        return git.Credentials(API_TOKEN_USERNAME if api_token else GIT_USERNAME, self._token)

    def _git_error(self, err: git.GitError, repo: Repository, action: str) -> ForgeError:
        """L'erreur de git, en erreur de la forge quand elle en est une."""
        if err.failure is git.GitFailure.AUTH:
            return TokenRefused(
                "Bitbucket refuse le token (git) : révoqué, expiré, ou mal copié. Se reconnecter."
            )
        if err.failure is git.GitFailure.DENIED:
            return AccessDenied(
                f"Bitbucket refuse de {action} {repo.full_name} (403) : le compte n'y a pas le "
                "droit d'écriture, ou le token n'a pas la portée des dépôts en écriture."
            )
        return err


class _Truncated(Exception):
    """``paginate`` a atteint sa limite de pages."""


def access_of(scopes: tuple[str, ...] | None) -> Access:
    """Ce que permettent les portées d'un token (d'OAuth, ou d'API Atlassian) ; ``None`` : non
    vérifié."""
    if scopes is None:
        return Access.UNKNOWN
    given = set(scopes)
    if (
        "pullrequest:write" in given
        or {
            "write:repository:bitbucket",
            "write:pullrequest:bitbucket",
        }
        <= given
    ):
        return Access.WRITE
    return Access.READ


def warnings_of(access: Access, *, email: bool = True) -> tuple[str, ...]:
    """Ce qui manquera avec ces droits ; ``email`` : l'adresse du compte a pu se lire (Bitbucket
    ne dit pas la portée ``email`` dans ``X-OAuth-Scopes`` : ``account`` la comprend)."""
    if access is Access.UNKNOWN:
        return (
            "Bitbucket ne dit pas les droits de ce token. Pour ouvrir des PR, un token d'API "
            "Atlassian a besoin des portées " + ", ".join(API_TOKEN_SCOPES) + ".",
        )
    if access is Access.READ:
        return (
            "Sans les dépôts et les pull requests en écriture, les dépôts se lisent mais aucune "
            "PR ne peut être ouverte.",
        )
    if not email:
        return (
            "L'adresse du compte ne se lit pas avec ce token : les commits de forceupdate ne "
            "seront pas rattachés au compte sur Bitbucket.",
        )
    return ()


def _scopes(headers: httpx.Headers) -> tuple[str, ...] | None:
    """Les portées du token, d'après l'en-tête ``X-OAuth-Scopes`` (virgules ou espaces).
    Bitbucket n'y écrit que celles « du dessus » : ``account, pullrequest:write`` pour l'application
    de forceupdate (``pullrequest:write`` comprend ``repository:write``, ``account`` comprend
    ``email`` ; vérifié à E20)."""
    value = headers.get("x-oauth-scopes")
    if value is None:
        return None
    return tuple(scope for scope in re.split(r"[\s,]+", value) if scope)


def _json(response: Response) -> Any:
    try:
        return response.json()
    except ValueError:
        raise ForgeError(
            f"Réponse illisible de Bitbucket (HTTP {response.status_code}, pas du JSON)."
        ) from None


def _path(url: str) -> str:
    """Le chemin d'une requête, sans l'adresse de l'API ni ses paramètres, ``%2F`` en ``/``."""
    path = urllib.parse.urlsplit(url).path or url
    return urllib.parse.unquote(path.removeprefix("/2.0"))


def _error(response: Response, url: str) -> ForgeError:
    """La ``ForgeError`` d'une réponse d'erreur de Bitbucket."""
    status = response.status_code
    message = _message(response)
    if status == 401:
        return TokenRefused(
            "Bitbucket refuse le token (401) : révoqué, expiré, ou mal copié. Se reconnecter."
        )
    if status == 429:
        return RateLimited(
            "Limite de l'API Bitbucket atteinte (1 000 requêtes par heure sur les dépôts) : "
            "réessayer dans quelques minutes."
        )
    if status == 403:
        if "scope" in message.lower() or "privilege" in message.lower():
            return AccessDenied(
                f"Le token n'a pas la portée nécessaire (403) pour {_path(url)} : {message}"
            )
        return AccessDenied(f"Bitbucket refuse l'accès (403) à {_path(url)} : {message}")
    if status == 404:
        return NotFound(
            f"Introuvable sur Bitbucket (404) : {_path(url)} n'existe pas, ou le token n'y a "
            "pas accès."
        )
    if status == 410:
        return ForgeError(f"Bitbucket a retiré ce point d'API (410) : {_path(url)}. {message}")
    return ForgeError(f"Bitbucket refuse la requête (HTTP {status}) sur {_path(url)} : {message}")


def _message(response: Response) -> str:
    """Le message d'erreur de Bitbucket (en anglais), en une phrase : ``error.message`` (et son
    ``detail``, ses ``fields``), ou ``error_description`` (OAuth)."""
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return "pas de détail."
    error = body.get("error")
    parts: list[str] = []
    if isinstance(error, dict):
        for key in ("message", "detail"):
            value = error.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip().rstrip("."))
        fields = error.get("fields")
        if isinstance(fields, dict):
            for name, value in fields.items():
                values = value if isinstance(value, list) else [value]
                parts.append(f"{name} : {', '.join(str(v) for v in values)}")
    else:
        for value in (body.get("error_description"), error):
            if isinstance(value, str) and value.strip():
                parts.append(value.strip().rstrip("."))
                break
    text = " ".join(" ; ".join(parts).split())
    return f"{text}." if text else "pas de détail."


_EMPTY = "Dépôt vide : aucun commit, rien à analyser."


def _segment(value: str) -> str:
    """Un nom (workspace, dépôt, commit) dans un segment d'URL."""
    return urllib.parse.quote(value, safe="")


def _quote(value: str) -> str:
    """Un chemin ou une branche dans un chemin d'URL (les ``/`` restent)."""
    return urllib.parse.quote(value, safe="/")


def _repo(repo: Repository) -> str:
    workspace, _, slug = repo.full_name.partition("/")
    return f"/repositories/{_segment(workspace)}/{_segment(slug)}"


def _bbql(value: str) -> str:
    """Une chaîne dans une requête BBQL (``q=``)."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _with_push(repo: Repository, can_push: bool) -> Repository:
    return replace(repo, can_push=can_push)


def _workspace_slug(item: Any) -> str | None:
    workspace = item.get("workspace") if isinstance(item, dict) else None
    return _text(workspace.get("slug")) if isinstance(workspace, dict) else None


def _target(found: Any) -> str | None:
    """Le commit d'une branche de l'API (``target.hash``)."""
    target = found.get("target") if isinstance(found, dict) else None
    commit = target.get("hash") if isinstance(target, dict) else None
    return commit if isinstance(commit, str) and _COMMIT.fullmatch(commit) else None


def _link(item: dict[str, Any], name: str) -> str | None:
    links = item.get("links")
    found = links.get(name) if isinstance(links, dict) else None
    return _text(found.get("href")) if isinstance(found, dict) else None


def _text(value: Any) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _size(value: Any) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None


def _date(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _branch_commit(item: dict[str, Any]) -> BranchCommit:
    message = item.get("message")
    found = item.get("parents")
    parents = tuple(
        parent["hash"]
        for parent in (found if isinstance(found, list) else [])
        if isinstance(parent, dict) and isinstance(parent.get("hash"), str)
    )
    return BranchCommit(
        sha=str(item.get("hash") or ""),
        message=message if isinstance(message, str) else "",
        merge=len(parents) > 1,
        parents=parents,
    )


def _source_repository(item: Any) -> str | None:
    """Le dépôt d'où vient une PR (``workspace/depot``, en minuscules) ; ``None`` si la réponse
    ne le dit pas."""
    source = item.get("source") if isinstance(item, dict) else None
    repository = source.get("repository") if isinstance(source, dict) else None
    name = _text(repository.get("full_name")) if isinstance(repository, dict) else None
    return name.lower() if name else None


def _change_request(item: Any) -> ChangeRequest | None:
    """Une PR de l'API ; ``None`` si la réponse n'en est pas une."""
    if not isinstance(item, dict):
        return None
    number, url = item.get("id"), _link(item, "html")
    if not isinstance(number, int) or url is None:
        return None
    source, destination = item.get("source"), item.get("destination")
    return ChangeRequest(
        number=number,
        url=url,
        title=str(item.get("title") or ""),
        branch=_branch_name(source),
        base=_branch_name(destination),
    )


def _branch_name(side: Any) -> str:
    branch = side.get("branch") if isinstance(side, dict) else None
    return str(branch.get("name") or "") if isinstance(branch, dict) else ""


# -- Connexion : OAuth ------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class OAuthApp(OAuthFlow):
    """L'application de Bitbucket auprès de qui on se connecte : publique, avec son secret
    (Bitbucket n'a pas de client sans secret)."""

    kind: ClassVar[ForgeKind] = ForgeKind.BITBUCKET
    callback_path: ClassVar[str] = CALLBACK_PATH
    revocable: ClassVar[bool] = False

    client_id: str
    client_secret: str = field(repr=False)

    @classmethod
    def default(cls) -> "OAuthApp":
        """Celle de forceupdate, ou celle des variables d'environnement."""
        client_id = os.environ.get(ENV_CLIENT_ID, "").strip()
        if client_id:
            return cls(client_id=client_id, client_secret=os.environ.get(ENV_CLIENT_SECRET, ""))
        return cls(client_id=CLIENT_ID, client_secret=CLIENT_SECRET)

    @property
    def web_flow(self) -> bool:
        """L'autorisation par la page de Bitbucket est possible (il faut l'application et son
        secret)."""
        return bool(self.client_id and self.client_secret)

    def authorization_url(self, *, redirect_to: str, state: str, verifier: str) -> str:
        """La page d'autorisation. Sans ``scope`` (les portées sont celles de l'application) ;
        ``code_challenge`` est accepté mais pas vérifié par Bitbucket : envoyé quand même, il
        servira le jour où il le sera."""
        parameters = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": redirect_to,
            "state": state,
            "code_challenge": challenge_of(verifier),
            "code_challenge_method": "S256",
        }
        return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(parameters)}"

    async def exchange_code(
        self, http: HttpClient, *, code: str, redirect_to: str, verifier: str
    ) -> Grant:
        fields = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_to,  # le même qu'à l'autorisation, sinon refusé
            "code_verifier": verifier,
        }
        _, body = await self._token_request(http, fields)
        grant = _grant(body)
        if grant is None:
            raise ForgeError(_oauth_error(body, "l'échange du code"))
        return grant

    async def refresh(self, http: HttpClient, refresh_token: str) -> Grant:
        """De nouveaux tokens, et un nouveau refresh token (l'ancien cesse de marcher peu
        après). Lève ``TokenRefused`` si le refresh token n'est plus valable (déjà servi,
        inutilisé depuis 3 mois, ou l'accès retiré à forceupdate)."""
        fields = {"grant_type": "refresh_token", "refresh_token": refresh_token}
        status, body = await self._token_request(http, fields)
        grant = _grant(body)
        if grant is not None:
            return grant
        if status in (400, 401, 403) and body.get("error") in (
            "invalid_grant",
            "invalid_request",
            "unauthorized_client",
        ):
            raise TokenRefused(
                "Bitbucket ne renouvelle plus le token (accès retiré à forceupdate, ou resté "
                "trop longtemps sans servir) : se reconnecter."
            )
        raise ForgeError(_oauth_error(body, "le renouvellement du token"))

    def authorization_error(self, error: str, description: str = "") -> str:
        return _oauth_error({"error": error, "error_description": description}, "l'autorisation")

    async def revoke(self, http: HttpClient, token: str) -> bool:
        """Bitbucket n'a pas de révocation par l'API : la personne retire l'accès de forceupdate
        dans ses réglages (``APPLICATIONS_URL``)."""
        return False

    async def _token_request(
        self, http: HttpClient, fields: dict[str, str]
    ) -> tuple[int, dict[str, Any]]:
        """Un ``POST`` au point des tokens : l'application par ``Basic``, le reste en formulaire
        (une erreur : 400, 401 ou 403, décrite par ``error``). Jamais rejoué : un code ou un
        refresh token ne servent qu'une fois."""
        credentials = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        response = await http.request(
            "POST",
            TOKEN_URL,
            headers={"Accept": "application/json", "Authorization": f"Basic {credentials}"},
            form=fields,
            retry=False,
        )
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise ForgeError(f"Réponse inattendue de Bitbucket (HTTP {response.status_code}).")
        return response.status_code, body


_OAUTH_ERRORS = {
    "invalid_grant": "Le code d'autorisation a expiré ou a déjà servi : recommencer.",
    "invalid_client": (
        "Bitbucket ne reconnaît pas l'application forceupdate (client id ou secret)."
    ),
    "unauthorized_client": (
        "Bitbucket ne reconnaît pas l'application forceupdate (client id ou secret)."
    ),
    "access_denied": "Autorisation refusée sur Bitbucket.",
    "invalid_scope": (
        "Bitbucket refuse les portées demandées : elles ne sont pas toutes cochées dans les "
        "réglages de l'application forceupdate."
    ),
}


def _grant(body: dict[str, Any]) -> Grant | None:
    token = body.get("access_token")
    if not isinstance(token, str) or not token:
        return None
    refresh = body.get("refresh_token")
    lifetime = body.get("expires_in")
    expires_at = None
    if isinstance(lifetime, int) and lifetime > 0:
        expires_at = datetime.now(UTC) + timedelta(seconds=lifetime)
    return Grant(
        access_token=token,
        refresh_token=refresh if isinstance(refresh, str) and refresh else None,
        expires_at=expires_at,
    )


def _oauth_error(body: dict[str, Any], what: str) -> str:
    error = str(body.get("error") or "")
    description = str(body.get("error_description") or "").strip()
    if error == "invalid_request" and "redirect_uri" in description.lower():
        return (
            "Bitbucket refuse l'adresse de retour : elle doit commencer par celle enregistrée "
            "pour l'application (http://127.0.0.1/oauth/bitbucket/callback)."
        )
    if error in _OAUTH_ERRORS:
        return _OAUTH_ERRORS[error]
    detail = description or error or "pas de détail"
    return f"Bitbucket refuse {what} : {detail.rstrip('.')}."
