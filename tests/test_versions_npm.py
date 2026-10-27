"""Versions npm : semver 2.0, plages de npm.

Les cas viennent de la doc de node-semver (README : plages développées, pré-versions)
et de ses tableaux de tests (``comparisons``, ``equality``, ``range-include``,
``range-exclude``, ``min-version``), sans ceux des options que npm n'utilise pas
(``includePrerelease``).
"""

import pytest

from forceupdate.versions import InvalidConstraint, InvalidVersion
from forceupdate.versions.npm import NPM, SemVer


@pytest.mark.parametrize(
    ("higher", "lower"),
    [
        ("0.0.0", "0.0.0-foo"),
        ("0.0.1", "0.0.0"),
        ("1.0.0", "0.9.9"),
        ("0.10.0", "0.9.0"),
        ("0.99.0", "0.10.0"),
        ("2.0.0", "1.2.3"),
        ("1.10.0", "1.9.0"),
        ("v0.0.0", "0.0.0-foo"),
        ("v0.0.1", "0.0.0"),
        ("1.2.3", "1.2.3-asdf"),
        ("1.2.3", "1.2.3-4"),
        ("1.2.3", "1.2.3-4-foo"),
        ("1.2.3-5-foo", "1.2.3-5"),
        ("1.2.3-5", "1.2.3-4"),
        ("1.2.3-5-foo", "1.2.3-5-Foo"),
        ("3.0.0", "2.7.2+asdf"),
        ("1.2.3-a.10", "1.2.3-a.5"),
        ("1.2.3-a.b", "1.2.3-a.5"),
        ("1.2.3-a.b", "1.2.3-a"),
        ("1.2.3-a.b.c.10.d.5", "1.2.3-a.b.c.5.d.100"),
        ("1.2.3-r2", "1.2.3-r100"),
        ("1.2.3-r100", "1.2.3-R2"),
    ],
)
def test_comparisons(higher: str, lower: str) -> None:
    assert NPM.compare(higher, lower) == 1
    assert NPM.compare(lower, higher) == -1
    assert NPM.parse(lower) < NPM.parse(higher)


def test_semver_spec_precedence() -> None:
    """L'exemple de semver.org (point 11)."""
    ordered = [
        "1.0.0-alpha",
        "1.0.0-alpha.1",
        "1.0.0-alpha.beta",
        "1.0.0-beta",
        "1.0.0-beta.2",
        "1.0.0-beta.11",
        "1.0.0-rc.1",
        "1.0.0",
        "2.0.0",
        "2.1.0",
        "2.1.1",
    ]
    assert sorted(reversed(ordered), key=NPM.parse) == ordered


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("1.2.3", "v1.2.3"),
        ("1.2.3", " 1.2.3 "),
        ("1.2.3-beta+build", "1.2.3-beta+otherbuild"),
        ("1.2.3+build", "1.2.3+otherbuild"),
        ("  v1.2.3+build", "1.2.3+otherbuild"),
    ],
)
def test_equality_ignores_build_metadata(a: str, b: str) -> None:
    assert NPM.compare(a, b) == 0
    assert NPM.parse(a) == NPM.parse(b)
    assert hash(NPM.parse(a)) == hash(NPM.parse(b))


def test_parse() -> None:
    version = NPM.parse("1.2.3-beta.11.x-y+sha.5")
    assert version == SemVer(1, 2, 3, ("beta", 11, "x-y"))
    assert version.build == ("sha", "5")
    assert str(version) == "1.2.3-beta.11.x-y"


@pytest.mark.parametrize(
    "text",
    ["", "1.2", "1", "1.2.3.4", "01.2.3", "1.02.3", "1.2.3-01", "=1.2.3", "1.2.3beta", "latest",
     "1.2.3-", "1.2.3+", "^1.2.3", "1.2.x", "\u0661.\u0662.\u0663"],
)  # fmt: skip
def test_published_versions_are_strict(text: str) -> None:
    with pytest.raises(InvalidVersion):
        NPM.parse(text)


@pytest.mark.parametrize(
    ("version", "expected"),
    [("1.0.0-beta", True), ("1.0.0-0", True), ("1.0.0", False), ("1.0.0+build", False)],
)
def test_is_prerelease(version: str, expected: bool) -> None:
    assert NPM.is_prerelease(version) is expected


# Le README de node-semver : chaque plage et sa forme développée. « >=0.0.0 » n'est pas
# une borne (node-semver l'efface aussi) : « ~0 » donne « <1.0.0-0 ».
@pytest.mark.parametrize(
    ("written", "developed"),
    [
        # Plages à trait d'union
        ("1.2.3 - 2.3.4", ">=1.2.3 <=2.3.4"),
        ("1.2 - 2.3.4", ">=1.2.0 <=2.3.4"),
        ("1.2.3 - 2.3", ">=1.2.3 <2.4.0-0"),
        ("1.2.3 - 2", ">=1.2.3 <3.0.0-0"),
        # Jokers
        ("*", "*"),
        ("", "*"),
        ("x", "*"),
        ("1.x", ">=1.0.0 <2.0.0-0"),
        ("1.2.x", ">=1.2.0 <1.3.0-0"),
        ("1", ">=1.0.0 <2.0.0-0"),
        ("1.2", ">=1.2.0 <1.3.0-0"),
        ("2.*.*", ">=2.0.0 <3.0.0-0"),
        # Tilde
        ("~1.2.3", ">=1.2.3 <1.3.0-0"),
        ("~1.2", ">=1.2.0 <1.3.0-0"),
        ("~1", ">=1.0.0 <2.0.0-0"),
        ("~0.2.3", ">=0.2.3 <0.3.0-0"),
        ("~0.2", ">=0.2.0 <0.3.0-0"),
        ("~0", "<1.0.0-0"),
        ("~1.2.3-beta.2", ">=1.2.3-beta.2 <1.3.0-0"),
        ("~>3.2.1", ">=3.2.1 <3.3.0-0"),
        ("~> 1", ">=1.0.0 <2.0.0-0"),
        # Caret
        ("^1.2.3", ">=1.2.3 <2.0.0-0"),
        ("^0.2.3", ">=0.2.3 <0.3.0-0"),
        ("^0.0.3", ">=0.0.3 <0.0.4-0"),
        ("^1.2.3-beta.2", ">=1.2.3-beta.2 <2.0.0-0"),
        ("^0.0.3-beta", ">=0.0.3-beta <0.0.4-0"),
        ("^1.2.x", ">=1.2.0 <2.0.0-0"),
        ("^0.0.x", "<0.1.0-0"),
        ("^0.0", "<0.1.0-0"),
        ("^1.x", ">=1.0.0 <2.0.0-0"),
        ("^0.x", "<1.0.0-0"),
        ("^ 1", ">=1.0.0 <2.0.0-0"),
        # Comparateurs, versions partielles
        (">=1.0.0", ">=1.0.0"),
        (">= 1.0.0", ">=1.0.0"),
        ("<    2.0.0", "<2.0.0"),
        ("=1.2.3", "1.2.3"),
        ("v1.2.3", "1.2.3"),
        (">=1", ">=1.0.0"),
        (">1", ">=2.0.0"),
        (">1.2", ">=1.3.0"),
        ("<1.2", "<1.2.0-0"),
        ("<=1.2", "<1.3.0-0"),
        ("=0.7.x", ">=0.7.0 <0.8.0-0"),
        ("<=0.7.x", "<0.8.0-0"),
        (">=0.7.x", ">=0.7.0"),
        ("<0.7.x", "<0.7.0-0"),
        (">=*", "*"),
        (">*", "<0.0.0-0"),
        ("<X", "<0.0.0-0"),
        ("1.0.0 - x", ">=1.0.0"),
        ("x - 1.0.0", "<=1.0.0"),
        # Unions
        ("0.1.20 || 1.2.4", "0.1.20||1.2.4"),
        (">=0.2.3 || <0.0.1", ">=0.2.3||<0.0.1"),
        ("1.2.x || 2.x", ">=1.2.0 <1.3.0-0||>=2.0.0 <3.0.0-0"),
        ("||", "*"),
        ("1.x || *", "*"),
        (">* || 1.x", ">=1.0.0 <2.0.0-0"),
    ],
)
def test_ranges_are_developed_like_node_semver(written: str, developed: str) -> None:
    assert str(NPM.parse_constraint(written)) == developed


@pytest.mark.parametrize(
    ("constraint", "version"),
    [
        ("1.0.0 - 2.0.0", "1.2.3"),
        ("^1.2.3+build", "1.2.3"),
        ("^1.2.3+build", "1.3.0"),
        ("1.2.3-pre+asdf - 2.4.3-pre+asdf", "1.2.3"),
        ("1.2.3pre+asdf - 2.4.3-pre+asdf", "1.2.3"),
        ("1.2.3-pre+asdf - 2.4.3pre+asdf", "1.2.3"),
        ("1.2.3-pre+asdf - 2.4.3-pre+asdf", "1.2.3-pre.2"),
        ("1.2.3-pre+asdf - 2.4.3-pre+asdf", "2.4.3-alpha"),
        ("1.2.3+asdf - 2.4.3+asdf", "1.2.3"),
        ("1.0.0", "1.0.0"),
        (">=*", "0.2.4"),
        ("", "1.0.0"),
        ("*", "1.2.3"),
        (">=1.0.0", "1.0.0"),
        (">=1.0.0", "1.0.1"),
        (">=1.0.0", "1.1.0"),
        (">1.0.0", "1.0.1"),
        (">1.0.0", "1.1.0"),
        ("<=2.0.0", "2.0.0"),
        ("<=2.0.0", "1.9999.9999"),
        ("<=2.0.0", "0.2.9"),
        ("<2.0.0", "1.9999.9999"),
        ("<2.0.0", "0.2.9"),
        (">= 1.0.0", "1.0.0"),
        (">=  1.0.0", "1.0.1"),
        (">   1.0.0", "1.1.0"),
        ("<=   2.0.0", "2.0.0"),
        ("<\t2.0.0", "0.2.9"),
        (">=0.1.97", "0.1.97"),
        ("0.1.20 || 1.2.4", "1.2.4"),
        (">=0.2.3 || <0.0.1", "0.0.0"),
        (">=0.2.3 || <0.0.1", "0.2.3"),
        (">=0.2.3 || <0.0.1", "0.2.4"),
        ("||", "1.3.4"),
        ("2.x.x", "2.1.3"),
        ("1.2.x", "1.2.3"),
        ("1.2.x || 2.x", "2.1.3"),
        ("1.2.x || 2.x", "1.2.3"),
        ("x", "1.2.3"),
        ("2.*.*", "2.1.3"),
        ("1.2.*", "1.2.3"),
        ("1.2.* || 2.*", "2.1.3"),
        ("1.2.* || 2.*", "1.2.3"),
        ("2", "2.1.2"),
        ("2.3", "2.3.1"),
        ("~0.0.1", "0.0.1"),
        ("~0.0.1", "0.0.2"),
        ("~x", "0.0.9"),
        ("~2", "2.0.9"),
        ("~2.4", "2.4.0"),
        ("~2.4", "2.4.5"),
        ("~>3.2.1", "3.2.2"),
        ("~1", "1.2.3"),
        ("~>1", "1.2.3"),
        ("~> 1", "1.2.3"),
        ("~1.0", "1.0.2"),
        ("~ 1.0", "1.0.2"),
        ("~ 1.0.3", "1.0.12"),
        ("~ 1.0.3alpha", "1.0.12"),
        (">=1", "1.0.0"),
        (">= 1", "1.0.0"),
        ("<1.2", "1.1.1"),
        ("< 1.2", "1.1.1"),
        ("~v0.5.4-pre", "0.5.5"),
        ("~v0.5.4-pre", "0.5.4"),
        ("=0.7.x", "0.7.2"),
        ("<=0.7.x", "0.7.2"),
        (">=0.7.x", "0.7.2"),
        ("<=0.7.x", "0.6.2"),
        ("~1.2.1 >=1.2.3", "1.2.3"),
        ("~1.2.1 =1.2.3", "1.2.3"),
        ("~1.2.1 1.2.3", "1.2.3"),
        ("~1.2.1 >=1.2.3 1.2.3", "1.2.3"),
        ("~1.2.1 1.2.3 >=1.2.3", "1.2.3"),
        (">=1.2.1 1.2.3", "1.2.3"),
        ("1.2.3 >=1.2.1", "1.2.3"),
        (">=1.2.3 >=1.2.1", "1.2.3"),
        (">=1.2.1 >=1.2.3", "1.2.3"),
        (">=1.2", "1.2.8"),
        ("^1.2.3", "1.8.1"),
        ("^0.1.2", "0.1.2"),
        ("^0.1", "0.1.2"),
        ("^0.0.1", "0.0.1"),
        ("^1.2", "1.4.2"),
        ("^1.2 ^1", "1.4.2"),
        ("^1.2.3-alpha", "1.2.3-pre"),
        ("^1.2.0-alpha", "1.2.0-pre"),
        ("^0.0.1-alpha", "0.0.1-beta"),
        ("^0.0.1-alpha", "0.0.1"),
        ("^0.1.1-alpha", "0.1.1-beta"),
        ("^x", "1.2.3"),
        ("x - 1.0.0", "0.9.7"),
        ("x - 1.x", "0.9.7"),
        ("1.0.0 - x", "1.9.7"),
        ("1.x - x", "1.9.7"),
        ("<=7.x", "7.9.9"),
    ],
)
def test_range_includes(constraint: str, version: str) -> None:
    assert NPM.satisfies(constraint, version)


@pytest.mark.parametrize(
    ("constraint", "version"),
    [
        ("1.0.0 - 2.0.0", "2.2.3"),
        ("1.2.3+asdf - 2.4.3+asdf", "1.2.3-pre.2"),
        ("1.2.3+asdf - 2.4.3+asdf", "2.4.3-alpha"),
        ("^1.2.3+build", "2.0.0"),
        ("^1.2.3+build", "1.2.0"),
        ("^1.2.3", "1.2.3-pre"),
        ("^1.2", "1.2.0-pre"),
        (">1.2", "1.3.0-beta"),
        ("<=1.2.3", "1.2.3-beta"),
        ("^1.2.3", "1.2.3-beta"),
        ("=0.7.x", "0.7.0-asdf"),
        (">=0.7.x", "0.7.0-asdf"),
        ("<=0.7.x", "0.7.0-asdf"),
        ("1.0.0", "1.0.1"),
        (">=1.0.0", "0.0.0"),
        (">=1.0.0", "0.0.1"),
        (">=1.0.0", "0.1.0"),
        (">1.0.0", "0.0.1"),
        (">1.0.0", "0.1.0"),
        ("<=2.0.0", "3.0.0"),
        ("<=2.0.0", "2.9999.9999"),
        ("<=2.0.0", "2.2.9"),
        ("<2.0.0", "2.9999.9999"),
        ("<2.0.0", "2.2.9"),
        (">=0.1.97", "0.1.93"),
        ("0.1.20 || 1.2.4", "1.2.3"),
        (">=0.2.3 || <0.0.1", "0.0.3"),
        (">=0.2.3 || <0.0.1", "0.2.2"),
        ("2.x.x", "1.1.3"),
        ("2.x.x", "3.1.3"),
        ("1.2.x", "1.3.3"),
        ("1.2.x || 2.x", "3.1.3"),
        ("1.2.x || 2.x", "1.1.3"),
        ("2.*.*", "1.1.3"),
        ("2.*.*", "3.1.3"),
        ("1.2.*", "1.3.3"),
        ("1.2.* || 2.*", "3.1.3"),
        ("1.2.* || 2.*", "1.1.3"),
        ("2", "1.1.2"),
        ("2.3", "2.4.1"),
        ("~0.0.1", "0.1.0-alpha"),
        ("~0.0.1", "0.1.0"),
        ("~2.4", "2.5.0"),
        ("~2.4", "2.3.9"),
        ("~>3.2.1", "3.3.2"),
        ("~>3.2.1", "3.2.0"),
        ("~1", "0.2.3"),
        ("~>1", "2.2.3"),
        ("~1.0", "1.1.0"),
        ("<1", "1.0.0"),
        (">=1.2", "1.1.1"),
        ("~v0.5.4-beta", "0.5.4-alpha"),
        ("=0.7.x", "0.8.2"),
        (">=0.7.x", "0.6.2"),
        ("<0.7.x", "0.7.2"),
        ("<1.2.3", "1.2.3-beta"),
        ("=1.2.3", "1.2.3-beta"),
        (">1.2", "1.2.8"),
        ("^0.0.1", "0.0.2-alpha"),
        ("^0.0.1", "0.0.2"),
        ("^1.2.3", "2.0.0-alpha"),
        ("^1.2.3", "1.2.2"),
        ("^1.2", "1.1.9"),
        ("^1.2.3", "2.0.0-pre"),
        ("^1.0.0", "1.0.0-rc1"),
        ("^1.0.0", "2.0.0-rc1"),
        ("^1.2.3-rc2", "2.0.0"),
        ("*", "1.2.3-foo"),
        (">*", "1.0.0"),
    ],
)
def test_range_excludes(constraint: str, version: str) -> None:
    assert not NPM.satisfies(constraint, version)


@pytest.mark.parametrize(
    ("constraint", "version", "expected"),
    [
        # Une pré-version n'entre que par un comparateur qui en porte une sur la même version.
        (">1.2.3-alpha.3", "1.2.3-alpha.7", True),
        (">1.2.3-alpha.3", "3.4.5", True),
        (">1.2.3-alpha.3", "3.4.5-alpha.9", False),
        ("~1.2.3-beta.2", "1.2.3-beta.4", True),
        ("~1.2.3-beta.2", "1.2.4-beta.2", False),
        ("^1.2.3-beta.2", "1.2.3-beta.4", True),
        ("^1.2.3-beta.2", "1.2.4-beta.2", False),
        ("^0.0.3-beta", "0.0.3-pr.2", True),
        ("^0.0.3-beta", "0.0.4-pr.2", False),
    ],
)
def test_prerelease_rule(constraint: str, version: str, expected: bool) -> None:
    assert NPM.satisfies(constraint, version) is expected


@pytest.mark.parametrize(
    ("constraint", "lowest"),
    [
        # Les cas de semver.minVersion…
        ("1.0.0", "1.0.0"),
        ("1.0", "1.0.0"),
        ("1.0.x", "1.0.0"),
        ("1.0.*", "1.0.0"),
        ("1", "1.0.0"),
        ("1.x.x", "1.0.0"),
        ("1.*.x", "1.0.0"),
        ("=1.0.0", "1.0.0"),
        ("~1.1.1", "1.1.1"),
        ("~1.1.1-beta", "1.1.1-beta"),
        ("~1.1.1 || >=2", "1.1.1"),
        ("^1.1.1", "1.1.1"),
        ("^1.1.1-beta", "1.1.1-beta"),
        ("^1.1.1 || >=2", "1.1.1"),
        ("^2.16.2 ^2.16", "2.16.2"),
        ("1.1.1 - 1.8.0", "1.1.1"),
        ("1.1 - 1.8.0", "1.1.0"),
        (">=1.1.1 <2 || >=2.2", "1.1.1"),
        (">1.0.0", "1.0.1"),
        (">1.0.0-0", "1.0.0-0.0"),
        (">1.0.0-beta", "1.0.0-beta.0"),
        (">2 || >1.0.0", "1.0.1"),
        (">2 || >1.0.0-0", "1.0.0-0.0"),
        (">2 || >1.0.0-beta", "1.0.0-beta.0"),
        (">4 <3", None),
        # … sauf sans borne basse : None au lieu de 0.0.0.
        ("*", None),
        ("", None),
        ("<2", None),
        ("^1.0.0 || <0.5", None),
        ("^0", None),
        (">=0.0.0", None),
        # Les plages du 0.x qui ont une borne
        ("^0.2.3", "0.2.3"),
        ("~0.2", "0.2.0"),
    ],
)
def test_lower_bound(constraint: str, lowest: str | None) -> None:
    assert NPM.lower_bound(constraint) == lowest


@pytest.mark.parametrize(
    ("constraint", "version"),
    [
        ("1.2.3", "1.2.3"),
        ("=1.2.3", "1.2.3"),
        ("v1.2.3", "1.2.3"),
        ("1.2.3-beta.1", "1.2.3-beta.1"),
        ("1.2", None),
        ("1.2.x", None),
        ("^1.2.3", None),
        (">=1.2.3", None),
        ("1.2.3 || 1.2.4", None),
        ("*", None),
        ("latest", None),
    ],
)
def test_exact(constraint: str, version: str | None) -> None:
    assert NPM.exact(constraint) == version


@pytest.mark.parametrize("tag", ["latest", "next", "beta", "v4-lts", "legacy_2"])
def test_a_tag_follows_the_registry(tag: str) -> None:
    """Une étiquette ne borne rien : toutes les versions la respectent, pré-versions
    comprises (c'est le registre qui dit laquelle installer), et pas de borne basse."""
    constraint = NPM.parse_constraint(tag)
    assert constraint.tag == tag
    assert NPM.satisfies(tag, "0.0.1")
    assert NPM.satisfies(tag, "3.0.0-rc.1")
    assert NPM.lower_bound(tag) is None


def test_an_empty_constraint_is_any_version() -> None:
    assert str(NPM.parse_constraint("  ")) == "*"
    assert NPM.satisfies("", "5.0.0")
    assert not NPM.satisfies("", "5.0.0-beta")


@pytest.mark.parametrize("constraint", ["catalog:", "catalog:react18", "Catalog:default"])
def test_a_catalog_alone_cannot_be_interpreted(constraint: str) -> None:
    with pytest.raises(InvalidConstraint, match=r"pnpm-workspace\.yaml"):
        NPM.parse_constraint(constraint)


@pytest.mark.parametrize(
    "constraint",
    ["^", ">=", "1.2.3.4", ">=1.2.3<2", "1.2.3 -", "- 1.2.3", "^1.2.3 >=", "git+https://x/y.git",
     "workspace:*", "npm:ms@1.0.0", "1.2.3 - 2.3.4 - 5", "~~1.2", "!1.2.3", "4-lts"],
)  # fmt: skip
def test_invalid_ranges(constraint: str) -> None:
    with pytest.raises(InvalidConstraint):
        NPM.parse_constraint(constraint)


def test_satisfies_needs_a_published_version() -> None:
    with pytest.raises(InvalidVersion):
        NPM.satisfies("^1.0.0", "1.2")
