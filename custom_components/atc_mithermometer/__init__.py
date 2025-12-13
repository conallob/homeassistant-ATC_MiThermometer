"""The ATC MiThermometer Manager integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components import bluetooth
from homeassistant.components.bthome import DOMAIN as BTHOME_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntry

from .const import (
    ATC_NAME_PREFIXES,
    CONF_FIRMWARE_SOURCE,
    CONF_MAC_ADDRESS,
    DOMAIN,
    PVVX_DEVICE_TYPE,
    SERVICE_UUID_ENVIRONMENTAL,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.UPDATE]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ATC MiThermometer Manager from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Store config entry data
    hass.data[DOMAIN][entry.entry_id] = {
        CONF_FIRMWARE_SOURCE: entry.data[CONF_FIRMWARE_SOURCE],
        CONF_MAC_ADDRESS: entry.data[CONF_MAC_ADDRESS],
    }

    # Link this config entry to the existing BTHome device
    mac_address = entry.data[CONF_MAC_ADDRESS]
    device_registry = dr.async_get(hass)
    bthome_device = await get_bthome_device_by_mac(hass, mac_address)

    if bthome_device:
        # Add our config entry to the existing device
        device_registry.async_update_device(
            bthome_device.id, add_config_entry_id=entry.entry_id
        )
        _LOGGER.debug(
            "Linked config entry %s to existing BTHome device %s",
            entry.entry_id,
            mac_address,
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Set up listener for device updates
    entry.async_on_unload(
        hass.bus.async_listen(
            f"{BTHOME_DOMAIN}_device_update",
            lambda event: _handle_bthome_update(hass, entry, event),
        )
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

        # Note: We don't remove the config entry from the device here
        # because the device is shared with BTHome integration.
        # Home Assistant will handle cleanup automatically.

    return unload_ok


@callback
def _handle_bthome_update(
    hass: HomeAssistant, entry: ConfigEntry, event: Any
) -> None:
    """Handle BTHome device updates."""
    # This allows us to react to BTHome device state changes if needed
    _LOGGER.debug("BTHome device update: %s", event.data)


def is_atc_mithermometer(device_name: str | None, service_uuids: list[str]) -> bool:
    """Check if a device is an ATC MiThermometer.

    Identifies devices by:
    - Name prefix (ATC_, LYWSD03MMC)
    - Environmental sensing service UUID
    """
    if device_name:
        for prefix in ATC_NAME_PREFIXES:
            if device_name.startswith(prefix):
                return True

    # Check for environmental sensing service
    if SERVICE_UUID_ENVIRONMENTAL.lower() in [uuid.lower() for uuid in service_uuids]:
        return True

    return False


async def get_atc_devices_from_bthome(hass: HomeAssistant) -> list[DeviceEntry]:
    """Get list of ATC MiThermometer devices from BTHome integration."""
    device_registry = dr.async_get(hass)
    atc_devices = []
    seen_device_ids = set()

    # Get all devices from all BTHome config entries
    # Use a set to track device IDs to avoid duplicates when a device
    # is associated with multiple BTHome config entries
    for entry in hass.config_entries.async_entries(BTHOME_DOMAIN):
        devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
        for device in devices:
            # Check if device matches ATC MiThermometer characteristics
            # and hasn't been added yet
            if (
                device.id not in seen_device_ids
                and device.name
                and any(
                    device.name.startswith(prefix) for prefix in ATC_NAME_PREFIXES
                )
            ):
                seen_device_ids.add(device.id)
                atc_devices.append(device)

    return atc_devices


async def get_device_mac_address(hass: HomeAssistant, device_id: str) -> str | None:
    """Get MAC address for a device."""
    device_registry = dr.async_get(hass)
    device = device_registry.async_get(device_id)

    if not device or not device.connections:
        return None

    # Extract MAC address from device connections
    for connection in device.connections:
        if connection[0] == dr.CONNECTION_BLUETOOTH:
            return connection[1]

    return None


async def get_bthome_device_by_mac(
    hass: HomeAssistant, mac_address: str
) -> DeviceEntry | None:
    """Get BTHome device entry by MAC address.

    This allows us to link our entities to the existing BTHome device
    instead of creating a duplicate device entry.
    """
    device_registry = dr.async_get(hass)

    # Find device by bluetooth connection
    device = device_registry.async_get_device(
        connections={(dr.CONNECTION_BLUETOOTH, mac_address)}
    )

    if not device:
        return None

    # Verify it's a BTHome device
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and entry.domain == BTHOME_DOMAIN:
            return device

    return None


async def get_current_firmware_version(
    hass: HomeAssistant, mac_address: str
) -> str | None:
    """Get current firmware version from device.

    This would typically be parsed from BLE advertisements or
    read from a device characteristic.
    """
    # TODO: Implement version detection from BLE
    # For now, return None - will be implemented in firmware.py
    _LOGGER.debug("Getting firmware version for %s", mac_address)
    return None
