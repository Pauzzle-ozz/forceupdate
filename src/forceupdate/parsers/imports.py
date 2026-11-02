"""Lire les imports d'un fichier de code, sans jamais l'exécuter ni l'importer (E28).

- **Python** : ``ast.parse`` seulement. ``import a.b`` et ``from a.b import c`` ; un import
  relatif (``from . import x``) n'est pas une dépendance. Un import gardé par un ``try`` qui
  rattrape ``ImportError`` (``ModuleNotFoundError``, ``Exception``, ou tout) est facultatif ; un
  import sous ``if TYPE_CHECKING:`` ne sert qu'aux annotations.
- **JavaScript et TypeScript** : un lexer, qui saute commentaires, chaînes, gabarits
  (``${…}`` imbriqués compris) et expressions régulières. ``import … from "x"``, ``import "x"``,
  ``import("x")``, ``export … from "x"``, ``require("x")`` (et ``import x = require("x")``) ; un
  ``import type`` ne sert qu'aux annotations. Une chaîne ordinaire s'arrête au bout de sa ligne :
  l'apostrophe d'un texte JSX (``<p>l'outil</p>``) ne mange pas la suite du fichier.
- **Go** : un lexer ; les déclarations ``import`` qui suivent ``package``, comme le veut la
  spécification (elles précèdent toutes les autres).

Ce module dit ce qui est importé, tel qu'écrit ; ``parsers.code`` en tire les paquets.
"""

import ast
import re
from collections.abc import Iterator
from typing import NamedTuple

from forceupdate.parsers.base import ParseError


class Import(NamedTuple):
    """Un import d'un fichier de code."""

    module: str
    """Ce qui est importé, tel qu'écrit : ``yaml``, ``google.cloud``, ``lodash/fp``,
    ``golang.org/x/text/language``."""
    line: int
    """Sa ligne, à partir de 1."""
    names: tuple[str, ...] = ()
    """Python : les noms de ``from module import a, b`` (des sous-modules, peut-être)."""
    optional: bool = False
    """Python : gardé par un ``try`` qui rattrape ``ImportError``."""
    types_only: bool = False
    """Seulement pour les annotations de types : ``if TYPE_CHECKING:``, ``import type``."""


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------

_IMPORT_ERRORS = frozenset({"ImportError", "ModuleNotFoundError", "Exception", "BaseException"})


def python_imports(content: str) -> list[Import]:
    """Les imports absolus d'un fichier Python, dans l'ordre du texte. Lève ``ParseError`` s'il
    ne se lit pas comme du Python (pour la version de Python qui fait tourner forceupdate)."""
    try:
        tree = ast.parse(content)
    except SyntaxError as err:
        line = f", ligne {err.lineno}" if err.lineno else ""
        raise ParseError(f"ne se lit pas comme du Python{line} : {err.msg}.") from err
    except ValueError as err:  # un octet nul
        raise ParseError(f"ne se lit pas comme du Python : {err}.") from err
    found: list[Import] = []
    _PythonVisitor(found).visit(tree)
    return sorted(found, key=lambda item: item.line)


class _PythonVisitor(ast.NodeVisitor):
    def __init__(self, found: list[Import]) -> None:
        self.found = found
        self.optional = 0
        self.types_only = 0

    def _add(self, module: str, line: int, names: tuple[str, ...] = ()) -> None:
        self.found.append(
            Import(
                module=module,
                line=line,
                names=names,
                optional=self.optional > 0,
                types_only=self.types_only > 0,
            )
        )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._add(alias.name, node.lineno)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level == 0 and node.module:
            self._add(node.module, node.lineno, tuple(a.name for a in node.names if a.name != "*"))

    def visit_Call(self, node: ast.Call) -> None:
        """``importlib.import_module("x")`` et ``__import__("x")`` d'un nom écrit (E34)."""
        if _name(node.func) in ("import_module", "__import__") and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                module = first.value.strip()
                if module and not module.startswith("."):
                    self._add(module, node.lineno)
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try | ast.TryStar) -> None:
        guarded = any(_catches_import_error(handler) for handler in node.handlers)
        self.optional += guarded
        for child in node.body:
            self.visit(child)
        for handler in node.handlers:
            self.visit(handler)
        self.optional -= guarded
        for child in (*node.orelse, *node.finalbody):
            self.visit(child)

    visit_TryStar = visit_Try

    def visit_If(self, node: ast.If) -> None:
        typing = _is_type_checking(node.test)
        self.visit(node.test)
        self.types_only += typing
        for child in node.body:
            self.visit(child)
        self.types_only -= typing
        for child in node.orelse:
            self.visit(child)


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    kinds = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(_name(kind) in _IMPORT_ERRORS for kind in kinds)


def _is_type_checking(test: ast.expr) -> bool:
    return _name(test) == "TYPE_CHECKING"


def _name(node: ast.expr) -> str | None:
    """Le nom d'une expression ``X`` ou ``module.X`` : ``X``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


# ---------------------------------------------------------------------------
# JavaScript, TypeScript
# ---------------------------------------------------------------------------


class _Token(NamedTuple):
    kind: str
    """``id`` (un identifiant ou un mot-clé), ``str`` (une chaîne), ``punct`` (un signe),
    ``other`` (un nombre, un gabarit, une expression régulière)."""
    value: str
    line: int


_REGEX_AFTER_PUNCT = frozenset("(,=:[!&|?{};+-*%<>~^")
"""Après ces signes, un ``/`` ouvre une expression régulière ; après le reste (``)``, ``]``,
``}``, un nom, un nombre, une chaîne), c'est une division."""
_REGEX_AFTER_WORDS = frozenset(
    {
        "return",
        "typeof",
        "instanceof",
        "in",
        "of",
        "new",
        "delete",
        "void",
        "throw",
        "case",
        "do",
        "else",
        "await",
        "yield",
    }
)
_SPACES = frozenset(" \t\r\f\v" + "".join(map(chr, (0xFEFF, 0xA0, 0x2028, 0x2029))))
_ID_CHAR = re.compile(r"[\w$" + chr(0x200C) + chr(0x200D) + "]")


def _js_tokens(text: str) -> Iterator[_Token]:
    """Les jetons significatifs d'un fichier JavaScript ou TypeScript (sans les commentaires)."""
    i = 0
    n = len(text)
    line = 1
    if text.startswith("#!"):  # la ligne « #!/usr/bin/env node »
        i = text.find("\n")
        i = n if i == -1 else i
    templates: list[int] = []
    """Pour chaque gabarit ouvert dans un ``${…}``, les accolades ouvertes depuis."""
    previous: _Token | None = None

    def emit(token: _Token) -> _Token:
        nonlocal previous
        previous = token
        return token

    while i < n:
        char = text[i]
        if char == "\n":
            line += 1
            i += 1
        elif char in _SPACES:
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end == -1 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end == -1 else end + 2
            line += text.count("\n", i, end)
            i = end
        elif char in "'\"":
            value, i = _js_string(text, i, char)
            yield emit(_Token("str", value, line))
        elif char == "`" or (char == "}" and templates and templates[-1] == 0):
            if char == "}":
                templates.pop()
            start_line = line
            i, line, opened = _js_template(text, i + 1, line)
            if opened:
                templates.append(0)
            yield emit(_Token("other", "`", start_line))
        elif char == "/" and _starts_regex(previous):
            i = _js_regex(text, i)
            yield emit(_Token("other", "/", line))
        elif char.isdigit():
            match = re.compile(r"[\w.]+").match(text, i)
            assert match is not None
            i = match.end()
            yield emit(_Token("other", match.group(), line))
        elif _ID_CHAR.match(char):
            start = i
            while i < n and _ID_CHAR.match(text[i]):
                i += 1
            yield emit(_Token("id", text[start:i], line))
        else:
            if templates:
                if char == "{":
                    templates[-1] += 1
                elif char == "}":
                    templates[-1] -= 1
            i += 1
            yield emit(_Token("punct", char, line))


def _starts_regex(previous: _Token | None) -> bool:
    if previous is None:
        return True
    if previous.kind == "punct":
        return previous.value in _REGEX_AFTER_PUNCT
    return previous.kind == "id" and previous.value in _REGEX_AFTER_WORDS


def _js_string(text: str, start: int, quote: str) -> tuple[str, int]:
    """La chaîne qui commence à ``start`` (son guillemet), et la position après elle. Elle
    s'arrête au bout de la ligne si elle n'est pas fermée."""
    i = start + 1
    chars = []
    while i < len(text):
        char = text[i]
        if char == quote:
            return "".join(chars), i + 1
        if char == "\n":
            return "".join(chars), i
        if char == "\\" and i + 1 < len(text):
            if text[i + 1] == "\n":
                i += 2
                continue
            chars.append(text[i + 1])
            i += 2
            continue
        chars.append(char)
        i += 1
    return "".join(chars), i


def _js_template(text: str, start: int, line: int) -> tuple[int, int, bool]:
    """Le texte d'un gabarit, à partir de ``start`` : la position après sa fin (`` ` ``) ou
    après un ``${``, la ligne où on en est, et si c'est un ``${`` qui s'ouvre."""
    i = start
    while i < len(text):
        char = text[i]
        if char == "\\":
            i += 2
            continue
        if char == "\n":
            line += 1
        elif char == "`":
            return i + 1, line, False
        elif text.startswith("${", i):
            return i + 2, line, True
        i += 1
    return i, line, False


def _js_regex(text: str, start: int) -> int:
    """La position après l'expression régulière qui commence à ``start`` (son ``/``), drapeaux
    compris ; au bout de la ligne si elle n'est pas fermée."""
    i = start + 1
    in_class = False
    while i < len(text):
        char = text[i]
        if char == "\\":
            i += 2
            continue
        if char == "\n":
            return i
        if char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        elif char == "/" and not in_class:
            i += 1
            while i < len(text) and _ID_CHAR.match(text[i]):
                i += 1
            return i
        i += 1
    return i


_STATEMENT_ENDS = frozenset({"import", "export", "const", "let", "var", "function", "class"})
_MAX_CLAUSE = 2000
"""Au plus autant de jetons entre ``import`` et son ``from``."""


def js_imports(content: str) -> list[Import]:
    """Les modules importés par un fichier JavaScript ou TypeScript, dans l'ordre du texte."""
    tokens = list(_js_tokens(content))
    found: list[Import] = []

    def at(index: int) -> _Token | None:
        return tokens[index] if 0 <= index < len(tokens) else None

    def punct(token: _Token | None, value: str) -> bool:
        return token is not None and token.kind == "punct" and token.value == value

    def word(token: _Token | None, value: str) -> bool:
        return token is not None and token.kind == "id" and token.value == value

    def string(token: _Token | None) -> bool:
        return token is not None and token.kind == "str"

    def from_clause(index: int) -> _Token | None:
        """La chaîne du ``from "x"`` qui suit ``index``, dans la même instruction."""
        for j in range(index, min(len(tokens) - 1, index + _MAX_CLAUSE)):
            token = tokens[j]
            if word(token, "from") and string(tokens[j + 1]):
                return tokens[j + 1]
            if punct(token, ";") or string(token):
                return None
            if j > index and token.kind == "id" and token.value in _STATEMENT_ENDS:
                return None
        return None

    for index, token in enumerate(tokens):
        if token.kind != "id" or punct(at(index - 1), "."):
            continue  # objet.import, objet.require : des propriétés
        after = at(index + 1)
        if token.value == "require":
            if punct(after, "(") and string(at(index + 2)) and punct(at(index + 3), ")"):
                found.append(Import(module=tokens[index + 2].value, line=token.line))
        elif token.value == "import":
            if punct(after, "("):
                target = at(index + 2)
                if string(target) and (punct(at(index + 3), ")") or punct(at(index + 3), ",")):
                    assert target is not None
                    found.append(Import(module=target.value, line=token.line))
            elif string(after):
                assert after is not None
                found.append(Import(module=after.value, line=token.line))
            elif after is not None and not punct(after, "."):
                types = word(after, "type") and not (
                    word(at(index + 2), "from") or punct(at(index + 2), ",")
                )
                source = from_clause(index + 1)
                if source is not None:
                    found.append(Import(module=source.value, line=token.line, types_only=types))
        elif token.value == "export":
            types = word(after, "type")
            first = at(index + 2) if types else after
            if punct(first, "*") or punct(first, "{"):
                source = from_clause(index + 1)
                if source is not None:
                    found.append(Import(module=source.value, line=token.line, types_only=types))
    return found


# ---------------------------------------------------------------------------
# Go
# ---------------------------------------------------------------------------


def _go_tokens(text: str) -> Iterator[_Token]:
    """Les jetons d'un fichier Go, sans les commentaires ni les espaces."""
    i = 0
    n = len(text)
    line = 1
    while i < n:
        char = text[i]
        if char == "\n":
            line += 1
            i += 1
        elif char.isspace():
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end == -1 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end == -1 else end + 2
            line += text.count("\n", i, end)
            i = end
        elif char == '"':
            value, i = _js_string(text, i, '"')
            yield _Token("str", value, line)
        elif char == "`":
            end = text.find("`", i + 1)
            end = n if end == -1 else end
            yield _Token("str", text[i + 1 : end], line)
            line += text.count("\n", i, end)
            i = end + 1
        elif char == "'":
            _, i = _js_string(text, i, "'")
            yield _Token("other", "'", line)
        elif char == "_" or char.isalpha():
            start = i
            while i < n and (text[i] == "_" or text[i].isalnum()):
                i += 1
            yield _Token("id", text[start:i], line)
        else:
            i += 1
            yield _Token("punct", char, line)


def go_imports(content: str) -> list[Import]:
    """Les chemins importés par un fichier Go (``import "fmt"``, ``import ( … )``), dans l'ordre.
    Lève ``ParseError`` si le fichier ne commence pas par ``package``."""
    tokens = list(_go_tokens(content))

    def at(index: int, kind: str, value: str | None = None) -> bool:
        if index >= len(tokens):
            return False
        token = tokens[index]
        return token.kind == kind and (value is None or token.value == value)

    if not (at(0, "id", "package") and at(1, "id")):
        raise ParseError("pas un fichier Go : il ne commence pas par « package ».")
    found: list[Import] = []

    def spec(index: int) -> int:
        """Lit ``[nom] "chemin"`` à ``index`` ; rend la position après, ou ``index`` sans spec."""
        if at(index, "id") or at(index, "punct", "."):
            index += 1  # le nom donné au paquet : « f », « . », « _ »
        if not at(index, "str"):
            return index
        found.append(Import(module=tokens[index].value, line=tokens[index].line))
        return index + 1

    index = 2
    while at(index, "punct", ";"):
        index += 1
    while at(index, "id", "import"):
        index += 1
        if at(index, "punct", "("):
            index += 1
            while index < len(tokens) and not at(index, "punct", ")"):
                after = spec(index)
                index = after + 1 if after == index else after  # un « ; » entre deux specs
            index += 1
        else:
            index = spec(index)
        while at(index, "punct", ";"):
            index += 1
    return found
