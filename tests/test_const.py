"""Test the const module."""

import pytest

from custom_components.atc_mithermometer.const import (
    ATC_NAME_PREFIXES,
    CHAR_UUID_OTA,
    DOMAIN,
    FIRMWARE_SOURCE_ATC1441,
    FIRMWARE_SOURCE_PVVX,
    FIRMWARE_SOURCES,
    OTA_CMD_END,
    OTA_CMD_START,
    OTA_PACKET_PAYLOAD_SIZE,
    OTA_SECTOR_SIZE,
    OTA_TRAILER_SEQ,
    SERVICE_UUID_ENVIRONMENTAL,
    normalize_mac,
)


def test_domain():
    """Test DOMAIN constant."""
    assert DOMAIN == "atc_mithermometer"


def test_firmware_sources():
    """Test firmware source constants."""
    assert FIRMWARE_SOURCE_PVVX == "pvvx"
    assert FIRMWARE_SOURCE_ATC1441 == "atc1441"

    # Verify firmware sources structure
    assert FIRMWARE_SOURCE_PVVX in FIRMWARE_SOURCES
    assert FIRMWARE_SOURCE_ATC1441 in FIRMWARE_SOURCES

    # Verify pvvx source has required fields
    pvvx = FIRMWARE_SOURCES[FIRMWARE_SOURCE_PVVX]
    assert "name" in pvvx
    assert "repo" in pvvx
    assert "api_url" in pvvx
    assert "asset_pattern" in pvvx
    assert pvvx["repo"] == "pvvx/ATC_MiThermometer"

    # Verify atc1441 source has required fields
    atc1441 = FIRMWARE_SOURCES[FIRMWARE_SOURCE_ATC1441]
    assert "name" in atc1441
    assert "repo" in atc1441
    assert "api_url" in atc1441
    assert "asset_pattern" in atc1441
    assert atc1441["repo"] == "atc1441/ATC_MiThermometer"


def test_service_uuids():
    """Test BLE service UUID constants."""
    assert SERVICE_UUID_ENVIRONMENTAL == "0000181a-0000-1000-8000-00805f9b34fb"


def test_device_name_prefixes():
    """Test ATC device name prefixes."""
    assert "ATC_" in ATC_NAME_PREFIXES
    assert "LYWSD03MMC" in ATC_NAME_PREFIXES


def test_ota_characteristic_uuid():
    """CHAR_UUID_OTA must be the real GATT characteristic UUID.

    Verified against pvvx/ATC_MiThermometer's own GATT attribute table
    (src/app_att.c: TELINK_SPP_DATA_OTA, SDK gatt_uuid.h). A future edit
    accidentally reverting to a wrong UUID (e.g. the OTA service UUID or
    the unrelated SPP service UUID this replaced) should fail this test
    close to the source, rather than only failing indirectly via
    firmware.py's packet-framing tests.
    """
    assert CHAR_UUID_OTA == "00010203-0405-0607-0809-0a0b0c0d2b12"


def test_ota_protocol_constants():
    """Test the Telink legacy OTA command/framing constants."""
    assert OTA_CMD_START == 0xFF01
    assert OTA_CMD_END == 0xFF02
    assert OTA_SECTOR_SIZE == 4096
    assert OTA_PACKET_PAYLOAD_SIZE == 17
    assert OTA_TRAILER_SEQ == 0xFF
    # OTA_CMD_START/OTA_CMD_END share the same 2-byte leading field as
    # sector_index in data packets, so they must fall in the reserved
    # 0xFF00-0xFFFF range that sector indices never reach.
    assert OTA_CMD_START > 0xFEFF
    assert OTA_CMD_END > 0xFEFF


class TestNormalizeMac:
    """Test MAC address normalization function."""

    @pytest.mark.parametrize(
        "input_mac,expected",
        [
            # Colons
            ("aa:bb:cc:dd:ee:ff", "AA:BB:CC:DD:EE:FF"),
            ("AA:BB:CC:DD:EE:FF", "AA:BB:CC:DD:EE:FF"),
            # Dashes
            ("aa-bb-cc-dd-ee-ff", "AA:BB:CC:DD:EE:FF"),
            ("AA-BB-CC-DD-EE-FF", "AA:BB:CC:DD:EE:FF"),
            # Dots
            ("aa.bb.cc.dd.ee.ff", "AA:BB:CC:DD:EE:FF"),
            ("AA.BB.CC.DD.EE.FF", "AA:BB:CC:DD:EE:FF"),
            # No separators
            ("aabbccddeeff", "AA:BB:CC:DD:EE:FF"),
            ("AABBCCDDEEFF", "AA:BB:CC:DD:EE:FF"),
            # Mixed case
            ("Aa:Bb:Cc:Dd:Ee:Ff", "AA:BB:CC:DD:EE:FF"),
            ("aA-bB-cC-dD-eE-fF", "AA:BB:CC:DD:EE:FF"),
            # Real-world addresses
            ("A4:C1:38:12:34:56", "A4:C1:38:12:34:56"),
            ("a4c138123456", "A4:C1:38:12:34:56"),
            ("a4-c1-38-12-34-56", "A4:C1:38:12:34:56"),
        ],
    )
    def test_normalize_mac_valid_formats(self, input_mac, expected):
        """Test normalizing various valid MAC address formats."""
        assert normalize_mac(input_mac) == expected

    @pytest.mark.parametrize(
        "invalid_mac",
        [
            "aa:bb:cc:dd:ee",  # Too short
            "aa:bb:cc:dd:ee:ff:00",  # Too long
            "aabbccddee",  # Too short (no separators)
            "",  # Empty string
        ],
    )
    def test_normalize_mac_invalid_length(self, invalid_mac):
        """Test normalizing MAC with invalid length."""
        with pytest.raises(ValueError, match="Invalid MAC address length"):
            normalize_mac(invalid_mac)

    @pytest.mark.parametrize(
        "invalid_mac",
        [
            "gg:hh:ii:jj:kk:ll",  # Invalid hex characters
            "aa:bb:cc:dd:ee:zz",  # Invalid character at end
            "aabbccddeefg",  # Invalid hex character (g) without separators
        ],
    )
    def test_normalize_mac_invalid_characters(self, invalid_mac):
        """Test normalizing MAC with invalid characters."""
        with pytest.raises(ValueError, match="non-hex characters"):
            normalize_mac(invalid_mac)
