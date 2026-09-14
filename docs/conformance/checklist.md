# Hardware conformance register

This file is a record of which panel behaviours have been tested, on which firmware, and with what
result. Each row is one behaviour the integration depends on. The row says whether a real panel has
confirmed it, and on which firmware.

The file is a **living register**, so it changes as more panels and firmwares are tested. It is not
part of the frozen v1 spec. `docs/spec/heatit-wifi-panel-v1.md` links here instead of repeating it.
It replaces §9 of `docs/research/panel-api-contract.md` and keeps its Q-numbers, so a reference to
"Q13" anywhere in this repo still points to the row below.

A row is verified **on one firmware**, and its status names **the units it was shown on**. Two
units so far, both at firmware 1.21: a **600 W** panel (`maxLoad` 6) and a **1000 W** panel
(`maxLoad` 10). A row shown on one of them is not shown on the other until a run says so. A new
model or firmware may give a different result, and this register is where that gets recorded.

## How to read a row

| column | meaning |
|---|---|
| **id** | Never changes. `Q1`–`Q38` come from the research document. `Q39`+ were raised by decision tickets. A retired id is never reused. `Q16`, `Q49`, `Q51` and `Q52` were retired on 2026-09-14 because each needed a firmware other than 1.21, and `Q48` because the panel offers no way to pair an external sensor. |
| **claim** | States *what the integration depends on*, in a way a real panel can prove false, so the status is a clear yes or no. Never states what the spec says. |
| **vs spec** | `agrees` / `disagrees` / `silent`. How the vendor's OpenAPI document relates to the claim. A `disagrees` row is the most valuable kind. It records a place where a future firmware could quietly go back to the documented behaviour. |
| **tier** | The probe tier, which is the hazard class. It matches the probe script's flags: `read`, `write`, `destructive`, `thermal`, `manual`. `manual` means no script can run it. |
| **status** | `open`, `verified fw <v> on <units>`, or `contradicted fw <v> on <units>`. Units are named by wattage, comma-separated: `verified fw 1.21 on 600 W, 1000 W`. The known units live in `scripts/check_conformance.py`. |
| **evidence** | Where the claim came from: an issue, a committed fixture, or a `P-n` procedure for an open manual row. Checked by CI. |
| **dependents** | What breaks if the row flips. Holds at least one reference CI can resolve: a repo path, an ADR, or an issue. May also hold prose. Checked by CI. |

**`contradicted` is not the same as `disagrees`.** A row starts as `open` or `verified`. `disagrees`
only records that the vendor document was wrong from the start. `contradicted` appears only when a
run **disproves a claim we already shipped code against**. That is why no row starts as
`contradicted`, and why it is the status that triggers work.

## How a row is checked

`scripts/probe.py` runs the automated rows. It picks its checks by the ids in this file:

```
probe.py                 → read tier only, unattended, no approval
probe.py --writes        → + benign writes, snapshotted and restore-verified
probe.py --destructive   → + kWh reset, settings reset          (y/N, TTY required)
probe.py --thermal       → + heater-on sequences                (y/N, TTY required)
```

`/api/reset/factory` is **structurally absent** from the probe. The path string appears nowhere in
its source, and a test asserts that. A factory reset unpairs the panel from the MyHeatit app and
leaves it off WiFi. No row asks for one.

`manual` rows have no script. Each has a numbered procedure in the appendix. Our single 600 W panel
at fw 1.21 can never close these rows, so the procedures are written for whoever has different
hardware.

This file is the **single source of the claim wording**. `probe.py` parses it at runtime for the
labels it prints, so a check and its claim cannot drift apart. `scripts/check_conformance.py` checks
the register in CI. It asserts that:

- ids are unique and statuses are legal.
- every `verified` row cites a firmware in `VERIFIED_FIRMWARES`, names known units, and has evidence that resolves.
- every dependents cell carries a resolvable reference.
- the register and `probe.py` hold exactly the same set of automated ids.

## When a claim is contradicted

When a run disproves a `verified` row:

1. flip the row to `contradicted fw <v> on <unit>` and cite the run.
2. open an issue labelled `conformance` that names the row. The **dependents** cell is the triage
   list, so nobody has to hunt for what breaks.
3. fix it in **one PR**. That PR carries the spec amendment, the code change, the new fixture and the
   row restored to `verified fw <v>`. It closes the issue.

The spec gains an **Amendments** section. It is not rewritten. The v1 document still reads as what
v1 claimed, with its corrections added at the end and dated.

## The register

| id | claim | vs spec | tier | status | evidence | dependents |
|----|-------|---------|------|--------|----------|------------|
| Q1 | Temperature writes accept bare integers and off-step values: the setpoint banks silently snap to the 0.5 grid, and the temperature limits reject off-step values | disagrees | write | verified fw 1.21 on 600 W, 1000 W | [#7](https://github.com/Normio/HeatIt-Wifi-Panel/issues/7) | [#11](https://github.com/Normio/HeatIt-Wifi-Panel/issues/11) number step and bounds |
| Q2 | An integer parameter given a decimal (`panelMode=1.0`) is rejected, not truncated | silent | write | verified fw 1.21 on 600 W, 1000 W | [#54](https://github.com/Normio/HeatIt-Wifi-Panel/issues/54) | [#7](https://github.com/Normio/HeatIt-Wifi-Panel/issues/7) registry serialisation |
| Q3 | Booleans accept `true`/`True`/`TRUE`/`1` and the false equivalents, and none is silently misread | silent | write | verified fw 1.21 on 600 W, 1000 W | [#7](https://github.com/Normio/HeatIt-Wifi-Panel/issues/7) | [#11](https://github.com/Normio/HeatIt-Wifi-Panel/issues/11) switch entities |
| Q4 | A multi-parameter write is all or nothing: one valid value plus one out-of-range value applies neither | silent | write | verified fw 1.21 on 600 W, 1000 W | [#54](https://github.com/Normio/HeatIt-Wifi-Panel/issues/54) | [#7](https://github.com/Normio/HeatIt-Wifi-Panel/issues/7) one parameter per request |
| Q5 | The 200 write echo uses the names sent and reports the value **applied**, with types normalised | agrees | write | verified fw 1.21 on 600 W, 1000 W | [#7](https://github.com/Normio/HeatIt-Wifi-Panel/issues/7) | [#7](https://github.com/Normio/HeatIt-Wifi-Panel/issues/7) optimistic update |
| Q6 | Writing a parameter to its current value returns 200, not 422 | disagrees | write | verified fw 1.21 on 600 W, 1000 W | [#7](https://github.com/Normio/HeatIt-Wifi-Panel/issues/7) | [#7](https://github.com/Normio/HeatIt-Wifi-Panel/issues/7) no diff-before-write |
| Q7 | `DELETE /api/reset/kwh` zeroes the energy counter without its documented query parameter | disagrees | destructive | verified fw 1.21 on 600 W, 1000 W | [#7](https://github.com/Normio/HeatIt-Wifi-Panel/issues/7) | [#18](https://github.com/Normio/HeatIt-Wifi-Panel/issues/18) reset button |
| Q8 | A query-string write applies correctly (a JSON body also works, but the query string is what we ship) | disagrees | write | verified fw 1.21 on 600 W, 1000 W | [#7](https://github.com/Normio/HeatIt-Wifi-Panel/issues/7) | [#7](https://github.com/Normio/HeatIt-Wifi-Panel/issues/7) client write path |
| Q9 | A POST with no body (`Content-Length: 0`) and a query string is accepted, which is aiohttp's default shape | silent | write | verified fw 1.21 on 600 W, 1000 W | [#7](https://github.com/Normio/HeatIt-Wifi-Panel/issues/7) | [#17](https://github.com/Normio/HeatIt-Wifi-Panel/issues/17) client posture |
| Q10 | `wifiSignalStrength` is signed and has the form `"-NNdBm"` | silent | read | verified fw 1.21 on 600 W, 1000 W | [#7](https://github.com/Normio/HeatIt-Wifi-Panel/issues/7) | [#11](https://github.com/Normio/HeatIt-Wifi-Panel/issues/11) signal sensor |
| Q11 | `Network.status` reads `"ok"` on a connected panel | agrees | read | verified fw 1.21 on 600 W, 1000 W | [#13](https://github.com/Normio/HeatIt-Wifi-Panel/issues/13) | [#21](https://github.com/Normio/HeatIt-Wifi-Panel/issues/21) diagnostics only |
| Q12 | `Network.mac` is **uppercase** hex with colons | disagrees | read | verified fw 1.21 on 600 W, 1000 W | [#13](https://github.com/Normio/HeatIt-Wifi-Panel/issues/13) | `docs/adr/0003-device-id-as-unique-id.md`, the `connections` migration hatch |
| Q13 | Eco mode regulates to `ecoSetpoint` | silent | thermal | verified fw 1.21 on 600 W, 1000 W | [#8](https://github.com/Normio/HeatIt-Wifi-Panel/issues/8), [#89](https://github.com/Normio/HeatIt-Wifi-Panel/issues/89) | [#8](https://github.com/Normio/HeatIt-Wifi-Panel/issues/8) climate presets, the founding assumption |
| Q14 | Either setpoint bank can be written in any panel mode, and only the live setpoint regulates | silent | write | verified fw 1.21 on 600 W, 1000 W | [#8](https://github.com/Normio/HeatIt-Wifi-Panel/issues/8) | [#11](https://github.com/Normio/HeatIt-Wifi-Panel/issues/11) setpoint numbers |
| Q15 | The temperature limits bound **both** banks, `min < max` is enforced, and narrowing a limit clamps a stored setpoint | silent | write | verified fw 1.21 on 600 W, 1000 W | [#8](https://github.com/Normio/HeatIt-Wifi-Panel/issues/8) | [#11](https://github.com/Normio/HeatIt-Wifi-Panel/issues/11) dynamic bounds |
| Q17 | A `loadLimit` above the reported `maxLoad` is rejected, not accepted and then misbehaving | silent | write | verified fw 1.21 on 600 W, 1000 W | [#54](https://github.com/Normio/HeatIt-Wifi-Panel/issues/54) | [#11](https://github.com/Normio/HeatIt-Wifi-Panel/issues/11) load limit bounds |
| Q18 | `state` reads `Idle` when the panel mode is Off | agrees | write | verified fw 1.21 on 600 W, 1000 W | [#8](https://github.com/Normio/HeatIt-Wifi-Panel/issues/8) | [#8](https://github.com/Normio/HeatIt-Wifi-Panel/issues/8) `hvac_action` mapping |
| Q19 | `state` reads `Heating` whenever the relay is closed, including while open window detection is overriding | silent | manual | open | [P-4](#p-4) | [#8](https://github.com/Normio/HeatIt-Wifi-Panel/issues/8) `hvac_action` mapping |
| Q20 | `currentPower` trails the relay by ~15 s and must never drive `hvac_action` | silent | thermal | verified fw 1.21 on 600 W, 1000 W | [#8](https://github.com/Normio/HeatIt-Wifi-Panel/issues/8) | [#11](https://github.com/Normio/HeatIt-Wifi-Panel/issues/11) power sensor |
| Q21 | A kWh reset sets the energy counter to exactly `0.00`, never a partial value | silent | destructive | verified fw 1.21 on 600 W, 1000 W | [#18](https://github.com/Normio/HeatIt-Wifi-Panel/issues/18) | [#18](https://github.com/Normio/HeatIt-Wifi-Panel/issues/18) `total_increasing` and the 10 % dip rule |
| Q22 | `totalConsumption` carries two decimals on the wire | agrees | read | verified fw 1.21 on 600 W, 1000 W | [#13](https://github.com/Normio/HeatIt-Wifi-Panel/issues/13) | [#11](https://github.com/Normio/HeatIt-Wifi-Panel/issues/11) energy sensor |
| Q23 | `sensorCalibration` shifts `roomTemperature` in `/api/status`, not only the display | silent | write | verified fw 1.21 on 600 W, 1000 W | [#54](https://github.com/Normio/HeatIt-Wifi-Panel/issues/54) | [#11](https://github.com/Normio/HeatIt-Wifi-Panel/issues/11) temperature sensor |
| Q24 | No status field is ever `null`, and a missing field means that parameter does not exist on this firmware | silent | read | verified fw 1.21 on 600 W, 1000 W | [#13](https://github.com/Normio/HeatIt-Wifi-Panel/issues/13) | [#14](https://github.com/Normio/HeatIt-Wifi-Panel/issues/14) required core and absent-field rules |
| Q25 | `OWD.activeTime` is `0` while `activeNow` is false | agrees | read | verified fw 1.21 on 600 W, 1000 W | [#13](https://github.com/Normio/HeatIt-Wifi-Panel/issues/13) | [#11](https://github.com/Normio/HeatIt-Wifi-Panel/issues/11) open-window duration sensor |
| Q26 | The device `id` survives a settings reset | silent | destructive | verified fw 1.21 on 600 W, 1000 W | [#10](https://github.com/Normio/HeatIt-Wifi-Panel/issues/10) | `docs/adr/0003-device-id-as-unique-id.md` |
| Q27 | `name` and `room` are free text, and `room` is `""` until the app assigns the panel a room | silent | read | verified fw 1.21 on 600 W, 1000 W | [#10](https://github.com/Normio/HeatIt-Wifi-Panel/issues/10) | [#10](https://github.com/Normio/HeatIt-Wifi-Panel/issues/10) title and `suggested_area` |
| Q28 | The panel runs no mDNS responder: a multicast browse that its own-segment neighbours answer within 100 ms returns no record for it, no service of any type, no hostname and no reverse PTR. SSDP is a unicast negative only, and the DHCP lease hostname is unread | silent | manual | verified fw 1.21 on 600 W | [#32](https://github.com/Normio/HeatIt-Wifi-Panel/issues/32), [P-2](#p-2) | [#10](https://github.com/Normio/HeatIt-Wifi-Panel/issues/10) discovery, [#21](https://github.com/Normio/HeatIt-Wifi-Panel/issues/21) `quality_scale.yaml` |
| Q29 | An unknown path returns `404` with `Content-Type: text/html` and the body `Nothing matches the given URI`, and `GET /` does the same, so there is no web UI | silent | read | verified fw 1.21 on 600 W, 1000 W | [#13](https://github.com/Normio/HeatIt-Wifi-Panel/issues/13) | [#10](https://github.com/Normio/HeatIt-Wifi-Panel/issues/10) config-flow fingerprint, no `configuration_url` |
| Q30 | The panel accepts at least 2 concurrent connections, and its accept backlog fails at roughly 4–5 | silent | read | verified fw 1.21 on 600 W, 1000 W | [#17](https://github.com/Normio/HeatIt-Wifi-Panel/issues/17) | [#17](https://github.com/Normio/HeatIt-Wifi-Panel/issues/17) one-request-in-flight lock |
| Q31 | A write is reflected in `/api/status` within 1.5 s (observed 305–632 ms) | silent | write | verified fw 1.21 on 600 W, 1000 W | [#7](https://github.com/Normio/HeatIt-Wifi-Panel/issues/7) | [#17](https://github.com/Normio/HeatIt-Wifi-Panel/issues/17) post-write refresh delay |
| Q32 | The HTTP server refuses fast instead of hanging while the panel is rebooting or off WiFi | silent | manual | open | [P-3](#p-3) | [#14](https://github.com/Normio/HeatIt-Wifi-Panel/issues/14) `ConfigEntryNotReady`, [#17](https://github.com/Normio/HeatIt-Wifi-Panel/issues/17) timeouts |
| Q33 | The panel answers only on tcp/80 with plain HTTP: no HTTPS, no other port, no redirect | silent | read | verified fw 1.21 on 600 W, 1000 W | [#10](https://github.com/Normio/HeatIt-Wifi-Panel/issues/10) | [#10](https://github.com/Normio/HeatIt-Wifi-Panel/issues/10) config flow |
| Q34 | A settings reset leaves `id`, `name`, `room` and the network block untouched, does not reboot, and settles within ~8 s | silent | destructive | verified fw 1.21 on 600 W, 1000 W | [#89](https://github.com/Normio/HeatIt-Wifi-Panel/issues/89), [#74](https://github.com/Normio/HeatIt-Wifi-Panel/issues/74), [#11](https://github.com/Normio/HeatIt-Wifi-Panel/issues/11) | [#11](https://github.com/Normio/HeatIt-Wifi-Panel/issues/11) settings-reset button |
| Q35 | The firmware version and the OpenAPI document's version are separate numbering schemes, and no endpoint or header exposes an API version | disagrees | read | verified fw 1.21 on 600 W, 1000 W | [#13](https://github.com/Normio/HeatIt-Wifi-Panel/issues/13) | [#14](https://github.com/Normio/HeatIt-Wifi-Panel/issues/14) `VERIFIED_FIRMWARES` |
| Q36 | The success sentinel is `"Success"` (capital S) and the failure sentinel `"failed"` (lowercase) | disagrees | write | verified fw 1.21 on 600 W, 1000 W | [#7](https://github.com/Normio/HeatIt-Wifi-Panel/issues/7) | [#7](https://github.com/Normio/HeatIt-Wifi-Panel/issues/7) client response parser |
| Q37 | The 200 write body is `{status, <echoed parameter names>}`, not the WiFi6 client's `{status, value}` | agrees | write | verified fw 1.21 on 600 W, 1000 W | [#7](https://github.com/Normio/HeatIt-Wifi-Panel/issues/7) | [#7](https://github.com/Normio/HeatIt-Wifi-Panel/issues/7) client response parser |
| Q38 | Re-sending an identical parameter write is harmless and returns 200 | silent | write | verified fw 1.21 on 600 W, 1000 W | [#7](https://github.com/Normio/HeatIt-Wifi-Panel/issues/7) | [#17](https://github.com/Normio/HeatIt-Wifi-Panel/issues/17) writes are never retried |
| Q39 | The panel speaks HTTP/1.1 only, and refuses an HTTP/1.0 request with 505 | silent | read | verified fw 1.21 on 600 W, 1000 W | [#17](https://github.com/Normio/HeatIt-Wifi-Panel/issues/17) | [#17](https://github.com/Normio/HeatIt-Wifi-Panel/issues/17) client posture |
| Q40 | Responses carry `Content-Length`, and the panel never uses chunked transfer | silent | read | verified fw 1.21 on 600 W, 1000 W | [#17](https://github.com/Normio/HeatIt-Wifi-Panel/issues/17) | [#17](https://github.com/Normio/HeatIt-Wifi-Panel/issues/17) client posture |
| Q41 | Success responses carry `Content-Type: application/json`, so `response.json()` works without a content-type override | silent | read | verified fw 1.21 on 600 W, 1000 W | [#13](https://github.com/Normio/HeatIt-Wifi-Panel/issues/13) | [#17](https://github.com/Normio/HeatIt-Wifi-Panel/issues/17) client parser (the WiFi6 device fails this) |
| Q42 | The panel honours keep-alive, and an idle socket survives at least 65 s | silent | read | verified fw 1.21 on 600 W, 1000 W | [#17](https://github.com/Normio/HeatIt-Wifi-Panel/issues/17) | [#17](https://github.com/Normio/HeatIt-Wifi-Panel/issues/17) shared HA session |
| Q43 | A status read completes in under 5 s (observed 30–210 ms) | silent | read | verified fw 1.21 on 600 W, 1000 W | [#17](https://github.com/Normio/HeatIt-Wifi-Panel/issues/17) | [#17](https://github.com/Normio/HeatIt-Wifi-Panel/issues/17) poll budget and per-attempt timeout |
| Q44 | The energy counter survives a power cycle | silent | manual | open | [P-3](#p-3) | [#18](https://github.com/Normio/HeatIt-Wifi-Panel/issues/18) `total_increasing` |
| Q45 | The energy counter reads `0.00` within 5 s of a reset acknowledgement | silent | destructive | verified fw 1.21 on 600 W, 1000 W | [#18](https://github.com/Normio/HeatIt-Wifi-Panel/issues/18) | [#18](https://github.com/Normio/HeatIt-Wifi-Panel/issues/18) reset-verification delay, an upper bound rather than a measurement |
| Q46 | The energy counter advances in steps of no more than 0.05 kWh at any wattage | silent | manual | open | [P-5](#p-5), [#89](https://github.com/Normio/HeatIt-Wifi-Panel/issues/89) | [#18](https://github.com/Normio/HeatIt-Wifi-Panel/issues/18) one lost step per reset |
| Q47 | `OWD.activeTime` counts down in seconds while `activeNow` is true | agrees | manual | open | [P-4](#p-4) | [#11](https://github.com/Normio/HeatIt-Wifi-Panel/issues/11) open-window duration sensor |
| Q50 | A settings reset sets `loadLimit` to the unit's own `maxLoad` on a **second model**, meaning any unit whose `maxLoad` is not 6 (a unit above 1500 W would also separate `maxLoad` from `min(maxLoad, 15)`, which neither probed unit can) | disagrees | manual | verified fw 1.21 on 1000 W | [#74](https://github.com/Normio/HeatIt-Wifi-Panel/issues/74), [P-8](#p-8) | [#11](https://github.com/Normio/HeatIt-Wifi-Panel/issues/11) load limit bounds. Q53 is shown on the 600 W unit, and [#74](https://github.com/Normio/HeatIt-Wifi-Panel/issues/74) says why the 1000 W run did not show it |
| Q53 | A settings reset sets every parameter to the vendor document's stated default **except `loadLimit`, which it sets to the unit's own `maxLoad`** | disagrees | destructive | verified fw 1.21 on 600 W, 1000 W | [#74](https://github.com/Normio/HeatIt-Wifi-Panel/issues/74), [#73](https://github.com/Normio/HeatIt-Wifi-Panel/issues/73) | `docs/api/heatit-wifi-panel-openapi.yaml`, the only claim we have about post-reset state, and wrong in this one place. Q50 is the same fact from the other side, on a unit whose `maxLoad` is not 6 |
| Q54 | `/api/status` is computed fresh for each request, not served from a cache | silent | read | verified fw 1.21 on 600 W, 1000 W | [#13](https://github.com/Normio/HeatIt-Wifi-Panel/issues/13) | [#12](https://github.com/Normio/HeatIt-Wifi-Panel/issues/12) fixture diff carries live-value noise |
| Q55 | A POST with no parameters gets no response at all: the firmware closes the connection, and the documented 422 does not exist | disagrees | write | verified fw 1.21 on 600 W, 1000 W | [#7](https://github.com/Normio/HeatIt-Wifi-Panel/issues/7) | [#14](https://github.com/Normio/HeatIt-Wifi-Panel/issues/14) write error handling |
| Q56 | A 400 body is free text that names the bad parameter, not the document's fixed `invalid data.` | disagrees | write | verified fw 1.21 on 600 W, 1000 W | [#7](https://github.com/Normio/HeatIt-Wifi-Panel/issues/7) | [#14](https://github.com/Normio/HeatIt-Wifi-Panel/issues/14) device `reason` surfaced verbatim |
| Q57 | A reset returns `{"status":"Success"}` with the `status` key, the same as parameter writes, not the documented `reset` key | disagrees | destructive | verified fw 1.21 on 600 W, 1000 W | [#7](https://github.com/Normio/HeatIt-Wifi-Panel/issues/7) | [#7](https://github.com/Normio/HeatIt-Wifi-Panel/issues/7) client response parser |
| Q58 | `sensorMode=true` on a panel with no external sensor paired returns a success echo but is not applied: a silent undo | silent | write | verified fw 1.21 on 600 W, 1000 W | [#11](https://github.com/Normio/HeatIt-Wifi-Panel/issues/11) | [#14](https://github.com/Normio/HeatIt-Wifi-Panel/issues/14) silent-undo warning, [#11](https://github.com/Normio/HeatIt-Wifi-Panel/issues/11) switch entity |

**48 verified at firmware 1.21 (47 on the 600 W unit, 47 on the 1000 W unit), 5 open, 12 `disagrees`.** Nothing is `contradicted`. The places
where the vendor document is simply wrong are recorded as `disagrees`, which is a different thing.
Those claims were never true. They did not stop being true. CI holds the three figures in the bold
sentence to the table, the two unit counts included.

## Appendix: manual procedures

These are the rows no script may run. Most need hardware this project does not have. If you run one,
open an issue labelled `conformance` on this repository with the results and the raw response bytes.
That is how a row becomes verified for a firmware or a model we have never seen.

Record three things with every result: the **firmware** string, the **model** string, and `maxLoad`,
all from `GET /api/status`. A result without them cannot go into the register. `maxLoad` is what
names the unit in a status: 6 is the 600 W panel, 10 the 1000 W panel.

<a id="p-2"></a>
### P-2 — on-segment discovery (Q28)

Needs a host on the panel's **own L2 segment**, or a router that reflects mDNS between segments.
Link-local mDNS (224.0.0.251, TTL 1) cannot cross a routed boundary on its own. So a sweep from
another VLAN is no evidence at all **unless the panel's neighbours show up in it**. Their presence
is the control that turns an off-segment browse into a real measurement.

**What closed the mDNS half (2026-09-11, fw 1.21).** The site router reflects mDNS. We ran a 75 s
browse from `10.10.150.0/24` for `_services._dns-sd._udp`, `_http._tcp`, `_heatit._tcp`,
`_arduino._tcp`, `_esphomelib._tcp`, `_espressif._tcp`, `_esphome._tcp` and the reverse PTR of the
panel's address. It returned other devices on the panel's own `10.10.30.0/24`. Repeated
`_http._tcp` queries got their answers within 40–120 ms every time. That is the control that makes
the browse a measurement. The panel was alive on tcp/80 throughout and appeared in none of it.
There was no A record for `10.10.30.40`, no instance naming it, no answer to the reverse lookup, and
no announcement in the background traffic. Devices that share the panel's `E4:B3:23` OUI did answer.
That is the MAC-prefix matcher's false positive, seen live.

**Still open.** SSDP: the same run's multicast `M-SEARCH` got nothing from any device. So SSDP
reflection is unproven, and the `:1900` negative is still only the unicast one. The DHCP lease
hostname: the router exposes no admin surface off-segment. Neither changes the row, because Home
Assistant's zeroconf is the mDNS half. But whoever sits on the segment should still run the SSDP
`M-SEARCH` and read the DHCP lease hostname, as the checklist below says.

The full checklist, including what off-segment runs have already ruled out, is in
[#32](https://github.com/Normio/HeatIt-Wifi-Panel/issues/32). In short: a ~30 s
`avahi-browse -art`, the targeted ESP-family service types, an SSDP `M-SEARCH`, and the router's DHCP
lease hostname for the panel's MAC.

Report: every record that resolves to the panel, with service type, instance name, port and all TXT
keys. A matcher is only as good as the fields it can key on. A clean negative is a useful result. It
becomes the `discovery` exemption comment.

<a id="p-3"></a>
### P-3 — power cycle and WiFi loss (Q32, Q44)

1. `GET /api/status`. Record `totalConsumption`.
2. Cut mains power to the panel for 30 s, then restore it.
3. Poll `GET /api/status` every second from the moment power is restored. Record how long the first
   successful response takes. Record whether the earlier attempts **refuse fast** or hang until
   timeout. That difference decides the client's connect timeout.
4. Record `totalConsumption` on the first successful response.
5. For the WiFi half: take the panel's SSID down instead of its power, and record the same.

Report: time to first response, the failure mode before it (connection refused / no route / timeout),
and the counter value before and after.

<a id="p-4"></a>
### P-4 — an open window detection event (Q19, Q47)

Needs a real temperature drop, so it needs a real open window and a cold day.

1. Enable open window detection (`openWindowDetection=true`). Set the panel mode to Heating with the
   comfort setpoint above room temperature, so the relay is closed.
2. Open a window near the panel.
3. Poll `GET /api/status` every 5 s until `OWD.activeNow` becomes true, then for a further 5 minutes.
4. Record every distinct `OWD.activeTime`, with its timestamp, and `state` throughout.

Report: whether `activeTime` only ever decreases, in seconds, what value it starts at, and whether
`state` reads `Idle` or `Heating` while the override is active.

<a id="p-5"></a>
### P-5 — energy publication step size at another wattage (Q46)

Needs a panel that is not 600 W.

1. Record `maxLoad`. Set the panel mode to Heating so the relay stays closed the whole time.
2. Poll `GET /api/status` every 5 s for at least 20 minutes.
3. Record every distinct `totalConsumption` value with its timestamp and the `currentPower` alongside.

Report: the step size between consecutive distinct values, and the time between them. This tells us
whether the counter publishes by energy or by time. One 600 W unit cannot tell those apart.

<a id="p-8"></a>
### P-8 — settings reset on a second model (Q50)

Needs a panel whose `maxLoad` is not 6. A 1000 W unit qualifies. It destroys that
panel's settings, so snapshot them first.

This is `probe.py`'s own destructive tier pointed at another panel. A second
pointer file is how it gets there:

```
cp .local/device.example.json .local/device-<unit>.json     # fill in host, maxLoad, notes
python3 scripts/probe.py --device .local/device-<unit>.json --destructive
```

By hand, if the probe cannot reach it:

1. `GET /api/status`. Record `maxLoad` and the full `parameters` object.
2. `DELETE /api/reset/settings`.
3. Wait 10 s, then `GET /api/status` and record `parameters` again.
4. Write every recorded parameter back, and confirm each from a fresh read.

Report: `maxLoad`, and `loadLimit` before and after. Q53 is verified on the
600 W unit. There the reset set the load limit to `maxLoad` 6, not the
document's fixed 15. This run asks the same question of a second model. It
still cannot settle one thing: at `maxLoad` 10 or 15, "lands on `maxLoad`" and
"lands on `min(maxLoad, 15)`" predict the same value. Only a unit above
1500 W can separate them.
