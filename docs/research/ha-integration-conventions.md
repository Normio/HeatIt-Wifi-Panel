# Home Assistant integration architecture and conventions

Research resolving [issue #2](https://github.com/Normio/HeatIt-Wifi-Panel/issues/2).
Verified against HA Core `dev` (`2026.10.0.dev0`, `requires-python >=3.14.2`) on 2026-09-07.

**Scope.** What a new, well-built HA integration looks like *today*, and which conventions matter
for `heatit_wifi_panel`. The map sets the bar: a HACS default listing, with HA **core** inclusion
kept possible.

**Method.** Sources were `developers.home-assistant.io` (and its source repo
`home-assistant/developers.home-assistant`), the `homeassistant/core` source tree, and, for HACS
specifics only, `hacs.xyz` plus the `hacs/integration` source. Every claim names the doc page or
source file it came from. Where the published docs and the enforcing code disagree, this note says
so instead of picking one quietly. See [§11](#11-where-the-docs-and-the-code-disagree).

**Worked example.** [`homeassistant/components/airgradient`](https://github.com/home-assistant/core/tree/dev/homeassistant/components/airgradient)
is `iot_class: local_polling`, `integration_type: device`, `quality_scale: platinum`. It polls a
local HTTP device over `aiohttp` with an injected session. It ships write platforms (number, select,
switch, button) next to sensors. It is the closest match in structure to what we are building, and
the reference shape throughout this note.

**Secondary examples.**
[`flexit_bacnet`](https://github.com/home-assistant/core/tree/dev/homeassistant/components/flexit_bacnet)
(silver, `local_polling`, `device`) shows the `climate` platform and the single "main feature" entity.
[`imgw_pib`](https://github.com/home-assistant/core/tree/dev/homeassistant/components/imgw_pib) shows
a coordinator that wraps its payload in a dataclass.

> **A warning about the docs.** Four "Building integrations" pages look like they should be
> authoritative: `config_entries_index`, `integration_fetching_data`, `integration_setup_failures`,
> `asyncio_working_with_async`. They are the *stalest* material on the site.
> `config_entries_index` uses `MyConfigEntry` in five signatures without ever defining it. It never
> mentions `runtime_data`. The main example in `integration_fetching_data` is untyped. It builds the
> coordinator in a *platform's* `async_setup_entry`. The quality-scale rules contradict that, and it
> is a latent bug (§2). **The current conventions live in
> `docs/core/integration-quality-scale/rules/*` and in core source.** This document draws from
> there.

---

## 1. Config entry setup: `runtime_data`, typed `ConfigEntry`, platform forwarding

### The current idiomatic shape

`hass.data[DOMAIN][entry.entry_id]` is **obsolete for new integrations**. `ConfigEntry.runtime_data`
is a bronze-tier requirement
([`runtime-data`](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/runtime-data)).
hassfest enforces it by machine.

From [`airgradient/__init__.py`](https://github.com/home-assistant/core/blob/dev/homeassistant/components/airgradient/__init__.py):

```python
"""The Airgradient integration."""

from airgradient import AirGradientClient

from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .coordinator import AirGradientConfigEntry, AirGradientCoordinator

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.UPDATE,
]


async def async_setup_entry(hass: HomeAssistant, entry: AirGradientConfigEntry) -> bool:
    """Set up Airgradient from a config entry."""

    client = AirGradientClient(
        entry.data[CONF_HOST], session=async_get_clientsession(hass)
    )

    coordinator = AirGradientCoordinator(hass, entry, client)

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: AirGradientConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
```

Details that matter:

- **Order matters.** `async_config_entry_first_refresh()` runs *before* `runtime_data` is assigned
  and *before* platforms are forwarded. On failure it raises `ConfigEntryNotReady`. Setup is then
  retried with nothing partly set up.
- **Do not clear `runtime_data` on unload.** Core does it
  ([`config_entries.py`](https://github.com/home-assistant/core/blob/dev/homeassistant/config_entries.py)):

  ```python
  if result:
      await self._async_process_on_unload(hass)
      if hasattr(self, "runtime_data"):
          object.__delattr__(self, "runtime_data")
  ```

  It is a bare declared attribute with no default. So `hasattr` is the correct existence check.
  Reading it before setup raises `AttributeError`.
- There is **no** `hass.data[DOMAIN].pop(...)` any more.

### Platform forwarding — the older APIs are gone, not merely discouraged

| API | Status in core `dev` |
| --- | --- |
| `hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)` | **The only public forward API.** |
| `async_forward_entry_setup(entry, platform)` (singular) | **Removed.** Only the private `_async_forward_entry_setup` remains. |
| `async_setup_platforms(...)` | **Gone entirely.** It appears nowhere in `config_entries.py`. |
| `async_unload_platforms(entry, PLATFORMS)` | Current. |
| `async_forward_entry_unload(entry, domain)` | Still public. Its own docstring says to prefer `async_unload_platforms`. |

There are two undocumented runtime constraints. `async_forward_entry_setups` raises
`OperationNotAllowed` if called while the setup lock is not held and the entry is not `LOADED`. And
if you do not `await` it inside `async_setup_entry`, `_report_non_awaited_platform_forwards` fires.

### The typed `ConfigEntry` alias — required, and name-constrained

Use a PEP 695 `type` statement. Core gives the class a default type parameter
(`class ConfigEntry[_DataT = Any]`), so bare `ConfigEntry` is still valid.

```python
type AirGradientConfigEntry = ConfigEntry[AirGradientCoordinator]
```

The `runtime-data` rule page states, in an `:::info` admonition:

> If the integration implements `strict-typing`, the use of a custom typed
> `MyIntegrationConfigEntry` is required and must be used throughout.

The `strict-typing` page says the same thing the other way round. The docs put the alias in
`__init__.py`. **Core practice puts it in `coordinator.py`** (airgradient, imgw_pib) and imports it
from there. The `common-modules` rule implies the same. Follow core.

This is machine-checked. From
[`script/hassfest/quality_scale_validation/runtime_data.py`](https://github.com/home-assistant/core/blob/dev/script/hassfest/quality_scale_validation/runtime_data.py):

```python
_ANNOTATION_MATCH = re.compile(r"^[A-Za-z][A-Za-z0-9]+ConfigEntry$")
```

**Consequence for us: the alias must be `HeatitWifiPanelConfigEntry`.** Letters and digits only.
An underscore anywhere in the name fails the check.

The same validator walks the AST and checks that `entry.runtime_data` is *assigned* inside
`async_setup_entry`. Once `strict-typing` is claimed, it also checks that the alias is the second
positional argument of:

| module | functions checked |
| --- | --- |
| `__init__.py` | `async_setup_entry`, `async_unload_entry`, `async_migrate_entry`, `async_remove_entry`, `async_remove_config_entry_device` |
| `diagnostics.py` | `async_get_config_entry_diagnostics`, `async_get_device_diagnostics` |
| every `<platform>.py` | `async_setup_entry` |
| `config_flow.py` | `async_get_options_flow` (first arg) |

### Is `hass.data` still needed?

Only for state that outlives a config entry or exists apart from one. Service actions registered in
`async_setup` still reach per-entry state *through the entry*, not through `hass.data`. From the
[`action-setup`](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/action-setup)
rule:

```python
        if not (entry := hass.config_entries.async_get_entry(call.data[ATTR_CONFIG_ENTRY_ID])):
            raise ServiceValidationError("Entry not found")
        if entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError("Entry not loaded")
        client = cast(MyConfigEntry, entry).runtime_data
```

We have no such state. **`heatit_wifi_panel` should not touch `hass.data` at all.**

---

## 2. `DataUpdateCoordinator`

### Current subclass shape

From [`airgradient/coordinator.py`](https://github.com/home-assistant/core/blob/dev/homeassistant/components/airgradient/coordinator.py):

```python
type AirGradientConfigEntry = ConfigEntry[AirGradientCoordinator]


@dataclass
class AirGradientData:
    """Class for AirGradient data."""

    measures: Measures
    config: Config


class AirGradientCoordinator(DataUpdateCoordinator[AirGradientData]):
    """Class to manage fetching AirGradient data."""

    config_entry: AirGradientConfigEntry
    _current_version: str

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: AirGradientConfigEntry,
        client: AirGradientClient,
    ) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            logger=LOGGER,
            config_entry=config_entry,
            name=f"AirGradient {client.host}",
            update_interval=timedelta(minutes=1),
        )
        self.client = client
        assert self.config_entry.unique_id
        self.serial_number = self.config_entry.unique_id

    @override
    async def _async_setup(self) -> None:
        """Set up the coordinator."""
        try:
            self._current_version = (
                await self.client.get_current_measures()
            ).firmware_version
        except AirGradientError as error:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_error",
                translation_placeholders={"error": str(error)},
            ) from error

    @override
    async def _async_update_data(self) -> AirGradientData:
        try:
            measures = await self.client.get_current_measures()
            config = await self.client.get_config()
        except AirGradientError as error:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_error",
                translation_placeholders={"error": str(error)},
            ) from error
        ...
        return AirGradientData(measures, config)
```

Three things here appear in **none** of the four "Building integrations" doc pages:

1. **The generic parameter** `DataUpdateCoordinator[AirGradientData]`, with a `@dataclass` payload
   instead of a `dict`.
2. **The class-level `config_entry: AirGradientConfigEntry` annotation.** Core's `__init__`
   assigns from a `ConfigEntry | UndefinedType | None` parameter and never annotates the attribute.
   Without this line mypy infers `ConfigEntry | None`, and every access needs a guard.
3. **`@override`** (`from typing import override`). Core's
   [`mypy.ini`](https://github.com/home-assistant/core/blob/dev/mypy.ini) sets
   `enable_error_code = deprecated, explicit-override, ignore-without-code, redundant-self, truthy-iterable`.
   So **every** override must carry it: `_async_update_data`, `_async_setup`,
   `_handle_coordinator_update`, `available`, `async_added_to_hass`, and property overrides on
   entities. This is mandatory in core and documented almost nowhere.

### `config_entry=` — pass it

From [`homeassistant/helpers/update_coordinator.py`](https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/update_coordinator.py):

```python
        if config_entry is UNDEFINED:
            # late import to avoid circular imports
            from . import frame  # noqa: PLC0415

            # It is not planned to enforce this for custom integrations.
            # see https://github.com/home-assistant/core/pull/138161#discussion_r1958184241
            frame.report_usage(
                "relies on ContextVar, but should pass the config entry explicitly.",
                core_behavior=frame.ReportBehavior.ERROR,
                core_integration_behavior=frame.ReportBehavior.ERROR,
                custom_integration_behavior=frame.ReportBehavior.IGNORE,
            )

            self.config_entry = config_entries.current_entry.get()
        else:
            self.config_entry = config_entry
```

Leaving it out is an **error for core integrations** and **silently ignored for custom ones**. In
that case core falls back to a `ContextVar` that only resolves inside the setup call stack. The map
keeps core inclusion open, so pass it. Passing it also has real side effects. It registers
`config_entry.async_on_unload(self.async_shutdown)`. It honours `config_entry.pref_disable_polling`,
which is the user-facing "Enable polling for updates" toggle, so we get that for free. And it names
refresh tasks via `config_entry.async_create_background_task`.

### `_async_setup`

```python
    async def _async_setup(self) -> None:
        """Set up the coordinator.

        Can be overwritten by integrations to load data or resources
        only once during the first refresh.
        """
```

**Called only from `async_config_entry_first_refresh()`**, via `__wrap_async_setup()`. It is *not*
called by `async_refresh()`, `async_request_refresh()`, or scheduled refreshes. Its error handling
decides what you may raise:

```python
        except (
            TimeoutError, requests.exceptions.Timeout, aiohttp.ClientError,
            requests.exceptions.RequestException, urllib.error.URLError,
            UpdateFailed, ConfigEntryNotReady,
        ) as err:
            self.last_exception = err

        except (ConfigEntryError, ConfigEntryAuthFailed) as err:
            self.last_exception = err
            self.last_update_success = False
            raise
```

So `UpdateFailed`, `ConfigEntryNotReady` and network errors are swallowed and become
`ConfigEntryNotReady` (**retry**). `ConfigEntryError` and `ConfigEntryAuthFailed` are **re-raised
at once** (no retry). Anything else is logged with a traceback and still becomes
`ConfigEntryNotReady`.

### `async_config_entry_first_refresh` vs `async_refresh`

| | `async_config_entry_first_refresh` | `async_refresh` |
| --- | --- | --- |
| Calls `_async_setup` | **Yes** | No |
| On failure | Raises `ConfigEntryNotReady`, chained via `__cause__`. **It passes on `translation_domain` / `translation_key` / `translation_placeholders`** | Never raises. Sets `last_update_success = False` |
| Logging | `log_failures=False`. The config entry machinery logs instead, which avoids retry spam | `log_failures=True` |
| `ConfigEntryAuthFailed` | propagates → setup starts reauth | caught → `config_entry.async_start_reauth_if_available(hass)` |
| `ConfigEntryError` | propagates → `SETUP_ERROR` | caught and logged only |
| `UpdateFailed(retry_after=…)` | **ignored** | honoured (one-shot) |

There are two hard preconditions, and both raise `ConfigEntryError` when unmet. The coordinator
must have a `config_entry`, and the entry must be in state `SETUP_IN_PROGRESS`. **So
`async_config_entry_first_refresh()` may only be called from `async_setup_entry` in `__init__.py`**
(or from a platform forwarded during that call). Calling it from a *late* platform forward, after
the entry reaches `LOADED`, raises. This is exactly the latent bug in the `integration_fetching_data`
doc example.

### Exception → HA behaviour mapping

The clearest statement is on the
[`test-before-setup`](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/test-before-setup)
rule:

> When the reason for the failure is temporary (like a temporary offline device), we should raise
> `ConfigEntryNotReady` and Home Assistant will retry the setup later. If the reason for the failure
> is that the password is incorrect or the api key is invalid, we should raise
> `ConfigEntryAuthFailed` […]. If we don't expect the integration to work in the foreseeable future,
> we should raise `ConfigEntryError`.

What core actually does (`config_entries.py`):

| Raised from `async_setup_entry` | Resulting state | Retry | Log level | Side effect |
| --- | --- | --- | --- | --- |
| `ConfigEntryNotReady` | `SETUP_RETRY` | **Yes, exponential** | `info` + `debug` traceback | schedules `_async_setup_again` |
| `ConfigEntryAuthFailed` | `SETUP_ERROR` | No | `warning` + `debug` traceback | `async_start_reauth_if_available` |
| `ConfigEntryError` | `SETUP_ERROR` | No | `logger.exception` | — |
| any other exception | `SETUP_ERROR` | No | `logger.exception` | — |
| returns `False` | `SETUP_ERROR` | No | — | — |

Backoff ladder (`SETUP_RETRY_MAX_WAIT = 600`):

```python
            wait_time = min(2**self._tries * 5, SETUP_RETRY_MAX_WAIT) + (
                randint(RANDOM_MICROSECOND_MIN, RANDOM_MICROSECOND_MAX) / 1000000
            )
```

That gives 5s, 10s, 20s, 40s, 80s, 160s, 320s, then capped at 600s, plus jitter. If HA is not yet
`running`, the retry waits for `EVENT_HOMEASSISTANT_STARTED`.

Placement rule, verbatim from
[`integration_setup_failures`](https://developers.home-assistant.io/docs/integration_setup_failures):

> To avoid doubt, raising `ConfigEntryNotReady` in a platform's `async_setup_entry` is ineffective
> because it is too late to be caught by the config entry setup.

All three exceptions derive from `IntegrationError`. Its `__str__` falls back to
`str(self.__cause__)`. That is why `raise ... from err` matters.

### `UpdateFailed`, `retry_after`, `always_update`

```python
class UpdateFailed(HomeAssistantError):
    """Raised when an update has failed."""

    def __init__(self, *args: Any, retry_after: float | None = None, **kwargs: Any) -> None:
```

`retry_after` is a **one-shot** override of the next interval. It is **ignored during the first
refresh** (core: *"We can only honor a retry_after, after the config entry has been set up"*).
`UpdateFailed` inherits `HomeAssistantError`, so it accepts translation kwargs. That is the modern
style, and it is what the gold `exception-translations` rule wants.

The coordinator already handles these, so **do not catch them yourself**: `TimeoutError`,
`requests.exceptions.Timeout`, `aiohttp.ClientError`, `requests.exceptions.RequestException`,
`urllib.error.URLError`, `OAuth2TokenRequestError`.

`always_update=False` makes the coordinator notify listeners only when the data actually changed:

```python
        if (
            self.always_update
            or self.last_update_success != previous_update_success
            or previous_data != self.data
        ):
            self.async_update_listeners()
```

The payload must implement `__eq__`. A `@dataclass` does. This is worth using for a heater whose
state mostly stays the same between polls.

Polling only runs while there are listeners. The first `async_add_listener` schedules it. Removing
the last listener unschedules it.

### `CoordinatorEntity`

```python
class CoordinatorEntity[
    _DataUpdateCoordinatorT: DataUpdateCoordinator[Any] = DataUpdateCoordinator[
        dict[str, Any]
    ]
](BaseCoordinatorEntity[_DataUpdateCoordinatorT]):
```

Subclass it with the generic bound to your coordinator. Do this on a shared base entity in
`entity.py`:

```python
class AirGradientEntity(CoordinatorEntity[AirGradientCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: AirGradientCoordinator) -> None:
        super().__init__(coordinator)
        ...
```

The base class already provides these. Do **not** re-implement them:

- `should_poll` → `False`
- `available` → `self.coordinator.last_update_success` (satisfies silver `entity-unavailable`)
- `async_added_to_hass` → registers `_handle_coordinator_update` and unregisters on removal
  (satisfies bronze `entity-event-setup`)
- `_handle_coordinator_update` → `self.async_write_ha_state()`
- `async_update` → `async_request_refresh()`, for the generic entity-update service

Override `_handle_coordinator_update` **only** to recompute cached `_attr_*` values. If your
properties read `self.coordinator.data` directly, do not override it at all. If you do override it,
it needs `@callback` and `@override`, and you must call `async_write_ha_state()` yourself.

To extend availability, the `entity-unavailable` rule says: *"be sure to incorporate the
`super().available` value"*:

```python
    @property
    @override
    def available(self) -> bool:
        return super().available and self.identifier in self.coordinator.data
```

**Base-class ordering.** The docs are inconsistent. One page has
`SensorEntity, CoordinatorEntity[...]`, another `CoordinatorEntity, LightEntity`, and a third
`CoordinatorEntity[...]` alone. No page states a rule. Follow core practice. The shared base
entity extends `CoordinatorEntity[…]`. Concrete entities are
`class HeatitSensor(HeatitEntity, SensorEntity)`: coordinator base first, platform mixin second.

---

## 3. Entity conventions

### `_attr_*` vs properties

The docs present three mechanisms and do not rank them outright. But the order is implied in the
["Generic properties" tip](https://developers.home-assistant.io/docs/core/entity):

> Properties should always only return information from memory and not do I/O […] Because these
> properties are always called when the state is written to the state machine, it is important to do
> as little work as possible in the property. To avoid calculations in a property method, set the
> corresponding entity class or instance attribute, or if the values never change, use entity
> descriptions.

So the order is: **entity description (never changes) → `_attr_*` (changes, can be computed at
update time) → property (must be derived on each read)**. `flexit_bacnet/climate.py` is the model.
It has nine `_attr_*` class attributes, and properties only for the four values that come from the
device.

Two mechanical constraints are easy to trip over:

- `_attr_` only works for names in `CACHED_PROPERTIES_WITH_ATTR_`
  ([`helpers/entity.py`](https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/entity.py)).
  Each platform extends the list (`climate` adds `hvac_mode`, `hvac_modes`, `hvac_action`,
  `current_temperature`, `target_temperature`, `temperature_unit`, …). They are `cached_property`
  backed by an `ABCCachedProperties` metaclass. The metaclass clears the cache on `_attr_` write.
- If you define a `@property name` **and** set `_attr_name`, the property wins. Only the base
  class's default implementation reads `_attr_`.
- The docs are explicit: *"If an integration needs to access its own properties it should access the
  property (`self.name`), not the class or instance attribute (`self._attr_name`)."*

### `EntityDescription` dataclasses

Each platform has a description subclass that carries behaviour as callables. From
[`airgradient/number.py`](https://github.com/home-assistant/core/blob/dev/homeassistant/components/airgradient/number.py):

```python
@dataclass(frozen=True, kw_only=True)
class AirGradientNumberEntityDescription(NumberEntityDescription):
    """Describes AirGradient number entity."""

    config_key: str
    value_fn: Callable[[Config], int | None]
    set_value_fn: Callable[[AirGradientClient, int], Awaitable[None]]


DISPLAY_BRIGHTNESS = AirGradientNumberEntityDescription(
    key="display_brightness",
    translation_key="display_brightness",
    entity_category=EntityCategory.CONFIG,
    native_min_value=0,
    native_max_value=100,
    native_step=1,
    native_unit_of_measurement=UnitOfRatio.PERCENTAGE,
    config_key=DISPLAY_BRIGHTNESS_CONFIG,
    value_fn=lambda config: config.display_brightness,
    set_value_fn=lambda client, value: client.set_display_brightness(value),
)
```

The entity is a thin shell:

```python
class AirGradientNumber(AirGradientEntity, NumberEntity):
    """Defines an AirGradient number entity."""

    entity_description: AirGradientNumberEntityDescription

    def __init__(
        self,
        coordinator: AirGradientCoordinator,
        description: AirGradientNumberEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.serial_number}-{description.key}"

    @property
    @override
    def native_value(self) -> int | None:
        return self.entity_description.value_fn(self.coordinator.data.config)

    @exception_handler
    @override
    async def async_set_native_value(self, value: float) -> None:
        await self.entity_description.set_value_fn(self.coordinator.client, int(value))
        await self.coordinator.async_request_refresh()
```

- **`frozen=True, kw_only=True`.** ⚠️ The docs' own example uses `@dataclass(kw_only=True)` without
  `frozen`. Every real core integration uses `frozen=True`. Follow core. The base
  `EntityDescription` is not a plain dataclass at all. It is
  `class EntityDescription(metaclass=FrozenOrThawed, frozen_or_thawed=True)`. Platform subclasses
  are declared `class SensorEntityDescription(EntityDescription, frozen_or_thawed=True)`.
- **Where the tuple lives:** in the platform module, not `const.py`. Both the doc example and
  airgradient do this. `const.py` holds `DOMAIN`, `LOGGER` and plain constants.
- `ClimateEntityDescription` exists but adds **no fields**. Climate is configured entirely via
  `_attr_*`. Do not build a description table for a single climate entity.
- `description.key` is the documented basis for the unique ID.

### `_attr_has_entity_name = True` — mandatory

The docs section header is literally *"`has_entity_name` True (Mandatory for new integrations)"*.
The `False` case is headed *"(Deprecated)"*. It is bronze rule `has-entity-name`, with
*"There are no exceptions to this rule."*

Composition, verbatim:

> - The entity is not a member of a device: `friendly_name = entity.name`
> - The entity is a member of a device and `entity.name` is not `None`: `friendly_name = f"{device.name} {entity.name}"`
> - The entity is a member of a device and `entity.name` is `None`: `friendly_name = f"{device.name}"`

The `entity_id` follows the same pattern (`sensor.nightlight_battery` vs `light.nightlight`).
Entity names *"should start with a capital letter, the rest of the words are lower case"*. Core uses
`device.name_by_user or device.name` for the device half.

**Main-feature entity** (our climate entity):

```python
class MySwitch(SwitchEntity):
    _attr_has_entity_name = True
    _attr_name = None
```

### `_attr_translation_key` — and the precedence trap

Core builds the key path `component.<domain>.entity.<platform>.<translation_key>.name`. In the
translation file that is `entity.<platform>.<translation_key>.name`. The docs are explicit that
*"Localization of entity names is only supported for entities which set the `has_entity_name`
property to `True`"*. They also say a translated name causes `EntityDescription.name` to be ignored.

The resolution order (`helpers/entity.py::_name_internal`) is **not** what most people assume:

```python
    def _name_internal(self, device_class_name, platform_translations):
        if hasattr(self, "_attr_name"):
            return self._attr_name
        if (
            self.has_entity_name
            and (name_translation_key := self._name_translation_key)
            and (name := platform_translations.get(name_translation_key))
        ):
            return self._substitute_name_placeholders(name)
        if hasattr(self, "entity_description"):
            description_name = self.entity_description.name
            if description_name is UNDEFINED and self._default_to_device_class_name():
                return device_class_name
            return description_name
        if self._default_to_device_class_name():
            return device_class_name
        return UNDEFINED
```

⚠️ **`_attr_name` beats `translation_key`, and `_attr_name = None` counts as "set"** (`hasattr` is
`True`). That is exactly why the main-feature idiom works. It also means the `flexit_bacnet`
combination:

```python
class FlexitClimateEntity(FlexitEntity, ClimateEntity):
    _attr_name = None
    _attr_translation_key = "flexit_bacnet"
```

is correct and intended. The name resolves to `None` (device name only). The `translation_key` is
used **only** for state and icon translations. Expecting it to supply a name here would be a bug.

The same key also drives state translations
(`entity.<platform>.<key>.state.<state>`), state-attribute translations
(`entity.<platform>.<key>.state_attributes.<attr>.state.<value>`), unit translations
(`entity.<platform>.<key>.unit_of_measurement`), and icons in `icons.json`.

`translation_placeholders` are substituted with `str.format`. A missing placeholder **raises
`HomeAssistantError`** on non-stable release channels and warns on stable.

Some platforms name themselves from the device class when unnamed. The docs list
binary_sensor/button/number/sensor. The `entity-translations` rule lists
binary_sensor/number/sensor/update. Core actually implements `_default_to_device_class_name()` in
**binary_sensor, button, number, sensor, update, event**. Trust core.

### `entity_category`

`EntityCategory` is a `StrEnum` in `homeassistant.const` with exactly `CONFIG` and `DIAGNOSTIC`.

> Set to `EntityCategory.CONFIG` for an entity that allows changing the configuration of a device
> […] Set to `EntityCategory.DIAGNOSTIC` for an entity that exposes some configuration parameter or
> diagnostics of a device but does not allow changing it, for example, a sensor showing RSSI or MAC
> address.

The only *documented* effect is that *"the entity category is used in, for example,
auto-generated dashboards."* In practice, categorised entities are also moved out of the device
card's main list into Configuration/Diagnostic sections. They are also excluded by default from
voice-assistant exposure. But only the dashboard claim is documented. This is gold rule
`entity-category`. Set it on the description. Precedence is `_attr_entity_category` →
`entity_description.entity_category` → `None`.

`entity_registry_enabled_default=False` is different, and often confused with it. It is gold rule
`entity-disabled-by-default`. It is for noisy diagnostics like RSSI, *"to prevent unneeded
(recorded) state changes or UI clutter"*. AirGradient sets it on its signal-strength sensor.

The primary controls must have **no** category. That means the climate entity and the power/energy
sensors a user actually looks at.

### `_attr_unique_id`

Bronze rule `entity-unique-id`, *"There are no exceptions to this rule."* The
[entity registry doc](https://developers.home-assistant.io/docs/entity_registry_index) gives an
explicit, complete list:

> **Example acceptable sources for a unique ID**
> - Serial number of a device
> - MAC address: formatted using `homeassistant.helpers.device_registry.format_mac`; Only obtain the
>   MAC address from the device API or a discovery handler. […]
> - Latitude and Longitude or other unique Geo Location
> - Unique identifier that is physically printed on the device or burned into an EEPROM
>
> **Unacceptable sources for a unique ID**
> - IP Address
> - Device Name
> - Hostname
> - URL
> - Email addresses
> - Usernames

Also: *"Entities should not include the `domain` […] and platform type […] in their Unique ID as the
system already accounts for these identifiers"*. For a multi-entity device, *"combine the unique
id with unique identifiers for the entities […] `{unique_id}-{sensor_type}`."*

The core form is `self._attr_unique_id = f"{coordinator.serial_number}-{description.key}"`. The
separator (`-` vs `_`) is not standardised. **Pick one and never change it.** Changing it orphans
every entity's registry settings.

The single main-feature entity may use the bare serial (`flexit_bacnet` does). But then you can
never add a second entity without a suffix later. Prefer the suffixed form even for climate.

---

## 4. `DeviceInfo` — **substantially changed in 2026.8**

This is where stale general knowledge is most dangerous. Devices are now owned by **a single config
entry** and at most one subentry
([blog, 2026-07-21](https://developers.home-assistant.io/blog/2026/07/21/device-registry-single-config-entry/)).
A follow-up round of deprecations came in 2026.8
([blog, 2026-08-24](https://developers.home-assistant.io/blog/2026/08/24/device-registry-follow-up-changes/)).

### Current TypedDict

From [`homeassistant/helpers/device_registry.py`](https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/device_registry.py):

```python
class DeviceInfo(TypedDict, total=False):
    """Entity device information for device registry."""

    configuration_url: str | URL | None
    connections: set[tuple[str, str]]
    entry_type: DeviceEntryType | None
    identifiers: set[tuple[str, str]]
    manufacturer: str | None
    model: str | None
    model_id: str | None
    name: str | None
    serial_number: str | None
    suggested_area: str | None
    sw_version: str | None
    hw_version: str | None
    translation_key: str | None
    translation_placeholders: Mapping[str, str] | None
    via_device_id: str
```

These are **gone from the TypedDict entirely**: `via_device` (→ `via_device_id`),
`default_manufacturer`, `default_model`, `default_name`. Using them is now a *typing error*, not a
warning. Core also refuses to accept both `via_device` and `via_device_id`:

```python
    "via_device": ("2027.8.0", "via_device_id"),
```

> Resolve the deprecated via_device to a device id. The identifier is not [unique globally] […]
> This ambiguity is why via_device is deprecated.

⚠️ The **docs still list `created_at` and `modified_at`** in `DeviceInfo`. Core has removed them.
They are deprecated as `async_get_or_create` kwargs, `("2027.9.0", None)`. They were ignored anyway.

### Required fields

```python
    if not device_info.get("connections") and not device_info.get("identifiers"):
        raise DeviceInfoError(
            config_entry.domain, device_info,
            "device info must include at least one of identifiers or connections",
        )
```

**At least one of `identifiers` or `connections` is required.** Everything else is optional. A
device with no `name` now defaults to the config entry title. The old "link / primary / secondary"
device-info classification is removed.

### Identifiers and connections are now scoped per config entry

> A physical device that is supported by several integrations […] is represented by one device entry
> per config entry rather than a single shared device. **Identifiers and connections are unique per
> config entry** […] the registry matches the registration against the existing devices of the same
> config entry, **by identifiers first and then by connections**.

This changes lookups. They must pass the entry id:
`async_get_device_by_identifier((DOMAIN, serial), entry.entry_id)` or
`async_get_device_by_connection((dr.CONNECTION_NETWORK_MAC, mac), entry.entry_id)`. The old
`DeviceRegistry.async_get_device()` is deprecated.

### The reference shape

From [`airgradient/entity.py`](https://github.com/home-assistant/core/blob/dev/homeassistant/components/airgradient/entity.py):

```python
class AirGradientEntity(CoordinatorEntity[AirGradientCoordinator]):
    """Defines a base AirGradient entity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AirGradientCoordinator) -> None:
        super().__init__(coordinator)
        measures = coordinator.data.measures
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.serial_number)},
            manufacturer="AirGradient",
            model=get_model_name(measures.model),
            model_id=measures.model,
            serial_number=coordinator.serial_number,
            sw_version=measures.firmware_version,
            connections={(dr.CONNECTION_NETWORK_MAC, coordinator.serial_number)},
        )
```

- Attached via `_attr_device_info` on the **shared base entity**, built once. The `device_info`
  *property* form still works, but the `__init__` form is current practice. Gate:
  *"Entity device info is only read if the entity is loaded via a config entry and the `unique_id`
  property is defined."*
- Inside an entity, *"prefer `self.device_entry` over looking the device up in the registry."*
- **`format_mac` is applied automatically** inside `connections`. Core's `_normalize_connections`
  does `format_mac(value)` for `CONNECTION_NETWORK_MAC`. You must call `dr.format_mac()` yourself
  only when a MAC goes into a **`unique_id`** or into **`identifiers`**. No normalisation happens
  there. The canonical form is lowercase and colon-separated: `aa:bb:cc:dd:ee:ff`.
- `configuration_url`: the scheme must be one of `http`, `https`, `homeassistant`, and it must have
  a host. Otherwise it raises `ValueError`. `homeassistant://<path>` links inside the HA UI. For us:
  `http://<host>/` if the panel serves a web UI.
- `serial_number`: *"Unlike a serial number in the `identifiers` set, this does not need to be
  unique."*
- `entry_type`: the only value is `DeviceEntryType.SERVICE`. Not us.
- `suggested_area` is **still supported as an input**. It seeds the area at creation and never
  overrides a user's choice. What *is* deprecated is **reading** `DeviceEntry.suggested_area`
  (`@deprecated_function(breaks_in_ha_version="2026.9")`). It is in `RUNTIME_ONLY_ATTRS` and is not
  persisted. Set it. Never read it back.
- `translation_key` / `translation_placeholders` on `DeviceInfo` translate the *device* name via
  `device.<translation_key>.name`. They override any `name` passed.
- **Child devices** (`ChildDeviceInfo`, `parent_device_id`) exist for composite products
  (power strips, multi-gang switches). They are explicitly marked *"a new feature and the design is
  still being finalized. The API and behavior described here may change."* They do not apply to a
  single panel. We should not build on an unstable API.

### Keeping `sw_version` live (firmware drift)

AirGradient updates it from the coordinator with the **current** lookup API:

```python
        if measures.firmware_version != self._current_version:
            device_registry = dr.async_get(self.hass)
            device_entry = device_registry.async_get_device_by_identifier(
                (DOMAIN, self.serial_number), self.config_entry.entry_id
            )
            assert device_entry
            device_registry.async_update_device(
                device_entry.id,
                sw_version=measures.firmware_version,
            )
            self._current_version = measures.firmware_version
```

This answers the *reporting* half of the map's "firmware drift" fog. Feature *gating* on firmware
is a separate question (§12).

### Deprecations to avoid

All of these warn for custom integrations today and raise `RuntimeError` for core. Removal is
2027.8–2027.9.

| Deprecated | Use instead |
| --- | --- |
| `DeviceInfo(via_device=...)` | `via_device_id=<device id str>`. Get it from `dr.async_get_device_id_by_identifier(hass, (DOMAIN, serial), config_entry_id=...)`, which raises `ValueError` if absent |
| `homeassistant.const.ATTR_VIA_DEVICE` | literal `"via_device_id"` |
| `DeviceRegistry.async_get_device(...)` | `async_get_device_by_identifier(...)` / `async_get_device_by_connection(...)` |
| `DeviceEntry.config_entries`, `.primary_config_entry` | `dr.async_get_device_and_config_entry_for_domain(hass, device_id, domain=DOMAIN)` |
| `async_update_device(merge_connections=/merge_identifiers=)` | `new_connections=` / `new_identifiers=` (pass the full desired set) |
| `registry.devices.get(id)` / `.values()` / `id in registry.devices` | `registry.async_get(id)`. To iterate, use `for device in registry.devices` |
| `default_manufacturer` / `default_model` / `default_name` | `manufacturer` / `model` / `name` |
| `DeviceRegistry.async_is_composite_device_id()` | two `async_get` calls, one with and one without `include_composite_devices=False` |
| `created_at` / `modified_at` kwargs | remove them. They were ignored |

Also new: an entity that attaches a device **must** have a `unique_id` and belong to a config entry.
Violations drop the device link at once and will raise from 2027.8.

To let users delete the device from the UI, implement this in `__init__.py`:

```python
async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
```

---

## 5. Translations — `strings.json` vs `translations/en.json`

This has a clear answer. **It differs between core and custom integrations, and the docs now warn
against the core shape in a custom component.**

### Mechanism

At runtime HA loads **only** `<integration>/translations/<lang>.json`. From
[`homeassistant/helpers/translation.py`](https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/translation.py):

```python
        files_to_load: dict[str, pathlib.Path] = {
            domain: integration.file_path / "translations" / file_name
            for domain in components
            ...
        }
```

Nothing reads `strings.json` at runtime.

### Core integrations

Developers write `strings.json`. `translations/*.json` is generated (`python3 -m script.translations
develop` locally, Lokalise in CI) and is **gitignored**. Core's `.gitignore` contains
`homeassistant/components/*/translations`. `airgradient/` on GitHub has `strings.json` and
`icons.json` but no `translations/` directory.

### Custom integrations — the opposite, and explicitly so

From [`docs/internationalization/custom_integration`](https://developers.home-assistant.io/docs/internationalization/custom_integration),
verbatim:

> :::caution Strings.json vs. Translations
> **Do not use `strings.json` for custom components.**
>
> The `strings.json` file and the placeholder syntax (for example,
> `[%key:common::config_flow::data::email%]`) are **build-time features** used only by Home
> Assistant Core.
>
> Custom integrations do not run through the internal translation build script. You must manually
> create the `translations/en.json` file and include the full, flat English text for every key. If
> you use `strings.json` or placeholders, your config flow will fail to load translations and show
> raw keys (for example, `username` rather than the translated value `Enter Username`).
> :::

**This contradicts the common advice to "just copy strings.json to translations/en.json".** A
core-shaped `strings.json` is full of `[%key:common::...%]` references. Nothing resolves them at
runtime. A copy would ship literal `[%key:...%]` strings into the UI.

One wrinkle: hassfest *does* still schema-validate a `strings.json` if one is present. In
custom-integration mode it also adds `translations/en.json` to the validated set. From
[`script/hassfest/translations.py`](https://github.com/home-assistant/core/blob/dev/script/hassfest/translations.py):

```python
    strings_files = [integration.path / "strings.json"]

    # Also validate translations for custom integrations
    if config.specific_integrations:
        # Only English needs to be always complete
        strings_files.append(integration.path / "translations/en.json")
```

**Recommendation for `heatit_wifi_panel`:** write `translations/en.json` as the single source of
truth. Expand it fully, with **no `[%key:...%]` references**. Do not ship a `strings.json`. If we
later prepare a core PR, we generate `strings.json` *from* `en.json` at that point and add
`[%key:common::...%]` references as an optimisation. The two files differ in content, not just in
location. So keeping both in parallel is a trap. (This changes the map's "Not yet specified"
assumption. See §12.)

### Key nesting

This combines `airgradient/strings.json`, the i18n doc, and the hassfest schema:

```json
{
  "config": {
    "flow_title": "{model}",
    "step": {
      "user": {
        "title": "Optional; the integration name is used if omitted",
        "description": "Markdown shown with the step.",
        "data": { "host": "Host" },
        "data_description": { "host": "The hostname or IP address of the panel." },
        "sections": { "advanced": { "name": "Advanced options" } }
      }
    },
    "error":    { "cannot_connect": "Failed to connect" },
    "abort":    { "already_configured": "Device is already configured" },
    "progress": { "slow_task": "Shown for async_show_progress" },
    "create_entry": { "default": "Shown in the success dialog" }
  },
  "options":           { "…": "same format as config" },
  "config_subentries": { "subentry_type": { "…": "same format as config" } },
  "entity": {
    "sensor": {
      "power": {
        "name": "Power",
        "state": { "idle": "Idle" },
        "state_attributes": { "mode": { "state": { "eco": "Eco" } } },
        "unit_of_measurement": "steps"
      }
    }
  },
  "device":     { "panel": { "name": "Panel with {n} zones" } },
  "exceptions": { "communication_error": { "message": "Error talking to the panel: {error}" } },
  "issues":     { "cold_tea": { "title": "…", "description": "…" } },
  "selector":   { "mode": { "options": { "off": "Off" } } },
  "services":   { "set_speed": { "name": "…", "description": "…", "fields": { "…": {} } } }
}
```

- Entity names: `entity.<platform>.<translation_key>.name`
- Entity states: `entity.<platform>.<translation_key>.state.<state>`. State keys must be
  `snake_case`.
- Exception messages: `exceptions.<key>.message`, matched by
  `HomeAssistantError(translation_domain=DOMAIN, translation_key=..., translation_placeholders=...)`.
  Core strips a trailing period from the message.
- `data_description` (per-field helper text) is used throughout core. It is a documented
  **subcheck of the bronze `config-flow` rule**. But it is missing from the i18n page's key table.

### Icons live in `icons.json`

Gold rule `icon-translations`. The keys follow the same pattern as entity translations:

```json
{
  "entity": {
    "number": { "display_brightness": { "default": "mdi:brightness-percent" } },
    "sensor": {
      "battery_level": {
        "default": "mdi:battery-unknown",
        "range": { "0": "mdi:battery-outline", "50": "mdi:battery-50", "100": "mdi:battery" }
      }
    }
  }
}
```

Both `state`-keyed and `range`-keyed variants are supported. For range, the highest key ≤ value
wins. State icons win over range icons. hassfest (`script/hassfest/icons.py`) enforces `mdi:`
prefixes and numeric, **ascending** range keys. It rejects a state icon identical to its `default`.

`icons.json` is **not** a build-time file. It works in custom integrations as-is.

`_attr_icon` and the `icon` property are **discouraged but not deprecated**. The entity doc's
attribute table says *"Using this property is not recommended"*. Icon translations are *"the
preferred way"*. The property is still the only option when the icon depends on logic outside the
entity's own state. The docs say: *"as this property is a method, it is possible to return
different icons based on custom logic unlike with icon translations."*

---

## 6. Integration quality scale

### The authoritative rule list — 54 rules

The docs' index page does **not** list them (§11). Two sources agree exactly:
[`script/hassfest/quality_scale.py::ALL_RULES`](https://github.com/home-assistant/core/blob/dev/script/hassfest/quality_scale.py)
and
[`docs/core/integration-quality-scale/_includes/tiers.json`](https://github.com/home-assistant/developers.home-assistant/blob/master/docs/core/integration-quality-scale/_includes/tiers.json).

**Bronze (20)**
`action-setup`, `appropriate-polling`, `brands`, `common-modules`, `config-flow`,
`config-flow-test-coverage`, `dependency-transparency`, `docs-actions`, `docs-conditions`,
`docs-high-level-description`, `docs-installation-instructions`, `docs-removal-instructions`,
`docs-triggers`, `entity-event-setup`, `entity-unique-id`, `has-entity-name`, `runtime-data`,
`test-before-configure`, `test-before-setup`, `unique-config-entry`

**Silver (10)**
`action-exceptions`, `config-entry-unloading`, `docs-configuration-parameters`,
`docs-installation-parameters`, `entity-unavailable`, `integration-owner`, `log-when-unavailable`,
`parallel-updates`, `reauthentication-flow`, `test-coverage` (>95%)

**Gold (21)**
`devices`, `diagnostics`, `discovery`, `discovery-update-info`, `docs-data-update`, `docs-examples`,
`docs-known-limitations`, `docs-supported-devices`, `docs-supported-functions`,
`docs-troubleshooting`, `docs-use-cases`, `dynamic-devices`, `entity-category`,
`entity-device-class`, `entity-disabled-by-default`, `entity-translations`, `exception-translations`,
`icon-translations`, `reconfiguration-flow`, `repair-issues`, `stale-devices`

**Platinum (3)**
`async-dependency`, `inject-websession`, `strict-typing`

Slugs use **hyphens**. Each has a page at
`https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/<slug>/`.

`docs-triggers` and `docs-conditions` were **added to bronze on 2026-07-01**. That is recent enough
that most third-party checklists predate them.

The bronze `config-flow` rule carries two subchecks. They are not separate yaml keys: *"Uses
`data_description` to give context to fields"* and *"Uses `ConfigEntry.data` and
`ConfigEntry.options` correctly"*.

Seven rules have automated validators: `config-flow`, `runtime-data`, `test-before-setup`,
`unique-config-entry`, `discovery`, `reconfiguration-flow`, `strict-typing`. A human reviews the
rest at core-PR time.

Beyond the four scaled tiers there are four special tiers: `no_score`, `internal`, `legacy`,
`custom`. Gold is the required level for the "Works with Home Assistant" program. An integration can
be **downgraded** (e.g. to bronze) if it loses its active code owner. `no_score` cannot be assigned
to new integrations.

### `quality_scale.yaml` format

```python
SCHEMA = vol.Schema({
    vol.Required("rules"): vol.Schema({
        vol.Required(rule.name): vol.Any(
            vol.In(["todo", "done"]),
            vol.Schema({vol.Required("status"): vol.In(["todo", "done"]),
                        vol.Required("comment"): str}),
            vol.Schema({vol.Required("status"): "exempt",
                        vol.Required("comment"): str}),
        )
        for rule in ALL_RULES
    })
})
```

- There is exactly one top-level key, `rules`. **All 54 rule keys are `vol.Required`**, even the
  `todo` ones.
- Values are bare `todo` / `done`, or a mapping with `status` + `comment`. `exempt` **must** use
  the mapping form and **must** carry a comment.
- The file lives at `<integration>/quality_scale.yaml`. The `# Bronze` / `# Silver` comment
  headers are convention, not schema.
- The declared `quality_scale` in `manifest.json` must be backed by every rule at that tier **and
  all tiers below** being `done` or `exempt`.

### **The catch: hassfest does not validate it for custom integrations**

```python
def validate_iqs_file(config: Config, integration: Integration) -> None:
    """Validate quality scale file for integration."""
    if not integration.core:
        return
```

`Integration.core` is true only under `config.core_integrations_path`. A custom component run
through the hassfest GitHub Action is never "core". So `quality_scale.yaml` is **never parsed** for
us. There is no error if it is absent, and no error if it is wrong.

It is still worth writing. It is the exact checklist a core PR is graded against, and the map's bar
is "keep core inclusion viable". But nothing in our CI will catch drift. We grade it by hand or
write our own check.

The manifest `quality_scale` **key** *is* validated for custom integrations, because it is on the
shared schema. It is limited to `bronze|silver|gold|platinum|custom|no_score|internal|legacy`.
hassfest also enforces that **any integration declaring silver or higher has non-empty
`codeowners`**.

New **core** integrations *"are required to at least reach the Bronze tier"*. So bronze is the floor
for the core-viability constraint, not a goal.

### Rules with direct bearing on our design

- **`appropriate-polling`**: *"an appropriate polling interval that will serve the majority of
  users"*. There is no fixed number and no enforced minimum for coordinators. (The 5-second floor on
  `integration_fetching_data` applies to platform `SCAN_INTERVAL`, not `update_interval`.)
  AirGradient uses `timedelta(minutes=1)` for a local sensor. A wall heater changes slowly. We must
  justify any poll interval faster than about 30s.
- **`parallel-updates`**, verbatim:

  > When using a coordinator, you are already centralizing the data updates. This means you can set
  > `PARALLEL_UPDATES = 0` for read-only platforms (`binary_sensor`, `sensor`, `device_tracker`,
  > `event`) […] A coordinator only centralizes the inbound data updates; it does not limit outbound
  > action calls.

  So use `0` on `sensor` / `binary_sensor`, and `1` on every platform that **writes** (`climate`,
  `number`, `switch`, `select`, `button`). AirGradient does exactly this. This matters for a small
  HTTP device that handles writes one at a time.
- **`common-modules`**: the coordinator **must** be in `coordinator.py`. The base entity **must** be
  in `entity.py`.
- **`log-when-unavailable`**: raising `UpdateFailed` satisfies this on its own. The coordinator
  logs once per transition.
- **`docs-*`** (11 rules across bronze/silver/gold) all require a page in the `home-assistant.io`
  docs repo. **A HACS-only integration cannot reach them.** This is the single largest block of
  rules we cannot honestly claim. It decides the tier question (§12).
- **`inject-websession`** (platinum): pass `session=async_get_clientsession(hass)` into the client.
  Never let it create its own session.
- **`strict-typing`** (platinum) also requires that **every** manifest `requirement` ships a
  `py.typed` marker or has a `types-*` stubs package
  ([`quality_scale_validation/strict_typing.py`](https://github.com/home-assistant/core/blob/dev/script/hassfest/quality_scale_validation/strict_typing.py)).
  It also needs a listing in core's `.strict-typing` file (core-only). The first half limits how we
  package the API client (§12).

---

## 7. `manifest.json`

Doc: [creating_integration_manifest](https://developers.home-assistant.io/docs/creating_integration_manifest).
Enforcement: [`script/hassfest/manifest.py`](https://github.com/home-assistant/core/blob/dev/script/hassfest/manifest.py).

```python
CUSTOM_INTEGRATION_MANIFEST_SCHEMA = INTEGRATION_MANIFEST_SCHEMA.extend(
    {
        vol.Required("documentation"): vol.All(vol.Url(), custom_documentation_url),
        vol.Optional("version"): vol.All(str, verify_version),
        vol.Optional("issue_tracker"): vol.Url(),
        vol.Optional("import_executor"): bool,
    }
)
```

Both schemas default to `PREVENT_EXTRA`. **Unknown keys are an error.**

### Required-key matrix

| Key | Core | Custom (hassfest) | HACS default listing |
| --- | --- | --- | --- |
| `domain` | required (must equal directory name) | required | **required** |
| `name` | required | required | **required** |
| `documentation` | required. Must start with `https://www.home-assistant.io/integrations` | required. Must **not** start with that | **required** (any URL) |
| `codeowners` | required (non-empty if `quality_scale >= silver`) | required | **required** (list) |
| `version` | **must be omitted** | schema says optional, but `validate_version()` hard-errors with *"No 'version' key in the manifest file."* So it is **required** | **required**. AwesomeVersion must be able to parse it |
| `iot_class` | required unless the domain is exempt | same | not checked |
| `issue_tracker` | **must be omitted** (auto-generated) | optional | **required** |
| `integration_type` | optional, default `hub`. Required for core integrations with a config flow | optional, default `hub` | not checked |

⚠️ **HACS requires `issue_tracker`, and core forbids it.** Any repo that aims at core inclusion
needs a manifest edit at contribution time. At the same time it must drop `version` and repoint
`documentation`. This is worth recording as a known migration step.

Keys must be sorted: `domain`, `name`, then alphabetical. Otherwise hassfest says *"Manifest keys
are not sorted correctly"*.

### Value enumerations

`iot_class` is one of `assumed_state`, `calculated`, `cloud_polling`, `cloud_push`,
`local_polling`, `local_push`. **Ours is `local_polling`**: *"Offers direct communication with
device. Polling the state means that an update might be noticed later."*

`integration_type` is one of `device`, `entity`, `hardware`, `helper`, `hub`, `service`, `system`,
`virtual`. **Ours is `device`**: *"Provides a single device like, for example, ESPHome."* The docs
say `entity`, `hardware` and `system` "should generally not be used". `virtual` *"can only be
provided by Home Assistant Core and not by custom integrations"*.

### Other keys

- `config_flow: true`: hassfest hard-errors if `config_flow.py` is missing. Discovery-based flows
  must set a unique ID. That is an **error** for core and a **warning** for custom.
- `single_config_entry: true` forbids more than one entry. **It must be absent for us.** The map
  wants multi-panel.
- `requirements`: pinned `==` strings. Git URLs are supported. *"Custom integrations should only
  include requirements that are not required by the Core `requirements.txt`."*
- `dependencies` / `after_dependencies`: *"Custom integrations may specify both built-in and custom
  integrations."*
- `loggers`: the logger names the requirements use for `getLogger`, for the log-filter UI.
- Discovery: `zeroconf`, `dhcp`, `ssdp`, `bluetooth`, `usb`, `homekit`, `mqtt`.
  ⚠️ The `zeroconf` matcher fields `macaddress`, `model` and `manufacturer` are wrapped in
  `cv.deprecated(...)`. They are still accepted, but prefer `properties` / `name` filters.
- **Undocumented-but-valid keys** (missing from the manifest doc page, present in the schema):
  `disabled` (str), `import_executor` (bool, custom-only), `preview_features` (documented only under
  [Home Assistant Labs](https://developers.home-assistant.io/docs/development/labs)). The schemas
  are `PREVENT_EXTRA`, so the doc page is not a complete key list in *either* direction.

### `version` is a hard runtime requirement

From [`homeassistant/loader.py`](https://github.com/home-assistant/core/blob/dev/homeassistant/loader.py):

```python
            if integration.version is None:
                _LOGGER.error(
                    "The custom integration '%s' does not have a version key in the"
                    " manifest file and was blocked from loading. …"
                )
                return None
```

It must also parse under one of `CALVER`, `SEMVER`, `SIMPLEVER`, `BUILDVER`, `PEP440`. Otherwise it
is blocked the same way. Keep it in sync with the GitHub release tag. HACS reads the tag on its own.

### `import_executor`

The loader warns for any integration without it:

```python
            if not integration.import_executor:
                _LOGGER.warning(IMPORT_EVENT_LOOP_WARNING, integration.domain)
```

> "We found an integration %s which is configured to to import its code in the event loop. This
> component might cause stability problems, be sure to disable it if you experience issues with
> Home Assistant"

Set `"import_executor": true`.

### Target manifest

```json
{
  "domain": "heatit_wifi_panel",
  "name": "Heatit WiFi Panel",
  "codeowners": ["@Normio"],
  "config_flow": true,
  "documentation": "https://github.com/Normio/HeatIt-Wifi-Panel",
  "import_executor": true,
  "integration_type": "device",
  "iot_class": "local_polling",
  "issue_tracker": "https://github.com/Normio/HeatIt-Wifi-Panel/issues",
  "requirements": [],
  "version": "0.1.0"
}
```

---

## 8. File structure

Doc: [creating_integration_file_structure](https://developers.home-assistant.io/docs/creating_integration_file_structure).
The documented bare minimum is only `manifest.json` + `__init__.py`. Everything else depends on a
condition or a rule.

```
custom_components/heatit_wifi_panel/
├── __init__.py            # REQUIRED — async_setup_entry / async_unload_entry / PLATFORMS
├── manifest.json          # REQUIRED
├── config_flow.py         # REQUIRED iff manifest has "config_flow": true (hassfest error)
├── const.py               # convention — DOMAIN, LOGGER, plain constants
├── coordinator.py         # HeatitWifiPanelConfigEntry alias + coordinator   [common-modules]
├── entity.py              # base CoordinatorEntity + DeviceInfo              [common-modules]
├── diagnostics.py         # async_get_config_entry_diagnostics               [gold: diagnostics]
├── icons.json             #                                                  [gold: icon-translations]
├── quality_scale.yaml     # never validated for custom integrations — self-tracking only
├── translations/
│   └── en.json            # REQUIRED at runtime; fully expanded, no [%key:...%]
├── brand/                 # NEW since 2026.3 — see §9
│   ├── icon.png
│   └── logo.png
├── climate.py
├── sensor.py
├── binary_sensor.py
├── switch.py
├── number.py
├── select.py
└── button.py
```

There is no `strings.json` (§5). Add `services.yaml` only if we register service actions. The map
currently implies we do not.

`diagnostics.py`, following the gold rule and airgradient:

```python
async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: AirGradientConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    return asdict(entry.runtime_data.data)
```

Use `async_redact_data(entry.data, TO_REDACT)` for anything sensitive in `entry.data`.

---

## 9. HACS and brand assets

### Brand assets — **the `home-assistant/brands` PR is no longer the mechanism for custom integrations**

This is the most often repeated stale instruction. The brands repo README says so itself:

> `custom_integrations`: Contains images for custom integrations (custom components). **Legacy
> folder: Since HA 2026.3.0, custom components can include their brand icons directly.**

— [`home-assistant/brands` README](https://github.com/home-assistant/brands/blob/master/README.md)

Ship them inside the component instead
([blog, 2026-02-24](https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api)):

```
custom_components/heatit_wifi_panel/
└── brand/
    ├── icon.png
    └── logo.png
```

Supported filenames are `icon.png`, `dark_icon.png`, `logo.png`, `dark_logo.png`, and `@2x`
variants. HA serves them via `/api/brands/integration/{domain}/{image}`. **Local brand images take
priority over the CDN.** Frontend code no longer fetches `brands.home-assistant.io` directly.

HACS does the same. Its default-listing brands check looks for `brand/icon.png` first and only then
falls back to the brands repo (`custom_components/hacs/validate/brands.py`,
[HACS docs](https://www.hacs.xyz/docs/publish/integration/)).

The image spec is still set by the brands README:

- PNG, compressed/optimised, interlaced preferred, transparency preferred, trimmed of empty edges.
- **Icon**: 1:1 square, exactly **256×256** (`@2x`: **512×512**).
- **Logo**: landscape preferred. Shortest side **128–256 px** (`@2x`: **256–512 px**).
- If the logo is square, ship only the icon. It is used as the logo fallback.
- **Custom integrations must not use Home Assistant branded images.**

A PR to `home-assistant/brands` (`core_integrations/<domain>/`) is still required for **core**
submission. That is what the bronze `brands` rule refers to. ⚠️ That rule page has not been updated
to mention the local `brand/` directory. That is defensible, since the rule is core-scoped.

### Repository requirements

From [hacs.xyz/docs/publish/start](https://www.hacs.xyz/docs/publish/start/) and
[/publish/integration](https://www.hacs.xyz/docs/publish/integration/):

- A public GitHub repository, with a **description**, **issues enabled**, and **GitHub topics** set.
- A **README** with usage information.
- `hacs.json` in the **repository root**.
- *"There must only be one integration per repository"*. That means exactly one subdirectory under
  `custom_components/`. *"If there are more than one, only the first one will be managed."*
- All integration files must live under `custom_components/<domain>/`.

### `hacs.json`

`HACS_MANIFEST_JSON_SCHEMA` validates it with **`extra=vol.PREVENT_EXTRA`**. Unknown keys fail.

| Key | Type | Required | Notes |
| --- | --- | --- | --- |
| `name` | string | **yes** | display name in the HACS UI |
| `homeassistant` | string | no | minimum HA version. Append `b0` to allow betas |
| `hacs` | string | no | minimum HACS version |
| `country` | string | no | ISO 3166-1 alpha-2 |
| `content_in_root` | bool | no | not for us |
| `zip_release` / `filename` | bool / string | no | `zip_release` without `filename` is a hard failure |
| `hide_default_branch` | bool | no | |
| `persistent_directory` | string | no | path kept safe across upgrades |

Minimal:

```json
{
  "name": "Heatit WiFi Panel",
  "homeassistant": "2026.8.0"
}
```

Pin `homeassistant` to whatever floor the device-registry APIs in §4 require.

⚠️ `render_readme` survives in the schema but was removed from the docs on purpose. Do not use it.
`country` is documented as a string, but the doc's own example passes a list. The validator accepts
both.

### Getting into the HACS **default** list

From [hacs.xyz/docs/publish/include](https://www.hacs.xyz/docs/publish/include/):

- *"Only the owner or a major contributor of a repository can submit a pull request."*
- Custom integrations that override or beta-test a core integration are **not accepted**.
- Two GitHub Actions must pass **without any errors or ignores**:

  ```yaml
  # .github/workflows/validate.yml
  name: Validate
  on:
    push:
    pull_request:
    schedule:
      - cron: "0 0 * * *"
    workflow_dispatch:
  permissions: {}
  jobs:
    validate-hacs:
      runs-on: "ubuntu-latest"
      steps:
        - name: HACS validation
          uses: "hacs/action@main"
          with:
            category: "integration"
    validate-hassfest:
      runs-on: "ubuntu-latest"
      steps:
        - uses: "actions/checkout@v4"
        - uses: "home-assistant/actions/hassfest@master"
  ```

  The `hacs/action` `ignore:` input **must not be used** for a default-list submission. Pinning
  `hacs/action@xx.xx.x` plus dependabot is recommended over `@main`.
- *"Create a new GitHub release (**not just a tag, a full release**) after the actions run
  successfully."* HACS reads the tag name of the latest **release** to set the remote version.
  Publishing tags alone is not enough.
- Then add `Normio/HeatIt-Wifi-Panel` **alphabetically** to
  [`hacs/default/integration`](https://github.com/hacs/default/blob/master/integration).
- Expectation, verbatim: *"new additions still take months to be reviewed and included."*

Automated checks on review: `brands`, `manifest`, `hacs-validation`, `hacsjson`, `archived`,
`releases`, `owner`, `repository` (description + issues + topics), `lint jq`, `lint sorted`.

⚠️ **Undocumented check.** `hacs/integration` added `custom_components/hacs/validate/license.py` on
**2026-07-04**. It requires a GitHub-detected license with a valid, **OSI-approved** SPDX id
(fast path: `Apache-2.0`, `BSD-2-Clause`, `BSD-3-Clause`, `CDDL-1.0`, `EPL-2.0`, `GPL-2.0`,
`GPL-3.0`, `LGPL-2.1`, `LGPL-3.0`, `MIT`, `MPL-2.0`). `NOASSERTION` or a missing license fails.
Forks are rejected. Its `more_info` link points at an anchor that **does not exist** in the docs.
**Ship an OSI-approved `LICENSE` file.** This repo already has one. Confirm GitHub detects it.

### What hassfest actually runs for us

The action runs `ghcr.io/home-assistant/hassfest`. It finds manifests only at
`custom_components/*/manifest.json` (depth exactly 2) or `./manifest.json`. Then it runs
`--action validate --integration-path …`, which is `config.specific_integrations` mode. It **errors
out if no integration is found**. Plugins active in that mode include `manifest`, `translations`,
`icons`, `config_flow`, `dependencies`, `requirements`, `json`, `codeowners`, `integration_type`,
`services`, `zeroconf`, `dhcp`, `ssdp`, `usb`, `bluetooth`, `quality_scale` (which skips itself for
non-core), and others.

---

## 10. Config flow

`airgradient/config_flow.py` is the full modern shape. It has a user step, zeroconf discovery, and
reconfigure. All three share one handler:

```python
class AirGradientConfigFlow(ConfigFlow, domain=DOMAIN):

    @override
    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input:
            session = async_get_clientsession(self.hass)
            self.client = AirGradientClient(user_input[CONF_HOST], session=session)
            try:
                current_measures = await self.client.get_current_measures()
            except AirGradientError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(
                    current_measures.serial_number, raise_on_progress=False
                )
                if self.source == SOURCE_USER:
                    self._abort_if_unique_id_configured()
                if self.source == SOURCE_RECONFIGURE:
                    self._abort_if_unique_id_mismatch()
                ...
                if self.source == SOURCE_USER:
                    return self.async_create_entry(
                        title=current_measures.model,
                        data={CONF_HOST: user_input[CONF_HOST]},
                    )
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(),
                    data={CONF_HOST: user_input[CONF_HOST]},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input) -> ConfigFlowResult:
        """Handle reconfiguration."""
        return await self.async_step_user()
```

Conventions in play:

- Bronze `test-before-configure`: actually talk to the device before creating the entry.
- Bronze `unique-config-entry`: `await self.async_set_unique_id(<device serial>)`, then
  `self._abort_if_unique_id_configured()`.
- Bronze `config-flow` subchecks: supply `data_description` for every field. Use `ConfigEntry.data`
  for connection info and `ConfigEntry.options` for user preferences.
- Gold `reconfiguration-flow`: `async_step_reconfigure` hands off to the user step. It is guarded
  by `_abort_if_unique_id_mismatch()`, because you must not repoint an entry at a *different*
  device. It finishes with `async_update_reload_and_abort(self._get_reconfigure_entry(), data=...)`.
- Gold `discovery-update-info`: on rediscovery, call
  `self._abort_if_unique_id_configured(updates={CONF_HOST: host})` so the entry follows the device's
  new IP. **This is why the unique ID must never be the IP.**
- Reauth flow context, if we ever need it: `source == SOURCE_REAUTH`, plus `entry_id` and
  `unique_id` in `self.context`.

---

## 11. Where the docs and the code disagree

Ranked by how likely each is to cause us trouble.

1. **`strings.json` in a custom integration.** The i18n docs now say **"Do not use `strings.json`
   for custom components"** because `[%key:...%]` is a build-time feature. Yet hassfest still
   schema-validates one if present. Resolution: write `translations/en.json` only, fully expanded.
   §5.
2. **Quality-scale rule slugs.** The
   [index page](https://developers.home-assistant.io/docs/core/integration-quality-scale/) example
   uses **underscores** (`config_flow`, `docs_high_level_description`). The schema and every real
   file use **hyphens**. Copying the doc example produces a schema failure.
3. **The docs never list the rules per tier.** Only `ALL_RULES` / `tiers.json` do. §6.
4. **`_attr_name` beats `translation_key`** in `_name_internal()`. This precedence is undocumented
   and fails silently. Set both without thinking and your translation is ignored. §3.
5. **`via_device` is gone from `DeviceInfo`** (typing error). `via_device_id` replaces it, and that
   is a device *id*, not an identifier tuple. The docs' `DeviceInfo` listing still shows
   `created_at` / `modified_at`, which core has removed. §4.
6. **`format_mac` responsibility.** The registry normalises `CONNECTION_NETWORK_MAC` inside
   `connections` on its own. You must call `dr.format_mac()` yourself only for `unique_id` and
   `identifiers`. The docs imply it is always your job.
7. **Coordinator `config_entry=` is enforced only for core.** Core comment: *"It is not planned to
   enforce this for custom integrations."* We follow the documented practice anyway. §2.
8. **`quality_scale.yaml` does nothing for custom integrations**, because of `if not
   integration.core: return`. The docs never say so. §6.
9. **The `integration_fetching_data` example has the wrong structure** for a modern integration. It
   is untyped, has no generic and no `@override`. It builds the coordinator in a *platform's*
   `async_setup_entry`, where `async_config_entry_first_refresh()` will raise `ConfigEntryError`
   on any late forward. §2.
10. **`ConfigEntryError` is missing from `integration_setup_failures`.** That is the page you would
    naturally read for "which exception when". It documents only `ConfigEntryNotReady`,
    `PlatformNotReady` and `ConfigEntryAuthFailed`.
11. **`@override` is mandatory in core** (`mypy.ini: enable_error_code = … explicit-override …`) and
    appears in almost no documentation.
12. **`@dataclass(kw_only=True)` in the docs vs `@dataclass(frozen=True, kw_only=True)` in core**
    for entity descriptions. §3.
13. **Doc typos not to copy blindly.** The `config-entry-unloading` rule's snippet is missing a `:`
    after its `if`. The i18n page's prose says exceptions live under `exception` (singular), while
    its own example and core use `exceptions`. The same page's table says `selectors`, while
    everything else uses `selector`.
14. **`creating_component_code_review` still tells you to use `hass.data[DOMAIN]`.** That directly
    contradicts the `runtime-data` rule. The page is unmaintained.
15. **`data_description`** is a documented `config-flow` subcheck and is used throughout core. But
    it is missing from the i18n page's key table.
16. **The HACS OSI-license check** is live in code (2026-07-04) but missing from `include.md`. Its
    own `more_info` anchor 404s. §9.
17. **The `brands` quality-scale rule page** still describes only the brands-repo route. It is out
    of step with the 2026.3 local `brand/` mechanism. §9.
18. **`zeroconf` matcher `macaddress` / `model` / `manufacturer`** are `cv.deprecated` in the schema
    but still shown in the manifest doc's examples.

These are genuinely **ambiguous**. The docs decline to rule:

- **`_attr_*` vs properties.** The docs describe both without ranking them. The order in §3 is
  inferred from the "do as little work as possible in the property" tip plus uniform core practice.
- **`_attr_icon`'s status.** It is "Not recommended", and `icons.json` replaces it for the gold
  rule. But it is not deprecated. It is still the only way to compute an icon from logic outside
  the entity's state.
- **Entity base-class ordering.** Three doc pages, three different orderings, no stated rule.
- **Polling interval.** No number, no enforced minimum for coordinators.
- **Unique-ID separator** (`-` vs `_`). Both appear in core. Nothing standardises it.
- **`EntityNamePart` / area+floor naming** machinery in `entity_registry.py` is undocumented and
  still changing. `friendly_name` currently pins `parts=(DEVICE, ENTITY)`, `use_legacy_naming=True`.
- **Child devices** are explicitly marked *"the design is still being finalized."*

---

## 12. Consequences for `heatit_wifi_panel`

### Settled — no further decision needed

- Module layout (`coordinator.py`, `entity.py`), `entry.runtime_data`, and the typed alias
  **`HeatitWifiPanelConfigEntry`** declared in `coordinator.py`. The alias uses letters and digits
  only, because the regex forbids underscores.
- Coordinator: `DataUpdateCoordinator[HeatitPanelData]` over a `@dataclass` payload, explicit
  `config_entry=`, class-level `config_entry:` annotation, `@override` on every override,
  `_async_setup` for one-time work, `UpdateFailed` with translation keys, `always_update=False`.
- `async_config_entry_first_refresh()` in `__init__.py` only, before `runtime_data` assignment and
  platform forwarding.
- The base entity extends `CoordinatorEntity[HeatitWifiPanelCoordinator]`. It sets
  `_attr_has_entity_name = True` and `_attr_device_info` once.
- `_attr_unique_id = f"{serial}-{description.key}"`. Never IP, hostname or entry id.
- Climate is the main feature: `_attr_name = None`.
- Description-driven platforms with `@dataclass(frozen=True, kw_only=True)` and `value_fn` /
  `set_value_fn` callables, declared in the platform module.
- `PARALLEL_UPDATES = 0` on `sensor` / `binary_sensor`. `= 1` on `climate`, `number`, `switch`,
  `select`, `button`.
- `translations/en.json` (fully expanded, no `[%key:...%]`), `icons.json`, no `strings.json`.
- `manifest.json` per §7, including `version`, `import_executor`, `issue_tracker`, and **no**
  `single_config_entry`.
- Brand images under `custom_components/heatit_wifi_panel/brand/` at 256×256 / 512×512, not a
  brands-repo PR.
- `sw_version` kept live from the coordinator via `async_get_device_by_identifier` +
  `async_update_device`.
- Multi-panel: one config entry per panel, each with its own device and coordinator. They already
  share an `aiohttp` session, because `async_get_clientsession(hass)` is HA-managed. That is also
  exactly what `inject-websession` requires. Nothing global is needed. `hass.data` stays untouched.

### Contradicts the map's current assumptions

1. **`.orca/drops/heatit-wifi-panel-ha-integration.md` is not present in this worktree.** So the
   handoff could not be diffed line by line. It was diffed instead against what issue #2 reports it
   contains. The `DataUpdateCoordinator` + entity-platform skeleton it sketches is broadly right.
   What has moved underneath it is `runtime_data`, the typed alias, the 2026.8 device-registry
   changes, the custom-integration translations rule, and the brands mechanism.
2. **The map's "Not yet specified → Release & CI hygiene" bullet names "the `home-assistant/brands`
   PR" as a required step.** For a HACS custom integration in 2026 it is not. Ship `brand/icon.png`
   instead. The brands PR only comes back at core-submission time.
3. **The map's "`strings.json` / translation coverage" bullet assumes `strings.json` is the file we
   write.** For a custom integration the docs now say the opposite. The deliverable is
   `translations/en.json`.

### Deserves its own ticket

1. **Where does the API client live, and does it ship to PyPI?** Platinum `strict-typing` requires
   every manifest `requirement` to ship `py.typed`. `dependency-transparency` and `async-dependency`
   assume a published, async package that can be reviewed on its own. A client vendored inside
   `custom_components/` avoids a PyPI release. But it rules out all three platinum rules and makes
   core migration much harder. Bronze and silver are unaffected either way. **This is a real fork.**
2. **Which quality tier do we commit to, and what does `quality_scale.yaml` claim?** The 11 `docs-*`
   rules cannot be met without a `home-assistant.io` page. So a HACS-only integration cannot
   honestly claim gold. "Bronze + silver fully met, gold met except `docs-*`" is defensible and
   checkable. But it is a decision. And since hassfest never validates the file for us, we need our
   own check or a manual review step. This also decides the map's "Diagnostics, repairs, and
   reconfiguration" fog. `diagnostics` and `reconfiguration-flow` are gold and cheap.
   `repair-issues` is gold and probably exempt.
3. **Core-submission delta.** `issue_tracker` (required by HACS, forbidden in core), `version`
   (required by HACS and the loader, forbidden in core), `documentation` (must repoint to
   `home-assistant.io/integrations/...`), `brand/` → brands-repo PR, and `translations/en.json` →
   `strings.json` with `[%key:...%]` references. Small but real. Better to record it now than to
   rediscover it later.

### Fog the research resolves without a ticket

- **Energy dashboard semantics at a kWh reset.** The
  [sensor docs](https://developers.home-assistant.io/docs/core/entity/sensor/) say a `total_increasing`
  sensor whose value decreases is treated as a new meter cycle. The zero-point is set to **0**, not
  to the decreased value. The *exception* is that decreases under **10%** are ignored as sensor
  noise. So a full reset-to-zero from our reset button is handled correctly. A *partial* reset would
  be misread. `last_reset` is documented only for `state_class: total`, not `total_increasing`. This
  settles the choice in favour of `total_increasing`. The 10% tolerance is the caveat to record in
  the conformance checklist.
- **Multi-panel session sharing.** Answered above: it is automatic, and `inject-websession`
  requires it.

### Confirmed out of scope / not applicable

- `reauthentication-flow`: the panel's local API has no auth in the OpenAPI spec. `exempt` with a
  comment.
- `action-setup`, `docs-actions`, `docs-triggers`, `docs-conditions`: no custom actions, triggers or
  conditions planned. `exempt`.
- `dynamic-devices`, `stale-devices`: one config entry is one fixed device. `exempt` (exactly what
  AirGradient does).
- `via_device_id` / hub topology, and **child devices**: not applicable. Child devices are an
  explicitly unstable API we should not build on.
- `integration_type: virtual`: a custom integration cannot provide it at all.
