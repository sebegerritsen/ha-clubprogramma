"""Coordinator: fetches the member's and family's program from LISA."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    LisaAuthError,
    LisaClient,
    LisaConnectionError,
    LisaError,
    WebAppConfig,
    fetch_web_app_config,
)
from .const import (
    CONF_API_URL,
    CONF_BASIC,
    CONF_CLUB_ID,
    CONF_FEDERATION_ID,
    CONF_MEMBER_ID,
    CONF_SPORT,
    DOMAIN,
    LOGGER,
    PRESENCE_AHEAD,
    PROGRAM_AHEAD,
    PROGRAM_BEHIND,
    STORAGE_VERSION,
    UPDATE_INTERVAL,
    WEB_HOSTS,
)
from .models import KIND_AGENDA, KIND_MATCH, KIND_TRAINING, PRESENCE_UNKNOWN, Member, Tile

type LisaConfigEntry = ConfigEntry[LisaCoordinator]


class ChangeType(StrEnum):
    """What happened to an activity."""

    CANCELLED = "cancelled"
    REINSTATED = "reinstated"
    RESCHEDULED = "rescheduled"
    MEETING_TIME_CHANGED = "meeting_time_changed"


@dataclass(frozen=True, slots=True)
class TileChange:
    """A change to an activity, with what it was before."""

    type: ChangeType
    tile: Tile
    previous_start: str | None
    previous_meeting_time: str | None


@dataclass(slots=True)
class LisaData:
    """The program of the member and their family."""

    tiles: list[Tile]
    members: dict[str, Member]
    changes: list[TileChange] = field(default_factory=list)

    def activities(self, member_id: str) -> list[Tile]:
        """Return a member's own activities (not the club agenda), by start."""
        return [t for t in self.tiles if t.member_id == member_id and t.kind != KIND_AGENDA]

    def agenda(self) -> list[Tile]:
        """Return the club agenda, each item once."""
        seen: set[str] = set()
        items = []
        for tile in self.tiles:
            if tile.kind == KIND_AGENDA and tile.id not in seen:
                seen.add(tile.id)
                items.append(tile)
        return items

    def upcoming(self, member_id: str, kind: str, now: datetime) -> list[Tile]:
        """Return a member's coming activities of one kind, not cancelled, current one first."""
        return [
            tile
            for tile in self.activities(member_id)
            if tile.kind == kind
            and not tile.cancelled
            and tile.start is not None
            and (tile.expected_end or tile.start) > now
        ]

    def next_activity(self, member_id: str, now: datetime) -> Tile | None:
        """Return the member's current or next activity of any kind (not cancelled)."""
        return next(
            (
                tile
                for tile in self.activities(member_id)
                if not tile.cancelled
                and tile.start is not None
                and (tile.expected_end or tile.start) > now
            ),
            None,
        )

    def next_of(self, member_id: str, kind: str, now: datetime) -> Tile | None:
        """Return the member's current or next activity of one kind."""
        return next(iter(self.upcoming(member_id, kind, now)), None)

    def on_day(self, member_id: str, kind: str, day: date) -> list[Tile]:
        """Return a member's activities of one kind on a day (local time), not cancelled."""
        return [
            tile
            for tile in self.activities(member_id)
            if tile.kind == kind
            and not tile.cancelled
            and tile.start is not None
            and dt_util.as_local(tile.start).date() == day
        ]

    def find(self, member_id: str, activity_id: str) -> Tile | None:
        """Return a member's activity by its id."""
        return next(
            (t for t in self.activities(member_id) if t.id == activity_id),
            None,
        )

    def next_training(self, member_id: str, now: datetime) -> Tile | None:
        """Return the member's next training."""
        return next(iter(self.upcoming(member_id, KIND_TRAINING, now)), None)

    def next_match(self, member_id: str, now: datetime) -> Tile | None:
        """Return the member's next match."""
        return next(iter(self.upcoming(member_id, KIND_MATCH, now)), None)

    def presence_todo(self, member_id: str, now: datetime) -> list[Tile]:
        """Return coming activities where the member can still say whether they come."""
        until = now + PRESENCE_AHEAD
        return [
            tile
            for tile in self.activities(member_id)
            if tile.can_change_presence
            and tile.presence == PRESENCE_UNKNOWN
            and not tile.cancelled
            and tile.start is not None
            and now < tile.start <= until
        ]


def _state(tile: Tile) -> dict[str, Any]:
    return {
        "start": tile.start.isoformat() if tile.start else None,
        "cancelled": tile.cancelled,
        "meeting_time": tile.meeting_time.isoformat() if tile.meeting_time else None,
    }


def detect_changes(
    previous: dict[str, dict[str, Any]], tiles: list[Tile], now: datetime
) -> list[TileChange]:
    """Return what changed about coming activities since they were last seen."""
    changes = []
    for tile in tiles:
        before = previous.get(tile.key)
        if before is None or tile.kind == KIND_AGENDA or tile.start is None or tile.start < now:
            continue
        current = _state(tile)

        def change(kind: ChangeType, tile: Tile = tile, before: dict[str, Any] = before) -> None:
            changes.append(TileChange(kind, tile, before.get("start"), before.get("meeting_time")))

        if current["cancelled"] and not before.get("cancelled"):
            change(ChangeType.CANCELLED)
            continue
        if current["cancelled"]:
            continue
        if before.get("cancelled"):
            change(ChangeType.REINSTATED)
        elif before.get("start") and current["start"] != before.get("start"):
            change(ChangeType.RESCHEDULED)
        if before.get("meeting_time") and current["meeting_time"] != before.get("meeting_time"):
            change(ChangeType.MEETING_TIME_CHANGED)
    return changes


class LisaCoordinator(DataUpdateCoordinator[LisaData]):
    """Fetches the program of the member and their family."""

    config_entry: LisaConfigEntry

    def __init__(self, hass: HomeAssistant, entry: LisaConfigEntry, client: LisaClient) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self.account_id: str = entry.data[CONF_MEMBER_ID]
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._states: dict[str, dict[str, Any]] = {}
        self._members: dict[str, Member] = {}

    async def _async_setup(self) -> None:
        """Load the activities and family members as they were last seen."""
        stored = await self._store.async_load() or {}
        if isinstance(stored.get("tiles"), dict):
            self._states = stored["tiles"]
        for member_id, item in (stored.get("members") or {}).items():
            if isinstance(item, dict) and item.get("first_name"):
                self._members[member_id] = Member(
                    member_id, item["first_name"], item.get("full_name")
                )

    async def _async_update_data(self) -> LisaData:
        try:
            raw = await self._fetch()
        except LisaAuthError as err:
            # The web app's public user may have changed: read it again, then try once more.
            try:
                changed = await self._refresh_web_app_config()
                raw = await self._fetch() if changed else None
            except LisaAuthError:
                raw = None
            except LisaError as other:
                raise UpdateFailed(
                    translation_domain=DOMAIN,
                    translation_key="cannot_connect",
                    translation_placeholders={"error": str(other)},
                ) from other
            if raw is None:
                raise ConfigEntryAuthFailed(
                    translation_domain=DOMAIN, translation_key="auth_failed"
                ) from err
        except LisaConnectionError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": str(err)},
            ) from err
        except LisaError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="unexpected_response",
                translation_placeholders={"error": str(err)},
            ) from err

        now = dt_util.utcnow()
        tiles = sorted(
            (tile for item in raw if (tile := Tile.from_api(item)) is not None),
            key=lambda t: (t.start is None, t.start or now),
        )
        members = dict(self._members)
        for tile in tiles:
            if tile.kind != KIND_AGENDA and tile.member_id and tile.member_first_name:
                members[tile.member_id] = Member(
                    tile.member_id, tile.member_first_name, tile.member_full_name
                )
        changes = detect_changes(self._states, tiles, now)
        await self._remember(tiles, members, now)
        return LisaData(tiles=tiles, members=members, changes=changes)

    async def async_set_presence(self, member_id: str, activity_id: str, status: str) -> None:
        """Say whether a member comes, in LISA, and show it at once."""
        if self.data is None or (tile := self.data.find(member_id, activity_id)) is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="activity_not_found"
            )
        if not tile.can_change_presence:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="presence_not_allowed"
            )
        try:
            await self.client.set_presence(self.config_entry.data[CONF_CLUB_ID], tile, status)
        except LisaError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="presence_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        tiles = [replace(t, presence=status) if t is tile else t for t in self.data.tiles]
        self.async_set_updated_data(LisaData(tiles=tiles, members=self.data.members, changes=[]))

    async def _fetch(self) -> list[dict[str, Any]]:
        today = dt_util.now().date()
        return await self.client.get_program(
            self.config_entry.data[CONF_FEDERATION_ID],
            today - PROGRAM_BEHIND,
            today + PROGRAM_AHEAD,
        )

    async def _refresh_web_app_config(self) -> bool:
        """Read the web app's API settings again; return whether they changed."""
        data = self.config_entry.data
        config = await fetch_web_app_config(
            async_get_clientsession(self.hass), WEB_HOSTS[data[CONF_SPORT]], data[CONF_SPORT]
        )
        if config == self.client.config:
            return False
        LOGGER.debug("The LISA web app's API settings changed")
        self.client.config = WebAppConfig(api_url=config.api_url, basic=config.basic)
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data={**data, CONF_API_URL: config.api_url, CONF_BASIC: config.basic},
        )
        return True

    async def _remember(self, tiles: list[Tile], members: dict[str, Member], now: datetime) -> None:
        """Keep coming activities and the family members, and store them if they changed."""
        states = {
            key: value
            for key, value in self._states.items()
            if _not_before(value.get("start"), now)
        }
        for tile in tiles:
            if tile.kind != KIND_AGENDA and tile.start is not None and tile.start >= now:
                states[tile.key] = _state(tile)
        if states == self._states and members == self._members:
            return
        self._states, self._members = states, members
        await self._store.async_save(
            {
                "tiles": states,
                "members": {
                    m.id: {"first_name": m.first_name, "full_name": m.full_name}
                    for m in members.values()
                },
            }
        )


def _not_before(value: Any, moment: datetime) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return datetime.fromisoformat(value) >= moment
    except ValueError:
        return False
