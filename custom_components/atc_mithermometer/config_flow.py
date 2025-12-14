"""Config flow for ATC MiThermometer Manager integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import device_registry as dr

from . import get_atc_devices_from_bthome, is_atc_mithermometer
from .const import (
    CONF_FIRMWARE_SOURCE,
    CONF_MAC_ADDRESS,
    DOMAIN,
    FIRMWARE_SOURCE_PVVX,
    FIRMWARE_SOURCES,
)

_LOGGER = logging.getLogger(__name__)


class ATCMiThermometerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ATC MiThermometer Manager."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}
        self._selected_device: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        # Get discovered Bluetooth devices
        current_addresses = self._async_current_ids()
        discovered_devices = await self._get_available_devices(current_addresses)

        if not discovered_devices:
            return self.async_abort(reason="no_devices_found")

        if user_input is not None:
            mac_address = user_input[CONF_MAC_ADDRESS]
            self._selected_device = mac_address

            # Check if already configured
            await self.async_set_unique_id(mac_address)
            self._abort_if_unique_id_configured()

            return await self.async_step_firmware_source()

        # Create selection schema
        device_names = {
            mac: f"{info.name or 'Unknown'} ({mac})"
            for mac, info in discovered_devices.items()
        }

        schema = vol.Schema(
            {
                vol.Required(CONF_MAC_ADDRESS): vol.In(device_names),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={"device_count": str(len(discovered_devices))},
        )

    async def async_step_firmware_source(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle firmware source selection."""
        if user_input is not None:
            return self.async_create_entry(
                title=f"ATC Manager ({self._selected_device})",
                data={
                    CONF_MAC_ADDRESS: self._selected_device,
                    CONF_FIRMWARE_SOURCE: user_input[CONF_FIRMWARE_SOURCE],
                },
            )

        # Create firmware source selection schema
        firmware_options = {
            source_id: source_info["name"]
            for source_id, source_info in FIRMWARE_SOURCES.items()
        }

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_FIRMWARE_SOURCE,
                    default=FIRMWARE_SOURCE_PVVX,
                ): vol.In(firmware_options),
            }
        )

        return self.async_show_form(
            step_id="firmware_source",
            data_schema=schema,
            description_placeholders={"device": self._selected_device or "Unknown"},
        )

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle bluetooth discovery."""
        _LOGGER.debug("Discovered device: %s", discovery_info)

        # Check if device is ATC MiThermometer
        if not is_atc_mithermometer(
            discovery_info.name,
            [str(uuid) for uuid in discovery_info.service_uuids],
        ):
            return self.async_abort(reason="not_supported")

        mac_address = discovery_info.address
        await self.async_set_unique_id(mac_address)
        self._abort_if_unique_id_configured()

        self._selected_device = mac_address
        self._discovered_devices[mac_address] = discovery_info

        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm bluetooth discovery."""
        if user_input is not None:
            return await self.async_step_firmware_source()

        device_info = self._discovered_devices.get(self._selected_device)
        device_name = device_info.name if device_info else "Unknown"

        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={
                "name": device_name,
                "address": self._selected_device or "Unknown",
            },
        )

    async def _get_available_devices(
        self, current_addresses: set[str]
    ) -> dict[str, BluetoothServiceInfoBleak]:
        """Get available ATC MiThermometer devices."""
        discovered_devices = {}

        # Get devices from Bluetooth scanner
        scanner = bluetooth.async_scanner_by_source(self.hass, bluetooth.MONOTONIC_TIME)
        if scanner:
            for service_info in scanner.discovered_devices:
                if service_info.address in current_addresses:
                    continue

                if is_atc_mithermometer(
                    service_info.name,
                    [str(uuid) for uuid in service_info.service_uuids],
                ):
                    discovered_devices[service_info.address] = service_info

        # Also check BTHome integration devices
        try:
            bthome_devices = await get_atc_devices_from_bthome(self.hass)

            for device in bthome_devices:
                for connection in device.connections:
                    if connection[0] == dr.CONNECTION_BLUETOOTH:
                        mac = connection[1]
                        if (
                            mac not in current_addresses
                            and mac not in discovered_devices
                        ):
                            # Try to get service info from bluetooth
                            service_info = bluetooth.async_last_service_info(
                                self.hass, mac, connectable=True
                            )
                            if service_info:
                                discovered_devices[mac] = service_info
        except Exception as err:
            _LOGGER.debug("Error getting BTHome devices: %s", err)

        return discovered_devices

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ATCMiThermometerOptionsFlow:
        """Get the options flow for this handler."""
        return ATCMiThermometerOptionsFlow(config_entry)


class ATCMiThermometerOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for ATC MiThermometer Manager."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        firmware_options = {
            source_id: source_info["name"]
            for source_id, source_info in FIRMWARE_SOURCES.items()
        }

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_FIRMWARE_SOURCE,
                    default=self.config_entry.data.get(
                        CONF_FIRMWARE_SOURCE, FIRMWARE_SOURCE_PVVX
                    ),
                ): vol.In(firmware_options),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
