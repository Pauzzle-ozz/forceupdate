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
import dataclasses
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime

from forceupdate import checks, config, parsers, registries
from forceupdate.advisories import Osv, OsvError, Query, Vulnerabilities
from forceupdate.checks import eol, runtimes, vulns
from forceupdate.checks.base import Current
from forceupdate.checks.runtimes import Refusal
from forceupdate.detect.code import code_ecosystem, code_language
from forceupdate.detect.languages import detect_languages
from forceupdate.detect.manifests import ecosystem_for_manifest, find_projects
from forceupdate.endoflife import EndOfLifeDate, EndOfLifeError, Product, ProductNotFound
from forceupdate.models import (
    CodeFile,
    CodeReading,
    Dependency,
    Ecosystem,
    Event,
    EventKind,
    Finding,
    FindingKind,
    Notice,
    Project,
    Report,
    Runtime,
    ScanOptions,
)
from forceupdate.net import Cache, HttpClient
from forceupdate.parsers import code as code_parser
from forceupdate.parsers import python
from forceupdate.parsers.base import REASON_WORKSPACE
from forceupdate.parsers.lockfiles import dirname
from forceupdate.registries import PackageInfo, PackageNotFound, Registry, RegistryError
from forceupdate.sources.base import ChosenCode, Source
from forceupdate.update import planner

EventCallback = Callable[[Event], None]

_Outcome = PackageInfo | PackageNotFound | RegistryError
_Found = Vulnerabilities | OsvError
_Lifecycle = Product | ProductNotFound | EndOfLifeError


def inventory(source: Source, *, include_tests: bool = False) -> Report:
    """Lit une source : ses langages, ses projets et leurs dépendances, sans rien vérifier.

    ``include_tests`` garde aussi les projets rangés dans des dossiers de tests, de
    fixtures ou d'exemples ; sinon ils sont listés dans ``Report.ignored_manifests``.

    La configuration du projet (``forceupdate.toml``, ``[tool.forceupdate]``, E29) est lue à la
    racine de la source (``Report.config``) : ses dossiers exclus ne sont pas lus, et son
    ``include-tests`` vaut ``include_tests``.

    Un fichier de code choisi seul (``Source.code_file``, E28) donne un seul projet : celui du
    bloc PEP 723 d'un script Python (son propre manifeste, comme pour ``uv run``) ; sinon celui
    trouvé en remontant les dossiers, même rangé dans un dossier de tests (il a été choisi) ;
    sinon le fichier lui-même, lu par ses imports (``parsers.code``).
    """
    configuration = config.read(source.read_text)
    code = source.code_file
    if code is not None:
        report = _code_inventory(source, code)
        report.config = configuration
        return report
    files = source.files()
    if configuration is not None:
        include_tests = include_tests or configuration.include_tests
        files = [f for f in files if not config.is_excluded_path(f.path, configuration.exclude)]
    projects, ignored = find_projects((file.path for file in files), include_tests=include_tests)
    project_dirs = [project.path for project in projects]
    for project in projects:
        parsers.parse_project(project, source.read_text, project_dirs)
    return Report(
        source=source.origin,
        languages=detect_languages(files),
        projects=projects,
        ignored_manifests=ignored,
        config=configuration,
    )


def _code_inventory(source: Source, code: ChosenCode) -> Report:
    """``inventory`` pour un fichier de code choisi seul (voir ``inventory``)."""
    language = code_language(code.path)
    ecosystem = code_ecosystem(code.path)
    content = _read_quietly(source, code.path)
    directory = dirname(code.path)
    script = python.is_script(code.path) and python.has_script_block(content or "")
    languages = detect_languages([(code.path, len((content or "").encode("utf-8")))])
    via: tuple[str, ...] = ()
    if not script and code.project is not None:
        files = source.files()
        found, _ = find_projects((file.path for file in files), include_tests=True)
        project = next((p for p in found if p.path == code.project), None)
        if project is not None:
            reading = CodeReading.PROJECT
            via = tuple(
                path
                for path in project.manifests
                if ecosystem is None or ecosystem_for_manifest(path) is ecosystem
            ) or tuple(project.manifests)
            prefix = "" if code.project == "." else f"{code.project}/"
            languages = detect_languages(f for f in files if f.path.startswith(prefix))
            parsers.parse_project(project, source.read_text, [project.path])
            return Report(
                source=source.origin,
                languages=languages,
                projects=[project],
                code=CodeFile(path=code.path, language=language, reading=reading, via=via),
            )
    lock = f"{code.path}.lock"
    project = Project(
        path=directory,
        ecosystems=[ecosystem] if ecosystem is not None else [],
        manifests=[code.path],
        lockfiles=[lock] if script and _read_quietly(source, lock) is not None else [],
    )
    parsers.parse_project(project, source.read_text, [project.path])
    reading = CodeReading.SCRIPT if script else CodeReading.IMPORTS
    return Report(
        source=source.origin,
        languages=languages,
        projects=[project],
        code=CodeFile(path=code.path, language=language, reading=reading),
    )


def _read_quietly(source: Source, path: str) -> str | None:
    try:
        return source.read_text(path)
    except ValueError:
        return None


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
    today: date | None = None,
) -> None:
    """Vérifie les dépendances du rapport auprès des registres et d'OSV, et range les constats
    dans chaque projet, du plus grave au moins grave.

    Les fins de vie (E27) : celles des runtimes de chaque projet et des frameworks parmi les
    dépendances vérifiées, d'après endoflife.date, à la date ``today`` (par défaut
    ``checks.eol.today()``, que les tests fixent). Les versions qu'un runtime du projet ne fait
    pas tourner ne sont pas proposées (``checks.runtimes``).

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

    Puis les mises à jour possibles (``planner.plan``) ; les versions qu'elles proposent sont à
    leur tour soumises à OSV, toutes en une requête (``planner.audit``).
    """
    options = options or ScanOptions()
    emit = on_event or _ignore
    report.options = options
    async with contextlib.AsyncExitStack() as stack:
        if http is None:
            http = await stack.enter_async_context(HttpClient(offline=options.offline))
        if cache is None:
            cache = Cache.default() if options.cache else Cache.disabled()
            stack.callback(cache.close)
        await _check(report, options, emit, http, cache, today)


async def _check(
    report: Report,
    options: ScanOptions,
    emit: EventCallback,
    http: HttpClient,
    cache: Cache,
    today: date | None,
) -> None:
    """``check``, une fois ``http`` et ``cache`` ouverts."""
    clients: dict[Ecosystem, Registry] = {}
    unsupported: dict[Ecosystem, str] = {}

    def client(ecosystem: Ecosystem) -> Registry | None:
        """Le client du registre de ``ecosystem``, un par analyse ; ``None`` s'il n'y en a pas."""
        if ecosystem not in clients and ecosystem not in unsupported:
            try:
                clients[ecosystem] = registries.for_ecosystem(ecosystem, http, cache)
            except LookupError as error:
                unsupported[ecosystem] = str(error)
        return clients.get(ecosystem)

    await _resolve_imports(report, client)
    ignore = config.ignore_rules(report, options)
    for project in report.projects:
        config.mark_ignored(project, ignore)
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
    lived = [
        (project, runtime)
        for project in report.projects
        for runtime in eol.selected_runtimes(project.runtimes)
    ]
    frameworks = [
        (project, dependency, product)
        for project, dependency in to_check
        if (product := eol.framework(dependency)) is not None
    ]
    products = sorted({r.product for _, r in lived} | {product for *_, product in frameworks})

    ecosystems = {dependency.ecosystem for _, dependency in to_check}
    ecosystems |= {dependency.ecosystem for _, dependency, _ in audited}
    for ecosystem in sorted(ecosystems):
        client(ecosystem)
    packages = sorted(
        {
            (dependency.ecosystem, clients[dependency.ecosystem].normalize(dependency.name))
            for _, dependency in to_check
            if dependency.ecosystem in clients
        }
    )
    progress = _Progress(emit, total=len(packages) + (1 if queries else 0))
    emit(Event(kind=EventKind.CHECKING, total=progress.total))
    osv = Osv(http, cache)
    outcomes, found, lifecycles = await asyncio.gather(
        _lookup_all(clients, packages, progress),
        _vulnerabilities(osv, queries, progress),
        _lifecycles(EndOfLifeDate(http, cache), products),
    )
    # Les versions publiées des indirectes en faille, pour choisir celle qui corrige.
    vulnerable = {
        (dependency.ecosystem, clients[dependency.ecosystem].normalize(dependency.name))
        for _, dependency, current in audited
        if dependency.ecosystem in clients
        and dependency.ignored is None  # pas de mise à jour pour un paquet ignoré
        and isinstance(result := found[_query(dependency, current)], Vulnerabilities)
        and result.advisories
    }
    outcomes |= await _lookup_all(clients, sorted(vulnerable - set(outcomes)), None)
    outcomes = _without_ignored(report, clients, outcomes, ignore)

    def refused(project: Project, dependency: Dependency) -> Mapping[str, Refusal]:
        registry = clients.get(dependency.ecosystem)
        if registry is None:
            return {}
        info = outcomes.get((dependency.ecosystem, registry.normalize(dependency.name)))
        if not isinstance(info, PackageInfo):
            return {}
        return runtimes.refused(info, runtimes.project_runtime(project, dependency.ecosystem))

    _record_lifecycles(lived, frameworks, lifecycles, today or eol.today(), refused)
    _record_findings(report, options, to_check, audited, clients, unsupported, outcomes, found)
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
    known = {q: v for q, v in found.items() if isinstance(v, Vulnerabilities)}
    rules = planner.rules(report.config.selection if report.config else (), options.selection)
    planner.plan(report, infos, known, rules)
    # Les versions proposées ont-elles elles-mêmes des failles ? Une requête pour toutes.
    proposed = [q for q in planner.proposed_versions(report) if q not in found]
    found |= await osv.vulnerabilities(proposed) if proposed else {}
    planner.audit(report, found, rules)

    dates = [o.fetched_at for o in outcomes.values() if isinstance(o, PackageInfo)]
    dates += [f.fetched_at for f in found.values() if isinstance(f, Vulnerabilities)]
    dates += [p.fetched_at for p in lifecycles.values() if isinstance(p, Product)]
    report.oldest_data = min(dates, default=None)


async def _resolve_imports(report: Report, client: Callable[[Ecosystem], Registry | None]) -> None:
    """Rattache à son paquet chaque import dont le paquet n'est pas sûr (``parsers.code.
    candidates`` : un module Go, un paquet sous un espace de noms Python) : le premier des noms
    possibles que le registre connaît, du plus long au plus court, comme ``go mod tidy``
    (vérifié avec Go 1.27 : ``golang.org/x/text/language`` vient de ``golang.org/x/text``).
    Aucun : la dépendance est non vérifiable. Le registre muet : elle garde son nom, et sa
    vérification dira l'erreur. Deux imports du même paquet n'en font plus qu'une."""

    async def resolve(dependency: Dependency, names: list[str]) -> Dependency:
        registry = client(dependency.ecosystem)
        if registry is None:
            return dependency
        for name in names:
            try:
                await registry.package(name)
            except PackageNotFound:
                continue
            except RegistryError:
                return dependency
            return dataclasses.replace(dependency, name=registry.normalize(name))
        reason = (
            f"aucun paquet de {registry.label} ne fournit « {dependency.imported} » "
            f"({', '.join(names)} : introuvables)"
        )
        return dataclasses.replace(dependency, unverifiable_reason=reason)

    pending = [
        (project, index, dependency, names)
        for project in report.projects
        for index, dependency in enumerate(project.dependencies)
        if len(names := code_parser.candidates(dependency)) > 1
    ]
    if not pending:
        return
    resolved = await asyncio.gather(*(resolve(d, names) for _, _, d, names in pending))
    for (project, index, _, _), dependency in zip(pending, resolved, strict=True):
        project.dependencies[index] = dependency
    for project in {id(project): project for project, *_ in pending}.values():
        seen: set[tuple[Ecosystem, str, str]] = set()
        kept = []
        for dependency in project.dependencies:
            key = (dependency.ecosystem, dependency.name, dependency.file)
            if dependency.imported is not None and key in seen:
                continue
            seen.add(key)
            kept.append(dependency)
        project.dependencies = kept


def _without_ignored(
    report: Report,
    clients: Mapping[Ecosystem, Registry],
    outcomes: dict[tuple[Ecosystem, str], _Outcome],
    rules: list[config.IgnoreRule],
) -> dict[tuple[Ecosystem, str], _Outcome]:
    """``outcomes``, sans les versions qu'ignorent les règles de versions (``config.
    without_ignored`` : forceupdate fait comme si elles n'étaient pas publiées), sauf celles
    qu'utilisent les projets. Chaque projet qui déclare le paquet le dit dans une remarque :
    combien de versions la règle écarte, ou qu'elle ne se lit pas pour son écosystème."""
    if all(rule.whole for rule in rules):
        return outcomes
    declared: dict[tuple[Ecosystem, str], list[tuple[Project, Dependency]]] = {}
    for project in report.projects:
        for dependency in project.dependencies:
            registry = clients.get(dependency.ecosystem)
            if registry is not None:
                key = (dependency.ecosystem, registry.normalize(dependency.name))
                declared.setdefault(key, []).append((project, dependency))
    filtered = dict(outcomes)
    for key, info in outcomes.items():
        users = declared.get(key)
        if not isinstance(info, PackageInfo) or not users:
            continue
        used = {v for _, d in users if (v := checks.current_version(d).version) is not None}
        result = config.without_ignored(info, users[0][1], rules, used)
        filtered[key] = result.info
        label = clients[key[0]].label
        said: set[tuple[int, str]] = set()
        for project, dependency in users:
            for rule, count in result.removed.items():
                if (id(project), rule) not in said:
                    said.add((id(project), rule))
                    what = "version publiée" if count == 1 else "versions publiées"
                    message = f"{rule} : {count} {what} de {dependency.name} jamais proposée"
                    message += "." if count == 1 else "s."
                    project.notices.append(Notice(file=dependency.file, message=message))
            for rule in result.unreadable:
                if (id(project), rule) not in said:
                    said.add((id(project), rule))
                    message = f"{rule} : version illisible pour {label}, rien n'est écarté."
                    project.notices.append(Notice(file=dependency.file, message=message))
    return filtered


def _record_lifecycles(
    lived: list[tuple[Project, Runtime]],
    frameworks: list[tuple[Project, Dependency, str]],
    lifecycles: dict[str, _Lifecycle],
    today: date,
    refused: Callable[[Project, Dependency], Mapping[str, Refusal]],
) -> None:
    """Range dans chaque projet les constats de fin de vie de ses runtimes, puis de ses
    frameworks : un par produit et par cycle (``checks.eol``) ; un « non concluant » quand
    endoflife.date n'a pas répondu, un par produit et par version. ``refused`` : les versions
    d'une dépendance que le runtime de son projet ne fait pas tourner."""
    seen: set[tuple[int, str, str]] = set()

    def add(project: Project, finding: Finding | None, product: str) -> None:
        if finding is None:
            return
        cycle = finding.eol.cycle if finding.eol is not None else finding.current_version or ""
        key = (id(project), product, cycle)
        if key not in seen:
            seen.add(key)
            project.findings.append(finding)

    for project, runtime in lived:
        result = lifecycles[runtime.product]
        if isinstance(result, Product):
            add(project, eol.check_runtime(runtime, result, today), runtime.product)
        else:
            label = eol.runtime_label(runtime)
            add(project, eol.unchecked(label, runtime.version, result, None), runtime.product)
    for project, dependency, product in frameworks:
        current = checks.current_version(dependency)
        result = lifecycles[product]
        if isinstance(result, Product):
            refusals = refused(project, dependency)
            finding = eol.check_framework(dependency, current, result, today, refusals)
            add(project, finding, product)
        elif current.version is not None:
            finding = eol.unchecked(dependency.name, current.version, result, dependency)
            add(project, finding, product)


async def _lifecycles(client: EndOfLifeDate, products: list[str]) -> dict[str, _Lifecycle]:
    """Les cycles de vie de tous les produits demandés, en même temps."""

    async def lookup(name: str) -> _Lifecycle:
        try:
            return await client.product(name)
        except (ProductNotFound, EndOfLifeError) as error:
            return error

    results = await asyncio.gather(*(lookup(name) for name in products))
    return dict(zip(products, results, strict=True))


def _record_findings(
    report: Report,
    options: ScanOptions,
    to_check: list[tuple[Project, Dependency]],
    audited: list[tuple[Project, Dependency, Current]],
    clients: dict[Ecosystem, Registry],
    unsupported: dict[Ecosystem, str],
    outcomes: dict[tuple[Ecosystem, str], _Outcome],
    found: dict[Query, _Found],
) -> None:
    """Range dans chaque projet les constats tirés des registres et d'OSV, du plus grave au
    moins grave."""
    for project, dependency in to_check:
        client = clients.get(dependency.ecosystem)
        if client is None:
            outcome: _Outcome = RegistryError(unsupported[dependency.ecosystem])
        else:
            outcome = outcomes[dependency.ecosystem, client.normalize(dependency.name)]
        project.findings.extend(_findings(project, dependency, outcome))
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
        project.notices.extend(_unpinned_notices(project))
        project.findings = checks.sort_findings(project.findings)


def _unpinned_notices(project: Project) -> list[Notice]:
    """Une remarque par fichier qui a des dépendances sans version fixée (``UNPINNED``) : leurs
    failles ne se vérifient pas sans version (E28)."""
    counts: dict[str, int] = {}
    for finding in project.findings:
        if finding.kind is FindingKind.UNPINNED and finding.dependency is not None:
            counts[finding.dependency.file] = counts.get(finding.dependency.file, 0) + 1
    notices = []
    for file, count in counts.items():
        what = "la dépendance" if count == 1 else f"les {count} dépendances"
        message = (
            f"Failles non vérifiables pour {what} sans version fixée : OSV juge une version. "
            "Fixer les versions (un manifeste, un lockfile, un bloc PEP 723) pour qu'elles le "
            "soient."
        )
        notices.append(Notice(file=file, message=message))
    return notices


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


def _findings(project: Project, dependency: Dependency, outcome: _Outcome) -> list[Finding]:
    if isinstance(outcome, PackageNotFound):
        message = str(outcome)
        if dependency.imported is not None:
            message = (
                f"Aucun paquet « {dependency.name} » sur le registre pour l'import "
                f"« {dependency.imported} » : un module du projet, ou un paquet qui ne porte pas "
                "le nom de son import ?"
            )
        return [Finding(kind=FindingKind.UNVERIFIABLE, message=message, dependency=dependency)]
    if isinstance(outcome, RegistryError):
        return [Finding(kind=FindingKind.INCONCLUSIVE, message=str(outcome), dependency=dependency)]
    runtime = runtimes.project_runtime(project, dependency.ecosystem)
    return checks.check_dependency(dependency, outcome, runtimes.refused(outcome, runtime))


def _ignore(_: Event) -> None:
    pass
