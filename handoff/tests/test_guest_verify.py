"""Production-contract integration on explicitly synthetic stores; no VM claims."""
import importlib.util
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'tests/unit'))
from storefix import SHA, accepted_store, baseline, fault_run, new_store

spec = importlib.util.spec_from_file_location('handoff_guest_verify', Path(__file__).resolve().parents[1]/'guest_verify.py')
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)


def test_complete_baseline_uses_real_commissioning_api(tmp_path):
    c = new_store(tmp_path/'witness.db')
    baseline(c)
    c.close()
    assert V.inspect(tmp_path, 'baseline', SHA)


def test_partial_baseline_cannot_pass(tmp_path):
    c = new_store(tmp_path/'witness.db')
    baseline(c, skip={('C-HEALTH', 'dev-b')})
    c.close()
    assert not V.inspect(tmp_path, 'baseline', SHA)


def test_wrong_revision_cannot_pass(tmp_path):
    c = new_store(tmp_path/'witness.db')
    baseline(c)
    c.close()
    assert not V.inspect(tmp_path, 'baseline', 'f'*40)


def test_fault_suite_uses_real_catalog_and_removals(tmp_path):
    c = new_store(tmp_path/'witness.db')
    fault_run(c)
    c.close()
    assert V.inspect(tmp_path, 'fault', SHA)


def test_full_audit_and_report_generation(tmp_path):
    c = new_store(tmp_path/'witness.db')
    accepted_store(c)
    c.close()
    assert V.inspect(tmp_path, 'full', SHA, 5)
    audit = json.loads((tmp_path/'acceptance.json').read_text())
    assert len(audit) == 24 and all(x['ok'] for x in audit)
    assert (tmp_path/'reports/traceability.md').exists()
    assert (tmp_path/'reports/commissioning-report.md').exists()


def test_five_ordinary_restarts_not_fresh_clones(tmp_path):
    c = new_store(tmp_path/'witness.db')
    for _ in range(5):
        baseline(c, provenance='same-restore')
    c.close()
    assert not V.inspect(tmp_path, 'baseline', SHA, 5)


def test_missing_evidence_never_becomes_acceptance(tmp_path):
    c = new_store(tmp_path/'witness.db')
    accepted_store(c)
    c.close()
    next((tmp_path/'evidence').glob('run-*/session/environment.json')).unlink()
    assert not V.inspect(tmp_path, 'full', SHA, 5)
