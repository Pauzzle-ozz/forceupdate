"""Les registres : ce que chacun dit d'un paquet (versions, dernière stable, dépréciation).

Un client par registre, derrière l'interface de ``base.py``. Pour une session :

    async with HttpClient() as http:
        registry = for_ecosystem(Ecosystem.NPM, http, Cache.default())
        info = await registry.package("lodash")  # PackageInfo
        info.latest  # "4.17.21"

PyPI et npm pour l'instant ; les autres registres arrivent avec leur étape (E21-E26).
"""

from forceupdate.models import Ecosystem
from forceupdate.net.cache import Cache
from forceupdate.net.http import HttpClient
from forceupdate.registries.base import (
    PackageInfo,
    PackageNotFound,
    PackageVersion,
    Registry,
    RegistryError,
)
from forceupdate.registries.npm import Npm
from forceupdate.registries.pypi import PyPI

__all__ = [
    "PackageInfo",
    "PackageNotFound",
    "PackageVersion",
    "Registry",
    "RegistryError",
    "for_ecosystem",
]

_REGISTRIES: dict[Ecosystem, type[Registry]] = {
    Ecosystem.PYPI: PyPI,
    Ecosystem.NPM: Npm,
}


def for_ecosystem(ecosystem: Ecosystem, http: HttpClient, cache: Cache) -> Registry:
    """Un client du registre de ``ecosystem``, pour la session ; ``LookupError`` s'il n'est pas
    encore géré.

    Garder l'instance pour toute la session : c'est elle qui fait qu'un paquet n'est demandé
    qu'une fois.
    """
    try:
        registry = _REGISTRIES[ecosystem]
    except KeyError:
        raise LookupError(f"registre {ecosystem} pas encore géré par forceupdate.") from None
    return registry(http, cache)
