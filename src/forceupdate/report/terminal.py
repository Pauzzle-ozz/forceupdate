"""Le rapport pour la console, avec ``rich`` : ``forceupdate scan``, et les mises à jour
proposées de ``forceupdate update`` (``render_plan``).

Pour ``scan``, dans l'ordre : la source, les langages, chaque projet (fichiers, un tableau de ses
dépendances directes, le détail des constats autres que « plus récente », les remarques), les
fichiers écartés, puis le résumé.

Tout ce qui vient des fichiers analysés ou des registres passe par ``Text`` : un nom de paquet
ou un message qui contient ``[…]`` (``sechunter[all]``) ne doit pas être lu comme du balisage.
"""

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from forceupdate.checks import GAP_LABELS
from forceupdate.models import (
    Finding,
    FindingKind,
    Gap,
    Project,
    Report,
    Severity,
    Update,
    UpdateOption,
)
from forceupdate.report import (
    KIND_LABELS,
    REASON_LABELS,
    UP_TO_DATE,
    Row,
    Summary,
    distinct_findings,
    format_date,
    format_share,
    label,
    option_changes,
    option_fixed,
    option_fixes,
    option_gap,
    plural,
    rows,
    subject,
    summarize,
    update_subject,
)
from forceupdate.update.planner import DEFAULT_RULES, Rules, Selection

_STYLES = {
    FindingKind.YANKED: "bold red",
    FindingKind.DEPRECATED: "yellow",
    FindingKind.UNVERIFIABLE: "magenta",
    FindingKind.INCONCLUSIVE: "magenta",
}
_GAP_STYLES = {Gap.MAJOR: "yellow", Gap.MINOR: "cyan", Gap.PATCH: "green"}
_SEVERITY_STYLES = {
    Severity.CRITICAL: "bold red",
    Severity.HIGH: "red",
    Severity.MEDIUM: "yellow",
    Severity.LOW: "cyan",
    Severity.INFO: "dim",
}


def render(report: Report, console: Console) -> None:
    """Écrit le rapport sur ``console``."""
    console.print(Text.assemble(("Source : ", "bold"), report.source))
    _print_dates(report, console)
    _print_languages(report, console)
    console.print()
    console.print(Text(f"Projets : {len(report.projects) or 'aucun'}", style="bold"))
    for project in report.projects:
        _print_project(project, report, console)
    if report.ignored_manifests:
        count = len(report.ignored_manifests)
        console.print()
        console.print(
            Text(
                "Écartés, car rangés dans des dossiers de tests ou d'exemples : "
                + plural(count, "fichier"),
                style="bold",
            )
        )
        for path in report.ignored_manifests:
            console.print(Text(f"  {path}"))
    if report.options is not None:
        console.print()
        console.print(_summary_line(summarize(report)))
        if not report.options.dev:
            console.print(Text("Dépendances de développement non vérifiées (--no-dev).", "dim"))


def _print_dates(report: Report, console: Console) -> None:
    if report.scanned_at is None:
        return
    line = f"Analyse du {format_date(report.scanned_at)}"
    if report.options is not None and report.options.offline:
        if report.oldest_data is None:
            line += " ; hors ligne, sans données des registres ni d'OSV en cache"
        else:
            line += (
                " ; hors ligne : données des registres et d'OSV prises dans le cache, la plus"
                f" ancienne du {format_date(report.oldest_data)}"
            )
    console.print(Text(line + ".", style="dim"))


def _print_languages(report: Report, console: Console) -> None:
    console.print()
    if not report.languages:
        console.print(Text("Langages : aucun reconnu", style="bold"))
        return
    console.print(Text("Langages", style="bold"))
    total = sum(language.bytes for language in report.languages)
    width = max(len(language.name) for language in report.languages)
    for language in report.languages:
        ecosystem = language.ecosystem or "aucun gestionnaire de paquets reconnu"
        share = format_share(language.bytes, total)
        console.print(Text(f"  {language.name:<{width}}  {share}  {ecosystem}"))


def _print_project(project: Project, report: Report, console: Console) -> None:
    console.print()
    title = Text.assemble(("Projet ", "bold"), (project.path, "bold cyan"))
    if project.ecosystems:
        title.append(f"  ({', '.join(project.ecosystems)})")
    console.print(title)
    console.print(Text(f"  manifestes : {', '.join(project.manifests) or 'aucun'}"))
    console.print(Text(f"  lockfiles  : {', '.join(project.lockfiles) or 'aucun'}"))
    direct_rows = rows(project, report)
    if direct_rows:
        console.print(_table(direct_rows))
    console.print(Text(f"  {_counts(project)}"))
    indirect_rows = rows(project, report, direct=False)
    if indirect_rows:
        console.print(Text("  Dépendances indirectes à signaler", style="bold"))
        console.print(_table(indirect_rows))
    details = [f for f in distinct_findings([project]) if f.kind is not FindingKind.OUTDATED]
    if details:
        console.print(Text("  Détails", style="bold"))
        grid = _grid()
        for finding in details:
            message = Text()
            if finding.dependency is not None:
                message.append(f"{subject(finding)} : ", style="bold")
            message.append(finding.message)
            grid.add_row("", Text(label(finding), style=_finding_style(finding)), message)
        console.print(grid)
    if project.notices:
        console.print(Text("  Remarques", style="bold"))
        grid = _grid()
        for notice in project.notices:
            grid.add_row("", Text(notice.file), Text(notice.message))
        console.print(grid)


def _grid() -> Table:
    """Une grille de trois colonnes : un retrait, une étiquette, un texte qui se replie sous
    lui-même."""
    grid = Table.grid(padding=(0, 1))
    grid.add_column(width=3)
    grid.add_column(no_wrap=True)
    grid.add_column(overflow="fold")
    return grid


def _table(found: list[Row]) -> Table:
    table = Table(box=box.SIMPLE_HEAD, pad_edge=False, padding=(0, 1), show_edge=False)
    table.add_column("Paquet", overflow="fold", min_width=10)
    table.add_column("Contrainte", overflow="fold", min_width=8)
    table.add_column("Utilisée", overflow="fold", min_width=8)
    table.add_column("Permise", overflow="fold", min_width=7)
    table.add_column("Dernière", overflow="fold", min_width=8)
    table.add_column("État", min_width=9)
    for row in found:
        name = Text(row.name)
        if row.notes:
            name.append(f" ({', '.join(row.notes)})", style="dim")
        table.add_row(
            name,
            Text(row.constraint),
            Text(row.current),
            Text(row.wanted),
            Text(row.latest),
            _states(row),
        )
    return table


def _states(row: Row) -> Text:
    text = Text()
    if not row.findings:
        for state in row.states:
            text.append(state, style="green" if state == UP_TO_DATE else "dim")
        return text
    seen = set()
    for finding in row.findings:
        word = label(finding)
        if word in seen:
            continue
        if seen:
            text.append(", ")
        seen.add(word)
        text.append(word, style=_finding_style(finding))
    return text


def _finding_style(finding: Finding) -> str:
    if finding.kind in (FindingKind.VULNERABLE, FindingKind.EOL):
        return _SEVERITY_STYLES[finding.severity]
    if finding.kind is FindingKind.OUTDATED and finding.gap is not None:
        return _GAP_STYLES[finding.gap]
    return _STYLES.get(finding.kind, "")


def _counts(project: Project) -> str:
    directs = [d for d in project.dependencies if d.direct]
    indirect = len(project.dependencies) - len(directs)
    scopes: dict[str, int] = {}
    for dependency in directs:
        scopes[dependency.scope] = scopes.get(dependency.scope, 0) + 1
    detail = ", ".join(f"{count} {scope}" for scope, count in scopes.items())
    line = f"dépendances directes : {len(directs) or 'aucune'}"
    if len(scopes) > 1:
        line += f" ({detail})"
    return line + f" ; indirectes : {indirect or 'aucune'}"


def _summary_line(summary: Summary) -> Text:
    text = Text("Résumé : ", style="bold")
    checked = plural(summary.checked, "dépendance")
    text.append(f"{checked} vérifiée{'s' if summary.checked > 1 else ''}")
    if summary.audited != summary.checked:
        text.append(f", failles cherchées sur {summary.audited}")
    if not summary.to_update:
        text.append(", rien à mettre à jour")
    else:
        parts = []
        for kind, count in summary.findings.items():
            if not count or kind in (FindingKind.UNVERIFIABLE, FindingKind.INCONCLUSIVE):
                continue
            if kind is FindingKind.OUTDATED:
                parts += [plural(n, GAP_LABELS[gap]) for gap, n in summary.outdated.items() if n]
            else:
                parts.append(plural(count, KIND_LABELS[kind]))
        text.append(f", {summary.to_update} à mettre à jour : {', '.join(parts)}")
    others = [
        plural(summary.findings[kind], KIND_LABELS[kind])
        for kind in (FindingKind.UNVERIFIABLE, FindingKind.INCONCLUSIVE)
        if summary.findings[kind]
    ]
    if others:
        text.append(f" ; {', '.join(others)}")
    text.append(".")
    return text


# ---------------------------------------------------------------------------
# Mises à jour proposées
# ---------------------------------------------------------------------------


def render_plan(
    report: Report, selection: Selection, console: Console, rules: Rules = DEFAULT_RULES
) -> None:
    """Écrit les mises à jour proposées sur ``console`` : par projet, celles que ``selection``
    choisit, puis les autres versions proposées, et ce que les options ne disent pas (faille
    sans version corrigée…). ``rules`` sont les règles qui ont fait la sélection."""
    console.print(Text.assemble(("Source : ", "bold"), report.source))
    _print_dates(report, console)
    updates = [u for project in report.projects for u in project.updates]
    for project in report.projects:
        if project.updates:
            _print_project_plan(project, selection, console)
    console.print()
    if not updates:
        console.print(Text("Rien à mettre à jour.", style="bold"))
        return
    count = sum(1 for update in updates if update.id in selection)
    line = Text("Mises à jour choisies : ", style="bold")
    line.append(f"{count} sur {plural(len(updates), 'paquet')} à mettre à jour ({_rules(rules)}).")
    console.print(line)
    console.print(
        Text(
            "Aucun fichier n'est modifié : forceupdate update montre pour l'instant ce qu'il "
            "ferait.",
            style="dim",
        )
    )


def _print_project_plan(project: Project, selection: Selection, console: Console) -> None:
    console.print()
    title = Text.assemble(("Projet ", "bold"), (project.path, "bold cyan"))
    if project.ecosystems:
        title.append(f"  ({', '.join(project.ecosystems)})")
    console.print(title)
    picked = [u for u in project.updates if u.id in selection]
    if picked:
        table = Table(box=box.SIMPLE_HEAD, pad_edge=False, padding=(0, 1), show_edge=False)
        table.add_column("Paquet", overflow="fold", min_width=10)
        table.add_column("Version", overflow="fold", min_width=10)
        table.add_column("Écart", min_width=9)
        table.add_column("Failles", no_wrap=True)
        table.add_column("Changement", overflow="fold")
        for update in picked:
            option = update.option(selection[update.id])
            assert option is not None
            table.add_row(
                Text(update_subject(update)),
                Text(f"{update.current_version} → {option.version}"),
                _gap_text(option),
                Text(option_fixes(option)),
                Text("\n".join(option_changes(option, project.path))),
            )
        console.print(table)
    else:
        console.print(Text("  Aucune mise à jour choisie.", style="dim"))
    others = [(u, o) for u in project.updates for o in _not_chosen(u, selection.get(u.id))]
    if others:
        console.print(Text("  Proposées, non cochées", style="bold"))
        grid = _grid()
        for update, option in others:
            name = Text(update_subject(update), style="bold")
            name.append(f" {update.current_version} → {option.version}")
            grid.add_row("", name, _option_detail(option, project.path))
        console.print(grid)
    notes = [u for u in project.updates if u.note]
    if notes:
        console.print(Text("  À savoir", style="bold"))
        grid = _grid()
        for update in notes:
            grid.add_row("", Text(update_subject(update), style="bold"), Text(update.note or ""))
        console.print(grid)


def _not_chosen(update: Update, version: str | None) -> list[UpdateOption]:
    """Les options à montrer en plus de la version choisie : celles au-dessus, ou toutes si
    aucune n'est choisie."""
    if version is None:
        return list(update.options)
    index = next(i for i, option in enumerate(update.options) if option.version == version)
    return list(update.options[index + 1 :])


def _option_detail(option: UpdateOption, project: str) -> Text:
    text = _gap_text(option)
    reasons = ", ".join(REASON_LABELS[reason] for reason in option.reasons)
    text.append(f" ; {reasons}")
    fixed = option_fixed(option)
    if fixed:
        text.append(f" ; {fixed}")
    text.append(".")
    for warning in option.warnings:
        text.append(f" {warning}", style="yellow")
    changes = option_changes(option, project)
    if changes:
        text.append(" " + " ; ".join(changes) + ".", style="dim")
    return text


def _gap_text(option: UpdateOption) -> Text:
    style = "yellow" if option.gap is None else _GAP_STYLES[option.gap]
    return Text(option_gap(option), style=style)


def _rules(rules: Rules) -> str:
    """Les règles de la sélection, comme on les écrirait sur la ligne de commande."""
    parts = [f"--level {rules.level}"]
    if rules.security_only:
        parts.append("--security-only")
    parts += [f"--include {pattern}" for pattern in rules.include]
    parts += [f"--exclude {pattern}" for pattern in rules.exclude]
    parts += [f"--ecosystem {ecosystem}" for ecosystem in sorted(rules.ecosystems)]
    return " ".join(parts)
