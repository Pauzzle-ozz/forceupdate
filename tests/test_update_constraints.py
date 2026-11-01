"""Réécrire une contrainte pour une nouvelle version, en gardant son style : un tableau de cas
par style, pour npm, pour PyPI (PEP 440 et Poetry), pour Cargo, Go, Composer et RubyGems."""

import pytest

from forceupdate import versions
from forceupdate.models import Ecosystem
from forceupdate.update.constraints import rewrite

NPM = Ecosystem.NPM
PYPI = Ecosystem.PYPI
CARGO = Ecosystem.CRATES_IO


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
    check_floor(ecosystem, constraint, target, expected)


def check_floor(ecosystem: Ecosystem, constraint: str, target: str, expected: str) -> None:
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
    assert rewrite(CARGO, "~>1.2", "1.3.0") is None


# -- Cargo --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("constraint", "target", "expected"),
    [
        # Sans opérateur, c'est un ^ : il reste sans opérateur, la précision gardée quand rien
        # ne se perd.
        ("1.2.3", "1.4.0", "1.4.0"),
        ("1.0.100", "1.0.229", "1.0.229"),
        ("1.2", "1.4.0", "1.4"),
        ("1.2", "1.4.2", "1.4.2"),
        ("1", "2.0.0", "2"),
        ("1", "2.1.3", "2.1.3"),
        ("0.3", "0.4.2", "0.4.2"),
        ("0.8", "0.10.3", "0.10.3"),
        ("0", "1.2.0", "1.2.0"),
        # ^ et ~ : la version visée derrière le même opérateur.
        ("^1.2", "2.0.0", "^2.0"),
        ("^1.2.3", "1.5.0", "^1.5.0"),
        ("~1.2.3", "1.3.1", "~1.3.1"),
        ("~1", "2.3.0", "~2"),  # ~1 va jusqu'à 2 : la précision reste
        # = : une version exacte ; =1.2 veut dire 1.2.*, sa précision reste.
        ("=1.5.4", "1.13.1", "=1.13.1"),
        ("=1.6.0", "1.16.4", "=1.16.4"),
        ("=1.2", "1.3.1", "=1.3"),
        # Jokers.
        ("1.2.*", "1.3.1", "1.3.*"),
        ("1.*", "2.0.4", "2.*"),
        ("0.1.x", "0.2.0", "0.2.x"),
        # Plusieurs bornes, séparées par des virgules : les espaces gardés.
        (">=1.2, <1.5", "1.7.2", ">=1.7.2, <1.8"),
        (">= 1.2 , < 2", "2.1.0", ">= 2.1 , < 3"),
        (">=1.2, <2", "1.7.0", ">=1.7, <2"),
        (">1.2", "1.4.0", ">=1.4"),
        ("<=1.2", "1.5.0", "<=1.6"),  # la borne haute passe au cran au-dessus, comme pour PyPI
        ("*", "1.0.0", None),
    ],
)
def test_cargo_styles(constraint: str, target: str, expected: str | None) -> None:
    check(CARGO, constraint, target, expected)


@pytest.mark.parametrize(
    ("constraint", "target", "expected"),
    [
        ("=1.2", "1.3.1", "=1.3, >=1.3.1"),
        ("0.1.*", "0.2.3", "0.2.*, >=0.2.3"),
        ("~1", "2.3.4", "~2, >=2.3.4"),
        ("0", "0.3.1", "0, >=0.3.1"),
        # Sinon, rien de plus.
        ("=1.5.4", "1.5.5", "=1.5.5"),
        ("0.1", "0.2.23", "0.2.23"),
        ("1.0.50", "1.0.103", "1.0.103"),
    ],
)
def test_cargo_floor_for_a_vulnerability(constraint: str, target: str, expected: str) -> None:
    check_floor(CARGO, constraint, target, expected)


# -- Go : une version de go.mod n'est pas une plage -----------------------------------------

GO = Ecosystem.GO


@pytest.mark.parametrize(
    ("constraint", "target", "expected"),
    [
        ("v1.3.0", "v1.6.0", "v1.6.0"),
        ("v4.4.0", "v4.5.2", "v4.5.2"),
        ("v3.0.0-20200313102051-9f266ea9e77c", "v3.0.1", "v3.0.1"),
        ("v1.5.4", "v1.5.5", "v1.5.5"),
        ("v4.1.2+incompatible", "v4.1.3+incompatible", "v4.1.3+incompatible"),
        ("v0.3.7", "0.3.8", "v0.3.8"),  # une version écrite comme dans un avis d'OSV
        # Illisible : à réécrire à la main.
        ("master", "v1.0.0", None),
        ("v1.0.0", "latest", None),
    ],
)
def test_go_versions(constraint: str, target: str, expected: str | None) -> None:
    check(GO, constraint, target, expected)
    check(GO, constraint, target, expected, floor=True)


# -- Composer : une version nue est exacte, ~ va jusqu'à la majeure suivante ------------------

COMPOSER = Ecosystem.PACKAGIST


@pytest.mark.parametrize(
    ("constraint", "target", "expected"),
    [
        # Une version nue est exacte, sa précision gardée quand rien ne se perd.
        ("7.4.0", "7.16.1", "7.16.1"),
        ("1.2", "1.3.0", "1.3"),
        ("1.2", "1.5.3", "1.5.3"),
        ("==1.2.3", "1.2.9", "==1.2.9"),
        ("1.2.3.4", "1.2.3.5", "1.2.3.5"),
        # Le v de Packagist (Symfony) n'est écrit que si la contrainte en avait un.
        ("5.4.0", "v5.4.47", "5.4.47"),
        ("v5.4.0", "v5.4.47", "v5.4.47"),
        ("^5.4", "v5.4.47", "^5.4.47"),
        # ^ comme npm.
        ("^2.3", "2.9.3", "^2.9.3"),
        ("^2.3", "3.12.1", "^3.12.1"),
        ("^1.0", "2.0.0", "^2.0"),
        ("^0.3", "0.4.1", "^0.4.1"),
        # ~1.2 va jusqu'à 2.0 : sa précision reste ; ~1.2.3 (jusqu'à 1.3) prend la version visée.
        ("~5.4", "5.4.47", "~5.4"),
        ("~5.4", "6.4.49", "~6.4"),
        ("~1", "2.3.4", "~2"),
        ("~5.4.10", "5.4.47", "~5.4.47"),
        ("~5.4.10", "6.0.3", "~6.0.3"),
        # Jokers.
        ("3.4.*", "3.4.3", "3.4.*"),
        ("3.4.*", "3.30.0", "3.30.*"),
        ("1.*", "2.3.0", "2.*"),
        # Unions (|| et |) : le membre qui accepte la version visée, ou le dernier.
        ("^1.1 || ^2.0", "3.0.2", "^3.0.2"),
        ("^6.0|^7.0", "7.2.0", "^7.2"),
        # Bornes, séparées par une espace ou une virgule.
        (">=1.2 <2.0", "2.3.0", ">=2.3 <3.0"),
        (">=1.2,<2.0", "1.5.0", ">=1.5,<2.0"),
        ("!=1.5.0 ^1.0", "1.6.0", "!=1.5.0 ^1.6"),
        # Un intervalle.
        ("1.0 - 2.0", "2.3.0", "2.3.0 - 2.3"),
        ("1.0 - 3.0", "2.3.0", "2.3.0 - 3.0"),
        # Un drapeau de stabilité est gardé.
        ("^1.0@beta", "1.4.0", "^1.4@beta"),
        # Rien à réécrire : une branche, *.
        ("dev-master", "1.0.0", None),
        ("*", "1.0.0", None),
    ],
)
def test_composer_styles(constraint: str, target: str, expected: str | None) -> None:
    check(COMPOSER, constraint, target, expected)


@pytest.mark.parametrize(
    ("constraint", "target", "expected"),
    [
        ("~5.4", "5.4.47", "~5.4, >=5.4.47"),
        ("~1.2", "1.2.9", "~1.2, >=1.2.9"),
        ("3.4.*", "3.4.3", "3.4.*, >=3.4.3"),
        # Sinon, rien de plus.
        ("^2.3", "2.9.3", "^2.9.3"),
        ("7.4.0", "7.4.5", "7.4.5"),
    ],
)
def test_composer_floor_for_a_vulnerability(constraint: str, target: str, expected: str) -> None:
    check_floor(COMPOSER, constraint, target, expected)


# -- RubyGems : = par défaut, ~> garde sa précision, une chaîne par contrainte ---------------

RUBYGEMS = Ecosystem.RUBYGEMS


@pytest.mark.parametrize(
    ("constraint", "target", "expected"),
    [
        # Une version nue, ou =, est exacte.
        ("5.6.4", "5.6.9", "5.6.9"),
        ("= 1.2", "1.3.0", "= 1.3"),
        ("= 1.2", "1.5.3", "= 1.5.3"),
        ("5.6.4", "2.2.8.1", "2.2.8.1"),
        # ~> garde sa précision : le nombre de nombres y fixe la borne haute.
        ("~> 2.2", "2.2.25", "~> 2.2"),
        ("~> 2.2", "4.2.1", "~> 4.2"),
        ("~> 2.2.3", "2.2.25", "~> 2.2.25"),
        ("~> 2.2.3", "2.2.8.1", "~> 2.2.8"),
        ("~> 2.2.3", "3.2.8", "~> 3.2.8"),
        ("~> 1", "2.3.0", "~> 2"),
        ("~>1.2", "1.5.0", "~>1.5"),
        # Bornes, et plusieurs contraintes.
        (">= 2.0", "3.1.0", ">= 3.1"),
        (">= 1.19.0, < 1.20", "1.19.4", ">= 1.19.4, < 1.20"),
        (">= 1.19.0, < 1.20", "1.21.2", ">= 1.21.2, < 1.22"),
        ("~> 2.2, != 2.2.4", "2.2.6", "~> 2.2, != 2.2.4"),
        ("> 2.0", "2.5.0", ">= 2.5"),
        # Sans contrainte : rien à réécrire. >= 0 est une borne basse comme une autre.
        ("", "1.0.0", None),
        (">= 0", "1.0.0", ">= 1"),
    ],
)
def test_rubygems_styles(constraint: str, target: str, expected: str | None) -> None:
    check(RUBYGEMS, constraint, target, expected)


@pytest.mark.parametrize(
    ("constraint", "target", "expected"),
    [
        # La forme des avis de sécurité de Rails : ~> X.Y.Z, >= X.Y.Z.W.
        ("~> 2.2.3", "2.2.8.1", "~> 2.2.8, >= 2.2.8.1"),
        ("~> 2.2", "2.2.3", "~> 2.2, >= 2.2.3"),
        ("~> 2.2", "4.2.1", "~> 4.2, >= 4.2.1"),
        # Sinon, rien de plus.
        ("~> 2.2.3", "2.2.25", "~> 2.2.25"),
        ("5.6.4", "5.6.9", "5.6.9"),
    ],
)
def test_rubygems_floor_for_a_vulnerability(constraint: str, target: str, expected: str) -> None:
    check_floor(RUBYGEMS, constraint, target, expected)


# -- Maven et Gradle : une version nue est la version utilisée, les plages de VersionRange -----

MAVEN = Ecosystem.MAVEN


@pytest.mark.parametrize(
    ("constraint", "target", "expected"),
    [
        # Une version nue devient la version visée, telle que la publie le dépôt.
        ("2.14.1", "2.17.1", "2.17.1"),
        ("30.1-jre", "33.7.2-jre", "33.7.2-jre"),
        ("5.3.17", "5.3.39", "5.3.39"),
        ("23", "40", "40"),
        ("1.7.15!!", "1.7.36", "1.7.36!!"),
        ("[1.2.3]", "1.2.9", "[1.2.9]"),
        # Un intervalle : sa borne basse monte, une borne haute dépassée se déplace.
        ("[1.9,2.0)", "1.15.0", "[1.15.0,2.0)"),
        ("[1.9,2.0)", "2.3.1", "[2.3.1,3.0)"),
        ("[1.9, 2.0)", "1.10.0", "[1.10.0, 2.0)"),
        ("(1.9,2.0]", "1.10.0", "[1.10.0,2.0]"),
        ("[1.0,1.5)", "1.7.2", "[1.7.2,1.8)"),
        ("[1.5,)", "2.0.1", "[2.0.1,)"),
        ("(,1.0]", "0.9", "(,1.0]"),
        ("(,1.0]", "2.1.0", "(,3.0]"),
        ("(,1.0],[1.2,)", "1.5.0", "[1.5.0,)"),
        ("[1.0,2.0[", "1.5", "[1.5,2.0["),
        # Gradle : un préfixe garde sa précision ; la dernière n'a pas de version.
        ("1.+", "2.3.4", "2.+"),
        ("1.2.+", "1.9.0", "1.9.+"),
        ("latest.release", "2.0", None),
        ("+", "2.0", None),
    ],
)
def test_maven_styles(constraint: str, target: str, expected: str | None) -> None:
    check(MAVEN, constraint, target, expected)


@pytest.mark.parametrize(
    ("constraint", "target", "expected"),
    [
        ("2.14.1", "2.17.1", "2.17.1"),
        ("[1.9,2.0)", "1.10.0", "[1.10.0,2.0)"),
        ("(,2.0)", "1.10.0", "[1.10.0,2.0)"),
    ],
)
def test_maven_floor_for_a_vulnerability(constraint: str, target: str, expected: str) -> None:
    check_floor(MAVEN, constraint, target, expected)


def test_a_gradle_prefix_cannot_take_a_floor() -> None:
    assert rewrite(MAVEN, "1.+", "1.9.2", floor=True) is None


# -- NuGet : NuGet prend la plus basse version qui convient --------------------------------------

NUGET = Ecosystem.NUGET


@pytest.mark.parametrize(
    ("constraint", "target", "expected"),
    [
        # Une version nue est un minimum, que NuGet prend : elle devient la version visée.
        ("12.0.1", "13.0.1", "13.0.1"),
        ("1.0", "2.0.0", "2.0"),
        ("1.0", "1.5.3", "1.5.3"),
        ("1.2.3.4", "1.2.3.5", "1.2.3.5"),
        ("4.5.0", "4.5.1-preview.1", "4.5.1-preview.1"),
        ("1.0.0-beta", "1.0.0", "1.0.0"),
        ("[1.2.3]", "1.4.0", "[1.4.0]"),
        # Un intervalle : la borne basse devient la version visée, incluse ; une borne haute
        # dépassée se déplace au même niveau.
        ("[1.0,2.0)", "1.5.3", "[1.5.3,2.0)"),
        ("(1.0,2.0)", "1.5.3", "[1.5.3,2.0)"),
        ("(,2.0]", "1.5.3", "[1.5.3,2.0]"),
        ("[1.0, 2.0)", "2.3.1", "[2.3.1, 3.0)"),
        ("[1.0,)", "3.1.0", "[3.1.0,)"),
        # Une version flottante garde sa précision.
        ("1.*", "1.5.0", "1.*"),
        ("1.*", "2.3.1", "2.*"),
        ("1.2.*", "2.3.1", "2.3.*"),
        ("1.2.3.*", "1.2.4.0", "1.2.4.*"),
        ("1.0.0-beta.*", "2.3.1", "2.3.1-beta.*"),
        ("1.*-*", "2.0.0", "2.*-*"),
        ("[1.0.*, 2.0)", "2.1.0", "[2.1.*, 3.0)"),
        # Rien à réécrire, ou rien de lisible.
        ("*", "3.0.0", None),
        ("*-*", "3.0.0", None),
        ("$(Version)", "1.0.0", None),
        ("", "1.0.0", None),
    ],
)
def test_nuget_styles(constraint: str, target: str, expected: str | None) -> None:
    check(NUGET, constraint, target, expected)


@pytest.mark.parametrize(
    ("constraint", "target", "expected"),
    [
        ("12.0.1", "13.0.1", "13.0.1"),
        ("[1.0,2.0)", "1.5.3", "[1.5.3,2.0)"),
        ("(,2.0)", "1.10.0", "[1.10.0,2.0)"),
    ],
)
def test_nuget_floor_for_a_vulnerability(constraint: str, target: str, expected: str) -> None:
    check_floor(NUGET, constraint, target, expected)


def test_a_nuget_floating_version_needs_no_floor() -> None:
    """NuGet prend la plus haute de ce que désigne une version flottante : pas de plancher."""
    assert rewrite(NUGET, "1.*", "2.3.1", floor=True) == "2.*"
    assert rewrite(NUGET, "1.2.*", "1.2.9", floor=True) == "1.2.*"
