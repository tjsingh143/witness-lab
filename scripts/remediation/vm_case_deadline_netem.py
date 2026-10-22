#!/usr/bin/env python3
"""F-03 (independent audit) on REAL lab traffic: the audit's 1.3 s-per-reply shape produced by the network instead of
a modified device. Run on witness-ctl as root (scripts/remediation/ctl.sh sudo python3 ...).

1. Refuses unless this is witness-ctl and both quick checks are GREEN.
2. witness-faultctl `apply netem 1300 data` on witness-field: lab0 egress, flower-scoped to device-source TCP 5020,
   non-SYN segments only (handshake unaffected, every reply ~1.3 s late: inside the 2.0 s read timeout, over the
   500 ms budget). The agent arms its 90 s dead-man timer. One fault at a time.
3. with_retry(read_series(dev-a.lab, 10 READs bracketed by HEALTH)) with the production 30 s case deadline:
   attempt 1 is PASS_SLOW (~16 s), the retry runs into the shared deadline.
4. finally: `revert netem` (verified) and the capture stopped; quick checks must be GREEN again.
Prints one JSON object; exit 0 iff the case ended within 30 s + 0.1 s as error/runner with attempt 1 kept, the
revert was verified and the lab is GREEN afterwards. Evidence: OUT_PREFIX.pcap/.txt (ctl lab0).
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/witness-lab")
from runner import lab as L  # noqa: E402
from runner.cases import decide, read_series, with_retry  # noqa: E402
from runner.classify import CASE_DEADLINE_S  # noqa: E402
from scripts.lib import inventory  # noqa: E402


def green(inv, field) -> tuple[bool, list]:
    c = L.quick_check_local(inv)
    f = field("check")
    bad = [x for x in c["checks"] + f["checks"] if x["status"] == "FAIL"]
    return c["green"] and f["green"], bad


def main(prefix: str) -> int:
    inv = inventory.load("/opt/witness-lab/inventory.yaml")
    L.assert_ctl_vm(inv)
    field = L.FieldCtl(next(v for v in inv["lab"]["vms"] if v["role"] == "field")["l2_address"])
    dev = next(d for d in inv["devices"] if d["device_id"] == "dev-a")
    ok0, bad0 = green(inv, field)
    if not ok0:
        print(json.dumps({"refused": "quick checks not GREEN before the experiment", "failed": bad0}))
        return 2
    cap = L.Capture(Path(prefix + ".pcap"), bpf=L.capture_filter([dev["port"]]), max_s=60).start()
    out: dict = {"started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "case_deadline_s": CASE_DEADLINE_S}
    applied = None
    try:
        applied = field("apply", "netem", "1300", "data")
        out["apply"] = {k: applied.get(k) for k in ("applied_at", "verified")}
        if not applied.get("verified"):
            raise RuntimeError(f"netem not verified: {applied}")
        t0 = time.monotonic()
        attempts = with_retry(lambda no: read_series(dev["hostname"], dev["port"], 10, bracket_health=True, no=no))
        out["elapsed_s"] = round(time.monotonic() - t0, 6)
        d = decide(attempts, "PASS", preflight_green=True)
        out["attempts"] = [{"no": a.attempt_no, "duration_ms": round(a.duration_ms, 1), "category": a.category,
                            "outcome": a.outcome("PASS"), "exchanges": len(a.exchanges), "cut_by_deadline": a.cut_by_deadline,
                            "categories": [c.category for _, c in a.exchanges],
                            "response_ms": [round(o.response_ms, 1) if o.response_ms else None for o, _ in a.exchanges],
                            "last_detail": a.exchanges[-1][1].detail if a.exchanges else None,
                            "local_port": a.exchanges[0][0].local_port if a.exchanges else None} for a in attempts]
        out["decision"] = {"verdict": d.verdict, "attribution": d.attribution, "detail": d.detail}
    finally:
        if applied is not None:
            rr = field("revert", "netem", timeout=60)
            out["revert"] = {k: rr.get(k) for k in ("removed_at", "verified", "detail")}
        out["capture"] = str(cap.stop())
        ok1, bad1 = green(inv, field)
        out["after_green"], out["after_failed"] = ok1, bad1
    ok = (out.get("elapsed_s", 99) <= CASE_DEADLINE_S + 0.1 and out["decision"]["verdict"] == "error"
          and out["decision"]["attribution"] == "runner" and len(out["attempts"]) == 2
          and out["attempts"][0]["category"] == "PASS_SLOW" and out["attempts"][1]["cut_by_deadline"]
          and out["revert"]["verified"] and ok1)
    out["result"] = "PASS: 30 s bound enforced on lab traffic, error/runner, fault reverted" if ok else "FAIL"
    print(json.dumps(out, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "/var/lib/witness/remediation/f03-netem"))
