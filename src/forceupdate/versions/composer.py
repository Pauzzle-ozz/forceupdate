"""Les versions Composer (Packagist) : la normalisation de Composer, l'ordre de PHP, ses
contraintes.

Composer lit une version avec ``VersionParser::normalize`` (composer/semver), puis compare les
versions normalisées avec ``version_compare`` de PHP. Écrit ici à la main, d'après le code de
composer/semver embarqué dans Composer 2.11 :

- ``v`` toléré devant (``v5.4.10``, comme l'écrit Symfony) ; de un à quatre nombres, les manquants
  à 0 (``1.2`` se lit ``1.2.0.0``) ; une version datée (``2010-01-02``) aussi ;
- les stabilités ``alpha`` (``a``), ``beta`` (``b``), ``RC``, ``patch`` (``pl``, ``p``), suivies ou
  non d'un nombre (``1.0.0-beta.2``, ``1.0.0beta2``, ``1.0.0-RC1``) ; ``-stable`` ne compte pas ;
  les métadonnées de build (``+build``) sont retirées ;
- l'ordre de ``version_compare`` : ``dev`` < ``alpha`` < ``beta`` < ``RC`` < la version <
  ``patch`` (``1.0.0-patch1`` vient après ``1.0.0`` : ce n'est pas une pré-version) ;
- une branche (``dev-master``, ``1.x-dev``) n'est pas une version : illisible ici. Une dépendance
  qui en demande une n'est pas vérifiable (``parsers.php``).

Les contraintes (``VersionParser::parseConstraints``) :

- ``||`` ou ``|`` entre les membres d'une union ; une virgule ou une espace entre des comparateurs
  à respecter tous (``>=1.2 <2.0``, ``>=1.2,<2.0``) ;
- **une version nue est exacte** : ``1.2`` veut dire ``==1.2.0.0`` (pas ``^1.2`` comme pour
  Cargo) ;
- ``^`` comme npm, règles du 0.x comprises ; **``~`` est la « prochaine version
  significative »** : ``~1.2`` veut dire ``>=1.2,<2.0`` (pas ``<1.3`` comme npm), ``~1.2.3``
  veut dire ``>=1.2.3,<1.3`` ;
- ``*`` accepte tout ; ``1.2.*`` (``x``, ``X``) est un joker ; ``1.0 - 2.0`` un intervalle (une fin
  partielle en exclut la suite : ``1.0 - 2`` veut dire ``>=1.0,<3.0``) ;
- ``@dev``, ``@alpha``, ``@beta``, ``@RC`` (``^1.0@beta``, ``@dev`` seul) : la stabilité acceptée
  pour ce paquet, au lieu de ``stable`` ; une pré-version écrite dans la contrainte (``^2.0-beta1``)
  vaut aussi pour sa stabilité ;
- ``~>`` est refusé, comme par Composer ; ``1.0 as 2.0`` (un alias) se lit ``1.0``.

Une contrainte accepte les pré-versions qu'encadrent ses bornes (``^1.2`` accepte ``1.5.0-beta1``)
: c'est la stabilité qui les écarte, dans Composer comme ici (``candidates``, ``max_satisfying``).
La stabilité minimale du projet (``minimum-stability``) n'est pas connue d'une contrainte : celle
par défaut, ``stable``, est prise (voir ``parsers.php``).

``str()`` d'une contrainte donne sa forme normalisée (``^1.2`` → ``>=1.2.0.0-dev <2.0.0.0-dev``).
"""

import functools
import re
from collections.abc import Iterable
from dataclasses import dataclass

from forceupdate.models import Ecosystem
from forceupdate.versions.base import Constraint, InvalidConstraint, InvalidVersion, VersionScheme

_MODIFIER = r"[._-]?(?:(stable|beta|b|RC|alpha|a|patch|pl|p)((?:[.-]?\d+)*+)?)?([.-]?dev)?"
_STABILITY_FLAG = r"stable|RC|beta|alpha|dev"

_ALIAS = re.compile(r"([^,\s]++) ++as ++([^,\s]++)")
_FLAG_SUFFIX = re.compile(rf"@(?:{_STABILITY_FLAG})$", re.IGNORECASE)
_BUILD = re.compile(r"([^,\s+]++)\+[^\s]++")
_CLASSICAL = re.compile(rf"v?(\d{{1,5}}+)(\.\d++)?(\.\d++)?(\.\d++)?{_MODIFIER}", re.IGNORECASE)
_DATED = re.compile(
    rf"v?(\d{{4}}(?:[.:-]?\d{{2}}){{1,6}}(?:[.:-]?\d{{1,3}}){{0,2}}){_MODIFIER}", re.IGNORECASE
)
_DEV_SUFFIX = re.compile(r"(.*?)[.-]?dev", re.IGNORECASE)
_BRANCH_NUMBERS = re.compile(
    r"v?(\d++)(\.(?:\d++|[xX*]))?(\.(?:\d++|[xX*]))?(\.(?:\d++|[xX*]))?", re.IGNORECASE
)

_VERSION = (
    r"v?(\d++)(?:\.(\d++))?(?:\.(\d++))?(?:\.(\d++))?"
    rf"(?:{_MODIFIER}|\.([xX*][.-]?dev))(?:\+[^\s]+)?"
)
"""Une version dans une contrainte : ses quatre nombres (groupes 1 à 4), sa stabilité (5, 6), un
``-dev`` (7), un ``.x-dev`` (8)."""
_TILDE = re.compile(rf"~>?{_VERSION}", re.IGNORECASE)
_CARET = re.compile(rf"\^{_VERSION}", re.IGNORECASE)
_WILDCARD = re.compile(r"v?(\d++)(?:\.(\d++))?(?:\.(\d++))?(?:\.[xX*])++")
_HYPHEN = re.compile(rf"(?P<from>{_VERSION}) +- +(?P<to>{_VERSION})", re.IGNORECASE)
_MATCH_ALL = re.compile(r"(v)?[xX*](\.[xX*])*", re.IGNORECASE)
_COMPARATOR = re.compile(r"(<>|!=|>=?|<=?|==?)?\s*(.*)", re.DOTALL)
_REF = re.compile(r"(dev-[^,\s@]+?|[^,\s@]+?\.x-dev)#.+", re.IGNORECASE)
_FLAGGED = re.compile(rf"([^,\s]*?)@({_STABILITY_FLAG})", re.IGNORECASE)

_OR = re.compile(r"\s*\|\|?\s*")
_AND = re.compile(r"(?<!^)(?<!as)(?<![=>< ,]) *(?<!-)[, ](?!-) *(?!,|as|$)")
"""Le séparateur des comparateurs, celui de Composer. Python n'a pas de lookbehind de longueur
variable : ``(?<!^|as|[=>< ,])`` y devient trois lookbehinds."""

STABILITIES = {"stable": 0, "RC": 5, "beta": 10, "alpha": 15, "dev": 20}
"""Les stabilités de Composer, de la plus stable à la moins stable
(``BasePackage::$stabilities``)."""

_OPERATORS = {
    "=": "==",
    "==": "==",
    "<>": "!=",
    "!=": "!=",
    "<": "<",
    "<=": "<=",
    ">": ">",
    ">=": ">=",
}

_SPECIAL_FORMS = (
    ("dev", 0),
    ("alpha", 1),
    ("a", 1),
    ("beta", 2),
    ("b", 2),
    ("RC", 3),
    ("rc", 3),
    ("#", 4),
    ("pl", 5),
    ("p", 5),
)
"""L'ordre des mots de ``version_compare`` de PHP : un mot est reconnu par son début, dans cet ordre
(``patch`` est un ``p``) ; un nombre vaut ``#`` ; un mot inconnu vient avant tout (-1)."""

_DIGITS = frozenset("0123456789")


def _special(token: str) -> int:
    return next((order for name, order in _SPECIAL_FORMS if token.startswith(name)), -1)


def _canonical(version: str) -> list[str]:
    """Les éléments de ``version`` comme les découpe ``version_compare`` (``php_canonicalize_
    version``) : ``-``, ``_`` et ``+`` deviennent des points, un point sépare chiffres et lettres
    (``1.0.0.0-beta2`` → ``1``, ``0``, ``0``, ``0``, ``beta``, ``2``)."""
    if not version:
        return []
    out = [version[0]]
    previous = version[0]
    for char in version[1:]:
        digit, previous_digit = char in _DIGITS, previous in _DIGITS
        if char in "-_+":
            if out[-1] != ".":
                out.append(".")
        elif (previous != "." and previous_digit != digit) and char != ".":
            if out[-1] != ".":
                out.append(".")
            out.append(char)
        elif not (char.isascii() and char.isalnum()):
            if out[-1] != ".":
                out.append(".")
        else:
            out.append(char)
        previous = char
    return "".join(out).split(".")


_Key = tuple[tuple[int, int], ...]


@functools.lru_cache(maxsize=8192)
def _key(normalized: str) -> _Key:
    """Une clé qui range comme ``version_compare`` : un nombre est ``(4, n)``, un mot ``(son rang,
    0)`` ; la fin vaut ``(4, -1)``, juste sous tout nombre : ``1.0`` < ``1.0.0``, ``1.0.0.0-dev`` <
    ``1.0.0.0`` < ``1.0.0.0-patch1``, comme le fait PHP quand une version a plus d'éléments."""
    tokens = [
        (4, int(token)) if token[:1] in _DIGITS else (_special(token), 0)
        for token in _canonical(normalized)
        if token
    ]
    return (*tokens, (4, -1))


@functools.total_ordering
@dataclass(frozen=True, eq=False)
class ComposerVersion:
    """Une version normalisée par Composer (``1.2.0.0``, ``5.4.10.0-RC1``)."""

    normalized: str

    @functools.cached_property
    def key(self) -> _Key:
        return _key(self.normalized)

    @functools.cached_property
    def release(self) -> tuple[int, int, int]:
        """Ses trois premiers nombres."""
        numbers = [int(part) for part in self.normalized.split("-", 1)[0].split(".") if part]
        major, minor, patch = (*numbers, 0, 0, 0)[:3]
        return major, minor, patch

    @functools.cached_property
    def stability(self) -> str:
        """``stable``, ``RC``, ``beta``, ``alpha`` ou ``dev`` (``patch`` est stable)."""
        return parse_stability(self.normalized)

    def __str__(self) -> str:
        return self.normalized

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ComposerVersion) and self.key == other.key

    def __lt__(self, other: "ComposerVersion") -> bool:
        return self.key < other.key

    def __hash__(self) -> int:
        return hash(self.key)


def parse_stability(version: str) -> str:
    """La stabilité d'une version ou d'une contrainte telle qu'écrite (``VersionParser::
    parseStability``) : ``dev`` pour une branche, sinon celle de son suffixe, ``stable`` sans."""
    version = re.sub(r"#.+$", "", version)
    if version.startswith("dev-") or version.endswith("-dev"):
        return "dev"
    match = re.search(rf"{_MODIFIER}(?:\+.*)?$", version.lower(), re.IGNORECASE)
    if match is not None:
        if match.group(3):
            return "dev"
        found = match.group(1)
        if found in ("beta", "b"):
            return "beta"
        if found in ("alpha", "a"):
            return "alpha"
        if found == "rc":
            return "RC"
    return "stable"


def _expand_stability(stability: str) -> str:
    lowered = stability.lower()
    return {"a": "alpha", "b": "beta", "p": "patch", "pl": "patch", "rc": "RC"}.get(
        lowered, lowered
    )


def normalize(version: str) -> str:
    """``version`` normalisée comme par Composer (``VersionParser::normalize``) : ``v1.2`` →
    ``1.2.0.0``, ``1.0.0-beta.2`` → ``1.0.0.0-beta2``, ``dev-main`` et ``1.x-dev`` (branches) →
    ``dev-main``, ``1.9999999.9999999.9999999-dev``. Lève ``InvalidVersion``."""
    original = version
    version = version.strip()
    alias = _ALIAS.fullmatch(version)
    if alias is not None:
        version = alias.group(1)
    flag = _FLAG_SUFFIX.search(version)
    if flag is not None:
        version = version[: flag.start()]
    if version in ("master", "trunk", "default"):
        version = f"dev-{version}"
    if version[:4].lower() == "dev-":
        return f"dev-{version[4:]}"
    build = _BUILD.fullmatch(version)
    if build is not None:
        version = build.group(1)
    found: list[str] | None = None
    match = _CLASSICAL.fullmatch(version)
    if match is not None:
        numbers = [match.group(1), *(match.group(i) or ".0" for i in (2, 3, 4))]
        normalized = "".join(numbers)
        found = [normalized, *(match.group(i) or "" for i in (5, 6, 7))]
    else:
        match = _DATED.fullmatch(version)
        if match is not None:
            normalized = re.sub(r"\D", ".", match.group(1))
            found = [normalized, *(match.group(i) or "" for i in (2, 3, 4))]
    if found is not None:
        normalized, stability, number, dev = found
        if stability:
            if stability == "stable":
                return normalized
            normalized += f"-{_expand_stability(stability)}{number.lstrip('.-')}"
        if dev:
            normalized += "-dev"
        return normalized
    dev_branch = _DEV_SUFFIX.fullmatch(version)
    if dev_branch is not None:
        branch = _normalize_branch(dev_branch.group(1))
        if "dev-" not in branch:
            return branch
    raise InvalidVersion(f"version Composer illisible : {original!r}")


def _normalize_branch(name: str) -> str:
    match = _BRANCH_NUMBERS.fullmatch(name.strip())
    if match is None:
        return f"dev-{name.strip()}"
    parts = [
        (match.group(i) or ".x").replace("*", "x").replace("X", "x") if i > 1 else match.group(1)
        for i in range(1, 5)
    ]
    return "".join(parts).replace("x", "9999999") + "-dev"


def is_branch(normalized: str) -> bool:
    """Vrai pour une version normalisée de stabilité ``dev`` : une branche (``dev-main``,
    ``1.9999999.9999999.9999999-dev`` pour ``1.x-dev``), jamais une version publiée."""
    return normalized.startswith("dev-") or normalized.endswith("-dev")


def _branch_like(normalized: str) -> bool:
    """Vrai pour la borne d'une contrainte qui désigne une branche (``dev-main``, ``1.x-dev``).
    Pour comparer, Composer ne tient pour branche que ``dev-…`` : ``>=1.2.0.0-dev``, la borne de
    ``^1.2``, se compare comme une version."""
    return normalized.startswith("dev-") or normalized.endswith("9999999-dev")


@functools.lru_cache(maxsize=8192)
def _parse(version: str) -> ComposerVersion:
    normalized = normalize(version)
    if is_branch(normalized):
        raise InvalidVersion(f"branche de développement, pas une version publiée : {version!r}")
    return ComposerVersion(normalized)


# ---------------------------------------------------------------------------
# Contraintes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Bound:
    """Un comparateur : ``operator`` (``==``, ``!=``, ``<``, ``<=``, ``>``, ``>=``) et une version
    normalisée, ou une branche (``dev-main``)."""

    operator: str
    version: str
    written: str = ""
    """La version telle qu'écrite, pour une contrainte exacte (``1.2``, ``v5.4.0``)."""

    def __str__(self) -> str:
        return f"{self.operator}{self.version}"

    def test(self, version: ComposerVersion) -> bool:
        """``Constraint::matchSpecific`` de composer/semver, pour une version publiée : une
        branche (``dev-…``) n'accepte aucune version, ``!=`` d'une branche les accepte toutes."""
        if self.version.startswith("dev-"):
            return self.operator == "!="
        bound = _key(self.version)
        here = version.key
        if self.operator == "==":
            return here == bound
        if self.operator == "!=":
            return here != bound
        if self.operator == "<":
            return here < bound
        if self.operator == "<=":
            return here <= bound
        if self.operator == ">":
            return here > bound
        return here >= bound


class ComposerConstraint(Constraint[ComposerVersion]):
    """Une contrainte Composer : une union d'ensembles de comparateurs, tous à respecter ; un
    ensemble vide accepte tout (``*``)."""

    def __init__(self, groups: tuple[tuple[_Bound, ...], ...], stability: str | None) -> None:
        self.groups = groups
        self.stability = stability
        """La stabilité la moins stable que permet la contrainte (``@beta``, ``^2.0-beta1``) ;
        ``None`` : celle du projet (``stable`` par défaut)."""

    def __str__(self) -> str:
        return " || ".join(" ".join(str(b) for b in group) or "*" for group in self.groups)

    def __repr__(self) -> str:
        return f"ComposerConstraint({str(self)!r})"

    def contains(self, version: ComposerVersion) -> bool:
        return any(all(bound.test(version) for bound in group) for group in self.groups)

    def lower_bound(self) -> str | None:
        """La plus haute borne basse de chaque ensemble, puis la plus petite de l'union, sans son
        ``-dev`` (``^1.2`` → ``1.2.0``). Une borne exclue (``>1.2``) est rendue telle quelle,
        comme pour PyPI : la version suivante n'existe pas. ``None`` sans borne basse (``*``,
        ``<2``, une branche) ou si elle est ``0.0.0``."""
        lowest: tuple[_Key, str] | None = None
        for group in self.groups:
            bounds = [
                b for b in group if b.operator in ("==", ">", ">=") and not _branch_like(b.version)
            ]
            if not bounds:
                return None
            bound = max(bounds, key=lambda b: _key(b.version))
            if lowest is None or _key(bound.version) < lowest[0]:
                lowest = (_key(bound.version), bound.version)
        if lowest is None:
            return None
        shown = _shown(lowest[1])
        return None if shown == "0.0.0" else shown

    def exact(self) -> str | None:
        """``1.2.3``, ``=1.2.3``, ``==v1.2.3`` seuls : la version telle qu'écrite. Un joker
        (``1.2.*``) ou une branche n'en sont pas."""
        if len(self.groups) != 1 or len(self.groups[0]) != 1:
            return None
        (bound,) = self.groups[0]
        if bound.operator != "==" or _branch_like(bound.version):
            return None
        return bound.written or _shown(bound.version)


def _shown(normalized: str) -> str:
    """Une version normalisée telle qu'on l'écrit : sans ``-dev``, et à trois nombres quand le
    quatrième est nul (``1.2.0.0-dev`` → ``1.2.0``, ``1.2.0.0-beta2`` → ``1.2.0-beta2``)."""
    text = normalized.removesuffix("-dev")
    numbers, dash, rest = text.partition("-")
    parts = numbers.split(".")
    if len(parts) == 4 and parts[3] == "0":
        parts = parts[:3]
    return ".".join(parts) + dash + rest


def _groups(match: re.Match[str], first: int) -> list[str]:
    """Les groupes ``first`` à ``first + 4`` d'une version de contrainte, ``""`` pour un absent
    (comme ``preg_match``), précédés d'un vide : ``[_, majeure, mineure, correctif, quatrième]``."""
    return ["", *(match.group(first + i) or "" for i in range(4))]


def _manipulate(numbers: list[str], position: int, increment: int = 0) -> str:
    """``VersionParser::manipulateVersionString`` : les nombres après ``position`` à 0, celui de
    ``position`` augmenté de ``increment``."""
    values = list(numbers)
    for index in range(4, 0, -1):
        if index > position:
            values[index] = "0"
        elif index == position and increment:
            values[index] = str(int(values[index]) + increment)
    return ".".join(values[1:5])


def _parse_one(text: str) -> tuple[list[_Bound], str | None]:
    """Un comparateur tel qu'écrit (``VersionParser::parseConstraint``) : ses bornes, et la
    stabilité qu'il demande (``@beta``). Lève ``InvalidConstraint``."""
    constraint = text
    alias = _ALIAS.fullmatch(constraint)
    if alias is not None:
        constraint = alias.group(1)
    modifier = None
    flagged = _FLAGGED.fullmatch(constraint)
    if flagged is not None:
        constraint = flagged.group(1) or "*"
        if flagged.group(2) != "stable":
            modifier = flagged.group(2)
    ref = _REF.fullmatch(constraint)
    if ref is not None:
        constraint = ref.group(1)
    every = _MATCH_ALL.fullmatch(constraint)
    if every is not None:
        if every.group(1) or every.group(2):
            return [_Bound(">=", "0.0.0.0-dev")], modifier
        return [], modifier

    try:
        tilde = _TILDE.fullmatch(constraint)
        if tilde is not None:
            if constraint.startswith("~>"):
                raise InvalidConstraint(f"« ~> » n'existe pas pour Composer (« ~ ») : {text!r}")
            numbers = _groups(tilde, 1)
            position = max((i for i in range(1, 5) if numbers[i]), default=1)
            if tilde.group(8):
                position += 1
            suffix = "" if tilde.group(5) or tilde.group(7) or tilde.group(8) else "-dev"
            low = normalize(constraint[1:] + suffix)
            high = _manipulate(numbers, max(1, position - 1), 1) + "-dev"
            return [_Bound(">=", low), _Bound("<", high)], modifier

        caret = _CARET.fullmatch(constraint)
        if caret is not None:
            numbers = _groups(caret, 1)
            if numbers[1] != "0" or not numbers[2]:
                position = 1
            elif numbers[2] != "0" or not numbers[3]:
                position = 2
            else:
                position = 3
            suffix = "" if caret.group(5) or caret.group(7) or caret.group(8) else "-dev"
            low = normalize(constraint[1:] + suffix)
            high = _manipulate(numbers, position, 1) + "-dev"
            return [_Bound(">=", low), _Bound("<", high)], modifier

        wildcard = _WILDCARD.fullmatch(constraint)
        if wildcard is not None:
            numbers = ["", *(wildcard.group(i) or "" for i in range(1, 4)), ""]
            position = max((i for i in range(1, 4) if numbers[i]), default=1)
            low = _manipulate(numbers, position) + "-dev"
            high = _manipulate(numbers, position, 1) + "-dev"
            if low == "0.0.0.0-dev":
                return [_Bound("<", high)], modifier
            return [_Bound(">=", low), _Bound("<", high)], modifier

        hyphen = _HYPHEN.fullmatch(constraint)
        if hyphen is not None:
            return _hyphen(hyphen), modifier

        comparator = _COMPARATOR.fullmatch(constraint)
        assert comparator is not None  # tout texte y correspond
        operator, written = comparator.group(1) or "=", comparator.group(2)
        try:
            version = normalize(written)
        except InvalidVersion:
            # « foo-dev » se lit « dev-foo », sauf derrière un opérateur.
            if written.endswith("-dev") and re.fullmatch(r"[0-9a-zA-Z\-./]+", written):
                version = normalize("dev-" + written[:-4])
            else:
                raise
        if operator not in ("==", "=") and modifier and parse_stability(version) == "stable":
            version += f"-{modifier}"
        elif (
            operator in ("<", ">=")
            and not re.search(rf"-{_MODIFIER}$", written, re.IGNORECASE)
            and not written.startswith("dev-")
        ):
            version += "-dev"
        return [_Bound(_OPERATORS[operator], version, written.strip())], modifier
    except InvalidVersion as error:
        raise InvalidConstraint(f"contrainte Composer illisible : {text!r} ({error})") from None


def _hyphen(match: re.Match[str]) -> list[_Bound]:
    """``1.0 - 2.0`` : de la première version comprise à la seconde ; une seconde partielle en
    accepte toute la suite (``1.0 - 2`` : ``<3.0``)."""

    def empty(value: str | None) -> bool:
        return value is None or value == ""

    suffix = "" if match.group(6) or match.group(8) or match.group(9) else "-dev"
    low = normalize(match.group("from")) + suffix
    if (not empty(match.group(12)) and not empty(match.group(13))) or any(
        match.group(i) for i in (15, 17, 18)
    ):
        return [_Bound(">=", low), _Bound("<=", normalize(match.group("to")))]
    numbers = ["", *(match.group(i) or "" for i in (11, 12, 13, 14))]
    normalize(match.group("to"))
    high = _manipulate(numbers, 1 if empty(match.group(12)) else 2, 1) + "-dev"
    return [_Bound(">=", low), _Bound("<", high)]


def _stability(text: str) -> str | None:
    """La stabilité que permet une contrainte (``RootPackageLoader::extractStabilityFlags``, sans
    la stabilité minimale du projet) : le drapeau le moins stable (``@beta``), sinon celle d'une
    version écrite en pré-version (``^2.0-beta1``) ; ``None`` pour ``stable``."""
    parts = [part for member in _OR.split(text.strip()) for part in _AND.split(member)]
    found = [
        match.group(1)
        for part in parts
        if (match := re.fullmatch(rf"[^@]*?@({_STABILITY_FLAG})", part, re.IGNORECASE))
    ]
    if not found:
        for part in parts:
            written = re.sub(r"^([^,\s@]+) as .+$", r"\1", part)
            if re.fullmatch(r"[^,\s@]+", written):
                found.append(parse_stability(written))
    if not found:
        return None
    named = [_normalize_flag(flag) for flag in found]
    worst = max(named, key=lambda name: STABILITIES[name])
    return None if worst == "stable" else worst


def _normalize_flag(flag: str) -> str:
    lowered = flag.lower()
    return "RC" if lowered == "rc" else lowered


@functools.lru_cache(maxsize=2048)
def _parse_constraint(constraint: str) -> ComposerConstraint:
    groups = []
    for member in _OR.split(constraint.strip()):
        bounds: list[_Bound] = []
        for part in _AND.split(member):
            found, _ = _parse_one(part)
            bounds += found
        groups.append(tuple(bounds))
    return ComposerConstraint(tuple(groups), _stability(constraint))


class ComposerVersions(VersionScheme[ComposerVersion]):
    """La normalisation de Composer, l'ordre de ``version_compare``, les contraintes de Composer."""

    ecosystem = Ecosystem.PACKAGIST

    def parse(self, version: str) -> ComposerVersion:
        return _parse(version)

    def parse_constraint(self, constraint: str) -> ComposerConstraint:
        return _parse_constraint(constraint)

    def _release(self, version: ComposerVersion) -> tuple[int, int, int]:
        return version.release

    def _is_pre(self, version: ComposerVersion) -> bool:
        return version.stability != "stable"

    def max_satisfying(
        self, constraint: str, versions: Iterable[str], current: str | None = None
    ) -> str | None:
        """La plus haute version acceptée, comme le choisit Composer : stable seulement (et la
        ligne de ``current`` quand c'est une pré-version, voir ``candidates``), sauf si la
        contrainte permet une autre stabilité (``@beta`` : bêtas, RC et stables)."""
        parsed = self.parse_constraint(constraint)
        if parsed.stability is None:
            return super().max_satisfying(constraint, versions, current)
        allowed = STABILITIES[parsed.stability]
        best: tuple[str, ComposerVersion] | None = None
        for text in versions:
            try:
                version = self.parse(text)
            except InvalidVersion:
                continue
            if STABILITIES[version.stability] > allowed or not parsed.contains(version):
                continue
            if best is None or best[1] < version:
                best = (text, version)
        return None if best is None else best[0]


COMPOSER = ComposerVersions()
