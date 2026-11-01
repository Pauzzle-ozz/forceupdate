"""Le parseur NuGet : ``packages.config``, les projets MSBuild (``*.csproj``, ``*.fsproj``,
``*.vbproj``), ``Directory.Packages.props``, ``Directory.Build.props`` et ``packages.lock.json``,
lus par ``xml.parsers.expat`` (``parsers.xml_spans``) et ``json``. MSBuild n'est jamais lancé.

**Ce qui est lu** :

- un projet MSBuild : ses ``<PackageReference Include="x" Version="…" />`` (la version en attribut
  ou en élément ``<Version>``) et ses ``<PropertyGroup>``. Avant lui, comme MSBuild, le
  ``Directory.Build.props`` le plus proche (dans son dossier ou au-dessus, et celui qu'il importe
  plus haut par ``GetPathOfFileAbove``), puis le ``Directory.Packages.props`` le plus proche : leurs
  propriétés et leurs ``PackageReference`` valent pour le projet ;
- la gestion centrale (``ManagePackageVersionsCentrally`` à ``true``) : une ``PackageReference``
  sans version prend celle de ``<PackageVersion Include="x" Version="…" />``, sauf
  ``VersionOverride`` ; ``<GlobalPackageReference>`` vaut pour tous les projets. Le projet du
  dossier de ``Directory.Packages.props`` donne ses versions centrales que n'utilisent pas les
  projets de ce dossier, comme un ``pom.xml`` parent donne sa ``dependencyManagement`` ;
- ``packages.config`` (l'ancien format, d'un projet sans ``PackageReference``) :
  ``<package id="x" version="1.2.3" />``, la version installée ; ``developmentDependency`` ;
  ``allowedVersions`` : les versions hors de la plage ne sont jamais proposées
  (``Dependency.excluded``) ;
- ``packages.lock.json`` (``RestorePackagesWithLockFile``) : pour chaque framework cible, la
  version résolue des directes (``Direct``), des indirectes (``Transitive``), des versions
  centrales venues par un autre paquet ou un projet référencé (``CentralTransitive``), et les
  projets référencés (``Project``), en graphe.

Les noms NuGet ne tiennent pas compte de la casse : ils sont comparés en minuscules, et gardés
tels qu'écrits.

**Où est la version** : là où elle est écrite, comme pour Maven (``parsers.maven``) : l'attribut
``Version`` (ou l'élément), la valeur de la propriété ``$(X)`` qu'il cite (du projet, ou d'un
``Directory.Build.props``), ``VersionOverride``, l'attribut ``Version`` de la ``PackageVersion``
centrale. ``Dependency.file`` est le fichier où elle est écrite. Une version écrite une fois pour
plusieurs projets (centrale, ou une propriété de ``Directory.Build.props``) a le même emplacement
pour chacun : elle se réécrit une fois. Une indirecte ``CentralTransitive`` a celui de sa
``PackageVersion``.

**La version utilisée** : celle du lockfile (la plus basse qui respecte la contrainte quand les
frameworks en résolvent plusieurs, les autres en indirectes) ; sans lockfile, celle que NuGet
prend d'après la contrainte (``versions.nuget`` : la borne basse d'une version nue).

**Les scopes** : ``PrivateAssets="all"`` (un analyseur, SourceLink…) et ``GlobalPackageReference``
→ ``build`` ; dans un projet de tests (``IsTestProject``, ou une référence à
``Microsoft.NET.Test.Sdk``) → ``dev`` ; ``developmentDependency="true"`` (``packages.config``) →
``dev``.

**Non vérifiables**, avec la raison : une propriété introuvable ou définie sous condition, une
expression MSBuild (``$([…])``), une référence sans version, une version centrale manquante.

**Conditions** (``Condition="…"``) : jamais évaluées. Une ``PackageReference`` conditionnelle (ou
dans un ``<Choose>``) est lue comme toujours présente, et une remarque le dit ; une propriété
définie sous condition n'a pas de valeur sûre, sauf la forme « si elle n'a pas de valeur »
(``Condition="'$(X)' == ''"``).

Repris de ``reference/argos_sca_parsers.py`` (``parse_packages_config``, L1061-1080), puis réécrit :
``xml.parsers.expat`` au lieu d'un motif (``id`` y devait précéder ``version``), emplacement de la
version, ``developmentDependency``, ``allowedVersions``, un fichier invalide signalé
(``ParseError``) ; les projets MSBuild, la gestion centrale et le lockfile ajoutés.
"""

import dataclasses
import functools
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from forceupdate.detect.manifests import match_dependency_file
from forceupdate.models import Dependency, Ecosystem, Location, Notice, Project, Scope
from forceupdate.parsers.base import ParseError, ReadText
from forceupdate.parsers.lockfiles import Edge, LockedPackage, Lockfile, Start, dirname, join
from forceupdate.parsers.lockfiles import transitives as lockfile_transitives
from forceupdate.parsers.xml_spans import Element, parse
from forceupdate.versions import InvalidConstraint, InvalidVersion
from forceupdate.versions.nuget import NUGET

CENTRAL = "Directory.Packages.props"
BUILD_PROPS = "Directory.Build.props"
PACKAGES_CONFIG = "packages.config"
LOCKFILE = "packages.lock.json"
PROJECTS = ("*.csproj", "*.fsproj", "*.vbproj")
TEST_SDK = "microsoft.net.test.sdk"

REASON_NO_VERSION = "aucune version écrite : NuGet prend la plus basse publiée"
REASON_NO_CENTRAL = "aucune version centrale (<PackageVersion>) pour ce paquet"
REASON_EXPRESSION = "version calculée par MSBuild"

_REFERENCE = re.compile(r"\$\(([^()$]*)\)")
_EXPRESSION = re.compile(r"\$\(\s*\[|@\(|%\(")
"""Une fonction de propriété (``$([System.String]::…)``), une liste d'éléments, une
métadonnée."""
_DEFAULT = re.compile(r"\s*'\$\((?P<name>[^()$']+)\)'\s*==\s*''\s*")
"""``'$(X)' == ''`` : la propriété ne prend cette valeur que si elle n'en a pas encore."""
_ABOVE = re.compile(r"GetPathOfFileAbove|GetDirectoryNameOfFileAbove", re.IGNORECASE)
_MAX_DEPTH = 10
"""Propriétés qui renvoient à d'autres, au plus ; ``Directory.*.props`` importés en chaîne."""
SCOPE_ORDER = (Scope.RUNTIME, Scope.OPTIONAL, Scope.BUILD, Scope.DEV)
"""Le scope d'une indirecte : le premier, dans cet ordre, des directes qui la tirent."""

_ITEMS = {
    "packagereference": "reference",
    "packageversion": "central",
    "globalpackagereference": "global",
}


# ---------------------------------------------------------------------------
# Un fichier MSBuild lu seul
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class Property:
    """Une propriété d'un ``<PropertyGroup>``."""

    name: str
    value: str
    file: str
    location: Location | None
    conditional: bool = False
    """Définie sous une condition (la sienne, celle de son groupe, ou un ``<Choose>``)."""
    default: bool = False
    """Sa condition est « si elle n'a pas de valeur » (``'$(X)' == ''``)."""


@dataclass(frozen=True, kw_only=True)
class Item:
    """Un ``PackageReference``, un ``PackageVersion`` ou un ``GlobalPackageReference``."""

    kind: str
    """``reference``, ``central`` ou ``global``."""
    name: str
    file: str
    version: str | None
    """``Version`` (attribut ou élément) ; ``None`` s'il n'y en a pas."""
    location: Location | None
    override: str | None = None
    """``VersionOverride`` (gestion centrale)."""
    override_location: Location | None = None
    private: bool = False
    """``PrivateAssets`` contient ``all`` : un outil de construction."""
    conditional: bool = False
    line: int = 0


@dataclass(frozen=True, kw_only=True)
class MsBuildFile:
    """Un fichier MSBuild (un projet, un ``.props``) lu seul."""

    path: str
    properties: tuple[Property, ...]
    items: tuple[Item, ...]
    imports: tuple[str, ...]
    """Les ``Project`` de ses ``<Import>``."""
    updates: tuple[str, ...] = ()
    """Les ``PackageReference Update="…"`` : pas lues."""


def read_msbuild(path: str, content: str) -> MsBuildFile:
    """Un fichier MSBuild lu seul. Lève ``ParseError`` s'il est invalide."""
    return _read_once(path, content)


@functools.lru_cache(maxsize=128)
def _read_once(path: str, content: str) -> MsBuildFile:
    """Lu une seule fois pour un même contenu. Le résultat est partagé : on ne le modifie pas."""
    root = parse(content)
    if root.tag.lower() != "project":
        raise ParseError("pas un fichier MSBuild : l'élément racine n'est pas <Project>.")
    found = _Found(path)
    found.walk(root, conditional=False)
    return MsBuildFile(
        path=path,
        properties=tuple(found.properties),
        items=tuple(found.items),
        imports=tuple(found.imports),
        updates=tuple(found.updates),
    )


def _condition(element: Element) -> str | None:
    return next((v for k, v in element.attributes.items() if k.lower() == "condition"), None)


def _attribute(element: Element, name: str) -> tuple[str | None, Location | None]:
    """L'attribut ``name`` (sans tenir compte de la casse : c'est une métadonnée MSBuild), sinon
    l'élément enfant de ce nom ; sa valeur et son emplacement."""
    for key, value in element.attributes.items():
        if key.lower() == name.lower():
            return value, element.attribute_locations.get(key)
    for child in element.children:
        if child.tag.lower() == name.lower() and not child.children:
            return child.text, child.location
    return None, None


@dataclass
class _Found:
    path: str
    properties: list[Property] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    updates: list[str] = field(default_factory=list)

    def walk(self, element: Element, *, conditional: bool) -> None:
        for child in element.children:
            tag = child.tag.lower()
            inner = conditional or _condition(child) is not None
            if tag == "propertygroup":
                for item in child.children:
                    self._property(item, inner)
            elif tag == "itemgroup":
                for item in child.children:
                    self._item(item, inner)
            elif tag == "choose":
                for branch in child.children:
                    if branch.tag.lower() in ("when", "otherwise"):
                        self.walk(branch, conditional=True)
            elif tag == "import":
                project, _ = _attribute(child, "Project")
                if project:
                    self.imports.append(project)

    def _property(self, element: Element, conditional: bool) -> None:
        condition = _condition(element)
        default = False
        if condition is not None and not conditional:
            match = _DEFAULT.fullmatch(condition)
            default = match is not None and match["name"].lower() == element.tag.lower()
        self.properties.append(
            Property(
                name=element.tag,
                value=element.text,
                file=self.path,
                location=None if element.children else element.location,
                conditional=(conditional or condition is not None) and not default,
                default=default,
            )
        )

    def _item(self, element: Element, conditional: bool) -> None:
        kind = _ITEMS.get(element.tag.lower())
        if kind is None:
            return
        include = element.attributes.get("Include")
        if include is None:
            update = element.attributes.get("Update")
            if update and kind == "reference":
                self.updates.append(update)
            return
        version, location = _attribute(element, "Version")
        override, override_location = _attribute(element, "VersionOverride")
        private, _ = _attribute(element, "PrivateAssets")
        for name in (part.strip() for part in include.split(";")):
            if not name:
                continue
            self.items.append(
                Item(
                    kind=kind,
                    name=name,
                    file=self.path,
                    version=version,
                    location=location,
                    override=override,
                    override_location=override_location,
                    private=kind == "global"
                    or "all" in (p.strip().lower() for p in (private or "").split(";")),
                    conditional=conditional or _condition(element) is not None,
                    line=element.line,
                )
            )


# ---------------------------------------------------------------------------
# Résoudre une version
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class _Resolved:
    value: str
    file: str
    location: Location | None
    reason: str | None = None


class Properties:
    """Les propriétés d'une évaluation, dans l'ordre où MSBuild les lit."""

    def __init__(self, properties: Iterable[Property]) -> None:
        self.by_name: dict[str, list[Property]] = {}
        for item in properties:
            self.by_name.setdefault(item.name.lower(), []).append(item)

    def get(self, name: str) -> Property | str | None:
        """La définition qui vaut ; la raison si on ne la connaît pas ; ``None`` si aucune."""
        current: Property | None = None
        uncertain = False
        for item in self.by_name.get(name.lower(), []):
            if item.default:
                if current is None and not uncertain:
                    current = item
            elif item.conditional:
                uncertain = True
            else:
                current, uncertain = item, False
        if uncertain:
            return f"propriété $({name}) définie sous condition (Condition=…)"
        return current

    def value(self, name: str) -> str | None:
        """La valeur résolue de ``name`` ; ``None`` si on ne la connaît pas."""
        resolved = self.resolve(f"$({name})", "", None)
        return None if resolved.reason is not None else resolved.value

    def resolve(self, text: str, file: str, location: Location | None, depth: int = 0) -> _Resolved:
        """``text`` avec ses ``$(…)`` remplacés, et l'emplacement de la valeur quand ``text``
        n'est qu'une propriété."""
        if _EXPRESSION.search(text):
            return _Resolved(value=text, file=file, location=None, reason=REASON_EXPRESSION)
        references = _REFERENCE.findall(text)
        if not references:
            return _Resolved(value=text, file=file, location=location)
        whole = _REFERENCE.fullmatch(text.strip())
        if whole is not None:
            name = whole.group(1).strip()
            found = self.get(name)
            if isinstance(found, str):
                return _Resolved(value=text, file=file, location=None, reason=found)
            if found is None or depth >= _MAX_DEPTH:
                reason = f"propriété $({name}) introuvable"
                return _Resolved(value=text, file=file, location=None, reason=reason)
            return self.resolve(found.value, found.file, found.location, depth + 1)
        value = text
        for name in dict.fromkeys(references):
            part = self.resolve(f"$({name})", file, None, depth + 1)
            if part.reason is not None:
                return _Resolved(value=text, file=file, location=None, reason=part.reason)
            value = value.replace(f"$({name})", part.value)
        return _Resolved(value=value, file=file, location=None)


# ---------------------------------------------------------------------------
# Un projet MSBuild évalué : le projet, et les Directory.*.props au-dessus
# ---------------------------------------------------------------------------


class _Loader:
    """Lit les fichiers MSBuild d'une source, une fois chacun, et note ce qui n'a pas pu l'être."""

    def __init__(self, read_text: ReadText, notices: list[Notice]) -> None:
        self.read_text = read_text
        self.notices = notices
        self.loaded: dict[str, MsBuildFile | None] = {}
        self.texts: dict[str, str | None] = {}

    def read(self, path: str) -> str | None:
        if path not in self.texts:
            try:
                self.texts[path] = self.read_text(path)
            except ValueError:
                self.texts[path] = None
        return self.texts[path]

    def load(self, path: str, *, required: bool = True) -> MsBuildFile | None:
        if path in self.loaded:
            return self.loaded[path]
        content = self.read(path)
        found = None
        if content is None:
            if required:
                self.notices.append(
                    Notice(file=path, message="introuvable, illisible ou trop gros : pas lu.")
                )
        else:
            try:
                found = read_msbuild(path, content)
            except ParseError as error:
                self.notices.append(Notice(file=path, message=str(error)))
        self.loaded[path] = found
        return found

    def chain(self, directory: str, name: str) -> list[MsBuildFile]:
        """Le ``name`` le plus proche (``directory`` ou au-dessus), puis ceux qu'il importe plus
        haut (``GetPathOfFileAbove``) : du plus haut au plus proche, l'ordre où MSBuild les lit."""
        found: list[MsBuildFile] = []
        start: str | None = directory
        while start is not None and len(found) < _MAX_DEPTH:
            path = next(
                (
                    candidate
                    for folder in [start, *_ancestors(start)]
                    if self.read(candidate := join(folder, name)) is not None
                ),
                None,
            )
            if path is None:
                break
            loaded = self.load(path)
            if loaded is None:
                break
            found.append(loaded)
            above = any(_ABOVE.search(i) and name.lower() in i.lower() for i in loaded.imports)
            folder = dirname(path)
            start = None if not above or folder == "." else dirname(folder)
        return list(reversed(found))


def _ancestors(directory: str) -> list[str]:
    """Les dossiers au-dessus de ``directory``, du plus proche à la racine ``.``."""
    if directory == ".":
        return []
    parts = directory.split("/")
    return ["/".join(parts[:i]) for i in range(len(parts) - 1, 0, -1)] + ["."]


class _Evaluation:
    """Un fichier MSBuild avec ce que MSBuild lit avant lui : ``Directory.Build.props``, puis
    ``Directory.Packages.props``."""

    def __init__(self, loader: _Loader, path: str, own: MsBuildFile) -> None:
        directory = dirname(path)
        before = [*loader.chain(directory, BUILD_PROPS), *loader.chain(directory, CENTRAL)]
        self.files = [f for f in before if f.path != path] + [own]
        self.own = own
        self.properties = Properties(p for f in self.files for p in f.properties)
        self.centrally = (self.properties.value("ManagePackageVersionsCentrally") or "").strip()
        self.centrally_managed = self.centrally.lower() == "true"
        self.central: dict[str, list[Item]] = {}
        for item in (i for f in self.files for i in f.items if i.kind == "central"):
            self.central.setdefault(item.name.lower(), []).append(item)
        self.references = [i for f in self.files for i in f.items if i.kind == "reference"]
        self.globals = [i for f in self.files for i in f.items if i.kind == "global"]
        test = (self.properties.value("IsTestProject") or "").strip().lower() == "true"
        self.tests = test or any(i.name.lower() == TEST_SDK for i in self.references)

    def scope(self, item: Item) -> Scope:
        if self.tests:
            return Scope.DEV
        return Scope.BUILD if item.private else Scope.RUNTIME

    def central_versions(self) -> dict[str, list[_Resolved]]:
        """Les versions centrales, résolues, par nom en minuscules (celles qu'on ne sait pas
        résoudre sont laissées)."""
        found: dict[str, list[_Resolved]] = {}
        for name, items in self.central.items():
            for item in items:
                if item.version is None:
                    continue
                resolved = self.properties.resolve(item.version, item.file, item.location)
                if resolved.reason is None:
                    found.setdefault(name, []).append(resolved)
        return found

    def dependencies(self) -> list[Dependency]:
        """Ses ``PackageReference`` (des ``Directory.Build.props`` compris), puis les
        ``GlobalPackageReference`` de la gestion centrale."""
        found = []
        for item in self.references:
            found.extend(self._reference(item))
        if self.centrally_managed:
            for item in self.globals:
                found.append(self.dependency(item, item.version, item.file, item.location))
        return found

    def _reference(self, item: Item) -> list[Dependency]:
        if self.centrally_managed and item.override is not None:
            return [self.dependency(item, item.override, item.file, item.override_location)]
        if self.centrally_managed and item.version is None:
            centrals = self.central.get(item.name.lower(), [])
            if not centrals:
                return [self._unverifiable(item, REASON_NO_CENTRAL)]
            return [self.dependency(item, c.version, c.file, c.location) for c in centrals]
        if item.version is None:
            return [self._unverifiable(item, REASON_NO_VERSION)]
        return [self.dependency(item, item.version, item.file, item.location)]

    def dependency(
        self, item: Item, version: str | None, file: str, location: Location | None
    ) -> Dependency:
        if version is None:
            return self._unverifiable(item, REASON_NO_VERSION)
        resolved = self.properties.resolve(version, file, location)
        if resolved.reason is not None:
            return self._unverifiable(item, resolved.reason, version)
        return Dependency(
            ecosystem=Ecosystem.NUGET,
            name=item.name,
            constraint=resolved.value,
            installed=_used(resolved.value),
            scope=self.scope(item),
            file=resolved.file,
            location=resolved.location,
        )

    def _unverifiable(self, item: Item, reason: str, constraint: str | None = None) -> Dependency:
        return Dependency(
            ecosystem=Ecosystem.NUGET,
            name=item.name,
            constraint=constraint or "",
            scope=self.scope(item),
            file=item.file,
            unverifiable_reason=reason,
        )


def _used(constraint: str) -> str | None:
    """La version que NuGet prend d'après ``constraint`` seule (``versions.nuget``)."""
    try:
        return NUGET.exact(constraint)
    except InvalidConstraint:
        return None


# ---------------------------------------------------------------------------
# packages.config
# ---------------------------------------------------------------------------


def parse_packages_config(path: str, content: str) -> list[Dependency]:
    """Les paquets d'un ``packages.config``. Lève ``ParseError`` s'il est invalide."""
    root = parse(content)
    if root.tag != "packages":
        raise ParseError("pas un packages.config : l'élément racine n'est pas <packages>.")
    found = []
    for element in root.findall("package"):
        name = (element.attributes.get("id") or "").strip()
        if not name:
            continue
        version = element.attributes.get("version") or ""
        development = (element.attributes.get("developmentDependency") or "").lower() == "true"
        found.append(
            Dependency(
                ecosystem=Ecosystem.NUGET,
                name=name,
                constraint=version,
                installed=_used(version) or (version.strip() or None),
                scope=Scope.DEV if development else Scope.RUNTIME,
                file=path,
                location=element.attribute_locations.get("version"),
                excluded=_outside(element.attributes.get("allowedVersions")),
            )
        )
    return found


def _outside(allowed: str | None) -> tuple[str, ...]:
    """Les plages hors de ``allowedVersions`` (``[3,4)`` : ``(,3.0.0)`` et ``[4.0.0,)``), que
    ``checks.base.is_excluded`` écarte. Une plage illisible n'écarte rien."""
    if not allowed or not allowed.strip():
        return ()
    try:
        parsed = NUGET.parse_constraint(allowed)
    except InvalidConstraint:
        return ()
    found = []
    if parsed.minimum is not None:
        closing = ")" if parsed.minimum_inclusive else "]"
        found.append(f"(,{parsed.minimum.normalized}{closing}")
    if parsed.maximum is not None:
        opening = "(" if parsed.maximum_inclusive else "["
        found.append(f"{opening}{parsed.maximum.normalized},)")
    return tuple(found)


# ---------------------------------------------------------------------------
# packages.lock.json
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class Locked:
    """Une entrée de ``packages.lock.json``, pour un framework cible."""

    target: str
    """``net8.0``, ``net8.0/win-x64``…"""
    name: str
    type: str
    """``Direct``, ``Transitive``, ``CentralTransitive`` ou ``Project``."""
    version: str
    package: LockedPackage


@dataclass(frozen=True, kw_only=True)
class NuGetLockfile:
    """Un ``packages.lock.json`` lu : le lockfile commun, et ses entrées par nom (en
    minuscules)."""

    lockfile: Lockfile
    entries: dict[str, list[Locked]]

    def versions(self, name: str, types: Sequence[str] = ("Direct",)) -> list[str]:
        """Les versions résolues de ``name`` (des entrées de ``types``), sans doublon."""
        found = (e.version for e in self.entries.get(name.lower(), []) if e.type in types)
        return list(dict.fromkeys(v for v in found if v))


def parse_packages_lock_json(path: str, content: str) -> NuGetLockfile:
    """Un ``packages.lock.json``. Lève ``ParseError`` s'il est invalide."""
    try:
        data = json.loads(content.removeprefix("﻿"))
    except json.JSONDecodeError as error:
        raise ParseError(f"JSON invalide (ligne {error.lineno}).") from error
    targets = data.get("dependencies") if isinstance(data, dict) else None
    if not isinstance(targets, dict):
        raise ParseError("pas un packages.lock.json : pas de « dependencies ».")
    names = {
        target: {name.lower() for name in packages}
        for target, packages in targets.items()
        if isinstance(packages, dict)
    }
    packages: list[LockedPackage] = []
    entries: dict[str, list[Locked]] = {}
    for target, listed in targets.items():
        if not isinstance(listed, dict):
            continue
        for name, entry in listed.items():
            if not isinstance(entry, dict):
                continue
            kind = str(entry.get("type") or "")
            version = entry.get("resolved") if isinstance(entry.get("resolved"), str) else ""
            requires = entry.get("dependencies")
            if not isinstance(requires, dict):
                requires = {}
            edges: tuple[Edge, ...] = tuple(
                (_node(_target_of(target, other, names), other), frozenset()) for other in requires
            )
            package = LockedPackage(
                name=name,
                version=version or "",
                dependencies=edges,
                local=kind == "Project",
                key=_node(target, name),
            )
            packages.append(package)
            entries.setdefault(name.lower(), []).append(
                Locked(target=target, name=name, type=kind, version=version or "", package=package)
            )
    lockfile = Lockfile(path=path, ecosystem=Ecosystem.NUGET, packages=tuple(packages), graph=True)
    return NuGetLockfile(lockfile=lockfile, entries=entries)


def locked_versions(path: str, content: str) -> Lockfile:
    """``packages.lock.json`` comme un lockfile commun (``parsers.parse_lockfile``)."""
    return parse_packages_lock_json(path, content).lockfile


def _node(target: str, name: str) -> str:
    return f"{target}|{name.lower()}"


def _target_of(target: str, name: str, names: dict[str, set[str]]) -> str:
    """Le framework où chercher ``name`` requis depuis ``target`` : le même, sinon (une section
    propre à une plateforme, ``net8.0/win-x64``) le framework seul."""
    if name.lower() in names.get(target, set()):
        return target
    return target.split("/", 1)[0]


# ---------------------------------------------------------------------------
# Un projet
# ---------------------------------------------------------------------------


def parse_project(project: Project, read_text: ReadText) -> None:
    """Lit les fichiers NuGet de ``project`` et remplit ses dépendances : celles des projets
    MSBuild, puis les versions centrales que n'utilisent pas les projets du dossier, puis
    ``packages.config``, puis les indirectes du lockfile ; et à ``project.notices`` ce qui n'a pas
    pu être lu."""
    _ProjectParser(project, read_text).run()


class _ProjectParser:
    def __init__(self, project: Project, read_text: ReadText) -> None:
        self.project = project
        self.notices: list[Notice] = []
        self.loader = _Loader(read_text, self.notices)
        self.manifests: dict[str, list[str]] = {}
        for path in project.manifests:
            self.manifests.setdefault(_pattern(path), []).append(path)
        self.lock_path = next((p for p in project.lockfiles if _pattern(p) == LOCKFILE), None)
        self.central: dict[str, list[_Resolved]] = {}
        """Les versions centrales des évaluations : celles des ``CentralTransitive``."""
        self.conditional: set[str] = set()
        """Les fichiers dont les références conditionnelles ont déjà leur remarque."""
        self.tests = False
        """Un projet de tests : ce que tirent ses projets référencés est de développement."""

    def run(self) -> None:
        directs: list[Dependency] = []
        config = self.manifests.get(PACKAGES_CONFIG, [])
        msbuild = [path for pattern in PROJECTS for path in self.manifests.get(pattern, [])]
        if config and msbuild:
            # Un projet à packages.config : NuGet ignore ses PackageReference.
            msbuild = []
        referenced: set[str] = set()
        for path in sorted(msbuild):
            evaluation = self._evaluate(path)
            if evaluation is None:
                continue
            self.tests = self.tests or evaluation.tests
            found = evaluation.dependencies()
            referenced |= {d.name.lower() for d in found}
            directs.extend(found)
        for path in self.manifests.get(CENTRAL, []):
            directs.extend(self._central(path, referenced, standalone=not msbuild))
        for path in config:
            directs.extend(self._packages_config(path))
        if self.lock_path is not None:
            lock = self._lockfile(self.lock_path)
            if lock is not None:
                directs = self._link(directs, lock)
        self.project.dependencies.extend(directs)
        self.project.notices.extend(self.notices)

    def _evaluate(self, path: str) -> _Evaluation | None:
        own = self.loader.load(path)
        if own is None:
            return None
        evaluation = _Evaluation(self.loader, path, own)
        for name, versions in evaluation.central_versions().items():
            self.central.setdefault(name, versions)
        self._conditions(evaluation)
        if own.updates:
            names = ", ".join(dict.fromkeys(own.updates))
            message = f"PackageReference Update=… pas lues ({names})."
            self.notices.append(Notice(file=path, message=message))
        return evaluation

    def _conditions(self, evaluation: _Evaluation) -> None:
        for file in evaluation.files:
            if file.path not in self.conditional and any(i.conditional for i in file.items):
                self.conditional.add(file.path)
                self.notices.append(
                    Notice(
                        file=file.path,
                        message=(
                            "conditions MSBuild (Condition=…) non évaluées : ses références "
                            "conditionnelles sont lues comme toujours présentes."
                        ),
                    )
                )

    def _central(self, path: str, referenced: set[str], *, standalone: bool) -> list[Dependency]:
        """Les versions centrales de ``Directory.Packages.props`` que n'utilisent pas les projets
        du même dossier, et ses ``GlobalPackageReference`` s'il n'y en a pas."""
        own = self.loader.load(path)
        if own is None:
            return []
        evaluation = _Evaluation(self.loader, path, own)
        self._conditions(evaluation)
        if not evaluation.centrally_managed:
            message = (
                "ManagePackageVersionsCentrally n'est pas à true : NuGet n'utilise pas ces "
                "versions centrales."
            )
            self.notices.append(Notice(file=path, message=message))
        found = []
        for item in own.items:
            unused = item.kind == "central" and item.name.lower() not in referenced
            if unused or (item.kind == "global" and standalone):
                found.append(evaluation.dependency(item, item.version, item.file, item.location))
        return found

    def _packages_config(self, path: str) -> list[Dependency]:
        content = self.loader.read(path)
        if content is None:
            message = "introuvable, illisible ou trop gros : pas lu."
            self.notices.append(Notice(file=path, message=message))
            return []
        try:
            return parse_packages_config(path, content)
        except ParseError as error:
            self.notices.append(Notice(file=path, message=str(error)))
            return []

    def _lockfile(self, path: str) -> NuGetLockfile | None:
        content = self.loader.read(path)
        if content is None:
            message = "introuvable, illisible ou trop gros : pas lu."
            self.notices.append(Notice(file=path, message=message))
            return None
        try:
            return parse_packages_lock_json(path, content)
        except ParseError as error:
            self.notices.append(Notice(file=path, message=str(error)))
            return None

    def _link(self, declared: list[Dependency], lock: NuGetLockfile) -> list[Dependency]:
        """Les directes avec leur version résolue, puis les indirectes du lockfile."""
        directs = []
        starts: list[Start] = []
        kept: set[tuple[str, str]] = set()
        for dependency in declared:
            entries = [
                e for e in lock.entries.get(dependency.name.lower(), []) if e.type != "Project"
            ]
            installed = _installed(dependency, [e.version for e in entries if e.type == "Direct"])
            if installed is None:
                directs.append(dependency)
                continue
            for entry in entries:
                starts.append((dependency.scope, (entry.package.node, frozenset())))
            kept.add((dependency.name.lower(), installed))
            directs.append(
                dataclasses.replace(dependency, installed=installed, lockfile=lock.lockfile.path)
            )
        # Ce que tirent les projets référencés (ProjectReference) : leurs dépendances.
        referenced = Scope.DEV if self.tests else Scope.RUNTIME
        for entries in lock.entries.values():
            starts += [
                (referenced, (e.package.node, frozenset())) for e in entries if e.package.local
            ]
        found = lockfile_transitives(
            lock.lockfile,
            starts,
            lambda package: (package.name.lower(), package.version) in kept,
            order=SCOPE_ORDER,
        )
        types = {(e.name.lower(), e.version): e.type for es in lock.entries.values() for e in es}
        found = [self._central_transitive(d, types) for d in found]
        found.sort(key=lambda d: (d.name.lower(), NUGET.sort_key(d.installed or "")))
        return directs + found

    def _central_transitive(
        self, dependency: Dependency, types: dict[tuple[str, str], str]
    ) -> Dependency:
        """Une indirecte ``CentralTransitive`` : sa version est celle de sa ``PackageVersion``,
        où elle se réécrit."""
        key = (dependency.name.lower(), dependency.installed or "")
        centrals = self.central.get(dependency.name.lower(), [])
        if types.get(key) != "CentralTransitive" or len(centrals) != 1:
            return dependency
        central = centrals[0]
        if central.location is None:
            return dependency
        return dataclasses.replace(
            dependency, constraint=central.value, file=central.file, location=central.location
        )


def _installed(dependency: Dependency, resolved: list[str]) -> str | None:
    """La version résolue d'une directe : la plus basse qui respecte sa contrainte, sinon la
    plus basse."""
    readable = []
    for version in resolved:
        try:
            NUGET.parse(version)
        except InvalidVersion:
            continue
        readable.append(version)
    if not readable:
        return None
    matching = []
    for version in readable:
        try:
            if NUGET.satisfies(dependency.constraint, version):
                matching.append(version)
        except (InvalidConstraint, InvalidVersion):
            continue
    return min(matching or readable, key=NUGET.sort_key)


def _pattern(path: str) -> str:
    match = match_dependency_file(path)
    return "" if match is None or match.ecosystem is not Ecosystem.NUGET else match.pattern
