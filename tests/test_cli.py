"""La ligne de commande : version, ``scan``, ``update`` (``ui`` : ``test_web_server.py``)."""

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from importlib.metadata import entry_points, version
from pathlib import Path

import pytest
import respx
from conftest import FakeTools, ToolCall
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


# -- update ---------------------------------------------------------------------

VULNERABLE = PROJECTS / "vulnerable"


def update(*args: str, input: str | None = None) -> Result:
    """``forceupdate update``, sans cache, sur 200 colonnes. Jamais d'écriture dans
    ``tests/projects`` : sur un mini-projet, seulement avec ``--dry-run``."""
    assert "--dry-run" in args or not args[0].startswith(str(PROJECTS))
    return runner.invoke(app, ["update", *args, "--no-cache"], env={"COLUMNS": "200"}, input=input)


def test_update_shows_the_default_selection(recorded: dict[str, respx.Route]) -> None:
    result = update(str(VULNERABLE), "--dry-run")

    assert result.exit_code == 0, result.output
    rows = words(result.stdout)
    assert ["Paquet", "Version", "Écart", "Failles", "Changement"] in rows
    assert [
        "lodash", "4.17.15", "→", "4.18.1", "mineure", "6", "sur", "6",
        "package.json", ":", "4.17.15", "→", "4.18.1",
    ] in rows  # fmt: skip
    assert [
        "flask", "0.12", "→", "0.12.5", "correctif", "1", "sur", "4",
        "requirements.in", ":", "==0.12", "→", "==0.12.5",
    ] in rows  # fmt: skip
    assert ["puis", "requirements.txt"] in rows
    assert [
        "jinja2", "(indirecte)", "2.10", "→", "2.11.3", "mineure", "2", "sur", "6",
        "requirements.txt", "(lockfile", "seul)",
    ] in rows  # fmt: skip
    lines = [line.strip() for line in result.stdout.splitlines()]
    assert "Proposées, non cochées" in lines
    assert any(line.startswith("flask 0.12 → 3.1.3") for line in lines)
    assert "Mises à jour choisies : 3 sur 4 paquets à mettre à jour (--level minor)." in lines
    # Puis le diff des manifestes, les lockfiles à régénérer, et rien n'est écrit.
    diff = lines[lines.index("Fichiers à réécrire") + 1 : lines.index("Lockfiles à régénérer")]
    assert diff == [
        "--- a/package.json",
        "+++ b/package.json",
        "@@ -3,6 +3,6 @@",
        '"version": "1.0.0",',
        '"private": true,',
        '"dependencies": {',
        '-    "lodash": "4.17.15"',
        '+    "lodash": "4.18.1"',
        "}",
        "}",
        "--- a/requirements.in",
        "+++ b/requirements.in",
        "@@ -1,2 +1,2 @@",
        "# Une vieille application Flask ; requirements.txt est compilé avec uv pip compile.",
        "-flask==0.12",
        "+flask==0.12.5",
        "",
    ]
    # Les outils ne sont pas installés pendant les tests (tests/conftest.py).
    assert lines[lines.index("Lockfiles à régénérer") + 1 :] == [
        "package-lock.json npm n'est pas installé : « npm install --package-lock-only "
        "--ignore-scripts » à lancer soi-même.",
        "requirements.txt  uv n'est pas installé : « uv pip compile requirements.in -o "
        "requirements.txt --python-version 3.7 -P flask==0.12.5 -P jinja2==2.11.3 » à lancer "
        "soi-même.",
        "Pas repris de l'en-tête de requirements.txt : --exclude-newer 2019-01-01, qui "
        "écarterait les versions choisies.",
        "uv construit les paquets publiés sans wheel dont il lit les dépendances, et le projet "
        "si elles sont dynamiques : leur code de construction s'exécute.",
        "",
        "Rien n'est écrit (--dry-run).",
    ]


@pytest.mark.parametrize(
    ("options", "chosen"),
    [
        (["--level", "patch"], "3 sur 4"),
        (["--level", "major"], "4 sur 4"),
        (["--security-only"], "3 sur 4"),
        (["--include", "lodash", "--include", "flask"], "2 sur 4"),
        (["--exclude", "*"], "0 sur 4"),
        (["--ecosystem", "npm"], "1 sur 4"),
        (["--ecosystem", "pypi", "--no-dev"], "2 sur 4"),
    ],
)
def test_update_options(recorded: dict[str, respx.Route], options: list[str], chosen: str) -> None:
    result = update(str(VULNERABLE), *options, "--dry-run")
    assert result.exit_code == 0, result.output
    assert f"Mises à jour choisies : {chosen} paquets à mettre à jour" in result.stdout


def test_update_with_nothing_to_do(recorded: dict[str, respx.Route], make_tree: MakeTree) -> None:
    root = make_tree({"requirements.txt": "flask==3.1.3\n"})
    result = update(str(root))
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[-1] == "Rien à mettre à jour."


def test_update_with_nothing_chosen(recorded: dict[str, respx.Route], tmp_path: Path) -> None:
    root = vulnerable_copy(tmp_path)
    result = update(str(root), "--exclude", "*")
    assert result.exit_code == 0, result.output
    assert "Fichiers à réécrire" not in result.stdout
    assert unchanged(root)


def vulnerable_copy(tmp_path: Path) -> Path:
    root = tmp_path / "vulnerable"
    shutil.copytree(VULNERABLE, root)
    return root


def unchanged(root: Path) -> bool:
    return all(
        (root / name).read_bytes() == (VULNERABLE / name).read_bytes()
        for name in ("package.json", "requirements.in", "requirements.txt", "package-lock.json")
    )


REWRITTEN = {
    "package.json": ('"lodash": "4.17.15"', '"lodash": "4.18.1"'),
    "requirements.in": ("flask==0.12\n", "flask==0.12.5\n"),
}


def rewritten(root: Path) -> bool:
    """Vrai si les deux manifestes de ``vulnerable`` sont réécrits, et rien d'autre."""
    for name, (old, new) in REWRITTEN.items():
        original = (VULNERABLE / name).read_text(encoding="utf-8")
        if (root / name).read_text(encoding="utf-8") != original.replace(old, new):
            return False
    lockfiles = ("requirements.txt", "package-lock.json")
    return all((root / n).read_bytes() == (VULNERABLE / n).read_bytes() for n in lockfiles)


def test_update_dry_run_writes_nothing(recorded: dict[str, respx.Route], tmp_path: Path) -> None:
    root = vulnerable_copy(tmp_path)
    result = update(str(root), "--dry-run")
    assert result.exit_code == 0, result.output
    assert "+flask==0.12.5" in result.stdout.splitlines()
    assert unchanged(root)


def test_update_yes_writes_the_manifests(
    recorded: dict[str, respx.Route], tmp_path: Path, no_git: None
) -> None:
    root = vulnerable_copy(tmp_path)
    result = update(str(root), "--yes")
    assert result.exit_code == 0, result.output
    assert rewritten(root)
    lines = result.stdout.splitlines()
    assert "Pas de dépôt git ici : rien ne permettra de revenir en arrière." in lines
    assert lines[lines.index("Fichiers réécrits : package.json, requirements.in.") + 1 :] == [
        "package-lock.json : à régénérer, npm n'est pas installé : « npm install "
        "--package-lock-only --ignore-scripts ».",
        "requirements.txt : à régénérer, uv n'est pas installé : « uv pip compile requirements.in "
        "-o requirements.txt --python-version 3.7 -P flask==0.12.5 -P jinja2==2.11.3 ».",
    ]


@pytest.mark.parametrize(
    ("answer", "written"), [("o\n", True), ("oui\n", True), ("n\n", False), ("\n", False)]
)
def test_update_asks_before_writing(
    recorded: dict[str, respx.Route], tmp_path: Path, answer: str, written: bool
) -> None:
    root = vulnerable_copy(tmp_path)
    result = update(str(root), input=answer)
    assert result.exit_code == 0, result.output
    assert "Réécrire 2 fichiers ? [o/N]" in result.stdout
    assert rewritten(root) is written
    assert unchanged(root) is not written
    if not written:
        assert "Rien n'est écrit." in result.stdout.splitlines()


def test_update_without_an_answer(recorded: dict[str, respx.Route], tmp_path: Path) -> None:
    root = vulnerable_copy(tmp_path)
    result = update(str(root))
    assert result.exit_code == EXIT_ERROR
    assert "forceupdate update : pas de réponse, rien n'est écrit." in result.stderr
    assert unchanged(root)


def git(root: Path, *args: str) -> None:
    command = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]
    command += ["-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args]
    subprocess.run(command, cwd=root, check=True, capture_output=True, timeout=60)


@pytest.mark.skipif(shutil.which("git") is None, reason="git absent")
def test_update_refuses_uncommitted_manifests(
    recorded: dict[str, respx.Route], tmp_path: Path
) -> None:
    root = vulnerable_copy(tmp_path)
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "départ")
    with (root / "requirements.in").open("a", encoding="utf-8", newline="") as file:
        file.write("# en cours\n")
    result = update(str(root), "--yes")
    assert result.exit_code == EXIT_ERROR
    assert result.stderr == (
        "forceupdate update : requirements.in : des changements que git n'a pas en commit. Les "
        "commiter (ou les mettre de côté) d'abord, ou relancer avec --force.\n"
    )
    assert (root / "package.json").read_bytes() == (VULNERABLE / "package.json").read_bytes()
    # --force écrit quand même ; et un dépôt propre ne bloque rien.
    assert update(str(root), "--yes", "--force").exit_code == 0
    assert "flask==0.12.5" in (root / "requirements.in").read_text(encoding="utf-8")
    git(root, "commit", "-q", "-am", "mise à jour")
    assert update(str(root), "--yes", "--level", "major").exit_code == 0
    assert "flask==3.1.3" in (root / "requirements.in").read_text(encoding="utf-8")


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


def test_update_regenerates_the_lockfiles(
    recorded: dict[str, respx.Route],
    tmp_path: Path,
    fake_tools: Callable[..., FakeTools],
) -> None:
    root = vulnerable_copy(tmp_path)
    tools = fake_npm_and_uv(fake_tools, root)
    result = update(str(root), input="o\n")
    assert result.exit_code == 0, result.output
    assert "Réécrire 2 fichiers et régénérer 2 lockfiles ? [o/N]" in result.stdout
    lines = [line.strip() for line in result.stdout.splitlines()]
    assert lines[lines.index("Fichiers réécrits : package.json, requirements.in.") :] == [
        "Fichiers réécrits : package.json, requirements.in.",
        "package-lock.json : régénéré (npm).",
        "lodash 4.18.1",
        "requirements.txt : régénéré (uv pip compile).",
        "flask              0.12.5",
        "jinja2 (indirecte) 2.11.3",
    ]
    assert [call.program for call in tools.calls] == ["npm", "uv"]
    assert "flask==0.12.5" in (root / "requirements.txt").read_text(encoding="utf-8")


def test_update_says_when_a_lockfile_fails(
    recorded: dict[str, respx.Route],
    tmp_path: Path,
    fake_tools: Callable[..., FakeTools],
) -> None:
    root = vulnerable_copy(tmp_path)
    tools = fake_npm_and_uv(fake_tools, root)
    tools.handlers["npm"] = lambda call: (1, "", "npm error code ETARGET\nnpm error pas de 4.18.1")
    result = update(str(root), "--yes")
    assert result.exit_code == EXIT_ERROR, result.output
    lines = [line.strip() for line in result.stdout.splitlines()]
    assert lines[lines.index("Fichiers réécrits : requirements.in.") :][:5] == [
        "Fichiers réécrits : requirements.in.",
        "package-lock.json : échec de npm ; remis comme avant : package.json.",
        "« npm install --package-lock-only --ignore-scripts --no-audit --no-fund » a échoué "
        "(code 1) :",
        "npm error code ETARGET",
        "npm error pas de 4.18.1",
    ]
    assert (root / "package.json").read_bytes() == (VULNERABLE / "package.json").read_bytes()
    assert "flask==0.12.5" in (root / "requirements.txt").read_text(encoding="utf-8")


def test_update_by_the_lockfile_alone(
    recorded: dict[str, respx.Route],
    tmp_path: Path,
    fake_tools: Callable[..., FakeTools],
) -> None:
    root = vulnerable_copy(tmp_path)
    tools = fake_npm_and_uv(fake_tools, root)
    result = update(str(root), "--include", "jinja2", input="o\n")
    assert result.exit_code == 0, result.output
    assert "Aucun manifeste à réécrire." in result.stdout
    assert "Régénérer 1 lockfile ? [o/N]" in result.stdout
    assert [call.arguments[-2:] for call in tools.calls] == [["-P", "jinja2==2.11.3"]]


@pytest.mark.skipif(shutil.which("git") is None, reason="git absent")
def test_update_refuses_an_uncommitted_lockfile(
    recorded: dict[str, respx.Route],
    tmp_path: Path,
    fake_tools: Callable[..., FakeTools],
) -> None:
    root = vulnerable_copy(tmp_path)
    fake_npm_and_uv(fake_tools, root)
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "départ")
    with (root / "package-lock.json").open("a", encoding="utf-8", newline="") as file:
        file.write("\n")
    result = update(str(root), "--yes")
    assert result.exit_code == EXIT_ERROR
    assert result.stderr.startswith("forceupdate update : package-lock.json : des changements")
    assert (root / "package.json").read_bytes() == (VULNERABLE / "package.json").read_bytes()


def test_update_missing_path(tmp_path: Path) -> None:
    missing = tmp_path / "absent"
    result = runner.invoke(app, ["update", str(missing)])
    assert result.exit_code == EXIT_ERROR
    assert result.stderr == f"forceupdate update : le chemin « {missing} » n'existe pas.\n"


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
