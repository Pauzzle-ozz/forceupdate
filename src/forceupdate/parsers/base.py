"""Ce qui est commun aux parseurs de tous les écosystèmes."""

from collections.abc import Callable

ReadText = Callable[[str], str | None]
"""Lit un fichier de la source par son chemin POSIX relatif : ``Source.read_text``.
Rend ``None`` si le fichier est illisible ou trop gros ; lève ``ValueError`` si le
chemin sort de la source."""

REASON_GIT = "dépendance git"
REASON_LOCAL = "chemin local"
REASON_URL = "téléchargée depuis une URL"
REASON_WORKSPACE = "membre du workspace"
"""Raisons courantes pour lesquelles une dépendance n'est pas vérifiable. Une raison ne
cite jamais l'URL ni le chemin : une URL peut contenir un token."""


class ParseError(ValueError):
    """Un fichier de dépendances ne peut pas être lu : TOML ou JSON invalide…

    Le message, en français, est fait pour être montré tel quel dans le rapport.
    """
