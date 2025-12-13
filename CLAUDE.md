# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Home Assistant integration for managing and updating ATC_MiThermometer firmware on Xiaomi Mijia BLE thermometer/hygrometer devices. The integration allows users to:

1. Identify devices running ATC_MiThermometer firmware from BTHome integration devices
2. Flash firmware from either:
   - https://github.com/pvvx/ATC_MiThermometer (most active fork)
   - https://github.com/atc1441/ATC_MiThermometer (original)
3. Integrate with Home Assistant's version update/repairs system for simplified firmware updates

## Architecture Strategy

**Reuse Existing Components**: The integration should leverage:
- **BTHome Integration** - For device discovery and identification (devices already discovered here)
- **ESPHome Components** - Reuse OTA/flashing patterns where applicable
- **Home Assistant Update Entity** - For firmware version management and update notifications
- **Home Assistant Repairs** - For surfacing update recommendations to users

**Integration Flow**:
1. Monitor BTHome integration for devices with ATC_MiThermometer firmware signatures
2. Create update entities for identified devices showing current firmware version
3. When updates available, create repair issues that guide users through the update process
4. Handle firmware download and flashing via BLE

## Home Assistant Integration Structure

```
custom_components/atc_mithermometer/
├── __init__.py           # Integration setup, device identification from BTHome
├── manifest.json         # Declare dependencies: BTHome, bluetooth
├── config_flow.py        # Configuration UI (firmware source selection)
├── update.py             # Update entity platform for firmware management
├── const.py              # Constants (firmware URLs, version endpoints)
└── firmware.py           # Firmware download and flashing logic
```

## Key Integration Points

**BTHome Device Identification**:
- Monitor `bluetooth` integration's discovered devices
- Identify ATC_MiThermometer by BLE advertisement format/service UUIDs
- Cross-reference with devices already in BTHome integration

**Firmware Version Detection**:
- Parse current firmware version from BLE advertisements
- Fetch latest versions from GitHub releases APIs:
  - `https://api.github.com/repos/pvvx/ATC_MiThermometer/releases/latest`
  - `https://api.github.com/repos/atc1441/ATC_MiThermometer/releases/latest`

**Update Entity Pattern**:
- Implement `UpdateEntity` to show current vs. available firmware
- `async_install()` method handles firmware flashing process
- Progress reporting during flash operation

**Repairs Integration**:
- Create repair issues when firmware updates are available
- Link to update entity for easy access to update flow

## Firmware Flashing Process

ATC_MiThermometer devices support OTA updates via BLE. The flashing process:

1. Download firmware binary from selected GitHub repository
2. Connect to device via BLE (using Home Assistant's bluetooth integration)
3. Send firmware binary in chunks over BLE characteristic
4. Verify successful flash and reconnection

Reference ESPHome's BLE OTA implementation for patterns on chunked upload and progress tracking.

## Development Commands

**Testing**:
- Install in Home Assistant dev environment
- Requires devices running ATC_MiThermometer or BLE simulation
- Monitor logs: `config/home-assistant.log`

**Validation**:
```bash
python -m script.hassfest  # Validate integration structure
```

## Important Notes

- All BLE operations must be async and use Home Assistant's `bluetooth` integration APIs
- Handle network errors gracefully when fetching firmware from GitHub
- Firmware flashing is risky - implement confirmation steps and clear user warnings
- Support both firmware variants (pvvx and atc1441) as they have different feature sets
