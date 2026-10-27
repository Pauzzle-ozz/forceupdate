"""Le client PyPI : l'API Simple en JSON, versions retirées, fichiers rangés par version,
statut du projet."""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import respx

from forceupdate.models import Ecosystem
from forceupdate.net import Cache
from forceupdate.registries import PackageInfo, PackageNotFound, RegistryError
from forceupdate.registries.pypi import ACCEPT, PyPI

FIXTURES = Path(__file__).parent / "fixtures" / "pypi"

Lookup = Callable[..., list[Any]]


def serve(
    respx_mock: respx.MockRouter,
    name: str,
    payload: dict[str, Any] | bytes,
    *,
    content_type: str = ACCEPT,
    base_url: str = "https://pypi.org",
) -> respx.Route:
    content = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return respx_mock.get(f"{base_url}/simple/{name}/").respond(
        200, content=content, headers={"content-type": content_type}
    )


def recorded(respx_mock: respx.MockRouter, name: str) -> respx.Route:
    """Sert la réponse enregistrée par ``tests/fixtures/record.py``."""
    return serve(respx_mock, name, (FIXTURES / f"{name}.json").read_bytes())


def simple(
    versions: list[str] | None,
    files: list[dict[str, Any]],
    *,
    status: dict[str, str] | None = None,
    api: str = "1.4",
) -> dict[str, Any]:
    """Une page de l'API Simple, comme PyPI la sert."""
    page: dict[str, Any] = {"meta": {"_last-serial": 1, "api-version": api}, "name": "demo"}
    if versions is not None:
        page["versions"] = versions
    page["files"] = files
    if status is not None:
        page["project-status"] = status
    return page


def file(filename: str, *, yanked: bool | str = False, uploaded: str = "2024-01-01") -> dict:
    return {
        "filename": filename,
        "url": f"https://files.pythonhosted.org/{filename}",
        "hashes": {"sha256": "0" * 64},
        "requires-python": None,
        "size": 1,
        "upload-time": f"{uploaded}T12:00:00.000000Z",
        "yanked": yanked,
    }


def info_of(lookup: Lookup, name: str = "demo", **options: Any) -> PackageInfo:
    [info] = lookup(PyPI, name, **options)
    assert isinstance(info, PackageInfo), info
    return info


def day(text: str) -> datetime:
    return datetime.fromisoformat(f"{text}T12:00:00+00:00")


# -- réponses enregistrées -----------------------------------------------------


def test_flask(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    route = recorded(respx_mock, "flask")
    info = info_of(lookup, "flask")
    assert route.calls.last.request.headers["accept"] == ACCEPT
    assert info.ecosystem is Ecosystem.PYPI
    assert info.name == "flask"
    assert len(info.versions) == 64
    assert info.versions[0].version == "0.1"
    assert info.latest == "3.1.3"  # à la date de l'enregistrement
    assert info.deprecated is None
    assert info.tags == {}
    assert info.url == "https://pypi.org/project/flask/"
    assert datetime.now(UTC) - info.fetched_at < timedelta(minutes=1)
    release = info.get("2.0.1")
    assert release is not None
    # La date d'une version : celle de son premier fichier (la wheel, puis le sdist).
    assert release.published == datetime(2021, 5, 21, 15, 53, 8, 128824, tzinfo=UTC)
    assert not release.yanked
    assert not any(v.yanked for v in info.versions)
    assert all(v.published is not None for v in info.versions)


def test_requests_has_two_yanked_versions(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    recorded(respx_mock, "requests")
    info = info_of(lookup, "requests")
    yanked = [(v.version, v.yanked_reason) for v in info.versions if v.yanked]
    reason = "Yanked due to conflicts with CVE-2024-35195 mitigation"
    assert yanked == [("2.32.0", reason), ("2.32.1", reason)]
    assert "2.32.0" not in info.available()
    assert "2.31.0" in info.available()
    assert info.latest == "2.34.2"  # à la date de l'enregistrement ; 2.34.0.dev1 est listée
    # Le sdist de 2.0.1 a été publié trois semaines avant sa wheel.
    release = info.get("2.0.1")
    assert release is not None
    assert release.published == datetime(2013, 10, 24, 14, 33, 21, 606209, tzinfo=UTC)


def test_aioredis_is_archived(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    recorded(respx_mock, "aioredis")
    info = info_of(lookup, "aioredis")
    assert info.deprecated == "projet archivé sur PyPI : il ne recevra plus de nouvelles versions."
    assert info.latest == "2.0.1"
    assert not any(v.yanked for v in info.versions)


# -- noms et adresses ------------------------------------------------------------


def test_the_name_is_normalized(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    route = serve(respx_mock, "flask-login", simple(["1.0"], [file("Flask-Login-1.0.tar.gz")]))
    first, second = lookup(PyPI, "Flask_Login", "flask.login")
    assert first == second
    assert first.name == "flask-login"
    assert first.url == "https://pypi.org/project/flask-login/"
    assert route.call_count == 1


def test_a_private_index(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    base = "https://pypi.example/root"
    serve(respx_mock, "demo", simple(["1.0"], []), base_url=base)
    info = info_of(lookup, base_url=base + "/")
    assert info.latest == "1.0"
    assert info.url is None


# -- les fichiers d'une version ---------------------------------------------------


def test_a_version_is_yanked_when_all_its_files_are(
    respx_mock: respx.MockRouter, lookup: Lookup
) -> None:
    files = [
        file("demo-1.0-py3-none-any.whl", yanked="cassée"),
        file("demo-1.0.tar.gz", yanked="cassée"),
        file("demo-1.1-py3-none-any.whl", yanked="une wheel seulement"),
        file("demo-1.1.tar.gz"),
        file("demo-1.2.tar.gz", yanked=True),
    ]
    serve(respx_mock, "demo", simple(["1.0", "1.1", "1.2"], files))
    info = info_of(lookup)
    assert [(v.version, v.yanked, v.yanked_reason) for v in info.versions] == [
        ("1.0", True, "cassée"),
        ("1.1", False, None),
        ("1.2", True, None),
    ]
    assert info.available() == ["1.1"]
    assert info.latest == "1.1"


def test_files_named_with_another_spelling_of_the_version(
    respx_mock: respx.MockRouter, lookup: Lookup
) -> None:
    # Le nom d'une wheel normalise la version : 1.8c1 devient 1.8rc1, 69.4.0 peut être 69.4.
    files = [
        file("Demo-1.8rc1-py2.py3-none-any.whl", yanked="x", uploaded="2015-03-02"),
        file("Demo-1.8c1.tar.gz", yanked="x", uploaded="2015-03-01"),
        file("demo-69.4-py3-none-any.whl", uploaded="2024-04-02"),
        file("demo-69.4.0.tar.gz", uploaded="2024-04-03"),
    ]
    serve(respx_mock, "demo", simple(["1.8c1", "69.4.0"], files))
    info = info_of(lookup)
    old, new = info.versions
    assert (old.version, old.yanked, old.published) == ("1.8c1", True, day("2015-03-01"))
    assert (new.version, new.yanked, new.published) == ("69.4.0", False, day("2024-04-02"))
    assert info.get("1.8rc1") is old
    assert info.get("69.4") is new


def test_old_formats_and_unreadable_versions(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    # Les vieux paquets de pytz : des versions hors PEP 440 (2004d), des .tar.bz2, des .exe.
    files = [
        file("pytz-2004d.tar.gz", uploaded="2004-04-01"),
        file("pytz-2005k.tar.bz2", uploaded="2005-08-02"),
        file("pytz-2005k.win32.exe", uploaded="2005-08-01"),
        file("pytz-2013b.tar.gz", uploaded="2013-03-01"),
        file("pytz-2013.7-py2.7.egg", uploaded="2013-10-01"),
        file("pytz-2013.7.zip", yanked="mauvais zip", uploaded="2013-10-02"),
    ]
    serve(respx_mock, "pytz", simple(["2004d", "2005k", "2013b", "2013.7"], files))
    info = info_of(lookup, "pytz")
    # Les versions lisibles d'abord, dans leur ordre (2013b est une bêta de 2013), puis le reste.
    assert [(v.version, v.published, v.yanked) for v in info.versions] == [
        ("2013b", day("2013-03-01"), False),
        ("2013.7", day("2013-10-01"), False),
        ("2004d", day("2004-04-01"), False),
        ("2005k", day("2005-08-01"), False),
    ]
    # Gardées, mais jamais candidates : la dernière stable est 2013.7.
    assert "2004d" in info.available()
    assert info.latest == "2013.7"
    assert info.get("2004d") is info.versions[2]


def test_a_name_with_dashes_written_in_several_ways(
    respx_mock: respx.MockRouter, lookup: Lookup
) -> None:
    files = [
        file("python-dateutil-1.4.1.win32.exe", uploaded="2008-01-01"),
        file("python_dateutil-2.8.2-py2.7.egg", uploaded="2021-07-09"),
        file("python_dateutil-2.8.2-py2.py3-none-any.whl", uploaded="2021-07-08"),
        file("python_dateutil-2.9.0.post0.tar.gz", uploaded="2024-03-01"),
        file("dateutil-3.0.tar.gz", uploaded="2025-01-01"),
    ]
    listed = ["1.4.1", "2.8.2", "2.9.0.post0", "3.0"]
    serve(respx_mock, "python-dateutil", simple(listed, files))
    info = info_of(lookup, "python-dateutil")
    assert [(v.version, v.published) for v in info.versions] == [
        ("1.4.1", day("2008-01-01")),
        ("2.8.2", day("2021-07-08")),
        ("2.9.0.post0", day("2024-03-01")),
        # Un fichier qui ne porte pas le nom du projet n'est rangé nulle part.
        ("3.0", None),
    ]


def test_a_version_without_files_is_neither_dated_nor_yanked(
    respx_mock: respx.MockRouter, lookup: Lookup
) -> None:
    serve(respx_mock, "demo", simple(["1.0", "2.0"], [file("demo-1.0.tar.gz", yanked="x")]))
    info = info_of(lookup)
    assert [(v.version, v.yanked, v.published) for v in info.versions] == [
        ("1.0", True, day("2024-01-01")),
        ("2.0", False, None),
    ]
    assert info.latest == "2.0"


@pytest.mark.parametrize(
    ("listed", "latest"),
    [
        (["1.0", "1.1", "2.0b1", "2.0rc1"], "1.1"),
        (["2.0b1", "2.0rc1"], None),
        ([], None),
        (["1.10", "1.9"], "1.10"),
    ],
)
def test_latest_skips_pre_releases(
    respx_mock: respx.MockRouter, lookup: Lookup, listed: list[str], latest: str | None
) -> None:
    serve(respx_mock, "demo", simple(listed, []))
    assert info_of(lookup).latest == latest


def test_versions_read_from_filenames_without_the_versions_key(
    respx_mock: respx.MockRouter, lookup: Lookup
) -> None:
    # Un miroir en API 1.0 (avant PEP 700) ne donne pas la liste des versions.
    files = [
        file("demo-1.0.tar.gz", uploaded="2020-01-01"),
        file("Demo-1.1rc1-py3-none-any.whl", uploaded="2020-02-01"),
        file("demo-1.1.tar.gz", uploaded="2020-03-01"),
        file("demo-1.1-py3-none-any.whl", uploaded="2020-03-02"),
        file("demo.exe"),
    ]
    serve(respx_mock, "demo", simple(None, files, api="1.0"))
    info = info_of(lookup)
    assert [(v.version, v.published) for v in info.versions] == [
        ("1.0", day("2020-01-01")),
        ("1.1rc1", day("2020-02-01")),
        ("1.1", day("2020-03-01")),
    ]
    assert info.latest == "1.1"


# -- statut du projet (PEP 792) --------------------------------------------------


@pytest.mark.parametrize(
    ("status", "message"),
    [
        ({"status": "active"}, None),
        (
            {"status": "archived"},
            "projet archivé sur PyPI : il ne recevra plus de nouvelles versions.",
        ),
        (
            {"status": "archived", "reason": "remplacé par redis"},
            "projet archivé sur PyPI : il ne recevra plus de nouvelles versions"
            " (remplacé par redis).",
        ),
        (
            {"status": "deprecated", "reason": " use demo2 "},
            "projet déclaré déprécié sur PyPI (use demo2).",
        ),
        ({"status": "frozen"}, None),
    ],
)
def test_project_status(
    respx_mock: respx.MockRouter, lookup: Lookup, status: dict[str, str], message: str | None
) -> None:
    serve(respx_mock, "demo", simple(["1.0"], [file("demo-1.0.tar.gz")], status=status))
    info = info_of(lookup)
    assert info.deprecated == message
    assert info.latest == "1.0"


def test_a_quarantined_project(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    # En quarantaine, PyPI ne sert plus aucun fichier : rien n'est installable.
    serve(respx_mock, "demo", simple(["1.0", "1.1"], [], status={"status": "quarantined"}))
    info = info_of(lookup)
    assert info.deprecated == (
        "projet mis en quarantaine par PyPI (soupçon de code malveillant) :"
        " ses fichiers ne sont plus proposés."
    )
    assert all(
        v.yanked and v.yanked_reason == "projet en quarantaine sur PyPI" for v in info.versions
    )
    assert info.latest is None


# -- réponses qu'on ne sait pas lire ----------------------------------------------


@pytest.mark.parametrize(
    ("content", "content_type", "detail"),
    [
        (b"<html></html>", "text/html", "pas le JSON de l'API Simple (text/html)"),
        (b"{}", "", "pas le JSON de l'API Simple (sans type)"),
        (
            json.dumps(simple([], [], api="2.0")).encode(),
            ACCEPT,
            "version 2.0 de l'API Simple inconnue",
        ),
        (b"{pas du json", ACCEPT, "Expecting property name"),
        (b"[]", ACCEPT, "objet JSON attendu, pas list"),
        (json.dumps({"files": {"a": 1}}).encode(), ACCEPT, "liste JSON attendue, pas dict"),
    ],
)
def test_an_unreadable_response_is_inconclusive(
    respx_mock: respx.MockRouter, lookup: Lookup, content: bytes, content_type: str, detail: str
) -> None:
    serve(respx_mock, "demo", content, content_type=content_type)
    [error] = lookup(PyPI, "demo")
    assert isinstance(error, RegistryError)
    assert str(error).startswith(f"PyPI : réponse illisible pour demo ({detail}")


def test_not_found(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    respx_mock.get("https://pypi.org/simple/demo/").respond(404)
    [error] = lookup(PyPI, "demo")
    assert isinstance(error, PackageNotFound)
    assert str(error) == "demo est introuvable sur PyPI : paquet privé, ou nom mal écrit ?"


@pytest.mark.network
def test_the_real_pypi(tmp_path: Path, lookup: Lookup) -> None:
    flask, missing = lookup(PyPI, "Flask", "forceupdate-paquet-qui-n-existe-pas", cache=Cache(None))
    assert isinstance(flask, PackageInfo), flask
    assert flask.name == "flask"
    assert flask.latest is not None
    assert flask.latest in flask.available()
    release = flask.get("2.0.1")
    assert release is not None
    assert release.published == datetime(2021, 5, 21, 15, 53, 8, 128824, tzinfo=UTC)
    assert isinstance(missing, PackageNotFound)
