"""Lire un fichier Ruby (``Gemfile``, ``.gemspec``) en jetons, avec leur position, sans l'exécuter.

Un ``Gemfile`` est du Ruby : Bundler l'évalue. forceupdate ne lance jamais Ruby pour le lire ; il
découpe le texte en jetons (chaînes, symboles, identifiants, ponctuation), avec la ligne et les
colonnes de chacun, puis en instructions (``statements``). C'est ce qui donne l'emplacement exact
d'une contrainte (``gem "rack", "~> 2.2"``), pour la réécrire sans toucher au reste.

Ce qui est reconnu :

- les chaînes ``"…"``, ``'…'``, ``%q(…)``, ``%Q[…]``, ``%(…)`` et ``` `…` ``` ; une chaîne est
  « telle qu'écrite » (``Token.plain``) sans échappement ni ``#{…}`` : son texte est sa valeur ;
- les symboles (``:test``, ``:"x"``), les étiquettes de hachage (``require:``), les listes
  ``%w[…]`` et ``%i[…]``, les nombres, les identifiants (``respond_to?``) ;
- les commentaires (``#``, ``=begin`` … ``=end``), les heredocs (``<<~EOS``), dont le texte est
  sauté, et ``__END__``, après lequel rien n'est lu.

Les instructions sont séparées par les fins de ligne, sauf à l'intérieur de parenthèses, de
crochets ou d'accolades, après une virgule ou un opérateur, ou devant une ligne qui commence par
``.`` ; ``;`` en sépare aussi. Le reste du Ruby (une expression régulière, une division) donne des
jetons sans importance pour les dépendances.
"""

import bisect
import re
from dataclasses import dataclass

__all__ = ["Statement", "Token", "statements", "tokens"]

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*[?!]?")
_NUMBER = re.compile(r"\d[\d_]*(?:\.\d[\d_]*)?")
_HEREDOC = re.compile(r"<<([~-]?)(?:([\"'`])([A-Za-z_]\w*)\2|([A-Za-z_]\w*))")
_PERCENT = re.compile(r"%([wWiIqQrsx]?)([^\w\s])")
_FLAGS = re.compile(r"[a-z]*")
"""Les options d'une expression régulière (``/darwin/i``)."""
_PAIRS = {"(": ")", "[": "]", "{": "}", "<": ">"}
_OPERATORS = ("**=", "<=>", "===", "...", "::", "=>", "->", "==", "!=", "=~", "!~", ">=", "<=")
_OPERATORS += ("&&", "||", "&.", "<<", ">>", "+=", "-=", "*=", "/=", "||=", "&&=", "**", "..")
_CONTINUE = frozenset(
    {",", "\\", ".", "&.", "&&", "||", "=>", "->", "=", "+", "-", "*", "/", "?", ":", "::", "(",
     "[", "{", "==", "!=", "<", ">", "<=", ">=", "+=", "-=", "||=", "&&=", "<<", "**", "%", "!"}
)  # fmt: skip
"""Un jeton qui, en fin de ligne, fait continuer l'instruction sur la suivante."""
_VALUE_BEFORE = frozenset({"ident", "string", "symbol", "number", "words"})


@dataclass(frozen=True)
class Token:
    """Un jeton : sa sorte, sa valeur, et où il est écrit.

    Pour une chaîne, la position est celle de son contenu, sans les guillemets."""

    kind: str
    """``string``, ``symbol``, ``label``, ``words``, ``ident``, ``number``, ``op`` ou
    ``newline``."""
    value: str
    """Le texte d'un identifiant ou d'un opérateur ; la valeur d'une chaîne, d'un symbole, d'une
    étiquette (sans ``:``)."""
    line: int
    """Ligne du début du jeton, à partir de 1."""
    column: int
    """Colonne de son début (du contenu d'une chaîne), à partir de 0."""
    end_column: int
    """Colonne de sa fin, exclue, sur sa dernière ligne."""
    end_line: int = 0
    """Sa dernière ligne (0 : la même que ``line``)."""
    plain: bool = True
    """Pour une chaîne : écrite telle quelle, sur une ligne, sans échappement ni ``#{…}``."""
    words: tuple[str, ...] = ()
    """Les mots de ``%w[…]`` et ``%i[…]``."""
    quote: str = ""
    """Le délimiteur ouvrant d'une chaîne (``"``, ``'``, ``(`` pour ``%q(…)``)."""


@dataclass(frozen=True)
class Statement:
    """Une instruction : ses jetons, sans les fins de ligne."""

    tokens: tuple[Token, ...]

    @property
    def line(self) -> int:
        return self.tokens[0].line


class _Lexer:
    def __init__(self, text: str) -> None:
        self.text = text
        self.starts = [0] + [i + 1 for i, char in enumerate(text) if char == "\n"]
        self.found: list[Token] = []
        self.heredocs: list[tuple[str, bool]] = []

    def line_at(self, index: int) -> str:
        """Le texte de ``index`` à la fin de sa ligne."""
        newline = self.text.find("\n", index)
        return self.text[index : len(self.text) if newline < 0 else newline]

    def position(self, index: int) -> tuple[int, int]:
        line = bisect.bisect_right(self.starts, index)
        return line, index - self.starts[line - 1]

    def add(self, kind: str, value: str, start: int, end: int, **extra: object) -> None:
        line, column = self.position(start)
        end_line, end_column = self.position(end)
        token = Token(kind, value, line, column, end_column, end_line, **extra)  # type: ignore[arg-type]
        self.found.append(token)

    def run(self) -> list[Token]:
        text, i = self.text, 0
        while i < len(text):
            char = text[i]
            at_line_start = i == 0 or text[i - 1] == "\n"
            if at_line_start and text.startswith("=begin", i):
                end = re.compile(r"^=end\b.*$", re.MULTILINE).search(text, i)
                i = len(text) if end is None else end.end()
                continue
            if at_line_start and self.line_at(i).rstrip() == "__END__":
                break
            if char in " \t\r\f\v﻿":
                i += 1
            elif char == "\\" and text.startswith("\n", i + 1):
                i += 2
            elif char == "\n":
                self.add("newline", "\n", i, i)
                i = self.skip_heredocs(i + 1)
            elif char == "#":
                newline = text.find("\n", i)
                i = len(text) if newline < 0 else newline
            elif char in "\"'`":
                i = self.string(i + 1, char, char)
            elif char == "%" and self.value_expected() and (match := _PERCENT.match(text, i)):
                i = self.percent(match)
            elif char == ":" and text.startswith("::", i):
                self.add("op", "::", i, i + 2)
                i += 2
            elif char == ":" and i + 1 < len(text) and text[i + 1] in "\"'":
                start = len(self.found)
                i = self.string(i + 2, text[i + 1], text[i + 1])
                token = self.found[start]
                self.found[start] = Token("symbol", token.value, token.line, token.column - 2,
                                          token.end_column + 1, token.end_line)  # fmt: skip
            elif char == ":" and (match := _IDENT.match(text, i + 1)):
                self.add("symbol", match.group(), i, match.end())
                i = match.end()
            elif char == "<" and self.value_expected() and (match := _HEREDOC.match(text, i)):
                i = self.heredoc(match)
            elif char == "/" and self.value_expected():
                start = len(self.found)
                i = self.string(i + 1, "/", "/")
                token = self.found[start]  # une expression régulière : sans importance ici
                self.found[start] = Token("op", "/…/", token.line, token.column, token.end_column)
                i = _FLAGS.match(text, i).end()
            elif match := _IDENT.match(text, i):
                end = match.end()
                if text.startswith(":", end) and not text.startswith("::", end):
                    self.add("label", match.group(), i, end + 1)
                    i = end + 1
                else:
                    self.add("ident", match.group(), i, end)
                    i = end
            elif match := _NUMBER.match(text, i):
                self.add("number", match.group(), i, match.end())
                i = match.end()
            else:
                operator = next((op for op in _OPERATORS if text.startswith(op, i)), char)
                self.add("op", operator, i, i + len(operator))
                i += len(operator)
        return self.found

    def value_expected(self) -> bool:
        """Vrai si un ``%``, un ``<<`` ou un ``/`` ouvre ici un littéral, et n'est pas un
        opérateur (après une valeur, ``a % b``, ``list << x``, ``a / b``)."""
        if not self.found:
            return True
        previous = self.found[-1]
        if previous.kind == "op":
            return previous.value not in (")", "]", "}")
        return previous.kind not in _VALUE_BEFORE or previous.value in ("if", "unless", "when")

    def string(self, start: int, opening: str, closing: str) -> int:
        """Une chaîne dont le contenu commence à ``start`` ; rend l'index après sa fin."""
        text, i, depth = self.text, start, 0
        plain = True
        interpolates = opening in '"`' or opening in _PAIRS or opening in "|!/"
        while i < len(text):
            char = text[i]
            if char == "\\":
                plain = False
                i += 2
                continue
            if interpolates and text.startswith("#{", i):
                plain = False
                i = self.interpolation(i + 2)
                continue
            if char == "\n":
                plain = False
            if opening != closing and char == opening:
                depth += 1
            elif char == closing:
                if depth == 0:
                    break
                depth -= 1
            i += 1
        value = text[start:i]
        self.add("string", value, start, i, plain=plain, quote=opening)
        return i + 1

    def interpolation(self, start: int) -> int:
        """L'index après le ``}`` qui ferme un ``#{`` ouvert avant ``start``."""
        text, i, depth = self.text, start, 1
        while i < len(text) and depth:
            if text[i] in "\"'":
                quote, i = text[i], i + 1
                while i < len(text) and text[i] != quote:
                    i += 2 if text[i] == "\\" else 1
            elif text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        return i

    def percent(self, match: re.Match[str]) -> int:
        kind, opening = match.group(1), match.group(2)
        closing = _PAIRS.get(opening, opening)
        if kind in ("w", "W", "i", "I"):
            end = self.text.find(closing, match.end())
            end = len(self.text) if end < 0 else end
            words = tuple(self.text[match.end() : end].split())
            self.add("words", " ".join(words), match.start(), end + 1, words=words)
            return end + 1
        start = len(self.found)
        i = self.string(match.end(), opening, closing)
        if kind in ("r", "s", "x"):  # une expression régulière, un symbole, une commande
            token = self.found[start]
            self.found[start] = Token("op", "%" + kind, token.line, token.column, token.end_column)
        return i

    def heredoc(self, match: re.Match[str]) -> int:
        """``<<~EOS`` : un jeton chaîne vide ; le texte est sauté à la fin de la ligne."""
        name = match.group(3) or match.group(4)
        self.heredocs.append((name, bool(match.group(1))))
        self.add("string", "", match.start(), match.end(), plain=False, quote="<<")
        return match.end()

    def skip_heredocs(self, i: int) -> int:
        """Après une fin de ligne, saute le texte des heredocs ouverts sur cette ligne."""
        text = self.text
        for name, indented in self.heredocs:
            while i < len(text):
                newline = text.find("\n", i)
                line = text[i : len(text) if newline < 0 else newline]
                i = len(text) if newline < 0 else newline + 1
                if (line.strip() if indented else line.rstrip("\r")) == name:
                    break
        self.heredocs.clear()
        return i


def tokens(text: str) -> list[Token]:
    """Les jetons de ``text``, avec les fins de ligne (``newline``)."""
    return _Lexer(text).run()


def statements(text: str) -> list[Statement]:
    """Les instructions de ``text``, dans l'ordre."""
    found: list[Statement] = []
    current: list[Token] = []
    depth = 0
    all_tokens = tokens(text)
    for index, token in enumerate(all_tokens):
        if token.kind == "op" and token.value in ("(", "[", "{"):
            depth += 1
        elif token.kind == "op" and token.value in (")", "]", "}"):
            depth = max(depth - 1, 0)
        ends = token.kind == "newline" or (token.kind == "op" and token.value == ";")
        if not ends:
            current.append(token)
            continue
        following = next((t for t in all_tokens[index + 1 :] if t.kind != "newline"), None)
        chained = (
            following is not None and following.kind == "op" and following.value in (".", "&.")
        )
        last = current[-1] if current else None
        continues = last is not None and last.kind == "op" and last.value in _CONTINUE
        if token.kind == "newline" and (depth or continues or chained):
            continue
        if current:
            found.append(Statement(tuple(current)))
        current = []
    if current:
        found.append(Statement(tuple(current)))
    return found
