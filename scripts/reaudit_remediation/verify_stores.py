"""Second-audit remediation: verify recorded stores with the repaired acceptance checker, on fresh verified copies.

For each STORE:EVIDENCE_ROOT pair: copy the database to SCRATCH (source sha256 checked before and after; the copy's
bytes equal the source's), then on the copy: PRAGMA integrity_check and foreign_key_check, schema version, all 21
acceptance assertions with byte verification against the evidence root, the size of the current evidence set, an
independent recount of EVERY capture_flows row with a dialled-flow filter (runner/evidence.flow_packets) compared with
both the stored count and tcpdump on the same indexed file, and a NON-GATING listing of what A17/A20's derivation finds
in superseded fair runs (outside the current evidence by design; reported, never rewritten).

    .venv/bin/python scripts/reaudit_remediation/verify_stores.py SCRATCH DB:ROOT [DB:ROOT ...]"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from runner import analysis as A, evidence as EV, lab as L  # noqa: E402


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify(db_path: Path, root: Path, scratch: Path) -> bool:
    before = sha(db_path)
    copy = scratch / f"{db_path.stem}-verify-copy.db"
    shutil.copyfile(db_path, copy)
    assert sha(copy) == before, "copy differs from source"
    print(f"== {db_path} sha256 {before}\n   copy {copy}\n   evidence root {root}")
    conn = sqlite3.connect(copy.resolve().as_uri() + "?mode=ro", uri=True)
    print("   integrity_check:", conn.execute("PRAGMA integrity_check").fetchone()[0],
          "| foreign_key_check rows:", len(conn.execute("PRAGMA foreign_key_check").fetchall()),
          "| schema:", [r[0] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version")],
          "| runs:", conn.execute("SELECT count(*), max(run_id) FROM runs").fetchone())
    res = A.audit(conn, evidence_root=root)
    for a in res:
        print(f"   {'HOLDS   ' if a['ok'] else 'VIOLATED'} {a['id']}" + ("" if a["ok"] else f" -> {a['violations'][:6]}"))
    print(f"   {sum(a['ok'] for a in res)}/{len(res)} hold")
    a14 = next(a for a in res if a["id"].startswith("A14"))
    a18 = next(a for a in res if a["id"].startswith("A18"))
    cur = A.current_evidence(conn, a14.get("runs", []), a18.get("run"))
    plan = A.flow_plan(conn, cur, A._sources(conn))
    n_ev = conn.execute("SELECT count(*) FROM evidence WHERE result_id IN (SELECT value FROM json_each(?))",
                        (json.dumps(sorted(cur)),)).fetchone()[0]
    print(f"   current evidence: {len(cur)} results; {len({p['run_id'] for p in plan.values()})} dialled "
          f"runs; {len(plan)} results dialled; {sum(len(p['flows']) for p in plan.values())} derived flows; "
          f"{n_ev} indexed files of current results (+ session files of their runs)")
    # independent recount of every stored flow count (all runs), against the stored count and tcpdump
    rows = conn.execute("SELECT f.result_id, f.capture, f.filter, f.packets, e.path FROM capture_flows f JOIN evidence e "
                        "ON e.result_id = f.result_id AND e.kind = CASE f.capture WHEN 'ctl' THEN 'pcap' ELSE "
                        "'pcap-field' END WHERE f.packets IS NOT NULL AND f.filter LIKE 'tcp %'").fetchall() \
        if A._has(conn, "capture_flows") else []
    agree = disagree = 0
    tcpdump = shutil.which("tcpdump")
    for rid, cap, bpf, n, rel in rows:
        data = (root / rel).read_bytes()
        mine = EV.flow_packets(data, bpf)
        td = L.count_packets(root / rel, bpf) if tcpdump else None
        if mine == n and (td is None or td == n):
            agree += 1
        else:
            disagree += 1
            print(f"   RECOUNT DIFFERS result {rid} {cap} {bpf}: stored {n}, independent {mine}, tcpdump {td}")
    print(f"   stored flow counts recounted: {len(rows)}; agree (stored = independent recount"
          f"{' = tcpdump' if tcpdump else ''}): {agree}; differ: {disagree}")
    # non-gating: the same derivation over every fair result, to show superseded runs honestly
    fair = {r[0]: "fair" for r in conn.execute("SELECT r.result_id FROM results r JOIN runs ru USING (run_id) WHERE "
                                               + A.FAIR)}
    all_plan = A.flow_plan(conn, fair, A._sources(conn))
    extra17 = [v for v in A.capture_flow_violations(conn, all_plan, A._sources(conn))
               if v not in next(a for a in res if a["id"].startswith("A17"))["violations"]]
    extra20 = [v for v in A.evidence_violations(conn, fair, all_plan, root)
               if v not in next(a for a in res if a["id"].startswith("A20"))["violations"]]
    print(f"   NON-GATING, superseded fair results only: {len(extra17)} capture-flow findings, {len(extra20)} byte findings")
    groups: dict[str, dict[str, set]] = {}
    for v in extra17 + extra20:
        label, what = v.split(": ", 1)
        kind = next((k for k in ("has no record of dialled flow", "is not accounted for", "differs from its index",
                                 ": missing", "holds no packet of dialled flow", "record says",
                                 "indexed ctl capture files", "indexed field capture files", "cannot be verified",
                                 "contradicts", "says expected=") if k in what), "other")
        g = groups.setdefault(kind, {"runs": set(), "cases": set()})
        g["runs"].add(int(label.split()[0][3:]))
        g["cases"].add(label.split()[1].split("/")[0])
        g["n"] = g.get("n", 0) + 1
    for kind, g in groups.items():
        print(f"      {g['n']:4d} x '{kind}': runs {sorted(g['runs'])}; cases {sorted(g['cases'])}")
    conn.close()
    after = sha(db_path)
    print("   source unchanged:", after == before)
    return after == before and disagree == 0


def main() -> int:
    scratch = Path(sys.argv[1])
    scratch.mkdir(parents=True, exist_ok=True)
    ok = True
    for arg in sys.argv[2:]:
        dbp, root = arg.split(":", 1)
        ok &= verify(Path(dbp), Path(root), scratch)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
