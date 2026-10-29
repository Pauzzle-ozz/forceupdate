"""L'adresse de retour d'OAuth : la forge y renvoie le navigateur après l'autorisation.

Elle n'est pas sous ``/api``, et le garde la traite à part (``security.Guard``, ``returns``) :
c'est une navigation venue d'un autre site (github.com, gitlab.com), le cookie de session
(``SameSite=Strict``) n'y est pas envoyé et ``Sec-Fetch-Site`` y vaut ``cross-site``. Ce qui la
protège, c'est le ``state`` : tiré au hasard par le serveur pour une connexion lancée depuis
l'interface (jeton de session compris), gardé en mémoire, valable 10 minutes et une seule fois.
Sans lui, la page ne fait rien.

Elle rend une petite page qui renvoie aussitôt vers ``/comptes?connexion=<id>`` (``<meta
http-equiv="refresh">`` : pas de script en ligne sous la CSP). Une redirection HTTP ne suffirait
pas : la chaîne de redirections partirait toujours de github.com, et la page suivante serait
encore « d'un autre site » (cookie absent, refus du garde). Lancée par cette page, la navigation
vient du serveur lui-même.
"""

import html

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from forceupdate.forges import github, gitlab
from forceupdate.forges.base import ForgeKind
from forceupdate.web.connections import Connections

router = APIRouter(include_in_schema=False)

RETURN_PATHS = frozenset({github.CALLBACK_PATH, gitlab.CALLBACK_PATH})
"""Les adresses de retour des forges, que le garde laisse passer sans jeton de session."""


@router.get(github.CALLBACK_PATH)
async def github_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    error_description: str = "",
) -> HTMLResponse:
    return await _callback(request, ForgeKind.GITHUB, code, state, error, error_description)


@router.get(gitlab.CALLBACK_PATH)
async def gitlab_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    error_description: str = "",
) -> HTMLResponse:
    return await _callback(request, ForgeKind.GITLAB, code, state, error, error_description)


async def _callback(
    request: Request, forge: ForgeKind, code: str, state: str, error: str, description: str
) -> HTMLResponse:
    connections: Connections = request.app.state.connections
    connection = connections.by_state(forge, state)
    if connection is None:
        return _page("Lien de connexion inconnu ou déjà utilisé.", "/comptes", status_code=400)
    await connections.finish_oauth(connection, code=code, error=error, description=description)
    return _page("Retour à forceupdate…", f"/comptes?connexion={connection.id}")


def _page(message: str, target: str, *, status_code: int = 200) -> HTMLResponse:
    """La page qui renvoie vers ``target``, avec un lien si le renvoi ne se fait pas."""
    target = html.escape(target, quote=True)
    body = (
        "<!doctype html>\n"
        '<html lang="fr">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="color-scheme" content="light dark">\n'
        f'<meta http-equiv="refresh" content="0; url={target}">\n'
        "<title>Connexion · forceupdate</title>\n</head>\n<body>\n"
        f'<p>{html.escape(message)} <a href="{target}">Continuer</a></p>\n'
        "</body>\n</html>\n"
    )
    return HTMLResponse(body, status_code=status_code)
