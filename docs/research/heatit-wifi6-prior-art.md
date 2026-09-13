# Prior art audit: `mattik-gh/heatit_wifi6`

Research output for [issue #4](https://github.com/Normio/HeatIt-Wifi-Panel/issues/4), *Research: audit mattik-gh/heatit_wifi6 against current standards*.
Parent map: [issue #1](https://github.com/Normio/HeatIt-Wifi-Panel/issues/1).

**Scope note.** This document gives **no fork / read-and-rewrite / ignore verdict**. The map owner changed the scope and moved that decision to [issue #16](https://github.com/Normio/HeatIt-Wifi-Panel/issues/16). Issue #16 is blocked on this ticket, on [#2](https://github.com/Normio/HeatIt-Wifi-Panel/issues/2) (current HA conventions) and on [#3](https://github.com/Normio/HeatIt-Wifi-Panel/issues/3) (HACS default requirements). This document only collects facts. It is laid out so someone else can score them.

**Method.** This audit cloned the repository and read all of it. That covers all 1,548 lines of Python in both shipped integration directories, the vendored OpenAPI document, `manifest.json`, `hacs.json` and the complete git history. Requirements come from primary sources: the developers.home-assistant.io rule pages and the `home-assistant/core` source itself. Each is cited inline. The README was read, but no judgement here rests on it.

**Audited revision.** `569fc32`, dated 2026-06-09. It was the repository HEAD on the audit date, 2026-09-07.

---

## 1. Licence — the hard facts

### What it is

`LICENSE.md` is the **MIT License**. The text is the standard text, unchanged. The copyright line is:

```
Copyright (c) 2025 mattik-gh
```

GitHub's own licence detection agrees (`repos/mattik-gh/heatit_wifi6` → `license.spdx_id == "MIT"`). `README.md` says the same. The repository has no second licence, no `NOTICE`, no CLA, and no DCO sign-off requirement.

### Obligations a fork or copy-with-modification creates

MIT sets exactly one duty you must act on. The key sentence is:

> The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

For a repository we plan to publish on HACS, this means:

| Situation | Obligation |
| --- | --- |
| Fork the repo wholesale | Keep `LICENSE.md` with the `Copyright (c) 2025 mattik-gh` line intact. We may add our own copyright line. We may not remove or replace theirs. |
| Copy a *substantial portion* (e.g. lift `api.py`, or the climate mode-mapping logic, into our tree) | Ship the MIT notice and the copyright line with it. The usual way is a `LICENSE-THIRD-PARTY` / `NOTICE` file, or a header comment on the derived file that names the origin. |
| Copy a trivial fragment (a one-line idiom, a constant, an endpoint path string) | No duty applies. Endpoint paths and parameter names come from Heatit's own OpenAPI document, not from this repo. They are facts about the device, not creative work. |
| Read it, learn from it, write our own | **No obligation at all.** MIT limits how the code is distributed. It does not limit what you learn from reading it. |

MIT is permissive. It has no copyleft, no share-alike, and no limit on relicensing the combined work. It does not conflict with HACS. HACS only requires that a repository *have* a licence.

### The two licence facts that actually constrain the map

**(a) HA core is Apache-2.0, and MIT-derived code creates a provenance question there.**
The map's stated quality bar is "built so Home Assistant **core** inclusion stays viable". Home Assistant core is licensed Apache-2.0, and it accepts contributions under those terms. Relicensing MIT code as Apache-2.0 is legal, because MIT is one-way compatible with Apache-2.0. *The MIT notice must be kept.* In practice, a core PR with MIT-derived third-party code carries a foreign copyright header and a second licence file. A core reviewer must think about those instead of approving quickly. A clean-room implementation carries none of that. **This is the licence point that matters for the map's quality bar. It is about friction and provenance, not a legal ban.** It is recorded here. Issue #16 weighs the trade-off.

**(b) The copyright line is incomplete, so a fork inherits an unclear chain.**
`LICENSE.md` names only `mattik-gh`. The git history shows that others wrote a large part of the code:

- `atlehogberg`: commits `fc82835`, `6a7cfcd`, `07482d2`, `3907d8c`, `c867d6d`, `1eb1b01` (2026-02 → 2026-03). This is *most of the current `api.py`* (retry logic), the staggered-startup code in `__init__.py`, and the eco-preset handling in `climate.py`.
- `Vladislav` / `vlad-323`: commits `94e1b71`, `8af4b9d`, `5d330f5` (2025-09).

These changes came in as pull requests (#2, #7) to a repo with no CLA and no DCO. The standard inbound=outbound position applies (GitHub ToS §D.6, plus the repo's own MIT licence as the stated project licence). Under it, those contributions are offered under MIT, so a fork is safe. But the `LICENSE.md` copyright line is incomplete. A careful attribution of forked code names at least three people. One of them, `atlehogberg`, maintains a competing downstream fork. HACS default listing does not care about this. HA core review probably would.

**Bottom line on licence: MIT is permissive and creates no blocking duty. Copying costs only a kept third-party notice and an incomplete authorship chain. The only real risk is extra friction on a future core PR. Reading the code costs nothing.**

---

## 2. Maintenance signals

All figures come from the GitHub API on 2026-09-07.

| Signal | Value |
| --- | --- |
| Created | 2025-03-31 |
| Last push | 2026-06-09 (~3 months before audit) |
| Total commits | 14, on a single `main` branch |
| **Releases** | **0** |
| **Tags** | **0** |
| Stars | 15 |
| Forks | 4 |
| Watchers | 4 |
| Open issues/PRs | 4 open (issues #3, #5, #6, #9) |
| Archived | No |
| Repo description | **empty** |
| Repo topics | **none** |
| In HACS default list | **No.** The `integration` file in `hacs/default` has no `heatit` and no `mattik` entry. Users install it via "Custom repositories" only, as the README itself says. As of HEAD it also **could not be accepted**. It has zero releases (a full GitHub release is code-enforced for the default list), an empty description and no topics (two HACS Action failures), and a hassfest manifest key-order error. See §3.4 rows 23b, 31, 32c. |
| Tests | None. No `tests/` directory, no test framework, no fixtures. |
| CI | None. No `.github/` directory at all. No hassfest action, no HACS action, no linting. |
| `quality_scale` | Not declared in `manifest.json`. No `quality_scale.yaml`. |

### Apparent user base and project health

15 stars and 4 forks mean "a handful of households". These named people are visible in the issue tracker as users: `mattik-gh`, `atlehogberg` (reports 5–6 thermostats), `nacree`, `chrispylizard`, `lvlie`, `t-liski-navi`, `santa-krauja`, `vlad-323`. That is roughly the whole population we can see.

Three signals matter more than the counts:

1. **The maintainer has said they have limited time.** In issue #5 (2026-02-13) the owner writes: *"I have limited time to continue development and debug of this Heatit Wifi6 project. It works well for me as is."* PR #7 was the large stability rewrite. It waited from 2026-03-04 to 2026-06-09 before merge, while contributors asked for attention (issue #6).

2. **Attempts to modernise have not landed.** Two separate contributors tried to move the integration from one climate entity with attributes to a proper multi-entity model:
   - PR #8 (`santa-krauja`, "Update to use entities") was **closed unmerged on 2026-03-15, with no comment**.
   - Issue #9 (`lvlie`, 2026-03-23) offers a branch that adds real power/energy sensors and a CI pipeline. It is **open and unanswered.**

   The attributes-not-entities design is not an accident waiting for a patch. The maintainer defends it (issue #3: users should build template sensors from attributes in `configuration.yaml`). Anyone who builds on this repo inherits a design its owner has refused to change.

3. **The merge that did land broke the repo structure.** See §3, the `hacs.json`/structure rows. `custom_components/` now holds **two** integration directories, `heatit_wifi6` and `heatit_wifi6_custom`. They are byte-identical except for the `DOMAIN` constant and a UTF-8 BOM/line-ending difference in the vendored YAML. `atlehogberg` flagged this himself in issue #5 (*"the `heatit_wifi6_custom/` files at the bottom should be ignored and not included in the pull"*). The files were merged anyway.

---

## 3. Conformance audit against current standards

Each requirement cites the Home Assistant Integration Quality Scale rule pages or the `home-assistant/core` source. HA states that the Bronze tier is required of all new integrations. Silver/Gold rows are included where the map's "core inclusion stays viable" bar makes them relevant.

Legend: ✅ conforms · ⚠️ partial / fragile · ❌ does not conform · n/a not applicable.

### 3.1 Config entry lifecycle and runtime data

| # | Requirement | Source | What `heatit_wifi6` does | Conforms | Remediation cost |
| --- | --- | --- | --- | --- | --- |
| 1 | Store runtime data in `ConfigEntry.runtime_data`. Use a typed `ConfigEntry` alias, e.g. `type MyIntegrationConfigEntry = ConfigEntry[MyClient]` | QS Bronze `runtime-data` | Uses `hass.data.setdefault(DOMAIN, {})` in `async_setup`, and `hass.data[DOMAIN].pop(entry.entry_id, None)` on unload. Nothing is ever *stored* there. The dict is created and popped but never written. The API client is built inside `climate.py`'s `async_setup_entry`, and only the entity holds it. | ❌ | Low as a code change, but only once a coordinator exists to *be* the runtime data. Right now there is no object to store. |
| 2 | Setup must check that setup is possible. Raise `ConfigEntryNotReady` on a transient failure so HA retries | QS Bronze `test-before-setup` | `climate.py:async_setup_entry` calls `api.get_device_id(retries=0, timeout=8)`. On failure it **logs a warning, makes up a fake id** (`f"unknown_{host.replace('.', '_')}"`) and adds the entity anyway. `__init__.py:async_setup_entry` always returns `True`. `ConfigEntryNotReady` is never raised anywhere in the codebase. | ❌ | Moderate. This is the root cause of open issue #4 ("Reload required after HA restart"). HA's own retry machinery is bypassed, so a device that is slow at boot stays degraded until a manual reload. |
| 3 | Do not block setup. Use HA's retry instead of sleeping | QS Bronze `test-before-setup`; core setup contract | `__init__.py` computes a per-entry index and runs `await asyncio.sleep(index * 2 + 2)` **inside `async_setup_entry`**, before it forwards platforms. Every entry sleeps at least 2 s. The sixth panel sleeps 12 s. | ❌ | Low to delete, moderate to replace. The *problem* it addresses is real (see §5). The fix is wrong. It runs setups one after another instead of handling failure. |
| 4 | Support config entry unloading | QS Silver `config-entry-unloading` | Implements `async_unload_entry`, but via `async_forward_entry_unload(entry, "climate")`. | ⚠️ | Trivial. Core's own docstring on `ConfigEntries.async_forward_entry_unload` says: *"Its is preferred to call `async_unload_platforms` instead of directly calling this method."* (`homeassistant/config_entries.py` L2888-2894). Not deprecated, but not the preferred call. |
| 5 | `async_setup` should not exist only to seed `hass.data` | — | Defines `async_setup` only to run `hass.data.setdefault(DOMAIN, {})`. With `runtime_data` this function has no reason to exist. | ⚠️ | Trivial (delete). |
| 6 | `PARALLEL_UPDATES` must be specified per platform | QS Silver `parallel-updates` | Not defined in `climate.py`. | ❌ | Trivial (one line). |

### 3.2 Data fetching, coordinator, and failure handling

| # | Requirement | Source | What `heatit_wifi6` does | Conforms | Remediation cost |
| --- | --- | --- | --- | --- | --- |
| 7 | Use `DataUpdateCoordinator` when one poll serves many entities. Signal failure with `UpdateFailed`. Use `async_config_entry_first_refresh` so a failed first fetch raises `ConfigEntryNotReady` | HA docs, *Fetching data*; QS `test-before-setup` | **No coordinator anywhere.** The single `ClimateEntity` polls itself in `async_update()`. No file imports `DataUpdateCoordinator`, `CoordinatorEntity` or `UpdateFailed`. | ❌ | High. This is the structural rewrite. With one entity the gap is survivable. The Panel's ~25-entity, 7-platform surface makes a coordinator mandatory. Without one, 25 entities poll the device on their own. |
| 8 | Recommended: pass a shared web session into the client, `async_get_clientsession(hass)` for aiohttp. Create your own only in special cases such as cookie isolation | QS Platinum `inject-websession` | `api.py` builds **a new `aiohttp.TCPConnector` and `aiohttp.ClientSession` for every single HTTP call**. `_get`, `_post` and `_delete` each open and close a session inside their own `async with`. It also forces `resolver=aiohttp.resolver.ThreadedResolver()` and `trust_env=False`. `hass` is never passed to the API class. | ❌ | Low to fix (inject the session), but it changes the whole `HeatitWiFi6API` constructor signature. At 1 request/min/device the waste is tolerable. At the Panel's target entity count with several panels it is not. |
| 9 | Errors must propagate so the coordinator can mark entities unavailable | QS Silver `entity-unavailable`, `log-when-unavailable` | Every error path in `api.py` **swallows the exception and returns `{}`**: `_get` (both `TimeoutError` and bare `except Exception`), `_post`, `_delete`. Nothing ever raises. The entity then infers unavailability from a falsy dict. `exceptions.py` defines `CannotConnect`. `climate.py` imports it and **never raises or catches it anywhere**. | ❌ | Moderate. This defect has the widest reach. The caller cannot tell apart "device offline", "malformed JSON", "HTTP 400 out of range" and "HTTP 422 no parameters changed". For the Panel that matters directly. The API's documented 400/422 responses look the same as a network drop. |
| 10 | Set an appropriate polling interval, declared where HA reads it | QS Bronze `appropriate-polling` | `climate.py` sets `SCAN_INTERVAL = timedelta(minutes=POLL_INTERVAL)` **as a class attribute on the entity**. Core reads it from the *platform module*: `homeassistant/helpers/entity_component.py` L191, `scan_interval=getattr(platform, "SCAN_INTERVAL", None)`. So a class attribute is never read. The platform falls back to the `climate` component's own `SCAN_INTERVAL`, which is `timedelta(seconds=60)` (`homeassistant/components/climate/__init__.py` L101). | ❌ (latent) | Trivial (move to module scope). **The bug is invisible today only by luck**: climate's 60 s default happens to equal the intended `POLL_INTERVAL = 1` minute. Change the constant and nothing happens. That is exactly the trap a derived integration would fall into, since the Panel handoff proposes a 30 s default. |
| 11 | `should_poll` handling | core `entity_platform.py` | Sets `should_poll = False` as a plain class attribute (not `_attr_should_poll`). Then it **sets `self.should_poll = True` at runtime inside `async_added_to_hass`**, after `async_add_entities([entity], False)`. | ⚠️ | Trivial under a coordinator (`CoordinatorEntity` handles it). As written, polling registration depends on the order of core's add-entity sequence, not on a declared value. |
| 12 | Service/entity actions should raise exceptions on failure | QS Silver `action-exceptions` | `async_set_temperature`, `async_set_preset_mode` and `async_set_hvac_mode` all fail silently. `set_parameter` returns `{}` and the `if` does not fire. The user sees no error. The UI reverts on the next poll. | ❌ | Moderate. |

### 3.3 Entities, naming and identity

| # | Requirement | Source | What `heatit_wifi6` does | Conforms | Remediation cost |
| --- | --- | --- | --- | --- | --- |
| 13 | Entities set `_attr_has_entity_name = True` (*"required for new integrations"*) | QS Bronze `has-entity-name`; HA docs, *Entity* | `climate.py` L61 declares **`attr_has_entity_name = True`**. The leading underscore is missing. This is not a recognised attribute name. It sets an inert instance attribute, and `has_entity_name` stays `False`. | ❌ | Trivial to fix (one character). But the fix *changes every entity's `friendly_name`* for existing users, so upstream is now somewhat stuck with it. |
| 14 | Entity names come from `EntityDescription` / translation keys, not hand-rolled `name` properties | QS Gold `entity-translations`; HA docs, *Entity* | No `EntityDescription` of any kind is used. The string "EntityDescription" does not appear in the repository. `climate.py` defines a `name` **property with a setter** that returns the raw user-typed name. | ❌ | High for the Panel's surface. A table driven by entity descriptions is the natural shape for ~25 parameter-backed entities. This repo has no such table to borrow. |
| 15 | Entities have a unique ID, not user-configurable | QS Bronze `entity-unique-id`; HA docs, *Entity* | `unique_id` returns `f"heatit_wifi6_{self._device_id}"`. The device id comes from `/api/status`. **But** when the device is unreachable at setup, `_device_id` becomes `f"unknown_{host.replace('.', '_')}"`. The unique ID is then **derived from the IP address**, which the user can change and DHCP can change. A device set up while offline gets a permanently wrong, IP-derived unique ID. | ⚠️ | Low to fix once #2 is fixed. Raising `ConfigEntryNotReady` removes the fallback path entirely. |
| 16 | Prevent duplicate setup of the same device | QS Bronze `unique-config-entry` | `config_flow.py` never calls `async_set_unique_id` or `_abort_if_unique_id_configured`. Adding the same panel twice creates two entries and two colliding entities. | ❌ | Low. |
| 17 | Test the connection in the config flow before creating the entry | QS Bronze `test-before-configure` | The config flow does **no I/O at all**. It adds `http://` if missing and calls `async_create_entry` at once. A mistyped IP creates a broken entry with no feedback. | ❌ | Low. |
| 18 | Integration creates devices with complete `DeviceInfo` | QS Gold `devices`; HA device registry docs | **No `DeviceInfo` anywhere.** The string does not appear in the repository. The integration creates a bare `climate` entity with no device, so there is no `manufacturer`, `model`, `sw_version`, `connections`, or `suggested_area`. All of it goes into `extra_state_attributes` instead (`hw_firmware`, `net_mac`, `net_ipAddress`, …). | ❌ | Moderate. A real user complaint confirms it: issue #9 asks for "a proper device with sensors". |
| 19 | Entities assigned `EntityCategory` where appropriate | QS Gold `entity-category` | Not used. There is only one entity. | ❌ (n/a in practice) | — |
| 20 | Entities use device classes | QS Gold `entity-device-class` | Not used. Power, energy, temperature and signal strength are all untyped attribute strings, so none reach the Energy dashboard or long-term statistics. | ❌ | Moderate. This is the single most-requested missing feature upstream (issues #3 and #9). |
| 21 | Icon translations rather than hardcoded icons | QS Gold `icon-translations` | `climate.py` hardcodes an `icon` property returning `"mdi:radiator"` / `"mdi:radiator-off"`. | ❌ | Trivial. |

### 3.4 Manifest, translations, and repository structure

| # | Requirement | Source | What `heatit_wifi6` does | Conforms | Remediation cost |
| --- | --- | --- | --- | --- | --- |
| 22 | `manifest.json` `requirements` lists third-party PyPI deps | HA docs, *Integration manifest* | Declares `"requirements": ["aiohttp"]`. `aiohttp` is a Home Assistant **core** dependency and is already present. Listing it is unnecessary, and it is unpinned. hassfest would *not* flag this. The `home-assistant/actions/hassfest` container never passes `--requirements`, so `validate_requirements()` (which holds the forbidden-package and core-package checks) never runs. Pinning with `==` is enforced only `if integration.core`. This is a convention/cleanliness issue, not a CI failure. | ⚠️ | Trivial (delete the key). |
| 23 | `dependencies` lists HA integrations genuinely required | HA docs, *Integration manifest* | Declares `"dependencies": ["network"]`. Nothing in the code uses the `network` integration. hassfest skips dependency-existence checks for custom integrations (`config.specific_integrations`), so this too passes CI while being wrong. | ⚠️ | Trivial (delete). |
| 23b | hassfest enforces manifest **key order**: `domain`, `name`, then alphabetical. It is an *error* in `--action validate` mode, and it applies to custom integrations | `script/hassfest/manifest.py` (`sort_manifest`) | Order is `domain, name, version, config_flow, documentation, dependencies, requirements, codeowners, iot_class, issue_tracker`. Required order after `domain, name` is `codeowners, config_flow, dependencies, documentation, iot_class, issue_tracker, requirements, version`. **Out of order.** | ❌ | Trivial. But it means **hassfest would fail this repo today**, and a passing hassfest is a hard prerequisite for HACS default-list inclusion. |
| 24 | `version` key is required for custom integrations. HACS states releases are *"preferred but not required"*. A repo without releases installs from the default branch | HA docs, *Integration manifest*; HACS *Publish → Integration* | `version` present: `"1.1.2"`. But there are **no git tags and no GitHub releases**. So every HACS install pulls whatever `main` happens to be, and the manifest version matches nothing pinned. Users cannot roll back. | ⚠️ | Not a HACS violation, but it gives up versioning entirely. Directly relevant to the map's open "release & CI hygiene" item. |
| 25 | HACS requires `manifest.json` to contain `domain`, `documentation`, `issue_tracker`, `codeowners`, `name`, `version` | HACS *Publish → Integration* | All six present and well-formed. `iot_class: local_polling` is also correct. | ✅ | — |
| 26 | `strings.json` is the source of translatable strings. `translations/en.json` is generated from it | HA docs, *Internationalization* | **No `strings.json`.** Ships hand-maintained `translations/en.json` and `translations/fi.json` only. hassfest skips a missing `strings.json` (`if not strings_file.is_file(): continue`), so this passes CI. It is a convention gap, not a CI failure. | ❌ | Low. |
| 27 | Exception messages translatable | QS Gold `exception-translations` | No `HomeAssistantError`/`ServiceValidationError` is raised at all. See #12. | ❌ | Moderate. |
| 28 | HACS: you *"must provide brand assets for your integration"* by *"adding a `brand` directory in your repository with at least an `icon.png` file"*. The HACS Action's `brands` check looks for `custom_components/<domain>/brand/icon.png`. Otherwise it falls back to requiring the domain in the `custom` array of `https://brands.home-assistant.io/domains.json` | HACS *Publish → Integration*; `hacs/integration` `validate/brands.py` | Ships `brands/icon.png` + `brands/logo.png`. The folder name is **plural**, so the local-path check misses it. **But the check still passes** via the fallback: `custom_integrations/heatit_wifi6/` already exists in `home-assistant/brands` (four files), and `heatit_wifi6` is listed in `domains.json`'s `custom` array. | ⚠️ | Passes CI by accident. Since HA 2026.3 the `custom_integrations/` folder is **legacy**, and a workflow auto-closes new folders there. The forward-compatible path is a local `custom_components/<domain>/brand/` directory. Correction to an earlier draft of this document: the `heatit` namespace is **not** unclaimed. See §5.3. |
| 29 | *"There must only be one integration per repository, i.e. there can only be one subdirectory to `ROOT_OF_THE_REPO/custom_components/`."* | HACS *Publish → Integration* (verbatim) | Contains **two**: `heatit_wifi6/` and `heatit_wifi6_custom/`, byte-identical except for the `DOMAIN` constant. Both declare `config_flow: true`. | ❌ | Documented rule, **not** code-enforced. HACS finds the integration with `get_first_directory_in_directory(tree, "custom_components")`. That function `break`s on the first directory entry and silently ignores the rest. Only *zero* subdirectories raises. So this is a silent wrong-integration hazard, not a validation failure. Trivial to fix upstream. It is the state of `main` today. |
| 30 | `hacs.json` | HACS publishing docs | Present: `{"name": "HeatIT WiFi6 Thermostat", "render_readme": true}`. Minimal but valid. | ✅ | — |
| 31 | Repository description and topics must be set. Both are **code-enforced** HACS Action checks (`description`, `topics`) | `hacs/integration` `validate/description.py`, `validate/topics.py`; HACS *Publish → Start* | GitHub API returns `"description": null` and `"topics": []`. **Two hard HACS Action failures**: *"The repository has no description"* and *"The repository has no valid topics"*. | ❌ | Trivial to fix. But as of today the HACS Action does not pass. |
| 32 | CI: hassfest action + HACS Action, both passing without `ignore`, are prerequisites for the HACS default list | HACS *Publish → Include*; `hacs/default` `.github/workflows/checks.yml` | **No `.github/` directory at all.** Neither action has ever run. Running them today would fail on `description` and `topics` (row 31) and on hassfest manifest key order (row 23b). | ❌ | Low to add. It would surface the batch above. |
| 32b | HACS Action `license` check: the repo licence must have an **OSI-approved SPDX ID** (added 2026-07, code-enforced but undocumented on the HACS action docs page) | `hacs/integration` `validate/license.py` | MIT, which is on the fast-path allow list. | ✅ | — |
| 32c | HACS **default-list** inclusion requires at least one full GitHub **release** (not merely a tag). Code-enforced by `hacs/default`'s `releases` check | `hacs/default` `scripts/check/releases.py`; HACS *Publish → Include* | **0 releases.** | ❌ | The single hardest default-list blocker: `'<repo>' has no releases`. This is stricter than the general publishing docs, which call releases *"preferred but not required"*. |
| 33 | Test coverage. Bronze requires full config-flow coverage. Silver requires >95% overall | QS Bronze `config-flow-test-coverage`; QS Silver `test-coverage` | **Zero tests.** No `tests/`, no `conftest.py`, no `pytest-homeassistant-custom-component`. | ❌ | High. Nothing here to reuse for the map's testing-strategy ticket (#12). |
| 34 | Strict typing; `py.typed` | QS Platinum `strict-typing` | Essentially untyped. `api.py` annotates three return types (`-> str`, `-> dict`). `climate.py`'s ~30 methods carry **one** annotation (`available -> bool`). No `py.typed`, no mypy config. | ❌ | High. |
| 35 | Common patterns in common modules (`coordinator.py`, `entity.py`) | QS Bronze `common-modules` | No `coordinator.py`, no `entity.py`. All entity logic lives in a single 502-line `climate.py`. | ❌ | High. |

### 3.5 Defects found while reading — independent of convention

These are not style points. They are bugs on code paths we might otherwise copy.

| # | Location | Defect |
| --- | --- | --- |
| D1 | `climate.py` `async_set_temperature` | Calls `self.hass.components.persistent_notification.create(...)`. The `hass.components` accessor **no longer exists on `HomeAssistant`** in current core (verified: no `components` property on the class in `homeassistant/core.py`). On any current HA this line raises `AttributeError` at runtime. It runs whenever a user sets a temperature while the device is OFF. |
| D2 | `api.py` `set_parameter` / `reset_device` | Both test `response.get("status", "Failed") == "Success"`, **capitalised**. The device's own OpenAPI document (vendored in this repo) defines the response enum as lowercase `success` / `failed`, and the Panel's spec agrees. Against a spec-conformant device this comparison **never matches**. So every successful write is logged as an error and returns `{}`, and every caller's `if` fails. |
| D3 | `api.py` `_post` | Sends parameters as a **JSON body** (`session.post(url, json=data)`). The vendored WiFi6 OpenAPI document declares all 25 parameters as `in: query` (verified: 25 × `in: query`, zero `requestBody`). So the code contradicts the spec it ships. It evidently works on real firmware, but that is undocumented, unverified leniency. |
| D4 | `climate.py` `async_set_temperature` | `setattr(self, param, temperature)` writes `self.heatingSetpoint`, an attribute nothing ever reads. The intended target is `self._param_heatingSetpoint`. Dead write. The optimistic update never happens. |
| D5 | `climate.py` `hvac_modes` | Returns a **dynamic** list computed from the *current* mode (`[OFF, COOL]` while cooling, `[OFF, HEAT]` otherwise). HA expects a stable capability list. A changing `hvac_modes` misleads the UI and voice assistants, and makes `HVACMode.COOL` unreachable once the device is in heat. |
| D6 | `climate.py` | No `min_temp` / `max_temp` / `target_temperature_step` properties, even though the device reports its own limits. HA's defaults apply. Confirmed against real user data posted in upstream issue #5: `min_temp: 7, max_temp: 35`. Those are HA's built-in defaults, not the device's documented 5.0–40.0. |
| D7 | `api.py` `_LOGGER` calls | `_LOGGER.error("set_parameter({parameter, value}): %s", str(response))` has literal braces, not an f-string. Several sibling lines mix an f-string with trailing `%s` lazy-logging args, which produces malformed log output. |
| D8 | `climate.py` `_hvac_mode_to_heatit_operatingmode` | Returns `-1` on an unrecognised mode, and the caller POSTs that `-1` to the device without checking. |
| D9 | `climate.py` module scope | `errors = {}` is an unused module-level mutable global. `import homeassistant.helpers.config_validation as cv` is unused. |
| D10 | Vendored spec, `Heatit_WiFi6_OpenAPI_v70.yaml` | Heatit's own document is internally inconsistent. The parameter keyed `internalMinimumTemperatureLimit` declares `name: internalMinTemperature`, so the documented wire name differs from the key used everywhere else. Also `state` is typed `boolean` while its `enum` is the strings `Idle`/`Heating`/`Cooling`. **Relevant beyond this repo: it is direct evidence that Heatit's OpenAPI documents contain errors. That supports the map's decision to treat "the spec says X" and "the device does X" as separate claims.** |

---

## 4. API surface diff — WiFi6 thermostat vs Panel

Sources: the WiFi6 OpenAPI **v7.0.0** document vendored at `custom_components/heatit_wifi6/docs/Heatit_WiFi6_OpenAPI_v70.yaml`, compared with the Panel API **v12.0.0** as transcribed in `.orca/drops/heatit-wifi-panel-ha-integration.md`.

The handoff claims the API surface is *"almost identical"*. The endpoint **shapes** are the same: `GET /api/status`, `POST /api/parameters` with query-string parameters, and `DELETE /api/reset/{factory,settings,kwh}`. The **contents** are not.

### 4.1 Headline numbers

- WiFi6 exposes **25** writable parameters. The Panel exposes **15** (plus read-only `maxLoad`).
- **5** parameters are shared with the same name, type, range and meaning: `heatingSetpoint`, `ecoSetpoint`, `temperatureDisplay`, `activeDisplayBrightness`, `openWindowDetection`.
- That is **20% of the WiFi6 surface** and **33% of the Panel surface**.
- **12** WiFi6 parameters have no Panel counterpart. **3** Panel parameters have no WiFi6 counterpart.

### 4.2 Same name, different meaning — the dangerous class

For these entries, a copied implementation compiles, runs, and gives wrong results.

| Parameter | WiFi6 (v7.0.0) | Panel (v12.0.0) | Consequence of copying |
| --- | --- | --- | --- |
| `sensorMode` | **integer 0–5**: Floor / Internal / Internal+floor-limit / External / External+floor-limit / Power-regulator | **boolean**: `false` = internal sensor, `true` = external wireless sensor | Entirely different domain. The WiFi6 integration's single most-advertised feature **does not apply to the Panel**. That feature is v0.9.4's "current temperature is dynamically based on `sensorMode`", with its `SENSORMODES` lookup table and the `match … case 0 / case 3\|4` dispatch in `async_update`. The Panel has exactly one temperature reading (`roomTemperature`). A copy would map boolean `True` to no case and silently fall through to the default branch. |
| `disableButtons` | **boolean** (`false`/`true`/`0`/`1`) | **integer 0/1/2**: enabled / disabled / lock menu | WiFi6 models this as a switch. The Panel needs a 3-state `select`. A copied boolean mapping silently loses "lock menu" and may write `true` where `2` was meant. |
| `standbyDisplayBrightness` | 1–10 | **0**–10 | A copied `number` entity's `min` is off by one. The Panel's "display off in standby" value becomes unreachable. |

### 4.3 The mode parameter — renamed *and* re-valued

This is the sharpest difference, and it is on the write path.

| | WiFi6 `operatingMode` | Panel `panelMode` |
| --- | --- | --- |
| 0 | OFF | Off |
| 1 | Heating (default) | Heating |
| 2 | **Cooling** | **Eco** |
| 3 | **ECO** | *(does not exist)* |

The parameter is renamed, so a literal copy fails loudly. `operatingMode` gets HTTP 400/422 on a Panel, which is the safe failure. The hazard is the *plausible adaptation*: rename the key to `panelMode` and keep the value map. Then `async_set_preset_mode(PRESET_ECO)` writes `panelMode=3`, which is out of range. And `HVACMode.COOL` writes `panelMode=2`, which silently puts the heater into **Eco** instead of cooling. The Panel has no cooling function at all. `coolingSetpoint` does not exist on it.

The WiFi6 climate code also mixes mode and preset in a way the Panel cannot inherit. `operatingMode=3` (eco) is reported as `HVACMode.HEAT` + `PRESET_ECO`. But `async_set_hvac_mode(HEAT)` writes `operatingMode=1`, which silently clears eco. And `async_set_preset_mode` writes the mode directly, so selecting a preset while the device is OFF turns it on. **These are exactly the semantics [issue #8](https://github.com/Normio/HeatIt-Wifi-Panel/issues/8) must decide, and this prior art gets them wrong.**

### 4.4 Renamed, analogous concept

| Concept | WiFi6 | Panel | Note |
| --- | --- | --- | --- |
| Sensor calibration | `internalCalibration`, `floorCalibration`, `externalCalibration` (3 × −6.0…6.0) | `sensorCalibration` (1 × −6.0…6.0) | Three collapse to one, under a different name. |
| Temperature limits | `internal{Min,Max}`, `floor{Min,Max}`, `external{Min,Max}TemperatureLimit` (6) | `minimumTemperatureLimit`, `maximumTemperatureLimit` (2) | Six collapse to two, under different names. |
| Load sizing | `sizeOfLoad` 0–99 (×100 W; **0 = use power metering**) | `loadLimit` 1–15 (×100 W), bounded by read-only `maxLoad` 4–15 | Same idea, different name, different range, different sentinel. And the Panel's upper bound is **reported by the device at runtime**, so it is a `number` entity whose `max` is dynamic. WiFi6 has no equivalent pattern to copy. |

### 4.5 WiFi6-only — 12 parameters with no Panel counterpart

`sensorValue` (NTC resistance 0–7), `floorMinimumTemperatureLimit`, `floorMaximumTemperatureLimit`, `externalMinimumTemperatureLimit`, `externalMaximumTemperatureLimit`, `floorCalibration`, `externalCalibration`, `regulationMode` (PWM vs hysteresis), `temperatureControlHysteresis` (0.3–3.0), `actionAfterError` (0 or 10–65535 s), `coolingSetpoint`, `powerRegulatorActiveTime` (PWER duty cycle).

Every one of these belongs to a *floor thermostat that drives an external relay or load*. A panel heater has no floor sensor, no user-selectable NTC, no cooling mode, and no relay duty cycle. Roughly half of the WiFi6 integration's surface models a device the Panel is not.

### 4.6 Panel-only — 3 parameters with no WiFi6 counterpart

| Parameter | Shape | Note |
| --- | --- | --- |
| `externalSensorFallback` | boolean | No analogue. |
| `lowTemperatureProtection` | **nested object**: `{ lowTemperatureProtection: 0\|1–10, activeNow: "disabled"\|"Idle"\|"Heating" }` | A low temperature protection feature with a writable threshold and a read-only tri-state status. Both share the outer key name. Awkward to model, and there is **no prior art for it at all**. |
| `maxLoad` | integer 4–15, read-only | Bounds `loadLimit`. |

### 4.7 Status-payload divergences

| Field | WiFi6 | Panel | Consequence |
| --- | --- | --- | --- |
| Network block key | **`network`** (lowercase) | **`Network`** (capital N) | A copied `data.get("network", {})` returns `{}` on the Panel. That is a **silent, total loss of SSID, MAC, IP, signal strength and status**. The MAC loss also breaks `CONNECTION_NETWORK_MAC` in `DeviceInfo`. A pure copy-paste trap with no error. |
| Temperature | `internalTemperature`, `floorTemperature`, `externalTemperature` | `roomTemperature` | Three fields become one, renamed. |
| `state` enum | `Idle` \| `Heating` \| `Cooling` | `Idle` \| `Heating` | The `Cooling` → `HVACAction.COOLING` branch is dead code on a Panel. |
| `parameters.OWD` | `{openWindowDetection, activeNow, activeTime}` | same | ✅ One of the few structures that transfers cleanly. |
| `parameters.lowTemperatureProtection` | absent | nested object | New. |
| `totalConsumption`, `currentPower`, `id`, `name`, `room`, `firmware` | present | present | ✅ Transfer cleanly. |

### 4.8 Verdict on the handoff's premise

**The two devices share the endpoint shapes but not the parameters.** "Almost identical" holds for *how you talk to the device*: URL shapes, query-string writes, write echoes, and `DELETE` resets. It fails for *what you can say*. Only 5 of 25 parameters are identical. The mode parameter is renamed and has new values. The network key has a different case. Roughly half of the WiFi6 surface models floor-heating hardware the Panel does not have.

The differences are concentrated **on the write path**: `panelMode` values, the number of `disableButtons` values, `sensorMode` type. This is the failure the ticket warned about. Two of them (`Network` casing, `panelMode`=2) fail *silently* rather than loudly. This finding is direct input to [#7 the parameter-write contract](https://github.com/Normio/HeatIt-Wifi-Panel/issues/7) and [#8 climate modes and presets](https://github.com/Normio/HeatIt-Wifi-Panel/issues/8).

---

## 5. Concretely reusable candidates

This list does not judge whether we should take them. That is #16's call. Each item is tagged to say whether taking it would trigger the §1 attribution duty.

### 5.1 Knowledge — free, no attribution obligation

| # | What | Why it is worth having |
| --- | --- | --- |
| K1 | **Content-Type workaround.** `api.py` deliberately parses JSON from `response.text()` rather than `response.json()`, with the comment: *"aiohttp `response.json()` require a correct content-type header on the http response. parse json from `response.text()` is immune of content-type header."* | Hard-won device behaviour: Heatit firmware apparently returns JSON with a wrong or missing `Content-Type`. If the Panel does the same, `await response.json()` fails outright. **This belongs in the hardware conformance checklist (#13) as an assumption to verify.** It cannot be derived from the OpenAPI spec. |
| K2 | **Startup congestion with multiple devices.** Upstream issues #4 and #5 document, from several users independently, that polling 5–6 Heatit WiFi devices at the same time on 2.4 GHz at HA restart makes most of them time out and land permanently "unavailable". `atlehogberg` reports 4 of 5 failing consistently. | Real operational evidence that bears directly on the map's open "multi-panel topology" question. The *problem* is credible, but the *fix* in this repo (`asyncio.sleep` in setup) is wrong. The correct answers are `ConfigEntryNotReady` + HA's own retry, a shared session with a connector limit, and generous timeouts. |
| K3 | **`coolingSetpoint` / mode-value collision.** §4.3. | Prevents a specific, silent, plausible bug in our climate implementation. |
| K4 | **Heatit's own specs contain errors.** D10. | Independent support for the map's insistence on a conformance checklist. |
| K5 | **The maintainer's argument against eco-as-preset.** Upstream issue #5: eco is *"a preset rather than a distinct operating mode"*, and HA can manage setpoints centrally without it. `atlehogberg` counters that he wants a device-local fallback setpoint that survives HA or WiFi going down. | A real, spelled-out design debate on exactly the question [#8](https://github.com/Normio/HeatIt-Wifi-Panel/issues/8) must settle. Worth reading both sides. |
| K6 | **Users want energy/power as first-class entities, not attributes.** Upstream issues #3, #9 and PR #8 are all the same request. | Validates the map's "full v1 entity surface" decision against real user demand. |

### 5.2 Code and artefacts — would trigger attribution if copied

| # | What | Assessment as a candidate |
| --- | --- | --- |
| C1 | **The vendored WiFi6 OpenAPI v7.0.0 YAML** (`custom_components/heatit_wifi6/docs/Heatit_WiFi6_OpenAPI_v70.yaml`, 992 lines) | Not the maintainer's work. It is Heatit's document, and the authoritative Panel equivalent is v12.0.0 from Heatit directly. Its value here is **comparative**: it shows how Heatit's spec conventions changed between v7 and v12, and it is the source of the D10 error evidence. Reference material, not a reuse candidate. |
| C2 | **HTTP client shape** (`api.py`, 165 lines) | The method surface (`get_status()`, `set_parameter()`, `reset_device(type)`) is a reasonable shape and close to what the handoff already proposes. But the *implementation* fails on four counts: per-request session creation (§3.2 #8), universal error swallowing (#9), JSON body instead of query string (D3), and the `"Success"` casing bug (D2). The idea is worth ~10 minutes of thought. The code is a liability. |
| C3 | **Config flow** (`config_flow.py`, 41 lines) | 41 lines with no connection test, no `unique_id`, no error handling, and a user-typed `CONF_NAME` that should not exist. There is almost nothing here. [#10](https://github.com/Normio/HeatIt-Wifi-Panel/issues/10) starts from a blank page either way. |
| C4 | **Parameter-to-entity mapping table** | **Does not exist.** There is no `EntityDescription` table anywhere in the repository. Parameters are hand-copied one line at a time into a 38-key `extra_state_attributes` dict. The single most valuable artefact for our purposes is the one thing this prior art does not contain. |
| C5 | **Test setup** | **Does not exist.** Zero tests, no CI. Nothing for [#12](https://github.com/Normio/HeatIt-Wifi-Panel/issues/12) to build on. |
| C6 | **`lvlie`'s Prism-mock CI pipeline.** Described in upstream issue #9. It lives in the `lvlie/heatit_wifi6` fork, *not* in `mattik-gh/main`. It mocks the device from the OpenAPI spec using Stoplight Prism, boots Home Assistant, installs the custom integration, drives it via an injected automation, and asserts the HA log is clean. | **The most interesting single artefact in this repository's orbit**, and it is not in the repository. It targets the map's hardest constraint, "no hardware", by generating a device simulator directly from the spec we already have. Same MIT licence via the fork. Flagged as a candidate for [#12](https://github.com/Normio/HeatIt-Wifi-Panel/issues/12). The author self-describes it as vibe-coded and unreviewed, so it is a *technique* worth evaluating more than a codebase worth importing. This audit has not yet verified it independently. |

### 5.3 Naming and collision

| Question | Finding |
| --- | --- |
| Domain collision | None. `heatit_wifi_panel` vs `heatit_wifi6` are distinct, and the map's choice already anticipated this. |
| Third domain in the wild | `heatit_wifi6_custom` is also shipped and installable from the same repo (§3.4 #29). Any future `heatit_*` naming should assume both exist. |
| HACS default-list name clash | `heatit_wifi6` is **not in the HACS default list** (verified against all 3,262 entries: no `heatit` and no `mattik` substring anywhere), so it holds no reserved name there. "Heatit WiFi Panel" and "HeatIT WiFi6 Thermostat" are distinguishable in any case. |
| **`heatit` is already claimed in core** | **Correction to this document's own first pass.** `heatit` exists in Home Assistant core as a **Z-Wave virtual brand**: `homeassistant/brands/heatit.json` = `{"domain": "heatit", "name": "Heatit", "iot_standards": ["zwave"]}`, with images at `core_brands/heatit/`. This matches the handoff's note that Heatit's official Works-with-HA support is Z-Wave only. But it means the brand namespace is **occupied, not vacant**. hassfest emits a *warning* (not an error) when a custom domain collides with a built-in one. `heatit_wifi_panel` does not collide, so we are clear. The consequence is for grouping, not naming. A future core submission would most naturally extend the existing `heatit` brand rather than create a new one. |
| `home-assistant/brands` | `custom_integrations/heatit_wifi6/` **already exists** (icon/logo at 1× and 2×), and `heatit_wifi6` appears in `domains.json`'s `custom` array. Since HA **2026.3** that folder is **legacy**. A workflow in `home-assistant/brands` auto-closes any PR that adds a new `custom_integrations/` folder. It directs authors to ship `custom_components/<domain>/brand/` locally instead (`icon.png`, optional `logo.png`, `dark_*`, `@2x` variants; icon 1:1, 256×256 / 512×512 hDPI). **So for `heatit_wifi_panel` there is no brands PR to file. We ship the assets in-tree.** That removes an external dependency from the release checklist. |
| Heatit's official presence | Heatit's own "Works with Home Assistant" support is Z-Wave only and occupies the `heatit` brand (above). It does not occupy the WiFi/local-HTTP space. |

---

## 6. Decision deferred

**This document does NOT make the fork / read-and-rewrite / ignore decision.** That decision goes to [issue #16](https://github.com/Normio/HeatIt-Wifi-Panel/issues/16). Issue #16 is blocked on this ticket, on [#2](https://github.com/Normio/HeatIt-Wifi-Panel/issues/2) (current HA integration conventions) and on [#3](https://github.com/Normio/HeatIt-Wifi-Panel/issues/3) (HACS default repository requirements).

### Open questions #16 will need answered

1. **What tier is the target?** Nearly every ❌ in §3 is a Bronze or Silver rule. Whether they count as "modernisation debt" or "irrelevant" depends on the tier the map commits to. That tier is not yet fixed. (#2, #3)
2. **Does the map's "HA core stays viable" bar make §1(a) binding?** If a core PR is a real future plan, the MIT provenance friction and the incomplete copyright chain (§1(b)) carry weight. If core is only a hope, they are noise.
3. **How much of §3 is *this repo* versus *the era*?** #2 should find out when `runtime_data`, `EntityDescription` and `_attr_has_entity_name` became expected. Some findings may show a 2025 integration that was never updated, rather than one written badly.
4. **Is a 20%/33% parameter overlap enough to call it a base?** §4 gives the numbers. Someone must decide what threshold matters. The shared 20% is the *easy* part (setpoints, brightness). The part that differs is the *hard* part (mode semantics, the write contract).
5. **Does the K2 startup-congestion evidence change the multi-panel design?** It is the map's only real-world data point on polling several Heatit devices at once. (#10, #14)
6. **Is C6 (Prism-mock CI) worth a separate evaluation?** It is out of tree, unreviewed, and targets the map's hardest constraint. It may deserve its own ticket whatever #16 decides about the parent repo. (#12)
7. ~~Should we claim the `heatit` brand slug?~~ **Answered, and it removes work from the map.** `heatit` is already a core Z-Wave virtual brand. Since HA 2026.3, custom integrations ship brand assets **in-tree** at `custom_components/<domain>/brand/`. New `custom_integrations/` PRs to `home-assistant/brands` are auto-closed. So the "`home-assistant/brands` PR" listed in the map's *Release & CI hygiene* fog item **is not required**. It becomes a task to author the assets instead. Feeds #3.

---

## Appendix: sources

**Primary — code and repository data.** `mattik-gh/heatit_wifi6` @ `569fc32`, cloned and read in full on 2026-09-07. That covers all Python in `custom_components/heatit_wifi6/` and `custom_components/heatit_wifi6_custom/`, `manifest.json`, `hacs.json`, `LICENSE.md`, `translations/*.json`, `docs/Heatit_WiFi6_OpenAPI_v70.yaml`, and the complete `git log`. Also, via the GitHub API: repository metadata, issues #3–#9 with full comment threads, PRs #1/#2/#7/#8, and the fork list.

**Primary — Home Assistant.**
- Integration Quality Scale and its rule pages: <https://developers.home-assistant.io/docs/core/integration-quality-scale/>, `.../rules/runtime-data`, `.../rules/test-before-setup`, `.../rules/inject-websession`, and the full rule checklist at `.../integration-quality-scale/checklist`
- Entity documentation (`_attr_has_entity_name`, `unique_id`, `should_poll`): <https://developers.home-assistant.io/docs/core/entity/>
- Config entries: <https://developers.home-assistant.io/docs/config_entries_index/>
- Fetching data / `DataUpdateCoordinator`: <https://developers.home-assistant.io/docs/integration_fetching_data/>
- Building a Python library: <https://developers.home-assistant.io/docs/api_lib_index/>
- `home-assistant/core` source, read directly via the GitHub API: `homeassistant/config_entries.py` (the `async_forward_entry_unload` docstring, L2888-2894), `homeassistant/helpers/entity_component.py` (`SCAN_INTERVAL` lookup, L191), `homeassistant/helpers/entity_platform.py`, `homeassistant/core.py` (absence of a `components` accessor)
- `script/hassfest/` validation source (`manifest.py` incl. `sort_manifest`/`validate_version`, `translations.py`, `requirements.py`, `dependencies.py`, `brand.py`, `__main__.py`) and `script/hassfest/docker/entrypoint.sh`; `home-assistant/actions` `hassfest/action.yml`
- `home-assistant/brands`: README, `core_brands/heatit/`, `custom_integrations/heatit_wifi6/`, `homeassistant/brands/heatit.json`, the `close-new-custom-integrations` workflow, and <https://brands.home-assistant.io/domains.json>

**Primary — HACS.** Publishing requirements: <https://hacs.xyz/docs/publish/start/>, <https://hacs.xyz/docs/publish/integration/>, <https://hacs.xyz/docs/publish/include/>. Validation source read directly in `hacs/integration` (`utils/validate.py` schemas, `validate/*.py` check modules, `repositories/integration.py`, `utils/filters.py`) and `hacs/action` (`action.yml`). `hacs/default`: the `integration` file (checked for `heatit`/`mattik`), `.github/workflows/checks.yml`, `scripts/check/releases.py`, `scripts/check/owner.py`.

*Note on divergence:* several HACS rules are enforced in code but missing from the docs pages. The `license` check (OSI-approved SPDX, added 2026-07) and the `integration_manifest` check are not documented on the HACS Action page. `hacs.json` is validated with `PREVENT_EXTRA`, so unknown keys hard-fail. The "one subdirectory" rule is documented but *not* enforced. Where docs and code disagree, this document follows the code and says so.

**Project.** `.orca/drops/heatit-wifi-panel-ha-integration.md` (the Panel API v12.0.0 transcription used for §4). Issues [#1](https://github.com/Normio/HeatIt-Wifi-Panel/issues/1) and [#4](https://github.com/Normio/HeatIt-Wifi-Panel/issues/4).
