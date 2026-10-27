"""Retrouver où sont écrites les chaînes d'un document JSON.

``json`` donne les valeurs d'un document, pas leur position. Comme ``toml_spans``
pour TOML, ce module parcourt le texte d'un document que ``json.loads`` a déjà
accepté, et rend, pour chaque chaîne, sa ligne et ses colonnes. C'est ce qui donne
l'emplacement exact d'une contrainte dans un ``package.json`` (et plus tard un
``composer.json``, E23), pour la réécrire sans toucher au reste (E10).

Une chaîne est repérée par son chemin dans le document, le même que dans ce que
rend ``json.loads`` : des clés et des indices de tableaux.
``{"dependencies": {"lodash": "^4.17.21"}}`` donne ``("dependencies", "lodash")``.
Seules les valeurs sont rendues, pas les clés. Une clé écrite deux fois dans un
objet garde sa dernière valeur, comme avec ``json.loads``.
"""

import bisect
import json
import logging

from forceupdate.parsers.toml_spans import StringSpan

logger = logging.getLogger(__name__)

JsonPath = tuple[str | int, ...]
"""Le chemin d'une valeur : clés et indices de tableaux, comme dans ``json.loads``."""

BOM = "﻿"
"""L'indicateur d'ordre des octets qu'ajoutent certains éditeurs Windows en tête de
fichier. ``json.loads`` le refuse ; npm l'ignore."""


def string_spans(text: str) -> dict[JsonPath, StringSpan]:
    """Les chaînes du document JSON ``text``, par chemin.

    ``text`` doit avoir été accepté par ``json.loads`` (après avoir retiré un
    ``BOM`` de tête, qui compte quand même pour les colonnes de la ligne 1) : il
    n'est pas revalidé. Les lignes sont comptées sur ``\\n`` seulement, comme
    ``Location`` ; une chaîne JSON tient toujours sur une ligne.
    """
    scanner = _Scanner(text)
    try:
        scanner.value(())
    except (IndexError, ValueError) as err:
        # Ne devrait pas arriver sur un document valide : on garde ce qui a été trouvé.
        logger.debug("JSON parcouru en partie seulement : %s", err)
    return scanner.spans


class _Scanner:
    """Parcourt un document JSON valide et note la position des chaînes."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 1 if text.startswith(BOM) else 0
        self.spans: dict[JsonPath, StringSpan] = {}
        self._line_starts = [0] + [i + 1 for i, char in enumerate(text) if char == "\n"]

    def value(self, path: JsonPath) -> None:
        self._skip_blank()
        char = self.text[self.pos]
        if char == '"':
            start = self.pos + 1
            self._skip_string()
            self._record(path, start, self.pos - 1)
        elif char == "{":
            self._object(path)
        elif char == "[":
            self._array(path)
        else:
            # Nombre, true, false, null : on passe jusqu'au prochain séparateur.
            while self.pos < len(self.text) and self.text[self.pos] not in ",]} \t\r\n":
                self.pos += 1

    def _object(self, path: JsonPath) -> None:
        self.pos += 1
        while True:
            self._skip_blank()
            if self.text[self.pos] == "}":
                self.pos += 1
                return
            start = self.pos
            self._skip_string()
            key = json.loads(self.text[start : self.pos])
            self._skip_blank()
            self.pos += 1  # les deux-points
            self.value((*path, key))
            self._skip_blank()
            if self.text[self.pos] == ",":
                self.pos += 1

    def _array(self, path: JsonPath) -> None:
        self.pos += 1
        index = 0
        while True:
            self._skip_blank()
            if self.text[self.pos] == "]":
                self.pos += 1
                return
            self.value((*path, index))
            index += 1
            self._skip_blank()
            if self.text[self.pos] == ",":
                self.pos += 1

    def _skip_string(self) -> None:
        """Avance après une chaîne ``"…"`` ; ``pos`` est sur le guillemet ouvrant."""
        index = self.pos + 1
        while self.text[index] != '"':
            index += 2 if self.text[index] == "\\" else 1
        self.pos = index + 1

    def _record(self, path: JsonPath, start: int, end: int) -> None:
        line = bisect.bisect_right(self._line_starts, start)
        self.spans[path] = StringSpan(
            line=line,
            column=start - self._line_starts[line - 1],
            raw=self.text[start:end],
            literal=False,
        )

    def _skip_blank(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos] in " \t\r\n":
            self.pos += 1
