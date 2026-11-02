"""Le serveur local de l'interface : FastAPI, servi par uvicorn sur ``127.0.0.1``.

``create_app`` construit l'application : les routes de ``/api`` (``web.routes``), le garde
(``web.security.Guard``), les tâches de fond (``web.jobs.Jobs``, créées au démarrage et
arrêtées à l'arrêt), et les pages du front, construit dans ``web/static/`` (E14). ``serve``
la lance pour ``forceupdate ui``.

Le schéma OpenAPI n'est pas servi : il est exporté dans ``web/openapi.json``
(``web.openapi``), d'où viennent les types du front.
"""

import contextlib
import signal
import socket
import threading
import time
import webbrowser
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import platformdirs
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, Response

from forceupdate import __version__
from forceupdate.forges.accounts import Accounts
from forceupdate.web import security
from forceupdate.web.connections import Connections
from forceupdate.web.jobs import Jobs, Recent
from forceupdate.web.preferences import UserPreferences
from forceupdate.web.proposals import Proposals
from forceupdate.web.repositories import Repositories
from forceupdate.web.routes import (
    accounts,
    files,
    fs,
    oauth,
    proposals,
    repositories,
    scans,
    settings,
    updates,
)

STATIC_DIR = Path(__file__).parent / "static"
"""Le front construit (``npm run build``, E14)."""

DESCRIPTION = (
    "L'API du serveur local de forceupdate : analyser un dossier, un fichier ou les dépôts des "
    "comptes connectés, préparer et appliquer les mises à jour, ouvrir une PR par dépôt. "
    "Chaque requête porte le jeton "
    "de session (cookie posé par l'adresse que donne « forceupdate ui », ou "
    "« Authorization: Bearer <jeton> »)."
)


@dataclass(frozen=True, kw_only=True)
class Settings:
    """Ce qu'il faut pour construire l'application."""

    token: str
    """Le jeton de session (``security.new_token``)."""
    port: int
    """Le port d'écoute : les en-têtes ``Host`` et ``Origin`` doivent le porter."""
    state_dir: Path
    """Où garder les chemins récemment analysés, et les comptes connectés (sans leurs
    tokens, qui sont dans le trousseau)."""
    static_dir: Path = STATIC_DIR
    temp_dir: Path | None = None
    """Où ranger le dossier de travail du serveur (``web.workdirs``) ; par défaut, le dossier
    temporaire du système."""


def create_app(server: Settings) -> FastAPI:
    """L'application, prête à servir."""

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        jobs = Jobs(recent=Recent(server.state_dir / "recent.json"), temp_dir=server.temp_dir)
        jobs.start()
        app.state.jobs = jobs
        app.state.preferences = preferences = UserPreferences()
        app.state.connections = Connections(
            accounts=Accounts(server.state_dir / "accounts.json"), port=server.port
        )
        app.state.repositories = Repositories(
            jobs=jobs, connections=app.state.connections, preferences=preferences
        )
        app.state.proposals = Proposals(jobs=jobs, repositories=app.state.repositories)
        try:
            yield
        finally:
            app.state.proposals.closing()
            await app.state.connections.close()
            await jobs.close()
            preferences.close()

    app = FastAPI(
        title="forceupdate",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
        # operationId : le nom de la fonction (start_scan…), pour le client généré du front.
        generate_unique_id_function=lambda route: route.name,
    )
    for module in (fs, scans, updates, files, accounts, repositories, proposals, settings, oauth):
        app.include_router(module.router)
    app.add_middleware(
        security.Guard, token=server.token, port=server.port, returns=oauth.RETURN_PATHS
    )

    @app.get("/{path:path}", include_in_schema=False)
    async def page(path: str) -> Response:
        """Les pages du front ; une adresse inconnue rend ``index.html`` (le front a ses propres
        adresses). Sans front construit, une ligne de texte."""
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Route inconnue.")
        index = server.static_dir / "index.html"
        if not index.is_file():
            return PlainTextResponse(
                f"forceupdate {__version__} : l'interface n'est pas encore construite. "
                "L'API répond sous /api/.\n"
            )
        found = _static_file(server.static_dir, path)
        return FileResponse(found or index)

    return app


def _static_file(root: Path, path: str) -> Path | None:
    """Le fichier ``path`` du front, s'il existe et reste dans ``root``."""
    if not path:
        return None
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root.resolve()) or not candidate.is_file():
        return None
    return candidate


def serve(
    *,
    port: int = 0,
    browser: bool = True,
    announce: Callable[[str], None] = print,
    state_dir: Path | None = None,
) -> None:
    """Lance le serveur sur ``127.0.0.1:port`` (un port libre pour 0), ouvre le navigateur
    sur l'adresse d'entrée (``browser``), et sert jusqu'à Ctrl+C. ``announce`` reçoit
    l'adresse d'entrée, jeton compris.

    Lève ``OSError`` si le port est pris."""
    sock = _bind(port)
    port = sock.getsockname()[1]
    settings = Settings(
        token=security.new_token(),
        port=port,
        state_dir=state_dir or platformdirs.user_state_path("forceupdate", appauthor=False),
    )
    url = f"http://127.0.0.1:{port}/?{security.TOKEN_PARAMETER}={settings.token}"
    config = uvicorn.Config(
        create_app(settings),
        log_level="warning",
        access_log=False,  # la première adresse porte le jeton
        timeout_graceful_shutdown=3,
    )
    server = uvicorn.Server(config)
    announce(url)
    if browser:
        threading.Thread(target=_open_browser, args=(server, url), daemon=True).start()
    try:
        with _break_as_interrupt():
            server.run(sockets=[sock])
    except KeyboardInterrupt:
        # Ctrl+C : uvicorn s'est déjà arrêté proprement, puis renvoie le signal reçu.
        pass
    finally:
        sock.close()


@contextlib.contextmanager
def _break_as_interrupt() -> Iterator[None]:
    """Sous Windows, Ctrl+Break comme Ctrl+C. uvicorn arrête le serveur, remet le gestionnaire
    d'avant, puis renvoie le signal : celui du runtime C pour ``SIGBREAK`` sort aussitôt, en
    code 3, sans « Interface arrêtée. » (vérifié le 2026-11-02 avec uvicorn 0.54). Avec celui de
    Ctrl+C, le signal renvoyé devient un ``KeyboardInterrupt``."""
    sigbreak = getattr(signal, "SIGBREAK", None)
    if sigbreak is None or threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = signal.signal(sigbreak, signal.default_int_handler)
    try:
        yield
    finally:
        signal.signal(sigbreak, previous)


def _bind(port: int) -> socket.socket:
    """Le socket d'écoute, sur ``127.0.0.1`` seulement. Sous Windows, il interdit à un autre
    programme d'écouter sur le même port (``SO_EXCLUSIVEADDRUSE``)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            sock.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        sock.bind(("127.0.0.1", port))
    except BaseException:
        sock.close()
        raise
    return sock


def _open_browser(server: uvicorn.Server, url: str) -> None:
    """Ouvre ``url`` dès que le serveur répond (au plus 10 s d'attente)."""
    deadline = time.monotonic() + 10
    while not server.started and not server.should_exit and time.monotonic() < deadline:
        time.sleep(0.05)
    if server.started:
        webbrowser.open(url)
