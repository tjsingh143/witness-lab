#!/usr/bin/env python3
"""Annotate (never rewrite or re-index) evidence files that no longer match their recorded sha256.

Found during the independent-audit remediation: the extended FT-F12 case applies F12 twice, and the injector named
its evidence by fault id only, so the second restart's fault-apply/snapshot/revert files overwrote the first
restart's files after both had been indexed (runs 133-138, commit c335c84/3a9bbbc; fixed in tests/live/conftest.py
by numbering evidence per application and refusing to overwrite any saved file). The results, attempts, exchanges,
measurements and fault_events of those runs are complete; only the first restart's four secondary files are lost.
Usage: .venv/bin/python scripts/remediation/annotate_evidence_mismatches.py DB EVIDENCE_ROOT OUT.md
"""
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from runner.report import evidence_mismatches, md_table  # noqa: E402


def main(db_path: str, root: str, out: str) -> int:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    bad = evidence_mismatches(conn, Path(root))
    n = conn.execute("SELECT count(*) FROM evidence").fetchone()[0]
    text = "\n".join([
        "# Evidence files that no longer match their recorded sha256 (annotation; nothing re-indexed)", "",
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} by "
        "`scripts/remediation/annotate_evidence_mismatches.py` (database opened read-only).", "",
        "Cause (independent-audit remediation, found by re-hashing the evidence after the first fault runs): the "
        "extended FT-F12 case restarts the device twice. The fault injector named its evidence by fault id only, so "
        "the second restart's `fault-apply-F12.json`, `snapshot-during-F12.txt`, `snapshot-ctl-during-F12.txt` and "
        "`fault-revert-F12.json` overwrote the first restart's files after both versions had been indexed. The rows "
        "below therefore describe the first restart's (lost) bytes; the files on disk hold the second restart's. "
        "The results, attempts, exchanges, measurements and fault_events of these runs are complete. Fixed in "
        "`tests/live/conftest.py`: evidence and marks are numbered per application (`F12.2`) and `Lab.save` never "
        "overwrites a saved file. Runs recorded after the fix must not appear here.", "",
        f"{n} evidence rows checked; {len(bad)} missing or different:", "",
        md_table(bad, ["run", "case", "device", "path", "recorded sha256", "now"])])
    Path(out).write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
