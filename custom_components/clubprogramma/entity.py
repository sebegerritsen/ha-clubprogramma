"""Base entities: a device per family member, and one for the account (the club)."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CLUB_NAME, CONF_CLUB_SHORT, DOMAIN
from .coordinator import LisaCoordinator


class LisaEntity(CoordinatorEntity[LisaCoordinator]):
    """An entity of a LISA login."""

    _attr_has_entity_name = True
    _attr_attribution = "Data: LISA"


class LisaMemberEntity(LisaEntity):
    """An entity of one family member."""

    def __init__(self, coordinator: LisaCoordinator, member_id: str, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.member_id = member_id
        account = coordinator.account_id
        member = coordinator.data.members.get(member_id)
        self._attr_unique_id = f"{account}_{member_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{account}_{member_id}")},
            name=member.first_name if member else member_id,
            manufacturer=coordinator.config_entry.data.get(CONF_CLUB_NAME),
            entry_type=DeviceEntryType.SERVICE,
        )


class LisaAccountEntity(LisaEntity):
    """An entity of the login itself: club-wide things."""

    def __init__(self, coordinator: LisaCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        account = coordinator.account_id
        data = coordinator.config_entry.data
        self._attr_unique_id = f"{account}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, account)},
            name=data.get(CONF_CLUB_SHORT) or data.get(CONF_CLUB_NAME),
            manufacturer=data.get(CONF_CLUB_NAME),
            entry_type=DeviceEntryType.SERVICE,
        )
