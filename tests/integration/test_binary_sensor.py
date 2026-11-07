"""The open-window detection of §5.2, as On and Off.

The entity table in ``test_entity.py`` pins the row itself, including the
**absent** device class. The panel infers an open window from a temperature
drop, not from a contact, so Open/Closed would claim something it does not
know. This file asserts that the detection follows the panel and that a
firmware without it has no such entity.
"""

from typing import TYPE_CHECKING

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, Platform
from homeassistant.helpers import entity_registry as er

from custom_components.heatit_wifi_panel import binary_sensor
from tests.fakes import ABSENT, FakeHeatitClient
from tests.integration.conftest import (
    REFERENCE_DEVICE_ID,
    entity_id,
    setup_entry,
)
from tests.integration.test_entity import ENTITY_TABLE

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry

KEY = "open_window_detected"
READ_PATH = "parameters.OWD.activeNow"


def detection_id(hass: HomeAssistant) -> str:
    """Return the one binary sensor's entity id, asked of the registry."""
    return entity_id(hass, Platform.BINARY_SENSOR, KEY)


def test_a_read_only_platform_serialises_nothing() -> None:
    """§3.5: nothing here writes, so there is nothing to hold a queue for."""
    assert binary_sensor.PARALLEL_UPDATES == 0


async def test_the_detection_follows_the_panel(
    hass: HomeAssistant,
    patched_client: FakeHeatitClient,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The reference capture has no open window; the panel is what changes it."""
    assert await setup_entry(hass, mock_config_entry)
    before = hass.states.get(detection_id(hass))
    assert before is not None
    assert before.state == STATE_OFF

    patched_client.set_status({READ_PATH: True})
    await mock_config_entry.runtime_data.async_refresh()

    after = hass.states.get(detection_id(hass))
    assert after is not None
    assert after.state == STATE_ON


async def test_a_firmware_without_the_detection_has_no_entity(
    hass: HomeAssistant,
    patched_client: FakeHeatitClient,
    mock_config_entry: MockConfigEntry,
) -> None:
    """§5.4's presence gate, on the one path this platform reads."""
    patched_client.set_status({READ_PATH: ABSENT})

    assert await setup_entry(hass, mock_config_entry)

    # §8.5: exactly that entity absent, every other entity present.
    registered = {
        found.unique_id
        for found in er.async_entries_for_config_entry(
            er.async_get(hass), mock_config_entry.entry_id
        )
    }
    assert registered == {
        f"{REFERENCE_DEVICE_ID}-{row.key}" for row in ENTITY_TABLE if row.key != KEY
    }


async def test_a_detection_that_vanishes_makes_the_entity_unavailable(
    hass: HomeAssistant,
    patched_client: FakeHeatitClient,
    mock_config_entry: MockConfigEntry,
) -> None:
    """§6.3: present at setup and gone later is unavailable, not off."""
    assert await setup_entry(hass, mock_config_entry)
    patched_client.set_status({READ_PATH: ABSENT})

    await mock_config_entry.runtime_data.async_refresh()

    reported = hass.states.get(detection_id(hass))
    assert reported is not None
    assert reported.state == STATE_UNAVAILABLE
