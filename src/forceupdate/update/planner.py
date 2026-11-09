"""Le planificateur : pour chaque paquet à mettre à jour, les versions possibles, ce qu'il faut
toucher, et ce qui est pré-coché. Il n'écrit rien : la réécriture des manifestes est dans
``update.writers``, la régénération des lockfiles dans ``update.lockfiles``.

**Les versions proposées** (``UpdateOption``), pour un paquet qui a un constat :

- le **dernier correctif** et la **dernière mineure** de la version utilisée, sans dépasser la
  dernière version du constat « plus récente » ; en 0.x, ``gap`` (E05) classe déjà en majeure
  ce qui sort de ``^`` (``0.2.3`` → ``0.3.0``) ;
- la **dernière majeure** : la cible du constat « plus récente » quand elle est majeure. Pas
  pour une indirecte, qui suit le paquet qui la tire ;
- la **correction des failles** : la plus petite version publiée qui les corrige toutes (au
  moins la plus haute des versions corrigées, et qu'aucun des avis ne concerne plus : Flask
  2.3.0 est au-dessus de 2.2.5 mais concernée), ni retirée ni dépréciée. lodash 4.17.15 :
  4.18.0 corrige tout, mais est dépréciée (« Bad release ») ; c'est 4.18.1. Une faille sans
  version corrigée (paquet malveillant, ``last_affected`` seul) n'est corrigée par aucune ;
- le **remplacement** d'une version retirée ou dépréciée (``checks.deprecated``), parfois en
  dessous de la version utilisée ;
- la **dernière version du cycle conseillé**, pour un framework en fin de vie (``checks.eol``) :
  Django 3.2 → 5.2.18 (LTS), à côté de la dernière 6.1.2. Un runtime en fin de vie n'a pas de
  mise à jour : il est signalé seulement.

Comme ``npm-pick-manifest`` (E07), les versions dépréciées ne sont proposées que faute
d'autre ; les retirées jamais ; les pré-versions seulement de la même version qu'une version
utilisée en pré-version. Une même version proposée pour plusieurs raisons ne fait qu'une
option.

**Ce qu'il faut toucher** :

- la version visée sort de la contrainte : la contrainte est réécrite dans son style
  (``update.constraints``), puis le lockfile régénéré ;
- elle y est déjà : le lockfile seul. Sans lockfile, la version utilisée est la borne basse
  (« approximative ») : on relève la borne basse ;
- une indirecte : le lockfile seul (``uv lock --upgrade-package x``, ``npm update x``), sauf
  si une version forcée (``overrides``, ``resolutions``, ``pnpm.overrides``) la fige et
  n'accepte pas la version visée : c'est elle qu'on réécrit. Une indirecte écrite dans le
  manifeste (Go : ``// indirect`` dans ``go.mod``) s'y réécrit, comme une directe ;
- une dépendance pair (npm) : sa plage s'élargit au lieu d'être remplacée ;
- une majeure publiée sous un autre nom (Go : ``…/v2``, ``VersionScheme.moved``) : proposée, à
  faire à la main, car les imports du code changent aussi ;
- une version écrite une fois pour plusieurs paquets (Maven : une propriété ; Gradle : une
  variable, une entrée ``[versions]`` du catalogue) : la réécrire les fait tous monter, un
  avertissement le dit.

Une version que le projet exclut (``exclude`` de ``go.mod``) n'est jamais proposée, ni une que son
runtime ne fait pas tourner (``checks.runtimes`` : ``engines.node``, ``require.php``…).

Pour une faille, la nouvelle contrainte n'accepte plus de version concernée (``floor``).

**La sélection par défaut** (brief, décision n°12) : correctifs, mineures et corrections de
failles pré-cochés ; majeures proposées, jamais cochées d'office (« Majeure : peut demander
d'adapter le code. »). Une faille corrigée seulement par une majeure : proposée, pas cochée,
avec les deux mentions. Pour un paquet, l'option pré-cochée est, parmi celles qui ne sont pas
majeures, celle qui corrige le plus de failles, puis la plus récente.

**Les versions proposées sont vérifiées auprès d'OSV** (``audit``, une fois le plan fait : le
moteur soumet toutes leurs versions en une requête) : une option dont la version a une faille
que la version utilisée n'a pas (``UpdateOption.introduced``) n'est jamais pré-cochée, et un
avertissement le dit.

**La sélection est une donnée** (``Selection``) : l'identifiant de chaque ``Update`` choisie et
sa version. ``select`` la calcule selon des règles (``Rules`` : les options de ``forceupdate
update``) ; l'interface la modifiera case par case.

**La sélection par défaut se règle** (E29, ``rules``) : la configuration du projet
(``[selection]`` de ``forceupdate.toml``) puis les réglages de la personne peuvent changer le
niveau pré-coché, ou ne pré-cocher que les corrections de failles, pour tous les écosystèmes ou
pour un seul. Un paquet ignoré (``Dependency.ignored``) n'a pas de mise à jour.
"""

import dataclasses
import posixpath
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any

from forceupdate import versions
from forceupdate.advisories import Advisory, OsvError, Query, Vulnerabilities
from forceupdate.checks import runtimes, vulns
from forceupdate.checks.base import Current, current_version, is_excluded
from forceupdate.models import (
    Dependency,
    Ecosystem,
    Edit,
    EditKind,
    Finding,
    FindingKind,
    Gap,
    Location,
    Notice,
    Override,
    Project,
    Report,
    Scope,
    SelectionRule,
    Update,
    UpdateOption,
    UpdateReason,
)
from forceupdate.parsers.lockfiles import dirname
from forceupdate.registries import PackageInfo
from forceupdate.update.constraints import rewrite
from forceupdate.versions import InvalidConstraint, InvalidVersion, VersionScheme

MAJOR_WARNING = "Majeure : peut demander d'adapter le code."
DOWNGRADE_WARNING = "Revient à une version plus ancienne."
INDIRECT_MAJOR_WARNING = (
    "Dépendance indirecte : le paquet qui la tire devra peut-être monter aussi."
)
REFERENCE_WARNING = (
    "NuGet ne fait pas monter une indirecte seul (il prend la plus basse version qui convient) : "
    "elle est ajoutée au projet, par une référence ou une version centrale."
)

Selection = dict[str, str]
"""Les mises à jour choisies : l'identifiant d'une ``Update``, et la version choisie parmi ses
options. Un paquet absent n'est pas mis à jour."""

_Operations = tuple[list[Edit], str | None, str | None]
"""Ce qu'une option touche : les contraintes à réécrire, le lockfile à régénérer, et pourquoi
il faut le faire à la main s'il le faut."""

_ACTIONABLE = frozenset(
    {
        FindingKind.VULNERABLE,
        FindingKind.EOL,
        FindingKind.OUTDATED,
        FindingKind.YANKED,
        FindingKind.DEPRECATED,
    }
)
"""Les constats qui peuvent donner une mise à jour."""


@dataclass(frozen=True, kw_only=True)
class Rules:
    """Ce que garde une sélection : les options de ``forceupdate update``, et la sélection par
    défaut de la configuration du projet et des réglages de la personne (``rules``, E29)."""

    level: Gap = Gap.MINOR
    """L'écart le plus grand accepté (``--level``) : ``minor`` par défaut, la décision n°12."""
    security_only: bool = False
    """Seulement les corrections de failles (``--security-only``) : pour chaque paquet, la plus
    petite version qui corrige le plus de failles."""
    include: tuple[str, ...] = ()
    """Motifs de noms de paquets à garder (``--include``, ``*`` et ``?`` permis) ; tous si
    vide."""
    exclude: tuple[str, ...] = ()
    """Motifs de noms de paquets à écarter (``--exclude``)."""
    ecosystems: frozenset[Ecosystem] = frozenset()
    """Les écosystèmes à garder (``--ecosystem``) ; tous si vide."""
    by_ecosystem: Mapping[Ecosystem, tuple[Gap, bool]] = dataclasses.field(default_factory=dict)
    """Pour un écosystème, ``level`` et ``security_only`` à sa place (``[selection.npm]``)."""

    def for_ecosystem(self, ecosystem: Ecosystem) -> tuple[Gap, bool]:
        """``level`` et ``security_only`` pour les paquets de ``ecosystem``."""
        return self.by_ecosystem.get(ecosystem, (self.level, self.security_only))


DEFAULT_RULES = Rules()


def rules(*layers: Sequence[SelectionRule], **options: Any) -> Rules:
    """Les règles d'après des sélections par défaut (``SelectionRule``), de la plus forte à la
    plus faible : la ligne de commande, puis la configuration du projet (``Report.config``),
    puis les réglages de la personne (``ScanOptions.selection``). Dans chacune, une règle d'un
    écosystème passe devant la règle générale ; un champ non dit vient de la suivante, puis des
    valeurs par défaut (``minor``, pas seulement les failles). ``options`` : les autres champs
    de ``Rules`` (``include``…)."""

    def pick(ecosystem: Ecosystem | None, name: str, default: Any) -> Any:
        for layer in layers:
            for rule in sorted(layer, key=lambda r: r.ecosystem is None):
                if rule.ecosystem in (ecosystem, None) and getattr(rule, name) is not None:
                    return getattr(rule, name)
        return default

    level, security_only = pick(None, "level", Gap.MINOR), pick(None, "security_only", False)
    by_ecosystem = {}
    for ecosystem in Ecosystem:
        own = (pick(ecosystem, "level", Gap.MINOR), pick(ecosystem, "security_only", False))
        if own != (level, security_only):
            by_ecosystem[ecosystem] = own
    return Rules(level=level, security_only=security_only, by_ecosystem=by_ecosystem, **options)


def plan(
    report: Report,
    infos: Mapping[tuple[Ecosystem, str], PackageInfo],
    vulnerabilities: Mapping[Query, Vulnerabilities],
    rules: Rules = DEFAULT_RULES,
) -> None:
    """Remplit ``updates`` de chaque projet de ``report``, d'après ses constats (déjà triés),
    ce que les registres disent des paquets (``infos``, par écosystème et nom de dépendance) et
    les failles qu'OSV connaît de chaque version (``vulnerabilities``). ``rules`` : la sélection
    par défaut (``Update.selected``). Un paquet ignoré (``Dependency.ignored``) n'en a pas."""
    overrides = {project.path: project.overrides for project in report.projects}
    shared: dict[tuple[str, Location], set[str]] = {}
    for project in report.projects:
        for dependency in project.dependencies:
            if dependency.location is not None and dependency.verifiable:
                shared.setdefault((dependency.file, dependency.location), set()).add(
                    dependency.name
                )
    for project in report.projects:
        project.updates = _plan_project(project, infos, vulnerabilities, overrides, shared, rules)


def proposed_versions(report: Report) -> list[Query]:
    """Les versions que proposent les mises à jour du rapport, à soumettre à OSV (``audit``) ;
    pas celles publiées sous un autre nom (une autre majeure d'un module Go), qu'OSV connaît
    sous ce nom-là."""
    return sorted(
        {
            (update.ecosystem, update.name, option.version)
            for project in report.projects
            for update in project.updates
            for option in update.options
            if versions.for_ecosystem(update.ecosystem).moved(update.name, option.version) is None
        }
    )


def audit(
    report: Report,
    found: Mapping[Query, Vulnerabilities | OsvError],
    rules: Rules = DEFAULT_RULES,
) -> None:
    """Range dans chaque option les failles connues de sa version que la version utilisée n'a
    pas (``UpdateOption.introduced``, avec un avertissement), d'après ce qu'OSV dit des versions
    de ``proposed_versions`` (``found``), puis refait la pré-sélection selon ``rules`` : une telle
    option n'est jamais pré-cochée.

    Une version qu'OSV n'a pas pu examiner ne change rien à son option : une remarque du projet
    le dit, une seule par erreur.
    """
    for project in report.projects:
        errors: dict[str, tuple[str, int]] = {}
        updates = []
        for update in project.updates:
            known = {
                identifier
                for finding in project.findings
                if finding.kind is FindingKind.VULNERABLE
                and finding.dependency in update.dependencies
                for identifier in finding.identifiers
            }
            options = []
            for option in update.options:
                result = found.get((update.ecosystem, update.name, option.version))
                if isinstance(result, OsvError):
                    file, count = errors.get(str(result), (update.dependencies[0].file, 0))
                    errors[str(result)] = (file, count + 1)
                elif result is not None:
                    option = _with_introduced(update, option, result, known)
                options.append(option)
            update = dataclasses.replace(update, options=tuple(options))
            updates.append(dataclasses.replace(update, selected=choose(update, rules)))
        project.updates = updates
        for error, (file, count) in errors.items():
            versions_text = "version proposée" if count == 1 else "versions proposées"
            message = f"Failles non vérifiées pour {count} {versions_text}. {error}"
            project.notices.append(Notice(file=file, message=message))


def _with_introduced(
    update: Update, option: UpdateOption, found: Vulnerabilities, known: set[str]
) -> UpdateOption:
    """``option``, avec les failles de sa version qui ne sont pas parmi celles de la version
    utilisée (``known`` : leurs identifiants)."""
    current = Current(version=option.version)
    findings = vulns.check(update.dependencies[0], current, found)
    introduced = tuple(_main_id(f) for f in findings if known.isdisjoint(f.identifiers))
    if not introduced:
        return option
    label = "Faille connue" if len(introduced) == 1 else "Failles connues"
    warning = f"{label} dans cette version : {', '.join(introduced)}."
    return dataclasses.replace(option, introduced=introduced, warnings=(*option.warnings, warning))


def select(report: Report, rules: Rules = DEFAULT_RULES) -> Selection:
    """La sélection selon ``rules`` : pour chaque mise à jour possible, la version à cocher, s'il
    y en a une. Avec les règles par défaut, ce sont les versions pré-cochées
    (``Update.selected``)."""
    selection = {}
    for project in report.projects:
        for update in project.updates:
            version = choose(update, rules)
            if version is not None:
                selection[update.id] = version
    return selection


def chosen(report: Report, selection: Selection) -> list[tuple[Project, Update, UpdateOption]]:
    """Les options choisies par ``selection``, projet par projet. Lève ``ValueError`` pour un
    identifiant ou une version qui n'existent pas dans le rapport."""
    found = []
    known = set()
    for project in report.projects:
        for update in project.updates:
            known.add(update.id)
            version = selection.get(update.id)
            if version is None:
                continue
            option = update.option(version)
            if option is None:
                raise ValueError(f"{update.name} : la version {version} n'est pas proposée.")
            found.append((project, update, option))
    unknown = sorted(set(selection) - known)
    if unknown:
        raise ValueError(f"mise à jour inconnue : {unknown[0]}")
    return found


def reselect(report: Report, rules: Rules = DEFAULT_RULES) -> None:
    """Refait la pré-sélection de chaque mise à jour selon ``rules`` (``Update.selected``) : après
    ``audit``, ou ``blockers.constrain``."""
    for project in report.projects:
        project.updates = [
            dataclasses.replace(update, selected=choose(update, rules))
            for update in project.updates
        ]


def choose(update: Update, rules: Rules = DEFAULT_RULES) -> str | None:
    """La version que ``rules`` cochent pour ``update`` ; ``None`` pour aucune. Jamais une option
    à faire à la main, ni une dont la version a une faille que la version utilisée n'a pas, ni
    une que des paquets installés retiendront ou feront refuser (``UpdateOption.held_by``,
    ``refused_by``)."""
    if not _kept(update, rules):
        return None
    scheme = versions.for_ecosystem(update.ecosystem)
    level, security_only = rules.for_ecosystem(update.ecosystem)
    eligible = [
        option
        for option in update.options
        if option.gap is not None
        and option.gap.rank <= level.rank
        and option.manual is None
        and not option.introduced
        and not option.held_by
        and not option.refused_by
    ]
    if security_only:
        eligible = [option for option in eligible if option.fixes]
        if not eligible:
            return None
        most = max(len(option.fixes) for option in eligible)
        best = [option for option in eligible if len(option.fixes) == most]
        return min(best, key=lambda option: scheme.sort_key(option.version)).version
    if not eligible:
        return None
    return max(eligible, key=lambda o: (len(o.fixes), scheme.sort_key(o.version))).version


def _kept(update: Update, rules: Rules) -> bool:
    if rules.ecosystems and update.ecosystem not in rules.ecosystems:
        return False
    name = update.name.lower()
    if rules.include and not any(fnmatchcase(name, p.lower()) for p in rules.include):
        return False
    return not any(fnmatchcase(name, p.lower()) for p in rules.exclude)


# ---------------------------------------------------------------------------
# Un projet
# ---------------------------------------------------------------------------


def _plan_project(
    project: Project,
    infos: Mapping[tuple[Ecosystem, str], PackageInfo],
    vulnerabilities: Mapping[Query, Vulnerabilities],
    overrides: Mapping[str, list[Override]],
    shared: Mapping[tuple[str, Location], set[str]],
    rules: Rules,
) -> list[Update]:
    groups: dict[tuple[str, ...], list[Dependency]] = {}
    for dependency in project.dependencies:
        if dependency.verifiable and dependency.ignored is None:
            groups.setdefault(_group_key(dependency), []).append(dependency)
    planned: dict[tuple[str, ...], Update | None] = {}
    for finding in project.findings:  # du plus grave au moins grave
        dependency = finding.dependency
        if dependency is None or finding.kind not in _ACTIONABLE:
            continue
        key = _group_key(dependency)
        if key in planned or key not in groups:
            continue
        members = groups[key]
        planned[key] = _Group(
            project=project,
            dependencies=members,
            findings=[f for f in project.findings if f.dependency in members],
            info=infos.get((dependency.ecosystem, dependency.name)),
            vulnerabilities=vulnerabilities,
            overrides=overrides.get(dirname(dependency.file), []) if not dependency.direct else [],
            shared=shared,
            rules=rules,
        ).plan()
    return [update for update in planned.values() if update is not None]


def _group_key(dependency: Dependency) -> tuple[str, ...]:
    """Une directe : toutes ses déclarations ensemble. Une indirecte : une version installée."""
    key = (dependency.ecosystem.value, dependency.name)
    return key if dependency.direct else (*key, dependency.installed or "")


class _Group:
    """Un paquet d'un projet, avec ses déclarations et ses constats."""

    def __init__(
        self,
        *,
        project: Project,
        dependencies: list[Dependency],
        findings: list[Finding],
        info: PackageInfo | None,
        vulnerabilities: Mapping[Query, Vulnerabilities],
        overrides: Sequence[Override],
        shared: Mapping[tuple[str, Location], set[str]],
        rules: Rules = DEFAULT_RULES,
    ) -> None:
        self.project = project
        self.rules = rules
        self.shared = shared
        """Les paquets de chaque emplacement de version, dans tout le rapport."""
        self.dependencies = dependencies
        self.lead = dependencies[0]
        self.ecosystem = self.lead.ecosystem
        self.scheme: VersionScheme = versions.for_ecosystem(self.ecosystem)
        self.findings = findings
        self.info = info
        self.overrides = overrides
        self.currents = [current_version(d) for d in dependencies]
        self.excluded = tuple(dict.fromkeys(c for d in dependencies for c in d.excluded))
        runtime = runtimes.project_runtime(project, self.ecosystem)
        self.refused = runtimes.refused(info, runtime) if info is not None else {}
        self.vulns = [f for f in findings if f.kind is FindingKind.VULNERABLE]
        self.fixable = [f for f in self.vulns if f.target_version is not None]
        self.advisories = _advisories(dependencies, self.currents, vulnerabilities)

    def plan(self) -> Update | None:
        current = self._current()
        if current is None:
            return None
        assert current.version is not None
        update_id = "|".join((self.project.path, *_group_key(self.lead)))
        base = {
            "id": update_id,
            "ecosystem": self.ecosystem,
            "name": self.lead.name,
            "direct": self.lead.direct,
            "dependencies": tuple(self.dependencies),
            "current_version": current.version,
            "current_is_approximate": current.approximate,
        }
        if self.info is None:
            if not self.vulns:
                return None
            note = "Versions publiées inconnues du registre : mise à jour non calculée."
            return Update(**base, note=note)
        reasons = self._versions(current.version)
        options = []
        for version in sorted(reasons, key=self.scheme.sort_key):
            option = self._option(current.version, version, reasons[version])
            if option is not None:
                options.append(option)
        note = self._note(current.version, reasons)
        if not options and note is None:
            return None
        update = Update(**base, options=tuple(options), note=note)
        return dataclasses.replace(update, selected=choose(update, self.rules))

    def _current(self) -> Current | None:
        """La version utilisée du paquet : la plus basse de ses déclarations (elles ont la même
        version installée ; sans lockfile, leurs bornes basses peuvent différer)."""
        known = [c for c in self.currents if c.version is not None]
        if not known:
            return None
        try:
            return min(known, key=lambda c: self.scheme.parse(c.version or ""))
        except InvalidVersion:  # outdated l'a déjà dit
            return None

    # -- les versions --------------------------------------------------------

    def _versions(self, current: str) -> dict[str, list[UpdateReason]]:
        """Les versions à proposer, avec leurs raisons."""
        assert self.info is not None
        found: dict[str, list[UpdateReason]] = {}

        def add(version: str | None, reason: UpdateReason) -> None:
            if version is not None and not self._excluded(version):
                found.setdefault(version, []).append(reason)

        fresh = [
            v.version
            for v in self.info.versions
            if not v.yanked and v.deprecated is None and not self._excluded(v.version)
        ]
        pool = sorted(self.scheme.candidates(fresh, current), key=self.scheme.sort_key)
        above = [v for v in pool if self.scheme.compare(v, current) > 0]
        outdated = next((f for f in self.findings if f.kind is FindingKind.OUTDATED), None)
        ceiling = None if outdated is None else outdated.target_version
        if ceiling is None and not self.lead.direct and self.vulns:
            # Une indirecte en faille, vérifiée sans --transitive : son dernier correctif et sa
            # dernière mineure, s'ils corrigent au moins une faille sans changer de majeure.
            ceiling = self.info.latest
        if ceiling is not None:
            line = [
                v
                for v in above
                if self.scheme.compare(v, ceiling) <= 0
                and self.scheme.gap(current, v) is not Gap.MAJOR
            ]
            if outdated is None:
                line = [v for v in line if any(not self._affected(f, v) for f in self.fixable)]
            patches = [v for v in line if self.scheme.gap(current, v) is Gap.PATCH]
            minors = [v for v in line if self.scheme.gap(current, v) is Gap.MINOR]
            add(patches[-1] if patches else None, UpdateReason.LATEST_PATCH)
            add(minors[-1] if minors else None, UpdateReason.LATEST_MINOR)
            if self.lead.direct and outdated is not None and outdated.gap is Gap.MAJOR:
                add(ceiling, UpdateReason.LATEST_MAJOR)
        add(self._security_fix(current, pool), UpdateReason.SECURITY_FIX)
        for finding in self.findings:
            if finding.kind in (FindingKind.YANKED, FindingKind.DEPRECATED):
                add(finding.target_version, UpdateReason.REPLACEMENT)
            elif finding.kind is FindingKind.EOL and finding.target_version in above:
                # Un framework en fin de vie : la dernière version du cycle conseillé, si elle
                # est publiée sous ce nom (pas Microsoft.AspNetCore.Http 10, qui n'existe pas).
                add(finding.target_version, UpdateReason.SUPPORTED_CYCLE)
        return found

    def _security_fix(self, current: str, pool: list[str], *, runnable: bool = True) -> str | None:
        """La plus petite version qui corrige toutes les failles qui peuvent l'être : au moins
        la plus haute des versions corrigées, qu'aucun avis ne concerne plus ; non dépréciée
        s'il y en a une, sinon dépréciée ; jamais retirée. ``runnable=False`` : même une que le
        runtime du projet ne fait pas tourner (pour le dire dans la note)."""
        if not self.fixable:
            return None
        assert self.info is not None
        floor = max((f.target_version or "" for f in self.fixable), key=self.scheme.sort_key)

        def kept(version: str) -> bool:
            if runnable:
                return not self._excluded(version)
            return not is_excluded(self.scheme, self.excluded, version)

        available = sorted(
            self.scheme.candidates([v for v in self.info.available() if kept(v)], current),
            key=self.scheme.sort_key,
        )
        for choices in (pool, available):
            for version in choices:
                if self._moved(version) is not None:
                    continue  # un autre module : ses failles ne sont pas celles-ci
                if self.scheme.compare(version, floor) >= 0 and not any(
                    self._affected(f, version) for f in self.fixable
                ):
                    return version
        return None

    def _moved(self, version: str) -> str | None:
        return self.scheme.moved(self.lead.name, version)

    def _excluded(self, version: str) -> bool:
        """Vrai si le projet écarte ``version`` (``exclude`` de ``go.mod``, ``conflict`` de
        ``composer.json``), ou si son runtime ne la fait pas tourner (``checks.runtimes``) : elle
        n'est jamais proposée."""
        return version in self.refused or is_excluded(self.scheme, self.excluded, version)

    def _affected(self, finding: Finding, version: str) -> bool:
        """Vrai si la faille ``finding`` concerne encore ``version``, d'après ses avis ; faute
        d'avis lisible, d'après sa version corrigée."""
        mine = [a for a in self._advisories_of(finding) if a.unavailable is None]
        if mine:
            return any(a.affects(self.ecosystem, self.lead.name, version) for a in mine)
        fix = finding.target_version
        return fix is None or self.scheme.compare(version, fix) < 0

    def _advisories_of(self, finding: Finding) -> list[Advisory]:
        return [a for a in self.advisories if a.id in finding.identifiers]

    def _note(self, current: str, reasons: Mapping[str, list[UpdateReason]]) -> str | None:
        unfixable = [f for f in self.vulns if f.target_version is None]
        if unfixable:
            ids = ", ".join(_main_id(f) for f in unfixable)
            malicious = any(a.malicious for f in unfixable for a in self._advisories_of(f))
            if malicious:
                return f"Code malveillant ({ids}) : retirer ce paquet, aucune version sûre connue."
            return f"Aucune version corrigée connue pour {ids}."
        if self.fixable and not any(UpdateReason.SECURITY_FIX in r for r in reasons.values()):
            blocked = self._security_fix(current, [], runnable=False) if self.refused else None
            if blocked is not None and blocked in self.refused:
                return (
                    f"La correction de toutes ses failles ({blocked}) n'est pas proposée : "
                    f"{self.refused[blocked].reason}."
                )
            return "Aucune version publiée ne corrige toutes ses failles."
        return None

    # -- une option -----------------------------------------------------------

    def _option(
        self, current: str, version: str, reasons: list[UpdateReason]
    ) -> UpdateOption | None:
        assert self.info is not None
        gap = self.scheme.gap(current, version)
        if gap is None and self.scheme.compare(version, current) == 0:
            return None
        moved = self._moved(version)
        if moved is None:
            fixes = tuple(_main_id(f) for f in self.fixable if not self._affected(f, version))
        else:
            fixes = ()  # un autre module : ses avis ne sont pas ceux-ci
        unfixed = tuple(_main_id(f) for f in self.vulns if _main_id(f) not in fixes)
        if moved is not None:
            edits, lockfile, manual = [], None, _moved_manual(self.lead.name, moved, version)
        elif self.lead.direct or _in_manifest(self.lead):
            edits, lockfile, manual = self._direct_edits(version, floor=bool(fixes))
        else:
            edits, lockfile, manual = self._indirect_edits(version, floor=bool(fixes))
        if not edits and lockfile is None and manual is None:
            return None  # sans lockfile, la contrainte accepte déjà cette version : rien à faire
        warnings = []
        if gap is Gap.MAJOR:
            warnings.append(MAJOR_WARNING)
            if not self.lead.direct:
                # Retiré quand on sait ce que demandent ceux qui la tirent (``blockers``).
                warnings.append(INDIRECT_MAJOR_WARNING)
        elif gap is None:
            warnings.append(DOWNGRADE_WARNING)
        published = self.info.get(version)
        if published is not None and published.deprecated:
            warnings.append(f"Version dépréciée : {published.deprecated}")
        if any(edit.kind is EditKind.REFERENCE for edit in edits):
            warnings.append(REFERENCE_WARNING)
        warnings.extend(self._shared_warnings(edits))
        return UpdateOption(
            version=version,
            gap=gap,
            reasons=tuple(dict.fromkeys(reasons)),
            fixes=fixes,
            unfixed=unfixed,
            edits=tuple(edits),
            lockfile=lockfile,
            manual=manual,
            warnings=tuple(warnings),
        )

    def _shared_warnings(self, edits: Iterable[Edit]) -> list[str]:
        """Une version écrite une fois pour plusieurs paquets (une propriété Maven, une variable
        Gradle, une entrée ``[versions]`` du catalogue) : ils montent ensemble, on le dit."""
        found = []
        for edit in edits:
            if edit.location is None:
                continue
            others = sorted(self.shared.get((edit.file, edit.location), set()) - {self.lead.name})
            if others:
                verb = "elle monte" if len(others) == 1 else "elles montent"
                found.append(
                    f"Version partagée avec {', '.join(others)} ({edit.file}, ligne "
                    f"{edit.location.line}) : {verb} aussi."
                )
        return found

    def _direct_edits(self, version: str, *, floor: bool) -> _Operations:
        """Les contraintes à réécrire pour monter à ``version`` : celles qui ne l'acceptent pas
        (ou dont le gestionnaire ne la prendrait pas : ``VersionScheme.reaches``), et, sans
        lockfile, celles dont la borne basse est à relever."""
        edits = []
        manual = None
        for dependency, current in zip(self.dependencies, self.currents, strict=True):
            text = dependency.effective_constraint
            try:
                inside = self.scheme.reaches(text, version)
            except (InvalidConstraint, InvalidVersion):
                manual = f"Contrainte « {text} » illisible : à réécrire à la main."
                continue
            if inside and not current.approximate:
                continue
            new = rewrite(
                self.ecosystem,
                text,
                version,
                floor=floor,
                widen=dependency.scope is Scope.PEER,
            )
            if new is None:
                manual = f"Contrainte « {text} » : style non géré, à réécrire à la main."
                continue
            if new == text:
                continue
            if dependency.manual is not None:
                manual = f"{dependency.file}, {dependency.manual}"
                continue
            catalog = dependency.resolved_constraint is not None
            if dependency.location is None and not catalog:
                manual = (
                    f"Contrainte « {text} » de {dependency.file} : emplacement inconnu, à "
                    f"réécrire à la main en « {new} »."
                )
                continue
            edits.append(
                Edit(
                    kind=EditKind.CATALOG if catalog else EditKind.DEPENDENCY,
                    file=dependency.file,
                    location=dependency.location,
                    old=text,
                    new=new,
                )
            )
        lockfile = next((d.lockfile for d in self.dependencies if d.lockfile), None)
        return edits, lockfile, manual

    def _indirect_edits(self, version: str, *, floor: bool) -> _Operations:
        """Une indirecte monte par son lockfile ; une version forcée qui ne l'accepte pas est
        réécrite. Pas avec NuGet, qui prend la plus basse version qui convient : une référence
        ajoutée au projet (E32, ``EditKind.REFERENCE``), sinon à la main."""
        if self.scheme.lowest:
            project = _msbuild_project(self.project, self.lead)
            if project is None:
                return [], None, _lowest_manual(self.lead.name, version)
            edit = Edit(kind=EditKind.REFERENCE, file=project, location=None, old="", new=version)
            return [edit], self.lead.lockfile, None
        lockfile = self.lead.lockfile or self.lead.file
        override = _override(self.lead.name, self.overrides)
        if override is None:
            return [], lockfile, None
        described = f"Version forcée « {override.key} » ({override.section}, {override.file})"
        if override.constraint.startswith("$"):
            # npm : « $minimist » renvoie à la dépendance directe de ce nom à la racine (vérifié
            # sur un vrai workspace, npm 11) ; c'est elle qui fait monter l'indirecte.
            followed = override.constraint[1:]
            return (
                [],
                lockfile,
                f"{described} : « {override.constraint} » suit la dépendance {followed} de "
                f"{override.file} ; la mettre à jour fait monter celle-ci.",
            )
        try:
            inside = self.scheme.satisfies(override.constraint, version)
        except (InvalidConstraint, InvalidVersion):
            return [], lockfile, f"{described} : « {override.constraint} », à réécrire à la main."
        if inside:
            return [], lockfile, None
        new = rewrite(self.ecosystem, override.constraint, version, floor=floor)
        if new is None or override.location is None:
            return [], lockfile, f"{described} : « {override.constraint} », à réécrire à la main."
        edit = Edit(
            kind=EditKind.OVERRIDE,
            file=override.file,
            location=override.location,
            old=override.constraint,
            new=new,
            override=override,
        )
        return [edit], lockfile, None


def _advisories(
    dependencies: Iterable[Dependency],
    currents: Iterable[Current],
    vulnerabilities: Mapping[Query, Vulnerabilities],
) -> list[Advisory]:
    """Les avis d'OSV pour les versions utilisées du paquet, sans doublon."""
    found: dict[str, Advisory] = {}
    for dependency, current in zip(dependencies, currents, strict=True):
        if current.version is None:
            continue
        query = (dependency.ecosystem, dependency.name, current.version)
        result = vulnerabilities.get(query)
        if result is not None:
            for advisory in result.advisories:
                found.setdefault(advisory.id, advisory)
    return list(found.values())


def _in_manifest(dependency: Dependency) -> bool:
    """Vrai pour une indirecte écrite dans un manifeste, où elle se réécrit : Go la note
    ``// indirect`` dans ``go.mod`` (ou la fige par un ``replace`` de ``go.work``). Celle d'un
    lockfile (un ``.txt`` compilé a aussi des emplacements) se met à jour par son outil."""
    return dependency.file != dependency.lockfile


def _msbuild_project(project: Project, dependency: Dependency) -> str | None:
    """Le projet MSBuild (``.csproj``…) dont ``dependency`` est une indirecte : celui du dossier
    de son lockfile ; ``None`` s'il n'y en a pas un seul."""
    if dependency.lockfile is None:
        return None
    found = [
        manifest
        for manifest in project.manifests
        if dirname(manifest) == dirname(dependency.lockfile)
        and posixpath.splitext(manifest)[1].lower() in (".csproj", ".fsproj", ".vbproj")
    ]
    return found[0] if len(found) == 1 else None


def _lowest_manual(name: str, version: str) -> str:
    """Pourquoi une indirecte NuGet ne monte pas seule, et comment faire."""
    return (
        "NuGet prend la plus basse version qui convient : régénérer le lockfile ne fait pas "
        "monter une indirecte. L'ajouter au projet : "
        f'<PackageReference Include="{name}" Version="{version}" /> (gestion centrale : sa '
        "<PackageVersion>, et la référence sans version)."
    )


def _moved_manual(name: str, moved: str, version: str) -> str:
    """Pourquoi une majeure publiée sous un autre nom ne s'applique pas seule, et comment faire."""
    return (
        f"Majeure publiée sous un autre module ({moved}) : les imports de {name} changent aussi "
        f"dans le code. go get {moved}@{version}, puis remplacer les imports."
    )


def _override(name: str, overrides: Iterable[Override]) -> Override | None:
    """La version forcée de ``name`` : celle qui vaut pour tout l'arbre de préférence, sinon
    celle d'un paquet parent."""
    mine = [o for o in overrides if o.name == name]
    whole_tree = [o for o in mine if o.key in (name, f"**/{name}") or o.key.startswith(f"{name}@")]
    return next(iter(whole_tree or mine), None)


def _main_id(finding: Finding) -> str:
    """Le premier identifiant d'une faille : une CVE s'il y en a une."""
    return finding.identifiers[0] if finding.identifiers else finding.message
