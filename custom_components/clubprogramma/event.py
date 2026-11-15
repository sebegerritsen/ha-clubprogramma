"""Event entity: an activity was cancelled, is back on, moved, or got a new meet time."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from .coordinator import ChangeType, LisaConfigEntry, LisaCoordinator, LisaData, TileChange
from .entity import LisaAccountEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LisaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the change event entity."""
    async_add_entities([LisaActivityUpdate(entry.runtime_data)])


def _iso(value: datetime | str | None) -> str | None:
    if isinstance(value, str):
        value = dt_util.parse_datetime(value)
    return dt_util.as_local(value).isoformat() if value else None


class LisaActivityUpdate(LisaAccountEntity, EventEntity):
    """Fires when a family member's activity is cancelled, back on, moved or re-timed."""

    _attr_translation_key = "activity_update"

    def __init__(self, coordinator: LisaCoordinator) -> None:
        """Initialize the event entity."""
        super().__init__(coordinator, "activity_update")
        self._attr_event_types = [change.value for change in ChangeType]
        self._seen: LisaData | None = None
        self._pending: list[TileChange] = []
        self._ready = False

    async def async_added_to_hass(self) -> None:
        """Report what the first update found, once added and Home Assistant has started."""
        await super().async_added_to_hass()
        self._collect()
        self.async_on_remove(async_call_later(self.hass, 0, self._async_added))

    @callback
    def _async_added(self, _now: datetime) -> None:
        self.async_on_remove(async_at_started(self.hass, self._async_ready))

    @callback
    def _async_ready(self, _hass: HomeAssistant) -> None:
        self._ready = True
        self._fire()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._collect()
        self._fire()
        super()._handle_coordinator_update()

    @callback
    def _collect(self) -> None:
        data = self.coordinator.data
        if data is None or data is self._seen:
            return
        self._seen = data
        self._pending.extend(data.changes)

    @callback
    def _fire(self) -> None:
        if not self._ready:
            return
        while self._pending:
            change = self._pending.pop(0)
            self._trigger_event(change.type.value, self._attributes(change))
            self.async_write_ha_state()

    def _attributes(self, change: TileChange) -> dict[str, Any]:
        tile = change.tile
        member = self.coordinator.data.members.get(tile.member_id or "")
        return {
            "member": member.first_name if member else tile.member_first_name,
            "kind": tile.kind,
            "title": tile.title,
            "team": tile.team,
            "start": _iso(tile.start),
            "previous_start": _iso(change.previous_start),
            "meeting_time": _iso(tile.meeting_time),
            "previous_meeting_time": _iso(change.previous_meeting_time),
            "location": tile.location,
            "pitch": tile.pitch,
        }
