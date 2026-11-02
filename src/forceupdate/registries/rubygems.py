"""Le client RubyGems : l'index « compact » (``https://index.rubygems.org/info/{nom}``), celui que
lit Bundler.

Pourquoi l'index, et pas l'API (``https://rubygems.org/api/v1/versions/{nom}.json``) : l'index est
un fichier texte servi par un CDN, celui que lit Bundler, huit fois plus léger (186 Ko pour
nokogiri, 1,4 Mo pour l'API, qui répète la description de chaque version), et il dit ce qui
sert. Les deux taisent les versions retirées (« yanked ») : rest-client 1.6.10 à 1.6.13,
piégées en 2019 et retirées, n'y sont pas, et l'API v2 répond 404 pour elles comme pour une
version jamais publiée. Vérifié le 2026-11-01 sur ``nokogiri``, ``rack``, ``rest-client``,
``minitest`` et un nom inconnu.

Une ligne d'en-tête (``---``), puis une ligne par version et par plateforme, dans l'ordre de
publication :

    1.19.0-x86_64-linux-gnu racc:~> 1.4|checksum:f482…,ruby:< 4.1.dev&>= 3.2,rubygems:>= 3.3.22,
    created_at:2025-12-28T16:47:18Z

- la version, et sa plateforme après le premier ``-`` (une version RubyGems n'en a pas) ;
- ses dépendances, puis après ``|`` : l'empreinte, le Ruby et le RubyGems demandés, la date de
  publication (``created_at``, aussi pour les versions de 2009) ;
- un nom inconnu donne 404 ; ``Cache-Control: max-age=60``. Les noms ne sont pas normalisés :
  RubyGems les distingue tels qu'écrits.

Ce qu'on en tire :

- les versions (une par numéro, toutes plateformes confondues), datées par leur première
  publication ;
- **la dernière stable** : la plus haute version sans lettre (``Gem::Version#prerelease?``) ;
- RubyGems n'a ni dépréciation ni raison de retrait : une version retirée disparaît, la version
  utilisée est alors « inconnue du registre ».

Le Ruby demandé par chaque version (``ruby:< 4.1.dev&>= 3.2``, ses conditions séparées par ``&``)
est gardé (``PackageVersion.requires_runtime``), celui de la ligne sans plateforme d'abord : Bundler
écarte une version que le Ruby du projet ne fait pas tourner (``checks.runtimes``, E27).
"""

import asyncio
import dataclasses
from datetime import datetime
from typing import Any
from urllib.parse import quote

from forceupdate.models import Ecosystem
from forceupdate.net.http import NetworkError, Response
from forceupdate.registries.base import (
    PackageInfo,
    PackageNotFound,
    PackageVersion,
    Registry,
    RegistryError,
    parse_time,
    sorted_versions,
)
from forceupdate.versions.rubygems import RUBYGEMS


def parse_info(text: str) -> list[PackageVersion]:
    """Les versions d'un fichier ``info`` de l'index compact, une par numéro, datées par la
    première ligne qui la publie. Lève ``ValueError`` sans la ligne d'en-tête ``---``."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("pas un fichier de l'index compact (« --- » attendu)")
    found: dict[str, PackageVersion] = {}
    rubies: dict[str, str] = {}
    for line in lines[1:]:
        if not line.strip():
            continue
        head, _, rest = line.partition(" ")
        number, _, platform = head.partition("-")
        _, _, requirements = rest.partition("|")
        published = None
        for item in requirements.split(","):
            key, _, value = item.partition(":")
            if key.strip() == "created_at":
                published = parse_time(value.strip())
            elif key.strip() == "ruby" and value.strip() and (not platform or number not in rubies):
                rubies[number] = value.strip()
        previous = found.get(number)
        if previous is None or (
            published is not None and (previous.published is None or published < previous.published)
        ):
            found[number] = PackageVersion(version=number, published=published)
    return [
        dataclasses.replace(version, requires_runtime=rubies.get(version.version))
        for version in found.values()
    ]


class RubyGems(Registry):
    ecosystem = Ecosystem.RUBYGEMS
    label = "RubyGems"
    base_url = "https://index.rubygems.org"

    def normalize(self, name: str) -> str:
        return name.strip()

    def url_for(self, name: str) -> str:
        return f"{self.base_url}/info/{quote(name, safe='')}"

    def page_url(self, name: str) -> str | None:
        if self.base_url != RubyGems.base_url:
            return None
        return f"https://rubygems.org/gems/{name}"

    def parse(self, name: str, response: Response, fetched_at: datetime) -> PackageInfo:
        versions = sorted_versions(self.ecosystem, parse_info(response.content.decode("utf-8")))
        return PackageInfo(
            ecosystem=self.ecosystem,
            name=name,
            versions=versions,
            latest=RUBYGEMS.latest(v.version for v in versions),
            url=self.page_url(name),
            fetched_at=fetched_at,
        )


class GemServer(RubyGems):
    """Un serveur de gems déclaré par un ``Gemfile`` ou par la configuration de Bundler (E34) : son
    index compact, à son adresse (``/info/{nom}``), comme Bundler le lit.

    Un serveur qui ne sert pas l'index compact (seulement l'ancienne API ``/api/v1/dependencies``,
    que Bundler prend à défaut) répond 404 pour chaque gem : sur un « introuvable », son
    ``/versions`` est demandé, une fois par session ; s'il manque aussi, le constat est « non
    concluant » (forceupdate ne lit que l'index compact), pas « introuvable »."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._compact: asyncio.Future[bool] | None = None

    async def _lookup(self, name: str) -> PackageInfo:
        try:
            return await super()._lookup(name)
        except PackageNotFound:
            if self._http.offline or await self._serves_compact_index():
                raise
            raise RegistryError(
                f"{self.label} ne sert pas l'index compact de Bundler (/versions, /info/…), le "
                "seul que lit forceupdate."
            ) from None

    async def _serves_compact_index(self) -> bool:
        if self._compact is None:
            self._compact = asyncio.ensure_future(self._probe())
        return await asyncio.shield(self._compact)

    async def _probe(self) -> bool:
        # Les premiers octets suffisent : un miroir de rubygems.org a un /versions de 20 Mo.
        try:
            response = await self._http.get(
                f"{self.base_url}/versions", headers={"Range": "bytes=0-0"}, auth=self._auth
            )
        except NetworkError:
            return True  # rien de sûr : l'« introuvable » de /info reste
        return response.status_code not in self.not_found_statuses
