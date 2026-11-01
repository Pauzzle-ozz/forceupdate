"""Versions RubyGems : ``Gem::Version`` et ``Gem::Requirement``.

Les tables ``ORDER``, ``PRERELEASE``, ``NORMALIZED``, ``EQUAL``, ``REFUSED``, ``SATISFIES``,
``REFUSED_CONSTRAINTS``, ``BUMP`` et ``RELEASE`` ont été relevées sur RubyGems 4.0.20 (Ruby 4.0.9),
le 2026-11-01 ; une comparaison plus large (6 013 versions de l'index compact de 39 gems, 90 926
paires, 221 contraintes) n'a donné aucun écart (voir les notes de E24 dans ``PLAN.md``).
``BUNDLER_CHOICES`` est la version qu'a choisie ``bundle lock`` (Bundler 4.0.20) pour chaque
contrainte, sur les versions de rack et de mustermann enregistrées dans
``tests/fixtures/rubygems/`` : à mettre à jour après un nouvel enregistrement si une version est
sortie depuis.
"""

import itertools
from functools import cmp_to_key
from pathlib import Path

import pytest

from forceupdate import versions
from forceupdate.models import Ecosystem, Gap
from forceupdate.registries.rubygems import parse_info
from forceupdate.versions import InvalidConstraint, InvalidVersion
from forceupdate.versions.rubygems import RUBYGEMS

RUBYGEMS_FIXTURES = Path(__file__).parent / "fixtures" / "rubygems"

ORDER = ["0", "", "1.0.0.RC1", "1.0.a", "1.0.0.a", "1.a", "1.0.0.a1", "1.0.0.alpha", "1.0.0.b",
         "1.0.0.beta.2", "1.0.0-rc1", "1.0.0.pre", "1.0.0.pre.1", "1.0.0.rc1", "1.0.0.rc.1",
         "1.0.0.z", "1", "1.0", "1.0.0", "1.0.0.0", "1.0.0.0.1", "1.0.1", "1.0.9", "1.0.10",
         "1.1.0.a", "1.1", "1.2.3.4.5.6", "1.9", "1.10", "2.0.0.rc1", "2", "2.2.8", " 2.2.8.1 ",
         "2.2.8.1", "2.2.9"]  # fmt: skip
"""Rangées par ``Gem::Version#<=>`` ; les égales (``TIES``) dans leur ordre d'entrée."""

TIES = {("0", ""), ("1.0.a", "1.0.0.a"), ("1.0.0.a", "1.a"), ("1.0.0.rc1", "1.0.0.rc.1"),
        ("1", "1.0"), ("1.0", "1.0.0"), ("1.0.0", "1.0.0.0"), (" 2.2.8.1 ", "2.2.8.1")}  # fmt: skip
"""Les voisines de ``ORDER`` que ``Gem::Version#<=>`` dit égales."""

PRERELEASE = {
    "1.0.a": True, "1.0.0.a1": True, "1.0.0.beta.2": True, "1.0.0-rc1": True, "1.0.0.RC1": True,
    "1.1.0.a": True, "2.0.0.rc1": True, "1.0.0.pre.1": True, "1": False, "1.0.0.0.1": False,
    "": False, " 2.2.8.1 ": False, "1.2.3.4.5.6": False,
}  # fmt: skip

NORMALIZED = {
    "1.0.0-rc1": "1.0.0.pre.rc1",
    "1.0-beta-2": "1.0.pre.beta.pre.2",
    " 1.2 ": "1.2",
    "": "0",
    "1.0.0-1": "1.0.0.pre.1",
}
"""``Gem::Version#to_s`` : un ``-`` devient ``.pre.``."""

EQUAL = [
    ("1.0", "1.0.0", True),
    ("1", "1.0.0.0", True),
    ("1.0.0.a", "1.a", True),
    ("1.0.a", "1.0.0.a", True),
    ("1.0.0.rc1", "1.0.0-rc1", False),
    ("1.0.0.rc1", "1.0.0.rc.1", True),
    ("1.0.0.RC1", "1.0.0.rc1", False),
    ("1.0.1", "1.0.01", True),
    ("0", "", True),
]

REFUSED = ["1..2", ".1", "1.2-", "a", "1 2", "v1.2", "1.2.", "-1", "1.2.3+4", "1._2", "1.2,3"]

SATISFIES = [
    ("~> 2.2", "2.1.9", False), ("~> 2.2", "2.2", True), ("~> 2.2", "2.2.0", True),
    ("~> 2.2", "2.9.9", True), ("~> 2.2", "3.0.0.a", False), ("~> 2.2", "3.0.0.rc1", False),
    ("~> 2.2", "3.0", False), ("~> 2.2.3", "2.2.2", False), ("~> 2.2.3", "2.2.3", True),
    ("~> 2.2.3", "2.2.8.1", True), ("~> 2.2.3", "2.2.99", True), ("~> 2.2.3", "2.3.0.a", False),
    ("~> 2.2.3", "2.3.0", False), ("~> 2.2.8.1", "2.2.8", False), ("~> 2.2.8.1", "2.2.8.1", True),
    ("~> 2.2.8.1", "2.2.8.9", True), ("~> 2.2.8.1", "2.2.9", False), ("~> 1", "0.9", False),
    ("~> 1", "1.0", True), ("~> 1", "1.9.9", True), ("~> 1", "2.0.0.a", False),
    ("~> 1", "2.0", False), ("~> 0", "0.0.1", True), ("~> 0", "0.9", True),
    ("~> 0", "1.0.a", False), ("~> 0", "1.0", False), ("~> 1.0.0.a", "1.0.0.a", True),
    ("~> 1.0.0.a", "1.0.0.rc1", True), ("~> 1.0.0.a", "1.0.0", True),
    ("~> 1.0.0.a", "1.0.9", True), ("~> 1.0.0.a", "1.1.0.a", False), ("~> 1.0.0.a", "1.1", False),
    ("~> 2.0.0.rc1", "2.0.0.beta", False), ("~> 2.0.0.rc1", "2.0.0.rc1", True),
    ("~> 2.0.0.rc1", "2.0.0", True), ("~> 2.0.0.rc1", "2.0.5", True),
    ("~> 2.0.0.rc1", "2.1.0", False), ("1.2", "1.2", True), ("1.2", "1.2.0", True),
    ("1.2", "1.2.0.0", True), ("1.2", "1.2.1", False),
    ("1.2", "1.2.0.a", False), ("= 1.2", "1.2", True), ("= 1.2", "1.2.0", True),
    ("= 1.2", "1.2.1", False), ("!= 1.2.3", "1.2.3", False), ("!= 1.2.3", "1.2.3.0", False),
    ("!= 1.2.3", "1.2.4", True), ("> 1.2", "1.2", False), ("> 1.2", "1.2.0", False),
    ("> 1.2", "1.2.0.1", True), ("> 1.2", "1.3.0.a", True), (">= 1.2", "1.1.9", False),
    (">= 1.2", "1.2", True), (">= 1.2", "1.2.0.a", False), (">= 1.2", "2.0.0.rc1", True),
    ("< 2", "1.9.9", True), ("< 2", "2.0.0.a", True), ("< 2", "2.0", False),
    ("< 2", "2.0.0", False),
    ("<= 2.1", "2.1.0", True), ("<= 2.1", "2.1.0.1", False), ("<= 2.1", "2.1.0.a", True),
    ("<= 2.1", "2.1.1", False), (">= 1.19.0, < 1.20", "1.18.9", False),
    (">= 1.19.0, < 1.20", "1.19.0", True), (">= 1.19.0, < 1.20", "1.19.4", True),
    (">= 1.19.0, < 1.20", "1.20.0.rc1", True), (">= 1.19.0, < 1.20", "1.20.0", False),
    ("~> 2.2, >= 2.2.3", "2.2.2", False), ("~> 2.2, >= 2.2.3", "2.2.3", True),
    ("~> 2.2, >= 2.2.3", "2.9", True), ("~> 2.2, >= 2.2.3", "3.0", False),
    ("~> 2.2, != 2.2.4", "2.2.3", True), ("~> 2.2, != 2.2.4", "2.2.4", False),
    ("~> 2.2, != 2.2.4", "2.2.5", True), ("", "0", True), ("", "0.0.1.a", True), ("", "99", True),
    (">= 0", "0", True), (">= 0", "0.0.1.a", True), (">= 0", "99", True),
]  # fmt: skip
"""``Gem::Requirement#satisfied_by?`` : les pré-versions comprises, c'est Bundler qui les écarte."""

REFUSED_CONSTRAINTS = ["~ 1.2", "^1.2", "1.2 1.3", "=> 1.2", ">= ", "~>", "1.2,", ",", "== 1.2",
                       "~> 1.2,, >= 1", ">= 1.0 < 2"]  # fmt: skip

BUMP = {"1.2.3": "1.3", "1.2": "2", "1": "2", "1.2.3.4": "1.2.4", "2.0.0.rc1": "2.1", "1.0.a": "2"}
"""La borne haute de ``~>`` (``Gem::Version#bump``)."""

RELEASE = {"2.0.0.rc1": "2.0.0", "1.0.a": "1.0", "1.2.3": "1.2.3", "1.0.0.pre.1": "1.0.0"}

BUNDLER_CHOICES = {
    ("rack", ""): "3.2.8",
    ("rack", "~> 2.2.3"): "2.2.25",
    ("rack", "~> 2.2"): "2.2.25",
    ("rack", "~> 2"): "2.2.25",
    ("rack", "~> 1.6"): "1.6.13",
    ("rack", ">= 2.0, < 3"): "2.2.25",
    ("rack", "< 3.0.0.a"): "2.2.25",
    ("rack", ">= 3.0.0.beta1, < 3.1"): "3.0.18",
    ("rack", "~> 3.0.0.beta1"): "3.0.18",
    ("rack", "= 2.2.8.1"): "2.2.8.1",
    ("rack", "2.2.8"): "2.2.8",
    ("rack", "~> 2.0.0"): "2.0.9.4",
    ("rack", "> 2.2.3, < 2.2.5"): "2.2.4",
    ("rack", "!= 3.2.8"): "3.2.7",
    ("rack", "<= 2.1"): "2.1.0",
    ("rack", "~> 1.0"): "1.6.13",
    ("rack", "~> 0.9"): "0.9.1",
    ("rack", ">= 2.2.3, < 2.3, != 2.2.25"): "2.2.24",
    ("rack", "~> 3.1.0"): "3.1.23",
    ("rack", "~> 3.0.0"): "3.0.18",
    ("mustermann", ""): "4.0.1",
    ("mustermann", "~> 3.0"): "3.1.1",
    ("mustermann", ">= 4.0.0.beta1"): "4.0.1",
    ("mustermann", "~> 4.0.0.rc1"): "4.0.1",
    ("mustermann", "< 4"): "3.1.1",
}
"""``bundle lock`` d'un ``Gemfile`` qui n'a que ``gem "<gem>", <contrainte>`` (Bundler 4.0.20)."""


def test_registered_for_rubygems() -> None:
    assert versions.for_ecosystem(Ecosystem.RUBYGEMS) is RUBYGEMS
    assert RUBYGEMS.ecosystem is Ecosystem.RUBYGEMS


def test_the_order_of_gem_version() -> None:
    for a, b in itertools.pairwise(ORDER):
        assert RUBYGEMS.compare(a, b) == (0 if (a, b) in TIES else -1), (a, b)
        assert RUBYGEMS.compare(b, a) == (0 if (a, b) in TIES else 1), (b, a)
    ranked = sorted(ORDER[::-1], key=cmp_to_key(RUBYGEMS.compare))
    assert all(RUBYGEMS.compare(a, b) <= 0 for a, b in itertools.pairwise(ranked))


@pytest.mark.parametrize(("version", "prerelease"), PRERELEASE.items())
def test_a_letter_makes_a_prerelease(version: str, prerelease: bool) -> None:
    assert RUBYGEMS.is_prerelease(version) is prerelease


@pytest.mark.parametrize(("text", "normalized"), NORMALIZED.items())
def test_normalized_like_rubygems(text: str, normalized: str) -> None:
    assert str(RUBYGEMS.parse(text)) == normalized


@pytest.mark.parametrize(("a", "b", "equal"), EQUAL)
def test_equal_versions(a: str, b: str, equal: bool) -> None:
    assert (RUBYGEMS.compare(a, b) == 0) is equal
    assert (RUBYGEMS.parse(a) == RUBYGEMS.parse(b)) is equal
    if equal:
        assert hash(RUBYGEMS.parse(a)) == hash(RUBYGEMS.parse(b))


@pytest.mark.parametrize("text", REFUSED)
def test_refused_versions(text: str) -> None:
    with pytest.raises(InvalidVersion):
        RUBYGEMS.parse(text)


@pytest.mark.parametrize(("constraint", "version", "satisfied"), SATISFIES)
def test_requirements_like_rubygems(constraint: str, version: str, satisfied: bool) -> None:
    assert RUBYGEMS.satisfies(constraint, version) is satisfied


@pytest.mark.parametrize("constraint", REFUSED_CONSTRAINTS)
def test_refused_constraints(constraint: str) -> None:
    with pytest.raises(InvalidConstraint):
        RUBYGEMS.parse_constraint(constraint)


def test_a_requirement_is_written_like_gem_requirement() -> None:
    assert str(RUBYGEMS.parse_constraint("~>1.2,>=1.2.3")) == "~> 1.2, >= 1.2.3"
    assert str(RUBYGEMS.parse_constraint("1.2")) == "= 1.2"
    assert str(RUBYGEMS.parse_constraint("")) == ">= 0"


@pytest.mark.parametrize(("version", "bump"), BUMP.items())
def test_bump(version: str, bump: str) -> None:
    assert str(RUBYGEMS.parse(version).bump()) == bump


@pytest.mark.parametrize(("version", "release"), RELEASE.items())
def test_release(version: str, release: str) -> None:
    assert str(RUBYGEMS.parse(version).release) == release


@pytest.mark.parametrize(
    ("current", "target", "gap"),
    [
        ("2.2.3", "2.2.25", Gap.PATCH),
        ("2.2.8", "2.2.8.1", Gap.PATCH),
        ("1.19.0", "1.19.4", Gap.PATCH),
        ("5.26.1", "5.27.0", Gap.MINOR),
        ("2.2.2", "4.2.1", Gap.MAJOR),
        ("0.0.5", "0.0.6", Gap.MAJOR),
        ("2.0.0.rc1", "2.0.0", Gap.MAJOR),
        ("2.1.0.rc1", "2.1.0", Gap.MINOR),
    ],
)
def test_gap(current: str, target: str, gap: Gap) -> None:
    assert RUBYGEMS.gap(current, target) is gap


@pytest.mark.parametrize(
    ("constraint", "lowest"),
    [
        ("~> 2.2.3", "2.2.3"),
        (">= 1.19.0, < 1.20", "1.19.0"),
        ("~> 2.2.8, >= 2.2.8.1", "2.2.8.1"),
        ("5.6.4", "5.6.4"),
        ("> 1.2", None),
        ("< 2", None),
        ("", None),
        (">= 0", None),
        (">= 2, < 1", None),
    ],
)
def test_lower_bound(constraint: str, lowest: str | None) -> None:
    assert RUBYGEMS.lower_bound(constraint) == lowest


@pytest.mark.parametrize(
    ("constraint", "version"),
    [("5.6.4", "5.6.4"), ("= 2.2.8.1", "2.2.8.1"), ("~> 2.2", None), ("= 1.2, != 1.3", None)],
)
def test_exact(constraint: str, version: str | None) -> None:
    assert RUBYGEMS.exact(constraint) == version


def test_max_satisfying_takes_prereleases_only_when_named() -> None:
    published = ["2.0.0", "2.1.0", "3.0.0.rc1"]
    assert RUBYGEMS.max_satisfying(">= 2.0", published) == "2.1.0"
    assert RUBYGEMS.max_satisfying(">= 3.0.0.a", published) == "3.0.0.rc1"
    assert RUBYGEMS.latest(published) == "2.1.0"


def published(gem: str) -> list[str]:
    text = (RUBYGEMS_FIXTURES / f"{gem}.txt").read_text(encoding="utf-8")
    return [v.version for v in parse_info(text)]


@pytest.mark.parametrize(("case", "chosen"), BUNDLER_CHOICES.items())
def test_the_same_choice_as_bundler(case: tuple[str, str], chosen: str) -> None:
    gem, constraint = case
    assert RUBYGEMS.max_satisfying(constraint, published(gem)) == chosen
