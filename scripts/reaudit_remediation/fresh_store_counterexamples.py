"""Second-audit remediation: the re-audit's R-01/R-02 counterexamples applied to a disposable copy of a FRESH store
recorded on the current code (its latest baseline and fault run are found by kind, not by number), with byte
verification against that store's evidence root. The source database is opened read-only; its sha256 is checked.

    .venv/bin/python scripts/reaudit_remediation/fresh_store_counterexamples.py DB EVIDENCE_ROOT SCRATCH"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from runner import analysis as A, db  # noqa: E402
from scripts.reaudit_remediation.acceptance_probes import copy, duplicate, reindex, scratch_root, strip_port  # noqa: E402


def main() -> int:
    src_path, root, scratch = Path(sys.argv[1]), Path(sys.argv[2]).resolve(), Path(sys.argv[3])
    before = hashlib.sha256(src_path.read_bytes()).hexdigest()
    src = sqlite3.connect(src_path.resolve().as_uri() + "?mode=ro", uri=True)
    base = src.execute("SELECT max(run_id) FROM runs WHERE kind='baseline'").fetchone()[0]
    fault = src.execute("SELECT max(run_id) FROM runs WHERE kind='fault'").fetchone()[0]
    f3 = f"SELECT result_id FROM results WHERE run_id={fault} AND case_id='FT-F3-WRONG-PORT'"
    print("SOURCE", src_path, before, "baseline run", base, "fault run", fault)

    def stripped(c):
        r = scratch_root(root, scratch, "fresh-metadata-only", (f"run-{fault}",))
        rel = f"run-{fault}/FT-F3-WRONG-PORT__dev-a/capture-field.pcap"
        print("  stripped", strip_port(r / rel, 5021), "packets of port 5021 from", rel)
        reindex(c, r, rel)
        return r

    probes = {
        "control_unmodified": (lambda c: root, set()),
        "R01_whitespace_python": (lambda c: (c.execute("UPDATE environment SET value=char(9)||char(10) WHERE run_id=? "
                                                       "AND key='python'", (base,)), root)[1], {"A13", "A18"}),
        "R01_invalid_offset": (lambda c: (c.execute("UPDATE environment SET value='offset_s=garbage' WHERE run_id=? "
                                                    "AND key='chrony.offset'", (base,)), root)[1], {"A13", "A18"}),
        "R01_conflicting_git_sha": (lambda c: (c.execute("UPDATE environment SET value='not-the-run-revision' WHERE "
                                                         "run_id=? AND key='git_sha'", (base,)), root)[1], {"A13", "A18"}),
        "R01_conflicting_run_level_duplicates": (lambda c: (duplicate(c, base, "C-ENVIRONMENT", None,
                                                                      [("fail", "runner"), ("pass", "none")]), root)[1],
                                                 {"A4", "A18", "A19"}),
        "R02_missing_field_flow": (lambda c: (c.execute(f"DELETE FROM capture_flows WHERE capture='field' AND result_id "
                                                        f"IN ({f3})"), root)[1], {"A17"}),
        "R02_declared_not_expected": (lambda c: (c.execute(f"UPDATE capture_flows SET expected=0, packets=0 WHERE "
                                                           f"result_id IN ({f3})"), root)[1], {"A17"}),
        "R02_metadata_without_packets": (stripped, {"A20"}),
    }
    bad = 0
    for name, (action, expect) in probes.items():
        c = copy(src)
        r = action(c)
        a = A.audit(c, evidence_root=r)
        got = {x["id"].split("-")[0] for x in a if not x["ok"]} - {"A12", "A14", "A15"}   # absent evidence classes
        ok = (expect <= got) if expect else not got
        bad += not ok
        print(f"{'MATCH   ' if ok else 'MISMATCH'} {name}: expect {sorted(expect) or 'none'} (besides A12/A14/A15); "
              + json.dumps({"violated": sorted(got, key=lambda k: int(k[1:])),
                            "reasons": {x["id"].split("-")[0]: x["violations"][:2] for x in a
                                        if not x["ok"] and x["id"].split("-")[0] in got},
                            "commissioned": db.commissioned_devices(c, base)}))
        c.close()
    after = hashlib.sha256(src_path.read_bytes()).hexdigest()
    print("SOURCE_HASH_UNCHANGED", before == after, "MISMATCHES", bad)
    return 0 if bad == 0 and before == after else 1


if __name__ == "__main__":
    sys.exit(main())
