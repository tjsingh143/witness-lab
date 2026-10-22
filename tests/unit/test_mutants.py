"""Mutant device builds (brief 7.4) on loopback: each mutant breaks exactly one contract rule, and the
runner's own client/classifier/case logic sees it. The live proof (real systemd service on witness-field,
real suite from witness-ctl) is the mutant campaign recorded in the results database."""
import threading

import pytest

from device import mutants
from device.device import Device, DeviceServer, ModeControl, main
from runner import cases as K
from runner import catalog
from runner.classify import Identity, classify
from runner.client import Deadlines, single

EXPECT = Identity("dev-a", "WIT-0001", "1.0.0")
DL = Deadlines(resolve_s=0.5, connect_s=0.5, read_s=0.5, attempt_s=1.5)


def serve(mutant: str | None, sleep=None):
    d = Device("dev-a", "WIT-0001", "WSIM-1", "1.0.0", mutant=mutants.Mutant(mutant) if mutant else None,
               **({"sleep": sleep} if sleep else {}))
    # idle timeout well above DL.read_s (as on the lab: 30 s vs 2 s); equal values raced (device FIN vs client
    # timeout) and made the M3 test flaky (phase4-final-unit-guest-20261017T140157Z.log)
    srv = DeviceServer(("127.0.0.1", 0), d, idle_timeout=3.0)
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    return d, srv, srv.server_address[1]


@pytest.fixture
def server(request):
    d, srv, port = serve(*request.param) if isinstance(request.param, tuple) else serve(request.param)
    yield d, port
    srv.stopping = True
    srv.shutdown()
    srv.server_close()
    srv.close_all()


def test_grammar():
    for ok in ("other-serial:WIT-0002", "seq-reuse", "no-newline", "off-by-one-id", "temp-string", "slow-7th"):
        assert mutants.valid_mutant(ok), ok
    for bad in ("", "other-serial:", "other-serial:wit 2", "slow-8th", "seq-reuse;reboot", "normal", None):
        assert not mutants.valid_mutant(bad), bad
    with pytest.raises(ValueError):
        mutants.Mutant("explode")


def test_catalog_specs_are_valid_and_cover_the_brief():
    devs = [{"device_id": "dev-a", "serial": "WIT-0001"}, {"device_id": "dev-b", "serial": "WIT-0002"}]
    specs = [catalog.mutant_spec(m.mutant_id, devs) for m in catalog.MUTANTS]
    assert specs == ["other-serial:WIT-0002", "seq-reuse", "no-newline", "off-by-one-id", "temp-string", "slow-7th"]
    assert all(mutants.valid_mutant(s) for s in specs)


@pytest.mark.parametrize("server", [None], indirect=True)
def test_stock_build_reports_stock(server, tmp_path):
    d, port = server
    assert d.build == "stock"
    assert classify(single("127.0.0.1", port, "IDENTIFY", DL), expect=EXPECT).category == "PASS"


@pytest.mark.parametrize("server", ["other-serial:WIT-0002"], indirect=True)
def test_m1_other_serial_is_wrong_identity(server):
    _, port = server
    c = classify(single("127.0.0.1", port, "IDENTIFY", DL), expect=EXPECT)
    assert c.category == "WRONG_IDENTITY" and c.detail.startswith("serial")


@pytest.mark.parametrize("server", ["seq-reuse"], indirect=True)
def test_m2_seq_reuse_is_stale_data_within_ten_reads(server):
    _, port = server
    a = K.read_series("127.0.0.1", port, 10, bracket_health=True, dl=DL)
    seqs = [c.payload["seq"] for o, c in a.exchanges if o.cmd == "READ" and c.payload]
    assert seqs[:5] == [1, 2, 3, 4, 5]
    assert a.category == "STALE_DATA" and "seq_not_increasing" in a.deciding.detail


@pytest.mark.parametrize("server", ["no-newline"], indirect=True)
def test_m3_no_newline_is_malformed_after_the_read_timeout_never_a_hang(server):
    _, port = server
    o = single("127.0.0.1", port, "HEALTH", DL)
    c = classify(o)
    assert o.end == "timeout" and len(o.data) > 0 and not o.data.endswith(b"\n")
    assert c.category == "MALFORMED" and c.detail.startswith("incomplete:")
    assert o.duration_ms < (DL.read_s + 0.3) * 1000


@pytest.mark.parametrize("server", ["off-by-one-id"], indirect=True)
def test_m4_wrong_id_is_malformed(server):
    _, port = server
    c = classify(single("127.0.0.1", port, "IDENTIFY", DL), expect=EXPECT)
    assert c.category == "MALFORMED" and c.detail.startswith("wrong_id")


@pytest.mark.parametrize("server", ["temp-string"], indirect=True)
def test_m5_temp_string_breaks_only_read(server):
    _, port = server
    assert classify(single("127.0.0.1", port, "HEALTH", DL)).category == "PASS"
    o = single("127.0.0.1", port, "READ", DL)
    c = classify(o)
    assert b'"temp_c":"' in o.data and c.category == "MALFORMED" and "temp_c" in c.detail


def test_m6_slow_every_7th_request_process_wide():
    slept = []
    d, srv, port = serve("slow-7th", sleep=slept.append)       # recorded, not slept: keeps the test fast
    try:
        for _ in range(13):
            single("127.0.0.1", port, "HEALTH", DL)
        assert slept == [2.5]                                   # request 7 only (14 not reached)
        single("127.0.0.1", port, "HEALTH", DL)
        assert slept == [2.5, 2.5]
    finally:
        srv.stopping = True
        srv.shutdown()
        srv.server_close()


def test_m6_real_sleep_is_a_read_timeout_and_retry_can_hide_it():
    """The 7th request really sleeps: attempt 1 READ_TIMEOUT, attempt 2 (request 8) passes -> FLAKE (fail)."""
    d, srv, port = serve("slow-7th")
    try:
        for _ in range(6):
            single("127.0.0.1", port, "HEALTH", DL)
        attempts = K.with_retry(lambda no: K.health("127.0.0.1", port, dl=DL, no=no))
        assert [a.category for a in attempts] == ["READ_TIMEOUT", "PASS"]
        dec = K.decide(attempts, "PASS", preflight_green=True)
        assert dec.verdict == "fail" and dec.detail.startswith("FLAKE")
    finally:
        srv.stopping = True
        srv.shutdown()
        srv.server_close()


def test_state_reports_build(tmp_path):
    d = Device("dev-a", "WIT-0001", "WSIM-1", "1.0.0", mutant=mutants.Mutant("seq-reuse"))
    ModeControl(d, str(tmp_path), "t").write_state()
    import json
    assert json.loads((tmp_path / "state.json").read_text())["build"] == "mutant:seq-reuse"


def test_main_refuses_unknown_mutant():
    assert main(["--device-id", "dev-a", "--serial", "WIT-0001", "--fw-version", "1.0.0", "--bind", "127.0.0.1",
                 "--mutant", "explode"]) == 2


def test_faultctl_uses_the_device_grammar():
    import importlib.util
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "scripts/faultctl.py").read_text()
    assert "from mutants import valid_mutant" in src and "50-witness-mutant.conf" in src
    assert importlib.util.find_spec("device.mutants") is not None
