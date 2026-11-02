"""Le dossier de travail du serveur (``web.workdirs``, E31) : les fichiers des analyses et les
clones des PR y sont rangés, il est effacé à l'arrêt, et ceux qu'un arrêt brutal a laissés sont
effacés au démarrage suivant, jamais celui d'un serveur qui tourne encore (son verrou). Les
« serveurs » d'un autre processus sont de vrais processus Python ; tout se passe dans le
dossier du test (``server_temp``)."""

import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import API_BASE, API_TOKEN
from fastapi.testclient import TestClient

from forceupdate.web import Settings, create_app, workdirs
from forceupdate.web.workdirs import LOCK, PREFIX, Workdirs, sweep

HOLD = """
import sys
from pathlib import Path
from forceupdate.web.workdirs import Workdirs
held = Workdirs(Path(sys.argv[1]))
print(held.path, flush=True)
if sys.argv[2] == "mort":
    import os
    os._exit(0)  # un arrêt brutal : ni close, ni rien
sys.stdin.read()  # tourne jusqu'à ce qu'on ferme son entrée
held.close()
"""


def read_only_file(directory: Path) -> Path:
    """Un fichier en lecture seule, comme les objets de git sous Windows."""
    target = directory / "clone" / ".git" / "objects" / "pack.idx"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x")
    os.chmod(target, stat.S_IREAD)
    return target


def server(base: Path, how: str) -> tuple[subprocess.Popen[str], Path]:
    """Un autre processus qui tient un dossier de travail (``vivant``), ou qui meurt sans
    l'effacer (``mort``)."""
    process = subprocess.Popen(
        [sys.executable, "-c", HOLD, str(base), how],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    path = Path(process.stdout.readline().strip())
    if how == "mort":
        process.wait(30)
    return process, path


def test_the_folder_is_locked_and_removed_at_close(server_temp: Path) -> None:
    held = Workdirs()
    assert held.path.parent == server_temp and held.path.name.startswith(PREFIX)
    made = held.make("depot-")
    assert made.parent == held.path
    read_only_file(made)
    assert sweep() == 0  # il tourne : son verrou est pris
    held.close()
    assert not held.path.exists()


def test_the_folder_of_a_dead_server_is_swept_not_a_living_one(server_temp: Path) -> None:
    alive, kept = server(server_temp, "vivant")
    try:
        _, dead = server(server_temp, "mort")
        read_only_file(dead)
        assert kept.is_dir() and dead.is_dir()
        assert sweep() == 1
        assert not dead.exists()
        assert kept.is_dir()  # son serveur tourne encore
    finally:
        assert alive.stdin is not None
        alive.stdin.close()
        alive.wait(30)
    assert not kept.exists()  # effacé par son serveur, à sa sortie


def test_a_folder_without_its_lock_is_left_while_young(server_temp: Path) -> None:
    young = server_temp / f"{PREFIX}jeune"
    young.mkdir()  # un serveur qui démarre : son verrou n'est pas encore là
    old = server_temp / f"{PREFIX}vieux"
    old.mkdir()
    past = time.time() - workdirs.YOUNG - 10
    os.utime(old, (past, past))
    other = server_temp / "forceupdate-autre"
    other.mkdir()
    assert sweep() == 1
    assert young.is_dir() and not old.exists() and other.is_dir()


def test_the_server_sweeps_at_start_and_cleans_at_stop(
    web_settings: Settings, server_temp: Path
) -> None:
    _, dead = server(server_temp, "mort")
    read_only_file(dead)
    (dead / LOCK).touch()
    with TestClient(
        create_app(web_settings),
        base_url=API_BASE,
        headers={"Authorization": f"Bearer {API_TOKEN}"},
    ) as client:
        jobs = client.app.state.jobs  # type: ignore[attr-defined]
        deadline = time.monotonic() + 10
        while dead.exists():
            assert time.monotonic() < deadline, "le dossier laissé n'est pas effacé"
            time.sleep(0.02)
        mine = jobs.workdirs.path
        assert mine.parent == server_temp
        # Un fichier envoyé est rangé dans le dossier du serveur.
        response = client.post(
            "/api/files?name=requirements.txt",
            content=b"flask==0.12\n",
            headers={"Content-Type": "application/octet-stream"},
        )
        assert response.status_code == 202, response.text
        scan = jobs.scans[response.json()["id"]]
        assert scan.upload_dir.parent == mine
    assert not mine.exists()
    assert list(server_temp.iterdir()) == []


def test_a_cloned_analysis_leaves_nothing(server_temp: Path) -> None:
    """Le clone d'une analyse (objets de git en lecture seule) part avec elle : avant E31,
    ``shutil.rmtree(ignore_errors=True)`` le laissait dans le dossier temporaire."""
    from forceupdate.web.jobs import _remove

    held = Workdirs()
    directory = held.make("depot-")
    read_only_file(directory)
    _remove(directory)
    assert not directory.exists()
    held.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows : un fichier ouvert ne s'efface pas")
def test_a_folder_still_in_use_is_left_for_later(server_temp: Path) -> None:
    dead = server_temp / f"{PREFIX}occupe"
    dead.mkdir()
    (dead / LOCK).touch()
    busy = dead / "fichier"
    with busy.open("wb"):
        assert sweep() == 0  # un git tué en route : on réessaiera au prochain démarrage
    # À moitié effacé (son .lock parti), il attend YOUNG secondes, puis part.
    past = time.time() - workdirs.YOUNG - 10
    os.utime(dead, (past, past))
    assert sweep() == 1
    assert not dead.exists()
