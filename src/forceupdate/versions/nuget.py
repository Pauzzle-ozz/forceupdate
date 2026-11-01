"""Les versions NuGet : ``NuGetVersion``, ``VersionComparer`` et ``VersionRange``, réécrits d'après
NuGet.Versioning 7.9.

**Une version** (``NuGetVersion``) :

- un à quatre nombres (``1``, ``1.2``, ``1.2.3``, ``1.2.3.4``), les absents valant 0 : ``1.0`` =
  ``1.0.0`` = ``1.0.0.0`` ; des zéros en tête permis (``01.2`` est ``1.2.0``), chacun au plus
  2 147 483 647 ; des espaces autour, et autour des nombres, ignorés ;
- une pré-version après ``-`` : des étiquettes séparées par ``.``, faites de lettres ASCII, de
  chiffres et de ``-``, non vides, sans zéro en tête pour une étiquette toute en chiffres
  (``1.0.0-beta.01`` est refusée) ;
- des métadonnées après ``+``, ignorées dans les comparaisons.

**L'ordre** : les quatre nombres ; puis une pré-version sous la version finale ; deux pré-versions,
étiquette par étiquette : deux nombres comme des nombres, un nombre avant un mot, deux mots sans
tenir compte de la casse (``1.0.0-Beta`` = ``1.0.0-beta``), et à égalité la plus courte avant
(``alpha`` < ``alpha.1``). Est un nombre ce que lit ``int.TryParse`` (``-1`` compris).

**Une contrainte** est un ``VersionRange`` :

- une version nue (``1.2.3``) est un **minimum** : ``[1.2.3, )`` ;
- ``[1.2.3]`` : exactement celle-là ; des intervalles ``[1.0,2.0)``, ``(1.0,)``, ``(,2.0]`` (un
  seul, deux bornes au plus) ;
- les versions flottantes (``FloatRange``) : ``1.*``, ``1.2.*``, ``1.2.3.*``, ``*``,
  ``1.0.0-*``, ``1.0.0-beta.*``, ``1.*-*``, ``*-*`` ; aussi en borne basse d'un intervalle
  (``[1.0.*, 2.0)``). Elles ont pour borne basse leur début (``1.*`` : ``[1.0.0, )``).

**NuGet prend la plus basse version qui convient** (``VersionRange.FindBestMatch``) : une version
nue, ``[1.0,2.0)`` donnent leur borne basse (la suivante si elle n'est pas publiée) ; une
pré-version n'est prise que si une borne en est une. Une version flottante prend la plus haute de
ce qu'elle désigne (``1.*`` : la plus haute 1.x stable). D'où, ici :

- ``exact`` (la version utilisée, sans lockfile) : la borne basse incluse d'une contrainte qui ne
  flotte pas, celle que NuGet prend ;
- ``reaches`` : régénérer le lockfile ne fait monter qu'une version flottante ; ailleurs, il faut
  réécrire la borne basse ;
- ``chosen`` : le choix de NuGet parmi les versions publiées.

Vérifié contre NuGet.Versioning 7.9.0, chargé par PowerShell : voir les notes de E26 dans
``PLAN.md``.
"""

import enum
import functools
import re
import unicodedata
from collections.abc import Iterable

from forceupdate.models import Ecosystem
from forceupdate.versions.base import Constraint, InvalidConstraint, InvalidVersion, VersionScheme

_INT_MAX = 2**31 - 1
_NUMERIC = re.compile(r"-?[0-9]+")
_SPACES = frozenset("\t\n\v\f\r \x85\xa0")


def _is_space(char: str) -> bool:
    """``char.IsWhiteSpace`` de .NET."""
    return char in _SPACES or unicodedata.category(char) in ("Zs", "Zl", "Zp")


def _trim(text: str) -> str:
    """``string.Trim`` de .NET."""
    start, end = 0, len(text)
    while start < end and _is_space(text[start]):
        start += 1
    while end > start and _is_space(text[end - 1]):
        end -= 1
    return text[start:end]


def _blank(text: str | None) -> bool:
    """``string.IsNullOrWhiteSpace``."""
    return text is None or all(_is_space(char) for char in text)


def _is_digit(char: str) -> bool:
    return "0" <= char <= "9"


def _valid_part(part: str, *, leading_zeros: bool) -> bool:
    """``SemanticVersion.IsValidPart`` : non vide, des lettres ASCII, des chiffres et ``-`` ; pas
    de zéro en tête pour une étiquette toute en chiffres (sauf ``leading_zeros``)."""
    if not part:
        return False
    if not leading_zeros and len(part) > 1 and part[0] == "0" and all(map(_is_digit, part[1:])):
        return False
    return all(char.isascii() and (char.isalnum() or char == "-") for char in part)


def _sections(value: str) -> tuple[str | None, list[str] | None, str | None]:
    """``SemanticVersion.ParseSections`` : la partie des nombres, les étiquettes, les métadonnées.
    Un ``-`` ou un ``+`` en dernier caractère reste dans la partie qui le précède (elle sera
    refusée)."""
    numbers: str | None = None
    labels: list[str] | None = None
    metadata: str | None = None
    numbers_end = plus = -1
    last = len(value) - 1
    for index, char in enumerate(value):
        end = index == last
        if numbers_end < 0:
            if end or char in "-+":
                numbers = value[: index + (1 if end else 0)]
                numbers_end = index
                if char == "+":
                    plus = index
        elif plus < 0:
            if end or char == "+":
                labels = value[numbers_end + 1 : index + (1 if end else 0)].split(".")
                plus = index
        elif end:
            metadata = value[plus + 1 : index + 1]
    return numbers, labels, metadata


def _numbers(text: str) -> tuple[int, int, int, int] | None:
    """``NuGetVersion.TryGetNormalizedVersion`` : un à quatre nombres, les absents à 0."""
    if _blank(text):
        return None
    found = []
    position = 0
    for _ in range(4):
        section = _section(text, position)
        if section is None:
            return None
        position, number = section
        found.append(number)
    if position != len(text):
        return None
    major, minor, patch, revision = found
    return major, minor, patch, revision


def _section(text: str, start: int) -> tuple[int, int] | None:
    """Un nombre de ``text`` à partir de ``start``, et où reprendre : après son ``.``."""
    length = len(text)
    if start == length:
        return start, 0
    end = start
    while end < length and _is_space(text[end]):
        end += 1
    if end < length and not _is_digit(text[end]):
        return None
    number = 0
    digits = False
    done = False
    while end < length:
        char = text[end]
        if _is_digit(char):
            digits = True
            number = number * 10 + ord(char) - ord("0")
            if number > _INT_MAX:
                return None
        elif char == ".":
            end += 1
            if end == length:
                return None
            done = True
            break
        elif _is_space(char):
            break
        else:
            return None
        end += 1
    if not digits:
        return None
    if end == length:
        done = True
    if not done:
        while end < length:
            char = text[end]
            if not _is_space(char):
                if char != ".":
                    return None
                end += 1
                if end == length:
                    return None
                break
            end += 1
    return end, number


def _label_key(label: str) -> tuple[int, int, str]:
    """``VersionComparer.CompareRelease`` : un nombre (``int.TryParse``) avant un mot, deux
    nombres comme des nombres, deux mots sans tenir compte de la casse."""
    if _NUMERIC.fullmatch(label) and -_INT_MAX - 1 <= int(label) <= _INT_MAX:
        return (0, int(label), "")
    return (1, 0, label.upper())


@functools.total_ordering
class NuGetVersion:
    """Une version lue, comparable comme ``VersionComparer.Default`` (sans les métadonnées)."""

    __slots__ = ("key", "labels", "metadata", "numbers", "text")

    def __init__(
        self, text: str, numbers: tuple[int, int, int, int], labels: tuple[str, ...], metadata: str
    ) -> None:
        self.text = text
        """La version telle qu'écrite."""
        self.numbers = numbers
        """Majeure, mineure, correctif, révision."""
        self.labels = labels
        self.metadata = metadata
        self.key = (*numbers, 0 if labels else 1, tuple(_label_key(label) for label in labels))

    def __repr__(self) -> str:
        return f"NuGetVersion({self.text!r})"

    def __str__(self) -> str:
        return self.text

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, NuGetVersion):
            return NotImplemented
        return self.key == other.key

    def __hash__(self) -> int:
        return hash(self.key)

    def __lt__(self, other: "NuGetVersion") -> bool:
        return self.key < other.key

    @property
    def prerelease(self) -> bool:
        return bool(self.labels)

    @property
    def release(self) -> str:
        """Les étiquettes, jointes par ``.`` (``Release``)."""
        return ".".join(self.labels)

    @property
    def normalized(self) -> str:
        """``ToNormalizedString`` : trois nombres, le quatrième s'il n'est pas nul, les
        étiquettes telles qu'écrites, sans les métadonnées (``1.0`` → ``1.0.0``)."""
        major, minor, patch, revision = self.numbers
        text = f"{major}.{minor}.{patch}" + (f".{revision}" if revision else "")
        return f"{text}-{self.release}" if self.labels else text


def _try_version(value: str | None) -> NuGetVersion | None:
    """``NuGetVersion.TryParse``."""
    if value is None:
        return None
    value = _trim(value)
    numbers_text, labels, metadata = _sections(value)
    if not numbers_text:
        return None
    numbers = _numbers(numbers_text)
    if numbers is None:
        return None
    if labels is not None and not all(_valid_part(label, leading_zeros=False) for label in labels):
        return None
    if metadata is not None and not all(
        _valid_part(part, leading_zeros=True) for part in metadata.split(".")
    ):
        return None
    return NuGetVersion(value, numbers, tuple(labels or ()), metadata or "")


@functools.lru_cache(maxsize=8192)
def _parse(version: str) -> NuGetVersion:
    parsed = _try_version(version)
    if parsed is None:
        raise InvalidVersion(f"version NuGet illisible : {version!r}")
    return parsed


# ---------------------------------------------------------------------------
# Versions flottantes
# ---------------------------------------------------------------------------


class Float(enum.Enum):
    """``NuGetVersionFloatBehavior`` : ce qui flotte."""

    NONE = "none"
    PRERELEASE = "prerelease"
    """``1.0.0-*``, ``1.0.0-beta.*`` : la plus haute pré-version (ou la finale) de 1.0.0."""
    REVISION = "revision"
    PATCH = "patch"
    MINOR = "minor"
    MAJOR = "major"
    ABSOLUTE_LATEST = "absolute-latest"
    """``*-*`` : la plus haute, pré-versions comprises."""
    PRERELEASE_REVISION = "prerelease-revision"
    PRERELEASE_PATCH = "prerelease-patch"
    PRERELEASE_MINOR = "prerelease-minor"
    PRERELEASE_MAJOR = "prerelease-major"


_WITH_PRERELEASES = frozenset(
    {
        Float.ABSOLUTE_LATEST,
        Float.PRERELEASE,
        Float.PRERELEASE_MAJOR,
        Float.PRERELEASE_MINOR,
        Float.PRERELEASE_PATCH,
        Float.PRERELEASE_REVISION,
    }
)
_ZERO = NuGetVersion("0.0.0", (0, 0, 0, 0), (), "")


class FloatRange:
    """``FloatRange`` : ce que désigne une version flottante, et sa plus petite version."""

    __slots__ = ("behavior", "minimum", "prefix")

    def __init__(self, behavior: Float, minimum: NuGetVersion, prefix: str | None = None) -> None:
        if prefix is None and minimum.prerelease:
            prefix = minimum.release
        if behavior is Float.ABSOLUTE_LATEST and prefix is None:
            prefix = ""
        if behavior in _WITH_PRERELEASES and prefix is None:
            raise InvalidConstraint("version flottante sans étiquette")
        self.behavior = behavior
        self.minimum = minimum
        self.prefix = prefix
        """Le début des étiquettes des pré-versions désignées (``beta.`` pour ``1.0-beta.*``)."""

    def satisfies(self, version: NuGetVersion) -> bool:
        """``FloatRange.Satisfies`` : ``version`` est de celles que désigne la version
        flottante."""
        behavior, minimum = self.behavior, self.minimum
        if behavior is Float.ABSOLUTE_LATEST:
            return True
        if behavior is Float.MAJOR and not version.prerelease:
            return True
        if behavior in _WITH_PRERELEASES:
            prefix = self.prefix or ""
            labelled = not version.prerelease or version.release.upper().startswith(prefix.upper())
            same = {
                Float.PRERELEASE_REVISION: 3,
                Float.PRERELEASE_PATCH: 2,
                Float.PRERELEASE_MINOR: 1,
                Float.PRERELEASE_MAJOR: 0,
                Float.PRERELEASE: 4,
            }.get(behavior, 0)
            return minimum.numbers[:same] == version.numbers[:same] and labelled
        same = {Float.REVISION: 3, Float.PATCH: 2, Float.MINOR: 1}.get(behavior)
        if same is None:
            return False
        return minimum.numbers[:same] == version.numbers[:same] and not version.prerelease


_PRERELEASE_FLOATS = {
    1: Float.PRERELEASE_MAJOR,
    2: Float.PRERELEASE_MINOR,
    3: Float.PRERELEASE_PATCH,
    4: Float.PRERELEASE_REVISION,
}
_STABLE_FLOATS = {2: Float.MINOR, 3: Float.PATCH, 4: Float.REVISION}


def _parse_float(text: str) -> FloatRange | None:
    """``FloatRange.TryParse`` (``text`` n'est pas débarrassé de ses espaces)."""
    if _blank(text):
        return None
    first, last = text.find("*"), text.rfind("*")
    if len(text) == 1 and first == 0:
        return FloatRange(Float.MAJOR, _ZERO)
    if text == "*-*":
        return FloatRange(Float.ABSOLUTE_LATEST, _parse("0.0.0-0"), "")
    if first != last and last != -1 and "+" not in text:
        behavior = Float.NONE
        dash = text.find("-")
        actual = prefix = None
        if dash != -1 and last == len(text) - 1 and first == dash - 1:
            stable = text[: dash - 1] + "0"
            behavior = _PRERELEASE_FLOATS.get(stable.count(".") + 1, Float.NONE)
            prefix = text[dash + 1 : -1]
            actual = f"{stable}-{prefix}{'0' if not prefix or prefix.endswith('.') else ''}"
        version = _try_version(actual)
        return None if version is None else FloatRange(behavior, version, prefix)
    if last == len(text) - 1 and "+" not in text:
        actual = text[:-1]
        prefix = None
        if "-" not in text:
            actual += "0"
            behavior = _STABLE_FLOATS.get(actual.count(".") + 1, Float.NONE)
        else:
            behavior = Float.PRERELEASE
            if text.find("-") == text.rfind("-"):
                prefix = actual[text.rfind("-") + 1 :]
                if not prefix or actual.endswith("."):
                    actual += "0"
                elif actual.endswith("-"):
                    actual += "-"
        version = _try_version(actual)
        return None if version is None else FloatRange(behavior, version, prefix)
    version = _try_version(text)
    return None if version is None else FloatRange(Float.NONE, version)


# ---------------------------------------------------------------------------
# Contraintes
# ---------------------------------------------------------------------------


class NuGetRange(Constraint[NuGetVersion]):
    """Un ``VersionRange`` : voir la docstring du module."""

    __slots__ = ("float", "maximum", "maximum_inclusive", "minimum", "minimum_inclusive")

    def __init__(
        self,
        minimum: NuGetVersion | None,
        minimum_inclusive: bool,
        maximum: NuGetVersion | None,
        maximum_inclusive: bool,
        float_range: FloatRange | None = None,
    ) -> None:
        self.minimum = minimum
        self.minimum_inclusive = minimum is not None and minimum_inclusive
        self.maximum = maximum
        self.maximum_inclusive = maximum is not None and maximum_inclusive
        self.float = float_range

    def __repr__(self) -> str:
        opening = "[" if self.minimum_inclusive else "("
        closing = "]" if self.maximum_inclusive else ")"
        lower = "" if self.minimum is None else self.minimum.normalized
        upper = "" if self.maximum is None else self.maximum.normalized
        floating = f", {self.float.behavior.value}" if self.floating else ""
        return f"NuGetRange({opening}{lower}, {upper}{closing}{floating})"

    @property
    def floating(self) -> bool:
        """``IsFloating`` : une version flottante (``1.*``)."""
        return self.float is not None and self.float.behavior is not Float.NONE

    def contains(self, version: NuGetVersion) -> bool:
        """``VersionRange.Satisfies`` : entre les bornes. Une version flottante y a sa plus
        petite version pour borne basse (``1.*`` accepte ``2.0.0``)."""
        if self.minimum is not None:
            if self.minimum_inclusive and version < self.minimum:
                return False
            if not self.minimum_inclusive and not self.minimum < version:
                return False
        if self.maximum is not None:
            if self.maximum_inclusive and self.maximum < version:
                return False
            if not self.maximum_inclusive and not version < self.maximum:
                return False
        return True

    def lower_bound(self) -> str | None:
        """La borne basse incluse ; celle d'une version flottante (``1.*`` : ``1.0.0``), sauf
        ``*`` et ``*-*``, qui n'en ont pas."""
        if self.float is not None and self.float.behavior in (Float.MAJOR, Float.ABSOLUTE_LATEST):
            return None
        if self.minimum is None or not self.minimum_inclusive:
            return None
        return self.minimum.normalized

    def exact(self) -> str | None:
        """La version que NuGet prend d'après la contrainte seule : sa borne basse incluse, si
        elle ne flotte pas (``1.2.3``, ``[1.2.3]``, ``[1.0,2.0)``)."""
        if self.floating:
            return None
        return self.lower_bound()

    def best_match(self, versions: Iterable[NuGetVersion]) -> NuGetVersion | None:
        """``VersionRange.FindBestMatch`` : la version que NuGet prend parmi ``versions``."""
        best: NuGetVersion | None = None
        for version in versions:
            if self._better(best, version):
                best = version
        return best

    def _better(self, current: NuGetVersion | None, considering: NuGetVersion) -> bool:
        """``VersionRange.IsBetter``."""
        if current is considering:
            return False
        prerelease_bounds = (self.minimum is not None and self.minimum.prerelease) or (
            self.maximum is not None and self.maximum.prerelease
        )
        behavior = None if self.float is None else self.float.behavior
        if not prerelease_bounds and considering.prerelease and behavior not in _WITH_PRERELEASES:
            return False
        if not self.contains(considering):
            return False
        if current is None:
            return True
        if self.floating:
            assert self.float is not None
            current_in = self.float.satisfies(current)
            considering_in = self.float.satisfies(considering)
            if current_in != considering_in:
                return considering_in
            if current_in:
                return current < considering
            current_low = current < self.float.minimum
            considering_low = considering < self.float.minimum
            if current_low != considering_low:
                return current_low
            return considering < current if not current_low else current < considering
        return considering < current


def _parse_range(spec: str) -> NuGetRange:
    """``VersionRange.TryParse``, versions flottantes permises."""
    found = _try_range(spec)
    if found is None:
        raise InvalidConstraint(f"contrainte NuGet illisible : {spec!r}")
    return found


@functools.lru_cache(maxsize=2048)
def _try_range(spec: str) -> NuGetRange | None:
    text = _trim(spec)
    if not text:
        return None
    if text == "*":
        return NuGetRange(_ZERO, True, None, True, _parse_float(text))
    if text[0] in "([":
        minimum_inclusive = text[0] == "["
        if text[-1] not in "])":
            return None
        maximum_inclusive = text[-1] == "]"
        parts = text[1:-1].split(",")
        if len(parts) > 2 or all(not part for part in parts):
            return None
        if len(parts) == 1 and not (minimum_inclusive and maximum_inclusive):
            return None
        minimum_text, maximum_text = parts[0], parts[-1]
    else:
        minimum_inclusive, maximum_inclusive = True, False
        minimum_text, maximum_text = text, None
    minimum = maximum = None
    float_range = None
    if not _blank(minimum_text):
        if "*" in minimum_text:
            float_range = _parse_float(minimum_text)
            if float_range is None:
                return None
            minimum = float_range.minimum
        else:
            minimum = _try_version(minimum_text)
            if minimum is None:
                return None
    if maximum_text is not None and not _blank(maximum_text):
        maximum = _try_version(maximum_text)
        if maximum is None:
            return None
    if minimum is not None and maximum is not None:
        if maximum < minimum:
            return None
        if minimum == maximum and minimum_inclusive != maximum_inclusive:
            return None
    return NuGetRange(minimum, minimum_inclusive, maximum, maximum_inclusive, float_range)


class NuGetVersions(VersionScheme[NuGetVersion]):
    """``NuGetVersion``, ``VersionRange`` et le choix de NuGet (la plus basse qui convient)."""

    ecosystem = Ecosystem.NUGET
    lowest = True

    def parse(self, version: str) -> NuGetVersion:
        return _parse(version)

    def parse_constraint(self, constraint: str) -> NuGetRange:
        return _parse_range(constraint)

    def _release(self, version: NuGetVersion) -> tuple[int, int, int]:
        major, minor, patch, _ = version.numbers
        return major, minor, patch

    def _is_pre(self, version: NuGetVersion) -> bool:
        return version.prerelease

    def _same_release(self, a: NuGetVersion, b: NuGetVersion) -> bool:
        return a.numbers == b.numbers

    def normalize(self, version: str) -> str:
        """``version`` comme l'écrit NuGet (``ToNormalizedString``) : ``1.0`` → ``1.0.0``."""
        return self.parse(version).normalized

    def reaches(self, constraint: str, version: str) -> bool:
        """Seule une version flottante monte sans réécriture, jusqu'à la plus haute de ce qu'elle
        désigne ; ailleurs, NuGet garde la borne basse."""
        parsed = self.parse_constraint(constraint)
        wanted = self.parse(version)
        if parsed.floating:
            assert parsed.float is not None
            return parsed.float.satisfies(wanted) and parsed.contains(wanted)
        exact = parsed.exact()
        return exact is not None and self.parse(exact) == wanted

    def chosen(
        self, constraint: str, versions: Iterable[str], current: str | None = None
    ) -> str | None:
        """``VersionRange.FindBestMatch`` sur ``versions`` : la plus basse qui convient, la plus
        haute de ce que désigne une version flottante."""
        parsed = self.parse_constraint(constraint)
        readable = {}
        for text in versions:
            try:
                readable.setdefault(self.parse(text), text)
            except InvalidVersion:
                continue
        best = parsed.best_match(readable)
        return None if best is None else readable[best]


NUGET = NuGetVersions()
"""Les règles de version de NuGet."""
