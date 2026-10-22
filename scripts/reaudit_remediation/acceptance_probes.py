"""Second independent audit (docs/independent-reaudit.md, R-01/R-02 and related holes): adversarial acceptance probes.

Every probe edits a DISPOSABLE in-memory copy of the store (the source is opened read-only and its sha256 is checked
before and after) and, for byte-level probes, a scratch evidence root (symlinks to the real run directories, with the
tampered run directory copied). Each probe states which acceptance assertions MUST reject it after the repair; the
log prints every violated assertion so the reason is visible, and "MATCH"/"MISMATCH" against that expectation.
Run before and after the repair: before, most probes are expected to report MISMATCH (that is the reproduction).

    .venv/bin/python scripts/reaudit_remediation/acceptance_probes.py results/witness.db results/evidence SCRATCH_DIR

Fixture edits are SQL written here, never production helpers; the pcap rewrite uses its own minimal parser."""
from __future__ import annotations

import hashlib
import inspect
import json
import shutil
import sqlite3
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from runner import analysis as A, db  # noqa: E402

SIG = inspect.signature(A.audit).parameters


def copy(src: sqlite3.Connection) -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    src.backup(c)
    c.execute("PRAGMA foreign_keys = ON")
    return c


def run_audit(c, root):
    kw = {"evidence_root": root} if "evidence_root" in SIG else {}
    return A.audit(c, **kw)


def delete_results(c, where: str) -> int:
    """Delete results matching `where` and every row that references them (FK-safe order)."""
    ids = [r[0] for r in c.execute(f"SELECT result_id FROM results WHERE {where}")]
    q = ",".join(map(str, ids)) or "NULL"
    c.execute(f"DELETE FROM exchanges WHERE attempt_id IN (SELECT attempt_id FROM attempts WHERE result_id IN ({q}))")
    for t in ("attempts", "checks", "evidence", "measurements", "capture_flows", "fault_events"):
        c.execute(f"DELETE FROM {t} WHERE result_id IN ({q})")
    c.execute(f"DELETE FROM results WHERE result_id IN ({q})")
    return len(ids)


def duplicate(c, run, case, dev, rows):
    """Insert copies of the (run, case, dev) result with the given (verdict, attribution) pairs, in order."""
    base = dict(c.execute("SELECT * FROM results WHERE run_id=? AND case_id=? AND device_id IS ?", (run, case, dev))
                .fetchone())
    base.pop("result_id")
    for verdict, attr in rows:
        base.update(verdict=verdict, attribution=attr, detail="probe: conflicting duplicate")
        c.execute("INSERT INTO results (" + ",".join(base) + ") VALUES (" + ",".join("?" * len(base)) + ")",
                  tuple(base.values()))


# ---- minimal classic-pcap rewrite (little-endian, Ethernet/IPv4/TCP), independent of runner code
def strip_port(path: Path, port: int) -> int:
    data = path.read_bytes()
    out, off, removed = bytearray(data[:24]), 24, 0
    assert struct.unpack("<I", data[:4])[0] == 0xA1B2C3D4 and struct.unpack("<I", data[20:24])[0] == 1
    while off + 16 <= len(data):
        incl = struct.unpack("<I", data[off + 8:off + 12])[0]
        rec = data[off:off + 16 + incl]
        pkt = rec[16:]
        drop = False
        if len(pkt) >= 34 and pkt[12:14] == b"\x08\x00" and pkt[23] == 6:
            ihl = (pkt[14] & 0x0F) * 4
            sport, dport = struct.unpack(">HH", pkt[14 + ihl:18 + ihl])
            drop = port in (sport, dport)
        if drop:
            removed += 1
        else:
            out += rec
        off += 16 + incl
    path.write_bytes(bytes(out))
    return removed


def scratch_root(real: Path, scratch: Path, name: str, copy_runs: tuple[str, ...]) -> Path:
    root = scratch / name
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    for p in real.iterdir():
        if p.name in copy_runs:
            shutil.copytree(p, root / p.name)
        else:
            (root / p.name).symlink_to(p.resolve())
    return root


def reindex(c, root: Path, rel: str) -> None:
    data = (root / rel).read_bytes()
    c.execute("UPDATE evidence SET sha256=?, bytes=? WHERE path=?", (hashlib.sha256(data).hexdigest(), len(data), rel))


F3 = "SELECT result_id FROM results WHERE run_id=146 AND case_id='FT-F3-WRONG-PORT'"
F4 = "SELECT result_id FROM results WHERE run_id=146 AND case_id='FT-F4-WRONG-ADDR'"
ENV150 = "UPDATE environment SET value={v} WHERE run_id=150 AND key='{k}'"


def env150(k, v):
    return [ENV150.format(k=k, v=v)]


# name -> (sql statements | callable(conn, scratch, real_root) -> root, assertions that must be violated)
# An empty expectation means: a control that must keep holding (with the stated commissioning outcome).
PROBES = {
    # ---------------- R-01: environment evidence
    "env_whitespace_python": (env150("python", "char(9)||char(10)"), {"A13", "A18"}),
    "env_offset_garbage": (env150("chrony.offset", "'offset_s=garbage'"), {"A13", "A18"}),
    "env_offset_nan": (env150("chrony.offset", "'offset_s=nan delay_s=nan samples=0/4 server=10.77.1.10'"),
                       {"A13", "A18"}),
    "env_offset_outside_clock_gate": (env150("chrony.offset",
                                             "'offset_s=+5.000000 delay_s=0.000300 samples=4/4 server=10.77.1.10'"),
                                      {"A13", "A18"}),
    "env_git_sha_text": (env150("git_sha", "'not-the-run-revision'"), {"A13", "A18"}),
    "env_git_sha_other_hex": (env150("git_sha", "'" + "0" * 40 + "'"), {"A13", "A18"}),
    "env_git_dirty_contradicts_run": (env150("git_dirty", "'1'"), {"A13", "A18"}),
    "env_clean_env_contradicts_run": (env150("runs.clean_env", "'0'"), {"A13", "A18"}),
    "env_blob_python": (env150("python", "CAST('3.12.3' AS BLOB)"), {"A13", "A18"}),
    "env_missing_field_kernel": (["DELETE FROM environment WHERE run_id=150 AND key='kernel.witness-field'"],
                                 {"A13", "A18"}),
    "env_kernel_garbage": (env150("kernel.witness-ctl", "'unknown'"), {"A13", "A18"}),
    "env_qdisc_missing_field0": (env150("qdisc.witness-field", "'lab0: qdisc fq_codel 0: root refcnt 2'"),
                                 {"A13", "A18"}),
    "env_nft_without_table": (env150("nft.witness-ctl", "'# nothing'"), {"A13", "A18"}),
    "env_kind_contradicts_run": (env150("runs.kind", "'fault'"), {"A13", "A18"}),
    "env_build_contradicts_field_record": (env150("device_build.a.witness-field", "'mutant:seq-reuse'"),
                                           {"A13", "A18"}),
    "env_near_duplicate_key": (["INSERT INTO environment VALUES (150, 'python ', '2.7.18')"], {"A13", "A18"}),
    "env_withheld_fw_of_control_device_in_mutant_run": (
        ["UPDATE environment SET value='unavailable (MALFORMED: incomplete:86B)' WHERE run_id=139 "
         "AND key='fw_version.dev-b'"], {"A13"}),
    "env_withheld_fw_without_category_in_mutant_run": (
        ["UPDATE environment SET value='unavailable' WHERE run_id=141 AND key='fw_version.dev-a'"], {"A13"}),
    "env_withheld_fw_in_fault_run": (
        ["UPDATE environment SET value='unavailable (READ_TIMEOUT: x)' WHERE run_id=146 AND key='fw_version.dev-a'"],
        {"A13"}),
    "control_invalid_env_in_unfair_run": (
        ["UPDATE environment SET value='' WHERE run_id=18 AND key='python'"], set()),
    # ---------------- R-01: result cardinality / conflicting duplicates
    "dup_runlevel_fail_then_pass": (lambda c, s, r: duplicate(c, 150, "C-ENVIRONMENT", None,
                                                              [("fail", "runner"), ("pass", "none")]),
                                    {"A4", "A18", "A19"}),
    "dup_runlevel_pass_then_fail": (lambda c, s, r: duplicate(c, 150, "C-ENVIRONMENT", None,
                                                              [("pass", "none"), ("fail", "runner")]),
                                    {"A4", "A18", "A19"}),
    "dup_device_fail_then_pass": (lambda c, s, r: duplicate(c, 150, "C-HEALTH", "dev-a",
                                                            [("fail", "device"), ("pass", "none")]),
                                  {"A4", "A18", "A19"}),
    "dup_device_pass_then_fail": (lambda c, s, r: duplicate(c, 150, "C-HEALTH", "dev-a",
                                                            [("pass", "none"), ("fail", "device")]),
                                  {"A4", "A18", "A19"}),
    "dup_identical_pass": (lambda c, s, r: duplicate(c, 150, "C-HEALTH", "dev-b", [("pass", "none")]),
                           {"A18", "A19"}),
    "dup_fault_case_conflict": (lambda c, s, r: duplicate(c, 146, "FT-F3-WRONG-PORT", "dev-a", [("fail", "device")]),
                                {"A4", "A19"}),
    "instance_runlevel_case_with_device": (
        ["INSERT INTO results (run_id,case_id,device_id,verdict,attribution,preflight,postflight,observed_at,attempts)"
         " VALUES (150,'C-ENVIRONMENT','dev-a','pass','none','green','green','2026-10-18T01:13:30.000Z',0)"], {"A19"}),
    "control_partial_latest_baseline": (lambda c, s, r: delete_results(c, "run_id=150 AND case_id='C-GATEWAY'"),
                                        set()),
    "control_contaminated_latest_baseline": (["UPDATE runs SET contaminated=1 WHERE run_id=150"], set()),
    "control_unfinished_latest_baseline": (["UPDATE runs SET finished_at=NULL WHERE run_id=150"], set()),
    # ---------------- R-02: capture-flow evidence
    "flow_delete_field_side": ([f"DELETE FROM capture_flows WHERE capture='field' AND result_id IN ({F3})"], {"A17"}),
    "flow_delete_ctl_side": ([f"DELETE FROM capture_flows WHERE capture='ctl' AND result_id IN ({F3})"], {"A17"}),
    "flow_declared_not_expected": ([f"UPDATE capture_flows SET expected=0, packets=0 WHERE result_id IN ({F3})"],
                                   {"A17"}),
    "flow_delete_all": ([f"DELETE FROM capture_flows WHERE result_id IN ({F3})"], {"A17"}),
    "flow_filter_retargeted_to_gateway_port": (
        [f"UPDATE capture_flows SET filter='tcp and host 10.77.2.11 and port 5020' WHERE result_id IN ({F3})"],
        {"A17"}),
    "flow_forged_no_route_justification": (
        [f"UPDATE exchanges SET os_error='ENETUNREACH' WHERE attempt_id IN (SELECT attempt_id FROM attempts "
         f"WHERE result_id IN ({F4}))", f"UPDATE capture_flows SET expected=0 WHERE result_id IN ({F4})"], {"A17"}),
    "flow_forged_no_address_justification": (
        [f"UPDATE exchanges SET addr=NULL WHERE attempt_id IN (SELECT attempt_id FROM attempts WHERE result_id IN ({F3}))",
         f"UPDATE capture_flows SET filter='(none: port 5021, no address)', expected=0, packets=NULL "
         f"WHERE result_id IN ({F3})"], {"A17"}),
    "flow_mutant_run_field_side_missing_ctl": (
        ["DELETE FROM capture_flows WHERE result_id IN (SELECT result_id FROM results WHERE run_id=140 "
         "AND case_id='C-READ-SERIES' AND device_id='dev-a')"], {"A17"}),
}


def bytes_probe_metadata_only(c, scratch, real):
    root = scratch_root(real, scratch, "metadata-only", ("run-146",))
    rel = "run-146/FT-F3-WRONG-PORT__dev-a/capture-field.pcap"
    n = strip_port(root / rel, 5021)
    reindex(c, root, rel)                       # the index now agrees with the file: only a recount can tell
    print(f"  (stripped {n} packets of port 5021 from {rel}; evidence row re-hashed)")
    return root


def bytes_probe_missing_file(c, scratch, real):
    root = scratch_root(real, scratch, "missing-file", ("run-150",))
    (root / "run-150/C-HEALTH__dev-a/capture.pcap").unlink()
    return root


def bytes_probe_hash_mismatch(c, scratch, real):
    root = scratch_root(real, scratch, "hash-mismatch", ("run-150",))
    p = root / "run-150/C-READ-SERIES__dev-b/timing.json"
    p.write_bytes(p.read_bytes().replace(b"clock", b"Clock", 1))
    return root


def bytes_probe_unindexed_capture(c, scratch, real):
    c.execute("DELETE FROM evidence WHERE path='run-146/FT-F3-WRONG-PORT__dev-a/capture-field.pcap'")
    return real


PROBES.update({
    "bytes_flow_metadata_without_packets": (bytes_probe_metadata_only, {"A20"}),
    "bytes_missing_capture_file": (bytes_probe_missing_file, {"A20"}),
    "bytes_hash_mismatch": (bytes_probe_hash_mismatch, {"A20"}),
    "bytes_capture_not_indexed": (bytes_probe_unindexed_capture, {"A20"}),
    "bytes_no_evidence_root": ("NO_ROOT", {"A20"}),
    # ---------------- reference data the required sets are derived from
    "ref_device_removed": (lambda c, s, r: (delete_results(c, "device_id='dev-b'"),
                                            c.execute("DELETE FROM devices WHERE device_id='dev-b'")),
                           {"A18", "A21"}),
    "ref_case_removed": (lambda c, s, r: (delete_results(c, "case_id='C-GATEWAY'"),
                                          c.execute("DELETE FROM case_requirements WHERE case_id='C-GATEWAY'"),
                                          c.execute("DELETE FROM cases WHERE case_id='C-GATEWAY'")),
                         {"A21"}),
})


def summary(c, root) -> dict:
    a = run_audit(c, root)
    bad = {x["id"].split("-")[0]: x for x in a if not x["ok"]}
    a18 = next(x for x in a if x["id"].startswith("A18"))
    return {"holds": f"{len(a) - len(bad)}/{len(a)}", "violated": sorted(bad, key=lambda k: int(k[1:])),
            "reasons": {k: [str(v) for v in x["violations"][:3]] for k, x in bad.items()},
            "A18_run": a18.get("run"), "commissioned150": db.commissioned_devices(c, 150),
            "fk": [tuple(r) for r in c.execute("PRAGMA foreign_key_check")]}


def main() -> int:
    src_path, real_root, scratch = Path(sys.argv[1]), Path(sys.argv[2]).resolve(), Path(sys.argv[3])
    scratch.mkdir(parents=True, exist_ok=True)
    before = hashlib.sha256(src_path.read_bytes()).hexdigest()
    src = sqlite3.connect(src_path.resolve().as_uri() + "?mode=ro", uri=True)
    print("SOURCE", src_path, before, "audit() parameters:", list(SIG))
    base = copy(src)
    s = summary(base, real_root)
    print("BASE (unmodified copy, real evidence root):", json.dumps(s))
    mismatches = 0
    for name, (action, expect) in PROBES.items():
        c = copy(src)
        root = real_root
        if action == "NO_ROOT":
            root = None
        elif callable(action):
            root = action(c, scratch, real_root) if name.startswith("bytes_") else (action(c, scratch, real_root),
                                                                                     real_root)[1]
        else:
            for stmt in action:
                c.execute(stmt)
        s = summary(c, root)
        got = set(s["violated"])
        ok = (expect <= got) if expect else not got
        mismatches += not ok
        print(f"{'MATCH   ' if ok else 'MISMATCH'} {name}: expect violated {sorted(expect) or 'none'}; "
              + json.dumps(s))
        c.close()
    after = hashlib.sha256(src_path.read_bytes()).hexdigest()
    print("SOURCE_HASH_UNCHANGED", before == after, after)
    print(f"PROBES {len(PROBES)} MISMATCHES {mismatches}")
    return 0 if mismatches == 0 and before == after else 1


if __name__ == "__main__":
    sys.exit(main())
