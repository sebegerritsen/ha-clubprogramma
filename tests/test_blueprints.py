"""Run the blueprints as automations, with a test event in place of the phone notification."""

from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.clubprogramma.const import DOMAIN

from .conftest import API, NOW, calls_to

BLUEPRINTS = Path(__file__).parent.parent / "blueprints" / "automation" / "clubprogramma"
NOTIFY = "- device_id: !input notify_device"
URL_TRAINING_PRESENCE = (
    f"{API}/clubs/club-1/trainings/train-a1/teams/team-1/members/m-alex/presences"
)


@pytest.fixture(autouse=True)
async def tz(hass: HomeAssistant) -> None:
    """Dutch time."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")


def _install(hass: HomeAssistant, tmp_path: Path, name: str) -> None:
    """Copy a blueprint into the config dir, each phone notification replaced by an event."""
    lines = (BLUEPRINTS / name).read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip() == NOTIFY:
            indent = line[: len(line) - len(line.lstrip())]
            assert lines[i + 1].strip() == "domain: mobile_app"
            assert lines[i + 2].strip() == "type: notify"
            out += [f"{indent}- event: lisa_test_notify", f"{indent}  event_data:"]
            i += 3
            while i < len(lines) and (
                not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip()) > len(indent)
            ):
                out.append(f"  {lines[i]}" if lines[i].strip() else lines[i])
                i += 1
            continue
        out.append(line)
        i += 1
    target = tmp_path / "blueprints" / "automation" / "clubprogramma" / name
    target.parent.mkdir(parents=True)
    target.write_text("\n".join(out) + "\n", encoding="utf-8")
    hass.config.config_dir = str(tmp_path)


async def _automation(hass: HomeAssistant, name: str, inputs: dict[str, Any]) -> None:
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "use_blueprint": {
                    "path": f"clubprogramma/{name}",
                    "input": {"notify_device": "phone", **inputs},
                }
            }
        },
    )
    await hass.async_block_till_done()


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_activity_update_notify(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    tmp_path: Path,
    freezer: FrozenDateTimeFactory,
    mock_lisa: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """A cancellation and a new meet time give readable notifications."""
    freezer.move_to(NOW)
    _install(hass, tmp_path, "activity_update_notify.yaml")
    await _automation(
        hass,
        "activity_update_notify.yaml",
        {"update_entity": "event.hcv_activity_update"},
    )
    sent = async_capture_events(hass, "lisa_test_notify")
    hass_storage[f"{DOMAIN}.{config_entry.entry_id}"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"{DOMAIN}.{config_entry.entry_id}",
        "data": {
            "tiles": {
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
    await _setup(hass, config_entry)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert [(e.data["title"], e.data["message"]) for e in sent] == [
        (
            "Afgelast: Training JO12-1 (Alex)",
            "wo 18-11 16:30 · Sportpark Voorbeeld",
        ),
        (
            "Andere verzameltijd: Voorbeeld JO12-1 – HC Fictief JO12-1 (Alex)",
            "Verzamelen 10:30 (was 10:15) · za 21-11 11:00 · Sportpark Voorbeeld",
        ),
    ]


@pytest.mark.parametrize("expected_lingering_timers", [True])  # the automation's time trigger
async def test_presence_buttons(
    hass: HomeAssistant,
    tmp_path: Path,
    freezer: FrozenDateTimeFactory,
    mock_lisa: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """At the set time each open activity is asked about; a tap tells LISA."""
    freezer.move_to(NOW)
    await _setup(hass, config_entry)
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, "m-parent_m-alex"), config_entry.entry_id
    )
    _install(hass, tmp_path, "presence_buttons.yaml")
    await _automation(
        hass, "presence_buttons.yaml", {"member_device": device.id, "time": "09:30:00"}
    )
    sent = async_capture_events(hass, "lisa_test_notify")
    freezer.move_to("2026-11-14T08:30:00+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert [(e.data["title"], e.data["message"]) for e in sent] == [
        ("Alex: MHC Proef JO12-1 – Voorbeeld JO12-1", "za 14-11 10:45 · Kom je?"),
        ("Alex: Training JO12-1", "ma 16-11 16:30 · Kom je?"),
    ]
    actions = sent[1].data["data"]["actions"]
    assert actions[0] == {"action": f"LISA|{device.id}|present|train-a1", "title": "Aanwezig"}

    mock_lisa.post(URL_TRAINING_PRESENCE, status=HTTPStatus.OK, text="")
    hass.bus.async_fire("mobile_app_notification_action", {"action": actions[0]["action"]})
    await hass.async_block_till_done()
    assert calls_to(mock_lisa, URL_TRAINING_PRESENCE, "post")[0][2] == {"status": "present"}
    assert hass.states.get("select.alex_attendance_next_training").state == "present"


async def test_meeting_time_reminder(
    hass: HomeAssistant,
    tmp_path: Path,
    freezer: FrozenDateTimeFactory,
    mock_lisa: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """An hour before the team meets, a reminder with the venue goes out."""
    freezer.move_to("2026-11-14T07:00:00+00:00")
    await _setup(hass, config_entry)
    _install(hass, tmp_path, "meeting_time_reminder.yaml")
    await _automation(
        hass,
        "meeting_time_reminder.yaml",
        {"meet_time_entity": "sensor.alex_meet_time", "lead_time": 60},
    )
    sent = async_capture_events(hass, "lisa_test_notify")
    for minute in ("07:29", "07:30", "07:31"):
        freezer.move_to(f"2026-11-14T{minute}:00+00:00")
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    assert [(e.data["title"], e.data["message"]) for e in sent] == [
        (
            "Alex: verzamelen 09:30",
            "MHC Proef JO12-1 – Voorbeeld JO12-1 · aanvang 10:45 · Sportpark MHC Proef"
            " (Laan 1, 1234AB Ergens)",
        )
    ]
