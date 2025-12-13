"""Constants for the ATC MiThermometer Manager integration."""
from typing import Final

DOMAIN: Final = "atc_mithermometer"

# Configuration
CONF_FIRMWARE_SOURCE: Final = "firmware_source"
CONF_MAC_ADDRESS: Final = "mac_address"

# Firmware sources
FIRMWARE_SOURCE_PVVX: Final = "pvvx"
FIRMWARE_SOURCE_ATC1441: Final = "atc1441"

FIRMWARE_SOURCES: Final = {
    FIRMWARE_SOURCE_PVVX: {
        "name": "pvvx (Most Active)",
        "repo": "pvvx/ATC_MiThermometer",
        "api_url": "https://api.github.com/repos/pvvx/ATC_MiThermometer/releases/latest",
        "asset_pattern": "ATC_.*\\.bin$",
    },
    FIRMWARE_SOURCE_ATC1441: {
        "name": "atc1441 (Original)",
        "repo": "atc1441/ATC_MiThermometer",
        "api_url": "https://api.github.com/repos/atc1441/ATC_MiThermometer/releases/latest",
        "asset_pattern": ".*\\.bin$",
    },
}

# BLE Service UUIDs
SERVICE_UUID_ENVIRONMENTAL: Final = "0000181a-0000-1000-8000-00805f9b34fb"
SERVICE_UUID_DEVICE_INFO: Final = "0000180a-0000-1000-8000-00805f9b34fb"

# Characteristic UUIDs for OTA
CHAR_UUID_OTA_CONTROL: Final = "00010203-0405-0607-0809-0a0b0c0d1912"
CHAR_UUID_OTA_DATA: Final = "00010203-0405-0607-0809-0a0b0c0d1910"

# Update settings
UPDATE_CHECK_INTERVAL: Final = 3600  # Check for updates every hour
FLASH_TIMEOUT: Final = 300  # 5 minutes timeout for flashing
CHUNK_SIZE: Final = 244  # BLE MTU size for firmware chunks

# Device identification
ATC_NAME_PREFIXES: Final = ["ATC_", "LYWSD03MMC"]
PVVX_DEVICE_TYPE: Final = 0x0A1C  # Device type in advertisements
ATC1441_DEVICE_TYPE: Final = 0x181A

# Attributes
ATTR_CURRENT_VERSION: Final = "current_version"
ATTR_LATEST_VERSION: Final = "latest_version"
ATTR_FIRMWARE_SOURCE: Final = "firmware_source"
ATTR_RELEASE_URL: Final = "release_url"
ATTR_INSTALLED_VERSION: Final = "installed_version"


def normalize_mac(mac: str) -> str:
    """Normalize MAC address to Home Assistant standard format.

    Home Assistant stores Bluetooth MAC addresses in uppercase format
    with colons as separators (e.g., "A4:C1:38:12:34:56").

    Args:
        mac: MAC address in any case

    Returns:
        MAC address in uppercase
    """
    return mac.upper()
