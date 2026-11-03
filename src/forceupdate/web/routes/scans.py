"""Les analyses : lancer, suivre, lire le rapport, le télécharger, annuler."""

import asyncio
import enum
import re
from pathlib import Path, PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse, Response, StreamingResponse

from forceupdate.models import Report
from forceupdate.report import json as json_report
from forceupdate.report import markdown, spreadsheet
from forceupdate.sources.base import SourceError
from forceupdate.sources.local import LocalSource
from forceupdate.web import sse
from forceupdate.web.routes import CurrentJobs, attachment, errors, find_scan, respond, sentence
from forceupdate.web.routes.settings import CurrentPreferences
from forceupdate.web.schemas import ScanDetail, ScanRequest, ScanSummary, SourceKind

router = APIRouter(prefix="/api/scans", tags=["analyses"])


class DownloadFormat(enum.StrEnum):
    """Ce qui se télécharge d'un rapport (session 36), comme ``scan --format``."""

    MD = "md"
    """Le rapport en Markdown."""
    JSON = "json"
    """Le rapport en JSON (``docs/JSON_FORMAT.md``)."""
    CSV = "csv"
    """Les dépendances à mettre à jour, pour un tableur (``report.spreadsheet``)."""


_MEDIA = {
    DownloadFormat.MD: "text/markdown; charset=utf-8",
    DownloadFormat.JSON: "application/json",
    DownloadFormat.CSV: "text/csv; charset=utf-8",
}


@router.post("", status_code=202, response_model=ScanSummary, responses=errors(400, 401, 403, 404))
async def start_scan(
    body: ScanRequest, jobs: CurrentJobs, store: CurrentPreferences
) -> JSONResponse:
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
    options = body.options(store.current)
    scan = jobs.start_scan(source, options, kind=kind, label=source.origin)
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
    "/{scan_id}/download",
    response_class=Response,
    responses={
        200: {
            "description": "Le rapport, ou les dépendances à mettre à jour, à télécharger.",
            "content": {media: {"schema": {"type": "string"}} for media in _MEDIA.values()},
        },
        **errors(401, 403, 404, 409),
    },
)
async def download_report(
    scan_id: str, jobs: CurrentJobs, format: DownloadFormat = DownloadFormat.MD
) -> Response:
    """Le rapport d'une analyse finie, en pièce jointe : en Markdown (``md``), en JSON
    (``json``), ou les dépendances à mettre à jour en CSV (``csv``, pour un tableur)."""
    scan = find_scan(jobs, scan_id)
    report = scan.report
    if report is None:
        raise HTTPException(409, "Pas de rapport : l'analyse n'est pas finie, ou a échoué.")
    if format is DownloadFormat.MD:
        text = markdown.render(report)
    elif format is DownloadFormat.JSON:
        text = json_report.render(report)
    else:
        text = spreadsheet.BOM + spreadsheet.render(report)
    return Response(
        text.encode("utf-8"),
        media_type=_MEDIA[format],
        headers={"Content-Disposition": attachment(download_name(scan.label, report, format))},
    )


def download_name(label: str, report: Report, format: DownloadFormat) -> str:
    """Le nom du fichier téléchargé : ``forceupdate-boutique-2026-11-03.md``, et
    ``forceupdate-boutique-a-mettre-a-jour-2026-11-03.csv`` ; le nom de la source réduit aux
    lettres, chiffres, points et tirets."""
    name = PurePosixPath(label.replace("\\", "/").rstrip("/")).name or "rapport"
    name = re.sub(r"[^\w.-]+", "-", name, flags=re.ASCII).strip("-.") or "rapport"
    what = "-a-mettre-a-jour" if format is DownloadFormat.CSV else ""
    day = f"-{report.scanned_at:%Y-%m-%d}" if report.scanned_at is not None else ""
    return f"forceupdate-{name}{what}{day}.{format}"


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
