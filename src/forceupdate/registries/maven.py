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
- pas de retrait ; **un artefact déplacé** (E34) : le ``pom`` de sa dernière version a une
  ``<distributionManagement><relocation>`` (mysql:mysql-connector-java 8.0.33 : vers
  ``com.mysql:mysql-connector-j``, avec un ``<message>``, vérifié le 2026-11-02) ; c'est sa
  dépréciation, qui cite le remplaçant. Une requête de plus par artefact : ``…/{version}/{artefact}-
  {version}.pom`` (``pom``, gardé 7 jours en cache, qui sert aussi aux versions gérées par un parent
  ou un BOM distant : ``managed``).

Les dépôts : **Google Maven** (``https://dl.google.com/android/maven2``, ``max-age=86400``) pour
``androidx.*``, ``com.android.*``, ``com.google.android.*``, ``com.google.firebase`` et
``com.google.gms``, qui n'y sont que là ; **le portail des plugins Gradle**
(``https://plugins.gradle.org/m2``, ``max-age=43200``) pour un plugin, nommé par son ``id`` :
l'artefact « marqueur » ``{id}:{id}.gradle.plugin`` (le portail renvoie à Maven Central ce qu'il
n'a pas) ; **Maven Central** (``https://repo1.maven.org/maven2``) pour le reste. Un dépôt déclaré
(``<repositories>``, ``repositories { }``, ``settings.xml``) : l'aiguillage (``routing/maven.py``,
E33) y demande ses artefacts, par ces mêmes classes à son adresse.
"""

import asyncio
import dataclasses
from datetime import datetime
from typing import Any

from forceupdate.models import Ecosystem
from forceupdate.net.cache import CacheKind
from forceupdate.net.http import Response
from forceupdate.parsers.base import ParseError
from forceupdate.parsers.gradle import plugin_id
from forceupdate.parsers.xml_spans import parse
from forceupdate.registries.base import (
    PackageInfo,
    PackageVersion,
    Registry,
    RegistryError,
    sorted_versions,
)
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


def relocation(text: str) -> str | None:
    """Le remplaçant que donne la ``<relocation>`` d'un ``pom`` (``com.mysql:mysql-connector-j``,
    et sa version si elle est écrite), et son message ; ``None`` sans relocation, ou pour un
    ``pom`` illisible. Un ``groupId`` ou un ``artifactId`` absent est celui de l'artefact."""
    try:
        root = parse(text)
    except ParseError:
        return None
    element = next(iter(root.path("distributionManagement", "relocation")), None)
    if element is None:
        return None
    parent = root.find("parent")
    group = element.child_text("groupId") or root.child_text("groupId")
    if not group and parent is not None:
        group = parent.child_text("groupId")
    artifact = element.child_text("artifactId") or root.child_text("artifactId") or ""
    target = f"{group or ''}:{artifact}"
    version = element.child_text("version")
    if version:
        target += f":{version}"
    message = " ".join((element.child_text("message") or "").split())
    return f"{target} : {message}" if message else target


class Maven(Registry):
    ecosystem = Ecosystem.MAVEN
    label = "Maven Central"
    base_url = "https://repo1.maven.org/maven2"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._poms: dict[str, asyncio.Future[str | None]] = {}

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

    async def _complete(self, name: str, info: PackageInfo) -> PackageInfo:
        """La ``<relocation>`` du ``pom`` de la dernière version : la dépréciation de l'artefact
        (voir la docstring du module). Rien pour un plugin Gradle (son marqueur n'en a pas), ni si
        le ``pom`` ne se lit pas."""
        if info.latest is None or plugin_id(name):
            return info
        try:
            text = await self.pom(name, info.latest)
        except RegistryError:
            return info
        moved = relocation(text) if text is not None else None
        if moved is None:
            return info
        return dataclasses.replace(info, deprecated=f"déplacé vers {moved}")

    def pom_url(self, name: str, version: str) -> str:
        group, artifact = coordinates(name)
        base = repository(name) if self.base_url == Maven.base_url else self.base_url
        return f"{base}/{group.replace('.', '/')}/{artifact}/{version}/{artifact}-{version}.pom"

    async def pom(self, name: str, version: str) -> str | None:
        """Le ``pom`` de ``version`` de ``name`` ; ``None`` si le dépôt ne l'a pas. Une seule
        requête par fichier dans la session, gardé 7 jours en cache (un ``pom`` publié ne change
        pas). Lève ``RegistryError`` (``AccessRefused`` pour un dépôt déclaré qui refuse)."""
        url = self.pom_url(name, version)
        lookup = self._poms.get(url)
        if lookup is None:
            lookup = self._poms[url] = asyncio.ensure_future(self._fetch_pom(url, name, version))
        return await asyncio.shield(lookup)

    async def _fetch_pom(self, url: str, name: str, version: str) -> str | None:
        entry = self._cache.get(CacheKind.FILES, url, stale_ok=self._http.offline)
        if entry is not None and isinstance(entry.value, dict) and "text" in entry.value:
            text = entry.value["text"]
            return text if isinstance(text, str) else None
        if self._http.offline:
            raise RegistryError(
                f"{self.label} : mode hors ligne, et le pom de {name} {version} n'est pas dans "
                "le cache."
            )
        response = await self._get(url, name, found=True)
        text = None if response is None else response.content.decode("utf-8", errors="replace")
        self._cache.set(CacheKind.FILES, url, {"text": text})
        return text
