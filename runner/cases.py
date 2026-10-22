"""Case execution: attempts, the single retry, the case deadline and verdict/attribution (protocol.md 7-8).

An attempt is one fresh connection carrying one or more exchanges. Its category is the
first non-pass exchange's category (runner/classify.combine). Retry policy: at most
one retry, only for commissioning cases, on a new connection after 250 ms; the first
attempt is always kept. Fault cases are never retried.

Case deadline (protocol.md section 7; independent audit F-03): ONE absolute CLOCK_MONOTONIC deadline,
CASE_DEADLINE_S after the case's first attempt starts, bounds every resolve, connect, request and read of every
attempt, the retry pause and the retry. Each blocking step is clamped to the time left (runner/client.py); a step
the deadline cuts short, or that has no time left to start, is kept with its partial bytes and makes the result
error/runner, as documented. with_retry() owns the deadline; an attempt function called on its own opens its own.

Attribution across attempts (independent audit F-04): each attempt is assessed on its own (`Attempt.outcome`):
`ok` (category and predicates as expected), `device` (a fair observation that violated the case), `runner`
(unclassifiable, or cut by the case deadline) or `infra` (restart observed: the window was invalid). If ANY
attempt was not a fair device test the result is `error` with that attempt's attribution, whatever the other
attempt saw: a harness or infrastructure problem never becomes a device flake, and never a pass. Only fair
attempts decide pass / fail / FLAKE (a pass only on retry is a fail).

Recovery cases (REQ-08/F12) record every probe on the attempt but name the exchange that
decides (`decisive`): the first PASS HEALTH after the restart, not the first refused probe.
Gateway cases (REQ-09) have no runner attempt; the observation is the gateway's own poll,
judged by decide_observed() with the same rules.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Callable, Iterator

from runner.classify import (CASE_DEADLINE_S, RETRY_PAUSE_S, Classification, HealthSample, Identity, Observation,
                             ReadState, classify, combine, read_state, restart_between)
from runner.client import Connection, Deadlines, single
from runner.db import wall_to_iso

OUTCOMES = ("ok", "device", "runner", "infra")
_CASE_DEADLINE: ContextVar[float | None] = ContextVar("witness_case_deadline", default=None)


@contextmanager
def case_deadline(seconds: float = CASE_DEADLINE_S) -> Iterator[float]:
    """Yield the case's absolute time.monotonic() deadline. Inside an enclosing case the enclosing (earlier)
    deadline is reused, so neither an attempt nor the retry can extend the case."""
    cur = _CASE_DEADLINE.get()
    if cur is not None:
        yield cur
        return
    token = _CASE_DEADLINE.set(time.monotonic() + seconds)
    try:
        yield _CASE_DEADLINE.get()
    finally:
        _CASE_DEADLINE.reset(token)


@dataclass
class Attempt:
    attempt_no: int
    exchanges: list[tuple[Observation, Classification]] = field(default_factory=list)
    predicates: dict[str, bool] = field(default_factory=dict)
    restart_observed: bool = False
    note: str = ""
    started_wall: float = 0.0
    duration_ms: float = 0.0
    decisive: int | None = None   # index into exchanges that decides the category (recovery cases)
    deadline_exhausted: bool = False   # the case deadline left no time for this attempt's next exchange

    @property
    def cut_by_deadline(self) -> bool:
        return self.deadline_exhausted or any(o.deadline_hit for o, _ in self.exchanges)

    @property
    def category(self) -> str | None:
        if self.cut_by_deadline:
            return None
        if self.decisive is not None:
            return self.exchanges[self.decisive][1].category
        return combine([c.category for _, c in self.exchanges]) if self.exchanges else None

    @property
    def deciding(self) -> Classification | None:
        if self.cut_by_deadline:
            return next((c for o, c in self.exchanges if o.deadline_hit), None) or \
                Classification(None, "deadline", f"case_deadline_exhausted:{self.note or 'before_next_exchange'}")
        if self.decisive is not None:
            return self.exchanges[self.decisive][1]
        for _, c in self.exchanges:
            if c.category not in ("PASS", "PASS_SLOW"):
                return c
        for _, c in self.exchanges:
            if c.category == "PASS_SLOW":
                return c
        return self.exchanges[-1][1] if self.exchanges else None

    @property
    def started_at(self) -> str | None:
        return wall_to_iso(self.started_wall)

    def outcome(self, expected: str) -> str:
        """This attempt on its own: ok | device | runner | infra (see module docstring)."""
        if self.cut_by_deadline or self.category is None:
            return "runner"
        if self.restart_observed:
            return "infra"
        if self.category == expected and all(self.predicates.values()):
            return "ok"
        return "device"

    def ok(self, expected: str) -> bool:
        return self.outcome(expected) == "ok"

    @property
    def first_latency_ms(self) -> float | None:
        if self.decisive is not None:
            return self.exchanges[self.decisive][0].latency_ms
        return self.exchanges[0][0].latency_ms if self.exchanges else None


def _timed(no: int, body: Callable[[Attempt, float], None], case_deadline_s: float = CASE_DEADLINE_S) -> Attempt:
    a = Attempt(attempt_no=no, started_wall=time.time())
    t0 = time.monotonic()
    with case_deadline(case_deadline_s) as deadline:
        body(a, deadline)
    a.duration_ms = (time.monotonic() - t0) * 1000
    return a


def identify(host: str, port: int, expect: Identity, dl: Deadlines = Deadlines(), no: int = 1, **kw) -> Attempt:
    def body(a: Attempt, deadline: float):
        o = single(host, port, "IDENTIFY", dl, case_deadline=deadline, **kw)
        a.exchanges.append((o, classify(o, expect=expect)))
    return _timed(no, body)


def health(host: str, port: int, dl: Deadlines = Deadlines(), no: int = 1, **kw) -> Attempt:
    def body(a: Attempt, deadline: float):
        o = single(host, port, "HEALTH", dl, case_deadline=deadline, **kw)
        c = classify(o)
        a.exchanges.append((o, c))
        if c.payload is not None and c.category in ("PASS", "PASS_SLOW"):
            a.predicates["status_ok"] = c.payload["status"] == "ok"
            a.predicates["sensor_ok"] = c.payload["sensor_ok"] is True
        else:
            a.predicates["health_payload"] = False
    return _timed(no, body)


def read_series(host: str, port: int, n: int = 10, *, bracket_health: bool, dl: Deadlines = Deadlines(),
                no: int = 1, case_deadline_s: float = CASE_DEADLINE_S, **kw) -> Attempt:
    """n READs on one connection (optionally HEALTH before and after). Stops at the first
    exchange that is not PASS/PASS_SLOW (the connection state is then unknown), or that the
    case deadline cut short. The bracketing HEALTHs detect a process restart with
    runner/classify.restart_between (not merely "uptime decreased")."""
    def body(a: Attempt, deadline: float):
        conn = Connection(host, port, dl, case_deadline=deadline, **kw)
        cmds = (["HEALTH"] if bracket_health else []) + ["READ"] * n + (["HEALTH"] if bracket_health else [])
        prev: ReadState | None = None
        healths: list[HealthSample] = []
        try:
            failed = conn.open(cmds[0])
            if failed is not None:
                a.exchanges.append((failed, classify(failed)))
                return
            for i, cmd in enumerate(cmds, 1):
                x0 = time.monotonic()
                o = conn.exchange(cmd)
                x1 = time.monotonic()
                c = classify(o, prev_read=prev)
                a.exchanges.append((o, c))
                if o.deadline_hit:
                    a.note = f"case deadline exhausted at exchange {i}/{len(cmds)} ({cmd})"
                    return
                if c.category not in ("PASS", "PASS_SLOW"):
                    return
                if cmd == "READ":
                    prev = read_state(c)
                else:
                    healths.append(HealthSample(c.payload["uptime_s"], x0, x1))
        finally:
            conn.close()
        reads = sum(1 for o, _ in a.exchanges if o.cmd == "READ")
        a.predicates["reads_complete"] = reads == n
        if len(healths) == 2:
            restarted, ev = restart_between(healths[0], healths[1])
            if restarted:
                a.restart_observed = True
                a.note = (f"restart observed ({ev['rule']}): uptime_s {ev['uptime_before_s']} -> "
                          f"{ev['uptime_after_s']} while >= {ev['elapsed_min_s']} s elapsed")
    return _timed(no, body, case_deadline_s)


def with_retry(make: Callable[[int], Attempt], expected: str = "PASS", allow_retry: bool = True) -> list[Attempt]:
    """Attempt 1, and at most one retry when it was not ok, all inside ONE case deadline (the pause too)."""
    with case_deadline() as deadline:
        first = make(1)
        if first.ok(expected) or not allow_retry or first.cut_by_deadline:
            return [first]
        time.sleep(max(0.0, min(RETRY_PAUSE_S, deadline - time.monotonic())))
        return [first, make(2)]


@dataclass
class Decision:
    verdict: str
    attribution: str
    detail: str


def _not_fair(a: Attempt, outcome: str) -> str:
    if a.cut_by_deadline:
        return f"case deadline {CASE_DEADLINE_S:g}s exhausted ({a.note or a.deciding.detail})"
    if outcome == "runner":
        return "unclassifiable observation"
    return f"{a.note}; window invalid"


def decide(attempts: list[Attempt], expected: str, *, preflight_green: bool,
           extra_predicates: dict[str, bool] | None = None) -> Decision:
    """Verdict and attribution, independent of (but informed by) the observed category, over ALL attempts."""
    final = attempts[-1]
    preds = {**final.predicates, **(extra_predicates or {})}
    failed_preds = sorted(k for k, v in preds.items() if not v)
    d = final.deciding
    what = f"observed={final.category} expected={expected}" + (f" [{d.stage}: {d.detail}]" if d else "")
    if not preflight_green:
        return Decision("error", "infra", "preflight/precheck red: device not fairly tested; " + what)
    outcomes = [a.outcome(expected) for a in attempts]
    for a, o in zip(attempts, outcomes):
        if o in ("runner", "infra"):
            if len(attempts) == 1:
                return Decision("error", o, f"{_not_fair(a, o)}; " + what)
            history = ", ".join(f"attempt {x.attempt_no} {xo} ({x.category}"
                                f"{': ' + x.deciding.detail if x.deciding else ''})" for x, xo in zip(attempts, outcomes))
            return Decision("error", o, f"attempt {a.attempt_no} was not a fair device test ({_not_fair(a, o)}); "
                            f"never a device flake or pass; {history}; " + what)
    if final.category == expected and not failed_preds:
        if len(attempts) == 2:
            a1 = attempts[0]
            bad1 = sorted(k for k, v in a1.predicates.items() if not v)
            why1 = (a1.deciding.detail if a1.deciding else "") + (f"; failed predicates: {','.join(bad1)}" if bad1 else "")
            return Decision("fail", "device", f"FLAKE: attempt 1 {a1.category} ({why1}), passed only on retry; " + what)
        return Decision("pass", "none", what)
    why = what + (f"; failed predicates: {','.join(failed_preds)}" if failed_preds else "")
    return Decision("fail", "device", why)


def decide_observed(observed: str | None, expected: str, *, preflight_green: bool,
                    predicates: dict[str, bool], what: str = "") -> Decision:
    """decide() for an observation the runner did not make itself (the gateway's poll, REQ-09).
    For gateway requirements the gateway is part of the system under test, so a violated
    bound is attributed `device` (system under test), never `runner`."""
    failed = sorted(k for k, v in predicates.items() if not v)
    what = f"observed={observed} expected={expected}" + (f" [{what}]" if what else "")
    if not preflight_green:
        return Decision("error", "infra", "preflight/precheck red: not fairly tested; " + what)
    if observed is None:
        return Decision("error", "runner", "no classified observation; " + what)
    if observed == expected and not failed:
        return Decision("pass", "none", what)
    return Decision("fail", "device", what + (f"; failed predicates: {','.join(failed)}" if failed else ""))
