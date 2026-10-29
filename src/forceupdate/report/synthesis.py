"""La synthèse de plusieurs analyses : les dépôts d'un compte (écran 7, E17).

- ``verdict`` : ce que dit le rapport d'un dépôt, en un mot (à mettre à jour, à jour, non
  concluant, sans dépendances) ;
- ``combine`` : les constats de plusieurs rapports, additionnés par type et par gravité.

Les règles sont celles du rapport d'un dossier : « à jour » ne se dit que si tout a été
vérifié (principe « ne jamais dire plus qu'on ne sait », MASTER) ; un constat « non
vérifiable » n'est pas à mettre à jour (une dépendance git ne se vérifie pas).
"""

import enum
from collections.abc import Iterable
from dataclasses import dataclass, field

from forceupdate.models import FindingKind, Severity
from forceupdate.report import Summary


class Verdict(enum.StrEnum):
    """Ce que dit le rapport d'un dépôt."""

    TO_UPDATE = "to_update"
    """Au moins un constat à mettre à jour (``Summary.to_update``)."""
    UP_TO_DATE = "up_to_date"
    """Tout ce qui a été vérifié est à jour, et rien n'est resté sans réponse."""
    INCONCLUSIVE = "inconclusive"
    """Rien à mettre à jour d'après ce qui a répondu, mais pas tout n'a répondu (registre ou
    OSV muets), ou le dépôt n'a pas été lu en entier : on ne peut pas dire « à jour »."""
    NO_DEPENDENCIES = "no_dependencies"
    """Aucun fichier de dépendances : rien à vérifier."""


def verdict(summary: Summary, *, partial: bool = False) -> Verdict:
    """Le verdict d'un rapport. ``partial`` : la source n'a pas été lue en entier
    (arborescence tronquée par la forge)."""
    if summary.to_update > 0:
        return Verdict.TO_UPDATE
    if summary.findings.get(FindingKind.INCONCLUSIVE, 0) > 0 or partial:
        return Verdict.INCONCLUSIVE
    if summary.projects == 0:
        return Verdict.NO_DEPENDENCIES
    return Verdict.UP_TO_DATE


@dataclass(kw_only=True)
class Combined:
    """Les constats de plusieurs rapports, additionnés. Un même paquet dans deux dépôts y
    compte deux fois : ce sont deux mises à jour à faire."""

    reports: int = 0
    findings: dict[FindingKind, int] = field(default_factory=lambda: dict.fromkeys(FindingKind, 0))
    """Par type, tous les types présents."""
    severities: dict[Severity, int] = field(default_factory=lambda: dict.fromkeys(Severity, 0))
    """Les constats à mettre à jour, par gravité."""
    vulnerabilities: dict[Severity, int] = field(default_factory=lambda: dict.fromkeys(Severity, 0))
    """Les failles, par gravité."""
    vulnerable_reports: int = 0
    """Les rapports qui ont au moins une faille."""

    @property
    def to_update(self) -> int:
        return sum(self.severities.values())


def combine(summaries: Iterable[Summary]) -> Combined:
    """Les constats de ``summaries`` additionnés."""
    combined = Combined()
    for summary in summaries:
        combined.reports += 1
        for kind, count in summary.findings.items():
            combined.findings[kind] += count
        for severity, count in summary.severities.items():
            combined.severities[severity] += count
        for severity, count in summary.vulnerabilities.items():
            combined.vulnerabilities[severity] += count
        if any(summary.vulnerabilities.values()):
            combined.vulnerable_reports += 1
    return combined
