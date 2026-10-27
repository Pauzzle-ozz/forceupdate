"""Une source locale : un dossier, ou un seul fichier, de l'ordinateur.

Dans un dépôt git, la liste des fichiers vient de git (``git ls-files``) : ce que
``.gitignore`` écarte (données, rapports, clones d'autres dépôts…) ne compte pas,
comme sur une forge. Hors de git, ou sans git installé, le dossier est parcouru en
sautant ``IGNORED_DIRS`` ; un dépôt rangé dans ce dossier garde son ``.gitignore``.

Un fichier seul est analysé avec les lockfiles posés à côté de lui.
"""

import logging
import os
import shutil
import stat
import subprocess
from pathlib import Path

from forceupdate.detect.manifests import (
    is_ignored_dir,
    is_ignored_path,
    lockfile_candidates,
    match_dependency_file,
    max_read_size,
    safe_read_text,
)
from forceupdate.sources.base import Source, SourceError, SourceFile

logger = logging.getLogger(__name__)

GIT_TIMEOUT = 60.0
"""Délai maximal de ``git ls-files``, en secondes."""


class LocalSource(Source):
    """Un dossier ou un fichier de l'ordinateur.

    Lève ``SourceError`` si le chemin n'existe pas.
    """

    root: Path
    """Le dossier analysé ; pour un fichier seul, son dossier."""

    def __init__(self, path: Path | str) -> None:
        given = Path(path)
        if not given.exists():
            raise SourceError(f"le chemin « {path} » n'existe pas")
        resolved = given.resolve()
        self.origin = resolved.as_posix()
        self._file: str | None = None
        if resolved.is_dir():
            self.root = resolved
        elif resolved.is_file():
            self.root = _file_root(resolved)
            self._file = resolved.relative_to(self.root).as_posix()
        else:
            raise SourceError(f"« {path} » n'est ni un dossier ni un fichier")

    def files(self) -> list[SourceFile]:
        if self._file is None:
            return sorted(_list_dir(self.root))
        paths = [self._file, *lockfile_candidates(self._file)]
        return sorted(file for path in paths if (file := _stat_file(self.root, path)) is not None)

    def read_text(self, path: str) -> str | None:
        """Le contenu de ``path``, relatif à ``root``.

        Plafonné à 2 Mo, 50 Mo pour un lockfile (voir ``max_read_size``). Lève
        ``ValueError`` si ``path`` mène hors de ``root``.
        """
        full = (self.root / path).resolve()
        if not full.is_relative_to(self.root):
            raise ValueError(f"chemin hors de la source : {path}")
        return safe_read_text(full, max_size=max_read_size(path))


def _file_root(file: Path) -> Path:
    """La racine d'une source faite d'un seul fichier.

    Son dossier, ou celui du dessus quand le motif reconnu en dépend :
    ``requirements/dev.txt`` est un manifeste du dossier qui contient ``requirements/``.
    """
    parent = file.parent
    match = match_dependency_file(f"{parent.name}/{file.name}")
    if match is not None and match.project == "." and parent.parent != parent:
        return parent.parent
    return parent


def _list_dir(directory: Path) -> list[SourceFile]:
    """Les fichiers sous ``directory``, avec des chemins relatifs à lui."""
    paths = _git_paths(directory)
    if paths is None:
        return _walk(directory)
    files = []
    for entry in paths:
        path = entry.rstrip("/")
        if is_ignored_path(path):
            continue
        try:
            info = (directory / path).lstat()
        except OSError:
            continue  # suivi par git, mais supprimé du disque
        if stat.S_ISREG(info.st_mode):
            files.append(SourceFile(path, info.st_size))
        elif stat.S_ISDIR(info.st_mode) and not is_ignored_dir(path.rsplit("/", 1)[-1]):
            # Un dépôt dans le dépôt (sous-module, ou clone non ignoré) : git ne liste
            # que son dossier, on lui demande ses fichiers.
            files.extend(_prefixed(path, _list_dir(directory / path)))
    return files


def _walk(directory: Path) -> list[SourceFile]:
    """Parcourt ``directory`` sans git, en sautant les dossiers ignorés et les liens."""
    files = []
    for current, dirs, names in os.walk(directory):
        here = Path(current)
        relative = here.relative_to(directory).as_posix()
        prefix = "" if relative == "." else f"{relative}/"
        kept = []
        for name in dirs:
            sub = here / name
            if is_ignored_dir(name) or sub.is_symlink():
                continue
            if (sub / ".git").exists():
                # Un dépôt git rangé ici : il garde son propre .gitignore.
                files.extend(_prefixed(prefix + name, _list_dir(sub)))
            else:
                kept.append(name)
        dirs[:] = kept
        for name in names:
            file = _stat_file(directory, prefix + name)
            if file is not None:
                files.append(file)
    return files


def _git_paths(directory: Path) -> list[str] | None:
    """Ce que git liste sous ``directory`` : fichiers suivis, et nouveaux non ignorés.

    ``None`` quand git ne peut pas répondre (pas un dépôt, git absent) ou ne liste
    rien (dossier vide, ou entièrement ignoré par ``.gitignore`` : on le parcourt
    alors quand même, puisqu'il a été choisi).
    """
    git = shutil.which("git")
    if git is None:
        return None
    command = [
        git,
        # Un dépôt peut déclarer un programme à lancer à chaque lecture de l'index.
        "-c",
        "core.fsmonitor=false",
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
    ]
    # Sans GIT_DIR & co, hérités par exemple d'un hook : git doit regarder ce dossier-ci.
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    try:
        result = subprocess.run(
            command, cwd=directory, env=env, capture_output=True, timeout=GIT_TIMEOUT, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as err:
        logger.debug("git ls-files impossible dans %s : %s", directory, err)
        return None
    if result.returncode != 0:
        return None
    paths = dict.fromkeys(os.fsdecode(raw) for raw in result.stdout.split(b"\0") if raw)
    return list(paths) or None


def _stat_file(root: Path, path: str) -> SourceFile | None:
    """``path`` et sa taille, si c'est un fichier ordinaire (pas un lien symbolique)."""
    try:
        info = (root / path).lstat()
    except OSError:
        return None
    return SourceFile(path, info.st_size) if stat.S_ISREG(info.st_mode) else None


def _prefixed(prefix: str, files: list[SourceFile]) -> list[SourceFile]:
    return [SourceFile(f"{prefix}/{file.path}", file.size) for file in files]
