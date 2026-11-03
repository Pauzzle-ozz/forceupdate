"""Les dépendances à mettre à jour, en CSV (session 36) : un tableau à ouvrir dans un tableur,
une ligne par paquet (et par version installée d'une indirecte), une par runtime en fin de vie.

Séparé par des points-virgules, en UTF-8 précédé d'un BOM (``BOM``, à mettre en tête du
fichier) : c'est ce qu'Excel ouvre tel quel en français, où la virgule est le séparateur
décimal, et qui lit sans BOM de l'ANSI. Les colonnes reprennent le tableau du rapport
(``report.rows``), plus ce qu'un tableur veut trier : directe ou indirecte, la gravité, le
nombre de failles et leurs identifiants, la version qui les corrige.

Seulement ce qui est à mettre à jour : pas ce qui ne dit rien à faire (une version non fixée,
un paquet non vérifiable, un constat non concluant : ``checks.priority.NOT_TO_UPDATE``). Le
rapport entier est en Markdown ou en JSON.
"""

import csv
import io
from collections.abc import Iterable

from forceupdate import versions
from forceupdate.checks.priority import NOT_TO_UPDATE
from forceupdate.checks.vulns import SEVERITY_LABELS
from forceupdate.models import Finding, FindingKind, Report, Severity
from forceupdate.report import KIND_LABELS, Row, label, rows

BOM = "﻿"
"""En tête d'un fichier CSV : sans lui, Excel lit l'UTF-8 comme de l'ANSI."""

HEADERS = (
    "Projet",
    "Écosystème",
    "Paquet",
    "Dépendance",
    "Portée",
    "Contrainte",
    "Utilisée",
    "Permise",
    "Dernière",
    "Constats",
    "Gravité",
    "Failles",
    "Identifiants",
    "Corrigée en",
    "Fichier",
)

_GRAVITY = {**SEVERITY_LABELS, Severity.INFO: "information"}
"""La gravité d'un constat, comme la barre des gravités du rapport : « information » plutôt que
« nulle » pour ce qui n'est pas une faille."""


def render(report: Report) -> str:
    """Le tableau en CSV, sans le BOM, lignes terminées par ``\\n`` comme les autres rapports (un
    tableur les lit, et la sortie standard de Windows doublerait un ``\\r``)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(HEADERS)
    for project in report.projects:
        for row in [*rows(project, report), *rows(project, report, direct=False)]:
            findings = [f for f in row.findings if f.kind not in NOT_TO_UPDATE]
            if findings:
                writer.writerow(_line(project.path, row, findings))
        for finding in project.findings:
            if finding.kind is FindingKind.EOL and finding.dependency is None and finding.eol:
                writer.writerow(_runtime(project.path, finding))
    return buffer.getvalue()


def _line(project: str, row: Row, findings: list[Finding]) -> list[str]:
    dependencies = row.dependencies
    ecosystem = dependencies[0].ecosystem if dependencies else ""
    vulnerabilities = [f for f in findings if f.kind is FindingKind.VULNERABLE]
    fixed = [f.target_version for f in vulnerabilities if f.target_version]
    # La version qui corrige toutes ses failles : la plus haute des corrections.
    fixing = versions.for_ecosystem(ecosystem).highest(fixed) if fixed else None
    return [
        project,
        ecosystem,
        row.name,
        "directe" if any(d.direct for d in dependencies) else "indirecte",
        _join(str(d.scope) for d in dependencies),
        row.constraint,
        row.current,
        row.wanted,
        row.latest,
        _join(label(f) for f in findings),
        _GRAVITY[_worst(findings)],
        str(len({f.identifiers[0] if f.identifiers else f.message for f in vulnerabilities})),
        " ".join(dict.fromkeys(i for f in vulnerabilities for i in f.identifiers)),
        fixing or "",
        _join(d.file for d in dependencies),
    ]


def _runtime(project: str, finding: Finding) -> list[str]:
    """Un runtime en fin de vie : Python 3.8, Node.js 16…"""
    assert finding.eol is not None
    runtime = finding.eol.runtime
    return [
        project,
        "runtime",
        finding.eol.label,
        "",
        "",
        runtime.source if runtime is not None else "",
        finding.current_version or "",
        "",
        finding.target_version or "",
        KIND_LABELS[FindingKind.EOL],
        _GRAVITY[finding.severity],
        "0",
        "",
        "",
        runtime.file if runtime is not None else "",
    ]


def _worst(findings: Iterable[Finding]) -> Severity:
    """La plus grave (``Severity`` va du plus grave au moins grave)."""
    order = list(Severity)
    return min((f.severity for f in findings), key=order.index)


def _join(values: Iterable[str]) -> str:
    return ", ".join(dict.fromkeys(v for v in values if v))
