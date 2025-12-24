"""Test the sensor platform."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bleak import BleakError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.atc_mithermometer.const import (
    ATTR_CURRENT_VERSION,
    ATTR_FIRMWARE_SOURCE,
    CONF_FIRMWARE_SOURCE,
    CONF_MAC_ADDRESS,
    FIRMWARE_SOURCE_PVVX,
)
from custom_components.atc_mithermometer.sensor import (
    ATCFirmwareCoordinator,
    ATCFirmwareVersionSensor,
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
    """Test setting up the sensor platform."""
    with patch(
        "custom_components.atc_mithermometer.sensor.FirmwareManager",
        return_value=mock_firmware_manager,
    ), patch(
        "custom_components.atc_mithermometer.sensor.get_bthome_device_by_mac",
        return_value=mock_bthome_device,
    ):
        async_add_entities = MagicMock()

        await async_setup_entry(hass, mock_config_entry, async_add_entities)

        assert async_add_entities.called
        entities = async_add_entities.call_args[0][0]
        assert len(entities) == 1
        assert isinstance(entities[0], ATCFirmwareVersionSensor)


class TestATCFirmwareCoordinator:
    """Test ATCFirmwareCoordinator."""

    async def test_coordinator_init(self, hass: HomeAssistant, mock_firmware_manager):
        """Test coordinator initialization."""
        coordinator = ATCFirmwareCoordinator(
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
        coordinator = ATCFirmwareCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )

        data = await coordinator._async_update_data()

        assert data[ATTR_CURRENT_VERSION] == "v1.0.0"
        assert data[ATTR_FIRMWARE_SOURCE] == FIRMWARE_SOURCE_PVVX

        # Verify mocked method was called
        mock_firmware_manager.get_current_version.assert_called_once()

    async def test_coordinator_update_no_version(
        self, hass: HomeAssistant, mock_firmware_manager
    ):
        """Test coordinator update when version cannot be determined."""
        mock_firmware_manager.get_current_version = AsyncMock(return_value=None)

        coordinator = ATCFirmwareCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )

        data = await coordinator._async_update_data()

        # Should still succeed but with None version
        assert data[ATTR_CURRENT_VERSION] is None
        assert data[ATTR_FIRMWARE_SOURCE] == FIRMWARE_SOURCE_PVVX

    async def test_coordinator_update_ble_error(
        self, hass: HomeAssistant, mock_firmware_manager
    ):
        """Test coordinator update with BLE error."""
        mock_firmware_manager.get_current_version = AsyncMock(
            side_effect=BleakError("BLE connection failed")
        )

        coordinator = ATCFirmwareCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )

        with pytest.raises(UpdateFailed, match="Error fetching firmware version"):
            await coordinator._async_update_data()

    async def test_coordinator_update_homeassistant_error(
        self, hass: HomeAssistant, mock_firmware_manager
    ):
        """Test coordinator update with Home Assistant error."""
        mock_firmware_manager.get_current_version = AsyncMock(
            side_effect=HomeAssistantError("Device not found")
        )

        coordinator = ATCFirmwareCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )

        with pytest.raises(UpdateFailed, match="Error fetching firmware version"):
            await coordinator._async_update_data()


class TestATCFirmwareVersionSensor:
    """Test ATCFirmwareVersionSensor entity."""

    async def test_sensor_init_with_bthome_device(
        self,
        hass: HomeAssistant,
        mock_config_entry,
        mock_firmware_manager,
        mock_bthome_device,
    ):
        """Test sensor initialization with BTHome device."""
        coordinator = ATCFirmwareCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )
        coordinator.data = {
            ATTR_CURRENT_VERSION: "v1.0.0",
            ATTR_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
        }

        with patch(
            "custom_components.atc_mithermometer.sensor.create_device_info"
        ) as mock_create_device_info:
            sensor = ATCFirmwareVersionSensor(
                coordinator, mock_config_entry, mock_bthome_device
            )

            assert sensor.unique_id == "AA:BB:CC:DD:EE:FF_firmware_version"
            assert sensor.name == "Firmware Version"
            # Verify create_device_info was called with correct args
            mock_create_device_info.assert_called_once_with(
                "AA:BB:CC:DD:EE:FF", mock_bthome_device
            )

    async def test_sensor_init_without_bthome_device(
        self, hass: HomeAssistant, mock_config_entry, mock_firmware_manager
    ):
        """Test sensor initialization without BTHome device."""
        coordinator = ATCFirmwareCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )
        coordinator.data = {
            ATTR_CURRENT_VERSION: "v1.0.0",
            ATTR_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
        }

        with patch(
            "custom_components.atc_mithermometer.sensor.create_device_info"
        ) as mock_create_device_info:
            sensor = ATCFirmwareVersionSensor(
                coordinator, mock_config_entry, None
            )

            assert sensor.unique_id == "AA:BB:CC:DD:EE:FF_firmware_version"
            # Verify create_device_info was called with None for bthome_device
            mock_create_device_info.assert_called_once_with(
                "AA:BB:CC:DD:EE:FF", None
            )

    async def test_native_value_with_version(
        self, hass: HomeAssistant, mock_config_entry, mock_firmware_manager
    ):
        """Test native_value property with valid version."""
        coordinator = ATCFirmwareCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )
        coordinator.data = {
            ATTR_CURRENT_VERSION: "v1.0.0",
            ATTR_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
        }

        sensor = ATCFirmwareVersionSensor(
            coordinator, mock_config_entry
        )

        assert sensor.native_value == "v1.0.0"

    async def test_native_value_without_version(
        self, hass: HomeAssistant, mock_config_entry, mock_firmware_manager
    ):
        """Test native_value property when version is unavailable."""
        coordinator = ATCFirmwareCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )
        coordinator.data = {
            ATTR_CURRENT_VERSION: None,
            ATTR_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
        }

        sensor = ATCFirmwareVersionSensor(
            coordinator, mock_config_entry
        )

        # Should return None when version is unavailable, letting HA show "Unavailable"
        assert sensor.native_value is None

    async def test_native_value_with_empty_string(
        self, hass: HomeAssistant, mock_config_entry, mock_firmware_manager
    ):
        """Test native_value property with empty string version."""
        coordinator = ATCFirmwareCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )
        coordinator.data = {
            ATTR_CURRENT_VERSION: "",
            ATTR_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
        }

        sensor = ATCFirmwareVersionSensor(
            coordinator, mock_config_entry
        )

        # Empty string should also return None
        assert sensor.native_value is None

    async def test_extra_state_attributes(
        self, hass: HomeAssistant, mock_config_entry, mock_firmware_manager
    ):
        """Test extra_state_attributes property."""
        coordinator = ATCFirmwareCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )
        coordinator.data = {
            ATTR_CURRENT_VERSION: "v1.0.0",
            ATTR_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
        }

        sensor = ATCFirmwareVersionSensor(
            coordinator, mock_config_entry
        )

        attrs = sensor.extra_state_attributes

        assert ATTR_FIRMWARE_SOURCE in attrs
        assert attrs[ATTR_FIRMWARE_SOURCE] == FIRMWARE_SOURCE_PVVX
        assert "firmware_source_name" in attrs
        assert "pvvx" in attrs["firmware_source_name"].lower()

    async def test_coordinator_data_updates(
        self, hass: HomeAssistant, mock_config_entry, mock_firmware_manager
    ):
        """Test sensor reflects coordinator data updates."""
        coordinator = ATCFirmwareCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )
        coordinator.data = {
            ATTR_CURRENT_VERSION: "v1.0.0",
            ATTR_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
        }

        sensor = ATCFirmwareVersionSensor(
            coordinator, mock_config_entry
        )

        # Initial value
        assert sensor.native_value == "v1.0.0"

        # Update coordinator data
        coordinator.data = {
            ATTR_CURRENT_VERSION: "v1.2.3",
            ATTR_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
        }

        # Sensor should reflect new value
        assert sensor.native_value == "v1.2.3"

    async def test_sensor_handles_missing_data_keys(
        self, hass: HomeAssistant, mock_config_entry, mock_firmware_manager
    ):
        """Test sensor handles missing keys in coordinator data gracefully."""
        coordinator = ATCFirmwareCoordinator(
            hass,
            mock_firmware_manager,
            FIRMWARE_SOURCE_PVVX,
            "AA:BB:CC:DD:EE:FF",
        )
        # Empty coordinator data
        coordinator.data = {}

        sensor = ATCFirmwareVersionSensor(
            coordinator, mock_config_entry
        )

        # Should handle missing keys gracefully by returning None
        assert sensor.native_value is None
        attrs = sensor.extra_state_attributes
        assert ATTR_FIRMWARE_SOURCE in attrs
        assert attrs[ATTR_FIRMWARE_SOURCE] is None
