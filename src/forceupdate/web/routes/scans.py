"""Les analyses : lancer, suivre, lire le rapport, annuler."""

import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from forceupdate.sources.base import SourceError
from forceupdate.sources.local import LocalSource
from forceupdate.web import sse
from forceupdate.web.routes import CurrentJobs, errors, find_scan, respond, sentence
from forceupdate.web.schemas import ScanDetail, ScanRequest, ScanSummary, SourceKind

router = APIRouter(prefix="/api/scans", tags=["analyses"])


@router.post("", status_code=202, response_model=ScanSummary, responses=errors(400, 401, 403, 404))
async def start_scan(body: ScanRequest, jobs: CurrentJobs) -> JSONResponse:
    """Lance l'analyse d'un dossier ou d'un fichier de l'ordinateur, en tâche de fond. La
    progression se suit sur ``…/events``, le rapport se lit sur ``GET /api/scans/{id}``."""
    path = Path(body.path)
    if not path.is_absolute():
        raise HTTPException(400, f"« {body.path} » : donner un chemin absolu.")
    try:
        source = await asyncio.to_thread(LocalSource, path)
    except SourceError as err:
        raise HTTPException(404, sentence(str(err))) from err
    kind = SourceKind.FOLDER if source.file is None else SourceKind.FILE
    scan = jobs.start_scan(source, body.options(), kind=kind, label=source.origin)
    await asyncio.to_thread(jobs.recent.add, source.origin)
    return respond(scan.summary(), 202, location=f"/api/scans/{scan.id}")


@router.get("", response_model=list[ScanSummary], responses=errors(401, 403))
async def list_scans(jobs: CurrentJobs) -> JSONResponse:
    """Les analyses de la session, de la plus récente à la plus ancienne."""
    scans = sorted(jobs.scans.values(), key=lambda scan: scan.started_at, reverse=True)
    return respond([scan.summary() for scan in scans])


@router.get("/{scan_id}", response_model=ScanDetail, responses=errors(401, 403, 404))
async def get_scan(scan_id: str, jobs: CurrentJobs) -> JSONResponse:
    """L'analyse, et son rapport une fois finie."""
    return respond(find_scan(jobs, scan_id).document())


@router.get(
    "/{scan_id}/events",
    response_class=StreamingResponse,
    responses={**sse.RESPONSES, **errors(401, 403, 404)},
)
async def scan_events(
    scan_id: str,
    jobs: CurrentJobs,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    """La progression de l'analyse, en Server-Sent Events : des ``Event`` (``progress``), puis
    ``end`` avec le statut final."""
    scan = find_scan(jobs, scan_id)
    return sse.stream(
        scan.progress, last_event_id, lambda: {"status": scan.status, "error": scan.error}
    )


@router.delete("/{scan_id}", response_model=ScanSummary, responses=errors(401, 403, 404, 409))
async def cancel_scan(scan_id: str, jobs: CurrentJobs) -> JSONResponse:
    """Annule l'analyse si elle tourne encore."""
    scan = find_scan(jobs, scan_id)
    if not jobs.cancel(scan):
        raise HTTPException(409, "L'analyse est déjà finie.")
    return respond(scan.summary())
