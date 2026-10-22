"""Reports (Markdown + one JSON audit) generated ONLY from the SQLite results database.

Nothing here is typed in by hand: every table is a query (runner/analysis.py, or the small
queries below) over runs/results/attempts/exchanges/checks/evidence/measurements/mutants.
Runs on witness-ctl:
    python3 -m runner.report --db /var/lib/witness/results/witness.db --out-dir /var/lib/witness/results/reports
Writes commissioning-report.md (everything) and the brief section 9 deliverables as separate files:
traceability.md, baseline-report.md, fault-report.md, mutant-report.md, acceptance-audit.md/.json.
Evidence links are relative to the reports directory (../evidence/run-N/<case>__<device>/).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from runner import analysis as A, db
from runner.catalog import CASES, COMMISSIONING_REQUIRED, MUTANT_DEVICE, counts

CTL, FIELD = "witness-ctl", "witness-field"
SCOPE = ("Scope: software-simulated sensor devices (Python processes) on a Linux VM, exercised over real "
         "TCP between two Ubuntu 24.04 VMs. This is not physical hardware or embedded firmware validation.\n")

LATEST_PER_CASE = """
SELECT r.case_id, coalesce(r.device_id, '(run)') AS device, r.run_id, ru.kind, r.observed_category, r.verdict,
       r.attribution, r.evidence_path
FROM results r JOIN runs ru USING (run_id)
WHERE r.result_id IN (""" + A.LATEST_CURRENT + """)
  AND r.case_id IN (SELECT case_id FROM case_requirements WHERE req_id = ?)
ORDER BY r.case_id, device, r.result_id"""

# Instances whose latest selecting run planned them but recorded no result (final verification RC-4): shown as MISSING,
# never replaced by an older run's result.
PLANNED_MISSING = """
SELECT l.case_id, coalesce(l.device_id, '(run)'), l.run_id FROM (""" + A.LATEST_RUN + """) l
WHERE l.case_id IN (SELECT case_id FROM case_requirements WHERE req_id = ?)
  AND NOT EXISTS (SELECT 1 FROM results r WHERE r.run_id = l.run_id AND r.case_id = l.case_id
                    AND r.device_id IS l.device_id)
ORDER BY l.case_id, l.device_id"""

TRACE = """
SELECT q.req_id, q.text,
       (SELECT group_concat(cr.case_id, ', ') FROM case_requirements cr WHERE cr.req_id = q.req_id) AS cases
FROM requirements q ORDER BY q.req_id"""

EVIDENCE_GAPS = """
SELECT r.run_id, r.case_id, coalesce(r.device_id, '(run)') AS device, e.path, e.bytes
FROM evidence e JOIN results r USING (result_id)
WHERE e.kind = 'pcap' AND e.bytes <= 24
  AND coalesce(r.observed_category, '') NOT IN ('NO_ROUTE', 'RESOLVE_FAIL')   -- no packet is expected
  AND EXISTS (SELECT 1 FROM attempts a JOIN exchanges x USING (attempt_id) WHERE a.result_id = r.result_id)
ORDER BY r.run_id, r.case_id"""

FLOW_GAPS = """
SELECT r.run_id, r.case_id, coalesce(r.device_id, '(run)'), f.capture, f.filter, coalesce(f.packets, 'no file'), f.detail
FROM capture_flows f JOIN results r USING (result_id)
WHERE f.expected = 1 AND coalesce(f.packets, 0) = 0 ORDER BY r.run_id, r.case_id, f.capture"""


def md_table(rows, headers) -> str:
    if not rows:
        return "_none_\n"

    def cell(v):
        s = "" if v is None else (f"{v:.1f}" if isinstance(v, float) else str(v))
        return s.replace("|", "\\|").replace("\n", " ")
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(cell(v) for v in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def link(path: str | None) -> str:
    return f"[{path}](../evidence/{path}/)" if path else ""


def q(conn, sql, *args):
    cur = conn.execute(A.sql(conn, sql), args)
    return [tuple(r) for r in cur.fetchall()], [d[0] for d in cur.description]


# ---------------------------------------------------------------- sections

def runs_section(conn) -> str:
    rows, _ = q(conn, """
      SELECT ru.run_id, ru.kind, coalesce(ru.mutant_id, ''), substr(ru.git_sha,1,10), ru.git_dirty, ru.clean_env,
             ru.contaminated, ru.started_at, ru.finished_at, count(r.result_id),
             sum(r.verdict='pass'), sum(r.verdict='fail'), sum(r.verdict='error'), ru.notes
      FROM runs ru LEFT JOIN results r USING (run_id) GROUP BY ru.run_id ORDER BY ru.run_id""")
    return ("## 1. Runs\n\n" + md_table(rows, ["run", "kind", "mutant", "git", "dirty", "clean_env", "contaminated",
                                              "started", "finished", "results", "pass", "fail", "error", "notes"])
            + "\n`clean_env` = both VMs' full preflight was GREEN at run start. `contaminated` = a postflight or "
              "session postflight was red, a fault revert was not verified, or the run never finished; such runs "
              "are listed but never used as evidence (\"fair\" = finished, clean, uncontaminated).\n")


COMMISSIONING_RULE = (
    "A run commissions a device only if (runner/db.py `COMMISSIONING_GAPS`, the catalog's complete commissioning set, "
    "never just the cases a run happened to execute): it is a finished, clean (both preflights GREEN), uncontaminated "
    "baseline; EVERY commissioning case of the catalog ({cases}) has exactly one result for the device (run-level "
    "cases once per run), each verdict pass with green precheck and postflight; no result in the run observed "
    "WRONG_IDENTITY for the device and no other result on it is non-pass; the firmware version the run recorded equals "
    "the inventory's; the device build is stock; the run's REQ-10 environment record is valid (runner/evidence.py); "
    "and the run and these results satisfy the evidence contract (docs/acceptance-contract.md: attempts, exchanges, "
    "captures, session evidence, plan; files and packet counts when the evidence directory is given). The devices are "
    "the inventory's, never only those the database still lists. The rule is per device: a duplicated per-device "
    "instance (an AMBIGUOUS run) blocks that device only; a duplicated run-level instance blocks every device.")


def commissioning_table(conn, run_id: int, evidence_root=None) -> tuple[str, list[str], str]:
    """(markdown, commissioned devices, COMPLETE | AMBIGUOUS | PARTIAL | INCOMPLETE) for one run."""
    cov = A.commissioning_coverage(conn, run_id)
    gaps = db.commissioning_gaps(conn, run_id, evidence_root=evidence_root)
    status = A.coverage_status(cov, A.planned_instances(conn, run_id))
    executed = sum(1 for *_, n in cov if n >= 1)
    comm = [d for d, g in gaps.items() if g is None]
    text = (f"Run **{run_id}**: **{status}** commissioning run ({executed}/{len(cov)} required instances executed"
            + (f"; {sum(n for *_, n in cov if n > 1)} results for {sum(1 for *_, n in cov if n > 1)} duplicated "
               "instance(s)" if status == "AMBIGUOUS" else "")
            + f"). Commissioned by it: **{', '.join(comm) or 'none'}**.\n\n"
            + md_table([(d, "yes" if g is None else "**no**", g or "") for d, g in gaps.items()],
                       ["device", "commissioned", "unmet prerequisites"]))
    return text, comm, status


def commissioning_section(conn, evidence_root=None) -> str:
    out = ["## 2. Commissioning status\n",
           COMMISSIONING_RULE.format(cases=", ".join(c for c, _ in COMMISSIONING_REQUIRED)) + "\n"]
    base = conn.execute("""SELECT run_id FROM runs ru WHERE kind='baseline' AND """ + A.FAIR +
                        " ORDER BY run_id DESC LIMIT 1").fetchone()
    if base is None:
        out.append("No fair baseline run: **no device is commissioned.**\n")
        return "\n".join(out)
    text, _, status = commissioning_table(conn, base[0], evidence_root)
    out.append("Latest fair baseline run:\n\n" + text)
    full = A.latest_complete_baseline(conn)
    if status == "INCOMPLETE":
        out.append("An incomplete run (a planned instance has no result) commissions no device that lacks one of its own "
                   "or of the run-level instances; A23 lists the missing results. "
                   + ("A18 evaluates this run (it selected the complete commissioning set).\n" if full == base[0] else
                      "It did not select the complete commissioning set either.\n"))
    if status == "PARTIAL":
        out.append("A partial run commissions no device that lacks one of its own or of the run-level instances. "
                   "(It did not select every instance; a run that planned an instance and lost its result is "
                   "INCOMPLETE instead and is never skipped.)\n")
    if status in ("PARTIAL", "INCOMPLETE") and full != base[0]:
        out.append(f"Latest fair baseline that selected the complete commissioning set (A18 evaluates run {full}):\n\n"
                   + commissioning_table(conn, full, evidence_root)[0] if full is not None
                   else "No fair baseline selected the complete commissioning set.\n")
    elif status == "AMBIGUOUS":
        out.append("An ambiguous run (duplicate or conflicting results for one instance) is not skipped: A18 evaluates "
                   "it, A19 lists its duplicates, and no device whose prerequisites include a duplicated instance is "
                   "commissioned by it.\n")
    rows, _ = q(conn, """SELECT r.case_id, coalesce(r.device_id,'(run)'), r.observed_category, r.first_attempt_category,
                                r.attempts, r.latency_ms, r.verdict, r.attribution, r.detail
                         FROM results r WHERE r.run_id=? ORDER BY r.case_id, r.device_id""", base[0])
    out.append(f"Results of run {base[0]}:\n")
    out.append(md_table(rows, ["case", "device", "observed", "first attempt", "attempts", "latency ms", "verdict",
                               "attribution", "detail"]))
    env, _ = q(conn, """SELECT key, value FROM environment WHERE run_id=? AND key IN
                        ('git_sha','git_dirty','runs.clean_env','kernel.witness-ctl','kernel.witness-field',
                         'distro.witness-ctl','python','fw_version.dev-a','fw_version.dev-b','device_build.dev-a',
                         'device_build.dev-b','provenance.witness-ctl','provenance.witness-field','qdisc.witness-ctl',
                         'qdisc.witness-field') ORDER BY key""", base[0])
    out.append(f"Environment and contamination of run {base[0]} (REQ-10; full rows in `environment`):\n")
    out.append(md_table(env, ["key", "value"]))
    out.append("Fault and mutant runs never commission a device: a fault case whose expected failure was observed "
               "has verdict `pass` (the suite detected the fault), not a commissioned device.\n")
    return "\n".join(out)


def traceability_section(conn) -> str:
    out = ["## 3. Traceability (REQ -> cases -> latest fair result)\n"]
    trace, _ = q(conn, TRACE)
    rows = []
    for req_id, text, cases in trace:
        latest, _ = q(conn, LATEST_PER_CASE, req_id)
        missing, _ = q(conn, PLANNED_MISSING, req_id)
        if not cases:
            rows.append((req_id, text[:90], "**GAP: no case**", "-"))
            continue
        summ = "; ".join([f"{c}/{d}: {v} ({o or 'n/a'}) run {r} {link(e)}" for c, d, r, k, o, v, a, e in latest]
                         + [f"{c}/{d}: MISSING (planned in run {r}, no result)" for c, d, r in missing]) \
            or "not yet run"
        rows.append((req_id, text[:90], cases, summ))
    out.append(md_table(rows, ["REQ", "requirement", "cases", "latest result per case/device (fair, non-mutant run)"]))
    gaps = [r[0] for r in trace if not r[2]]
    out.append(f"Traceability gaps (REQ without a case): **{', '.join(gaps) or 'none'}**.\n")
    orphan = conn.execute("SELECT count(*) FROM cases WHERE case_id NOT IN (SELECT case_id FROM case_requirements)").fetchone()[0]
    out.append(f"Cases without a requirement: **{orphan}**.\n")
    rows, _ = q(conn, """SELECT c.case_id, c.kind, group_concat(cr.req_id, ', '),
                                (SELECT count(*) FROM results r JOIN runs ru USING (run_id) WHERE r.case_id = c.case_id
                                   AND ru.kind <> 'mutant' AND """ + A.FAIR + """),
                                (SELECT sum(r.verdict='pass') FROM results r JOIN runs ru USING (run_id)
                                   WHERE r.case_id = c.case_id AND ru.kind <> 'mutant' AND """ + A.FAIR + """)
                         FROM cases c JOIN case_requirements cr USING (case_id) GROUP BY c.case_id ORDER BY c.kind, c.case_id""")
    out.append("Case -> requirement map with fair (non-mutant) execution counts:\n")
    out.append(md_table(rows, ["case", "kind", "requirements", "fair results", "pass verdicts"]))
    return "\n".join(out)


def catalog_counts_line(conn) -> str:
    """Independent audit F-08: three different counts, derived from the catalog and checked against the database."""
    n_dev = conn.execute("SELECT count(*) FROM devices").fetchone()[0]
    c = counts(n_dev)
    types, variants = conn.execute("SELECT count(DISTINCT catalog_id), count(*) FROM faults").fetchone()
    agree = (types, variants) == (c["fault_types"], c["fault_variants"])
    return (f"Catalog (runner/catalog.py; `faults` table {'agrees' if agree else f'DISAGREES: {types} types, {variants} variants'}): "
            f"**{c['fault_types']} fault types** (brief F1-F13), **{c['fault_variants']} fault variants** (e.g. F6 has "
            f"three, F7 two), **{c['fault_test_instances']} live fault-test instances** (fault cases; the gateway "
            f"cases reuse F1/F5/F8) and {c['commissioning_instances']} commissioning instances for {n_dev} devices.\n")


def faults_section(conn) -> str:
    out = ["## 4. Fault-injection results\n", catalog_counts_line(conn), "### 4a. Latest fair result per fault variant\n"]
    rows, _ = q(conn, """
      SELECT r.fault_id, f.catalog_id, r.run_id, r.case_id, r.expected_category, r.observed_category, r.verdict,
             x.connect_ms, x.response_ms, r.latency_ms, r.detection_ms, x.read_end, x.local_port, r.postflight,
             (SELECT group_concat(cf.capture || ' ' || coalesce(cf.packets, '-'), ', ') FROM capture_flows cf
               WHERE cf.result_id = r.result_id AND cf.expected = 1) AS flow_packets, r.evidence_path
      FROM results r JOIN faults f USING (fault_id)
      LEFT JOIN attempts a ON a.result_id = r.result_id AND a.attempt_no = 1
      LEFT JOIN exchanges x ON x.attempt_id = a.attempt_id AND x.ord = 1
      WHERE r.fault_id IS NOT NULL AND r.result_id IN (""" + A.LATEST_CURRENT + """)
      ORDER BY CAST(substr(f.catalog_id, 2) AS INTEGER), r.fault_id, r.case_id, r.result_id""")
    out.append(md_table([r[:-1] + (link(r[-1]),) for r in rows],
                        ["fault", "catalog", "run", "case", "expected", "observed", "verdict", "connect ms",
                         "response ms", "latency ms", "detection ms", "read end", "local port", "postflight",
                         "dialled-flow packets", "evidence"]))
    out.append("`dialled-flow packets`: packets of the flow the case dialled (address:port, both directions) in the "
               "ctl and field captures (`capture_flows`); empty = recorded before that check existed (independent "
               "audit F-07). A local failure that sends nothing (NO_ROUTE, RESOLVE_FAIL) has no expected flow.\n")
    out.append("`detection ms`: runner cases = fault confirmed applied (witness-faultctl returned) -> attempt "
               "classified; GW-* cases = fault command sent -> gateway state `unreachable` (REQ-09); FT-F12 = restart "
               "returned -> first PASS HEALTH (REQ-08). Expected categories are predictions recorded before the "
               "run. `local port` is empty when the connect itself failed (no established socket): such cases are "
               "matched to packets by time, address and the SYN's source port in the capture text.\n")
    out.append("### 4b. Fault catalog coverage (brief section 6.3, F1-F13)\n")
    cov = []
    for cid in A.CATALOG_FAULTS:
        variants = [r[0] for r in conn.execute("SELECT fault_id FROM faults WHERE catalog_id=? ORDER BY fault_id", (cid,))]
        if not variants:
            cov.append((cid, "-", 0, 0, "**NOT IN CATALOG**"))
            continue
        for fid in variants:
            r = conn.execute("SELECT count(*), sum(r.verdict='pass') FROM results r JOIN runs ru USING (run_id) "
                             "WHERE r.fault_id=? AND " + A.FAIR, (fid,)).fetchone()
            # the same current evidence as A4 and traceability: never an older run's result for a planned instance
            cur = [f"{c}: {e} / {o or '(none)'} / {v} (run {run})" for c, e, o, v, run in q(conn, """
                SELECT r.case_id, r.expected_category, r.observed_category, r.verdict, r.run_id FROM results r
                WHERE r.fault_id = ? AND r.result_id IN (""" + A.LATEST_CURRENT + """) ORDER BY r.case_id""", fid)[0]]
            cases = {c.case_id for c in CASES if c.fault_id == fid}
            cur += [f"{c}: MISSING (planned in run {run}, no result)" for c, d, run in q(conn, """
                SELECT l.case_id, l.device_id, l.run_id FROM (""" + A.LATEST_RUN + """) l
                WHERE NOT EXISTS (SELECT 1 FROM results r WHERE r.run_id = l.run_id AND r.case_id = l.case_id
                                    AND r.device_id IS l.device_id) ORDER BY l.case_id""")[0] if c in cases]
            cov.append((cid, fid, r[0], r[1] or 0, "; ".join(cur) or "**NOT RUN**"))
    out.append(md_table(cov, ["catalog", "variant", "fair results", "pass verdicts",
                              "current evidence per case: expected / observed / verdict"]))
    ev, _ = q(conn, """SELECT fault_id, count(*), sum(removal_verified), min(applied_at), max(removed_at)
                       FROM fault_events GROUP BY fault_id ORDER BY fault_id""")
    out.append("Fault application/removal (all runs):\n")
    out.append(md_table(ev, ["fault", "applications", "removals verified", "first applied", "last removed"]))
    out.append("### 4c. Gateway and recovery measurements (REQ-08, REQ-09), latest fair result per case/device\n")
    rows, _ = q(conn, """
      SELECT r.case_id, coalesce(r.device_id,'(run)'), r.run_id, r.observed_category, r.verdict, m.name, m.value,
             m.unit, m.bound,
             CASE WHEN m.bound IS NULL OR m.value IS NULL THEN '' WHEN m.value <= m.bound THEN 'yes' ELSE 'NO' END, m.clock
      FROM measurements m JOIN results r USING (result_id)
      WHERE r.result_id IN (""" + A.LATEST_CURRENT + """)
      ORDER BY r.case_id, r.device_id, m.name, r.result_id""")
    out.append(md_table(rows, ["case", "device", "run", "observed", "verdict", "measurement", "value", "unit", "bound",
                               "within", "clock"]))
    out.append("`bound` is the requirement limit the value is compared with. For a fault case the value may be outside "
               "it by design (FT-F13-SKEW's READ is 30 s outside the ±2 s REQ-04 window: that is the expected "
               "observation). Gateway/REQ-08/09 values must be within.\n")
    rows, _ = q(conn, """SELECT m.name, m.unit, count(*), min(m.value), max(m.value), max(m.bound),
                                sum(m.bound IS NOT NULL AND m.value > m.bound)
                         FROM measurements m JOIN results r USING (result_id) JOIN runs ru USING (run_id)
                         WHERE m.bound IS NOT NULL AND ru.kind <> 'mutant' AND """ + A.FAIR + """
                         GROUP BY m.name, m.unit ORDER BY m.name""")
    out.append("All fair runs, bounded measurements:\n")
    out.append(md_table(rows, ["measurement", "unit", "n", "min", "max", "bound", "outside bound"]))
    return "\n".join(out)


def analyses_section(conn) -> str:
    out = ["## 5. Analysis queries (PROJECT_BRIEF.md section 8; SQL in runner/analysis.py)\n"]
    for title, sql, params in (
            ("Q1. Failures by device and case (all runs, by run kind)", A.Q1_FAILURES, {}),
            ("Q2. Verdict/category differs across fair clean-baseline runs (flakiness, all baselines)", A.Q2_FLAKY,
             {"runs": None}),
            ("Q3. Expected vs observed per fault, mismatch count", A.Q3_FAULT_MATCH, {}),
            ("Q4. Detection time per fault and case (ms; fair runs; median computed in SQL)", A.Q4_DETECTION, {}),
            ("Q5. Passed only after retry (reported as FLAKE, verdict fail)", A.Q5_RETRY, {}),
            ("Q5b. Every retried result (first attempt not PASS)", A.Q5B_RETRIED, {}),
            ("Q6. Infra-attributed results / unclean, contaminated or unfinished runs (discard candidates)",
             A.Q6_INFRA, {})):
        rows, cols = A.rows(conn, sql, **params)
        out.append(f"### {title}\n")
        out.append(md_table(rows, cols))
    return "\n".join(out)


def baseline_section(conn) -> str:
    out = ["## 6. Clean baselines (brief 7.3)\n"]
    fresh = A.fresh_trial_runs(conn, CTL, FIELD)
    rows, cols = A.rows(conn, A.FRESH_BASELINE_RUNS, ctl=CTL, field=FIELD)
    out.append("### 6a. Baseline runs started on freshly restored golden clones (provenance recorded by the runner)\n")
    out.append(md_table(rows, cols))
    out.append(f"Independent fresh-clone trials counted (first fair baseline per distinct restore): **{len(fresh)}** "
               f"-> runs {', '.join(map(str, fresh)) or 'none'}.\n")
    if fresh:
        out.append("### 6b. Variability across those trials\n")
        r, c = A.rows(conn, A.BASELINE_VARIABILITY, runs=A.runs_param(fresh))
        out.append(md_table(r, c))
        r, c = A.rows(conn, A.Q2_FLAKY, runs=A.runs_param(fresh))
        out.append("Cases whose verdict or category differs across these trials (Q2 restricted to them):\n")
        out.append(md_table(r, c))
    n = conn.execute("SELECT count(*) FROM runs ru WHERE kind='baseline' AND " + A.FAIR).fetchone()[0]
    out.append(f"### 6c. All fair baseline runs (long-lived and fresh VMs): {n}\n")
    r, c = A.rows(conn, A.BASELINE_VARIABILITY, runs=None)
    out.append(md_table(r, c))
    return "\n".join(out)


def mutant_section(conn) -> str:
    out = ["## 7. Mutants (brief 7.4): deliberately broken device builds on dev-a, dev-b stock as control\n"]
    rows, cols = A.rows(conn, A.MUTANT_SUMMARY, mdev=MUTANT_DEVICE)
    out.append(md_table(rows, cols))
    tested = [r for r in rows if r[5] != "NOT TESTED"]
    caught = [r for r in tested if r[5].startswith("CAUGHT")]
    runs_valid = sum(r[3] for r in rows)
    runs_det = sum(r[4] for r in rows)
    out.append(f"Mutants caught: **{len(caught)}/{len(rows)}** ({len(tested)} tested). Run-level detection: "
               f"**{runs_det}/{runs_valid}** valid mutant runs had >= 1 device-attributed failure on {MUTANT_DEVICE}. "
               "A run is valid only if it is fair and has no infra/runner-attributed result (an infrastructure "
               "error is never counted as a detection). `control_nonpass` = non-pass results on the stock device "
               "in valid runs (false alarms); run-level cases (C-ENVIRONMENT) are listed per run, never as a catch.\n")
    out.append("Predictions recorded before the first mutant run (`mutants.predicted`):\n")
    p, _ = q(conn, "SELECT mutant_id, spec, predicted FROM mutants ORDER BY mutant_id")
    out.append(md_table(p, ["mutant", "spec", "predicted catch"]))
    out.append("### Per mutant run\n")
    rows, cols = A.rows(conn, A.MUTANT_RUNS, mdev=MUTANT_DEVICE)
    out.append(md_table(rows, cols))
    rows, _ = q(conn, """SELECT ru.mutant_id, r.run_id, r.case_id, coalesce(r.device_id,'(run)'), r.first_attempt_category,
                                r.observed_category, r.verdict, r.attribution, substr(r.detail, 1, 160), r.evidence_path
                         FROM results r JOIN runs ru USING (run_id) WHERE ru.kind = 'mutant' AND r.verdict <> 'pass'
                         ORDER BY ru.mutant_id, r.run_id, r.case_id, r.device_id""")
    out.append("### Every non-pass result in mutant runs (the evidence)\n")
    out.append(md_table([r[:-1] + (link(r[-1]),) for r in rows],
                        ["mutant", "run", "case", "device", "first attempt", "observed", "verdict", "attribution",
                         "detail", "evidence"]))
    return "\n".join(out)


def audit_section(results: list[dict]) -> str:
    rows = [(a["id"], a["claim"], "HOLDS" if a["ok"] else "**VIOLATED**",
             ", ".join(map(str, a["violations"][:12])) + (" ..." if len(a["violations"]) > 12 else ""))
            for a in results]
    fresh = next((a for a in results if a["id"].startswith("A14")), {})
    return ("## 8. Acceptance assertions (SQL over the store; runner/analysis.py ASSERTIONS)\n\n"
            + md_table(rows, ["id", "claim", "status", "violations"])
            + f"\n{sum(a['ok'] for a in results)}/{len(results)} assertions hold. These are machine checks over the "
              "recorded evidence; they are necessary for acceptance, not a certificate of it.\n"
            + (f"\nProvenance: the fresh-clone baselines counted by A14 (runs {', '.join(map(str, fresh['runs']))}) "
               f"ran source revision(s) {', '.join(fresh['source_revisions'])} (`runs.git_sha`); evidence produced "
               "by other revisions is reported with its own `git_sha` in section 1.\n" if fresh.get("runs") else ""))


def environment_section(conn) -> str:
    out = ["## 9. Environment (REQ-10), latest run of each kind\n"]
    for kind in ("baseline", "fault", "mutant"):
        r = conn.execute("SELECT max(run_id) FROM runs WHERE kind=?", (kind,)).fetchone()[0]
        if r is None:
            continue
        rows, _ = q(conn, """SELECT key, value FROM environment WHERE run_id=? AND key NOT LIKE 'nft.%'
                             AND key NOT LIKE 'chrony.tracking%' AND key NOT LIKE 'routes.%' AND key NOT LIKE 'device_env.%'
                             ORDER BY key""", r)
        out.append(f"Run {r} ({kind}); full nft rulesets, routes and chrony tracking are in the `environment` table.\n")
        out.append(md_table([(k, (v[:110] + "...") if len(v) > 110 else v) for k, v in rows], ["key", "value"]))
    return "\n".join(out)


def evidence_mismatches(conn, root: Path) -> list[tuple]:
    """Every indexed evidence file that is missing or whose bytes no longer match its recorded length and sha256.
    Added in the independent-audit remediation after FT-F12's second restart had overwritten four indexed files per
    run (runs 133-138; results/evidence/F12-overwritten-evidence-annotations.md)."""
    out = []
    for run, case, dev, path, sha, n in conn.execute(
            "SELECT e.run_id, coalesce(r.case_id, '(run)'), coalesce(r.device_id, ''), e.path, e.sha256, e.bytes "
            "FROM evidence e LEFT JOIN results r USING (result_id) ORDER BY e.evidence_id"):
        f = root / path
        if not f.exists():
            out.append((run, case, dev, path, sha[:12], "missing"))
            continue
        data = f.read_bytes()
        if len(data) != n or hashlib.sha256(data).hexdigest() != sha:
            out.append((run, case, dev, path, sha[:12], f"differs ({len(data)} B now, {n} B recorded)"))
    return out


def problems_section(conn, evidence_root: Path | None = None) -> str:
    out = ["## 10. Known problems recorded in the database\n"]
    rows, _ = q(conn, """SELECT r.run_id, ru.kind, r.case_id, coalesce(r.device_id,'(run)'), r.verdict, r.attribution,
                                r.observed_category, r.detail FROM results r JOIN runs ru USING (run_id)
                         WHERE r.verdict <> 'pass' AND ru.kind <> 'mutant' ORDER BY r.run_id""")
    out.append("Non-pass results outside mutant runs (mutant-run failures are in section 7):\n")
    out.append(md_table(rows, ["run", "kind", "case", "device", "verdict", "attribution", "observed", "detail"]))
    rows, _ = q(conn, "SELECT run_id, notes FROM runs WHERE contaminated = 1 ORDER BY run_id")
    out.append("Contaminated runs:\n")
    out.append(md_table(rows, ["run", "notes"]))
    rows, _ = q(conn, "SELECT run_id, phase, vm, name, detail FROM checks WHERE status='FAIL' ORDER BY run_id, check_id")
    out.append("Failed checks (preflight/precheck/postflight):\n")
    out.append(md_table(rows, ["run", "phase", "vm", "check", "detail"]))
    rows, _ = q(conn, EVIDENCE_GAPS)
    out.append("Evidence integrity: packet captures that contain no packets although the case exchanged traffic:\n")
    out.append(md_table(rows, ["run", "case", "device", "pcap", "bytes"]))
    n = conn.execute("SELECT count(*), coalesce(sum(expected), 0), coalesce(sum(expected = 1 AND packets > 0), 0) "
                     "FROM capture_flows").fetchone()
    out.append(f"Dialled-flow checks (`capture_flows`, independent audit F-07): {n[0]} recorded, {n[1]} expected on the "
               f"wire, {n[2]} of those present in their capture. Expected flows missing from a capture (any run):\n")
    rows, _ = q(conn, FLOW_GAPS)
    out.append(md_table(rows, ["run", "case", "device", "capture", "flow filter", "packets", "why expected"]))
    out.append("Captures recorded before the check are not rewritten. The pre-remediation F3 captures filtered "
               "`tcp port 5020 or icmp` and hold none of the dialled port-5021 packets; they are kept and annotated in "
               "`results/evidence/F07-historical-capture-annotations.md`.\n")
    if evidence_root is not None and Path(evidence_root).is_dir():
        bad = evidence_mismatches(conn, Path(evidence_root))
        n_ev = conn.execute("SELECT count(*) FROM evidence").fetchone()[0]
        out.append(f"Evidence files checked against their recorded length and sha256: {n_ev}; missing or different: "
                   f"**{len(bad)}** (kept as recorded, never re-indexed; see the annotations in results/evidence/):\n")
        out.append(md_table(bad, ["run", "case", "device", "path", "recorded sha256", "now"]))
    else:
        out.append("Evidence files were not re-hashed for this report (no evidence directory given).\n")
    return "\n".join(out)


def header(title: str) -> str:
    return f"# {title}\n\nGenerated {db.utcnow()} from the SQLite results database only (no hand-entered results).\n\n{SCOPE}"


def build_all(conn, evidence_root: Path | None = None) -> dict[str, str]:
    """{file name: content}. commissioning-report.md contains every section."""
    if conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0:
        return {"commissioning-report.md": header("Witness commissioning report") + "\nNo runs recorded.\n"}
    audit = A.audit(conn, ctl=CTL, field=FIELD, evidence_root=evidence_root)
    s = {"runs": runs_section(conn), "comm": commissioning_section(conn, evidence_root),
         "trace": traceability_section(conn),
         "faults": faults_section(conn), "q": analyses_section(conn), "base": baseline_section(conn),
         "mut": mutant_section(conn), "audit": audit_section(audit), "env": environment_section(conn),
         "prob": problems_section(conn, evidence_root)}
    full = header("Witness commissioning report") + "\n" + "\n".join(s.values())
    return {
        "commissioning-report.md": full,
        "traceability.md": header("Witness traceability: requirement -> case -> latest result") + "\n" + s["trace"],
        "baseline-report.md": header("Witness clean-baseline report") + "\n" + s["base"],
        "fault-report.md": header("Witness fault-injection results") + "\n" + s["faults"] + "\n" + s["q"],
        "mutant-report.md": header("Witness mutant report") + "\n" + s["mut"],
        "acceptance-audit.md": header("Witness acceptance assertions") + "\n" + s["audit"],
        "acceptance-audit.json": json.dumps({"generated_at": db.utcnow(), "assertions": audit}, indent=1, default=str),
    }


def build(conn) -> str:
    return build_all(conn)["commissioning-report.md"]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--db", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--evidence-root", help="re-hash every indexed evidence file (default: <db dir>/evidence if present)")
    a = p.parse_args(argv)
    if not Path(a.db).exists():
        print(f"no database at {a.db}", file=sys.stderr)
        return 1
    conn = db.connect(a.db)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    root = Path(a.evidence_root) if a.evidence_root else Path(a.db).parent / "evidence"
    for name, text in build_all(conn, root if root.is_dir() else None).items():
        (out / name).write_text(text)
        print(f"wrote {out / name} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
