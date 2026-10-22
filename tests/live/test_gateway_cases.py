"""Gateway cases on the real lab (REQ-08, REQ-09). Run on witness-ctl:
    sudo python3 -m pytest tests/live --live -k "gateway or f12"
The gateway (witness-gateway.service on witness-ctl) polls witness-field every P = 2.0 s. Its
state is read through GET /devices/<id>; every *_mono value it reports is CLOCK_MONOTONIC on
witness-ctl, the same clock as the runner's time.monotonic(), so detection and recovery times
are differences on ONE clock, with these references:
- REQ-09 detection = gateway transition to `unreachable` (its poll's completion time) minus the
  moment the runner SENT the fault command (case.t_apply_start). The fault cannot act earlier,
  so this is an upper bound and never negative. Bound 3 P = 6000 ms.
- Category: the transition poll can land while the fault is still taking effect. Run 54: a poll
  reached dev-a during its ~115 ms graceful stop (listener still open, no longer accepting), the
  kernel completed the handshake and the connection was reset when the listener closed, giving
  CONN_RESET, not CONN_REFUSED. So the case's observed category is the gateway's category for a
  poll that STARTED after the fault was confirmed applied (steady state); the transition poll's
  category is kept in the result detail and the evidence.
- Recovery after a revert is measured the same way, from the revert command being SENT. Run 47
  showed why: the nft table was gone and the gateway recovered 13 ms before the revert call
  RETURNED (it was still draining connections), so "from return" found no later transition.
- REQ-08 detection = first PASS HEALTH (probe end) minus the moment `witness-faultctl apply
  restart` RETURNED on ctl (systemctl restart returned on field, plus the SSH reply). Bound 10 s.
  The value from the command being SENT is recorded too, and both must be within the bound.
- REQ-08 gateway recovery = the gateway poll that first saw the restarted process (its
  `last_restart.mono`) minus that first PASS HEALTH; also the runner's API sample time. Bound 2 P.
- Early restart (independent audit F-02): FT-F12 then restarts the NEW process again while it is
  young, right after the gateway first saw it. The gateway's next poll can find a process OLDER than
  the young one it last saw, so "uptime decreased" cannot reveal the restart; the gateway must still
  detect it (runner/classify.restart_between), never report STALE_DATA for the new process's
  restarted seq, and report it healthy <= 2 P after its first PASS HEALTH. The uptime rise is
  recorded: > 0 means the pre-remediation rule would have missed that restart.
"""
import hashlib
import json
import time
from pathlib import Path

import pytest

from runner import catalog, lab as L
from runner.cases import Attempt
from runner.classify import HealthSample, classify, restart_between
from runner.client import Connection, single
from scripts.lib import inventory

pytestmark = [pytest.mark.live]
REPO = Path(__file__).resolve().parents[2]
INV = inventory.load(REPO / "inventory.yaml")
DEVICES = [d["device_id"] for d in INV["devices"]]
REQ08_HEALTHY_MS = 10_000


def interval(lab) -> float:
    return lab.gw.get("/inventory")[1]["gateway"]["poll_interval_s"]


def wait_all_healthy(case, lab, P: float) -> list[dict]:
    ok, samples = lab.gw.sample(DEVICES, lambda recs: all(r["state"] == "healthy" for r in recs.values()),
                                timeout=3 * P + 1)
    if not ok:
        raise L.LabError(f"gateway did not report every device healthy before the fault: {samples[-1]}", infra=True)
    return samples


def first_transition(rec: dict, to: str, after_mono: float) -> dict | None:
    return next((t for t in rec["transitions"] if t["to"] == to and t["mono"] >= after_mono), None)


def save_samples(case, name: str, samples: list[dict]) -> None:
    case.file(name, "\n".join(json.dumps(s, sort_keys=True) for s in samples) + "\n", "gateway-samples")


# ---------------------------------------------------------------- control (no fault)

@pytest.mark.commissioning
@pytest.mark.case("C-GATEWAY")
@pytest.mark.parametrize("device", DEVICES)
def test_gateway_reports_device_healthy(case, lab, device):
    gw, d = lab.gw, case.device
    code, inv = gw.get("/inventory")
    P = inv["gateway"]["poll_interval_s"]
    r1 = gw.device(device)
    time.sleep(P + 0.3)
    r2 = gw.device(device)
    dt = r2["last_poll"]["started_mono"] - r1["last_poll"]["started_mono"]
    k = max(1, round(dt / P))
    want_sha = hashlib.sha256((REPO / "inventory.yaml").read_bytes()).hexdigest()
    bad_code, bad_body, _ = gw.request("GET", "/devices/no-such-device")
    post_code, _, post_hdr = gw.request("POST", "/inventory")
    case.measure("gateway_last_seen_age_ms", r2["last_seen_age_s"] * 1000, bound=2 * P * 1000)
    case.measure("gateway_poll_period_ms", dt / k * 1000, detail=f"{dt:.4f} s over {k} slot(s), P={P}")
    case.measure("gateway_poll_duration_ms", r2["last_poll"]["duration_ms"], bound=4000)
    case.file("gateway-device.json", json.dumps({"before": r1, "after": r2}, indent=1), "gateway")
    preds = {
        "api_inventory_200_lists_inventory": code == 200 and sorted(x["device_id"] for x in inv["devices"]) == DEVICES,
        "gateway_inventory_is_repo_inventory": inv["gateway"]["inventory_sha256"] == want_sha,
        "poll_interval_is_2s": P == 2.0,
        "state_healthy_reachable": r2["state"] == "healthy" and r2["reachable"] is True,
        "identity_matches_inventory": r2["identity_ok"] is True and r2["identity"] is not None
        and (r2["identity"]["device_id"], r2["identity"]["serial"]) == (d["device_id"], d["serial"]),
        "firmware_matches_inventory": r2["firmware"]["ok"] is True and r2["firmware"]["reported"] == d["fw_version"],
        "health_ok": r2["health"] is not None and r2["health"]["status"] == "ok" and r2["health"]["sensor_ok"] is True,
        "read_fresh": r2["freshness"] is not None and r2["freshness"]["fresh"] is True,
        "last_seen_within_2P": r2["last_seen_age_s"] is not None and r2["last_seen_age_s"] <= 2 * P,
        "polls_advancing": r2["polls"] > r1["polls"],
        "poll_period_is_P": abs(dt / k - P) < 0.05,
        "no_consecutive_failures": r2["consecutive_failures"] == 0,
        "api_unknown_device_404": bad_code == 404 and bad_body.get("error") == "unknown_device",
        "api_bad_id_400": gw.get("/devices/BAD!id")[0] == 400,
        "api_post_405_with_allow": post_code == 405 and post_hdr.get("Allow") == "GET, HEAD",
    }
    case.finish_observed(r2["last_category"], "PASS", predicates=preds,
                         what=f"gateway {device}: state={r2['state']} polls={r2['polls']}")


# ---------------------------------------------------------------- REQ-09: unreachable within 3 P

def gateway_unreachable(case, lab, inject, fault_id: str, affected: list[str], unaffected: list[str]):
    gw = lab.gw
    P = interval(lab)
    expected = catalog.FAULTS_BY_ID[fault_id].expected_category
    pre = wait_all_healthy(case, lab, P)
    case.mark("gateway_all_healthy")
    inject(fault_id)
    t_cmd, t_applied = case.t_apply_start, case.t_applied
    ok, s1 = gw.sample(DEVICES, lambda recs: all(recs[x]["state"] == "unreachable" for x in affected),
                       timeout=3 * P + 2)
    t_seen = case.mark("gateway_unreachable_seen") if ok else None
    # steady state: a poll that started after the fault was confirmed applied
    ok_s, s1b = gw.sample(DEVICES, lambda recs: all(recs[x]["last_poll"]["started_mono"] > t_applied
                                                     for x in affected), timeout=P + 2)
    s1 += s1b
    recs = {x: gw.device(x) for x in DEVICES}
    preds, det, cats, trans = {}, {}, {}, {}
    for x in affected:
        tr = first_transition(recs[x], "unreachable", t_cmd)
        det[x] = None if tr is None else (tr["mono"] - t_cmd) * 1000
        trans[x] = tr["category"] if tr else None
        steady = recs[x]["last_poll"]["started_mono"] > t_applied
        cats[x] = recs[x]["last_category"] if steady else None
        case.measure(f"gateway_detection_ms.{x}", det[x], bound=3 * P * 1000,
                     detail="gateway transition to unreachable (its poll completion) - fault command sent")
        case.measure(f"gateway_detection_from_applied_ms.{x}", None if tr is None else (tr["mono"] - t_applied) * 1000,
                     detail="same transition - fault confirmed applied (reference per REQ-09 wording)")
        preds[f"{x}_unreachable_within_3P"] = det[x] is not None and det[x] <= 3 * P * 1000
        preds[f"{x}_category_{expected}"] = cats[x] == expected
    case.measure("fault_apply_call_ms", (t_applied - t_cmd) * 1000, detail="ctl: fault command sent -> confirmed")
    api_ms = None if t_seen is None else (t_seen - t_cmd) * 1000
    case.measure("gateway_unreachable_api_observed_ms", api_ms, bound=3 * P * 1000,
                 detail="runner's GET /devices sample first showing every affected device unreachable - command sent")
    preds["api_observed_within_3P"] = api_ms is not None and api_ms <= 3 * P * 1000
    for x in unaffected:
        moved = [t for t in recs[x]["transitions"] if t["mono"] >= t_cmd]
        preds[f"{x}_stayed_healthy"] = recs[x]["state"] == "healthy" and not moved \
            and all(s["records"][x]["state"] == "healthy" for s in s1)
    case.file("gateway-during-fault.json", json.dumps(recs, indent=1), "gateway")
    # recovery: remove the fault now, then the gateway must see the device healthy again
    inject.revert(fault_id)
    t_rev_cmd, t_rev_done = case.marks[f"revert_start:{fault_id}"], case.marks[f"reverted:{fault_id}"]
    ok2, s2 = gw.sample(affected, lambda recs: all(r["state"] == "healthy" for r in recs.values()), timeout=2 * P + 2)
    recs2 = {x: gw.device(x) for x in affected}
    for x in affected:
        tr = first_transition(recs2[x], "healthy", t_rev_cmd)
        rec = None if tr is None else (tr["mono"] - t_rev_cmd) * 1000
        case.measure(f"gateway_recovery_after_revert_ms.{x}", rec, bound=2 * P * 1000,
                     detail="gateway transition back to healthy - revert command sent")
        case.measure(f"gateway_recovery_from_revert_returned_ms.{x}",
                     None if tr is None else (tr["mono"] - t_rev_done) * 1000,
                     detail="same transition - revert confirmed (negative: recovered while the revert call ran)")
        preds[f"{x}_recovered_within_2P_of_revert"] = rec is not None and rec <= 2 * P * 1000
    save_samples(case, "gateway-samples.jsonl", [dict(s, phase="pre") for s in pre[-3:]] +
                 [dict(s, phase="fault") for s in s1] + [dict(s, phase="recovery") for s in s2])
    primary = affected[0]
    case.finish_observed(cats[primary], expected, predicates=preds, detection_ms=det[primary],
                         what="gateway " + ",".join(f"{x}:{cats[x]} (transition poll {trans[x]} "
                                                    f"@{det[x] and round(det[x])}ms)" for x in affected))


@pytest.mark.fault
@pytest.mark.case("GW-F1-UNREACHABLE")
def test_gateway_detects_stopped_device(case, lab, inject):
    gateway_unreachable(case, lab, inject, "F1", ["dev-a"], ["dev-b"])


@pytest.mark.fault
@pytest.mark.case("GW-F5-UNREACHABLE")
def test_gateway_detects_route_loss(case, lab, inject):
    gateway_unreachable(case, lab, inject, "F5", ["dev-a", "dev-b"], [])     # both share the deleted route


@pytest.mark.fault
@pytest.mark.case("GW-F8-UNREACHABLE")
def test_gateway_detects_silent_drop(case, lab, inject):
    gateway_unreachable(case, lab, inject, "F8", ["dev-a"], ["dev-b"])


# ---------------------------------------------------------------- REQ-08: restart during polls

def first_pass_health(d: dict, a: Attempt, t_from: float):
    """Fresh HEALTH probes every 100 ms until the first PASS with status ok / sensor ok, bounded by REQ-08's 10 s
    from t_from. Every probe is kept on the attempt. -> (time of that PASS or None, first probe's category, index)."""
    first = None
    while time.monotonic() - t_from < REQ08_HEALTHY_MS / 1000:
        o = single(d["hostname"], d["port"], "HEALTH")
        c = classify(o)
        t = time.monotonic()
        a.exchanges.append((o, c))
        first = first or c.category
        if c.category == "PASS" and c.payload["status"] == "ok" and c.payload["sensor_ok"] is True:
            return t, first, len(a.exchanges) - 1
        time.sleep(0.1)
    return None, first, None


def timed_exchange(conn: Connection, a: Attempt, cmd: str) -> tuple[dict | None, tuple[float, float]]:
    """One exchange on an open connection, kept on the attempt -> (payload or None, monotonic bounds)."""
    x0 = time.monotonic()
    o = conn.exchange(cmd)
    x1 = time.monotonic()
    c = classify(o)
    a.exchanges.append((o, c))
    return (c.payload if c.category in ("PASS", "PASS_SLOW") else None), (x0, x1)


@pytest.mark.fault
@pytest.mark.case("FT-F12-RESTART")
def test_f12_restart_during_polls(case, lab, inject):
    gw, d = lab.gw, case.device
    dev = d["device_id"]
    P = interval(lab)
    wait_all_healthy(case, lab, P)
    r0 = gw.device(dev)["restarts_detected"]
    a = Attempt(attempt_no=1, started_wall=time.time())
    case.inflight_attempt = a   # retain the real partial probe sequence if the overall deadline expires
    t_att = case.mark("first_attempt")
    # 1. old process: HEALTH + READ on a connection that is held open across the restart
    held = Connection(d["hostname"], d["port"])
    case.connections.append(held)
    failed = held.open("HEALTH")
    if failed is not None:
        a.exchanges.append((failed, classify(failed)))
        a.decisive = 0
        case.finish([a], "PASS", extra_predicates={"pre_restart_connection": False})
    pre_health, pre_bounds = timed_exchange(held, a, "HEALTH")
    pre_read, _ = timed_exchange(held, a, "READ")
    # 2. restart (Type=notify: returns after the new process bound)
    r = inject("F12")
    t_cmd, t_ret = case.t_apply_start, case.t_applied
    # 3. the held connection was closed by the old process's graceful stop
    o = held.exchange("READ")
    a.exchanges.append((o, classify(o)))
    held_cat = a.exchanges[-1][1]
    held.close()
    # 4. fresh HEALTH probes every 100 ms until the first PASS (bounded by the 10 s requirement)
    probes0 = len(a.exchanges)
    t_pass, first_probe, a.decisive = first_pass_health(d, a, t_ret)
    if a.decisive is None:
        a.decisive = len(a.exchanges) - 1
    probes = len(a.exchanges) - probes0
    if t_pass is not None:
        case.mark("first_pass_health")
    # 5. new process: same identity, seq restarted, and a NEW process by its uptime (restart_between, not "lower")
    o = single(d["hostname"], d["port"], "IDENTIFY")
    a.exchanges.append((o, classify(o, expect=lab.identity(case.device_id))))
    ident = a.exchanges[-1][1]
    conn = Connection(d["hostname"], d["port"])
    case.connections.append(conn)
    post_read = post_health = post_bounds = None
    if conn.open("READ") is None:
        post_read, _ = timed_exchange(conn, a, "READ")
        post_health, post_bounds = timed_exchange(conn, a, "HEALTH")
    conn.close()
    new_process = None
    if pre_health is not None and post_health is not None:
        new_process = restart_between(HealthSample(pre_health["uptime_s"], *pre_bounds),
                                      HealthSample(post_health["uptime_s"], *post_bounds))
    # 6. the gateway must have polled the NEW process and report it healthy
    ok, samples = gw.sample([dev], lambda recs: recs[dev]["restarts_detected"] > r0
                            and recs[dev]["state"] == "healthy", timeout=2 * P + 2)
    g = gw.device(dev)
    save_samples(case, "gateway-samples.jsonl", samples)
    case.file("gateway-after-restart.json", json.dumps(g, indent=1), "gateway")
    det = None if t_pass is None else (t_pass - t_ret) * 1000
    det_cmd = None if t_pass is None else (t_pass - t_cmd) * 1000
    gw_ms = None if (t_pass is None or not ok or not g["last_restart"]) else (g["last_restart"]["mono"] - t_pass) * 1000
    api_ms = None if (t_pass is None or not ok) else (samples[-1]["t_mono"] - t_pass) * 1000
    case.measure("device_healthy_after_restart_ms", det, bound=REQ08_HEALTHY_MS,
                 detail="first PASS HEALTH - `apply restart` returned on ctl (REQ-08 t_restart)")
    case.measure("device_healthy_after_restart_cmd_ms", det_cmd, bound=REQ08_HEALTHY_MS,
                 detail="first PASS HEALTH - restart command sent (upper bound incl. the restart itself)")
    case.measure("restart_call_ms", (t_ret - t_cmd) * 1000, detail="ctl: command sent -> returned (SSH + restart)")
    case.measure("systemctl_restart_ms", r.get("restart_ms"), clock="witness-field monotonic",
                 detail=f"pid {r.get('old_pid')} -> {r.get('new_pid')}; listening at return={r.get('listening_at_return')}")
    case.measure("health_probes_until_pass", probes, unit="count", detail=f"first probe {first_probe}")
    case.measure("gateway_recovery_ms", gw_ms, bound=2 * P * 1000,
                 detail="gateway poll that first saw the new process (last_restart.mono) - first PASS HEALTH; "
                        "negative = the gateway saw it first")
    case.measure("gateway_recovery_api_observed_ms", api_ms, bound=2 * P * 1000,
                 detail="runner's GET /devices sample showing it - first PASS HEALTH")
    preds = {
        "first_pass_health_within_10s": det is not None and det <= REQ08_HEALTHY_MS and det_cmd <= REQ08_HEALTHY_MS,
        "gateway_recovery_within_2P": gw_ms is not None and gw_ms <= 2 * P * 1000 and api_ms <= 2 * P * 1000,
        "gateway_detected_restart": ok and g["restarts_detected"] > r0,
        "new_pid": r.get("new_pid") not in (None, 0, r.get("old_pid")),
        "held_connection_reset_by_old_process": held_cat.category == "CONN_RESET",
        "identity_unchanged_after_restart": ident.category == "PASS",
        "seq_restarted": post_read is not None and pre_read is not None and post_read["seq"] < pre_read["seq"],
        "new_process_by_uptime": new_process is not None and new_process[0],
    }
    # 7. early restart (independent audit F-02): restart the young new process right after the gateway first saw it
    g1 = gw.device(dev)
    r1 = g1["restarts_detected"]
    seen = f"uptime {(g1['health'] or {}).get('uptime_s')} s, seq {(g1['freshness'] or {}).get('seq')}"
    r2 = inject("F12")
    t_cmd2, t_ret2 = case.t_apply_start, case.t_applied
    t_pass2, first2, _ = first_pass_health(d, a, t_ret2)
    if t_pass2 is not None:
        case.mark("first_pass_health_2")
    ok2, samples2 = gw.sample([dev], lambda recs: recs[dev]["restarts_detected"] > r1
                              and recs[dev]["state"] == "healthy", timeout=2 * P + 2)
    g2 = gw.device(dev)
    lr2 = g2["last_restart"] if g2["restarts_detected"] > r1 else None
    stale = [t for t in g2["transitions"] if t["mono"] >= t_cmd2 and t["to"] == "stale"]
    det2 = None if t_pass2 is None else (t_pass2 - t_ret2) * 1000
    gw2 = None if (t_pass2 is None or lr2 is None) else (lr2["mono"] - t_pass2) * 1000
    api2 = None if (t_pass2 is None or not ok2) else (samples2[-1]["t_mono"] - t_pass2) * 1000
    rise = None if lr2 is None else lr2["uptime_after_s"] - lr2["uptime_before_s"]
    save_samples(case, "gateway-samples-early-restart.jsonl", samples2)
    case.file("gateway-after-early-restart.json", json.dumps(g2, indent=1), "gateway")
    case.measure("early_restart_device_healthy_ms", det2, bound=REQ08_HEALTHY_MS,
                 detail="second (early) restart: first PASS HEALTH - `apply restart` returned on ctl")
    case.measure("early_restart_gateway_recovery_ms", gw2, bound=2 * P * 1000,
                 detail="gateway poll that detected the second restart (last_restart.mono) - its first PASS HEALTH")
    case.measure("early_restart_gateway_recovery_api_observed_ms", api2, bound=2 * P * 1000,
                 detail="runner's GET /devices sample showing it healthy and the restart counted - first PASS HEALTH")
    case.measure("early_restart_uptime_rise_s", rise, unit="s", clock="device uptime_s (gateway samples)",
                 detail=f"gateway's uptime after - before the second restart; rule {lr2 and lr2['rule']}; > 0 = the "
                        f"pre-remediation 'uptime decreased' rule could not see it. Gateway last saw the young "
                        f"process at {seen}; first probe after the restart {first2}")
    preds.update({
        "early_restart_new_pid": r2.get("old_pid") == r.get("new_pid") and r2.get("new_pid") not in (None, 0, r.get("new_pid")),
        "early_restart_healthy_within_10s": det2 is not None and det2 <= REQ08_HEALTHY_MS,
        "early_restart_gateway_detected": lr2 is not None,
        "early_restart_gateway_recovery_within_2P": gw2 is not None and gw2 <= 2 * P * 1000 and api2 is not None
        and api2 <= 2 * P * 1000,
        "early_restart_never_stale": not stale,
    })
    a.duration_ms = (time.monotonic() - t_att) * 1000
    case.finish([a], "PASS", detection_ms=det, extra_predicates=preds)
