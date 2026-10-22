"""Independent contract verification IC-01 (docs/independent-contract-verification.md): a run's contamination note
named the run itself as the later session that found it unfinished, so a current failing baseline left acceptance
and an older passing run stood in. An abort is corroborated only by a SEPARATE run that started after it (larger run
id, later recorded start) while it was still unfinished; every marker in the note must hold. Fixture stores
(tests/unit/storefix.py, tests/contract/refstore.py); never lab evidence."""
import pytest

from runner import analysis as A, contract as C, db
from storefix import accepted_store, env_ok, new_store
from tests.contract import refstore as R


def stamp(s: float) -> str:
    return f"2026-10-17T11:03:{s:06.3f}Z"


def run(run_id, started, finished=None, notes="") -> dict:
    return {"run_id": run_id, "started_at": started, "finished_at": finished, "notes": notes, "contaminated": 1}


def cause(ru: dict, started: dict, sessions: dict | None = None) -> str | None:
    """`sessions`: {run: (first, last) session record time}; by default every run's session records span its start
    to its finish (or to its start: a killed run)."""
    if sessions is None:
        sessions = {r: (t, ru["finished_at"] or t) if r == ru["run_id"] else (t, None) for r, t in started.items()}
    return C._contamination_cause(ru, started, False, False, False, sessions)


def marker(n) -> str:
    return f"selftest | aborted: never finished (detected by run {n})"


# ---------------------------------------------------------------- the corroboration rule

def test_a_run_cannot_certify_its_own_abort():
    why = cause(run(14, stamp(10), stamp(20), marker(14)), {14: stamp(10)})
    assert why and "itself" in why


def test_a_detector_that_was_never_recorded_is_rejected():
    assert "not a recorded run" in cause(run(14, stamp(10), None, marker(99)), {14: stamp(10)})


@pytest.mark.parametrize("det_id,det_start", [(13, stamp(5)), (15, stamp(10)), (15, stamp(5))],
                         ids=["earlier-run", "same-start", "larger-id-earlier-start"])
def test_a_detector_that_did_not_start_after_the_run_is_rejected(det_id, det_start):
    why = cause(run(14, stamp(10), None, marker(det_id)), {14: stamp(10), det_id: det_start})
    assert why and "did not start after it" in why


def test_unfinished_run_found_by_the_next_session_is_corroborated():
    assert cause(run(41, stamp(32.246), None, marker(42)), {41: stamp(32.246), 42: stamp(40)}) is None


def test_run_still_finishing_when_the_next_session_started_is_corroborated():
    """Master run 38 (SIGTERM self-test): its teardown wrote finished_at 137 ms after run 39 had started; its own
    append-only session records (postflight checks 45.210-45.213, command log 45.218) follow run 39's first one
    (preflight check 45.087)."""
    assert cause(run(38, stamp(39.394), stamp(45.219), marker(39)), {38: stamp(39.394), 39: stamp(45.082)},
                 {38: (stamp(39.397), stamp(45.218)), 39: (stamp(45.087), stamp(46.109))}) is None


def test_run_that_finished_before_its_detector_started_is_rejected():
    why = cause(run(14, stamp(10), stamp(20), marker(15)), {14: stamp(10), 15: stamp(30)})
    assert why and "finished" in why and "before run 15 started" in why


def test_finish_moved_after_the_detector_started_is_not_its_own_witness():
    """Independent review F1: the run's finished_at (the same row as the flag) claimed the overlap; its session
    records all precede the detector's first one."""
    why = cause(run(7, stamp(1), stamp(30.001), marker(8)), {7: stamp(1), 8: stamp(30)},
                {7: (stamp(1.003), stamp(2.5)), 8: (stamp(30.005), stamp(40))})
    assert why and "session" in why and "only its own finished_at" in why


def test_detector_start_moved_inside_the_run_is_rejected():
    """Independent review F1c: the genuine next run's started_at moved 1 ms after the run's start; its first session
    record (and the run's last) still say the run had finished before the next session began."""
    why = cause(run(7, stamp(1), stamp(2.6), marker(8)), {7: stamp(1), 8: stamp(1.001)},
                {7: (stamp(1.003), stamp(2.5)), 8: (stamp(30.005), stamp(40))})
    assert why and "only its own finished_at" in why


def test_session_records_of_the_same_millisecond_do_not_prove_the_overlap():
    why = cause(run(7, stamp(1), stamp(30.002), marker(8)), {7: stamp(1), 8: stamp(30)},
                {7: (stamp(1.003), stamp(30.001)), 8: (stamp(30.001), stamp(40))})
    assert why and "only its own finished_at" in why


def test_detector_without_a_recorded_session_is_rejected():
    """Independent review F2: a bare runs row (no session record) cannot have found anything."""
    why = cause(run(14, stamp(10), None, marker(15)), {14: stamp(10), 15: stamp(30)}, {14: (stamp(10.003), None)})
    assert why and "no session record" in why


@pytest.mark.parametrize("own,det,finished", [(None, stamp(30), None), (stamp(10), None, None),
                                              ("yesterday", stamp(30), None), (stamp(10), "", None),
                                              (stamp(10), stamp(30), "soon")],
                         ids=["own-start-missing", "detector-start-missing", "own-start-malformed",
                              "detector-start-empty", "finish-malformed"])
def test_missing_or_malformed_timestamps_leave_the_abort_uncorroborated(own, det, finished):
    why = cause(run(14, own, finished, marker(15)), {14: own, 15: det})
    assert why and "not recorded" in why


def test_every_marker_must_hold():
    """Master run 7 carries one marker per later session (17, 18): both corroborate it. A self-citing marker added
    beside a genuine one does not."""
    started = {7: stamp(1), 17: stamp(20), 18: stamp(30)}
    assert cause(run(7, stamp(1), None, marker(17) + " | aborted: never finished (detected by run 18)"), started) is None
    why = cause(run(7, stamp(1), None, marker(17) + " | aborted: never finished (detected by run 7)"), started)
    assert why and "itself" in why


# ---------------------------------------------------------------- the store: acceptance and the session writer

@pytest.fixture
def store(tmp_path):
    conn = new_store(tmp_path / "s.db")
    runs = accepted_store(conn)
    b = R.Builder(conn=conn, root=tmp_path / "evidence")
    yield conn, runs, b, tmp_path / "evidence"
    conn.close()


def audit(conn, root) -> dict:
    return {a["id"].split("-")[0]: a for a in A.audit(conn, evidence_root=root)}


def failing_baseline(b) -> int:
    return b.run("failing", "baseline", R.commissioning_set({("C-HEALTH", "dev-a"): R.degraded_health("dev-a")}),
                 env=env_ok())


def test_failing_baseline_that_certifies_its_own_abort_is_rejected(store):
    """The auditor's counterexample: before, A4 and A18 reject the current failure; after the single UPDATE, an older
    passing baseline stood in and acceptance held 24/24."""
    conn, runs, b, root = store
    bad = failing_baseline(b)
    before = audit(conn, root)
    assert {k for k, a in before.items() if not a["ok"]} == {"A4", "A18"} and before["A18"]["run"] == bad
    conn.execute("UPDATE runs SET contaminated = 1, notes = notes || ' | aborted: never finished (detected by run ' "
                 "|| run_id || ')' WHERE run_id = ?", (bad,))
    after = audit(conn, root)
    assert not after["A23"]["ok"], "a self-certified abort must not remove the current failure from acceptance"
    assert any(v.startswith(f"run {bad}: [I1.2] contaminated as aborted") and "itself" in v
               for v in after["A23"]["violations"]), after["A23"]["violations"]


def test_failing_fault_run_that_certifies_its_own_abort_is_rejected(store):
    conn, runs, b, root = store
    bad = b.run("fault-cut", "fault", R.fault_set(replace={"FT-F2-HUNG": R.deadline_cut("FT-F2-HUNG")}),
                env=env_ok(kind="fault"))
    assert {k for k, a in audit(conn, root).items() if not a["ok"]} == {"A4"}
    conn.execute("UPDATE runs SET contaminated = 1, notes = notes || ' | aborted: never finished (detected by run ' "
                 "|| run_id || ')' WHERE run_id = ?", (bad,))
    assert any(v.startswith(f"run {bad}: [I1.2] contaminated as aborted") for v in audit(conn, root)["A23"]["violations"])


FORGED_FINISH = ("UPDATE runs SET contaminated = 1, notes = notes || ' | aborted: never finished (detected by run ' "
                 "|| :det || ')', finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', julianday((SELECT started_at FROM runs "
                 "WHERE run_id = :det)) + 0.001 / 86400.0) WHERE run_id = :run")


def test_failing_fault_run_cannot_claim_it_was_still_running_when_the_next_session_started(store):
    """Independent review F1 (one UPDATE): the fault run's finish moved 1 ms after the genuine next run's start."""
    conn, runs, b, root = store
    bad = b.run("fault-cut", "fault", R.fault_set(replace={"FT-F2-HUNG": R.deadline_cut("FT-F2-HUNG")}),
                env=env_ok(kind="fault"))
    nxt = b.run("next", "baseline", R.commissioning_set(), env=env_ok())
    conn.execute(FORGED_FINISH, {"det": nxt, "run": bad})
    au = audit(conn, root)
    assert any(v.startswith(f"run {bad}: [I1.2] contaminated as aborted") and "only its own finished_at" in v
               for v in au["A23"]["violations"]), au["A23"]["violations"]


def test_failing_baseline_cannot_claim_it_was_still_running_when_the_fault_run_started(store):
    """Independent review F1b: baseline then fault run, the order of a normal campaign."""
    conn, runs, b, root = store
    bad = failing_baseline(b)
    nxt = b.run("fault-after", "fault", R.fault_set(), env=env_ok(kind="fault"))
    conn.execute(FORGED_FINISH, {"det": nxt, "run": bad})
    assert not audit(conn, root)["A23"]["ok"]


def test_detector_start_moved_inside_the_failing_run_is_rejected(store):
    """Independent review F1c: two runs rows (the detector's start and the failing run's flag), no session record."""
    conn, runs, b, root = store
    bad = failing_baseline(b)
    nxt = b.run("next", "baseline", R.commissioning_set(), env=env_ok())
    conn.execute("UPDATE runs SET started_at = strftime('%Y-%m-%dT%H:%M:%fZ', julianday((SELECT started_at FROM runs "
                 "WHERE run_id = ?)) + 0.001 / 86400.0) WHERE run_id = ?", (bad, nxt))
    conn.execute("UPDATE runs SET contaminated = 1, notes = notes || ' | aborted: never finished (detected by run ' "
                 "|| ? || ')' WHERE run_id = ?", (nxt, bad))
    assert any(v.startswith(f"run {bad}: [I1.2] contaminated as aborted") for v in audit(conn, root)["A23"]["violations"])


def test_fabricated_detector_row_is_rejected(store):
    """Independent review F2: one bare runs row inserted as the 'next session' (no session record)."""
    conn, runs, b, root = store
    bad = failing_baseline(b)
    conn.execute("INSERT INTO runs (started_at, kind, git_sha, git_dirty, clean_env, runner_host, notes) VALUES "
                 "(strftime('%Y-%m-%dT%H:%M:%fZ', julianday((SELECT started_at FROM runs WHERE run_id = ?)) + "
                 "0.001 / 86400.0), 'baseline', ?, 0, 1, 'fixture', 'fabricated')", (bad, "0" * 40))
    det = conn.execute("SELECT max(run_id) FROM runs").fetchone()[0]
    conn.execute("UPDATE runs SET contaminated = 1, notes = notes || ' | aborted: never finished (detected by run ' "
                 "|| ? || ')' WHERE run_id = ?", (det, bad))
    assert any(v.startswith(f"run {bad}: [I1.2] contaminated as aborted") and "no session record" in v
               for v in audit(conn, root)["A23"]["violations"])


def test_failing_run_killed_and_found_by_the_next_session_leaves_acceptance_to_that_session(store):
    """Valid control: a killed run (no teardown, so no finish and no session postflight) holding a failure is
    excluded once the next session marks it; that session's complete baseline is the current evidence."""
    conn, runs, b, root = store
    killed = b.run("killed", "baseline", R.commissioning_set({("C-HEALTH", "dev-a"): R.degraded_health("dev-a")}),
                   env=env_ok(), finished=False)
    nxt = b.run("next", "baseline", R.commissioning_set(), env=env_ok())
    assert db.mark_aborted_runs(conn, nxt) == [killed]
    au = audit(conn, root)
    assert not {k: a["violations"] for k, a in au.items() if not a["ok"]}
    assert au["A18"]["run"] == nxt


def test_killed_run_whose_marker_is_rewritten_to_cite_itself_is_rejected(store):
    conn, runs, b, root = store
    killed = b.run("killed", "baseline", R.commissioning_set(), env=env_ok(), finished=False)
    nxt = b.run("next", "baseline", R.commissioning_set(), env=env_ok())
    db.mark_aborted_runs(conn, nxt)
    conn.execute("UPDATE runs SET notes = replace(notes, 'detected by run ' || ?, 'detected by run ' || run_id) "
                 "WHERE run_id = ?", (nxt, killed))
    assert any(v.startswith(f"run {killed}: [I1.2] contaminated as aborted") and "itself" in v
               for v in audit(conn, root)["A23"]["violations"])


def test_a_session_never_marks_a_newer_run_as_one_it_found_unfinished(store):
    """db.mark_aborted_runs writes the invariant the verifier checks: only runs that started before the detecting
    session (smaller run id) can have been found unfinished by it."""
    conn, runs, b, root = store
    older = b.run("older", "baseline", R.commissioning_set(), env=env_ok(), finished=False)
    newer = b.run("newer", "baseline", R.commissioning_set(), env=env_ok(), finished=False)
    assert db.mark_aborted_runs(conn, older) == []
    assert db.mark_aborted_runs(conn, newer) == [older]
