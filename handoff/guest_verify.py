"""Read-only evidence evaluation on the dedicated controller; never edits result rows."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, '/opt/witness-lab')
from runner import analysis as A, db, catalog


def inspect(root, kind, revision, count=0):
    root = Path(root)
    conn = sqlite3.connect((root / 'witness.db').as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    checks = {}
    checks['sqlite_integrity'] = conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    checks['foreign_keys'] = not conn.execute('PRAGMA foreign_key_check').fetchall()
    runs = [dict(r) for r in conn.execute('SELECT * FROM runs ORDER BY run_id')]
    checks['exact_source'] = bool(runs) and all(r['git_sha'] == revision and r['git_dirty'] == 0 for r in runs)
    latest = runs[-1]['run_id'] if runs else None
    rr = [dict(r) for r in conn.execute('SELECT * FROM results WHERE run_id=?', (latest,))]
    audit = A.audit(conn, evidence_root=root / 'evidence')
    if kind in ('baseline', 'fresh'):
        checks['complete_commissioning'] = bool(latest) and not any(db.commissioning_gaps(conn, latest, evidence_root=root/'evidence').values())
        checks['eleven_retry_free_passes'] = len(rr) == 11 and all(r['verdict'] == 'pass' and r['attempts'] <= 1 for r in rr)
    elif kind == 'fault':
        checks['24_fault_instances'] = len(rr) == 24 and all(r['verdict'] == 'pass' for r in rr)
        checks['25_verified_removals'] = conn.execute('SELECT count(*) FROM fault_events WHERE run_id=? AND removal_verified=1', (latest,)).fetchone()[0] == 25
    elif kind == 'mutant':
        rows = [dict(r) for r in conn.execute(A.MUTANT_RUNS, {'mdev': catalog.MUTANT_DEVICE}) if r['run_id'] == latest]
        checks['genuine_detection_and_stock_control'] = bool(rows) and all(r['fair'] and r['results'] == 11 and not r['harness_or_infra'] and r['caught_cases'] > 0 and r['control_nonpass'] == 0 for r in rows)
    elif kind == 'deadline':
        checks['one_runner_deadline_error'] = len(rr) == 1 and rr[0]['verdict'] == 'error' and rr[0]['attribution'] == 'runner' and 'deadline' in rr[0]['detail'].lower()
        # The configured budget stays 30.0; allow only 100 ms row-persistence overhead.
        checks['deadline_observed'] = len(rr) == 1 and 29900 < rr[0]['duration_ms'] < 30100
        checks['negative_store_integrity'] = all(x['ok'] for x in audit if x['id'].startswith(('A23-', 'A24-')))
    elif kind == 'control':
        checks['one_targeted_control_pass'] = len(rr) == 1 and rr[0]['verdict'] == 'pass' and rr[0]['duration_ms'] <= 30000
        checks['control_evidence_integrity'] = all(x['ok'] for x in audit if x['id'].startswith(('A23-', 'A24-')))
    elif kind == 'interruption':
        checks['interrupted_session_integrity'] = all(x['ok'] for x in audit if x['id'].startswith(('A23-', 'A24-')))
    elif kind == 'full':
        checks['all_24_assertions'] = len(audit) == 24 and all(x['ok'] for x in audit)
    if count:
        trials = A.fresh_trial_runs(conn, 'witness-ctl', 'witness-field')
        checks['distinct_restoration_count'] = len(trials) == count
        checks['all_restorations_commission'] = all(not A.trial_problems(conn, r, root=root/'evidence') for r in trials)
    result = {'kind': kind, 'checks': checks, 'ok': all(checks.values()), 'runs': runs, 'latest_results': rr, 'audit': audit}
    (root / ('verification-' + kind + '.json')).write_text(json.dumps(result, indent=2) + '\n')
    if kind == 'full':
        from runner.report import build_all
        out = root / 'reports'
        out.mkdir(exist_ok=True)
        for name, content in build_all(conn, root/'evidence').items():
            (out/name).write_text(content)
        (root/'acceptance.json').write_text(json.dumps(audit, indent=2)+'\n')
    print(json.dumps({'kind': kind, 'checks': checks, 'ok': result['ok']}, indent=2))
    return result['ok']


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('root')
    p.add_argument('kind')
    p.add_argument('revision')
    p.add_argument('--count', type=int, default=0)
    a = p.parse_args()
    raise SystemExit(0 if inspect(a.root, a.kind, a.revision, a.count) else 1)
