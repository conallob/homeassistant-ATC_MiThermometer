import assert from "node:assert/strict";
import { test } from "node:test";
import { JSDOM } from "jsdom";

// The card is a plain browser Web Component with no build step, so it
// expects window/document/customElements/HTMLElement as bare globals. Set
// those up once (jsdom) before importing it, matching how a real Lovelace
// dashboard loads it as a JavaScript module resource.
const dom = new JSDOM("<!doctype html><html><body></body></html>", {
  url: "https://homeassistant.local/",
});
global.window = dom.window;
global.document = dom.window.document;
global.HTMLElement = dom.window.HTMLElement;
global.customElements = dom.window.customElements;
global.Event = dom.window.Event;

await import(
  "../../custom_components/atc_mithermometer/www/atc-mithermometer-panel.js"
);

function makeCard() {
  return document.createElement("atc-mithermometer-panel");
}

function makeHass(overrides = {}) {
  return {
    states: {},
    entities: {},
    devices: {},
    callService: async () => {},
    ...overrides,
  };
}

test("registers the custom element and its customCards picker metadata", () => {
  assert.ok(customElements.get("atc-mithermometer-panel"));
  assert.ok(Array.isArray(window.customCards));
  assert.ok(
    window.customCards.some((c) => c.type === "atc-mithermometer-panel")
  );
});

test("discovers only atc_mithermometer update entities, sorted by device name", () => {
  const card = makeCard();
  card.hass = makeHass({
    states: {
      "update.device_a": { attributes: { firmware_source: "pvvx" } },
      "update.device_b": { attributes: { firmware_source: "atc1441" } },
      "sensor.unrelated": {},
    },
    entities: {
      "update.device_a": { platform: "atc_mithermometer", device_id: "dev-a" },
      "update.device_b": { platform: "atc_mithermometer", device_id: "dev-b" },
      "sensor.unrelated": { platform: "bthome", device_id: "dev-c" },
    },
    devices: {
      "dev-a": { name: "Kitchen" },
      "dev-b": { name: "Bedroom" },
    },
  });

  assert.deepEqual(
    card._devices.map((d) => d.name),
    ["Bedroom", "Kitchen"]
  );
  const kitchen = card._devices.find((d) => d.deviceId === "dev-a");
  assert.equal(kitchen.firmwareSource, "pvvx");
});

test("renders the empty-state placeholder on the very first render with zero devices", () => {
  const card = makeCard();
  card.hass = makeHass();

  assert.equal(card._deviceSelect.disabled, true);
  assert.equal(card._deviceSelect.options.length, 1);
  assert.match(
    card._deviceSelect.options[0].textContent,
    /No ATC MiThermometer devices found/
  );
});

test("preserves the selected device across hass updates when the device list is unchanged", () => {
  const card = makeCard();
  global.fetch = async () => ({ ok: true, status: 200, json: async () => [] });

  const hass = makeHass({
    states: {
      "update.device_a": { attributes: { firmware_source: "pvvx" } },
      "update.device_b": { attributes: { firmware_source: "pvvx" } },
    },
    entities: {
      "update.device_a": { platform: "atc_mithermometer", device_id: "dev-a" },
      "update.device_b": { platform: "atc_mithermometer", device_id: "dev-b" },
    },
    devices: {
      "dev-a": { name: "Bedroom" },
      "dev-b": { name: "Kitchen" },
    },
  });

  card.hass = hass;
  card._deviceSelect.value = "dev-b";
  card._deviceSelect.dispatchEvent(new window.Event("change"));
  assert.equal(card._selectedDeviceId, "dev-b");

  // A later hass update with the same device list must not reset the
  // user's in-progress selection back to the first device.
  card.hass = { ...hass, states: { ...hass.states } };

  assert.equal(card._selectedDeviceId, "dev-b");
  assert.equal(card._deviceSelect.value, "dev-b");
});

test("resyncs the flavour dropdown when the selected device's firmware_source changes without a registry change", () => {
  const card = makeCard();
  global.fetch = async () => ({ ok: true, status: 200, json: async () => [] });

  // Same entities/devices object references across both hass assignments -
  // simulates a state-only update (e.g. the config entry's firmware
  // source was changed in another tab) rather than a registry change.
  const entities = {
    "update.device_a": { platform: "atc_mithermometer", device_id: "dev-a" },
  };
  const devices = { "dev-a": { name: "Bedroom" } };

  card.hass = makeHass({
    states: { "update.device_a": { attributes: { firmware_source: "pvvx" } } },
    entities,
    devices,
  });
  assert.equal(card._selectedSource, "pvvx");
  assert.equal(card._sourceSelect.value, "pvvx");

  card.hass = makeHass({
    states: {
      "update.device_a": { attributes: { firmware_source: "atc1441" } },
    },
    entities,
    devices,
  });

  assert.equal(card._selectedSource, "atc1441");
  assert.equal(card._sourceSelect.value, "atc1441");
});

test("skips the full entity scan when hass.entities/hass.devices are unchanged", () => {
  const card = makeCard();
  global.fetch = async () => ({ ok: true, status: 200, json: async () => [] });

  const entities = {
    "update.device_a": { platform: "atc_mithermometer", device_id: "dev-a" },
  };
  const devices = { "dev-a": { name: "Bedroom" } };

  let ownKeysCalls = 0;
  function makeStates(firmwareSource) {
    const raw = {
      "update.device_a": { attributes: { firmware_source: firmwareSource } },
    };
    return new Proxy(raw, {
      ownKeys(target) {
        ownKeysCalls += 1;
        return Reflect.ownKeys(target);
      },
    });
  }

  card.hass = makeHass({ states: makeStates("pvvx"), entities, devices });
  assert.ok(ownKeysCalls > 0, "the first render must scan every entity");

  // Same entities/devices references (no registry change) - the O(n) scan
  // over every entity in the instance must not run again, only a cheap
  // lookup of the already-known device's own state.
  ownKeysCalls = 0;
  card.hass = makeHass({ states: makeStates("pvvx"), entities, devices });
  assert.equal(
    ownKeysCalls,
    0,
    "unchanged entities/devices must skip the full states scan"
  );
});

test("_loadVersions excludes prereleases and drafts from the dropdown", async () => {
  const card = makeCard();
  card.hass = makeHass({
    states: { "update.device_a": { attributes: { firmware_source: "pvvx" } } },
    entities: {
      "update.device_a": { platform: "atc_mithermometer", device_id: "dev-a" },
    },
    devices: { "dev-a": { name: "Bedroom" } },
  });

  global.fetch = async () => ({
    ok: true,
    status: 200,
    json: async () => [
      { tag_name: "v6.0", prerelease: false, draft: false },
      { tag_name: "v6.1-beta", prerelease: true, draft: false },
      { tag_name: "v6.2-draft", prerelease: false, draft: true },
    ],
  });

  card._selectedDeviceId = "dev-a";
  card._selectedSource = "pvvx";
  await card._loadVersions();

  assert.deepEqual(card._versions, ["v6.0"]);
});

test("_loadVersions guards against a slower stale response clobbering a newer selection", async () => {
  const card = makeCard();
  card.hass = makeHass({
    states: { "update.device_a": { attributes: { firmware_source: "pvvx" } } },
    entities: {
      "update.device_a": { platform: "atc_mithermometer", device_id: "dev-a" },
    },
    devices: { "dev-a": { name: "Bedroom" } },
  });

  let calls = 0;
  global.fetch = async (url) => {
    calls += 1;
    const firstCall = calls === 1;
    const tag = url.includes("atc1441") ? "atc1441-v1" : "pvvx-v1";
    if (firstCall) {
      // The first request (pvvx) resolves slower than the second
      // (atc1441) - it must not win just because it settles later.
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
    return {
      ok: true,
      status: 200,
      json: async () => [{ tag_name: tag, prerelease: false, draft: false }],
    };
  };

  card._selectedDeviceId = "dev-a";
  card._selectedSource = "pvvx";
  const slow = card._loadVersions();

  card._selectedSource = "atc1441";
  const fast = card._loadVersions();

  await Promise.all([slow, fast]);

  assert.deepEqual(card._versions, ["atc1441-v1"]);
});

test("_applyFirmware calls apply_firmware with the selected device/source/version", async () => {
  const card = makeCard();
  const calls = [];
  card.hass = makeHass({
    states: { "update.device_a": { attributes: { firmware_source: "pvvx" } } },
    entities: {
      "update.device_a": { platform: "atc_mithermometer", device_id: "dev-a" },
    },
    devices: { "dev-a": { name: "Bedroom" } },
    callService: async (domain, service, data) => {
      calls.push({ domain, service, data });
    },
  });

  card._selectedDeviceId = "dev-a";
  card._selectedSource = "pvvx";
  card._selectedVersion = "v6.0";

  await card._applyFirmware();

  assert.deepEqual(calls, [
    {
      domain: "atc_mithermometer",
      service: "apply_firmware",
      data: {
        device_id: "dev-a",
        desired_version: "v6.0",
        firmware_source: "pvvx",
      },
    },
  ]);
  assert.equal(card._busy, false);
  assert.equal(card._statusIsError, false);
});

test("_applyFirmware surfaces a failed service call as a status error", async () => {
  const card = makeCard();
  card.hass = makeHass({
    states: { "update.device_a": { attributes: { firmware_source: "pvvx" } } },
    entities: {
      "update.device_a": { platform: "atc_mithermometer", device_id: "dev-a" },
    },
    devices: { "dev-a": { name: "Bedroom" } },
    callService: async () => {
      throw new Error("boom");
    },
  });

  card._selectedDeviceId = "dev-a";
  card._selectedSource = "pvvx";
  card._selectedVersion = "v6.0";

  await card._applyFirmware();

  assert.match(card._statusMessage, /Failed to apply firmware: boom/);
  assert.equal(card._statusIsError, true);
  assert.equal(card._busy, false);
});

test("implements the standard Lovelace card lifecycle methods", () => {
  const card = makeCard();
  card.hass = makeHass();

  card.setConfig({ some: "config" });
  assert.deepEqual(card._config, { some: "config" });
  card.setConfig();
  assert.deepEqual(card._config, {});

  const PanelClass = customElements.get("atc-mithermometer-panel");
  assert.deepEqual(PanelClass.getStubConfig(), {});
  assert.equal(card.getCardSize(), 4);
  assert.equal(card.hass, card._hass);
});

test("switching the firmware flavour dropdown reloads versions for that source", () => {
  const card = makeCard();
  let fetchedUrls = [];
  global.fetch = async (url) => {
    fetchedUrls.push(url);
    return { ok: true, status: 200, json: async () => [] };
  };

  card.hass = makeHass({
    states: { "update.device_a": { attributes: { firmware_source: "pvvx" } } },
    entities: {
      "update.device_a": { platform: "atc_mithermometer", device_id: "dev-a" },
    },
    devices: { "dev-a": { name: "Bedroom" } },
  });

  fetchedUrls = [];
  card._sourceSelect.value = "atc1441";
  card._sourceSelect.dispatchEvent(new window.Event("change"));

  assert.equal(card._selectedSource, "atc1441");
  assert.ok(fetchedUrls.some((url) => url.includes("atc1441/ATC_MiThermometer")));
});

test("picking a version from the dropdown updates the selected version", () => {
  const card = makeCard();
  global.fetch = async () => ({ ok: true, status: 200, json: async () => [] });
  card.hass = makeHass({
    states: { "update.device_a": { attributes: { firmware_source: "pvvx" } } },
    entities: {
      "update.device_a": { platform: "atc_mithermometer", device_id: "dev-a" },
    },
    devices: { "dev-a": { name: "Bedroom" } },
  });

  const option = document.createElement("option");
  option.value = "v9.9";
  card._versionSelect.appendChild(option);
  card._versionSelect.value = "v9.9";
  card._versionSelect.dispatchEvent(new window.Event("change"));

  assert.equal(card._selectedVersion, "v9.9");
});

test("_loadVersions skips refetching when already cached for the same device+source", async () => {
  const card = makeCard();
  let calls = 0;
  global.fetch = async () => {
    calls += 1;
    return {
      ok: true,
      status: 200,
      json: async () => [{ tag_name: "v1.0", prerelease: false, draft: false }],
    };
  };

  // No devices yet, so this first render can't auto-select one and fire its
  // own _loadVersions() - keeps this test's fetch count solely about the
  // two explicit calls below.
  card.hass = makeHass();

  card._selectedDeviceId = "dev-a";
  card._selectedSource = "pvvx";
  await card._loadVersions();
  assert.equal(calls, 1);

  // Same device/source key - must reuse the cached result, not refetch.
  await card._loadVersions();
  assert.equal(calls, 1);
});

test("_applyFirmware is a no-op with nothing selected", async () => {
  const card = makeCard();
  let called = false;
  card.hass = makeHass({
    callService: async () => {
      called = true;
    },
  });

  await card._applyFirmware();

  assert.equal(called, false);
  assert.equal(card._busy, false);
});
