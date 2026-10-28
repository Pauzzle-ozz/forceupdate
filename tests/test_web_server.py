"""Le serveur autour des routes : les tâches de fond (``web.jobs``), le flux SSE, le schéma
OpenAPI exporté, le vrai serveur uvicorn (``web.serve``) et la commande ``ui``."""

import asyncio
import json
import signal
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from conftest import API_BASE, API_TOKEN
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from forceupdate import cli, engine
from forceupdate.models import Event, EventKind, Report, ScanOptions
from forceupdate.net import Cache, HttpClient
from forceupdate.web import app as app_module
from forceupdate.web import jobs as jobs_module
from forceupdate.web import openapi
from forceupdate.web.jobs import Progress, Recent, Worker

PROJECTS = Path(__file__).parent / "projects"

# -- Tâches de fond ---------------------------------------------------------------


def test_scans_share_one_client_and_one_cache_off_the_server_loop(
    api: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[HttpClient | None, Cache | None, str, ScanOptions]] = []
    server_thread = threading.get_ident()

    async def analyze(source: Any, options: ScanOptions, **kwargs: Any) -> Report:
        assert threading.get_ident() != server_thread
        seen.append((kwargs["http"], kwargs["cache"], threading.current_thread().name, options))
        return Report(source=source.origin)

    monkeypatch.setattr(engine, "analyze", analyze)
    for options in ({}, {}, {"offline": True}, {"cache": False}):
        scan_id = api.post("/api/scans", json={"path": str(tmp_path), **options}).json()["id"]
        while api.get(f"/api/scans/{scan_id}").json()["status"] == "running":
            time.sleep(0.01)
    (http, cache, thread, _), (http2, cache2, _, _), offline, uncached = seen
    assert thread == "forceupdate-analyses"
    assert isinstance(http, HttpClient) and not http.offline
    assert isinstance(cache, Cache)
    assert (http2, cache2) == (http, cache)
    # Hors ligne : le moteur crée un client qui n'envoie rien ; sans cache : un cache désactivé.
    assert offline[:2] == (None, cache)
    assert uncached[:2] == (http, None)


def test_the_progress_reaches_the_server_loop_in_order(
    api: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def analyze(source: Any, options: ScanOptions, **kwargs: Any) -> Report:
        for done in range(1, 51):
            kwargs["on_event"](Event(kind=EventKind.PACKAGE_CHECKED, done=done, total=50))
            await asyncio.sleep(0)
        return Report(source=source.origin)

    monkeypatch.setattr(engine, "analyze", analyze)
    scan_id = api.post("/api/scans", json={"path": str(tmp_path)}).json()["id"]
    text = api.get(f"/api/scans/{scan_id}/events").text
    dones = [json.loads(line[6:])["done"] for line in text.splitlines() if '"kind"' in line]
    assert dones == list(range(1, 51))


def test_progress_follow_sends_pings_while_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs_module, "PING_EVERY", 0.01)

    async def main() -> list[Any]:
        progress = Progress()
        progress.add(Event(kind=EventKind.READING))
        received: list[Any] = []

        async def later() -> None:
            await asyncio.sleep(0.05)
            progress.add(Event(kind=EventKind.FINISHED))
            progress.finish()

        task = asyncio.create_task(later())
        async for item in progress.follow():
            received.append(item if item is None else (item[0], item[1].kind))
        await task
        return received

    received = asyncio.run(main())
    assert received[0] == (0, EventKind.READING)
    assert received[-1] == (1, EventKind.FINISHED)
    assert None in received[1:-1]


def test_recent_paths_file(tmp_path: Path) -> None:
    recent = Recent(tmp_path / "état" / "recent.json")
    assert recent.load() == []
    for path in ("/a", "/b", "/a", *(f"/{n}" for n in range(12))):
        recent.add(path)
    assert recent.load() == [f"/{n}" for n in range(11, 1, -1)]
    (tmp_path / "état" / "recent.json").write_text("{pas du json", encoding="utf-8")
    assert recent.load() == []
    (tmp_path / "état" / "recent.json").write_text('{"a": 1}', encoding="utf-8")
    assert recent.load() == []


def test_closing_waits_for_an_update_and_cancels_the_scans(
    web_settings: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cancelled = threading.Event()

    async def analyze(*args: Any, **kwargs: Any) -> Report:
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        raise AssertionError("inaccessible")

    monkeypatch.setattr(engine, "analyze", analyze)
    with TestClient(
        app_module.create_app(web_settings),
        base_url=API_BASE,
        headers={"Authorization": f"Bearer {API_TOKEN}"},
    ) as client:
        client.post("/api/scans", json={"path": str(tmp_path)})
    assert cancelled.is_set()


# -- Schéma OpenAPI ---------------------------------------------------------------


def test_the_exported_openapi_schema_is_up_to_date() -> None:
    exported = openapi.OPENAPI_JSON.read_text(encoding="utf-8")
    assert exported == openapi.render(), "relancer : uv run python -m forceupdate.web.openapi"


def test_the_schema_describes_every_route() -> None:
    schema = openapi.document()
    operations = {
        (method.upper(), path): operation["operationId"]
        for path, item in schema["paths"].items()
        for method, operation in item.items()
    }
    assert operations == {
        ("GET", "/api/fs"): "list_folder",
        ("POST", "/api/scans"): "start_scan",
        ("GET", "/api/scans"): "list_scans",
        ("GET", "/api/scans/{scan_id}"): "get_scan",
        ("GET", "/api/scans/{scan_id}/events"): "scan_events",
        ("DELETE", "/api/scans/{scan_id}"): "cancel_scan",
        ("POST", "/api/updates/plan"): "plan_update",
        ("POST", "/api/updates/apply"): "apply_update",
        ("GET", "/api/updates/{plan_id}"): "get_plan",
        ("GET", "/api/updates/{plan_id}/events"): "plan_events",
        ("GET", "/api/updates/{plan_id}/files/{path}"): "download_file",
        ("POST", "/api/files"): "upload_file",
    }


def test_response_fields_are_all_required_request_fields_are_not() -> None:
    components = openapi.document()["components"]["schemas"]
    assert components["Dependency"]["required"] == [
        "ecosystem",
        "name",
        "constraint",
        "resolved_constraint",
        "installed",
        "lockfile",
        "direct",
        "scope",
        "file",
        "location",
        "unverifiable_reason",
    ]
    assert components["SummaryDocument"]["required"][-1] == "to_update"
    assert components["ScanRequest"]["required"] == ["path"]
    assert components["ApplyRequest"]["required"] == ["plan"]


def test_a_type_used_both_ways_is_refused() -> None:
    from dataclasses import dataclass

    from fastapi import FastAPI

    @dataclass
    class Both:
        value: int = 0

    app = FastAPI()

    @app.post("/x", response_model=Both)
    async def handler(body: Both) -> Both:
        return body

    with pytest.raises(ValueError, match="types à la fois en entrée et en sortie : Both"):
        openapi.document(app)


def conforms(value: Any, schema: dict[str, Any], components: dict[str, Any]) -> list[str]:
    """Les écarts entre ``value`` et ``schema`` (tous les champs requis, aucun en trop)."""
    if "$ref" in schema:
        return conforms(value, components[schema["$ref"].rsplit("/", 1)[-1]], components)
    if "anyOf" in schema:
        failures = [conforms(value, option, components) for option in schema["anyOf"]]
        return [] if any(not f for f in failures) else min(failures, key=len)
    kind = schema.get("type")
    if "enum" in schema:
        return [] if value in schema["enum"] else [f"{value!r} hors de {schema['enum']}"]
    if kind == "null":
        return [] if value is None else [f"{value!r} n'est pas null"]
    if kind == "object":
        if not isinstance(value, dict):
            return [f"{value!r} n'est pas un objet"]
        properties = schema.get("properties")
        if properties is None:
            extra = schema.get("additionalProperties", {})
            return [e for item in value.values() for e in conforms(item, extra, components)]
        errors = [f"champ en trop : {key}" for key in value if key not in properties]
        errors += [
            f"champ manquant : {key}" for key in schema.get("required", []) if key not in value
        ]
        for key, item in value.items():
            if key in properties:
                errors += [f"{key}.{e}" for e in conforms(item, properties[key], components)]
        return errors
    if kind == "array":
        if not isinstance(value, list):
            return [f"{value!r} n'est pas une liste"]
        return [e for item in value for e in conforms(item, schema.get("items", {}), components)]
    expected = {"string": str, "integer": int, "number": int | float, "boolean": bool}.get(kind)
    if expected is not None and not isinstance(value, expected):
        return [f"{value!r} n'est pas {kind}"]
    return []


def test_responses_follow_the_exported_schema(
    api: TestClient,
    finished: Callable[[str], dict[str, Any]],
    tmp_path: Path,
    recorded: dict[str, respx.Route],
) -> None:
    import shutil

    root = tmp_path / "vulnerable"
    shutil.copytree(PROJECTS / "vulnerable", root)
    schema = json.loads(openapi.OPENAPI_JSON.read_text(encoding="utf-8"))
    components = schema["components"]["schemas"]

    def check(value: Any, name: str) -> None:
        assert conforms(value, {"$ref": f"#/components/schemas/{name}"}, components) == []

    started = api.post("/api/scans", json={"path": str(root)}).json()
    check(started, "ScanSummary")
    state = finished(f"/api/scans/{started['id']}")
    check(state, "ScanDetail")
    selection = {
        update["id"]: update["options"][-1]["version"]
        for project in state["report"]["projects"]
        for update in project["updates"]
    }
    planned = api.post("/api/updates/plan", json={"scan": state["id"], "selection": selection})
    check(planned.json(), "UpdatePlan")
    check(api.get("/api/fs", params={"path": str(root)}).json(), "Listing")
    check(api.get("/api/fs").json(), "Listing")
    check(api.get("/api/scans/inconnue").json(), "Error")


# -- Le vrai serveur ----------------------------------------------------------------


def test_serve_on_a_free_port_with_the_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    servers: list[Any] = []
    original = app_module.uvicorn.Server

    class Recorded(original):  # type: ignore[misc, valid-type]
        def __init__(self, config: Any) -> None:
            super().__init__(config)
            servers.append(self)

    monkeypatch.setattr(app_module.uvicorn, "Server", Recorded)
    opened: list[str] = []
    monkeypatch.setattr(app_module.webbrowser, "open", opened.append)
    announced: list[str] = []
    thread = threading.Thread(
        target=app_module.serve,
        kwargs={"announce": announced.append, "state_dir": tmp_path},
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 10
    while not (servers and servers[0].started) and time.monotonic() < deadline:
        time.sleep(0.02)
    try:
        [url] = announced
        base, _, token = url.partition("/?token=")
        assert base.startswith("http://127.0.0.1:") and len(token) >= 43
        port = int(base.rsplit(":", 1)[1])
        assert port > 0
        while not opened and time.monotonic() < deadline:
            time.sleep(0.02)
        assert opened == [url]
        with httpx.Client(base_url=base, follow_redirects=True) as client:
            assert client.get("/api/scans").status_code == 401
            entry = client.get(f"/?token={token}")
            assert entry.status_code == 200  # après la redirection, avec le cookie
            assert client.get("/api/scans").json() == []
            assert client.get("/api/scans", headers={"Host": "evil.example"}).status_code == 400
        # Seulement sur 127.0.0.1.
        assert servers[0].servers[0].sockets[0].getsockname()[0] == "127.0.0.1"
    finally:
        if servers:
            servers[0].should_exit = True
        thread.join(10)
    assert not thread.is_alive()


def test_the_analyses_loop_leaves_the_ctrl_c_wakeup_to_the_server() -> None:
    def wakeup() -> int:
        current = signal.set_wakeup_fd(-1)
        signal.set_wakeup_fd(current)
        return current

    before = wakeup()
    worker = Worker(Cache.disabled())
    worker.start()
    during = wakeup()
    worker.stop()
    assert before == during == wakeup()


def test_ctrl_c_stops_the_server_cleanly_during_a_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cancelled = threading.Event()

    async def analyze(*args: Any, **kwargs: Any) -> Report:
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        raise AssertionError("inaccessible")

    monkeypatch.setattr(engine, "analyze", analyze)
    announced: list[str] = []

    def press_ctrl_c() -> None:
        deadline = time.monotonic() + 10
        while not announced and time.monotonic() < deadline:
            time.sleep(0.02)
        base, _, token = announced[0].partition("/?token=")
        with httpx.Client(base_url=base, headers={"Authorization": f"Bearer {token}"}) as client:
            while True:
                try:
                    client.post("/api/scans", json={"path": str(tmp_path)})
                    break
                except httpx.ConnectError:
                    time.sleep(0.02)
        signal.raise_signal(signal.SIGINT)

    thread = threading.Thread(target=press_ctrl_c, daemon=True)
    thread.start()
    start = time.monotonic()
    try:
        app_module.serve(browser=False, announce=announced.append, state_dir=tmp_path)
    except KeyboardInterrupt:
        pytest.fail("Ctrl+C est sorti de serve")
    assert time.monotonic() - start < 10
    assert cancelled.is_set()
    thread.join(5)


def test_serve_refuses_a_taken_port(tmp_path: Path) -> None:
    taken = app_module._bind(0)
    taken.listen()
    try:
        with pytest.raises(OSError):
            app_module.serve(port=taken.getsockname()[1], browser=False, state_dir=tmp_path)
    finally:
        taken.close()


# -- La commande ui ---------------------------------------------------------------

runner = CliRunner()


def test_ui_starts_the_server(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def serve(**kwargs: Any) -> None:
        calls.append(kwargs)
        kwargs["announce"]("http://127.0.0.1:4321/?token=abc")

    monkeypatch.setattr(app_module, "serve", serve)
    monkeypatch.setattr("forceupdate.web.serve", serve)
    result = runner.invoke(cli.app, ["ui", "--port", "4321", "--no-browser"])
    assert result.exit_code == 0, result.output
    assert calls[0]["port"] == 4321
    assert calls[0]["browser"] is False
    assert result.stdout == (
        "forceupdate : interface sur http://127.0.0.1:4321/?token=abc\n"
        "Ctrl+C pour arrêter.\n"
        "Interface arrêtée.\n"
    )
    assert runner.invoke(cli.app, ["ui"]).exit_code == 0
    assert calls[1]["port"] == 0
    assert calls[1]["browser"] is True


def test_ui_with_a_taken_port(monkeypatch: pytest.MonkeyPatch) -> None:
    def serve(**kwargs: Any) -> None:
        raise OSError(10048, "Une seule utilisation de chaque adresse de socket est permise")

    monkeypatch.setattr("forceupdate.web.serve", serve)
    result = runner.invoke(cli.app, ["ui", "--port", "4321"])
    assert result.exit_code == cli.EXIT_ERROR
    assert result.stderr == (
        "forceupdate ui : impossible d'écouter sur 127.0.0.1:4321 (Une seule utilisation de "
        "chaque adresse de socket est permise).\n"
    )


def test_ui_rejects_a_port_out_of_range() -> None:
    assert runner.invoke(cli.app, ["ui", "--port", "70000"]).exit_code == 2
