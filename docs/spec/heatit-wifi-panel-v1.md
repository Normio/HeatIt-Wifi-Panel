# Heatit WiFi Panel — Home Assistant integration, v1 design spec

A Home Assistant custom integration (HACS custom component) for the **Heatit WiFi Panel** wall
heater. It talks to the panel over its local HTTP API. Domain `heatit_wifi_panel`. Python, async, `aiohttp`.

This document is complete enough to build v1 from. There are **no decisions left to make**. Every
device behaviour stated here was observed on a real panel. Every Home Assistant convention stated
here was read from `docs/core/integration-quality-scale/rules/*` or from core source. None came from
the "Building integrations" documentation pages.

---

## 0. How to read this document

**It is frozen at v1.** Corrections go into [§15 Amendments](#15-amendments) with a date. They are
not edited into the body. This lets a reviewer compare shipped code against this document and see
which parts were corrected later and which were right from the start.

**It does not contain the conformance checklist.** That checklist is a *living* register at
[`docs/conformance/checklist.md`](../conformance/checklist.md). It grows, and its rows change state.
A frozen document cannot hold it. [§12](#12-hardware-conformance) introduces it and links it. The
probe script that drives it is specified there too.

**Three kinds of claim are kept apart throughout.** The difference matters:

| | |
|---|---|
| *the vendor document says X* | Evidence, never truth. The register records each place where it is simply wrong as `disagrees`. Count them there. |
| *this panel does X* | One 600 W unit at firmware **1.21**. Every measurement here carries that qualifier. |
| *every panel does X* | Never claimed. The register exists so a second panel can show where we were wrong. |

**Observed beats documented.** The parameter registry, the entity table and every test fixture hold
only what a real panel has **returned**. A parameter enters only with a captured fixture. The
vendor's OpenAPI document is a proposal. The hardware decides.

Vocabulary is defined once, in [`CONTEXT.md`](../../CONTEXT.md). Terms in *italics* on first use
here are glossary entries. Examples: *panel mode*, *comfort setpoint*, *live setpoint*, *relay state*,
*required core*, *silent undo*, *write echo*. Use these terms. Do not drift to the synonyms each
entry lists under *Avoid*.

---

## 1. Scope and non-goals

### In scope for v1

The whole panel as the local API exposes it: one climate entity, both *setpoint banks*, the
*temperature limits*, display and button settings, the *load limit*, *open window detection*, power,
energy and diagnostics. That is **21 entities** across eight platforms. Also in scope: a config flow
with DHCP IP-follow, a reconfigure flow, an options flow, diagnostics, a full offline test suite, CI,
and HACS packaging.

The quality bar is a **HACS default repository** listing, and nothing beyond it.

### Out of scope, and why

| Excluded | Reason |
|---|---|
| **BlueFusion** (`/api/bluefusion/*`, the panel as a BLE hub) | Deferred. The vendor document's own BlueFusion examples disagree with each other on field names. It would need its own research effort. |
| **DirectLink** (`/api/directlink`, `relayControl` / `masterThermostat`) | Deferred for the same reason. |
| **`DELETE /api/reset/factory` as an entity** | A factory reset unpairs the panel from the MyHeatit app and leaves it off WiFi. A mis-tapped dashboard button must not be able to trigger that. The endpoint is also **not implemented** on firmware 1.21. So the ruling holds both because we choose it and because the panel cannot do it. |
| **Home Assistant core inclusion** | Costed and rejected. Core requires all device code in a published PyPI package with sdists and a public CI publish pipeline. Core forbids the `version` key that HACS requires. Core rejects the `documentation` URL that core itself mandates, so no single `manifest.json` serves both. Core also limits a new integration's first PR to a single platform, and our surface has eight platforms. If core is ever wanted, it is a fresh effort, not a resumption. |
| **The API client as a published library** | Existed only to serve core. HACS requires nothing here, and the split only gates the platinum tier. The client is a module inside the integration. The *discipline* of keeping device I/O free of `homeassistant` imports survives, because it helps testability (§3.2). |
| **A `home-assistant/brands` pull request** | The brands repository auto-closes new `custom_integrations/` PRs. Since HA 2026.3, custom integrations ship brand assets in-tree. Authoring the assets is in scope (§10). Opening that PR is a wasted cycle. |
| **A YAML `rest:` / `rest_command:` fallback** | Solves a different problem: one or two heaters, right now. It competes with this integration rather than leading to it. |
| **Executing the conformance checklist in full** | Specifying it is in scope (§12) and is a required deliverable. Running every row, across more than one firmware, is a separate effort. It *is* still a gate on HACS submission (§11). |

---

## 2. The device

Everything in this section was observed on a real panel at firmware **1.21**, `model`
`"Heatit WiFi Panel Heater"`, `maxLoad: 6` (a 600 W unit), except where marked *unobserved*. The
vendor's OpenAPI document (version 12.0.0) is vendored at
[`docs/api/heatit-wifi-panel-openapi.yaml`](../api/heatit-wifi-panel-openapi.yaml). It is cited only
where it is the sole source, or where the device proved it wrong.

### 2.1 Transport

- **Plain HTTP on tcp/80.** No TLS, no alternate port, no redirect, and no authentication of any
  kind. Anyone on the LAN can read and write. Of tcp 22/23/80/443/1900/5000/5353/8080/8123/8266/9999/49152,
  only 80 answers.
- **HTTP/1.1 only.** The panel refuses an HTTP/1.0 request with `505 Version Not Supported`.
- Responses carry `Content-Length`. The panel never uses chunked transfer. The response headers are
  `Content-Type` and `Content-Length` **only**. There is no `Date`, no `Server`, and no API-version header.
- **Keep-alive is honoured.** An idle socket was still served after 65 s.
- Read latency is 28–213 ms on a fresh connection and 52–214 ms on a reused one. It is bimodal,
  around ~30 ms and ~205 ms. **Connection reuse gives no measurable gain.**
- **Accept backlog is about 4–5.** Two and four parallel connections are served cleanly. At eight,
  three waited 1.2 s for a SYN retransmit before being accepted. No request failed at any count.
- **`GET /api/status` is computed per request**, not served from a cache. Over 24 samples across
  120 s, `wifiSignalStrength` changed between consecutive 5 s reads.

### 2.2 Endpoints

The integration uses four endpoints, and only four:

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/status` | The whole *status*. The only read. `HEAD` returns `405`. |
| `POST` | `/api/parameters?<name>=<value>` | One parameter per request (§2.4). |
| `DELETE` | `/api/reset/kwh?resetKwh=Reset` | Zeroes the *energy counter*. |
| `DELETE` | `/api/reset/settings` | Resets parameters to defaults. Keeps network, pairing, `id`, `name`, `room`. |

There is **no `GET /api/parameters`**. Parameters can only be read through the status. An unknown
path returns `404`, `Content-Type: text/html`, body `Nothing matches the given URI` (a CherryPy
default). `GET /`, `GET /api`, `GET /api/status/` and `GET /api/Status` all return that same 404.
So paths are case-sensitive, a trailing slash is not accepted, and **the panel serves no web UI**.
That is why the integration ships no `configuration_url`.

`/api/reset/factory` is **absent** on this firmware.

### 2.3 The status document

A success response carries `Content-Type: application/json` with **no `charset`**. The body
contains real non-ASCII UTF-8, such as a room name like `"Päämakuuhuone 1"`. Error paths serve
`text/html` with a plain-text body. **So the client reads bytes and decodes UTF-8 explicitly. It
never uses `response.json()`** (§3.2).

Top level:

| Field | Observed | Notes |
|---|---|---|
| `id` | `"FU2yTQsAVW8cYBgrehc2z4"` | 22 chars, **mixed case**. The vendor document says 23 lowercase. It is wrong on both counts. Never lowercased, never length-validated. |
| `name` | free text, non-ASCII | The MyHeatit app's device name. Not writable over this API. |
| `room` | `""` unassigned, else free text (`"Bedroom"`) | The *assigned room*. Not writable over this API. |
| `model` | `"Heatit WiFi Panel Heater"` | **Undocumented**. We only know it exists because we looked. Used for `DeviceInfo.model`. **Never** used as a fingerprint (§4.2). |
| `firmware` | `"1.21"` | Independent of the document's own version numbering. |
| `state` | `"Idle"` / `"Heating"` | The *relay state*. No `Off` value exists. |
| `currentPower` | integer W | Instantaneous draw (590–601 W heating, 0 idle). **Not** a duty-cycle average. Trails the relay by ~15 s. |
| `totalConsumption` | float, **two decimals on the wire** (`0.00`) | The *energy counter*. Published in ~0.04 kWh steps, not continuously. |
| `roomTemperature` | float °C | Sub-zero readings are in contract. |
| `parameters` | object | §2.4. |
| `Network` | object | `SSID`, `mac`, `ipAddress`, `wifiSignalStrength`, `status`. |

`Network` details. `mac` is **UPPERCASE** with colons (`E4:B3:23:AA:BB:CC`). The device half is
redacted here, as it is everywhere outside `.local/`. Normalise it through `dr.format_mac` before it
reaches `connections`. `wifiSignalStrength` is a **signed** string (`"-65dBm"`). No sign fix-up is
needed or wanted. `status` reads `"ok"` on a connected panel. No other value can be reached without
dropping WiFi. The observed OUI `E4:B3:23` belongs to **Espressif**, not Heatit. That is the finding,
and the OUI is the only half of a MAC that carries one.

**No status field has ever been `null`.** The key set never changed across a 24-sample sweep. So the
integration models no third state. `null` is treated exactly as absent (§6.3).

### 2.4 The parameters

There are **thirteen** *observed parameters*. The vendor document lists fifteen. No panel has
ever returned `externalSensorFallback` or `lowTemperatureProtection`, so they are *unobserved*
parameters. They are **not modelled, not exposed, and not tested**. They are neither absent nor
unsupported. They have simply never been seen. Register rows Q48 and Q49 track whether they ever
appear. A positive answer arrives as a captured fixture, not as a checkbox.

| Wire name | Type | Range / values | Read path under `parameters` | Serialisation on the wire |
|---|---|---|---|---|
| `panelMode` | int | 0 Off, 1 Heating, 2 Eco | `panelMode` | bare integer |
| `heatingSetpoint` | float °C | 5.0–40.0, **step 0.5** | `heatingSetpoint` | quantise 0.5, then `f"{v:.1f}"` |
| `ecoSetpoint` | float °C | 5.0–40.0, **step 0.5** | `ecoSetpoint` | quantise 0.5, then `f"{v:.1f}"` |
| `minimumTemperatureLimit` | float °C | 5.0–40.0, **step 0.5** | `minimumTemperatureLimit` | quantise 0.5, then `f"{v:.1f}"` |
| `maximumTemperatureLimit` | float °C | 5.0–40.0, **step 0.5** | `maximumTemperatureLimit` | quantise 0.5, then `f"{v:.1f}"` |
| `sensorCalibration` | float °C | −6.0–6.0, **step 0.1** | `sensorCalibration` | quantise 0.1, then `f"{v:.1f}"` |
| `loadLimit` | int ×100 W | 1–15, capped by `maxLoad` | `loadLimit` | bare integer |
| `activeDisplayBrightness` | int ×10 % | 1–10 | `activeDisplayBrightness` | bare integer |
| `standbyDisplayBrightness` | int ×10 % | 0–10 | `standbyDisplayBrightness` | bare integer |
| `disableButtons` | int | 0 enabled, 1 disabled, 2 lock menu | `disableButtons` | bare integer |
| `temperatureDisplay` | bool | false = setpoint, true = measured (**in standby only**) | `temperatureDisplay` | lowercase `true`/`false` |
| `sensorMode` | bool | false = internal, true = external wireless | `sensorMode` | lowercase `true`/`false` |
| `openWindowDetection` | bool | — | **`OWD.openWindowDetection`** | lowercase `true`/`false` |

Read-only members of `parameters`: `maxLoad` (the *rated load*, ×100 W), `OWD.activeNow` (bool),
`OWD.activeTime` (int seconds, **`0` while `activeNow` is false**).

**One read/write asymmetry must be hard-coded.** `openWindowDetection` is *written* flat
(`?openWindowDetection=true`) but *read* nested at `parameters.OWD.openWindowDetection`.

### 2.5 Write semantics

**Writes go in the query string, flat.** Both a query string and a JSON body work at firmware
1.21. The query string is what the vendor document specifies, and it is what we ship. There is **no
transport hedge**: no setup probe, no options override, no per-write fallback. The register records
that a JSON body also worked, as a documented option if a future firmware breaks the query path. It
is a note, not a code path.

**One parameter per request.** Batching cannot be expressed at all, because the client's write
method takes a single parameter. Atomicity has not been probed (register Q4). A partial failure in
a multi-parameter write would leave the state unknown. The single-parameter design also keeps a
firmware defect out of reach. A `POST` with no parameter gets **no response at all**. The firmware
closes the connection, and the documented `422` does not exist. A single-parameter API can never
send that request.

**A write succeeds when the HTTP status is 200 *and* `status` matches case-insensitively.** The
match is done after stripping whitespace and trailing punctuation. This is mandatory, not defensive.
The device sends `"Success"` **capitalised** and `"failed"` **lowercase**. That contradicts the
document (`enum: [success]`) and is inconsistent with itself. **The whole API uses one envelope**,
resets included. There is no `reset` key.

**Never branch on `reason`.** One device has shown five different punctuation styles
(`is invalid!`, `is not in range 0~10`, `must be step values of 0.5`,
`outrange of temperature limit(min or max)`,
`minimumTemperatureLimit is greater than current max temperature limit or equal to it`). The text is
freeform, and the vendor may change it. **Show it verbatim to the user. Never match on it.**

**The *write echo* reports what was applied, not what was requested.** It uses the exact parameter
names sent, and it **normalises types** (`19` for `19.0`, `-1` for `-1.0`). It is the basis of the
optimistic update (§5.4). It is not always honest. `sensorMode=true` on a panel with no external
sensor paired echoes `true`, but the device keeps `false`. That is a *silent undo* (§6.5).

**Quantisation is real and undocumented, and it is not consistent across parameters.**
Temperatures are quantised to **0.5**, not the 0.1 that the document's `^\d+\.\d{1}$` pattern
implies. `heatingSetpoint` and `ecoSetpoint` **silently snap** an off-step value. The two limits
**reject** an off-step value with a 400. `sensorCalibration` really is step **0.1**. The pattern is
also stricter than the device. Bare `39`, `39.00` and `039.0` are all accepted. Only a leading `+`
is rejected, as the regex predicts. A decimal on an integer parameter
(`standbyDisplayBrightness=1.0`) is rejected. **Client-side quantisation is what makes the silent
snap harmless.** We never send an off-step value, so the device never has to snap one.

**Booleans are lenient.** `true`/`True`/`TRUE`/`1` and the false equivalents all apply correctly.
`yes`/`no` are cleanly rejected. The feared silent misread, where `False` parses as true, **does
not occur**. We send lowercase for robustness, not to fix a bug.

**Writing a parameter to the value it already holds returns 200**, not 422. No diff-before-write is
needed.

**A write shows up in the status within 1.5 s** (measured 305 ms and 632 ms). An immediate read
after a write returns **stale** data. This was observed directly. Writes themselves complete in
46–319 ms.

**The limits bind both banks.** They bound `heatingSetpoint` and `ecoSetpoint` in the same way.
Bounds are inclusive. `min < max` is enforced. **Narrowing a limit past a stored setpoint clamps
that setpoint on the device** within the write-to-status lag. That eco also clamps is inferred by
symmetry, not observed.

**Eco regulates to `ecoSetpoint`.** This is the founding assumption of the climate design, and it
has now been observed. In `panelMode 2`, with eco raised 1.3 °C above room temperature, the relay
closed within 2 s and drew 598 W. **Cross-bank writes are stored and inert.** Writing
`heatingSetpoint` while in Eco is accepted and stored, and changes nothing about regulation.

**Resets.** The bare `DELETE /api/reset/kwh` zeroes the counter. This was verified with 0.04 kWh
banked: `0.04 → 0.0` within 5 s. `?resetKwh=Reset`, `?resetKwh=reset` and `?resetKwh=bogus` are all
accepted the same way. The enum is not enforced. **Send `?resetKwh=Reset` anyway.** It costs one
parameter, matches the documented contract, and is provably ignored. So it is free insurance
against a firmware that starts enforcing it. `DELETE /api/reset/settings` returns the same uniform
envelope. It does **not** reboot the panel. It leaves `id` / `name` / `room` / `Network` untouched.
It applies **staggered over up to ~8 s** (4.6 s and 5.2 s measured, Q34), so the 1.5 s post-write
refresh sees a *partial* reset and the next poll completes it. On the 600 W unit, the post-reset `loadLimit` stays clamped at `maxLoad`
rather than the document's default of 15.

---

## 3. Architecture

### 3.1 Repository layout

```
custom_components/heatit_wifi_panel/
├── __init__.py            async_setup_entry / async_unload_entry / PLATFORMS
├── manifest.json
├── const.py               DOMAIN, LOGGER, VERIFIED_FIRMWARES, tuning constants
├── api.py                 the client — imports nothing from homeassistant
├── registry.py            the parameter registry (§3.3)
├── coordinator.py         HeatitWifiPanelConfigEntry alias + HeatitWifiPanelCoordinator
├── entity.py              base CoordinatorEntity + DeviceInfo
├── config_flow.py
├── diagnostics.py
├── climate.py  number.py  switch.py  select.py  sensor.py  binary_sensor.py  button.py
├── icons.json
├── quality_scale.yaml
├── translations/
│   └── en.json            fully expanded; there is NO strings.json
└── brand/
    ├── icon.png           256×256
    └── icon@2x.png        512×512
scripts/
├── probe.py               hardware conformance probe (§12)
├── check_conformance.py   CI gate over the register (§12)
├── check_quality_scale.py CI gate over quality_scale.yaml (§9)
├── capture_fixtures.py    read-only fixture capture (§8)
└── check.sh               the one shared local/CI entry point (§9)
tests/                     §8
docs/                      this spec, the register, the ADRs, the research
hacs.json  LICENSE  README.md  CHANGELOG.md  AGENTS.md  CONTEXT.md
```

**We must not ship `strings.json`.** For custom integrations, that file and its `[%key:...%]`
placeholder syntax are build-time features. Nothing resolves them at runtime. Shipping either one
makes the config flow show raw keys. The file we author is a fully-expanded `translations/en.json`.

No `services.yaml`: v1 registers no service actions.

### 3.2 The client — `api.py`

**The client imports nothing from `homeassistant`.** This is not for portability. There is no
library and no core submission. It is for testability. The client is tested over `aioresponses`
with no `hass`, and `scripts/capture_fixtures.py` imports it directly without booting Home Assistant.

The public surface is exactly four methods:

```python
async def get_status(self) -> PanelStatus       # the only method with a retry
async def set_parameter(self, key: str, value: object) -> object   # returns the applied value
async def reset_kwh(self) -> None
async def reset_settings(self) -> None
```

There is deliberately **no public request method that takes a retry count**. This means nobody can
write a retried reset by accident (§3.6).

**Session.** The client takes `session=async_get_clientsession(hass)` and never creates its own.
This satisfies `inject-websession`. Some worried that a pooled session would hurt a small embedded
server. Nothing observed on this device supports that worry. Keep-alive works, idle sockets survive
for 65 s or more, and reuse is no faster than a fresh connection. This decision would be reversed if
a panel were observed refusing or dropping a reused connection.

**One request in flight per panel.** The client holds an `asyncio.Lock`. Every request to one panel
waits its turn in arrival order. That includes polls, writes, resets, and the post-write refresh. So
a single HA instance never opens more than one connection to a panel. The accept backlog cannot
fill. Write-then-refresh ordering is guaranteed by us, not left to the device. The lock is per
client instance, and there is one client per config entry. The config flow's validation client is a
separate instance with no shared lock. So a validation `GET` may overlap a poll. The device
tolerates that.

**Response handling.** Read bytes, call `.decode("utf-8")` explicitly, then `json.loads`. Never use
`response.json()`. A success response carries no `charset` and real non-ASCII, and error paths serve
`text/html`.

**Exceptions** (device vocabulary, no HA types):

| Exception | Raised for |
|---|---|
| `HeatitConnectionError` | timeout, refused, dropped, OS-level |
| `HeatitResponseError` | unexpected HTTP status; carries `status_code` and the raw `reason` |
| `HeatitParameterRejected` (subclass, 400) | also carries the parameter name **we sent**, because `reason` cannot be parsed |
| `HeatitProtocolError` | a 200 whose body we could not make sense of |

The client keeps the **last raw status body and headers** for diagnostics (§7.3).

### 3.3 The parameter registry — `registry.py`

The registry is a module-level table of frozen descriptors, one per *observed parameter*. Each
descriptor carries:

- the **wire name** and the Python type;
- the **serialiser and step** (§2.4), set per parameter, not per type;
- **bounds or enum** for client-side validation;
- the **dotted read path** into the status;
- a **scale** where the user-facing unit differs from the wire (`loadLimit` ×100 W, the brightnesses
  ×10 %);
- a **presence flag**.

The registry pays for itself four times over. The read/write asymmetry (`openWindowDetection`)
lives in one place. The per-parameter step rules have one home. Client-side validation turns an
out-of-range value into a local error instead of a device `400`. And the entity surface (§5) is
driven from the same table instead of restating thirteen ranges.

**The presence flag guards against a *dropped* parameter, not a spec-only one.** The registry holds
observed parameters only. A future firmware that stops returning one of the thirteen must not break
setup. §8 tests that for each observed parameter.

### 3.4 Config entry and coordinator

```python
# coordinator.py
type HeatitWifiPanelConfigEntry = ConfigEntry[HeatitWifiPanelCoordinator]
```

The alias name is **regex-constrained** to `^[A-Za-z][A-Za-z0-9]+ConfigEntry$`. Only letters and
digits are allowed, so an underscore fails. Ours is exactly `HeatitWifiPanelConfigEntry`.

```python
# __init__.py
PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR, Platform.BUTTON, Platform.CLIMATE, Platform.NUMBER,
    Platform.SELECT, Platform.SENSOR, Platform.SWITCH,
]

async def async_setup_entry(hass, entry: HeatitWifiPanelConfigEntry) -> bool:
    client = HeatitClient(entry.data[CONF_HOST], session=async_get_clientsession(hass))
    coordinator = HeatitWifiPanelCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    _async_register_device(hass, entry, coordinator.data)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True
```

The order matters: first refresh, then assign `runtime_data`, then register the device, then forward
platforms. **Do not clear `runtime_data` on unload.** Core removes it. `hass.data` is untouched.
`async_forward_entry_setup` (singular) and `async_setup_platforms` have been removed from core. Do
not use them. **No sleep of any kind in setup** (§3.6).

The coordinator subclasses `DataUpdateCoordinator[PanelStatus]`. It carries a class-level
`config_entry: HeatitWifiPanelConfigEntry` annotation to narrow away the inherited `| None`. It
passes `config_entry=` to `super().__init__`. Core does not enforce that for custom integrations,
but passing it wires `async_on_unload(self.async_shutdown)` and honours `pref_disable_polling`. It
marks `_async_update_data` with `@override`. `async_config_entry_first_refresh()` is called
**only** from `async_setup_entry` in `__init__.py`. It asserts `SETUP_IN_PROGRESS` and raises hard
anywhere else.
The coordinator is built in `__init__.py`, never inside a platform's `async_setup_entry`.

`update_interval` comes from the options *poll interval* (§4.5). Option changes take effect by
**reloading the entry**. `OptionsFlowWithReload` does the reload. There is no update listener
(§4.6). `coordinator.update_interval` is never changed in place.

### 3.5 Entities — `entity.py` and the platform modules

A base `CoordinatorEntity[HeatitWifiPanelCoordinator]` supplies `DeviceInfo` and the availability
rule (§6.3). Rules for every platform:

- `_attr_has_entity_name = True` on every entity, no exceptions.
- **Names come from `translation_key`, resolved in `translations/en.json`. They never come from
  `_attr_name` literals.** Core's name resolution checks `_attr_name` *before* `translation_key`,
  and `_attr_name = None` counts as set. So setting both silently ignores the key. The one entity
  that sets `_attr_name = None` is the climate entity. That marks it as the main feature. Its
  `translation_key` then serves state and icon translations only.
- `_attr_unique_id = f"{device_id}-{description.key}"`.
- Entity descriptions are `@dataclass(frozen=True, kw_only=True)`. They are declared in the
  platform module and carry `value_fn` / `set_value_fn` callables.
- `PARALLEL_UPDATES = 0` in `sensor.py` and `binary_sensor.py`. `PARALLEL_UPDATES = 1` in
  `climate.py`, `number.py`, `switch.py`, `select.py`, `button.py`. This sits *on top of* the
  client's per-panel lock. `PARALLEL_UPDATES` only serialises within a platform.

`DeviceInfo` is built once, from the first status:

```python
DeviceInfo(
    identifiers={(DOMAIN, status.id)},
    connections={(dr.CONNECTION_NETWORK_MAC, status.network.mac)},   # format_mac applied by core
    manufacturer="Heatit",
    model=status.model,          # "Heatit WiFi Panel Heater", from the device
    name=status.name,
    sw_version=status.firmware,
)
```

No `configuration_url` (§2.2). `via_device` **was removed from the `DeviceInfo` TypedDict in HA
2026.8** and is now a typing error. We have no hub, so nothing replaces it. Core applies
`format_mac` automatically inside `connections`. Call it yourself only for `unique_id` or
`identifiers`, and here those use the *device id* instead. v1 does **not** keep `sw_version` live
across a firmware update. A firmware change is picked up on reload (§6.3).

### 3.6 Timeouts, retries and startup

| | |
|---|---|
| `GET /api/status` | `ClientTimeout(total=5, connect=3)` per attempt. **Retried once** on any `aiohttp.ClientError` or `TimeoutError`, with no backoff. That gives a **poll budget of 10 s**. |
| `POST /api/parameters` | `ClientTimeout(total=10, connect=3)`, **one attempt, never retried** |
| `DELETE /api/reset/*` | `ClientTimeout(total=10, connect=3)`, **one attempt, never retried** |

Measured reads and writes complete in well under a third of a second. So these numbers cover WiFi
loss, not device speed.

**Lock wait is outside the budget.** Timeouts cover wire time only. Queueing behind the lock adds
to the caller's wait, but it is never a failure by itself. The worst case is a write queued behind
a fully retried poll. That is 20 s, and it only happens when the panel is already failing polls.

**Writes are never retried.** A write is idempotent in effect. But a retry doubles the user's wait,
and it only proves that the request was *sent*, not that it was *applied*. The echo can lie, and
the 1.5 s refresh is the authority. When a *poll* retry succeeds, the client logs one debug line
naming the panel and the first attempt's error. A retry is a dropped packet, not a device anomaly.

**Keep-alive is left at defaults.** No `force_close`, no `Connection: close`, no custom keep-alive
timeout. With a poll interval of 30 s or more, every poll opens a fresh connection anyway. Reuse
happens only between a write and its 1.5 s refresh, or between a failed attempt and its retry. The
device holds idle sockets far longer than either gap.

**No startup stagger, ever, and no sleep in setup.** Multi-device restart failures on related
Heatit hardware were traced to swallowed exceptions and a missing `ConfigEntryNotReady`. The device
was not the cause. At restart each panel receives exactly one connection, and the measured accept
backlog can handle that. Our first refresh goes through `async_config_entry_first_refresh`, which
raises `ConfigEntryNotReady` and lets Home Assistant retry with its own backoff. The status read has
its own retry. `DataUpdateCoordinator` already jitters every scheduled refresh by a random
0.05–0.5 s, so we need to do nothing to stop entries polling in lockstep. No global semaphore, no
jittered first refresh.

### 3.7 Named constants (`const.py`)

| Constant | Value | Justified by |
|---|---|---|
| `POST_WRITE_REFRESH_DELAY` | `1.5` s | write→status lag 305–632 ms (register Q31) |
| `RESET_VERIFY_DELAY` | `5` s | counter reads 0.00 within 5 s of the ack (Q45). Recorded as the upper bound it is. |
| `POLL_BUDGET` | `10` s (5 s × 2 attempts) | status read completes in under 5 s, observed 30–210 ms (Q43) |
| `MIN_POLL_INTERVAL` | `30` s | three times the poll budget |
| `DEFAULT_POLL_INTERVAL` | `60` s | §4.5 |
| `VERIFIED_FIRMWARES` | `{"1.21"}` | mirrors `tests/fixtures/observed/fw-*/` and the README table; asserted by a test (§8.6) |

---

## 4. Config flow, identity and options

### 4.1 Identity — the device id, verbatim

Recorded as **[ADR-0003](../adr/0003-device-id-as-unique-id.md)**.

| | |
|---|---|
| `unique_id` | the status `id`: 22 chars, **mixed case, never lowercased** |
| Entity unique ids | `{id}-{key}` |
| `DeviceInfo.identifiers` | `{(DOMAIN, id)}` |
| `DeviceInfo.connections` | `{(CONNECTION_NETWORK_MAC, Network.mac)}`. Hardware, not identity. |
| *Foreign panel* | status `id` ≠ entry `unique_id` → permanent setup failure, and a failed poll (§6.2) |

The MAC is strictly the more stable identifier. It was rejected on purpose, not overlooked. It sits
in `connections` so that there is a migration path if a firmware is ever found to change the device
id. Whether the id survives a **factory reset** or a **firmware update** is untested (register
Q52). That is the one identity claim ADR-0003 rests on. The id *is* known to survive a settings
reset.

### 4.2 The user step — host only

There is no name field. The title comes from the device (§4.4).

Validation is a **`GET` through the client's own parser**. It passes when the response is 200,
decodable, and the *required core* is present. The required core is `id`, `state`,
`roomTemperature`, and under `parameters`: `panelMode`, `heatingSetpoint`, `ecoSetpoint`. Nothing
else is required. This is deliberately stricter than setup (§6.2). Someone typing an address gets an
immediate answer instead of a retry loop. Validation must be a `GET`, because `HEAD /api/status`
returns 405.

| Outcome | Result |
|---|---|
| Timeout / refused / dropped | error `cannot_connect` |
| 200 but required core absent, or undecodable | error `invalid_response` |
| Valid, `id` already configured | abort `already_configured` |
| Valid, new | create entry |

`_abort_if_unique_id_configured()` is called **bare**, without `updates=`. Adding a panel only adds
a panel. Changing an address is the reconfigure flow's job. So re-adding a moved panel aborts. It
does not silently rewrite an existing entry's connection data.

**`model` never gates setup.** It is the strongest available evidence that a host is a Heatit
panel, and it is wholly undocumented. Gating on it would lock out any unit whose string differs or
whose firmware drops the key, with no workaround. It is used for `DeviceInfo.model`, where its
absence costs nothing.

### 4.3 Discovery — `registered_devices` and nothing else

```json
"dhcp": [{ "registered_devices": true }]
```

**No `zeroconf` key, no `ssdp` key.** `registered_devices: true` matches only devices already in
Home Assistant's registry via `CONNECTION_NETWORK_MAC`, which §3.5 populates. This gives automatic
IP-follow for a configured panel, zero false positives, no claim to new-device discovery, and one
manifest line.

`async_step_dhcp` receives a `DhcpServiceInfo` carrying only ip / hostname / macaddress. It does:

1. `GET /api/status` at the discovered IP.
2. `async_set_unique_id(id)`.
3. `_abort_if_unique_id_configured(updates={CONF_HOST: ip})`.
4. On any failure, a **quiet abort** with the reason step 1 computed: `cannot_connect` or
   `invalid_response`, the same pair as §4.2. Home Assistant fires the step again on the next DHCP
   event. So a panel still booting after a fresh lease is picked up shortly after.

The status read is not optional. The *device id* is not in the DHCP packet. Matching on the
packet's MAC alone would repoint an entry without the id check that foreign-panel safety depends on.

**Why no mDNS or SSDP matcher.** The panel runs no mDNS responder. Unicast mDNS to its `:5353` drew
no reply. That was tried from an ephemeral port and from source port 5353, for
`_services._dns-sd._udp.local`, `_http._tcp.local` and `_heatit._tcp.local`. A multicast browse
through a reflecting router also returned no record for it. In that browse the panel's own-segment
neighbours answered within 100 ms. The panel showed no service of any type, no hostname, and no
answer to the reverse lookup of its address (register row Q28, procedure P-2, fw 1.21). Unicast SSDP
to `:1900` drew no reply, and only tcp/80 is open. That negative stays **soft**, because SSDP
reflection was not demonstrated. Separately, the Espressif OUI rules out a `macaddress: "E4B323*"`
matcher completely. It would fire on every ESP32 device on a user's LAN, and the same browse saw
other devices with that prefix. The DHCP lease hostname is still unread. If a later on-segment run
finds a distinctive one, it amends this spec. It did not delay it.

`quality_scale.yaml`: `discovery-update-info` **done** (`async_step_dhcp` in `config_flow.py`);
`discovery` **exempt**, with the finding above as the comment.

### 4.4 Naming and area — read once, then frozen

`name` becomes the entry title **and** the device name. A `room` that matches an area Home
Assistant already has becomes `suggested_area`. A `room` that matches no area is dropped. Both are
read **at creation only**. A poll never rewrites them.

The area registry belongs to the user, not the panel. `suggested_area` is core's only
creation-time area input. Core resolves it through `area_registry.async_get_or_create`. So passing
the room unconditionally would *create* an area for any room name the user has never made one for.
That adds to the registry instead of choosing from it. So the room only ever picks between areas
that already exist. The match uses the registry's own normalisation, so `bedroom` finds `Bedroom`.
With no match, the device is left unassigned and Home Assistant offers its own area picker for it.
A user who never set a room in the MyHeatit app ends up in the same place.

Home Assistant's convention is that the user owns the entry title and device name once the entry
exists. That is why the rediscovery idiom updates `CONF_HOST` and never the title. Following an app
rename would silently destroy a rename made in Home Assistant. There is no way to tell "the user
renamed this in HA" from "the user never touched it". So an app rename simply diverges.

### 4.5 Reconfigure — host only, and it never adopts

Home Assistant's documentation fixes the mechanism. It is not a matter of preference.
`async_step_reconfigure` must *update the current entry and abort*, and it *should not create a new
entry*. There is no documented route to adopting a different device. The
`_abort_if_unique_id_mismatch` helper exists to forbid it.

The step takes the host only. It calls `await self.async_set_unique_id(id)`, then
`self._abort_if_unique_id_mismatch(reason="wrong_panel")`, and finishes with
`async_update_reload_and_abort(self._get_reconfigure_entry(), data={CONF_HOST: host})`.

The translated `config.abort.wrong_panel` string **names both the expected and the found device id.
It states that a replaced unit must be added as a new entry.** A replaced panel means delete and
re-add, and that loses history. That is the platform's answer. The alternative is a button that
quietly rewrites device identity.

The host is **not** an options field. The README recommends a static DHCP reservation.

### 4.6 Options — the poll interval, alone

| | |
|---|---|
| Field | *poll interval*, seconds |
| Default | **60 s** |
| Minimum | **30 s** |
| Applied by | `OptionsFlowWithReload` → entry reload |

The default is 60 s because every write already schedules its own 1.5 s refresh. So the interval
only governs how fast Home Assistant notices *external* changes: the physical buttons, the MyHeatit
app, open window detection firing, and the relay flipping. 60 s halves the traffic to a wall heater
whose room temperature moves slowly. It is also clearly safe at HACS review, where an aggressive
default is a documented rejection reason. Anyone who wants faster feedback can go down to 30 s.
That is the whole reason the option exists.

**Nothing else belongs in options.** Every other user preference is a CONFIG-category entity (§5).
Bronze `config-flow` reserves `ConfigEntry.options` for preferences and `ConfigEntry.data` for
connection info. So `data` = `{CONF_HOST}` and `options` = `{poll interval}`.

All 21 entities go briefly unavailable on an option change. That is a rare, deliberate action. It
is a fair price for never shipping a stale-config bug. It also reuses the unload path the test suite
already exercises.

### 4.7 Multiple panels

Each panel gets one config entry, one device, and one coordinator. **Nothing is global.** The HA
session is shared and HA-managed. Concurrency is bounded per panel by the client lock. `hass.data`
is untouched. Each entry takes its title from its own `name` and its area from its own `room`.
`has_entity_name` builds display names from the device name.

---

## 5. The entity surface

**21 entities** at firmware 1.21. **3 are disabled by default.** An implementer works straight down
this table.

### 5.1 Not entities, by decision

These are not entities: `panelMode` (owned by climate), `state` (climate `hvac_action`), `maxLoad`
(shown as the load limit's maximum), `Network.SSID` / `ipAddress` / `status`, `name`, `room`, `id`,
`firmware`, `model`. The diagnostic entities stop at signal strength.

### 5.2 The table

Names come from `translations/en.json` at `entity.<platform>.<translation_key>.name`. Icons come
from `icons.json`, keyed the same way, and only where a device class does not supply one. "Key" is
both the `translation_key` and the `{id}-{key}` unique-id suffix. "On" = `entity_registry_enabled_default`.

| Platform | Key | Name | Read path | Device class · unit · state class | Category | On | Bounds / options / notes |
|---|---|---|---|---|---|---|---|
| climate | `panel` | *(`_attr_name = None`)* | §5.3 | — | — | yes | §5.3. `translation_key` serves icon/state translation only |
| number | `comfort_setpoint` | Comfort setpoint | `parameters.heatingSetpoint` | temperature · °C | CONFIG | yes | step 0.5; min/max = the device limits, **dynamic** |
| number | `eco_setpoint` | Eco setpoint | `parameters.ecoSetpoint` | temperature · °C | CONFIG | yes | as above |
| number | `minimum_temperature_limit` | Minimum temperature limit | `parameters.minimumTemperatureLimit` | temperature · °C | CONFIG | yes | 5.0 .. (current max − 0.5), step 0.5, **dynamic**. So HA never offers a value the device rejects for min ≥ max |
| number | `maximum_temperature_limit` | Maximum temperature limit | `parameters.maximumTemperatureLimit` | temperature · °C | CONFIG | yes | (current min + 0.5) .. 40.0, step 0.5, **dynamic** |
| number | `sensor_calibration` | Sensor calibration | `parameters.sensorCalibration` | **none** · °C | CONFIG | yes | −6.0 .. 6.0, step 0.1. **No device class on purpose.** It is an offset, and converting an offset to °F gives a wrong value. Icon `mdi:thermometer-plus` |
| number | `load_limit` | Load limit | `parameters.loadLimit` | power · W | CONFIG | yes | 100 .. `maxLoad × 100`, step 100, **dynamic max**. Registry reads ×100, writes ÷100, bare integer on the wire |
| number | `active_display_brightness` | Active display brightness | `parameters.activeDisplayBrightness` | none · % | CONFIG | yes | 10 .. 100, step 10. Registry ×10 / ÷10. Icon `mdi:brightness-6` |
| number | `standby_display_brightness` | Standby display brightness | `parameters.standbyDisplayBrightness` | none · % | CONFIG | yes | 0 .. 100, step 10. Registry ×10 / ÷10. Icon `mdi:brightness-4` |
| switch | `open_window_detection` | Open window detection | `parameters.OWD.openWindowDetection` | — | CONFIG | yes | Written **flat** as `openWindowDetection` |
| switch | `external_sensor` | External sensor | `parameters.sensorMode` | — | CONFIG | yes | Safe to expose. The write is **inert without a paired sensor**. The echo lies here, so the switch flips on and then back off at the 1.5 s refresh. That is accepted, §5.4 |
| select | `standby_display` | Standby display | `parameters.temperatureDisplay` | options `setpoint`, `measured_temperature` | CONFIG | yes | `false` ↔ `setpoint`, `true` ↔ `measured_temperature`. A select, not a switch, because both states are meaningful |
| select | `buttons` | Buttons | `parameters.disableButtons` | options `enabled`, `disabled`, `menu_locked` | CONFIG | yes | 0 / 1 / 2. **Named the way the device and the app name it.** Not inverted into a "lock" |
| sensor | `temperature` | Temperature | `roomTemperature` | temperature · °C · measurement | — | yes | The one mirror of climate state, per the floor-thermostat precedent |
| sensor | `power` | Power | `currentPower` | power · W · measurement | — | yes | Instantaneous draw, not a duty-cycle average |
| sensor | `energy` | Energy | `totalConsumption` | energy · kWh · **total_increasing** | — | yes | §5.5 |
| sensor | `signal_strength` | Signal strength | `Network.wifiSignalStrength` | signal_strength · dBm · measurement | DIAGNOSTIC | **no** | Parse `^\s*(-?\d+)\s*dBm\s*$` case-insensitively. **No sign fix-up**, because the device emits a signed value. On parse failure, return `None` and log one debug line. **Never** raise an exception |
| sensor | `open_window_time_remaining` | Open window time remaining | `parameters.OWD.activeTime` | duration · s · **no state class** | DIAGNOSTIC | yes | `0` when inactive (observed). Whether it counts down is register Q47 |
| binary_sensor | `open_window_detected` | Open window detected | `parameters.OWD.activeNow` | **no device class** | — | yes | On/Off, not Open/Closed. It is an inference, not a contact. Icons `mdi:window-open-variant` (on) / `mdi:window-closed-variant` (off) |
| button | `reset_energy` | Reset energy counter | `DELETE /api/reset/kwh?resetKwh=Reset` | — | CONFIG | **no** | §5.5. Never retried. Icon `mdi:counter` |
| button | `restore_defaults` | Restore default settings | `DELETE /api/reset/settings` | — | CONFIG | **no** | Keeps network and pairing. Applies **staggered over up to ~8 s**. So the 1.5 s refresh may see a partial reset, or none of it yet, and a later poll completes it. Icon `mdi:restore` |

Counts: 1 climate, 8 numbers, 2 switches, 2 selects, 5 sensors, 1 binary sensor, 2 buttons.

### 5.3 The climate entity

```
hvac_modes         = [HVACMode.OFF, HVACMode.HEAT]     fixed, never computed from state
preset_modes       = [PRESET_COMFORT, PRESET_ECO]      panelMode 1 → comfort, 2 → eco
preset_mode        = None while Off
current_temperature = roomTemperature
target_temperature = the live setpoint (comfort in Heating, eco in Eco); None while Off
target_temperature_step = 0.5      precision left at the Celsius default (tenths)
temperature_unit   = UnitOfTemperature.CELSIUS
supported_features = TARGET_TEMPERATURE | PRESET_MODE | TURN_ON | TURN_OFF
```

**Why a preset and not a temperature range.** Eco cannot be a third `HVACMode`. The enum is
closed, core coerces `set_hvac_mode` to it, and the entity's `state` property raises on a
non-member. So the preset is the *only* way Eco can appear inside the climate dialog or on the
thermostat card. `TARGET_TEMPERATURE_RANGE` would expose both banks at once and keep history honest.
It was weighed seriously and rejected. Under it, a plain `climate.set_temperature` with
`temperature:` **fails**. That breaks the most common heater automation. It also forces eco ≤
comfort, which the panel does not. The two config `number` entities give the same honest per-bank
history without that cost. Recorded as **[ADR-0004](../adr/0004-eco-as-a-climate-preset.md)**.

**`hvac_modes` is fixed and never computed from live state.** So the capability list cannot flap.

**`TURN_ON` / `TURN_OFF` are mandatory and explicit.** The 2024.2 compatibility shim inferred them
from `HVACMode.OFF in hvac_modes`. That shim was **deleted in 2025.1**. There is now no warning and
no auto-add. Area-targeted service calls **silently skip** an entity that does not declare them.
Core's default `async_turn_on` / `async_turn_off` route correctly for a two-mode entity, so we write
no turn methods.

| HA call | Panel write |
|---|---|
| `set_hvac_mode(OFF)` / `turn_off` | `panelMode=0` |
| `set_hvac_mode(HEAT)` / `turn_on` from Off | **`panelMode=1`, always.** Turning on means comfort. The panel has no "on" verb and remembers nothing, so HA invents no memory either |
| `set_hvac_mode(HEAT)` while already Heating **or Eco** | **no-op.** Never flips Eco to comfort |
| `set_preset_mode(comfort)` / `(eco)` in any mode, **including Off** | `panelMode=1` / `=2`. A preset is an explicit choice of on-mode. So selecting one while Off turns the panel on in that mode |
| `set_preset_mode` | **sends the mode only**, never a temperature |

**Setpoint writes.**

- `set_temperature` writes the **live bank**. The live bank is **re-read from device state inside
  the call**, never from a cached preset. A device-side mode change that races the call must not
  write the wrong bank.
- With `hvac_mode` in the call: switch mode **first**, then write the bank *that mode* uses. Core
  passes `hvac_mode` through unvalidated and unapplied. Handling it is our job.
- **While Off**: `target_temperature` is `None`, and a plain `set_temperature` raises
  `ServiceValidationError` (`set_temperature_while_off`). The error tells the user to turn on or
  pass `hvac_mode`. This follows the Heatit floor thermostats, whose dial is blank while Off. There
  is one deliberate difference. They drop the write *silently*. We refuse *loudly*, so an automation
  learns it did nothing.
- The signature is `async_set_temperature(self, **kwargs)`, because core leaks `entity_id` into
  kwargs.
- The `number` entities write their named bank **unconditionally, in any mode**. This is verified
  safe. A comfort write made in Eco is stored and does not change regulation.

**Limits.** `min_temp` / `max_temp` come from the device's limits, reported as they are, with **no
client-side clamping**. The device bounds both banks itself, enforces min < max, and clamps a
stored setpoint when a limit narrows past it. So the out-of-bounds-display hazard does not arise. A
limit change is followed by a refresh, and the card is consistent again.

**`hvac_action` comes from the relay, with one synthesised value.** `state` leads `currentPower`
by ~15 s. So the action is derived from `state` and **never** from power.

| `state` | *Panel mode* | `hvac_action` |
|---|---|---|
| `Heating` | any | `HEATING`. The element is on. That stays true if a future firmware's frost protection heats while Off |
| `Idle` | Off | `OFF`. Synthesised, because the device has no Off value |
| `Idle` | Heating / Eco | `IDLE` |

This is the one place we deliberately differ from the floor thermostats. They report `idle` for an
Off thermostat. We follow core's convention and report `off`.

### 5.4 Rules that apply across the table

- **Units are real units.** Load limit in W, brightness in %. The registry descriptor carries the
  scale. The wire sees the device's integers. Nothing dimensionless is exposed.
- **Bounds are dynamic wherever they come from device state.** The setpoints' bounds are the
  limits. Each limit's inner bound is the other limit ± 0.5. The load limit's max is
  `maxLoad × 100`. All are read from coordinator data, never cached at setup.
- **Presence-gated creation.** A descriptor becomes an entity only if its read path resolves in the
  **first** status at setup. A parameter that appears later is picked up on **reload**, not live. A
  parameter that vanishes at runtime makes its entity **unavailable** (§6.3).
- **Only the temperature sensor mirrors climate state.** There is no heating binary sensor, because
  power and `hvac_action` already say it. There are no setpoint sensors, because the config numbers
  record history. Long-term statistics for setpoints were judged not worth two entities. Anything
  not in the table is **omitted**, not created disabled.
- **Optimistic updates follow one rule.** Apply the **echoed** value immediately, coerced back to
  the registry's declared type. Then run a debounced refresh at **1.5 s** as the authority. If the
  echo is missing or unparseable, fall back to the requested value. The refresh corrects either
  way. This stays one rule even though the echo lies for `sensorMode`. A per-parameter honesty flag
  was weighed and rejected, to keep the contract at one rule. The *silent undo* warning (§6.5) is
  what surfaces the exception.
- **Disabled by default means one of two things**, and nothing else: a **noisy diagnostic** (signal
  strength) or a **button whose press discards device state** (energy reset, settings reset). Any
  future reset-shaped button inherits opt-in without a new decision. It is not a general
  "dangerous" marker.
- **Two concepts, two names.** For open window detection: the *setting* is "Open window detection"
  (switch), the *detection* is "Open window detected" (binary sensor), and the *countdown* is "Open
  window time remaining" (sensor). The same rule applies to *low temperature protection* if it is
  ever observed. Its wire name means both a threshold and a live state. They must never share a
  name in prose or in the UI.

### 5.5 Energy and its reset

**The energy sensor stays `total_increasing`.**

- `state_class: total` with `last_reset` is **rejected**. The counter can be zeroed from the
  MyHeatit app, and possibly by a power cycle. Home Assistant can never learn when those happened.
  Only our own button presses are known. So a `last_reset` attribute would be wrong the first time
  anyone else resets it.
- HA has a **10 % dip tolerance**: a decrease smaller than 10 % is read as noise, not a reset. That
  is safe here **because the device resets to exactly `0.0`**. A partial reset would be misread,
  but this panel does not do one. That precondition is register row Q21.
- **One publication step, ~0.04 kWh, is lost per reset.** The counter publishes in lumps. It stayed
  flat for 274 s at ~591 W before the first step. A reset writes through within 5 s. So energy
  banked since the last published step never reaches HA's statistics. The loss is bounded by one
  step. We cannot fix it from our side. It is **documented rather than worked around**.
- Long-run statistics otherwise survive a reset intact. The drop starts a new meter cycle with zero
  point 0, and the running `sum` continues from the pre-reset total.

**The reset button stays, and it is opt-in.** An action mirroring `zwave_js.reset_meter` was
rejected. That shape comes from Z-Wave's generic meter command class, not from preference. It would
also put `services.yaml`, `action-setup` and `docs-actions` back on the plate for nothing. Dropping
the reset entirely was rejected too. The app and the panel's own display show the counter, and
parity with them is a legitimate reason to press it. A button entity cannot show a confirmation
dialog. So **disabled by default is the only guard Home Assistant offers.** A mis-tap has a bounded
cost: at most one unpublished step lost in HA, and the panel's own counter zeroed.

**Verification: warn once, at a later poll.** A parameter write has an echo to compare against. A
reset has none. So the only check is *did the counter drop below its pre-reset value*.

1. On press, record the **pre-reset value** (the last coordinator reading) and the **ack time**.
2. The **first poll that completes `RESET_VERIFY_DELAY` (5 s) or later after the ack** judges it.
   Any refresh that completes earlier, scheduled or write-triggered, is ignored for judging.
3. If the pre-reset value was **non-zero** and the judged reading is **not below it**, log a
   **warning once per entry lifetime** naming the pre-reset and current values. Later occurrences
   are debug until reload.
4. If the pre-reset value was zero, clear the pending record and log nothing.
5. A second press before judgement replaces the pending record.
6. **No retry, no availability effect.** The button's call has already returned. The warning is the
   only consequence.

Pressing at `0.0` still sends the request. The last reading may be a poll interval stale, and the
request is harmless. Only the verification is skipped. Accumulation within 30 s cannot reach a new
publication step, so "not below" is a reliable test at the poll-interval floor.

**Counter drops that Home Assistant did not cause are never logged.** A reset from the app is a
legitimate act. The statistics engine already treats the drop as a new cycle. It is not the device
misbehaving.

---

## 6. Failure and availability

**The governing idea: the poll is the sole judge of availability.** Setup, writes and resets never
decide whether the device is there. They raise to whoever called them and let the next status read
settle it.

### 6.1 Poll-time failure

A failed `_async_update_data` raises `UpdateFailed`. **Every entity goes unavailable on the first
failed poll.** There is no coordinator-level grace, no hand-rolled failure counter, and no stale
data served as fresh. The tolerance for a single dropped packet lives **one layer down**. The status
`GET` is retried once inside the poll budget (§3.6). So a poll fails only when the device was
unreachable for the whole budget.

Recovery is the next good poll. The coordinator logs the two transitions itself: one `error` line
on failure, one `info` on recovery, and nothing in between. **We add no lines of our own** to that
path. A panel that is off all night costs two log lines.

### 6.2 Setup-time failure — everything retries except a foreign panel

`async_setup_entry` runs `async_config_entry_first_refresh()`. Its failure becomes
`ConfigEntryNotReady`. Home Assistant retries at 5 s, 10 s, 20 s and so on, capped at 10 min,
forever. The exception's translation key is propagated.

| Condition | Result | Why |
|---|---|---|
| Host unreachable (timeout, refused, dropped) | `ConfigEntryNotReady` | A DHCP renew or a reboot. The panel may return at this address by itself |
| Host answers but is not a panel (404, `text/html`, unparseable) | `ConfigEntryNotReady` | A captive page or a mid-reboot stack looks identical. A permanent error would strand a panel that comes back |
| Status parses but lacks a *required core* field | `ConfigEntryNotReady` | Treated as drift or a transient. Retrying is free |
| Status carries an `id` different from the entry's unique id | **`ConfigEntryError`**, naming both ids | A *foreign panel* owns this address. Retrying can never fix it. The fix is the reconfigure step (§4.5) |

**The id check runs on every poll, not only at setup.** A status whose `id` is not the entry's
raises `ConfigEntryError` (key `foreign_panel`, placeholders `expected_id` / `actual_id`). It is
never accepted as data. The alternative would be writing one bedroom's setpoints into another
room's entities. One raise site serves both moments. A `ConfigEntryError` raised from a scheduled
refresh is caught and logged by the coordinator and never escalated. So at poll time the user sees
the device unavailable and one error line. A reload turns it into the permanent setup error.

### 6.3 Malformed or partial status

- **Required core**: `id`, `state`, `roomTemperature`, and under `parameters`: `panelMode`,
  `heatingSetpoint`, `ecoSetpoint`. If any of them is missing, or the body is not JSON, the poll
  fails (`UpdateFailed`, key `missing_field` with the dotted path, or `invalid_response`).
  Everything goes unavailable, and one log line names the field.
- **Every other observed field is optional.** If one is absent, that entity alone is unavailable and
  the poll succeeds. An absent `firmware` is treated as unverified (§7.2), not as an error.
- **`null` is absent.** No panel has ever returned one. The parser maps `null` to the same
  missing-path outcome, and the integration models no third state. This is revisited only if an
  observed fixture ever contains a `null`.
- **Unknown keys are ignored**, at top level and under `parameters`.
- **Presence is decided once, at setup.** A parameter that appears later is logged at debug and
  picked up on the next reload or restart. There is no dynamic entity addition and no automatic
  reload. A parameter that vanishes and returns makes its entity unavailable and then available
  again. Nothing is removed from the entity registry either way.

So per-entity availability is `super().available and <read path resolves in coordinator.data>`.
**Nothing stays available while the coordinator is failed**, the reset buttons included. Pressing
one against an absent device is a request with no meaning.

### 6.4 Write-time failure

All write errors are `HomeAssistantError`. All carry translation keys in `translations/en.json`.
The device's `reason` is passed through **verbatim and never parsed**:

| Client exception | HA exception | Translation key | Placeholders |
|---|---|---|---|
| `HeatitParameterRejected` (400) | `HomeAssistantError` | `parameter_rejected` | `parameter` (the name **we sent**), `reason` |
| `HeatitConnectionError` | `HomeAssistantError` | `cannot_connect` | — |
| `HeatitProtocolError`, `HeatitResponseError` | `HomeAssistantError` | `unexpected_response` | `status` |
| *(local)* plain `set_temperature` while Off | `ServiceValidationError` | `set_temperature_while_off` | — |

A 400 is **not** a user error. HA's number and climate layers validate ranges before we are
called. The registry also quantises and bounds locally. So a rejection that still reaches the
device means our bounds and the device's disagree. That is drift. It is surfaced as an error, in
the device's own words. `ServiceValidationError` stays reserved for the one local case above.

**After any write, success or failure, the same debounced 1.5 s refresh is scheduled.** The device
commits within 300–600 ms. So a timeout on the *response* does not mean the value did not stick.
The refresh brings HA in line with whatever the device did. **The write path never touches
availability.** A failed write raises to the caller. The next poll decides whether the device is
gone.

### 6.5 Silent undo

When the post-write refresh disagrees with the echoed value, the coordinator logs a **warning once
per parameter per entry lifetime**. The warning names the parameter, the echoed value and the
refreshed value. Later occurrences for the same parameter are debug until reload.

Client-side quantisation has already removed the snap case. So every mismatch that remains is a
real device refusal disguised as success. The one known instance is `sensorMode=true` with no
external sensor paired.

### 6.6 No repair issues in v1

`repair-issues` is exempt. The foreign panel shows up as `ConfigEntryError` on the integrations
page at setup, and as the coordinator's error line at poll time. An unverified firmware is an info
line. There is no repairs platform, no issue registry, and no fix flow.

---

## 7. Logging, redaction and diagnostics

### 7.1 One redaction function

A single function scrubs exactly **`id`, `Network.mac`, `Network.SSID`, `Network.ipAddress`**.
Logging, diagnostics and fixture capture all share it. **`name` is kept**, and so is `room`. They
are human-readable labels, not identifiers. `name` is also the evidence that the charset-less UTF-8
decode is required.

**Raw response bytes are never logged, at any level.** When parsing fails, the log line carries
the content type, the byte length and the exception. The documented way to get the bytes is
`scripts/capture_fixtures.py` or a diagnostics download. Both scrub.

One function means the HACS security review has a single surface to read. Leaked SSIDs, MACs and
PII in debug output are the most frequently cited rejection reason in that review.

### 7.2 Log levels

| Level | Line | Cadence |
|---|---|---|
| `error` / `info` | device unavailable / recovered | the coordinator's own, once per transition |
| `error` | first-refresh failure | the config-entry machinery's own |
| `warning` | a parameter present at setup **vanished** from status (entity → unavailable) | once per transition; `info` when it returns |
| `warning` | **echo mismatch** after the post-write refresh (§6.5) | once per parameter per entry lifetime, then debug |
| `warning` | **energy reset not observed** (§5.5) | once per entry lifetime, then debug |
| `info` | setup met a firmware with no observed fixture. Names the firmware and `VERIFIED_FIRMWARES` | once per setup |
| `debug` | per poll: request line, status code, byte length, the parsed status **after redaction** | every poll |
| `debug` | per write: parameter and value sent, status code, echoed value | every write |
| `debug` | a successful retry of a status read | per occurrence |
| `debug` | a parameter appeared after setup | once per transition |

**Nothing routine logs above debug. Nothing repeats per poll.**

### 7.3 Diagnostics

`diagnostics.py` implements **`async_get_config_entry_diagnostics` only**. One entry is one
device, so device diagnostics would duplicate it. The download contains:

- `entry_data` and `options` (host, poll interval) through the shared redaction;
- `status`: the coordinator's parsed data;
- `firmware`, and whether it is in `VERIFIED_FIRMWARES`;
- `observed_parameters` at setup and `vanished_parameters` since;
- `last_poll`: outcome, duration, whether the retry was used;
- **`raw`: the last status response body and headers as received**, through the same
  **wire-level** scrub. `async_redact_data` redacts dict keys, not text. So the raw section goes
  through our scrub, not HA's helper.

So a download from a user on an unverified firmware is a **fixture candidate**. It preserves fields
the parser does not model. That is the whole point of shipping the raw section.

---

## 8. Testing

**One panel at one firmware is not the fleet.** The answer to that is not a bigger suite. It is a
**provenance discipline**. Every fixture says where it came from. Nothing in the registry, the
entity table or the tests exists because a document said so.

### 8.1 Two tiers, and no third

| Tier | Runs | Talks to hardware | Writes |
|---|---|---|---|
| **Offline suite** — `pytest` | CI, every PR | never | never |
| **Conformance probe** — `scripts/probe.py` (§12) | by hand, dev present | yes | opt-in, approved, self-reverting |

There is **no third tier**. No opt-in live pytest marker, no env-var-gated hardware run. A third
tier would answer one question: *does the integration's own client still read this panel?* A
read-only capture script, `scripts/capture_fixtures.py`, answers it instead:

- it reads `.local/device.json`, imports the client **directly** (no HA boot), and performs the
  status read through the real read path;
- it writes the raw response bytes and headers under `tests/fixtures/observed/fw-<firmware>/`,
  scrubbing on the way (§8.3);
- it prints a diff against what is committed;
- it is **read-only by construction**. It has no code path that issues anything but
  `GET /api/status`, and it never runs in CI.

**The diff must separate the volatile fields**, or it is worthless. The status is computed per
request, and four fields move on their own: `wifiSignalStrength`, `roomTemperature`,
`currentPower`, `totalConsumption`. None of them is on the scrub list. The script prints them in a
separate **live values** block. That block is for information only and never counts as drift. A
difference **outside** those four is the drift signal. Excluding the four outright was rejected. A
field that stops moving is itself worth seeing.

A **new observed directory** appears only when a real panel produced it. A second panel or a new
firmware means a new `fw-<version>/` directory. Its capture is the admission ticket for anything it
shows that 1.21 did not.

### 8.2 The spec-derived mock is rejected

One option was to generate a device simulator from the OpenAPI document (Prism or equivalent), boot
HA against it, and assert a clean log. That is **not adopted**. The reason is recorded here so it is
not argued again:

- The document it would simulate has already lost to the device on the success sentinel, the reset
  envelope, the non-existent 422, idempotent writes and the float pattern. A spec-derived double
  would serve every one of those errors as truth. So a client that matches the panel would fail
  against it, and a client that passes it would fail against the panel.
- Its one unique offer is the full HA-boot path with no hardware. That is already covered by
  `pytest-homeassistant-custom-component`, which boots a real `hass` in-process against a fake
  client fed from **observed** bytes.
- It brings a Node toolchain into a Python project's CI.

### 8.3 Fixtures — observed or synthesised, never invented

```
tests/fixtures/
  observed/
    fw-1.21/
      manifest.json      captured_at, firmware, model, maxLoad, scrubbed_fields, capture-script version
      status.json        raw wire bytes, scrubbed — NOT re-serialised
      status.headers     raw response headers (a charset-less Content-Type is evidence)
  synthesised/
    manifest.json        per file: what it is, derived from which observed file, or transcribed from what
    write-echo-*.json
    error-400-*.txt
```

Observed files are the bytes the device sent, byte-for-byte outside the scrubbed fields. **They
are never round-tripped through `json.dumps`.** The wire says `"totalConsumption": 0.00`, and a
round-trip would silently rewrite it.

**The scrub list is exactly five fields.** Each is replaced by a fixed, shape-preserving
placeholder through targeted substitution on the raw bytes:

| Field | Placeholder | Why this shape |
|---|---|---|
| `Network.SSID` | `"SSID-REDACTED"` | never parsed |
| `Network.mac` | `"02:00:00:00:00:01"` | locally administered, valid for `format_mac` |
| `Network.ipAddress` | `"10.0.0.2"` | valid RFC 1918 IPv4 |
| `id` | `"FIXTUREFIXTUREFIXTUREX"` | same length (22) and mixed case as a real id, so `{id}-{key}` unique ids are exercised verbatim |
| `name` | `"Näytehuone 1"` | **stays non-ASCII**. This field is the evidence that the charset-less UTF-8 decode is required |

`room` is kept as captured, for the same reason as `name`. A CI test asserts that every
`observed/*/status.json` holds exactly the placeholder in each of the five fields. So an unscrubbed
capture cannot merge.

**Synthesised variants are derived, not written.** Off mode, Eco engaged, open window detection
active, a dropped parameter, an unknown extra key, a malformed body, a WiFi drop: nobody is turning
on a bedroom heater to capture these. They are produced **in test code by mutating an observed
fixture**. The test loads the reference bytes, parses them, changes the named fields, and
re-encodes. They are never hand-written as standalone JSON. So every unobserved part of a
synthesised fixture is real. A synthesised value may only take a form the device has been seen to
emit for that field. **No synthesised fixture may introduce a field no observed fixture contains.**

**Write echoes are transcribed now and replaced by the probe later.** The write-path responses
start life in `synthesised/`, with their manifest naming the source. These are the 200 echo with
its type normalisation, the 400 punctuation styles, the reset envelope, the `text/html` 404/405
bodies, and the connection drop on a parameter-less POST. The probe, run with writes enabled, saves
each write and reset response as raw bytes into `observed/fw-<version>/`. Those replace the
transcriptions.

**Reference fixture.** The suite pins one observed directory for state assertions. It is the newest
by version, named explicitly in `conftest.py`. A **parse-only sweep** runs the status parser over
*every* observed directory. So a second panel's capture extends the suite with no test edits.

### 8.4 Two seams, split by layer

| Tests of | Seam | Mechanism | Fixture source |
|---|---|---|---|
| The client (`tests/client/`) | **HTTP** | the real client over `aioresponses`, no `hass` | observed bytes + synthesised write responses |
| Config flow, coordinator, entities (`tests/integration/`) | **Client** | `FakeHeatitClient` patched in | the same observed bytes, parsed by the **real** parser |

There is one source of truth. The fake is built from an observed fixture's bytes *through the
client's real parser*. So its status shape can never drift from what the client produces. It
records every write. It answers a write with an echo built from the request, which is the device's
own behaviour. It also takes scripted failures for the coordinator and optimistic-update tests:
raise on the next read, or return a mutated status after a write.

### 8.5 What must be asserted

A reviewer checks this named list, not a percentage.

**Client, at the HTTP seam.** These are what a careless refactor would undo:

- The exact request for each serialisation class: `heatingSetpoint=19.0` (0.5-quantised, one
  decimal), `sensorCalibration=1.1` (0.1), `standbyDisplayBrightness=5` (bare integer, **never**
  `5.0`), `openWindowDetection=false` (lowercase). `loadLimit` is scaled ÷100 and the brightnesses
  ÷10 on the wire.
- Client-side quantisation and bounds: an off-step or out-of-range value raises **locally** and
  **no request is emitted**.
- **No code path emits a parameter-less `POST`.** Across the full write surface, the mock never
  sees a `POST /api/parameters` without a query.
- A write succeeds when the HTTP status is 200 **and** `status` matches case-insensitively after
  stripping whitespace and trailing punctuation. `"Success"`, `"success"`, `"Success."` pass.
  `"failed"` fails.
- Echo handling: the **applied** value is returned, coerced to the declared type (`19` → `19.0`,
  `-1` → `-1.0`). A missing or unparseable echo gives the requested value.
- Bytes are decoded as UTF-8 with **no charset** in `Content-Type`. The observed non-ASCII `name`
  survives.
- `400` → `HeatitParameterRejected` carrying the parameter name *we sent* and `reason` verbatim.
  `text/html` 404/405 → `HeatitResponseError` with `status_code`. Timeout / refused / dropped →
  `HeatitConnectionError`. 200 with an unparseable body → `HeatitProtocolError`.
- Resets: `DELETE /api/reset/kwh?resetKwh=Reset` and `DELETE /api/reset/settings` exactly, with
  the uniform `status` envelope, **never retried**. One request even on failure.
- Status parsing: every registry read path resolves against the reference fixture. The parse-only
  sweep runs over every observed directory.
- Signal strength: `"-67dBm"` → `-67`. No sign fix-up. Garbage → `None` and no exception.

**Integration, at the client seam:**

- **Config flow: every path in §4, at 100 % line coverage.**
- Setup against the reference fixture yields exactly **21 entities**. The entity table is a single
  test parametrised over a **test-side literal table** transcribed from §5.2. It covers unique id
  `{id}-{key}`, name, platform, device class, unit, state class, category, enabled-by-default, and
  initial state. **By rule it is never derived from the integration's descriptor table.** So the
  test compares two independent encodings.
- **Dropped-parameter tolerance**, parametrised over every observed parameter: remove it from the
  reference fixture, setup succeeds, exactly that entity is absent, every other entity is present.
  Also: an unknown extra key at top level and under `parameters` is ignored.
- Climate: `hvac_modes == [OFF, HEAT]`. Preset switching writes `panelMode`. `set_temperature`
  writes the **live** bank. `target_temperature is None` and `set_temperature` raises while Off.
  `hvac_action` for all three cases. Turn on lands in Heating. HEAT while in Eco is a no-op. A
  preset chosen while Off turns the panel on in that mode.
- **Dynamic bounds**: number min/max follow the limits, each limit follows the other ± 0.5, and
  the load limit's max follows `maxLoad × 100`. All come from coordinator data. This is verified by
  changing the fake's status and reading the bounds again.
- **Optimistic update**: after a write, the state shows the echoed value immediately. Exactly
  **one** refresh is scheduled at 1.5 s. This is asserted by advancing `hass`'s clock, never by
  sleeping. The refreshed value wins. This includes the `sensorMode` inert case (echo `true`,
  refresh `false`, state returns to off) and the once-per-parameter warning.
- Coordinator failure handling per §6: unavailable on the first failed poll, recovery on the next
  good poll, a foreign id is `UpdateFailed`, a missing required-core field is `UpdateFailed`, an
  optional missing field is per-entity unavailability, `null` == absent. The §7.2 table is the
  must-assert list for logging.
- Energy reset verification: a press records the pre-reset value. A poll that completes before 5 s
  does not judge. A later poll showing no drop warns exactly once.
- Buttons: reset-energy emits the exact `DELETE`. Both buttons are disabled by default.
- Fixture hygiene: every observed fixture carries the five placeholders.
- **Three-way firmware consistency**: the README `## Verified firmware` table's version set ==
  `tests/fixtures/observed/fw-*/` == `VERIFIED_FIRMWARES`.

### 8.6 What is not asserted

This list is recorded so this spec does not license coverage for its own sake:

1. **Home Assistant's own machinery**: that the coordinator polls on schedule, that entities
   register, that a config entry unloads. That is framework behaviour, tested upstream.
2. **The `reason` text of a 400.** It is never parsed and never branched on. It is asserted only as
   surfaced verbatim.
3. **The vendor document's regexes and enums.** They are not the device's rules. A test that a
   value matches `^\d+\.\d{1}$` pins fiction.
4. **Translation strings and icon choices.** Reviewed, not tested.
5. **Wall-clock timing.** The 1.5 s refresh is asserted by advancing the clock and counting
   refreshes, never by sleeping and measuring.
6. **Any firmware that did not produce a fixture.** No test asserts fleet-wide behaviour. Every
   assertion is scoped to an observed directory.
7. **Log wording**, beyond the presence of one line when a device goes unavailable and one when it
   recovers.

### 8.7 Gate, framework and CI matrix

**Hybrid gate.** Two things block a merge. The first is `config_flow.py` at **100 % line
coverage** (`coverage report --fail-under=100 --include='*/config_flow.py'`). It is a small module
where a missed path is a user-facing bug. The second is the named list in §8.5, checked by the
reviewer. Overall coverage is **measured and reported**, not gated. Core's silver 95 % is not
inherited.

**Framework.** `pytest` + `pytest-homeassistant-custom-component` (which provides `hass`,
`enable_custom_integrations`, `aioclient_mock`) + `aioresponses` for the client tests +
`pytest-cov`. `syrupy` is present through the harness but **unused**. Explicit assertions
everywhere, no snapshots. Layout: `tests/conftest.py`, `tests/fakes.py`, `tests/client/` (no
`hass`), `tests/integration/`, `tests/fixtures/`.

**Matrix: two rows.** `pytest-homeassistant-custom-component` releases in lockstep with HA core.
There is one package version per HA release, and each pins that HA exactly. So a row is one HA
release plus its Python.

| Row | Install | Python | Blocks merge | Also runs |
|---|---|---|---|---|
| **floor** | `requirements_test.txt`, `pytest-homeassistant-custom-component==0.13.317` (HA 2026.3.1) | 3.14 | **yes** | — |
| **latest** | `pytest-homeassistant-custom-component` **unpinned** | 3.14 | no (`continue-on-error`) | **monthly cron** |

The floor row is what a developer installs locally. The latest row is the early warning for a
monthly HA release deprecating something we use. Red there is a signal, not a blocker.

---

## 9. Quality and tooling

The quality scale is a **borrowed checklist, enforced by us**. `hassfest` returns early on
`if not integration.core`. It never parses `quality_scale.yaml` for a custom integration, and no
reviewer will either. So the adopted set is checked by our own CI or by nobody.

### 9.1 Which rules

**Every bronze, silver, gold and platinum rule that is about the code is adopted**, unless it is
listed below as `exempt` with a one-line reason. Leaving a rule out is what needs justifying.

| Exempt | Reason (verbatim into the yaml) |
|---|---|
| the 15 `docs-*` rules | require a `home-assistant.io` page; HACS-only integration, the README carries the facts |
| `strict-typing`, `dependency-transparency`, `async-dependency` | assume a published PyPI requirement; the client is a module inside the integration. Typing itself is enforced by mypy strict below, not by this rule |
| `repair-issues` | no repairs platform in v1 |
| `reauthentication-flow` | the local API has no authentication |
| `action-setup` | no custom service actions in v1 |
| `dynamic-devices`, `stale-devices` | one config entry is one fixed device |
| `discovery` | the panel runs no mDNS responder: unicast and reflected-multicast browses that its neighbours answer return no record for it; SSDP is a unicast negative; the Espressif OUI makes a MAC-prefix matcher unusable (§4.3, Q28) |

`test-coverage` (silver, > 95 %) is adopted **as reported, not gated**. The yaml comment says so.
`discovery-update-info` is **done**. Everything else is `done`, or `todo` until the release that
ships it.

The rules impose these consequences on the implementer. They are gathered in one place:

- `entity-translations` + `has-entity-name`: names from `translation_key` in `translations/en.json`,
  never `_attr_name` literals. §5.2's Name column is the English string that lands in `en.json`.
- `icon-translations`: `icons.json` keyed by the same translation keys.
- `common-modules`: coordinator in `coordinator.py`, base entity in `entity.py`.
- `runtime-data`: the `HeatitWifiPanelConfigEntry` alias.
- `integration-owner`: `codeowners: ["@Normio"]`.
- `parallel-updates`, `config-entry-unloading`, `unique-config-entry`, `test-before-configure`,
  `test-before-setup`, `entity-event-setup`, `entity-unique-id`, `entity-unavailable`,
  `log-when-unavailable`, `exception-translations`, `inject-websession`, `devices`, `diagnostics`,
  `reconfiguration-flow`, `entity-category`, `entity-device-class`,
  `entity-disabled-by-default`, `appropriate-polling`: all adopted, all evidenced by §9.2's tests or
  by a named module.

### 9.2 What enforces it

`custom_components/heatit_wifi_panel/quality_scale.yaml` is written in hassfest's own schema: all
54 hyphen-slugged keys, with values `done` / `todo` / `exempt`. **`scripts/check_quality_scale.py`**
checks it. The script runs from `test.yml`, so it also gates releases. It fails when:

1. any of the 54 rule keys is missing, or an unknown key is present. The rule list is vendored in
   the script with the core commit it came from. When core adds a rule, the script is updated and
   the yaml gains a `todo`;
2. a `done` or `exempt` entry has no comment;
3. a **`done` comment does not start with a repo-relative path that exists**. The path is a test
   file, a module, or a directory that is the evidence. Free text may follow the path. Any later
   word in that text that starts with a top-level directory of the tree is a path too, and must
   exist as well (amended 2026-09-11, #47). Deleting the test that proved a rule breaks the build
   until the yaml is updated;
4. `manifest.json` carries a `quality_scale` key. **The key is deliberately omitted.** The yaml says
   what we hold ourselves to. The manifest makes no claim that a reviewer never graded;
5. **any rule is `todo` and the version under check is `v1.0.0` or later.** On PRs and 0.x tags,
   the script reports the `todo` count and passes.

The escape hatch is the format itself: `exempt` with a comment.

**Rule tests.** The mechanically checkable rules get a real test, and the yaml's `done` path
points at it:

| Rule | The test asserts |
|---|---|
| `entity-unique-id` | every entity has a unique id of the form `{id}-{key}`, stable across a reload |
| `has-entity-name` | `_attr_has_entity_name` is true on every entity |
| `entity-translations`, `icon-translations` | every `translation_key` resolves in `translations/en.json`, and every key in `icons.json` names a shipping entity. No `_attr_name` or icon literal (amended 2026-09-11, #47) |
| `parallel-updates` | every platform module declares `PARALLEL_UPDATES`: `0` on `sensor` and `binary_sensor`, `1` on the five write platforms |
| `config-entry-unloading` | unload returns true and the client/session hold nothing afterwards |
| `unique-config-entry` | a second entry for the same status `id` aborts |
| `diagnostics` | no unscrubbed `id`, MAC, SSID or IP in **either** the parsed or the raw section. The raw section byte-equals the scrubbed fixture |
| `common-modules` | the `done` path is the module itself. Existence is the check |

### 9.3 Linters

- **ruff**: `select = ["ALL"]` with a **named ignore list** in `pyproject.toml`, one reason per
  entry. `ruff format --check` runs alongside. Per-file ignores are allowed only under `tests/`.
  `RUF100` (unused `noqa`) and `PGH004` (bare `noqa`) are on, so a stale or code-less suppression
  fails. Ruff runs **once**, in its own `test.yml` job. It needs no Home Assistant.
- **mypy**: `strict = true` over `custom_components/` and `scripts/`. It runs **inside each pytest
  row** against that row's Home Assistant. The **floor row blocks**. The latest row is a signal,
  not a blocker. `warn_unused_ignores` is part of strict, so a dead `# type: ignore[code]` fails.
  Ruff `PGH003` rejects a bare `# type: ignore`.
- Both **block a merge**. Both are **pinned exactly** in the floor row's `requirements_test.txt`,
  because a gate must not go red on its own.
- Suppressions are always **specific-code**: `# noqa: CODE`, `# type: ignore[code]`.

`scripts/probe.py`, `scripts/check_conformance.py` and `scripts/capture_fixtures.py` are under the
same ruff and mypy rules as everything else in `scripts/`.

### 9.4 One shared entry point

`scripts/check.sh` holds the exact commands: ruff, ruff format, mypy, both pytest invocations,
`check_quality_scale.py`, `check_conformance.py`. **`test.yml` calls it** instead of listing
commands, so local and CI cannot drift. **No git hooks, no pre-commit framework.** A fresh worktree
without hooks installed is exactly the drift we are designing against. `AGENTS.md` names the entry
point as the step before a push.

---

## 10. Packaging

### 10.1 Fixed values

`hacs.json` contains this and **nothing else**. The schema rejects unknown keys:

```json
{
  "name": "Heatit WiFi Panel",
  "homeassistant": "2026.3.1",
  "hide_default_branch": true
}
```

`hide_default_branch: true` is present **from the first commit of the file**. `zip_release`,
`content_in_root`, `country`, `persistent_directory` and `render_readme` are all unset.

`manifest.json`, with keys sorted `domain`, `name`, then alphabetical:

```json
{
  "domain": "heatit_wifi_panel",
  "name": "Heatit WiFi Panel",
  "codeowners": ["@Normio"],
  "config_flow": true,
  "dhcp": [{ "registered_devices": true }],
  "documentation": "https://github.com/Normio/HeatIt-Wifi-Panel",
  "import_executor": true,
  "integration_type": "device",
  "iot_class": "local_polling",
  "issue_tracker": "https://github.com/Normio/HeatIt-Wifi-Panel/issues",
  "requirements": [],
  "version": "0.1.0"
}
```

No `quality_scale` key (§9.2). No `single_config_entry`, because several panels per instance is
supported. `version` is `vol.Optional` in the schema, but the **loader refuses to load the
integration without it**. It must parse as SemVer here.

> **Assembly note.** `import_executor: true` was recommended by the conventions research (the loader
> warns on every start without it) and was never explicitly ruled on. It is included here on that
> basis; striking it costs one line and one warning.

**The floor is `2026.3.1`, and it is honest.** The only 2026-era mechanism we use is the in-tree
`brand/` icon, which renders on ≥ 2026.3. Nothing on this map uses a newer API. The 2026.8
device-registry rewrite is not used. `runtime_data`, the typed alias, the explicit
`TURN_ON`/`TURN_OFF` flags and `translations/en.json` all predate it. The **patch** number is there
because the floor CI row pins exactly, and no `pytest-homeassistant-custom-component` release pins
2026.3.0. Declaring `2026.3.1` makes the declaration and the enforced row match byte for byte. It
avoids a one-patch gap that nothing tests. Reach at the time of the decision: 82.4 % of reporting
installs. A 2026.8 floor would have halved that to 57.8 % for nothing.

**The floor moves only when a PR needs a newer HA API.** Never for age, never on a schedule, and
never frozen for a line. The pin moves in the same PR. The bump is a `CHANGELOG.md` entry, and it
is at least a minor version. **The floor CI row is the enforcement.** Code that uses an API newer
than the floor goes red there. That is the same check the HACS reviewer performs by reading source.
We keep it running after submission, when no reviewer is watching.

**Brand assets.** `custom_components/heatit_wifi_panel/brand/icon.png` (256×256) and `icon@2x.png`
(512×512), copied from `home-assistant/brands` `core_brands/heatit/`. This is identifying use of
the vendor mark, the same precedent the core Z-Wave brand relies on. **No `logo*`**: the icon is
the logo fallback, and the brands validator rejects a byte-identical logo. No `dark_*`. And
**nowhere else in the repository**. A root `brand/` or a stray `icon.png` is a documented review
comment.

**Licence.** Root `LICENSE`, MIT. GitHub already detects it as `spdx_id: MIT`, which satisfies the
undocumented HACS OSI-licence check. It ships in every release automatically, because HACS
downloads the tag's source archive. The release gate's presence check is a second safeguard.

**The domain string is permanent.** `heatit_wifi_panel` was verified free across core, the brands
repository and the HACS catalog. A duplicate domain is the most common substantive rejection.

**Explicitly not required**, so the implementation does not invent work: release assets /
`zip_release`, `info.md`, the `images` check, `country`, `content_in_root`, `persistent_directory`,
a `hacs` minimum-version key, a `home-assistant/brands` PR, any repository-age requirement.

### 10.2 Releases

Recorded as **[ADR-0002](../adr/0002-tag-push-release-with-gate.md)**.

**Pushing a `vX.Y.Z` tag is the only way a release is created.** The manifest bump and the
changelog section land on `main` through an ordinary reviewed PR first. `release.yml` runs on the
tag. If its gate passes, it creates the GitHub release.

- Tags are `v`-prefixed SemVer. `manifest.json` carries the bare number. `v0.1.0` ↔ `0.1.0`. The
  form is **permanent**, because HACS compares tag strings. There is no `VERSION` constant anywhere
  in the code. `manifest.json` is the single source.
- **0.x are ordinary stable releases** through the hardware-validation window. **`v1.0.0` is cut
  when the `hacs/default` PR opens.** The GitHub pre-release flag is reserved for real betas after
  1.0. An all-pre-release repository has no `last_version` and falls back to the default branch.
  That is exactly what `hide_default_branch` exists to prevent.
- **Only the owner may create `v*` tags** (a GitHub tag ruleset). A failed gate **leaves the bare
  tag**. HACS ignores tags without releases. The owner deletes the tag, bumps, and retags. No
  workflow is ever granted tag deletion.

**The gate.** `release.yml`'s publish job `needs` all of the following, run against the tagged SHA:

1. **HACS Action** and **hassfest**, the same jobs as `validate.yml`, with no `ignore:`.
2. **Both pytest rows** from §8.7, exposed via `workflow_call`, plus the linters and the two check
   scripts. A Home Assistant release that breaks us blocks our own release until it is fixed. That
   is a deliberate choice.
3. A lockstep script that asserts all of the following. Tag minus `v` == manifest `version`. The
   tagged commit is an **ancestor of `main`**. Agent sessions work on side branches in worktrees,
   and a tag pushed from one must never become a release. `LICENSE`, `hacs.json`, `manifest.json`
   and `brand/icon.png` exist in the checkout. `hacs.json` has `hide_default_branch: true` and a
   present, AwesomeVersion-parseable `homeassistant` key. `CHANGELOG.md` contains a non-empty
   `## [X.Y.Z]` section for the tag. That section's body becomes the release notes.

**Changelog.** `CHANGELOG.md` at the root, in **Keep a Changelog** format. **Every PR writes its
entry under `## [Unreleased]`.** A PR check enforces this. It fails when `CHANGELOG.md` is
untouched, unless the PR carries the **`skip-changelog`** label (docs-only, CI-only). The rule is
also stated in `AGENTS.md`. The release PR renames Unreleased to the version with its date and
rewrites the entries into final form. The gate reads the result.

**Validators.** One `validate.yml`, two jobs: `hacs/action@main` with `category: integration` (no
checkout needed), and `actions/checkout` + `home-assistant/actions/hassfest@master`. Triggers:
`push`, `pull_request`, nightly `schedule`, `workflow_dispatch`. `permissions: {}`. **No `ignore:`
anywhere.** They are **unpinned on purpose**. The nightly run exists to catch HACS and hassfest
changing their rules under us. Pinning would make it stop telling the truth. Five checks
(`archived`, `description`, `issues`, `license`, `topics`) carry `allow_fork = False` and skip on
fork PRs. `hacs/default` runs all ten. So **the nightly run is the only truthful signal**, and a
green PR run does not predict the submission.

### 10.3 Repository settings — a human must apply these

Nightly-only HACS checks that no workflow can satisfy:

```
gh repo edit Normio/HeatIt-Wifi-Panel \
  --description "Home Assistant integration for the Heatit WiFi Panel wall heater (local HTTP API)" \
  --add-topic home-assistant --add-topic hacs --add-topic custom-component \
  --add-topic heatit --add-topic heater --add-topic climate
```

plus the **`v*` tag ruleset** (owner-only create) in repository settings. Both are still unapplied.
The session token that agreed the values could not write them. Both are gate item 5 in §11.

---

## 11. Release and submission

### 11.1 Sequencing

- **`v0.1.0` ships when config flow + climate work against the real panel.** The remaining
  platforms arrive as further 0.x releases.
- **The custom-repository URL is never shared before the first release exists.** `can_download`
  has an `if self.data.releases` guard. Because of it, the `homeassistant` floor gate **does not
  exist** for a repository without releases. Users on old installs would be offered an incompatible
  download.

### 11.2 The submission gate

HACS-default-**ready** is the quality bar. **Submission is deferred.** "Not production ready
pending live-device validation" is a documented `hacs/default` rejection, and it describes 0.x
exactly. Opening that PR is also the moment `v1.0.0` is cut. So this gate *is* the 1.0.0 gate.

The `hacs/default` PR opens only when **all** of these are true:

1. The conformance register (§12) has been **executed in full on at least one real panel**. Every
   row is recorded as verified at that firmware. Its write echoes are saved into
   `tests/fixtures/observed/fw-<version>/`.
2. **Every platform has shipped** in a 0.x release. The catalog entry describes the whole
   21-entity surface, not a growing one.
3. **At least one HA monthly release has shipped and been installed on the dev's own instance
   while the complete integration was running there.** That is one cycle of daily use. It gives a
   poll-loop, availability or restart bug a release boundary to show itself across.
4. The nightly `validate.yml` run is green.
5. The repository settings in §10.3 are applied.

Rejected alternatives: submitting on the checklist alone (a catalog entry for a growing
integration); checklist plus platforms with no soak (a slow-burn bug is then found by listed
users); waiting for a second panel or firmware (it does not exist).

### 11.3 The README

- **Facts only, never disclaimers.** The README never says "beta", "alpha", "not production
  ready", "pending validation" or any equivalent, in 0.x or after. That kind of prose caused a real
  `hacs/default` submission to be rejected. The 0.x version number already carries the message.
- A **`## Verified firmware`** section: one table row per firmware, version first, then the unit it
  was verified on (`1.21 | 600 W (maxLoad 6)`). It is updated in the same PR as each new
  `observed/fw-<version>/` directory. CI asserts it against the fixture directories **and**
  `VERIFIED_FIRMWARES`. All three copies of the fact agree, or the build fails.
- A **static DHCP reservation** is recommended (§4.5).
- A **one-line signpost** for owners of the Heatit **WiFi6 thermostat**. It states that this
  integration is for the WiFi Panel wall heater and points them at their own device's integration.
  It is a routing aid, so HACS users searching "heatit" pick the right one. It is **not** an
  acknowledgement. No prior-art credit or licence notice goes with it.
- **Install docs are written in the `v0.1.0` release PR**, not before. They are a My Home Assistant
  redirect link plus the manual add-repository steps (HACS → Custom repositories → URL, category
  *Integration*). **HACS custom repository only.** There is no manual-copy route. That route would
  bypass the floor gate and never see a release. The **`v1.0.0` release PR rewrites** that section
  to plain default-store instructions, because HACS refuses a custom-repository entry for a repo
  already in the default store.

---

## 12. Hardware conformance

**The register is [`docs/conformance/checklist.md`](../conformance/checklist.md).** It is not
reproduced here, and it must not be. It is *living*: a list of open questions that shrinks and a
regression suite that grows. This document is frozen. At the time of writing it holds **58 rows,
41 verified at firmware 1.21, 17 open**.

### 12.1 What a row is

Seven columns: `id | claim | vs spec | tier | status | evidence | dependents`.

- **Ids are the research document's Q-numbers verbatim.** They extend past Q38 for rows raised by
  decision tickets. Those numbers are cited in prose across immutable issue comments. Renumbering
  would break every citation. The cost is a permanently arbitrary, unsorted numbering. That cost is
  accepted.
- **The claim is always what the integration depends on.** It is phrased so it can be proved false.
  It is never what the vendor document says. So a status is truly binary. Nuance ("accepted but
  silently snapped") is written into the claim rather than fudged in a verdict.
- **`vs spec`** is `agrees` / `disagrees` / `silent`. It is the three-claims problem of §0 turned
  into a column. The `disagrees` rows are the most valuable rows in the file. The register's summary
  line says how many there are. Each records a place where a future firmware could quietly revert
  to the documented behaviour.
- **`contradicted` is not `disagrees`.** A `disagrees` row was never true. A `contradicted` row
  *stopped* being true, with shipped code resting on it. The register starts with zero
  contradicted rows. That is why that status is the one that triggers work.
- **`dependents` lists everything a row affects.** So triaging a flipped row means reading one cell
  instead of hunting through this document.

**Measurements are threshold claims that name the constant they justify.** Q31 → the post-write
refresh delay. Q43 → the poll budget. Q30 → the one-request-in-flight lock. Q45 →
`RESET_VERIFY_DELAY`, recorded as the upper bound it is rather than the measurement it is not. A
second panel that misses a bound flips the row and points straight at the constant to retune. A
bare measurements table could never do that. A number with no threshold can never fail.

### 12.2 `scripts/probe.py`

**Specified here, built by the implementing session.** It is standalone: raw HTTP, no import of
the integration. It is **stdlib only**. `http.client` gives the control over protocol version and
headers that the HTTP-hygiene rows need. `socket` covers the backlog and keep-alive rows. A stranger
with a second panel can run it with nothing but Python.

A check registers its **id and tier only**:

```python
@check("Q13", tier=THERMAL)
def eco_regulates_to_eco_setpoint(panel): ...
```

**The claim text is not in the script.** `probe.py` parses the register at runtime and takes the
label it prints from the claim cell. So the sentence exists once. A check that tightens what it
asserts cannot leave the register describing the older, weaker claim.

**Four ascending flags**, matching the register's *probe tiers*:

```
probe.py                 → read tier only, unattended, no approval
probe.py --writes        → + benign writes, snapshotted and restore-verified
probe.py --destructive   → + kWh reset, settings reset          (y/N)
probe.py --thermal       → + heater-on sequences                (y/N, TTY required)
```

Selection is `--check Q13 Q29` or `--group write`. The default run is every `read`-tier check.

- `--thermal` also requires `sys.stdin.isatty()` and the same y/N answer as `--destructive`. So
  **no CI job, cron or background run can ever turn a heater on in someone's bedroom**. A thermal
  check also refuses to raise a setpoint more than 2 °C above the current room temperature. It caps
  how long it may leave the relay closed.
- **`/api/reset/factory` is structurally absent.** The string appears nowhere in the source, and
  `tests/test_probe_safety.py` asserts that by reading the file. It is not a flag that could be
  passed by accident.

**The revert contract.** It does not trust the echo, because this panel lies in its echo:

1. Before the first write of a run, snapshot the full status to `.local/probe-snapshot-<ts>.json`.
2. Every parameter a check touches is registered for restore.
3. An exit hook restores them and then **re-reads the status to verify**. The hook runs on normal
   return, exception, `SIGINT` and `SIGTERM`.
4. A failed or unverified restore prints a banner naming the parameter, its original value and the
   exact `curl` to fix it by hand. It then exits non-zero.
5. `--restore <file>` replays a snapshot as a standalone command. It is the backstop for a run that
   died too hard for any hook to fire (`kill -9`, a sleeping laptop, a crash inside the hook). Those
   are exactly the cases where a 600 W heater is left running.

**Output** is a Markdown result table to stdout that pastes into an issue, plus a fixtures block
and a measurements block. Results are `PASS` / `FAIL` / `INCONCLUSIVE` / `SKIPPED (tier not
enabled)`. `INCONCLUSIVE` is a first-class result. **A human transcribes results into the register,
deliberately. No machine marks a claim verified.**

**Fixtures.** When run with writes enabled, the probe saves each **write and reset** response as
raw bytes into `tests/fixtures/observed/fw-<version>/`. These replace the transcribed ones (§8.3).
It saves **no status captures**. It imports nothing from the integration, so it cannot use the
shared redaction function. A second copy of a redaction function is a leak waiting to happen. It
does not need one. A write echo is `{"status":"Success","heatingSetpoint":19.0}` and carries none of
the five scrubbed fields. So instead it **asserts fail-closed** that no scrub key appears in the
response bytes. It refuses to write the file if one does. Status captures stay
`capture_fixtures.py`'s job, where the real scrub lives.

**Exit codes**: `0` all selected checks passed · `1` a check failed, i.e. a contradiction · `2` a
revert failed, the loud one · `3` usage or connectivity.

### 12.3 Manual rows and their procedures

Twelve rows are `manual` tier. No script may run them. Most are rows a single 600 W unit at
firmware 1.21 can **never** close: a factory reset, a 1500 W unit, a paired external sensor, a
firmware carrying low temperature protection, a host on the panel's own VLAN. The people who close
them are strangers with other hardware. So the register's appendix carries **nine numbered
procedures (P-1…P-9)** with preconditions, steps, what to record and where to send it. That
appendix is the contributor-facing half of the document.

### 12.4 CI enforces the register

`scripts/check_conformance.py` runs from `test.yml` beside `check_quality_scale.py`, and from
§9.4's shared entry point. It fails when:

1. an id is duplicated or malformed, a row has the wrong column count, or `vs spec` / `tier` /
   `status` is outside its vocabulary;
2. a `verified` or `contradicted` row names a firmware that is not in `VERIFIED_FIRMWARES`, or a
   unit that is not in the script's `KNOWN_UNITS`, or a unit twice;
3. a non-`open` row has no evidence, or an evidence entry does not resolve. An entry resolves when
   it is a repo path that exists, an issue or PR link, or a `P-n` defined in the appendix;
4. a dependents cell carries no resolvable reference of those same kinds. Prose may sit alongside
   the reference, and it does. During the spec era, that reference is an ADR or an issue. After
   implementation, it becomes a module path, updated by the PR that renames it. This is the same
   discipline §9.2 puts on quality-scale `done` comments;
5. an `open` `manual` row cites no procedure, or an appendix procedure is cited by no row;
6. **the set of non-`manual` ids in the register is not exactly the set registered in `probe.py`**.
   That is the one place the two can silently diverge;
7. the summary line under the table is missing, or any of its figures (verified at the named
   firmware, how many of those on each unit, `open`, `disagrees`) is not what the table counts. The line stays hand-written prose.
   Its one bold sentence is the form the check reads, and the script's docstring holds that form.

The escape hatch is the vocabulary itself: `manual` tier and `open` status ask for nothing.

### 12.5 When a claim is contradicted

Four contradictions have already happened. Each surfaced *inside a live decision ticket*, so no
process was needed. That mechanism ends when this document is assembled. The next contradiction
lands against a frozen spec with shipped code on it.

1. The row flips to `contradicted fw <v> on <unit>`, citing the run.
2. An issue labelled `conformance` opens, naming the row. Its **dependents** cell is the triage.
3. **One PR** carries the spec amendment (§15), the code change, the new fixture and the row
   restored to `verified fw <v> on <units>`. It closes the issue.

**The spec gains an amendment rather than being rewritten.** So the v1 document still reads as
what v1 claimed, with its corrections appended and dated.

---

## 13. Open questions carried forward

None of these blocks the build. Each is written down so an implementer meets it as a known unknown
rather than a surprise.

1. **Seventeen open register rows**, listed in the register with their tiers and procedures. The
   ones most likely to touch code: **Q17** (can `loadLimit` exceed `maxLoad`? §5.2 makes the load
   limit's maximum `maxLoad × 100`. That is a design choice the vendor document does not license);
   **Q4** (multi-parameter atomicity, the reason for one parameter per request); **Q52** (does the
   *device id* survive a factory reset or a firmware update? That is the one identity claim
   ADR-0003 rests on); **Q23** (does `sensorCalibration` shift `roomTemperature`, or only the
   display?); **Q47** (does `OWD.activeTime` count down?).
2. **On-segment discovery.** Register row Q28 / procedure P-2, tracked as its own issue. It is
   blocked on network access, not on a decision. It explicitly does **not** gate v1. The manifest
   ships `dhcp: [{"registered_devices": true}]` either way. If it ever turns up an advertisement,
   it amends this spec and flips `discovery` from `exempt` to `done`. *Closed for mDNS on
   2026-09-11, see §15. SSDP on-segment and the DHCP hostname remain P-2's open steps.*
3. **The runtime response to firmware drift.** The *detection* half is settled. Every claim sits in
   the register with the firmware it was verified at. A second firmware that disagrees flips a row
   to `contradicted`, and the dependents cell names what breaks. The *posture* half is settled too:
   observed parameters only, a new fixture directory per panel or firmware, a parse-only sweep,
   dropped-parameter tolerance tested per observed parameter, an info line at setup for an
   unverified firmware, and a vanished parameter making its entity unavailable. What is **not**
   settled is what the integration should *do at runtime* when a second observed firmware behaves
   differently from the first. Examples: the 0.5/0.1 split, the snap-versus-reject asymmetry, the
   echo. Whether to gate by firmware, warn, or ignore cannot be answered with one firmware, and
   there is exactly one. This question is resolved the day a second panel appears.
4. **The `import_executor` assembly note** in §10.1.
5. **The two unobserved parameters.** `externalSensorFallback` and `lowTemperatureProtection`
   return to the registry and the entity table only with a captured fixture that contains them
   (register Q48, Q49; procedures P-6, P-7). Three entity rows come back with them: a number and an
   enum sensor for low temperature protection, and an external-sensor-fallback switch. The *low
   temperature protection* glossary entry's warning applies. Its wire name means both a threshold
   and a live state, and the two must never share a name.

---

## 14. Decision records

| ADR | Decision |
|---|---|
| [0001](../adr/0001-no-fork-of-heatit-wifi6.md) | The prior-art integration for the related Heatit WiFi6 thermostat is **ignored**: not forked, not copied, not credited. The integration is written from the vendor document and the observed panel. |
| [0002](../adr/0002-tag-push-release-with-gate.md) | A `vX.Y.Z` **tag push is the only release trigger**, behind a gate that fails closed (§10.2). |
| [0003](../adr/0003-device-id-as-unique-id.md) | The panel's **device id, not its MAC, is the Home Assistant unique id** (§4.1). |
| [0004](../adr/0004-eco-as-a-climate-preset.md) | **Eco is a climate preset**, with both *setpoint banks* also exposed as config numbers. It is not a second target temperature (§5.3). |

---

## 15. Amendments

Corrections to this document after v1 was frozen. Each entry names the register row or issue that
forced it, and the PR that carried it.

**2026-09-14 — register rows Q16, Q49, Q51 and Q52 are retired** (§11.2).
§11.2's first gate item asks for every register row verified. Four rows can never be, because each
needs a firmware other than 1.21. Heatit has shipped none and may never ship one.

- Q16 and Q49 ask about `lowTemperatureProtection`, a parameter 1.21 does not return.
- Q51 asks whether the setpoint and calibration grids hold on another firmware.
- Q52 asks whether the device `id` survives a factory reset **and** a firmware update.

The rows and their procedures, P-1, P-7 and P-9, leave the register. Their ids are never reused.
§12's "P-1…P-9" now runs P-2…P-8. Q19's claim drops its low temperature protection half and keeps
the open window override, which a 1.21 panel can show.

What the rows tracked stays true. §2.4 still treats `lowTemperatureProtection` as unobserved, and
§13 item 5's entities still come back only with a captured fixture. A panel that starts returning
the parameter shows it in the raw status bytes of its diagnostics download. §4.1 and §13 still
call the id's survival untested, and it still is. The MAC in `DeviceInfo.connections` stays the
migration path if a firmware ever changes the id. A new firmware opens new rows, not these.

**2026-09-13 — a status names the units a row was shown on** ([#89](https://github.com/Normio/HeatIt-Wifi-Panel/issues/89), [PR #90](https://github.com/Normio/HeatIt-Wifi-Panel/pull/90)).
§12.1 and §12.4 read a status as `verified fw <v>`, one firmware and nothing about which panel.
With two units run through every tier, "verified" no longer said on what. A status is now
`verified fw <v> on <units>`, the units named by wattage and comma-separated, and
`check_conformance.py` holds each one to its `KNOWN_UNITS` and holds the summary line's per-unit
counts to the table (conditions 2 and 7). The 46 automated rows are on both units. Q28's browse in
#32 was of the 600 W unit, and Q50 needs a `maxLoad` other than 6, so it is 1000 W only. Q13 and
Q34 are set on the 1000 W unit from #89's run: the sequence that served Q20 there closed the relay
3 s after entering Eco, which is what Q13 asserts, and the 5.2 s settle sits inside the ~8 s bound
the entry below adopts.

**2026-09-13 — Q34's settle is "~8 s", not "~5 s"; `--thermal` needs no typed phrase** ([#89](https://github.com/Normio/HeatIt-Wifi-Panel/issues/89), [PR #90](https://github.com/Normio/HeatIt-Wifi-Panel/pull/90)).
§5.2 and §10's button row said a settings reset "applies staggered over ~5 s", and the probe held
Q34 to a strict 5.0 s. #74 called that a knife edge after the 600 W unit settled at exactly 5.0 s
over 12 parameters. On the first full run of every tier on both units the 1000 W unit settled at
**5.2 s** over the same 12, and the row read FAIL. Nothing in the integration waits 5 s for a
reset; §10 already sends the reader to a later poll. So the claim and the bound now say "~8 s",
which the same two measurements (4.6 s and 5.2 s) sit inside with room, and Q34 stays
`verified fw 1.21` on #89's run. In the same pass §12.2 drops the typed phrase `--thermal` asked
for on top of the flag. A stray character in it cost Q13 its verdict on the 1000 W unit while the
sequence it names ran for Q20 anyway. The flag is the consent; one y/N, shared with
`--destructive`, is the last look at which panel it lands on, and a no drops both tiers.

**2026-09-12 — §3.4 had `config_entry=` both ignored and wired; the register's summary line is CI-checked** ([#79](https://github.com/Normio/HeatIt-Wifi-Panel/issues/79), [PR #83](https://github.com/Normio/HeatIt-Wifi-Panel/pull/83)).
§3.4 said the coordinator's `config_entry=` argument "is ignored for custom integrations" and, in
the same sentence, that it wires the shutdown on unload and honours `pref_disable_polling`. Both
could not be true, and the first was wrong. Core only leaves the *omission* unenforced for custom
integrations. Passing the entry always registers `async_shutdown` on unload and always honours the
polling toggle, as `docs/research/ha-integration-conventions.md` §2 says. The coordinator passes
it, and does not change. §3.4 now says that one thing. In the same pass, §0 and §12.1 stop naming
how many register rows are `disagrees`. The figure had drifted from ten to twelve without either
sentence noticing. Both now send the reader to the register, whose summary line carries the count.
§12.4 gains condition 7: `check_conformance.py` holds that line's three figures to the table.

**2026-09-11 — §4.3's mDNS negative is hard, not soft** ([#32](https://github.com/Normio/HeatIt-Wifi-Panel/issues/32), PR pending).
§4.3 called both discovery negatives soft, because link-local multicast could not cross the VLAN
boundary. The site router turned out to reflect mDNS. A reflected browse is a real measurement once
the panel's own-segment neighbours are seen answering in it. They did, within 100 ms, across 75 s
and seven service types plus the reverse lookup of the panel's address. The panel answered nothing.
Q28 flips to `verified fw 1.21`. §4.3 and the `discovery` exemption row now say the panel runs no
mDNS responder, rather than that the question was untestable. §13's item 2 notes what is still
open. SSDP was not shown to reflect, so its negative stays unicast-only. The DHCP lease hostname is
unread. Nothing in the manifest or the config flow changes. `discovery` stays `exempt`, now on
evidence instead of an excuse.

**2026-09-11 — §4.4's `room` only picks an area, it never creates one** (PR pending).
§4.4 said "a non-empty `room` becomes `suggested_area`" and took that to be a suggestion. It is
not. Core resolves `suggested_area` through `area_registry.async_get_or_create`. So a room naming
no existing area had one *created*. The panel was silently writing to a registry that belongs to
the user. As shipped in 0.1.0, adding a panel whose MyHeatit room was `Bedroom` made a `Bedroom`
area. §4.4 now matches the room against the existing areas and drops it when nothing matches. The
paragraph there records why. The unmatched case is the one Home Assistant already handles by
offering its area picker.

**2026-09-09 — `scripts/check_layout.py` joins §3.1 and §9.4** ([#36](https://github.com/Normio/HeatIt-Wifi-Panel/issues/36), PR #49).
Three of #36's acceptance criteria have no upstream enforcer: no `strings.json` anywhere, brand
assets nowhere else in the repository, and `hacs.json` holding exactly three keys. hassfest
validates `strings.json` only when the file exists. The HACS Action never looks past `hacs.json`
and the manifest. So §3.1's `scripts/` listing gains `check_layout.py`, and §9.4's command list
gains one line. The script also asserts §10.1's fixed manifest keys and their order, and that no
`quality_scale` key is present. **§9.2's failure condition 4 moves to `check_quality_scale.py` when
that script lands ([#47](https://github.com/Normio/HeatIt-Wifi-Panel/issues/47)). It
does not live in both.**

**2026-09-09 — `config_flow.py` ships with the scaffold** ([#36](https://github.com/Normio/HeatIt-Wifi-Panel/issues/36), PR #49).
§3.1 lists it, but #36 named only `manifest.json` and `__init__.py`. hassfest *errors*, not
warns, when a manifest declares `config_flow: true` and the file is absent. This holds for custom
integrations. So the scaffold ships a `ConfigFlow` subclass with no steps.
[#40](https://github.com/Normio/HeatIt-Wifi-Panel/issues/40) fills it in. `const.py` is
present for the same reason, holding `DOMAIN` alone.

**2026-09-09 — §9.3's "ruff runs once, in its own `test.yml` job" is deferred, not dropped** ([#36](https://github.com/Normio/HeatIt-Wifi-Panel/issues/36), PR #49).
§9.4's "`test.yml` calls `scripts/check.sh`" was taken as the binding half. Until §8.7's rows
exist, there is nothing to matrix over. So one job runs the whole script.
[#38](https://github.com/Normio/HeatIt-Wifi-Panel/issues/38) adds the two rows and splits
ruff back out, so it does not run once per row.

**2026-09-09 — `--destructive` also requires a terminal** ([#37](https://github.com/Normio/HeatIt-Wifi-Panel/issues/37)).
§12.2 reserves the `isatty()` requirement for `--thermal`. But a settings reset lands the panel at
its documented defaults, comfort 21 °C in Heating mode, for the seconds until the restore. So on a
cold day, `yes | probe.py --destructive` from a cron would close the relay. Both hazardous tiers
now refuse a non-interactive stdin. The y/N prompt stays for `--destructive`. The typed
confirmation naming the check stays for `--thermal`. Register row Q18 also moves from the `read`
to the `write` tier in the same PR. Its evidence required writing `panelMode=0`, which no
read-tier check may do.

**2026-09-09 — required status checks join §10.3's human-applied list** ([#36](https://github.com/Normio/HeatIt-Wifi-Panel/issues/36), PR #49).
§9.3 says both linters "block a merge". §10.3 lists what a workflow cannot apply. Branch
protection was named in neither. `Checks`, `HACS Action`, `hassfest` and `Changelog entry` must be
marked required on `main` by the owner. Nothing in the repository can assert that they are.

**2026-09-09 — the client ticket refines §3.2, §8.5 and §8.7** ([#38](https://github.com/Normio/HeatIt-Wifi-Panel/issues/38)).
Three refinements came out of implementation. (1) §2.4's "quantise" and §8.5's "an off-step value
raises locally" are reconciled as follows. A value within float noise of a grid point *is* that
grid point (``0.1 * 3`` is ``0.3``). Anything further off the grid raises a local ``ValueError``
with no request emitted. The client never rounds a user's value into a different one. (2) §3.2's
exception list gains ``HeatitMissingFieldError``, a subclass of ``HeatitProtocolError``. It
carries the dotted path of the absent *required core* field, because §6.3's ``missing_field``
translation key needs the path and the coordinator must not re-parse. ``HeatitParameterRejected``
is raised for a ``400`` **and** for a ``200`` whose envelope is not success. A refusal is a
refusal, and both carry ``reason`` verbatim. The same ``failed`` envelope on a reset is a
``HeatitResponseError`` with ``status_code`` 200 and the ``reason``. (3) §8.7's matrix lands with
the client rather than with the integration tests. So `test.yml`'s single `Checks` job becomes
`Lint`, `Tests (floor)` and `Tests (latest)`. The required status checks named in the amendment of
PR #49 are now `Lint`, `Tests (floor)`, `HACS Action`, `hassfest` and `Changelog entry`.
`scripts/check.sh` takes a `lint` or `test` stage, so CI still runs the one shared file. The
monthly cron runs both rows rather than the latest row alone, since the floor row is free and
confirms the pin still installs. §8.7's `config_flow.py` coverage gate joins `check.sh` with the
config flow ([#40](https://github.com/Normio/HeatIt-Wifi-Panel/issues/40)), because there
is no `config_flow.py` to cover yet. The shared redaction of §7.1 lives in `api.py` beside the
parser it scrubs for. The fixture-only fifth placeholder for `name` (§8.3) is applied by
`scripts/capture_fixtures.py` alone. Logging and diagnostics keep `name`.

**2026-09-09 — the lockstep script is `scripts/check_release.py`, and joins §3.1** ([#39](https://github.com/Normio/HeatIt-Wifi-Panel/issues/39), PR #50).
§10.2 describes the gate's third member without naming it. It is `scripts/check_release.py`. Only
`release.yml` runs it. It needs a pushed tag, so it is the one script §9.4's entry point does not
run. It writes the changelog section the publish job uses as the release body. Its tests live
under `tests/scripts/`, a directory §8.7's layout did not list. `pytest` and mypy strict over
`tests/` arrived with [#38](https://github.com/Normio/HeatIt-Wifi-Panel/issues/38) and
cover them unchanged.

**2026-09-09 — the gate calls `test.yml` whole, so §8.7's rows join it when they land** ([#39](https://github.com/Normio/HeatIt-Wifi-Panel/issues/39), PR #50).
§10.2 says the publish job needs "both pytest rows from §8.7, exposed via `workflow_call`". The
rows did not exist when this was written
([#38](https://github.com/Normio/HeatIt-Wifi-Panel/issues/38) added them). So
`release.yml` calls `test.yml` and `validate.yml` as reusable workflows rather than naming jobs.
Whatever either file holds is what a release must pass. #38 indeed changed nothing in
`release.yml`.

**2026-09-09 — §10.3's settings are applied, and `docs/releasing.md` records them** ([#39](https://github.com/Normio/HeatIt-Wifi-Panel/issues/39), PR #50).
§10.3 says the description, topics and the `v*` tag ruleset "are still unapplied". As of this
date, all three are applied, and so is the `main` ruleset with the required status checks from the
amendment above. They were verified through the API. `docs/releasing.md` holds the procedure, the
gate, the commands and the ruleset shapes, so the owner can check or restore them. §11.2's gate
item 5 reads from there.

**2026-09-10 — §8.7's `latest` row blocks a release, though it still never blocks a merge** ([#38](https://github.com/Normio/HeatIt-Wifi-Panel/issues/38), [#39](https://github.com/Normio/HeatIt-Wifi-Panel/issues/39), PR #50).
§8.7 makes the `latest` row a signal rather than a blocker. §10.2 makes **both** pytest rows part
of the release gate. Merging #38 and #39 put those two rules in direct contact, because a
`continue-on-error` job in a called workflow fails without failing its caller. Both rules hold,
split by ref. `test.yml`'s row carries
`continue-on-error: ${{ matrix.row == 'latest' && !startsWith(github.ref, 'refs/tags/') }}`. That
is advisory on pull requests and the monthly cron, and blocking on a tag, where `release.yml` is
the caller and `github.ref` is the pushed tag. So `tests/scripts/test_release_gate.py` accepts any
`continue-on-error` carrying that guard as a top-level `&&` conjunct. It rejects everything else,
including a bare literal and any expression containing `||`. The required status checks are
unchanged. `Tests (latest)` is still not one of them.

**2026-09-10 — the README's contract is wider than §11.3, and CI holds all of it** ([#48](https://github.com/Normio/HeatIt-Wifi-Panel/issues/48)).
§11.3 names four README facts, and §8.5 asserts one of them, *three-way firmware consistency*.
Meeting the HACS default checklist's "substantive docs: setup, entities, services, limitations —
not two lines" needed three more. Each is asserted rather than trusted, in `tests/test_readme.py`:

- an **`## Entities`** table listing exactly the entities the platform modules declare. The list
  is read from their entity descriptions and from the class-level `_attr_translation_key` the
  climate entity names itself with (§5.2 makes that string the unique-id suffix too). **A platform
  ships its README rows in the same pull request as its module**, just as a new firmware ships its
  table row.
  [#41](https://github.com/Normio/HeatIt-Wifi-Panel/issues/41)–[#47](https://github.com/Normio/HeatIt-Wifi-Panel/issues/47)
  each carry theirs. While no platform ships, the section is absent. That is why this ticket's
  README has none;
- the stated Home Assistant floor equals `hacs.json`'s `homeassistant`, the version HACS refuses a
  download below;
- §11.3's disclaimer ban and [ADR-0001](../adr/0001-no-fork-of-heatit-wifi6.md)'s WiFi6 signpost
  are scanned for, rather than left to a reviewer's eye. The signpost is checked for the prior-art
  credit and licence notice the ADR refused.

This is deliberately more than §8.6 licenses as coverage. A README fact with a machine-readable
owner elsewhere in the tree is a *third copy*. The register's own discipline, all copies of a fact
or none, applies to it. Facts with no such owner (the prose, the network guidance) stay unasserted.

**§11.3's "install docs are written in the `v0.1.0` release PR, not before" gains both halves.**
Offline, the README may carry an `## Installation` section only once `CHANGELOG.md` holds a
released version section. The release pull request writes both, so before it there is neither.
That enforces §11.1's rule that the custom-repository URL is never shared before a release exists,
instead of leaving it to memory. On a tag, `scripts/check_release.py` refuses four kinds of
release: one whose README has no such section, one below `1.0.0` that does not name HACS's
*Custom repositories* dialog, one from `1.0.0` on that still does, and one at **any** version
offering a manual copy into `custom_components/`. `README.md` joins §10.2's required files, which
HACS's own `information` check already assumed. `docs/releasing.md` carries the runbook half, on
the release pull request's checklist.

**2026-09-10 — §11.3's WiFi6 signpost is withdrawn** ([#48](https://github.com/Normio/HeatIt-Wifi-Panel/issues/48)).
§11.3 requires "a **one-line signpost** for owners of the Heatit **WiFi6 thermostat** … so HACS
users searching \"heatit\" pick the right one". [ADR-0001](../adr/0001-no-fork-of-heatit-wifi6.md)
lists carrying it among that decision's consequences. The owner has withdrawn it. **The README
names no other device.** The assertion that enforced its shape goes with it. That assertion checked
for one line, naming the WiFi Panel, carrying none of the credit or licence words the ADR refused.
ADR-0001's consequence is struck through rather than deleted, so the reversal is readable next to
what it reverses.

Nothing else in that decision moves. The signpost was a *routing aid, not an acknowledgement*.
Dropping it is not an acknowledgement either. Coexistence with the other integration was settled
by the distinct domain `heatit_wifi_panel`, never by this line. The prior-art audit, the handoff
brief and the register rows that cite the other device as **evidence** are records of what was
investigated. They are not claims this integration makes. They stand unchanged.

**2026-09-10 — the config flow and coordinator ticket refines §3.4, §3.5, §4.3, §4.6 and §6.2** ([#40](https://github.com/Normio/HeatIt-Wifi-Panel/issues/40)).
Five refinements. (1) §3.4's `entry.add_update_listener(_async_update_listener)` and §4.6's
"applied by update listener → `async_reload`" are replaced by **`OptionsFlowWithReload`**. That
class reloads the entry itself when the options change. Home Assistant's own documentation now
says so: "since the most common reason to add an update listener is to reload the integration when
the options have changed, `OptionsFlowWithReload` avoids the need for that listener". The class
docstring forbids combining the two: "it's not allowed to use this class if the integration uses
config entry update listeners". The observable contract is unchanged. An option change reloads the
entry, `update_interval` is never changed in place, and all the panel's entities go briefly
unavailable. (2) §3.5 builds `DeviceInfo` on the base entity. But this ticket ships **no
platforms**, and its acceptance criteria require a device with zero entities. So the device is
registered in `__init__.py` from the first status, immediately after `runtime_data` is assigned.
`entity.py` ([#41](https://github.com/Normio/HeatIt-Wifi-Panel/issues/41)) needs only
`identifiers` to attach to it. The values, and the absent `configuration_url`, are §3.5's,
unchanged. §4.4's "read at creation only" is taken literally for both fields it names. The registry
honours `suggested_area` when it makes the device and ignores it afterwards. `name` is passed only
on the setup that creates the device. A later setup withholds it, so an app rename diverges rather
than overwriting the device name on the next reload. `model` and `sw_version` are refreshed every
setup instead. They are facts about the hardware, not labels the user owns. That is how §3.5 has a
firmware change picked up on reload. The entry title is read once, in the flow. (3) `PLATFORMS`
starts **empty**, and each platform ticket appends to it. §3.4's seven-entry list is the end state,
not the state at this ticket. Forwarding to a module that does not exist yet would fail setup.
(4) §4.3's `async_step_dhcp` lists three outcomes and a quiet abort. A fourth exists in code: a
panel answering at the discovered address whose *device id* matches no entry. `registered_devices`
should make it unreachable. But `_abort_if_unique_id_configured` returns rather than raising in
that case. So it aborts with `not_configured` and is tested directly, because this module is held
at 100 % line coverage. The gate itself was deferred by the amendment of PR #50. It now lives in
`scripts/check.sh` as `coverage report --fail-under=100 --include='*/config_flow.py'`. (5) §6.2's
table gives the setup-time *foreign panel* as `ConfigEntryError`. Its following paragraph gave the
poll-time one as `UpdateFailed`. But that paragraph then describes what a `ConfigEntryError` from a
scheduled refresh already does. The coordinator catches it, logs one error line and fails the poll
without escalating (`update_coordinator.py`'s `except ConfigEntryError` branch). The sentence is
corrected to `ConfigEntryError`. The coordinator raises it at both moments from one site. The
translation key, the placeholders and everything the user sees are unchanged. The alternative was
a `config_entry.state` check whose only effect would have been the wording of a core log line.

**2026-09-10 — §7.3's `entry_data` is redacted by key, not by the shared redaction** ([#46](https://github.com/Normio/HeatIt-Wifi-Panel/issues/46)).
§7.3 sends `entry_data` and `options` "through the shared redaction". But §7.1's function scrubs
four dotted paths *of a status*, and `entry.data` holds `host` alone, which none of them names.
Applied there it scrubs nothing. The download would then carry the user's local address in the one
field that is only ever that address. So `entry_data` goes through
`async_redact_data(entry.data, {CONF_HOST})`, the key-based helper the platform provides for
exactly this, and reads `**REDACTED**`. The host is hidden for the same reason §7.1 hides
`Network.ipAddress`. It is the same address by another name. §7.3's own next sentence already
reserves the shared scrub for the `raw` section, where a key-based helper can do nothing.
`options` needs neither. The *poll interval* is a number the user chose.

**2026-09-10 — the retained retry flag means the retry was *used*, not that it *worked*** ([#46](https://github.com/Normio/HeatIt-Wifi-Panel/issues/46)).
§3.2's retained state was written for §7.2's debug line, which fires only when a second attempt
succeeds. §7.3's `last_poll` asks "whether the retry was used". The poll a user reports is usually
the one where both attempts failed. The flag is now set when the second attempt is *made*. So a
`cannot_connect` poll reports `retried: true`. The debug line's cadence is unchanged. The record
itself (outcome, duration and that flag) is a frozen `PollRecord`. The coordinator writes it on
the way out of every poll, good or bad. So the download describes the poll that just happened,
not the last one that happened to succeed. Its `outcome` is the poll's own translation key
(`cannot_connect`, `missing_field`, `invalid_response`, `foreign_panel`), or `ok`.

**2026-09-10 — §7.3's raw *headers* are scrubbed by value, and the download names the poll interval** ([#46](https://github.com/Normio/HeatIt-Wifi-Panel/issues/46)).
Two refinements the download itself forced. (1) §7.3 sends body *and headers* "through the same
wire-level scrub". But that scrub is a substitution on `"key": "value"` JSON pairs. A header is
neither JSON nor keyed by anything it carries. Applied to one, the scrub does nothing.
`redact_text` is the third face of the one redaction. Same four fields, same placeholders. But the
value to look for is read out of the status the panel just returned, and it is replaced wherever
it occurs in the header value. It can only over-scrub, which at the wire is the documented
direction. The observed firmware sends `Content-Type` and `Content-Length` alone. That is exactly
why this is not left to the observation. The section exists to carry what *this* firmware does
that no fixture covers. `scripts/capture_fixtures.py` still writes headers verbatim. It captures
from a panel the developer owns, into a file they read before committing. (2) §7.3's `entry_data`
and `options` gloss reads "(host, poll interval)". But `ConfigEntry.options` is empty until the
user opens the options flow. So a default download named no interval at all. `options` stays the
stored options, the truth about the entry. `poll_interval_seconds` beside it is the interval in
force. Both are needed. A bug report needs the effective number, and a reviewer needs to know
whether the user ever chose it.

**2026-09-11 — the climate ticket refines §3.5, §5.3, §6.4 and §6.5** ([#41](https://github.com/Normio/HeatIt-Wifi-Panel/issues/41)).
Four refinements. (1) §3.5 requires every platform's entities to carry a frozen entity
description with `value_fn` / `set_value_fn`. **The climate entity carries none.** It is the whole
of its platform. `_attr_name = None` marks it the main feature. A description holding one entity's
key would be a table of one. It names itself with a class-level `_attr_translation_key`. §5.2
makes that its unique-id suffix too, and `tests/test_readme.py` already reads it out of there. The
rule stands for the five description-driven platforms. `entity.py` takes the key as an argument,
so both shapes reach one base. Reading and writing go through the coordinator's `parameter()` and
`async_write_parameter()`. That is where the *write echo* and the *silent undo* have to live
anyway: one per panel, not one per entity. (2) §5.3 has `min_temp` / `max_temp` come "from the
device's limits". But both *temperature limits* are **optional parameters** under §5.4's
presence-gating. A firmware returning neither still has a thermostat. In that case they report the
registry's own bounds on a *setpoint bank*, 5.0 and 40.0. Those are the two numbers every setpoint
write is already validated against, so the card offers exactly what the panel will accept.
`registry.py` names them, rather than `climate.py` repeating them. (3) §6.4's table gains a row. A
**local `ValueError` from the registry** becomes `HomeAssistantError` with the key `invalid_value`,
carrying the message verbatim. §6.4 says *all* write errors are translated, and this one is
reachable. Core validates a `climate.set_temperature` against `min_temp` and `max_temp` and
**never** against `target_temperature_step`. So an off-grid value arrives as written, and the
client refuses it before a request exists (the amendment of #38). A Fahrenheit user meets this on
most calls, because 70 °F is 21.11 °C. That is §8.5's client-side quantisation rule working as
specified. Whether the entity should snap to the grid instead is left open rather than decided
here. (4) §6.5's "**post-write** refresh" is pinned to §5.5's rule for the energy reset. It is the
same question asked twice. The first status that completes `POST_WRITE_REFRESH_DELAY` or later
after the acknowledgement is the one that judges an echo. An earlier one leaves it pending.
Without that rule, a scheduled poll landing inside the 1.5 s a write needs to reach the status
would report a *silent undo* that never happened. And `DataUpdateCoordinator` cancels the
debounced refresh when a scheduled poll runs, so no later refresh would correct it before the next
*poll interval*.

**2026-09-11 — the switch and select platforms refine §3.5** ([#43](https://github.com/Normio/HeatIt-Wifi-Panel/issues/43)).
§3.5 has every entity description carry `value_fn` / `set_value_fn` callables. The amendment of
[#41](https://github.com/Normio/HeatIt-Wifi-Panel/issues/41) let the climate entity out
of descriptions altogether, while holding the rule for "the five description-driven platforms".
The two platforms that landed here are description-driven and carry **no callables**.
`HeatitSwitchDescription` holds the parameter's wire name. `HeatitSelectDescription` holds that
plus the option names and the device value behind each. A `value_fn` here could only be
`lambda c: c.parameter("sensorMode")`, the same call with the same argument the description already
names. A `set_value_fn` could only be the matching `async_write_parameter`. So the pair would
restate the wire name twice more per entity, and give a reviewer three places to check that a
switch writes what it reads. §3.5's point is that the *table* holds what varies between entities,
rather than a class per entity. A description naming one registry parameter holds exactly that.
The callables stay for a platform whose reading is **not** one parameter. `sensor.py` and
`binary_sensor.py`, merged alongside this from
[#44](https://github.com/Normio/HeatIt-Wifi-Panel/issues/44), carry a `read_path` and a
`value_fn` for exactly that reason. Their rows read top-level *status* fields the registry holds
no descriptor for, and the signal strength needs a parse rather than a lookup. So the rule is
**narrowed to "where the value is not one *observed parameter*"** rather than dropped. The two
shapes are the two halves of §5.2's table: what the panel accepts a write for, and what it only
reports. Every parameter-backed platform does share one binding: the registry lookup that turns a
wire name into a read path. That moves to a second base class in `entity.py`,
`HeatitParameterEntity`. So §3.5's "a base `CoordinatorEntity` supplying `DeviceInfo` and the
availability rule" now describes two classes: that one, and the parameter binding on top of it.

**2026-09-11 — the number ticket refines §3.5, §5.2 and §5.3** ([#42](https://github.com/Normio/HeatIt-Wifi-Panel/issues/42)).
Three refinements, on top of #43's narrowing of §3.5 above. `number.py` sits inside that
narrowing. A number *is* one *observed parameter*, so `HeatitNumberDescription` holds that
parameter's wire name and no `value_fn`. (1) It does carry two callables. The narrowing does not
cover them, because they are not the value. `minimum_fn` / `maximum_fn` are the half of §5.2
marked **dynamic**, answered from coordinator data on every access. So the rule takes this shape:
**the value of a parameter-backed entity is a lookup, never a callable. Anything about that value
that moves with device state is a callable, because nothing else can be read fresh.** Ten of the
sixteen bounds in the eight rows do not move, and those are the registry's. (2) §5.2 bounds the
*load limit* at `maxLoad × 100`. It does not say what bounds it on a firmware that does not report
`maxLoad`. In that case the bound is **the registry's own ceiling**, 1500 W, the largest model
Heatit sells. The device refuses anything above its own rating either way (Q17). `maxLoad` gets no
registry descriptor. The registry is the client's *write* surface, and a descriptor would make a
never-written parameter writable. (3) #41's amendment gave the *climate* entity the registry's
bounds on a *setpoint bank* where a *temperature limit* is absent. **Both setpoint numbers need the
same two readings on the same terms.** So the fallback moves to the coordinator as
`minimum_temperature` / `maximum_temperature`, and is written once rather than per platform.

**2026-09-11 — §4.3's quiet abort carries the reason validation found** ([#60](https://github.com/Normio/HeatIt-Wifi-Panel/issues/60), PR pending).
§4.3 asked for a quiet abort and named no reason. `async_step_dhcp` picked `cannot_connect` for
both branches. So a host answering at the discovered address without being a panel aborted with
*Nothing answered at that address*. That is false for exactly that branch. The reason is now the
one `_async_validate` already computed. `config.abort` gains the `invalid_response` string it
needs. `config.error` had it, `config.abort` did not. This is the shape core itself ships. Hue's
discovery aborts `not_hue_bridge` rather than folding "not ours" into "no answer". Nothing gets
louder, and nothing is now read that was not read before. Core awaits a discovery flow and
discards its result, so the reason reaches no card and no log line. It is corrected because a
string that ships must be a string that is true, not because anyone reads this one. Step 4 names
the pair rather than leaving it to the code.

**2026-09-11 — what the 1.5 s refresh sees after a settings reset, and where the load limit lands** ([#73](https://github.com/Normio/HeatIt-Wifi-Panel/issues/73)).
§5.2 said the reset "applies staggered over ~5 s, so the 1.5 s refresh sees a partial reset and
the next poll completes it". The outcome is right. The mechanism was an assumption. On the #45
hardware run, at **1.8 s** after the acknowledgement **no parameter had moved at all**. All four
that the reset changed were present by **8.0 s**. So the refresh may equally see the panel as it
was. Nothing operational follows. There is still nothing to retry and nothing to fix, and a later
poll carries the change. The cell now says "may see a partial reset, or none of it yet". That run
sampled at 1.8 s and 8.0 s and nowhere between. So it says nothing about the ~5 s settle itself.
Register row Q34 stands. `scripts/probe.py`, which polls twice a second, is what can time it.

The same run answered **Q53**. Every parameter lands on the vendor document's stated default
except `loadLimit`. That lands on the unit's own `maxLoad`: 6 on the 600 W panel, against the
document's fixed 15, which that unit rejects anyway (Q17). The row is `verified fw 1.21` and
`disagrees`. The probe's check compares the load limit against `maxLoad`, so a firmware that
honours the document would fail it.

**2026-09-11 — the quality-scale gate runs in the test stage, reads the manifest's version, and holds the icon rule one way** ([#47](https://github.com/Normio/HeatIt-Wifi-Panel/issues/47)).
Three refinements.

(1) §9.2 says `scripts/check_quality_scale.py` is "run from `test.yml`", and §9.4 groups it with
the check scripts. Those run in `check.sh`'s lint half, which needs no Home Assistant. It runs in
the **test half** instead. The yaml is parsed with `homeassistant.util.yaml.load_yaml_dict`, the
loader hassfest itself uses. So a file hassfest would refuse is one this refuses too. PyYAML also
ships no stubs, so mypy strict would not accept a direct import. The cost is one run per matrix row
of a script that takes a moment. Failure condition 4 stays with `check_layout.py`, as the amendment
of PR #49 promised. That script now skips a `quality_scale` key rather than naming it, so one
problem has one line.

(2) "The version under check" in condition 5 is the manifest's `version`. `check_release.py` holds
the tag equal to it, so on a tag they are one number. On a pull request the manifest is the only
version there is. So the pull request that bumps it to `1.0.0` is the one that fails on a leftover
`todo`, before any tag exists. No rule is `todo` today. Every row of §9.1's "everything else"
shipped by 0.3.0. The `discovery` comment is §9.1's text word for word while register row Q28
stays open. When [#32](https://github.com/Normio/HeatIt-Wifi-Panel/issues/32) closes it,
the comment moves with the table.

(3) §9.2's table has `icon-translations` assert that every `translation_key` "resolves in
`translations/en.json` and `icons.json`". §5.2 has icons "only where a device class does not supply
one". Four entities, the two switches and the two selects, have neither and take their domain's
icon, as §5.2 lists them. So the test holds `icons.json` **one way**: every key in it names a
shipping entity and every value is an `mdi:` name. It holds the literal ban on both sides: no
`_attr_name` string and no `_attr_icon` or description `icon` on any entity. The icon cannot be
read back from a state, because the frontend resolves icon translations, not the state machine.
`translations/en.json` is held both ways: every entity resolves and there is no orphan key. And
condition 3 gains a clause. `common-modules` names two modules, and a second path in a `done`
comment's free text was evidence in name only. So every word starting with a top-level directory
of the tree is checked to exist, not the first alone.

**2026-09-12 — the README no longer has to recommend a static DHCP reservation** ([#82](https://github.com/Normio/HeatIt-Wifi-Panel/pull/82)).
§4.5 says the README recommends a static DHCP reservation, and §11.3 lists it as a required README
item. `tests/test_readme.py` held that promise. The owner dropped the sentence from the README, and
the test with it. The host is still not an options field. The DHCP IP-follow of §4.3 is what keeps
the entry pointed at the panel when its address changes, and a reservation is now only a user's
own choice, not a promise the README makes.
