"""Les sources NuGet déclarées (E33) : la hiérarchie de ``nuget.config``, ``<clear />``, les sources
désactivées, ``packageSourceMapping``, les identifiants rattachés à un nom de source ; de bout en
bout par le moteur, avec un flux v3 simulé (index de services, puis API « registration »)."""

import asyncio
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import respx
from conftest import UserFiles, recorded_responses

from forceupdate import engine
from forceupdate.models import FindingKind, Report
from forceupdate.net import Cache, HttpClient
from forceupdate.sources.local import LocalSource

MakeTree = Callable[..., Path]
FEED = "https://pkgs.corp.example/nuget/v3/index.json"
REGISTRATIONS = "https://pkgs.corp.example/nuget/v3/registrations"

CSPROJ = """\
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Contoso.Internal" Version="1.0.0" />
    <PackageReference Include="Newtonsoft.Json" Version="13.0.1" />
  </ItemGroup>
</Project>
"""


def nuget_config(sources: str, extra: str = "") -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n<configuration>\n'
        f"  <packageSources>\n{sources}  </packageSources>\n{extra}</configuration>\n"
    )


CORP = '    <add key="corp" value="https://pkgs.corp.example/nuget/v3/index.json" />\n'
MAPPING = """\
  <packageSourceMapping>
    <packageSource key="corp"><package pattern="Contoso.*" /></packageSource>
    <packageSource key="nuget.org"><package pattern="*" /></packageSource>
  </packageSourceMapping>
"""


def registration(name: str, versions: list[str]) -> dict[str, object]:
    leaves = [
        {"catalogEntry": {"version": v, "listed": True, "published": "2026-01-01T00:00:00Z"}}
        for v in versions
    ]
    return {"items": [{"@id": f"{REGISTRATIONS}/{name}/index.json#page", "items": leaves}]}


async def no_sleep(_: float) -> None:
    pass


@contextmanager
def feed(status: int = 200) -> Iterator[dict[str, respx.Route]]:
    extra: dict[str, respx.Route] = {}
    index = {
        "version": "3.0.0",
        "resources": [
            {"@id": "https://pkgs.corp.example/nuget/v3/query", "@type": "SearchQueryService"},
            {"@id": f"{REGISTRATIONS}/", "@type": "RegistrationsBaseUrl/3.6.0"},
        ],
    }

    def add(router: respx.MockRouter) -> None:
        extra["index"] = router.get(FEED).respond(status, json=index)
        extra["contoso"] = router.get(f"{REGISTRATIONS}/contoso.internal/index.json").respond(
            200, json=registration("contoso.internal", ["1.0.0", "1.3.0"])
        )
        extra["corp-other"] = router.get(url__regex=rf"^{REGISTRATIONS}/").respond(404)
        extra["public-contoso"] = router.get(
            "https://api.nuget.org/v3/registration5-gz-semver2/contoso.internal/index.json"
        ).respond(200, json=registration("contoso.internal", ["9.9.9"]))

    with recorded_responses(add) as routes:
        yield {**routes, **extra}


def analyze(root: Path) -> Report:
    async def main() -> Report:
        async with HttpClient(sleep=no_sleep) as http:
            return await engine.analyze(LocalSource(root), http=http, cache=Cache.disabled())

    return asyncio.run(main())


def findings(report: Report, name: str) -> list[tuple[FindingKind, str]]:
    return [
        (f.kind, f.message)
        for project in report.projects
        for f in project.findings
        if f.dependency is not None and f.dependency.name.lower() == name.lower()
    ]


def osv_names(routes: dict[str, respx.Route]) -> set[str]:
    return {
        query["package"]["name"].lower()
        for call in routes["osv:querybatch"].calls
        for query in json.loads(call.request.content)["queries"]
    }


def test_a_mapped_package_is_asked_to_its_source_only(
    make_tree: MakeTree, user_files: UserFiles
) -> None:
    root = make_tree({"App/App.csproj": CSPROJ, "nuget.config": nuget_config(CORP, MAPPING)})
    user_files.write(
        "AppData/Roaming/NuGet/NuGet.Config",
        nuget_config(
            CORP + '    <add key="nuget.org" value="https://api.nuget.org/v3/index.json" />\n',
            "  <packageSourceCredentials>\n    <corp>\n"
            '      <add key="Username" value="jo" />\n'
            '      <add key="ClearTextPassword" value="%CORP_PAT%" />\n'
            "    </corp>\n  </packageSourceCredentials>\n",
        ),
    )
    user_files.write(
        ".nuget/NuGet/NuGet.Config",
        (user_files.home / "AppData/Roaming/NuGet/NuGet.Config").read_text(encoding="utf-8"),
    )
    user_files.env["CORP_PAT"] = "pw"
    with feed() as routes:
        report = analyze(root)
    assert routes["index"].call_count == 1
    for name in ("index", "contoso"):
        assert routes[name].calls.last.request.headers["authorization"] == "Basic am86cHc="
    assert routes["public-contoso"].call_count == 0
    assert routes["corp-other"].call_count == 0  # Newtonsoft.Json va à nuget.org seul
    assert routes["nuget:Newtonsoft.Json"].call_count == 1
    assert "contoso.internal" not in osv_names(routes)
    assert "newtonsoft.json" in osv_names(routes)
    ((kind, message),) = findings(report, "Contoso.Internal")
    assert kind is FindingKind.OUTDATED
    assert "1.3.0" in message


def test_without_mapping_the_company_feed_comes_first(make_tree: MakeTree) -> None:
    root = make_tree({"App/App.csproj": CSPROJ, "nuget.config": nuget_config(CORP)})
    with feed() as routes:
        analyze(root)
    assert routes["contoso"].call_count == 1
    assert routes["public-contoso"].call_count == 0
    assert routes["corp-other"].call_count == 1  # Newtonsoft.Json : pas sur le flux, puis nuget.org
    assert routes["nuget:Newtonsoft.Json"].call_count == 1
    assert "newtonsoft.json" in osv_names(routes)


def test_a_refusing_feed_stops_everything(make_tree: MakeTree) -> None:
    root = make_tree({"App/App.csproj": CSPROJ, "nuget.config": nuget_config(CORP)})
    with feed(status=401) as routes:
        report = analyze(root)
    assert routes["public-contoso"].call_count == 0
    assert routes["nuget:Newtonsoft.Json"].call_count == 0
    ((kind, message),) = findings(report, "Contoso.Internal")
    assert kind is FindingKind.UNVERIFIABLE
    assert message == (
        "Registre privé : non vérifié : pkgs.corp.example refuse l'accès à son index de services "
        "(HTTP 401) : identifiants absents ou refusés."
    )


def test_the_person_credentials_never_follow_a_project_address(
    make_tree: MakeTree, user_files: UserFiles
) -> None:
    """Le projet donne au nom « corp » une autre adresse : les identifiants de la personne pour
    « corp » n'y partent pas."""
    evil = '    <add key="corp" value="https://evil.example/v3/index.json" />\n'
    root = make_tree({"App/App.csproj": CSPROJ, "nuget.config": nuget_config(evil)})
    personal = nuget_config(
        CORP,
        "  <packageSourceCredentials>\n    <corp>\n"
        '      <add key="Username" value="jo" />\n'
        '      <add key="ClearTextPassword" value="pw" />\n'
        "    </corp>\n  </packageSourceCredentials>\n",
    )
    user_files.write("AppData/Roaming/NuGet/NuGet.Config", personal)
    user_files.write(".nuget/NuGet/NuGet.Config", personal)

    def add(router: respx.MockRouter) -> None:
        evil_route = router.get("https://evil.example/v3/index.json").respond(401)
        captured["evil"] = evil_route

    captured: dict[str, respx.Route] = {}
    with recorded_responses(add):
        report = analyze(root)
    assert "authorization" not in captured["evil"].calls.last.request.headers
    (project,) = report.projects
    assert any("ne partent pas vers l'adresse" in n.message for n in project.notices)


def test_clear_and_disabled_sources(make_tree: MakeTree) -> None:
    root = make_tree(
        {
            "nuget.config": nuget_config(CORP),
            "src/nuget.config": nuget_config(
                "    <clear />\n"
                '    <add key="nuget.org" value="https://api.nuget.org/v3/index.json" />\n'
            ),
            "src/App/App.csproj": CSPROJ,
        }
    )
    with feed() as routes:
        analyze(root)
    assert routes["index"].call_count == 0  # « corp » est écarté par <clear />
    assert routes["public-contoso"].call_count == 1

    disabled = (
        "  <disabledPackageSources>\n"
        '    <add key="corp" value="true" />\n'
        "  </disabledPackageSources>\n"
    )
    root = make_tree(
        {"App/App.csproj": CSPROJ, "nuget.config": nuget_config(CORP, disabled)}, root=root / "x"
    )
    with feed() as routes:
        analyze(root)
    assert routes["index"].call_count == 0


def test_a_v2_feed_is_not_read(make_tree: MakeTree) -> None:
    old = '    <add key="old" value="https://legacy.example/api/v2" />\n'
    root = make_tree({"App/App.csproj": CSPROJ, "nuget.config": nuget_config(old)})
    with feed() as routes:
        report = analyze(root)
    assert routes["nuget:Newtonsoft.Json"].call_count == 0
    ((kind, message),) = findings(report, "Newtonsoft.Json")
    assert kind is FindingKind.UNVERIFIABLE
    assert "« old » est un flux NuGet v2" in message


def test_a_project_variable_in_credentials_is_never_expanded(
    make_tree: MakeTree, user_files: UserFiles
) -> None:
    creds = (
        "  <packageSourceCredentials>\n    <corp>\n"
        '      <add key="Username" value="jo" />\n'
        '      <add key="ClearTextPassword" value="%CORP_PAT%" />\n'
        "    </corp>\n  </packageSourceCredentials>\n"
    )
    root = make_tree({"App/App.csproj": CSPROJ, "nuget.config": nuget_config(CORP, creds)})
    user_files.env["CORP_PAT"] = "pw"
    with feed() as routes:
        report = analyze(root)
    assert "authorization" not in routes["index"].calls.last.request.headers
    (project,) = report.projects
    assert any("variable d'environnement" in n.message for n in project.notices)


def test_credentials_written_in_a_source_address(
    make_tree: MakeTree, user_files: UserFiles
) -> None:
    root = make_tree({"App/App.csproj": CSPROJ})
    source = CORP.replace("https://", "https://jo:pw@")
    for path in ("AppData/Roaming/NuGet/NuGet.Config", ".nuget/NuGet/NuGet.Config"):
        user_files.write(path, nuget_config(source))
    with feed() as routes:
        analyze(root)
    request = routes["index"].calls.last.request
    assert request.headers["authorization"] == "Basic am86cHc="
    assert "jo" not in str(request.url)


def test_project_literal_credentials(make_tree: MakeTree) -> None:
    creds = (
        "  <packageSourceCredentials>\n    <corp>\n"
        '      <add key="Username" value="jo" />\n'
        '      <add key="ClearTextPassword" value="pw" />\n'
        "    </corp>\n  </packageSourceCredentials>\n"
    )
    root = make_tree({"App/App.csproj": CSPROJ, "nuget.config": nuget_config(CORP, creds)})
    with feed() as routes:
        analyze(root)
    assert routes["contoso"].calls.last.request.headers["authorization"] == "Basic am86cHc="
