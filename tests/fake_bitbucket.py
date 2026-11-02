"""Un Bitbucket Cloud simulé (E20), à brancher sur un routeur ``respx`` : ``/user`` (portées dans
``X-OAuth-Scopes`` pour un token d'OAuth), ``/user/emails``, les workspaces du compte et ses
droits (``/user/workspaces``, ``…/permission``, ``…/permissions/repositories``), les dépôts d'un
workspace (``/repositories/{ws}``, paginés par ``next``), un dépôt, ses branches
(``refs/branches``), ses commits propres (``commits?include=…&exclude=…``), son arborescence
(``src/{commit}/?max_depth=…``, en largeur, paginée, avec les tailles) et ses fichiers bruts, les
PR (liste filtrée par BBQL, création, lecture, mise à jour), et OAuth (``/site/oauth2/
access_token`` : l'application par ``Basic``, en formulaire ; le code lié à l'adresse de retour ;
refresh token renouvelé à chaque usage, l'ancien refusé en 403 comme sur Bitbucket).

Les dépôts sont des ``fake_forge.FakeRepo`` (``workspace/dépôt``) : un dépôt peut avoir un vrai
dépôt git « bare », local (``fake_forge.make_remote``), où git clone, lit la branche et pousse
(``bitbucket.GIT_URL = remotes_url(…)``) ; les branches et commits que rend l'API sont alors les
siens. Jamais le vrai Bitbucket.

Un token inconnu, expiré ou révoqué reçoit 401 ; sans token, seuls les dépôts publics se voient
(un privé rend 404). Bitbucket ne dit pas les requêtes restantes : aucun en-tête de limite."""

import base64
import itertools
import json
import re
import urllib.parse
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import httpx
import respx
from fake_forge import FakePull, FakeRepo, git

API = "https://api.bitbucket.org/2.0"
WEB = "https://bitbucket.org"

USER = {
    "account_id": "557058:aaaa-bbbb",
    "uuid": "{0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0}",
    "username": "ecureuil",
    "nickname": "ecureuil",
    "display_name": "Écureuil Roux",
}

OAUTH_SCOPES = ("account", "pullrequest:write")
"""Les portées d'un token d'OAuth de l'application de test, comme les écrit Bitbucket dans
``X-OAuth-Scopes`` : seulement celles « du dessus » (l'application a aussi coché ``email``,
``repository:write`` : comprises dans celles-là ; vérifié à E20)."""


@dataclass(kw_only=True)
class FakeToken:
    """Un token du faux Bitbucket : d'OAuth (``oauth``, ses portées dans ``X-OAuth-Scopes``) ou
    d'API Atlassian (``api`` : Bitbucket ne dit pas ses portées)."""

    kind: str = "oauth"
    scopes: tuple[str, ...] = OAUTH_SCOPES
    valid: bool = True
    """Faux : expiré ou révoqué (401)."""


@dataclass(kw_only=True)
class FakeGrant:
    """Une autorisation donnée à l'application : son token et son refresh token."""

    access: str
    refresh: str
    used: bool = False
    """Le refresh token a déjà servi : Bitbucket le refuse ensuite (403)."""


@dataclass(kw_only=True)
class FakeBitbucket:
    """Bitbucket Cloud, avec ses dépôts et ses tokens."""

    repos: Iterable[FakeRepo] = ()
    tokens: dict[str, FakeToken] | None = None
    """``None`` : tout token est accepté (d'OAuth, toutes les portées)."""
    page_size: int = 100
    user: dict[str, Any] = field(default_factory=lambda: dict(USER))
    emails: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {"email": "ecureuil@example.org", "is_primary": True, "is_confirmed": True},
            {"email": "ancienne@example.org", "is_primary": False, "is_confirmed": True},
        ]
    )
    administrator: frozenset[str] = frozenset()
    """Les workspaces que le compte administre (il y pousse partout)."""
    client_id: str = "app-bitbucket-de-test"
    client_secret: str = "secret-bitbucket-de-test"
    codes: dict[str, str] = field(default_factory=dict)
    """Code d'autorisation → l'adresse de retour donnée à l'autorisation."""
    slow_tree: bool = False
    """L'arborescence prend trop de temps à Bitbucket : 555."""

    def __post_init__(self) -> None:
        self.repositories = {repo.full_name.lower(): repo for repo in self.repos}
        self.requests: list[httpx.Request] = []
        self.down = False
        self.grants: list[FakeGrant] = []
        self.numbers = itertools.count(1)
        """Les numéros des PR créées."""
        self._serial = itertools.count(1)

    def routes(self, router: respx.MockRouter) -> None:
        router.route(url__regex=f"^{re.escape(API)}/").mock(side_effect=self._dispatch)
        router.post(f"{WEB}/site/oauth2/access_token").mock(side_effect=self._oauth_token)

    def pull(self, full_name: str, number: int | None = None) -> FakePull:
        """Une PR de ``full_name`` (la seule, si ``number`` n'est pas donné)."""
        found = self.repositories[full_name.lower()].pulls
        if number is None:
            assert len(found) == 1, found
            return found[0]
        return next(pull for pull in found if pull.number == number)

    def files(self) -> list[str]:
        """Les fichiers téléchargés, ``workspace/dépôt:fichier``, dans l'ordre."""
        found = []
        for request in self.requests:
            path = request.url.raw_path.decode().split("?")[0]
            match = re.match(r"^/2\.0/repositories/([^/]+)/([^/]+)/src/[0-9a-f]+/(.+)$", path)
            if match and not match[3].endswith("/"):
                repo = f"{urllib.parse.unquote(match[1])}/{urllib.parse.unquote(match[2])}"
                found.append(f"{repo}:{urllib.parse.unquote(match[3])}")
        return found

    def authorize(self, redirect_uri: str) -> str:
        """Un code d'autorisation, comme si la personne avait autorisé l'application, pour
        l'adresse de retour donnée à la page d'autorisation."""
        code = f"code-{next(self._serial)}"
        self.codes[code] = redirect_uri
        return code

    def expire(self, token: str) -> None:
        """Le token expire (2 h sont passées) ; son refresh token reste bon."""
        assert self.tokens is not None
        self.tokens[token].valid = False

    # -- OAuth -------------------------------------------------------------------------

    def _grant(self) -> dict[str, Any]:
        serial = next(self._serial)
        # Un token d'OAuth de Bitbucket a plus de 2 000 caractères (E20).
        grant = FakeGrant(
            access=f"bbo-acces-{serial}-" + "x" * 2100, refresh=f"bbo-refresh-{serial}"
        )
        self.grants.append(grant)
        if self.tokens is None:
            self.tokens = {}
        self.tokens[grant.access] = FakeToken()
        return {
            "access_token": grant.access,
            "token_type": "bearer",
            "expires_in": 7200,
            "refresh_token": grant.refresh,
            "scope": " ".join(OAUTH_SCOPES),
        }

    def _oauth_token(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        expected = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        if request.headers.get("authorization") != f"Basic {expected}":
            return httpx.Response(
                401,
                json={
                    "error": "unauthorized_client",
                    "error_description": "Client credentials missing; this request needs to be "
                    "authenticated with the OAuth client id and secret",
                },
            )
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
        body = dict(urllib.parse.parse_qsl(request.content.decode()))
        if body.get("grant_type") == "authorization_code":
            redirect = self.codes.pop(body.get("code", ""), None)
            if redirect is None:
                return httpx.Response(
                    400,
                    json={"error": "invalid_grant", "error_description": "code expired"},
                )
            if body.get("redirect_uri") != redirect:
                return httpx.Response(
                    400,
                    json={
                        "error": "invalid_request",
                        "error_description": "redirect_uri does not match",
                    },
                )
            return httpx.Response(200, json=self._grant())
        if body.get("grant_type") == "refresh_token":
            grant = next((g for g in self.grants if g.refresh == body.get("refresh_token")), None)
            if grant is None or grant.used:
                return httpx.Response(
                    403,
                    json={
                        "error": "unauthorized_client",
                        "error_description": "refresh_token is invalid",
                    },
                )
            grant.used = True
            return httpx.Response(200, json=self._grant())
        return httpx.Response(400, json={"error": "unsupported_grant_type"})

    # -- l'API -------------------------------------------------------------------------

    def _token(self, request: httpx.Request) -> str | None:
        authorization = request.headers.get("authorization", "")
        return authorization.removeprefix("Bearer ") if authorization else None

    def _details(self, token: str | None) -> FakeToken | None:
        if token is None:
            return None
        if self.tokens is None:
            return FakeToken()
        return self.tokens.get(token)

    def _dispatch(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.down:
            raise httpx.ConnectError("Bitbucket simulé : coupé", request=request)
        token = self._token(request)
        details = self._details(token)
        if token is not None and (details is None or not details.valid):
            return self._error(
                401, "Access token expired. Use your refresh token to obtain a new access token."
            )
        raw = request.url.raw_path.decode()
        path, _, query_text = raw.partition("?")
        path = path.removeprefix("/2.0")
        query = urllib.parse.parse_qs(query_text)
        if path.startswith("/user"):
            if details is None:
                return self._error(401, "Authentication required.")
            return self._user(path, query, request, details)
        match = re.fullmatch(r"/repositories/([^/]+)(?:/([^/]+)(/.*)?)?", path)
        if match is None:
            return self._error(404, "Resource not found")
        workspace = urllib.parse.unquote(match[1])
        if match[2] is None:
            assert query.get("role") == ["member"], query
            listed = [
                self._repository(repo)
                for repo in self.repositories.values()
                if repo.member
                and details is not None
                and repo.full_name.split("/")[0].lower() == workspace.lower()
            ]
            return self._page(request, listed, query)
        repo = self.repositories.get(f"{workspace}/{urllib.parse.unquote(match[2])}".lower())
        if repo is None or (repo.private and (details is None or not repo.member)):
            return self._error(
                404,
                "You may not have access to this repository or it no longer exists in this "
                "workspace. If you think this repository exists and you have access, make sure "
                "you are authenticated.",
            )
        return self._in_repository(repo, match[3] or "", query, request)

    def _user(
        self, path: str, query: dict[str, list[str]], request: httpx.Request, details: FakeToken
    ) -> httpx.Response:
        headers = {"X-Credential-Type": "api_token" if details.kind == "api" else "oauth2_legacy"}
        if details.kind == "oauth":
            headers["X-OAuth-Scopes"] = ", ".join(details.scopes)
        if path == "/user":
            user = {
                **self.user,
                "type": "user",
                "links": {"html": {"href": f"{WEB}/%7B{self.user['uuid'][1:-1]}%7D/"}},
            }
            return self._json(200, user, headers=headers)
        if path == "/user/emails":
            if details.kind == "oauth" and not {"account", "email"} & set(details.scopes):
                return self._error(
                    403,
                    "Your credentials lack one or more required privilege scopes.",
                    detail={"required": ["email"]},
                )
            return self._page(request, self.emails, query)
        if path == "/user/workspaces":
            if "sort" in query:  # comme Bitbucket pour ``sort=workspace.slug`` (vu à E20)
                return self._error(400, f"Invalid field name: {query['sort'][0]}")
            slugs = sorted(
                {repo.full_name.split("/")[0] for repo in self.repositories.values() if repo.member}
            )
            items = [
                {
                    "type": "workspace_access",
                    "administrator": slug in self.administrator,
                    "workspace": {"type": "workspace_base", "slug": slug, "name": slug.title()},
                }
                for slug in slugs
            ]
            return self._page(request, items, query)
        match = re.fullmatch(r"/user/workspaces/([^/]+)/permission", path)
        if match:
            slug = urllib.parse.unquote(match[1])
            permission = "owner" if slug in self.administrator else "member"
            return self._json(200, {"type": "workspace_membership", "permission": permission})
        match = re.fullmatch(r"/user/workspaces/([^/]+)/permissions/repositories", path)
        if match:
            slug = urllib.parse.unquote(match[1]).lower()
            assert query.get("q") == ['permission>"read"'], query
            items = [
                {
                    "type": "repository_permission",
                    "permission": "write",
                    "repository": {"type": "repository", "full_name": repo.full_name},
                }
                for repo in self.repositories.values()
                if repo.member and repo.push and repo.full_name.split("/")[0].lower() == slug
            ]
            return self._page(request, items, query)
        return self._error(404, "Resource not found")

    def _repository(self, repo: FakeRepo) -> dict[str, Any]:
        workspace, slug = repo.full_name.split("/")
        data: dict[str, Any] = {
            "type": "repository",
            "full_name": repo.full_name,
            "name": slug,
            "slug": slug,
            "workspace": {"type": "workspace", "slug": workspace},
            "is_private": repo.private,
            "language": (repo.language or "").lower(),
            "updated_on": repo.pushed_at,
            "mainbranch": None if repo.empty else {"type": "branch", "name": repo.default_branch},
            "links": {
                "html": {"href": f"{WEB}/{repo.full_name}"},
                "clone": [
                    {
                        "name": "https",
                        "href": f"https://ecureuil@bitbucket.org/{repo.full_name}.git",
                    }
                ],
            },
        }
        if repo.fork:
            data["parent"] = {"type": "repository", "full_name": "amont/depot"}
        return data

    def _in_repository(
        self, repo: FakeRepo, rest: str, query: dict[str, list[str]], request: httpx.Request
    ) -> httpx.Response:
        if rest == "":
            return self._json(200, self._repository(repo))
        if rest.startswith("/pullrequests"):
            return self._pullrequests(repo, rest, query, request)
        if rest.startswith("/refs/branches/"):
            branch = urllib.parse.unquote(rest.removeprefix("/refs/branches/"))
            head = None if repo.empty else self._branch(repo, branch)
            if head is None:
                return self._error(404, f"Branch not found: {branch}")
            return self._json(200, {"type": "branch", "name": branch, "target": {"hash": head}})
        if rest == "/commits":
            return self._commits(repo, query, request)
        match = re.fullmatch(r"/src/([0-9a-f]{40})/(.*)", rest)
        if match is None or repo.empty:
            return self._error(404, "Resource not found")
        assert match[1] == repo.commit, (match[1], repo.commit)
        if match[2] == "":
            return self._tree(repo, query, request)
        content = repo.files.get(urllib.parse.unquote(match[2]))
        if content is None:
            return self._error(404, f"No such file or directory: {urllib.parse.unquote(match[2])}")
        return httpx.Response(
            200,
            content=content,
            headers={"Content-Type": "text/plain", "Content-Disposition": "attachment"},
        )

    def _branch(self, repo: FakeRepo, branch: str) -> str | None:
        if repo.remote is None:
            return repo.commit if branch == repo.default_branch else None
        found = git(repo.remote, "for-each-ref", "--format=%(objectname)", f"refs/heads/{branch}")
        return found.strip() or None

    def _tree(
        self, repo: FakeRepo, query: dict[str, list[str]], request: httpx.Request
    ) -> httpx.Response:
        if self.slow_tree:
            return self._error(555, "Timeout")
        depth = int(query.get("max_depth", ["1"])[0])
        entries: list[dict[str, Any]] = []
        directories: set[str] = set()
        files = [(path, repo.files[path], []) for path in repo.files]
        files += [(path, b"cible", ["link"]) for path in repo.symlinks]
        files += [(path, b"0" * 40, ["subrepository"]) for path in repo.submodules]
        for path, content, attributes in files:
            parts = path.split("/")
            for level in range(1, len(parts)):
                directories.add("/".join(parts[:level]))
            if len(parts) <= depth:
                entries.append(
                    {
                        "type": "commit_file",
                        "path": path,
                        "size": len(content),
                        "attributes": attributes,
                        "escaped_path": path,
                    }
                )
        entries += [
            {"type": "commit_directory", "path": d}
            for d in directories
            if d.count("/") + 1 <= depth
        ]
        entries.sort(key=lambda entry: (entry["path"].count("/"), entry["path"]))
        return self._page(request, entries, query)

    def _commits(
        self, repo: FakeRepo, query: dict[str, list[str]], request: httpx.Request
    ) -> httpx.Response:
        assert repo.remote is not None
        include, exclude = query["include"][0], query["exclude"][0]
        listed = git(repo.remote, "rev-list", "--parents", include, f"^{exclude}")
        commits = []
        for line in listed.splitlines():
            sha, *parents = line.split()
            message = git(repo.remote, "log", "-1", "--format=%B", sha)
            commits.append(
                {
                    "type": "commit",
                    "hash": sha,
                    "message": message.rstrip("\n") + "\n",
                    "parents": [{"hash": parent, "type": "commit"} for parent in parents],
                }
            )
        return self._page(request, commits, query)

    def _document(self, repo: FakeRepo, pull: FakePull) -> dict[str, Any]:
        return {
            "type": "pullrequest",
            "id": pull.number,
            "title": pull.title,
            "description": pull.body,
            "summary": {"raw": pull.body},
            "state": pull.state,
            "updated_on": pull.closed_at or "2026-10-20T10:00:00.000000+00:00",
            "source": {
                "branch": {"name": pull.head},
                "repository": {"full_name": repo.full_name},
            },
            "destination": {
                "branch": {"name": pull.base},
                "repository": {"full_name": repo.full_name},
            },
            "reviewers": list(getattr(pull, "reviewers", [])),
            "links": {"html": {"href": f"{WEB}/{repo.full_name}/pull-requests/{pull.number}"}},
        }

    def _pullrequests(
        self, repo: FakeRepo, rest: str, query: dict[str, list[str]], request: httpx.Request
    ) -> httpx.Response:
        if request.method == "GET" and rest == "/pullrequests":
            states = query.get("state", ["OPEN"])
            wanted = _bbql(query.get("q", [""])[0])
            found = [
                self._document(repo, pull)
                for pull in repo.pulls
                if pull.state in states
                and all(
                    {"source.branch.name": pull.head, "destination.branch.name": pull.base}.get(key)
                    == value
                    for key, value in wanted.items()
                )
            ]
            if query.get("sort") == ["-created_on"]:  # par numéro
                found.reverse()
            return self._page(request, found, query)
        if request.method == "GET":
            number = int(rest.removeprefix("/pullrequests/"))
            pull = next((p for p in repo.pulls if p.number == number), None)
            if pull is None:
                return self._error(404, "Pull request not found")
            return self._json(200, self._document(repo, pull))
        if not repo.push:
            return self._error(403, "You don't have access to this repository.")
        body = json.loads(request.content)
        if request.method == "POST":
            assert rest == "/pullrequests"
            head = body["source"]["branch"]["name"]
            base = body["destination"]["branch"]["name"]
            if self._branch(repo, head) is None:
                return self._error(
                    400, "There are no changes to be pulled", fields={"source": [head]}
                )
            pull = FakePull(
                number=next(self.numbers),
                title=body["title"],
                body=body.get("description", ""),
                head=head,
                base=base,
                state="OPEN",
            )
            repo.pulls.append(pull)
            return self._json(201, self._document(repo, pull))
        assert request.method == "PUT"
        number = int(rest.removeprefix("/pullrequests/"))
        pull = next((p for p in repo.pulls if p.number == number), None)
        if pull is None:
            return self._error(404, "Pull request not found")
        pull.title = body.get("title", pull.title)
        pull.body = body.get("description", pull.body)
        if "reviewers" in body:
            pull.reviewers = body["reviewers"]  # type: ignore[attr-defined]
        return self._json(200, self._document(repo, pull))

    def _page(
        self, request: httpx.Request, items: list[Any], query: dict[str, list[str]]
    ) -> httpx.Response:
        size = min(int(query.get("pagelen", ["10"])[0]), self.page_size)
        page = int(query.get("page", ["1"])[0])
        chunk = items[(page - 1) * size : page * size]
        body: dict[str, Any] = {"pagelen": size, "page": page, "size": len(items), "values": chunk}
        if page * size < len(items):
            following = dict(urllib.parse.parse_qsl(request.url.query.decode()))
            following["page"] = str(page + 1)
            path = request.url.raw_path.decode().partition("?")[0]
            body["next"] = f"https://api.bitbucket.org{path}?{urllib.parse.urlencode(following)}"
        return self._json(200, body)

    def _error(self, status: int, message: str, **extra: Any) -> httpx.Response:
        return self._json(status, {"type": "error", "error": {"message": message, **extra}})

    def _json(
        self, status: int, body: Any, *, headers: dict[str, str] | None = None
    ) -> httpx.Response:
        return httpx.Response(
            status,
            content=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", **(headers or {})},
        )


def _bbql(text: str) -> dict[str, str]:
    """Les conditions ``champ="valeur"`` d'une requête BBQL, reliées par ``AND``."""
    return {
        key: value.replace('\\"', '"').replace("\\\\", "\\")
        for key, value in re.findall(r'([a-z_.]+)\s*=\s*"((?:[^"\\]|\\.)*)"', text)
    }
