"""F3 acceptance-integrity regression: session bytes independently record a baseline's identity.

These tests use fixture writers and an independent before/after oracle, never the acceptance SQL as an expectation.
All mutations operate on disposable database/evidence copies. Synthetic data is not VM commissioning evidence.
"""
import hashlib
import json

import pytest

from runner import analysis as A, contract as C, db
from tests.contract import harness as H, matrix as MX, oracle as O, refstore as R


@pytest.fixture(scope="module")
def stores(tmp_path_factory):
    return H.build_all(tmp_path_factory.mktemp("session-env"), ["reference", "current-failure", "legacy"])


F3 = MX.session_environment_findings()


@pytest.mark.parametrize("m", F3, ids=[m.name for m in F3])
def test_session_metadata_mutation_is_rejected(stores, tmp_path, m):
    outcome = H.run_mutation(m, stores, tmp_path)
    assert outcome.status == "OK", outcome


def test_original_counterexample_keeps_the_failure_and_the_hash_verified_baseline(stores, tmp_path):
    b = stores["current-failure"]
    conn, root = H.copy_store(b, tmp_path, False)
    try:
        run = b.ref.runs["B"]
        before = list(conn.execute("SELECT result_id,verdict,attribution FROM results WHERE run_id=?", (run,)))
        ev = conn.execute("SELECT * FROM evidence WHERE run_id=? AND kind='environment'", (run,)).fetchone()
        raw = (root / ev["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == ev["sha256"] and len(raw) == ev["bytes"]
        assert json.loads(raw)["runs.kind"] == "baseline"
        MX.relabel_run("mutant")(MX.Ctx(conn, root, b.ref))
        assert list(conn.execute("SELECT result_id,verdict,attribution FROM results WHERE run_id=?", (run,))) == before
        assert O.deviations(conn, root, b.truth)  # independent of every production acceptance predicate
        res = A.audit(conn, evidence_root=root)
        bad = {a["id"].split("-")[0] for a in res if not a["ok"]}
        assert "A23" in bad, res
        # Selection can still show the older baseline, but the store must explicitly reject that explanation.
        assert next(a for a in res if a["id"].startswith("A18"))["run"] == b.ref.runs["T5"]
    finally:
        conn.close()


@pytest.mark.parametrize("variant", ["reference", "current-failure", "legacy"])
def test_valid_controls_keep_their_declared_acceptance(stores, tmp_path, variant):
    assert H.run_control(variant, stores[variant], tmp_path).status == "OK"


def test_standalone_commissioning_rejects_session_disagreement(stores, tmp_path):
    conn, root = H.copy_store(stores["reference"], tmp_path, False)
    try:
        c = MX.Ctx(conn, root, stores["reference"].ref)
        conn.execute("UPDATE runs SET git_dirty=1 WHERE run_id=?", (c.run("B"),))
        conn.execute("UPDATE environment SET value='1' WHERE run_id=? AND key='git_dirty'", (c.run("B"),))
        assert db.commissioned_devices(conn, c.run("B"), evidence_root=root) == []
    finally:
        conn.close()


def test_new_guard_is_required_by_the_original_regression(stores, tmp_path, monkeypatch):
    # Deliberately disable only the new comparison; the independent oracle still sees the relabelled baseline.
    monkeypatch.setattr(C, "_session_environment", lambda *a, **kw: [])
    o = H.run_mutation(F3[0], stores, tmp_path)
    assert o.status == "FALSE_ACCEPT", o


def test_duplicate_session_names_cannot_be_read_as_the_last_record(stores, tmp_path, monkeypatch):
    monkeypatch.setattr(C, "_predicate_record", json.loads)
    for m in F3:
        if m.name in ("F3: duplicate kind", "F3: escaped duplicate kind"):
            o = H.run_mutation(m, stores, tmp_path)
            assert o.status == "FALSE_ACCEPT", o


@pytest.mark.parametrize("label", ["B", "M1", "M2", "M3", "M4", "M5", "M6"])
def test_actual_writer_format_without_clean_env_in_json_is_valid(stores, tmp_path, label):
    conn, root = H.copy_store(stores["reference"], tmp_path, True)
    try:
        c = MX.Ctx(conn, root, stores["reference"].ref)
        def edit(text):
            doc = json.loads(text)
            del doc["runs.clean_env"]
            return json.dumps(doc)
        MX.session_edit(edit, label)(c)
        assert C.run_violations(conn, root=root, runs=[c.run(label)]) == []
        if label == "B":
            assert db.commissioned_devices(conn, c.run(label), evidence_root=root) == R.DEVICES
    finally:
        conn.close()


def test_pre_mutant_historical_format_is_valid_without_inventing_metadata(stores, tmp_path):
    conn, root = H.copy_store(stores["legacy"], tmp_path, True)
    try:
        c = MX.Ctx(conn, root, stores["legacy"].ref)
        keys = ["mutant", "runs.clean_env", "device_build.dev-a", "device_build.dev-b"]
        def edit(text):
            doc = json.loads(text)
            for key in keys:
                del doc[key]
            return json.dumps(doc)
        MX.session_edit(edit, "T1")(c)
        for key in keys:
            if key != "runs.clean_env":
                conn.execute("DELETE FROM environment WHERE run_id=? AND key=?", (c.run("T1"), key))
        assert C.run_violations(conn, root=root, runs=[c.run("T1")]) == []
    finally:
        conn.close()


def test_legitimate_mixed_run_is_accepted(stores, tmp_path):
    conn, root = H.copy_store(stores["reference"], tmp_path, True)
    try:
        b = R.Builder(conn=conn, root=root)
        run = b.run("mixed-control", "mixed", [R.passing("C-HEALTH", "dev-a"), R.passing("FT-F2-HUNG", "dev-a")])
        assert C.run_violations(conn, root=root, runs=[run]) == []
        assert all(a["ok"] for a in A.audit(conn, evidence_root=root))
    finally:
        conn.close()
