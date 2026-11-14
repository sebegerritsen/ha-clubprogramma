"""Selects per family member: attendance for the next training and the next match.

Changing one says in LISA whether the member comes; the team sees it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import LisaConfigEntry, LisaCoordinator, LisaData
from .entity import LisaMemberEntity
from .models import PRESENCE_ABSENT, PRESENCE_PRESENT, PRESENCE_UNKNOWN, Tile

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class LisaPresenceDescription(SelectEntityDescription):
    """Describes an attendance select."""

    tile_fn: Callable[[LisaData, str, datetime], Tile | None]


SELECTS = (
    LisaPresenceDescription(
        key="next_training_presence",
        translation_key="next_training_presence",
        tile_fn=lambda d, m, now: d.next_training(m, now),
    ),
    LisaPresenceDescription(
        key="next_match_presence",
        translation_key="next_match_presence",
        tile_fn=lambda d, m, now: d.next_match(m, now),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LisaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the attendance selects."""
    coordinator = entry.runtime_data
    async_add_entities(
        LisaPresenceSelect(coordinator, member_id, description)
        for member_id in coordinator.data.members
        for description in SELECTS
    )


class LisaPresenceSelect(LisaMemberEntity, SelectEntity):
    """Whether a family member comes to their next training or match."""

    entity_description: LisaPresenceDescription

    def __init__(
        self, coordinator: LisaCoordinator, member_id: str, description: LisaPresenceDescription
    ) -> None:
        """Initialize the select."""
        super().__init__(coordinator, member_id, description.key)
        self.entity_description = description
        self._attr_options = [PRESENCE_UNKNOWN, PRESENCE_PRESENT, PRESENCE_ABSENT]

    def _tile(self) -> Tile | None:
        return self.entity_description.tile_fn(
            self.coordinator.data, self.member_id, dt_util.utcnow()
        )

    @property
    def available(self) -> bool:
        """Available when there is a next activity that takes an answer."""
        tile = self._tile()
        return super().available and tile is not None and tile.can_change_presence

    @property
    def current_option(self) -> str | None:
        """Return the member's answer."""
        tile = self._tile()
        return tile.presence if tile and tile.presence in self._attr_options else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return which activity this is about."""
        if (tile := self._tile()) is None:
            return {}
        return {
            "activity_id": tile.id,
            "title": tile.title,
            "start": dt_util.as_local(tile.start).isoformat() if tile.start else None,
            "present": tile.present,
            "absent": tile.absent,
            "unknown": tile.unknown,
        }

    async def async_select_option(self, option: str) -> None:
        """Say in LISA whether the member comes."""
        if (tile := self._tile()) is not None:
            await self.coordinator.async_set_presence(self.member_id, tile.id, option)
