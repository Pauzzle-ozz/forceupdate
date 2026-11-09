"""Essai de la vraie fenêtre de « Parcourir… » (``web.picker``, E37), sur un ordinateur qui a un
affichage : pas un test de la suite (il ouvre une fenêtre), mais le script du workflow
« Fenêtre de choix » (``.github/workflows/picker.yml``, lancé à la main), sous macOS et sous
Linux (Xvfb). Il ouvre la fenêtre, la capture, la remplit comme une personne (``xdotool`` sous
Linux, System Events sous macOS), vérifie le chemin rendu, puis l'ouvre encore et l'annule.

Usage : ``uv run python tests/picker_desktop.py <dossier des captures>`` ; code 1 si un essai
échoue. Sous macOS, Safari est ouvert d'abord : la fenêtre doit passer devant le navigateur.
"""

import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from forceupdate.web import picker

SHOTS = Path(sys.argv[1] if len(sys.argv) > 1 else "captures")
MAC = sys.platform == "darwin"
START = Path.home() / "forceupdate-essai"
CHOSEN = START / "projet-choisi"


def shot(name: str) -> None:
    command = ["screencapture", "-x"] if MAC else ["import", "-window", "root"]
    subprocess.run([*command, str(SHOTS / f"{name}.png")], check=False)


def run(*command: str) -> str:
    done = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
    if done.returncode != 0:
        print("   ", " ".join(command[:3]), "→", done.stderr.strip()[-200:], flush=True)
    return done.stdout.strip()


def keys(*lines: str) -> None:
    """macOS : des frappes, par System Events (il faut que le terminal ait l'accessibilité)."""
    run("osascript", *[arg for line in lines for arg in ("-e", line)])


def frontmost() -> str:
    if not MAC:
        return run("xdotool", "getactivewindow", "getwindowname")
    return run(
        "osascript",
        "-e",
        'tell application "System Events" to get name of first process whose frontmost is true',
    )


def attempt(label: str, fill: bool) -> object:
    result: dict[str, object] = {}
    stop = threading.Event()

    def go() -> None:
        try:
            result["path"] = picker.pick(picker.PickKind.FOLDER, str(START), cancel=stop)
        except Exception as err:  # on le dit : c'est un essai
            result["error"] = repr(err)

    thread = threading.Thread(target=go, daemon=True)
    thread.start()
    time.sleep(6)
    print(label, "au premier plan :", frontmost(), flush=True)
    shot(f"{label}-ouverte")
    if MAC:
        # Le clic de la personne dans la fenêtre : osascript, programme d'arrière-plan, ne prend
        # pas le clavier seul (le navigateur le garde).
        keys(
            'tell application "System Events" to set frontmost of '
            '(first process whose name is "osascript") to true'
        )
        time.sleep(1)
        print(label, "après le clic, au premier plan :", frontmost(), flush=True)
        if fill:
            keys(
                'tell application "System Events" to keystroke "g" using {command down, shift down}'
            )
            time.sleep(2)
            keys(f'tell application "System Events" to keystroke "{CHOSEN}"')
            time.sleep(1)
            keys('tell application "System Events" to key code 36')  # Entrée : y aller
            time.sleep(2)
            shot(f"{label}-remplie")
            keys('tell application "System Events" to key code 36')  # Entrée : Choisir
        else:
            keys('tell application "System Events" to key code 53')  # Échap
    else:
        window = run("xdotool", "search", "--sync", "--name", "forceupdate").split()[-1]
        run("xdotool", "windowactivate", "--sync", window)
        if fill and shutil.which("zenity"):
            run("xdotool", "key", "ctrl+l")  # la barre d'adresse de GTK
            time.sleep(1)
            run("xdotool", "type", "--delay", "150", f"{CHOSEN}/")
            run("xdotool", "key", "Delete")  # ce que l'autocomplétion de GTK a ajouté
        elif fill:
            run("xdotool", "key", "End")  # Tk : « Selection » dit déjà le dossier de départ
            run("xdotool", "type", "--delay", "150", f"/{CHOSEN.name}")
        if fill:
            time.sleep(1)
            shot(f"{label}-remplie")
            run("xdotool", "key", "Return")  # y aller
            time.sleep(1)
            run("xdotool", "key", "Return")  # le choisir
        else:
            run("xdotool", "key", "Escape")
    thread.join(20)
    if thread.is_alive():
        shot(f"{label}-toujours-ouverte")
        stop.set()
        thread.join(10)
        result.setdefault("error", "la fenêtre est restée ouverte (frappes refusées ?)")
    print(label, "résultat :", result, flush=True)
    return result


SHOTS.mkdir(parents=True, exist_ok=True)
CHOSEN.mkdir(parents=True, exist_ok=True)
if MAC:
    subprocess.run(["open", "-a", "Safari", "https://example.com"], check=False)
    time.sleep(8)
    print("avant la fenêtre, au premier plan :", frontmost(), flush=True)
chosen = attempt("choisir", fill=True)
cancelled = attempt("annuler", fill=False)
ok = chosen.get("path") == CHOSEN.as_posix() and cancelled == {"path": None}  # type: ignore[union-attr]
print("RÉSULTAT :", "bon" if ok else "à regarder (captures)", flush=True)
sys.exit(0 if ok else 1)
