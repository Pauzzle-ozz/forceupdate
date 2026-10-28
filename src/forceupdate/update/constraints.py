"""Réécrire une contrainte pour une nouvelle version, en gardant son style.

``^4.17.0`` devient ``^4.21.2``, pas ``4.21.2`` (brief, « Garder le style de contrainte ») :
seuls les numéros de version changent. Les opérateurs, les espaces, l'ordre, les préfixes
(``v``, ``=``) et le reste du texte sont gardés.

La règle : la nouvelle contrainte accepte la version visée, et sa borne basse monte jusqu'à
elle (``>=2.25,<3`` vers 3.1 : ``>=3.1,<4``). Par style :

- **version exacte** (``==1.2.3``, ``1.2.3`` npm, version nue Poetry) et **borne basse**
  (``>=``, ``>``) : la version visée ; ``>`` devient ``>=``, sinon elle s'exclurait ;
- ``^`` et ``~`` (npm, Poetry) : la version visée derrière le même opérateur ;
- **borne haute** (``<``, ``<=``) : déplacée seulement si elle exclut la version visée, au même
  niveau que celui qu'elle fixait (``<3`` vers 3.1 : ``<4`` ; ``<1.5`` vers 1.7.2 : ``<1.8``) ;
- ``!=`` est gardé tel quel ;
- **union** (``^1 || ^2``) : remplacée par le membre qui accepte la version visée, ou par le
  dernier, réécrit ;
- **dépendance pair** (``widen``) : la plage dit avec quelles versions le paquet fonctionne ;
  la remplacer retirerait les anciennes à ses utilisateurs. Un membre est ajouté à la fin
  (``^18.0.0`` vers 19.1.0 : ``^18.0.0 || ^19.1.0`` ; ``^1 || ^2`` : ``^1 || ^2 || ^3.1.0``).

**Précision.** Le nombre de nombres écrits est gardé quand la version visée s'y écrit sans
rien perdre (``^1`` vers 2.0.0 : ``^2`` ; ``==1.2`` vers 1.3.0 : ``==1.3``). Sinon la version
visée est écrite en entier, sauf là où le nombre de nombres change le sens de la contrainte :

- ``~=1.4`` veut dire ``>=1.4, ==1.*``, mais ``~=1.4.2`` veut dire ``==1.4.*`` : ``~=`` garde
  toujours sa précision (``~=1.4`` vers 1.9.2 : ``~=1.9``) ;
- les jokers (``1.2.*``, ``1.x``, la version partielle ``1.2`` de npm) aussi : ``2.3.*`` ;
- ``~1`` va jusqu'à 2, ``~1.3.4`` seulement jusqu'à 1.4 ; ``^0`` jusqu'à 1, ``^0.3.1`` seulement
  jusqu'à 0.4 : ``~`` à un seul nombre, et ``^`` dont le premier nombre non nul de la version
  visée tomberait hors de la précision écrite, gardent leur précision.

**Plancher** (``floor``) : pour une faille, la borne basse doit atteindre la version visée,
sinon la nouvelle contrainte accepterait encore des versions concernées. Quand le style ne le
permet pas (``~=1.9`` pour 1.9.2, ``2.3.*``), une borne ``>=`` est ajoutée :
``~=1.9,>=1.9.2``, ``2.x >=2.3.1``.

Le résultat est relu : il doit accepter la version visée (et respecter le plancher). Sinon, ou
pour un style qu'on ne sait pas réécrire (intervalle npm ``1.2.3 - 2.3.4`` dépassé, contrainte
sans version comme ``*`` ou une étiquette), ``rewrite`` rend ``None`` : à réécrire à la main.
"""

import re
from dataclasses import dataclass

from forceupdate import versions
from forceupdate.models import Ecosystem
from forceupdate.versions import InvalidConstraint, InvalidVersion, VersionScheme

_NPM_OPERATORS = r"~>|<=|>=|[<>=~^]"
_PYPI_OPERATORS = r"===|==|!=|<>|<=|>=|~=|[<>=~^]"
_VERSION_TEXT = r"[vV]?(?:\d|[xX*])[0-9A-Za-z.!+*_-]*"
"""Une version telle qu'écrite dans une contrainte : complète, partielle, avec joker,
pré-version ou version locale. Le découpage fin est fait par ``_NUMBERS``."""

_NUMBERS = re.compile(
    r"(?P<prefix>[vV=]*)(?P<epoch>\d+!)?(?P<numbers>(?:\d+|[xX*])(?:\.(?:\d+|[xX*]))*)"
    r"(?P<rest>.*)",
    re.ASCII,
)
_PLAIN = re.compile(r"(?P<epoch>\d+!)?(?P<numbers>\d+(?:\.\d+)*)(?P<rest>.*)", re.ASCII)
_HYPHEN = re.compile(r"(?P<first>\S+)(?P<middle>\s+-\s+)(?P<last>\S+)")
_UNION = re.compile(r"\s*\|\|?\s*")


@dataclass(frozen=True)
class _Comparator:
    """Un comparateur tel qu'écrit dans un membre de contrainte."""

    operator: str
    operator_span: tuple[int, int]
    version: str
    version_span: tuple[int, int]


@dataclass(frozen=True)
class _Target:
    """La version visée, découpée : ses nombres, et ce qui les suit (pré-version, ``.post0``…)."""

    text: str
    epoch: str
    numbers: tuple[int, ...]
    rest: str

    def written(self, count: int) -> str:
        """Ses ``count`` premiers nombres (complétés par des zéros), sans ce qui les suit."""
        numbers = (*self.numbers, *([0] * count))[:count]
        return self.epoch + ".".join(str(n) for n in numbers)

    def fits(self, count: int) -> bool:
        """Vrai si ``count`` nombres l'écrivent sans rien perdre : ``2.0.0`` en deux (``2.0``),
        pas ``2.0.1`` ni ``2.0.0rc1``."""
        return not self.rest and all(n == 0 for n in self.numbers[count:])


def rewrite(
    ecosystem: Ecosystem, constraint: str, target: str, *, floor: bool = False, widen: bool = False
) -> str | None:
    """La contrainte ``constraint`` réécrite pour ``target``, dans le même style (voir la
    docstring du module) ; ``None`` si on ne sait pas la réécrire.

    ``floor`` : la borne basse doit atteindre ``target`` (une faille). ``widen`` : la plage
    s'élargit d'un membre au lieu d'être remplacée (une dépendance pair), et reste telle quelle
    si elle accepte déjà ``target``.

    La borne basse monte toujours jusqu'à ``target`` (ou ce que le style en garde) : quand la
    contrainte l'accepte déjà et qu'un lockfile la fige, c'est au planificateur de ne pas
    réécrire la contrainte (le lockfile seul suffit).
    """
    scheme = versions.for_ecosystem(ecosystem)
    parsed_target = _split_target(target)
    if parsed_target is None:
        return None
    members = _members(constraint)
    try:
        if len(members) > 1 or widen:
            new = _rewrite_union(scheme, constraint, members, parsed_target, floor, widen)
        else:
            new = _rewrite_member(scheme, constraint.strip(), parsed_target, floor)
        if new is None or not scheme.satisfies(new, target):
            return None
        if floor and not _reaches(scheme, new, target):
            return None
    except (InvalidConstraint, InvalidVersion):
        return None
    return new


def _split_target(target: str) -> _Target | None:
    match = _PLAIN.fullmatch(target.strip().lstrip("vV="))
    if match is None:
        return None
    numbers = tuple(int(n) for n in match.group("numbers").split("."))
    return _Target(target, match.group("epoch") or "", numbers, match.group("rest"))


def _members(constraint: str) -> list[str]:
    """Les membres d'une union (``||`` de npm et Poetry, ``|`` de Poetry)."""
    return [part for part in _UNION.split(constraint.strip())]


def _rewrite_union(
    scheme: VersionScheme,
    constraint: str,
    members: list[str],
    target: _Target,
    floor: bool,
    widen: bool,
) -> str | None:
    containing = [m for m in members if m and scheme.satisfies(m, target.text)]
    if widen:
        if containing:
            return constraint
        added = _rewrite_member(scheme, members[-1], target, floor=False)
        if added is None:
            return None
        separator = _UNION.search(constraint)
        return constraint.rstrip() + (separator.group() if separator else " || ") + added
    member = containing[0] if containing else members[-1]
    return _rewrite_member(scheme, member, target, floor)


def _rewrite_member(scheme: VersionScheme, text: str, target: _Target, floor: bool) -> str | None:
    npm = scheme.ecosystem is Ecosystem.NPM
    hyphen = _HYPHEN.fullmatch(text) if npm else None
    if hyphen is not None:
        return _rewrite_hyphen(scheme, hyphen, target)
    comparators = [(c, _kind(c, npm=npm)) for c in _comparators(text, npm=npm)]
    if all(kind == "any" for _, kind in comparators):
        return None  # « * », « x », une étiquette : pas de version à réécrire
    replacements: list[tuple[tuple[int, int], str]] = []
    for comparator, kind in comparators:
        if kind == "any":
            continue
        if kind == "upper":
            if not scheme.satisfies(comparator.operator + comparator.version, target.text):
                shifted = _shift_upper(comparator.version, target)
                if shifted is None:
                    return None
                replacements.append((comparator.version_span, shifted))
            continue
        if kind == "exclude":
            continue
        written = _written(comparator, kind, target)
        if written is None:
            return None
        replacements.append((comparator.version_span, written))
        if comparator.operator == ">":
            replacements.append((comparator.operator_span, ">="))
    new = _apply(text, replacements)
    if floor and not _reaches(scheme, new, target.text):
        new += f" >={target.text}" if npm else f",>={target.text}"
    return new


def _comparators(text: str, *, npm: bool) -> list[_Comparator]:
    operators = _NPM_OPERATORS if npm else _PYPI_OPERATORS
    pattern = re.compile(rf"(?P<op>{operators})?\s*(?P<version>{_VERSION_TEXT})", re.ASCII)
    found = []
    for match in pattern.finditer(text):
        operator = match.group("op") or ""
        found.append(
            _Comparator(
                operator=operator,
                operator_span=match.span("op") if operator else (match.start(), match.start()),
                version=match.group("version"),
                version_span=match.span("version"),
            )
        )
    return found


def _kind(comparator: _Comparator, *, npm: bool) -> str:
    """Le rôle d'un comparateur : ``exact``, ``lower``, ``upper``, ``caret``, ``tilde``,
    ``compatible`` (``~=``), ``wildcard``, ``exclude`` (``!=``) ou ``any`` (``*``)."""
    operator = comparator.operator
    numbers = _NUMBERS.fullmatch(comparator.version)
    count, wildcard = _count(numbers.group("numbers")) if numbers else (0, True)
    if count == 0:
        return "any"
    if operator in ("<", "<="):
        return "upper"
    if operator in (">", ">="):
        return "lower"
    if operator == "^":
        return "caret"
    if operator in ("~", "~>"):
        return "tilde"
    if operator == "~=":
        return "compatible"
    if operator in ("!=", "<>"):
        return "exclude"
    if wildcard:
        return "wildcard"
    if npm and count < 3:
        return "wildcard"  # « 1.2 » veut dire « 1.2.x » pour npm
    return "exact"


def _count(numbers: str) -> tuple[int, bool]:
    """Le nombre de nombres écrits avant un éventuel joker, et s'il y a un joker."""
    count = 0
    for part in numbers.split("."):
        if not part.isdigit():
            return count, True
        count += 1
    return count, False


def _written(comparator: _Comparator, kind: str, target: _Target) -> str | None:
    """Le nouveau texte de la version d'un comparateur qui porte la borne basse."""
    numbers = _NUMBERS.fullmatch(comparator.version)
    if numbers is None:
        return None
    prefix = numbers.group("prefix")
    count, _ = _count(numbers.group("numbers"))
    if kind == "wildcard":
        return prefix + target.written(count) + _joker(numbers.group("numbers"), count)
    if kind == "compatible":
        return prefix + target.written(max(count, 2))
    if target.fits(count):
        return prefix + target.written(count)
    if kind == "tilde" and count < 2:
        return prefix + target.written(count)
    if kind == "caret" and not any(n != 0 for n in target.numbers[:count]):
        return prefix + target.written(count)
    return prefix + target.text


def _joker(numbers: str, count: int) -> str:
    """Ce qui suit les ``count`` premiers nombres : le joker (``.x``, ``.*``), ou rien."""
    return numbers[len(".".join(numbers.split(".")[:count])) :]


def _shift_upper(upper: str, target: _Target) -> str | None:
    """Une borne haute déplacée au-dessus de ``target``, au même niveau : le dernier nombre non
    nul de la borne dit ce qu'elle fixait (``<3`` une majeure, ``<1.5`` une mineure)."""
    match = _NUMBERS.fullmatch(upper)
    if match is None:
        return None
    count, wildcard = _count(match.group("numbers"))
    if wildcard or count == 0:
        return None
    written = [int(n) for n in match.group("numbers").split(".")]
    level = max((i for i, n in enumerate(written) if n != 0), default=0)
    numbers = [*target.numbers, *([0] * count)][: level + 1]
    numbers[level] += 1
    numbers += [0] * (count - level - 1)
    return match.group("prefix") + ".".join(str(n) for n in numbers) + match.group("rest")


def _rewrite_hyphen(scheme: VersionScheme, hyphen: re.Match[str], target: _Target) -> str | None:
    """``1.2.3 - 2.3.4`` (npm) : le début devient la version visée ; une fin partielle
    (``- 2``, ``- 2.3``) suit la version visée à la même précision. Une fin complète dépassée
    n'a pas de règle évidente : à réécrire à la main."""
    last = hyphen.group("last")
    if not scheme.satisfies(f"0.0.0 - {last}", target.text):
        match = _NUMBERS.fullmatch(last)
        if match is None:
            return None
        count, wildcard = _count(match.group("numbers"))
        if count >= 3 and not wildcard:
            return None
        last = match.group("prefix") + target.written(count) + _joker(match.group("numbers"), count)
    return f"{target.text}{hyphen.group('middle')}{last}"


def _apply(text: str, replacements: list[tuple[tuple[int, int], str]]) -> str:
    for (start, end), new in sorted(replacements, reverse=True):
        text = text[:start] + new + text[end:]
    return text


def _reaches(scheme: VersionScheme, constraint: str, target: str) -> bool:
    """Vrai si la borne basse de ``constraint`` atteint ``target``."""
    lower = scheme.lower_bound(constraint)
    return lower is not None and scheme.compare(lower, target) >= 0
