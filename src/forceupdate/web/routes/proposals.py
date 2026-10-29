"""Les PR des dépôts (écran 8) : préparer le récapitulatif (rien n'est poussé), l'envoyer une
fois validé, suivre l'envoi.

Pas de logique ici : ``web.proposals`` tient les récapitulatifs et leurs envois,
``update.forge`` fait la mise à jour d'un dépôt et sa PR. Les tokens ne vont jamais au
navigateur.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from forceupdate.web.proposals import Proposal, Proposals
from forceupdate.web.repositories import RepositoryError
from forceupdate.web.routes import errors, respond
from forceupdate.web.schemas import Proposal as ProposalDocument
from forceupdate.web.schemas import ProposalRequest, SendRequest

router = APIRouter(prefix="/api/proposals", tags=["PR"])


def current_proposals(request: Request) -> Proposals:
    proposals: Proposals = request.app.state.proposals
    return proposals


CurrentProposals = Annotated[Proposals, Depends(current_proposals)]


@router.post(
    "",
    status_code=201,
    response_model=ProposalDocument,
    responses=errors(400, 401, 403, 404, 409),
)
async def create_proposal(body: ProposalRequest, proposals: CurrentProposals) -> JSONResponse:
    """Le récapitulatif des PR (MR sur GitLab) de quelques dépôts des comptes connectés, de
    plusieurs forges au besoin : pour chacun, la sélection (donnée, ou celle par défaut de sa
    dernière analyse) préparée sur les fichiers de l'analyse (diffs, lockfiles, commandes), la
    PR déjà ouverte, ou pourquoi il est sauté. Rien n'est cloné ni poussé."""
    try:
        proposal = await proposals.create(body.repositories)
    except RepositoryError as err:
        raise HTTPException(err.status, str(err)) from err
    return respond(proposal.document(), 201, location=f"/api/proposals/{proposal.id}")


@router.get("/{proposal_id}", response_model=ProposalDocument, responses=errors(401, 403, 404))
async def get_proposal(proposal_id: str, proposals: CurrentProposals) -> JSONResponse:
    """Le récapitulatif ; pendant et après l'envoi, où en est chaque dépôt, et sa PR."""
    return respond(_find(proposals, proposal_id).document())


@router.post(
    "/{proposal_id}/send",
    status_code=202,
    response_model=ProposalDocument,
    responses=errors(400, 401, 403, 404, 409),
)
async def send_proposal(
    proposal_id: str, body: SendRequest, proposals: CurrentProposals
) -> JSONResponse:
    """Envoie les dépôts cochés du récapitulatif, en tâche de fond, un à la fois : clone,
    mise à jour, commit, push de ``forceupdate/dependencies`` (jamais la branche par défaut),
    PR ouverte ou mise à jour. Se suit par ``GET /api/proposals/{id}``. Ne s'annule pas."""
    proposal = _find(proposals, proposal_id)
    try:
        await proposals.send(proposal, body.repositories)
    except RepositoryError as err:
        raise HTTPException(err.status, str(err)) from err
    return respond(proposal.document(), 202, location=f"/api/proposals/{proposal.id}")


def _find(proposals: Proposals, proposal_id: str) -> Proposal:
    proposal = proposals.proposals.get(proposal_id)
    if proposal is None:
        raise HTTPException(404, f"Récapitulatif inconnu : {proposal_id}.")
    return proposal
