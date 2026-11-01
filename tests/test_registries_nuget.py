"""Le client NuGet : l'API « registration » de nuget.org, ses pages au-delà de 128 versions, les
versions non listées, la dépréciation."""

import json
from collections.abc import Callable
from typing import Any

import pytest
import respx

from forceupdate.models import Ecosystem
from forceupdate.net import Cache
from forceupdate.registries import PackageInfo, PackageNotFound, RegistryError
from forceupdate.registries.nuget import NuGet, deprecation_message

BASE = NuGet.base_url
Lookup = Callable[..., list[Any]]
Routes = dict[str, respx.Route]


def info_of(lookup: Lookup, name: str) -> PackageInfo:
    [info] = lookup(NuGet, name)
    assert isinstance(info, PackageInfo), info
    return info


def leaf(version: str, **entry: Any) -> dict[str, Any]:
    return {"catalogEntry": {"version": version, "listed": True, **entry}}


def index(*pages: dict[str, Any]) -> dict[str, Any]:
    return {"count": len(pages), "items": list(pages)}


def test_newtonsoft_json(recorded: Routes, lookup: Lookup) -> None:
    info = info_of(lookup, "Newtonsoft.Json")
    assert info.ecosystem is Ecosystem.NUGET
    assert info.name == "newtonsoft.json"
    assert info.url == "https://www.nuget.org/packages/newtonsoft.json"
    assert info.latest == "13.0.4"
    assert len(info.versions) == 86
    versions = [v.version for v in info.versions]
    assert versions.index("12.0.1") < versions.index("12.0.2-beta1") < versions.index("13.0.1")
    unlisted = info.get("12.0.2-beta1")
    assert unlisted is not None and unlisted.yanked and unlisted.published is None
    listed = info.get("12.0.1")
    assert listed is not None and not listed.yanked
    assert listed.published is not None and listed.published.year == 2018
    assert info.deprecated is None
    assert recorded["nuget:Newtonsoft.Json"].call_count == 1


def test_pages_outside_the_index(recorded: Routes, lookup: Lookup) -> None:
    """Serilog a plus de 128 versions : ses dix pages sont demandées à part."""
    info = info_of(lookup, "serilog")
    assert len(info.versions) > 600
    assert info.get("2.10.0") is not None and info.get("4.4.0") is not None
    assert info.latest == "4.4.0"


def test_a_legacy_package_is_deprecated(recorded: Routes, lookup: Lookup) -> None:
    info = info_of(lookup, "xunit")
    assert info.deprecated is not None
    assert info.deprecated.startswith("plus maintenu (nuget.org), remplacé par xunit.v3 : ")
    version = info.get("2.4.1")
    assert version is not None and version.deprecated == info.deprecated


def test_an_unlisted_version_is_yanked(recorded: Routes, lookup: Lookup) -> None:
    info = info_of(lookup, "log4net")
    yanked = [v.version for v in info.versions if v.yanked]
    assert [f"2.0.{n}" for n in range(10)] == [v for v in yanked if v.startswith("2.0.")]
    assert info.get("2.0.10") is not None and not info.get("2.0.10").yanked  # type: ignore[union-attr]
    assert info.get("2.0.8") is not None and info.get("2.0.8").yanked  # type: ignore[union-attr]
    assert info.latest is not None and info.latest.startswith("3.")


def test_the_latest_listed_stable(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    page = {
        "items": [
            leaf("1.0.0"),
            leaf("1.1.0-beta"),
            leaf("1.0.1", deprecation={"reasons": ["CriticalBugs"], "message": "Bad build."}),
            leaf("2.0.0", listed=False),
        ]
    }
    respx_mock.get(f"{BASE}/demo/index.json").respond(200, json=index(page))
    info = info_of(lookup, "Demo")
    assert [v.version for v in info.versions] == ["1.0.0", "1.0.1", "1.1.0-beta", "2.0.0"]
    assert info.latest == "1.0.1"
    assert info.get("1.0.1").deprecated == "bogues critiques (nuget.org) : Bad build."  # type: ignore[union-attr]
    # Une dernière version dépréciée pour un bogue ne fait pas un paquet déprécié.
    assert info.deprecated is None


def test_a_page_is_requested_only_from_the_registry(
    respx_mock: respx.MockRouter, lookup: Lookup
) -> None:
    elsewhere = {"@id": "https://ailleurs.test/page.json", "count": 1}
    respx_mock.get(f"{BASE}/demo/index.json").respond(200, json=index(elsewhere))
    [error] = lookup(NuGet, "demo")
    assert isinstance(error, RegistryError)
    assert "page hors du registre" in str(error)


def test_a_failing_page(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    page = {"@id": f"{BASE}/demo/page/1.0.0/2.0.0.json", "count": 1}
    respx_mock.get(f"{BASE}/demo/index.json").respond(200, json=index(page))
    respx_mock.get(page["@id"]).respond(403)
    [error] = lookup(NuGet, "demo")
    assert isinstance(error, RegistryError)
    assert str(error) == "nuget.org : réponse inattendue pour demo (HTTP 403)."


def test_an_unreadable_answer_is_inconclusive(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    respx_mock.get(f"{BASE}/demo/index.json").respond(200, json={"items": [{"items": [{}]}]})
    [error] = lookup(NuGet, "demo")
    assert isinstance(error, RegistryError)
    assert str(error).startswith("nuget.org : réponse illisible pour demo")


def test_not_found(recorded: Routes, lookup: Lookup) -> None:
    [error] = lookup(NuGet, "Pas.Un.Paquet")
    assert isinstance(error, PackageNotFound)
    assert (
        str(error)
        == "pas.un.paquet est introuvable sur nuget.org : paquet privé, ou nom mal écrit ?"
    )


def test_cached_with_its_pages(recorded: Routes, lookup: Lookup) -> None:
    first = info_of(lookup, "Serilog")
    calls = recorded["nuget:Serilog"].call_count
    second = info_of(lookup, "Serilog")
    assert recorded["nuget:Serilog"].call_count == calls == 1
    assert second.versions == first.versions
    assert second.latest == first.latest


def test_another_registry_has_no_page(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    respx_mock.get("https://nuget.maison.test/v3/registration/demo/index.json").respond(
        200, json=index({"items": [leaf("1.0.0")]})
    )
    [info] = lookup(NuGet, "demo", base_url="https://nuget.maison.test/v3/registration/")
    assert isinstance(info, PackageInfo)
    assert info.url is None


@pytest.mark.parametrize(
    ("deprecation", "message"),
    [
        (None, None),
        ({}, "déprécié (nuget.org)"),
        ({"reasons": ["Legacy", "Other"]}, "plus maintenu, déprécié (nuget.org)"),
        (
            {
                "reasons": ["Legacy"],
                "alternatePackage": {"id": "Azure.Storage.Common", "range": "*"},
            },
            "plus maintenu (nuget.org), remplacé par Azure.Storage.Common",
        ),
        (
            {"reasons": ["Unknown"], "message": "  Voir ailleurs. "},
            "Unknown (nuget.org) : Voir ailleurs.",
        ),
    ],
)
def test_deprecation_message(deprecation: Any, message: str | None) -> None:
    assert deprecation_message(deprecation) == message


def test_the_recorded_answers_are_complete() -> None:
    """Chaque page citée par un index enregistré l'est aussi."""
    import gzip
    from pathlib import Path

    for path in (Path(__file__).parent / "fixtures" / "nuget").glob("*.json.gz"):
        answers = json.loads(gzip.decompress(path.read_bytes()))
        index_suffix = next(s for s in answers if s.endswith("/index.json"))
        pages = json.loads(answers[index_suffix]["body"])["items"]
        for page in pages:
            if "items" not in page:
                assert page["@id"].removeprefix(f"{BASE}/") in answers, path.name


@pytest.mark.network
def test_the_real_registry(lookup: Lookup) -> None:
    newtonsoft, storage, missing = lookup(
        NuGet,
        "Newtonsoft.Json",
        "WindowsAzure.Storage",
        "Forceupdate.Paquet.Qui.N.Existe.Pas",
        cache=Cache(None),
    )
    assert isinstance(newtonsoft, PackageInfo), newtonsoft
    assert newtonsoft.get("12.0.1") is not None and newtonsoft.latest is not None
    assert isinstance(storage, PackageInfo), storage
    assert storage.deprecated is not None and "Azure.Storage.Common" in storage.deprecated
    assert isinstance(missing, PackageNotFound)
