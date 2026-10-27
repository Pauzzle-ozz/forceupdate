"""Ce qui est commun aux écosystèmes : trouver les règles, l'écart, les candidates."""

from pathlib import Path

import pytest

from forceupdate import engine
from forceupdate.models import Ecosystem, Gap
from forceupdate.sources.local import LocalSource
from forceupdate.versions import InvalidConstraint, InvalidVersion, for_ecosystem
from forceupdate.versions.npm import NPM
from forceupdate.versions.pypi import PYPI

PATCH, MINOR, MAJOR = Gap.PATCH, Gap.MINOR, Gap.MAJOR
PROJECTS = Path(__file__).parent / "projects"


def test_for_ecosystem() -> None:
    assert for_ecosystem(Ecosystem.PYPI) is PYPI
    assert for_ecosystem(Ecosystem.NPM) is NPM
    assert PYPI.ecosystem is Ecosystem.PYPI
    assert NPM.ecosystem is Ecosystem.NPM


def test_an_ecosystem_not_yet_handled() -> None:
    with pytest.raises(LookupError, match="Go"):
        for_ecosystem(Ecosystem.GO)


@pytest.mark.parametrize(
    ("current", "target", "gap"),
    [
        # Le premier nombre qui change
        ("2.3.1", "2.3.4", PATCH),
        ("2.3.1", "2.9.0", MINOR),
        ("2.3.1", "3.0.0", MAJOR),
        ("1.9.0", "1.10.0", MINOR),
        ("1.2.3", "1.2.4-beta.1", PATCH),
        ("1.2.3", "2.0.0-rc.1", MAJOR),
        # 0.x : comme « ^ », 0.y change de majeure à chaque y, 0.0.z à chaque z
        ("0.2.3", "0.2.4", PATCH),
        ("0.2.3", "0.3.0", MAJOR),
        ("0.2.3", "1.0.0", MAJOR),
        ("0.0.3", "0.0.4", MAJOR),
        ("0.0.3", "0.1.0", MAJOR),
        # Une pré-version est juste sous sa version
        ("1.0.0-rc.1", "1.0.0", MAJOR),
        ("1.2.0-rc.1", "1.2.0", MINOR),
        ("1.2.3-rc.1", "1.2.3", PATCH),
        ("1.0.0-rc.1", "1.1.1", MAJOR),
        ("1.2.0-rc.1", "1.3.0", MINOR),
        ("1.2.3-rc.1", "1.2.4", PATCH),
        ("1.0.0-alpha", "1.0.0-beta", MAJOR),
        ("1.2.3-alpha", "1.2.3-beta", PATCH),
        ("0.3.0-rc.1", "0.3.0", MAJOR),
        # Pas plus récente
        ("1.2.3", "1.2.3", None),
        ("1.2.4", "1.2.3", None),
        ("1.2.3+a", "1.2.3+b", None),
    ],
)
def test_npm_gap(current: str, target: str, gap: Gap | None) -> None:
    assert NPM.gap(current, target) is gap


@pytest.mark.parametrize(
    ("current", "target", "gap"),
    [
        ("1.9", "1.10", MINOR),
        ("1.2", "1.2.1", PATCH),
        ("1.2", "1.3", MINOR),
        ("1.2.3", "1.2.3.post1", PATCH),
        ("1.2.3.4", "1.2.3.5", PATCH),
        ("2.0.0rc1", "2.0.0", MAJOR),
        ("2.0rc1", "2.0", MAJOR),
        ("1.2.3.dev1", "1.2.3", PATCH),
        ("1.0.dev1", "1.0", MAJOR),
        # fastapi 0.x : une mineure peut casser
        ("0.110.0", "0.115.0", MAJOR),
        ("0.110.0", "0.110.1", PATCH),
        # L'époque
        ("1!1.0", "1!1.1", MINOR),
        ("2024.1", "1!0.5", MAJOR),
        # Pas plus récente
        ("1.0", "1.0.0", None),
        ("2.0", "1.9", None),
    ],
)
def test_pypi_gap(current: str, target: str, gap: Gap | None) -> None:
    assert PYPI.gap(current, target) is gap


def test_gap_needs_readable_versions() -> None:
    with pytest.raises(InvalidVersion):
        NPM.gap("1.2", "1.3.0")


NPM_VERSIONS = [
    "1.0.0",
    "1.1.0",
    "1.2.0-beta.1",
    "2.0.0-rc.1",
    "1.1.1",
    "not-a-version",
    "2.0.0-rc.2",
]
PYPI_VERSIONS = ["1.0", "1.1", "1.2rc1", "2.0b1", "1.1.post1", "legacy-junk", "2.0b2"]


def test_prereleases_are_not_candidates() -> None:
    assert NPM.candidates(NPM_VERSIONS) == ["1.0.0", "1.1.0", "1.1.1"]
    assert NPM.candidates(NPM_VERSIONS, current="1.0.0") == ["1.0.0", "1.1.0", "1.1.1"]
    assert NPM.latest(NPM_VERSIONS) == "1.1.1"
    assert PYPI.candidates(PYPI_VERSIONS) == ["1.0", "1.1", "1.1.post1"]
    assert PYPI.latest(PYPI_VERSIONS) == "1.1.post1"


def test_prereleases_of_the_current_prerelease_are_candidates() -> None:
    """Sur une pré-version, celles de la même version restent candidates, pas les autres :
    de 2.0.0-rc.1, on propose 2.0.0-rc.2, pas 1.2.0-beta.1."""
    assert NPM.candidates(NPM_VERSIONS, current="2.0.0-rc.1") == [
        "1.0.0",
        "1.1.0",
        "2.0.0-rc.1",
        "1.1.1",
        "2.0.0-rc.2",
    ]
    assert NPM.latest(NPM_VERSIONS, current="2.0.0-rc.1") == "2.0.0-rc.2"
    assert PYPI.latest(PYPI_VERSIONS, current="2.0b1") == "2.0b2"
    assert PYPI.latest(PYPI_VERSIONS, current="2.0.0b1") == "2.0b2"  # 2.0 = 2.0.0
    assert PYPI.latest(PYPI_VERSIONS, current="1.2rc0") == "1.2rc1"
    assert PYPI.latest(PYPI_VERSIONS, current="3.0a1") == "1.1.post1"


def test_current_must_be_readable() -> None:
    with pytest.raises(InvalidVersion):
        NPM.candidates(NPM_VERSIONS, current="latest")


@pytest.mark.parametrize(
    ("constraint", "current", "expected"),
    [
        ("~1.0.0", None, "1.0.0"),
        ("^1.0.0", None, "1.1.1"),
        ("^1.0.0", "1.0.0", "1.1.1"),
        (">=3", None, None),
        ("*", None, "1.1.1"),
        ("latest", None, "1.1.1"),
        ("^2.0.0-rc.1", None, None),  # les pré-versions ne sont pas candidates…
        ("^2.0.0-rc.1", "2.0.0-rc.1", "2.0.0-rc.2"),  # … sauf celles de l'actuelle
    ],
)
def test_npm_max_satisfying(constraint: str, current: str | None, expected: str | None) -> None:
    assert NPM.max_satisfying(constraint, NPM_VERSIONS, current) == expected


@pytest.mark.parametrize(
    ("constraint", "current", "expected"),
    [
        ("<1.1", None, "1.0"),
        ("~=1.0", None, "1.1.post1"),
        ("==1.1", None, "1.1"),
        ("^1.0", None, "1.1.post1"),
        ("^1.0 || ^2.0", "2.0b1", "1.1.post1"),  # 2.0b2 est sous 2.0
        ("^1.0 || ^2.0b1", "2.0b1", "2.0b2"),
        (">=3", None, None),
        ("*", None, "1.1.post1"),
    ],
)
def test_pypi_max_satisfying(constraint: str, current: str | None, expected: str | None) -> None:
    assert PYPI.max_satisfying(constraint, PYPI_VERSIONS, current) == expected


def test_max_satisfying_needs_a_readable_constraint() -> None:
    with pytest.raises(InvalidConstraint):
        NPM.max_satisfying("catalog:", NPM_VERSIONS)


def test_highest_includes_prereleases() -> None:
    assert NPM.highest(NPM_VERSIONS) == "2.0.0-rc.2"
    assert PYPI.highest(["1.0", "2.0rc1", "junk"]) == "2.0rc1"
    assert PYPI.highest(["1.0", "1.0.0"]) == "1.0"  # à égalité, la première
    assert PYPI.highest(["junk"]) is None
    assert NPM.highest([]) is None


def test_sort_key_never_raises() -> None:
    versions = ["1.10.0", "git-ref", "1.9.0", "", "1.2.0", "1.10.0-beta"]
    assert sorted(versions, key=NPM.sort_key) == [
        "1.2.0",
        "1.9.0",
        "1.10.0-beta",
        "1.10.0",
        "",
        "git-ref",
    ]
    assert sorted(["1.10", "1.9", "abc def"], key=PYPI.sort_key) == ["1.9", "1.10", "abc def"]


@pytest.mark.parametrize("name", sorted(p.name for p in PROJECTS.iterdir() if p.is_dir()))
def test_mini_projects_constraints_are_understood(name: str) -> None:
    """Les lockfiles des mini-projets viennent des vrais outils (pip-tools, Poetry, uv,
    Pipenv, npm, Yarn, pnpm) : chaque contrainte écrite se lit, et chaque version
    installée respecte la contrainte de son manifeste."""
    report = engine.inventory(LocalSource(PROJECTS / name))
    for project in report.projects:
        for dependency in project.dependencies:
            if not (dependency.direct and dependency.verifiable):
                continue
            scheme = for_ecosystem(dependency.ecosystem)
            constraint = scheme.parse_constraint(dependency.effective_constraint)
            if dependency.installed is not None:
                assert constraint.contains(scheme.parse(dependency.installed)), dependency
