"""The section 8 SQL analyses, the mutant/baseline queries and the acceptance assertions, on fixture data
with known answers (the same SQL runs over the real store in runner/report.py)."""
import statistics
from pathlib import Path

import pytest

from runner import analysis as A, catalog, db, report
from scripts.lib import inventory

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "a.db")
    db.sync_reference(c, requirements=db.requirements_from_md(REPO / "docs/requirements.md"),
                      devices=inventory.load(REPO / "inventory.yaml")["devices"], cases=catalog.CASES,
                      faults=catalog.FAULTS, mutants=catalog.MUTANTS)
    yield c
    c.close()


def run(conn, kind="baseline", clean=1, finished=True, mutant=None, env=None):
    rid = db.start_run(conn, kind=kind, git_sha="s", git_dirty=0, clean_env=clean, runner_host="t", mutant_id=mutant)
    if env:
        db.put_env(conn, rid, env)
    if finished:
        db.finish_run(conn, rid)
    return rid


def res(conn, rid, case="C-IDENTIFY", dev="dev-a", verdict="pass", attribution="none", observed="PASS",
        fault=None, expected="PASS", detection=None, first=None, attempts=1, latency=1.0, preflight="green"):
    return db.insert_result(conn, run_id=rid, case_id=case, device_id=dev, fault_id=fault, expected=expected,
                            observed=observed, first_attempt=first or observed, attempts=attempts, latency_ms=latency,
                            detection_ms=detection, verdict=verdict, attribution=attribution, detail="",
                            preflight=preflight, evidence_path=f"run-{rid}/{case}__{dev}", observed_at=db.utcnow(),
                            duration_ms=1.0)


@pytest.mark.parametrize("values", [[5.0], [3.0, 1.0], [9.0, 1.0, 5.0], [4.0, 1.0, 3.0, 2.0], [7.0, 7.0, 1.0, 100.0, 2.0]])
def test_q4_sql_median_equals_statistics_median(conn, values):
    for v in values:
        r = run(conn, kind="fault")
        res(conn, r, case="FT-F1-STOPPED", fault="F1", expected="CONN_REFUSED", observed="CONN_REFUSED", detection=v)
    unfair = run(conn, kind="fault", clean=0)       # excluded: not fairly tested
    res(conn, unfair, case="FT-F1-STOPPED", fault="F1", expected="CONN_REFUSED", observed="CONN_REFUSED", detection=1e6)
    rows, cols = A.rows(conn, A.Q4_DETECTION)
    assert cols == ["catalog_id", "fault_id", "case_id", "n", "min_ms", "median_ms", "max_ms"]
    assert rows == [("F1", "F1", "FT-F1-STOPPED", len(values), min(values), statistics.median(values), max(values))]


def test_q4_groups_runner_and_gateway_cases_separately(conn):
    r = run(conn, kind="fault")
    res(conn, r, case="FT-F1-STOPPED", fault="F1", observed="CONN_REFUSED", expected="CONN_REFUSED", detection=1.0)
    res(conn, r, case="GW-F1-UNREACHABLE", fault="F1", observed="CONN_REFUSED", expected="CONN_REFUSED", detection=900.0)
    assert [x[2] for x in A.rows(conn, A.Q4_DETECTION)[0]] == ["FT-F1-STOPPED", "GW-F1-UNREACHABLE"]


def test_q2_flags_only_differences_among_fair_baselines_and_honours_the_run_list(conn):
    a, b, c = run(conn), run(conn), run(conn)
    for r in (a, b, c):
        res(conn, r, case="C-HEALTH")
    res(conn, a, case="C-IDENTIFY")
    res(conn, b, case="C-IDENTIFY", verdict="fail", attribution="device", observed="READ_TIMEOUT")
    bad = run(conn, clean=0)                                  # unfair run: never evidence of flakiness
    res(conn, bad, case="C-HEALTH", verdict="error", attribution="infra", observed=None)
    rows, _ = A.rows(conn, A.Q2_FLAKY, runs=None)
    assert [(r[0], r[1], r[2], r[3]) for r in rows] == [("C-IDENTIFY", "dev-a", 2, 1)]
    assert A.rows(conn, A.Q2_FLAKY, runs=A.runs_param([a, c]))[0] == []


def test_q3_counts_mismatches_and_keeps_unfair_rows_visible(conn):
    r = run(conn, kind="fault")
    res(conn, r, case="FT-F4-WRONG-ADDR", fault="F4", expected="CONNECT_TIMEOUT", observed="CONNECT_TIMEOUT")
    res(conn, r, case="FT-F4-WRONG-ADDR", fault="F4", expected="CONNECT_TIMEOUT", observed="NO_ROUTE",
        verdict="fail", attribution="device")
    u = run(conn, kind="fault", finished=False)
    res(conn, u, case="FT-F4-WRONG-ADDR", fault="F4", expected="CONNECT_TIMEOUT", observed="NO_ROUTE",
        verdict="fail", attribution="device")
    rows = {r[3]: r[4:] for r in A.rows(conn, A.Q3_FAULT_MATCH)[0]}
    assert rows["CONNECT_TIMEOUT"] == (1, 0, 0, 0)
    assert rows["NO_ROUTE"] == (1, 1, 1, 0)


def test_q5_retry_only_pass_and_q6_infra(conn):
    r = run(conn)
    res(conn, r, case="C-HEALTH", verdict="fail", attribution="device", observed="PASS", first="READ_TIMEOUT", attempts=2)
    res(conn, r, case="C-READ-CLOCK", verdict="fail", attribution="device", observed="READ_TIMEOUT",
        first="READ_TIMEOUT", attempts=2)
    i = run(conn, clean=0)
    res(conn, i, verdict="error", attribution="infra", observed=None, preflight="red")
    assert [(x[3], x[5], x[6], x[7]) for x in A.rows(conn, A.Q5_RETRY)[0]] == [("C-HEALTH", "READ_TIMEOUT", "PASS", "fail")]
    assert len(A.rows(conn, A.Q5B_RETRIED)[0]) == 2
    q6 = A.rows(conn, A.Q6_INFRA)[0]
    assert [(x[0], x[5]) for x in q6] == [(i, 1)]


def test_mutant_summary_counts_only_valid_runs_and_never_infra(conn):
    m1 = run(conn, kind="mutant", mutant="M1")
    res(conn, m1, case="C-IDENTIFY", verdict="fail", attribution="device", observed="WRONG_IDENTITY")
    res(conn, m1, case="C-IDENTIFY", dev="dev-b")
    res(conn, m1, case="C-ENVIRONMENT", dev=None, verdict="fail", attribution="device", observed=None)
    m3_infra = run(conn, kind="mutant", mutant="M3")            # infra error: neither caught nor a valid run
    res(conn, m3_infra, case="C-IDENTIFY", verdict="error", attribution="infra", observed=None, preflight="red")
    m6a = run(conn, kind="mutant", mutant="M6")                 # passed everything: a false negative
    res(conn, m6a, case="C-IDENTIFY")
    m6b = run(conn, kind="mutant", mutant="M6")
    res(conn, m6b, case="C-HEALTH", verdict="fail", attribution="device", observed="PASS", first="READ_TIMEOUT",
        attempts=2)
    s = {r[0]: r for r in A.rows(conn, A.MUTANT_SUMMARY, mdev="dev-a")[0]}
    assert s["M1"][2:6] == (1, 1, 1, "CAUGHT") and s["M1"][6] == "REQ-01"
    assert s["M3"][2:6] == (1, 0, 0, "NOT TESTED")
    assert s["M6"][2:6] == (2, 2, 1, "CAUGHT (not every run)")
    assert s["M2"][5] == "NOT TESTED"
    runs = {r[0]: r for r in A.rows(conn, A.MUTANT_RUNS, mdev="dev-a")[0]}
    assert runs[m6b][-1] == "C-HEALTH:PASS(1st READ_TIMEOUT)"
    assert runs[m1][6] == 0 and runs[m1][7] == 1               # control device clean; run-level row apart
    assert s["M1"][8] == 0


def test_fresh_trials_need_distinct_restores_and_fair_runs(conn):
    def env(tag, boot):
        return {"provenance.witness-ctl": f"golden-restore id={tag} boot_id={boot}",
                "provenance.witness-field": f"golden-restore id={tag} boot_id={boot}"}
    a = run(conn, env=env("r1", "b1"))
    run(conn, env=env("r1", "b2"))                               # same restore, rebooted: not independent
    run(conn, clean=0, env=env("r2", "b3"))                       # unfair
    c = run(conn, env=env("r3", "b4"))
    run(conn, env={"provenance.witness-ctl": "long-lived VM (no golden-restore record) boot_id=x",
                   "provenance.witness-field": "long-lived VM (no golden-restore record) boot_id=x"})
    assert A.fresh_trial_runs(conn, "witness-ctl", "witness-field") == [a, c]
    # restore identifiers alone are not baselines (independent audit F-06): these runs have no results
    au = {x["id"]: x for x in A.audit(conn, min_fresh_baselines=2)}
    assert not au["A14-fresh-baselines"]["ok"] and au["A14-fresh-baselines"]["runs"] == []
    assert any(f"run {a}: dev-a: " in v and "missing C-IDENTIFY/dev-a" in v for v in au["A14-fresh-baselines"]["violations"])
    # complete, passing fresh-clone baselines are counted
    from storefix import baseline
    good = [baseline(conn, provenance=p) for p in ("r7", "r8")]
    au = {x["id"]: x for x in A.audit(conn, min_fresh_baselines=2)}
    assert au["A14-fresh-baselines"]["ok"] and au["A14-fresh-baselines"]["runs"] == good


def test_audit_reports_violations_not_prose(conn):
    au = {x["id"]: x for x in A.audit(conn)}
    assert au["A1-req-has-case"]["ok"] and au["A2-case-has-req"]["ok"]
    assert not au["A3-case-executed"]["ok"] and "C-IDENTIFY" in au["A3-case-executed"]["violations"]
    assert set(au["A6-category-observed-live"]["violations"]) == set(A.CATEGORIES)
    assert au["A12-every-mutant-tested"]["violations"] == ["M1", "M2", "M3", "M4", "M5", "M6"]
    assert not au["A14-fresh-baselines"]["ok"]


def test_report_files_and_mutant_section(conn):
    m = run(conn, kind="mutant", mutant="M4")
    res(conn, m, case="C-IDENTIFY", verdict="fail", attribution="device", observed="MALFORMED")
    out = report.build_all(conn)
    assert set(out) == {"commissioning-report.md", "traceability.md", "baseline-report.md", "fault-report.md",
                        "mutant-report.md", "acceptance-audit.md", "acceptance-audit.json"}
    assert "Mutants caught: **1/6**" in out["mutant-report.md"]
    assert "[run-1/C-IDENTIFY__dev-a](../evidence/run-1/C-IDENTIFY__dev-a/)" in out["mutant-report.md"]
    # a mutant run never shows up as the latest commissioning evidence or commissions anything
    assert "No fair baseline run: **no device is commissioned.**" in out["commissioning-report.md"]
    assert "not physical hardware" in out["traceability.md"]
