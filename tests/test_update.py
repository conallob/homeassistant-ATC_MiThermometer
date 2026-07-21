"""Test the update platform."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.atc_mithermometer.const import (
    ATTR_CURRENT_VERSION,
    ATTR_FIRMWARE_SOURCE,
    ATTR_LATEST_VERSION,
    CONF_FIRMWARE_SOURCE,
    CONF_MAC_ADDRESS,
    FIRMWARE_SOURCE_PVVX,
    POST_FLASH_REBOOT_DELAY,
    PROGRESS_DOWNLOAD_COMPLETE,
    PROGRESS_DOWNLOAD_START,
)
from custom_components.atc_mithermometer.firmware import FirmwareRelease
from custom_components.atc_mithermometer.update import (
    ATCMiThermometerUpdate,
    ATCUpdateCoordinator,
    async_setup_entry,
)


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test_entry"
    entry.data = {
        CONF_MAC_ADDRESS: "AA:BB:CC:DD:EE:FF",
        CONF_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
    }
    return entry


@pytest.fixture
def mock_firmware_manager():
    """Create a mock firmware manager."""
    manager = MagicMock()
    manager.get_current_version = AsyncMock(return_value="v1.0.0")
    manager.get_latest_release = AsyncMock(
        return_value=FirmwareRelease(
            version="v1.2.3",
            download_url="https://example.com/firmware.bin",
            release_url="https://example.com/release",
            release_notes="Test release notes",
        )
    )
    manager.download_firmware = AsyncMock(return_value=b"firmware_data")
    manager.flash_firmware = AsyncMock(return_value=True)
    manager.apply_firmware_update = AsyncMock(return_value=True)
    return manager


@pytest.fixture
def mock_bthome_device():
    """Create a mock BTHome device."""
    device = MagicMock()
    device.id = "bthome_device_id"
    device.identifiers = {("bthome", "AA:BB:CC:DD:EE:FF")}
    device.connections = {("bluetooth", "AA:BB:CC:DD:EE:FF")}
    return device


async def test_async_setup_entry(
    hass: HomeAssistant, mock_config_entry, mock_firmware_manager, mock_bthome_device
):
    """Test setting up the update platform."""
    with (
        patch(
            "custom_components.atc_mithermometer.update.FirmwareManager",
            return_value=mock_firmware_manager,
        ),
        patch(
            "custom_components.atc_mithermometer.update.get_bthome_device_by_mac",
            return_value=mock_bthome_device,
        ),
    ):
        async_add_entities = MagicMock()

        await async_setup_entry(hass, mock_config_entry, async_add_entities)

        assert async_add_entities.called
        entities = async_add_entities.call_args[0][0]
        assert len(entities) == 1
        assert isinstance(entities[0], ATCMiThermometerUpdate)


class TestATCUpdateCoordinator:
    """Test ATCUpdateCoordinator."""

    async def test_coordinator_init(self, hass: HomeAssistant, mock_firmware_manager):
        """Test coordinator initialization."""
        coordinator = ATCUpdateCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )

        assert coordinator.firmware_manager == mock_firmware_manager
        assert coordinator.firmware_source == FIRMWARE_SOURCE_PVVX
        assert coordinator.mac_address == "AA:BB:CC:DD:EE:FF"

    async def test_coordinator_update_success(
        self, hass: HomeAssistant, mock_firmware_manager
    ):
        """Test successful coordinator update."""
        coordinator = ATCUpdateCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )

        data = await coordinator._async_update_data()

        assert data[ATTR_CURRENT_VERSION] == "v1.0.0"
        assert data[ATTR_LATEST_VERSION] == "v1.2.3"
        assert data[ATTR_FIRMWARE_SOURCE] == FIRMWARE_SOURCE_PVVX
        assert "latest_release" in data

        # Verify mocked methods were called
        mock_firmware_manager.get_current_version.assert_called_once()
        mock_firmware_manager.get_latest_release.assert_called_once_with(
            FIRMWARE_SOURCE_PVVX
        )

    async def test_coordinator_update_no_release(
        self, hass: HomeAssistant, mock_firmware_manager
    ):
        """Test coordinator update with no release found."""
        mock_firmware_manager.get_latest_release = AsyncMock(return_value=None)

        coordinator = ATCUpdateCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )

        with pytest.raises(UpdateFailed, match="Failed to fetch latest release info"):
            await coordinator._async_update_data()

        # Verify mocked methods were called
        mock_firmware_manager.get_latest_release.assert_called_once_with(
            FIRMWARE_SOURCE_PVVX
        )

    async def test_coordinator_update_network_error(
        self, hass: HomeAssistant, mock_firmware_manager
    ):
        """Test coordinator update with network error."""
        mock_firmware_manager.get_latest_release = AsyncMock(
            side_effect=aiohttp.ClientError("Network error")
        )

        coordinator = ATCUpdateCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )

        with pytest.raises(UpdateFailed, match="Error fetching update data"):
            await coordinator._async_update_data()

        # Verify mocked method was called
        mock_firmware_manager.get_latest_release.assert_called_once_with(
            FIRMWARE_SOURCE_PVVX
        )


class TestATCMiThermometerUpdate:
    """Test ATCMiThermometerUpdate entity."""

    @pytest.fixture(autouse=True)
    def _no_reboot_delay(self):
        """Skip the real POST_FLASH_REBOOT_DELAY sleep in async_install tests."""
        with patch(
            "custom_components.atc_mithermometer.update.asyncio.sleep",
            new=AsyncMock(),
        ):
            yield

    async def test_entity_init_with_bthome_device(
        self,
        hass: HomeAssistant,
        mock_config_entry,
        mock_firmware_manager,
        mock_bthome_device,
    ):
        """Test entity initialization with BTHome device."""
        coordinator = ATCUpdateCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )
        coordinator.data = {
            ATTR_CURRENT_VERSION: "v1.0.0",
            ATTR_LATEST_VERSION: "v1.2.3",
            ATTR_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
            "latest_release": FirmwareRelease(
                version="v1.2.3",
                download_url="https://example.com/firmware.bin",
                release_url="https://example.com/release",
            ),
        }

        entity = ATCMiThermometerUpdate(
            coordinator, mock_config_entry, mock_firmware_manager, mock_bthome_device
        )

        assert entity.unique_id == "AA:BB:CC:DD:EE:FF_firmware_update"
        assert entity.name == "Firmware Update"
        assert entity.device_info is not None

    async def test_entity_init_without_bthome_device(
        self, hass: HomeAssistant, mock_config_entry, mock_firmware_manager
    ):
        """Test entity initialization without BTHome device."""
        coordinator = ATCUpdateCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )
        coordinator.data = {
            ATTR_CURRENT_VERSION: "v1.0.0",
            ATTR_LATEST_VERSION: "v1.2.3",
            ATTR_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
            "latest_release": FirmwareRelease(
                version="v1.2.3",
                download_url="https://example.com/firmware.bin",
                release_url="https://example.com/release",
            ),
        }

        entity = ATCMiThermometerUpdate(
            coordinator, mock_config_entry, mock_firmware_manager, None
        )

        assert entity.unique_id == "AA:BB:CC:DD:EE:FF_firmware_update"
        assert entity.device_info is not None

    async def test_installed_version(
        self, hass: HomeAssistant, mock_config_entry, mock_firmware_manager
    ):
        """Test installed_version property."""
        coordinator = ATCUpdateCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )
        coordinator.data = {
            ATTR_CURRENT_VERSION: "v1.0.0",
            ATTR_LATEST_VERSION: "v1.2.3",
            ATTR_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
        }

        entity = ATCMiThermometerUpdate(
            coordinator, mock_config_entry, mock_firmware_manager
        )

        assert entity.installed_version == "v1.0.0"

    async def test_latest_version(
        self, hass: HomeAssistant, mock_config_entry, mock_firmware_manager
    ):
        """Test latest_version property."""
        coordinator = ATCUpdateCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )
        coordinator.data = {
            ATTR_CURRENT_VERSION: "v1.0.0",
            ATTR_LATEST_VERSION: "v1.2.3",
            ATTR_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
        }

        entity = ATCMiThermometerUpdate(
            coordinator, mock_config_entry, mock_firmware_manager
        )

        assert entity.latest_version == "v1.2.3"

    async def test_release_url(
        self, hass: HomeAssistant, mock_config_entry, mock_firmware_manager
    ):
        """Test release_url property."""
        coordinator = ATCUpdateCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )
        coordinator.data = {
            ATTR_CURRENT_VERSION: "v1.0.0",
            ATTR_LATEST_VERSION: "v1.2.3",
            ATTR_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
            "latest_release": FirmwareRelease(
                version="v1.2.3",
                download_url="https://example.com/firmware.bin",
                release_url="https://example.com/release",
            ),
        }

        entity = ATCMiThermometerUpdate(
            coordinator, mock_config_entry, mock_firmware_manager
        )

        assert entity.release_url == "https://example.com/release"

    async def test_release_summary(
        self, hass: HomeAssistant, mock_config_entry, mock_firmware_manager
    ):
        """Test release_summary property."""
        coordinator = ATCUpdateCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )
        coordinator.data = {
            ATTR_CURRENT_VERSION: "v1.0.0",
            ATTR_LATEST_VERSION: "v1.2.3",
            ATTR_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
            "latest_release": FirmwareRelease(
                version="v1.2.3",
                download_url="https://example.com/firmware.bin",
                release_url="https://example.com/release",
                release_notes="Test release notes",
            ),
        }

        entity = ATCMiThermometerUpdate(
            coordinator, mock_config_entry, mock_firmware_manager
        )

        assert entity.release_summary == "Test release notes"

    async def test_in_progress_false(
        self, hass: HomeAssistant, mock_config_entry, mock_firmware_manager
    ):
        """Test in_progress when not installing."""
        coordinator = ATCUpdateCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )
        coordinator.data = {}

        entity = ATCMiThermometerUpdate(
            coordinator, mock_config_entry, mock_firmware_manager
        )

        assert entity.in_progress is False

    async def test_in_progress_with_value(
        self, hass: HomeAssistant, mock_config_entry, mock_firmware_manager
    ):
        """Test in_progress when installing."""
        coordinator = ATCUpdateCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )
        coordinator.data = {}

        entity = ATCMiThermometerUpdate(
            coordinator, mock_config_entry, mock_firmware_manager
        )
        entity._install_progress = 50

        assert entity.in_progress == 50

    async def test_extra_state_attributes(
        self, hass: HomeAssistant, mock_config_entry, mock_firmware_manager
    ):
        """Test extra_state_attributes property."""
        coordinator = ATCUpdateCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )
        coordinator.data = {
            ATTR_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
        }

        entity = ATCMiThermometerUpdate(
            coordinator, mock_config_entry, mock_firmware_manager
        )

        attrs = entity.extra_state_attributes

        assert ATTR_FIRMWARE_SOURCE in attrs
        assert attrs[ATTR_FIRMWARE_SOURCE] == FIRMWARE_SOURCE_PVVX
        assert "firmware_source_name" in attrs

    async def test_async_install_success(
        self, hass: HomeAssistant, mock_config_entry, mock_firmware_manager
    ):
        """Test successful firmware installation."""
        coordinator = ATCUpdateCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )
        coordinator.data = {
            ATTR_CURRENT_VERSION: "v1.0.0",
            ATTR_LATEST_VERSION: "v1.2.3",
            ATTR_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
            "latest_release": FirmwareRelease(
                version="v1.2.3",
                download_url="https://example.com/firmware.bin",
                release_url="https://example.com/release",
            ),
        }
        coordinator.async_request_refresh = AsyncMock()

        entity = ATCMiThermometerUpdate(
            coordinator, mock_config_entry, mock_firmware_manager
        )
        entity.hass = hass
        entity.async_write_ha_state = MagicMock()

        await entity.async_install(version="v1.2.3", backup=False)

        # Verify apply_firmware_update was called with the release
        mock_firmware_manager.apply_firmware_update.assert_called_once()
        call_args = mock_firmware_manager.apply_firmware_update.call_args
        assert call_args[0][0].version == "v1.2.3"

        # Verify coordinator refresh was requested
        coordinator.async_request_refresh.assert_called_once()

        # Progress should be reset
        assert entity._install_progress == 0

    async def test_async_install_waits_for_reboot_before_refresh(
        self, hass: HomeAssistant, mock_config_entry, mock_firmware_manager
    ):
        """The reboot delay must happen before the refresh, not after.

        Regression test: refreshing immediately after the OTA end command
        races the device's reboot, making the version-confirmation check
        either silently skip (device briefly unreachable) or produce a false
        warning (still reads the pre-update version for a moment).
        """
        coordinator = ATCUpdateCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )
        coordinator.data = {
            ATTR_CURRENT_VERSION: "v1.2.3",
            ATTR_LATEST_VERSION: "v1.2.3",
            ATTR_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
            "latest_release": FirmwareRelease(
                version="v1.2.3",
                download_url="https://example.com/firmware.bin",
                release_url="https://example.com/release",
            ),
        }
        coordinator.async_request_refresh = AsyncMock()

        entity = ATCMiThermometerUpdate(
            coordinator, mock_config_entry, mock_firmware_manager
        )
        entity.hass = hass
        entity.async_write_ha_state = MagicMock()

        call_order = []
        sleep_mock = AsyncMock(side_effect=lambda *_: call_order.append("sleep"))
        coordinator.async_request_refresh.side_effect = (
            lambda: call_order.append("refresh") or None
        )

        with patch(
            "custom_components.atc_mithermometer.update.asyncio.sleep",
            new=sleep_mock,
        ):
            await entity.async_install(version="v1.2.3", backup=False)

        sleep_mock.assert_called_once_with(POST_FLASH_REBOOT_DELAY)
        assert call_order == ["sleep", "refresh"]

    async def test_async_install_warns_when_version_unconfirmed(
        self, hass: HomeAssistant, mock_config_entry, mock_firmware_manager, caplog
    ):
        """Warn (but don't fail) if the version still doesn't match post-refresh.

        The OTA characteristic has no notify/ACK, so a successful write is not
        proof the device applied it. If the post-install coordinator refresh
        still reports the old version, that should be surfaced as a warning
        rather than silently reported as a clean success.
        """

        coordinator = ATCUpdateCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )
        coordinator.data = {
            ATTR_CURRENT_VERSION: "v1.0.0",
            ATTR_LATEST_VERSION: "v1.2.3",
            ATTR_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
            "latest_release": FirmwareRelease(
                version="v1.2.3",
                download_url="https://example.com/firmware.bin",
                release_url="https://example.com/release",
            ),
        }
        # Simulate a refresh that doesn't change the reported version - e.g.
        # the device hasn't finished rebooting yet, or rejected the update.
        coordinator.async_request_refresh = AsyncMock()

        entity = ATCMiThermometerUpdate(
            coordinator, mock_config_entry, mock_firmware_manager
        )
        entity.hass = hass
        entity.async_write_ha_state = MagicMock()

        with caplog.at_level(logging.WARNING):
            await entity.async_install(version="v1.2.3", backup=False)

        assert "does not yet match the expected" in caplog.text

    async def test_async_install_no_warning_when_version_confirmed(
        self, hass: HomeAssistant, mock_config_entry, mock_firmware_manager, caplog
    ):
        """No warning when the refreshed version matches the target."""

        coordinator = ATCUpdateCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )
        coordinator.data = {
            ATTR_CURRENT_VERSION: "v1.0.0",
            ATTR_LATEST_VERSION: "v1.2.3",
            ATTR_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
            "latest_release": FirmwareRelease(
                version="v1.2.3",
                download_url="https://example.com/firmware.bin",
                release_url="https://example.com/release",
            ),
        }

        async def fake_refresh():
            """Simulate the device reporting the new version after reboot."""
            coordinator.data = {**coordinator.data, ATTR_CURRENT_VERSION: "v1.2.3"}

        coordinator.async_request_refresh = AsyncMock(side_effect=fake_refresh)

        entity = ATCMiThermometerUpdate(
            coordinator, mock_config_entry, mock_firmware_manager
        )
        entity.hass = hass
        entity.async_write_ha_state = MagicMock()

        with caplog.at_level(logging.WARNING):
            await entity.async_install(version="v1.2.3", backup=False)

        assert "does not yet match the expected" not in caplog.text

    async def test_async_install_warns_when_device_unreachable_after_flash(
        self, hass: HomeAssistant, mock_config_entry, mock_firmware_manager, caplog
    ):
        """Warn when the device doesn't respond at all after flashing.

        This is arguably the most concerning outcome (bad framing, the
        device never coming back, etc.) - it must not be the one case that
        stays silent just because there's no old version to compare
        against.
        """
        coordinator = ATCUpdateCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )
        coordinator.data = {
            ATTR_CURRENT_VERSION: "v1.0.0",
            ATTR_LATEST_VERSION: "v1.2.3",
            ATTR_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
            "latest_release": FirmwareRelease(
                version="v1.2.3",
                download_url="https://example.com/firmware.bin",
                release_url="https://example.com/release",
            ),
        }

        async def fake_refresh():
            """Simulate the device staying unreachable after the flash."""
            coordinator.data = {**coordinator.data, ATTR_CURRENT_VERSION: None}

        coordinator.async_request_refresh = AsyncMock(side_effect=fake_refresh)

        entity = ATCMiThermometerUpdate(
            coordinator, mock_config_entry, mock_firmware_manager
        )
        entity.hass = hass
        entity.async_write_ha_state = MagicMock()

        with caplog.at_level(logging.WARNING):
            await entity.async_install(version="v1.2.3", backup=False)

        assert "did not respond afterwards" in caplog.text

    async def test_async_install_no_release(
        self, hass: HomeAssistant, mock_config_entry, mock_firmware_manager
    ):
        """Test install with no release available."""
        coordinator = ATCUpdateCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )
        coordinator.data = {
            ATTR_CURRENT_VERSION: "v1.0.0",
            ATTR_LATEST_VERSION: "v1.2.3",
            ATTR_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
        }

        entity = ATCMiThermometerUpdate(
            coordinator, mock_config_entry, mock_firmware_manager
        )
        entity.hass = hass

        with pytest.raises(HomeAssistantError, match="No firmware release available"):
            await entity.async_install(version="v1.2.3", backup=False)

    async def test_async_install_download_failed(
        self, hass: HomeAssistant, mock_config_entry, mock_firmware_manager
    ):
        """Test install when download fails."""
        mock_firmware_manager.apply_firmware_update = AsyncMock(
            side_effect=HomeAssistantError("Failed to download firmware")
        )

        coordinator = ATCUpdateCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )
        coordinator.data = {
            "latest_release": FirmwareRelease(
                version="v1.2.3",
                download_url="https://example.com/firmware.bin",
                release_url="https://example.com/release",
            ),
        }

        entity = ATCMiThermometerUpdate(
            coordinator, mock_config_entry, mock_firmware_manager
        )
        entity.hass = hass
        entity.async_write_ha_state = MagicMock()

        with pytest.raises(HomeAssistantError, match="Failed to download firmware"):
            await entity.async_install(version="v1.2.3", backup=False)

        # Verify apply_firmware_update was attempted
        mock_firmware_manager.apply_firmware_update.assert_called_once()

        # Progress should be reset on failure
        assert entity._install_progress == 0

    async def test_async_install_flash_failed(
        self, hass: HomeAssistant, mock_config_entry, mock_firmware_manager
    ):
        """Test install when flash fails."""
        mock_firmware_manager.apply_firmware_update = AsyncMock(
            side_effect=HomeAssistantError("Firmware flash failed")
        )

        coordinator = ATCUpdateCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )
        coordinator.data = {
            "latest_release": FirmwareRelease(
                version="v1.2.3",
                download_url="https://example.com/firmware.bin",
                release_url="https://example.com/release",
            ),
        }

        entity = ATCMiThermometerUpdate(
            coordinator, mock_config_entry, mock_firmware_manager
        )
        entity.hass = hass
        entity.async_write_ha_state = MagicMock()

        with pytest.raises(HomeAssistantError, match="Firmware flash failed"):
            await entity.async_install(version="v1.2.3", backup=False)

        # Verify apply_firmware_update was attempted
        mock_firmware_manager.apply_firmware_update.assert_called_once()

        # Progress should be reset on failure
        assert entity._install_progress == 0

    async def test_async_install_progress_updates(
        self, hass: HomeAssistant, mock_config_entry, mock_firmware_manager
    ):
        """Test install progress updates."""
        coordinator = ATCUpdateCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )
        coordinator.data = {
            "latest_release": FirmwareRelease(
                version="v1.2.3",
                download_url="https://example.com/firmware.bin",
                release_url="https://example.com/release",
            ),
        }
        coordinator.async_request_refresh = AsyncMock()

        entity = ATCMiThermometerUpdate(
            coordinator, mock_config_entry, mock_firmware_manager
        )
        entity.hass = hass

        write_state_calls = []

        def track_state_writes():
            write_state_calls.append(entity._install_progress)

        entity.async_write_ha_state = track_state_writes

        await entity.async_install(version="v1.2.3", backup=False)

        # Should have progress updates
        assert len(write_state_calls) > 0
        # Should include download start
        assert PROGRESS_DOWNLOAD_START in write_state_calls
        # Should include download complete
        assert PROGRESS_DOWNLOAD_COMPLETE in write_state_calls
