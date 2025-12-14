"""Test the const module."""
import pytest

from custom_components.atc_mithermometer.const import (
    DOMAIN,
    FIRMWARE_SOURCE_PVVX,
    FIRMWARE_SOURCE_ATC1441,
    FIRMWARE_SOURCES,
    SERVICE_UUID_ENVIRONMENTAL,
    ATC_NAME_PREFIXES,
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


class TestNormalizeMac:
    """Test MAC address normalization function."""

    def test_normalize_mac_with_colons(self):
        """Test normalizing MAC with colons."""
        assert normalize_mac("aa:bb:cc:dd:ee:ff") == "AA:BB:CC:DD:EE:FF"
        assert normalize_mac("AA:BB:CC:DD:EE:FF") == "AA:BB:CC:DD:EE:FF"

    def test_normalize_mac_with_dashes(self):
        """Test normalizing MAC with dashes."""
        assert normalize_mac("aa-bb-cc-dd-ee-ff") == "AA:BB:CC:DD:EE:FF"
        assert normalize_mac("AA-BB-CC-DD-EE-FF") == "AA:BB:CC:DD:EE:FF"

    def test_normalize_mac_with_dots(self):
        """Test normalizing MAC with dots."""
        assert normalize_mac("aa.bb.cc.dd.ee.ff") == "AA:BB:CC:DD:EE:FF"
        assert normalize_mac("AA.BB.CC.DD.EE.FF") == "AA:BB:CC:DD:EE:FF"

    def test_normalize_mac_no_separators(self):
        """Test normalizing MAC without separators."""
        assert normalize_mac("aabbccddeeff") == "AA:BB:CC:DD:EE:FF"
        assert normalize_mac("AABBCCDDEEFF") == "AA:BB:CC:DD:EE:FF"

    def test_normalize_mac_mixed_case(self):
        """Test normalizing MAC with mixed case."""
        assert normalize_mac("Aa:Bb:Cc:Dd:Ee:Ff") == "AA:BB:CC:DD:EE:FF"
        assert normalize_mac("aA-bB-cC-dD-eE-fF") == "AA:BB:CC:DD:EE:FF"

    def test_normalize_mac_invalid_length(self):
        """Test normalizing MAC with invalid length."""
        with pytest.raises(ValueError, match="Invalid MAC address length"):
            normalize_mac("aa:bb:cc:dd:ee")

        with pytest.raises(ValueError, match="Invalid MAC address length"):
            normalize_mac("aa:bb:cc:dd:ee:ff:00")

        with pytest.raises(ValueError, match="Invalid MAC address length"):
            normalize_mac("aabbccddee")

    def test_normalize_mac_invalid_characters(self):
        """Test normalizing MAC with invalid characters."""
        with pytest.raises(ValueError, match="non-hex characters"):
            normalize_mac("gg:hh:ii:jj:kk:ll")

        with pytest.raises(ValueError, match="non-hex characters"):
            normalize_mac("aa:bb:cc:dd:ee:zz")

        with pytest.raises(ValueError, match="non-hex characters"):
            normalize_mac("aa!bb@cc#dd$ee%ff")

    def test_normalize_mac_empty_string(self):
        """Test normalizing empty MAC address."""
        with pytest.raises(ValueError, match="Invalid MAC address length"):
            normalize_mac("")

    def test_normalize_mac_real_addresses(self):
        """Test normalizing real-world MAC addresses."""
        assert normalize_mac("A4:C1:38:12:34:56") == "A4:C1:38:12:34:56"
        assert normalize_mac("a4c138123456") == "A4:C1:38:12:34:56"
        assert normalize_mac("a4-c1-38-12-34-56") == "A4:C1:38:12:34:56"
