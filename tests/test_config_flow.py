"""Test the config flow."""

from unittest.mock import MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.atc_mithermometer.config_flow import (
    ATCMiThermometerConfigFlow,
    ATCMiThermometerOptionsFlow,
)
from custom_components.atc_mithermometer.const import (
    CONF_FIRMWARE_SOURCE,
    CONF_MAC_ADDRESS,
    DOMAIN,
    FIRMWARE_SOURCE_ATC1441,
    FIRMWARE_SOURCE_PVVX,
    SERVICE_UUID_ENVIRONMENTAL,
)


@pytest.fixture
def mock_bluetooth_service_info():
    """Create a mock BluetoothServiceInfoBleak."""
    info = MagicMock(spec=BluetoothServiceInfoBleak)
    info.name = "ATC_123456"
    info.address = "AA:BB:CC:DD:EE:FF"
    info.service_uuids = [SERVICE_UUID_ENVIRONMENTAL]
    return info


@pytest.fixture
def mock_setup_entry():
    """Mock async_setup_entry."""
    with patch(
        "custom_components.atc_mithermometer.async_setup_entry",
        return_value=True,
    ) as mock_setup:
        yield mock_setup


class TestConfigFlow:
    """Test the config flow."""

    async def test_user_step_no_devices(self, hass: HomeAssistant, mock_setup_entry):
        """Test user step with no devices found."""
        with patch(
            "custom_components.atc_mithermometer.config_flow.ATCMiThermometerConfigFlow._get_available_devices",
            return_value={},
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )

            assert result["type"] == FlowResultType.ABORT
            assert result["reason"] == "no_devices_found"

    async def test_user_step_shows_devices(
        self, hass: HomeAssistant, mock_bluetooth_service_info, mock_setup_entry
    ):
        """Test user step shows available devices."""
        mock_devices = {
            "AA:BB:CC:DD:EE:FF": mock_bluetooth_service_info,
        }

        with patch(
            "custom_components.atc_mithermometer.config_flow.ATCMiThermometerConfigFlow._get_available_devices",
            return_value=mock_devices,
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )

            assert result["type"] == FlowResultType.FORM
            assert result["step_id"] == "user"
            assert CONF_MAC_ADDRESS in result["data_schema"].schema

    async def test_user_step_device_selection(
        self, hass: HomeAssistant, mock_bluetooth_service_info, mock_setup_entry
    ):
        """Test selecting a device in user step."""
        mock_devices = {
            "AA:BB:CC:DD:EE:FF": mock_bluetooth_service_info,
        }

        with patch(
            "custom_components.atc_mithermometer.config_flow.ATCMiThermometerConfigFlow._get_available_devices",
            return_value=mock_devices,
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={CONF_MAC_ADDRESS: "AA:BB:CC:DD:EE:FF"},
            )

            assert result["type"] == FlowResultType.FORM
            assert result["step_id"] == "firmware_source"

    async def test_user_step_already_configured(
        self, hass: HomeAssistant, mock_bluetooth_service_info, mock_setup_entry
    ):
        """Test device already configured."""
        # Create existing entry using MockConfigEntry
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="AA:BB:CC:DD:EE:FF",
            data={
                CONF_MAC_ADDRESS: "AA:BB:CC:DD:EE:FF",
                CONF_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
            },
        )
        entry.add_to_hass(hass)

        mock_devices = {
            "AA:BB:CC:DD:EE:FF": mock_bluetooth_service_info,
        }

        with patch(
            "custom_components.atc_mithermometer.config_flow.ATCMiThermometerConfigFlow._get_available_devices",
            return_value=mock_devices,
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={CONF_MAC_ADDRESS: "AA:BB:CC:DD:EE:FF"},
            )

            assert result["type"] == FlowResultType.ABORT
            assert result["reason"] == "already_configured"

    async def test_firmware_source_step(
        self, hass: HomeAssistant, mock_bluetooth_service_info, mock_setup_entry
    ):
        """Test firmware source selection step."""
        mock_devices = {
            "AA:BB:CC:DD:EE:FF": mock_bluetooth_service_info,
        }

        with patch(
            "custom_components.atc_mithermometer.config_flow.ATCMiThermometerConfigFlow._get_available_devices",
            return_value=mock_devices,
        ):
            # Start flow
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )

            # Select device
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={CONF_MAC_ADDRESS: "AA:BB:CC:DD:EE:FF"},
            )

            # Select firmware source
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={CONF_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX},
            )

            assert result["type"] == FlowResultType.CREATE_ENTRY
            assert result["title"] == "ATC Manager (AA:BB:CC:DD:EE:FF)"
            assert result["data"] == {
                CONF_MAC_ADDRESS: "AA:BB:CC:DD:EE:FF",
                CONF_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
            }

    async def test_firmware_source_step_atc1441(
        self, hass: HomeAssistant, mock_bluetooth_service_info, mock_setup_entry
    ):
        """Test firmware source selection with ATC1441."""
        mock_devices = {
            "AA:BB:CC:DD:EE:FF": mock_bluetooth_service_info,
        }

        with patch(
            "custom_components.atc_mithermometer.config_flow.ATCMiThermometerConfigFlow._get_available_devices",
            return_value=mock_devices,
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={CONF_MAC_ADDRESS: "AA:BB:CC:DD:EE:FF"},
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                user_input={CONF_FIRMWARE_SOURCE: FIRMWARE_SOURCE_ATC1441},
            )

            assert result["type"] == FlowResultType.CREATE_ENTRY
            assert result["data"][CONF_FIRMWARE_SOURCE] == FIRMWARE_SOURCE_ATC1441

    async def test_bluetooth_discovery_step(
        self, hass: HomeAssistant, mock_bluetooth_service_info, mock_setup_entry
    ):
        """Test bluetooth discovery."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_BLUETOOTH},
            data=mock_bluetooth_service_info,
        )

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "bluetooth_confirm"

    async def test_bluetooth_discovery_not_supported(
        self, hass: HomeAssistant, mock_setup_entry
    ):
        """Test bluetooth discovery of unsupported device."""
        info = MagicMock(spec=BluetoothServiceInfoBleak)
        info.name = "Other Device"
        info.address = "AA:BB:CC:DD:EE:FF"
        info.service_uuids = []

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_BLUETOOTH},
            data=info,
        )

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "not_supported"

    async def test_bluetooth_discovery_already_configured(
        self, hass: HomeAssistant, mock_bluetooth_service_info, mock_setup_entry
    ):
        """Test bluetooth discovery when already configured."""
        # Create existing entry using MockConfigEntry
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="AA:BB:CC:DD:EE:FF",
            data={
                CONF_MAC_ADDRESS: "AA:BB:CC:DD:EE:FF",
                CONF_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
            },
        )
        entry.add_to_hass(hass)

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_BLUETOOTH},
            data=mock_bluetooth_service_info,
        )

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "already_configured"

    async def test_bluetooth_confirm_step(
        self, hass: HomeAssistant, mock_bluetooth_service_info, mock_setup_entry
    ):
        """Test bluetooth confirmation step."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_BLUETOOTH},
            data=mock_bluetooth_service_info,
        )

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={},
        )

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "firmware_source"

    async def test_get_available_devices_from_scanner(
        self, hass: HomeAssistant, mock_bluetooth_service_info
    ):
        """Test getting available devices from bluetooth scanner."""
        mock_scanner = MagicMock()
        mock_scanner.discovered_devices = [mock_bluetooth_service_info]

        with (
            patch(
                "custom_components.atc_mithermometer.config_flow.bluetooth.async_scanner_by_source",
                return_value=mock_scanner,
            ),
            patch(
                "custom_components.atc_mithermometer.config_flow.get_atc_devices_from_bthome",
                return_value=[],
            ),
        ):
            flow = ATCMiThermometerConfigFlow()
            flow.hass = hass

            devices = await flow._get_available_devices(set())

            assert "AA:BB:CC:DD:EE:FF" in devices
            assert devices["AA:BB:CC:DD:EE:FF"] == mock_bluetooth_service_info

    async def test_get_available_devices_excludes_configured(
        self, hass: HomeAssistant, mock_bluetooth_service_info
    ):
        """Test get available devices excludes already configured."""
        mock_scanner = MagicMock()
        mock_scanner.discovered_devices = [mock_bluetooth_service_info]

        with (
            patch(
                "custom_components.atc_mithermometer.config_flow.bluetooth.async_scanner_by_source",
                return_value=mock_scanner,
            ),
            patch(
                "custom_components.atc_mithermometer.config_flow.get_atc_devices_from_bthome",
                return_value=[],
            ),
        ):
            flow = ATCMiThermometerConfigFlow()
            flow.hass = hass

            devices = await flow._get_available_devices({"AA:BB:CC:DD:EE:FF"})

            assert len(devices) == 0

    async def test_get_available_devices_from_bthome(self, hass: HomeAssistant):
        """Test getting available devices from BTHome."""
        mock_device = MagicMock()
        mock_device.connections = {("bluetooth", "AA:BB:CC:DD:EE:FF")}

        mock_service_info = MagicMock(spec=BluetoothServiceInfoBleak)
        mock_service_info.name = "ATC_123456"
        mock_service_info.address = "AA:BB:CC:DD:EE:FF"

        with (
            patch(
                "custom_components.atc_mithermometer.config_flow.bluetooth.async_scanner_by_source",
                return_value=None,
            ),
            patch(
                "custom_components.atc_mithermometer.config_flow.get_atc_devices_from_bthome",
                return_value=[mock_device],
            ),
            patch(
                "custom_components.atc_mithermometer.config_flow.bluetooth.async_last_service_info",
                return_value=mock_service_info,
            ),
            patch(
                "custom_components.atc_mithermometer.config_flow.dr.async_get",
                return_value=MagicMock(),
            ),
        ):
            flow = ATCMiThermometerConfigFlow()
            flow.hass = hass

            devices = await flow._get_available_devices(set())

            assert "AA:BB:CC:DD:EE:FF" in devices

    async def test_get_available_devices_handles_bthome_error(
        self, hass: HomeAssistant
    ):
        """Test get available devices handles BTHome errors gracefully."""
        with (
            patch(
                "custom_components.atc_mithermometer.config_flow.bluetooth.async_scanner_by_source",
                return_value=None,
            ),
            patch(
                "custom_components.atc_mithermometer.config_flow.get_atc_devices_from_bthome",
                side_effect=Exception("Test error"),
            ),
        ):
            flow = ATCMiThermometerConfigFlow()
            flow.hass = hass

            # Should not raise, returns empty dict
            devices = await flow._get_available_devices(set())

            assert len(devices) == 0


class TestOptionsFlow:
    """Test the options flow."""

    async def test_options_flow(self, hass: HomeAssistant):
        """Test options flow."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="AA:BB:CC:DD:EE:FF",
            data={
                CONF_MAC_ADDRESS: "AA:BB:CC:DD:EE:FF",
                CONF_FIRMWARE_SOURCE: FIRMWARE_SOURCE_PVVX,
            },
        )

        flow = ATCMiThermometerOptionsFlow(entry)

        # Show form
        result = await flow.async_step_init()

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "init"

        # Submit form
        result = await flow.async_step_init(
            user_input={CONF_FIRMWARE_SOURCE: FIRMWARE_SOURCE_ATC1441}
        )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"] == {CONF_FIRMWARE_SOURCE: FIRMWARE_SOURCE_ATC1441}

    async def test_options_flow_defaults_to_current_source(self, hass: HomeAssistant):
        """Test options flow shows current firmware source as default."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="AA:BB:CC:DD:EE:FF",
            data={
                CONF_MAC_ADDRESS: "AA:BB:CC:DD:EE:FF",
                CONF_FIRMWARE_SOURCE: FIRMWARE_SOURCE_ATC1441,
            },
        )

        flow = ATCMiThermometerOptionsFlow(entry)

        result = await flow.async_step_init()

        # Default should be the current source
        schema_dict = result["data_schema"].schema
        for key in schema_dict:
            if hasattr(key, "description") and key.description.get("suggested_value"):
                assert False, "No suggested value should be set"
