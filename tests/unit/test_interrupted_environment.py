"""Independent F3 omission counterexample: obligations survive loss of file AND index.

Disposable synthetic stores only; these are not VM commissioning results.
"""
import json

import pytest

from runner import analysis as A, contract as C, db, report
from tests.contract import harness as H, matrix as MX, refstore as R


@pytest.fixture(scope="module")
def stores(tmp_path_factory):
    return H.build_all(tmp_path_factory.mktemp("interrupted-env"),
                       ["reference", "current-failure", "aborted-detected", "legacy"])


OMISSIONS = MX.interrupted_environment_findings()


@pytest.mark.parametrize("m", OMISSIONS, ids=[m.name for m in OMISSIONS])
def test_declared_omission_is_rejected(stores, tmp_path, m):
    assert (outcome := H.run_mutation(m, stores, tmp_path)).status == "OK", outcome


def test_exact_auditor_counterexample_preserves_all_other_run_facts(stores, tmp_path):
    b = stores["aborted-detected"]
    conn, root = H.copy_store(b, tmp_path, True)
    try:
        run = b.ref.runs["K"]
        saved = {t: list(map(tuple, conn.execute(f"SELECT * FROM {t} WHERE run_id=?", (run,))))
                 for t in ("runs", "environment", "checks", "results", "run_plan")}
        assert len(saved["environment"]) == 20
        assert all(a["ok"] for a in A.audit(conn, evidence_root=root))
        MX.omit_session_environment("K")(MX.Ctx(conn, root, b.ref))
        assert saved == {t: list(map(tuple, conn.execute(f"SELECT * FROM {t} WHERE run_id=?", (run,))))
                         for t in saved}
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        audit = A.audit(conn, evidence_root=root)
        a23 = next(a for a in audit if a["id"].startswith("A23"))
        assert not a23["ok"], audit
        assert any(f"run {run}: [I1.7]" in v for v in a23["violations"])
        texts = report.build_all(conn, root)
        assert json.loads(texts["acceptance-audit.json"])["assertions"] == audit
        assert "[I1.7]" in texts["commissioning-report.md"]
    finally:
        conn.close()


@pytest.mark.parametrize("rooted", [False, True])
@pytest.mark.parametrize("rows", ["all", "single", "results-only", "finished-only"])
def test_durable_collection_facts_require_snapshot_even_for_unfair_run(stores, tmp_path, rooted, rows):
    b = stores["aborted-detected"]
    conn, root = H.copy_store(b, tmp_path, True)
    try:
        run = b.ref.runs["K"]
        if rows == "finished-only":
            # A finished unclean session, with no case results, still crossed environment collection.
            builder = R.Builder(conn=conn, root=root)
            run = builder.run("finished-unclean", "baseline", [], clean=False)
            label = "finished-unclean"
            ctx = MX.Ctx(conn, root, R.Ref(b.ref.db, root, builder.runs, "probe", frozenset()))
        else:
            label, ctx = "K", MX.Ctx(conn, root, b.ref)
        MX.omit_session_environment(label)(ctx)
        if rows == "single":
            conn.execute("DELETE FROM environment WHERE run_id=? AND key <> 'runs.clean_env'", (run,))
        elif rows in ("results-only", "finished-only"):
            conn.execute("DELETE FROM environment WHERE run_id=?", (run,))
        violations = C.run_violations(conn, root=root if rooted else None, runs=[run])
        assert any(f"run {run}: [I1.7]" in v for v in violations), violations
    finally:
        conn.close()


def test_genuine_pre_environment_interruption_with_plan_needs_no_snapshot(stores, tmp_path):
    b = stores["reference"]
    conn, root = H.copy_store(b, tmp_path, True)
    try:
        builder = R.Builder(conn=conn, root=root)
        early = db.start_run(conn, kind="baseline", git_sha=R.SHA, git_dirty=0, clean_env=1, runner_host="fixture")
        builder.checks(early, "preflight", None)
        builder.save(early, "session/preflight-ctl.txt", "ctl GREEN", "preflight", None)
        builder.save(early, "session/preflight-field.txt", "field GREEN", "preflight", None)
        builder.save(early, "session/plan.json", db.record_plan(conn, early, [("C-HEALTH", "dev-a")]), "plan", None)
        assert conn.execute("SELECT count(*) FROM environment WHERE run_id=?", (early,)).fetchone()[0] == 0
        assert C.run_violations(conn, root=root, runs=[early]) == []
        assert all(a["ok"] for a in A.audit(conn, evidence_root=root))
        # It remains a legitimate early interruption after a real later session detects it.
        detector = builder.run("detector", "baseline", R.commissioning_set())
        assert db.mark_aborted_runs(conn, detector) == [early]
        assert C.run_violations(conn, root=root, runs=[early]) == []
        assert all(a["ok"] for a in A.audit(conn, evidence_root=root))
    finally:
        conn.close()


def test_newer_failed_unfair_run_cannot_be_hidden_by_older_success(stores, tmp_path):
    b = stores["current-failure"]
    conn, root = H.copy_store(b, tmp_path, True)
    try:
        run = b.ref.runs["B"]
        before = list(map(tuple, conn.execute("SELECT * FROM results WHERE run_id=?", (run,))))
        conn.execute("UPDATE runs SET clean_env=0, contaminated=1, notes='contaminated: failed preflight check' "
                     "WHERE run_id=?", (run,))
        conn.execute("UPDATE environment SET value='0' WHERE run_id=? AND key='runs.clean_env'", (run,))
        conn.execute("UPDATE checks SET status='FAIL' WHERE check_id=(SELECT check_id FROM checks WHERE run_id=? "
                     "AND result_id IS NULL AND phase='preflight' LIMIT 1)", (run,))
        MX.omit_session_environment("B")(MX.Ctx(conn, root, b.ref))
        audit = {a["id"].split("-")[0]: a for a in A.audit(conn, evidence_root=root)}
        assert audit["A18"]["run"] == b.ref.runs["T5"]  # per-run selection cannot greenlight the dataset
        assert not audit["A23"]["ok"], audit
        assert any(f"run {run}: [I1.7]" in v for v in audit["A23"]["violations"])
        assert list(map(tuple, conn.execute("SELECT * FROM results WHERE run_id=?", (run,)))) == before
    finally:
        conn.close()


@pytest.mark.parametrize("variant", ["reference", "current-failure", "aborted-detected", "legacy"])
def test_valid_controls_keep_exact_outcomes(stores, tmp_path, variant):
    assert (outcome := H.run_control(variant, stores[variant], tmp_path)).status == "OK", outcome


@pytest.mark.parametrize("label", ["B", "M1", "M2", "M3", "M4", "M5", "M6"])
def test_complete_baseline_and_each_mutant_remain_valid(stores, tmp_path, label):
    b = stores["reference"]
    conn, root = H.copy_store(b, tmp_path, False)
    try:
        assert C.run_violations(conn, root=root, runs=[b.ref.runs[label]]) == []
    finally:
        conn.close()


def test_disabling_only_durable_obligation_restores_the_counterexample(stores, tmp_path):
    from scripts.verify_acceptance_contract import _weakenings
    weakening = _weakenings()["F3 omission: session obligation derived only from surviving index/file"]
    m = next(m for m in OMISSIONS if m.base == "aborted-detected" and m.name.endswith("snapshot and index"))
    with weakening():
        assert (outcome := H.run_mutation(m, stores, tmp_path)).status == "FALSE_ACCEPT", outcome
    assert (outcome := H.run_mutation(m, stores, tmp_path)).status == "OK", outcome


@pytest.mark.parametrize("rehash", [False, True], ids=["hash-disagreement", "snapshot-table-disagreement"])
def test_interrupted_snapshot_and_index_must_still_agree(stores, tmp_path, rehash):
    b = stores["aborted-detected"]
    conn, root = H.copy_store(b, tmp_path, True)
    try:
        ctx = MX.Ctx(conn, root, b.ref)
        MX.session_edit(lambda text: text.replace('"baseline"', '"fault"'), "K", rehash=rehash)(ctx)
        assert any("[I1.7]" in v for v in C.run_violations(conn, root=root, runs=[ctx.run("K")]))
    finally:
        conn.close()
