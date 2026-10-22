"""Acceptance-contract harness (docs/acceptance-contract.md): the production verifier against an independent oracle
over a valid reference store, its legitimate control variants, a declared mutation matrix and seeded random
combinations. Synthetic fixture stores only; never lab evidence. scripts/verify_acceptance_contract.py runs the same
checks as one command with a compact report."""
import os

import pytest

from tests.contract import harness as H, matrix as MX, refstore as R

SEEDS = range(int(os.environ.get("WITNESS_CONTRACT_SEEDS", "40")))


@pytest.fixture(scope="session")
def built(tmp_path_factory):
    return H.build_all(tmp_path_factory.mktemp("contract"))


@pytest.fixture(scope="session")
def work(tmp_path_factory):
    return tmp_path_factory.mktemp("contract-work")


@pytest.mark.parametrize("variant", list(R.VARIANTS))
def test_control_variant_has_exactly_its_declared_outcome(built, work, variant):
    if variant not in built:
        pytest.skip("variant needs the schema-v5 run plan")
    o = H.run_control(variant, built[variant], work)
    assert o.status == "OK", o


MATRIX = MX.build_matrix()


@pytest.mark.parametrize("m", MATRIX, ids=[m.name for m in MATRIX])
def test_mutation_matches_declaration_and_oracle(built, work, m):
    o = H.run_mutation(m, built, work)
    if o.status == "N/A":
        pytest.skip("attack on the schema-v5 run plan")
    assert o.status == "OK", o


@pytest.mark.parametrize("seed", SEEDS)
def test_random_combination_is_rejected(built, work, seed):
    o = H.run_combination(seed, built, work)
    if o.status != "OK":
        o.why.append(f"minimal failing steps: {H.shrink(seed, built, work)}")
    assert o.status == "OK", o


@pytest.mark.parametrize("seed", SEEDS)
def test_removing_evidence_never_makes_a_failing_store_acceptable(built, work, seed):
    o = H.run_combination(seed, built, work, base="current-failure")
    assert o.production, f"store accepted after removing evidence: {o}"


def test_oracle_sees_a_decision_erased_shadowed_or_relabelled_but_not_reordered(built, work):
    """Independent contract verification: the oracle's projection omitted results.predicates, so erasing a gateway
    decision was no deviation (its 'oracle-predicate-projection' probe)."""
    if not R.HAS_DECISION:
        pytest.skip("needs the schema-v5 decision predicates")
    import json
    from tests.contract import oracle as O
    b = built["reference"]
    for text, deviates in (("{}", True), (None, False), ("dup", True), ("relabel", True)):
        conn, root, c, runs = _copy(built, work)
        rid = c.rid("B", "C-GATEWAY", "dev-b")
        preds = json.loads(conn.execute("SELECT predicates FROM results WHERE result_id = ?", (rid,)).fetchone()[0])
        new = {"{}": "{}", None: json.dumps(dict(reversed(list(preds.items())))),
               "dup": json.dumps(preds)[:-1] + ', "api_unknown_device_404": true}',
               "relabel": json.dumps({k.replace("404", "4xx"): v for k, v in preds.items()})}[text]
        conn.execute("UPDATE results SET predicates = ? WHERE result_id = ?", (new, rid))
        assert bool(O.deviations(conn, root, b.truth)) == deviates, text
        conn.close()


# ---------------------------------------------------------------- standalone commissioning and report (I3, I11)

def _copy(built, work, variant="reference"):
    b = built[variant]
    conn, root = H.copy_store(b, work, False)
    return conn, root, MX.Ctx(conn, root, b.ref), b.ref.runs


def test_fv02_standalone_commissioning_keeps_every_inventory_device(built, work):
    from runner import analysis as A, db, report
    conn, root, c, runs = _copy(built, work)
    MX.del_device("dev-b")(c)
    gaps = db.commissioning_gaps(conn, runs["B"])
    assert set(gaps) == set(R.DEVICES), gaps                 # the inventory, not the devices table, sets the scope
    assert gaps["dev-b"] and gaps["dev-a"] is None, gaps
    cov = A.commissioning_coverage(conn, runs["B"])
    assert len(cov) == 11 and A.coverage_status(cov) != "COMPLETE", cov
    text = report.commissioning_section(conn)
    assert "COMPLETE" not in text.split("Latest fair baseline run:")[1].split("\n")[2], text[:800]
    assert "| dev-b | **no** |" in text, text[:800]


def test_ambiguous_run_prose_matches_the_per_device_rule(built, work):
    from runner import db, report
    conn, root, c, runs = _copy(built, work)
    MX.dup_result("B", "C-HEALTH", "dev-a", "pass", "pass")(c)
    assert db.commissioned_devices(conn, runs["B"]) == ["dev-b"]
    text = report.commissioning_section(conn)
    assert "commissions nothing" not in text and "Commissioned by it: **dev-b**" in text, text[:1500]


def test_report_never_shows_an_older_pass_for_a_planned_missing_instance(built, work):
    if not R.HAS_PLAN:
        pytest.skip("needs the schema-v5 run plan")
    from runner import report
    conn, root, c, runs = _copy(built, work)
    c.delete_result(c.rid("B", "C-HEALTH"))
    text = report.traceability_section(conn)
    assert f"C-HEALTH/dev-a: MISSING (planned in run {runs['B']}, no result)" in text, text[:2000]
    assert f"C-HEALTH/dev-a: pass (PASS) run {runs['T5']}" not in text


def test_review8_fault_table_never_shows_an_older_pass_for_a_planned_missing_instance(built, work):
    if not R.HAS_PLAN:
        pytest.skip("needs the schema-v5 run plan")
    from runner import report
    conn, root, c, runs = _copy(built, work)
    c.delete_result(c.rid("F", "FT-F2-HUNG"))
    text = report.faults_section(conn).split("### 4b")[1].split("###")[0]
    row = next(line for line in text.splitlines() if line.startswith("| F2 | F2 |"))
    assert f"(run {runs['F0']})" not in row and "MISSING" in row, row


def test_review9_report_names_the_run_a18_evaluates(built, work):
    if not R.HAS_PLAN:
        pytest.skip("needs the schema-v5 run plan")
    from runner import analysis as A, report
    conn, root, c, runs = _copy(built, work)
    b = R.Builder(conn=conn, root=root)
    newest = b.run("P", "baseline", [R.passing("C-HEALTH", "dev-a"), R.passing("C-HEALTH", "dev-b")])
    c.delete_result(conn.execute("SELECT result_id FROM results WHERE run_id = ? AND device_id = 'dev-b'",
                                 (newest,)).fetchone()[0])
    a18 = next(a for a in A.audit(conn, evidence_root=root) if a["id"].startswith("A18"))
    text = report.commissioning_section(conn)
    assert a18["run"] == runs["B"] and f"Run **{runs['B']}**" in text, (a18["run"], text[:600])
    assert "A18 evaluates it" not in text
