"""Fixtures for the LISA tests. All clubs, members and their activities are made up."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.clubprogramma.const import (
    CONF_API_URL,
    CONF_BASIC,
    CONF_CLUB_ID,
    CONF_CLUB_NAME,
    CONF_CLUB_SHORT,
    CONF_FEDERATION_ID,
    CONF_LOGIN_TYPE,
    CONF_MEMBER_ID,
    CONF_NUMBER,
    CONF_PASSWORD,
    CONF_SPORT,
    CONF_TOKEN,
    DOMAIN,
    LOGIN_CLUB_NUMBER,
)

FIXTURES = Path(__file__).parent / "fixtures"
API = "https://api.example.invalid/api/v1/my"
BASIC = "Basic dGVzdHVzZXI6dGVzdHBhc3M="
URL_WEB = "https://mijn.lisahockey.nl/"
URL_BUNDLE = "https://mijn.lisahockey.nl/assets/index-Test123.js"
URL_FEDERATION = f"{API}/federations"
URL_CLUBS = f"{API}/federations/fed-1/clubs"
URL_LOGIN = f"{API}/clubs/club-1/auth_tokens"
URL_MEMBER = f"{API}/clubs/club-1/members/m-parent"
URL_PROGRAM = f"{API}/federations/fed-1/program"

# Saturday 14 November 2026, 09:00 in the Netherlands; Alex plays away at 10:45.
NOW = "2026-11-14T08:00:00+00:00"


def load_fixture(name: str) -> Any:
    """Load a fixture."""
    text = (FIXTURES / name).read_text(encoding="utf-8")
    return json.loads(text) if name.endswith(".json") else text


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load the integration from custom_components."""


@pytest.fixture
async def dutch(hass: Any) -> None:
    """Run Home Assistant in Dutch, in Dutch time."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    hass.config.language = "nl"


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a configured LISA login."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Robin (HCV)",
        unique_id="club-1:m-parent",
        data={
            CONF_SPORT: "hockey",
            CONF_API_URL: API,
            CONF_BASIC: BASIC,
            CONF_FEDERATION_ID: "fed-1",
            CONF_CLUB_ID: "club-1",
            CONF_CLUB_NAME: "HC Voorbeeld",
            CONF_CLUB_SHORT: "HCV",
            CONF_LOGIN_TYPE: LOGIN_CLUB_NUMBER,
            CONF_NUMBER: "12345",
            CONF_PASSWORD: "geheim",
            CONF_TOKEN: "token-0",
            CONF_MEMBER_ID: "m-parent",
        },
    )


@pytest.fixture
def mock_lisa(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Answer every LISA call with the fixtures."""
    aioclient_mock.get(URL_WEB, text=load_fixture("web_app.html"))
    aioclient_mock.get(URL_BUNDLE, text=load_fixture("web_app_bundle.js"))
    aioclient_mock.get(URL_FEDERATION, json={"id": "fed-1", "sport": "hockey"})
    aioclient_mock.get(URL_CLUBS, json=load_fixture("clubs.json"))
    aioclient_mock.post(URL_LOGIN, json=load_fixture("login.json"), status=201)
    aioclient_mock.get(URL_MEMBER, json=load_fixture("member.json"))
    aioclient_mock.get(URL_PROGRAM, json=load_fixture("program.json"))
    return aioclient_mock


def calls_to(mock: AiohttpClientMocker, url: str, method: str = "get") -> list[tuple]:
    """Return the calls to a URL (any query)."""
    return [
        call
        for call in mock.mock_calls
        if call[0].lower() == method and str(call[1]).split("?")[0] == url
    ]
