"""Les routes de l'API (``web/routes/``), avec le client de test de FastAPI : dossiers,
analyses, plans et mises à jour, fichier envoyé, pages du front."""

import asyncio
import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import respx
from conftest import API_BASE, API_TOKEN, FakeTools, ToolCall
from fastapi.testclient import TestClient

from forceupdate import engine
from forceupdate.models import Report
from forceupdate.report import json as json_report
from forceupdate.sources.local import LocalSource
from forceupdate.web import Settings, create_app
from forceupdate.web import jobs as jobs_module
from forceupdate.web.routes import files as files_route
from forceupdate.web.routes import fs as fs_route

PROJECTS = Path(__file__).parent / "projects"
VULNERABLE = PROJECTS / "vulnerable"

Finished = Callable[[str], dict[str, Any]]


def vulnerable_copy(tmp_path: Path) -> Path:
    root = tmp_path / "vulnerable"
    shutil.copytree(VULNERABLE, root)
    return root


def scan(api: TestClient, finished: Finished, path: Path, **options: Any) -> dict[str, Any]:
    """Lance l'analyse de ``path`` et rend son état une fois finie."""
    response = api.post("/api/scans", json={"path": str(path), **options})
    assert response.status_code == 202, response.text
    return finished(f"/api/scans/{response.json()['id']}")


def default_selection(report: dict[str, Any]) -> dict[str, str]:
    return {
        update["id"]: update["selected"]
        for project in report["projects"]
        for update in project["updates"]
        if update["selected"] is not None
    }


def plan(api: TestClient, state: dict[str, Any], selection: dict[str, str] | None = None) -> Any:
    if selection is None:
        selection = default_selection(state["report"])
    return api.post("/api/updates/plan", json={"scan": state["id"], "selection": selection})


def events(text: str) -> list[tuple[str, str, dict[str, Any]]]:
    """Les messages d'un flux SSE : (id, type, données)."""
    found = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in fields:
            found.append((fields["id"], fields["event"], json.loads(fields["data"])))
    return found


def git(root: Path, *args: str) -> None:
    command = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]
    command += ["-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args]
    subprocess.run(command, cwd=root, check=True, capture_output=True, timeout=60)


def fake_npm_and_uv(fake_tools: Callable[..., FakeTools], root: Path) -> FakeTools:
    """npm et uv simulés sur ``vulnerable`` : ils écrivent les versions choisies."""
    tools = fake_tools("npm", "uv")

    def npm(call: ToolCall) -> None:
        lock = root / "package-lock.json"
        text = lock.read_text(encoding="utf-8")
        lock.write_text(text.replace('"version": "4.17.15"', '"version": "4.18.1"'), "utf-8")

    def uv(call: ToolCall) -> None:
        lock = root / "requirements.txt"
        text = lock.read_text(encoding="utf-8").replace("flask==0.12\n", "flask==0.12.5\n")
        lock.write_text(text.replace("jinja2==2.10\n", "jinja2==2.11.3\n"), encoding="utf-8")

    tools.handlers.update(npm=npm, uv=uv)
    return tools


# -- Dossiers ---------------------------------------------------------------------


def test_the_starting_points(api: TestClient) -> None:
    listing = api.get("/api/fs").json()
    home = Path.home().as_posix()
    assert listing["path"] is None
    assert listing["parent"] is None
    assert listing["home"] == home
    assert listing["entries"][0] == {
        "name": Path.home().name,
        "path": home,
        "kind": "folder",
        "hidden": False,
    }
    drives = [entry for entry in listing["entries"] if entry["kind"] == "drive"]
    if os.name == "nt":
        assert {"name": "C:", "path": "C:/", "kind": "drive", "hidden": False} in drives
    else:
        assert drives == [{"name": "/", "path": "/", "kind": "drive", "hidden": False}]


def test_a_folder_lists_its_folders_and_dependency_files(api: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "projet"
    for folder in ("src", "Docs", ".venv", "requirements"):
        (root / folder).mkdir(parents=True)
    for name in ("package.json", "pyproject.toml", "README.md", "app.py"):
        (root / name).write_text("{}", encoding="utf-8")
    (root / "requirements" / "dev.txt").write_text("pytest\n", encoding="utf-8")
    listing = api.get("/api/fs", params={"path": str(root)}).json()
    assert listing["path"] == root.as_posix()
    assert listing["parent"] == tmp_path.as_posix()
    assert listing["truncated"] is False
    assert [(e["name"], e["kind"], e["hidden"]) for e in listing["entries"]] == [
        (".venv", "folder", True),
        ("Docs", "folder", False),
        ("requirements", "folder", False),
        ("src", "folder", False),
        ("package.json", "file", False),
        ("pyproject.toml", "file", False),
    ]
    assert listing["entries"][1]["path"] == (root / "Docs").as_posix()
    # Un fichier reconnu d'après son dossier (requirements/*.txt).
    inner = api.get("/api/fs", params={"path": str(root / "requirements")}).json()
    assert [e["name"] for e in inner["entries"]] == ["dev.txt"]


def test_symbolic_links_are_not_listed(api: TestClient, tmp_path: Path) -> None:
    (tmp_path / "vrai").mkdir()
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    try:
        os.symlink(tmp_path / "vrai", tmp_path / "lien", target_is_directory=True)
        os.symlink(tmp_path / "package.json", tmp_path / "lien.json")
    except OSError:
        pytest.skip("pas le droit de créer des liens symboliques")
    listing = api.get("/api/fs", params={"path": str(tmp_path)}).json()
    assert [e["name"] for e in listing["entries"]] == ["vrai", "package.json"]


@pytest.mark.skipif(os.name != "nt", reason="jonctions de Windows")
def test_windows_junctions_are_not_listed(api: TestClient, tmp_path: Path) -> None:
    (tmp_path / "vrai").mkdir()
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(tmp_path / "jonction"), str(tmp_path / "vrai")],
        check=True,
        capture_output=True,
    )
    assert (tmp_path / "jonction").is_dir()
    listing = api.get("/api/fs", params={"path": str(tmp_path)}).json()
    assert [e["name"] for e in listing["entries"]] == ["vrai"]


def test_a_long_folder_is_truncated(
    api: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("a", "b", "c"):
        (tmp_path / name).mkdir()
    monkeypatch.setattr(fs_route, "MAX_ENTRIES", 2)
    listing = api.get("/api/fs", params={"path": str(tmp_path)}).json()
    assert [e["name"] for e in listing["entries"]] == ["a", "b"]
    assert listing["truncated"] is True


@pytest.mark.parametrize(
    ("path", "status", "detail"),
    [
        ("relatif/dossier", 400, "« relatif/dossier » : donner un chemin absolu."),
        ("{tmp}/absent", 404, "Le dossier « {tmp}/absent » n'existe pas."),
        ("{tmp}/fichier.txt", 400, "« {tmp}/fichier.txt » n'est pas un dossier."),
    ],
)
def test_folder_errors(
    api: TestClient, tmp_path: Path, path: str, status: int, detail: str
) -> None:
    (tmp_path / "fichier.txt").write_text("", encoding="utf-8")
    tmp = str(tmp_path)
    response = api.get("/api/fs", params={"path": path.format(tmp=tmp)})
    assert response.status_code == status
    assert response.json() == {"detail": detail.format(tmp=tmp)}


def test_recent_paths(
    api: TestClient, finished: Finished, tmp_path: Path, recorded: dict[str, respx.Route]
) -> None:
    first, second = tmp_path / "un", tmp_path / "deux"
    for folder in (first, second):
        folder.mkdir()
        (folder / "requirements.txt").write_text("flask==0.12\n", encoding="utf-8")
    for folder in (first, second, first):
        scan(api, finished, folder)
    shutil.rmtree(second)
    assert api.get("/api/fs").json()["recent"] == [first.as_posix()]


# -- Analyses ---------------------------------------------------------------------


def test_a_scan_runs_in_the_background_and_gives_the_report(
    api: TestClient, finished: Finished, recorded: dict[str, respx.Route]
) -> None:
    response = api.post("/api/scans", json={"path": str(VULNERABLE)})
    assert response.status_code == 202
    started = response.json()
    assert response.headers["location"] == f"/api/scans/{started['id']}"
    assert started["source"] == VULNERABLE.resolve().as_posix()
    assert started["kind"] == "folder"
    assert started["options"] == {
        "include_tests": False,
        "dev": True,
        "transitive": False,
        "offline": False,
        "cache": True,
    }
    state = finished(f"/api/scans/{started['id']}")
    assert state["status"] == "done"
    assert state["error"] is None
    assert state["finished_at"] is not None
    assert state["progress"]["kind"] == "finished"
    report = state["report"]
    # Le JSON de « forceupdate scan --format json ».
    expected = json_report.build(engine.scan(LocalSource(VULNERABLE)))
    for document in (report, expected):
        document.pop("scanned_at")
        document.pop("oldest_data")
    assert report == expected
    assert report["summary"]["findings"]["vulnerable"] == 28
    assert api.get("/api/scans").json() == [{k: v for k, v in state.items() if k != "report"}]


def test_scan_options(
    api: TestClient, finished: Finished, recorded: dict[str, respx.Route]
) -> None:
    state = scan(api, finished, VULNERABLE, dev=False, transitive=True, offline=True, cache=False)
    assert state["options"] == {
        "include_tests": False,
        "dev": False,
        "transitive": True,
        "offline": True,
        "cache": False,
    }
    assert state["report"]["options"] == state["options"]
    # Hors ligne et sans cache : rien n'est demandé, tout est « non concluant ».
    assert not any(route.called for route in recorded.values())
    assert state["report"]["summary"]["findings"]["vulnerable"] == 0


def test_a_single_file(
    api: TestClient, finished: Finished, recorded: dict[str, respx.Route]
) -> None:
    state = scan(api, finished, VULNERABLE / "package.json")
    assert state["kind"] == "file"
    assert [p["manifests"] for p in state["report"]["projects"]] == [["package.json"]]


def test_scan_events(api: TestClient, finished: Finished, recorded: dict[str, respx.Route]) -> None:
    state = scan(api, finished, VULNERABLE)
    response = api.get(f"/api/scans/{state['id']}/events")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    received = events(response.text)
    kinds = [data.get("kind") for _, kind, data in received if kind == "progress"]
    assert kinds[:3] == ["reading", "projects_found", "checking"]
    assert kinds[-1] == "finished"
    assert kinds.count("package_checked") == 2
    assert kinds.count("vulnerabilities_checked") == 1
    assert [identifier for identifier, _, _ in received] == [str(n) for n in range(len(received))]
    assert received[-1][1:] == ("end", {"status": "done", "error": None})
    # Rebranché : seulement ce qui suit le dernier reçu.
    again = api.get(f"/api/scans/{state['id']}/events", headers={"Last-Event-ID": "4"})
    assert events(again.text) == received[5:]


def test_scan_errors(api: TestClient, tmp_path: Path) -> None:
    relative = api.post("/api/scans", json={"path": "tests/projects/npm"})
    assert relative.status_code == 400
    assert relative.json() == {"detail": "« tests/projects/npm » : donner un chemin absolu."}
    missing = api.post("/api/scans", json={"path": str(tmp_path / "absent")})
    assert missing.status_code == 404
    assert missing.json() == {"detail": f"Le chemin « {tmp_path / 'absent'} » n'existe pas."}
    assert api.post("/api/scans", json={}).status_code == 422
    for path in ("/api/scans/inconnue", "/api/scans/inconnue/events"):
        response = api.get(path)
        assert response.status_code == 404
        assert response.json() == {"detail": "Analyse inconnue : inconnue."}
    assert api.delete("/api/scans/inconnue").status_code == 404


@pytest.fixture
def stuck(monkeypatch: pytest.MonkeyPatch) -> list[asyncio.CancelledError]:
    """Des analyses qui ne finissent jamais d'elles-mêmes ; rend les annulations reçues."""
    cancelled: list[asyncio.CancelledError] = []

    async def analyze(*args: Any, **kwargs: Any) -> Report:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError as error:
            cancelled.append(error)
            raise
        raise AssertionError("inaccessible")

    monkeypatch.setattr(engine, "analyze", analyze)
    return cancelled


def test_cancel_a_scan(
    api: TestClient, tmp_path: Path, stuck: list[asyncio.CancelledError]
) -> None:
    scan_id = api.post("/api/scans", json={"path": str(tmp_path)}).json()["id"]
    assert api.get(f"/api/scans/{scan_id}").json()["status"] == "running"
    response = api.delete(f"/api/scans/{scan_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["finished_at"] is not None
    # Annuler encore ne change rien ; le flux d'événements se termine.
    assert api.delete(f"/api/scans/{scan_id}").json()["status"] == "cancelled"
    received = events(api.get(f"/api/scans/{scan_id}/events").text)
    assert received[-1][1:] == ("end", {"status": "cancelled", "error": None})
    state = api.get(f"/api/scans/{scan_id}").json()
    assert state["status"] == "cancelled"
    assert state["report"] is None
    # La tâche elle-même a bien été interrompue, dans la boucle des analyses.
    deadline = time.monotonic() + 5
    while not stuck and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(stuck) == 1


def test_a_finished_scan_cannot_be_cancelled(
    api: TestClient, finished: Finished, recorded: dict[str, respx.Route]
) -> None:
    state = scan(api, finished, VULNERABLE)
    response = api.delete(f"/api/scans/{state['id']}")
    assert response.status_code == 409
    assert response.json() == {"detail": "L'analyse est déjà finie."}


def test_a_failed_scan(
    api: TestClient, finished: Finished, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def analyze(*args: Any, **kwargs: Any) -> Report:
        raise RuntimeError("bug")

    monkeypatch.setattr(engine, "analyze", analyze)
    state = scan(api, finished, tmp_path)
    assert state["status"] == "failed"
    assert state["error"] == "erreur inattendue : RuntimeError('bug')"
    assert state["report"] is None
    events_text = api.get(f"/api/scans/{state['id']}/events").text
    assert events(events_text)[-1][1:] == (
        "end",
        {"status": "failed", "error": "erreur inattendue : RuntimeError('bug')"},
    )


# -- Plans et mises à jour --------------------------------------------------------


def test_a_plan_gives_the_diffs_and_the_lockfiles(
    api: TestClient, finished: Finished, tmp_path: Path, recorded: dict[str, respx.Route]
) -> None:
    root = vulnerable_copy(tmp_path)
    state = scan(api, finished, root)
    response = plan(api, state)
    assert response.status_code == 201
    document = response.json()
    assert response.headers["location"] == f"/api/updates/{document['id']}"
    assert document["scan"] == state["id"]
    assert document["status"] == "planned"
    assert document["selection"] == {
        ".|PyPI|flask": "0.12.5",
        ".|PyPI|jinja2|2.10": "2.11.3",
        ".|npm|lodash": "4.18.1",
    }
    assert document["applied"] == [
        {"update": ".|PyPI|flask", "version": "0.12.5"},
        {"update": ".|PyPI|jinja2|2.10", "version": "2.11.3"},
        {"update": ".|npm|lodash", "version": "4.18.1"},
    ]
    assert document["skipped"] == []
    assert [f["path"] for f in document["files"]] == ["package.json", "requirements.in"]
    assert '-    "lodash": "4.17.15"\n+    "lodash": "4.18.1"\n' in document["files"][0]["diff"]
    assert "-flask==0.12\n+flask==0.12.5\n" in document["files"][1]["diff"]
    lockfiles = document["lockfiles"]
    assert [(j["lockfile"], j["tool"], j["available"]) for j in lockfiles] == [
        ("package-lock.json", "npm", False),
        ("requirements.txt", "uv pip compile", False),
    ]
    assert lockfiles[0]["command"] == "npm install --package-lock-only --ignore-scripts"
    assert lockfiles[0]["updates"] == [{"update": ".|npm|lodash", "version": "4.18.1"}]
    assert document["uncommitted"] is None  # pas de dépôt git
    assert document["applicable"] is True
    assert document["results"] == []
    assert document["progress"] is None
    # Rien n'est écrit.
    assert (root / "package.json").read_bytes() == (VULNERABLE / "package.json").read_bytes()
    assert api.get(f"/api/updates/{document['id']}").json() == document


def test_a_plan_says_what_is_not_applied(
    api: TestClient, finished: Finished, tmp_path: Path, recorded: dict[str, respx.Route]
) -> None:
    root = vulnerable_copy(tmp_path)
    state = scan(api, finished, root)
    (root / "package.json").write_text('{"dependencies": {"lodash": "^4"}}', encoding="utf-8")
    document = plan(api, state).json()
    assert document["skipped"] == [
        {
            "update": ".|npm|lodash",
            "version": "4.18.1",
            "reason": document["skipped"][0]["reason"],
        }
    ]
    assert "a changé depuis l'analyse" in document["skipped"][0]["reason"]
    assert [f["path"] for f in document["files"]] == ["requirements.in"]


def test_plan_errors(
    api: TestClient,
    finished: Finished,
    tmp_path: Path,
    recorded: dict[str, respx.Route],
    stuck: list[asyncio.CancelledError],
) -> None:
    unknown = api.post("/api/updates/plan", json={"scan": "inconnue", "selection": {}})
    assert unknown.status_code == 404
    running = api.post("/api/scans", json={"path": str(tmp_path)}).json()
    response = api.post("/api/updates/plan", json={"scan": running["id"], "selection": {}})
    assert response.status_code == 409
    assert response.json() == {
        "detail": "L'analyse n'est pas finie : pas de rapport sur lequel préparer."
    }
    api.delete(f"/api/scans/{running['id']}")
    response = api.post("/api/updates/plan", json={"scan": running["id"], "selection": {}})
    assert response.json() == {
        "detail": "L'analyse n'a pas abouti : pas de rapport sur lequel préparer."
    }


def test_a_selection_must_match_the_report(
    api: TestClient, finished: Finished, tmp_path: Path, recorded: dict[str, respx.Route]
) -> None:
    state = scan(api, finished, vulnerable_copy(tmp_path))
    for selection, detail in [
        ({".|npm|lodash": "9.9.9"}, "Lodash : la version 9.9.9 n'est pas proposée."),
        ({"x|npm|y": "1.0.0"}, "Mise à jour inconnue : x|npm|y."),
    ]:
        response = plan(api, state, selection)
        assert response.status_code == 400
        assert response.json() == {"detail": detail}
    assert plan(api, state, {".|npm|lodash": 4}).status_code == 422  # type: ignore[dict-item]


def test_apply_writes_then_regenerates(
    api: TestClient,
    finished: Finished,
    tmp_path: Path,
    recorded: dict[str, respx.Route],
    fake_tools: Callable[..., FakeTools],
) -> None:
    root = vulnerable_copy(tmp_path)
    tools = fake_npm_and_uv(fake_tools, root)
    state = scan(api, finished, root)
    planned = plan(api, state).json()
    assert [j["available"] for j in planned["lockfiles"]] == [True, True]
    response = api.post("/api/updates/apply", json={"plan": planned["id"]})
    assert response.status_code == 202
    assert response.json()["status"] in {"running", "done"}
    assert response.json()["applicable"] is False
    document = finished(f"/api/updates/{planned['id']}")
    assert document["status"] == "done"
    assert document["error"] is None
    assert document["finished_at"] is not None
    assert [(r["lockfile"], r["status"], r["error"]) for r in document["results"]] == [
        ("package-lock.json", "regenerated", None),
        ("requirements.txt", "regenerated", None),
    ]
    assert document["results"][0]["installed"] == [
        {
            "update": ".|npm|lodash",
            "version": "4.18.1",
            "versions": ["4.18.1"],
            "reach": "exact",
            "held_by": [],
        }
    ]
    assert [call.program for call in tools.calls] == ["npm", "uv"]
    assert '"lodash": "4.18.1"' in (root / "package.json").read_text(encoding="utf-8")
    assert "flask==0.12.5" in (root / "requirements.txt").read_text(encoding="utf-8")
    received = events(api.get(f"/api/updates/{planned['id']}/events").text)
    assert [(kind, data.get("kind"), data.get("name")) for _, kind, data in received] == [
        ("progress", "written", None),
        ("progress", "regenerating", "package-lock.json"),
        ("progress", "regenerating", "requirements.txt"),
        ("progress", "finished", None),
        ("end", None, None),
    ]
    assert received[0][2]["total"] == 2
    assert [data["done"] for _, kind, data in received[1:3]] == [0, 1]
    assert received[-1][2] == {"status": "done", "error": None}
    # Un plan ne s'applique qu'une fois.
    again = api.post("/api/updates/apply", json={"plan": planned["id"]})
    assert again.status_code == 409
    assert again.json() == {"detail": "Ce plan est déjà appliqué, ou en cours d'application."}


def test_a_failing_tool_restores_the_files(
    api: TestClient,
    finished: Finished,
    tmp_path: Path,
    recorded: dict[str, respx.Route],
    fake_tools: Callable[..., FakeTools],
) -> None:
    root = vulnerable_copy(tmp_path)
    tools = fake_npm_and_uv(fake_tools, root)
    tools.handlers["npm"] = lambda call: (1, "", "npm error code ETARGET")
    state = scan(api, finished, root)
    planned = plan(api, state).json()
    api.post("/api/updates/apply", json={"plan": planned["id"]})
    document = finished(f"/api/updates/{planned['id']}")
    assert document["status"] == "done"
    npm, uv = document["results"]
    assert npm["status"] == "failed"
    assert npm["restored"] == ["package.json"]
    assert "npm error code ETARGET" in npm["error"]
    assert uv["status"] == "regenerated"
    assert (root / "package.json").read_bytes() == (VULNERABLE / "package.json").read_bytes()


def test_apply_refuses_a_file_changed_since_the_plan(
    api: TestClient, finished: Finished, tmp_path: Path, recorded: dict[str, respx.Route]
) -> None:
    root = vulnerable_copy(tmp_path)
    state = scan(api, finished, root)
    planned = plan(api, state).json()
    with (root / "requirements.in").open("a", encoding="utf-8", newline="") as file:
        file.write("# changé\n")
    api.post("/api/updates/apply", json={"plan": planned["id"]})
    document = finished(f"/api/updates/{planned['id']}")
    assert document["status"] == "failed"
    assert document["error"] == (
        "requirements.in a changé depuis le calcul du diff : rien n'est écrit, relancer la "
        "mise à jour."
    )
    assert (root / "package.json").read_bytes() == (VULNERABLE / "package.json").read_bytes()
    received = events(api.get(f"/api/updates/{planned['id']}/events").text)
    assert received == [(str(0), "end", {"status": "failed", "error": document["error"]})]


@pytest.mark.skipif(shutil.which("git") is None, reason="git absent")
def test_apply_refuses_uncommitted_files_unless_forced(
    api: TestClient, finished: Finished, tmp_path: Path, recorded: dict[str, respx.Route]
) -> None:
    root = vulnerable_copy(tmp_path)
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "départ")
    state = scan(api, finished, root)
    assert plan(api, state).json()["uncommitted"] == []
    with (root / "requirements.in").open("a", encoding="utf-8", newline="") as file:
        file.write("# en cours\n")
    state = scan(api, finished, root)
    planned = plan(api, state).json()
    assert planned["uncommitted"] == ["requirements.in"]
    response = api.post("/api/updates/apply", json={"plan": planned["id"]})
    assert response.status_code == 409
    assert response.json() == {
        "detail": "requirements.in : des changements que git n'a pas en commit. Les commiter "
        "(ou les mettre de côté) d'abord, ou appliquer avec « force »."
    }
    assert api.get(f"/api/updates/{planned['id']}").json()["status"] == "planned"
    forced = api.post("/api/updates/apply", json={"plan": planned["id"], "force": True})
    assert forced.status_code == 202
    assert finished(f"/api/updates/{planned['id']}")["status"] == "done"
    assert "flask==0.12.5" in (root / "requirements.in").read_text(encoding="utf-8")


def test_nothing_to_apply(
    api: TestClient, finished: Finished, tmp_path: Path, recorded: dict[str, respx.Route]
) -> None:
    # jinja2 se met à jour par le lockfile seul, et uv n'est pas installé : rien à faire.
    state = scan(api, finished, vulnerable_copy(tmp_path))
    planned = plan(api, state, {".|PyPI|jinja2|2.10": "2.11.3"}).json()
    assert planned["files"] == []
    assert planned["applicable"] is False
    response = api.post("/api/updates/apply", json={"plan": planned["id"]})
    assert response.status_code == 409
    assert response.json() == {"detail": "Rien à écrire ni à lancer."}


def test_update_errors(api: TestClient) -> None:
    for response in (
        api.get("/api/updates/inconnu"),
        api.get("/api/updates/inconnu/events"),
        api.get("/api/updates/inconnu/files/package.json"),
        api.post("/api/updates/apply", json={"plan": "inconnu"}),
    ):
        assert response.status_code == 404
        assert response.json() == {"detail": "Plan inconnu : inconnu."}


def test_events_of_a_plan_not_applied(
    api: TestClient, finished: Finished, tmp_path: Path, recorded: dict[str, respx.Route]
) -> None:
    state = scan(api, finished, vulnerable_copy(tmp_path))
    planned = plan(api, state).json()
    response = api.get(f"/api/updates/{planned['id']}/events")
    assert response.status_code == 409


def test_download_a_rewritten_file(
    api: TestClient, finished: Finished, tmp_path: Path, recorded: dict[str, respx.Route]
) -> None:
    root = vulnerable_copy(tmp_path)
    state = scan(api, finished, root)
    planned = plan(api, state).json()
    response = api.get(f"/api/updates/{planned['id']}/files/package.json")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"] == 'attachment; filename="package.json"'
    original = (root / "package.json").read_bytes()
    assert response.content == original.replace(b'"4.17.15"', b'"4.18.1"')
    missing = api.get(f"/api/updates/{planned['id']}/files/package-lock.json")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Ce plan ne réécrit pas « package-lock.json »."}


# -- Fichier envoyé ---------------------------------------------------------------


def test_an_uploaded_file(
    api: TestClient, finished: Finished, recorded: dict[str, respx.Route]
) -> None:
    content = (VULNERABLE / "package.json").read_bytes()
    response = api.post(
        "/api/files",
        params={"name": "package.json"},
        content=content,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 202
    started = response.json()
    assert (started["source"], started["kind"]) == ("package.json", "upload")
    state = finished(f"/api/scans/{started['id']}")
    assert state["status"] == "done"
    report = state["report"]
    assert report["source"] == "package.json"
    assert report["summary"]["findings"]["vulnerable"] == 6
    planned = plan(api, state).json()
    assert planned["lockfiles"] == []
    assert planned["uncommitted"] is None
    assert planned["applicable"] is False
    assert [f["path"] for f in planned["files"]] == ["package.json"]
    download = api.get(f"/api/updates/{planned['id']}/files/package.json")
    assert download.content == content.replace(b'"4.17.15"', b'"4.18.1"')
    refused = api.post("/api/updates/apply", json={"plan": planned["id"]})
    assert refused.status_code == 409
    assert refused.json()["detail"].startswith("Fichier envoyé : rien ne s'écrit sur le disque")
    assert api.get("/api/fs").json()["recent"] == []


def test_an_uploaded_file_is_removed_with_the_server(
    web_settings: Settings, recorded: dict[str, respx.Route]
) -> None:
    with TestClient(
        create_app(web_settings),
        base_url=API_BASE,
        headers={"Authorization": f"Bearer {API_TOKEN}"},
    ) as client:
        started = client.post(
            "/api/files", params={"name": "requirements.txt"}, content=b"flask==0.12\n"
        ).json()
        scan_state = client.app.state.jobs.scans[started["id"]]  # type: ignore[attr-defined]
        directory = scan_state.upload_dir
        assert (directory / "requirements.txt").read_bytes() == b"flask==0.12\n"
    assert not directory.exists()


@pytest.mark.parametrize(
    ("name", "detail"),
    [
        ("../package.json", "Nom de fichier invalide : « ../package.json »."),
        ("a/package.json", "Nom de fichier invalide : « a/package.json »."),
        ("a\\package.json", "Nom de fichier invalide : « a\\package.json »."),
        ("C:package.json", "Nom de fichier invalide : « C:package.json »."),
        ("..", "Nom de fichier invalide : « .. »."),
        ("", "Nom de fichier manquant."),
        (
            "notes.txt",
            "« notes.txt » n'est pas un manifeste ni un lockfile que forceupdate sait lire.",
        ),
    ],
)
def test_upload_names(api: TestClient, name: str, detail: str) -> None:
    response = api.post("/api/files", params={"name": name}, content=b"{}")
    assert response.status_code == 400
    assert response.json() == {"detail": detail}


def test_an_upload_too_big(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(files_route, "max_read_size", lambda name: 2 * 2**20)
    response = api.post(
        "/api/files", params={"name": "package.json"}, content=b" " * (2 * 2**20 + 1)
    )
    assert response.status_code == 413
    assert response.json() == {"detail": "Fichier trop gros : plus de 2 Mo."}
    assert api.get("/api/scans").json() == []


# -- Pages ------------------------------------------------------------------------


def test_pages_without_a_built_front(api: TestClient) -> None:
    response = api.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text.endswith(
        "l'interface n'est pas encore construite. L'API répond sous /api/.\n"
    )


def test_pages_of_the_built_front(api: TestClient, web_settings: Settings, tmp_path: Path) -> None:
    static = web_settings.static_dir
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>forceupdate</title>", "utf-8")
    (static / "assets" / "app.js").write_text("console.log(1)", "utf-8")
    (tmp_path / "secret.txt").write_text("secret", "utf-8")
    assert api.get("/").text.startswith("<!doctype html>")
    assert api.get("/rapport/3").text.startswith("<!doctype html>")  # adresse du front
    assert api.get("/assets/app.js").text == "console.log(1)"
    assert api.get("/assets/../../secret.txt").text.startswith("<!doctype html>")
    assert api.get("/%2E%2E/secret.txt").text.startswith("<!doctype html>")
    unknown = api.get("/api/inconnue")
    assert unknown.status_code == 404
    assert unknown.json() == {"detail": "Route inconnue."}


def test_scans_are_forgotten_beyond_the_limit(
    api: TestClient,
    finished: Finished,
    tmp_path: Path,
    recorded: dict[str, respx.Route],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(jobs_module, "MAX_SCANS", 2)
    root = vulnerable_copy(tmp_path)
    first = scan(api, finished, root)
    first_plan = plan(api, first).json()
    second = scan(api, finished, root)
    third = scan(api, finished, root)
    assert [s["id"] for s in api.get("/api/scans").json()] == [third["id"], second["id"]]
    assert api.get(f"/api/scans/{first['id']}").status_code == 404
    assert api.get(f"/api/updates/{first_plan['id']}").status_code == 404
