"""Diagnostics: settings without the login, and the program without names."""

from __future__ import annotations

from collections import Counter
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_BASIC, CONF_MEMBER_ID, CONF_NUMBER, CONF_PASSWORD, CONF_TOKEN
from .coordinator import LisaConfigEntry

TO_REDACT = {CONF_BASIC, CONF_MEMBER_ID, CONF_NUMBER, CONF_PASSWORD, CONF_TOKEN}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: LisaConfigEntry
) -> dict[str, Any]:
    """Return diagnostics: no names, member ids, numbers, passwords or tokens."""
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "last_update_success": coordinator.last_update_success,
        "members": len(data.members) if data else None,
        "tiles": dict(Counter(tile.kind for tile in data.tiles)) if data else None,
        "cancelled": sum(tile.cancelled for tile in data.tiles) if data else None,
        "presence": dict(Counter(tile.presence for tile in data.tiles)) if data else None,
    }
