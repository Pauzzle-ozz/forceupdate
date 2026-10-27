"""Les rapports : le résultat d'une analyse, mis en forme.

- ``terminal.py`` : pour la console (``rich``) ;
- ``json.py`` : le format de l'API (E12), décrit dans ``docs/JSON_FORMAT.md`` ;
- ``markdown.py`` : un rapport à lire, qui servira aussi de corps aux PR (E18).

Ce module garde ce qu'ils partagent : les noms des constats, le résumé, et les lignes du
tableau d'un projet (un paquet par ligne, même déclaré deux fois).
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from forceupdate import checks
from forceupdate.checks import GAP_LABELS, vulns
from forceupdate.models import (
    Dependency,
    Finding,
    FindingKind,
    Gap,
    Project,
    Report,
    Scope,
)

KIND_LABELS = {
    FindingKind.VULNERABLE: "faille",
    FindingKind.EOL: "fin de vie",
    FindingKind.YANKED: "retirée",
    FindingKind.DEPRECATED: "déprécié",
    FindingKind.OUTDATED: "plus récente",
    FindingKind.UNVERIFIABLE: "non vérifiable",
    FindingKind.INCONCLUSIVE: "non concluant",
}
"""Le type d'un constat en français, tel qu'on l'affiche."""

UP_TO_DATE = "à jour"
POSSIBLE_VULNERABILITY = "faille possible"
"""Une faille de la borne basse d'une contrainte, sans lockfile : la version installée peut
être plus récente, et corrigée."""


def label(finding: Finding) -> str:
    """Le constat en un ou deux mots : ``majeure``, ``retirée``, ``faille possible``…"""
    if finding.kind is FindingKind.OUTDATED and finding.gap is not None:
        return GAP_LABELS[finding.gap]
    if finding.kind is FindingKind.VULNERABLE and finding.current_is_approximate:
        return POSSIBLE_VULNERABILITY
    return KIND_LABELS[finding.kind]


def subject(finding: Finding) -> str:
    """Ce dont parle le constat, pour le détail : le paquet ; pour une dépendance indirecte, sa
    version aussi (un paquet npm peut y être en plusieurs versions)."""
    dependency = finding.dependency
    if dependency is None:
        return ""
    if dependency.direct:
        return dependency.name
    version = f" {dependency.installed}" if dependency.installed else ""
    return f"{dependency.name}{version} (indirecte)"


def plural(count: int, word: str) -> str:
    """``count`` suivi de ``word``, au pluriel au-delà de 1 : ``2 majeures``, ``3 fins de vie``."""
    if count > 1:
        word = _PLURALS.get(word, word + "s")
    return f"{count} {word}"


_PLURALS = {"fin de vie": "fins de vie"}


def format_date(when: datetime) -> str:
    """Une date à la française, à l'heure locale : ``27/10/2026 à 14:03``."""
    return when.astimezone().strftime("%d/%m/%Y à %H:%M")


def format_share(part: int, total: int) -> str:
    """Une part en pourcentage, à la française : `` 75,0 %``."""
    return f"{100 * part / total:5.1f} %".replace(".", ",")


@dataclass(frozen=True, kw_only=True)
class Summary:
    """Les chiffres d'une analyse. Un paquet déclaré deux fois dans un projet (runtime et dev)
    donne deux constats identiques : ils comptent pour un."""

    projects: int
    direct: int
    """Dépendances directes, toutes déclarations comprises."""
    transitive: int
    checked: int
    """Dépendances vérifiées auprès des registres (voir ``ScanOptions``)."""
    audited: int = 0
    """Dépendances dont les failles ont été cherchées (OSV) : toutes celles dont on connaît la
    version, indirectes comprises (voir ``checks.vulns``)."""
    findings: dict[FindingKind, int] = field(default_factory=dict)
    """Constats par type, dans l'ordre de priorité ; tous les types y sont, même à 0."""
    outdated: dict[Gap, int] = field(default_factory=dict)
    """Versions plus récentes par écart, de la majeure au correctif."""

    @property
    def to_update(self) -> int:
        """Ce qui est à mettre à jour : tout sauf « non vérifiable » et « non concluant »."""
        return sum(
            count
            for kind, count in self.findings.items()
            if kind not in (FindingKind.UNVERIFIABLE, FindingKind.INCONCLUSIVE)
        )


def summarize(report: Report) -> Summary:
    """Le résumé de ``report``."""
    findings = dict.fromkeys(KIND_LABELS, 0)
    outdated = dict.fromkeys(GAP_LABELS, 0)
    for finding in distinct_findings(report.projects):
        findings[finding.kind] += 1
        if finding.kind is FindingKind.OUTDATED and finding.gap is not None:
            outdated[finding.gap] += 1
    dependencies = [d for project in report.projects for d in project.dependencies]
    direct = sum(1 for d in dependencies if d.direct)
    options = report.options
    checked = audited = 0
    if options is not None:
        checked = sum(1 for d in dependencies if checks.selected(d, options))
        audited = sum(
            1
            for d in dependencies
            if vulns.audited(d, options) and vulns.version_to_check(d) is not None
        )
    return Summary(
        projects=len(report.projects),
        direct=direct,
        transitive=len(dependencies) - direct,
        checked=checked,
        audited=audited,
        findings=findings,
        outdated=outdated,
    )


def distinct_findings(projects: Iterable[Project]) -> list[Finding]:
    """Les constats de ``projects``, du plus grave au moins grave, sans les doubles : un
    paquet déclaré deux fois dans un projet n'est compté qu'une fois."""
    seen = set()
    kept = []
    for project in projects:
        for finding in project.findings:
            dependency = finding.dependency
            key = (
                project.path,
                finding.kind,
                None if dependency is None else (dependency.ecosystem, dependency.name),
                finding.current_version,
                finding.target_version,
                finding.message,
            )
            if key not in seen:
                seen.add(key)
                kept.append(finding)
    return checks.sort_findings(kept)


@dataclass(frozen=True, kw_only=True)
class Row:
    """Une ligne du tableau d'un projet : un paquet, avec toutes ses déclarations."""

    name: str
    notes: tuple[str, ...]
    """Ce qui la distingue : scope (sauf ``runtime``), fichier quand le projet en a plusieurs."""
    constraint: str
    """La contrainte telle qu'écrite (``-`` s'il n'y en a pas), avec la plage d'un catalogue
    pnpm entre parenthèses ; plusieurs, séparées par des virgules."""
    current: str
    """La version utilisée ; ``≈ 1.2`` pour une borne basse ; ``-`` si on ne la connaît pas."""
    wanted: str
    """La plus haute que la contrainte accepte ; vide si rien n'est à signaler."""
    latest: str
    """La dernière ; vide si rien n'est à signaler."""
    findings: tuple[Finding, ...]
    """Ses constats, sans les doubles, du plus grave au moins grave."""
    checked: bool
    """Vérifiée auprès du registre."""
    unverifiable: str | None = None
    """Pourquoi on ne peut pas la vérifier (``Dependency.unverifiable_reason``)."""

    @property
    def states(self) -> list[str]:
        """Les constats en un ou deux mots ; « à jour » pour une dépendance vérifiée sans
        constat ; pourquoi elle n'est pas vérifiable (un membre du workspace n'a pas de
        constat) ; rien si elle n'a pas été vérifiée."""
        if self.findings:
            return list(dict.fromkeys(label(finding) for finding in self.findings))
        if self.unverifiable is not None:
            return [f"non vérifiable : {self.unverifiable}"]
        return [UP_TO_DATE] if self.checked else []


def rows(project: Project, report: Report, *, direct: bool = True) -> list[Row]:
    """Les lignes du tableau de ``project`` : ses dépendances directes vérifiées (ou toutes si
    rien n'a été vérifié), une ligne par paquet, les plus graves en tête.

    ``direct=False`` : les dépendances indirectes qui ont un constat (une faille, ou ce
    qu'ajoute ``--transitive``) ; une ligne par version installée.
    """
    several_files = len({d.file for d in project.dependencies if d.direct}) > 1
    groups: dict[tuple[str, ...], list[Dependency]] = {}
    for dependency in project.dependencies:
        if dependency.direct is not direct:
            continue
        if (
            direct
            and report.options is not None
            and not checks.selected(dependency, report.options)
        ):
            continue
        key = (dependency.ecosystem, dependency.name)
        if not direct:
            key += (dependency.installed or "",)
        groups.setdefault(key, []).append(dependency)
    found = []
    for group in groups.values():
        row = _row(group, project.findings, several_files, checked=report.options is not None)
        if direct or row.findings:
            found.append(row)
    return sorted(found, key=_row_order)


def _row(
    group: list[Dependency], findings: list[Finding], several_files: bool, *, checked: bool
) -> Row:
    mine = checks.sort_findings(f for f in findings if f.dependency in group)
    unique: dict[tuple[object, ...], Finding] = {}
    for finding in mine:
        unique.setdefault((finding.kind, finding.message), finding)
    notes = []
    for dependency in group:
        if dependency.scope is not Scope.RUNTIME:
            notes.append(str(dependency.scope))
        if several_files:
            notes.append(dependency.file)
    versions = [f for f in unique.values() if f.target_version and f.kind in _VERSION_KINDS]
    return Row(
        name=group[0].name,
        notes=tuple(dict.fromkeys(notes)),
        constraint=_join(_constraint(d) for d in group),
        current=_join(_current(d) for d in group),
        wanted=_join(f.wanted_version or "" for f in versions),
        latest=_join(f.target_version or "" for f in versions),
        findings=tuple(unique.values()),
        checked=checked and all(d.verifiable for d in group),
        unverifiable=next((d.unverifiable_reason for d in group if not d.verifiable), None),
    )


_VERSION_KINDS = (FindingKind.OUTDATED, FindingKind.INCONCLUSIVE)
"""Les constats qui portent la dernière version et celle de la contrainte."""


def _row_order(row: Row) -> tuple[tuple[int, int], str]:
    worst = checks.priority(row.findings[0]) if row.findings else (len(KIND_LABELS), 0)
    return worst, row.name


def _constraint(dependency: Dependency) -> str:
    text = dependency.constraint or "-"
    if dependency.resolved_constraint is not None:
        text += f" ({dependency.resolved_constraint})"
    return text


def _current(dependency: Dependency) -> str:
    if not dependency.verifiable:
        return dependency.installed or "-"
    try:
        current = checks.current_version(dependency)
    except LookupError:  # écosystème dont les versions ne sont pas encore gérées
        return dependency.installed or "-"
    if current.version is None:
        return "-"
    return f"≈ {current.version}" if current.approximate else current.version


def _join(values: Iterable[str]) -> str:
    return ", ".join(value for value in dict.fromkeys(values) if value)
