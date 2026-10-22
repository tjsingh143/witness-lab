"""SQLite schema/migration, reference sync, constraints, retry/verdict logic."""
import sqlite3
from pathlib import Path

import pytest

from runner import catalog, db
from runner.cases import Attempt, decide, decide_observed, with_retry
from runner.classify import Classification, Observation
from scripts.lib import inventory

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "w.db")
    reqs = db.requirements_from_md(REPO / "docs/requirements.md")
    inv = inventory.load(REPO / "inventory.yaml")
    db.sync_reference(c, requirements=reqs, devices=inv["devices"], cases=catalog.CASES, faults=catalog.FAULTS)
    yield c
    c.close()


def att(no, *cats, preds=None, restart=False):
    a = Attempt(attempt_no=no, predicates=preds or {}, restart_observed=restart)
    for cat in cats:
        o = Observation(host="h", port=1, cmd="IDENTIFY", req_id=1)
        a.exchanges.append((o, Classification(cat, "x", f"d-{cat}")))
    return a


def test_migration_idempotent_and_fk_on(tmp_path):
    p = tmp_path / "m.db"
    c1 = db.connect(p)
    c1.close()
    c2 = db.connect(p)
    assert c2.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    assert c2.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == len(db.MIGRATIONS) == 5
    assert c2.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_v1_database_migrates_to_v5_keeping_rows(tmp_path):
    """A Phase 2 (v1) results DB gains measurements + exchanges.local_port (v2), the rebuilt runs table
    with kind 'mutant' (v3), attempts.outcome/predicates + capture_flows (v4) and run_plan (v5) without losing rows."""
    p = tmp_path / "v1.db"
    raw = sqlite3.connect(p)
    raw.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, description TEXT NOT NULL, applied_at TEXT NOT NULL)")
    for stmt in (x.strip() for x in db._V1.split(";")):
        if stmt:
            raw.execute(stmt)
    raw.execute("INSERT INTO schema_migrations VALUES (1, 'v1', 'x')")
    raw.execute("INSERT INTO runs (started_at, kind, clean_env) VALUES ('t', 'baseline', 1)")
    raw.commit()
    raw.close()
    c = db.connect(p)
    assert c.execute("SELECT count(*) FROM runs").fetchone()[0] == 1
    assert c.execute("PRAGMA user_version").fetchone()[0] == 5
    assert c.execute("SELECT count(*) FROM run_plan").fetchone()[0] == 0
    assert "local_port" in {r[1] for r in c.execute("PRAGMA table_info(exchanges)")}
    assert {"outcome", "predicates"} <= {r[1] for r in c.execute("PRAGMA table_info(attempts)")}
    assert c.execute("SELECT count(*) FROM capture_flows").fetchone()[0] == 0
    assert c.execute("SELECT count(*) FROM measurements").fetchone()[0] == 0
    assert "mutant_id" in {r[1] for r in c.execute("PRAGMA table_info(runs)")}


def test_v5_run_plan_records_the_declared_selection(conn):
    """Final independent verification FV-01 class: the run's selection is recorded before its first case, as rows and
    as the canonical document the live session indexes as session/plan.json."""
    import json
    run = db.start_run(conn, kind="baseline", git_sha=None, git_dirty=None, clean_env=1, runner_host="t")
    text = db.record_plan(conn, run, [("C-HEALTH", "dev-b"), ("C-ENVIRONMENT", None), ("C-HEALTH", "dev-a")])
    rows = conn.execute("SELECT case_id, device_id FROM run_plan WHERE run_id = ? ORDER BY case_id, device_id",
                        (run,)).fetchall()
    assert [tuple(r) for r in rows] == [("C-ENVIRONMENT", None), ("C-HEALTH", "dev-a"), ("C-HEALTH", "dev-b")]
    assert json.loads(text)["instances"] == [["C-ENVIRONMENT", None], ["C-HEALTH", "dev-a"], ["C-HEALTH", "dev-b"]]
    with pytest.raises(sqlite3.IntegrityError):              # one row per instance, run-level ones included
        db.record_plan(conn, run, [("C-ENVIRONMENT", None)])
    with pytest.raises(sqlite3.IntegrityError):              # only catalogued cases and inventoried devices
        db.record_plan(conn, run, [("C-NOPE", "dev-a")])


@pytest.mark.parametrize("sql", ["DELETE FROM run_plan", "DELETE FROM results", "DELETE FROM exchanges",
                                 "UPDATE capture_flows SET packets = 999", "UPDATE evidence SET sha256 = 'x'",
                                 "DELETE FROM runs"])
def test_v5_recorded_evidence_is_append_only(conn, sql):
    """Accidental deletion or rewrite through SQLite is refused (defence in depth: acceptance does not rely on it)."""
    run = db.start_run(conn, kind="baseline", git_sha=None, git_dirty=None, clean_env=1, runner_host="t")
    db.record_plan(conn, run, [("C-HEALTH", "dev-a")])
    rid = db.insert_result(conn, run_id=run, case_id="C-HEALTH", device_id="dev-a", fault_id=None, expected="PASS",
                           observed="PASS", first_attempt="PASS", attempts=1, latency_ms=1.0, detection_ms=None,
                           verdict="pass", attribution="none", detail="", preflight="green", evidence_path="x",
                           observed_at=db.utcnow(), duration_ms=1.0)
    o = Observation(host="dev-a.lab", port=5020, cmd="HEALTH", req_id=1, addr="10.77.2.11")
    db.insert_attempt(conn, rid, 1, "PASS", "x", "", db.utcnow(), 1.0, [(o, Classification("PASS", "x"))], outcome="ok")
    db.add_capture_flow(conn, rid, capture="ctl", bpf="tcp and host 10.77.2.11 and port 5020", expected=True,
                        packets=4, detail="")
    conn.execute("INSERT INTO evidence (run_id, result_id, kind, path, sha256, bytes, created_at) VALUES "
                 "(?, ?, 'pcap', 'p', 's', 1, 't')", (run, rid))
    db.set_postflight(conn, rid, True)                        # the runner's own later update stays allowed
    db.finish_run(conn, run)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute(sql)


def test_v2_to_v3_rebuild_keeps_rows_and_foreign_keys(tmp_path):
    """The v3 runs rebuild (foreign keys off, copy, drop, rename) keeps every child row pointing at its run,
    keeps foreign keys enforced afterwards, and adds the mutant-kind constraint."""
    p = tmp_path / "v2.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, description TEXT NOT NULL, applied_at TEXT NOT NULL)")
    for v, sql in ((1, db._V1), (2, db._V2)):
        for stmt in (x.strip() for x in sql.split(";")):
            if stmt:
                c.execute(stmt)
        c.execute("INSERT INTO schema_migrations VALUES (?, 'x', 'x')", (v,))
    c.execute("INSERT INTO runs (run_id, started_at, kind, clean_env, notes) VALUES (7, 't', 'fault', 1, 'n')")
    c.execute("INSERT INTO cases VALUES ('C-X', 'fault', 'd')")
    c.execute("INSERT INTO results (run_id, case_id, verdict, attribution, preflight, observed_at) "
              "VALUES (7, 'C-X', 'pass', 'none', 'green', 't')")
    c.execute("INSERT INTO environment VALUES (7, 'k', 'v')")
    c.commit()
    c.close()
    m = db.connect(p)
    assert m.execute("SELECT run_id, kind, notes, mutant_id FROM runs").fetchall()[0][:] == (7, "fault", "n", None)
    assert m.execute("SELECT count(*) FROM results r JOIN runs USING (run_id)").fetchone()[0] == 1
    assert m.execute("PRAGMA foreign_key_check").fetchall() == []
    assert m.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):          # FK still enforced on the rebuilt parent
        m.execute("INSERT INTO environment VALUES (99, 'k', 'v')")
    with pytest.raises(sqlite3.IntegrityError):          # kind=mutant needs a mutant id
        m.execute("INSERT INTO runs (started_at, kind, clean_env) VALUES ('t', 'mutant', 1)")
    with pytest.raises(sqlite3.IntegrityError):          # ... which must exist in mutants
        m.execute("INSERT INTO runs (started_at, kind, clean_env, mutant_id) VALUES ('t', 'mutant', 1, 'M9')")
    assert "kind = 'mutant'" in m.execute("SELECT sql FROM sqlite_master WHERE name='runs'").fetchone()[0]


def test_requirements_parsed_from_doc(conn):
    ids = [r[0] for r in conn.execute("SELECT req_id FROM requirements ORDER BY 1")]
    assert ids == [f"REQ-{i:02d}" for i in range(1, 11)]


def test_every_case_traces_to_a_requirement(conn):
    orphans = conn.execute("SELECT case_id FROM cases WHERE case_id NOT IN (SELECT case_id FROM case_requirements)").fetchall()
    assert orphans == []
    # many-to-many: FT-F2-HUNG proves REQ-07 and REQ-06
    assert {r[0] for r in conn.execute("SELECT req_id FROM case_requirements WHERE case_id='FT-F2-HUNG'")} == {"REQ-06", "REQ-07"}


def _run(conn, kind="baseline"):
    return db.start_run(conn, kind=kind, git_sha="abc", git_dirty=0, clean_env=1, runner_host="t")


def _res(conn, run, case="C-IDENTIFY", dev="dev-a", verdict="pass", attribution="none", observed="PASS",
         preflight="green", fault=None):
    return db.insert_result(conn, run_id=run, case_id=case, device_id=dev, fault_id=fault, expected="PASS",
                            observed=observed, first_attempt=observed, attempts=1, latency_ms=1.0, detection_ms=None,
                            verdict=verdict, attribution=attribution, detail="", preflight=preflight,
                            evidence_path=None, observed_at=db.utcnow(), duration_ms=1.0)


def test_constraints_device_attribution_needs_green_preflight(conn):
    run = _run(conn)
    with pytest.raises(sqlite3.IntegrityError):
        _res(conn, run, verdict="fail", attribution="device", observed="CONN_REFUSED", preflight="red")
    with pytest.raises(sqlite3.IntegrityError):
        _res(conn, run, verdict="pass", attribution="device")
    with pytest.raises(sqlite3.IntegrityError):
        _res(conn, run, observed="TIMEOUT")          # not one of the 11 categories
    with pytest.raises(sqlite3.IntegrityError):
        _res(conn, run, case="NO-SUCH-CASE")         # foreign key enforced


def test_attempts_and_exchanges_rows(conn):
    run = _run(conn)
    rid = _res(conn, run)
    a = att(1, "PASS", "PASS")
    a.exchanges[0][0].local_port = 40123
    db.insert_attempt(conn, rid, 1, a.category, "latency", "", db.utcnow(), 1.0, a.exchanges)
    assert conn.execute("SELECT count(*) FROM exchanges").fetchone()[0] == 2
    assert [r[0] for r in conn.execute("SELECT local_port FROM exchanges ORDER BY ord")] == [40123, None]


def test_measurements_unique_per_result(conn):
    run = _run(conn)
    rid = _res(conn, run)
    db.add_measurement(conn, rid, "gateway_detection_ms", 1234.5, bound=6000)
    db.add_measurement(conn, rid, "never_detected_ms", None, bound=6000)
    with pytest.raises(sqlite3.IntegrityError):
        db.add_measurement(conn, rid, "gateway_detection_ms", 1.0)
    assert tuple(conn.execute("SELECT value, bound, clock FROM measurements WHERE name='gateway_detection_ms'").fetchone()) \
        == (1234.5, 6000.0, "ctl-monotonic")


def test_fault_runs_never_commission(conn):
    run = _run(conn, kind="fault")
    _res(conn, run, case="C-IDENTIFY", dev="dev-a")
    db.finish_run(conn, run)
    assert db.commissioned_devices(conn, run) == []


# ---------------------------------------------------------------- verdict / retry

def test_decide_pass_fail_error():
    assert decide([att(1, "PASS")], "PASS", preflight_green=True).verdict == "pass"
    d = decide([att(1, "PASS_SLOW")], "PASS", preflight_green=True)
    assert (d.verdict, d.attribution) == ("fail", "device")
    d = decide([att(1, "PASS")], "PASS", preflight_green=False)
    assert (d.verdict, d.attribution) == ("error", "infra")
    d = decide([att(1, None)], "PASS", preflight_green=True)
    assert (d.verdict, d.attribution) == ("error", "runner")
    d = decide([att(1, "PASS", restart=True)], "PASS", preflight_green=True)
    assert (d.verdict, d.attribution) == ("error", "infra")


def test_decisive_exchange_decides_recovery_attempts():
    a = att(1, "PASS", "CONN_RESET", "CONN_REFUSED", "PASS", "PASS")
    assert a.category == "CONN_RESET"                 # default: first non-pass decides
    a.decisive = 3                                   # F12: the first PASS HEALTH after the restart decides
    assert a.category == "PASS" and a.deciding.detail == "d-PASS"
    assert decide([a], "PASS", preflight_green=True).verdict == "pass"


def test_decide_observed_for_gateway_cases():
    assert decide_observed("CONN_REFUSED", "CONN_REFUSED", preflight_green=True, predicates={"x": True}).verdict == "pass"
    d = decide_observed("CONN_REFUSED", "CONN_REFUSED", preflight_green=True, predicates={"within_3P": False})
    assert (d.verdict, d.attribution) == ("fail", "device") and "within_3P" in d.detail
    assert decide_observed("PASS", "CONN_REFUSED", preflight_green=False, predicates={}).attribution == "infra"
    assert decide_observed(None, "CONN_REFUSED", preflight_green=True, predicates={}).attribution == "runner"


def test_fault_case_expected_failure_is_a_pass_verdict():
    d = decide([att(1, "CONN_REFUSED")], "CONN_REFUSED", preflight_green=True)
    assert (d.verdict, d.attribution) == ("pass", "none")


def test_predicate_failure_with_pass_category():
    d = decide([att(1, "PASS", preds={"status_ok": False})], "PASS", preflight_green=True)
    assert d.verdict == "fail" and "status_ok" in d.detail


def test_flake_is_fail_and_first_attempt_kept():
    seq = iter([att(1, "READ_TIMEOUT"), att(2, "PASS")])
    attempts = with_retry(lambda no: next(seq))
    assert [a.category for a in attempts] == ["READ_TIMEOUT", "PASS"]
    d = decide(attempts, "PASS", preflight_green=True)
    assert d.verdict == "fail" and d.detail.startswith("FLAKE")


def test_at_most_one_retry_and_no_retry_when_disallowed():
    calls = []

    def make(no):
        calls.append(no)
        return att(no, "CONN_REFUSED")
    assert len(with_retry(make)) == 2 and calls == [1, 2]
    calls.clear()
    assert len(with_retry(make, allow_retry=False)) == 1 and calls == [1]


def test_report_from_db(conn, tmp_path):
    from runner import report
    run = _run(conn)
    rid = _res(conn, run)
    a = att(1, "PASS")
    db.insert_attempt(conn, rid, 1, "PASS", "latency", "", db.utcnow(), 1.0, a.exchanges)
    pcap = tmp_path / "ev" / "c.pcap"
    pcap.parent.mkdir()
    pcap.write_bytes(b"\0" * 24)                      # header only: an empty capture
    db.add_evidence(conn, run_id=run, result_id=rid, kind="pcap", root=tmp_path / "ev", path=pcap)
    flake = db.insert_result(conn, run_id=run, case_id="C-HEALTH", device_id="dev-a", fault_id=None, expected="PASS",
                             observed="PASS", first_attempt="READ_TIMEOUT", attempts=2, latency_ms=1.0,
                             detection_ms=None, verdict="fail", attribution="device", detail="FLAKE",
                             preflight="green", evidence_path=None, observed_at=db.utcnow(), duration_ms=1.0)
    db.finish_run(conn, run)
    db.add_measurement(conn, rid, "gateway_detection_ms", 7000.0, bound=6000)
    text = report.build(conn)
    assert "GAP: no case" not in text and "Traceability gaps (REQ without a case): **none**" in text
    assert "| 1 | baseline |  | C-HEALTH | dev-a | READ_TIMEOUT | PASS | fail |" in text   # Q5 lists the flake
    assert "| F13 | F13-skew | 0 | 0 | **NOT RUN** |" in text      # coverage shows faults with no result
    assert "| gateway_detection_ms | 7000.0 | ms | 6000.0 | NO |" in text   # over-bound measurement flagged
    assert "c.pcap | 24 |" in text                              # evidence-integrity check
    assert "not physical hardware" in text
    assert flake


def test_report_flags_a_requirement_without_cases(conn):
    from runner import report
    conn.execute("INSERT INTO requirements VALUES ('REQ-99', 'synthetic requirement with no case')")
    conn.commit()
    _run(conn)
    text = report.build(conn)
    assert "| REQ-99 | synthetic requirement with no case | **GAP: no case** | - |" in text
    assert "Traceability gaps (REQ without a case): **REQ-99**" in text


def test_unfinished_runs_marked_aborted(conn):
    killed = _run(conn)
    current = _run(conn)
    assert db.mark_aborted_runs(conn, current) == [killed]
    r = conn.execute("SELECT contaminated, notes FROM runs WHERE run_id=?", (killed,)).fetchone()
    assert r[0] == 1 and "aborted" in r[1]
    assert conn.execute("SELECT contaminated FROM runs WHERE run_id=?", (current,)).fetchone()[0] == 0
    db.finish_run(conn, current)
    assert db.mark_aborted_runs(conn, _run(conn)) == []          # marked once, not by every later run


def test_report_lists_evidence_that_no_longer_matches_its_hash(conn, tmp_path):
    """Remediation: FT-F12's second restart overwrote indexed evidence files; the report must show such files."""
    from runner import report
    run = _run(conn)
    rid = _res(conn, run)
    root = tmp_path / "ev"
    (root / "run-1").mkdir(parents=True)
    keep, change, gone = (root / "run-1" / n for n in ("keep.txt", "change.txt", "gone.txt"))
    for f in (keep, change, gone):
        f.write_text("original")
        db.add_evidence(conn, run_id=run, result_id=rid, kind="snapshot", root=root, path=f)
    change.write_text("overwritten by a later step")
    gone.unlink()
    db.finish_run(conn, run)
    bad = {r[3]: r[5] for r in report.evidence_mismatches(conn, root)}
    assert bad == {"run-1/change.txt": "differs (27 B now, 8 B recorded)", "run-1/gone.txt": "missing"}
    text = report.build_all(conn, root)["commissioning-report.md"]
    assert "missing or different: **2**" in text
    assert "Evidence files were not re-hashed" in report.build_all(conn)["commissioning-report.md"]
