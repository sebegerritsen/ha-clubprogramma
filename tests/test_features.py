"""Tests for giving attendance, the 'today' sensors and the other sensors."""

from __future__ import annotations

from http import HTTPStatus

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.clubprogramma.const import DOMAIN

from .conftest import API, NOW, calls_to

pytestmark = pytest.mark.usefixtures("tz")

URL_TRAINING_PRESENCE = (
    f"{API}/clubs/club-1/trainings/train-a1/teams/team-1/members/m-alex/presences"
)
URL_MATCH_PRESENCE = f"{API}/clubs/club-1/matches/match-a1/teams/team-1/members/m-alex/presence"
URL_EVENT_PRESENCE = f"{API}/clubs/club-1/team_events/tev-1/event_date/date-1/presence/m-alex"


@pytest.fixture
async def tz(hass: HomeAssistant) -> None:
    """Dutch time."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_sensors(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_lisa: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Next activity, duty and umpiring; match and training today."""
    freezer.move_to(NOW)
    await _setup(hass, config_entry)
    state = hass.states.get("sensor.alex_next_activity")
    assert state.state == "2026-11-14T09:45:00+00:00"
    assert state.attributes["kind"] == "match"
    assert state.attributes["activity_id"] == "match-a1"
    upcoming = state.attributes["upcoming"]
    assert [(a["activity_id"], a["cancelled"]) for a in upcoming] == [
        ("match-a1", False),
        ("train-a1", False),
        ("train-a2", True),
        ("match-a2", False),
    ]
    assert upcoming[0]["meeting_time"] == "2026-11-14T09:30:00+01:00"
    assert upcoming[3]["presence"] == "present"
    assert upcoming[3]["opponent"] == "HC Fictief JO12-1"
    assert upcoming[3]["role"] == "player"
    state = hass.states.get("sensor.sam_next_duty")
    assert state.state == "2026-11-22T09:00:00+00:00"
    assert state.attributes["title"] == "Bardienst"
    assert state.attributes["location"] == "Clubhuis"
    assert hass.states.get("sensor.sam_next_umpiring").state == "unknown"

    state = hass.states.get("binary_sensor.alex_match_today")
    assert state.state == "on"
    assert state.attributes["meeting_time"] == "2026-11-14T09:30:00+01:00"
    assert hass.states.get("binary_sensor.alex_training_today").state == "off"
    assert hass.states.get("binary_sensor.sam_match_today").state == "off"


async def test_presence_selects(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_lisa: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Picking an answer tells LISA, and shows at once."""
    freezer.move_to(NOW)
    await _setup(hass, config_entry)
    state = hass.states.get("select.alex_attendance_next_training")
    assert state.state == "not_given"
    assert state.attributes["options"] == ["not_given", "present", "absent"]
    assert state.attributes["activity_id"] == "train-a1"

    mock_lisa.post(URL_TRAINING_PRESENCE, status=HTTPStatus.OK, text="")
    mock_lisa.post(URL_MATCH_PRESENCE, status=HTTPStatus.CREATED, text="")
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.alex_attendance_next_training", "option": "present"},
        blocking=True,
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.alex_attendance_next_match", "option": "absent"},
        blocking=True,
    )
    assert calls_to(mock_lisa, URL_TRAINING_PRESENCE, "post")[0][2] == {"status": "present"}
    assert calls_to(mock_lisa, URL_MATCH_PRESENCE, "post")[0][2] == {"status": "absent"}
    assert hass.states.get("select.alex_attendance_next_training").state == "present"
    assert hass.states.get("select.alex_attendance_next_match").state == "absent"
    assert hass.states.get("sensor.alex_attendance_to_give").state == "0"


async def test_set_presence_action(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_lisa: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """The action gives attendance for any activity, here a team event."""
    freezer.move_to(NOW)
    await _setup(hass, config_entry)
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, "m-parent_m-alex"), config_entry.entry_id
    )
    mock_lisa.post(URL_EVENT_PRESENCE, status=HTTPStatus.CREATED, text="")
    await hass.services.async_call(
        DOMAIN,
        "set_presence",
        {"device_id": device.id, "activity_id": "date-1", "status": "absent"},
        blocking=True,
    )
    assert calls_to(mock_lisa, URL_EVENT_PRESENCE, "post")[0][2] == {
        "status": "absent",
        "comment": None,
    }

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN,
            "set_presence",
            {"device_id": device.id, "activity_id": "nope", "status": "absent"},
            blocking=True,
        )


async def test_presence_refused(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_lisa: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """When LISA does not take the answer, say so and keep the old one."""
    freezer.move_to(NOW)
    await _setup(hass, config_entry)
    mock_lisa.post(URL_TRAINING_PRESENCE, status=HTTPStatus.BAD_REQUEST, text="")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": "select.alex_attendance_next_training", "option": "present"},
            blocking=True,
        )
    assert hass.states.get("select.alex_attendance_next_training").state == "not_given"
