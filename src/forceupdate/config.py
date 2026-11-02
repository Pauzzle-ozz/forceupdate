"""La configuration d'un projet (E29) : ``forceupdate.toml`` à la racine de la source analysée,
sinon la table ``[tool.forceupdate]`` de son ``pyproject.toml`` (comme ruff, le premier prime).

.. code-block:: toml

    ignore = ["lodash", "@types/*", "django@>=5"]   # paquets, ou versions, ignorés
    exclude = ["legacy", "packages/*/examples"]      # dossiers jamais lus
    include-tests = true      # analyser aussi les projets des dossiers de tests et d'exemples

    [selection]               # la sélection par défaut : ce que le plan pré-coche
    level = "patch"           # patch, minor (par défaut) ou major
    security-only = false     # seulement les corrections de failles

    [selection.npm]           # pour un écosystème : pypi, npm, cargo, go, composer, rubygems,
    level = "minor"           # maven, nuget (ou python, rust, php, ruby, java, dotnet)

**Un paquet ignoré** (``lodash``, ``@types/*`` : ``*`` et ``?`` permis, sans tenir compte de la
casse) n'est pas vérifié auprès de son registre et n'a jamais de mise à jour ; ses failles
restent cherchées et dites : ignorer un paquet ne cache jamais une faille. **Une version
ignorée** (``django@>=5`` : une ou plusieurs comparaisons séparées par des virgules, avec ``<``,
``<=``, ``>``, ``>=``, ``==``, ou une version seule) n'est jamais proposée : forceupdate fait
comme si elle n'était pas publiée, sauf la version utilisée. Les comparaisons suivent les règles
de version de l'écosystème du paquet (``2`` vaut ``2.0.0`` pour npm, ``v2.0.0`` pour Go). La
syntaxe est la même pour les huit écosystèmes : Go n'a pas de plages, Maven et NuGet en ont
d'autres (``[5,)``).

**Un dossier exclu** (``legacy``, ``packages/*/examples``, relatif à la racine ; ``*`` va aussi
au-delà d'un ``/``) n'est jamais lu, ni pour les langages ni pour les projets.

Les réglages de la personne (``preferences``) ont les mêmes clés, sauf ``exclude`` ; la
configuration du projet prime sur eux, et leurs ``ignore`` s'ajoutent.

Une erreur (TOML invalide, clé inconnue, valeur d'un mauvais type) n'arrête pas l'analyse : la
valeur est écartée, et le rapport le dit (``Configuration.problems``).
"""

import dataclasses
import re
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any, NamedTuple

from forceupdate import versions
from forceupdate.models import (
    Configuration,
    Dependency,
    Ecosystem,
    Gap,
    Notice,
    Project,
    Report,
    ScanOptions,
    SelectionRule,
)
from forceupdate.parsers.base import ReadText
from forceupdate.registries import PackageInfo
from forceupdate.versions import InvalidVersion, VersionScheme

CONFIG_FILE = "forceupdate.toml"
PYPROJECT = "pyproject.toml"

PREFERENCES_ORIGIN = "réglages"
"""D'où vient une règle des réglages de la personne, dans ce que dit le rapport."""

ECOSYSTEM_KEYS: Mapping[Ecosystem, str] = {
    Ecosystem.PYPI: "pypi",
    Ecosystem.NPM: "npm",
    Ecosystem.CRATES_IO: "cargo",
    Ecosystem.GO: "go",
    Ecosystem.PACKAGIST: "composer",
    Ecosystem.RUBYGEMS: "rubygems",
    Ecosystem.MAVEN: "maven",
    Ecosystem.NUGET: "nuget",
}
"""La clé d'un écosystème sous ``[selection]``, telle qu'on l'écrit (sans point, sans
guillemets)."""

_ALIASES: Mapping[str, Ecosystem] = {
    **{key: ecosystem for ecosystem, key in ECOSYSTEM_KEYS.items()},
    **{ecosystem.value.lower(): ecosystem for ecosystem in Ecosystem},
    "python": Ecosystem.PYPI,
    "rust": Ecosystem.CRATES_IO,
    "php": Ecosystem.PACKAGIST,
    "ruby": Ecosystem.RUBYGEMS,
    "bundler": Ecosystem.RUBYGEMS,
    "java": Ecosystem.MAVEN,
    "gradle": Ecosystem.MAVEN,
    "dotnet": Ecosystem.NUGET,
}
"""Les noms qu'on accepte pour un écosystème : sa clé, son nom chez OSV (``crates.io``,
``packagist``), son langage ou son outil."""

PROJECT_KEYS = frozenset({"ignore", "exclude", "include-tests", "selection"})
"""Les clés de la configuration d'un projet."""

LEVELS = ", ".join(gap.value for gap in Gap)


class Problem(NamedTuple):
    """Une valeur écartée : où (``ignore[2]``, ``selection.npm.level``), et pourquoi."""

    field: str
    message: str

    def text(self, file: str) -> str:
        """En une phrase : ``forceupdate.toml : selection.level : « mineur » n'est pas …``."""
        return (
            f"{file} : {self.field} : {self.message}" if self.field else f"{file} : {self.message}"
        )


# ---------------------------------------------------------------------------
# Lire
# ---------------------------------------------------------------------------


def read(read_text: ReadText) -> Configuration | None:
    """La configuration du projet, lue à la racine de la source par ``read_text`` ; ``None``
    s'il n'en a pas (ni ``forceupdate.toml``, ni ``[tool.forceupdate]``)."""
    text = _read_quietly(read_text, CONFIG_FILE)
    pyproject = _tool_table(_read_quietly(read_text, PYPROJECT))
    if text is not None:
        configuration = parse(text, CONFIG_FILE)
        if pyproject is not None:
            problem = f"{PYPROJECT} : [tool.forceupdate] n'est pas lue : {CONFIG_FILE} prime."
            configuration = dataclasses.replace(
                configuration, problems=(*configuration.problems, problem)
            )
        return configuration
    if pyproject is not None:
        return from_table(pyproject, PYPROJECT, where="tool.forceupdate.")
    return None


def parse(text: str, file: str = CONFIG_FILE) -> Configuration:
    """La configuration d'un ``forceupdate.toml`` de contenu ``text``."""
    try:
        data = tomllib.loads(text.removeprefix(chr(0xFEFF)))
    except tomllib.TOMLDecodeError as err:
        return Configuration(file=file, problems=(f"{file} : TOML invalide ({err}) : non lu.",))
    return from_table(data, file)


def from_table(data: Mapping[str, Any], file: str, *, where: str = "") -> Configuration:
    """La configuration d'une table TOML déjà lue (``where`` préfixe le nom des clés dans les
    problèmes : ``tool.forceupdate.``)."""
    found, problems = read_table(data, PROJECT_KEYS)
    return Configuration(
        file=file,
        ignore=found.get("ignore", ()),
        exclude=found.get("exclude", ()),
        include_tests=found.get("include-tests", False),
        selection=found.get("selection", ()),
        problems=tuple(Problem(f"{where}{p.field}", p.message).text(file) for p in problems),
    )


def read_table(
    data: Mapping[str, Any], allowed: Iterable[str]
) -> tuple[dict[str, Any], list[Problem]]:
    """Les valeurs des clés de ``data`` qu'on connaît (parmi ``allowed``), lues et vérifiées, et
    les problèmes : une clé inconnue, une valeur d'un mauvais type (écartée). Les clés des
    réglages de la personne sont lues ici aussi (``preferences``)."""
    keys = frozenset(allowed)
    found: dict[str, Any] = {}
    problems: list[Problem] = []
    for key, value in data.items():
        if key not in keys:
            problems.append(Problem(key, "clé inconnue, ignorée."))
            continue
        reader = _READERS.get(key)
        if reader is None:
            found[key] = value
            continue
        result, errors = reader(value, key)
        problems.extend(errors)
        if result is not None:
            found[key] = result
    return found, problems


def _read_ignore(value: Any, field: str) -> tuple[tuple[str, ...] | None, list[Problem]]:
    texts, problems = _strings(value, field)
    kept = []
    for index, text in texts:
        try:
            IgnoreRule.parse(text)
        except ValueError as err:
            problems.append(Problem(f"{field}[{index}]", str(err)))
            continue
        kept.append(text.strip())
    return (tuple(kept) if texts or not problems else None), problems


def _read_exclude(value: Any, field: str) -> tuple[tuple[str, ...] | None, list[Problem]]:
    texts, problems = _strings(value, field)
    kept = []
    for index, text in texts:
        try:
            kept.append(folder_pattern(text))
        except ValueError as err:
            problems.append(Problem(f"{field}[{index}]", str(err)))
    return (tuple(kept) if texts or not problems else None), problems


def _read_bool(value: Any, field: str) -> tuple[bool | None, list[Problem]]:
    if isinstance(value, bool):
        return value, []
    return None, [Problem(field, f"{_shown(value)} n'est pas true ou false.")]


def _read_selection(
    value: Any, field: str
) -> tuple[tuple[SelectionRule, ...] | None, list[Problem]]:
    if not isinstance(value, Mapping):
        return None, [Problem(field, "une table est attendue ([selection]).")]
    problems: list[Problem] = []
    general, errors = _selection_rule(value, field, None)
    problems.extend(errors)
    rules = [general] if general is not None else []
    for key, table in value.items():
        if key in ("level", "security-only"):
            continue
        ecosystem = _ALIASES.get(str(key).lower())
        if ecosystem is None:
            message = f"« {key} » n'est pas un écosystème ({', '.join(ECOSYSTEM_KEYS.values())})."
            problems.append(Problem(f"{field}.{key}", message))
            continue
        if not isinstance(table, Mapping):
            problems.append(Problem(f"{field}.{key}", "une table est attendue."))
            continue
        rule, errors = _selection_rule(table, f"{field}.{key}", ecosystem)
        problems.extend(errors)
        unknown = [k for k in table if k not in ("level", "security-only")]
        problems.extend(Problem(f"{field}.{key}.{k}", "clé inconnue, ignorée.") for k in unknown)
        if rule is not None:
            rules = [r for r in rules if r.ecosystem is not ecosystem] + [rule]
    return tuple(rules), problems


def _selection_rule(
    table: Mapping[str, Any], field: str, ecosystem: Ecosystem | None
) -> tuple[SelectionRule | None, list[Problem]]:
    problems = []
    level = None
    if "level" in table:
        raw = table["level"]
        try:
            level = Gap(str(raw).lower()) if isinstance(raw, str) else None
        except ValueError:
            level = None
        if level is None:
            problems.append(Problem(f"{field}.level", f"{_shown(raw)} n'est pas {LEVELS}."))
    security_only = None
    if "security-only" in table:
        security_only, errors = _read_bool(table["security-only"], f"{field}.security-only")
        problems.extend(errors)
    if level is None and security_only is None:
        return None, problems
    return SelectionRule(ecosystem=ecosystem, level=level, security_only=security_only), problems


_READERS = {
    "ignore": _read_ignore,
    "exclude": _read_exclude,
    "include-tests": _read_bool,
    "selection": _read_selection,
}


def _strings(value: Any, field: str) -> tuple[list[tuple[int, str]], list[Problem]]:
    """Les chaînes d'une liste, avec leur rang ; une valeur qui n'en est pas est un problème."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return [], [Problem(field, "une liste de chaînes est attendue.")]
    found, problems = [], []
    for index, item in enumerate(value):
        if isinstance(item, str) and item.strip():
            found.append((index, item))
        else:
            problems.append(
                Problem(f"{field}[{index}]", f"{_shown(item)} : une chaîne non vide est attendue.")
            )
    return found, problems


def _shown(value: Any) -> str:
    return f"« {value} »" if isinstance(value, str) else f"« {value!r} »"


def _tool_table(text: str | None) -> Mapping[str, Any] | None:
    """La table ``[tool.forceupdate]`` d'un ``pyproject.toml`` ; ``None`` s'il n'y en a pas, ou
    si le fichier ne se lit pas (le parseur de Python le dit déjà)."""
    if text is None:
        return None
    try:
        data = tomllib.loads(text.removeprefix(chr(0xFEFF)))
    except tomllib.TOMLDecodeError:
        return None
    tool = data.get("tool")
    table = tool.get("forceupdate") if isinstance(tool, dict) else None
    return table if isinstance(table, dict) else None


def _read_quietly(read_text: ReadText, path: str) -> str | None:
    try:
        return read_text(path)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Dossiers exclus
# ---------------------------------------------------------------------------


def folder_pattern(text: str) -> str:
    """Le motif d'un dossier exclu, relatif à la racine, au format POSIX (``legacy``,
    ``packages/*/examples``) ; lève ``ValueError`` pour un chemin absolu ou qui remonte."""
    pattern = text.strip().replace("\\", "/").removeprefix("./").strip("/")
    if not pattern:
        raise ValueError("un dossier vide n'exclut rien.")
    if text.strip().startswith("/") or re.match(r"^[A-Za-z]:", pattern):
        raise ValueError(f"« {text} » : un dossier relatif à la racine du projet est attendu.")
    if ".." in pattern.split("/"):
        raise ValueError(f"« {text} » : un dossier exclu reste dans le projet (pas de ..).")
    return pattern


def is_excluded_path(path: str, patterns: Sequence[str]) -> bool:
    """Vrai si ``path`` (relatif à la racine) est dans un dossier exclu, ou l'est lui-même : un
    de ses dossiers parents correspond à un motif, sans tenir compte de la casse."""
    if not patterns:
        return False
    lowered = [pattern.lower() for pattern in patterns]
    parts = path.lower().split("/")
    for end in range(1, len(parts) + 1):
        prefix = "/".join(parts[:end])
        if any(fnmatchcase(prefix, pattern) for pattern in lowered):
            return True
    return False


# ---------------------------------------------------------------------------
# Paquets et versions ignorés
# ---------------------------------------------------------------------------

_COMPARISON = re.compile(r"^(<=|>=|==|<|>|=)?\s*([0-9A-Za-z][0-9A-Za-z.+_-]*)$")


@dataclass(frozen=True, kw_only=True)
class IgnoreRule:
    """Une règle de ``ignore`` : un paquet (``lodash``), ou des versions d'un paquet
    (``django@>=5``). Voir la docstring du module."""

    text: str
    """La règle telle qu'écrite."""
    name: str
    """Le nom du paquet, ``*`` et ``?`` permis."""
    comparisons: tuple[tuple[str, str], ...] = ()
    """Les comparaisons des versions ignorées (``(">=", "5")``), toutes à respecter ; vide pour
    le paquet entier."""
    origin: str = ""
    """D'où vient la règle : le fichier de configuration du projet, ou les réglages."""

    @classmethod
    def parse(cls, text: str, origin: str = "") -> "IgnoreRule":
        """La règle ``text`` ; lève ``ValueError`` (en français) si elle ne se lit pas. Le ``@``
        d'un paquet npm scopé (``@types/node@>=20``) n'est pas un séparateur."""
        written = text.strip()
        at = written.rfind("@")
        name, wanted = (written, None) if at <= 0 else (written[:at], written[at + 1 :])
        name = name.strip()
        if not name or any(char.isspace() for char in name):
            raise ValueError(
                f"« {text} » : un nom de paquet sans espace est attendu (lodash, django@>=5)."
            )
        comparisons: list[tuple[str, str]] = []
        if wanted is not None:
            for part in wanted.split(","):
                match = _COMPARISON.match(part.strip())
                if match is None:
                    raise ValueError(
                        f"« {text} » : « {part.strip()} » n'est pas une comparaison (>=5, <2, "
                        "==1.2.3, ou une version)."
                    )
                operator = match.group(1) or "=="
                comparisons.append(("==" if operator == "=" else operator, match.group(2)))
        return cls(text=written, name=name, comparisons=tuple(comparisons), origin=origin)

    @property
    def whole(self) -> bool:
        """Vrai si la règle ignore le paquet entier, pas seulement des versions."""
        return not self.comparisons

    @property
    def label(self) -> str:
        """La règle et d'où elle vient : ``lodash (forceupdate.toml)``."""
        return f"{self.text} ({self.origin})" if self.origin else self.text

    def matches(self, dependency: Dependency) -> bool:
        """Vrai si la règle vise le paquet de ``dependency`` (son nom, sans la casse ; selon PEP
        503 pour PyPI : ``Foo_Bar`` vaut ``foo-bar``)."""
        return fnmatchcase(
            _normalized(dependency.ecosystem, dependency.name), self._pattern(dependency.ecosystem)
        )

    def covers(self, scheme: VersionScheme, version: str) -> bool:
        """Vrai si ``version`` est ignorée par la règle (une règle de paquet les ignore toutes).
        Lève ``InvalidVersion`` si une borne ne se lit pas selon ``scheme``."""
        if self.whole:
            return True
        parsed = scheme.parse(version)
        for operator, bound in self.comparisons:
            other = _bound(scheme, bound)
            if not _OPERATORS[operator](parsed, other):
                return False
        return True

    def _pattern(self, ecosystem: Ecosystem) -> str:
        return _normalized(ecosystem, self.name)


_OPERATORS = {
    "<": lambda a, b: a < b,
    "<=": lambda a, b: not b < a,
    ">": lambda a, b: b < a,
    ">=": lambda a, b: not a < b,
    "==": lambda a, b: not a < b and not b < a,
}


def _normalized(ecosystem: Ecosystem, name: str) -> str:
    lowered = name.lower()
    return re.sub(r"[-_.]+", "-", lowered) if ecosystem is Ecosystem.PYPI else lowered


def _bound(scheme: VersionScheme, text: str) -> Any:
    """La borne ``text`` lue selon ``scheme`` : complétée par des ``.0`` (``5`` → ``5.0.0``
    pour npm), et d'un ``v`` pour Go. Lève ``InvalidVersion``."""
    prefix = "v" if scheme.ecosystem is Ecosystem.GO and not text.startswith("v") else ""
    candidates = [f"{prefix}{text}", f"{prefix}{text}.0", f"{prefix}{text}.0.0"]
    for candidate in candidates:
        try:
            return scheme.parse(candidate)
        except InvalidVersion:
            continue
    raise InvalidVersion(f"version illisible : {text!r}")


def ignore_rules(report: Report, options: ScanOptions) -> list[IgnoreRule]:
    """Les règles ``ignore`` de l'analyse : celles de la configuration du projet, puis celles
    des réglages de la personne (``options.ignore``). Une règle illisible est sautée (la
    configuration le dit déjà ; les réglages sont vérifiés à l'enregistrement)."""
    written = []
    if report.config is not None:
        written += [(text, report.config.file) for text in report.config.ignore]
    written += [(text, PREFERENCES_ORIGIN) for text in options.ignore]
    rules = []
    for text, origin in written:
        try:
            rules.append(IgnoreRule.parse(text, origin))
        except ValueError:
            continue
    return rules


def mark_ignored(project: Project, rules: Sequence[IgnoreRule]) -> None:
    """Marque les dépendances de ``project`` que vise une règle de paquet (``Dependency.
    ignored``), et le dit dans une remarque par fichier, un paquet une fois (sur le premier
    fichier qui le déclare : le manifeste d'une directe, le lockfile d'une indirecte) : elles ne
    seront ni vérifiées auprès de leur registre, ni mises à jour ; leurs failles restent
    cherchées."""
    whole = [rule for rule in rules if rule.whole]
    if not whole:
        return
    by_file: dict[str, dict[str, None]] = {}
    said: set[tuple[Ecosystem, str]] = set()
    for index, dependency in enumerate(project.dependencies):
        rule = next((rule for rule in whole if rule.matches(dependency)), None)
        if rule is None or dependency.ignored is not None:
            continue
        project.dependencies[index] = dataclasses.replace(dependency, ignored=rule.label)
        if (dependency.ecosystem, dependency.name) not in said:
            said.add((dependency.ecosystem, dependency.name))
            by_file.setdefault(dependency.file, {})[f"{dependency.name} ({rule.origin})"] = None
    for file, names in by_file.items():
        label = "Paquet ignoré" if len(names) == 1 else "Paquets ignorés"
        message = (
            f"{label} : {', '.join(names)}. Ni versions plus récentes ni mises à jour ; les "
            "failles restent cherchées."
        )
        project.notices.append(Notice(file=file, message=message))


@dataclass(frozen=True, kw_only=True)
class Filtered:
    """Ce que les règles de versions retirent des versions publiées d'un paquet."""

    info: PackageInfo
    """Ce que dit le registre, sans les versions ignorées."""
    removed: Mapping[str, int]
    """Le nombre de versions retirées par chaque règle (``IgnoreRule.label``)."""
    unreadable: tuple[str, ...] = ()
    """Les règles dont une borne ne se lit pas selon l'écosystème du paquet."""


def without_ignored(
    info: PackageInfo, dependency: Dependency, rules: Sequence[IgnoreRule], used: Iterable[str]
) -> Filtered:
    """``info`` sans les versions qu'ignorent les règles de versions qui visent ``dependency``
    (``rules``), sauf les versions utilisées (``used``) ; sa dernière stable recalculée si elle
    est ignorée, les étiquettes npm qui en désignent une retirées."""
    wanted = [rule for rule in rules if not rule.whole and rule.matches(dependency)]
    if not wanted:
        return Filtered(info=info, removed={})
    scheme = versions.for_ecosystem(info.ecosystem)
    readable = [rule for rule in wanted if _readable_bounds(scheme, rule)]
    unreadable = [rule.label for rule in wanted if rule not in readable]
    keep = set(used)
    removed: dict[str, int] = {}
    kept = []
    for published in info.versions:
        hit = None
        if published.version not in keep:
            hit = next(
                (rule for rule in readable if _covered(scheme, rule, published.version)), None
            )
        if hit is None:
            kept.append(published)
        else:
            removed[hit.label] = removed.get(hit.label, 0) + 1
    if not removed:
        return Filtered(info=info, removed={}, unreadable=tuple(unreadable))
    gone = {v.version for v in info.versions} - {v.version for v in kept}
    latest = info.latest
    if latest in gone:
        fresh = [v.version for v in kept if not v.yanked and v.deprecated is None]
        latest = scheme.latest(fresh) or scheme.latest(v.version for v in kept if not v.yanked)
    tags = {tag: version for tag, version in info.tags.items() if version not in gone}
    if "latest" in info.tags and latest is not None:
        tags["latest"] = latest
    filtered = dataclasses.replace(info, versions=tuple(kept), latest=latest, tags=tags)
    return Filtered(info=filtered, removed=removed, unreadable=tuple(unreadable))


def _covered(scheme: VersionScheme, rule: IgnoreRule, version: str) -> bool:
    """``rule.covers``, faux pour une version publiée illisible (gardée, comme ailleurs)."""
    try:
        return rule.covers(scheme, version)
    except InvalidVersion:
        return False


def _readable_bounds(scheme: VersionScheme, rule: IgnoreRule) -> bool:
    try:
        for _, bound in rule.comparisons:
            _bound(scheme, bound)
    except InvalidVersion:
        return False
    return True
