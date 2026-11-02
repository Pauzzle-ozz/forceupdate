"""Les parseurs Rust : ``Cargo.toml``, ``Cargo.lock``, et le lien entre les deux.

Manifeste lu : ``Cargo.toml``, ses sections de dépendances :

- ``[dependencies]`` (``runtime``, ou ``optional`` avec ``optional = true``),
  ``[dev-dependencies]`` (``dev``) et ``[build-dependencies]`` (``build``), aussi écrites
  ``dev_dependencies`` et ``build_dependencies`` ;
- les mêmes pour une plateforme : ``[target.'cfg(windows)'.dependencies]``,
  ``[target.x86_64-pc-windows-msvc.dev-dependencies]``…

Une dépendance s'écrit ``serde = "1.0"``, ``serde = { version = "1.0", features = […] }``, ou
dans sa propre table ``[dependencies.serde]``. ``package = "…"`` la renomme : c'est le vrai nom
du crate qui est vérifié (``my-log = { package = "log", version = "0.4" }`` est ``log``).

**Workspace.** ``serde = { workspace = true }`` (ou ``serde.workspace = true``) reprend la
dépendance de ``[workspace.dependencies]`` du ``Cargo.toml`` à la racine du workspace, le plus
proche en remontant qui a une table ``[workspace]``. La contrainte telle qu'écrite est
``workspace = true`` ; celle de la racine va dans ``resolved_constraint``, comme un
``catalog:`` de pnpm, et c'est elle qu'une mise à jour réécrit. Un ``package``, ``git``,
``path`` ou ``registry`` de la racine vaut pour la dépendance. ``version.workspace = true``
dans ``[package]`` reprend ``[workspace.package] version``.

Le ``Cargo.lock`` d'un workspace est à sa racine : E02 le rattache au plus proche dossier
parent. Il n'est gardé que si le projet est membre : la racine elle-même, un dossier qui
correspond à ``[workspace] members`` (des motifs), ou un crate que le lockfile connaît comme
local (une dépendance ``path`` d'un membre en est un d'office). ``exclude`` l'emporte : ce sont
des préfixes de chemin, comme pour Cargo.

Une dépendance ``git`` ou ``path`` (même avec une ``version``, Cargo prend le chemin), ou d'un
autre registre (``registry = "…"``) est « non vérifiable », avec la raison. Le lockfile le dit
aussi : la source d'un paquet remplacé par ``[patch]`` est un dépôt git ou un chemin. Celle d'un
autre registre, l'aiguillage (``routing.cargo``, E34) sait la demander à ce registre.

Lockfile lu : ``Cargo.lock``, formats 1 à 4. Chaque ``[[package]]`` dit ce qu'il requiert
(``dependencies``, ``"nom"`` ou ``"nom version"`` quand plusieurs versions sont figées) : on
suit le graphe depuis le paquet du projet. Les dépendances de dev et de build y sont mêlées aux
autres ; le scope d'une transitive est celui des directes qui la tirent.

Repris de ``reference/argos_sca_parsers.py`` (L895-958), puis adapté : ``Dependency`` au lieu de
``SCAComponent``, contraintes gardées telles qu'écrites, emplacements, sections de plateforme,
dépendances renommées, git, chemins et autres registres, workspaces, lockfile relié au
manifeste par son graphe, et un fichier invalide signalé (``ParseError``) au lieu d'une liste
vide.
"""

import dataclasses
import functools
import logging
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from forceupdate.detect.manifests import match_dependency_file
from forceupdate.models import Dependency, Ecosystem, Location, Notice, Project, Scope
from forceupdate.parsers.base import REASON_GIT, REASON_LOCAL, ParseError, ReadText
from forceupdate.parsers.lockfiles import (
    SCOPE_ORDER,
    Edge,
    LockedPackage,
    Lockfile,
    Start,
    dirname,
    glob_match,
    join,
    relative_to,
    transitives,
)
from forceupdate.parsers.toml_spans import StringSpan, TomlPath, string_spans
from forceupdate.versions import InvalidConstraint, InvalidVersion
from forceupdate.versions.cargo import CARGO

logger = logging.getLogger(__name__)

MANIFEST = "Cargo.toml"
LOCKFILE = "Cargo.lock"

WORKSPACE_CONSTRAINT = "workspace = true"
"""La contrainte telle qu'écrite d'une dépendance reprise du workspace : sa plage est dans
``[workspace.dependencies]`` (``Dependency.resolved_constraint``)."""

CRATES_IO_SOURCES = frozenset(
    {"registry+https://github.com/rust-lang/crates.io-index", "sparse+https://index.crates.io/"}
)
"""La source de crates.io dans un ``Cargo.lock`` : Cargo écrit la première, même quand il lit
l'index « sparse »."""

REASON_OTHER_REGISTRY = "vient d'un autre registre que crates.io"
_NAMED_REGISTRY = re.compile(r"^vient du registre « (?P<name>[^»]+) », pas de crates\.io$")

SCOPES = (*SCOPE_ORDER, Scope.BUILD)
"""Le scope d'une transitive : le premier, dans cet ordre, des directes qui la tirent. Les
dépendances de build sont dans ``Cargo.lock`` (Cargo les résout et les fige), après celles de
l'exécution."""

_SECTIONS = (
    ("dependencies", Scope.RUNTIME),
    ("dev-dependencies", Scope.DEV),
    ("dev_dependencies", Scope.DEV),
    ("build-dependencies", Scope.BUILD),
    ("build_dependencies", Scope.BUILD),
)
"""Les sections de dépendances d'un manifeste (ou d'une plateforme), et leur scope. Les formes
à ``_`` sont anciennes, refusées par l'édition 2024, mais encore lues par Cargo avant."""


# ---------------------------------------------------------------------------
# Cargo.toml
# ---------------------------------------------------------------------------


def _load_toml(content: str) -> dict[str, Any]:
    try:
        return tomllib.loads(content)
    except tomllib.TOMLDecodeError as err:
        raise ParseError(f"TOML invalide ({err}).") from err


def _table(data: Any, *keys: str) -> dict[str, Any]:
    """La table ``data[k1][k2]…`` ; une table vide si elle n'existe pas ou n'en est pas une."""
    for key in keys:
        if not isinstance(data, dict):
            return {}
        data = data.get(key)
    return data if isinstance(data, dict) else {}


@dataclass(frozen=True, kw_only=True)
class _Spec:
    """Ce qu'une dépendance déclare, sous sa clé : vrai nom, contrainte, d'où elle vient."""

    name: str
    constraint: str
    location: Location | None
    reason: str | None
    workspace: bool = False
    """``workspace = true`` : le reste vient de ``[workspace.dependencies]``."""
    optional: bool = False


def _spec(
    key: str, value: Any, keys: TomlPath, spans: Mapping[TomlPath, StringSpan]
) -> _Spec | None:
    """Une dépendance telle qu'écrite sous ``keys`` (``("dependencies", "serde")``) ; ``None``
    si elle est illisible (ni chaîne, ni table)."""
    if isinstance(value, str):
        constraint, location = _constraint(value, spans.get(keys))
        return _Spec(name=key, constraint=constraint, location=location, reason=None)
    if not isinstance(value, dict):
        return None
    package = value.get("package")
    name = package if isinstance(package, str) and package else key
    optional = value.get("optional") is True
    if value.get("workspace") is True:
        return _Spec(
            name=key,
            constraint=WORKSPACE_CONSTRAINT,
            location=None,
            reason=None,
            workspace=True,
            optional=optional,
        )
    version = value.get("version")
    constraint, location = "", None
    if isinstance(version, str):
        constraint, location = _constraint(version, spans.get((*keys, "version")))
    return _Spec(
        name=name,
        constraint=constraint,
        location=location,
        reason=_reason(value),
        optional=optional,
    )


def _constraint(value: str, span: StringSpan | None) -> tuple[str, Location | None]:
    """La contrainte sans les espaces qui l'entourent, et son emplacement."""
    start = len(value) - len(value.lstrip())
    end = len(value.rstrip())
    return value[start:end], span.location(start, end) if span is not None else None


def _reason(table: Mapping[str, Any]) -> str | None:
    """Pourquoi une dépendance écrite en table n'est pas vérifiable : git, chemin, autre
    registre. La raison ne cite jamais l'adresse : elle peut contenir un token."""
    if "git" in table:
        return REASON_GIT
    if "path" in table:
        return REASON_LOCAL
    registry = table.get("registry")
    if isinstance(registry, str) and registry != "crates-io":
        return _registry_reason(registry)
    if "registry-index" in table:
        return REASON_OTHER_REGISTRY
    return None


def _registry_reason(registry: str) -> str:
    return f"vient du registre « {registry} », pas de crates.io"


def registry_of(reason: str | None) -> str | None:
    """Le nom du registre d'une dépendance ``registry = "…"``, d'après sa raison « non
    vérifiable » ; ``None`` sinon. L'aiguillage (``routing.cargo``, E34) la demande alors à ce
    registre."""
    match = _NAMED_REGISTRY.match(reason or "")
    return match.group("name") if match else None


@dataclass(frozen=True)
class _Declared:
    """Une dépendance directe lue dans un manifeste."""

    dependency: Dependency
    workspace: bool
    """``workspace = true`` : sa contrainte est à lire dans ``[workspace.dependencies]``."""
    key: str
    """Sa clé dans le manifeste : le nom qu'elle a dans ``[workspace.dependencies]``."""


@dataclass(frozen=True, kw_only=True)
class _CargoToml:
    """Un ``Cargo.toml`` lu."""

    declared: list[_Declared]
    notices: list[Notice]
    package: str | None
    """Le nom du crate (``[package] name``) ; ``None`` pour un manifeste virtuel (un
    workspace sans crate à lui)."""
    version: str | None
    """Sa version ; ``None`` si elle est reprise du workspace (``version.workspace = true``)."""
    workspace_key: str | None
    """``[package] workspace`` : le dossier de la racine du workspace, s'il est donné."""
    data: dict[str, Any]


def parse_cargo_toml(path: str, content: str) -> list[Dependency]:
    """Les dépendances d'un ``Cargo.toml``, dans l'ordre des sections : ``[dependencies]``,
    ``[dev-dependencies]``, ``[build-dependencies]``, puis celles des plateformes.

    Une dépendance ``workspace = true`` a pour contrainte ``workspace = true``, sans
    emplacement : sa plage est dans le ``Cargo.toml`` de la racine (``parse_project`` l'y lit).
    Lève ``ParseError`` si le TOML est invalide."""
    return [declared.dependency for declared in _parse_cargo_toml(path, content).declared]


def _parse_cargo_toml(path: str, content: str) -> _CargoToml:
    data = _load_toml(content)
    spans = string_spans(content)
    declared: list[_Declared] = []
    notices: list[Notice] = []

    def section(keys: TomlPath, values: Any, scope: Scope) -> None:
        if not isinstance(values, dict):
            return
        for key, value in values.items():
            spec = _spec(key, value, (*keys, key), spans)
            if spec is None:
                notices.append(Notice(file=path, message=f"« {key} » : dépendance illisible."))
                continue
            item_scope = Scope.OPTIONAL if spec.optional and scope is Scope.RUNTIME else scope
            dependency = Dependency(
                ecosystem=Ecosystem.CRATES_IO,
                name=spec.name,
                constraint=spec.constraint,
                scope=item_scope,
                file=path,
                location=spec.location,
                unverifiable_reason=spec.reason,
            )
            declared.append(_Declared(dependency, spec.workspace, key))

    for name, scope in _SECTIONS:
        section((name,), data.get(name), scope)
    for platform, tables in _table(data, "target").items():
        for name, scope in _SECTIONS:
            section(("target", platform, name), _table(tables).get(name), scope)

    package = _table(data, "package") or _table(data, "project")  # [project] : ancien nom
    name = package.get("name")
    version = package.get("version")
    workspace_key = package.get("workspace")
    if isinstance(version, dict) and version.get("workspace") is True:
        version = None
    elif not isinstance(version, str):
        version = "0.0.0"  # sans version, Cargo la met à 0.0.0
    return _CargoToml(
        declared=declared,
        notices=notices,
        package=name if isinstance(name, str) else None,
        version=version,
        workspace_key=workspace_key if isinstance(workspace_key, str) else None,
        data=data,
    )


@dataclass(frozen=True, kw_only=True)
class WorkspaceDependency:
    """Une entrée de ``[workspace.dependencies]``."""

    key: str
    """Sa clé : le nom sous lequel les membres la reprennent."""
    name: str
    """Le vrai nom du crate (``package = "…"``, sinon la clé)."""
    constraint: str
    """La contrainte telle qu'écrite ; vide sans ``version`` (git, chemin)."""
    location: Location | None
    reason: str | None = None
    """Pourquoi elle n'est pas vérifiable (git, chemin, autre registre)."""


@dataclass(frozen=True, kw_only=True)
class CargoWorkspace:
    """La table ``[workspace]`` d'un ``Cargo.toml`` lue."""

    path: str
    """Le ``Cargo.toml`` de la racine."""
    members: list[str]
    exclude: list[str]
    dependencies: list[WorkspaceDependency]
    package_version: str | None
    """``[workspace.package] version``, que reprennent les membres."""

    def entry(self, key: str) -> WorkspaceDependency | None:
        return next((entry for entry in self.dependencies if entry.key == key), None)

    def excludes(self, relative: str) -> bool:
        """Vrai si le dossier ``relative`` (relatif à la racine) est exclu : ``exclude`` donne
        des préfixes de chemin."""
        for excluded in self.exclude:
            prefix = excluded.replace("\\", "/").strip("/").removeprefix("./")
            if prefix and (relative == prefix or relative.startswith(f"{prefix}/")):
                return True
        return False

    def lists(self, relative: str) -> bool:
        """Vrai si le dossier ``relative`` est la racine, ou correspond à ``members``."""
        return relative == "." or any(glob_match(relative, member) for member in self.members)


def parse_workspace(path: str, content: str) -> CargoWorkspace | None:
    """La table ``[workspace]`` du ``Cargo.toml`` ``path`` ; ``None`` s'il n'en a pas. Lève
    ``ParseError`` si le TOML est invalide."""
    data = _load_toml(content)
    return _workspace(path, data, string_spans(content))


def _workspace(
    path: str, data: Mapping[str, Any], spans: Mapping[TomlPath, StringSpan]
) -> CargoWorkspace | None:
    if not isinstance(data.get("workspace"), dict):
        return None
    table = _table(data, "workspace")
    entries = []
    for key, value in _table(table, "dependencies").items():
        spec = _spec(key, value, ("workspace", "dependencies", key), spans)
        if spec is None or spec.workspace:
            continue
        entries.append(
            WorkspaceDependency(
                key=key,
                name=spec.name,
                constraint=spec.constraint,
                location=spec.location,
                reason=spec.reason,
            )
        )
    version = _table(table, "package").get("version")
    return CargoWorkspace(
        path=path,
        members=_strings(table.get("members")),
        exclude=_strings(table.get("exclude")),
        dependencies=entries,
        package_version=version if isinstance(version, str) else None,
    )


def _strings(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def read_workspace_root(directory: str, read_text: ReadText) -> tuple[str, str] | None:
    """Le ``Cargo.toml`` de la racine du workspace de ``directory`` : le plus proche, en
    remontant depuis ``directory`` compris, qui a une table ``[workspace]`` ; son chemin et
    son contenu. ``None`` s'il n'y en a pas. Un fichier illisible ou invalide est sauté."""
    for candidate in [directory, *_ancestors(directory)]:
        path = join(candidate, MANIFEST)
        try:
            content = read_text(path)
        except ValueError:
            content = None
        if content is None:
            continue
        try:
            data = tomllib.loads(content)
        except tomllib.TOMLDecodeError:
            continue
        if isinstance(data.get("workspace"), dict):
            return path, content
    return None


def _ancestors(directory: str) -> list[str]:
    """Les dossiers parents de ``directory``, du plus proche à la racine ``.``."""
    if directory == ".":
        return []
    parts = directory.split("/")
    return ["/".join(parts[:i]) for i in range(len(parts) - 1, 0, -1)] + ["."]


# ---------------------------------------------------------------------------
# Cargo.lock
# ---------------------------------------------------------------------------

_EDGE = re.compile(r"(?P<name>[^\s(]+)(?: (?P<version>[^\s(]+))?(?: \((?P<source>[^)]*)\))?")


@dataclass(frozen=True, kw_only=True)
class CargoLockfile:
    """Un ``Cargo.lock`` lu : ses paquets, et de quoi y retrouver ceux du workspace."""

    lockfile: Lockfile

    def local(self, name: str, version: str | None) -> LockedPackage | None:
        """Le crate local (un membre, ou une dépendance ``path``) ``name``, à ``version`` si
        elle est donnée."""
        found = [p for p in self.lockfile.packages if p.local and p.name == name]
        if version is not None:
            found = [p for p in found if p.version == version] or found
        return found[0] if found else None

    def package(self, node: str) -> LockedPackage | None:
        return self._by_node.get(node)

    def named(self, name: str) -> list[LockedPackage]:
        """Les paquets du registre ou d'un dépôt (pas les locaux) qui s'appellent ``name``."""
        return [p for p in self.lockfile.packages if p.name == name and not p.local]

    @functools.cached_property
    def _by_node(self) -> dict[str, LockedPackage]:
        return {package.node: package for package in self.lockfile.packages}


def parse_cargo_lock(path: str, content: str) -> CargoLockfile:
    """Un ``Cargo.lock`` (formats 1 à 4). Ses crates locaux sont ``local`` ; un paquet d'un
    dépôt git ou d'un autre registre est « non vérifiable ». Lève ``ParseError`` si le TOML est
    invalide."""
    return _parse_lock_once(path, content)


@functools.lru_cache(maxsize=4)
def _parse_lock_once(path: str, content: str) -> CargoLockfile:
    """Lu une seule fois pour un même contenu : celui d'un workspace est relu par chacun de ses
    membres. Le résultat est partagé : on ne le modifie pas."""
    data = _load_toml(content)
    entries = [
        entry
        for entry in [*_entries(data.get("package")), _table(data, "root")]
        if isinstance(entry.get("name"), str)
    ]
    keys: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for entry in entries:
        keys.setdefault((entry["name"], str(entry.get("version", ""))), []).append(entry)

    def node(entry: Mapping[str, Any]) -> str:
        name, version = entry["name"], str(entry.get("version", ""))
        source = entry.get("source")
        if len(keys[name, version]) > 1 and isinstance(source, str):
            return f"{name} {version} ({source})"
        return f"{name} {version}"

    by_name: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        by_name.setdefault(entry["name"], []).append(entry)

    def target(text: str) -> str | None:
        match = _EDGE.fullmatch(text.strip())
        if match is None:
            return None
        candidates = by_name.get(match["name"], [])
        if match["version"] is not None:
            candidates = [e for e in candidates if str(e.get("version", "")) == match["version"]]
        if match["source"] is not None:
            candidates = [e for e in candidates if e.get("source") == match["source"]] or candidates
        return node(candidates[0]) if candidates else None

    packages = []
    for entry in entries:
        source = entry.get("source")
        edges: list[Edge] = [
            (found, frozenset())
            for text in _strings(entry.get("dependencies"))
            if (found := target(text)) is not None
        ]
        packages.append(
            LockedPackage(
                name=entry["name"],
                version=str(entry.get("version", "")),
                dependencies=tuple(edges),
                local=not isinstance(source, str),
                unverifiable_reason=_source_reason(source),
                key=node(entry),
            )
        )
    lockfile = Lockfile(
        path=path,
        ecosystem=Ecosystem.CRATES_IO,
        packages=tuple(packages),
        graph=True,
        shared=True,
    )
    return CargoLockfile(lockfile=lockfile)


def _entries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, dict)]


def _source_reason(source: Any) -> str | None:
    """Pourquoi un paquet figé n'est pas vérifiable, d'après sa ``source`` ; ``None`` pour
    crates.io et pour un crate local (qui n'est pas une dépendance)."""
    if not isinstance(source, str) or source in CRATES_IO_SOURCES:
        return None
    if source.startswith("git+"):
        return REASON_GIT
    return REASON_OTHER_REGISTRY


# ---------------------------------------------------------------------------
# Un projet
# ---------------------------------------------------------------------------


def parse_project(project: Project, read_text: ReadText) -> None:
    """Lit les fichiers Rust de ``project`` et remplit ses dépendances.

    Ajoute à ``project.dependencies`` les directes (dans l'ordre du ``Cargo.toml``) puis les
    transitives, et à ``project.notices`` ce qui n'a pas pu être lu. Le ``Cargo.lock`` d'un
    workspace dont le projet n'est pas membre est retiré de ``project.lockfiles``.
    """
    _ProjectParser(project, read_text).run()


class _ProjectParser:
    """Lit les fichiers Rust d'un projet et relie le ``Cargo.toml`` au ``Cargo.lock``."""

    def __init__(self, project: Project, read_text: ReadText) -> None:
        self.project = project
        self.read_text = read_text
        self.notices: list[Notice] = []
        self.manifest_path = next((p for p in project.manifests if _is(p, MANIFEST)), None)
        self.lock_path = next((p for p in project.lockfiles if _is(p, LOCKFILE)), None)

    def run(self) -> None:
        manifest = self._manifest()
        root = self._workspace_root(manifest)
        lock = self._lockfile(manifest, root)
        declared = self._resolved(manifest, root) if manifest is not None else []
        directs: list[Dependency] = [item.dependency for item in declared]
        found: list[Dependency] = []
        if lock is not None and manifest is not None:
            directs, found = self._link(manifest, root, declared, lock)
        elif lock is not None and dirname(lock.lockfile.path) == self.project.path:
            # Pas de Cargo.toml lisible : tout le lockfile est transitif.
            lockfile = dataclasses.replace(lock.lockfile, shared=False)
            found = transitives(lockfile, [], lambda package: False)
        found.sort(key=lambda d: (d.file, d.name, CARGO.sort_key(d.installed or "")))
        self.project.dependencies.extend(directs + found)
        self.project.notices.extend(self.notices)

    # -- lecture ------------------------------------------------------------

    def _read(self, path: str) -> str | None:
        try:
            content = self.read_text(path)
        except ValueError:
            content = None
        if content is None:
            self.notices.append(
                Notice(file=path, message="introuvable, illisible ou trop gros : pas lu.")
            )
        return content

    def _manifest(self) -> _CargoToml | None:
        if self.manifest_path is None:
            return None
        content = self._read(self.manifest_path)
        if content is None:
            return None
        try:
            parsed = _parse_cargo_toml(self.manifest_path, content)
        except ParseError as err:
            self.notices.append(Notice(file=self.manifest_path, message=str(err)))
            return None
        self.notices.extend(parsed.notices)
        return parsed

    def _workspace_root(self, manifest: _CargoToml | None) -> CargoWorkspace | None:
        """La table ``[workspace]`` de la racine du workspace du projet : la sienne, celle du
        dossier que donne ``[package] workspace``, ou la plus proche en remontant. ``None``
        s'il n'y en a pas, ou s'il en est exclu."""
        if manifest is None:
            return None
        if manifest.workspace_key is not None:
            directory = _normalize(join(self.project.path, manifest.workspace_key))
            found = read_workspace_root(directory, self.read_text) if directory else None
        else:
            found = read_workspace_root(self.project.path, self.read_text)
        if found is None:
            return None
        path, content = found
        try:
            workspace = parse_workspace(path, content)
        except ParseError:
            return None  # la remarque vient avec le projet de la racine
        if workspace is None:
            return None
        if workspace.excludes(relative_to(self.project.path, dirname(path))):
            return None
        return workspace

    # -- lockfile -----------------------------------------------------------

    def _lockfile(
        self, manifest: _CargoToml | None, root: CargoWorkspace | None
    ) -> CargoLockfile | None:
        """Le ``Cargo.lock`` du projet : le sien, ou celui de la racine de son workspace s'il
        en est membre."""
        if self.lock_path is None:
            return None
        lock_dir = dirname(self.lock_path)
        lock = self._parse_lock(self.lock_path)
        if lock_dir == self.project.path:
            return lock
        member = (
            root is not None
            and dirname(root.path) == lock_dir
            and (
                root.lists(relative_to(self.project.path, lock_dir))
                or (
                    lock is not None
                    and manifest is not None
                    and manifest.package is not None
                    and lock.local(manifest.package, None) is not None
                )
            )
        )
        if not member:
            logger.debug("%s n'est pas membre du workspace de %s", self.project.path, lock_dir)
            self.project.lockfiles.remove(self.lock_path)
            self.notices = [n for n in self.notices if n.file != self.lock_path]
            return None
        return lock

    def _parse_lock(self, path: str) -> CargoLockfile | None:
        content = self._read(path)
        if content is None:
            return None
        try:
            return parse_cargo_lock(path, content)
        except ParseError as err:
            self.notices.append(Notice(file=path, message=str(err)))
            return None

    # -- workspace = true ---------------------------------------------------

    def _resolved(self, manifest: _CargoToml, root: CargoWorkspace | None) -> list[_Declared]:
        """Les directes, celles en ``workspace = true`` avec la plage de la racine
        (``resolved_constraint``) et ce qu'elle dit d'autre (vrai nom, git, chemin)."""
        resolved = []
        for item in manifest.declared:
            if not item.workspace:
                resolved.append(item)
                continue
            entry = root.entry(item.key) if root is not None else None
            if entry is None:
                where = root.path if root is not None else self.manifest_path or "."
                if root is None:
                    message = (
                        f"« {item.key} » : workspace = true, mais pas de workspace au-dessus : "
                        "contrainte inconnue."
                    )
                else:
                    message = (
                        f"« {item.key} » absent de [workspace.dependencies] : contrainte inconnue."
                    )
                self.notices.append(Notice(file=where, message=message))
                resolved.append(item)
                continue
            dependency = dataclasses.replace(
                item.dependency,
                name=entry.name,
                resolved_constraint=entry.constraint if entry.constraint else None,
                unverifiable_reason=entry.reason,
            )
            resolved.append(_Declared(dependency, True, item.key))
        return resolved

    # -- lien ---------------------------------------------------------------

    def _link(
        self,
        manifest: _CargoToml,
        root: CargoWorkspace | None,
        declared: Sequence[_Declared],
        lock: CargoLockfile,
    ) -> tuple[list[Dependency], list[Dependency]]:
        """Les directes avec leur version installée, et les transitives que le projet tire du
        lockfile, en suivant le graphe depuis les nœuds de ses directes."""
        own = None
        if manifest.package is not None:
            version = manifest.version
            if version is None and root is not None:
                version = root.package_version
            own = lock.local(manifest.package, version)
        directs = []
        starts: list[Start] = []
        direct_nodes: set[str] = set()
        for item in declared:
            dependency = item.dependency
            package = self._locked(dependency, own, lock)
            if package is not None:
                starts.append((dependency.scope, (package.node, frozenset())))
                direct_nodes.add(package.node)
                if dependency.unverifiable_reason is None and (
                    package.local or package.unverifiable_reason is not None
                ):
                    # Remplacée par [patch] (git, chemin), ou tirée d'un autre registre.
                    reason = package.unverifiable_reason or REASON_LOCAL
                    dependency = dataclasses.replace(dependency, unverifiable_reason=reason)
                if package.version and not package.local:
                    dependency = dataclasses.replace(
                        dependency, installed=package.version, lockfile=lock.lockfile.path
                    )
            directs.append(dependency)
        found = transitives(
            lock.lockfile, starts, lambda package: package.node in direct_nodes, order=SCOPES
        )
        return directs, found

    @staticmethod
    def _locked(
        dependency: Dependency, own: LockedPackage | None, lock: CargoLockfile
    ) -> LockedPackage | None:
        """Le paquet figé d'une directe : parmi ce que requiert le crate du projet, celui de ce
        nom (celui qui respecte la contrainte s'il y en a plusieurs) ; sans le crate du projet
        dans le lockfile, le plus haut de ce nom qui la respecte."""
        if own is not None:
            candidates = [
                package
                for node, _ in own.dependencies
                if (package := lock.package(node)) is not None and package.name == dependency.name
            ]
        else:
            candidates = lock.named(dependency.name)
        if len(candidates) <= 1:
            return candidates[0] if candidates else None
        fitting = [p for p in candidates if _satisfies(dependency, p.version)]
        return max(fitting or candidates, key=lambda p: CARGO.sort_key(p.version))


def _satisfies(dependency: Dependency, version: str) -> bool:
    try:
        return CARGO.satisfies(dependency.effective_constraint, version)
    except (InvalidConstraint, InvalidVersion):
        return False


def _is(path: str, pattern: str) -> bool:
    match = match_dependency_file(path)
    return match is not None and match.ecosystem is Ecosystem.CRATES_IO and match.pattern == pattern


def _normalize(path: str) -> str | None:
    """``path`` sans ``.`` ni ``..`` ; ``None`` s'il sort de la source."""
    parts: list[str] = []
    for part in path.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part)
    return "/".join(parts) or "."
