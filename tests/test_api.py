"""Tests for the LISA client."""

from __future__ import annotations

from datetime import date
from http import HTTPStatus

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.lisa.api import (
    Credentials,
    LisaAuthError,
    LisaClient,
    LisaConnectionError,
    LisaResponseError,
    WebAppConfig,
    fetch_web_app_config,
)

from .conftest import (
    API,
    BASIC,
    URL_BUNDLE,
    URL_LOGIN,
    URL_PROGRAM,
    URL_WEB,
    calls_to,
    load_fixture,
)

CREDENTIALS = Credentials(club_id="club-1", number="12345", password="geheim")


def _client(hass: HomeAssistant, **kwargs) -> LisaClient:
    return LisaClient(async_get_clientsession(hass), WebAppConfig(API, BASIC), **kwargs)


async def test_web_app_config(hass: HomeAssistant, mock_lisa: AiohttpClientMocker) -> None:
    """The API address and public web user come from the web app's bundle."""
    session = async_get_clientsession(hass)
    config = await fetch_web_app_config(session, "mijn.lisahockey.nl", "hockey")
    assert config == WebAppConfig(API, BASIC)
    tennis = await fetch_web_app_config(session, "mijn.lisahockey.nl", "tennis")
    assert tennis.api_url == "https://api-tennis.example.invalid/api/v1/my"


async def test_web_app_config_changed(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A bundle without the settings is an unexpected answer."""
    aioclient_mock.get(URL_WEB, text=load_fixture("web_app.html"))
    aioclient_mock.get(URL_BUNDLE, text="var nothing = 1;")
    with pytest.raises(LisaResponseError):
        await fetch_web_app_config(async_get_clientsession(hass), "mijn.lisahockey.nl", "hockey")


async def test_login(hass: HomeAssistant, mock_lisa: AiohttpClientMocker) -> None:
    """Logging in sends the number and password with the public user, and keeps the token."""
    tokens: list[str] = []
    client = _client(hass, on_token_change=tokens.append)
    assert await client.login(CREDENTIALS) == "m-parent"
    assert client.token == "token-1"
    assert tokens == ["token-1"]
    _method, _url, body, headers = calls_to(mock_lisa, URL_LOGIN, "post")[0]
    assert body == {
        "club_membership_number": "12345",
        "federation_membership_number": None,
        "password": "geheim",
    }
    assert headers["Authorization"] == BASIC
    assert "x-lisa-auth-token" not in headers


async def test_login_with_federation_number(
    hass: HomeAssistant, mock_lisa: AiohttpClientMocker
) -> None:
    """The federation number goes in its own field."""
    credentials = Credentials("club-1", "K12AB34", "geheim", federation_number=True)
    await _client(hass).login(credentials)
    body = calls_to(mock_lisa, URL_LOGIN, "post")[0][2]
    assert body["federation_membership_number"] == "K12AB34"
    assert body["club_membership_number"] is None


@pytest.mark.parametrize("status", [HTTPStatus.FORBIDDEN, HTTPStatus.UNAUTHORIZED])
async def test_login_refused(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, status: int
) -> None:
    """A refused login (LISA answers 403 with an empty body) is an auth error."""
    aioclient_mock.post(URL_LOGIN, status=status, text="")
    with pytest.raises(LisaAuthError):
        await _client(hass).login(CREDENTIALS)


async def test_logs_in_again(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """A refused token logs in again with the stored login, then retries."""
    calls = 0

    async def respond(method, url, data):
        nonlocal calls
        calls += 1
        if calls == 1:
            return AiohttpClientMockResponse("get", url, status=HTTPStatus.UNAUTHORIZED, text="")
        return AiohttpClientMockResponse("get", url, json=load_fixture("program.json"))

    aioclient_mock.get(URL_PROGRAM, side_effect=respond)
    aioclient_mock.post(URL_LOGIN, json=load_fixture("login.json"), status=201)
    client = _client(hass, token="old", credentials=CREDENTIALS)
    tiles = await client.get_program("fed-1", date(2026, 11, 13), date(2026, 12, 19))
    assert len(tiles) == 10
    assert client.token == "token-1"
    assert aioclient_mock.mock_calls[-1][3]["x-lisa-auth-token"] == "token-1"


async def test_forbidden_after_login(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Still refused after logging in fine: not allowed for this member, not a bad login."""
    aioclient_mock.get(f"{API}/clubs/club-1/members", status=HTTPStatus.FORBIDDEN, text="")
    aioclient_mock.post(URL_LOGIN, json=load_fixture("login.json"), status=201)
    client = _client(hass, token="old", credentials=CREDENTIALS)
    with pytest.raises(LisaResponseError):
        await client.get("/clubs/club-1/members")


async def test_program_pages(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """The program is followed over its pages, each tile once."""
    program = load_fixture("program.json")
    first = {**program, "tiles": program["tiles"][:5], "page_end_date": "2026-11-17T16:00:00Z"}
    second = {**program, "tiles": program["tiles"][4:], "page_end_date": "2026-12-19T00:00:00Z"}
    answers = iter(
        [
            AiohttpClientMockResponse("get", URL_PROGRAM, json=first),
            AiohttpClientMockResponse("get", URL_PROGRAM, json=second),
        ]
    )

    async def respond(method, url, data):
        return next(answers)

    aioclient_mock.get(URL_PROGRAM, side_effect=respond)
    tiles = await _client(hass, token="t").get_program(
        "fed-1", date(2026, 11, 13), date(2026, 12, 19)
    )
    assert len(tiles) == 10
    urls = [str(call[1]) for call in calls_to(aioclient_mock, URL_PROGRAM)]
    assert "from_date=2026-11-13" in urls[0]
    assert "from_date=2026-11-17" in urls[1]


async def test_errors(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """Server and network errors are connection errors; odd answers response errors."""
    client = _client(hass, token="t")
    aioclient_mock.get(URL_PROGRAM, status=HTTPStatus.BAD_GATEWAY)
    with pytest.raises(LisaConnectionError):
        await client.get_program("fed-1", date(2026, 11, 13), date(2026, 12, 19))
    aioclient_mock.clear_requests()
    aioclient_mock.get(URL_PROGRAM, json={"no": "tiles"})
    with pytest.raises(LisaResponseError):
        await client.get_program("fed-1", date(2026, 11, 13), date(2026, 12, 19))
    aioclient_mock.clear_requests()
    aioclient_mock.get(URL_PROGRAM, exc=TimeoutError())
    with pytest.raises(LisaConnectionError):
        await client.get_program("fed-1", date(2026, 11, 13), date(2026, 12, 19))
