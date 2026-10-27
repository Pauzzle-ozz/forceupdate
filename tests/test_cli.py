"""La ligne de commande : version, ``scan``, et commandes pas encore disponibles."""

import json
import os
import subprocess
import sys
from collections.abc import Callable
from importlib.metadata import entry_points, version
from pathlib import Path

import pytest
import respx
from typer.testing import CliRunner, Result

from forceupdate import __version__
from forceupdate.cli import EXIT_ERROR, EXIT_FAIL_ON, app

runner = CliRunner()
PROJECTS = Path(__file__).parent / "projects"
MakeTree = Callable[..., Path]


def test_version_comes_from_package_metadata() -> None:
    assert __version__ == version("forceupdate")


def test_version_option() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout == f"forceupdate {__version__}\n"


def test_console_script_points_to_app() -> None:
    (script,) = entry_points(group="console_scripts", name="forceupdate")
    assert script.load() is app


@pytest.mark.parametrize("args", [["ui"], ["update"], ["update", "."]])
def test_commands_not_available_yet(args: list[str]) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == EXIT_ERROR
    assert f"forceupdate {args[0]} : pas encore disponible." in result.stderr


def scan(*args: str) -> Result:
    """``forceupdate scan``, hors ligne et sans cache, sur 200 colonnes."""
    return runner.invoke(app, ["scan", *args, "--offline", "--no-cache"], env={"COLUMNS": "200"})


def words(output: str) -> list[list[str]]:
    return [line.split() for line in output.splitlines()]


def test_scan_shows_languages_and_projects(make_tree: MakeTree) -> None:
    root = make_tree(
        {
            "backend/pyproject.toml": "",
            "backend/uv.lock": "",
            "backend/app.py": "x" * 75,
            "frontend/package.json": "{}",
            "frontend/main.c": "x" * 25,
            "tests/projects/npm/package.json": "{}",
        }
    )

    result = scan(str(root))

    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines[0] == f"Source : {root.resolve().as_posix()}"
    assert lines[1].startswith("Analyse du ")
    assert lines[1].endswith(" ; hors ligne, sans données des registres ni d'OSV en cache.")
    assert "  Python   75,0 %  PyPI" in lines
    assert "  C        25,0 %  aucun gestionnaire de paquets reconnu" in lines
    assert "Projets : 2" in lines
    assert "Projet backend  (PyPI)" in lines
    assert "  lockfiles  : backend/uv.lock" in lines
    assert "Projet frontend  (npm)" in lines
    assert "  lockfiles  : aucun" in lines
    assert "Écartés, car rangés dans des dossiers de tests ou d'exemples : 1 fichier" in lines
    assert "  tests/projects/npm/package.json" in lines
    assert lines[-1] == "Résumé : 0 dépendance vérifiée, rien à mettre à jour."


def test_scan_shows_direct_dependencies() -> None:
    result = scan(str(PROJECTS / "uv"))

    assert result.exit_code == 0
    rows = words(result.stdout)
    assert ["Paquet", "Contrainte", "Utilisée", "Permise", "Dernière", "État"] in rows
    assert ["httpx", ">=0.27", "0.28.1", "non", "concluant"] in rows
    assert ["rich", "(optional)", ">=13", "15.0.0", "non", "concluant"] in rows
    assert ["hatchling", "(build)", "-", "-", "non", "concluant"] in rows
    assert ["demo-lib", "-", "0.1.0", "non", "vérifiable", ":", "membre", "du", "workspace"] in rows
    lines = result.stdout.splitlines()
    assert (
        "  dépendances directes : 5 (2 runtime, 1 optional, 1 dev, 1 build) ; indirectes : 13"
        in lines
    )
    # Sans borne basse ni lockfile, pas de version actuelle.
    assert ["requests", "<2", "-", "non", "concluant"] in rows


def test_scan_shows_notices(make_tree: MakeTree) -> None:
    root = make_tree({"Cargo.toml": "", "setup.py": ""})

    result = scan(str(root))

    lines = [line.strip() for line in result.stdout.splitlines()]
    assert "dépendances directes : aucune ; indirectes : aucune" in lines
    assert "Remarques" in lines
    notices = [" ".join(line.split()) for line in lines]
    assert "setup.py pas lu : il faudrait l'exécuter pour connaître ses dépendances." in notices
    assert "Cargo.toml dépendances crates.io pas encore lues par forceupdate." in notices


def test_scan_empty_folder(tmp_path: Path) -> None:
    result = scan(str(tmp_path))
    assert result.exit_code == 0
    assert "Langages : aucun reconnu" in result.stdout
    assert "Projets : aucun" in result.stdout


def test_scan_missing_path(tmp_path: Path) -> None:
    missing = tmp_path / "absent"
    result = runner.invoke(app, ["scan", str(missing)])
    assert result.exit_code == EXIT_ERROR
    assert result.stderr == f"forceupdate scan : le chemin « {missing} » n'existe pas.\n"


def test_scan_unknown_format(tmp_path: Path) -> None:
    result = runner.invoke(app, ["scan", str(tmp_path), "--format", "xml"])
    assert result.exit_code == EXIT_ERROR


# -- formats et fichier de sortie ---------------------------------------------


def test_scan_json_to_stdout(make_tree: MakeTree) -> None:
    root = make_tree({"requirements.txt": "flask==2.0.1\n"})
    result = scan(str(root), "--format", "json")
    assert result.exit_code == 0
    data = json.loads(result.stdout_bytes.decode("utf-8"))
    assert data["schema_version"] == 1
    assert data["options"]["offline"] is True
    findings = data["projects"][0]["findings"]
    assert [finding["kind"] for finding in findings] == ["inconclusive", "inconclusive"]
    assert [finding["message"] for finding in findings] == [
        "PyPI : mode hors ligne, et flask n'est pas dans le cache.",
        "Failles non vérifiées. OSV : mode hors ligne, sans réponse en cache.",
    ]


@pytest.mark.parametrize(
    ("output_format", "start"),
    [
        ("json", '{\n  "schema_version": 1,'),
        ("md", "# Rapport forceupdate\n"),
        ("terminal", "Source : "),
    ],
)
def test_scan_output_file(make_tree: MakeTree, output_format: str, start: str) -> None:
    root = make_tree({"projet-é/requirements.txt": "flask==2.0.1\n"})
    target = root / "rapport.txt"
    result = scan(str(root / "projet-é"), "--format", output_format, "--output", str(target))
    assert result.exit_code == 0
    assert result.stdout == ""
    text = target.read_bytes().decode("utf-8")  # UTF-8, quel que soit le système
    assert text.startswith(start)
    assert "projet-é" in text
    assert "\r\n" not in text


def test_scan_output_file_error(tmp_path: Path) -> None:
    result = scan(str(tmp_path), "--output", str(tmp_path / "absent" / "rapport.json"))
    assert result.exit_code == EXIT_ERROR
    assert "forceupdate scan : impossible d'écrire" in result.stderr


# -- --fail-on -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("requirements", "threshold", "code"),
    [
        ("flask==2.0.1\n", None, 0),  # sans --fail-on, des constats ne sont pas une erreur
        ("flask==2.0.1\n", "vuln", 0),
        ("flask==2.0.1\n", "major", EXIT_FAIL_ON),
        ("flask==3.1.2\n", "major", 0),
        ("flask==3.1.2\n", "any", EXIT_FAIL_ON),
        ("flask==3.1.3\n", "any", 0),
        ("requests==2.32.0\n", "major", EXIT_FAIL_ON),  # retirée
        ("inconnu-xyz==1.0\n", "any", 0),  # non vérifiable : ne compte pas
    ],
)
def test_fail_on(
    recorded: dict[str, respx.Route],
    make_tree: MakeTree,
    requirements: str,
    threshold: str | None,
    code: int,
) -> None:
    root = make_tree({"requirements.txt": requirements})
    args = ["scan", str(root), "--no-cache"]
    if threshold is not None:
        args += ["--fail-on", threshold]
    result = runner.invoke(app, args)
    assert result.exit_code == code, result.output


# -- sortie redirigée ----------------------------------------------------------


@pytest.mark.parametrize("output_format", ["json", "md", "terminal"])
def test_redirected_output_is_utf8(make_tree: MakeTree, output_format: str) -> None:
    """Une vraie sortie redirigée (un tube) : sous Windows, Python l'écrirait en cp1252."""
    root = make_tree({"setup.py": ""})
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    command = [sys.executable, "-m", "forceupdate", "scan", str(root)]
    command += ["--format", output_format, "--offline", "--no-cache"]
    completed = subprocess.run(command, capture_output=True, env=env, timeout=60, check=False)
    assert completed.returncode == 0, completed.stderr
    assert "il faudrait l'exécuter" in completed.stdout.decode("utf-8")
    assert completed.stderr == b""  # pas de barre de progression hors d'une console


def test_no_arguments_shows_help() -> None:
    result = runner.invoke(app, [])
    for command in ("ui", "scan", "update"):
        assert command in result.output
