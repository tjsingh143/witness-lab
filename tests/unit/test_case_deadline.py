"""Independent audit F-03: ONE absolute case deadline bounds every attempt, pause, connect, request and read of a
case, including the retry; each blocking step is clamped to the time left; expiry keeps the partial observations
and is error/runner (protocol.md section 7). The audit's counterexample used the real 30 s deadline and 1.3 s
replies (31.6 s, fail/device); here the same shape is scaled (short deadline, short delays) on loopback so the unit
suite stays fast. scripts/remediation/case_deadline_30s.py reruns it at full scale. Not VM evidence."""
import socket
import threading
import time

import pytest

from device.device import Device, DeviceServer
from runner import cases as K
from runner.classify import Identity

SLACK_S = 0.08          # scheduling slack allowed beyond the deadline on a loaded host


class SlowDevice(Device):
    def __init__(self, delay_s: float):
        super().__init__("dev-a", "WIT-0001", "WSIM-1", "1.0.0")
        self.delay_s = delay_s

    def handle_line(self, line, served=0):
        time.sleep(self.delay_s)
        return super().handle_line(line, served)


@pytest.fixture
def slow():
    servers = []

    def make(delay_s):
        s = DeviceServer(("127.0.0.1", 0), SlowDevice(delay_s), idle_timeout=5)
        threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        servers.append(s)
        return s.server_address[1]
    yield make
    for s in servers:
        s.stopping = True
        s.shutdown()
        s.server_close()
        s.close_all()


def test_auditor_shape_retry_cannot_extend_the_case(slow):
    """The audit's shape, scaled: every reply is slower than the 500 ms budget but inside the 2 s read timeout, so
    attempt 1 completes PASS_SLOW (not ok -> retry) and the retry runs into the shared case deadline."""
    port = slow(0.52)
    t0 = time.monotonic()
    with K.case_deadline(4.0):
        attempts = K.with_retry(lambda no: K.read_series("127.0.0.1", port, 3, bracket_health=True, no=no))
    elapsed = time.monotonic() - t0
    assert elapsed <= 4.0 + SLACK_S, elapsed
    a1, a2 = attempts
    assert a1.category == "PASS_SLOW" and len(a1.exchanges) == 5 and not a1.cut_by_deadline
    assert a2.cut_by_deadline and a2.category is None and a2.outcome("PASS") == "runner"
    assert a2.exchanges[-1][0].deadline_hit == "case" and a2.exchanges[-1][1].category is None
    assert all(c.category == "PASS_SLOW" for _, c in a2.exchanges[:-1])        # partial observations kept
    d = K.decide(attempts, "PASS", preflight_green=True)
    assert (d.verdict, d.attribution) == ("error", "runner") and "case deadline" in d.detail


def test_deadline_clamps_a_read_below_the_read_timeout():
    """A hung listener: the 2.0 s read timeout would apply, but only 0.4 s of case time is left."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    try:
        t0 = time.monotonic()
        with K.case_deadline(0.4):
            a = K.identify("127.0.0.1", srv.getsockname()[1], Identity("dev-a", "WIT-0001", "1.0.0"))
        assert time.monotonic() - t0 <= 0.4 + SLACK_S
        o, c = a.exchanges[0]
        assert o.deadline_hit == "case" and c.category is None and c.detail.startswith("case_deadline_exhausted:timeout")
        d = K.decide([a], "PASS", preflight_green=True)
        assert (d.verdict, d.attribution) == ("error", "runner")
    finally:
        srv.close()


def test_no_time_left_sends_nothing_and_never_retries(slow):
    port = slow(0.0)
    with K.case_deadline(0.0):
        time.sleep(0.01)
        attempts = K.with_retry(lambda no: K.health("127.0.0.1", port, no=no))
    assert len(attempts) == 1
    o, c = attempts[0].exchanges[0]
    assert o.deadline_hit == "case" and o.error == "not_started" and o.addr is None and c.category is None


def test_a_case_that_fits_is_unaffected(slow):
    port = slow(0.0)
    attempts = K.with_retry(lambda no: K.read_series("127.0.0.1", port, 10, bracket_health=True, no=no))
    assert len(attempts) == 1 and attempts[0].category == "PASS" and not attempts[0].cut_by_deadline
    assert K.decide(attempts, "PASS", preflight_green=True).verdict == "pass"


def test_nested_deadline_keeps_the_earlier_one():
    with K.case_deadline(1.0) as outer:
        with K.case_deadline(30.0) as inner:
            assert inner == outer
    with K.case_deadline(30.0) as fresh:
        assert fresh > outer
