"""La synthèse de plusieurs analyses (``report.synthesis``) : le verdict d'un dépôt, et les
constats additionnés."""

import pytest

from forceupdate.models import FindingKind, Severity
from forceupdate.report import Summary
from forceupdate.report.synthesis import Verdict, combine, verdict


def summary(
    *,
    projects: int = 1,
    findings: dict[FindingKind, int] | None = None,
    vulnerabilities: dict[Severity, int] | None = None,
) -> Summary:
    counts = dict.fromkeys(FindingKind, 0) | (findings or {})
    severities = dict.fromkeys(Severity, 0)
    for kind, count in counts.items():
        if kind not in (FindingKind.UNVERIFIABLE, FindingKind.INCONCLUSIVE):
            severities[Severity.LOW] += count
    return Summary(
        projects=projects,
        direct=3,
        transitive=0,
        checked=3,
        findings=counts,
        severities=severities,
        vulnerabilities=dict.fromkeys(Severity, 0) | (vulnerabilities or {}),
    )


@pytest.mark.parametrize(
    ("given", "partial", "expected"),
    [
        (summary(findings={FindingKind.OUTDATED: 2}), False, Verdict.TO_UPDATE),
        # Quelque chose à mettre à jour reste à mettre à jour, même si tout n'a pas répondu.
        (
            summary(findings={FindingKind.OUTDATED: 1, FindingKind.INCONCLUSIVE: 3}),
            True,
            Verdict.TO_UPDATE,
        ),
        (summary(), False, Verdict.UP_TO_DATE),
        # Une dépendance git ne se vérifie pas : ce n'est pas une mise à jour à faire.
        (summary(findings={FindingKind.UNVERIFIABLE: 1}), False, Verdict.UP_TO_DATE),
        # Jamais « à jour » sans avoir tout vérifié.
        (summary(findings={FindingKind.INCONCLUSIVE: 1}), False, Verdict.INCONCLUSIVE),
        (summary(), True, Verdict.INCONCLUSIVE),
        (summary(projects=0), True, Verdict.INCONCLUSIVE),
        (summary(projects=0), False, Verdict.NO_DEPENDENCIES),
    ],
)
def test_verdict(given: Summary, partial: bool, expected: Verdict) -> None:
    assert verdict(given, partial=partial) is expected


def test_combine_adds_the_findings_of_every_report() -> None:
    combined = combine(
        [
            summary(
                findings={FindingKind.VULNERABLE: 2, FindingKind.OUTDATED: 1},
                vulnerabilities={Severity.CRITICAL: 1, Severity.HIGH: 1},
            ),
            summary(findings={FindingKind.OUTDATED: 4, FindingKind.INCONCLUSIVE: 2}),
            summary(findings={FindingKind.VULNERABLE: 1}, vulnerabilities={Severity.MEDIUM: 1}),
        ]
    )
    assert combined.reports == 3
    assert combined.findings[FindingKind.VULNERABLE] == 3
    assert combined.findings[FindingKind.OUTDATED] == 5
    assert combined.findings[FindingKind.INCONCLUSIVE] == 2
    assert set(combined.findings) == set(FindingKind)
    assert combined.vulnerabilities == {
        Severity.CRITICAL: 1,
        Severity.HIGH: 1,
        Severity.MEDIUM: 1,
        Severity.LOW: 0,
        Severity.INFO: 0,
    }
    assert combined.vulnerable_reports == 2
    assert combined.to_update == 8


def test_combine_nothing() -> None:
    combined = combine([])
    assert combined.reports == 0
    assert combined.to_update == 0
    assert not any(combined.findings.values())
