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

from forceupdate.models import Dependency, Ecosystem, Location, Scope

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


SCOPE_ORDER = (Scope.RUNTIME, Scope.PEER, Scope.OPTIONAL, Scope.DEV)
"""Le scope d'une transitive est le premier, dans cet ordre, des directes qui la tirent.
Les dépendances de build ne sont pas dans les lockfiles."""


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
    lock: Lockfile, starts: Sequence[Start], is_direct: Callable[[LockedPackage], bool]
) -> list[Dependency]:
    """Les paquets du lockfile qui ne sont pas des directes (selon ``is_direct``).

    Avec un graphe, le scope de chacun est celui des directes (``starts``) qui le
    tirent ; pour un lockfile partagé (workspace), seuls comptent les paquets
    qu'elles tirent. Un même paquet à la même version n'est rendu qu'une fois.
    """
    scopes = reachable_scopes(starts, lock) if lock.graph else {}
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
            )
        )
    return result


def reachable_scopes(starts: Sequence[Start], lock: Lockfile) -> dict[str, Scope]:
    """Pour chaque nœud que tirent les directes, son scope (voir ``SCOPE_ORDER``)."""
    by_node: dict[str, list[LockedPackage]] = defaultdict(list)
    for package in lock.packages:
        by_node[package.node].append(package)
    scopes: dict[str, Scope] = {}
    for scope in SCOPE_ORDER:
        for node in reach([edge for s, edge in starts if s is scope], by_node):
            scopes.setdefault(node, scope)
    return scopes


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
