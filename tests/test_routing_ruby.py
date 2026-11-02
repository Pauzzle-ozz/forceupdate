"""Les serveurs de gems (E33, E34) : la source globale d'un ``Gemfile``, ses blocs
``source "…" do``, l'option ``source:``, les sections ``GEM`` du lockfile, les miroirs et les
identifiants de Bundler ; de bout en bout par le moteur, avec un serveur de gems simulé (son index
compact)."""

import asyncio
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import respx
from conftest import UserFiles, recorded_responses

from forceupdate import engine
from forceupdate.models import FindingKind, Report
from forceupdate.net import Cache, HttpClient
from forceupdate.report.json import render
from forceupdate.routing.ruby import BundlerSettings, parse_settings, settings_key
from forceupdate.sources.local import LocalSource

MakeTree = Callable[..., Path]
CORP = "https://gems.corp.example"
BASIC = "Basic YWxpY2U6czNjcmV0"  # alice:s3cret

ACME = (
    "---\n"
    "1.0.0 |checksum:aa,ruby:>= 2.7,created_at:2026-01-01T00:00:00Z\n"
    "1.2.0 |checksum:bb,ruby:>= 3.0,created_at:2026-10-01T00:00:00Z\n"
)
JSON_ON_MIRROR = "---\n2.0.0 |checksum:cc\n9.9.9 |checksum:dd\n"


async def no_sleep(_: float) -> None:
    pass


@contextmanager
def gem_server(
    base: str = CORP, status: int = 200, versions: int = 200
) -> Iterator[dict[str, respx.Route]]:
    """Les réponses enregistrées, plus un serveur de gems à ``base`` : ``acme`` et ``json``
    (``status``), ``/versions`` (``versions``), tout autre gem introuvable."""
    extra: dict[str, respx.Route] = {}

    def add(router: respx.MockRouter) -> None:
        extra["acme"] = router.get(f"{base}/info/acme").respond(status, text=ACME)
        extra["json"] = router.get(f"{base}/info/json").respond(status, text=JSON_ON_MIRROR)
        extra["versions"] = router.get(f"{base}/versions").respond(versions, text="---\n")
        extra["other"] = router.get(url__regex=rf"^{base}/info/").respond(404)

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
        if f.dependency is not None and f.dependency.name == name
    ]


def osv_names(routes: dict[str, respx.Route]) -> set[str]:
    return {
        query["package"]["name"]
        for call in routes["osv:querybatch"].calls
        for query in json.loads(call.request.content)["queries"]
    }


def auth(route: respx.Route) -> str | None:
    return route.calls.last.request.headers.get("authorization")


# -- la source globale ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source", ['"https://gems.corp.example"', "('https://gems.corp.example/')"]
)
def test_a_private_global_source_is_asked_instead_of_rubygems(
    make_tree: MakeTree, user_files: UserFiles, source: str
) -> None:
    gemfile = f"source {source}\n\ngem 'acme', '~> 1.0'\ngem 'json', '~> 2.0'\n"
    root = make_tree({"Gemfile": gemfile})
    user_files.write(".bundle/config", '---\nBUNDLE_GEMS__CORP__EXAMPLE: "alice:s3cret"\n')
    with gem_server() as routes:
        report = analyze(root)
    assert routes["rubygems:json"].call_count == 0
    assert auth(routes["acme"]) == BASIC
    assert auth(routes["json"]) == BASIC
    # Une source globale sert aussi les gems publiques (un miroir) : leurs failles sont cherchées.
    assert findings(report, "json")[0][0] is FindingKind.OUTDATED
    assert "9.9.9" in findings(report, "json")[0][1]
    assert "s3cret" not in render(report)


def test_a_refusal_says_private_unchecked_and_never_asks_rubygems(make_tree: MakeTree) -> None:
    root = make_tree({"Gemfile": f"source '{CORP}'\ngem 'json', '~> 2.0'\n"})
    with gem_server(status=401) as routes:
        report = analyze(root)
    assert routes["rubygems:json"].call_count == 0
    assert findings(report, "json") == [
        (
            FindingKind.UNVERIFIABLE,
            "Registre privé : non vérifié : gems.corp.example refuse l'accès à json (HTTP 401) : "
            "identifiants absents ou refusés.",
        )
    ]


def test_a_server_without_compact_index_is_inconclusive(make_tree: MakeTree) -> None:
    root = make_tree({"Gemfile": f"source '{CORP}'\ngem 'rails'\ngem 'rack'\n"})
    with gem_server(versions=404) as routes:
        report = analyze(root)
    assert routes["versions"].call_count == 1  # une fois par serveur
    assert routes["versions"].calls.last.request.headers["range"] == "bytes=0-0"
    ((kind, message),) = findings(report, "rails")
    assert kind is FindingKind.INCONCLUSIVE
    assert message == (
        "gems.corp.example ne sert pas l'index compact de Bundler (/versions, /info/…), le seul "
        "que lit forceupdate."
    )


def test_a_gem_missing_from_a_compact_index_is_not_found(make_tree: MakeTree) -> None:
    root = make_tree({"Gemfile": f"source '{CORP}'\ngem 'rails'\n"})
    with gem_server():
        report = analyze(root)
    assert findings(report, "rails") == [
        (FindingKind.UNVERIFIABLE, "rails est introuvable sur gems.corp.example.")
    ]


def test_several_global_sources_take_the_first(make_tree: MakeTree) -> None:
    gemfile = f"source '{CORP}'\nsource 'https://other.example'\ngem 'acme'\n"
    root = make_tree({"Gemfile": gemfile})
    with gem_server() as routes:
        report = analyze(root)
    assert routes["acme"].call_count == 1
    (project,) = report.projects
    assert any("Bundler n'en accepte qu'une" in n.message for n in project.notices)


def test_a_source_that_is_a_folder_is_not_read(make_tree: MakeTree) -> None:
    root = make_tree({"Gemfile": "source 'file:///srv/gems'\ngem 'json'\n"})
    with gem_server() as routes:
        report = analyze(root)
    assert routes["rubygems:json"].call_count == 0
    ((kind, message),) = findings(report, "json")
    assert kind is FindingKind.UNVERIFIABLE
    assert "n'est pas un serveur http(s)" in message


# -- les blocs et l'option source: ----------------------------------------------------------------


def test_rubygems_and_a_source_block(make_tree: MakeTree) -> None:
    gemfile = (
        "source 'https://rubygems.org'\n\n"
        f"source '{CORP}' do\n  gem 'acme', '~> 1.0'\nend\n\n"
        "gem 'json', '~> 2.0'\n"
    )
    root = make_tree({"Gemfile": gemfile})
    with gem_server() as routes:
        report = analyze(root)
    assert routes["rubygems:json"].call_count == 1
    assert routes["json"].call_count == 0
    assert routes["acme"].call_count == 1
    assert "acme" not in osv_names(routes)  # privée par son nom
    assert "json" in osv_names(routes)
    ((kind, message),) = findings(report, "acme")
    assert kind is FindingKind.OUTDATED
    assert "1.2.0" in message
    (project,) = report.projects
    assert any("paquet privé" in n.message for n in project.notices)


def test_the_source_option(make_tree: MakeTree) -> None:
    gemfile = f"source 'https://rubygems.org'\ngem 'acme', '~> 1.0', source: '{CORP}'\n"
    root = make_tree({"Gemfile": gemfile})
    with gem_server() as routes:
        report = analyze(root)
    assert routes["acme"].call_count == 1
    assert findings(report, "acme")[0][0] is FindingKind.OUTDATED


def test_a_private_gem_missing_from_its_server_is_never_asked_to_rubygems(
    make_tree: MakeTree,
) -> None:
    gemfile = f"source 'https://rubygems.org'\nsource '{CORP}' do\n  gem 'json'\nend\n"
    root = make_tree({"Gemfile": gemfile})
    with gem_server(status=404) as routes:
        report = analyze(root)
    assert routes["rubygems:json"].call_count == 0
    assert findings(report, "json") == [
        (FindingKind.UNVERIFIABLE, "json est introuvable sur gems.corp.example.")
    ]


LOCK = f"""GEM
  remote: https://rubygems.org/
  specs:
    json (2.7.1)

GEM
  remote: {CORP}/
  specs:
    acme (1.0.0)
      helper (>= 0)
    helper (0.1.0)

PLATFORMS
  ruby

DEPENDENCIES
  acme!
  json (~> 2.0)

BUNDLED WITH
  4.0.20
"""


def test_an_indirect_gem_of_a_private_section_is_private(make_tree: MakeTree) -> None:
    gemfile = (
        f"source 'https://rubygems.org'\nsource '{CORP}' do\n  gem 'acme'\nend\n"
        "gem 'json', '~> 2.0'\n"
    )
    root = make_tree({"Gemfile": gemfile, "Gemfile.lock": LOCK})
    with gem_server() as routes:
        report = analyze(root)
    names = osv_names(routes)
    assert "json" in names
    assert "acme" not in names
    assert "helper" not in names  # tirée par une gem privée, rangée avec elle
    (project,) = report.projects
    acme = next(d for d in project.dependencies if d.name == "acme")
    assert acme.installed == "1.0.0"
    assert acme.unverifiable_reason is None  # demandée à son serveur


# -- les miroirs ------------------------------------------------------------------------------


def test_a_mirror_of_rubygems_is_asked_instead(make_tree: MakeTree, user_files: UserFiles) -> None:
    root = make_tree({"Gemfile": "source 'https://rubygems.org'\ngem 'json', '~> 2.0'\n"})
    user_files.write(
        ".bundle/config",
        f'---\nBUNDLE_MIRROR__HTTPS://RUBYGEMS__ORG/: "{CORP}"\n'
        'BUNDLE_GEMS__CORP__EXAMPLE: "alice:s3cret"\n',
    )
    with gem_server() as routes:
        report = analyze(root)
    assert routes["rubygems:json"].call_count == 0
    assert auth(routes["json"]) == BASIC
    assert "json" in osv_names(routes)
    assert "9.9.9" in findings(report, "json")[0][1]


def test_a_mirror_of_every_source(make_tree: MakeTree, user_files: UserFiles) -> None:
    gemfile = (
        "source 'https://rubygems.org'\nsource 'https://other.example' do\n  gem 'acme'\nend\n"
    )
    root = make_tree({"Gemfile": gemfile})
    user_files.env["BUNDLE_MIRROR__ALL"] = CORP
    with gem_server() as routes:
        analyze(root)
    assert routes["acme"].call_count == 1


# -- les identifiants ---------------------------------------------------------------------------


def test_the_exact_address_comes_before_the_host(
    make_tree: MakeTree, user_files: UserFiles
) -> None:
    root = make_tree({"Gemfile": f"source '{CORP}/private'\ngem 'acme'\n"})
    user_files.write(
        ".bundle/config",
        "---\n"
        'BUNDLE_GEMS__CORP__EXAMPLE: "bob:other"\n'
        'BUNDLE_HTTPS://GEMS__CORP__EXAMPLE/PRIVATE/: "alice:s3cret"\n',
    )
    with gem_server(f"{CORP}/private") as routes:
        analyze(root)
    assert auth(routes["acme"]) == BASIC


def test_the_project_then_the_environment_then_the_person(
    make_tree: MakeTree, user_files: UserFiles
) -> None:
    root = make_tree(
        {
            "Gemfile": f"source '{CORP}'\ngem 'acme'\n",
            ".bundle/config": '---\nBUNDLE_GEMS__CORP__EXAMPLE: "alice:s3cret"\n',
        }
    )
    user_files.env["BUNDLE_GEMS__CORP__EXAMPLE"] = "env:env"
    user_files.write(".bundle/config", '---\nBUNDLE_GEMS__CORP__EXAMPLE: "home:home"\n')
    with gem_server() as routes:
        analyze(root)
    assert auth(routes["acme"]) == BASIC
    (root / ".bundle" / "config").unlink()
    with gem_server() as routes:
        analyze(root)
    assert auth(routes["acme"]) == "Basic ZW52OmVudg=="  # env:env


def test_bundle_user_home_and_bundle_config(make_tree: MakeTree, user_files: UserFiles) -> None:
    root = make_tree({"Gemfile": f"source '{CORP}'\ngem 'acme'\n"})
    content = '---\nBUNDLE_GEMS__CORP__EXAMPLE: "alice:s3cret"\n'
    path = user_files.write("bundle-home/config", content)
    user_files.env["BUNDLE_USER_HOME"] = str(path.parent)
    with gem_server() as routes:
        analyze(root)
    assert auth(routes["acme"]) == BASIC


def test_credentials_written_in_the_gemfile(make_tree: MakeTree) -> None:
    root = make_tree({"Gemfile": "source 'https://alice:s3cret@gems.corp.example'\ngem 'acme'\n"})
    with gem_server() as routes:
        report = analyze(root)
    assert auth(routes["acme"]) == BASIC
    assert "s3cret" not in render(report)


def test_a_host_key_holds_for_every_port_but_not_another_host(
    make_tree: MakeTree, user_files: UserFiles
) -> None:
    base = "https://gems.corp.example:8443"
    root = make_tree({"Gemfile": f"source '{base}'\ngem 'acme'\n"})
    user_files.env["BUNDLE_GEMS__CORP__EXAMPLE"] = "alice:s3cret"
    user_files.env["BUNDLE_OTHER__EXAMPLE"] = "x:y"
    with gem_server(base) as routes:
        analyze(root)
    assert auth(routes["acme"]) == BASIC
    assert routes["acme"].call_count == 1


def test_no_credential_over_plain_http(make_tree: MakeTree, user_files: UserFiles) -> None:
    base = "http://gems.corp.example"
    root = make_tree({"Gemfile": f"source '{base}'\ngem 'acme'\n"})
    user_files.env["BUNDLE_GEMS__CORP__EXAMPLE"] = "alice:s3cret"
    with gem_server(base) as routes:
        report = analyze(root)
    assert auth(routes["acme"]) is None
    (project,) = report.projects
    assert any("n'est pas envoyé : la source est en http" in n.message for n in project.notices)


def test_a_dash_in_a_host() -> None:
    assert settings_key("gems-corp.example") == "BUNDLE_GEMS___CORP__EXAMPLE"
    assert settings_key("https://gems.corp.example") == "BUNDLE_HTTPS://GEMS__CORP__EXAMPLE/"
    assert settings_key("mirror.https://rubygems.org") == "BUNDLE_MIRROR__HTTPS://RUBYGEMS__ORG/"


def test_parse_settings_like_bundler() -> None:
    text = (
        "---\n"
        'BUNDLE_GEMS__CORP__EXAMPLE: "alice:s3cret"\n'
        "BUNDLE_PATH: vendor/bundle\n"
        'BUNDLE_HTTPS://GEMS__CORP__EXAMPLE: "a:b"\n'
        '# BUNDLE_COMMENTED: "x"\n'
        'BUNDLE_WITH_HASH: "tok#en"\n'
        'BUNDLE_gems-x.example: "c:d"\n'
    )
    assert parse_settings(text) == {
        "BUNDLE_GEMS__CORP__EXAMPLE": "alice:s3cret",
        "BUNDLE_PATH": "vendor/bundle",
        "BUNDLE_HTTPS://GEMS__CORP__EXAMPLE/": "a:b",
        "BUNDLE_WITH_HASH": "tok",  # Bundler coupe à un « # »
        "BUNDLE_gems___x__example": "c:d",
    }


def test_mirror_lookup() -> None:
    settings = BundlerSettings(
        layers=[
            ("", {"BUNDLE_MIRROR__HTTPS://RUBYGEMS__ORG/": "https://m.example"}),
            ("~/.bundle/config", {"BUNDLE_MIRROR__GEMS__CORP__EXAMPLE": "https://n.example"}),
        ]
    )
    rubygems = settings.mirror("https://rubygems.org")
    assert rubygems is not None
    assert rubygems.value == "https://m.example"
    assert rubygems.source == "BUNDLE_MIRROR__HTTPS://RUBYGEMS__ORG/"
    by_host = settings.mirror("https://gems.corp.example/private/")
    assert by_host is not None
    assert by_host.value == "https://n.example"
    assert settings.mirror("https://other.example/") is None
