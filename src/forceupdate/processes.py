"""Lancer un programme externe (npm, uv, git, gh…), et tuer tout son arbre quand il le faut.

``subprocess.run(timeout=)`` ne tue que le processus lancé. Sous Windows, c'est souvent un
lanceur qui en lance un autre : ``npm.CMD`` (``cmd.exe``, puis node), le ``git.exe`` de
``Git\\cmd`` (puis celui de ``mingw64``), ``bundle.bat``, ``composer.bat``. Vérifié le 2026-11-02
avec ``npm.CMD run`` et un délai de 3 s : sortie capturée, ``subprocess.run`` ne rend la main
qu'après 25,8 s (node, qui a hérité des tuyaux de la sortie, les tient ouverts jusqu'à sa fin) ;
sans capture, à 3 s, mais node et ses enfants tournent encore.

``run`` tue donc tout l'arbre quand le délai est dépassé, quand on l'interrompt (Ctrl+C), ou
quand ``cancel`` est levé (l'arrêt du serveur) :

- sous Windows, par ``taskkill /F /T`` (vérifié : les quatre processus de ``npm.CMD run`` tués,
  la main rendue en 3,6 s). Le programme reste dans le groupe de la console : Ctrl+C l'atteint,
  comme avant ;
- ailleurs, le programme a sa propre session (``start_new_session``), dont tout le groupe est
  tué (``killpg``). Ctrl+C dans le terminal ne l'atteint plus : c'est ``run`` qui le tue, à la
  ``KeyboardInterrupt``, ou ``cancel``.

Un descendant qui sort de l'arbre (un démon) peut garder les tuyaux : une fois l'arbre tué, la
fin de la sortie n'est attendue que ``DRAIN`` secondes.
"""

import contextlib
import os
import signal
import subprocess
import threading
import time
from collections.abc import Sequence
from typing import Any

DRAIN = 10.0
"""Attente maximale de la fin de la sortie, une fois l'arbre tué, en secondes."""

_POLL = 0.1
"""Toutes les combien de secondes ``cancel`` est regardé."""


class Interrupted(subprocess.SubprocessError):
    """Le programme a été arrêté parce que ``cancel`` a été levé."""


def run(
    command: Sequence[str],
    *,
    timeout: float | None = None,
    input: bytes | None = None,
    capture_output: bool = False,
    check: bool = False,
    cancel: threading.Event | None = None,
    **options: Any,
) -> subprocess.CompletedProcess[bytes]:
    """``subprocess.run``, sans shell : ``command`` lancé avec ``options`` (``cwd``, ``env``,
    ``stdin``, ``stdout``…), sa sortie lue, son code de retour rendu.

    Lève ``subprocess.TimeoutExpired`` après ``timeout`` secondes, ``Interrupted`` dès que
    ``cancel`` est levé, et laisse passer ``KeyboardInterrupt`` : dans les trois cas, tout l'arbre
    du programme est tué d'abord. ``cancel`` déjà levé : rien n'est lancé (un ``git push`` local
    aurait le temps de finir avant ``taskkill``). Avec ``check``, lève
    ``subprocess.CalledProcessError`` pour un code de retour non nul. ``OSError`` si le programme
    ne se lance pas."""
    if cancel is not None and cancel.is_set():
        raise Interrupted(f"{command[0]} pas lancé")
    if capture_output:
        options["stdout"] = options["stderr"] = subprocess.PIPE
    if input is not None:
        options["stdin"] = subprocess.PIPE
    if os.name != "nt":
        options["start_new_session"] = True
    with subprocess.Popen(list(command), shell=False, **options) as process:
        try:
            stdout, stderr = _communicate(process, input, timeout, cancel)
        except BaseException:
            kill_tree(process)
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.communicate(timeout=DRAIN)
            raise
    result = subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
    if check:
        result.check_returncode()
    return result


def _communicate(
    process: "subprocess.Popen[bytes]",
    input: bytes | None,
    timeout: float | None,
    cancel: threading.Event | None,
) -> tuple[bytes, bytes]:
    """La sortie de ``process``, une fois fini ; ``cancel`` regardé toutes les ``_POLL``
    secondes. Rappeler ``communicate`` après un délai dépassé est permis (sans ``input``)."""
    if cancel is None:
        return process.communicate(input, timeout=timeout)
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        if cancel.is_set():
            raise Interrupted(f"{process.args[0]} arrêté")
        wait = _POLL if deadline is None else max(0.0, min(_POLL, deadline - time.monotonic()))
        try:
            return process.communicate(input, timeout=wait)
        except subprocess.TimeoutExpired:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(process.args, timeout or 0.0) from None
        input = None


def kill_tree(process: "subprocess.Popen[bytes]") -> None:
    """Tue ``process`` et tous ses descendants."""
    if os.name == "nt":
        if process.poll() is None:  # fini, son arbre ne se retrouve plus
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                subprocess.run(
                    [_taskkill(), "/F", "/T", "/PID", str(process.pid)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=30,
                    check=False,
                )
    else:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGKILL)
    with contextlib.suppress(OSError):
        process.kill()


def _taskkill() -> str:
    """``taskkill.exe`` du système, par son chemin : jamais un autre du dossier courant ou du
    ``PATH``."""
    return os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32", "taskkill.exe")
