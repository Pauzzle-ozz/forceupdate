"""Les versions PyPI : PEP 440, avec ``packaging``.

Une contrainte est d'abord lue comme un ``SpecifierSet`` de PEP 440 (``>=2.25, <3``,
``~=1.4``, ``==1.2.*``). Ce que ``SpecifierSet`` refuse est de la syntaxe Poetry ou
Pipfile, que les parseurs gardent telle qu'écrite (E03), traduite ici en PEP 440 :

- ``^1.2.3`` → ``>=1.2.3,<2.0.0``, ``^0.2.3`` → ``>=0.2.3,<0.3.0``, ``^0.0.3`` →
  ``>=0.0.3,<0.0.4`` : la borne haute est la prochaine version « cassante » ;
- ``~1.2.3`` → ``>=1.2.3,<1.3.0``, ``~1`` → ``>=1,<2`` ;
- ``1.2.*`` (ou ``1.2.x``) → ``==1.2.*``, une version nue ``6.0.2`` → ``==6.0.2`` ;
- ``*`` (Poetry et Pipfile) : toutes les versions ;
- plusieurs contraintes séparées par des virgules ou des espaces (``>= 1.2 < 2.0``) ;
- ``||`` : une union. ``SpecifierSet`` ne sait faire que des intersections, d'où une
  liste d'ensembles.

Une contrainte est un ensemble de versions : ``2.0rc1`` respecte ``>=1.0``. Ce sont
les candidates (``VersionScheme.candidates``) qui écartent les pré-versions.
"""

import functools
import re

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion as _PackagingInvalidVersion
from packaging.version import Version

from forceupdate.models import Ecosystem, Gap
from forceupdate.versions.base import Constraint, InvalidConstraint, InvalidVersion, VersionScheme

_LOWER_OPERATORS = frozenset({">=", ">", "==", "~=", "==="})
"""Les opérateurs qui donnent une borne basse ; ``!=``, ``<`` et ``<=`` n'en donnent pas."""

_OR = re.compile(r"\s*\|\|?\s*")
_OPERATOR = re.compile(r"===|==|!=|<>|<=|>=|~=|<|>|=|\^|~")
_SINGLE = re.compile(rf"(?P<op>{_OPERATOR.pattern})?\s*(?P<version>\S+)")
_ANY = re.compile(r"v?[xX*](?:\.[xX*])*")
_WILDCARD = re.compile(r"v?(?P<prefix>[0-9]+(?:\.[0-9]+)*)(?:\.[xX*])+")


class PypiConstraint(Constraint[Version]):
    """Une contrainte PEP 440, ou une union de contraintes (``||`` de Poetry)."""

    def __init__(self, sets: tuple[SpecifierSet, ...]) -> None:
        self.sets = sets
        """Les ensembles de l'union : une version doit en respecter au moins un."""

    def __repr__(self) -> str:
        return f"PypiConstraint({' || '.join(str(s) or '*' for s in self.sets)})"

    def contains(self, version: Version) -> bool:
        return any(specifiers.contains(version, prereleases=True) for specifiers in self.sets)

    def lower_bound(self) -> str | None:
        """La plus haute borne basse de chaque ensemble, puis la plus petite de l'union. Une
        borne exclue (``>1.2``) est rendue telle quelle : PEP 440 n'a pas de « version
        suivante », c'est la meilleure approximation."""
        lowest: tuple[Version, str] | None = None
        for specifiers in self.sets:
            bounds = []
            for specifier in specifiers:
                if specifier.operator not in _LOWER_OPERATORS:
                    continue
                text = specifier.version.removesuffix(".*")
                try:
                    bounds.append((Version(text), text))
                except _PackagingInvalidVersion:
                    continue  # « === » accepte n'importe quel texte
            if not bounds:
                return None
            bound = max(bounds, key=lambda pair: pair[0])
            if lowest is None or bound[0] < lowest[0]:
                lowest = bound
        return None if lowest is None else lowest[1]

    def exact(self) -> str | None:
        """``==1.2.3`` (sans joker) ou ``===1.2.3``, seul : sa version. Une version nue de
        Poetry (``6.0.2``) est traduite en ``==``."""
        if len(self.sets) != 1:
            return None
        specifiers = list(self.sets[0])
        if len(specifiers) != 1:
            return None
        (specifier,) = specifiers
        if specifier.operator == "===" or (
            specifier.operator == "==" and not specifier.version.endswith(".*")
        ):
            return specifier.version
        return None


class PypiVersions(VersionScheme[Version]):
    """PEP 440. L'époque (``1!2.0``) compte : en changer est une majeure."""

    ecosystem = Ecosystem.PYPI

    def parse(self, version: str) -> Version:
        return _parse(version)

    def parse_constraint(self, constraint: str) -> PypiConstraint:
        return _parse_constraint(constraint)

    def _release(self, version: Version) -> tuple[int, int, int]:
        major, minor, patch = (*version.release, 0, 0)[:3]
        return major, minor, patch

    def _is_pre(self, version: Version) -> bool:
        return version.is_prerelease

    def _same_release(self, a: Version, b: Version) -> bool:
        return (a.epoch, _stripped(a.release)) == (b.epoch, _stripped(b.release))

    def _gap(self, a: Version, b: Version) -> Gap:
        if a.epoch != b.epoch:
            return Gap.MAJOR
        return super()._gap(a, b)


PYPI = PypiVersions()


def _stripped(release: tuple[int, ...]) -> tuple[int, ...]:
    """``(1, 2, 0)`` → ``(1, 2)`` : ``1.2`` et ``1.2.0`` sont la même version."""
    end = len(release)
    while end > 1 and release[end - 1] == 0:
        end -= 1
    return release[:end]


@functools.lru_cache(maxsize=4096)
def _parse(version: str) -> Version:
    try:
        return Version(version)
    except _PackagingInvalidVersion:
        raise InvalidVersion(f"version PEP 440 illisible : {version!r}") from None


@functools.lru_cache(maxsize=1024)
def _parse_constraint(constraint: str) -> PypiConstraint:
    try:
        return PypiConstraint((SpecifierSet(constraint),))
    except InvalidSpecifier:
        pass
    try:
        return PypiConstraint(tuple(_poetry_set(part) for part in _OR.split(constraint.strip())))
    except ValueError:  # InvalidSpecifier et InvalidVersion de packaging en sont
        message = f"contrainte PEP 440 ou Poetry illisible : {constraint!r}"
        raise InvalidConstraint(message) from None


def _poetry_set(text: str) -> SpecifierSet:
    """Un membre d'une union Poetry : des contraintes séparées par des virgules ou des
    espaces, toutes à respecter. Un opérateur seul (``>= 1.2``) va avec ce qui suit. Un
    membre vide (``^1 || || ^2``) est refusé, comme le fait Poetry."""
    if not text.strip():
        raise ValueError(text)
    specifiers: list[str] = []
    operator = ""
    for token in re.split(r"[\s,]+", text):
        if not token:
            continue
        if _OPERATOR.fullmatch(token):
            if operator:
                raise ValueError(token)
            operator = token
            continue
        specifiers.extend(_poetry_single(operator + token))
        operator = ""
    if operator:
        raise ValueError(operator)
    return SpecifierSet(",".join(specifiers))


def _poetry_single(text: str) -> list[str]:
    """Une contrainte Poetry, en spécificateurs PEP 440 (aucun pour ``*``)."""
    match = _SINGLE.fullmatch(text)
    if match is None:
        raise ValueError(text)
    operator, written = match.group("op") or "", match.group("version")
    if _ANY.fullmatch(written):
        if operator not in ("", "=", "==", ">="):
            raise ValueError(text)
        return []
    wildcard = _WILDCARD.fullmatch(written)
    if wildcard is not None:
        if operator not in ("", "=", "==", "!="):
            raise ValueError(text)
        return [f"{'!=' if operator == '!=' else '=='}{wildcard.group('prefix')}.*"]
    version = Version(written)
    if operator == "^":
        return [f">={version}", f"<{_next_breaking(version)}"]
    if operator == "~":
        index = 0 if len(version.release) == 1 else 1
        return [f">={version}", f"<{_bump(version, index)}"]
    if operator in ("", "="):
        return [f"=={version}"]
    if operator == "<>":
        return [f"!={version}"]
    return [f"{operator}{version}"]


def _next_breaking(version: Version) -> str:
    """La borne haute de ``^`` : la prochaine majeure, ou en 0.x la prochaine mineure
    (``^0.2.3`` → ``0.3.0``), ou en 0.0.x le prochain correctif (``^0.0.3`` → ``0.0.4``).
    Comme Poetry, ``^0`` va jusqu'à ``1`` et ``^0.0`` jusqu'à ``0.1``."""
    release = version.release
    if release[0] > 0 or len(release) == 1:
        return _bump(version, 0)
    if release[1] > 0 or len(release) == 2:
        return _bump(version, 1)
    return _bump(version, 2)


def _bump(version: Version, index: int) -> str:
    """La version stable où le nombre ``index`` monte de 1 et ceux d'après passent à 0,
    écrite avec autant de nombres que ``version`` : ``1.2.3`` monté en 1 donne ``1.3.0``."""
    release = version.release
    width = max(len(release), index + 1)
    numbers = (*release[:index], release[index] + 1, *([0] * (width - index - 1)))
    text = ".".join(str(number) for number in numbers)
    return f"{version.epoch}!{text}" if version.epoch else text
