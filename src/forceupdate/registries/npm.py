"""Le client npm : le document complet d'un paquet (``GET /{nom}``).

Pourquoi le document complet, et pas l'abrégé que lit ``npm install`` (``Accept:
application/vnd.npm.install-v1+json``) : l'abrégé garde les ``dist-tags`` et le
``deprecated`` de chaque version, mais perd les dates de publication (``time``). Et il
n'allège pas là où ça compte : compressés, les deux pèsent presque pareil (``@types/node`` :
1,4 Mo contre 1,1), et pour ``next``, le plus gros, l'abrégé fait encore 25,7 Mo
décompressés contre 31,5, à lire aussi lentement. Mesuré le 2026-10-27. Du document, on ne
garde que ce qui sert : c'est ça qui va dans le cache.

Ce qu'on en tire :

- les versions (``versions``), datées par ``time``. npm n'a pas de retrait : une version
  dépubliée disparaît, aucune n'est donc « retirée » ;
- le ``deprecated`` de chaque version (une chaîne vide veut dire « plus dépréciée ») ;
- les étiquettes (``dist-tags``), pour une dépendance écrite avec une étiquette ;
- **la dernière stable** : ``dist-tags.latest`` si c'est une version stable. C'est celle que
  choisit ``npm install``, et celle que suivent Renovate et Dependabot. Une version plus
  haute publiée sous une autre étiquette (une 5.0.0 sous ``next``) n'est pas proposée : le
  mainteneur ne l'a pas encore désignée comme la version à installer. Si ``latest`` est une
  pré-version, ou manque : la plus haute stable qui ne la dépasse pas ;
- **la dépréciation du paquet** : celle de sa version ``latest``, comme sur npmjs.com. Deux
  cas s'y ajoutent : un paquet remplacé par l'équipe sécurité de npm (version
  ``0.0.1-security``, « security holding package »), souvent pour du code malveillant, et un
  paquet dont toutes les versions ont été dépubliées.

Un nom scopé s'encode : ``@types/node`` → ``@types%2Fnode``.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, ClassVar
from urllib.parse import quote

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
from forceupdate.versions.npm import NPM

_SECURITY_HOLDING = "security holding package"
"""La description des paquets vides que publie l'équipe sécurité de npm à la place d'un paquet
retiré."""


class Npm(Registry):
    ecosystem = Ecosystem.NPM
    label = "npm"
    base_url = "https://registry.npmjs.org"
    headers: ClassVar[Mapping[str, str]] = {"Accept": "application/json"}

    def normalize(self, name: str) -> str:
        return name

    def url_for(self, name: str) -> str:
        return f"{self.base_url}/{quote(name, safe='@')}"

    def page_url(self, name: str) -> str | None:
        if self.base_url != Npm.base_url:
            return None
        return f"https://www.npmjs.com/package/{name}"

    def parse(self, name: str, response: Response, fetched_at: datetime) -> PackageInfo:
        data = _mapping(response.json())
        manifests = {
            version: _mapping(manifest)
            for version, manifest in _mapping(data.get("versions")).items()
        }
        times = _mapping(data.get("time"))
        tags = {
            tag: version
            for tag, version in _mapping(data.get("dist-tags")).items()
            if isinstance(version, str)
        }
        found = sorted_versions(
            self.ecosystem,
            (
                PackageVersion(
                    version=version,
                    published=parse_time(times.get(version)),
                    deprecated=_deprecation(manifest),
                )
                for version, manifest in manifests.items()
            ),
        )
        latest = _latest([v.version for v in found], tags.get("latest"))
        return PackageInfo(
            ecosystem=self.ecosystem,
            name=name,
            versions=found,
            latest=latest,
            deprecated=_package_deprecation(manifests, times, tags.get("latest") or latest),
            tags=tags,
            url=self.page_url(name),
            fetched_at=fetched_at,
        )


def _mapping(value: Any) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"objet JSON attendu, pas {type(value).__name__}")
    return value


def _deprecation(manifest: Mapping[str, Any]) -> str | None:
    value = manifest.get("deprecated")
    if isinstance(value, str):
        return value.strip() or None
    return "version dépréciée" if value is True else None


def _latest(published: list[str], tag: str | None) -> str | None:
    """La dernière stable : la plus haute des candidates qui ne dépasse pas ``tag``
    (``dist-tags.latest``), ou de toutes si ``tag`` manque ou est illisible."""
    if tag is not None:
        try:
            ceiling = NPM.parse(tag)
        except InvalidVersion:
            ceiling = None
        if ceiling is not None:
            published = [v for v in published if _at_most(v, ceiling)]
    return NPM.latest(published)


def _at_most(version: str, ceiling: Any) -> bool:
    try:
        return not ceiling < NPM.parse(version)
    except InvalidVersion:
        return False


def _package_deprecation(
    manifests: Mapping[str, Mapping[str, Any]], times: Mapping[str, Any], latest: str | None
) -> str | None:
    if not manifests and "unpublished" in times:
        return "toutes ses versions ont été dépubliées du registre npm."
    manifest = manifests.get(latest) if latest is not None else None
    if manifest is None:
        return None
    if manifest.get("description") == _SECURITY_HOLDING:
        return (
            "paquet retiré du registre par l'équipe sécurité de npm, souvent pour du code"
            " malveillant : son nom est gardé par un paquet vide."
        )
    return _deprecation(manifest)
