"""Le moteur : enchaîne les étapes d'une analyse, de la source au rapport.

L'interface web et la ligne de commande l'appellent, et n'ont pas de logique métier.

- ``inventory`` : langages, projets, dépendances. Synchrone, sans réseau ;
- ``check`` : demande aux registres ce qu'ils savent de chaque paquet, et à OSV les failles
  de chaque version, et en tire les constats (``checks/``). Asynchrone : tous les paquets
  sont demandés en même temps ;
- ``analyze`` : les deux à la suite, avec l'aiguillage des registres (``routing``, E33 : les
  registres privés que déclarent le projet et la personne). C'est la coroutine que lance le
  serveur ;
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

from forceupdate import checks, config, managed, parsers, routing, versions
from forceupdate.advisories import Osv, OsvError, PackagistAdvisories, Query, Vulnerabilities
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
from forceupdate.parsers.base import REASON_WORKSPACE, ReadText
from forceupdate.parsers.lockfiles import dirname
from forceupdate.registries import AccessRefused, PackageInfo, PackageNotFound, RegistryError
from forceupdate.registries.maven import Maven
from forceupdate.routing import Clients, Route, Routing
from forceupdate.sources.base import ChosenCode, Source
from forceupdate.update import planner

EventCallback = Callable[[Event], None]

_Outcome = PackageInfo | PackageNotFound | RegistryError
_Key = tuple[Ecosystem, tuple[tuple[tuple[str, str], ...], bool], str]
"""Un paquet à demander : son écosystème, sa route (``Route.key``) et son nom normalisé."""
_Found = Vulnerabilities | OsvError
_Lifecycle = Product | ProductNotFound | EndOfLifeError


def inventory(source: Source, *, include_tests: bool = False) -> Report:
    """Lit une source : ses langages, ses projets et leurs dépendances, sans rien vérifier.

    ``include_tests`` garde aussi les projets rangés dans des dossiers de tests, de
    fixtures ou d'exemples ; sinon ils sont listés dans ``Report.ignored_manifests``.

    La configuration du projet (``forceupdate.toml``, ``[tool.forceupdate]``, E29) est lue à la
    racine de la source (``Report.config``) : ses dossiers exclus ne sont pas lus, et son
    ``include-tests`` vaut ``include_tests``.

    Ce que la source n'a pas pu lister (``Source.notices``), et un nombre de fichiers de
    dépendances au-delà du plafond, sont dits dans ``Report.notices``.

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
    notices = source.notices
    if configuration is not None:
        include_tests = include_tests or configuration.include_tests
        files = [f for f in files if not config.is_excluded_path(f.path, configuration.exclude)]
    projects, ignored = find_projects(
        (file.path for file in files), include_tests=include_tests, notices=notices
    )
    project_dirs = [project.path for project in projects]
    for project in projects:
        parsers.parse_project(project, source.read_text, project_dirs)
    return Report(
        source=source.origin,
        languages=detect_languages(files),
        projects=projects,
        ignored_manifests=ignored,
        notices=notices,
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
    if not script:
        code_parser.without_local_namespaces(project, code.path, source.is_directory)
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
    """Analyse une source : ``inventory``, l'aiguillage des registres (``routing.read`` : ceux que
    déclarent les fichiers du projet et de la personne), puis ``check``. Voir ``check`` pour
    ``http`` et ``cache``."""
    options = options or ScanOptions()
    emit = on_event or _ignore
    scanned_at = datetime.now(UTC)
    emit(Event(kind=EventKind.READING))
    report = inventory(source, include_tests=options.include_tests)
    report.scanned_at = scanned_at
    routes = routing.read(report, source.read_text)
    emit(Event(kind=EventKind.PROJECTS_FOUND, total=len(report.projects)))
    await check(
        report,
        options,
        on_event=emit,
        http=http,
        cache=cache,
        routes=routes,
        read_text=source.read_text,
    )
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
    routes: Routing | None = None,
    read_text: ReadText | None = None,
) -> None:
    """Vérifie les dépendances du rapport auprès des registres et d'OSV, et range les constats
    dans chaque projet, du plus grave au moins grave.

    ``routes`` : à quel registre demander chaque paquet (``routing``, E33) ; par défaut, au
    registre public. ``read_text`` : les fichiers de la source, pour les versions Maven gérées
    par un parent ou un BOM distant (``managed``, E34) ; sans lui, elles restent non
    vérifiables. Un paquet privé n'est jamais demandé au registre public ni à OSV : une
    remarque du projet dit que ses failles ne sont pas cherchées ; sans registre à qui le demander,
    ou si le sien refuse l'accès, son constat est « privé : non vérifié ».

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
        await _check(report, options, emit, http, cache, today, routes or Routing(), read_text)


async def _check(
    report: Report,
    options: ScanOptions,
    emit: EventCallback,
    http: HttpClient,
    cache: Cache,
    today: date | None,
    routes: Routing,
    read_text: ReadText | None = None,
) -> None:
    """``check``, une fois ``http`` et ``cache`` ouverts."""
    clients = Clients(http, cache, routes.credentials)

    def key(project: Project, dependency: Dependency) -> _Key | None:
        """La clé du paquet de ``dependency`` ; ``None`` si son écosystème n'a pas de registre."""
        registry = clients.client(dependency.ecosystem)
        if registry is None:
            return None
        route = routes.route(project, dependency)
        return dependency.ecosystem, route.key, registry.normalize(dependency.name)

    routing.apply(report, routes)
    for project in report.projects:
        project.notices.extend(routes.notices(project))
    await _resolve_imports(report, clients, routes)
    if read_text is not None:
        await managed.resolve(
            report, read_text, lambda project: _pom_fetcher(clients, routes, project)
        )
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
        unchecked = routes.route(project, dependency).unchecked
        if dependency.verifiable and unchecked is not None:
            message = f"{unchecked}."
            project.findings.append(
                Finding(kind=FindingKind.UNVERIFIABLE, message=message, dependency=dependency)
            )
        elif dependency.verifiable:
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
    audited: list[tuple[Project, Dependency, Current]] = []
    private: dict[tuple[int, str], int] = {}
    for project in report.projects:
        for dependency in project.dependencies:
            if not vulns.audited(dependency, options):
                continue
            if routes.route(project, dependency).private:
                # OSV ne connaît que les paquets publics : un homonyme n'est pas ce paquet-ci.
                where = (id(project), dependency.file)
                private[where] = private.get(where, 0) + 1
            elif (current := vulns.version_to_check(dependency)) is not None:
                audited.append((project, dependency, current))
    for project in report.projects:
        project.notices.extend(_private_notices(project, private))
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

    wanted: dict[_Key, Route] = {}
    for project, dependency in to_check:
        if (found_key := key(project, dependency)) is not None:
            wanted[found_key] = routes.route(project, dependency)
    packages = sorted(wanted)
    progress = _Progress(emit, total=len(packages) + (1 if queries else 0))
    emit(Event(kind=EventKind.CHECKING, total=progress.total))
    osv = Osv(http, cache)
    packagist = PackagistAdvisories(http, cache)
    outcomes, found, lifecycles = await asyncio.gather(
        _lookup_all(clients, {k: wanted[k] for k in packages}, progress),
        _vulnerabilities(osv, packagist, queries, progress),
        _lifecycles(EndOfLifeDate(http, cache), products),
    )
    if packagist.error is not None:
        php = {
            id(project): dependency.file
            for project, dependency, _ in reversed(audited)
            if dependency.ecosystem is Ecosystem.PACKAGIST
        }
        message = (
            f"Failles de Packagist (GitHub, FriendsOfPHP) non lues : {packagist.error} Seules "
            "celles d'OSV sont cherchées."
        )
        for project in report.projects:
            if id(project) in php:
                project.notices.append(Notice(file=php[id(project)], message=message))
    # Les versions publiées des indirectes en faille, pour choisir celle qui corrige.
    vulnerable: dict[_Key, Route] = {}
    for project, dependency, current in audited:
        if (
            dependency.ignored is None  # pas de mise à jour pour un paquet ignoré
            and isinstance(result := found[_query(dependency, current)], Vulnerabilities)
            and result.advisories
            and (found_key := key(project, dependency)) is not None
            and found_key not in outcomes
        ):
            vulnerable[found_key] = routes.route(project, dependency)
    outcomes |= await _lookup_all(clients, dict(sorted(vulnerable.items())), None)
    outcomes = _without_ignored(report, clients, key, outcomes, ignore)
    outcomes = _without_newer(report, key, outcomes, today)

    def refused(project: Project, dependency: Dependency) -> Mapping[str, Refusal]:
        found_key = key(project, dependency)
        info = outcomes.get(found_key) if found_key is not None else None
        if not isinstance(info, PackageInfo):
            return {}
        return runtimes.refused(info, runtimes.project_runtime(project, dependency.ecosystem))

    _record_lifecycles(lived, frameworks, lifecycles, today or eol.today(), refused)
    _record_findings(report, options, to_check, audited, clients, key, outcomes, found)
    infos = {
        (dependency.ecosystem, dependency.name): outcome
        for project in report.projects
        for dependency in project.dependencies
        if (found_key := key(project, dependency)) is not None
        and isinstance(outcome := outcomes.get(found_key), PackageInfo)
    }
    known = {q: v for q, v in found.items() if isinstance(v, Vulnerabilities)}
    rules = planner.rules(report.config.selection if report.config else (), options.selection)
    planner.plan(report, infos, known, rules)
    # Les versions proposées ont-elles elles-mêmes des failles ? Une requête pour toutes, sans
    # les paquets privés (OSV n'a pas à apprendre leur nom).
    private_names = {
        (dependency.ecosystem, dependency.name)
        for project in report.projects
        for dependency in project.dependencies
        if routes.route(project, dependency).private
    }
    proposed = [
        q
        for q in planner.proposed_versions(report)
        if q not in found and (q[0], q[1]) not in private_names
    ]
    found |= await packagist.merge(await osv.vulnerabilities(proposed)) if proposed else {}
    planner.audit(report, found, rules)

    dates = [o.fetched_at for o in outcomes.values() if isinstance(o, PackageInfo)]
    dates += [f.fetched_at for f in found.values() if isinstance(f, Vulnerabilities)]
    dates += [p.fetched_at for p in lifecycles.values() if isinstance(p, Product)]
    report.oldest_data = min(dates, default=None)


async def _resolve_imports(report: Report, clients: Clients, routes: Routing) -> None:
    """Rattache à son paquet chaque import dont le paquet n'est pas sûr (``parsers.code.
    candidates`` : un module Go, un paquet sous un espace de noms Python) : le premier des noms
    possibles que le registre connaît, du plus long au plus court, comme ``go mod tidy``
    (vérifié avec Go 1.27 : ``golang.org/x/text/language`` vient de ``golang.org/x/text``).
    Aucun : la dépendance est non vérifiable. Le registre muet : elle garde son nom, et sa
    vérification dira l'erreur. Deux imports du même paquet n'en font plus qu'une. Chaque nom
    est demandé là où le dit l'aiguillage (``routing``) : un module privé n'est demandé à
    personne, sa vérification dira « privé : non vérifié »."""

    async def resolve(project: Project, dependency: Dependency, names: list[str]) -> Dependency:
        registry = clients.client(dependency.ecosystem)
        if registry is None:
            return dependency
        for name in names:
            route = routes.route(project, dataclasses.replace(dependency, name=name))
            if route.unchecked is not None:
                return dependency
            try:
                await clients.package(dependency.ecosystem, route, name)
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
    resolved = await asyncio.gather(*(resolve(p, d, names) for p, _, d, names in pending))
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


def _pom_fetcher(clients: Clients, routes: Routing, project: Project) -> managed.Fetch:
    """De quoi lire le ``pom`` d'un artefact Maven pour ``project`` (``managed``) : là où
    l'aiguillage le demande (ses dépôts déclarés, puis Maven Central)."""

    async def fetch(name: str, version: str) -> str | None:
        probe = Dependency(ecosystem=Ecosystem.MAVEN, name=name, file=project.path)
        route = routes.route(project, probe)
        if route.unchecked is not None:
            raise RegistryError(route.unchecked)
        for declared in route.registries:
            registry = clients.declared(Ecosystem.MAVEN, declared)
            if isinstance(registry, Maven) and (text := await registry.pom(name, version)):
                return text
        public = clients.client(Ecosystem.MAVEN) if route.public else None
        return await public.pom(name, version) if isinstance(public, Maven) else None

    return fetch


def _without_ignored(
    report: Report,
    clients: Clients,
    key: Callable[[Project, Dependency], _Key | None],
    outcomes: dict[_Key, _Outcome],
    rules: list[config.IgnoreRule],
) -> dict[_Key, _Outcome]:
    """``outcomes``, sans les versions qu'ignorent les règles de versions (``config.
    without_ignored`` : forceupdate fait comme si elles n'étaient pas publiées), sauf celles
    qu'utilisent les projets. Chaque projet qui déclare le paquet le dit dans une remarque :
    combien de versions la règle écarte, ou qu'elle ne se lit pas pour son écosystème."""
    if all(rule.whole for rule in rules):
        return outcomes
    declared: dict[_Key, list[tuple[Project, Dependency]]] = {}
    for project in report.projects:
        for dependency in project.dependencies:
            found_key = key(project, dependency)
            if found_key is not None:
                declared.setdefault(found_key, []).append((project, dependency))
    filtered = dict(outcomes)
    for found_key, info in outcomes.items():
        users = declared.get(found_key)
        if not isinstance(info, PackageInfo) or not users:
            continue
        used = {v for _, d in users if (v := checks.current_version(d).version) is not None}
        result = config.without_ignored(info, users[0][1], rules, used)
        filtered[found_key] = result.info
        label = clients.public[found_key[0]].label
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


def _without_newer(
    report: Report,
    key: Callable[[Project, Dependency], _Key | None],
    outcomes: dict[_Key, _Outcome],
    today: date | None,
) -> dict[_Key, _Outcome]:
    """``outcomes``, sans les versions de PyPI publiées après l'``exclude-newer`` de uv (E34,
    ``Project.resolution``) : uv ne les installe pas, forceupdate ne les propose pas. Un paquet
    qu'un projet sans ce réglage utilise aussi garde toutes ses versions ; une version sans date
    est gardée. Une remarque par projet le dit, ou dit le réglage illisible."""
    cutoffs: dict[int, datetime | None] = {}
    for project in report.projects:
        written = project.resolution.get("exclude-newer")
        if written is None:
            continue
        cutoff = python.exclude_newer_cutoff(written, datetime.now(UTC))
        cutoffs[id(project)] = cutoff
        if cutoff is None:
            message = f"exclude-newer = « {written} » (uv) : illisible, rien n'est écarté."
        else:
            message = (
                f"exclude-newer = « {written} » (uv) : les versions de PyPI publiées après le "
                f"{cutoff:%d/%m/%Y à %H:%M} (UTC) ne sont pas proposées, comme uv ne les "
                "installe pas."
            )
        project.notices.append(Notice(file=project.manifests[0], message=message))
    if not any(cutoffs.values()):
        return outcomes
    users: dict[_Key, list[datetime | None]] = {}
    for project in report.projects:
        for dependency in project.dependencies:
            found_key = key(project, dependency)
            if found_key is not None and dependency.ecosystem is Ecosystem.PYPI:
                users.setdefault(found_key, []).append(cutoffs.get(id(project)))
    filtered = dict(outcomes)
    for found_key, limits in users.items():
        info = outcomes.get(found_key)
        if not isinstance(info, PackageInfo) or any(limit is None for limit in limits):
            continue
        cutoff = min(limit for limit in limits if limit is not None)
        kept = tuple(v for v in info.versions if v.published is None or v.published <= cutoff)
        if len(kept) == len(info.versions):
            continue
        scheme = versions.for_ecosystem(Ecosystem.PYPI)
        latest = scheme.latest(v.version for v in kept if not v.yanked)
        filtered[found_key] = dataclasses.replace(info, versions=kept, latest=latest)
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
    clients: Clients,
    key: Callable[[Project, Dependency], _Key | None],
    outcomes: dict[_Key, _Outcome],
    found: dict[Query, _Found],
) -> None:
    """Range dans chaque projet les constats tirés des registres et d'OSV, du plus grave au
    moins grave."""
    for project, dependency in to_check:
        found_key = key(project, dependency)
        if found_key is None:
            outcome: _Outcome = RegistryError(clients.unsupported[dependency.ecosystem])
        else:
            outcome = outcomes[found_key]
        project.findings.extend(_findings(project, dependency, outcome))
    unchecked: dict[tuple[int, str, str], int] = {}
    for project, dependency, current in audited:
        result = found[_query(dependency, current)]
        if isinstance(result, Vulnerabilities):
            found_key = key(project, dependency)
            info = outcomes.get(found_key) if found_key is not None else None
            published = info.available() if isinstance(info, PackageInfo) else ()
            project.findings.extend(vulns.check(dependency, current, result, published))
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


def _private_notices(project: Project, private: Mapping[tuple[int, str], int]) -> list[Notice]:
    """Une remarque par fichier qui a des paquets privés (``routing``) : leurs failles ne sont pas
    demandées à OSV."""
    notices = []
    for (owner, file), count in private.items():
        if owner == id(project):
            what = "le paquet privé" if count == 1 else f"les {count} paquets privés"
            message = (
                f"Failles non cherchées pour {what} : OSV ne connaît que les paquets publics (un "
                "homonyme n'est pas le même paquet), et n'a pas à apprendre leur nom."
            )
            notices.append(Notice(file=file, message=message))
    return notices


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
    osv: Osv, packagist: PackagistAdvisories, queries: list[Query], progress: _Progress
) -> dict[Query, _Found]:
    """Les failles de toutes les versions demandées, auprès d'OSV, et de Packagist pour les
    paquets PHP (E34 : les avis de FriendsOfPHP qui manquent à OSV)."""
    if not queries:
        return {}
    found = await packagist.merge(await osv.vulnerabilities(queries))
    progress.step(EventKind.VULNERABILITIES_CHECKED)
    return found


async def _lookup_all(
    clients: Clients, packages: Mapping[_Key, Route], progress: _Progress | None
) -> dict[_Key, _Outcome]:
    """Demande tous les paquets en même temps, chacun par sa route ; un événement par paquet
    vérifié, sauf sans ``progress``."""

    async def lookup(found_key: _Key, route: Route) -> PackageInfo:
        ecosystem, _, name = found_key
        try:
            return await clients.package(ecosystem, route, name)
        finally:
            if progress is not None:
                progress.step(EventKind.PACKAGE_CHECKED, ecosystem=ecosystem, name=name)

    keys = list(packages)
    results = await asyncio.gather(*(lookup(k, packages[k]) for k in keys), return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException) and not isinstance(
            result, PackageNotFound | RegistryError
        ):
            raise result
    return dict(zip(keys, results, strict=True))  # type: ignore[arg-type]


def _findings(project: Project, dependency: Dependency, outcome: _Outcome) -> list[Finding]:
    if isinstance(outcome, AccessRefused):
        message = f"Registre privé : non vérifié : {outcome}"
        return [Finding(kind=FindingKind.UNVERIFIABLE, message=message, dependency=dependency)]
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
    refused = runtimes.refused(outcome, runtime)
    return checks.check_dependency(dependency, outcome, refused, project.resolution)


def _ignore(_: Event) -> None:
    pass
