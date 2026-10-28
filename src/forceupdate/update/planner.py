"""Le planificateur : pour chaque paquet à mettre à jour, les versions possibles, ce qu'il faut
toucher, et ce qui est pré-coché. Il n'écrit rien : la réécriture des manifestes est E10, celle
des lockfiles E11.

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
  dessous de la version utilisée.

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
  n'accepte pas la version visée : c'est elle qu'on réécrit ;
- une dépendance pair (npm) : sa plage s'élargit au lieu d'être remplacée.

Pour une faille, la nouvelle contrainte n'accepte plus de version concernée (``floor``).

**La sélection par défaut** (brief, décision n°12) : correctifs, mineures et corrections de
failles pré-cochés ; majeures proposées, jamais cochées d'office (« Majeure : peut demander
d'adapter le code. »). Une faille corrigée seulement par une majeure : proposée, pas cochée,
avec les deux mentions. Pour un paquet, l'option pré-cochée est, parmi celles qui ne sont pas
majeures, celle qui corrige le plus de failles, puis la plus récente.

**La sélection est une donnée** (``Selection``) : l'identifiant de chaque ``Update`` choisie et
sa version. ``select`` la calcule selon des règles (``Rules`` : les options de ``forceupdate
update``) ; l'interface la modifiera case par case.
"""

import dataclasses
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase

from forceupdate import versions
from forceupdate.advisories import Advisory, Query, Vulnerabilities
from forceupdate.checks.base import Current, current_version
from forceupdate.models import (
    Dependency,
    Ecosystem,
    Edit,
    EditKind,
    Finding,
    FindingKind,
    Gap,
    Override,
    Project,
    Report,
    Scope,
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

Selection = dict[str, str]
"""Les mises à jour choisies : l'identifiant d'une ``Update``, et la version choisie parmi ses
options. Un paquet absent n'est pas mis à jour."""

_Operations = tuple[list[Edit], str | None, str | None]
"""Ce qu'une option touche : les contraintes à réécrire, le lockfile à régénérer, et pourquoi
il faut le faire à la main s'il le faut."""

_ACTIONABLE = frozenset(
    {FindingKind.VULNERABLE, FindingKind.OUTDATED, FindingKind.YANKED, FindingKind.DEPRECATED}
)
"""Les constats qui peuvent donner une mise à jour."""


@dataclass(frozen=True, kw_only=True)
class Rules:
    """Ce que garde une sélection : les options de ``forceupdate update``."""

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


DEFAULT_RULES = Rules()


def plan(
    report: Report,
    infos: Mapping[tuple[Ecosystem, str], PackageInfo],
    vulnerabilities: Mapping[Query, Vulnerabilities],
) -> None:
    """Remplit ``updates`` de chaque projet de ``report``, d'après ses constats (déjà triés),
    ce que les registres disent des paquets (``infos``, par écosystème et nom de dépendance) et
    les failles qu'OSV connaît de chaque version (``vulnerabilities``)."""
    overrides = {project.path: project.overrides for project in report.projects}
    for project in report.projects:
        project.updates = _plan_project(project, infos, vulnerabilities, overrides)


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


def choose(update: Update, rules: Rules = DEFAULT_RULES) -> str | None:
    """La version que ``rules`` cochent pour ``update`` ; ``None`` pour aucune."""
    if not _kept(update, rules):
        return None
    scheme = versions.for_ecosystem(update.ecosystem)
    eligible = [
        option
        for option in update.options
        if option.gap is not None and option.gap.rank <= rules.level.rank and option.manual is None
    ]
    if rules.security_only:
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
) -> list[Update]:
    groups: dict[tuple[str, ...], list[Dependency]] = {}
    for dependency in project.dependencies:
        if dependency.verifiable:
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
    ) -> None:
        self.project = project
        self.dependencies = dependencies
        self.lead = dependencies[0]
        self.ecosystem = self.lead.ecosystem
        self.scheme: VersionScheme = versions.for_ecosystem(self.ecosystem)
        self.findings = findings
        self.info = info
        self.overrides = overrides
        self.currents = [current_version(d) for d in dependencies]
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
        note = self._note(reasons)
        if not options and note is None:
            return None
        update = Update(**base, options=tuple(options), note=note)
        return dataclasses.replace(update, selected=choose(update))

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
            if version is not None:
                found.setdefault(version, []).append(reason)

        fresh = [v.version for v in self.info.versions if not v.yanked and v.deprecated is None]
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
        return found

    def _security_fix(self, current: str, pool: list[str]) -> str | None:
        """La plus petite version qui corrige toutes les failles qui peuvent l'être : au moins
        la plus haute des versions corrigées, qu'aucun avis ne concerne plus ; non dépréciée
        s'il y en a une, sinon dépréciée ; jamais retirée."""
        if not self.fixable:
            return None
        assert self.info is not None
        floor = max((f.target_version or "" for f in self.fixable), key=self.scheme.sort_key)
        available = sorted(
            self.scheme.candidates(self.info.available(), current), key=self.scheme.sort_key
        )
        for choices in (pool, available):
            for version in choices:
                if self.scheme.compare(version, floor) >= 0 and not any(
                    self._affected(f, version) for f in self.fixable
                ):
                    return version
        return None

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

    def _note(self, reasons: Mapping[str, list[UpdateReason]]) -> str | None:
        unfixable = [f for f in self.vulns if f.target_version is None]
        if unfixable:
            ids = ", ".join(_main_id(f) for f in unfixable)
            malicious = any(a.malicious for f in unfixable for a in self._advisories_of(f))
            if malicious:
                return f"Code malveillant ({ids}) : retirer ce paquet, aucune version sûre connue."
            return f"Aucune version corrigée connue pour {ids}."
        if self.fixable and not any(UpdateReason.SECURITY_FIX in r for r in reasons.values()):
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
        fixes = tuple(_main_id(f) for f in self.fixable if not self._affected(f, version))
        unfixed = tuple(_main_id(f) for f in self.vulns if _main_id(f) not in fixes)
        if self.lead.direct:
            edits, lockfile, manual = self._direct_edits(version, floor=bool(fixes))
        else:
            edits, lockfile, manual = self._indirect_edits(version, floor=bool(fixes))
        if not edits and lockfile is None and manual is None:
            return None  # sans lockfile, la contrainte accepte déjà cette version : rien à faire
        warnings = []
        if gap is Gap.MAJOR:
            warnings.append(MAJOR_WARNING)
            if not self.lead.direct:
                warnings.append(INDIRECT_MAJOR_WARNING)
        elif gap is None:
            warnings.append(DOWNGRADE_WARNING)
        published = self.info.get(version)
        if published is not None and published.deprecated:
            warnings.append(f"Version dépréciée : {published.deprecated}")
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

    def _direct_edits(self, version: str, *, floor: bool) -> _Operations:
        """Les contraintes à réécrire pour monter à ``version`` : celles qui ne l'acceptent pas,
        et, sans lockfile, celles dont la borne basse est à relever."""
        edits = []
        manual = None
        for dependency, current in zip(self.dependencies, self.currents, strict=True):
            text = dependency.effective_constraint
            try:
                inside = self.scheme.satisfies(text, version)
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
        réécrite."""
        lockfile = self.lead.lockfile or self.lead.file
        override = _override(self.lead.name, self.overrides)
        if override is None:
            return [], lockfile, None
        described = f"Version forcée « {override.key} » ({override.section}, {override.file})"
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


def _override(name: str, overrides: Iterable[Override]) -> Override | None:
    """La version forcée de ``name`` : celle qui vaut pour tout l'arbre de préférence, sinon
    celle d'un paquet parent."""
    mine = [o for o in overrides if o.name == name]
    whole_tree = [o for o in mine if o.key in (name, f"**/{name}") or o.key.startswith(f"{name}@")]
    return next(iter(whole_tree or mine), None)


def _main_id(finding: Finding) -> str:
    """Le premier identifiant d'une faille : une CVE s'il y en a une."""
    return finding.identifiers[0] if finding.identifiers else finding.message
