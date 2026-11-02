"""Une source locale : un dossier, ou un seul fichier, de l'ordinateur.

Dans un dépôt git, la liste des fichiers vient de git (``git ls-files``) : ce que
``.gitignore`` écarte (données, rapports, clones d'autres dépôts…) ne compte pas,
comme sur une forge. Hors de git, ou sans git installé, le dossier est parcouru en
sautant ``IGNORED_DIRS`` ; un dépôt rangé dans ce dossier garde son ``.gitignore``.

Un manifeste ou un lockfile seul est analysé avec les lockfiles posés à côté de lui.

Un fichier de code (E28 : ``app.py``, ``index.ts``…) l'est à travers son projet : on remonte les
dossiers jusqu'au premier qui a un manifeste de son écosystème (``detect.code``), en s'arrêtant à
la racine du dépôt git, à celle du disque, ou avant le dossier personnel (un ``package.json``
laissé là par erreur n'est pas un projet). La source est alors le dépôt git qui contient ce
projet (ses lockfiles de workspace, ses ``Directory.Packages.props`` et ses ``pom.xml`` parents
sont au-dessus de lui), sinon le dossier du projet ; le moteur n'en analyse que ce projet. Sans
projet, la source est le dossier du fichier, réduite au fichier (et au lockfile d'un script,
``script.py.lock``) : ce sont ses imports qui sont lus. Un fichier envoyé par l'interface
(``alone``) n'a jamais de projet autour.
"""

import logging
import os
import shutil
import stat
import subprocess
from pathlib import Path

from forceupdate.detect.code import code_ecosystem
from forceupdate.detect.manifests import (
    is_ignored_dir,
    is_ignored_path,
    lockfile_candidates,
    match_dependency_file,
    max_read_size,
    safe_read_text,
)
from forceupdate.models import Ecosystem
from forceupdate.sources.base import ChosenCode, Source, SourceError, SourceFile

logger = logging.getLogger(__name__)

GIT_TIMEOUT = 60.0
"""Délai maximal de ``git ls-files``, en secondes."""


class LocalSource(Source):
    """Un dossier ou un fichier de l'ordinateur.

    Lève ``SourceError`` si le chemin n'existe pas.
    """

    root: Path
    """Le dossier analysé ; pour un fichier seul, son dossier ; pour un fichier de code dans un
    projet, le dépôt git qui le contient, sinon le dossier du projet."""

    def __init__(self, path: Path | str, *, alone: bool = False) -> None:
        """``alone`` : un fichier de code n'a pas de projet autour (un fichier envoyé, rangé
        dans un dossier temporaire)."""
        given = Path(path)
        if not given.exists():
            raise SourceError(f"le chemin « {path} » n'existe pas")
        resolved = given.resolve()
        self.origin = resolved.as_posix()
        self._file: str | None = None
        self._code: ChosenCode | None = None
        if resolved.is_dir():
            self.root = resolved
        elif resolved.is_file():
            if match_dependency_file(f"{resolved.parent.name}/{resolved.name}") is not None:
                self.root = _file_root(resolved)
                self._file = resolved.relative_to(self.root).as_posix()
                return
            project = None if alone else _project_dir(resolved)
            self.root = resolved.parent if project is None else _project_root(project)
            self._file = resolved.relative_to(self.root).as_posix()
            where = None if project is None else project.relative_to(self.root).as_posix()
            self._code = ChosenCode(self._file, where)
        else:
            raise SourceError(f"« {path} » n'est ni un dossier ni un fichier")

    @property
    def file(self) -> str | None:
        """Pour un fichier seul, son chemin relatif à ``root`` ; ``None`` pour un dossier."""
        return self._file

    @property
    def code_file(self) -> ChosenCode | None:
        return self._code

    def files(self) -> list[SourceFile]:
        if self._file is None or (self._code is not None and self._code.project is not None):
            return sorted(_list_dir(self.root))
        if self._code is not None:
            paths = [self._file, f"{self._file}.lock"]
        else:
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


def _project_dir(file: Path) -> Path | None:
    """Le dossier du projet d'un fichier de code : le premier, en remontant depuis le sien, qui
    a un manifeste de son écosystème (de n'importe lequel pour un fichier d'un autre langage).
    ``None`` si on atteint la racine du dépôt git, celle du disque, ou le dossier personnel
    sans en trouver."""
    ecosystem = code_ecosystem(file.name)
    home = _home()
    folder = file.parent
    while folder != home:
        if _has_manifest(folder, ecosystem):
            return folder
        if (folder / ".git").exists() or folder.parent == folder:
            return None
        folder = folder.parent
    return None


def _home() -> Path | None:
    try:
        return Path.home().resolve()
    except (OSError, RuntimeError):
        return None


def _has_manifest(folder: Path, ecosystem: Ecosystem | None) -> bool:
    """Vrai si ``folder`` a un manifeste de ``ecosystem`` (de n'importe lequel avec ``None``) :
    un fichier ordinaire, ou un ``requirements/*.txt`` (le motif d'un dossier)."""
    for directory, prefix in ((folder, ""), (folder / "requirements", "requirements/")):
        try:
            with os.scandir(directory) as entries:
                names = [e.name for e in entries if e.is_file(follow_symlinks=False)]
        except OSError:
            continue
        for name in names:
            # Un nom de dossier quelconque devant : « requirements/dev.txt » appartient au dossier
            # du dessus, sauf s'il est préfixé ici.
            match = match_dependency_file(f"projet/{prefix}{name}")
            if match is None or match.lockfile or match.project != "projet":
                continue
            if ecosystem is None or match.ecosystem is ecosystem:
                return True
    return False


def _project_root(project: Path) -> Path:
    """La racine de la source d'un fichier de code dans ``project`` : le dépôt git qui contient
    le projet, sauf si le projet est dans un dossier jamais parcouru (``node_modules``…) ; sinon
    le projet lui-même."""
    for candidate in [project, *project.parents]:
        if (candidate / ".git").exists():
            inside = project.relative_to(candidate).as_posix()
            return project if is_ignored_path(f"{inside}/x") else candidate
    return project


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
