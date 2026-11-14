"""Tests for the config flow."""

from __future__ import annotations

from http import HTTPStatus

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.lisa.const import (
    CONF_CLUB_ID,
    CONF_LOGIN_TYPE,
    CONF_MEMBER_ID,
    CONF_NUMBER,
    CONF_PASSWORD,
    CONF_TOKEN,
    DOMAIN,
)

from .conftest import BASIC, URL_CLUBS, URL_LOGIN, load_fixture

LOGIN = {CONF_LOGIN_TYPE: "club", CONF_NUMBER: " 12345 ", CONF_PASSWORD: "geheim"}


async def _start(hass: HomeAssistant, query: str = "voorbeeld"):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"sport": "hockey", "query": query}
    )


async def test_flow(hass: HomeAssistant, mock_lisa: AiohttpClientMocker) -> None:
    """Search the club, log in, and the login is set up."""
    result = await _start(hass)
    assert result["step_id"] == "login"
    assert result["description_placeholders"] == {"club": "HC Voorbeeld"}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], LOGIN)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Robin (HCV)"
    assert result["result"].unique_id == "club-1:m-parent"
    data = result["data"]
    assert data[CONF_CLUB_ID] == "club-1"
    assert data[CONF_NUMBER] == "12345"
    assert data[CONF_MEMBER_ID] == "m-parent"
    assert data[CONF_TOKEN] == "token-1"
    assert data["basic"] == BASIC


async def test_several_clubs(hass: HomeAssistant, mock_lisa: AiohttpClientMocker) -> None:
    """Several hits: pick the club."""
    clubs = load_fixture("clubs.json")
    clubs["clubs"].append(
        {"club": {"id": "club-2", "name": "MHC Proef", "short_name": "MHCP", "city": "testdorp"}}
    )
    mock_lisa.clear_requests()
    mock_lisa.get(URL_CLUBS, json=clubs)
    for url, kwargs in (
        ("https://mijn.lisahockey.nl/", {"text": load_fixture("web_app.html")}),
        (
            "https://mijn.lisahockey.nl/assets/index-Test123.js",
            {"text": load_fixture("web_app_bundle.js")},
        ),
        ("https://api.example.invalid/api/v1/my/federations", {"json": {"id": "fed-1"}}),
    ):
        mock_lisa.get(url, **kwargs)
    result = await _start(hass)
    assert result["step_id"] == "club"
    options = result["data_schema"].schema[CONF_CLUB_ID].config["options"]
    assert [o["label"] for o in options] == ["HC Voorbeeld · Voorbeeldstad", "MHC Proef · Testdorp"]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CLUB_ID: "club-1"}
    )
    assert result["step_id"] == "login"


async def test_no_club(hass: HomeAssistant, mock_lisa: AiohttpClientMocker) -> None:
    """No hits: say so."""
    mock_lisa.clear_requests()
    mock_lisa.get("https://mijn.lisahockey.nl/", text=load_fixture("web_app.html"))
    mock_lisa.get(
        "https://mijn.lisahockey.nl/assets/index-Test123.js", text=load_fixture("web_app_bundle.js")
    )
    mock_lisa.get("https://api.example.invalid/api/v1/my/federations", json={"id": "fed-1"})
    mock_lisa.get(URL_CLUBS, json={"clubs": []})
    result = await _start(hass, "xyz")
    assert result["errors"] == {"query": "no_clubs_found"}


async def test_cannot_connect(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """LISA unreachable: say so."""
    aioclient_mock.get("https://mijn.lisahockey.nl/", exc=TimeoutError())
    result = await _start(hass)
    assert result["errors"] == {"base": "cannot_connect"}


async def test_wrong_password(hass: HomeAssistant, mock_lisa: AiohttpClientMocker) -> None:
    """A refused login asks again."""
    result = await _start(hass)
    mock_lisa.clear_requests()
    mock_lisa.post(URL_LOGIN, status=HTTPStatus.FORBIDDEN, text="")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], LOGIN)
    assert result["errors"] == {"base": "invalid_auth"}


async def test_already_configured(
    hass: HomeAssistant, mock_lisa: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    """The same member at the same club only once."""
    config_entry.add_to_hass(hass)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], LOGIN)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(
    hass: HomeAssistant, mock_lisa: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    """A new password is stored after logging in with it."""
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "nieuw"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_PASSWORD] == "nieuw"
    assert config_entry.data[CONF_TOKEN] == "token-1"
    await hass.async_block_till_done()  # the entry reloads with the new login


async def test_reauth_other_member(
    hass: HomeAssistant, mock_lisa: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    """Logging in as someone else is refused."""
    config_entry.add_to_hass(hass)
    login = load_fixture("login.json")
    login["club_member"]["id"] = "m-other"
    mock_lisa.clear_requests()
    mock_lisa.post(URL_LOGIN, json=login, status=201)
    result = await config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "nieuw"}
    )
    assert result["reason"] == "wrong_account"
