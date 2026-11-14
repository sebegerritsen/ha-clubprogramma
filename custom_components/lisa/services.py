"""Actions: say whether a family member comes to an activity."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
import voluptuous as vol

from .const import DOMAIN
from .coordinator import LisaConfigEntry
from .models import PRESENCE_ABSENT, PRESENCE_PRESENT, PRESENCE_UNKNOWN

SERVICE_SET_PRESENCE = "set_presence"
ATTR_DEVICE_ID = "device_id"
ATTR_ACTIVITY_ID = "activity_id"
ATTR_STATUS = "status"

SET_PRESENCE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_ACTIVITY_ID): cv.string,
        vol.Required(ATTR_STATUS): vol.In([PRESENCE_PRESENT, PRESENCE_ABSENT, PRESENCE_UNKNOWN]),
    }
)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions."""

    async def set_presence(call: ServiceCall) -> None:
        device = dr.async_get(hass).async_get(call.data[ATTR_DEVICE_ID])
        if device is None:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_member")
        identifier = next((i for d, i in device.identifiers if d == DOMAIN), None)
        for entry_id in device.config_entries:
            entry: LisaConfigEntry | None = hass.config_entries.async_get_entry(entry_id)
            if (
                entry is None
                or entry.domain != DOMAIN
                or entry.state is not ConfigEntryState.LOADED
            ):
                continue
            coordinator = entry.runtime_data
            prefix = f"{coordinator.account_id}_"
            if identifier and identifier.startswith(prefix):
                await coordinator.async_set_presence(
                    identifier.removeprefix(prefix),
                    call.data[ATTR_ACTIVITY_ID],
                    call.data[ATTR_STATUS],
                )
                return
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_member")

    hass.services.async_register(
        DOMAIN, SERVICE_SET_PRESENCE, set_presence, schema=SET_PRESENCE_SCHEMA
    )
