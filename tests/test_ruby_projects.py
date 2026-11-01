"""Le mini-projet Ruby de ``tests/projects/`` : ``bundler``.

Son ``Gemfile.lock`` a été fait par Bundler 4.0.20 (voir ``tests/projects/README.md``). On y
vérifie l'inventaire, puis l'analyse (réponses enregistrées : fixture ``recorded``), le plan, et
``forceupdate scan`` et ``update`` en ligne de commande (``bundle`` simulé : ``fake_bundler``)."""

import asyncio
import shutil
from collections.abc import Callable
from pathlib import Path

import respx
from conftest import FakeTools
from fake_bundler import FakeBundler
from typer.testing import CliRunner

from forceupdate import engine
from forceupdate.cli import app
from forceupdate.models import EditKind, FindingKind, Gap, Project, Report, Scope
from forceupdate.net import Cache, HttpClient
from forceupdate.parsers import parse_lockfile
from forceupdate.parsers.base import REASON_LOCAL
from forceupdate.sources.local import LocalSource

PROJECT = Path(__file__).parent / "projects" / "bundler"
Routes = dict[str, respx.Route]
runner = CliRunner()


def scan(root: Path) -> dict[str, Project]:
    return {p.path: p for p in engine.inventory(LocalSource(root)).projects}


def analyze(root: Path) -> Report:
    async def main() -> Report:
        async with HttpClient() as http:
            return await engine.analyze(LocalSource(root), http=http, cache=Cache.disabled())

    return asyncio.run(main())


def test_every_location_points_at_its_constraint() -> None:
    """Chaque emplacement montre la contrainte ; plusieurs chaînes, avec leurs guillemets."""
    source = LocalSource(PROJECT)
    for project in scan(PROJECT).values():
        located = [d for d in project.dependencies if d.location is not None]
        assert located
        for dependency in located:
            text = source.read_text(dependency.file)
            assert text is not None and dependency.location is not None
            written = dependency.location.extract(text)
            assert written.replace('", "', ", ") == dependency.constraint


def test_the_bundler_mini_project() -> None:
    projects = scan(PROJECT)
    project = projects["."]
    assert (project.manifests, project.lockfiles) == (
        ["Gemfile", "demo.gemspec"],
        ["Gemfile.lock"],
    )
    directs = [
        (d.name, d.constraint, d.installed, d.scope, d.file)
        for d in project.dependencies
        if d.direct
    ]
    assert directs == [
        ("rack", "~> 2.2.3", "2.2.3", Scope.RUNTIME, "Gemfile"),
        ("nokogiri", ">= 1.19.0, < 1.20", "1.19.0", Scope.RUNTIME, "Gemfile"),
        ("puma", "5.6.4", "5.6.4", Scope.RUNTIME, "Gemfile"),
        ("sinatra", "~> 2.2", "2.2.2", Scope.RUNTIME, "Gemfile"),
        ("rake", "~> 13.0", "13.0.6", Scope.RUNTIME, "Gemfile"),
        ("tzinfo-data", "", "1.2026.6", Scope.RUNTIME, "Gemfile"),
        ("helper", "", "0.1.0", Scope.RUNTIME, "Gemfile"),
        ("rspec", "~> 3.10", "3.10.0", Scope.DEV, "Gemfile"),
        ("minitest", "~> 5.15", "5.26.1", Scope.DEV, "Gemfile"),
        ("mustermann", "~> 2.0", "2.0.0", Scope.RUNTIME, "demo.gemspec"),
        ("tilt", ">= 2.0.10", "2.0.10", Scope.RUNTIME, "demo.gemspec"),
        ("diff-lcs", "~> 1.4", "1.4.4", Scope.DEV, "demo.gemspec"),
    ]
    found = {d.name: d for d in project.dependencies}
    assert found["helper"].unverifiable_reason == REASON_LOCAL
    transitives = [(d.name, d.installed, d.scope) for d in project.dependencies if not d.direct]
    assert ("rspec-core", "3.10.1", Scope.DEV) in transitives
    assert ("json", "2.3.0", Scope.RUNTIME) in transitives  # tirée par helper
    assert len(transitives) == 11
    assert "demo" not in found  # la gem du projet lui-même
    assert {d.lockfile for d in project.dependencies if d.installed} == {"Gemfile.lock"}
    assert project.notices == []
    # La gem locale helper (path:) est résolue dans le Gemfile.lock de la racine.
    helper = projects["helper"]
    assert (helper.manifests, helper.lockfiles) == (["helper/helper.gemspec"], ["Gemfile.lock"])
    assert [(d.name, d.constraint, d.installed) for d in helper.dependencies] == [
        ("json", ">= 2.0", "2.3.0")
    ]


def vulnerabilities(project: Project, name: str) -> list[tuple[str, str | None]]:
    return [
        (f.identifiers[0], f.target_version)
        for f in project.findings
        if f.kind is FindingKind.VULNERABLE and f.dependency and f.dependency.name == name
    ]


def test_findings_of_the_bundler_mini_project(recorded: Routes) -> None:
    projects = {p.path: p for p in analyze(PROJECT).projects}
    project = projects["."]
    assert [len(vulnerabilities(project, n)) for n in ("rack", "nokogiri", "puma", "sinatra")] == [
        32,
        11,
        5,
        3,
    ]
    assert ("CVE-2022-30123", "2.2.3.1") in vulnerabilities(project, "rack")
    assert ("CVE-2024-26141", "2.2.8.1") in vulnerabilities(project, "rack")
    # nokogiri 1.19.0-x86_64-linux-gnu : la version sans sa plateforme, pour OSV.
    assert ("CVE-2026-79772", "1.19.1") in vulnerabilities(project, "nokogiri")
    outdated = {
        f.dependency.name: (f.target_version, f.wanted_version, f.gap)
        for f in project.findings
        if f.kind is FindingKind.OUTDATED and f.dependency
    }
    assert outdated["rack"] == ("3.2.8", "2.2.25", Gap.MAJOR)
    assert outdated["nokogiri"] == ("1.19.4", "1.19.4", Gap.PATCH)
    assert outdated["puma"] == ("8.0.2", "5.6.4", Gap.MAJOR)  # 5.6.4 exacte
    assert outdated["minitest"] == ("6.0.6", "5.27.0", Gap.MAJOR)
    assert outdated["mustermann"] == ("4.0.1", "2.0.2", Gap.MAJOR)
    assert "tzinfo-data" not in outdated
    assert [f.message for f in project.findings if f.kind is FindingKind.UNVERIFIABLE] == [
        "Non vérifiable : chemin local."
    ]
    (helper_json,) = [f for f in projects["helper"].findings if f.kind is FindingKind.OUTDATED]
    assert (helper_json.target_version, helper_json.gap) == ("3.1.0", Gap.MAJOR)


def test_plan_of_the_bundler_mini_project(recorded: Routes) -> None:
    projects = {p.path: p for p in analyze(PROJECT).projects}
    updates = {u.name: u for u in projects["."].updates}
    puma = updates["puma"]
    assert puma.selected == "5.6.9"
    option = puma.option("5.6.9")
    assert option is not None and option.lockfile == "Gemfile.lock"
    (edit,) = option.edits
    assert (edit.kind, edit.file, edit.old, edit.new) == (
        EditKind.DEPENDENCY,
        "Gemfile",
        "5.6.4",
        "5.6.9",
    )
    # rack : les failles et la dernière de ~> 2.2.3, par le lockfile seul.
    rack = updates["rack"]
    assert [o.version for o in rack.options] == ["2.2.23", "2.2.25", "3.2.8"]
    assert rack.selected == "2.2.25" and rack.option("2.2.25").edits == ()  # type: ignore[union-attr]
    (major,) = rack.option("3.2.8").edits  # type: ignore[union-attr]
    assert (major.old, major.new) == ("~> 2.2.3", "~> 3.2.8")
    # sinatra : une majeure qui corrige une faille garde ~> et ajoute un plancher.
    (floor,) = updates["sinatra"].option("4.2.1").edits  # type: ignore[union-attr]
    assert (floor.old, floor.new) == ("~> 2.2", "~> 4.2, >= 4.2.1")
    # Une dépendance du .gemspec.
    (gemspec,) = updates["mustermann"].option("4.0.1").edits  # type: ignore[union-attr]
    assert (gemspec.file, gemspec.old, gemspec.new) == ("demo.gemspec", "~> 2.0", "~> 4.0")
    # nokogiri, deux contraintes : 1.19.4 y est déjà.
    assert updates["nokogiri"].option("1.19.4").edits == ()  # type: ignore[union-attr]
    assert "helper" not in updates and "tzinfo-data" not in updates
    # json, de la gem locale : par le Gemfile.lock de la racine.
    (json_update,) = projects["helper"].updates
    assert json_update.selected == "2.21.2"
    assert json_update.option("2.21.2").lockfile == "Gemfile.lock"  # type: ignore[union-attr]


# -- en ligne de commande -------------------------------------------------------------------


def test_scan_of_the_bundler_mini_project(recorded: Routes) -> None:
    result = runner.invoke(app, ["scan", str(PROJECT), "--no-cache"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    rows = [line.split() for line in result.stdout.splitlines()]
    assert [
        "rack",
        "(Gemfile)",
        "~>",
        "2.2.3",
        "2.2.3",
        "2.2.25",
        "3.2.8",
        "faille,",
        "majeure",
    ] in rows
    assert [
        "nokogiri", "(Gemfile)", ">=", "1.19.0,", "<", "1.20", "1.19.0", "1.19.4", "1.19.4",
        "faille,", "correctif",
    ] in rows  # fmt: skip
    assert [
        "mustermann",
        "(demo.gemspec)",
        "~>",
        "2.0",
        "2.0.0",
        "2.0.2",
        "4.0.1",
        "majeure",
    ] in rows
    assert ["helper", "(Gemfile)", "-", "0.1.0", "non", "vérifiable"] in rows


def test_update_of_the_bundler_mini_project(
    recorded: Routes, tmp_path: Path, fake_tools: Callable[..., FakeTools]
) -> None:
    root = tmp_path / "bundler"
    shutil.copytree(PROJECT, root)
    tools = fake_tools("bundle")
    tools.handlers["bundle"] = FakeBundler()
    tools.watch(root / "Gemfile", root / "helper" / "helper.gemspec")
    included = ("--include", "rack", "--include", "puma", "--include", "json")
    result = runner.invoke(
        app, ["update", str(root), "--yes", *included, "--no-cache"], env={"COLUMNS": "200"}
    )
    assert result.exit_code == 0, result.output
    lines = [line.split() for line in result.stdout.splitlines()]
    start = lines.index(["Fichiers", "réécrits", ":", "Gemfile."])
    assert lines[start + 1 : start + 5] == [
        ["Gemfile.lock", ":", "régénéré", "(Bundler)."],
        ["puma", "5.6.9"],
        ["rack", "2.2.25"],
        ["json", "2.21.2"],
    ]
    assert tools.commands() == ["bundle lock", "bundle lock"]
    pinned, final = tools.calls
    assert 'gem "rack", "= 2.2.25"' in pinned.files["Gemfile"]
    assert 'add_dependency "json", "= 2.21.2"' in pinned.files["helper.gemspec"]
    assert 'gem "rack", "~> 2.2.3"' in final.files["Gemfile"]
    assert 'gem "puma", "5.6.9"' in final.files["Gemfile"]
    assert final.cwd == root
    lock = parse_lockfile("Gemfile.lock", (root / "Gemfile.lock").read_text(encoding="utf-8"))
    versions = {p.name: p.version for p in lock.packages}
    assert (versions["rack"], versions["puma"], versions["json"]) == ("2.2.25", "5.6.9", "2.21.2")
    output = " ".join(result.stdout.split())
    assert "Bundler exécute le Gemfile (c'est du Ruby)" in output
