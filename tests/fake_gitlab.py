"""Un GitLab simulé (E19), à brancher sur un routeur ``respx`` : ``/user``, les portées d'un
token (``/personal_access_tokens/self``, ``/oauth/token/info``), ``/projects`` (paginé par
``Link``, ``membership``, ``min_access_level``), un projet par son chemin complet, ses commits,
son arborescence (paginée, sans les tailles, comme GitLab) et ses fichiers bruts, ses branches,
``compare``, les MR (liste filtrée, création, mise à jour, 409 si elle existe déjà), et OAuth
(échange du code avec PKCE, refresh token à usage unique, révocation).

Sur gitlab.com ou sur une instance (``host``). Les projets sont des ``fake_forge.FakeRepo`` :
un projet peut avoir un vrai dépôt git « bare », local (``fake_forge.make_remote``), où git
clone et pousse (``gitlab.GIT_URL = remotes_url(…)``), et les branches, commits et arbres que
rend l'API sont alors les siens. Jamais le vrai GitLab.

Un token inconnu, expiré ou révoqué reçoit 401 ; sans token, seuls les projets publics se
voient (un privé rend 404, comme sur GitLab). Chaque réponse porte les en-têtes
``RateLimit-*``, qui décomptent."""

import base64
import hashlib
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

RESET = 1793208000
"""L'heure de remise à zéro des requêtes, en secondes depuis 1970."""

USER = {"id": 4242, "username": "renard", "name": "Renard Roux"}


@dataclass(kw_only=True)
class FakeToken:
    """Un token du faux GitLab : personnel (``pat``) ou d'OAuth (``oauth``)."""

    kind: str = "pat"
    scopes: tuple[str, ...] = ("api",)
    expires_at: str | None = None
    """Un token personnel : sa date d'expiration (``2027-01-31``)."""
    valid: bool = True
    """Faux : expiré ou révoqué (401)."""


@dataclass(kw_only=True)
class FakeGrant:
    """Une autorisation OAuth donnée à l'application : son token et son refresh token."""

    access: str
    refresh: str
    used: bool = False
    """Le refresh token a déjà servi : il ne sert plus."""


@dataclass(kw_only=True)
class FakeGitLab:
    """GitLab sur ``host``, avec ses projets et ses tokens."""

    repos: Iterable[FakeRepo] = ()
    host: str = "gitlab.com"
    tokens: dict[str, FakeToken] | None = None
    """``None`` : tout token est accepté (personnel, portée ``api``)."""
    page_size: int = 100
    user: dict[str, Any] = field(default_factory=lambda: dict(USER))
    client_id: str = "app-gitlab-de-test"
    codes: dict[str, str] = field(default_factory=dict)
    """Code d'autorisation → ``code_challenge`` attendu (PKCE)."""

    def __post_init__(self) -> None:
        self.projects = {repo.full_name.lower(): repo for repo in self.repos}
        self.ids = {name: number for number, name in enumerate(self.projects, start=101)}
        self.remaining = 2000
        self.requests: list[httpx.Request] = []
        self.down = False
        self.grants: list[FakeGrant] = []
        self.revoked: list[str] = []
        self.numbers = itertools.count(1)
        """Les numéros (``iid``) des MR créées."""
        self._serial = itertools.count(1)

    @property
    def base(self) -> str:
        return f"https://{self.host}"

    def routes(self, router: respx.MockRouter) -> None:
        api = re.escape(f"{self.base}/api/v4/")
        router.route(url__regex=f"^{api}").mock(side_effect=self._dispatch)
        router.get(f"{self.base}/oauth/token/info").mock(side_effect=self._token_info)
        router.post(f"{self.base}/oauth/token").mock(side_effect=self._oauth_token)
        router.post(f"{self.base}/oauth/revoke").mock(side_effect=self._revoke)

    def request(self, full_name: str, iid: int | None = None) -> FakePull:
        """Une MR de ``full_name`` (la seule, si ``iid`` n'est pas donné)."""
        found = self.projects[full_name.lower()].pulls
        if iid is None:
            assert len(found) == 1, found
            return found[0]
        return next(pull for pull in found if pull.number == iid)

    def files(self) -> list[str]:
        """Les fichiers téléchargés, ``chemin/du/projet:fichier``, dans l'ordre."""
        found = []
        for request in self.requests:
            match = re.match(
                r"^/api/v4/projects/([^/]+)/repository/files/([^/]+)/raw$",
                request.url.raw_path.decode().split("?")[0],
            )
            if match:
                project = urllib.parse.unquote(match[1])
                found.append(f"{project}:{urllib.parse.unquote(match[2])}")
        return found

    def authorize(self, verifier: str) -> str:
        """Un code d'autorisation, comme si la personne avait autorisé l'application, pour le
        ``code_verifier`` donné."""
        code = f"code-{next(self._serial)}"
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        self.codes[code] = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return code

    def code_for(self, challenge: str) -> str:
        """Un code d'autorisation pour le ``code_challenge`` d'une page d'autorisation."""
        code = f"code-{next(self._serial)}"
        self.codes[code] = challenge
        return code

    def expire(self, token: str) -> None:
        """Le token expire (2 h sont passées) ; son refresh token reste bon."""
        assert self.tokens is not None
        self.tokens[token].valid = False

    # -- OAuth -------------------------------------------------------------------------

    def _grant(self) -> dict[str, Any]:
        serial = next(self._serial)
        grant = FakeGrant(access=f"glo-acces-{serial}", refresh=f"glo-refresh-{serial}")
        self.grants.append(grant)
        if self.tokens is None:
            self.tokens = {}
        self.tokens[grant.access] = FakeToken(kind="oauth")
        return {
            "access_token": grant.access,
            "token_type": "Bearer",
            "expires_in": 7200,
            "refresh_token": grant.refresh,
            "scope": "api",
            "created_at": 1793200000,
        }

    def _oauth_token(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content)
        if body.get("client_id") != self.client_id:
            return httpx.Response(401, json={"error": "invalid_client"})
        if body.get("grant_type") == "authorization_code":
            challenge = self.codes.pop(body.get("code", ""), None)
            verifier = body.get("code_verifier", "")
            digest = hashlib.sha256(verifier.encode("ascii")).digest()
            given = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
            if challenge is None or challenge != given or "client_secret" in body:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json=self._grant())
        if body.get("grant_type") == "refresh_token":
            grant = next((g for g in self.grants if g.refresh == body.get("refresh_token")), None)
            if grant is None or grant.used:
                return httpx.Response(
                    400,
                    json={
                        "error": "invalid_grant",
                        "error_description": "The provided authorization grant is invalid.",
                    },
                )
            grant.used = True
            assert self.tokens is not None
            self.tokens[grant.access].valid = False  # l'ancien token cesse de marcher
            return httpx.Response(200, json=self._grant())
        return httpx.Response(400, json={"error": "unsupported_grant_type"})

    def _revoke(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content)
        token = body.get("token", "")
        self.revoked.append(token)
        if self.tokens is not None and token in self.tokens:
            self.tokens[token].valid = False
        return httpx.Response(200, json={})

    def _token_info(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        token = self._token(request)
        found = self.tokens.get(token) if self.tokens is not None and token else None
        if found is None or not found.valid or found.kind != "oauth":
            return httpx.Response(401, json={"error": "invalid_token"})
        return httpx.Response(200, json={"scope": list(found.scopes), "expires_in": 7000})

    # -- l'API -------------------------------------------------------------------------

    def _token(self, request: httpx.Request) -> str | None:
        authorization = request.headers.get("authorization", "")
        return authorization.removeprefix("Bearer ") if authorization else None

    def _dispatch(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.down:
            raise httpx.ConnectError("GitLab simulé : coupé", request=request)
        token = self._token(request)
        if token is not None and self.tokens is not None:
            found = self.tokens.get(token)
            if found is None or not found.valid:
                return self._json(401, {"message": "401 Unauthorized"})
        self.remaining = max(self.remaining - 1, 0)
        raw = request.url.raw_path.decode()
        path, _, query_text = raw.partition("?")
        path = path.removeprefix("/api/v4")
        query = urllib.parse.parse_qs(query_text)
        if path == "/user":
            if token is None:
                return self._json(401, {"message": "401 Unauthorized"})
            return self._json(200, {**self.user, "web_url": f"{self.base}/{self.user['username']}"})
        if path == "/personal_access_tokens/self":
            given = self._details(token)
            if given is None:
                return self._json(401, {"message": "401 Unauthorized"})
            if given.kind != "pat":  # ce que répond gitlab.com pour un token d'OAuth (E19)
                message = (
                    "400 Bad request - This endpoint requires token type to be a personal "
                    "access token"
                )
                return self._json(400, {"message": message})
            return self._json(
                200, {"scopes": list(given.scopes), "expires_at": given.expires_at, "active": True}
            )
        if path == "/projects":
            if token is None:
                return self._json(401, {"message": "401 Unauthorized"})
            assert query.get("membership") == ["true"]
            minimum = int(query.get("min_access_level", ["0"])[0])
            listed = [
                self._project(repo)
                for repo in self.projects.values()
                if repo.member and (minimum < 30 or repo.push)
            ]
            return self._page(request, listed, query)
        match = re.fullmatch(r"/projects/([^/]+)(/.*)?", path)
        if match is None:
            return self._json(404, {"message": "404 Not Found"})
        repo = self.projects.get(urllib.parse.unquote(match[1]).lower())
        if repo is None or (repo.private and (token is None or not repo.member)):
            return self._json(404, {"message": "404 Project Not Found"})
        return self._repository(repo, match[2] or "", query, request)

    def _details(self, token: str | None) -> FakeToken | None:
        if token is None:
            return None
        if self.tokens is None:
            return FakeToken()
        return self.tokens.get(token)

    def _project(self, repo: FakeRepo, *, permissions: bool = False) -> dict[str, Any]:
        full_name = repo.full_name
        data: dict[str, Any] = {
            "id": self.ids[full_name.lower()],
            "path_with_namespace": full_name,
            "name": full_name.rpartition("/")[2],
            "visibility": "private" if repo.private else "public",
            "archived": repo.archived,
            "empty_repo": repo.empty,
            "default_branch": None if repo.empty else repo.default_branch,
            "web_url": f"{self.base}/{full_name}",
            "http_url_to_repo": f"{self.base}/{full_name}.git",
            "last_activity_at": repo.pushed_at,
        }
        if repo.fork:
            data["forked_from_project"] = {"id": 1, "path_with_namespace": "amont/projet"}
        if permissions:
            level = 30 if repo.push else 20
            data["permissions"] = {"project_access": None, "group_access": {"access_level": level}}
        return data

    def _repository(
        self, repo: FakeRepo, rest: str, query: dict[str, list[str]], request: httpx.Request
    ) -> httpx.Response:
        if rest == "":
            return self._json(200, self._project(repo, permissions=True))
        if rest.startswith("/merge_requests"):
            return self._merge_requests(repo, rest, query, request)
        if repo.empty:
            return self._json(404, {"message": "404 Tree Not Found"})
        if rest.startswith("/repository/commits/"):
            ref = urllib.parse.unquote(rest.removeprefix("/repository/commits/"))
            commit = self._resolve(repo, ref)
            if commit is None:
                return self._json(404, {"message": "404 Commit Not Found"})
            return self._json(200, {"id": commit, "short_id": commit[:8]})
        if rest == "/repository/tree":
            return self._tree(repo, query, request)
        match = re.fullmatch(r"/repository/files/([^/]+)/raw", rest)
        if match:
            assert query.get("ref") == [repo.commit], query
            content = repo.files.get(urllib.parse.unquote(match[1]))
            if content is None:
                return self._json(404, {"message": "404 File Not Found"})
            return self._response(200, content=content, type="text/plain")
        if rest.startswith("/repository/branches/"):
            branch = urllib.parse.unquote(rest.removeprefix("/repository/branches/"))
            head = self._branch(repo, branch)
            if head is None:
                return self._json(404, {"message": "404 Branch Not Found"})
            return self._json(200, {"name": branch, "commit": {"id": head}})
        if rest == "/repository/compare":
            return self._compare(repo, query)
        return self._json(404, {"message": "404 Not Found"})

    def _branch(self, repo: FakeRepo, branch: str) -> str | None:
        if repo.remote is None:
            return repo.commit if branch == repo.default_branch else None
        found = git(repo.remote, "for-each-ref", "--format=%(objectname)", f"refs/heads/{branch}")
        return found.strip() or None

    def _resolve(self, repo: FakeRepo, ref: str) -> str | None:
        if re.fullmatch(r"[0-9a-f]{40}", ref):
            return ref
        return self._branch(repo, ref)

    def _tree(
        self, repo: FakeRepo, query: dict[str, list[str]], request: httpx.Request
    ) -> httpx.Response:
        ref = query["ref"][0]
        if query.get("recursive") == ["true"]:
            assert ref == repo.commit, (ref, repo.commit)
            return self._page(request, self._entries(repo), query)
        assert repo.remote is not None, "la racine d'un arbre se lit dans un dépôt « bare »"
        listed = git(repo.remote, "ls-tree", "-z", ref).split("\0")
        entries = []
        for line in listed:
            if not line:
                continue
            meta, _, name = line.partition("\t")
            mode, kind, oid = meta.split()
            gitlab_mode = "040000" if mode == "040000" or kind == "tree" else mode
            entries.append(
                {"id": oid, "name": name, "type": kind, "path": name, "mode": gitlab_mode}
            )
        return self._page(request, entries, query)

    def _entries(self, repo: FakeRepo) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        directories: set[str] = set()
        for path in sorted(repo.files):
            parts = path.split("/")
            for depth in range(1, len(parts)):
                directories.add("/".join(parts[:depth]))
            entries.append({"path": path, "name": parts[-1], "type": "blob", "mode": "100644"})
        for path in repo.symlinks:
            entries.append({"path": path, "name": path, "type": "blob", "mode": "120000"})
        for path in repo.submodules:
            entries.append({"path": path, "name": path, "type": "commit", "mode": "160000"})
        entries += [
            {"path": d, "name": d.rpartition("/")[2], "type": "tree", "mode": "040000"}
            for d in sorted(directories)
        ]
        for entry in entries:
            entry["id"] = hashlib.sha1(entry["path"].encode()).hexdigest()
        return entries

    def _compare(self, repo: FakeRepo, query: dict[str, list[str]]) -> httpx.Response:
        assert repo.remote is not None
        base, head = query["from"][0], query["to"][0]
        assert query.get("straight", ["false"]) == ["false"]
        listed = git(repo.remote, "rev-list", "--reverse", "--parents", f"{base}..{head}")
        commits = []
        for line in listed.splitlines():
            sha, *parents = line.split()
            message = git(repo.remote, "log", "-1", "--format=%B", sha)
            commits.append({"id": sha, "parent_ids": parents, "message": message.rstrip("\n")})
        return self._json(200, {"commits": commits, "diffs": [], "compare_same_ref": False})

    def _document(self, repo: FakeRepo, pull: FakePull) -> dict[str, Any]:
        project = self.ids[repo.full_name.lower()]
        return {
            "iid": pull.number,
            "web_url": f"{self.base}/{repo.full_name}/-/merge_requests/{pull.number}",
            "title": pull.title,
            "description": pull.body,
            "state": pull.state,
            "source_branch": pull.head,
            "target_branch": pull.base,
            "source_project_id": project,
            "target_project_id": project,
            "closed_at": pull.closed_at if pull.state == "closed" else None,
        }

    def _merge_requests(
        self, repo: FakeRepo, rest: str, query: dict[str, list[str]], request: httpx.Request
    ) -> httpx.Response:
        if request.method == "GET":
            assert rest == "/merge_requests"
            state = query.get("state", ["opened"])[0]
            found = [
                self._document(repo, pull)
                for pull in repo.pulls
                if state in ("all", pull.state)
                and (not query.get("source_branch") or query["source_branch"][0] == pull.head)
                and (not query.get("target_branch") or query["target_branch"][0] == pull.base)
            ]
            if query.get("sort") == ["desc"]:  # ``order_by=created_at`` : par numéro
                found.reverse()
            return self._json(200, found)
        if not repo.push:
            return self._json(403, {"message": "403 Forbidden"})
        body = json.loads(request.content)
        if request.method == "POST":
            head, base = body["source_branch"], body["target_branch"]
            existing = next(
                (
                    p
                    for p in repo.pulls
                    if p.state == "opened" and p.head == head and p.base == base
                ),
                None,
            )
            if existing is not None:
                message = (
                    "Another open merge request already exists for this source branch: "
                    f"!{existing.number}"
                )
                return self._json(409, {"message": [message]})
            if self._branch(repo, head) is None:
                return self._json(400, {"message": {"source_branch": ["is invalid"]}})
            pull = FakePull(
                number=next(self.numbers),
                title=body["title"],
                body=body["description"],
                head=head,
                base=base,
                state="opened",
            )
            repo.pulls.append(pull)
            return self._json(201, self._document(repo, pull))
        assert request.method == "PUT"
        number = int(rest.removeprefix("/merge_requests/"))
        pull = next((p for p in repo.pulls if p.number == number), None)
        if pull is None:
            return self._json(404, {"message": "404 Not found"})
        pull.title = body.get("title", pull.title)
        pull.body = body.get("description", pull.body)
        return self._json(200, self._document(repo, pull))

    def _page(
        self, request: httpx.Request, items: list[Any], query: dict[str, list[str]]
    ) -> httpx.Response:
        size = min(int(query.get("per_page", ["20"])[0]), self.page_size)
        page = int(query.get("page", ["1"])[0])
        chunk = items[(page - 1) * size : page * size]
        headers = {}
        if page * size < len(items):
            following = dict(urllib.parse.parse_qsl(request.url.query.decode()))
            following["page"] = str(page + 1)
            path = request.url.raw_path.decode().partition("?")[0]
            url = f"{self.base}{path}?{urllib.parse.urlencode(following)}"
            headers["Link"] = f'<{url}>; rel="next"'
        return self._json(200, chunk, headers=headers)

    def _json(
        self, status: int, body: Any, *, headers: dict[str, str] | None = None
    ) -> httpx.Response:
        return self._response(
            status, content=json.dumps(body).encode(), type="application/json", headers=headers
        )

    def _response(
        self,
        status: int,
        *,
        content: bytes,
        type: str,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        return httpx.Response(
            status,
            content=content,
            headers={
                "Content-Type": type,
                "RateLimit-Limit": "2000",
                "RateLimit-Remaining": str(self.remaining),
                "RateLimit-Reset": str(RESET),
                **(headers or {}),
            },
        )
