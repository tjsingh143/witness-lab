"""Classifier unit tests: every category, frame/schema edge cases and stage precedence
(docs/protocol.md section 5). Pure function tests on hand-built Observations."""
import errno
import json
import time

import pytest

from runner import classify as C
from runner.classify import Identity, Observation, ReadState, classify, parse_frame, FrameError

EXPECT = Identity("dev-a", "WIT-0001", "1.0.0")
NOW = time.time()


def ts(t):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def obs(cmd="IDENTIFY", data=None, end="newline", req_id=1, latency=5.0, **kw):
    if isinstance(data, dict):
        data = (json.dumps(data) + "\n").encode()
    return Observation(host="dev-a.lab", port=5020, cmd=cmd, req_id=req_id, addr="10.77.2.11",
                       data=data or b"", end=end, latency_ms=latency, response_ms=latency,
                       t_send_wall=NOW, t_recv_wall=NOW + 0.01, **kw)


IDENT = {"id": 1, "device_id": "dev-a", "serial": "WIT-0001", "model": "WSIM-1", "fw_version": "1.0.0"}
HEALTH = {"id": 1, "status": "ok", "uptime_s": 12.5, "sensor_ok": True}


def read(seq=5, t=None, **over):
    return {"id": 1, "seq": seq, "ts": ts(NOW if t is None else t), "temp_c": 22.4, "rh_pct": 41.8, **over}


def cat(o, **kw):
    return classify(o, **kw).category


# ---------------------------------------------------------------- all 11 categories

def test_pass_identify():
    c = classify(obs(data=IDENT), expect=EXPECT)
    assert (c.category, c.stage) == ("PASS", "latency")


def test_pass_slow_over_budget():
    assert cat(obs(data=IDENT, latency=500.1), expect=EXPECT) == "PASS_SLOW"
    assert cat(obs(data=IDENT, latency=500.0), expect=EXPECT) == "PASS"   # budget is inclusive


def test_resolve_fail():
    assert cat(obs(stage_failed="resolve", error="gaierror:-2", end=None)) == "RESOLVE_FAIL"
    assert cat(obs(stage_failed="resolve", error="timeout", end=None)) == "RESOLVE_FAIL"


@pytest.mark.parametrize("eno", [errno.ENETUNREACH, errno.EHOSTUNREACH])
def test_no_route(eno):
    assert cat(obs(stage_failed="connect", errno=eno, error="x", end=None)) == "NO_ROUTE"


def test_conn_refused():
    assert cat(obs(stage_failed="connect", errno=errno.ECONNREFUSED, error="ECONNREFUSED", end=None)) == "CONN_REFUSED"


def test_connect_timeout():
    assert cat(obs(stage_failed="connect", error="timeout", end=None)) == "CONNECT_TIMEOUT"


def test_read_timeout_zero_bytes():
    assert cat(obs(data=b"", end="timeout")) == "READ_TIMEOUT"


@pytest.mark.parametrize("end", ["eof", "reset"])
def test_conn_reset_zero_bytes(end):
    # protocol.md 2.6: FIN or RST before ANY response byte is CONN_RESET
    assert cat(obs(data=b"", end=end)) == "CONN_RESET"


def test_conn_reset_on_send():
    assert cat(obs(stage_failed="send", errno=errno.EPIPE, error="EPIPE", end=None)) == "CONN_RESET"


def test_malformed_bad_json():
    assert cat(obs(data=b'{"id":1,}\n')) == "MALFORMED"


def test_wrong_identity_serial_only():
    c = classify(obs(data={**IDENT, "serial": "WIT-0002"}), expect=EXPECT)
    assert c.category == "WRONG_IDENTITY" and c.detail.startswith("serial ")


def test_wrong_identity_fw_mismatch_is_identity():
    c = classify(obs(data={**IDENT, "fw_version": "1.0.1"}), expect=EXPECT)
    assert c.category == "WRONG_IDENTITY" and c.detail.startswith("fw_version")


def test_wrong_identity_other_device_names_both_fields():
    c = classify(obs(data={**IDENT, "device_id": "dev-b", "serial": "WIT-0002"}), expect=EXPECT)
    assert c.category == "WRONG_IDENTITY" and c.detail.split()[0] == "device_id,serial"


def test_stale_data_clock_skew():
    c = classify(obs(cmd="READ", data=read(t=NOW + 30)))
    assert c.category == "STALE_DATA" and "ts_outside_window" in c.detail


def test_stale_data_window_edges():
    assert cat(obs(cmd="READ", data=read(t=NOW + 0.01 + 1.999))) == "PASS"
    assert cat(obs(cmd="READ", data=read(t=NOW - 1.999))) == "PASS"
    assert cat(obs(cmd="READ", data=read(t=NOW - 2.1))) == "STALE_DATA"


def test_stale_data_repeat_seq_and_backwards_ts():
    prev = ReadState(seq=5, ts=C.parse_ts(ts(NOW)))   # same ms precision as the frame
    assert cat(obs(cmd="READ", data=read(seq=5)), prev_read=prev) == "STALE_DATA"
    assert cat(obs(cmd="READ", data=read(seq=6, t=NOW - 0.5)), prev_read=prev) == "STALE_DATA"
    assert cat(obs(cmd="READ", data=read(seq=7, t=NOW)), prev_read=prev) == "PASS"   # equal ts allowed


# ---------------------------------------------------------------- read-stage edge cases

@pytest.mark.parametrize("end", ["eof", "reset"])
def test_partial_then_close_is_malformed_truncated(end):
    c = classify(obs(data=b'{"id":1,"dev', end=end))
    assert c.category == "MALFORMED" and c.detail.startswith("truncated:" + end)


def test_partial_held_open_is_malformed_incomplete():
    c = classify(obs(data=b'{"id":1}', end="timeout"))
    assert c.category == "MALFORMED" and c.detail.startswith("incomplete")


def test_oversize():
    assert classify(obs(data=b"x" * 4096, end="oversize")).detail == "oversize"


def test_unexpected_errno_is_unclassifiable():
    c = classify(obs(stage_failed="connect", errno=errno.EADDRNOTAVAIL, error="EADDRNOTAVAIL", end=None))
    assert c.category is None
    c = classify(obs(data=b"", end="error", errno=errno.ETIMEDOUT, error="ETIMEDOUT"))
    assert c.category is None


# ---------------------------------------------------------------- frame layer

@pytest.mark.parametrize("raw,detail", [
    (b"\n", "empty_frame"),
    (b'{"id":1}\r\n', "carriage_return"),
    (b'\xef\xbb\xbf{"id":1}\n', "utf8_bom"),
    (b'{"id":1,"x":"\xff"}\n', "invalid_utf8"),
    (b'{"id":1,"x":"\xed\xa0\x80"}\n', "invalid_utf8"),       # UTF-8 encoded surrogate
    (b'{"id":1,"x":"\xc0\xaf"}\n', "invalid_utf8"),           # overlong
    (b'[1,2]\n', "not_object"),
    (b'{"id":1,"id":1}\n', "duplicate_key:id"),
    (b'{"id":NaN}\n', "non_json_constant:NaN"),
    (b'{"id":Infinity}\n', "non_json_constant:Infinity"),
    (b'{"id":1e400}\n', "non_finite_number"),
    (b'{"id":1} {"id":2}\n', "bad_json:JSONDecodeError"),
    (b'{"id":1}', "no_newline"),
])
def test_frame_errors(raw, detail):
    with pytest.raises(FrameError) as e:
        parse_frame(raw)
    assert str(e.value) == detail


def test_frame_whitespace_allowed_and_max_length():
    assert parse_frame(b' {\t"id" : 1 } \n') == {"id": 1}
    pad = 4096 - len(b'{"id":1,"p":""}\n')
    assert parse_frame(b'{"id":1,"p":"' + b"a" * pad + b'"}\n')["id"] == 1
    with pytest.raises(FrameError):
        parse_frame(b'{"id":1,"p":"' + b"a" * (pad + 1) + b'"}\n')


# ---------------------------------------------------------------- schema layer (row 9 order)

@pytest.mark.parametrize("mut,detail", [
    (lambda d: d.pop("id"), "id_missing"),
    (lambda d: d.update(id=True), "id_type"),
    (lambda d: d.update(id=1.0), "id_type"),
    (lambda d: d.update(id="1"), "id_type"),
    (lambda d: d.update(id=2), "wrong_id"),
    (lambda d: d.update(error="bad_request"), "device_error"),
    (lambda d: d.pop("serial"), "missing:serial"),
    (lambda d: d.update(serial=1), "type:serial"),
    (lambda d: d.update(serial=""), "type:serial"),
    (lambda d: d.update(serial="WIT-01"), "domain:serial"),
    (lambda d: d.update(device_id="Dev_A"), "domain:device_id"),
    (lambda d: d.update(model="m" * 65), "domain:model"),
    (lambda d: d.update(extra=1), "unknown_key:extra"),
])
def test_identify_schema(mut, detail):
    d = dict(IDENT)
    mut(d)
    c = classify(obs(data=d), expect=EXPECT)
    assert (c.category, c.detail) == ("MALFORMED", detail)


@pytest.mark.parametrize("over,detail", [
    ({"temp_c": "22.4"}, "type:temp_c"),             # mutant: temp_c as a string
    ({"temp_c": True}, "type:temp_c"),
    ({"temp_c": 85.01}, "out_of_range:temp_c"),
    ({"rh_pct": -0.1}, "out_of_range:rh_pct"),
    ({"seq": 0}, "out_of_range:seq"),
    ({"seq": 1.0}, "type:seq"),
    ({"seq": 2**53}, "type:seq"),
    ({"ts": "2026-10-16T21:15:03+00:00"}, "domain:ts"),
    ({"ts": "2026-10-16t21:15:03Z"}, "domain:ts"),
    ({"ts": "2026-02-30T21:15:03Z"}, "domain:ts"),
    ({"ts": "2026-10-16T21:15:03.1234567Z"}, "domain:ts"),
])
def test_read_schema(over, detail):
    c = classify(obs(cmd="READ", data=read(**over)))
    assert (c.category, c.detail) == ("MALFORMED", detail)


def test_health_schema_bool_and_status():
    assert classify(obs(cmd="HEALTH", data={**HEALTH, "sensor_ok": 1})).detail == "type:sensor_ok"
    assert classify(obs(cmd="HEALTH", data={**HEALTH, "status": "OK"})).detail == "domain:status"
    assert classify(obs(cmd="HEALTH", data={**HEALTH, "uptime_s": 0})).category == "PASS"   # int is a number


def test_degraded_health_is_still_pass_category():
    c = classify(obs(cmd="HEALTH", data={**HEALTH, "status": "degraded", "sensor_ok": False}))
    assert c.category == "PASS"   # truthful answer; REQ-03 verdict fails elsewhere (protocol.md section 8)


# ---------------------------------------------------------------- precedence

def test_wrong_id_echo_beats_wrong_identity():
    # a well-formed response from the WRONG device that also echoes the wrong id: MALFORMED
    c = classify(obs(data={**IDENT, "id": 2, "device_id": "dev-b", "serial": "WIT-0002"}), expect=EXPECT)
    assert (c.category, c.detail) == ("MALFORMED", "wrong_id")


def test_wrong_id_beats_error_key_and_missing_keys():
    assert classify(obs(data={"id": 7, "error": "x"})).detail == "wrong_id"
    assert classify(obs(data={"id": 1, "error": "unknown_cmd"})).detail == "device_error"


def test_type_errors_reported_before_domain_errors():
    c = classify(obs(cmd="READ", data=read(seq=0, temp_c="x")))
    assert c.detail == "type:temp_c"


def test_truncated_wrong_identity_is_malformed():
    frame = (json.dumps({**IDENT, "serial": "WIT-0002"}) + "\n").encode()
    assert cat(obs(data=frame[:20], end="eof"), expect=EXPECT) == "MALFORMED"


def test_bytes_then_reset_is_malformed_not_conn_reset():
    assert cat(obs(data=b"{", end="reset")) == "MALFORMED"


def test_stale_beats_slow_and_identity_beats_slow():
    assert cat(obs(cmd="READ", data=read(t=NOW + 30), latency=900)) == "STALE_DATA"
    assert cat(obs(data={**IDENT, "serial": "WIT-0009"}, latency=900), expect=EXPECT) == "WRONG_IDENTITY"


def test_malformed_beats_stale():
    assert classify(obs(cmd="READ", data=read(t=NOW + 30, rh_pct=101))).detail == "out_of_range:rh_pct"


def test_identity_not_checked_without_expectation_and_not_for_other_cmds():
    assert cat(obs(data={**IDENT, "serial": "WIT-0002"})) == "PASS"


def test_combine():
    assert C.combine(["PASS", "PASS_SLOW", "PASS"]) == "PASS_SLOW"
    assert C.combine(["PASS", "STALE_DATA", "MALFORMED"]) == "STALE_DATA"
    assert C.combine(["PASS", None]) is None


def test_constants_match_protocol():
    assert (C.CONNECT_TIMEOUT_S, C.READ_TIMEOUT_S, C.ATTEMPT_DEADLINE_S) == (1.0, 2.0, 4.0)
    assert (C.LATENCY_BUDGET_MS, C.CLOCK_WINDOW_S, C.MAX_FRAME, C.CASE_DEADLINE_S) == (500.0, 2.0, 4096, 30.0)
    assert len(C.CATEGORIES) == 11
