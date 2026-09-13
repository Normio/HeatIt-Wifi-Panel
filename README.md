# Heatit WiFi Panel

A Home Assistant integration for the **Heatit WiFi Panel** wall heater. It
talks to the panel's own HTTP API on your local network. Home Assistant reads
the panel's status and writes its settings directly. 

There is no cloud
service, no account, and no vendor app in the path once the panel is on WiFi.

## Requirements

- Home Assistant **2026.3.1** or newer.
- A Heatit WiFi Panel on the same network as Home Assistant.

## Installation

Install this integration through [HACS](https://hacs.xyz) as a custom
repository.

[![Open this repository inside your Home Assistant's HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Normio&repository=HeatIt-Wifi-Panel&category=integration)

The button opens HACS on this repository in your own Home Assistant. To do the
same by hand:

1. In HACS, open the menu in the top right and choose **Custom repositories**.
2. Paste this repository's address:
 `https://github.com/Normio/HeatIt-Wifi-Panel`.
3. Pick the type **Integration** and add it.
4. Download **Heatit WiFi Panel** from HACS and restart Home Assistant.

After the restart, add the panel: **Settings** → **Devices &amp; services** →
**Add integration** → **Heatit WiFi Panel**. Enter the panel's address. Home
Assistant reads the panel's status once to learn which unit it is. If the
panel's address changes later, for example after a power cut gives it a new
DHCP lease, Home Assistant follows it to the new address on its own.

## Entities

One panel is one device. All the entities below belong to it. Home Assistant
names each entity from the device's name plus the entity's own name.


| Entity                                                    | Platform      | What it is                                                                                                                                                                                                      |
| --------------------------------------------------------- | ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Heatit WiFi Panel (`panel`)                               | climate       | The thermostat. It has off and heat, the comfort and eco presets, the temperature the panel is heating to, and whether the element is on right now. It carries the panel's own name, because it *is* the panel. |
| Comfort setpoint (`comfort_setpoint`)                     | number        | The temperature the panel heats to in comfort.                                                                                                                                                                  |
| Eco setpoint (`eco_setpoint`)                             | number        | The temperature the panel heats to in eco.                                                                                                                                                                      |
| Minimum temperature limit (`minimum_temperature_limit`)   | number        | The lowest value either setpoint can be set to.                                                                                                                                                                 |
| Maximum temperature limit (`maximum_temperature_limit`)   | number        | The highest value either setpoint can be set to.                                                                                                                                                                |
| Sensor calibration (`sensor_calibration`)                 | number        | An offset added to the temperature the panel measures, from −6 to +6 °C.                                                                                                                                        |
| Load limit (`load_limit`)                                 | number        | The most power the panel will draw, in watts, up to the rating of your model.                                                                                                                                   |
| Active display brightness (`active_display_brightness`)   | number        | How bright the display is while you are using the panel.                                                                                                                                                        |
| Standby display brightness (`standby_display_brightness`) | number        | How bright the display is the rest of the time. 0 turns it off.                                                                                                                                                 |
| Open window detection (`open_window_detection`)           | switch        | Whether the panel drops to a low temperature when it senses an open window.                                                                                                                                     |
| External sensor (`external_sensor`)                       | switch        | Whether the panel uses a paired wireless sensor instead of its own. With no sensor paired, the panel accepts the change but ignores it. The switch then turns itself back off after a second or two.            |
| Standby display (`standby_display`)                       | select        | What the display shows when nobody is touching the panel: the setpoint, or the measured temperature.                                                                                                            |
| Buttons (`buttons`)                                       | select        | The panel's physical buttons: enabled, disabled, or working with the menu locked.                                                                                                                               |
| Temperature (`temperature`)                               | sensor        | The room temperature the panel measures, with its own history. The thermostat shows the same reading.                                                                                                           |
| Power (`power`)                                           | sensor        | What the panel is drawing right now, in watts. This is the reading itself, not an average over the heating cycle.                                                                                               |
| Energy (`energy`)                                         | sensor        | What the panel has used since its counter was last zeroed, in kWh. You can add it to the Energy dashboard.                                                                                                      |
| Signal strength (`signal_strength`)                       | sensor        | The panel's WiFi signal, in dBm. A diagnostic. **Off until you turn it on** from the device page: it changes on every poll and most homes never need it.                                                        |
| Open window time remaining (`open_window_time_remaining`) | sensor        | How much longer the panel will hold its setpoint down for an open window it has detected. `0` when it has detected none.                                                                                        |
| Open window detected (`open_window_detected`)             | binary_sensor | Whether the panel thinks a window is open, based on a drop in room temperature. It reads on or off, not open or closed, because the panel watches the temperature, not a window.                                |
| Reset energy counter (`reset_energy`)                     | button        | Zeroes the panel's energy counter. It is the same counter the MyHeatit app and the panel's display show. **Off until you turn it on** from the device page.                                                     |
| Restore default settings (`restore_defaults`)             | button        | Puts every setting on this page back to the panel's default. Your network and the panel's pairing are kept. **Off until you turn it on** from the device page.                                                  |


## Verified firmware

The integration has been tested on the firmware and panels below. A panel on another firmware should work the same way, it just has not been tested yet. 

The details of what was tested are in the [conformance register](docs/conformance/checklist.md).


| Firmware | Verified on                                                         |
| -------- | ------------------------------------------------------------------- |
| 1.21     | 600 W wall panel (`maxLoad` 6) and 1000 W wall panel (`maxLoad` 10) |


## Network

The panel serves plain HTTP on port 80 with **no authentication of any kind**.
Anyone who can reach it on the network can read its status and change its
settings. That includes this integration. Put the panel on a network you
trust.

Home Assistant reaches the panel by its IP address.

## Diagnostics

The panel's device page offers **Download diagnostics**. The file holds:

- the panel's status as the integration parsed it;
- the same status as raw bytes, exactly as the panel sent them;
- the firmware version, and whether it is one of the versions above;
- what the last poll did.

The panel's `id`, MAC address, WiFi SSID and IP address are replaced with fixed
placeholders.

## Documentation

- [Design spec](docs/spec/heatit-wifi-panel-v1.md) — the whole integration, decision by decision.
- [Conformance register](docs/conformance/checklist.md) — every claim about the panel, and the firmware it was verified on.
- [Vocabulary](CONTEXT.md) — the words this project uses for the panel and its status.
- [Changelog](CHANGELOG.md).

## Licence

[MIT](LICENSE).