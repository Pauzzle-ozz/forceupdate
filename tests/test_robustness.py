"""La robustesse (E30) : encodages, interruptions, remarques sur la source.

- un fichier de dépendances en UTF-16 (``>`` de PowerShell 5.1) ou avec un BOM se lit comme en
  UTF-8 : chaque fichier de chaque mini-projet, réécrit ainsi, redonne le même inventaire ;
- la réécriture garde le BOM, et refuse l'UTF-16 en le disant ;
- une mise à jour interrompue (Ctrl+C pendant l'écriture ou un outil, arrêt du serveur) remet
  comme avant ce qui n'était pas fini ;
- ce que la source n'a pas pu lister est dit dans le rapport (``Report.notices``).
"""

import codecs
import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import respx
from conftest import API_BASE, API_TOKEN, FakeTools, ToolCall
from fastapi.testclient import TestClient
from rich.console import Console

from forceupdate import engine, processes
from forceupdate.detect.manifests import (
    decode_text,
    find_projects,
    is_runtime_file,
    match_dependency_file,
    text_encoding,
)
from forceupdate.models import Notice, Report
from forceupdate.report import json as json_report
from forceupdate.report import markdown, terminal
from forceupdate.sources import local as local_source
from forceupdate.sources.local import LocalSource
from forceupdate.update import local, planner, writers
from forceupdate.web import Settings, create_app

PROJECTS = Path(__file__).parent / "projects"
VULNERABLE = PROJECTS / "vulnerable"
BOM = codecs.BOM_UTF8


# -- Encodages ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "encoding", "text"),
    [
        (b"a\r\nb\rc\n", "utf-8", "a\nb\nc\n"),
        (BOM + b"[project]\n", "utf-8-sig", "[project]\n"),
        ("requests==2.0.0\r\n".encode("utf-16"), "utf-16", "requests==2.0.0\n"),
        (codecs.BOM_UTF16_BE + "x=1\n".encode("utf-16-be"), "utf-16", "x=1\n"),
        ("x=1\n".encode("utf-32"), "utf-32", "x=1\n"),
        ("# café\n".encode("cp1252"), "utf-8", "# caf\N{REPLACEMENT CHARACTER}\n"),
    ],
)
def test_decode_text(data: bytes, encoding: str, text: str) -> None:
    assert text_encoding(data) == encoding
    assert decode_text(data) == text


def _dependency_dirs() -> list[Path]:
    """Les dossiers des mini-projets qui ont un fichier de dépendances ou de runtime."""
    found = {
        path.parent
        for path in PROJECTS.rglob("*")
        if path.is_file()
        and (
            match_dependency_file(path.relative_to(PROJECTS).as_posix()) is not None
            or is_runtime_file(path.name)
        )
    }
    return sorted(found)


def _inventory(root: Path) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    report = engine.inventory(LocalSource(root), include_tests=True)
    dependencies = sorted(
        (
            (p.path, d.file, d.name, d.constraint, d.installed, d.location)
            for p in report.projects
            for d in p.dependencies
        ),
        key=repr,
    )
    others = sorted(
        [(p.path, n.file, n.message) for p in report.projects for n in p.notices]
        + [(p.path, r.file, r.product, r.version) for p in report.projects for r in p.runtimes],
        key=repr,
    )
    return dependencies, others


@pytest.mark.parametrize(
    "folder", _dependency_dirs(), ids=lambda path: path.relative_to(PROJECTS).as_posix()
)
def test_every_dependency_file_reads_the_same_with_a_bom_or_in_utf16(
    folder: Path, tmp_path: Path
) -> None:
    # Avant E30 : TOML, requirements, go.mod, yarn.lock, Pipfile.lock et les fichiers de version
    # ne se lisaient plus avec un BOM ; rien ne se lisait en UTF-16.
    root = tmp_path / "projet"
    shutil.copytree(folder, root)
    expected = _inventory(root)
    for file in sorted(root.iterdir()):
        if not file.is_file():
            continue
        if match_dependency_file(f"x/{file.name}") is None and not is_runtime_file(file.name):
            continue
        data = file.read_bytes()
        text = data.decode("utf-8")
        for encoded in (BOM + data, text.encode("utf-16")):
            file.write_bytes(encoded)
            assert _inventory(root) == expected, file.name
        file.write_bytes(data)


def _requirements_project(tmp_path: Path, data: bytes) -> Report:
    (tmp_path / "requirements.txt").write_bytes(data)
    return engine.inventory(LocalSource(tmp_path))


def _choice(report: Report, name: str, version: str, new: str) -> writers.Choice:
    from test_lockfiles import wanted  # l'aide des tests de la réécriture

    project = report.projects[0]
    return wanted(project, name, version, new=new)


def test_a_bom_stays_and_the_first_line_is_rewritten_in_place(tmp_path: Path) -> None:
    report = _requirements_project(tmp_path, BOM + b"flask==1.0\r\nrequests==2.0\r\n")
    (dependency,) = [d for d in report.projects[0].dependencies if d.name == "flask"]
    assert (dependency.location.line, dependency.location.column) == (1, 5)  # type: ignore[union-attr]
    changes = writers.prepare(tmp_path, [_choice(report, "flask", "1.1", "==1.1")])
    writers.write(tmp_path, changes)
    assert (tmp_path / "requirements.txt").read_bytes() == BOM + b"flask==1.1\r\nrequests==2.0\r\n"


def test_a_utf16_file_is_read_but_not_rewritten(tmp_path: Path) -> None:
    report = _requirements_project(tmp_path, "flask==1.0\r\n".encode("utf-16"))
    assert [d.name for d in report.projects[0].dependencies] == ["flask"]
    changes = writers.prepare(tmp_path, [_choice(report, "flask", "1.1", "==1.1")])
    assert changes.files == ()
    (skipped,) = changes.skipped
    assert skipped.reason == (
        "requirements.txt : en UTF-16, pas réécrit (le réenregistrer en UTF-8 pour que "
        "forceupdate le mette à jour)."
    )


# -- Interruptions --------------------------------------------------------------------------


@pytest.fixture
def analysed(tmp_path: Path, recorded: dict[str, respx.Route]) -> tuple[LocalSource, Report]:
    """``vulnerable`` analysé : package.json (npm) et requirements.in (uv pip compile), deux
    groupes de lockfiles, dans cet ordre."""
    root = tmp_path / "vulnerable"
    shutil.copytree(VULNERABLE, root)
    source = LocalSource(root)
    return source, engine.scan(source)


def _unchanged(root: Path, *paths: str) -> bool:
    return all((root / p).read_bytes() == (VULNERABLE / p).read_bytes() for p in paths)


def test_ctrl_c_while_writing_puts_back_what_was_written(
    analysed: tuple[LocalSource, Report], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, report = analysed
    prepared = local.prepare(source, report, planner.select(report))
    assert [c.path for c in prepared.changes.files] == ["package.json", "requirements.in"]
    replace = writers.replace_file
    calls = []

    def interrupted(path: Path, data: bytes) -> None:
        calls.append(path.name)
        if len(calls) == 2:
            raise KeyboardInterrupt
        replace(path, data)

    monkeypatch.setattr(writers, "replace_file", interrupted)
    with pytest.raises(KeyboardInterrupt):
        local.apply(source, report, prepared)
    assert calls == ["package.json", "requirements.in", "package.json"]
    assert _unchanged(source.root, "package.json", "requirements.in")


def test_ctrl_c_in_a_tool_puts_back_its_group_and_those_not_run(
    analysed: tuple[LocalSource, Report], fake_tools: Callable[..., FakeTools]
) -> None:
    source, report = analysed
    tools = fake_tools("npm", "uv")

    def npm(call: ToolCall) -> None:
        (source.root / "package-lock.json").write_text("{}", encoding="utf-8")
        raise KeyboardInterrupt

    tools.handlers["npm"] = npm
    prepared = local.prepare(source, report, planner.select(report))
    with pytest.raises(KeyboardInterrupt):
        local.apply(source, report, prepared)
    assert [call.program for call in tools.calls] == ["npm"]
    # Le groupe de npm (en cours) et celui d'uv (pas lancé) : comme avant.
    paths = ("package.json", "package-lock.json", "requirements.in", "requirements.txt")
    assert _unchanged(source.root, *paths)


def test_ctrl_c_in_the_second_tool_keeps_the_first_group(
    analysed: tuple[LocalSource, Report], fake_tools: Callable[..., FakeTools]
) -> None:
    source, report = analysed
    tools = fake_tools("npm", "uv")

    def uv(call: ToolCall) -> None:
        raise KeyboardInterrupt

    tools.handlers["uv"] = uv
    prepared = local.prepare(source, report, planner.select(report))
    with pytest.raises(KeyboardInterrupt):
        local.apply(source, report, prepared)
    assert [call.program for call in tools.calls] == ["npm", "uv"]
    assert '"lodash": "4.18.1"' in (source.root / "package.json").read_text(encoding="utf-8")
    assert _unchanged(source.root, "requirements.in", "requirements.txt")


def test_cancel_stops_before_the_next_tool(
    analysed: tuple[LocalSource, Report], fake_tools: Callable[..., FakeTools]
) -> None:
    source, report = analysed
    tools = fake_tools("npm", "uv")
    cancel = threading.Event()

    def npm(call: ToolCall) -> None:
        assert call.options["cancel"] is cancel
        cancel.set()  # l'arrêt du serveur, pendant que npm finit

    tools.handlers["npm"] = npm
    prepared = local.prepare(source, report, planner.select(report))
    with pytest.raises(processes.Interrupted):
        local.apply(source, report, prepared, cancel=cancel)
    assert [call.program for call in tools.calls] == ["npm"]
    assert '"lodash": "4.18.1"' in (source.root / "package.json").read_text(encoding="utf-8")
    assert _unchanged(source.root, "requirements.in", "requirements.txt")


def test_stopping_the_server_stops_the_update_and_puts_files_back(
    web_settings: Settings,
    tmp_path: Path,
    recorded: dict[str, respx.Route],
    fake_tools: Callable[..., FakeTools],
) -> None:
    root = tmp_path / "vulnerable"
    shutil.copytree(VULNERABLE, root)
    tools = fake_tools("npm", "uv")
    running = threading.Event()

    def npm(call: ToolCall) -> None:
        # Ce que fait processes.run d'un outil qui tourne quand cancel est levé : il le tue.
        running.set()
        assert call.options["cancel"].wait(30)
        raise processes.Interrupted("npm arrêté")

    tools.handlers["npm"] = npm
    with TestClient(
        create_app(web_settings),
        base_url=API_BASE,
        headers={"Authorization": f"Bearer {API_TOKEN}"},
    ) as client:
        scan_id = client.post("/api/scans", json={"path": str(root)}).json()["id"]
        state = _finished(client, f"/api/scans/{scan_id}")
        selection = {
            update["id"]: update["selected"]
            for project in state["report"]["projects"]
            for update in project["updates"]
            if update["selected"] is not None
        }
        planned = client.post(
            "/api/updates/plan", json={"scan": scan_id, "selection": selection}
        ).json()
        client.post("/api/updates/apply", json={"plan": planned["id"]})
        assert running.wait(30)
    # Sortir du client arrête le serveur : l'outil en cours est tué, uv n'est jamais lancé.
    assert [call.program for call in tools.calls] == ["npm"]
    assert _unchanged(root, "package.json", "requirements.in", "requirements.txt")


def _finished(client: TestClient, url: str) -> dict[str, Any]:
    deadline = time.monotonic() + 10
    while (state := client.get(url).json())["status"] == "running":
        assert time.monotonic() < deadline, url
        time.sleep(0.02)
    return state


# -- Remarques sur la source ----------------------------------------------------------------


def test_too_many_files_is_said_in_every_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_git: None
) -> None:
    for n in range(5):
        (tmp_path / f"p{n}").mkdir()
        (tmp_path / f"p{n}" / "requirements.txt").write_text("flask==3.0.0\n", encoding="utf-8")
    monkeypatch.setattr(local_source, "MAX_FILES", 3)
    report = engine.inventory(LocalSource(tmp_path))
    assert len(report.projects) == 3
    assert [n.file for n in report.notices] == ["."]
    message = report.notices[0].message
    assert message.startswith("plus de 3 fichiers : la liste s'arrête là")
    assert json_report.build(report)["notices"] == [{"file": ".", "message": message}]
    written = markdown.render(report)
    assert "## Remarques sur la source\n\n- `.` : plus de 3 fichiers" in written
    console = Console(record=True, width=200)
    terminal.render(report, console)
    assert "Remarques sur la source" in console.export_text()


def test_too_many_dependency_files_is_said(tmp_path: Path, no_git: None) -> None:
    notices: list[Notice] = []
    paths = [f"p{n}/package.json" for n in range(4)]
    projects, _ = find_projects(paths, max_files=2, notices=notices)
    assert [p.path for p in projects] == ["p0", "p1"]
    assert notices == [
        Notice(
            file=".",
            message="plus de 2 fichiers de dépendances : seuls les 2 premiers sont lus, dans "
            "l'ordre des chemins.",
        )
    ]
