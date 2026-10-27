"""Versions PyPI : PEP 440, et les contraintes Poetry et Pipfile traduites en PEP 440.

Les cas d'ordre et de spécificateurs viennent des exemples de PEP 440 ; ceux de Poetry,
de sa doc (« Dependency specification »).
"""

import itertools

import pytest
from packaging.specifiers import SpecifierSet

from forceupdate.versions import InvalidConstraint, InvalidVersion
from forceupdate.versions.pypi import PYPI


def test_pep_440_ordering() -> None:
    """L'exemple de PEP 440 (« Summary of permitted suffixes and relative ordering »)."""
    ordered = [
        "1.dev0",
        "1.0.dev456",
        "1.0a1",
        "1.0a2.dev456",
        "1.0a12.dev456",
        "1.0a12",
        "1.0b1.dev456",
        "1.0b2",
        "1.0b2.post345.dev456",
        "1.0b2.post345",
        "1.0rc1.dev456",
        "1.0rc1",
        "1.0",
        "1.0+abc.5",
        "1.0+abc.7",
        "1.0+5",
        "1.0.post456.dev34",
        "1.0.post456",
        "1.0.15",
        "1.1.dev1",
    ]
    assert sorted(reversed(ordered), key=PYPI.parse) == ordered
    for lower, higher in itertools.pairwise(ordered):
        assert PYPI.compare(lower, higher) == -1


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("1.10", "1.9", 1),
        ("1.0", "1.0.0", 0),
        ("v1.2", "1.2", 0),
        ("1.0.0-beta", "1.0.0b0", 0),
        ("1!1.0", "2.0", 1),
        ("2.0.0rc1", "2.0.0", -1),
    ],
)
def test_compare(a: str, b: str, expected: int) -> None:
    assert PYPI.compare(a, b) == expected


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("2.0.0rc1", True),
        ("1.0a1", True),
        ("1.0.dev1", True),
        ("1.0", False),
        ("1.0.post1", False),
        ("1.0+local", False),
    ],
)
def test_is_prerelease(version: str, expected: bool) -> None:
    assert PYPI.is_prerelease(version) is expected


@pytest.mark.parametrize("text", ["", "latest", "1.2.3-foo-bar", "^1.2", "1..2"])
def test_invalid_versions(text: str) -> None:
    with pytest.raises(InvalidVersion):
        PYPI.parse(text)


@pytest.mark.parametrize(
    ("constraint", "version", "expected"),
    [
        # Version compatible (~=)
        ("~=2.2", "2.2", True),
        ("~=2.2", "2.9", True),
        ("~=2.2", "3.0", False),
        ("~=2.2", "2.1", False),
        ("~=1.4.5", "1.4.9", True),
        ("~=1.4.5", "1.5.0", False),
        ("~=2.2.post3", "2.2.post3", True),
        ("~=2.2.post3", "2.3", True),
        ("~=2.2.post3", "2.2", False),
        ("~=1.4.5a4", "1.4.5a4", True),
        ("~=1.4.5a4", "1.4.5", True),
        ("~=1.4.5a4", "1.5", False),
        ("~=2.2.0", "2.2.5", True),
        ("~=2.2.0", "2.3.0", False),
        ("~=1.4.5.0", "1.4.5.1", True),
        ("~=1.4.5.0", "1.4.6", False),
        # Égalité, préfixe, versions locales
        ("==1.1", "1.1.0", True),
        ("==1.1", "1.1+ubuntu1", True),
        ("==1.1", "1.1.post1", False),
        ("==1.1.*", "1.1.post1", True),
        ("==1.1.post1", "1.1.post1", True),
        ("!=1.1.*", "1.1.3", False),
        ("!=1.1.*", "1.2", True),
        # Comparaisons exclusives
        (">1.7", "1.7.1", True),
        (">1.7", "1.7.0.post1", False),
        (">1.7.post2", "1.7.1", True),
        (">1.7.post2", "1.7.0.post3", True),
        (">1.7.post2", "1.7.0", False),
        ("<1.7", "1.6.9", True),
        ("<1.7", "1.7.0rc1", False),
        # Une contrainte est un ensemble : les candidates écartent les pré-versions, pas elle.
        (">=1.0", "2.0rc1", True),
        ("", "2.0rc1", True),
        # Intersection
        (">= 2.25, < 3", "2.31.0", True),
        (">= 2.25, < 3", "3.0", False),
    ],
)
def test_pep_440_specifiers(constraint: str, version: str, expected: bool) -> None:
    assert PYPI.satisfies(constraint, version) is expected


@pytest.mark.parametrize(
    ("written", "sets"),
    [
        # Caret
        ("^1.2.3", [">=1.2.3,<2.0.0"]),
        ("^1.2", [">=1.2,<2.0"]),
        ("^1", [">=1,<2"]),
        ("^0.2.3", [">=0.2.3,<0.3.0"]),
        ("^0.0.3", [">=0.0.3,<0.0.4"]),
        ("^0.0", [">=0.0,<0.1"]),
        ("^0", [">=0,<1"]),
        ("^1.2.3b1", [">=1.2.3b1,<2.0.0"]),
        ("^ 1.2", [">=1.2,<2.0"]),
        # Tilde
        ("~1.2.3", [">=1.2.3,<1.3.0"]),
        ("~1.2", [">=1.2,<1.3"]),
        ("~1", [">=1,<2"]),
        # Jokers et versions nues
        ("1.2.*", ["==1.2.*"]),
        ("1.*", ["==1.*"]),
        ("1.2.x", ["==1.2.*"]),
        ("!=1.2.*", ["!=1.2.*"]),
        ("*", [""]),
        ("6.0.2", ["==6.0.2"]),
        ("=6.0.2", ["==6.0.2"]),
        ("v6.0.2", ["==6.0.2"]),
        ("<>1.5", ["!=1.5"]),
        # Plusieurs contraintes, avec des espaces ou des virgules
        (">=1.2 <2.0", [">=1.2,<2.0"]),
        (">= 1.2 < 2.0", [">=1.2,<2.0"]),
        (">=1.2, <2.0 !=1.5", [">=1.2,<2.0,!=1.5"]),
        ("^1.2 !=1.4.0", [">=1.2,<2.0,!=1.4.0"]),
        # Unions
        ("^1.2 || ^3.0", [">=1.2,<2.0", ">=3.0,<4.0"]),
        ("1.2.* || 2.*", ["==1.2.*", "==2.*"]),
        (">=1.0,<1.5 || >=2.0", [">=1.0,<1.5", ">=2.0"]),
        ("~1.0 | ~2.0", [">=1.0,<1.1", ">=2.0,<2.1"]),
        # PEP 440 tel quel
        (">= 2.25, < 3", [">=2.25,<3"]),
        ("~=1.4.2", ["~=1.4.2"]),
        ("", [""]),
    ],
)
def test_poetry_and_pipfile_constraints(written: str, sets: list[str]) -> None:
    constraint = PYPI.parse_constraint(written)
    assert constraint.sets == tuple(SpecifierSet(s) for s in sets)


@pytest.mark.parametrize(
    ("constraint", "version", "expected"),
    [
        ("^1.2 || ^3.0", "1.9", True),
        ("^1.2 || ^3.0", "2.5", False),
        ("^1.2 || ^3.0", "3.1", True),
        ("^0.2.3", "0.2.9", True),
        ("^0.2.3", "0.3.0", False),
        ("^0.2.3", "0.3.0rc1", False),  # « <0.3.0 » écarte les pré-versions de 0.3.0
        ("*", "0.0.1", True),
        ("6.0.2", "6.0.2", True),
        ("6.0.2", "6.0.3", False),
    ],
)
def test_poetry_satisfies(constraint: str, version: str, expected: bool) -> None:
    assert PYPI.satisfies(constraint, version) is expected


@pytest.mark.parametrize(
    ("constraint", "lowest"),
    [
        (">=1.2,<2", "1.2"),
        (">=1.2,>=1.5", "1.5"),
        ("^1.2", "1.2"),
        ("~=1.4.2", "1.4.2"),
        ("==1.2.*", "1.2"),
        ("1.2.*", "1.2"),
        ("6.0.2", "6.0.2"),
        (">1.2", "1.2"),  # borne exclue : la meilleure approximation
        (">=1.0 || >=0.5,<0.9", "0.5"),
        ("<2", None),
        ("!=1.5", None),
        ("*", None),
        ("", None),
        (">=1.0 || <0.5", None),
        ("===foobar", None),
    ],
)
def test_lower_bound(constraint: str, lowest: str | None) -> None:
    assert PYPI.lower_bound(constraint) == lowest


@pytest.mark.parametrize(
    ("constraint", "version"),
    [
        ("==1.2.3", "1.2.3"),
        ("== 1.2.3", "1.2.3"),
        ("===1.2.3-weird", "1.2.3-weird"),
        ("6.0.2", "6.0.2"),  # version nue de Poetry
        ("=6.0.2", "6.0.2"),
        ("==1.2.*", None),
        (">=1.2.3", None),
        ("==1.2.3,!=1.2.4", None),
        ("^1.2.3", None),
        ("==1.2.3 || ==1.2.4", None),
        ("", None),
    ],
)
def test_exact(constraint: str, version: str | None) -> None:
    assert PYPI.exact(constraint) == version


@pytest.mark.parametrize(
    "constraint",
    ["^", ">=", "^1.2.*", ">=1.2.*", "1.2.3 - 2.0", "foo", "~=1", "<*", ">=1.0 ||| <2", "dev"],
)
def test_invalid_constraints(constraint: str) -> None:
    with pytest.raises(InvalidConstraint):
        PYPI.parse_constraint(constraint)
