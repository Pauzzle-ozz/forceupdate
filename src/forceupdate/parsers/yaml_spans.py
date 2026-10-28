"""Retrouver où sont écrits les scalaires d'un document YAML.

Comme ``toml_spans`` et ``json_spans`` : ``yaml.load`` donne les valeurs d'un document, pas
leur position. ``yaml.compose`` donne, pour chaque nœud, où il commence et où il finit dans le
texte ; ce module en tire, pour chaque scalaire écrit sur une ligne, sa ligne et ses colonnes.
C'est ce qui donne l'emplacement exact d'une plage d'un catalogue pnpm ou d'une version forcée
de ``pnpm-workspace.yaml``, pour la réécrire sans toucher au reste (E10).

Un scalaire est repéré par son chemin dans le document, le même que dans ce que rend
``yaml.load`` avec ``BaseLoader`` : des clés (des chaînes) et des indices de listes.
``catalog: {react: ^18.2.0}`` donne ``("catalog", "react")``.

Ne sont pas rendus, faute de savoir les réécrire sans risque :

- un scalaire sur plusieurs lignes (``|``, ``>``, ou replié sur la ligne suivante) ;
- un scalaire entre guillemets dont le texte n'est pas la valeur (un échappement ``\\"``, un
  ``''``) ;
- un nœud qu'un alias (``*ancre``) cite ailleurs : le réécrire changerait aussi l'autre endroit.
"""

import bisect
import logging
from collections import Counter

import yaml

from forceupdate.parsers.toml_spans import StringSpan

logger = logging.getLogger(__name__)

YamlPath = tuple[str | int, ...]
"""Le chemin d'une valeur : clés et indices de listes, comme dans ``yaml.load``."""

_LOADER = yaml.SafeLoader
"""Le chargeur écrit en Python. Ses positions (``Mark.index``) comptent des caractères, BOM
compris, comme ``Location`` ; celles de libyaml ne sont pas garanties. Seul son compositeur sert :
rien n'est construit."""


def string_spans(text: str) -> dict[YamlPath, StringSpan]:
    """Les scalaires sur une ligne du dernier document YAML de ``text``, par chemin (le dernier,
    comme ``parsers.npm`` lit un ``pnpm-lock.yaml`` à deux documents).

    ``text`` doit être un YAML valide : sinon, rien n'est rendu. Les lignes sont comptées sur
    ``\\n`` seulement, comme ``Location``.
    """
    try:
        documents = [node for node in yaml.compose_all(text, Loader=_LOADER) if node is not None]
    except yaml.YAMLError as err:
        logger.debug("YAML non parcouru : %s", err)
        return {}
    if not documents:
        return {}
    found: list[tuple[YamlPath, yaml.ScalarNode]] = []
    _walk(documents[-1], (), found, frozenset())
    uses = Counter(id(node) for _, node in found)
    line_starts = [0] + [i + 1 for i, char in enumerate(text) if char == "\n"]
    spans = {}
    for path, node in found:
        span = _span(text, line_starts, node) if uses[id(node)] == 1 else None
        if span is not None:
            spans[path] = span
    return spans


def _walk(
    node: yaml.Node,
    path: YamlPath,
    found: list[tuple[YamlPath, yaml.ScalarNode]],
    parents: frozenset[int],
) -> None:
    """Note les scalaires sous ``node``. ``parents`` : les nœuds traversés, contre un alias qui
    cite l'un d'eux (``&a [*a]``)."""
    if isinstance(node, yaml.ScalarNode):
        found.append((path, node))
        return
    if id(node) in parents:
        return
    inside = parents | {id(node)}
    if isinstance(node, yaml.MappingNode):
        for key, value in node.value:
            if isinstance(key, yaml.ScalarNode):
                _walk(value, (*path, key.value), found, inside)
    elif isinstance(node, yaml.SequenceNode):
        for index, item in enumerate(node.value):
            _walk(item, (*path, index), found, inside)


def _span(text: str, line_starts: list[int], node: yaml.ScalarNode) -> StringSpan | None:
    start, end = node.start_mark.index, node.end_mark.index
    if node.style in ("'", '"'):
        start, end = start + 1, end - 1  # sans les guillemets
    elif node.style is not None:
        return None  # bloc « | » ou « > »
    raw = text[start:end]
    if raw != node.value or "\n" in raw or (not raw and node.style is None):
        return None  # échappement, scalaire replié, ou valeur absente (« clé: »)
    line = bisect.bisect_right(line_starts, start)
    return StringSpan(line=line, column=start - line_starts[line - 1], raw=raw, literal=True)
