"""Les rapports : résumé, lignes de tableau, JSON, Markdown et terminal."""

import asyncio
import io
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
import respx
from rich.console import Console

from forceupdate import __version__, engine
from forceupdate.models import (
    Dependency,
    Ecosystem,
    Finding,
    FindingKind,
    Gap,
    Language,
    Notice,
    Project,
    Report,
    ScanOptions,
    Scope,
    Severity,
)
from forceupdate.net import Cache, HttpClient
from forceupdate.report import json as json_report
from forceupdate.report import markdown, rows, summarize, terminal
from forceupdate.sources.local import LocalSource

MakeTree = Callable[..., Path]

PYPROJECT = """\
[project]
name = "api"
dependencies = ["Flask==2.0.1", "requests==2.32.0", "sechunter-extra[all]>=1"]
[dependency-groups]
dev = ["flask==2.0.1"]
"""


@pytest.fixture
def report(recorded: dict[str, respx.Route], make_tree: MakeTree) -> Report:
    root = make_tree(
        {
            "api/pyproject.toml": PYPROJECT,
            "api/setup.py": "",
            "web/package.json": json.dumps({"dependencies": {"left-pad": "^1 || ^2"}}),
            "tests/demo/package.json": "{}",
            "api/main.py": "print('é')\n",
        }
    )

    async def main() -> Report:
        async with HttpClient() as http:
            return await engine.analyze(LocalSource(root), http=http, cache=Cache.disabled())

    return asyncio.run(main())


def dependency(name: str, **fields: object) -> Dependency:
    return Dependency(ecosystem=Ecosystem.PYPI, name=name, file="requirements.txt", **fields)  # type: ignore[arg-type]


# -- résumé et lignes ----------------------------------------------------------


def test_summary_counts_a_double_declaration_once(report: Report) -> None:
    summary = summarize(report)
    assert (summary.projects, summary.direct, summary.transitive, summary.checked) == (2, 5, 0, 5)
    assert summary.findings == {
        FindingKind.VULNERABLE: 0,
        FindingKind.EOL: 0,
        FindingKind.YANKED: 1,
        FindingKind.DEPRECATED: 1,
        FindingKind.OUTDATED: 3,  # flask (une fois), requests, left-pad
        FindingKind.UNVERIFIABLE: 1,
        FindingKind.INCONCLUSIVE: 0,
    }
    assert summary.outdated == {Gap.MAJOR: 1, Gap.MINOR: 2, Gap.PATCH: 0}
    assert summary.to_update == 5


def test_rows_group_a_package_declared_twice(report: Report) -> None:
    api = report.projects[0]
    found = rows(api, report)
    assert [row.name for row in found] == ["requests", "flask", "sechunter-extra"]
    requests, flask, extra = found
    assert requests.states == ["retirée", "mineure"]
    assert (flask.constraint, flask.notes, flask.current) == ("==2.0.1", ("dev",), "2.0.1")
    assert (flask.wanted, flask.latest, flask.states) == ("2.0.1", "3.1.3", ["majeure"])
    assert extra.states == ["non vérifiable"]


def test_rows_of_an_inventory() -> None:
    project = Project(path=".", dependencies=[dependency("a", constraint=">=1")])
    (row,) = rows(project, Report(source=".", projects=[project]))
    assert (row.current, row.states, row.checked) == ("≈ 1", [], False)


def test_rows_say_up_to_date_and_hide_unchecked() -> None:
    project = Project(
        path=".",
        dependencies=[
            dependency("a", installed="1.0"),
            dependency("b", scope=Scope.DEV),
            dependency("c", unverifiable_reason="membre du workspace"),
        ],
    )
    report = Report(source=".", projects=[project], options=ScanOptions(dev=False))
    assert [(row.name, row.states) for row in rows(project, report)] == [
        ("a", ["à jour"]),
        ("c", ["non vérifiable : membre du workspace"]),
    ]


def test_indirect_rows_only_with_a_finding() -> None:
    old = dependency("x", installed="1.0", direct=False)
    project = Project(
        path=".",
        dependencies=[old, dependency("y", installed="1.0", direct=False)],
        findings=[
            Finding(
                kind=FindingKind.OUTDATED,
                message="",
                dependency=old,
                current_version="1.0",
                target_version="2.0",
                gap=Gap.MAJOR,
            )
        ],
    )
    report = Report(source=".", projects=[project], options=ScanOptions(transitive=True))
    assert [row.name for row in rows(project, report, direct=False)] == ["x"]
    assert rows(project, report) == []


# -- JSON ----------------------------------------------------------------------


def test_json(report: Report) -> None:
    data = json.loads(json_report.render(report))
    assert data["schema_version"] == 1
    assert data["tool"] == {"name": "forceupdate", "version": __version__}
    assert data["source"] == report.source
    assert data["options"] == {
        "include_tests": False,
        "dev": True,
        "transitive": False,
        "offline": False,
        "cache": True,
    }
    assert datetime.fromisoformat(data["scanned_at"]).tzinfo is not None
    assert data["ignored_manifests"] == ["tests/demo/package.json"]
    assert data["summary"]["findings"]["yanked"] == 1
    assert data["summary"]["outdated"] == {"major": 1, "minor": 2, "patch": 0}
    assert data["summary"]["to_update"] == 5
    api = data["projects"][0]
    assert api["notices"][0]["file"] == "api/setup.py"
    yanked = api["findings"][0]
    assert yanked["kind"] == "yanked"
    assert yanked["severity"] == "medium"
    assert yanked["target_version"] == "2.32.2"
    assert yanked["dependency"]["name"] == "requests"
    assert yanked["dependency"]["location"] == {"line": 3, "column": 41, "end_column": 49}
    assert set(yanked) == {
        "kind",
        "severity",
        "message",
        "dependency",
        "current_version",
        "current_is_approximate",
        "target_version",
        "wanted_version",
        "gap",
        "identifiers",
        "cvss_score",
        "detail",
        "url",
    }


def test_json_keeps_accents() -> None:
    text = json_report.render(Report(source="C:/Projets/évaluation"))
    assert '"source": "C:/Projets/évaluation"' in text
    assert text.endswith("}\n")


# -- Markdown ------------------------------------------------------------------


def test_markdown(report: Report) -> None:
    text = markdown.render(report)
    assert text.startswith("# Rapport forceupdate\n")
    assert "## Résumé" in text
    assert "- 5 à mettre à jour :" in text
    assert "  - 1 majeure\n  - 2 mineures\n" in text
    assert "## Projet `api` (PyPI)" in text
    assert "| `requests` | `==2.32.0` | 2.32.0 |  | 2.34.2 | retirée, mineure |" in text
    assert "| `flask` (dev) | `==2.0.1` | 2.0.1 | 2.0.1 | 3.1.3 | majeure |" in text
    # « || » ne coupe pas la cellule
    assert "| `left-pad` | `^1 \\|\\| ^2` | ≈ 1.0.0 |" in text
    assert "- **retirée** — `requests` : Version 2.32.0 retirée de PyPI" in text
    assert "### Remarques" in text
    assert "## Fichiers écartés" in text


def test_markdown_escapes_text() -> None:
    project = Project(
        path=".",
        notices=[Notice(file="a.txt", message="*gras* et [lien](x) | tube")],
    )
    text = markdown.render(Report(source=".", projects=[project]))
    assert r"- `a.txt` : \*gras\* et \[lien\]\(x\) \| tube" in text


# -- terminal ------------------------------------------------------------------


def render(report: Report) -> list[str]:
    buffer = io.StringIO()
    terminal.render(report, Console(file=buffer, width=200, color_system=None))
    return [line.rstrip() for line in buffer.getvalue().splitlines()]


def test_terminal(report: Report) -> None:
    lines = render(report)
    assert lines[0] == f"Source : {report.source}"
    assert lines[1].startswith("Analyse du ")
    assert "Projet api  (PyPI)" in lines
    table = [line.split() for line in lines]
    assert ["Paquet", "Contrainte", "Utilisée", "Permise", "Dernière", "État"] in table
    assert ["requests", "==2.32.0", "2.32.0", "2.34.2", "retirée,", "mineure"] in table
    assert ["flask", "(dev)", "==2.0.1", "2.0.1", "2.0.1", "3.1.3", "majeure"] in table
    assert [
        "left-pad",
        "^1",
        "||",
        "^2",
        "≈",
        "1.0.0",
        "1.3.0",
        "1.3.0",
        "déprécié,",
        "mineure",
    ] in table
    assert "  Détails" in lines
    assert "  Remarques" in lines
    assert [
        "non",
        "vérifiable",
        "sechunter-extra",
        ":",
        "sechunter-extra",
        "est",
        "introuvable",
        "sur",
        "PyPI",
        ":",
        "paquet",
        "privé,",
        "ou",
        "nom",
        "mal",
        "écrit",
        "?",
    ] in table
    assert lines[-1] == (
        "Résumé : 5 dépendances vérifiées, 5 à mettre à jour : 1 retirée, 1 déprécié, "
        "1 majeure, 2 mineures ; 1 non vérifiable."
    )


def test_terminal_is_not_fooled_by_markup() -> None:
    project = Project(path="[bold]x[/bold]", notices=[Notice(file="a", message="[red]b[/red]")])
    lines = render(Report(source="[link]", projects=[project]))
    assert "Source : [link]" in lines
    assert "Projet [bold]x[/bold]" in lines


def test_terminal_says_offline_data_date() -> None:
    report = Report(
        source=".",
        options=ScanOptions(offline=True),
        scanned_at=datetime(2026, 10, 27, 12, 0, tzinfo=UTC),
        oldest_data=datetime(2026, 10, 20, 9, 30, tzinfo=UTC),
        languages=[Language(name="Python", bytes=10, ecosystem=Ecosystem.PYPI)],
    )
    lines = render(report)
    oldest = datetime(2026, 10, 20, 9, 30, tzinfo=UTC).astimezone().strftime("%d/%m/%Y à %H:%M")
    assert lines[1].endswith(
        "hors ligne : données des registres et d'OSV prises dans le cache, la plus ancienne du "
        f"{oldest}."
    )
    assert lines[-1] == "Résumé : 0 dépendance vérifiée, rien à mettre à jour."


# -- failles -------------------------------------------------------------------


def vulnerable_report() -> Report:
    """Une directe en faille possible (sans lockfile), une indirecte en faille, une indirecte
    sans constat ; analysée sans ``--transitive``."""
    flask = dependency("flask", constraint=">=0.12")
    jinja2 = dependency("jinja2", installed="2.10", direct=False)
    project = Project(
        path=".",
        dependencies=[flask, jinja2, dependency("click", installed="7.0", direct=False)],
        findings=[
            Finding(
                kind=FindingKind.VULNERABLE,
                severity=Severity.HIGH,
                message="CVE-2018-1000656 (gravité élevée, CVSS 7,5) : … Faille possible : …",
                dependency=flask,
                current_version="0.12",
                current_is_approximate=True,
                target_version="0.12.3",
                identifiers=("CVE-2018-1000656",),
                cvss_score=7.5,
                url="https://osv.dev/vulnerability/GHSA-562c-5r94-xh97",
            ),
            Finding(
                kind=FindingKind.VULNERABLE,
                severity=Severity.HIGH,
                message="CVE-2019-10906 (gravité élevée, CVSS 8,6) : Jinja2 sandbox escape.",
                dependency=jinja2,
                current_version="2.10",
                target_version="2.10.1",
                identifiers=("CVE-2019-10906",),
                url="https://osv.dev/vulnerability/GHSA-462w-v97r-4m45",
            ),
        ],
    )
    return Report(source=".", projects=[project], options=ScanOptions())


def test_indirect_rows_show_vulnerabilities_without_transitive() -> None:
    report = vulnerable_report()
    project = report.projects[0]
    (flask,) = rows(project, report)
    assert (flask.current, flask.states) == ("≈ 0.12", ["faille possible"])
    (jinja2,) = rows(project, report, direct=False)  # click n'a pas de constat
    assert (jinja2.name, jinja2.current, jinja2.states) == ("jinja2", "2.10", ["faille"])


def test_summary_counts_the_dependencies_searched_for_vulnerabilities() -> None:
    summary = summarize(vulnerable_report())
    assert (summary.checked, summary.audited) == (1, 3)
    assert summary.findings[FindingKind.VULNERABLE] == 2
    assert summary.to_update == 2
    data = json.loads(json_report.render(vulnerable_report()))
    assert data["summary"]["audited"] == 3
    assert data["projects"][0]["findings"][0]["cvss_score"] == 7.5


def test_terminal_with_vulnerabilities() -> None:
    lines = render(vulnerable_report())
    assert "  Dépendances indirectes à signaler" in lines
    assert ["jinja2", "-", "2.10", "faille"] in [line.split() for line in lines]
    assert any(
        "faille possible flask : CVE-2018-1000656" in " ".join(line.split()) for line in lines
    )
    assert any(
        "faille jinja2 2.10 (indirecte) : CVE-2019-10906" in " ".join(line.split())
        for line in lines
    )
    assert lines[-1] == (
        "Résumé : 1 dépendance vérifiée, failles cherchées sur 3, 2 à mettre à jour : 2 failles."
    )


def test_markdown_with_vulnerabilities() -> None:
    text = markdown.render(vulnerable_report())
    assert "- 1 projet, 1 dépendance vérifiée, failles cherchées sur 3\n" in text
    assert "  - 2 failles\n" in text
    assert "### Dépendances indirectes à signaler" in text
    assert (
        "- **faille** — `jinja2` 2.10 (indirecte) : CVE-2019-10906 \\(gravité élevée, CVSS 8,6\\) "
        ": Jinja2 sandbox escape. [Avis](https://osv.dev/vulnerability/GHSA-462w-v97r-4m45)\n"
    ) in text
    assert "- **faille possible** — `flask` : CVE-2018-1000656" in text
