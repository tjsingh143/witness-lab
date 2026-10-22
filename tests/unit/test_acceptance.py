"""Independent audit F-06 (and the acceptance parts of F-01/F-04/F-07/F-08): the acceptance assertions must hold on
a complete, passing store and FAIL on deliberately incomplete or failing stores, including the audit's two
counterexamples. Fixture stores (tests/unit/storefix.py), never lab evidence."""
import re
import shutil
import sqlite3
from pathlib import Path

import pytest

from runner import analysis as A, catalog, db, report
from storefix import CTL, DEVICES, FIELD, accepted_store, baseline, env_ok, finish, new_store, result

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def store(tmp_path):
    c = new_store(tmp_path / "acc.db")
    runs = accepted_store(c)
    ROOT[0] = tmp_path / "evidence"            # written by storefix (every result carries its evidence files)
    ROOT[0].mkdir(exist_ok=True)
    yield c, runs
    c.close()


ROOT = [None]      # the store fixture's evidence root


def audit(conn) -> dict:
    return {a["id"]: a for a in A.audit(conn, ctl=CTL, field=FIELD, evidence_root=ROOT[0])}


def failing(conn) -> set[str]:
    return {k for k, a in audit(conn).items() if not a["ok"]}


def test_complete_store_passes_every_assertion(store):
    conn, runs = store
    au = audit(conn)
    assert not failing(conn), {k: a["violations"][:3] for k, a in au.items() if not a["ok"]}
    assert au["A14-fresh-baselines"]["runs"] == runs["fresh"] and au["A18-commissioning-complete"]["run"] == runs["final"]
    assert len(au) == 24


def test_auditor_counterexample_1_missing_and_blank_environment(store):
    """Audit F-06: delete field kernel/distro/qdisc/nft, dev-b firmware, git_dirty and chrony.offset, blank python."""
    conn, _ = store
    conn.execute("DELETE FROM environment WHERE key IN ('kernel.witness-field','distro.witness-field',"
                 "'qdisc.witness-field','nft.witness-field','fw_version.dev-b','git_dirty','chrony.offset')")
    conn.execute("UPDATE environment SET value='' WHERE key='python'")
    conn.commit()
    v = audit(conn)["A13-environment-recorded"]
    assert not v["ok"]
    keys = {x.split(":", 1)[1].split("=")[0] for x in v["violations"]}
    assert keys == {"kernel.witness-field", "distro.witness-field", "qdisc.witness-field", "nft.witness-field",
                    "fw_version.dev-b", "git_dirty", "chrony.offset", "python"}


def test_auditor_counterexample_2_fresh_baselines_failing_health(store):
    """Audit F-06: every fresh-trial C-HEALTH changed to fail/device must break the five-successful-baselines claim."""
    conn, runs = store
    conn.execute("UPDATE results SET verdict='fail', attribution='device' WHERE case_id='C-HEALTH' AND run_id IN "
                 f"({','.join(map(str, runs['fresh']))})")
    conn.commit()
    au = audit(conn)
    assert not au["A14-fresh-baselines"]["ok"] and au["A14-fresh-baselines"]["runs"] == []
    assert any("C-HEALTH/dev-a fail/device" in x for x in au["A14-fresh-baselines"]["violations"])
    assert au["A15-fresh-baselines-stable"]["ok"]      # consistently failing is stable, which is why A14 must check


@pytest.mark.parametrize("sql,key", [
    ("UPDATE environment SET value='2' WHERE key='git_dirty'", "git_dirty"),
    ("UPDATE environment SET value='0' WHERE key='runs.clean_env'", "runs.clean_env"),
    ("UPDATE environment SET value='error: no reply' WHERE key='chrony.offset'", "chrony.offset"),
    ("UPDATE environment SET value='unavailable (MALFORMED: x)' WHERE key='fw_version.dev-a' AND run_id IN "
     "(SELECT run_id FROM runs WHERE kind <> 'mutant')", "fw_version.dev-a"),
    ("UPDATE environment SET value='   ' WHERE key='nft.witness-ctl'", "nft.witness-ctl"),
])
def test_invalid_environment_values_violate_a13(store, sql, key):
    conn, _ = store
    conn.execute(sql)
    conn.commit()
    v = audit(conn)["A13-environment-recorded"]
    assert not v["ok"] and all(f":{key}=" in x for x in v["violations"])


def test_withheld_firmware_is_accepted_only_in_a_mutant_run(store):
    conn, runs = store
    conn.execute("UPDATE environment SET value='unavailable (MALFORMED: incomplete:86B)' WHERE key='fw_version.dev-a' "
                 f"AND run_id = {runs['mutants'][2]}")
    conn.commit()
    assert audit(conn)["A13-environment-recorded"]["ok"]


@pytest.mark.parametrize("problem", ["partial", "retried", "postflight", "unclean"])
def test_fresh_trial_that_is_not_a_successful_clean_baseline_is_not_counted(store, problem):
    conn, runs = store
    r = runs["fresh"][0]
    if problem == "partial":                       # the results and every record that references them
        ids = [x[0] for x in conn.execute("SELECT result_id FROM results WHERE run_id=? AND case_id='C-GATEWAY'", (r,))]
        for t in ("checks", "evidence", "measurements"):
            conn.execute(f"DELETE FROM {t} WHERE result_id IN ({','.join(map(str, ids))})")
        conn.execute("DELETE FROM results WHERE run_id=? AND case_id='C-GATEWAY'", (r,))
    elif problem == "retried":
        conn.execute("UPDATE results SET attempts=2, verdict='fail', attribution='device' WHERE run_id=? "
                     "AND case_id='C-IDENTIFY' AND device_id='dev-b'", (r,))
    elif problem == "postflight":
        conn.execute("UPDATE results SET postflight='red' WHERE run_id=? AND case_id='C-READ-SERIES'", (r,))
    else:
        conn.execute("UPDATE runs SET clean_env=0 WHERE run_id=?", (r,))
    conn.commit()
    a14 = audit(conn)["A14-fresh-baselines"]
    assert not a14["ok"] and r not in a14["runs"] and len(a14["runs"]) == 4


def test_a4_uses_the_latest_result_not_an_older_pass(store):
    conn, _ = store
    run = baseline(conn, finished=False)
    conn.execute("UPDATE results SET verdict='fail', attribution='device', observed_category='STALE_DATA' "
                 "WHERE run_id=? AND case_id='C-READ-CLOCK' AND device_id='dev-b'", (run,))
    conn.commit()
    finish(conn, run)
    v = audit(conn)["A4-req-current-evidence-passes"]
    assert v["violations"] == [f"REQ-04: C-READ-CLOCK/dev-b latest fail/device (run {run})"]


def test_a18_latest_complete_baseline_must_commission_every_device(store):
    conn, _ = store
    partial = baseline(conn, skip={("C-IDENTIFY", "dev-a")})          # a later partial run does not count
    assert audit(conn)["A18-commissioning-complete"]["ok"]
    # An honestly recorded wrong firmware, consistent in session bytes and table. A table-only edit is now a
    # separate integrity failure (F3), covered by test_session_environment.py.
    full = baseline(conn, finished=False, env={**env_ok(), "fw_version.dev-b": "9.9.9"})
    finish(conn, full)
    a18 = audit(conn)["A18-commissioning-complete"]
    assert not a18["ok"] and a18["run"] == full and partial < full
    assert a18["violations"] == [f"run {full} dev-b: recorded firmware '9.9.9' <> inventory '1.0.0'"]


def _dial(conn, rid, addr="10.77.2.11", port=5021):
    """Record one dialled exchange on the result in place of the observation storefix recorded for it (its flow
    records removed: the state before capture_flows were written)."""
    from runner.classify import Classification, Observation
    conn.execute("DELETE FROM exchanges WHERE attempt_id IN (SELECT attempt_id FROM attempts WHERE result_id=?)", (rid,))
    conn.execute("DELETE FROM attempts WHERE result_id=?", (rid,))
    conn.execute("DELETE FROM capture_flows WHERE result_id=?", (rid,))
    o = Observation(host="dev-a.lab", port=port, cmd="IDENTIFY", req_id=1, addr=addr, stage_failed="connect",
                    error="ECONNREFUSED")
    db.insert_attempt(conn, rid, 1, "CONN_REFUSED", "connect", "", db.utcnow(), 1.0,
                      [(o, Classification("CONN_REFUSED", "connect", "ECONNREFUSED"))], outcome="ok")


def test_a17_capture_flow_evidence(store):
    conn, runs = store
    rid = conn.execute("SELECT result_id FROM results WHERE run_id=? AND case_id='FT-F3-WRONG-PORT'",
                       (runs["fault"],)).fetchone()[0]
    _dial(conn, rid)
    v = audit(conn)["A17-capture-flow-evidence"]       # dialled under the check, no record: each capture is listed
    bpf = "tcp and host 10.77.2.11 and port 5021"
    assert v["violations"] == [f"run{runs['fault']} FT-F3-WRONG-PORT/dev-a: [I8.1] {cap} capture has no record of "
                               f"dialled flow {bpf} (dialled flow must be on the wire)" for cap in ("ctl", "field")]
    db.add_capture_flow(conn, rid, capture="ctl", bpf=bpf, expected=True, packets=2, detail="dialled")
    db.add_capture_flow(conn, rid, capture="field", bpf=bpf, expected=True, packets=0, detail="dialled")
    v = audit(conn)["A17-capture-flow-evidence"]                     # the field capture missed it
    assert v["violations"] == [f"run{runs['fault']} FT-F3-WRONG-PORT/dev-a: field capture holds 0 packets of {bpf}"]
    conn.execute("UPDATE capture_flows SET packets=2 WHERE capture='field'")
    conn.commit()
    assert audit(conn)["A17-capture-flow-evidence"]["ok"]


def test_audit_of_an_unmigrated_v3_database_is_read_only(store, tmp_path):
    """The auditor's own scripts call analysis.audit() on a raw schema-v3 copy: it must run, not migrate the file,
    and report the v4-only evidence as absent."""
    conn, runs = store
    rid = conn.execute("SELECT result_id FROM results WHERE run_id=? AND case_id='FT-F3-WRONG-PORT'",
                       (runs["fault"],)).fetchone()[0]
    _dial(conn, rid)
    conn.close()
    v3 = tmp_path / "v3.db"
    shutil.copy(tmp_path / "acc.db", v3)
    raw = sqlite3.connect(v3)
    raw.executescript("DROP TABLE capture_flows; ALTER TABLE attempts DROP COLUMN outcome; "
                      "ALTER TABLE attempts DROP COLUMN predicates; DELETE FROM schema_migrations WHERE version=4; "
                      "PRAGMA user_version=3;")
    before = v3.read_bytes()
    res = {a["id"]: a for a in A.audit(raw)}
    raw.close()
    assert v3.read_bytes() == before
    assert res["A16-retry-attribution"]["ok"] and not res["A17-capture-flow-evidence"]["ok"]


def test_catalog_counts_are_consistent_with_readme_and_report(store):
    """Independent audit F-08: 13 fault types, 21 variants, 24 live fault-test instances, all catalog-derived."""
    conn, _ = store
    c = catalog.counts(len(DEVICES))
    assert (c["fault_types"], c["fault_variants"], c["fault_test_instances"]) == (13, 21, 24)
    readme = (REPO / "README.md").read_text()
    for n, what in ((13, "fault types"), (21, "fault variants"), (24, "live fault-test instances")):
        assert re.search(rf"\b{n} {what}\b", readme), what
    for m in re.finditer(r"\b20 (?:fault )?variants\b", readme):        # only in the note that corrects it
        assert "wrong" in readme[m.start():m.start() + 60], readme[m.start() - 80:m.start() + 60]
    line = report.catalog_counts_line(conn)
    assert "**13 fault types**" in line and "**21 fault variants**" in line and "**24 live fault-test instances**" in line
    assert "agrees" in line
