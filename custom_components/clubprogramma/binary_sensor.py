"""Binary sensors per family member: training today, match today."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from .coordinator import LisaConfigEntry, LisaCoordinator
from .entity import LisaMemberEntity
from .models import KIND_MATCH, KIND_TRAINING

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class LisaTodayDescription(BinarySensorEntityDescription):
    """Describes a 'today' binary sensor."""

    kind: str


TODAY = (
    LisaTodayDescription(
        key="training_today", translation_key="training_today", kind=KIND_TRAINING
    ),
    LisaTodayDescription(key="match_today", translation_key="match_today", kind=KIND_MATCH),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LisaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        LisaToday(coordinator, member_id, description)
        for member_id in coordinator.data.members
        for description in TODAY
    )


class LisaToday(LisaMemberEntity, BinarySensorEntity):
    """On all day when the member has a training (or match) today that is not cancelled."""

    entity_description: LisaTodayDescription

    def __init__(
        self, coordinator: LisaCoordinator, member_id: str, description: LisaTodayDescription
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, member_id, description.key)
        self.entity_description = description

    async def async_added_to_hass(self) -> None:
        """Also update just after midnight."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_change(self.hass, self._new_day, hour=0, minute=0, second=1)
        )

    @callback
    def _new_day(self, _now: datetime) -> None:
        self.async_write_ha_state()

    def _today(self) -> list:
        return self.coordinator.data.on_day(
            self.member_id, self.entity_description.kind, dt_util.now().date()
        )

    @property
    def is_on(self) -> bool:
        """Return whether there is one today."""
        return bool(self._today())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return today's first one."""
        if not (today := self._today()):
            return {}
        tile = today[0]
        return {
            "start": dt_util.as_local(tile.start).isoformat() if tile.start else None,
            "meeting_time": dt_util.as_local(tile.meeting_time).isoformat()
            if tile.meeting_time
            else None,
            "title": tile.title,
            "location": tile.location,
        }
