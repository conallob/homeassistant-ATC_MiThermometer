"""Fixtures for ATC MiThermometer Manager tests."""
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations in Home Assistant."""
    yield


@pytest.fixture
async def hass(event_loop):
    """Create a Home Assistant instance for testing."""
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

    hass = HomeAssistant("/tmp")
    hass.config.config_dir = "/tmp"

    # Set up the necessary components
    await async_setup_component(hass, "homeassistant", {})

    # Initialize device and entity registries
    hass.data.setdefault(dr.DATA_REGISTRY, dr.DeviceRegistry(hass))

    # Start the hass instance
    await hass.async_block_till_done()

    yield hass

    # Cleanup
    await hass.async_stop()


@pytest.fixture
def mock_bluetooth_scanner():
    """Mock the bluetooth scanner."""
    scanner = MagicMock()
    scanner.discovered_devices = []
    return scanner


@pytest.fixture
def mock_device_registry():
    """Mock the device registry."""
    registry = MagicMock()
    registry.async_get = MagicMock(return_value=None)
    registry.async_get_device = MagicMock(return_value=None)
    registry.async_update_device = MagicMock()
    return registry


@pytest.fixture
def mock_aiohttp_session():
    """Mock aiohttp client session."""
    session = MagicMock()
    return session


@pytest.fixture
def mock_bleak_client():
    """Mock BleakClient."""
    client = MagicMock()
    client.is_connected = True
    client.write_gatt_char = MagicMock()
    return client


# Enable custom integrations for all tests
pytest_plugins = ["pytest_homeassistant_custom_component"]
