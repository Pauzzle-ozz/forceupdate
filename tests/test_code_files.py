"""Un fichier de code choisi seul (E28), de bout en bout, sur les réponses enregistrées : le
mini-projet ``tests/projects/scripts`` (un script à bloc PEP 723, un script verrouillé, des
imports en Python, TypeScript et Go) et un fichier du mini-projet ``eol`` (dans un projet).

Les fichiers sont copiés dans le dossier du test : dans le dépôt, un ``.py`` serait analysé à
travers le ``pyproject.toml`` de forceupdate lui-même."""

import asyncio
import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
import respx
from conftest import FakeTools
from typer.testing import CliRunner

from forceupdate import engine
from forceupdate.cli import app
from forceupdate.models import (
    CodeFile,
    CodeReading,
    FindingKind,
    Report,
    ScanOptions,
    Scope,
)
from forceupdate.net import Cache, HttpClient
from forceupdate.report import markdown, summarize
from forceupdate.sources import local
from forceupdate.sources.local import LocalSource

PROJECTS = Path(__file__).parent / "projects"
Routes = dict[str, respx.Route]
runner = CliRunner()


@pytest.fixture
def scripts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Une copie du mini-projet ``scripts`` ; la remontée des dossiers s'arrête au-dessus."""
    monkeypatch.setattr(local, "_home", lambda: tmp_path.resolve())
    return Path(shutil.copytree(PROJECTS / "scripts", tmp_path / "scripts"))


def analyze(path: Path, options: ScanOptions | None = None) -> Report:
    async def main() -> Report:
        async with HttpClient(offline=bool(options and options.offline)) as http:
            return await engine.analyze(
                LocalSource(path), options, http=http, cache=Cache.disabled()
            )

    return asyncio.run(main())


def kinds(report: Report) -> dict[str, list[FindingKind]]:
    found: dict[str, list[FindingKind]] = {}
    for finding in report.findings:
        if finding.dependency is not None:
            found.setdefault(finding.dependency.name, []).append(finding.kind)
    return found


# -- Un script avec seulement des imports ------------------------------------------------------


def test_python_imports(recorded: Routes, scripts: Path) -> None:
    report = analyze(scripts / "imports.py")
    assert report.code == CodeFile(
        path="imports.py", language="Python", reading=CodeReading.IMPORTS
    )
    (project,) = report.projects
    assert (project.path, project.manifests, project.lockfiles) == (".", ["imports.py"], [])
    # json et os : la bibliothèque standard ; helpers : posé à côté du script.
    assert [(d.name, d.imported, d.scope) for d in project.dependencies] == [
        ("requests", "requests", Scope.RUNTIME),
        ("python-dateutil", "dateutil", Scope.RUNTIME),
        ("flask", "flask", Scope.RUNTIME),
        ("jinja2", "jinja2", Scope.OPTIONAL),
    ]
    assert kinds(report) == {
        "requests": [FindingKind.UNPINNED],
        "python-dateutil": [FindingKind.UNPINNED],
        "flask": [FindingKind.UNPINNED],
        "jinja2": [FindingKind.UNPINNED],
    }
    dateutil = next(
        f for f in report.findings if f.dependency and f.dependency.name == "python-dateutil"
    )
    assert dateutil.message.startswith("Version non fixée (importé : dateutil) : la dernière est ")
    assert dateutil.target_version == "4.0.0"
    assert [n.message for n in project.notices] == [
        "Failles non vérifiables pour les 4 dépendances sans version fixée : OSV juge une version. "
        "Fixer les versions (un manifeste, un lockfile, un bloc PEP 723) pour qu'elles le soient."
    ]
    assert project.updates == []
    summary = summarize(report)
    assert (summary.to_update, summary.findings[FindingKind.UNPINNED], summary.audited) == (0, 4, 0)
    # Aucune version à soumettre à OSV.
    assert not recorded["osv:querybatch"].called


def test_python_imports_offline_are_inconclusive(recorded: Routes, scripts: Path) -> None:
    report = analyze(scripts / "imports.py", ScanOptions(offline=True))
    assert {kind for found in kinds(report).values() for kind in found} == {
        FindingKind.INCONCLUSIVE
    }


# -- Un script à bloc PEP 723 --------------------------------------------------------------------


def test_pep723_script(recorded: Routes, scripts: Path) -> None:
    report = analyze(scripts / "pep723.py")
    assert report.code == CodeFile(path="pep723.py", language="Python", reading=CodeReading.SCRIPT)
    (project,) = report.projects
    assert [(d.name, d.constraint, d.imported) for d in project.dependencies] == [
        ("flask", ">=0.12", None),
        ("requests", "", None),
    ]
    (runtime,) = project.runtimes
    assert (runtime.version, runtime.approximate, runtime.file) == ("3.11", True, "pep723.py")
    found = kinds(report)
    assert FindingKind.VULNERABLE in found["flask"] and FindingKind.OUTDATED in found["flask"]
    assert found["requests"] == [FindingKind.UNPINNED]
    (update,) = project.updates
    assert update.name == "flask"
    assert all(edit.file == "pep723.py" for option in update.options for edit in option.edits)


def test_update_rewrites_the_block_only(recorded: Routes, scripts: Path) -> None:
    script = scripts / "pep723.py"
    before = script.read_text(encoding="utf-8")
    result = runner.invoke(
        app,
        ["update", str(script), "--yes", "--no-cache", "--level", "major"],
        env={"COLUMNS": "200"},
    )
    assert result.exit_code == 0, result.output
    after = script.read_text(encoding="utf-8")
    changed = [
        (a, b) for a, b in zip(before.splitlines(), after.splitlines(), strict=True) if a != b
    ]
    assert len(changed) == 1
    old, new = changed[0]
    assert old == '#   "flask>=0.12",'
    assert new.startswith('#   "flask>=3.') and new.endswith('",')
    assert "Fichiers réécrits : pep723.py." in result.output


def test_locked_script(recorded: Routes, scripts: Path) -> None:
    report = analyze(scripts / "locked.py")
    (project,) = report.projects
    assert project.lockfiles == ["locked.py.lock"]
    flask = next(d for d in project.dependencies if d.name == "flask")
    assert (flask.installed, flask.lockfile) == ("2.3.0", "locked.py.lock")
    assert FindingKind.VULNERABLE in kinds(report)["flask"]


def test_locked_script_is_relocked_by_uv(
    recorded: Routes, scripts: Path, fake_tools: Callable[..., FakeTools]
) -> None:
    tools = fake_tools("uv")
    result = runner.invoke(
        app, ["update", str(scripts / "locked.py"), "--yes", "--no-cache"], env={"COLUMNS": "200"}
    )
    assert result.exit_code == 0, result.output
    (command,) = tools.commands()
    assert command.startswith("uv lock --script locked.py -P flask==2.3.")
    assert tools.calls[0].cwd == scripts.resolve()
    assert "locked.py.lock : régénéré (uv)." in result.output


# -- JavaScript, TypeScript, Go ------------------------------------------------------------------


def test_typescript_imports(recorded: Routes, scripts: Path) -> None:
    report = analyze(scripts / "index.ts")
    assert report.code is not None and report.code.reading is CodeReading.IMPORTS
    (project,) = report.projects
    assert [(d.name, d.imported, d.scope) for d in project.dependencies] == [
        ("lodash", "lodash/fp", Scope.RUNTIME),
        ("@hapi/joi", "@hapi/joi", Scope.RUNTIME),
        ("colors", "colors", Scope.DEV),
        ("left-pad", "left-pad", Scope.RUNTIME),
    ]
    found = kinds(report)
    assert found["lodash"] == [FindingKind.UNPINNED]
    assert FindingKind.DEPRECATED in found["@hapi/joi"]
    assert FindingKind.UNPINNED in found["left-pad"]


def test_go_imports_are_attached_to_their_module(recorded: Routes, scripts: Path) -> None:
    report = analyze(scripts / "main.go")
    (project,) = report.projects
    # golang.org/x/text/cases et …/language : un seul module, golang.org/x/text.
    assert [(d.name, d.imported) for d in project.dependencies] == [
        ("github.com/google/uuid", "github.com/google/uuid"),
        ("golang.org/x/text", "golang.org/x/text/cases"),
    ]
    assert kinds(report) == {
        "github.com/google/uuid": [FindingKind.UNPINNED],
        "golang.org/x/text": [FindingKind.UNPINNED],
    }


def test_go_import_without_a_module(recorded: Routes, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(local, "_home", lambda: tmp_path.resolve())
    main = tmp_path / "main.go"
    main.write_text('package main\n\nimport "example.com/nothing/here"\n', encoding="utf-8")
    report = analyze(main)
    (finding,) = report.findings
    assert finding.kind is FindingKind.UNVERIFIABLE
    assert finding.message == (
        "Non vérifiable : aucun paquet de proxy.golang.org ne fournit « example.com/nothing/here » "
        "(example.com/nothing/here, example.com/nothing, example.com : introuvables)."
    )


def test_import_without_a_package(recorded: Routes, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(local, "_home", lambda: tmp_path.resolve())
    script = tmp_path / "run.py"
    script.write_text("import notapackage\n", encoding="utf-8")
    (finding,) = analyze(script).findings
    assert finding.kind is FindingKind.UNVERIFIABLE
    assert "pour l'import « notapackage » : un module du projet" in finding.message


# -- Un fichier de code dans un projet -----------------------------------------------------------


def test_code_file_in_a_project(recorded: Routes, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(local, "_home", lambda: tmp_path.resolve())
    eol = Path(shutil.copytree(PROJECTS / "eol", tmp_path / "eol"))
    report = analyze(eol / "app" / "__init__.py")
    assert report.code == CodeFile(
        path="app/__init__.py",
        language="Python",
        reading=CodeReading.PROJECT,
        via=("pyproject.toml",),
    )
    (project,) = report.projects
    folder = analyze(eol).projects[0]
    assert project.manifests == folder.manifests
    assert project.runtime_files == folder.runtime_files
    assert [f.message for f in project.findings] == [f.message for f in folder.findings]


# -- La ligne de commande ------------------------------------------------------------------------


def test_scan_in_the_terminal(recorded: Routes, scripts: Path) -> None:
    result = runner.invoke(
        app, ["scan", str(scripts / "imports.py"), "--no-cache"], env={"COLUMNS": "200"}
    )
    assert result.exit_code == 0, result.output
    assert (
        "Fichier de code imports.py, sans projet autour : ses imports, sans version."
        in result.output
    )
    assert "python-dateutil (import dateutil)" in result.output
    assert "version non fixée" in result.output
    assert "rien à mettre à jour ; 4 versions non fixées." in result.output


def test_unpinned_never_fails_the_scan(recorded: Routes, scripts: Path) -> None:
    result = runner.invoke(
        app, ["scan", str(scripts / "imports.py"), "--no-cache", "--fail-on", "any"]
    )
    assert result.exit_code == 0, result.output


def test_scan_json_and_markdown(recorded: Routes, scripts: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["scan", str(scripts / "pep723.py"), "--no-cache", "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    document = json.loads(result.output)
    assert document["code"] == {
        "path": "pep723.py",
        "language": "Python",
        "reading": "script",
        "via": [],
    }
    assert document["summary"]["findings"]["unpinned"] == 1
    requests = next(d for d in document["projects"][0]["dependencies"] if d["name"] == "requests")
    assert requests["imported"] is None
    text = markdown.render(analyze(scripts / "pep723.py"))
    assert "tient lieu de manifeste" in text
    assert "- 1 version non fixée" in text


def test_a_local_namespace_package_is_not_a_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded: object
) -> None:
    """E34 : un dossier voisin sans ``__init__.py`` (PEP 420) est un module du projet."""
    monkeypatch.setattr(local, "_home", lambda: tmp_path.resolve())
    folder = tmp_path / "outil"
    (folder / "monlib").mkdir(parents=True)
    (folder / "monlib" / "aides.py").write_text("X = 1\n", encoding="utf-8")
    script = folder / "app.py"
    script.write_text("import monlib.aides\nimport requests\n", encoding="utf-8")
    report = analyze(script)
    (project,) = report.projects
    assert [d.name for d in project.dependencies] == ["requests"]
