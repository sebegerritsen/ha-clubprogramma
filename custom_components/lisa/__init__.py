"""The LISA integration: trainings, matches and attendance of a member and their family."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .api import Credentials, LisaClient, WebAppConfig
from .const import (
    CONF_API_URL,
    CONF_BASIC,
    CONF_CLUB_ID,
    CONF_CLUB_NAME,
    CONF_CLUB_SHORT,
    CONF_LOGIN_TYPE,
    CONF_MEMBER_ID,
    CONF_NUMBER,
    CONF_PASSWORD,
    CONF_TOKEN,
    DOMAIN,
    LOGIN_FEDERATION_NUMBER,
    STORAGE_VERSION,
)
from .coordinator import LisaConfigEntry, LisaCoordinator
from .services import async_setup_services

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CALENDAR,
    Platform.EVENT,
    Platform.SELECT,
    Platform.SENSOR,
]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions."""
    async_setup_services(hass)
    return True


def credentials_from(data: dict) -> Credentials:
    """Return the login stored in a config entry."""
    return Credentials(
        club_id=data[CONF_CLUB_ID],
        number=data[CONF_NUMBER],
        password=data[CONF_PASSWORD],
        federation_number=data.get(CONF_LOGIN_TYPE) == LOGIN_FEDERATION_NUMBER,
    )


async def async_setup_entry(hass: HomeAssistant, entry: LisaConfigEntry) -> bool:
    """Set up a LISA login from a config entry."""

    @callback
    def _store_token(token: str) -> None:
        hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_TOKEN: token})

    client = LisaClient(
        async_get_clientsession(hass),
        WebAppConfig(api_url=entry.data[CONF_API_URL], basic=entry.data[CONF_BASIC]),
        token=entry.data.get(CONF_TOKEN),
        credentials=credentials_from(dict(entry.data)),
        on_token_change=_store_token,
    )
    coordinator = LisaCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    # The account's device first: the family members' devices hang under it.
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.data[CONF_MEMBER_ID])},
        name=entry.data.get(CONF_CLUB_SHORT) or entry.data.get(CONF_CLUB_NAME),
        manufacturer="LISA",
        model=entry.data.get(CONF_CLUB_NAME),
        entry_type=dr.DeviceEntryType.SERVICE,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    known = set(coordinator.data.members)

    @callback
    def _new_member() -> None:
        # A family member seen for the first time gets their device on a reload.
        if coordinator.data and set(coordinator.data.members) - known:
            hass.config_entries.async_schedule_reload(entry.entry_id)

    entry.async_on_unload(coordinator.async_add_listener(_new_member))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LisaConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: LisaConfigEntry) -> None:
    """Remove what was stored for change alerts."""
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()
