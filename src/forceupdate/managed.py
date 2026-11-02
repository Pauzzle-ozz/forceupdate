"""Les versions gérées hors du dépôt (E34) : une dépendance Maven sans ``<version>`` dont la version
vient d'un parent distant (``spring-boot-starter-parent``) ou d'un BOM importé
(``<type>pom</type><scope>import</scope>``).

Le parseur ne lit pas le réseau : il la dit « non vérifiable » (« version gérée par le parent …
(hors du dépôt) », « … par un BOM importé (…) »). Le moteur lit ici le ``pom`` de ce parent ou de
ces BOM à leur dépôt (``registries.maven.Maven.pom``, gardé 7 jours en cache), comme Maven
construit le modèle d'un projet :

- **l'héritage** : le ``pom.xml``, ses parents du dépôt, puis le parent distant et ses propres
  parents, du plus proche au plus loin. La première ``<dependencyManagement>`` qui gère l'artefact
  l'emporte (``<pluginManagement>`` pour un plugin) ; ses ``${…}`` se lisent avec les propriétés de
  toute la chaîne, celle du plus proche l'emportant (``${project.version}`` est celle du projet) :
  la propriété d'un projet Spring Boot (``<jackson-bom.version>``) change la version que donne son
  parent, comme dans Maven ;
- **les BOM importés** de la chaîne ensuite, dans l'ordre, chacun avec son propre héritage et ses
  propres propriétés, et ses propres imports ; le premier qui gère l'artefact l'emporte.

Vérifié le 2026-11-02 sur Maven Central : spring-boot-starter-parent 3.2.0 a pour parent
spring-boot-dependencies 3.2.0, qui gère ``spring-boot-starter-web`` (``3.2.0``) et importe 39 BOM,
dont ``jackson-bom`` (``${jackson-bom.version}`` : 2.15.3), lui-même fils de ``jackson-parent``
2.15 ; ``jackson-databind`` y vaut ``${jackson.version.databind}``.

La dépendance devient vérifiable, à la version ainsi trouvée ; sa mise à jour est celle du parent ou
du BOM (ou une ``<version>`` écrite dans le ``pom.xml``) : elle est « à la main »
(``Dependency.manual``), jamais pré-cochée. Un ``pom`` introuvable ou illisible la laisse non
vérifiable, avec la raison. Au plus ``MAX_POMS`` fichiers par analyse.
"""

import asyncio
import dataclasses
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass

from forceupdate.models import Dependency, Ecosystem, Project, Report, Scope
from forceupdate.parsers import maven
from forceupdate.parsers.base import ParseError, ReadText
from forceupdate.parsers.maven import Pom
from forceupdate.registries import RegistryError
from forceupdate.versions import InvalidConstraint
from forceupdate.versions.maven import MAVEN

REMOTE_PARENT = "version gérée par le parent "
REMOTE_BOM = "version gérée par un BOM importé ("
MAX_POMS = 120
"""``pom`` distants lus au plus dans une analyse (Spring Boot en importe une quarantaine)."""
MAX_PARENTS = 10
MAX_IMPORTS = 4
"""Profondeur des BOM importés par un BOM."""
_REFERENCE = re.compile(r"\$\{([^}]*)\}")

Fetch = Callable[[str, str], Awaitable[str | None]]
"""Le texte du ``pom`` d'un artefact (``groupe:artefact``) à une version ; ``None`` s'il est
introuvable. Peut lever ``RegistryError``."""


class _Unreadable(Exception):
    pass


@dataclass(frozen=True, kw_only=True)
class _Managed:
    version: str
    origin: str
    """Ce que la personne met à jour pour la changer : « le parent g:a:v », « le BOM g:a:v »."""


Management = dict[tuple[str, str, str], _Managed]
"""Les versions gérées : (sorte, groupe, artefact) → version. La sorte : ``managed``
(``dependencyManagement``) ou ``managed-plugin`` (``pluginManagement``)."""


def is_remote(reason: str | None) -> bool:
    """Vrai pour une dépendance dont la version est gérée hors du dépôt (voir la docstring)."""
    return reason is not None and reason.startswith((REMOTE_PARENT, REMOTE_BOM))


async def resolve(report: Report, read_text: ReadText, fetch: Callable[[Project], Fetch]) -> None:
    """Rend vérifiables les dépendances Maven de ``report`` dont la version est gérée hors du
    dépôt, d'après les ``pom`` distants (voir la docstring du module). ``fetch`` : de quoi lire
    un ``pom`` pour un projet (ses dépôts déclarés, puis Maven Central)."""
    for project in report.projects:
        if Ecosystem.MAVEN not in project.ecosystems:
            continue
        pending = {
            index: dependency
            for index, dependency in enumerate(project.dependencies)
            if dependency.ecosystem is Ecosystem.MAVEN and is_remote(dependency.unverifiable_reason)
        }
        if not pending:
            continue
        reader = _Reader(fetch(project))
        files = sorted({dependency.file for dependency in pending.values()})
        models = await asyncio.gather(*(reader.project(file, read_text) for file in files))
        by_file = dict(zip(files, models, strict=True))
        for index, dependency in pending.items():
            project.dependencies[index] = _resolved(dependency, by_file[dependency.file])


def _resolved(dependency: Dependency, model: tuple[Management, list[str]]) -> Dependency:
    management, problems = model
    group, _, artifact = dependency.name.partition(":")
    kinds = ("managed-plugin", "managed") if dependency.scope is Scope.BUILD else ("managed",)
    found = next(
        (management[k, group, artifact] for k in kinds if (k, group, artifact) in management),
        None,
    )
    if found is None:
        if not problems:
            return dependency
        # Le problème du parent ou du BOM que cite la raison, sinon le premier.
        cited = re.findall(r"[\w.-]+:[\w.-]+", dependency.unverifiable_reason or "")
        problem = next((p for p in problems if any(f"{c}:" in p for c in cited)), problems[0])
        reason = f"{dependency.unverifiable_reason} : {problem}"
        return dataclasses.replace(dependency, unverifiable_reason=reason)
    try:
        installed = MAVEN.exact(found.version)
    except InvalidConstraint:
        installed = None
    return dataclasses.replace(
        dependency,
        constraint=found.version,
        installed=installed,
        unverifiable_reason=None,
        manual=(
            f"version gérée par {found.origin} : la changer avec lui, ou écrire la <version> voulue"
        ),
    )


class _Reader:
    """Les ``pom`` distants d'un projet, chacun lu une fois."""

    def __init__(self, fetch: Fetch) -> None:
        self._fetch = fetch
        self._poms: dict[tuple[str, str], asyncio.Future[Pom]] = {}
        self._boms: dict[tuple[str, str], asyncio.Future[Management]] = {}

    async def project(self, path: str, read_text: ReadText) -> tuple[Management, list[str]]:
        """La gestion de ``path`` (un ``pom.xml`` du dépôt) : celle de son héritage, puis de ses
        BOM ; et pourquoi des ``pom`` n'ont pas pu être lus."""
        local = maven.pom_chain(path, read_text)
        if not local:
            return {}, []
        own = local[0]
        problems: list[str] = []
        try:
            remote = await self._parents(local[-1], _values(local))
        except _Unreadable as error:
            remote, problems = [], [str(error)]
        chain = [*local, *remote]
        values = _values(chain, own)
        parent = local[-1].parent
        origin = (
            f"le parent {parent.group}:{parent.artifact}:{_interpolate(parent.version, values)}"
            if parent is not None and remote
            else ""
        )
        management = await self._management(
            chain, values, depth=0, problems=problems, local=len(local), origin=origin
        )
        return management, problems

    async def _pom(self, name: str, version: str) -> Pom:
        key = (name, version)
        lookup = self._poms.get(key)
        if lookup is None:
            lookup = self._poms[key] = asyncio.ensure_future(self._load(name, version))
        return await asyncio.shield(lookup)

    async def _load(self, name: str, version: str) -> Pom:
        if sum(1 for f in self._poms.values() if f.done()) >= MAX_POMS:
            raise _Unreadable(f"plus de {MAX_POMS} pom distants à lire")
        try:
            text = await self._fetch(name, version)
        except RegistryError as error:
            raise _Unreadable(f"le pom de {name}:{version} n'a pas pu être lu ({error})") from error
        if text is None:
            raise _Unreadable(f"le pom de {name}:{version} est introuvable")
        try:
            return maven.read_pom(f"{name}:{version}", text)
        except ParseError as error:
            raise _Unreadable(f"le pom de {name}:{version} est illisible ({error})") from error

    async def _parents(self, pom: Pom, values: Mapping[str, str]) -> list[Pom]:
        """Les parents distants de ``pom``, du plus proche au plus loin."""
        found: list[Pom] = []
        current = pom
        while current.parent is not None and len(found) < MAX_PARENTS:
            reference = current.parent
            version = _interpolate(reference.version, {**values, **_values([current])})
            if not version:
                raise _Unreadable(
                    f"la version du parent {reference.group}:{reference.artifact} ne se lit pas"
                )
            current = await self._pom(f"{reference.group}:{reference.artifact}", version)
            found.append(current)
        return found

    async def _bom(self, name: str, version: str, depth: int) -> Management:
        key = (name, version)
        lookup = self._boms.get(key)
        if lookup is None:
            lookup = self._boms[key] = asyncio.ensure_future(self._bom_model(name, version, depth))
        return await asyncio.shield(lookup)

    async def _bom_model(self, name: str, version: str, depth: int) -> Management:
        pom = await self._pom(name, version)
        chain = [pom, *await self._parents(pom, _values([pom]))]
        problems: list[str] = []
        return await self._management(
            chain,
            _values(chain, pom),
            depth=depth,
            problems=problems,
            local=0,
            origin=f"le BOM {name}:{version}",
        )

    async def _management(
        self,
        chain: Sequence[Pom],
        values: Mapping[str, str],
        *,
        depth: int,
        problems: list[str],
        local: int,
        origin: str,
    ) -> Management:
        """La gestion d'une chaîne d'héritage (voir la docstring du module). ``local`` : combien
        de ses ``pom`` sont du dépôt (leurs BOM se disent « le BOM … », ceux du parent distant
        « le parent … ») ; ``origin`` : ce que vaut la gestion héritée du parent distant."""
        found: Management = {}
        for pom in chain[local:]:  # celles des pom du dépôt, le parseur les a lues
            for entry in pom.entries:
                if entry.kind not in ("managed", "managed-plugin") or entry.is_import:
                    continue
                if entry.profile is not None:
                    continue  # un profil : Maven ne l'active que sous condition
                key = _key(entry.kind, entry.group, entry.artifact, values)
                version = _interpolate(entry.version, values)
                if key is not None and version and origin:
                    found.setdefault(key, _Managed(version=version, origin=origin))
        if depth >= MAX_IMPORTS:
            return found
        imports: list[tuple[str, str, str]] = []
        for position, pom in enumerate(chain):
            for entry in pom.entries:
                if not entry.is_import or (position >= local and entry.profile is not None):
                    continue
                group = _interpolate(entry.group, values)
                artifact = _interpolate(entry.artifact, values)
                version = _interpolate(entry.version, values)
                if not (group and artifact and version):
                    continue
                name = f"{group}:{artifact}"
                label = f"le BOM {name}:{version}" if position < local else origin
                imports.append((name, version, label))
        results = await asyncio.gather(
            *(self._bom(name, version, depth + 1) for name, version, _ in imports),
            return_exceptions=True,
        )
        for (_, _, label), result in zip(imports, results, strict=True):
            if isinstance(result, _Unreadable):
                problems.append(str(result))
                continue
            if isinstance(result, BaseException):
                raise result
            for key, managed in result.items():
                found.setdefault(
                    key, _Managed(version=managed.version, origin=label or managed.origin)
                )
        return found


def _key(
    kind: str, group: str, artifact: str, values: Mapping[str, str]
) -> tuple[str, str, str] | None:
    resolved_group = _interpolate(group, values)
    resolved_artifact = _interpolate(artifact, values)
    if not resolved_group or not resolved_artifact:
        return None
    return kind, resolved_group, resolved_artifact


def _values(chain: Sequence[Pom], own: Pom | None = None) -> dict[str, str]:
    """Les propriétés de ``chain`` (le plus proche l'emporte), et celles du modèle du projet
    ``own`` (``project.version``…)."""
    values: dict[str, str] = {}
    for pom in reversed(chain):
        values.update({name: item.value for name, item in pom.properties.items()})
    project = own or (chain[0] if chain else None)
    if project is not None:
        for key, value in (
            ("groupId", project.group),
            ("artifactId", project.artifact),
            ("version", project.version),
        ):
            if value:
                values.setdefault(f"project.{key}", value)
                values.setdefault(f"pom.{key}", value)
        if project.parent is not None and project.parent.version:
            values.setdefault("project.parent.version", project.parent.version)
    return values


def _interpolate(text: str | None, values: Mapping[str, str], depth: int = 0) -> str | None:
    """``text`` avec ses ``${…}`` remplacés ; ``None`` s'il en reste un qu'on ne connaît pas."""
    if text is None:
        return None
    text = text.strip()
    if "${" not in text:
        return text
    if depth >= 10:
        return None
    missing = False

    def replace(match: re.Match[str]) -> str:
        nonlocal missing
        found = values.get(match.group(1))
        if found is None:
            missing = True
            return match.group(0)
        return found

    replaced = _REFERENCE.sub(replace, text)
    if missing:
        return None
    return _interpolate(replaced, values, depth + 1)
