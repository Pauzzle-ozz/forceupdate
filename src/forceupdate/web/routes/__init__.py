"""Les routes de l'API, une par module : ``fs`` (dossiers), ``scans`` (analyses), ``updates``
(plans et mises à jour), ``files`` (fichier envoyé).

Pas de logique métier ici : les routes appellent ``engine`` (par ``web.jobs``),
``update.local``, ``detect``, comme le fait ``cli.py``. Les réponses sont écrites par
``models.to_dict`` (``respond``) ; ``response_model`` ne sert qu'au schéma OpenAPI. Une erreur
rend ``{"detail": "…"}``, en français (``schemas.Error``).
"""

from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from forceupdate.models import to_dict
from forceupdate.web.jobs import Jobs, Plan, Scan
from forceupdate.web.schemas import Error

_ERRORS = {
    400: "Requête invalide",
    401: "Jeton de session manquant ou invalide",
    403: "Requête venue d'un autre site",
    404: "Introuvable",
    409: "Impossible dans l'état actuel",
    413: "Fichier trop gros",
}


def errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    """Les réponses d'erreur d'une route, pour le schéma OpenAPI."""
    return {code: {"model": Error, "description": _ERRORS[code]} for code in codes}


def current_jobs(request: Request) -> Jobs:
    jobs: Jobs = request.app.state.jobs
    return jobs


CurrentJobs = Annotated[Jobs, Depends(current_jobs)]


def respond(document: Any, status_code: int = 200, *, location: str | None = None) -> JSONResponse:
    """La réponse JSON : ``document`` (un modèle, une liste de modèles, ou déjà des types
    simples)."""
    headers = {"Location": location} if location is not None else None
    return JSONResponse(_plain(document), status_code=status_code, headers=headers)


def _plain(document: Any) -> Any:
    if isinstance(document, list):
        return [_plain(item) for item in document]
    return document if isinstance(document, dict) else to_dict(document)


def sentence(message: str) -> str:
    """Un message du moteur (« le chemin … n'existe pas ») en phrase : majuscule, point."""
    message = message.rstrip(" .")
    return f"{message[:1].upper()}{message[1:]}."


def find_scan(jobs: Jobs, scan_id: str) -> Scan:
    scan = jobs.scans.get(scan_id)
    if scan is None:
        raise HTTPException(404, f"Analyse inconnue : {scan_id}.")
    return scan


def find_plan(jobs: Jobs, plan_id: str) -> Plan:
    plan = jobs.plans.get(plan_id)
    if plan is None:
        raise HTTPException(404, f"Plan inconnu : {plan_id}.")
    return plan
