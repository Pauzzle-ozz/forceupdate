"""Versions Cargo : semver 2.0, et les contraintes de Cargo (le crate ``semver``).

Les cas des contraintes viennent des tests du crate ``semver`` (``tests/test_version_req.rs`` :
``test_default``, ``test_exact``, ``test_greater_than``, ``test_less_than``, ``test_multiple``,
``test_tilde``, ``test_caret``, ``test_wildcard``). Le tableau ``CARGO_CHOICES`` a été relevé
avec cargo 1.99 (``cargo generate-lockfile``, le 2026-10-30) sur ``rand``, dont l'index est
enregistré dans ``tests/fixtures/crates/rand.jsonl`` : à mettre à jour après un nouvel
enregistrement si une version de ``rand`` est sortie depuis.
"""

import json
from pathlib import Path

import pytest

from forceupdate import versions
from forceupdate.models import Ecosystem, Gap
from forceupdate.versions import InvalidConstraint, InvalidVersion
from forceupdate.versions.cargo import CARGO

RAND = Path(__file__).parent / "fixtures" / "crates" / "rand.jsonl"


def test_registered_for_crates_io() -> None:
    assert versions.for_ecosystem(Ecosystem.CRATES_IO) is CARGO


@pytest.mark.parametrize(
    ("higher", "lower"),
    [
        ("1.0.0", "0.9.9"),
        ("0.10.0", "0.9.0"),
        ("1.10.0", "1.9.0"),
        ("1.2.3", "1.2.3-alpha"),
        ("1.2.3-alpha.10", "1.2.3-alpha.5"),
        ("1.2.3-beta", "1.2.3-alpha.beta"),
        ("0.9.0-beta.3", "0.9.0-alpha.2"),
        ("0.10.0-rc.10", "0.10.0-rc.9"),
        ("0.10.0-rc.10-0", "0.10.0-rc.10"),
    ],
)
def test_comparisons(higher: str, lower: str) -> None:
    assert CARGO.compare(higher, lower) == 1
    assert CARGO.compare(lower, higher) == -1


def test_build_metadata_does_not_count() -> None:
    assert CARGO.compare("0.10.0+wasi-snapshot-preview1", "0.10.0") == 0


@pytest.mark.parametrize("text", ["v1.2.3", "1.2", "01.2.3", "1.2.3-01", "1.2.3-", "", "1.2.3.4"])
def test_published_versions_are_strict(text: str) -> None:
    with pytest.raises(InvalidVersion):
        CARGO.parse(text)


@pytest.mark.parametrize(
    ("current", "target", "gap"),
    [
        ("1.0.100", "1.0.229", Gap.PATCH),
        ("1.5.4", "1.13.1", Gap.MINOR),
        ("1.6.0", "2.0.0", Gap.MAJOR),
        ("0.8.8", "0.10.3", Gap.MAJOR),  # ^0.8 ne va pas jusqu'à 0.10
        ("0.1.45", "0.1.46", Gap.PATCH),
        ("0.0.3", "0.0.4", Gap.MAJOR),
    ],
)
def test_gap_follows_the_caret(current: str, target: str, gap: Gap) -> None:
    assert CARGO.gap(current, target) is gap


# -- contraintes : les tests du crate semver ---------------------------------------------


@pytest.mark.parametrize(
    ("constraint", "accepted", "refused"),
    [
        # test_default : sans opérateur, c'est ^
        ("1.0.0", ["1.0.0", "1.0.1", "1.1.0"], ["0.9.9", "0.1.0", "1.0.0-pre", "2.0.0"]),
        # test_exact
        ("=1.0.0", ["1.0.0"], ["1.0.1", "0.9.9", "0.1.0", "1.0.0-pre"]),
        ("=0.9.0", ["0.9.0"], ["0.9.1", "1.9.0", "0.0.9", "0.9.0-pre"]),
        ("=0.0.2", ["0.0.2"], ["0.0.1", "0.0.3", "0.0.2-pre"]),
        ("=0.1.0-beta2.a", ["0.1.0-beta2.a"], ["0.9.1", "0.1.0", "0.1.1-beta2.a", "0.1.0-beta2"]),
        ("=0.1.0+meta", ["0.1.0", "0.1.0+meta", "0.1.0+any"], []),
        # test_greater_than
        (">= 1.0.0", ["1.0.0", "2.0.0"], ["0.1.0", "0.0.1", "1.0.0-pre", "2.0.0-pre"]),
        (
            ">= 2.1.0-alpha2",
            ["2.1.0-alpha2", "2.1.0-alpha3", "2.1.0", "3.0.0"],
            ["2.0.0", "2.1.0-alpha1", "2.0.0-alpha2", "3.0.0-alpha2"],
        ),
        # test_less_than
        ("< 1.0.0", ["0.1.0", "0.0.1"], ["1.0.0", "1.0.0-beta", "1.0.1", "0.9.9-alpha"]),
        (
            "<= 2.1.0-alpha2",
            ["2.1.0-alpha2", "2.1.0-alpha1", "2.0.0", "1.0.0"],
            ["2.1.0", "2.2.0-alpha1", "2.0.0-alpha2", "1.0.0-alpha2"],
        ),
        (">1.0.0-alpha, <1.0.0", ["1.0.0-beta"], ["1.0.0", "1.0.0-alpha"]),
        # test_multiple
        (">0.0.9, <=2.5.3", ["0.0.10", "1.0.0", "2.5.3"], ["0.0.8", "2.5.4"]),
        ("0.3.0, 0.4.0", [], ["0.0.8", "0.3.0", "0.4.0"]),
        ("<=0.2.0, >=0.5.0", [], ["0.0.8", "0.3.0", "0.5.1"]),
        ("0.1.0, 0.1.4, 0.1.6", ["0.1.6", "0.1.9"], ["0.1.0", "0.1.4", "0.2.0"]),
        (
            ">=0.5.1-alpha3, <0.6",
            ["0.5.1-alpha3", "0.5.1-alpha4", "0.5.1-beta", "0.5.1", "0.5.5"],
            ["0.5.1-alpha1", "0.5.2-alpha3", "0.5.5-pre", "0.5.0-pre", "0.6.0", "0.6.0-pre"],
        ),
        # test_tilde
        ("~1", ["1.0.0", "1.0.1", "1.1.1"], ["0.9.1", "2.9.0", "0.0.9"]),
        ("~1.2", ["1.2.0", "1.2.1"], ["1.1.1", "1.3.0", "0.0.9"]),
        ("~1.2.2", ["1.2.2", "1.2.4"], ["1.2.1", "1.9.0", "1.0.9", "2.0.1", "0.1.3"]),
        (
            "~1.2.3-beta.2",
            ["1.2.3", "1.2.4", "1.2.3-beta.2", "1.2.3-beta.4"],
            ["1.3.3", "1.1.4", "1.2.3-beta.1", "1.2.4-beta.2"],
        ),
        # test_caret
        ("^1", ["1.1.2", "1.1.0", "1.2.1", "1.0.1"], ["0.9.1", "2.9.0", "0.1.4", "1.0.0-beta1"]),
        ("^1.1", ["1.1.2", "1.1.0", "1.2.1"], ["0.9.1", "2.9.0", "1.0.1", "0.1.4"]),
        (
            "^1.1.2",
            ["1.1.2", "1.1.4", "1.2.1"],
            ["0.9.1", "2.9.0", "1.1.1", "0.0.1", "1.1.2-alpha1", "1.1.3-alpha1", "2.9.0-alpha1"],
        ),
        (
            "^0.1.2",
            ["0.1.2", "0.1.4"],
            ["0.9.1", "2.9.0", "1.1.1", "0.0.1", "0.1.2-beta", "0.1.3-alpha", "0.2.0-pre"],
        ),
        (
            "^0.5.1-alpha3",
            ["0.5.1-alpha3", "0.5.1-alpha4", "0.5.1-beta", "0.5.1", "0.5.5"],
            ["0.5.1-alpha1", "0.5.2-alpha3", "0.5.5-pre", "0.5.0-pre", "0.6.0"],
        ),
        ("^0.0.2", ["0.0.2"], ["0.9.1", "2.9.0", "1.1.1", "0.0.1", "0.1.4"]),
        ("^0.0", ["0.0.2", "0.0.0"], ["0.9.1", "2.9.0", "1.1.1", "0.1.4"]),
        ("^0", ["0.9.1", "0.0.2", "0.0.0"], ["2.9.0", "1.1.1"]),
        (
            "^1.4.2-beta.5",
            ["1.4.2", "1.4.3", "1.4.2-beta.5", "1.4.2-beta.6", "1.4.2-c"],
            ["0.9.9", "2.0.0", "1.4.2-alpha", "1.4.2-beta.4", "1.4.3-beta.5"],
        ),
        # test_wildcard
        ("*", ["0.9.1", "2.9.0", "0.0.9", "1.0.1", "1.1.1"], ["1.0.0-pre"]),
        ("x", ["0.9.1", "2.9.0"], []),
        ("1.*", ["1.2.0", "1.2.1", "1.1.1", "1.3.0"], ["0.0.9", "2.0.0"]),
        ("1.X", ["1.2.0", "1.3.0"], ["0.0.9"]),
        ("1.2.*", ["1.2.0", "1.2.2", "1.2.4"], ["1.9.0", "1.0.9", "2.0.1", "0.1.3"]),
        ("1.*.*", ["1.2.0"], ["2.0.0"]),
        # un opérateur devant un joker : une version partielle
        ("^0.1.*", ["0.1.0", "0.1.4"], ["0.2.0"]),
        (">=1.*", ["1.0.0", "3.1.0"], ["0.9.9"]),
        # =1.2 veut dire 1.2.* ; >1 veut dire >=2.0.0 ; <=1.2 veut dire <1.3.0
        ("=1.2", ["1.2.0", "1.2.9"], ["1.3.0", "1.1.9"]),
        (">1", ["2.0.0"], ["1.9.9"]),
        (">1.2", ["1.3.0"], ["1.2.9"]),
        ("<=1.2", ["1.2.9", "0.1.0"], ["1.3.0"]),
        # espaces autour des opérateurs et des virgules
        (" >= 0.7 , < 0.8 ", ["0.7.3"], ["0.8.0"]),
    ],
)
def test_constraints(constraint: str, accepted: list[str], refused: list[str]) -> None:
    for version in accepted:
        assert CARGO.satisfies(constraint, version), (constraint, version)
    for version in refused:
        assert not CARGO.satisfies(constraint, version), (constraint, version)


@pytest.mark.parametrize(
    "constraint",
    [
        "",
        "  ",
        "~>0.8",
        "0.8 0.9",
        "> 0.0.9 <= 2.5.3",
        "v0.8",
        ">=*",
        "^*",
        "0.08",
        "0.*.3",
        "1.2-beta",
        "1.*-beta",
        "0.8,",
        "0.8 || 0.9",
        "=1.2.3 || =2.3.4",
        "latest",
        "*, >1",
        "\t1.2",
        ", ".join(["1"] * 33),
    ],
)
def test_constraints_cargo_refuses(constraint: str) -> None:
    with pytest.raises(InvalidConstraint):
        CARGO.parse_constraint(constraint)


@pytest.mark.parametrize(
    ("constraint", "normalized"),
    [
        ("1.2", "^1.2"),
        ("=1.2.3", "=1.2.3"),
        (">= 1.0.0 , <2", ">=1.0.0, <2"),
        ("1.*", "1.*"),
        ("1.2.x", "1.2.*"),
        ("*", "*"),
        ("~1.2.3-beta.2", "~1.2.3-beta.2"),
        ("1.2.3+build", "^1.2.3"),
    ],
)
def test_str_is_the_form_cargo_shows(constraint: str, normalized: str) -> None:
    assert str(CARGO.parse_constraint(constraint)) == normalized


@pytest.mark.parametrize(
    ("constraint", "lowest"),
    [
        ("1.2", "1.2.0"),
        ("^0.1.2", "0.1.2"),
        ("~1.2.3-beta.2", "1.2.3-beta.2"),
        ("=1.2", "1.2.0"),
        ("1.*", "1.0.0"),
        (">1", "2.0.0"),
        (">1.2", "1.3.0"),
        (">1.2.3", "1.2.4"),
        (">1.2.3-beta", "1.2.3-beta.0"),
        (">=1.2, <1.5", "1.2.0"),
        ("<2", None),
        ("*", None),
        ("0", None),
        ("<=0.2.0, >=0.5.0", None),
    ],
)
def test_lower_bound(constraint: str, lowest: str | None) -> None:
    assert CARGO.lower_bound(constraint) == lowest


@pytest.mark.parametrize(
    ("constraint", "version"),
    [
        ("=1.2.3", "1.2.3"),
        ("=1.2.3-beta", "1.2.3-beta"),
        ("=1.2.3+build", "1.2.3"),
        ("1.2.3", None),  # ^1.2.3
        ("=1.2", None),  # 1.2.*
        (">=1.2.3", None),
        ("=1.2.3, <2", None),
    ],
)
def test_exact(constraint: str, version: str | None) -> None:
    assert CARGO.exact(constraint) == version


# -- la version que choisit cargo ----------------------------------------------------------

CARGO_CHOICES = {
    "0.8": "0.8.8",
    "0.8.3": "0.8.8",
    "^0.8": "0.8.8",
    "~0.8.3": "0.8.8",
    "=0.8": "0.8.8",
    "=0.8.3": "0.8.3",
    "0.*": "0.10.3",
    "0.8.*": "0.8.8",
    "0.x": "0.10.3",
    "*": "0.10.3",
    ">=0.7, <0.8": "0.7.3",
    ">= 0.7 , < 0.8": "0.7.3",
    ">0.8": "0.10.3",
    "<0.8": "0.7.3",
    "<=0.7": "0.7.3",
    "^0.9.0-alpha.1": "0.9.5",
    "0.9.0-alpha.1": "0.9.5",
    "=0.10.0-rc.5": "0.10.0-rc.5",
    "~0.10.0-rc.1": "0.10.3",
    ">=0.9.0-beta.0, <0.9.0": "0.9.0-beta.3",
    "0.8.5+build": "0.8.8",
    "0": "0.10.3",
    "^0.1.*": "0.1.4",
    "1": None,
    "0.0": None,
    "=0.8.5, =0.8.4": None,
}
"""La version de ``rand`` que choisit cargo 1.99 pour chaque contrainte (``None`` : « failed to
select a version »)."""


def published_rand() -> list[str]:
    lines = RAND.read_text(encoding="utf-8").splitlines()
    return [entry["vers"] for entry in map(json.loads, lines) if not entry["yanked"]]


@pytest.mark.parametrize(("constraint", "chosen"), sorted(CARGO_CHOICES.items()))
def test_the_same_choice_as_cargo(constraint: str, chosen: str | None) -> None:
    """Cargo prend la plus haute version non retirée qui respecte la contrainte, pré-versions
    comprises quand la contrainte en nomme une."""
    fitting = [v for v in published_rand() if CARGO.satisfies(constraint, v)]
    assert CARGO.highest(fitting) == chosen


def test_max_satisfying_proposes_prereleases_only_from_one() -> None:
    """Pour proposer une mise à jour, les pré-versions restent écartées, sauf celles de la
    version actuelle quand c'en est une (``VersionScheme.candidates``)."""
    published = published_rand()
    assert CARGO.max_satisfying("=0.10.0-rc.5", published) is None
    assert CARGO.max_satisfying("~0.10.0-rc.1", published, "0.10.0-rc.5") == "0.10.3"
    assert CARGO.latest(published) == "0.10.3"
