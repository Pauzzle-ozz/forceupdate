"""Les versions : comparer, classer l'écart, tester une contrainte, un module par écosystème.

Les modèles gardent versions et contraintes en chaînes, telles qu'écrites. Pour les
interpréter, prendre les règles de l'écosystème avec ``for_ecosystem`` :

    scheme = for_ecosystem(Ecosystem.NPM)
    scheme.max_satisfying("^4.17.0", ["4.17.21", "5.0.0"])  # "4.17.21"
    scheme.gap("4.17.15", "5.0.0")  # Gap.MAJOR

PyPI et npm pour l'instant ; les autres écosystèmes arrivent avec leur étape (E21-E26),
chacun avec sa ``VersionScheme``.
"""

from typing import Any

from forceupdate.models import Ecosystem
from forceupdate.versions.base import Constraint, InvalidConstraint, InvalidVersion, VersionScheme
from forceupdate.versions.npm import NPM
from forceupdate.versions.pypi import PYPI

__all__ = [
    "Constraint",
    "InvalidConstraint",
    "InvalidVersion",
    "VersionScheme",
    "for_ecosystem",
]

_SCHEMES: dict[Ecosystem, VersionScheme[Any]] = {
    Ecosystem.PYPI: PYPI,
    Ecosystem.NPM: NPM,
}


def for_ecosystem(ecosystem: Ecosystem) -> VersionScheme[Any]:
    """Les règles de version de ``ecosystem`` ; ``LookupError`` s'il n'est pas encore géré."""
    try:
        return _SCHEMES[ecosystem]
    except KeyError:
        raise LookupError(f"versions {ecosystem} pas encore gérées par forceupdate.") from None
