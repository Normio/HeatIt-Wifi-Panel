# Changelog

Every notable change to this project is recorded in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.1] - 2026-09-12

The repository moved. The links on the integration's page follow it.

### Changed

- The documentation and issue links on the integration's page now point at
`Normio/HeatIt-Wifi-Panel`
- The settings reset is documented as settling within about 8 s, not 5 s.
A 1000 W unit took 5.2 s.

## [0.4.0] - 2026-09-12

The setup dialog, the options dialog and the log lines use plainer wording.

### Changed

- The setup dialog wording
- The options dialog wording

### Verified

- A **1000 W panel** at firmware **1.21**.

## [0.3.0] - 2026-09-11

Adds 2 buttons: a reset and a restore. Both are off until you turn them on.

### Added

**Buttons**

- Reset the energy counter
- Restore the panel's default settings. Your network and the panel's pairing
are kept

## [0.2.0] - 2026-09-11

Adds 8 numbers, 2 switches, 2 selects, 5 sensors and 1 binary sensor. The
room a panel is assigned to in the MyHeatit app now picks an area you already
have, instead of creating one.

### Added

**Numbers**

- Comfort setpoint
- Eco setpoint
- Lowest and highest temperature the setpoints may be set to
- Sensor calibration, to correct the temperature the panel measures
- Load limit, in watts
- Display brightness, in use and on standby

**Switches**

- Open window detection
- External sensor. Needs a wireless sensor paired to the panel

**Selects**

- What the standby display shows: the setpoint, or the measured temperature
- The panel's buttons: enabled, disabled, or menu locked

**Sensors**

- Room temperature
- Power, in watts
- Energy, in kWh, ready for the Energy dashboard
- How much longer the panel will hold its setpoint down for an open window
- WiFi signal strength, off until you turn it on

**Binary sensor**

- Open window detected

### Changed

- The room a panel is assigned to in the MyHeatit app now only **picks between
the areas you already have**. It matches by name, so `bedroom` finds
`Bedroom`. It no longer creates an area automatically.

## [0.1.0] - 2026-09-11

First release: the **Heatit WiFi Panel** wall heater over its own HTTP API on
your local network. No cloud, no account, no vendor app. Only the thermostat
ships here. The remaining entities follow in later releases.

### Added

- The panel is added as a **device**. It has one **climate entity**, polled
every 60 seconds by default, and a **diagnostics download** on its device
page. The download replaces the panel's identifiers and its address with
placeholders.
- The climate entity has off and heat, with **comfort and eco as presets**. The
target temperature follows whichever setpoint the panel is heating to. So it
moves with the preset, and it is blank while the panel is off
([ADR-0004](https://github.com/Normio/HeatIt-Wifi-Panel/blob/main/docs/adr/0004-eco-as-a-climate-preset.md)). Whether the
element is on comes from the panel's relay, not from its reported power.

### Verified

- Firmware **1.21** on a 600 W panel. The evidence is recorded in the
[conformance register](https://github.com/Normio/HeatIt-Wifi-Panel/blob/main/docs/conformance/checklist.md).

