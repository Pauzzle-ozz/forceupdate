"""Le serveur de ``forceupdate ui`` pour les tests de bout en bout du front (Playwright), et les
rapports qui servent d'exemples à ses tests de composants.

Comme les tests Python : jamais le réseau (PyPI, npm et OSV répondent par les réponses
enregistrées de ``tests/fixtures/``, ``conftest.recorded_responses``), jamais le cache ni les
chemins récents de l'utilisateur (un dossier temporaire), jamais le navigateur. Le jeton est
fixe, pour que les tests ouvrent l'adresse d'entrée ::

    uv run python tests/e2e_server.py --port 8799 --token jeton-e2e

Le front servi est celui de ``src/forceupdate/web/static/`` (``npm run build`` d'abord).

Jamais de vrai outil de lockfile non plus : npm et uv sont simulés (``fake_which``,
``fake_spawn``, comme ``conftest.FakeTools``) ; ils écrivent dans le lockfile les versions que
leur commande demande. Les autres outils sont absents (« commande à lancer »).

Jamais le vrai trousseau ni le vrai GitHub (E16) : le trousseau est en mémoire
(``conftest.MemoryKeyring``), GitHub est simulé (``FakeGitHub`` : l'échange du code, le device
flow, ``/user``, la révocation), ``gh`` aussi (connecté, token ``gho_e2e_gh``). Ses dépôts
(E17) aussi (``fake_forge.FakeGitHubRepos``, ``REPOSITORIES`` : des mini-projets de
``tests/projects``, une organisation qui restreint l'accès des applications, un dépôt public
d'un autre compte). Pour les PR (E18), chaque dépôt a un vrai dépôt git « bare » dans le
dossier temporaire (``fake_forge.make_remote``) : git y clone et y pousse, jamais vers GitHub ;
le faux GitHub ouvre et met à jour les PR. La page
d'autorisation est servie par un petit serveur sur ``localhost`` et un autre port : pour le
navigateur, c'est un autre site, comme github.com. Elle renvoie aussitôt vers l'adresse de
retour, avec le code ``e2e-code`` : le retour d'OAuth se teste pour de vrai (cookie
``SameSite=Strict`` absent, ``Sec-Fetch-Site: cross-site``).

GitLab aussi (E19, ``fake_gitlab.FakeGitLab``) : gitlab.com, dont la page d'autorisation (la
même fausse page, ``/oauth/authorize``) rend un code lié au ``code_challenge`` reçu (PKCE), et
une instance auto-hébergée (``gitlab-e2e.example.com``, token ``glpat-e2e-instance``) ; leurs
projets ont aussi leur dépôt « bare », où git pousse les MR.

Un rapport d'exemple (``--report`` : le JSON de ``scan --format json``, celui de
``GET /api/scans/{id}``, avec le chemin analysé remplacé par ``--source`` et des dates fixes)
pour les tests du front (``frontend/src/test/fixtures/``) ::

    uv run python tests/e2e_server.py --report tests/projects/vulnerable \\
        --source C:/Projets/vulnerable > frontend/src/test/fixtures/vulnerable.json
"""

import argparse
import http.server
import itertools
import json
import re
import subprocess
import sys
import tempfile
import threading
import urllib.parse
from pathlib import Path, PurePath
from typing import Any

import httpx
import keyring
import respx

sys.path.insert(0, str(Path(__file__).parent))

from conftest import MemoryKeyring, recorded_responses
from fake_forge import FakeGitHubRepos, FakeRepo, from_directory, make_remote, remotes_url
from fake_gitlab import FakeGitLab, FakeToken

from forceupdate import engine
from forceupdate.forges import github, gitlab
from forceupdate.models import ScanOptions
from forceupdate.net import cache as cache_module
from forceupdate.report import json as json_report
from forceupdate.sources.local import LocalSource
from forceupdate.update import lockfiles
from forceupdate.web import app, security

FAKE_TOOLS = ("npm", "uv")


def fake_which(program: str) -> str | None:
    return f"/outils-e2e/{program}" if program in FAKE_TOOLS else None


def fake_spawn(command: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
    """npm : chaque version exacte de ``package.json`` (épinglée le temps du passage) passe
    dans ``package-lock.json``. uv : chaque ``-P nom==version`` passe dans le fichier ``-o``.
    Le reste des commandes ne fait rien."""
    cwd = Path(options["cwd"])
    program, *arguments = command
    if PurePath(program).name == "npm":
        _npm(cwd)
    elif PurePath(program).name == "uv" and "-o" in arguments:
        _uv(cwd / arguments[arguments.index("-o") + 1], arguments)
    return subprocess.CompletedProcess(command, 0, b"", b"")


def _npm(cwd: Path) -> None:
    manifest = json.loads((cwd / "package.json").read_text(encoding="utf-8"))
    path = cwd / "package-lock.json"
    lock = json.loads(path.read_text(encoding="utf-8"))
    for section in ("dependencies", "devDependencies"):
        for name, spec in manifest.get(section, {}).items():
            entry = lock.get("packages", {}).get(f"node_modules/{name}")
            if entry is not None and re.fullmatch(r"\d+\.\d+\.\d+", spec):
                entry["version"] = spec
                entry["resolved"] = (
                    f"https://registry.npmjs.org/{name}/-/{name.split('/')[-1]}-{spec}.tgz"
                )
                entry.pop("integrity", None)
    path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8", newline="\n")


def _uv(output: Path, arguments: list[str]) -> None:
    text = output.read_text(encoding="utf-8")
    for index, argument in enumerate(arguments[:-1]):
        if argument == "-P":
            name, version = arguments[index + 1].split("==")
            pattern = rf"^{re.escape(name)}==\S+$"
            text = re.sub(pattern, f"{name}=={version}", text, flags=re.MULTILINE | re.IGNORECASE)
    output.write_text(text, encoding="utf-8", newline="\n")


USER = {
    "id": 4242,
    "login": "octo-e2e",
    "name": "Octo E2E",
    "html_url": "https://github.com/octo-e2e",
}

TOKENS: dict[str, str | None] = {
    "gho_e2e_oauth": "repo, read:org",
    "gho_e2e_device": "repo, read:org",
    "gho_e2e_gh": "repo, read:org, gist",
    "ghp_e2e_classic": "repo, read:org",
    "github_pat_e2e": None,
}
"""Les tokens que le faux GitHub accepte, avec leurs portées (``None`` : fine-grained)."""

PROJECTS = Path(__file__).parent / "projects"

REPOSITORIES = [
    from_directory("octo-e2e/vulnerable", PROJECTS / "vulnerable", private=True, language="Python"),
    FakeRepo(
        full_name="octo-e2e/a-jour",
        files={"requirements.txt": b"werkzeug==3.1.9\n", "app.py": b"print(1)\n"},
        language="Python",
    ),
    FakeRepo(full_name="octo-e2e/docs", files={"README.md": b"# docs\n"}, language="Markdown"),
    from_directory("atelier-e2e/outils", PROJECTS / "pip", push=False, language="Python"),
    FakeRepo(full_name="octo-e2e/ancien", archived=True, files={"requirements.txt": b"flask\n"}),
    FakeRepo(full_name="octo-e2e/neuf", empty=True),
    FakeRepo(
        full_name="pallets-e2e/flask",
        files={"requirements.txt": b"flask==0.12\n"},
        member=False,
        language="Python",
    ),
]
"""Les dépôts du faux GitHub : ceux du compte connecté, et un dépôt public d'un autre compte
(``pallets-e2e/flask``)."""

GITLAB_USER = {"id": 7777, "username": "renard-e2e", "name": "Renard E2E"}

GITLAB_PROJECTS = [
    from_directory("renard-e2e/outils/vulnerable", PROJECTS / "vulnerable", private=True),
    FakeRepo(full_name="renard-e2e/a-jour", files={"requirements.txt": b"werkzeug==3.1.9\n"}),
]
"""Les projets de gitlab.com : un dans un sous-groupe, un à jour."""

INSTANCE_HOST = "gitlab-e2e.example.com"
INSTANCE_TOKEN = "glpat-e2e-instance"
INSTANCE_PROJECTS = [
    FakeRepo(full_name="equipe-e2e/app", files={"requirements.txt": b"werkzeug==3.1.9\n"}),
]

LAB = FakeGitLab(
    repos=GITLAB_PROJECTS,
    tokens={"glpat-e2e": FakeToken()},
    user=dict(GITLAB_USER),
    client_id=gitlab.CLIENT_ID,
)
"""gitlab.com simulé ; ses tokens d'OAuth s'ajoutent à ``tokens`` quand il les donne."""
INSTANCE = FakeGitLab(
    repos=INSTANCE_PROJECTS,
    host=INSTANCE_HOST,
    tokens={INSTANCE_TOKEN: FakeToken(expires_at="2027-06-30")},
    user=dict(GITLAB_USER),
)


class FakeGitHub:
    """GitHub simulé pour le serveur de test : chaque code de device flow est en attente aux
    deux premières demandes (le temps de le voir à l'écran), puis donne ``gho_e2e_device``."""

    def __init__(self) -> None:
        self._codes = itertools.count(1)
        self._asked: dict[str, int] = {}

    def routes(self, router: respx.MockRouter) -> None:
        router.post("https://github.com/login/device/code").mock(side_effect=self._device)
        router.post("https://github.com/login/oauth/access_token").mock(side_effect=self._token)
        router.get("https://api.github.com/user").mock(side_effect=self._user)
        router.delete(url__regex=r"^https://api\.github\.com/applications/[^/]+/token$").respond(
            204
        )

    def _device(self, request: httpx.Request) -> httpx.Response:
        code = f"appareil-{next(self._codes)}"
        return httpx.Response(
            200,
            json={
                "device_code": code,
                "user_code": "WDJB-MJHT",
                "verification_uri": "https://github.com/login/device",
                "expires_in": 900,
                "interval": 1,
            },
        )

    def _token(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "device_code" in body:
            asked = self._asked[body["device_code"]] = self._asked.get(body["device_code"], 0) + 1
            if asked <= 2:
                return httpx.Response(200, json={"error": "authorization_pending"})
            return httpx.Response(200, json={"access_token": "gho_e2e_device"})
        if body.get("code") != "e2e-code":
            return httpx.Response(200, json={"error": "bad_verification_code"})
        return httpx.Response(200, json={"access_token": "gho_e2e_oauth", "scope": "repo,read:org"})

    def _user(self, request: httpx.Request) -> httpx.Response:
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        if token not in TOKENS:
            return httpx.Response(401, json={"message": "Bad credentials"})
        scopes = TOKENS[token]
        headers = {} if scopes is None else {"X-OAuth-Scopes": scopes}
        return httpx.Response(200, json=USER, headers=headers)


class _Authorize(http.server.BaseHTTPRequestHandler):
    """La page d'autorisation de GitHub (``/login/oauth/authorize``) ou de GitLab
    (``/oauth/authorize``) : accepte tout de suite, et renvoie vers l'adresse de retour avec un
    code (``e2e-code`` ; pour GitLab, un code lié au ``code_challenge`` reçu) et le ``state``."""

    def do_GET(self) -> None:
        parts = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parts.query)
        target = query["redirect_uri"][0]
        state = query["state"][0]
        code = "e2e-code"
        if parts.path == "/oauth/authorize":
            code = LAB.code_for(query["code_challenge"][0])
        location = f"{target}?{urllib.parse.urlencode({'code': code, 'state': state})}"
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        pass


def fake_authorize() -> str:
    """Lance la fausse page d'autorisation ; rend son adresse, sur ``localhost`` (un autre site
    que 127.0.0.1 pour le navigateur)."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Authorize)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://localhost:{server.server_address[1]}"


def fake_gh_run(command: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(command, 0, b"gho_e2e_gh\n", b"")


def serve(port: int, token: str, state_dir: Path) -> None:
    security.new_token = lambda: token
    lockfiles._which = fake_which
    lockfiles._spawn = fake_spawn
    keyring.set_keyring(MemoryKeyring())
    github._which = lambda program: "/outils-e2e/gh" if program == "gh" else None
    github._run = fake_gh_run
    authorize = fake_authorize()
    github.AUTHORIZE_URL = f"{authorize}/login/oauth/authorize"
    gitlab.AUTHORIZE_URL = f"{authorize}/oauth/authorize"
    app.serve(
        port=port,
        browser=False,
        state_dir=state_dir,
        announce=lambda url: print(url, flush=True),
    )


def report(path: Path, source: str) -> None:
    """Le rapport de ``path``, comme une analyse finie de l'API, sur la sortie standard."""
    found = engine.scan(LocalSource(path), ScanOptions())
    document = json.loads(json.dumps(json_report.build(found)).replace(found.source, source))
    for name in ("scanned_at", "oldest_data"):
        document[name] = "2026-10-28T17:30:00+00:00"
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.stdout.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=8799)
    parser.add_argument("--token", default="jeton-e2e")
    parser.add_argument("--report", type=Path, help="écrire le rapport de ce dossier, et sortir")
    parser.add_argument("--source", default="/projets/exemple", help="le chemin à y montrer")
    options = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="forceupdate-e2e-") as tmp:
        cache_module.default_cache_path = lambda: Path(tmp) / "cache.sqlite3"
        if options.report is None:
            remotes = Path(tmp) / "distants"
            for repo in [*REPOSITORIES, *GITLAB_PROJECTS]:
                if not repo.empty:
                    make_remote(repo, remotes)
            github.GIT_URL = remotes_url(remotes)
            gitlab.GIT_URL = remotes_url(remotes)
        repositories = FakeGitHubRepos(
            REPOSITORIES,
            tokens=set(TOKENS),
            organizations={"atelier-e2e": "ok", "nord-e2e": "restricted"},
        )

        def routes(router: respx.MockRouter) -> None:
            FakeGitHub().routes(router)
            repositories.routes(router)
            LAB.routes(router)
            INSTANCE.routes(router)

        with recorded_responses(routes):
            if options.report is not None:
                report(options.report.resolve(), options.source)
            else:
                serve(options.port, options.token, Path(tmp) / "état")


if __name__ == "__main__":
    main()
