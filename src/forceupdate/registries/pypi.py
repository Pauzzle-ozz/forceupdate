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
- **la dépréciation** : le statut du projet. ``archived`` (plus de nouvelles versions),
  ``deprecated``, ou ``quarantined`` (soupçon de code malveillant : PyPI ne propose plus ses
  fichiers, toutes ses versions sont donc retirées).

Les fichiers sont rangés par version d'après leur nom : ``Flask-2.0.1-py3-none-any.whl``,
``flask-2.0.1.tar.gz``, mais aussi les vieux formats (``PyYAML-3.10.win32-py2.7.exe``,
``pytz-2005k.tar.bz2``). Le nom peut écrire la version autrement que la liste (``1.8rc1``
pour ``1.8c1``, ``69.4`` pour ``69.4.0``) : on compare alors les versions lues. Un fichier
qu'on ne sait pas ranger est ignoré, et une version sans fichier rangé n'est ni datée ni
retirée : un nom de fichier mal lu ne doit pas donner un faux « retiré ».
"""

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, ClassVar
from urllib.parse import quote

from packaging.utils import (
    InvalidSdistFilename,
    InvalidWheelFilename,
    canonicalize_name,
    parse_sdist_filename,
    parse_wheel_filename,
)

from forceupdate.models import Ecosystem
from forceupdate.net.http import Response
from forceupdate.registries.base import (
    PackageInfo,
    PackageVersion,
    Registry,
    parse_time,
    sorted_versions,
)
from forceupdate.versions import InvalidVersion
from forceupdate.versions.pypi import PYPI

ACCEPT = "application/vnd.pypi.simple.v1+json"

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
