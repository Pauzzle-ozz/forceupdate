"""Le parseur NuGet : ``packages.config``, les projets MSBuild, ``Directory.Packages.props``,
``Directory.Build.props`` et ``packages.lock.json`` ; et la position des attributs XML."""

import json

import pytest

from forceupdate import parsers
from forceupdate.detect.manifests import ecosystem_for_manifest, find_projects
from forceupdate.models import Dependency, Ecosystem, Location, Notice, Project, Scope
from forceupdate.parsers.base import ParseError
from forceupdate.parsers.nuget import (
    REASON_EXPRESSION,
    REASON_NO_CENTRAL,
    REASON_NO_VERSION,
    parse_packages_config,
    parse_packages_lock_json,
    read_msbuild,
)
from forceupdate.parsers.xml_spans import parse


def project(files: dict[str, str]) -> Project:
    """Le projet du dossier de premier niveau qui a un manifeste NuGet (``.`` sinon), lu."""
    projects, _ = find_projects(list(files))
    found = {p.path: p for p in projects}
    for item in projects:
        parsers.parse_project(item, files.get)
    return found


def rows(found: Project) -> list[tuple[str, str, str | None, Scope, str]]:
    return [(d.name, d.constraint, d.installed, d.scope, d.file) for d in found.dependencies]


def at(text: str, dependency: Dependency) -> str:
    assert dependency.location is not None
    return dependency.location.extract(text)


# ---------------------------------------------------------------------------
# Les attributs XML
# ---------------------------------------------------------------------------


class TestAttributeLocations:
    def test_each_value_written_as_is(self) -> None:
        text = (
            '﻿<Project>\n  <PackageReference Include="Newtonsoft.Json" Version="12.0.1" />\n'
            "  <PackageReference\n      Include='Serilog'   Version = \"2.10.0\"/>\n</Project>\n"
        )
        first, second = parse(text).children
        assert first.attribute_locations == {
            "Include": Location(line=2, column=29, end_column=44),
            "Version": Location(line=2, column=55, end_column=61),
        }
        assert [loc.extract(text) for loc in second.attribute_locations.values()] == [
            "Serilog",
            "2.10.0",
        ]

    def test_values_that_xml_transforms_have_none(self) -> None:
        text = '<a b="x&amp;y" c="" d="t\tu" e="ü" f="1\n2" />'
        element = parse(text)
        assert sorted(element.attribute_locations) == ["c", "e"]
        assert element.attribute_locations["c"] == Location(line=1, column=18, end_column=18)
        assert element.attribute_locations["e"].extract(text) == "ü"


# ---------------------------------------------------------------------------
# packages.config
# ---------------------------------------------------------------------------

PACKAGES_CONFIG = """<?xml version="1.0" encoding="utf-8"?>
<packages>
  <package id="log4net" version="2.0.8" targetFramework="net472" />
  <package version="9.0.1" id="Newtonsoft.Json" />
  <package id="NUnit" version="3.12.0" developmentDependency="true" allowedVersions="[3,4)" />
  <package id="Exact" version="1.0" allowedVersions="(1.0,2.0]" />
  <package id="" version="1.0" />
</packages>
"""


class TestPackagesConfig:
    def test_reference_mapping(self) -> None:
        # Repris de reference/argos_sca_parsers_tests.py (TestEcosystemMapping).
        assert ecosystem_for_manifest("packages.config") is Ecosystem.NUGET

    def test_packages(self) -> None:
        found = parse_packages_config("packages.config", PACKAGES_CONFIG)
        assert [(d.name, d.constraint, d.installed, d.scope) for d in found] == [
            ("log4net", "2.0.8", "2.0.8", Scope.RUNTIME),
            ("Newtonsoft.Json", "9.0.1", "9.0.1", Scope.RUNTIME),
            ("NUnit", "3.12.0", "3.12.0", Scope.DEV),
            ("Exact", "1.0", "1.0.0", Scope.RUNTIME),
        ]
        assert all(at(PACKAGES_CONFIG, d) == d.constraint for d in found)

    def test_allowed_versions_exclude_the_rest(self) -> None:
        found = {d.name: d for d in parse_packages_config("packages.config", PACKAGES_CONFIG)}
        assert found["NUnit"].excluded == ("(,3.0.0)", "[4.0.0,)")
        assert found["Exact"].excluded == ("(,1.0.0]", "(2.0.0,)")
        assert found["log4net"].excluded == ()

    def test_invalid(self) -> None:
        with pytest.raises(ParseError, match="XML invalide"):
            parse_packages_config("packages.config", "<packages>")
        with pytest.raises(ParseError, match=r"pas un packages\.config"):
            parse_packages_config("packages.config", "<package />")


# ---------------------------------------------------------------------------
# Un projet MSBuild seul
# ---------------------------------------------------------------------------

CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <SerilogVersion>2.10.0</SerilogVersion>
    <Nested>$(SerilogVersion)</Nested>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Newtonsoft.Json" Version="12.0.1" />
    <PackageReference Include="Serilog" Version="$(Nested)" />
    <PackageReference Include="Polly">
      <Version>7.2.3</Version>
    </PackageReference>
    <PackageReference Include="StyleCop.Analyzers" Version="1.1.118" PrivateAssets="All" />
    <PackageReference Include="SourceLink">
      <Version>1.1.1</Version>
      <PrivateAssets>analyzers;all</PrivateAssets>
    </PackageReference>
    <PackageReference Include="Float" Version="1.*" />
    <PackageReference Include="Missing" Version="$(Nowhere)" />
    <PackageReference Include="Computed" Version="$([System.String]::Copy('1.0'))" />
    <PackageReference Include="NoVersion" />
    <PackageReference Update="Newtonsoft.Json" Version="13.0.1" />
    <PackageReference Remove="Gone" />
    <ProjectReference Include="..\\Lib\\Lib.csproj" />
  </ItemGroup>
</Project>
"""


class TestMsBuildProject:
    def test_references_versions_and_their_location(self) -> None:
        found = project({"App.csproj": CSPROJ})["."]
        # L'Update=, après l'Include, change sa version (E34, comme MSBuild).
        assert rows(found) == [
            ("Newtonsoft.Json", "13.0.1", "13.0.1", Scope.RUNTIME, "App.csproj"),
            ("Serilog", "2.10.0", "2.10.0", Scope.RUNTIME, "App.csproj"),
            ("Polly", "7.2.3", "7.2.3", Scope.RUNTIME, "App.csproj"),
            ("StyleCop.Analyzers", "1.1.118", "1.1.118", Scope.BUILD, "App.csproj"),
            ("SourceLink", "1.1.1", "1.1.1", Scope.BUILD, "App.csproj"),
            ("Float", "1.*", None, Scope.RUNTIME, "App.csproj"),
            ("Missing", "$(Nowhere)", None, Scope.RUNTIME, "App.csproj"),
            ("Computed", "$([System.String]::Copy('1.0'))", None, Scope.RUNTIME, "App.csproj"),
            ("NoVersion", "", None, Scope.RUNTIME, "App.csproj"),
        ]
        located = [d for d in found.dependencies if d.location is not None]
        assert [at(CSPROJ, d) for d in located] == [
            "13.0.1",
            "2.10.0",
            "7.2.3",
            "1.1.118",
            "1.1.1",
            "1.*",
        ]
        assert located[1].location == Location(line=4, column=20, end_column=26)
        reasons = {d.name: d.unverifiable_reason for d in found.dependencies}
        assert reasons["Missing"] == "propriété $(Nowhere) introuvable"
        assert reasons["Computed"] == REASON_EXPRESSION
        assert reasons["NoVersion"] == REASON_NO_VERSION
        assert found.notices == []

    def test_read_alone(self) -> None:
        file = read_msbuild("App.csproj", CSPROJ)
        assert [(i.kind, i.name, i.version, i.private) for i in file.items][:3] == [
            ("reference", "Newtonsoft.Json", "12.0.1", False),
            ("reference", "Serilog", "$(Nested)", False),
            ("reference", "Polly", "7.2.3", False),
        ]
        assert [p.name for p in file.properties] == ["TargetFramework", "SerilogVersion", "Nested"]
        assert file.updates == ("Newtonsoft.Json",)

    def test_not_a_project(self) -> None:
        with pytest.raises(ParseError, match="pas un fichier MSBuild"):
            read_msbuild("App.csproj", "<packages />")
        found = project({"App.csproj": "<Project>"})["."]
        assert found.dependencies == []
        assert found.notices[0].file == "App.csproj"
        assert "XML invalide" in found.notices[0].message

    def test_conditions(self) -> None:
        text = """<Project>
  <PropertyGroup>
    <A>1.0.0</A>
    <A Condition="'$(Configuration)' == 'Debug'">2.0.0</A>
    <B Condition=" '$(B)' == '' ">3.0.0</B>
    <C>4.0.0</C>
    <C Condition="'$(C)'==''">5.0.0</C>
  </PropertyGroup>
  <PropertyGroup Condition="'$(TargetFramework)' == 'net48'">
    <D>6.0.0</D>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="UsesA" Version="$(A)" />
    <PackageReference Include="UsesB" Version="$(B)" />
    <PackageReference Include="UsesC" Version="$(C)" />
    <PackageReference Include="UsesD" Version="$(D)" />
  </ItemGroup>
  <ItemGroup Condition="'$(TargetFramework)' == 'net48'">
    <PackageReference Include="OnlyNet48" Version="1.0.0" />
  </ItemGroup>
  <Choose>
    <When Condition="'$(X)' == 'y'">
      <ItemGroup><PackageReference Include="InWhen" Version="1.0.0" /></ItemGroup>
    </When>
  </Choose>
</Project>
"""
        found = project({"App.csproj": text})["."]
        versions = {d.name: (d.constraint, d.unverifiable_reason) for d in found.dependencies}
        uncertain = "propriété $(A) définie sous condition (Condition=…)"
        assert versions == {
            "UsesA": ("$(A)", uncertain),
            "UsesB": ("3.0.0", None),
            "UsesC": ("4.0.0", None),
            "UsesD": ("$(D)", "propriété $(D) définie sous condition (Condition=…)"),
            "OnlyNet48": ("1.0.0", None),
            "InWhen": ("1.0.0", None),
        }
        assert [n.message for n in found.notices] == [
            "conditions MSBuild (Condition=…) non évaluées : ses références conditionnelles sont "
            "lues comme toujours présentes."
        ]

    def test_a_test_project_is_dev(self) -> None:
        text = (
            '<Project><ItemGroup><PackageReference Include="Microsoft.NET.Test.Sdk" '
            'Version="17.0.0" /><PackageReference Include="xunit" Version="2.4.1" />'
            "</ItemGroup></Project>"
        )
        found = project({"Tests.csproj": text})["."]
        assert {d.scope for d in found.dependencies} == {Scope.DEV}
        flagged = text.replace(
            "<Project>",
            "<Project><PropertyGroup><IsTestProject>true</IsTestProject></PropertyGroup>",
        )
        flagged = flagged.replace("Microsoft.NET.Test.Sdk", "Other")
        assert {d.scope for d in project({"Tests.fsproj": flagged})["."].dependencies} == {
            Scope.DEV
        }

    def test_several_names_in_one_include(self) -> None:
        text = (
            '<Project><ItemGroup><PackageReference Include="A; B" Version="1.0.0" />'
            "</ItemGroup></Project>"
        )
        found = project({"App.vbproj": text})["."]
        assert [(d.name, d.location) for d in found.dependencies] == [
            ("A", Location(line=1, column=62, end_column=67)),
            ("B", Location(line=1, column=62, end_column=67)),
        ]


# ---------------------------------------------------------------------------
# Directory.Build.targets (E34)
# ---------------------------------------------------------------------------

TARGETS_APP = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <SerilogVersion>2.10.0</SerilogVersion>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Newtonsoft.Json" Version="12.0.1" />
    <PackageReference Include="Serilog" Version="$(SerilogVersion)" />
    <PackageReference Include="Polly" Version="7.2.3" />
  </ItemGroup>
</Project>
"""

BUILD_TARGETS = """<Project>
  <PropertyGroup>
    <SerilogVersion>3.1.1</SerilogVersion>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Update="Newtonsoft.Json" Version="13.0.1" />
    <PackageReference Include="Humanizer.Core" Version="2.14.1" />
  </ItemGroup>
</Project>
"""

TARGETS_PROPS = """<Project>
  <ItemGroup>
    <PackageReference Update="Polly" Version="8.0.0" />
  </ItemGroup>
</Project>
"""


class TestDirectoryBuildTargets:
    """Vérifié avec le SDK .NET 10.0.403 (``dotnet restore``, ``project.assets.json``) :
    Newtonsoft.Json 13.0.1, Serilog 3.1.1, Humanizer.Core ajouté, Polly reste en 7.2.3."""

    def test_like_msbuild(self) -> None:
        files = {
            "src/App/App.csproj": TARGETS_APP,
            "Directory.Build.targets": BUILD_TARGETS,
            "Directory.Build.props": TARGETS_PROPS,
        }
        found = project(files)["src/App"]
        assert rows(found) == [
            ("Newtonsoft.Json", "13.0.1", "13.0.1", Scope.RUNTIME, "Directory.Build.targets"),
            ("Serilog", "3.1.1", "3.1.1", Scope.RUNTIME, "Directory.Build.targets"),
            ("Polly", "7.2.3", "7.2.3", Scope.RUNTIME, "src/App/App.csproj"),
            ("Humanizer.Core", "2.14.1", "2.14.1", Scope.RUNTIME, "Directory.Build.targets"),
        ]
        newtonsoft = found.dependencies[0]
        assert at(BUILD_TARGETS, newtonsoft) == "13.0.1"
        assert found.notices == [
            Notice(
                file="Directory.Build.props",
                message=(
                    'PackageReference Update="Polly" sans effet : aucune référence de ce nom '
                    "n'est lue avant lui (MSBuild lit Directory.Build.props avant le projet, "
                    "Directory.Build.targets après)."
                ),
            )
        ]

    def test_an_update_of_private_assets(self) -> None:
        targets = (
            '<Project><ItemGroup><PackageReference Update="Polly" PrivateAssets="all" />'
            "</ItemGroup></Project>"
        )
        found = project({"src/App/App.csproj": TARGETS_APP, "Directory.Build.targets": targets})
        polly = next(d for d in found["src/App"].dependencies if d.name == "Polly")
        assert (polly.constraint, polly.scope, polly.file) == (
            "7.2.3",
            Scope.BUILD,
            "src/App/App.csproj",
        )

    def test_the_writers_read_it_again(self) -> None:
        from forceupdate.update.writers import _reader

        reader = _reader("Directory.Build.targets")
        assert reader is not None
        declarations = reader("Directory.Build.targets", BUILD_TARGETS)
        assert any(d.constraint == "13.0.1" and d.location is not None for d in declarations)


# ---------------------------------------------------------------------------
# Directory.Build.props, Directory.Packages.props
# ---------------------------------------------------------------------------

BUILD_PROPS = """<Project>
  <PropertyGroup>
    <SerilogVersion>2.10.0</SerilogVersion>
    <ManagePackageVersionsCentrally>true</ManagePackageVersionsCentrally>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Microsoft.SourceLink.GitHub" PrivateAssets="all" />
  </ItemGroup>
</Project>
"""

CENTRAL = """<Project>
  <ItemGroup>
    <PackageVersion Include="Newtonsoft.Json" Version="12.0.1" />
    <PackageVersion Include="Serilog" Version="$(SerilogVersion)" />
    <PackageVersion Include="Microsoft.SourceLink.GitHub" Version="1.1.1" />
    <PackageVersion Include="Unused" Version="3.0.0" />
    <GlobalPackageReference Include="StyleCop.Analyzers" Version="1.1.118" />
  </ItemGroup>
</Project>
"""

APP = """<Project Sdk="Microsoft.NET.Sdk">
  <ItemGroup>
    <PackageReference Include="newtonsoft.json" />
    <PackageReference Include="Serilog" />
    <PackageReference Include="Polly" VersionOverride="7.2.3" />
    <PackageReference Include="NotCentral" />
  </ItemGroup>
</Project>
"""


class TestCentralManagement:
    def files(self) -> dict[str, str]:
        return {
            "Directory.Build.props": BUILD_PROPS,
            "Directory.Packages.props": CENTRAL,
            "src/App/App.csproj": APP,
        }

    def test_references_take_the_central_version(self) -> None:
        found = project(self.files())
        assert rows(found["src/App"]) == [
            (
                "Microsoft.SourceLink.GitHub",
                "1.1.1",
                "1.1.1",
                Scope.BUILD,
                "Directory.Packages.props",
            ),
            ("newtonsoft.json", "12.0.1", "12.0.1", Scope.RUNTIME, "Directory.Packages.props"),
            ("Serilog", "2.10.0", "2.10.0", Scope.RUNTIME, "Directory.Build.props"),
            ("Polly", "7.2.3", "7.2.3", Scope.RUNTIME, "src/App/App.csproj"),
            ("NotCentral", "", None, Scope.RUNTIME, "src/App/App.csproj"),
            ("StyleCop.Analyzers", "1.1.118", "1.1.118", Scope.BUILD, "Directory.Packages.props"),
        ]
        app = {d.name: d for d in found["src/App"].dependencies}
        assert at(CENTRAL, app["newtonsoft.json"]) == "12.0.1"
        assert at(BUILD_PROPS, app["Serilog"]) == "2.10.0"
        assert at(APP, app["Polly"]) == "7.2.3"
        assert app["NotCentral"].unverifiable_reason == REASON_NO_CENTRAL

    def test_the_central_project_gives_what_its_folder_does_not_use(self) -> None:
        found = project(self.files())
        assert rows(found["."]) == [
            ("Newtonsoft.Json", "12.0.1", "12.0.1", Scope.RUNTIME, "Directory.Packages.props"),
            ("Serilog", "2.10.0", "2.10.0", Scope.RUNTIME, "Directory.Build.props"),
            (
                "Microsoft.SourceLink.GitHub",
                "1.1.1",
                "1.1.1",
                Scope.RUNTIME,
                "Directory.Packages.props",
            ),
            ("Unused", "3.0.0", "3.0.0", Scope.RUNTIME, "Directory.Packages.props"),
            ("StyleCop.Analyzers", "1.1.118", "1.1.118", Scope.BUILD, "Directory.Packages.props"),
        ]
        files = self.files() | {"App.csproj": APP}
        names = [d.name for d in project(files)["."].dependencies]
        assert names[:6] == [
            "Microsoft.SourceLink.GitHub",
            "newtonsoft.json",
            "Serilog",
            "Polly",
            "NotCentral",
            "StyleCop.Analyzers",
        ]
        assert names[6:] == ["Unused"]

    def test_without_central_management(self) -> None:
        files = self.files()
        files["Directory.Build.props"] = BUILD_PROPS.replace(">true<", ">false<")
        found = project(files)
        assert {d.name: d.unverifiable_reason for d in found["src/App"].dependencies} == {
            "Microsoft.SourceLink.GitHub": REASON_NO_VERSION,
            "newtonsoft.json": REASON_NO_VERSION,
            "Serilog": REASON_NO_VERSION,
            "Polly": REASON_NO_VERSION,
            "NotCentral": REASON_NO_VERSION,
        }
        assert found["."].notices == [
            Notice(
                file="Directory.Packages.props",
                message=(
                    "ManagePackageVersionsCentrally n'est pas à true : NuGet n'utilise pas ces "
                    "versions centrales."
                ),
            )
        ]

    def test_the_nearest_props_and_those_it_imports_above(self) -> None:
        above = "<Project><PropertyGroup><V>1.0.0</V><W>9.0.0</W></PropertyGroup></Project>"
        nearest = (
            "<Project><Import Project=\"$([MSBuild]::GetPathOfFileAbove('Directory.Build.props', "
            "'$(MSBuildThisFileDirectory)../'))\" /><PropertyGroup><V>2.0.0</V></PropertyGroup>"
            "</Project>"
        )
        csproj = (
            '<Project><ItemGroup><PackageReference Include="A" Version="$(V)" />'
            '<PackageReference Include="B" Version="$(W)" /></ItemGroup></Project>'
        )
        files = {
            "Directory.Build.props": above,
            "src/Directory.Build.props": nearest,
            "src/App/App.csproj": csproj,
        }
        assert rows(project(files)["src/App"]) == [
            ("A", "2.0.0", "2.0.0", Scope.RUNTIME, "src/Directory.Build.props"),
            ("B", "9.0.0", "9.0.0", Scope.RUNTIME, "Directory.Build.props"),
        ]
        without_import = files | {
            "src/Directory.Build.props": nearest.split("<PropertyGroup>")[0].split("<Import")[0]
            + "<PropertyGroup><V>2.0.0</V></PropertyGroup></Project>"
        }
        reasons = {
            d.name: d.unverifiable_reason for d in project(without_import)["src/App"].dependencies
        }
        assert reasons == {"A": None, "B": "propriété $(W) introuvable"}

    def test_a_packages_config_project_ignores_package_references(self) -> None:
        files = {
            "legacy/Legacy.csproj": APP,
            "legacy/packages.config": PACKAGES_CONFIG,
            "Directory.Packages.props": CENTRAL,
        }
        assert [d.name for d in project(files)["legacy"].dependencies] == [
            "log4net",
            "Newtonsoft.Json",
            "NUnit",
            "Exact",
        ]


# ---------------------------------------------------------------------------
# packages.lock.json
# ---------------------------------------------------------------------------


def lockfile(targets: dict[str, dict[str, dict[str, object]]]) -> str:
    return json.dumps({"version": 2, "dependencies": targets}, indent=2)


LOCK = lockfile(
    {
        "net8.0": {
            "Newtonsoft.Json": {"type": "Direct", "requested": "[12.0.1, )", "resolved": "12.0.1"},
            "Serilog": {
                "type": "Direct",
                "requested": "[2.10.0, )",
                "resolved": "2.10.0",
                "dependencies": {"System.Buffers": "4.5.0"},
            },
            "System.Buffers": {"type": "Transitive", "resolved": "4.5.0"},
            "lib": {"type": "Project", "dependencies": {"Polly": "[7.2.3, )"}},
            "Polly": {"type": "CentralTransitive", "requested": "[7.2.3, )", "resolved": "7.2.3"},
        },
        "net10.0": {
            "Newtonsoft.Json": {"type": "Direct", "requested": "[12.0.1, )", "resolved": "13.0.1"},
            "Serilog": {"type": "Direct", "requested": "[2.10.0, )", "resolved": "2.10.0"},
            "lib": {"type": "Project", "dependencies": {"Polly": "[7.2.3, )"}},
            "Polly": {"type": "CentralTransitive", "requested": "[7.2.3, )", "resolved": "7.2.3"},
        },
        "net10.0/win-x64": {
            "runtime.win.Native": {
                "type": "Transitive",
                "resolved": "1.0.0",
                "dependencies": {"System.Buffers": "4.5.0"},
            },
        },
    }
)


class TestPackagesLockJson:
    def test_entries_by_target(self) -> None:
        lock = parse_packages_lock_json("packages.lock.json", LOCK)
        assert lock.versions("newtonsoft.json") == ["12.0.1", "13.0.1"]
        assert lock.versions("Polly", ("CentralTransitive",)) == ["7.2.3"]
        packages = {p.key: p for p in lock.lockfile.packages}
        assert packages["net8.0|serilog"].dependencies == (("net8.0|system.buffers", frozenset()),)
        assert packages["net8.0|lib"].local
        # Une section propre à une plateforme renvoie au framework seul.
        assert packages["net10.0/win-x64|runtime.win.native"].dependencies == (
            ("net10.0|system.buffers", frozenset()),
        )
        assert lock.lockfile.graph

    def test_invalid(self) -> None:
        with pytest.raises(ParseError, match="JSON invalide"):
            parse_packages_lock_json("packages.lock.json", "{")
        with pytest.raises(ParseError, match=r"pas un packages\.lock\.json"):
            parse_packages_lock_json("packages.lock.json", "[]")

    def test_parse_lockfile_reads_it(self) -> None:
        lock = parsers.parse_lockfile("src/packages.lock.json", "﻿" + LOCK)
        assert lock.ecosystem is Ecosystem.NUGET
        assert {(p.name, p.version) for p in lock.packages if not p.local} >= {
            ("Newtonsoft.Json", "12.0.1"),
            ("Newtonsoft.Json", "13.0.1"),
        }

    def test_linked_to_the_project(self) -> None:
        csproj = """<Project><ItemGroup>
  <PackageReference Include="newtonsoft.json" Version="12.0.1" />
  <PackageReference Include="Serilog" Version="2.10.0" />
  <PackageReference Include="NotLocked" Version="1.0.0" />
</ItemGroup></Project>"""
        central = (
            '<Project><ItemGroup><PackageVersion Include="Polly" Version="7.2.3" />'
            "</ItemGroup></Project>"
        )
        files = {
            "src/App/App.csproj": csproj,
            "src/App/packages.lock.json": LOCK,
            "Directory.Packages.props": central,
        }
        found = project(files)["src/App"]
        directs = [(d.name, d.installed, d.lockfile) for d in found.dependencies if d.direct]
        assert directs == [
            ("newtonsoft.json", "12.0.1", "src/App/packages.lock.json"),
            ("Serilog", "2.10.0", "src/App/packages.lock.json"),
            ("NotLocked", "1.0.0", None),
        ]
        indirect = [
            (d.name, d.installed, d.scope, d.file, d.constraint)
            for d in found.dependencies
            if not d.direct
        ]
        assert indirect == [
            ("Newtonsoft.Json", "13.0.1", Scope.RUNTIME, "src/App/packages.lock.json", ""),
            ("Polly", "7.2.3", Scope.RUNTIME, "Directory.Packages.props", "7.2.3"),
            ("runtime.win.Native", "1.0.0", Scope.RUNTIME, "src/App/packages.lock.json", ""),
            ("System.Buffers", "4.5.0", Scope.RUNTIME, "src/App/packages.lock.json", ""),
        ]
        polly = next(d for d in found.dependencies if d.name == "Polly")
        assert polly.lockfile == "src/App/packages.lock.json"
        assert at(central, polly) == "7.2.3"

    def test_a_test_project_makes_what_its_project_references_pull_dev(self) -> None:
        csproj = (
            "<Project><PropertyGroup><IsTestProject>true</IsTestProject></PropertyGroup>"
            '<ItemGroup><PackageReference Include="Serilog" Version="2.10.0" />'
            "</ItemGroup></Project>"
        )
        files = {"Tests.csproj": csproj, "packages.lock.json": LOCK}
        scopes = {d.name: d.scope for d in project(files)["."].dependencies if not d.direct}
        assert scopes["Polly"] is Scope.DEV
        assert scopes["System.Buffers"] is Scope.DEV
