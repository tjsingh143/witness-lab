"""Gateway unit tests on loopback with the real device simulator (fast interval P = 0.2 s).
They prove the poller/state machine/API logic only; the deployed gateway on witness-ctl
polling witness-field over the routed lab network is tested by tests/live/test_gateway_cases.py."""
import http.client
import json
import socket
import threading
import time

import pytest

from device import mutants
from device.device import Device, DeviceServer
from gateway import gateway as G
from runner.cases import health
from runner.classify import HealthSample, restart_between

P, DEADLINE = 0.2, 0.4


def row(dev_id, port, serial="WIT-0001", fw="1.0.0"):
    return {"device_id": dev_id, "hostname": "127.0.0.1", "address": "127.0.0.1", "port": port,
            "serial": serial, "fw_version": fw, "instance": dev_id[-1]}


class Dev:
    """A real DeviceServer on 127.0.0.1 that can be stopped and restarted on the same port."""

    def __init__(self, dev_id="dev-a", serial="WIT-0001", port=0):
        self.dev_id, self.serial = dev_id, serial
        self.port = port
        self.start()

    def start(self):
        self.device = Device(self.dev_id, self.serial, "WSIM-1", "1.0.0")
        self.srv = DeviceServer(("127.0.0.1", self.port), self.device, idle_timeout=2)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

    def stop(self):
        self.srv.stopping = True
        self.srv.shutdown()
        self.srv.server_close()
        self.srv.close_all()


@pytest.fixture
def devs():
    made = []

    def make(*a, **kw):
        d = Dev(*a, **kw)
        made.append(d)
        return d
    yield make
    for d in made:
        try:
            d.stop()
        except OSError:
            pass


@pytest.fixture
def gw_for():
    gws = []

    def make(rows, start=True):
        g = G.Gateway({"devices": rows}, inventory_path="test", inventory_sha256="0" * 64,
                      interval_s=P, deadline_s=DEADLINE)
        if start:
            g.start_pollers(delay_s=0.0)
        gws.append(g)
        return g
    yield make
    for g in gws:
        g.stop.set()
        for t in g.threads:
            t.join(2)


def wait_state(g, dev_id, want, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        with g.lock:
            if g.devices[dev_id].state == want:
                return g.devices[dev_id]
        time.sleep(0.01)
    raise AssertionError(f"{dev_id} never {want}; now {g.devices[dev_id].state}: {g.devices[dev_id].last_poll}")


def hung_listener():
    """Listening socket that never accepts: the kernel completes the handshake, nobody answers."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(8)
    return s


def test_poll_once_identify_health_read_pass(devs):
    d = devs()
    p = G.poll_once(row("dev-a", d.port), deadline_s=DEADLINE)
    assert p["category"] == "PASS" and [e["cmd"] for e in p["exchanges"]] == ["IDENTIFY", "HEALTH", "READ"]
    assert set(p["payload"]) == {"IDENTIFY", "HEALTH", "READ"} and p["local_port"] and p["addr"] == "127.0.0.1"
    assert G.state_for(p) == "healthy"


def test_healthy_then_unreachable_then_recovery_with_restart_detected(devs, gw_for):
    d = devs()
    g = gw_for([row("dev-a", d.port)])
    wait_state(g, "dev-a", "healthy")
    time.sleep(2.5 * P)                       # a few polls on the old process (uptime grows)
    t_stop = time.monotonic()
    d.stop()
    st = wait_state(g, "dev-a", "unreachable", timeout=P + DEADLINE + 0.3)
    assert st.state_since_mono - t_stop <= P + 0.1          # refused at the next slot
    assert st.last_poll["category"] == "CONN_REFUSED" and st.reachable is False and st.outage_open
    d.start()
    t_up = time.monotonic()
    st = wait_state(g, "dev-a", "healthy", timeout=2 * P + 0.3)
    assert st.state_since_mono - t_up <= 2 * P                # REQ-08 shape: within two intervals
    assert st.restarts_detected == 1 and st.last_restart["uptime_after_s"] < st.last_restart["uptime_before_s"]
    assert st.last_outage["category"] == "CONN_REFUSED" and st.last_outage["duration_ms"] > 0
    assert [t["to"] for t in st.transitions] == ["healthy", "unreachable", "healthy"]


def test_hung_device_is_bounded_and_does_not_delay_the_other(devs, gw_for):
    good = devs("dev-b", "WIT-0002")
    hung = hung_listener()
    try:
        g = gw_for([row("dev-a", hung.getsockname()[1]), row("dev-b", good.port, serial="WIT-0002")])
        st = wait_state(g, "dev-a", "unreachable", timeout=DEADLINE + 0.5)
        assert st.last_poll["category"] == "READ_TIMEOUT"
        assert st.last_poll["duration_ms"] <= DEADLINE * 1000 + 100          # poll deadline holds
        time.sleep(6 * P)
        with g.lock:
            a, b = g.devices["dev-a"], g.devices["dev-b"]
            assert b.state == "healthy" and b.consecutive_failures == 0
            # dev-b polls every slot; dev-a's 0.4 s polls skip slots instead of queueing them
            assert b.polls >= a.polls + 2 and a.skipped_slots >= 2 and b.skipped_slots == 0
    finally:
        hung.close()


def test_wrong_identity_stale_and_protocol_error_states(devs, gw_for):
    wrong = devs("dev-a", "WIT-0009")
    skew, rep, bad = devs("dev-b", "WIT-0002"), devs("dev-c", "WIT-0003"), devs("dev-d", "WIT-0004")
    skew.device.mode, rep.device.mode, bad.device.mode = "clock-skew:+30s", "repeat-seq", "malformed"
    g = gw_for([row("dev-a", wrong.port), row("dev-b", skew.port, serial="WIT-0002"),
                row("dev-c", rep.port, serial="WIT-0003"), row("dev-d", bad.port, serial="WIT-0004")])
    a = wait_state(g, "dev-a", "wrong_identity")
    assert a.identity_ok is False and a.identity_mismatch == ["serial"] and a.reachable
    b = wait_state(g, "dev-b", "stale")
    assert b.freshness["fresh"] is False and b.freshness["detail"].startswith("ts_outside_window:+")
    assert abs(float(b.freshness["detail"].split(":")[1][:-1]) - 30) < 0.1 and abs(b.freshness["skew_s"] - 30) < 0.1
    c = wait_state(g, "dev-c", "stale", timeout=3 * P)            # first READ fine, second repeats seq
    assert c.freshness["detail"].startswith("seq_not_increasing")
    d = wait_state(g, "dev-d", "protocol_error")
    assert d.last_poll["category"] == "MALFORMED"
    skew.device.mode = "normal"
    wait_state(g, "dev-b", "healthy")                             # recovers on the next good poll


def test_api_contract(devs, gw_for):
    d = devs()
    g = gw_for([row("dev-a", d.port)])
    wait_state(g, "dev-a", "healthy")
    httpd = G.serve(g, "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    try:
        def call(method, path):
            c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=2)
            c.request(method, path)
            r = c.getresponse()
            body = r.read()
            c.close()
            return r.status, r.getheader("Content-Type"), r.getheader("Allow"), body
        st, ct, _, body = call("GET", "/inventory")
        inv = json.loads(body)
        assert st == 200 and ct == "application/json" and [x["device_id"] for x in inv["devices"]] == ["dev-a"]
        assert inv["gateway"]["poll_interval_s"] == P and inv["summary"] == {"healthy": 1}
        st, _, _, body = call("GET", "/devices/dev-a")
        rec = json.loads(body)
        assert st == 200 and rec["state"] == "healthy" and rec["identity_ok"] and rec["firmware"]["ok"]
        assert rec["freshness"]["fresh"] and rec["health"]["status"] == "ok" and rec["now_mono"] >= rec["last_seen_mono"]
        assert [e["cmd"] for e in rec["last_poll"]["exchanges"]] == ["IDENTIFY", "HEALTH", "READ"]
        assert call("GET", "/devices/nope")[0] == 404 and json.loads(call("GET", "/devices/nope")[3])["error"] == "unknown_device"
        assert call("GET", "/devices/BAD!")[0] == 400
        assert call("GET", "/nothing")[0] == 404
        st, _, allow, body = call("POST", "/inventory")
        assert st == 405 and allow == "GET, HEAD" and json.loads(body)["error"] == "method_not_allowed"
        st, _, _, body = call("HEAD", "/inventory")
        assert st == 200 and body == b""
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_poll_all_once_and_deadline_guard(devs):
    d = devs()
    g = G.Gateway({"devices": [row("dev-a", d.port), row("dev-x", 1)]}, inventory_path="t", inventory_sha256="0",
                  interval_s=P, deadline_s=DEADLINE)
    out = G.poll_all_once(g)
    states = {x["device_id"]: (x["state"], x["last_category"]) for x in out["devices"]}
    assert states == {"dev-a": ("healthy", "PASS"), "dev-x": ("unreachable", "CONN_REFUSED")}
    with pytest.raises(ValueError):
        G.Gateway({"devices": []}, inventory_path="t", inventory_sha256="0", interval_s=1.0, deadline_s=2.5)


def test_main_rejects_invalid_inventory(tmp_path):
    p = tmp_path / "inv.yaml"
    p.write_text("schema_version: 1\ndevices: []\n")
    assert G.main(["--inventory", str(p), "--once"]) == 2


# ---------------------------------------------------------------- restart inference (independent audit F-02)

def hs(uptime, t):
    """A HEALTH sample taken by a 1 ms exchange at observer time t."""
    return HealthSample(uptime, t, t + 0.001)


def test_restart_between_rules():
    # same process: uptime advances with the observer's clock (incl. 1 ms rounding and a 400 ppm rate error)
    assert not restart_between(hs(10.000, 100.0), hs(12.001, 102.0))[0]
    assert not restart_between(hs(10.000, 100.0), hs(11.999, 102.0))[0]
    assert not restart_between(hs(10.000, 100.0), hs(10.000 + 3600 * (1 - 400e-6), 3700.0))[0]
    # restart, uptime lower (the only case the pre-remediation rule saw)
    r, ev = restart_between(hs(500.0, 100.0), hs(1.5, 102.0))
    assert r and ev["rule"] == "uptime_decreased"
    # EARLY restart: old process polled young (0.014 s), new one polled 1.6 s old -> higher uptime, still a restart
    r, ev = restart_between(hs(0.014, 100.0), hs(1.600, 102.0))
    assert r and ev["rule"] == "uptime_advanced_less_than_elapsed" and ev["uptime_advance_s"] > 0
    assert ev["shortfall_s"] == pytest.approx(0.413, abs=0.002)
    # the documented blind spot: a successor that started within the exchanges' durations + tolerance
    assert not restart_between(hs(0.014, 100.0), hs(2.012, 102.0))[0]


def test_early_restart_is_detected_and_recovers_within_two_intervals(gw_for):
    """The audit's scenario on loopback with the real Device/DeviceServer/Gateway: the old process is polled while
    young with its seq pushed to 1000, then replaced 50 ms later by a new process (seq restarts at 1) whose first
    poll reports a HIGHER uptime. The gateway must count the restart, never go stale, and report healthy within
    2 P of the first successful HEALTH probe."""
    old = Device("dev-a", "WIT-0001", "WSIM-1", "1.0.0")
    for n in range(1000):
        old.respond(n, "READ")
    srv = DeviceServer(("127.0.0.1", 0), old, idle_timeout=2)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.005}, daemon=True).start()
    new_srv = None
    try:
        g = gw_for([row("dev-a", port)])
        st = wait_state(g, "dev-a", "healthy")
        with g.lock:
            young = st.health["uptime_s"]
            assert st.freshness["seq"] == 1001 and young < P
        srv.stopping = True
        srv.shutdown()
        srv.server_close()
        srv.close_all()
        time.sleep(0.05)                                       # restart takes time; the new process starts now
        new = Device("dev-a", "WIT-0001", "WSIM-1", "1.0.0")
        new_srv = DeviceServer(("127.0.0.1", port), new, idle_timeout=2)
        threading.Thread(target=new_srv.serve_forever, kwargs={"poll_interval": 0.005}, daemon=True).start()
        while health("127.0.0.1", port).category != "PASS":
            time.sleep(0.005)
        t_pass = time.monotonic()
        end = t_pass + 2 * P + 0.3
        while time.monotonic() < end:
            with g.lock:
                if st.restarts_detected and st.state == "healthy":
                    break
            time.sleep(0.005)
        with g.lock:
            assert st.restarts_detected == 1 and st.state == "healthy", st.last_poll
            lr = st.last_restart
            assert lr["mono"] - t_pass <= 2 * P                         # REQ-08 shape: within two intervals
            assert lr["rule"] == "uptime_advanced_less_than_elapsed"
            assert lr["uptime_after_s"] > lr["uptime_before_s"] == young   # "uptime decreased" could not see it
            assert "stale" not in [t["to"] for t in st.transitions]
    finally:
        if new_srv is not None:
            new_srv.stopping = True
            new_srv.shutdown()
            new_srv.server_close()
            new_srv.close_all()


def test_seq_reuse_inside_one_process_stays_stale_never_a_restart(gw_for):
    """Mutant M2 (seq wraps 1..5) and F13 repeat-seq are ONE process: the new rule must not excuse them."""
    m2 = Device("dev-a", "WIT-0001", "WSIM-1", "1.0.0", mutant=mutants.Mutant("seq-reuse"))
    srv = DeviceServer(("127.0.0.1", 0), m2, idle_timeout=2)
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.005}, daemon=True).start()
    try:
        g = gw_for([row("dev-a", srv.server_address[1])])
        st = wait_state(g, "dev-a", "stale", timeout=8 * P)
        with g.lock:
            assert st.freshness["detail"].startswith("seq_not_increasing") and st.restarts_detected == 0
    finally:
        srv.stopping = True
        srv.shutdown()
        srv.server_close()
        srv.close_all()
