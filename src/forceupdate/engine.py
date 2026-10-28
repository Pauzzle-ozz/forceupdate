"""Le moteur : enchaîne les étapes d'une analyse, de la source au rapport.

L'interface web et la ligne de commande l'appellent, et n'ont pas de logique métier.

- ``inventory`` : langages, projets, dépendances. Synchrone, sans réseau ;
- ``check`` : demande aux registres ce qu'ils savent de chaque paquet, et à OSV les failles
  de chaque version, et en tire les constats (``checks/``). Asynchrone : tous les paquets
  sont demandés en même temps ;
- ``analyze`` : les deux à la suite. C'est la coroutine que lancera le serveur (E12) ;
- ``scan`` : ``analyze`` pour qui n'a pas de boucle ``asyncio`` (la ligne de commande).

**Synchrone et asynchrone (tranché à E07)** : la lecture des fichiers reste synchrone (elle
est rapide, et les parseurs le sont) ; seule la vérification est une coroutine. ``scan`` la
lance avec ``asyncio.run``, une boucle par analyse. Le serveur, qui a déjà sa boucle, attend
``analyze`` directement, avec un ``HttpClient`` et un ``Cache`` à lui ; il devra la lancer hors
de la boucle qui répond aux requêtes (E12 : un gros document npm se lit sans rendre la main).

Chaque étape émet un ``Event`` (``on_event``) : la ligne de commande en fait une barre de
progression, l'API l'enverra au navigateur.
"""

import asyncio
import contextlib
from collections.abc import Callable
from datetime import UTC, datetime

from forceupdate import checks, parsers, registries
from forceupdate.advisories import Osv, OsvError, Query, Vulnerabilities
from forceupdate.checks import vulns
from forceupdate.checks.base import Current
from forceupdate.detect.languages import detect_languages
from forceupdate.detect.manifests import find_projects
from forceupdate.models import (
    Dependency,
    Ecosystem,
    Event,
    EventKind,
    Finding,
    FindingKind,
    Notice,
    Project,
    Report,
    ScanOptions,
)
from forceupdate.net import Cache, HttpClient
from forceupdate.parsers.base import REASON_WORKSPACE
from forceupdate.registries import PackageInfo, PackageNotFound, Registry, RegistryError
from forceupdate.sources.base import Source
from forceupdate.update import planner

EventCallback = Callable[[Event], None]

_Outcome = PackageInfo | PackageNotFound | RegistryError
_Found = Vulnerabilities | OsvError


def inventory(source: Source, *, include_tests: bool = False) -> Report:
    """Lit une source : ses langages, ses projets et leurs dépendances, sans rien vérifier.

    ``include_tests`` garde aussi les projets rangés dans des dossiers de tests, de
    fixtures ou d'exemples ; sinon ils sont listés dans ``Report.ignored_manifests``.
    """
    files = source.files()
    projects, ignored = find_projects((file.path for file in files), include_tests=include_tests)
    project_dirs = [project.path for project in projects]
    for project in projects:
        parsers.parse_project(project, source.read_text, project_dirs)
    return Report(
        source=source.origin,
        languages=detect_languages(files),
        projects=projects,
        ignored_manifests=ignored,
    )


async def analyze(
    source: Source,
    options: ScanOptions | None = None,
    *,
    on_event: EventCallback | None = None,
    http: HttpClient | None = None,
    cache: Cache | None = None,
) -> Report:
    """Analyse une source : ``inventory``, puis ``check``. Voir ``check`` pour ``http`` et
    ``cache``."""
    options = options or ScanOptions()
    emit = on_event or _ignore
    scanned_at = datetime.now(UTC)
    emit(Event(kind=EventKind.READING))
    report = inventory(source, include_tests=options.include_tests)
    report.scanned_at = scanned_at
    emit(Event(kind=EventKind.PROJECTS_FOUND, total=len(report.projects)))
    await check(report, options, on_event=emit, http=http, cache=cache)
    emit(Event(kind=EventKind.FINISHED))
    return report


def scan(
    source: Source, options: ScanOptions | None = None, *, on_event: EventCallback | None = None
) -> Report:
    """``analyze``, depuis du code synchrone. Ne pas l'appeler depuis une boucle ``asyncio``
    en cours : y attendre ``analyze``."""
    return asyncio.run(analyze(source, options, on_event=on_event))


async def check(
    report: Report,
    options: ScanOptions | None = None,
    *,
    on_event: EventCallback | None = None,
    http: HttpClient | None = None,
    cache: Cache | None = None,
) -> None:
    """Vérifie les dépendances du rapport auprès des registres et d'OSV, et range les constats
    dans chaque projet, du plus grave au moins grave.

    Sont vérifiées auprès des registres les directes, plus les indirectes avec
    ``options.transitive`` ; les failles sont cherchées pour toutes, indirectes comprises
    (``checks.vulns``). Celles de développement sauf sans ``options.dev``. Chaque paquet n'est
    demandé qu'une fois, même déclaré deux fois ou dans plusieurs projets, et tous le sont en
    même temps, en même temps qu'OSV.

    ``http`` et ``cache`` : ceux de la session s'ils sont donnés (le serveur les partage entre
    ses analyses), sinon un ``HttpClient`` (hors ligne avec ``options.offline``) et un
    ``Cache`` (``Cache.disabled()`` sans ``options.cache``) créés pour l'analyse, et fermés
    après. Un paquet introuvable donne un constat « non vérifiable », une erreur du registre
    un « non concluant » ; toute autre exception est un bug, et remonte. Si OSV ne répond pas,
    une dépendance vérifiée a un constat « non concluant » ; pour les autres indirectes, une
    remarque du projet le dit.
    """
    options = options or ScanOptions()
    emit = on_event or _ignore
    report.options = options
    selected = [
        (project, dependency)
        for project in report.projects
        for dependency in project.dependencies
        if checks.selected(dependency, options)
    ]
    to_check: list[tuple[Project, Dependency]] = []
    for project, dependency in selected:
        if dependency.verifiable:
            to_check.append((project, dependency))
        elif dependency.unverifiable_reason != REASON_WORKSPACE:
            # Un membre du workspace est du code du dépôt lui-même : rien à vérifier.
            project.findings.append(
                Finding(
                    kind=FindingKind.UNVERIFIABLE,
                    message=f"Non vérifiable : {dependency.unverifiable_reason}.",
                    dependency=dependency,
                )
            )
    audited: list[tuple[Project, Dependency, Current]] = [
        (project, dependency, current)
        for project in report.projects
        for dependency in project.dependencies
        if vulns.audited(dependency, options)
        and (current := vulns.version_to_check(dependency)) is not None
    ]
    queries = sorted({_query(dependency, current) for _, dependency, current in audited})

    async with contextlib.AsyncExitStack() as stack:
        if http is None:
            http = await stack.enter_async_context(HttpClient(offline=options.offline))
        if cache is None:
            cache = Cache.default() if options.cache else Cache.disabled()
            stack.callback(cache.close)
        clients: dict[Ecosystem, Registry] = {}
        unsupported: dict[Ecosystem, str] = {}
        ecosystems = {dependency.ecosystem for _, dependency in to_check}
        ecosystems |= {dependency.ecosystem for _, dependency, _ in audited}
        for ecosystem in sorted(ecosystems):
            try:
                clients[ecosystem] = registries.for_ecosystem(ecosystem, http, cache)
            except LookupError as error:
                unsupported[ecosystem] = str(error)
        packages = sorted(
            {
                (dependency.ecosystem, clients[dependency.ecosystem].normalize(dependency.name))
                for _, dependency in to_check
                if dependency.ecosystem in clients
            }
        )
        progress = _Progress(emit, total=len(packages) + (1 if queries else 0))
        emit(Event(kind=EventKind.CHECKING, total=progress.total))
        outcomes, found = await asyncio.gather(
            _lookup_all(clients, packages, progress),
            _vulnerabilities(Osv(http, cache), queries, progress),
        )
        # Les versions publiées des indirectes en faille, pour choisir celle qui corrige.
        vulnerable = {
            (dependency.ecosystem, clients[dependency.ecosystem].normalize(dependency.name))
            for _, dependency, current in audited
            if dependency.ecosystem in clients
            and isinstance(result := found[_query(dependency, current)], Vulnerabilities)
            and result.advisories
        }
        outcomes |= await _lookup_all(clients, sorted(vulnerable - set(outcomes)), None)

    for project, dependency in to_check:
        client = clients.get(dependency.ecosystem)
        if client is None:
            outcome: _Outcome = RegistryError(unsupported[dependency.ecosystem])
        else:
            outcome = outcomes[dependency.ecosystem, client.normalize(dependency.name)]
        project.findings.extend(_findings(dependency, outcome))
    unchecked: dict[tuple[int, str, str], int] = {}
    for project, dependency, current in audited:
        result = found[_query(dependency, current)]
        if isinstance(result, Vulnerabilities):
            project.findings.extend(vulns.check(dependency, current, result))
        elif checks.selected(dependency, options):
            project.findings.append(vulns.unchecked(dependency, current, result))
        else:
            # Des centaines d'indirectes « non concluantes » noieraient le rapport : une
            # remarque par lockfile le dit à leur place.
            key = (id(project), dependency.file, str(result))
            unchecked[key] = unchecked.get(key, 0) + 1
    for project in report.projects:
        for (owner, file, error), count in unchecked.items():
            if owner == id(project):
                indirect = "dépendance indirecte" if count == 1 else "dépendances indirectes"
                message = f"Failles non vérifiées pour {count} {indirect}. {error}"
                project.notices.append(Notice(file=file, message=message))
        project.findings = checks.sort_findings(project.findings)
    infos = {
        (dependency.ecosystem, dependency.name): outcome
        for project in report.projects
        for dependency in project.dependencies
        if dependency.ecosystem in clients
        and isinstance(
            outcome := outcomes.get(
                (dependency.ecosystem, clients[dependency.ecosystem].normalize(dependency.name))
            ),
            PackageInfo,
        )
    }
    planner.plan(report, infos, {q: v for q, v in found.items() if isinstance(v, Vulnerabilities)})
    dates = [o.fetched_at for o in outcomes.values() if isinstance(o, PackageInfo)]
    dates += [f.fetched_at for f in found.values() if isinstance(f, Vulnerabilities)]
    report.oldest_data = min(dates, default=None)


def _query(dependency: Dependency, current: Current) -> Query:
    assert current.version is not None
    return dependency.ecosystem, dependency.name, current.version


class _Progress:
    """Compte les vérifications terminées (les paquets des registres, puis les failles) pour
    les événements de progression."""

    def __init__(self, emit: EventCallback, *, total: int) -> None:
        self.emit = emit
        self.total = total
        self.done = 0

    def step(
        self, kind: EventKind, *, ecosystem: Ecosystem | None = None, name: str | None = None
    ) -> None:
        self.done += 1
        self.emit(
            Event(kind=kind, done=self.done, total=self.total, ecosystem=ecosystem, name=name)
        )


async def _vulnerabilities(
    osv: Osv, queries: list[Query], progress: _Progress
) -> dict[Query, _Found]:
    """Les failles de toutes les versions demandées, auprès d'OSV."""
    if not queries:
        return {}
    found = await osv.vulnerabilities(queries)
    progress.step(EventKind.VULNERABILITIES_CHECKED)
    return found


async def _lookup_all(
    clients: dict[Ecosystem, Registry],
    packages: list[tuple[Ecosystem, str]],
    progress: _Progress | None,
) -> dict[tuple[Ecosystem, str], _Outcome]:
    """Demande tous les paquets en même temps ; un événement par paquet vérifié, sauf sans
    ``progress``."""

    async def lookup(ecosystem: Ecosystem, name: str) -> PackageInfo:
        try:
            return await clients[ecosystem].package(name)
        finally:
            if progress is not None:
                progress.step(EventKind.PACKAGE_CHECKED, ecosystem=ecosystem, name=name)

    results = await asyncio.gather(
        *(lookup(ecosystem, name) for ecosystem, name in packages), return_exceptions=True
    )
    for result in results:
        if isinstance(result, BaseException) and not isinstance(
            result, PackageNotFound | RegistryError
        ):
            raise result
    return dict(zip(packages, results, strict=True))  # type: ignore[arg-type]


def _findings(dependency: Dependency, outcome: _Outcome) -> list[Finding]:
    if isinstance(outcome, PackageNotFound):
        return [Finding(kind=FindingKind.UNVERIFIABLE, message=str(outcome), dependency=dependency)]
    if isinstance(outcome, RegistryError):
        return [Finding(kind=FindingKind.INCONCLUSIVE, message=str(outcome), dependency=dependency)]
    return checks.check_dependency(dependency, outcome)


def _ignore(_: Event) -> None:
    pass
