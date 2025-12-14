# ATC MiThermometer Manager - Test Suite

This directory contains comprehensive unit tests for the ATC MiThermometer Manager Home Assistant integration.

## Test Structure

```
tests/
├── __init__.py              # Package initialization
├── conftest.py              # Shared pytest fixtures
├── README.md                # This file
├── test_const.py            # Tests for constants and utilities
├── test_init.py             # Tests for integration setup
├── test_config_flow.py      # Tests for configuration flow
├── test_firmware.py         # Tests for firmware management
└── test_update.py           # Tests for update entity
```

## Running Tests

### Prerequisites

Install test dependencies:

```bash
pip install -r requirements-test.txt
```

### Running All Tests

```bash
pytest
```

### Running Specific Test Files

```bash
# Test constants
pytest tests/test_const.py

# Test initialization
pytest tests/test_init.py

# Test config flow
pytest tests/test_config_flow.py

# Test firmware management
pytest tests/test_firmware.py

# Test update entity
pytest tests/test_update.py
```

### Running with Coverage

```bash
pytest --cov=custom_components.atc_mithermometer --cov-report=html
```

Coverage report will be generated in `htmlcov/index.html`.

### Running Specific Tests

```bash
# Run a specific test class
pytest tests/test_const.py::TestNormalizeMac

# Run a specific test function
pytest tests/test_const.py::TestNormalizeMac::test_normalize_mac_with_colons

# Run tests matching a pattern
pytest -k "test_normalize"
```

## Test Coverage

The test suite provides comprehensive coverage of:

### `test_const.py`
- Domain and constant validation
- Firmware source configuration
- Service UUID definitions
- MAC address normalization (all formats and edge cases)

### `test_init.py`
- Integration setup and teardown
- Device identification logic
- BTHome integration linking
- Device registry operations
- MAC address resolution
- Error handling for device operations

### `test_config_flow.py`
- User-initiated configuration flow
- Bluetooth discovery flow
- Device selection and validation
- Firmware source selection
- Duplicate device handling
- Error cases and edge conditions
- Options flow for updating settings

### `test_firmware.py`
- GitHub release fetching (both pvvx and atc1441)
- Firmware download with validation
- Size validation (min/max)
- BLE firmware flashing
- Progress tracking
- Version detection from advertisements
- Network error handling
- Timeout handling
- BLE connection errors

### `test_update.py`
- Update coordinator initialization
- Update entity setup
- Version checking
- Firmware installation flow
- Progress reporting
- Device info linking
- Release notes display
- Error handling during updates
- State management

## Writing New Tests

When adding new functionality, follow these guidelines:

1. **Create descriptive test names**: Use `test_<functionality>_<scenario>` format
2. **Use fixtures**: Leverage existing fixtures in `conftest.py` for common objects
3. **Mock external dependencies**: Mock all Home Assistant, aiohttp, and BLE operations
4. **Test error cases**: Include tests for failures, timeouts, and edge cases
5. **Keep tests isolated**: Each test should be independent and not rely on others
6. **Use async where needed**: Mark async tests with `async def`

### Example Test

```python
async def test_my_new_feature(hass: HomeAssistant, mock_config_entry):
    """Test my new feature does what it should."""
    # Arrange
    mock_dependency = MagicMock()

    with patch("module.dependency", mock_dependency):
        # Act
        result = await my_function(hass, mock_config_entry)

        # Assert
        assert result is True
        mock_dependency.assert_called_once()
```

## Continuous Integration

These tests are designed to run in CI/CD pipelines. Ensure all tests pass before submitting pull requests.

## Troubleshooting

### Import Errors

If you encounter import errors, ensure:
- You're running tests from the repository root
- All dependencies are installed: `pip install -r requirements-test.txt`
- The `custom_components` directory is in your Python path

### Home Assistant Version Compatibility

Tests are written for Home Assistant 2024.1.0+. If you encounter compatibility issues, check:
- Your Home Assistant version matches requirements
- You have `pytest-homeassistant-custom-component` installed

### Async Test Issues

If async tests fail:
- Ensure `pytest-asyncio` is installed
- Check that `asyncio_mode = auto` is set in `pytest.ini`
- Mark async tests with `async def`

## Additional Resources

- [Home Assistant Testing Documentation](https://developers.home-assistant.io/docs/development_testing)
- [pytest Documentation](https://docs.pytest.org/)
- [pytest-asyncio Documentation](https://pytest-asyncio.readthedocs.io/)
