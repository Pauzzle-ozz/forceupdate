"""Télécharger le rapport (session 36) : en Markdown, en JSON, et les dépendances à mettre à jour
en CSV pour un tableur (``report.spreadsheet``), depuis l'interface (``GET
/api/scans/{id}/download``) et la ligne de commande (``scan --format csv``) ; et la fenêtre de
choix d'un dossier du système (``web.picker``, ``POST /api/fs/pick``)."""

import csv
import io
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import respx
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from forceupdate import engine, processes
from forceupdate.cli import app
from forceupdate.models import Report
from forceupdate.report import spreadsheet
from forceupdate.sources.local import LocalSource
from forceupdate.web import picker
from forceupdate.web.routes import fs as fs_route

PROJECTS = Path(__file__).parent / "projects"
VULNERABLE = PROJECTS / "vulnerable"
EOL = PROJECTS / "eol"
Routes = dict[str, respx.Route]
Finished = Callable[[str], dict[str, Any]]
runner = CliRunner()


def table(text: str) -> list[dict[str, str]]:
    """Le CSV en lignes, par colonne."""
    return list(csv.DictReader(io.StringIO(text.removeprefix(spreadsheet.BOM)), delimiter=";"))


def analyze(root: Path) -> Report:
    return engine.scan(LocalSource(root))


# ---------------------------------------------------------------------------
# Le CSV des dépendances à mettre à jour
# ---------------------------------------------------------------------------


def test_the_dependencies_to_update_of_vulnerable(recorded: Routes) -> None:
    text = spreadsheet.render(analyze(VULNERABLE))
    assert text.splitlines()[0] == ";".join(spreadsheet.HEADERS)
    lines = {line["Paquet"]: line for line in table(text)}
    assert {"flask", "lodash", "jinja2"} <= set(lines)
    flask = lines["flask"]
    assert flask["Écosystème"] == "PyPI"
    assert flask["Dépendance"] == "directe"
    assert flask["Contrainte"] == "==0.12"
    assert flask["Constats"] == "faille, majeure"
    assert flask["Gravité"] == "élevée"
    assert flask["Failles"] == "4"
    assert flask["Identifiants"].startswith("CVE-2018-1000656 GHSA-562c-5r94-xh97")
    # La version qui corrige toutes ses failles : la plus haute des corrections.
    assert flask["Corrigée en"] == "3.1.3"
    assert flask["Fichier"] == "requirements.in"
    jinja2 = lines["jinja2"]
    assert (jinja2["Dépendance"], jinja2["Utilisée"], jinja2["Fichier"]) == (
        "indirecte",
        "2.10",
        "requirements.txt",
    )


def test_a_runtime_at_its_end_of_life_is_a_line(recorded: Routes) -> None:
    lines = table(spreadsheet.render(analyze(EOL)))
    python = next(line for line in lines if line["Paquet"] == "Python")
    assert python["Écosystème"] == "runtime"
    assert python["Constats"] == "fin de vie"
    assert python["Gravité"] == "moyenne"
    assert (python["Utilisée"], python["Dernière"], python["Fichier"]) == (
        "3.8",
        "3.15.2",
        ".python-version",
    )
    # Une version plus récente, seulement : « information ».
    assert {line["Gravité"] for line in lines if line["Constats"] == "mineure"} <= {"information"}


def test_nothing_to_update_gives_the_headers_only(tmp_path: Path, recorded: Routes) -> None:
    """Une version non fixée, un non vérifiable : rien à mettre à jour, pas de ligne."""
    (tmp_path / "requirements.txt").write_text("requests\n", encoding="utf-8")
    text = spreadsheet.render(analyze(tmp_path))
    assert text == ";".join(spreadsheet.HEADERS) + "\n"


def test_scan_format_csv(recorded: Routes, tmp_path: Path) -> None:
    printed = runner.invoke(app, ["scan", str(VULNERABLE), "--no-cache", "--format", "csv"])
    assert printed.exit_code == 0, printed.output
    # Sur la sortie standard, sans BOM : un script la lit.
    assert printed.stdout.startswith("Projet;Écosystème;Paquet")
    output = tmp_path / "a-mettre-a-jour.csv"
    written = runner.invoke(
        app, ["scan", str(VULNERABLE), "--no-cache", "--format", "csv", "--output", str(output)]
    )
    assert written.exit_code == 0, written.output
    # Dans un fichier, le BOM qu'attend Excel, puis de l'UTF-8.
    data = output.read_bytes()
    assert data.startswith(b"\xef\xbb\xbfProjet;\xc3\x89cosyst\xc3\xa8me;")
    assert data.decode("utf-8-sig") == printed.stdout


# ---------------------------------------------------------------------------
# Le téléchargement, depuis l'interface
# ---------------------------------------------------------------------------


def scanned(api: TestClient, finished: Finished, path: Path) -> str:
    response = api.post("/api/scans", json={"path": str(path)})
    assert response.status_code == 202, response.text
    scan_id = response.json()["id"]
    assert finished(f"/api/scans/{scan_id}")["status"] == "done"
    return scan_id


def test_download_the_report(api: TestClient, finished: Finished, recorded: Routes) -> None:
    scan_id = scanned(api, finished, VULNERABLE)

    markdown = api.get(f"/api/scans/{scan_id}/download")
    assert markdown.status_code == 200
    assert markdown.headers["content-type"] == "text/markdown; charset=utf-8"
    disposition = markdown.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="forceupdate-vulnerable-')
    assert disposition.endswith('.md"')
    assert markdown.text.startswith("# Rapport forceupdate")

    document = api.get(f"/api/scans/{scan_id}/download", params={"format": "json"})
    assert document.headers["content-type"] == "application/json"
    assert json.loads(document.text)["schema_version"] == 1

    sheet = api.get(f"/api/scans/{scan_id}/download", params={"format": "csv"})
    assert sheet.headers["content-type"] == "text/csv; charset=utf-8"
    assert "forceupdate-vulnerable-a-mettre-a-jour-" in sheet.headers["content-disposition"]
    assert sheet.content.startswith(b"\xef\xbb\xbfProjet;")
    assert {line["Paquet"] for line in table(sheet.content.decode("utf-8"))} >= {"flask", "lodash"}


def test_download_errors(api: TestClient, tmp_path: Path) -> None:
    assert api.get("/api/scans/inconnue/download").status_code == 404
    assert api.get("/api/scans/inconnue/download", params={"format": "pdf"}).status_code == 422


def test_a_scan_without_report_has_nothing_to_download(
    api: TestClient, finished: Finished, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Une analyse échouée (ou pas finie) n'a pas de rapport."""
    scan_id = scanned(api, finished, tmp_path)
    scan = api.app.state.jobs.scans[scan_id]  # type: ignore[attr-defined]
    monkeypatch.setattr(scan, "report", None)
    response = api.get(f"/api/scans/{scan_id}/download")
    assert response.status_code == 409
    assert response.json()["detail"] == "Pas de rapport : l'analyse n'est pas finie, ou a échoué."


def test_the_name_of_the_downloaded_file() -> None:
    from datetime import UTC, datetime

    from forceupdate.web.routes.scans import DownloadFormat, download_name

    report = Report(source="x", scanned_at=datetime(2026, 11, 3, 12, tzinfo=UTC))
    assert download_name("C:/Projets/boutique", report, DownloadFormat.MD) == (
        "forceupdate-boutique-2026-11-03.md"
    )
    assert download_name("octo/mon dépôt", report, DownloadFormat.CSV) == (
        "forceupdate-mon-d-p-t-a-mettre-a-jour-2026-11-03.csv"
    )
    assert download_name("/", report, DownloadFormat.JSON) == "forceupdate-rapport-2026-11-03.json"


# ---------------------------------------------------------------------------
# La fenêtre de choix du système
# ---------------------------------------------------------------------------


def answering(stdout: str, code: int = 0, stderr: str = "") -> Callable[..., Any]:
    """Un faux ``processes.run`` : le programme de la fenêtre répond ``stdout``."""
    calls: list[list[str]] = []

    def run(command: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        return subprocess.CompletedProcess(command, code, stdout.encode(), stderr.encode())

    run.calls = calls  # type: ignore[attr-defined]
    return run


def test_the_window_gives_the_chosen_folder() -> None:
    run = answering('{"path": "C:/Users/moi/Projets/boutique"}\n')
    assert picker.pick(picker.PickKind.FOLDER, "C:/Users/moi", run=run, system="win32") == (
        "C:/Users/moi/Projets/boutique"
    )
    (command,) = run.calls  # type: ignore[attr-defined]
    # Le même Python, isolé, le script de la fenêtre, puis ce qu'elle demande.
    assert command[:3] == [sys.executable, "-I", "-c"]
    assert command[3] == picker.SCRIPT
    assert command[4:] == ["folder", "C:/Users/moi", picker.TITLES[picker.PickKind.FOLDER]]


def test_cancelled_gives_nothing() -> None:
    found = picker.pick(picker.PickKind.FILE, run=answering('{"path": null}\n'), system="win32")
    assert found is None


@pytest.mark.parametrize(
    ("stdout", "says"),
    [
        ('{"unavailable": "tk"}\n', "n'a pas Tk"),
        ('{"unavailable": "display", "detail": "no display name"}\n', "pas d'affichage"),
        ("", "s'est fermée sur une erreur"),
    ],
)
def test_no_window_says_why(stdout: str, says: str) -> None:
    with pytest.raises(picker.Unavailable, match=says):
        picker.pick(picker.PickKind.FOLDER, run=answering(stdout), system="win32")


def tools(*found: str) -> Callable[[str], str | None]:
    """Un faux ``shutil.which`` : ``found`` sont installés, dans ``/usr/bin``."""
    return lambda name: f"/usr/bin/{name}" if name in found else None


def test_macos_asks_the_finder() -> None:
    """E37 : ``osascript``, la fenêtre du Finder, sans Tk ; le titre et le dossier de départ en
    arguments, jamais dans le script."""
    run = answering("/Users/moi/Projets/boutique/\n")
    found = picker.pick(
        picker.PickKind.FOLDER, "/Users/moi", run=run, system="darwin", which=tools("osascript")
    )
    assert found == "/Users/moi/Projets/boutique"
    (command,) = run.calls  # type: ignore[attr-defined]
    assert command == [
        "/usr/bin/osascript",
        "-e",
        picker.OSASCRIPT,
        picker.TITLES[picker.PickKind.FOLDER],
        "folder",
        "/Users/moi",
    ]
    run = answering("/Users/moi/app.py\n")
    assert (
        picker.pick(picker.PickKind.FILE, run=run, system="darwin", which=tools("osascript"))
        == "/Users/moi/app.py"
    )
    assert run.calls[0][-1] == "file"  # type: ignore[attr-defined]


def test_macos_cancelled_or_failing() -> None:
    cancelled = answering("", 1, "0:120: execution error: User canceled. (-128)\n")
    mac = {"system": "darwin", "which": tools("osascript")}
    assert picker.pick(picker.PickKind.FOLDER, run=cancelled, **mac) is None  # type: ignore[arg-type]
    failing = answering("", 1, "execution error: Can't make file (-1700)\n")
    with pytest.raises(picker.Unavailable, match="-1700"):
        picker.pick(picker.PickKind.FOLDER, run=failing, **mac)  # type: ignore[arg-type]


def test_linux_without_a_display_has_no_window() -> None:
    run = answering("")
    with pytest.raises(picker.Unavailable, match="pas d'affichage"):
        picker.pick(
            picker.PickKind.FOLDER, run=run, system="linux", which=tools("zenity"), environ={}
        )
    assert run.calls == []  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("installed", "kind", "expected"),
    [
        (
            "zenity",
            picker.PickKind.FOLDER,
            [
                "/usr/bin/zenity",
                "--file-selection",
                f"--title={picker.TITLES[picker.PickKind.FOLDER]}",
                "--directory",
                "--filename=/home/moi/",
            ],
        ),
        (
            "kdialog",
            picker.PickKind.FILE,
            [
                "/usr/bin/kdialog",
                "--title",
                picker.TITLES[picker.PickKind.FILE],
                "--getopenfilename",
                "/home/moi",
            ],
        ),
    ],
)
def test_linux_asks_the_desktop(installed: str, kind: picker.PickKind, expected: list[str]) -> None:
    run = answering("/home/moi/projets/boutique\n")
    found = picker.pick(
        kind,
        "/home/moi",
        run=run,
        system="linux",
        which=tools(installed),
        environ={"WAYLAND_DISPLAY": "wayland-0"},
    )
    assert found == "/home/moi/projets/boutique"
    assert run.calls == [expected]  # type: ignore[attr-defined]
    cancelled = answering("", 1)
    linux = {"system": "linux", "which": tools(installed), "environ": {"DISPLAY": ":0"}}
    assert picker.pick(kind, run=cancelled, **linux) is None  # type: ignore[arg-type]


def test_linux_without_zenity_nor_kdialog_uses_tk() -> None:
    run = answering('{"path": "/home/moi/projet"}\n')
    found = picker.pick(
        picker.PickKind.FOLDER, run=run, system="linux", which=tools(), environ={"DISPLAY": ":0"}
    )
    assert found == "/home/moi/projet"
    assert run.calls[0][:3] == [sys.executable, "-I", "-c"]  # type: ignore[attr-defined]


def test_the_script_runs(tmp_path: Path) -> None:
    """Le script est du Python valide, et dit « pas de Tk » quand tkinter manque (la vraie
    fenêtre ne s'ouvre jamais dans les tests)."""
    blocker = tmp_path / "tkinter.py"
    blocker.write_text("raise ImportError('pas de Tk ici')\n", encoding="utf-8")
    launcher = f"import sys; sys.path.insert(0, {str(tmp_path)!r}); exec(sys.stdin.read())"
    result = subprocess.run(
        [sys.executable, "-c", launcher, "folder", "", "titre"],
        input=picker.SCRIPT.encode(),
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"unavailable": "tk"}


def test_pick_route(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[tuple[Any, ...]] = []

    def pick(kind: picker.PickKind, start: str | None, **options: Any) -> str | None:
        asked.append((kind, start, options["cancel"] is not None))
        return "C:/Users/moi/Projets/boutique"

    monkeypatch.setattr(picker, "pick", pick)
    response = api.post("/api/fs/pick", json={"kind": "folder", "start": "C:/Users/moi"})
    assert response.status_code == 200
    assert response.json() == {"path": "C:/Users/moi/Projets/boutique"}
    assert asked == [(picker.PickKind.FOLDER, "C:/Users/moi", True)]
    # Par défaut : un dossier, là où le système veut.
    assert api.post("/api/fs/pick", json={}).status_code == 200
    assert asked[-1][:2] == (picker.PickKind.FOLDER, None)


def test_pick_route_errors(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(*arguments: Any, **options: Any) -> str | None:
        raise picker.Unavailable("Pas de fenêtre de choix : pas d'affichage.")

    monkeypatch.setattr(picker, "pick", unavailable)
    response = api.post("/api/fs/pick", json={"kind": "file"})
    assert response.status_code == 503
    assert response.json() == {"detail": "Pas de fenêtre de choix : pas d'affichage."}

    def stopped(*arguments: Any, **options: Any) -> str | None:
        raise processes.Interrupted("le serveur s'arrête")

    monkeypatch.setattr(picker, "pick", stopped)
    assert api.post("/api/fs/pick", json={}).json() == {"path": None}

    # Une fenêtre déjà ouverte : pas une seconde.
    assert fs_route._picking.acquire(blocking=False)
    try:
        busy = api.post("/api/fs/pick", json={})
    finally:
        fs_route._picking.release()
    assert busy.status_code == 409
    assert "déjà ouverte" in busy.json()["detail"]
    # Sans le jeton, rien ne s'ouvre : test_web_security passe par toutes les routes.
