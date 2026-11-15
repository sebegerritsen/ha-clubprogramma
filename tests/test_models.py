"""Tests for parsing program tiles leniently."""

from __future__ import annotations

from datetime import UTC, datetime

from custom_components.clubprogramma.models import KIND_TEAM_EVENT, Club, Tile


def test_team_event_and_duty() -> None:
    """Kinds without a dedicated layout still become activities with a title and time."""
    tile = Tile.from_api(
        {
            "type": "teamEvent",
            "teamEvent": {"id": "e1", "title": "Teamuitje", "starts_at": "2026-11-20T18:00:00Z"},
            "club_member_id": "m1",
            "club_member_first_name": "Alex",
        }
    )
    assert tile is not None
    assert tile.kind == KIND_TEAM_EVENT
    assert tile.title == "Teamuitje"
    assert tile.expected_end == datetime(2026, 11, 20, 19, 0, tzinfo=UTC)
    duty = Tile.from_api({"type": "duty", "duty": {"id": "d1", "name": "Bardienst"}, "date": "x"})
    assert duty is not None
    assert duty.title == "Bardienst"
    assert duty.start is None


def test_lenient() -> None:
    """Missing or odd fields give None, not errors."""
    assert Tile.from_api({"type": "match"}) is None
    assert Tile.from_api({"match": {"id": "x"}}) is None
    tile = Tile.from_api(
        {"type": "match", "match": {"id": "m", "result": "not json", "status": "Cancelled"}}
    )
    assert tile is not None
    assert tile.cancelled is True
    assert tile.score_home is None
    assert tile.title == "? – ?"
    assert Club.from_api({"name": "no id"}) is None
