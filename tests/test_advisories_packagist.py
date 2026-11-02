"""Les avis de sécurité de Packagist (E34) : lus, réunis à ceux d'OSV par leurs identifiants,
jamais demandés pour un paquet privé ; une erreur n'efface pas les failles d'OSV."""

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import respx
from conftest import recorded_responses

from forceupdate import engine
from forceupdate.advisories import Advisory, OsvError, Vulnerabilities
from forceupdate.advisories.packagist import API_URL, PackagistAdvisories, parse_advisory, ranges
from forceupdate.models import Ecosystem, FindingKind, Report, Severity
from forceupdate.net import Cache, HttpClient
from forceupdate.sources.local import LocalSource

MakeTree = Callable[..., Path]

ITEM = {
    "advisoryId": "PKSA-yd6k-t2gh-1m43",
    "packageName": "twig/twig",
    "remoteId": "twig/twig/CVE-2026-46636.yaml",
    "title": "Twig: an escaping bypass",
    "link": "https://github.com/FriendsOfPHP/security-advisories/blob/master/twig/twig/x.yaml",
    "cve": "CVE-2026-46636",
    "affectedVersions": ">=1.0.0,<2.0.0|>=2.0.0,<3.0.0|>=3.0.0,<3.27.0",
    "reportedAt": "2026-06-01 10:00:00",
    "severity": None,
    "sources": [
        {"name": "FriendsOfPHP/security-advisories", "remoteId": "twig/twig/CVE-2026-46636.yaml"}
    ],
}


async def no_sleep(_: float) -> None:
    pass


def test_an_advisory_is_read() -> None:
    item = parse_advisory("twig/twig", ITEM)
    advisory = item.advisory
    assert advisory.id == "PKSA-yd6k-t2gh-1m43"
    assert advisory.aliases == ("CVE-2026-46636",)  # le remoteId de FriendsOfPHP est un fichier
    assert advisory.url == ITEM["link"]
    assert advisory.severity is None
    assert item.concerns("3.4.1")
    assert not item.concerns("3.27.0")
    assert advisory.fixed_in(Ecosystem.PACKAGIST, "twig/twig", "3.4.1") == "3.27.0"
    assert advisory.fixed_in(Ecosystem.PACKAGIST, "twig/twig", "1.5.0") == "3.27.0"


def test_github_identifiers_and_severity() -> None:
    item = {
        **ITEM,
        "remoteId": "GHSA-529h-vh3j-85hq",
        "severity": "high",
        "sources": [{"name": "GitHub", "remoteId": "GHSA-529h-vh3j-85hq"}],
    }
    advisory = parse_advisory("twig/twig", item).advisory
    assert advisory.aliases == ("CVE-2026-46636", "GHSA-529h-vh3j-85hq")
    assert advisory.severity is Severity.HIGH


def test_ranges() -> None:
    assert [r.events for r in ranges(">=1.0.0,<1.44.7|>=2.0.0,<2.16.0")] == [
        (("introduced", "1.0.0"), ("fixed", "1.44.7")),
        (("introduced", "2.0.0"), ("fixed", "2.16.0")),
    ]
    assert [r.events for r in ranges("<=3.26.0")] == [
        (("introduced", "0"), ("last_affected", "3.26.0"))
    ]
    assert [r.events for r in ranges("<1.20.0")] == [(("introduced", "0"), ("fixed", "1.20.0"))]
    assert [r.events for r in ranges("2.0.1")] == [
        (("introduced", "2.0.1"), ("last_affected", "2.0.1"))
    ]
    assert ranges("dev-master") == ()


def merge(found: dict, advisories: dict) -> tuple[dict, PackagistAdvisories, respx.Route]:  # type: ignore[type-arg]
    async def main() -> tuple[dict, PackagistAdvisories]:  # type: ignore[type-arg]
        async with HttpClient(sleep=no_sleep) as http:
            client = PackagistAdvisories(http, Cache.disabled())
            return await client.merge(found), client

    with respx.mock(assert_all_called=False) as router:
        route = router.get(url__startswith=API_URL).respond(200, json={"advisories": advisories})
        result, client = asyncio.run(main())
    return result, client, route


def osv_advisory(ids: tuple[str, ...]) -> Advisory:
    return Advisory(id=ids[0], aliases=ids[1:], summary="OSV")


def test_merged_with_osv_and_grouped_by_identifiers() -> None:
    now = datetime.now(UTC)
    query = (Ecosystem.PACKAGIST, "twig/twig", "3.4.1")
    found = {
        query: Vulnerabilities(advisories=(osv_advisory(("GHSA-x", "CVE-1")),), fetched_at=now)
    }
    same = {**ITEM, "advisoryId": "PKSA-1", "cve": "CVE-1"}
    result, _, route = merge(found, {"twig/twig": [same, ITEM]})
    advisories = result[query].advisories  # type: ignore[union-attr]
    assert [a.id for a in advisories] == ["GHSA-x", "PKSA-1", "PKSA-yd6k-t2gh-1m43"]
    assert route.call_count == 1
    # checks.vulns réunit PKSA-1 à GHSA-x par leur CVE : deux failles, pas trois.
    from forceupdate.checks import vulns
    from forceupdate.checks.base import Current
    from forceupdate.models import Dependency

    dependency = Dependency(
        ecosystem=Ecosystem.PACKAGIST,
        name="twig/twig",
        constraint="3.4.1",
        installed="3.4.1",
        file="composer.json",
    )
    current = Current(version="3.4.1")
    assert len(vulns.check(dependency, current, result[query])) == 2  # type: ignore[arg-type]


def test_an_osv_error_stays_an_error_and_other_ecosystems_are_untouched() -> None:
    error = OsvError("OSV : réseau.")
    php = (Ecosystem.PACKAGIST, "twig/twig", "3.4.1")
    npm = (Ecosystem.NPM, "twig/twig", "3.4.1")
    now = datetime.now(UTC)
    found = {php: error, npm: Vulnerabilities(advisories=(), fetched_at=now)}
    result, _, route = merge(found, {"twig/twig": [ITEM]})
    assert result[php] is error
    assert result[npm].advisories == ()  # type: ignore[union-attr]
    assert route.call_count == 0  # aucun paquet PHP à examiner


def test_an_empty_answer_is_an_array() -> None:
    query = (Ecosystem.PACKAGIST, "psr/log", "1.1.4")
    found = {query: Vulnerabilities(advisories=(), fetched_at=datetime.now(UTC))}
    result, client, _ = merge(found, [])  # type: ignore[arg-type]
    assert result[query].advisories == ()  # type: ignore[union-attr]
    assert client.error is None


def analyze(root: Path) -> Report:
    async def main() -> Report:
        async with HttpClient(sleep=no_sleep) as http:
            return await engine.analyze(LocalSource(root), http=http, cache=Cache.disabled())

    return asyncio.run(main())


LOCK = {
    "packages": [{"name": "twig/twig", "version": "v3.4.1"}],
    "packages-dev": [],
}


def test_a_failure_keeps_osv_and_says_so(make_tree: MakeTree) -> None:
    root = make_tree(
        {
            "composer.json": json.dumps({"require": {"twig/twig": "3.4.*"}}),
            "composer.lock": json.dumps(LOCK),
        }
    )

    def add(router: respx.MockRouter) -> None:
        # Un autre motif que la route enregistrée : respx remplacerait une route au même motif.
        router.get(url__regex=r"^https://packagist\.org/api/").respond(503)

    with recorded_responses(add):
        report = analyze(root)
    (project,) = report.projects
    found = [f for f in project.findings if f.kind is FindingKind.VULNERABLE]
    assert len(found) == 15  # celles d'OSV
    assert any(
        n.message.startswith("Failles de Packagist (GitHub, FriendsOfPHP) non lues : Packagist")
        for n in project.notices
    )


def test_a_private_package_is_never_sent(make_tree: MakeTree) -> None:
    satis = "https://satis.acme.example"
    composer = {
        "repositories": [{"type": "composer", "url": satis, "only": ["acme/*"]}],
        "require": {"acme/private": "^1.0", "twig/twig": "3.4.*"},
    }
    lock = {
        "packages": [
            {"name": "acme/private", "version": "1.0.0"},
            {"name": "twig/twig", "version": "v3.4.1"},
        ],
        "packages-dev": [],
    }
    root = make_tree({"composer.json": json.dumps(composer), "composer.lock": json.dumps(lock)})

    def add(router: respx.MockRouter) -> None:
        router.get(f"{satis}/packages.json").respond(200, json={"packages": []})

    with recorded_responses(add) as routes:
        analyze(root)
    asked = [
        name
        for call in routes["packagist:advisories"].calls
        for name in call.request.url.params.get_list("packages[]")
    ]
    assert "twig/twig" in asked
    assert "acme/private" not in asked
