"""Le lien entre manifestes et lockfiles, commun à tous les écosystèmes.

Un manifeste donne les dépendances directes (``Declared``), un lockfile les paquets
figés (``LockedPackage``). Ce module relie les deux : la version installée de
chaque directe, et les transitives (``direct=False``), avec leur scope tiré du
graphe du lockfile quand il en a un. Il dit aussi quels dossiers sont membres d'un
workspace (``in_workspace``), dont le lockfile est à la racine.

Écrit pour Python (E03), sorti de ``parsers/python.py`` à E04 pour servir aussi à
npm, puis aux écosystèmes de la phase F. La façon de trouver la version installée
d'une directe reste propre à chaque écosystème : la plus haute selon PEP 440 pour
Python, la résolution de ``node_modules`` pour npm.
"""

import posixpath
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from fnmatch import fnmatchcase

from forceupdate.models import Dependency, Ecosystem, Location, Requirement, Scope

Edge = tuple[str, frozenset[str]]
"""Ce qu'un paquet requiert : l'autre paquet (son ``LockedPackage.node``), et ses extras
(Python)."""


@dataclass(frozen=True)
class Declared:
    """Une dépendance directe, avec les extras demandés : ils comptent pour suivre le lockfile."""

    dependency: Dependency
    extras: frozenset[str] = frozenset()


@dataclass(frozen=True, kw_only=True)
class LockedPackage:
    """Un paquet figé dans un lockfile."""

    name: str
    version: str = ""
    dependencies: tuple[Edge, ...] = ()
    """Ce qu'il requiert, si le lockfile le dit (``uv.lock``, ``package-lock.json``…)."""
    extras: Mapping[str, tuple[Edge, ...]] = field(default_factory=dict)
    """Ce que requiert chacun de ses extras."""
    scope: Scope | None = None
    """Ce que le lockfile dit de son scope (``category``, ``dev: true``, section ``develop``)."""
    local: bool = False
    """Le projet lui-même, un membre du workspace ou un lien local : pas une dépendance."""
    unverifiable_reason: str | None = None
    constraint: str = ""
    """La contrainte telle qu'écrite, pour un ``.txt`` compilé (``==2.0.1``)."""
    location: Location | None = None
    key: str = ""
    """Son identifiant dans le graphe, quand un même nom peut y être en plusieurs versions
    (npm : ``node_modules/a/node_modules/x``, descripteur Yarn, clé pnpm). Vide : le nom."""
    requires: Mapping[str, str] = field(default_factory=dict)
    """La plage qu'il demande de chaque paquet qu'il requiert, par nom, si le lockfile la dit
    (``package-lock.json`` : ``{"minimatch": "^10.2.1"}`` ; ``yarn.lock``, ``poetry.lock``) ;
    elle va dans ``Dependency.required_by``."""
    peers: Mapping[str, str] = field(default_factory=dict)
    """npm : la plage de chacune de ses dépendances pair (``peerDependencies``), si le lockfile
    la dit (``package-lock.json``, Yarn 2+, ``pnpm-lock.yaml``)."""

    @property
    def node(self) -> str:
        """Ce qui le désigne dans le graphe : sa clé, sinon son nom."""
        return self.key or self.name


@dataclass(frozen=True, kw_only=True)
class Lockfile:
    """Un lockfile lu."""

    path: str
    ecosystem: Ecosystem
    packages: tuple[LockedPackage, ...]
    graph: bool = False
    """Vrai si les paquets disent ce qu'ils requièrent : on peut suivre le graphe."""
    shared: bool = False
    """Vrai s'il contient les paquets d'autres projets (workspace) : seuls ceux que
    tirent les dépendances du projet sont à lui."""
    ranges: bool = True
    """Faux si le lockfile ne dit jamais la plage qu'un paquet demande de ceux qu'il requiert
    (``uv.lock``, ``pnpm-lock.yaml`` : seulement leurs noms, ou leurs versions) : chaque lien
    donne alors un ``Requirement`` sans plage, à lire au registre (E37)."""


SCOPE_ORDER = (Scope.RUNTIME, Scope.PEER, Scope.OPTIONAL, Scope.DEV)
"""Le scope d'une transitive est le premier, dans cet ordre, des directes qui la tirent.
Les dépendances de build ne sont pas dans les lockfiles Python et npm ; Cargo les fige
(``parsers.rust.SCOPES``)."""


def with_installed(
    declared: Iterable[Declared], installed: Callable[[Declared], tuple[str, str] | None]
) -> list[Dependency]:
    """Les dépendances directes, avec la version installée et le lockfile que leur donne
    ``installed`` (``(version, chemin du lockfile)``).

    Une dépendance de build n'en reçoit jamais : elle n'est pas installée avec le
    projet, et les lockfiles ne la figent pas.
    """
    result = []
    for item in declared:
        dependency = item.dependency
        if dependency.scope is not Scope.BUILD:
            found = installed(item)
            if found is not None:
                version, lockfile = found
                dependency = replace(dependency, installed=version, lockfile=lockfile)
        result.append(dependency)
    return result


Start = tuple[Scope, Edge]
"""Un point de départ dans le graphe d'un lockfile : une directe, avec son scope."""


def graph_starts(declared: Iterable[Declared]) -> list[Start]:
    """Les directes comme points de départ du graphe : par nom, avec leurs extras."""
    return [(d.dependency.scope, (d.dependency.name, d.extras)) for d in declared]


def transitives(
    lock: Lockfile,
    starts: Sequence[Start],
    is_direct: Callable[[LockedPackage], bool],
    *,
    order: Sequence[Scope] = SCOPE_ORDER,
) -> list[Dependency]:
    """Les paquets du lockfile qui ne sont pas des directes (selon ``is_direct``).

    Avec un graphe, le scope de chacun est celui des directes (``starts``) qui le
    tirent, le premier dans ``order`` ; pour un lockfile partagé (workspace), seuls
    comptent les paquets qu'elles tirent. Un même paquet à la même version n'est rendu
    qu'une fois.
    """
    scopes = reachable_scopes(starts, lock, order=order) if lock.graph else {}
    required = required_by(lock)
    result = []
    seen: set[tuple[str, str]] = set()
    for package in lock.packages:
        if package.local or is_direct(package):
            continue
        if lock.shared and package.node not in scopes:
            continue
        if (package.name, package.version) in seen:
            continue
        seen.add((package.name, package.version))
        result.append(
            Dependency(
                ecosystem=lock.ecosystem,
                name=package.name,
                constraint=package.constraint,
                installed=package.version or None,
                lockfile=lock.path,
                direct=False,
                scope=scopes.get(package.node) or package.scope or Scope.RUNTIME,
                file=lock.path,
                location=package.location,
                unverifiable_reason=package.unverifiable_reason,
                required_by=tuple(required.get((package.name, package.version), ())),
            )
        )
    return result


def required_by(lock: Lockfile) -> dict[tuple[str, str], list[Requirement]]:
    """Pour chaque paquet du lockfile (nom, version), ceux qui le requièrent et la plage que
    chacun demande, toutes ses copies confondues (``Dependency.required_by``) : par les liens du
    graphe, avec ``LockedPackage.requires`` ou ``peers`` ; sans plage si le lockfile n'en dit
    jamais (``Lockfile.ranges``). Une dépendance pair que le lockfile ne relie pas (Yarn 2+,
    pnpm) va à toutes les copies du paquet de ce nom. Pas le projet lui-même ni un membre du
    workspace (``local``) : leurs plages sont les contraintes de leurs manifestes. Vide sans
    graphe."""
    if not lock.graph:
        return {}
    by_node = {package.node: package for package in lock.packages}
    by_name: dict[str, list[LockedPackage]] = defaultdict(list)
    for package in lock.packages:
        if not package.local:
            by_name[package.name].append(package)
    found: dict[tuple[str, str], list[Requirement]] = defaultdict(list)

    def add(child: LockedPackage, requirement: Requirement) -> None:
        if requirement not in found[(child.name, child.version)]:
            found[(child.name, child.version)].append(requirement)

    for parent in lock.packages:
        if parent.local:
            continue
        linked = set()
        for node, _ in parent.dependencies:
            child = by_node.get(node)
            if child is None or child.local:
                continue
            linked.add(child.name)
            if child.name in parent.requires:
                wanted, peer = parent.requires[child.name], False
            elif child.name in parent.peers:
                wanted, peer = parent.peers[child.name], True
            elif not lock.ranges:
                wanted, peer = "", False
            else:
                continue
            add(
                child,
                Requirement(name=parent.name, version=parent.version, range=wanted, peer=peer),
            )
        for name, wanted in parent.peers.items():
            if name in linked:
                continue
            for child in by_name.get(name, ()):
                add(
                    child,
                    Requirement(name=parent.name, version=parent.version, range=wanted, peer=True),
                )
    return found


def with_required_by(
    dependencies: Iterable[Dependency], required: Mapping[tuple[str, str], Sequence[Requirement]]
) -> list[Dependency]:
    """``dependencies`` (des directes), chacune avec les paquets du lockfile qui requièrent sa
    version installée (``required``, de ``required_by``)."""
    result = []
    for dependency in dependencies:
        found = required.get((dependency.name, dependency.installed or ""))
        if found and dependency.installed:
            dependency = replace(dependency, required_by=tuple(found))
        result.append(dependency)
    return result


def reachable_scopes(
    starts: Sequence[Start], lock: Lockfile, *, order: Sequence[Scope] = SCOPE_ORDER
) -> dict[str, Scope]:
    """Pour chaque nœud que tirent les directes, son scope : le premier dans ``order`` (voir
    ``SCOPE_ORDER``)."""
    by_node: dict[str, list[LockedPackage]] = defaultdict(list)
    for package in lock.packages:
        by_node[package.node].append(package)
    scopes: dict[str, Scope] = {}
    for scope in order:
        for node in reach([edge for s, edge in starts if s is scope], by_node):
            scopes.setdefault(node, scope)
    return scopes


def dependents(lock: Lockfile, name: str, version: str) -> list[LockedPackage]:
    """Les paquets du lockfile qui requièrent ``name`` à la version ``version`` : ce qui le
    retient à cette version. Vide si le lockfile n'a pas de graphe."""
    nodes = {p.node for p in lock.packages if p.name == name and p.version == version}
    if not nodes:
        return []
    return [
        package
        for package in lock.packages
        if package.node not in nodes and any(node in nodes for node, _ in _all_edges(package))
    ]


def _all_edges(package: LockedPackage) -> Iterable[Edge]:
    yield from package.dependencies
    for edges in package.extras.values():
        yield from edges


def reach(starts: Iterable[Edge], by_node: Mapping[str, list[LockedPackage]]) -> set[str]:
    """Les nœuds tirés, de proche en proche, depuis ``starts``.

    Un paquet demandé avec des extras tire aussi ce qu'ils requièrent. Le graphe
    peut avoir des cycles : chaque (nœud, extra) n'est suivi qu'une fois. Quand les
    nœuds sont des noms (Python), les versions d'un même nom sont confondues.
    """
    reached: set[str] = set()
    followed: set[tuple[str, str | None]] = set()
    stack = list(starts)
    while stack:
        node, extras = stack.pop()
        todo = [item for item in (None, *extras) if (node, item) not in followed]
        if not todo:
            continue
        followed.update((node, item) for item in todo)
        reached.add(node)
        for package in by_node.get(node, ()):
            for item in todo:
                stack.extend(package.dependencies if item is None else package.extras.get(item, ()))
    return reached


# ---------------------------------------------------------------------------
# Workspaces et chemins
# ---------------------------------------------------------------------------


def in_workspace(path: str, members: Iterable[str], exclude: Iterable[str] = ()) -> bool:
    """Vrai si le dossier ``path`` (relatif à la racine du workspace) est membre :
    il correspond à un motif de ``members`` et à aucun de ``exclude``."""
    return any(glob_match(path, pattern) for pattern in members) and not any(
        glob_match(path, pattern) for pattern in exclude
    )


def glob_match(path: str, pattern: str) -> bool:
    """Vrai si le chemin POSIX ``path`` correspond au motif ``pattern`` (``packages/*``,
    ``libs/**``), élément par élément, comme les membres d'un workspace."""
    pattern = pattern.replace("\\", "/")
    parts = [part for part in pattern.split("/") if part not in ("", ".")]
    return _match_parts(path.split("/") if path != "." else [], parts)


def _match_parts(parts: Sequence[str], pattern: Sequence[str]) -> bool:
    if not pattern:
        return not parts
    head, rest = pattern[0], pattern[1:]
    if head == "**":
        return any(_match_parts(parts[i:], rest) for i in range(len(parts) + 1))
    return bool(parts) and fnmatchcase(parts[0], head) and _match_parts(parts[1:], rest)


def dirname(path: str) -> str:
    """Le dossier d'un chemin POSIX relatif ; ``.`` pour un fichier à la racine."""
    return posixpath.dirname(path) or "."


def join(directory: str, name: str) -> str:
    """``directory/name``, sans ``./`` devant quand ``directory`` est la racine."""
    return name if directory == "." else f"{directory}/{name}"


def relative_to(path: str, root: str) -> str:
    """Le dossier ``path`` vu depuis ``root``, qui le contient (``.`` si c'est le même)."""
    if root == ".":
        return path
    if path == root:
        return "."
    return path[len(root) + 1 :]
