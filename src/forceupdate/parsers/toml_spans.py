"""Retrouver où sont écrites les chaînes d'un document TOML.

``tomllib`` donne les valeurs d'un document, pas leur position. Ce module parcourt
le texte d'un document que ``tomllib`` a déjà accepté, et rend, pour chaque chaîne
écrite sur une seule ligne, sa ligne et ses colonnes. C'est ce qui donne
l'emplacement exact d'une contrainte dans un ``pyproject.toml`` ou un ``Pipfile``,
pour la réécrire sans toucher au reste (E10).

Une chaîne est repérée par son chemin dans le document, le même que dans ce que
rend ``tomllib`` : des clés et des indices de tableaux. ``dependencies = ["a", "b"]``
dans ``[project]`` donne ``("project", "dependencies", 1)`` pour ``"b"`` ; le
troisième ``[[package]]`` d'un lockfile donne ``("package", 2, …)``.
"""

import bisect
import logging
from dataclasses import dataclass

from forceupdate.models import Location

logger = logging.getLogger(__name__)

TomlPath = tuple[str | int, ...]
"""Le chemin d'une valeur : clés et indices de tableaux, comme dans ``tomllib``."""

_BARE_KEY_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")
_ESCAPE_LENGTHS = {"u": 6, "U": 10, "x": 4}
"""Longueur écrite des échappements qui ne font pas deux caractères (``\\u00e9``…)."""
_SIMPLE_ESCAPES = {"b": "\b", "t": "\t", "n": "\n", "f": "\f", "r": "\r", "e": "\x1b"}


@dataclass(frozen=True)
class StringSpan:
    """Une chaîne TOML écrite sur une seule ligne, et sa position.

    Sert aussi aux chaînes JSON (``json_spans``) : leurs échappements sont ceux de
    TOML, plus les paires de substituts (``\\ud83d\\ude00``), qui font un seul caractère.
    """

    line: int
    """Sa ligne, à partir de 1."""
    column: int
    """Colonne du premier caractère après le guillemet ouvrant, à partir de 0."""
    raw: str
    """Le contenu tel qu'il est écrit, sans les guillemets (échappements compris)."""
    literal: bool
    """Vrai pour une chaîne littérale (``'…'``), qui n'a pas d'échappements."""

    def location(self, start: int, end: int) -> Location | None:
        """L'emplacement des caractères ``start`` à ``end`` (exclu) de la valeur décodée.

        ``None`` si ce morceau contient un échappement (``\\"``…) : le texte écrit
        n'y est pas la valeur, on ne saurait pas le réécrire.
        """
        offsets = self._offsets()
        if not 0 <= start <= end < len(offsets):
            return None
        first, last = offsets[start], offsets[end]
        if last - first != end - start:
            return None
        return Location(line=self.line, column=self.column + first, end_column=self.column + last)

    def _offsets(self) -> list[int]:
        """Pour chaque caractère de la valeur décodée, sa colonne dans ``raw`` ; plus la fin."""
        if self.literal:
            return list(range(len(self.raw) + 1))
        offsets = []
        index = 0
        while index < len(self.raw):
            offsets.append(index)
            if self.raw[index] == "\\":
                length = _ESCAPE_LENGTHS.get(self.raw[index + 1 : index + 2], 2)
                if length == 6 and _starts_surrogate_pair(self.raw, index):
                    length = 12
                index += length
            else:
                index += 1
        offsets.append(len(self.raw))
        return offsets


def _starts_surrogate_pair(raw: str, index: int) -> bool:
    """Vrai si ``raw[index:]`` commence par deux ``\\uXXXX`` qui forment une paire de
    substituts (JSON) : ``json`` les décode en un seul caractère."""
    if not raw.startswith("\\u", index + 6):
        return False
    try:
        high = int(raw[index + 2 : index + 6], 16)
        low = int(raw[index + 8 : index + 12], 16)
    except ValueError:
        return False
    return 0xD800 <= high <= 0xDBFF and 0xDC00 <= low <= 0xDFFF


def string_spans(text: str) -> dict[TomlPath, StringSpan]:
    """Les chaînes sur une ligne du document TOML ``text``, par chemin.

    ``text`` doit avoir été accepté par ``tomllib`` : il n'est pas revalidé. Les
    chaînes sur plusieurs lignes (``\"\"\"…\"\"\"``) ne sont pas rendues. Les lignes
    sont comptées sur ``\\n`` seulement, comme ``Location``.
    """
    scanner = _Scanner(text)
    try:
        scanner.document()
    except (IndexError, ValueError) as err:
        # Ne devrait pas arriver sur un document valide : on garde ce qui a été trouvé.
        logger.debug("TOML parcouru en partie seulement : %s", err)
    return scanner.spans


def decode_basic_string(raw: str) -> str:
    """Décode le contenu d'une chaîne TOML entre guillemets doubles (``\\"``, ``\\u00e9``…)."""
    chars = []
    index = 0
    while index < len(raw):
        char = raw[index]
        if char != "\\":
            chars.append(char)
            index += 1
            continue
        kind = raw[index + 1]
        if kind in _ESCAPE_LENGTHS:
            length = _ESCAPE_LENGTHS[kind]
            chars.append(chr(int(raw[index + 2 : index + length], 16)))
            index += length
        else:
            chars.append(_SIMPLE_ESCAPES.get(kind, kind))
            index += 2
    return "".join(chars)


class _Scanner:
    """Parcourt un document TOML valide et note la position des chaînes."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0
        self.spans: dict[TomlPath, StringSpan] = {}
        self._line_starts = [0] + [i + 1 for i, char in enumerate(text) if char == "\n"]
        self._array_tables: dict[TomlPath, int] = {}
        """Dernier indice de chaque tableau de tables (``[[package]]``)."""

    def document(self) -> None:
        table: TomlPath = ()
        while True:
            self._skip_blank()
            if self.pos >= len(self.text):
                return
            if self.text[self.pos] == "[":
                table = self._header()
            else:
                self._key_value(table)

    def _header(self) -> TomlPath:
        """Lit ``[a.b]`` ou ``[[a.b]]`` ; rend le chemin de la table ainsi ouverte."""
        self.pos += 1
        array = self.text[self.pos] == "["
        if array:
            self.pos += 1
        keys = self._key()
        self._skip_spaces()
        self.pos += 2 if array else 1
        path: TomlPath = ()
        for i, key in enumerate(keys):
            path = (*path, key)
            if array and i == len(keys) - 1:
                index = self._array_tables.get(path, -1) + 1
                self._array_tables[path] = index
                return (*path, index)
            if path in self._array_tables:
                path = (*path, self._array_tables[path])
        return path

    def _key_value(self, table: TomlPath) -> None:
        keys = self._key()
        self._skip_spaces()
        self.pos += 1  # le signe =
        self._skip_spaces()
        self._value((*table, *keys))

    def _key(self) -> list[str]:
        """Lit une clé, pointée ou non (``a."b c".d``)."""
        keys = []
        while True:
            self._skip_spaces()
            char = self.text[self.pos]
            if char == '"':
                start = self.pos + 1
                self._skip_basic_string()
                keys.append(decode_basic_string(self.text[start : self.pos - 1]))
            elif char == "'":
                start = self.pos + 1
                self.pos = self.text.index("'", start) + 1
                keys.append(self.text[start : self.pos - 1])
            else:
                start = self.pos
                while self.text[self.pos] in _BARE_KEY_CHARS:
                    self.pos += 1
                if self.pos == start:
                    raise ValueError(f"clé attendue à la position {start}")
                keys.append(self.text[start : self.pos])
            self._skip_spaces()
            if self.text[self.pos] != ".":
                return keys
            self.pos += 1

    def _value(self, path: TomlPath) -> None:
        char = self.text[self.pos]
        if self.text.startswith(('"""', "'''"), self.pos):
            self._skip_multiline_string()
        elif char == '"':
            start = self.pos + 1
            self._skip_basic_string()
            self._record(path, start, self.pos - 1, literal=False)
        elif char == "'":
            start = self.pos + 1
            self.pos = self.text.index("'", start) + 1
            self._record(path, start, self.pos - 1, literal=True)
        elif char == "[":
            self._array(path)
        elif char == "{":
            self._inline_table(path)
        else:
            # Nombre, booléen, date : on passe jusqu'au prochain séparateur.
            while self.pos < len(self.text) and self.text[self.pos] not in ",]}#\r\n":
                self.pos += 1

    def _array(self, path: TomlPath) -> None:
        self.pos += 1
        index = 0
        while True:
            self._skip_blank()
            if self.text[self.pos] == "]":
                self.pos += 1
                return
            self._value((*path, index))
            index += 1
            self._skip_blank()
            if self.text[self.pos] == ",":
                self.pos += 1

    def _inline_table(self, path: TomlPath) -> None:
        self.pos += 1
        while True:
            self._skip_blank()
            if self.text[self.pos] == "}":
                self.pos += 1
                return
            self._key_value(path)
            self._skip_blank()
            if self.text[self.pos] == ",":
                self.pos += 1

    def _skip_basic_string(self) -> None:
        """Avance après une chaîne ``"…"`` ; ``pos`` est sur le guillemet ouvrant."""
        index = self.pos + 1
        while self.text[index] != '"':
            index += 2 if self.text[index] == "\\" else 1
        self.pos = index + 1

    def _skip_multiline_string(self) -> None:
        quote = self.text[self.pos : self.pos + 3]
        index = self.pos + 3
        while not self.text.startswith(quote, index):
            index += 2 if quote == '"""' and self.text[index] == "\\" else 1
        index += 3
        # Jusqu'à deux guillemets de plus collés à la fin font partie du contenu.
        extra = 0
        while extra < 2 and index < len(self.text) and self.text[index] == quote[0]:
            index += 1
            extra += 1
        self.pos = index

    def _record(self, path: TomlPath, start: int, end: int, *, literal: bool) -> None:
        line = bisect.bisect_right(self._line_starts, start)
        self.spans[path] = StringSpan(
            line=line,
            column=start - self._line_starts[line - 1],
            raw=self.text[start:end],
            literal=literal,
        )

    def _skip_spaces(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos] in " \t":
            self.pos += 1

    def _skip_blank(self) -> None:
        """Passe les espaces, les fins de ligne et les commentaires."""
        while self.pos < len(self.text):
            char = self.text[self.pos]
            if char in " \t\r\n":
                self.pos += 1
            elif char == "#":
                end = self.text.find("\n", self.pos)
                self.pos = len(self.text) if end == -1 else end
            else:
                return
