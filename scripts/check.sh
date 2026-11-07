#!/usr/bin/env bash
# The one shared entry point. Run this before a push. .github/workflows/test.yml
# calls this file instead of listing the commands, so local and CI cannot
# drift. There are no git hooks and no pre-commit framework, on purpose: a
# fresh worktree without hooks installed is exactly the drift we design against.
#
# Two stages, so CI can run the row-independent half once and the
# Home-Assistant-dependent half once per matrix row (§8.7, §9.3):
#
#   scripts/check.sh        everything, in order; what a developer runs
#   scripts/check.sh lint   ruff, ruff format --check, the layout check
#   scripts/check.sh test   mypy strict, the quality-scale check and pytest,
#                           against the installed HA
#
# scripts/check_release.py is not run here: it needs a pushed tag, and only
# .github/workflows/release.yml has one. Its tests run with the rest.
set -euo pipefail

cd "$(dirname "$0")/.."

run_lint() {
  ruff check .
  ruff format --check .
  python3 scripts/check_layout.py
  # Stdlib only, like the layout check, so it belongs to the row-independent
  # half instead of running once per Home Assistant row.
  python3 scripts/check_conformance.py
}

run_tests() {
  python3 scripts/check_types.py
  # In this half, not the lint half, because it parses the yaml with the
  # loader hassfest uses, which is Home Assistant's (§9.2). Every `done` rule
  # names the file that proves it, so a deleted test fails here.
  python3 scripts/check_quality_scale.py
  # Overall coverage is measured and reported, not gated (§8.7). Core's silver
  # 95 % is not inherited.
  python3 -m pytest \
    --quiet \
    --cov=custom_components/heatit_wifi_panel \
    --cov-report=term-missing
  # The one gate. config_flow.py is small and every line of it is a path a user
  # can walk. A missed line there is a user-facing bug, not a coverage
  # statistic. Reads the .coverage file the run above wrote.
  python3 -m coverage report \
    --fail-under=100 \
    --include='*/config_flow.py'
}

case "${1:-all}" in
  lint) run_lint ;;
  test) run_tests ;;
  all) run_lint; run_tests ;;
  *) echo "usage: $0 [lint|test]" >&2; exit 2 ;;
esac
