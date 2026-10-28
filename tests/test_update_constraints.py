"""Réécrire une contrainte pour une nouvelle version, en gardant son style : un tableau de cas
par style, pour npm puis pour PyPI (PEP 440 et Poetry)."""

import pytest

from forceupdate import versions
from forceupdate.models import Ecosystem
from forceupdate.update.constraints import rewrite

NPM = Ecosystem.NPM
PYPI = Ecosystem.PYPI


def check(ecosystem: Ecosystem, constraint: str, target: str, expected: str | None, **kw: bool):
    result = rewrite(ecosystem, constraint, target, **kw)
    assert result == expected
    if result is not None:
        scheme = versions.for_ecosystem(ecosystem)
        assert scheme.satisfies(result, target)


@pytest.mark.parametrize(
    ("constraint", "target", "expected"),
    [
        # ^ : la version visée derrière le même opérateur.
        ("^4.17.0", "4.21.2", "^4.21.2"),  # l'exemple du brief
        ("^4.17.0", "5.1.2", "^5.1.2"),
        ("^4.17", "5.0.0", "^5.0"),  # la précision est gardée quand rien ne se perd
        ("^4.17", "5.0.3", "^5.0.3"),  # sinon la version entière : même borne haute
        ("^1", "2.0.0", "^2"),
        ("^1", "2.3.4", "^2.3.4"),
        ("^0.2.3", "0.3.1", "^0.3.1"),
        ("^0.2", "0.3.1", "^0.3.1"),
        ("^0", "0.3.1", "^0"),  # ^0.3.1 n'irait plus que jusqu'à 0.4
        ("^0", "1.2.0", "^1.2.0"),
        ("^0.0.3", "0.0.4", "^0.0.4"),
        ("^1.0.0-beta.2", "1.2.0", "^1.2.0"),
        ("^ 1.2.3", "2.0.0", "^ 2.0.0"),
        # ~ et ~>
        ("~1.2.3", "1.3.0", "~1.3.0"),
        ("~1.2", "1.3.5", "~1.3.5"),
        ("~1", "2.0.0", "~2"),
        ("~1", "2.3.4", "~2"),  # ~2.3.4 n'irait plus que jusqu'à 2.4
        ("~>1.2.3", "1.4.0", "~>1.4.0"),
        # version exacte, avec ou sans préfixe
        ("4.17.15", "4.18.1", "4.18.1"),
        ("=4.17.15", "4.18.1", "=4.18.1"),
        ("v1.2.3", "2.0.0", "v2.0.0"),
        ("1.0.0-rc.1", "1.0.0", "1.0.0"),
        # bornes basses et hautes
        (">=1.2.3", "1.4.0", ">=1.4.0"),
        (">= 1.2.3", "1.4.0", ">= 1.4.0"),
        (">1.2.0", "1.5.0", ">=1.5.0"),  # « > » excluerait la version visée
        (">=1.2.0 <2.0.0", "1.5.0", ">=1.5.0 <2.0.0"),
        (">=1.2.0 <2.0.0", "2.1.0", ">=2.1.0 <3.0.0"),
        (">=1.2 <1.5", "1.7.2", ">=1.7.2 <1.8"),  # la borne haute fixait une mineure
        ("<2.0.0", "2.1.0", "<3.0.0"),
        ("<=1.5", "1.7.2", "<=1.8"),
        ("<2.0.0-0", "2.1.0", "<3.0.0-0"),
        # jokers et versions partielles : la précision a un sens
        ("1.x", "2.3.1", "2.x"),
        ("1.2.x", "1.3.4", "1.3.x"),
        ("1.*", "2.3.1", "2.*"),
        ("1.2", "1.3.4", "1.3"),
        ("1", "2.3.4", "2"),
        ("1.x.x", "2.0.1", "2.x.x"),
        # intervalles
        ("1.2.3 - 2.3", "2.5.1", "2.5.1 - 2.5"),
        ("1.2.3 - 2", "3.0.1", "3.0.1 - 3"),
        ("1.2.3 - 2.3.4", "2.0.0", "2.0.0 - 2.3.4"),
        ("1.2.3 - 2.3.4", "2.5.1", None),  # fin complète dépassée : pas de règle évidente
        # unions : le membre qui l'accepte, ou le dernier, réécrit
        ("^1 || ^2", "3.1.0", "^3.1.0"),
        ("^1.0.0 || ^2.0.0", "2.5.0", "^2.5.0"),
        ("1.x || >=2.5.0 <3", "3.0.1", ">=3.0.1 <4"),
        # sans version : rien à réécrire
        ("*", "2.0.0", None),
        ("", "2.0.0", None),
        ("x", "2.0.0", None),
        ("latest", "2.0.0", None),
    ],
)
def test_npm_styles(constraint: str, target: str, expected: str | None) -> None:
    check(NPM, constraint, target, expected)


@pytest.mark.parametrize(
    ("constraint", "target", "expected"),
    [
        # PEP 440 : versions exactes
        ("==0.12", "0.12.5", "==0.12.5"),
        ("==0.12", "2.2.5", "==2.2.5"),
        ("==1.2", "1.3.0", "==1.3"),
        ("===1.0", "1.1", "===1.1"),
        # bornes, avec la mise en forme d'origine
        (">=0.12", "2.2.5", ">=2.2.5"),
        (">1.2", "1.4", ">=1.4"),
        (">=2.25,<3", "3.1", ">=3.1,<4"),
        (">= 2.25, < 3", "3.1.2", ">= 3.1.2, < 4"),
        (">=0.40.0,<1.0.0", "2.3.0", ">=2.3.0,<3.0.0"),
        (">=1.2,<1.5", "1.7.2", ">=1.7.2,<1.8"),
        ("<0.110", "0.115.2", "<0.116"),
        (">=3.8,<4", "4.0.1", ">=4.0.1,<5"),
        (">=1.0,!=1.5", "2.0", ">=2.0,!=1.5"),  # « != » est gardé
        (">=2.8.0", "2.9.0.post0", ">=2.9.0.post0"),
        (">=6.0", "6.0.12.20260906", ">=6.0.12.20260906"),
        # ~= : la précision dit jusqu'où on peut monter
        ("~=1.4", "1.9.2", "~=1.9"),
        ("~=1.4.2", "1.4.7", "~=1.4.7"),
        ("~=1.4.2", "2.0.1", "~=2.0.1"),
        ("~= 1.4", "2.0", "~= 2.0"),
        # jokers
        ("==1.2.*", "1.3.4", "==1.3.*"),
        ("!=1.5.*,>=1.0", "2.0", "!=1.5.*,>=2.0"),
        # Poetry
        ("^1.2", "2.0.0", "^2.0"),
        ("^1.2.3", "2.1.0", "^2.1.0"),
        ("^0.2", "0.3.1", "^0.3.1"),
        ("~1.2", "1.3.5", "~1.3.5"),
        ("~1", "2.3.4", "~2"),
        ("6.0.2", "6.0.3", "6.0.3"),
        ("=6.0.2", "6.1.0", "=6.1.0"),
        ("1.2.*", "1.3.0", "1.3.*"),
        (">= 1.2 < 2.0", "2.1", ">= 2.1 < 3.0"),
        ("^1.2 || ^2.0", "3.0.1", "^3.0.1"),
        ("*", "1.0", None),
    ],
)
def test_pypi_styles(constraint: str, target: str, expected: str | None) -> None:
    check(PYPI, constraint, target, expected)


@pytest.mark.parametrize(
    ("ecosystem", "constraint", "target", "expected"),
    [
        # Pour une faille, la borne basse doit atteindre la version visée : quand le style ne le
        # permet pas, une borne « >= » s'ajoute.
        (NPM, "~1", "2.3.4", "~2 >=2.3.4"),
        (NPM, "1.2.x", "1.3.4", "1.3.x >=1.3.4"),
        (NPM, "^0", "0.3.1", "^0 >=0.3.1"),
        (PYPI, "~=1.4", "1.9.2", "~=1.9,>=1.9.2"),
        (PYPI, "==1.2.*", "1.3.4", "==1.3.*,>=1.3.4"),
        (PYPI, "~=2.8.0", "2.9.0.post0", "~=2.9.0,>=2.9.0.post0"),
        # Sinon, rien de plus.
        (NPM, "^4.17.0", "4.17.21", "^4.17.21"),
        (NPM, "4.17.15", "4.18.1", "4.18.1"),
        (PYPI, ">=0.12", "2.2.5", ">=2.2.5"),
        (PYPI, "~=1.4.2", "1.4.7", "~=1.4.7"),
        (PYPI, "^1.2", "2.0.0", "^2.0"),
    ],
)
def test_floor_for_a_vulnerability(
    ecosystem: Ecosystem, constraint: str, target: str, expected: str
) -> None:
    check(ecosystem, constraint, target, expected, floor=True)
    scheme = versions.for_ecosystem(ecosystem)
    lower = scheme.lower_bound(expected)
    assert lower is not None
    assert scheme.compare(lower, target) >= 0


@pytest.mark.parametrize(
    ("constraint", "target", "expected"),
    [
        # Une dépendance pair : la plage s'élargit.
        ("^17.0.0 || ^18.0.0", "19.1.0", "^17.0.0 || ^18.0.0 || ^19.1.0"),
        ("^17||^18", "19.0.0", "^17||^18||^19"),
        ("^17.0.0 || ^18.0.0", "18.3.1", "^17.0.0 || ^18.0.0"),  # déjà acceptée : rien
        ("^18.0.0", "19.1.0", "^18.0.0 || ^19.1.0"),
        (">=16.8 <19", "19.1.0", ">=16.8 <19 || >=19.1 <20"),
        ("^18.0.0", "18.3.1", "^18.0.0"),
    ],
)
def test_widen_a_union(constraint: str, target: str, expected: str) -> None:
    check(NPM, constraint, target, expected, widen=True)


def test_an_exclusion_of_the_target_cannot_be_kept() -> None:
    assert rewrite(PYPI, ">=1.0,!=2.0", "2.0") is None


def test_an_unreadable_constraint_or_target() -> None:
    assert rewrite(NPM, "^1.2.3", "pas-une-version") is None
    assert rewrite(PYPI, ">=1.0,<", "2.0") is None
