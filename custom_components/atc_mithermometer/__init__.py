"""The ATC MiThermometer Manager integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.entity import DeviceInfo
from packaging import version

from .const import (
    ATC_NAME_PREFIXES,
    CONF_FIRMWARE_SOURCE,
    CONF_MAC_ADDRESS,
    DOMAIN,
    FIRMWARE_SOURCES,
    SERVICE_UUID_ENVIRONMENTAL,
    normalize_mac,
)
from .firmware import FirmwareManager

_LOGGER = logging.getLogger(__name__)

# BTHome integration domain - used to link devices
# We define this directly to avoid import dependencies on the BTHome integration
BTHOME_DOMAIN = "bthome"

# Service names
SERVICE_APPLY_FIRMWARE = "apply_firmware"

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.UPDATE]


def _versions_equal(version1: str, version2: str) -> bool:
    """Compare two version strings for equality.

    Uses packaging.version for semantic version comparison, with fallback
    to string comparison if versions can't be parsed.

    Handles common version formats:
    - "v1.0.0" vs "1.0.0" (prefix differences)
    - "1.0" vs "1.0.0" (different precision)

    Args:
        version1: First version string
        version2: Second version string

    Returns:
        True if versions are semantically equal, False otherwise
    """
    # Try semantic version comparison first
    try:
        # Normalize by removing common prefixes like 'v'
        v1_normalized = version1.lstrip("v")
        v2_normalized = version2.lstrip("v")

        v1_parsed = version.parse(v1_normalized)
        v2_parsed = version.parse(v2_normalized)

        return v1_parsed == v2_parsed
    except version.InvalidVersion:
        # Fall back to string comparison if parsing fails
        # This handles custom version schemes that don't follow semver
        # Normalize both versions by removing 'v' prefix before comparing
        _LOGGER.debug(
            "Could not parse versions '%s' and '%s' semantically, "
            "using string comparison",
            version1,
            version2,
        )
        return version1.lstrip("v") == version2.lstrip("v")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ATC MiThermometer Manager from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Store config entry data
    hass.data[DOMAIN][entry.entry_id] = {
        CONF_FIRMWARE_SOURCE: entry.data[CONF_FIRMWARE_SOURCE],
        CONF_MAC_ADDRESS: entry.data[CONF_MAC_ADDRESS],
    }

    # Link this config entry to the existing BTHome device
    # This must happen before platform setup so that when the update entity
    # is created, it can properly reference the shared device and avoid
    # creating duplicate device entries
    mac_address = entry.data[CONF_MAC_ADDRESS]
    device_registry = dr.async_get(hass)
    bthome_device = await get_bthome_device_by_mac(hass, mac_address)

    if bthome_device:
        # Add our config entry to the existing device
        try:
            device_registry.async_update_device(
                bthome_device.id, add_config_entry_id=entry.entry_id
            )
            _LOGGER.info(
                "Linked config entry to existing BTHome device %s",
                mac_address,
            )
        except (ValueError, KeyError) as err:
            # ValueError: Invalid device ID (device was deleted between check
            # and update)
            # KeyError: Device registry entry missing expected keys
            _LOGGER.warning(
                "Failed to link config entry to BTHome device %s: %s. "
                "Entity will create standalone device.",
                mac_address,
                err,
            )
            # Continue setup anyway - entity will create standalone device as fallback

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Set up listener for device updates
    entry.async_on_unload(
        hass.bus.async_listen(
            f"{BTHOME_DOMAIN}_device_update",
            lambda event: _handle_bthome_update(hass, entry, event),
        )
    )

    # Register service for applying firmware (only once for the domain)
    # Note: While there's a theoretical race condition if multiple config entries
    # are loaded simultaneously, Home Assistant's service registry handles this
    # safely - async_register is idempotent and won't error on duplicate calls.
    # The check below is an optimization to avoid unnecessary registrations.
    if not hass.services.has_service(DOMAIN, SERVICE_APPLY_FIRMWARE):

        async def async_handle_apply_firmware(call: ServiceCall) -> None:
            """Handle the apply_firmware service call."""
            await _async_apply_firmware(hass, call)

        hass.services.async_register(
            DOMAIN,
            SERVICE_APPLY_FIRMWARE,
            async_handle_apply_firmware,
            schema=vol.Schema(
                {
                    vol.Required("device_id"): str,
                    vol.Required("desired_version"): str,
                }
            ),
        )

    return True


async def _async_apply_firmware(hass: HomeAssistant, call: ServiceCall) -> None:
    """Apply firmware to a device if desired version doesn't match current version.

    This service allows programmatic firmware updates through automations and scripts.
    It uses the shared firmware application logic from FirmwareManager to ensure
    consistency with the update entity implementation.

    Args:
        hass: Home Assistant instance
        call: Service call data containing device_id and desired_version

    Raises:
        HomeAssistantError: If device not found, version mismatch check fails,
                           or firmware application fails
    """
    device_id = call.data["device_id"]
    desired_version = call.data["desired_version"]

    # Get device from device registry
    device_registry = dr.async_get(hass)
    device = device_registry.async_get(device_id)

    if not device:
        raise HomeAssistantError(f"Device {device_id} not found")

    # Get MAC address from device
    mac_address = None
    for connection in device.connections:
        if connection[0] == dr.CONNECTION_BLUETOOTH:
            mac_address = connection[1]
            break

    if not mac_address:
        raise HomeAssistantError(
            f"No Bluetooth MAC address found for device {device_id}"
        )

    # Find the config entry for this device
    config_entry = None
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and entry.domain == DOMAIN:
            config_entry = entry
            break

    if not config_entry:
        raise HomeAssistantError(
            f"No ATC MiThermometer config entry found for device {device_id}"
        )

    # Get current version
    firmware_manager = FirmwareManager(hass, mac_address)
    current_version = await firmware_manager.get_current_version()

    if not current_version:
        _LOGGER.warning(
            "Could not determine current firmware version for %s, "
            "proceeding with update",
            mac_address,
        )
    elif _versions_equal(current_version, desired_version):
        _LOGGER.info(
            "Device %s already has desired firmware version %s",
            mac_address,
            desired_version,
        )
        return

    # Get firmware source from config
    firmware_source = config_entry.data[CONF_FIRMWARE_SOURCE]

    # Validate firmware source
    if firmware_source not in FIRMWARE_SOURCES:
        raise HomeAssistantError(
            f"Invalid firmware source: {firmware_source}. "
            f"Valid sources are: {', '.join(FIRMWARE_SOURCES.keys())}"
        )

    # Get the specific version requested
    release = await firmware_manager.get_release_by_version(
        firmware_source, desired_version
    )

    if not release:
        raise HomeAssistantError(
            f"Firmware version {desired_version} not found for source "
            f"{firmware_source}. Please check the version number and try again."
        )

    _LOGGER.info(
        "Applying firmware %s to device %s (current: %s)",
        release.version,
        mac_address,
        current_version or "unknown",
    )

    # Progress callback for logging with milestone tracking
    last_milestone = {"value": 0}  # Use dict to allow mutation in nested function

    def progress_callback(current: int, total: int) -> None:
        """Log progress during flash at 25% milestones."""
        if total > 0 and current > 0:
            progress_percent = (current * 100) // total
            # Determine current milestone (0, 25, 50, 75, 100)
            current_milestone = (progress_percent // 25) * 25

            # Log when we cross a new milestone
            if current_milestone > last_milestone["value"] and current_milestone <= 100:
                last_milestone["value"] = current_milestone
                _LOGGER.info(
                    "Flash progress: %d%% (%d/%d)", current_milestone, current, total
                )

    # Use shared firmware application logic
    await firmware_manager.apply_firmware_update(release, progress_callback)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

        # Remove service if this is the last config entry for this integration
        # Check is done within the event loop so it's thread-safe
        # Also verify service exists before attempting removal
        if (
            not hass.config_entries.async_entries(DOMAIN)
            and hass.services.has_service(DOMAIN, SERVICE_APPLY_FIRMWARE)
        ):
            try:
                hass.services.async_remove(DOMAIN, SERVICE_APPLY_FIRMWARE)
                _LOGGER.debug(
                    "Removed apply_firmware service (last config entry unloaded)"
                )
            except (ValueError, KeyError, RuntimeError) as err:
                # Service might have been removed by another concurrent unload
                # or the service registry may have internal errors
                # This is not a fatal error, just log it
                _LOGGER.debug(
                    "Failed to remove apply_firmware service "
                    "(may have been removed already): %s",
                    err,
                )

        # Note: We don't remove the config entry from the device here
        # because the device is shared with BTHome integration.
        # Home Assistant will handle cleanup automatically.
        # FirmwareManager uses Home Assistant's shared session, so no cleanup needed.

    return unload_ok


@callback
def _handle_bthome_update(hass: HomeAssistant, entry: ConfigEntry, event: Any) -> None:
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
                and any(device.name.startswith(prefix) for prefix in ATC_NAME_PREFIXES)
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

    Args:
        hass: Home Assistant instance
        mac_address: Bluetooth MAC address in any format
                     (will be normalized to uppercase)

    Returns:
        BTHome device entry if found, None otherwise
    """
    device_registry = dr.async_get(hass)

    # Normalize MAC address to Home Assistant standard format
    try:
        mac_normalized = normalize_mac(mac_address)
    except ValueError as err:
        _LOGGER.error("Invalid MAC address format: %s", err)
        return None

    # Find device by bluetooth connection
    device = device_registry.async_get_device(
        connections={(dr.CONNECTION_BLUETOOTH, mac_normalized)}
    )

    if not device:
        return None

    # Verify it's a BTHome device by checking if any config entry belongs to BTHome
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and entry.domain == BTHOME_DOMAIN:
            return device

    return None


def create_device_info(
    mac_address: str, bthome_device: DeviceEntry | None = None
) -> DeviceInfo:
    """Create DeviceInfo for an ATC MiThermometer device.

    This shared helper ensures consistent device linking across all entity platforms
    (sensor, update, etc.) and avoids duplicate device entries.

    Args:
        mac_address: The Bluetooth MAC address of the device
        bthome_device: Optional existing BTHome device entry to link to

    Returns:
        DeviceInfo configured to link to BTHome device or create standalone device
    """
    try:
        mac_normalized = normalize_mac(mac_address)
    except ValueError:
        # Fallback to original if normalization fails
        mac_normalized = mac_address

    if bthome_device:
        # Link to existing BTHome device by combining identifiers
        # This intentional identifier sharing allows both BTHome and this
        # integration to manage the same physical device
        identifiers: set[tuple[str, str]] = set(bthome_device.identifiers) | {
            (DOMAIN, mac_normalized)
        }

        return DeviceInfo(
            identifiers=identifiers,
            connections=bthome_device.connections,
        )

    # Fallback: create standalone device if BTHome device not found
    return DeviceInfo(
        identifiers={(DOMAIN, mac_normalized)},
        name=f"ATC MiThermometer {mac_normalized[-5:]}",
        manufacturer="Custom",
        model="ATC MiThermometer",
        connections={(dr.CONNECTION_BLUETOOTH, mac_normalized)},
    )
