"""Le serveur de ``forceupdate ui`` pour les tests de bout en bout du front (Playwright), et les
rapports qui servent d'exemples à ses tests de composants.

Comme les tests Python : jamais le réseau (PyPI, npm et OSV répondent par les réponses
enregistrées de ``tests/fixtures/``, ``conftest.recorded_responses``), jamais le cache ni les
chemins récents de l'utilisateur (un dossier temporaire), jamais le navigateur. Le jeton est
fixe, pour que les tests ouvrent l'adresse d'entrée ::

    uv run python tests/e2e_server.py --port 8799 --token jeton-e2e

Le front servi est celui de ``src/forceupdate/web/static/`` (``npm run build`` d'abord).

Jamais de vrai outil de lockfile non plus : npm et uv sont simulés (``fake_which``,
``fake_spawn``, comme ``conftest.FakeTools``) ; ils écrivent dans le lockfile les versions que
leur commande demande. Les autres outils sont absents (« commande à lancer »).

Un rapport d'exemple (``--report`` : le JSON de ``scan --format json``, celui de
``GET /api/scans/{id}``, avec le chemin analysé remplacé par ``--source`` et des dates fixes)
pour les tests du front (``frontend/src/test/fixtures/``) ::

    uv run python tests/e2e_server.py --report tests/projects/vulnerable \\
        --source C:/Projets/vulnerable > frontend/src/test/fixtures/vulnerable.json
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path, PurePath
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from conftest import recorded_responses

from forceupdate import engine
from forceupdate.models import ScanOptions
from forceupdate.net import cache as cache_module
from forceupdate.report import json as json_report
from forceupdate.sources.local import LocalSource
from forceupdate.update import lockfiles
from forceupdate.web import app, security

FAKE_TOOLS = ("npm", "uv")


def fake_which(program: str) -> str | None:
    return f"/outils-e2e/{program}" if program in FAKE_TOOLS else None


def fake_spawn(command: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
    """npm : chaque version exacte de ``package.json`` (épinglée le temps du passage) passe
    dans ``package-lock.json``. uv : chaque ``-P nom==version`` passe dans le fichier ``-o``.
    Le reste des commandes ne fait rien."""
    cwd = Path(options["cwd"])
    program, *arguments = command
    if PurePath(program).name == "npm":
        _npm(cwd)
    elif PurePath(program).name == "uv" and "-o" in arguments:
        _uv(cwd / arguments[arguments.index("-o") + 1], arguments)
    return subprocess.CompletedProcess(command, 0, b"", b"")


def _npm(cwd: Path) -> None:
    manifest = json.loads((cwd / "package.json").read_text(encoding="utf-8"))
    path = cwd / "package-lock.json"
    lock = json.loads(path.read_text(encoding="utf-8"))
    for section in ("dependencies", "devDependencies"):
        for name, spec in manifest.get(section, {}).items():
            entry = lock.get("packages", {}).get(f"node_modules/{name}")
            if entry is not None and re.fullmatch(r"\d+\.\d+\.\d+", spec):
                entry["version"] = spec
                entry["resolved"] = (
                    f"https://registry.npmjs.org/{name}/-/{name.split('/')[-1]}-{spec}.tgz"
                )
                entry.pop("integrity", None)
    path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8", newline="\n")


def _uv(output: Path, arguments: list[str]) -> None:
    text = output.read_text(encoding="utf-8")
    for index, argument in enumerate(arguments[:-1]):
        if argument == "-P":
            name, version = arguments[index + 1].split("==")
            pattern = rf"^{re.escape(name)}==\S+$"
            text = re.sub(pattern, f"{name}=={version}", text, flags=re.MULTILINE | re.IGNORECASE)
    output.write_text(text, encoding="utf-8", newline="\n")


def serve(port: int, token: str, state_dir: Path) -> None:
    security.new_token = lambda: token
    lockfiles._which = fake_which
    lockfiles._spawn = fake_spawn
    app.serve(
        port=port,
        browser=False,
        state_dir=state_dir,
        announce=lambda url: print(url, flush=True),
    )


def report(path: Path, source: str) -> None:
    """Le rapport de ``path``, comme une analyse finie de l'API, sur la sortie standard."""
    found = engine.scan(LocalSource(path), ScanOptions())
    document = json.loads(json.dumps(json_report.build(found)).replace(found.source, source))
    for name in ("scanned_at", "oldest_data"):
        document[name] = "2026-10-28T17:30:00+00:00"
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.stdout.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=8799)
    parser.add_argument("--token", default="jeton-e2e")
    parser.add_argument("--report", type=Path, help="écrire le rapport de ce dossier, et sortir")
    parser.add_argument("--source", default="/projets/exemple", help="le chemin à y montrer")
    options = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="forceupdate-e2e-") as tmp:
        cache_module.default_cache_path = lambda: Path(tmp) / "cache.sqlite3"
        with recorded_responses():
            if options.report is not None:
                report(options.report.resolve(), options.source)
            else:
                serve(options.port, options.token, Path(tmp) / "état")


if __name__ == "__main__":
    main()
