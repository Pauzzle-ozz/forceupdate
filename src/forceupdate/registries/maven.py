"""Le client Maven : ``maven-metadata.xml`` de Maven Central, de Google Maven (Android) et du
portail des plugins Gradle.

``GET {dépôt}/{groupe en chemin}/{artefact}/maven-metadata.xml`` : le fichier que lisent Maven et
Gradle pour connaître les versions d'un artefact. Vérifié le 2026-11-01 :

- ``<versioning><versions>`` : toutes les versions publiées, dans l'ordre de publication (pas dans
  l'ordre des versions) ; ``<latest>`` et ``<release>`` sont la dernière publiée, **pré-version
  comprise** (log4j-core : ``3.0.0-beta3`` ; maven-artifact : ``4.0.0-rc-7``) : la dernière stable
  est donc calculée (``versions.maven``) ; ``<lastUpdated>`` date le fichier, pas chaque version.
  Le dépôt ne date pas les versions : ``PackageVersion.published`` reste vide (aucun contrôle ne
  s'en sert) ;
- un artefact inconnu : 404 (une page HTML) ;
- pas de dépréciation ni de retrait : un artefact « déplacé » (``<relocation>`` du ``pom`` d'une
  version) n'est pas vu.

Les dépôts : **Google Maven** (``https://dl.google.com/android/maven2``, ``max-age=86400``) pour
``androidx.*``, ``com.android.*``, ``com.google.android.*``, ``com.google.firebase`` et
``com.google.gms``, qui n'y sont que là ; **le portail des plugins Gradle**
(``https://plugins.gradle.org/m2``, ``max-age=43200``) pour un plugin, nommé par son ``id`` :
l'artefact « marqueur » ``{id}:{id}.gradle.plugin`` (le portail renvoie à Maven Central ce qu'il
n'a pas) ; **Maven Central** (``https://repo1.maven.org/maven2``) pour le reste. Un dépôt privé
(``<repositories>``, ``repositories { }``) n'est pas lu : ses artefacts sont cherchés là.
"""

from datetime import datetime

from forceupdate.models import Ecosystem
from forceupdate.net.http import Response
from forceupdate.parsers.base import ParseError
from forceupdate.parsers.gradle import plugin_id
from forceupdate.parsers.xml_spans import parse
from forceupdate.registries.base import PackageInfo, PackageVersion, Registry, sorted_versions
from forceupdate.versions.maven import MAVEN

GOOGLE = "https://dl.google.com/android/maven2"
GRADLE_PLUGINS = "https://plugins.gradle.org/m2"
_GOOGLE_GROUPS = ("androidx.", "com.android.", "com.google.android.")
_GOOGLE_EXACT = ("com.google.firebase", "com.google.gms")


def coordinates(name: str) -> tuple[str, str]:
    """Le groupe et l'artefact de ``name`` : ``groupe:artefact``, ou l'``id`` d'un plugin Gradle
    (son marqueur ``{id}:{id}.gradle.plugin``)."""
    if plugin_id(name):
        return name, f"{name}.gradle.plugin"
    group, _, artifact = name.partition(":")
    return group, artifact


def repository(name: str) -> str:
    """Le dépôt public où chercher ``name`` (voir la docstring du module)."""
    if plugin_id(name):
        return GRADLE_PLUGINS
    group = name.partition(":")[0]
    if group.startswith(_GOOGLE_GROUPS) or any(
        group == exact or group.startswith(f"{exact}.") for exact in _GOOGLE_EXACT
    ):
        return GOOGLE
    return Maven.base_url


def parse_metadata(text: str) -> list[PackageVersion]:
    """Les versions d'un ``maven-metadata.xml``. Lève ``ValueError`` si ce n'en est pas un."""
    try:
        root = parse(text)
    except ParseError as error:
        raise ValueError(str(error)) from error
    if root.tag != "metadata":
        raise ValueError("pas un maven-metadata.xml (<metadata> attendu)")
    found = [
        element.text
        for versioning in root.findall("versioning")
        for element in versioning.path("versions", "version")
        if element.text
    ]
    return [PackageVersion(version=version) for version in dict.fromkeys(found)]


class Maven(Registry):
    ecosystem = Ecosystem.MAVEN
    label = "Maven Central"
    base_url = "https://repo1.maven.org/maven2"

    def normalize(self, name: str) -> str:
        return name.strip()

    def url_for(self, name: str) -> str:
        group, artifact = coordinates(name)
        base = repository(name) if self.base_url == Maven.base_url else self.base_url
        return f"{base}/{group.replace('.', '/')}/{artifact}/maven-metadata.xml"

    def page_url(self, name: str) -> str | None:
        if self.base_url != Maven.base_url:
            return None
        group, artifact = coordinates(name)
        where = repository(name)
        if where == GRADLE_PLUGINS:
            return f"https://plugins.gradle.org/plugin/{name}"
        if where == GOOGLE:
            return f"https://maven.google.com/web/index.html#{group}:{artifact}"
        return f"https://central.sonatype.com/artifact/{group}/{artifact}"

    def _not_found(self, name: str) -> str:
        where = {GOOGLE: "Google Maven", GRADLE_PLUGINS: "le portail des plugins Gradle"}.get(
            repository(name), self.label
        )
        return f"{name} est introuvable sur {where} : artefact privé, ou nom mal écrit ?"

    def parse(self, name: str, response: Response, fetched_at: datetime) -> PackageInfo:
        versions = sorted_versions(
            self.ecosystem, parse_metadata(response.content.decode("utf-8", errors="replace"))
        )
        return PackageInfo(
            ecosystem=self.ecosystem,
            name=name,
            versions=versions,
            latest=MAVEN.latest(v.version for v in versions),
            url=self.page_url(name),
            fetched_at=fetched_at,
        )
