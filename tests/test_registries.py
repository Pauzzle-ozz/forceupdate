"""Ce qui est commun aux registres : une requête par paquet, le cache, le hors ligne, les
erreurs qui donnent « introuvable » ou « non concluant »."""

import asyncio
import dataclasses
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from forceupdate import registries
from forceupdate.models import Ecosystem
from forceupdate.net import Cache, CacheKind, HttpClient
from forceupdate.registries import PackageInfo, PackageNotFound, PackageVersion, RegistryError
from forceupdate.registries.npm import Npm
from forceupdate.registries.pypi import ACCEPT, PyPI

URL = "https://pypi.org/simple/demo/"
PAGE = {
    "meta": {"_last-serial": 1, "api-version": "1.4"},
    "name": "demo",
    "versions": ["1.0", "1.1"],
    "files": [
        {"filename": "demo-1.0.tar.gz", "upload-time": "2024-01-01T00:00:00Z", "yanked": "x"},
        {"filename": "demo-1.1.tar.gz", "upload-time": "2024-02-01T00:00:00Z", "yanked": False},
    ],
}

Lookup = Callable[..., list[Any]]


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


def serve(respx_mock: respx.MockRouter, page: dict[str, Any] = PAGE) -> respx.Route:
    return respx_mock.get(URL).respond(
        200, content=json.dumps(page).encode(), headers={"content-type": ACCEPT}
    )


def test_for_ecosystem() -> None:
    async def main() -> None:
        async with HttpClient() as http:
            assert isinstance(registries.for_ecosystem(Ecosystem.PYPI, http, Cache(None)), PyPI)
            assert isinstance(registries.for_ecosystem(Ecosystem.NPM, http, Cache(None)), Npm)
            with pytest.raises(LookupError, match=r"crates\.io"):
                registries.for_ecosystem(Ecosystem.CRATES_IO, http, Cache(None))

    asyncio.run(main())


def test_one_request_per_package_in_a_session(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    route = serve(respx_mock)
    results = lookup(PyPI, "demo", "Demo", "demo", cache=Cache(None))
    assert route.call_count == 1
    assert all(isinstance(r, PackageInfo) for r in results)
    assert results[0] is results[1] is results[2]


def test_the_cache_is_shared_between_sessions(
    respx_mock: respx.MockRouter, lookup: Lookup, cache: Cache
) -> None:
    route = serve(respx_mock)
    [fresh] = lookup(PyPI, "demo")
    [cached] = lookup(PyPI, "demo")
    assert route.call_count == 1
    # Relue du cache, la réponse est la même, datée du moment où elle y a été rangée.
    assert cached == dataclasses.replace(fresh, fetched_at=cached.fetched_at)
    assert abs((cached.fetched_at - fresh.fetched_at).total_seconds()) < 60
    entry = cache.get(CacheKind.VERSIONS, URL)
    assert entry is not None
    assert entry.value["versions"][0] == ["1.0", "2024-01-01T00:00:00+00:00", True, "x", None]


def test_without_cache_every_session_asks(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    route = serve(respx_mock)
    lookup(PyPI, "demo", cache=Cache.disabled())
    lookup(PyPI, "demo", cache=Cache.disabled())
    assert route.call_count == 2


def test_an_expired_entry_is_asked_again(respx_mock: respx.MockRouter, tmp_path: Path) -> None:
    clock = Clock()
    cache = Cache(tmp_path / "cache.sqlite3", clock=clock)
    route = serve(respx_mock)

    async def session() -> PackageInfo:
        async with HttpClient() as http:
            return await PyPI(http, cache).package("demo")

    asyncio.run(session())
    clock.now += 3599
    asyncio.run(session())
    assert route.call_count == 1
    clock.now += 2
    asyncio.run(session())
    assert route.call_count == 2
    cache.close()


def test_a_cache_entry_of_another_format_is_ignored(
    respx_mock: respx.MockRouter, lookup: Lookup, cache: Cache
) -> None:
    route = serve(respx_mock)
    cache.set(CacheKind.VERSIONS, URL, {"format": 0, "versions": "ancien format"})
    [info] = lookup(PyPI, "demo")
    assert isinstance(info, PackageInfo)
    assert route.call_count == 1


def test_not_found_is_cached(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    route = respx_mock.get(URL).respond(404)
    [first] = lookup(PyPI, "demo")
    [second] = lookup(PyPI, "demo")
    assert isinstance(first, PackageNotFound)
    assert isinstance(second, PackageNotFound)
    assert str(second) == str(first)
    assert route.call_count == 1


@pytest.mark.parametrize(
    ("response", "message", "calls"),
    [
        (httpx.Response(500), "PyPI : pypi.org en erreur (HTTP 500).", 4),
        (httpx.Response(403), "PyPI : réponse inattendue pour demo (HTTP 403).", 1),
        (httpx.ConnectError("refusé"), "PyPI : pypi.org injoignable (ConnectError).", 4),
    ],
)
def test_an_error_is_inconclusive_and_not_cached(
    respx_mock: respx.MockRouter, lookup: Lookup, response: Any, message: str, calls: int
) -> None:
    route = respx_mock.get(URL)
    if isinstance(response, Exception):
        route.mock(side_effect=response)
    else:
        route.mock(return_value=response)
    [error] = lookup(PyPI, "demo")
    assert isinstance(error, RegistryError)
    assert str(error) == message
    assert route.call_count == calls
    # Rien n'est rangé : la session suivante réessaie.
    lookup(PyPI, "demo")
    assert route.call_count == 2 * calls


def test_offline_uses_the_cache_even_when_stale(
    respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    clock = Clock()
    cache = Cache(tmp_path / "cache.sqlite3", clock=clock)
    route = serve(respx_mock)

    async def session(*, offline: bool) -> PackageInfo:
        async with HttpClient(offline=offline) as http:
            return await PyPI(http, cache).package("demo")

    online = asyncio.run(session(offline=False))
    clock.now += 7 * 24 * 3600
    offline = asyncio.run(session(offline=True))
    assert route.call_count == 1
    assert offline.latest == online.latest == "1.1"
    # La date dit d'où vient la donnée : de la session d'il y a une semaine.
    assert offline.fetched_at.timestamp() == pytest.approx(clock.now - 7 * 24 * 3600)
    cache.close()


def test_offline_without_cache_is_inconclusive(
    respx_mock: respx.MockRouter, lookup: Lookup
) -> None:
    [error] = lookup(PyPI, "demo", offline=True)
    assert isinstance(error, RegistryError)
    assert str(error) == "PyPI : mode hors ligne, et demo n'est pas dans le cache."
    assert respx_mock.calls.call_count == 0


def test_an_unreachable_registry_is_asked_once(
    respx_mock: respx.MockRouter, lookup: Lookup
) -> None:
    # Sans réseau, le premier paquet épuise ses reprises ; les suivants échouent tout de suite.
    route = respx_mock.route(host="registry.npmjs.org").mock(side_effect=httpx.ConnectError("non"))
    names = ["a", "b", "c", "d", "e"]

    async def main() -> list[Any]:
        async def no_sleep(_: float) -> None:
            pass

        async with HttpClient(sleep=no_sleep) as http:
            npm = Npm(http, Cache(None))
            first = await asyncio.gather(npm.package(names[0]), return_exceptions=True)
            rest = await asyncio.gather(
                *(npm.package(n) for n in names[1:]), return_exceptions=True
            )
            return first + rest

    errors = asyncio.run(main())
    assert all(isinstance(e, RegistryError) for e in errors)
    assert {str(e) for e in errors} == {"npm : registry.npmjs.org injoignable (ConnectError)."}
    assert route.call_count == 4


def test_package_info_lookups() -> None:
    info = PackageInfo(
        ecosystem=Ecosystem.PYPI,
        name="demo",
        versions=(
            PackageVersion(version="1.0"),
            PackageVersion(version="1.8c1", yanked=True),
            PackageVersion(version="2004d"),
        ),
        latest="1.0",
        fetched_at=datetime(2026, 10, 27, tzinfo=UTC),
    )
    assert info.get("1.0") is info.versions[0]
    assert info.get("1.0.0") is info.versions[0]
    assert info.get("1.8rc1") is info.versions[1]
    assert info.get("2004d") is info.versions[2]
    assert info.get("2.0") is None
    assert info.get("pas une version") is None
    assert info.available() == ["1.0", "2004d"]
