"""Le client d'un dépôt ``composer`` déclaré dans ``repositories`` (E33) : Satis, Private Packagist,
un miroir, le registre Composer de GitLab…

Comme Composer 2 (``ComposerRepository``, vérifié le 2026-11-02 avec Composer 2.11.0 et un dépôt
servi en local : ``packages.json``, puis ``p2/acme/private.json``) :

- ``{url}/packages.json`` d'abord (``url`` elle-même si elle finit par ``.json``), une fois par
  analyse : ``metadata-url`` (``/p2/%package%.json``, un chemin absolu pris sur l'hôte du dépôt, ou
  une adresse) donne le fichier de chaque paquet, au format de Packagist (``registries.packagist``,
  minifié ou non) ; ``available-packages`` et ``available-package-patterns``, s'ils sont là,
  disent quels paquets le dépôt a : un autre n'y est pas demandé ;
- sans ``metadata-url`` (Composer 1, un Satis ancien) : les paquets écrits dans ``packages``
  (``{"acme/x": {"1.0.0": {…}}}``) et dans les fichiers de ``includes`` ;
- ``providers-url`` seul (l'ancien protocole de Packagist) n'est pas lu : le paquet est dit
  introuvable sur ce dépôt.

Les identifiants : ceux d'``auth.json`` pour l'hôte du dépôt (``routing.composer``).
"""

import asyncio
import posixpath
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

from forceupdate.registries.base import PackageInfo, PackageNotFound, RegistryError
from forceupdate.registries.packagist import Packagist
from forceupdate.versions.composer import COMPOSER

MAX_INCLUDES = 20
"""Au plus autant de fichiers ``includes`` lus pour un dépôt."""


class _Root:
    """Ce que dit le ``packages.json`` d'un dépôt."""

    def __init__(self, data: dict[str, Any], packages_url: str) -> None:
        metadata = data.get("metadata-url")
        self.metadata_url = metadata if isinstance(metadata, str) and metadata else None
        available = data.get("available-packages")
        patterns = data.get("available-package-patterns")
        self.available = (
            {name.lower() for name in available if isinstance(name, str)}
            if isinstance(available, list)
            else None
        )
        self.patterns = (
            [p.lower() for p in patterns if isinstance(p, str)]
            if isinstance(patterns, list)
            else None
        )
        self.inline: dict[str, list[dict[str, Any]]] = {}
        self.add(data.get("packages"))
        includes = data.get("includes")
        self.includes = (
            [urljoin(packages_url, path) for path in includes][:MAX_INCLUDES]
            if isinstance(includes, dict)
            else []
        )

    def add(self, packages: Any) -> None:
        """Les paquets écrits en entier (``{"acme/x": {"1.0.0": {…}}}``, ou des listes)."""
        if not isinstance(packages, dict):
            return
        for name, versions in packages.items():
            entries = list(versions.values()) if isinstance(versions, dict) else versions
            if isinstance(name, str) and isinstance(entries, list):
                found = [e for e in entries if isinstance(e, dict)]
                self.inline.setdefault(name.lower(), []).extend(found)

    def has(self, name: str) -> bool | None:
        """Vrai ou faux si le dépôt dit quels paquets il a ; ``None`` s'il ne le dit pas."""
        if self.available is None and self.patterns is None:
            return None
        if name in (self.available or ()):
            return True
        return any(fnmatchcase(name, pattern) for pattern in self.patterns or ())


class ComposerRepository(Packagist):
    """Un dépôt ``composer`` déclaré, à l'adresse ``base_url`` (``url`` de ``repositories``)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._root: asyncio.Future[_Root] | None = None

    def page_url(self, name: str) -> str | None:
        return None

    def _packages_json(self) -> str:
        if urlsplit(self.base_url).path.endswith(".json"):
            return self.base_url
        return f"{self.base_url}/packages.json"

    async def _read_root(self) -> _Root:
        url = self._packages_json()
        response = await self._get(url, "son packages.json")
        assert response is not None
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("packages.json n'est pas un objet")
        root = _Root(data, url)
        for include in root.includes:
            answer = await self._get(include, posixpath.basename(urlsplit(include).path))
            assert answer is not None
            included = answer.json()
            if isinstance(included, dict):
                root.add(included.get("packages"))
        return root

    async def root(self) -> _Root:
        """Le ``packages.json`` du dépôt, lu une fois par analyse."""
        if self._root is None:
            self._root = asyncio.ensure_future(self._read_root())
        return await asyncio.shield(self._root)

    async def _url(self, name: str) -> str:
        root = await self.root()
        if root.has(name) is False or root.metadata_url is None:
            raise PackageNotFound(self._not_found(name))
        template = root.metadata_url
        if template.startswith("/"):
            parts = urlsplit(self.base_url)
            template = f"{parts.scheme}://{parts.netloc}{template}"
        return template.replace("%package%", quote(name, safe="/"))

    async def _lookup(self, name: str) -> PackageInfo:
        try:
            root = await self.root()
        except ValueError as error:
            raise RegistryError(f"{self.label} : packages.json illisible ({error}).") from error
        if root.metadata_url is None and root.has(name) is not False:
            entries = root.inline.get(name)
            if not entries:
                raise PackageNotFound(self._not_found(name))
            entries = sorted(
                (e for e in entries if isinstance(e.get("version"), str)),
                key=lambda e: COMPOSER.sort_key(e["version"]),
                reverse=True,
            )
            return self.info(name, entries, datetime.now(UTC))
        return await super()._lookup(name)
