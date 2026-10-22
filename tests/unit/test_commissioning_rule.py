"""Independent audit F-01: commissioning is decided against the catalog's COMPLETE commissioning set
(runner/db.py COMMISSIONING_GAPS), never against whichever cases a run happened to execute.
Fixture stores only (tests/unit/storefix.py); the real partial-run check runs on witness-ctl."""
import pytest

from runner import catalog, db, report
from storefix import DEVICES, baseline, env_ok, finish, new_store, result

REQUIRED = [(c, d) for c, per_dev in catalog.COMMISSIONING_REQUIRED for d in (DEVICES if per_dev else [None])]


@pytest.fixture
def conn(tmp_path):
    c = new_store(tmp_path / "c.db")
    yield c
    c.close()


def test_required_set_is_the_whole_commissioning_catalog():
    assert {c for c, _ in catalog.COMMISSIONING_REQUIRED} == {c.case_id for c in catalog.CASES
                                                               if c.kind == "commissioning"}
    assert len(REQUIRED) == catalog.counts(len(DEVICES))["commissioning_instances"] == 11


def test_complete_passing_baseline_commissions_every_device(conn):
    run = baseline(conn)
    assert db.commissioning_gaps(conn, run) == {"dev-a": None, "dev-b": None}
    assert db.commissioned_devices(conn, run) == ["dev-a", "dev-b"]


def test_auditor_health_only_run_commissions_nothing(conn):
    """The audit's counterexample: one passing C-HEALTH on dev-a (in-memory repro) and the real VM shape of
    audit run 3 (C-HEALTH on both devices) were reported commissioned. Neither may be."""
    for devs in (["dev-a"], ["dev-a", "dev-b"]):
        run = db.start_run(conn, kind="baseline", git_sha="s", git_dirty=0, clean_env=1, runner_host="unit")
        db.put_env(conn, run, env_ok())
        for d in devs:
            result(conn, run, "C-HEALTH", d)
        db.finish_run(conn, run)
        gaps = db.commissioning_gaps(conn, run)
        assert db.commissioned_devices(conn, run) == []
        for d in DEVICES:
            assert "missing C-IDENTIFY/" + d in gaps[d] and "missing C-READ-SERIES/" + d in gaps[d]
            assert "missing C-ENVIRONMENT (run-level)" in gaps[d]
        text = report.commissioning_section(conn)
        assert f"Run **{run}**: **PARTIAL** commissioning run" in text and "Commissioned by it: **none**" in text


@pytest.mark.parametrize("missing", REQUIRED, ids=lambda m: f"{m[0]}/{m[1] or 'run'}")
def test_every_single_missing_instance_blocks(conn, missing):
    run = baseline(conn, skip={missing})
    case_id, dev = missing
    blocked = DEVICES if dev is None else [dev]       # a run-level case gates every device
    assert db.commissioned_devices(conn, run) == [d for d in DEVICES if d not in blocked]
    for d in blocked:
        assert f"missing {case_id}" in db.commissioning_gaps(conn, run)[d]


@pytest.mark.parametrize("second", ["pass", "fail"])
def test_duplicate_or_conflicting_results_block(conn, second):
    run = baseline(conn, finished=False)
    result(conn, run, "C-READ-CLOCK", "dev-b", verdict=second, attribution="none" if second == "pass" else "device",
           observed="PASS" if second == "pass" else "STALE_DATA")
    finish(conn, run)
    gaps = db.commissioning_gaps(conn, run)
    assert db.commissioned_devices(conn, run) == ["dev-a"]
    assert "duplicate C-READ-CLOCK/dev-b (2 results)" in gaps["dev-b"]


@pytest.mark.parametrize("mutate,why", [
    (lambda c, r: c.execute("UPDATE runs SET finished_at = NULL WHERE run_id = ?", (r,)), "run not finished"),
    (lambda c, r: c.execute("UPDATE runs SET clean_env = 0 WHERE run_id = ?", (r,)), "red preflight"),
    (lambda c, r: db.mark_contaminated(c, r, "unit"), "run contaminated"),
    (lambda c, r: c.execute("UPDATE runs SET kind = 'fault' WHERE run_id = ?", (r,)), "run kind fault"),
])
def test_run_level_prerequisites(conn, mutate, why):
    run = baseline(conn)
    mutate(conn, run)
    conn.commit()
    assert db.commissioned_devices(conn, run) == []
    assert all(why in g for g in db.commissioning_gaps(conn, run).values())


def test_aborted_run_marked_by_the_next_session_never_commissions(conn):
    killed = baseline(conn, finished=False)
    nxt = db.start_run(conn, kind="baseline", git_sha="s", git_dirty=0, clean_env=1, runner_host="unit")
    assert db.mark_aborted_runs(conn, nxt) == [killed]
    gaps = db.commissioning_gaps(conn, killed)
    assert all("run not finished" in g and "run contaminated" in g for g in gaps.values())


def test_case_result_problems_block_only_that_device(conn):
    run = baseline(conn, finished=False)
    conn.execute("UPDATE results SET postflight = NULL WHERE run_id = ? AND case_id = 'C-HEALTH' AND device_id = 'dev-a'",
                 (run,))
    conn.execute("UPDATE results SET verdict = 'error', attribution = 'runner' WHERE run_id = ? "
                 "AND case_id = 'C-GATEWAY' AND device_id = 'dev-b'", (run,))
    conn.commit()
    finish(conn, run)
    gaps = db.commissioning_gaps(conn, run)
    assert "C-HEALTH/dev-a pass/none, postflight not recorded" in gaps["dev-a"]
    assert "C-GATEWAY/dev-b error/runner" in gaps["dev-b"]
    assert db.commissioned_devices(conn, run) == []


def test_identity_firmware_and_build(conn):
    run = baseline(conn, finished=False)
    result(conn, run, "FT-F7-NAME-SWAP", "dev-a", verdict="pass", observed="WRONG_IDENTITY", expected="WRONG_IDENTITY",
           fault="F7")
    db.put_env(conn, run, {"fw_version.dev-b": "unavailable (MALFORMED: incomplete:86B)"})
    finish(conn, run)
    gaps = db.commissioning_gaps(conn, run)
    assert "WRONG_IDENTITY observed (FT-F7-NAME-SWAP)" in gaps["dev-a"]
    assert "recorded firmware 'unavailable (MALFORMED: incomplete:86B)' <> inventory '1.0.0'" in gaps["dev-b"]
    run2 = baseline(conn, env={k: v for k, v in env_ok().items() if k != "device_build.dev-a"} |
                    {"device_build.dev-b": "mutant:seq-reuse"})
    gaps2 = db.commissioning_gaps(conn, run2)
    assert "device build not recorded (stock required)" in gaps2["dev-a"]
    assert "device build 'mutant:seq-reuse' (stock required)" in gaps2["dev-b"]


def test_report_shows_latest_complete_run_when_the_latest_is_partial(conn):
    full = baseline(conn)
    partial = baseline(conn, skip={("C-IDENTIFY", "dev-a"), ("C-IDENTIFY", "dev-b")})
    text = report.commissioning_section(conn)
    assert f"Run **{partial}**: **PARTIAL** commissioning run (9/11 required instances executed)" in text
    assert f"Run **{partial}**: **PARTIAL** commissioning run (9/11 required instances executed). Commissioned by " \
           "it: **none**." in text
    assert "A partial run commissions no device that lacks one of its own or of the run-level instances." in text
    assert f"Run **{full}**: **COMPLETE** commissioning run (11/11 required instances executed). " \
           "Commissioned by it: **dev-a, dev-b**." in text


@pytest.mark.parametrize("key,value", [("python", "\t\n"), ("git_sha", "not-the-run-revision"),
                                       ("chrony.offset", "offset_s=garbage"), ("kernel.witness-field", "")])
def test_invalid_environment_record_blocks_commissioning(conn, key, value):
    """Second independent audit R-01: the run's passing C-ENVIRONMENT result is not trusted over the record itself
    (runner/evidence.check_environment, the same validation as the live case and acceptance A13)."""
    run = baseline(conn, env={**env_ok(), key: value})
    assert db.commissioned_devices(conn, run) == []
    assert all(g.startswith(f"environment record invalid: {key} ") for g in db.commissioning_gaps(conn, run).values())
