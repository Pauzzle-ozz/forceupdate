"""Le manifeste Go : ``go.mod`` (et ``go.work``), ses ``require`` et ses ``replace``.

Une version se réécrit là où elle est écrite : dans son ``require`` (directe, ou indirecte
``// indirect``), ou dans le ``replace`` qui la remplace par un autre module ou une autre
version. Le relecteur rend les deux, dans l'ordre du fichier : une réécriture ne doit changer que
le numéro visé.
"""

from forceupdate.parsers.go import parse_go_mod_file
from forceupdate.update.writers.base import Declaration, Reader


def read_go_mod(path: str, content: str) -> list[Declaration]:
    """Les versions d'un ``go.mod`` ou d'un ``go.work`` : ses ``require``, puis ses ``replace``
    vers un module."""
    parsed = parse_go_mod_file(path, content)
    requires = [
        Declaration(
            identity=("require", r.path, "indirect" if r.indirect else "direct"),
            constraint=r.version,
            location=r.location,
        )
        for r in parsed.requires
    ]
    replaces = [
        Declaration(
            identity=("replace", r.old_path, r.old_version, r.new_path),
            constraint=r.new_version,
            location=r.location,
        )
        for r in parsed.replaces
        if r.new_version is not None
    ]
    return requires + replaces


READERS: dict[str, Reader] = {"go.mod": read_go_mod, "go.work": read_go_mod}
"""Le parseur qui relit chaque manifeste, par motif reconnu (``detect.manifests``)."""
