"""Firmware management for ATC MiThermometer devices."""

from __future__ import annotations

import asyncio
import hashlib
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

from .const import (
    CHAR_UUID_OTA_CONTROL,
    CHAR_UUID_OTA_DATA,
    CHAR_UUID_SOFTWARE_REVISION,
    CHUNK_SIZE,
    FIRMWARE_SOURCES,
    FLASH_TIMEOUT,
    GATT_CONNECTION_TIMEOUT,
    MAX_FIRMWARE_SIZE,
    MAX_VERSION_LENGTH,
    MIN_FIRMWARE_SIZE,
    MIN_MANUFACTURER_DATA_LEN,
    OTA_CHUNK_DELAY,
    OTA_COMMAND_DELAY,
    VERSION_BYTE_MAJOR,
    VERSION_BYTE_MINOR,
    VERSION_PREFIX_CHARS,
    VERSION_VALIDATION_PATTERN,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class FirmwareRelease:
    """Firmware release information."""

    version: str
    download_url: str
    release_url: str
    release_notes: str | None = None
    published_at: str | None = None
    checksum: str | None = None
    checksum_type: str | None = None


class FirmwareManager:
    """Manage firmware operations for ATC MiThermometer devices."""

    def __init__(self, hass: HomeAssistant, mac_address: str) -> None:
        """Initialize firmware manager."""
        self.hass = hass
        self.mac_address = mac_address
        # Use Home Assistant's shared aiohttp session instead of creating our own
        # This is automatically cleaned up by Home Assistant
        self._session = async_get_clientsession(hass)
        # Rate limit retry configuration
        self._max_retries = 3
        self._retry_delay_base = 2  # Base delay in seconds for exponential backoff

    async def _fetch_github_api(self, url: str) -> dict | None:
        """Fetch data from GitHub API with exponential backoff on rate limits.

        Args:
            url: GitHub API URL to fetch

        Returns:
            Parsed JSON response or None if all retries failed

        Implements exponential backoff for 429 (rate limit) responses.
        """
        for attempt in range(self._max_retries + 1):
            try:
                async with self._session.get(
                    url, timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    # Handle rate limiting with exponential backoff
                    if response.status == 429:
                        if attempt < self._max_retries:
                            # Calculate exponential backoff delay
                            delay = self._retry_delay_base ** (attempt + 1)
                            _LOGGER.warning(
                                "GitHub API rate limit hit (429). "
                                "Retrying in %d seconds (attempt %d/%d)",
                                delay,
                                attempt + 1,
                                self._max_retries,
                            )
                            await asyncio.sleep(delay)
                            continue
                        else:
                            _LOGGER.error(
                                "GitHub API rate limit exceeded after %d retries. "
                                "Please wait before trying again.",
                                self._max_retries,
                            )
                            return None

                    if response.status != 200:
                        _LOGGER.error(
                            "Failed to fetch from GitHub API: HTTP %s", response.status
                        )
                        return None

                    return await response.json()

            except TimeoutError:
                _LOGGER.error("Timeout fetching from GitHub API")
                return None
            except aiohttp.ClientError as err:
                _LOGGER.error("Error fetching from GitHub API: %s", err)
                return None

        return None

    async def get_latest_release(self, firmware_source: str) -> FirmwareRelease | None:
        """Get latest firmware release from GitHub with rate limit handling."""
        if firmware_source not in FIRMWARE_SOURCES:
            _LOGGER.error("Unknown firmware source: %s", firmware_source)
            return None

        source_info = FIRMWARE_SOURCES[firmware_source]
        api_url = source_info["api_url"]
        asset_pattern = source_info["asset_pattern"]

        # Use helper method with rate limit handling
        data = await self._fetch_github_api(api_url)
        if not data:
            return None

        try:
            # Find matching binary asset
            download_url = None
            firmware_filename = None
            for asset in data.get("assets", []):
                if re.match(asset_pattern, asset["name"]):
                    download_url = asset["browser_download_url"]
                    firmware_filename = asset["name"]
                    break

            if not download_url:
                _LOGGER.warning(
                    "No matching firmware binary found in release %s",
                    data.get("tag_name"),
                )
                return None

            # Try to find checksum from release body
            checksum, checksum_type = self._parse_checksum_from_release(
                data.get("body", ""), firmware_filename
            )

            return FirmwareRelease(
                version=data.get("tag_name", "unknown"),
                download_url=download_url,
                release_url=data.get("html_url", ""),
                release_notes=data.get("body"),
                published_at=data.get("published_at"),
                checksum=checksum,
                checksum_type=checksum_type,
            )

        except (KeyError, ValueError, TypeError) as err:
            _LOGGER.error("Error parsing firmware release data: %s", err)
            return None

    async def download_firmware(self, download_url: str) -> bytes | None:
        """Download firmware binary from URL.

        Args:
            download_url: HTTPS URL to download firmware from

        Returns:
            Firmware binary data if successful, None otherwise

        Security:
            Only HTTPS URLs are allowed to prevent man-in-the-middle attacks
        """
        # Security: Enforce HTTPS-only downloads
        if not download_url.startswith("https://"):
            _LOGGER.error(
                "SECURITY: Refusing to download firmware from non-HTTPS URL: %s. "
                "Only HTTPS URLs are allowed to prevent man-in-the-middle attacks.",
                download_url,
            )
            return None

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

        except TimeoutError:
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

                # Finalize OTA
                await self._finalize_ota(client)

                _LOGGER.info("Firmware flash completed successfully")
                return True

        except BleakError as err:
            _LOGGER.error("BLE error during firmware flash: %s", err)
            return False
        except TimeoutError:
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

    async def get_release_by_version(
        self, firmware_source: str, version: str
    ) -> FirmwareRelease | None:
        """Get a specific firmware release by version from GitHub.

        Args:
            firmware_source: The firmware source (pvvx or atc1441)
            version: The specific version to fetch (e.g., "v4.5")

        Returns:
            FirmwareRelease object if found, None otherwise
        """
        if firmware_source not in FIRMWARE_SOURCES:
            _LOGGER.error("Unknown firmware source: %s", firmware_source)
            return None

        source_info = FIRMWARE_SOURCES[firmware_source]
        repo = source_info["repo"]
        asset_pattern = source_info["asset_pattern"]

        # Build URL for specific release tag
        api_url = f"https://api.github.com/repos/{repo}/releases/tags/{version}"

        # For specific version lookup, we need to handle 404 specially
        # so we can't use the generic _fetch_github_api helper
        for attempt in range(self._max_retries + 1):
            try:
                async with self._session.get(
                    api_url, timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 404:
                        _LOGGER.warning("Version %s not found for %s", version, repo)
                        return None

                    # Handle rate limiting with exponential backoff
                    if response.status == 429:
                        if attempt < self._max_retries:
                            delay = self._retry_delay_base ** (attempt + 1)
                            _LOGGER.warning(
                                "GitHub API rate limit hit (429). "
                                "Retrying in %d seconds (attempt %d/%d)",
                                delay,
                                attempt + 1,
                                self._max_retries,
                            )
                            await asyncio.sleep(delay)
                            continue
                        else:
                            _LOGGER.error(
                                "GitHub API rate limit exceeded after %d retries",
                                self._max_retries,
                            )
                            return None

                    if response.status != 200:
                        _LOGGER.error(
                            "Failed to fetch release %s: HTTP %s",
                            version,
                            response.status,
                        )
                        return None

                    data = await response.json()
                    break  # Success, exit retry loop

            except TimeoutError:
                _LOGGER.error("Timeout fetching firmware release %s", version)
                return None
            except aiohttp.ClientError as err:
                _LOGGER.error("Error fetching firmware release %s: %s", version, err)
                return None
        else:
            # All retries exhausted
            return None

        try:
            # Find matching binary asset
            download_url = None
            firmware_filename = None
            for asset in data.get("assets", []):
                if re.match(asset_pattern, asset["name"]):
                    download_url = asset["browser_download_url"]
                    firmware_filename = asset["name"]
                    break

            if not download_url:
                _LOGGER.warning(
                    "No matching firmware binary found in release %s",
                    data.get("tag_name"),
                )
                return None

            # Try to find checksum from release body
            checksum, checksum_type = self._parse_checksum_from_release(
                data.get("body", ""), firmware_filename
            )

            return FirmwareRelease(
                version=data.get("tag_name", version),
                download_url=download_url,
                release_url=data.get("html_url", ""),
                release_notes=data.get("body"),
                published_at=data.get("published_at"),
                checksum=checksum,
                checksum_type=checksum_type,
            )

        except (KeyError, ValueError, TypeError) as err:
            _LOGGER.error(
                "Error parsing firmware release data for %s: %s", version, err
            )
            return None

    def _parse_checksum_from_release(
        self, release_body: str, firmware_filename: str | None
    ) -> tuple[str | None, str | None]:
        """Parse checksum from GitHub release body.

        Looks for common checksum patterns in release notes:
        - SHA256: <hash> <filename>
        - SHA512: <hash> <filename>
        - <hash> (if only one firmware file)

        Args:
            release_body: The release notes/body text
            firmware_filename: Name of the firmware file to find checksum for

        Returns:
            Tuple of (checksum, checksum_type) or (None, None) if not found
        """
        if not release_body or not firmware_filename:
            return None, None

        # Common SHA256 patterns
        # Format: <64 hex chars> <filename>
        sha256_pattern = rf"([a-fA-F0-9]{{64}})\s+{re.escape(firmware_filename)}"
        match = re.search(sha256_pattern, release_body)
        if match:
            return match.group(1).lower(), "sha256"

        # Format: SHA256(<filename>)= <hash>
        sha256_pattern2 = (
            rf"SHA256\s*\(\s*{re.escape(firmware_filename)}\s*\)\s*=\s*"
            r"([a-fA-F0-9]{64})"
        )
        match = re.search(sha256_pattern2, release_body, re.IGNORECASE)
        if match:
            return match.group(1).lower(), "sha256"

        # Common SHA512 patterns
        sha512_pattern = rf"([a-fA-F0-9]{{128}})\s+{re.escape(firmware_filename)}"
        match = re.search(sha512_pattern, release_body)
        if match:
            return match.group(1).lower(), "sha512"

        _LOGGER.debug(
            "No checksum found in release notes for %s. "
            "Firmware will be validated by size only.",
            firmware_filename,
        )
        return None, None

    def _validate_firmware_checksum(
        self, firmware_data: bytes, checksum: str | None, checksum_type: str | None
    ) -> bool:
        """Validate firmware checksum using strong cryptographic hashes.

        Only SHA256 and SHA512 are supported for security reasons.
        MD5 and SHA1 are rejected as they are cryptographically broken.

        Args:
            firmware_data: The firmware binary data
            checksum: Expected checksum value
            checksum_type: Type of checksum (must be sha256 or sha512)

        Returns:
            True if checksum matches or no checksum provided, False otherwise
        """
        if not checksum or not checksum_type:
            _LOGGER.warning(
                "No checksum provided for firmware validation. "
                "Firmware integrity cannot be verified. "
                "This is a security risk - firmware could be corrupted or "
                "tampered with."
            )
            return True

        checksum_type_lower = checksum_type.lower()

        # Reject weak hash algorithms
        if checksum_type_lower in ("md5", "sha1"):
            _LOGGER.error(
                "SECURITY: Rejecting firmware with %s checksum. "
                "%s is cryptographically broken and cannot guarantee "
                "firmware integrity. Only SHA256 and SHA512 are accepted.",
                checksum_type_lower.upper(),
                checksum_type_lower.upper(),
            )
            return False

        # Calculate checksum using approved algorithms
        try:
            if checksum_type_lower == "sha256":
                calculated = hashlib.sha256(firmware_data).hexdigest()
            elif checksum_type_lower == "sha512":
                calculated = hashlib.sha512(firmware_data).hexdigest()
            else:
                _LOGGER.error(
                    "Unsupported checksum type: %s. "
                    "Only SHA256 and SHA512 are supported.",
                    checksum_type,
                )
                return False

            if calculated.lower() != checksum.lower():
                _LOGGER.error(
                    "Firmware checksum mismatch! Expected %s, got %s. "
                    "Firmware may be corrupted or tampered with.",
                    checksum,
                    calculated,
                )
                return False

            _LOGGER.info(
                "Firmware checksum validated successfully using %s", checksum_type
            )
            return True

        except (ValueError, TypeError) as err:
            # Handle invalid checksum format or type conversion errors
            _LOGGER.error("Error calculating checksum: %s", err)
            return False

    async def apply_firmware_update(
        self,
        release: FirmwareRelease,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> bool:
        """Apply a firmware update to the device.

        This is the unified method for applying firmware updates, used by both
        the update entity and the apply_firmware service.

        Args:
            release: The firmware release to apply
            progress_callback: Optional callback for progress updates (current, total)

        Returns:
            True if successful, False otherwise

        Raises:
            HomeAssistantError: If firmware download or validation fails
        """
        _LOGGER.info(
            "Starting firmware update for device %s: %s",
            self.mac_address,
            release.version,
        )

        # Download firmware
        firmware_data = await self.download_firmware(release.download_url)

        if not firmware_data:
            raise HomeAssistantError("Failed to download firmware")

        # Validate checksum if provided
        if not self._validate_firmware_checksum(
            firmware_data, release.checksum, release.checksum_type
        ):
            raise HomeAssistantError(
                "Firmware checksum validation failed. "
                "Downloaded file may be corrupted or tampered with."
            )

        # Flash firmware with progress tracking
        # Wrap the progress callback to handle errors gracefully
        def safe_progress_callback(current: int, total: int) -> None:
            """Safely call progress callback with error handling."""
            if progress_callback:
                try:
                    # Prevent division by zero
                    if total > 0:
                        progress_callback(current, total)
                except Exception as err:
                    # Log at warning level so callback errors are visible
                    _LOGGER.warning(
                        "Error in progress callback (current=%d, total=%d): %s",
                        current,
                        total,
                        err,
                    )

        success = await self.flash_firmware(firmware_data, safe_progress_callback)

        if not success:
            raise HomeAssistantError("Firmware flash failed")

        _LOGGER.info(
            "Successfully applied firmware %s to device %s",
            release.version,
            self.mac_address,
        )
        return True

    async def _read_version_from_gatt(self, client: BleakClient) -> str | None:
        """Read and validate firmware version from GATT characteristic.

        Args:
            client: Connected BleakClient instance

        Returns:
            Validated version string or None if reading/validation fails
        """
        if not client.is_connected:
            _LOGGER.debug(
                "Client not connected for %s", self.mac_address
            )
            return None

        # Read Software Revision String (0x2A28)
        software_revision = await client.read_gatt_char(
            CHAR_UUID_SOFTWARE_REVISION
        )

        # Check for None or empty response
        if not software_revision:
            _LOGGER.debug(
                "Empty or None response from Software Revision for %s",
                self.mac_address,
            )
            return None

        # Decode bytes to string with strict UTF-8 validation
        try:
            version_str = software_revision.decode("utf-8").strip()
        except UnicodeDecodeError as err:
            _LOGGER.debug(
                "Invalid UTF-8 in version string for %s: %s",
                self.mac_address,
                err,
            )
            return None

        # Check for empty string after decode
        if not version_str:
            _LOGGER.debug(
                "Empty version string after decode for %s",
                self.mac_address,
            )
            return None

        # Check for excessive length (potential attack or corruption)
        if len(version_str) > MAX_VERSION_LENGTH:
            _LOGGER.warning(
                "Version string exceeds max length (%d > %d) for %s",
                len(version_str),
                MAX_VERSION_LENGTH,
                self.mac_address,
            )
            return None

        # Remove version prefix if present (e.g., "V4.3" -> "4.3")
        if version_str and version_str[0] in VERSION_PREFIX_CHARS:
            version_str = version_str[1:]

        # Validate version format with regex
        if not re.match(VERSION_VALIDATION_PATTERN, version_str):
            _LOGGER.debug(
                "Version string '%s' does not match expected format for %s",
                version_str,
                self.mac_address,
            )
            return None

        _LOGGER.info(
            "Detected firmware version %s from Device Information Service",
            version_str,
        )
        return version_str

    async def get_current_version(self) -> str | None:
        """Get current firmware version by reading Device Information Service.

        Connects to the device and reads the Software Revision String characteristic
        from the standard BLE Device Information Service (0x180A), just like the
        web flasher tool does.

        Version Detection Strategy:
        1. Connect to the device via BLE
        2. Read Software Revision String characteristic (0x2A28)
        3. Parse version string (e.g., "V4.3" -> "4.3")
        4. Fallback to manufacturer data if GATT read fails

        Returns:
            str: Version string (e.g., "4.3") if successfully detected
            None: If device not available, connection fails, or reading fails

        Note:
            This method connects to the device to read GATT characteristics.
            The coordinator calls this method every UPDATE_CHECK_INTERVAL (6 hours),
            so connection overhead is minimal. GATT characteristic reading is more
            reliable than parsing advertisement data, ensuring accurate version
            detection even when manufacturer data format varies between firmware
            versions.
        """
        try:
            ble_device = bluetooth.async_ble_device_from_address(
                self.hass, self.mac_address, connectable=True
            )

            if not ble_device:
                _LOGGER.debug("Device %s not available", self.mac_address)
                return None

            # Try to read version from Device Information Service
            try:
                async with BleakClient(
                    ble_device, timeout=GATT_CONNECTION_TIMEOUT
                ) as client:
                    version = await self._read_version_from_gatt(client)
                    if version:
                        return version
                    # If helper returns None, fall through to manufacturer data

            except (BleakError, TimeoutError) as err:
                # Use DEBUG level for expected fallback scenarios
                # (characteristic not found)
                # Use WARNING level for unexpected errors
                # (timeout, connection issues)
                if isinstance(err, BleakError) and "not found" in str(err).lower():
                    _LOGGER.debug(
                        "Software Revision characteristic not found for %s. "
                        "Falling back to manufacturer data parsing.",
                        self.mac_address,
                    )
                else:
                    _LOGGER.warning(
                        "Could not read version from Device Information Service for "
                        "%s: %s. Falling back to manufacturer data parsing.",
                        self.mac_address,
                        err,
                    )
                # Fall through to try manufacturer data

            # Fallback: Try to parse version from manufacturer data
            service_info = bluetooth.async_last_service_info(
                self.hass, self.mac_address, connectable=True
            )

            if service_info and service_info.manufacturer_data:
                for _mfr_id, data in service_info.manufacturer_data.items():
                    try:
                        if len(data) < MIN_MANUFACTURER_DATA_LEN:
                            continue

                        major = data[VERSION_BYTE_MAJOR]
                        minor = data[VERSION_BYTE_MINOR]

                        if not (0 <= major <= 99 and 0 <= minor <= 99):
                            continue

                        version_str = f"{major}.{minor}"
                        _LOGGER.debug(
                            "Detected version %s from manufacturer data (fallback)",
                            version_str,
                        )
                        return version_str
                    except (IndexError, KeyError, ValueError, TypeError):
                        continue

            _LOGGER.debug(
                "Could not determine firmware version for %s", self.mac_address
            )
            return None

        except (BleakError, HomeAssistantError) as err:
            _LOGGER.debug("Error getting current version: %s", err)
            return None
