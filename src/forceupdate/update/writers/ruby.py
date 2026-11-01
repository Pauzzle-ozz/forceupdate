"""Les manifestes Ruby : ``Gemfile`` (``gems.rb``) et ``.gemspec``.

Une gem peut avoir plusieurs contraintes, une par chaîne : ``gem "nokogiri", ">= 1.19.0", "<
1.20"``. Le parseur les joint (``>= 1.19.0, < 1.20``, comme ``Gemfile.lock``), et leur emplacement
va du début de la première chaîne à la fin de la dernière : le texte écrit y est ``>= 1.19.0",
"< 1.20``. ``written_target`` passe de l'une à l'autre forme : la contrainte jointe d'une
réécriture devient le texte à écrire, chaque contrainte dans sa chaîne, avec les séparateurs du
fichier (``", "``) et ses guillemets. Une contrainte de plus (le plancher d'une faille) prend le
même séparateur ; une de moins (``= 1.19.4`` le temps d'une régénération) retire le sien.

À la relecture, une déclaration a pour contrainte ce texte écrit, guillemets intérieurs compris :
c'est ce que compare la vérification de ``update.writers``. Bundler ne touche pas au ``Gemfile``
ni au ``.gemspec`` pendant ``bundle lock`` (vérifié avec Bundler 4.0.20).
"""

import re

from forceupdate.models import Dependency
from forceupdate.parsers.ruby import parse_gemfile, parse_gemspec
from forceupdate.update.writers.base import Declaration, Reader, Refused, Target

_SEPARATOR = re.compile(r"""["']\s*,\s*["']""")
"""Ce qui sépare deux chaînes de contraintes sur une ligne : ``", "``, ``','``…"""


def _written(content: str, found: list[Dependency]) -> list[Declaration]:
    """Les déclarations, avec pour contrainte le texte écrit à leur emplacement."""
    return [
        Declaration(
            identity=("dependency", d.name, d.scope.value, d.unverifiable_reason),
            constraint=d.constraint if d.location is None else d.location.extract(content),
            location=d.location,
        )
        for d in found
    ]


def read_gemfile(path: str, content: str) -> list[Declaration]:
    """Les gems d'un ``Gemfile``, avec leurs contraintes telles qu'écrites."""
    return _written(content, parse_gemfile(path, content))


def read_gemspec(path: str, content: str) -> list[Declaration]:
    """Les dépendances d'un ``.gemspec``, avec leurs contraintes telles qu'écrites."""
    return _written(content, parse_gemspec(path, content))


def written_target(text: str, target: Target) -> Target:
    """``target``, dont ``old`` et ``new`` sont des contraintes jointes (``~> 2.2, >= 2.2.3``),
    avec le texte écrit à la place : les chaînes et leurs séparateurs (``~> 2.2", ">= 2.2.3``).
    Lève ``Refused`` si le texte à cet emplacement n'est pas ``old``."""
    lines = text.split("\n")
    location = target.location
    if location.line > len(lines):
        return target
    line = lines[location.line - 1].removesuffix("\r")
    raw = line[location.column : location.end_column]
    if raw == target.old and "," not in target.new:
        return target
    pieces = _SEPARATOR.split(raw)
    old = [part.strip() for part in target.old.split(",")]
    if [piece.strip() for piece in pieces] != old:
        raise Refused(
            f"{target.path} a changé depuis l'analyse : « {target.old} » n'est plus à la ligne "
            f"{location.line}."
        )
    separators = _SEPARATOR.findall(raw) or [_separator(line, location.column)]
    new = [part.strip() for part in target.new.split(",")]
    written = new[0]
    for index, part in enumerate(new[1:]):
        written += separators[min(index, len(separators) - 1)] + part
    return Target(path=target.path, location=location, old=raw, new=written, pattern=target.pattern)


def _separator(line: str, column: int) -> str:
    """Le séparateur d'une contrainte ajoutée à une chaîne seule : ``", "`` avec ses guillemets."""
    before = line[:column].rstrip()
    quote = before[-1] if before and before[-1] in "\"'" else '"'
    return f"{quote}, {quote}"


READERS: dict[str, Reader] = {
    "Gemfile": read_gemfile,
    "gems.rb": read_gemfile,
    "*.gemspec": read_gemspec,
}
"""Le parseur qui relit chaque manifeste, par motif reconnu (``detect.manifests``)."""

WRITTEN = {pattern: written_target for pattern in READERS}
"""Les formats dont une contrainte s'écrit autrement qu'elle ne se lit (``update.writers``)."""
