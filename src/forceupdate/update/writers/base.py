"""Ce qui est commun aux formats : une réécriture située, une déclaration relue, et le refus."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from forceupdate.models import Dependency, Location, Override


class Refused(Exception):
    """Une réécriture qu'on ne fait pas : fichier changé depuis l'analyse, illisible, qui ne se
    relit plus… Le message, en français, est fait pour être montré tel quel."""


@dataclass(frozen=True, kw_only=True)
class Target:
    """Une réécriture située : à ``location`` de ``path``, ``old`` devient ``new``."""

    path: str
    """Le fichier, relatif à la racine de la source (le ``pnpm-workspace.yaml`` d'un
    catalogue)."""
    location: Location
    old: str
    new: str


@dataclass(frozen=True, kw_only=True)
class Declaration:
    """Une contrainte d'un fichier, telle que son parseur la lit."""

    identity: tuple[str | None, ...]
    """Ce qui ne change pas quand on la réécrit : sa sorte, le paquet, son scope…"""
    constraint: str
    location: Location | None


Reader = Callable[[str, str], list[Declaration]]
"""Relit un fichier : son chemin, et son contenu tel que le voient les parseurs (lignes sur
``\\n``). Lève ``ParseError`` s'il est invalide."""

Check = Callable[[str, str, Target], None]
"""Ce qu'un format vérifie de plus avant une réécriture (son chemin, son contenu, la
réécriture) : lève ``Refused`` si elle casserait autre chose que la contrainte."""


def dependencies(found: Iterable[Dependency]) -> list[Declaration]:
    """Les déclarations de dépendances lues par un parseur de manifeste."""
    return [
        Declaration(
            identity=("dependency", d.name, d.scope.value, d.unverifiable_reason),
            constraint=d.constraint,
            location=d.location,
        )
        for d in found
    ]


def overrides(found: Iterable[Override]) -> list[Declaration]:
    """Les versions forcées lues par un parseur."""
    return [
        Declaration(
            identity=("override", o.section, o.key, o.name),
            constraint=o.constraint,
            location=o.location,
        )
        for o in found
    ]
