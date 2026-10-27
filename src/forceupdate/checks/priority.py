"""L'ordre des constats, et le seuil qui fait échouer ``scan --fail-on``.

L'ordre est celui du brief (décision n°8) : faille (par sévérité) > fin de vie > retiré >
déprécié > majeure > mineure > correctif. Viennent ensuite ce qui n'a pas pu être vérifié
(non vérifiable), puis ce qui n'a rien conclu (non concluant).

**Gravité des constats autres que les failles (tranché à E07)**. Une faille a celle de son
avis (CVSS, E08). Pour les autres, elle sert à l'affichage ; l'ordre, lui, suit le type :

- version retirée : ``MEDIUM`` (ses mainteneurs l'ont retirée, souvent parce qu'elle casse
  ou qu'elle est dangereuse) ;
- paquet ou version déprécié : ``LOW`` ;
- version plus récente : ``LOW`` pour une majeure, ``INFO`` pour une mineure ou un correctif ;
- non vérifiable, non concluant : ``INFO``.

Un paquet malveillant retiré par npm (crossenv) est aussi une faille critique : OSV le connaît
(``checks.vulns``).
"""

import enum
from collections.abc import Iterable

from forceupdate.models import Finding, FindingKind, Gap

_KIND_ORDER = {
    FindingKind.VULNERABLE: 0,
    FindingKind.EOL: 1,
    FindingKind.YANKED: 2,
    FindingKind.DEPRECATED: 3,
    FindingKind.OUTDATED: 4,
    FindingKind.UNVERIFIABLE: 5,
    FindingKind.INCONCLUSIVE: 6,
}


def priority(finding: Finding) -> tuple[int, int]:
    """La clé de tri d'un constat : la plus petite pour le plus grave."""
    rank = _KIND_ORDER[finding.kind]
    if finding.kind in (FindingKind.VULNERABLE, FindingKind.EOL):
        return rank, -finding.severity.rank
    if finding.kind is FindingKind.OUTDATED and finding.gap is not None:
        return rank, -finding.gap.rank
    return rank, 0


def sort_findings(findings: Iterable[Finding]) -> list[Finding]:
    """Les constats du plus grave au moins grave ; à gravité égale, par nom de paquet."""
    return sorted(findings, key=_sort_key)


def _sort_key(finding: Finding) -> tuple[tuple[int, int], str]:
    name = finding.dependency.name if finding.dependency is not None else ""
    return priority(finding), name


class FailOn(enum.StrEnum):
    """Le seuil de ``scan --fail-on`` : à partir de quel constat l'analyse échoue (code 1)."""

    VULN = "vuln"
    """Une faille."""
    MAJOR = "major"
    """Une faille, une fin de vie, une version retirée, un paquet ou une version déprécié, une
    version majeure plus récente : tout ce qui précède les mineures dans l'ordre du brief."""
    ANY = "any"
    """Tout ce qui est à mettre à jour, mineures et correctifs compris. Ce qui n'a pas pu être
    vérifié ou n'a rien conclu ne compte jamais."""


def reaches(finding: Finding, threshold: FailOn) -> bool:
    """Vrai si ``finding`` atteint le seuil ``threshold``."""
    if threshold is FailOn.VULN:
        return finding.kind is FindingKind.VULNERABLE
    if finding.kind in (FindingKind.UNVERIFIABLE, FindingKind.INCONCLUSIVE):
        return False
    if threshold is FailOn.ANY:
        return True
    return priority(finding) <= (_KIND_ORDER[FindingKind.OUTDATED], -Gap.MAJOR.rank)


def fails(findings: Iterable[Finding], threshold: FailOn) -> bool:
    """Vrai si un des constats atteint le seuil."""
    return any(reaches(finding, threshold) for finding in findings)
