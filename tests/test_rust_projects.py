"""Les mini-projets Rust de ``tests/projects/`` : ``cargo`` (un crate) et ``cargo-workspace``.

Leurs ``Cargo.lock`` ont été faits par cargo 1.99 (voir ``tests/projects/README.md``). On y vérifie
l'inventaire, puis l'analyse (réponses enregistrées : fixture ``recorded``), le plan, et
``forceupdate scan`` et ``update`` en ligne de commande (cargo simulé)."""

import asyncio
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
import respx
from conftest import FakeTools, ToolCall
from typer.testing import CliRunner

from forceupdate import engine
from forceupdate.cli import app
from forceupdate.models import EditKind, FindingKind, Gap, Project, Report, Scope
from forceupdate.net import Cache, HttpClient
from forceupdate.parsers.base import REASON_GIT, REASON_LOCAL
from forceupdate.parsers.rust import WORKSPACE_CONSTRAINT
from forceupdate.sources.local import LocalSource

PROJECTS = Path(__file__).parent / "projects"
CARGO, WORKSPACE = PROJECTS / "cargo", PROJECTS / "cargo-workspace"
RUNTIME, DEV, BUILD, OPTIONAL = Scope.RUNTIME, Scope.DEV, Scope.BUILD, Scope.OPTIONAL
Routes = dict[str, respx.Route]
runner = CliRunner()


def scan(root: Path) -> dict[str, Project]:
    return {project.path: project for project in engine.inventory(LocalSource(root)).projects}


def directs(project: Project) -> list[tuple[str, str, str | None, Scope]]:
    return [(d.name, d.constraint, d.installed, d.scope) for d in project.dependencies if d.direct]


def transitives(project: Project) -> dict[str, tuple[str | None, Scope]]:
    return {d.name: (d.installed, d.scope) for d in project.dependencies if not d.direct}


def analyze(root: Path) -> Report:
    async def main() -> Report:
        async with HttpClient() as http:
            return await engine.analyze(LocalSource(root), http=http, cache=Cache.disabled())

    return asyncio.run(main())


@pytest.mark.parametrize("root", [CARGO, WORKSPACE], ids=["cargo", "cargo-workspace"])
def test_every_location_points_at_its_constraint(root: Path) -> None:
    source = LocalSource(root)
    located = 0
    for project in engine.inventory(source).projects:
        for dependency in project.dependencies:
            if dependency.location is not None:
                text = source.read_text(dependency.file)
                assert text is not None
                assert dependency.location.extract(text) == dependency.constraint, dependency
                located += 1
    assert located > 0


def test_the_cargo_mini_project() -> None:
    (project,) = scan(CARGO).values()
    assert project.lockfiles == ["Cargo.lock"]
    assert directs(project) == [
        ("serde", "1.0.100", "1.0.150", RUNTIME),
        ("rand", "0.8", "0.8.8", RUNTIME),
        ("regex", "=1.5.4", "1.5.4", RUNTIME),
        ("time", "0.1", "0.1.45", OPTIONAL),
        ("log", "0.4.14", "0.4.14", RUNTIME),  # my-log = { package = "log", … }
        ("itoa", "", "1.0.11", RUNTIME),
        ("local-crate", "", None, RUNTIME),
        ("anyhow", "1.0", "1.0.75", RUNTIME),
        ("pretty_assertions", "1", "1.4.1", DEV),
        ("cc", "1.0", "1.10.0", BUILD),
        ("winapi", "0.3", "0.3.9", RUNTIME),  # [target.'cfg(windows)'.dependencies]
    ]
    reasons = {d.name: d.unverifiable_reason for d in project.dependencies if d.direct}
    assert reasons["itoa"] == REASON_GIT and reasons["local-crate"] == REASON_LOCAL
    found = [(d.name, d.installed, d.scope) for d in project.dependencies if not d.direct]
    assert len(found) == 25
    assert ("memchr", "2.8.3", RUNTIME) in found  # tirée par local-crate
    assert ("diff", "0.1.13", DEV) in found  # pretty_assertions
    assert ("shlex", "2.0.1", BUILD) in found  # cc
    # Deux versions de wasi : celle de time (facultative), celle de getrandom (rand).
    assert ("wasi", "0.10.0+wasi-snapshot-preview1", OPTIONAL) in found
    assert ("wasi", "0.11.1+wasi-snapshot-preview1", RUNTIME) in found
    assert [v for n, v, _ in found if n == "syn"] == ["1.0.109", "2.0.119"]
    assert project.notices == []


def test_the_cargo_workspace_mini_project() -> None:
    projects = scan(WORKSPACE)
    assert sorted(projects) == [".", "crates/app", "crates/core", "crates/excluded"]
    assert projects["."].dependencies == []
    app_, core, excluded = (projects[p] for p in ("crates/app", "crates/core", "crates/excluded"))
    assert app_.lockfiles == core.lockfiles == ["Cargo.lock"]
    assert [
        (d.name, d.constraint, d.resolved_constraint, d.installed)
        for d in app_.dependencies
        if d.direct
    ] == [
        ("core-lib", "", None, None),
        ("serde", WORKSPACE_CONSTRAINT, "1.0.150", "1.0.160"),
        ("anyhow", WORKSPACE_CONSTRAINT, "1.0.50", "1.0.75"),
        ("smallvec", WORKSPACE_CONSTRAINT, "=1.6.0", "1.6.0"),
        ("log", WORKSPACE_CONSTRAINT, "0.4", "0.4.17"),
    ]
    assert transitives(app_)["itoa"] == ("1.0.18", RUNTIME)  # par core-lib
    assert directs(core) == [
        ("serde", WORKSPACE_CONSTRAINT, "1.0.160", RUNTIME),
        ("log", WORKSPACE_CONSTRAINT, "0.4.17", RUNTIME),
        ("itoa", "1.0", "1.0.18", RUNTIME),
    ]
    # exclude = ["crates/excluded"] : ni le lockfile de la racine, ni son workspace.
    assert excluded.lockfiles == []
    assert directs(excluded) == [("log", "0.4.20", None, RUNTIME)]
    assert all(not p.notices for p in projects.values())


def vulnerabilities(report: Report, path: str, name: str) -> list[tuple[str, str | None]]:
    project = next(p for p in report.projects if p.path == path)
    return [
        (f.identifiers[0], f.target_version)
        for f in project.findings
        if f.kind is FindingKind.VULNERABLE and f.dependency and f.dependency.name == name
    ]


def test_findings_and_plan_of_the_cargo_mini_project(recorded: Routes) -> None:
    report = analyze(CARGO)
    assert vulnerabilities(report, ".", "regex") == [("CVE-2022-24713", "1.5.5")]
    assert vulnerabilities(report, ".", "time") == [("CVE-2020-26235", "0.2.23")]
    assert vulnerabilities(report, ".", "anyhow") == [("RUSTSEC-2026-0190", "1.0.103")]
    (project,) = report.projects
    outdated = {
        f.dependency.name: (f.target_version, f.wanted_version, f.gap)
        for f in project.findings
        if f.kind is FindingKind.OUTDATED and f.dependency
    }
    assert outdated["rand"] == ("0.10.3", "0.8.8", Gap.MAJOR)
    assert outdated["log"] == ("0.4.34", "0.4.34", Gap.PATCH)
    updates = {u.name: u for u in project.updates}
    # regex : =1.5.4 réécrite, la dernière mineure pré-cochée (elle corrige aussi la faille).
    regex = updates["regex"]
    assert regex.selected == "1.13.1"
    (edit,) = regex.option("1.13.1").edits  # type: ignore[union-attr]
    assert (edit.kind, edit.file, edit.old, edit.new) == (
        EditKind.DEPENDENCY,
        "Cargo.toml",
        "=1.5.4",
        "=1.13.1",
    )
    # anyhow et log : le lockfile seul ; time et rand : des majeures, jamais cochées.
    assert updates["anyhow"].selected == "1.0.104"
    assert updates["anyhow"].option("1.0.104").edits == ()  # type: ignore[union-attr]
    assert updates["log"].selected == "0.4.34"
    assert updates["time"].selected is None and updates["rand"].selected is None
    time = updates["time"].option("0.2.23")
    assert time is not None and [(e.old, e.new) for e in time.edits] == [("0.1", "0.2.23")]


def test_findings_and_plan_of_the_cargo_workspace(recorded: Routes) -> None:
    report = analyze(WORKSPACE)
    assert vulnerabilities(report, "crates/app", "smallvec") == [("CVE-2021-25900", "1.6.1")]
    app_ = next(p for p in report.projects if p.path == "crates/app")
    smallvec = next(u for u in app_.updates if u.name == "smallvec")
    assert smallvec.selected == "1.16.4"
    option = smallvec.option("1.16.4")
    assert option is not None
    (edit,) = option.edits
    assert (edit.kind, edit.file, edit.old, edit.new) == (
        EditKind.CATALOG,
        "crates/app/Cargo.toml",
        "=1.6.0",
        "=1.16.4",
    )
    assert option.lockfile == "Cargo.lock"


# -- en ligne de commande -------------------------------------------------------------------


def test_scan_of_the_cargo_mini_project(recorded: Routes) -> None:
    result = runner.invoke(app, ["scan", str(CARGO), "--no-cache"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    rows = [line.split() for line in result.stdout.splitlines()]
    assert ["regex", "=1.5.4", "1.5.4", "1.5.4", "1.13.1", "faille,", "mineure"] in rows
    assert ["log", "0.4.14", "0.4.14", "0.4.34", "0.4.34", "correctif"] in rows


def fake_cargo(fake_tools: Callable[..., FakeTools], root: Path) -> FakeTools:
    """Un faux cargo : chaque ``cargo update`` passe le lockfile aux versions choisies."""
    tools = fake_tools("cargo")

    def cargo(call: ToolCall) -> None:
        lock = root / "Cargo.lock"
        text = lock.read_text(encoding="utf-8")
        for name, old, new in (("regex", "1.5.4", "1.13.1"), ("anyhow", "1.0.75", "1.0.104")):
            before, after = f'"{name}"\nversion = "{old}"', f'"{name}"\nversion = "{new}"'
            text = text.replace(before, after)
        lock.write_text(text, encoding="utf-8")

    tools.handlers["cargo"] = cargo
    return tools


def test_update_of_the_cargo_mini_project(
    recorded: Routes, tmp_path: Path, fake_tools: Callable[..., FakeTools]
) -> None:
    root = tmp_path / "cargo"
    shutil.copytree(CARGO, root)
    tools = fake_cargo(fake_tools, root)
    result = runner.invoke(
        app,
        ["update", str(root), "--yes", "--include", "regex", "--include", "anyhow", "--no-cache"],
        env={"COLUMNS": "200"},
    )
    assert result.exit_code == 0, result.output
    lines = [line.strip() for line in result.stdout.splitlines()]
    assert lines[lines.index("Fichiers réécrits : Cargo.toml.") :][:4] == [
        "Fichiers réécrits : Cargo.toml.",
        "Cargo.lock : régénéré (Cargo).",
        "regex  1.13.1",
        "anyhow 1.0.104",
    ]
    assert [call.arguments for call in tools.calls] == [["update", "--workspace"]] * 2
    assert 'regex = "=1.13.1"' in (root / "Cargo.toml").read_text(encoding="utf-8")
