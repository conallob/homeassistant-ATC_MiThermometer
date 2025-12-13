# ATC MiThermometer Manager for Home Assistant

A Home Assistant integration for managing and updating ATC_MiThermometer custom firmware on Xiaomi Mijia BLE thermometer/hygrometer devices.

## Features

- **Automatic Device Discovery**: Identifies ATC MiThermometer devices from your BTHome integration
- **Dual Firmware Support**: Choose between two firmware variants:
  - [pvvx/ATC_MiThermometer](https://github.com/pvvx/ATC_MiThermometer) - Most actively maintained with additional features
  - [atc1441/ATC_MiThermometer](https://github.com/atc1441/ATC_MiThermometer) - Original implementation
- **Over-the-Air Updates**: Flash firmware updates directly via Bluetooth Low Energy
- **Home Assistant Integration**: Native update entities with progress tracking
- **Update Notifications**: Integrates with Home Assistant's repair system to notify you of available updates

## Requirements

- Home Assistant 2023.1 or newer
- BTHome integration installed and configured
- Xiaomi Mijia thermometer devices with ATC_MiThermometer firmware already installed
- Active Bluetooth adapter

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to "Integrations"
3. Click the three dots in the top right and select "Custom repositories"
4. Add this repository URL: `https://github.com/conallob/homeassistant-ATC_MiThermometer`
5. Select category "Integration"
6. Click "Install"
7. Restart Home Assistant

### Manual Installation

1. Copy the `custom_components/atc_mithermometer` directory to your Home Assistant's `custom_components` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration**
3. Search for "ATC MiThermometer Manager"
4. Select your device from the list of discovered devices
5. Choose your preferred firmware source (pvvx or atc1441)
6. Click **Submit**

The integration will automatically detect ATC MiThermometer devices that are already visible in your BTHome integration.

## Usage

### Checking for Updates

The integration automatically checks for firmware updates every hour. When an update is available, you'll see it in:

- The Update entity for your device
- Home Assistant notifications (via the repair system)

### Installing Updates

1. Navigate to your device in **Settings** → **Devices & Services**
2. Click on the "Firmware Update" entity
3. Click **Install** when an update is available
4. Monitor the progress bar during installation

### Manual Firmware Flash

You can also use the service calls to manually trigger firmware updates:

```yaml
service: atc_mithermometer.flash_firmware
target:
  device_id: your_device_id
data:
  firmware_source: pvvx  # or atc1441
  version: v4.5  # optional, defaults to latest
```

### Switching Firmware Sources

To switch between pvvx and atc1441 firmware:

1. Go to your device's integration entry
2. Click **Configure**
3. Select the new firmware source
4. The next update check will use the new source

## Supported Devices

This integration supports Xiaomi Mijia devices running ATC_MiThermometer custom firmware:

- LYWSD03MMC (Xiaomi Mijia Thermometer 2)
- CGG1 (Qingping Temp & RH Monitor)
- MHO-C401 (Mijia E-Ink Display)
- CGDK2 (Qingping Temp & RH Monitor Lite)

**Note**: Devices must already have ATC_MiThermometer firmware installed. This integration does not convert stock firmware devices.

## Troubleshooting

### Device Not Found

- Ensure the device is powered on and in range
- Verify the device appears in your BTHome integration
- Check that Bluetooth is enabled on your Home Assistant host

### Firmware Flash Failed

- Make sure the device is not already being used by another connection
- Reduce distance between device and Bluetooth adapter
- Try restarting the device (remove and reinsert battery)

### Update Check Fails

- Verify you have internet connectivity
- Check Home Assistant logs for specific errors
- GitHub API rate limits may apply (60 requests/hour for unauthenticated)

## Development

See [CLAUDE.md](CLAUDE.md) for development guidance.

## License

This project is licensed under the BSD 3-Clause License - see the [LICENSE](LICENSE) file for details.

## Credits

- [pvvx](https://github.com/pvvx) - Active ATC_MiThermometer firmware development
- [atc1441](https://github.com/atc1441) - Original ATC_MiThermometer firmware
- Home Assistant community
