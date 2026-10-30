"""Versions Go : semver avec ``v``, pseudo-versions, ``+incompatible``, chemins de majeure.

``GO_ORDER`` et ``GO_PATHS`` ont été relevés le 2026-10-30 avec Go 1.27.3 et
``golang.org/x/mod`` v0.29.0 (``semver.Compare``, ``module.IsPseudoVersion``, ``module.Check``),
le paquet dont se sert ``go``.
"""

import pytest

from forceupdate import versions
from forceupdate.models import Ecosystem, Gap
from forceupdate.versions import InvalidConstraint, InvalidVersion
from forceupdate.versions.go import GO, canonical, is_pseudo, module_path, path_major

GO_ORDER = [
    ("v0.0.0-20200313102051-9f266ea9e77c", True),
    ("v1.0.0-alpha", False),
    ("v1.0.0-alpha.beta", False),
    ("v1.0.0-rc.1", False),
    ("v1.0.0-rc.2", False),
    ("v1.0.0-rc.10", False),
    ("v1.2.3-pre", False),
    ("v1.2.3-pre.0.20230101120000-abcdef123456", True),
    ("v1.2.3", False),
    ("v1.2.4-0.20220101120000-abcdef123456", True),
    ("v1.2.4-0.20230101120000-abcdef123456", True),
    ("v1.2.4", False),
    ("v1.9.9", False),
    ("v1.10.0", False),
    ("v2.0.0+incompatible", False),
    ("v3.0.0-20220521103104-8f96da9f5d5e", True),
    ("v3.0.0", False),
    ("v4.0.0-rc2+incompatible", False),
    ("v4.0.0+incompatible", False),
]
"""Des versions dans l'ordre de ``semver.Compare``, et si ``module.IsPseudoVersion`` y voit une
pseudo-version."""

GO_PATHS = [
    ("github.com/foo/bar", "v1.2.3", True),
    ("github.com/foo/bar", "v0.1.0", True),
    ("github.com/foo/bar", "v2.0.0", False),
    ("github.com/foo/bar", "v2.0.0+incompatible", True),
    ("github.com/foo/bar", "v3.0.1", False),
    ("github.com/foo/bar/v2", "v2.0.0", True),
    ("github.com/foo/bar/v2", "v1.2.3", False),
    ("github.com/foo/bar/v2", "v3.0.1", False),
    ("gopkg.in/yaml.v3", "v3.0.1", True),
    ("gopkg.in/yaml.v3", "v2.0.0", False),
    ("gopkg.in/user/pkg.v1", "v1.2.3", True),
    ("gopkg.in/user/pkg.v1", "v2.0.0", False),
]
"""Des versions, et si ``module.Check`` les accepte sous ce chemin."""


def test_registered_for_go() -> None:
    assert versions.for_ecosystem(Ecosystem.GO) is GO


def test_order_follows_go() -> None:
    texts = [text for text, _ in GO_ORDER]
    assert sorted(reversed(texts), key=GO.sort_key) == texts


@pytest.mark.parametrize(("version", "pseudo"), GO_ORDER)
def test_pseudo_versions(version: str, pseudo: bool) -> None:
    assert is_pseudo(version) is pseudo
    assert GO.unlisted(version) is pseudo


@pytest.mark.parametrize(("path", "version", "accepted"), GO_PATHS)
def test_major_paths_follow_go(path: str, version: str, accepted: bool) -> None:
    assert (GO.moved(path, version) is None) is accepted


@pytest.mark.parametrize(
    ("path", "version", "moved"),
    [
        ("github.com/go-chi/chi", "v5.2.3", "github.com/go-chi/chi/v5"),
        ("github.com/golang-jwt/jwt/v4", "v5.3.0", "github.com/golang-jwt/jwt/v5"),
        ("github.com/foo/bar/v3", "v1.0.0", "github.com/foo/bar"),
        ("gopkg.in/yaml.v2", "v3.0.1", "gopkg.in/yaml.v3"),
        ("gopkg.in/pkg.v1-unstable", "v2.0.0", "gopkg.in/pkg.v2-unstable"),
    ],
)
def test_moved_gives_the_other_path(path: str, version: str, moved: str) -> None:
    assert GO.moved(path, version) == moved


@pytest.mark.parametrize(
    ("path", "major"),
    [
        ("github.com/foo/bar", None),
        ("github.com/foo/bar/v2", 2),
        ("github.com/foo/bar/v10", 10),
        ("github.com/foo/bar/v1", None),
        ("github.com/foo/bar/v0", None),
        ("gopkg.in/yaml.v3", 3),
        ("gopkg.in/check.v1", 1),
        ("gopkg.in/user/pkg.v0", 0),
    ],
)
def test_path_major(path: str, major: int | None) -> None:
    assert path_major(path) == major


def test_module_path_for_a_major() -> None:
    assert module_path("github.com/foo/bar", 2) == "github.com/foo/bar/v2"
    assert module_path("github.com/foo/bar", 1) == "github.com/foo/bar"
    assert module_path("github.com/foo/bar", 4, incompatible=True) == "github.com/foo/bar"
    assert module_path("github.com/foo/bar/v2", 2) == "github.com/foo/bar/v2"
    assert module_path("gopkg.in/yaml.v2", 3) == "gopkg.in/yaml.v3"


def test_osv_versions_without_v() -> None:
    assert GO.compare("0.3.8", "v0.3.8") == 0
    assert GO.compare("v0.3.7", "0.3.8") == -1
    assert canonical("0.3.8") == "v0.3.8"
    assert canonical("v0.3.8") == "v0.3.8"


def test_incompatible_is_build_metadata() -> None:
    assert GO.compare("v2.0.0+incompatible", "v2.0.0") == 0
    assert GO.compare("v4.1.2+incompatible", "v1.5.5") == 1


@pytest.mark.parametrize("text", ["1.2", "v1.2", "v01.2.3", "v1.2.3-01", "v1.2.3-", "", "latest"])
def test_versions_are_strict(text: str) -> None:
    with pytest.raises(InvalidVersion):
        GO.parse(text)


# -- une version de go.mod n'est pas une plage ---------------------------------------------


def test_a_requirement_accepts_only_its_version() -> None:
    assert GO.satisfies("v1.3.0", "v1.3.0")
    assert not GO.satisfies("v1.3.0", "v1.3.1")
    assert not GO.satisfies("v1.3.0", "v1.2.9")
    assert GO.lower_bound("v1.3.0") == "v1.3.0"
    assert GO.exact("v1.3.0") == "v1.3.0"
    assert GO.exact("v0.0.0-20200313102051-9f266ea9e77c") == "v0.0.0-20200313102051-9f266ea9e77c"


def test_max_satisfying_is_the_written_version() -> None:
    published = ["v1.3.0", "v1.4.0", "v1.6.0"]
    assert GO.max_satisfying("v1.3.0", published) == "v1.3.0"
    assert GO.max_satisfying("v1.3.1", published) is None


@pytest.mark.parametrize("text", ["", "^1.2.3", ">=v1.2.3", "v1.2", "master"])
def test_unreadable_requirements(text: str) -> None:
    with pytest.raises(InvalidConstraint):
        GO.parse_constraint(text)


# -- écart et candidates -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("current", "target", "gap"),
    [
        ("v1.3.0", "v1.6.0", Gap.MINOR),
        ("v4.4.0", "v4.5.2", Gap.MINOR),
        ("v1.5.4", "v1.5.5", Gap.PATCH),
        ("v1.5.4", "v5.2.3", Gap.MAJOR),
        ("v0.3.7", "v0.3.8", Gap.PATCH),
        ("v0.3.7", "v0.41.0", Gap.MAJOR),  # 0.x : la mineure joue le rôle de la majeure
        ("v1.2.4-0.20230101120000-abcdef123456", "v1.2.4", Gap.PATCH),
        ("v1.2.4-0.20230101120000-abcdef123456", "v1.3.0", Gap.MINOR),
        ("v3.0.0-20200313102051-9f266ea9e77c", "v3.0.0", Gap.MAJOR),
    ],
)
def test_gap(current: str, target: str, gap: Gap) -> None:
    assert GO.gap(current, target) is gap


def test_candidates_drop_prereleases_but_keep_pseudo_versions_of_the_same_base() -> None:
    published = ["v0.0.0-20240101000000-aaaaaaaaaaaa", "v0.1.0-rc.1"]
    assert GO.candidates(published) == []
    current = "v0.0.0-20230101000000-bbbbbbbbbbbb"
    assert GO.candidates(published, current) == ["v0.0.0-20240101000000-aaaaaaaaaaaa"]
