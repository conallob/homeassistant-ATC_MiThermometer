"""Test the firmware module."""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from bleak import BleakClient, BleakError
from homeassistant.core import HomeAssistant

from custom_components.atc_mithermometer.const import (
    CONNECT_TIMEOUT,
    FIRMWARE_SOURCE_ATC1441,
    FIRMWARE_SOURCE_PVVX,
    MAX_FIRMWARE_SIZE,
    MIN_FIRMWARE_SIZE,
    OTA_SECTOR_SIZE,
)
from custom_components.atc_mithermometer.firmware import (
    FirmwareManager,
    FirmwareRelease,
    _crc16_ccitt,
)


class TestCrc16Ccitt:
    """Test the CRC16-CCITT helper used to frame OTA packets."""

    def test_empty_input_is_init_value(self):
        """CRC of no data is just the initial register value."""
        assert _crc16_ccitt(b"") == 0xFFFF

    def test_known_vector(self):
        """The string b'123456789' is the standard CRC16-CCITT test vector."""
        assert _crc16_ccitt(b"123456789") == 0x29B1

    def test_single_bit_change_changes_crc(self):
        """A single changed byte must produce a different CRC."""
        assert _crc16_ccitt(b"\x00" * 16) != _crc16_ccitt(b"\x00" * 15 + b"\x01")

    def test_result_fits_in_16_bits(self):
        """CRC must always be a valid u16."""
        assert 0 <= _crc16_ccitt(bytes(range(256))) <= 0xFFFF


@pytest.fixture
def firmware_manager(hass: HomeAssistant):
    """Create a firmware manager instance."""
    # Mock async_get_clientsession to avoid event loop issues in __init__
    mock_session = MagicMock()
    with patch(
        "custom_components.atc_mithermometer.firmware.async_get_clientsession",
        return_value=mock_session,
    ):
        manager = FirmwareManager(hass, "AA:BB:CC:DD:EE:FF")
    return manager


@pytest.fixture
def mock_github_release_data():
    """Create mock GitHub release data."""
    return {
        "tag_name": "v1.2.3",
        "html_url": "https://github.com/pvvx/ATC_MiThermometer/releases/tag/v1.2.3",
        "body": "Release notes here",
        "published_at": "2024-01-01T00:00:00Z",
        "assets": [
            {
                "name": "ATC_v1.2.3.bin",
                "browser_download_url": "https://github.com/pvvx/ATC_MiThermometer/releases/download/v1.2.3/ATC_v1.2.3.bin",
            }
        ],
    }


class TestFirmwareRelease:
    """Test FirmwareRelease dataclass."""

    def test_firmware_release_creation(self):
        """Test creating a FirmwareRelease."""
        release = FirmwareRelease(
            version="v1.2.3",
            download_url="https://example.com/firmware.bin",
            release_url="https://example.com/releases/v1.2.3",
        )

        assert release.version == "v1.2.3"
        assert release.download_url == "https://example.com/firmware.bin"
        assert release.release_url == "https://example.com/releases/v1.2.3"
        assert release.release_notes is None
        assert release.published_at is None

    def test_firmware_release_with_optional_fields(self):
        """Test creating a FirmwareRelease with optional fields."""
        release = FirmwareRelease(
            version="v1.2.3",
            download_url="https://example.com/firmware.bin",
            release_url="https://example.com/releases/v1.2.3",
            release_notes="Test notes",
            published_at="2024-01-01",
        )

        assert release.release_notes == "Test notes"
        assert release.published_at == "2024-01-01"


class TestFirmwareManager:
    """Test FirmwareManager class."""

    def test_firmware_manager_init(self, hass: HomeAssistant):
        """Test firmware manager initialization."""
        # Mock async_get_clientsession to avoid event loop issues
        mock_session = MagicMock()
        with patch(
            "custom_components.atc_mithermometer.firmware.async_get_clientsession",
            return_value=mock_session,
        ):
            manager = FirmwareManager(hass, "AA:BB:CC:DD:EE:FF")

        assert manager.hass == hass
        assert manager.mac_address == "AA:BB:CC:DD:EE:FF"
        assert manager._session is not None

    async def test_get_latest_release_pvvx(
        self, firmware_manager, mock_github_release_data
    ):
        """Test getting latest release for pvvx firmware."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_github_release_data)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch.object(
            firmware_manager._session,
            "get",
            return_value=mock_response,
        ) as mock_get:
            release = await firmware_manager.get_latest_release(FIRMWARE_SOURCE_PVVX)

            assert release is not None
            assert release.version == "v1.2.3"
            assert "ATC_v1.2.3.bin" in release.download_url
            assert release.release_notes == "Release notes here"
            assert release.published_at == "2024-01-01T00:00:00Z"

            # Verify the API was called correctly
            mock_get.assert_called_once()
            mock_response.json.assert_called_once()

    async def test_get_latest_release_atc1441(self, firmware_manager):
        """Test getting latest release for atc1441 firmware."""
        mock_data = {
            "tag_name": "v2.0.0",
            "html_url": "https://github.com/atc1441/ATC_MiThermometer/releases/tag/v2.0.0",
            "body": "ATC1441 release notes",
            "published_at": "2024-02-01T00:00:00Z",
            "assets": [
                {
                    "name": "firmware.bin",
                    "browser_download_url": "https://github.com/atc1441/ATC_MiThermometer/releases/download/v2.0.0/firmware.bin",
                }
            ],
        }

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_data)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch.object(
            firmware_manager._session,
            "get",
            return_value=mock_response,
        ) as mock_get:
            release = await firmware_manager.get_latest_release(FIRMWARE_SOURCE_ATC1441)

            assert release is not None
            assert release.version == "v2.0.0"
            assert "firmware.bin" in release.download_url

            # Verify the API was called
            mock_get.assert_called_once()
            mock_response.json.assert_called_once()

    async def test_get_latest_release_unknown_source(self, firmware_manager):
        """Test getting release with unknown firmware source."""
        release = await firmware_manager.get_latest_release("unknown_source")

        assert release is None

    async def test_get_latest_release_http_error(self, firmware_manager):
        """Test handling HTTP error when fetching release."""
        mock_response = AsyncMock()
        mock_response.status = 404
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch.object(
            firmware_manager._session,
            "get",
            return_value=mock_response,
        ) as mock_get:
            release = await firmware_manager.get_latest_release(FIRMWARE_SOURCE_PVVX)

            assert release is None
            mock_get.assert_called_once()

    async def test_get_latest_release_timeout(self, firmware_manager):
        """Test handling timeout when fetching release."""
        with patch.object(
            firmware_manager._session,
            "get",
            side_effect=asyncio.TimeoutError(),
        ) as mock_get:
            release = await firmware_manager.get_latest_release(FIRMWARE_SOURCE_PVVX)

            assert release is None
            mock_get.assert_called_once()

    async def test_get_latest_release_network_error(self, firmware_manager):
        """Test handling network error when fetching release."""
        with patch.object(
            firmware_manager._session,
            "get",
            side_effect=aiohttp.ClientError(),
        ) as mock_get:
            release = await firmware_manager.get_latest_release(FIRMWARE_SOURCE_PVVX)

            assert release is None
            mock_get.assert_called_once()

    async def test_get_latest_release_no_matching_asset(
        self, firmware_manager, mock_github_release_data
    ):
        """Test handling no matching firmware asset."""
        mock_github_release_data["assets"] = [
            {
                "name": "other_file.txt",
                "browser_download_url": "https://example.com/other_file.txt",
            }
        ]

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_github_release_data)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch.object(
            firmware_manager._session,
            "get",
            return_value=mock_response,
        ) as mock_get:
            release = await firmware_manager.get_latest_release(FIRMWARE_SOURCE_PVVX)

            assert release is None
            mock_get.assert_called_once()
            mock_response.json.assert_called_once()

    async def test_get_latest_release_malformed_data(self, firmware_manager):
        """Test handling malformed release data."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"malformed": "data"})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch.object(
            firmware_manager._session,
            "get",
            return_value=mock_response,
        ) as mock_get:
            release = await firmware_manager.get_latest_release(FIRMWARE_SOURCE_PVVX)

            assert release is None
            mock_get.assert_called_once()
            mock_response.json.assert_called_once()

    async def test_download_firmware_success(self, firmware_manager):
        """Test successful firmware download."""
        firmware_data = b"x" * 10000  # Valid size

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.read = AsyncMock(return_value=firmware_data)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch.object(
            firmware_manager._session,
            "get",
            return_value=mock_response,
        ) as mock_get:
            result = await firmware_manager.download_firmware(
                "https://example.com/firmware.bin"
            )

            assert result == firmware_data
            mock_get.assert_called_once_with(
                "https://example.com/firmware.bin",
                timeout=aiohttp.ClientTimeout(total=60)
            )
            mock_response.read.assert_called_once()

    async def test_download_firmware_http_error(self, firmware_manager):
        """Test firmware download with HTTP error."""
        mock_response = AsyncMock()
        mock_response.status = 404
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch.object(
            firmware_manager._session,
            "get",
            return_value=mock_response,
        ) as mock_get:
            result = await firmware_manager.download_firmware(
                "https://example.com/firmware.bin"
            )

            assert result is None
            mock_get.assert_called_once_with(
                "https://example.com/firmware.bin",
                timeout=aiohttp.ClientTimeout(total=60)
            )

    async def test_download_firmware_too_small(self, firmware_manager):
        """Test firmware download with file too small."""
        firmware_data = b"x" * (MIN_FIRMWARE_SIZE - 1)

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.read = AsyncMock(return_value=firmware_data)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch.object(
            firmware_manager._session,
            "get",
            return_value=mock_response,
        ) as mock_get:
            result = await firmware_manager.download_firmware(
                "https://example.com/firmware.bin"
            )

            assert result is None
            mock_get.assert_called_once_with(
                "https://example.com/firmware.bin",
                timeout=aiohttp.ClientTimeout(total=60)
            )
            mock_response.read.assert_called_once()

    async def test_download_firmware_too_large(self, firmware_manager):
        """Test firmware download with file too large."""
        firmware_data = b"x" * (MAX_FIRMWARE_SIZE + 1)

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.read = AsyncMock(return_value=firmware_data)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch.object(
            firmware_manager._session,
            "get",
            return_value=mock_response,
        ) as mock_get:
            result = await firmware_manager.download_firmware(
                "https://example.com/firmware.bin"
            )

            assert result is None
            mock_get.assert_called_once_with(
                "https://example.com/firmware.bin",
                timeout=aiohttp.ClientTimeout(total=60)
            )
            mock_response.read.assert_called_once()

    async def test_download_firmware_timeout(self, firmware_manager):
        """Test firmware download timeout."""
        with patch.object(
            firmware_manager._session,
            "get",
            side_effect=asyncio.TimeoutError(),
        ) as mock_get:
            result = await firmware_manager.download_firmware(
                "https://example.com/firmware.bin"
            )

            assert result is None
            mock_get.assert_called_once_with(
                "https://example.com/firmware.bin",
                timeout=aiohttp.ClientTimeout(total=60)
            )

    async def test_download_firmware_network_error(self, firmware_manager):
        """Test firmware download network error."""
        with patch.object(
            firmware_manager._session,
            "get",
            side_effect=aiohttp.ClientError(),
        ) as mock_get:
            result = await firmware_manager.download_firmware(
                "https://example.com/firmware.bin"
            )

            assert result is None
            mock_get.assert_called_once_with(
                "https://example.com/firmware.bin",
                timeout=aiohttp.ClientTimeout(total=60)
            )

    async def test_flash_firmware_success(self, firmware_manager):
        """Test successful firmware flash."""
        firmware_data = b"x" * MIN_FIRMWARE_SIZE

        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = True
        mock_client.write_gatt_char = AsyncMock()
        mock_client.disconnect = AsyncMock()

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ) as mock_get_device,
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(return_value=mock_client),
            ) as mock_bleak,
        ):
            result = await firmware_manager.flash_firmware(firmware_data)

            assert result is True
            mock_get_device.assert_called_once()
            mock_bleak.assert_called_once()
            assert mock_client.write_gatt_char.called
            mock_client.disconnect.assert_called_once()

    async def test_flash_firmware_disconnects_even_on_transfer_error(
        self, firmware_manager
    ):
        """The connection must be released even if the transfer itself fails.

        establish_connection() doesn't manage disconnection as a context
        manager, so this relies on the try/finally in flash_firmware() -
        a transfer error must not leak the connection.
        """
        firmware_data = b"x" * MIN_FIRMWARE_SIZE

        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = True
        mock_client.write_gatt_char = AsyncMock(side_effect=BleakError("write failed"))
        mock_client.disconnect = AsyncMock()

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(return_value=mock_client),
            ),
        ):
            result = await firmware_manager.flash_firmware(firmware_data)

        assert result is False
        mock_client.disconnect.assert_called_once()

    async def test_flash_firmware_disconnect_error_does_not_mask_result(
        self, firmware_manager
    ):
        """A disconnect-time error must not override a real result.

        If the link already dropped by the time we call disconnect(), that
        raising is not something the caller can act on - it must not
        replace a successful flash with a failure (or vice versa hide a
        real failure), which a bare `finally: await client.disconnect()`
        would otherwise do.
        """
        firmware_data = b"x" * MIN_FIRMWARE_SIZE

        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = True
        mock_client.write_gatt_char = AsyncMock()
        mock_client.disconnect = AsyncMock(
            side_effect=BleakError("already disconnected")
        )

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(return_value=mock_client),
            ),
        ):
            result = await firmware_manager.flash_firmware(firmware_data)

        assert result is True
        mock_client.disconnect.assert_called_once()

    async def test_flash_firmware_connect_is_bounded_by_connect_timeout(
        self, firmware_manager
    ):
        """establish_connection() must be wrapped with CONNECT_TIMEOUT.

        Regression test: bleak_retry_connector's own retry accounting
        tracks timeouts and "transient" errors as separate budgets, so a
        marginal device can end up retrying far past its documented
        default of 4 attempts - observed in production running 9-10
        retries, multiple minutes, for a single connection attempt. That
        was enough for Home Assistant to cancel an entire config entry's
        setup, not just fail one reading. asyncio.wait_for(CONNECT_TIMEOUT)
        around the connect call is the fix, and must not regress.
        """
        firmware_data = b"x" * MIN_FIRMWARE_SIZE

        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = True
        mock_client.write_gatt_char = AsyncMock()
        mock_client.disconnect = AsyncMock()

        real_wait_for = asyncio.wait_for
        wait_for_timeouts = []

        async def spy_wait_for(aw, timeout):
            wait_for_timeouts.append(timeout)
            return await real_wait_for(aw, timeout=timeout)

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(return_value=mock_client),
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.asyncio.wait_for",
                side_effect=spy_wait_for,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.asyncio.sleep",
                new=AsyncMock(),
            ),
        ):
            result = await firmware_manager.flash_firmware(firmware_data)

        assert result is True
        # First wait_for call wraps the connect; the second wraps the OTA
        # transfer phase (OTA_TRANSFER_TIMEOUT) - order matters here.
        assert wait_for_timeouts[0] == CONNECT_TIMEOUT

    async def test_flash_firmware_with_progress_callback(self, firmware_manager):
        """Test firmware flash with progress callback."""
        firmware_data = b"x" * MIN_FIRMWARE_SIZE

        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = True
        mock_client.write_gatt_char = AsyncMock()
        mock_client.disconnect = AsyncMock()

        progress_calls = []

        def progress_callback(current, total):
            progress_calls.append((current, total))

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(return_value=mock_client),
            ),
        ):
            result = await firmware_manager.flash_firmware(
                firmware_data, progress_callback
            )

            assert result is True
            assert len(progress_calls) > 0
            # Check that progress was reported
            assert progress_calls[-1][0] == progress_calls[-1][1]  # 100%

    async def test_flash_firmware_device_not_found(self, firmware_manager):
        """Test firmware flash when device not found."""
        firmware_data = b"x" * MIN_FIRMWARE_SIZE

        with patch(
            "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
            return_value=None,
        ) as mock_get_device:
            result = await firmware_manager.flash_firmware(firmware_data)

            assert result is False
            mock_get_device.assert_called_once()

    async def test_flash_firmware_connection_failed(self, firmware_manager):
        """Test firmware flash when establish_connection can't connect.

        establish_connection() only ever returns an already-connected
        client - on failure (after exhausting its own retries) it raises,
        it never hands back a client with is_connected=False.
        """
        firmware_data = b"x" * MIN_FIRMWARE_SIZE

        mock_ble_device = MagicMock()

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ) as mock_get_device,
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(side_effect=BleakError("Failed to connect after 4 attempts")),
            ) as mock_bleak,
        ):
            result = await firmware_manager.flash_firmware(firmware_data)

            assert result is False
            mock_get_device.assert_called_once()
            mock_bleak.assert_called_once()

    async def test_flash_firmware_ble_error(self, firmware_manager):
        """Test firmware flash with BLE error."""
        firmware_data = b"x" * MIN_FIRMWARE_SIZE

        mock_ble_device = MagicMock()

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ) as mock_get_device,
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                side_effect=BleakError("Connection failed"),
            ) as mock_bleak,
        ):
            result = await firmware_manager.flash_firmware(firmware_data)

            assert result is False
            mock_get_device.assert_called_once()
            mock_bleak.assert_called_once()

    async def test_flash_firmware_timeout(self, firmware_manager):
        """Test firmware flash timeout."""
        firmware_data = b"x" * MIN_FIRMWARE_SIZE

        mock_ble_device = MagicMock()

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ) as mock_get_device,
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                side_effect=asyncio.TimeoutError(),
            ) as mock_bleak,
        ):
            result = await firmware_manager.flash_firmware(firmware_data)

            assert result is False
            mock_get_device.assert_called_once()
            mock_bleak.assert_called_once()

    async def test_flash_firmware_rejects_undersized_data(self, firmware_manager):
        """flash_firmware must validate size itself, not just download_firmware.

        It's a public method, so a caller that bypasses download_firmware
        (or passes bad data directly) shouldn't be able to trigger an OTA
        start/end command sequence for empty/tiny data.
        """
        firmware_data = b"x" * (MIN_FIRMWARE_SIZE - 1)

        with patch(
            "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
        ) as mock_get_device:
            result = await firmware_manager.flash_firmware(firmware_data)

        assert result is False
        # Should fail fast, before ever looking up the BLE device.
        mock_get_device.assert_not_called()

    async def test_flash_firmware_rejects_oversized_data(self, firmware_manager):
        """flash_firmware must reject data larger than MAX_FIRMWARE_SIZE."""
        firmware_data = b"x" * (MAX_FIRMWARE_SIZE + 1)

        with patch(
            "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
        ) as mock_get_device:
            result = await firmware_manager.flash_firmware(firmware_data)

        assert result is False
        mock_get_device.assert_not_called()

    async def test_flash_firmware_uses_single_ota_characteristic(
        self, firmware_manager
    ):
        """All OTA writes must target the single real OTA characteristic.

        The GATT attribute table only exposes one characteristic for OTA
        (UUID 00010203-0405-0607-0809-0a0b0c0d2b12, "TELINK_SPP_DATA_OTA" in
        pvvx/ATC_MiThermometer's src/app_att.c). Writing to any other UUID
        (as the previous implementation did) fails on real hardware because
        no such characteristic exists.
        """
        firmware_data = b"x" * MIN_FIRMWARE_SIZE

        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = True
        mock_client.write_gatt_char = AsyncMock()
        mock_client.disconnect = AsyncMock()

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(return_value=mock_client),
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.asyncio.sleep",
                new=AsyncMock(),
            ),
        ):
            result = await firmware_manager.flash_firmware(firmware_data)

        assert result is True
        uuids_written = {
            call.args[0] for call in mock_client.write_gatt_char.call_args_list
        }
        assert uuids_written == {"00010203-0405-0607-0809-0a0b0c0d2b12"}
        # Every write must be write-without-response, matching the
        # characteristic's CHAR_PROP_WRITE_WITHOUT_RSP-only declaration.
        assert all(
            call.kwargs.get("response") is False
            for call in mock_client.write_gatt_char.call_args_list
        )

    async def test_flash_firmware_packet_framing(self, firmware_manager):
        """Verify start/data/trailer/end packets follow the documented framing."""
        # MIN_FIRMWARE_SIZE (1024 bytes) - smaller than one 4K sector, but
        # still large enough to need multiple 17-byte data packets.
        firmware_data = bytes([0x42]) * MIN_FIRMWARE_SIZE

        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = True
        mock_client.write_gatt_char = AsyncMock()
        mock_client.disconnect = AsyncMock()

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(return_value=mock_client),
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.asyncio.sleep",
                new=AsyncMock(),
            ),
        ):
            result = await firmware_manager.flash_firmware(firmware_data)

        assert result is True
        packets = [call.args[1] for call in mock_client.write_gatt_char.call_args_list]
        # start command + N data packets + one trailer packet + end command
        assert len(packets) > 3

        start_packet = packets[0]
        assert len(start_packet) == 20
        assert int.from_bytes(start_packet[0:2], "little") == 0xFF01
        assert int.from_bytes(start_packet[2:6], "little") == len(firmware_data)

        end_packet = packets[-1]
        assert len(end_packet) == 20
        assert int.from_bytes(end_packet[0:2], "little") == 0xFF02

        trailer_packet = packets[-2]
        assert len(trailer_packet) == 20
        assert int.from_bytes(trailer_packet[0:2], "little") == 0  # sector 0
        assert trailer_packet[2] == 0xFF  # trailer sentinel

        data_packets = packets[1:-2]
        for seq, packet in enumerate(data_packets):
            assert len(packet) == 20
            assert int.from_bytes(packet[0:2], "little") == 0  # sector 0
            assert packet[2] == seq  # packet_seq increments from 0

        reconstructed = b"".join(p[3:20] for p in data_packets)[: len(firmware_data)]
        assert reconstructed == firmware_data

    async def test_flash_firmware_multi_sector(self, firmware_manager):
        """Verify sector_index increments and each sector gets its own trailer.

        Regression test for sector-boundary handling: previous tests only
        covered firmware that fit in a single 4K sector.
        """
        # Just over 2 sectors: sector 0 and 1 full (4096 bytes each), sector 2
        # partial (10 bytes).
        firmware_data = bytes(range(256)) * 32 + b"\x99" * 10
        assert len(firmware_data) == 2 * OTA_SECTOR_SIZE + 10

        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = True
        mock_client.write_gatt_char = AsyncMock()
        mock_client.disconnect = AsyncMock()

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(return_value=mock_client),
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.asyncio.sleep",
                new=AsyncMock(),
            ),
        ):
            result = await firmware_manager.flash_firmware(firmware_data)

        assert result is True
        packets = [call.args[1] for call in mock_client.write_gatt_char.call_args_list]

        # Trailer packets are the ones with packet_seq == 0xFF.
        trailer_packets = [p for p in packets[1:-1] if p[2] == 0xFF]
        assert len(trailer_packets) == 3  # one per sector, including the partial one
        trailer_sector_indices = [
            int.from_bytes(p[0:2], "little") for p in trailer_packets
        ]
        assert trailer_sector_indices == [0, 1, 2]

        for sector_index, trailer in zip(
            trailer_sector_indices, trailer_packets, strict=True
        ):
            offset = sector_index * OTA_SECTOR_SIZE
            sector = firmware_data[offset : offset + OTA_SECTOR_SIZE]
            # The final (partial) sector is padded to a full 4K with 0xff
            # (erased-flash convention) before its CRC is taken - a no-op
            # for the two full sectors here, but required for sector 2.
            expected_crc = _crc16_ccitt(sector.ljust(OTA_SECTOR_SIZE, b"\xff"))
            assert int.from_bytes(trailer[-2:], "little") == expected_crc
            if sector_index == 2:
                assert len(sector) < OTA_SECTOR_SIZE  # actually exercises padding

    async def test_get_current_version_from_advertisements(self, firmware_manager):
        """Test getting current version from device advertisements."""
        mock_ble_device = MagicMock()

        # Mock BLE client that fails to connect (triggers fallback to manufacturer data)
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = False
        mock_client.disconnect = AsyncMock()

        mock_service_info = MagicMock()
        mock_service_info.manufacturer_data = {
            0x0001: bytes([0x00, 0x01, 0x02, 0x03, 0x01, 0x02])  # version 1.2
        }

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(return_value=mock_client),
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_last_service_info",
                return_value=mock_service_info,
            ),
        ):
            version = await firmware_manager.get_current_version()

            assert version == "1.2"

    async def test_get_current_version_device_not_found(self, firmware_manager):
        """Test getting version when device not found."""
        with patch(
            "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
            return_value=None,
        ):
            version = await firmware_manager.get_current_version()

            assert version is None

    async def test_get_current_version_not_connectable_warns_once(
        self, firmware_manager, caplog
    ):
        """The "no connectable route" message should only warn once.

        Repeated failures (e.g. a coordinator polling every 6 hours for a
        device that's only ever seen passively) should drop to debug after
        the first warning, so steady-state logs for a deliberately
        non-connectable device don't accumulate warnings forever.
        """
        with patch(
            "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
            return_value=None,
        ):
            with caplog.at_level(logging.WARNING):
                await firmware_manager.get_current_version()
            assert "No connectable Bluetooth route" in caplog.text

            caplog.clear()
            with caplog.at_level(logging.WARNING):
                await firmware_manager.get_current_version()
            assert "No connectable Bluetooth route" not in caplog.text

    async def test_get_current_version_not_connectable_warns_again_after_recovery(
        self, firmware_manager, caplog
    ):
        """A new connectivity regression should warn again, not stay silent.

        If the device becomes connectable again in between failures (e.g. a
        Bluetooth proxy flapping), the next "not connectable" occurrence is a
        *new* regression and should be surfaced at warning level again rather
        than staying suppressed at debug forever.
        """
        with patch(
            "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
            return_value=None,
        ):
            await firmware_manager.get_current_version()
        assert firmware_manager._connectable_warning_logged is True

        # Device becomes connectable again (GATT read itself fails, but that's
        # irrelevant here - what matters is ble_device was found this time).
        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=MagicMock(),
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                side_effect=BleakError("simulated transient failure"),
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_last_service_info",
                return_value=None,
            ),
        ):
            await firmware_manager.get_current_version()
        assert firmware_manager._connectable_warning_logged is False

        caplog.clear()
        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=None,
            ),
            caplog.at_level(logging.WARNING),
        ):
            await firmware_manager.get_current_version()
        assert "No connectable Bluetooth route" in caplog.text

    async def test_get_current_version_no_manufacturer_data(self, firmware_manager):
        """Test getting version when no manufacturer data."""
        mock_ble_device = MagicMock()

        # Mock BLE client that fails to connect (triggers fallback to manufacturer data)
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = False
        mock_client.disconnect = AsyncMock()

        mock_service_info = MagicMock()
        mock_service_info.manufacturer_data = {}

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(return_value=mock_client),
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_last_service_info",
                return_value=mock_service_info,
            ),
        ):
            version = await firmware_manager.get_current_version()

            assert version is None

    async def test_get_current_version_short_data(self, firmware_manager):
        """Test getting version with insufficient data."""
        mock_ble_device = MagicMock()

        # Mock BLE client that fails to connect (triggers fallback to manufacturer data)
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = False
        mock_client.disconnect = AsyncMock()

        mock_service_info = MagicMock()
        mock_service_info.manufacturer_data = {0x0001: bytes([0x00, 0x01])}  # Too short

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(return_value=mock_client),
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_last_service_info",
                return_value=mock_service_info,
            ),
        ):
            version = await firmware_manager.get_current_version()

            assert version is None

    async def test_get_current_version_ble_error(self, firmware_manager):
        """Test getting version with BLE error."""
        with patch(
            "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
            side_effect=BleakError("Connection failed"),
        ):
            version = await firmware_manager.get_current_version()

            assert version is None

    async def test_get_current_version_from_gatt_success(self, firmware_manager):
        """Test getting version from GATT characteristic successfully."""
        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = True
        mock_client.read_gatt_char = AsyncMock(return_value=b"V4.3")
        mock_client.disconnect = AsyncMock()

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(return_value=mock_client),
            ),
        ):
            version = await firmware_manager.get_current_version()

            assert version == "4.3"
            mock_client.read_gatt_char.assert_called_once()
            mock_client.disconnect.assert_called_once()

    async def test_get_current_version_disconnect_error_does_not_mask_result(
        self, firmware_manager
    ):
        """A disconnect-time error must not discard a version already read.

        Without the safety wrapper, a disconnect() failure in the finally
        block would propagate past `return version`, get caught by the
        broad `except (BleakError, TimeoutError)` around the connection
        block, and fall through to the manufacturer-data fallback -
        discarding a version that was actually read successfully.
        """
        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = True
        mock_client.read_gatt_char = AsyncMock(return_value=b"V4.3")
        mock_client.disconnect = AsyncMock(
            side_effect=BleakError("already disconnected")
        )

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(return_value=mock_client),
            ),
        ):
            version = await firmware_manager.get_current_version()

        assert version == "4.3"
        mock_client.disconnect.assert_called_once()

    async def test_get_current_version_connect_is_bounded_by_connect_timeout(
        self, firmware_manager
    ):
        """establish_connection() must be wrapped with CONNECT_TIMEOUT.

        See the matching flash_firmware regression test for why: without
        this, a marginal device can make a single version-check connection
        attempt run for minutes, which during initial config entry setup
        was enough for Home Assistant to cancel the whole entry's setup.
        """
        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = True
        mock_client.read_gatt_char = AsyncMock(return_value=b"V4.3")
        mock_client.disconnect = AsyncMock()

        real_wait_for = asyncio.wait_for
        wait_for_timeouts = []

        async def spy_wait_for(aw, timeout):
            wait_for_timeouts.append(timeout)
            return await real_wait_for(aw, timeout=timeout)

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(return_value=mock_client),
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.asyncio.wait_for",
                side_effect=spy_wait_for,
            ),
        ):
            version = await firmware_manager.get_current_version()

        assert version == "4.3"
        assert wait_for_timeouts == [CONNECT_TIMEOUT]

    async def test_get_current_version_from_gatt_lowercase_prefix(
        self, firmware_manager
    ):
        """Test getting version from GATT with lowercase 'v' prefix."""
        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = True
        mock_client.read_gatt_char = AsyncMock(return_value=b"v3.2.1")
        mock_client.disconnect = AsyncMock()

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(return_value=mock_client),
            ),
        ):
            version = await firmware_manager.get_current_version()

            assert version == "3.2.1"

    async def test_get_current_version_from_gatt_no_prefix(self, firmware_manager):
        """Test getting version from GATT without version prefix."""
        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = True
        mock_client.read_gatt_char = AsyncMock(return_value=b"2.0")
        mock_client.disconnect = AsyncMock()

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(return_value=mock_client),
            ),
        ):
            version = await firmware_manager.get_current_version()

            assert version == "2.0"

    async def test_get_current_version_from_gatt_with_whitespace(
        self, firmware_manager
    ):
        """Test getting version from GATT with surrounding whitespace."""
        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = True
        mock_client.read_gatt_char = AsyncMock(return_value=b"  V5.1  ")
        mock_client.disconnect = AsyncMock()

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(return_value=mock_client),
            ),
        ):
            version = await firmware_manager.get_current_version()

            assert version == "5.1"

    async def test_get_current_version_gatt_empty_after_prefix(self, firmware_manager):
        """Test GATT version that becomes empty after prefix removal."""
        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = True
        # Only contains prefix, nothing after
        mock_client.read_gatt_char = AsyncMock(return_value=b"V")
        mock_client.disconnect = AsyncMock()

        mock_service_info = MagicMock()
        mock_service_info.manufacturer_data = {
            0x0001: bytes([0x00, 0x01, 0x02, 0x03, 0x01, 0x02])  # version 1.2 fallback
        }

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(return_value=mock_client),
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_last_service_info",
                return_value=mock_service_info,
            ),
        ):
            version = await firmware_manager.get_current_version()

            # Should fall back to manufacturer data
            assert version == "1.2"

    async def test_get_current_version_gatt_utf8_error(self, firmware_manager):
        """Test GATT version with invalid UTF-8 bytes falls back to manufacturer data."""
        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = True
        # Invalid UTF-8 sequence that should trigger fallback
        mock_client.read_gatt_char = AsyncMock(
            return_value=b"V4.\xff\xfe3"  # Invalid UTF-8
        )
        mock_client.disconnect = AsyncMock()

        # Mock manufacturer data for fallback
        mock_service_info = MagicMock()
        mock_service_info.manufacturer_data = {
            0x0001: bytes([0x00, 0x01, 0x02, 0x03, 0x04, 0x05])  # version 4.5 fallback
        }

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(return_value=mock_client),
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_last_service_info",
                return_value=mock_service_info,
            ),
        ):
            version = await firmware_manager.get_current_version()

            # Should fall back to manufacturer data when UTF-8 decode fails
            assert version == "4.5"

    async def test_get_current_version_gatt_timeout_fallback(self, firmware_manager):
        """Test GATT timeout with fallback to manufacturer data."""
        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = True
        mock_client.read_gatt_char = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_client.disconnect = AsyncMock()

        mock_service_info = MagicMock()
        mock_service_info.manufacturer_data = {
            0x0001: bytes([0x00, 0x01, 0x02, 0x03, 0x02, 0x05])  # version 2.5
        }

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(return_value=mock_client),
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_last_service_info",
                return_value=mock_service_info,
            ),
        ):
            version = await firmware_manager.get_current_version()

            # Should fall back to manufacturer data
            assert version == "2.5"

    async def test_get_current_version_gatt_bleak_error_fallback(
        self, firmware_manager
    ):
        """Test GATT BleakError with fallback to manufacturer data."""
        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = True
        mock_client.read_gatt_char = AsyncMock(
            side_effect=BleakError("Characteristic not found")
        )
        mock_client.disconnect = AsyncMock()

        mock_service_info = MagicMock()
        mock_service_info.manufacturer_data = {
            0x0001: bytes([0x00, 0x01, 0x02, 0x03, 0x03, 0x00])  # version 3.0
        }

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(return_value=mock_client),
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_last_service_info",
                return_value=mock_service_info,
            ),
        ):
            version = await firmware_manager.get_current_version()

            # Should fall back to manufacturer data
            assert version == "3.0"

    async def test_get_current_version_gatt_connection_failed(self, firmware_manager):
        """Test GATT when client connection fails, falls back to manufacturer data."""
        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = False  # Connection failed
        mock_client.disconnect = AsyncMock()

        mock_service_info = MagicMock()
        mock_service_info.manufacturer_data = {
            0x0001: bytes([0x00, 0x01, 0x02, 0x03, 0x04, 0x01])  # version 4.1
        }

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(return_value=mock_client),
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_last_service_info",
                return_value=mock_service_info,
            ),
        ):
            version = await firmware_manager.get_current_version()

            # Should fall back to manufacturer data when GATT connection fails
            assert version == "4.1"

    async def test_get_current_version_gatt_empty_response(self, firmware_manager):
        """Test GATT with empty response."""
        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = True
        mock_client.read_gatt_char = AsyncMock(return_value=b"")
        mock_client.disconnect = AsyncMock()

        mock_service_info = MagicMock()
        mock_service_info.manufacturer_data = {
            0x0001: bytes([0x00, 0x01, 0x02, 0x03, 0x01, 0x05])  # version 1.5
        }

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(return_value=mock_client),
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_last_service_info",
                return_value=mock_service_info,
            ),
        ):
            version = await firmware_manager.get_current_version()

            # Should fall back to manufacturer data
            assert version == "1.5"

    async def test_get_current_version_gatt_none_response(self, firmware_manager):
        """Test GATT with None response falls back to manufacturer data."""
        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = True
        # Return None instead of bytes
        mock_client.read_gatt_char = AsyncMock(return_value=None)
        mock_client.disconnect = AsyncMock()

        mock_service_info = MagicMock()
        mock_service_info.manufacturer_data = {
            0x0001: bytes([0x00, 0x01, 0x02, 0x03, 0x02, 0x03])  # version 2.3
        }

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(return_value=mock_client),
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_last_service_info",
                return_value=mock_service_info,
            ),
        ):
            version = await firmware_manager.get_current_version()

            # Should fall back to manufacturer data when GATT returns None
            assert version == "2.3"

    async def test_get_current_version_gatt_max_length_boundary(
        self, firmware_manager
    ):
        """Test GATT version at the MAX_VERSION_LENGTH boundary (20 chars).

        The longest string VERSION_VALIDATION_PATTERN can ever accept is 16
        chars ("V" + "123.456.789.012"), well under MAX_VERSION_LENGTH (20).
        So a string that is exactly 20 chars is always rejected - by the
        length check if it happens to be even longer, or by the pattern
        otherwise - and detection falls back to manufacturer data.
        """
        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = True
        # Exactly 20 characters: "123.456.789.0123456" (19 chars + "V" prefix = 20)
        mock_client.read_gatt_char = AsyncMock(
            return_value=b"123.456.789.0123456"
        )
        mock_client.disconnect = AsyncMock()

        mock_service_info = MagicMock()
        mock_service_info.manufacturer_data = {
            0x0001: bytes([0x00, 0x01, 0x02, 0x03, 0x02, 0x03])  # version 2.3
        }

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(return_value=mock_client),
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_last_service_info",
                return_value=mock_service_info,
            ),
        ):
            version = await firmware_manager.get_current_version()

            # Not a valid version format, so GATT rejects it and we fall back
            assert version == "2.3"

    async def test_get_current_version_gatt_exceeds_max_length(
        self, firmware_manager
    ):
        """Test GATT version exceeding MAX_VERSION_LENGTH falls back."""
        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = True
        # 21 characters exceeds MAX_VERSION_LENGTH (20)
        mock_client.read_gatt_char = AsyncMock(
            return_value=b"123.456.789.01234567"
        )
        mock_client.disconnect = AsyncMock()

        mock_service_info = MagicMock()
        mock_service_info.manufacturer_data = {
            0x0001: bytes([0x00, 0x01, 0x02, 0x03, 0x03, 0x04])  # version 3.4
        }

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(return_value=mock_client),
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_last_service_info",
                return_value=mock_service_info,
            ),
        ):
            version = await firmware_manager.get_current_version()

            # Should fall back to manufacturer data when exceeding max length
            assert version == "3.4"

    async def test_get_current_version_gatt_invalid_after_prefix_removal(
        self, firmware_manager
    ):
        """Test GATT version invalid after prefix removal falls back."""
        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = True
        # "Vabc" -> after removing "V" = "abc", which is invalid
        mock_client.read_gatt_char = AsyncMock(return_value=b"Vabc")
        mock_client.disconnect = AsyncMock()

        mock_service_info = MagicMock()
        mock_service_info.manufacturer_data = {
            0x0001: bytes([0x00, 0x01, 0x02, 0x03, 0x05, 0x06])  # version 5.6
        }

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(return_value=mock_client),
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_last_service_info",
                return_value=mock_service_info,
            ),
        ):
            version = await firmware_manager.get_current_version()

            # Should fall back to manufacturer data for invalid format
            assert version == "5.6"

    async def test_get_current_version_gatt_single_component_after_prefix(
        self, firmware_manager
    ):
        """Test GATT version with single component after prefix falls back."""
        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = True
        # "V4" -> after removing "V" = "4", which doesn't match major.minor pattern
        mock_client.read_gatt_char = AsyncMock(return_value=b"V4")
        mock_client.disconnect = AsyncMock()

        mock_service_info = MagicMock()
        mock_service_info.manufacturer_data = {
            0x0001: bytes([0x00, 0x01, 0x02, 0x03, 0x04, 0x00])  # version 4.0
        }

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.establish_connection",
                AsyncMock(return_value=mock_client),
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_last_service_info",
                return_value=mock_service_info,
            ),
        ):
            version = await firmware_manager.get_current_version()

            # Should fall back to manufacturer data for single-component version
            assert version == "4.0"
