#!/usr/bin/env python3
"""Witness gateway: holds the expected inventory, polls every device on a fixed schedule,
records last-seen state and serves it as JSON over HTTP (GET /inventory, GET /devices/<id>).

Runs on witness-ctl as systemd unit witness-gateway.service (Type=notify, DynamicUser), from
the installed copy /usr/local/lib/witness-gateway (scripts/provision_ctl.sh). The devices are
simulated (Python processes on witness-field); the traffic is real TCP between the two VMs.

Polling (docs/protocol.md section 10):
- one poller thread per device, so a hung or slow device cannot delay another;
- fixed-rate schedule on CLOCK_MONOTONIC: poll k of every device starts at t0 + k*P
  (P = --interval, 2.0 s). A poll that overruns its slot makes the poller skip the missed
  slot(s) (counted as `skipped_slots`), never queue them: at most one poll per device is in flight;
- a poll is ONE fresh TCP connection carrying IDENTIFY, HEALTH, READ (runner/client.py) with the
  runner's resolve/connect/read deadlines and one overall poll deadline (--poll-deadline, 4.0 s),
  so P + deadline = 6 s = 3P bounds the detection of any failure, even a timeout;
- every exchange is classified by runner/classify.py (the runner's 11 categories, same rules);
  the poll's category is the first non-pass exchange.

State per device, decided by each poll (no hysteresis: one failed poll = unreachable, one good
poll = recovered): unknown, healthy, degraded (PASS_SLOW or HEALTH not ok), wrong_identity,
protocol_error (MALFORMED), stale (STALE_DATA), unreachable (RESOLVE_FAIL, NO_ROUTE,
CONN_REFUSED, CONNECT_TIMEOUT, READ_TIMEOUT, CONN_RESET), error (unclassifiable).
A device process restart is inferred from HEALTH uptime against ctl's own monotonic clock
(runner/classify.restart_between): the uptime advanced less than the time that certainly elapsed
between the two HEALTH exchanges, beyond the measurement uncertainty. That covers an uptime that
went down AND an early restart whose new uptime is higher than a young old process's (independent
audit F-02). A restart is counted, and the freshness baseline (seq/ts) is reset before the same
poll's READ is judged; within one process the baseline is never reset, so repeated or reused seq
values stay STALE_DATA.
Every *_mono value is time.monotonic() in seconds on witness-ctl. CLOCK_MONOTONIC is
system-wide, so the runner on the same VM compares these values with its own clock directly.

Usage: python3 -m gateway.gateway [--inventory PATH] [--listen 127.0.0.1:8080]
                                  [--interval 2.0] [--poll-deadline 4.0] [--once]
--once polls every device once (concurrently), prints the device records as JSON and exits.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import logging
import os
import re
import signal
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from runner.classify import (ATTEMPT_DEADLINE_S, HealthSample, Identity, ReadState, classify, combine, parse_ts,
                             read_state, restart_between)
from runner.client import Connection, Deadlines
from scripts.lib import inventory as inventory_lib

log = logging.getLogger("witness-gateway")

POLL_INTERVAL_S = 2.0            # P, docs/requirements.md
POLL_DEADLINE_S = ATTEMPT_DEADLINE_S
COMMANDS = ("IDENTIFY", "HEALTH", "READ")
PASSING = ("PASS", "PASS_SLOW")
TRANSPORT = ("RESOLVE_FAIL", "NO_ROUTE", "CONN_REFUSED", "CONNECT_TIMEOUT", "READ_TIMEOUT", "CONN_RESET")
STATE_BY_CATEGORY = {"MALFORMED": "protocol_error", "WRONG_IDENTITY": "wrong_identity", "STALE_DATA": "stale"}
STATES = ("unknown", "healthy", "degraded", "wrong_identity", "protocol_error", "stale", "unreachable", "error")
DEVICE_ID_RE = re.compile(r"^[a-z0-9-]{1,32}$")
MAX_TRANSITIONS = 50


def iso(t: float | None) -> str | None:
    if t is None:
        return None
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _r(v: float | None, nd: int = 3) -> float | None:
    return None if v is None else round(v, nd)


# ---------------------------------------------------------------- one poll

def poll_once(row: dict, prev_read: ReadState | None = None, prev_health: HealthSample | None = None,
              deadline_s: float = POLL_DEADLINE_S, dl: Deadlines = Deadlines()) -> dict:
    """Poll one device once: fresh connection, IDENTIFY -> HEALTH -> READ, bounded by deadline_s.
    Pure with respect to gateway state: the caller passes the previous READ baseline and the previous
    HEALTH sample (uptime + this clock's bounds of its exchange) used to infer a process restart."""
    started_mono, started_wall = time.monotonic(), time.time()
    expect = Identity(row["device_id"], row["serial"], row["fw_version"])
    conn = Connection(row["hostname"], row["port"],
                      Deadlines(dl.resolve_s, dl.connect_s, dl.read_s, min(dl.attempt_s, deadline_s)))
    exchanges, payload, restarted, health_sample, restart_evidence = [], {}, False, None, None
    try:
        failed = conn.open(COMMANDS[0])
        if failed is not None:
            exchanges.append((failed, classify(failed)))
        else:
            for cmd in COMMANDS:
                remaining = deadline_s - (time.monotonic() - started_mono)
                x0 = time.monotonic()
                o = conn.exchange(cmd, read_s=max(0.001, remaining))
                x1 = time.monotonic()
                c = classify(o, expect=expect if cmd == "IDENTIFY" else None,
                             prev_read=prev_read if cmd == "READ" else None)
                exchanges.append((o, c))
                if c.payload is not None and c.category in PASSING + ("WRONG_IDENTITY", "STALE_DATA"):
                    payload[cmd] = c.payload
                if c.category not in PASSING:
                    break
                if cmd == "HEALTH":
                    health_sample = HealthSample(c.payload["uptime_s"], x0, x1)
                    if prev_health is not None:
                        restarted, restart_evidence = restart_between(prev_health, health_sample)
                        if restarted:
                            prev_read = None          # new process: new seq/ts baseline for this poll's READ
    finally:
        conn.close()
    completed_mono = time.monotonic()
    cats = [c.category for _, c in exchanges]
    category = combine(cats)
    deciding = next((c for _, c in exchanges if c.category not in PASSING), exchanges[-1][1])
    read_c = next((c for o, c in exchanges if o.cmd == "READ"), None)
    read_o = next((o for o, _ in exchanges if o.cmd == "READ"), None)
    skew = None
    if "READ" in payload and read_o is not None and read_o.t_recv_wall:
        skew = parse_ts(payload["READ"]["ts"]) - read_o.t_recv_wall    # also for a STALE_DATA read
    return {
        "started_mono": started_mono, "started_at": iso(started_wall),
        "completed_mono": completed_mono, "completed_at": iso(time.time()),
        "duration_ms": (completed_mono - started_mono) * 1000,
        "category": category, "stage": deciding.stage, "detail": deciding.detail,
        "addr": exchanges[0][0].addr, "local_port": exchanges[0][0].local_port,
        "exchanges": [{"cmd": o.cmd, "category": c.category, "stage": c.stage, "detail": c.detail,
                       "connect_ms": _r(o.connect_ms), "response_ms": _r(o.response_ms),
                       "latency_ms": _r(o.latency_ms), "read_end": o.end, "bytes": len(o.data)}
                      for o, c in exchanges],
        "payload": payload, "restarted": restarted, "restart_evidence": restart_evidence,
        "uptime_before": None if prev_health is None else prev_health.uptime_s, "health_sample": health_sample,
        "read_state": read_state(read_c) if read_c is not None else None,
        "read_category": read_c.category if read_c is not None else None,
        "read_skew_s": skew,
    }


def state_for(poll: dict) -> str:
    cat = poll["category"]
    if cat is None:
        return "error"
    if cat in TRANSPORT:
        return "unreachable"
    if cat in STATE_BY_CATEGORY:
        return STATE_BY_CATEGORY[cat]
    h = poll["payload"].get("HEALTH")
    healthy = cat == "PASS" and h is not None and h["status"] == "ok" and h["sensor_ok"] is True
    return "healthy" if healthy else "degraded"


# ---------------------------------------------------------------- per-device state

class DeviceState:
    """Everything the gateway knows about one inventoried device (guarded by Gateway.lock)."""

    def __init__(self, row: dict):
        self.row = row
        now_m, now_w = time.monotonic(), time.time()
        self.state, self.state_since_mono, self.state_since = "unknown", now_m, iso(now_w)
        self.reachable: bool | None = None
        self.last_poll: dict | None = None
        self.last_seen_mono = self.last_seen = None
        self.last_ok_mono = self.last_ok = None
        self.identity = None
        self.identity_ok: bool | None = None
        self.identity_mismatch: list[str] = []
        self.health = None
        self.freshness = None
        self.prev_read: ReadState | None = None
        self.prev_health: HealthSample | None = None     # last HEALTH answer (restart inference baseline)
        self.polls = self.polls_unreachable = self.skipped_slots = 0
        self.consecutive_failures = self.consecutive_ok = 0
        self.restarts_detected = 0
        self.last_restart = None
        self.outages = 0
        self.outage_open: dict | None = None
        self.last_outage = None
        self.transitions: collections.deque = collections.deque(maxlen=MAX_TRANSITIONS)

    def apply(self, poll: dict) -> None:
        dev = self.row["device_id"]
        new = state_for(poll)
        done_m, done_w = poll["completed_mono"], poll["completed_at"]
        self.polls += 1
        self.last_poll = poll
        self.reachable = new not in ("unreachable", "error")
        if self.reachable:
            self.last_seen_mono, self.last_seen = done_m, done_w
            self.consecutive_failures, self.consecutive_ok = 0, self.consecutive_ok + 1
        else:
            self.polls_unreachable += 1
            self.consecutive_failures, self.consecutive_ok = self.consecutive_failures + 1, 0
        if new == "healthy":
            self.last_ok_mono, self.last_ok = done_m, done_w
        pl = poll["payload"]
        if "IDENTIFY" in pl:
            p = pl["IDENTIFY"]
            self.identity = {k: p[k] for k in ("device_id", "serial", "model", "fw_version")}
            self.identity_mismatch = [k for k in ("device_id", "serial", "fw_version") if p[k] != self.row[k]]
            self.identity_ok = not self.identity_mismatch
        if "HEALTH" in pl:
            self.health = {k: pl["HEALTH"][k] for k in ("status", "uptime_s", "sensor_ok")}
        if poll.get("health_sample") is not None:
            self.prev_health = poll["health_sample"]
        if poll["restarted"]:
            ev = poll["restart_evidence"]
            self.restarts_detected += 1
            self.prev_read = None
            self.last_restart = {"mono": done_m, "at": done_w, "uptime_before_s": ev["uptime_before_s"],
                                 "uptime_after_s": ev["uptime_after_s"], "poll": self.polls, "rule": ev["rule"],
                                 "evidence": ev}
            log.info("%s: device process restart detected at poll %d (%s: uptime %.3f s -> %.3f s while >= %.3f s "
                     "elapsed)", dev, self.polls, ev["rule"], ev["uptime_before_s"], ev["uptime_after_s"],
                     ev["elapsed_min_s"])
        if poll["read_category"] is not None and "READ" in pl:
            r = pl["READ"]
            st = poll["read_state"]
            self.freshness = {"seq": r["seq"], "ts": r["ts"], "fresh": poll["read_category"] in PASSING,
                              "skew_s": _r(poll["read_skew_s"]),
                              "category": poll["read_category"],
                              "detail": next((e["detail"] for e in poll["exchanges"] if e["cmd"] == "READ"), "")}
            if st is not None:
                self.prev_read = st
        if new != self.state:
            self._transition(new, poll)

    def _transition(self, new: str, poll: dict) -> None:
        dev, old = self.row["device_id"], self.state
        done_m, done_w = poll["completed_mono"], poll["completed_at"]
        self.transitions.append({"mono": done_m, "at": done_w, "from": old, "to": new, "poll": self.polls,
                                 "category": poll["category"], "stage": poll["stage"], "detail": poll["detail"]})
        self.state, self.state_since_mono, self.state_since = new, done_m, done_w
        why = f"{poll['category']} at {poll['stage']}: {poll['detail']}"
        if new == "unreachable":
            self.outages += 1
            self.outage_open = {"down_mono": done_m, "down_at": done_w, "category": poll["category"]}
            log.warning("%s: %s -> unreachable at poll %d (%s); last seen %s", dev, old, self.polls, why,
                        self.last_seen or "never")
        elif old == "unreachable" and self.outage_open is not None:
            o = self.outage_open
            self.last_outage = {**o, "up_mono": done_m, "up_at": done_w, "duration_ms": (done_m - o["down_mono"]) * 1000}
            self.outage_open = None
            log.info("%s: unreachable -> %s at poll %d after %.3f s outage (%s)", dev, new, self.polls,
                     done_m - o["down_mono"], o["category"])
        else:
            (log.info if new == "healthy" else log.warning)("%s: %s -> %s at poll %d (%s)", dev, old, new,
                                                           self.polls, why)

    def to_json(self, now_mono: float, full: bool = True) -> dict:
        r = self.row
        lp = self.last_poll
        out = {
            "device_id": r["device_id"], "state": self.state, "reachable": self.reachable,
            "state_since": self.state_since, "state_since_mono": _r(self.state_since_mono, 6),
            "last_category": lp["category"] if lp else None,
            "last_seen": self.last_seen, "last_seen_mono": _r(self.last_seen_mono, 6),
            "last_seen_age_s": _r(now_mono - self.last_seen_mono) if self.last_seen_mono else None,
            "identity_ok": self.identity_ok, "polls": self.polls,
        }
        if not full:
            return out
        out.update({
            "inventory": {k: r[k] for k in ("hostname", "address", "port", "serial", "fw_version")},
            "last_ok": self.last_ok, "last_ok_mono": _r(self.last_ok_mono, 6),
            "last_poll": None if lp is None else {k: (_r(v, 6) if k.endswith("_mono") else v) for k, v in lp.items()
                                                   if k not in ("payload", "read_state", "read_skew_s", "health_sample",
                                                                "uptime_before", "read_category")},
            "identity": self.identity, "identity_mismatch": self.identity_mismatch,
            "firmware": {"reported": self.identity["fw_version"] if self.identity else None,
                         "expected": r["fw_version"],
                         "ok": None if self.identity is None else self.identity["fw_version"] == r["fw_version"]},
            "health": self.health, "freshness": self.freshness,
            "consecutive_failures": self.consecutive_failures, "consecutive_ok": self.consecutive_ok,
            "polls_unreachable": self.polls_unreachable, "skipped_slots": self.skipped_slots,
            "restarts_detected": self.restarts_detected, "last_restart": self.last_restart,
            "outages": self.outages, "outage_open": self.outage_open, "last_outage": self.last_outage,
            "transitions": list(self.transitions),
        })
        return out


# ---------------------------------------------------------------- gateway

class Gateway:
    def __init__(self, inv: dict, *, inventory_path: str, inventory_sha256: str,
                 interval_s: float = POLL_INTERVAL_S, deadline_s: float = POLL_DEADLINE_S):
        if not 0 < deadline_s <= 2 * interval_s:
            raise ValueError("poll deadline must be in (0, 2*interval]: detection bound is interval + deadline")
        self.inv, self.interval_s, self.deadline_s = inv, interval_s, deadline_s
        self.inventory_path, self.inventory_sha256 = inventory_path, inventory_sha256
        self.lock = threading.Lock()
        self.devices = {d["device_id"]: DeviceState(d) for d in inv["devices"]}
        self.stop = threading.Event()
        self.started_mono, self.started_wall = time.monotonic(), time.time()
        self.t0_mono: float | None = None
        self.threads: list[threading.Thread] = []

    def start_pollers(self, delay_s: float = 0.1) -> None:
        self.t0_mono = time.monotonic() + delay_s
        for dev_id in self.devices:
            t = threading.Thread(target=self._poller, args=(dev_id,), name=f"poll-{dev_id}", daemon=True)
            t.start()
            self.threads.append(t)

    def _poller(self, dev_id: str) -> None:
        st, P, t0 = self.devices[dev_id], self.interval_s, self.t0_mono
        k = 0
        while not self.stop.is_set():
            delay = t0 + k * P - time.monotonic()
            if delay > 0 and self.stop.wait(delay):
                return
            with self.lock:
                prev_read, prev_health = st.prev_read, st.prev_health
            try:
                poll = poll_once(st.row, prev_read, prev_health, self.deadline_s)
            except Exception as e:  # noqa: BLE001 - a poller must never die; record it as unclassifiable
                now = time.monotonic()
                log.exception("%s: poll raised", dev_id)
                poll = {"started_mono": now, "started_at": iso(time.time()), "completed_mono": now,
                        "completed_at": iso(time.time()), "duration_ms": 0.0, "category": None, "stage": "gateway",
                        "detail": f"poll raised {type(e).__name__}: {e}", "addr": None, "local_port": None,
                        "exchanges": [], "payload": {}, "restarted": False, "restart_evidence": None,
                        "uptime_before": None if prev_health is None else prev_health.uptime_s, "health_sample": None,
                        "read_state": None, "read_category": None, "read_skew_s": None}
            poll["slot"] = k
            with self.lock:
                st.apply(poll)
                nk = int((time.monotonic() - t0) // P) + 1     # next slot strictly in the future
                st.skipped_slots += max(0, nk - (k + 1))
            k = nk

    def inventory_json(self) -> dict:
        now = time.monotonic()
        with self.lock:
            devs = [s.to_json(now, full=False) | {k: s.row[k] for k in ("hostname", "address", "port")} |
                    {"expected_serial": s.row["serial"], "expected_fw": s.row["fw_version"]}
                    for s in self.devices.values()]
        summary = collections.Counter(d["state"] for d in devs)
        return {"gateway": self.meta(now), "devices": devs, "summary": dict(sorted(summary.items()))}

    def device_json(self, dev_id: str) -> dict:
        now = time.monotonic()
        with self.lock:
            out = self.devices[dev_id].to_json(now)
        out["now_mono"] = round(now, 6)
        out["poll_interval_s"] = self.interval_s
        return out

    def meta(self, now: float) -> dict:
        return {"version": 1, "pid": os.getpid(), "started_at": iso(self.started_wall),
                "uptime_s": round(now - self.started_mono, 3), "now": iso(time.time()), "now_mono": round(now, 6),
                "poll_interval_s": self.interval_s, "poll_deadline_s": self.deadline_s,
                "schedule_t0_mono": _r(self.t0_mono, 6), "inventory_path": self.inventory_path,
                "inventory_sha256": self.inventory_sha256, "clock": "CLOCK_MONOTONIC (witness-ctl) for *_mono"}


# ---------------------------------------------------------------- HTTP API

class Api(BaseHTTPRequestHandler):
    """GET/HEAD only. 200 JSON, 400 bad_device_id, 404 unknown_device|not_found, 405 method_not_allowed."""
    server_version = "witness-gateway/1"
    sys_version = ""
    timeout = 5                     # a stalled client cannot hold a handler thread forever
    gateway: Gateway                # set on the subclass by serve()

    def _send(self, code: int, obj: dict, head: bool = False, extra: dict | None = None) -> None:
        body = (json.dumps(obj, separators=(",", ":")) + "\n").encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _route(self, head: bool) -> None:
        path = urlsplit(self.path).path
        if path == "/inventory":
            return self._send(200, self.gateway.inventory_json(), head)
        if path.startswith("/devices/"):
            dev_id = path[len("/devices/"):]
            if not DEVICE_ID_RE.match(dev_id):
                return self._send(400, {"error": "bad_device_id", "device_id": dev_id[:64]}, head)
            if dev_id not in self.gateway.devices:
                return self._send(404, {"error": "unknown_device", "device_id": dev_id}, head)
            return self._send(200, self.gateway.device_json(dev_id), head)
        return self._send(404, {"error": "not_found", "path": path[:200],
                                "endpoints": ["/inventory", "/devices/<device_id>"]}, head)

    def do_GET(self):  # noqa: N802 (http.server naming)
        self._route(False)

    def do_HEAD(self):  # noqa: N802
        self._route(True)

    def _not_allowed(self):
        self._send(405, {"error": "method_not_allowed", "method": self.command}, extra={"Allow": "GET, HEAD"})

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _not_allowed

    def log_message(self, fmt, *args):     # access log off (the runner samples every 100 ms)
        log.debug("%s " + fmt, self.address_string(), *args)


def serve(gw: Gateway, host: str, port: int) -> ThreadingHTTPServer:
    handler = type("BoundApi", (Api,), {"gateway": gw})
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    return httpd


def sd_notify(msg: str) -> None:
    path = os.environ.get("NOTIFY_SOCKET")
    if not path:
        return
    if path.startswith("@"):
        path = "\0" + path[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
        s.connect(path)
        s.sendall(msg.encode())


def poll_all_once(gw: Gateway) -> dict:
    """--once: every device polled concurrently, once; returns the device records."""
    def one(st):
        st.apply(poll_once(st.row, None, None, gw.deadline_s))
    ts = [threading.Thread(target=one, args=(s,)) for s in gw.devices.values()]
    for t in ts:
        t.start()
    for t in ts:
        t.join(gw.deadline_s + 1)
    now = time.monotonic()
    return {"gateway": gw.meta(now), "devices": [s.to_json(now) for s in gw.devices.values()]}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--inventory", default="/etc/witness/inventory.yaml")
    p.add_argument("--listen", default="127.0.0.1:8080")
    p.add_argument("--interval", type=float, default=POLL_INTERVAL_S)
    p.add_argument("--poll-deadline", type=float, default=POLL_DEADLINE_S)
    p.add_argument("--once", action="store_true")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
    raw = Path(a.inventory).read_bytes()
    try:
        inv = inventory_lib.load(a.inventory)
    except (inventory_lib.InventoryError, OSError) as e:
        log.error("inventory %s invalid: %s", a.inventory, e)
        return 2
    gw = Gateway(inv, inventory_path=a.inventory, inventory_sha256=hashlib.sha256(raw).hexdigest(),
                 interval_s=a.interval, deadline_s=a.poll_deadline)
    if a.once:
        logging.getLogger().setLevel(logging.ERROR)
        print(json.dumps(poll_all_once(gw), indent=1))
        return 0
    host, _, port = a.listen.rpartition(":")
    httpd = serve(gw, host, int(port))

    def on_term(signum, _frame):
        if gw.stop.is_set():
            return
        gw.stop.set()
        log.info("signal %s: stopping", signal.Signals(signum).name)
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)
    gw.start_pollers()
    log.info("listening http://%s:%s; %d devices (%s); interval %.1f s, poll deadline %.1f s; inventory %s sha256 %s",
             host, port, len(gw.devices), ", ".join(gw.devices), gw.interval_s, gw.deadline_s, a.inventory,
             gw.inventory_sha256[:12])
    sd_notify(f"READY=1\nSTATUS=polling {len(gw.devices)} devices every {gw.interval_s:g} s")
    try:
        httpd.serve_forever(poll_interval=0.2)
    finally:
        httpd.server_close()
        for t in gw.threads:
            t.join(gw.deadline_s + 0.5)
        log.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
