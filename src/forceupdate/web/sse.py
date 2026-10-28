"""La progression d'une tâche envoyée au navigateur en Server-Sent Events (``EventSource``).

Chaque événement porte un numéro (``id``) : les événements déjà passés sont renvoyés d'abord,
depuis le début, ou depuis celui qui suit ``Last-Event-ID`` quand le navigateur se rebranche.

- ``event: progress`` : un ``models.Event`` en JSON ;
- ``event: end`` : la tâche est finie, ``{"status": …, "error": …}`` ; le flux se ferme. Le
  navigateur doit alors fermer son ``EventSource``, qui sinon se rebrancherait ;
- ``: ping`` (un commentaire), après un moment sans rien : un navigateur parti est ainsi
  remarqué.
"""

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

from starlette.responses import StreamingResponse

from forceupdate.models import to_dict
from forceupdate.web.jobs import Progress

RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "Flux d'événements (text/event-stream) : « progress », puis « end ».",
        "content": {"text/event-stream": {"schema": {"type": "string"}}},
    }
}
"""Pour le schéma OpenAPI des routes ``…/events``."""


def stream(
    progress: Progress, last_event_id: str | None, end: Callable[[], dict[str, Any]]
) -> StreamingResponse:
    """La réponse SSE qui suit ``progress`` ; ``end()`` donne le contenu de l'événement final."""
    start = 0
    if last_event_id is not None and last_event_id.strip().isdigit():
        start = int(last_event_id) + 1
    return StreamingResponse(
        _events(progress, start, end),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


async def _events(
    progress: Progress, start: int, end: Callable[[], dict[str, Any]]
) -> AsyncIterator[str]:
    async for item in progress.follow(start):
        if item is None:
            yield ": ping\n\n"
            continue
        index, event = item
        yield _message(index, "progress", to_dict(event))
    yield _message(len(progress.events), "end", end())


def _message(index: int, kind: str, data: dict[str, Any]) -> str:
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"id: {index}\nevent: {kind}\ndata: {text}\n\n"
