"""Acceptance contract (docs/acceptance-contract.md): evidence obligations taken from sources the verified rows cannot
change, and their verification. One implementation, used alike by acceptance (runner/analysis.py A17, A20, A22-A24),
commissioning (runner/db.commissioning_gaps) and the report.

Final independent verification FV-01/FV-02 (docs/independent-final-verification.md): the required capture flows of a
result were derived from its surviving exchange rows, the required files from the evidence index and the required
devices from the devices table, so deleting evidence also deleted the obligation. Here the obligations come from:
- the catalog and CONTRACTS below: per case the observation kind, attempts allowed, the command grammar of one
  attempt, the dialled target, the captures, the evidence files, fault applications and measurements the live case
  records (tests/live);
- the inventory: devices, addresses, ports, identities, VMs;
- the run plan (schema v5): the declared selection, written before the run's first case (run_plan rows and the
  indexed session/plan.json);
- the evidence directories on disk (receipts): every executed case created run-N/<case>__<device|run>/, the only
  completeness record of runs that predate the plan.
Every violation names its contract invariant, e.g. "run7 FT-F3-WRONG-PORT/dev-a: [I5.1] attempt 1 has no exchange".
"""
from __future__ import annotations

import hashlib
import itertools
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from runner import evidence as EV, lab as L
from runner.catalog import CASES_BY_ID, COMMISSIONING_REQUIRED, FAULT_DEVICE, FAULTS_BY_ID, UNUSED_ADDR, WRONG_PORT
from runner.classify import FrameError, combine, parse_frame

PASSING = ("PASS", "PASS_SLOW")
LETTER = {"IDENTIFY": "I", "HEALTH": "H", "READ": "R"}
DEADLINE = "case_deadline_exhausted"
F12 = "FT-F12-RESTART"
F12_GRAMMAR = re.compile(r"H(?:RRH+I(?:RH)?H+)?")   # held HEALTH READ, READ across the restart, probes, IDENTIFY,
#                                                     new-process READ HEALTH (if it connected), early-restart probes
SERIES = {"C-READ-CLOCK": "R" * 10, "C-READ-SERIES": "H" + "R" * 10 + "H", "FT-F11-CLOSE-FIN": "R" * 10,
          "FT-F11-CLOSE-RST": "R" * 10, "FT-F13-SKEW": "R" * 3, "FT-F13-REPEAT-SEQ": "R" * 3}
GATEWAY_OBSERVED = {"C-GATEWAY", "GW-F1-UNREACHABLE", "GW-F5-UNREACHABLE", "GW-F8-UNREACHABLE"}
RECORD = {"C-ENVIRONMENT"}
# measurements a passing case records (tests/live: case.measure); {dev} = each device the gateway case observes
_GW = ("gateway_detection_ms.{dev}", "gateway_detection_from_applied_ms.{dev}", "gateway_recovery_after_revert_ms.{dev}",
       "gateway_recovery_from_revert_returned_ms.{dev}")
MEASUREMENTS = {
    "C-GATEWAY": ("gateway_last_seen_age_ms", "gateway_poll_period_ms", "gateway_poll_duration_ms"),
    "GW-F1-UNREACHABLE": _GW + ("fault_apply_call_ms", "gateway_unreachable_api_observed_ms"),
    "GW-F5-UNREACHABLE": _GW + ("fault_apply_call_ms", "gateway_unreachable_api_observed_ms"),
    "GW-F8-UNREACHABLE": _GW + ("fault_apply_call_ms", "gateway_unreachable_api_observed_ms"),
    F12: ("device_healthy_after_restart_ms", "device_healthy_after_restart_cmd_ms", "restart_call_ms",
          "systemctl_restart_ms", "health_probes_until_pass", "gateway_recovery_ms", "gateway_recovery_api_observed_ms",
          "early_restart_device_healthy_ms", "early_restart_gateway_recovery_ms",
          "early_restart_gateway_recovery_api_observed_ms", "early_restart_uptime_rise_s"),
    "FT-F13-SKEW": ("read_skew_s",),
    "FT-F4-WRONG-ADDR": ("field_Ip.InAddrErrors_delta", "field_Icmp.OutDestUnreachs_delta", "field_Tcp.OutRsts_delta"),
    "FT-F5-NO-ROUTE": ("connect_ms",),
    "FT-F7-NAME-MISSING": ("resolve_ms",),
    "FT-F7-NAME-SWAP": ("gateway_wrong_identity_ms",),
    "FT-F8-DROP": ("field_Tcp.OutRsts_delta", "field_Icmp.OutDestUnreachs_delta"),
}
# gateway records (GET /devices JSON) and sample logs a passing case saves (its predicates rest on them)
GATEWAY_FILES = {"C-GATEWAY": 1, "GW-F1-UNREACHABLE": 1, "GW-F5-UNREACHABLE": 1, "GW-F8-UNREACHABLE": 1, F12: 2,
                 "FT-F3-WRONG-PORT": 1, "FT-F7-NAME-SWAP": 1, "FT-F7-NAME-MISSING": 1}
SAMPLE_FILES = {"GW-F1-UNREACHABLE": 1, "GW-F5-UNREACHABLE": 1, "GW-F8-UNREACHABLE": 1, F12: 2}
SESSION_FILES = {"preflight": 2, "environment": 1, "postflight": 2, "command-log": 1}
# files the live Injector writes per application of a fault of each kind (tests/live/conftest.py Injector.apply)
FAULT_KIND_FILES = {"inventory-addr": ("counters", "hosts", "inventory"), "nft": ("counters",),
                    "hosts-swap": ("hosts",), "hosts-remove": ("hosts",), "inventory-port": ("inventory",)}
# the observation a passing fault case predicts exchange by exchange (runner/catalog.py descriptions, tests/live)
PASS_SHAPE = {"FT-F11-CLOSE-FIN": ["PASS", "PASS", "CONN_RESET"], "FT-F11-CLOSE-RST": ["PASS", "PASS", "CONN_RESET"],
              "FT-F13-REPEAT-SEQ": ["PASS", "STALE_DATA"], "FT-F13-SKEW": ["STALE_DATA"]}
# measurements a pass records OUTSIDE their requirement bound by design: F13 skew is 30 s beyond REQ-04's 2 s window
OUTSIDE_BOUND_ON_PASS = {("FT-F13-SKEW", "read_skew_s")}
# the case's own decision predicates (results.predicates, schema v5), recorded beside the final attempt's
# (derived_predicates) with every verdict: tests/live extra_predicates of case.finish and the predicates of
# finish_observed; C-ENVIRONMENT records every REQ-10 key (case_predicates). {dev}: each device a gateway case observes,
# {other}: each device it must leave healthy, {category}: the case's prediction.
_GW_PREDICATES = ("{dev}_unreachable_within_3P", "{dev}_category_{category}", "{dev}_recovered_within_2P_of_revert",
                  "{other}_stayed_healthy", "api_observed_within_3P")
CASE_PREDICATES = {
    "C-GATEWAY": ("api_inventory_200_lists_inventory", "gateway_inventory_is_repo_inventory", "poll_interval_is_2s",
                  "state_healthy_reachable", "identity_matches_inventory", "firmware_matches_inventory", "health_ok",
                  "read_fresh", "last_seen_within_2P", "polls_advancing", "poll_period_is_P",
                  "no_consecutive_failures", "api_unknown_device_404", "api_bad_id_400", "api_post_405_with_allow"),
    "GW-F1-UNREACHABLE": _GW_PREDICATES, "GW-F5-UNREACHABLE": _GW_PREDICATES, "GW-F8-UNREACHABLE": _GW_PREDICATES,
    F12: ("first_pass_health_within_10s", "gateway_recovery_within_2P", "gateway_detected_restart", "new_pid",
          "held_connection_reset_by_old_process", "identity_unchanged_after_restart", "seq_restarted",
          "new_process_by_uptime", "early_restart_new_pid", "early_restart_healthy_within_10s",
          "early_restart_gateway_detected", "early_restart_gateway_recovery_within_2P", "early_restart_never_stale"),
    "FT-F2-HUNG": ("returned_within_read_timeout_plus_0.5s", "within_case_deadline"),
    "FT-F6-DELAY-300": ("latency_recorded_in_(500,2000]",),
    "FT-F6-DELAY-3000": ("connect_returned_within_timeout_plus_0.5s",),
    "FT-F6-DELAY-3000-DATA": ("returned_within_read_timeout_plus_0.5s",),
    "FT-F7-NAME-SWAP": ("detail_names_serial_and_device_id", "dialled_address_was_other_device",
                        "dev_a_not_commissioned", "gateway_flags_wrong_identity_within_3P"),
    "FT-F7-NAME-MISSING": ("no_address_resolved", "failed_before_resolve_timeout",
                           "gateway_sees_resolve_fail_within_3P"),
    "FT-F10-MALFORMED": ("detail_bad_json", "within_case_deadline"),
    "FT-F10-TRUNCATED": ("detail_truncated", "within_case_deadline"),
    "FT-F10-WRONG-ID": ("detail_wrong_id", "within_case_deadline"),
    "FT-F3-WRONG-PORT": ("dialled_port_5021", "device_answers_on_inventoried_port", "gateway_once_agrees_CONN_REFUSED"),
    "FT-F4-WRONG-ADDR": ("dialled_unused_address", "connect_returned_within_timeout_plus_0.5s"),
    "FT-F5-NO-ROUTE": ("failed_before_connect_timeout", "errno_ENETUNREACH"),
    "FT-F8-DROP": ("connect_returned_within_timeout_plus_0.5s",),
    "FT-F9-REJECT": ("device_process_still_running",),
    "FT-F9-REJECT-DATA": ("handshake_completed", "zero_response_bytes"),
    "FT-F11-CLOSE-FIN": ("two_reads_then_reset", "read_end_eof", "detail_eof_before_response", "zero_response_bytes",
                         "series_incomplete_not_pass"),
    "FT-F11-CLOSE-RST": ("two_reads_then_reset", "read_end_reset", "detail_reset_before_response",
                         "zero_response_bytes", "series_incomplete_not_pass"),
    "FT-F13-SKEW": ("first_read_stale_by_+30s",),
    "FT-F13-REPEAT-SEQ": ("first_read_pass_second_stale", "detail_seq_not_increasing"),
}
# what a case that stopped before its observation was complete records instead (always a fail): FT-F12 whose
# connection to the old process failed before the restart
PARTIAL_PREDICATES = {F12: (("pre_restart_connection",),)}


@dataclass(frozen=True)
class CaseContract:
    case_id: str
    observation: str               # runner | gateway | record
    max_attempts: int              # runner: commissioning 2 (one retry), fault 1; gateway/record 0
    ops: str | None                # commands of one complete attempt (I/H/R); None = F12 grammar
    series: bool                   # an attempt may end early at a non-pass or deadline-cut exchange
    captures: tuple[str, ...]      # ctl always; field for fault cases (tests/live/conftest.py `case`)
    applications: int              # fault applications per case (F12 restarts twice)
    measurements: tuple[str, ...]
    on_pass_files: dict = field(default_factory=dict)


def contract(case_id: str) -> CaseContract:
    c = CASES_BY_ID[case_id]
    fault = c.kind == "fault"
    obs = "gateway" if case_id in GATEWAY_OBSERVED else "record" if case_id in RECORD else "runner"
    apps = 2 if c.fault_id == "F12" else 1 if fault else 0
    files = {k: n for k, n in (("gateway", GATEWAY_FILES.get(case_id, 0)), ("gateway-samples",
                                                                            SAMPLE_FILES.get(case_id, 0))) if n}
    if apps:
        files.update({"fault-apply": apps, "fault-revert": apps, "snapshot": 2 * apps})
        for kind in FAULT_KIND_FILES.get(FAULTS_BY_ID[c.fault_id].kind, ()):
            files[kind] = files.get(kind, 0) + apps
    ops = None if case_id == F12 else SERIES.get(case_id) or ("H" if case_id == "C-HEALTH" else "I")
    return CaseContract(case_id, obs, 0 if obs != "runner" else (1 if fault else 2), ops if obs == "runner" else "",
                        case_id in SERIES, ("ctl", "field") if fault else ("ctl",), apps,
                        MEASUREMENTS.get(case_id, ()), files)


def expected_category(case_id: str) -> str | None:
    c = CASES_BY_ID[case_id]
    if c.fault_id:
        return FAULTS_BY_ID[c.fault_id].expected_category
    return None if case_id in RECORD else "PASS"


def case_predicates(case_id: str, device_id: str | None, inv: dict) -> tuple[frozenset, tuple[frozenset, ...]]:
    """(the names of the case's own decision predicates, the partial sets a fail may record instead), from the case
    contract and the inventory, never from the row being verified: a name that is missing from a decision is a
    missing observation, not a check the case never made (independent contract verification IC-02)."""
    if case_id in RECORD:
        return frozenset(EV.required_env_keys(inv)), ()
    devs = [d["device_id"] for d in inv["devices"]]
    seen = devs if case_id == "GW-F5-UNREACHABLE" else [device_id]
    fill = {"dev": seen, "other": [d for d in devs if d not in seen], "category": [expected_category(case_id)]}

    def render(names) -> frozenset:
        out = set()
        for n in names:
            keys = [k for k in fill if "{" + k + "}" in n]
            out.update(n.format(**dict(zip(keys, vals))) for vals in itertools.product(*(fill[k] for k in keys)))
        return frozenset(out)
    return render(CASE_PREDICATES.get(case_id, ())), tuple(render(p) for p in PARTIAL_PREDICATES.get(case_id, ()))


def target(case_id: str, device_id: str, inv: dict) -> tuple[str, str | None, int]:
    """(hostname, address, port) a case instance dials: the inventory row, as its fault makes the runner dial it
    (tests/live/conftest.py Injector): F3 the wrong port, F4 the unused address, F7 the other device's address, F7
    name-missing no address at all."""
    devs = {d["device_id"]: d for d in inv["devices"]}
    d = devs[device_id]
    host, addr, port = d["hostname"], d["address"], int(d["port"])
    fid = CASES_BY_ID[case_id].fault_id
    if fid == "F3":
        port = WRONG_PORT
    elif fid == "F4":
        addr = UNUSED_ADDR
    elif fid == "F7":
        addr = next(x["address"] for x in inv["devices"] if x["device_id"] != device_id)
    elif fid == "F7-missing":
        addr = None
    return host, addr, port


def required_devices(conn, inv: dict) -> list[str]:
    """The devices every requirement is checked for: the inventory's, never the devices table (FV-02)."""
    return [d["device_id"] for d in inv["devices"]]


def required_commissioning(conn, inv: dict) -> list[tuple[str, str | None]]:
    devs = required_devices(conn, inv)
    return [(case_id, dev) for case_id, per_dev in COMMISSIONING_REQUIRED for dev in (devs if per_dev else [None])]


def instance_problem(case_id: str, device_id: str | None, inv: dict) -> str | None:
    """Why (case, device) is not a catalog instance (I1.3): unknown case, per-device <-> device, inventory device,
    fault cases on FAULT_DEVICE."""
    c = CASES_BY_ID.get(case_id)
    if c is None:
        return "not a catalogued case"
    if c.per_device != (device_id is not None):
        return "per-device case without a device" if c.per_device else "run-level case with a device"
    if device_id is not None and device_id not in {d["device_id"] for d in inv["devices"]}:
        return f"device {device_id} is not in the inventory"
    if c.kind == "fault" and device_id != FAULT_DEVICE:
        return f"fault cases target {FAULT_DEVICE}"
    return None


# ---------------------------------------------------------------- store access (any schema version, read-only)

def has(conn, table: str, column: str | None = None) -> bool:
    if column is None:
        return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone() \
            is not None
    return any(r[1] == column for r in conn.execute(f"PRAGMA table_info({table})"))


def migration_time(conn, version: int) -> str | None:
    """When this store applied schema `version` (runs started later are under that version's obligations): read from
    the migration record, never inferred from which rows happen to exist."""
    if not has(conn, "schema_migrations"):
        return None
    r = conn.execute("SELECT applied_at FROM schema_migrations WHERE version = ?", (version,)).fetchone()
    return r[0] if r else None


# schema features and the migration that introduced them (runner/db.py MIGRATIONS)
_FEATURES = ((2, "measurements", None), (3, "mutants", None), (4, "capture_flows", None), (4, "attempts", "outcome"),
             (5, "run_plan", None))


def schema_record_violations(conn) -> list[str]:
    """I1.1: the migration record is the authority for when each obligation starts (migration_time), so it must
    agree with the schema and with the rows it governs: every present feature's version recorded, versions applied in
    order, and no run holding records of a version (plan rows, capture-flow records, attempt outcomes) started before
    that version was applied. Otherwise moving or deleting a migration row would switch obligations off."""
    if not has(conn, "schema_migrations"):
        return ["[I1.1] no schema_migrations table: obligation start times unknown"]
    applied = {v: t for v, t in conn.execute("SELECT version, applied_at FROM schema_migrations")}
    out = [f"[I1.1] schema has {t}{'.' + c if c else ''} but migration {v} is not recorded"
           for v, t, c in _FEATURES if has(conn, t, c) and v not in applied]
    if applied and sorted(applied) != list(range(1, max(applied) + 1)):
        out.append(f"[I1.1] migrations recorded {sorted(applied)}, not 1..{max(applied)}")
    times = [applied[v] for v in sorted(applied)]
    if times != sorted(times):
        out.append(f"[I1.1] migrations applied out of order: {[(v, applied[v]) for v in sorted(applied)]}")
    plan_files = conn.execute("SELECT min(ru.started_at), count(*) FROM evidence e JOIN runs ru USING (run_id) WHERE "
                              "e.kind = 'plan'").fetchone()
    if plan_files[1]:
        if 5 not in applied or not has(conn, "run_plan"):
            out.append("[I1.1] run plan files are indexed but migration 5 / the run_plan table is missing")
        elif plan_files[0] < applied[5]:
            out.append(f"[I1.1] run plan files exist in a run started {plan_files[0]}, before migration 5 was applied "
                       f"({applied[5]})")
    governed = []
    if has(conn, "run_plan"):
        governed.append((5, "run plan rows", "SELECT min(ru.started_at) FROM runs ru WHERE ru.run_id IN "
                                             "(SELECT run_id FROM run_plan)"))
    if has(conn, "capture_flows"):
        governed.append((4, "capture-flow records", "SELECT min(ru.started_at) FROM capture_flows f JOIN results r "
                                                    "USING (result_id) JOIN runs ru USING (run_id)"))
    if has(conn, "attempts", "outcome"):
        governed.append((4, "attempt outcomes", "SELECT min(ru.started_at) FROM attempts a JOIN results r "
                                                "USING (result_id) JOIN runs ru USING (run_id) WHERE a.outcome "
                                                "IS NOT NULL"))
    for v, what, q in governed:
        first = conn.execute(q).fetchone()[0]
        if first is not None and v in applied and first < applied[v]:
            out.append(f"[I1.1] {what} exist in a run started {first}, before migration {v} was applied "
                       f"({applied[v]})")
    return out


def _dicts(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _ids(ids) -> str:
    return json.dumps(sorted(int(i) for i in ids))


def load(conn, rids) -> dict[int, dict]:
    """Every result in `rids` with its run, attempts (with exchanges), evidence, flows, checks, fault events and
    measurements, in a few queries."""
    ids = _ids(rids)
    inq = "IN (SELECT value FROM json_each(?))"
    out = {r["result_id"]: dict(r, attempt_rows=[], evidence=[], flow_rows=[], checks=[], events=[], measurements=[])
           for r in _dicts(conn.execute(
               "SELECT r.*, ru.started_at AS run_started, ru.kind AS run_kind FROM results r JOIN runs ru "
               f"USING (run_id) WHERE r.result_id {inq}", (ids,)))}
    v4 = has(conn, "attempts", "outcome")
    atts = {}
    for a in _dicts(conn.execute(
            "SELECT attempt_id, result_id, attempt_no, category, stage, detail, "
            + ("outcome, predicates" if v4 else "NULL AS outcome, NULL AS predicates")
            + f" FROM attempts WHERE result_id {inq} ORDER BY result_id, attempt_no, attempt_id", (ids,))):
        a["exchanges"] = []
        atts[a["attempt_id"]] = a
        out[a["result_id"]]["attempt_rows"].append(a)
    lp = "local_port" if has(conn, "exchanges", "local_port") else "NULL AS local_port"
    for x in _dicts(conn.execute(
            f"SELECT x.attempt_id, x.ord, x.cmd, x.req_id, x.host, x.addr, x.port, {lp}, x.category, x.detail, "
            "x.stage_failed, x.os_error, x.t_send, x.response FROM exchanges x JOIN attempts a USING (attempt_id) "
            f"WHERE a.result_id {inq} ORDER BY x.attempt_id, x.ord", (ids,))):
        atts[x["attempt_id"]]["exchanges"].append(x)
    for table, key in (("evidence", "evidence"), ("checks", "checks"), ("fault_events", "events"),
                       ("measurements", "measurements")) + ((("capture_flows", "flow_rows"),)
                                                           if has(conn, "capture_flows") else ()):
        for row in _dicts(conn.execute(f"SELECT * FROM {table} WHERE result_id {inq}", (ids,))):
            out[row["result_id"]][key].append(row)
    return out


def _label(r: dict) -> str:
    return f"run{r['run_id']} {r['case_id']}/{r['device_id'] or '(run)'}"


def _cut(x: dict) -> bool:
    return x["category"] is None and (x["detail"] or "").startswith(DEADLINE)


def _payload(x: dict) -> dict | None:
    """The recorded response as the protocol frame it must be (the runner stores the received bytes as a BLOB; any
    other stored type is not a recorded response)."""
    data = x["response"]
    if not isinstance(data, (bytes, bytearray)):
        return None
    try:
        obj = parse_frame(bytes(data))
    except FrameError:
        return None
    return obj if obj.get("id") == x["req_id"] else None


def _fail_closed(label: str, e: Exception) -> str:
    """A record the verifier cannot evaluate (wrong stored type, malformed value) is a violation, never a pass."""
    return f"{label}: [I1.1] its records could not be evaluated ({type(e).__name__}: {str(e)[:80]}): rejected"


_FIELDS = {"IDENTIFY": ("device_id", "serial", "fw_version"), "HEALTH": ("status", "uptime_s", "sensor_ok"),
           "READ": ("seq", "ts", "temp_c", "rh_pct")}


# ---------------------------------------------------------------- I4-I7, I10.2/3: one result's evidence chain

def result_violations(conn, rids, inv: dict | None = None) -> dict[int, list[str]]:
    """{result_id: violations} of the case contract, from the records alone (no evidence files needed)."""
    inv = inv or EV.repo_inventory()
    v2, v4, v5 = migration_time(conn, 2), migration_time(conn, 4), migration_time(conn, 5)
    out = {}
    for rid, r in load(conn, rids).items():
        try:
            out[rid] = _result(r, inv, v4, v2, v5)
        except Exception as e:  # noqa: BLE001 - fail closed: an unevaluable record is rejected
            out[rid] = [_fail_closed(_label(r), e)]
    return out


def _result(r: dict, inv: dict, v4_start: str | None, v2_start: str | None = None,
            v5_start: str | None = None) -> list[str]:
    out: list[str] = []

    def bad(inv_id: str, msg: str) -> None:
        out.append(f"{_label(r)}: [{inv_id}] {msg}")

    if r["case_id"] not in CASES_BY_ID:
        bad("I4.4", "not a catalogued case")
        return out
    k = contract(r["case_id"])
    exp = expected_category(r["case_id"])
    decided = r["verdict"] in ("pass", "fail")
    atts = r["attempt_rows"]
    nos = [a["attempt_no"] for a in atts]
    if nos != list(range(1, len(nos) + 1)) or len(nos) != r["attempts"]:
        bad("I4.1", f"results.attempts={r['attempts']} but attempt rows numbered {nos}")
    if k.observation != "runner":
        if atts or r["attempts"]:
            bad("I4.2", f"{k.observation}-observed case recorded runner attempts {nos}")
    elif decided and not 1 <= len(atts) <= k.max_attempts:
        bad("I4.2", f"decided ({r['verdict']}) on {len(atts)} attempt(s); the case allows 1..{k.max_attempts}")
    if r["expected_category"] != exp:
        bad("I4.4", f"expected_category {r['expected_category']} <> catalog {exp}")
    if atts:
        if (r["observed_category"], r["first_attempt_category"]) != (atts[-1]["category"], atts[0]["category"]):
            bad("I4.3", f"observed/first {r['observed_category']}/{r['first_attempt_category']} <> attempts "
                        f"{atts[-1]['category']}/{atts[0]['category']}")
    elif k.observation == "gateway" and r["first_attempt_category"] != r["observed_category"]:
        bad("I4.3", "first_attempt_category differs from the gateway observation")
    elif k.observation == "record" and r["observed_category"] is not None:
        bad("I4.3", f"a record case has no observed category, not {r['observed_category']}")
    legacy = v4_start is None or r["run_started"] < v4_start
    outcomes = [_outcome(a, exp, legacy, bad) for a in atts]
    if r["verdict"] == "pass":
        if r["preflight"] != "green" or r["postflight"] != "green":
            bad("I4.5", f"pass with preflight {r['preflight']} / postflight {r['postflight']}")
        if r["observed_category"] != exp:
            bad("I4.5", f"pass but observed {r['observed_category']} <> expected {exp}")
        if k.observation == "runner" and (len(atts) != 1 or outcomes[0] != "ok"):
            bad("I4.5", f"pass needs exactly one attempt with outcome ok, has {list(zip(nos, outcomes))}")
        shape = PASS_SHAPE.get(r["case_id"])
        if shape and atts and [x["category"] for x in atts[-1]["exchanges"]] != shape:
            bad("I4.5", f"pass, but the exchanges observed {[x['category'] for x in atts[-1]['exchanges']]}, not the "
                        f"predicted {shape}")
    if decided and v5_start is not None and r["run_started"] >= v5_start:
        _decision(r, atts, k, exp, outcomes, inv, bad)
    ports = v2_start is not None and r["run_started"] >= v2_start          # exchanges.local_port recorded (v2)
    if k.observation == "runner":
        for a, outcome in zip(atts, outcomes):
            _attempt(r, a, k, exp, outcome, inv, decided, bad, ports, legacy)
    if decided:
        _evidence(r, k, inv, bad)
    return out


def _predicate_record(text) -> dict:
    """A recorded predicate set: a JSON object in which no name appears twice (json keeps the last of two equal names,
    so a false record followed by a true one would read as true). ValueError otherwise."""
    def pairs(items):
        names = [k for k, _ in items]
        twice = sorted({k for k in names if names.count(k) > 1})
        if twice:
            raise ValueError(f"{twice} recorded twice")
        return dict(items)
    return json.loads(text, object_pairs_hook=pairs)


def _decision(r: dict, atts: list[dict], k: CaseContract, exp: str | None, outcomes: list[str], inv: dict,
              bad) -> None:
    """I4.5 (schema v5): the predicates the verdict was decided on are recorded, a pass has every one true, and they
    include the final attempt's own predicates with the same values. Which predicates the decision holds comes from
    the case contract (case_predicates) and the final attempt's exchanges (derived_predicates), never from the row:
    a missing name is a missing observation (independent contract verification IC-02); a fail may hold the partial
    set of a case that stopped early. The verdict is the one its recorded basis yields, pass and fail alike. Before v5
    only the verdict records the case's own predicates (gateway bounds, timing, F11 shape): there the verdict is the
    basis, as the contract states."""
    try:
        preds = _predicate_record(r.get("predicates") or "null")
    except ValueError as e:
        preds = f"unreadable: {e}"
    if not isinstance(preds, dict) or not all(isinstance(v, bool) for v in preds.values()):
        bad("I4.5", f"the predicates its {r['verdict']} was decided on are not recorded ({str(preds)[:120]})")
        return
    if r["verdict"] == "pass" and not all(preds.values()):
        bad("I4.5", f"pass, but its recorded predicates {sorted(k for k, v in preds.items() if not v)} are false")
    if atts and atts[-1]["predicates"]:
        try:
            final = json.loads(atts[-1]["predicates"])
        except ValueError:
            final = {}
        differ = sorted(k for k, v in final.items() if preds.get(k) != v)
        if differ:
            bad("I4.5", f"decision predicates disagree with the final attempt's on {differ}")
    derived = set(derived_predicates(r, atts[-1], k)) if k.observation == "runner" and atts else set()
    full, partial = case_predicates(r["case_id"], r["device_id"], inv)
    got = set(preds)
    if k.observation == "record":           # C-ENVIRONMENT also records each contradictory other record, as false
        complete = full <= got and not any(preds[n] for n in got - full)
    else:
        complete = any(got == derived | s for s in (full, *(partial if r["verdict"] == "fail" else ())))
    if not complete:
        missing = sorted((derived | full) - got)
        extra = sorted(n for n in got - derived - full if k.observation != "record" or preds[n])
        bad("I4.5", f"its {r['verdict']} was not decided on the case's predicates: "
                    + "; ".join(([f"{missing} missing"] if missing else [])
                                + ([f"{extra} not recorded by the case"] if extra else [])))
    one_ok = k.observation != "runner" or (len(atts) == 1 and outcomes[0] == "ok")
    if r["verdict"] == "fail" and complete and one_ok and r["observed_category"] == exp and all(preds.values()):
        bad("I4.5", "fail, but its recorded decision basis (observed = expected, every predicate true"
                    + (", one attempt with outcome ok" if k.observation == "runner" else "") + ") yields pass")


def _outcome(a: dict, exp: str | None, legacy: bool, bad) -> str:
    if a["outcome"] is not None:
        return a["outcome"]
    if not legacy:
        bad("I4.6", f"attempt {a['attempt_no']}: no recorded outcome on a schema-v4 row")
        return "unrecorded"
    # rows before schema v4 record no outcome/predicates: the category is the only basis (stated, not assumed ok)
    if a["category"] is None:
        return "runner"
    return "ok" if a["category"] == exp and "restart observed" not in (a["detail"] or "") else "device"


def _attempt(r: dict, a: dict, k: CaseContract, exp, outcome: str, inv: dict, decided: bool, bad,
             ports: bool = True, legacy: bool = False) -> None:
    no = a["attempt_no"]
    xs = a["exchanges"]
    ords = [x["ord"] for x in xs]
    cut_attempt = a["category"] is None and (a["detail"] or "").startswith(DEADLINE)
    cuts = [x for x in xs if _cut(x)]
    if ords != list(range(1, len(xs) + 1)):
        bad("I5.1", f"attempt {no}: exchange ord {ords} is not 1..{len(xs)}")
    if not xs and not cut_attempt:
        bad("I5.1", f"attempt {no} has no exchange")
    letters = "".join(LETTER.get(x["cmd"], "?") for x in xs)
    if k.ops is None:                                     # F12: the bare first HEALTH only when it failed
        ok = bool(F12_GRAMMAR.fullmatch(letters)) and (letters != "H" or xs[0]["category"] not in PASSING)
    else:
        early = bool(xs) and (xs[-1]["category"] not in PASSING or bool(cuts)) or cut_attempt
        ok = letters == k.ops or (k.ops.startswith(letters) and early and (k.series or cut_attempt or bool(cuts)))
    if not ok:
        bad("I5.2", f"attempt {no}: commands {letters or '(none)'} do not follow "
                    f"{k.ops if k.ops is not None else F12_GRAMMAR.pattern}"
                    + (" (a series stops early only at a non-pass or deadline-cut exchange)" if k.series else ""))
    host, addr, port = target(r["case_id"], r["device_id"], inv)
    for x in xs:
        where = f"attempt {no} exchange {x['ord']}"
        if x["host"] != host or x["port"] != port:
            bad("I5.3", f"{where} dialled {x['host']}:{x['port']}, the case dials {host}:{port}")
        if x["addr"] is not None and x["addr"] != addr:
            bad("I5.3", f"{where} reached {x['addr']}, the case's {host} resolves to {addr}")
        cut = _cut(x)
        if x["addr"] is None and not (x["stage_failed"] == "resolve" and (x["category"] == "RESOLVE_FAIL" or cut)):
            bad("I6", f"{where}: no address, but not a failed resolve ({x['stage_failed']} {x['category']})")
        if x["category"] == "RESOLVE_FAIL" and x["addr"] is not None:
            bad("I6", f"{where}: RESOLVE_FAIL with address {x['addr']}")
        if x["os_error"] == "not_started" and not cut:
            bad("I6", f"{where}: 'not started' without the case deadline cutting it")
        if x["stage_failed"] == "connect" and x["os_error"] == "ENETUNREACH" and x["category"] != "NO_ROUTE" \
                and not cut:
            bad("I6", f"{where}: ENETUNREACH (nothing sent) classified {x['category']}")
        if ports and x["stage_failed"] not in ("resolve", "connect") and x["local_port"] is None and not cut:
            bad("I6", f"{where}: connected, but its local port is not recorded (the key that tells the runner's "
                      "connection from the gateway's polls to the same address:port)")
    sends = [str(x["t_send"]) for x in xs if x["t_send"]]
    if sends != sorted(sends):
        bad("I5.5", f"attempt {no}: exchanges out of chronological order (t_send by ord {sends})")
    cats = [x["category"] for x in xs]
    if cut_attempt or cuts:
        want = {None}
    elif k.ops is None:
        i = letters.find("I")
        want = {cats[0]} if letters == "H" else set(cats[3:i if i > 0 else len(cats)])
    else:
        want = {combine(cats)} if cats else {None}
    if a["category"] not in want:
        bad("I5.4", f"attempt {no}: category {a['category']} <> recomputed from its exchanges {sorted(map(str, want))}")
    preds, recorded = {}, a["predicates"] is not None
    if not recorded and not legacy:
        bad("I4.6", f"attempt {no}: no recorded predicates on a schema-v4 row (an empty set is recorded as {{}})")
    if a["predicates"]:
        try:
            preds = json.loads(a["predicates"])
        except ValueError:
            bad("I4.6", f"attempt {no}: predicates not JSON")
    if outcome == "ok" and (a["category"] != exp or not all(preds.values()) or cut_attempt or cuts):
        bad("I4.6", f"attempt {no}: outcome ok, but category {a['category']} (expected {exp}), predicates "
                    f"{sorted(k for k, v in preds.items() if not v)} false, deadline cut {bool(cut_attempt or cuts)}")
    for v in response_violations(r, a, k, preds if recorded else None, inv):
        bad("I5.6", v)


def derived_predicates(r: dict, a: dict, k: CaseContract) -> dict:
    """The predicates runner/cases.py computes for this attempt, recomputed from its exchanges and response bytes:
    C-HEALTH {status_ok, sensor_ok} from the HEALTH payload (or health_payload false); a READ series that ran to its
    end {reads_complete: true}, one that stopped early nothing; every other attempt nothing."""
    xs = a["exchanges"]
    if r["case_id"] == "C-HEALTH":
        o = _payload(xs[0]) if len(xs) == 1 and xs[0]["category"] in PASSING else None
        return ({"status_ok": o.get("status") == "ok", "sensor_ok": o.get("sensor_ok") is True} if o is not None
                else {"health_payload": False})
    if k.series:
        complete = "".join(LETTER.get(x["cmd"], "?") for x in xs) == k.ops and all(x["category"] in PASSING
                                                                                     for x in xs)
        return {"reads_complete": True} if complete else {}
    return {}


def response_violations(r: dict, a: dict, k: CaseContract, preds: dict | None, inv: dict) -> list[str]:
    """I5.6: a PASS/PASS_SLOW exchange carries the well-formed response (id echoed, the command's fields) that made
    it pass; IDENTIFY in identity-checked cases answers the inventory identity; the attempt's recorded predicates are
    exactly the ones its exchanges and response bytes yield (derived_predicates)."""
    out = []
    no, xs = a["attempt_no"], a["exchanges"]
    for x in xs:
        if x["category"] not in PASSING:
            continue
        where = f"attempt {no} exchange {x['ord']}"
        obj = _payload(x)
        if obj is None or not all(f in obj for f in _FIELDS.get(x["cmd"], ())):
            out.append(f"{where}: {x['category']} without a well-formed {x['cmd']} response echoing id {x['req_id']}")
        elif x["cmd"] == "IDENTIFY" and r["case_id"] in ("C-IDENTIFY", F12):
            d = next(d for d in inv["devices"] if d["device_id"] == r["device_id"])
            if (obj["device_id"], obj["serial"], obj["fw_version"]) != (d["device_id"], d["serial"], d["fw_version"]):
                out.append(f"{where}: PASS IDENTIFY answers {obj['device_id']}/{obj['serial']}, not the inventory's")
    if preds is not None:
        want = derived_predicates(r, a, k)
        if preds != want:
            out.append(f"attempt {no}: recorded predicates {preds} contradict its exchanges and responses, which yield "
                       f"{want}")
    return out


def _evidence(r: dict, k: CaseContract, inv: dict, bad) -> None:
    kinds = Counter(e["kind"] for e in r["evidence"])
    home = f"{r['evidence_path']}/"
    for e in r["evidence"]:                  # a record of this case lies in this case's directory, captures by name
        want = {"pcap": home + "capture.pcap", "pcap-field": home + "capture-field.pcap"}.get(e["kind"])
        if not e["path"].startswith(home) or (want and e["path"] != want):
            bad("I7", f"indexed '{e['kind']}' file {e['path']} is not {want or 'under ' + home}")
    need = {"pcap": 1, "pcap-text": 1, "timing": 1, "command-log": 1, "journal": 1 + (r["device_id"] is not None)}
    if "field" in k.captures:
        need.update({"pcap-field": 1, "pcap-field-text": 1})
    if r["verdict"] == "pass":
        need.update(k.on_pass_files)
    for kind, n in sorted(need.items()):
        if kinds[kind] != n:
            bad("I7" if kind in ("pcap", "pcap-field") else "I10.3",
                f"{kinds[kind]} indexed '{kind}' file(s); the case records exactly {n}")
    vms = [v["name"] for v in inv["lab"]["vms"]]
    for phase in ("precheck", "postflight"):
        rows = [c for c in r["checks"] if c["phase"] == phase]
        missing = [vm for vm in vms if not any(c["vm"] == vm for c in rows)]
        failed = sorted({c["name"] for c in rows if c["status"] == "FAIL"})
        if missing or failed:
            bad("I4.5", f"{phase} checks " + (f"missing for {missing}" if missing else f"FAIL: {failed}"))
    if r["verdict"] != "pass":
        return
    if k.applications and (len(r["events"]) != k.applications
                           or any(e["removal_verified"] != 1 for e in r["events"])):
        bad("I10.2", f"{len(r['events'])} fault application(s) ({[e['removal_verified'] for e in r['events']]} "
                     f"verified); the case applies its fault {k.applications} time(s)")
    devs = [d["device_id"] for d in inv["devices"]] if r["case_id"] == "GW-F5-UNREACHABLE" else [r["device_id"]]
    want = sorted({m.format(dev=d) for m in k.measurements for d in devs})
    got = sorted(m["name"] for m in r["measurements"])
    if got != want:
        bad("I10.3", f"measurements {sorted(set(want) - set(got)) or ''} missing"
                     + (f", {sorted(set(got) - set(want))} unexpected" if set(got) - set(want) else "")
                     + (" (duplicated)" if len(got) != len(set(got)) else ""))
    for m in r["measurements"]:              # a pass is within every bound it measured, unless the case predicts not
        if m["bound"] is not None and (r["case_id"], m["name"]) not in OUTSIDE_BOUND_ON_PASS and \
                (not isinstance(m["value"], (int, float)) or not isinstance(m["bound"], (int, float))
                 or m["value"] > m["bound"]):
            bad("I10.3", f"pass, but measurement {m['name']}={m['value']} {m['unit']} exceeds its bound {m['bound']}")


# ---------------------------------------------------------------- I8: capture-flow records

def derived_flows(r: dict) -> list[dict]:
    """runner/lab.dialled_flows over ALL exchanges of a result, each with its record filter (bpf) or the reason it
    is not a flow. A result without exchanges has none: its evidence chain is then violated (I5.1), never skipped."""
    rows = [(x["addr"], x["port"], x["local_port"], x["stage_failed"], x["os_error"])
            for a in r["attempt_rows"] for x in a["exchanges"]]
    out = []
    for f in L.dialled_flows(rows):
        try:
            f["bpf"] = L.flow_record_filter(f)
        except ValueError as e:
            f["bpf"], f["error"] = None, str(e)
        out.append(f)
    return out


def gateway_flows(r: dict, inv: dict) -> list[str]:
    """I8.2: the polls a gateway-observed case watched (no runner exchange, no capture_flows record): the observed
    device's address:port (every device for GW-F5) must be in each required capture."""
    if r["case_id"] not in GATEWAY_OBSERVED:
        return []
    devs = inv["devices"] if r["case_id"] == "GW-F5-UNREACHABLE" else \
        [d for d in inv["devices"] if d["device_id"] == r["device_id"]]
    return [L.flow_filter(d["address"], d["port"]) for d in devs]


def flow_record_violations(conn, loaded: dict[int, dict], why: dict[int, str]) -> list[str]:
    """A17 over the given results: every dialled flow x required capture has exactly one record with the matching
    expectation, nothing unaccounted (an expected record with 0 packets: runner/analysis.py A17 SQL). Results recorded before capture_flows
    existed (schema v4) have no records: a latest fair one is listed, the bytes are still recounted by A20."""
    out = []
    v4 = migration_time(conn, 4) if has(conn, "capture_flows") else None
    for rid, r in sorted(loaded.items()):
        try:
            out += _flow_records(r, v4, why.get(rid))
        except Exception as e:  # noqa: BLE001 - fail closed
            out.append(_fail_closed(_label(r), e))
    return out


def _flow_records(r: dict, v4: str | None, why: str | None) -> list[str]:
    out = []
    lab = _label(r)
    if v4 is None or r["run_started"] < v4:
        if why == "latest":
            out.append(f"{lab}: [I8.1] latest fair result has no capture-flow record (recorded before the F-07 "
                       "check)")
        return out
    k = contract(r["case_id"]) if r["case_id"] in CASES_BY_ID else None
    stored = Counter((f["capture"], f["filter"]) for f in r["flow_rows"])
    by_key = {(f["capture"], f["filter"]): f for f in r["flow_rows"]}
    need = set()
    for f in derived_flows(r):
        if f["bpf"] is None:
            out.append(f"{lab}: [I8.1] exchange endpoint {f['addr']}:{f['port']} is not a flow: {f['error']}")
            continue
        for cap in (k.captures if k else ("ctl",)):
            need.add((cap, f["bpf"]))
            row = by_key.get((cap, f["bpf"]))
            if row is None:
                out.append(f"{lab}: [I8.1] {cap} capture has no record of dialled flow {f['bpf']} ({f['why']})")
            elif bool(row["expected"]) != f["expected"]:
                out.append(f"{lab}: [I8.1] {cap} record of {f['bpf']} says expected={row['expected']}, its "
                           f"exchanges say {int(f['expected'])} ({f['why']})")
    out += [f"{lab}: [I8.1] {cap} record of {bpf} is not accounted for by the case's dialled flows and captures"
            for cap, bpf in sorted(set(stored) - need)]
    out += [f"{lab}: [I8.1] {cap} record of {bpf} stored {n} times" for (cap, bpf), n in sorted(stored.items())
            if n > 1]
    return out


# ---------------------------------------------------------------- I9: the bytes

def bytes_violations(conn, loaded: dict[int, dict], root, inv: dict | None = None) -> list[str]:
    return [v for _, v in _bytes(conn, loaded, root, inv or EV.repo_inventory())]


def _bytes(conn, loaded: dict[int, dict], root, inv: dict) -> list[tuple[int | None, str]]:
    """A20 over the given results: every indexed file of each (and its run's session files) has its recorded length
    and SHA-256; every required capture of a decided result is indexed exactly once; every expected dialled flow, and
    every gateway-observed device's polls, are recounted from the hash-verified capture (runner/evidence.flow_packets)
    and are > 0 and equal to their records."""
    if root is None:
        return [(None, "[I9] evidence bytes not verified: no evidence root given (python3 -m runner.analysis --db DB "
                       "--evidence-root DIR)")]
    root = Path(root)
    if not root.is_dir():
        return [(None, f"[I9] evidence root {root} is not a directory: nothing verified")]
    out, broken = [], set()
    runs = sorted({r["run_id"] for r in loaded.values()})
    session = _dicts(conn.execute("SELECT * FROM evidence WHERE result_id IS NULL AND run_id IN (SELECT value FROM "
                                  "json_each(?)) ORDER BY evidence_id", (_ids(runs),)))
    checked = session + [e for r in loaded.values() for e in r["evidence"]]
    for path, n in sorted(Counter(str(e["path"]) for e in checked).items()):
        if n > 1:
            out.append((None, f"[I9] {path} is indexed {n} times (one file, one record)"))
    for e in checked:
        try:
            why = EV.file_problem(root, str(e["path"]), e["sha256"], e["bytes"])
        except Exception as ex:  # noqa: BLE001 - fail closed
            why = f"cannot be checked ({type(ex).__name__})"
        if why:
            broken.add(e["evidence_id"])
            rid = e["result_id"]
            lab = _label(loaded[rid]) if rid in loaded else f"run{e['run_id']} (session)"
            out.append((rid, f"{lab}: [I9] {e['path']}: {why}"))
    for rid, r in sorted(loaded.items()):
        try:
            out += _result_bytes(rid, r, root, inv, broken)
        except Exception as e:  # noqa: BLE001 - fail closed
            out.append((rid, _fail_closed(_label(r), e)))
    return out


def _result_bytes(rid: int, r: dict, root: Path, inv: dict, broken: set) -> list[tuple[int | None, str]]:
    out = []
    if r["case_id"] not in CASES_BY_ID or r["verdict"] not in ("pass", "fail"):
        return out
    lab = _label(r)
    k = contract(r["case_id"])
    flows = [f for f in derived_flows(r) if f["expected"] and f["bpf"]]
    polls = gateway_flows(r, inv)
    for cap in k.captures:
        kind = "pcap" if cap == "ctl" else "pcap-field"
        got = [e for e in r["evidence"] if e["kind"] == kind]
        if len(got) != 1:
            out.append((rid, f"{lab}: [I7] {len(got)} indexed {cap} capture files; exactly one is required"))
            continue
        if got[0]["evidence_id"] in broken:
            continue                                       # already listed: its bytes cannot be trusted
        data = (root / got[0]["path"]).read_bytes()
        counted = [(f["filter"], f["packets"]) for f in r["flow_rows"] if f["capture"] == cap
                   and f["packets"] is not None and f["filter"].startswith("tcp ")]
        try:
            for f in flows:
                if EV.flow_packets(data, f["bpf"]) == 0:
                    out.append((rid, f"{lab}: [I9] {got[0]['path']} holds no packet of dialled flow {f['bpf']} "
                                     "(the bytes, recounted)"))
            for bpf in polls:
                if EV.flow_packets(data, bpf) == 0:
                    out.append((rid, f"{lab}: [I8.2] {got[0]['path']} holds no packet of the gateway's polls {bpf}"))
            for bpf, n in counted:
                m = EV.flow_packets(data, bpf)
                if m != n:
                    out.append((rid, f"{lab}: [I9] {cap} record says {n} packets of {bpf}, {got[0]['path']} holds {m}"))
        except EV.PcapError as e:
            out.append((rid, f"{lab}: [I9] {got[0]['path']} cannot be verified: {e}"))
    return out


# ---------------------------------------------------------------- I1, I10.4: runs, plans, receipts

MARKERS = ("contaminated:", "aborted:")


def plan_rows(conn) -> dict[int, list[tuple[str, str | None]]]:
    if not has(conn, "run_plan"):
        return {}
    out = defaultdict(list)
    for run_id, case_id, dev in conn.execute("SELECT run_id, case_id, device_id FROM run_plan"):
        out[run_id].append((case_id, dev))
    return dict(out)


def run_violations(conn, inv: dict | None = None, root=None, runs=None) -> list[str]:
    """I1.2-I1.5 and I10.4 for every run (or `runs`): flags agree with their records; every fair run executed exactly
    its declared selection with its session checks and evidence indexed; with an evidence root, plan files and
    receipts (case directories) agree with the results."""
    return [v for _, v in _runs(conn, inv or EV.repo_inventory(), root, runs)]


def _runs(conn, inv: dict, root, runs) -> list[tuple[str | None, str]]:
    """run_violations as (device the violation concerns, None = the whole run; message); fails closed."""
    try:
        return _runs_checked(conn, inv, root, runs)
    except Exception as e:  # noqa: BLE001 - an unevaluable run record is a violation, never a pass
        return [(None, _fail_closed(f"runs {runs or 'all'}", e))]


def _runs_checked(conn, inv: dict, root, runs) -> list[tuple[str | None, str]]:
    out: list[tuple[str | None, str]] = []

    def add(msg: str, dev: str | None = None) -> None:
        out.append((dev, msg))

    vms = [v["name"] for v in inv["lab"]["vms"]]
    start = migration_time(conn, 5)
    plans = plan_rows(conn)
    sel = "" if runs is None else " WHERE run_id IN (SELECT value FROM json_each(?))"
    args = () if runs is None else (_ids(runs),)
    rows = _dicts(conn.execute("SELECT * FROM runs" + sel + " ORDER BY run_id", args))
    env = defaultdict(dict)
    for r, k, v in conn.execute("SELECT run_id, key, value FROM environment"):
        env[r][k] = v
    checks = defaultdict(list)
    for c in _dicts(conn.execute("SELECT run_id, result_id, phase, vm, name, status FROM checks" + sel, args)):
        checks[c["run_id"]].append(c)
    results = defaultdict(list)
    for r in _dicts(conn.execute("SELECT result_id, run_id, case_id, device_id, verdict, evidence_path FROM results"
                                 + sel, args)):
        results[r["run_id"]].append(r)
    session = defaultdict(list)
    for e in _dicts(conn.execute("SELECT * FROM evidence WHERE result_id IS NULL"
                                 + ("" if runs is None else " AND run_id IN (SELECT value FROM json_each(?))"), args)):
        session[e["run_id"]].append(e)
    environments = defaultdict(list)
    for e in _dicts(conn.execute("SELECT * FROM evidence WHERE (kind = 'environment' OR "
                                 "path GLOB 'run-*/session/environment.json')"
                                 + ("" if runs is None else " AND run_id IN (SELECT value FROM json_each(?))"), args)):
        environments[e["run_id"]].append(e)
    started = dict(conn.execute("SELECT run_id, started_at FROM runs"))
    # first and last session record of every run (append-only checks/evidence without a result): when a session was
    # demonstrably running, independent of the runs row's own columns (_abort_unconfirmed)
    sessions = {r: (first, last) for r, first, last in conn.execute(
        "SELECT run_id, min(t), max(t) FROM (SELECT run_id, checked_at AS t FROM checks WHERE result_id IS NULL "
        "UNION ALL SELECT run_id, created_at FROM evidence WHERE result_id IS NULL) GROUP BY run_id")}
    unverified = {r[0] for r in conn.execute("SELECT DISTINCT run_id FROM fault_events WHERE "
                                             "coalesce(removal_verified, 0) <> 1")}
    resets = {r[0] for r in conn.execute("SELECT DISTINCT run_id FROM evidence WHERE kind = 'reset'")}
    for ru in rows:
        run = ru["run_id"]
        lab = f"run {run}"
        finished = ru["finished_at"] is not None
        planned_run = (start is not None and ru["started_at"] >= start) or run in plans or \
            any(e["kind"] == "plan" for e in session[run])
        post_recorded = any(c["result_id"] is None and c["phase"] == "session-postflight" for c in checks[run]) or \
            any(e["kind"] == "postflight" for e in session[run])
        # Check recorded identity before excluding ANY kind or unfair status. Mutant/superseded runs need this
        # comparison too: changing a baseline's kind must never hide its failure via an older baseline (F3).
        out += [(None, v) for v in _session_environment(ru, env[run], environments[run], root, inv, planned_run,
                                                      progressed=bool(results[run]) or post_recorded)]
        pre = [c for c in checks[run] if c["result_id"] is None and c["phase"] == "preflight"]
        if finished:
            e = env[run].get("runs.clean_env")
            if e is not None and e != str(ru["clean_env"]):
                add(f"{lab}: [I1.2] runs.clean_env={ru['clean_env']} but the environment records {e!r}")
            fails = [c for c in pre if c["status"] == "FAIL"]
            if ru["clean_env"] == 1 and (fails or any(not any(c["vm"] == vm for c in pre) for vm in vms)):
                add(f"{lab}: [I1.2] clean_env=1 but its session preflight " + (
                    f"failed {sorted({c['name'] for c in fails})}" if fails else "is not recorded for every VM"))
            if ru["clean_env"] == 0 and not fails:
                add(f"{lab}: [I1.2] clean_env=0 without a failed session preflight check")
        if not finished and post_recorded:
            add(f"{lab}: [I1.2] not finished, yet its session postflight (written just before the run finishes) is "
                "recorded")
        if ru["contaminated"]:
            why = _contamination_cause(ru, started, any(c["status"] == "FAIL" for c in checks[run]),
                                       run in unverified, run in resets, sessions)
            if why:
                add(f"{lab}: [I1.2] contaminated {why}")
        if not (finished and ru["clean_env"] == 1 and ru["contaminated"] == 0):
            continue                                                # unfair: kept, listed, never evidence
        failed = sorted({f"{c['phase']}:{c['name']}" for c in checks[run] if c["status"] == "FAIL"})
        if failed:
            add(f"{lab}: [I1.2] fair run holds failed checks {failed[:5]}")
        post = [c for c in checks[run] if c["result_id"] is None and c["phase"] == "session-postflight"]
        missing = [vm for vm in vms if not any(c["vm"] == vm for c in post)]
        if missing:
            add(f"{lab}: [I1.2] no session postflight recorded for {missing}")
        kinds = Counter(e["kind"] for e in session[run])
        for e in session[run]:
            if not e["path"].startswith(f"run-{run}/session/"):
                add(f"{lab}: [I10.4] session file {e['path']} is not under run-{run}/session/")
        want = dict(SESSION_FILES, **({"plan": 1} if planned_run else {}))
        for kind, n in sorted(want.items()):
            if kinds[kind] != n:
                add(f"{lab}: [I10.4] {kinds[kind]} indexed session '{kind}' file(s); the session records {n}")
        got = Counter((r["case_id"], r["device_id"]) for r in results[run])
        if planned_run:
            plan = plans.get(run, [])
            if not plan:
                add(f"{lab}: [I1.3] no run plan (the run started under schema v5)")
            for c, d in plan:
                why = instance_problem(c, d, inv)
                if why:
                    add(f"{lab}: [I1.3] planned {c}/{d or '(run)'}: {why}", d)
                if got[(c, d)] != 1:
                    add(f"{lab}: [I1.4] planned {c}/{d or '(run)'} has {got[(c, d)]} results", d)
            for (c, d) in sorted(set(got) - set(plan), key=str):
                if plan:
                    add(f"{lab}: [I1.4] result {c}/{d or '(run)'} is not in the run plan", d)
            if root is not None:
                out += [(None, v) for v in _plan_file(lab, root, session[run], plan)]
        if root is not None:
            out += _receipts(lab, Path(root), run, results[run])
    if root is not None and runs is None:
        ids = {ru["run_id"] for ru in rows}
        for p in sorted(Path(root).glob("run-*")):
            if p.is_dir() and p.name[4:].isdigit() and int(p.name[4:]) not in ids:
                add(f"run {p.name[4:]}: [I1.5] evidence directory {p.name}/ has no run row")
    return out


def _session_environment(ru: dict, env: dict, files: list[dict], root, inv: dict, v5: bool, *,
                         progressed: bool = False) -> list[str]:
    """I1.7: compare the session's recorded environment with its DB representation, regardless of selection.

    Hash agreement establishes correspondence with the index, NOT authenticity: this detects metadata edits while
    session bytes are preserved, not a coordinated rewrite of files and metadata. No file access without a root
    (the audit separately rejects that omission). Only an unfinished session with no durable collection facts can
    predate its environment: plans/preflight precede collection, but environment rows, case results, postflight or
    a recorded finish require the snapshot independently of the index being validated. Lost bytes are unverified,
    even if the writer was interrupted between persisting the environment rows and saving the snapshot.
    """
    lab = f"run {ru['run_id']}: [I1.7] session environment"
    path = f"run-{ru['run_id']}/session/environment.json"
    fair = ru["finished_at"] is not None and ru["clean_env"] == 1 and ru["contaminated"] == 0
    present = root is not None and (Path(root) / path).exists()
    if ru["finished_at"] is None and not (env or progressed or files or present):
        return []
    if len(files) != 1:
        return [f"{lab}: {len(files)} indexed records, expected exactly one"]
    e = files[0]
    if e["result_id"] is not None or e["kind"] != "environment" or e["path"] != path:
        return [f"{lab}: index must be run-level kind=environment at {path}"]
    if root is None:
        return []
    try:
        raw = (Path(root) / path).read_bytes()
        if len(raw) != e["bytes"] or hashlib.sha256(raw).hexdigest() != e["sha256"]:
            return [f"{lab}: {path} differs from its index (length/SHA-256)"]
        # The strict reader keeps duplicate names (including escaped aliases) from silently taking the last value.
        doc = _predicate_record(raw)
        if not isinstance(doc, dict) or any(not isinstance(v, str) for v in doc.values()):
            return [f"{lab}: expected a JSON object of text values"]
    except (OSError, ValueError, TypeError) as exc:
        return [f"{lab}: {path} unreadable: {exc}"]
    out = []
    required = {"runs.kind", "git_sha", "git_dirty"}
    if fair:
        required.update(EV.required_env_keys(inv))
        required.discard("runs.clean_env")  # db.set_clean_env writes this to the TABLE after env was collected
    if v5 or ru["kind"] == "mutant":
        required.update({"mutant", *(f"device_build.{d['device_id']}" for d in inv["devices"])})
    missing = required - doc.keys()
    if missing:
        out.append(f"{lab}: missing recorded keys {sorted(missing)}")
    for key in sorted(doc.keys() | env.keys()):
        if key == "runs.clean_env" and key not in doc:
            continue  # absent in actual live snapshots, present in some valid fixture/legacy formats
        if key not in doc or key not in env or doc[key] != env[key]:
            out.append(f"{lab}: {key} differs between session bytes and environment table")
    for key, value in (("runs.kind", ru["kind"]), ("git_sha", ru["git_sha"]),
                       ("git_dirty", str(ru["git_dirty"])), ("mutant", ru.get("mutant_id") or "none"),
                       ("runs.clean_env", str(ru["clean_env"]))):
        if key in doc and doc[key] != value:
            out.append(f"{lab}: {key} contradicts the runs row")
    return out


_ABORTED = re.compile(r"aborted: never finished \(detected by run (\d+)\)")
_STAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z")          # runner/db.utcnow


def _contamination_cause(ru: dict, started: dict, failed_check: bool, unverified: bool, reset: bool,
                         sessions: dict) -> str | None:
    """None if a contaminated run's flag is corroborated, else why not. The runner sets it with a cause (db.py
    mark_contaminated "contaminated: <why>" after a red check, an unverified fault removal or a reset; mark_aborted_runs
    "aborted: never finished (detected by run N)" when a later session found it unfinished). A bare edit of the flag
    (and its note) would otherwise hand a newer run's instances to an older run. Every abort marker must name a
    separate, later session that demonstrably began while this run was unfinished (_abort_unconfirmed): independent
    contract verification IC-01, a run naming itself satisfied "started within its interval" by construction, and
    its own finished_at could claim the overlap (independent review F1)."""
    notes = ru["notes"] or ""
    found = _ABORTED.findall(notes)
    if found:
        for n in found:                     # earlier stores carry one marker per later session (master run 7)
            why = _abort_unconfirmed(ru, int(n), started, sessions)
            if why:
                return f"as aborted, but run {n} cannot have found it unfinished: {why}"
        return None
    if "contaminated:" in notes:
        return None if (failed_check or unverified or reset) else \
            "with a note but no failed check, unverified fault removal or reset recorded"
    return f"without the runner's recorded cause ({' / '.join(MARKERS)})"


def _abort_unconfirmed(ru: dict, det: int, started: dict, sessions: dict) -> str | None:
    """Why run `det` cannot be the later session that found run `ru` unfinished (db.mark_aborted_runs, at that
    session's start, just before it records its session preflight), else None. It must be a separate recorded run
    with a larger id and a later recorded start (run ids follow start order) that recorded its session, and `ru` must
    have been unfinished then: no finish, or a finish after that start whose own last session record (its teardown)
    follows `det`'s first session record (equal times cannot order them) — as master run 38's SIGTERM teardown (postflight 45.210-45.213, command log 45.218)
    followed run 39's first preflight check (45.087). The runs row's finished_at alone cannot say so: it is the same
    row as the flag (independent review F1). Session records are `sessions[run] = (first, last)` record time; times
    in another form cannot be ordered."""
    run, own, end = ru["run_id"], ru["started_at"], ru["finished_at"]
    if det == run:
        return "it names itself as the later session"
    if det not in started:
        return f"run {det} is not a recorded run"
    when = started[det]
    if not all(isinstance(t, str) and _STAMP.fullmatch(t) for t in (own, when) + ((end,) if end is not None else ())):
        return (f"a start or finish time is not recorded in the runner's form (started {own!r}, finished {end!r}, run "
                f"{det} started {when!r}): their order cannot be established")
    if det < run or when <= own:
        return f"run {det} (started {when}) did not start after it (run {run}, started {own})"
    if end is not None and end < when:
        return f"it finished ({end}) before run {det} started ({when})"
    first = (sessions.get(det) or (None, None))[0]
    if not (isinstance(first, str) and _STAMP.fullmatch(first)):
        return f"run {det} has no session record (preflight checks, session files): no record shows it ran"
    if end is not None:
        last = (sessions.get(run) or (None, None))[1]
        if not (isinstance(last, str) and _STAMP.fullmatch(last) and last > first):
            return (f"it records a finish ({end}), but its last session record ({last}) does not follow run {det}'s "
                    f"first ({first}): only its own finished_at says it was still running")
    return None


def _plan_file(lab: str, root, files: list[dict], plan: list) -> list[str]:
    f = [e for e in files if e["kind"] == "plan"]
    if len(f) != 1:
        return []                                       # counted above (I10.4)
    why = EV.file_problem(Path(root), f[0]["path"], f[0]["sha256"], f[0]["bytes"])
    if why:
        return [f"{lab}: [I1.3] plan file {f[0]['path']}: {why}"]
    try:
        doc = json.loads((Path(root) / f[0]["path"]).read_text())
        listed = sorted((c, d) for c, d in doc["instances"])
    except (ValueError, KeyError, TypeError) as e:
        return [f"{lab}: [I1.3] plan file {f[0]['path']} unreadable: {e}"]
    rows = sorted(plan, key=lambda x: (x[0], x[1] or ""))
    if sorted(listed, key=lambda x: (x[0], x[1] or "")) != rows:
        return [f"{lab}: [I1.3] plan file {f[0]['path']} lists {len(listed)} instances, the run_plan rows "
                f"{len(rows)} ({sorted(set(map(tuple, listed)) ^ set(rows), key=str)[:3]} differ)"]
    return []


def _receipts(lab: str, root: Path, run: int, results: list[dict]) -> list[tuple[str | None, str]]:
    """I1.5: case directories (written by every executed case) <-> results' evidence_path."""
    out = []
    d = root / f"run-{run}"
    dirs = {f"run-{run}/{p.name}" for p in d.iterdir() if p.is_dir() and "__" in p.name} if d.is_dir() else set()
    paths = set()
    for r in results:
        what = f"{r['case_id']}/{r['device_id'] or '(run)'}"
        want = f"run-{run}/{r['case_id']}__{r['device_id'] or 'run'}"
        if r["evidence_path"] != want:
            out.append((r["device_id"], f"{lab}: [I1.5] {what} evidence_path {r['evidence_path']!r} is not its "
                                        f"directory {want}"))
        paths.add(r["evidence_path"])
        if r["verdict"] in ("pass", "fail") and r["evidence_path"] not in dirs:
            out.append((r["device_id"], f"{lab}: [I1.5] decided {what} has no evidence directory {r['evidence_path']}"))
    for p in sorted(dirs - paths):
        dev = p.rsplit("__", 1)[-1]
        out.append((None if dev == "run" else dev, f"{lab}: [I1.5] evidence directory {p}/ (an executed case) has "
                                                    "no result"))
    return out


# ---------------------------------------------------------------- commissioning (I10.5)

def commissioning_contract_gaps(conn, run_id: int, inv: dict, root=None) -> dict[str, list[str]]:
    """{device: contract violations among the run's commissioning prerequisites and the run itself}: what the
    commissioning decision must apply on top of verdicts (RC-6). Bytes and receipts only with an evidence root."""
    devs = required_devices(conn, inv)
    req = set(required_commissioning(conn, inv))
    rids = {r[0]: (r[1], r[2]) for r in conn.execute(
        "SELECT result_id, case_id, device_id FROM results WHERE run_id = ?", (run_id,)) if (r[1], r[2]) in req}
    out: dict[str, list[str]] = {d: [] for d in devs}
    every = []
    for dev, v in _runs(conn, inv, root, [run_id]):
        (out[dev] if dev in out else every).append(v)
    loaded = load(conn, rids)
    per = result_violations(conn, rids, inv)
    for rid, r in loaded.items():
        per[rid] = per.get(rid, []) + flow_record_violations(conn, {rid: r}, {})
    if root is not None:
        for rid, v in _bytes(conn, loaded, root, inv):
            dev = rids[rid][1] if rid in rids else None
            (out[dev] if dev in out else every).append(v)
    for rid, vs in per.items():
        dev = rids[rid][1]
        for d in ([dev] if dev else devs):
            out[d] += vs
    for d in devs:
        out[d] += every
    return out
