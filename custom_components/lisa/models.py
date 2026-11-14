"""Data models for LISA's member API, parsed leniently: a missing field gives None."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import re
from typing import Any

from .const import DEFAULT_DURATION, MATCH_DURATION

KIND_TRAINING = "training"
KIND_MATCH = "match"
KIND_AGENDA = "agenda"
KIND_DUTY = "duty"
KIND_REFEREE = "referee"
KIND_TEAM_EVENT = "team_event"  # LISA says "teamEvent"
KIND_BOOKING = "booking"

PRESENCE_UNKNOWN = "unknown"
PRESENCE_PRESENT = "present"
PRESENCE_ABSENT = "absent"


def _str(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text or None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return None


def _bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def _first(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        if (value := _str(data.get(key))) is not None:
            return value
    return None


def _address(location: dict[str, Any]) -> str | None:
    address = _dict(location.get("address"))
    if not address:
        return _str(location.get("address"))
    street = " ".join(
        part
        for part in (
            _str(address.get("street")),
            _str(address.get("house_number")),
            _str(address.get("house_number_extension")),
        )
        if part
    )
    place = " ".join(
        part for part in (_str(address.get("zip_code")), _str(address.get("city"))) if part
    )
    return ", ".join(part for part in (street, place) if part) or None


def _names(items: list[Any]) -> tuple[str, ...]:
    names = []
    for item in items:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            name = _first(
                item,
                "name",
                "full_name",
                "club_member_full_name",
                "title",
                "task_name",
                "role_name",
            )
            if name:
                names.append(name)
    return tuple(names)


@dataclass(frozen=True, slots=True)
class Club:
    """A club, from the federation's club search."""

    id: str
    name: str
    short_name: str | None
    city: str | None
    federation_code: str | None

    @classmethod
    def from_api(cls, data: Any) -> Club | None:
        """Parse a club; None without an id."""
        data = _dict(_dict(data).get("club") or data)
        if (club_id := _str(data.get("id"))) is None:
            return None
        return cls(
            id=club_id,
            name=_str(data.get("name")) or club_id,
            short_name=_str(data.get("short_name")),
            city=_str(data.get("city")),
            federation_code=_str(data.get("federation_code")),
        )


@dataclass(frozen=True, slots=True)
class Member:
    """A member whose activities are in the program (the account holder or family)."""

    id: str
    first_name: str
    full_name: str | None


@dataclass(frozen=True, slots=True)
class Tile:
    """One item of a member's program: a training, match, team event, duty, …"""

    kind: str
    id: str
    member_id: str | None
    member_first_name: str | None
    member_full_name: str | None
    relation: str | None
    team_id: str | None
    team: str | None
    title: str
    start: datetime | None
    end: datetime | None
    location: str | None
    address: str | None
    pitch: str | None
    cancelled: bool
    status: str | None
    presence: str | None
    can_change_presence: bool
    present: int | None
    absent: int | None
    unknown: int | None
    is_player: bool | None
    is_staff: bool | None
    roles: tuple[str, ...]
    meeting_time: datetime | None = None
    is_home: bool | None = None
    opponent: str | None = None
    home_team: str | None = None
    away_team: str | None = None
    score_home: int | None = None
    score_away: int | None = None
    alternate_kit: bool | None = None
    tasks: tuple[str, ...] = ()
    umpires: tuple[str, ...] = ()
    trainers: tuple[str, ...] = ()
    team_event_id: str | None = None
    home_logo: str | None = None
    away_logo: str | None = None
    opponent_logo: str | None = None

    @property
    def key(self) -> str:
        """Return what identifies this item for this member."""
        return f"{self.kind}:{self.id}:{self.member_id}"

    @property
    def expected_end(self) -> datetime | None:
        """Return the end, or an estimate when LISA gives none."""
        if self.end is not None or self.start is None:
            return self.end
        return self.start + (MATCH_DURATION if self.kind == KIND_MATCH else DEFAULT_DURATION)

    @classmethod
    def from_api(cls, data: Any) -> Tile | None:
        """Parse a program tile; None if it has no type or id."""
        data = _dict(data)
        raw_kind = _str(data.get("type"))
        if raw_kind is None:
            return None
        body = _dict(data.get(raw_kind))
        kind = re.sub(r"(?<!^)(?=[A-Z])", "_", raw_kind).lower()  # teamEvent -> team_event
        tile_id = _first(body, "id", "training_id", "team_event_id")
        if tile_id is None:
            return None
        presence = _dict(body.get("presence"))
        reactions = _dict(presence.get("reactions"))
        location = _dict(body.get("location"))
        pitch = _dict(body.get("pitch"))
        pitch_name = _str(pitch.get("name"))
        if pitch_name and _str(pitch.get("type")):
            pitch_name = f"{pitch_name} ({pitch['type']})"
        status = _str(body.get("status"))
        cancelled = _bool(body.get("cancelled")) or bool(status and "cancel" in status.lower())
        team = _first(body, "team_abbreviation", "team_name", "team")
        common: dict[str, Any] = {
            "kind": kind,
            "id": tile_id,
            "member_id": _str(data.get("club_member_id")),
            "member_first_name": _str(data.get("club_member_first_name")),
            "member_full_name": _str(data.get("club_member_full_name")),
            "relation": _str(data.get("relation_type")),
            "team_id": _str(data.get("team_id")) or _str(body.get("team_id")),
            "team": team,
            "start": _datetime(body.get("starts_at")) or _datetime(data.get("date")),
            "end": _datetime(body.get("ends_at")),
            "location": _first(location, "name") or _str(body.get("location")),
            "address": _address(location),
            "pitch": pitch_name,
            "cancelled": cancelled,
            "status": status,
            "presence": _str(presence.get("status")),
            "can_change_presence": bool(_bool(presence.get("show_presence_toggle"))),
            "present": _int(reactions.get("present")),
            "absent": _int(reactions.get("absent")),
            "unknown": _int(reactions.get("unknown")),
            "is_player": _bool(body.get("is_member_a_player_in_tile")),
            "is_staff": _bool(body.get("is_member_a_staff_in_tile")),
            "roles": _names(_list(body.get("person_staff_roles"))),
        }
        if kind == KIND_MATCH:
            home = _first(body, "home_team_name", "home_team_short")
            away = _first(body, "away_team_name", "away_team_short")
            score = _score(body.get("result"))
            return cls(
                **common,
                title=f"{home or '?'} – {away or '?'}",
                meeting_time=_datetime(body.get("meeting_time")),
                is_home=_bool(body.get("is_home")),
                opponent=" ".join(
                    part
                    for part in (
                        _str(body.get("opponent_club_name")),
                        _str(body.get("opponent_team")),
                    )
                    if part
                )
                or None,
                home_team=home,
                away_team=away,
                score_home=score[0],
                score_away=score[1],
                alternate_kit=_bool(body.get("alternate_kit")),
                home_logo=_str(body.get("home_club_logo")),
                away_logo=_str(body.get("away_club_logo")),
                opponent_logo=_str(body.get("opponent_club_logo")),
                tasks=_names(_list(body.get("tasks"))),
                umpires=_names(_list(body.get("match_umpires"))),
            )
        if kind == KIND_TRAINING:
            return cls(
                **common,
                title=f"Training {team}" if team else "Training",
                trainers=_names(_list(body.get("trainers"))),
            )
        title = _first(body, "title", "name", "description", "task_name") or kind
        return cls(**common, title=title, team_event_id=_str(body.get("team_event_id")))


def _score(value: Any) -> tuple[int | None, int | None]:
    """Read a match result, which LISA sends as a JSON string."""
    if isinstance(value, str) and value.strip().startswith("{"):
        try:
            value = json.loads(value)
        except ValueError:
            return None, None
    data = _dict(value)
    return _int(data.get("homescore")), _int(data.get("awayscore"))
