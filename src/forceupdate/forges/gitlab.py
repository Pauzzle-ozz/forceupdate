"""GitLab : le client REST (``GitLab``), et la connexion d'un compte (E19).

**Connexion** : chaque personne connecte son propre compte :

- **gitlab.com par OAuth** (``OAuthApp`` : ``authorization_url`` puis ``exchange_code``) :
  forceupdate y est enregistré, une fois, par son auteur, comme application « non
  confidentielle » (``CLIENT_ID`` ; pas de secret, PKCE à la place), portée ``api``. La page
  d'autorisation renvoie vers ``http://127.0.0.1:<port>/oauth/gitlab/callback`` : GitLab (par
  Doorkeeper) accepte n'importe quel port pour une adresse de retour en 127.0.0.1 (RFC 8252,
  §7.3). **Ses tokens expirent après 2 h** : ``OAuthApp.refresh`` en donne de nouveaux contre
  le ``refresh_token``, qui ne sert qu'une fois (l'ancien token et l'ancien refresh token
  cessent alors de marcher). Se déconnecter révoque le token (``revoke``) ;
- **un token d'accès personnel collé**, pour gitlab.com ou pour une instance auto-hébergée
  (par son adresse) : l'OAuth demanderait d'enregistrer forceupdate sur chaque instance.

**Client REST** : API v4 (``https://{hôte}/api/v4``), ``Authorization: Bearer`` (token
d'OAuth comme token personnel), pagination par l'en-tête ``Link``, requêtes restantes
(``RateLimit-*``), une ``ForgeError`` au message clair pour 401, 403, 404 et 409. Un token
refusé (401) est renouvelé une fois (``renew``, pour un token d'OAuth) avant d'abandonner. Le
token n'est jamais dans une URL, un message ni un journal.

**Projets** (le dépôt de GitLab) : ``list_repos`` (``/projects?membership=true`` : ceux du
compte, de ses groupes et sous-groupes ; puis ``min_access_level=30`` pour ceux où il peut
pousser, rôle Developer au moins), ``repository`` (un projet par son chemin complet, groupes
compris), ``tree`` (l'arborescence d'un commit, paginée, **sans les tailles** : GitLab ne les
donne pas ; tronquée au-delà de ``MAX_TREE_PAGES`` pages, le dépôt est alors cloné), et
``read_file`` (le fichier brut).

**Mise à jour** : ``clone`` et ``push_branch`` par git (``forges.git``, nom ``oauth2``),
``branch`` (``repository/branches`` puis ``repository/compare`` ; l'arbre du dernier commit,
que GitLab ne donne pas, est recalculé depuis la liste de sa racine : ``tree_id``),
``find_open_request`` et ``open_or_update_request`` (``merge_requests`` : la MR ouverte depuis
la branche vers la branche par défaut, mise à jour plutôt que doublée).
"""

import asyncio
import hashlib
import os
import re
import urllib.parse
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import httpx

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

HOST = "gitlab.com"
WEB_URL = f"https://{HOST}"
AUTHORIZE_URL = f"{WEB_URL}/oauth/authorize"
TOKEN_URL = f"{WEB_URL}/oauth/token"
REVOKE_URL = f"{WEB_URL}/oauth/revoke"
GIT_URL: str | None = None
"""D'où git clone et où il pousse (``{GIT_URL}/groupe/projet.git``) ; ``None`` : l'instance
elle-même. Les tests le font pointer vers un dossier de dépôts « bare »
(``fake_forge.remotes_url``)."""

SCOPES = ("api",)
"""La portée demandée par OAuth : lire les projets, pousser une branche (git compris), ouvrir
une MR. ``read_api`` ne permettrait pas d'ouvrir une MR, ``write_repository`` pas l'API."""

CALLBACK_PATH = "/oauth/gitlab/callback"
"""Le chemin de l'adresse de retour : celui enregistré auprès de GitLab
(``http://127.0.0.1/oauth/gitlab/callback``), sur le port du serveur."""

CLIENT_ID = "a31c8e4448a5d959c404a35865b7be8a197c6040d8a3f6edd3af4d26024c62ac"
"""L'application « forceupdate » de gitlab.com, enregistrée par l'auteur de l'outil (E19),
non confidentielle : elle n'a pas de secret, PKCE en tient lieu. ``FORCEUPDATE_GITLAB_CLIENT_ID``
la remplace (une autre application, un fork)."""

ENV_CLIENT_ID = "FORCEUPDATE_GITLAB_CLIENT_ID"

GIT_USERNAME = "oauth2"
"""Le nom que git présente avec un token, sur GitLab (le token est le mot de passe)."""

DEVELOPER = 30
"""Le rôle à partir duquel on pousse une branche et on ouvre une MR (Developer)."""

MAX_TREE_PAGES = 100
"""Pages d'arborescence lues au plus (100 entrées chacune, dossiers compris) ; au-delà, elle est
tronquée et le dépôt est cloné (comme une arborescence tronquée par GitHub)."""

_COMMIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_LINK = re.compile(r'<([^>]+)>\s*;\s*rel="([^"]+)"')


def web_url(host: str) -> str:
    return f"https://{host}"


def api_url(host: str) -> str:
    return f"{web_url(host)}/api/v4"


def label(host: str) -> str:
    """Le nom à montrer : « GitLab » pour gitlab.com, « GitLab (hôte) » pour une instance."""
    return "GitLab" if host == HOST else f"GitLab ({host})"


def token_settings_url(host: str = HOST) -> str:
    """Où créer un token d'accès personnel, nom et portée pré-remplis."""
    return f"{web_url(host)}/-/user_settings/personal_access_tokens?name=forceupdate&scopes=api"


# -- Client REST ----------------------------------------------------------------------


class GitLab(Forge):
    """GitLab (gitlab.com, ou une instance auto-hébergée par son hôte), vu avec un token."""

    kind: ClassVar[ForgeKind] = ForgeKind.GITLAB

    def __init__(
        self,
        http: HttpClient,
        token: str | None,
        *,
        host: str = HOST,
        renew: Renew | None = None,
        git_url: str | None = None,
    ) -> None:
        self.host = host
        self._http = http
        self._token = token
        """``None`` : sans compte, les projets publics seulement."""
        self._renew = renew
        """Pour un token d'OAuth : le renouveler quand il expire."""
        self._api = api_url(host)
        self._web = web_url(host)
        self._git = (git_url or GIT_URL or self._web).rstrip("/")
        self._name = label(host)
        self.rate_limit: RateLimit | None = None
        self.requests = 0

    def __repr__(self) -> str:
        return f"GitLab({self._api})"

    async def request(
        self, method: str, path: str, *, json: Any = None, renew: bool = True
    ) -> Response:
        """``method path`` (un chemin de l'API, ou une URL complète de l'instance) ; lève une
        ``ForgeError`` pour une réponse d'erreur. Un token refusé est renouvelé une fois
        (``renew``), puis la requête rejouée."""
        url = path if path.startswith(("https://", "http://")) else f"{self._api}{path}"
        response = await self._send(method, url, json)
        if (
            response.status_code == 401
            and renew
            and self._renew is not None
            and self._token is not None
        ):
            self._token = await self._renew(self._http, self._token)
            response = await self._send(method, url, json)
        if response.status_code >= 400:
            raise _error(response, path, self._name)
        return response

    async def _send(self, method: str, url: str, json: Any) -> Response:
        headers = {"Accept": "application/json"}
        if self._token is not None:
            headers["Authorization"] = f"Bearer {self._token}"
        self.requests += 1
        response = await self._http.request(method, url, headers=headers, json=json)
        self.rate_limit = _rate_limit(response.headers) or self.rate_limit
        return response

    async def get(self, path: str, *, renew: bool = True) -> Any:
        """``GET path``, en JSON."""
        return _json(await self.request("GET", path, renew=renew), self._name)

    async def paginate(self, path: str, *, limit: int | None = None) -> AsyncIterator[Any]:
        """Les éléments de toutes les pages de ``path`` (une liste JSON par page), en suivant
        l'en-tête ``Link`` (``rel="next"``), 100 par page ; ``limit`` pages au plus (lève alors
        ``_Truncated``)."""
        separator = "&" if "?" in path else "?"
        url: str | None = f"{path}{separator}per_page=100"
        pages = 0
        while url is not None:
            if limit is not None and pages >= limit:
                raise _Truncated
            response = await self.request("GET", url)
            pages += 1
            page = _json(response, self._name)
            if not isinstance(page, list):
                raise ForgeError(f"Réponse inattendue de {self._name} pour {_path(path)}.")
            for item in page:
                yield item
            url = _next_link(response.headers)

    async def whoami(self) -> Identity:
        user = await self.get("/user")
        if not isinstance(user, dict) or not isinstance(user.get("username"), str):
            raise ForgeError(f"Réponse inattendue de {self._name} pour /user.")
        login: str = user["username"]
        scopes, expires = await self._token_scopes()
        access = access_of(scopes)
        user_id = user.get("id")
        domain = self.host.partition(":")[0]
        return Identity(
            forge=ForgeKind.GITLAB,
            host=self.host,
            login=login,
            name=user.get("name") or None,
            url=user.get("web_url") or f"{self._web}/{login}",
            access=access,
            scopes=scopes,
            warnings=warnings_of(access, scopes, expires),
            email=f"{user_id}-{login}@users.noreply.{domain}" if isinstance(user_id, int) else None,
        )

    async def _token_scopes(self) -> tuple[tuple[str, ...] | None, str | None]:
        """Les portées du token, et sa date d'expiration s'il en a une : celles d'un token
        personnel (``/personal_access_tokens/self``), sinon d'un token d'OAuth
        (``/oauth/token/info``). ``(None, None)`` si GitLab ne les dit pas. Sans renouveler le
        token : ces adresses refusent l'autre sorte de token (gitlab.com répond 400 « This
        endpoint requires token type to be a personal access token » pour un token d'OAuth)."""
        try:
            found = await self.get("/personal_access_tokens/self", renew=False)
        except ForgeError:
            found = None
        if isinstance(found, dict) and isinstance(found.get("scopes"), list):
            expires = found.get("expires_at")
            return _scope_list(found["scopes"]), expires if isinstance(expires, str) else None
        try:
            found = await self.get(f"{self._web}/oauth/token/info", renew=False)
        except ForgeError:
            return None, None
        given = found.get("scope") or found.get("scopes") if isinstance(found, dict) else None
        return (_scope_list(given) if isinstance(given, list) else None), None

    async def list_repos(self) -> list[Repository]:
        """Les projets dont le compte est membre, directement ou par un groupe (sous-groupes
        compris), et parmi eux ceux où il peut pousser (Developer au moins)."""
        listed = [
            item async for item in self.paginate("/projects?membership=true&order_by=id&sort=asc")
        ]
        writable = {
            item.get("id")
            async for item in self.paginate(
                f"/projects?membership=true&min_access_level={DEVELOPER}&order_by=id&sort=asc"
                "&simple=true"
            )
            if isinstance(item, dict)
        }
        found = [self._repository(item, can_push=item.get("id") in writable) for item in listed]
        return [repo for repo in found if repo is not None]

    async def repository(self, full_name: str) -> Repository:
        found = self._repository(await self.get(f"/projects/{_id(full_name)}"))
        if found is None:
            raise ForgeError(f"Réponse inattendue de {self._name} pour /projects/{full_name}.")
        return found

    async def tree(self, repo: Repository, ref: str | None = None) -> Tree:
        """L'arborescence du dernier commit de ``ref`` : le commit d'abord (les fichiers se
        liront à ce commit, même si la branche avance), puis ses fichiers, page par page. Sans
        les liens symboliques, les sous-modules à part ; GitLab ne donne pas leur taille."""
        branch = ref or repo.default_branch
        if repo.empty or branch is None:
            raise EmptyRepository(_EMPTY)
        commit = await self._commit(repo, branch)
        entries: list[TreeEntry] = []
        submodules: list[str] = []
        truncated = False
        url = f"{_repo(repo)}/tree?ref={commit}&recursive=true&pagination=keyset"
        try:
            async for item in self.paginate(url, limit=MAX_TREE_PAGES):
                if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                    continue
                if item.get("type") == "blob" and item.get("mode") != "120000":  # pas un lien
                    entries.append(TreeEntry(path=item["path"], size=None))
                elif item.get("type") == "commit":
                    submodules.append(item["path"])
        except _Truncated:
            truncated = True
        return Tree(
            commit=commit,
            entries=tuple(entries),
            truncated=truncated,
            submodules=tuple(submodules),
        )

    async def read_file(self, repo: Repository, path: str, ref: str) -> bytes | None:
        """Le contenu brut (``repository/files/…/raw``)."""
        url = f"{_repo(repo)}/files/{_segment(path)}/raw?ref={_segment(ref)}"
        try:
            response = await self.request("GET", url)
        except NotFound:
            return None
        return response.content

    async def _commit(self, repo: Repository, ref: str) -> str:
        """Le commit de ``ref`` (une branche, ou déjà un commit)."""
        found = await self.get(f"{_repo(repo)}/commits/{_segment(ref)}")
        commit = found.get("id") if isinstance(found, dict) else None
        if not isinstance(commit, str) or not _COMMIT.fullmatch(commit):
            raise ForgeError(f"Réponse inattendue de {self._name} pour les commits de {ref}.")
        return commit

    def _repository(self, item: Any, *, can_push: bool | None = None) -> Repository | None:
        """Un projet de l'API ; ``can_push`` : d'après la liste des projets où l'on pousse,
        sinon d'après ses ``permissions`` (un seul projet)."""
        if not isinstance(item, dict) or not isinstance(item.get("path_with_namespace"), str):
            return None
        full_name: str = item["path_with_namespace"]
        default = item.get("default_branch") or None
        empty = bool(item.get("empty_repo")) or item.get("repository_access_level") == "disabled"
        if can_push is None:
            can_push = _access_level(item.get("permissions")) >= DEVELOPER
        return Repository(
            forge=ForgeKind.GITLAB,
            host=self.host,
            full_name=full_name,
            default_branch=None if empty else default,
            private=item.get("visibility") != "public",
            archived=bool(item.get("archived")),
            fork=isinstance(item.get("forked_from_project"), dict),
            can_push=can_push,
            url=item.get("web_url") or f"{self._web}/{full_name}",
            clone_url=item.get("http_url_to_repo") or f"{self._web}/{full_name}.git",
            empty=empty or default is None,
            pushed_at=_date(item.get("last_activity_at")),
        )

    # -- mise à jour : git, puis la MR ------------------------------------------------

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
        défaut (``compare``), et l'arbre de son dernier commit."""
        base = _repo(repo)
        try:
            found = await self.get(f"{base}/branches/{_segment(name)}")
        except NotFound:
            return None
        commit = found.get("commit") if isinstance(found, dict) else None
        head = commit.get("id") if isinstance(commit, dict) else None
        if not isinstance(head, str) or not _COMMIT.fullmatch(head):
            raise ForgeError(f"Réponse inattendue de {self._name} pour la branche {name}.")
        if repo.default_branch is None:
            return Branch(name=name, head=head, tree=None, commits=(), ahead=0)
        compared = await self.get(
            f"{base}/compare?from={_segment(repo.default_branch)}&to={head}&straight=false"
        )
        items = compared.get("commits") if isinstance(compared, dict) else None
        if not isinstance(items, list):
            raise ForgeError(f"Réponse inattendue de {self._name} pour {base}/compare.")
        commits = tuple(_branch_commit(item) for item in items if isinstance(item, dict))
        tree = await self._root_tree(repo, head) if commits else None
        return Branch(name=name, head=head, tree=tree, commits=commits, ahead=len(commits))

    async def _root_tree(self, repo: Repository, commit: str) -> str | None:
        """L'arbre de ``commit``, recalculé depuis sa racine ; ``None`` si GitLab ne la rend
        pas comme attendu (on poussera alors, sans risque)."""
        found = [item async for item in self.paginate(f"{_repo(repo)}/tree?ref={commit}")]
        entries = []
        for item in found:
            if not isinstance(item, dict):
                return None
            mode, name, oid = item.get("mode"), item.get("name"), item.get("id")
            if not (isinstance(mode, str) and isinstance(name, str) and isinstance(oid, str)):
                return None
            entries.append((mode, name, oid))
        return tree_id(entries)

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
        """La MR ouverte depuis ``branch`` (du projet même, pas d'un fork) vers la branche par
        défaut."""
        if repo.default_branch is None:
            return None
        query = urllib.parse.urlencode(
            {
                "state": "opened",
                "source_branch": branch,
                "target_branch": repo.default_branch,
                "per_page": "10",
            }
        )
        items = await self.get(f"{_project(repo)}/merge_requests?{query}")
        if not isinstance(items, list):
            raise ForgeError(f"Réponse inattendue de {self._name} pour les MR de {repo.full_name}.")
        found = [
            _change_request(item)
            for item in items
            if isinstance(item, dict)
            and item.get("source_project_id") == item.get("target_project_id")
        ]
        return next((request for request in found if request is not None), None)

    async def closed_request(self, repo: Repository, branch: str) -> ChangeRequest | None:
        """La dernière MR créée depuis ``branch`` (du projet même), si elle est ``closed`` (une
        MR fusionnée est ``merged``)."""
        if repo.default_branch is None:
            return None
        query = urllib.parse.urlencode(
            {
                "state": "all",
                "source_branch": branch,
                "target_branch": repo.default_branch,
                "order_by": "created_at",
                "sort": "desc",
                "per_page": "10",
            }
        )
        items = await self.get(f"{_project(repo)}/merge_requests?{query}")
        if not isinstance(items, list):
            raise ForgeError(f"Réponse inattendue de {self._name} pour les MR de {repo.full_name}.")
        last = next(
            (
                item
                for item in items
                if isinstance(item, dict)
                and item.get("source_project_id") == item.get("target_project_id")
            ),
            None,
        )
        if last is None or last.get("state") != "closed":
            return None
        request = _change_request(last)
        return None if request is None else replace(request, closed_at=_date(last.get("closed_at")))

    async def open_or_update_request(
        self, repo: Repository, *, branch: str, title: str, body: str
    ) -> ChangeRequest:
        if repo.default_branch is None or branch == repo.default_branch:
            raise ForgeError(
                "Une MR se propose depuis une autre branche que la branche par défaut."
            )
        requests = f"{_project(repo)}/merge_requests"
        found = await self.find_open_request(repo, branch)
        if found is None:
            fields = {
                "source_branch": branch,
                "target_branch": repo.default_branch,
                "title": title,
                "description": body,
            }
            try:
                created = await self.request("POST", requests, json=fields)
            except ForgeError as err:
                # Ouverte entre-temps (une autre fenêtre, un autre outil) : la mettre à jour.
                if "already exists" not in str(err).lower():
                    raise
                found = await self.find_open_request(repo, branch)
                if found is None:
                    raise
            else:
                return self._parsed_request(_json(created, self._name))
        updated = await self.request(
            "PUT", f"{requests}/{found.number}", json={"title": title, "description": body}
        )
        return self._parsed_request(_json(updated, self._name))

    def _parsed_request(self, item: Any) -> ChangeRequest:
        request = _change_request(item)
        if request is None:
            raise ForgeError(f"Réponse inattendue de {self._name} pour une MR.")
        return request

    def _clone_url(self, repo: Repository) -> str:
        """L'adresse du projet pour git, construite ici : jamais celle d'une réponse ni de la
        personne. Sans identifiants (ils passent par ``forges.git``)."""
        return f"{self._git}/{repo.full_name}.git"

    async def _credentials(self) -> git.Credentials | None:
        """Ce que git présentera : un token à jour (git dure : pas de 401 à rattraper)."""
        if self._token is None:
            return None
        if self._renew is not None:
            self._token = await self._renew(self._http, None)
        return git.Credentials(GIT_USERNAME, self._token)

    def _git_error(self, err: git.GitError, repo: Repository, action: str) -> ForgeError:
        """L'erreur de git, en erreur de la forge quand elle en est une."""
        if err.failure is git.GitFailure.AUTH:
            return TokenRefused(
                f"{self._name} refuse le token (git) : révoqué, expiré, ou mal copié. Se "
                "reconnecter."
            )
        if err.failure is git.GitFailure.DENIED:
            return AccessDenied(
                f"{self._name} refuse de {action} {repo.full_name} (403) : le compte n'y a pas "
                "le rôle Developer, ou le token n'a pas la portée api."
            )
        return err


class _Truncated(Exception):
    """``paginate`` a atteint sa limite de pages."""


def access_of(scopes: tuple[str, ...] | None) -> Access:
    """Ce que permettent les portées d'un token ; ``None`` : non vérifié."""
    if scopes is None:
        return Access.UNKNOWN
    if "api" in scopes:
        return Access.WRITE
    return Access.READ


def warnings_of(
    access: Access, scopes: tuple[str, ...] | None, expires: str | None = None
) -> tuple[str, ...]:
    """Ce qui manquera avec ces droits, et quand un token personnel expire."""
    found: list[str] = []
    if access is Access.UNKNOWN:
        found.append(
            "GitLab ne dit pas les droits de ce token. Pour ouvrir des MR, il lui faut la "
            "portée api, et le rôle Developer sur les projets."
        )
    elif access is Access.READ:
        if scopes is not None and "read_api" in scopes:
            found.append(
                "Portée read_api : les projets se lisent, mais aucune MR ne peut être ouverte "
                "(il faut la portée api)."
            )
        else:
            found.append(
                "Sans la portée api (ou read_api), les projets ne peuvent pas être lus : créer "
                "un token avec la portée api."
            )
    if expires:
        found.append(f"Ce token expire le {_day(expires)} : il faudra en coller un nouveau.")
    return tuple(found)


def tree_id(entries: Iterable[tuple[str, str, str]]) -> str | None:
    """L'identifiant git d'un arbre, recalculé de ses entrées ``(mode, nom, id)`` comme le
    fait ``git mktree`` : triées par nom (un dossier comme s'il finissait par ``/``), chacune
    ``<mode> <nom>\\0<id en octets>``, le tout précédé de ``tree <taille>\\0``, en SHA-1 (ou
    SHA-256 pour un dépôt qui l'utilise). ``None`` si une entrée n'a pas la forme attendue."""
    rows = []
    for mode, name, oid in entries:
        normalized = mode.lstrip("0")
        if not normalized.isdigit() or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", oid):
            return None
        directory = normalized == "40000"
        rows.append((name.encode() + (b"/" if directory else b""), normalized, name, oid))
    if not rows or len({len(row[3]) for row in rows}) != 1:
        return None
    body = b"".join(
        f"{mode} ".encode() + name.encode() + b"\0" + bytes.fromhex(oid)
        for _, mode, name, oid in sorted(rows)
    )
    algorithm = hashlib.sha1 if len(rows[0][3]) == 40 else hashlib.sha256
    return algorithm(b"tree %d\0" % len(body) + body).hexdigest()


def _rate_limit(headers: httpx.Headers) -> RateLimit | None:
    try:
        return RateLimit(
            limit=int(headers["ratelimit-limit"]),
            remaining=int(headers["ratelimit-remaining"]),
            reset_at=datetime.fromtimestamp(int(headers["ratelimit-reset"]), UTC),
        )
    except (KeyError, ValueError):
        return None


def _next_link(headers: httpx.Headers) -> str | None:
    for url, relation in _LINK.findall(headers.get("link", "")):
        if relation == "next":
            return str(url)
    return None


def _json(response: Response, name: str) -> Any:
    try:
        return response.json()
    except ValueError:
        raise ForgeError(
            f"Réponse illisible de {name} (HTTP {response.status_code}, pas du JSON)."
        ) from None


def _path(path: str) -> str:
    """Le chemin d'une requête, sans l'adresse de l'API ni ses paramètres, ``%2F`` en ``/``."""
    return urllib.parse.unquote(urllib.parse.urlsplit(path).path or path)


def _error(response: Response, path: str, name: str) -> ForgeError:
    """La ``ForgeError`` d'une réponse d'erreur de GitLab."""
    status = response.status_code
    message = _message(response)
    if status == 401:
        return TokenRefused(
            f"{name} refuse le token (401) : révoqué, expiré, ou mal copié. Se reconnecter."
        )
    if status == 429:
        reset = _rate_limit(response.headers)
        when = reset.reset_at.astimezone().strftime("%H:%M") if reset else None
        return RateLimited(
            f"Limite de l'API {name} atteinte : réessayer"
            + (f" après {when}." if when else " dans quelques minutes."),
            reset_at=reset.reset_at if reset else None,
        )
    if status == 403:
        if "insufficient_scope" in message.lower() or "insufficient scope" in message.lower():
            return AccessDenied(
                f"Le token n'a pas la portée nécessaire (403) pour {_path(path)} : il lui faut "
                "la portée api."
            )
        return AccessDenied(f"{name} refuse l'accès (403) à {_path(path)} : {message}")
    if status == 404:
        return NotFound(
            f"Introuvable sur {name} (404) : {_path(path)} n'existe pas, ou le token n'y a pas "
            "accès."
        )
    return ForgeError(f"{name} refuse la requête (HTTP {status}) sur {_path(path)} : {message}")


_EMPTY = "Dépôt vide : aucun commit, rien à analyser."


def _id(full_name: str) -> str:
    """Un projet dans un chemin d'URL : son chemin complet, ``/`` compris, encodé."""
    return urllib.parse.quote(full_name, safe="")


def _project(repo: Repository) -> str:
    return f"/projects/{_id(repo.full_name)}"


def _repo(repo: Repository) -> str:
    return f"{_project(repo)}/repository"


def _segment(value: str) -> str:
    """Une branche, un chemin de fichier ou un commit dans un segment d'URL (``/`` encodé)."""
    return urllib.parse.quote(value, safe="")


def _access_level(permissions: Any) -> int:
    """Le rôle le plus haut du compte sur un projet : le sien, ou celui de son groupe."""
    if not isinstance(permissions, dict):
        return 0
    levels = [
        found.get("access_level")
        for found in (permissions.get("project_access"), permissions.get("group_access"))
        if isinstance(found, dict)
    ]
    return max((level for level in levels if isinstance(level, int)), default=0)


def _scope_list(values: list[Any]) -> tuple[str, ...]:
    return tuple(str(value) for value in values if isinstance(value, str))


def _date(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _day(value: str) -> str:
    """``2027-01-31`` en « 31/01/2027 »."""
    try:
        return datetime.fromisoformat(value).strftime("%d/%m/%Y")
    except ValueError:
        return value


def _message(response: Response) -> str:
    """Le message d'erreur de GitLab (en anglais), en une phrase. GitLab le donne en texte,
    en liste (« Another open merge request already exists… ») ou par champ (``{"title":
    ["can't be blank"]}``), ou en ``error`` et ``error_description``."""
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return "pas de détail."
    given = body.get("message")
    if given is None:
        given = body.get("error_description") or body.get("error")
    parts: list[str] = []
    if isinstance(given, str):
        parts.append(given)
    elif isinstance(given, list):
        parts += [str(item) for item in given]
    elif isinstance(given, dict):
        for key, value in given.items():
            values = value if isinstance(value, list) else [value]
            parts.append(f"{key} {', '.join(str(v) for v in values)}")
    text = " ".join(" ; ".join(part.strip() for part in parts if part.strip()).split())
    if not text:
        return "pas de détail."
    return text if text.endswith(".") else f"{text}."


def _branch_commit(item: dict[str, Any]) -> BranchCommit:
    message = item.get("message")
    parents = item.get("parent_ids")
    return BranchCommit(
        sha=str(item.get("id") or ""),
        message=message if isinstance(message, str) else "",
        merge=isinstance(parents, list) and len(parents) > 1,
    )


def _change_request(item: Any) -> ChangeRequest | None:
    """Une MR de l'API ; ``None`` si la réponse n'en est pas une."""
    if not isinstance(item, dict):
        return None
    number, url = item.get("iid"), item.get("web_url")
    if not isinstance(number, int) or not isinstance(url, str):
        return None
    return ChangeRequest(
        number=number,
        url=url,
        title=str(item.get("title") or ""),
        branch=str(item.get("source_branch") or ""),
        base=str(item.get("target_branch") or ""),
    )


# -- Connexion : OAuth (gitlab.com) -----------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class OAuthApp(OAuthFlow):
    """L'application de gitlab.com auprès de qui on se connecte : non confidentielle, sans
    secret (PKCE)."""

    kind: ClassVar[ForgeKind] = ForgeKind.GITLAB
    callback_path: ClassVar[str] = CALLBACK_PATH

    client_id: str

    @classmethod
    def default(cls) -> "OAuthApp":
        """Celle de forceupdate, ou celle de ``FORCEUPDATE_GITLAB_CLIENT_ID``."""
        return cls(client_id=os.environ.get(ENV_CLIENT_ID, "").strip() or CLIENT_ID)

    @property
    def web_flow(self) -> bool:
        return bool(self.client_id)

    def authorization_url(self, *, redirect_to: str, state: str, verifier: str) -> str:
        parameters = {
            "client_id": self.client_id,
            "redirect_uri": redirect_to,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "state": state,
            "code_challenge": challenge_of(verifier),
            "code_challenge_method": "S256",
        }
        return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(parameters)}"

    async def exchange_code(
        self, http: HttpClient, *, code: str, redirect_to: str, verifier: str
    ) -> Grant:
        fields = {
            "client_id": self.client_id,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_to,
            "code_verifier": verifier,
        }
        body = await _token_request(http, TOKEN_URL, fields)
        grant = _grant(body)
        if grant is None:
            raise ForgeError(_oauth_error(body, "l'échange du code"))
        return grant

    async def refresh(self, http: HttpClient, refresh_token: str) -> Grant:
        """De nouveaux tokens : l'ancien token et l'ancien refresh token cessent de marcher.
        Lève ``TokenRefused`` si le refresh token n'est plus valable (révoqué sur gitlab.com,
        déjà servi)."""
        fields = {
            "client_id": self.client_id,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        body = await _token_request(http, TOKEN_URL, fields)
        grant = _grant(body)
        if grant is not None:
            return grant
        message = _oauth_error(body, "le renouvellement du token")
        if body.get("error") in ("invalid_grant", "invalid_client", "unauthorized_client"):
            raise TokenRefused(
                "GitLab ne renouvelle plus le token (révoqué, ou l'accès retiré à forceupdate) : "
                "se reconnecter."
            )
        raise ForgeError(message)

    def authorization_error(self, error: str, description: str = "") -> str:
        return _oauth_error({"error": error, "error_description": description}, "l'autorisation")

    async def revoke(self, http: HttpClient, token: str) -> bool:
        """Révoque le token auprès de gitlab.com (son refresh token avec lui)."""
        try:
            response = await http.request(
                "POST",
                REVOKE_URL,
                headers={"Accept": "application/json"},
                json={"client_id": self.client_id, "token": token},
            )
        except NetworkError:
            return False
        return response.status_code == 200


_OAUTH_ERRORS = {
    "invalid_grant": "Le code d'autorisation a expiré ou a déjà servi : recommencer.",
    "invalid_client": "GitLab ne reconnaît pas l'application forceupdate (Application ID).",
    "invalid_redirect_uri": (
        "GitLab refuse l'adresse de retour : elle doit être celle enregistrée pour "
        "l'application (http://127.0.0.1/oauth/gitlab/callback)."
    ),
    "access_denied": "Autorisation refusée sur GitLab.",
    "invalid_scope": "GitLab refuse la portée demandée (api) pour l'application forceupdate.",
}


async def _token_request(http: HttpClient, url: str, fields: dict[str, str]) -> dict[str, Any]:
    """Un ``POST`` au point des tokens de GitLab, réponse en JSON (une erreur : 400 ou 401,
    décrite par ``error``). Jamais rejoué : un code ou un refresh token ne servent qu'une
    fois."""
    response = await http.request(
        "POST", url, headers={"Accept": "application/json"}, json=fields, retry=False
    )
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise ForgeError(f"Réponse inattendue de GitLab (HTTP {response.status_code}).")
    return body


def _grant(body: dict[str, Any]) -> Grant | None:
    token = body.get("access_token")
    if not isinstance(token, str) or not token:
        return None
    refresh = body.get("refresh_token")
    lifetime = body.get("expires_in")
    expires_at = None
    if isinstance(lifetime, int) and lifetime > 0:
        # Sur l'horloge d'ici, pas sur ``created_at`` de GitLab : c'est elle qui dira quand
        # le renouveler.
        expires_at = datetime.now(UTC) + timedelta(seconds=lifetime)
    return Grant(
        access_token=token,
        refresh_token=refresh if isinstance(refresh, str) and refresh else None,
        expires_at=expires_at,
    )


def _oauth_error(body: dict[str, Any], what: str) -> str:
    error = str(body.get("error") or "")
    if error in _OAUTH_ERRORS:
        return _OAUTH_ERRORS[error]
    detail = str(body.get("error_description") or error or "pas de détail").strip()
    return f"GitLab refuse {what} : {detail.rstrip('.')}."
