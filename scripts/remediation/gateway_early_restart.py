#!/usr/bin/env python3
"""F-02 (independent audit) at production timing (P = 2.0 s, poll deadline 4.0 s) on LOOPBACK with the real
Device, DeviceServer and Gateway classes (not VM traffic; the VM check is FT-F12's early-restart step).

Scenario, as in the audit's gateway-restart-anchored.py: the old process's seq is pushed to 1000 (accelerated test
data), the gateway polls it while it is YOUNG, the process is replaced 200 ms later (a realistic restart time on
witness-field is 85-561 ms over 27 FT-F12 runs) by a stock process on the same port; an independent HEALTH probe marks the first PASS
HEALTH. REQ-08: the gateway must report the device healthy, with the restart counted, within 2 P of that probe.
The pre-remediation gateway stayed `stale` 4.3 s later (seq 2 <= 1001, restarts_detected 0).
Prints one JSON line per trial; exit 0 iff every trial recovered within 2 P with the restart detected and no stale.
Usage: .venv/bin/python scripts/remediation/gateway_early_restart.py [TRIALS]
"""
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from device.device import Device, DeviceServer  # noqa: E402
from gateway.gateway import Gateway  # noqa: E402
from runner.cases import health  # noqa: E402


def serve(device, port=0):
    s = DeviceServer(("127.0.0.1", port), device, idle_timeout=3)
    threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    return s


def close(s):
    s.stopping = True
    s.shutdown()
    s.server_close()
    s.close_all()


def trial(n: int) -> dict:
    old = Device("dev-a", "WIT-0001", "WSIM-1", "1.0.0")
    for i in range(1000):
        old.respond(i, "READ")
    s = serve(old)
    port = s.server_address[1]
    row = {"device_id": "dev-a", "hostname": "127.0.0.1", "address": "127.0.0.1", "port": port,
           "serial": "WIT-0001", "fw_version": "1.0.0", "instance": "a"}
    g = Gateway({"devices": [row]}, inventory_path="loopback", inventory_sha256="loopback")
    P = g.interval_s
    g.start_pollers(delay_s=0)
    try:
        end = time.monotonic() + 3
        while g.device_json("dev-a")["state"] != "healthy" and time.monotonic() < end:
            time.sleep(0.005)
        before = g.device_json("dev-a")
        close(s)
        time.sleep(0.2)
        s = serve(Device("dev-a", "WIT-0001", "WSIM-1", "1.0.0"), port)
        while health("127.0.0.1", port).category != "PASS":
            time.sleep(0.005)
        t_pass = time.monotonic()
        seen = None
        while time.monotonic() < t_pass + 2 * P + 1:
            r = g.device_json("dev-a")
            if r["restarts_detected"] and r["state"] == "healthy":
                seen = time.monotonic()
                break
            time.sleep(0.01)
        after = g.device_json("dev-a")
        lr = after["last_restart"]
        out = {"trial": n, "P_s": P, "old_uptime_s": before["health"]["uptime_s"], "old_seq": before["freshness"]["seq"],
               "state": after["state"], "restarts_detected": after["restarts_detected"],
               "rule": lr and lr["rule"], "uptime_before_s": lr and lr["uptime_before_s"],
               "uptime_after_s": lr and lr["uptime_after_s"],
               "gateway_recovery_ms": lr and round((lr["mono"] - t_pass) * 1000, 3),
               "api_observed_ms": seen and round((seen - t_pass) * 1000, 3),
               "stale_transitions": [t for t in after["transitions"] if t["to"] == "stale"]}
        out["ok"] = (seen is not None and after["restarts_detected"] == 1 and not out["stale_transitions"]
                     and out["gateway_recovery_ms"] <= 2 * P * 1000 and out["api_observed_ms"] <= 2 * P * 1000)
        out["old_rule_would_detect"] = lr is not None and lr["uptime_after_s"] < lr["uptime_before_s"]
        return out
    finally:
        g.stop.set()
        for t in g.threads:
            t.join(5)
        close(s)


def main(trials: int) -> int:
    res = [trial(i + 1) for i in range(trials)]
    for r in res:
        print(json.dumps(r))
    ok = all(r["ok"] for r in res)
    print("RESULT", f"PASS: {trials}/{trials} early restarts detected, healthy within 2 P of the first PASS HEALTH, "
          f"never stale; uptime rose in {sum(not r['old_rule_would_detect'] for r in res)}" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 3))
