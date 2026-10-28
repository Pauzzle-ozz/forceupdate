"""Le garde-fou de la mise à jour locale : ne pas réécrire un fichier dont git n'a pas la
dernière version.

Un manifeste modifié, ajouté à l'index sans commit, ou que git ne suit pas : la réécriture
mêlerait ses changements à ceux de la personne, et ``git checkout`` ne permettrait plus de
revenir en arrière. ``forceupdate update`` refuse alors, sauf ``--force``.
"""

import logging
import os
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger(__name__)

GIT_TIMEOUT = 60.0
"""Délai maximal de chaque commande git, en secondes."""


def uncommitted(root: Path, paths: Iterable[str]) -> list[str] | None:
    """Parmi ``paths`` (relatifs à ``root``, au format POSIX), ceux qui ont des changements que
    git n'a pas en commit : modifiés, ajoutés à l'index, ou pas suivis. Dans l'ordre de ``paths``.

    ``None`` si on ne peut pas le savoir : ``root`` n'est pas dans un dépôt git, ou git n'est
    pas installé.
    """
    wanted = list(dict.fromkeys(paths))
    prefix = _git(root, "rev-parse", "--show-prefix")
    if prefix is None:
        return None
    status = _git(
        root,
        "--literal-pathspecs",
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--",
        *wanted,
    )
    if status is None:
        return None
    # Les chemins de « git status » partent de la racine du dépôt, pas de root.
    start = prefix.strip()
    changed = set()
    entries = iter(status.split("\0"))
    for entry in entries:
        if len(entry) < 4:
            continue
        if "R" in entry[:2] or "C" in entry[:2]:
            next(entries, None)  # renommé ou copié : l'ancien chemin suit
        path = entry[3:]
        if path.startswith(start):
            changed.add(path[len(start) :])
    return [path for path in wanted if path in changed]


def _git(root: Path, *args: str) -> str | None:
    """La sortie de ``git args`` lancé dans ``root`` ; ``None`` si git est absent ou échoue."""
    git = shutil.which("git")
    if git is None:
        return None
    # Un dépôt peut déclarer un programme à lancer à chaque lecture de l'index.
    command = [git, "-c", "core.fsmonitor=false", *args]
    # Sans GIT_DIR & co, hérités par exemple d'un hook : git doit regarder ce dossier-ci.
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    try:
        result = subprocess.run(
            command, cwd=root, env=env, capture_output=True, timeout=GIT_TIMEOUT, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as err:
        logger.debug("git %s impossible dans %s : %s", args[0], root, err)
        return None
    if result.returncode != 0:
        return None
    return os.fsdecode(result.stdout)
