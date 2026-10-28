"""Les fichiers npm : ``package.json`` (dépendances et versions forcées) et
``pnpm-workspace.yaml`` (catalogues et versions forcées de pnpm).

Une dépendance ``catalog:`` n'a pas d'emplacement dans son ``package.json`` : sa plage est dans
le ``pnpm-workspace.yaml`` le plus proche en remontant, celui que lit l'analyse
(``parsers.npm.nearest_pnpm_workspace``). ``catalog_target`` l'y retrouve, avec sa position
YAML ; une plage écrite sur plusieurs lignes ou avec un échappement n'est pas réécrite.
"""

from collections.abc import Iterable

from forceupdate.models import Dependency, Edit
from forceupdate.parsers.base import ParseError, ReadText
from forceupdate.parsers.lockfiles import dirname
from forceupdate.parsers.npm import (
    catalog_name,
    nearest_pnpm_workspace,
    parse_overrides,
    parse_package_json,
    parse_pnpm_workspace,
)
from forceupdate.update.writers.base import (
    Declaration,
    Reader,
    Refused,
    Target,
    dependencies,
    overrides,
)

PNPM_WORKSPACE = "pnpm-workspace.yaml"


def read_package_json(path: str, content: str) -> list[Declaration]:
    """Les dépendances d'un ``package.json``, puis ses versions forcées."""
    return dependencies(parse_package_json(path, content)) + overrides(
        parse_overrides(path, content)
    )


def read_pnpm_workspace(path: str, content: str) -> list[Declaration]:
    """Les entrées des catalogues d'un ``pnpm-workspace.yaml``, puis ses versions forcées."""
    workspace = parse_pnpm_workspace(path, content)
    catalogs = [
        Declaration(
            identity=("catalog", entry.catalog, entry.key, entry.name, entry.reason),
            constraint=entry.constraint,
            location=entry.location,
        )
        for entry in workspace.catalogs
    ]
    return catalogs + overrides(workspace.overrides)


READERS: dict[str, Reader] = {"package.json": read_package_json}
"""Le parseur qui relit chaque manifeste, par motif reconnu (``detect.manifests``).
``pnpm-workspace.yaml`` n'en est pas un : il est reconnu à son nom (``PNPM_WORKSPACE``)."""


def catalog_target(edit: Edit, dependencies: Iterable[Dependency], read_text: ReadText) -> Target:
    """La plage d'un catalogue pnpm à réécrire (``EditKind.CATALOG``), dans le
    ``pnpm-workspace.yaml`` du ``package.json`` de ``edit`` ; la dépendance qui y renvoie est
    parmi ``dependencies``. Lève ``Refused`` si on ne l'y trouve pas, ou si on ne sait pas la
    réécrire."""
    dependency = next(
        (
            d
            for d in dependencies
            if d.file == edit.file
            and d.resolved_constraint == edit.old
            and catalog_name(d.constraint) is not None
        ),
        None,
    )
    if dependency is None:
        raise Refused(f"{edit.file} : la dépendance en catalog: n'y est plus.")
    catalog = catalog_name(dependency.constraint)
    found = nearest_pnpm_workspace(dirname(edit.file), read_text)
    if found is None:
        raise Refused(
            f"aucun {PNPM_WORKSPACE} pour {edit.file} : la plage du catalogue est inconnue."
        )
    path, content = found
    try:
        workspace = parse_pnpm_workspace(path, content)
    except ParseError as err:
        raise Refused(f"{path} : {err}") from err
    entries = [
        entry
        for entry in workspace.catalogs
        if entry.catalog == catalog
        and entry.name == dependency.name
        and entry.constraint == edit.old
    ]
    if len(entries) > 1:  # deux alias du même paquet, avec la même plage
        entries = [entry for entry in entries if entry.key == dependency.name]
    if len(entries) != 1:
        raise Refused(
            f"{path} : « {edit.old} » ({dependency.name}) n'est plus dans le catalogue "
            f"« {catalog} »."
        )
    location = entries[0].location
    if location is None:
        raise Refused(
            f"{path} : la plage « {edit.old} » ({dependency.name}) est écrite sur plusieurs lignes "
            f"ou avec un échappement, à réécrire à la main en « {edit.new} »."
        )
    return Target(path=path, location=location, old=edit.old, new=edit.new)
