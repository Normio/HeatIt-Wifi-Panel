# Releasing

How a version of the integration becomes a GitHub release, what can stop it,
and the repository settings the release depends on that no workflow can apply.
See spec §10.2 and §10.3, and [ADR-0002](adr/0002-tag-push-release-with-gate.md).

## Cutting a release

Pushing a `vX.Y.Z` tag is the only way to create a release. Nothing else does
it: no `workflow_dispatch`, no bot, no hand-made release. The tag form is
permanent, because HACS compares tag strings.

1. **The release PR**, reviewed and merged like any other:
   - bump `version` in `custom_components/heatit_wifi_panel/manifest.json` to
     the bare number, for example `0.1.0`;
   - in `CHANGELOG.md`, rename `## [Unreleased]` to `## [0.1.0] - YYYY-MM-DD`
     and put its entries into final form. Then open a fresh, empty
     `## [Unreleased]` above it. That section's body becomes the release
     notes, word for word;
   - write or rewrite the README's `## Installation` section. See below. The
     lockstep check refuses a tag whose README does not install the way that
     version is installed, so this step cannot be forgotten.
2. **The tag**, pushed by the owner from the merged commit on `main`:

   ```sh
   git switch main && git pull --ff-only
   git tag v0.1.0
   git push origin v0.1.0
   ```

3. `.github/workflows/release.yml` runs on the tag. When every gate job is
   green, the publish job creates the release with the changelog section as
   its body. When any job is red, no release is created and the tag stays.

## The README's install section

Spec §11.3 says the install docs go in the **`v0.1.0` release PR and not one
commit earlier**. The reason is in §11.1: the custom-repository URL must not
be shared before a release exists. HACS's `can_download` only checks the
`homeassistant` floor when `self.data.releases` is set. So a repository with
no releases has no floor gate at all, and would offer an incompatible download
to users on old installs. Install instructions published before the first
release are that URL, shared.

**`v0.1.0` through `v0.x.y`: the custom-repository route, and only that.** A
My Home Assistant redirect link, then the manual steps: HACS → **Custom
repositories** → this repository's URL, category *Integration*. Never offer a
manual-copy route. A copy into `custom_components/` bypasses the floor gate
and never sees a release.

**`v1.0.0` rewrites the section** to plain default-store instructions: search
HACS for *Heatit WiFi Panel* and download. That happens in the same PR that
opens the `hacs/default` submission. HACS refuses a custom-repository entry
for a repository that is already in the default store. Leaving the old text in
place would send every new user into an error.

Both halves of "not before, not later" are enforced, not remembered.

`tests/test_readme.py` enforces **not before**. It runs offline, on every pull
request. The README may carry an `## Installation` section only once
`CHANGELOG.md` holds a released version section. The release PR writes both,
in the order above, so they arrive together or not at all.

`scripts/check_release.py` enforces **not later**, on the tag. It fails when:

- the tag has no `## Installation` section;
- the section names `custom_components/` at any version, because that is the
  manual-copy route;
- a `0.x` tag's section does not name the **Custom repositories** dialog;
- a `1.0.0`-or-later tag's section still names it.

## The gate

Every job runs against the tagged commit. The publish job `needs` all of:

| Job | What it is |
|---|---|
| Validate | `validate.yml` called whole: HACS Action and hassfest, with no `ignore:` |
| Test | `test.yml` called whole: the `Lint` job and both pytest rows, so ruff, mypy, the check scripts and the tests. A job that is `continue-on-error` on pull requests must not be so on a tag, or the gate would pass over its failure. `Tests (latest)` guards its own with `&& !startsWith(github.ref, 'refs/tags/')`, and `tests/scripts/test_release_gate.py` fails on any value that is not guarded that way |
| Lockstep | `scripts/check_release.py`: the tag names the manifest's version; the tagged commit is an ancestor of `main`; `LICENSE`, `hacs.json`, the manifest, `README.md` and `brand/icon.png` exist; `hacs.json` has `hide_default_branch: true` and a `homeassistant` value AwesomeVersion can parse; `CHANGELOG.md` has a non-empty `## [X.Y.Z]` section; the README's install section matches the version being released |

To rehearse the lockstep half before pushing, from the checkout holding the
tag:

```sh
python3 scripts/check_release.py v0.1.0 --main origin/main
```

It prints nothing when the tag would pass, and one line per problem when not.

## When the gate fails

A failed gate **leaves the bare tag** and deletes nothing. HACS ignores tags
without a release, so the bare tag is harmless. Fix the cause on `main`
through a PR. Then delete the tag and retag the new commit:

```sh
git push origin --delete v0.1.0
git tag --delete v0.1.0
git switch main && git pull --ff-only
git tag v0.1.0 && git push origin v0.1.0
```

Only the owner can do this. The `v*` tag ruleset denies creation, update and
deletion to everyone else, including the workflows' tokens. No workflow is
ever given tag deletion.

## Repository settings the release depends on

These live in GitHub's settings, not in the repository. They need an
administrator's token, which the agent sessions do not have (`gh repo edit`
answers 403). They are gate item 5 of the submission gate (spec §11.2).
**All of them were applied and verified through the API on 2026-09-09.** The
commands and the ruleset shapes are here so they can be checked or restored.

**Description and topics.** The nightly HACS checks `description` and
`topics` read them:

```sh
gh repo edit Normio/HeatIt-Wifi-Panel \
  --description "Home Assistant integration for the Heatit WiFi Panel wall heater (local HTTP API)" \
  --add-topic home-assistant --add-topic hacs --add-topic custom-component \
  --add-topic heatit --add-topic heater --add-topic climate
```

Check with `gh repo view --json description,repositoryTopics`.

**The `v*` tag ruleset** ("Release tags", target `tag`, enforcement `active`):
`refs/tags/v*` is restricted for creation, update and deletion. The
repository's administrators are the only bypass actors. This is what makes
"only the owner may create `v*` tags" true. It also denies every workflow
token tag deletion, whatever `permissions:` it declares.

**The `main` ruleset** ("Main", target `branch`): no deletion, no
force-push, changes only through a pull request, and the blocking jobs of
`test.yml`, `validate.yml` and `changelog.yml` required as status checks.
This is the "blocks a merge" half of the linters and validators.

As of 2026-09-10 the required checks are `Lint`, `Tests (floor)`,
`HACS Action`, `hassfest` and `Changelog entry`, verified through the API. The
ruleset was first written naming `Checks`. That single job was split into
`Lint`, `Tests (floor)` and `Tests (latest)` in #38. The owner then renamed it
by hand, which is the only way, because no workflow token can edit a ruleset.
`Tests (latest)` is deliberately *not* required. It is `continue-on-error`
off a tag, so it is a signal rather than a blocker (§8.7). **Any future rename
of a blocking job needs the same manual step.** Until it is made, every pull
request blocks on a job that no longer runs, with every check green.

Check both with:

```sh
gh api repos/Normio/HeatIt-Wifi-Panel/rulesets --jq '.[] | "\(.name) \(.target) \(.enforcement)"'
```
