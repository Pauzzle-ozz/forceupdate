"""Lire un document XML (``pom.xml``, ``maven-metadata.xml``) en arbre, avec la position du texte.

``xml.etree`` donne les éléments d'un document, pas leur position. Ce module le lit avec
``xml.parsers.expat`` (l'analyseur de ``xml.etree``, dans la bibliothèque standard) et note, pour
chaque élément, où commence et où finit son contenu. Le texte d'un élément feuille écrit tel
quel (``<version>1.2.3</version>``, sans entité, commentaire ni ``CDATA``) a alors un emplacement
exact (``Element.location``) : c'est ce qui permet de réécrire une version sans toucher au reste.

Les noms d'éléments sont gardés sans préfixe d'espace de noms (``<pom:version>`` donne
``version``) : un ``pom.xml`` déclare ``xmlns="http://maven.apache.org/POM/4.0.0"``, qu'on ignore.

**Un document qui a une DTD (``<!DOCTYPE …>``) est refusé** : une DTD peut définir des entités
qui s'étendent à l'infini (« billion laughs ») ou désignent un fichier ; un ``pom.xml`` n'en a
pas. Expat ne va jamais chercher d'entité externe sans qu'on le lui demande.
"""

import bisect
from collections.abc import Iterator
from dataclasses import dataclass, field
from xml.parsers import expat

from forceupdate.models import Location
from forceupdate.parsers.base import ParseError


@dataclass(eq=False)
class Element:
    """Un élément : son nom, ses attributs, ses enfants, son texte, et où il est écrit."""

    tag: str
    """Le nom, sans préfixe d'espace de noms."""
    attributes: dict[str, str]
    line: int
    """La ligne de ``<``, à partir de 1."""
    children: list["Element"] = field(default_factory=list)
    text: str = ""
    """Le texte écrit directement dans l'élément (hors enfants), sans les espaces autour."""
    location: Location | None = None
    """Pour un élément sans enfant : l'emplacement de son texte (sans les espaces autour), s'il
    est écrit tel quel sur une ligne. ``None`` sinon (vide, entité, ``CDATA``, commentaire,
    plusieurs lignes)."""

    def find(self, tag: str) -> "Element | None":
        """Le premier enfant de ce nom."""
        return next((child for child in self.children if child.tag == tag), None)

    def findall(self, tag: str) -> list["Element"]:
        """Les enfants de ce nom."""
        return [child for child in self.children if child.tag == tag]

    def child_text(self, tag: str) -> str | None:
        """Le texte du premier enfant de ce nom ; ``None`` s'il n'y en a pas."""
        child = self.find(tag)
        return None if child is None else child.text

    def path(self, *tags: str) -> Iterator["Element"]:
        """Les descendants au bout du chemin ``tags`` (``path("build", "plugins", "plugin")``)."""
        if not tags:
            yield self
            return
        for child in self.findall(tags[0]):
            yield from child.path(*tags[1:])


def parse(text: str) -> Element:
    """L'élément racine du document ``text``. Lève ``ParseError`` s'il est mal formé ou s'il a
    une DTD."""
    return _Builder(text).run()


class _Builder:
    def __init__(self, text: str) -> None:
        self.text = text
        self.data = text.encode("utf-8")
        self.ascii = len(self.data) == len(text)
        self.line_starts = [0] + [i + 1 for i, char in enumerate(text) if char == "\n"]
        self.stack: list[tuple[Element, int, list[str]]] = []
        """Les éléments ouverts : l'élément, l'octet de son ``<``, son texte en morceaux."""
        self.root: Element | None = None
        self.parser = expat.ParserCreate(encoding="utf-8")
        self.parser.StartElementHandler = self._start
        self.parser.EndElementHandler = self._end
        self.parser.CharacterDataHandler = self._characters
        self.parser.StartDoctypeDeclHandler = self._doctype
        self.parser.EntityDeclHandler = self._entity

    def run(self) -> Element:
        try:
            self.parser.Parse(self.data, True)
        except expat.ExpatError as error:
            raise ParseError(
                f"XML invalide ({expat.ErrorString(error.code)}, ligne {error.lineno})."
            ) from error
        if self.root is None:
            raise ParseError("XML invalide (aucun élément).")
        return self.root

    def _doctype(self, *_: object) -> None:
        raise ParseError("XML refusé : il déclare une DTD (<!DOCTYPE …>).")

    def _entity(self, *_: object) -> None:
        raise ParseError("XML refusé : il déclare une entité.")

    def _start(self, name: str, attributes: dict[str, str]) -> None:
        element = Element(
            tag=name.rsplit(":", 1)[-1],
            attributes=attributes,
            line=self.parser.CurrentLineNumber,
        )
        if self.stack:
            self.stack[-1][0].children.append(element)
        else:
            self.root = element
        self.stack.append((element, self.parser.CurrentByteIndex, []))

    def _characters(self, data: str) -> None:
        if self.stack:
            self.stack[-1][2].append(data)

    def _end(self, _name: str) -> None:
        element, start, pieces = self.stack.pop()
        element.text = "".join(pieces).strip()
        end = self.parser.CurrentByteIndex
        if element.children or not element.text or not self.data.startswith(b"</", end):
            return
        opened = self._tag_end(start)
        if opened < 0 or opened >= end:
            return
        raw = self.data[opened:end]
        if b"<" in raw or b"&" in raw:
            return  # entité, CDATA, commentaire : le texte écrit n'est pas la valeur
        lead = len(raw) - len(raw.lstrip())
        trail = len(raw.rstrip())
        first, last = self._char_offset(opened + lead), self._char_offset(opened + trail)
        line = bisect.bisect_right(self.line_starts, first)
        line_start = self.line_starts[line - 1]
        if "\n" in self.text[first:last]:
            return
        element.location = Location(
            line=line, column=first - line_start, end_column=last - line_start
        )

    def _tag_end(self, start: int) -> int:
        """L'octet qui suit le ``>`` de la balise ouvrante qui commence à ``start`` ; ``-1`` si
        on ne le trouve pas."""
        quote = None
        for index in range(start, len(self.data)):
            byte = self.data[index : index + 1]
            if quote is not None:
                if byte == quote:
                    quote = None
            elif byte in (b'"', b"'"):
                quote = byte
            elif byte == b">":
                return index + 1
        return -1

    def _char_offset(self, byte_offset: int) -> int:
        if self.ascii:
            return byte_offset
        return len(self.data[:byte_offset].decode("utf-8", errors="replace"))
