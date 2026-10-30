"""Le manifeste PHP : ``composer.json``, ses ``require`` et ``require-dev``.

Une contrainte se réécrit là où elle est écrite, dans sa chaîne JSON ; une chaîne qui a un
échappement (``\\u…``) n'a pas d'emplacement, et n'est pas réécrite. Composer ne touche jamais au
``composer.json`` pendant ``composer update`` (vérifié avec Composer 2.11) : la mise en forme reste
celle du fichier.
"""

from forceupdate.parsers.php import parse_composer_json
from forceupdate.update.writers.base import Declaration, Reader, dependencies


def read_composer_json(path: str, content: str) -> list[Declaration]:
    """Les dépendances d'un ``composer.json``, sans les paquets « plateforme »."""
    return dependencies(parse_composer_json(path, content))


READERS: dict[str, Reader] = {"composer.json": read_composer_json}
"""Le parseur qui relit chaque manifeste, par motif reconnu (``detect.manifests``)."""
