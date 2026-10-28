"""Un fichier envoyé par l'interface (glisser-déposer) : le navigateur ne donne pas son chemin,
seulement son contenu.

Il est rangé dans un dossier temporaire, puis analysé comme un fichier de l'ordinateur : même
progression, même rapport, même plan. Mais rien ne s'écrit sur le disque de la personne et
aucun outil n'est lancé : sa version réécrite se télécharge depuis le plan
(``GET /api/updates/{id}/files/{nom}``).
"""

import asyncio
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from forceupdate.detect.manifests import match_dependency_file, max_read_size
from forceupdate.models import ScanOptions
from forceupdate.sources.local import LocalSource
from forceupdate.web.routes import CurrentJobs, errors, respond
from forceupdate.web.schemas import ScanSummary, SourceKind

router = APIRouter(prefix="/api/files", tags=["fichiers"])

_BODY = {
    "requestBody": {
        "required": True,
        "description": "Le contenu du fichier, tel quel.",
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
    }
}


@router.post(
    "",
    status_code=202,
    response_model=ScanSummary,
    responses=errors(400, 401, 403, 413),
    openapi_extra=_BODY,
)
async def upload_file(
    request: Request,
    jobs: CurrentJobs,
    name: Annotated[str, Query(description="Le nom du fichier (package.json…).")],
) -> JSONResponse:
    """Analyse un fichier envoyé : un manifeste ou un lockfile, son contenu dans le corps de la
    requête. Rend l'analyse lancée, comme ``POST /api/scans``."""
    _check_name(name)
    content = await _read_body(request, max_read_size(name))
    directory = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="forceupdate-"))
    path = directory / name
    await asyncio.to_thread(path.write_bytes, content)
    source = LocalSource(path)
    scan = jobs.start_scan(
        source, ScanOptions(), kind=SourceKind.UPLOAD, label=name, upload_dir=directory
    )
    return respond(scan.summary(), 202, location=f"/api/scans/{scan.id}")


def _check_name(name: str) -> None:
    """Un nom de fichier seul (ni dossier, ni lecteur), d'un fichier de dépendances connu."""
    if not name:
        raise HTTPException(400, "Nom de fichier manquant.")
    bare = name == PurePosixPath(name).name == PureWindowsPath(name).name
    if not bare or name in {".", ".."} or "\0" in name or len(name) > 255:
        raise HTTPException(400, f"Nom de fichier invalide : « {name} ».")
    if match_dependency_file(name) is None:
        raise HTTPException(
            400, f"« {name} » n'est pas un manifeste ni un lockfile que forceupdate sait lire."
        )


async def _read_body(request: Request, limit: int) -> bytes:
    too_big = HTTPException(413, f"Fichier trop gros : plus de {limit // 2**20} Mo.")
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise too_big
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise too_big
        chunks.append(chunk)
    return b"".join(chunks)
