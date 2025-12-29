"""Test the firmware module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from bleak import BleakClient, BleakError
from homeassistant.core import HomeAssistant

from custom_components.atc_mithermometer.const import (
    FIRMWARE_SOURCE_ATC1441,
    FIRMWARE_SOURCE_PVVX,
    MAX_FIRMWARE_SIZE,
    MIN_FIRMWARE_SIZE,
)
from custom_components.atc_mithermometer.firmware import (
    FirmwareManager,
    FirmwareRelease,
)


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
        firmware_data = b"x" * 1000

        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = True
        mock_client.write_gatt_char = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ) as mock_get_device,
            patch(
                "custom_components.atc_mithermometer.firmware.BleakClient",
                return_value=mock_client,
            ) as mock_bleak,
        ):
            result = await firmware_manager.flash_firmware(firmware_data)

            assert result is True
            mock_get_device.assert_called_once()
            mock_bleak.assert_called_once()
            assert mock_client.write_gatt_char.called

    async def test_flash_firmware_with_progress_callback(self, firmware_manager):
        """Test firmware flash with progress callback."""
        firmware_data = b"x" * 1000

        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = True
        mock_client.write_gatt_char = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        progress_calls = []

        def progress_callback(current, total):
            progress_calls.append((current, total))

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.BleakClient",
                return_value=mock_client,
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
        firmware_data = b"x" * 1000

        with patch(
            "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
            return_value=None,
        ) as mock_get_device:
            result = await firmware_manager.flash_firmware(firmware_data)

            assert result is False
            mock_get_device.assert_called_once()

    async def test_flash_firmware_connection_failed(self, firmware_manager):
        """Test firmware flash when connection fails."""
        firmware_data = b"x" * 1000

        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = False
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ) as mock_get_device,
            patch(
                "custom_components.atc_mithermometer.firmware.BleakClient",
                return_value=mock_client,
            ) as mock_bleak,
        ):
            result = await firmware_manager.flash_firmware(firmware_data)

            assert result is False
            mock_get_device.assert_called_once()
            mock_bleak.assert_called_once()

    async def test_flash_firmware_ble_error(self, firmware_manager):
        """Test firmware flash with BLE error."""
        firmware_data = b"x" * 1000

        mock_ble_device = MagicMock()

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ) as mock_get_device,
            patch(
                "custom_components.atc_mithermometer.firmware.BleakClient",
                side_effect=BleakError("Connection failed"),
            ) as mock_bleak,
        ):
            result = await firmware_manager.flash_firmware(firmware_data)

            assert result is False
            mock_get_device.assert_called_once()
            mock_bleak.assert_called_once()

    async def test_flash_firmware_timeout(self, firmware_manager):
        """Test firmware flash timeout."""
        firmware_data = b"x" * 1000

        mock_ble_device = MagicMock()

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ) as mock_get_device,
            patch(
                "custom_components.atc_mithermometer.firmware.BleakClient",
                side_effect=asyncio.TimeoutError(),
            ) as mock_bleak,
        ):
            result = await firmware_manager.flash_firmware(firmware_data)

            assert result is False
            mock_get_device.assert_called_once()
            mock_bleak.assert_called_once()

    async def test_get_current_version_from_advertisements(self, firmware_manager):
        """Test getting current version from device advertisements."""
        mock_ble_device = MagicMock()

        # Mock BLE client that fails to connect (triggers fallback to manufacturer data)
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = False
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

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
                "custom_components.atc_mithermometer.firmware.BleakClient",
                return_value=mock_client,
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

    async def test_get_current_version_no_manufacturer_data(self, firmware_manager):
        """Test getting version when no manufacturer data."""
        mock_ble_device = MagicMock()

        # Mock BLE client that fails to connect (triggers fallback to manufacturer data)
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = False
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        mock_service_info = MagicMock()
        mock_service_info.manufacturer_data = {}

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.BleakClient",
                return_value=mock_client,
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
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        mock_service_info = MagicMock()
        mock_service_info.manufacturer_data = {0x0001: bytes([0x00, 0x01])}  # Too short

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.BleakClient",
                return_value=mock_client,
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
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.BleakClient",
                return_value=mock_client,
            ),
        ):
            version = await firmware_manager.get_current_version()

            assert version == "4.3"
            mock_client.read_gatt_char.assert_called_once()

    async def test_get_current_version_from_gatt_lowercase_prefix(
        self, firmware_manager
    ):
        """Test getting version from GATT with lowercase 'v' prefix."""
        mock_ble_device = MagicMock()
        mock_client = AsyncMock(spec=BleakClient)
        mock_client.is_connected = True
        mock_client.read_gatt_char = AsyncMock(return_value=b"v3.2.1")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.BleakClient",
                return_value=mock_client,
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
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.BleakClient",
                return_value=mock_client,
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
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with (
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_ble_device_from_address",
                return_value=mock_ble_device,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.BleakClient",
                return_value=mock_client,
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
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

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
                "custom_components.atc_mithermometer.firmware.BleakClient",
                return_value=mock_client,
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
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

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
                "custom_components.atc_mithermometer.firmware.BleakClient",
                return_value=mock_client,
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
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

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
                "custom_components.atc_mithermometer.firmware.BleakClient",
                return_value=mock_client,
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
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

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
                "custom_components.atc_mithermometer.firmware.BleakClient",
                return_value=mock_client,
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
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

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
                "custom_components.atc_mithermometer.firmware.BleakClient",
                return_value=mock_client,
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
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

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
                "custom_components.atc_mithermometer.firmware.BleakClient",
                return_value=mock_client,
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
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

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
                "custom_components.atc_mithermometer.firmware.BleakClient",
                return_value=mock_client,
            ),
            patch(
                "custom_components.atc_mithermometer.firmware.bluetooth.async_last_service_info",
                return_value=mock_service_info,
            ),
        ):
            version = await firmware_manager.get_current_version()

            # Should fall back to manufacturer data when GATT returns None
            assert version == "2.3"
