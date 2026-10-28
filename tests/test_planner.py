"""Le planificateur : les mises à jour possibles de chaque paquet, ce qu'elles touchent, et la
sélection par défaut (brief, décision n°12).

Les constats viennent des vrais contrôles (``checks``, ``checks.vulns``), sur des versions
publiées et des avis d'OSV écrits à la main."""

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

import pytest

from forceupdate import checks, versions
from forceupdate.advisories import Advisory, Affected, AffectedRange, OsvError, Vulnerabilities
from forceupdate.checks import vulns
from forceupdate.models import (
    Dependency,
    Ecosystem,
    EditKind,
    Gap,
    Location,
    Override,
    Project,
    Report,
    Scope,
    Severity,
    Update,
    UpdateReason,
)
from forceupdate.registries import PackageInfo, PackageVersion
from forceupdate.update import planner
from forceupdate.update.planner import (
    DOWNGRADE_WARNING,
    INDIRECT_MAJOR_WARNING,
    MAJOR_WARNING,
    Rules,
)

NPM = Ecosystem.NPM
PYPI = Ecosystem.PYPI
PATCH, MINOR, MAJOR = Gap.PATCH, Gap.MINOR, Gap.MAJOR
NOW = datetime(2026, 10, 28, tzinfo=UTC)
VERSIONS = ["1.0.0", "1.0.1", "1.0.2", "1.1.0", "1.2.0", "1.2.1", "2.0.0", "2.1.0"]

_MISSING = object()


def info(
    name: str,
    published: Sequence[str],
    *,
    ecosystem: Ecosystem = NPM,
    deprecated: dict[str, str] | None = None,
    yanked: Iterable[str] = (),
) -> PackageInfo:
    """Ce que le registre dit de ``name`` : ``published`` dans l'ordre, la dernière stable non
    retirée comme ``latest``."""
    deprecated = deprecated or {}
    yanked = set(yanked)
    scheme = versions.for_ecosystem(ecosystem)
    latest = scheme.latest(v for v in published if v not in yanked)
    return PackageInfo(
        ecosystem=ecosystem,
        name=name,
        versions=tuple(
            PackageVersion(version=v, deprecated=deprecated.get(v), yanked=v in yanked)
            for v in published
        ),
        latest=latest,
        tags={"latest": latest} if ecosystem is NPM and latest else {},
        fetched_at=NOW,
    )


def dep(
    name: str,
    constraint: str,
    installed: str | None = None,
    *,
    ecosystem: Ecosystem = NPM,
    direct: bool = True,
    scope: Scope = Scope.RUNTIME,
    file: str | None = None,
    lockfile: object = _MISSING,
    location: object = _MISSING,
    resolved: str | None = None,
) -> Dependency:
    """Une dépendance ; sa contrainte écrite ligne 1, colonne 10 de son manifeste."""
    npm = ecosystem is NPM
    if file is None:
        file = ("package.json" if npm else "pyproject.toml") if direct else _lock(ecosystem)
    if lockfile is _MISSING:
        lockfile = _lock(ecosystem) if installed else None
    if location is _MISSING:
        location = Location(line=1, column=10, end_column=10 + len(constraint)) if direct else None
    return Dependency(
        ecosystem=ecosystem,
        name=name,
        constraint=constraint,
        resolved_constraint=resolved,
        installed=installed,
        lockfile=lockfile,  # type: ignore[arg-type]
        direct=direct,
        scope=scope,
        file=file,
        location=location,  # type: ignore[arg-type]
    )


def _lock(ecosystem: Ecosystem) -> str:
    return "package-lock.json" if ecosystem is NPM else "uv.lock"


def advisory(
    vuln_id: str,
    name: str,
    *events: tuple[str, str],
    ecosystem: Ecosystem = NPM,
    malicious: bool = False,
) -> Advisory:
    """Un avis d'OSV : ``("introduced", "0"), ("fixed", "1.0.1")``…"""
    return Advisory(
        id=vuln_id,
        aliases=(f"CVE-{vuln_id}",),
        summary=f"Faille {vuln_id}",
        severity=Severity.HIGH,
        malicious=malicious,
        affected=(
            Affected(
                ecosystem=ecosystem.value,
                name=name,
                ranges=(AffectedRange(type="ECOSYSTEM", events=events),),
            ),
        ),
    )


def plan(
    *dependencies: Dependency,
    infos: Iterable[PackageInfo] = (),
    advisories: Iterable[Advisory] = (),
    overrides: Iterable[Override] = (),
) -> Project:
    """Le projet de ``dependencies``, vérifié comme le fait le moteur, puis planifié."""
    project = Project(path=".", dependencies=list(dependencies), overrides=list(overrides))
    by_name = {(i.ecosystem, i.name): i for i in infos}
    advisories = list(advisories)
    found = {}
    for dependency in dependencies:
        known = by_name.get((dependency.ecosystem, dependency.name))
        if dependency.direct and known is not None:
            project.findings += checks.check_dependency(dependency, known)
        current = vulns.version_to_check(dependency)
        if current is None or current.version is None:
            continue
        mine = tuple(
            a
            for a in advisories
            if a.affects(dependency.ecosystem, dependency.name, current.version)
        )
        result = Vulnerabilities(advisories=mine, fetched_at=NOW)
        found[(dependency.ecosystem, dependency.name, current.version)] = result
        project.findings += vulns.check(dependency, current, result)
    project.findings = checks.sort_findings(project.findings)
    planner.plan(Report(source=".", projects=[project]), by_name, found)
    return project


def single(project: Project) -> Update:
    (update,) = project.updates
    return update


def options(update: Update) -> list[tuple[str, Gap | None]]:
    return [(option.version, option.gap) for option in update.options]


# ---------------------------------------------------------------------------
# Les versions proposées, et celle qui est pré-cochée
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("installed", "published", "expected", "selected"),
    [
        # Correctifs et mineures pré-cochés, la plus récente l'emporte ; majeure proposée.
        ("1.0.0", VERSIONS, [("1.0.2", PATCH), ("1.2.1", MINOR), ("2.1.0", MAJOR)], "1.2.1"),
        ("1.1.0", VERSIONS, [("1.2.1", MINOR), ("2.1.0", MAJOR)], "1.2.1"),
        ("1.2.0", VERSIONS, [("1.2.1", PATCH), ("2.1.0", MAJOR)], "1.2.1"),
        # Seulement une majeure : proposée, jamais cochée d'office.
        ("1.2.1", VERSIONS, [("2.1.0", MAJOR)], None),
        ("2.1.0", VERSIONS, [], None),
        # En 0.x, ce qui sort de ^ est une majeure (E05).
        ("0.2.3", ["0.2.3", "0.2.5", "0.3.0"], [("0.2.5", PATCH), ("0.3.0", MAJOR)], "0.2.5"),
        ("0.0.3", ["0.0.3", "0.0.4"], [("0.0.4", MAJOR)], None),
        # Les pré-versions ne sont pas proposées.
        ("1.0.0", ["1.0.0", "1.0.1", "1.1.0-beta.1"], [("1.0.1", PATCH)], "1.0.1"),
    ],
)
@pytest.mark.parametrize("ecosystem", [NPM, PYPI])
def test_default_selection(
    ecosystem: Ecosystem,
    installed: str,
    published: list[str],
    expected: list[tuple[str, Gap]],
    selected: str | None,
) -> None:
    if ecosystem is PYPI:
        published = [v.replace("-beta.", "b") for v in published]
    project = plan(
        dep("pkg", f">={installed}", installed, ecosystem=ecosystem),
        infos=[info("pkg", published, ecosystem=ecosystem)],
    )
    if not expected:
        assert project.updates == []
        return
    update = single(project)
    assert options(update) == expected
    assert update.selected == selected
    assert planner.select(Report(source=".", projects=[project])) == (
        {update.id: selected} if selected else {}
    )
    for option in update.options:
        assert (MAJOR_WARNING in option.warnings) is (option.gap is MAJOR)


def test_reasons_and_identifiers() -> None:
    project = plan(dep("pkg", "^1.0.0", "1.0.0"), infos=[info("pkg", VERSIONS)])
    update = single(project)
    assert update.id == ".|npm|pkg"
    assert update.name == "pkg"
    assert update.direct
    assert update.current_version == "1.0.0"
    assert [o.reasons for o in update.options] == [
        (UpdateReason.LATEST_PATCH,),
        (UpdateReason.LATEST_MINOR,),
        (UpdateReason.LATEST_MAJOR,),
    ]
    assert update.option("1.2.1") is update.options[1]
    assert update.option("9.9.9") is None


def test_deprecated_versions_are_avoided() -> None:
    """Comme npm-pick-manifest : une version dépréciée n'est proposée que faute d'autre."""
    published = ["1.0.0", "1.0.1", "1.0.2", "1.1.0", "1.1.1"]
    project = plan(
        dep("pkg", "^1.0.0", "1.0.0"),
        infos=[info("pkg", published, deprecated={"1.0.2": "cassée", "1.1.1": "cassée"})],
    )
    assert options(single(project)) == [("1.0.1", PATCH), ("1.1.0", MINOR)]


# ---------------------------------------------------------------------------
# Failles
# ---------------------------------------------------------------------------


def test_a_vulnerability_fixed_by_a_patch() -> None:
    project = plan(
        dep("pkg", "^1.0.0", "1.0.0"),
        infos=[info("pkg", VERSIONS)],
        advisories=[advisory("A", "pkg", ("introduced", "0"), ("fixed", "1.0.1"))],
    )
    update = single(project)
    assert options(update) == [
        ("1.0.1", PATCH),
        ("1.0.2", PATCH),
        ("1.2.1", MINOR),
        ("2.1.0", MAJOR),
    ]
    fix = update.options[0]
    assert fix.reasons == (UpdateReason.SECURITY_FIX,)
    assert fix.fixes == ("CVE-A",)
    assert fix.unfixed == ()
    # Parmi celles qui corrigent autant, la plus récente qui n'est pas majeure.
    assert update.selected == "1.2.1"


def test_a_vulnerability_fixed_only_by_a_major() -> None:
    """Proposée, pas cochée, avec les deux mentions : elle corrige, et elle est majeure."""
    project = plan(
        dep("pkg", "^1.2.0", "1.2.0"),
        infos=[info("pkg", ["1.2.0", "1.2.1", "1.3.0", "2.0.0", "2.1.0"])],
        advisories=[advisory("A", "pkg", ("introduced", "0"), ("fixed", "2.0.0"))],
    )
    update = single(project)
    assert options(update) == [
        ("1.2.1", PATCH),
        ("1.3.0", MINOR),
        ("2.0.0", MAJOR),
        ("2.1.0", MAJOR),
    ]
    security = update.option("2.0.0")
    assert security is not None
    assert security.reasons == (UpdateReason.SECURITY_FIX,)
    assert security.fixes == ("CVE-A",)
    assert security.warnings == (MAJOR_WARNING,)
    assert update.option("1.3.0").unfixed == ("CVE-A",)  # type: ignore[union-attr]
    assert update.selected == "1.3.0"


def test_lodash_skips_the_deprecated_fix() -> None:
    """4.18.0 corrige tout mais est dépréciée (« Bad release ») : c'est 4.18.1."""
    published = ["4.17.15", "4.17.19", "4.17.21", "4.18.0", "4.18.1"]
    project = plan(
        dep("lodash", "4.17.15", "4.17.15"),
        infos=[info("lodash", published, deprecated={"4.18.0": "Bad release"})],
        advisories=[
            advisory("A", "lodash", ("introduced", "0"), ("fixed", "4.17.19")),
            advisory("B", "lodash", ("introduced", "0"), ("fixed", "4.17.21")),
            advisory("C", "lodash", ("introduced", "0"), ("fixed", "4.18.0")),
        ],
    )
    update = single(project)
    assert options(update) == [("4.17.21", PATCH), ("4.18.1", MINOR)]
    assert update.options[0].fixes == ("CVE-A", "CVE-B")
    assert update.options[0].unfixed == ("CVE-C",)
    assert update.options[1].reasons == (UpdateReason.LATEST_MINOR, UpdateReason.SECURITY_FIX)
    assert len(update.options[1].fixes) == 3
    assert update.selected == "4.18.1"


def test_the_fix_of_every_branch() -> None:
    """Deux branches corrigées (Flask : 2.2.5, et 2.3.2 pour 2.3.x) : 2.3.0 est au-dessus de
    la plus haute version corrigée, mais encore concernée."""
    project = plan(
        dep("flask", "==2.0.0", "2.0.0", ecosystem=PYPI),
        infos=[info("flask", ["2.0.0", "2.2.5", "2.3.0", "2.3.1", "2.3.2"], ecosystem=PYPI)],
        advisories=[
            advisory(
                "A",
                "flask",
                ("introduced", "0"),
                ("fixed", "2.2.5"),
                ("introduced", "2.3.0"),
                ("fixed", "2.3.2"),
                ecosystem=PYPI,
            ),
            advisory("B", "flask", ("introduced", "0"), ("fixed", "2.3.0"), ecosystem=PYPI),
        ],
    )
    update = single(project)
    security = [o for o in update.options if UpdateReason.SECURITY_FIX in o.reasons]
    assert [o.version for o in security] == ["2.3.2"]
    assert update.option("2.3.2").edits[0].new == "==2.3.2"  # type: ignore[union-attr]


def test_a_malicious_package() -> None:
    project = plan(
        dep("crossenv", "1.0.0", "1.0.0"),
        infos=[info("crossenv", ["1.0.0"])],
        advisories=[advisory("M", "crossenv", ("introduced", "0"), malicious=True)],
    )
    update = single(project)
    assert update.options == ()
    assert update.selected is None
    assert (
        update.note == "Code malveillant (CVE-M) : retirer ce paquet, aucune version sûre connue."
    )


def test_a_vulnerability_without_fix() -> None:
    project = plan(
        dep("pkg", "^1.0.0", "1.0.0"),
        infos=[info("pkg", ["1.0.0", "1.0.1"])],
        advisories=[advisory("A", "pkg", ("introduced", "0"), ("last_affected", "1.0.1"))],
    )
    update = single(project)
    assert options(update) == [("1.0.1", PATCH)]
    assert update.options[0].unfixed == ("CVE-A",)
    assert update.note == "Aucune version corrigée connue pour CVE-A."


def test_a_fix_that_is_not_published() -> None:
    project = plan(
        dep("pkg", "^1.0.0", "1.0.0"),
        infos=[info("pkg", ["1.0.0", "1.0.1"])],
        advisories=[advisory("A", "pkg", ("introduced", "0"), ("fixed", "1.0.5"))],
    )
    update = single(project)
    assert update.note == "Aucune version publiée ne corrige toutes ses failles."


def test_a_fix_only_in_a_deprecated_version() -> None:
    project = plan(
        dep("pkg", "1.0.0", "1.0.0"),
        infos=[info("pkg", ["1.0.0", "1.0.1"], deprecated={"1.0.1": "Ne plus utiliser"})],
        advisories=[advisory("A", "pkg", ("introduced", "0"), ("fixed", "1.0.1"))],
    )
    option = single(project).option("1.0.1")
    assert option is not None
    assert option.fixes == ("CVE-A",)
    assert "Version dépréciée : Ne plus utiliser" in option.warnings


def test_without_published_versions() -> None:
    """Le registre n'a pas répondu, OSV si : on le dit au lieu de proposer une version."""
    project = plan(
        dep("pkg", "^1.0.0", "1.0.0"),
        advisories=[advisory("A", "pkg", ("introduced", "0"), ("fixed", "1.0.1"))],
    )
    update = single(project)
    assert update.options == ()
    assert update.note == ("Versions publiées inconnues du registre : mise à jour non calculée.")


# ---------------------------------------------------------------------------
# Ce que les mises à jour touchent
# ---------------------------------------------------------------------------


def test_inside_the_constraint_only_the_lockfile() -> None:
    update = single(plan(dep("pkg", "^1.0.0", "1.0.0"), infos=[info("pkg", VERSIONS)]))
    minor = update.option("1.2.1")
    assert minor is not None
    assert minor.edits == ()
    assert minor.lockfile == "package-lock.json"
    major = update.option("2.1.0")
    assert major is not None
    (edit,) = major.edits
    assert (edit.kind, edit.file, edit.old, edit.new) == (
        EditKind.DEPENDENCY,
        "package.json",
        "^1.0.0",
        "^2.1.0",
    )
    assert edit.location == Location(line=1, column=10, end_column=16)
    assert major.lockfile == "package-lock.json"


@pytest.mark.parametrize(
    ("ecosystem", "constraint", "expected"),
    [
        (NPM, "1.0.0", {"1.0.2": "1.0.2", "1.2.1": "1.2.1", "2.1.0": "2.1.0"}),
        (NPM, "~1.0.0", {"1.0.2": None, "1.2.1": "~1.2.1", "2.1.0": "~2.1.0"}),
        (NPM, "^1.0.0", {"1.0.2": None, "1.2.1": None, "2.1.0": "^2.1.0"}),
        (NPM, ">=1.0.0 <2.0.0", {"1.0.2": None, "1.2.1": None, "2.1.0": ">=2.1.0 <3.0.0"}),
        (NPM, "1.x", {"1.0.2": None, "1.2.1": None, "2.1.0": "2.x"}),
        (PYPI, "==1.0.0", {"1.0.2": "==1.0.2", "1.2.1": "==1.2.1", "2.1.0": "==2.1.0"}),
        (PYPI, "~=1.0.0", {"1.0.2": None, "1.2.1": "~=1.2.1", "2.1.0": "~=2.1.0"}),
        (PYPI, "~=1.0", {"1.0.2": None, "1.2.1": None, "2.1.0": "~=2.1"}),
        (PYPI, ">=1.0,<2", {"1.0.2": None, "1.2.1": None, "2.1.0": ">=2.1,<3"}),
        (PYPI, "^1.0", {"1.0.2": None, "1.2.1": None, "2.1.0": "^2.1"}),
        (PYPI, "1.0.0", {"1.0.2": "1.0.2", "1.2.1": "1.2.1", "2.1.0": "2.1.0"}),
    ],
)
def test_each_constraint_style_with_a_lockfile(
    ecosystem: Ecosystem, constraint: str, expected: dict[str, str | None]
) -> None:
    """Avec un lockfile : la contrainte n'est réécrite (dans son style) que si elle n'accepte
    pas la version visée ; sinon le lockfile seul."""
    update = single(
        plan(
            dep("pkg", constraint, "1.0.0", ecosystem=ecosystem),
            infos=[info("pkg", VERSIONS, ecosystem=ecosystem)],
        )
    )
    found = {o.version: (o.edits[0].new if o.edits else None) for o in update.options}
    assert found == expected
    assert all(o.lockfile == _lock(ecosystem) for o in update.options)


@pytest.mark.parametrize(
    ("ecosystem", "constraint", "current", "expected"),
    [
        (NPM, "^1.0.0", "1.0.0", {"1.0.2": "^1.0.2", "1.2.1": "^1.2.1", "2.1.0": "^2.1.0"}),
        (NPM, ">=1.0.0", "1.0.0", {"1.0.2": ">=1.0.2", "1.2.1": ">=1.2.1", "2.1.0": ">=2.1.0"}),
        (PYPI, ">=1.0", "1.0", {"1.0.2": ">=1.0.2", "1.2.1": ">=1.2.1", "2.1.0": ">=2.1"}),
        (PYPI, "~=1.0", "1.0", {"1.2.1": "~=1.2", "2.1.0": "~=2.1"}),
    ],
)
def test_without_lockfile_the_lower_bound_is_raised(
    ecosystem: Ecosystem, constraint: str, current: str, expected: dict[str, str]
) -> None:
    """Sans lockfile, la version utilisée est la borne basse (« approximative ») : monter,
    c'est relever la borne basse. ``~=1.0`` garde sa précision : son dernier correctif ne
    changerait rien, il n'est pas proposé."""
    update = single(
        plan(
            dep("pkg", constraint, ecosystem=ecosystem),
            infos=[info("pkg", VERSIONS, ecosystem=ecosystem)],
        )
    )
    assert update.current_version == current
    assert update.current_is_approximate
    assert {o.version: o.edits[0].new for o in update.options} == expected
    assert all(o.lockfile is None for o in update.options)


def test_a_possible_vulnerability_raises_the_lower_bound_above_the_fix() -> None:
    """« Faille possible » (borne basse, sans lockfile) : la nouvelle contrainte n'accepte plus
    la version concernée."""
    project = plan(
        dep("flask", "~=0.12", ecosystem=PYPI),
        infos=[info("flask", ["0.12", "0.12.3", "0.12.5", "1.0"], ecosystem=PYPI)],
        advisories=[
            advisory("A", "flask", ("introduced", "0"), ("fixed", "0.12.3"), ecosystem=PYPI)
        ],
    )
    update = single(project)
    fix = update.option("0.12.3")
    assert fix is not None
    assert fix.edits[0].new == "~=0.12,>=0.12.3"
    assert update.selected == "0.12.5"
    assert update.option("0.12.5").edits[0].new == "~=0.12,>=0.12.5"  # type: ignore[union-attr]


def test_a_package_declared_twice_moves_together() -> None:
    project = plan(
        dep("httpx", ">=0.27", "0.27.0", ecosystem=PYPI),
        dep("httpx", "==0.27.0", "0.27.0", ecosystem=PYPI, scope=Scope.DEV),
        infos=[info("httpx", ["0.27.0", "0.27.2"], ecosystem=PYPI)],
    )
    update = single(project)
    assert len(update.dependencies) == 2
    (option,) = update.options
    assert [(e.old, e.new) for e in option.edits] == [("==0.27.0", "==0.27.2")]


def test_a_constraint_without_location_is_manual() -> None:
    project = plan(
        dep("pkg", "1.0.0", "1.0.0", location=None),
        infos=[info("pkg", ["1.0.0", "1.0.1"])],
    )
    update = single(project)
    (option,) = update.options
    assert option.edits == ()
    assert option.manual == (
        "Contrainte « 1.0.0 » de package.json : emplacement inconnu, à réécrire à la main en "
        "« 1.0.1 »."
    )
    assert update.selected is None  # jamais pré-cochée


def test_a_pnpm_catalog() -> None:
    project = plan(
        dep("pkg", "catalog:", "1.0.0", location=None, resolved="1.0.0"),
        infos=[info("pkg", ["1.0.0", "1.0.1"])],
    )
    (option,) = single(project).options
    (edit,) = option.edits
    assert (edit.kind, edit.location, edit.old, edit.new) == (
        EditKind.CATALOG,
        None,
        "1.0.0",
        "1.0.1",
    )
    assert option.manual is None


def test_a_peer_dependency_widens() -> None:
    project = plan(
        dep("react", "^17.0.0 || ^18.0.0", "18.3.1", scope=Scope.PEER),
        infos=[info("react", ["17.0.2", "18.3.1", "19.1.0"])],
    )
    (option,) = single(project).options
    assert option.edits[0].new == "^17.0.0 || ^18.0.0 || ^19.1.0"


def test_a_yanked_version_and_its_replacement() -> None:
    published = ["2.31.0", "2.32.0", "2.32.1", "2.32.2", "2.32.3"]
    project = plan(
        dep("requests", "==2.32.0", "2.32.0", ecosystem=PYPI),
        infos=[info("requests", published, ecosystem=PYPI, yanked={"2.32.0", "2.32.1"})],
    )
    update = single(project)
    assert options(update) == [("2.32.2", PATCH), ("2.32.3", PATCH)]
    assert update.options[0].reasons == (UpdateReason.REPLACEMENT,)
    assert update.selected == "2.32.3"


def test_a_replacement_below_is_never_preselected() -> None:
    project = plan(
        dep("pkg", "==2.5.0", "2.5.0", ecosystem=PYPI),
        infos=[info("pkg", ["2.4.0", "2.4.1", "2.5.0", "3.0.0"], ecosystem=PYPI, yanked={"2.5.0"})],
    )
    update = single(project)
    assert options(update) == [("2.4.1", None), ("3.0.0", MAJOR)]
    assert update.options[0].warnings == (DOWNGRADE_WARNING,)
    assert update.selected is None
    assert planner.choose(update, Rules(level=MAJOR)) == "3.0.0"


# ---------------------------------------------------------------------------
# Indirectes et versions forcées
# ---------------------------------------------------------------------------


def indirect(name: str, installed: str) -> Dependency:
    return dep(name, "", installed, direct=False)


LODASH = ["4.17.15", "4.17.21", "4.18.1", "5.0.0"]
LODASH_ADVISORIES = [
    advisory("A", "lodash", ("introduced", "0"), ("fixed", "4.17.21")),
    advisory("B", "lodash", ("introduced", "0"), ("fixed", "5.0.0")),
]


def test_an_indirect_dependency_moves_with_its_lockfile() -> None:
    project = plan(
        indirect("lodash", "4.17.15"), infos=[info("lodash", LODASH)], advisories=LODASH_ADVISORIES
    )
    update = single(project)
    assert update.id == ".|npm|lodash|4.17.15"
    assert not update.direct
    # Sans constat « plus récente » (pas de --transitive) : seulement ce qui corrige.
    assert options(update) == [("4.17.21", PATCH), ("4.18.1", MINOR), ("5.0.0", MAJOR)]
    assert all(o.edits == () and o.lockfile == "package-lock.json" for o in update.options)
    assert update.options[0].reasons == (UpdateReason.LATEST_PATCH,)
    assert update.option("5.0.0").warnings == (MAJOR_WARNING, INDIRECT_MAJOR_WARNING)  # type: ignore[union-attr]
    assert update.selected == "4.18.1"


def override(constraint: str, key: str = "lodash", section: str = "overrides") -> Override:
    return Override(
        ecosystem=NPM,
        name="lodash",
        constraint=constraint,
        key=key,
        section=section,
        file="package.json",
        location=Location(line=8, column=15, end_column=15 + len(constraint)),
    )


def test_a_forced_indirect_dependency_rewrites_the_override() -> None:
    project = plan(
        indirect("lodash", "4.17.15"),
        infos=[info("lodash", LODASH)],
        advisories=LODASH_ADVISORIES,
        overrides=[override("4.17.15")],
    )
    fix = single(project).option("4.17.21")
    assert fix is not None
    (edit,) = fix.edits
    assert (edit.kind, edit.file, edit.old, edit.new) == (
        EditKind.OVERRIDE,
        "package.json",
        "4.17.15",
        "4.17.21",
    )
    assert edit.override is not None
    assert fix.lockfile == "package-lock.json"


def test_an_override_that_already_accepts_the_version() -> None:
    project = plan(
        indirect("lodash", "4.17.15"),
        infos=[info("lodash", LODASH)],
        advisories=LODASH_ADVISORIES,
        overrides=[override("^4.17.0")],
    )
    assert single(project).option("4.17.21").edits == ()  # type: ignore[union-attr]


def test_an_override_that_cannot_be_rewritten() -> None:
    project = plan(
        indirect("lodash", "4.17.15"),
        infos=[info("lodash", LODASH)],
        advisories=LODASH_ADVISORIES,
        overrides=[override("$lodash")],
    )
    fix = single(project).option("4.17.21")
    assert fix is not None
    assert fix.manual == (
        "Version forcée « lodash » (overrides, package.json) : « $lodash », à réécrire à la main."
    )


def test_the_override_of_the_whole_tree_comes_first() -> None:
    project = plan(
        indirect("lodash", "4.17.15"),
        infos=[info("lodash", LODASH)],
        advisories=LODASH_ADVISORIES,
        overrides=[override("4.17.15", key="a>lodash"), override("4.17.16", key="**/lodash")],
    )
    edit = single(project).option("4.17.21").edits[0]  # type: ignore[union-attr]
    assert edit.old == "4.17.16"


# ---------------------------------------------------------------------------
# La sélection : règles de la ligne de commande, choix de l'interface
# ---------------------------------------------------------------------------


@pytest.fixture
def report() -> Report:
    """Trois paquets : ``pkg`` (correctif, mineure, majeure), ``vuln`` (une faille corrigée
    par un correctif) et ``pypkg`` (PyPI)."""
    project = plan(
        dep("pkg", "^1.0.0", "1.0.0"),
        dep("vuln", "^1.0.0", "1.0.0"),
        dep("pypkg", "==1.0.0", "1.0.0", ecosystem=PYPI),
        infos=[
            info("pkg", VERSIONS),
            info("vuln", VERSIONS),
            info("pypkg", VERSIONS, ecosystem=PYPI),
        ],
        advisories=[advisory("A", "vuln", ("introduced", "0"), ("fixed", "1.0.1"))],
    )
    return Report(source=".", projects=[project])


@pytest.mark.parametrize(
    ("rules", "expected"),
    [
        (Rules(), {"pkg": "1.2.1", "vuln": "1.2.1", "pypkg": "1.2.1"}),
        (Rules(level=PATCH), {"pkg": "1.0.2", "vuln": "1.0.2", "pypkg": "1.0.2"}),
        (Rules(level=MAJOR), {"pkg": "2.1.0", "vuln": "2.1.0", "pypkg": "2.1.0"}),
        # La plus petite version qui corrige.
        (Rules(security_only=True), {"vuln": "1.0.1"}),
        (Rules(include=("p*",)), {"pkg": "1.2.1", "pypkg": "1.2.1"}),
        (Rules(include=("PKG", "vuln")), {"pkg": "1.2.1", "vuln": "1.2.1"}),
        (Rules(exclude=("py*",)), {"pkg": "1.2.1", "vuln": "1.2.1"}),
        (Rules(ecosystems=frozenset({PYPI})), {"pypkg": "1.2.1"}),
        (Rules(level=PATCH, security_only=True, exclude=("vuln",)), {}),
    ],
)
def test_rules(report: Report, rules: Rules, expected: dict[str, str]) -> None:
    selection = planner.select(report, rules)
    names = {update.id: update.name for update in report.projects[0].updates}
    assert {names[key]: version for key, version in selection.items()} == expected


def test_security_only_with_a_major_fix() -> None:
    project = plan(
        dep("pkg", "^1.2.0", "1.2.0"),
        infos=[info("pkg", ["1.2.0", "1.3.0", "2.0.0"])],
        advisories=[advisory("A", "pkg", ("introduced", "0"), ("fixed", "2.0.0"))],
    )
    update = single(project)
    assert planner.choose(update, Rules(security_only=True)) is None
    assert planner.choose(update, Rules(security_only=True, level=MAJOR)) == "2.0.0"


def test_chosen_options(report: Report) -> None:
    selection = planner.select(report)
    found = planner.chosen(report, selection)
    assert [(update.name, option.version) for _, update, option in found] == [
        ("vuln", "1.2.1"),
        ("pkg", "1.2.1"),
        ("pypkg", "1.2.1"),
    ]
    # L'interface coche une autre option : la sélection est une donnée.
    selection[".|npm|pkg"] = "2.1.0"
    del selection[".|PyPI|pypkg"]
    found = planner.chosen(report, selection)
    assert [(update.name, option.version) for _, update, option in found] == [
        ("vuln", "1.2.1"),
        ("pkg", "2.1.0"),
    ]


def test_chosen_refuses_what_is_not_proposed(report: Report) -> None:
    with pytest.raises(ValueError, match=r"pkg : la version 9.9.9 n'est pas proposée"):
        planner.chosen(report, {".|npm|pkg": "9.9.9"})
    with pytest.raises(ValueError, match="mise à jour inconnue"):
        planner.chosen(report, {".|npm|absent": "1.0.0"})


def test_updates_follow_the_order_of_findings(report: Report) -> None:
    """La faille d'abord, puis les autres par nom, comme les constats."""
    assert [u.name for u in report.projects[0].updates] == ["vuln", "pkg", "pypkg"]


# ---------------------------------------------------------------------------
# Les versions proposées, vérifiées auprès d'OSV (E10)
# ---------------------------------------------------------------------------


def audited(project: Project, advisories: Iterable[Advisory]) -> Report:
    """Le projet, ses versions proposées soumises à un OSV qui connaît ``advisories``."""
    report = Report(source=".", projects=[project])
    advisories = list(advisories)
    found = {
        query: Vulnerabilities(
            advisories=tuple(a for a in advisories if a.affects(*query)), fetched_at=NOW
        )
        for query in planner.proposed_versions(report)
    }
    planner.audit(report, found)
    return report


def test_proposed_versions() -> None:
    project = plan(dep("pkg", "^1.0.0", "1.0.0"), infos=[info("pkg", VERSIONS)])
    report = Report(source=".", projects=[project])
    assert planner.proposed_versions(report) == [
        (NPM, "pkg", "1.0.2"),
        (NPM, "pkg", "1.2.1"),
        (NPM, "pkg", "2.1.0"),
    ]


def test_an_option_with_a_new_vulnerability_is_not_preselected() -> None:
    """1.2.1, la dernière mineure, a une faille que 1.0.0 n'a pas : le dernier correctif est
    pré-coché à sa place, et l'option le dit."""
    project = plan(dep("pkg", "^1.0.0", "1.0.0"), infos=[info("pkg", VERSIONS)])
    assert single(project).selected == "1.2.1"
    new = advisory("NEW", "pkg", ("introduced", "1.2.0"), ("fixed", "2.0.0"))
    report = audited(project, [new])
    update = single(project)
    assert [(o.version, o.introduced) for o in update.options] == [
        ("1.0.2", ()),
        ("1.2.1", ("CVE-NEW",)),
        ("2.1.0", ()),
    ]
    assert update.option("1.2.1").warnings == ("Faille connue dans cette version : CVE-NEW.",)
    assert update.selected == "1.0.2"
    assert planner.select(report) == {update.id: "1.0.2"}
    assert planner.select(report, Rules(level=MAJOR)) == {update.id: "2.1.0"}


def test_a_vulnerability_the_current_version_already_has_is_not_new() -> None:
    """OLD concerne 1.0.0 et 1.0.2 : 1.0.2 la laisse (``unfixed``), elle n'en introduit pas."""
    old = advisory("OLD", "pkg", ("introduced", "0"), ("fixed", "1.1.0"))
    project = plan(dep("pkg", "^1.0.0", "1.0.0"), infos=[info("pkg", VERSIONS)], advisories=[old])
    audited(project, [old])
    update = single(project)
    patch = update.option("1.0.2")
    assert patch is not None
    assert patch.unfixed == ("CVE-OLD",)
    assert all(o.introduced == () for o in update.options)
    assert update.selected == "1.2.1"


def test_several_new_vulnerabilities() -> None:
    project = plan(dep("pkg", "^1.0.0", "1.0.0"), infos=[info("pkg", VERSIONS)])
    news = [
        advisory(name, "pkg", ("introduced", "1.0.1"), ("fixed", "1.1.0")) for name in ("A", "B")
    ]
    audited(project, news)
    patch = single(project).option("1.0.2")
    assert patch is not None
    assert patch.introduced == ("CVE-A", "CVE-B")
    assert patch.warnings[-1] == "Failles connues dans cette version : CVE-A, CVE-B."


def test_proposed_versions_osv_could_not_check() -> None:
    """OSV ne répond pas : les options ne changent pas, une remarque du projet le dit."""
    project = plan(dep("pkg", "^1.0.0", "1.0.0"), infos=[info("pkg", VERSIONS)])
    before = single(project)
    report = Report(source=".", projects=[project])
    error = OsvError("OSV : api.osv.dev injoignable (ConnectError).")
    planner.audit(report, dict.fromkeys(planner.proposed_versions(report), error))
    assert single(project) == before
    assert [(n.file, n.message) for n in project.notices] == [
        (
            "package.json",
            "Failles non vérifiées pour 3 versions proposées. OSV : api.osv.dev injoignable "
            "(ConnectError).",
        )
    ]
