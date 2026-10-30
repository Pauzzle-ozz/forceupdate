"""Les parseurs PHP : ``composer.json``, ``composer.lock``, et le lien entre les deux.

Manifeste lu : ``composer.json``, ses ``require`` (``runtime``) et ``require-dev`` (``dev``), avec
la contrainte telle qu'écrite et son emplacement exact. Les noms sont mis en minuscules, comme le
fait Composer (``Monolog/Monolog`` est ``monolog/monolog``), et comme les attend OSV.

Mis de côté :

- les paquets « plateforme » : ``php``, ``ext-*``, ``lib-*``, ``composer-plugin-api``… (le motif
  de Composer, ``PlatformRepository::PLATFORM_PACKAGE_REGEX``). La version de PHP est pour E27 ;
- ``replace`` et ``provide`` : des paquets que le projet fournit lui-même. Ils ne sont pas dans
  le lockfile ; une dépendance qui en est un est « non vérifiable ».

**Non vérifiables**, avec la raison :

- une branche : ``dev-main``, ``1.x-dev``, ``dev-main as 1.0.x-dev``, ``dev-main#abc123`` ; une
  version figée qui en est une (``*@dev`` résolu en ``dev-master``) ;
- un paquet d'un dépôt ``path`` (le lockfile le dit : ``"dist": {"type": "path"}``) ;
- un paquet venu d'un autre dépôt que Packagist, quand ``repositories`` en déclare un ``vcs``
  (``git``, ``github``…), ``package`` ou ``artifact`` : le lockfile n'y a pas l'adresse de
  Packagist (``notification-url``). Un dépôt ``composer`` (miroir, Satis, Private Packagist) n'est
  pas distingué : ses paquets sont cherchés sur Packagist, un paquet privé y est introuvable.

``conflict`` donne les versions que le projet refuse : ``Dependency.excluded`` (des
contraintes), jamais proposées. ``minimum-stability`` (``stable`` par défaut) et ``prefer-stable``
: forceupdate ne propose que des versions stables ; une stabilité plus basse sans
``prefer-stable`` donne une remarque (Composer peut alors choisir une pré-version).

Lockfile lu : ``composer.lock``, ``packages`` et ``packages-dev`` (``dev``), la version telle
qu'écrite (``v5.4.10`` pour Symfony), et ce que chaque paquet requiert (``require``) : on suit le
graphe depuis les directes pour le scope des transitives. Composer n'a pas de workspace : le
lockfile est celui du dossier du ``composer.json``.

Repris de ``reference/argos_sca_parsers.py`` (L959-1022), puis adapté : ``Dependency`` au lieu de
``SCAComponent``, contraintes gardées telles qu'écrites au lieu de ``_strip_npm_version`` (qui
exigeait trois nombres), emplacements, ``lib-*`` et ``composer-plugin-api`` écartés comme ``php``
et ``ext-*``, branches, dépôts ``path`` et autres non vérifiables (``reference/`` marquait tout le
lockfile ``pinned``, ``dev-master`` compris), lockfile relié au manifeste par son graphe, et un
fichier invalide signalé (``ParseError``) au lieu d'une liste vide.
"""

import dataclasses
import functools
import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from forceupdate.detect.manifests import match_dependency_file
from forceupdate.models import Dependency, Ecosystem, Location, Notice, Project, Scope
from forceupdate.parsers.base import REASON_LOCAL, ParseError, ReadText
from forceupdate.parsers.json_spans import BOM, string_spans
from forceupdate.parsers.lockfiles import Edge, LockedPackage, Lockfile, Start, transitives
from forceupdate.parsers.toml_spans import StringSpan
from forceupdate.versions import InvalidVersion
from forceupdate.versions.composer import COMPOSER, STABILITIES, is_branch, normalize

logger = logging.getLogger(__name__)

MANIFEST = "composer.json"
LOCKFILE = "composer.lock"

PACKAGIST_NOTIFICATION = "https://packagist.org/downloads/"
"""Le ``notification-url`` d'un paquet venu de Packagist, dans ``composer.lock``."""

REASON_BRANCH = "branche de développement"
REASON_PROVIDED = "fournie par le projet lui-même (replace, provide)"
REASON_OTHER_REPOSITORY = "vient d'un dépôt déclaré dans « repositories », pas de Packagist"

PLATFORM = re.compile(
    r"(?:php(?:-64bit|-ipv6|-zts|-debug)?|hhvm|(?:ext|lib)-[a-z0-9](?:[_.-]?[a-z0-9]+)*"
    r"|composer(?:-(?:plugin|runtime)-api)?)",
    re.IGNORECASE,
)
"""Un paquet « plateforme » : PHP, une extension, une bibliothèque du système, l'API de Composer
(``PlatformRepository::PLATFORM_PACKAGE_REGEX`` de Composer 2.11)."""

_SECTIONS = (("require", Scope.RUNTIME), ("require-dev", Scope.DEV))

_OTHER_REPOSITORIES = frozenset(
    {
        "vcs",
        "git",
        "github",
        "gitlab",
        "bitbucket",
        "git-bitbucket",
        "hg",
        "fossil",
        "perforce",
        "svn",
        "package",
        "artifact",
    }
)
"""Les types de ``repositories`` dont les paquets ne viennent pas de Packagist ni d'un miroir."""


def is_platform(name: str) -> bool:
    """Vrai pour un paquet « plateforme » (``php``, ``ext-json``…) : pas un paquet de Packagist."""
    return PLATFORM.fullmatch(name) is not None


# ---------------------------------------------------------------------------
# composer.json
# ---------------------------------------------------------------------------


def _load_json(content: str) -> dict[str, Any]:
    try:
        data = json.loads(content.removeprefix(BOM))
    except ValueError as err:
        raise ParseError(f"JSON invalide ({err}).") from err
    if not isinstance(data, dict):
        raise ParseError("JSON inattendu : un objet est attendu.")
    return data


def _object(data: Any, key: str) -> dict[str, Any]:
    value = data.get(key) if isinstance(data, dict) else None
    return value if isinstance(value, dict) else {}


@dataclass(frozen=True, kw_only=True)
class ComposerJson:
    """Un ``composer.json`` lu."""

    dependencies: list[Dependency]
    notices: list[Notice]
    conflicts: dict[str, tuple[str, ...]]
    """``conflict`` : par paquet, les contraintes des versions que le projet refuse."""
    other_repositories: bool
    """``repositories`` déclare un dépôt qui n'est ni Packagist ni un miroir (``vcs``,
    ``package``, ``artifact``…)."""


def parse_composer_json(path: str, content: str) -> list[Dependency]:
    """Les dépendances d'un ``composer.json`` : ``require``, puis ``require-dev``, sans les
    paquets « plateforme ». Lève ``ParseError`` si le JSON est invalide."""
    return _parse_composer_json(path, content).dependencies


def _parse_composer_json(path: str, content: str) -> ComposerJson:
    data = _load_json(content)
    spans = string_spans(content)
    provided = {
        name.lower() for key in ("replace", "provide") for name in _object(data, key) if name
    }
    conflicts: dict[str, tuple[str, ...]] = {}
    for name, value in _object(data, "conflict").items():
        if isinstance(value, str) and value.strip():
            conflicts[name.lower()] = (*conflicts.get(name.lower(), ()), value.strip())
    dependencies = []
    notices = []
    for section, scope in _SECTIONS:
        for key, value in _object(data, section).items():
            name = key.strip().lower()
            if not name or is_platform(name):
                continue
            if not isinstance(value, str):
                notices.append(Notice(file=path, message=f"« {key} » : contrainte illisible."))
                continue
            constraint, location = _constraint(value, spans.get((section, key)))
            reason = REASON_PROVIDED if name in provided else _reason(constraint)
            dependencies.append(
                Dependency(
                    ecosystem=Ecosystem.PACKAGIST,
                    name=name,
                    constraint=constraint,
                    scope=scope,
                    file=path,
                    location=location,
                    unverifiable_reason=reason,
                    excluded=conflicts.get(name, ()),
                )
            )
    stability = data.get("minimum-stability")
    if (
        isinstance(stability, str)
        and stability.lower() in {s.lower() for s in STABILITIES}
        and stability.lower() != "stable"
        and data.get("prefer-stable") is not True
    ):
        notices.append(
            Notice(
                file=path,
                message=(
                    f"minimum-stability « {stability} » sans prefer-stable : Composer peut choisir "
                    "des pré-versions ; forceupdate ne propose que des versions stables."
                ),
            )
        )
    return ComposerJson(
        dependencies=dependencies,
        notices=notices,
        conflicts=conflicts,
        other_repositories=bool(_repository_types(data.get("repositories")) & _OTHER_REPOSITORIES),
    )


def _constraint(value: str, span: StringSpan | None) -> tuple[str, Location | None]:
    """La contrainte sans les espaces qui l'entourent, et son emplacement."""
    start = len(value) - len(value.lstrip())
    end = len(value.rstrip())
    return value[start:end], span.location(start, end) if span is not None else None


def _reason(constraint: str) -> str | None:
    """Pourquoi une contrainte n'est pas vérifiable : elle demande une branche (``dev-main``,
    ``1.x-dev``, avec un alias, une référence ou un drapeau de stabilité). Une union ou un
    intervalle qui en citent une reste vérifiable."""
    text = constraint.split(" as ", 1)[0].strip()
    if not text or re.search(r"[|\s,]", text):
        return None
    text = re.sub(r"@\w+$", "", re.sub(r"#.+$", "", text))
    try:
        return REASON_BRANCH if is_branch(normalize(text)) else None
    except InvalidVersion:
        return None


def _repository_types(value: Any) -> set[str]:
    """Les types des dépôts de ``repositories`` (une liste, ou un objet par nom)."""
    if isinstance(value, dict):
        entries = list(value.values())
    elif isinstance(value, list):
        entries = value
    else:
        return set()
    return {
        entry["type"].lower()
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("type"), str)
    }


# ---------------------------------------------------------------------------
# composer.lock
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class ComposerLockfile:
    """Un ``composer.lock`` lu."""

    lockfile: Lockfile
    from_packagist: frozenset[str]
    """Les paquets que le lockfile dit venus de Packagist (``notification-url``)."""

    def package(self, name: str) -> LockedPackage | None:
        return self._by_name.get(name)

    @functools.cached_property
    def _by_name(self) -> dict[str, LockedPackage]:
        return {package.name: package for package in self.lockfile.packages}


def parse_composer_lock(path: str, content: str) -> ComposerLockfile:
    """Un ``composer.lock`` : ``packages``, puis ``packages-dev``. Un paquet d'un dépôt ``path``,
    ou figé à une branche, est « non vérifiable ». Lève ``ParseError`` si le JSON est
    invalide."""
    return _parse_lock_once(path, content)


@functools.lru_cache(maxsize=4)
def _parse_lock_once(path: str, content: str) -> ComposerLockfile:
    """Lu une seule fois pour un même contenu. Le résultat est partagé : on ne le modifie pas."""
    data = _load_json(content)
    packages = []
    from_packagist = set()
    for section, scope in (("packages", Scope.RUNTIME), ("packages-dev", Scope.DEV)):
        entries = data.get(section)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                continue
            name = entry["name"].lower()
            version = entry.get("version")
            version = version if isinstance(version, str) else ""
            edges: list[Edge] = [
                (required.lower(), frozenset())
                for required in _object(entry, "require")
                if not is_platform(required)
            ]
            packages.append(
                LockedPackage(
                    name=name,
                    version=version,
                    dependencies=tuple(edges),
                    scope=scope,
                    unverifiable_reason=_lock_reason(entry, version),
                )
            )
            if entry.get("notification-url") == PACKAGIST_NOTIFICATION:
                from_packagist.add(name)
    lockfile = Lockfile(
        path=path, ecosystem=Ecosystem.PACKAGIST, packages=tuple(packages), graph=True
    )
    return ComposerLockfile(lockfile=lockfile, from_packagist=frozenset(from_packagist))


def _lock_reason(entry: Mapping[str, Any], version: str) -> str | None:
    """Pourquoi un paquet figé n'est pas vérifiable : un dépôt ``path``, une branche."""
    for key in ("dist", "source"):
        if _object(entry, key).get("type") == "path":
            return REASON_LOCAL
    try:
        return REASON_BRANCH if is_branch(normalize(version)) else None
    except InvalidVersion:
        return None  # « plus récente » dira qu'elle est illisible


# ---------------------------------------------------------------------------
# Un projet
# ---------------------------------------------------------------------------


def parse_project(project: Project, read_text: ReadText) -> None:
    """Lit les fichiers PHP de ``project`` et remplit ses dépendances : les directes (dans l'ordre
    du ``composer.json``) puis les transitives, et à ``project.notices`` ce qui n'a pas pu être
    lu."""
    _ProjectParser(project, read_text).run()


class _ProjectParser:
    """Lit les fichiers PHP d'un projet et relie le ``composer.json`` au ``composer.lock``."""

    def __init__(self, project: Project, read_text: ReadText) -> None:
        self.project = project
        self.read_text = read_text
        self.notices: list[Notice] = []
        self.manifest_path = next((p for p in project.manifests if _is(p, MANIFEST)), None)
        self.lock_path = next((p for p in project.lockfiles if _is(p, LOCKFILE)), None)

    def run(self) -> None:
        manifest = self._manifest()
        lock = self._lockfile()
        directs = manifest.dependencies if manifest is not None else []
        found: list[Dependency] = []
        if lock is not None:
            if manifest is not None and manifest.other_repositories:
                lock = _other_repositories(lock)
            directs, found = _link(directs, lock)
            conflicts = manifest.conflicts if manifest is not None else {}
            found = [
                dataclasses.replace(d, excluded=conflicts[d.name]) if d.name in conflicts else d
                for d in found
            ]
        found.sort(key=lambda d: (d.name, COMPOSER.sort_key(d.installed or "")))
        self.project.dependencies.extend(directs + found)
        self.project.notices.extend(self.notices)

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

    def _manifest(self) -> ComposerJson | None:
        if self.manifest_path is None:
            return None
        content = self._read(self.manifest_path)
        if content is None:
            return None
        try:
            parsed = _parse_composer_json(self.manifest_path, content)
        except ParseError as err:
            self.notices.append(Notice(file=self.manifest_path, message=str(err)))
            return None
        self.notices.extend(parsed.notices)
        return parsed

    def _lockfile(self) -> ComposerLockfile | None:
        if self.lock_path is None:
            return None
        content = self._read(self.lock_path)
        if content is None:
            return None
        try:
            return parse_composer_lock(self.lock_path, content)
        except ParseError as err:
            self.notices.append(Notice(file=self.lock_path, message=str(err)))
            return None


def _other_repositories(lock: ComposerLockfile) -> ComposerLockfile:
    """``lock``, ses paquets qui ne viennent pas de Packagist marqués non vérifiables."""
    packages = tuple(
        package
        if package.name in lock.from_packagist or package.unverifiable_reason is not None
        else dataclasses.replace(package, unverifiable_reason=REASON_OTHER_REPOSITORY)
        for package in lock.lockfile.packages
    )
    lockfile = dataclasses.replace(lock.lockfile, packages=packages)
    return ComposerLockfile(lockfile=lockfile, from_packagist=lock.from_packagist)


def _link(
    declared: list[Dependency], lock: ComposerLockfile
) -> tuple[list[Dependency], list[Dependency]]:
    """Les directes avec leur version figée, et les transitives que le projet tire du lockfile,
    leur scope suivi dans le graphe depuis les directes."""
    directs = []
    starts: list[Start] = []
    for dependency in declared:
        package = lock.package(dependency.name)
        if package is not None:
            starts.append((dependency.scope, (package.node, frozenset())))
            if dependency.unverifiable_reason is None and package.unverifiable_reason is not None:
                dependency = dataclasses.replace(
                    dependency, unverifiable_reason=package.unverifiable_reason
                )
            if package.version:
                dependency = dataclasses.replace(
                    dependency, installed=package.version, lockfile=lock.lockfile.path
                )
        directs.append(dependency)
    names = {d.name for d in declared}
    found = transitives(lock.lockfile, starts, lambda package: package.name in names)
    return directs, found


def _is(path: str, pattern: str) -> bool:
    match = match_dependency_file(path)
    return match is not None and match.ecosystem is Ecosystem.PACKAGIST and match.pattern == pattern
