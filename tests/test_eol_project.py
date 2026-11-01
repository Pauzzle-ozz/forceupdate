"""Le mini-projet ``tests/projects/eol`` (E27) : Python 3.8, Django 3.2 et Node.js 16, trois fins
de vie datées et justes, dans le rapport et en ligne de commande ; et ce qui arrive quand
endoflife.date ne répond pas."""

import asyncio
import json
from datetime import date
from pathlib import Path

import respx
from typer.testing import CliRunner

from forceupdate import engine
from forceupdate.cli import app
from forceupdate.models import FindingKind, Gap, Report, ScanOptions, Severity, UpdateReason
from forceupdate.net import Cache, HttpClient
from forceupdate.report import markdown
from forceupdate.sources.local import LocalSource

PROJECT = Path(__file__).parent / "projects" / "eol"
Routes = dict[str, respx.Route]
runner = CliRunner()


def analyze(root: Path = PROJECT, options: ScanOptions | None = None) -> Report:
    async def main() -> Report:
        async with HttpClient(offline=bool(options and options.offline)) as http:
            return await engine.analyze(
                LocalSource(root), options, http=http, cache=Cache.disabled()
            )

    return asyncio.run(main())


def test_three_dated_end_of_life_findings(recorded: Routes) -> None:
    (project,) = analyze().projects
    ended = [f for f in project.findings if f.kind is FindingKind.EOL]
    assert [f.message for f in ended] == [
        "Python 3.8 : fin de vie depuis le 07/10/2024. Lu dans .python-version : 3.8. Cycle "
        "conseillé : 3.15, dernière version 3.15.2.",
        "Node.js 16 : fin de vie depuis le 11/09/2023. Lu dans .nvmrc : 16. Cycle conseillé : 26 "
        "(LTS), dernière version 26.13.0.",
        "Django 3.2 : fin de vie depuis le 01/04/2024. Cycle conseillé : 5.2 (LTS), dernière "
        "version 5.2.18, qui demande Python >=3.10 ; le projet : 3.8 et plus (pyproject.toml). "
        "Changer de Python d'abord.",
    ]
    assert {f.severity for f in ended} == {Severity.MEDIUM}
    python, node, django = ended
    assert (python.dependency, node.dependency) == (None, None)
    assert django.dependency is not None and django.dependency.name == "django"
    assert [f.eol.ends_on for f in ended if f.eol] == [
        date(2024, 10, 7),
        date(2023, 9, 11),
        date(2024, 4, 1),
    ]
    # Les failles d'abord, puis les fins de vie, puis les plus récentes (décision n°8).
    kinds = [f.kind for f in project.findings]
    assert kinds.index(FindingKind.EOL) > max(
        i for i, k in enumerate(kinds) if k is FindingKind.VULNERABLE
    )
    assert kinds.index(FindingKind.OUTDATED) > max(
        i for i, k in enumerate(kinds) if k is FindingKind.EOL
    )


def test_versions_the_runtime_cannot_run_are_not_proposed(recorded: Routes) -> None:
    (project,) = analyze().projects
    outdated = {
        f.dependency.name: f
        for f in project.findings
        if f.kind is FindingKind.OUTDATED and f.dependency
    }
    # Django 5 demande Python 3.10 ; le projet accepte 3.8 : la plus haute qui convient est 4.2.
    assert (outdated["django"].target_version, outdated["django"].gap) == ("4.2.30", Gap.MAJOR)
    assert outdated["django"].message.endswith(
        "La 6.1.2 n'est pas proposée : elle demande Python >=3.12 ; le projet : 3.8 et plus "
        "(pyproject.toml)."
    )
    assert outdated["p-limit"].target_version == "4.0.0"
    assert outdated["p-limit"].message.endswith(
        "La 7.3.3 n'est pas proposée : elle demande Node.js >=20 ; le projet : 16 et plus "
        "(package.json)."
    )
    updates = {u.name: u for u in project.updates}
    assert [o.version for o in updates["django"].options] == ["4.2.30"]
    assert updates["django"].note == (
        "La correction de toutes ses failles (5.2.17) n'est pas proposée : elle demande Python "
        ">=3.10 ; le projet : 3.8 et plus (pyproject.toml)."
    )
    assert [o.version for o in updates["p-limit"].options] == ["4.0.0"]
    # Un runtime n'a pas de mise à jour.
    assert {u.name for u in project.updates} == {"django", "p-limit"}


def test_scan_on_the_command_line(recorded: Routes) -> None:
    result = runner.invoke(app, ["scan", str(PROJECT), "--no-cache"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    text = " ".join(result.stdout.split())
    assert "runtimes : Python 3.8 (.python-version), Node.js 16 (.nvmrc)" in text
    assert "fin de vie Python 3.8 : fin de vie depuis le 07/10/2024." in text
    assert "fin de vie Node.js 16 : fin de vie depuis le 11/09/2023." in text
    assert "fin de vie django : Django 3.2 : fin de vie depuis le 01/04/2024." in text
    assert "3 fins de vie" in text
    # --fail-on major : une fin de vie compte.
    failing = runner.invoke(app, ["scan", str(PROJECT), "--no-cache", "--fail-on", "major"])
    assert failing.exit_code == 1


def test_scan_in_json(recorded: Routes) -> None:
    result = runner.invoke(app, ["scan", str(PROJECT), "--no-cache", "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["summary"]["findings"]["eol"] == 3
    (project,) = data["projects"]
    assert project["runtime_files"] == [".nvmrc", ".python-version", "Dockerfile"]
    assert project["runtimes"][0] == {
        "product": "python",
        "version": "3.8",
        "approximate": True,
        "file": "pyproject.toml",
        "source": 'requires-python = ">=3.8"',
    }
    python = next(f for f in project["findings"] if f["kind"] == "eol")
    assert python["eol"] == {
        "product": "python",
        "label": "Python",
        "cycle": "3.8",
        "ends_on": "2024-10-07",
        "passed": True,
        "advised_cycle": "3.15",
        "advised_version": "3.15.2",
        "advised_lts": False,
        "advised_blocked": None,
        "runtime": {
            "product": "python",
            "version": "3.8",
            "approximate": False,
            "file": ".python-version",
            "source": "3.8",
        },
    }
    assert python["url"] == "https://endoflife.date/python"


def test_markdown(recorded: Routes) -> None:
    text = markdown.render(analyze())
    assert "- Runtimes : Python 3.8 \\(.python-version\\), Node.js 16 \\(.nvmrc\\)" in text
    assert "- **fin de vie** — Python 3.8 : fin de vie depuis le 07/10/2024." in text
    assert "- **fin de vie** — `django` : Django 3.2 : fin de vie depuis le 01/04/2024." in text


def test_offline_without_cache_is_inconclusive(recorded: Routes) -> None:
    (project,) = analyze(options=ScanOptions(offline=True, cache=False)).projects
    assert not [f for f in project.findings if f.kind is FindingKind.EOL]
    messages = [f.message for f in project.findings if f.kind is FindingKind.INCONCLUSIVE]
    assert (
        "Fin de vie de Python 3.8 non vérifiée. endoflife.date : mode hors ligne, et python "
        "n'est pas dans le cache."
    ) in messages
    assert any(m.startswith("Fin de vie de Node.js 16 non vérifiée.") for m in messages)


def test_endoflife_down_is_inconclusive(recorded: Routes) -> None:
    recorded["endoflife:django"].respond(503)
    (project,) = analyze().projects
    django = [
        f
        for f in project.findings
        if f.dependency is not None
        and f.dependency.name == "django"
        and f.message.startswith("Fin de vie")
    ]
    assert [(f.kind, f.message.split(". ")[0]) for f in django] == [
        (FindingKind.INCONCLUSIVE, "Fin de vie de django 3.2.25 non vérifiée")
    ]
    # Les runtimes, eux, sont vérifiés.
    assert len([f for f in project.findings if f.kind is FindingKind.EOL]) == 2


def test_supported_cycle_of_a_framework(recorded: Routes) -> None:
    root = Path(__file__).parent / "projects" / "maven"
    project = next(p for p in analyze(root).projects if p.path == "app")
    spring = next(f for f in project.findings if f.kind is FindingKind.EOL)
    assert spring.message == (
        "Spring Framework 5.3 : fin de vie depuis le 31/08/2024. Cycle conseillé : 7.0, "
        "dernière version 7.0.10."
    )
    update = next(u for u in project.updates if u.name == "org.springframework:spring-webmvc")
    option = update.option("7.0.10")
    assert option is not None
    assert option.reasons == (UpdateReason.LATEST_MAJOR, UpdateReason.SUPPORTED_CYCLE)
    assert update.selected == "5.3.39"  # une majeure n'est jamais pré-cochée
