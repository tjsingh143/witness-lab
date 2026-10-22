#!/usr/bin/env python3
"""F-03 (independent audit) at full scale, on Mac or guest LOOPBACK (not VM traffic, no lab state touched).

The audit's counterexample: a stock Device that sleeps 1.3 s before every reply (inside the 2.0 s read timeout,
over the 500 ms budget), served on an ephemeral 127.0.0.1 port; with_retry(read_series(10 READs, bracketed by
HEALTH)) with the production 30 s case deadline. Pre-remediation: 31.6 s and fail/device. The documented bound is
30 s with expiry -> error/runner. Prints one JSON line; exit 0 iff the case ended within 30 s + 0.1 s and was
decided error/runner with attempt 1 kept and attempt 2 cut by the case deadline.
Usage: .venv/bin/python scripts/remediation/case_deadline_30s.py
"""
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from device.device import Device, DeviceServer  # noqa: E402
from runner.cases import decide, read_series, with_retry  # noqa: E402
from runner.classify import CASE_DEADLINE_S  # noqa: E402


class Slow(Device):
    def handle_line(self, line, served=0):
        time.sleep(1.3)
        return super().handle_line(line, served)


def main() -> int:
    s = DeviceServer(("127.0.0.1", 0), Slow("dev-a", "WIT-0001", "WSIM-1", "1.0.0"), idle_timeout=3)
    threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    t = time.monotonic()
    try:
        attempts = with_retry(lambda no: read_series("127.0.0.1", s.server_address[1], 10, bracket_health=True, no=no))
        elapsed = time.monotonic() - t
    finally:
        s.stopping = True
        s.shutdown()
        s.server_close()
        s.close_all()
    d = decide(attempts, "PASS", preflight_green=True)
    out = {"case_deadline_s": CASE_DEADLINE_S, "elapsed_s": round(elapsed, 6),
           "attempts": [{"no": a.attempt_no, "duration_ms": round(a.duration_ms, 1), "category": a.category,
                         "outcome": a.outcome("PASS"), "exchanges": len(a.exchanges), "cut_by_deadline": a.cut_by_deadline,
                         "last": a.exchanges[-1][1].detail if a.exchanges else None} for a in attempts],
           "decision": {"verdict": d.verdict, "attribution": d.attribution, "detail": d.detail}}
    print(json.dumps(out, indent=1))
    ok = (elapsed <= CASE_DEADLINE_S + 0.1 and (d.verdict, d.attribution) == ("error", "runner")
          and len(attempts) == 2 and attempts[0].category == "PASS_SLOW" and attempts[1].cut_by_deadline)
    print("RESULT", "PASS: 30 s case bound enforced, expiry error/runner" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
