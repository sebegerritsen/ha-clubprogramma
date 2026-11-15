"""Tests for setting up a login: entities, change alerts, logging in again."""

from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.json import json_bytes
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.clubprogramma.const import CONF_BASIC, DOMAIN, UPDATE_INTERVAL
from custom_components.clubprogramma.diagnostics import async_get_config_entry_diagnostics

from .conftest import BASIC, NOW, URL_LOGIN, URL_PROGRAM, load_fixture

pytestmark = pytest.mark.usefixtures("dutch")


@pytest.fixture
async def dutch(hass: HomeAssistant) -> None:
    """Dutch time; entity names stay English so the ids are predictable."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_entities(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_lisa: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Each family member gets a calendar and sensors; the club agenda its own calendar."""
    freezer.move_to(NOW)
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    state = hass.states.get("sensor.alex_next_match")
    assert state.state == "2026-11-14T09:45:00+00:00"
    assert state.attributes["meeting_time"] == "2026-11-14T09:30:00+01:00"
    assert state.attributes["home_away"] == "away"
    assert state.attributes["opponent"] == "MHC Proef JO12-1"
    assert state.attributes["alternate_kit"] is True
    assert state.attributes["presence"] == "unknown"
    assert state.attributes["present"] == 10
    assert hass.states.get("sensor.alex_meet_time").state == "2026-11-14T08:30:00+00:00"

    # The cancelled training on Wednesday is skipped by the next-training sensor.
    state = hass.states.get("sensor.alex_next_training")
    assert state.state == "2026-11-16T15:30:00+00:00"
    assert state.attributes["pitch"] == "Veld 3 (Kunstgras)"
    assert state.attributes["address"] == "Voorbeeldlaan 1, 1234AB Voorbeeldstad"
    assert state.attributes["trainers"] == ["Trainer Een"]

    state = hass.states.get("sensor.alex_attendance_to_give")
    assert state.state == "2"
    assert [a["title"] for a in state.attributes["activities"]] == [
        "MHC Proef JO12-1 – Voorbeeld JO12-1",
        "Training JO12-1",
    ]

    state = hass.states.get("sensor.sam_next_match")
    assert state.attributes["role"] == "staff"
    assert state.attributes["tasks"] == ["Rijden"]
    assert hass.states.get("sensor.sam_attendance_to_give").state == "0"
    assert hass.states.get("sensor.sam_next_training").attributes["staff_roles"] == ["Manager"]

    assert hass.states.get("calendar.hcv_club_agenda").attributes["message"] == "Clubdag"
    assert hass.states.get("calendar.alex_activities").attributes["message"] == (
        "MHC Proef JO12-1 – Voorbeeld JO12-1"
    )


async def test_calendar_events(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_lisa: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """The calendar has the member's activities without cancelled ones, texts in Dutch."""
    freezer.move_to(NOW)
    hass.config.language = "nl"
    await _setup(hass, config_entry)
    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": "calendar.alex_activiteiten",
            "start_date_time": "2026-11-14T00:00:00",
            "duration": {"days": 30},
        },
        blocking=True,
        return_response=True,
    )
    events = response["calendar.alex_activiteiten"]["events"]
    assert [e["summary"] for e in events] == [
        "MHC Proef JO12-1 – Voorbeeld JO12-1",
        "Training JO12-1",
        "Voorbeeld JO12-1 – HC Fictief JO12-1",
        "Training JO12-1",
        "Teamuitje",
    ]
    assert events[0]["end"] == "2026-11-14T12:15:00+01:00"
    assert events[0]["description"].splitlines() == [
        "Verzamelen 09:30",
        "Veld 1",
        "10 aanwezig, 1 afwezig, 3 onbekend",
    ]
    assert events[0]["location"] == "Sportpark MHC Proef, Laan 1, 1234AB Ergens"


def _fired(hass: HomeAssistant) -> list[dict[str, Any]]:
    fired: list[dict[str, Any]] = []

    @callback
    def listener(event: Event) -> None:
        new = event.data["new_state"]
        ours = event.data["entity_id"] == "event.hcv_activity_update"
        if ours and new and new.state not in ("unknown", "unavailable"):
            fired.append(dict(new.attributes))

    hass.bus.async_listen(EVENT_STATE_CHANGED, listener)
    return fired


async def test_changes(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    mock_lisa: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """What changed since the last look fires once: cancelled, back on, moved, new meet time."""
    freezer.move_to(NOW)
    hass_storage[f"{DOMAIN}.{config_entry.entry_id}"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"{DOMAIN}.{config_entry.entry_id}",
        "data": {
            "tiles": {
                "training:train-a1:m-alex": {
                    "start": "2026-11-16T16:30:00+00:00",
                    "cancelled": False,
                    "meeting_time": None,
                },
                "training:train-s1:m-sam": {
                    "start": "2026-11-17T16:00:00+00:00",
                    "cancelled": True,
                    "meeting_time": None,
                },
                "training:train-a2:m-alex": {
                    "start": "2026-11-18T15:30:00+00:00",
                    "cancelled": False,
                    "meeting_time": None,
                },
                "match:match-a2:m-alex": {
                    "start": "2026-11-21T10:00:00+00:00",
                    "cancelled": False,
                    "meeting_time": "2026-11-21T09:15:00+00:00",
                },
            },
            "members": {},
        },
    }
    fired = _fired(hass)
    await _setup(hass, config_entry)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert [(e["event_type"], e["member"], e["title"]) for e in fired] == [
        ("rescheduled", "Alex", "Training JO12-1"),
        ("reinstated", "Sam", "Training MO10-2"),
        ("cancelled", "Alex", "Training JO12-1"),
        ("meeting_time_changed", "Alex", "Voorbeeld JO12-1 – HC Fictief JO12-1"),
    ]
    assert fired[0]["previous_start"] == "2026-11-16T17:30:00+01:00"
    assert fired[0]["start"] == "2026-11-16T16:30:00+01:00"
    assert fired[3]["previous_meeting_time"] == "2026-11-21T10:15:00+01:00"
    assert fired[3]["meeting_time"] == "2026-11-21T10:30:00+01:00"

    # Stored as they are now: the next update reports nothing.
    fired.clear()
    freezer.tick(UPDATE_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert fired == []
    members = hass_storage[f"{DOMAIN}.{config_entry.entry_id}"]["data"]["members"]
    assert {m["first_name"] for m in members.values()} == {"Alex", "Sam"}


async def test_refused_login_asks_again(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_lisa: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """When LISA refuses the stored password, Home Assistant asks for it."""
    freezer.move_to(NOW)
    mock_lisa.clear_requests()
    mock_lisa.get("https://mijn.lisahockey.nl/", text=load_fixture("web_app.html"))
    mock_lisa.get(
        "https://mijn.lisahockey.nl/assets/index-Test123.js", text=load_fixture("web_app_bundle.js")
    )
    mock_lisa.get(URL_PROGRAM, status=HTTPStatus.UNAUTHORIZED, text="")
    mock_lisa.post(URL_LOGIN, status=HTTPStatus.FORBIDDEN, text="")
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]


async def test_public_user_changed(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_lisa: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """When the web app's public user changed, it is read again and stored."""
    freezer.move_to(NOW)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=config_entry.title,
        unique_id=config_entry.unique_id,
        data={**config_entry.data, CONF_BASIC: "Basic b2xkOm9sZA=="},
    )
    calls = 0

    async def respond(method, url, data):
        nonlocal calls
        calls += 1
        if calls == 1:
            return AiohttpClientMockResponse("get", url, status=HTTPStatus.UNAUTHORIZED, text="")
        return AiohttpClientMockResponse("get", url, json=load_fixture("program.json"))

    mock_lisa.clear_requests()
    mock_lisa.get("https://mijn.lisahockey.nl/", text=load_fixture("web_app.html"))
    mock_lisa.get(
        "https://mijn.lisahockey.nl/assets/index-Test123.js", text=load_fixture("web_app_bundle.js")
    )
    mock_lisa.get(URL_PROGRAM, side_effect=respond)
    mock_lisa.post(URL_LOGIN, status=HTTPStatus.UNAUTHORIZED, text="")
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.data[CONF_BASIC] == BASIC


async def test_new_family_member(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_lisa: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """A family member who shows up later gets their own device."""
    freezer.move_to(NOW)
    await _setup(hass, config_entry)
    assert hass.states.get("sensor.kim_next_training") is None

    program = load_fixture("program.json")
    extra = {**program["tiles"][3]}
    extra["club_member_id"], extra["club_member_first_name"] = "m-kim", "Kim"
    extra["training"] = {**extra["training"], "id": "train-k1"}
    program["tiles"].append(extra)
    mock_lisa.clear_requests()
    mock_lisa.get(URL_PROGRAM, json=program)
    freezer.tick(UPDATE_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.kim_next_training").state == "2026-11-16T15:30:00+00:00"


async def test_diagnostics_without_names(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_lisa: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Diagnostics count things and leave out names, numbers and secrets."""
    freezer.move_to(NOW)
    await _setup(hass, config_entry)
    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)
    text = json_bytes(diagnostics).decode()
    for secret in ("Alex", "Sam", "Robin", "12345", "geheim", "token-1", BASIC):
        assert secret not in text
    assert diagnostics["tiles"] == {
        "match": 3,
        "agenda": 1,
        "training": 4,
        "duty": 1,
        "team_event": 1,
    }
    assert diagnostics["cancelled"] == 1


async def test_unload(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_lisa: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """A login can be unloaded."""
    freezer.move_to(NOW)
    await _setup(hass, config_entry)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_connection_error_retries(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """LISA unreachable at start: set up again later."""
    freezer.move_to(NOW)
    aioclient_mock.get(URL_PROGRAM, exc=TimeoutError())
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    freezer.tick(timedelta(minutes=1))
