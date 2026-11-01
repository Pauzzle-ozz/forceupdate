"""Le client NuGet : l'API « registration » de nuget.org (``registration5-gz-semver2``).

``GET https://api.nuget.org/v3/registration5-gz-semver2/{id en minuscules}/index.json`` (compressée
par gzip) : les versions d'un paquet, rangées en pages de 64. Vérifié le 2026-11-01 :

- jusqu'à 128 versions, les pages sont dans l'index (``items`` de chaque page) ; au-delà, chaque
  page est un autre fichier (son ``@id``), demandé à son tour : 10 pour Serilog, 24 pour
  AWSSDK.Core (7,5 Ko chacune sur le réseau) ;
- pour chaque version (``catalogEntry``) : ``version`` (telle que publiée), ``listed`` (``false`` :
  retirée de la liste par son auteur, ``published`` vaut alors ``1900-01-01``), ``published``,
  ``deprecation`` (``reasons`` : ``Legacy``, ``CriticalBugs``, ``Other`` ; ``message`` ;
  ``alternatePackage``, le remplaçant) et ``vulnerabilities`` (pas lues : les failles viennent
  d'OSV, comme ailleurs) ;
- les versions non listées y sont : le « flat container » (``v3-flatcontainer/{id}/index.json``),
  qui ne donne que la liste des versions, en minuscules, n'est pas demandé ;
- un paquet inconnu : 404 (une erreur XML du stockage d'Azure) ; ``Cache-Control: no-store``.

Ce qu'on en tire :

- **une version non listée est « retirée »** : NuGet ne la propose plus (log4net 2.0.8), mais la
  restaure si on la demande, comme un retrait PyPI ;
- **une version dépréciée** l'est avec ses raisons et son message ; **le paquet entier** l'est
  quand sa dernière version l'est comme « plus maintenue » (``Legacy`` : WindowsAzure.Storage,
  xunit 2), avec son remplaçant ;
- **la dernière stable** : la plus haute version listée, sans pré-version.
"""

import asyncio
from datetime import datetime
from typing import Any
from urllib.parse import quote

from forceupdate.models import Ecosystem
from forceupdate.net.http import NetworkError, Response
from forceupdate.registries.base import (
    PackageInfo,
    PackageVersion,
    Registry,
    RegistryError,
    parse_time,
    sorted_versions,
)
from forceupdate.versions.nuget import NUGET

_REASONS = {"Legacy": "plus maintenu", "CriticalBugs": "bogues critiques", "Other": "déprécié"}
"""Les raisons d'une dépréciation, en français."""


def deprecation_message(value: Any) -> str | None:
    """Le message d'une dépréciation (``deprecation`` d'une version) ; ``None`` sans
    dépréciation."""
    if not isinstance(value, dict):
        return None
    written = [reason for reason in value.get("reasons") or [] if isinstance(reason, str)]
    reasons = [_REASONS.get(reason, reason) for reason in written]
    text = f"{', '.join(dict.fromkeys(reasons)) or 'déprécié'} (nuget.org)"
    alternate = value.get("alternatePackage")
    if isinstance(alternate, dict) and isinstance(alternate.get("id"), str):
        text += f", remplacé par {alternate['id']}"
    message = value.get("message")
    if isinstance(message, str) and message.strip():
        text += f" : {message.strip()}"
    return text


def _legacy(value: Any) -> bool:
    """Vrai pour une dépréciation « plus maintenu » (``Legacy``)."""
    return isinstance(value, dict) and "Legacy" in (value.get("reasons") or [])


def _leaves(page: Any) -> list[dict[str, Any]]:
    """Les versions (``catalogEntry``) d'une page."""
    if not isinstance(page, dict) or not isinstance(page.get("items"), list):
        raise ValueError("page sans « items »")
    found = []
    for leaf in page["items"]:
        entry = leaf.get("catalogEntry") if isinstance(leaf, dict) else None
        if not isinstance(entry, dict) or not isinstance(entry.get("version"), str):
            raise ValueError("version sans « catalogEntry »")
        found.append(entry)
    return found


class NuGet(Registry):
    ecosystem = Ecosystem.NUGET
    label = "nuget.org"
    base_url = "https://api.nuget.org/v3/registration5-gz-semver2"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._partial: dict[str, tuple[list[dict[str, Any]], list[str]]] = {}
        """Ce que ``parse`` a lu de l'index, et les pages à demander ensuite (``_complete``)."""

    def normalize(self, name: str) -> str:
        return name.strip().lower()

    def url_for(self, name: str) -> str:
        return f"{self.base_url}/{quote(name, safe='')}/index.json"

    def page_url(self, name: str) -> str | None:
        if self.base_url != NuGet.base_url:
            return None
        return f"https://www.nuget.org/packages/{name}"

    def parse(self, name: str, response: Response, fetched_at: datetime) -> PackageInfo:
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise ValueError("pas d'« items »")
        entries: list[dict[str, Any]] = []
        pending = []
        for page in data["items"]:
            if isinstance(page, dict) and "items" not in page:
                url = page.get("@id")
                if not isinstance(url, str) or not url.startswith(f"{self.base_url}/"):
                    raise ValueError(f"page hors du registre : {url!r:.80}")
                pending.append(url)
            else:
                entries.extend(_leaves(page))
        if pending:
            self._partial[name] = (entries, pending)
        return self._info(name, entries, fetched_at)

    async def _complete(self, name: str, info: PackageInfo) -> PackageInfo:
        """Les pages que l'index ne contient pas (plus de 128 versions), demandées en même
        temps."""
        partial = self._partial.pop(name, None)
        if partial is None:
            return info
        entries, pending = partial
        pages = await asyncio.gather(*(self._page(url, name) for url in pending))
        for page in pages:
            entries = entries + _leaves(page)
        return self._info(name, entries, info.fetched_at)

    async def _page(self, url: str, name: str) -> Any:
        try:
            response = await self._http.get(url, headers=self.headers)
        except NetworkError as error:
            raise RegistryError(f"{self.label} : {error}") from error
        if response.status_code != 200:
            raise RegistryError(
                f"{self.label} : réponse inattendue pour {name} (HTTP {response.status_code})."
            )
        return response.json()

    def _info(self, name: str, entries: list[dict[str, Any]], fetched_at: datetime) -> PackageInfo:
        found = {}
        deprecations = {}
        for entry in entries:
            version = entry["version"]
            listed = entry.get("listed", True) is not False
            published = parse_time(entry.get("published"))
            if published is not None and published.year <= 1900:
                published = None  # la date que nuget.org donne à une version non listée
            found[version] = PackageVersion(
                version=version,
                published=published,
                yanked=not listed,
                deprecated=deprecation_message(entry.get("deprecation")),
            )
            deprecations[version] = entry.get("deprecation")
        versions = sorted_versions(self.ecosystem, found.values())
        listed_versions = [v.version for v in versions if not v.yanked]
        latest = NUGET.latest(listed_versions)
        newest = latest or NUGET.highest(listed_versions)
        deprecated = None
        if newest is not None and _legacy(deprecations.get(newest)):
            deprecated = found[newest].deprecated
        return PackageInfo(
            ecosystem=self.ecosystem,
            name=name,
            versions=versions,
            latest=latest,
            deprecated=deprecated,
            url=self.page_url(name),
            fetched_at=fetched_at,
        )
