"""Client + classifier over real loopback sockets with hand-written fake devices.
Every category is produced through the actual client code path (bounded I/O),
with short deadlines so the suite stays fast."""
import errno
import json
import socket
import time

import pytest

from runner.classify import Identity, classify
from runner.client import Connection, Deadlines, resolve, single
from tests.unit.conftest import rst_close

FAST = Deadlines(resolve_s=0.3, connect_s=0.3, read_s=0.4, attempt_s=1.0)
EXPECT = Identity("dev-a", "WIT-0001", "1.0.0")


def ident(req, **over):
    rid = json.loads(req)["id"]
    return (json.dumps({"id": rid, "device_id": "dev-a", "serial": "WIT-0001", "model": "WSIM-1",
                        "fw_version": "1.0.0", **over}) + "\n").encode()


def run(port, cmd="IDENTIFY", dl=FAST, budget=150, **kw):
    o = single("127.0.0.1", port, cmd, dl, **kw)
    return o, classify(o, expect=EXPECT, budget_ms=budget)


def closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_pass(fake):
    srv = fake(lambda c, req: c.sendall(ident(req)))
    o, c = run(srv.port)
    assert c.category == "PASS", c
    assert o.latency_ms is not None and o.connect_ms is not None and o.response_ms <= o.latency_ms
    assert o.t_send_wall <= o.t_recv_wall


def test_pass_slow(fake):
    srv = fake(lambda c, req: (time.sleep(0.2), c.sendall(ident(req))))
    o, c = run(srv.port)
    assert c.category == "PASS_SLOW" and o.latency_ms > 150


def test_resolve_fail_error_and_timeout():
    def boom(h, p):
        raise socket.gaierror(-2, "Name or service not known")

    def hang(h, p):
        time.sleep(2)
        return []

    o, c = run(1, resolver=boom)
    assert c.category == "RESOLVE_FAIL" and "gaierror" in c.detail
    t0 = time.monotonic()
    o, c = run(1, resolver=hang)
    assert c.category == "RESOLVE_FAIL" and c.detail == "timeout"
    assert time.monotonic() - t0 < FAST.resolve_s + 0.2      # bounded although getaddrinfo hangs


def test_resolve_no_ipv4():
    addr, err, _ = resolve("x", 1, 0.5, resolver=lambda h, p: [(socket.AF_INET6, 1, 6, "", ("::1", 1, 0, 0))])
    assert addr is None and err == "no_ipv4_address"


class _FailingSock:
    def __init__(self, exc):
        self.exc = exc

    def settimeout(self, t):
        pass

    def connect(self, a):
        raise self.exc

    def close(self):
        pass


@pytest.mark.parametrize("eno", [errno.ENETUNREACH, errno.EHOSTUNREACH])
def test_no_route(eno):
    o, c = run(5020, sock_factory=lambda: _FailingSock(OSError(eno, "unreachable")))
    assert c.category == "NO_ROUTE"


def test_conn_refused_real_rst():
    o, c = run(closed_port())
    assert c.category == "CONN_REFUSED" and o.errno == errno.ECONNREFUSED


def test_connect_timeout():
    t0 = time.monotonic()
    o, c = run(5020, sock_factory=lambda: _FailingSock(socket.timeout("timed out")))
    assert c.category == "CONNECT_TIMEOUT"


def test_connect_timeout_real_unanswered_syn():
    # A listener whose accept backlog is full: Linux drops further SYNs (macOS may RST).
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(0)
    port = s.getsockname()[1]
    hold = []
    try:
        for _ in range(4):
            h = socket.socket()
            h.setblocking(False)
            h.connect_ex(("127.0.0.1", port))
            hold.append(h)
        time.sleep(0.05)
        o, c = run(port)
        assert c.category in ("CONNECT_TIMEOUT", "CONN_REFUSED", "READ_TIMEOUT")   # platform-dependent
    finally:
        for h in hold:
            h.close()
        s.close()


def test_read_timeout_hung_server(fake):
    srv = fake(lambda c, req: time.sleep(1.0))
    t0 = time.monotonic()
    o, c = run(srv.port)
    assert c.category == "READ_TIMEOUT"
    assert time.monotonic() - t0 < FAST.read_s + 0.3


def test_conn_reset_fin_before_bytes(fake):
    srv = fake(lambda c, req: c.shutdown(socket.SHUT_WR))
    o, c = run(srv.port)
    assert (c.category, o.end) == ("CONN_RESET", "eof")


def test_conn_reset_rst_before_bytes(fake):
    srv = fake(lambda c, req: rst_close(c))
    o, c = run(srv.port)
    assert c.category == "CONN_RESET" and o.end in ("reset", "eof")


def test_malformed_truncated_fin(fake):
    srv = fake(lambda c, req: c.sendall(ident(req)[:20]))
    o, c = run(srv.port)
    assert c.category == "MALFORMED" and c.detail.startswith("truncated:eof")


def test_malformed_truncated_rst(fake):
    def h(c, req):
        c.sendall(ident(req)[:20])
        time.sleep(0.05)
        rst_close(c)
    o, c = run(fake(h).port)
    assert c.category == "MALFORMED" and c.detail.startswith("truncated:")


def test_malformed_no_newline_held_open(fake):
    srv = fake(lambda c, req: (c.sendall(ident(req)[:-1]), time.sleep(1.0)))
    o, c = run(srv.port)
    assert c.category == "MALFORMED" and c.detail.startswith("incomplete")


def test_malformed_oversize_stops_reading(fake):
    srv = fake(lambda c, req: (c.sendall(b"{" + b" " * 10000), time.sleep(1.0)))
    t0 = time.monotonic()
    o, c = run(srv.port)
    assert (c.category, c.detail, len(o.data)) == ("MALFORMED", "oversize", 4096)
    assert time.monotonic() - t0 < FAST.read_s     # did not wait for the deadline


def test_malformed_wrong_id_echo(fake):
    srv = fake(lambda c, req: c.sendall(ident(json.dumps({"id": json.loads(req)["id"] + 1}))))
    o, c = run(srv.port)
    assert (c.category, c.detail) == ("MALFORMED", "wrong_id")


def test_malformed_temp_c_string(fake):
    def h(c, req):
        rid = json.loads(req)["id"]
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        c.sendall((json.dumps({"id": rid, "seq": 1, "ts": now, "temp_c": "22.4", "rh_pct": 40.0}) + "\n").encode())
    o, c = run(fake(h).port, cmd="READ")
    assert (c.category, c.detail) == ("MALFORMED", "type:temp_c")


def test_wrong_identity(fake):
    srv = fake(lambda c, req: c.sendall(ident(req, serial="WIT-0002", device_id="dev-b")))
    o, c = run(srv.port)
    assert c.category == "WRONG_IDENTITY" and "serial" in c.detail and "device_id" in c.detail


def test_stale_data_skewed_clock(fake):
    def h(c, req):
        rid = json.loads(req)["id"]
        from datetime import datetime, timezone
        t = datetime.fromtimestamp(time.time() + 30, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        c.sendall((json.dumps({"id": rid, "seq": 1, "ts": t, "temp_c": 22.4, "rh_pct": 40.0}) + "\n").encode())
    o, c = run(fake(h).port, cmd="READ")
    assert c.category == "STALE_DATA"


def test_connection_sequential_ids_and_buffering(fake):
    def h(c, req):
        rid = json.loads(req)["id"]
        c.sendall(ident(req))
        buf = b""
        while b"\n" not in buf:
            buf += c.recv(100)
        rid2 = json.loads(buf)["id"]
        assert rid2 == rid + 1
        msg = ident(buf)
        c.sendall(msg[:10])
        time.sleep(0.05)
        c.sendall(msg[10:])
    conn = Connection("127.0.0.1", fake(h).port, FAST)
    assert conn.open("IDENTIFY") is None
    o1 = conn.exchange("IDENTIFY")
    o2 = conn.exchange("IDENTIFY")
    conn.close()
    assert (o1.req_id, o2.req_id) == (1, 2)
    assert classify(o1, expect=EXPECT).category == "PASS" and classify(o2, expect=EXPECT).category == "PASS"
    assert o1.first_on_connection and not o2.first_on_connection and o2.connect_ms is None


def test_attempt_deadline_bounds_everything(fake):
    srv = fake(lambda c, req: time.sleep(3))
    dl = Deadlines(resolve_s=1, connect_s=1, read_s=2, attempt_s=0.5)
    t0 = time.monotonic()
    o, c = run(srv.port, dl=dl)
    assert c.category == "READ_TIMEOUT" and time.monotonic() - t0 < 0.8
