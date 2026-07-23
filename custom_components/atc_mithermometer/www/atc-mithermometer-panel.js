/**
 * ATC MiThermometer firmware panel.
 *
 * A Lovelace card that calls the atc_mithermometer.apply_firmware service
 * without needing Developer Tools > Actions: pick a device, a firmware
 * flavour, and a version (populated from that flavour's real GitHub
 * releases), then apply it.
 *
 * No build step / no external dependencies on purpose - this is a plain
 * Web Component so it works by simply being registered as a Lovelace
 * JavaScript module resource, with no bundler or npm install required.
 */

const REPOS = {
  pvvx: "pvvx/ATC_MiThermometer",
  atc1441: "atc1441/ATC_MiThermometer",
};

const SOURCE_LABELS = {
  pvvx: "pvvx (Most Active)",
  atc1441: "atc1441 (Original)",
};

class AtcMithermometerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._built = false;

    this._deviceFingerprint = "";
    this._devices = [];

    this._selectedDeviceId = null;
    this._selectedSource = "pvvx";
    this._selectedVersion = "";

    this._versions = [];
    this._versionsLoading = false;
    this._versionsError = "";
    this._versionsForKey = "";

    this._busy = false;
    this._statusMessage = "";
    this._statusIsError = false;
  }

  setConfig(config) {
    this._config = config || {};
  }

  static getStubConfig() {
    return {};
  }

  getCardSize() {
    return 4;
  }

  set hass(hass) {
    this._hass = hass;
    this._refreshDevices();
    if (!this._built) {
      this._buildSkeleton();
      this._built = true;
    }
    this._syncDeviceOptions();
    this._syncControlsEnabled();
  }

  get hass() {
    return this._hass;
  }

  // ---------------------------------------------------------------------
  // Device discovery - built entirely from data hass already provides, no
  // backend call needed for this part.
  // ---------------------------------------------------------------------

  _refreshDevices() {
    if (!this._hass) return;
    const entities = this._hass.entities || {};
    const devices = this._hass.devices || {};
    const states = this._hass.states || {};
    const byDevice = new Map();

    for (const entityId of Object.keys(states)) {
      if (!entityId.startsWith("update.")) continue;
      const entry = entities[entityId];
      if (!entry || entry.platform !== "atc_mithermometer") continue;
      if (!entry.device_id || byDevice.has(entry.device_id)) continue;

      const device = devices[entry.device_id];
      const name =
        (device && (device.name_by_user || device.name)) || entityId;
      const state = states[entityId];
      const firmwareSource =
        (state && state.attributes && state.attributes.firmware_source) ||
        "pvvx";

      byDevice.set(entry.device_id, {
        deviceId: entry.device_id,
        name,
        firmwareSource,
      });
    }

    this._devices = Array.from(byDevice.values()).sort((a, b) =>
      a.name.localeCompare(b.name)
    );

    const fingerprint = this._devices
      .map((d) => `${d.deviceId}:${d.name}:${d.firmwareSource}`)
      .join("|");
    this._devicesChanged = fingerprint !== this._deviceFingerprint;
    this._deviceFingerprint = fingerprint;

    if (
      (!this._selectedDeviceId ||
        !this._devices.some((d) => d.deviceId === this._selectedDeviceId)) &&
      this._devices.length
    ) {
      this._selectedDeviceId = this._devices[0].deviceId;
      this._selectedSource = this._devices[0].firmwareSource;
    }
  }

  // ---------------------------------------------------------------------
  // One-time DOM construction. Rebuilt only once per card instance -
  // hass is set on every state change bus-wide, so re-creating the whole
  // shadow DOM on every update would wipe out in-progress selections.
  // ---------------------------------------------------------------------

  _buildSkeleton() {
    const root = this.shadowRoot;
    root.innerHTML = `
      <style>
        ha-card {
          padding: 16px;
        }
        .row {
          display: flex;
          flex-direction: column;
          margin-bottom: 12px;
        }
        label {
          font-size: 0.85em;
          color: var(--secondary-text-color);
          margin-bottom: 4px;
        }
        select, button {
          font-family: inherit;
          font-size: 1em;
          padding: 8px;
          border-radius: 4px;
          border: 1px solid var(--divider-color, #ccc);
          background: var(--card-background-color, #fff);
          color: var(--primary-text-color);
        }
        select:disabled, button:disabled {
          opacity: 0.5;
        }
        button {
          background: var(--primary-color);
          color: var(--text-primary-color, #fff);
          border: none;
          cursor: pointer;
          font-weight: 500;
        }
        button:disabled {
          cursor: default;
        }
        .status {
          margin-top: 12px;
          font-size: 0.9em;
        }
        .status.error {
          color: var(--error-color, #db4437);
        }
        .status.ok {
          color: var(--success-color, var(--primary-text-color));
        }
        .empty {
          color: var(--secondary-text-color);
        }
      </style>
      <ha-card header="ATC MiThermometer Firmware">
        <div class="content">
          <div class="row" id="device-row">
            <label for="device">Device</label>
            <select id="device"></select>
          </div>
          <div class="row" id="source-row">
            <label for="source">Firmware flavour</label>
            <select id="source">
              <option value="pvvx">${SOURCE_LABELS.pvvx}</option>
              <option value="atc1441">${SOURCE_LABELS.atc1441}</option>
            </select>
          </div>
          <div class="row" id="version-row">
            <label for="version">Version</label>
            <select id="version"></select>
          </div>
          <button id="apply">Apply Firmware</button>
          <div class="status" id="status"></div>
        </div>
      </ha-card>
    `;

    this._deviceSelect = root.getElementById("device");
    this._sourceSelect = root.getElementById("source");
    this._versionSelect = root.getElementById("version");
    this._applyButton = root.getElementById("apply");
    this._statusEl = root.getElementById("status");

    this._deviceSelect.addEventListener("change", () => {
      this._selectedDeviceId = this._deviceSelect.value;
      const device = this._devices.find(
        (d) => d.deviceId === this._selectedDeviceId
      );
      if (device) {
        this._selectedSource = device.firmwareSource;
        this._sourceSelect.value = this._selectedSource;
      }
      this._loadVersions();
    });

    this._sourceSelect.addEventListener("change", () => {
      this._selectedSource = this._sourceSelect.value;
      this._loadVersions();
    });

    this._versionSelect.addEventListener("change", () => {
      this._selectedVersion = this._versionSelect.value;
    });

    this._applyButton.addEventListener("click", () => this._applyFirmware());
  }

  // ---------------------------------------------------------------------
  // Keep the device dropdown's *options* in sync without disturbing an
  // in-progress selection unless the underlying device list actually
  // changed.
  // ---------------------------------------------------------------------

  _syncDeviceOptions() {
    if (!this._devicesChanged) return;

    const select = this._deviceSelect;
    const previousValue = select.value;
    select.innerHTML = "";

    if (!this._devices.length) {
      const option = document.createElement("option");
      option.textContent = "No ATC MiThermometer devices found";
      option.value = "";
      select.appendChild(option);
      select.disabled = true;
      this._selectedDeviceId = null;
      return;
    }

    select.disabled = false;
    for (const device of this._devices) {
      const option = document.createElement("option");
      option.value = device.deviceId;
      option.textContent = device.name;
      select.appendChild(option);
    }

    const stillValid = this._devices.some(
      (d) => d.deviceId === previousValue
    );
    select.value = stillValid ? previousValue : this._selectedDeviceId;

    if (!stillValid) {
      this._sourceSelect.value = this._selectedSource;
      this._loadVersions();
    }
  }

  _syncControlsEnabled() {
    const hasDevice = Boolean(this._selectedDeviceId);
    this._sourceSelect.disabled = this._busy || !hasDevice;
    this._versionSelect.disabled =
      this._busy || !hasDevice || this._versionsLoading;
    this._applyButton.disabled =
      this._busy ||
      !hasDevice ||
      !this._selectedVersion ||
      this._versionsLoading;
    this._applyButton.textContent = this._busy
      ? "Applying..."
      : "Apply Firmware";
  }

  // ---------------------------------------------------------------------
  // Available versions - fetched directly from GitHub's public releases
  // API, matching what the backend's own release lookup uses, so a
  // version listed here is guaranteed to be an installable release tag
  // (not just a device's self-reported version, which isn't always one).
  // ---------------------------------------------------------------------

  async _loadVersions() {
    if (!this._selectedDeviceId) return;
    const key = `${this._selectedDeviceId}:${this._selectedSource}`;
    if (key === this._versionsForKey && this._versions.length) {
      this._syncControlsEnabled();
      return;
    }

    // Guards against a slower, now-stale request resolving after a newer
    // one (e.g. the user switches device/source twice in quick succession)
    // and clobbering the dropdown with results for the wrong selection.
    const requestId = (this._versionsRequestId = (this._versionsRequestId || 0) + 1);

    this._versionsLoading = true;
    this._versionsError = "";
    this._versionSelect.innerHTML = "<option>Loading...</option>";
    this._syncControlsEnabled();

    try {
      const repo = REPOS[this._selectedSource];
      const response = await fetch(
        `https://api.github.com/repos/${repo}/releases?per_page=15`
      );
      if (!response.ok) {
        throw new Error(`GitHub API returned HTTP ${response.status}`);
      }
      const releases = await response.json();
      if (requestId !== this._versionsRequestId) return;
      this._versions = releases
        .map((release) => release.tag_name)
        .filter(Boolean);
      this._versionsForKey = key;
    } catch (err) {
      if (requestId !== this._versionsRequestId) return;
      this._versions = [];
      this._versionsError = `Could not load versions: ${err.message}`;
    } finally {
      if (requestId === this._versionsRequestId) {
        this._versionsLoading = false;
        this._renderVersionOptions();
        this._syncControlsEnabled();
      }
    }
  }

  _renderVersionOptions() {
    const select = this._versionSelect;
    select.innerHTML = "";

    if (this._versionsError) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = this._versionsError;
      select.appendChild(option);
      this._selectedVersion = "";
      return;
    }

    if (!this._versions.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "No releases found";
      select.appendChild(option);
      this._selectedVersion = "";
      return;
    }

    for (const version of this._versions) {
      const option = document.createElement("option");
      option.value = version;
      option.textContent = version;
      select.appendChild(option);
    }
    this._selectedVersion = this._versions[0];
    select.value = this._selectedVersion;
  }

  // ---------------------------------------------------------------------
  // Apply.
  // ---------------------------------------------------------------------

  async _applyFirmware() {
    if (!this._selectedDeviceId || !this._selectedVersion || this._busy) {
      return;
    }

    this._busy = true;
    this._setStatus(
      `Applying ${this._selectedVersion} - this can take a while and ` +
        `will not confirm success until the device reboots.`,
      false
    );
    this._syncControlsEnabled();

    try {
      await this._hass.callService("atc_mithermometer", "apply_firmware", {
        device_id: this._selectedDeviceId,
        desired_version: this._selectedVersion,
        firmware_source: this._selectedSource,
      });
      this._setStatus(
        `Firmware ${this._selectedVersion} applied to the device.`,
        false
      );
    } catch (err) {
      this._setStatus(`Failed to apply firmware: ${err.message}`, true);
    } finally {
      this._busy = false;
      this._syncControlsEnabled();
    }
  }

  _setStatus(message, isError) {
    this._statusMessage = message;
    this._statusIsError = isError;
    if (!this._statusEl) return;
    this._statusEl.textContent = message;
    this._statusEl.className = `status ${isError ? "error" : "ok"}`;
  }
}

customElements.define("atc-mithermometer-panel", AtcMithermometerPanel);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "atc-mithermometer-panel",
  name: "ATC MiThermometer Firmware Panel",
  description:
    "Pick a device, firmware flavour, and version, then apply firmware " +
    "without using Developer Tools > Actions.",
});
