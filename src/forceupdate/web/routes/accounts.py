"""Les comptes des forges : lister, connecter (OAuth, device flow, token collé, ``gh``),
vérifier les droits, déconnecter.

Un compte se désigne par sa forge et son hôte (``?host=``, par défaut le service en ligne de
la forge) : un compte gitlab.com et un compte par instance GitLab auto-hébergée. Une instance
se connecte par son adresse et un token collé. Bitbucket Cloud : par OAuth, ou un token d'API
Atlassian collé.

Les tokens ne vont jamais au navigateur : il reçoit le compte (identifiant, droits), jamais son
token. Un refus de la forge n'est jamais un ``401`` de l'API (celui-là veut dire « session
terminée ») : c'est un ``400`` avec la raison, ou ``problem`` sur le compte ; une forge qui ne
répond pas, un ``502``.
"""

import asyncio
import urllib.parse
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from forceupdate.forges import FORGES, ForgeInfo, bitbucket, github, gitlab, info, label
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

SCOPES = {
    ForgeKind.GITHUB: github.SCOPES,
    ForgeKind.GITLAB: gitlab.SCOPES,
    ForgeKind.BITBUCKET: bitbucket.SCOPES,
}
"""Les portées demandées à la connexion, par forge (Bitbucket : celles de l'application)."""
TOKEN_SCOPES = {**SCOPES, ForgeKind.BITBUCKET: bitbucket.API_TOKEN_SCOPES}
"""Les portées d'un token collé, par forge."""
TOKEN_URLS = {
    ForgeKind.GITHUB: github.TOKEN_SETTINGS_URL,
    ForgeKind.GITLAB: gitlab.token_settings_url(),
    ForgeKind.BITBUCKET: bitbucket.TOKEN_SETTINGS_URL,
}
"""Où créer un token à coller, portées pré-cochées."""
APPLICATIONS_URLS = {
    ForgeKind.GITHUB: github.APPLICATIONS_URL,
    ForgeKind.GITLAB: f"{gitlab.WEB_URL}/-/user_settings/applications",
    ForgeKind.BITBUCKET: bitbucket.APPLICATIONS_URL,
}
"""Où révoquer à la main l'accès donné à forceupdate."""


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
        pending = connections.pending(forge.kind)
        mine = [account for account in connected if account.forge is forge.kind]
        forges.append(
            ForgeStatus(
                forge=forge.kind,
                name=forge.name,
                host=forge.host,
                available=forge.available,
                methods=_methods(forge, connections, gh=gh),
                scopes=SCOPES.get(forge.kind, ()),
                token_scopes=TOKEN_SCOPES.get(forge.kind, ()),
                token_url=TOKEN_URLS.get(forge.kind),
                revocable=app.revocable if (app := connections.apps.get(forge.kind)) else False,
                applications_url=APPLICATIONS_URLS.get(forge.kind),
                self_hosted=forge.self_hosted,
                request=forge.request,
                account=next((a for a in mine if a.host == forge.host), None),
                instances=tuple(a for a in mine if a.host != forge.host),
                connection=pending.document() if pending is not None else None,
            )
        )
    return respond(AccountList(keyring=problem, forges=tuple(forges)))


def _methods(forge: ForgeInfo, connections: Connections, *, gh: bool) -> tuple[ConnectMethod, ...]:
    """Les façons de se connecter à ``forge`` possibles maintenant."""
    if not forge.available:
        return ()
    methods: list[ConnectMethod] = []
    if connections.web_flow(forge.kind):
        methods.append(ConnectMethod.OAUTH)
    if forge.kind is ForgeKind.GITHUB:
        methods.append(ConnectMethod.DEVICE)
    methods.append(ConnectMethod.TOKEN)
    if forge.kind is ForgeKind.GITHUB and gh:
        methods.append(ConnectMethod.GH)
    return tuple(methods)


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
    name = info(forge).name
    if not connections.web_flow(forge):
        other = "avec un code (device flow)" if forge is ForgeKind.GITHUB else "avec un token"
        raise HTTPException(
            409, f"L'application forceupdate n'est pas prête sur {name} : se connecter {other}."
        )
    expected = f"127.0.0.1:{connections.port}"
    if request.headers.get("host") != expected:
        other = ", ou se connecter avec un code" if forge is ForgeKind.GITHUB else ""
        raise HTTPException(
            409,
            f"{name} ne revient que vers 127.0.0.1 : ouvrir l'interface par http://{expected} "
            f"(l'adresse que donne « forceupdate ui »){other}.",
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
    ``GET /api/accounts/connections/{id}``. GitHub seulement."""
    _check_available(forge)
    if forge is not ForgeKind.GITHUB:
        raise HTTPException(400, f"{info(forge).name} : pas de connexion par code, ici.")
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
    """Connecte un compte avec un token collé (GitHub : classic ou fine-grained ; GitLab : un
    token d'accès personnel), une fois que la forge l'a accepté. ``url`` : l'adresse d'une
    instance auto-hébergée (GitLab)."""
    _check_available(forge)
    host = _instance(forge, body.url) if body.url else info(forge).host
    token = body.token.strip()
    if not token or len(token) > MAX_TOKEN or any(c.isspace() for c in token):
        raise HTTPException(
            400, "Ce n'est pas un token : une seule suite de caractères, sans espace."
        )
    return await _connect(connections, forge, token, ConnectMethod.TOKEN, host=host)


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
async def verify_account(
    forge: ForgeKind, connections: CurrentConnections, host: str | None = None
) -> JSONResponse:
    """Redemande à la forge qui est connecté et avec quels droits (le token renouvelé s'il a
    expiré). Un token refusé (révoqué sur la forge) est dit dans ``problem`` : le compte reste
    affiché, pour qu'on se reconnecte."""
    account = await _account(connections, forge, host)
    try:
        checked = await accounts_module.verify(
            connections.accounts,
            connections.http,
            account,
            renew=connections.renew(account),
        )
    except AccountsError as err:
        raise HTTPException(409, str(err)) from err
    except (ForgeError, NetworkError) as err:
        raise _refused(err, forge) from err
    return respond(checked)


@router.delete("/{forge}", response_model=Disconnection, responses=errors(401, 403, 404, 409))
async def disconnect(
    forge: ForgeKind, connections: CurrentConnections, host: str | None = None
) -> JSONResponse:
    """Déconnecte le compte : efface son token du trousseau, et le révoque auprès de la forge
    s'il a été donné à forceupdate (OAuth, device flow)."""
    host = (host or info(forge).host).lower()
    name = label(forge, host)
    try:
        account, token = await asyncio.to_thread(connections.accounts.remove, forge, host)
    except AccountsError as err:
        raise HTTPException(409, str(err)) from err
    if account is None or token is None:
        raise HTTPException(404, f"Aucun compte {name} connecté.")
    revoked: bool | None = None
    app = connections.apps.get(forge)
    if account.method.from_app and app is not None:
        revoked = await app.revoke(connections.http, token) if app.revocable else False
    if revoked:
        message = f"Déconnecté de {name} : token effacé de cet ordinateur et révoqué."
    elif revoked is None:
        message = (
            f"Déconnecté de {name} : token effacé de cet ordinateur. Il reste valable sur "
            f"{name} (il n'appartient pas à forceupdate)."
        )
    elif app is not None and not app.revocable:
        message = (
            f"Déconnecté de {name} : token effacé de cet ordinateur. {name} ne permet pas de le "
            "révoquer d'ici : retirer l'accès de forceupdate dans ses réglages (applications "
            "autorisées)."
        )
    else:
        message = (
            f"Déconnecté de {name} : token effacé de cet ordinateur, mais {name} ne l'a pas "
            f"révoqué (injoignable). Le révoquer dans ses réglages : {APPLICATIONS_URLS[forge]}"
        )
    return respond(
        Disconnection(forge=forge, host=host, login=account.login, revoked=revoked, message=message)
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


async def _account(connections: Connections, forge: ForgeKind, host: str | None) -> Account:
    host = (host or info(forge).host).lower()
    try:
        account = await asyncio.to_thread(connections.accounts.get, forge, host)
    except AccountsError as err:
        raise HTTPException(409, str(err)) from err
    if account is None:
        raise HTTPException(404, f"Aucun compte {label(forge, host)} connecté.")
    return account


def _instance(forge: ForgeKind, url: str) -> str:
    """L'hôte d'une instance auto-hébergée, d'après son adresse (``https://hôte[:port]``).
    Lève ``HTTPException`` (400) avec un message à montrer."""
    if not info(forge).self_hosted:
        raise HTTPException(400, f"{info(forge).name} : pas d'instance auto-hébergée, ici.")
    text = url.strip()
    parsed = urllib.parse.urlsplit(text if "://" in text else f"https://{text}")
    try:
        port = parsed.port
    except ValueError:
        port = -1
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path.strip("/")
        or port == -1
    ):
        raise HTTPException(
            400,
            "Adresse d'instance refusée : donner https://hôte (ou https://hôte:port), sans "
            "chemin ni identifiants. Le token ne part jamais en clair (http).",
        )
    return parsed.hostname.lower() + (f":{port}" if port not in (None, 443) else "")


async def _connect(
    connections: Connections,
    forge: ForgeKind,
    token: str,
    method: ConnectMethod,
    *,
    host: str | None = None,
) -> JSONResponse:
    await _check_keyring(connections)
    try:
        account = await accounts_module.connect(
            connections.accounts, connections.http, forge, token, method, host=host
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
