"""Les avis de sécurité de Packagist (E34) : ceux de GitHub et de la base FriendsOfPHP que lit
``composer audit``, ajoutés à ceux d'OSV et réunis avec eux par leurs identifiants (CVE, GHSA).

Vérifié le 2026-11-02 sur twig/twig 3.4.1 : ``composer audit --locked`` (Composer 2.11.0) dit 17
failles ; OSV en connaît 15 ; les deux autres (CVE-2026-46627, CVE-2026-46636) n'ont pour source
que ``FriendsOfPHP/security-advisories``.

L'API, celle que donne le ``packages.json`` de Packagist (``security-advisories.api-url``) :
``GET https://packagist.org/api/security-advisories/?packages[]=twig/twig&packages[]=…`` rend,
par paquet, tous ses avis, toutes versions confondues :

    {"advisories": {"twig/twig": [{"advisoryId": "PKSA-8zx5-v2nz-58pb", "remoteId": "GHSA-…",
     "title": "…", "link": "https://github.com/advisories/GHSA-…", "cve": "CVE-2026-49981",
     "affectedVersions": ">=1.0.0,<2.0.0|>=3.0.0,<3.27.0", "reportedAt": "2026-07-01 18:55:49",
     "severity": "high", "sources": [{"name": "GitHub", "remoteId": "GHSA-…"},
     {"name": "FriendsOfPHP/security-advisories", "remoteId": "twig/twig/2026-…yaml"}]}]}}

Chaque avis devient un ``Advisory`` : son identifiant (``PKSA-…``), ses alias (sa CVE, et le
``remoteId`` de ses sources qui est un identifiant : ``GHSA-…``), son titre, sa gravité, son lien,
et ses versions concernées (``affectedVersions``, une contrainte Composer : des plages séparées par
``|``) en plages OSV, pour la version corrigée (``>=A,<B`` : ``introduced`` A, ``fixed`` B ;
``<=B`` : ``last_affected`` B). Comme ``composer audit``, une version est concernée si elle
respecte la contrainte (``versions.composer``).

Un paquet n'est demandé qu'une fois par session, et gardé une heure en cache, comme les failles
d'OSV. Une erreur n'efface rien : les failles d'OSV restent, et une remarque dit que celles de
Packagist n'ont pas été lues.
"""

import asyncio
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from forceupdate.advisories.osv import (
    Advisory,
    Affected,
    AffectedRange,
    OsvError,
    Query,
    Vulnerabilities,
)
from forceupdate.models import Ecosystem, Severity
from forceupdate.net.cache import Cache, CacheKind
from forceupdate.net.http import HttpClient, NetworkError
from forceupdate.versions import InvalidConstraint, InvalidVersion
from forceupdate.versions.composer import COMPOSER

API_URL = "https://packagist.org/api/security-advisories/"
BATCH_SIZE = 50
"""Paquets par requête (l'adresse les porte tous)."""

_FORMAT = 1
_SEVERITIES = {
    "critical": Severity.CRITICAL,
    "high": Severity.HIGH,
    "medium": Severity.MEDIUM,
    "moderate": Severity.MEDIUM,
    "low": Severity.LOW,
}
_IDENTIFIER = re.compile(r"^(?:GHSA|CVE|PYSEC|GO|RUSTSEC)-[\w-]+$")
_CONDITION = re.compile(r"^(>=|<=|>|<|==|=)?\s*v?([0-9][\w.+-]*)$")


@dataclass(frozen=True, kw_only=True)
class PackagistAdvisory:
    """Un avis de Packagist : l'avis lu, et la contrainte des versions qu'il concerne."""

    advisory: Advisory
    affected: str
    """``affectedVersions``, telle que Packagist l'écrit."""

    def concerns(self, version: str) -> bool:
        try:
            return COMPOSER.satisfies(self.affected, version)
        except (InvalidConstraint, InvalidVersion):
            return False


class PackagistAdvisories:
    """Le client des avis de Packagist pour une session : ``await client.merge(found)``."""

    def __init__(self, http: HttpClient, cache: Cache, *, base_url: str = API_URL) -> None:
        self._http = http
        self._cache = cache
        self.base_url = base_url
        self._known: dict[str, list[PackagistAdvisory]] = {}
        self._failed: set[str] = set()
        self.error: str | None = None
        """Pourquoi des avis n'ont pas pu être lus (le dernier message) ; ``None`` sinon."""

    async def merge(
        self, found: Mapping[Query, Vulnerabilities | OsvError]
    ) -> dict[Query, Vulnerabilities | OsvError]:
        """``found``, avec les avis de Packagist ajoutés à ceux d'OSV pour chaque version d'un
        paquet Packagist qui les concerne. Une version qu'OSV n'a pas pu examiner reste ainsi."""
        names = sorted(
            {
                name
                for (ecosystem, name, _), value in found.items()
                if ecosystem is Ecosystem.PACKAGIST and isinstance(value, Vulnerabilities)
            }
        )
        if not names:
            return dict(found)
        known = await self.advisories(names)
        merged: dict[Query, Vulnerabilities | OsvError] = {}
        for query, value in found.items():
            ecosystem, name, version = query
            extra = [
                item.advisory
                for item in known.get(name, ())
                if ecosystem is Ecosystem.PACKAGIST and item.concerns(version)
            ]
            if extra and isinstance(value, Vulnerabilities):
                value = Vulnerabilities(
                    advisories=(*value.advisories, *extra), fetched_at=value.fetched_at
                )
            merged[query] = value
        return merged

    async def advisories(self, names: Iterable[str]) -> dict[str, list[PackagistAdvisory]]:
        """Les avis de chaque paquet de ``names`` ; ceux qu'on n'a pas pu lire n'y sont pas
        (``error`` dit pourquoi). Chaque paquet n'est demandé qu'une fois par session."""
        wanted = list(dict.fromkeys(names))
        for name in wanted:
            if name not in self._known and (cached := self._cached(name)) is not None:
                self._known[name] = cached
        missing = [n for n in wanted if n not in self._known and n not in self._failed]
        batches = [missing[i : i + BATCH_SIZE] for i in range(0, len(missing), BATCH_SIZE)]
        results = await asyncio.gather(*(self._fetch(b) for b in batches), return_exceptions=True)
        for batch, result in zip(batches, results, strict=True):
            if isinstance(result, _Failed):
                self.error = str(result)
                self._failed.update(batch)
            elif isinstance(result, BaseException):
                raise result
            else:
                self._known.update(result)
        return {name: self._known[name] for name in wanted if name in self._known}

    def _key(self, name: str) -> str:
        return f"{self.base_url}?{urlencode({'packages[]': name})}"

    def _cached(self, name: str) -> list[PackagistAdvisory] | None:
        entry = self._cache.get(
            CacheKind.VULNERABILITIES, self._key(name), stale_ok=self._http.offline
        )
        if entry is None or not isinstance(entry.value, dict):
            return None
        if entry.value.get("format") != _FORMAT:
            return None
        try:
            return [parse_advisory(name, item) for item in entry.value["advisories"]]
        except (KeyError, TypeError, ValueError):
            return None

    async def _fetch(self, batch: list[str]) -> dict[str, list[PackagistAdvisory]]:
        if self._http.offline:
            raise _Failed("Packagist : mode hors ligne, sans réponse en cache.")
        url = f"{self.base_url}?{urlencode([('packages[]', name) for name in batch])}"
        try:
            response = await self._http.get(url, headers={"Accept": "application/json"})
        except NetworkError as error:
            raise _Failed(f"Packagist : {error}") from error
        if response.status_code != 200:
            raise _Failed(f"Packagist : réponse inattendue (HTTP {response.status_code}).")
        try:
            data = response.json()["advisories"]
            if isinstance(data, list):  # aucun avis : PHP écrit un tableau vide
                data = {}
            found = {}
            for name in batch:
                raw = data.get(name) or []
                if isinstance(raw, dict):
                    raw = list(raw.values())
                found[name] = [parse_advisory(name, item) for item in raw]
                self._cache.set(
                    CacheKind.VULNERABILITIES,
                    self._key(name),
                    {"format": _FORMAT, "advisories": raw},
                )
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise _Failed(f"Packagist : réponse illisible ({error}).") from error
        return found


class _Failed(Exception):
    pass


def parse_advisory(name: str, item: Mapping[str, Any]) -> PackagistAdvisory:
    """Un avis de l'API (voir la docstring du module) ; lève ``ValueError`` sans identifiant ni
    versions concernées."""
    advisory_id = item.get("advisoryId")
    affected = item.get("affectedVersions")
    if not isinstance(advisory_id, str) or not isinstance(affected, str):
        raise ValueError("avis sans advisoryId ni affectedVersions")
    aliases = []
    cve = item.get("cve")
    if isinstance(cve, str) and cve:
        aliases.append(cve)
    for source in item.get("sources") or []:
        remote = source.get("remoteId") if isinstance(source, dict) else None
        if isinstance(remote, str) and _IDENTIFIER.match(remote):
            aliases.append(remote)
    remote = item.get("remoteId")
    if isinstance(remote, str) and _IDENTIFIER.match(remote):
        aliases.append(remote)
    severity = item.get("severity")
    link = item.get("link")
    advisory = Advisory(
        id=advisory_id,
        aliases=tuple(dict.fromkeys(a for a in aliases if a != advisory_id)),
        summary=str(item.get("title") or ""),
        modified=str(item.get("reportedAt") or ""),
        severity=_SEVERITIES.get(severity.lower()) if isinstance(severity, str) else None,
        affected=(
            Affected(ecosystem=Ecosystem.PACKAGIST.value, name=name, ranges=ranges(affected)),
        ),
        link=link if isinstance(link, str) and link.startswith("https://") else None,
    )
    return PackagistAdvisory(advisory=advisory, affected=affected)


def ranges(constraint: str) -> tuple[AffectedRange, ...]:
    """Les plages OSV d'une contrainte de versions concernées (voir la docstring du module) ;
    une plage qui ne se lit pas est laissée de côté (pas de version corrigée tirée d'elle)."""
    found = []
    for clause in constraint.split("|"):
        events: list[tuple[str, str]] = []
        lower = False
        for condition in re.split(r"[,\s]+", clause.strip()):
            match = _CONDITION.match(condition)
            if not condition:
                continue
            if match is None:
                events = []
                break
            operator, version = match.groups()
            if operator in (">=", ">"):
                events.append(("introduced", version))
                lower = True
            elif operator == "<":
                events.append(("fixed", version))
            elif operator == "<=":
                events.append(("last_affected", version))
            else:  # une version seule
                events += [("introduced", version), ("last_affected", version)]
                lower = True
        if events:
            if not lower:
                events.insert(0, ("introduced", "0"))
            found.append(AffectedRange(type="ECOSYSTEM", events=tuple(events)))
    return tuple(found)
