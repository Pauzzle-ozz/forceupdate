"""Ce que demandent les autres paquets (E37) : une version qu'un paquet installé n'accepte pas.

Après le plan (``planner.plan``) et le contrôle des versions proposées (``planner.audit``), chaque
option d'un paquet npm ou PyPI est confrontée aux paquets du lockfile qui le requièrent
(``Dependency.required_by``) :

- une plage que le lockfile ne dit pas (``uv.lock``, ``pnpm-lock.yaml``) est lue au registre, dans
  ce que demande la version installée de ce paquet (``Registry.requires``) ;
- une indirecte montée par le lockfile seul, par un outil qui la monte « aussi haut que le
  permet ce qui la tire » (npm, pnpm, Yarn, Poetry, PDM, pipenv) : un paquet dont la plage ne
  l'accepte pas la **retient** (``UpdateOption.held_by``) ;
- sinon (une directe, ou une version que l'outil vise exactement : uv et pip-compile, par
  ``--upgrade-package x==V``), une plage qui ne l'accepte pas la fera **refuser**
  (``UpdateOption.refused_by``) : en Python, où une seule version sert tout le projet, ou pour une
  dépendance pair de npm (pour une dépendance ordinaire, npm installe une copie à part). Sauf si
  ce paquet monte aussi : la phrase le dit ;
- npm : la version visée peut demander une dépendance pair que la version installée ne satisfait
  pas (``@types/react-dom`` 19 et ``@types/react`` 18) : refusée aussi, sauf si l'autre monte ;
- pour chacun, la plus basse version publiée de ce paquet, au-dessus de l'installée, qui
  l'accepterait (``Blocker.accepting``) : toutes les versions du document npm ; pour PyPI,
  version par version (la dernière d'abord, puis par dichotomie : une plage suit les versions).

Une option retenue ou refusée n'est jamais pré-cochée, et ses failles ne sont pas comptées
corrigées. La reprise de l'outil du lockfile (``update.lockfiles``, session 37) reste : ce qu'on
prévoit ici ne vaut que ce que disent les lockfiles et les registres.

Ce n'est pas vérifié pour les autres écosystèmes (leurs lockfiles ne disent pas les plages), ni
ce qu'une version Python demande elle-même (uv fait monter ce qu'il faut, sauf une contrainte du
projet).
"""

import asyncio
import dataclasses
import posixpath
from collections.abc import Callable, Iterable, Sequence
from typing import Protocol

from forceupdate import versions
from forceupdate.models import (
    Blocker,
    Dependency,
    Ecosystem,
    Project,
    Report,
    Requirement,
    Update,
    UpdateOption,
)
from forceupdate.registries import PackageInfo, Requires
from forceupdate.update.planner import INDIRECT_MAJOR_WARNING
from forceupdate.versions import InvalidConstraint, InvalidVersion, VersionScheme

ECOSYSTEMS = frozenset({Ecosystem.NPM, Ecosystem.PYPI})
"""Ceux dont les lockfiles disent qui requiert quoi (``Dependency.required_by``)."""

MOVES_UP = frozenset(
    {
        "package-lock.json",
        "npm-shrinkwrap.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "poetry.lock",
        "pdm.lock",
        "Pipfile.lock",
    }
)
"""Les lockfiles dont l'outil monte une indirecte aussi haut que le permet ce qui la tire
(``npm update x``, ``poetry update --lock x``…) : une plage la retient. uv et pip-compile la
visent exactement (``--upgrade-package x==V``) : une plage la fait refuser."""

_TOOLS = {
    "package-lock.json": "npm",
    "npm-shrinkwrap.json": "npm",
    "yarn.lock": "Yarn",
    "pnpm-lock.yaml": "pnpm",
    "uv.lock": "uv",
    "poetry.lock": "Poetry",
    "pdm.lock": "PDM",
    "Pipfile.lock": "pipenv",
}

MAX_LOOKUPS = 8
"""Pour PyPI, le plus de versions d'un paquet qu'on lit pour trouver celle qui accepte : la
dernière, puis la dichotomie (256 versions au-dessus de l'installée)."""


class Lookup(Protocol):
    """Ce que disent les registres, pour un projet (la route de ses paquets, E33). ``None`` quand
    on ne sait pas : paquet introuvable, registre en erreur, hors ligne sans cache."""

    async def package(
        self, project: Project, ecosystem: Ecosystem, name: str
    ) -> PackageInfo | None: ...

    async def requires(
        self, project: Project, ecosystem: Ecosystem, name: str, version: str
    ) -> Requires | None: ...


class NoLookup:
    """Aucun registre : seules comptent les plages des lockfiles."""

    async def package(self, project: Project, ecosystem: Ecosystem, name: str) -> None:
        return None

    async def requires(
        self, project: Project, ecosystem: Ecosystem, name: str, version: str
    ) -> None:
        return None


async def constrain(report: Report, lookup: Lookup) -> None:
    """Range dans chaque option de ``report`` les paquets qui la retiennent ou la feront refuser
    (``held_by``, ``refused_by``, ``blockers``), avec leur avertissement. La pré-sélection est à
    refaire ensuite (``planner.reselect``). Les registres sont demandés en même temps pour tous
    les paquets."""
    jobs = [
        _option_blockers(project, update, option, lookup)
        for project in report.projects
        for update in project.updates
        if update.ecosystem in ECOSYSTEMS
        for option in update.options
    ]
    results = iter(await asyncio.gather(*jobs))
    for project in report.projects:
        updates = []
        for update in project.updates:
            if update.ecosystem in ECOSYSTEMS:
                options = tuple(next(results) for _ in update.options)
                update = dataclasses.replace(update, options=options)
            updates.append(update)
        project.updates = updates


# ---------------------------------------------------------------------------
# Une option
# ---------------------------------------------------------------------------


async def _option_blockers(
    project: Project, update: Update, option: UpdateOption, lookup: Lookup
) -> UpdateOption:
    if option.manual is not None or option.lockfile is None:
        return option
    scheme = versions.for_ecosystem(update.ecosystem)
    npm = update.ecosystem is Ecosystem.NPM
    if npm and not update.direct and option.edits:
        return option  # une version forcée (``overrides``) passe outre les plages
    held = not update.direct and not option.edits and _moves_up(option.lockfile)
    requirements, known = await _requirements(project, update, lookup)
    refusing = [
        r
        for r in requirements
        if (held or not npm or r.peer) and _refuses(scheme, r.range, option.version)
    ]
    blockers = [
        await _blocker(project, update, option.version, r, held=held, lookup=lookup)
        for r in refusing
    ]
    if npm and not held:
        blockers += await _companions(project, update, option.version, lookup)
    warnings = list(option.warnings)
    if known and INDIRECT_MAJOR_WARNING in warnings:
        warnings.remove(INDIRECT_MAJOR_WARNING)  # on sait ce que demandent ceux qui la tirent
    if not blockers:
        return dataclasses.replace(option, warnings=tuple(warnings))
    tool = _tool(option.lockfile)
    all_held = len({(r.name, r.version) for r in refusing}) == len(
        {(r.name, r.version) for r in requirements}
    )
    warnings += [_warning(b, tool, all_held=all_held) for b in blockers]
    return dataclasses.replace(
        option,
        warnings=tuple(dict.fromkeys(warnings)),
        held_by=_names(b for b in blockers if b.held),
        refused_by=_names(b for b in blockers if not b.held),
        blockers=tuple(blockers),
    )


def _names(blockers: Iterable[Blocker]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(f"{b.name} {b.version}".strip() for b in blockers))


def _moves_up(lockfile: str) -> bool:
    return posixpath.basename(lockfile) in MOVES_UP


def _tool(lockfile: str) -> str:
    """L'outil du lockfile, dans une phrase : « uv la refusera »."""
    name = posixpath.basename(lockfile)
    if name in _TOOLS:
        return _TOOLS[name]
    return "pip-compile" if name.endswith(".txt") else "l'outil du lockfile"


def _refuses(scheme: VersionScheme, wanted: str, version: str) -> bool:
    """Vrai si la plage ``wanted`` n'accepte pas ``version`` ; une plage illisible n'en refuse
    aucune."""
    try:
        return not scheme.satisfies(wanted, version)
    except (InvalidConstraint, InvalidVersion):
        return False


async def _requirements(
    project: Project, update: Update, lookup: Lookup
) -> tuple[list[Requirement], bool]:
    """Les paquets qui requièrent ``update`` (toutes ses déclarations) et la plage de chacun,
    celles que le lockfile ne dit pas lues au registre ; et vrai si on les connaît toutes (on
    sait alors ce que demande chacun). Une plage introuvable est oubliée."""
    found = list(dict.fromkeys(r for d in update.dependencies for r in d.required_by))
    if not found:
        return [], False
    resolved = await asyncio.gather(*(_resolve(project, update, r, lookup) for r in found))
    known = [r for r in resolved if r is not None]
    return known, len(known) == len(found)


async def _resolve(
    project: Project, update: Update, requirement: Requirement, lookup: Lookup
) -> Requirement | None:
    """``requirement`` avec sa plage : celle du lockfile, sinon celle que la version installée du
    paquet demande d'après son registre ; ``None`` si on ne la connaît pas."""
    if requirement.range:
        return requirement
    requires = await lookup.requires(
        project, update.ecosystem, requirement.name, requirement.version
    )
    wanted = requires.wants(update.name) if requires is not None else None
    if wanted is None:
        return None
    return dataclasses.replace(requirement, range=wanted[0], peer=wanted[1])


async def _blocker(
    project: Project,
    update: Update,
    version: str,
    requirement: Requirement,
    *,
    held: bool,
    lookup: Lookup,
) -> Blocker:
    """Le paquet de ``requirement``, avec la plus basse de ses versions qui accepte ``version``
    d'``update``."""
    scheme = versions.for_ecosystem(update.ecosystem)

    def accepts(_: str, requires: Requires | None) -> bool | None:
        if requires is None:
            return None
        wanted = requires.wants(update.name)
        return wanted is None or not _refuses(scheme, wanted[0], version)

    accepting, checked = await _lowest(
        project, update.ecosystem, requirement.name, requirement.version, accepts, lookup
    )
    return Blocker(
        name=requirement.name,
        version=requirement.version,
        range=requirement.range,
        peer=requirement.peer,
        accepting=accepting,
        checked=checked,
        held=held,
    )


async def _companions(
    project: Project, update: Update, version: str, lookup: Lookup
) -> list[Blocker]:
    """npm : les dépendances pair de ``version`` que la version installée ne satisfait pas (aucune
    de ses copies). Un pair absent du projet n'en est pas un : npm l'installe."""
    requires = await lookup.requires(project, update.ecosystem, update.name, version)
    if requires is None:
        return []
    used = update.current_version
    before = (
        await lookup.requires(project, update.ecosystem, update.name, used)
        if used is not None
        else None
    )
    scheme = versions.for_ecosystem(update.ecosystem)
    found = []
    for name, wanted in requires.peers.items():
        if name == update.name:
            continue
        installed = _installed(project.dependencies, update.ecosystem, name)
        if not installed or any(not _refuses(scheme, wanted, v) for v in installed):
            continue
        asked = before.peers.get(name) if before is not None else None
        if asked is not None and all(_refuses(scheme, asked, v) for v in installed):
            # La version utilisée la demandait déjà : le projet vit avec (une copie à part).
            continue
        current = scheme.highest(installed) or installed[0]

        def satisfies(release: str, _: Requires | None, wanted: str = wanted) -> bool:
            return not _refuses(scheme, wanted, release)

        accepting, checked = await _lowest(
            project, update.ecosystem, name, current, satisfies, lookup, by_version=True
        )
        found.append(
            Blocker(
                name=name,
                version=current,
                range=wanted,
                peer=True,
                companion=True,
                accepting=accepting,
                checked=checked,
            )
        )
    return found


def _installed(dependencies: Sequence[Dependency], ecosystem: Ecosystem, name: str) -> list[str]:
    return list(
        dict.fromkeys(
            d.installed
            for d in dependencies
            if d.ecosystem is ecosystem and d.name == name and d.installed
        )
    )


Judge = Callable[[str, Requires | None], bool | None]
"""Dit si une version publiée convient, d'après elle-même et ce qu'elle demande (``None`` si on
ne le sait pas) ; ``None`` : on ne sait pas."""


async def _lowest(
    project: Project,
    ecosystem: Ecosystem,
    name: str,
    current: str,
    judge: Judge,
    lookup: Lookup,
    *,
    by_version: bool = False,
) -> tuple[str | None, bool]:
    """La plus basse version publiée stable de ``name``, au-dessus de ``current``, que ``judge``
    accepte, et vrai si on a pu le savoir. ``by_version`` : la version suffit à juger, ce qu'elle
    demande n'est pas lu."""
    info = await lookup.package(project, ecosystem, name)
    if info is None:
        return None, False
    scheme = versions.for_ecosystem(ecosystem)
    try:
        above = [v for v in scheme.candidates(info.available()) if scheme.compare(v, current) > 0]
    except InvalidVersion:
        return None, False
    if not above:
        return None, True

    if by_version or ecosystem is not Ecosystem.PYPI:
        # Le document du paquet dit tout (npm), ou la version suffit : dans l'ordre.
        unknown = False
        for release in above:
            published = info.get(release)
            requires = published.requires if published is not None else None
            verdict = judge(release, requires)
            if verdict:
                return release, True
            unknown = unknown or verdict is None
        return None, not unknown

    # PyPI : une requête par version ; la dernière d'abord, puis par dichotomie.
    async def verdict_of(release: str) -> bool | None:
        return judge(release, await lookup.requires(project, ecosystem, name, release))

    last = await verdict_of(above[-1])
    if last is None:
        return None, False
    if not last:
        return None, True
    low, high, asked = 0, len(above) - 1, 1
    while low < high and asked < MAX_LOOKUPS:
        middle = (low + high) // 2
        verdict = await verdict_of(above[middle])
        asked += 1
        if verdict:
            high = middle
        else:
            low = middle + 1
    return above[high], True


# ---------------------------------------------------------------------------
# Les phrases
# ---------------------------------------------------------------------------


def _warning(blocker: Blocker, tool: str, *, all_held: bool) -> str:
    """L'avertissement d'un paquet qui retient la version, ou la fera refuser."""
    pair = " (dépendance pair)" if blocker.peer else ""
    if blocker.companion:
        said = (
            f"Demande {blocker.name} {blocker.range}{pair}, et {blocker.name} {blocker.version} "
            "est installée"
        )
        if blocker.accepting is not None:
            return (
                f"{said} : {tool} la refusera, sauf si {blocker.name} monte aussi "
                f"({blocker.accepting} au moins)."
            )
        if blocker.checked:
            return (
                f"{said}, et aucune version publiée de ce paquet ne convient : {tool} la refusera."
            )
        return f"{said} : {tool} la refusera, sauf si {blocker.name} monte aussi."
    said = f"{blocker.name} {blocker.version} demande {blocker.range or '*'}{pair}"
    if blocker.held:
        outcome = (
            "le lockfile seul ne la fera pas monter"
            if all_held
            else "une de ses copies restera en dessous"
        )
        if blocker.accepting is not None:
            return (
                f"{said} : {outcome} ; monter d'abord {blocker.name} en {blocker.accepting} "
                "(la première version qui l'accepte)."
            )
        if blocker.checked:
            return f"{said} : {outcome}, et aucune de ses versions publiées ne l'accepte."
        return f"{said} : {outcome} ; monter {blocker.name} d'abord."
    if blocker.accepting is not None:
        return (
            f"{said} : {tool} la refusera, sauf si {blocker.name} monte aussi "
            f"(en {blocker.accepting}, la première version qui l'accepte)."
        )
    if blocker.checked:
        return f"{said} : {tool} la refusera, et aucune de ses versions publiées ne l'accepte."
    return f"{said} : {tool} la refusera, sauf si {blocker.name} monte aussi."
