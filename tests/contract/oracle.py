"""Independent reference oracle for the acceptance-contract harness.

Shares no code with the production verifiers (runner/analysis.py, runner/contract.py, the commissioning SQL in
runner/db.py). Ground truth is the reference store as built: a projection of every obligation-bearing record, taken
with this module's own SQL, plus the SHA-256 of every file of its evidence tree. A mutated store is judged by
comparison with that truth: any obligation-bearing record missing, added, duplicated, changed or orphaned, any file
missing, added or changed, or a failed SQLite integrity/foreign-key check, is a deviation. A store without
deviations has exactly the acceptance outcome its variant declares (refstore.Ref.expected_failures).

Columns outside the projection (free-text details, notes beyond the runner's contamination/abort markers, durations,
latencies, timestamps of results) carry no obligation under docs/acceptance-contract.md; mutations confined to them
are benign. The decision predicates (results.predicates) are projected as their name/value pairs in name order, every
pair kept: the order of a JSON object is no obligation, a name recorded twice is (independent contract verification:
this projection had omitted them, so erasing a decision was no deviation).
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

RKEY = "r.run_id, r.case_id, r.device_id"
PROJECTION = {
    "runs": "SELECT run_id, kind, mutant_id, git_sha, git_dirty, clean_env, contaminated, finished_at IS NOT NULL, "
            "started_at, coalesce(notes, '') FROM runs",
    "run_plan": "SELECT run_id, case_id, device_id FROM run_plan",
    "environment": "SELECT run_id, key, value FROM environment",
    "results": f"SELECT {RKEY}, r.fault_id, r.expected_category, r.observed_category, r.first_attempt_category, "
               "r.attempts, r.verdict, r.attribution, r.preflight, r.postflight, r.evidence_path, {predicates} "
               "FROM results r",
    "attempts": f"SELECT {RKEY}, a.attempt_no, a.category, a.outcome, a.predicates, a.stage, a.detail "
                "FROM attempts a JOIN results r USING (result_id)",
    "exchanges": f"SELECT {RKEY}, a.attempt_no, x.ord, x.cmd, x.req_id, x.host, x.addr, x.port, x.local_port, "
                 "x.category, x.stage_failed, x.os_error, x.read_end, x.detail, x.bytes, x.t_send, x.response "
                 "FROM exchanges x JOIN attempts a USING (attempt_id) JOIN results r USING (result_id)",
    "capture_flows": f"SELECT {RKEY}, f.capture, f.filter, f.expected, f.packets "
                     "FROM capture_flows f JOIN results r USING (result_id)",
    "evidence": "SELECT e.run_id, r.case_id, r.device_id, e.result_id IS NULL, e.kind, e.path, e.sha256, e.bytes "
                "FROM evidence e LEFT JOIN results r USING (result_id)",
    "checks": "SELECT c.run_id, r.case_id, r.device_id, c.result_id IS NULL, c.phase, c.vm, c.name, c.status "
              "FROM checks c LEFT JOIN results r USING (result_id)",
    "fault_events": f"SELECT e.run_id, {RKEY}, e.fault_id, e.vm, e.removal_verified, e.applied_at IS NOT NULL, "
                    "e.removed_at IS NOT NULL FROM fault_events e LEFT JOIN results r USING (result_id)",
    "measurements": f"SELECT {RKEY}, m.name, m.value, m.unit, m.bound FROM measurements m JOIN results r "
                    "USING (result_id)",
    "requirements": "SELECT * FROM requirements",
    "cases": "SELECT * FROM cases",
    "case_requirements": "SELECT * FROM case_requirements",
    "devices": "SELECT * FROM devices",
    "faults": "SELECT * FROM faults",
    "mutants": "SELECT * FROM mutants",
    "schema_migrations": "SELECT version, applied_at FROM schema_migrations",
}
# rows of a child table whose parent is gone (a JOIN above would silently drop them)
ORPHANS = {
    "attempts": "SELECT count(*) FROM attempts WHERE result_id NOT IN (SELECT result_id FROM results)",
    "exchanges": "SELECT count(*) FROM exchanges WHERE attempt_id NOT IN (SELECT attempt_id FROM attempts)",
    "capture_flows": "SELECT count(*) FROM capture_flows WHERE result_id NOT IN (SELECT result_id FROM results)",
    "measurements": "SELECT count(*) FROM measurements WHERE result_id NOT IN (SELECT result_id FROM results)",
    "evidence": "SELECT count(*) FROM evidence WHERE result_id IS NOT NULL AND result_id NOT IN "
                "(SELECT result_id FROM results)",
    "results.device": "SELECT count(*) FROM results WHERE device_id IS NOT NULL AND device_id NOT IN "
                      "(SELECT device_id FROM devices)",
}


def _tables(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _markers(row: tuple) -> tuple:
    """A run's notes as the obligations they carry: whether the runner recorded a contamination/abort cause, and the
    runs each abort marker names as its detector."""
    notes = row[-1]
    return row[:-1] + ("contaminated:" in notes or "aborted:" in notes,
                       tuple(re.findall(r"aborted: never finished \(detected by run (\d+)\)", notes)))


def _pairs(row: tuple) -> tuple:
    text = row[-1]
    if text is None:
        return row
    try:
        value = json.loads(text, object_pairs_hook=lambda p: ("object", tuple(sorted(p, key=repr))))
    except ValueError:
        value = ("unreadable", text)
    return row[:-1] + (repr(value),)


CANON = {"runs": _markers, "results": _pairs}


def projection(conn: sqlite3.Connection) -> dict[str, Counter]:
    have = _tables(conn)
    preds = "r.predicates" if any(r[1] == "predicates" for r in conn.execute("PRAGMA table_info(results)")) \
        else "NULL"
    out = {}
    for t, sql in PROJECTION.items():
        if t in have:
            canon = CANON.get(t, lambda row: row)
            out[t] = Counter(canon(tuple(r)) for r in conn.execute(sql.replace("{predicates}", preds)).fetchall())
    for t, sql in ORPHANS.items():
        if t.split(".")[0] in have:
            out[f"orphans:{t}"] = Counter({("n", conn.execute(sql).fetchone()[0]): 1})
    return out


def files(root: Path) -> dict[str, str]:
    root = Path(root)
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()} if root.is_dir() else {}


def truth(conn: sqlite3.Connection, root: Path) -> dict:
    return {"projection": projection(conn), "files": files(root)}


def deviations(conn: sqlite3.Connection, root: Path, want: dict) -> list[str]:
    """Every difference between the store and the truth (empty = the store realizes the truth exactly)."""
    out = []
    if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        out.append("sqlite integrity_check fails")
    if conn.execute("PRAGMA foreign_key_check").fetchall():
        out.append("foreign_key_check: orphaned rows")
    got = projection(conn)
    for t in sorted(set(want["projection"]) | set(got)):
        w, g = want["projection"].get(t, Counter()), got.get(t, Counter())
        if w != g:
            miss, extra = w - g, g - w
            out.append(f"{t}: {sum(miss.values())} missing/changed, {sum(extra.values())} added/changed"
                       + (f" e.g. -{next(iter(miss))!r:.120}" if miss else "")
                       + (f" +{next(iter(extra))!r:.120}" if extra else ""))
    have = files(root)
    for p in sorted(set(want["files"]) | set(have)):
        if want["files"].get(p) != have.get(p):
            out.append(f"file {p}: " + ("missing" if p not in have else "added" if p not in want["files"]
                                        else "bytes changed"))
    return out


def verdict(conn, root, want: dict, expected_failures: frozenset) -> tuple[str, list[str]]:
    """('ACCEPT' | 'REJECT', why). A deviating store is never acceptable; otherwise the variant's declaration."""
    dev = deviations(conn, root, want)
    if dev:
        return "REJECT", dev
    return ("ACCEPT", []) if not expected_failures else ("REJECT", [f"variant expects {sorted(expected_failures)}"])
