"""Le client Packagist : les métadonnées ``p2`` de Composer 2 (``https://repo.packagist.org/p2/…``).

Un fichier par paquet, ``/p2/{vendor}/{paquet}.json``, statique, servi par un CDN, celui que lit
Composer. Vérifié le 2026-10-30 sur ``monolog/monolog``, ``guzzlehttp/guzzle``,
``symfony/console``, ``twig/twig``, ``swiftmailer/swiftmailer`` et ``doctrine/cache`` :

    {"packages": {"monolog/monolog": [{"name": …, "version": "3.12.1", "version_normalized":
     "3.12.1.0", "time": "2026-09-29T19:21:12+00:00", "require": {…}, …}, {"version": "3.12.0",
     "time": …}, …]}, "minified": "composer/2.0", "security-advisories": […]}

- les versions étiquetées, de la plus récente à la plus ancienne, pré-versions comprises ; les
  branches sont dans un autre fichier (``~dev.json``), pas demandé : une dépendance qui en suit une
  n'est pas vérifiable ;
- **« minifié »** (``"minified": "composer/2.0"``) : chaque version ne garde que ce qui change
  depuis la précédente, et ``"__unset"`` retire une clé. Reconstruit comme le fait Composer
  (``MetadataMinifier::expand``) ;
- ``require.php`` : le PHP que demande la version ; Composer la refuse si le PHP du projet
  (``config.platform.php``, sinon celui de la machine) n'y convient pas (``checks.runtimes``, E27) ;
- ``time`` : la date de l'étiquette ; ``abandoned`` : ``true``, ou le paquet qui le remplace
  (``"symfony/mailer"`` pour ``swiftmailer/swiftmailer``), écrit dans la plus récente et donc
  repris par toutes ;
- un paquet inconnu donne 404 (``404 not found, no packages here``) ; ``Cache-Control:
  max-age=900``.

Ce qu'on en tire :

- **la dernière stable** : la plus haute version stable (ni ``alpha``, ``beta``, ``RC``, comme le
  ``minimum-stability`` par défaut de Composer) ;
- **un paquet abandonné** est « déprécié », avec son remplaçant s'il en a un ;
- Packagist n'a pas de retrait : une version supprimée disparaît du fichier.

Les failles de ``security-advisories`` ne sont pas lues : elles viennent d'OSV, comme ailleurs. Les
noms sont en minuscules, comme le fait Composer.
"""

from datetime import datetime
from typing import Any
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
from forceupdate.versions.composer import COMPOSER

UNSET = "__unset"
"""La valeur qui retire une clé dans les métadonnées minifiées."""


def expand(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Les versions de métadonnées minifiées, complètes : chacune reprend la précédente, avec ce
    qui change (``MetadataMinifier::expand`` de Composer)."""
    expanded: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"version qui n'est pas un objet : {entry!r:.80}")
        if current is None:
            current = dict(entry)
        else:
            current = dict(current)
            for key, value in entry.items():
                if value == UNSET:
                    current.pop(key, None)
                else:
                    current[key] = value
        expanded.append(current)
    return expanded


def _php(require: Any) -> str | None:
    """Le PHP que demande une version (``require.php``) ; ``None`` sans."""
    php = require.get("php") if isinstance(require, dict) else None
    if not isinstance(php, str):
        return None
    return php.strip() or None


def abandoned_message(value: Any) -> str | None:
    """Le message d'un paquet abandonné (``abandoned`` : ``true`` ou son remplaçant) ; ``None`` s'il
    ne l'est pas."""
    if isinstance(value, str) and value.strip():
        return f"abandonné sur Packagist, remplacé par {value.strip()}."
    if value is True:
        return "abandonné sur Packagist, sans remplaçant indiqué."
    return None


class Packagist(Registry):
    ecosystem = Ecosystem.PACKAGIST
    label = "Packagist"
    base_url = "https://repo.packagist.org"

    def normalize(self, name: str) -> str:
        return name.strip().lower()

    def url_for(self, name: str) -> str:
        return f"{self.base_url}/p2/{quote(name, safe='/')}.json"

    def page_url(self, name: str) -> str | None:
        if self.base_url != Packagist.base_url:
            return None
        return f"https://packagist.org/packages/{name}"

    def parse(self, name: str, response: Response, fetched_at: datetime) -> PackageInfo:
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("packages"), dict):
            raise ValueError("pas de « packages »")
        entries = data["packages"].get(name)
        if not isinstance(entries, list):
            raise ValueError(f"« packages » sans {name}")
        if data.get("minified") is not None:
            entries = expand(entries)
        found = [
            PackageVersion(
                version=entry["version"],
                published=parse_time(entry.get("time")),
                requires_runtime=_php(entry.get("require")),
            )
            for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("version"), str)
        ]
        versions = sorted_versions(self.ecosystem, found)
        deprecated = abandoned_message(entries[0].get("abandoned")) if entries else None
        return PackageInfo(
            ecosystem=self.ecosystem,
            name=name,
            versions=versions,
            latest=COMPOSER.latest(v.version for v in versions),
            deprecated=deprecated,
            url=self.page_url(name),
            fetched_at=fetched_at,
        )
