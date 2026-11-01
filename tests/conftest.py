"""Configuration commune des tests.

Les tests qui touchent le vrai réseau sont marqués ``network`` : ils sont sautés
par défaut, et lancés avec ``--run-network``. Les autres tournent hors ligne, sur
des réponses HTTP enregistrées dans ``tests/fixtures/``.

Six garde-fous valent pour tous les tests : le cache de l'utilisateur n'est jamais
touché (``Cache.default()`` en ouvre un dans le dossier du test), un test qui n'est pas
marqué ``network`` ne peut pas ouvrir de connexion (une requête non simulée par ``respx``
échoue au lieu de partir sur le réseau : jamais le vrai GitHub), ni lancer un vrai outil de
lockfile (npm, uv… : ``update.lockfiles`` les croit absents ; un test les simule avec
``FakeTools``), ni lancer git vers autre chose qu'un dépôt local (``forges.git`` : une adresse
``https://`` est refusée ; les tests clonent et poussent vers des dépôts « bare » de leur
dossier, ``fake_forge.make_remote``), aucun test n'ouvre le navigateur (``webbrowser.open``
échoue), et aucun ne touche le trousseau du système ni ``gh`` (``keychain`` : un trousseau en
mémoire, propre au test ; ``gh`` est absent, et le lancer échoue). Et la date du jour, qui
décide d'une fin de vie, est celle de l'enregistrement des réponses d'endoflife.date
(``_fixed_today``).

Le serveur de l'interface se teste avec ``api``, le client de test de FastAPI.
"""

import asyncio
import asyncio.base_events
import contextlib
import gzip
import json
import re
import subprocess
import time
import webbrowser
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import httpx
import keyring.backend
import keyring.core
import keyring.errors
import pytest
import respx
from fastapi.testclient import TestClient
from fixtures.record import RECORDED_ON

from forceupdate.checks import eol
from forceupdate.endoflife import BASE_URL as ENDOFLIFE
from forceupdate.forges import git as forge_git
from forceupdate.forges import github
from forceupdate.net import Cache, HttpClient
from forceupdate.net import cache as cache_module
from forceupdate.registries import Registry
from forceupdate.registries.crates import index_path
from forceupdate.registries.maven import coordinates, repository
from forceupdate.registries.nuget import NuGet
from forceupdate.registries.pypi import ACCEPT
from forceupdate.update import lockfiles
from forceupdate.web import Settings, create_app

FIXTURES = Path(__file__).parent / "fixtures"

API_TOKEN = "jeton-de-test"
API_PORT = 8765
API_BASE = f"http://127.0.0.1:{API_PORT}"


@pytest.fixture(autouse=True)
def _no_user_cache(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``Cache.default()`` ouvre un cache neuf, propre au test, jamais celui de l'utilisateur."""
    path = tmp_path_factory.mktemp("user-cache") / "cache.sqlite3"
    monkeypatch.setattr(cache_module, "default_cache_path", lambda: path)


@pytest.fixture(autouse=True)
def _no_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Hors des tests ``network``, ouvrir une connexion est une erreur du test."""
    if "network" in request.keywords:
        return

    async def refuse(self: object, *args: object, **kwargs: object) -> None:
        raise RuntimeError("test hors ligne : connexion refusée (requête non simulée par respx)")

    monkeypatch.setattr(asyncio.base_events.BaseEventLoop, "create_connection", refuse)


@pytest.fixture(autouse=True)
def _no_lock_tools(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Hors des tests ``network``, aucun outil de lockfile n'est installé, et en lancer un est
    une erreur du test : npm et uv touchent le vrai registre."""
    if "network" in request.keywords:
        return

    def refuse(command: list[str], **options: object) -> None:
        raise RuntimeError(f"test hors ligne : outil réel refusé ({command[0]})")

    monkeypatch.setattr(lockfiles, "_which", lambda program: None)
    monkeypatch.setattr(lockfiles, "_spawn", refuse)


_REMOTE_ADDRESS = re.compile(r"^(?!file://)[a-z][a-z0-9+.-]*://|^[^/\s]+@[^/\s]+:", re.I)


@pytest.fixture(autouse=True)
def _no_git_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Hors des tests ``network``, git ne parle qu'à des dépôts locaux (``file://``, un
    chemin) : jamais à GitHub."""
    if "network" in request.keywords:
        return
    spawn = forge_git._spawn

    def guarded(command: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
        remote = [argument for argument in command if _REMOTE_ADDRESS.match(argument)]
        if remote:
            raise RuntimeError(f"test hors ligne : git vers {remote[0]} refusé")
        return spawn(command, **options)

    monkeypatch.setattr(forge_git, "_spawn", guarded)


@pytest.fixture(autouse=True)
def _fixed_today(monkeypatch: pytest.MonkeyPatch) -> None:
    """Une fin de vie se juge à la date du jour : tous les tests se placent au jour où les
    réponses d'endoflife.date ont été enregistrées (``record.RECORDED_ON``), jamais à l'horloge."""
    monkeypatch.setattr(eol, "today", lambda: RECORDED_ON)


@pytest.fixture(autouse=True)
def _no_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ouvrir le navigateur (``forceupdate ui``) est une erreur du test."""

    def refuse(url: str, *args: object, **kwargs: object) -> bool:
        raise RuntimeError(f"test : navigateur refusé ({url})")

    monkeypatch.setattr(webbrowser, "open", refuse)


class MemoryKeyring(keyring.backend.KeyringBackend):
    """Un trousseau en mémoire : ``passwords[(service, nom)]``. Comme le Gestionnaire
    d'identification de Windows, il refuse un secret de plus de ``MAX_SECRET`` caractères."""

    priority = 1  # type: ignore[assignment]
    MAX_SECRET = 1280
    """2 560 octets, en UTF-16 : la limite de Windows (vérifiée à E20, erreur 1783 au-delà)."""

    def __init__(self) -> None:
        super().__init__()
        self.passwords: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.passwords.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        if len(password) > self.MAX_SECRET:
            raise keyring.errors.PasswordSetError(f"secret trop long ({len(password)})")
        self.passwords[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if self.passwords.pop((service, username), None) is None:
            raise keyring.errors.PasswordDeleteError(username)


@pytest.fixture(autouse=True)
def keychain(monkeypatch: pytest.MonkeyPatch) -> MemoryKeyring:
    """Le trousseau des tests : en mémoire, neuf pour chaque test, jamais celui du système. Et
    GitHub CLI n'est pas installé : le lancer est une erreur du test."""
    memory = MemoryKeyring()
    monkeypatch.setattr(keyring.core, "_keyring_backend", memory)

    def refuse(command: list[str], **options: object) -> None:
        raise RuntimeError(f"test : vrai gh refusé ({command[0]})")

    monkeypatch.setattr(github, "_which", lambda program: None)
    monkeypatch.setattr(github, "_run", refuse)
    return memory


@dataclass
class ToolCall:
    """Un outil lancé par ``update.lockfiles`` : son nom (``npm``), ses arguments, et ce qu'il
    a vu."""

    program: str
    arguments: list[str]
    cwd: Path
    env: dict[str, str]
    options: dict[str, Any]
    files: dict[str, str] = field(default_factory=dict)
    """Les fichiers que le test a demandé de lire au moment de l'appel (``FakeTools.watch``)."""


Handler = Callable[[ToolCall], int | tuple[int, str, str] | None]
"""Ce que fait un faux outil : écrire des fichiers, puis rendre son code de sortie (0 si
``None``), ou le code, la sortie et la sortie d'erreur."""


class FakeTools:
    """De faux outils de lockfile : ``programs`` sont « installés », chaque appel est noté
    (``calls``), et ``handlers[nom]`` fait ce que l'outil ferait."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, programs: Iterable[str]) -> None:
        self.programs = set(programs)
        self.calls: list[ToolCall] = []
        self.handlers: dict[str, Handler] = {}
        self.watched: list[Path] = []
        monkeypatch.setattr(lockfiles, "_which", self.which)
        monkeypatch.setattr(lockfiles, "_spawn", self.spawn)

    def which(self, program: str) -> str | None:
        return f"/outils/{program}" if program in self.programs else None

    def watch(self, *paths: Path) -> None:
        """Lit ``paths`` à chaque appel (``ToolCall.files``), pour voir ce que l'outil a vu."""
        self.watched += paths

    def spawn(self, command: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
        cwd = Path(options.get("cwd", "."))
        call = ToolCall(
            program=PurePosixPath(command[0]).name,
            arguments=list(command[1:]),
            cwd=cwd,
            env=dict(options.get("env") or {}),
            options=options,
            files={p.name: p.read_text(encoding="utf-8") for p in self.watched if p.exists()},
        )
        self.calls.append(call)
        handler = self.handlers.get(call.program)
        outcome = handler(call) if handler is not None else None
        code, out, err = (outcome or 0, "", "") if not isinstance(outcome, tuple) else outcome
        return subprocess.CompletedProcess(command, code, out.encode(), err.encode())

    def commands(self) -> list[str]:
        """Les appels, comme on les taperait : ``npm install --package-lock-only…``."""
        return [" ".join([call.program, *call.arguments]) for call in self.calls]


@pytest.fixture
def fake_tools(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeTools]:
    """``fake_tools("npm", "uv")`` : ces outils sont « installés », et simulés."""

    def make(*programs: str) -> FakeTools:
        return FakeTools(monkeypatch, programs)

    return make


def osv_querybatch(results: dict[str, Any]) -> Callable[[httpx.Request], httpx.Response]:
    """Une réponse ``querybatch`` d'OSV faite de ``results`` (``écosystème/nom@version`` →
    résultat, comme ``tests/fixtures/osv/queries.json``) ; ``{}`` (aucune faille) pour une
    version qui n'y est pas."""

    def respond(request: httpx.Request) -> httpx.Response:
        queries = json.loads(request.content)["queries"]
        found = [
            results.get(f"{q['package']['ecosystem']}/{q['package']['name']}@{q['version']}", {})
            for q in queries
        ]
        return httpx.Response(200, json={"results": found})

    return respond


@pytest.fixture
def recorded() -> Iterator[dict[str, respx.Route]]:
    """PyPI, npm, crates.io, le proxy Go, Packagist, RubyGems, Maven (Maven Central, Google Maven,
    le portail des plugins Gradle), nuget.org, OSV et endoflife.date simulés par ``respx``, avec
    les réponses enregistrées par ``tests/fixtures/record.py`` : flask, requests, aioredis,
    jinja2, werkzeug, django ; left-pad, @hapi/joi, colors, crossenv, lodash, p-limit ; rand,
    regex, time, anyhow, log, smallvec ; les modules Go de ``PACKAGES["goproxy"]`` ; les paquets
    PHP de ``PACKAGES["packagist"]`` ; les gems de ``PACKAGES["rubygems"]`` ; les artefacts de
    ``PACKAGES["maven"]`` ; les paquets NuGet de ``PACKAGES["nuget"]``. Tout autre paquet est
    introuvable (404). OSV connaît les failles des versions de ``tests/fixtures/osv/queries.json``
    ; pour les autres, il n'en connaît pas. endoflife.date connaît les produits de
    ``LIFECYCLES`` ; les autres sont introuvables (404). Rend les routes, par nom de paquet
    (``crates:<nom>`` pour crates.io, ``goproxy:<module>`` pour la liste d'un module Go,
    ``packagist:<nom>``, ``rubygems:<nom>``, ``maven:<groupe:artefact>``, ``nuget:<id>`` pour
    l'index d'un paquet NuGet, ``endoflife:<produit>``), plus ``osv:querybatch`` et ``osv:<id>``.
    """
    with recorded_responses() as routes:
        yield routes


@contextlib.contextmanager
def recorded_responses(
    extra: Callable[[respx.MockRouter], None] | None = None,
) -> Iterator[dict[str, respx.Route]]:
    """Ce que fait la fixture ``recorded``, hors de pytest : le serveur des tests de bout en
    bout du front s'en sert (``tests/e2e_server.py``), avec ses propres routes (``extra`` : un
    GitHub simulé)."""
    with respx.mock(assert_all_called=False) as router:
        if extra is not None:
            extra(router)
        routes = {}
        for path in sorted((FIXTURES / "pypi").glob("*.json")):
            routes[path.stem] = router.get(f"https://pypi.org/simple/{path.stem}/").respond(
                200, content=path.read_bytes(), headers={"content-type": ACCEPT}
            )
        for path in sorted((FIXTURES / "npm").glob("*.json")):
            name = path.stem.replace("__", "/")
            url = f"https://registry.npmjs.org/{name.replace('/', '%2F')}"
            routes[name] = router.get(url).respond(
                200, content=path.read_bytes(), headers={"content-type": "application/json"}
            )
        for path in sorted((FIXTURES / "crates").glob("*.jsonl")):
            url = f"https://index.crates.io/{index_path(path.stem)}"
            routes[f"crates:{path.stem}"] = router.get(url).respond(
                200, content=path.read_bytes(), headers={"content-type": "text/plain"}
            )
        for path in sorted((FIXTURES / "goproxy").glob("*.json")):
            name = path.stem.replace("__", "/")
            for suffix, answer in json.loads(path.read_text(encoding="utf-8")).items():
                route = router.get(f"https://proxy.golang.org/{suffix}").respond(
                    answer["status"],
                    content=answer["body"].encode(),
                    headers={"content-type": answer["content_type"]},
                )
                if suffix.endswith("/@v/list") and f"goproxy:{name}" not in routes:
                    routes[f"goproxy:{name}"] = route
        for path in sorted((FIXTURES / "packagist").glob("*.json")):
            name = path.stem.replace("__", "/")
            routes[f"packagist:{name}"] = router.get(
                f"https://repo.packagist.org/p2/{name}.json"
            ).respond(200, content=path.read_bytes(), headers={"content-type": "application/json"})
        for path in sorted((FIXTURES / "rubygems").glob("*.txt")):
            routes[f"rubygems:{path.stem}"] = router.get(
                f"https://index.rubygems.org/info/{path.stem}"
            ).respond(200, content=path.read_bytes(), headers={"content-type": "text/plain"})
        for path in sorted((FIXTURES / "maven").glob("*.xml")):
            name = path.stem.replace("__", ":")
            group, artifact = coordinates(name)
            url = f"{repository(name)}/{group.replace('.', '/')}/{artifact}/maven-metadata.xml"
            routes[f"maven:{name}"] = router.get(url).respond(
                200, content=path.read_bytes(), headers={"content-type": "text/xml"}
            )
        for path in sorted((FIXTURES / "nuget").glob("*.json.gz")):
            name = path.name.removesuffix(".json.gz")
            answers = json.loads(gzip.decompress(path.read_bytes()))
            for suffix, answer in answers.items():
                route = router.get(f"{NuGet.base_url}/{suffix}").respond(
                    answer["status"],
                    content=answer["body"].encode(),
                    headers={"content-type": answer["content_type"]},
                )
                if suffix.endswith("/index.json") and f"nuget:{name}" not in routes:
                    routes[f"nuget:{name}"] = route
        router.get(url__regex=r"^https://pypi\.org/simple/").respond(404)
        router.get(url__regex=r"^https://registry\.npmjs\.org/").respond(404, json={})
        router.get(url__regex=r"^https://index\.crates\.io/").respond(404)
        router.get(url__regex=r"^https://proxy\.golang\.org/").respond(404, text="not found")
        router.get(url__regex=r"^https://repo\.packagist\.org/").respond(
            404, text="404 not found, no packages here"
        )
        router.get(url__regex=r"^https://index\.rubygems\.org/").respond(
            404, text="This rubygem could not be found."
        )
        for maven in (r"repo1\.maven\.org/maven2", r"dl\.google\.com/android/maven2"):
            router.get(url__regex=rf"^https://{maven}/").respond(404, text="404 Not Found")
        router.get(url__regex=r"^https://plugins\.gradle\.org/m2/").respond(404)
        router.get(url__regex=r"^https://api\.nuget\.org/").respond(
            404, text="<Error><Code>BlobNotFound</Code></Error>"
        )
        for path in sorted((FIXTURES / "endoflife").glob("*.json")):
            routes[f"endoflife:{path.stem}"] = router.get(
                f"{ENDOFLIFE}/api/v1/products/{path.stem}"
            ).respond(200, content=path.read_bytes(), headers={"content-type": "application/json"})
        router.get(url__regex=r"^https://endoflife\.date/").respond(
            404, text="<!DOCTYPE html><title>Page not Found | endoflife.date</title>"
        )
        queries = json.loads((FIXTURES / "osv" / "queries.json").read_text(encoding="utf-8"))
        routes["osv:querybatch"] = router.post("https://api.osv.dev/v1/querybatch").mock(
            side_effect=osv_querybatch(queries)
        )
        for path in sorted((FIXTURES / "osv" / "vulns").glob("*.json")):
            routes[f"osv:{path.stem}"] = router.get(
                f"https://api.osv.dev/v1/vulns/{path.stem}"
            ).respond(200, content=path.read_bytes(), headers={"content-type": "application/json"})
        router.get(url__regex=r"^https://api\.osv\.dev/v1/vulns/").respond(404, json={})
        yield routes


@pytest.fixture
def make_tree(tmp_path: Path) -> Callable[..., Path]:
    """Crée des fichiers : ``make_tree({"chemin/posix": "contenu"}, root=tmp_path)``.

    Le contenu est écrit en UTF-8, sans conversion des fins de ligne. Rend ``root``.
    """

    def make(files: dict[str, str], root: Path = tmp_path) -> Path:
        for path, content in files.items():
            full = root / path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8", newline="")
        return root

    return make


@pytest.fixture
def no_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fait comme si git n'était pas installé : les sources locales parcourent le disque."""
    monkeypatch.setenv("PATH", "")


@pytest.fixture
def cache(tmp_path: Path) -> Iterator[Cache]:
    """Un cache disque neuf, dans le dossier du test : jamais celui de l'utilisateur."""
    disk = Cache(tmp_path / "cache.sqlite3")
    yield disk
    disk.close()


@pytest.fixture
def lookup(cache: Cache) -> Callable[..., list[Any]]:
    """Interroge un registre dans une session neuve : ``lookup(PyPI, "flask", "django")``.

    Rend, pour chaque nom, le ``PackageInfo`` ou l'exception levée. Les noms sont demandés
    en même temps. Le cache est celui du test, sauf ``cache=…`` ; les reprises n'attendent
    pas.
    """

    def run(
        registry: type[Registry],
        *names: str,
        cache: Cache = cache,
        offline: bool = False,
        base_url: str | None = None,
    ) -> list[Any]:
        async def no_sleep(_: float) -> None:
            pass

        async def main() -> list[Any]:
            async with HttpClient(offline=offline, sleep=no_sleep) as http:
                client = registry(http, cache, base_url=base_url)
                return await asyncio.gather(
                    *(client.package(name) for name in names), return_exceptions=True
                )

        return asyncio.run(main())

    return run


@pytest.fixture
def web_settings(tmp_path: Path) -> Settings:
    """Les réglages du serveur de test : jeton ``API_TOKEN``, port ``API_PORT``, chemins récents
    et front dans le dossier du test."""
    return Settings(
        token=API_TOKEN,
        port=API_PORT,
        state_dir=tmp_path / "état",
        static_dir=tmp_path / "static",
    )


@pytest.fixture
def api(web_settings: Settings) -> Iterator[TestClient]:
    """Le serveur de ``forceupdate ui`` (client de test de FastAPI), démarré, avec le jeton
    (``Authorization: Bearer``). Ses analyses ont le cache du test (``_no_user_cache``)."""
    with TestClient(
        create_app(web_settings),
        base_url=API_BASE,
        headers={"Authorization": f"Bearer {API_TOKEN}"},
    ) as client:
        yield client


@pytest.fixture
def finished(api: TestClient) -> Callable[[str], dict[str, Any]]:
    """``finished("/api/scans/<id>")`` : attend (10 s au plus) que la tâche ne tourne plus, et
    rend son état."""

    def wait(url: str) -> dict[str, Any]:
        deadline = time.monotonic() + 10
        while True:
            state: dict[str, Any] = api.get(url).json()
            if state["status"] != "running":
                return state
            assert time.monotonic() < deadline, f"{url} tourne encore"
            time.sleep(0.02)

    return wait


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-network",
        action="store_true",
        default=False,
        help="lance aussi les tests marqués network, qui touchent le vrai réseau",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "network: le test touche le vrai réseau (sauté sauf avec --run-network)"
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-network"):
        return
    skip_network = pytest.mark.skip(reason="test réseau : lancer avec --run-network")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip_network)
