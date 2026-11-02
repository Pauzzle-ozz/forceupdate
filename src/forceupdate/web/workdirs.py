"""Les dossiers de travail du serveur : les fichiers téléchargés d'un dépôt (et son clone), un
fichier envoyé, le clone d'une PR.

Tous sont rangés dans le dossier de ce serveur, ``forceupdate-ui-*`` du dossier temporaire du
système, effacé à l'arrêt. Un arrêt brutal (processus tué, ordinateur éteint) le laisse : le
serveur suivant l'efface au démarrage (``sweep``). Jamais celui d'un serveur qui tourne encore
(deux ``forceupdate ui`` à la fois) : chaque serveur garde ouvert et verrouillé le fichier
``.lock`` de son dossier, et le système relâche ce verrou à sa mort, même brutale
(``msvcrt.locking`` sous Windows, ``flock`` ailleurs). Un dossier qu'on ne peut pas verrouiller,
ou qu'on ne peut pas lire (celui d'une autre personne), est laissé.

Sous Windows, git écrit ses objets en lecture seule : ils s'effacent par ``git.remove_tree``
(avant E31, ``shutil.rmtree(ignore_errors=True)`` les laissait, et chaque analyse clonée laissait
son clone dans le dossier temporaire).
"""

import contextlib
import logging
import os
import tempfile
import time
from pathlib import Path

from forceupdate.forges.git import remove_tree

logger = logging.getLogger(__name__)

PREFIX = "forceupdate-ui-"
LOCK = ".lock"
YOUNG = 60.0
"""Secondes pendant lesquelles un dossier sans ``.lock`` est laissé : un serveur qui démarre
crée son dossier, puis son verrou."""


def default_base() -> Path:
    """Où ranger les dossiers des serveurs : le dossier temporaire du système. Les tests le
    remplacent (``conftest.py``)."""
    return Path(tempfile.gettempdir())


class Workdirs:
    """Le dossier de travail de ce serveur, verrouillé tant qu'il tourne."""

    def __init__(self, base: Path | None = None) -> None:
        self.path = Path(tempfile.mkdtemp(prefix=PREFIX, dir=base or default_base()))
        self._lock: int | None = os.open(self.path / LOCK, os.O_RDWR | os.O_CREAT, 0o600)
        os.write(self._lock, b"\0")
        os.lseek(self._lock, 0, os.SEEK_SET)
        _lock(self._lock)

    def make(self, prefix: str) -> Path:
        """Un nouveau dossier, dans celui du serveur."""
        return Path(tempfile.mkdtemp(prefix=prefix, dir=self.path))

    def close(self) -> None:
        """Relâche le verrou et efface le dossier ; un échec est noté, sans lever (un processus
        qui y écrit encore : le serveur suivant le finira)."""
        if self._lock is not None:
            with contextlib.suppress(OSError):
                _unlock(self._lock)
            os.close(self._lock)
            self._lock = None
        try:
            remove_tree(self.path)
        except OSError as err:
            logger.warning("dossier de travail pas entièrement effacé (%s) : %s", self.path, err)


def sweep(base: Path | None = None) -> int:
    """Efface les dossiers laissés par des serveurs arrêtés brutalement ; rend leur nombre."""
    removed = 0
    for directory in sorted((base or default_base()).glob(f"{PREFIX}*")):
        try:
            if directory.is_symlink() or not directory.is_dir() or not _abandoned(directory):
                continue
            remove_tree(directory)
        except OSError as err:
            logger.info("dossier de travail laissé (%s) : %s", directory, err)
            continue
        removed += 1
    if removed:
        logger.info("%d dossier(s) de travail laissé(s) par un arrêt brutal, effacé(s)", removed)
    return removed


def _abandoned(directory: Path) -> bool:
    """Plus aucun serveur ne tient le verrou de ``directory``. Lève ``OSError`` s'il ne se lit
    pas."""
    try:
        descriptor = os.open(directory / LOCK, os.O_RDWR)
    except FileNotFoundError:
        return time.time() - directory.stat().st_mtime > YOUNG
    try:
        _lock(descriptor)
    except OSError:
        return False  # un serveur le tient
    else:
        _unlock(descriptor)
        return True
    finally:
        os.close(descriptor)


if os.name == "nt":
    import msvcrt

    def _lock(descriptor: int) -> None:
        """Verrouille le premier octet, sans attendre : ``OSError`` s'il est déjà pris."""
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)

    def _unlock(descriptor: int) -> None:
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock(descriptor: int) -> None:
        """Verrouille le fichier, sans attendre : ``OSError`` s'il est déjà pris."""
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(descriptor: int) -> None:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
