"""Update platform for ATC MiThermometer Manager integration."""

from __future__ import annotations

import aiohttp
import logging
from typing import Any

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from . import get_bthome_device_by_mac
from .const import (
    ATTR_CURRENT_VERSION,
    ATTR_FIRMWARE_SOURCE,
    ATTR_LATEST_VERSION,
    CONF_FIRMWARE_SOURCE,
    CONF_MAC_ADDRESS,
    DOMAIN,
    FIRMWARE_SOURCES,
    PROGRESS_COMPLETE,
    PROGRESS_DOWNLOAD_COMPLETE,
    PROGRESS_DOWNLOAD_START,
    PROGRESS_FLASH_RANGE,
    UPDATE_CHECK_INTERVAL,
    normalize_mac,
)
from .firmware import FirmwareManager, FirmwareRelease

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ATC MiThermometer update entities."""
    mac_address = entry.data[CONF_MAC_ADDRESS]
    firmware_source = entry.data[CONF_FIRMWARE_SOURCE]

    firmware_manager = FirmwareManager(hass, mac_address)

    # Get the existing BTHome device to link to
    bthome_device = await get_bthome_device_by_mac(hass, mac_address)

    # Create coordinator for checking updates
    coordinator = ATCUpdateCoordinator(
        hass,
        firmware_manager,
        firmware_source,
        mac_address,
    )

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    async_add_entities(
        [ATCMiThermometerUpdate(coordinator, entry, firmware_manager, bthome_device)],
        True,
    )


class ATCUpdateCoordinator(DataUpdateCoordinator):
    """Coordinator for checking firmware updates."""

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
            name=f"ATC MiThermometer {mac_address}",
            update_interval=UPDATE_CHECK_INTERVAL,
        )
        self.firmware_manager = firmware_manager
        self.firmware_source = firmware_source
        self.mac_address = mac_address

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch latest firmware info."""
        try:
            # Get current version from device
            current_version = await self.firmware_manager.get_current_version()

            # Get latest release info
            latest_release = await self.firmware_manager.get_latest_release(
                self.firmware_source
            )

            if not latest_release:
                raise UpdateFailed("Failed to fetch latest release info")

            return {
                ATTR_CURRENT_VERSION: current_version,
                ATTR_LATEST_VERSION: latest_release.version,
                "latest_release": latest_release,
                ATTR_FIRMWARE_SOURCE: self.firmware_source,
            }

        except UpdateFailed:
            # Re-raise UpdateFailed as-is
            raise
        except (OSError, TimeoutError, aiohttp.ClientError) as err:
            # Network and HTTP errors
            raise UpdateFailed(f"Error fetching update data: {err}") from err


class ATCMiThermometerUpdate(CoordinatorEntity, UpdateEntity):
    """Update entity for ATC MiThermometer firmware."""

    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL
        | UpdateEntityFeature.PROGRESS
        | UpdateEntityFeature.RELEASE_NOTES
    )

    def __init__(
        self,
        coordinator: ATCUpdateCoordinator,
        entry: ConfigEntry,
        firmware_manager: FirmwareManager,
        bthome_device: dr.DeviceEntry | None = None,
    ) -> None:
        """Initialize the update entity."""
        super().__init__(coordinator)
        self._firmware_manager = firmware_manager
        self._mac_address = entry.data[CONF_MAC_ADDRESS]
        self._attr_unique_id = f"{self._mac_address}_firmware_update"
        self._attr_name = "Firmware Update"
        self._install_progress = 0

        # Device info - link to existing BTHome device if available
        if bthome_device:
            # Use the existing BTHome device's identifiers to link our entity
            # Add our domain to the existing identifiers so both integrations
            # can manage the same device. This intentional identifier sharing
            # allows both BTHome and this integration to manage the same physical
            # device, with BTHome handling sensors and this handling firmware updates.
            # Create explicit copy to avoid mutating BTHome device's identifiers
            try:
                mac_normalized = normalize_mac(self._mac_address)
            except ValueError:
                # Fallback to original if normalization fails
                mac_normalized = self._mac_address
            identifiers: set[tuple[str, str]] = set(bthome_device.identifiers) | {
                (DOMAIN, mac_normalized)
            }

            self._attr_device_info = DeviceInfo(
                identifiers=identifiers,
                connections=bthome_device.connections,
            )
            _LOGGER.debug(
                "Linking to existing BTHome device %s with identifiers: %s",
                self._mac_address,
                identifiers,
            )
        else:
            # Fallback: create standalone device if BTHome device not found
            try:
                mac_normalized = normalize_mac(self._mac_address)
            except ValueError:
                # Fallback to original if normalization fails
                mac_normalized = self._mac_address
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, mac_normalized)},
                name=f"ATC MiThermometer {mac_normalized[-5:]}",
                manufacturer="Custom",
                model="ATC MiThermometer",
                connections={(dr.CONNECTION_BLUETOOTH, mac_normalized)},
            )
            _LOGGER.debug(
                "BTHome device not found for %s, creating standalone device",
                self._mac_address,
            )

    @property
    def installed_version(self) -> str | None:
        """Return the current installed version."""
        return self.coordinator.data.get(ATTR_CURRENT_VERSION)

    @property
    def latest_version(self) -> str | None:
        """Return the latest available version."""
        return self.coordinator.data.get(ATTR_LATEST_VERSION)

    @property
    def release_url(self) -> str | None:
        """Return the release URL."""
        latest_release: FirmwareRelease | None = self.coordinator.data.get(
            "latest_release"
        )
        return latest_release.release_url if latest_release else None

    @property
    def release_summary(self) -> str | None:
        """Return the release notes."""
        latest_release: FirmwareRelease | None = self.coordinator.data.get(
            "latest_release"
        )
        return latest_release.release_notes if latest_release else None

    @property
    def in_progress(self) -> bool | int:
        """Return the installation progress."""
        if self._install_progress > 0:
            return self._install_progress
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {
            ATTR_FIRMWARE_SOURCE: self.coordinator.data.get(ATTR_FIRMWARE_SOURCE),
            "firmware_source_name": FIRMWARE_SOURCES.get(
                self.coordinator.data.get(ATTR_FIRMWARE_SOURCE, ""), {}
            ).get("name", "Unknown"),
        }

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Install firmware update."""
        latest_release: FirmwareRelease | None = self.coordinator.data.get(
            "latest_release"
        )

        if not latest_release:
            raise HomeAssistantError("No firmware release available")

        _LOGGER.info(
            "Starting firmware installation for %s: %s",
            self._mac_address,
            latest_release.version,
        )

        try:
            # Download firmware
            self._install_progress = PROGRESS_DOWNLOAD_START
            self.async_write_ha_state()

            firmware_data = await self._firmware_manager.download_firmware(
                latest_release.download_url
            )

            if not firmware_data:
                raise HomeAssistantError("Failed to download firmware")

            self._install_progress = PROGRESS_DOWNLOAD_COMPLETE
            self.async_write_ha_state()

            # Flash firmware
            def progress_callback(current: int, total: int) -> None:
                """Update progress during flash."""
                # Map progress from DOWNLOAD_COMPLETE to near COMPLETE
                progress = PROGRESS_DOWNLOAD_COMPLETE + int(
                    (current / total) * PROGRESS_FLASH_RANGE
                )
                self._install_progress = progress
                # Schedule state write on event loop for thread safety
                self.hass.loop.call_soon_threadsafe(self.async_write_ha_state)

            success = await self._firmware_manager.flash_firmware(
                firmware_data, progress_callback
            )

            if not success:
                raise HomeAssistantError("Firmware flash failed")

            self._install_progress = PROGRESS_COMPLETE
            self.async_write_ha_state()

            # Wait a bit for device to reboot, then refresh
            await self.coordinator.async_request_refresh()

        except HomeAssistantError:
            # Re-raise our own errors without wrapping
            raise
        except (UpdateFailed, RuntimeError) as err:
            # Coordinator refresh failures or state update errors
            _LOGGER.error("Error installing firmware: %s", err)
            raise HomeAssistantError(f"Installation failed: {err}") from err
        finally:
            self._install_progress = 0
            self.async_write_ha_state()

    @callback
    def async_create_repair_issue(self) -> None:
        """Create a repair issue for available update."""
        if self.installed_version and self.latest_version:
            if self.installed_version != self.latest_version:
                # This would integrate with HA's repairs system
                # to notify users of available updates
                _LOGGER.info(
                    "Firmware update available for %s: %s -> %s",
                    self._mac_address,
                    self.installed_version,
                    self.latest_version,
                )
