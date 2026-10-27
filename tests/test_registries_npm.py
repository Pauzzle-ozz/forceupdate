"""Le client npm : noms scopés, étiquettes, dernière stable, dépréciations."""

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
from forceupdate.registries.npm import Npm

FIXTURES = Path(__file__).parent / "fixtures" / "npm"
REGISTRY = "https://registry.npmjs.org"
SECURITY = (
    "paquet retiré du registre par l'équipe sécurité de npm, souvent pour du code malveillant :"
    " son nom est gardé par un paquet vide."
)

Lookup = Callable[..., list[Any]]


def serve(respx_mock: respx.MockRouter, path: str, payload: dict[str, Any] | bytes) -> respx.Route:
    content = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return respx_mock.get(f"{REGISTRY}/{path}").respond(
        200, content=content, headers={"content-type": "application/json"}
    )


def recorded(respx_mock: respx.MockRouter, name: str) -> respx.Route:
    """Sert la réponse enregistrée par ``tests/fixtures/record.py``."""
    content = (FIXTURES / f"{name.replace('/', '__')}.json").read_bytes()
    return serve(respx_mock, name.replace("/", "%2F"), content)


def packument(
    versions: dict[str, dict[str, Any]], tags: dict[str, str] | None = None, **extra: Any
) -> dict[str, Any]:
    """Un document npm : ``versions`` donne, pour chaque version, les champs de son manifeste."""
    return {
        "name": "demo",
        "dist-tags": {} if tags is None else tags,
        "versions": {v: {"name": "demo", "version": v, **fields} for v, fields in versions.items()},
        "time": {v: f"2024-01-{n + 1:02d}T00:00:00.000Z" for n, v in enumerate(versions)},
        **extra,
    }


def info_of(lookup: Lookup, name: str = "demo") -> PackageInfo:
    [info] = lookup(Npm, name)
    assert isinstance(info, PackageInfo), info
    return info


# -- réponses enregistrées -----------------------------------------------------


def test_left_pad_is_deprecated(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    route = recorded(respx_mock, "left-pad")
    info = info_of(lookup, "left-pad")
    assert route.calls.last.request.headers["accept"] == "application/json"
    assert info.ecosystem is Ecosystem.NPM
    assert info.name == "left-pad"
    assert info.latest == "1.3.0"
    assert info.tags == {"latest": "1.3.0"}
    assert info.deprecated == "use String.prototype.padStart()"
    assert info.url == "https://www.npmjs.com/package/left-pad"
    assert len(info.versions) == 15
    assert all(v.deprecated == "use String.prototype.padStart()" for v in info.versions)
    assert not any(v.yanked for v in info.versions)
    first = info.versions[0]
    assert first.version == "0.0.0"
    assert first.published == datetime(2014, 3, 14, 9, 9, 20, 762000, tzinfo=UTC)


def test_a_scoped_package_with_tags(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    route = recorded(respx_mock, "@hapi/joi")
    info = info_of(lookup, "@hapi/joi")
    assert route.calls.last.request.url == "https://registry.npmjs.org/@hapi%2Fjoi"
    assert info.name == "@hapi/joi"
    assert info.url == "https://www.npmjs.com/package/@hapi/joi"
    assert info.tags == {"lts": "14.5.0", "preview": "16.0.0-preview", "latest": "17.1.1"}
    assert info.latest == "17.1.1"
    assert info.deprecated == "Switch to 'npm install joi'"
    preview = info.get("16.0.0-rc2")
    assert preview is not None
    assert preview.deprecated == "This preview has been deprecated"


def test_colors_next_is_older_than_latest(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    recorded(respx_mock, "colors")
    info = info_of(lookup, "colors")
    assert info.tags == {"next": "1.2.0-rc0", "latest": "1.4.0"}
    assert info.latest == "1.4.0"
    assert info.deprecated is None
    assert [v.version for v in info.versions][-3:] == ["1.3.2", "1.3.3", "1.4.0"]


def test_a_security_holding_package(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    # crossenv volait les variables d'environnement : npm l'a remplacé par un paquet vide.
    recorded(respx_mock, "crossenv")
    info = info_of(lookup, "crossenv")
    assert info.tags == {"latest": "0.0.2-security"}
    assert info.deprecated == SECURITY
    # Les anciennes versions restent listées, mais aucune n'est sous « latest » : rien à proposer.
    assert [v.version for v in info.versions] == [
        "0.0.1-security",
        "0.0.2-security",
        "1.0.0",
        "1.0.1",
    ]
    assert info.latest is None


# -- la dernière stable ------------------------------------------------------------


@pytest.mark.parametrize(
    ("published", "tags", "latest"),
    [
        # dist-tags.latest, même si une version plus haute est publiée sous une autre étiquette
        (["4.9.0", "5.0.0"], {"latest": "4.9.0", "next": "5.0.0"}, "4.9.0"),
        (["1.9.0", "1.10.0"], {"latest": "1.10.0"}, "1.10.0"),
        # latest est une pré-version : la plus haute stable sous elle
        (["1.9.0", "2.0.0-beta.1", "2.0.0"], {"latest": "2.0.0-beta.1"}, "1.9.0"),
        (["2.0.0-beta.1"], {"latest": "2.0.0-beta.1"}, None),
        # latest manque, est illisible, ou n'est pas publiée
        (["1.0.0", "2.0.0", "3.0.0-rc.1"], {}, "2.0.0"),
        (["1.0.0", "2.0.0"], {"latest": "banane"}, "2.0.0"),
        (["1.0.0", "2.0.0"], {"latest": "1.5.0"}, "1.0.0"),
    ],
)
def test_latest(
    respx_mock: respx.MockRouter,
    lookup: Lookup,
    published: list[str],
    tags: dict[str, str],
    latest: str | None,
) -> None:
    serve(respx_mock, "demo", packument({v: {} for v in published}, tags))
    assert info_of(lookup).latest == latest


def test_versions_are_sorted_and_unreadable_ones_kept(
    respx_mock: respx.MockRouter, lookup: Lookup
) -> None:
    serve(
        respx_mock,
        "demo",
        packument({"1.10.0": {}, "pas-une-version": {}, "1.9.0": {}, "1.2.3-beta": {}}),
    )
    info = info_of(lookup)
    assert [v.version for v in info.versions] == [
        "1.2.3-beta",
        "1.9.0",
        "1.10.0",
        "pas-une-version",
    ]
    assert info.latest == "1.10.0"
    published = info.get("1.9.0")
    assert published is not None
    assert published.published == datetime(2024, 1, 3, tzinfo=UTC)


# -- dépréciations -----------------------------------------------------------------


def test_deprecation_of_each_version(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    versions = {
        "1.0.0": {"deprecated": "trop vieille"},
        "1.1.0": {"deprecated": ""},  # « npm deprecate demo@1.1.0 "" » la rend à nouveau sûre
        "1.2.0": {"deprecated": True},
        "1.3.0": {"deprecated": False},
        "2.0.0": {},
    }
    serve(respx_mock, "demo", packument(versions, {"latest": "2.0.0"}))
    info = info_of(lookup)
    assert [(v.version, v.deprecated) for v in info.versions] == [
        ("1.0.0", "trop vieille"),
        ("1.1.0", None),
        ("1.2.0", "version dépréciée"),
        ("1.3.0", None),
        ("2.0.0", None),
    ]
    # Le paquet n'est déprécié que si sa version « latest » l'est.
    assert info.deprecated is None


def test_the_package_deprecation_is_that_of_latest(
    respx_mock: respx.MockRouter, lookup: Lookup
) -> None:
    versions = {"1.0.0": {"deprecated": "passez à demo2"}, "2.0.0-rc.1": {}}
    serve(respx_mock, "demo", packument(versions, {"latest": "1.0.0", "next": "2.0.0-rc.1"}))
    info = info_of(lookup)
    assert info.deprecated == "passez à demo2"
    assert info.latest == "1.0.0"


def test_a_package_whose_versions_were_all_unpublished(
    respx_mock: respx.MockRouter, lookup: Lookup
) -> None:
    document = {
        "name": "demo",
        "time": {
            "created": "2020-01-01T00:00:00.000Z",
            "unpublished": {"time": "2020-02-01T00:00:00.000Z", "versions": ["1.0.0"]},
        },
    }
    serve(respx_mock, "demo", document)
    info = info_of(lookup)
    assert info.versions == ()
    assert info.latest is None
    assert info.deprecated == "toutes ses versions ont été dépubliées du registre npm."


# -- adresses et réponses qu'on ne sait pas lire ------------------------------------


def test_a_private_registry(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    base = "https://npm.example/repository/npm"
    respx_mock.get(f"{base}/@corp%2Fdemo").respond(200, json=packument({"1.0.0": {}}))
    [info] = lookup(Npm, "@corp/demo", base_url=base + "/")
    assert isinstance(info, PackageInfo), info
    assert info.latest == "1.0.0"
    assert info.url is None


@pytest.mark.parametrize(
    ("content", "detail"),
    [
        (b"pas du json", "Expecting value"),
        (b"[1, 2]", "objet JSON attendu, pas list"),
        (json.dumps({"versions": {"1.0.0": "texte"}}).encode(), "objet JSON attendu, pas str"),
        (json.dumps({"dist-tags": ["latest"]}).encode(), "objet JSON attendu, pas list"),
    ],
)
def test_an_unreadable_response_is_inconclusive(
    respx_mock: respx.MockRouter, lookup: Lookup, content: bytes, detail: str
) -> None:
    serve(respx_mock, "demo", content)
    [error] = lookup(Npm, "demo")
    assert isinstance(error, RegistryError)
    assert str(error).startswith(f"npm : réponse illisible pour demo ({detail}")


def test_not_found(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    respx_mock.get(f"{REGISTRY}/@corp%2Fprive").respond(404, json={"error": "Not found"})
    [error] = lookup(Npm, "@corp/prive")
    assert isinstance(error, PackageNotFound)
    assert str(error) == "@corp/prive est introuvable sur npm : paquet privé, ou nom mal écrit ?"


@pytest.mark.network
def test_the_real_npm(lookup: Lookup) -> None:
    joi, missing = lookup(
        Npm, "@hapi/joi", "@forceupdate/paquet-qui-n-existe-pas", cache=Cache(None)
    )
    assert isinstance(joi, PackageInfo), joi
    assert joi.deprecated == "Switch to 'npm install joi'"
    assert joi.tags["latest"] == "17.1.1"
    assert joi.latest == "17.1.1"
    release = joi.get("17.1.1")
    assert release is not None
    assert release.published == datetime(2020, 3, 14, 0, 3, 53, 591000, tzinfo=UTC)
    assert isinstance(missing, PackageNotFound)
