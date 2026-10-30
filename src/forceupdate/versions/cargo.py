"""Les versions Cargo (crates.io) : semver 2.0, et les contraintes de Cargo.

Les versions publiées sont du semver strict (``1.2.3``, ``1.0.0-beta.2``), comme pour npm,
mais sans ``v`` devant. Les contraintes suivent le crate ``semver`` dont se sert Cargo
(``VersionReq``), écrit ici à la main :

- des comparateurs séparés par des virgules, tous à respecter (``>=1.2, <1.5``) ; ni ``||``,
  ni espace comme séparateur ;
- **sans opérateur, c'est** ``^`` : ``1.2`` veut dire ``^1.2``, soit ``>=1.2.0, <2.0.0`` ;
- ``^`` et ``~`` comme npm, règles du 0.x comprises (``^0.2.3`` : ``>=0.2.3, <0.3.0``) ;
- ``=1.2`` veut dire ``1.2.*`` ; ``>1`` veut dire ``>=2.0.0``, ``<=1.2`` veut dire ``<1.3.0`` ;
- ``*`` seul accepte tout ; ``1.*`` et ``1.2.*`` (ou ``x``, ``X``) sont des jokers ; derrière un
  opérateur, un joker fait une version partielle (``^0.1.*`` est ``^0.1``, ``>=1.*`` est
  ``>=1``) ;
- une pré-version ne respecte une contrainte que si l'un de ses comparateurs porte sur le même
  ``major.minor.patch`` avec une pré-version : ``>=0.9.0-beta.0, <0.9.0`` accepte
  ``0.9.0-beta.3``, ``^1.2`` n'accepte aucune pré-version ;
- les métadonnées de build (``1.2.3+abc``) sont lues, et ne comptent pas.

Ce que Cargo refuse est illisible ici aussi : une contrainte vide, ``v1.2``, ``01.2``, ``~>1.2``,
``1.2 1.3``, ``1.2,``, ``^1 || ^2``, ``>=*``, ``1.*.3``, ``*, >1``.

Vérifié contre cargo 1.99 (``cargo generate-lockfile`` sur une quarantaine de contraintes de
``rand``) : voir les notes de E21 dans ``PLAN.md``. La version que choisit Cargo est la plus
haute qui respecte la contrainte, retirées exclues (``max_satisfying`` sur
``PackageInfo.available``) ; le résolveur 3 (édition 2024) préfère en plus celles dont le
``rust-version`` convient, ce qu'on ne sait pas ici.

``str()`` d'une contrainte donne sa forme normalisée, celle qu'affiche Cargo (``1.2`` →
``^1.2``).
"""

import functools
import re
from dataclasses import dataclass

from forceupdate.models import Ecosystem
from forceupdate.versions.base import Constraint, InvalidConstraint, InvalidVersion, VersionScheme
from forceupdate.versions.npm import SemVer

_NUMBER = r"0|[1-9]\d*"
_PRE_ID = r"(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
_BUILD_ID = r"[0-9A-Za-z-]+"

_VERSION = re.compile(
    rf"(?P<major>{_NUMBER})\.(?P<minor>{_NUMBER})\.(?P<patch>{_NUMBER})"
    rf"(?:-(?P<pre>{_PRE_ID}(?:\.{_PRE_ID})*))?"
    rf"(?:\+(?P<build>{_BUILD_ID}(?:\.{_BUILD_ID})*))?",
    re.ASCII,
)
"""Une version publiée : semver strict, sans ``v``."""

_COMPARATOR = re.compile(
    r"(?P<op>>=|<=|[=><~^])?"
    rf" *(?P<major>{_NUMBER})"
    rf"(?:\.(?:(?P<minor>{_NUMBER})|(?P<minor_any>[*xX])))?"
    rf"(?:\.(?:(?P<patch>{_NUMBER})|(?P<patch_any>[*xX])))?"
    rf"(?:-(?P<pre>{_PRE_ID}(?:\.{_PRE_ID})*))?"
    rf"(?:\+{_BUILD_ID}(?:\.{_BUILD_ID})*)?",
    re.ASCII,
)
"""Un comparateur tel qu'écrit : opérateur, version complète, partielle ou à joker."""

_WILDCARDS = frozenset("*xX")
_MAX_COMPARATORS = 32
"""Comme le crate ``semver`` : au-delà, la contrainte est refusée."""


@dataclass(frozen=True)
class _Comparator:
    """Un comparateur : l'opérateur (``""`` pour un joker) et une version, partielle ou non."""

    operator: str
    """``^``, ``~``, ``=``, ``>``, ``>=``, ``<``, ``<=`` ; ``*`` pour un joker (``1.*``)."""
    major: int
    minor: int | None
    patch: int | None
    prerelease: tuple[int | str, ...] = ()

    def __str__(self) -> str:
        numbers = [n for n in (self.major, self.minor, self.patch) if n is not None]
        text = ".".join(str(n) for n in numbers)
        if self.operator == "*":
            return f"{text}.*"
        if self.prerelease:
            text += "-" + ".".join(str(part) for part in self.prerelease)
        return self.operator + text

    def test(self, version: SemVer) -> bool:
        """``matches_impl`` du crate ``semver``, sans la règle des pré-versions."""
        if self.operator in ("=", "*"):
            return self._exact(version)
        if self.operator == ">":
            return self._greater(version)
        if self.operator == ">=":
            return self._exact(version) or self._greater(version)
        if self.operator == "<":
            return self._less(version)
        if self.operator == "<=":
            return self._exact(version) or self._less(version)
        if self.operator == "~":
            return self._tilde(version)
        return self._caret(version)

    def _exact(self, version: SemVer) -> bool:
        if version.major != self.major:
            return False
        if self.minor is not None and version.minor != self.minor:
            return False
        if self.patch is not None and version.patch != self.patch:
            return False
        return version.prerelease == self.prerelease

    def _greater(self, version: SemVer) -> bool:
        if version.major != self.major:
            return version.major > self.major
        if self.minor is None:
            return False
        if version.minor != self.minor:
            return version.minor > self.minor
        if self.patch is None:
            return False
        if version.patch != self.patch:
            return version.patch > self.patch
        return _pre_order(self.prerelease) < _pre_order(version.prerelease)

    def _less(self, version: SemVer) -> bool:
        if version.major != self.major:
            return version.major < self.major
        if self.minor is None:
            return False
        if version.minor != self.minor:
            return version.minor < self.minor
        if self.patch is None:
            return False
        if version.patch != self.patch:
            return version.patch < self.patch
        return _pre_order(version.prerelease) < _pre_order(self.prerelease)

    def _tilde(self, version: SemVer) -> bool:
        if version.major != self.major:
            return False
        if self.minor is not None and version.minor != self.minor:
            return False
        if self.patch is not None and version.patch != self.patch:
            return version.patch > self.patch
        return not _pre_order(version.prerelease) < _pre_order(self.prerelease)

    def _caret(self, version: SemVer) -> bool:
        if version.major != self.major:
            return False
        if self.minor is None:
            return True
        if self.patch is None:
            if self.major > 0:
                return version.minor >= self.minor
            return version.minor == self.minor
        if self.major > 0:
            if version.minor != self.minor:
                return version.minor > self.minor
            if version.patch != self.patch:
                return version.patch > self.patch
        elif self.minor > 0:
            if version.minor != self.minor:
                return False
            if version.patch != self.patch:
                return version.patch > self.patch
        elif version.minor != self.minor or version.patch != self.patch:
            return False
        return not _pre_order(version.prerelease) < _pre_order(self.prerelease)

    def allows_prerelease_of(self, version: SemVer) -> bool:
        """Vrai si ce comparateur ouvre la porte aux pré-versions de ``version`` : il porte sur
        le même ``major.minor.patch``, avec une pré-version."""
        return bool(self.prerelease) and (self.major, self.minor, self.patch) == version.release

    def minimum(self) -> SemVer | None:
        """La plus petite version qu'il accepte ; ``None`` pour ``<`` et ``<=``."""
        if self.operator in ("<", "<="):
            return None
        minor, patch = self.minor or 0, self.patch or 0
        if self.operator != ">":
            return SemVer(self.major, minor, patch, self.prerelease)
        if self.minor is None:  # >1 : 2.0.0
            return SemVer(self.major + 1, 0, 0)
        if self.patch is None:  # >1.2 : 1.3.0
            return SemVer(self.major, self.minor + 1, 0)
        if self.prerelease:  # >1.2.3-beta : 1.2.3-beta.0
            return SemVer(self.major, self.minor, self.patch, (*self.prerelease, 0))
        return SemVer(self.major, self.minor, self.patch + 1)


def _pre_order(prerelease: tuple[int | str, ...]) -> tuple[object, ...]:
    """Une clé qui range les pré-versions comme semver : sans pré-version, après toutes."""
    if not prerelease:
        return (1,)
    return (0, *((0, p, "") if isinstance(p, int) else (1, 0, p) for p in prerelease))


class CargoRequirement(Constraint[SemVer]):
    """Une contrainte Cargo : des comparateurs, tous à respecter ; aucun pour ``*``."""

    def __init__(self, comparators: tuple[_Comparator, ...]) -> None:
        self.comparators = comparators

    def __str__(self) -> str:
        return ", ".join(str(c) for c in self.comparators) or "*"

    def __repr__(self) -> str:
        return f"CargoRequirement({str(self)!r})"

    def contains(self, version: SemVer) -> bool:
        if not all(comparator.test(version) for comparator in self.comparators):
            return False
        if not version.prerelease:
            return True
        return any(comparator.allows_prerelease_of(version) for comparator in self.comparators)

    def lower_bound(self) -> str | None:
        """La plus petite version acceptée ; ``None`` sans borne basse (``*``, ``<2``, ``^0``),
        ou si la contrainte n'accepte rien."""
        bounds = [m for c in self.comparators if (m := c.minimum()) is not None]
        if not bounds:
            return None
        lowest = max(bounds)
        if lowest == SemVer(0, 0, 0) or not self.contains(lowest):
            return None
        return str(lowest)

    def exact(self) -> str | None:
        """``=1.2.3`` seul : ``1.2.3``. ``1.2.3`` sans opérateur est une plage (``^1.2.3``), et
        ``=1.2`` aussi (``1.2.*``)."""
        if len(self.comparators) != 1:
            return None
        (comparator,) = self.comparators
        if comparator.operator != "=" or comparator.patch is None:
            return None
        assert comparator.minor is not None
        version = SemVer(
            comparator.major, comparator.minor, comparator.patch, comparator.prerelease
        )
        return str(version)


class CargoVersions(VersionScheme[SemVer]):
    """semver 2.0, et les contraintes de Cargo."""

    ecosystem = Ecosystem.CRATES_IO

    def parse(self, version: str) -> SemVer:
        return _parse(version)

    def parse_constraint(self, constraint: str) -> CargoRequirement:
        return _parse_requirement(constraint)

    def _release(self, version: SemVer) -> tuple[int, int, int]:
        return version.release

    def _is_pre(self, version: SemVer) -> bool:
        return bool(version.prerelease)


CARGO = CargoVersions()


def _identifiers(text: str | None) -> tuple[int | str, ...]:
    if not text:
        return ()
    return tuple(int(part) if part.isdigit() else part for part in text.split("."))


@functools.lru_cache(maxsize=4096)
def _parse(version: str) -> SemVer:
    match = _VERSION.fullmatch(version.strip())
    if match is None:
        raise InvalidVersion(f"version semver illisible : {version!r}")
    build = match.group("build")
    return SemVer(
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        _identifiers(match.group("pre")),
        tuple(build.split(".")) if build else (),
    )


@functools.lru_cache(maxsize=1024)
def _parse_requirement(constraint: str) -> CargoRequirement:
    # Comme le crate semver : seules les espaces (pas les tabulations) sont tolérées, autour
    # des opérateurs et des virgules.
    text = constraint.strip(" ")
    if len(text) == 1 and text in _WILDCARDS:
        return CargoRequirement(())
    parts = [part.strip(" ") for part in text.split(",")]
    if len(parts) > _MAX_COMPARATORS:
        raise InvalidConstraint(f"plus de {_MAX_COMPARATORS} comparateurs : {constraint!r}")
    return CargoRequirement(tuple(_comparator(part, constraint) for part in parts))


def _comparator(text: str, constraint: str) -> _Comparator:
    match = _COMPARATOR.fullmatch(text)
    if match is None:
        raise InvalidConstraint(f"contrainte Cargo illisible : {constraint!r}")
    operator = match.group("op") or ""
    minor_any, patch_any = match.group("minor_any"), match.group("patch_any")
    minor = None if match.group("minor") is None else int(match.group("minor"))
    patch = None if match.group("patch") is None else int(match.group("patch"))
    pre = match.group("pre")
    if (minor_any and match.group("patch")) or (pre and patch is None):
        # « 1.*.3 », « 1.2-beta » : rien après un joker, pas de pré-version sans correctif.
        raise InvalidConstraint(f"contrainte Cargo illisible : {constraint!r}")
    if minor_any or patch_any:
        operator = operator or "*"
    return _Comparator(operator or "^", int(match.group("major")), minor, patch, _identifiers(pre))
