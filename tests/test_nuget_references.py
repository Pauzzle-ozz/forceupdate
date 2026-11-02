"""Une indirecte NuGet en faille, ajoutée au projet (E32) : NuGet prend la plus basse version qui
convient, régénérer le lockfile ne la fait pas monter. La réécriture insère la ``PackageReference``
(ou, avec la gestion centrale, la ``PackageVersion`` et ``CentralPackageTransitivePinningEnabled``),
puis relit le fichier comme les autres. Vérifié avec le SDK .NET 10.0.403 : ``dotnet restore``
donne alors ``CentralTransitive`` 4.5.1."""

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import FakeTools, ToolCall

from forceupdate import engine
from forceupdate.models import (
    Edit,
    EditKind,
    Gap,
    Project,
    Report,
    Update,
    UpdateOption,
    UpdateReason,
)
from forceupdate.sources.local import LocalSource
from forceupdate.update import local, lockfiles, writers
from forceupdate.update.lockfiles import LockStatus
from forceupdate.update.writers import Choice
from forceupdate.update.writers.nuget import PINNING

NUGET = Path(__file__).parent / "projects" / "nuget"
MakeTree = Callable[..., Path]
ENCODINGS = "System.Text.Encodings.Web"


def copied(tmp_path: Path) -> Path:
    root = tmp_path / "nuget"
    shutil.copytree(NUGET, root)
    return root


def inventory(root: Path) -> tuple[LocalSource, Report]:
    source = LocalSource(root)
    return source, engine.inventory(source)


def added(project: Project, name: str, version: str, *, manifest: str | None = None) -> Choice:
    """L'indirecte ``name`` ajoutée au projet en ``version`` (``EditKind.REFERENCE``)."""
    (dependency,) = [d for d in project.dependencies if d.name == name and not d.direct][:1]
    if manifest is None:
        manifest = next(m for m in project.manifests if m.endswith("proj"))
    edit = Edit(kind=EditKind.REFERENCE, file=manifest, location=None, old="", new=version)
    option = UpdateOption(
        version=version,
        gap=Gap.PATCH,
        reasons=(UpdateReason.SECURITY_FIX,),
        edits=(edit,),
        lockfile=dependency.lockfile,
    )
    update = Update(
        id=name,
        ecosystem=dependency.ecosystem,
        name=name,
        direct=False,
        dependencies=(dependency,),
        current_version=dependency.installed,
        options=(option,),
    )
    return project, update, option


def project_of(report: Report, path: str) -> Project:
    return next(project for project in report.projects if project.path == path)


def test_central_management_gets_a_version_and_the_pinning(tmp_path: Path) -> None:
    root = copied(tmp_path)
    _, report = inventory(root)
    changes = writers.prepare(root, [added(project_of(report, "src/App"), ENCODINGS, "4.5.1")])
    assert changes.skipped == ()
    (change,) = changes.files
    assert change.path == "Directory.Packages.props"
    assert change.diff == (
        "--- a/Directory.Packages.props\n"
        "+++ b/Directory.Packages.props\n"
        "@@ -1,6 +1,7 @@\n"
        " <Project>\n"
        "   <PropertyGroup>\n"
        "     <ManagePackageVersionsCentrally>true</ManagePackageVersionsCentrally>\n"
        f"+    {PINNING}\n"
        "   </PropertyGroup>\n"
        "   <ItemGroup>\n"
        '     <PackageVersion Include="Newtonsoft.Json" Version="12.0.1" />\n'
        "@@ -10,6 +11,7 @@\n"
        '     <PackageVersion Include="xunit" Version="2.4.1" />\n'
        '     <PackageVersion Include="xunit.runner.visualstudio" Version="2.4.3" />\n'
        '     <PackageVersion Include="Microsoft.NET.Test.Sdk" Version="16.11.0" />\n'
        f'+    <PackageVersion Include="{ENCODINGS}" Version="4.5.1" />\n'
        "   </ItemGroup>\n"
        "   <ItemGroup>\n"
        '     <GlobalPackageReference Include="StyleCop.Analyzers" Version="1.1.118" />\n'
    )


def test_the_other_projects_of_the_props_are_regenerated(
    tmp_path: Path, fake_tools: Callable[..., object]
) -> None:
    """L'épinglage vaut pour tous les projets qui lisent ce ``Directory.Packages.props`` : leurs
    lockfiles sont régénérés aussi."""
    root = copied(tmp_path)
    source, report = inventory(root)
    tools = fake_tools("dotnet")
    tools.handlers["dotnet"] = lambda call: (
        (0, "10.0.403 [C:\\sdk]\n", "") if call.arguments == ["--list-sdks"] else None
    )  # type: ignore[attr-defined]
    changes = writers.prepare(root, [added(project_of(report, "src/App"), ENCODINGS, "4.5.1")])
    jobs = lockfiles.plan(source, report, changes)
    assert [(job.lockfile, job.reason) for job in jobs] == [
        ("src/App/packages.lock.json", None),
        ("src/App.Tests/packages.lock.json", "Directory.Packages.props a changé"),
    ]


def test_two_indirects_and_the_pinning_once(tmp_path: Path) -> None:
    """Deux indirectes ajoutées au même endroit : les deux lignes, et l'épinglage une fois."""
    root = copied(tmp_path)
    _, report = inventory(root)
    project = project_of(report, "src/App")
    other = next(d.name for d in project.dependencies if not d.direct and d.name != ENCODINGS)
    choices = [added(project, ENCODINGS, "4.5.1"), added(project, other, "9.9.9")]
    changes = writers.prepare(root, choices)
    assert changes.skipped == ()
    (change,) = changes.files
    assert change.after.count("CentralPackageTransitivePinningEnabled") == 2  # ouvrante, fermante
    assert f'<PackageVersion Include="{ENCODINGS}" Version="4.5.1" />' in change.after
    assert f'<PackageVersion Include="{other}" Version="9.9.9" />' in change.after


CSPROJ = """\
<Project Sdk="Microsoft.NET.Sdk">\r
\r
  <PropertyGroup>\r
    <TargetFramework>net8.0</TargetFramework>\r
    <RestorePackagesWithLockFile>true</RestorePackagesWithLockFile>\r
  </PropertyGroup>\r
\r
  <ItemGroup>\r
    <PackageReference Include="Microsoft.AspNetCore.Http" Version="2.1.0" />\r
    <PackageReference Include="Serilog">\r
      <Version>2.10.0</Version>\r
    </PackageReference>\r
  </ItemGroup>\r
\r
</Project>\r
"""

LOCK = """\
{
  "version": 1,
  "dependencies": {
    "net8.0": {
      "Microsoft.AspNetCore.Http": {
        "type": "Direct",
        "requested": "[2.1.0, )",
        "resolved": "2.1.0",
        "dependencies": {"System.Text.Encodings.Web": "4.5.0"}
      },
      "Serilog": {"type": "Direct", "requested": "[2.10.0, )", "resolved": "2.10.0"},
      "System.Text.Encodings.Web": {"type": "Transitive", "resolved": "4.5.0"}
    }
  }
}
"""


def test_without_central_management_a_package_reference(make_tree: MakeTree) -> None:
    """Après la dernière ``PackageReference`` (même à plusieurs lignes), à son indentation ; les
    fins de ligne CRLF gardées."""
    root = make_tree({"app/App.csproj": CSPROJ, "app/packages.lock.json": LOCK})
    _, report = inventory(root)
    changes = writers.prepare(root, [added(project_of(report, "app"), ENCODINGS, "4.5.1")])
    assert changes.skipped == ()
    (change,) = changes.files
    assert change.after == CSPROJ.replace(
        "    </PackageReference>\r\n",
        "    </PackageReference>\r\n"
        f'    <PackageReference Include="{ENCODINGS}" Version="4.5.1" />\r\n',
    )


def test_the_added_reference_is_read_back(
    make_tree: MakeTree, fake_tools: Callable[..., FakeTools]
) -> None:
    """Ajoutée au projet, l'indirecte en devient une directe : la relecture la retrouve
    (``dotnet restore`` simulé, comme le vrai : ``Direct``, ``requested`` ``[4.5.1, )``)."""
    root = make_tree({"app/App.csproj": CSPROJ, "app/packages.lock.json": LOCK})
    source, report = inventory(root)
    tools = fake_tools("dotnet")

    def dotnet(call: ToolCall) -> tuple[int, str, str] | None:
        if call.arguments == ["--list-sdks"]:
            return 0, "10.0.403 [C:\\sdk]\n", ""
        lock = call.cwd / "packages.lock.json"
        lock.write_text(
            LOCK.replace(
                '"System.Text.Encodings.Web": {"type": "Transitive", "resolved": "4.5.0"}',
                '"System.Text.Encodings.Web": {"type": "Direct", "requested": "[4.5.1, )", '
                '"resolved": "4.5.1"}',
            ).replace(
                '"System.Text.Encodings.Web": "4.5.0"', '"System.Text.Encodings.Web": "4.5.1"'
            ),
            encoding="utf-8",
        )
        return None

    tools.handlers["dotnet"] = dotnet
    changes = writers.prepare(root, [added(project_of(report, "app"), ENCODINGS, "4.5.1")])
    jobs = lockfiles.plan(source, report, changes)
    (result,) = local.apply(source, report, local.Prepared(changes=changes, jobs=jobs))
    assert result.status is LockStatus.REGENERATED, result.error
    (installed,) = result.installed
    assert (installed.versions, installed.reach) == (("4.5.1",), lockfiles.Reach.EXACT)


def test_a_project_without_reference_gets_an_item_group(make_tree: MakeTree) -> None:
    csproj = (
        '<Project Sdk="Microsoft.NET.Sdk">\n'
        "    <PropertyGroup>\n"
        "        <TargetFramework>net8.0</TargetFramework>\n"
        "    </PropertyGroup>\n"
        "    <ItemGroup>\n"
        '        <ProjectReference Include="..\\lib\\Lib.csproj" />\n'
        "    </ItemGroup>\n"
        "</Project>\n"
    )
    root = make_tree({"app/App.csproj": csproj, "app/packages.lock.json": LOCK})
    _, report = inventory(root)
    changes = writers.prepare(root, [added(project_of(report, "app"), ENCODINGS, "4.5.1")])
    assert changes.skipped == ()
    (change,) = changes.files
    assert change.after.endswith(
        "    </ItemGroup>\n"
        "    <ItemGroup>\n"
        f'        <PackageReference Include="{ENCODINGS}" Version="4.5.1" />\n'
        "    </ItemGroup>\n"
        "</Project>\n"
    )


def test_pinning_turned_off_and_an_existing_version(tmp_path: Path) -> None:
    """``CentralPackageTransitivePinningEnabled`` à ``false`` : la ``PackageVersion``, et une
    ``PackageReference`` sans version dans le projet. Une ``PackageVersion`` déjà là : à la
    main."""
    root = copied(tmp_path)
    props = root / "Directory.Packages.props"
    text = props.read_text(encoding="utf-8")
    props.write_text(
        text.replace(
            "</ManagePackageVersionsCentrally>\n",
            "</ManagePackageVersionsCentrally>\n    " + PINNING.replace("true", "false") + "\n",
        ),
        encoding="utf-8",
    )
    _, report = inventory(root)
    changes = writers.prepare(root, [added(project_of(report, "src/App"), ENCODINGS, "4.5.1")])
    assert changes.skipped == ()
    assert [change.path for change in changes.files] == [
        "Directory.Packages.props",
        "src/App/App.csproj",
    ]
    assert f'<PackageReference Include="{ENCODINGS}" />' in changes.files[1].after

    props.write_text(
        text.replace(
            "  </ItemGroup>\n",
            f'    <PackageVersion Include="{ENCODINGS}" Version="4.5.0" />\n  </ItemGroup>\n',
            1,
        ),
        encoding="utf-8",
    )
    _, report = inventory(root)
    changes = writers.prepare(root, [added(project_of(report, "src/App"), ENCODINGS, "4.5.1")])
    assert [s.reason for s in changes.skipped] == [
        f"Directory.Packages.props a déjà une PackageVersion de {ENCODINGS} : y écrire 4.5.1 à la "
        "main."
    ]


def test_an_insertion_that_does_not_read_back_is_refused(make_tree: MakeTree) -> None:
    """La dernière ``PackageReference`` et ``</ItemGroup>`` sur la même ligne : l'élément ajouté
    serait hors du groupe ; la relecture le voit, rien n'est écrit."""
    csproj = (
        "<Project>\n"
        '  <ItemGroup><PackageReference Include="Serilog" Version="2.10.0" /></ItemGroup>\n'
        "  <PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup>\n"
        "</Project>\n"
    )
    root = make_tree({"app/App.csproj": csproj, "app/packages.lock.json": LOCK})
    _, report = inventory(root)
    changes = writers.prepare(root, [added(project_of(report, "app"), ENCODINGS, "4.5.1")])
    assert changes.files == ()
    (skipped,) = changes.skipped
    assert skipped.reason.startswith(
        "app/App.csproj : une fois réécrit, il ne lit pas ce qui est ajouté"
    )


@pytest.mark.network
def test_the_real_dotnet_restores_the_added_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le vrai SDK .NET : la ``PackageVersion`` et l'épinglage ajoutés, ``dotnet restore`` donne
    ``CentralTransitive`` 4.5.1 (les paquets dans le dossier du test)."""
    dotnet = shutil.which("dotnet")
    if dotnet is None:
        pytest.skip("dotnet n'est pas installé")
    sdks = subprocess.run([dotnet, "--list-sdks"], capture_output=True, text=True, timeout=60)
    if not sdks.stdout.strip():
        pytest.skip("le SDK .NET n'est pas installé")
    monkeypatch.setenv("NUGET_PACKAGES", str(tmp_path / "packages"))
    monkeypatch.setenv("DOTNET_CLI_HOME", str(tmp_path / "home"))
    root = copied(tmp_path)
    source, report = inventory(root)
    choice = added(project_of(report, "src/App"), ENCODINGS, "4.5.1")
    changes = writers.prepare(root, [choice])
    jobs = lockfiles.plan(source, report, changes)
    results = local.apply(source, report, local.Prepared(changes=changes, jobs=jobs))
    assert [r.status for r in results] == [LockStatus.REGENERATED, LockStatus.REGENERATED], [
        r.error for r in results
    ]
    lock = (root / "src" / "App" / "packages.lock.json").read_text(encoding="utf-8")
    entry = lock[lock.index(f'"{ENCODINGS}": {{') :]
    assert '"type": "CentralTransitive"' in entry[:200] and '"resolved": "4.5.1"' in entry[:300]
    (installed,) = results[0].installed
    assert installed.reach is lockfiles.Reach.EXACT
