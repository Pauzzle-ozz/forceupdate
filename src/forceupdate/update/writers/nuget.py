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
import re
from collections.abc import Callable

from forceupdate.models import Edit, Location
from forceupdate.parsers.base import ParseError, ReadText
from forceupdate.parsers.json_spans import BOM
from forceupdate.parsers.nuget import (
    BUILD_PROPS,
    CENTRAL,
    GLOBAL_JSON,
    PACKAGES_CONFIG,
    PROJECTS,
    MsBuildFile,
    Properties,
    Property,
    central_management,
    global_json_sdks,
    parse_packages_config,
    read_msbuild,
)
from forceupdate.update.writers.base import Declaration, Reader, Refused, Target, dependencies


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


_PLAIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")
"""Un nom de paquet ou une version qui s'écrit tel quel dans un attribut XML."""

PINNING = "<CentralPackageTransitivePinningEnabled>true</CentralPackageTransitivePinningEnabled>"


def reference_targets(
    edit: Edit, name: str, raw: Callable[[str], str], read_text: ReadText
) -> list[Target]:
    """Les insertions qui font monter l'indirecte ``name`` à ``edit.new`` dans le projet
    ``edit.file`` (``EditKind.REFERENCE``, E32) : NuGet garde une indirecte à la plus basse version
    que demandent ceux qui la tirent ; une référence du projet passe devant.

    - sans gestion centrale : ``<PackageReference Include="x" Version="V" />`` dans le projet ;
    - avec : ``<PackageVersion Include="x" Version="V" />`` dans son ``Directory.Packages.props``,
      et ``CentralPackageTransitivePinningEnabled`` à ``true`` (sous la propriété
      ``ManagePackageVersionsCentrally``) s'il ne l'est pas : une version centrale vaut alors pour
      les indirectes ; si le projet l'a mis à ``false``, une ``PackageReference`` sans version
      dans le projet à la place.

    Chaque élément va après le dernier de sa sorte (``PackageReference``, ``PackageVersion``),
    à la même indentation, sinon dans un nouvel ``<ItemGroup>`` avant ``</Project>``.
    ``raw`` donne le texte tel quel d'un fichier (ses fins de ligne), ``read_text`` tel que le
    voient les parseurs. Lève ``Refused``."""
    version = edit.new
    if not (_PLAIN.fullmatch(name) and _PLAIN.fullmatch(version)):
        raise Refused(f"{name} {version} : ne s'écrit pas tel quel dans un projet MSBuild.")
    try:
        central = central_management(edit.file, read_text)
    except ParseError as err:
        raise Refused(f"{edit.file} : {err}") from err
    if not central.managed:
        reference = f'<PackageReference Include="{name}" Version="{version}" />'
        return [_after_items(edit.file, central.project, "reference", reference, (version,), raw)]
    if central.file is None or central.central is None:
        raise Refused(
            f"{edit.file} : gestion centrale sans {CENTRAL} au-dessus ; ajouter la version de "
            f"{name} à la main."
        )
    if any(i.kind == "central" and i.name.lower() == name.lower() for i in central.central.items):
        raise Refused(
            f"{central.file} a déjà une PackageVersion de {name} : y écrire {version} à la main."
        )
    entry = f'<PackageVersion Include="{name}" Version="{version}" />'
    targets = [_after_items(central.file, central.central, "central", entry, (version,), raw)]
    if central.pinning == "false":
        reference = f'<PackageReference Include="{name}" />'
        targets.append(_after_items(edit.file, central.project, "reference", reference, (), raw))
    elif central.pinning != "true":
        targets.append(_after_property(central.switch, PINNING, raw))
    return targets


def _after_items(
    path: str,
    file: MsBuildFile,
    kind: str,
    element: str,
    expects: tuple[str, ...],
    raw: Callable[[str], str],
) -> Target:
    """``element`` inséré après le dernier élément ``kind`` de ``file`` (hors condition), sinon
    dans un ``<ItemGroup>`` neuf avant ``</Project>``."""
    lines, newline = _lines(path, raw)
    anchors = [i for i in file.items if i.kind == kind and not i.conditional and i.end_line]
    if anchors:
        anchor = max(anchors, key=lambda item: item.end_line)
        indent = _indent(lines[anchor.line - 1])
        text = f"{indent}{element}{newline}"
        return _insertion(path, anchor.end_line + 1, text, expects, len(lines))
    unit = _unit(lines)
    text = f"{unit}<ItemGroup>{newline}{unit * 2}{element}{newline}{unit}</ItemGroup>{newline}"
    return _insertion(path, file.end_line, text, expects, len(lines))


def _after_property(switch: Property | None, element: str, raw: Callable[[str], str]) -> Target:
    """``element`` inséré après la propriété ``switch``, à la même indentation."""
    if switch is None or not switch.end_line:
        raise Refused(
            "ManagePackageVersionsCentrally introuvable : y ajouter "
            f"{element} à la main, à côté de lui."
        )
    lines, newline = _lines(switch.file, raw)
    text = f"{_indent(lines[switch.line - 1])}{element}{newline}"
    return _insertion(switch.file, switch.end_line + 1, text, ("true",), len(lines))


def _insertion(path: str, line: int, text: str, expects: tuple[str, ...], count: int) -> Target:
    if not 1 <= line <= count:
        raise Refused(f"{path} : pas de ligne où ajouter « {text.strip()} » ; à faire à la main.")
    return Target(
        path=path,
        location=Location(line=line, column=0, end_column=0),
        old="",
        new=text,
        insert=True,
        expects=expects,
    )


def _lines(path: str, raw: Callable[[str], str]) -> tuple[list[str], str]:
    """Les lignes de ``path`` telles quelles (sans le BOM), et sa fin de ligne."""
    text = raw(path)
    return text.removeprefix(BOM).split("\n"), "\r\n" if "\r\n" in text else "\n"


def _indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _unit(lines: list[str]) -> str:
    """L'indentation d'un niveau dans le fichier : celle de la première ligne indentée (deux
    espaces sinon)."""
    found = next((_indent(line) for line in lines if line.strip() and _indent(line)), "")
    return found or "  "


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
    "PINNING",
    "READERS",
    "read_global_json",
    "read_msbuild_file",
    "read_packages_config",
    "reference_targets",
]
