"""Ce que les registres disent d'un paquet : ses versions, la dernière stable, sa dépréciation.

Un client par registre (PyPI et npm, puis ceux de la phase F), derrière une même
interface. Pour un paquet, trois issues :

- ``PackageInfo`` : le registre le connaît ;
- ``PackageNotFound`` : il ne le connaît pas (paquet privé, faute de frappe). Le constat
  est « non vérifiable », ce n'est pas une erreur fatale ;
- ``RegistryError`` : pas de réponse exploitable (réseau, hors ligne sans cache, réponse
  illisible). Le constat est « non concluant », jamais faux ;
- ``AccessRefused`` (un ``RegistryError``) : un registre déclaré (privé, E33) refuse l'accès
  (401, 403). Le constat est « privé : non vérifié ».

Un registre déclaré par le projet ou par la personne (``routing``, E33) est un client de la même
classe, à une autre adresse (``base_url``), avec les identifiants de l'analyse (``auth`` : seul
celui qui est lié à l'adresse demandée part, ``net.auth``) ; son nom dans les messages est son
hôte, jamais l'adresse (qui peut contenir un token).

Les versions restent des chaînes, telles que le registre les donne. Elles s'interprètent
avec ``forceupdate.versions`` ; une version que ses règles ne savent pas lire (un vieux
paquet PyPI hors PEP 440) est gardée, mais n'est jamais candidate.

Une réponse est réduite à ce qui sert, puis rangée dans le cache disque (``CacheKind.
VERSIONS``, 1 h), un « introuvable » aussi. Une erreur ne l'est pas.
"""

import asyncio
import functools
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, ClassVar

from forceupdate import versions
from forceupdate.models import Ecosystem
from forceupdate.net.auth import Credentials
from forceupdate.net.cache import Cache, CacheEntry, CacheKind
from forceupdate.net.http import HttpClient, NetworkError, Response
from forceupdate.versions import InvalidVersion

_FORMAT = 3
"""Version du format des entrées du cache : une autre est ignorée, et le registre réinterrogé
(2 : le runtime que demande chaque version, E27 ; 3 : celui des crates, E34)."""


class PackageNotFound(LookupError):
    """Le registre ne connaît pas le paquet : paquet privé, ou faute de frappe.

    Le message, en français, est fait pour être montré tel quel dans le rapport.
    """


class RegistryError(Exception):
    """Le registre n'a pas donné de réponse exploitable : réseau, mode hors ligne sans
    cache, statut inattendu, réponse illisible.

    Le message, en français, est fait pour être montré tel quel dans le rapport.
    """


class AccessRefused(RegistryError):
    """Un registre déclaré (privé) refuse l'accès (401, 403) : identifiants absents ou refusés.
    Rien n'est rangé dans le cache : la réponse changera avec les identifiants.

    Le message, en français, est fait pour être montré tel quel dans le rapport.
    """


@dataclass(frozen=True, kw_only=True)
class PackageVersion:
    """Une version publiée d'un paquet."""

    version: str
    """Telle que le registre l'écrit."""
    published: datetime | None = None
    """Date de publication (UTC) ; ``None`` si le registre ne la donne pas."""
    yanked: bool = False
    """Retirée : on ne la propose plus, et l'utiliser est un constat. Sur PyPI, quand tous
    ses fichiers sont « yanked ». npm n'a pas de retrait : une version dépubliée disparaît."""
    yanked_reason: str | None = None
    """La raison du retrait donnée par le registre, s'il y en a une."""
    deprecated: str | None = None
    """npm : le message de dépréciation de cette version ; ``None`` si elle ne l'est pas."""
    requires_runtime: str | None = None
    """Le runtime qu'elle demande, tel que le registre l'écrit : ``engines.node`` (npm),
    ``require.php`` (Packagist), ``ruby`` (RubyGems), ``requires-python`` (PyPI), ``rust_version``
    (crates.io) ; ``None`` si elle n'en dit rien (``checks.runtimes``)."""


@dataclass(frozen=True, kw_only=True)
class PackageInfo:
    """Ce qu'un registre dit d'un paquet."""

    ecosystem: Ecosystem
    name: str
    """Le nom tel que le registre le connaît (normalisé selon PEP 503 pour PyPI)."""
    versions: tuple[PackageVersion, ...]
    """Toutes les versions publiées, de la plus ancienne à la plus récente ; les versions
    illisibles à la fin."""
    latest: str | None
    """La dernière stable, celle qu'on propose (voir chaque registre pour sa règle) ; ``None``
    s'il n'y en a pas (que des pré-versions, ou des versions retirées)."""
    deprecated: str | None = None
    """Le paquet entier est déprécié, abandonné ou retiré : le message à montrer (celui du
    registre quand il en donne un) ; ``None`` sinon."""
    tags: Mapping[str, str] = field(default_factory=dict)
    """npm : les étiquettes (``dist-tags``) et leur version, ``{"latest": "4.17.21", "next":
    …}``. Une dépendance écrite avec une étiquette suit celle-ci. Vide pour PyPI."""
    url: str | None = None
    """La page du paquet, pour en savoir plus."""
    fetched_at: datetime
    """Quand le registre a répondu (UTC) : plus ancien si la réponse vient du cache."""

    def get(self, version: str) -> PackageVersion | None:
        """La version publiée ``version`` : même texte, sinon même version selon les règles de
        l'écosystème (``1.8c1`` et ``1.8rc1`` sur PyPI). ``None`` si elle n'est pas publiée."""
        found = self._by_text.get(version)
        if found is not None:
            return found
        try:
            return self._by_parsed.get(versions.for_ecosystem(self.ecosystem).parse(version))
        except InvalidVersion:
            return None

    def available(self) -> list[str]:
        """Les versions qu'on peut proposer, de la plus ancienne à la plus récente : toutes sauf
        les retirées. C'est la liste à donner à ``versions`` (``latest``, ``max_satisfying``)."""
        return [v.version for v in self.versions if not v.yanked]

    @functools.cached_property
    def _by_text(self) -> dict[str, PackageVersion]:
        return {v.version: v for v in self.versions}

    @functools.cached_property
    def _by_parsed(self) -> dict[Any, PackageVersion]:
        scheme = versions.for_ecosystem(self.ecosystem)
        found = {}
        for v in self.versions:
            try:
                found.setdefault(scheme.parse(v.version), v)
            except InvalidVersion:
                continue
        return found


class Registry(ABC):
    """Le client d'un registre : ``await registry.package(nom)``.

    Une instance par session, avec le client HTTP et le cache de la session : un paquet
    n'y est demandé qu'une fois, même si plusieurs projets le demandent en même temps.
    """

    ecosystem: Ecosystem
    label: str
    """Le nom du registre dans les messages (``PyPI``, ``npm``)."""
    base_url: str
    """L'adresse du registre public, sans ``/`` final."""
    headers: ClassVar[Mapping[str, str]] = {}
    """En-têtes des requêtes (le format de réponse voulu)."""
    not_found_statuses: ClassVar[frozenset[int]] = frozenset({404})
    """Les statuts qui disent que le registre ne connaît pas le paquet (404 ; 410 aussi pour le
    proxy Go)."""

    def __init__(
        self,
        http: HttpClient,
        cache: Cache,
        *,
        base_url: str | None = None,
        auth: Credentials | None = None,
        label: str | None = None,
    ) -> None:
        self._http = http
        self._cache = cache
        self.declared = base_url is not None
        """Un registre déclaré (``base_url`` donnée) : un refus d'accès est ``AccessRefused``."""
        if base_url is not None:
            self.base_url = base_url.rstrip("/")
        if label is not None:
            self.label = label
        self._auth = auth
        self._lookups: dict[str, asyncio.Future[PackageInfo]] = {}

    # -- à écrire pour chaque registre ------------------------------------------

    @abstractmethod
    def normalize(self, name: str) -> str:
        """Le nom tel que le registre le connaît (``Flask`` → ``flask`` pour PyPI)."""

    @abstractmethod
    def url_for(self, name: str) -> str:
        """L'URL à interroger pour le paquet ``name``, déjà normalisé."""

    @abstractmethod
    def page_url(self, name: str) -> str | None:
        """La page web du paquet ; ``None`` si on ne la connaît pas (registre privé)."""

    @abstractmethod
    def parse(self, name: str, response: Response, fetched_at: datetime) -> PackageInfo:
        """Lit la réponse (statut 200) ; lève ``ValueError`` si elle est illisible."""

    async def _url(self, name: str) -> str:
        """L'URL à interroger pour ``name`` : ``url_for``, sauf pour un registre qui doit d'abord
        lire son propre index (un dépôt Composer : son ``packages.json``). Peut lever
        ``PackageNotFound`` ou ``RegistryError``."""
        return self.url_for(name)

    async def _complete(self, name: str, info: PackageInfo) -> PackageInfo:
        """``info`` complété par d'autres requêtes, avant d'aller au cache : le proxy Go donne
        les retraits et la dépréciation dans un autre fichier. Peut lever ``PackageNotFound``,
        ``RegistryError`` ou ``ValueError`` (réponse illisible). Rien à faire par défaut."""
        return info

    # -- commun --------------------------------------------------------------

    async def package(self, name: str) -> PackageInfo:
        """Ce que le registre dit du paquet ``name``.

        Lève ``PackageNotFound`` s'il ne le connaît pas, ``RegistryError`` sans réponse
        exploitable. Une seule requête par paquet dans la session : les appels suivants, ou
        simultanés, rendent la même réponse (ou la même erreur).
        """
        key = self.normalize(name)
        lookup = self._lookups.get(key)
        if lookup is None:
            lookup = self._lookups[key] = asyncio.ensure_future(self._lookup(key))
        # shield : un appelant annulé n'annule pas la requête que d'autres attendent.
        return await asyncio.shield(lookup)

    async def _lookup(self, name: str) -> PackageInfo:
        url = await self._url(name)
        entry = self._cache.get(CacheKind.VERSIONS, url, stale_ok=self._http.offline)
        if entry is not None:
            cached = self._from_cache(name, entry)
            if cached is not None:
                return cached
        if self._http.offline:
            raise RegistryError(
                f"{self.label} : mode hors ligne, et {name} n'est pas dans le cache."
            )
        response = await self._get(url, name, found=True)
        if response is None:
            self._cache.set(CacheKind.VERSIONS, url, {"format": _FORMAT, "not_found": True})
            raise PackageNotFound(self._not_found(name))
        try:
            info = self.parse(name, response, datetime.now(UTC))
            info = await self._complete(name, info)
        except PackageNotFound:
            self._cache.set(CacheKind.VERSIONS, url, {"format": _FORMAT, "not_found": True})
            raise
        except (ValueError, KeyError, TypeError) as error:
            # Une réponse d'un format inconnu n'arrête pas l'analyse : elle est non concluante.
            raise RegistryError(
                f"{self.label} : réponse illisible pour {name} ({error})."
            ) from error
        self._cache.set(CacheKind.VERSIONS, url, _info_to_cache(info))
        return info

    async def _get(self, url: str, name: str, *, found: bool = False) -> Response | None:
        """La réponse 200 du registre à ``url`` (pour le paquet ``name``) ; ``None`` pour un statut
        de ``not_found_statuses`` si ``found``. Lève ``AccessRefused`` pour un registre déclaré
        qui refuse l'accès, ``RegistryError`` sinon."""
        try:
            response = await self._http.get(url, headers=self.headers, auth=self._auth)
        except NetworkError as error:
            raise RegistryError(f"{self.label} : {error}") from error
        status = response.status_code
        if found and status in self.not_found_statuses:
            return None
        if self.declared and status in (401, 403):
            raise AccessRefused(
                f"{self.label} refuse l'accès à {name} (HTTP {status}) : identifiants absents ou "
                "refusés."
            )
        if status != 200:
            raise RegistryError(f"{self.label} : réponse inattendue pour {name} (HTTP {status}).")
        return response

    def _not_found(self, name: str) -> str:
        if self.declared:
            return f"{name} est introuvable sur {self.label}."
        return f"{name} est introuvable sur {self.label} : paquet privé, ou nom mal écrit ?"

    def _from_cache(self, name: str, entry: CacheEntry) -> PackageInfo | None:
        """L'entrée du cache relue ; lève ``PackageNotFound`` pour un « introuvable » rangé,
        ``None`` pour une entrée d'un autre format."""
        value = entry.value
        if not isinstance(value, dict) or value.get("format") != _FORMAT:
            return None
        if value.get("not_found"):
            raise PackageNotFound(self._not_found(name))
        try:
            return _info_from_cache(self.ecosystem, value, entry.stored_at)
        except (ValueError, KeyError, TypeError):
            return None


def sorted_versions(
    ecosystem: Ecosystem, found: Iterable[PackageVersion]
) -> tuple[PackageVersion, ...]:
    """Les versions de la plus ancienne à la plus récente, les illisibles à la fin."""
    key = versions.for_ecosystem(ecosystem).sort_key
    return tuple(sorted(found, key=lambda v: key(v.version)))


def parse_time(value: object) -> datetime | None:
    """Une date ISO 8601 du registre (``2021-05-21T15:53:08.128824Z``), en UTC ; ``None`` si
    elle manque ou est illisible."""
    if not isinstance(value, str):
        return None
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        return None
    return when.replace(tzinfo=UTC) if when.tzinfo is None else when.astimezone(UTC)


def _info_to_cache(info: PackageInfo) -> dict[str, Any]:
    return {
        "format": _FORMAT,
        "name": info.name,
        "versions": [
            [
                v.version,
                None if v.published is None else v.published.isoformat(),
                v.yanked,
                v.yanked_reason,
                v.deprecated,
                v.requires_runtime,
            ]
            for v in info.versions
        ],
        "latest": info.latest,
        "deprecated": info.deprecated,
        "tags": dict(info.tags),
        "url": info.url,
    }


def _info_from_cache(
    ecosystem: Ecosystem, value: dict[str, Any], stored_at: datetime
) -> PackageInfo:
    found = tuple(
        PackageVersion(
            version=version,
            published=parse_time(published),
            yanked=yanked,
            yanked_reason=reason,
            deprecated=deprecated,
            requires_runtime=requires,
        )
        for version, published, yanked, reason, deprecated, requires in value["versions"]
    )
    return PackageInfo(
        ecosystem=ecosystem,
        name=value["name"],
        versions=found,
        latest=value["latest"],
        deprecated=value["deprecated"],
        tags=dict(value["tags"]),
        url=value["url"],
        fetched_at=stored_at,
    )
