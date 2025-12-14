"""Constants for the ATC MiThermometer Manager integration."""
from datetime import timedelta
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
UPDATE_CHECK_INTERVAL: Final = timedelta(hours=1)  # Check for updates every hour
FLASH_TIMEOUT: Final = 300  # 5 minutes timeout for flashing
CHUNK_SIZE: Final = 244  # BLE MTU size for firmware chunks

# Firmware validation
MIN_FIRMWARE_SIZE: Final = 1024  # Minimum valid firmware size (1KB)
MAX_FIRMWARE_SIZE: Final = 512 * 1024  # Maximum valid firmware size (512KB)

# OTA timing constants (in seconds)
OTA_CHUNK_DELAY: Final = 0.02  # Delay between firmware chunks
OTA_COMMAND_DELAY: Final = 0.5  # Delay after OTA commands

# Progress tracking constants (percentage)
PROGRESS_DOWNLOAD_START: Final = 10
PROGRESS_DOWNLOAD_COMPLETE: Final = 30
PROGRESS_FLASH_RANGE: Final = 60  # 30% to 90%
PROGRESS_COMPLETE: Final = 100

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

    This function handles various input formats:
    - aa:bb:cc:dd:ee:ff (lowercase with colons)
    - AA-BB-CC-DD-EE-FF (uppercase with dashes)
    - aabbccddeeff (no separators)
    - AA.BB.CC.DD.EE.FF (with dots)

    Args:
        mac: MAC address in any format

    Returns:
        MAC address in uppercase with colons (XX:XX:XX:XX:XX:XX)

    Raises:
        ValueError: If MAC address contains invalid characters or wrong length
    """
    # Remove any separators and convert to uppercase
    mac_clean = mac.replace(":", "").replace("-", "").replace(".", "").upper()

    # Validate length and hex characters
    if len(mac_clean) != 12:
        raise ValueError(f"Invalid MAC address length: {mac} (expected 12 hex chars)")

    # Validate that all characters are valid hex
    try:
        int(mac_clean, 16)
    except ValueError as err:
        raise ValueError(f"Invalid MAC address: {mac} (non-hex characters)") from err

    # Add colons every 2 characters
    return ":".join(mac_clean[i : i + 2] for i in range(0, 12, 2))
