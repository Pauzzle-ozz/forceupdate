"""Le manifeste Rust : ``Cargo.toml``, ses dépendances et son ``[workspace.dependencies]``.

Une dépendance ``workspace = true`` n'a pas d'emplacement dans le ``Cargo.toml`` de son crate :
sa contrainte est dans ``[workspace.dependencies]`` du ``Cargo.toml`` à la racine du workspace,
celui que lit l'analyse (``parsers.rust.read_workspace_root``). ``workspace_target`` l'y
retrouve, comme la plage d'un catalogue pnpm (``EditKind.CATALOG``) ; une contrainte écrite sur
plusieurs lignes ou avec un échappement n'est pas réécrite.
"""

from collections.abc import Iterable

from forceupdate.models import Dependency, Edit
from forceupdate.parsers.base import ParseError, ReadText
from forceupdate.parsers.lockfiles import dirname
from forceupdate.parsers.rust import (
    WORKSPACE_CONSTRAINT,
    parse_cargo_toml,
    parse_workspace,
    read_workspace_root,
)
from forceupdate.update.writers.base import Declaration, Reader, Refused, Target, dependencies


def read_cargo_toml(path: str, content: str) -> list[Declaration]:
    """Les dépendances d'un ``Cargo.toml``, puis les entrées de son
    ``[workspace.dependencies]``."""
    workspace = parse_workspace(path, content)
    entries = [] if workspace is None else workspace.dependencies
    return dependencies(parse_cargo_toml(path, content)) + [
        Declaration(
            identity=("workspace", entry.key, entry.name, entry.reason),
            constraint=entry.constraint,
            location=entry.location,
        )
        for entry in entries
    ]


READERS: dict[str, Reader] = {"Cargo.toml": read_cargo_toml}
"""Le parseur qui relit chaque manifeste, par motif reconnu (``detect.manifests``)."""


def workspace_target(edit: Edit, dependencies: Iterable[Dependency], read_text: ReadText) -> Target:
    """La contrainte de ``[workspace.dependencies]`` à réécrire (``EditKind.CATALOG``), à la
    racine du workspace du ``Cargo.toml`` de ``edit`` ; la dépendance qui la reprend est parmi
    ``dependencies``. Lève ``Refused`` si on ne l'y trouve pas, ou si on ne sait pas la
    réécrire."""
    dependency = next(
        (
            d
            for d in dependencies
            if d.file == edit.file
            and d.resolved_constraint == edit.old
            and d.constraint == WORKSPACE_CONSTRAINT
        ),
        None,
    )
    if dependency is None:
        raise Refused(f"{edit.file} : la dépendance en workspace = true n'y est plus.")
    found = read_workspace_root(dirname(edit.file), read_text)
    if found is None:
        raise Refused(
            f"aucun workspace au-dessus de {edit.file} : la contrainte de « {dependency.name} » "
            "est inconnue."
        )
    path, content = found
    try:
        workspace = parse_workspace(path, content)
    except ParseError as err:
        raise Refused(f"{path} : {err}") from err
    entries = [
        entry
        for entry in (workspace.dependencies if workspace is not None else [])
        if entry.name == dependency.name and entry.constraint == edit.old
    ]
    if len(entries) > 1:  # deux clés pour le même crate, avec la même contrainte
        entries = [entry for entry in entries if entry.key == dependency.name]
    if len(entries) != 1:
        raise Refused(
            f"{path} : « {edit.old} » ({dependency.name}) n'est plus dans [workspace.dependencies]."
        )
    location = entries[0].location
    if location is None:
        raise Refused(
            f"{path} : la contrainte « {edit.old} » ({dependency.name}) est écrite sur plusieurs "
            f"lignes ou avec un échappement, à réécrire à la main en « {edit.new} »."
        )
    return Target(path=path, location=location, old=edit.old, new=edit.new)
