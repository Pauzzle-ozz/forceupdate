"""Les dossiers de l'ordinateur, pour choisir quoi analyser : un navigateur ne peut pas donner
le chemin d'un dossier à une page web (brief, « Les sources »), c'est donc le serveur qui les
liste.

Seulement des noms : les dossiers, et les fichiers de dépendances qu'on peut choisir
(``detect.manifests.match_dependency_file``). Jamais le contenu d'un fichier. Les liens
symboliques et les jonctions Windows ne sont pas listés : l'analyse ne les suit jamais (E02).
Un dossier OneDrive, autre « point d'analyse » de Windows, l'est.

Les chemins sont absolus, au format POSIX (``C:/Users/…`` sous Windows), comme
``Report.source``.
"""

import asyncio
import ctypes
import os
import stat
import string
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from forceupdate.detect.manifests import match_dependency_file
from forceupdate.web.routes import CurrentJobs, errors, respond
from forceupdate.web.schemas import Entry, EntryKind, Listing

router = APIRouter(prefix="/api/fs", tags=["dossiers"])

MAX_ENTRIES = 5000
"""Entrées listées au plus dans un dossier."""

_HIDDEN = getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0)
_LINKS = {
    getattr(stat, "IO_REPARSE_TAG_SYMLINK", -1),
    getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", -1),
}
"""Les liens de Windows : liens symboliques et jonctions."""


@router.get("", response_model=Listing, responses=errors(400, 401, 403, 404))
async def list_folder(jobs: CurrentJobs, path: str | None = None) -> JSONResponse:
    """Le contenu du dossier ``path`` (absolu) ; sans ``path``, les points de départ : le
    dossier personnel et les lecteurs. Toujours avec les derniers chemins analysés."""
    recent = await asyncio.to_thread(_recent, jobs.recent.load())
    if not path:
        return respond(await asyncio.to_thread(_roots, recent))
    return respond(await asyncio.to_thread(_listing, path, recent))


def _roots(recent: tuple[str, ...]) -> Listing:
    home = Path.home()
    entries = [
        Entry(
            name=home.name or home.as_posix(),
            path=home.as_posix(),
            kind=EntryKind.FOLDER,
            hidden=False,
        )
    ]
    entries += [
        Entry(name=drive.rstrip("/"), path=drive, kind=EntryKind.DRIVE, hidden=False)
        for drive in _drives()
    ]
    return Listing(
        path=None,
        parent=None,
        entries=tuple(entries),
        truncated=False,
        home=home.as_posix(),
        recent=recent,
    )


def _listing(path: str, recent: tuple[str, ...]) -> Listing:
    folder = Path(path)
    if not folder.is_absolute():
        raise HTTPException(400, f"« {path} » : donner un chemin absolu.")
    folder = Path(os.path.normpath(folder))
    try:
        with os.scandir(folder) as scanned:
            found = list(scanned)
    except FileNotFoundError as err:
        raise HTTPException(404, f"Le dossier « {path} » n'existe pas.") from err
    except NotADirectoryError as err:
        raise HTTPException(400, f"« {path} » n'est pas un dossier.") from err
    except PermissionError as err:
        raise HTTPException(403, f"Accès refusé au dossier « {path} ».") from err
    except OSError as err:
        raise HTTPException(400, f"Dossier « {path} » illisible : {err.strerror or err}.") from err
    folders: list[Entry] = []
    files: list[Entry] = []
    for item in found:
        entry = _entry(folder, item)
        if entry is not None:
            (folders if entry.kind is EntryKind.FOLDER else files).append(entry)
    entries = sorted(folders, key=_by_name) + sorted(files, key=_by_name)
    parent = folder.parent if folder.parent != folder else None
    return Listing(
        path=folder.as_posix(),
        parent=parent.as_posix() if parent is not None else None,
        entries=tuple(entries[:MAX_ENTRIES]),
        truncated=len(entries) > MAX_ENTRIES,
        home=Path.home().as_posix(),
        recent=recent,
    )


def _entry(folder: Path, item: os.DirEntry[str]) -> Entry | None:
    """Un dossier, ou un fichier de dépendances ; ``None`` pour le reste (liens compris)."""
    try:
        info = item.stat(follow_symlinks=False)
    except OSError:
        return None
    if item.is_symlink() or getattr(info, "st_reparse_tag", None) in _LINKS:
        return None
    hidden = item.name.startswith(".") or bool(getattr(info, "st_file_attributes", 0) & _HIDDEN)
    path = (folder / item.name).as_posix()
    if stat.S_ISDIR(info.st_mode):
        return Entry(name=item.name, path=path, kind=EntryKind.FOLDER, hidden=hidden)
    if stat.S_ISREG(info.st_mode) and match_dependency_file(f"{folder.name}/{item.name}"):
        return Entry(name=item.name, path=path, kind=EntryKind.FILE, hidden=hidden)
    return None


def _by_name(entry: Entry) -> tuple[str, str]:
    return entry.name.casefold(), entry.name


def _drives() -> list[str]:
    """Les lecteurs (``C:/``…) sous Windows, ``/`` ailleurs. Sous Windows, sans les toucher :
    un lecteur réseau déconnecté ferait attendre."""
    if os.name != "nt":
        return ["/"]
    mask = ctypes.windll.kernel32.GetLogicalDrives()  # type: ignore[attr-defined]
    return [
        f"{letter}:/" for index, letter in enumerate(string.ascii_uppercase) if mask >> index & 1
    ]


def _recent(paths: list[str]) -> tuple[str, ...]:
    """Les chemins récents qui existent encore."""
    return tuple(path for path in paths if Path(path).exists())
