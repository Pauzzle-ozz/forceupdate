"""Ce que demande chaque version d'un paquet, d'après son registre (E37) : le document npm le dit
pour toutes ses versions, PyPI version par version (son API JSON)."""

import asyncio
import json
from typing import Any

import pytest
import respx

from forceupdate.net import Cache, HttpClient
from forceupdate.net.cache import CacheKind
from forceupdate.registries import PackageInfo, RegistryError, Requires
from forceupdate.registries.npm import Npm
from forceupdate.registries.pypi import PyPI, SimpleIndex, requires_dist

NPM_URL = "https://registry.npmjs.org/demo"
PYPI_JSON = "https://pypi.org/pypi/{name}/{version}/json"


def packument(versions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "name": "demo",
        "dist-tags": {"latest": "2.0.0"},
        "versions": {v: {"name": "demo", "version": v, **fields} for v, fields in versions.items()},
        "time": {v: "2024-01-01T00:00:00.000Z" for v in versions},
    }


DEMO = packument(
    {
        "1.0.0": {"dependencies": {"minimatch": "^10.2.1"}},
        "1.1.0": {"dependencies": {"minimatch": "^10.2.1"}},
        "2.0.0": {
            "dependencies": {"minimatch": "^11.0.0"},
            "optionalDependencies": {"fsevents": "~2.3.0"},
            "peerDependencies": {"typescript": "^5"},
        },
        "3.0.0-beta.1": {"dependencies": {"minimatch": "^12.0.0"}},
    }
)


def npm_info(respx_mock: respx.MockRouter, cache: Cache) -> PackageInfo:
    respx_mock.get(NPM_URL).respond(200, json=DEMO)

    async def main() -> PackageInfo:
        async with HttpClient() as http:
            return await Npm(http, cache).package("demo")

    return asyncio.run(main())


def test_npm_says_what_each_stable_version_requires(
    respx_mock: respx.MockRouter, cache: Cache
) -> None:
    info = npm_info(respx_mock, cache)
    assert info.get("1.0.0").requires == Requires(dependencies={"minimatch": "^10.2.1"})  # type: ignore[union-attr]
    assert info.get("2.0.0").requires == Requires(  # type: ignore[union-attr]
        dependencies={"minimatch": "^11.0.0", "fsevents": "~2.3.0"}, peers={"typescript": "^5"}
    )
    # Pas pour une pré-version : on n'en propose pas.
    assert info.get("3.0.0-beta.1").requires is None  # type: ignore[union-attr]


def test_npm_requires_survive_the_cache_once_per_distinct_set(
    respx_mock: respx.MockRouter, cache: Cache
) -> None:
    fresh = npm_info(respx_mock, cache)
    cached = npm_info(respx_mock, cache)
    assert respx_mock.calls.call_count == 1
    assert [v.requires for v in cached.versions] == [v.requires for v in fresh.versions]
    # 1.0.0 et 1.1.0 demandent la même chose : rangé une fois.
    stored = cache.get(CacheKind.VERSIONS, NPM_URL)
    assert stored is not None
    assert len(stored.value["requires"]) == 2
    assert [row[-1] for row in stored.value["versions"]] == [0, 0, 1, None]


def test_the_requires_of_a_version_from_the_package_document(
    respx_mock: respx.MockRouter, cache: Cache
) -> None:
    respx_mock.get(NPM_URL).respond(200, json=DEMO)

    async def main() -> list[Requires | None]:
        async with HttpClient() as http:
            npm = Npm(http, cache)
            return [await npm.requires("demo", v) for v in ("1.1.0", "9.9.9")]

    known, unpublished = asyncio.run(main())
    assert known == Requires(dependencies={"minimatch": "^10.2.1"})
    assert unpublished is None


# -- PyPI : l'API JSON d'une version --------------------------------------------------------


def serve_version(
    respx_mock: respx.MockRouter, name: str, version: str, requires: list[str] | None
) -> respx.Route:
    payload = {"info": {"name": name, "version": version, "requires_dist": requires}}
    return respx_mock.get(PYPI_JSON.format(name=name, version=version)).respond(
        200, content=json.dumps(payload).encode(), headers={"content-type": "application/json"}
    )


def pypi_requires(
    cache: Cache, *pairs: tuple[str, str], offline: bool = False, registry: type[PyPI] = PyPI
) -> list[Any]:
    async def main() -> list[Any]:
        async with HttpClient(offline=offline) as http:
            client = registry(
                http,
                cache,
                base_url="https://pkgs.example/simple" if registry is SimpleIndex else None,
            )
            return await asyncio.gather(
                *(client.requires(name, version) for name, version in pairs),
                return_exceptions=True,
            )

    return asyncio.run(main())


def test_requires_dist_by_package() -> None:
    found = requires_dist(
        [
            "redis[hiredis]<6,>=4.2.0",
            'click>=8.0; python_version >= "3.8"',
            'click<8.0; python_version < "3.8"',
            "Typing_Extensions",
            'pytest>=7; extra == "test"',
            "not a requirement !",
        ]
    )
    assert found == Requires(
        dependencies={
            "redis": "<6,>=4.2.0",
            # Les marqueurs n'en gardent qu'une, qu'on ne sait pas choisir : l'une ou l'autre.
            "click": ">=8.0 || <8.0",
            "typing-extensions": "",
            "pytest": ">=7",
        }
    )
    # fastembed 0.8.0 : les mêmes bornes hautes, la basse selon Python : la plus large les contient.
    assert requires_dist(
        [
            'pillow<13.0,>=10.3.0; python_version < "3.12"',
            'pillow<13.0,>=11.0.0; python_version == "3.12"',
            'pillow<13.0,>=12.0.0; python_version >= "3.13"',
        ]
    ) == Requires(dependencies={"pillow": "<13.0,>=10.3.0"})
    assert requires_dist(['x<2; os_name == "nt"', 'x<2,>=1; os_name != "nt"']) == Requires(
        dependencies={"x": "<2"}
    )
    assert requires_dist(None) == Requires()  # aucune dépendance
    with pytest.raises(ValueError, match="liste attendue"):
        requires_dist("redis")


def test_pypi_asks_each_version_once_and_keeps_it(
    respx_mock: respx.MockRouter, cache: Cache
) -> None:
    route = serve_version(respx_mock, "arq", "0.26.3", ["redis[hiredis]<6,>=4.2.0", "click>=8.0"])
    first = pypi_requires(cache, ("arq", "0.26.3"), ("Arq", "0.26.3"))
    assert first == [Requires(dependencies={"redis": "<6,>=4.2.0", "click": ">=8.0"})] * 2
    assert route.call_count == 1
    # Une autre session : le cache (une version publiée ne change pas).
    assert pypi_requires(cache, ("arq", "0.26.3")) == first[:1]
    assert route.call_count == 1
    # Hors ligne aussi.
    assert pypi_requires(cache, ("arq", "0.26.3"), offline=True) == first[:1]


def test_pypi_an_unknown_version_says_nothing(respx_mock: respx.MockRouter, cache: Cache) -> None:
    route = respx_mock.get(PYPI_JSON.format(name="arq", version="9.9")).respond(404)
    assert pypi_requires(cache, ("arq", "9.9")) == [None]
    assert pypi_requires(cache, ("arq", "9.9")) == [None]
    assert route.call_count == 1  # rangé aussi


def test_pypi_offline_without_cache_is_an_error(cache: Cache) -> None:
    (error,) = pypi_requires(cache, ("arq", "0.26.3"), offline=True)
    assert isinstance(error, RegistryError)


def test_pypi_an_unreadable_answer_is_an_error_not_cached(
    respx_mock: respx.MockRouter, cache: Cache
) -> None:
    respx_mock.get(PYPI_JSON.format(name="arq", version="1.0")).respond(200, json={"info": 3})
    (error,) = pypi_requires(cache, ("arq", "1.0"))
    assert isinstance(error, RegistryError)
    assert "illisible" in str(error)


def test_a_declared_index_has_no_json_api(respx_mock: respx.MockRouter, cache: Cache) -> None:
    assert pypi_requires(cache, ("arq", "0.26.3"), registry=SimpleIndex) == [None]
    assert respx_mock.calls.call_count == 0
