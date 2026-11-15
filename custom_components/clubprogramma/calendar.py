"""Calendars: each family member's activities, and the club agenda."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DEFAULT_DURATION
from .coordinator import LisaConfigEntry, LisaCoordinator
from .entity import LisaAccountEntity, LisaMemberEntity
from .models import KIND_DUTY, KIND_MATCH, KIND_REFEREE, Tile

PARALLEL_UPDATES = 0

# Words in event texts, by Home Assistant's language.
WORDS = {
    "nl": {
        "meet": "Verzamelen",
        "pitch": "Veld",
        "present": "aanwezig",
        "absent": "afwezig",
        "unknown": "onbekend",
        "duty": "Taak",
        "referee": "Fluiten",
        "tasks": "Taken",
        "umpires": "Scheidsrechters",
    },
    "en": {
        "meet": "Meet",
        "pitch": "Pitch",
        "present": "present",
        "absent": "absent",
        "unknown": "unknown",
        "duty": "Duty",
        "referee": "Umpiring",
        "tasks": "Tasks",
        "umpires": "Umpires",
    },
}


def words(hass: HomeAssistant) -> dict[str, str]:
    """Return the event words in Home Assistant's language (Dutch or English)."""
    return WORDS["nl"] if (hass.config.language or "").startswith("nl") else WORDS["en"]


def tile_event(hass: HomeAssistant, tile: Tile) -> CalendarEvent | None:
    """Return the calendar event of an activity; None without a time or when cancelled."""
    if tile.start is None or tile.cancelled:
        return None
    w = words(hass)
    summary = tile.title
    if tile.kind == KIND_MATCH and tile.score_home is not None and tile.score_away is not None:
        summary += f" ({tile.score_home}–{tile.score_away})"
    elif tile.kind == KIND_DUTY:
        summary = f"{w['duty']}: {tile.title}"
    elif tile.kind == KIND_REFEREE:
        summary = f"{w['referee']}: {tile.title}"
    lines = []
    if tile.meeting_time:
        lines.append(f"{w['meet']} {dt_util.as_local(tile.meeting_time).strftime('%H:%M')}")
    if tile.pitch:
        lines.append(
            tile.pitch
            if w["pitch"].lower() in tile.pitch.lower()
            else f"{w['pitch']}: {tile.pitch}"
        )
    if tile.present is not None or tile.absent is not None:
        lines.append(
            f"{tile.present or 0} {w['present']}, {tile.absent or 0} {w['absent']}, "
            f"{tile.unknown or 0} {w['unknown']}"
        )
    if tile.tasks:
        lines.append(f"{w['tasks']}: {', '.join(tile.tasks)}")
    if tile.umpires:
        lines.append(f"{w['umpires']}: {', '.join(tile.umpires)}")
    location = ", ".join(part for part in (tile.location, tile.address) if part)
    start = dt_util.as_local(tile.start)
    end = dt_util.as_local(tile.expected_end or tile.start)
    if end <= start:  # a calendar event needs a duration
        end = start + DEFAULT_DURATION
    return CalendarEvent(
        start=start,
        end=end,
        summary=summary,
        description="\n".join(lines) or None,
        location=location or None,
        uid=f"lisa_{tile.key}",
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LisaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the calendars."""
    coordinator = entry.runtime_data
    entities: list[CalendarEntity] = [LisaAgendaCalendar(coordinator)]
    entities += [
        LisaMemberCalendar(coordinator, member_id) for member_id in coordinator.data.members
    ]
    async_add_entities(entities)


class _LisaCalendar(CalendarEntity):
    """Shared calendar logic."""

    hass: HomeAssistant

    def _tiles(self) -> list[Tile]:
        raise NotImplementedError

    def _events(self) -> list[CalendarEvent]:
        return [event for tile in self._tiles() if (event := tile_event(self.hass, tile))]

    @property
    def event(self) -> CalendarEvent | None:
        """Return the current or next activity."""
        now = dt_util.now()
        return next((event for event in self._events() if event.end > now), None)

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return the activities between two moments."""
        return [e for e in self._events() if e.start < end_date and e.end > start_date]


class LisaMemberCalendar(LisaMemberEntity, _LisaCalendar):
    """A family member's trainings, matches, team events, duties and umpiring."""

    _attr_translation_key = "activities"

    def __init__(self, coordinator: LisaCoordinator, member_id: str) -> None:
        """Initialize the calendar."""
        super().__init__(coordinator, member_id, "calendar")

    def _tiles(self) -> list[Tile]:
        return self.coordinator.data.activities(self.member_id)


class LisaAgendaCalendar(LisaAccountEntity, _LisaCalendar):
    """The club agenda."""

    _attr_translation_key = "agenda"

    def __init__(self, coordinator: LisaCoordinator) -> None:
        """Initialize the calendar."""
        super().__init__(coordinator, "agenda")

    def _tiles(self) -> list[Tile]:
        return self.coordinator.data.agenda()
