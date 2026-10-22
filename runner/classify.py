"""Strict frame parsing, schema validation and the 11-category classifier.

Implements docs/protocol.md v1 sections 2-6. classify() takes one Observation (raw
facts from runner/client.py) and returns exactly one category, or None when the
observation is outside the contract (verdict error, attribution runner). The first
failing stage decides: resolve -> connect -> read -> frame -> schema -> identity ->
freshness -> latency. Pure functions, no I/O, so every edge case is unit-testable.
"""
from __future__ import annotations

import errno as _errno
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

CATEGORIES = (
    "PASS", "PASS_SLOW", "RESOLVE_FAIL", "NO_ROUTE", "CONN_REFUSED", "CONNECT_TIMEOUT",
    "READ_TIMEOUT", "CONN_RESET", "MALFORMED", "WRONG_IDENTITY", "STALE_DATA",
)
COMMANDS = ("IDENTIFY", "HEALTH", "READ")

# protocol.md section 7 (rationale there)
MAX_FRAME = 4096            # bytes including the trailing \n
RESOLVE_TIMEOUT_S = 1.0
CONNECT_TIMEOUT_S = 1.0
READ_TIMEOUT_S = 2.0
ATTEMPT_DEADLINE_S = 4.0
CASE_DEADLINE_S = 30.0
LATENCY_BUDGET_MS = 500.0
CLOCK_WINDOW_S = 2.0
RETRY_PAUSE_S = 0.25

INT_LIMIT = 2**53
ID_MAX = 2147483647

_TS_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?Z$")
_DEVICE_ID_RE = re.compile(r"^[a-z0-9-]{1,32}$")
_SERIAL_RE = re.compile(r"^WIT-[0-9]{4}$")
_FW_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")

NO_ROUTE_ERRNOS = {_errno.EHOSTUNREACH, _errno.ENETUNREACH}
RESET_ERRNOS = {_errno.ECONNRESET, _errno.EPIPE}


class FrameError(ValueError):
    """The frame violates protocol.md section 2/3; str(e) is the MALFORMED detail."""


@dataclass
class Observation:
    """Raw facts about one request/response exchange (filled by runner/client.py).

    stage_failed: None, or "resolve" | "connect" | "send" | "read" when an OS-level
    error ended the exchange before a frame boundary. `end` says how reading stopped.
    Times: *_wall are time.time() (realtime, for freshness); *_ms are monotonic durations.
    """
    host: str
    port: int
    cmd: str
    req_id: int
    addr: str | None = None
    local_port: int | None = None     # our ephemeral port (ties the exchange to a capture)
    stage_failed: str | None = None
    error: str | None = None          # "timeout", errno name, or exception class
    errno: int | None = None
    data: bytes = b""                 # bytes received for this exchange (frame incl. \n if complete)
    end: str | None = None            # newline | eof | reset | timeout | oversize | error
    first_on_connection: bool = True
    t_start_wall: float | None = None
    t_send_wall: float | None = None
    t_recv_wall: float | None = None
    resolve_ms: float | None = None
    connect_ms: float | None = None
    response_ms: float | None = None  # request sent -> \n received
    latency_ms: float | None = None   # connect start -> \n for the first exchange, else response_ms
    duration_ms: float | None = None  # whole exchange wall time incl. failures
    # "case" when the case's overall deadline (protocol.md section 7), not the stage's own timeout, ended this
    # exchange or prevented it from starting. Such an observation says nothing about the device: unclassifiable.
    deadline_hit: str | None = None


@dataclass(frozen=True)
class Identity:
    device_id: str
    serial: str
    fw_version: str


@dataclass
class ReadState:
    seq: int
    ts: float          # epoch seconds parsed from the device's ts


@dataclass
class Classification:
    category: str | None      # one of CATEGORIES, or None = unclassifiable
    stage: str                # stage that decided
    detail: str = ""
    payload: dict[str, Any] | None = field(default=None, repr=False)

    @property
    def is_pass(self) -> bool:
        return self.category == "PASS"


# ---------------------------------------------------------------- frame layer

def _reject_constant(name: str):
    raise FrameError(f"non_json_constant:{name}")


def _pairs_no_dupes(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise FrameError(f"duplicate_key:{k}")
        out[k] = v
    return out


def _parse_float(s: str) -> float:
    v = float(s)
    if not math.isfinite(v):
        raise FrameError("non_finite_number")
    return v


def parse_frame(data: bytes) -> dict:
    """Bytes of one complete frame (ending in \\n) -> JSON object, or FrameError."""
    if not data.endswith(b"\n"):
        raise FrameError("no_newline")
    if len(data) > MAX_FRAME:
        raise FrameError("oversize")
    body = data[:-1]
    if not body:
        raise FrameError("empty_frame")
    if b"\r" in body:
        raise FrameError("carriage_return")
    if b"\n" in body:
        raise FrameError("embedded_newline")
    if body.startswith(b"\xef\xbb\xbf"):
        raise FrameError("utf8_bom")
    try:
        text = body.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise FrameError("invalid_utf8") from None
    try:
        obj = json.loads(text, object_pairs_hook=_pairs_no_dupes,
                         parse_constant=_reject_constant, parse_float=_parse_float)
    except FrameError:
        raise
    except (ValueError, RecursionError) as e:
        raise FrameError(f"bad_json:{type(e).__name__}") from None
    if not isinstance(obj, dict):
        raise FrameError("not_object")
    return obj


# ---------------------------------------------------------------- schema layer

def _is_int(v) -> bool:
    return type(v) is int and -INT_LIMIT < v < INT_LIMIT


def _is_number(v) -> bool:
    return (type(v) is int and -INT_LIMIT < v < INT_LIMIT) or (type(v) is float and math.isfinite(v))


def _is_str(v) -> bool:
    return type(v) is str and v != ""


def parse_ts(s: str) -> float:
    """RFC 3339 UTC 'YYYY-MM-DDTHH:MM:SS[.f{1,6}]Z' -> epoch seconds, or ValueError."""
    m = _TS_RE.match(s)
    if not m:
        raise ValueError("ts_format")
    y, mo, d, h, mi, sec, frac = m.groups()
    dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(sec), tzinfo=timezone.utc)
    return dt.timestamp() + (int(frac) / 10 ** len(frac) if frac else 0.0)


# Per command: ordered (key, type check, domain check). Order fixes the detail string.
_SCHEMAS = {
    "IDENTIFY": (
        ("device_id", _is_str, lambda v: bool(_DEVICE_ID_RE.match(v))),
        ("serial", _is_str, lambda v: bool(_SERIAL_RE.match(v))),
        ("model", _is_str, lambda v: len(v) <= 64),
        ("fw_version", _is_str, lambda v: bool(_FW_RE.match(v))),
    ),
    "HEALTH": (
        ("status", _is_str, lambda v: v in ("ok", "degraded")),
        ("uptime_s", _is_number, lambda v: 0 <= v < 3.2e9),
        ("sensor_ok", lambda v: type(v) is bool, lambda v: True),
    ),
    "READ": (
        ("seq", _is_int, lambda v: 1 <= v < INT_LIMIT),
        ("ts", _is_str, lambda v: _ts_ok(v)),
        ("temp_c", _is_number, lambda v: -40.0 <= v <= 85.0),
        ("rh_pct", _is_number, lambda v: 0.0 <= v <= 100.0),
    ),
}


def _ts_ok(v: str) -> bool:
    try:
        parse_ts(v)
        return True
    except (ValueError, OverflowError):
        return False


def check_schema(obj: dict, cmd: str, req_id: int) -> str | None:
    """Return the first schema failure (protocol.md section 5 row 9 order), or None."""
    if "id" not in obj:
        return "id_missing"
    rid = obj["id"]
    if not (type(rid) is int and 0 <= rid <= ID_MAX):
        return "id_type"
    if rid != req_id:
        return "wrong_id"
    if "error" in obj:
        return "device_error"
    schema = _SCHEMAS[cmd]
    for key, _, _ in schema:
        if key not in obj:
            return f"missing:{key}"
    for key, type_ok, _ in schema:
        if not type_ok(obj[key]):
            return f"type:{key}"
    for key, _, dom_ok in schema:
        if not dom_ok(obj[key]):
            return "out_of_range:" + key if key in ("temp_c", "rh_pct", "uptime_s", "seq") else f"domain:{key}"
    allowed = {"id"} | {k for k, _, _ in schema}
    unknown = sorted(set(obj) - allowed)
    if unknown:
        return "unknown_key:" + ",".join(unknown)
    return None


# ---------------------------------------------------------------- classifier

def _errno_name(n: int | None) -> str:
    return _errno.errorcode.get(n, str(n)) if n is not None else "none"


def classify(obs: Observation, *, expect: Identity | None = None,
             prev_read: ReadState | None = None,
             budget_ms: float = LATENCY_BUDGET_MS,
             window_s: float = CLOCK_WINDOW_S) -> Classification:
    """Exactly one category for one exchange (protocol.md section 5)."""
    # 0 the case deadline, not the device, ended the exchange: no category (verdict error, attribution runner)
    if obs.deadline_hit:
        return Classification(None, obs.stage_failed or "read",
                              f"{obs.deadline_hit}_deadline_exhausted:{obs.end or obs.error or 'not_started'}:"
                              f"{len(obs.data)}B")
    # 1 resolve
    if obs.stage_failed == "resolve":
        return Classification("RESOLVE_FAIL", "resolve", obs.error or "resolve_failed")
    # 2-4 connect
    if obs.stage_failed == "connect":
        if obs.error == "timeout":
            return Classification("CONNECT_TIMEOUT", "connect", "no_handshake_within_timeout")
        if obs.errno in NO_ROUTE_ERRNOS:
            return Classification("NO_ROUTE", "connect", _errno_name(obs.errno))
        if obs.errno == _errno.ECONNREFUSED:
            return Classification("CONN_REFUSED", "connect", "ECONNREFUSED")
        return Classification(None, "connect", f"unclassifiable_connect_error:{obs.error}")
    # 5-7 read (send failures count as read stage: nothing usable came back)
    if obs.stage_failed == "send":
        if obs.errno in RESET_ERRNOS:
            return Classification("CONN_RESET", "send", _errno_name(obs.errno))
        return Classification(None, "send", f"unclassifiable_send_error:{obs.error}")
    n = len(obs.data)
    if obs.end == "oversize":
        return Classification("MALFORMED", "read", "oversize")
    if obs.end in ("eof", "reset"):
        if n > 0:
            return Classification("MALFORMED", "read", f"truncated:{obs.end}:{n}B")
        return Classification("CONN_RESET", "read", f"{obs.end}_before_response")
    if obs.end == "timeout":
        if n > 0:
            return Classification("MALFORMED", "read", f"incomplete:{n}B")
        return Classification("READ_TIMEOUT", "read", "no_bytes_by_deadline")
    if obs.end != "newline":
        return Classification(None, "read", f"unclassifiable_read_end:{obs.end}:{obs.error}")
    # 8 frame
    try:
        obj = parse_frame(obs.data)
    except FrameError as e:
        return Classification("MALFORMED", "frame", str(e))
    # 9 schema
    bad = check_schema(obj, obs.cmd, obs.req_id)
    if bad:
        return Classification("MALFORMED", "schema", bad, obj)
    # 10 identity
    if obs.cmd == "IDENTIFY" and expect is not None:
        wrong = [k for k in ("device_id", "serial", "fw_version") if obj[k] != getattr(expect, k)]
        if wrong:
            got = ";".join(f"{k}={obj[k]}!={getattr(expect, k)}" for k in wrong)
            return Classification("WRONG_IDENTITY", "identity", ",".join(wrong) + " " + got, obj)
    # 11 freshness
    if obs.cmd == "READ":
        ts = parse_ts(obj["ts"])
        if obs.t_send_wall is None or obs.t_recv_wall is None:
            return Classification(None, "freshness", "missing_runner_timestamps", obj)
        if not (obs.t_send_wall - window_s <= ts <= obs.t_recv_wall + window_s):
            skew = ts - obs.t_recv_wall if ts > obs.t_recv_wall else ts - obs.t_send_wall
            return Classification("STALE_DATA", "freshness", f"ts_outside_window:{skew:+.3f}s", obj)
        if prev_read is not None:
            if obj["seq"] <= prev_read.seq:
                return Classification("STALE_DATA", "freshness",
                                      f"seq_not_increasing:{obj['seq']}<={prev_read.seq}", obj)
            if ts < prev_read.ts:
                return Classification("STALE_DATA", "freshness",
                                      f"ts_backwards:{ts - prev_read.ts:+.6f}s", obj)
    # 12-13 latency
    if obs.latency_ms is None:
        return Classification(None, "latency", "missing_latency", obj)
    if obs.latency_ms > budget_ms:
        return Classification("PASS_SLOW", "latency", f"latency_ms={obs.latency_ms:.1f}>{budget_ms:g}", obj)
    return Classification("PASS", "latency", f"latency_ms={obs.latency_ms:.1f}", obj)


def read_state(c: Classification) -> ReadState | None:
    """Baseline for the next READ's monotonicity check (only from a schema-valid READ)."""
    p = c.payload
    if p is None or c.category not in ("PASS", "PASS_SLOW") or "seq" not in p:
        return None
    return ReadState(seq=p["seq"], ts=parse_ts(p["ts"]))


# ---------------------------------------------------------------- process restart inference (protocol.md 6, 10)
# HEALTH uptime_s is the device process's own monotonic age, rounded to 1 ms. One process answering two HEALTH
# requests must have aged at least as much as the observer's monotonic clock advanced between the two device-side
# samples. Each sample happened somewhere inside its exchange (request sent .. reply received on the observer's
# clock), so that advance is at least `elapsed_min` = start of the later exchange - end of the earlier one.
# An uptime that advanced less than that, beyond the measurement uncertainty, belongs to a NEW process. This holds
# whether the new process's uptime is lower OR higher than the old one's (an early restart: the old process was
# polled young, the new one is polled older), which a plain "uptime decreased" test misses (audit F-02).
UPTIME_RESOLUTION_S = 0.001     # two values rounded to 1 ms each by the device
RESTART_SLACK_S = 0.002         # float rounding and the scheduling between taking a timestamp and the I/O
# Relative rate of two VMs' CLOCK_MONOTONIC: each kernel bounds the NTP frequency correction at 500 ppm. chronyd can
# slew faster only while correcting a large offset, which the preflight clock gate (|offset| < 100 ms) excludes.
RESTART_RATE_TOL = 1000e-6


@dataclass(frozen=True)
class HealthSample:
    """One HEALTH answer with the observer's monotonic time bounds of its exchange (seconds)."""
    uptime_s: float
    t_sent: float
    t_recv: float


def restart_between(prev: HealthSample, cur: HealthSample) -> tuple[bool, dict]:
    """Did a different process answer `cur` than answered `prev`? -> (restarted, evidence).
    The rule compares the uptime advance with a LOWER bound of the true elapsed time, so two samples of one process
    are not flagged while the clocks' relative rate stays within RESTART_RATE_TOL; a stale-sequence fault inside one
    process (F13 repeat-seq, mutant M2) is therefore not excused as a restart. Residual blind spot: a new process
    that started within (both exchanges' durations + tolerance) of the old process's start is indistinguishable by
    timing alone (protocol v1 has no incarnation id); a real restart takes far longer (systemctl restart 85-561 ms
    on witness-field over 27 FT-F12 runs, against exchanges of ~1 ms)."""
    advance = cur.uptime_s - prev.uptime_s
    elapsed_min = cur.t_sent - prev.t_recv
    elapsed_max = cur.t_recv - prev.t_sent
    tol = UPTIME_RESOLUTION_S + RESTART_SLACK_S + RESTART_RATE_TOL * max(0.0, elapsed_max)
    shortfall = elapsed_min - advance
    if advance < 0:
        rule = "uptime_decreased"
    elif shortfall > tol:
        rule = "uptime_advanced_less_than_elapsed"
    else:
        rule = None
    return rule is not None, {
        "rule": rule, "uptime_before_s": prev.uptime_s, "uptime_after_s": cur.uptime_s,
        "uptime_advance_s": round(advance, 6), "elapsed_min_s": round(elapsed_min, 6),
        "elapsed_max_s": round(elapsed_max, 6), "shortfall_s": round(shortfall, 6), "tolerance_s": round(tol, 6)}


def combine(categories: list[str | None]) -> str | None:
    """Attempt category for a multi-exchange attempt: the first non-pass exchange decides,
    else PASS_SLOW if any exchange was slow, else PASS. None (unclassifiable) propagates."""
    for c in categories:
        if c not in ("PASS", "PASS_SLOW"):
            return c
    return "PASS_SLOW" if "PASS_SLOW" in categories else "PASS"
