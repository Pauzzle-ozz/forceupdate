"""Les manifestes NuGet : les projets MSBuild (``*.csproj``, ``*.fsproj``, ``*.vbproj``),
``Directory.Packages.props``, ``Directory.Build.props`` et ``packages.config``.

Une version NuGet se réécrit là où elle est écrite (``parsers.nuget``) : l'attribut ``Version``
(ou l'élément ``<Version>``) d'une ``PackageReference``, ``VersionOverride``, celui d'une
``PackageVersion`` centrale, la valeur de la propriété qu'il cite, ou l'attribut ``version`` d'un
``packages.config``. Pour qu'une telle réécriture se vérifie, chaque fichier relu seul redonne
ses versions (les propriétés citées résolues dans le fichier même), puis ses propriétés, chacune
avec son emplacement.
"""

from forceupdate.parsers.nuget import (
    BUILD_PROPS,
    CENTRAL,
    PACKAGES_CONFIG,
    PROJECTS,
    Properties,
    parse_packages_config,
    read_msbuild,
)
from forceupdate.update.writers.base import Declaration, Reader, dependencies


def read_msbuild_file(path: str, content: str) -> list[Declaration]:
    """Les versions d'un fichier MSBuild lu seul (``Version``, ``VersionOverride``, les
    propriétés citées résolues dans le fichier), puis ses propriétés."""
    file = read_msbuild(path, content)
    properties = Properties(file.properties)
    found = []
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


READERS: dict[str, Reader] = {
    **dict.fromkeys(PROJECTS, read_msbuild_file),
    CENTRAL: read_msbuild_file,
    PACKAGES_CONFIG: read_packages_config,
}
"""Le parseur qui relit chaque manifeste, par motif reconnu (``detect.manifests``) ;
``Directory.Build.props`` n'en est pas un : ``update.writers`` le reconnaît par son nom."""

__all__ = ["BUILD_PROPS", "READERS", "read_msbuild_file", "read_packages_config"]
