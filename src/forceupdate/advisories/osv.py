"""Les failles connues, demandées à OSV (https://osv.dev), la base qui réunit les avis de
GitHub (GHSA), de PyPI (PYSEC), des paquets malveillants (MAL) et des autres écosystèmes.

Deux temps :

1. ``POST /v1/querybatch`` : pour chaque version de paquet, les identifiants des failles qui
   la concernent, et leur date de modification. Jusqu'à 1000 versions par requête. C'est
   tout ce que donne cette route : ni gravité, ni version corrigée. Argos s'arrêtait là
   (``ARGOS (3)`` dans ``reference/``) : toutes ses failles sortaient en gravité moyenne,
   sans version corrigée ;
2. ``GET /v1/vulns/{id}`` : chaque avis complet. Une seule fois par session, même s'il
   concerne plusieurs paquets ou plusieurs projets, et gardé 7 jours en cache tant que sa
   date de modification ne change pas.

**Une erreur ne donne jamais « pas de faille »** : une version qu'on n'a pas pu soumettre à
OSV donne ``OsvError`` (le constat sera « non concluant ») ; un avis qu'on n'a pas pu lire
reste une faille, de gravité et de version corrigée inconnues (``Advisory.unavailable``).
Hors ligne, tout vient du cache, même périmé ; le reste est « non concluant ».

Repris de ``reference/argos_sca_parsers.py`` (``query_osv_batch``, ``_parse_osv_vuln``), puis
adapté : le client HTTP de forceupdate au lieu de la session d'Argos (``ARGOS (2)``), les
avis complets (``ARGOS (3)``), la version corrigée lue dans les événements des plages au lieu
de la liste de toutes les versions « fixed », les paquets malveillants reconnus, et une
erreur signalée au lieu d'un résultat vide.
"""

import asyncio
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlencode

from packaging.utils import canonicalize_name

from forceupdate import versions
from forceupdate.advisories import cvss
from forceupdate.models import Ecosystem, Severity
from forceupdate.net.cache import Cache, CacheEntry, CacheKind
from forceupdate.net.http import HttpClient, NetworkError
from forceupdate.versions import InvalidVersion, VersionScheme

BASE_URL = "https://api.osv.dev"
BATCH_SIZE = 1000
"""Versions par requête ``querybatch`` : le maximum qu'accepte OSV."""
MAX_PAGES = 10
"""Pages suivies pour une même version (``next_page_token``, quand OSV coupe une réponse
trop longue)."""

_FORMAT = 1
"""Version du format des entrées ``VULNERABILITIES`` du cache : une autre est ignorée."""
_RANGE_TYPES = frozenset({"SEMVER", "ECOSYSTEM"})
"""Les plages lues. ``GIT`` donne des commits, pas des versions publiées."""
_EVENTS = frozenset({"introduced", "fixed", "last_affected", "limit"})
_GITHUB_SEVERITIES = {
    "CRITICAL": Severity.CRITICAL,
    "HIGH": Severity.HIGH,
    "MODERATE": Severity.MEDIUM,
    "MEDIUM": Severity.MEDIUM,
    "LOW": Severity.LOW,
}
"""La gravité que GitHub donne à ses avis (``database_specific.severity``)."""
_MALICIOUS_CWE = "CWE-506"
"""« Embedded Malicious Code » : ce que GitHub met sur ses avis de paquets malveillants."""
_SUMMARY_LENGTH = 200
"""Longueur maximale d'un titre tiré de la description d'un avis."""
_BEYOND_MICROSECONDS = re.compile(r"(\.\d{1,6})\d*")

Query = tuple[Ecosystem, str, str]
"""Une version de paquet à soumettre à OSV : écosystème, nom, version."""


class OsvError(Exception):
    """OSV n'a pas pu dire quelles failles concernent une version : réseau, mode hors ligne
    sans cache, réponse illisible. Le constat est « non concluant », jamais « pas de faille ».

    Le message, en français, est fait pour être montré tel quel dans le rapport.
    """


@dataclass(frozen=True, kw_only=True)
class AffectedRange:
    """Une plage de versions concernées, décrite par des événements, dans l'ordre d'OSV."""

    type: str
    """``SEMVER`` ou ``ECOSYSTEM`` : des versions à comparer selon les règles de l'écosystème."""
    events: tuple[tuple[str, str], ...]
    """``("introduced", "0")``, ``("fixed", "4.17.21")``, ``("last_affected", "1.0.1")``,
    ``("limit", …)``. ``introduced`` à ``"0"`` : depuis toujours."""


@dataclass(frozen=True, kw_only=True)
class Affected:
    """Un paquet concerné par un avis. Un avis en cite parfois plusieurs (lodash, lodash-es,
    lodash.template…), ou le même plusieurs fois (une entrée par branche corrigée)."""

    ecosystem: str
    """Tel qu'OSV l'écrit : les valeurs d'``Ecosystem``, ou d'autres (``Debian:12``…)."""
    name: str
    ranges: tuple[AffectedRange, ...] = ()
    versions: tuple[str, ...] = ()
    """Les versions concernées, quand l'avis les énumère."""


@dataclass(frozen=True, kw_only=True)
class Advisory:
    """Un avis de sécurité d'OSV, réduit à ce qui sert."""

    id: str
    """``GHSA-…``, ``PYSEC-…``, ``MAL-…``…"""
    aliases: tuple[str, ...] = ()
    """Les autres identifiants de la même faille (``CVE-…``, l'avis d'une autre base)."""
    summary: str = ""
    """Le titre de l'avis, tel quel (en anglais en général) ; vide s'il n'en a pas."""
    modified: str = ""
    """Date de dernière modification, telle qu'OSV l'écrit (ISO 8601)."""
    severity: Severity | None = None
    """``None`` si l'avis ne dit rien de sa gravité (ou seulement en CVSS 4.0)."""
    score: float | None = None
    """Le score CVSS 3, de 0 à 10, s'il est connu."""
    malicious: bool = False
    """Un paquet malveillant (``MAL-…``, ou un avis GitHub marqué ``CWE-506``)."""
    withdrawn: bool = False
    """Avis retiré par sa base : ce n'est plus une faille."""
    affected: tuple[Affected, ...] = ()
    unavailable: str | None = None
    """Pourquoi l'avis complet n'a pas pu être lu (réseau, hors ligne…) ; ``None`` s'il l'a
    été. Un avis indisponible reste une faille : on n'en connaît que l'identifiant."""

    @property
    def url(self) -> str:
        """La page de l'avis sur osv.dev."""
        return f"https://osv.dev/vulnerability/{quote(self.id, safe='')}"

    def fixed_in(self, ecosystem: Ecosystem, name: str, version: str) -> str | None:
        """La plus petite version qui corrige la faille pour qui utilise ``version`` de
        ``name`` : la plus petite des versions « fixed » des plages au-dessus de ``version``
        qui n'est elle-même plus concernée.

        Avec deux branches corrigées (Flask : ``< 2.2.5`` et ``>= 2.3.0, < 2.3.2``), depuis
        0.12 c'est 2.2.5, depuis 2.3.0 c'est 2.3.2. ``None`` si l'avis n'en donne pas : faille
        jamais corrigée, seulement une dernière version concernée, paquet malveillant.
        """
        scheme = versions.for_ecosystem(ecosystem)
        try:
            current = scheme.parse(version)
        except InvalidVersion:
            return None
        entries = self._entries(ecosystem, name)
        fixes = []
        for entry in entries:
            for affected_range in entry.ranges:
                for kind, value in affected_range.events:
                    if kind != "fixed":
                        continue
                    try:
                        parsed = scheme.parse(value)
                    except InvalidVersion:
                        continue
                    if current < parsed:
                        fixes.append((parsed, value))
        fixes.sort(key=lambda fix: fix[0])
        for parsed, text in fixes:
            if not _concerned(scheme, entries, parsed):
                return text
        return None

    def affects(self, ecosystem: Ecosystem, name: str, version: str) -> bool:
        """Vrai si ``version`` de ``name`` est concernée, d'après les plages et les versions
        de l'avis. C'est OSV qui décide quelles failles concernent une version ; ceci sert à
        choisir la version corrigée."""
        scheme = versions.for_ecosystem(ecosystem)
        try:
            parsed = scheme.parse(version)
        except InvalidVersion:
            return False
        return _concerned(scheme, self._entries(ecosystem, name), parsed)

    def _entries(self, ecosystem: Ecosystem, name: str) -> list[Affected]:
        return [
            entry
            for entry in self.affected
            if entry.ecosystem == ecosystem.value and _same_name(ecosystem, entry.name, name)
        ]


@dataclass(frozen=True, kw_only=True)
class Vulnerabilities:
    """Les failles qu'OSV connaît pour une version d'un paquet."""

    advisories: tuple[Advisory, ...]
    """Les avis, dans l'ordre d'OSV ; vide si la version n'a pas de faille connue."""
    fetched_at: datetime
    """Quand OSV a répondu (UTC) : plus ancien si la réponse vient du cache."""


class Osv:
    """Le client d'OSV pour une session, avec son client HTTP et son cache :
    ``await osv.vulnerabilities([(Ecosystem.NPM, "lodash", "4.17.15")])``.

    Une instance par session : c'est elle qui fait qu'un avis n'est demandé qu'une fois.
    """

    def __init__(
        self,
        http: HttpClient,
        cache: Cache,
        *,
        base_url: str | None = None,
        batch_size: int = BATCH_SIZE,
    ) -> None:
        self._http = http
        self._cache = cache
        self.base_url = (base_url or BASE_URL).rstrip("/")
        self._batch_size = batch_size
        self._advisories: dict[str, asyncio.Future[Advisory]] = {}

    async def vulnerabilities(
        self, queries: Iterable[Query]
    ) -> dict[Query, Vulnerabilities | OsvError]:
        """Pour chaque version de paquet, ses failles connues, ou l'erreur qui empêche de les
        connaître. Les versions sont demandées par lots, les avis tous en même temps."""
        wanted = list(dict.fromkeys(queries))
        found: dict[Query, tuple[list[tuple[str, str]], datetime] | OsvError] = {}
        missing = []
        for query in wanted:
            cached = self._cached_ids(query)
            if cached is None:
                missing.append(query)
            else:
                found[query] = cached
        if missing and self._http.offline:
            # Le même message pour toutes : une remarque les réunit (``engine.check``).
            offline = OsvError("OSV : mode hors ligne, sans réponse en cache.")
            found.update(dict.fromkeys(missing, offline))
        elif missing:
            size = self._batch_size
            batches = [missing[start : start + size] for start in range(0, len(missing), size)]
            for result in await asyncio.gather(*(self._query_batch(b) for b in batches)):
                found.update(result)

        modified: dict[str, str] = {}
        for value in found.values():
            if not isinstance(value, OsvError):
                for vuln_id, when in value[0]:
                    modified[vuln_id] = max(modified.get(vuln_id, ""), when)
        ids = sorted(modified)
        advisories = await asyncio.gather(*(self.advisory(i, modified[i] or None) for i in ids))
        by_id = dict(zip(ids, advisories, strict=True))

        result: dict[Query, Vulnerabilities | OsvError] = {}
        for query in wanted:
            value = found[query]
            if isinstance(value, OsvError):
                result[query] = value
            else:
                pairs, fetched_at = value
                result[query] = Vulnerabilities(
                    advisories=tuple(by_id[vuln_id] for vuln_id, _ in pairs),
                    fetched_at=fetched_at,
                )
        return result

    async def advisory(self, vuln_id: str, modified: str | None = None) -> Advisory:
        """L'avis complet ``vuln_id``. ``modified`` : sa date de modification d'après
        ``querybatch`` ; un avis en cache d'une autre date est redemandé.

        Ne lève pas : un avis qu'on ne peut pas lire est rendu avec ``unavailable``. Une seule
        requête par avis dans la session, même pour des appels simultanés.
        """
        lookup = self._advisories.get(vuln_id)
        if lookup is None:
            lookup = self._advisories[vuln_id] = asyncio.ensure_future(
                self._fetch_advisory(vuln_id, modified)
            )
        # shield : un appelant annulé n'annule pas la requête que d'autres attendent.
        return await asyncio.shield(lookup)

    # -- querybatch -------------------------------------------------------------

    def _query_key(self, query: Query) -> str:
        ecosystem, name, version = query
        fields = {"ecosystem": ecosystem.value, "name": name, "version": version}
        return f"{self.base_url}/v1/query?{urlencode(fields)}"

    def _cached_ids(self, query: Query) -> tuple[list[tuple[str, str]], datetime] | None:
        entry = self._cache.get(
            CacheKind.VULNERABILITIES, self._query_key(query), stale_ok=self._http.offline
        )
        if entry is None:
            return None
        value = entry.value
        if not isinstance(value, dict) or value.get("format") != _FORMAT:
            return None
        try:
            pairs = [(str(vuln_id), str(when)) for vuln_id, when in value["vulns"]]
        except (KeyError, TypeError, ValueError):
            return None
        return pairs, entry.stored_at

    async def _query_batch(
        self, batch: Sequence[Query]
    ) -> dict[Query, tuple[list[tuple[str, str]], datetime] | OsvError]:
        """Un lot de versions, avec les pages suivantes de celles qu'OSV a coupées."""
        url = f"{self.base_url}/v1/querybatch"
        pairs: dict[Query, list[tuple[str, str]]] = {query: [] for query in batch}
        tokens: dict[Query, str] = {}
        todo = list(batch)
        for _ in range(MAX_PAGES):
            body = {"queries": [_query_body(query, tokens.get(query)) for query in todo]}
            try:
                response = await self._http.request("POST", url, json=body, retry=True)
            except NetworkError as error:
                return _failed(batch, f"OSV : {error}")
            if response.status_code != 200:
                return _failed(batch, f"OSV : réponse inattendue (HTTP {response.status_code}).")
            try:
                results = _batch_results(response.json(), len(todo))
            except (ValueError, KeyError, TypeError) as error:
                return _failed(batch, f"OSV : réponse illisible ({error}).")
            pending = []
            for query, (ids, token) in zip(todo, results, strict=True):
                pairs[query].extend(ids)
                if token:
                    tokens[query] = token
                    pending.append(query)
            todo = pending
            if not todo:
                break
        fetched_at = datetime.now(UTC)
        result: dict[Query, tuple[list[tuple[str, str]], datetime] | OsvError] = {}
        for query in batch:
            if query in todo:
                _, name, version = query
                result[query] = OsvError(
                    f"OSV : trop de failles pour {name} {version} (plus de {MAX_PAGES} pages)."
                )
                continue
            found = list(dict.fromkeys(pairs[query]))
            self._cache.set(
                CacheKind.VULNERABILITIES,
                self._query_key(query),
                {"format": _FORMAT, "vulns": [list(pair) for pair in found]},
            )
            result[query] = (found, fetched_at)
        return result

    # -- vulns/{id} -------------------------------------------------------------

    async def _fetch_advisory(self, vuln_id: str, modified: str | None) -> Advisory:
        url = f"{self.base_url}/v1/vulns/{quote(vuln_id, safe='')}"
        entry = self._cache.get(CacheKind.ADVISORIES, url, stale_ok=True)
        cached = _from_cache(entry)
        if (
            entry is not None
            and cached is not None
            and (
                self._http.offline
                or (entry.fresh and (modified is None or _same_time(modified, cached.modified)))
            )
        ):
            return cached
        if self._http.offline:
            return Advisory(id=vuln_id, unavailable="mode hors ligne, et l'avis n'est pas en cache")
        try:
            response = await self._http.get(url)
        except NetworkError as error:
            # Mieux vaut l'avis d'il y a quelques jours que rien.
            return cached or Advisory(id=vuln_id, unavailable=str(error).rstrip("."))
        if response.status_code != 200:
            reason = f"OSV a répondu HTTP {response.status_code}"
            return cached or Advisory(id=vuln_id, unavailable=reason)
        try:
            raw = response.json()
        except ValueError:
            raw = None
        advisory = parse_vuln(raw)
        if advisory is None:
            return cached or Advisory(id=vuln_id, unavailable="avis illisible")
        self._cache.set(CacheKind.ADVISORIES, url, raw)
        return advisory


def parse_vuln(raw: Any) -> Advisory | None:
    """Un avis au format OSV (``GET /v1/vulns/{id}``) ; ``None`` s'il n'a pas d'identifiant.

    Gravité : le score du vecteur CVSS 3, sinon le score que donne la base, sinon la gravité
    que lui donne GitHub ; ``None`` sinon.
    """
    if not isinstance(raw, dict):
        return None
    vuln_id = raw.get("id")
    if not isinstance(vuln_id, str) or not vuln_id:
        return None
    aliases = tuple(alias for alias in _list(raw.get("aliases")) if isinstance(alias, str))
    summary = raw.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        details = raw.get("details")
        summary = _shorten(details) if isinstance(details, str) else ""
    database = raw.get("database_specific")
    database = database if isinstance(database, dict) else {}
    cwe_ids = _list(database.get("cwe_ids"))
    severity, score = _severity(raw, database)
    return Advisory(
        id=vuln_id,
        aliases=aliases,
        summary=summary.strip(),
        modified=str(raw.get("modified") or ""),
        severity=severity,
        score=score,
        malicious=(
            any(i.startswith("MAL-") for i in (vuln_id, *aliases)) or _MALICIOUS_CWE in cwe_ids
        ),
        withdrawn=bool(raw.get("withdrawn")),
        affected=tuple(
            entry for entry in map(_affected, _list(raw.get("affected"))) if entry is not None
        ),
    )


def _severity(
    raw: dict[str, Any], database: dict[str, Any]
) -> tuple[Severity | None, float | None]:
    for entry in _list(raw.get("severity")):
        if isinstance(entry, dict) and entry.get("type") == "CVSS_V3":
            score = cvss.base_score(str(entry.get("score", "")))
            if score is not None:
                return cvss.severity(score), score
    info = database.get("cvss")
    if isinstance(info, dict):
        try:
            score = float(info.get("score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        if 0 < score <= 10:
            return cvss.severity(score), score
    text = database.get("severity")
    if isinstance(text, str) and text.upper() in _GITHUB_SEVERITIES:
        return _GITHUB_SEVERITIES[text.upper()], None
    return None, None


def _affected(raw: Any) -> Affected | None:
    if not isinstance(raw, dict):
        return None
    package = raw.get("package")
    if not isinstance(package, dict):
        return None
    ecosystem, name = package.get("ecosystem"), package.get("name")
    if not isinstance(ecosystem, str) or not isinstance(name, str):
        return None
    ranges = []
    for item in _list(raw.get("ranges")):
        if not isinstance(item, dict) or item.get("type") not in _RANGE_TYPES:
            continue
        events = tuple(
            (kind, value)
            for event in _list(item.get("events"))
            if isinstance(event, dict)
            for kind, value in event.items()
            if kind in _EVENTS and isinstance(value, str)
        )
        ranges.append(AffectedRange(type=item["type"], events=events))
    return Affected(
        ecosystem=ecosystem,
        name=name,
        ranges=tuple(ranges),
        versions=tuple(v for v in _list(raw.get("versions")) if isinstance(v, str)),
    )


def _shorten(details: str) -> str:
    """Un titre tiré de la description d'un avis qui n'en a pas (les PYSEC) : sa première
    ligne, coupée entre deux mots au-delà de ``_SUMMARY_LENGTH`` caractères."""
    line = details.strip().split("\n", 1)[0].strip()
    if len(line) <= _SUMMARY_LENGTH:
        return line
    cut = line[:_SUMMARY_LENGTH].rsplit(" ", 1)[0].rstrip(" ,;:.")
    return f"{cut}…"


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _same_time(first: str, second: str) -> bool:
    """Vrai si deux dates de modification d'OSV sont les mêmes, à la microseconde :
    ``querybatch`` les arrondit (``…38.085813Z``), ``vulns/{id}`` donne les nanosecondes
    (``…38.085813876Z``)."""

    def moment(text: str) -> datetime | str:
        try:
            return datetime.fromisoformat(_BEYOND_MICROSECONDS.sub(r"\1", text))
        except ValueError:
            return text

    return moment(first) == moment(second)


def _same_name(ecosystem: Ecosystem, first: str, second: str) -> bool:
    if ecosystem is Ecosystem.PYPI:
        return canonicalize_name(first) == canonicalize_name(second)
    return first == second


def _concerned(scheme: VersionScheme[Any], entries: Iterable[Affected], version: Any) -> bool:
    """Vrai si ``version`` (déjà lue) est dans une des plages ou des versions de ``entries``."""
    for entry in entries:
        if any(_in_range(scheme, r, version) for r in entry.ranges):
            return True
        for listed in entry.versions:
            try:
                if scheme.parse(listed) == version:
                    return True
            except InvalidVersion:
                continue
    return False


def _in_range(scheme: VersionScheme[Any], affected_range: AffectedRange, version: Any) -> bool:
    """L'algorithme de la spécification d'OSV : les événements triés par version, le dernier
    franchi décide. Un événement dont la version est illisible est ignoré."""
    events: list[tuple[Any, str]] = []
    for kind, value in affected_range.events:
        if kind == "introduced" and value == "0":
            events.append((None, kind))
            continue
        try:
            events.append((scheme.parse(value), kind))
        except InvalidVersion:
            continue
    events.sort(key=lambda event: (event[0] is not None, event[0]))
    concerned = False
    for bound, kind in events:
        if kind == "introduced":
            if bound is None or not version < bound:
                concerned = True
        elif kind in ("fixed", "limit"):
            if not version < bound:
                concerned = False
        elif bound < version:  # last_affected
            concerned = False
    return concerned


def _query_body(query: Query, page_token: str | None) -> dict[str, Any]:
    ecosystem, name, version = query
    body: dict[str, Any] = {
        "package": {"ecosystem": ecosystem.value, "name": name},
        "version": version,
    }
    if page_token:
        body["page_token"] = page_token
    return body


def _batch_results(payload: Any, count: int) -> list[tuple[list[tuple[str, str]], str | None]]:
    """Les résultats d'une réponse ``querybatch``, un par version demandée, dans l'ordre."""
    results = payload["results"]
    if not isinstance(results, list) or len(results) != count:
        size = len(results) if isinstance(results, list) else "pas de liste de"
        raise ValueError(f"{size} résultats pour {count} versions")
    found = []
    for item in results:
        if not isinstance(item, dict):
            raise TypeError("un résultat n'est pas un objet")
        ids = [(str(v["id"]), str(v.get("modified") or "")) for v in _list(item.get("vulns"))]
        token = item.get("next_page_token")
        found.append((ids, token if isinstance(token, str) and token else None))
    return found


def _failed(batch: Sequence[Query], message: str) -> dict[Query, Any]:
    error = OsvError(message)
    return dict.fromkeys(batch, error)


def _from_cache(entry: CacheEntry | None) -> Advisory | None:
    """L'avis rangé dans le cache (le document d'OSV tel quel), relu ; ``None`` sans entrée."""
    if entry is None:
        return None
    advisory = parse_vuln(entry.value)
    return None if advisory is None or advisory.unavailable else advisory
