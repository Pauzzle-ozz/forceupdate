"""Le client du proxy Go (``https://proxy.golang.org``), celui que ``go`` interroge par défaut.

Le protocole ``GOPROXY`` (vérifié le 2026-10-30 sur ``github.com/go-chi/chi``,
``github.com/BurntSushi/toml``, ``github.com/golang/protobuf``, ``golang.org/x/text``…) :

- ``{module}/@v/list`` : les versions étiquetées, une par ligne, **dans le désordre**, sans
  pseudo-versions ni dates ;
- ``{module}/@v/{version}.mod`` : le ``go.mod`` de cette version (rien qu'une ligne ``module``
  quand elle n'en a pas, ce qu'est une ``+incompatible``) ;
- ``{module}/@latest`` : ``{"Version": …, "Time": …}``, la seule source quand la liste est vide (un
  module sans étiquette : une pseudo-version du dernier commit) ;
- le chemin et la version **en minuscules, une majuscule écrite ``!`` puis sa minuscule**
  (``github.com/!burnt!sushi/toml``) ; ``github.com/BurntSushi/toml`` tel quel donne 404 ;
- 404 ou 410 : le proxy ne connaît pas le module (privé, mal écrit, ou introuvable pour lui :
  il le cherche lui-même chez son hébergeur). ``Cache-Control: max-age=60`` sur la liste.

Ce qu'on en tire, comme ``go`` (référence des modules, « Version queries », « retract ») :

- **la dernière** : la plus haute des versions publiées ; à défaut la plus haute des
  pré-versions ; à défaut la pseudo-version de ``@latest``. Les ``+incompatible`` n'y comptent pas
  quand la dernière version compatible a un ``go.mod`` (``versionHasGoMod`` : autre chose qu'une
  ligne ``module``) : chi v1.5.5 l'emporte sur v4.1.2+incompatible ;
- **les retraits** (``retract``) et **la dépréciation** (``// Deprecated:``) se lisent dans le
  ``go.mod`` de cette dernière version, retraits ignorés. Une version retirée l'est avec sa
  raison ; la dernière proposée est la plus haute non retirée ;
- **une majeure plus récente** a un autre chemin (``…/v5``, ``gopkg.in/yaml.v3``) : on demande la
  liste du chemin de la majeure suivante, tant qu'il y en a une. Sa dernière version est ajoutée
  aux versions du module (``VersionScheme.moved`` dit où elle est publiée) et devient la
  « dernière » : elle est proposée, jamais appliquée seule (``update.planner``). Une requête de
  plus par module (souvent un 404).

Les noms ne sont pas normalisés : un chemin de module distingue les majuscules.
"""

from datetime import datetime
from urllib.parse import quote

from forceupdate.models import Ecosystem
from forceupdate.net.http import Response
from forceupdate.parsers.base import ParseError
from forceupdate.parsers.go import GoMod, Retraction, parse_go_mod_file
from forceupdate.registries.base import (
    PackageInfo,
    PackageNotFound,
    PackageVersion,
    Registry,
    sorted_versions,
)
from forceupdate.versions import InvalidVersion
from forceupdate.versions.go import GO, INCOMPATIBLE, module_path, path_major

MAX_MAJOR_PROBES = 10
"""Au plus autant de chemins de majeures suivantes demandés pour un module."""


def escape(text: str) -> str:
    """``text`` (un chemin de module, une version) comme l'écrit le proxy : une majuscule devient
    ``!`` suivi de sa minuscule."""
    return "".join(f"!{char.lower()}" if char.isupper() else char for char in text)


def latest_of(versions: list[str]) -> str | None:
    """La version que ``go`` prend pour la dernière : la plus haute des publiées, sinon des
    pré-versions (et pseudo-versions)."""
    readable = []
    for version in versions:
        try:
            readable.append((version, GO.parse(version)))
        except InvalidVersion:
            continue
    releases = [pair for pair in readable if not pair[1].prerelease]
    pool = releases or readable
    return max(pool, key=lambda pair: pair[1])[0] if pool else None


def has_go_mod(mod: GoMod, content: str) -> bool:
    """Vrai si un ``go.mod`` rendu par le proxy est un vrai ``go.mod`` : il dit autre chose que la
    ligne ``module`` que le proxy écrit pour une version qui n'en a pas."""
    lines = [line.strip() for line in content.splitlines()]
    words = [line for line in lines if line and not line.startswith("//")]
    return mod.module is None or len(words) != 1


class GoProxy(Registry):
    ecosystem = Ecosystem.GO
    label = "proxy.golang.org"
    base_url = "https://proxy.golang.org"
    not_found_statuses = frozenset({404, 410})

    def normalize(self, name: str) -> str:
        return name

    def url_for(self, name: str) -> str:
        return self._path(name, "@v/list")

    def page_url(self, name: str) -> str | None:
        if self.base_url != GoProxy.base_url:
            return None
        return f"https://pkg.go.dev/{name}"

    def _not_found(self, name: str) -> str:
        if self.declared:
            return f"{name} est introuvable sur {self.label}."
        return f"{name} est introuvable sur {self.label} : module privé, ou chemin mal écrit ?"

    def _path(self, name: str, suffix: str) -> str:
        return f"{self.base_url}/{quote(escape(name), safe='/!~+')}/{suffix}"

    def parse(self, name: str, response: Response, fetched_at: datetime) -> PackageInfo:
        listed = [line.strip() for line in response.content.decode("utf-8").splitlines()]
        found = [PackageVersion(version=version) for version in dict.fromkeys(listed) if version]
        return PackageInfo(
            ecosystem=self.ecosystem,
            name=name,
            versions=sorted_versions(self.ecosystem, found),
            latest=None,
            url=self.page_url(name),
            fetched_at=fetched_at,
        )

    async def _complete(self, name: str, info: PackageInfo) -> PackageInfo:
        listed = [v.version for v in info.versions]
        if not listed:
            pseudo = await self._latest(name)
            if pseudo is None:
                raise PackageNotFound(self._not_found(name))
            listed = [pseudo]
        compatible = [v for v in listed if INCOMPATIBLE not in v]
        candidates = listed
        top = latest_of(compatible)
        mod = await self._go_mod(name, top) if top is not None else None
        if mod is not None and has_go_mod(*mod):
            candidates = compatible
        latest_listed = latest_of(candidates)
        if latest_listed is not None and latest_listed != top:
            mod = await self._go_mod(name, latest_listed)
        retracts = mod[0].retracts if mod is not None else []
        versions = []
        for version in listed:
            reason = _retracted(version, retracts)
            versions.append(
                PackageVersion(
                    version=version, yanked=reason is not None, yanked_reason=reason or None
                )
            )
        kept = [v.version for v in versions if not v.yanked and v.version in candidates]
        latest = latest_of(kept)
        newer = await self._newer_major(name, listed)
        if newer is not None:
            versions.append(PackageVersion(version=newer))
            latest = newer
        return PackageInfo(
            ecosystem=self.ecosystem,
            name=name,
            versions=sorted_versions(self.ecosystem, versions),
            latest=latest,
            deprecated=mod[0].deprecated if mod is not None else None,
            url=info.url,
            fetched_at=info.fetched_at,
        )

    async def _latest(self, name: str) -> str | None:
        """La version de ``@latest`` (une pseudo-version pour un module sans étiquette)."""
        response = await self._get(self._path(name, "@latest"), name, found=True)
        if response is None:
            return None
        version = response.json().get("Version")
        if not isinstance(version, str):
            raise ValueError("@latest sans « Version »")
        return version

    async def _go_mod(self, name: str, version: str) -> tuple[GoMod, str] | None:
        """Le ``go.mod`` de ``version``, lu, et son texte ; ``None`` si le proxy ne l'a pas."""
        response = await self._get(self._path(name, f"@v/{escape(version)}.mod"), name, found=True)
        if response is None:
            return None
        content = response.content.decode("utf-8", errors="replace")
        try:
            return parse_go_mod_file("go.mod", content), content
        except ParseError as error:
            raise ValueError(f"go.mod de {version} : {error}") from error

    async def _newer_major(self, name: str, listed: list[str]) -> str | None:
        """La dernière version de la plus haute majeure publiée sous un autre chemin que
        ``name`` (``…/v5``) ; ``None`` s'il n'y en a pas. Une majeure qui n'a que des
        pré-versions n'est pas encore publiée."""
        majors = []
        for version in listed:
            try:
                majors.append(GO.parse(version).major)
            except InvalidVersion:
                continue
        major = max([path_major(name) or 1, *majors]) + 1
        found = None
        for _ in range(MAX_MAJOR_PROBES):
            path = module_path(name, major)
            response = await self._get(self._path(path, "@v/list"), path, found=True)
            if response is None:
                break
            versions = [line.strip() for line in response.content.decode().splitlines()]
            latest = latest_of([v for v in versions if v and INCOMPATIBLE not in v])
            if latest is None or GO.is_prerelease(latest):
                break
            found = latest
            major += 1
        return found


def _retracted(version: str, retracts: list[Retraction]) -> str | None:
    """La raison du retrait de ``version`` (``""`` sans raison donnée) ; ``None`` si elle n'est
    pas retirée."""
    for retraction in retracts:
        try:
            if GO.compare(retraction.low, version) <= 0 <= GO.compare(retraction.high, version):
                return retraction.rationale
        except InvalidVersion:
            continue
    return None
