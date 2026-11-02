"""Le client Maven : ``maven-metadata.xml`` de Maven Central, de Google Maven et du portail des
plugins Gradle ; la dernière stable calculée (``<release>`` peut être une pré-version)."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from forceupdate.models import Ecosystem
from forceupdate.net import Cache
from forceupdate.registries import PackageInfo, PackageNotFound, RegistryError
from forceupdate.registries.maven import (
    GOOGLE,
    GRADLE_PLUGINS,
    Maven,
    coordinates,
    parse_metadata,
    relocation,
    repository,
)

FIXTURES = Path(__file__).parent / "fixtures" / "maven"
CENTRAL = "https://repo1.maven.org/maven2"
Lookup = Callable[..., list[Any]]

METADATA = b"""<?xml version="1.0" encoding="UTF-8"?>
<metadata>
  <groupId>org.demo</groupId>
  <artifactId>demo</artifactId>
  <versioning>
    <latest>2.0.0-beta1</latest>
    <release>2.0.0-beta1</release>
    <versions>
      <version>1.0</version>
      <version>1.10</version>
      <version>1.9</version>
      <version>2.0.0-beta1</version>
    </versions>
    <lastUpdated>20260101000000</lastUpdated>
  </versioning>
</metadata>
"""


@pytest.fixture(autouse=True)
def _no_poms(request: pytest.FixtureRequest) -> None:
    """Le ``pom`` de la dernière version (sa ``<relocation>``, E34) : introuvable, sauf dans les
    tests qui le servent (``serve_poms``). Pas pour un test ``network`` (le vrai dépôt)."""
    if request.node.get_closest_marker("network") is not None:
        return
    respx_mock: respx.MockRouter = request.getfixturevalue("respx_mock")
    respx_mock.get(url__regex=r"\.pom$", name="poms").respond(404)


def serve_poms(respx_mock: respx.MockRouter, poms: dict[str, str]) -> None:
    """Sert ces ``pom`` (adresse → contenu) ; 404 pour les autres."""

    def respond(request: httpx.Request) -> httpx.Response:
        text = poms.get(str(request.url))
        return httpx.Response(404) if text is None else httpx.Response(200, text=text)

    respx_mock.routes["poms"].side_effect = respond


def serve(respx_mock: respx.MockRouter, url: str, content: bytes) -> respx.Route:
    return respx_mock.get(url).respond(200, content=content, headers={"content-type": "text/xml"})


def recorded(respx_mock: respx.MockRouter, name: str) -> respx.Route:
    """Sert la réponse enregistrée par ``tests/fixtures/record.py``."""
    group, artifact = coordinates(name)
    url = f"{repository(name)}/{group.replace('.', '/')}/{artifact}/maven-metadata.xml"
    path = FIXTURES / f"{name.replace(':', '__')}.xml"
    return serve(respx_mock, url, path.read_bytes())


def info_of(lookup: Lookup, name: str) -> PackageInfo:
    [info] = lookup(Maven, name)
    assert isinstance(info, PackageInfo), info
    return info


def test_parse_metadata() -> None:
    assert [v.version for v in parse_metadata(METADATA.decode())] == [
        "1.0",
        "1.10",
        "1.9",
        "2.0.0-beta1",
    ]
    with pytest.raises(ValueError, match="maven-metadata"):
        parse_metadata("<html><body>maintenance</body></html>")
    with pytest.raises(ValueError, match="XML invalide"):
        parse_metadata("pas du XML")


@pytest.mark.parametrize(
    ("name", "where", "url"),
    [
        ("junit:junit", CENTRAL, f"{CENTRAL}/junit/junit/maven-metadata.xml"),
        (
            "org.apache.logging.log4j:log4j-core",
            CENTRAL,
            f"{CENTRAL}/org/apache/logging/log4j/log4j-core/maven-metadata.xml",
        ),
        (
            "androidx.annotation:annotation",
            GOOGLE,
            f"{GOOGLE}/androidx/annotation/annotation/maven-metadata.xml",
        ),
        (
            "com.android.tools.build:gradle",
            GOOGLE,
            f"{GOOGLE}/com/android/tools/build/gradle/maven-metadata.xml",
        ),
        ("com.google.firebase:firebase-bom", GOOGLE, None),
        ("com.google.android.material:material", GOOGLE, None),
        ("com.google.android:android", CENTRAL, None),  # l'ancien android.jar est sur Central
        ("com.google.guava:guava", CENTRAL, None),
        (
            "org.springframework.boot",
            GRADLE_PLUGINS,
            f"{GRADLE_PLUGINS}/org/springframework/boot/org.springframework.boot.gradle.plugin/"
            "maven-metadata.xml",
        ),
    ],
)
def test_the_repository_of_an_artifact(name: str, where: str, url: str | None) -> None:
    assert repository(name) == where
    if url is not None:
        assert Maven(None, Cache(None)).url_for(name) == url  # type: ignore[arg-type]


# -- réponses enregistrées -----------------------------------------------------


def test_log4j_core(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    route = recorded(respx_mock, "org.apache.logging.log4j:log4j-core")
    info = info_of(lookup, "org.apache.logging.log4j:log4j-core")
    assert info.ecosystem is Ecosystem.MAVEN
    assert info.url == "https://central.sonatype.com/artifact/org.apache.logging.log4j/log4j-core"
    # <release> est 3.0.0-beta3 : une pré-version, pas la dernière stable.
    assert info.latest == "2.26.1"
    versions = [v.version for v in info.versions]
    assert versions.index("2.0-beta9") < versions.index("2.0-rc1") < versions.index("2.0")
    assert versions.index("2.14.1") < versions.index("2.15.0") < versions.index("2.17.1")
    assert info.get("2.14.1") is not None
    assert all(v.published is None and not v.yanked for v in info.versions)
    assert route.call_count == 1


def test_guava_flavors(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    recorded(respx_mock, "com.google.guava:guava")
    info = info_of(lookup, "com.google.guava:guava")
    assert info.latest == "33.7.2-jre"
    assert info.get("32.0.0-android") is not None and info.get("r03") is not None


def test_google_maven(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    recorded(respx_mock, "androidx.annotation:annotation")
    info = info_of(lookup, "androidx.annotation:annotation")
    assert info.latest == "1.11.0"
    assert info.url == "https://maven.google.com/web/index.html#androidx.annotation:annotation"


def test_a_gradle_plugin(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    recorded(respx_mock, "org.springframework.boot")
    info = info_of(lookup, "org.springframework.boot")
    assert info.get("2.6.6") is not None and info.latest is not None
    assert not info.latest.lower().endswith(("-rc1", "-m1"))
    assert info.url == "https://plugins.gradle.org/plugin/org.springframework.boot"


# -- formats --------------------------------------------------------------------------


def test_only_prereleases(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    serve(
        respx_mock,
        f"{CENTRAL}/org/demo/demo/maven-metadata.xml",
        METADATA.replace(b"<version>1.", b"<version>0.1-alpha-1."),
    )
    info = info_of(lookup, "org.demo:demo")
    assert info.latest is None


def test_sorted_by_version(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    serve(respx_mock, f"{CENTRAL}/org/demo/demo/maven-metadata.xml", METADATA)
    info = info_of(lookup, "org.demo:demo")
    assert [v.version for v in info.versions] == ["1.0", "1.9", "1.10", "2.0.0-beta1"]
    assert info.latest == "1.10"


def test_an_unreadable_answer_is_inconclusive(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    serve(respx_mock, f"{CENTRAL}/org/demo/demo/maven-metadata.xml", b"<html>maintenance</html>")
    [error] = lookup(Maven, "org.demo:demo")
    assert isinstance(error, RegistryError)
    assert str(error).startswith("Maven Central : réponse illisible pour org.demo:demo")


@pytest.mark.parametrize(
    ("name", "url", "where"),
    [
        ("org.nope:nope", f"{CENTRAL}/org/nope/nope/maven-metadata.xml", "Maven Central"),
        ("androidx.nope:nope", f"{GOOGLE}/androidx/nope/nope/maven-metadata.xml", "Google Maven"),
        (
            "org.nope",
            f"{GRADLE_PLUGINS}/org/nope/org.nope.gradle.plugin/maven-metadata.xml",
            "le portail des plugins Gradle",
        ),
    ],
)
def test_not_found(
    respx_mock: respx.MockRouter, lookup: Lookup, name: str, url: str, where: str
) -> None:
    respx_mock.get(url).respond(404, text="<html>404 Not Found</html>")
    [error] = lookup(Maven, name)
    assert isinstance(error, PackageNotFound)
    assert str(error) == f"{name} est introuvable sur {where} : artefact privé, ou nom mal écrit ?"


def test_another_repository_has_no_page(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    serve(respx_mock, "https://nexus.maison.test/maven/org/demo/demo/maven-metadata.xml", METADATA)
    [info] = lookup(Maven, "org.demo:demo", base_url="https://nexus.maison.test/maven/")
    assert isinstance(info, PackageInfo)
    assert info.url is None


def test_cached(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    route = serve(respx_mock, f"{CENTRAL}/org/demo/demo/maven-metadata.xml", METADATA)
    first = info_of(lookup, "org.demo:demo")
    second = info_of(lookup, "org.demo:demo")
    assert route.call_count == 1
    assert second.versions == first.versions


@pytest.mark.network
def test_the_real_repositories(lookup: Lookup) -> None:
    log4j, androidx, plugin, missing = lookup(
        Maven,
        "org.apache.logging.log4j:log4j-core",
        "androidx.annotation:annotation",
        "org.springframework.boot",
        "org.forceupdate:artefact-qui-n-existe-pas",
        cache=Cache(None),
    )
    assert isinstance(log4j, PackageInfo), log4j
    assert log4j.get("2.14.1") is not None and log4j.latest is not None
    assert isinstance(androidx, PackageInfo), androidx
    assert androidx.get("1.3.0") is not None
    assert isinstance(plugin, PackageInfo), plugin
    assert plugin.get("2.6.6") is not None
    assert isinstance(missing, PackageNotFound)


RELOCATED = """<project>
  <modelVersion>4.0.0</modelVersion>
  <groupId>mysql</groupId>
  <artifactId>mysql-connector-java</artifactId>
  <version>8.0.33</version>
  <distributionManagement>
    <relocation>
      <groupId>com.mysql</groupId>
      <artifactId>mysql-connector-j</artifactId>
      <message>MySQL Connector/J artifacts moved to reverse-DNS compliant Maven 2+
        coordinates.</message>
    </relocation>
  </distributionManagement>
</project>
"""


def test_relocation() -> None:
    assert relocation(RELOCATED) == (
        "com.mysql:mysql-connector-j : MySQL Connector/J artifacts moved to reverse-DNS "
        "compliant Maven 2+ coordinates."
    )
    same_group = "<project><groupId>g</groupId><artifactId>a</artifactId><distributionManagement>"
    same_group += "<relocation><artifactId>b</artifactId><version>2.0</version></relocation>"
    same_group += "</distributionManagement></project>"
    assert relocation(same_group) == "g:b:2.0"
    assert relocation("<project><groupId>g</groupId></project>") is None
    assert relocation("pas du xml") is None


def test_a_relocated_artifact_is_deprecated(respx_mock: respx.MockRouter, lookup: Lookup) -> None:
    """mysql:mysql-connector-java (vérifié le 2026-11-02 : le pom de 8.0.33 a une relocation)."""
    serve(respx_mock, f"{CENTRAL}/org/demo/demo/maven-metadata.xml", METADATA)
    serve_poms(respx_mock, {f"{CENTRAL}/org/demo/demo/1.10/demo-1.10.pom": RELOCATED})
    info = info_of(lookup, "org.demo:demo")
    assert info.latest == "1.10"
    assert info.deprecated == (
        "déplacé vers com.mysql:mysql-connector-j : MySQL Connector/J artifacts moved to "
        "reverse-DNS compliant Maven 2+ coordinates."
    )


def test_the_pom_is_asked_once_and_kept(
    respx_mock: respx.MockRouter, lookup: Lookup, cache: Cache
) -> None:
    serve(respx_mock, f"{CENTRAL}/org/demo/demo/maven-metadata.xml", METADATA)
    serve_poms(respx_mock, {f"{CENTRAL}/org/demo/demo/1.10/demo-1.10.pom": RELOCATED})
    info_of(lookup, "org.demo:demo")
    assert respx_mock.routes["poms"].call_count == 1
    # Hors ligne, depuis le cache.
    [info] = lookup(Maven, "org.demo:demo", offline=True)
    assert info.deprecated is not None
