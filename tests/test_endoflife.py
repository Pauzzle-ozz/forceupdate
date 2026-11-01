"""Le client d'endoflife.date (E27) : la réponse lue, le cache de 24 h, un produit inconnu, une
erreur qui ne donne jamais de faux constat."""

import asyncio
from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
import respx

from forceupdate.endoflife import (
    BASE_URL,
    EndOfLifeDate,
    EndOfLifeError,
    Product,
    ProductNotFound,
    Release,
)
from forceupdate.net import Cache, CacheKind, HttpClient

Routes = dict[str, respx.Route]
URL = f"{BASE_URL}/api/v1/products/python"


def ask(cache: Cache, *names: str, offline: bool = False) -> list[Any]:
    """Demande des produits dans une session neuve : le ``Product`` ou l'exception, pour chacun."""

    async def no_sleep(_: float) -> None:
        pass

    async def main() -> list[Any]:
        async with HttpClient(offline=offline, sleep=no_sleep) as http:
            client = EndOfLifeDate(http, cache)
            return await asyncio.gather(*(client.product(n) for n in names), return_exceptions=True)

    return asyncio.run(main())


def release(product: Product, name: str) -> Release:
    return next(r for r in product.releases if r.name == name)


def test_the_recorded_answer(recorded: Routes, cache: Cache) -> None:
    (python,) = ask(cache, "python")
    assert isinstance(python, Product)
    assert (python.name, python.label, python.url) == (
        "python",
        "Python",
        "https://endoflife.date/python",
    )
    assert release(python, "3.8") == Release(
        name="3.8",
        label="3.8",
        released=date(2019, 10, 14),
        lts=False,
        lts_from=None,
        eol=True,
        eol_from=date(2024, 10, 7),
        latest="3.8.20",
    )
    # Python 2.7 vient après 3.2 dans la page : l'ordre n'est pas tout à fait celui des dates.
    names = [r.name for r in python.releases]
    assert names.index("2.7") > names.index("3.2")


def test_lts_and_dates_that_may_be_missing(recorded: Routes, cache: Cache) -> None:
    node, go = ask(cache, "nodejs", "go")
    twenty_six = release(node, "26")
    assert (twenty_six.lts, twenty_six.lts_from, twenty_six.latest) == (
        True,
        date(2026, 10, 28),
        "26.13.0",
    )
    assert twenty_six.is_lts(date(2026, 11, 1)) and not twenty_six.is_lts(date(2026, 10, 1))
    one = release(node, "1")
    # Fini, sans date connue : isEol décide.
    assert (one.eol, one.eol_from) == (True, None)
    assert one.ended(date(2000, 1, 1))
    # Maintenu, sans date fixée.
    newest = release(go, "1.27")
    assert (newest.eol, newest.eol_from) == (False, None)
    assert not newest.ended(date(2030, 1, 1))


def test_the_date_wins_over_the_flag() -> None:
    # isEol a été calculé le jour où la page a été faite ; la date compte d'abord.
    cycle = Release(name="9", label="9", eol=False, eol_from=date(2026, 11, 10))
    assert not cycle.ended(date(2026, 11, 9))
    assert cycle.ended(date(2026, 11, 10))


def test_one_request_per_product_and_the_cache(recorded: Routes, cache: Cache) -> None:
    ask(cache, "python", "python")
    assert recorded["endoflife:python"].call_count == 1
    entry = cache.get(CacheKind.LIFECYCLES, URL)
    assert entry is not None and entry.value["releases"][0][0] == "3.15"
    (again,) = ask(cache, "python")
    assert recorded["endoflife:python"].call_count == 1
    assert isinstance(again, Product) and release(again, "3.8").eol_from == date(2024, 10, 7)


def test_an_unknown_product(recorded: Routes, cache: Cache) -> None:
    (error,) = ask(cache, "pas-un-produit")
    assert isinstance(error, ProductNotFound)
    assert str(error) == "pas-un-produit est inconnu d'endoflife.date."
    # Rangé aussi : pas redemandé.
    (again,) = ask(cache, "pas-un-produit", offline=True)
    assert isinstance(again, ProductNotFound)


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        ({"status_code": 503}, "endoflife.date : "),
        ({"status_code": 418}, "endoflife.date : réponse inattendue pour python (HTTP 418)."),
        (
            {"status_code": 200, "json": {"result": {"name": "python"}}},
            "endoflife.date : réponse illisible pour python (pas de « releases »).",
        ),
    ],
)
def test_an_error_is_never_a_finding(
    respx_mock: respx.MockRouter, cache: Cache, answer: dict[str, Any], message: str
) -> None:
    respx_mock.get(URL).respond(**answer)
    (error,) = ask(cache, "python")
    assert isinstance(error, EndOfLifeError)
    assert str(error).startswith(message)
    assert cache.get(CacheKind.LIFECYCLES, URL) is None


def test_offline(recorded: Routes, cache: Cache, tmp_path: Any) -> None:
    (error,) = ask(Cache(tmp_path / "vide.sqlite3"), "python", offline=True)
    assert isinstance(error, EndOfLifeError)
    assert str(error) == "endoflife.date : mode hors ligne, et python n'est pas dans le cache."
    ask(cache, "python")
    (cached,) = ask(cache, "python", offline=True)
    assert isinstance(cached, Product)


def test_a_stale_entry_serves_offline_only(
    recorded: Routes, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1_000_000.0]
    clock: Callable[[], float] = lambda: now[0]  # noqa: E731
    cache = Cache(tmp_path / "cache.sqlite3", clock=clock)
    ask(cache, "python")
    now[0] += 24 * 3600 + 1
    (cached,) = ask(cache, "python", offline=True)
    assert isinstance(cached, Product)
    ask(cache, "python")
    assert recorded["endoflife:python"].call_count == 2


@pytest.mark.network
def test_the_real_endoflife_date(tmp_path: Any) -> None:
    django, unknown = ask(Cache(tmp_path / "cache.sqlite3"), "django", "pas-un-produit-xyz")
    assert isinstance(django, Product) and django.label == "Django"
    assert release(django, "3.2").eol_from == date(2024, 4, 1)
    assert isinstance(unknown, ProductNotFound)
