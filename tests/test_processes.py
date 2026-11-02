"""``processes.run`` : un programme lancé sans shell, et tout son arbre tué à son délai, ou quand
on l'arrête.

Les arbres sont faits de Python (``sys.executable``) : un enfant qui lance un petit-enfant, qui
hérite de la sortie et la garde ouverte, comme le node de ``npm.CMD`` (E30). Jamais un vrai outil.
"""

import ctypes
import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from forceupdate import processes

CHILD = textwrap.dedent(
    """
    import subprocess, sys, time
    grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    with open(sys.argv[1], "w") as f:
        f.write(str(grandchild.pid))
    print("prêt", flush=True)
    time.sleep(60)
    """
)
"""Un enfant qui lance un petit-enfant (il hérite de la sortie), note son PID, puis attend."""


def _alive(pid: int) -> bool:
    """Vrai si le processus ``pid`` tourne encore (sans le toucher : sous Windows, ``os.kill``
    le tuerait)."""
    if os.name == "nt":
        kernel = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            kernel.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _gone(pid: int, within: float = 10.0) -> bool:
    deadline = time.monotonic() + within
    while _alive(pid):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True


def _tree(tmp_path: Path) -> tuple[list[str], Path]:
    script = tmp_path / "enfant.py"
    script.write_text(CHILD, encoding="utf-8")
    marker = tmp_path / "petit-enfant.pid"
    return [sys.executable, str(script), str(marker)], marker


def test_run_returns_the_output_and_the_code() -> None:
    result = processes.run(
        [sys.executable, "-c", "import sys; print(sys.stdin.read().upper()); sys.exit(3)"],
        input=b"bonjour",
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 3
    assert result.stdout.strip() == b"BONJOUR"
    with pytest.raises(subprocess.CalledProcessError):
        processes.run([sys.executable, "-c", "raise SystemExit(1)"], check=True, timeout=60)


def test_run_never_uses_a_shell(tmp_path: Path) -> None:
    result = processes.run(
        [sys.executable, "-c", "import sys; print(sys.argv[1])", "a & echo b"],
        capture_output=True,
        timeout=60,
    )
    assert result.stdout.decode().strip() == "a & echo b"


def test_a_timeout_kills_the_whole_tree_and_returns_on_time(tmp_path: Path) -> None:
    command, marker = _tree(tmp_path)
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        processes.run(command, capture_output=True, timeout=3)
    # subprocess.run attendait la fin du petit-enfant (60 s), qui tient la sortie.
    assert time.monotonic() - start < 20
    assert _gone(int(marker.read_text()))


def test_cancel_kills_the_tree(tmp_path: Path) -> None:
    command, marker = _tree(tmp_path)
    cancel = threading.Event()
    timer = threading.Timer(2, cancel.set)
    timer.start()
    start = time.monotonic()
    try:
        with pytest.raises(processes.Interrupted):
            processes.run(command, capture_output=True, timeout=120, cancel=cancel)
    finally:
        timer.cancel()
    assert time.monotonic() - start < 20
    assert _gone(int(marker.read_text()))


def test_cancel_already_set_stops_at_once(tmp_path: Path) -> None:
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(processes.Interrupted):
        processes.run(
            [sys.executable, "-c", "import time; time.sleep(60)"], timeout=120, cancel=cancel
        )


def test_with_cancel_a_quick_program_just_finishes() -> None:
    result = processes.run(
        [sys.executable, "-c", "print('fini')"],
        capture_output=True,
        timeout=60,
        cancel=threading.Event(),
    )
    assert (result.returncode, result.stdout.strip()) == (0, b"fini")


def test_with_cancel_the_timeout_still_holds(tmp_path: Path) -> None:
    command, marker = _tree(tmp_path)
    with pytest.raises(subprocess.TimeoutExpired):
        processes.run(command, capture_output=True, timeout=3, cancel=threading.Event())
    assert _gone(int(marker.read_text()))


def test_taskkill_is_the_one_of_the_system(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYSTEMROOT", r"D:\Win")
    assert processes._taskkill() == os.path.join(r"D:\Win", "System32", "taskkill.exe")
