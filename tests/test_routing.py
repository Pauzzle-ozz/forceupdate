"""Les registres privés (E33) : les identifiants liés à leur adresse (``net.auth``), le client
HTTP qui les envoie, les fichiers de la personne (``userfiles``), et l'aiguillage (``routing`` :
les registres déclarés d'abord, le public ensuite, jamais après un refus)."""

import asyncio
from pathlib import Path

import httpx
import pytest
import respx
from conftest import UserFiles

from forceupdate import userfiles
from forceupdate.models import Ecosystem
from forceupdate.net import Cache, HttpClient
from forceupdate.net.auth import (
    Credential,
    Credentials,
    basic,
    bearer,
    bound_to,
    is_loopback,
    split_userinfo,
)
from forceupdate.registries import AccessRefused, PackageInfo, PackageNotFound, RegistryError
from forceupdate.routing import Clients, Declared, Route

PRIVATE = "https://npm.acme.example/"
LEFT_PAD = Path(__file__).parent / "fixtures" / "npm" / "left-pad.json"


async def no_sleep(_: float) -> None:
    pass


# -- net.auth -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://npm.acme.example/@acme%2Fui", True),
        ("https://NPM.acme.example:443/x", True),
        ("http://npm.acme.example/x", False),  # en clair, vers une autre machine : jamais
        ("https://npm.acme.example:8443/x", False),  # un autre port
        ("https://evil.example/npm.acme.example/", False),
        ("https://npm.acme.example.evil.example/", False),
        ("ftp://npm.acme.example/", False),
    ],
)
def test_a_credential_goes_to_its_host_only(url: str, expected: bool) -> None:
    credential = bound_to(PRIVATE, value=bearer("secret"), source="~/.npmrc")
    assert credential.matches(url) is expected


def test_a_credential_is_bound_to_its_path() -> None:
    credential = bound_to("https://corp.example/api/npm/team/", value="x", source="s")
    assert credential.matches("https://corp.example/api/npm/team/lodash")
    assert not credential.matches("https://corp.example/api/npm/other/lodash")
    assert not credential.matches("https://corp.example/api/npm/teammate/lodash")


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]", "127.1.2.3"])
def test_http_to_the_machine_itself_may_carry_a_credential(host: str) -> None:
    credential = bound_to(f"http://{host}:4873/", value="x", source="s", with_scheme=False)
    assert credential.matches(f"http://{host}:4873/lodash")
    assert is_loopback(host)


def test_a_scheme_free_credential_takes_the_default_port_of_each_scheme() -> None:
    credential = bound_to("https://corp.example/", value="x", source="s", with_scheme=False)
    assert credential.matches("https://corp.example/a")
    assert not credential.matches("http://corp.example/a")  # en clair : jamais


def test_the_secret_never_shows() -> None:
    credential = bound_to(PRIVATE, value=bearer("s3cr3t"), source="~/.npmrc")
    assert "s3cr3t" not in repr(credential)
    assert "s3cr3t" not in repr(Credentials([credential]))
    assert repr(credential) == "Credential(npm.acme.example/, ~/.npmrc)"


def test_the_most_precise_credential_wins() -> None:
    broad = bound_to("https://corp.example/", value="broad", source="s")
    narrow = bound_to("https://corp.example/npm/", value="narrow", source="s")
    credentials = Credentials([broad, narrow])
    assert credentials.for_url("https://corp.example/npm/x") is narrow
    assert credentials.for_url("https://corp.example/maven/x") is broad
    assert credentials.for_url("https://other.example/") is None


def test_the_first_credential_for_an_address_keeps_priority() -> None:
    project = bound_to(PRIVATE, value="project", source=".npmrc")
    mine = bound_to(PRIVATE, value="mine", source="~/.npmrc")
    assert Credentials([project, mine]).for_url(PRIVATE) is project


def test_userinfo_is_taken_out_of_an_address() -> None:
    assert split_userinfo("https://jo%40corp:p%3Ass@pkgs.example/simple/") == (
        "https://pkgs.example/simple/",
        ("jo@corp", "p:ss"),
    )
    assert split_userinfo("https://pkgs.example/simple/") == ("https://pkgs.example/simple/", None)
    assert basic("jo", "pw") == "Basic am86cHc="


# -- userfiles ------------------------------------------------------------------------


def test_variables_are_expanded_from_the_environment(user_files: UserFiles) -> None:
    user_files.env["NPM_TOKEN"] = "abc"
    assert userfiles.expand("${NPM_TOKEN}") == "abc"
    assert userfiles.expand("${env.NPM_TOKEN}/x") == "abc/x"  # Maven
    assert userfiles.expand("%NPM_TOKEN%", style="windows") == "abc"  # NuGet
    assert userfiles.expand("${MISSING}") is None
    assert userfiles.unexpanded("${NPM_TOKEN}")
    assert userfiles.unexpanded("%NPM_TOKEN%")
    assert not userfiles.unexpanded("https://x/%40scope%2Fname")


def test_the_person_files_are_never_read_by_a_test() -> None:
    with pytest.raises(RuntimeError, match="fichier de la personne refusé"):
        userfiles.read(Path.home() / ".npmrc")


def test_the_test_home_is_read(user_files: UserFiles) -> None:
    user_files.write(".npmrc", "registry=https://x/\n")
    assert userfiles.read(userfiles.home() / ".npmrc") == "registry=https://x/\n"
    assert userfiles.environ() == {}


# -- HttpClient ----------------------------------------------------------------------


def get(url: str, credentials: Credentials) -> httpx.Response:
    async def main() -> object:
        async with HttpClient(sleep=no_sleep) as http:
            return await http.get(url, auth=credentials)

    return asyncio.run(main())  # type: ignore[return-value]


@respx.mock
def test_the_bound_credential_goes_with_the_request() -> None:
    route = respx.get(f"{PRIVATE}lodash").respond(200, json={})
    credentials = Credentials([bound_to(PRIVATE, value=bearer("t0k"), source="s")])
    get(f"{PRIVATE}lodash", credentials)
    assert route.calls.last.request.headers["authorization"] == "Bearer t0k"


@respx.mock
def test_no_credential_for_another_host() -> None:
    route = respx.get("https://other.example/lodash").respond(200, json={})
    credentials = Credentials([bound_to(PRIVATE, value=bearer("t0k"), source="s")])
    get("https://other.example/lodash", credentials)
    assert "authorization" not in route.calls.last.request.headers


@respx.mock
def test_a_redirect_to_another_origin_goes_without_the_credential() -> None:
    respx.get(f"{PRIVATE}lodash").respond(302, headers={"location": "https://cdn.example/l"})
    cdn = respx.get("https://cdn.example/l").respond(200, json={})
    # Même un identifiant de la personne pour l'autre hôte ne part pas sur une redirection.
    credentials = Credentials(
        [
            bound_to(PRIVATE, value=bearer("t0k"), source="s"),
            bound_to("https://cdn.example/", value=bearer("cdn"), source="s"),
        ]
    )
    response = get(f"{PRIVATE}lodash", credentials)
    assert response.status_code == 200
    assert "authorization" not in cdn.calls.last.request.headers


@respx.mock
def test_a_redirect_on_the_same_origin_keeps_the_credential() -> None:
    respx.get(f"{PRIVATE}lodash").respond(301, headers={"location": "/v2/lodash"})
    moved = respx.get(f"{PRIVATE}v2/lodash").respond(200, json={})
    credentials = Credentials([bound_to(PRIVATE, value=bearer("t0k"), source="s")])
    get(f"{PRIVATE}lodash", credentials)
    assert moved.calls.last.request.headers["authorization"] == "Bearer t0k"


@respx.mock
def test_endless_redirects_stop() -> None:
    respx.get(f"{PRIVATE}a").respond(302, headers={"location": "/a"})
    with pytest.raises(Exception, match="impossible"):
        get(f"{PRIVATE}a", Credentials())


# -- Clients : la chaîne des registres --------------------------------------------------


def lookup(route: Route, name: str = "left-pad") -> PackageInfo | Exception:
    async def main() -> PackageInfo | Exception:
        async with HttpClient(sleep=no_sleep) as http:
            clients = Clients(http, Cache.disabled(), Credentials())
            try:
                return await clients.package(Ecosystem.NPM, route, name)
            except (PackageNotFound, RegistryError) as error:
                return error

    return asyncio.run(main())


MIRROR = Declared(url="https://mirror.example/npm", file=".npmrc")
CORP = Declared(url="https://corp.example", file=".npmrc")


@respx.mock
def test_declared_registries_come_first_then_the_public_one() -> None:
    mirror = respx.get("https://mirror.example/npm/left-pad").respond(404, json={})
    corp = respx.get("https://corp.example/left-pad").respond(404, json={})
    public = respx.get("https://registry.npmjs.org/left-pad").respond(
        200, content=LEFT_PAD.read_bytes(), headers={"content-type": "application/json"}
    )
    found = lookup(Route(registries=(MIRROR, CORP)))
    assert isinstance(found, PackageInfo)
    assert (mirror.call_count, corp.call_count, public.call_count) == (1, 1, 1)
    assert found.url == "https://www.npmjs.com/package/left-pad"


@respx.mock
def test_the_first_registry_that_knows_the_package_wins() -> None:
    respx.get("https://mirror.example/npm/left-pad").respond(
        200, content=LEFT_PAD.read_bytes(), headers={"content-type": "application/json"}
    )
    corp = respx.get("https://corp.example/left-pad").respond(404, json={})
    found = lookup(Route(registries=(MIRROR, CORP)))
    assert isinstance(found, PackageInfo)
    assert found.url is None  # la page npmjs.com n'est pas celle d'un registre privé
    assert corp.call_count == 0


@respx.mock
def test_a_refusal_never_falls_back_to_the_public_registry() -> None:
    respx.get("https://mirror.example/npm/left-pad").respond(401)
    public = respx.get("https://registry.npmjs.org/left-pad").respond(200, json={})
    found = lookup(Route(registries=(MIRROR,)))
    assert isinstance(found, AccessRefused)
    assert str(found) == (
        "mirror.example refuse l'accès à left-pad (HTTP 401) : identifiants absents ou refusés."
    )
    assert public.call_count == 0


@respx.mock
def test_an_error_never_falls_back_to_the_public_registry() -> None:
    respx.get("https://mirror.example/npm/left-pad").respond(500)
    public = respx.get("https://registry.npmjs.org/left-pad").respond(200, json={})
    found = lookup(Route(registries=(MIRROR,)))
    assert isinstance(found, RegistryError)
    assert "mirror.example" in str(found)
    assert public.call_count == 0


@respx.mock
def test_a_private_package_unknown_to_its_registry() -> None:
    respx.get("https://corp.example/%40acme%2Fui").respond(404, json={})
    found = lookup(Route(registries=(CORP,), public=False, private=True), "@acme/ui")
    assert isinstance(found, PackageNotFound)
    assert str(found) == "@acme/ui est introuvable sur corp.example."


def test_a_credential_value_is_only_a_header() -> None:
    credential = Credential(host="h", value="Bearer x", source="s")
    assert credential.headers() == {"Authorization": "Bearer x"}
