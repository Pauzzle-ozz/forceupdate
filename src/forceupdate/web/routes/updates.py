"""Les mises à jour : préparer un plan (diffs, lockfiles), l'appliquer, suivre l'application,
télécharger un fichier réécrit.

Le plan est gardé sur le serveur, avec son identifiant : c'est ce plan-là, et le même
``Prepared``, qu'on applique. ``writers.write`` refuse d'écrire un fichier qui a changé depuis
son diff ; le navigateur ne renvoie jamais les réécritures.
"""

import asyncio
import urllib.parse
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse, Response, StreamingResponse

from forceupdate.update import local
from forceupdate.web import sse
from forceupdate.web.jobs import Plan
from forceupdate.web.routes import CurrentJobs, errors, find_plan, find_scan, respond, sentence
from forceupdate.web.schemas import (
    ApplyRequest,
    PlanRequest,
    SourceKind,
    TaskStatus,
    UpdatePlan,
)

router = APIRouter(prefix="/api/updates", tags=["mises à jour"])


@router.post(
    "/plan", status_code=201, response_model=UpdatePlan, responses=errors(400, 401, 403, 404, 409)
)
async def plan_update(body: PlanRequest, jobs: CurrentJobs) -> JSONResponse:
    """Prépare une sélection sur le rapport d'une analyse finie, sans rien écrire : les diffs,
    ce qui ne sera pas appliqué, les lockfiles à régénérer, et le garde-fou git."""
    scan = find_scan(jobs, body.scan)
    if scan.report is None:
        state = "n'est pas finie" if scan.status is TaskStatus.RUNNING else "n'a pas abouti"
        raise HTTPException(409, f"L'analyse {state} : pas de rapport sur lequel préparer.")
    upload = scan.kind is SourceKind.UPLOAD
    try:
        prepared = await asyncio.to_thread(
            local.prepare, scan.source, scan.report, body.selection, regenerate=not upload
        )
    except ValueError as err:
        raise HTTPException(400, sentence(str(err))) from err
    uncommitted = None
    if not upload:
        uncommitted = await asyncio.to_thread(local.uncommitted, scan.source, prepared)
    plan = jobs.add_plan(scan, body.selection, prepared, uncommitted)
    return respond(plan.document(), 201, location=f"/api/updates/{plan.id}")


@router.post(
    "/apply", status_code=202, response_model=UpdatePlan, responses=errors(401, 403, 404, 409)
)
async def apply_update(body: ApplyRequest, jobs: CurrentJobs) -> JSONResponse:
    """Applique un plan, en tâche de fond : réécrit les fichiers, puis régénère les lockfiles.
    Refusé si des fichiers à toucher ont des changements que git n'a pas en commit, sauf
    ``force``. La progression se suit sur ``/api/updates/{id}/events``."""
    plan = find_plan(jobs, body.plan)
    _check_applicable(plan)
    if not body.force:
        dirty = await asyncio.to_thread(local.uncommitted, plan.scan.source, plan.prepared)
        plan.uncommitted = dirty
        if dirty:
            raise HTTPException(
                409,
                f"{', '.join(dirty)} : des changements que git n'a pas en commit. Les commiter "
                "(ou les mettre de côté) d'abord, ou appliquer avec « force ».",
            )
        _check_applicable(plan)  # une autre requête a pu l'appliquer pendant l'attente
    jobs.start_apply(plan)
    return respond(plan.document(), 202, location=f"/api/updates/{plan.id}")


def _check_applicable(plan: Plan) -> None:
    if plan.scan.kind is SourceKind.UPLOAD:
        raise HTTPException(
            409,
            "Fichier envoyé : rien ne s'écrit sur le disque, sa version réécrite se télécharge "
            "(GET /api/updates/{id}/files/{chemin}).",
        )
    if plan.status is not TaskStatus.PLANNED:
        raise HTTPException(409, "Ce plan est déjà appliqué, ou en cours d'application.")
    if plan.prepared.empty:
        raise HTTPException(409, "Rien à écrire ni à lancer.")


@router.get("/{plan_id}", response_model=UpdatePlan, responses=errors(401, 403, 404))
async def get_plan(plan_id: str, jobs: CurrentJobs) -> JSONResponse:
    """Le plan ; une fois appliqué, ce qu'il est advenu de chaque lockfile."""
    return respond(find_plan(jobs, plan_id).document())


@router.get(
    "/{plan_id}/events",
    response_class=StreamingResponse,
    responses={**sse.RESPONSES, **errors(401, 403, 404, 409)},
)
async def plan_events(
    plan_id: str,
    jobs: CurrentJobs,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    """La progression de l'application, en Server-Sent Events : ``written``, un
    ``regenerating`` par lockfile, ``finished``, puis ``end`` avec le statut final."""
    plan = find_plan(jobs, plan_id)
    if plan.status is TaskStatus.PLANNED:
        raise HTTPException(409, "Ce plan n'est pas appliqué : pas de progression à suivre.")
    return sse.stream(
        plan.progress, last_event_id, lambda: {"status": plan.status, "error": plan.error}
    )


@router.get(
    "/{plan_id}/files/{path:path}",
    response_class=Response,
    responses={
        200: {
            "description": "Le fichier réécrit, à télécharger.",
            "content": {"application/octet-stream": {"schema": {"type": "string"}}},
        },
        **errors(401, 403, 404),
    },
)
async def download_file(plan_id: str, path: str, jobs: CurrentJobs) -> Response:
    """Un fichier tel que le plan le réécrit : pour un fichier envoyé par glisser-déposer, sa
    version mise à jour."""
    plan = find_plan(jobs, plan_id)
    change = next((c for c in plan.prepared.changes.files if c.path == path), None)
    if change is None:
        raise HTTPException(404, f"Ce plan ne réécrit pas « {path} ».")
    name = PurePosixPath(path).name
    return Response(
        change.after.encode("utf-8"),
        media_type="application/octet-stream",
        headers={"Content-Disposition": _attachment(name)},
    )


def _attachment(name: str) -> str:
    quoted = urllib.parse.quote(name)
    if quoted == name:
        return f'attachment; filename="{name}"'
    return f"attachment; filename*=utf-8''{quoted}"
