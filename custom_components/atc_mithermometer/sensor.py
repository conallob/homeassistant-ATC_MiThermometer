"""Sensor platform for ATC MiThermometer Manager integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from . import create_device_info, get_bthome_device_by_mac
from .const import (
    ATTR_CURRENT_VERSION,
    ATTR_FIRMWARE_SOURCE,
    CONF_FIRMWARE_SOURCE,
    CONF_MAC_ADDRESS,
    FIRMWARE_SOURCES,
    UPDATE_CHECK_INTERVAL,
)
from .firmware import FirmwareManager

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ATC MiThermometer sensor entities."""
    mac_address = entry.data[CONF_MAC_ADDRESS]
    firmware_source = entry.data[CONF_FIRMWARE_SOURCE]

    firmware_manager = FirmwareManager(hass, mac_address)

    # Get the existing BTHome device to link to
    bthome_device = await get_bthome_device_by_mac(hass, mac_address)

    # Create coordinator for checking firmware version
    coordinator = ATCFirmwareCoordinator(
        hass,
        firmware_manager,
        firmware_source,
        mac_address,
    )

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    async_add_entities(
        [ATCFirmwareVersionSensor(coordinator, entry, bthome_device)],
        True,
    )


class ATCFirmwareCoordinator(DataUpdateCoordinator):
    """Coordinator for checking firmware version."""

    def __init__(
        self,
        hass: HomeAssistant,
        firmware_manager: FirmwareManager,
        firmware_source: str,
        mac_address: str,
    ) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"ATC MiThermometer Firmware {mac_address}",
            update_interval=UPDATE_CHECK_INTERVAL,
        )
        self.firmware_manager = firmware_manager
        self.firmware_source = firmware_source
        self.mac_address = mac_address

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch current firmware version."""
        try:
            # Get current version from device
            current_version = await self.firmware_manager.get_current_version()

            return {
                ATTR_CURRENT_VERSION: current_version,
                ATTR_FIRMWARE_SOURCE: self.firmware_source,
            }

        except UpdateFailed:
            # Re-raise UpdateFailed as-is
            raise
        except Exception as err:
            # Other unexpected errors
            raise UpdateFailed(f"Error fetching firmware version: {err}") from err


class ATCFirmwareVersionSensor(CoordinatorEntity, SensorEntity):
    """Sensor entity for ATC MiThermometer firmware version."""

    _attr_has_entity_name = True
    _attr_name = "Firmware Version"

    def __init__(
        self,
        coordinator: ATCFirmwareCoordinator,
        entry: ConfigEntry,
        bthome_device = None,
    ) -> None:
        """Initialize the sensor entity."""
        super().__init__(coordinator)
        self._mac_address = entry.data[CONF_MAC_ADDRESS]
        self._attr_unique_id = f"{self._mac_address}_firmware_version"

        # Use shared device info helper
        self._attr_device_info = create_device_info(self._mac_address, bthome_device)

        if bthome_device:
            _LOGGER.debug(
                "Linked firmware sensor to existing BTHome device %s",
                self._mac_address,
            )
        else:
            _LOGGER.debug(
                "BTHome device not found for %s, created standalone device",
                self._mac_address,
            )

    @property
    def native_value(self) -> str | None:
        """Return the current firmware version."""
        version = self.coordinator.data.get(ATTR_CURRENT_VERSION)
        return version if version else "Unknown"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        firmware_source = self.coordinator.data.get(ATTR_FIRMWARE_SOURCE)
        return {
            ATTR_FIRMWARE_SOURCE: firmware_source,
            "firmware_source_name": FIRMWARE_SOURCES.get(firmware_source, {}).get(
                "name", "Unknown"
            ),
        }
