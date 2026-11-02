"""Le npm qu'attend un projet, pour régénérer son ``package-lock.json`` avec lui (E32).

Un lockfile se régénère par le npm de la machine, qui n'est pas forcément celui de la CI du
projet. Vu sur un dépôt de l'utilisateur : npm 11 (Node 24) retire du lockfile des paquets
facultatifs (pairs facultatifs imbriqués : ``ws``, ``zod``, ``@emnapi/*``) que npm 10 exige, et
``npm ci`` de la CI (Node 22, npm 10) refuse le lockfile (« Missing: … from lock file »). npm 10
retire aussi les ``"peer": true`` qu'ajoute npm 11 : deux npm différents se disputent le fichier.

**Ce que le projet attend**, dans cet ordre (le premier qui dit quelque chose décide) :

1. ``packageManager`` du ``package.json`` (``npm@10.9.0``) ; un autre gestionnaire (``pnpm@…``,
   ``yarn@…``) : rien à dire ;
2. ``devEngines.packageManager`` (``{"name": "npm", "version": "^10"}``), puis ``engines.npm`` :
   une plage ; le npm installé qui la respecte convient ;
3. le Node.js choisi par le projet (``Project.runtimes`` qui ne sont pas des bornes basses :
   ``.nvmrc``, ``.node-version``, ``volta``, ``.tool-versions``, un ``FROM node:22``, la
   ``node-version`` de ``actions/setup-node`` ou l'``image`` de la CI) : le plus ancien, car un
   lockfile qu'accepte le npm le plus ancien est accepté des autres. Il donne le npm livré avec
   ce Node (``NODE_NPM``) ;
4. ``engines.node`` : une plage ; si le Node installé la respecte, rien à dire, sinon le npm de la
   plus récente ligne de Node qu'elle accepte.

Une version de Node partielle (``22``, ``lts/jod``) désigne la dernière de sa ligne, celle que
prend ``actions/setup-node`` : son npm est celui de la dernière version publiée.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from forceupdate.models import Runtime
from forceupdate.versions import InvalidConstraint, InvalidVersion
from forceupdate.versions.npm import NPM

NODE_NPM: Mapping[int, tuple[tuple[int, int], ...]] = {
    14: ((0, 6),),
    15: ((0, 7),),
    16: ((0, 7), (11, 8)),
    17: ((0, 8),),
    18: ((0, 8), (14, 9), (19, 10)),
    19: ((0, 8), (3, 9)),
    20: ((0, 9), (7, 10)),
    21: ((0, 10),),
    22: ((0, 10),),
    23: ((0, 10),),
    24: ((0, 11),),
    25: ((0, 11),),
    26: ((0, 11),),
}
"""La majeure de npm livrée avec Node.js, par ligne : à partir de quelle mineure (Node 18.14 :
npm 9, 18.19 : npm 10). Relevée sur ``nodejs.org/dist/index.json`` le 2026-11-02 (Node 22 : npm
10.9.9, Node 24 : npm 11.19.1, Node 26 : npm 11.20.0 ; Node 27 n'a que des pré-versions). Une
ligne plus récente n'est pas connue : rien n'est dit."""

MIN_NPM = 8
"""Le plus ancien npm que forceupdate lance par ``npx`` : npm 7 réécrit un lockfile au format 2,
npm 6 au format 1 (vérifié sous Node 24) ; npm 8 et plus gardent le format 3."""

_PACKAGE_MANAGER = re.compile(r"(?P<name>[\w.-]+)@(?P<version>[^+\s]+)(?:\+\S*)?")
"""``packageManager`` : ``npm@10.9.0``, avec ou sans l'empreinte de corepack (``+sha512.…``)."""


@dataclass(frozen=True, kw_only=True)
class Expected:
    """Le npm qu'attend le projet, quand ce n'est pas celui de la machine."""

    major: int
    """La majeure de npm attendue (``10``)."""
    installed: str
    """La version du npm de la machine (``11.6.2``)."""
    source: str
    """D'où on le sait : ``packageManager = "npm@10.9.0"``, ``Node.js 22, lu dans
    .github/workflows/ci.yml (actions/setup-node : node-version 22)``."""


def declared(manifest: Any, runtimes: Sequence[Runtime]) -> bool:
    """Vrai si le projet dit quelque chose de son npm ou de son Node : sans rien, inutile de
    demander leur version aux outils de la machine."""
    if not isinstance(manifest, dict):
        manifest = {}
    keys = (
        manifest.get("packageManager"),
        _get(manifest, "devEngines", "packageManager"),
        _get(manifest, "engines", "npm"),
        _get(manifest, "engines", "node"),
    )
    return any(value is not None for value in keys) or any(
        runtime.product == "nodejs" for runtime in runtimes
    )


def expected(
    manifest: Any,
    runtimes: Sequence[Runtime],
    installed: str,
    node: Callable[[], str | None],
) -> Expected | None:
    """Le npm qu'attend le projet (son ``package.json`` lu, ``manifest``, et ses runtimes),
    quand le npm installé (``installed``, ``11.6.2``) ne convient pas ; ``None`` sinon, ou si le
    projet ne dit rien. ``node`` donne la version du Node installé (demandée seulement pour
    ``engines.node``). Voir la docstring du module."""
    if not isinstance(manifest, dict):
        manifest = {}
    try:
        current = NPM.parse(installed)
    except InvalidVersion:
        return None
    major = current.major

    def differs(wanted: int | None, source: str) -> Expected | None:
        if wanted is None or wanted == major:
            return None
        return Expected(major=wanted, installed=installed, source=source)

    package_manager = manifest.get("packageManager")
    if isinstance(package_manager, str):
        found = _PACKAGE_MANAGER.fullmatch(package_manager.strip())
        if found is None or found["name"] != "npm":
            return None
        wanted = _major(found["version"])
        return differs(wanted, f'packageManager = "{package_manager.strip()}"')
    for keys, label in (
        (("devEngines", "packageManager"), "devEngines.packageManager"),
        (("engines", "npm"), "engines.npm"),
    ):
        declared_range = _npm_range(_get(manifest, *keys))
        if declared_range is not None:
            if _satisfies(declared_range, installed):
                return None
            source = f'{label} = "{declared_range}"'
            return differs(_highest_major(declared_range), source)
    chosen = [r for r in runtimes if r.product == "nodejs" and not r.approximate]
    oldest = min(chosen, key=lambda r: _line_key(r.version), default=None)
    if oldest is not None:
        source = f"Node.js {oldest.version}, lu dans {oldest.file} ({oldest.source})"
        return differs(npm_of_node(oldest.version), source)
    engines = _get(manifest, "engines", "node")
    if isinstance(engines, str) and engines.strip():
        running = node()
        if running is None or _satisfies(engines, running):
            return None
        line = _highest_node_line(engines)
        if line is None:
            return None
        source = f'engines.node = "{engines.strip()}" (Node.js {running} ici)'
        return differs(npm_of_node(str(line)), source)
    return None


def npm_of_node(version: str) -> int | None:
    """La majeure de npm livrée avec ``version`` de Node.js (``22``, ``20.5.1``) : pour une
    version partielle, celle de la dernière de la ligne. ``None`` pour une ligne inconnue."""
    numbers = [int(part) for part in re.findall(r"\d+", version)[:2]]
    if not numbers or numbers[0] not in NODE_NPM:
        return None
    steps = NODE_NPM[numbers[0]]
    if len(numbers) == 1:
        return steps[-1][1]
    return next(npm for minor, npm in reversed(steps) if numbers[1] >= minor)


def _major(version: str) -> int | None:
    try:
        return NPM.parse(version.strip().lstrip("v")).major
    except InvalidVersion:
        return None


def _npm_range(value: Any) -> str | None:
    """La plage de npm de ``devEngines.packageManager`` (une table, ou une liste de tables :
    celle de npm), ou de ``engines.npm`` (une chaîne)."""
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        value = [value]
    if isinstance(value, list):
        for entry in value:
            if isinstance(entry, dict) and entry.get("name") == "npm":
                version = entry.get("version")
                if not isinstance(version, str):
                    return None
                return version.strip() or None
    return None


def _satisfies(constraint: str, version: str) -> bool:
    """Vrai si ``version`` respecte ``constraint`` ; vrai aussi pour une plage illisible (on ne
    sait rien dire)."""
    try:
        return NPM.satisfies(constraint, version.strip().lstrip("v"))
    except (InvalidConstraint, InvalidVersion):
        return True


def _highest_major(constraint: str) -> int | None:
    """La plus haute majeure de npm dont une version respecte ``constraint`` : parmi celles que
    livre Node.js."""
    majors = sorted({npm for steps in NODE_NPM.values() for _, npm in steps}, reverse=True)
    for npm in majors:
        for minor in (99999, 0):
            if _strict(constraint, f"{npm}.{minor}.0"):
                return npm
    return None


def _highest_node_line(constraint: str) -> int | None:
    """La plus récente ligne de Node.js connue (``NODE_NPM``) dont une version respecte
    ``constraint``."""
    for line in sorted(NODE_NPM, reverse=True):
        if any(_strict(constraint, f"{line}.{minor}.0") for minor in (99999, 0)):
            return line
    return None


def _strict(constraint: str, version: str) -> bool:
    try:
        return NPM.satisfies(constraint, version)
    except (InvalidConstraint, InvalidVersion):
        return False


def _line_key(version: str) -> tuple[int, ...]:
    """Pour trier des versions de Node partielles : ``22`` vaut la dernière de la ligne."""
    numbers = [int(part) for part in re.findall(r"\d+", version)[:3]]
    return tuple(numbers + [99999] * (3 - len(numbers)))


def _get(data: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data
