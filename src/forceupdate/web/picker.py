"""La fenêtre de choix d'un dossier ou d'un fichier du système, pour l'écran 2 (session 36) : la
personne attendait du bouton « Ouvrir » la fenêtre de l'Explorateur, pas seulement une liste
dans la page. Un navigateur ne peut pas donner un chemin à une page ; le serveur, qui tourne sur
l'ordinateur de la personne, peut ouvrir cette fenêtre et rendre le chemin choisi.

Par Tk (``tkinter``, livré avec Python : ``askdirectory``, ``askopenfilename``), qui ouvre la
fenêtre du système : celle de l'Explorateur sous Windows, du Finder sous macOS ; sous Linux,
celle de Tk. Dans un programme à part, le même Python : Tk veut le fil principal de son
programme, et une fenêtre qui plante n'emporte pas le serveur. Elle passe au premier plan
(``-topmost``) : sinon Windows la laisserait derrière le navigateur.

Sans affichage (un serveur, WSL sans WSLg) ou sans Tk (un Python compilé sans) : ``Unavailable``,
avec la raison ; la liste de la page reste. L'arrêt du serveur (``cancel``) ferme la fenêtre.
"""

import enum
import json
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from forceupdate import processes


class PickKind(enum.StrEnum):
    FOLDER = "folder"
    FILE = "file"


class Unavailable(Exception):
    """Pas de fenêtre de choix sur cet ordinateur ; le message dit pourquoi, en français."""


TIMEOUT = 30 * 60
"""La fenêtre attend la personne ; au-delà (une demi-heure), elle est fermée."""

TITLES = {
    PickKind.FOLDER: "forceupdate : le dossier à analyser",
    PickKind.FILE: "forceupdate : le fichier à analyser",
}

SCRIPT = """\
import json
import sys

kind, start, title = sys.argv[1:4]
try:
    import tkinter
    from tkinter import filedialog
except ImportError:
    print(json.dumps({"unavailable": "tk"}))
    raise SystemExit(0)
try:
    root = tkinter.Tk()
except tkinter.TclError as err:
    print(json.dumps({"unavailable": "display", "detail": str(err)}))
    raise SystemExit(0)
root.withdraw()
root.attributes("-topmost", True)
root.update()
options = {"parent": root, "title": title}
if start:
    options["initialdir"] = start
if kind == "folder":
    chosen = filedialog.askdirectory(mustexist=True, **options)
else:
    chosen = filedialog.askopenfilename(**options)
root.destroy()
print(json.dumps({"path": chosen if isinstance(chosen, str) and chosen else None}))
"""
"""Lancé par ``python -I -c`` : il écrit sur la sortie standard, en JSON (ASCII), le chemin
choisi (``null`` : annulé), ou pourquoi il n'y a pas de fenêtre."""

Runner = Callable[..., subprocess.CompletedProcess[bytes]]


def pick(
    kind: PickKind,
    start: str | None = None,
    *,
    cancel: threading.Event | None = None,
    run: Runner = processes.run,
) -> str | None:
    """Ouvre la fenêtre et attend la personne : le chemin choisi, au format POSIX
    (``C:/Users/…``), ou ``None`` si elle a annulé (ou laissé la fenêtre une demi-heure).
    Lève ``Unavailable`` ; ``processes.Interrupted`` si ``cancel`` est levé."""
    command = [sys.executable, "-I", "-c", SCRIPT, str(kind), start or "", TITLES[kind]]
    try:
        result = run(
            command,
            capture_output=True,
            timeout=TIMEOUT,
            cancel=cancel,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return None
    except OSError as err:
        raise Unavailable(
            f"La fenêtre de choix n'a pas pu s'ouvrir ({err.strerror or err})."
        ) from err
    answer = _answer(result.stdout)
    if result.returncode != 0 or answer is None:
        said = result.stderr.decode("utf-8", "replace").strip().splitlines()
        detail = f" : {said[-1]}" if said else ""
        raise Unavailable(f"La fenêtre de choix s'est fermée sur une erreur{detail}.")
    if answer.get("unavailable") == "tk":
        raise Unavailable(
            "Pas de fenêtre de choix : le Python de forceupdate n'a pas Tk (tkinter). Choisir "
            "dans la liste, ou coller le chemin."
        )
    if answer.get("unavailable") == "display":
        raise Unavailable(
            "Pas de fenêtre de choix : pas d'affichage sur l'ordinateur où tourne forceupdate "
            "(un serveur, WSL). Choisir dans la liste, ou coller le chemin."
        )
    chosen = answer.get("path")
    return Path(chosen).as_posix() if isinstance(chosen, str) and chosen else None


def _answer(stdout: bytes) -> dict[str, Any] | None:
    """La dernière ligne JSON de la sortie ; ``None`` si elle n'en a pas."""
    for line in reversed(stdout.decode("ascii", "replace").strip().splitlines()):
        try:
            found = json.loads(line)
        except ValueError:
            continue
        if isinstance(found, dict):
            return found
    return None
