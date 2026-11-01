"""Les manifestes NuGet : les projets MSBuild (``*.csproj``, ``*.fsproj``, ``*.vbproj``),
``Directory.Packages.props``, ``Directory.Build.props`` et ``packages.config`` ; la version d'un
SDK de projet (``Sdk="Nom/Version"``, ``msbuild-sdks`` de ``global.json``, E27).

Une version NuGet se réécrit là où elle est écrite (``parsers.nuget``) : l'attribut ``Version``
(ou l'élément ``<Version>``) d'une ``PackageReference``, ``VersionOverride``, celui d'une
``PackageVersion`` centrale, la valeur de la propriété qu'il cite, ou l'attribut ``version`` d'un
``packages.config``. Pour qu'une telle réécriture se vérifie, chaque fichier relu seul redonne
ses versions (les propriétés citées résolues dans le fichier même), puis ses propriétés, chacune
avec son emplacement.
"""

import json

from forceupdate.parsers.base import ParseError
from forceupdate.parsers.json_spans import BOM
from forceupdate.parsers.nuget import (
    BUILD_PROPS,
    CENTRAL,
    GLOBAL_JSON,
    PACKAGES_CONFIG,
    PROJECTS,
    Properties,
    global_json_sdks,
    parse_packages_config,
    read_msbuild,
)
from forceupdate.update.writers.base import Declaration, Reader, dependencies


def read_msbuild_file(path: str, content: str) -> list[Declaration]:
    """Les versions des SDK de projet d'un fichier MSBuild lu seul (``Sdk="Nom/Version"``), puis
    ses versions (``Version``, ``VersionOverride``, les propriétés citées résolues dans le
    fichier), puis ses propriétés."""
    file = read_msbuild(path, content)
    properties = Properties(file.properties)
    found = [
        Declaration(
            identity=("sdk", sdk.name, str(index)),
            constraint=sdk.version or "",
            location=sdk.location,
        )
        for index, sdk in enumerate(file.sdks)
    ]
    for index, item in enumerate(file.items):
        for kind, version, location in (
            (item.kind, item.version, item.location),
            ("override", item.override, item.override_location),
        ):
            if version is None:
                continue
            resolved = properties.resolve(version, path, location)
            known = resolved.reason is None
            found.append(
                Declaration(
                    identity=("item", kind, item.name, str(index)),
                    constraint=resolved.value if known else version,
                    location=resolved.location if known else None,
                )
            )
    for index, item in enumerate(file.properties):
        found.append(
            Declaration(
                identity=("property", item.name, str(index)),
                constraint=item.value,
                location=item.location,
            )
        )
    return found


def read_packages_config(path: str, content: str) -> list[Declaration]:
    """Les paquets d'un ``packages.config``."""
    return dependencies(parse_packages_config(path, content))


def read_global_json(path: str, content: str) -> list[Declaration]:
    """Les versions de ``msbuild-sdks`` d'un ``global.json``. Lève ``ParseError`` s'il n'est plus
    du JSON."""
    try:
        json.loads(content.removeprefix(BOM))
    except ValueError as error:
        raise ParseError(f"JSON invalide ({error}).") from error
    return [
        Declaration(identity=("sdk", sdk.name), constraint=sdk.version or "", location=sdk.location)
        for sdk in global_json_sdks(path, content)
    ]


READERS: dict[str, Reader] = {
    **dict.fromkeys(PROJECTS, read_msbuild_file),
    CENTRAL: read_msbuild_file,
    PACKAGES_CONFIG: read_packages_config,
}
"""Le parseur qui relit chaque manifeste, par motif reconnu (``detect.manifests``) ;
``Directory.Build.props`` et ``global.json`` n'en sont pas : ``update.writers`` les reconnaît par
leur nom."""

__all__ = [
    "BUILD_PROPS",
    "GLOBAL_JSON",
    "READERS",
    "read_global_json",
    "read_msbuild_file",
    "read_packages_config",
]
