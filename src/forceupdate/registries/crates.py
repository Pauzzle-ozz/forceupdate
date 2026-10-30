"""Le client crates.io : l'index « sparse » (``https://index.crates.io/…``), celui que lit Cargo.

Pourquoi l'index, et pas l'API (``https://crates.io/api/v1/crates/{nom}``) : l'API est limitée à
une requête par seconde (règles d'usage de crates.io), quand l'index est un fichier statique
servi par un CDN, sans limite, que Cargo lit des milliers de fois par seconde. Il dit ce qui
sert : chaque version, si elle est retirée (``yanked``), et sa date de publication
(``pubtime``). Vérifié le 2026-10-30 sur ``serde``, ``rand``, ``libc``, ``log``, ``cc`` et ``a``.

Un fichier par crate, une ligne JSON par version, dans l'ordre de publication :

    {"name":"serde","vers":"1.0.229","deps":[…],"cksum":"…","features":{…},"yanked":false,
     "rust_version":"1.56","pubtime":"2026-07-18T23:05:13Z"}

Le chemin du fichier vient du nom, **en minuscules** (``Serde`` donne 404) : ``1/a``, ``2/cc``,
``3/l/log``, puis les deux premières lettres et les deux suivantes, ``se/rd/serde``. Un crate
inconnu donne 404.

Ce qu'on en tire :

- les versions, datées par ``pubtime`` (l'index le donne depuis 2025, aussi pour les anciennes
  versions) ; une version est **retirée** quand ``yanked`` est vrai. L'index ne donne pas la
  raison d'un retrait ;
- **la dernière stable** : la plus haute des versions non retirées, pré-versions exclues, comme
  la « max stable version » de crates.io ;
- crates.io n'a pas de dépréciation : un crate dont toutes les versions sont retirées est dit
  retiré du registre.

Les noms ne sont pas normalisés : Cargo demande le nom exact (``serde_json``, pas
``serde-json``) ; seul le chemin de l'index l'écrit en minuscules.
"""

import json
from datetime import datetime
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
from forceupdate.versions.cargo import CARGO


def index_path(name: str) -> str:
    """Le chemin du fichier de ``name`` dans l'index de Cargo (``se/rd/serde``)."""
    lowered = name.lower()
    if len(lowered) <= 2:
        return f"{len(lowered)}/{lowered}"
    if len(lowered) == 3:
        return f"3/{lowered[0]}/{lowered}"
    return f"{lowered[:2]}/{lowered[2:4]}/{lowered}"


class Crates(Registry):
    ecosystem = Ecosystem.CRATES_IO
    label = "crates.io"
    base_url = "https://index.crates.io"

    def normalize(self, name: str) -> str:
        return name

    def url_for(self, name: str) -> str:
        return f"{self.base_url}/{quote(index_path(name))}"

    def page_url(self, name: str) -> str | None:
        if self.base_url != Crates.base_url:
            return None
        return f"https://crates.io/crates/{name}"

    def parse(self, name: str, response: Response, fetched_at: datetime) -> PackageInfo:
        lines = [line for line in response.content.decode("utf-8").splitlines() if line.strip()]
        found = []
        for line in lines:
            entry = json.loads(line)
            if not isinstance(entry, dict):
                raise ValueError(f"ligne de l'index qui n'est pas un objet : {line[:80]!r}")
            version = entry.get("vers")
            if not isinstance(version, str):
                continue
            found.append(
                PackageVersion(
                    version=version,
                    published=parse_time(entry.get("pubtime")),
                    yanked=entry.get("yanked") is True,
                )
            )
        versions = sorted_versions(self.ecosystem, found)
        available = [v.version for v in versions if not v.yanked]
        deprecated = None
        if versions and not available:
            deprecated = "toutes ses versions ont été retirées de crates.io."
        return PackageInfo(
            ecosystem=self.ecosystem,
            name=name,
            versions=versions,
            latest=CARGO.latest(available),
            deprecated=deprecated,
            url=self.page_url(name),
            fetched_at=fetched_at,
        )
