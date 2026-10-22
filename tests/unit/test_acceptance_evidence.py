"""Second independent audit (docs/independent-reaudit.md): negative regression tests for R-01 (invalid environment
evidence, conflicting duplicate results) and R-02 (incomplete capture-flow evidence), plus the similar holes found
around them (reference tables, evidence bytes, fault applications, recorded predictions). Every test tampers with a
fixture store that otherwise passes all 21 assertions, and checks that the RIGHT assertion rejects it for the RIGHT
reason. Fixture stores and synthetic pcaps (tests/unit/storefix.py); never lab evidence."""
from types import SimpleNamespace

import pytest

from runner import analysis as A, db, evidence as EV, report
from storefix import (INV, accepted_store, baseline, env_ok, flow_frames, new_store, pcap_bytes, reindex, result,
                      wire)

F3_BPF = "tcp and host 10.77.2.11 and port 5021"


@pytest.fixture
def w(tmp_path):
    conn = new_store(tmp_path / "w.db")
    runs = accepted_store(conn)                # every result recorded with its full evidence chain (storefix)
    root = tmp_path / "evidence"
    root.mkdir(exist_ok=True)

    def rid(run, case, dev="dev-a"):
        return conn.execute("SELECT result_id FROM results WHERE run_id=? AND case_id=? AND device_id IS ?",
                            (run, case, dev)).fetchone()[0]

    def captures(r):
        return {"ctl" if k == "pcap" else "field": root / p for k, p in conn.execute(
            "SELECT kind, path FROM evidence WHERE result_id=? AND kind IN ('pcap', 'pcap-field')", (r,))}
    ns = SimpleNamespace(conn=conn, runs=runs, root=root, rid=rid, fault=runs["fault"], final=runs["final"])
    ns.f3 = rid(runs["fault"], "FT-F3-WRONG-PORT")            # refused connect: address:port flow, SYN/RST
    ns.f3_paths = captures(ns.f3)
    ns.f5 = rid(runs["fault"], "FT-F5-NO-ROUTE")              # legitimately nothing on the wire
    ns.f7 = rid(runs["fault"], "FT-F7-NAME-MISSING")          # name never resolved: no address at all
    ns.health = rid(runs["final"], "C-HEALTH")               # established flow, keyed on the runner's port,
    ns.health_paths = captures(ns.health)                    # beside the gateway's polls to the same address:port
    ns.health_lport = conn.execute("SELECT x.local_port FROM exchanges x JOIN attempts a USING (attempt_id) WHERE "
                                   "a.result_id=?", (ns.health,)).fetchone()[0]
    ns.mutant = rid(runs["mutants"][1], "C-IDENTIFY")        # the latest valid M2 run: current mutant evidence
    conn.commit()
    yield ns
    conn.close()


def audit(w, root="default") -> dict:
    return {a["id"].split("-")[0]: a for a in A.audit(w.conn, evidence_root=w.root if root == "default" else root)}


def violated(w, **kw) -> set[str]:
    return {k for k, a in audit(w, **kw).items() if not a["ok"]}


def test_complete_wired_store_passes_every_assertion(w):
    au = audit(w)
    assert len(au) == 24 and not {k: a["violations"] for k, a in au.items() if not a["ok"]}
    assert au["A18"]["run"] == w.final


# ---------------------------------------------------------------- R-01: environment evidence

@pytest.mark.parametrize("key", EV.required_env_keys(INV))
def test_every_missing_required_environment_key_is_rejected(w, key):
    w.conn.execute("DELETE FROM environment WHERE run_id=? AND key=?", (w.final, key))
    au = audit(w)
    assert au["A13"]["violations"] == [f"{w.final}:{key}=missing"]
    assert au["A18"]["run"] == w.final and all(f"environment record invalid: {key} missing" in v
                                                for v in au["A18"]["violations"])
    assert db.commissioned_devices(w.conn, w.final) == []


@pytest.mark.parametrize("key,value,why", [
    ("python", "\t\n", "blank"),                         # the audit's exact R-01 value
    ("chrony.offset", "offset_s=garbage", "not 'offset_s="),
    ("git_sha", "not-the-run-revision", "not a 40-hex"),
    ("git_sha", "f" * 40, "contradicts runs.git_sha"),
    ("git_dirty", "1", "contradicts runs.git_dirty"),
    ("qdisc.witness-field", "lab0: qdisc fq_codel 0: root refcnt 2", "not the lab interfaces"),
    ("nft.witness-field", "\n", "blank"),
    ("fw_version.dev-a", "unavailable (READ_TIMEOUT: no_bytes_by_deadline)", "withheld by the device"),
])
def test_invalid_environment_value_in_the_latest_baseline_is_rejected(w, key, value, why):
    w.conn.execute("UPDATE environment SET value=? WHERE run_id=? AND key=?", (value, w.final, key))
    au = audit(w)
    assert len(au["A13"]["violations"]) == 1 and au["A13"]["violations"][0].startswith(f"{w.final}:{key}=")
    assert why in au["A13"]["violations"][0]
    assert not au["A18"]["ok"] and db.commissioned_devices(w.conn, w.final) == []


def test_blob_environment_value_is_rejected(w):
    w.conn.execute("UPDATE environment SET value=CAST('3.12.3' AS BLOB) WHERE run_id=? AND key='python'", (w.final,))
    v = audit(w)["A13"]["violations"]
    assert v == [f"{w.final}:python=not text (bytes b'3.12.3')"]


@pytest.mark.parametrize("key,value", [("python ", "2.7.18"), ("runs.kind", "fault"), ("mutant", "M4"),
                                       ("device_build.a.witness-field", "mutant:off-by-one-id")])
def test_contradictory_duplicate_environment_records_are_rejected(w, key, value):
    db.put_env(w.conn, w.final, {key: value})
    au = audit(w)
    assert au["A13"]["violations"] and all(x.startswith(f"{w.final}:") for x in au["A13"]["violations"])
    assert any(s in x for x in au["A13"]["violations"] for s in ("ambiguous duplicate", "contradicts"))
    assert not au["A18"]["ok"]


def test_withheld_firmware_is_honest_only_for_the_mutant_device(w):
    m1 = w.runs["mutants"][0]
    w.conn.execute("UPDATE environment SET value='unavailable (WRONG_IDENTITY: serial WIT-0002)' WHERE run_id=? "
                   "AND key='fw_version.dev-a'", (m1,))
    assert "A13" not in violated(w)
    w.conn.execute("UPDATE environment SET value='unavailable (MALFORMED: x)' WHERE run_id=? AND key='fw_version.dev-b'",
                   (m1,))
    assert audit(w)["A13"]["violations"][0].startswith(f"{m1}:fw_version.dev-b=withheld by the device")


@pytest.mark.parametrize("how", ["unfinished", "contaminated", "unclean", "interrupted"])
def test_invalid_evidence_in_an_unfair_run_is_neither_accepted_nor_held_against_the_store(w, how):
    """Unfair runs are not evidence: an invalid record in one is not an A13/A19 violation, and the run commissions
    nothing, so the previous complete baseline remains the commissioning evidence."""
    env = {**env_ok(), "python": "\t", "chrony.offset": "no reply rc=1"}
    run = baseline(w.conn, env=env, finished=how not in ("unfinished", "interrupted"), clean=int(how != "unclean"))
    result(w.conn, run, "C-HEALTH", "dev-a", verdict="fail", attribution="device", observed="READ_TIMEOUT")
    if how == "contaminated":                           # as the live case does: a red postflight check, then the flag
        db.add_checks(w.conn, run, "postflight", "witness-field", [{"name": "no-fault-nft", "status": "FAIL"}])
        db.mark_contaminated(w.conn, run, "postflight red after C-HEALTH")
    if how == "interrupted":
        db.mark_aborted_runs(w.conn, baseline(w.conn))      # the next session marks it; that run is the new final
    au = audit(w)
    assert not violated(w), {k: a["violations"] for k, a in au.items() if not a["ok"]}
    assert db.commissioned_devices(w.conn, run) == [] and au["A18"]["run"] != run


# ---------------------------------------------------------------- R-01: result cardinality / conflicting duplicates

def _duplicate(w, run, case, dev, rows):
    base = dict(w.conn.execute("SELECT * FROM results WHERE run_id=? AND case_id=? AND device_id IS ?",
                               (run, case, dev)).fetchone())
    base.pop("result_id")
    for verdict, attr in rows:
        base.update(verdict=verdict, attribution=attr, detail="conflicting duplicate")
        w.conn.execute("INSERT INTO results (" + ",".join(base) + ") VALUES (" + ",".join("?" * len(base)) + ")",
                       tuple(base.values()))


@pytest.mark.parametrize("order", [(("fail", "device"), ("pass", "none")), (("pass", "none"), ("fail", "device"))],
                         ids=["fail-then-pass", "pass-then-fail"])
@pytest.mark.parametrize("case,dev", [("C-HEALTH", "dev-b"), ("C-ENVIRONMENT", None)])
def test_conflicting_duplicates_in_either_insertion_order_are_rejected(w, order, case, dev):
    rows = [(v, "runner" if a == "device" and dev is None else a) for v, a in order]
    _duplicate(w, w.final, case, dev, rows)
    au = audit(w)
    inst = f"{case}/{dev or '(run)'}"
    assert any(f"run {w.final} {inst}: 3 results for one instance" in v for v in au["A19"]["violations"])
    assert any(f"{inst} latest fail/" in v and f"(run {w.final})" in v for v in au["A4"]["violations"])
    assert au["A18"]["run"] == w.final, "the conflicting run must not be skipped in favour of an older one"
    assert any(f"duplicate {case}" in v for v in au["A18"]["violations"])
    assert (dev or "dev-a") not in db.commissioned_devices(w.conn, w.final)


def test_identical_pass_duplicate_is_still_ambiguous(w):
    _duplicate(w, w.final, "C-READ-CLOCK", "dev-a", [("pass", "none")])
    # the bare duplicate row also has no plan slot (A23) and no evidence chain or capture of its own (A24, A20)
    assert violated(w) == {"A18", "A19", "A20", "A23", "A24"}
    assert db.commissioned_devices(w.conn, w.final) == ["dev-b"]
    text = report.commissioning_section(w.conn)
    assert f"Run **{w.final}**: **AMBIGUOUS** commissioning run (11/11 required instances executed; 2 results for 1 " \
           "duplicated instance(s))" in text


def test_conflicting_duplicate_in_a_fault_run_is_rejected(w):
    _duplicate(w, w.fault, "FT-F1-STOPPED", "dev-a", [("fail", "device")])
    au = audit(w)
    assert {"A4", "A19"} <= violated(w)
    assert any("FT-F1-STOPPED/dev-a latest fail/device" in v for v in au["A4"]["violations"])
    rows = report.q(w.conn, report.LATEST_PER_CASE, "REQ-01")[0]
    assert [r[5] for r in rows if r[0] == "FT-F1-STOPPED"] == ["pass", "fail"]     # traceability shows both


@pytest.mark.parametrize("case,dev,why", [("C-ENVIRONMENT", "dev-a", "run-level case recorded for a device"),
                                          ("C-HEALTH", None, "per-device case recorded without a device")])
def test_malformed_instance_is_rejected(w, case, dev, why):
    result(w.conn, w.final, case, dev)
    assert any(why in v for v in audit(w)["A19"]["violations"])


def test_partial_latest_baseline_falls_back_without_commissioning(w):
    part = baseline(w.conn, skip={("C-GATEWAY", "dev-b")})
    au = audit(w)
    assert not violated(w) and au["A18"]["run"] == w.final
    # per device (F-01 rule): dev-a's own and every run-level instance are complete; dev-b lacks one
    assert db.commissioned_devices(w.conn, part) == ["dev-a"]
    assert db.commissioning_gaps(w.conn, part)["dev-b"] == "missing C-GATEWAY/dev-b"
    assert "PARTIAL" in report.commissioning_section(w.conn)


# ---------------------------------------------------------------- R-02: capture-flow evidence

def _a17(w):
    return audit(w)["A17"]["violations"]


@pytest.mark.parametrize("side", ["field", "ctl"])
def test_missing_one_side_of_a_required_two_sided_capture_is_rejected(w, side):
    w.conn.execute("DELETE FROM capture_flows WHERE result_id=? AND capture=?", (w.f3, side))
    assert _a17(w) == [f"run{w.fault} FT-F3-WRONG-PORT/dev-a: [I8.1] {side} capture has no record of dialled flow {F3_BPF} "
                       "(dialled flow must be on the wire)"]


def test_missing_every_flow_record_is_rejected(w):
    w.conn.execute("DELETE FROM capture_flows WHERE result_id=?", (w.health,))
    assert len(_a17(w)) == 1 and "ctl capture has no record of dialled flow tcp and host 10.77.2.11 and port 5020 " \
                                  f"and port {w.health_lport}" in _a17(w)[0]


def test_expectedness_is_derived_not_trusted(w):
    w.conn.execute("UPDATE capture_flows SET expected=0, packets=0 WHERE result_id=?", (w.f3,))
    au = audit(w)
    assert [v.split(": ", 1)[1] for v in au["A17"]["violations"]] == [
        f"[I8.1] {c} record of {F3_BPF} says expected=0, its exchanges say 1 (dialled flow must be on the wire)"
        for c in ("ctl", "field")]
    assert all("record says 0 packets" in v for v in au["A20"]["violations"])     # and the bytes say otherwise


def test_retargeted_filter_and_unaccounted_records_are_rejected(w):
    w.conn.execute("UPDATE capture_flows SET filter='tcp and host 10.77.2.11 and port 5020' WHERE result_id=?", (w.f3,))
    v = _a17(w)
    assert sum("has no record of dialled flow" in x for x in v) == 2
    assert sum("is not accounted for by the case's dialled flows and captures" in x for x in v) == 2


def test_forged_no_packet_justifications_are_rejected(w):
    """'Nothing was sent' must agree with the exchange's own classification: ENETUNREACH only with NO_ROUTE, no
    address only after a failed resolve (contract I6, checked on every exchange of a current result: A24)."""
    w.conn.execute("UPDATE exchanges SET os_error='ENETUNREACH' WHERE attempt_id IN "
                   "(SELECT attempt_id FROM attempts WHERE result_id=?)", (w.f3,))
    w.conn.execute("UPDATE capture_flows SET expected=0 WHERE result_id=?", (w.f3,))
    v = audit(w)["A24"]["violations"]
    assert any("[I6] attempt 1 exchange 1: ENETUNREACH (nothing sent) classified CONN_REFUSED" in x for x in v), v
    w.conn.execute("UPDATE exchanges SET addr=NULL, os_error='ECONNREFUSED' WHERE attempt_id IN "
                   "(SELECT attempt_id FROM attempts WHERE result_id=?)", (w.f3,))
    w.conn.execute("UPDATE capture_flows SET filter='(none: port 5021, no address)', packets=NULL WHERE result_id=?",
                   (w.f3,))
    v = audit(w)["A24"]["violations"]
    assert any("[I6] attempt 1 exchange 1: no address, but not a failed resolve (connect CONN_REFUSED)" in x
               for x in v), v


def test_legitimate_no_packet_cases_are_accepted_with_their_reason(w):
    rows = w.conn.execute("SELECT r.case_id, f.capture, f.expected, f.packets, f.detail FROM capture_flows f "
                          "JOIN results r USING (result_id) WHERE r.result_id IN (?, ?) ORDER BY 1, 2", (w.f5, w.f7))
    assert [tuple(r) for r in rows] == [
        ("FT-F5-NO-ROUTE", "ctl", 0, 0, "ENETUNREACH: connect failed locally, nothing is sent"),
        ("FT-F5-NO-ROUTE", "field", 0, 0, "ENETUNREACH: connect failed locally, nothing is sent"),
        ("FT-F7-NAME-MISSING", "ctl", 0, None, "no address (resolve gaierror:-3): nothing can be sent"),
        ("FT-F7-NAME-MISSING", "field", 0, None, "no address (resolve gaierror:-3): nothing can be sent")]
    assert "A17" not in violated(w) and "A20" not in violated(w)


def test_current_mutant_run_flows_are_checked(w):
    w.conn.execute("DELETE FROM capture_flows WHERE result_id=?", (w.mutant,))
    assert any(f"run{w.runs['mutants'][1]} C-IDENTIFY/dev-a: [I8.1] ctl capture has no record" in x for x in _a17(w))


def test_zero_packet_expected_flow_is_rejected_in_any_fair_run_but_superseded_runs_are_not_current(w):
    run = db.start_run(w.conn, kind="fault", git_sha="0123456789abcdef0123456789abcdef01234567", git_dirty=0,
                       clean_env=1, runner_host="unit")
    db.put_env(w.conn, run, env_ok())
    new = result(w.conn, run, "FT-F3-WRONG-PORT", "dev-a", observed="CONN_REFUSED", expected="CONN_REFUSED", fault="F3")
    db.add_fault_event(w.conn, run_id=run, result_id=new, fault_id="F3", vm="witness-ctl", applied_at=db.utcnow(),
                       removed_at=db.utcnow(), removal_verified=True, detail="fixture")
    wire(w.conn, w.root, new, addr="10.77.2.11", port=5021, category="CONN_REFUSED", stage="connect",
         err="ECONNREFUSED", detail="ECONNREFUSED")
    db.finish_run(w.conn, run)
    w.conn.execute("DELETE FROM capture_flows WHERE result_id=? AND capture='field'", (w.f3,))   # superseded: not current
    assert "A17" not in violated(w)
    w.conn.execute("UPDATE capture_flows SET packets=0 WHERE result_id=? AND capture='ctl'", (w.f3,))
    assert _a17(w) == [f"run{w.fault} FT-F3-WRONG-PORT/dev-a: ctl capture holds 0 packets of {F3_BPF}"]


def test_latest_result_recorded_before_the_capture_flow_check_is_listed(w):
    w.conn.execute("UPDATE schema_migrations SET applied_at='2999-01-01T00:00:00.000Z' WHERE version=4")
    v = _a17(w)
    assert f"run{w.fault} FT-F3-WRONG-PORT/dev-a: [I8.1] latest fair result has no capture-flow record (recorded " \
           "before the F-07 check)" in v


# ---------------------------------------------------------------- R-02: the bytes behind the records

def _a20(w, **kw):
    return audit(w, **kw)["A20"]["violations"]


def test_flow_metadata_without_packets_in_the_capture_is_rejected(w):
    p = w.f3_paths["field"]
    p.write_bytes(pcap_bytes([]))
    reindex(w.conn, w.root, p)                          # even with an index rewritten to match the file
    assert "A17" not in violated(w)                     # the records alone look complete
    assert _a20(w) == [f"run{w.fault} FT-F3-WRONG-PORT/dev-a: [I9] {p.relative_to(w.root)} holds no packet of dialled "
                       f"flow {F3_BPF} (the bytes, recounted)",
                       f"run{w.fault} FT-F3-WRONG-PORT/dev-a: [I9] field record says 2 packets of {F3_BPF}, "
                       f"{p.relative_to(w.root)} holds 0"]


def test_gateway_polls_do_not_stand_in_for_the_runners_connection(w):
    """c335c84's defect class: the capture holds the device's address:port only from the gateway's polls."""
    p = w.health_paths["ctl"]
    p.write_bytes(pcap_bytes(flow_frames("10.77.2.11", 5020, 51000)))
    reindex(w.conn, w.root, p)
    assert any(f"holds no packet of dialled flow tcp and host 10.77.2.11 and port 5020 and port {w.health_lport}" in v
               for v in _a20(w))


def test_recorded_count_must_equal_the_bytes(w):
    w.conn.execute("UPDATE capture_flows SET packets=7 WHERE result_id=? AND capture='ctl'", (w.f3,))
    assert _a20(w) == [f"run{w.fault} FT-F3-WRONG-PORT/dev-a: [I9] ctl record says 7 packets of {F3_BPF}, "
                       f"{w.f3_paths['ctl'].relative_to(w.root)} holds 2"]


def test_missing_evidence_file_is_rejected(w):
    w.health_paths["ctl"].unlink()
    assert _a20(w) == [f"run{w.final} C-HEALTH/dev-a: [I9] {w.health_paths['ctl'].relative_to(w.root)}: missing"]


def test_hash_mismatch_is_rejected(w):
    p = w.health_paths["ctl"]
    data = p.read_bytes()
    p.write_bytes(data[:-1] + bytes([data[-1] ^ 0xFF]))
    v = _a20(w)
    assert v == [f"run{w.final} C-HEALTH/dev-a: [I9] {p.relative_to(w.root)}: differs from its index "
                 f"({p.stat().st_size} B now, {p.stat().st_size} B recorded)"]


def test_capture_file_that_is_not_indexed_is_rejected(w):
    w.conn.execute("DELETE FROM evidence WHERE result_id=? AND kind='pcap-field'", (w.f3,))
    assert _a20(w) == [f"run{w.fault} FT-F3-WRONG-PORT/dev-a: [I7] 0 indexed field capture files; exactly one is "
                       "required"]


def test_unparseable_capture_is_rejected(w):
    p = w.f3_paths["ctl"]
    p.write_bytes(b"\x0a\x0d\x0d\x0a" + bytes(60))
    reindex(w.conn, w.root, p)
    assert any("cannot be verified: not a classic pcap" in v for v in _a20(w))


def test_without_an_evidence_root_nothing_is_verified(w):
    assert _a20(w, root=None) == ["[I9] evidence bytes not verified: no evidence root given (python3 -m "
                                  "runner.analysis --db DB --evidence-root DIR)"]
    assert violated(w, root=None) == {"A20", "A23"}      # A23: plan files and case directories not verified either


# ---------------------------------------------------------------- the sets the SQL derives requirements from

def _delete_results(conn, where, args=()):
    ids = [r[0] for r in conn.execute(f"SELECT result_id FROM results WHERE {where}", args)]
    q = ",".join(map(str, ids)) or "NULL"
    conn.execute(f"DELETE FROM exchanges WHERE attempt_id IN (SELECT attempt_id FROM attempts WHERE result_id IN ({q}))")
    for t in ("attempts", "checks", "evidence", "measurements", "capture_flows", "fault_events"):
        conn.execute(f"DELETE FROM {t} WHERE result_id IN ({q})")
    conn.execute(f"DELETE FROM results WHERE result_id IN ({q})")


def _delete_plan(conn, where):
    conn.execute(f"DELETE FROM run_plan WHERE {where}")


def test_deleting_a_device_does_not_shrink_what_commissioning_requires(w):
    _delete_results(w.conn, "device_id='dev-b'")
    _delete_plan(w.conn, "device_id='dev-b'")
    w.conn.execute("DELETE FROM devices WHERE device_id='dev-b'")
    au = audit(w)
    assert au["A21"]["violations"] == ["device dev-b: missing from the database"]
    # every baseline lost dev-b's results and plan rows, so none selected the complete inventory set: A18 is violated
    # (standalone commissioning names dev-b: tests/contract), and the case directories expose the deleted results
    assert au["A18"]["violations"] == ["no fair baseline executed the complete commissioning set"]
    assert any(f"run-{w.final}/C-IDENTIFY__dev-b/ (an executed case) has no result" in v for v in au["A23"]["violations"])
    assert "inventory device absent from the devices table" in db.commissioning_gaps(w.conn, w.final)["dev-b"]


def test_deleting_a_case_or_requirement_does_not_shrink_what_traceability_requires(w):
    _delete_results(w.conn, "case_id='FT-F13-SKEW'")
    _delete_plan(w.conn, "case_id='FT-F13-SKEW'")
    w.conn.execute("DELETE FROM case_requirements WHERE case_id='FT-F13-SKEW'")
    w.conn.execute("DELETE FROM cases WHERE case_id='FT-F13-SKEW'")
    v = audit(w)["A21"]["violations"]
    assert "case FT-F13-SKEW: missing from the database" in v and \
           "case->requirement ('FT-F13-SKEW', 'REQ-04'): missing from the database" in v


def test_rewritten_prediction_is_rejected(w):
    w.conn.execute("UPDATE faults SET expected_category='PASS' WHERE fault_id='F3'")
    assert "fault F3: database ('F3', 'inventory-port', 'PASS') <> source ('F3', 'inventory-port', 'CONN_REFUSED')" \
        in audit(w)["A21"]["violations"]
    w.conn.execute("UPDATE faults SET expected_category='CONN_REFUSED' WHERE fault_id='F3'")
    w.conn.execute("UPDATE results SET expected_category='PASS', observed_category='PASS' WHERE result_id=?", (w.f3,))
    assert audit(w)["A5"]["violations"] == ["F3"]       # a result's own prediction rewritten to match its observation


def test_fault_result_without_a_recorded_application_is_rejected(w):
    w.conn.execute("DELETE FROM fault_events WHERE result_id=?", (w.f3,))
    assert audit(w)["A9"]["violations"] == [f"run {w.fault} FT-F3-WRONG-PORT/dev-a pass: fault-case result without a "
                                            "recorded fault application"]

