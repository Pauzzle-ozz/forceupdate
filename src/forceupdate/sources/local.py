"""Une source locale : un dossier, ou un seul fichier, de l'ordinateur.

Dans un dépôt git, la liste des fichiers vient de git (``git ls-files``) : ce que
``.gitignore`` écarte (données, rapports, clones d'autres dépôts…) ne compte pas,
comme sur une forge. Hors de git, ou sans git installé, le dossier est parcouru en
sautant ``IGNORED_DIRS`` ; un dépôt rangé dans ce dossier garde son ``.gitignore``.

Robustesse (E30, vérifié le 2026-11-02 sous Windows) :

- au plus ``MAX_FILES`` fichiers listés : au-delà (un dossier personnel, un disque entier), la
  liste s'arrête et le rapport le dit (``Source.notices``) ;
- ni les liens symboliques, ni les jonctions Windows (``mklink /J``) ne sont suivis. Une jonction
  est un dossier pour ``lstat`` : ``os.walk`` y entre, et ``git ls-files`` liste ce qu'elle
  contient comme des fichiers du dépôt, même hors de lui (``_is_junction``) ;
- un sous-module git non initialisé est un dossier vide : il n'est pas analysé, le rapport le
  dit. Dans ce dossier, git répond ``./`` (on y entrait sans fin, jusqu'au ``RecursionError``).

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

from forceupdate import processes
from forceupdate.detect.code import code_ecosystem
from forceupdate.detect.manifests import (
    is_ignored_dir,
    is_ignored_path,
    lockfile_candidates,
    match_dependency_file,
    max_read_size,
    safe_read_text,
)
from forceupdate.models import Ecosystem, Notice
from forceupdate.sources.base import ChosenCode, Source, SourceError, SourceFile

logger = logging.getLogger(__name__)

GIT_TIMEOUT = 60.0
"""Délai maximal de ``git ls-files``, en secondes."""
MAX_FILES = 200_000
"""Le nombre maximal de fichiers listés d'une source. Un gros dépôt en a moins (le noyau Linux,
90 000) ; un dossier personnel ou un disque, bien plus."""


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
        self._notices: list[Notice] = []
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

    @property
    def notices(self) -> list[Notice]:
        return list(self._notices)

    SUBMODULE = "sous-module git non initialisé : pas analysé (git submodule update --init)."
    """La remarque d'un sous-module vide."""

    def files(self) -> list[SourceFile]:
        if self._file is None or (self._code is not None and self._code.project is not None):
            listing = _Listing(MAX_FILES, submodule=self.SUBMODULE)
            listing.directory(self.root, "")
            self._notices = listing.notices
            return sorted(listing.files)
        if self._code is not None:
            paths = [self._file, f"{self._file}.lock"]
        else:
            paths = [self._file, *lockfile_candidates(self._file)]
        return sorted(file for path in paths if (file := _stat_file(self.root, path)) is not None)

    def is_directory(self, path: str) -> bool:
        full = (self.root / path).resolve()
        return full.is_relative_to(self.root) and full.is_dir()

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


class _Listing:
    """Les fichiers d'une source en cours de liste : au plus ``limit``, et les remarques à faire
    dans le rapport."""

    def __init__(self, limit: int, *, submodule: str) -> None:
        """``submodule`` : la remarque d'un sous-module vide."""
        self.limit = limit
        self.submodule = submodule
        self.files: list[SourceFile] = []
        self.notices: list[Notice] = []
        self._full = False
        self._junctions: dict[Path, bool] = {}

    def directory(self, directory: Path, prefix: str) -> None:
        """Ajoute les fichiers sous ``directory``, leurs chemins précédés de ``prefix`` (vide,
        ou ``dossier/``) : ceux que liste git, sinon ceux du dossier."""
        paths = _git_paths(directory)
        if paths is None:
            self._walk(directory, prefix)
        else:
            self._git(directory, prefix, paths)

    def _git(self, directory: Path, prefix: str, paths: list[str]) -> None:
        for entry in paths:
            if self._full:
                return
            path = entry.rstrip("/")
            if path in ("", ".") or is_ignored_path(path):
                continue  # « ./ » : ce que répond git dans un sous-module vide
            if self._in_junction(directory, (directory / path).parent):
                continue
            try:
                info = (directory / path).lstat()
            except OSError:
                continue  # suivi par git, mais supprimé du disque
            if stat.S_ISREG(info.st_mode):
                self._add(SourceFile(prefix + path, info.st_size))
            elif (
                stat.S_ISDIR(info.st_mode)
                and not is_ignored_dir(path.rsplit("/", 1)[-1])
                and not _is_junction(directory / path)
            ):
                self._repository(directory / path, prefix + path, submodule=not entry.endswith("/"))

    def _repository(self, directory: Path, path: str, *, submodule: bool) -> None:
        """Un dépôt dans le dépôt (sous-module, ou clone non ignoré) : git ne liste que son
        dossier, on lui demande ses fichiers. Un sous-module non initialisé n'en a pas."""
        if (directory / ".git").exists():
            self.directory(directory, f"{path}/")
        elif submodule:
            self.notices.append(Notice(file=path, message=self.submodule))

    def _walk(self, directory: Path, prefix: str) -> None:
        """Parcourt ``directory`` sans git, en sautant les dossiers ignorés, les liens et les
        jonctions."""
        for current, dirs, names in os.walk(directory):
            here = Path(current)
            relative = here.relative_to(directory).as_posix()
            inside = prefix if relative == "." else f"{prefix}{relative}/"
            kept = []
            for name in dirs:
                sub = here / name
                if is_ignored_dir(name) or sub.is_symlink() or _is_junction(sub):
                    continue
                if (sub / ".git").exists():
                    # Un dépôt git rangé ici : il garde son propre .gitignore.
                    self.directory(sub, f"{inside}{name}/")
                else:
                    kept.append(name)
            dirs[:] = kept
            for name in names:
                file = _stat_file(here, name)
                if file is not None:
                    self._add(SourceFile(inside + name, file.size))
            if self._full:
                return

    def _add(self, file: SourceFile) -> None:
        """Ajoute ``file``, sauf une fois la limite atteinte : le rapport le dit."""
        if self._full:
            return
        if len(self.files) >= self.limit:
            self._full = True
            count = f"{self.limit:,}".replace(",", "\N{NO-BREAK SPACE}")
            self.notices.append(
                Notice(
                    file=".",
                    message=f"plus de {count} fichiers : la liste s'arrête là, les projets "
                    "des fichiers suivants ne sont pas analysés (choisir un dossier plus petit).",
                )
            )
            return
        self.files.append(file)

    def _in_junction(self, root: Path, folder: Path) -> bool:
        """Vrai si ``folder``, sous ``root``, est une jonction ou dans une jonction. Sous
        Windows seulement ; chaque dossier n'est regardé qu'une fois."""
        if os.name != "nt" or folder == root:
            return False
        found = self._junctions.get(folder)
        if found is None:
            found = self._in_junction(root, folder.parent) or _is_junction(folder)
            self._junctions[folder] = found
        return found


def _is_junction(path: Path) -> bool:
    """Vrai pour une jonction Windows (``mklink /J``). ``Path.is_junction`` n'existe qu'à partir
    de Python 3.12. Ailleurs, jamais (``stat.IO_REPARSE_TAG_MOUNT_POINT`` n'y existe pas)."""
    if os.name != "nt":
        return False
    try:
        info = path.lstat()
    except OSError:
        return False
    return getattr(info, "st_reparse_tag", 0) == stat.IO_REPARSE_TAG_MOUNT_POINT


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
        result = processes.run(
            command, cwd=directory, env=env, capture_output=True, timeout=GIT_TIMEOUT
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
