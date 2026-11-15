"""Sensors per family member: next training, next match, meet time, attendance still to give."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .coordinator import LisaConfigEntry, LisaCoordinator, LisaData
from .entity import LisaMemberEntity
from .models import KIND_DUTY, KIND_MATCH, KIND_REFEREE, KIND_TRAINING, Tile

PARALLEL_UPDATES = 0
# Activities listed in the next activity's `upcoming`.
UPCOMING_MAX = 25


def _iso(moment: datetime | None) -> str | None:
    return dt_util.as_local(moment).isoformat() if moment else None


def activity_attributes(tile: Tile | None) -> dict[str, Any]:
    """Return what everyone wants to know about an activity."""
    if tile is None:
        return {}
    return {
        "activity_id": tile.id,
        "kind": tile.kind,
        "title": tile.title,
        "team": tile.team,
        "start": _iso(tile.start),
        "end": _iso(tile.expected_end),
        "location": tile.location,
        "address": tile.address,
        "pitch": tile.pitch,
        "presence": tile.presence,
        "can_change_presence": tile.can_change_presence,
        "present": tile.present,
        "absent": tile.absent,
        "unknown": tile.unknown,
        "role": "staff" if tile.is_staff else "player" if tile.is_player else None,
        "staff_roles": list(tile.roles),
    }


def training_attributes(tile: Tile | None) -> dict[str, Any]:
    """Return the attributes of a training."""
    if tile is None:
        return {}
    return {**activity_attributes(tile), "trainers": list(tile.trainers)}


def match_attributes(tile: Tile | None) -> dict[str, Any]:
    """Return the attributes of a match."""
    if tile is None:
        return {}
    return {
        **activity_attributes(tile),
        "meeting_time": _iso(tile.meeting_time),
        "home_team": tile.home_team,
        "away_team": tile.away_team,
        "opponent": tile.opponent,
        "home_away": None if tile.is_home is None else "home" if tile.is_home else "away",
        "alternate_kit": tile.alternate_kit,
        "home_logo": tile.home_logo,
        "away_logo": tile.away_logo,
        "opponent_logo": tile.opponent_logo,
        "tasks": list(tile.tasks),
        "umpires": list(tile.umpires),
        "status": tile.status,
    }


def any_attributes(tile: Tile | None) -> dict[str, Any]:
    """Return the attributes of an activity of any kind."""
    if tile is None:
        return {}
    if tile.kind == KIND_MATCH:
        return match_attributes(tile)
    if tile.kind == KIND_TRAINING:
        return training_attributes(tile)
    return activity_attributes(tile)


def coming_attributes(data: LisaData, member_id: str, now: datetime) -> dict[str, Any]:
    """Return the next activity, and everything in the coming two weeks (for dashboards)."""
    return {
        **any_attributes(data.next_activity(member_id, now)),
        "upcoming": [
            {
                "activity_id": tile.id,
                "kind": tile.kind,
                "title": tile.title,
                "team": tile.team,
                "start": _iso(tile.start),
                "end": _iso(tile.expected_end),
                "meeting_time": _iso(tile.meeting_time),
                "location": tile.location,
                "pitch": tile.pitch,
                "cancelled": tile.cancelled,
                "presence": tile.presence,
                "can_change_presence": tile.can_change_presence,
                "is_home": tile.is_home,
                "opponent": tile.opponent,
                "role": "staff" if tile.is_staff else "player" if tile.is_player else None,
                "staff_roles": list(tile.roles),
            }
            for tile in data.coming(member_id, now)[:UPCOMING_MAX]
        ],
    }


def todo_attributes(tiles: list[Tile]) -> dict[str, Any]:
    """List the activities that still need an answer."""
    return {
        "activities": [
            {
                "activity_id": tile.id,
                "start": _iso(tile.start),
                "title": tile.title,
                "kind": tile.kind,
                "team": tile.team,
            }
            for tile in tiles
        ]
    }


@dataclass(frozen=True, kw_only=True)
class LisaSensorDescription(SensorEntityDescription):
    """Describes a family member's sensor."""

    value_fn: Callable[[LisaData, str, datetime], StateType | datetime]
    attributes_fn: Callable[[LisaData, str, datetime], dict[str, Any]]


SENSORS: tuple[LisaSensorDescription, ...] = (
    LisaSensorDescription(
        key="next_activity",
        translation_key="next_activity",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d, m, now: (t := d.next_activity(m, now)) and t.start,
        attributes_fn=coming_attributes,
    ),
    LisaSensorDescription(
        key="next_training",
        translation_key="next_training",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d, m, now: (t := d.next_training(m, now)) and t.start,
        attributes_fn=lambda d, m, now: training_attributes(d.next_training(m, now)),
    ),
    LisaSensorDescription(
        key="next_match",
        translation_key="next_match",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d, m, now: (t := d.next_match(m, now)) and t.start,
        attributes_fn=lambda d, m, now: match_attributes(d.next_match(m, now)),
    ),
    LisaSensorDescription(
        key="meeting_time",
        translation_key="meeting_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d, m, now: (t := d.next_match(m, now)) and t.meeting_time,
        attributes_fn=lambda d, m, now: match_attributes(d.next_match(m, now)),
    ),
    LisaSensorDescription(
        key="next_duty",
        translation_key="next_duty",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d, m, now: (t := d.next_of(m, KIND_DUTY, now)) and t.start,
        attributes_fn=lambda d, m, now: activity_attributes(d.next_of(m, KIND_DUTY, now)),
    ),
    LisaSensorDescription(
        key="next_umpiring",
        translation_key="next_umpiring",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d, m, now: (t := d.next_of(m, KIND_REFEREE, now)) and t.start,
        attributes_fn=lambda d, m, now: activity_attributes(d.next_of(m, KIND_REFEREE, now)),
    ),
    LisaSensorDescription(
        key="presence_todo",
        translation_key="presence_todo",
        value_fn=lambda d, m, now: len(d.presence_todo(m, now)),
        attributes_fn=lambda d, m, now: todo_attributes(d.presence_todo(m, now)),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LisaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors of each family member."""
    coordinator = entry.runtime_data
    async_add_entities(
        LisaSensor(coordinator, member_id, description)
        for member_id in coordinator.data.members
        for description in SENSORS
    )


class LisaSensor(LisaMemberEntity, SensorEntity):
    """A sensor of a family member."""

    entity_description: LisaSensorDescription
    _unrecorded_attributes = frozenset(
        {"activities", "staff_roles", "trainers", "tasks", "umpires"}
    )

    def __init__(
        self, coordinator: LisaCoordinator, member_id: str, description: LisaSensorDescription
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, member_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType | datetime:
        """Return the state."""
        return self.entity_description.value_fn(
            self.coordinator.data, self.member_id, dt_util.utcnow()
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the details."""
        return self.entity_description.attributes_fn(
            self.coordinator.data, self.member_id, dt_util.utcnow()
        )
