"""Le client du proxy Go : chemins encodés, la dernière version comme ``go``, les retraits et la
dépréciation du ``go.mod`` de la dernière, ``@latest`` pour un module sans étiquette, la majeure
suivante sous un autre chemin, 404 et 410."""

from collections.abc import Callable
from typing import Any

import pytest
import respx

from forceupdate.models import Ecosystem
from forceupdate.net import Cache
from forceupdate.parsers.go import parse_go_mod_file
from forceupdate.registries import PackageInfo, PackageNotFound, RegistryError
from forceupdate.registries.goproxy import GoProxy, escape, has_go_mod, latest_of

PROXY = "https://proxy.golang.org"
Lookup = Callable[..., list[Any]]
Routes = dict[str, respx.Route]


def info_of(lookup: Lookup, name: str) -> PackageInfo:
    [info] = lookup(GoProxy, name)
    assert isinstance(info, PackageInfo), info
    return info


def serve(
    respx_mock: respx.MockRouter,
    module: str,
    versions: list[str],
    *,
    mods: dict[str, str] | None = None,
    majors: dict[str, list[str]] | None = None,
) -> respx.Route:
    """Un module : ses versions (dans le désordre, comme le proxy), le ``go.mod`` de certaines,
    les listes d'autres chemins (``…/v2``). Le reste donne 404."""
    route = respx_mock.get(f"{PROXY}/{escape(module)}/@v/list").respond(
        200, text="".join(f"{v}\n" for v in versions)
    )
    for version, content in (mods or {}).items():
        respx_mock.get(f"{PROXY}/{escape(module)}/@v/{escape(version)}.mod").respond(
            200, text=content
        )
    for path, listed in (majors or {}).items():
        respx_mock.get(f"{PROXY}/{escape(path)}/@v/list").respond(
            200, text="".join(f"{v}\n" for v in listed)
        )
    respx_mock.get(url__regex=rf"^{PROXY}/").respond(404, text="not found")
    return route


@pytest.mark.parametrize(
    ("text", "escaped"),
    [
        ("github.com/BurntSushi/toml", "github.com/!burnt!sushi/toml"),
        ("github.com/Azure/azure-sdk-for-go", "github.com/!azure/azure-sdk-for-go"),
        ("golang.org/x/text", "golang.org/x/text"),
        ("v1.0.0-RC1", "v1.0.0-!r!c1"),
    ],
)
def test_escape(text: str, escaped: str) -> None:
    """Vérifié le 2026-10-30 : ``github.com/BurntSushi/toml`` tel quel donne 404."""
    assert escape(text) == escaped


def test_latest_like_go() -> None:
    assert latest_of(["v1.2.2", "v1.2.3-pre", "v1.0.0"]) == "v1.2.2"  # une publiée d'abord
    assert latest_of(["v0.1.0-rc.1", "v0.1.0-rc.2"]) == "v0.1.0-rc.2"
    assert latest_of(["v0.0.0-20240101000000-aaaaaaaaaaaa"]) == "v0.0.0-20240101000000-aaaaaaaaaaaa"
    assert latest_of([]) is None


@pytest.mark.parametrize(
    ("content", "real"),
    [
        ("module github.com/pkg/errors\n", False),
        ("module github.com/go-chi/chi\n\ngo 1.16\n", True),
        ("// Deprecated: x\nmodule m\n", False),  # un commentaire ne fait pas un go.mod
        ("module m\nrequire a.io/b v1.0.0\n", True),
    ],
)
def test_has_go_mod(content: str, real: bool) -> None:
    assert has_go_mod(parse_go_mod_file("go.mod", content), content) is real


# -- réponses enregistrées -----------------------------------------------------


def test_chi(recorded: Routes, lookup: Lookup) -> None:
    info = info_of(lookup, "github.com/go-chi/chi")
    assert info.ecosystem is Ecosystem.GO
    assert info.url == "https://pkg.go.dev/github.com/go-chi/chi"
    assert info.deprecated == (
        "Please upgrade to the latest major version: go get github.com/go-chi/chi/v5"
    )
    versions = [v.version for v in info.versions]
    # Les +incompatible restent (une version utilisée peut en être une), mais v1.5.5 a un vrai
    # go.mod : elles ne comptent pas pour la dernière, comme pour go. La v5 est un autre chemin.
    assert versions[-3:] == ["v4.1.1+incompatible", "v4.1.2+incompatible", "v5.5.0"]
    assert versions.index("v1.5.5") < versions.index("v2.0.0+incompatible")
    assert info.latest == "v5.5.0"
    assert not any(v.yanked for v in info.versions)


def test_jwt_v4_retracts_a_version(recorded: Routes, lookup: Lookup) -> None:
    info = info_of(lookup, "github.com/golang-jwt/jwt/v4")
    retracted = info.get("v4.4.0")
    assert retracted is not None and retracted.yanked
    assert retracted.yanked_reason == (
        "Contains a backwards incompatible change to the Claims interface."
    )
    assert "v4.4.0" not in info.available()
    assert info.latest == "v5.3.1"  # github.com/golang-jwt/jwt/v5
    assert info.deprecated is None


def test_an_incompatible_range_retracted(recorded: Routes, lookup: Lookup) -> None:
    info = info_of(lookup, "github.com/mattn/go-sqlite3")
    yanked = [v.version for v in info.versions if v.yanked]
    assert yanked[0] == "v2.0.0+incompatible"
    assert all(v.endswith("+incompatible") for v in yanked)
    assert info.latest == "v1.14.52"


def test_toml_has_capitals(recorded: Routes, lookup: Lookup) -> None:
    info = info_of(lookup, "github.com/BurntSushi/toml")
    assert info.name == "github.com/BurntSushi/toml"
    assert info.latest == "v1.6.0"
    route = recorded["goproxy:github.com/BurntSushi/toml"]
    assert route.calls.last.request.url.path == "/github.com/!burnt!sushi/toml/@v/list"


def test_a_module_without_tags(recorded: Routes, lookup: Lookup) -> None:
    info = info_of(lookup, "golang.org/x/exp")
    assert [v.version for v in info.versions] == ["v0.0.0-20261014143641-f0251eb4aa3e"]
    assert info.latest == "v0.0.0-20261014143641-f0251eb4aa3e"


def test_a_module_deprecated_for_another(recorded: Routes, lookup: Lookup) -> None:
    info = info_of(lookup, "github.com/golang/protobuf")
    assert info.deprecated == 'Use the "google.golang.org/protobuf" module instead.'
    assert info.latest == "v1.5.4"


def test_gopkg_in(recorded: Routes, lookup: Lookup) -> None:
    info = info_of(lookup, "gopkg.in/yaml.v3")
    assert [v.version for v in info.versions] == ["v3.0.0", "v3.0.1"]
    assert info.latest == "v3.0.1"  # gopkg.in/yaml.v4 : 404


# -- formats --------------------------------------------------------------------------


def test_incompatible_versions_count_without_a_real_go_mod(
    respx_mock: respx.MockRouter, lookup: Lookup
) -> None:
    serve(
        respx_mock,
        "example.com/old",
        ["v1.0.0", "v2.1.0+incompatible", "v2.0.0+incompatible"],
        mods={"v1.0.0": "module example.com/old\n"},
    )
    assert info_of(lookup, "example.com/old").latest == "v2.1.0+incompatible"


def test_the_latest_skips_retracted_versions_but_retractions_come_from_it(
    respx_mock: respx.MockRouter, lookup: Lookup
) -> None:
    serve(
        respx_mock,
        "example.com/m",
        ["v1.0.0", "v1.1.0", "v1.2.0"],
        mods={"v1.2.0": "module example.com/m\n\ngo 1.21\n\nretract v1.2.0 // Oups.\n"},
    )
    info = info_of(lookup, "example.com/m")
    assert info.latest == "v1.1.0"
    assert [(v.version, v.yanked_reason) for v in info.versions if v.yanked] == [
        ("v1.2.0", "Oups.")
    ]


def test_a_retraction_without_rationale(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    serve(
        respx_mock,
        "example.com/m",
        ["v1.0.0", "v1.1.0"],
        mods={"v1.1.0": "module example.com/m\n\nretract [v1.0.0, v1.0.9]\n"},
    )
    retracted = info_of(lookup, "example.com/m").get("v1.0.0")
    assert retracted is not None and retracted.yanked and retracted.yanked_reason is None


def test_newer_majors_are_followed(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    serve(
        respx_mock,
        "example.com/m",
        ["v1.0.0"],
        majors={"example.com/m/v2": ["v2.0.0", "v2.1.0"], "example.com/m/v3": ["v3.0.0-rc.1"]},
    )
    info = info_of(lookup, "example.com/m")
    assert [v.version for v in info.versions] == ["v1.0.0", "v2.1.0"]
    assert info.latest == "v2.1.0"


def test_not_found(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    respx_mock.get(f"{PROXY}/example.com/private/@v/list").respond(410, text="gone")
    [error] = lookup(GoProxy, "example.com/private")
    assert isinstance(error, PackageNotFound)
    assert str(error) == (
        "example.com/private est introuvable sur proxy.golang.org : module privé, ou chemin mal "
        "écrit ?"
    )


def test_an_empty_list_without_latest(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    serve(respx_mock, "example.com/empty", [])
    [error] = lookup(GoProxy, "example.com/empty")
    assert isinstance(error, PackageNotFound)


def test_a_failing_go_mod_is_inconclusive(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    respx_mock.get(f"{PROXY}/example.com/m/@v/v1.0.0.mod").respond(500)
    serve(respx_mock, "example.com/m", ["v1.0.0"])
    [error] = lookup(GoProxy, "example.com/m")
    assert isinstance(error, RegistryError)
    assert "HTTP 500" in str(error)


def test_cached_with_its_retractions(
    respx_mock: respx.MockRouter, lookup: Lookup, cache: Cache
) -> None:
    route = serve(
        respx_mock,
        "example.com/m",
        ["v1.0.0", "v1.1.0"],
        mods={"v1.1.0": "module example.com/m\nretract v1.0.0 // Non.\n"},
    )
    first = info_of(lookup, "example.com/m")
    second = info_of(lookup, "example.com/m")
    assert route.call_count == 1
    assert second.versions == first.versions
    assert second.get("v1.0.0").yanked_reason == "Non."  # type: ignore[union-attr]


def test_another_proxy_has_no_page(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    respx_mock.get("https://goproxy.maison.test/example.com/m/@v/list").respond(
        200, text="v1.0.0\n"
    )
    respx_mock.get(url__regex=r"^https://goproxy\.maison\.test/").respond(404)
    [info] = lookup(GoProxy, "example.com/m", base_url="https://goproxy.maison.test/")
    assert isinstance(info, PackageInfo)
    assert info.url is None


@pytest.mark.network
def test_the_real_proxy(lookup: Lookup) -> None:
    chi, jwt, missing = lookup(
        GoProxy,
        "github.com/go-chi/chi",
        "github.com/golang-jwt/jwt/v4",
        "github.com/pauzzle-ozz/forceupdate-module-qui-n-existe-pas",
        cache=Cache(None),
    )
    assert isinstance(chi, PackageInfo), chi
    assert chi.deprecated is not None and chi.latest is not None
    assert chi.latest.startswith("v5.")
    assert isinstance(jwt, PackageInfo), jwt
    assert jwt.get("v4.4.0").yanked  # type: ignore[union-attr]
    assert isinstance(missing, PackageNotFound)
