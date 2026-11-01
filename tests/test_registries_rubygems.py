"""Le client RubyGems : l'index compact de Bundler, les versions à plateforme, la dernière stable,
les versions retirées absentes."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import respx

from forceupdate.models import Ecosystem
from forceupdate.net import Cache
from forceupdate.registries import PackageInfo, PackageNotFound, RegistryError
from forceupdate.registries.rubygems import RubyGems, parse_info

FIXTURES = Path(__file__).parent / "fixtures" / "rubygems"
INDEX = "https://index.rubygems.org/info"
Lookup = Callable[..., list[Any]]


def serve(respx_mock: respx.MockRouter, name: str, content: bytes) -> respx.Route:
    return respx_mock.get(f"{INDEX}/{name}").respond(
        200, content=content, headers={"content-type": "text/plain"}
    )


def recorded(respx_mock: respx.MockRouter, name: str) -> respx.Route:
    """Sert la réponse enregistrée par ``tests/fixtures/record.py``."""
    return serve(respx_mock, name, (FIXTURES / f"{name}.txt").read_bytes())


def info_of(lookup: Lookup, name: str = "demo") -> PackageInfo:
    [info] = lookup(RubyGems, name)
    assert isinstance(info, PackageInfo), info
    return info


def test_parse_info() -> None:
    text = (
        "---\n"
        "1.0.0 |checksum:aa,created_at:2020-01-02T03:04:05Z\n"
        "1.1.0-x86_64-linux-gnu racc:~> 1.4|checksum:bb,ruby:< 4.1.dev&>= 3.2,"
        "created_at:2021-02-02T00:00:00Z\n"
        "1.1.0-java racc:~> 1.4|checksum:cc,created_at:2021-01-01T00:00:00Z\n"
        "1.1.0 mini_portile2:~> 2.8.2,racc:~> 1.4|checksum:dd,ruby:>= 3.2,"
        "created_at:2021-03-01T00:00:00Z\n"
        "2.0.0.rc1 |checksum:ee\n"
    )
    found = [(v.version, v.published) for v in parse_info(text)]
    assert found == [
        ("1.0.0", datetime(2020, 1, 2, 3, 4, 5, tzinfo=UTC)),
        ("1.1.0", datetime(2021, 1, 1, tzinfo=UTC)),  # la plus ancienne de ses plateformes
        ("2.0.0.rc1", None),
    ]
    with pytest.raises(ValueError, match="index compact"):
        parse_info("<html>maintenance</html>")


# -- réponses enregistrées -----------------------------------------------------


def test_rack(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    route = recorded(respx_mock, "rack")
    info = info_of(lookup, "rack")
    assert info.ecosystem is Ecosystem.RUBYGEMS
    assert info.name == "rack"
    assert info.url == "https://rubygems.org/gems/rack"
    assert info.deprecated is None
    assert info.latest == "3.2.8"
    versions = [v.version for v in info.versions]
    # Rangées de la plus ancienne à la plus récente, pré-versions à leur place.
    assert versions[0] == "0.1.0"
    assert versions.index("3.0.0.beta1") < versions.index("3.0.0.rc1") < versions.index("3.0.0")
    assert versions.index("2.2.8") < versions.index("2.2.8.1") < versions.index("2.2.9")
    published = info.get("2.2.3")
    assert published is not None
    assert published.published == datetime(2020, 6, 15, 22, 25, 14, tzinfo=UTC)
    assert not any(v.yanked for v in info.versions)  # une version retirée n'est pas listée
    assert route.call_count == 1


def test_versions_with_a_platform_are_one_version(
    respx_mock: respx.MockRouter, lookup: Lookup
) -> None:
    recorded(respx_mock, "nokogiri")
    info = info_of(lookup, "nokogiri")
    versions = [v.version for v in info.versions]
    assert len(versions) == len(set(versions))
    assert "1.19.0" in versions and not any("-" in v for v in versions)
    assert info.latest == "1.19.4"


def test_yanked_versions_are_absent(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    recorded(respx_mock, "rest-client")
    info = info_of(lookup, "rest-client")
    assert info.get("1.6.9") is not None and info.get("1.6.14") is not None
    assert [info.get(f"1.6.{n}") for n in (10, 11, 12, 13)] == [None] * 4


# -- formats --------------------------------------------------------------------------


def test_only_prereleases(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    serve(respx_mock, "demo", b"---\n1.0.0.beta1 |checksum:aa\n")
    info = info_of(lookup)
    assert info.latest is None
    assert [v.version for v in info.versions] == ["1.0.0.beta1"]


def test_an_unreadable_answer_is_inconclusive(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    serve(respx_mock, "demo", b"<html>maintenance</html>")
    [error] = lookup(RubyGems, "demo")
    assert isinstance(error, RegistryError)
    assert str(error).startswith("RubyGems : réponse illisible pour demo")


def test_not_found(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    respx_mock.get(f"{INDEX}/nope").respond(404, text="This rubygem could not be found.")
    [error] = lookup(RubyGems, "nope")
    assert isinstance(error, PackageNotFound)
    assert str(error) == "nope est introuvable sur RubyGems : paquet privé, ou nom mal écrit ?"


def test_the_name_is_kept_as_written(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    route = respx_mock.get(f"{INDEX}/Demo_Gem").respond(200, content=b"---\n1.0.0 |\n")
    info = info_of(lookup, " Demo_Gem ")
    assert info.name == "Demo_Gem"
    assert route.call_count == 1


def test_another_server_has_no_page(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    respx_mock.get("https://gems.maison.test/info/demo").respond(200, content=b"---\n1.0.0 |\n")
    [info] = lookup(RubyGems, "demo", base_url="https://gems.maison.test/")
    assert isinstance(info, PackageInfo)
    assert info.url is None


def test_cached(respx_mock: respx.MockRouter, lookup: Lookup, cache: Cache) -> None:
    route = serve(respx_mock, "demo", b"---\n1.0.0 |checksum:aa,created_at:2020-01-02T03:04:05Z\n")
    first = info_of(lookup)
    second = info_of(lookup)
    assert route.call_count == 1
    assert second.versions == first.versions


@pytest.mark.network
def test_the_real_registry(lookup: Lookup) -> None:
    rack, nokogiri, missing = lookup(
        RubyGems, "rack", "nokogiri", "forceupdate-gem-qui-n-existe-pas", cache=Cache(None)
    )
    assert isinstance(rack, PackageInfo), rack
    assert rack.get("2.2.3") is not None and rack.latest is not None
    assert isinstance(nokogiri, PackageInfo), nokogiri
    assert nokogiri.get("1.19.0") is not None
    assert isinstance(missing, PackageNotFound)
