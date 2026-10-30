"""Le client Packagist : les métadonnées ``p2`` minifiées, ``abandoned``, la dernière stable."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import respx

from forceupdate.models import Ecosystem
from forceupdate.net import Cache
from forceupdate.registries import PackageInfo, PackageNotFound, RegistryError
from forceupdate.registries.packagist import Packagist, abandoned_message, expand

FIXTURES = Path(__file__).parent / "fixtures" / "packagist"
REPO = "https://repo.packagist.org/p2"

Lookup = Callable[..., list[Any]]


def serve(respx_mock: respx.MockRouter, name: str, content: bytes) -> respx.Route:
    return respx_mock.get(f"{REPO}/{name}.json").respond(
        200, content=content, headers={"content-type": "application/json"}
    )


def recorded(respx_mock: respx.MockRouter, name: str) -> respx.Route:
    """Sert la réponse enregistrée par ``tests/fixtures/record.py``."""
    return serve(respx_mock, name, (FIXTURES / f"{name.replace('/', '__')}.json").read_bytes())


def p2(name: str, *versions: dict[str, Any], minified: bool = True) -> bytes:
    """Une réponse ``p2`` : les versions de la plus récente à la plus ancienne."""
    body: dict[str, Any] = {"packages": {name: list(versions)}}
    if minified:
        body["minified"] = "composer/2.0"
    return json.dumps(body).encode()


def info_of(lookup: Lookup, name: str = "acme/demo") -> PackageInfo:
    [info] = lookup(Packagist, name)
    assert isinstance(info, PackageInfo), info
    return info


def test_expand_like_composer() -> None:
    minified = [
        {"name": "a/b", "version": "2.0.0", "require": {"php": ">=8"}, "extra": {"x": 1}},
        {"version": "1.1.0", "extra": "__unset"},
        {"version": "1.0.0", "require": {"php": ">=7"}},
    ]
    assert expand(minified) == [
        {"name": "a/b", "version": "2.0.0", "require": {"php": ">=8"}, "extra": {"x": 1}},
        {"name": "a/b", "version": "1.1.0", "require": {"php": ">=8"}},
        {"name": "a/b", "version": "1.0.0", "require": {"php": ">=7"}},
    ]
    assert minified[1] == {"version": "1.1.0", "extra": "__unset"}  # rien n'est modifié


def test_abandoned_message() -> None:
    assert abandoned_message("symfony/mailer") == (
        "abandonné sur Packagist, remplacé par symfony/mailer."
    )
    assert abandoned_message(True) == "abandonné sur Packagist, sans remplaçant indiqué."
    assert abandoned_message(False) is None
    assert abandoned_message(None) is None


# -- réponses enregistrées -----------------------------------------------------


def test_monolog(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    route = recorded(respx_mock, "monolog/monolog")
    info = info_of(lookup, "monolog/monolog")
    assert info.ecosystem is Ecosystem.PACKAGIST
    assert info.name == "monolog/monolog"
    assert info.url == "https://packagist.org/packages/monolog/monolog"
    assert info.deprecated is None
    assert len(info.versions) == 91
    assert info.latest == "3.12.1"
    versions = [v.version for v in info.versions]
    # Rangées de la plus ancienne à la plus récente, pré-versions à leur place.
    assert versions[0] == "1.0.0-RC1"
    assert versions.index("2.0.0-beta1") < versions.index("2.0.0-beta2") < versions.index("2.0.0")
    first = info.get("1.0.0-RC1")
    assert first is not None and first.published == datetime(2011, 7, 1, 19, 29, 40, tzinfo=UTC)
    assert not any(v.yanked for v in info.versions)  # Packagist n'a pas de retrait
    assert route.call_count == 1


def test_twig_has_a_prerelease_above_the_last_stable(
    respx_mock: respx.MockRouter, lookup: Lookup
) -> None:
    recorded(respx_mock, "twig/twig")
    info = info_of(lookup, "twig/twig")
    assert info.versions[-1].version == "v4.0.0-alpha1"
    assert info.latest == "v3.30.0"
    assert info.get("3.4.1") is not None  # « v3.4.1 » sur Packagist


def test_symfony_versions_have_a_v(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    recorded(respx_mock, "symfony/console")
    info = info_of(lookup, "symfony/console")
    assert info.latest == "v8.1.10"
    published = info.get("5.4.10")
    assert published is not None and published.version == "v5.4.10"


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("doctrine/cache", "abandonné sur Packagist, sans remplaçant indiqué."),
        ("php-http/message-factory", "abandonné sur Packagist, remplacé par psr/http-factory."),
    ],
)
def test_abandoned_packages(
    respx_mock: respx.MockRouter, lookup: Lookup, name: str, message: str
) -> None:
    recorded(respx_mock, name)
    assert info_of(lookup, name).deprecated == message


# -- formats --------------------------------------------------------------------------


def test_only_prereleases(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    serve(respx_mock, "acme/demo", p2("acme/demo", {"version": "1.0.0-beta1"}))
    info = info_of(lookup)
    assert info.latest is None
    assert [v.version for v in info.versions] == ["1.0.0-beta1"]


def test_not_minified(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    content = p2(
        "acme/demo",
        {"version": "1.1.0", "time": "2026-01-02T00:00:00+00:00"},
        {"version": "1.0.0"},
        minified=False,
    )
    serve(respx_mock, "acme/demo", content)
    info = info_of(lookup)
    assert [(v.version, v.published is None) for v in info.versions] == [
        ("1.0.0", True),
        ("1.1.0", False),
    ]


def test_an_unreadable_answer_is_inconclusive(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    serve(respx_mock, "acme/demo", b"<html>maintenance</html>")
    [error] = lookup(Packagist, "acme/demo")
    assert isinstance(error, RegistryError)
    assert str(error).startswith("Packagist : réponse illisible pour acme/demo")


def test_an_answer_for_another_package_is_inconclusive(
    respx_mock: respx.MockRouter, lookup: Lookup
) -> None:
    serve(respx_mock, "acme/demo", p2("acme/other", {"version": "1.0.0"}))
    [error] = lookup(Packagist, "acme/demo")
    assert isinstance(error, RegistryError)


def test_not_found(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    respx_mock.get(f"{REPO}/acme/nope.json").respond(404, text="404 not found, no packages here")
    [error] = lookup(Packagist, "acme/nope")
    assert isinstance(error, PackageNotFound)
    assert (
        str(error) == "acme/nope est introuvable sur Packagist : paquet privé, ou nom mal écrit ?"
    )


def test_the_name_is_lowercased(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    route = serve(respx_mock, "acme/demo", p2("acme/demo", {"version": "1.0.0"}))
    info = info_of(lookup, "Acme/Demo")
    assert info.name == "acme/demo"
    assert route.calls.last.request.url.path == "/p2/acme/demo.json"


def test_another_repository_has_no_page(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    respx_mock.get("https://satis.maison.test/p2/acme/demo.json").respond(
        200, content=p2("acme/demo", {"version": "1.0.0"})
    )
    [info] = lookup(Packagist, "acme/demo", base_url="https://satis.maison.test/")
    assert isinstance(info, PackageInfo)
    assert info.url is None


def test_cached(respx_mock: respx.MockRouter, lookup: Lookup, cache: Cache) -> None:
    route = serve(respx_mock, "acme/demo", p2("acme/demo", {"version": "1.0.0", "abandoned": True}))
    first = info_of(lookup)
    second = info_of(lookup)
    assert route.call_count == 1
    assert second.versions == first.versions
    assert second.deprecated == first.deprecated


@pytest.mark.network
def test_the_real_registry(lookup: Lookup) -> None:
    monolog, swiftmailer, missing = lookup(
        Packagist,
        "monolog/monolog",
        "swiftmailer/swiftmailer",
        "forceupdate/paquet-qui-n-existe-pas",
        cache=Cache(None),
    )
    assert isinstance(monolog, PackageInfo), monolog
    assert monolog.get("2.3.5") is not None and monolog.latest is not None
    assert isinstance(swiftmailer, PackageInfo), swiftmailer
    assert swiftmailer.deprecated == "abandonné sur Packagist, remplacé par symfony/mailer."
    assert isinstance(missing, PackageNotFound)
