#!/usr/bin/env python3
"""F-06 (independent audit): apply the audit's two adversarial data edits to a SCRATCH COPY of a results database
and show that each now makes the acceptance audit fail. The source database is opened read-only and never changed.

  1. delete kernel/distro/qdisc/nft of witness-field, fw_version.dev-b, git_dirty and chrony.offset, blank python
     -> A13 must be violated (pre-remediation: A13 held)
  2. every fresh-trial C-HEALTH result -> fail/device
     -> A14 must be violated (pre-remediation: all 15 assertions held)
Usage: .venv/bin/python scripts/remediation/acceptance_counterexamples.py SOURCE.db SCRATCH_DIR
Exit 0 iff both counterexamples produce the expected violation.
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from runner import analysis as A, db  # noqa: E402

EDITS = {
    "1-environment": ("A13-environment-recorded", [
        "DELETE FROM environment WHERE key IN ('kernel.witness-field','distro.witness-field','qdisc.witness-field',"
        "'nft.witness-field','fw_version.dev-b','git_dirty','chrony.offset')",
        "UPDATE environment SET value='' WHERE key='python'"]),
    "2-fresh-health-fail": ("A14-fresh-baselines", [
        "UPDATE results SET verdict='fail', attribution='device' WHERE case_id='C-HEALTH' AND run_id IN "
        "(SELECT value FROM json_each(:fresh))"]),
}


def summary(conn) -> dict:
    return {a["id"]: (a["ok"], len(a["violations"])) for a in A.audit(conn)}


def main(src: str, scratch: str) -> int:
    Path(scratch).mkdir(parents=True, exist_ok=True)
    ok = True
    ro = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    for name, (want, stmts) in EDITS.items():
        dst = Path(scratch) / f"counterexample-{name}.db"
        dst.unlink(missing_ok=True)
        out = sqlite3.connect(dst)
        ro.backup(out)
        out.close()
        conn = db.connect(dst)                      # the scratch copy may be migrated; the source never is
        before = summary(conn)
        fresh = A.fresh_trial_runs(conn, "witness-ctl", "witness-field")
        for s in stmts:
            conn.execute(s, {"fresh": json.dumps(fresh)})
        conn.commit()
        after = summary(conn)
        hit = before[want][0] and not after[want][0]
        ok &= hit
        changed = {k: (before[k], after[k]) for k in after if after[k] != before[k]}
        print(json.dumps({"counterexample": name, "fresh_trials": fresh, "expected_violation": want,
                          "held_before_edit": before[want][0], "violated_after_edit": not after[want][0],
                          "changed_assertions": changed,
                          "violations": next(a["violations"][:8] for a in A.audit(conn) if a["id"] == want)}))
        conn.close()
    ro.close()
    print("RESULT", "PASS: each audit counterexample now fails acceptance" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
