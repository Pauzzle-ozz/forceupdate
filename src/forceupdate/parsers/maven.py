"""Le parseur Maven : ``pom.xml``, lu par ``xml.parsers.expat`` (``parsers.xml_spans``).

**Ce qui est lu**, dans le projet et dans chacun de ses ``<profiles>`` :

- ``<dependencies>`` (scope ``runtime``, ``test`` → ``dev``, ``<optional>`` → ``optional``) ;
- ``<dependencyManagement>`` : les versions que le projet impose, et les BOM importés
  (``<type>pom</type><scope>import</scope>``), qui sont aussi des dépendances à mettre à jour ;
- ``<build>`` : ``<plugins>``, ``<pluginManagement>``, les dépendances d'un plugin, ``<extensions>``
  (scope ``build`` ; un plugin sans ``<groupId>`` est de ``org.apache.maven.plugins``) ;
- ``<parent>`` : un parent hors du dépôt (``spring-boot-starter-parent``) est une dépendance ; un
  parent du dépôt (``<relativePath>``, ``../pom.xml`` par défaut, dont le ``groupId:artifactId``
  correspond) donne ses propriétés et ses versions gérées.

Un nom Maven est ``groupId:artifactId`` (celui d'OSV). L'ordre des balises est libre.

**Où est la version.** Chaque version est située là où elle est écrite, pour être réécrite là :

- le texte de ``<version>`` ;
- ``${propriété}`` : la valeur de la propriété, dans les ``<properties>`` du ``pom.xml``, ou d'un
  parent du dépôt (celle de l'enfant l'emporte, comme dans Maven). ``Dependency.file`` est alors le
  fichier de la propriété. Plusieurs dépendances qui citent la même propriété ont le même
  emplacement : elles montent ensemble ;
- une dépendance sans ``<version>`` : celle de ``<dependencyManagement>`` (du même ``pom.xml``, ou
  d'un parent du dépôt). Dans le même fichier, c'est une seule déclaration, qui prend le scope de
  la dépendance.

**Non vérifiables**, avec la raison : un module du même build (son ``groupId:artifactId`` est
celui d'un ``pom.xml`` du dépôt, ou sa version est ``${project.version}``) ; ``<scope>system``
(un fichier local) ; une version gérée hors du dépôt (par le parent distant, ou par un BOM
importé) ; une propriété introuvable ; un plugin sans version (Maven en choisit une).

**La version utilisée** : Maven prend une version nue telle quelle (le plus proche l'emporte : une
dépendance directe gagne toujours) ; sans lockfile, c'est ``Dependency.installed``. Une version
écrite à partir de plusieurs propriétés (``${a}.${b}``) est lue, mais n'a pas d'emplacement : elle
est à réécrire à la main.

Repris de ``reference/argos_sca_parsers.py`` (L1028-1058), puis réécrit : ``xml.parsers.expat`` au
lieu de motifs (l'ordre ``groupId`` puis ``artifactId`` y était imposé), propriétés résolues (elles
étaient marquées « non épinglées »), parents du dépôt, ``dependencyManagement``, BOM, plugins,
scopes, emplacement de chaque version, et un fichier invalide signalé (``ParseError``).
"""

import functools
import posixpath
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from forceupdate.models import Dependency, Ecosystem, Location, Notice, Scope
from forceupdate.parsers.base import REASON_LOCAL, ParseError, ReadText
from forceupdate.parsers.xml_spans import Element, parse
from forceupdate.versions import InvalidConstraint
from forceupdate.versions.maven import MAVEN

MANIFEST = "pom.xml"
DEFAULT_PLUGIN_GROUP = "org.apache.maven.plugins"

REASON_MODULE = "module du même build Maven"
REASON_NO_VERSION = "aucune version écrite"
REASON_PLUGIN_DEFAULT = "aucune version écrite : Maven choisit celle du plugin"

_REFERENCE = re.compile(r"\$\{([^}]*)\}")
_PROJECT_VERSIONS = frozenset(
    {"project.version", "pom.version", "version", "project.parent.version", "parent.version"}
)
"""Les propriétés qui donnent la version du projet : une dépendance qui les cite est un module du
même build."""
_MAX_DEPTH = 10
"""Propriétés qui renvoient à d'autres propriétés, au plus ; parents du dépôt, au plus."""

_SCOPES = {"test": Scope.DEV}
_NO_SCOPE: Scope | None = None
"""Une dépendance gérée dans le même fichier, sans ``<scope>`` : celui de la gestion vaut."""


@dataclass(frozen=True, kw_only=True)
class Property:
    """Une propriété de ``<properties>``."""

    name: str
    value: str
    file: str
    location: Location | None


@dataclass(frozen=True, kw_only=True)
class Entry:
    """Un artefact déclaré dans un ``pom.xml``, avec sa version telle qu'écrite."""

    kind: str
    """``dependency``, ``managed`` (``dependencyManagement``), ``plugin``, ``managed-plugin``
    (``pluginManagement``), ``plugin-dependency``, ``extension`` ou ``parent``."""
    group: str
    artifact: str
    version: str | None
    """Le texte de ``<version>`` ; ``None`` sans ``<version>``."""
    location: Location | None
    scope: str | None = None
    type: str | None = None
    optional: bool = False
    profile: str | None = None
    """L'``id`` du profil (``<profiles>``) qui la déclare."""
    line: int = 0
    """La ligne de son élément : les déclarations sont rangées dans l'ordre du fichier."""

    @property
    def is_import(self) -> bool:
        """Un BOM importé : ``<type>pom</type><scope>import</scope>`` dans la gestion."""
        return self.kind == "managed" and self.scope == "import" and self.type == "pom"


@dataclass(frozen=True, kw_only=True)
class ParentRef:
    """``<parent>`` : l'artefact parent, et où chercher son ``pom.xml`` dans le dépôt."""

    group: str
    artifact: str
    version: str | None
    location: Location | None
    relative_path: str | None
    """``<relativePath>`` ; ``None`` sans la balise (``../pom.xml``), vide pour « hors du
    dépôt »."""


@dataclass(frozen=True, kw_only=True)
class Pom:
    """Un ``pom.xml`` lu seul, sans ses parents."""

    path: str
    group: str | None
    """Son ``groupId``, ou celui de son parent."""
    artifact: str | None
    version: str | None
    """Sa version, ou celle de son parent."""
    parent: ParentRef | None
    properties: dict[str, Property]
    profile_properties: dict[str, dict[str, Property]]
    modules: tuple[str, ...]
    entries: tuple[Entry, ...]

    @property
    def coordinates(self) -> str | None:
        return f"{self.group}:{self.artifact}" if self.group and self.artifact else None


def read_pom(path: str, content: str) -> Pom:
    """Un ``pom.xml`` lu seul. Lève ``ParseError`` s'il est invalide."""
    return _read_once(path, content)


@functools.lru_cache(maxsize=64)
def _read_once(path: str, content: str) -> Pom:
    """Lu une seule fois pour un même contenu. Le résultat est partagé : on ne le modifie pas."""
    root = parse(content)
    if root.tag != "project":
        raise ParseError("pas un pom.xml : l'élément racine n'est pas <project>.")
    parent_element = root.find("parent")
    parent = None
    if parent_element is not None:
        version = parent_element.find("version")
        parent = ParentRef(
            group=parent_element.child_text("groupId") or "",
            artifact=parent_element.child_text("artifactId") or "",
            version=None if version is None else version.text,
            location=None if version is None else version.location,
            relative_path=parent_element.child_text("relativePath"),
        )
    entries: list[Entry] = []
    modules: list[str] = []
    profile_properties: dict[str, dict[str, Property]] = {}
    for scope_element, profile in [(root, None)] + [
        (element, element.child_text("id") or "") for element in root.path("profiles", "profile")
    ]:
        entries.extend(_entries(scope_element, profile))
        modules.extend(m.text for m in scope_element.path("modules", "module") if m.text)
        if profile is not None:
            profile_properties[profile] = _properties(path, scope_element)
    if parent is not None and parent_element is not None:
        entries.append(
            Entry(
                kind="parent",
                group=parent.group,
                artifact=parent.artifact,
                version=parent.version,
                location=parent.location,
                line=parent_element.line,
            )
        )
    entries.sort(key=lambda entry: entry.line)
    return Pom(
        path=path,
        group=root.child_text("groupId") or (parent.group if parent else None),
        artifact=root.child_text("artifactId"),
        version=root.child_text("version") or (parent.version if parent else None),
        parent=parent,
        properties=_properties(path, root),
        profile_properties=profile_properties,
        modules=tuple(dict.fromkeys(modules)),
        entries=tuple(entries),
    )


def _properties(path: str, element: Element) -> dict[str, Property]:
    found = {}
    for block in element.findall("properties"):
        for item in block.children:
            found[item.tag] = Property(
                name=item.tag, value=item.text, file=path, location=item.location
            )
    return found


def _entries(element: Element, profile: str | None) -> list[Entry]:
    """Les artefacts de ``element`` (le projet, ou un profil)."""
    found = []
    sections = (
        ("dependency", ("dependencies", "dependency")),
        ("managed", ("dependencyManagement", "dependencies", "dependency")),
        ("plugin", ("build", "plugins", "plugin")),
        ("managed-plugin", ("build", "pluginManagement", "plugins", "plugin")),
        ("plugin", ("reporting", "plugins", "plugin")),
        ("extension", ("build", "extensions", "extension")),
    )
    for kind, tags in sections:
        for item in element.path(*tags):
            found.append(_entry(kind, item, profile))
            if kind in ("plugin", "managed-plugin"):
                for dependency in item.path("dependencies", "dependency"):
                    found.append(_entry("plugin-dependency", dependency, profile))
    return found


def _entry(kind: str, item: Element, profile: str | None) -> Entry:
    version = item.find("version")
    group = item.child_text("groupId")
    if not group and kind in ("plugin", "managed-plugin"):
        group = DEFAULT_PLUGIN_GROUP
    return Entry(
        kind=kind,
        group=group or "",
        artifact=item.child_text("artifactId") or "",
        version=None if version is None else version.text,
        location=None if version is None else version.location,
        scope=(item.child_text("scope") or "").lower() or None,
        type=(item.child_text("type") or "").lower() or None,
        optional=(item.child_text("optional") or "").lower() == "true",
        profile=profile,
        line=item.line,
    )


# ---------------------------------------------------------------------------
# Résoudre une version
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class _Resolved:
    """Une version résolue : sa valeur, le fichier et l'emplacement où elle est écrite, ou
    pourquoi elle n'est pas vérifiable."""

    value: str
    file: str
    location: Location | None
    reason: str | None = None


@dataclass(kw_only=True)
class _Context:
    """Ce qu'il faut pour résoudre les ``${…}`` d'un ``pom.xml`` : ses propriétés et celles de ses
    parents du dépôt (l'enfant l'emporte), le ``groupId:artifactId`` du projet, son parent
    distant."""

    properties: dict[str, Property]
    model: dict[str, str] = field(default_factory=dict)
    remote_parent: str | None = None

    def with_profile(self, extra: dict[str, Property]) -> "_Context":
        if not extra:
            return self
        return _Context(
            properties={**self.properties, **extra},
            model=self.model,
            remote_parent=self.remote_parent,
        )


def _resolve(text: str, file: str, location: Location | None, context: _Context) -> _Resolved:
    """``text`` (une version, un ``groupId``…) avec ses ``${…}`` remplacés."""
    return _resolve_at(text, file, location, context, 0)


def _resolve_at(
    text: str, file: str, location: Location | None, context: _Context, depth: int
) -> _Resolved:
    references = _REFERENCE.findall(text)
    if not references:
        return _Resolved(value=text, file=file, location=location)
    whole = _REFERENCE.fullmatch(text)
    if whole is not None:
        name = whole.group(1)
        if name in _PROJECT_VERSIONS:
            return _Resolved(value=text, file=file, location=None, reason=REASON_MODULE)
        if name in context.model:
            return _Resolved(value=context.model[name], file=file, location=None)
        found = context.properties.get(name)
        if found is None or depth >= _MAX_DEPTH:
            return _Resolved(value=text, file=file, location=None, reason=_missing(name, context))
        return _resolve_at(found.value, found.file, found.location, context, depth + 1)
    value = text
    for name in dict.fromkeys(references):
        part = _resolve_at(f"${{{name}}}", file, None, context, depth + 1)
        if part.reason is not None:
            return _Resolved(value=text, file=file, location=None, reason=part.reason)
        value = value.replace(f"${{{name}}}", part.value)
    return _Resolved(value=value, file=file, location=None)


def _missing(name: str, context: _Context) -> str:
    if context.remote_parent is not None:
        return f"propriété ${{{name}}} définie hors du dépôt (parent {context.remote_parent} ?)"
    return f"propriété ${{{name}}} introuvable"


# ---------------------------------------------------------------------------
# Un pom.xml seul
# ---------------------------------------------------------------------------


def parse_pom_xml(path: str, content: str) -> list[Dependency]:
    """Les dépendances d'un ``pom.xml`` lu seul : ses propriétés résolues, sans ses parents (une
    version gérée par un parent est « non vérifiable »). Lève ``ParseError`` s'il est invalide."""
    pom = read_pom(path, content)
    return _Resolver(pom, [], _context(pom, []), frozenset()).dependencies()


def _context(pom: Pom, parents: list[Pom], remote_parent: str | None = None) -> _Context:
    """Les propriétés de ``pom`` et de ses parents du dépôt (du plus proche au plus loin)."""
    properties: dict[str, Property] = {}
    for ancestor in reversed([pom, *parents]):
        properties.update(ancestor.properties)
    model = {}
    for key in ("groupId", "artifactId"):
        value = pom.group if key == "groupId" else pom.artifact
        if value:
            model[f"project.{key}"] = value
            model[f"pom.{key}"] = value
    if pom.parent is not None:
        model["project.parent.groupId"] = pom.parent.group
        model["project.parent.artifactId"] = pom.parent.artifact
    if remote_parent is None and pom.parent is not None and not parents:
        remote_parent = f"{pom.parent.group}:{pom.parent.artifact}"
    return _Context(properties=properties, model=model, remote_parent=remote_parent)


class _Resolver:
    """Les dépendances d'un ``pom.xml``, d'après lui et ses parents du dépôt."""

    def __init__(
        self, pom: Pom, parents: list[Pom], context: _Context, modules: frozenset[str]
    ) -> None:
        self.pom = pom
        self.parents = parents
        self.context = context
        self.modules = modules
        """Les ``groupId:artifactId`` des modules du même build."""

    def dependencies(self) -> list[Dependency]:
        found: list[Dependency] = []
        usages = self._usage_scopes()
        seen: set[tuple[str, str, Location | None]] = set()
        for entry in self.pom.entries:
            if entry.kind == "parent" and self.parents:
                continue  # le parent est dans le dépôt : c'est un module, pas une dépendance
            dependency = self._dependency(entry, usages)
            if dependency is None:
                continue
            key = (dependency.name, dependency.file, dependency.location)
            if dependency.location is not None and key in seen:
                continue
            seen.add(key)
            found.append(dependency)
        return found

    def _usage_scopes(self) -> dict[tuple[str, str], Scope | None]:
        """Le scope des dépendances sans version que gère ce même ``pom.xml`` : elles ne font
        qu'une déclaration avec leur version gérée, qui le prend."""
        managed = {
            (e.group, e.artifact) for e in self.pom.entries if e.kind == "managed" and e.version
        }
        found: dict[tuple[str, str], Scope | None] = {}
        for entry in self.pom.entries:
            key = (entry.group, entry.artifact)
            if entry.kind == "dependency" and not entry.version and key in managed:
                # Sans <scope>, c'est celui de la gestion qui vaut (comme dans Maven).
                written = entry.scope is not None or entry.optional
                found.setdefault(key, _scope(entry) if written else _NO_SCOPE)
        return found

    def _dependency(
        self, entry: Entry, usages: dict[tuple[str, str], Scope | None]
    ) -> Dependency | None:
        if not entry.group or not entry.artifact:
            return None
        key = (entry.group, entry.artifact)
        context = self.context
        if entry.profile is not None:
            context = context.with_profile(self.pom.profile_properties.get(entry.profile, {}))
        group = _resolve(entry.group, self.pom.path, None, context)
        artifact = _resolve(entry.artifact, self.pom.path, None, context)
        name = f"{group.value}:{artifact.value}"
        scope = _scope(entry)
        if entry.kind == "managed" and not entry.is_import:
            scope = usages.get(key) or scope
        if entry.version is None:
            if entry.kind == "managed":
                return None  # une gestion sans version ne gère rien
            if entry.kind == "dependency" and key in usages:
                return None  # une seule déclaration : celle de dependencyManagement
            resolved, managed = self._managed(entry, context)
            if managed is not None and entry.scope is None and not entry.optional:
                scope = _scope(managed)
        else:
            resolved = _resolve(entry.version, self.pom.path, entry.location, context)
        reason = group.reason or artifact.reason
        if reason is None and name in self.modules and entry.kind != "parent":
            reason = REASON_MODULE
        if reason is None and entry.scope == "system":
            reason = REASON_LOCAL
        reason = reason or resolved.reason
        if reason is not None:
            return Dependency(
                ecosystem=Ecosystem.MAVEN,
                name=name,
                constraint=entry.version or "",
                scope=scope,
                file=self.pom.path,
                unverifiable_reason=reason,
            )
        try:
            installed = MAVEN.exact(resolved.value)
        except InvalidConstraint:
            installed = None
        return Dependency(
            ecosystem=Ecosystem.MAVEN,
            name=name,
            constraint=resolved.value,
            installed=installed,
            scope=scope,
            file=resolved.file,
            location=resolved.location,
        )

    def _managed(self, entry: Entry, context: _Context) -> tuple[_Resolved, Entry | None]:
        """La version d'un artefact sans ``<version>`` : celle qu'un ``pom.xml`` du dépôt gère (et
        cette gestion), ou pourquoi on ne la connaît pas."""
        kinds = ("managed-plugin",) if entry.kind == "plugin" else ("managed",)
        imports = []
        for pom in [self.pom, *self.parents]:
            for managed in pom.entries:
                if managed.kind not in kinds:
                    continue
                if managed.is_import:
                    imports.append(f"{managed.group}:{managed.artifact}")
                    continue
                same = (managed.group, managed.artifact) == (entry.group, entry.artifact)
                if same and managed.version:
                    resolved = _resolve(managed.version, pom.path, managed.location, context)
                    return resolved, managed
        if imports:
            reason = f"version gérée par un BOM importé ({', '.join(dict.fromkeys(imports))})"
        elif context.remote_parent is not None:
            reason = f"version gérée par le parent {context.remote_parent} (hors du dépôt)"
        else:
            reason = REASON_PLUGIN_DEFAULT if entry.kind == "plugin" else REASON_NO_VERSION
        return _Resolved(value="", file=self.pom.path, location=None, reason=reason), None


def _scope(entry: Entry) -> Scope:
    if entry.kind in ("plugin", "managed-plugin", "plugin-dependency", "extension"):
        return Scope.BUILD
    if entry.scope in _SCOPES:
        return _SCOPES[entry.scope]
    return Scope.OPTIONAL if entry.optional else Scope.RUNTIME


# ---------------------------------------------------------------------------
# Un projet : le pom.xml et ses parents du dépôt
# ---------------------------------------------------------------------------


def parse_pom_project(
    manifest: str, read_text: ReadText, notices: list[Notice]
) -> list[Dependency]:
    """Les dépendances du ``pom.xml`` ``manifest``, avec ses parents du dépôt et les modules de
    son build ; ajoute à ``notices`` ce qui n'a pas pu être lu."""
    pom = _load(manifest, read_text, notices)
    if pom is None:
        return []
    parents, remote = _parents(pom, read_text, notices)
    modules = _modules([pom, *parents], read_text)
    context = _context(pom, parents, remote)
    return _Resolver(pom, parents, context, modules).dependencies()


def _load(path: str, read_text: ReadText, notices: list[Notice] | None) -> Pom | None:
    try:
        content = read_text(path)
    except ValueError:
        content = None
    if content is None:
        if notices is not None:
            notices.append(
                Notice(file=path, message="introuvable, illisible ou trop gros : pas lu.")
            )
        return None
    try:
        return read_pom(path, content)
    except ParseError as error:
        if notices is not None:
            notices.append(Notice(file=path, message=str(error)))
        return None


def _parents(pom: Pom, read_text: ReadText, notices: list[Notice]) -> tuple[list[Pom], str | None]:
    """Les parents du dépôt, du plus proche au plus loin, et le ``groupId:artifactId`` du premier
    parent hors du dépôt (``None`` s'il n'y en a pas)."""
    found: list[Pom] = []
    current = pom
    seen = {pom.path}
    while current.parent is not None and len(found) < _MAX_DEPTH:
        reference = current.parent
        wanted = f"{reference.group}:{reference.artifact}"
        path = _parent_path(current.path, reference.relative_path)
        if path is None or path in seen:
            return found, wanted
        parent = _load(path, read_text, None)
        if parent is None or parent.coordinates != wanted:
            if parent is not None and reference.relative_path:
                notices.append(
                    Notice(
                        file=current.path,
                        message=(
                            f"<relativePath> mène à {path}, qui n'est pas le parent {wanted} : "
                            "parent cherché hors du dépôt."
                        ),
                    )
                )
            return found, wanted
        found.append(parent)
        seen.add(path)
        current = parent
    return found, None


def _parent_path(pom_path: str, relative_path: str | None) -> str | None:
    """Le ``pom.xml`` du parent dans le dépôt ; ``None`` pour un ``<relativePath/>`` vide, ou un
    chemin qui sort du dépôt."""
    if relative_path is not None and not relative_path.strip():
        return None
    return _in_repo(posixpath.dirname(pom_path), relative_path or "../pom.xml")


def _in_repo(folder: str, relative: str) -> str | None:
    """Le ``pom.xml`` que désigne ``relative`` (un fichier, ou son dossier) depuis ``folder`` ;
    ``None`` s'il sort du dépôt."""
    path = posixpath.normpath(posixpath.join(folder, relative.strip().replace("\\", "/")))
    if not path.endswith(".xml"):
        path = posixpath.join(path, MANIFEST)
    if path == ".." or path.startswith(("../", "/")):
        return None
    return path


def _modules(poms: Iterable[Pom], read_text: ReadText, limit: int = 500) -> frozenset[str]:
    """Les ``groupId:artifactId`` du build : ``poms`` et leurs ``<modules>``, de proche en
    proche."""
    found: set[str] = set()
    pending = list(poms)
    seen = {pom.path for pom in pending}
    while pending and len(seen) <= limit:
        pom = pending.pop()
        if pom.coordinates:
            found.add(pom.coordinates)
        for module in pom.modules:
            path = _in_repo(posixpath.dirname(pom.path), module)
            if path is None or path in seen:
                continue
            seen.add(path)
            child = _load(path, read_text, None)
            if child is not None:
                pending.append(child)
    return frozenset(found)
