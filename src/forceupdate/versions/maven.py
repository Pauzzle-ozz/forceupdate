"""Les versions Maven : ``ComparableVersion`` et les plages de ``VersionRange``, réécrits d'après
Maven 3.9.

**Une version** (``ComparableVersion``) est découpée en éléments, sans tenir compte de la casse :

- des nombres et des mots, séparés par ``.`` ou ``-``, ou par le passage d'un chiffre à une lettre
  (``1rc2`` donne ``1``, ``rc``, ``2``) ; un ``-``, un passage chiffre ↔ lettre, ou un mot après
  un ``.``, ouvrent une sous-liste : ``1.0-rc-1`` est ``1, [rc, [1]]`` ;
- les zéros et les mots « de version finale » (``ga``, ``final``, ``release``, et le vide) de fin
  de liste ne comptent pas : ``1.0`` = ``1.0.0`` = ``1-ga`` = ``1.0.RELEASE`` ;
- ``a1``, ``b1``, ``m1`` sont ``alpha-1``, ``beta-1``, ``milestone-1`` ; ``cr`` est ``rc`` ;
- l'ordre des mots connus : ``alpha`` < ``beta`` < ``milestone`` < ``rc`` < ``snapshot`` <
  version finale < ``sp`` ; un mot inconnu vient après tous, dans l'ordre du texte (``1.0-jre``
  est au-dessus de ``1.0``) ; à la même place, un mot < une sous-liste < un nombre (``1-sp`` <
  ``1-1`` < ``1.1``).

Toute chaîne est une version pour Maven ; forceupdate refuse le vide, les espaces et ``,[]()${}``
(une plage, une propriété non résolue).

**Une contrainte** est une « spécification » de ``VersionRange`` :

- une version nue (``1.2.3``) est une **recommandation** : Maven la prend telle quelle, sauf conflit
  plus haut dans l'arbre (le plus proche l'emporte). Sans lockfile, c'est la version utilisée, et
  aucune autre ne s'obtient sans réécrire le manifeste : comme pour Go, elle n'accepte qu'elle
  (``satisfies``), c'est sa borne basse et sa version exacte. (Pour ``VersionRange``, elle
  « contient » toutes les versions.) Gradle lit de même une version nue (« require ») ;
- ``[1.2.3]`` : exactement celle-là ;
- des intervalles : ``[1.0,2.0)``, ``(,1.0]``, ``[1.5,)``, plusieurs séparés par des virgules
  (``(,1.0],[1.2,)``), sans chevauchement ; ``[`` et ``]`` incluent la borne, ``(`` et ``)``
  l'excluent. Gradle écrit aussi ``]1.0,2.0[`` pour exclure. Maven prend la plus haute version
  publiée de l'intervalle, pré-versions comprises (``[1.0,2.0)`` contient ``2.0-alpha-1``, qui est
  sous ``2.0``) ; ``max_satisfying`` n'en propose pas, comme ailleurs ;
- Gradle encore : ``1.+`` (toute version dont le texte commence par ``1.``), ``+``,
  ``latest.release`` et ``latest.integration`` (la dernière : pas de borne basse), ``1.2.3!!``
  (« strictly » : exactement celle-là).

Vérifié contre ``maven-artifact`` 3.9.16 (``ComparableVersion``, ``VersionRange``), lancé par Java :
voir les notes de E25 dans ``PLAN.md``.

**Pré-version** : une version sous sa version finale (``alpha``, ``beta``, ``milestone``, ``rc``,
``snapshot``), ou marquée par un mot que Maven range au-dessus mais qui en annonce une (``dev``,
``ea``, ``pre``, ``preview``). ``1.0-jre``, ``1.0-sp1`` ou ``1.0.Final`` n'en sont pas.

**Variante** : les autres mots d'une version (``jre`` et ``android`` de Guava). Une version d'une
autre variante n'est jamais proposée (``compatible``) : de ``31.0.1-jre``, on monte à
``33.4.0-jre``, pas à ``33.4.0-android``.
"""

import functools
import re

from forceupdate.models import Ecosystem
from forceupdate.versions.base import Constraint, InvalidConstraint, InvalidVersion, VersionScheme

_QUALIFIERS = ("alpha", "beta", "milestone", "rc", "snapshot", "", "sp")
"""Les mots connus de ``ComparableVersion``, dans leur ordre ; le vide est la version finale."""
_ALIASES = {"cr": "rc", "ga": "", "final": "", "release": ""}
_SHORT = {"a": "alpha", "b": "beta", "m": "milestone"}
"""Une lettre seule suivie d'un chiffre : ``a1`` est ``alpha-1``."""
_RELEASE = str(_QUALIFIERS.index(""))
_PRE_WORDS = frozenset(
    {"alpha", "beta", "milestone", "rc", "snapshot", "dev", "ea", "pre", "preview"}
)
"""Les mots qui font une pré-version (voir la docstring du module)."""
_FORBIDDEN = re.compile(r"[\s,\[\]()${}]")

Item = int | str | list["Item"]
"""Un élément : un nombre, un mot (déjà traduit par ``_ALIASES``), ou une sous-liste."""


def _qualifier(value: str, followed_by_digit: bool) -> str:
    if followed_by_digit and len(value) == 1:
        value = _SHORT.get(value, value)
    return _ALIASES.get(value, value)


def _item(is_digit: bool, text: str) -> Item:
    return int(text) if is_digit else _qualifier(text, False)


def _items(version: str) -> list[Item]:
    """Les éléments de ``version``, comme ``ComparableVersion.parseVersion``."""
    text = version.lower()
    root: list[Item] = []
    current = root
    stack = [root]

    def open_list() -> None:
        nonlocal current
        child: list[Item] = []
        current.append(child)
        current = child
        stack.append(child)

    is_digit = False
    start = 0
    for index, char in enumerate(text):
        if char in ".-":
            current.append(0 if index == start else _item(is_digit, text[start:index]))
            start = index + 1
            if char == "-":
                open_list()
        elif char.isdecimal():
            if not is_digit and index > start:
                if current:  # 1.0.0.X1 < 1.0.0-X2 : « .X » se lit comme « -X »
                    open_list()
                current.append(_qualifier(text[start:index], True))
                start = index
                open_list()
            is_digit = True
        else:
            if is_digit and index > start:
                current.append(_item(True, text[start:index]))
                start = index
                open_list()
            is_digit = False
    if len(text) > start:
        if not is_digit and current:
            open_list()
        current.append(_item(is_digit, text[start:]))
    for items in reversed(stack):
        _normalize(items)
    return root


def _is_null(item: Item) -> bool:
    return item == 0 if isinstance(item, int) else not item


def _normalize(items: list[Item]) -> None:
    """Retire les éléments nuls de la fin (``0``, mot de version finale, liste vide), en passant
    par-dessus les sous-listes."""
    for index in range(len(items) - 1, -1, -1):
        if _is_null(items[index]):
            del items[index]
        elif not isinstance(items[index], list):
            break


def _comparable(qualifier: str) -> str:
    """Le rang d'un mot, comparable comme du texte : son indice parmi les connus, sinon après
    eux, dans l'ordre du texte."""
    if qualifier in _QUALIFIERS:
        return str(_QUALIFIERS.index(qualifier))
    return f"{len(_QUALIFIERS)}-{qualifier}"


def _sign(a: object, b: object) -> int:
    return (a > b) - (a < b)  # type: ignore[operator]


def _compare(left: Item, right: Item | None) -> int:
    """``Item.compareTo`` : ``right`` absent (``None``) quand l'autre liste s'arrête."""
    if isinstance(left, int):
        if right is None:
            return 0 if left == 0 else 1
        return _sign(left, right) if isinstance(right, int) else 1
    if isinstance(left, str):
        if right is None:
            return _sign(_comparable(left), _RELEASE)
        if isinstance(right, str):
            return _sign(_comparable(left), _comparable(right))
        return -1
    if right is None:
        return next((result for item in left if (result := _compare(item, None))), 0)
    if isinstance(right, int):
        return -1
    if isinstance(right, str):
        return 1
    for index in range(max(len(left), len(right))):
        first = left[index] if index < len(left) else None
        second = right[index] if index < len(right) else None
        if first is None:
            result = 0 if second is None else -_compare(second, None)
        else:
            result = _compare(first, second)
        if result:
            return result
    return 0


def _canonical(items: list[Item]) -> str:
    """La forme canonique de ``ComparableVersion`` (``1.0-RC1`` → ``1-rc-1``)."""
    parts = []
    for index, item in enumerate(items):
        if index:
            parts.append("-" if isinstance(item, list) else ".")
        parts.append(_canonical(item) if isinstance(item, list) else str(item))
    return "".join(parts)


def _words(items: list[Item]) -> set[str]:
    found = set()
    for item in items:
        if isinstance(item, list):
            found |= _words(item)
        elif isinstance(item, str):
            found.add(item)
    return found


@functools.total_ordering
class MavenVersion:
    """Une version lue, comparable comme ``ComparableVersion``."""

    __slots__ = ("items", "text")

    def __init__(self, text: str) -> None:
        self.text = text
        """La version telle qu'écrite."""
        self.items = _items(text)

    def __repr__(self) -> str:
        return f"MavenVersion({self.text!r})"

    def __str__(self) -> str:
        return self.text

    @property
    def canonical(self) -> str:
        return _canonical(self.items)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MavenVersion):
            return NotImplemented
        return _compare(self.items, other.items) == 0

    def __hash__(self) -> int:
        return hash(self.canonical)

    def __lt__(self, other: "MavenVersion") -> bool:
        return _compare(self.items, other.items) < 0

    @property
    def numbers(self) -> tuple[int, ...]:
        """Les nombres du début, avant le premier mot ou la première sous-liste."""
        found = []
        for item in self.items:
            if not isinstance(item, int):
                break
            found.append(item)
        return tuple(found)

    @property
    def prerelease(self) -> bool:
        return bool(_words(self.items) & _PRE_WORDS)

    @property
    def flavor(self) -> frozenset[str]:
        """Sa variante : les mots qui ne font pas une pré-version (``jre`` de ``31.0.1-jre``,
        ``android``, ``v`` de ``9.4.51.v20230217``)."""
        return frozenset(_words(self.items) - _PRE_WORDS)


@functools.lru_cache(maxsize=8192)
def _parse(version: str) -> MavenVersion:
    text = version.strip()
    if not text or _FORBIDDEN.search(text):
        raise InvalidVersion(f"version Maven illisible : {version!r}")
    return MavenVersion(text)


# ---------------------------------------------------------------------------
# Contraintes
# ---------------------------------------------------------------------------


class Restriction:
    """Un intervalle de ``VersionRange`` : ses bornes, incluses ou non ; ``None`` pour une borne
    absente."""

    __slots__ = ("lower", "lower_inclusive", "text", "upper", "upper_inclusive")

    def __init__(
        self,
        lower: MavenVersion | None,
        lower_inclusive: bool,
        upper: MavenVersion | None,
        upper_inclusive: bool,
        text: str = "",
    ) -> None:
        self.lower = lower
        self.lower_inclusive = lower_inclusive
        self.upper = upper
        self.upper_inclusive = upper_inclusive
        self.text = text
        """L'intervalle tel qu'écrit (``[1.0, 2.0)``)."""

    def __repr__(self) -> str:
        opening = "[" if self.lower_inclusive else "("
        closing = "]" if self.upper_inclusive else ")"
        lower = "" if self.lower is None else self.lower.text
        upper = "" if self.upper is None else self.upper.text
        if self.lower is not None and self.lower is self.upper:
            return f"[{lower}]"
        return f"{opening}{lower},{upper}{closing}"

    def contains(self, version: MavenVersion) -> bool:
        lower, upper = self.lower, self.upper
        if lower is not None and (
            version < lower or (version == lower and not self.lower_inclusive)
        ):
            return False
        return upper is None or not (
            upper < version or (version == upper and not self.upper_inclusive)
        )


class MavenRange(Constraint[MavenVersion]):
    """Une spécification de version Maven (ou Gradle) : voir la docstring du module."""

    def __init__(
        self,
        *,
        recommended: MavenVersion | None = None,
        restrictions: tuple[Restriction, ...] = (),
        prefix: str | None = None,
        latest: bool = False,
    ) -> None:
        self.recommended = recommended
        """La version nue (« recommandation »), ou celle de ``1.2.3!!`` (Gradle)."""
        self.restrictions = restrictions
        self.prefix = prefix
        """Gradle : le début du texte des versions acceptées (``1.`` pour ``1.+``)."""
        self.latest = latest
        """Gradle : ``latest.release``, ``latest.integration``."""

    def __repr__(self) -> str:
        if self.recommended is not None:
            return f"MavenRange({self.recommended.text!r})"
        if self.prefix is not None:
            return f"MavenRange({self.prefix + '+'!r})"
        if self.latest:
            return "MavenRange('latest')"
        return f"MavenRange({','.join(map(repr, self.restrictions))!r})"

    def contains(self, version: MavenVersion) -> bool:
        if self.recommended is not None:
            return version == self.recommended
        if self.prefix is not None:
            return version.text.lower().startswith(self.prefix.lower())
        if self.latest:
            return True
        return any(restriction.contains(version) for restriction in self.restrictions)

    def lower_bound(self) -> str | None:
        """La version nue ; pour des intervalles, la borne basse incluse du premier (``None``
        si elle manque ou si elle est exclue : la version suivante n'a pas de sens) ; pour
        ``1.2.+``, ``1.2``."""
        if self.recommended is not None:
            return self.recommended.text
        if self.prefix is not None:
            base = self.prefix.rstrip(".")
            try:
                return _parse(base).text if base else None
            except InvalidVersion:
                return None
        if not self.restrictions:
            return None
        first = self.restrictions[0]
        if first.lower is None or not first.lower_inclusive:
            return None
        return first.lower.text

    def exact(self) -> str | None:
        """La version nue (recommandation, ``1.2.3!!``) ou ``[1.2.3]`` : celle-là."""
        if self.recommended is not None:
            return self.recommended.text
        if len(self.restrictions) == 1:
            only = self.restrictions[0]
            if only.lower is not None and only.lower is only.upper:
                return only.lower.text
        return None


_OPENINGS = {"[": True, "(": False, "]": False}
_CLOSINGS = {"]": True, ")": False, "[": False}
_GRADLE_LATEST = frozenset({"latest.release", "latest.integration"})


@functools.lru_cache(maxsize=2048)
def _parse_range(spec: str) -> MavenRange:
    text = spec.strip()
    if not text:
        raise InvalidConstraint("contrainte Maven vide")
    if text.lower() in _GRADLE_LATEST:
        return MavenRange(latest=True)
    try:
        if text.endswith("!!"):
            return MavenRange(recommended=_parse(text[:-2]))
        if text.endswith("+"):
            prefix = text[:-1]
            if prefix and (_FORBIDDEN.search(prefix) or not prefix[0].isdecimal()):
                raise InvalidVersion(prefix)
            return MavenRange(prefix=prefix)
        if text[0] not in _OPENINGS:
            return MavenRange(recommended=_parse(text))
        return MavenRange(restrictions=_restrictions(spec, text))
    except InvalidVersion as error:
        raise InvalidConstraint(f"contrainte Maven illisible : {spec!r}") from error


def _restrictions(spec: str, text: str) -> tuple[Restriction, ...]:
    """Les intervalles de ``text``, comme ``VersionRange.createFromVersionSpec``."""
    found: list[Restriction] = []
    rest = text
    while rest and rest[0] in _OPENINGS:
        end = _closing(rest)
        if end < 0:
            raise InvalidConstraint(f"intervalle non fermé : {spec!r}")
        restriction = _restriction(spec, rest[: end + 1])
        previous = found[-1].upper if found else None
        if previous is not None and (restriction.lower is None or restriction.lower < previous):
            raise InvalidConstraint(f"intervalles qui se chevauchent : {spec!r}")
        found.append(restriction)
        rest = rest[end + 1 :].strip()
        if rest.startswith(","):
            rest = rest[1:].strip()
    if rest:
        raise InvalidConstraint(f"contrainte Maven illisible : {spec!r}")
    return tuple(found)


def _closing(text: str) -> int:
    """L'indice du crochet ou de la parenthèse qui ferme le premier intervalle de ``text`` : après
    la virgule (Gradle peut fermer par ``[``), sinon le premier ``]`` ou ``)``."""
    comma = text.find(",")
    search_from = 1 if comma < 0 else comma + 1
    for index in range(search_from, len(text)):
        if text[index] in "])" or (comma >= 0 and text[index] == "["):
            return index
    return -1


def _restriction(spec: str, text: str) -> Restriction:
    lower_inclusive = _OPENINGS[text[0]]
    upper_inclusive = _CLOSINGS[text[-1]]
    inner = text[1:-1].strip()
    if "," not in inner:
        if not lower_inclusive or not upper_inclusive:
            raise InvalidConstraint(f"une version seule s'écrit entre [] : {spec!r}")
        version = _parse(inner)
        return Restriction(version, True, version, True, text)
    lower_text, upper_text = (part.strip() for part in inner.split(",", 1))
    lower = _parse(lower_text) if lower_text else None
    upper = _parse(upper_text) if upper_text else None
    if (
        lower is not None
        and upper is not None
        and (upper < lower or (upper == lower and not (lower_inclusive and upper_inclusive)))
    ):
        raise InvalidConstraint(f"intervalle vide : {spec!r}")
    return Restriction(lower, lower_inclusive, upper, upper_inclusive, text)


class MavenVersions(VersionScheme[MavenVersion]):
    """L'ordre de ``ComparableVersion``, les spécifications de ``VersionRange`` (et de Gradle)."""

    ecosystem = Ecosystem.MAVEN

    def parse(self, version: str) -> MavenVersion:
        return _parse(version)

    def parse_constraint(self, constraint: str) -> MavenRange:
        return _parse_range(constraint)

    def _release(self, version: MavenVersion) -> tuple[int, int, int]:
        major, minor, patch = (*version.numbers, 0, 0, 0)[:3]
        return major, minor, patch

    def _is_pre(self, version: MavenVersion) -> bool:
        return version.prerelease

    def _compatible(self, current: MavenVersion, version: MavenVersion) -> bool:
        """Une autre variante n'est pas proposée (``32.0.0-android`` pour qui a ``31.0.1-jre``) ;
        une version sans variante l'est toujours, et toute version à qui n'en a pas."""
        mine, theirs = current.flavor, version.flavor
        return not mine or not theirs or mine == theirs


MAVEN = MavenVersions()
"""Les règles de version de Maven (et de Gradle, qui en lit les dépôts)."""
