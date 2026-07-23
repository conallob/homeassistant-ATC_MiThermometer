"""Test the __init__ module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.atc_mithermometer import (
    _async_apply_firmware,
    _versions_equal,
    async_setup_entry,
    async_unload_entry,
    get_atc_devices_from_bthome,
    get_bthome_device_by_mac,
    get_device_mac_address,
    is_atc_mithermometer,
)
from custom_components.atc_mithermometer.const import (
    CONF_FIRMWARE_SOURCE,
    CONF_MAC_ADDRESS,
    DOMAIN,
    FIRMWARE_SOURCE_ATC1441,
    FIRMWARE_SOURCE_PVVX,
    SERVICE_UUID_ENVIRONMENTAL,
)
from custom_components.atc_mithermometer.firmware import FirmwareRelease


class TestIsATCMiThermometer:
    """Test is_atc_mithermometer function."""

    def test_identifies_by_name_prefix_atc(self):
        """Test identification by ATC_ name prefix."""
        assert is_atc_mithermometer("ATC_123456", []) is True

    def test_identifies_by_name_prefix_lywsd(self):
        """Test identification by LYWSD03MMC name prefix."""
        assert is_atc_mithermometer("LYWSD03MMC", []) is True

    def test_identifies_by_service_uuid(self):
        """Test identification by environmental service UUID."""
        assert (
            is_atc_mithermometer("Unknown Device", [SERVICE_UUID_ENVIRONMENTAL]) is True
        )

    def test_identifies_by_service_uuid_case_insensitive(self):
        """Test service UUID matching is case insensitive."""
        assert (
            is_atc_mithermometer("Unknown Device", [SERVICE_UUID_ENVIRONMENTAL.upper()])
            is True
        )

    def test_does_not_identify_wrong_device(self):
        """Test does not identify non-ATC devices."""
        assert is_atc_mithermometer("Other Device", []) is False
        assert is_atc_mithermometer("Other Device", ["some-other-uuid"]) is False

    def test_handles_none_device_name(self):
        """Test handles None device name."""
        assert is_atc_mithermometer(None, [SERVICE_UUID_ENVIRONMENTAL]) is True
        assert is_atc_mithermometer(None, []) is False

    def test_partial_name_match(self):
        """Test partial name matches work correctly."""
        assert is_atc_mithermometer("ATC_Device_123", []) is True
        assert is_atc_mithermometer("MyATC_Device", []) is False


class TestVersionsEqual:
    """Test _versions_equal function."""

    def test_equal_versions_simple(self):
        """Test equal version strings."""
        assert _versions_equal("1.0.0", "1.0.0") is True
        assert _versions_equal("2.5", "2.5") is True

    def test_equal_versions_with_prefix(self):
        """Test versions with v prefix are equal."""
        assert _versions_equal("v1.0.0", "1.0.0") is True
        assert _versions_equal("1.0.0", "v1.0.0") is True
        assert _versions_equal("v1.0.0", "v1.0.0") is True

    def test_different_versions(self):
        """Test different versions are not equal."""
        assert _versions_equal("1.0.0", "1.0.1") is False
        assert _versions_equal("1.0", "2.0") is False
        assert _versions_equal("v1.0.0", "v2.0.0") is False

    def test_different_precision_equal(self):
        """Test versions with different precision."""
        # Note: packaging treats "1.0" and "1.0.0" as equal
        assert _versions_equal("1.0", "1.0.0") is True

    def test_invalid_version_fallback_to_string(self):
        """Test invalid versions fall back to string comparison."""
        # Invalid versions that can't be parsed should use string comparison
        assert _versions_equal("custom-v1", "custom-v1") is True
        assert _versions_equal("custom-v1", "custom-v2") is False


async def test_async_setup_entry(hass: HomeAssistant):
    """Test setting up a config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_MAC_ADDRESS: "AA:BB:CC:DD:EE:FF",
            CONF_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
        },
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.atc_mithermometer.get_bthome_device_by_mac",
            return_value=None,
        ),
        patch.object(hass.config_entries, "async_forward_entry_setups") as mock_forward,
        patch.object(hass, "http", MagicMock()),
    ):
        result = await async_setup_entry(hass, entry)

        assert result is True
        assert DOMAIN in hass.data
        assert entry.entry_id in hass.data[DOMAIN]
        assert (
            hass.data[DOMAIN][entry.entry_id][CONF_MAC_ADDRESS] == "AA:BB:CC:DD:EE:FF"
        )
        assert (
            hass.data[DOMAIN][entry.entry_id][CONF_FIRMWARE_SOURCE]
            == FIRMWARE_SOURCE_PVVX
        )

        # Verify platforms were set up
        mock_forward.assert_called_once_with(entry, [Platform.SENSOR, Platform.UPDATE])


async def test_async_setup_entry_links_to_bthome_device(hass: HomeAssistant):
    """Test setup links to existing BTHome device."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_MAC_ADDRESS: "AA:BB:CC:DD:EE:FF",
            CONF_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
        },
    )
    entry.add_to_hass(hass)

    mock_device = MagicMock()
    mock_device.id = "device_123"

    mock_device_registry = MagicMock()
    mock_device_registry.async_update_device = MagicMock()

    with (
        patch(
            "custom_components.atc_mithermometer.get_bthome_device_by_mac",
            return_value=mock_device,
        ),
        patch(
            "custom_components.atc_mithermometer.dr.async_get",
            return_value=mock_device_registry,
        ),
        patch.object(hass.config_entries, "async_forward_entry_setups"),
        patch.object(hass, "http", MagicMock()),
    ):
        result = await async_setup_entry(hass, entry)

        assert result is True
        mock_device_registry.async_update_device.assert_called_once_with(
            mock_device.id, add_config_entry_id=entry.entry_id
        )


async def test_async_setup_entry_handles_device_link_error(hass: HomeAssistant):
    """Test setup continues even if device linking fails."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_MAC_ADDRESS: "AA:BB:CC:DD:EE:FF",
            CONF_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
        },
    )
    entry.add_to_hass(hass)

    mock_device = MagicMock()
    mock_device.id = "device_123"

    mock_device_registry = MagicMock()
    mock_device_registry.async_update_device = MagicMock(
        side_effect=ValueError("Test error")
    )

    with (
        patch(
            "custom_components.atc_mithermometer.get_bthome_device_by_mac",
            return_value=mock_device,
        ),
        patch(
            "custom_components.atc_mithermometer.dr.async_get",
            return_value=mock_device_registry,
        ),
        patch.object(hass.config_entries, "async_forward_entry_setups"),
        patch.object(hass, "http", MagicMock()),
    ):
        # Should not raise, continues setup
        result = await async_setup_entry(hass, entry)
        assert result is True


async def test_async_unload_entry(hass: HomeAssistant):
    """Test unloading a config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_MAC_ADDRESS: "AA:BB:CC:DD:EE:FF",
            CONF_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
        },
    )
    entry.add_to_hass(hass)

    # Set up some data
    hass.data[DOMAIN] = {entry.entry_id: {}}

    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        return_value=True,
    ) as mock_unload:
        result = await async_unload_entry(hass, entry)

        assert result is True
        assert entry.entry_id not in hass.data[DOMAIN]
        mock_unload.assert_called_once_with(entry, [Platform.SENSOR, Platform.UPDATE])


async def test_async_unload_entry_fails(hass: HomeAssistant):
    """Test unload fails properly."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_MAC_ADDRESS: "AA:BB:CC:DD:EE:FF",
            CONF_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
        },
    )
    entry.add_to_hass(hass)

    # Set up some data
    hass.data[DOMAIN] = {entry.entry_id: {}}

    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        return_value=False,
    ):
        result = await async_unload_entry(hass, entry)

        assert result is False
        # Data should not be removed if unload failed
        assert entry.entry_id in hass.data[DOMAIN]


async def test_get_atc_devices_from_bthome(hass: HomeAssistant):
    """Test getting ATC devices from BTHome integration."""
    mock_entry = MagicMock()
    mock_entry.entry_id = "bthome_entry_1"

    mock_device1 = MagicMock()
    mock_device1.id = "device_1"
    mock_device1.name = "ATC_123456"

    mock_device2 = MagicMock()
    mock_device2.id = "device_2"
    mock_device2.name = "LYWSD03MMC_789"

    mock_device3 = MagicMock()
    mock_device3.id = "device_3"
    mock_device3.name = "Other Device"

    mock_device_registry = MagicMock()

    with (
        patch.object(
            hass.config_entries,
            "async_entries",
            return_value=[mock_entry],
        ),
        patch(
            "custom_components.atc_mithermometer.dr.async_get",
            return_value=mock_device_registry,
        ),
        patch(
            "custom_components.atc_mithermometer.dr.async_entries_for_config_entry",
            return_value=[mock_device1, mock_device2, mock_device3],
        ),
    ):
        devices = await get_atc_devices_from_bthome(hass)

        assert len(devices) == 2
        assert mock_device1 in devices
        assert mock_device2 in devices
        assert mock_device3 not in devices


async def test_get_atc_devices_from_bthome_no_duplicates(hass: HomeAssistant):
    """Test get ATC devices avoids duplicates."""
    mock_entry1 = MagicMock()
    mock_entry1.entry_id = "bthome_entry_1"

    mock_entry2 = MagicMock()
    mock_entry2.entry_id = "bthome_entry_2"

    mock_device = MagicMock()
    mock_device.id = "device_1"
    mock_device.name = "ATC_123456"

    mock_device_registry = MagicMock()

    with (
        patch.object(
            hass.config_entries,
            "async_entries",
            return_value=[mock_entry1, mock_entry2],
        ),
        patch(
            "custom_components.atc_mithermometer.dr.async_get",
            return_value=mock_device_registry,
        ),
        patch(
            "custom_components.atc_mithermometer.dr.async_entries_for_config_entry",
            return_value=[mock_device],
        ),
    ):
        devices = await get_atc_devices_from_bthome(hass)

        # Should only return device once even though it appears in two entries
        assert len(devices) == 1
        assert mock_device in devices


async def test_get_device_mac_address(hass: HomeAssistant):
    """Test getting MAC address from device."""
    device_id = "test_device_id"
    mac_address = "AA:BB:CC:DD:EE:FF"

    mock_device = MagicMock()
    mock_device.connections = {(dr.CONNECTION_BLUETOOTH, mac_address)}

    mock_device_registry = MagicMock()
    mock_device_registry.async_get = MagicMock(return_value=mock_device)

    with patch(
        "custom_components.atc_mithermometer.dr.async_get",
        return_value=mock_device_registry,
    ):
        result = await get_device_mac_address(hass, device_id)

        assert result == mac_address


async def test_get_device_mac_address_no_device(hass: HomeAssistant):
    """Test getting MAC address when device not found."""
    device_id = "nonexistent_device"

    mock_device_registry = MagicMock()
    mock_device_registry.async_get = MagicMock(return_value=None)

    with patch(
        "custom_components.atc_mithermometer.dr.async_get",
        return_value=mock_device_registry,
    ):
        result = await get_device_mac_address(hass, device_id)

        assert result is None


async def test_get_device_mac_address_no_connections(hass: HomeAssistant):
    """Test getting MAC address when device has no connections."""
    device_id = "test_device_id"

    mock_device = MagicMock()
    mock_device.connections = set()

    mock_device_registry = MagicMock()
    mock_device_registry.async_get = MagicMock(return_value=mock_device)

    with patch(
        "custom_components.atc_mithermometer.dr.async_get",
        return_value=mock_device_registry,
    ):
        result = await get_device_mac_address(hass, device_id)

        assert result is None


async def test_get_bthome_device_by_mac(hass: HomeAssistant):
    """Test getting BTHome device by MAC address."""
    mac_address = "aa:bb:cc:dd:ee:ff"
    mac_normalized = "AA:BB:CC:DD:EE:FF"

    mock_device = MagicMock()
    mock_device.config_entries = ["entry_1"]

    mock_entry = MagicMock()
    mock_entry.domain = "bthome"

    mock_device_registry = MagicMock()
    mock_device_registry.async_get_device = MagicMock(return_value=mock_device)

    with (
        patch(
            "custom_components.atc_mithermometer.dr.async_get",
            return_value=mock_device_registry,
        ),
        patch.object(
            hass.config_entries,
            "async_get_entry",
            return_value=mock_entry,
        ),
    ):
        result = await get_bthome_device_by_mac(hass, mac_address)

        assert result == mock_device
        mock_device_registry.async_get_device.assert_called_once_with(
            connections={(dr.CONNECTION_BLUETOOTH, mac_normalized)}
        )


async def test_get_bthome_device_by_mac_not_found(hass: HomeAssistant):
    """Test getting BTHome device when not found."""
    mac_address = "AA:BB:CC:DD:EE:FF"

    mock_device_registry = MagicMock()
    mock_device_registry.async_get_device = MagicMock(return_value=None)

    with patch(
        "custom_components.atc_mithermometer.dr.async_get",
        return_value=mock_device_registry,
    ):
        result = await get_bthome_device_by_mac(hass, mac_address)

        assert result is None


async def test_get_bthome_device_by_mac_not_bthome(hass: HomeAssistant):
    """Test device found but not a BTHome device."""
    mac_address = "AA:BB:CC:DD:EE:FF"

    mock_device = MagicMock()
    mock_device.config_entries = ["entry_1"]

    mock_entry = MagicMock()
    mock_entry.domain = "other_domain"

    mock_device_registry = MagicMock()
    mock_device_registry.async_get_device = MagicMock(return_value=mock_device)

    with (
        patch(
            "custom_components.atc_mithermometer.dr.async_get",
            return_value=mock_device_registry,
        ),
        patch.object(
            hass.config_entries,
            "async_get_entry",
            return_value=mock_entry,
        ),
    ):
        result = await get_bthome_device_by_mac(hass, mac_address)

        assert result is None


async def test_get_bthome_device_by_mac_invalid_mac(hass: HomeAssistant):
    """Test getting device with invalid MAC address."""
    mac_address = "invalid_mac"

    result = await get_bthome_device_by_mac(hass, mac_address)

    assert result is None


class TestApplyFirmwareService:
    """Test the apply_firmware service handler (_async_apply_firmware)."""

    @pytest.fixture
    def mock_call(self):
        """Create a mock service call."""
        call = MagicMock()
        call.data = {"device_id": "device_1", "desired_version": "v5.8"}
        return call

    @pytest.fixture
    def mock_device(self):
        """Create a mock device registry entry with a Bluetooth connection."""
        device = MagicMock()
        device.connections = {(dr.CONNECTION_BLUETOOTH, "AA:BB:CC:DD:EE:FF")}
        device.config_entries = ["entry_1"]
        return device

    @pytest.fixture
    def mock_config_entry(self):
        """Create a mock ATC MiThermometer config entry."""
        entry = MagicMock()
        entry.domain = DOMAIN
        entry.data = {CONF_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX}
        return entry

    @pytest.fixture
    def mock_firmware_manager(self):
        """Create a mock FirmwareManager with a distinct current version."""
        manager = MagicMock()
        manager.get_current_version = AsyncMock(return_value="4.3")
        manager.get_release_by_version = AsyncMock(
            return_value=FirmwareRelease(
                version="v5.8",
                download_url="https://example.com/firmware.bin",
                release_url="https://example.com/release",
            )
        )
        manager.apply_firmware_update = AsyncMock(return_value=True)
        return manager

    async def test_device_not_found(self, hass: HomeAssistant, mock_call):
        """Test error when device_id doesn't resolve to a registry entry."""
        mock_device_registry = MagicMock()
        mock_device_registry.async_get = MagicMock(return_value=None)

        with (
            patch(
                "custom_components.atc_mithermometer.dr.async_get",
                return_value=mock_device_registry,
            ),
            pytest.raises(HomeAssistantError, match="not found"),
        ):
            await _async_apply_firmware(hass, mock_call)

    async def test_no_bluetooth_mac_address(self, hass: HomeAssistant, mock_call):
        """Test error when the device has no Bluetooth connection."""
        device = MagicMock()
        device.connections = set()

        mock_device_registry = MagicMock()
        mock_device_registry.async_get = MagicMock(return_value=device)

        with (
            patch(
                "custom_components.atc_mithermometer.dr.async_get",
                return_value=mock_device_registry,
            ),
            pytest.raises(HomeAssistantError, match="No Bluetooth MAC address"),
        ):
            await _async_apply_firmware(hass, mock_call)

    async def test_no_matching_config_entry(
        self, hass: HomeAssistant, mock_call, mock_device
    ):
        """Test error when the device has no ATC MiThermometer config entry."""
        mock_device_registry = MagicMock()
        mock_device_registry.async_get = MagicMock(return_value=mock_device)

        with (
            patch(
                "custom_components.atc_mithermometer.dr.async_get",
                return_value=mock_device_registry,
            ),
            patch.object(hass.config_entries, "async_get_entry", return_value=None),
            pytest.raises(HomeAssistantError, match="No ATC MiThermometer config"),
        ):
            await _async_apply_firmware(hass, mock_call)

    async def test_already_at_desired_version_skips_update(
        self,
        hass: HomeAssistant,
        mock_call,
        mock_device,
        mock_config_entry,
        mock_firmware_manager,
    ):
        """Test that a matching current version skips the update entirely."""
        mock_call.data = {"device_id": "device_1", "desired_version": "v4.3"}
        mock_firmware_manager.get_current_version = AsyncMock(return_value="4.3")

        mock_device_registry = MagicMock()
        mock_device_registry.async_get = MagicMock(return_value=mock_device)

        with (
            patch(
                "custom_components.atc_mithermometer.dr.async_get",
                return_value=mock_device_registry,
            ),
            patch.object(
                hass.config_entries,
                "async_get_entry",
                return_value=mock_config_entry,
            ),
            patch(
                "custom_components.atc_mithermometer.FirmwareManager",
                return_value=mock_firmware_manager,
            ),
        ):
            await _async_apply_firmware(hass, mock_call)

        mock_firmware_manager.get_release_by_version.assert_not_called()
        mock_firmware_manager.apply_firmware_update.assert_not_called()

    async def test_unknown_current_version_still_proceeds(
        self,
        hass: HomeAssistant,
        mock_call,
        mock_device,
        mock_config_entry,
        mock_firmware_manager,
    ):
        """Test that an undetectable current version doesn't block the update."""
        mock_firmware_manager.get_current_version = AsyncMock(return_value=None)

        mock_device_registry = MagicMock()
        mock_device_registry.async_get = MagicMock(return_value=mock_device)

        with (
            patch(
                "custom_components.atc_mithermometer.dr.async_get",
                return_value=mock_device_registry,
            ),
            patch.object(
                hass.config_entries,
                "async_get_entry",
                return_value=mock_config_entry,
            ),
            patch(
                "custom_components.atc_mithermometer.FirmwareManager",
                return_value=mock_firmware_manager,
            ),
        ):
            await _async_apply_firmware(hass, mock_call)

        mock_firmware_manager.apply_firmware_update.assert_called_once()

    async def test_invalid_firmware_source(
        self, hass: HomeAssistant, mock_call, mock_device, mock_firmware_manager
    ):
        """Test error when the config entry has an invalid firmware source."""
        config_entry = MagicMock()
        config_entry.domain = DOMAIN
        config_entry.data = {CONF_FIRMWARE_SOURCE: "not_a_real_source"}

        mock_device_registry = MagicMock()
        mock_device_registry.async_get = MagicMock(return_value=mock_device)

        with (
            patch(
                "custom_components.atc_mithermometer.dr.async_get",
                return_value=mock_device_registry,
            ),
            patch.object(
                hass.config_entries, "async_get_entry", return_value=config_entry
            ),
            patch(
                "custom_components.atc_mithermometer.FirmwareManager",
                return_value=mock_firmware_manager,
            ),
            pytest.raises(HomeAssistantError, match="Invalid firmware source"),
        ):
            await _async_apply_firmware(hass, mock_call)

    async def test_version_not_found_error_names_the_repo(
        self,
        hass: HomeAssistant,
        mock_call,
        mock_device,
        mock_config_entry,
        mock_firmware_manager,
    ):
        """Test the not-found error explains it must match a real release tag.

        Regression test for the confusing original message - doesn't pin
        exact wording, just that it points at the real repo/releases page
        rather than just repeating the version string back.
        """
        mock_firmware_manager.get_release_by_version = AsyncMock(return_value=None)

        mock_device_registry = MagicMock()
        mock_device_registry.async_get = MagicMock(return_value=mock_device)

        with (
            patch(
                "custom_components.atc_mithermometer.dr.async_get",
                return_value=mock_device_registry,
            ),
            patch.object(
                hass.config_entries,
                "async_get_entry",
                return_value=mock_config_entry,
            ),
            patch(
                "custom_components.atc_mithermometer.FirmwareManager",
                return_value=mock_firmware_manager,
            ),
            pytest.raises(
                HomeAssistantError,
                match="pvvx/ATC_MiThermometer/releases",
            ),
        ):
            await _async_apply_firmware(hass, mock_call)

    async def test_version_lookup_failure_propagates_as_is(
        self,
        hass: HomeAssistant,
        mock_call,
        mock_device,
        mock_config_entry,
        mock_firmware_manager,
    ):
        """A lookup failure (as opposed to a confirmed 404) must not be
        reworded into the "no release tagged" message - that would
        confidently claim something false about a transient failure.
        """
        mock_firmware_manager.get_release_by_version = AsyncMock(
            side_effect=HomeAssistantError("GitHub API rate limit exceeded")
        )

        mock_device_registry = MagicMock()
        mock_device_registry.async_get = MagicMock(return_value=mock_device)

        with (
            patch(
                "custom_components.atc_mithermometer.dr.async_get",
                return_value=mock_device_registry,
            ),
            patch.object(
                hass.config_entries,
                "async_get_entry",
                return_value=mock_config_entry,
            ),
            patch(
                "custom_components.atc_mithermometer.FirmwareManager",
                return_value=mock_firmware_manager,
            ),
            pytest.raises(HomeAssistantError, match="rate limit exceeded"),
        ):
            await _async_apply_firmware(hass, mock_call)

    async def test_success_applies_firmware(
        self,
        hass: HomeAssistant,
        mock_call,
        mock_device,
        mock_config_entry,
        mock_firmware_manager,
    ):
        """Test the full happy path applies the located release."""
        mock_device_registry = MagicMock()
        mock_device_registry.async_get = MagicMock(return_value=mock_device)

        with (
            patch(
                "custom_components.atc_mithermometer.dr.async_get",
                return_value=mock_device_registry,
            ),
            patch.object(
                hass.config_entries,
                "async_get_entry",
                return_value=mock_config_entry,
            ),
            patch(
                "custom_components.atc_mithermometer.FirmwareManager",
                return_value=mock_firmware_manager,
            ),
        ):
            await _async_apply_firmware(hass, mock_call)

        mock_firmware_manager.get_release_by_version.assert_called_once_with(
            FIRMWARE_SOURCE_PVVX, "v5.8"
        )
        mock_firmware_manager.apply_firmware_update.assert_called_once()
        call_args = mock_firmware_manager.apply_firmware_update.call_args
        assert call_args[0][0].version == "v5.8"

    async def test_firmware_source_override_takes_precedence(
        self,
        hass: HomeAssistant,
        mock_call,
        mock_device,
        mock_config_entry,
        mock_firmware_manager,
    ):
        """An explicit firmware_source in the call overrides the device's
        configured default (e.g. from the firmware panel), without changing
        the device's permanent configuration.
        """
        mock_call.data = {
            "device_id": "device_1",
            "desired_version": "v5.8",
            "firmware_source": FIRMWARE_SOURCE_ATC1441,
        }

        mock_device_registry = MagicMock()
        mock_device_registry.async_get = MagicMock(return_value=mock_device)

        with (
            patch(
                "custom_components.atc_mithermometer.dr.async_get",
                return_value=mock_device_registry,
            ),
            patch.object(
                hass.config_entries,
                "async_get_entry",
                return_value=mock_config_entry,
            ),
            patch(
                "custom_components.atc_mithermometer.FirmwareManager",
                return_value=mock_firmware_manager,
            ),
        ):
            await _async_apply_firmware(hass, mock_call)

        mock_firmware_manager.get_release_by_version.assert_called_once_with(
            FIRMWARE_SOURCE_ATC1441, "v5.8"
        )
        assert mock_config_entry.data[CONF_FIRMWARE_SOURCE] == FIRMWARE_SOURCE_PVVX

    async def test_firmware_source_defaults_to_config_entry(
        self,
        hass: HomeAssistant,
        mock_call,
        mock_device,
        mock_config_entry,
        mock_firmware_manager,
    ):
        """Omitting firmware_source falls back to the device's configured
        default, preserving the previous behavior.
        """
        assert "firmware_source" not in mock_call.data

        mock_device_registry = MagicMock()
        mock_device_registry.async_get = MagicMock(return_value=mock_device)

        with (
            patch(
                "custom_components.atc_mithermometer.dr.async_get",
                return_value=mock_device_registry,
            ),
            patch.object(
                hass.config_entries,
                "async_get_entry",
                return_value=mock_config_entry,
            ),
            patch(
                "custom_components.atc_mithermometer.FirmwareManager",
                return_value=mock_firmware_manager,
            ),
        ):
            await _async_apply_firmware(hass, mock_call)

        mock_firmware_manager.get_release_by_version.assert_called_once_with(
            FIRMWARE_SOURCE_PVVX, "v5.8"
        )
