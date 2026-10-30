"""Le client crates.io : l'index « sparse », ses chemins, les versions retirées, la dernière
stable."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import respx

from forceupdate.models import Ecosystem
from forceupdate.net import Cache
from forceupdate.net.http import USER_AGENT
from forceupdate.registries import PackageInfo, PackageNotFound, RegistryError
from forceupdate.registries.crates import Crates, index_path

FIXTURES = Path(__file__).parent / "fixtures" / "crates"
INDEX = "https://index.crates.io"

Lookup = Callable[..., list[Any]]


def serve(respx_mock: respx.MockRouter, name: str, content: bytes) -> respx.Route:
    return respx_mock.get(f"{INDEX}/{index_path(name)}").respond(
        200, content=content, headers={"content-type": "text/plain"}
    )


def recorded(respx_mock: respx.MockRouter, name: str) -> respx.Route:
    """Sert la réponse enregistrée par ``tests/fixtures/record.py``."""
    return serve(respx_mock, name, (FIXTURES / f"{name}.jsonl").read_bytes())


def index(*versions: tuple[str, bool] | tuple[str, bool, str | None]) -> bytes:
    """Un fichier de l'index : ``(version, retirée)``, et sa date (``pubtime``)."""
    lines = []
    for vers, yanked, *rest in versions:
        entry: dict[str, Any] = {"name": "demo", "vers": vers, "deps": [], "yanked": yanked}
        pubtime = rest[0] if rest else "2026-01-01T00:00:00Z"
        if pubtime is not None:
            entry["pubtime"] = pubtime
        lines.append(json.dumps(entry))
    return ("\n".join(lines) + "\n").encode()


def info_of(lookup: Lookup, name: str = "demo") -> PackageInfo:
    [info] = lookup(Crates, name)
    assert isinstance(info, PackageInfo), info
    return info


@pytest.mark.parametrize(
    ("name", "path"),
    [
        ("a", "1/a"),
        ("cc", "2/cc"),
        ("log", "3/l/log"),
        ("rand", "ra/nd/rand"),
        ("serde", "se/rd/serde"),
        ("Inflector", "in/fl/inflector"),
        ("serde_json", "se/rd/serde_json"),
    ],
)
def test_index_path(name: str, path: str) -> None:
    """Les chemins vérifiés le 2026-10-30 sur index.crates.io : en minuscules (``Serde`` y donne
    404)."""
    assert index_path(name) == path


# -- réponses enregistrées -----------------------------------------------------


def test_rand(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    route = recorded(respx_mock, "rand")
    info = info_of(lookup, "rand")
    assert info.ecosystem is Ecosystem.CRATES_IO
    assert info.name == "rand"
    assert info.url == "https://crates.io/crates/rand"
    assert info.deprecated is None
    yanked = [v.version for v in info.versions if v.yanked]
    assert yanked == ["0.4.4", "0.7.1"]
    assert all(v.yanked_reason is None for v in info.versions)  # l'index ne la donne pas
    assert "0.7.1" not in info.available()
    # Les pré-versions sont gardées, rangées à leur place, mais jamais la dernière stable.
    versions = [v.version for v in info.versions]
    assert (
        versions.index("0.9.0-alpha.0") < versions.index("0.9.0-beta.3") < versions.index("0.9.0")
    )
    assert info.latest == "0.10.3"
    first = info.get("0.1.1")
    assert first is not None and first.published == datetime(2015, 2, 3, 6, 17, 14, tzinfo=UTC)
    assert route.calls.last.request.headers["user-agent"] == USER_AGENT


def test_regex(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    recorded(respx_mock, "regex")
    info = info_of(lookup, "regex")
    assert info.get("1.5.4") is not None and info.get("1.5.5") is not None
    assert info.latest == "1.13.1"


# -- formats --------------------------------------------------------------------------


def test_versions_are_sorted_and_yanked_ones_are_not_proposed(
    respx_mock: respx.MockRouter, lookup: Lookup
) -> None:
    serve(respx_mock, "demo", index(("1.0.0", False), ("1.2.0", True), ("1.1.0", False)))
    info = info_of(lookup)
    assert [(v.version, v.yanked) for v in info.versions] == [
        ("1.0.0", False),
        ("1.1.0", False),
        ("1.2.0", True),
    ]
    assert info.latest == "1.1.0"
    assert info.available() == ["1.0.0", "1.1.0"]


def test_only_prereleases(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    serve(respx_mock, "demo", index(("0.1.0-alpha.1", False), ("0.1.0-beta.1", False)))
    info = info_of(lookup)
    assert info.latest is None
    assert info.deprecated is None


def test_every_version_yanked(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    serve(respx_mock, "demo", index(("0.1.0", True), ("0.2.0", True)))
    info = info_of(lookup)
    assert info.latest is None
    assert info.deprecated == "toutes ses versions ont été retirées de crates.io."


def test_without_pubtime(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    serve(respx_mock, "demo", index(("1.0.0", False, None)))
    [version] = info_of(lookup).versions
    assert version.published is None


def test_blank_lines_and_lines_without_version_are_skipped(
    respx_mock: respx.MockRouter, lookup: Lookup
) -> None:
    content = b'\n{"name":"demo","vers":"1.0.0","yanked":false}\n\n{"name":"demo"}\n'
    serve(respx_mock, "demo", content)
    assert [v.version for v in info_of(lookup).versions] == ["1.0.0"]


def test_an_unreadable_index_is_inconclusive(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    serve(respx_mock, "demo", b"<html>maintenance</html>\n")
    [error] = lookup(Crates, "demo")
    assert isinstance(error, RegistryError)
    assert str(error).startswith("crates.io : réponse illisible pour demo")


def test_not_found(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    respx_mock.get(f"{INDEX}/pa/s-/pas-un-crate").respond(404, content=b"<Error/>")
    [error] = lookup(Crates, "pas-un-crate")
    assert isinstance(error, PackageNotFound)
    assert str(error) == (
        "pas-un-crate est introuvable sur crates.io : paquet privé, ou nom mal écrit ?"
    )


def test_the_name_keeps_its_case(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    route = serve(respx_mock, "Inflector", index(("0.11.4", False)))
    info = info_of(lookup, "Inflector")
    assert info.name == "Inflector"
    assert info.url == "https://crates.io/crates/Inflector"
    assert route.calls.last.request.url.path == "/in/fl/inflector"


def test_another_index_has_no_page(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    respx_mock.get("https://index.maison.test/de/mo/demo").respond(
        200, content=index(("1.0.0", False))
    )
    [info] = lookup(Crates, "demo", base_url="https://index.maison.test/")
    assert isinstance(info, PackageInfo)
    assert info.url is None


def test_cached(respx_mock: respx.MockRouter, lookup: Lookup, cache: Cache) -> None:
    route = serve(respx_mock, "demo", index(("1.0.0", False), ("1.0.1", True)))
    first = info_of(lookup)
    second = info_of(lookup)
    assert route.call_count == 1
    assert second.versions == first.versions


@pytest.mark.network
def test_the_real_index(lookup: Lookup) -> None:
    rand, serde, missing = lookup(
        Crates, "rand", "serde", "forceupdate-crate-qui-n-existe-pas", cache=Cache(None)
    )
    assert isinstance(rand, PackageInfo), rand
    assert [v.version for v in rand.versions if v.yanked][:2] == ["0.4.4", "0.7.1"]
    assert isinstance(serde, PackageInfo), serde
    assert serde.latest is not None and serde.get("1.0.0") is not None
    assert isinstance(missing, PackageNotFound)
