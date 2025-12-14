"""Test the __init__ module."""

from unittest.mock import MagicMock, patch

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.atc_mithermometer import (
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
    FIRMWARE_SOURCE_PVVX,
    SERVICE_UUID_ENVIRONMENTAL,
)


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

    with patch(
        "custom_components.atc_mithermometer.get_bthome_device_by_mac",
        return_value=None,
    ), patch.object(hass.config_entries, "async_forward_entry_setups") as mock_forward:
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
        mock_forward.assert_called_once_with(entry, [Platform.UPDATE])


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

    with patch(
        "custom_components.atc_mithermometer.get_bthome_device_by_mac",
        return_value=mock_device,
    ), patch(
        "custom_components.atc_mithermometer.dr.async_get",
        return_value=mock_device_registry,
    ), patch.object(
        hass.config_entries, "async_forward_entry_setups"
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

    with patch(
        "custom_components.atc_mithermometer.get_bthome_device_by_mac",
        return_value=mock_device,
    ), patch(
        "custom_components.atc_mithermometer.dr.async_get",
        return_value=mock_device_registry,
    ), patch.object(
        hass.config_entries, "async_forward_entry_setups"
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
        mock_unload.assert_called_once_with(entry, [Platform.UPDATE])


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

    with patch.object(
        hass.config_entries,
        "async_entries",
        return_value=[mock_entry],
    ), patch(
        "custom_components.atc_mithermometer.dr.async_get",
        return_value=mock_device_registry,
    ), patch(
        "custom_components.atc_mithermometer.dr.async_entries_for_config_entry",
        return_value=[mock_device1, mock_device2, mock_device3],
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

    with patch.object(
        hass.config_entries,
        "async_entries",
        return_value=[mock_entry1, mock_entry2],
    ), patch(
        "custom_components.atc_mithermometer.dr.async_get",
        return_value=mock_device_registry,
    ), patch(
        "custom_components.atc_mithermometer.dr.async_entries_for_config_entry",
        return_value=[mock_device],
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

    with patch(
        "custom_components.atc_mithermometer.dr.async_get",
        return_value=mock_device_registry,
    ), patch.object(
        hass.config_entries,
        "async_get_entry",
        return_value=mock_entry,
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

    with patch(
        "custom_components.atc_mithermometer.dr.async_get",
        return_value=mock_device_registry,
    ), patch.object(
        hass.config_entries,
        "async_get_entry",
        return_value=mock_entry,
    ):
        result = await get_bthome_device_by_mac(hass, mac_address)

        assert result is None


async def test_get_bthome_device_by_mac_invalid_mac(hass: HomeAssistant):
    """Test getting device with invalid MAC address."""
    mac_address = "invalid_mac"

    result = await get_bthome_device_by_mac(hass, mac_address)

    assert result is None
