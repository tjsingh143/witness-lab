#!/usr/bin/env python3
"""F-07 (independent audit): annotate, never rewrite, the historical FT-F3 (wrong port) captures.

Before the remediation both capture filters were `tcp port 5020 or icmp`, so the dialled 10.77.2.11:5021 SYN and
the field kernel's RST were filtered out. This lists every FT-F3 capture indexed in the evidence table, its sha256
as recorded, whether the file is present and still matches, and how many packets it holds in total and on TCP port
5021 (tcpdump -r). Writes Markdown to OUT. The database is opened read-only; capture files are only read.
Usage: .venv/bin/python scripts/remediation/f07_annotate_historical.py DB EVIDENCE_ROOT OUT.md [MAX_RUN]
MAX_RUN (default 130, the last pre-remediation run) limits the listing to runs recorded before the fix.
"""
import hashlib
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def count(path: Path, bpf: str | None) -> int | None:
    p = subprocess.run(["tcpdump", "-nn", "-r", str(path)] + ([bpf] if bpf else []), capture_output=True, text=True,
                       timeout=20)
    return None if p.returncode != 0 else sum(1 for x in p.stdout.splitlines() if x.strip())


def main(db_path: str, root: str, out: str, max_run: str = "130") -> int:
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = c.execute("""SELECT r.run_id, r.result_id, r.observed_category, e.kind, e.path, e.sha256, e.bytes
                        FROM results r JOIN evidence e USING (result_id)
                        WHERE r.case_id = 'FT-F3-WRONG-PORT' AND e.kind IN ('pcap', 'pcap-field')
                          AND r.run_id <= ? ORDER BY r.run_id, e.kind""", (int(max_run),)).fetchall()
    lines = ["# F-07: historical FT-F3 captures (annotation; the captures themselves are unchanged)", "",
             f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} by "
             "`scripts/remediation/f07_annotate_historical.py` from the evidence table (read-only).", "",
             "Until the independent-audit remediation, the ctl capture (runner/lab.py `Capture`) and the field capture "
             "(`witness-faultctl capture start`) both used the fixed filter `tcp port 5020 or icmp`. FT-F3 dials the "
             "wrong inventory port 5021, so its SYN and the field kernel's RST were never captured: these files hold "
             "only gateway/runner traffic on 5020. Their CONN_REFUSED results stand on the socket observation "
             "(ECONNREFUSED) and the 5020 control probe, not on packet evidence of the tested flow. Captures recorded "
             "after the fix include the fault's port and every result carries a `capture_flows` check.", "",
             "| run | result | observed | capture | file | sha256 matches record | packets | packets on tcp port 5021 |",
             "|---|---|---|---|---|---|---|---|"]
    bad = 0
    for run, rid, obs, kind, rel, sha, nbytes in rows:
        p = Path(root) / rel
        present = p.exists()
        same = present and hashlib.sha256(p.read_bytes()).hexdigest() == sha
        total = count(p, None) if present else None
        on5021 = count(p, "tcp port 5021") if present else None
        bad += bool(on5021 == 0)
        lines.append(f"| {run} | {rid} | {obs} | {'ctl lab0' if kind == 'pcap' else 'field lab0'} | `{rel}` | "
                     f"{'yes' if same else 'FILE MISSING' if not present else 'NO'} | {total if present else '-'} | "
                     f"{on5021 if present else '-'} |")
    lines += ["", f"{len(rows)} FT-F3 captures of runs <= {max_run} indexed; {bad} present captures contain 0 packets of the "
              "dialled port-5021 flow.", ""]
    Path(out).write_text("\n".join(lines))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:5]))
