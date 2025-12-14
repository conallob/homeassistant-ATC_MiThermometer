"""Firmware management for ATC MiThermometer devices."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

import aiohttp
from bleak import BleakClient, BleakError
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (CHAR_UUID_OTA_CONTROL, CHAR_UUID_OTA_DATA, CHUNK_SIZE,
                    FIRMWARE_SOURCES, FLASH_TIMEOUT, MAX_FIRMWARE_SIZE,
                    MIN_FIRMWARE_SIZE, OTA_CHUNK_DELAY, OTA_COMMAND_DELAY)

_LOGGER = logging.getLogger(__name__)


@dataclass
class FirmwareRelease:
    """Firmware release information."""

    version: str
    download_url: str
    release_url: str
    release_notes: str | None = None
    published_at: str | None = None


class FirmwareManager:
    """Manage firmware operations for ATC MiThermometer devices."""

    def __init__(self, hass: HomeAssistant, mac_address: str) -> None:
        """Initialize firmware manager."""
        self.hass = hass
        self.mac_address = mac_address
        # Use Home Assistant's shared aiohttp session instead of creating our own
        # This is automatically cleaned up by Home Assistant
        self._session = async_get_clientsession(hass)

    async def get_latest_release(self, firmware_source: str) -> FirmwareRelease | None:
        """Get latest firmware release from GitHub."""
        if firmware_source not in FIRMWARE_SOURCES:
            _LOGGER.error("Unknown firmware source: %s", firmware_source)
            return None

        source_info = FIRMWARE_SOURCES[firmware_source]
        api_url = source_info["api_url"]
        asset_pattern = source_info["asset_pattern"]

        try:
            async with self._session.get(
                api_url, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status != 200:
                    _LOGGER.error(
                        "Failed to fetch release info: HTTP %s", response.status
                    )
                    return None

                data = await response.json()

                # Find matching binary asset
                download_url = None
                for asset in data.get("assets", []):
                    if re.match(asset_pattern, asset["name"]):
                        download_url = asset["browser_download_url"]
                        break

                if not download_url:
                    _LOGGER.warning(
                        "No matching firmware binary found in release %s",
                        data.get("tag_name"),
                    )
                    return None

                return FirmwareRelease(
                    version=data.get("tag_name", "unknown"),
                    download_url=download_url,
                    release_url=data.get("html_url", ""),
                    release_notes=data.get("body"),
                    published_at=data.get("published_at"),
                )

        except asyncio.TimeoutError:
            _LOGGER.error("Timeout fetching firmware release")
            return None
        except aiohttp.ClientError as err:
            _LOGGER.error("Error fetching firmware release: %s", err)
            return None
        except (KeyError, ValueError, TypeError) as err:
            _LOGGER.error("Error parsing firmware release data: %s", err)
            return None

    async def download_firmware(self, download_url: str) -> bytes | None:
        """Download firmware binary from URL."""
        try:
            async with self._session.get(
                download_url, timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                if response.status != 200:
                    _LOGGER.error(
                        "Failed to download firmware: HTTP %s", response.status
                    )
                    return None

                firmware_data = await response.read()

                # Validate firmware size
                firmware_size = len(firmware_data)
                if firmware_size < MIN_FIRMWARE_SIZE:
                    _LOGGER.error(
                        "Downloaded firmware too small: %d bytes (minimum %d)",
                        firmware_size,
                        MIN_FIRMWARE_SIZE,
                    )
                    return None

                if firmware_size > MAX_FIRMWARE_SIZE:
                    _LOGGER.error(
                        "Downloaded firmware too large: %d bytes (maximum %d)",
                        firmware_size,
                        MAX_FIRMWARE_SIZE,
                    )
                    return None

                _LOGGER.info(
                    "Downloaded firmware: %d bytes from %s",
                    firmware_size,
                    download_url,
                )
                return firmware_data

        except asyncio.TimeoutError:
            _LOGGER.error("Timeout downloading firmware")
            return None
        except aiohttp.ClientError as err:
            _LOGGER.error("Error downloading firmware: %s", err)
            return None

    async def flash_firmware(
        self,
        firmware_data: bytes,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> bool:
        """Flash firmware to device via BLE OTA.

        Args:
            firmware_data: The firmware binary data
            progress_callback: Optional callback for progress updates (current, total)

        Returns:
            True if successful, False otherwise
        """
        _LOGGER.info("Starting firmware flash for device %s", self.mac_address)

        try:
            # Get BLE device
            ble_device = bluetooth.async_ble_device_from_address(
                self.hass, self.mac_address, connectable=True
            )

            if not ble_device:
                raise HomeAssistantError(f"Device {self.mac_address} not found")

            async with BleakClient(ble_device, timeout=FLASH_TIMEOUT) as client:
                # Verify connection
                if not client.is_connected:
                    raise HomeAssistantError("Failed to connect to device")

                _LOGGER.info("Connected to device %s", self.mac_address)

                # Start OTA mode
                await self._start_ota_mode(client)

                # Send firmware in chunks
                total_chunks = (len(firmware_data) + CHUNK_SIZE - 1) // CHUNK_SIZE

                for i in range(0, len(firmware_data), CHUNK_SIZE):
                    chunk = firmware_data[i : i + CHUNK_SIZE]
                    chunk_num = i // CHUNK_SIZE

                    await client.write_gatt_char(CHAR_UUID_OTA_DATA, chunk)

                    if progress_callback:
                        progress_callback(chunk_num + 1, total_chunks)

                    # Small delay to avoid overwhelming the device
                    await asyncio.sleep(OTA_CHUNK_DELAY)

                    # Log only at 25% milestones to reduce log spam
                    progress_percent = ((chunk_num + 1) * 100) // total_chunks
                    if progress_percent % 25 == 0 and (
                        chunk_num == 0
                        or ((chunk_num * 100) // total_chunks) // 25
                        != progress_percent // 25
                    ):
                        _LOGGER.debug(
                            "Flash progress: %d%% (%d/%d chunks)",
                            progress_percent,
                            chunk_num + 1,
                            total_chunks,
                        )

                # Finalize OTA
                await self._finalize_ota(client)

                _LOGGER.info("Firmware flash completed successfully")
                return True

        except BleakError as err:
            _LOGGER.error("BLE error during firmware flash: %s", err)
            return False
        except asyncio.TimeoutError:
            _LOGGER.error("Timeout during firmware flash")
            return False
        except HomeAssistantError as err:
            _LOGGER.error("Home Assistant error during firmware flash: %s", err)
            return False

    async def _start_ota_mode(self, client: BleakClient) -> None:
        """Start OTA mode on device."""
        # Send OTA start command (device-specific implementation)
        # This is a placeholder - actual command depends on ATC firmware
        try:
            # Command to enter OTA mode (example, may need adjustment)
            await client.write_gatt_char(CHAR_UUID_OTA_CONTROL, b"\x01")
            await asyncio.sleep(OTA_COMMAND_DELAY)
            _LOGGER.debug("OTA mode started")
        except (BleakError, TimeoutError) as err:
            # These errors are expected if device doesn't support this command
            _LOGGER.debug("OTA mode start command not supported or failed: %s", err)

    async def _finalize_ota(self, client: BleakClient) -> None:
        """Finalize OTA update."""
        try:
            # Send OTA complete command
            await client.write_gatt_char(CHAR_UUID_OTA_CONTROL, b"\x02")
            await asyncio.sleep(OTA_COMMAND_DELAY)
            _LOGGER.debug("OTA finalized")
        except (BleakError, TimeoutError) as err:
            # These errors are expected if device doesn't support this command
            _LOGGER.debug("OTA finalize command not supported or failed: %s", err)

    async def get_current_version(self) -> str | None:
        """Get current firmware version from device.

        This attempts to read the firmware version from the device
        via BLE characteristics or advertisements.
        """
        try:
            ble_device = bluetooth.async_ble_device_from_address(
                self.hass, self.mac_address, connectable=True
            )

            if not ble_device:
                _LOGGER.debug("Device %s not available", self.mac_address)
                return None

            # Try to get version from advertisement data first
            service_info = bluetooth.async_last_service_info(
                self.hass, self.mac_address, connectable=True
            )

            if service_info and service_info.manufacturer_data:
                # Parse version from manufacturer data if present
                # This is device-specific and may need adjustment
                for mfr_id, data in service_info.manufacturer_data.items():
                    try:
                        if len(data) >= 6:
                            # Version might be encoded in manufacturer data
                            # Format depends on firmware implementation
                            version = f"{data[4]}.{data[5]}"
                            _LOGGER.debug(
                                "Detected version %s from advertisements", version
                            )
                            return version
                    except (IndexError, KeyError) as err:
                        # Firmware format may have changed, continue to next
                        _LOGGER.debug(
                            "Could not parse version from manufacturer data: %s", err
                        )
                        continue

            # Fallback: try reading from device info service
            # This would require connecting to the device
            _LOGGER.debug("Could not determine version from advertisements")
            return None

        except (BleakError, HomeAssistantError) as err:
            _LOGGER.debug("Error getting current version: %s", err)
            return None
