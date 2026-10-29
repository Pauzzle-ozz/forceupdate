"""Un GitHub simulé pour les dépôts (E17), à brancher sur un routeur ``respx`` :
``/user/repos`` (paginé par ``Link``), ``/repos/{o}/{r}``, ses commits, son arborescence et ses
fichiers bruts, ``/user/orgs`` et ``/orgs/{org}/repos`` (accès des applications restreint, SSO).
Sert aux tests (``test_forges_github.py``, ``test_sources_forge.py``,
``test_web_repositories.py``) et au serveur de bout en bout du front (``e2e_server.py``).

Un token inconnu reçoit 401 ; sans token, seuls les dépôts publics se voient (un privé rend
404, comme sur GitHub). Chaque réponse porte les en-têtes ``X-RateLimit-*``, qui décomptent."""

import hashlib
import json
import re
import urllib.parse
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import respx

API = "https://api.github.com"
RESET = 1793208000
"""L'heure de remise à zéro des requêtes, en secondes depuis 1970."""

RESTRICTED = (
    "Although you appear to have the correct authorization credentials, the `{org}` "
    "organization has enabled OAuth App access restrictions, meaning that data access to "
    "third-parties is limited."
)


@dataclass(kw_only=True)
class FakeRepo:
    full_name: str
    files: dict[str, bytes] = field(default_factory=dict)
    private: bool = False
    archived: bool = False
    fork: bool = False
    push: bool = True
    empty: bool = False
    language: str | None = None
    pushed_at: str = "2026-10-20T10:00:00Z"
    default_branch: str = "main"
    truncated: bool = False
    size: int | None = None
    """``size`` de l'API (Ko) ; par défaut 0 pour un dépôt vide, 1 sinon."""
    symlinks: tuple[str, ...] = ()
    submodules: tuple[str, ...] = ()
    member: bool = True
    """Le compte y a accès : ``/user/repos`` le liste. Sinon, c'est le dépôt d'un autre compte,
    qui ne se voit que par son nom (et seulement s'il est public)."""

    @property
    def commit(self) -> str:
        return hashlib.sha1(self.full_name.encode()).hexdigest()

    def metadata(self, *, permissions: bool = True) -> dict[str, Any]:
        owner, name = self.full_name.split("/")
        size = self.size if self.size is not None else (0 if self.empty else 1)
        data: dict[str, Any] = {
            "full_name": self.full_name,
            "name": name,
            "owner": {"login": owner},
            "private": self.private,
            "archived": self.archived,
            "fork": self.fork,
            "default_branch": self.default_branch,
            "html_url": f"https://github.com/{self.full_name}",
            "clone_url": f"https://github.com/{self.full_name}.git",
            "language": self.language,
            "pushed_at": self.pushed_at,
            "size": size,
        }
        if permissions:
            data["permissions"] = {"admin": False, "push": self.push, "pull": True}
        return data


def from_directory(full_name: str, directory: Path, **flags: Any) -> FakeRepo:
    """Un dépôt fait des fichiers de ``directory`` (un mini-projet de ``tests/projects``)."""
    files = {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }
    return FakeRepo(full_name=full_name, files=files, **flags)


class FakeGitHubRepos:
    """GitHub, pour ``tokens`` (``None`` : tout token est accepté)."""

    def __init__(
        self,
        repos: Iterable[FakeRepo],
        *,
        tokens: set[str] | None = None,
        organizations: dict[str, str] | None = None,
        page_size: int = 100,
    ) -> None:
        self.repos = {repo.full_name.lower(): repo for repo in repos}
        self.tokens = tokens
        self.organizations = organizations or {}
        """Organisation → ``ok``, ``restricted`` (accès des applications) ou ``sso``."""
        self.orgs_scope = True
        """Faux : ``/user/orgs`` rend 403 (token sans ``read:org``)."""
        self.page_size = page_size
        self.remaining = 5000
        self.requests: list[httpx.Request] = []
        self.down = False
        """Vrai : GitHub ne répond plus (coupure réseau)."""

    def routes(self, router: respx.MockRouter) -> None:
        pattern = r"^https://api\.github\.com/(user/repos|user/orgs|orgs/|repos/)"
        router.get(url__regex=pattern).mock(side_effect=self._dispatch)

    def contents(self) -> list[str]:
        """Les fichiers téléchargés, ``owner/nom:chemin``, dans l'ordre."""
        found = []
        for request in self.requests:
            match = re.match(r"^/repos/([^/]+/[^/]+)/contents/(.+)$", request.url.path)
            if match:
                found.append(f"{match[1]}:{urllib.parse.unquote(match[2])}")
        return found

    # -- les réponses ------------------------------------------------------------------

    def _dispatch(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.down:
            raise httpx.ConnectError("GitHub simulé : coupé", request=request)
        authorization = request.headers.get("authorization", "")
        token = authorization.removeprefix("Bearer ") if authorization else None
        if token is not None and self.tokens is not None and token not in self.tokens:
            return self._json(401, {"message": "Bad credentials"})
        self.remaining = max(self.remaining - 1, 0)
        path = request.url.path
        query = urllib.parse.parse_qs(request.url.query.decode())
        if path == "/user/repos":
            if token is None:
                return self._json(401, {"message": "Requires authentication"})
            listed = [r.metadata() for r in self.repos.values() if r.member]
            return self._page(request, listed, query)
        if path == "/user/orgs":
            if not self.orgs_scope:
                return self._json(403, {"message": "Must have admin rights to Repository."})
            return self._json(200, [{"login": org} for org in self.organizations])
        match = re.fullmatch(r"/orgs/([^/]+)/repos", path)
        if match:
            return self._organization(match[1])
        match = re.fullmatch(r"/repos/([^/]+/[^/]+)(/.*)?", path)
        if match is None:
            return self._json(404, {"message": "Not Found"})
        repo = self.repos.get(urllib.parse.unquote(match[1]).lower())
        if repo is None or (repo.private and (token is None or not repo.member)):
            return self._json(404, {"message": "Not Found"})
        return self._repository(repo, match[2] or "", query, request)

    def _repository(
        self, repo: FakeRepo, rest: str, query: dict[str, list[str]], request: httpx.Request
    ) -> httpx.Response:
        if rest == "":
            return self._json(
                200, repo.metadata(permissions=request.headers.get("authorization") is not None)
            )
        if rest == "/commits":
            if repo.empty:
                return self._json(409, {"message": "Git Repository is empty."})
            return self._json(200, [{"sha": repo.commit}])
        if rest.startswith("/commits/"):
            if repo.empty:
                return self._json(409, {"message": "Git Repository is empty."})
            if urllib.parse.unquote(rest.removeprefix("/commits/")) != repo.default_branch:
                return self._json(422, {"message": "No commit found for SHA"})
            assert request.headers["accept"] == "application/vnd.github.sha"
            return self._response(200, content=repo.commit.encode(), type="text/plain")
        if rest == f"/git/trees/{repo.commit}":
            assert query.get("recursive") == ["1"]
            return self._json(200, self._tree(repo))
        if rest.startswith("/contents/"):
            assert query.get("ref") == [repo.commit], query
            assert request.headers["accept"] == "application/vnd.github.raw"
            path = urllib.parse.unquote(rest.removeprefix("/contents/"))
            content = repo.files.get(path)
            if content is None:
                return self._json(404, {"message": "Not Found"})
            return self._response(200, content=content, type="application/vnd.github.raw")
        return self._json(404, {"message": "Not Found"})

    def _tree(self, repo: FakeRepo) -> dict[str, Any]:
        entries: list[dict[str, Any]] = []
        directories: set[str] = set()
        for path, content in sorted(repo.files.items()):
            parts = path.split("/")
            for depth in range(1, len(parts)):
                directories.add("/".join(parts[:depth]))
            entries.append({"path": path, "mode": "100644", "type": "blob", "size": len(content)})
        for path in repo.symlinks:
            entries.append({"path": path, "mode": "120000", "type": "blob", "size": 12})
        for path in repo.submodules:
            entries.append({"path": path, "mode": "160000", "type": "commit"})
        entries += [{"path": d, "mode": "040000", "type": "tree"} for d in sorted(directories)]
        return {"sha": "arbre-" + repo.commit[:8], "tree": entries, "truncated": repo.truncated}

    def _organization(self, org: str) -> httpx.Response:
        state = self.organizations.get(org)
        if state == "restricted":
            return self._json(403, {"message": RESTRICTED.format(org=org)})
        if state == "sso":
            return self._json(
                403,
                {"message": "Resource protected by organization SAML enforcement."},
                headers={"X-GitHub-SSO": f"required; url=https://github.com/orgs/{org}/sso"},
            )
        if state is None:
            return self._json(404, {"message": "Not Found"})
        return self._json(200, [])

    def _page(
        self, request: httpx.Request, items: list[Any], query: dict[str, list[str]]
    ) -> httpx.Response:
        size = min(int(query.get("per_page", ["30"])[0]), self.page_size)
        page = int(query.get("page", ["1"])[0])
        chunk = items[(page - 1) * size : page * size]
        headers = {}
        if page * size < len(items):
            following = dict(urllib.parse.parse_qsl(request.url.query.decode()))
            following["page"] = str(page + 1)
            url = f"{API}{request.url.path}?{urllib.parse.urlencode(following)}"
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
                "X-RateLimit-Limit": "5000",
                "X-RateLimit-Remaining": str(self.remaining),
                "X-RateLimit-Reset": str(RESET),
                **(headers or {}),
            },
        )
