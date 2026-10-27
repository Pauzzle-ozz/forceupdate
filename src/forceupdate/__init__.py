"""forceupdate : trouve les dépendances à mettre à jour, et fait les mises à jour.

La version vient des métadonnées du paquet installé : elle n'est écrite qu'à un
seul endroit, dans ``pyproject.toml``.
"""

from importlib.metadata import version

__version__ = version("forceupdate")
