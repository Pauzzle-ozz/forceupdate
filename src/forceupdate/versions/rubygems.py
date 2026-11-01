"""Les versions RubyGems : ``Gem::Version`` et ``Gem::Requirement``, réécrits d'après RubyGems 4.0.

**Une version** (``Gem::Version``) : des nombres et des lettres séparés par des points
(``1.2.3``, ``2.0.0.rc1``, ``1.0.a``). Ce qu'en fait RubyGems :

- un ``-`` devient ``.pre.`` (``1.0.0-rc1`` est ``1.0.0.pre.rc1``) ; une chaîne vide vaut ``0`` ;
- les segments sont les suites de chiffres (des nombres) et de lettres (des mots) :
  ``1.0.0.rc1`` donne ``1, 0, 0, "rc", 1`` ;
- **une lettre fait une pré-version** : ``1.0.a``, ``2.0.0.rc1``, ``3.0.0.beta.2`` ;
- **les zéros de fin ne comptent pas** : ``1.0`` égale ``1.0.0`` ; ceux d'avant une lettre non
  plus, pour une pré-version (``1.0.0.a`` égale ``1.a``) ;
- l'ordre : segment par segment, un mot avant un nombre (``1.0.a`` < ``1.0.0`` < ``1.0.1``), les
  mots dans l'ordre du texte ; quand l'un s'arrête, un mot qui reste dans l'autre le fait passer
  devant, un nombre non nul après.

**Une contrainte** (``Gem::Requirement``) : un opérateur et une version par chaîne (``"~> 1.2"``),
plusieurs chaînes à respecter toutes (``gem "x", "~> 1.2", ">= 1.2.3"``). forceupdate les écrit
séparées par des virgules, comme ``Gemfile.lock`` et ``Gem::Requirement#to_s`` : ``~> 1.2, >=
1.2.3``. Une chaîne ne peut pas en contenir deux. Les opérateurs :

- ``=`` (celui par défaut : ``1.2`` veut dire ``= 1.2``, donc ``1.2.0``), ``!=``, ``>``, ``<``,
  ``>=``, ``<=`` ;
- ``~>``, la contrainte « pessimiste » : ``~> 1.2`` veut dire ``>= 1.2, < 2``, ``~> 1.2.3`` veut
  dire ``>= 1.2.3, < 1.3`` ; ``~> 1`` va jusqu'à 2 ; une pré-version de la borne haute est hors
  de la contrainte (``2.0.0.rc1`` pour ``~> 1.2``) ;
- sans contrainte, ``>= 0``.

``Gem::Requirement`` accepte les pré-versions dans ses bornes ; c'est Bundler qui les écarte,
sauf quand la contrainte en nomme une (``>= 2.0.0.rc1``) : ``max_satisfying`` fait comme lui.

Vérifié contre RubyGems 4.0.20 (Ruby 4.0.9) : voir les notes de E24 dans ``PLAN.md``. La version
que choisit Bundler est la plus haute permise (vérifié avec Bundler 4.0.20) ; il écarte en plus
celles qui demandent un autre Ruby (``required_ruby_version``), ce qu'on ne sait pas ici (E27).
"""

import functools
import re
from collections.abc import Iterable

from forceupdate.models import Ecosystem
from forceupdate.versions.base import Constraint, InvalidConstraint, InvalidVersion, VersionScheme

_VERSION_PATTERN = r"[0-9]+(?>\.[0-9a-zA-Z]+)*(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
_VERSION = re.compile(rf"\s*({_VERSION_PATTERN})?\s*")
_REQUIREMENT = re.compile(rf"\s*(~>|>=|<=|!=|=|>|<)?\s*({_VERSION_PATTERN})\s*")
_SEGMENT = re.compile(r"\d+|[a-zA-Z]+")

Segment = int | str


@functools.total_ordering
class GemVersion:
    """Une version lue, comparable comme ``Gem::Version``."""

    __slots__ = ("_canonical", "prerelease", "segments", "text")

    def __init__(self, text: str) -> None:
        self.text = text
        """La version normalisée par RubyGems (``1.0.0-rc1`` → ``1.0.0.pre.rc1``)."""
        self.segments: tuple[Segment, ...] = _segments(text)
        self.prerelease = re.search(r"[a-zA-Z]", text) is not None
        canonical = re.sub(r"(?<=[a-zA-Z.])[.0]+\Z", "", text, count=1)
        if self.prerelease:
            canonical = re.sub(r"(?:(?<=\.)|\A)[0.]+(?=[a-zA-Z])", "", canonical, count=1)
        self._canonical = _segments(canonical)

    def __repr__(self) -> str:
        return f"GemVersion({self.text!r})"

    def __str__(self) -> str:
        return self.text

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, GemVersion):
            return NotImplemented
        return self._canonical == other._canonical

    def __hash__(self) -> int:
        return hash(self._canonical)

    def __lt__(self, other: "GemVersion") -> bool:
        return _compare(self._canonical, other._canonical) < 0

    @property
    def release(self) -> "GemVersion":
        """La version sans sa partie pré-version (``2.0.0.rc1`` → ``2.0.0``)."""
        if not self.prerelease:
            return self
        return _parse(".".join(str(s) for s in _numbers(self.segments)))

    def bump(self) -> "GemVersion":
        """La borne haute de ``~>`` : sans les mots, le dernier nombre retiré, puis le précédent
        augmenté (``1.2.3`` → ``1.3``, ``1.2`` → ``2``, ``1`` → ``2``)."""
        numbers = list(_numbers(self.segments))
        if len(numbers) > 1:
            numbers.pop()
        numbers[-1] += 1
        return _parse(".".join(str(n) for n in numbers))


def _segments(text: str) -> tuple[Segment, ...]:
    return tuple(int(s) if s[0].isdigit() else s for s in _SEGMENT.findall(text))


def _numbers(segments: tuple[Segment, ...]) -> tuple[int, ...]:
    """Les nombres d'avant le premier mot."""
    found = []
    for segment in segments:
        if isinstance(segment, str):
            break
        found.append(segment)
    return tuple(found)


def _compare(left: tuple[Segment, ...], right: tuple[Segment, ...]) -> int:
    """``Gem::Version#<=>`` sur les segments canoniques."""
    if left == right:
        return 0
    limit = min(len(left), len(right))
    for a, b in zip(left[:limit], right[:limit], strict=True):
        if a == b:
            continue
        if isinstance(a, str) and isinstance(b, int):
            return -1
        if isinstance(a, int) and isinstance(b, str):
            return 1
        return -1 if a < b else 1  # type: ignore[operator]
    for b in right[limit:]:
        if isinstance(b, str):
            return 1
        if b != 0:
            return -1
    for a in left[limit:]:
        if isinstance(a, str):
            return -1
        if a != 0:
            return 1
    return 0


@functools.lru_cache(maxsize=8192)
def _parse(version: str) -> GemVersion:
    match = _VERSION.fullmatch(version)
    if match is None:
        raise InvalidVersion(f"version RubyGems illisible : {version!r}")
    text = (match.group(1) or "0").replace("-", ".pre.")
    return GemVersion(text)


class GemRequirement(Constraint[GemVersion]):
    """Une contrainte RubyGems : des comparateurs, tous à respecter ; ``>= 0`` sans comparateur."""

    def __init__(self, comparators: tuple[tuple[str, GemVersion], ...]) -> None:
        self.comparators = comparators or ((">=", _parse("0")),)

    def __str__(self) -> str:
        return ", ".join(f"{operator} {version}" for operator, version in self.comparators)

    def __repr__(self) -> str:
        return f"GemRequirement({str(self)!r})"

    @property
    def prerelease(self) -> bool:
        """Vrai si un comparateur nomme une pré-version : Bundler en propose alors."""
        return any(version.prerelease for _, version in self.comparators)

    def contains(self, version: GemVersion) -> bool:
        return all(_test(operator, version, wanted) for operator, wanted in self.comparators)

    def lower_bound(self) -> str | None:
        """La plus petite version acceptée : la borne de ``=``, ``>=`` ou ``~>`` ; ``None`` sans
        borne basse (``>= 0``, ``< 2``), pour un ``>`` seul (la version suivante n'a pas de
        sens : ``1.2.3.1`` ou ``1.2.4`` ?), ou si la contrainte n'accepte rien."""
        bounds = [v for operator, v in self.comparators if operator in ("=", ">=", "~>")]
        if not bounds:
            return None
        lowest = max(bounds)
        if lowest == _parse("0") or not self.contains(lowest):
            return None
        return str(lowest)

    def exact(self) -> str | None:
        """``= 1.2.3`` (ou ``1.2.3``) seul : ``1.2.3``."""
        if len(self.comparators) != 1 or self.comparators[0][0] != "=":
            return None
        return str(self.comparators[0][1])


def _test(operator: str, version: GemVersion, wanted: GemVersion) -> bool:
    if operator == "=":
        return version == wanted
    if operator == "!=":
        return version != wanted
    if operator == ">":
        return wanted < version
    if operator == "<":
        return version < wanted
    if operator == ">=":
        return not version < wanted
    if operator == "<=":
        return not wanted < version
    return not version < wanted and version.release < wanted.bump()  # ~>


@functools.lru_cache(maxsize=2048)
def _parse_requirement(constraint: str) -> GemRequirement:
    if not constraint.strip():
        return GemRequirement(())
    comparators = []
    for part in constraint.split(","):
        match = _REQUIREMENT.fullmatch(part)
        if match is None:
            raise InvalidConstraint(f"contrainte RubyGems illisible : {constraint!r}")
        comparators.append((match.group(1) or "=", _parse(match.group(2))))
    return GemRequirement(tuple(dict.fromkeys(comparators)))


class RubyGemsVersions(VersionScheme[GemVersion]):
    """L'ordre de ``Gem::Version``, les contraintes de ``Gem::Requirement``."""

    ecosystem = Ecosystem.RUBYGEMS

    def parse(self, version: str) -> GemVersion:
        return _parse(version)

    def parse_constraint(self, constraint: str) -> GemRequirement:
        return _parse_requirement(constraint)

    def _release(self, version: GemVersion) -> tuple[int, int, int]:
        major, minor, patch = (*_numbers(version.segments), 0, 0, 0)[:3]
        return major, minor, patch

    def _is_pre(self, version: GemVersion) -> bool:
        return version.prerelease

    def max_satisfying(
        self, constraint: str, versions: Iterable[str], current: str | None = None
    ) -> str | None:
        """La plus haute version acceptée, comme la choisit Bundler : sans les pré-versions (sauf
        la ligne de ``current``, voir ``candidates``), sauf si la contrainte en nomme une."""
        parsed = self.parse_constraint(constraint)
        if not parsed.prerelease:
            return super().max_satisfying(constraint, versions, current)
        best: tuple[str, GemVersion] | None = None
        for text in versions:
            try:
                version = self.parse(text)
            except InvalidVersion:
                continue
            if parsed.contains(version) and (best is None or best[1] < version):
                best = (text, version)
        return None if best is None else best[0]


RUBYGEMS = RubyGemsVersions()
"""Les règles de version de RubyGems."""
