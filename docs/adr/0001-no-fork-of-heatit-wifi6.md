---
status: accepted
---

# No fork of heatit_wifi6

The originating brief proposed forking `mattik-gh/heatit_wifi6`. That is a HACS integration for the related Heatit WiFi6 thermostat. The brief called its API "almost identical". An audit of that repository (`docs/research/heatit-wifi6-prior-art.md`) found this is not true:

- Only 5 of the Panel's 15 writable parameters match in name, type, range and meaning.
- The differences sit on the write path, and two of them fail silently. The network block is `Network` on the Panel and `network` on the WiFi6. `panelMode` 2 is Eco on the Panel, while `operatingMode` 2 is Cool on the WiFi6.
- About 30 of 38 current-standards rows fail. There is no coordinator, no entity descriptions, no device, no config-flow validation, no tests and no CI.
- The three things worth inheriting (a parameter-to-entity table, a test setup, a config flow) do not exist there.

We decided to **ignore** it. The integration is written from the spec and the observed panel, in this repository's own history. No code is copied, no history is forked, and no acknowledgement is owed or given.

## Consequences

- The spec never names `heatit_wifi6`. The audit surfaced some device behaviours: a wrong `Content-Type` on JSON responses, and several Heatit devices timing out when polled together at Home Assistant restart. Those stand as claims about the device. The conformance checklist verifies them against our own panel, and once verified they are sourced to the panel.
- ~~The README carries a one-line signpost telling WiFi6 thermostat owners this integration is not for their device. That is a routing aid, not credit.~~ **Withdrawn 2026-09-10** ([#48](https://github.com/Normio/HeatIt-Wifi-Panel/issues/48)): the README names no other device at all. The reasoning above has not changed. The signpost was never credit, and dropping it is not credit either. But a routing aid the owner does not want is not one this decision can keep imposing. Coexistence is not affected. It rests on the distinct domain, below, and never rested on the signpost.
- The handoff brief keeps its fork recommendation word for word, as the historical record. A banner says it is superseded and the fork was rejected.
- Coexistence with `heatit_wifi6` on the same Home Assistant is settled by the distinct domain `heatit_wifi_panel` and display name. Nothing in code guards it.
