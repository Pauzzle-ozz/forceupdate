"""Les modèles : emplacement d'une contrainte, tri, sortie JSON."""

import dataclasses
import json

import pytest

from forceupdate.models import (
    Dependency,
    Ecosystem,
    Finding,
    FindingKind,
    Gap,
    Language,
    Location,
    Project,
    Report,
    Scope,
    Severity,
    to_dict,
)

PACKAGE_JSON = '{\n  "dependencies": {\n    "express": "^4.18.0"\n  }\n}\n'


def make_report() -> Report:
    express = Dependency(
        ecosystem=Ecosystem.NPM,
        name="express",
        constraint="^4.18.0",
        installed="4.18.2",
        file="frontend/package.json",
        location=Location(line=3, column=16, end_column=23),
    )
    finding = Finding(
        kind=FindingKind.VULNERABLE,
        severity=Severity.HIGH,
        message="express 4.18.2 a une faille connue.",
        dependency=express,
        current_version="4.18.2",
        target_version="4.19.2",
        gap=Gap.MINOR,
        identifiers=("CVE-2024-29041", "GHSA-rv95-896h-c2vc"),
    )
    project = Project(
        path="frontend",
        ecosystems=[Ecosystem.NPM],
        manifests=["frontend/package.json"],
        lockfiles=["frontend/package-lock.json"],
        dependencies=[express],
        findings=[finding],
    )
    return Report(
        source="C:/code/app",
        languages=[Language(name="TypeScript", bytes=1200, ecosystem=Ecosystem.NPM)],
        projects=[project],
        ignored_manifests=["tests/fixtures/package.json"],
    )


def test_location_extracts_the_constraint() -> None:
    location = Location(line=3, column=16, end_column=23)
    assert location.extract(PACKAGE_JSON) == "^4.18.0"


def test_location_ignores_carriage_returns_before_the_constraint() -> None:
    location = Location(line=3, column=16, end_column=23)
    assert location.extract(PACKAGE_JSON.replace("\n", "\r\n")) == "^4.18.0"


def test_location_outside_the_text_gives_nothing() -> None:
    assert Location(line=99, column=0, end_column=3).extract(PACKAGE_JSON) == ""


@pytest.mark.parametrize(("line", "column", "end_column"), [(0, 0, 1), (1, -1, 2), (1, 5, 4)])
def test_location_rejects_invalid_positions(line: int, column: int, end_column: int) -> None:
    with pytest.raises(ValueError, match="emplacement invalide"):
        Location(line=line, column=column, end_column=end_column)


def test_ecosystem_values_are_osv_names() -> None:
    assert [e.value for e in Ecosystem] == [
        "PyPI",
        "npm",
        "crates.io",
        "Go",
        "Packagist",
        "RubyGems",
        "Maven",
        "NuGet",
    ]


def test_severity_rank_orders_from_most_to_least_severe() -> None:
    by_rank = sorted(Severity, key=lambda s: s.rank, reverse=True)
    assert by_rank == [
        Severity.CRITICAL,
        Severity.HIGH,
        Severity.MEDIUM,
        Severity.LOW,
        Severity.INFO,
    ]


def test_gap_rank_orders_patch_minor_major() -> None:
    assert Gap.PATCH.rank < Gap.MINOR.rank < Gap.MAJOR.rank


def test_dependency_defaults() -> None:
    dep = Dependency(ecosystem=Ecosystem.PYPI, name="flask", file="requirements.txt")
    assert dep.direct
    assert dep.scope is Scope.RUNTIME
    assert dep.verifiable


def test_dependency_with_reason_is_not_verifiable() -> None:
    dep = Dependency(
        ecosystem=Ecosystem.NPM,
        name="lib",
        constraint="file:../lib",
        file="package.json",
        unverifiable_reason="dépendance locale (file:)",
    )
    assert not dep.verifiable


def test_effective_constraint_is_the_catalog_range_when_there_is_one() -> None:
    plain = Dependency(ecosystem=Ecosystem.NPM, name="react", constraint="^18", file="package.json")
    assert plain.effective_constraint == "^18"
    catalog = dataclasses.replace(plain, constraint="catalog:", resolved_constraint="^18.2.0")
    assert catalog.effective_constraint == "^18.2.0"
    assert dataclasses.replace(catalog, resolved_constraint=None).effective_constraint == "catalog:"


def test_dependency_is_immutable() -> None:
    dep = Dependency(ecosystem=Ecosystem.PYPI, name="flask", file="requirements.txt")
    with pytest.raises(dataclasses.FrozenInstanceError):
        dep.name = "django"  # type: ignore[misc]


def test_report_lists_findings_of_all_projects() -> None:
    report = make_report()
    report.projects.append(Project(path="backend"))
    assert [f.kind for f in report.findings] == [FindingKind.VULNERABLE]


def test_report_to_dict_is_plain_json() -> None:
    data = to_dict(make_report())
    assert json.loads(json.dumps(data)) == data

    finding = data["projects"][0]["findings"][0]
    assert finding["kind"] == "vulnerable"
    assert finding["severity"] == "high"
    assert finding["gap"] == "minor"
    assert finding["identifiers"] == ["CVE-2024-29041", "GHSA-rv95-896h-c2vc"]
    assert finding["dependency"]["ecosystem"] == "npm"
    assert finding["dependency"]["scope"] == "runtime"
    assert finding["dependency"]["location"] == {"line": 3, "column": 16, "end_column": 23}
    assert type(finding["kind"]) is str
    assert data["languages"] == [{"name": "TypeScript", "bytes": 1200, "ecosystem": "npm"}]
    assert data["projects"][0]["ecosystems"] == ["npm"]
    assert data["ignored_manifests"] == ["tests/fixtures/package.json"]


def test_to_dict_rejects_non_models() -> None:
    with pytest.raises(TypeError):
        to_dict({"not": "a model"})
    with pytest.raises(TypeError):
        to_dict(Report)
