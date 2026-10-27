"""Le rapport en Markdown : ``forceupdate scan --format md``. Il servira aussi de corps aux PR
(E18) : du Markdown que GitHub, GitLab et Bitbucket affichent tous (titres, tableaux,
listes).

Ce qui vient des fichiers analysés ou des registres est échappé : un ``|`` (``^1 || ^2``)
couperait une cellule de tableau, un ``*`` ou un ``_`` mettrait en forme un message.
"""

import re

from forceupdate.checks import GAP_LABELS
from forceupdate.models import FindingKind, Project, Report
from forceupdate.report import (
    KIND_LABELS,
    Row,
    Summary,
    distinct_findings,
    format_date,
    format_share,
    label,
    plural,
    rows,
    summarize,
)

_SPECIAL = re.compile(r"([\\`*_{}\[\]<>()#+!|~])")


def render(report: Report) -> str:
    """Le rapport en Markdown, terminé par un saut de ligne."""
    lines = ["# Rapport forceupdate", ""]
    lines.append(f"Source : `{_code(report.source)}`")
    if report.scanned_at is not None:
        lines += ["", f"Analyse du {format_date(report.scanned_at)}."]
        if report.options is not None and report.options.offline:
            if report.oldest_data is None:
                lines.append("Hors ligne, sans données des registres ni d'OSV en cache.")
            else:
                lines.append(
                    "Hors ligne : données des registres et d'OSV prises dans le cache, la plus"
                    f" ancienne du {format_date(report.oldest_data)}."
                )
    if report.options is not None:
        lines += ["", "## Résumé", "", *_summary(summarize(report))]
        if not report.options.dev:
            lines += ["", "Dépendances de développement non vérifiées (`--no-dev`)."]
    lines += ["", "## Langages", ""]
    if not report.languages:
        lines.append("Aucun reconnu.")
    else:
        total = sum(language.bytes for language in report.languages)
        lines += ["| Langage | Part | Écosystème |", "|---|---:|---|"]
        for language in report.languages:
            ecosystem = language.ecosystem or "aucun gestionnaire de paquets reconnu"
            share = format_share(language.bytes, total).strip()
            lines.append(f"| {_escape(language.name)} | {share} | {ecosystem} |")
    if not report.projects:
        lines += ["", "## Projets", "", "Aucun."]
    for project in report.projects:
        lines += _project(project, report)
    if report.ignored_manifests:
        lines += [
            "",
            "## Fichiers écartés",
            "",
            "Rangés dans des dossiers de tests ou d'exemples, ce ne sont pas de vrais projets :",
            "",
        ]
        lines += [f"- `{_code(path)}`" for path in report.ignored_manifests]
    return "\n".join(lines) + "\n"


def _summary(summary: Summary) -> list[str]:
    lines = [
        f"- {plural(summary.projects, 'projet')}, "
        f"{plural(summary.checked, 'dépendance')} vérifiée{'s' if summary.checked > 1 else ''}"
    ]
    if summary.audited != summary.checked:
        lines[0] += f", failles cherchées sur {summary.audited}"
    if not summary.to_update:
        lines.append("- Rien à mettre à jour.")
    else:
        lines.append(f"- {summary.to_update} à mettre à jour :")
        for kind, count in summary.findings.items():
            if not count or kind in (FindingKind.UNVERIFIABLE, FindingKind.INCONCLUSIVE):
                continue
            if kind is FindingKind.OUTDATED:
                lines += [
                    f"  - {plural(n, GAP_LABELS[gap])}" for gap, n in summary.outdated.items() if n
                ]
            else:
                lines.append(f"  - {plural(count, KIND_LABELS[kind])}")
    for kind in (FindingKind.UNVERIFIABLE, FindingKind.INCONCLUSIVE):
        if summary.findings[kind]:
            lines.append(f"- {plural(summary.findings[kind], KIND_LABELS[kind])}")
    return lines


def _project(project: Project, report: Report) -> list[str]:
    title = f"## Projet `{_code(project.path)}`"
    if project.ecosystems:
        title += f" ({', '.join(project.ecosystems)})"
    lines = ["", title, ""]
    lines.append(f"- Manifestes : {_files(project.manifests)}")
    lines.append(f"- Lockfiles : {_files(project.lockfiles)}")
    directs = sum(1 for d in project.dependencies if d.direct)
    lines.append(
        f"- Dépendances directes : {directs or 'aucune'} ; "
        f"indirectes : {len(project.dependencies) - directs or 'aucune'}"
    )
    direct_rows = rows(project, report)
    if direct_rows:
        lines += ["", *_table(direct_rows)]
    indirect_rows = rows(project, report, direct=False)
    if indirect_rows:
        lines += ["", "### Dépendances indirectes à signaler", "", *_table(indirect_rows)]
    details = [f for f in distinct_findings([project]) if f.kind is not FindingKind.OUTDATED]
    if details:
        lines += ["", "### Détails", ""]
        for finding in details:
            dependency = finding.dependency
            name = ""
            if dependency is not None:
                name = f"`{_code(dependency.name)}`"
                if not dependency.direct and dependency.installed:
                    name += f" {_escape(dependency.installed)}"
                name += " (indirecte) : " if not dependency.direct else " : "
            link = ""
            if finding.kind is FindingKind.VULNERABLE and finding.url:
                link = f" [Avis]({finding.url})"
            lines.append(f"- **{label(finding)}** — {name}{_escape(finding.message)}{link}")
    if project.notices:
        lines += ["", "### Remarques", ""]
        lines += [
            f"- `{_code(notice.file)}` : {_escape(notice.message)}" for notice in project.notices
        ]
    return lines


def _table(found: list[Row]) -> list[str]:
    lines = [
        "| Paquet | Contrainte | Utilisée | Permise | Dernière | État |",
        "|---|---|---|---|---|---|",
    ]
    for row in found:
        name = f"`{_code(row.name)}`"
        if row.notes:
            name += f" ({_escape(', '.join(row.notes))})"
        constraint = f"`{_code(row.constraint)}`" if row.constraint != "-" else "-"
        lines.append(
            f"| {name} | {constraint} | {_escape(row.current)} | {_escape(row.wanted)} "
            f"| {_escape(row.latest)} | {_escape(', '.join(row.states))} |"
        )
    return lines


def _files(paths: list[str]) -> str:
    return ", ".join(f"`{_code(path)}`" for path in paths) or "aucun"


def _escape(text: str) -> str:
    """Du texte ordinaire : les caractères de Markdown échappés, sur une ligne."""
    return _SPECIAL.sub(r"\\\1", " ".join(text.split()))


def _code(text: str) -> str:
    """Du texte entre accents graves : sans accent grave, et ``|`` échappé (dans un tableau,
    GitHub coupe la cellule même dans du code)."""
    return " ".join(text.replace("`", "'").split()).replace("|", "\\|")
