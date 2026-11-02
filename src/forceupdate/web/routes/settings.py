"""Les réglages de la personne (écran 9) : les lire, les enregistrer, vider le cache.

Pas de logique ici : ``preferences`` lit, vérifie et écrit les réglages (le même fichier que la
ligne de commande), ``net.cache.Cache`` dit ce qu'il contient et se vide.
"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from forceupdate.web import preferences
from forceupdate.web.preferences import UserPreferences
from forceupdate.web.routes import CurrentJobs, errors, respond
from forceupdate.web.schemas import (
    CacheState,
    SettingsDocument,
    SettingsRejected,
    SettingsRequest,
    cache_state,
)

router = APIRouter(prefix="/api", tags=["réglages"])


def current_preferences(request: Request) -> UserPreferences:
    store: UserPreferences = request.app.state.preferences
    return store


CurrentPreferences = Annotated[UserPreferences, Depends(current_preferences)]


@router.get("/settings", response_model=SettingsDocument, responses=errors(401, 403))
async def get_settings(store: CurrentPreferences, jobs: CurrentJobs) -> JSONResponse:
    """Les réglages de la personne, leurs valeurs par défaut, et l'état du cache."""
    stats = await asyncio.to_thread(jobs.worker.cache.stats)
    return respond(preferences.document(store, cache_state(stats)))


@router.put(
    "/settings",
    response_model=SettingsDocument,
    responses={
        400: {"model": SettingsRejected, "description": "Des valeurs refusées, champ par champ"},
        **errors(401, 403, 409),
    },
)
async def save_settings(
    body: SettingsRequest, store: CurrentPreferences, jobs: CurrentJobs
) -> JSONResponse:
    """Enregistre les réglages, tous à la fois : ils valent pour les analyses, les plans et les
    PR qui suivent, et pour la ligne de commande. Une valeur refusée : rien n'est enregistré, et
    la réponse dit lesquelles (``fields``)."""
    value, refused = preferences.from_request(body)
    if refused:
        count = len(refused)
        detail = "Une valeur est refusée" if count == 1 else f"{count} valeurs sont refusées"
        rejected = SettingsRejected(
            detail=f"{detail} : rien n'est enregistré.", fields=tuple(refused)
        )
        return respond(rejected, 400)
    try:
        await asyncio.to_thread(store.save, value)
    except OSError as err:
        raise HTTPException(
            409, f"Réglages non enregistrés dans {store.path} : {err.strerror or err}."
        ) from err
    stats = await asyncio.to_thread(jobs.worker.cache.stats)
    return respond(preferences.document(store, cache_state(stats)))


@router.delete("/cache", response_model=CacheState, responses=errors(401, 403))
async def clear_cache(jobs: CurrentJobs) -> JSONResponse:
    """Vide le cache disque (versions des paquets, failles, fins de vie) : la prochaine analyse
    redemande tout au réseau."""
    cache = jobs.worker.cache
    await asyncio.to_thread(cache.clear)
    return respond(cache_state(await asyncio.to_thread(cache.stats)))
