"""Configuration commune des tests.

Les tests qui touchent le vrai réseau sont marqués ``network`` : ils sont sautés
par défaut, et lancés avec ``--run-network``. Les autres tournent hors ligne, sur
des réponses HTTP enregistrées dans ``tests/fixtures/``.

Deux garde-fous valent pour tous les tests : le cache de l'utilisateur n'est jamais
touché (``Cache.default()`` en ouvre un dans le dossier du test), et un test qui n'est pas
marqué ``network`` ne peut pas ouvrir de connexion (une requête non simulée par ``respx``
échoue au lieu de partir sur le réseau).
"""

import asyncio
import asyncio.base_events
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from forceupdate.net import Cache, HttpClient
from forceupdate.net import cache as cache_module
from forceupdate.registries import Registry
from forceupdate.registries.pypi import ACCEPT

FIXTURES = Path(__file__).parent / "fixtures"


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
    """PyPI, npm et OSV simulés par ``respx``, avec les réponses enregistrées par
    ``tests/fixtures/record.py`` : flask, requests, aioredis, jinja2, werkzeug ; left-pad,
    @hapi/joi, colors, crossenv, lodash. Tout autre paquet est introuvable (404). OSV connaît
    les failles des versions de ``tests/fixtures/osv/queries.json`` ; pour les autres, il n'en
    connaît pas.
    Rend les routes, par nom de paquet, plus ``osv:querybatch`` et ``osv:<id>``.
    """
    with respx.mock(assert_all_called=False) as router:
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
        router.get(url__regex=r"^https://pypi\.org/simple/").respond(404)
        router.get(url__regex=r"^https://registry\.npmjs\.org/").respond(404, json={})
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
