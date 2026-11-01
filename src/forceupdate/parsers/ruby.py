"""Les parseurs Ruby : ``Gemfile``, ``.gemspec``, ``Gemfile.lock``, et le lien entre eux.

**Le ``Gemfile`` est du Ruby**, que Bundler évalue : forceupdate ne l'exécute pas, il le lit par
motifs (``ruby_spans`` : des jetons, avec leur position). ``gems.rb`` et ``gems.locked``, les
autres noms que connaît Bundler, sont lus de même. Ce qui est lu :

- ``gem "nom"``, avec ses contraintes : ``gem "rack", "~> 2.2", ">= 2.2.3"`` (une par chaîne,
  toutes à respecter) ou une liste (``["~> 2.2", ">= 2.2.3"]``), entre parenthèses ou non. La
  contrainte est écrite comme dans ``Gemfile.lock`` : ``~> 2.2, >= 2.2.3`` ; son emplacement va
  du début de la première chaîne à la fin de la dernière, quand elles sont sur une même ligne
  (``update.writers.ruby`` sait y remettre les guillemets) ;
- les groupes : ``group :development, :test do … end`` et ``group:`` (ou ``groups:``) en option ;
  une gem des seuls groupes ``development`` et ``test`` est ``dev``, d'un groupe
  ``optional: true`` ``optional``, sinon ``runtime`` ;
- d'où vient la gem : ``git:``, ``github:``, ``gist:``, ``bitbucket:``, une source ``git_source``
  du ``Gemfile``, ou un bloc ``git``/``github`` : « dépendance git » ; ``path:`` ou un bloc
  ``path`` : « chemin local » ; ``source:`` ou un bloc ``source "…" do`` vers un autre serveur
  que rubygems.org : non vérifiable aussi. La source globale (``source "https://…"`` sans bloc)
  n'est pas distinguée : un miroir ou un serveur privé est cherché sur rubygems.org, où une gem
  privée est introuvable ;
- ``platforms`` (bloc ou option) : une gem que le ``Gemfile.lock`` n'installe sur aucune de ses
  plateformes (``platforms: :jruby`` pour un projet Linux) est non vérifiable ;
- ``gemspec`` : les dépendances du ``.gemspec`` du dossier (``add_dependency`` et
  ``add_runtime_dependency`` : ``runtime`` ; ``add_development_dependency`` : ``dev``), lues par
  ``parse_gemspec`` avec leur emplacement ; ``name:`` choisit le ``.gemspec``. Un dossier qui a
  un ``.gemspec`` sans ``Gemfile`` est une gem : ses dépendances sont lues, sans lockfile ;
- ce qui ne se lit pas par motifs donne une remarque, pas une erreur : ``eval_gemfile`` (le
  fichier chargé n'est pas lu), une gem déclarée sous condition (``if``, ``unless``, ``case`` :
  lue comme toujours déclarée), une contrainte ou un nom qui n'est pas une chaîne écrite en clair
  (une variable : la contrainte est alors celle du ``Gemfile.lock``, à réécrire à la main).

``ruby "3.3.0"`` (la version de Ruby) est pour E27.

**Le ``Gemfile.lock``**, lu comme le fait ``Bundler::LockfileParser`` (Bundler 4.0) : les sections
``GEM`` (rubygems.org, ``remote:``), ``GIT``, ``PATH`` et ``PLUGIN SOURCE``, chacune avec ses
gems (``specs:``, quatre espaces) et ce que chacune requiert (six espaces) ; ``PLATFORMS`` ;
``DEPENDENCIES`` (les contraintes du ``Gemfile``, ``nom!`` pour une gem d'une source à part) ;
``CHECKSUMS``, ``RUBY VERSION``, ``BUNDLED WITH``. Une gem à plateforme
(``nokogiri (1.19.0-x86_64-linux-gnu)``) a la version d'avant le premier ``-`` : les versions
RubyGems n'en ont pas. Le lockfile n'a pas les groupes : on suit le graphe depuis les directes
pour le scope des transitives. Une gem d'une section ``GIT`` est « dépendance git », d'une section
``PATH`` « chemin local » (sauf la gem du projet lui-même, ``remote: .``), d'une section ``GEM``
d'un autre serveur que rubygems.org (quand il y en a plusieurs) non vérifiable. Bundler n'a pas
de workspace : le lockfile est celui du dossier du ``Gemfile``.

Repris de ``reference/argos_sca_parsers.py`` (L800-825, ``parse_gemfile_lock``), puis réécrit :
``Dependency`` au lieu de ``SCAComponent``, toutes les sections (``reference/`` ne lisait que les
``specs:``, et marquait tout ``pinned``, git et chemins compris), versions à plateforme, graphe,
et le ``Gemfile`` et le ``.gemspec``, que ``reference/`` repérait sans les lire.
"""

import dataclasses
import functools
import logging
import posixpath
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from forceupdate.detect.manifests import match_dependency_file
from forceupdate.models import Dependency, Ecosystem, Location, Notice, Project, Scope
from forceupdate.parsers.base import REASON_GIT, REASON_LOCAL, ParseError, ReadText
from forceupdate.parsers.lockfiles import (
    Edge,
    LockedPackage,
    Lockfile,
    Start,
    dirname,
    join,
    transitives,
)
from forceupdate.parsers.ruby_spans import Statement, Token, statements
from forceupdate.versions import InvalidConstraint, InvalidVersion
from forceupdate.versions.rubygems import RUBYGEMS

logger = logging.getLogger(__name__)

MANIFESTS = {"Gemfile": "Gemfile.lock", "gems.rb": "gems.locked"}
"""Les noms du ``Gemfile`` que connaît Bundler, et le lockfile de chacun."""
GEMSPEC = "*.gemspec"

REASON_OTHER_SOURCE = "vient d'un autre serveur de gems que rubygems.org"
REASON_PLUGIN = "vient d'une source de plugin de Bundler"
REASON_PLATFORMS = "pas installée sur les plateformes du Gemfile.lock (platforms)"
REASON_BUNDLER = "Bundler lui-même : sa version est celle de BUNDLED WITH"

DEV_GROUPS = frozenset({"development", "test"})
"""Les groupes d'une gem de développement : seulement eux, c'est ``dev``."""
RUBYGEMS_HOSTS = frozenset({"rubygems.org", "www.rubygems.org", "index.rubygems.org"})

_GIT_KEYS = frozenset({"git", "github", "gist", "bitbucket"})
_CONDITIONS = frozenset({"if", "unless", "case", "while", "until"})
_OTHER_OPENERS = frozenset({"def", "class", "module", "begin", "for"})
_MODIFIERS = frozenset({"if", "unless"})
_ADD_METHODS = {
    "add_dependency": Scope.RUNTIME,
    "add_runtime_dependency": Scope.RUNTIME,
    "add_development_dependency": Scope.DEV,
}


def is_rubygems(url: str) -> bool:
    """Vrai pour l'adresse de rubygems.org (``https://rubygems.org/``)."""
    try:
        host = urlsplit(url.strip()).hostname
    except ValueError:
        return False
    return host is not None and host.lower() in RUBYGEMS_HOSTS


# ---------------------------------------------------------------------------
# Arguments d'un appel
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Argument:
    """Un argument d'un appel Ruby : positionnel (``key`` vide) ou option (``require: false``)."""

    key: str
    tokens: tuple[Token, ...]

    def strings(self) -> list[Token] | None:
        """Les chaînes d'une chaîne seule ou d'une liste de chaînes (``.freeze`` permis) ;
        ``None`` pour autre chose."""
        items = _without_freeze(self.tokens)
        if len(items) == 1 and items[0].kind == "string":
            return [items[0]]
        if len(items) >= 2 and _is(items[0], "op", "[") and _is(items[-1], "op", "]"):
            inner = [t for t in items[1:-1] if not _is(t, "op", ",")]
            inner = _without_freeze(tuple(inner))
            if all(t.kind == "string" for t in inner):
                return list(inner)
        return None

    def values(self) -> list[str] | None:
        """Les valeurs d'une option : un symbole, une chaîne, ``true``, une liste (``%i[…]``,
        ``[:a, :b]``) ; ``None`` pour autre chose (une variable)."""
        items = _without_freeze(self.tokens)
        if len(items) == 1:
            token = items[0]
            if token.kind in ("symbol", "string", "ident"):
                return [token.value]
            if token.kind == "words":
                return list(token.words)
            return None
        if len(items) >= 2 and _is(items[0], "op", "[") and _is(items[-1], "op", "]"):
            inner = [t for t in items[1:-1] if not _is(t, "op", ",")]
            if all(t.kind in ("symbol", "string") for t in inner):
                return [t.value for t in inner]
        return None


def _is(token: Token, kind: str, value: str) -> bool:
    return token.kind == kind and token.value == value


def _without_freeze(tokens: Sequence[Token]) -> tuple[Token, ...]:
    """``tokens`` sans les ``.freeze`` qui suivent les chaînes (``%q<rack>.freeze``)."""
    kept: list[Token] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        follows = tokens[index + 1 : index + 3]
        if (
            len(follows) == 2
            and _is(follows[0], "op", ".")
            and _is(follows[1], "ident", "freeze")
            and token.kind == "string"
        ):
            kept.append(token)
            index += 3
            continue
        kept.append(token)
        index += 1
    return tuple(kept)


def _arguments(tokens: Sequence[Token]) -> tuple[list[_Argument], Token | None]:
    """Les arguments d'un appel (``tokens`` : ce qui suit le nom de la méthode), et le ``if`` ou
    ``unless`` qui le met sous condition. S'arrête au ``do`` d'un bloc."""
    items = list(tokens)
    trailing: list[Token] = []
    if items and _is(items[0], "op", "("):
        end = _closing(items)
        items, trailing = items[1:end], items[end + 1 :]
    arguments: list[_Argument] = []
    current: list[Token] = []
    depth = 0
    modifier = None
    for token in items:
        if depth == 0 and token.kind == "ident" and token.value in ("if", "unless", "do"):
            modifier = token if token.value != "do" else None
            break
        if token.kind == "op" and token.value in ("(", "[", "{"):
            depth += 1
        elif token.kind == "op" and token.value in (")", "]", "}"):
            depth -= 1
        if depth == 0 and _is(token, "op", ","):
            arguments.append(_argument(current))
            current = []
            continue
        current.append(token)
    if current:
        arguments.append(_argument(current))
    if modifier is None:
        modifier = next((t for t in trailing if t.kind == "ident" and t.value in _MODIFIERS), None)
    return arguments, modifier


def _closing(tokens: Sequence[Token]) -> int:
    """L'index de la parenthèse qui ferme celle de ``tokens[0]`` ; la fin sans elle."""
    depth = 0
    for index, token in enumerate(tokens):
        if token.kind == "op" and token.value in ("(", "[", "{"):
            depth += 1
        elif token.kind == "op" and token.value in (")", "]", "}"):
            depth -= 1
            if depth == 0:
                return index
    return len(tokens)


def _argument(tokens: list[Token]) -> _Argument:
    if len(tokens) >= 2 and tokens[0].kind == "label":
        return _Argument(tokens[0].value, tuple(tokens[1:]))
    if len(tokens) >= 3 and tokens[0].kind in ("symbol", "string") and _is(tokens[1], "op", "=>"):
        return _Argument(tokens[0].value, tuple(tokens[2:]))
    return _Argument("", tuple(tokens))


def _blocks(statement: Statement) -> int:
    """Les blocs qu'ouvre l'instruction, moins ceux qu'elle ferme : ``group :test do`` en ouvre
    un, ``if x`` aussi, ``end`` en ferme un, ``foo do |x| x end`` aucun. Un ``if`` ou un
    ``unless`` qui suit l'instruction (``gem "x" if y``) n'ouvre rien."""
    tokens = statement.tokens
    head = tokens[0]
    opened = sum(1 for t in tokens if _is(t, "ident", "do"))
    if head.kind == "ident" and head.value in _CONDITIONS | _OTHER_OPENERS:
        opened += 1
    return opened - sum(1 for t in tokens if _is(t, "ident", "end"))


# ---------------------------------------------------------------------------
# Requirements : les contraintes d'une gem
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Requirement:
    """Les contraintes d'une gem telles qu'écrites, et leur emplacement."""

    constraint: str
    location: Location | None
    literal: bool
    """Faux si une contrainte n'est pas une chaîne écrite en clair (une variable)."""


def _requirement(arguments: Sequence[_Argument]) -> _Requirement:
    """Les contraintes des arguments positionnels (après le nom), jointes par ``, ``."""
    parts: list[Token] = []
    for argument in arguments:
        found = argument.strings()
        if found is None:
            return _Requirement("", None, literal=False)
        parts += found
    if not parts:
        return _Requirement("", None, literal=True)
    constraint = ", ".join(t.value.strip() for t in parts)
    first, last = parts[0], parts[-1]
    location = None
    if all(t.plain and t.line == first.line and t.end_line == first.line for t in parts):
        start = first.column + len(first.value) - len(first.value.lstrip())
        end = last.end_column - (len(last.value) - len(last.value.rstrip()))
        if start <= end:
            location = Location(line=first.line, column=start, end_column=end)
    return _Requirement(constraint, location, literal=True)


# ---------------------------------------------------------------------------
# Gemfile
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GemspecDirective:
    """Une ligne ``gemspec`` du ``Gemfile`` et ses options."""

    path: str = "."
    name: str | None = None
    development_group: str = "development"
    line: int = 0


@dataclass(frozen=True, kw_only=True)
class Gemfile:
    """Un ``Gemfile`` lu."""

    dependencies: list[Dependency]
    notices: list[Notice]
    gemspecs: tuple[GemspecDirective, ...] = ()
    platform_restricted: frozenset[int] = frozenset()
    """Les index, dans ``dependencies``, des gems limitées à des plateformes (``platforms``)."""
    unwritten: frozenset[int] = frozenset()
    """Les index des gems dont la contrainte n'est pas écrite en clair."""
    paths: tuple[str, ...] = ()
    """Les dossiers des gems locales : ``path:``, les blocs ``path``, ``gemspec path:``. Relatifs
    au dossier du ``Gemfile``."""


@dataclass
class _Block:
    kind: str
    """``group``, ``platforms``, ``source``, ``condition`` ou ``other``."""
    groups: tuple[str, ...] = ()
    optional: bool = False
    reason: str | None = None
    line: int = 0


@dataclass
class _GemfileReader:
    path: str
    stack: list[_Block] = field(default_factory=list)
    git_keys: set[str] = field(default_factory=lambda: set(_GIT_KEYS))
    dependencies: list[Dependency] = field(default_factory=list)
    notices: list[Notice] = field(default_factory=list)
    gemspecs: list[GemspecDirective] = field(default_factory=list)
    restricted: set[int] = field(default_factory=set)
    unwritten: set[int] = field(default_factory=set)
    warned: set[int] = field(default_factory=set)
    paths: list[str] = field(default_factory=list)

    def read(self, content: str) -> Gemfile:
        for statement in statements(content):
            self.statement(statement)
        return Gemfile(
            dependencies=self.dependencies,
            notices=self.notices,
            gemspecs=tuple(self.gemspecs),
            platform_restricted=frozenset(self.restricted),
            unwritten=frozenset(self.unwritten),
            paths=tuple(dict.fromkeys(self.paths)),
        )

    def note(self, line: int, message: str) -> None:
        self.notices.append(Notice(file=self.path, message=f"ligne {line} : {message}"))

    def statement(self, statement: Statement) -> None:
        tokens = statement.tokens
        head = tokens[0]
        balance = _blocks(statement)
        name = head.value if head.kind == "ident" else ""
        arguments: list[_Argument] = []
        if name in _CONDITIONS:
            block = _Block("condition", line=head.line)
        elif name in _OTHER_OPENERS or name in ("", "end"):
            block = _Block("other", line=head.line)
        else:
            arguments, modifier = _arguments(tokens[1:])
            if name == "gem":
                self.gem(statement, arguments, modifier)
            elif name == "gemspec":
                self.gemspec(statement, arguments)
            elif name == "eval_gemfile":
                self.note(
                    head.line, "eval_gemfile : le fichier chargé n'est pas lu par forceupdate."
                )
            elif name == "git_source" and arguments and arguments[0].tokens:
                self.git_keys.add(arguments[0].tokens[0].value)
            elif name == "path" and arguments and not arguments[0].key:
                self.paths += arguments[0].values() or []
            block = self.block(name, arguments, head.line)
        if balance > 0:
            self.stack += [block] * balance
        else:
            del self.stack[max(len(self.stack) + balance, 0) :]

    def block(self, name: str, arguments: Sequence[_Argument], line: int) -> _Block:
        positional = [a for a in arguments if not a.key]
        options = {a.key: a for a in arguments if a.key}
        if name == "group":
            groups = tuple(v for a in positional for v in (a.values() or []))
            optional = (
                (options["optional"].values() or []) == ["true"] if "optional" in options else False
            )
            return _Block("group", groups=groups, optional=optional, line=line)
        if name in ("platforms", "platform"):
            return _Block("platforms", line=line)
        if name == "source":
            url = positional[0].values() if positional else None
            if "type" in options:
                return _Block("source", reason=REASON_PLUGIN, line=line)
            other = url is None or not is_rubygems(url[0])
            return _Block("source", reason=REASON_OTHER_SOURCE if other else None, line=line)
        if name == "path":
            return _Block("source", reason=REASON_LOCAL, line=line)
        if name in ("git", "github"):
            return _Block("source", reason=REASON_GIT, line=line)
        return _Block("other", line=line)

    def gem(self, statement: Statement, arguments: list[_Argument], modifier: Token | None) -> None:
        line = statement.line
        positional = [a for a in arguments if not a.key]
        options = {a.key: a for a in arguments if a.key}
        names = positional[0].strings() if positional else None
        if not names or len(names) != 1 or not names[0].plain or not names[0].value.strip():
            self.note(line, "gem dont le nom n'est pas une chaîne écrite en clair : pas lue.")
            return
        name = names[0].value.strip()
        requirement = _requirement(positional[1:])
        if not requirement.literal:
            self.note(
                line,
                f"la contrainte de « {name} » n'est pas une chaîne écrite en clair : celle du "
                "Gemfile.lock est prise, à réécrire à la main.",
            )
        groups = [g for b in self.stack if b.kind == "group" for g in b.groups]
        for key in ("group", "groups"):
            if key in options:
                groups += options[key].values() or ["?"]
        optional = any(b.optional for b in self.stack if b.kind == "group")
        if groups and all(g in DEV_GROUPS for g in groups):
            scope = Scope.DEV
        elif optional:
            scope = Scope.OPTIONAL
        else:
            scope = Scope.RUNTIME
        reason = next((b.reason for b in reversed(self.stack) if b.kind == "source"), None)
        if self.git_keys & options.keys():
            reason = REASON_GIT
        elif "path" in options:
            reason = REASON_LOCAL
            self.paths += options["path"].values() or []
        elif "source" in options:
            url = options["source"].values()
            reason = None if url and is_rubygems(url[0]) else REASON_OTHER_SOURCE
        condition = next((b for b in reversed(self.stack) if b.kind == "condition"), None)
        if modifier is not None:
            self.note(
                line,
                f"« {name} » est déclarée sous condition ({modifier.value}), que forceupdate "
                "n'évalue pas : lue comme toujours déclarée.",
            )
        elif condition is not None and condition.line not in self.warned:
            self.warned.add(condition.line)
            self.note(
                condition.line,
                "condition que forceupdate n'évalue pas : les gem qu'elle déclare sont lues "
                "comme toujours déclarées.",
            )
        index = len(self.dependencies)
        if (
            any(b.kind == "platforms" for b in self.stack)
            or {"platforms", "platform"} & options.keys()
        ):
            self.restricted.add(index)
        if not requirement.literal:
            self.unwritten.add(index)
        self.dependencies.append(
            Dependency(
                ecosystem=Ecosystem.RUBYGEMS,
                name=name,
                constraint=requirement.constraint,
                scope=scope,
                file=self.path,
                location=requirement.location,
                unverifiable_reason=REASON_BUNDLER if name == "bundler" else reason,
            )
        )

    def gemspec(self, statement: Statement, arguments: list[_Argument]) -> None:
        options = {a.key: a.values() for a in arguments if a.key}
        path = (options.get("path") or ["."])[0]
        name = (options.get("name") or [None])[0]
        group = (options.get("development_group") or ["development"])[0]
        self.gemspecs.append(GemspecDirective(path, name, group or "development", statement.line))
        self.paths.append(path)


def parse_gemfile(path: str, content: str) -> list[Dependency]:
    """Les gems d'un ``Gemfile``, dans l'ordre où il les déclare (sans celles de ``gemspec``)."""
    return _parse_gemfile(path, content).dependencies


def _parse_gemfile(path: str, content: str) -> Gemfile:
    return _GemfileReader(path).read(content)


# ---------------------------------------------------------------------------
# .gemspec
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class Gemspec:
    """Un ``.gemspec`` lu."""

    name: str | None
    """Le nom de la gem (``spec.name = "…"``), s'il est écrit en clair."""
    dependencies: list[Dependency]
    notices: list[Notice]
    unwritten: frozenset[int] = frozenset()
    """Les index des dépendances dont la contrainte n'est pas écrite en clair."""


def parse_gemspec(
    path: str, content: str, *, development_group: str = "development"
) -> list[Dependency]:
    """Les dépendances d'un ``.gemspec`` : ``add_dependency``, ``add_runtime_dependency``
    (``runtime``) et ``add_development_dependency`` (``dev``, ou le scope de
    ``development_group``)."""
    return _parse_gemspec(path, content, development_group=development_group).dependencies


def _parse_gemspec(path: str, content: str, *, development_group: str = "development") -> Gemspec:
    name = None
    dependencies: list[Dependency] = []
    notices: list[Notice] = []
    unwritten: set[int] = set()
    dev_scope = Scope.DEV if development_group in DEV_GROUPS else Scope.RUNTIME
    for statement in statements(content):
        tokens = statement.tokens
        for index, token in enumerate(tokens[:-1]):
            if not (_is(token, "op", ".") and tokens[index + 1].kind == "ident"):
                continue
            method = tokens[index + 1].value
            if method == "name" and index + 3 < len(tokens) and _is(tokens[index + 2], "op", "="):
                value = _without_freeze(tokens[index + 3 :])
                if len(value) == 1 and value[0].kind == "string" and value[0].plain:
                    name = value[0].value.strip()
            if method not in _ADD_METHODS:
                continue
            arguments, _ = _arguments(tokens[index + 2 :])
            positional = [a for a in arguments if not a.key]
            names = positional[0].strings() if positional else None
            if not names or len(names) != 1 or not names[0].plain:
                notices.append(
                    Notice(
                        file=path,
                        message=f"ligne {statement.line} : dépendance dont le nom n'est pas une "
                        "chaîne écrite en clair : pas lue.",
                    )
                )
                break
            gem = names[0].value.strip()
            requirement = _requirement(positional[1:])
            if not requirement.literal:
                unwritten.add(len(dependencies))
                notices.append(
                    Notice(
                        file=path,
                        message=f"ligne {statement.line} : la contrainte de « {gem} » n'est pas "
                        "une chaîne écrite en clair : pas réécrite.",
                    )
                )
            dependencies.append(
                Dependency(
                    ecosystem=Ecosystem.RUBYGEMS,
                    name=gem,
                    constraint=requirement.constraint,
                    scope=dev_scope if _ADD_METHODS[method] is Scope.DEV else Scope.RUNTIME,
                    file=path,
                    location=requirement.location,
                    unverifiable_reason=REASON_BUNDLER if gem == "bundler" else None,
                )
            )
            break
        if name is None and tokens and _is(tokens[0], "ident", "Gem"):
            # Gem::Specification.new "nom", "1.0" do |s|
            for index, token in enumerate(tokens[:-1]):
                if _is(token, "ident", "new") and tokens[index + 1].kind == "string":
                    name = tokens[index + 1].value.strip()
                    break
    return Gemspec(
        name=name, dependencies=dependencies, notices=notices, unwritten=frozenset(unwritten)
    )


# ---------------------------------------------------------------------------
# Gemfile.lock
# ---------------------------------------------------------------------------

_NAME_VERSION = re.compile(
    r"^( {2}| {4}| {6})(?! )(.*?)(?: \(([^-]*)(?:-(.*))?\))?(!)?(?: ([^ ]+))?$"
)
"""``LockfileParser::NAME_VERSION`` de Bundler : l'indentation, le nom, la version, la plateforme
(après le premier ``-``), le ``!`` d'une gem d'une source à part, une empreinte (``CHECKSUMS``)."""
_SOURCES = ("GIT", "GEM", "PATH", "PLUGIN SOURCE")
_OPTION = re.compile(r"^  ([a-z]+): (.*)$", re.IGNORECASE)


@dataclass(frozen=True, kw_only=True)
class GemfileLock:
    """Un ``Gemfile.lock`` lu."""

    lockfile: Lockfile
    requirements: dict[str, str]
    """``DEPENDENCIES`` : les contraintes du ``Gemfile`` par gem (``~> 2.2, >= 2.2.3`` ; vide sans
    contrainte)."""
    platforms: tuple[str, ...] = ()
    bundled_with: str | None = None
    ruby_version: str | None = None

    def packages(self, name: str) -> list[LockedPackage]:
        return self._by_name.get(name, [])

    @functools.cached_property
    def _by_name(self) -> dict[str, list[LockedPackage]]:
        found: dict[str, list[LockedPackage]] = {}
        for package in self.lockfile.packages:
            found.setdefault(package.name, []).append(package)
        return found


@dataclass
class _Section:
    kind: str
    remotes: list[str] = field(default_factory=list)
    specs: list[tuple[str, str, list[str]]] = field(default_factory=list)


def parse_gemfile_lock(path: str, content: str) -> GemfileLock:
    """Un ``Gemfile.lock`` : ses gems (toutes les sections de sources), ce qu'elles requièrent,
    ses plateformes, ``DEPENDENCIES``, ``BUNDLED WITH`` et ``RUBY VERSION``. Lève ``ParseError``
    pour un fichier qui n'a aucune section connue."""
    return _parse_lock_once(path, content)


@functools.lru_cache(maxsize=4)
def _parse_lock_once(path: str, content: str) -> GemfileLock:
    """Lu une seule fois pour un même contenu. Le résultat est partagé : on ne le modifie pas."""
    lines = [line for line in re.split(r"\r?\n", content.removeprefix("﻿")) if line.strip()]
    known = {*_SOURCES, "DEPENDENCIES", "CHECKSUMS", "PLATFORMS", "RUBY VERSION", "BUNDLED WITH"}
    if lines and not any(line in known for line in lines):
        raise ParseError(
            "ce n'est pas un Gemfile.lock : aucune section connue (GEM, DEPENDENCIES…)."
        )
    sections: list[_Section] = []
    requirements: dict[str, str] = {}
    platforms: list[str] = []
    bundled_with = ruby_version = None
    mode = None
    current: _Section | None = None
    spec: list[str] | None = None
    for line in lines:
        if line in _SOURCES:
            mode, current, spec = "source", _Section(line), None
            sections.append(current)
            continue
        if not line.startswith(" "):
            mode = line if line in known else None
            continue
        if mode == "source" and current is not None:
            option = _OPTION.match(line)
            if line == "  specs:" or option is not None:
                if option is not None and option.group(1) == "remote":
                    current.remotes.append(option.group(2).strip())
                continue
            match = _NAME_VERSION.match(line)
            if match is None:
                continue
            if len(match.group(1)) == 4:
                spec = []
                current.specs.append((match.group(2), match.group(3) or "", spec))
            elif len(match.group(1)) == 6 and spec is not None:
                spec.append(match.group(2))
        elif mode == "DEPENDENCIES":
            match = _NAME_VERSION.match(line)
            if match is not None and len(match.group(1)) == 2:
                versions = match.group(3)
                parts = [p.strip() for p in versions.split(",")] if versions else []
                requirements[match.group(2)] = ", ".join(parts)
        elif mode == "PLATFORMS":
            platforms.append(line.strip())
        elif mode == "BUNDLED WITH":
            bundled_with = line.strip()
        elif mode == "RUBY VERSION":
            ruby_version = line.strip()
    gems = [s for s in sections if s.kind == "GEM"]
    packages = []
    for section in sections:
        reason = _source_reason(section, len(gems))
        for name, version, required in section.specs:
            edges: list[Edge] = [(dep, frozenset()) for dep in required]
            local = section.kind == "PATH" and section.remotes[:1] == ["."]
            packages.append(
                LockedPackage(
                    name=name,
                    version=version.strip(),
                    dependencies=tuple(edges),
                    local=local,
                    unverifiable_reason=None if local else reason,
                )
            )
    lockfile = Lockfile(
        path=path, ecosystem=Ecosystem.RUBYGEMS, packages=tuple(packages), graph=True
    )
    return GemfileLock(
        lockfile=lockfile,
        requirements=requirements,
        platforms=tuple(platforms),
        bundled_with=bundled_with,
        ruby_version=ruby_version,
    )


def _source_reason(section: _Section, gem_sections: int) -> str | None:
    """Pourquoi les gems d'une section ne sont pas vérifiables : git, chemin, plugin, ou un
    autre serveur que rubygems.org quand le lockfile en a plusieurs (la seule section ``GEM``
    est celle de la source globale : un miroir est cherché sur rubygems.org)."""
    if section.kind == "GIT":
        return REASON_GIT
    if section.kind == "PATH":
        return REASON_LOCAL
    if section.kind == "PLUGIN SOURCE":
        return REASON_PLUGIN
    if gem_sections > 1 and not any(is_rubygems(remote) for remote in section.remotes):
        return REASON_OTHER_SOURCE
    return None


# ---------------------------------------------------------------------------
# Un projet
# ---------------------------------------------------------------------------


def parse_project(project: Project, read_text: ReadText) -> None:
    """Lit les fichiers Ruby de ``project`` et remplit ses dépendances : celles du ``Gemfile``
    (dans son ordre), celles des ``.gemspec`` qu'il cite, puis les transitives ; et à
    ``project.notices`` ce qui n'a pas pu être lu."""
    _ProjectParser(project, read_text).run()


class _ProjectParser:
    """Lit les fichiers Ruby d'un projet et relie le ``Gemfile`` et ses ``.gemspec`` au
    ``Gemfile.lock``."""

    def __init__(self, project: Project, read_text: ReadText) -> None:
        self.project = project
        self.read_text = read_text
        self.notices: list[Notice] = []
        self.manifest_path = next((p for p in project.manifests if _is_file(p, *MANIFESTS)), None)
        self.gemspec_paths = [p for p in project.manifests if _is_file(p, GEMSPEC)]
        lockfiles = list(MANIFESTS.values())
        self.lock_path = next((p for p in project.lockfiles if _is_file(p, *lockfiles)), None)

    def run(self) -> None:
        gemfile = self._gemfile()
        declared: list[_Declared] = []
        if gemfile is not None:
            declared += [
                _Declared(d, i in gemfile.platform_restricted, i in gemfile.unwritten)
                for i, d in enumerate(gemfile.dependencies)
            ]
        local_names: set[str] = set()
        for spec in self._gemspecs(gemfile):
            declared += [
                _Declared(d, False, i in spec.unwritten) for i, d in enumerate(spec.dependencies)
            ]
            if spec.name:
                local_names.add(spec.name)
        directs = [d.dependency for d in declared]
        found: list[Dependency] = []
        member = self.lock_path is not None and dirname(self.lock_path) != self.project.path
        if member and not self._member():
            assert self.lock_path is not None
            self.project.lockfiles.remove(self.lock_path)
            self.lock_path = None
        lock = self._lockfile()
        if lock is not None:
            directs, found = _link(declared, lock, local_names, shared=member)
        found.sort(key=lambda d: (d.name, RUBYGEMS.sort_key(d.installed or "")))
        self.project.dependencies.extend(directs + found)
        self.project.notices.extend(self.notices)

    def _read(self, path: str) -> str | None:
        try:
            content = self.read_text(path)
        except ValueError:
            content = None
        if content is None:
            self.notices.append(
                Notice(file=path, message="introuvable, illisible ou trop gros : pas lu.")
            )
        return content

    def _gemfile(self) -> Gemfile | None:
        if self.manifest_path is None:
            return None
        content = self._read(self.manifest_path)
        if content is None:
            return None
        parsed = _parse_gemfile(self.manifest_path, content)
        self.notices.extend(parsed.notices)
        return parsed

    def _gemspecs(self, gemfile: Gemfile | None) -> list[Gemspec]:
        """Les ``.gemspec`` que cite le ``Gemfile`` (``gemspec``) ; tous ceux du dossier s'il n'y
        a pas de ``Gemfile`` (une gem). Un ``.gemspec`` que le ``Gemfile`` ne cite pas : une
        remarque."""
        if gemfile is None and self.manifest_path is not None:
            return []
        directives = gemfile.gemspecs if gemfile is not None else (GemspecDirective(),)
        read: dict[str, Gemspec] = {}
        for directive in directives:
            if posixpath.normpath(directive.path) != ".":
                self.notices.append(
                    Notice(
                        file=self.manifest_path or "",
                        message=f"ligne {directive.line} : gemspec d'un autre dossier "
                        f"({directive.path}) : lu avec son propre projet.",
                    )
                )
                continue
            for path in self.gemspec_paths:
                spec = read.get(path) or self._gemspec(path, directive.development_group)
                if spec is None:
                    continue
                if directive.name is None or spec.name == directive.name:
                    read[path] = spec
        if gemfile is not None:
            for path in self.gemspec_paths:
                if path not in read and not gemfile.gemspecs:
                    self.notices.append(
                        Notice(file=path, message="pas cité par le Gemfile (gemspec) : pas lu.")
                    )
        return list(read.values())

    def _gemspec(self, path: str, development_group: str) -> Gemspec | None:
        content = self._read(path)
        if content is None:
            return None
        parsed = _parse_gemspec(path, content, development_group=development_group)
        self.notices.extend(parsed.notices)
        return parsed

    def _member(self) -> bool:
        """Vrai si le projet (un ``.gemspec`` sans ``Gemfile``) est une gem locale du ``Gemfile``
        du lockfile qu'on lui a rattaché, plus haut : ``path:``, un bloc ``path`` ou ``gemspec
        path:`` désigne son dossier. Bundler la résout alors dans ce lockfile."""
        if self.manifest_path is not None or self.lock_path is None:
            return False
        root = dirname(self.lock_path)
        gemfile = join(
            root, next(m for m, lock in MANIFESTS.items() if _named(self.lock_path, lock))
        )
        try:
            content = self.read_text(gemfile)
        except ValueError:
            content = None
        if content is None:
            return False
        paths = _parse_gemfile(gemfile, content).paths
        return any(_normalize(join(root, path)) == self.project.path for path in paths)

    def _lockfile(self) -> GemfileLock | None:
        if self.lock_path is None:
            return None
        content = self._read(self.lock_path)
        if content is None:
            return None
        try:
            return parse_gemfile_lock(self.lock_path, content)
        except ParseError as err:
            self.notices.append(Notice(file=self.lock_path, message=str(err)))
            return None


@dataclass(frozen=True)
class _Declared:
    """Une dépendance d'un manifeste, et ce que le lien au lockfile doit en savoir."""

    dependency: Dependency
    restricted: bool
    """Limitée à des plateformes (``platforms``)."""
    unwritten: bool
    """Sa contrainte n'est pas écrite en clair : celle du lockfile (``DEPENDENCIES``) la donne."""


def _link(
    declared: Iterable[_Declared], lock: GemfileLock, local_names: set[str], *, shared: bool
) -> tuple[list[Dependency], list[Dependency]]:
    """Les directes avec leur version figée, et les transitives que le projet tire du lockfile,
    leur scope suivi dans le graphe depuis les directes. ``shared`` : le lockfile d'un
    ``Gemfile`` plus haut, dont le projet est une gem locale ; seules les gems que tirent ses
    directes sont à lui."""
    packages = tuple(
        dataclasses.replace(p, local=True, unverifiable_reason=None)
        if p.name in local_names and p.unverifiable_reason == REASON_LOCAL
        else p
        for p in lock.lockfile.packages
    )
    lockfile = dataclasses.replace(lock.lockfile, packages=packages, shared=shared)
    directs = []
    starts: list[Start] = []
    for item in declared:
        dependency = item.dependency
        if item.unwritten and dependency.name in lock.requirements:
            dependency = dataclasses.replace(
                dependency, constraint=lock.requirements[dependency.name], location=None
            )
        found = [p for p in packages if p.name == dependency.name and not p.local]
        if found:
            starts.append((dependency.scope, (dependency.name, frozenset())))
            package = _installed(dependency, found)
            if dependency.unverifiable_reason is None and package.unverifiable_reason is not None:
                dependency = dataclasses.replace(
                    dependency, unverifiable_reason=package.unverifiable_reason
                )
            dependency = dataclasses.replace(
                dependency, installed=package.version, lockfile=lockfile.path
            )
        elif item.restricted and dependency.unverifiable_reason is None:
            dependency = dataclasses.replace(dependency, unverifiable_reason=REASON_PLATFORMS)
        directs.append(dependency)
    names = {d.name for d in directs}
    found_transitives = transitives(lockfile, starts, lambda package: package.name in names)
    return directs, found_transitives


def _installed(dependency: Dependency, packages: Sequence[LockedPackage]) -> LockedPackage:
    """Le paquet figé d'une directe : la plus haute version qui respecte sa contrainte (les
    variantes à plateforme d'une gem ont la même)."""

    def accepted(package: LockedPackage) -> bool:
        try:
            return RUBYGEMS.satisfies(dependency.constraint, package.version)
        except (InvalidConstraint, InvalidVersion):
            return False

    candidates = [p for p in packages if accepted(p)] or list(packages)
    return max(candidates, key=lambda p: RUBYGEMS.sort_key(p.version))


def _named(path: str, name: str) -> bool:
    return posixpath.basename(path) == name


def _normalize(path: str) -> str:
    """Un chemin POSIX relatif sans ``./`` ni ``/`` final (``.`` pour la racine)."""
    return posixpath.normpath(path.replace("\\", "/"))


def _is_file(path: str, *patterns: str) -> bool:
    match = match_dependency_file(path)
    return match is not None and match.ecosystem is Ecosystem.RUBYGEMS and match.pattern in patterns
