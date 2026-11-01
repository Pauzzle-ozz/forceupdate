"""Réécrire une contrainte pour une nouvelle version, en gardant son style.

``^4.17.0`` devient ``^4.21.2``, pas ``4.21.2`` (brief, « Garder le style de contrainte ») :
seuls les numéros de version changent. Les opérateurs, les espaces, l'ordre, les préfixes
(``v``, ``=``) et le reste du texte sont gardés.

La règle : la nouvelle contrainte accepte la version visée, et sa borne basse monte jusqu'à
elle (``>=2.25,<3`` vers 3.1 : ``>=3.1,<4``). Par style :

- **version exacte** (``==1.2.3``, ``1.2.3`` npm, version nue Poetry, ``=1.2.3`` Cargo) et
  **borne basse** (``>=``, ``>``) : la version visée ; ``>`` devient ``>=``, sinon elle
  s'exclurait ;
- ``^`` et ``~`` (npm, Poetry, Cargo) : la version visée derrière le même opérateur. Pour Cargo,
  une version sans opérateur est un ``^`` (``1.2`` veut dire ``^1.2``) : elle reste sans
  opérateur ;
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
- les jokers (``1.2.*``, ``1.x``, la version partielle ``1.2`` de npm, ``=1.2`` de Cargo, qui
  veut dire ``1.2.*``) aussi : ``2.3.*`` ;
- ``~1`` va jusqu'à 2, ``~1.3.4`` seulement jusqu'à 1.4 ; ``^0`` jusqu'à 1, ``^0.3.1`` seulement
  jusqu'à 0.4 : ``~`` à un seul nombre, et ``^`` dont le premier nombre non nul de la version
  visée tomberait hors de la précision écrite, gardent leur précision.

**Plancher** (``floor``) : pour une faille, la borne basse doit atteindre la version visée,
sinon la nouvelle contrainte accepterait encore des versions concernées. Quand le style ne le
permet pas (``~=1.9`` pour 1.9.2, ``2.3.*``), une borne ``>=`` est ajoutée :
``~=1.9,>=1.9.2``, ``2.x >=2.3.1``, ``=1.3, >=1.3.1`` (Cargo).

**Go** : une version de ``go.mod`` n'est pas une plage (``versions.go``) : elle devient la version
visée, écrite avec son ``v`` (``v1.3.0`` vers 1.6.0 : ``v1.6.0``).

**Composer** (``versions.composer``) : une version nue est exacte (``1.2`` vers 1.5.3 : ``1.5.3``) ;
``~`` est la « prochaine version significative » : ``~1.2`` (jusqu'à 2.0) et ``~1`` gardent leur
précision (``~1.2`` vers 1.5.3 : ``~1.5``, et ``~1.5, >=1.5.3`` pour un plancher), ``~1.2.3``
(jusqu'à 1.3) prend la version visée ; ``^``, les jokers, ``||`` et ``|``, l'intervalle
``1.0 - 2.0`` et les bornes comme npm ; un drapeau de stabilité (``^1.0@beta``) est gardé. La
version visée est écrite sans le ``v`` que lui donne Packagist (``v5.4.20`` pour Symfony), sauf si
la contrainte en avait un.

**RubyGems** (``versions.rubygems``) : une version nue ou ``=`` est exacte (``= 1.2`` vers 1.5.3 :
``= 1.5.3``) ; ``~>`` garde toujours sa précision, comme ``~=`` : le nombre de nombres y fixe la
borne haute (``~> 2.2.3`` va jusqu'à 2.3, ``~> 2.2.8.1`` seulement jusqu'à 2.2.9). ``~> 2.2.3``
vers 2.2.8.1 donne ``~> 2.2.8``, et ``~> 2.2.8, >= 2.2.8.1`` pour un plancher : la forme
qu'écrivent les avis de sécurité de Rails. Les contraintes d'une gem sont jointes par ``, ``
(``update.writers.ruby`` remet les guillemets de chacune).

**Maven** (``versions.maven``, Gradle compris) : une version nue est la version utilisée, elle
devient la version visée telle que la publie le dépôt (``31.0.1-jre`` vers ``32.1.3-jre``) ;
``1.2.3!!`` (Gradle) garde ses ``!!`` ; ``[1.2.3]`` devient ``[V]``. Un
intervalle (``[1.0,2.0)``) : celui qui accepte la version visée, sinon le dernier, seul ; sa borne
basse devient la version visée, incluse (``[1.5.3,2.0)``), une borne haute qui l'exclut se déplace
au même niveau (``[2.1.0,3.0)``), une borne basse absente le reste, sauf pour un plancher.
``1.+`` (Gradle) garde sa précision (``2.+``), sans plancher possible.

**NuGet** (``versions.nuget``) : NuGet prend la plus basse version qui convient, donc la borne
basse doit devenir la version visée. Une version nue (un minimum) devient la version visée, à la
même précision si elle s'y écrit (``1.0`` vers 2.0.0 : ``2.0``) ; ``[1.2.3]`` devient ``[V]`` ;
un intervalle prend la version visée pour borne basse, incluse (``(1.0,2.0)`` vers 1.5.3 :
``[1.5.3,2.0)`` ; ``(,2.0]`` : ``[1.5.3,2.0]``), et sa borne haute se déplace au même niveau si
elle l'exclut. Une version flottante garde sa précision (``1.*`` vers 2.3.1 : ``2.*`` ;
``1.2.*`` : ``2.3.*`` ; ``1.0.0-beta.*`` : ``2.3.1-beta.*``) ; NuGet y prend la plus haute de ce
qu'elle désigne, le plancher n'y a pas de sens.

Le résultat est relu : il doit accepter la version visée (et respecter le plancher). Sinon, ou
pour un style qu'on ne sait pas réécrire (intervalle npm ``1.2.3 - 2.3.4`` dépassé, contrainte
sans version comme ``*`` ou une étiquette), ``rewrite`` rend ``None`` : à réécrire à la main.
"""

import re
from dataclasses import dataclass

from forceupdate import versions
from forceupdate.models import Ecosystem
from forceupdate.versions import InvalidConstraint, InvalidVersion, VersionScheme
from forceupdate.versions.go import canonical
from forceupdate.versions.maven import MAVEN
from forceupdate.versions.nuget import NUGET

_OPERATORS = {
    Ecosystem.NPM: r"~>|<=|>=|[<>=~^]",
    Ecosystem.CRATES_IO: r"<=|>=|[<>=~^]",
    Ecosystem.PACKAGIST: r"<>|!=|==|<=|>=|[<>=~^]",
    Ecosystem.RUBYGEMS: r"~>|!=|<=|>=|[<>=]",
}
_PYPI_OPERATORS = r"===|==|!=|<>|<=|>=|~=|[<>=~^]"
"""Les opérateurs de chaque écosystème ; ceux de PyPI (Poetry et Pipenv compris) sinon."""
_FLOOR_SEPARATORS = {
    Ecosystem.NPM: " ",
    Ecosystem.CRATES_IO: ", ",
    Ecosystem.PACKAGIST: ", ",
    Ecosystem.RUBYGEMS: ", ",
}
"""Ce qui précède la borne ``>=`` ajoutée pour un plancher ; ``,`` sinon (PyPI)."""
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
    if ecosystem is Ecosystem.GO:
        try:
            scheme.parse_constraint(constraint)
            scheme.parse(target)
        except (InvalidConstraint, InvalidVersion):
            return None
        return canonical(target)
    if ecosystem is Ecosystem.MAVEN:
        try:
            new = _rewrite_maven(constraint.strip(), target, floor)
            if new is None or not scheme.satisfies(new, target):
                return None
            if floor and not _reaches(scheme, new, target):
                return None
        except (InvalidConstraint, InvalidVersion):
            return None
        return new
    if ecosystem is Ecosystem.NUGET:
        try:
            new, floating = _rewrite_nuget(constraint, target)
            if new is None or not scheme.satisfies(new, target):
                return None
            if floor and not floating and not _reaches(scheme, new, target):
                return None
        except (InvalidConstraint, InvalidVersion):
            return None
        return new
    if ecosystem is Ecosystem.PACKAGIST:
        target = _without_v(target)
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


def _rewrite_maven(constraint: str, target: str, floor: bool) -> str | None:
    """Une spécification Maven ou Gradle réécrite pour ``target`` (voir la docstring du module)."""
    parsed = MAVEN.parse_constraint(constraint)
    if parsed.recommended is not None:
        return f"{target}!!" if constraint.endswith("!!") else target
    if parsed.latest:
        return None
    if parsed.prefix is not None:
        split = _split_target(target)
        prefix = parsed.prefix
        count = len([part for part in prefix.split(".") if part])
        if (
            split is None
            or not count
            or not all(p.isdigit() for p in prefix.rstrip(".").split("."))
        ):
            return None
        return split.written(count) + ("." if prefix.endswith(".") else "") + "+"
    restrictions = parsed.restrictions
    wanted = MAVEN.parse(target)
    chosen = next(
        (r.text for r in restrictions if r.contains(wanted)),
        restrictions[-1].text if restrictions else None,
    )
    if not chosen:
        return None
    inner = chosen[1:-1]
    if "," not in inner:
        return f"[{target}]"
    lower, upper = inner.split(",", 1)
    closing = chosen[-1]
    if upper.strip():
        bound = MAVEN.parse(upper.strip())
        if bound < wanted or (bound == wanted and closing != "]"):
            split = _split_target(target)
            shifted = None if split is None else _shift_upper(upper.strip(), split)
            if shifted is None:
                return None
            upper = upper.replace(upper.strip(), shifted)
    if lower.strip() or floor:
        lead = lower[: len(lower) - len(lower.lstrip())]
        return f"[{lead}{target}{lower[len(lower.rstrip()) :]},{upper}{closing}"
    return f"{chosen[0]}{lower},{upper}{closing}"


_NUGET_FLOAT = re.compile(
    r"(?P<lead>\s*)(?P<numbers>\d+(?:\.\d+)*)(?P<rest>(?:\.\*)?(?:-[^*\s]*\*)?)(?P<trail>\s*)"
)
"""Une version flottante NuGet, en borne basse : ses nombres, puis ce qui flotte (``.*``,
``-beta.*``)."""


def _rewrite_nuget(constraint: str, target: str) -> tuple[str | None, bool]:
    """Une contrainte NuGet réécrite pour ``target`` (voir la docstring du module), et si elle
    flotte."""
    parsed = NUGET.parse_constraint(constraint)
    split = _split_target(target)
    text = constraint.strip()
    if split is None:
        return None, False
    if text[0] not in "([":
        if parsed.floating:
            return _nuget_float(text, split), True
        count = len(text.split("-", 1)[0].split("+", 1)[0].split("."))
        return (split.written(count) if split.fits(count) else target), False
    inner = text[1:-1]
    if "," not in inner:
        return f"[{target}]", False
    lower, upper = inner.split(",", 1)
    closing = text[-1]
    if upper.strip():
        bound = NUGET.parse(upper.strip())
        wanted = NUGET.parse(target)
        if bound < wanted or (bound == wanted and closing != "]"):
            shifted = _shift_upper(upper.strip(), split)
            if shifted is None:
                return None, False
            upper = upper.replace(upper.strip(), shifted)
    if parsed.floating:
        floated = _nuget_float(lower, split)
        return (None if floated is None else f"{text[0]}{floated},{upper}{closing}"), True
    lead = lower[: len(lower) - len(lower.lstrip())]
    trail = lower[len(lower.rstrip()) :]
    return f"[{lead}{target}{trail},{upper}{closing}", False


def _nuget_float(spec: str, target: _Target) -> str | None:
    """Une version flottante (``1.2.*``, ``1.0.0-beta.*``) pour ``target``, à la même précision ;
    ``None`` pour ``*`` ou ``*-*``, qui désignent déjà toutes les versions."""
    match = _NUGET_FLOAT.fullmatch(spec)
    if match is None:
        return None
    count = len(match["numbers"].split("."))
    return f"{match['lead']}{target.written(count)}{match['rest']}{match['trail']}"


def _without_v(version: str) -> str:
    """``v5.4.20`` (une étiquette Symfony sur Packagist) → ``5.4.20`` : la version visée s'écrit
    sans ``v`` ; une contrainte qui en avait un le garde (``_NUMBERS``, ``prefix``)."""
    version = version.strip()
    return version[1:] if version[:1] in "vV" and version[1:2].isdigit() else version


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
    ecosystem = scheme.ecosystem
    hyphen = _HYPHEN.fullmatch(text) if ecosystem in (Ecosystem.NPM, Ecosystem.PACKAGIST) else None
    if hyphen is not None:
        return _rewrite_hyphen(scheme, hyphen, target)
    comparators = [(c, _kind(c, ecosystem)) for c in _comparators(text, ecosystem)]
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
        written = _written(comparator, kind, target, ecosystem)
        if written is None:
            return None
        replacements.append((comparator.version_span, written))
        if comparator.operator == ">":
            replacements.append((comparator.operator_span, ">="))
    new = _apply(text, replacements)
    if floor and not _reaches(scheme, new, target.text):
        operator = ">= " if ecosystem is Ecosystem.RUBYGEMS else ">="
        new += f"{_FLOOR_SEPARATORS.get(ecosystem, ',')}{operator}{target.text}"
    return new


def _comparators(text: str, ecosystem: Ecosystem) -> list[_Comparator]:
    operators = _OPERATORS.get(ecosystem, _PYPI_OPERATORS)
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


def _kind(comparator: _Comparator, ecosystem: Ecosystem) -> str:
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
    if ecosystem is Ecosystem.CRATES_IO and not operator:
        return "caret"  # « 1.2 » veut dire « ^1.2 » pour Cargo
    if ecosystem in (Ecosystem.NPM, Ecosystem.CRATES_IO) and count < 3:
        return "wildcard"  # « 1.2 » (npm) et « =1.2 » (Cargo) veulent dire « 1.2.x »
    return "exact"


def _count(numbers: str) -> tuple[int, bool]:
    """Le nombre de nombres écrits avant un éventuel joker, et s'il y a un joker."""
    count = 0
    for part in numbers.split("."):
        if not part.isdigit():
            return count, True
        count += 1
    return count, False


def _written(
    comparator: _Comparator, kind: str, target: _Target, ecosystem: Ecosystem
) -> str | None:
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
    if kind == "tilde" and ecosystem is Ecosystem.RUBYGEMS:
        return prefix + target.written(count)  # ~> : la précision fixe la borne haute
    if target.fits(count):
        return prefix + target.written(count)
    if kind == "tilde" and count < (3 if ecosystem is Ecosystem.PACKAGIST else 2):
        return prefix + target.written(count)  # ~1 (et ~1.2 de Composer) : jusqu'à 2.0
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
