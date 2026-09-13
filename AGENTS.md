# AGENTS.md

Home Assistant integration (HACS custom component) for the Heatit WiFi Panel
wall heater. It drives the panel over its local HTTP API.

## Agent skills

### Issue tracker

Issues are GitHub issues in `Normio/HeatIt-Wifi-Panel`, managed with
the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

There are five triage roles. Each label string is the same as its role name.
See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repo: `CONTEXT.md` and `docs/adr/` live at the repo
root. See `docs/agents/domain.md`.

### Local device pointer

If a real Heatit WiFi Panel is reachable, its address lives in
`.local/device.json`. That file is gitignored. Its shape is in
`.local/device.example.json`. Probe scripts and hardware conformance runs read
the host from there. Never hardcode an IP address, and never commit one.

`scripts/capture_fixtures.py` reads the panel's status through the real
client. It only reads, it never writes. It refreshes
`tests/fixtures/observed/fw-<firmware>/` and scrubs identifiers on the way.
Run it by hand, never from CI. A new firmware means a new directory. In the
same pull request, add the version to `VERIFIED_FIRMWARES` in `const.py` and
to the README's `## Verified firmware` table.

## Quality scale

`custom_components/heatit_wifi_panel/quality_scale.yaml` is the checklist.
`scripts/check_quality_scale.py` is what makes it one. A `done` rule's comment
starts with the repo-relative path that is its evidence. Deleting that file
fails the check until the yaml says otherwise. Moving or renaming a test a
rule points at means editing the yaml in the same pull request. The escape
hatch is the format itself: `exempt`, with a reason.

## README

Read `tests/test_readme.py` before editing `README.md`. It keeps the README in
step with the code in the tree. It checks that:

- the `## Verified firmware` table, the observed fixture directories and
  `VERIFIED_FIRMWARES` all name the same versions;
- the `## Entities` table lists exactly the entities the platform modules
  declare. So **a platform ships its README rows in the same pull request as
  its module**;
- the Home Assistant floor in the README is the one `hacs.json` declares;
- no "beta", "experimental" or "pending validation" wording appears anywhere.
  The 0.x version number already says that. Saying it in words is a
  documented reason for a `hacs/default` rejection.

The install section belongs to the release runbook, not to this file. See
`docs/releasing.md`.

## Before a push

Run `scripts/check.sh`. It is the one shared entry point. It runs ruff,
`ruff format --check`, the repository layout check, the conformance register
check, mypy strict, the quality-scale check and pytest.
`.github/workflows/test.yml` calls the same file, so local and CI cannot
drift. `scripts/check.sh lint` and
`scripts/check.sh test` run either half on its own. There are no git hooks and
no pre-commit framework, on purpose.

Install what it needs with `pip install -r requirements_test.txt`.

## Changelog

`CHANGELOG.md` records **what a user can see or do in Home Assistant**:
behaviour, entities, configuration. Nothing else. Not the scripts, not the
workflows, not the tooling a contributor runs. Write the entry under
`## [Unreleased]`.

A documentation-only change gets no entry. A conformance register row
flipping to `verified`, a research note, a spec amendment, a README change, or
a change to this file is already its own record. Repeating it in the changelog
means two places to keep true. Label such a pull request `skip-changelog`.
That is the label the pull request check looks for. CI-only changes take the
same label.

A **fix to unreleased work** takes the same label, as long as the
`## [Unreleased]` entry already describes the fixed behaviour. Code that
disagrees with an entry from the same release cycle is a bug that never
shipped. Keep a Changelog folds that into the original entry instead of
recording a fix. A reader sees the same sentence before and after. If the fix
changes what the entry *claims*, edit the entry instead. That touches
`CHANGELOG.md`, so no label is needed.

The test is this: would a **user of the integration** see or do something
differently in Home Assistant? A contributor running a script differently does
not count. Neither does "read the document that changed" or "nothing, the
entry already said this". Those do not belong here.
