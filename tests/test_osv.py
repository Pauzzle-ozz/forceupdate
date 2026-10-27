"""Le client d'OSV et ses avis : lecture d'un avis, version corrigée, ``querybatch`` puis
``vulns/{id}``, cache, hors ligne, et les erreurs, qui ne donnent jamais « pas de faille ».

Les avis viennent de ``tests/fixtures/osv`` (``tests/fixtures/record.py``)."""

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from conftest import osv_querybatch

from forceupdate.advisories import Advisory, Osv, OsvError, Query, Vulnerabilities, parse_vuln
from forceupdate.models import Ecosystem, Severity
from forceupdate.net import Cache, CacheKind, HttpClient

FIXTURES = Path(__file__).parent / "fixtures" / "osv"
BATCH = "https://api.osv.dev/v1/querybatch"
NPM, PYPI = Ecosystem.NPM, Ecosystem.PYPI
LODASH: Query = (NPM, "lodash", "4.17.15")
FLASK: Query = (PYPI, "flask", "0.12")
QUERY = "ecosystem=npm&name=lodash&version=4.17.15"
"""La clé de ``LODASH`` dans le cache, après ``https://api.osv.dev/v1/query?``."""


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


def recorded_vuln(vuln_id: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / "vulns" / f"{vuln_id}.json").read_bytes())
    return data


def advisory(vuln_id: str) -> Advisory:
    found = parse_vuln(recorded_vuln(vuln_id))
    assert found is not None
    return found


def synthetic(*affected: dict[str, Any], **fields: Any) -> Advisory:
    """Un avis écrit pour le test : ``affected`` au format d'OSV."""
    found = parse_vuln({"id": "TEST-1", "affected": list(affected), **fields})
    assert found is not None
    return found


def npm_range(*events: dict[str, str], name: str = "demo") -> dict[str, Any]:
    return {
        "package": {"ecosystem": "npm", "name": name},
        "ranges": [{"type": "SEMVER", "events": list(events)}],
    }


def ask(
    *queries: Query,
    cache: Cache | None = None,
    offline: bool = False,
    batch_size: int = 1000,
) -> dict[Query, Vulnerabilities | OsvError]:
    """Les failles de ``queries``, dans une session neuve ; les reprises n'attendent pas."""

    async def no_sleep(_: float) -> None:
        pass

    async def main() -> dict[Query, Vulnerabilities | OsvError]:
        async with HttpClient(offline=offline, sleep=no_sleep) as http:
            osv = Osv(http, cache or Cache.disabled(), batch_size=batch_size)
            return await osv.vulnerabilities(queries)

    return asyncio.run(main())


def ids(result: Vulnerabilities | OsvError) -> list[str]:
    assert isinstance(result, Vulnerabilities), result
    return [a.id for a in result.advisories]


def serve_vuln(router: respx.MockRouter, vuln_id: str, **changes: Any) -> respx.Route:
    return router.get(f"https://api.osv.dev/v1/vulns/{vuln_id}").respond(
        200, json={**recorded_vuln(vuln_id), **changes}
    )


# -- lire un avis --------------------------------------------------------------


def test_a_github_advisory() -> None:
    found = advisory("GHSA-35jh-r3h4-6jhm")
    assert found.id == "GHSA-35jh-r3h4-6jhm"
    assert found.aliases == ("CVE-2021-23337",)
    assert found.summary == "Command Injection in lodash"
    assert (found.severity, found.score) == (Severity.HIGH, 7.2)
    assert not found.malicious and not found.withdrawn and found.unavailable is None
    assert [entry.name for entry in found.affected] == [
        "lodash",
        "lodash-es",
        "lodash.template",
        "lodash-template",
        "lodash-rails",
    ]
    assert found.affected[0].ranges[0].events == (("introduced", "0"), ("fixed", "4.17.21"))
    assert found.url == "https://osv.dev/vulnerability/GHSA-35jh-r3h4-6jhm"


def test_an_advisory_without_summary_takes_the_first_line_of_its_details() -> None:
    found = advisory("PYSEC-2018-66")
    assert found.summary.startswith("The Pallets Project flask version Before 0.12.3 contains")
    assert found.severity is None and found.score is None
    long = parse_vuln({"id": "X", "details": ("mot " * 80).strip() + "\nsuite"})
    assert long is not None
    assert len(long.summary) <= 201
    assert long.summary.endswith("mot…")


def test_severity_comes_from_cvss_then_from_github() -> None:
    # CVSS 3 : le score calculé.
    assert advisory("GHSA-562c-5r94-xh97").score == 7.5
    # CVSS 4 seulement : la gravité que donne GitHub, sans score.
    found = advisory("GHSA-68rp-wp8r-4726")
    assert (found.severity, found.score) == (Severity.LOW, None)
    # Un score donné par la base.
    scored = parse_vuln({"id": "X", "database_specific": {"cvss": {"score": "9.1"}}})
    assert scored is not None and (scored.severity, scored.score) == (Severity.CRITICAL, 9.1)
    moderate = parse_vuln({"id": "X", "database_specific": {"severity": "MODERATE"}})
    assert moderate is not None and moderate.severity is Severity.MEDIUM
    nothing = parse_vuln({"id": "X", "severity": [{"type": "CVSS_V2", "score": "AV:N/AC:L"}]})
    assert nothing is not None and (nothing.severity, nothing.score) == (None, None)


@pytest.mark.parametrize(
    ("vuln_id", "malicious"),
    [
        ("MAL-2025-20690", True),  # base des paquets malveillants
        ("GHSA-c2m4-w5hm-vqjw", True),  # crossenv : GitHub, CWE-506
        ("GHSA-pjwm-rvh2-c87w", True),  # ua-parser-js 0.7.29, version piégée
        ("GHSA-35jh-r3h4-6jhm", False),
    ],
)
def test_malicious_packages(vuln_id: str, malicious: bool) -> None:
    assert advisory(vuln_id).malicious is malicious


def test_unreadable_advisories() -> None:
    assert parse_vuln(None) is None
    assert parse_vuln([]) is None
    assert parse_vuln({"id": ""}) is None
    odd = parse_vuln(
        {
            "id": "X",
            "aliases": "CVE-1",
            "withdrawn": "2024-01-01T00:00:00Z",
            "affected": [
                "?",
                {"package": "?"},
                {"package": {"ecosystem": "npm", "name": "a"}, "ranges": [{"type": "GIT"}]},
            ],
        }
    )
    assert odd is not None
    assert odd.aliases == () and odd.withdrawn
    assert [(e.name, e.ranges) for e in odd.affected] == [("a", ())]


# -- version corrigée ----------------------------------------------------------


@pytest.mark.parametrize(
    ("vuln_id", "fixed"),
    [
        ("GHSA-p6mc-m468-83gw", "4.17.19"),  # lodash-es est corrigé en 4.17.20 : pas lodash
        ("GHSA-35jh-r3h4-6jhm", "4.17.21"),
        ("GHSA-29mw-wpgm-hmr9", "4.17.21"),
        ("GHSA-xxjr-mmjv-4gpg", "4.17.23"),
        ("GHSA-f23m-r3pf-42rh", "4.18.0"),
        ("GHSA-r5fr-rjxr-66jc", "4.18.0"),
    ],
)
def test_fixed_in_lodash(vuln_id: str, fixed: str) -> None:
    assert advisory(vuln_id).fixed_in(NPM, "lodash", "4.17.15") == fixed


def test_fixed_in_two_branches() -> None:
    """Flask, CVE-2023-30861 : corrigée en 2.2.5, et en 2.3.2 pour la branche 2.3."""
    for vuln_id in ("GHSA-m2qf-hxjv-5gpq", "PYSEC-2023-62"):  # deux entrées, ou une plage
        found = advisory(vuln_id)
        assert found.fixed_in(PYPI, "flask", "0.12") == "2.2.5"
        assert found.fixed_in(PYPI, "Flask", "2.3.0") == "2.3.2"  # nom normalisé (PEP 503)
        assert found.affects(PYPI, "flask", "2.3.1")
        assert not found.affects(PYPI, "flask", "2.2.5")
        assert not found.affects(PYPI, "flask", "2.3.2")


def test_fixed_in_several_entries_of_a_package() -> None:
    # ua-parser-js : trois versions piégées, chacune corrigée par la suivante.
    found = advisory("GHSA-pjwm-rvh2-c87w")
    assert found.fixed_in(NPM, "ua-parser-js", "0.7.29") == "0.7.30"
    assert found.fixed_in(NPM, "ua-parser-js", "1.0.0") == "1.0.1"


def test_no_fix_known() -> None:
    crossenv = advisory("GHSA-c2m4-w5hm-vqjw")  # last_affected 1.0.1
    assert crossenv.fixed_in(NPM, "crossenv", "1.0.0") is None
    assert crossenv.affects(NPM, "crossenv", "1.0.1")  # la dernière concernée l'est
    assert not crossenv.affects(NPM, "crossenv", "1.0.2")
    flatmap = advisory("GHSA-9x64-5r7x-2q53")  # seulement une liste de versions
    assert flatmap.fixed_in(NPM, "flatmap-stream", "0.1.1") is None
    assert flatmap.affects(NPM, "flatmap-stream", "0.1.1")
    assert not flatmap.affects(NPM, "flatmap-stream", "0.1.2")
    assert flatmap.fixed_in(NPM, "flatmap-stream", "pas-une-version") is None
    assert flatmap.fixed_in(NPM, "autre-paquet", "0.1.1") is None


def test_a_fix_that_is_itself_concerned_is_skipped() -> None:
    """La faille revient en 1.1.0 (une régression) : depuis 1.0.0, 1.1.0 ne corrige rien."""
    found = synthetic(
        npm_range({"introduced": "0"}, {"fixed": "1.1.0"}),
        npm_range({"introduced": "1.1.0"}, {"fixed": "1.3.0"}),
    )
    assert found.fixed_in(NPM, "demo", "1.0.0") == "1.3.0"


def test_events_that_cannot_be_read_and_limits() -> None:
    found = synthetic(
        npm_range({"introduced": "0"}, {"fixed": "pas-une-version"}, {"fixed": "2.0.0"}),
        npm_range({"introduced": "3.0.0"}, {"limit": "3.5.0"}),
    )
    assert found.fixed_in(NPM, "demo", "1.0.0") == "2.0.0"
    assert found.affects(NPM, "demo", "3.1.0")
    assert not found.affects(NPM, "demo", "3.5.0")


# -- querybatch, puis vulns/{id} -----------------------------------------------


def test_ids_then_each_advisory_once(recorded: dict[str, respx.Route]) -> None:
    found = ask(LODASH, FLASK, LODASH, (NPM, "inconnu", "1.0.0"))
    assert recorded["osv:querybatch"].call_count == 1
    assert ids(found[LODASH]) == [
        "GHSA-29mw-wpgm-hmr9",
        "GHSA-35jh-r3h4-6jhm",
        "GHSA-f23m-r3pf-42rh",
        "GHSA-p6mc-m468-83gw",
        "GHSA-r5fr-rjxr-66jc",
        "GHSA-xxjr-mmjv-4gpg",
    ]
    assert len(ids(found[FLASK])) == 8  # 4 failles, chacune chez GitHub et chez PyPI
    assert ids(found[(NPM, "inconnu", "1.0.0")]) == []
    lodash = found[LODASH]
    assert isinstance(lodash, Vulnerabilities)
    assert all(a.unavailable is None for a in lodash.advisories)
    assert recorded["osv:GHSA-35jh-r3h4-6jhm"].call_count == 1
    body = json.loads(recorded["osv:querybatch"].calls.last.request.content)
    # Une seule fois chaque version, dans l'ordre demandé.
    assert body["queries"] == [
        {"package": {"ecosystem": "npm", "name": "lodash"}, "version": "4.17.15"},
        {"package": {"ecosystem": "PyPI", "name": "flask"}, "version": "0.12"},
        {"package": {"ecosystem": "npm", "name": "inconnu"}, "version": "1.0.0"},
    ]


def test_an_advisory_shared_by_two_versions_is_asked_once(
    respx_mock: respx.MockRouter,
) -> None:
    entry = {"vulns": [{"id": "GHSA-35jh-r3h4-6jhm", "modified": "x"}]}
    respx_mock.post(BATCH).mock(
        side_effect=osv_querybatch({"npm/lodash@4.17.15": entry, "npm/lodash@4.17.20": entry})
    )
    route = serve_vuln(respx_mock, "GHSA-35jh-r3h4-6jhm")
    found = ask(LODASH, (NPM, "lodash", "4.17.20"))
    assert route.call_count == 1
    assert ids(found[LODASH]) == ids(found[(NPM, "lodash", "4.17.20")])


def test_queries_go_in_batches(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(BATCH).mock(side_effect=osv_querybatch({}))
    queries = [(NPM, f"paquet-{n}", "1.0.0") for n in range(5)]
    found = ask(*queries, batch_size=2)
    assert route.call_count == 3
    sizes = sorted(len(json.loads(call.request.content)["queries"]) for call in route.calls)
    assert sizes == [1, 2, 2]
    assert all(ids(found[query]) == [] for query in queries)


def test_next_pages_are_followed(respx_mock: respx.MockRouter) -> None:
    pages = [
        {"results": [{}, {"vulns": [{"id": "A-1"}], "next_page_token": "page-2"}]},
        {"results": [{"vulns": [{"id": "A-2"}]}]},
    ]
    route = respx_mock.post(BATCH).mock(side_effect=[httpx.Response(200, json=p) for p in pages])
    respx_mock.get(url__regex=r"/v1/vulns/").respond(404)
    other, paged = (NPM, "a", "1.0.0"), (NPM, "b", "1.0.0")
    found = ask(other, paged)
    assert route.call_count == 2
    second = json.loads(route.calls[1].request.content)
    assert second == {
        "queries": [
            {
                "package": {"ecosystem": "npm", "name": "b"},
                "version": "1.0.0",
                "page_token": "page-2",
            }
        ]
    }
    assert ids(found[paged]) == ["A-1", "A-2"]
    assert ids(found[other]) == []


def test_too_many_pages(respx_mock: respx.MockRouter) -> None:
    page = {"results": [{"vulns": [{"id": "A-1"}], "next_page_token": "encore"}]}
    respx_mock.post(BATCH).respond(200, json=page)
    respx_mock.get(url__regex=r"/v1/vulns/").respond(404)
    result = ask(LODASH)[LODASH]
    assert isinstance(result, OsvError)
    assert str(result) == "OSV : trop de failles pour lodash 4.17.15 (plus de 10 pages)."


# -- erreurs : jamais « pas de faille » ----------------------------------------
# Repris de TestQueryOSVNetworkErrors (reference/argos_sca_parsers_tests.py). Argos rendait un
# résultat vide, comme si la version n'avait pas de faille ; ici, c'est une erreur.


@pytest.mark.parametrize(
    ("response", "message", "calls"),
    [
        (httpx.Response(500), "OSV : api.osv.dev en erreur (HTTP 500).", 4),
        (httpx.Response(429), "OSV : api.osv.dev limite le débit (HTTP 429).", 4),
        (httpx.ReadTimeout("lent"), "OSV : api.osv.dev ne répond pas (délai dépassé).", 4),
        (httpx.ConnectError("refusé"), "OSV : api.osv.dev injoignable (ConnectError).", 4),
        (httpx.Response(200, text="pas du JSON"), "OSV : réponse illisible", 1),
        (httpx.Response(200, json={"results": []}), "OSV : réponse illisible", 1),
        (httpx.Response(200, json={"results": ["?"]}), "OSV : réponse illisible", 1),
        (httpx.Response(400), "OSV : réponse inattendue (HTTP 400).", 1),
    ],
)
def test_an_error_is_never_no_vulnerability(
    respx_mock: respx.MockRouter, response: Any, message: str, calls: int
) -> None:
    route = respx_mock.post(BATCH)
    if isinstance(response, Exception):
        route.mock(side_effect=response)
    else:
        route.mock(return_value=response)
    found = ask(LODASH, FLASK)
    # Une recherche se rejoue sans risque : reprises comme pour un GET.
    assert route.call_count == calls
    for query in (LODASH, FLASK):
        result = found[query]
        assert isinstance(result, OsvError)
        assert str(result).startswith(message)


def test_an_advisory_that_cannot_be_read_stays_a_vulnerability(
    respx_mock: respx.MockRouter,
) -> None:
    entry = {"vulns": [{"id": "GHSA-1", "modified": "x"}, {"id": "GHSA-2"}, {"id": "GHSA-3"}]}
    respx_mock.post(BATCH).mock(side_effect=osv_querybatch({"npm/lodash@4.17.15": entry}))
    respx_mock.get("https://api.osv.dev/v1/vulns/GHSA-1").respond(500)
    respx_mock.get("https://api.osv.dev/v1/vulns/GHSA-2").respond(404)
    respx_mock.get("https://api.osv.dev/v1/vulns/GHSA-3").respond(200, text="pas du JSON")
    result = ask(LODASH)[LODASH]
    assert isinstance(result, Vulnerabilities)
    assert [(a.id, a.unavailable) for a in result.advisories] == [
        ("GHSA-1", "api.osv.dev en erreur (HTTP 500)"),
        ("GHSA-2", "OSV a répondu HTTP 404"),
        ("GHSA-3", "avis illisible"),
    ]


# -- cache et hors ligne -------------------------------------------------------


def test_the_cache_is_shared_between_sessions(
    recorded: dict[str, respx.Route], cache: Cache
) -> None:
    """L'avis en cache resert : querybatch arrondit sa date de modification à la microseconde
    (``…38.085813Z``), l'avis la donne en nanosecondes (``…38.085813876Z``), c'est la même."""
    first = ask(LODASH, cache=cache)
    second = ask(LODASH, cache=cache)
    assert recorded["osv:querybatch"].call_count == 1
    assert recorded["osv:GHSA-35jh-r3h4-6jhm"].call_count == 1
    assert ids(first[LODASH]) == ids(second[LODASH])
    assert cache.get(CacheKind.VULNERABILITIES, f"https://api.osv.dev/v1/query?{QUERY}")
    assert cache.get(CacheKind.ADVISORIES, "https://api.osv.dev/v1/vulns/GHSA-35jh-r3h4-6jhm")


def test_an_advisory_is_asked_again_when_modified_or_old(
    respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    clock = Clock()
    disk = Cache(tmp_path / "cache.sqlite3", clock=clock)
    modified = {"value": "2025-01-01T00:00:00Z"}

    def batch(request: httpx.Request) -> httpx.Response:
        vulns = [{"id": "GHSA-35jh-r3h4-6jhm", "modified": modified["value"]}]
        return httpx.Response(200, json={"results": [{"vulns": vulns}]})

    respx_mock.post(BATCH).mock(side_effect=batch)
    route = serve_vuln(respx_mock, "GHSA-35jh-r3h4-6jhm", modified="2025-01-01T00:00:00Z")
    ask(LODASH, cache=disk)
    clock.now += 2 * 3600  # la liste des failles a expiré, pas l'avis
    ask(LODASH, cache=disk)
    assert route.call_count == 1
    modified["value"] = "2026-01-01T00:00:00Z"  # l'avis a changé
    clock.now += 2 * 3600
    ask(LODASH, cache=disk)
    assert route.call_count == 2
    clock.now += 8 * 24 * 3600  # plus de 7 jours
    ask(LODASH, cache=disk)
    assert route.call_count == 3
    disk.close()


def test_a_stale_advisory_is_better_than_nothing(
    respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    clock = Clock()
    disk = Cache(tmp_path / "cache.sqlite3", clock=clock)
    respx_mock.post(BATCH).mock(
        side_effect=osv_querybatch(
            {"npm/lodash@4.17.15": {"vulns": [{"id": "GHSA-35jh-r3h4-6jhm"}]}}
        )
    )
    route = serve_vuln(respx_mock, "GHSA-35jh-r3h4-6jhm")
    ask(LODASH, cache=disk)
    clock.now += 8 * 24 * 3600
    route.respond(503)
    result = ask(LODASH, cache=disk)[LODASH]
    assert isinstance(result, Vulnerabilities)
    assert result.advisories[0].summary == "Command Injection in lodash"
    disk.close()


def test_offline_uses_the_cache_even_when_stale(
    recorded: dict[str, respx.Route], tmp_path: Path
) -> None:
    clock = Clock()
    disk = Cache(tmp_path / "cache.sqlite3", clock=clock)
    ask(LODASH, cache=disk)
    recorded["osv:querybatch"].reset()
    clock.now += 3 * 24 * 3600
    found = ask(LODASH, FLASK, cache=disk, offline=True)
    assert recorded["osv:querybatch"].call_count == 0
    lodash = found[LODASH]
    assert isinstance(lodash, Vulnerabilities) and len(lodash.advisories) == 6
    assert all(a.unavailable is None for a in lodash.advisories)
    assert (clock.now - lodash.fetched_at.timestamp()) == pytest.approx(3 * 24 * 3600)
    flask = found[FLASK]
    assert isinstance(flask, OsvError)
    assert str(flask) == "OSV : mode hors ligne, sans réponse en cache."
    disk.close()


def test_offline_with_ids_but_without_the_advisory(cache: Cache) -> None:
    cache.set(
        CacheKind.VULNERABILITIES,
        f"https://api.osv.dev/v1/query?{QUERY}",
        {"format": 1, "vulns": [["GHSA-35jh-r3h4-6jhm", "x"]]},
    )
    result = ask(LODASH, cache=cache, offline=True)[LODASH]
    assert isinstance(result, Vulnerabilities)
    (found,) = result.advisories
    assert (found.id, found.unavailable) == (
        "GHSA-35jh-r3h4-6jhm",
        "mode hors ligne, et l'avis n'est pas en cache",
    )


def test_a_cache_entry_of_another_format_is_ignored(
    recorded: dict[str, respx.Route], cache: Cache
) -> None:
    key = f"https://api.osv.dev/v1/query?{QUERY}"
    cache.set(CacheKind.VULNERABILITIES, key, {"format": 0, "vulns": []})
    assert len(ids(ask(LODASH, cache=cache)[LODASH])) == 6
    assert recorded["osv:querybatch"].call_count == 1


@pytest.mark.network
def test_the_real_osv() -> None:
    """Sur le vrai OSV : des failles corrigées depuis longtemps, qui ne bougent plus."""
    found = ask(LODASH, FLASK)
    lodash, flask = found[LODASH], found[FLASK]
    assert isinstance(lodash, Vulnerabilities) and isinstance(flask, Vulnerabilities)
    command_injection = next(a for a in lodash.advisories if a.id == "GHSA-35jh-r3h4-6jhm")
    assert command_injection.unavailable is None
    assert "CVE-2021-23337" in command_injection.aliases
    assert command_injection.severity is Severity.HIGH
    assert command_injection.fixed_in(NPM, "lodash", "4.17.15") == "4.17.21"
    dos = next(a for a in flask.advisories if a.id == "GHSA-562c-5r94-xh97")
    assert dos.fixed_in(PYPI, "flask", "0.12") == "0.12.3"
