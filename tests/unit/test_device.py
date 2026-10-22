"""Device simulator unit tests: protocol replies, fault modes and lifecycle on loopback.
The deployed systemd service is tested on witness-field by the live suite."""
import json
import os
import socket
import threading
import time

import pytest

from device.device import Device, DeviceServer, ModeControl
from runner.classify import Identity, classify, parse_frame
from runner.client import Connection, Deadlines, single

EXPECT = Identity("dev-a", "WIT-0001", "1.0.0")
DL = Deadlines(resolve_s=0.5, connect_s=0.5, read_s=0.5, attempt_s=1.5)


@pytest.fixture
def dev():
    d = Device("dev-a", "WIT-0001", "WSIM-1", "1.0.0")
    srv = DeviceServer(("127.0.0.1", 0), d, idle_timeout=0.5)
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    t.start()
    yield d, srv, srv.server_address[1]
    srv.stopping = True
    srv.shutdown()
    srv.server_close()
    srv.close_all()


def raw(port, payload: bytes, read_until_close=False) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=1) as s:
        s.sendall(payload)
        buf = b""
        while read_until_close or b"\n" not in buf:
            try:
                chunk = s.recv(8192)
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk
        return buf


def test_identify_health_read_pass(dev):
    _, _, port = dev
    for cmd in ("IDENTIFY", "HEALTH", "READ"):
        o = single("127.0.0.1", port, cmd, DL)
        c = classify(o, expect=EXPECT)
        assert c.category == "PASS", (cmd, c)


def test_read_seq_strictly_increasing_across_connections(dev):
    _, _, port = dev
    seqs = []
    for _ in range(3):
        conn = Connection("127.0.0.1", port, DL)
        assert conn.open("READ") is None
        for _ in range(4):
            seqs.append(parse_frame(conn.exchange("READ").data)["seq"])
        conn.close()
    assert seqs == list(range(1, 13))   # deterministic: starts at 1, +1 per READ served


def test_values_deterministic_per_seq():
    a, b = Device("dev-a", "WIT-0001", "m", "1.0.0"), Device("dev-a", "WIT-0001", "m", "1.0.0")
    ra, rb = a.respond(1, "READ"), b.respond(1, "READ")
    assert (ra["temp_c"], ra["rh_pct"]) == (rb["temp_c"], rb["rh_pct"])


def test_bad_requests_get_error_and_connection_stays_open(dev):
    _, _, port = dev
    with socket.create_connection(("127.0.0.1", port), timeout=1) as s:
        f = s.makefile("rb")
        for req, want in [(b"nonsense\n", {"id": None, "error": "bad_json"}),
                          (b'{"id": 5}\n', {"id": 5, "error": "bad_request"}),
                          (b'{"id": 6, "cmd": "REBOOT"}\n', {"id": 6, "error": "unknown_cmd"}),
                          (b'{"id": -1, "cmd": "READ"}\n', {"id": None, "error": "bad_request"}),
                          (b'{"id": 7, "cmd": "HEALTH", "x": 1}\n', {"id": 7, "error": "bad_request"})]:
            s.sendall(req)
            assert json.loads(f.readline()) == want
        s.sendall(b'{"id": 8, "cmd": "IDENTIFY"}\n')
        assert json.loads(f.readline())["serial"] == "WIT-0001"


def test_oversize_request_closes(dev):
    _, _, port = dev
    out = raw(port, b"x" * 5000, read_until_close=True)
    assert json.loads(out) == {"id": None, "error": "frame_too_long"}


@pytest.mark.parametrize("mode,detail", [("malformed", "bad_json"), ("truncated", "truncated:eof"),
                                         ("wrong-id", "wrong_id")])
def test_fault_modes_are_malformed(dev, mode, detail):
    d, _, port = dev
    d.mode = mode
    c = classify(single("127.0.0.1", port, "IDENTIFY", DL), expect=EXPECT)
    assert c.category == "MALFORMED" and c.detail.startswith(detail), c
    d.mode = "normal"
    assert classify(single("127.0.0.1", port, "IDENTIFY", DL), expect=EXPECT).category == "PASS"


def test_idle_connection_closed_with_fin(dev):
    _, _, port = dev
    with socket.create_connection(("127.0.0.1", port), timeout=2) as s:
        t0 = time.monotonic()
        assert s.recv(10) == b""       # FIN after the (test) idle timeout of 0.5 s
        assert 0.4 < time.monotonic() - t0 < 1.5


def test_mode_control_file_and_state(tmp_path):
    d = Device("dev-a", "WIT-0001", "m", "1.0.0")
    mc = ModeControl(d, str(tmp_path), "2026-01-01T00:00:00.000Z", str(tmp_path / "mode"))
    mc.reload()
    st = json.loads((tmp_path / "state.json").read_text())
    assert st["mode"] == "normal" and st["pid"] == os.getpid() and st["mode_error"] is None
    (tmp_path / "mode").write_text("wrong-id\n")
    mc.reload()
    assert d.mode == "wrong-id" and json.loads((tmp_path / "state.json").read_text())["mode"] == "wrong-id"
    (tmp_path / "mode").write_text("explode\n")
    mc.reload()                                   # unknown mode: rejected, previous mode kept
    st = json.loads((tmp_path / "state.json").read_text())
    assert d.mode == "wrong-id" and "unknown mode" in st["mode_error"]
    (tmp_path / "mode").unlink()
    mc.reload()
    assert d.mode == "normal"


def test_graceful_shutdown_refuses_new_and_closes_open():
    d = Device("dev-a", "WIT-0001", "m", "1.0.0")
    srv = DeviceServer(("127.0.0.1", 0), d)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    t.start()
    s = socket.create_connection(("127.0.0.1", port), timeout=2)
    time.sleep(0.1)
    srv.stopping = True
    srv.shutdown()
    srv.server_close()
    srv.close_all()
    assert s.recv(10) == b""      # open connection sees FIN
    s.close()
    c = classify(single("127.0.0.1", port, "IDENTIFY", DL))
    assert c.category == "CONN_REFUSED"


def test_main_refuses_wildcard_bind_and_missing_identity():
    from device.device import main
    assert main(["--device-id", "d", "--serial", "WIT-0001", "--fw-version", "1.0.0", "--bind", "0.0.0.0"]) == 2
    assert main(["--bind", "127.0.0.1"]) == 2


@pytest.mark.parametrize("mode,end,detail", [("close-after:2", "eof", "eof_before_response"),
                                             ("reset-after:2", "reset", "reset_before_response")])
def test_f11_mid_session_close_fin_vs_rst(dev, mode, end, detail):
    """Two responses, then the third request gets FIN (EOF) or RST before any byte: both CONN_RESET
    (protocol section 2.6); the read end and the detail tell them apart."""
    d, _, port = dev
    d.mode = mode
    conn = Connection("127.0.0.1", port, DL)
    assert conn.open("IDENTIFY") is None
    cats = []
    for cmd in ("IDENTIFY", "HEALTH", "READ"):
        o = conn.exchange(cmd)
        cats.append((classify(o, expect=EXPECT).category, o.end))
    conn.close()
    assert cats[:2] == [("PASS", "newline"), ("PASS", "newline")]
    o_cat, o_end = cats[2]
    assert (o_cat, o_end) == ("CONN_RESET", end)
    d.mode = "normal"


def test_f13_clock_skew_and_repeat_seq():
    t = [1_800_000_000.0]
    d = Device("dev-a", "WIT-0001", "m", "1.0.0", clock=lambda: t[0])
    d.mode = "clock-skew:+30s"
    assert d.respond(1, "READ")["ts"] == "2027-01-15T08:00:30.000Z"
    d.mode = "clock-skew:-5s"
    assert d.respond(2, "READ")["ts"] == "2027-01-15T07:59:55.000Z"
    d.mode = "repeat-seq"
    s = [d.respond(i, "READ")["seq"] for i in range(3)]
    assert s == [2, 2, 2]                          # frozen; ts stays current (only the seq rule breaks)
    d.mode = "normal"
    assert d.respond(9, "READ")["seq"] == 3


def test_mode_grammar_same_in_device_and_faultctl(monkeypatch):
    import importlib.util
    from pathlib import Path
    from device.device import valid_mode
    repo = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("WIT_REPO", str(repo))
    spec = importlib.util.spec_from_file_location("faultctl_under_test", repo / "scripts/faultctl.py")
    fc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fc)
    good = ["malformed", "truncated", "wrong-id", "repeat-seq", "close-after:1", "reset-after:9",
            "clock-skew:+30s", "clock-skew:-1s", "clock-skew:+3600s"]
    bad = ["", "explode", "close-after:0", "close-after:10", "reset-after:x", "clock-skew:30s", "clock-skew:+0s",
           "clock-skew:+3601s", "clock-skew:+30", "close-after:2;id", "repeat-seq ", "CLOSE-AFTER:2"]
    assert all(valid_mode(m) and fc.valid_mode(m) for m in good)
    assert not any(valid_mode(m) or fc.valid_mode(m) for m in bad)
    assert valid_mode("normal") and not fc.valid_mode("normal")     # faultctl applies faults; revert sets normal
    assert set(fc.NFT_KINDS) == {"drop", "reject", "reject-data"}


# ---------------------------------------------------------------- request frames (independent audit F-05)

FORBIDDEN = {   # frame bodies (without the \n terminator) that docs/protocol.md section 2 rule 4 rejects
    "duplicate id": b'{"id":1,"id":2,"cmd":"IDENTIFY"}',
    "duplicate cmd": b'{"id":1,"cmd":"READ","cmd":"IDENTIFY"}',
    "duplicate, same value": b'{"id":1,"id":1,"cmd":"IDENTIFY"}',
    "raw CR inside": b'{"id":1,\r"cmd":"IDENTIFY"}',
    "CRLF terminator": b'{"id":1,"cmd":"IDENTIFY"}\r',
    "UTF-8 BOM": b'\xef\xbb\xbf{"id":1,"cmd":"IDENTIFY"}',
    "NaN": b'{"id":NaN,"cmd":"IDENTIFY"}',
    "trailing data": b'{"id":1,"cmd":"IDENTIFY"} {}',
    "invalid UTF-8": b'{"id":1,"cmd":"\xff"}',
    "overlong UTF-8": b'{"id":1,"cmd":"\xc0\xafIDENTIFY"}',
    "encoded surrogate": b'{"id":1,"cmd":"\xed\xa0\x80"}',
    "not an object": b'[1,"IDENTIFY"]',
    "empty": b"",
}


@pytest.mark.parametrize("name", sorted(FORBIDDEN))
def test_forbidden_request_frames_are_bad_json(name):
    d = Device("dev-a", "WIT-0001", "WSIM-1", "1.0.0")
    assert d.parse_request(FORBIDDEN[name]) == (None, None, "bad_json")
    out, close, _ = d.handle_line(FORBIDDEN[name])
    assert json.loads(out) == {"id": None, "error": "bad_json"} and close is None


@pytest.mark.parametrize("name", sorted(FORBIDDEN))
def test_device_request_parser_matches_runner_frame_parser(name):
    """Parity: whatever the runner rejects as a response frame (runner/classify.parse_frame), the device rejects as
    a request frame, and the other way round."""
    from runner.classify import FrameError
    with pytest.raises(FrameError):
        parse_frame(FORBIDDEN[name] + b"\n")


def test_deeply_nested_request_gets_a_bounded_error_reply():
    """Valid JSON whose cmd is 2000 nested arrays: Python 3.12's parser raises RecursionError (caught -> bad_json;
    before the fix it escaped the handler), 3.14 parses it (-> bad_request). Either way: an error reply, no crash."""
    d = Device("dev-a", "WIT-0001", "WSIM-1", "1.0.0")
    out, close, _ = d.handle_line(b'{"id":1,"cmd":' + b"[" * 2000 + b"]" * 2000 + b"}")
    assert json.loads(out)["error"] in ("bad_json", "bad_request") and close is None


def test_valid_requests_still_accepted():
    d = Device("dev-a", "WIT-0001", "WSIM-1", "1.0.0")
    for body in (b'{"id":1,"cmd":"IDENTIFY"}', b'{"id": 1, "cmd": "IDENTIFY"}', b'{"id":1,\t"cmd":"IDENTIFY"}',
                 b' {"cmd":"IDENTIFY","id":1} ', b'{"id":2147483647,"cmd":"READ"}'):
        rid, cmd, err = d.parse_request(body)
        assert err is None and cmd in ("IDENTIFY", "READ") and parse_frame(body + b"\n")


def test_forbidden_frames_on_a_socket_then_the_connection_still_serves(dev):
    _, _, port = dev
    with socket.create_connection(("127.0.0.1", port), timeout=1) as s:
        f = s.makefile("rb")
        for name in ("duplicate id", "duplicate cmd", "raw CR inside", "CRLF terminator"):
            s.sendall(FORBIDDEN[name] + b"\n")
            assert json.loads(f.readline()) == {"id": None, "error": "bad_json"}, name
        s.sendall(b'{"id": 9, "cmd": "IDENTIFY"}\n')
        assert json.loads(f.readline())["id"] == 9
