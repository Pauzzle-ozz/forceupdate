"""Les contrôles : version actuelle, « plus récente », « retirée / dépréciée », priorité."""

from datetime import UTC, datetime
from typing import Any

import pytest

from forceupdate import checks
from forceupdate.checks import FailOn, current_version, deprecated, outdated
from forceupdate.checks.base import nearest
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
from forceupdate.registries import PackageInfo, PackageVersion
from forceupdate.versions.npm import NPM
from forceupdate.versions.pypi import PYPI

PYPI_ECO, NPM_ECO = Ecosystem.PYPI, Ecosystem.NPM
WHEN = datetime(2026, 10, 27, tzinfo=UTC)


def dep(
    constraint: str = "",
    installed: str | None = None,
    *,
    ecosystem: Ecosystem = PYPI_ECO,
    name: str = "demo",
    **fields: Any,
) -> Dependency:
    return Dependency(
        ecosystem=ecosystem,
        name=name,
        constraint=constraint,
        installed=installed,
        file="requirements.txt" if ecosystem is PYPI_ECO else "package.json",
        **fields,
    )


def info(
    published: list[str] | dict[str, dict[str, Any]],
    latest: str | None,
    *,
    ecosystem: Ecosystem = PYPI_ECO,
    **fields: Any,
) -> PackageInfo:
    """Un ``PackageInfo`` : ``published`` donne les versions, ou, pour chacune, ses champs
    (``yanked``, ``deprecated``…)."""
    if isinstance(published, list):
        published = {version: {} for version in published}
    return PackageInfo(
        ecosystem=ecosystem,
        name="demo",
        versions=tuple(PackageVersion(version=v, **f) for v, f in published.items()),
        latest=latest,
        url="https://example.org/demo",
        fetched_at=WHEN,
        **fields,
    )


def run(dependency: Dependency, package: PackageInfo) -> list[Finding]:
    return checks.check_dependency(dependency, package)


# -- version actuelle ----------------------------------------------------------


@pytest.mark.parametrize(
    ("dependency", "version", "approximate"),
    [
        (dep(">=2.0", "2.3.1"), "2.3.1", False),
        (dep(">=2.0,<3"), "2.0", True),
        (dep("==2.0.1"), "2.0.1", False),
        (dep("^1.2", ecosystem=NPM_ECO), "1.2.0", True),
        (dep("1.2.3", ecosystem=NPM_ECO), "1.2.3", False),
        (dep("6.0.2"), "6.0.2", False),  # version nue de Poetry : exacte
        (dep("foo bar", "1.0"), "1.0", False),  # illisible : on se fie à l'installée
    ],
)
def test_current_version(dependency: Dependency, version: str, approximate: bool) -> None:
    current = current_version(dependency)
    assert (current.version, current.approximate) == (version, approximate)
    assert current.unknown is None


@pytest.mark.parametrize(
    ("dependency", "why"),
    [
        (dep(""), "aucune contrainte"),
        (dep("*"), "la contrainte « * » n'a pas de borne basse"),
        (dep("<2"), "la contrainte « <2 » n'a pas de borne basse"),
        (dep("latest", ecosystem=NPM_ECO), "l'étiquette « latest » suit le registre"),
        (dep("foo bar"), "la contrainte « foo bar » est illisible"),
        (dep("catalog:", ecosystem=NPM_ECO), "la plage de « catalog: » est introuvable"),
    ],
)
def test_without_current_version(dependency: Dependency, why: str) -> None:
    current = current_version(dependency)
    assert current.version is None
    assert current.unknown == f"{why}, et pas de version installée"


def test_the_range_of_a_pnpm_catalog_is_used() -> None:
    dependency = dep("catalog:", ecosystem=NPM_ECO, resolved_constraint="^7.0.0")
    current = current_version(dependency)
    assert (current.version, current.approximate, current.constraint) == ("7.0.0", True, "^7.0.0")


def test_an_unreadable_constraint_is_not_interpreted() -> None:
    assert current_version(dep("foo bar", "1.0")).constraint is None
    assert current_version(dep(">=1", "1.0")).constraint == ">=1"


# -- plus récente --------------------------------------------------------------

FLASK = ["1.1.4", "2.0.1", "2.0.3", "2.3.3", "3.0.0", "3.1.3"]


def test_a_newer_major() -> None:
    (finding,) = run(dep(">=2.0,<3", "2.0.1"), info(FLASK, "3.1.3"))
    assert finding.kind is FindingKind.OUTDATED
    assert finding.severity is Severity.LOW
    assert (finding.current_version, finding.current_is_approximate) == ("2.0.1", False)
    assert (finding.target_version, finding.gap) == ("3.1.3", Gap.MAJOR)
    assert finding.wanted_version == "2.3.3"
    assert finding.url == "https://example.org/demo"
    assert finding.message == (
        "Version 3.1.3 disponible (majeure) ; utilisée : 2.0.1. "
        "La contrainte accepte jusqu'à 2.3.3."
    )


def test_a_newer_patch_already_accepted() -> None:
    (finding,) = run(dep(">=3", "3.1.0"), info([*FLASK, "3.1.0"], "3.1.3"))
    assert (finding.gap, finding.severity, finding.wanted_version) == (
        Gap.PATCH,
        Severity.INFO,
        "3.1.3",
    )
    assert finding.message.endswith("La contrainte l'accepte déjà.")


def test_nothing_newer_within_the_constraint() -> None:
    (finding,) = run(dep("==2.0.1", "2.0.1"), info(FLASK, "3.1.3"))
    assert finding.wanted_version == "2.0.1"
    assert finding.message == "Version 3.1.3 disponible (majeure) ; utilisée : 2.0.1."


def test_up_to_date() -> None:
    assert run(dep(">=3", "3.1.3"), info(FLASK, "3.1.3")) == []


def test_ahead_of_latest_is_not_reported() -> None:
    """Quelqu'un sur la voie ``next`` de npm : au-dessus de ``latest``, rien à signaler."""
    package = info(["4.17.21", "5.0.0"], "4.17.21", ecosystem=NPM_ECO, tags={"latest": "4.17.21"})
    assert run(dep("^5.0.0", "5.0.0", ecosystem=NPM_ECO), package) == []


def test_an_approximate_current_version() -> None:
    (finding,) = run(dep(">=2.0"), info(FLASK, "3.1.3"))
    assert (finding.current_version, finding.current_is_approximate) == ("2.0", True)
    assert finding.gap is Gap.MAJOR
    assert "au moins 2.0 d'après la contrainte (pas de version installée)" in finding.message


def test_an_unknown_current_version_is_inconclusive() -> None:
    (finding,) = run(dep("*"), info(FLASK, "3.1.3"))
    assert finding.kind is FindingKind.INCONCLUSIVE
    assert (finding.current_version, finding.gap) == (None, None)
    assert (finding.target_version, finding.wanted_version) == ("3.1.3", "3.1.3")
    assert finding.message == (
        "Version utilisée inconnue : la contrainte « * » n'a pas de borne basse, et pas de "
        "version installée. Dernière : 3.1.3."
    )


def test_nothing_to_propose_without_a_latest_stable() -> None:
    assert run(dep(">=1", "1.0.0"), info(["1.0.0", "2.0.0rc1"], None)) == []


def test_an_unreadable_installed_version_is_inconclusive() -> None:
    (finding,) = outdated.check(
        dep(">=1", "not-a-version"), info(FLASK, "3.1.3"), current_version(dep(">=1", "x!"))
    )
    assert finding.kind is FindingKind.INCONCLUSIVE
    assert "illisible selon les règles de PyPI" in finding.message


def test_an_unreadable_constraint_trusts_the_installed_version() -> None:
    (finding,) = run(dep("foo bar", "2.0.1"), info(FLASK, "3.1.3"))
    assert (finding.kind, finding.gap, finding.wanted_version) == (
        FindingKind.OUTDATED,
        Gap.MAJOR,
        None,
    )


def test_an_indirect_dependency_has_no_wanted_version() -> None:
    dependency = dep("==2.0.1", "2.0.1", direct=False)
    (finding,) = run(dependency, info(FLASK, "3.1.3"))
    assert finding.wanted_version is None


def test_a_prerelease_moves_to_a_newer_prerelease_of_the_same_version() -> None:
    package = info(["1.9.0", "2.0.0rc1", "2.0.0rc2", "2.1.0b1"], "1.9.0")
    (finding,) = run(dep(">=2.0.0rc1", "2.0.0rc1"), package)
    assert finding.target_version == "2.0.0rc2"
    assert finding.wanted_version == "2.0.0rc2"


def test_a_prerelease_moves_to_its_final_version() -> None:
    (finding,) = run(dep(">=2.0.0rc1", "2.0.0rc1"), info(["2.0.0rc1", "2.0.0", "2.0.1"], "2.0.1"))
    assert (finding.target_version, finding.gap) == ("2.0.1", Gap.MAJOR)


def test_a_deprecated_latest_is_not_proposed() -> None:
    """``@types/parse-json`` 7.0.0 est un paquet vide déprécié : comme ``npm outdated``, on
    ne le propose pas à qui a la 4.0.2 ; le paquet déprécié est signalé à part."""
    stub = "This is a stub types definition."
    package = info(
        {"3.0.0": {}, "4.0.2": {}, "7.0.0": {"deprecated": stub}},
        "7.0.0",
        ecosystem=NPM_ECO,
        tags={"latest": "7.0.0"},
        deprecated=stub,
    )
    assert [f.kind for f in run(dep("^4.0.0", "4.0.2", ecosystem=NPM_ECO), package)] == [
        FindingKind.DEPRECATED
    ]
    (_, older) = run(dep("^3.0.0", "3.0.0", ecosystem=NPM_ECO), package)
    assert (older.kind, older.target_version) == (FindingKind.OUTDATED, "4.0.2")


def test_a_deprecated_latest_without_alternative_is_proposed() -> None:
    package = info(
        {"1.2.0": {"deprecated": "x"}, "1.3.0": {"deprecated": "x"}},
        "1.3.0",
        ecosystem=NPM_ECO,
        tags={"latest": "1.3.0"},
        deprecated="x",
    )
    (_, finding) = run(dep("^1.2.0", "1.2.0", ecosystem=NPM_ECO), package)
    assert finding.target_version == "1.3.0"


def test_a_package_released_as_prereleases() -> None:
    """chromium-bidi publie ses versions en pré-versions, sous ``latest``."""
    package = info(
        ["17.0.2", "157.0.8090-0", "158.0.8127-2"],
        "17.0.2",
        ecosystem=NPM_ECO,
        tags={"latest": "158.0.8127-2"},
    )
    (finding,) = run(dep("157.0.8090-0", "157.0.8090-0", ecosystem=NPM_ECO), package)
    assert (finding.target_version, finding.gap) == ("158.0.8127-2", Gap.MAJOR)
    assert run(dep("^17.0.0", "17.0.2", ecosystem=NPM_ECO), package) == []


def test_pypi_wanted_skips_yanked_versions() -> None:
    package = info({"2.0.0": {}, "2.1.0": {}, "2.2.0": {"yanked": True}}, "2.1.0")
    (finding,) = run(dep(">=2.0,<3", "2.0.0"), package)
    assert (finding.wanted_version, finding.target_version) == ("2.1.0", "2.1.0")


# npm : le choix de npm-pick-manifest


def test_npm_wanted_prefers_the_latest_tag() -> None:
    """``>=4`` accepte une 5.0.0 publiée sous ``next`` ; npm choisit ``latest``."""
    package = info(
        ["4.17.20", "4.17.21", "5.0.0"],
        "4.17.21",
        ecosystem=NPM_ECO,
        tags={"latest": "4.17.21", "next": "5.0.0"},
    )
    (finding,) = run(dep(">=4", "4.17.20", ecosystem=NPM_ECO), package)
    assert (finding.wanted_version, finding.target_version) == ("4.17.21", "4.17.21")


def test_npm_wanted_avoids_deprecated_versions() -> None:
    package = info(
        {"1.0.0": {}, "1.1.0": {}, "1.2.0": {"deprecated": "Bad release"}, "2.0.0": {}},
        "2.0.0",
        ecosystem=NPM_ECO,
        tags={"latest": "2.0.0"},
    )
    (finding,) = run(dep("^1.0.0", "1.0.0", ecosystem=NPM_ECO), package)
    assert finding.wanted_version == "1.1.0"


def test_npm_wanted_skips_a_deprecated_latest() -> None:
    package = info(
        {"1.0.0": {}, "1.1.0": {"deprecated": "oops"}},
        "1.1.0",
        ecosystem=NPM_ECO,
        tags={"latest": "1.1.0"},
    )
    dependency = dep("^1.0.0", "1.0.0", ecosystem=NPM_ECO)
    assert outdated.wanted_version(dependency, package, current_version(dependency)) == "1.0.0"
    assert run(dependency, package) == []  # et la latest dépréciée n'est pas proposée


def test_npm_wanted_falls_back_to_deprecated_versions() -> None:
    """Toutes les versions de la plage sont dépréciées : npm prend quand même la plus haute."""
    package = info(
        {"1.0.0": {"deprecated": "x"}, "1.1.0": {"deprecated": "x"}, "2.0.0": {}},
        "2.0.0",
        ecosystem=NPM_ECO,
        tags={"latest": "2.0.0"},
    )
    (outdated_finding,) = outdated.check(
        dep("^1.0.0", "1.0.0", ecosystem=NPM_ECO),
        package,
        current_version(dep("^1.0.0", "1.0.0", ecosystem=NPM_ECO)),
    )
    assert outdated_finding.wanted_version == "1.1.0"


def test_npm_a_tag_resolves_through_dist_tags() -> None:
    package = info(
        ["1.0.0", "1.1.0", "2.0.0-rc.1"],
        "1.1.0",
        ecosystem=NPM_ECO,
        tags={"latest": "1.1.0", "next": "2.0.0-rc.1"},
    )
    (finding,) = run(dep("latest", "1.0.0", ecosystem=NPM_ECO), package)
    assert (finding.wanted_version, finding.target_version) == ("1.1.0", "1.1.0")
    assert run(dep("next", "2.0.0-rc.1", ecosystem=NPM_ECO), package) == []


# -- retirée, dépréciée --------------------------------------------------------


def test_a_deprecated_package() -> None:
    package = info(["1.0.0"], "1.0.0", deprecated="projet archivé sur PyPI")
    (finding,) = run(dep(">=1", "1.0.0"), package)
    assert finding.kind is FindingKind.DEPRECATED
    assert finding.severity is Severity.LOW
    assert finding.message == "Paquet déprécié : projet archivé sur PyPI"
    assert finding.detail == "projet archivé sur PyPI"
    assert finding.target_version is None


def test_a_yanked_version_is_replaced_by_the_nearest() -> None:
    reason = "Yanked due to conflicts with CVE-2024-35195 mitigation"
    package = info(
        {
            "2.31.0": {},
            "2.32.0": {"yanked": True, "yanked_reason": reason},
            "2.32.1": {"yanked": True, "yanked_reason": reason},
            "2.32.2": {},
            "2.34.2": {},
        },
        "2.34.2",
    )
    findings = run(dep("==2.32.0"), package)
    assert [f.kind for f in findings] == [FindingKind.YANKED, FindingKind.OUTDATED]
    yanked = findings[0]
    assert yanked.severity is Severity.MEDIUM
    assert (yanked.target_version, yanked.gap, yanked.detail) == ("2.32.2", Gap.PATCH, reason)
    assert yanked.message == (
        f"Version 2.32.0 retirée de PyPI : {reason}. La plus proche non retirée : 2.32.2."
    )


def test_a_yanked_version_without_replacement() -> None:
    package = info({"1.0": {"yanked": True}}, None)
    (finding,) = run(dep(">=1", "1.0"), package)
    assert finding.kind is FindingKind.YANKED
    assert finding.target_version is None
    assert finding.message == (
        "Version 1.0 retirée de PyPI. Aucune version non retirée à proposer."
    )


def test_a_yanked_lower_bound_is_not_reported() -> None:
    """``>=2.32.0`` sans lockfile ne dit pas qu'on utilise 2.32.0."""
    package = info({"2.32.0": {"yanked": True}, "2.32.2": {}}, "2.32.2")
    assert [f.kind for f in run(dep(">=2.32.0"), package)] == [FindingKind.OUTDATED]


def test_a_deprecated_npm_version() -> None:
    package = info(
        {"4.17.21": {}, "4.18.0": {"deprecated": "Bad release"}, "4.18.1": {}},
        "4.18.1",
        ecosystem=NPM_ECO,
        tags={"latest": "4.18.1"},
    )
    findings = run(dep("^4.17.0", "4.18.0", ecosystem=NPM_ECO), package)
    assert [f.kind for f in findings] == [FindingKind.DEPRECATED, FindingKind.OUTDATED]
    assert findings[0].message == (
        "Version 4.18.0 dépréciée : Bad release. La plus proche non dépréciée : 4.18.1."
    )
    assert (findings[0].target_version, findings[0].detail) == ("4.18.1", "Bad release")


def test_a_registry_message_ending_with_a_period() -> None:
    package = info(
        {"4.18.0": {"deprecated": "Bad release. Please use lodash@4.17.21 instead."}, "4.18.1": {}},
        "4.18.1",
        ecosystem=NPM_ECO,
        tags={"latest": "4.18.1"},
    )
    (finding, _) = run(dep("4.18.0", "4.18.0", ecosystem=NPM_ECO), package)
    assert finding.message == (
        "Version 4.18.0 dépréciée : Bad release. Please use lodash@4.17.21 instead. "
        "La plus proche non dépréciée : 4.18.1."
    )


def test_a_deprecated_package_hides_its_deprecated_versions() -> None:
    package = info(
        {"1.3.0": {"deprecated": "use String.prototype.padStart()"}},
        "1.3.0",
        ecosystem=NPM_ECO,
        tags={"latest": "1.3.0"},
        deprecated="use String.prototype.padStart()",
    )
    findings = run(dep("^1.3.0", "1.3.0", ecosystem=NPM_ECO), package)
    assert [f.kind for f in findings] == [FindingKind.DEPRECATED]
    assert findings[0].target_version is None


def test_an_installed_version_unknown_to_the_registry() -> None:
    """colors 1.4.1, la version sabotée de 2022, a été dépubliée."""
    package = info(["1.3.3", "1.4.0"], "1.4.0", ecosystem=NPM_ECO, tags={"latest": "1.4.0"})
    findings = run(dep("^1.4.0", "1.4.1", ecosystem=NPM_ECO), package)
    assert [f.kind for f in findings] == [FindingKind.INCONCLUSIVE]
    assert findings[0].message == (
        "Version 1.4.1 inconnue de npm : dépubliée, ou venue d'un autre index. Impossible de "
        "dire si elle est retirée."
    )


def test_a_version_found_by_value() -> None:
    """PyPI : la version installée ``1.8rc1`` est la publiée ``1.8c1``."""
    package = info({"1.8c1": {"yanked": True}, "1.8": {}}, "1.8")
    findings = run(dep(">=1.8c1", "1.8rc1"), package)
    assert findings[0].kind is FindingKind.YANKED


# -- la plus proche ------------------------------------------------------------


@pytest.mark.parametrize(
    ("current", "choices", "expected"),
    [
        ("2.32.0", ["2.31.0", "2.32.2", "2.34.2"], "2.32.2"),
        ("1.9.9", ["1.9.8", "2.0.0"], "1.9.8"),  # pas de majeure si on peut l'éviter
        ("1.9.9", ["2.0.0", "3.0.0"], "2.0.0"),
        ("1.0.0", ["1.0.0"], None),
        ("1.0.0", ["1.1.0rc1", "0.9.0"], "0.9.0"),  # pas de pré-version
        ("1.0", [], None),
    ],
)
def test_nearest(current: str, choices: list[str], expected: str | None) -> None:
    assert nearest(PYPI, current, choices) == expected


def test_nearest_npm_major_zero() -> None:
    """En 0.x, ``0.3.0`` est une majeure depuis ``0.2.3`` : on préfère redescendre."""
    assert nearest(NPM, "0.2.3", ["0.2.1", "0.3.0"]) == "0.2.1"


# -- priorité et seuil ---------------------------------------------------------


def finding(kind: FindingKind, **fields: Any) -> Finding:
    return Finding(kind=kind, message="", dependency=dep(name=fields.pop("name", "x")), **fields)


ORDERED = [
    finding(FindingKind.VULNERABLE, severity=Severity.CRITICAL),
    finding(FindingKind.VULNERABLE, severity=Severity.LOW),
    finding(FindingKind.EOL, severity=Severity.HIGH),
    finding(FindingKind.YANKED),
    finding(FindingKind.DEPRECATED),
    finding(FindingKind.OUTDATED, gap=Gap.MAJOR),
    finding(FindingKind.OUTDATED, gap=Gap.MINOR),
    finding(FindingKind.OUTDATED, gap=Gap.PATCH),
    finding(FindingKind.UNVERIFIABLE),
    finding(FindingKind.INCONCLUSIVE),
]


def test_findings_are_sorted_by_priority() -> None:
    assert checks.sort_findings(reversed(ORDERED)) == ORDERED


def test_equal_findings_are_sorted_by_name() -> None:
    b, a = finding(FindingKind.YANKED, name="b"), finding(FindingKind.YANKED, name="a")
    assert checks.sort_findings([b, a]) == [a, b]


@pytest.mark.parametrize(
    ("threshold", "reached"),
    [
        (FailOn.VULN, 2),
        (FailOn.MAJOR, 6),  # failles, fin de vie, retirée, dépréciée, majeure
        (FailOn.ANY, 8),  # tout sauf non vérifiable et non concluant
    ],
)
def test_fail_on(threshold: FailOn, reached: int) -> None:
    assert [checks.reaches(f, threshold) for f in ORDERED] == [True] * reached + [False] * (
        len(ORDERED) - reached
    )
    assert checks.fails(ORDERED, threshold)
    assert not checks.fails(ORDERED[reached:], threshold)


@pytest.mark.parametrize(
    ("options", "checked"),
    [
        (ScanOptions(), {"runtime", "dev"}),
        (ScanOptions(dev=False), {"runtime"}),
        (ScanOptions(transitive=True), {"runtime", "dev", "indirect", "indirect-dev"}),
        (ScanOptions(transitive=True, dev=False), {"runtime", "indirect"}),
    ],
)
def test_selected(options: ScanOptions, checked: set[str]) -> None:
    dependencies = {
        "runtime": dep(),
        "dev": dep(scope=Scope.DEV),
        "indirect": dep(direct=False),
        "indirect-dev": dep(direct=False, scope=Scope.DEV),
    }
    assert {key for key, d in dependencies.items() if checks.selected(d, options)} == checked


def test_deprecated_check_alone_ignores_unknown_current() -> None:
    """Sans version actuelle, rien à dire de la version : seulement du paquet."""
    package = info(["1.0"], "1.0", deprecated="abandonné")
    findings = deprecated.check(dep("*"), package, current_version(dep("*")))
    assert [f.kind for f in findings] == [FindingKind.DEPRECATED]
