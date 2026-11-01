"""Lire un script Gradle (``build.gradle`` en Groovy, ``build.gradle.kts`` en Kotlin) en jetons,
avec leur position, sans l'exécuter.

Un script Gradle est un programme : Gradle l'exécute pour connaître les dépendances. forceupdate
ne lance jamais Gradle pour le lire ; il découpe le texte en jetons (chaînes, identifiants,
nombres, ponctuation, fins de ligne), avec la ligne et les colonnes de chacun. C'est ce qui donne
l'emplacement exact d'une version (``implementation("g:a:1.2.3")``), pour la réécrire sans toucher
au reste.

Ce qui est reconnu : les chaînes ``'…'``, ``"…"``, ``'''…'''`` et ``\"\"\"…\"\"\"`` (le texte
écrit est gardé tel quel : ``Token.value``) ; les commentaires ``//`` et ``/* … */`` ; les
identifiants, les nombres, la ponctuation. Une chaîne entre ``"`` peut citer des variables
(``"g:a:$v"``, ``"${v}"``) : ``Token.interpolates`` le dit. Le reste du langage (une expression
régulière ``/…/`` de Groovy, une division) donne des jetons sans importance pour les dépendances.
"""

import bisect
import re
from dataclasses import dataclass

__all__ = ["Token", "tokens"]

_IDENT = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_NUMBER = re.compile(r"\d[\d_]*(?:\.\d[\d_]*)?[A-Za-z]*")


@dataclass(frozen=True)
class Token:
    """Un jeton : sa sorte, sa valeur, et où il est écrit.

    Pour une chaîne, la position est celle de son contenu, sans les guillemets."""

    kind: str
    """``string``, ``ident``, ``number``, ``op`` ou ``newline``."""
    value: str
    """Le texte d'un identifiant, d'un nombre ou d'un opérateur ; le contenu d'une chaîne tel
    qu'écrit."""
    line: int
    """Ligne du début du jeton (du contenu d'une chaîne), à partir de 1."""
    column: int
    end_column: int
    """Colonne de sa fin, exclue, sur sa dernière ligne."""
    plain: bool = True
    """Pour une chaîne : sur une ligne, sans échappement ; son texte est sa valeur, colonne pour
    colonne (des ``$`` compris, voir ``interpolates``)."""
    interpolates: bool = False
    """Pour une chaîne : entre ``"`` ou ``\"\"\"``, où ``$nom`` et ``${…}`` citent des variables."""


class _Lexer:
    def __init__(self, text: str) -> None:
        self.text = text
        self.starts = [0] + [i + 1 for i, char in enumerate(text) if char == "\n"]
        self.found: list[Token] = []

    def position(self, index: int) -> tuple[int, int]:
        line = bisect.bisect_right(self.starts, index)
        return line, index - self.starts[line - 1]

    def add(self, kind: str, value: str, start: int, end: int, **extra: bool) -> None:
        line, column = self.position(start)
        _, end_column = self.position(end)
        self.found.append(Token(kind, value, line, column, end_column, **extra))

    def run(self) -> list[Token]:
        text, i = self.text, 0
        while i < len(text):
            char = text[i]
            if char in " \t\r\f\v﻿":
                i += 1
            elif char == "\\" and text.startswith("\n", i + 1):
                i += 2
            elif char == "\n":
                self.add("newline", "\n", i, i)
                i += 1
            elif text.startswith("//", i):
                newline = text.find("\n", i)
                i = len(text) if newline < 0 else newline
            elif text.startswith("/*", i):
                end = text.find("*/", i + 2)
                i = len(text) if end < 0 else end + 2
            elif text.startswith(('"""', "'''"), i):
                i = self.string(i + 3, text[i : i + 3])
            elif char in "\"'":
                i = self.string(i + 1, char)
            elif match := _IDENT.match(text, i):
                self.add("ident", match.group(), i, match.end())
                i = match.end()
            elif match := _NUMBER.match(text, i):
                self.add("number", match.group(), i, match.end())
                i = match.end()
            else:
                self.add("op", char, i, i + 1)
                i += 1
        return self.found

    def string(self, start: int, quote: str) -> int:
        """Une chaîne dont le contenu commence à ``start`` ; rend l'index après sa fin."""
        text, i = self.text, start
        plain = True
        interpolates = quote.startswith('"')
        while i < len(text):
            if text.startswith(quote, i):
                break
            char = text[i]
            if char == "\\" and quote != '"""':
                plain = False
                i += 2
                continue
            if interpolates and text.startswith("${", i):
                i = self.interpolation(i + 2)
                continue
            if char == "\n":
                plain = False
                if len(quote) == 1:
                    break  # une chaîne simple non fermée s'arrête à la fin de la ligne
            i += 1
        self.add("string", text[start:i], start, i, plain=plain, interpolates=interpolates)
        return i + len(quote)

    def interpolation(self, start: int) -> int:
        """L'index après le ``}`` qui ferme un ``${`` ouvert avant ``start``."""
        text, i, depth = self.text, start, 1
        while i < len(text) and depth:
            if text[i] in "\"'":
                quote, i = text[i], i + 1
                while i < len(text) and text[i] != quote and text[i] != "\n":
                    i += 2 if text[i] == "\\" else 1
            elif text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        return i


def tokens(text: str) -> list[Token]:
    """Les jetons de ``text``, avec les fins de ligne (``newline``)."""
    return _Lexer(text).run()
