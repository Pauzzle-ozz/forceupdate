"""Les cycles de vie des runtimes et des frameworks, demandés à endoflife.date (E27).

``GET https://endoflife.date/api/v1/products/{produit}``. Vérifié le 2026-11-01 sur ``python``,
``nodejs``, ``django``, ``go``, ``ruby``, ``php``, ``eclipse-temurin``, ``dotnet``, ``dotnetfx``,
``rails``, ``spring-boot``, ``laravel``, ``symfony``, ``angular``, ``vue``, ``nuxt`` et
``electron`` :

    {"schema_version": "1.2.1", "generated_at": …, "result": {"name": "python", "label":
     "Python", "links": {"html": "https://endoflife.date/python", …}, "labels": {"eol":
     "Security Support", …}, "releases": [{"name": "3.15", "label": "3.15", "releaseDate":
     "2026-10-09", "isLts": false, "ltsFrom": null, "isEol": false, "eolFrom": "2031-10-31",
     "isMaintained": true, "latest": {"name": "3.15.2", "date": …}, …}, …]}}

- un cycle par ``release``, du plus récent au plus ancien, à peu près : Python 2.7 vient après
  3.2. ``name`` est le cycle (``3.8``, ``16``, ``3.5-sp1`` pour .NET Framework) ;
- ``isEol`` est un booléen, calculé le jour où la page a été faite ; ``eolFrom`` sa date, ou
  ``null`` : un cycle encore maintenu dont la fin n'est pas fixée (Go 1.27, Vue 3.5), ou un vieux
  cycle fini sans date connue (Node.js 1 à 3, Vue 1). La date compte d'abord : le cache garde la
  réponse un jour, et l'analyse peut se faire un autre jour ;
- ``isLts`` et ``ltsFrom`` de même (Node.js 26 n'est LTS que depuis le 2026-10-28) ;
- ``latest.name`` : la dernière version du cycle (``3.14.10``, ``8u504-b01`` pour Temurin 8) ;
- un produit inconnu donne 404, en HTML ; un alias (``node``) renvoie (301) vers son nom
  (``nodejs``). Pas de ``Cache-Control`` utile (``max-age=0``).

L'ancienne forme, ``/api/{produit}.json``, existe encore : une liste de cycles (``cycle``,
``eol`` qui est une date ou un booléen, ``lts``, ``latest``), sans le nom du produit ni ses
liens. Elle n'est pas demandée.

Une réponse est réduite à ce qui sert, puis rangée dans le cache (``CacheKind.LIFECYCLES``, 24 h),
un produit inconnu aussi. **Une erreur ne donne jamais de faux constat** : ``EndOfLifeError``
donne un « non concluant ».
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import quote

from forceupdate.net.cache import Cache, CacheEntry, CacheKind
from forceupdate.net.http import HttpClient, NetworkError, Response

BASE_URL = "https://endoflife.date"
_FORMAT = 1
"""Version du format des entrées du cache : une autre est ignorée, et le site réinterrogé."""


class ProductNotFound(LookupError):
    """endoflife.date ne connaît pas le produit. Le message, en français, est fait pour être
    montré tel quel dans le rapport."""


class EndOfLifeError(Exception):
    """endoflife.date n'a pas donné de réponse exploitable : réseau, mode hors ligne sans cache,
    statut inattendu, réponse illisible. Le constat est « non concluant », jamais faux.

    Le message, en français, est fait pour être montré tel quel dans le rapport.
    """


@dataclass(frozen=True, kw_only=True)
class Release:
    """Un cycle d'un produit : ``3.8`` de Python, ``16`` de Node.js."""

    name: str
    """Le cycle, tel qu'endoflife.date l'écrit : ``3.8``, ``16``, ``3.5-sp1``."""
    label: str
    """Son nom affiché : ``26 (LTS)``, ``Core 2.1``."""
    released: date | None = None
    lts: bool = False
    """``isLts`` : à support long, le jour où la page a été faite."""
    lts_from: date | None = None
    eol: bool = False
    """``isEol`` : en fin de vie, le jour où la page a été faite."""
    eol_from: date | None = None
    """La date de fin de vie ; ``None`` si elle n'est pas fixée, ou pas connue."""
    latest: str | None = None
    """La dernière version publiée du cycle."""

    def ended(self, today: date) -> bool:
        """Vrai si le cycle est en fin de vie à la date ``today`` : d'après ``eol_from`` s'il y
        en a une, sinon d'après ``eol``."""
        return self.eol_from <= today if self.eol_from is not None else self.eol

    def is_lts(self, today: date) -> bool:
        """Vrai si le cycle est à support long à la date ``today`` (même règle)."""
        return self.lts_from <= today if self.lts_from is not None else self.lts


@dataclass(frozen=True, kw_only=True)
class Product:
    """Ce qu'endoflife.date dit d'un produit."""

    name: str
    """Son nom chez endoflife.date : ``python``, ``spring-boot``."""
    label: str
    """Son nom affiché : ``Python``, ``Spring Boot``."""
    releases: tuple[Release, ...]
    """Ses cycles, dans l'ordre de la page."""
    url: str | None
    """Sa page sur endoflife.date."""
    fetched_at: datetime
    """Quand endoflife.date a répondu (UTC) : plus ancien si la réponse vient du cache."""


class EndOfLifeDate:
    """Le client d'endoflife.date pour une session, avec son client HTTP et son cache : un produit
    n'y est demandé qu'une fois, même si plusieurs projets le demandent en même temps."""

    def __init__(self, http: HttpClient, cache: Cache, *, base_url: str = BASE_URL) -> None:
        self._http = http
        self._cache = cache
        self.base_url = base_url.rstrip("/")
        self._lookups: dict[str, asyncio.Future[Product]] = {}

    def url_for(self, name: str) -> str:
        return f"{self.base_url}/api/v1/products/{quote(name, safe='')}"

    async def product(self, name: str) -> Product:
        """Les cycles du produit ``name``. Lève ``ProductNotFound`` s'il est inconnu,
        ``EndOfLifeError`` sans réponse exploitable ; une seule requête par produit dans la
        session."""
        lookup = self._lookups.get(name)
        if lookup is None:
            lookup = self._lookups[name] = asyncio.ensure_future(self._lookup(name))
        return await asyncio.shield(lookup)

    async def _lookup(self, name: str) -> Product:
        url = self.url_for(name)
        entry = self._cache.get(CacheKind.LIFECYCLES, url, stale_ok=self._http.offline)
        if entry is not None:
            cached = self._from_cache(name, entry)
            if cached is not None:
                return cached
        if self._http.offline:
            raise EndOfLifeError(
                f"endoflife.date : mode hors ligne, et {name} n'est pas dans le cache."
            )
        try:
            response = await self._http.get(url, headers={"Accept": "application/json"})
        except NetworkError as error:
            raise EndOfLifeError(f"endoflife.date : {error}") from error
        if response.status_code == 404:
            self._cache.set(CacheKind.LIFECYCLES, url, {"format": _FORMAT, "not_found": True})
            raise ProductNotFound(_not_found(name))
        if response.status_code != 200:
            raise EndOfLifeError(
                f"endoflife.date : réponse inattendue pour {name} (HTTP {response.status_code})."
            )
        try:
            product = parse(name, response, datetime.now(UTC))
        except (ValueError, KeyError, TypeError) as error:
            raise EndOfLifeError(
                f"endoflife.date : réponse illisible pour {name} ({error})."
            ) from error
        self._cache.set(CacheKind.LIFECYCLES, url, _to_cache(product))
        return product

    def _from_cache(self, name: str, entry: CacheEntry) -> Product | None:
        value = entry.value
        if not isinstance(value, dict) or value.get("format") != _FORMAT:
            return None
        if value.get("not_found"):
            raise ProductNotFound(_not_found(name))
        try:
            return _from_cache(value, entry.stored_at)
        except (ValueError, KeyError, TypeError):
            return None


def parse(name: str, response: Response, fetched_at: datetime) -> Product:
    """La réponse de ``/api/v1/products/{name}`` (statut 200) ; lève ``ValueError`` si elle est
    illisible."""
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("result"), dict):
        raise ValueError("pas de « result »")
    result = data["result"]
    releases = result.get("releases")
    if not isinstance(releases, list):
        raise ValueError("pas de « releases »")
    links = result.get("links") if isinstance(result.get("links"), dict) else {}
    return Product(
        name=str(result.get("name") or name),
        label=str(result.get("label") or name),
        releases=tuple(_release(item) for item in releases if isinstance(item, dict)),
        url=links.get("html") if isinstance(links.get("html"), str) else None,
        fetched_at=fetched_at,
    )


def _release(item: dict[str, Any]) -> Release:
    name = item.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError(f"cycle sans nom : {item!r:.80}")
    latest = item.get("latest")
    return Release(
        name=name,
        label=item["label"] if isinstance(item.get("label"), str) else name,
        released=_date(item.get("releaseDate")),
        lts=item.get("isLts") is True,
        lts_from=_date(item.get("ltsFrom")),
        eol=item.get("isEol") is True,
        eol_from=_date(item.get("eolFrom")),
        latest=latest.get("name") if isinstance(latest, dict) else None,
    )


def _date(value: object) -> date | None:
    """Une date ``AAAA-MM-JJ`` ; ``None`` si elle manque ou est illisible."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _not_found(name: str) -> str:
    return f"{name} est inconnu d'endoflife.date."


def _to_cache(product: Product) -> dict[str, Any]:
    return {
        "format": _FORMAT,
        "name": product.name,
        "label": product.label,
        "url": product.url,
        "releases": [
            [
                r.name,
                r.label,
                _iso(r.released),
                r.lts,
                _iso(r.lts_from),
                r.eol,
                _iso(r.eol_from),
                r.latest,
            ]
            for r in product.releases
        ],
    }


def _iso(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _from_cache(value: dict[str, Any], stored_at: datetime) -> Product:
    releases = tuple(
        Release(
            name=name,
            label=label,
            released=_date(released),
            lts=lts,
            lts_from=_date(lts_from),
            eol=eol,
            eol_from=_date(eol_from),
            latest=latest,
        )
        for name, label, released, lts, lts_from, eol, eol_from, latest in value["releases"]
    )
    return Product(
        name=value["name"],
        label=value["label"],
        releases=releases,
        url=value["url"],
        fetched_at=stored_at,
    )
