"""``scripts/check_conformance.py`` fails on each of the spec's seven conditions."""

from pathlib import Path

import check_conformance
import probe

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTER = REPO_ROOT / "docs" / "conformance" / "checklist.md"

ISSUE = "[#7](https://github.com/Normio/HeatIt-Wifi-Panel/issues/7)"
FIRMWARE = "1.21"
FIRMWARES = frozenset({FIRMWARE})

HEADER = (
    "## The register\n\n"
    "| id | claim | vs spec | tier | status | evidence | dependents |\n"
    "|----|-------|---------|------|--------|----------|------------|\n"
)
APPENDIX = (
    "\n## Appendix: manual procedures\n\n"
    '<a id="p-1"></a>\n### P-1 — a procedure (Q2)\n\nSteps.\n'
)


def summary(verified: int, open_: int, disagrees: int) -> str:
    """Write a summary line in the one form the check reads."""
    return (
        f"\n**{verified} verified at firmware {FIRMWARE}, {open_} open, "
        f"{disagrees} `disagrees`.** Nothing is `contradicted`.\n"
    )


def counted_summary(rows: str) -> str:
    """Write a summary line that agrees with the well-formed rows it follows.

    This counts the way the script does, so it is no oracle for condition 7.
    It only keeps the other conditions' fixtures from tripping it. The
    condition 7 test states its expected figures by hand.
    """
    parsed = [
        probe.row_from_cells(cells)
        for cells in probe.parse_register_cells(HEADER + rows)
        if len(cells) == len(probe.REGISTER_COLUMNS)
    ]
    return summary(
        sum(row.status == f"verified fw {FIRMWARE}" for row in parsed),
        sum(row.status == "open" for row in parsed),
        sum(row.vs_spec == "disagrees" for row in parsed),
    )


def register(
    rows: str, *, summary_line: str | None = None, appendix: str = APPENDIX
) -> str:
    """Assemble a register document: table, summary line, appendix.

    The summary line agrees with the table unless one is given.
    """
    if summary_line is None:
        summary_line = counted_summary(rows)
    return HEADER + rows + summary_line + appendix


def problems(text: str, *, probe_ids: frozenset[str]) -> list[str]:
    """Run the gate over a register text with a stated probe id set."""
    return check_conformance.problems(
        text,
        repo_root=REPO_ROOT,
        verified_firmwares=FIRMWARES,
        probe_ids=probe_ids,
    )


GOOD_ROWS = (
    f"| Q1 | A claim | agrees | write | verified fw 1.21 | {ISSUE} | {ISSUE} prose |\n"
    "| Q2 | Another | silent | manual | open | [P-1](#p-1) | "
    "`docs/adr/0003-device-id-as-unique-id.md` |\n"
)


def test_a_well_formed_register_passes() -> None:
    """The good case: nothing to report."""
    assert problems(register(GOOD_ROWS), probe_ids=frozenset({"Q1"})) == []


def test_the_real_register_passes_against_the_real_probe() -> None:
    """The committed register and ``probe.py`` agree today."""
    text = REGISTER.read_text(encoding="utf-8")
    assert problems(text, probe_ids=probe.registered_ids()) == []


def test_condition_1_duplicate_or_malformed_ids_and_vocabulary() -> None:
    """A duplicated id, a bad id, a bad column count, a word outside the vocabulary."""
    rows = (
        f"| Q1 | A | agrees | write | verified fw 1.21 | {ISSUE} | {ISSUE} |\n"
        f"| Q1 | B | agrees | write | verified fw 1.21 | {ISSUE} | {ISSUE} |\n"
        f"| Q-3 | C | agrees | write | verified fw 1.21 | {ISSUE} | {ISSUE} |\n"
        f"| Q4 | D | agrees | write | verified fw 1.21 | {ISSUE} |\n"
        f"| Q5 | E | maybe | write | verified fw 1.21 | {ISSUE} | {ISSUE} |\n"
        f"| Q6 | F | agrees | scripted | verified fw 1.21 | {ISSUE} | {ISSUE} |\n"
        f"| Q7 | G | agrees | write | probably | {ISSUE} | {ISSUE} |\n"
    )
    found = problems(register(rows), probe_ids=frozenset({"Q1", "Q5", "Q6", "Q7"}))
    assert any("Q1" in p and "duplicate" in p for p in found)
    assert any("Q-3" in p and "malformed" in p for p in found)
    assert any("Q4" in p and "7 columns" in p for p in found)
    assert any("Q5" in p and "vs spec" in p for p in found)
    assert any("Q6" in p and "tier" in p for p in found)
    assert any("Q7" in p and "status" in p for p in found)


def test_condition_2_an_unknown_firmware() -> None:
    """A verified or contradicted row must cite a firmware in the verified set."""
    rows = (
        f"| Q1 | A | agrees | write | verified fw 1.30 | {ISSUE} | {ISSUE} |\n"
        f"| Q2 | B | agrees | write | contradicted fw 9.9 | {ISSUE} | {ISSUE} |\n"
    )
    found = problems(register(rows), probe_ids=frozenset({"Q1", "Q2"}))
    assert any("Q1" in p and "1.30" in p for p in found)
    assert any("Q2" in p and "9.9" in p for p in found)


def test_condition_3_missing_or_unresolvable_evidence() -> None:
    """A non-open row needs evidence, and every evidence entry must resolve."""
    rows = (
        "| Q1 | A | agrees | write | verified fw 1.21 | — | "
        f"{ISSUE} |\n"
        "| Q2 | B | agrees | write | verified fw 1.21 | `docs/nowhere.md` | "
        f"{ISSUE} |\n"
        "| Q3 | C | agrees | write | verified fw 1.21 | [P-9](#p-9) | "
        f"{ISSUE} |\n"
        f"| Q4 | D | agrees | write | verified fw 1.21 | {ISSUE}, "
        f"[x](https://example.com) | {ISSUE} |\n"
    )
    found = problems(register(rows), probe_ids=frozenset({"Q1", "Q2", "Q3", "Q4"}))
    assert any("Q1" in p and "no evidence" in p for p in found)
    assert any("Q2" in p and "docs/nowhere.md" in p for p in found)
    assert any("Q3" in p and "P-9" in p for p in found)
    assert any("Q4" in p and "example.com" in p for p in found)


def test_condition_4_dependents_without_a_resolvable_reference() -> None:
    """Prose alone does not count as a dependents list."""
    rows = (
        f"| Q1 | A | agrees | write | verified fw 1.21 | {ISSUE} | "
        "the climate entity, probably |\n"
        f"| Q2 | B | agrees | write | verified fw 1.21 | {ISSUE} | "
        "`docs/adr/0003-device-id-as-unique-id.md` and prose |\n"
    )
    found = problems(register(rows), probe_ids=frozenset({"Q1", "Q2"}))
    assert any("Q1" in p and "dependents" in p for p in found)
    assert not any("Q2" in p for p in found)


def test_condition_5_manual_rows_and_procedures_cite_each_other() -> None:
    """An open manual row must cite a procedure, and every procedure must be cited."""
    rows = (
        "| Q1 | A | silent | manual | open | — | "
        "`docs/adr/0003-device-id-as-unique-id.md` |\n"
    )
    found = problems(register(rows), probe_ids=frozenset())
    assert any("Q1" in p and "procedure" in p for p in found)
    assert any("P-1" in p and "cited by no row" in p for p in found)


def test_condition_6_the_register_and_the_probe_disagree() -> None:
    """Every non-manual id is registered in the probe, and nothing else is."""
    found = problems(register(GOOD_ROWS), probe_ids=frozenset({"Q1", "Q99"}))
    assert any("Q99" in p and "probe.py" in p for p in found)
    found = problems(register(GOOD_ROWS), probe_ids=frozenset())
    assert any("Q1" in p and "probe.py" in p for p in found)


def test_condition_7_the_summary_line_disagrees_with_the_table() -> None:
    """Each of the three figures is held to the table, and the message names both."""
    rows = (
        f"| Q1 | A | agrees | write | verified fw 1.21 | {ISSUE} | {ISSUE} |\n"
        f"| Q2 | B | disagrees | write | verified fw 1.21 | {ISSUE} | {ISSUE} |\n"
        "| Q3 | C | silent | manual | open | [P-1](#p-1) | "
        "`docs/adr/0003-device-id-as-unique-id.md` |\n"
    )
    ids = frozenset({"Q1", "Q2"})
    assert problems(register(rows, summary_line=summary(2, 1, 1)), probe_ids=ids) == []
    for line, message in (
        (summary(3, 1, 1), "says 3 verified, the table has 2"),
        (summary(2, 2, 1), "says 2 open, the table has 1"),
        (summary(2, 1, 0), "says 0 disagrees, the table has 1"),
    ):
        found = problems(register(rows, summary_line=line), probe_ids=ids)
        assert len(found) == 1, found
        assert message in found[0]


def test_condition_7_a_missing_summary_line_is_a_problem() -> None:
    """Deleting the line is not a way to stop it drifting."""
    found = problems(register(GOOD_ROWS, summary_line=""), probe_ids=frozenset({"Q1"}))
    assert any("summary line" in p for p in found)


def test_a_missing_register_table_is_a_problem() -> None:
    """A document with no register table is not a register."""
    assert problems("# nothing here\n", probe_ids=frozenset())
