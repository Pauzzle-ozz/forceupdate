"""La mise à jour d'une source locale de bout en bout (``update.local``) : ce qu'enchaînent
``forceupdate update`` et l'API."""

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
import respx
from conftest import FakeTools

from forceupdate import engine
from forceupdate.models import Event, EventKind, Report
from forceupdate.sources.local import LocalSource
from forceupdate.update import local, planner, writers
from forceupdate.update.lockfiles import LockStatus

VULNERABLE = Path(__file__).parent / "projects" / "vulnerable"


@pytest.fixture
def analysed(tmp_path: Path, recorded: dict[str, respx.Route]) -> tuple[LocalSource, Report]:
    root = tmp_path / "vulnerable"
    shutil.copytree(VULNERABLE, root)
    source = LocalSource(root)
    return source, engine.scan(source)


def test_prepare_writes_nothing(analysed: tuple[LocalSource, Report]) -> None:
    source, report = analysed
    prepared = local.prepare(source, report, planner.select(report))
    assert [c.path for c in prepared.changes.files] == ["package.json", "requirements.in"]
    assert [job.lockfile for job in prepared.jobs] == ["package-lock.json", "requirements.txt"]
    # Aucun outil installé (garde-fou des tests) : rien ne sera régénéré.
    assert prepared.runnable == ()
    assert prepared.touched == ["package.json", "requirements.in"]
    assert not prepared.empty
    assert (source.root / "package.json").read_bytes() == (VULNERABLE / "package.json").read_bytes()
    assert local.uncommitted(source, prepared) is None  # pas de dépôt git


def test_prepare_without_lockfiles(analysed: tuple[LocalSource, Report]) -> None:
    source, report = analysed
    prepared = local.prepare(source, report, planner.select(report), regenerate=False)
    assert prepared.jobs == ()
    lockfile_only = local.prepare(source, report, {".|PyPI|jinja2|2.10": "2.11.3"})
    assert lockfile_only.changes.files == ()
    assert lockfile_only.empty  # uv n'est pas installé


def test_prepare_refuses_a_selection_foreign_to_the_report(
    analysed: tuple[LocalSource, Report],
) -> None:
    source, report = analysed
    with pytest.raises(ValueError, match="mise à jour inconnue"):
        local.prepare(source, report, {"autre|npm|x": "1.0.0"})


def test_apply_writes_regenerates_and_tells(
    analysed: tuple[LocalSource, Report], fake_tools: Callable[..., FakeTools]
) -> None:
    source, report = analysed
    tools = fake_tools("npm", "uv")
    prepared = local.prepare(source, report, planner.select(report))
    assert prepared.touched == [
        "package.json",
        "requirements.in",
        "package-lock.json",
        "requirements.txt",
    ]
    events: list[Event] = []
    results = local.apply(source, report, prepared, on_event=events.append)
    assert [r.status for r in results] == [LockStatus.REGENERATED] * 2
    assert [call.program for call in tools.calls] == ["npm", "uv"]
    assert events == [
        Event(kind=EventKind.WRITTEN, total=2),
        Event(kind=EventKind.REGENERATING, name="package-lock.json", done=0, total=2),
        Event(kind=EventKind.REGENERATING, name="requirements.txt", done=1, total=2),
        Event(kind=EventKind.FINISHED),
    ]
    assert '"lodash": "4.18.1"' in (source.root / "package.json").read_text(encoding="utf-8")


def test_apply_refuses_a_file_changed_since_prepare(
    analysed: tuple[LocalSource, Report],
) -> None:
    source, report = analysed
    prepared = local.prepare(source, report, planner.select(report))
    (source.root / "package.json").write_text("{}", encoding="utf-8")
    events: list[Event] = []
    with pytest.raises(writers.WriteError, match=r"package\.json a changé depuis le calcul"):
        local.apply(source, report, prepared, on_event=events.append)
    assert events == []
    assert "flask==0.12\n" in (source.root / "requirements.in").read_text(encoding="utf-8")
