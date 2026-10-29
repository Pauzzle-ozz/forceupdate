"""Les comptes des forges : lister, connecter (OAuth, device flow, token collé, ``gh``),
vérifier les droits, déconnecter.

Les tokens ne vont jamais au navigateur : il reçoit le compte (identifiant, droits), jamais son
token. Un refus de la forge n'est jamais un ``401`` de l'API (celui-là veut dire « session
terminée ») : c'est un ``400`` avec la raison, ou ``problem`` sur le compte ; une forge qui ne
répond pas, un ``502``.
"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from forceupdate.forges import FORGES, github, info
from forceupdate.forges import accounts as accounts_module
from forceupdate.forges.accounts import Account, AccountsError, ConnectMethod
from forceupdate.forges.base import ForgeError, ForgeKind, RateLimited
from forceupdate.net import NetworkError
from forceupdate.web.connections import Connection, Connections, failure
from forceupdate.web.routes import errors, respond
from forceupdate.web.schemas import (
    AccountConnection,
    AccountList,
    Disconnection,
    ForgeStatus,
    TokenRequest,
)

router = APIRouter(prefix="/api/accounts", tags=["comptes"])

MAX_TOKEN = 1024
"""Longueur maximale d'un token collé."""


def current_connections(request: Request) -> Connections:
    connections: Connections = request.app.state.connections
    return connections


CurrentConnections = Annotated[Connections, Depends(current_connections)]


@router.get("", response_model=AccountList, responses=errors(401, 403))
async def list_accounts(connections: CurrentConnections) -> JSONResponse:
    """Les forges, comment s'y connecter, et les comptes connectés (sans leur token). Rien
    n'est demandé aux forges : ``POST …/verify`` relit les droits."""
    store = connections.accounts
    problem = await asyncio.to_thread(store.unavailable)
    connected: list[Account] = []
    if problem is None:
        try:
            connected = await asyncio.to_thread(store.connected)
        except AccountsError as err:
            problem = str(err)
    gh = await asyncio.to_thread(github.gh_installed)
    forges = []
    for forge in FORGES:
        methods: list[ConnectMethod] = []
        if forge.available and forge.kind is ForgeKind.GITHUB:
            if connections.app.web_flow:
                methods.append(ConnectMethod.OAUTH)
            methods += [ConnectMethod.DEVICE, ConnectMethod.TOKEN]
            if gh:
                methods.append(ConnectMethod.GH)
        pending = connections.pending(forge.kind)
        forges.append(
            ForgeStatus(
                forge=forge.kind,
                name=forge.name,
                host=forge.host,
                available=forge.available,
                methods=tuple(methods),
                scopes=github.SCOPES if forge.kind is ForgeKind.GITHUB else (),
                token_url=github.TOKEN_SETTINGS_URL if forge.kind is ForgeKind.GITHUB else None,
                account=next((a for a in connected if a.forge is forge.kind), None),
                connection=pending.document() if pending is not None else None,
            )
        )
    return respond(AccountList(keyring=problem, forges=tuple(forges)))


@router.post(
    "/{forge}/oauth",
    status_code=201,
    response_model=AccountConnection,
    responses=errors(401, 403, 409),
)
async def start_oauth(
    forge: ForgeKind, request: Request, connections: CurrentConnections
) -> JSONResponse:
    """Commence une connexion par la page d'autorisation de la forge : le navigateur doit aller
    à ``authorize_url``. La forge le renverra sur le serveur, qui échange le code contre le
    token, puis vers ``/comptes?connexion=<id>``."""
    _check_available(forge)
    await _check_keyring(connections)
    if not connections.app.web_flow:
        raise HTTPException(
            409, "L'application n'a pas de secret : se connecter avec un code (device flow)."
        )
    expected = f"127.0.0.1:{connections.port}"
    if request.headers.get("host") != expected:
        raise HTTPException(
            409,
            f"GitHub ne revient que vers 127.0.0.1 : ouvrir l'interface par http://{expected} "
            "(l'adresse que donne « forceupdate ui »), ou se connecter avec un code.",
        )
    connection = connections.start_oauth(forge)
    return _connection_response(connection)


@router.post(
    "/{forge}/device",
    status_code=201,
    response_model=AccountConnection,
    responses=errors(401, 403, 409, 502),
)
async def start_device(forge: ForgeKind, connections: CurrentConnections) -> JSONResponse:
    """Commence une connexion par device flow : la forge donne un code (``user_code``) à taper
    sur ``verification_uri`` ; le serveur attend, la connexion se suit sur
    ``GET /api/accounts/connections/{id}``."""
    _check_available(forge)
    await _check_keyring(connections)
    try:
        connection = await connections.start_device(forge)
    except (ForgeError, NetworkError) as err:
        raise _refused(err, forge) from err
    return _connection_response(connection)


@router.get(
    "/connections/{connection_id}",
    response_model=AccountConnection,
    responses=errors(401, 403, 404),
)
async def get_connection(connection_id: str, connections: CurrentConnections) -> JSONResponse:
    """Où en est une connexion : ``pending``, puis ``done`` (avec le compte), ``failed``,
    ``expired`` ou ``cancelled`` (avec la raison)."""
    return respond(_find(connections, connection_id).document())


@router.delete(
    "/connections/{connection_id}",
    response_model=AccountConnection,
    responses=errors(401, 403, 404),
)
async def cancel_connection(connection_id: str, connections: CurrentConnections) -> JSONResponse:
    """Abandonne une connexion en attente (le device flow cesse d'attendre)."""
    connection = _find(connections, connection_id)
    connections.cancel(connection)
    return respond(connection.document())


@router.post(
    "/{forge}/token",
    status_code=201,
    response_model=Account,
    responses=errors(400, 401, 403, 409, 502),
)
async def connect_token(
    forge: ForgeKind, body: TokenRequest, connections: CurrentConnections
) -> JSONResponse:
    """Connecte un compte avec un token collé (classic ou fine-grained), une fois que la forge
    l'a accepté."""
    _check_available(forge)
    token = body.token.strip()
    if not token or len(token) > MAX_TOKEN or any(c.isspace() for c in token):
        raise HTTPException(
            400, "Ce n'est pas un token : une seule suite de caractères, sans espace."
        )
    return await _connect(connections, forge, token, ConnectMethod.TOKEN)


@router.post(
    "/{forge}/gh",
    status_code=201,
    response_model=Account,
    responses=errors(400, 401, 403, 409, 502),
)
async def connect_gh(forge: ForgeKind, connections: CurrentConnections) -> JSONResponse:
    """Connecte le compte avec lequel GitHub CLI (``gh``) est connecté : son token est lu par
    ``gh auth token``, puis rangé dans le trousseau de forceupdate."""
    _check_available(forge)
    if forge is not ForgeKind.GITHUB:
        raise HTTPException(400, "gh ne sert qu'à GitHub.")
    try:
        token = await asyncio.to_thread(github.gh_token)
    except ForgeError as err:
        raise HTTPException(400, str(err)) from err
    return await _connect(connections, forge, token, ConnectMethod.GH)


@router.post("/{forge}/verify", response_model=Account, responses=errors(401, 403, 404, 409, 502))
async def verify_account(forge: ForgeKind, connections: CurrentConnections) -> JSONResponse:
    """Redemande à la forge qui est connecté et avec quels droits. Un token refusé (révoqué sur
    la forge) est dit dans ``problem`` : le compte reste affiché, pour qu'on se reconnecte."""
    account = await _account(connections, forge)
    try:
        checked = await accounts_module.verify(connections.accounts, connections.http, account)
    except AccountsError as err:
        raise HTTPException(409, str(err)) from err
    except (ForgeError, NetworkError) as err:
        raise _refused(err, forge) from err
    return respond(checked)


@router.delete("/{forge}", response_model=Disconnection, responses=errors(401, 403, 404, 409))
async def disconnect(forge: ForgeKind, connections: CurrentConnections) -> JSONResponse:
    """Déconnecte le compte : efface son token du trousseau, et le révoque auprès de la forge
    s'il a été donné à forceupdate (OAuth, device flow)."""
    name = info(forge).name
    try:
        account, token = await asyncio.to_thread(
            connections.accounts.remove, forge, info(forge).host
        )
    except AccountsError as err:
        raise HTTPException(409, str(err)) from err
    if account is None or token is None:
        raise HTTPException(404, f"Aucun compte {name} connecté.")
    revoked: bool | None = None
    if account.method.from_app:
        revoked = await github.revoke(connections.http, connections.app, token)
    if revoked:
        message = f"Déconnecté de {name} : token effacé de cet ordinateur et révoqué."
    elif revoked is None:
        message = (
            f"Déconnecté de {name} : token effacé de cet ordinateur. Il reste valable sur "
            f"{name} (il n'appartient pas à forceupdate)."
        )
    else:
        message = (
            f"Déconnecté de {name} : token effacé de cet ordinateur, mais {name} ne l'a pas "
            "révoqué (injoignable). Le révoquer dans ses réglages : "
            "https://github.com/settings/applications"
        )
    return respond(
        Disconnection(forge=forge, login=account.login, revoked=revoked, message=message)
    )


def _check_available(forge: ForgeKind) -> None:
    if not info(forge).available:
        raise HTTPException(409, f"{info(forge).name} : la connexion n'est pas encore disponible.")


async def _check_keyring(connections: Connections) -> None:
    problem = await asyncio.to_thread(connections.accounts.unavailable)
    if problem is not None:
        raise HTTPException(409, problem)


def _find(connections: Connections, connection_id: str) -> Connection:
    connection = connections.get(connection_id)
    if connection is None:
        raise HTTPException(404, f"Connexion inconnue : {connection_id}.")
    return connection


async def _account(connections: Connections, forge: ForgeKind) -> Account:
    try:
        account = await asyncio.to_thread(connections.accounts.get, forge, info(forge).host)
    except AccountsError as err:
        raise HTTPException(409, str(err)) from err
    if account is None:
        raise HTTPException(404, f"Aucun compte {info(forge).name} connecté.")
    return account


async def _connect(
    connections: Connections, forge: ForgeKind, token: str, method: ConnectMethod
) -> JSONResponse:
    await _check_keyring(connections)
    try:
        account = await accounts_module.connect(
            connections.accounts, connections.http, forge, token, method
        )
    except AccountsError as err:
        raise HTTPException(409, str(err)) from err
    except (ForgeError, NetworkError) as err:
        raise _refused(err, forge) from err
    return respond(account, 201)


def _refused(error: ForgeError | NetworkError, forge: ForgeKind) -> HTTPException:
    """L'erreur de l'API pour un refus de la forge (jamais un 401 : celui de l'API veut dire
    « session terminée »)."""
    if isinstance(error, NetworkError):
        return HTTPException(502, failure(error, forge))
    if isinstance(error, RateLimited):
        return HTTPException(409, str(error))
    return HTTPException(400, str(error))


def _connection_response(connection: Connection) -> JSONResponse:
    return respond(
        connection.document(), 201, location=f"/api/accounts/connections/{connection.id}"
    )
