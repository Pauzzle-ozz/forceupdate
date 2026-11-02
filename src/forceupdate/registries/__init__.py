"""Les registres : ce que chacun dit d'un paquet (versions, dernière stable, dépréciation).

Un client par registre, derrière l'interface de ``base.py``. Pour une session :

    async with HttpClient() as http:
        registry = for_ecosystem(Ecosystem.NPM, http, Cache.default())
        info = await registry.package("lodash")  # PackageInfo
        info.latest  # "4.17.21"

PyPI, npm, crates.io, le proxy Go, Packagist, RubyGems, Maven (Maven Central, Google Maven, le
portail des plugins Gradle) et NuGet (nuget.org).
"""

from forceupdate.models import Ecosystem
from forceupdate.net.auth import Credentials
from forceupdate.net.cache import Cache
from forceupdate.net.http import HttpClient
from forceupdate.registries.base import (
    AccessRefused,
    PackageInfo,
    PackageNotFound,
    PackageVersion,
    Registry,
    RegistryError,
)
from forceupdate.registries.composer import ComposerRepository
from forceupdate.registries.crates import Crates
from forceupdate.registries.goproxy import GoProxy
from forceupdate.registries.maven import Maven
from forceupdate.registries.npm import Npm
from forceupdate.registries.nuget import NuGet, NuGetFeed
from forceupdate.registries.packagist import Packagist
from forceupdate.registries.pypi import PyPI, SimpleIndex
from forceupdate.registries.rubygems import GemServer, RubyGems

__all__ = [
    "AccessRefused",
    "PackageInfo",
    "PackageNotFound",
    "PackageVersion",
    "Registry",
    "RegistryError",
    "declared",
    "for_ecosystem",
]

_REGISTRIES: dict[Ecosystem, type[Registry]] = {
    Ecosystem.PYPI: PyPI,
    Ecosystem.NPM: Npm,
    Ecosystem.CRATES_IO: Crates,
    Ecosystem.GO: GoProxy,
    Ecosystem.PACKAGIST: Packagist,
    Ecosystem.RUBYGEMS: RubyGems,
    Ecosystem.MAVEN: Maven,
    Ecosystem.NUGET: NuGet,
}


def for_ecosystem(
    ecosystem: Ecosystem, http: HttpClient, cache: Cache, *, auth: Credentials | None = None
) -> Registry:
    """Un client du registre de ``ecosystem``, pour la session ; ``LookupError`` s'il n'est pas
    encore géré. ``auth`` : les identifiants de la personne (``net.auth``) ; seul un identifiant
    déclaré pour l'hôte du registre public part avec ses requêtes (un paquet privé hébergé sur
    npmjs.com).

    Garder l'instance pour toute la session : c'est elle qui fait qu'un paquet n'est demandé
    qu'une fois.
    """
    try:
        registry = _REGISTRIES[ecosystem]
    except KeyError:
        raise LookupError(f"registre {ecosystem} pas encore géré par forceupdate.") from None
    return registry(http, cache, auth=auth)


_DECLARED: dict[tuple[Ecosystem, str], type[Registry]] = {
    (Ecosystem.NPM, ""): Npm,
    (Ecosystem.GO, ""): GoProxy,
    (Ecosystem.MAVEN, ""): Maven,
    (Ecosystem.PACKAGIST, "composer"): ComposerRepository,
    (Ecosystem.NUGET, ""): NuGetFeed,
    (Ecosystem.PYPI, ""): SimpleIndex,
    (Ecosystem.RUBYGEMS, ""): GemServer,
    (Ecosystem.CRATES_IO, ""): Crates,
}
"""Les clients d'un registre déclaré (E33), par écosystème et sorte (``routing.Declared.kind``)."""


def declared(
    ecosystem: Ecosystem,
    http: HttpClient,
    cache: Cache,
    *,
    base_url: str,
    kind: str = "",
    auth: Credentials | None = None,
    label: str | None = None,
) -> Registry:
    """Un client du registre déclaré à ``base_url`` (``routing``, E33) ; ``LookupError`` si
    forceupdate ne sait pas le lire."""
    try:
        registry = _DECLARED[ecosystem, kind]
    except KeyError:
        raise LookupError(f"registre {ecosystem} « {kind} » pas géré par forceupdate.") from None
    return registry(http, cache, base_url=base_url, auth=auth, label=label)
