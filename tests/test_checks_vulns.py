"""Les constats « faille » (``checks.vulns``), tirés des avis d'OSV enregistrés dans
``tests/fixtures/osv`` : une faille par constat, sa gravité, sa version corrigée, les paquets
malveillants, la version approximative, et ce qui n'a pas pu être vérifié."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from forceupdate.advisories import Advisory, OsvError, Vulnerabilities, parse_vuln
from forceupdate.checks import current_version, vulns
from forceupdate.models import (
    Dependency,
    Ecosystem,
    Finding,
    FindingKind,
    Gap,
    ScanOptions,
    Scope,
    Severity,
)

FIXTURES = Path(__file__).parent / "fixtures" / "osv" / "vulns"
NOW = datetime(2026, 10, 27, tzinfo=UTC)


def advisory(vuln_id: str) -> Advisory:
    found = parse_vuln(json.loads((FIXTURES / f"{vuln_id}.json").read_bytes()))
    assert found is not None
    return found


def dependency(
    name: str,
    constraint: str,
    installed: str | None = None,
    *,
    ecosystem: Ecosystem = Ecosystem.NPM,
    direct: bool = True,
    scope: Scope = Scope.RUNTIME,
    unverifiable_reason: str | None = None,
) -> Dependency:
    return Dependency(
        ecosystem=ecosystem,
        name=name,
        constraint=constraint,
        installed=installed,
        direct=direct,
        scope=scope,
        file="package.json" if ecosystem is Ecosystem.NPM else "requirements.txt",
        unverifiable_reason=unverifiable_reason,
    )


def check(dep: Dependency, *found: Advisory) -> list[Finding]:
    return vulns.check(dep, current_version(dep), Vulnerabilities(advisories=found, fetched_at=NOW))


FLASK = dependency("flask", "==0.12", ecosystem=Ecosystem.PYPI)
FLASK_ADVISORIES = [
    "GHSA-562c-5r94-xh97",
    "GHSA-5wv5-4vpf-pj6m",
    "GHSA-68rp-wp8r-4726",
    "GHSA-m2qf-hxjv-5gpq",
    "PYSEC-2018-66",
    "PYSEC-2019-179",
    "PYSEC-2023-62",
    "PYSEC-2026-2151",
]


def test_flask_0_12() -> None:
    """Les 8 avis d'OSV sont 4 failles, chacune chez GitHub et chez PyPI."""
    findings = check(FLASK, *map(advisory, FLASK_ADVISORIES))
    assert [(f.identifiers[0], f.target_version, f.severity) for f in findings] == [
        ("CVE-2018-1000656", "0.12.3", Severity.HIGH),
        ("CVE-2019-1010083", "1.0", Severity.HIGH),
        ("CVE-2023-30861", "2.2.5", Severity.HIGH),
        ("CVE-2026-27205", "3.1.3", Severity.MEDIUM),
    ]
    first = findings[0]
    assert first.kind is FindingKind.VULNERABLE
    assert first.identifiers == ("CVE-2018-1000656", "GHSA-562c-5r94-xh97", "PYSEC-2018-66")
    assert first.message == (
        "CVE-2018-1000656, GHSA-562c-5r94-xh97 (gravité élevée, CVSS 7,5) : Flask is vulnerable "
        "to Denial of Service via incorrect encoding of JSON data. Corrigée en 0.12.3."
    )
    assert (first.current_version, first.current_is_approximate) == ("0.12", False)
    assert (first.gap, first.cvss_score) == (Gap.PATCH, 7.5)
    assert (
        first.detail
        == "Flask is vulnerable to Denial of Service via incorrect encoding of JSON data"
    )
    assert first.url == "https://osv.dev/vulnerability/GHSA-562c-5r94-xh97"
    assert first.dependency == FLASK
    assert findings[2].gap is Gap.MAJOR


def test_the_worst_severity_of_merged_advisories() -> None:
    """GitHub dit faible (CVSS 4), PyPI moyenne (CVSS 3 à 4,3) : on garde la plus grave."""
    (finding,) = check(FLASK, advisory("GHSA-68rp-wp8r-4726"), advisory("PYSEC-2026-2151"))
    assert (finding.severity, finding.cvss_score) == (Severity.MEDIUM, 4.3)
    assert finding.identifiers == ("CVE-2026-27205", "GHSA-68rp-wp8r-4726", "PYSEC-2026-2151")


def test_lodash_4_17_15() -> None:
    lodash = dependency("lodash", "4.17.15", "4.17.15")
    found = [
        "GHSA-29mw-wpgm-hmr9",
        "GHSA-35jh-r3h4-6jhm",
        "GHSA-f23m-r3pf-42rh",
        "GHSA-p6mc-m468-83gw",
        "GHSA-r5fr-rjxr-66jc",
        "GHSA-xxjr-mmjv-4gpg",
    ]
    findings = check(lodash, *map(advisory, found))
    assert [(f.identifiers[0], f.target_version, f.severity) for f in findings] == [
        ("CVE-2026-4800", "4.18.0", Severity.HIGH),
        ("CVE-2020-8203", "4.17.19", Severity.HIGH),
        ("CVE-2021-23337", "4.17.21", Severity.HIGH),
        ("CVE-2025-13465", "4.17.23", Severity.MEDIUM),
        ("CVE-2026-2950", "4.18.0", Severity.MEDIUM),
        ("CVE-2020-28500", "4.17.21", Severity.MEDIUM),
    ]
    # À gravité égale, le plus haut score d'abord.
    assert [f.cvss_score for f in findings] == [8.1, 7.4, 7.2, 6.5, 6.5, 5.3]


def test_a_malicious_package_is_critical() -> None:
    crossenv = dependency("crossenv", "1.0.0", "1.0.0")
    (finding,) = check(crossenv, advisory("GHSA-c2m4-w5hm-vqjw"))
    assert finding.severity is Severity.CRITICAL  # GitHub dit élevée (CVSS 7,5)
    assert finding.target_version is None
    assert finding.message == (
        "Code malveillant (CVE-2017-16074, GHSA-c2m4-w5hm-vqjw) : crossenv is malware. Retirer "
        "ce paquet : aucune version sûre connue."
    )


def test_the_advisories_of_a_malicious_package_are_merged() -> None:
    """flatmap-stream : deux avis GitHub et un MAL, qui ne se citent pas, disent la même chose."""
    flatmap = dependency("flatmap-stream", "0.1.1", "0.1.1")
    found = ["GHSA-9x64-5r7x-2q53", "GHSA-mh6f-8j2x-4483", "MAL-2025-20690"]
    (finding,) = check(flatmap, *map(advisory, found))
    assert finding.identifiers == ("GHSA-9x64-5r7x-2q53", "GHSA-mh6f-8j2x-4483", "MAL-2025-20690")
    assert finding.severity is Severity.CRITICAL
    assert finding.message.startswith(
        "Code malveillant (GHSA-9x64-5r7x-2q53, GHSA-mh6f-8j2x-4483) : Malicious Package in "
        "flatmap-stream."
    )


def test_a_trapped_version_with_a_fix() -> None:
    ua = dependency("ua-parser-js", "0.7.29", "0.7.29")
    (finding,) = check(ua, advisory("GHSA-pjwm-rvh2-c87w"))
    assert (finding.severity, finding.target_version) == (Severity.CRITICAL, "0.7.30")
    assert finding.message.endswith("Embedded malware in ua-parser-js. Corrigée en 0.7.30.")


def test_withdrawn_advisories_are_not_vulnerabilities() -> None:
    withdrawn = parse_vuln({"id": "GHSA-0", "withdrawn": "2024-01-01T00:00:00Z"})
    assert withdrawn is not None
    assert check(FLASK, withdrawn) == []
    assert check(FLASK) == []


def test_unknown_severity_and_no_fix() -> None:
    bare = parse_vuln({"id": "PYSEC-0", "summary": "Something bad."})
    assert bare is not None
    (finding,) = check(FLASK, bare)
    assert finding.severity is Severity.MEDIUM
    assert finding.cvss_score is None
    assert finding.message == (
        "PYSEC-0 (gravité inconnue) : Something bad. Aucune version corrigée connue."
    )


def test_an_advisory_that_could_not_be_read() -> None:
    unread = Advisory(id="GHSA-1", unavailable="api.osv.dev injoignable (ConnectError)")
    (finding,) = check(FLASK, unread)
    assert finding.kind is FindingKind.VULNERABLE
    assert finding.severity is Severity.MEDIUM
    assert finding.target_version is None
    assert finding.message == (
        "GHSA-1 : détail de l'avis indisponible (api.osv.dev injoignable (ConnectError)) ; "
        "gravité et version corrigée inconnues."
    )


def test_a_lower_bound_gives_a_possible_vulnerability() -> None:
    """Sans lockfile, ``>=0.12`` donne 0.12 : la version installée peut être plus récente."""
    flask = dependency("flask", ">=0.12", ecosystem=Ecosystem.PYPI)
    finding = check(flask, advisory("GHSA-562c-5r94-xh97"))[0]
    assert (finding.current_version, finding.current_is_approximate) == ("0.12", True)
    assert finding.message.endswith(
        "Corrigée en 0.12.3. Faille possible : 0.12 est la borne basse de « >=0.12 », faute de "
        "lockfile ; la version installée peut être plus récente."
    )


def test_unchecked() -> None:
    error = OsvError("OSV : api.osv.dev injoignable (ConnectError).")
    finding = vulns.unchecked(FLASK, current_version(FLASK), error)
    assert finding.kind is FindingKind.INCONCLUSIVE
    assert finding.severity is Severity.INFO
    assert finding.message == (
        "Failles non vérifiées. OSV : api.osv.dev injoignable (ConnectError)."
    )
    assert finding.current_version == "0.12"


@pytest.mark.parametrize(
    ("dep", "options", "expected"),
    [
        (dependency("a", "1.0.0", "1.0.0"), ScanOptions(), True),
        # Les indirectes, quelle que soit --transitive.
        (dependency("a", "", "1.0.0", direct=False), ScanOptions(), True),
        (dependency("a", "1.0.0", "1.0.0", scope=Scope.DEV), ScanOptions(dev=False), False),
        (
            dependency("a", "", "1.0.0", direct=False, scope=Scope.DEV),
            ScanOptions(dev=False),
            False,
        ),
        (dependency("a", "1.0.0", "1.0.0", scope=Scope.DEV), ScanOptions(), True),
        (
            dependency("a", "git+https://x", unverifiable_reason="dépendance git"),
            ScanOptions(),
            False,
        ),
    ],
)
def test_audited(dep: Dependency, options: ScanOptions, expected: bool) -> None:
    assert vulns.audited(dep, options) is expected


def test_version_to_check() -> None:
    def version(dep: Dependency) -> str | None:
        current = vulns.version_to_check(dep)
        return None if current is None else current.version

    assert version(dependency("a", "^1.2.0", "1.4.0")) == "1.4.0"
    assert version(dependency("a", "^1.2.0")) == "1.2.0"
    assert version(dependency("a", "*")) is None  # rien à demander à OSV
    assert version(dependency("a", "latest")) is None
    assert version(dependency("a", "1.0", "1.0", ecosystem=Ecosystem.CRATES_IO)) is None
