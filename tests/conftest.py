"""Fixtures for ATC MiThermometer Manager tests."""

# Enable pytest-homeassistant-custom-component plugin
# This provides the hass fixture, enable_custom_integrations, and other Home Assistant testing utilities
pytest_plugins = ["pytest_homeassistant_custom_component"]

from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for all tests.

    This fixture uses the enable_custom_integrations fixture from
    pytest-homeassistant-custom-component to allow testing custom components.
    """
    yield


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
    """Mock BleakClient for Bluetooth LE operations."""
    client = MagicMock()
    client.is_connected = True
    client.write_gatt_char = MagicMock()
    return client
