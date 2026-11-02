"""Le mini-projet .NET de ``tests/projects/nuget`` : une solution à gestion centrale
(``Directory.Packages.props``, ``Directory.Build.props``), deux projets aux ``packages.lock.json``
produits par le vrai ``dotnet restore`` (SDK .NET 10.0.403), et un ``packages.config``.

On y vérifie l'inventaire, puis l'analyse (réponses enregistrées : fixture ``recorded``), le plan,
et ``forceupdate scan`` et ``update`` en ligne de commande, ``dotnet`` simulé."""

import asyncio
import json
import shutil
from collections.abc import Callable
from pathlib import Path

import respx
from conftest import FakeTools, ToolCall
from typer.testing import CliRunner

from forceupdate import engine
from forceupdate.cli import app
from forceupdate.models import EditKind, FindingKind, Gap, Project, Report, Scope, Severity
from forceupdate.net import Cache, HttpClient
from forceupdate.sources.local import LocalSource
from forceupdate.update.planner import REFERENCE_WARNING

NUGET = Path(__file__).parent / "projects" / "nuget"
Routes = dict[str, respx.Route]
Tools = Callable[..., FakeTools]
runner = CliRunner()


def scan(root: Path) -> dict[str, Project]:
    return {p.path: p for p in engine.inventory(LocalSource(root)).projects}


def analyze(root: Path) -> Report:
    async def main() -> Report:
        async with HttpClient() as http:
            return await engine.analyze(LocalSource(root), http=http, cache=Cache.disabled())

    return asyncio.run(main())


def directs(project: Project) -> list[tuple[str, str, str | None, Scope, str]]:
    return [
        (d.name, d.constraint, d.installed, d.scope, d.file)
        for d in project.dependencies
        if d.direct
    ]


def test_every_location_points_at_its_version() -> None:
    source = LocalSource(NUGET)
    for project in scan(NUGET).values():
        for dependency in project.dependencies:
            if dependency.location is None:
                continue
            text = source.read_text(dependency.file)
            assert text is not None
            assert dependency.location.extract(text) == dependency.constraint


def test_the_mini_project() -> None:
    projects = scan(NUGET)
    assert sorted(projects) == [".", "legacy", "src/App", "src/App.Tests"]
    props, build = "Directory.Packages.props", "Directory.Build.props"
    assert directs(projects["src/App"]) == [
        ("Newtonsoft.Json", "12.0.1", "12.0.1", Scope.RUNTIME, props),
        ("Serilog", "2.10.0", "2.10.0", Scope.RUNTIME, build),
        ("Microsoft.AspNetCore.Http", "2.1.0", "2.1.0", Scope.RUNTIME, props),
        ("Microsoft.SourceLink.GitHub", "1.1.1", "1.1.1", Scope.BUILD, props),
        ("StyleCop.Analyzers", "1.1.118", "1.1.118", Scope.BUILD, props),
    ]
    assert all(d.lockfile == "src/App/packages.lock.json" for d in projects["src/App"].dependencies)
    tests = projects["src/App.Tests"]
    assert directs(tests)[3] == (
        "Newtonsoft.Json",
        "13.0.1",
        "13.0.1",
        Scope.DEV,
        "src/App.Tests/App.Tests.csproj",
    )
    # Ce que tire le projet référencé, dont les versions centrales (CentralTransitive).
    central = {d.name: (d.file, d.scope) for d in tests.dependencies if not d.direct and d.location}
    assert central == {
        "Microsoft.AspNetCore.Http": (props, Scope.DEV),
        "Serilog": (build, Scope.DEV),
    }
    # Le projet de Directory.Packages.props : les versions centrales, et l'analyseur global.
    assert [d.name for d in projects["."].dependencies] == [
        "Newtonsoft.Json",
        "Serilog",
        "Microsoft.AspNetCore.Http",
        "Microsoft.SourceLink.GitHub",
        "xunit",
        "xunit.runner.visualstudio",
        "Microsoft.NET.Test.Sdk",
        "StyleCop.Analyzers",
    ]
    legacy = {d.name: d for d in projects["legacy"].dependencies}
    assert (legacy["NUnit"].scope, legacy["NUnit"].excluded) == (
        Scope.DEV,
        ("(,3.0.0)", "[4.0.0,)"),
    )
    assert all(not p.notices for p in projects.values())


def findings(project: Project, kind: FindingKind) -> dict[str, list[str | None]]:
    found: dict[str, list[str | None]] = {}
    for finding in project.findings:
        if finding.kind is kind and finding.dependency is not None:
            found.setdefault(finding.dependency.name, []).append(finding.target_version)
    return found


def test_findings_of_the_mini_project(recorded: Routes) -> None:
    projects = {p.path: p for p in analyze(NUGET).projects}
    app_ = projects["src/App"]
    assert findings(app_, FindingKind.VULNERABLE) == {
        "System.Text.Encodings.Web": ["4.5.1"],
        "Microsoft.AspNetCore.Http": ["2.1.22"],
        "Newtonsoft.Json": ["13.0.1"],
    }
    outdated = {
        f.dependency.name: (f.target_version, f.wanted_version, f.gap)
        for f in app_.findings
        if f.kind is FindingKind.OUTDATED and f.dependency
    }
    # NuGet prend la plus basse version qui convient : la « permise » est l'utilisée.
    assert outdated["Newtonsoft.Json"] == ("13.0.4", "12.0.1", Gap.MAJOR)
    assert outdated["Microsoft.AspNetCore.Http"] == ("2.3.13", "2.1.0", Gap.MINOR)
    tests = projects["src/App.Tests"]
    assert findings(tests, FindingKind.DEPRECATED) == {"xunit": [None]}
    assert findings(tests, FindingKind.VULNERABLE) == {"Microsoft.AspNetCore.Http": ["2.1.22"]}
    legacy = projects["legacy"]
    assert findings(legacy, FindingKind.YANKED) == {"log4net": ["2.0.10"]}
    yanked = next(f for f in legacy.findings if f.kind is FindingKind.YANKED)
    assert yanked.message == (
        "Version 2.0.8 retirée de la liste de nuget.org par son auteur (non listée). La plus "
        "proche non retirée : 2.0.10."
    )
    nunit = next(
        f
        for f in legacy.findings
        if f.kind is FindingKind.OUTDATED and f.dependency.name == "NUnit"  # type: ignore[union-attr]
    )
    # allowedVersions="[3,4)" : la 4 n'est jamais proposée.
    assert (nunit.target_version, nunit.gap) == ("3.14.0", Gap.MINOR)
    log4net = next(
        f
        for f in legacy.findings
        if f.kind is FindingKind.OUTDATED and f.dependency.name == "log4net"  # type: ignore[union-attr]
    )
    # NuGet restaure une version non listée : elle reste la « permise ».
    assert log4net.wanted_version == "2.0.8"


def test_end_of_life_of_the_mini_project(recorded: Routes) -> None:
    # E27 : .NET 8 finit le 2026-11-10 (le jour des tests : 2026-11-01) ; les paquets
    # d'ASP.NET Core 2.1 suivent .NET Core 2.1, fini en 2021.
    projects = {p.path: p for p in analyze(NUGET).projects}
    app_ = projects["src/App"]
    ended = [f for f in app_.findings if f.kind is FindingKind.EOL]
    assert [(f.dependency and f.dependency.name, f.severity) for f in ended] == [
        ("Microsoft.AspNetCore.Http", Severity.MEDIUM),
        (None, Severity.LOW),
    ]
    assert ended[1].message == (
        ".NET 8 : fin de vie le 10/11/2026, dans moins de 6 mois. Lu dans src/App/App.csproj : "
        "<TargetFramework>net8.0</TargetFramework>. Cycle conseillé : 10 (LTS), dernière version "
        "10.0.13."
    )
    # net10.0 aussi dans le projet de tests : seul net8.0 finit bientôt. ASP.NET Core n'y est
    # qu'une indirecte (CentralTransitive) : pas vérifiée sans --transitive.
    tests = projects["src/App.Tests"]
    assert [f.eol.cycle for f in tests.findings if f.kind is FindingKind.EOL and f.eol] == ["8"]


def test_plan_of_the_mini_project(recorded: Routes) -> None:
    projects = {p.path: p for p in analyze(NUGET).projects}
    updates = {u.name: u for u in projects["src/App"].updates}
    newtonsoft = updates["Newtonsoft.Json"]
    assert newtonsoft.selected == "12.0.3"  # la faille n'est corrigée qu'en majeure
    (edit,) = newtonsoft.option("13.0.1").edits  # type: ignore[union-attr]
    assert (edit.file, edit.old, edit.new) == ("Directory.Packages.props", "12.0.1", "13.0.1")
    serilog = updates["Serilog"].option("2.12.0")
    assert serilog is not None and serilog.lockfile == "src/App/packages.lock.json"
    (edit,) = serilog.edits
    assert (edit.file, edit.old, edit.new) == ("Directory.Build.props", "2.10.0", "2.12.0")
    # Une indirecte ne monte pas en régénérant : elle est ajoutée au projet (E32), relue, puis
    # le lockfile est régénéré. La mineure qui corrige la faille est pré-cochée.
    encodings = updates["System.Text.Encodings.Web"]
    assert encodings.selected == "4.7.2"
    fix = encodings.option("4.5.1")
    assert fix is not None and fix.lockfile == "src/App/packages.lock.json"
    assert fix.manual is None
    (edit,) = fix.edits
    assert (edit.kind, edit.file, edit.old, edit.new) == (
        EditKind.REFERENCE,
        "src/App/App.csproj",
        "",
        "4.5.1",
    )
    assert REFERENCE_WARNING in fix.warnings
    # Une version centrale tirée par le projet référencé : réécrite là où elle est écrite.
    tests = {u.name: u for u in projects["src/App.Tests"].updates}
    http = tests["Microsoft.AspNetCore.Http"]
    assert not http.direct and http.selected == "2.3.13"
    (edit,) = http.option("2.3.13").edits  # type: ignore[union-attr]
    assert (edit.file, edit.new) == ("Directory.Packages.props", "2.3.13")
    legacy = {u.name: u for u in projects["legacy"].updates}
    assert legacy["log4net"].selected == "2.0.17"
    option = legacy["log4net"].option("2.0.17")
    assert option is not None and option.lockfile is None
    assert [(e.file, e.old, e.new) for e in option.edits] == [
        ("legacy/packages.config", "2.0.8", "2.0.17")
    ]


# -- en ligne de commande -------------------------------------------------------------------


def test_scan_of_the_mini_project(recorded: Routes) -> None:
    result = runner.invoke(app, ["scan", str(NUGET), "--no-cache"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    rows_ = [line.split() for line in result.stdout.splitlines()]
    assert ["Newtonsoft.Json", "(Directory.Packages.props)", "12.0.1", "12.0.1", "12.0.1",
            "13.0.4", "faille,", "majeure"] in rows_  # fmt: skip
    assert ["Serilog", "(Directory.Build.props)", "2.10.0", "2.10.0", "2.10.0", "4.4.0",
            "majeure"] in rows_  # fmt: skip
    assert ["log4net", "2.0.8", "2.0.8", "2.0.8", "3.5.0", "faille,", "retirée,",
            "majeure"] in rows_  # fmt: skip
    assert ["lockfiles", ":", "src/App/packages.lock.json"] in rows_


def restore(versions: dict[str, str]) -> Callable[[ToolCall], tuple[int, str, str] | None]:
    """Un faux ``dotnet`` : un SDK, et ``restore``, qui met ``versions`` dans le lockfile."""

    def run(call: ToolCall) -> tuple[int, str, str] | None:
        if call.arguments == ["--list-sdks"]:
            return 0, "10.0.403 [C:\\Program Files\\dotnet\\sdk]\n", ""
        lock = call.cwd / "packages.lock.json"
        data = json.loads(lock.read_text(encoding="utf-8"))
        for packages in data["dependencies"].values():
            for name, entry in packages.items():
                if name in versions:
                    entry["resolved"] = versions[name]
        lock.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return None

    return run


def test_update_of_the_mini_project(recorded: Routes, tmp_path: Path, fake_tools: Tools) -> None:
    root = tmp_path / "nuget"
    shutil.copytree(NUGET, root)
    tools = fake_tools("dotnet")
    tools.handlers["dotnet"] = restore({"Serilog": "2.12.0", "log4net": "2.0.17"})
    result = runner.invoke(
        app,
        [
            "update",
            str(root),
            "--yes",
            "--include",
            "Serilog",
            "--include",
            "log4net",
            "--no-cache",
        ],
        env={"COLUMNS": "200"},
    )
    assert result.exit_code == 0, result.output
    build = (root / "Directory.Build.props").read_text(encoding="utf-8")
    assert "<SerilogVersion>2.12.0</SerilogVersion>" in build
    config = (root / "legacy" / "packages.config").read_text(encoding="utf-8")
    assert '<package id="log4net" version="2.0.17"' in config
    # La propriété est lue par les deux projets : leurs deux lockfiles sont régénérés.
    assert [c for c in tools.commands() if "restore" in c] == [
        "dotnet restore App.csproj --force-evaluate -noAutoResponse -p:RestoreLockedMode=false",
        "dotnet restore App.Tests.csproj --force-evaluate -noAutoResponse "
        "-p:RestoreLockedMode=false",
    ]
    output = " ".join(result.stdout.split())
    assert "src/App/packages.lock.json : régénéré (dotnet)." in output
    after = scan(root)
    assert {d.installed for d in after["src/App.Tests"].dependencies if d.name == "Serilog"} == {
        "2.12.0"
    }
