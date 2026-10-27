"""Ligne de commande : ``forceupdate ui``, ``scan`` et ``update``.

Pas de logique métier ici : chaque commande appelle le moteur, et les rapports (``report/``)
mettent le résultat en forme. Codes de retour : 0 rien à signaler, 1 seuil ``--fail-on``
atteint, 2 erreur.

Le JSON et le Markdown sortent toujours en UTF-8, sur la sortie standard comme dans un fichier.
Sous Windows, une sortie redirigée serait sinon écrite dans le codage de la console (cp1252) :
la sortie standard redirigée est donc repassée en UTF-8 (``_utf8_stdout``).
"""

import enum
import io
import sys
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn

from forceupdate import __version__, checks, engine
from forceupdate.checks import FailOn
from forceupdate.models import Event, EventKind, ScanOptions
from forceupdate.report import json as json_report
from forceupdate.report import markdown, terminal
from forceupdate.sources.base import SourceError
from forceupdate.sources.local import LocalSource

EXIT_FAIL_ON = 1
EXIT_ERROR = 2

FILE_WIDTH = 120
"""Largeur du rapport terminal écrit dans un fichier (``--output``)."""

app = typer.Typer(
    name="forceupdate",
    help="Trouve les dépendances à mettre à jour, et fait les mises à jour.",
    no_args_is_help=True,
    add_completion=False,
)

PathArgument = Annotated[
    Path,
    typer.Argument(help="Dossier ou fichier à traiter (par défaut, le dossier courant)."),
]


class OutputFormat(enum.StrEnum):
    TERMINAL = "terminal"
    JSON = "json"
    MD = "md"


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"forceupdate {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_print_version,
            is_eager=True,
            help="Affiche la version et quitte.",
        ),
    ] = False,
) -> None:
    """Trouve les dépendances à mettre à jour, et fait les mises à jour."""


def _fail(command: str, message: str) -> NoReturn:
    """Affiche l'erreur sur stderr, et sort avec le code d'erreur."""
    typer.echo(f"forceupdate {command} : {message}", err=True)
    raise typer.Exit(code=EXIT_ERROR)


def _not_available(command: str) -> NoReturn:
    """Commande prévue au plan mais pas encore écrite : le dire, et sortir en erreur."""
    _fail(command, "pas encore disponible.")


@app.command()
def ui() -> None:
    """Ouvre l'interface web dans le navigateur."""
    _not_available("ui")


@app.command()
def scan(
    path: PathArgument = Path("."),
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", "-f", help="Forme du rapport : terminal, json ou md."),
    ] = OutputFormat.TERMINAL,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            dir_okay=False,
            help="Écrit le rapport dans ce fichier (UTF-8) au lieu de la sortie standard.",
        ),
    ] = None,
    dev: Annotated[
        bool,
        typer.Option(
            "--dev/--no-dev", help="Vérifie aussi les dépendances de développement (par défaut)."
        ),
    ] = True,
    transitive: Annotated[
        bool,
        typer.Option(
            "--transitive",
            help=(
                "Cherche aussi les versions plus récentes, retirées ou dépréciées des "
                "dépendances indirectes (leurs failles sont toujours cherchées)."
            ),
        ),
    ] = False,
    offline: Annotated[
        bool,
        typer.Option(
            "--offline",
            help="N'interroge pas les registres : seulement le cache, le reste « non concluant ».",
        ),
    ] = False,
    no_cache: Annotated[
        bool,
        typer.Option("--no-cache", help="Ne lit ni n'écrit le cache disque."),
    ] = False,
    fail_on: Annotated[
        FailOn | None,
        typer.Option(
            "--fail-on",
            help=(
                "Sort avec le code 1 si un constat atteint ce seuil : vuln (une faille), major "
                "(faille, fin de vie, retirée, dépréciée ou majeure), any (tout ce qui est à "
                "mettre à jour)."
            ),
        ),
    ] = None,
) -> None:
    """Analyse un dossier ou un fichier : langages, dépendances, ce qui est à mettre à jour."""
    try:
        source = LocalSource(path)
    except SourceError as err:
        _fail("scan", f"{err}.")
    options = ScanOptions(dev=dev, transitive=transitive, offline=offline, cache=not no_cache)
    with _ProgressBar(Console(stderr=True)) as progress:
        report = engine.scan(source, options, on_event=progress)

    if output_format is OutputFormat.JSON:
        text = json_report.render(report)
    elif output_format is OutputFormat.MD:
        text = markdown.render(report)
    elif output is not None:
        buffer = io.StringIO()
        terminal.render(report, Console(file=buffer, width=FILE_WIDTH, color_system=None))
        text = buffer.getvalue()
    else:
        _utf8_stdout()
        terminal.render(report, Console(highlight=False))
        text = None

    if text is not None:
        if output is None:
            _utf8_stdout()
            sys.stdout.write(text)
            sys.stdout.flush()
        else:
            try:
                output.write_text(text, encoding="utf-8", newline="\n")
            except OSError as err:
                _fail("scan", f"impossible d'écrire « {output} » : {err.strerror or err}.")

    if fail_on is not None and checks.fails(report.findings, fail_on):
        raise typer.Exit(code=EXIT_FAIL_ON)


@app.command()
def update(path: PathArgument = Path(".")) -> None:
    """Met à jour les dépendances d'un dossier ou d'un fichier."""
    _not_available("update")


def _utf8_stdout() -> None:
    """Passe la sortie standard en UTF-8 si elle est redirigée (un fichier, un tube). Dans une
    console, Python écrit déjà de l'Unicode, quel que soit le codage de la console."""
    stdout = sys.stdout
    if stdout.isatty() or not isinstance(stdout, io.TextIOWrapper):
        return
    if stdout.encoding.lower().replace("-", "") != "utf8":
        stdout.reconfigure(encoding="utf-8")


class _ProgressBar:
    """Affiche les événements du moteur en barre de progression, sur la sortie d'erreur, et
    seulement dans une console : rien ne s'écrit dans une sortie redirigée."""

    def __init__(self, console: Console) -> None:
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn("{task.fields[name]}", style="dim"),
            console=console,
            transient=True,
            disable=not console.is_terminal,
        )
        self._task = self._progress.add_task("Lecture des projets", total=None, name="")

    def __enter__(self) -> "_ProgressBar":
        self._progress.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._progress.stop()

    def __call__(self, event: Event) -> None:
        if event.kind is EventKind.CHECKING:
            self._progress.update(
                self._task, description="Vérification des paquets", total=event.total, completed=0
            )
        elif event.kind is EventKind.PACKAGE_CHECKED:
            self._progress.update(self._task, completed=event.done, name=event.name or "")
        elif event.kind is EventKind.VULNERABILITIES_CHECKED:
            self._progress.update(self._task, completed=event.done, name="failles (OSV)")
