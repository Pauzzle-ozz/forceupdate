"""Le client HTTP commun : User-Agent, reprises, Retry-After, délais, limites par hôte."""

import asyncio
import email.utils
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx

from forceupdate import __version__
from forceupdate.net import USER_AGENT, HttpClient, NetworkError

URL = "https://registry.example/paquet"
OTHER = "https://registry.example/autre"


def run(send: Callable[[HttpClient], Awaitable[Any]], **options: Any) -> tuple[Any, list[float]]:
    """Lance ``send`` avec un client neuf ; rend son résultat et les attentes entre essais,
    sans attendre pour de vrai."""
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async def main() -> Any:
        async with HttpClient(sleep=sleep, **options) as http:
            return await send(http)

    return asyncio.run(main()), sleeps


def failure(send: Callable[[HttpClient], Awaitable[Any]], **options: Any) -> str:
    """Le message de la ``NetworkError`` que lève ``send``."""

    async def expect_error(http: HttpClient) -> str:
        with pytest.raises(NetworkError) as error:
            await send(http)
        return str(error.value)

    message, _ = run(expect_error, **options)
    return message


def test_user_agent_and_response(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(URL).respond(200, json={"name": "paquet"})
    response, sleeps = run(lambda http: http.get(URL))
    expected = f"forceupdate/{__version__} (+https://github.com/Pauzzle-ozz/forceupdate)"
    assert expected == USER_AGENT
    assert route.calls.last.request.headers["user-agent"] == USER_AGENT
    assert response.status_code == 200
    assert response.url == URL
    assert response.media_type == "application/json"
    assert response.json() == {"name": "paquet"}
    assert sleeps == []


def test_extra_headers_are_sent(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(URL).respond(200)
    run(lambda http: http.get(URL, headers={"Accept": "application/vnd.pypi.simple.v1+json"}))
    assert route.calls.last.request.headers["accept"] == "application/vnd.pypi.simple.v1+json"


def test_a_final_status_is_returned_without_retry(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(URL).respond(404, text="Not Found")
    response, sleeps = run(lambda http: http.get(URL))
    assert response.status_code == 404
    assert route.call_count == 1
    assert sleeps == []


def test_5xx_is_retried_with_a_growing_backoff(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(URL).mock(
        side_effect=[httpx.Response(503), httpx.Response(502), httpx.Response(200, text="ok")]
    )
    response, sleeps = run(lambda http: http.get(URL))
    assert response.content == b"ok"
    assert route.call_count == 3
    assert 0.5 <= sleeps[0] <= 1.0
    assert 1.0 <= sleeps[1] <= 1.5


def test_retry_after_in_seconds(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL).mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200)]
    )
    _, sleeps = run(lambda http: http.get(URL))
    assert sleeps == [7.0]


def test_retry_after_as_an_http_date(respx_mock: respx.MockRouter) -> None:
    later = email.utils.format_datetime(datetime.now(UTC) + timedelta(seconds=30), usegmt=True)
    respx_mock.get(URL).mock(
        side_effect=[httpx.Response(503, headers={"Retry-After": later}), httpx.Response(200)]
    )
    _, sleeps = run(lambda http: http.get(URL))
    assert 25 < sleeps[0] <= 30


@pytest.mark.parametrize("value", ["Wed, 21 Oct 2015 07:28:00 GMT", "plus tard", "-3"])
def test_a_past_or_unreadable_retry_after(respx_mock: respx.MockRouter, value: str) -> None:
    respx_mock.get(URL).mock(
        side_effect=[httpx.Response(503, headers={"Retry-After": value}), httpx.Response(200)]
    )
    _, sleeps = run(lambda http: http.get(URL))
    # Une date passée : on réessaie tout de suite ; illisible : l'attente par défaut.
    assert sleeps == [0.0] if value.startswith("Wed") else 0.5 <= sleeps[0] <= 1.0


def test_a_long_retry_after_gives_up_and_abandons_the_host(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(URL).respond(429, headers={"Retry-After": "3600"})
    other = respx_mock.get(OTHER).respond(200)
    elsewhere = respx_mock.get("https://ailleurs.example/").respond(200)

    async def send(http: HttpClient) -> list[str]:
        messages = []
        for url in (URL, OTHER):
            with pytest.raises(NetworkError) as error:
                await http.get(url)
            messages.append(str(error.value))
        await http.get("https://ailleurs.example/")
        return messages

    messages, sleeps = run(send)
    expected = "registry.example limite le débit (HTTP 429) : réessayer dans 60 min."
    assert messages == [expected, expected]
    assert route.call_count == 1
    assert other.call_count == 0
    assert elsewhere.call_count == 1
    assert sleeps == []


def test_5xx_after_every_retry(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(URL).respond(503)
    other = respx_mock.get(OTHER).respond(200)

    async def send(http: HttpClient) -> int:
        with pytest.raises(NetworkError, match=r"^registry\.example en erreur \(HTTP 503\)\.$"):
            await http.get(URL)
        # Une page en erreur n'empêche pas d'interroger le reste de l'hôte.
        return (await http.get(OTHER)).status_code

    status, sleeps = run(send)
    assert route.call_count == 4
    assert len(sleeps) == 3
    assert status == 200
    assert other.call_count == 1


def test_a_429_without_retry_after(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL).respond(429)
    assert failure(lambda http: http.get(URL)) == "registry.example limite le débit (HTTP 429)."


def test_a_transport_error_is_retried(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(URL).mock(
        side_effect=[httpx.ConnectError("connexion refusée"), httpx.Response(200)]
    )
    response, sleeps = run(lambda http: http.get(URL))
    assert response.status_code == 200
    assert route.call_count == 2
    assert len(sleeps) == 1


def test_an_unreachable_host_is_abandoned_for_the_session(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(URL).mock(side_effect=httpx.ConnectError("getaddrinfo failed"))
    other = respx_mock.get(OTHER).respond(200)

    async def send(http: HttpClient) -> list[str]:
        messages = []
        for url in (URL, OTHER):
            with pytest.raises(NetworkError) as error:
                await http.get(url)
            messages.append(str(error.value))
        return messages

    messages, sleeps = run(send)
    assert messages == ["registry.example injoignable (ConnectError)."] * 2
    assert route.call_count == 4
    assert other.call_count == 0
    assert len(sleeps) == 3


def test_a_timeout(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL).mock(side_effect=httpx.ReadTimeout("trop long"))
    message = failure(lambda http: http.get(URL))
    assert message == "registry.example ne répond pas (délai dépassé)."


def test_the_deadline_of_an_attempt(respx_mock: respx.MockRouter) -> None:
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200)

    respx_mock.get(URL).mock(side_effect=slow)
    message = failure(lambda http: http.get(URL), deadline=0.05, retries=0)
    assert message == "registry.example ne répond pas (délai dépassé)."


def test_a_post_is_retried_only_when_asked(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(URL).mock(
        side_effect=[httpx.Response(503), httpx.Response(503), httpx.Response(200)]
    )

    async def send(http: HttpClient) -> int:
        with pytest.raises(NetworkError):
            await http.request("POST", URL, json={"q": 1})
        response = await http.request("POST", URL, json={"q": 1}, retry=True)
        return response.status_code

    status, _ = run(send)
    assert status == 200
    assert route.call_count == 3
    assert route.calls.last.request.content == b'{"q":1}'


def test_offline_sends_nothing(respx_mock: respx.MockRouter) -> None:
    message = failure(lambda http: http.get(URL), offline=True)
    assert message == "mode hors ligne : registry.example n'est pas interrogé."
    assert respx_mock.calls.call_count == 0


def test_a_body_too_large(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL).respond(200, content=b"x" * 2048)
    message = failure(lambda http: http.get(URL), max_body=1024)
    assert message == "réponse de registry.example trop grosse (plus de 0 Mo)."


def test_a_body_too_large_without_content_length(respx_mock: respx.MockRouter) -> None:
    async def chunks() -> Any:
        for _ in range(4):
            yield b"x" * 512

    respx_mock.get(URL).mock(side_effect=lambda request: httpx.Response(200, content=chunks()))
    with pytest.raises(NetworkError, match="trop grosse"):
        run(lambda http: http.get(URL), max_body=1024)
    response, _ = run(lambda http: http.get(URL), max_body=4096)
    assert len(response.content) == 2048


def test_concurrency_is_bounded_per_host(respx_mock: respx.MockRouter) -> None:
    active: dict[str, int] = {}
    peaks: dict[str, int] = {}

    async def slow(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        active[host] = active.get(host, 0) + 1
        peaks[host] = max(peaks.get(host, 0), active[host])
        await asyncio.sleep(0.01)
        active[host] -= 1
        return httpx.Response(200)

    respx_mock.route(host="a.example").mock(side_effect=slow)
    respx_mock.route(host="b.example").mock(side_effect=slow)

    async def send(http: HttpClient) -> None:
        urls = [f"https://{host}.example/{n}" for host in "ab" for n in range(6)]
        await asyncio.gather(*(http.get(url) for url in urls))

    run(send, max_per_host=2)
    assert peaks == {"a.example": 2, "b.example": 2}


def test_redirects_are_followed(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL).respond(301, headers={"Location": OTHER})
    respx_mock.get(OTHER).respond(200, text="ici")
    response, _ = run(lambda http: http.get(URL))
    assert response.url == OTHER
    assert response.content == b"ici"


def test_an_error_that_retrying_cannot_fix(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(URL).respond(302, headers={"Location": URL})
    message = failure(lambda http: http.get(URL))
    assert message == "requête vers registry.example impossible (TooManyRedirects)."
    assert route.call_count == 21
