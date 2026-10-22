"""Deliberately broken device builds ("mutants", PROJECT_BRIEF.md section 7.4).

A mutant is a build defect, not a runtime fault mode: it is selected when the process
starts (`device.py --mutant SPEC`, or WITNESS_MUTANT in the environment) and stays for
the process lifetime. On the lab it is deployed only by `witness-faultctl mutant deploy`,
which writes a runtime systemd drop-in under /run (gone after a reboot) and restarts the
device; `mutant restore` removes it, and reset_lab.sh removes it too. The device reports
its build in state.json ("stock" or "mutant:SPEC") and logs a WARNING at start, so the
runner can refuse to call a run against a mutant a clean baseline.

The six mutants, in the brief's order:
  M1 other-serial:SERIAL  IDENTIFY reports another device's serial (identity otherwise intact)
  M2 seq-reuse            READ seq wraps after 5 reads (1..5, 1..5, ...): seq values are reused
  M3 no-newline           every response frame lacks the trailing "\\n"
  M4 off-by-one-id        every response echoes id-1 (a well-formed, uncorrelated reply)
  M5 temp-string          READ temp_c is a JSON string ("21.15") instead of a number
  M6 slow-7th             every 7th request handled by the process sleeps 2.5 s before replying
Each touches exactly one contract rule; everything else is the stock behaviour.
"""
from __future__ import annotations

import re
import threading

SEQ_REUSE_PERIOD = 5
SLOW_EVERY = 7
SLOW_S = 2.5

MUTANT_RE = re.compile(r"^(?:other-serial:([A-Z0-9][A-Z0-9-]{0,31})|seq-reuse|no-newline|off-by-one-id|"
                       r"temp-string|slow-7th)$")


def valid_mutant(spec: str) -> bool:
    return bool(MUTANT_RE.match(spec or ""))


class Mutant:
    """Hooks called by device.Device; each is the identity for every other mutant."""

    def __init__(self, spec: str):
        m = MUTANT_RE.match(spec or "")
        if not m:
            raise ValueError(f"unknown mutant {spec!r}")
        self.spec = spec
        self.name = spec.split(":", 1)[0]
        self.other_serial = m.group(1)
        self._lock = threading.Lock()
        self._requests = 0

    @property
    def build(self) -> str:
        return f"mutant:{self.spec}"

    def identity(self, ident: dict) -> dict:
        if self.name == "other-serial":
            return {**ident, "serial": self.other_serial}
        return ident

    def seq(self, n: int) -> int:
        """n = stock seq (READs served so far by this process, 1-based)."""
        if self.name == "seq-reuse":
            return (n - 1) % SEQ_REUSE_PERIOD + 1
        return n

    def response(self, resp: dict, cmd: str) -> dict:
        if self.name == "off-by-one-id":
            resp = {**resp, "id": resp["id"] - 1 if resp["id"] > 0 else 1}
        if self.name == "temp-string" and cmd == "READ":
            resp = {**resp, "temp_c": f"{resp['temp_c']}"}
        return resp

    def frame(self, data: bytes) -> bytes:
        if self.name == "no-newline" and data.endswith(b"\n"):
            return data[:-1]
        return data

    def delay_s(self) -> float:
        """Called once per request line; process-wide count across all connections."""
        if self.name != "slow-7th":
            return 0.0
        with self._lock:
            self._requests += 1
            n = self._requests
        return SLOW_S if n % SLOW_EVERY == 0 else 0.0
