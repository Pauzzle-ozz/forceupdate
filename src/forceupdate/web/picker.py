"""La fenêtre de choix d'un dossier ou d'un fichier du système, pour l'écran 2 (session 36) : la
personne attendait du bouton « Ouvrir » la fenêtre de l'Explorateur, pas seulement une liste
dans la page. Un navigateur ne peut pas donner un chemin à une page ; le serveur, qui tourne sur
l'ordinateur de la personne, peut ouvrir cette fenêtre et rendre le chemin choisi.

Toujours dans un programme à part : une fenêtre qui plante n'emporte pas le serveur, et l'arrêt
du serveur (``cancel``) la ferme. Selon le système (E37) :

- **Windows** : Tk (``tkinter``, livré avec Python : ``askdirectory``, ``askopenfilename``), qui
  ouvre la fenêtre de l'Explorateur ; le même Python, car Tk veut le fil principal de son
  programme. Elle passe au premier plan (``-topmost``) : sinon Windows la laisserait derrière le
  navigateur (vérifié par l'utilisateur, session 37) ;
- **macOS** : ``osascript`` (``choose folder``, ``choose file``), la fenêtre du Finder, sans
  dépendre de Tk ; annuler est l'erreur -128 ; elle prend le clavier (E38) ;
- **Linux** : avec un affichage (``DISPLAY``, ``WAYLAND_DISPLAY``), ``zenity`` (GNOME) ou
  ``kdialog`` (KDE), sinon Tk ; sans affichage (un serveur, WSL sans WSLg), aucune.

Le titre et le dossier de départ passent en arguments, jamais dans le texte d'un script. Sans
fenêtre possible : ``Unavailable``, avec la raison ; la liste de la page reste.
"""

import enum
import json
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable, Mapping
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

OSASCRIPT = """\
use AppleScript version "2.4"
use framework "AppKit"
use scripting additions

on run argv
    try
        set theApp to current application's NSApplication's sharedApplication()
        theApp's setActivationPolicy:1
        theApp's activateIgnoringOtherApps:true
    end try
    set thePrompt to item 1 of argv
    set theKind to item 2 of argv
    if (count of argv) > 2 then
        set theStart to POSIX file (item 3 of argv)
        if theKind is "folder" then
            set chosen to choose folder with prompt thePrompt default location theStart
        else
            set chosen to choose file with prompt thePrompt default location theStart
        end if
    else if theKind is "folder" then
        set chosen to choose folder with prompt thePrompt
    else
        set chosen to choose file with prompt thePrompt
    end if
    return POSIX path of chosen
end run
"""
"""Le script AppleScript de macOS (``osascript -e``) : le titre, le genre, puis le dossier de
départ, en arguments. Il écrit le chemin POSIX choisi (``/Users/…/projet/``).

``osascript`` est un programme d'arrière-plan : sa fenêtre s'affichait devant le navigateur, mais
le clavier restait au navigateur jusqu'à un clic dedans, et ``activate`` n'y changeait rien (un
tel programme ne peut pas passer au premier plan ; vu sur la machine macOS de la CI, E37). Il se
déclare donc d'abord programme de premier plan, sans icône dans le Dock (AppKit :
``setActivationPolicy:`` 1, « accessory »), puis passe devant (E38). Il ne touche qu'à lui-même :
aucune autorisation de macOS, contrairement à System Events. Si macOS le refuse (``try``), la
fenêtre s'ouvre comme avant. Vérifié sur la machine macOS de la CI, sans clic : elle reçoit les
frappes (la barre de menus reste celle du navigateur : c'est le propre d'un programme
« accessory »)."""

_CANCELLED = "(-128)"
"""L'erreur d'``osascript`` quand la personne annule (« User canceled. (-128) »)."""

NO_DISPLAY = (
    "Pas de fenêtre de choix : pas d'affichage sur l'ordinateur où tourne forceupdate (un "
    "serveur, WSL). Choisir dans la liste, ou coller le chemin."
)

Runner = Callable[..., subprocess.CompletedProcess[bytes]]


def pick(
    kind: PickKind,
    start: str | None = None,
    *,
    cancel: threading.Event | None = None,
    run: Runner = processes.run,
    system: str = sys.platform,
    which: Callable[[str], str | None] = shutil.which,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    """Ouvre la fenêtre et attend la personne : le chemin choisi, au format POSIX
    (``C:/Users/…``), ou ``None`` si elle a annulé (ou laissé la fenêtre une demi-heure).
    Lève ``Unavailable`` ; ``processes.Interrupted`` si ``cancel`` est levé. ``system``,
    ``which`` et ``environ`` : ceux de l'ordinateur (les tests les fixent)."""
    environ = os.environ if environ is None else environ
    if system == "darwin" and (osascript := which("osascript")):
        command = [osascript, "-e", OSASCRIPT, TITLES[kind], str(kind)]
        result = _run(run, [*command, start] if start else command, cancel)
        if result is None or (result.returncode != 0 and _CANCELLED in _text(result.stderr)):
            return None
        return _chosen(result, _text(result.stdout).strip().rstrip("/") or "/")
    if system.startswith("linux"):
        if not (environ.get("DISPLAY") or environ.get("WAYLAND_DISPLAY")):
            raise Unavailable(NO_DISPLAY)
        if zenity := which("zenity"):
            command = [zenity, "--file-selection", f"--title={TITLES[kind]}"]
            if kind is PickKind.FOLDER:
                command.append("--directory")
            if start:
                command.append(f"--filename={start.rstrip('/')}/")
            return _desktop(run, command, cancel)
        if kdialog := which("kdialog"):
            option = "--getexistingdirectory" if kind is PickKind.FOLDER else "--getopenfilename"
            command = [kdialog, "--title", TITLES[kind], option, start or str(Path.home())]
            return _desktop(run, command, cancel)
    return _tk(kind, start, cancel, run)


def _run(
    run: Runner, command: list[str], cancel: threading.Event | None
) -> subprocess.CompletedProcess[bytes] | None:
    """Lance la fenêtre et attend ; ``None`` si elle est restée ouverte une demi-heure."""
    try:
        return run(
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


def _text(output: bytes) -> str:
    return output.decode("utf-8", "replace")


def _chosen(result: subprocess.CompletedProcess[bytes], path: str) -> str | None:
    """Le chemin écrit par une fenêtre qui a répondu (code 0) ; sinon, son erreur."""
    if result.returncode != 0:
        said = _text(result.stderr).strip().splitlines()
        detail = f" : {said[-1]}" if said else ""
        raise Unavailable(f"La fenêtre de choix s'est fermée sur une erreur{detail}.")
    return Path(path).as_posix() if path else None


def _desktop(run: Runner, command: list[str], cancel: threading.Event | None) -> str | None:
    """``zenity`` ou ``kdialog`` : le chemin, dernière ligne de la sortie ; le code 1, annulé."""
    result = _run(run, command, cancel)
    if result is None or result.returncode == 1:
        return None
    lines = _text(result.stdout).strip().splitlines()
    return _chosen(result, lines[-1].strip() if lines else "")


def _tk(
    kind: PickKind, start: str | None, cancel: threading.Event | None, run: Runner
) -> str | None:
    """La fenêtre de Tk, par le même Python (``SCRIPT``)."""
    command = [sys.executable, "-I", "-c", SCRIPT, str(kind), start or "", TITLES[kind]]
    result = _run(run, command, cancel)
    if result is None:
        return None
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
        raise Unavailable(NO_DISPLAY)
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
