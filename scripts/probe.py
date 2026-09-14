"""Hardware conformance probe for the Heatit WiFi Panel.

Runs the automated rows of ``docs/conformance/checklist.md`` against a real
panel. Prints a Markdown table that can be pasted into an issue. It uses the
standard library only and imports nothing from the integration. Anyone with a
second panel can run it with nothing but Python.

Four flags, one per probe tier, each one adding to the one before::

    probe.py                 read tier only, unattended, no approval
    probe.py --writes        + harmless writes, snapshotted and restore-verified
    probe.py --destructive   + kWh reset, settings reset          (y/N)
    probe.py --thermal       + heater-on sequences                (y/N, TTY)

A check registers only its id and tier. The claim it prints is read from the
register at runtime, so the sentence exists once. Every write run snapshots the
status first, registers each touched parameter and restores them on any exit.
It then re-reads the status to verify, because this panel's write echo lies.
``--restore <file>`` replays a snapshot for a run that died before any hook
could fire.

Exit codes: 0 all selected checks passed, 1 a check failed, 2 a revert failed,
3 usage or connectivity.
"""

from __future__ import annotations

import argparse
import http.client
import itertools
import json
import math
import re
import signal
import socket
import sys
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any, Protocol

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTER_PATH = REPO_ROOT / "docs" / "conformance" / "checklist.md"
OPENAPI_PATH = REPO_ROOT / "docs" / "api" / "heatit-wifi-panel-openapi.yaml"
DEVICE_PATH = REPO_ROOT / ".local" / "device.json"
SNAPSHOT_DIR = REPO_ROOT / ".local"
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "observed"

READ = "read"
WRITE = "write"
DESTRUCTIVE = "destructive"
THERMAL = "thermal"
MANUAL = "manual"
#: The automated tiers, least dangerous first; the order the flags enable them in.
TIERS: tuple[str, ...] = (READ, WRITE, DESTRUCTIVE, THERMAL)

PASS = "PASS"  # noqa: S105  # a verdict, not a password
FAIL = "FAIL"
INCONCLUSIVE = "INCONCLUSIVE"
SKIPPED = "SKIPPED (tier not enabled)"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_REVERT = 2
EXIT_USAGE = 3

#: The writable parameters seen on a real panel, so also all that a restore covers.
WRITABLE_PARAMETERS: tuple[str, ...] = (
    "panelMode",
    "heatingSetpoint",
    "ecoSetpoint",
    "minimumTemperatureLimit",
    "maximumTemperatureLimit",
    "sensorCalibration",
    "loadLimit",
    "activeDisplayBrightness",
    "standbyDisplayBrightness",
    "disableButtons",
    "temperatureDisplay",
    "sensorMode",
    "openWindowDetection",
)
#: Restored first, widest first, so no stored setpoint is ever out of range.
RESTORE_FIRST: tuple[str, ...] = ("maximumTemperatureLimit", "minimumTemperatureLimit")
#: The five fields the fixture scrub replaces; none may appear in a saved echo.
SCRUB_KEYS: tuple[str, ...] = ("id", "name", "SSID", "mac", "ipAddress")

REGISTER_COLUMNS = (
    "id",
    "claim",
    "vs spec",
    "tier",
    "status",
    "evidence",
    "dependents",
)
ROW_ID = re.compile(r"^Q\d+$")

#: A thermal check may raise a setpoint this far above the room, and no further.
THERMAL_MAX_ABOVE_ROOM = 2.0
#: The longest a thermal check may leave the relay closed.
THERMAL_MAX_RELAY_SECONDS = 45
THERMAL_CLOSE_DEADLINE = 30.0
THERMAL_DECAY_WATCH = 25.0

REQUEST_TIMEOUT = 5.0
CONNECT_TIMEOUT = 1.0
#: Q31's bound: a write shows in the status within this.
REFLECT_BOUND = 1.5
REFLECT_DEADLINE = 3.0
REFLECT_POLL = 0.05
#: Q45's bound: the counter reads zero within this of the reset acknowledgement.
RESET_ZERO_BOUND = 5.0
RESET_POLL = 0.25
#: Q34's bound: a settings reset has stopped changing parameters within this.
#: Measured 4.6 s and 5.2 s over 12 parameters at fw 1.21; 5.0 was a coin flip.
SETTINGS_SETTLE_BOUND = 8.0
SETTINGS_WATCH = 10.0
SETTINGS_POLL = 0.5
#: Q43's bound: a status read completes within this.
STATUS_READ_BOUND = 5.0
STATUS_SAMPLES = 5
#: Q42's bound: an idle keep-alive socket survives at least this long.
KEEPALIVE_IDLE = 65.0
#: Q30: how many connections are opened at once; the claim is at least two.
CONCURRENT_CONNECTIONS = 4
CONCURRENT_REQUIRED = 2
CACHE_SAMPLES = 6
CACHE_INTERVAL = 5.0
SILENT_UNDO_SAMPLES = 10
SILENT_UNDO_INTERVAL = 1.5
CALIBRATION_WATCH = 30.0
CALIBRATION_TOLERANCE = 0.3
CALIBRATION_MAX = 6.0
COLD_OFFSET = 2.5
LOAD_LIMIT_MAX = 15
OUT_OF_RANGE_BRIGHTNESS = "99"
#: Only tcp/80 answers; the rest of this list must refuse.
PORTS_TO_TRY: tuple[int, ...] = (
    22, 23, 80, 443, 1900, 5000, 5353, 8080, 8123, 8266, 9999, 49152,
)  # fmt: skip
NOT_FOUND_BODY = b"Nothing matches the given URI"
DOCUMENTED_400_BODY = "invalid data."
SUCCESS_SENTINEL = b'"Success"'
FAILED_SENTINEL = b'"failed"'

MODE_OFF = 0
MODE_HEATING = 1
MODE_ECO = 2


# --------------------------------------------------------------------------- #
# Errors and results
# --------------------------------------------------------------------------- #


class CheckFailedError(Exception):
    """The claim did not hold: a contradiction, or an open row answered no."""


class Inconclusive(Exception):  # noqa: N818  # a verdict, not an error condition
    """The run could not decide the claim on this panel in this state."""


class ThermalRefusedError(Exception):
    """A thermal guard refused to close the relay."""


class ScrubViolationError(Exception):
    """A response carries a scrub key or an identifying value; not saved."""


class Terminated(SystemExit):
    """SIGTERM arrived; the exit hook restores and the run stops."""


class UsageError(Exception):
    """Bad arguments or no panel: exit 3."""


@dataclass
class Result:
    """One row of the result table."""

    row_id: str
    tier: str
    verdict: str
    claim: str
    detail: str = ""


# --------------------------------------------------------------------------- #
# The register
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Row:
    """One row of the conformance register, as its seven cells."""

    row_id: str
    claim: str
    vs_spec: str
    tier: str
    status: str
    evidence: str
    dependents: str


def split_cells(line: str) -> tuple[str, ...]:
    """Split a Markdown table line into its cells; an escaped pipe does not split."""
    inner = line.strip()
    inner = inner.removeprefix("|").removesuffix("|")
    return tuple(cell.strip() for cell in re.split(r"(?<!\\)\|", inner))


def register_table_lines(text: str) -> list[str]:
    """Return the body lines of the register table, or an empty list."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("|"):
            continue
        header = tuple(cell.lower() for cell in split_cells(line))
        if header != REGISTER_COLUMNS:
            continue
        body: list[str] = []
        for candidate in lines[index + 2 :]:
            if not candidate.startswith("|"):
                break
            body.append(candidate)
        return body
    return []


def parse_register_cells(text: str) -> list[tuple[str, ...]]:
    """Return every register row as its raw cells, malformed rows included."""
    return [split_cells(line) for line in register_table_lines(text)]


def row_from_cells(cells: tuple[str, ...]) -> Row:
    """Build a row from seven cells; raise ``ValueError`` on any other count."""
    if len(cells) != len(REGISTER_COLUMNS):
        msg = f"{cells[0] if cells else '?'}: {len(cells)} cells, expected 7"
        raise ValueError(msg)
    return Row(*cells)


def load_register(path: Path = REGISTER_PATH) -> dict[str, Row]:
    """Parse the register into rows keyed by id; usage error if malformed."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        msg = f"cannot read the register at {path}: {error}"
        raise UsageError(msg) from error
    rows: dict[str, Row] = {}
    for cells in parse_register_cells(text):
        try:
            row = row_from_cells(cells)
        except ValueError as error:
            msg = f"malformed register row: {error}"
            raise UsageError(msg) from error
        rows[row.row_id] = row
    if not rows:
        msg = f"no register table found in {path}"
        raise UsageError(msg)
    return rows


# --------------------------------------------------------------------------- #
# The check registry
# --------------------------------------------------------------------------- #


CheckFunction = Callable[["Run"], str | None]


@dataclass(frozen=True)
class Check:
    """A registered check: its id, its tier and the function that runs it."""

    row_id: str
    tier: str
    function: CheckFunction


CHECKS: dict[str, Check] = {}


def check(row_id: str, *, tier: str) -> Callable[[CheckFunction], CheckFunction]:
    """Register a check by register id and probe tier, nothing else."""
    if tier not in TIERS:
        msg = f"{row_id}: unknown tier {tier!r}"
        raise ValueError(msg)
    if row_id in CHECKS:
        msg = f"{row_id}: registered twice"
        raise ValueError(msg)

    def register(function: CheckFunction) -> CheckFunction:
        CHECKS[row_id] = Check(row_id, tier, function)
        return function

    return register


def registered_ids() -> frozenset[str]:
    """Return the ids the probe can run; the CI gate compares them to the register."""
    return frozenset(CHECKS)


def enabled_tiers(
    *, writes: bool = False, destructive: bool = False, thermal: bool = False
) -> frozenset[str]:
    """Return the tiers a flag set enables: each flag and every tier below it."""
    highest = READ
    if writes:
        highest = WRITE
    if destructive:
        highest = DESTRUCTIVE
    if thermal:
        highest = THERMAL
    return frozenset(TIERS[: TIERS.index(highest) + 1])


def exit_code_for(verdicts: list[str]) -> int:
    """0 when nothing failed; 1 when any check failed."""
    return EXIT_FAILED if FAIL in verdicts else EXIT_OK


# --------------------------------------------------------------------------- #
# Wire values
# --------------------------------------------------------------------------- #


def serialise(value: object) -> str:
    """Render a status value the way the panel accepts it on the wire."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def read_parameter(doc: dict[str, Any], name: str) -> object:
    """Read a writable parameter from a status; open window detection is nested."""
    parameters = doc["parameters"]
    if name == "openWindowDetection":
        return parameters["OWD"]["openWindowDetection"]
    return parameters[name]


def coerce_like(observed: object, parsed: object) -> object:
    """Give a parsed wire value the type the panel stores for that parameter."""
    if isinstance(observed, bool):
        return bool(parsed)
    if isinstance(observed, float) and isinstance(parsed, int | float):
        return float(parsed)
    return parsed


def parse_wire_value(value: str) -> object:
    """Parse a wire string into the JSON type the panel would store."""
    lowered = value.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return float(value)


def on_grid(value: float, step: float = 0.5) -> bool:
    """Return whether a temperature sits on the panel's grid."""
    return math.isclose(round(value / step) * step, value, abs_tol=1e-9)


def grid_floor(value: float) -> float:
    """Return the 0.5 grid value at or below ``value``."""
    return math.floor(value * 2) / 2


def grid_ceil(value: float) -> float:
    """Return the 0.5 grid value at or above ``value``."""
    return math.ceil(value * 2) / 2


# --------------------------------------------------------------------------- #
# Thermal guards
# --------------------------------------------------------------------------- #


def assert_thermal_setpoint(*, room_temperature: float, target: float) -> None:
    """Refuse a setpoint more than the allowed margin above the room."""
    if target - room_temperature > THERMAL_MAX_ABOVE_ROOM + 1e-9:
        msg = (
            f"refusing setpoint {target:.1f} °C: more than "
            f"{THERMAL_MAX_ABOVE_ROOM} °C above the room at {room_temperature:.1f}"
        )
        raise ThermalRefusedError(msg)


def thermal_target(room_temperature: float, *, maximum_limit: float) -> float:
    """Return a thermal check's setpoint: room + 1, rounded up to the grid."""
    target = grid_ceil(room_temperature + 1.0)
    assert_thermal_setpoint(room_temperature=room_temperature, target=target)
    if target > maximum_limit:
        msg = (
            f"refusing: the maximum limit {maximum_limit:.1f} °C is below the "
            f"target {target:.1f} °C"
        )
        raise ThermalRefusedError(msg)
    return target


# --------------------------------------------------------------------------- #
# The panel
# --------------------------------------------------------------------------- #


@dataclass
class Response:
    """An HTTP response as received: status, headers and the raw body bytes."""

    status: int
    reason: str
    headers: dict[str, str]
    body: bytes
    raw_headers: bytes
    elapsed: float = 0.0

    def header(self, name: str) -> str | None:
        """Return a header value by case-insensitive name."""
        lowered = name.lower()
        for key, value in self.headers.items():
            if key.lower() == lowered:
                return value
        return None

    def json(self) -> Any:  # noqa: ANN401  # a JSON document is any shape
        """Return the body parsed as JSON."""
        return json.loads(self.body.decode("utf-8"))


@dataclass
class Status:
    """A status read: the raw bytes, the headers and the parsed document."""

    raw: bytes
    headers: dict[str, str]
    doc: dict[str, Any]

    @property
    def parameters(self) -> dict[str, Any]:
        """The parameters object."""
        parameters: dict[str, Any] = self.doc["parameters"]
        return parameters

    @property
    def room_temperature(self) -> float:
        """The room temperature."""
        return float(self.doc["roomTemperature"])


class PanelLike(Protocol):
    """What the ledger needs from a panel: read the status, write a parameter."""

    host: str
    port: int

    def status(self) -> Status:
        """Read the status."""
        ...

    def write(self, name: str, value: str) -> Response:
        """Write one parameter."""
        ...


class Panel:
    """Raw HTTP to one panel over ``http.client``; one connection per request."""

    def __init__(self, host: str, port: int = 80) -> None:
        """Remember where the panel is."""
        self.host = host
        self.port = port

    def connection(self) -> http.client.HTTPConnection:
        """Open a fresh connection."""
        return http.client.HTTPConnection(self.host, self.port, timeout=REQUEST_TIMEOUT)

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        """Send one request on a fresh connection and read the whole response."""
        conn = self.connection()
        started = time.monotonic()
        try:
            conn.request(method, path, body=body, headers=headers or {})
            raw = conn.getresponse()
            body_bytes = raw.read()
            header_items = list(raw.getheaders())
        finally:
            conn.close()
        raw_headers = "".join(f"{k}: {v}\r\n" for k, v in header_items).encode()
        return Response(
            status=raw.status,
            reason=raw.reason,
            headers=dict(header_items),
            body=body_bytes,
            raw_headers=raw_headers,
            elapsed=time.monotonic() - started,
        )

    def read_status(self) -> Response:
        """``GET /api/status`` as a response."""
        return self.request("GET", "/api/status")

    def status(self) -> Status:
        """Read the status; usage error if the panel does not answer 200 JSON."""
        response = self.read_status()
        if response.status != HTTPStatus.OK:
            msg = f"GET /api/status returned {response.status} {response.reason}"
            raise UsageError(msg)
        return Status(raw=response.body, headers=response.headers, doc=response.json())

    def write(self, name: str, value: str) -> Response:
        """Write one parameter through the query string, with no body."""
        return self.write_query(f"{name}={value}")

    def write_query(
        self,
        query: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        """``POST /api/parameters`` with any query string."""
        path = f"/api/parameters?{query}" if query else "/api/parameters"
        return self.request("POST", path, body=body, headers=headers)

    def reset_kwh(self) -> Response:
        """``DELETE /api/reset/kwh`` without the documented parameter (Q7's point)."""
        return self.request("DELETE", "/api/reset/kwh")

    def reset_settings(self) -> Response:
        """``DELETE /api/reset/settings``."""
        return self.request("DELETE", "/api/reset/settings")

    def raw_socket(self, timeout: float = REQUEST_TIMEOUT) -> socket.socket:
        """Open a TCP socket for the checks that speak HTTP by hand."""
        return socket.create_connection((self.host, self.port), timeout=timeout)


def raw_exchange(sock: socket.socket, request: bytes) -> Response | None:
    """Send request bytes and read one response; ``None`` if the peer closed."""
    started = time.monotonic()
    sock.sendall(request)
    buffer = b""
    while b"\r\n\r\n" not in buffer:
        chunk = sock.recv(4096)
        if not chunk:
            return None
        buffer += chunk
    head, _, rest = buffer.partition(b"\r\n\r\n")
    status_line, _, header_block = head.partition(b"\r\n")
    headers: dict[str, str] = {}
    for line in header_block.decode("latin-1").splitlines():
        key, _, value = line.partition(":")
        headers[key.strip()] = value.strip()
    length = int(headers.get("Content-Length", "0") or 0)
    body = rest
    while len(body) < length:
        chunk = sock.recv(4096)
        if not chunk:
            break
        body += chunk
    parts = status_line.decode("latin-1").split(" ", 2)
    _, status_text, reason = [*parts, "", ""][:3]
    status = int(status_text) if status_text.isdigit() else 0
    return Response(
        status=status,
        reason=reason,
        headers=headers,
        body=body[:length] if length else body,
        raw_headers=header_block + b"\r\n",
        elapsed=time.monotonic() - started,
    )


# --------------------------------------------------------------------------- #
# The restore ledger
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RestoreFailure:
    """A parameter the panel did not confirm back at its original value."""

    parameter: str
    original: str
    observed: str


def restore_order(names: list[str]) -> list[str]:
    """Limits first, widest first, then in the order they were touched."""
    ordered = [name for name in RESTORE_FIRST if name in names]
    ordered += [name for name in names if name not in RESTORE_FIRST]
    return ordered


class Ledger:
    """Snapshot the status before the first write; restore and verify on exit."""

    def __init__(
        self,
        panel: PanelLike,
        *,
        snapshot_dir: Path = SNAPSHOT_DIR,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Bind to a panel; nothing is read until a parameter is touched."""
        self.panel = panel
        self.snapshot_dir = snapshot_dir
        self.sleep = sleep
        self.snapshot_path: Path | None = None
        self.snapshot_doc: dict[str, Any] | None = None
        self.originals: dict[str, str] = {}
        self.touched: list[str] = []

    @classmethod
    def from_snapshot(
        cls,
        path: Path,
        panel: PanelLike,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> Ledger:
        """Rebuild a ledger from a snapshot file, for ``--restore``."""
        data = json.loads(path.read_text(encoding="utf-8"))
        ledger = cls(panel, snapshot_dir=path.parent, sleep=sleep)
        ledger.snapshot_path = path
        ledger.snapshot_doc = data["status"]
        for name in data["touched"]:
            ledger.touched.append(name)
            ledger.originals[name] = serialise(read_parameter(data["status"], name))
        return ledger

    @property
    def pending(self) -> tuple[str, ...]:
        """The parameters touched and not yet verified back at their original."""
        return tuple(self.touched)

    def take_snapshot(self) -> dict[str, Any]:
        """Read the status once and write it beside the touched list."""
        if self.snapshot_doc is None:
            self.snapshot_doc = self.panel.status().doc
            stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
            self.snapshot_dir.mkdir(parents=True, exist_ok=True)
            self.snapshot_path = self.snapshot_dir / f"probe-snapshot-{stamp}.json"
            self.save()
        return self.snapshot_doc

    def save(self) -> None:
        """Rewrite the snapshot file with the current touched list."""
        if self.snapshot_path is None:
            return
        document = {
            "host": self.panel.host,
            "port": self.panel.port,
            "touched": self.touched,
            "status": self.snapshot_doc,
        }
        self.snapshot_path.write_text(
            json.dumps(document, indent=1, ensure_ascii=False), encoding="utf-8"
        )

    def touch(self, name: str) -> None:
        """Register a parameter for restore before the first write to it."""
        if name not in WRITABLE_PARAMETERS:
            msg = f"{name} is not a writable parameter"
            raise ValueError(msg)
        doc = self.take_snapshot()
        if name in self.originals:
            return
        self.originals[name] = serialise(read_parameter(doc, name))
        self.touched.append(name)
        self.save()

    def original(self, name: str) -> str:
        """Return the wire value a touched parameter held before the run."""
        return self.originals[name]

    def restore(self) -> list[RestoreFailure]:
        """Write every touched parameter back, then verify from a status read."""
        names = restore_order(self.touched)
        failures = self.write_originals(names)
        remaining = [name for name in names if name not in failures]
        for attempt in range(2):
            if not remaining:
                break
            self.sleep(REFLECT_BOUND)
            remaining = self.verify(remaining, failures, last_attempt=attempt == 1)
        self.touched = [name for name in self.touched if name in failures]
        for name in list(self.originals):
            if name not in failures:
                self.originals.pop(name)
        self.save()
        return [failures[name] for name in names if name in failures]

    def write_originals(self, names: list[str]) -> dict[str, RestoreFailure]:
        """Write each original back; a write that errors is already a failure."""
        failures: dict[str, RestoreFailure] = {}
        for name in names:
            original = self.originals[name]
            try:
                self.panel.write(name, original)
            except (OSError, http.client.HTTPException) as error:
                failures[name] = RestoreFailure(
                    name, original, f"write failed: {error}"
                )
        return failures

    def verify(
        self,
        names: list[str],
        failures: dict[str, RestoreFailure],
        *,
        last_attempt: bool,
    ) -> list[str]:
        """Read the status once; return the names still not at their original."""
        try:
            doc = self.panel.status().doc
        except (OSError, http.client.HTTPException, UsageError) as error:
            if last_attempt:
                for name in names:
                    failures[name] = RestoreFailure(
                        name, self.originals[name], f"status unreadable: {error}"
                    )
            return names
        still: list[str] = []
        for name in names:
            observed = serialise(read_parameter(doc, name))
            if observed == self.originals[name]:
                failures.pop(name, None)
                continue
            still.append(name)
            failures[name] = RestoreFailure(name, self.originals[name], observed)
        return still


def restore_banner(host: str, port: int, failures: list[RestoreFailure]) -> str:
    """Render the loud banner: what is wrong and the curl that fixes it by hand."""
    lines = [
        "",
        "!!! RESTORE FAILED: the panel is NOT back in its original state.",
        f"!!! Panel: {host}:{port}. Fix each parameter by hand and re-check status:",
    ]
    for failure in failures:
        lines.append(
            f"  {failure.parameter}: original {failure.original}, "
            f"now {failure.observed}"
        )
        lines.append(
            f"    curl -X POST 'http://{host}:{port}/api/parameters?"
            f"{failure.parameter}={failure.original}'"
        )
    lines.append(f"  then: curl 'http://{host}:{port}/api/status'")
    return "\n".join(lines)


def replay_snapshot(
    path: Path, panel: PanelLike, *, sleep: Callable[[float], None] = time.sleep
) -> list[RestoreFailure]:
    """``--restore <file>``: rewrite what a dead run touched, and verify."""
    ledger = Ledger.from_snapshot(path, panel, sleep=sleep)
    return ledger.restore()


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


class FixtureStore:
    """Save write and reset responses as raw bytes; refuse anything identifying."""

    def __init__(self, directory: Path, *, secrets: tuple[str, ...]) -> None:
        """Bind to a directory (created on first save) and the values to refuse."""
        self.directory = directory
        self.secrets = tuple(secret for secret in secrets if secret)
        self.saved: list[Path] = []
        self.kept: list[Path] = []
        """Fixtures a run did not overwrite, because they already exist."""

    def check_scrubbable(self, body: bytes) -> None:
        """Refuse the save if the body carries a scrub key or an identifying value."""
        for key in SCRUB_KEYS:
            if f'"{key}"'.encode() in body:
                msg = f"response carries the scrub key {key!r}; not saved"
                raise ScrubViolationError(msg)
        for secret in self.secrets:
            if secret.encode("utf-8") in body:
                msg = "response carries an identifying value; not saved"
                raise ScrubViolationError(msg)

    def save(self, name: str, response: Response) -> Path:
        """Write ``<name>.json`` or ``<name>.txt`` plus ``<name>.headers``.

        **A fixture already in the tree is never overwritten.** A committed
        fixture is reviewed evidence, and a probe run is not a review. Three
        runs in a row rewrote the heating-setpoint echo to whatever value the
        room temperature implied that hour. Once that lost the integer the
        fixture existed to show. Once it reached a commit unnoticed inside a
        ``git add -A``. A new firmware's directory is empty, so a capture there
        still lands. Refreshing an existing one is done on purpose: delete
        the file and run again.
        """
        self.check_scrubbable(response.body)
        content_type = response.header("Content-Type") or ""
        suffix = ".json" if "json" in content_type else ".txt"
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{name}{suffix}"
        if path.exists():
            self.kept.append(path)
            return path
        path.write_bytes(response.body)
        path.with_suffix(".headers").write_bytes(response.raw_headers)
        self.saved.append(path)
        return path


# --------------------------------------------------------------------------- #
# The run context and its helpers
# --------------------------------------------------------------------------- #


#: Seconds into the sequence, the relay state, the power draw.
RelaySample = tuple[float, str, int]
#: Seconds into the watch, the status document read then.
StatusSample = tuple[float, dict[str, Any]]


@dataclass
class HeatOutcome:
    """What one heater-on sequence recorded."""

    timeline: list[RelaySample]
    heating_at: float | None
    power_at: float | None
    idle_at: float | None
    power_zero_at: float | None


@dataclass
class KwhResetOutcome:
    """What one kWh reset recorded."""

    before: float
    response: Response
    zero_after: float | None
    raw_after: bytes


@dataclass
class SettingsResetOutcome:
    """What one settings reset recorded."""

    before: Status
    response: Response
    timeline: list[StatusSample]
    read_failures: int
    nudged: dict[str, str]
    """Each parameter confirmed off its documented default first, and at what.

    A parameter missing from here could not be moved off its default
    (:func:`nudge_plan`). So if the reset leaves it there, that proves nothing
    about it either way.
    """


@dataclass
class Run:
    """Everything a check may reach: panel, ledger, fixtures and shared outcomes."""

    panel: Panel
    ledger: Ledger
    fixtures: FixtureStore | None
    measurements: dict[str, str] = field(default_factory=dict)
    #: Outcomes shared by the rows that one reset or one heater-on sequence serves.
    shared: dict[str, Any] = field(default_factory=dict)
    sleep: Callable[[float], None] = time.sleep

    def measure(self, key: str, value: str) -> None:
        """Record a measurement for the measurements block."""
        self.measurements[key] = value

    def save_fixture(self, name: str, response: Response) -> None:
        """Save a response as a fixture when writes are enabled; refuse a scrub hit."""
        if self.fixtures is None:
            return
        try:
            self.fixtures.save(name, response)
        except ScrubViolationError as error:
            self.measure(f"fixture {name}", f"refused: {error}")

    def write(self, name: str, value: str) -> Response:
        """Register the parameter for restore, then write it."""
        self.ledger.touch(name)
        return self.panel.write(name, value)

    def reflect(self, name: str, wire_value: str) -> tuple[Status, float | None]:
        """Poll the status until a parameter shows a value; ``None`` if it never did."""
        started = time.monotonic()
        status = self.panel.status()
        wanted = parse_wire_value(wire_value)
        while True:
            elapsed = time.monotonic() - started
            observed = read_parameter(status.doc, name)
            if serialise(observed) == serialise(coerce_like(observed, wanted)):
                return status, elapsed
            if elapsed >= REFLECT_DEADLINE:
                return status, None
            self.sleep(REFLECT_POLL)
            status = self.panel.status()

    def write_applied(self, name: str, value: str) -> Response:
        """Write and require both a 200 and the status to show it."""
        response = self.write(name, value)
        expect(
            response.status == HTTPStatus.OK,
            f"{name}={value}: expected 200, got {response.status} "
            f"{body_text(response)}",
        )
        _, elapsed = self.reflect(name, value)
        expect(elapsed is not None, f"{name}={value}: status never showed it")
        return response

    def write_rejected(self, name: str, value: str) -> Response:
        """Write and require a 400."""
        response = self.write(name, value)
        expect(
            response.status == HTTPStatus.BAD_REQUEST,
            f"{name}={value}: expected 400, got {response.status} "
            f"{body_text(response)}",
        )
        return response


def expect(condition: bool, message: str) -> None:  # noqa: FBT001  # an assertion
    """Fail the check unless the condition holds."""
    if not condition:
        raise CheckFailedError(message)


def require[T](value: T | None, message: str) -> T:
    """Fail the check when a value is missing; otherwise return it."""
    if value is None:
        raise CheckFailedError(message)
    return value


def body_text(response: Response, limit: int = 120) -> str:
    """Render a response body as short printable text."""
    text = response.body.decode("utf-8", errors="replace").strip()
    return text[:limit]


def cold_setpoint(status: Status, *, offset: float = COLD_OFFSET) -> float:
    """Pick a setpoint safely below the room and inside the limits, on the grid."""
    parameters = status.parameters
    minimum = float(parameters["minimumTemperatureLimit"])
    maximum = float(parameters["maximumTemperatureLimit"])
    value = grid_floor(status.room_temperature - offset)
    if value < minimum + 1.0 or value > maximum:
        msg = (
            f"no setpoint at least {offset} °C below the room "
            f"({status.room_temperature:.1f} °C) fits inside the limits "
            f"{minimum:.1f}-{maximum:.1f}"
        )
        raise Inconclusive(msg)
    return value


def other_brightness(current: int) -> int:
    """Pick a standby brightness that differs from the current one."""
    return 1 if current != 1 else 2


def walk_for_null(value: object, path: str = "") -> list[str]:
    """Return every path in a JSON document whose value is ``null``."""
    found: list[str] = []
    if value is None:
        found.append(path or "<root>")
    elif isinstance(value, dict):
        for key, inner in value.items():
            found += walk_for_null(inner, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        for index, inner in enumerate(value):
            found += walk_for_null(inner, f"{path}[{index}]")
    return found


def openapi_defaults(path: Path = OPENAPI_PATH) -> dict[str, object]:
    """Read the vendor document's stated default for each writable parameter."""
    defaults: dict[str, object] = {}
    current: str | None = None
    in_schemas = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip("\r")
        if line == "  schemas:":
            in_schemas = True
            continue
        if not in_schemas:
            continue
        schema = re.fullmatch(r" {4}(\w+):\s*", line)
        if schema:
            current = schema.group(1)
            continue
        default = re.fullmatch(r"\s+default:\s*(\S+)\s*", line)
        if default and current in WRITABLE_PARAMETERS and current not in defaults:
            defaults[current] = parse_wire_value(default.group(1))
    return defaults


# --------------------------------------------------------------------------- #
# Read-tier checks
# --------------------------------------------------------------------------- #


@check("Q10", tier=READ)
def signal_strength_is_signed(run: Run) -> str | None:
    """``wifiSignalStrength`` is ``"-NNdBm"``."""
    value = run.panel.status().doc["Network"]["wifiSignalStrength"]
    expect(isinstance(value, str), f"wifiSignalStrength is {value!r}, not a string")
    expect(re.fullmatch(r"-\d+dBm", value) is not None, f"read {value!r}")
    return f"read {value!r}"


@check("Q11", tier=READ)
def network_status_is_ok(run: Run) -> str | None:
    """``Network.status`` reads ``"ok"``."""
    value = run.panel.status().doc["Network"]["status"]
    expect(value == "ok", f"read {value!r}")
    return None


@check("Q12", tier=READ)
def mac_is_uppercase_with_colons(run: Run) -> str | None:
    """``Network.mac`` is uppercase hex with colons."""
    mac = run.panel.status().doc["Network"]["mac"]
    expect(
        re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", mac) is not None,
        "the MAC is not uppercase colon-separated hex",
    )
    if not re.search(r"[A-F]", mac):
        msg = "this MAC has no letters, so its case cannot be told"
        raise Inconclusive(msg)
    return None


@check("Q18", tier=WRITE)
def state_is_idle_when_off(run: Run) -> str | None:
    """Switch the panel Off and expect the relay state to read idle."""
    run.write_applied("panelMode", str(MODE_OFF))
    run.sleep(REFLECT_BOUND)
    seen = {run.panel.status().doc["state"] for _ in range(3)}
    expect(seen == {"Idle"}, f"state read {sorted(seen)} while Off")
    return None


@check("Q22", tier=READ)
def consumption_has_two_decimals_on_the_wire(run: Run) -> str | None:
    """Check the energy counter's wire literal for exactly two decimals."""
    raw = run.panel.status().raw
    match = require(
        re.search(rb'"totalConsumption"\s*:\s*(-?\d+\.\d+)', raw),
        "totalConsumption is not a decimal on the wire",
    )
    literal = match.group(1).decode()
    expect(len(literal.split(".")[1]) == 2, f"wire literal is {literal}")  # noqa: PLR2004
    return f"wire literal {literal}"


@check("Q24", tier=READ)
def no_field_is_null(run: Run) -> str | None:
    """No status field is ever ``null``."""
    status = run.panel.status()
    nulls = walk_for_null(status.doc)
    expect(not nulls, f"null at {', '.join(nulls)}")
    expect(b"null" not in status.raw, "the bytes carry a null token")
    return f"{len(status.doc['parameters'])} parameter keys, none null"


@check("Q25", tier=READ)
def open_window_active_time_is_zero_when_inactive(run: Run) -> str | None:
    """Check the open-window countdown reads zero while no detection is active."""
    owd = run.panel.status().parameters["OWD"]
    if owd["activeNow"]:
        msg = "open window detection is active right now"
        raise Inconclusive(msg)
    expect(owd["activeTime"] == 0, f"activeTime is {owd['activeTime']}")
    return None


@check("Q27", tier=READ)
def name_and_room_are_free_text(run: Run) -> str | None:
    """``name`` and ``room`` are strings; ``room`` may be empty."""
    doc = run.panel.status().doc
    expect(isinstance(doc["name"], str), f"name is {type(doc['name']).__name__}")
    expect(isinstance(doc["room"], str), f"room is {type(doc['room']).__name__}")
    return "room is " + ("assigned" if doc["room"] else '""')


@check("Q29", tier=READ)
def unknown_paths_are_the_cherrypy_404(run: Run) -> str | None:
    """Check that an unknown path and ``/`` are the same ``text/html`` 404."""
    for path in ("/", "/no-such-path", "/api", "/api/Status"):
        response = run.panel.request("GET", path)
        expect(
            response.status == HTTPStatus.NOT_FOUND,
            f"GET {path} returned {response.status}",
        )
        content_type = response.header("Content-Type") or ""
        expect(content_type.startswith("text/html"), f"{path}: {content_type!r}")
        expect(response.body == NOT_FOUND_BODY, f"{path}: body {body_text(response)!r}")
        if path == "/no-such-path":
            run.save_fixture("error-404-unknown-path", response)
    head = run.panel.request("HEAD", "/api/status")
    run.measure("Q29 HEAD /api/status", f"{head.status} {head.reason}")
    return None


@check("Q30", tier=READ)
def accepts_concurrent_connections(run: Run) -> str | None:
    """At least two concurrent connections are served."""
    barrier = threading.Barrier(CONCURRENT_CONNECTIONS)

    def one() -> float | None:
        try:
            barrier.wait(timeout=REQUEST_TIMEOUT)
            response = run.panel.read_status()
        except OSError, http.client.HTTPException, threading.BrokenBarrierError:
            return None
        return response.elapsed if response.status == HTTPStatus.OK else None

    with ThreadPoolExecutor(max_workers=CONCURRENT_CONNECTIONS) as pool:
        outcomes = list(pool.map(lambda _: one(), range(CONCURRENT_CONNECTIONS)))
    served = [elapsed for elapsed in outcomes if elapsed is not None]
    run.measure(
        "Q30 concurrent",
        f"{len(served)}/{CONCURRENT_CONNECTIONS} served"
        + (f", slowest {max(served):.3f} s" if served else ""),
    )
    expect(
        len(served) >= CONCURRENT_REQUIRED,
        f"only {len(served)} of {CONCURRENT_CONNECTIONS} concurrent reads served",
    )
    return f"{len(served)}/{CONCURRENT_CONNECTIONS} served"


@check("Q33", tier=READ)
def only_port_80_answers(run: Run) -> str | None:
    """Only tcp/80 accepts, and nothing on it redirects."""
    open_ports: list[int] = []
    for port in PORTS_TO_TRY:
        try:
            with socket.create_connection((run.panel.host, port), CONNECT_TIMEOUT):
                open_ports.append(port)
        except OSError:
            continue
    run.measure("Q33 open ports", ", ".join(map(str, open_ports)) or "none")
    expect(open_ports == [80], f"open ports: {open_ports}")
    response = run.panel.request("GET", "/")
    expect(response.header("Location") is None, "GET / carried a Location header")
    return None


@check("Q35", tier=READ)
def no_api_version_is_exposed(run: Run) -> str | None:
    """Only ``Content-Type`` and ``Content-Length`` come back; no version anywhere."""
    status = run.panel.status()
    names = sorted(key.lower() for key in status.headers)
    expect(names == ["content-length", "content-type"], f"headers: {names}")
    for path in ("/api/version", "/version", "/api/info"):
        response = run.panel.request("GET", path)
        expect(response.status == HTTPStatus.NOT_FOUND, f"{path} → {response.status}")
    return f"firmware {status.doc['firmware']!r}; headers {names}"


@check("Q39", tier=READ)
def http_1_0_is_refused_with_505(run: Run) -> str | None:
    """Check that an HTTP/1.0 request is refused with 505."""
    request = f"GET /api/status HTTP/1.0\r\nHost: {run.panel.host}\r\n\r\n".encode()
    with run.panel.raw_socket() as sock:
        response = require(
            raw_exchange(sock, request),
            "the panel closed the connection with no response",
        )
    expect(
        response.status == HTTPStatus.HTTP_VERSION_NOT_SUPPORTED,
        f"HTTP/1.0 got {response.status} {response.reason}",
    )
    run.save_fixture("error-505-http10", response)
    return f"{response.status} {response.reason}"


@check("Q40", tier=READ)
def responses_carry_content_length(run: Run) -> str | None:
    """Responses carry ``Content-Length`` and never chunked transfer."""
    response = run.panel.read_status()
    expect(response.header("Content-Length") is not None, "no Content-Length")
    expect(response.header("Transfer-Encoding") is None, "Transfer-Encoding present")
    expect(
        int(response.header("Content-Length") or 0) == len(response.body),
        "Content-Length does not match the body",
    )
    return None


@check("Q41", tier=READ)
def success_is_application_json(run: Run) -> str | None:
    """Success responses carry ``Content-Type: application/json``."""
    content_type = require(
        run.panel.read_status().header("Content-Type"),
        "no Content-Type on the status",
    )
    expect(
        content_type.split(";")[0].strip() == "application/json",
        f"Content-Type is {content_type!r}",
    )
    return f"Content-Type {content_type!r}"


@check("Q42", tier=READ)
def keep_alive_survives_an_idle_minute(run: Run) -> str | None:
    """Check that an idle keep-alive socket is still served after 65 s."""
    request = f"GET /api/status HTTP/1.1\r\nHost: {run.panel.host}\r\n\r\n".encode()
    with run.panel.raw_socket(timeout=REQUEST_TIMEOUT) as sock:
        first = raw_exchange(sock, request)
        expect(first is not None and first.status == HTTPStatus.OK, "first read failed")
        run.sleep(KEEPALIVE_IDLE)
        try:
            second = raw_exchange(sock, request)
        except OSError as error:
            msg = f"second request after {KEEPALIVE_IDLE:.0f} s idle: {error}"
            raise CheckFailedError(msg) from error
    served = require(second, f"socket closed within {KEEPALIVE_IDLE:.0f} s idle")
    expect(served.status == HTTPStatus.OK, f"second read got {served.status}")
    return f"served after {KEEPALIVE_IDLE:.0f} s idle"


@check("Q43", tier=READ)
def status_read_is_fast(run: Run) -> str | None:
    """Check that a status read completes in under 5 s."""
    timings = [run.panel.read_status().elapsed for _ in range(STATUS_SAMPLES)]
    run.measure(
        "Q43 status read",
        f"{min(timings) * 1000:.0f}-{max(timings) * 1000:.0f} ms over "
        f"{STATUS_SAMPLES} fresh connections",
    )
    expect(max(timings) < STATUS_READ_BOUND, f"slowest read {max(timings):.2f} s")
    return f"{min(timings) * 1000:.0f}-{max(timings) * 1000:.0f} ms"


@check("Q54", tier=READ)
def status_is_computed_per_request(run: Run) -> str | None:
    """Consecutive reads differ somewhere, so the status is not cached."""
    samples = [run.panel.status().raw]
    for _ in range(CACHE_SAMPLES - 1):
        run.sleep(CACHE_INTERVAL)
        samples.append(run.panel.status().raw)
    distinct = len(set(samples))
    run.measure("Q54 distinct bodies", f"{distinct} of {CACHE_SAMPLES}")
    if distinct == 1:
        msg = (
            f"{CACHE_SAMPLES} reads over {CACHE_INTERVAL * (CACHE_SAMPLES - 1):.0f} s "
            f"were byte-identical: a cache and a quiet panel look the same"
        )
        raise Inconclusive(msg)
    return f"{distinct} distinct bodies of {CACHE_SAMPLES}"


# --------------------------------------------------------------------------- #
# Write-tier checks
# --------------------------------------------------------------------------- #


@check("Q1", tier=WRITE)
def temperatures_snap_and_limits_reject(run: Run) -> str | None:
    """Setpoints accept bare integers and snap off-step values; limits reject them."""
    status = run.panel.status()
    cold = cold_setpoint(status)
    off_step = round(cold + 0.3, 1)
    response = run.write("heatingSetpoint", f"{off_step:.1f}")
    expect(response.status == HTTPStatus.OK, f"off-step got {response.status}")
    run.sleep(REFLECT_BOUND)
    stored = float(run.panel.status().parameters["heatingSetpoint"])
    expect(on_grid(stored), f"{off_step} was stored as {stored}, off the grid")
    run.measure("Q1 snap", f"{off_step} → {stored}")
    run.write_applied("heatingSetpoint", str(int(cold)))
    minimum = float(status.parameters["minimumTemperatureLimit"])
    run.write_rejected("minimumTemperatureLimit", f"{minimum + 0.3:.1f}")
    return f"snapped {off_step} → {stored}; bare {int(cold)} applied; limit rejected"


@check("Q2", tier=WRITE)
def decimals_on_integer_parameters_are_rejected(run: Run) -> str | None:
    """``panelMode=1.0`` and the like are rejected, not truncated."""
    parameters = run.panel.status().parameters
    run.write_rejected("panelMode", f"{parameters['panelMode']}.0")
    run.write_rejected(
        "standbyDisplayBrightness", f"{parameters['standbyDisplayBrightness']}.0"
    )
    return None


@check("Q3", tier=WRITE)
def boolean_spellings_apply(run: Run) -> str | None:
    """Every documented spelling of true and false applies; none is misread."""
    spellings = (
        ("False", False),
        ("True", True),
        ("FALSE", False),
        ("TRUE", True),
        ("0", False),
        ("1", True),
        ("false", False),
        ("true", True),
    )
    for spelling, expected in spellings:
        run.write_applied("temperatureDisplay", spelling)
        stored = read_parameter(run.panel.status().doc, "temperatureDisplay")
        expect(stored is expected, f"{spelling!r} stored as {stored!r}")
    run.write_rejected("temperatureDisplay", "yes")
    return "8 spellings applied; 'yes' rejected"


@check("Q4", tier=WRITE)
def multi_parameter_writes_are_atomic(run: Run) -> str | None:
    """Check that one valid plus one out-of-range parameter applies neither."""
    status = run.panel.status()
    cold = cold_setpoint(status)
    if math.isclose(cold, float(status.parameters["heatingSetpoint"])):
        cold -= 0.5
    run.ledger.touch("heatingSetpoint")
    run.ledger.touch("activeDisplayBrightness")
    response = run.panel.write_query(
        f"heatingSetpoint={cold:.1f}&activeDisplayBrightness={OUT_OF_RANGE_BRIGHTNESS}"
    )
    run.sleep(REFLECT_BOUND)
    after = run.panel.status().parameters
    applied = math.isclose(float(after["heatingSetpoint"]), cold)
    run.measure(
        "Q4 multi-parameter", f"{response.status}; valid half applied: {applied}"
    )
    expect(not applied, f"got {response.status} and the valid half was applied")
    expect(response.status != HTTPStatus.OK, f"got 200 {body_text(response)}")
    return f"{response.status}; neither applied"


@check("Q5", tier=WRITE)
def echo_reports_the_applied_value(run: Run) -> str | None:
    """Check that the echo uses the name sent and the value applied."""
    status = run.panel.status()
    cold = cold_setpoint(status)
    # Use a **whole** degree wherever one is also safely below the room. This
    # check exists to show type normalisation: `20` coming back for `20.0`.
    # Only an integer-valued setpoint can show it; a `.5` echoes `20.5` and
    # says nothing about the type. This is also why the committed fixture kept
    # drifting. `cold_setpoint` lands on a half degree whenever the room does,
    # so two runs in a row rewrote the evidence away.
    floor = float(math.floor(cold))
    minimum = float(status.parameters["minimumTemperatureLimit"])
    cold = floor if floor >= minimum + 1.0 else cold
    response = run.write_applied("heatingSetpoint", f"{cold:.1f}")
    echo = response.json()
    expect("heatingSetpoint" in echo, f"echo keys {sorted(echo)}")
    expect(
        math.isclose(float(echo["heatingSetpoint"]), cold),
        f"echo {echo['heatingSetpoint']!r} for {cold:.1f}",
    )
    run.save_fixture("write-echo-heatingSetpoint", response)
    kind = type(echo["heatingSetpoint"]).__name__
    run.measure(
        "Q5 echo type", f"sent {cold:.1f}, echo {echo['heatingSetpoint']!r} ({kind})"
    )
    return f"echo {body_text(response)}"


@check("Q6", tier=WRITE)
def writing_the_current_value_is_200(run: Run) -> str | None:
    """Check that writing a parameter to its current value returns 200."""
    current = run.panel.status().parameters["activeDisplayBrightness"]
    response = run.write("activeDisplayBrightness", str(current))
    expect(response.status == HTTPStatus.OK, f"got {response.status}")
    return None


@check("Q8", tier=WRITE)
def query_string_writes_apply(run: Run) -> str | None:
    """Check that a query-string write applies; a JSON body is only recorded."""
    current = int(run.panel.status().parameters["standbyDisplayBrightness"])
    run.write_applied("standbyDisplayBrightness", str(other_brightness(current)))
    body = json.dumps({"standbyDisplayBrightness": current}).encode()
    response = run.panel.write_query(
        "", body=body, headers={"Content-Type": "application/json"}
    )
    _, elapsed = run.reflect("standbyDisplayBrightness", str(current))
    run.measure("Q8 JSON body", f"{response.status}, applied: {elapsed is not None}")
    return f"query string applied; JSON body {response.status}"


@check("Q9", tier=WRITE)
def body_less_post_is_accepted(run: Run) -> str | None:
    """Check that a ``Content-Length: 0`` POST with a query string is accepted."""
    current = run.panel.status().parameters["activeDisplayBrightness"]
    run.ledger.touch("activeDisplayBrightness")
    response = run.panel.write_query(
        f"activeDisplayBrightness={current}", headers={"Content-Length": "0"}
    )
    expect(response.status == HTTPStatus.OK, f"got {response.status}")
    expect(SUCCESS_SENTINEL in response.body, f"body {body_text(response)}")
    return None


@check("Q14", tier=WRITE)
def either_bank_is_writable_in_any_mode(run: Run) -> str | None:
    """Both setpoint banks accept a write in the current mode and in the other."""
    status = run.panel.status()
    cold = cold_setpoint(status)
    mode = int(status.parameters["panelMode"])
    other_mode = MODE_ECO if mode != MODE_ECO else MODE_HEATING
    run.ledger.touch("panelMode")
    for target_mode in (mode, other_mode):
        run.write_applied("panelMode", str(target_mode))
        run.write_applied("heatingSetpoint", f"{cold:.1f}")
        run.write_applied("ecoSetpoint", f"{cold - 0.5:.1f}")
    started = time.monotonic()
    state = run.panel.status().doc["state"]
    while state != "Idle" and time.monotonic() - started < STATUS_READ_BOUND:
        run.sleep(1.0)
        state = run.panel.status().doc["state"]
    expect(state == "Idle", f"relay {state} with both banks below the room")
    return f"both banks written in modes {mode} and {other_mode}"


@check("Q15", tier=WRITE)
def limits_bound_both_banks_and_clamp(run: Run) -> str | None:
    """Limits bound both banks, ``min < max`` holds, narrowing clamps a setpoint."""
    cold = cold_setpoint(run.panel.status())
    run.write_applied("heatingSetpoint", f"{cold:.1f}")
    run.write_applied("ecoSetpoint", f"{cold:.1f}")
    narrowed = cold - 0.5
    run.write_applied("maximumTemperatureLimit", f"{narrowed:.1f}")
    _, heating_clamped = run.reflect("heatingSetpoint", f"{narrowed:.1f}")
    _, eco_clamped = run.reflect("ecoSetpoint", f"{narrowed:.1f}")
    expect(heating_clamped is not None, "narrowing max did not clamp heatingSetpoint")
    expect(eco_clamped is not None, "narrowing max did not clamp ecoSetpoint")
    run.write_rejected("heatingSetpoint", f"{cold:.1f}")
    run.write_rejected("ecoSetpoint", f"{cold:.1f}")
    run.write_rejected("minimumTemperatureLimit", f"{narrowed:.1f}")
    return f"max {narrowed} clamped both banks; above-max and min==max rejected"


@check("Q17", tier=WRITE)
def load_limit_above_max_load_is_rejected(run: Run) -> str | None:
    """``loadLimit`` above ``maxLoad`` is rejected."""
    parameters = run.panel.status().parameters
    max_load = int(parameters["maxLoad"])
    if max_load >= LOAD_LIMIT_MAX:
        msg = f"maxLoad is {max_load}; nothing above it can be sent"
        raise Inconclusive(msg)
    run.write_rejected("loadLimit", str(max_load + 1))
    run.sleep(REFLECT_BOUND)
    stored = run.panel.status().parameters["loadLimit"]
    expect(stored == parameters["loadLimit"], f"loadLimit changed to {stored}")
    return f"loadLimit={max_load + 1} rejected"


@check("Q23", tier=WRITE)
def calibration_shifts_room_temperature(run: Run) -> str | None:
    """``sensorCalibration`` shifts ``roomTemperature`` in the status."""
    status = run.panel.status()
    current = float(status.parameters["sensorCalibration"])
    delta = 1.0 if current + 1.0 <= CALIBRATION_MAX else -1.0
    if delta < 0:
        msg = "calibration is at its maximum; a downward shift could heat"
        raise Inconclusive(msg)
    before = status.room_temperature
    run.write_applied("sensorCalibration", f"{current + delta:.1f}")
    started = time.monotonic()
    while time.monotonic() - started < CALIBRATION_WATCH:
        room = run.panel.status().room_temperature
        if abs(room - (before + delta)) <= CALIBRATION_TOLERANCE:
            elapsed = time.monotonic() - started
            run.measure("Q23 shift", f"{before} → {room} after {elapsed:.1f} s")
            return f"{before} → {room} after {elapsed:.1f} s"
        run.sleep(1.0)
    msg = f"roomTemperature stayed at {before} for {CALIBRATION_WATCH:.0f} s"
    raise CheckFailedError(msg)


@check("Q31", tier=WRITE)
def write_is_reflected_within_the_bound(run: Run) -> str | None:
    """Check that a write is reflected in the status within 1.5 s."""
    current = int(run.panel.status().parameters["standbyDisplayBrightness"])
    value = str(other_brightness(current))
    response = run.write("standbyDisplayBrightness", value)
    expect(response.status == HTTPStatus.OK, f"got {response.status}")
    elapsed = require(
        run.reflect("standbyDisplayBrightness", value)[1], "never reflected"
    )
    run.measure(
        "Q31 write→status",
        f"write {response.elapsed * 1000:.0f} ms, reflected {elapsed * 1000:.0f} ms",
    )
    expect(elapsed <= REFLECT_BOUND, f"reflected after {elapsed:.2f} s")
    return f"reflected after {elapsed * 1000:.0f} ms"


@check("Q36", tier=WRITE)
def sentinels_are_capital_success_and_lowercase_failed(run: Run) -> str | None:
    """``"Success"`` on success and ``"failed"`` on failure, exactly."""
    current = run.panel.status().parameters["activeDisplayBrightness"]
    ok = run.write("activeDisplayBrightness", str(current))
    expect(ok.status == HTTPStatus.OK, f"got {ok.status}")
    expect(SUCCESS_SENTINEL in ok.body, f"success body {body_text(ok)}")
    rejected = run.write_rejected("activeDisplayBrightness", OUT_OF_RANGE_BRIGHTNESS)
    expect(FAILED_SENTINEL in rejected.body, f"failure body {body_text(rejected)}")
    run.save_fixture("error-400-activeDisplayBrightness", rejected)
    return None


@check("Q37", tier=WRITE)
def echo_is_status_plus_the_parameter(run: Run) -> str | None:
    """Check that the 200 body is ``{status, <parameter>}`` and nothing else."""
    current = run.panel.status().parameters["standbyDisplayBrightness"]
    response = run.write("standbyDisplayBrightness", str(current))
    expect(response.status == HTTPStatus.OK, f"got {response.status}")
    keys = set(response.json())
    expect(keys == {"status", "standbyDisplayBrightness"}, f"keys {sorted(keys)}")
    run.save_fixture("write-echo-standbyDisplayBrightness", response)
    return None


@check("Q38", tier=WRITE)
def identical_writes_are_harmless(run: Run) -> str | None:
    """Re-sending an identical write returns 200 again."""
    current = run.panel.status().parameters["activeDisplayBrightness"]
    statuses = [
        run.write("activeDisplayBrightness", str(current)).status for _ in range(2)
    ]
    expect(statuses == [HTTPStatus.OK, HTTPStatus.OK], f"got {statuses}")
    return None


@check("Q55", tier=WRITE)
def parameter_less_post_gets_no_response(run: Run) -> str | None:
    """Check that a parameter-less POST is answered by closing the connection."""
    try:
        response = run.panel.write_query("")
    except http.client.RemoteDisconnected, http.client.BadStatusLine, ConnectionError:
        after = run.panel.read_status()
        expect(after.status == HTTPStatus.OK, "the panel stopped answering afterwards")
        return "connection closed, no bytes; panel answered afterwards"
    msg = f"got a response: {response.status} {body_text(response)}"
    raise CheckFailedError(msg)


@check("Q56", tier=WRITE)
def a_400_names_the_parameter(run: Run) -> str | None:
    """Check that a 400 body names the parameter and is not ``invalid data.``."""
    response = run.write_rejected("activeDisplayBrightness", OUT_OF_RANGE_BRIGHTNESS)
    text = body_text(response, limit=400)
    expect("activeDisplayBrightness" in text, f"body {text!r}")
    expect(text.strip() != DOCUMENTED_400_BODY, "the documented fixed body")
    return f"body {text}"


@check("Q58", tier=WRITE)
def sensor_mode_echo_lies_when_unpaired(run: Run) -> str | None:
    """``sensorMode=true`` with no sensor echoes true and stays false."""
    if run.panel.status().parameters["sensorMode"]:
        msg = "sensorMode is already true: a sensor seems to be paired"
        raise Inconclusive(msg)
    response = run.write("sensorMode", "true")
    expect(response.status == HTTPStatus.OK, f"got {response.status}")
    expect(response.json().get("sensorMode") is True, f"echo {body_text(response)}")
    run.save_fixture("write-echo-sensorMode-unpaired", response)
    for _ in range(SILENT_UNDO_SAMPLES):
        run.sleep(SILENT_UNDO_INTERVAL)
        stored = run.panel.status().parameters["sensorMode"]
        expect(stored is False, "sensorMode became true: the write applied this time")
    watched = SILENT_UNDO_SAMPLES * SILENT_UNDO_INTERVAL
    return f"echo true, status false for {watched:.0f} s"


# --------------------------------------------------------------------------- #
# Destructive-tier checks: one reset each, shared by the rows that read it
# --------------------------------------------------------------------------- #


def kwh_reset(run: Run) -> KwhResetOutcome:
    """Reset the energy counter once per run and remember what happened."""
    if "kwh" in run.shared:
        outcome: KwhResetOutcome = run.shared["kwh"]
        return outcome
    before = float(run.panel.status().doc["totalConsumption"])
    response = run.panel.reset_kwh()
    started = time.monotonic()
    zero_after: float | None = None
    raw_after = b""
    while time.monotonic() - started < RESET_ZERO_BOUND:
        status = run.panel.status()
        raw_after = status.raw
        if float(status.doc["totalConsumption"]) == 0.0:
            zero_after = time.monotonic() - started
            break
        run.sleep(RESET_POLL)
    if response.status == HTTPStatus.OK:
        run.save_fixture("reset-kwh", response)
    run.measure(
        "Q7/Q45 kWh reset",
        f"{before} before; zero after "
        + (f"{zero_after:.2f} s" if zero_after is not None else "never"),
    )
    outcome = KwhResetOutcome(before, response, zero_after, raw_after)
    run.shared["kwh"] = outcome
    return outcome


def require_banked_energy(outcome: KwhResetOutcome) -> None:
    """Refuse to decide on a reset when the counter was already at zero."""
    if outcome.before == 0.0:
        msg = "the counter was already 0.00; bank some kWh first"
        raise Inconclusive(msg)


@check("Q7", tier=DESTRUCTIVE)
def bare_kwh_reset_zeroes_the_counter(run: Run) -> str | None:
    """``DELETE /api/reset/kwh`` without its query parameter zeroes the counter."""
    outcome = kwh_reset(run)
    expect(outcome.response.status == HTTPStatus.OK, f"got {outcome.response.status}")
    require_banked_energy(outcome)
    expect(outcome.zero_after is not None, "the counter did not reach zero")
    return f"{outcome.before} → 0"


@check("Q21", tier=DESTRUCTIVE)
def reset_lands_at_exactly_zero(run: Run) -> str | None:
    """Check that the counter reads exactly ``0.00`` after a reset."""
    outcome = kwh_reset(run)
    require_banked_energy(outcome)
    expect(outcome.zero_after is not None, "the counter did not reach zero")
    expect(
        re.search(rb'"totalConsumption"\s*:\s*0\.00\b', outcome.raw_after) is not None,
        "the wire did not read 0.00",
    )
    return None


@check("Q45", tier=DESTRUCTIVE)
def counter_is_zero_within_five_seconds(run: Run) -> str | None:
    """Check that the counter reads ``0.00`` within 5 s of the acknowledgement."""
    outcome = kwh_reset(run)
    require_banked_energy(outcome)
    zero_after = require(
        outcome.zero_after, f"not zero within {RESET_ZERO_BOUND:.0f} s"
    )
    return f"zero after {zero_after:.2f} s"


@check("Q57", tier=DESTRUCTIVE)
def reset_uses_the_status_envelope(run: Run) -> str | None:
    """Check that a reset returns ``{"status":"Success"}`` with no ``reset`` key."""
    outcome = kwh_reset(run)
    expect(outcome.response.status == HTTPStatus.OK, f"got {outcome.response.status}")
    envelope = outcome.response.json()
    expect(set(envelope) == {"status"}, f"keys {sorted(envelope)}")
    expect(envelope["status"] == "Success", f"status {envelope['status']!r}")
    return f"body {body_text(outcome.response)}"


def as_float(defaults: dict[str, object], which: str, fallback: float) -> float:
    """Read one temperature-limit default as a float, however it was spelled."""
    value = defaults.get(f"{which}imumTemperatureLimit", fallback)
    return float(str(value))


def nudge_plan(status: Status, defaults: dict[str, object]) -> dict[str, str]:
    """Return the wire value each parameter is moved to before a settings reset.

    The point is to make the reset prove itself. A parameter already sitting on
    the value the reset would restore cannot tell "written back to its default"
    from "left alone". On both units probed so far, nine of thirteen were
    exactly that, the load limit included. Moving each one off its default
    first gives the reset somewhere to move it from.

    Nothing here can make the panel heat. Both setpoints go **below** room
    temperature and the mode goes to Eco, not Heating. The load limit goes one
    step under the unit's own ``maxLoad``. That is also what makes the load
    limit's landing place visible at all, because the document's fixed 15 is a
    value this hardware rejects (Q17).

    ``sensorMode`` is left out on purpose. The write does nothing without a
    paired sensor, so the panel acknowledges it and keeps the old value (Q58).
    Any parameter whose planned value is its default anyway drops out, so every
    entry returned is off its default by construction.
    """
    cold = serialise(cold_setpoint(status))
    plan = {
        "panelMode": "2",
        "heatingSetpoint": cold,
        "ecoSetpoint": cold,
        "minimumTemperatureLimit": serialise(as_float(defaults, "min", 5.0) + 1.0),
        "maximumTemperatureLimit": serialise(as_float(defaults, "max", 40.0) - 1.0),
        "sensorCalibration": serialise(1.0),
        "loadLimit": serialise(max(1, int(status.parameters["maxLoad"]) - 1)),
        "activeDisplayBrightness": "5",
        "standbyDisplayBrightness": "0",
        "disableButtons": "1",
        "temperatureDisplay": "true",
        "openWindowDetection": "true",
    }
    return {
        name: value
        for name, value in plan.items()
        if name in defaults and value != serialise(defaults[name])
    }


def nudge_off_defaults(run: Run) -> dict[str, str]:
    """Move every writable parameter off its default; a refused write is skipped.

    Returns only the parameters a fresh status read confirms off their default.
    A write the panel refuses is left out, not raised. The aim is to make
    as much of the reset visible as this panel allows. Whatever it refuses is
    reported as not demonstrated instead of counted as a match.

    Every value goes through :meth:`Run.write`, so the ledger holds the
    original and the per-check restore puts it back. The reset is about to
    overwrite all of it anyway. That is why this adds no risk in the only
    tier that calls it.
    """
    status = run.panel.status()
    # The limits last: narrowing one past a stored setpoint clamps it (Q15),
    # and the setpoints are where the reset most needs to be visible.
    plan = nudge_plan(status, openapi_defaults())
    order = sorted(plan, key=lambda name: name in RESTORE_FIRST)
    moved: dict[str, str] = {}
    for name in order:
        # Some parameters are already off their default. For example, the panel
        # ships with buttons disabled where the document defaults them on. Those
        # need no write at all; what the reset has to prove is the same either way.
        if serialise(read_parameter(status.doc, name)) != plan[name]:
            response = run.write(name, plan[name])
            if response.status != HTTPStatus.OK:
                continue
        # Confirm by polling, never by one immediate read: the panel commits a
        # write in 305-632 ms (Q31). The first two runs of this function read
        # once and lost a different parameter each time. On both runs it was
        # the one written last, whose read raced its own write most tightly.
        _, reflected = run.reflect(name, plan[name])
        if reflected is not None:
            moved[name] = plan[name]
    return moved


def settings_reset(run: Run) -> SettingsResetOutcome:
    """Reset the settings once per run, with every writable parameter registered."""
    if "settings" in run.shared:
        outcome: SettingsResetOutcome = run.shared["settings"]
        return outcome
    for name in WRITABLE_PARAMETERS:
        run.ledger.touch(name)
    nudged = nudge_off_defaults(run)
    before = run.panel.status()
    response = run.panel.reset_settings()
    if response.status == HTTPStatus.OK:
        run.save_fixture("reset-settings", response)
    started = time.monotonic()
    timeline: list[StatusSample] = []
    read_failures = 0
    while time.monotonic() - started < SETTINGS_WATCH:
        try:
            status = run.panel.status()
        except OSError, http.client.HTTPException, UsageError:
            read_failures += 1
        else:
            timeline.append((time.monotonic() - started, status.doc))
        run.sleep(SETTINGS_POLL)
    outcome = SettingsResetOutcome(before, response, timeline, read_failures, nudged)
    run.shared["settings"] = outcome
    return outcome


def last_change_at(timeline: list[StatusSample]) -> float:
    """Return when the parameters last changed during the watch."""
    last = 0.0
    for (_, earlier), (at, later) in itertools.pairwise(timeline):
        if earlier["parameters"] != later["parameters"]:
            last = at
    return last


@check("Q26", tier=DESTRUCTIVE)
def id_survives_a_settings_reset(run: Run) -> str | None:
    """Check that the device ``id`` survives a settings reset."""
    outcome = settings_reset(run)
    expect(outcome.response.status == HTTPStatus.OK, f"got {outcome.response.status}")
    expect(bool(outcome.timeline), "no status could be read after the reset")
    final = outcome.timeline[-1][1]
    expect(final["id"] == outcome.before.doc["id"], "the id changed")
    return None


@check("Q34", tier=DESTRUCTIVE)
def settings_reset_keeps_identity_and_settles(run: Run) -> str | None:
    """Identity and network untouched, no reboot, settled within about 5 s."""
    outcome = settings_reset(run)
    expect(outcome.response.status == HTTPStatus.OK, f"got {outcome.response.status}")
    expect(outcome.read_failures == 0, f"{outcome.read_failures} reads failed")
    expect(bool(outcome.timeline), "no status could be read after the reset")
    final = outcome.timeline[-1][1]
    before = outcome.before.doc
    for key in ("id", "name", "room"):
        expect(final[key] == before[key], f"{key} changed")
    for key in ("SSID", "mac", "ipAddress"):
        expect(
            final["Network"][key] == before["Network"][key], f"Network.{key} changed"
        )
    settled = last_change_at(outcome.timeline)
    run.measure(
        "Q34 settle",
        f"last parameter change at {settled:.1f} s, over "
        f"{len(outcome.nudged)} parameter(s) held off their default first",
    )
    expect(settled <= SETTINGS_SETTLE_BOUND, f"still changing at {settled:.1f} s")
    return f"settled by {settled:.1f} s"


@check("Q53", tier=DESTRUCTIVE)
def post_reset_values_match_the_documented_defaults(run: Run) -> str | None:
    """Post-reset values match the document's defaults, except the load limit.

    The load limit is compared against the unit's own ``maxLoad`` instead,
    because that is what the firmware does. At fw 1.21 on a 600 W unit every
    other documented default matched. ``loadLimit`` landed on 6 instead of
    the document's fixed 15, which that unit would have rejected anyway
    (Q17). A panel that starts to use the documented 15 fails here. That is
    the point of keeping the row.
    """
    outcome = settings_reset(run)
    expect(bool(outcome.timeline), "no status could be read after the reset")
    final = outcome.timeline[-1][1]
    expected = openapi_defaults() | {"loadLimit": read_parameter(final, "maxLoad")}
    # Only the parameters the reset was made to move can be checked. One that
    # was already on its default and could not be moved ends there either
    # way. Counting it as a match is how this check used to pass too easily.
    judged = {name: value for name, value in expected.items() if name in outcome.nudged}
    undemonstrated = sorted(set(expected) - set(judged))
    differing = [
        f"{name}: {serialise(read_parameter(final, name))} vs expected "
        f"{serialise(value)}"
        for name, value in judged.items()
        if serialise(read_parameter(final, name)) != serialise(value)
    ]
    missed = (
        f"; not demonstrated: {', '.join(undemonstrated)}" if undemonstrated else ""
    )
    run.measure(
        "Q53 defaults",
        f"{len(judged)} checked, {'; '.join(differing) or 'all match'}{missed}",
    )
    expect(bool(judged), "no parameter could be moved off its default")
    expect(not differing, "; ".join(differing))
    return f"{len(judged)} of {len(expected)} restored to their default"


# --------------------------------------------------------------------------- #
# Thermal-tier checks: one heater-on sequence, shared
# --------------------------------------------------------------------------- #


def watch_relay(
    run: Run, started: float, *, until: Callable[[], bool], deadline: float
) -> None:
    """Poll state and power once a second, recording, until a condition or deadline."""
    timeline: list[RelaySample] = run.shared["timeline"]
    while time.monotonic() - started < deadline:
        doc = run.panel.status().doc
        timeline.append(
            (time.monotonic() - started, doc["state"], int(doc["currentPower"]))
        )
        if until():
            return
        run.sleep(1.0)


def latest(timeline: list[RelaySample]) -> RelaySample:
    """Return the latest timeline sample, or a zero sample before the first."""
    return timeline[-1] if timeline else (0.0, "", 0)


def heat_sequence(run: Run) -> HeatOutcome:
    """Close the relay once per run, briefly, in Eco mode and record the edges."""
    if "heat" in run.shared:
        outcome: HeatOutcome = run.shared["heat"]
        return outcome
    status = run.panel.status()
    if status.doc["state"] != "Idle":
        msg = f"the relay is already {status.doc['state']!r}; nothing to switch on"
        raise Inconclusive(msg)
    target = thermal_target(
        status.room_temperature,
        maximum_limit=float(status.parameters["maximumTemperatureLimit"]),
    )
    assert_thermal_setpoint(room_temperature=status.room_temperature, target=target)
    run.ledger.touch("panelMode")
    run.ledger.touch("ecoSetpoint")
    timeline: list[RelaySample] = []
    run.shared["timeline"] = timeline

    def heating() -> bool:
        return latest(timeline)[1] == "Heating"

    def powered() -> bool:
        return latest(timeline)[2] > 0

    def idle() -> bool:
        return latest(timeline)[1] == "Idle"

    def unpowered() -> bool:
        return latest(timeline)[2] == 0

    started = time.monotonic()
    heating_at: float | None = None
    try:
        # The guarded setpoint lands first, so switching to Eco can never
        # regulate to a stored eco setpoint the guard never saw.
        run.write_applied("ecoSetpoint", f"{target:.1f}")
        run.write_applied("panelMode", str(MODE_ECO))
        watch_relay(run, started, until=heating, deadline=THERMAL_CLOSE_DEADLINE)
        if heating():
            heating_at = latest(timeline)[0]
            watch_relay(
                run,
                started,
                until=powered,
                deadline=heating_at + THERMAL_MAX_RELAY_SECONDS,
            )
    finally:
        run.panel.write("ecoSetpoint", run.ledger.original("ecoSetpoint"))
        run.panel.write("panelMode", run.ledger.original("panelMode"))
    power_at = next((at for at, _, power in timeline if power > 0), None)
    idle_deadline = (time.monotonic() - started) + THERMAL_DECAY_WATCH
    watch_relay(run, started, until=idle, deadline=idle_deadline)
    idle_at = latest(timeline)[0] if idle() else None
    watch_relay(run, started, until=unpowered, deadline=idle_deadline)
    power_zero_at = latest(timeline)[0] if unpowered() and idle_at else None
    run.measure(
        "Q13/Q20 relay",
        f"target {target:.1f} °C at room {status.room_temperature:.1f} °C; "
        f"heating at {fmt_at(heating_at)}, power at {fmt_at(power_at)}, "
        f"idle at {fmt_at(idle_at)}, power zero at {fmt_at(power_zero_at)}",
    )
    outcome = HeatOutcome(timeline, heating_at, power_at, idle_at, power_zero_at)
    run.shared["heat"] = outcome
    return outcome


def fmt_at(moment: float | None) -> str:
    """Render a timeline moment for the measurements block."""
    return "never" if moment is None else f"{moment:.0f} s"


@check("Q13", tier=THERMAL)
def eco_regulates_to_eco_setpoint(run: Run) -> str | None:
    """In Eco, raising ``ecoSetpoint`` above the room closes the relay."""
    outcome = heat_sequence(run)
    expect(outcome.heating_at is not None, "the relay never closed")
    return f"relay closed at {fmt_at(outcome.heating_at)}"


@check("Q20", tier=THERMAL)
def power_trails_the_relay(run: Run) -> str | None:
    """``currentPower`` lags the relay state at both edges."""
    outcome = heat_sequence(run)
    if outcome.heating_at is None:
        msg = "the relay never closed"
        raise Inconclusive(msg)
    if outcome.power_at is None:
        msg = "power never rose within the relay cap"
        raise Inconclusive(msg)
    expect(
        outcome.power_at > outcome.heating_at,
        "power rose in the same sample as the relay",
    )
    lag = outcome.power_at - outcome.heating_at
    return f"power lagged the relay by {lag:.0f} s"


# --------------------------------------------------------------------------- #
# Running and reporting
# --------------------------------------------------------------------------- #


def say(message: str) -> None:
    """Print a progress line to stderr, so the report on stdout pastes clean."""
    print(message, file=sys.stderr, flush=True)  # noqa: T201  # a CLI's progress line


def emit(message: str = "") -> None:
    """Print a report line to stdout."""
    print(message, flush=True)  # noqa: T201  # a CLI's report line


def run_one(entry: Check, run: Run) -> tuple[str, str]:
    """Run one check and map its outcome to a verdict and a detail."""
    try:
        detail = entry.function(run)
    except CheckFailedError as error:
        return FAIL, str(error)
    except (Inconclusive, ThermalRefusedError) as error:
        return INCONCLUSIVE, str(error)
    except (
        OSError,
        http.client.HTTPException,
        UsageError,
        ValueError,
        KeyError,
    ) as error:
        return INCONCLUSIVE, f"{type(error).__name__}: {error}"
    return PASS, detail or ""


def escape_cell(text: str) -> str:
    """Make a string safe inside a Markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ")


def select_checks(register: dict[str, Row], args: argparse.Namespace) -> list[Check]:
    """Select the checks a run covers, in register order."""
    if args.check:
        unknown = [row_id for row_id in args.check if row_id not in CHECKS]
        if unknown:
            msg = f"not automated checks: {', '.join(unknown)}"
            raise UsageError(msg)
        wanted = set(args.check)
    elif args.group:
        wanted = {
            row_id for row_id, entry in CHECKS.items() if entry.tier == args.group
        }
    else:
        wanted = set(CHECKS)
    ordered = [row_id for row_id in register if row_id in wanted]
    ordered += sorted(row_id for row_id in wanted if row_id not in register)
    return [CHECKS[row_id] for row_id in ordered]


def ask_yes_no(question: str) -> bool:
    """Ask a y/N question; anything but ``y``, including end of input, is no."""
    try:
        answer = input(f"{question} [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() == "y"


@dataclass
class Report:
    """What a run prints once the checks are done."""

    status: Status
    flags: str
    results: list[Result]
    measurements: dict[str, str]
    fixtures: list[Path]
    kept: list[Path]
    """Fixtures the run left alone because the tree already had them."""

    snapshot: Path | None

    def render(self) -> Iterator[str]:
        """Render the Markdown report, line by line."""
        doc = self.status.doc
        stamp = datetime.now(tz=UTC).isoformat(timespec="seconds")
        yield (
            f"## probe.py: firmware {doc.get('firmware')!r}, model "
            f"{doc.get('model')!r}, maxLoad {doc['parameters'].get('maxLoad')!r}"
        )
        yield ""
        yield f"Run at {stamp} with `{self.flags}`."
        yield ""
        yield "| id | tier | result | claim | detail |"
        yield "|----|------|--------|-------|--------|"
        for result in self.results:
            yield (
                f"| {result.row_id} | {result.tier} | {result.verdict} | "
                f"{escape_cell(result.claim)} | {escape_cell(result.detail)} |"
            )
        yield ""
        yield "### Fixtures"
        yield ""
        if self.fixtures:
            yield from (f"- `{path.relative_to(REPO_ROOT)}`" for path in self.fixtures)
        elif self.kept:
            yield "- none new (every capture already exists in the tree)"
        else:
            yield "- none saved (fixtures are written from the write tier up)"
        if self.kept:
            yield ""
            yield "Left as committed, not overwritten:"
            yield ""
            yield from (f"- `{path.relative_to(REPO_ROOT)}`" for path in self.kept)
        yield ""
        yield "### Measurements"
        yield ""
        if self.measurements:
            yield from (f"- {key}: {value}" for key, value in self.measurements.items())
        else:
            yield "- none"
        if self.snapshot is not None:
            yield ""
            yield f"Snapshot: `{self.snapshot}`. Replay it with `probe.py --restore`."


def load_device(path: Path) -> tuple[str, int]:
    """Read the panel's host and port from the gitignored device pointer."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        msg = (
            f"cannot read the device pointer at {path}: {error}. Copy "
            f".local/device.example.json to .local/device.json and fill it in."
        )
        raise UsageError(msg) from error
    host = data.get("host")
    if not isinstance(host, str) or not host:
        msg = f"{path} has no host"
        raise UsageError(msg)
    return host, int(data.get("port", 80))


def build_parser() -> argparse.ArgumentParser:
    """Build the command line."""
    parser = argparse.ArgumentParser(
        prog="probe.py",
        description="Run the conformance register's automated rows against a panel.",
    )
    parser.add_argument("--writes", action="store_true", help="enable harmless writes")
    parser.add_argument(
        "--destructive", action="store_true", help="+ kWh reset, settings reset (y/N)"
    )
    parser.add_argument(
        "--thermal",
        action="store_true",
        help="+ heater-on sequences (y/N, TTY)",
    )
    parser.add_argument("--check", nargs="+", metavar="ID", help="only these ids")
    parser.add_argument("--group", choices=TIERS, help="only this tier's checks")
    parser.add_argument(
        "--device", type=Path, default=DEVICE_PATH, help="the device pointer file"
    )
    parser.add_argument(
        "--register", type=Path, default=REGISTER_PATH, help="the register file"
    )
    parser.add_argument(
        "--restore", type=Path, metavar="FILE", help="replay a snapshot and exit"
    )
    return parser


def install_signal_handlers() -> None:
    """Turn SIGTERM into an exception so the exit hook runs; SIGINT already is one."""

    def terminated(signum: int, _frame: object) -> None:
        msg = f"terminated by signal {signum}"
        raise Terminated(msg)

    signal.signal(signal.SIGTERM, terminated)


def restore_and_report(ledger: Ledger, panel: Panel) -> bool:
    """Run the exit hook; print the banner if anything is not back. True if clean."""
    if not ledger.pending:
        return True
    say(f"restoring {len(ledger.pending)} parameter(s) and verifying…")
    try:
        failures = ledger.restore()
    except BaseException:  # noqa: BLE001  # the hook must report even a second Ctrl-C
        failures = [
            RestoreFailure(name, ledger.originals[name], "restore interrupted")
            for name in ledger.pending
        ]
    if failures:
        say(restore_banner(panel.host, panel.port, failures))
        return False
    say("restore verified from a fresh status read.")
    return True


def secrets_of(status: Status) -> tuple[str, ...]:
    """Collect the identifying values a fixture must never carry."""
    doc = status.doc
    network = doc.get("Network", {})
    return tuple(
        str(value)
        for value in (
            doc.get("id"),
            doc.get("name"),
            network.get("SSID"),
            network.get("mac"),
            network.get("ipAddress"),
        )
        if value
    )


class RevertFailedError(Exception):
    """A check's parameters could not be verified back; the run stops here."""


def run_checks(
    checks: list[Check],
    register: dict[str, Row],
    run: Run,
    enabled: frozenset[str],
    results: list[Result] | None = None,
) -> list[Result]:
    """Run every selected check its tier allows, restoring after each one.

    Restoring per check keeps one check's writes out of the next one's
    preconditions. It also keeps a settings reset's defaults (comfort 21 °C in
    Heating mode) from standing for the rest of the run. A revert the status
    does not confirm stops the run: the exit hook then prints the banner.

    Verdicts land in ``results`` as they are reached, so a caller that passes
    its own list keeps every check that ran when the run stops early. A run
    on a weak WiFi link once lost twelve passes that way.
    """
    if results is None:
        results = []
    for entry in checks:
        claim = register[entry.row_id].claim if entry.row_id in register else ""
        if entry.tier not in enabled:
            results.append(Result(entry.row_id, entry.tier, SKIPPED, claim))
            continue
        say(f"{entry.row_id} ({entry.tier})…")
        verdict, detail = run_one(entry, run)
        say(f"  {verdict}{': ' + detail if detail else ''}")
        results.append(Result(entry.row_id, entry.tier, verdict, claim, detail))
        failures = run.ledger.restore() if run.ledger.pending else []
        if failures:
            unconfirmed = "; ".join(
                f"{failure.parameter} original {failure.original}, "
                f"now {failure.observed}"
                for failure in failures
            )
            msg = f"{entry.row_id}: restore not confirmed by the status: {unconfirmed}"
            raise RevertFailedError(msg)
    return results


def confirm_tiers(
    enabled: frozenset[str], checks: list[Check], host: str
) -> frozenset[str]:
    """Ask one y/N for the destructive and thermal tiers, whichever has a check.

    The flag is the consent for what each tier does; the answer is the last
    look at which panel it lands on. A no drops both tiers, because a no to
    a zeroed counter is a no to a closed relay too. Q13 and Q20 used to ask
    once more each for a typed phrase, and a stray character in it cost a row.
    """
    selected = {entry.tier for entry in checks}
    asked = [tier for tier in (DESTRUCTIVE, THERMAL) if tier in enabled & selected]
    if not asked:
        return enabled
    parts = [f"Run the checks that change the panel at {host}?"]
    if DESTRUCTIVE in asked:
        parts.append(
            "The kWh counter is zeroed for good. Every writable parameter is "
            "first moved off its documented default, so the reset can be seen "
            "to undo it. A settings reset then puts the panel at its defaults "
            "(comfort 21.0 °C, Heating mode) for about 15 s until the restore "
            "lands. The heater runs for that long if the room is colder."
        )
    if THERMAL in asked:
        parts.append(
            f"The relay is closed once, in Eco at no more than "
            f"{THERMAL_MAX_ABOVE_ROOM:.0f} °C above the room, for up to "
            f"{THERMAL_MAX_RELAY_SECONDS} s (Q13 and Q20)."
        )
    parts.append("Every parameter is restored and verified from a fresh read.")
    if not ask_yes_no(" ".join(parts)):
        enabled = enabled - {DESTRUCTIVE, THERMAL}
    return enabled


def main_restore(args: argparse.Namespace) -> int:
    """``--restore <file>``."""
    host, port = load_device(args.device)
    panel = Panel(host, port)
    try:
        failures = replay_snapshot(args.restore, panel)
    except (OSError, ValueError, KeyError) as error:
        msg = f"cannot replay {args.restore}: {error}"
        raise UsageError(msg) from error
    if failures:
        say(restore_banner(host, port, failures))
        return EXIT_REVERT
    say("snapshot replayed and verified from a fresh status read.")
    return EXIT_OK


def main_probe(args: argparse.Namespace) -> int:
    """Run the selected checks, restore and print the report."""
    register = load_register(args.register)
    checks = select_checks(register, args)
    host, port = load_device(args.device)
    panel = Panel(host, port)
    try:
        status = panel.status()
    except (OSError, http.client.HTTPException) as error:
        msg = f"no panel at {host}:{port}: {error}"
        raise UsageError(msg) from error
    say(f"panel at {host}: firmware {status.doc.get('firmware')!r}")

    if (args.thermal or args.destructive) and not sys.stdin.isatty():
        # A settings reset lands the panel at its defaults (comfort 21 °C in
        # Heating mode) until the restore. So it can heat as surely as the
        # thermal tier can. Neither may ever run from a cron or a pipe.
        msg = "--destructive and --thermal need an interactive terminal"
        raise UsageError(msg)
    enabled = enabled_tiers(
        writes=args.writes, destructive=args.destructive, thermal=args.thermal
    )
    enabled = confirm_tiers(enabled, checks, host)
    fixtures = None
    if WRITE in enabled:
        firmware = str(status.doc.get("firmware", "unknown"))
        fixtures = FixtureStore(
            FIXTURE_ROOT / f"fw-{firmware}", secrets=secrets_of(status)
        )
    ledger = Ledger(panel)
    run = Run(panel=panel, ledger=ledger, fixtures=fixtures)
    install_signal_handlers()
    results: list[Result] = []
    interrupted = False
    try:
        run_checks(checks, register, run, enabled, results)
    except (KeyboardInterrupt, Terminated) as error:
        interrupted = True
        say(f"\ninterrupted: {error or 'SIGINT'}")
    except RevertFailedError as error:
        say(f"stopping: {error}")
    except Exception as error:  # noqa: BLE001  # a bug must not skip the report
        interrupted = True
        say(f"\naborted by an internal error: {error!r}")
    finally:
        clean = restore_and_report(ledger, panel)

    flags = " ".join(sys.argv[1:]) or "(read tier)"
    report = Report(
        status,
        flags,
        results,
        run.measurements,
        fixtures.saved if fixtures else [],
        fixtures.kept if fixtures else [],
        ledger.snapshot_path,
    )
    for line in report.render():
        emit(line)
    if not clean:
        return EXIT_REVERT
    if interrupted:
        return EXIT_USAGE
    return exit_code_for([result.verdict for result in results])


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    args = build_parser().parse_args(argv)
    try:
        if args.restore is not None:
            return main_restore(args)
        return main_probe(args)
    except UsageError as error:
        say(f"probe.py: {error}")
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
