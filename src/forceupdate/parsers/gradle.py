"""Le parseur Gradle : le catalogue ``gradle/libs.versions.toml``, ``build.gradle`` et
``build.gradle.kts``, ``gradle.properties``. **Gradle n'est jamais exécuté** : un script est un
programme (Groovy ou Kotlin), lu ici en jetons (``parsers.gradle_spans``), comme le ``Gemfile``.

**Le catalogue** (``gradle/libs.versions.toml``, celui que Gradle lit tout seul) est du TOML, lu
entièrement :

- ``[libraries]`` : ``"groupe:artefact:version"``, ou une table (``module``, ou ``group`` et
  ``name`` ; ``version``, ``version.ref`` qui renvoie à ``[versions]``, ou une version riche
  ``{ strictly, require, prefer }``, dont la première de cet ordre est lue) ;
- ``[plugins]`` : ``"id:version"``, ou ``{ id, version }`` ; un plugin s'appelle par son ``id``
  (scope ``build``) ;
- ``[versions]`` : une version partagée par plusieurs entrées ``version.ref`` n'a qu'un
  emplacement, celui de ``[versions]`` : elles montent ensemble.

Ses entrées sont les dépendances du projet du catalogue (le dossier au-dessus de ``gradle/``). Leur
scope vient des scripts du projet et de ceux en dessous (``testImplementation(libs.junit)`` :
``dev``) ; ``runtime`` sinon. Un script qui cite ``libs.x`` ne redonne pas la dépendance : sa
version est celle du catalogue, vérifiée une fois.

**Un script** : les formes littérales courantes, dans un bloc ``dependencies`` ou ``buildscript`` :

- ``implementation("g:a:v")``, ``implementation 'g:a:v'``, plusieurs notations séparées par des
  virgules, ``g:a:v:classifieur``, ``g:a:v@ext`` ;
- ``implementation(platform("g:a:v"))``, ``enforcedPlatform``, ``testFixtures`` ;
- ``implementation group: 'g', name: 'a', version: 'v'`` (Groovy), ``implementation(group = "g",
  name = "a", version = "v")`` (Kotlin) ;
- dans ``plugins { }`` : ``id("x") version "v"``, ``id 'x' version 'v'``, ``kotlin("jvm") version
  "v"`` (l'``id`` ``org.jetbrains.kotlin.jvm``) ; ``classpath("g:a:v")`` dans ``buildscript`` ;
- une version riche (E34) : ``implementation("g:a") { version { strictly("1.7.36") } }``, la
  première de ``strictly``, ``require``, ``prefer``, comme dans le catalogue.

**``settings.gradle(.kts)``** (E34) : ses ``plugins { }`` et ceux de ``pluginManagement``, lus comme
ceux d'un script ; les autres catalogues de ``dependencyResolutionManagement { versionCatalogs {
create("deps") { from(files("gradle/deps.versions.toml")) } } }`` (Groovy : ``deps { from(…) }``),
lus comme ``libs.versions.toml`` (le scope de leurs entrées est ``runtime`` : seul ``libs.`` est
suivi dans les scripts) ; un catalogue publié (``from("g:a:v")``) n'est pas lu (une remarque).
``buildSrc`` est un build à part : son ``build.gradle(.kts)`` est un projet ; les constantes de ses
sources Kotlin ou Groovy (``object Versions { … }``) ne sont pas lues.

La configuration donne le scope : ``test…`` et ``androidTest…`` : ``dev`` ; ``classpath``,
``annotationProcessor``, ``kapt``, ``ksp`` : ``build`` ; ``runtime`` sinon.

**Une variable** (``"g:a:$v"``, ``"${v}"``) est cherchée, dans l'ordre : dans le script (``val v =
"…"``, ``def v = '…'``, ``ext.v = …``, ``ext { v = … }``, ``extra["v"] = …``, ``val v by
extra(…)``),
dans les ``ext`` des scripts des dossiers parents, puis dans ``gradle.properties`` (celui du
projet, puis des dossiers parents). La version est alors située dans la valeur de la variable,
qui monte pour toutes les dépendances qui la citent. Une variable introuvable, ou une expression
(``"${deps.x}"``) : non vérifiable, avec la raison.

**La version utilisée** : une version nue est celle que demande le script (« require ») ; Gradle
peut en prendre une plus haute si une autre dépendance l'exige. Sans lockfile, c'est
``Dependency.installed``. **Les verrous de Gradle** (``gradle.lockfile`` du projet, E34) : les
lignes ``groupe:artefact:version=configurations`` donnent la version installée des directes, et
les indirectes (leur scope d'après leurs configurations : ``test…`` → ``dev``). forceupdate ne les
régénère pas (Gradle exécute les scripts du projet, et n'est jamais lancé) : une remarque dit de
les refaire après une mise à jour (``gradle dependencies --write-locks``), sinon le build échoue.
"""

import dataclasses
import functools
import posixpath
import re
import tomllib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from forceupdate.models import Dependency, Ecosystem, Location, Notice, Scope
from forceupdate.parsers.base import ParseError, ReadText
from forceupdate.parsers.gradle_spans import Token, tokens
from forceupdate.parsers.toml_spans import string_spans
from forceupdate.versions import InvalidConstraint
from forceupdate.versions.maven import MAVEN

CATALOG = "gradle/libs.versions.toml"
SCRIPTS = ("build.gradle", "build.gradle.kts")
SETTINGS = ("settings.gradle", "settings.gradle.kts")
PROPERTIES = "gradle.properties"
LOCKFILE = "gradle.lockfile"

REASON_PLATFORM = "sans version : fixée par une plateforme (BOM) ou par un plugin"
REASON_EXPRESSION = "version calculée par le script ({expression}), pas lue"

_CONFIGURATIONS = frozenset(
    {
        "implementation", "api", "compileOnly", "runtimeOnly", "compileOnlyApi", "compile",
        "runtime", "provided", "providedCompile", "providedRuntime", "developmentOnly",
        "annotationProcessor", "kapt", "ksp", "classpath", "coreLibraryDesugaring",
        "detektPlugins", "lintChecks", "lintPublish",
    }
)  # fmt: skip
_CONFIGURATION = re.compile(
    r"[a-z][A-Za-z0-9]*(?:Implementation|Api|CompileOnly|RuntimeOnly|AnnotationProcessor"
    r"|Compile|Runtime)"
)
_BUILD_CONFIGURATIONS = re.compile(
    r"classpath|annotationProcessor|kapt.*|ksp.*|detektPlugins|lintChecks|lintPublish"
    r"|coreLibraryDesugaring|.*AnnotationProcessor"
)
_WRAPPERS = frozenset({"platform", "enforcedPlatform", "testFixtures"})
_MODIFIERS = frozenset({"val", "var", "def", "const", "private", "final", "static", "String"})
_SIMPLE_REFERENCE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)|\$\{\s*([^{}]*?)\s*\}")
_OWNER = re.compile(r"(?:(?:rootProject|project)\.)?(?:(?:ext|extra)\.)?([A-Za-z_][A-Za-z0-9_]*)")
"""Une variable citée simplement : ``v``, ``project.ext.v``, ``rootProject.v``…"""
_RICH = ("strictly", "require", "prefer")
"""Les versions d'une version riche, dans l'ordre où on en lit une."""


def configuration_scope(configuration: str) -> Scope:
    """Le scope d'une configuration Gradle (``testImplementation`` : ``dev``)."""
    if "test" in configuration.lower() or configuration == "developmentOnly":
        return Scope.DEV
    if _BUILD_CONFIGURATIONS.fullmatch(configuration):
        return Scope.BUILD
    return Scope.RUNTIME


def is_configuration(name: str) -> bool:
    return name in _CONFIGURATIONS or _CONFIGURATION.fullmatch(name) is not None


def plugin_id(name: str) -> bool:
    """Vrai pour le nom d'un plugin Gradle (son ``id``, sans ``:``) : il se cherche sur le
    portail des plugins."""
    return ":" not in name


# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class Variable:
    """Une variable qui peut donner une version : sa valeur, et où elle est écrite."""

    name: str
    value: str | None
    """``None`` si la valeur n'est pas une chaîne écrite telle quelle."""
    file: str
    location: Location | None
    shared: bool = False
    """Vraie pour une propriété « extra » (``ext``, ``extra``), que voient les scripts des
    sous-projets."""


def read_properties(path: str, content: str) -> dict[str, Variable]:
    """Les propriétés d'un ``gradle.properties`` (``clé=valeur``, ``clé: valeur``)."""
    found = {}
    for number, line in enumerate(content.split("\n"), start=1):
        match = re.match(r"\s*([^=:#!\s][^=:\s]*)\s*[=:]\s*(.*?)\s*$", line)
        if match is None or line.lstrip().startswith(("#", "!")):
            continue
        value = match.group(2)
        plain = "\\" not in value
        location = (
            Location(line=number, column=match.start(2), end_column=match.end(2))
            if plain and value
            else None
        )
        found[match.group(1)] = Variable(
            name=match.group(1), value=value if plain else None, file=path, location=location,
            shared=True,
        )  # fmt: skip
    return found


# ---------------------------------------------------------------------------
# Le catalogue
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class CatalogEntry:
    """Une entrée de ``[libraries]`` ou de ``[plugins]``."""

    section: str
    alias: str
    name: str
    """``groupe:artefact``, ou l'``id`` d'un plugin."""
    version: str
    """La version, déjà reprise de ``[versions]`` pour ``version.ref`` ; vide sans version."""
    location: Location | None
    reason: str | None = None


@dataclass(frozen=True, kw_only=True)
class Catalog:
    """Un ``libs.versions.toml`` lu."""

    path: str
    versions: dict[str, tuple[str, Location | None]]
    entries: tuple[CatalogEntry, ...]
    bundles: dict[str, tuple[str, ...]]

    def accessor(self, section: str, path: str) -> list[CatalogEntry]:
        """Les entrées qu'un script cite par ``libs.<path>`` : une bibliothèque ou un plugin
        (``section``), ou les bibliothèques d'un ``bundles``."""
        if section == "bundles":
            aliases = next(
                (items for alias, items in self.bundles.items() if _accessor(alias) == path), ()
            )
            libraries = {e.alias: e for e in self.entries if e.section == "libraries"}
            return [libraries[alias] for alias in aliases if alias in libraries]
        return [e for e in self.entries if e.section == section and _accessor(e.alias) == path]


def _accessor(alias: str) -> str:
    """L'accesseur d'un alias : ``-`` et ``_`` deviennent des ``.`` (``spring-core`` :
    ``libs.spring.core``)."""
    return re.sub(r"[-_.]", ".", alias)


def read_catalog(path: str, content: str) -> Catalog:
    """Un catalogue de versions. Lève ``ParseError`` si le TOML est invalide."""
    return _read_catalog_once(path, content)


@functools.lru_cache(maxsize=16)
def _read_catalog_once(path: str, content: str) -> Catalog:
    try:
        data = tomllib.loads(content.removeprefix("﻿"))
    except tomllib.TOMLDecodeError as error:
        raise ParseError(f"TOML invalide ({error}).") from error
    spans = string_spans(content)

    def location(*key: str | int, start: int = 0, end: int | None = None) -> Location | None:
        span = spans.get(key)
        if span is None:
            return None
        value = data_at(key)
        stop = len(value) if end is None and isinstance(value, str) else end
        return None if stop is None else span.location(start, stop)

    def data_at(key: tuple[str | int, ...]) -> Any:
        value: Any = data
        for part in key:
            value = value.get(part) if isinstance(value, dict) else None
        return value

    versions: dict[str, tuple[str, Location | None]] = {}
    for key, value in _table(data, "versions").items():
        if isinstance(value, str):
            versions[key] = (value.strip(), location("versions", key))
        elif isinstance(value, dict):
            rich = next((r for r in _RICH if isinstance(value.get(r), str)), None)
            if rich is not None:
                versions[key] = (value[rich].strip(), location("versions", key, rich))
    entries = []
    for section in ("libraries", "plugins"):
        for alias, value in _table(data, section).items():
            entry = _catalog_entry(section, alias, value, versions, location)
            if entry is not None:
                entries.append(entry)
    bundles = {
        alias: tuple(item for item in items if isinstance(item, str))
        for alias, items in _table(data, "bundles").items()
        if isinstance(items, list)
    }
    return Catalog(path=path, versions=versions, entries=tuple(entries), bundles=bundles)


def _table(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _catalog_entry(
    section: str, alias: str, value: Any, versions: dict[str, tuple[str, Location | None]],
    location: Any,
) -> CatalogEntry | None:  # fmt: skip
    plugin = section == "plugins"
    if isinstance(value, str):
        parts = value.split(":")
        count = 2 if plugin else 3
        name = parts[0] if plugin else ":".join(parts[:2])
        if len(parts) < count or not all(parts[: count - 1]):
            return CatalogEntry(section=section, alias=alias, name=name, version="",
                                location=None, reason=REASON_PLATFORM)  # fmt: skip
        start = len(":".join(parts[: count - 1])) + 1
        version = ":".join(parts[count - 1 :]) if plugin else parts[count - 1]
        where = location(section, alias, start=start, end=start + len(version))
        return CatalogEntry(section=section, alias=alias, name=name, version=version.strip(),
                            location=where)  # fmt: skip
    if not isinstance(value, dict):
        return None
    if plugin:
        name = value.get("id") if isinstance(value.get("id"), str) else None
    elif isinstance(value.get("module"), str):
        name = value["module"]
    elif isinstance(value.get("group"), str) and isinstance(value.get("name"), str):
        name = f"{value['group']}:{value['name']}"
    else:
        name = None
    if not name:
        return None
    version = value.get("version")
    if isinstance(version, str):
        return CatalogEntry(section=section, alias=alias, name=name, version=version.strip(),
                            location=location(section, alias, "version"))  # fmt: skip
    if isinstance(version, dict) and isinstance(version.get("ref"), str):
        ref = version["ref"]
        if ref not in versions:
            return CatalogEntry(section=section, alias=alias, name=name, version="",
                                location=None,
                                reason=f"version.ref « {ref} » absente de [versions]")  # fmt: skip
        text, where = versions[ref]
        return CatalogEntry(section=section, alias=alias, name=name, version=text, location=where)
    if isinstance(version, dict):
        rich = next((r for r in _RICH if isinstance(version.get(r), str)), None)
        if rich is not None:
            return CatalogEntry(section=section, alias=alias, name=name,
                                version=version[rich].strip(),
                                location=location(section, alias, "version", rich))  # fmt: skip
    return CatalogEntry(section=section, alias=alias, name=name, version="", location=None,
                        reason=REASON_PLATFORM)  # fmt: skip


# ---------------------------------------------------------------------------
# Un script
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class Notation:
    """Une dépendance écrite dans un script, avec sa version telle qu'écrite."""

    name: str
    """``groupe:artefact`` (ses ``$`` déjà remplacés s'il en avait), ou l'``id`` d'un plugin."""
    version: str | None
    """Le texte de la version, ``$v`` compris ; ``None`` sans version."""
    location: Location | None
    """L'emplacement de la version dans le script, si elle y est écrite telle quelle."""
    scope: Scope
    interpolates: bool = False
    reason: str | None = None
    """Ce qui empêche de la lire : un ``groupId`` calculé…"""


@dataclass(frozen=True, kw_only=True)
class Script:
    """Un ``build.gradle`` ou ``build.gradle.kts`` lu."""

    path: str
    notations: tuple[Notation, ...]
    references: tuple[tuple[str, str, Scope], ...]
    """Les entrées du catalogue citées : section (``libraries``, ``plugins``, ``bundles``),
    accesseur (``spring.core``), scope."""
    variables: dict[str, Variable]
    expressions: tuple[str, ...] = field(default=())


def read_script(path: str, content: str) -> Script:
    """Un script Gradle, lu en jetons, sans l'exécuter."""
    return _read_script_once(path, content)


@functools.lru_cache(maxsize=64)
def _read_script_once(path: str, content: str) -> Script:
    reader = _ScriptReader(path, tokens(content))
    reader.run()
    return Script(
        path=path,
        notations=tuple(reader.notations),
        references=tuple(reader.references),
        variables=reader.variables,
    )


class _ScriptReader:
    def __init__(self, path: str, found: list[Token]) -> None:
        self.path = path
        self.tokens = found
        self.notations: list[Notation] = []
        self.references: list[tuple[str, str, Scope]] = []
        self.variables: dict[str, Variable] = {}
        self._conflicts: set[str] = set()

    def run(self) -> None:
        blocks: list[str] = []
        index = 0
        tokens_ = self.tokens
        while index < len(tokens_):
            token = tokens_[index]
            if token.kind == "op" and token.value == "{":
                previous = tokens_[index - 1] if index else None
                blocks.append(
                    previous.value if previous is not None and previous.kind == "ident" else ""
                )
            elif token.kind == "op" and token.value == "}":
                if blocks:
                    blocks.pop()
            if token.kind == "ident" and self._statement_start(index):
                index = self._statement(index, blocks)
                continue
            index += 1

    def _statement_start(self, index: int) -> bool:
        if index == 0:
            return True
        previous = self.tokens[index - 1]
        return previous.kind == "newline" or (previous.kind == "op" and previous.value in "{;}")

    def _at(self, index: int) -> Token | None:
        return self.tokens[index] if index < len(self.tokens) else None

    def _is(self, index: int, kind: str, value: str | None = None) -> bool:
        token = self._at(index)
        return token is not None and token.kind == kind and (value is None or token.value == value)

    def _statement(self, index: int, blocks: list[str]) -> int:
        """Lit une instruction qui commence par un identifiant ; rend l'index où reprendre."""
        token = self.tokens[index]
        name = token.value
        if name in ("id", "kotlin") and ("plugins" in blocks):
            return self._plugin(index)
        if name == "alias" and "plugins" in blocks:
            return self._plugin_alias(index)
        if is_configuration(name) and self._starts_arguments(index + 1):
            return self._dependency(index)
        return self._assignment(index, blocks)

    def _starts_arguments(self, index: int) -> bool:
        token = self._at(index)
        if token is None:
            return False
        return token.kind == "string" or (token.kind == "op" and token.value == "(") or (
            token.kind == "ident" and (token.value in _WRAPPERS or token.value == "libs"
                                       or self._is(index + 1, "op", ":"))
        )  # fmt: skip

    # -- arguments ---------------------------------------------------------

    def _arguments(self, index: int) -> tuple[list[list[Token]], int]:
        """Les arguments qui suivent ``index`` : entre parenthèses, ou jusqu'à la fin de
        l'instruction (Groovy) ; chacun en jetons. Rend aussi l'index après eux."""
        tokens_ = self.tokens
        parenthesized = self._is(index, "op", "(")
        if parenthesized:
            index += 1
        arguments: list[list[Token]] = [[]]
        depth = 0
        while index < len(tokens_):
            token = tokens_[index]
            if token.kind == "op" and token.value in "([{":
                depth += 1
            elif token.kind == "op" and token.value in ")]}":
                if depth == 0:
                    if parenthesized and token.value == ")":
                        index += 1
                    break
                depth -= 1
            elif depth == 0 and token.kind == "op" and token.value == ",":
                arguments.append([])
                index += 1
                continue
            elif (
                depth == 0
                and not parenthesized
                and (token.kind == "newline" or (token.kind == "op" and token.value == ";"))
                and arguments[-1]
            ):
                break  # la fin de l'instruction (Groovy) ; après une virgule, elle continue
            if token.kind != "newline":
                arguments[-1].append(token)
            index += 1
        return [argument for argument in arguments if argument], index

    def _dependency(self, index: int) -> int:
        configuration = self.tokens[index].value
        scope = configuration_scope(configuration)
        arguments, end = self._arguments(index + 1)
        before = len(self.notations)
        end = self._read_arguments(arguments, scope, end)
        if self._is(end, "op", "{") and len(self.notations) == before + 1:
            last = self.notations[-1]
            rich = self._rich_version(end)
            if last.version is None and last.reason is None and rich is not None:
                self.notations[-1] = dataclasses.replace(
                    last,
                    version=rich.value,
                    location=(
                        Location(line=rich.line, column=rich.column, end_column=rich.end_column)
                        if rich.plain and "$" not in rich.value
                        else None
                    ),
                    interpolates=rich.interpolates,
                )
        return end

    def _rich_version(self, start: int) -> Token | None:
        """La version riche du bloc qui commence à ``start`` (``{ version { strictly("v") }
        }``) : la première de ``strictly``, ``require``, ``prefer`` ; ``None`` sans."""
        depth = 0
        found: dict[str, Token] = {}
        in_version = 0
        index = start
        while index < len(self.tokens):
            token = self.tokens[index]
            if token.kind == "op" and token.value == "{":
                depth += 1
                if self._is(index - 1, "ident", "version"):
                    in_version = depth
            elif token.kind == "op" and token.value == "}":
                if depth == in_version:
                    in_version = 0
                depth -= 1
                if depth == 0:
                    break
            elif in_version and token.kind == "ident" and token.value in _RICH:
                value = (
                    self.tokens[index + 2]
                    if self._is(index + 1, "op", "(")
                    else self._at(index + 1)
                )
                if value is not None and value.kind == "string":
                    found.setdefault(token.value, value)
            index += 1
        return next((found[key] for key in _RICH if key in found), None)

    def _read_arguments(self, arguments: list[list[Token]], scope: Scope, end: int) -> int:
        named: dict[str, list[Token]] = {}
        for argument in arguments:
            if len(argument) >= 3 and argument[0].kind == "ident" and argument[1].kind == "op" and (
                argument[1].value in ":="
            ):  # fmt: skip
                named[argument[0].value] = argument[2:]
                continue
            self._argument(argument, scope)
        if "group" in named and "name" in named:
            self._named(named, scope)
        return end

    def _argument(self, argument: list[Token], scope: Scope) -> None:
        first = argument[0]
        if first.kind == "ident" and first.value in _WRAPPERS and len(argument) >= 3:
            inner = argument[2:-1] if argument[-1].value == ")" else argument[2:]
            if inner:
                self._argument(inner, scope)
            return
        if first.kind == "string" and len(argument) == 1:
            self._notation(first, scope)
            return
        if first.kind == "string" and argument[1].value == "+":
            parts = _split_notation(first.value)
            if len(parts) >= 2 and parts[0][0] and parts[1][0]:
                expression = " ".join(t.value if t.kind != "string" else f'"{t.value}"'
                                      for t in argument)  # fmt: skip
                self.notations.append(
                    Notation(
                        name=f"{parts[0][0]}:{parts[1][0]}",
                        version=None,
                        location=None,
                        scope=scope,
                        reason=REASON_EXPRESSION.format(expression=expression),
                    )
                )
            return
        accessor = _catalog_reference(argument)
        if accessor is not None:
            self.references.append((*accessor, scope))

    def _notation(self, token: Token, scope: Scope) -> None:
        """``"g:a:v"`` (et ``g:a:v:classifieur``, ``g:a:v@ext``)."""
        parts = _split_notation(token.value)
        if len(parts) < 2:
            return
        (group, _), (artifact, _) = parts[0], parts[1]
        if not group or not artifact:
            return
        version_text, offset = (
            (parts[2][0].split("@", 1)[0], parts[2][1]) if len(parts) > 2 else (None, 0)
        )
        location = None
        if version_text and token.plain and "$" not in version_text:
            location = Location(
                line=token.line,
                column=token.column + offset,
                end_column=token.column + offset + len(version_text),
            )
        self.notations.append(
            Notation(
                name=f"{group}:{artifact}",
                version=version_text or None,
                location=location,
                scope=scope,
                interpolates=token.interpolates,
            )
        )

    def _named(self, named: dict[str, list[Token]], scope: Scope) -> None:
        """``group: 'g', name: 'a', version: 'v'`` (Groovy), ``group = "g", …`` (Kotlin)."""
        values = {}
        for key in ("group", "name", "version"):
            tokens_ = named.get(key)
            if tokens_ and len(tokens_) == 1 and tokens_[0].kind == "string":
                values[key] = tokens_[0]
        group, artifact, version = values.get("group"), values.get("name"), values.get("version")
        if group is None or artifact is None:
            return
        location = None
        if version is not None and version.plain and "$" not in version.value:
            location = Location(
                line=version.line, column=version.column, end_column=version.end_column
            )
        self.notations.append(
            Notation(
                name=f"{group.value}:{artifact.value}",
                version=None if version is None else version.value,
                location=location,
                scope=scope,
                interpolates=version is not None and version.interpolates,
            )
        )

    # -- plugins -------------------------------------------------------------

    def _plugin(self, index: int) -> int:
        """``id("x") version "v"``, ``id 'x' version 'v'``, ``kotlin("jvm") version "v"``."""
        tokens_ = self.tokens
        kotlin = tokens_[index].value == "kotlin"
        cursor = index + 1
        parenthesized = self._is(cursor, "op", "(")
        if parenthesized:
            cursor += 1
        if not self._is(cursor, "string"):
            return index + 1
        identifier = tokens_[cursor].value
        cursor += 1
        if parenthesized:
            if not self._is(cursor, "op", ")"):
                return index + 1
            cursor += 1
        if self._is(cursor, "op", "."):
            cursor += 1
        if not self._is(cursor, "ident", "version"):
            return cursor
        cursor += 1
        wrapped = self._is(cursor, "op", "(")
        if wrapped:
            cursor += 1
        if not self._is(cursor, "string"):
            return cursor
        version = tokens_[cursor]
        name = f"org.jetbrains.kotlin.{identifier}" if kotlin else identifier
        location = None
        if version.plain and "$" not in version.value:
            location = Location(
                line=version.line, column=version.column, end_column=version.end_column
            )
        self.notations.append(
            Notation(
                name=name,
                version=version.value,
                location=location,
                scope=Scope.BUILD,
                interpolates=version.interpolates,
            )
        )
        return cursor + 1

    def _plugin_alias(self, index: int) -> int:
        """``alias(libs.plugins.x)``."""
        arguments, end = self._arguments(index + 1)
        for argument in arguments:
            accessor = _catalog_reference(argument)
            if accessor is not None:
                self.references.append((*accessor, Scope.BUILD))
        return end

    # -- variables ---------------------------------------------------------

    def _assignment(self, index: int, blocks: list[str]) -> int:
        """``val v = "…"``, ``def v = '…'``, ``ext.v = …``, ``extra["v"] = …``, ``val v by
        extra("…")``, ``v = …`` dans ``ext { }``."""
        tokens_ = self.tokens
        cursor = index
        shared = bool(blocks) and blocks[-1] in ("ext", "extra")
        while self._is(cursor, "ident") and tokens_[cursor].value in _MODIFIERS and (
            self._is(cursor + 1, "ident")
        ):  # fmt: skip
            cursor += 1
        while (
            self._is(cursor, "ident")
            and tokens_[cursor].value in ("project", "rootProject", "ext", "extra")
            and self._is(cursor + 1, "op", ".")
        ):
            shared = shared or tokens_[cursor].value in ("ext", "extra")
            cursor += 2
        name: str | None = None
        indexed = self._is(cursor, "ident", "extra") or self._is(cursor, "ident", "ext")
        if indexed and self._is(cursor + 1, "op", "[") and self._is(cursor + 2, "string") and (
            self._is(cursor + 3, "op", "]")
        ):  # fmt: skip
            name, cursor, shared = tokens_[cursor + 2].value, cursor + 4, True
        if name is None and self._is(cursor, "ident"):
            name = tokens_[cursor].value
            cursor += 1
            if self._is(cursor, "op", ":") and self._is(cursor + 1, "ident"):
                cursor += 2  # val v: String = …
        if name is None:
            return index + 1
        if self._is(cursor, "ident", "by") and self._is(cursor + 1, "ident", "extra"):
            if self._is(cursor + 2, "op", "(") and self._is(cursor + 3, "string") and self._is(
                cursor + 4, "op", ")"
            ):  # fmt: skip
                self._variable(name, tokens_[cursor + 3], shared=True)
                return cursor + 5
            return cursor
        if not (self._is(cursor, "op", "=") and not self._is(cursor + 1, "op", "=")):
            return index + 1
        value = self._at(cursor + 1)
        after = self._at(cursor + 2)
        ends = (
            after is None or after.kind == "newline" or (after.kind == "op" and after.value in ";}")
        )
        if value is not None and value.kind == "string" and ends:
            self._variable(name, value, shared=shared)
            return cursor + 2
        return cursor + 1

    def _variable(self, name: str, token: Token, *, shared: bool) -> None:
        plain = token.plain and "$" not in token.value if token.interpolates else token.plain
        location = None
        if plain:
            location = Location(line=token.line, column=token.column, end_column=token.end_column)
        variable = Variable(
            name=name, value=token.value if plain else None, file=self.path, location=location,
            shared=shared,
        )  # fmt: skip
        previous = self.variables.get(name)
        if previous is not None and previous.value != variable.value:
            self._conflicts.add(name)
            variable = Variable(name=name, value=None, file=self.path, location=None, shared=shared)
        if name in self._conflicts:
            variable = Variable(name=name, value=None, file=self.path, location=None, shared=shared)
        self.variables[name] = variable


def _split_notation(value: str) -> list[tuple[str, int]]:
    """Les parties d'une notation ``g:a:v``, séparées par ``:`` hors des ``${…}``, avec la colonne
    de chacune dans la chaîne."""
    parts = []
    start = 0
    depth = 0
    index = 0
    while index < len(value):
        if value.startswith("${", index):
            depth += 1
            index += 2
            continue
        char = value[index]
        if char == "}" and depth:
            depth -= 1
        elif char == ":" and not depth:
            parts.append((value[start:index], start))
            start = index + 1
        index += 1
    parts.append((value[start:], start))
    return parts


def _catalog_reference(argument: Sequence[Token]) -> tuple[str, str] | None:
    """``libs.spring.core`` (``.get()`` permis) : la section du catalogue et l'accesseur."""
    if not argument or argument[0].kind != "ident" or argument[0].value != "libs":
        return None
    names = []
    index = 1
    while (
        index + 1 < len(argument)
        and argument[index].value == "."
        and argument[index + 1].kind == "ident"
    ):
        names.append(argument[index + 1].value)
        index += 2
    if names and names[-1] == "get":
        names.pop()
    if not names:
        return None
    if names[0] in ("plugins", "bundles", "versions") and len(names) > 1:
        return names[0], ".".join(names[1:])
    return "libraries", ".".join(names)


# ---------------------------------------------------------------------------
# Les versions d'un script
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class _Version:
    value: str
    file: str
    location: Location | None
    reason: str | None = None


def _resolve(
    text: str, file: str, location: Location | None, variables: dict[str, Variable]
) -> _Version:
    """La version ``text`` d'une notation, ses ``$v`` remplacés par leur valeur (``variables``)."""
    references = list(_SIMPLE_REFERENCE.finditer(text))
    if not references:
        return _Version(value=text, file=file, location=location)
    names = []
    for match in references:
        expression = match.group(1) or match.group(2)
        simple = _OWNER.fullmatch(expression)
        if simple is None:
            return _Version(value=text, file=file, location=None,
                            reason=REASON_EXPRESSION.format(expression=match.group()))  # fmt: skip
        names.append((match, simple.group(1)))
    value = text
    for match, name in names:
        variable = variables.get(name)
        if variable is None or variable.value is None:
            return _Version(value=text, file=file, location=None,
                            reason=f"version dans une variable ({name}) non résolue")  # fmt: skip
        value = value.replace(match.group(), variable.value, 1)
    if len(names) == 1 and names[0][0].group() == text:
        variable = variables[names[0][1]]
        return _Version(value=value, file=variable.file, location=variable.location)
    return _Version(value=value, file=file, location=None)


def _dependency(
    name: str, version: _Version | None, scope: Scope, file: str, reason: str | None = None
) -> Dependency:
    if version is None:
        reason = reason or REASON_PLATFORM
    elif version.reason is not None:
        reason = reason or version.reason
    if reason is not None:
        return Dependency(ecosystem=Ecosystem.MAVEN, name=name,
                          constraint="" if version is None else version.value, scope=scope,
                          file=file, unverifiable_reason=reason)  # fmt: skip
    assert version is not None
    try:
        installed = MAVEN.exact(version.value)
    except InvalidConstraint:
        installed = None
    return Dependency(
        ecosystem=Ecosystem.MAVEN,
        name=name,
        constraint=version.value,
        installed=installed,
        scope=scope,
        file=version.file,
        location=version.location,
    )


def script_dependencies(script: Script, variables: dict[str, Variable]) -> list[Dependency]:
    """Les dépendances écrites dans ``script``, ses versions résolues avec ``variables``."""
    found = []
    for notation in script.notations:
        version = None
        if notation.version is not None:
            text = notation.version
            if notation.interpolates:
                version = _resolve(text, script.path, notation.location, variables)
            else:
                version = _Version(value=text, file=script.path, location=notation.location)
        found.append(
            _dependency(notation.name, version, notation.scope, script.path, notation.reason)
        )
    return found


def catalog_dependencies(
    catalog: Catalog, scopes: dict[tuple[str, str], Scope]
) -> list[Dependency]:
    """Les entrées du catalogue, avec le scope que leur donnent les scripts (``scopes``, par
    section et alias)."""
    found = []
    for entry in catalog.entries:
        default = Scope.BUILD if entry.section == "plugins" else Scope.RUNTIME
        scope = scopes.get((entry.section, entry.alias), default)
        version = None if entry.reason else _Version(
            value=entry.version, file=catalog.path, location=entry.location
        )  # fmt: skip
        found.append(_dependency(entry.name, version, scope, catalog.path, entry.reason))
    return found


# ---------------------------------------------------------------------------
# Un projet
# ---------------------------------------------------------------------------


def parse_gradle_project(
    directory: str,
    manifests: Iterable[str],
    read_text: ReadText,
    project_dirs: Sequence[str],
    notices: list[Notice],
) -> list[Dependency]:
    """Les dépendances Gradle du projet de dossier ``directory`` : son catalogue, puis ses
    scripts ; ajoute à ``notices`` ce qui n'a pas pu être lu."""
    manifests = list(manifests)
    found: list[Dependency] = []
    catalog_path = next((m for m in manifests if m.endswith(CATALOG)), None)
    catalog = _load_catalog(catalog_path, read_text, notices) if catalog_path else None
    scripts = [
        script
        for path in manifests
        if posixpath.basename(path) in (*SCRIPTS, *SETTINGS)
        and (script := _load_script(path, read_text, notices)) is not None
    ]
    for path in manifests:
        if posixpath.basename(path) in SETTINGS:
            for other in _other_catalogs(path, read_text, notices):
                loaded = _load_catalog(other, read_text, notices)
                if loaded is not None and other != catalog_path:
                    found.extend(catalog_dependencies(loaded, {}))
    if catalog is not None:
        scopes = _usage_scopes(catalog, directory, scripts, read_text, project_dirs)
        found.extend(catalog_dependencies(catalog, scopes))
    nearest = catalog or _nearest_catalog(directory, read_text)
    for script in scripts:
        variables = _variables(script, directory, read_text)
        found.extend(script_dependencies(script, variables))
        for section, accessor, _ in script.references:
            if section == "versions":
                continue
            if nearest is None or not nearest.accessor(section, accessor):
                notices.append(
                    Notice(
                        file=script.path,
                        message=f"« libs.{_prefix(section)}{accessor} » absent du catalogue "
                        f"{CATALOG} : pas vérifié.",
                    )
                )
    lockfile = _join(directory, LOCKFILE)
    try:
        locked = read_text(lockfile)
    except ValueError:
        locked = None
    if locked is not None:
        found = _with_locks(found, read_lockfile(locked), lockfile)
        notices.append(
            Notice(
                file=lockfile,
                message=(
                    "verrous de Gradle : lus pour les versions installées, mais pas régénérés "
                    "(Gradle exécute les scripts du projet, forceupdate ne le lance jamais). "
                    "Après une mise à jour, les refaire (gradle dependencies --write-locks), "
                    "sinon le build échoue."
                ),
            )
        )
    return found


def read_lockfile(content: str) -> dict[str, tuple[str, tuple[str, ...]]]:
    """Un ``gradle.lockfile`` : ``groupe:artefact`` → (version, configurations). Les lignes
    ``groupe:artefact:version=configurations`` ; ``empty=…`` et les commentaires sont sautés."""
    found = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        coordinates, _, configurations = line.partition("=")
        parts = coordinates.split(":")
        if len(parts) < 3 or not all(parts[:3]):
            continue
        names = tuple(c.strip() for c in configurations.split(",") if c.strip())
        found[f"{parts[0]}:{parts[1]}"] = (parts[2], names)
    return found


def _locked_scope(configurations: Sequence[str]) -> Scope:
    """Le scope d'une indirecte d'après ses configurations : seulement des tests, ``dev`` ;
    seulement le build (``kapt``, ``annotationProcessor``…), ``build`` ; ``runtime`` sinon."""
    scopes = {_classpath_scope(name) for name in configurations}
    if scopes == {Scope.DEV}:
        return Scope.DEV
    if scopes == {Scope.BUILD}:
        return Scope.BUILD
    return Scope.RUNTIME


def _classpath_scope(configuration: str) -> Scope:
    base = re.sub(r"(CompileClasspath|RuntimeClasspath|Classpath)$", "", configuration)
    return configuration_scope(base or "implementation")


def _with_locks(
    found: list[Dependency], locks: dict[str, tuple[str, tuple[str, ...]]], lockfile: str
) -> list[Dependency]:
    """Les directes avec leur version des verrous, puis les indirectes des verrous. Pas de
    ``Dependency.lockfile`` : forceupdate ne sait pas les régénérer."""
    directs = []
    for dependency in found:
        lock = locks.get(dependency.name)
        if lock is not None and dependency.unverifiable_reason is None:
            dependency = dataclasses.replace(dependency, installed=lock[0])
        directs.append(dependency)
    names = {d.name for d in found}
    indirects = [
        Dependency(
            ecosystem=Ecosystem.MAVEN,
            name=name,
            installed=version,
            direct=False,
            scope=_locked_scope(configurations),
            file=lockfile,
        )
        for name, (version, configurations) in sorted(locks.items())
        if name not in names
    ]
    return directs + indirects


_CATALOG_FROM = re.compile(
    r"""(?:create\s*\(\s*["'](?P<created>[\w-]+)["']\s*\)|(?P<named>[\w-]+))\s*\{\s*"""
    r"""from\s*\(?\s*(?:files\s*\(\s*["'](?P<file>[^"']+)["']|["'](?P<published>[^"']+)["'])"""
)


def _other_catalogs(settings: str, read_text: ReadText, notices: list[Notice]) -> list[str]:
    """Les catalogues que déclare ``settings`` (``versionCatalogs``), leurs chemins dans la
    source ; une remarque pour un catalogue publié, qui n'est pas lu."""
    try:
        content = read_text(settings)
    except ValueError:
        content = None
    if not content or "versionCatalogs" not in content:
        return []
    block = content[content.index("versionCatalogs") :]
    folder = posixpath.dirname(settings)
    found = []
    for match in _CATALOG_FROM.finditer(block):
        name = match.group("created") or match.group("named")
        if match.group("published"):
            notices.append(
                Notice(
                    file=settings,
                    message=(
                        f"catalogue « {name} » publié ({match.group('published')}) : pas lu par "
                        "forceupdate."
                    ),
                )
            )
            continue
        path = posixpath.normpath(posixpath.join(folder, match.group("file")))
        if not path.startswith(".."):
            found.append(path)
    return found


def _prefix(section: str) -> str:
    return "" if section == "libraries" else f"{section}."


def _load_catalog(path: str, read_text: ReadText, notices: list[Notice] | None) -> Catalog | None:
    try:
        content = read_text(path)
    except ValueError:
        content = None
    if content is None:
        if notices is not None:
            notices.append(
                Notice(file=path, message="introuvable, illisible ou trop gros : pas lu.")
            )
        return None
    try:
        return read_catalog(path, content)
    except ParseError as error:
        if notices is not None:
            notices.append(Notice(file=path, message=str(error)))
        return None


def _load_script(path: str, read_text: ReadText, notices: list[Notice] | None) -> Script | None:
    try:
        content = read_text(path)
    except ValueError:
        content = None
    if content is None:
        if notices is not None:
            notices.append(
                Notice(file=path, message="introuvable, illisible ou trop gros : pas lu.")
            )
        return None
    return read_script(path, content)


def _nearest_catalog(directory: str, read_text: ReadText) -> Catalog | None:
    """Le catalogue d'un dossier parent : celui de la racine du build, pour un sous-projet."""
    for ancestor in _ancestors(directory):
        catalog = _load_catalog(_join(ancestor, CATALOG), read_text, None)
        if catalog is not None:
            return catalog
    return None


def _usage_scopes(
    catalog: Catalog,
    directory: str,
    scripts: list[Script],
    read_text: ReadText,
    project_dirs: Sequence[str],
) -> dict[tuple[str, str], Scope]:
    """Le scope de chaque entrée du catalogue d'après les scripts qui la citent : ceux du projet
    et des sous-projets. ``dev`` si toutes ses citations le sont, ``build`` de même, ``runtime``
    sinon."""
    every = list(scripts)
    for other in project_dirs:
        if other != directory and _below(other, directory):
            for name in SCRIPTS:
                script = _load_script(_join(other, name), read_text, None)
                if script is not None:
                    every.append(script)
    seen: dict[tuple[str, str], set[Scope]] = {}
    for script in every:
        for section, accessor, scope in script.references:
            for entry in catalog.accessor(section, accessor):
                seen.setdefault((entry.section, entry.alias), set()).add(scope)
    return {
        key: scopes.pop() if len(scopes) == 1 else Scope.RUNTIME for key, scopes in seen.items()
    }


def _variables(script: Script, directory: str, read_text: ReadText) -> dict[str, Variable]:
    """Les variables que voit ``script`` : les siennes, puis les ``ext`` des scripts des dossiers
    parents, puis ``gradle.properties`` du projet et des dossiers parents (le plus proche
    l'emporte)."""
    found: dict[str, Variable] = {}
    for ancestor in reversed(_ancestors(directory)):
        properties = _properties_of(_join(ancestor, PROPERTIES), read_text)
        found.update(properties)
    found.update(_properties_of(_join(directory, PROPERTIES), read_text))
    for ancestor in reversed(_ancestors(directory)):
        for name in SCRIPTS:
            parent = _load_script(_join(ancestor, name), read_text, None)
            if parent is not None:
                found.update({k: v for k, v in parent.variables.items() if v.shared})
    found.update(script.variables)
    return found


def _properties_of(path: str, read_text: ReadText) -> dict[str, Variable]:
    try:
        content = read_text(path)
    except ValueError:
        content = None
    return {} if content is None else read_properties(path, content)


def _ancestors(directory: str) -> list[str]:
    """Les dossiers parents de ``directory``, du plus proche à la racine ``.``."""
    if directory == ".":
        return []
    parts = directory.split("/")
    return ["/".join(parts[:i]) for i in range(len(parts) - 1, 0, -1)] + ["."]


def _below(path: str, directory: str) -> bool:
    return directory == "." or path.startswith(f"{directory}/")


def _join(directory: str, name: str) -> str:
    return name if directory == "." else f"{directory}/{name}"
