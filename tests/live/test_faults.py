"""Fault cases observed by the runner (F1-F11, F13) on the real lab. Run on witness-ctl:
    sudo python3 -m pytest tests/live --live -m fault
Each fault is applied by `inject` and reverted in its finally, then postflight runs.
Expected categories are the catalog's PREDICTIONS; the observation is recorded as seen.
A matching observation is a passing TEST (the fault was detected), never a commissioned device.
Fault cases are never retried. Gateway-observed faults (REQ-08/09) are in test_gateway_cases.py."""
import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

from runner import cases as K
from runner import catalog, db
from runner.classify import CONNECT_TIMEOUT_S, LATENCY_BUDGET_MS, READ_TIMEOUT_S, CASE_DEADLINE_S

REPO = Path(__file__).resolve().parents[2]

pytestmark = [pytest.mark.live, pytest.mark.fault]
SLACK_S = 0.5


def probe(case, lab):
    """IDENTIFY the row the case dials (the inventory row, or the faulted copy for F3/F4)."""
    t = case.target
    return K.identify(t["hostname"], t["port"], lab.identity(case.device_id))


def connect_bounded(a: K.Attempt) -> bool:
    o = a.exchanges[0][0]
    return o.connect_ms is not None and o.connect_ms <= (CONNECT_TIMEOUT_S + SLACK_S) * 1000


def counter_deltas(case, lab, names):
    after = lab.field("counters")["counters"]
    out = {}
    for n in names:
        out[n] = after[n] - case.counters_before[n]
        case.measure(f"field_{n}_delta", out[n], unit="count", clock="witness-field /proc/net/snmp",
                     detail=f"{case.counters_before[n]} -> {after[n]} between fault apply and after the probe")
    return out


def wait_s(a: K.Attempt) -> float:
    """Seconds from the request being sent to the exchange ending."""
    o = a.exchanges[0][0]
    return (o.duration_ms / 1000) - ((o.t_send_wall - o.t_start_wall) if o.t_send_wall else 0)


@pytest.mark.case("FT-F1-STOPPED")
def test_f1_process_stopped(case, lab, inject):
    inject("F1")
    a = probe(case, lab)
    case.finish([a], "CONN_REFUSED", detection_ms=case.detection_ms())


@pytest.mark.case("FT-F2-HUNG")
def test_f2_sigstop_hung(case, lab, inject):
    inject("F2")
    a = probe(case, lab)
    case.finish([a], "READ_TIMEOUT", detection_ms=case.detection_ms(),
                extra_predicates={"returned_within_read_timeout_plus_0.5s": wait_s(a) <= READ_TIMEOUT_S + SLACK_S,
                                  "within_case_deadline": a.duration_ms <= CASE_DEADLINE_S * 1000})


@pytest.mark.case("FT-F6-DELAY-300")
def test_f6_delay_300(case, lab, inject):
    inject("F6-300")
    a = probe(case, lab)
    lat = a.first_latency_ms
    case.finish([a], "PASS_SLOW", detection_ms=case.detection_ms(),
                extra_predicates={"latency_recorded_in_(500,2000]": lat is not None and LATENCY_BUDGET_MS < lat <= 2000})


@pytest.mark.case("FT-F6-DELAY-3000")
def test_f6_delay_3000_all(case, lab, inject):
    inject("F6-3000")
    a = probe(case, lab)
    o = a.exchanges[0][0]
    case.finish([a], "CONNECT_TIMEOUT", detection_ms=case.detection_ms(),
                extra_predicates={"connect_returned_within_timeout_plus_0.5s":
                                  o.connect_ms is not None and o.connect_ms <= (CONNECT_TIMEOUT_S + SLACK_S) * 1000})


@pytest.mark.case("FT-F6-DELAY-3000-DATA")
def test_f6_delay_3000_post_handshake(case, lab, inject):
    inject("F6-3000-data")
    a = probe(case, lab)
    case.finish([a], "READ_TIMEOUT", detection_ms=case.detection_ms(),
                extra_predicates={"returned_within_read_timeout_plus_0.5s": wait_s(a) <= READ_TIMEOUT_S + SLACK_S})


@pytest.mark.case("FT-F7-NAME-SWAP")
def test_f7_name_points_at_wrong_device(case, lab, inject):
    inject("F7")
    a = probe(case, lab)
    det = case.detection_ms()
    c = a.exchanges[0][1]
    fields = c.detail.split(" ", 1)[0].split(",") if c.category == "WRONG_IDENTITY" else []
    # the gateway (independent poller, same /etc/hosts) must flag the same mismatch within 3 P
    P = lab.gw.get("/inventory")[1]["gateway"]["poll_interval_s"]
    ok, samples = lab.gw.sample([case.device_id], lambda r: r[case.device_id]["state"] == "wrong_identity",
                                timeout=3 * P + 1)
    g = lab.gw.device(case.device_id)
    tr = next((t for t in g["transitions"] if t["to"] == "wrong_identity" and t["mono"] >= case.t_apply_start), None)
    case.measure("gateway_wrong_identity_ms", None if tr is None else (tr["mono"] - case.t_apply_start) * 1000,
                 bound=3 * P * 1000, detail="gateway transition to wrong_identity - fault command sent")
    case.file("gateway-during-fault.json", json.dumps(g, indent=1), "gateway")
    case.finish([a], "WRONG_IDENTITY", detection_ms=det,
                extra_predicates={"detail_names_serial_and_device_id": {"serial", "device_id"} <= set(fields),
                                  "dialled_address_was_other_device": a.exchanges[0][0].addr != case.device["address"],
                                  "dev_a_not_commissioned": case.device_id not in db.commissioned_devices(lab.conn, lab.run_id),
                                  "gateway_flags_wrong_identity_within_3P": ok and tr is not None
                                  and {"serial", "device_id"} <= set(g["identity_mismatch"])})


@pytest.mark.case("FT-F7-NAME-MISSING")
def test_f7_name_missing(case, lab, inject):
    inject("F7-missing")
    a = probe(case, lab)
    det = case.detection_ms()
    o = a.exchanges[0][0]
    # the gateway resolves the same name on every poll, so it must also stop reaching dev-a (by name)
    P = lab.gw.get("/inventory")[1]["gateway"]["poll_interval_s"]
    ok, _ = lab.gw.sample([case.device_id], lambda r: r[case.device_id]["last_category"] == "RESOLVE_FAIL",
                          timeout=3 * P + 1)
    g = lab.gw.device(case.device_id)
    case.file("gateway-during-fault.json", json.dumps(g, indent=1), "gateway")
    case.measure("resolve_ms", o.resolve_ms, bound=1000, detail="getaddrinfo(dev-a.lab) with the name removed")
    case.finish([a], "RESOLVE_FAIL", detection_ms=det,
                extra_predicates={"no_address_resolved": o.addr is None,
                                  "failed_before_resolve_timeout": o.resolve_ms is not None and o.resolve_ms < 1000,
                                  "gateway_sees_resolve_fail_within_3P": ok})


@pytest.mark.case("FT-F10-MALFORMED")
def test_f10_malformed(case, lab, inject):
    inject("F10-malformed")
    a = probe(case, lab)
    case.finish([a], "MALFORMED", detection_ms=case.detection_ms(),
                extra_predicates={"detail_bad_json": a.exchanges[0][1].detail.startswith("bad_json"),
                                  "within_case_deadline": a.duration_ms <= CASE_DEADLINE_S * 1000})


@pytest.mark.case("FT-F10-TRUNCATED")
def test_f10_truncated(case, lab, inject):
    inject("F10-truncated")
    a = probe(case, lab)
    case.finish([a], "MALFORMED", detection_ms=case.detection_ms(),
                extra_predicates={"detail_truncated": a.exchanges[0][1].detail.startswith("truncated"),
                                  "within_case_deadline": a.duration_ms <= CASE_DEADLINE_S * 1000})


@pytest.mark.case("FT-F10-WRONG-ID")
def test_f10_wrong_id(case, lab, inject):
    inject("F10-wrong-id")
    a = probe(case, lab)
    case.finish([a], "MALFORMED", detection_ms=case.detection_ms(),
                extra_predicates={"detail_wrong_id": a.exchanges[0][1].detail == "wrong_id",
                                  "within_case_deadline": a.duration_ms <= CASE_DEADLINE_S * 1000})


# ---------------------------------------------------------------- Phase 3

@pytest.mark.case("FT-F3-WRONG-PORT")
def test_f3_wrong_port_in_inventory(case, lab, inject):
    inject("F3")
    a = probe(case, lab)
    det = case.detection_ms()          # before the evidence steps below
    # control: the real device still answers on its inventoried port, so the inventory is wrong, not the device
    ctl = K.identify(case.device["hostname"], case.device["port"], lab.identity(case.device_id))
    # the gateway code, given the same faulted inventory, must reach the same conclusion
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump({**lab.inv, "devices": [case.target if d["device_id"] == case.device_id else d
                                               for d in lab.inv["devices"]]}, f)
    try:
        p = subprocess.run(["python3", "-m", "gateway.gateway", "--inventory", f.name, "--once"], cwd=REPO,
                           capture_output=True, text=True, timeout=20)
    finally:
        os.unlink(f.name)
    case.file("gateway-once-faulted-inventory.json", p.stdout + p.stderr, "gateway")
    once = {d["device_id"]: d for d in json.loads(p.stdout)["devices"]} if p.returncode == 0 else {}
    case.finish([a], "CONN_REFUSED", detection_ms=det,
                extra_predicates={"dialled_port_5021": a.exchanges[0][0].port == catalog.WRONG_PORT,
                                  "device_answers_on_inventoried_port": ctl.category == "PASS",
                                  "gateway_once_agrees_CONN_REFUSED":
                                      once.get(case.device_id, {}).get("last_category") == "CONN_REFUSED"})


@pytest.mark.case("FT-F4-WRONG-ADDR")
def test_f4_wrong_address_unused(case, lab, inject):
    inject("F4")
    a = probe(case, lab)
    det = case.detection_ms()
    o = a.exchanges[0][0]
    counter_deltas(case, lab, ["Ip.InAddrErrors", "Icmp.OutDestUnreachs", "Tcp.OutRsts"])
    case.finish([a], "CONNECT_TIMEOUT", detection_ms=det,
                extra_predicates={"dialled_unused_address": o.addr == catalog.UNUSED_ADDR,
                                  "connect_returned_within_timeout_plus_0.5s": connect_bounded(a)})


@pytest.mark.case("FT-F5-NO-ROUTE")
def test_f5_route_deleted(case, lab, inject):
    inject("F5")
    a = probe(case, lab)
    o = a.exchanges[0][0]
    case.measure("connect_ms", o.connect_ms, detail="connect() to the routeless device subnet")
    case.finish([a], "NO_ROUTE", detection_ms=case.detection_ms(),
                extra_predicates={"failed_before_connect_timeout": o.connect_ms is not None and o.connect_ms < 1000,
                                  "errno_ENETUNREACH": o.error == "ENETUNREACH"})


@pytest.mark.case("FT-F8-DROP")
def test_f8_nft_drop(case, lab, inject):
    inject("F8")
    a = probe(case, lab)
    det = case.detection_ms()
    counter_deltas(case, lab, ["Tcp.OutRsts", "Icmp.OutDestUnreachs"])
    case.finish([a], "CONNECT_TIMEOUT", detection_ms=det,
                extra_predicates={"connect_returned_within_timeout_plus_0.5s": connect_bounded(a)})


@pytest.mark.case("FT-F9-REJECT")
def test_f9_nft_reject_syn(case, lab, inject):
    inject("F9")
    a = probe(case, lab)
    det = case.detection_ms()
    st = lab.field("status")
    case.finish([a], "CONN_REFUSED", detection_ms=det,
                extra_predicates={"device_process_still_running":
                                  f"service-inactive:{case.device['instance']}" not in st["active_faults"]
                                  and any(f.startswith("nft:") for f in st["active_faults"])})


@pytest.mark.case("FT-F9-REJECT-DATA")
def test_f9_nft_reject_after_handshake(case, lab, inject):
    inject("F9-data")
    a = probe(case, lab)
    o, c = a.exchanges[0]
    case.finish([a], "CONN_RESET", detection_ms=case.detection_ms(),
                extra_predicates={"handshake_completed": o.connect_ms is not None and o.stage_failed in (None, "send"),
                                  "zero_response_bytes": len(o.data) == 0})


def _f11(case, lab, inject, fault_id, end, detail):
    inject(fault_id)
    d = case.target
    a = K.read_series(d["hostname"], d["port"], 10, bracket_health=False)
    cats = [c.category for _, c in a.exchanges]
    o, c = a.exchanges[-1]
    case.finish([a], "CONN_RESET", detection_ms=case.detection_ms(),
                extra_predicates={"two_reads_then_reset": cats == ["PASS", "PASS", "CONN_RESET"],
                                  f"read_end_{end}": o.end == end, f"detail_{detail}": c.detail == detail,
                                  "zero_response_bytes": len(o.data) == 0,
                                  "series_incomplete_not_pass": len(cats) < 10})


@pytest.mark.case("FT-F11-CLOSE-FIN")
def test_f11_mid_session_fin(case, lab, inject):
    _f11(case, lab, inject, "F11-fin", "eof", "eof_before_response")


@pytest.mark.case("FT-F11-CLOSE-RST")
def test_f11_mid_session_rst(case, lab, inject):
    _f11(case, lab, inject, "F11-rst", "reset", "reset_before_response")


@pytest.mark.case("FT-F13-SKEW")
def test_f13_clock_skew(case, lab, inject):
    inject("F13-skew")
    d = case.target
    a = K.read_series(d["hostname"], d["port"], 3, bracket_health=False)
    c = a.exchanges[0][1]
    skew = float(c.detail.split(":")[1][:-1]) if c.detail.startswith("ts_outside_window:") else None
    case.measure("read_skew_s", skew, unit="s", bound=2.0, clock="device ts vs runner realtime")
    case.finish([a], "STALE_DATA", detection_ms=case.detection_ms(),
                extra_predicates={"first_read_stale_by_+30s": skew is not None and 29.0 <= skew <= 31.0})


@pytest.mark.case("FT-F13-REPEAT-SEQ")
def test_f13_repeat_seq(case, lab, inject):
    inject("F13-repeat-seq")
    d = case.target
    a = K.read_series(d["hostname"], d["port"], 3, bracket_health=False)
    cats = [c.category for _, c in a.exchanges]
    case.finish([a], "STALE_DATA", detection_ms=case.detection_ms(),
                extra_predicates={"first_read_pass_second_stale": cats == ["PASS", "STALE_DATA"],
                                  "detail_seq_not_increasing": a.exchanges[-1][1].detail.startswith("seq_not_increasing")})
