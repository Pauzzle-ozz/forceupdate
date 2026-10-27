"""Les parseurs npm : ``package.json``, les lockfiles de npm, Yarn et pnpm, et le lien
entre les deux.

Manifeste lu : ``package.json``, ses ``dependencies`` (``runtime``),
``devDependencies`` (``dev``), ``peerDependencies`` (``peer``) et
``optionalDependencies`` (``optional``).

Lockfiles lus :

- ``package-lock.json`` et ``npm-shrinkwrap.json``, formats 1 (npm 5 et 6), 2 et 3 ;
- ``yarn.lock`` de Yarn 1, et celui de Yarn 2 et plus (YAML) ;
- ``pnpm-lock.yaml`` des formats 5.4 (pnpm 7), 6.0 (pnpm 8) et 9.0 (pnpm 9 et 10).

Pour un projet (``parse_project``) :

- les dépendances directes sont celles du ``package.json``, avec leur contrainte
  telle qu'écrite (``^1.2``, ``>=1 <2``, ``1.x || 2.x`` : E05 en tirera la borne
  basse) et son emplacement exact ;
- leur version installée est celle que le lockfile donne au projet : le
  ``node_modules/x`` que Node trouverait depuis son dossier (npm), son descripteur
  (Yarn), son importeur (pnpm) ;
- le reste du lockfile donne les transitives, avec leur scope tiré du graphe. Une
  autre version d'une directe (``node_modules/a/node_modules/x``) est une transitive.

Une dépendance ``catalog:`` (pnpm) garde sa contrainte telle qu'écrite ; la plage du
catalogue, lue dans ``pnpm-workspace.yaml``, va dans ``resolved_constraint``.

Un alias (``"mon-ms": "npm:ms@2.0.0"``) est vérifié sous le vrai nom du paquet
(``ms``), et sa contrainte est la partie après le ``@``. Une dépendance git, locale
(``file:``, ``link:``…) ou membre du workspace (``workspace:``) est « non
vérifiable », avec la raison.

Le lockfile d'un workspace, rattaché par E02 au plus proche dossier parent, n'est
gardé que si le projet en est membre : le lockfile le décrit, ou il correspond aux
``workspaces`` du ``package.json`` racine ou aux ``packages`` du
``pnpm-workspace.yaml``.

Repris de ``reference/argos_sca_parsers.py`` (L405-416, L648-797), puis adapté :
``Dependency`` au lieu de ``SCAComponent``, contraintes gardées telles qu'écrites au
lieu de ``_strip_npm_version``, emplacements, Yarn 2+ et pnpm 6 et 9 lus avec
``pyyaml`` au lieu d'une regex, lockfiles reliés aux manifestes, et un fichier
invalide signalé (``ParseError``) au lieu d'une liste vide.
"""

import dataclasses
import functools
import json
import logging
import posixpath
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import yaml

from forceupdate.detect.manifests import match_dependency_file
from forceupdate.models import Dependency, Ecosystem, Notice, Project, Scope
from forceupdate.parsers.base import (
    REASON_GIT,
    REASON_LOCAL,
    REASON_URL,
    REASON_WORKSPACE,
    ParseError,
    ReadText,
)
from forceupdate.parsers.json_spans import BOM, string_spans
from forceupdate.parsers.lockfiles import (
    Declared,
    Edge,
    LockedPackage,
    Lockfile,
    Start,
    dirname,
    in_workspace,
    join,
    relative_to,
    transitives,
)
from forceupdate.versions.npm import NPM

logger = logging.getLogger(__name__)

REASON_PATCH = "modifiée par un correctif local (patch:)"

_SECTIONS = (
    ("dependencies", Scope.RUNTIME),
    ("devDependencies", Scope.DEV),
    ("peerDependencies", Scope.PEER),
    ("optionalDependencies", Scope.OPTIONAL),
)

_RANGE_STARTS = frozenset("0123456789^~<>=*")
"""Premiers caractères d'une version ou d'une plage, jamais d'un nom de paquet courant."""

_PACKAGE_NAME = re.compile(r"(?:@[^/@\s]+/)?[^/@\s]+")

_GIT_PREFIXES = ("git+", "git:", "git@", "github:", "gitlab:", "bitbucket:", "gist:")
_LOCAL_PREFIXES = ("file:", "link:", "portal:", "exec:")

_YAML_LOADER = getattr(yaml, "CBaseLoader", yaml.BaseLoader)
"""Chargeur YAML qui garde tous les scalaires en chaînes : ``1.10`` reste ``"1.10"``, et
rien d'autre que des chaînes, listes et dictionnaires n'est construit. Celui de libyaml
s'il est là, bien plus rapide sur un gros lockfile."""


# ---------------------------------------------------------------------------
# Contraintes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Spec:
    """Ce que dit la valeur d'une dépendance dans un ``package.json``."""

    name: str
    """Le paquet à vérifier : la clé, ou le vrai paquet d'un alias ``npm:``."""
    constraint: str
    span: tuple[int, int] | None
    """Position de la contrainte dans la valeur ; ``None`` si on ne sait pas la réécrire."""
    reason: str | None = None


def _split_spec(key: str, value: str) -> _Spec:
    """Découpe la valeur d'une dépendance : plage, alias, git, chemin local…

    La contrainte est gardée telle qu'écrite, sans les espaces autour. Celle d'une
    dépendance non vérifiable est vide, et sans emplacement : une URL peut contenir
    un token.
    """
    start = len(value) - len(value.lstrip())
    end = len(value.rstrip())
    text = value[start:end]
    lowered = text.lower()
    if lowered.startswith("npm:"):
        return _split_alias(key, value, start + len("npm:"), end)
    if lowered.startswith("catalog:"):
        # Catalogue pnpm : la vraie plage est dans pnpm-workspace.yaml.
        return _Spec(key, text, None)
    reason = _spec_reason(text)
    if reason is not None:
        return _Spec(key, "", None, reason)
    return _Spec(key, text, (start, end))


def _split_alias(key: str, value: str, start: int, end: int) -> _Spec:
    """``npm:autre@^1.0`` : le paquet ``autre``, contrainte ``^1.0``. ``npm:^1.0`` (Yarn 2+)
    désigne le paquet de la clé."""
    rest = value[start:end]
    if not rest or rest[0] in _RANGE_STARTS:
        return _Spec(key, rest, (start, end))
    match = _PACKAGE_NAME.match(rest)
    if match is None:
        return _Spec(key, rest, (start, end))
    at = start + match.end()
    if at < end and value[at] == "@":
        return _Spec(match.group(), value[at + 1 : end], (at + 1, end))
    # Alias sans version : il faudrait ajouter « @ » avec la contrainte.
    return _Spec(match.group(), "", None)


def _spec_reason(spec: str) -> str | None:
    """Pourquoi une dépendance n'est pas vérifiable, d'après sa valeur ; ``None`` si elle
    vient du registre. La raison ne cite jamais l'URL."""
    lowered = spec.lower()
    if lowered.startswith("workspace:"):
        return REASON_WORKSPACE
    if lowered.startswith("patch:"):
        return REASON_PATCH
    if (
        lowered.startswith(_LOCAL_PREFIXES)
        or lowered.startswith((".", "/", "~/", "\\"))
        or re.match(r"[a-z]:[\\/]", lowered)
    ):
        return REASON_LOCAL
    if lowered.startswith(_GIT_PREFIXES):
        return REASON_GIT
    if "://" in lowered:
        return REASON_GIT if lowered.split("#", 1)[0].endswith(".git") else REASON_URL
    if "/" in lowered:
        return REASON_GIT  # raccourci GitHub : « utilisateur/depot#branche »
    return None


def _catalog_name(constraint: str) -> str | None:
    """Le catalogue pnpm que désigne une contrainte (``catalog:`` → ``default``,
    ``catalog:react17`` → ``react17``) ; ``None`` si ce n'en est pas une."""
    if not constraint.lower().startswith("catalog:"):
        return None
    return constraint[len("catalog:") :].strip() or "default"


def _real_name(key: str, spec: Any) -> str:
    """Le paquet derrière une dépendance d'un lockfile : la clé, sauf pour un alias."""
    return _split_spec(key, spec).name if isinstance(spec, str) else key


# ---------------------------------------------------------------------------
# package.json
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Entry:
    """Une dépendance d'un ``package.json``."""

    declared: Declared
    key: str
    """Son nom sous ``node_modules`` : la clé du ``package.json`` (l'alias, s'il y en a un)."""
    spec: str
    """Sa valeur telle qu'écrite : Yarn 1 la reprend telle quelle dans ses descripteurs."""


@dataclass
class _PackageJson:
    """Un ``package.json`` lu."""

    name: str | None
    entries: list[_Entry]
    workspaces: list[str]
    """Motifs des membres du workspace (``packages/*``), s'il y en a."""
    package_manager: str | None
    """L'outil déclaré dans ``packageManager`` (``npm``, ``yarn``, ``pnpm``)."""


def parse_package_json(path: str, content: str) -> list[Dependency]:
    """Les dépendances d'un ``package.json`` : ``dependencies``, ``devDependencies``,
    ``peerDependencies`` puis ``optionalDependencies``.

    Lève ``ParseError`` si le JSON est invalide.
    """
    return [entry.declared.dependency for entry in _parse_package_json(path, content).entries]


def _load_json(content: str) -> dict[str, Any]:
    try:
        data = json.loads(content.removeprefix(BOM))
    except ValueError as err:
        raise ParseError(f"JSON invalide ({err}).") from err
    if not isinstance(data, dict):
        raise ParseError("JSON inattendu : un objet est attendu.")
    return data


def _parse_package_json(path: str, content: str) -> _PackageJson:
    data = _load_json(content)
    spans = string_spans(content)
    entries = []
    for section, scope in _SECTIONS:
        values = data.get(section)
        if not isinstance(values, dict):
            continue
        for key, value in values.items():
            if not isinstance(value, str):
                continue
            spec = _split_spec(key, value)
            span = spans.get((section, key))
            location = None
            if span is not None and spec.span is not None:
                location = span.location(*spec.span)
            dependency = Dependency(
                ecosystem=Ecosystem.NPM,
                name=spec.name,
                constraint=spec.constraint,
                scope=scope,
                file=path,
                location=location,
                unverifiable_reason=spec.reason,
            )
            entries.append(_Entry(Declared(dependency), key, value))
    workspaces = data.get("workspaces")
    if isinstance(workspaces, dict):  # Yarn 1 : { "packages": [...], "nohoist": [...] }
        workspaces = workspaces.get("packages")
    manager = data.get("packageManager")
    name = data.get("name")
    return _PackageJson(
        name=name if isinstance(name, str) else None,
        entries=entries,
        workspaces=_strings(workspaces),
        package_manager=manager.split("@", 1)[0] if isinstance(manager, str) else None,
    )


def _strings(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


# ---------------------------------------------------------------------------
# Lockfiles
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class NpmLockfile:
    """Un lockfile npm, Yarn ou pnpm lu.

    Ses paquets forment un graphe de nœuds (``LockedPackage.key``) : un même paquet
    peut y être installé en plusieurs versions, à des endroits différents, et chaque
    paquet désigne exactement celui qu'il reçoit.
    """

    lockfile: Lockfile
    importers: Mapping[str, Mapping[str, str | None]] = field(default_factory=dict)
    """Les projets que le lockfile décrit, par dossier relatif au sien (``.`` pour le
    sien) : pour chacun, le nœud que reçoit chacune de ses dépendances, par nom sous
    ``node_modules`` (l'alias s'il y en a un)."""
    descriptors: Mapping[str, str] = field(default_factory=dict)
    """Yarn : le nœud de chaque descripteur (``lodash@^4.17.0``). Yarn 1 ne décrit pas
    les projets : c'est par là qu'on les relie au lockfile."""
    nodes: Mapping[str, LockedPackage] = field(default_factory=dict)
    """Les paquets, par nœud."""

    def resolve(self, project: str, key: str, spec: str) -> LockedPackage | None:
        """Le paquet que reçoit la dépendance ``key`` (valeur ``spec``) du projet
        ``project``, un dossier relatif à celui du lockfile."""
        importer = self.importers.get(project)
        # Yarn 1 ne décrit pas les projets : on passe par le descripteur.
        node = importer.get(key) if importer is not None else self.descriptors.get(f"{key}@{spec}")
        return self.nodes.get(node) if node is not None else None


def _npm_lockfile(
    path: str,
    packages: Iterable[LockedPackage],
    *,
    importers: Mapping[str, Mapping[str, str | None]] | None = None,
    descriptors: Mapping[str, str] | None = None,
) -> NpmLockfile:
    locked = tuple(packages)
    return NpmLockfile(
        lockfile=Lockfile(path=path, ecosystem=Ecosystem.NPM, packages=locked, graph=True),
        importers=importers or {},
        descriptors=descriptors or {},
        nodes={package.node: package for package in locked},
    )


def _edges(nodes: Iterable[str | None]) -> tuple[Edge, ...]:
    return tuple((node, frozenset()) for node in nodes if node is not None)


def _flag_scope(entry: Mapping[str, Any]) -> Scope | None:
    """Le scope que donnent les drapeaux d'un paquet (``dev``, ``optional``, ``peer``) :
    ``true`` en JSON, ``"true"`` avec le chargeur YAML."""

    def flag(name: str) -> bool:
        return entry.get(name) in (True, "true")

    if flag("dev") or flag("devOptional"):
        return Scope.DEV
    if flag("optional"):
        return Scope.OPTIONAL
    if flag("peer"):
        return Scope.PEER
    return None


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


# -- package-lock.json, npm-shrinkwrap.json ---------------------------------


def parse_package_lock_json(path: str, content: str) -> NpmLockfile:
    """Un ``package-lock.json`` ou un ``npm-shrinkwrap.json``.

    Formats 2 et 3 : ``packages``, où ``""`` est le projet, ``packages/a`` un membre
    du workspace (ou la cible d'un ``file:``), et ``node_modules/x`` un paquet
    installé. Format 1 (npm 5 et 6) : l'arbre ``dependencies``. Lève ``ParseError``
    si le JSON est invalide.
    """
    data = _load_json(content)
    packages = data.get("packages")
    if not isinstance(packages, dict):
        packages = _v1_packages(data.get("dependencies"))
    return _package_lock(path, packages)


def _package_lock(path: str, raw: Mapping[str, Any]) -> NpmLockfile:
    packages = {key: entry for key, entry in raw.items() if isinstance(entry, dict)}

    def resolve(start: str, name: str) -> str | None:
        """Le nœud de ``name`` que Node trouverait depuis le dossier ``start`` : dans son
        ``node_modules``, puis dans ceux des dossiers au-dessus. Un lien mène à sa cible."""
        directory = start
        while True:
            candidate = f"{directory}/node_modules/{name}" if directory else f"node_modules/{name}"
            entry = packages.get(candidate)
            if entry is not None:
                target = entry.get("resolved")
                if entry.get("link") is True and isinstance(target, str) and target in packages:
                    return target
                return candidate
            if not directory:
                return None
            directory = posixpath.dirname(directory)

    locked = []
    importers: dict[str, dict[str, str | None]] = {}
    for key, entry in packages.items():
        installed_name = _installed_name(key)
        if installed_name is None:  # un projet : la racine, un membre, la cible d'un file:
            importers[key or "."] = {
                dependency: resolve(key, dependency)
                for section, _ in _SECTIONS
                for dependency in _mapping(entry.get(section))
            }
        reason = _resolved_reason(entry.get("resolved"))
        name = entry.get("name")
        locked.append(
            LockedPackage(
                name=name if isinstance(name, str) else installed_name or key,
                version=str(entry.get("version", "")),
                dependencies=_edges(
                    resolve(key, dependency)
                    for section in ("dependencies", "optionalDependencies", "peerDependencies")
                    for dependency in _mapping(entry.get(section))
                ),
                scope=_flag_scope(entry) or Scope.RUNTIME,
                local=installed_name is None or entry.get("link") is True or reason == REASON_LOCAL,
                unverifiable_reason=reason,
                key=key or ".",
            )
        )
    return _npm_lockfile(path, locked, importers=importers)


def _installed_name(key: str) -> str | None:
    """Le nom installé d'une clé de ``packages`` (``node_modules/a/node_modules/@s/x`` →
    ``@s/x``) ; ``None`` pour un projet (``""``, ``packages/a``)."""
    if not key.startswith("node_modules/") and "/node_modules/" not in key:
        return None
    return key.rsplit("node_modules/", 1)[1]


def _v1_packages(dependencies: Any) -> dict[str, dict[str, Any]]:
    """L'arbre ``dependencies`` du format 1, mis sous la forme des ``packages`` des
    formats 2 et 3 : ``node_modules/a/node_modules/b`` pour ``b`` rangé sous ``a``."""
    top = _mapping(dependencies)
    packages: dict[str, dict[str, Any]] = {"": {"dependencies": dict.fromkeys(top, "")}}

    def walk(tree: Mapping[str, Any], prefix: str) -> None:
        for key, entry in tree.items():
            if not isinstance(entry, dict):
                continue
            location = f"{prefix}node_modules/{key}"
            raw_version = str(entry.get("version", ""))
            name, version, reason = _v1_version(key, raw_version)
            packages[location] = {
                **{flag: entry[flag] for flag in ("dev", "optional") if flag in entry},
                "name": name,
                "version": version,
                # Une « version » git ou file: dit d'où vient le paquet.
                "resolved": raw_version if reason else entry.get("resolved"),
                "dependencies": _mapping(entry.get("requires")),
            }
            walk(_mapping(entry.get("dependencies")), f"{location}/")

    walk(top, "")
    return packages


def _v1_version(key: str, version: str) -> tuple[str, str, str | None]:
    """Nom, version et raison d'un paquet du format 1 : la version peut être un alias
    (``npm:ms@2.0.0``), un chemin (``file:…``) ou une URL git."""
    if version.startswith("npm:"):
        spec = _split_spec(key, version)
        return spec.name, spec.constraint, None
    reason = _spec_reason(version)
    if reason is not None:
        return key, "", reason
    return key, version, None


def _resolved_reason(resolved: Any) -> str | None:
    """La raison que donne l'URL ``resolved`` d'un paquet : git ou chemin local."""
    if not isinstance(resolved, str):
        return None
    lowered = resolved.lower()
    if lowered.startswith(_GIT_PREFIXES):
        return REASON_GIT
    if lowered.startswith("file:"):
        return REASON_LOCAL
    return None


# -- yarn.lock ----------------------------------------------------------------


def parse_yarn_lock(path: str, content: str) -> NpmLockfile:
    """Un ``yarn.lock`` : le format de Yarn 1, ou le YAML de Yarn 2 et plus (reconnu à sa
    section ``__metadata``).

    Chaque bloc est un nœud, désigné par ses descripteurs (``lodash@^4.17.0``). Lève
    ``ParseError`` si le fichier n'est pas lisible.
    """
    if re.search(r"^__metadata:", content, re.MULTILINE):
        return _yarn_berry(path, content)
    return _yarn_v1(path, content)


def _split_descriptor(descriptor: str) -> tuple[str, str]:
    """``@s/x@^1.0`` → ``("@s/x", "^1.0")`` ; ``x@npm:^1.0`` → ``("x", "npm:^1.0")``."""
    at = descriptor.find("@", 1)
    if at == -1:
        return descriptor, ""
    return descriptor[:at], descriptor[at + 1 :]


def _descriptor_edges(descriptors: Mapping[str, str], *sections: Any) -> tuple[Edge, ...]:
    """Les dépendances d'un paquet Yarn (``nom: plage``) : le nœud de leur descripteur."""
    return _edges(
        descriptors.get(f"{key}@{spec}")
        for section in sections
        for key, spec in _mapping(section).items()
    )


def _yarn_v1(path: str, content: str) -> NpmLockfile:
    """Le format de Yarn 1 : des blocs ``descripteurs:`` puis ``  clé valeur``."""
    descriptors: dict[str, str] = {}
    blocks = []
    for keys, entry in _yarn_v1_blocks(content).items():
        version = entry.get("version")
        names = [_split_descriptor(d) for d in _split_outside_quotes(keys, ",")]
        if not isinstance(version, str) or not names:
            continue
        for key, spec in names:
            descriptors[f"{key}@{spec}"] = keys
        blocks.append((keys, entry, version, names[0]))
    locked = []
    for keys, entry, version, (key, spec) in blocks:
        reason = None if spec.startswith("npm:") else _spec_reason(spec)
        locked.append(
            LockedPackage(
                name=_real_name(key, spec),
                version=version,
                dependencies=_descriptor_edges(
                    descriptors, entry.get("dependencies"), entry.get("optionalDependencies")
                ),
                local=reason in (REASON_LOCAL, REASON_WORKSPACE),
                unverifiable_reason=reason or _resolved_reason(entry.get("resolved")),
                key=keys,
            )
        )
    return _npm_lockfile(path, locked, descriptors=descriptors)


def _yarn_v1_blocks(content: str) -> dict[str, dict[str, Any]]:
    """Les blocs d'un ``yarn.lock`` de Yarn 1, par ligne de descripteurs (brute).

    Le format est fait de lignes ``clé valeur`` et ``clé:``, imbriquées par
    l'indentation ; clés et valeurs sont entre guillemets quand il le faut.
    """
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for number, raw in enumerate(content.split("\n"), start=1):
        line = raw.rstrip()
        text = line.lstrip(" ")
        if not text or text.startswith("#"):
            continue
        indent = len(line) - len(text)
        while stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        if text.endswith(":"):
            child: dict[str, Any] = {}
            parent[text[:-1] if indent == 0 else _unquote(text[:-1])] = child
            stack.append((indent, child))
            continue
        words = _split_outside_quotes(text, " ")
        if len(words) != 2 or indent == 0:
            raise ParseError(f"yarn.lock illisible à la ligne {number}.")
        parent[words[0]] = words[1]
    return root


def _split_outside_quotes(text: str, separator: str) -> list[str]:
    """Coupe ``text`` sur ``separator``, sauf entre guillemets, et retire les guillemets ;
    sans les morceaux vides."""
    parts = []
    current: list[str] = []
    quoted = False
    index = 0
    while index < len(text):
        char = text[index]
        if quoted and char == "\\":
            current.append(text[index : index + 2])
            index += 2
            continue
        if char == '"':
            quoted = not quoted
        if char == separator and not quoted:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    parts.append("".join(current))
    return [_unquote(part.strip()) for part in parts if part.strip()]


def _unquote(text: str) -> str:
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        try:
            return str(json.loads(text))
        except ValueError:
            return text[1:-1]
    return text


def _load_yaml(content: str) -> dict[str, Any]:
    """Le document YAML de ``content`` ; le dernier s'il y en a plusieurs.

    Depuis pnpm 11, ``pnpm-lock.yaml`` commence par un document qui fige pnpm
    lui-même (``packageManagerDependencies``), puis vient le lockfile du projet.
    """
    try:
        documents = list(yaml.load_all(content, Loader=_YAML_LOADER))  # que des chaînes
        data = next((d for d in reversed(documents) if d is not None), None)
    except yaml.YAMLError as err:
        mark = getattr(err, "problem_mark", None)
        problem = getattr(err, "problem", None)
        if mark is not None and problem:
            raise ParseError(f"YAML invalide (ligne {mark.line + 1} : {problem}).") from err
        raise ParseError("YAML invalide.") from err
    if not isinstance(data, dict):
        raise ParseError("YAML inattendu : un dictionnaire est attendu.")
    return data


def _yarn_berry(path: str, content: str) -> NpmLockfile:
    """Le ``yarn.lock`` de Yarn 2 et plus : du YAML, une entrée par paquet résolu, et une
    par membre du workspace (``nom@workspace:chemin``), qui liste ses dépendances."""
    data = _load_yaml(content)
    descriptors: dict[str, str] = {}
    blocks = []
    for keys, entry in data.items():
        if keys == "__metadata" or not isinstance(entry, dict):
            continue
        resolution = entry.get("resolution")
        version = entry.get("version")
        if not isinstance(resolution, str) or not isinstance(version, str):
            continue
        for descriptor in keys.split(","):
            descriptors[descriptor.strip()] = keys
        blocks.append((keys, entry, resolution, version))
    locked = []
    importers: dict[str, dict[str, str | None]] = {}
    for keys, entry, resolution, version in blocks:
        name, reference = _split_descriptor(resolution)
        reason = _berry_reason(reference)
        local = reason in (REASON_LOCAL, REASON_WORKSPACE)
        dependencies = _mapping(entry.get("dependencies"))
        if reference.startswith("workspace:"):
            importers[posixpath.normpath(reference.removeprefix("workspace:"))] = {
                key: descriptors.get(f"{key}@{spec}") for key, spec in dependencies.items()
            }
        locked.append(
            LockedPackage(
                name=name,
                version="" if local else version,
                dependencies=_descriptor_edges(descriptors, dependencies),
                local=local,
                unverifiable_reason=reason,
                key=keys,
            )
        )
    return _npm_lockfile(path, locked, importers=importers, descriptors=descriptors)


def _berry_reason(reference: str) -> str | None:
    """La raison d'une résolution de Yarn 2+ (``npm:1.0.0``, ``workspace:…``, URL git…).

    Un ``patch:`` reste vérifiable : Yarn en met d'office sur ``typescript``,
    ``fsevents`` ou ``resolve``, et c'est le paquet du registre qui est en dessous.
    """
    if reference.startswith(("npm:", "patch:")):
        return None
    return _spec_reason(reference)


# -- pnpm-lock.yaml -----------------------------------------------------------


def parse_pnpm_lock_yaml(path: str, content: str) -> NpmLockfile:
    """Un ``pnpm-lock.yaml``, formats 5.4, 6.0 et 9.0.

    Les ``importers`` sont les projets du workspace (sans workspace, avant le format
    9, le projet est écrit à la racine du fichier) ; chacun est aussi un nœud, que
    tirent les projets qui en dépendent (``link:../lib``). Les paquets sont dans
    ``snapshots`` (format 9) ou ``packages``. Lève ``ParseError`` si le YAML est
    invalide.
    """
    data = _load_yaml(content)
    v5 = str(data.get("lockfileVersion", "")).startswith("5")
    raw_importers = data.get("importers")
    if not isinstance(raw_importers, dict):
        raw_importers = {".": data}
    projects = {
        posixpath.normpath(project): _mapping(entry)
        for project, entry in raw_importers.items()
        if isinstance(project, str)
    }
    metadata = _mapping(data.get("packages"))
    snapshots = data.get("snapshots")
    entries = _mapping(snapshots) if isinstance(snapshots, dict) else metadata
    nodes = {
        key.removeprefix("/"): entry
        for key, entry in entries.items()
        if isinstance(key, str) and isinstance(entry, dict)
    }

    def target(name: str, reference: Any, project: str | None) -> str | None:
        """Le nœud que désigne une référence : ``4.17.21``, ``18.3.1(react@18.3.1)``, un
        alias (``ms@2.0.0``, ``/ms@2.0.0``, ``/ms/2.0.0``), ou ``link:../lib`` depuis le
        dossier ``project``."""
        if isinstance(reference, dict):  # formats 6 et 9 : {specifier, version}
            reference = reference.get("version")
        if not isinstance(reference, str):
            return None
        if reference.startswith("link:"):
            if project is None:
                return None
            linked = posixpath.normpath(posixpath.join(project, reference.removeprefix("link:")))
            return _importer_node(linked) if linked in projects else None
        bare = reference.removeprefix("/")
        qualified = f"{name}/{bare}" if v5 else f"{name}@{bare}"
        return next((node for node in (qualified, bare) if node in nodes), None)

    locked = []
    importers: dict[str, dict[str, str | None]] = {}
    for project, entry in projects.items():
        importers[project] = {
            key: target(key, reference, project)
            for section, _ in _SECTIONS
            for key, reference in _mapping(entry.get(section)).items()
        }
        locked.append(
            LockedPackage(
                name=project,
                dependencies=_edges(
                    target(key, reference, project)
                    for section in ("dependencies", "optionalDependencies")
                    for key, reference in _mapping(entry.get(section)).items()
                ),
                local=True,
                key=_importer_node(project),
            )
        )
    for key, entry in nodes.items():
        name, version = _pnpm_package_key(key, v5=v5)
        details = _mapping(metadata.get(_without_peers(key, v5=v5))) or entry
        reason = _pnpm_reason(version, _mapping(details.get("resolution")))
        if reason is not None:
            # Paquet git ou local : sa clé est une URL ou un chemin, mais pnpm écrit à
            # côté son nom (format 6) et sa version.
            name = details["name"] if isinstance(details.get("name"), str) else name
            version = details["version"] if isinstance(details.get("version"), str) else ""
        locked.append(
            LockedPackage(
                name=name,
                version="" if reason in (REASON_LOCAL, REASON_WORKSPACE) else version,
                dependencies=_edges(
                    target(dependency, reference, None)
                    for section in ("dependencies", "optionalDependencies")
                    for dependency, reference in _mapping(entry.get(section)).items()
                ),
                scope=_flag_scope(entry) or _flag_scope(details),
                local=reason in (REASON_LOCAL, REASON_WORKSPACE),
                unverifiable_reason=reason,
                key=key,
            )
        )
    return _npm_lockfile(path, locked, importers=importers)


def _importer_node(project: str) -> str:
    """Le nœud d'un projet de ``importers`` : distinct des clés de paquets."""
    return f"importer:{project}"


def _pnpm_package_key(key: str, *, v5: bool) -> tuple[str, str]:
    """Nom et version d'une clé de paquet : ``@s/x@1.0.0(peer@2)`` (formats 6 et 9) ou
    ``@s/x/1.0.0_peer@2`` (format 5). La version d'un paquet git ou local est sa
    référence (``github.com/…``, ``file:…``)."""
    if v5:
        parts = key.split("/", 2) if key.startswith("@") else key.split("/", 1)
        if len(parts) < (3 if key.startswith("@") else 2):
            return key, ""
        return "/".join(parts[:-1]), _without_peers(parts[-1], v5=True)
    name, version = _split_descriptor(key)
    return name, _without_peers(version, v5=False)


def _without_peers(version: str, *, v5: bool) -> str:
    """Retire ce que pnpm ajoute après la version : ``(react@18.3.1)``, ou ``_react@18.3.1``
    au format 5."""
    cut = version.find("_" if v5 else "(")
    return version if cut == -1 else version[:cut]


def _pnpm_reason(version: str, resolution: Mapping[str, Any]) -> str | None:
    if version[:1].isdigit():
        return None
    if "directory" in resolution or version.startswith(("file:", "link:")):
        return REASON_LOCAL
    if resolution.get("type") == "git" or "git" in version.lower():
        return REASON_GIT
    return REASON_URL


# ---------------------------------------------------------------------------
# Un projet
# ---------------------------------------------------------------------------

_LOCK_PARSERS: dict[str, Callable[[str, str], NpmLockfile]] = {
    "npm-shrinkwrap.json": parse_package_lock_json,
    "package-lock.json": parse_package_lock_json,
    "yarn.lock": parse_yarn_lock,
    "pnpm-lock.yaml": parse_pnpm_lock_yaml,
}
"""Les lockfiles npm, dans l'ordre de préférence quand ``packageManager`` ne dit rien.
npm ignore ``package-lock.json`` quand il y a un ``npm-shrinkwrap.json``."""

_MANAGER_LOCKS = {
    "npm": ("npm-shrinkwrap.json", "package-lock.json"),
    "yarn": ("yarn.lock",),
    "pnpm": ("pnpm-lock.yaml",),
}


def parse_project(project: Project, read_text: ReadText, project_dirs: Sequence[str] = ()) -> None:
    """Lit les fichiers npm de ``project`` et remplit ses dépendances.

    Ajoute à ``project.dependencies`` les directes (dans l'ordre du ``package.json``)
    puis les transitives, et à ``project.notices`` ce qui n'a pas pu être lu. Le
    lockfile d'un workspace dont le projet n'est pas membre est retiré de
    ``project.lockfiles``.

    ``project_dirs`` sont les dossiers de tous les projets de la source : Yarn 1
    n'écrit pas les membres de son workspace dans ``yarn.lock``, on les retrouve là.
    """
    _ProjectParser(project, read_text, project_dirs).run()


@functools.lru_cache(maxsize=4)
def _parse_lock_once(pattern: str, path: str, content: str) -> NpmLockfile:
    """Lit un lockfile, une seule fois pour un même contenu : celui d'un workspace est
    relu par chacun de ses membres (21 fois chez ariakit). Le résultat est partagé :
    on ne le modifie pas."""
    return _LOCK_PARSERS[pattern](path, content)


class _ProjectParser:
    """Lit les fichiers npm d'un projet et relie le ``package.json`` au lockfile."""

    def __init__(self, project: Project, read_text: ReadText, project_dirs: Sequence[str]) -> None:
        self.project = project
        self.read_text = read_text
        self.project_dirs = project_dirs
        self.notices: list[Notice] = []
        self.manifest_path = next(
            (path for path in project.manifests if _pattern(path) == "package.json"), None
        )
        self.locks = {
            pattern: path
            for path in project.lockfiles
            if (pattern := _pattern(path)) in _LOCK_PARSERS
        }

    def run(self) -> None:
        directs: list[Dependency] = []
        found: list[Dependency] = []
        manifest = self._manifest()
        lock = self._lockfile(manifest)
        if manifest is not None and lock is not None:
            directs, found = self._link(manifest, lock)
        elif manifest is not None:
            directs = [entry.declared.dependency for entry in manifest.entries]
        elif lock is not None and dirname(lock.lockfile.path) == self.project.path:
            # Pas de package.json lisible : tout le lockfile est transitif.
            lockfile = dataclasses.replace(lock.lockfile, shared=False)
            found = transitives(lockfile, [], lambda package: False)
        directs = self._with_catalogs(directs)
        found.sort(key=lambda d: (d.file, d.name, NPM.sort_key(d.installed or "")))
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

    def _read_quietly(self, path: str) -> str | None:
        """Lit un fichier dont l'absence n'est pas une erreur (``pnpm-workspace.yaml``)."""
        try:
            return self.read_text(path)
        except ValueError:
            return None

    def _manifest(self) -> _PackageJson | None:
        if self.manifest_path is None:
            return None
        content = self._read(self.manifest_path)
        if content is None:
            return None
        try:
            return _parse_package_json(self.manifest_path, content)
        except ParseError as err:
            self.notices.append(Notice(file=self.manifest_path, message=str(err)))
            return None

    def _parse_lock(self, path: str) -> NpmLockfile | None:
        content = self._read(path)
        if content is None:
            return None
        try:
            return _parse_lock_once(_pattern(path) or "", path, content)
        except ParseError as err:
            self.notices.append(Notice(file=path, message=str(err)))
            return None

    # -- lockfile -----------------------------------------------------------

    def _lockfile(self, manifest: _PackageJson | None) -> NpmLockfile | None:
        """Le lockfile du projet, s'il en a un et qu'il en est bien membre.

        Les autres lockfiles npm du même dossier reçoivent une remarque « pas lu ».
        """
        if not self.locks:
            return None
        lock_dir = dirname(next(iter(self.locks.values())))
        relative = relative_to(self.project.path, lock_dir)
        root = manifest if lock_dir == self.project.path else self._root_manifest(lock_dir)
        preferred = _MANAGER_LOCKS.get(root.package_manager or "", ()) if root else ()
        chosen = next(
            self.locks[name] for name in (*preferred, *_LOCK_PARSERS) if name in self.locks
        )
        lock = self._parse_lock(chosen)
        globs = root.workspaces if root is not None else []
        if _pattern(chosen) == "pnpm-lock.yaml":
            globs = self._pnpm_workspace(lock_dir)

        known = lock is not None and relative in lock.importers
        if lock_dir != self.project.path and not (known or _in_globs(relative, globs)):
            logger.debug("%s n'est pas membre du workspace de %s", self.project.path, lock_dir)
            for path in self.locks.values():
                self.project.lockfiles.remove(path)
            self.notices = [n for n in self.notices if n.file not in self.locks.values()]
            return None

        owner = self.manifest_path or "ce dossier"
        for path in self.locks.values():
            if path != chosen:
                message = f"pas lu : {chosen} est le lockfile pris pour {owner}."
                self.notices.append(Notice(file=path, message=message))
        if lock is None:
            return None
        if globs and not lock.importers:
            lock = self._yarn_v1_workspace(lock, lock_dir, globs)
        shared = len(lock.importers) > 1 or bool(globs)
        return dataclasses.replace(lock, lockfile=dataclasses.replace(lock.lockfile, shared=shared))

    def _yarn_v1_workspace(self, lock: NpmLockfile, lock_dir: str, globs: list[str]) -> NpmLockfile:
        """Ajoute au ``yarn.lock`` d'un workspace Yarn 1 ses projets, que Yarn 1 n'écrit pas
        (Yarn 2+ et pnpm le font) : chacun devient un nœud, qui tire ses dépendances.

        Sans ça, ``"a": "^1.0.0"`` vers le membre ``a`` serait pris pour le paquet ``a``
        du registre, et ce que ``a`` tire serait perdu.
        """
        manifests: dict[str, _PackageJson] = {}
        for directory in dict.fromkeys([lock_dir, *self.project_dirs]):
            inside = (
                lock_dir == "." or directory == lock_dir or directory.startswith(f"{lock_dir}/")
            )
            relative = relative_to(directory, lock_dir) if inside else None
            if relative is None or (relative != "." and not _in_globs(relative, globs)):
                continue
            path = join(directory, "package.json")
            content = self._read_quietly(path)
            try:
                if content is not None:
                    manifests[relative] = _parse_package_json(path, content)
            except ParseError:
                continue  # la remarque vient avec ce projet
        members = {m.name: relative for relative, m in manifests.items() if m.name is not None}

        def node(entry: _Entry) -> str | None:
            if entry.key in members:
                return _importer_node(members[entry.key])
            return lock.descriptors.get(f"{entry.key}@{entry.spec}")

        projects = [
            LockedPackage(
                name=manifest.name or relative,
                dependencies=_edges(
                    node(entry)
                    for entry in manifest.entries
                    if entry.declared.dependency.scope in (Scope.RUNTIME, Scope.OPTIONAL)
                ),
                local=True,
                key=_importer_node(relative),
            )
            for relative, manifest in manifests.items()
        ]
        return _npm_lockfile(
            lock.lockfile.path,
            (*lock.lockfile.packages, *projects),
            importers={
                relative: {entry.key: node(entry) for entry in manifest.entries}
                for relative, manifest in manifests.items()
            },
            descriptors=lock.descriptors,
        )

    def _root_manifest(self, directory: str) -> _PackageJson | None:
        """Le ``package.json`` à la racine du workspace ; ``None`` s'il n'est pas lisible
        (la remarque vient avec le projet racine)."""
        path = join(directory, "package.json")
        content = self._read_quietly(path)
        if content is None:
            return None
        try:
            return _parse_package_json(path, content)
        except ParseError:
            return None

    def _pnpm_workspace(self, directory: str) -> list[str]:
        """Les motifs ``packages`` du ``pnpm-workspace.yaml`` de ``directory``."""
        path = join(directory, "pnpm-workspace.yaml")
        content = self._read_quietly(path)
        if content is None:
            return []
        try:
            return _strings(_load_yaml(content).get("packages"))
        except ParseError as err:
            if directory == self.project.path:
                self.notices.append(Notice(file=path, message=str(err)))
            return []

    # -- catalogues pnpm ----------------------------------------------------

    def _with_catalogs(self, directs: list[Dependency]) -> list[Dependency]:
        """Les directes en ``catalog:``, avec la plage de leur catalogue
        (``resolved_constraint``), lue dans le ``pnpm-workspace.yaml`` le plus proche.

        Une valeur de catalogue qui n'est pas une plage (alias ``npm:``, git…) est lue
        comme dans un ``package.json``. Plage introuvable : une remarque, et E07 se fiera
        à la version installée.
        """
        if all(_catalog_name(d.constraint) is None for d in directs):
            return directs
        path, catalogs = self._catalogs()
        if catalogs is None:
            if path is None:
                message = "catalog: : aucun pnpm-workspace.yaml lisible, plage inconnue."
                self.notices.append(Notice(file=self.manifest_path or ".", message=message))
            return directs
        resolved = []
        for dependency in directs:
            catalog = _catalog_name(dependency.constraint)
            if catalog is None:
                resolved.append(dependency)
                continue
            value = _mapping(catalogs.get(catalog)).get(dependency.name)
            spec = _split_spec(dependency.name, value) if isinstance(value, str) else None
            if spec is None or _catalog_name(spec.constraint) is not None:
                message = f"{dependency.name} absent du catalogue « {catalog} » : plage inconnue."
                self.notices.append(Notice(file=path or ".", message=message))
                resolved.append(dependency)
                continue
            resolved.append(
                dataclasses.replace(
                    dependency,
                    name=spec.name,
                    resolved_constraint=spec.constraint if spec.reason is None else None,
                    unverifiable_reason=spec.reason,
                )
            )
        return resolved

    def _catalogs(self) -> tuple[str | None, dict[str, Any] | None]:
        """Le ``pnpm-workspace.yaml`` le plus proche en remontant depuis le projet, et ses
        catalogues par nom : ``catalog`` est le catalogue ``default``, comme
        ``catalogs.default``. ``(None, None)`` s'il n'y en a pas ; ``(chemin, None)`` s'il
        est invalide (avec une remarque)."""
        directory = self.project.path
        while True:
            path = join(directory, "pnpm-workspace.yaml")
            content = self._read_quietly(path)
            if content is not None:
                break
            if directory == ".":
                return None, None
            directory = dirname(directory)
        try:
            data = _load_yaml(content)
        except ParseError as err:
            notice = Notice(file=path, message=str(err))
            if notice not in self.notices:
                self.notices.append(notice)
            return path, None
        catalogs = dict(_mapping(data.get("catalogs")))
        if isinstance(data.get("catalog"), dict):
            catalogs["default"] = data["catalog"]
        return path, catalogs

    # -- lien ---------------------------------------------------------------

    def _link(
        self, manifest: _PackageJson, lock: NpmLockfile
    ) -> tuple[list[Dependency], list[Dependency]]:
        """Les directes avec leur version installée, et les transitives que le projet tire
        du lockfile, en suivant le graphe depuis les nœuds de ses directes."""
        relative = relative_to(self.project.path, dirname(lock.lockfile.path))
        directs = []
        starts: list[Start] = []
        direct_nodes: set[str] = set()
        for entry in manifest.entries:
            dependency = entry.declared.dependency
            package = lock.resolve(relative, entry.key, entry.spec)
            if package is not None:
                starts.append((dependency.scope, (package.node, frozenset())))
                direct_nodes.add(package.node)
                if package.local and dependency.unverifiable_reason is None:
                    # « "a": "^1.0.0" » que npm a résolu vers le membre packages/a : le
                    # paquet « a » du registre n'a rien à voir.
                    reason = package.unverifiable_reason or REASON_WORKSPACE
                    dependency = dataclasses.replace(dependency, unverifiable_reason=reason)
                elif package.version and not package.local:
                    dependency = dataclasses.replace(dependency, installed=package.version)
            directs.append(dependency)
        # Un paquet en double à la même version (les « patch: » que Yarn met d'office) n'est
        # pas une transitive non plus.
        pairs = {(d.name, d.installed) for d in directs if d.installed}
        found = transitives(
            lock.lockfile,
            starts,
            lambda package: (
                package.node in direct_nodes or (package.name, package.version) in pairs
            ),
        )
        return directs, found


def _pattern(path: str) -> str | None:
    """Le motif npm reconnu pour ``path`` (``package.json``, ``yarn.lock``…)."""
    match = match_dependency_file(path)
    if match is None or match.ecosystem is not Ecosystem.NPM:
        return None
    return match.pattern


def _in_globs(path: str, globs: Iterable[str]) -> bool:
    """Vrai si ``path`` correspond aux motifs d'un workspace npm ou pnpm, où ``!motif``
    exclut."""
    members = [glob for glob in globs if not glob.startswith("!")]
    excluded = [glob[1:] for glob in globs if glob.startswith("!")]
    return in_workspace(path, members, excluded)
