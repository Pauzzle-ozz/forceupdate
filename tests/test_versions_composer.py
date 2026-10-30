"""Versions Composer : la normalisation de Composer, l'ordre de ``version_compare``, ses
contraintes.

Les tables ``NORMALIZED``, ``ORDER`` et ``MATCHES`` ont été relevées sur composer/semver, celui
qu'embarque Composer 2.11 (``VersionParser::normalize``, ``version_compare`` de PHP 8.5,
``parseConstraints(…)->matches(…)``), le 2026-10-30 ; une comparaison plus large (1 282 versions de
Packagist, 19 600 paires, 99 contraintes) n'a donné aucun écart (voir les notes de E23 dans
``PLAN.md``). ``COMPOSER_CHOICES`` est la version qu'a choisie ``composer update`` (2.11) pour
chaque contrainte, sur les versions de monolog et de twig enregistrées dans
``tests/fixtures/packagist/`` : à mettre à jour après un nouvel enregistrement si une version est
sortie depuis.
"""

import json
from pathlib import Path

import pytest

from forceupdate import versions
from forceupdate.models import Ecosystem, Gap
from forceupdate.registries.packagist import expand
from forceupdate.versions import InvalidConstraint, InvalidVersion
from forceupdate.versions.composer import COMPOSER, is_branch, normalize, parse_stability

PACKAGIST = Path(__file__).parent / "fixtures" / "packagist"

NORMALIZED = {
    "1": "1.0.0.0",
    "1.2": "1.2.0.0",
    "v1.2.3": "1.2.3.0",
    "V2.0": "2.0.0.0",
    "1.2.3.4": "1.2.3.4",
    "01.2.3": "01.2.3.0",
    "1.0.0-beta.2": "1.0.0.0-beta2",
    "1.0.0beta2": "1.0.0.0-beta2",
    "1.0.0-b1": "1.0.0.0-beta1",
    "1.0.0-alpha": "1.0.0.0-alpha",
    "1.0.0-a1": "1.0.0.0-alpha1",
    "1.0.0-RC1": "1.0.0.0-RC1",
    "1.0.0-rc.1": "1.0.0.0-RC1",
    "1.0.0-p1": "1.0.0.0-patch1",
    "1.0.0-pl2": "1.0.0.0-patch2",
    "1.0.0-patch1": "1.0.0.0-patch1",
    "1.0.0-stable": "1.0.0.0",
    "1.0.0+build.5": "1.0.0.0",
    "1.0 as 2.0": "1.0.0.0",
    "1.0@dev": "1.0.0.0",
    "2010-01-02": "2010.01.02",
    "dev-master": "dev-master",
    "master": "dev-master",
    "1.x-dev": "1.9999999.9999999.9999999-dev",
    "1.0.x-dev": "1.0.9999999.9999999-dev",
    "foo": None,
    "": None,
    "1.2.3-": "1.2.3.0",
    "100000.1": "100000.1",
    "1.0.0-beta1-dev": "1.0.0.0-beta1-dev",
}

ORDER = [
    "0.9.9",
    "0.10.0",
    "1.0.0-alpha",
    "1.0.0-alpha2",
    "1.0.0-beta",
    "1.0.0-beta.2",
    "1.0.0-beta.10",
    "1.0.0-RC1",
    "1.0.0-RC2",
    "1.0.0",
    "1.0.0-patch1",
    "1.0.0-patch2",
    "1.0.0.1",
    "1.0.1",
    "1.2.3.4",
    "1.9.0",
    "1.10.0",
    "2.0.0-RC1",
    "v2.0.0",
    "20100102",
]
"""Rangées par ``usort`` et ``version_compare`` : ``patch`` après la version, pas avant."""

CANDIDATES = [
    "0.2.0",
    "0.3.0",
    "0.3.1",
    "0.3.9",
    "0.4.0",
    "1.0.0",
    "1.1.0",
    "1.2.0-beta1",
    "1.2.0",
    "1.2.3",
    "1.2.9",
    "1.3.0",
    "1.9.0",
    "2.0.0-RC1",
    "2.0.0",
    "2.0.1",
    "2.5.0",
    "3.0.0-alpha1",
    "3.0.0",
    "v5.4.0",
    "v5.4.47",
    "6.0.0",
    "1.2.3.4",
    "1.0.0-patch1",
]
EVERYTHING = CANDIDATES
UNDER_2 = [
    "0.2.0",
    "0.3.0",
    "0.3.1",
    "0.3.9",
    "0.4.0",
    "1.0.0",
    "1.1.0",
    "1.2.0-beta1",
    "1.2.0",
    "1.2.3",
    "1.2.9",
    "1.3.0",
    "1.9.0",
    "1.2.3.4",
    "1.0.0-patch1",
]
FROM_1_2 = ["1.2.0-beta1", "1.2.0", "1.2.3", "1.2.9", "1.3.0", "1.9.0", "1.2.3.4"]
FROM_1_2_UP = [
    "1.2.0-beta1",
    "1.2.0",
    "1.2.3",
    "1.2.9",
    "1.3.0",
    "1.9.0",
    "2.0.0-RC1",
    "2.0.0",
    "2.0.1",
    "2.5.0",
    "3.0.0-alpha1",
    "3.0.0",
    "v5.4.0",
    "v5.4.47",
    "6.0.0",
    "1.2.3.4",
]
ONE_X = [
    "1.0.0",
    "1.1.0",
    "1.2.0-beta1",
    "1.2.0",
    "1.2.3",
    "1.2.9",
    "1.3.0",
    "1.9.0",
    "1.2.3.4",
    "1.0.0-patch1",
]
ONE_OR_TWO = [*ONE_X[:8], "2.0.0-RC1", "2.0.0", "2.0.1", "2.5.0", "1.2.3.4", "1.0.0-patch1"]
NOT_1_2_3 = [v for v in CANDIDATES if v != "1.2.3"]

MATCHES: dict[str, list[str] | None] = {
    "^1.2": FROM_1_2,
    "^1.2.3": ["1.2.3", "1.2.9", "1.3.0", "1.9.0", "1.2.3.4"],
    "^0.3": ["0.3.0", "0.3.1", "0.3.9"],
    "^0.3.1": ["0.3.1", "0.3.9"],
    "^0": ["0.2.0", "0.3.0", "0.3.1", "0.3.9", "0.4.0"],
    "~1.2": FROM_1_2,  # jusqu'à 2.0, pas 1.3 comme npm
    "~1.2.3": ["1.2.3", "1.2.9", "1.2.3.4"],
    "~1": ONE_X,
    "~0.3": ["0.3.0", "0.3.1", "0.3.9", "0.4.0"],
    "1.2.*": ["1.2.0-beta1", "1.2.0", "1.2.3", "1.2.9", "1.2.3.4"],
    "1.*": ONE_X,
    "*": EVERYTHING,
    "v*": EVERYTHING,
    "1.2": ["1.2.0"],  # une version nue est exacte
    "1.2.3": ["1.2.3"],
    "=1.2.3": ["1.2.3"],
    "==1.2.3": ["1.2.3"],
    "v1.2.3": ["1.2.3"],
    ">=1.2": FROM_1_2_UP,
    ">1.2": [v for v in FROM_1_2_UP if v not in ("1.2.0-beta1", "1.2.0")],
    "<2.0": UNDER_2,
    "<=2.0": [*UNDER_2[:13], "2.0.0-RC1", "2.0.0", "1.2.3.4", "1.0.0-patch1"],
    "!=1.2.3": NOT_1_2_3,
    "<>1.2.3": NOT_1_2_3,
    ">=1.2 <2.0": FROM_1_2,
    ">=1.2,<2.0": FROM_1_2,
    ">= 1.2": FROM_1_2_UP,
    "1.0 - 2.0": [*ONE_X[:8], "2.0.0-RC1", "2.0.0", "2.0.1", "1.2.3.4", "1.0.0-patch1"],
    "1.0 - 2": ONE_OR_TWO,
    "1.0.0 - 2.0.0": [*ONE_X[:8], "2.0.0-RC1", "2.0.0", "1.2.3.4", "1.0.0-patch1"],
    "^1.0 || ^2.0": ONE_OR_TWO,
    "^1.0 | ^2.0": ONE_OR_TWO,
    "^1.0@beta": ONE_X,
    "@dev": EVERYTHING,
    "*@dev": EVERYTHING,
    "dev-master": [],
    "1.x-dev": [],
    "^2.0-beta1": ["2.0.0-RC1", "2.0.0", "2.0.1", "2.5.0"],
    "2.0.0-RC1": ["2.0.0-RC1"],
    "~>1.2": None,
    "": None,
    "1.2,": None,
    "1.0 as 2.0": ["1.0.0"],
    "~5.4": ["v5.4.0", "v5.4.47"],
    "~5.4.0": ["v5.4.0", "v5.4.47"],
    "^1.2.3.4": ["1.2.9", "1.3.0", "1.9.0", "1.2.3.4"],
    "^v1.2": FROM_1_2,
    ">=1.2 <2.0 || ^3.0": [*FROM_1_2[:6], "3.0.0-alpha1", "3.0.0", "1.2.3.4"],
    "!=1.2.3 ^1.0": [v for v in ONE_X if v != "1.2.3"],
    "^1.2 ||": None,
}
"""Pour chaque contrainte, les versions de ``CANDIDATES`` qu'elle accepte ; ``None`` : Composer la
refuse. Les pré-versions comprises : c'est la stabilité qui les écarte, pas la contrainte."""

COMPOSER_CHOICES = {
    ("monolog/monolog", "^1.0"): "1.27.1",
    ("monolog/monolog", "^2.0"): "2.11.1",
    ("monolog/monolog", "~2.3"): "2.11.1",
    ("monolog/monolog", "~2.3.0"): "2.3.5",
    ("monolog/monolog", "2.3.*"): "2.3.5",
    ("monolog/monolog", ">=2.0 <2.5"): "2.4.0",
    ("monolog/monolog", "^2.0@beta"): "2.11.1",
    ("monolog/monolog", "3.0.0-RC1"): "3.0.0-RC1",
    ("monolog/monolog", "^3.0@RC"): "3.12.1",
    ("monolog/monolog", "<2.0"): "1.27.1",
    ("monolog/monolog", "1.0 - 2.3"): "2.3.5",
    ("monolog/monolog", "^2.3 || ^3.0"): "3.12.1",
    ("monolog/monolog", "!=3.12.1 ^3.0"): "3.12.0",
    ("monolog/monolog", ">=2.0.0-beta1 <2.0.0"): None,
    ("monolog/monolog", "~2.0@beta"): "2.11.1",
    ("twig/twig", "^4.0@alpha"): "v4.0.0-alpha1",
    ("twig/twig", "^3.0"): "v3.30.0",
    ("twig/twig", "3.4.*"): "v3.4.3",
    ("twig/twig", "~3.4"): "v3.30.0",
    ("twig/twig", "~3.4.0"): "v3.4.3",
    ("twig/twig", "^1.0"): "v1.44.8",
    ("twig/twig", ">=4.0@alpha"): "v4.0.0-alpha1",
}
"""Ce qu'a choisi ``composer update`` (2.11, ``config.platform.php`` 8.5.12). Deux écarts relevés
ne sont pas des contraintes : ``2.0.0-beta1`` (Composer la refuse, elle demande PHP 7 : la version
de PHP est pour E27) et ``4.*@dev``, où Composer prend la branche ``4.x-dev`` (forceupdate ne
propose jamais de branche)."""


def test_registered_for_packagist() -> None:
    assert versions.for_ecosystem(Ecosystem.PACKAGIST) is COMPOSER


@pytest.mark.parametrize(("text", "expected"), NORMALIZED.items())
def test_normalize_like_composer(text: str, expected: str | None) -> None:
    if expected is None:
        with pytest.raises(InvalidVersion):
            normalize(text)
    else:
        assert normalize(text) == expected


def test_the_order_of_version_compare() -> None:
    assert sorted(reversed(ORDER), key=COMPOSER.parse) == ORDER


@pytest.mark.parametrize(
    ("same", "other"),
    [("1.0", "1.0.0"), ("v1.2.3", "1.2.3.0"), ("1.0.0-b2", "1.0.0-beta.2"), ("1.0+x", "1.0.0")],
)
def test_equal_versions(same: str, other: str) -> None:
    assert COMPOSER.compare(same, other) == 0
    assert COMPOSER.parse(same) == COMPOSER.parse(other)
    assert hash(COMPOSER.parse(same)) == hash(COMPOSER.parse(other))


@pytest.mark.parametrize("text", ["dev-master", "1.x-dev", "1.0.0-dev", "foo", ""])
def test_branches_are_not_published_versions(text: str) -> None:
    with pytest.raises(InvalidVersion):
        COMPOSER.parse(text)


def test_is_branch() -> None:
    assert is_branch("dev-main") and is_branch(normalize("2.x-dev"))
    assert not is_branch(normalize("2.0.0"))


@pytest.mark.parametrize(
    ("version", "stability"),
    [
        ("1.0.0", "stable"),
        ("1.0.0-beta1", "beta"),
        ("1.0.0-RC2", "RC"),
        ("^2.0-beta1", "beta"),
        ("dev-master", "dev"),
        ("1.x-dev", "dev"),
        ("1.0.0-p1", "stable"),  # un patch n'est pas une pré-version
        ("v1.0b2", "beta"),
        ("2.0.0-rc.1+build", "RC"),
    ],
)
def test_stability(version: str, stability: str) -> None:
    assert parse_stability(version) == stability


def test_prereleases() -> None:
    assert COMPOSER.is_prerelease("1.0.0-RC1")
    assert COMPOSER.is_prerelease("v4.0.0-alpha1")
    assert not COMPOSER.is_prerelease("1.0.0-patch1")
    assert not COMPOSER.is_prerelease("v5.4.10")


@pytest.mark.parametrize(
    ("current", "target", "gap"),
    [
        ("2.3.5", "2.3.9", Gap.PATCH),
        ("2.3.5", "2.11.1", Gap.MINOR),
        ("2.3.5", "3.12.1", Gap.MAJOR),
        ("v5.4.10", "v5.4.47", Gap.PATCH),
        ("1.2.3.4", "1.2.3.5", Gap.PATCH),
        ("1.0.0", "1.0.0-patch1", Gap.PATCH),
        ("0.3.1", "0.4.0", Gap.MAJOR),  # 0.x : comme ^
    ],
)
def test_gap(current: str, target: str, gap: Gap) -> None:
    assert COMPOSER.gap(current, target) is gap


@pytest.mark.parametrize(("constraint", "accepted"), MATCHES.items())
def test_constraints_like_composer(constraint: str, accepted: list[str] | None) -> None:
    if accepted is None:
        with pytest.raises(InvalidConstraint):
            COMPOSER.parse_constraint(constraint)
        return
    assert [v for v in CANDIDATES if COMPOSER.satisfies(constraint, v)] == accepted


def test_tilde_operator_is_refused_with_its_ruby_form() -> None:
    with pytest.raises(InvalidConstraint, match="~>"):
        COMPOSER.parse_constraint("~>1.2")


@pytest.mark.parametrize(
    ("constraint", "lowest"),
    [
        ("^1.2", "1.2.0"),
        ("~5.4", "5.4.0"),
        ("3.4.*", "3.4.0"),
        ("7.4.0", "7.4.0"),
        ("v5.4.10", "5.4.10"),
        (">=1.2 <2.0", "1.2.0"),
        ("^1.1 || ^2.0", "1.1.0"),
        (">1.2", "1.2.0"),  # comme PyPI : la borne exclue, faute de version suivante
        ("1.2.3.4", "1.2.3.4"),
        (">=1.0@beta", "1.0.0-beta"),
        ("*", None),
        ("<2.0", None),
        ("^0.0", None),
        ("dev-master", None),
        ("1.x-dev", None),
        ("^1.0 || <0.5", None),
    ],
)
def test_lower_bound(constraint: str, lowest: str | None) -> None:
    assert COMPOSER.lower_bound(constraint) == lowest


@pytest.mark.parametrize(
    ("constraint", "version"),
    [
        ("7.4.0", "7.4.0"),
        ("=1.2.3", "1.2.3"),
        ("==v1.2.3", "v1.2.3"),
        ("1.2", "1.2"),
        ("1.2.*", None),
        ("^1.2", None),
        ("dev-master", None),
        ("1.0.x-dev", None),
        ("1.0 || 2.0", None),
    ],
)
def test_exact(constraint: str, version: str | None) -> None:
    assert COMPOSER.exact(constraint) == version


def test_stability_flags() -> None:
    assert COMPOSER.parse_constraint("^1.0").stability is None
    assert COMPOSER.parse_constraint("^1.0@beta").stability == "beta"
    assert COMPOSER.parse_constraint("^1.0@stable").stability is None
    assert COMPOSER.parse_constraint("@dev").stability == "dev"
    assert COMPOSER.parse_constraint("^2.0-beta1").stability == "beta"
    assert COMPOSER.parse_constraint("^1.0@RC || ^2.0@alpha").stability == "alpha"


def test_max_satisfying_takes_stables_without_a_flag() -> None:
    published = ["1.0.0", "1.5.0", "1.6.0-beta1", "2.0.0-RC1"]
    assert COMPOSER.max_satisfying("^1.0", published) == "1.5.0"
    assert COMPOSER.max_satisfying("^1.0@beta", published) == "1.6.0-beta1"
    assert COMPOSER.max_satisfying("^1.0@RC", published) == "1.5.0"
    assert COMPOSER.max_satisfying("^2.0@RC", published) == "2.0.0-RC1"
    # Sans drapeau, la ligne d'une pré-version installée compte (``candidates``).
    assert COMPOSER.max_satisfying("^1.5", [*published, "1.6.0-beta2"], "1.6.0-beta1") == (
        "1.6.0-beta2"
    )


def published(package: str) -> list[str]:
    data = json.loads((PACKAGIST / f"{package.replace('/', '__')}.json").read_text("utf-8"))
    return [entry["version"] for entry in expand(data["packages"][package])]


@pytest.mark.parametrize(("case", "chosen"), COMPOSER_CHOICES.items())
def test_the_same_choice_as_composer(case: tuple[str, str], chosen: str | None) -> None:
    package, constraint = case
    assert COMPOSER.max_satisfying(constraint, published(package)) == chosen
