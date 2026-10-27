"""L'interface commune des sources : ce que le moteur attend d'elles.

Une source dit d'où vient le code (``origin``), liste ses fichiers avec leur taille,
et lit ceux dont le moteur a besoin. Le reste (langages, projets, dépendances) ne
dépend pas de la source : le dossier local et le dépôt distant passent par les
mêmes étapes.
"""

from abc import ABC, abstractmethod
from typing import NamedTuple


class SourceError(Exception):
    """La source ne peut pas être analysée : chemin inexistant, dépôt inaccessible…

    Le message, en français, est fait pour être montré tel quel.
    """


class SourceFile(NamedTuple):
    """Un fichier de la source. C'est un ``(chemin, taille)``, ce qu'attend ``detect``."""

    path: str
    """Chemin POSIX, relatif à la racine de la source."""
    size: int
    """Taille en octets."""


class Source(ABC):
    """Une source de code à analyser."""

    origin: str
    """Ce qui a été choisi, pour le rapport : un chemin absolu, ou ``owner/repo``."""

    @abstractmethod
    def files(self) -> list[SourceFile]:
        """Les fichiers à analyser, triés par chemin.

        Sans ce qui n'est jamais parcouru (``node_modules``, ``.venv``… : voir
        ``detect.manifests.IGNORED_DIRS``), ni les liens symboliques.
        """

    @abstractmethod
    def read_text(self, path: str) -> str | None:
        """Le contenu d'un fichier de la source, ou ``None`` s'il est illisible ou trop gros."""
