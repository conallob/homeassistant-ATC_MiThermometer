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
from bleak_retry_connector import establish_connection
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CHAR_UUID_OTA,
    CHAR_UUID_SOFTWARE_REVISION,
    CONNECT_TIMEOUT,
    FIRMWARE_SOURCES,
    MAX_FIRMWARE_SIZE,
    MAX_VERSION_LENGTH,
    MIN_FIRMWARE_SIZE,
    MIN_MANUFACTURER_DATA_LEN,
    OTA_CHUNK_DELAY,
    OTA_CMD_END,
    OTA_CMD_START,
    OTA_COMMAND_DELAY,
    OTA_PACKET_PAYLOAD_SIZE,
    OTA_SECTOR_SIZE,
    OTA_TRAILER_SEQ,
    OTA_TRANSFER_TIMEOUT,
    VERSION_BYTE_MAJOR,
    VERSION_BYTE_MINOR,
    VERSION_PREFIX_CHARS,
    VERSION_VALIDATION_PATTERN,
)

_CRC16_CCITT_POLY = 0x1021
_CRC16_CCITT_INIT = 0xFFFF


def _crc16_ccitt(data: bytes) -> int:
    """Compute CRC16-CCITT (poly 0x1021, init 0xFFFF) over data.

    The Telink OTA GATT service (ble_ll_ota.h) declares a crc16() helper
    but its implementation is compiled into a closed-source vendor library,
    so the exact algorithm can't be read from source. CRC16-CCITT is the
    conventional choice used across Telink SDK OTA reference material.
    """
    crc = _CRC16_CCITT_INIT
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ _CRC16_CCITT_POLY) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


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
        # Only warn once about a missing connectable BLE route; some users
        # intentionally only ever see this device passively (e.g. via a
        # BTHome-only Bluetooth proxy) and don't need a warning every
        # UPDATE_CHECK_INTERVAL poll.
        self._connectable_warning_logged = False

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
        """Flash firmware to device via the Telink legacy BLE OTA protocol.

        Args:
            firmware_data: The firmware binary data
            progress_callback: Optional callback for progress updates (current, total)

        Returns:
            True if successful, False otherwise
        """
        _LOGGER.info("Starting firmware flash for device %s", self.mac_address)

        if not MIN_FIRMWARE_SIZE <= len(firmware_data) <= MAX_FIRMWARE_SIZE:
            _LOGGER.error(
                "Refusing to flash firmware of invalid size: %d bytes "
                "(expected %d-%d)",
                len(firmware_data),
                MIN_FIRMWARE_SIZE,
                MAX_FIRMWARE_SIZE,
            )
            return False

        try:
            # Get BLE device
            ble_device = bluetooth.async_ble_device_from_address(
                self.hass, self.mac_address, connectable=True
            )

            if not ble_device:
                raise HomeAssistantError(f"Device {self.mac_address} not found")

            # establish_connection retries with backoff on the normal transient
            # BLE failures (busy adapter/proxy, stale cache, etc.) instead of
            # failing on the first attempt like a bare BleakClient().connect()
            # would - see https://github.com/Bluetooth-Devices/bleak-retry-connector
            # CONNECT_TIMEOUT bounds its retries to a predictable ceiling; see
            # the constant's comment for why that matters.
            client = await asyncio.wait_for(
                establish_connection(BleakClient, ble_device, self.mac_address),
                timeout=CONNECT_TIMEOUT,
            )
            try:
                _LOGGER.info("Connected to device %s", self.mac_address)

                await asyncio.wait_for(
                    self._transfer_firmware(client, firmware_data, progress_callback),
                    timeout=OTA_TRANSFER_TIMEOUT,
                )

                _LOGGER.info(
                    "Firmware data transfer completed for %s; device will validate "
                    "and reboot if the CRC checks pass",
                    self.mac_address,
                )
                return True
            finally:
                await self._safe_disconnect(client)

        except BleakError as err:
            _LOGGER.error("BLE error during firmware flash: %s", err)
            return False
        except TimeoutError:
            _LOGGER.error("Timeout during firmware flash")
            return False
        except HomeAssistantError as err:
            _LOGGER.error("Home Assistant error during firmware flash: %s", err)
            return False

    async def _safe_disconnect(self, client: BleakClient) -> None:
        """Disconnect without letting a disconnect-time error mask a result.

        A failure while disconnecting (e.g. the link already dropped) isn't
        something the caller can act on, and letting it propagate out of a
        connection block's finally would override whatever the try body
        already produced - including a version that was already read
        successfully in get_current_version().
        """
        try:
            await client.disconnect()
        except (BleakError, OSError) as err:
            _LOGGER.debug("Error disconnecting from %s: %s", self.mac_address, err)

    async def _transfer_firmware(
        self,
        client: BleakClient,
        firmware_data: bytes,
        progress_callback: Callable[[int, int], None] | None,
    ) -> None:
        """Run the OTA start/sector/end sequence, bounded by OTA_TRANSFER_TIMEOUT."""
        await self._send_ota_start(client, len(firmware_data))

        total_bytes = len(firmware_data)
        bytes_sent = 0

        for sector_index, sector_offset in enumerate(
            range(0, total_bytes, OTA_SECTOR_SIZE)
        ):
            sector = firmware_data[sector_offset : sector_offset + OTA_SECTOR_SIZE]
            bytes_sent = await self._send_ota_sector(
                client,
                sector_index,
                sector,
                bytes_sent,
                total_bytes,
                progress_callback,
            )

        await self._send_ota_end(client)

    async def _send_ota_sector(
        self,
        client: BleakClient,
        sector_index: int,
        sector: bytes,
        bytes_sent: int,
        total_bytes: int,
        progress_callback: Callable[[int, int], None] | None,
    ) -> int:
        """Send one 4K sector's data packets plus its CRC trailer packet."""
        if sector_index > 0xFEFF:
            # Not reachable today: MAX_FIRMWARE_SIZE (512K) caps sector count
            # at 128, far under this limit. Guards against a future increase
            # to MAX_FIRMWARE_SIZE colliding with the 0xFF00-0xFFFF command
            # range reserved for OTA_CMD_START/OTA_CMD_END.
            raise HomeAssistantError("Firmware too large for OTA sector indexing")

        for seq, chunk_offset in enumerate(
            range(0, len(sector), OTA_PACKET_PAYLOAD_SIZE)
        ):
            if seq >= OTA_TRAILER_SEQ:
                # Not reachable today: a 4K sector needs at most 241 packets
                # of OTA_PACKET_PAYLOAD_SIZE (17) bytes, far under 0xFF (255).
                # Guards against OTA_SECTOR_SIZE or OTA_PACKET_PAYLOAD_SIZE
                # ever changing such that a sector collides with
                # OTA_TRAILER_SEQ, the sentinel that marks the trailer packet.
                raise HomeAssistantError("Sector produced too many OTA packets")

            chunk = sector[chunk_offset : chunk_offset + OTA_PACKET_PAYLOAD_SIZE]
            payload = chunk.ljust(OTA_PACKET_PAYLOAD_SIZE, b"\xff")
            packet = sector_index.to_bytes(2, "little") + bytes([seq]) + payload
            await client.write_gatt_char(CHAR_UUID_OTA, packet, response=False)

            bytes_sent += len(chunk)
            if progress_callback:
                progress_callback(bytes_sent, total_bytes)

            await asyncio.sleep(OTA_CHUNK_DELAY)

        # Sector trailer packet: zero-padded payload with the sector's CRC16
        # in the final 2 bytes, so the device can validate the sector before
        # committing it to flash. The final sector of an image whose size
        # isn't a multiple of OTA_SECTOR_SIZE is shorter than 4096 bytes here;
        # pad it to a full sector with 0xff (erased-flash convention) before
        # computing the CRC, matching the padding already used for individual
        # packet payloads (see .ljust(..., b"\xff") above) - the device's own
        # per-sector CRC almost certainly covers the full physical 4K flash
        # page, treating the unwritten tail as erased 0xff, not a short slice.
        sector_crc = _crc16_ccitt(sector.ljust(OTA_SECTOR_SIZE, b"\xff"))
        trailer_payload = bytes(OTA_PACKET_PAYLOAD_SIZE - 2) + sector_crc.to_bytes(
            2, "little"
        )
        trailer_packet = (
            sector_index.to_bytes(2, "little")
            + bytes([OTA_TRAILER_SEQ])
            + trailer_payload
        )
        await client.write_gatt_char(CHAR_UUID_OTA, trailer_packet, response=False)
        await asyncio.sleep(OTA_CHUNK_DELAY)

        return bytes_sent

    async def _send_ota_start(self, client: BleakClient, firmware_size: int) -> None:
        """Send the OTA start command with the total firmware size."""
        payload = firmware_size.to_bytes(4, "little").ljust(16, b"\x00")
        packet = self._build_ota_command(OTA_CMD_START, payload)
        await client.write_gatt_char(CHAR_UUID_OTA, packet, response=False)
        await asyncio.sleep(OTA_COMMAND_DELAY)
        _LOGGER.debug("OTA start sent (firmware size %d bytes)", firmware_size)

    async def _send_ota_end(self, client: BleakClient) -> None:
        """Send the OTA end command to finalize the update."""
        packet = self._build_ota_command(OTA_CMD_END, bytes(16))
        await client.write_gatt_char(CHAR_UUID_OTA, packet, response=False)
        await asyncio.sleep(OTA_COMMAND_DELAY)
        _LOGGER.debug("OTA end sent")

    @staticmethod
    def _build_ota_command(command_id: int, payload: bytes) -> bytes:
        """Build a 20-byte OTA command packet: id + 16-byte payload + CRC16.

        Command packets and sector data packets share the same 2-byte
        leading field (command_id here, sector_index in _send_ota_sector),
        which is why sector_index is kept out of the reserved 0xFF00-0xFFFF
        range. How the device itself tells the two packet kinds apart
        (this leading field, packet length, or separate state) isn't
        confirmed here - it's inferred from ext_ota.h's command IDs, not
        verified against real hardware.
        """
        body = command_id.to_bytes(2, "little") + payload
        return body + _crc16_ccitt(body).to_bytes(2, "little")

    async def get_release_by_version(
        self, firmware_source: str, version: str
    ) -> FirmwareRelease | None:
        """Get a specific firmware release by version from GitHub.

        Args:
            firmware_source: The firmware source (pvvx or atc1441)
            version: The specific version to fetch (e.g., "v4.5")

        Returns:
            FirmwareRelease object if a release tagged `version` exists,
            None only if GitHub confirmed (via HTTP 404) that it doesn't.

        Raises:
            HomeAssistantError: If the lookup itself couldn't be completed
                (network error, timeout, rate limit, non-404 HTTP error).
                This is deliberately distinct from returning None: callers
                use None to mean "confirmed no such release exists" and
                would otherwise tell users that a version doesn't exist
                when the real cause was a transient GitHub API failure.
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
                            raise HomeAssistantError(
                                f"GitHub API rate limit exceeded after "
                                f"{self._max_retries} retries while checking "
                                f"for release {version} of {repo}"
                            )

                    if response.status != 200:
                        raise HomeAssistantError(
                            f"Failed to check for release {version} of "
                            f"{repo}: GitHub API returned "
                            f"HTTP {response.status}"
                        )

                    data = await response.json()
                    break  # Success, exit retry loop

            except TimeoutError as err:
                raise HomeAssistantError(
                    f"Timeout checking for release {version} of {repo}"
                ) from err
            except aiohttp.ClientError as err:
                raise HomeAssistantError(
                    f"Error checking for release {version} of {repo}: {err}"
                ) from err
        else:  # pragma: no cover
            # Not expected to be reachable given the branches above (every
            # path either returns, raises, or continues toward a final
            # raise), but fail loudly rather than silently claim "not
            # found" if it somehow is.
            raise HomeAssistantError(
                f"Failed to check for release {version} of {repo} after "
                f"{self._max_retries} retries"
            )

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
            _LOGGER.debug("Client not connected for %s", self.mac_address)
            return None

        # Read Software Revision String (0x2A28)
        software_revision = await client.read_gatt_char(CHAR_UUID_SOFTWARE_REVISION)

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
                log = (
                    _LOGGER.warning
                    if not self._connectable_warning_logged
                    else _LOGGER.debug
                )
                log(
                    "No connectable Bluetooth route to %s. The device may only be "
                    "visible via a passive/non-connectable Bluetooth proxy or "
                    "adapter - firmware version detection and OTA updates require "
                    "an active (connectable) Bluetooth connection to the device.",
                    self.mac_address,
                )
                self._connectable_warning_logged = True
                return None

            # Connectable again - reset so a *new* connectivity regression
            # (e.g. the proxy flapping) is still surfaced at warning level
            # rather than staying silent at debug forever.
            self._connectable_warning_logged = False

            # Try to read version from Device Information Service.
            # establish_connection retries with backoff on the normal
            # transient BLE failures instead of failing on the first
            # attempt like a bare BleakClient().connect() would - see
            # https://github.com/Bluetooth-Devices/bleak-retry-connector
            # CONNECT_TIMEOUT bounds its retries to a predictable ceiling;
            # see the constant's comment for why that matters.
            try:
                client = await asyncio.wait_for(
                    establish_connection(BleakClient, ble_device, self.mac_address),
                    timeout=CONNECT_TIMEOUT,
                )
                try:
                    version = await self._read_version_from_gatt(client)
                    if version:
                        return version
                    # If helper returns None, fall through to manufacturer data
                finally:
                    await self._safe_disconnect(client)

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
