"""Les versions npm : semver 2.0 et les plages de npm, écrits à la main (comme node-semver 7).

Les versions publiées sont du semver strict (``1.2.3``, ``1.0.0-beta.2``, ``v`` toléré
devant). Les plages suivent les règles de node-semver, en mode « lâche » comme npm :

- ``^``, ``~`` (et ``~>``), les jokers ``x``, ``X`` et ``*``, ``a - b``, les
  comparateurs (``>=1.2 <2``), ``||`` ; ``v`` et ``=`` tolérés devant une version, et
  des versions partielles (``1.2``) ;
- les règles du 0.x : ``^0.2.3`` veut dire ``>=0.2.3 <0.3.0-0``, ``^0.0.3``
  ``>=0.0.3 <0.0.4-0`` ;
- une pré-version ne respecte une plage que si un comparateur de la plage porte sur
  le même ``major.minor.patch`` avec une pré-version : ``^1.2.3-beta.2`` accepte
  ``1.2.3-beta.4``, mais pas ``1.2.4-beta.1``.

Ce qu'un ``package.json`` peut écrire d'autre (E04) :

- ``""`` veut dire ``*`` ;
- une étiquette (``latest``, ``next``) suit le registre : elle accepte toutes les
  versions et n'a pas de borne basse ;
- ``catalog:`` (pnpm) renvoie à ``pnpm-workspace.yaml`` : les parseurs y lisent la plage
  (``Dependency.resolved_constraint``). Seule, elle lève ``InvalidConstraint``.

``str()`` d'une plage donne sa forme développée, celle de ``semver.validRange``.
"""

import functools
import re
from dataclasses import dataclass
from typing import Any, NamedTuple

from forceupdate.models import Ecosystem
from forceupdate.versions.base import Constraint, InvalidConstraint, InvalidVersion, VersionScheme

_NUMBER = r"0|[1-9]\d*"
_PRE_ID = r"(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
_LOOSE_ID = r"[0-9A-Za-z-]+"

_VERSION = re.compile(
    rf"v?(?P<major>{_NUMBER})\.(?P<minor>{_NUMBER})\.(?P<patch>{_NUMBER})"
    rf"(?:-(?P<pre>{_PRE_ID}(?:\.{_PRE_ID})*))?"
    rf"(?:\+(?P<build>{_LOOSE_ID}(?:\.{_LOOSE_ID})*))?",
    re.ASCII,
)
"""Une version publiée : semver strict."""

_X = r"\d+|[xX*]"
_PARTIAL = re.compile(
    rf"[v=\s]*(?P<major>{_X})(?:\.(?P<minor>{_X})(?:\.(?P<patch>{_X})"
    rf"(?:-?(?P<pre>{_LOOSE_ID}(?:\.{_LOOSE_ID})*))?"
    rf"(?:\+{_LOOSE_ID}(?:\.{_LOOSE_ID})*)?)?)?",
    re.ASCII,
)
"""Une version dans une plage : lâche (``v1``, ``=1.2``, ``01.2.3``, ``1.2.3beta``)
ou partielle (``1``, ``1.2.x``)."""

_HYPHEN = re.compile(r"(\S+)\s+-\s+(\S+)")
_LONE_OPERATOR = re.compile(r"[<>]=?|=|~>?|\^")
_COMPARATOR = re.compile(r"(?P<op>[<>]?=?)(?P<version>.*)")
_TAG = re.compile(r"[A-Za-z][0-9A-Za-z._-]*")
"""Une étiquette du registre (``latest``, ``next``, ``v4-lts``) : ce qui n'est pas une plage."""


@functools.total_ordering
@dataclass(frozen=True, eq=False)
class SemVer:
    """Une version semver 2.0. Les métadonnées de build (``+sha.1``) ne comptent pas dans
    l'ordre."""

    major: int
    minor: int
    patch: int
    prerelease: tuple[int | str, ...] = ()
    build: tuple[str, ...] = ()

    def __str__(self) -> str:
        text = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            text += "-" + ".".join(str(part) for part in self.prerelease)
        return text

    @property
    def release(self) -> tuple[int, int, int]:
        return self.major, self.minor, self.patch

    def _key(self) -> tuple[int, int, int, tuple[Any, ...]]:
        # Sans pré-version, une version passe après toutes ses pré-versions. Entre deux
        # identifiants : les nombres avant le texte, les nombres par valeur, le texte en
        # ASCII ; à égalité, la liste la plus courte d'abord.
        if not self.prerelease:
            return self.major, self.minor, self.patch, (1,)
        parts = tuple((0, p, "") if isinstance(p, int) else (1, 0, p) for p in self.prerelease)
        return self.major, self.minor, self.patch, (0, *parts)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SemVer) and self._key() == other._key()

    def __lt__(self, other: "SemVer") -> bool:
        return self._key() < other._key()

    def __hash__(self) -> int:
        return hash(self._key())


def _identifiers(text: str | None) -> tuple[int | str, ...]:
    if not text:
        return ()
    return tuple(int(part) if part.isdigit() else part for part in text.split("."))


@dataclass(frozen=True)
class _Comparator:
    """Un comparateur d'une plage développée : ``>=1.2.3``, ``<2.0.0-0``, ``1.2.3``."""

    operator: str
    """``>=``, ``>``, ``<=``, ``<`` ou ``""`` (égal)."""
    version: SemVer

    def __str__(self) -> str:
        return f"{self.operator}{self.version}"

    def test(self, version: SemVer) -> bool:
        if self.operator == ">=":
            return not version < self.version
        if self.operator == ">":
            return self.version < version
        if self.operator == "<=":
            return not self.version < version
        if self.operator == "<":
            return version < self.version
        return version == self.version


_NULL = _Comparator("<", SemVer(0, 0, 0, (0,)))
"""Le comparateur qu'aucune version ne respecte (``>*`` donne ça)."""
_ZERO = SemVer(0, 0, 0)

_Set = tuple[_Comparator, ...]
"""Un ensemble de comparateurs, tous à respecter ; vide, il accepte tout."""


class NpmRange(Constraint[SemVer]):
    """Une plage npm développée : une union d'ensembles de comparateurs, ou une étiquette."""

    def __init__(self, sets: tuple[_Set, ...], tag: str | None = None) -> None:
        self.sets = sets
        self.tag = tag
        """L'étiquette (``latest``, ``next``) ; le registre dit vers quelle version elle pointe."""

    def __str__(self) -> str:
        if self.tag is not None:
            return self.tag
        return "||".join(" ".join(str(c) for c in comparators) for comparators in self.sets) or "*"

    def __repr__(self) -> str:
        return f"NpmRange({str(self)!r})"

    def contains(self, version: SemVer) -> bool:
        if self.tag is not None:
            return True
        return any(_test_set(comparators, version) for comparators in self.sets)

    def lower_bound(self) -> str | None:
        """Comme ``semver.minVersion``, sauf qu'une plage dont un ensemble n'a pas de borne
        basse (``*``, ``<2``, ``^0``) rend ``None`` au lieu de ``0.0.0``."""
        if self.tag is not None:
            return None
        lowest: SemVer | None = None
        for comparators in self.sets:
            bounds = [_minimum(c) for c in comparators if c.operator in ("", ">=", ">")]
            if not bounds:
                return None
            bound = max(bounds)
            if lowest is None or bound < lowest:
                lowest = bound
        if lowest is None or not self.contains(lowest):
            return None
        return str(lowest)

    def exact(self) -> str | None:
        """Une version complète seule (``1.2.3``, ``=1.2.3``, ``v1.2.3``) : elle-même. ``1.2``
        est une plage (``>=1.2.0 <1.3.0-0``)."""
        if self.tag is not None or len(self.sets) != 1 or len(self.sets[0]) != 1:
            return None
        (comparator,) = self.sets[0]
        return str(comparator.version) if comparator.operator == "" else None


def _minimum(comparator: _Comparator) -> SemVer:
    """La plus petite version qui respecte un comparateur ``>=``, ``>`` ou ``=`` :
    ``>1.2.3`` → ``1.2.4``, ``>1.2.3-beta`` → ``1.2.3-beta.0``."""
    version = comparator.version
    if comparator.operator != ">":
        return version
    if version.prerelease:
        return SemVer(version.major, version.minor, version.patch, (*version.prerelease, 0))
    return SemVer(version.major, version.minor, version.patch + 1)


def _test_set(comparators: _Set, version: SemVer) -> bool:
    if not all(comparator.test(version) for comparator in comparators):
        return False
    if not version.prerelease:
        return True
    # Une pré-version n'entre que par un comparateur qui en porte une sur la même version.
    return any(c.version.prerelease and c.version.release == version.release for c in comparators)


class NpmVersions(VersionScheme[SemVer]):
    """semver 2.0, et les plages de npm."""

    ecosystem = Ecosystem.NPM

    def parse(self, version: str) -> SemVer:
        return _parse(version)

    def parse_constraint(self, constraint: str) -> NpmRange:
        return _parse_range(constraint)

    def _release(self, version: SemVer) -> tuple[int, int, int]:
        return version.release

    def _is_pre(self, version: SemVer) -> bool:
        return bool(version.prerelease)


NPM = NpmVersions()


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


# ---------------------------------------------------------------------------
# Plages
# ---------------------------------------------------------------------------


class _RangeError(ValueError):
    pass


class _Partial(NamedTuple):
    """Une version de plage : ``None`` pour un nombre absent ou joker (``1.x``)."""

    major: int | None
    minor: int | None
    patch: int | None
    prerelease: tuple[int | str, ...]


@functools.lru_cache(maxsize=1024)
def _parse_range(constraint: str) -> NpmRange:
    text = " ".join(constraint.split())
    if text.lower().startswith("catalog:"):
        raise InvalidConstraint(
            f"{constraint!r} renvoie à un catalogue pnpm : la plage est dans pnpm-workspace.yaml"
        )
    try:
        return NpmRange(_simplify(tuple(_parse_set(part.strip()) for part in text.split("||"))))
    except _RangeError:
        if _TAG.fullmatch(text):
            return NpmRange((), tag=text)
        raise InvalidConstraint(f"plage npm illisible : {constraint!r}") from None


def _simplify(sets: tuple[_Set, ...]) -> tuple[_Set, ...]:
    """Comme node-semver : les ensembles vides de sens (``<0.0.0-0``) partent s'il en reste
    d'autres, et un ensemble qui accepte tout absorbe l'union."""
    if len(sets) == 1:
        return sets
    kept = tuple(s for s in sets if s != (_NULL,)) or sets[:1]
    if () in kept:
        return ((),)
    return kept


def _parse_set(text: str) -> _Set:
    """Un membre de l'union : ``1.2.3 - 2.3.4``, ou des comparateurs séparés par des espaces."""
    if not text:
        return ()
    hyphen = _HYPHEN.fullmatch(text)
    if hyphen is not None and (first := _partial_or_none(hyphen[1])) is not None:
        comparators = _hyphen(first, _partial(hyphen[2]))
    else:
        comparators = []
        operator = ""
        for token in text.split(" "):
            if _LONE_OPERATOR.fullmatch(token):
                # « >= 1.2.3 », « ^ 1.2 » : l'opérateur va avec ce qui suit.
                if operator:
                    raise _RangeError(token)
                operator = token
                continue
            comparators.extend(_comparators(operator + token))
            operator = ""
        if operator:
            raise _RangeError(operator)
    # >=0.0.0 n'est pas une borne : c'est « toutes les versions ».
    kept = [c for c in comparators if not (c.operator == ">=" and c.version == _ZERO)]
    if _NULL in kept:
        return (_NULL,)
    return tuple(dict.fromkeys(kept))


def _partial(text: str) -> _Partial:
    partial = _partial_or_none(text)
    if partial is None:
        raise _RangeError(text)
    return partial


def _partial_or_none(text: str) -> _Partial | None:
    match = _PARTIAL.fullmatch(text)
    if match is None:
        return None

    def number(group: str) -> int | None:
        value = match.group(group)
        return None if value is None or value in ("x", "X", "*") else int(value)

    return _Partial(
        number("major"), number("minor"), number("patch"), _identifiers(match.group("pre"))
    )


def _comparators(token: str) -> list[_Comparator]:
    """Un comparateur tel qu'écrit, développé : ``^1.2.3`` → ``>=1.2.3 <2.0.0-0``."""
    if token.startswith("^"):
        return _caret(_partial(token[1:]))
    if token.startswith("~"):
        return _tilde(_partial(token[2:] if token.startswith("~>") else token[1:]))
    match = _COMPARATOR.fullmatch(token)
    if match is None:  # pragma: no cover - l'expression accepte tout
        raise _RangeError(token)
    return _xrange(match.group("op"), _partial(match.group("version")))


def _ge(major: int, minor: int, patch: int, pre: tuple[int | str, ...] = ()) -> _Comparator:
    return _Comparator(">=", SemVer(major, minor, patch, pre))


def _lt(major: int, minor: int, patch: int) -> _Comparator:
    """``<X.Y.Z-0`` : sous ``X.Y.Z`` et toutes ses pré-versions."""
    return _Comparator("<", SemVer(major, minor, patch, (0,)))


def _caret(p: _Partial) -> list[_Comparator]:
    """``^`` : ne change pas le premier nombre non nul (règles du 0.x)."""
    major, minor, patch = p.major, p.minor, p.patch
    if major is None:
        return []
    if minor is None:
        return [_ge(major, 0, 0), _lt(major + 1, 0, 0)]
    if patch is None:
        upper = _lt(0, minor + 1, 0) if major == 0 else _lt(major + 1, 0, 0)
        return [_ge(major, minor, 0), upper]
    lower = _ge(major, minor, patch, p.prerelease)
    if major > 0:
        return [lower, _lt(major + 1, 0, 0)]
    if minor > 0:
        return [lower, _lt(0, minor + 1, 0)]
    return [lower, _lt(0, 0, patch + 1)]


def _tilde(p: _Partial) -> list[_Comparator]:
    """``~`` : les correctifs si la mineure est donnée, sinon les mineures."""
    major, minor, patch = p.major, p.minor, p.patch
    if major is None:
        return []
    if minor is None:
        return [_ge(major, 0, 0), _lt(major + 1, 0, 0)]
    if patch is None:
        return [_ge(major, minor, 0), _lt(major, minor + 1, 0)]
    return [_ge(major, minor, patch, p.prerelease), _lt(major, minor + 1, 0)]


def _xrange(operator: str, p: _Partial) -> list[_Comparator]:
    """Un comparateur, avec ou sans joker : ``1.2.x``, ``>1.2``, ``<=1``, ``*``, ``1.2.3``."""
    major, minor, patch = p.major, p.minor, p.patch
    if operator == "=":
        operator = ""
    if major is None:
        return [_NULL] if operator in (">", "<") else []
    if minor is None or patch is None:
        if not operator:
            if minor is None:
                return [_ge(major, 0, 0), _lt(major + 1, 0, 0)]
            return [_ge(major, minor, 0), _lt(major, minor + 1, 0)]
        # Comparateur sur une version partielle : on le ramène à une version complète.
        bump_major = minor is None
        minor = minor or 0
        if operator == ">":  # >1 → >=2.0.0 ; >1.2 → >=1.3.0
            operator = ">="
            major, minor = (major + 1, 0) if bump_major else (major, minor + 1)
        elif operator == "<=":  # <=1.2 → <1.3.0-0
            operator = "<"
            major, minor = (major + 1, 0) if bump_major else (major, minor + 1)
        if operator == "<":
            return [_lt(major, minor, 0)]
        return [_Comparator(operator, SemVer(major, minor, 0))]
    return [_Comparator(operator, SemVer(major, minor, patch, p.prerelease))]


def _hyphen(first: _Partial, last: _Partial) -> list[_Comparator]:
    """``1.2 - 2.3.4`` → ``>=1.2.0 <=2.3.4`` ; ``1.2.3 - 2.3`` → ``>=1.2.3 <2.4.0-0``."""
    comparators = []
    if first.major is not None:
        comparators.append(
            _ge(first.major, first.minor or 0, first.patch or 0, first.prerelease)
            if first.minor is not None and first.patch is not None
            else _ge(first.major, first.minor or 0, 0)
        )
    if last.major is not None:
        if last.minor is None:
            comparators.append(_lt(last.major + 1, 0, 0))
        elif last.patch is None:
            comparators.append(_lt(last.major, last.minor + 1, 0))
        else:
            version = SemVer(last.major, last.minor, last.patch, last.prerelease)
            comparators.append(_Comparator("<=", version))
    return comparators
