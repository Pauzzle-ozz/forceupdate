"""Le client PyPI : l'API « Simple » en JSON (PEP 691), avec ``versions`` et ``upload-time``
(PEP 700) et le statut du projet (PEP 792).

Pourquoi pas l'API JSON de PyPI (``/pypi/{nom}/json``) : sa clé ``releases``, la seule qui
liste les versions, est dépréciée (la doc de PyPI renvoie vers l'API Simple) ; elle pèse un
tiers de plus ; et elle ne dit pas si le projet est archivé. L'API Simple est un standard,
que parlent aussi les miroirs (devpi, Artifactory…). Vérifié le 2026-10-27 : PyPI sert la
version 1.4 de l'API.

Ce qu'on en tire :

- les versions : la liste ``versions`` (PEP 700). Un miroir qui ne la donne pas (API 1.0) :
  celles lues dans les noms de fichiers ;
- une version est **retirée** si tous ses fichiers sont « yanked » (PEP 592), avec la raison
  donnée ; sa date est celle de son premier fichier ;
- **la dernière stable** : la plus haute des versions non retirées, pré-versions exclues ;
- le Python que demande chaque version (``requires-python`` de ses fichiers, PEP 503) : uv,
  Poetry et PDM refusent une version qui ne convient pas à tout le ``requires-python`` du projet
  (``checks.runtimes``, E27) ;
- **la dépréciation** : le statut du projet. ``archived`` (plus de nouvelles versions),
  ``deprecated``, ou ``quarantined`` (soupçon de code malveillant : PyPI ne propose plus ses
  fichiers, toutes ses versions sont donc retirées).

Un index déclaré (E33, ``SimpleIndex`` : ``--index-url``, ``[[tool.uv.index]]``, une source de
Poetry…) parle la même API à son adresse (``{index}/{nom}/``) : en JSON s'il la sert, sinon en
HTML (PEP 503, celle de tous les index : Artifactory, Nexus, devpi, pypiserver, GitLab). C'est
l'``Accept`` de uv (vérifié avec uv 0.10.11 sur un index servi en local) : du JSON, puis du
HTML. Dans le HTML,
chaque lien est un fichier : son texte est le nom du fichier, ``data-yanked`` le retire (avec sa
raison), ``data-requires-python`` dit le Python qu'il demande.

Les fichiers sont rangés par version d'après leur nom : ``Flask-2.0.1-py3-none-any.whl``,
``flask-2.0.1.tar.gz``, mais aussi les vieux formats (``PyYAML-3.10.win32-py2.7.exe``,
``pytz-2005k.tar.bz2``). Le nom peut écrire la version autrement que la liste (``1.8rc1``
pour ``1.8c1``, ``69.4`` pour ``69.4.0``) : on compare alors les versions lues. Un fichier
qu'on ne sait pas ranger est ignoré, et une version sans fichier rangé n'est ni datée ni
retirée : un nom de fichier mal lu ne doit pas donner un faux « retiré ».
"""

import asyncio
from collections.abc import Iterable, Mapping
from datetime import datetime
from html.parser import HTMLParser
from typing import Any, ClassVar
from urllib.parse import quote, unquote, urlsplit

from packaging.requirements import InvalidRequirement
from packaging.requirements import Requirement as PackagingRequirement
from packaging.specifiers import SpecifierSet
from packaging.utils import (
    InvalidSdistFilename,
    InvalidWheelFilename,
    canonicalize_name,
    parse_sdist_filename,
    parse_wheel_filename,
)
from packaging.version import InvalidVersion as PackagingInvalidVersion
from packaging.version import Version

from forceupdate.models import Ecosystem
from forceupdate.net.cache import CacheKind
from forceupdate.net.http import Response
from forceupdate.registries.base import (
    PackageInfo,
    PackageVersion,
    Registry,
    RegistryError,
    Requires,
    parse_time,
    sorted_versions,
)
from forceupdate.versions import InvalidVersion
from forceupdate.versions.pypi import PYPI

ACCEPT = "application/vnd.pypi.simple.v1+json"
ACCEPT_ANY = (
    "application/vnd.pypi.simple.v1+json, application/vnd.pypi.simple.v1+html;q=0.2, "
    "text/html;q=0.01"
)
"""Celui de uv : du JSON, sinon du HTML."""

_STATUS = {
    "archived": "projet archivé sur PyPI : il ne recevra plus de nouvelles versions",
    "deprecated": "projet déclaré déprécié sur PyPI",
    "quarantined": (
        "projet mis en quarantaine par PyPI (soupçon de code malveillant) : "
        "ses fichiers ne sont plus proposés"
    ),
}
"""Les statuts de PEP 792 qui font un paquet déprécié ; ``active`` n'en est pas un."""


class PyPI(Registry):
    ecosystem = Ecosystem.PYPI
    label = "PyPI"
    base_url = "https://pypi.org"
    headers: ClassVar[Mapping[str, str]] = {"Accept": ACCEPT}

    def normalize(self, name: str) -> str:
        return canonicalize_name(name)

    def url_for(self, name: str) -> str:
        return f"{self.base_url}/simple/{quote(name)}/"

    def page_url(self, name: str) -> str | None:
        return f"https://pypi.org/project/{name}/" if self.base_url == PyPI.base_url else None

    def parse(self, name: str, response: Response, fetched_at: datetime) -> PackageInfo:
        if response.media_type != ACCEPT:
            raise ValueError(f"pas le JSON de l'API Simple ({response.media_type or 'sans type'})")
        data = _mapping(response.json())
        api = str(_mapping(data.get("meta")).get("api-version", "1.0"))
        if api.partition(".")[0] != "1":
            raise ValueError(f"version {api} de l'API Simple inconnue")
        files = [f for f in _list(data.get("files")) if isinstance(f, dict)]
        listed = data.get("versions")
        if isinstance(listed, list):
            listed = list(dict.fromkeys(v for v in listed if isinstance(v, str)))
        else:
            listed = _versions_from_filenames(f.get("filename") for f in files)
        status = _mapping(data.get("project-status"))
        return self._info(name, listed, files, status, fetched_at)

    def _info(
        self,
        name: str,
        listed: list[str],
        files: list[Mapping[str, Any]],
        status: Mapping[str, Any],
        fetched_at: datetime,
    ) -> PackageInfo:
        state = status.get("status")
        quarantined = state == "quarantined"

        groups = _group_files(name, listed, files)
        found = []
        for version in listed:
            group = groups[version]
            yanked = quarantined or (bool(group) and all(_is_yanked(f) for f in group))
            reason = "projet en quarantaine sur PyPI" if quarantined else _yanked_reason(group)
            dates = [d for d in (parse_time(f.get("upload-time")) for f in group) if d is not None]
            found.append(
                PackageVersion(
                    version=version,
                    published=min(dates, default=None),
                    yanked=yanked,
                    yanked_reason=reason if yanked else None,
                    requires_runtime=_requires_python(group),
                )
            )
        found = sorted_versions(self.ecosystem, found)
        return PackageInfo(
            ecosystem=self.ecosystem,
            name=name,
            versions=found,
            latest=PYPI.latest(v.version for v in found if not v.yanked),
            deprecated=_deprecation(state, status.get("reason")),
            url=self.page_url(name),
            fetched_at=fetched_at,
        )

    async def requires(self, name: str, version: str) -> Requires | None:
        """Ce que demande la version ``version`` (``requires_dist``, E37), lu dans l'API JSON de
        PyPI pour cette version (``/pypi/{nom}/{version}/json``) : l'API Simple ne le dit pas. Une
        requête par version, une fois par session ; rangée 7 jours dans le cache (``FILES`` : ce
        que demande une version publiée ne change pas). Seulement sur pypi.org : un index déclaré
        n'a pas cette API (``None``), ni une version que PyPI ne connaît pas."""
        if self.base_url != PyPI.base_url:
            return None
        key = (self.normalize(name), version)
        lookup = self._requires_lookups.get(key)
        if lookup is None:
            lookup = self._requires_lookups[key] = asyncio.ensure_future(self._requires_of(*key))
        return await asyncio.shield(lookup)

    async def _requires_of(self, name: str, version: str) -> Requires | None:
        url = f"{self.base_url}/pypi/{quote(name)}/{quote(version)}/json"
        entry = self._cache.get(CacheKind.FILES, url, stale_ok=self._http.offline)
        cached = entry.value if entry is not None else None
        if isinstance(cached, dict) and cached.get("format") == _REQUIRES_FORMAT:
            found = cached.get("requires")
            return None if found is None else Requires(dependencies=dict(found))
        if self._http.offline:
            raise RegistryError(
                f"{self.label} : mode hors ligne, et {name} {version} n'est pas dans le cache."
            )
        response = await self._get(url, name, found=True, headers={"Accept": "application/json"})
        requires = None
        if response is not None:
            try:
                info = _mapping(_mapping(response.json()).get("info"))
                requires = requires_dist(info.get("requires_dist"))
            except (ValueError, TypeError) as error:
                raise RegistryError(
                    f"{self.label} : réponse illisible pour {name} {version} ({error})."
                ) from error
        self._cache.set(
            CacheKind.FILES,
            url,
            {
                "format": _REQUIRES_FORMAT,
                "requires": None if requires is None else dict(requires.dependencies),
            },
        )
        return requires


_REQUIRES_FORMAT = 1
"""Version du format des entrées du cache de ``PyPI.requires``."""


def requires_dist(lines: Any) -> Requires:
    """``requires_dist`` (des lignes de PEP 508) en plages par paquet : les lignes d'un même paquet
    réunies par ``||`` (leurs marqueurs n'en gardent qu'une, qu'on ne sait pas choisir sans
    l'environnement) ; une ligne sans contrainte accepte tout (plage vide). ``null`` : aucune
    dépendance. Une ligne illisible est ignorée."""
    if lines is None:
        return Requires()
    if not isinstance(lines, list):
        raise ValueError(f"liste attendue pour requires_dist, pas {type(lines).__name__}")
    found: dict[str, list[SpecifierSet]] = {}
    for line in lines:
        if not isinstance(line, str):
            continue
        try:
            requirement = PackagingRequirement(line)
        except InvalidRequirement:
            continue
        ranges = found.setdefault(canonicalize_name(requirement.name), [])
        if requirement.specifier not in ranges:
            ranges.append(requirement.specifier)
    return Requires(dependencies={name: _union(ranges) for name, ranges in found.items()})


def _union(ranges: list[SpecifierSet]) -> str:
    """Les plages des lignes d'un même paquet, réunies : vide si l'une accepte tout ; une seule si
    elles ne diffèrent que par leur borne basse ``>=`` (``<13,>=10.3`` et ``<13,>=12``, selon la
    version de Python : la plus basse les contient toutes) ; sinon ``a || b``."""
    if any(not str(r) for r in ranges):
        return ""
    if len(ranges) > 1:
        rest = {frozenset(str(s) for s in r if s.operator != ">=") for r in ranges}
        lows = [[s for s in r if s.operator == ">="] for r in ranges]
        if len(rest) == 1 and all(len(low) <= 1 for low in lows):
            if any(not low for low in lows):
                return str(SpecifierSet(",".join(rest.pop())))
            try:
                return str(min(ranges, key=_lower_bound))
            except PackagingInvalidVersion:
                pass
    return " || ".join(str(r) for r in ranges)


def _lower_bound(specifiers: SpecifierSet) -> Version:
    return Version(next(s for s in specifiers if s.operator == ">=").version)


def _mapping(value: Any) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"objet JSON attendu, pas {type(value).__name__}")
    return value


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"liste JSON attendue, pas {type(value).__name__}")
    return value


def _is_yanked(file: Mapping[str, Any]) -> bool:
    # PEP 691 : faux, vrai, ou la raison du retrait (une chaîne).
    value = file.get("yanked", False)
    return value is True or isinstance(value, str)


def _requires_python(files: Iterable[Mapping[str, Any]]) -> str | None:
    """Le Python que demande une version (``requires-python`` de ses fichiers, le même en
    général) : celui de son premier fichier qui en dit un ; ``None`` sinon."""
    for file in files:
        value = file.get("requires-python")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _yanked_reason(files: Iterable[Mapping[str, Any]]) -> str | None:
    for file in files:
        value = file.get("yanked")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _deprecation(state: object, reason: object) -> str | None:
    message = _STATUS.get(state) if isinstance(state, str) else None
    if message is None:
        return None
    if isinstance(reason, str) and reason.strip():
        message += f" ({reason.strip()})"
    return message + "."


def _versions_from_filenames(filenames: Iterable[object]) -> list[str]:
    """Les versions lues dans les noms des wheels et des sdists, sans doublon : pour un miroir
    qui ne donne pas la liste ``versions`` (API Simple 1.0)."""
    found: dict[Any, str] = {}
    for filename in filenames:
        if not isinstance(filename, str):
            continue
        try:
            if filename.endswith(".whl"):
                version = parse_wheel_filename(filename)[1]
            else:
                version = parse_sdist_filename(filename)[1]
        except (InvalidWheelFilename, InvalidSdistFilename, ValueError):
            continue
        found.setdefault(version, str(version))
    return list(found.values())


def _group_files(
    name: str, listed: list[str], files: list[Mapping[str, Any]]
) -> dict[str, list[Mapping[str, Any]]]:
    """Les fichiers de chaque version de ``listed``, d'après leur nom."""
    canonical = canonicalize_name(name)
    known = set(listed)
    by_parsed: dict[Any, str] = {}
    for text in listed:
        try:
            by_parsed.setdefault(PYPI.parse(text), text)
        except InvalidVersion:
            continue
    groups: dict[str, list[Mapping[str, Any]]] = {text: [] for text in listed}
    for file in files:
        filename = file.get("filename")
        if not isinstance(filename, str):
            continue
        version = _file_version(filename, canonical, known, by_parsed)
        if version is not None:
            groups[version].append(file)
    return groups


def _file_version(
    filename: str, canonical: str, known: set[str], by_parsed: Mapping[Any, str]
) -> str | None:
    """La version de la liste à laquelle appartient le fichier ; ``None`` si on ne sait pas.

    Après le nom du projet et un ``-`` vient la version. Une wheel la termine par ``-`` ;
    les autres formats y collent une extension ou une plateforme (``.tar.gz``,
    ``.win32-py2.7.exe``, ``-py2.7.egg``). On essaie donc chaque coupure, de la plus longue
    à la plus courte : d'abord le texte exact de la liste, puis la même version lue.
    """
    rest = _after_name(filename, canonical)
    if rest is None:
        return None
    if filename.endswith(".whl"):
        cuts = [rest.partition("-")[0]]
    else:
        cuts = [rest[:i] for i in range(len(rest) - 1, 0, -1) if rest[i] in ".-"]
    for text in cuts:
        if text in known:
            return text
    for text in cuts:
        try:
            version = PYPI.parse(text)
        except InvalidVersion:
            continue
        if version in by_parsed:
            return by_parsed[version]
    return None


def _after_name(filename: str, canonical: str) -> str | None:
    """Ce qui suit le nom du projet et son ``-`` dans ``filename`` ; ``None`` si le fichier ne
    commence pas par le nom (écrit ``PyYAML``, ``python_dateutil``…)."""
    for index, char in enumerate(filename):
        if char == "-" and canonicalize_name(filename[:index]) == canonical:
            return filename[index + 1 :]
    return None


class SimpleIndex(PyPI):
    """Un index Python déclaré : ``base_url`` est son adresse (``https://pkgs.example/simple``)."""

    label = "index"
    headers: ClassVar[Mapping[str, str]] = {"Accept": ACCEPT_ANY}

    def url_for(self, name: str) -> str:
        return f"{self.base_url}/{quote(name)}/"

    def page_url(self, name: str) -> str | None:
        return None

    def parse(self, name: str, response: Response, fetched_at: datetime) -> PackageInfo:
        if response.media_type == ACCEPT:
            return super().parse(name, response, fetched_at)
        if response.media_type not in ("text/html", "application/vnd.pypi.simple.v1+html", ""):
            raise ValueError(f"ni JSON ni HTML de l'API Simple ({response.media_type})")
        files = simple_html_files(response.content.decode("utf-8", errors="replace"))
        listed = _versions_from_filenames(f.get("filename") for f in files)
        return self._info(name, listed, files, {}, fetched_at)


class _Links(HTMLParser):
    """Les liens d'une page de l'API Simple en HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.files: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attributes = dict(attrs)
        href = attributes.get("href") or ""
        entry: dict[str, Any] = {"href": href}
        if "data-yanked" in attributes:
            entry["yanked"] = attributes["data-yanked"] or True
        if attributes.get("data-requires-python"):
            entry["requires-python"] = attributes["data-requires-python"]
        self._current = entry
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._current is None:
            return
        entry = self._current
        text = "".join(self._text).strip()
        path = unquote(urlsplit(entry.pop("href")).path)
        entry["filename"] = text or path.rpartition("/")[2]
        self.files.append(entry)
        self._current = None


def simple_html_files(text: str) -> list[dict[str, Any]]:
    """Les fichiers d'une page de l'API Simple en HTML (PEP 503), au format de son JSON
    (``filename``, ``yanked``, ``requires-python``)."""
    parser = _Links()
    parser.feed(text)
    parser.close()
    return parser.files
