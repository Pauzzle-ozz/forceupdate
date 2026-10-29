"""Les dépôts des comptes connectés : la liste (drapeaux, organisations restreintes, requêtes
restantes, synthèse), les analyses groupées, et l'analyse d'un dépôt donné par son nom.

Pas de logique ici : ``web.repositories`` tient la liste et les lots, le moteur classe et
additionne (``report.synthesis``). Les tokens ne vont jamais au navigateur.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from forceupdate.web.repositories import Batch, Repositories, RepositoryError
from forceupdate.web.routes import errors, respond
from forceupdate.web.schemas import (
    BatchRequest,
    RepositoryBatch,
    RepositoryList,
    RepositoryRequest,
    ScanSummary,
)

router = APIRouter(prefix="/api/repositories", tags=["dépôts"])


def current_repositories(request: Request) -> Repositories:
    repositories: Repositories = request.app.state.repositories
    return repositories


CurrentRepositories = Annotated[Repositories, Depends(current_repositories)]


@router.get("", response_model=RepositoryList, responses=errors(401, 403))
async def list_repositories(
    repositories: CurrentRepositories, reload: bool = False
) -> JSONResponse:
    """Les dépôts des comptes connectés, l'état de leur dernière analyse, et la synthèse. La
    liste est demandée aux forges la première fois, puis gardée le temps de la session ;
    ``reload`` la redemande. Un refus de la forge est dit dans ``accounts[].error``."""
    return respond(await repositories.document(reload=reload))


@router.post(
    "/batches",
    status_code=202,
    response_model=RepositoryBatch,
    responses=errors(400, 401, 403, 404, 409),
)
async def start_batch(body: BatchRequest, repositories: CurrentRepositories) -> JSONResponse:
    """Analyse ensemble des dépôts du compte connecté à ``forge``, sans les cloner : quelques
    dépôts à la fois, une analyse par dépôt (``scans``), qui se suit comme les autres. Les
    dépôts vides sont sautés."""
    try:
        batch = await repositories.start_batch(body.forge, body.repositories, body.options())
    except RepositoryError as err:
        raise HTTPException(err.status, str(err)) from err
    return respond(batch.document(), 202, location=f"/api/repositories/batches/{batch.id}")


@router.get("/batches/{batch_id}", response_model=RepositoryBatch, responses=errors(401, 403, 404))
async def get_batch(batch_id: str, repositories: CurrentRepositories) -> JSONResponse:
    """Où en est une analyse groupée."""
    return respond(_find(repositories, batch_id).document())


@router.delete(
    "/batches/{batch_id}", response_model=RepositoryBatch, responses=errors(401, 403, 404)
)
async def cancel_batch(batch_id: str, repositories: CurrentRepositories) -> JSONResponse:
    """Annule les analyses du lot qui ne sont pas finies ; celles qui le sont restent."""
    batch = _find(repositories, batch_id)
    repositories.cancel_batch(batch)
    return respond(batch.document())


@router.post(
    "/scans",
    status_code=202,
    response_model=ScanSummary,
    responses=errors(400, 401, 403, 404, 409, 502),
)
async def scan_repository(
    body: RepositoryRequest, repositories: CurrentRepositories
) -> JSONResponse:
    """Analyse un dépôt donné par son nom (``owner/nom``) ou son adresse, même d'un autre compte
    s'il est public : avec le token du compte connecté à sa forge, sans token sinon (GitHub :
    60 requêtes par heure). Se suit comme une autre analyse."""
    try:
        scan = await repositories.start_scan(body.repository, body.options())
    except RepositoryError as err:
        raise HTTPException(err.status, str(err)) from err
    return respond(scan.summary(), 202, location=f"/api/scans/{scan.id}")


def _find(repositories: Repositories, batch_id: str) -> Batch:
    batch = repositories.batches.get(batch_id)
    if batch is None:
        raise HTTPException(404, f"Analyse groupée inconnue : {batch_id}.")
    return batch
