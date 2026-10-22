"""SQL analyses over the normalized results store (PROJECT_BRIEF.md sections 7.3, 7.4, 8, 9).

Every function is one SQL statement (SQLite >= 3.25 window functions, JSON1 for run lists); the
report and the audit only format what these return. "Fair" run = finished, clean_env=1 (both full
preflights GREEN at start) and not contaminated: results of other runs are kept and listed, but
never used as evidence that something works.

Median: SQLite has no median aggregate. MEDIAN_CTE numbers the values of each group with
row_number() and averages the middle one (odd n) or two (even n): positions (n+1)/2 and (n+2)/2
in integer arithmetic are the same row for odd n and the two middle rows for even n.

Acceptance assertions (independent audit F-06): each returns the VIOLATIONS of one claim. They were
strengthened so that the conjunction cannot hold over missing environment values, stable failures,
partial runs or old passing evidence: A4 uses the LATEST fair result of every case instance, A13
checks every REQ-10 key for both VMs and every device with a valid value, A14 counts only fresh-clone
baselines that are complete, all-pass and retry-free (commissioning every device), A16-A18 cover retry
attribution, capture-flow evidence and commissioning. A database older than schema v4 can still be
audited read-only: v4-only records are then treated as absent (and the assertions needing them fail).

Second independent audit (docs/independent-reaudit.md R-01/R-02): the required sets never come from the rows being
checked. A13 validates every value against runner/evidence.check_environment (inventory-derived keys, one allowed
representation each, agreement with the run row); "latest" means every result of the latest fair run of an instance,
so a conflicting duplicate cannot hide behind a newer row, and A19 rejects ambiguous result sets; A17 derives each
current result's required capture-flow records from its exchanges and the case's capture contract instead of trusting
the stored rows; A20 verifies the bytes (indexed hashes, packets recounted from the capture files); A21 checks that
the reference tables the SQL joins against equal the catalog and inventory. Those four are computed in Python.

Final independent verification (docs/independent-final-verification.md FV-01/FV-02): A17/A20 still derived each
result's obligations from its surviving exchange rows and the evidence index, so deleting those rows deleted the
obligation. Every obligation now comes from runner/contract.py (catalog case contract, inventory, the schema-v5 run
plan, the case evidence directories), never from the rows under examination (docs/acceptance-contract.md). A22 checks
store integrity (no orphan of a deleted parent), A23 every run's flags, declared selection and receipts, A24 every
current result's evidence chain; "latest" is the latest fair run that recorded OR PLANNED an instance, and a planned
instance without its result is a violation, never a fall-back to an older run.
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from runner import contract as C, db, evidence as EV
from runner.catalog import CASES, FAULTS, MUTANTS

REPO = Path(__file__).resolve().parents[1]
FAIR = "ru.finished_at IS NOT NULL AND ru.clean_env = 1 AND ru.contaminated = 0"
CATEGORIES = ("PASS", "PASS_SLOW", "RESOLVE_FAIL", "NO_ROUTE", "CONN_REFUSED", "CONNECT_TIMEOUT",
              "READ_TIMEOUT", "CONN_RESET", "MALFORMED", "WRONG_IDENTITY", "STALE_DATA")
CATALOG_FAULTS = tuple(f"F{n}" for n in range(1, 14))

# Q1. Failures (verdict fail or error) by device and case across all runs, split by run kind.
Q1_FAILURES = """
SELECT coalesce(r.device_id, '(run)') AS device, r.case_id, ru.kind,
       sum(r.verdict = 'fail') AS fails, sum(r.verdict = 'error') AS errors,
       group_concat(DISTINCT r.attribution) AS attributions,
       group_concat(DISTINCT coalesce(r.observed_category, '-')) AS observed,
       count(DISTINCT r.run_id) AS runs, min(r.run_id) AS first_run, max(r.run_id) AS last_run
FROM results r JOIN runs ru USING (run_id)
WHERE r.verdict <> 'pass'
GROUP BY device, r.case_id, ru.kind ORDER BY ru.kind, device, r.case_id"""

# Q2. Cases whose verdict (or observed category) differs across fair clean-baseline runs.
# :runs = JSON array of run ids to restrict to (e.g. the five fresh-clone trials), or NULL for all.
Q2_FLAKY = """
SELECT r.case_id, coalesce(r.device_id, '(run)') AS device, count(DISTINCT r.run_id) AS runs,
       sum(r.verdict = 'pass') AS passes,
       group_concat(r.verdict || ':' || coalesce(r.observed_category, '-') || '@' || r.run_id, ' ') AS verdicts
FROM results r JOIN runs ru USING (run_id)
WHERE ru.kind = 'baseline' AND """ + FAIR + """
  AND (:runs IS NULL OR ru.run_id IN (SELECT value FROM json_each(:runs)))
GROUP BY r.case_id, r.device_id
HAVING count(DISTINCT r.verdict) > 1 OR count(DISTINCT coalesce(r.observed_category, '-')) > 1
ORDER BY r.case_id, device"""

# Q3. For each fault variant: expected vs observed category with mismatch counts. Fair runs are the
# evidence; results from unfair runs are counted separately so nothing disappears.
Q3_FAULT_MATCH = """
SELECT f.catalog_id, r.fault_id, r.expected_category AS expected,
       coalesce(r.observed_category, '(none)') AS observed,
       sum(""" + FAIR + """) AS n_fair,
       sum((""" + FAIR + """) AND coalesce(r.observed_category, '') <> r.expected_category) AS mismatches_fair,
       sum(NOT (""" + FAIR + """)) AS n_unfair_runs,
       sum(r.attribution = 'infra') AS infra
FROM results r JOIN faults f USING (fault_id) JOIN runs ru USING (run_id)
GROUP BY r.fault_id, r.expected_category, r.observed_category
ORDER BY CAST(substr(f.catalog_id, 2) AS INTEGER), r.fault_id, observed"""

MEDIAN_CTE = """
d AS (
  SELECT r.fault_id, r.case_id, r.detection_ms AS v,
         row_number() OVER (PARTITION BY r.fault_id, r.case_id ORDER BY r.detection_ms) AS rn,
         count(*) OVER (PARTITION BY r.fault_id, r.case_id) AS n
  FROM results r JOIN runs ru USING (run_id)
  WHERE r.fault_id IS NOT NULL AND r.detection_ms IS NOT NULL AND r.verdict <> 'error' AND """ + FAIR + """)"""

# Q4. Detection time per fault (and case: runner and gateway cases measure different things): min, median, max.
Q4_DETECTION = "WITH " + MEDIAN_CTE + """
SELECT f.catalog_id, d.fault_id, d.case_id, max(d.n) AS n, round(min(d.v), 1) AS min_ms,
       round(avg(CASE WHEN d.rn IN ((d.n + 1) / 2, (d.n + 2) / 2) THEN d.v END), 1) AS median_ms,
       round(max(d.v), 1) AS max_ms
FROM d JOIN faults f USING (fault_id)
GROUP BY d.fault_id, d.case_id ORDER BY CAST(substr(f.catalog_id, 2) AS INTEGER), d.fault_id, d.case_id"""

# Q5. Cases that passed only after the single retry: attempt 1 did NOT meet the case (its category AND predicates,
# attempts.outcome, schema v4) and attempt 2 did. A first attempt whose category was PASS but whose predicate failed
# (e.g. degraded HEALTH) counts (independent audit F-04). verdict/attribution show what the result became: fail/device
# (FLAKE) after a fair device failure, error/runner or error/infra when attempt 1 was not a fair device test. Rows
# recorded before schema v4 have no outcome; for them the category is the only basis, and `basis` says so.
Q5_RETRY = """
SELECT r.run_id, ru.kind, ru.mutant_id, r.case_id, r.device_id, r.first_attempt_category AS first,
       r.observed_category AS final, r.verdict, r.attribution, a1.outcome AS first_outcome,
       a2.outcome AS final_outcome,
       CASE WHEN a1.outcome IS NULL OR a2.outcome IS NULL THEN 'category (row predates schema v4)'
            ELSE 'attempt outcome' END AS basis, r.detail
FROM results r JOIN runs ru USING (run_id)
LEFT JOIN attempts a1 ON a1.result_id = r.result_id AND a1.attempt_no = 1
LEFT JOIN attempts a2 ON a2.result_id = r.result_id AND a2.attempt_no = 2
WHERE r.attempts = 2
  AND CASE WHEN a1.outcome IS NOT NULL AND a2.outcome IS NOT NULL THEN a1.outcome <> 'ok' AND a2.outcome = 'ok'
           ELSE coalesce(r.first_attempt_category, '') <> 'PASS' AND r.observed_category = 'PASS' END
ORDER BY r.run_id, r.case_id, r.device_id"""

# Q5b. Every retried result, whatever the second attempt saw, with both attempts' own outcomes.
Q5B_RETRIED = """
SELECT r.run_id, ru.kind, ru.mutant_id, r.case_id, r.device_id, r.first_attempt_category AS first,
       r.observed_category AS second, r.verdict, a1.detail AS first_detail, a1.outcome AS first_outcome,
       a2.outcome AS second_outcome, r.attribution
FROM results r JOIN runs ru USING (run_id)
LEFT JOIN attempts a1 ON a1.result_id = r.result_id AND a1.attempt_no = 1
LEFT JOIN attempts a2 ON a2.result_id = r.result_id AND a2.attempt_no = 2
WHERE r.attempts = 2 ORDER BY r.run_id, r.case_id, r.device_id"""

# Q6. Results attributed to infra grouped by run, plus every unclean/contaminated/unfinished run: discard candidates.
Q6_INFRA = """
SELECT ru.run_id, ru.kind, ru.clean_env, ru.contaminated, ru.finished_at IS NOT NULL AS finished,
       count(r.result_id) AS infra_results,
       group_concat(r.case_id || coalesce('/' || r.device_id, ''), ' ') AS cases
FROM runs ru LEFT JOIN results r ON r.run_id = ru.run_id AND r.attribution = 'infra'
GROUP BY ru.run_id
HAVING infra_results > 0 OR ru.contaminated = 1 OR ru.clean_env = 0 OR ru.finished_at IS NULL
ORDER BY ru.run_id"""

# ---- mutants (brief 7.4). Detection = a fair mutant run with no infra/runner result, in which at least
# one case on the mutant device has verdict fail attributed to the device. Infra errors never count.
MUTANT_RUNS = """
SELECT ru.run_id, ru.mutant_id, (""" + FAIR + """) AS fair,
       count(r.result_id) AS results,
       sum(r.attribution IN ('infra', 'runner')) AS harness_or_infra,
       sum(r.verdict = 'fail' AND r.attribution = 'device' AND r.device_id = :mdev) AS caught_cases,
       sum(r.verdict <> 'pass' AND r.device_id IS NOT NULL AND r.device_id <> :mdev) AS control_nonpass,
       sum(r.verdict <> 'pass' AND r.device_id IS NULL) AS run_level_nonpass,
       sum(r.attempts = 2) AS retried,
       group_concat(CASE WHEN r.verdict = 'fail' AND r.device_id = :mdev
                         THEN r.case_id || ':' || coalesce(r.observed_category, '-')
                              || CASE WHEN r.attempts = 2 THEN '(1st ' || coalesce(r.first_attempt_category, '-') || ')'
                                      ELSE '' END END, ' ') AS catching
FROM runs ru LEFT JOIN results r USING (run_id)
WHERE ru.kind = 'mutant'
GROUP BY ru.run_id ORDER BY ru.mutant_id, ru.run_id"""

MUTANT_SUMMARY = """
WITH mr AS (""" + MUTANT_RUNS + """),
v AS (SELECT *, (fair AND harness_or_infra = 0 AND results > 0) AS valid FROM mr)
SELECT m.mutant_id, m.description, count(v.run_id) AS runs, coalesce(sum(v.valid), 0) AS valid_runs,
       coalesce(sum(v.valid AND v.caught_cases > 0), 0) AS detected_runs,
       CASE WHEN coalesce(sum(v.valid), 0) = 0 THEN 'NOT TESTED'
            WHEN sum(v.valid AND v.caught_cases > 0) = sum(v.valid) THEN 'CAUGHT'
            WHEN sum(v.valid AND v.caught_cases > 0) > 0 THEN 'CAUGHT (not every run)'
            ELSE 'MISSED' END AS outcome,
       (SELECT group_concat(DISTINCT cr.req_id) FROM results r JOIN runs ru2 USING (run_id)
          JOIN case_requirements cr USING (case_id)
          WHERE ru2.mutant_id = m.mutant_id AND r.verdict = 'fail' AND r.attribution = 'device'
            AND r.device_id = :mdev AND ru2.run_id IN (SELECT run_id FROM v WHERE valid)) AS catching_reqs,
       (SELECT group_concat(DISTINCT r.case_id || ':' || coalesce(r.observed_category, '-'))
          FROM results r JOIN runs ru2 USING (run_id)
          WHERE ru2.mutant_id = m.mutant_id AND r.verdict = 'fail' AND r.attribution = 'device'
            AND r.device_id = :mdev AND ru2.run_id IN (SELECT run_id FROM v WHERE valid)) AS catching_cases,
       coalesce(sum(CASE WHEN v.valid THEN v.control_nonpass END), 0) AS control_nonpass
FROM mutants m LEFT JOIN v USING (mutant_id)
GROUP BY m.mutant_id ORDER BY m.mutant_id"""

# ---- clean-baseline variability over a run set (:runs JSON array, or NULL = all fair baselines).
BASELINE_VARIABILITY = """
WITH b AS (
  SELECT r.case_id, coalesce(r.device_id, '(run)') AS device, r.verdict, r.observed_category, r.attempts,
         r.first_attempt_category, r.latency_ms
  FROM results r JOIN runs ru USING (run_id)
  WHERE ru.kind = 'baseline' AND """ + FAIR + """
    AND (:runs IS NULL OR ru.run_id IN (SELECT value FROM json_each(:runs)))),
l AS (
  SELECT case_id, device, latency_ms AS v,
         row_number() OVER (PARTITION BY case_id, device ORDER BY latency_ms) AS rn,
         count(*) OVER (PARTITION BY case_id, device) AS n
  FROM b WHERE latency_ms IS NOT NULL)
SELECT b.case_id, b.device, count(*) AS runs, sum(b.verdict = 'pass') AS passes,
       group_concat(DISTINCT coalesce(b.observed_category, '-')) AS observed,
       sum(b.attempts = 2) AS retried,
       (SELECT round(min(v), 1) FROM l WHERE l.case_id = b.case_id AND l.device = b.device) AS lat_min_ms,
       (SELECT round(avg(v), 1) FROM l WHERE l.case_id = b.case_id AND l.device = b.device
          AND rn IN ((n + 1) / 2, (n + 2) / 2)) AS lat_median_ms,
       (SELECT round(max(v), 1) FROM l WHERE l.case_id = b.case_id AND l.device = b.device) AS lat_max_ms
FROM b GROUP BY b.case_id, b.device ORDER BY b.case_id, b.device"""

# Baseline runs started on freshly restored golden clones: provenance recorded by the runner (REQ-10).
FRESH_BASELINE_RUNS = """
SELECT ru.run_id, (""" + FAIR + """) AS fair, ru.git_sha, ru.git_dirty, ru.started_at,
       ec.value AS ctl_provenance, ef.value AS field_provenance,
       (SELECT count(*) FROM results r WHERE r.run_id = ru.run_id) AS results,
       (SELECT sum(r.verdict = 'pass') FROM results r WHERE r.run_id = ru.run_id) AS passes
FROM runs ru
JOIN environment ec ON ec.run_id = ru.run_id AND ec.key = 'provenance.' || :ctl
JOIN environment ef ON ef.run_id = ru.run_id AND ef.key = 'provenance.' || :field
WHERE ru.kind = 'baseline' AND ec.value LIKE 'golden-restore%' AND ef.value LIKE 'golden-restore%'
ORDER BY ru.run_id"""


def rows(conn: sqlite3.Connection, sql: str, **params) -> tuple[list[tuple], list[str]]:
    cur = conn.execute(sql, params)
    return [tuple(r) for r in cur.fetchall()], [d[0] for d in cur.description]


def runs_param(run_ids) -> str | None:
    return None if run_ids is None else json.dumps(sorted(int(r) for r in run_ids))


def fresh_trial_runs(conn, ctl: str, field: str) -> list[int]:
    """Fair baseline run ids from DISTINCT golden restores (the first fair baseline after each restore)."""
    seen, out = set(), []
    for run_id, fair, *_rest in rows(conn, FRESH_BASELINE_RUNS, ctl=ctl, field=field)[0]:
        ctl_p, field_p = _rest[3], _rest[4]
        key = (ctl_p.split(" boot_id=")[0], field_p.split(" boot_id=")[0])
        if fair and key not in seen:
            seen.add(key)
            out.append(run_id)
    return out


# ---------------------------------------------------------------- acceptance assertions
# Each query returns the VIOLATIONS of one machine-checkable claim (empty = holds). {ATT} and {FLOWS} stand for the
# attempts and capture_flows tables (schema v4), or empty stand-ins on an older database (_sources).

# The CURRENT evidence for a case instance (case, device): EVERY result it has in the latest fair, non-mutant run that
# executed OR PLANNED it (report LATEST_PER_CASE). Not max(result_id) per instance: that showed only the newest of two
# conflicting results of one run, so a fail inserted before a pass vanished (second independent audit R-01); A19
# rejects the run. Not only runs that recorded it: a newer run that planned it and lost its result would hand the claim
# to an older run (FV-01 class, RC-4); A4 lists such an instance as planned without a result. {PLAN} = run_plan, or an
# empty stand-in on a store older than schema v5 (sql()).
LATEST_RUN = ("SELECT s.case_id, s.device_id, max(s.run_id) AS run_id FROM (SELECT run_id, case_id, device_id FROM "
              "results UNION SELECT run_id, case_id, device_id FROM {PLAN}) s JOIN runs ru USING (run_id) "
              "WHERE ru.kind <> 'mutant' AND " + FAIR + " GROUP BY s.case_id, s.device_id")
LATEST_CURRENT = ("SELECT r2.result_id FROM results r2 JOIN (" + LATEST_RUN + ") l ON l.case_id = r2.case_id AND "
                  "l.device_id IS r2.device_id AND l.run_id = r2.run_id")
NO_PLAN = "(SELECT NULL AS run_id, NULL AS case_id, NULL AS device_id WHERE 0)"
# The same selection over recorded results only: plain SQL valid on any schema, kept for scripts written against
# schema v4 (e.g. the independent audits' reproductions). It cannot see a planned instance whose result is missing;
# acceptance and the report use LATEST_CURRENT (through sql()).
LATEST_FAIR = LATEST_CURRENT.replace("{PLAN}", NO_PLAN)

# The latest valid run of each mutant (fair, >= 1 result, no infra/runner result): current mutant-detection evidence.
LATEST_VALID_MUTANT_RUNS = ("SELECT max(ru.run_id) FROM runs ru WHERE ru.kind = 'mutant' AND " + FAIR
                            + " AND EXISTS (SELECT 1 FROM results r WHERE r.run_id = ru.run_id) AND NOT EXISTS "
                            "(SELECT 1 FROM results r WHERE r.run_id = ru.run_id AND r.attribution IN ('infra', "
                            "'runner')) GROUP BY ru.mutant_id")

# A19: in a fair run every result is one well-formed catalog instance (per-device case <-> device set) and no
# instance has more than one result. Duplicates are listed with every row, never merged or deleted.
A19_CARDINALITY = """
WITH inst(case_id, per_device) AS (VALUES {instances})
SELECT 'run ' || r.run_id || ' ' || r.case_id || '/' || coalesce(r.device_id, '(run)') || ' result ' || r.result_id
       || ': ' || CASE WHEN i.case_id IS NULL THEN 'not a catalogued case'
                       WHEN i.per_device = 1 THEN 'per-device case recorded without a device'
                       ELSE 'run-level case recorded for a device' END
FROM results r JOIN runs ru USING (run_id) LEFT JOIN inst i ON i.case_id = r.case_id
WHERE """ + FAIR + """ AND (i.case_id IS NULL OR (i.per_device = 1) <> (r.device_id IS NOT NULL))
UNION ALL
SELECT 'run ' || r.run_id || ' ' || r.case_id || '/' || coalesce(r.device_id, '(run)') || ': ' || count(*)
       || ' results for one instance (' || group_concat(r.result_id || ' ' || r.verdict || '/' || r.attribution, ', ')
       || ')'
FROM results r JOIN runs ru USING (run_id) WHERE """ + FAIR + """
GROUP BY r.run_id, r.case_id, r.device_id HAVING count(*) > 1"""

ASSERTIONS = (
    ("A1-req-has-case", "every requirement traces to >= 1 case",
     "SELECT q.req_id FROM requirements q WHERE NOT EXISTS (SELECT 1 FROM case_requirements cr WHERE cr.req_id = q.req_id)"),
    ("A2-case-has-req", "every case traces to >= 1 requirement",
     "SELECT c.case_id FROM cases c WHERE NOT EXISTS (SELECT 1 FROM case_requirements cr WHERE cr.case_id = c.case_id)"),
    ("A3-case-executed", "every catalogued case has >= 1 result in a fair run",
     "SELECT c.case_id FROM cases c WHERE NOT EXISTS (SELECT 1 FROM results r JOIN runs ru USING (run_id) "
     "WHERE r.case_id = c.case_id AND " + FAIR + ")"),
    ("A4-req-current-evidence-passes", "every requirement has fair non-mutant evidence and the LATEST such result of "
     "every instance of every case mapped to it passes; latest = the latest fair run that recorded or PLANNED the "
     "instance (older passing runs cannot stand in for a current failure or a planned result that is missing)",
     "SELECT q.req_id || ': no fair non-mutant result' FROM requirements q WHERE NOT EXISTS (SELECT 1 FROM "
     "case_requirements cr JOIN results r USING (case_id) WHERE cr.req_id = q.req_id AND r.result_id IN (" + LATEST_CURRENT
     + ")) UNION ALL SELECT cr.req_id || ': ' || r.case_id || '/' || coalesce(r.device_id, '(run)') || ' latest ' || "
     "r.verdict || '/' || r.attribution || ' (run ' || r.run_id || ')' FROM case_requirements cr JOIN results r "
     "USING (case_id) WHERE r.result_id IN (" + LATEST_CURRENT + ") AND r.verdict <> 'pass' UNION ALL "
     "SELECT cr.req_id || ': ' || l.case_id || '/' || coalesce(l.device_id, '(run)') || ' planned in run ' || l.run_id "
     "|| ' but no result recorded (no older run stands in)' FROM (" + LATEST_RUN + ") l JOIN case_requirements cr "
     "USING (case_id) WHERE NOT EXISTS (SELECT 1 FROM results r WHERE r.run_id = l.run_id AND r.case_id = l.case_id "
     "AND r.device_id IS l.device_id)"),
    ("A5-fault-observed-as-predicted", "every brief fault F1-F13 has a fair result whose observed category equals "
     "the recorded prediction (verdict pass; the result's expected category is the catalog's, not one rewritten "
     "to match)",
     "WITH c(id) AS (VALUES " + ",".join(f"('{f}')" for f in CATALOG_FAULTS) + ") "
     "SELECT c.id FROM c WHERE NOT EXISTS (SELECT 1 FROM results r JOIN faults f USING (fault_id) JOIN runs ru "
     "USING (run_id) WHERE f.catalog_id = c.id AND r.observed_category = r.expected_category AND r.verdict = 'pass' "
     "AND r.expected_category = f.expected_category AND " + FAIR + ")"),
    ("A6-category-observed-live", "each of the 11 outcome categories was observed on the VMs in a fair run",
     "WITH c(cat) AS (VALUES " + ",".join(f"('{c}')" for c in CATEGORIES) + ") "
     "SELECT c.cat FROM c WHERE NOT EXISTS (SELECT 1 FROM results r JOIN runs ru USING (run_id) "
     "WHERE r.observed_category = c.cat AND " + FAIR + ")"),
    ("A7-no-device-blame-on-red-preflight", "no result is attributed to the device while its preflight was red",
     "SELECT result_id FROM results WHERE attribution = 'device' AND preflight <> 'green'"),
    ("A8-no-pass-with-blame", "no pass verdict carries an attribution",
     "SELECT result_id FROM results WHERE verdict = 'pass' AND attribution <> 'none'"),
    ("A9-faults-removed", "every recorded fault application in a finished run has a verified removal, and every "
     "decided (pass/fail) fault-case result of a fair run has a recorded application (no vacuous 'all removed' over "
     "missing records)",
     "SELECT e.event_id || ':' || e.fault_id || '@run' || e.run_id FROM fault_events e JOIN runs ru USING (run_id) "
     "WHERE ru.finished_at IS NOT NULL AND coalesce(e.removal_verified, 0) <> 1 UNION ALL "
     "SELECT 'run ' || r.run_id || ' ' || r.case_id || '/' || coalesce(r.device_id, '(run)') || ' ' || r.verdict "
     "|| ': fault-case result without a recorded fault application' FROM results r JOIN runs ru USING (run_id) "
     "JOIN cases c USING (case_id) WHERE c.kind = 'fault' AND r.verdict <> 'error' AND " + FAIR
     + " AND NOT EXISTS (SELECT 1 FROM fault_events e WHERE e.result_id = r.result_id)"),
    ("A10-retried-is-never-pass", "a result that needed the retry is never verdict pass (a pass only on retry is a "
     "FLAKE: fail; with at most one retry, 2 attempts mean attempt 1 did not meet the case)",
     "SELECT result_id FROM results WHERE attempts = 2 AND verdict = 'pass'"),
    ("A11-mutant-runs-labelled", "every run against a mutant build is kind=mutant with its mutant id (so it is "
     "never a baseline and never commissions a device)",
     "SELECT run_id FROM runs WHERE (kind = 'mutant') <> (mutant_id IS NOT NULL)"),
    ("A12-every-mutant-tested", "each of the six brief mutants has >= 1 valid (fair, no infra/runner result) run",
     "WITH m(mutant_id) AS (VALUES " + ",".join(f"('{m.mutant_id}')" for m in MUTANTS) + ") "
     "SELECT m.mutant_id FROM m WHERE NOT EXISTS (SELECT 1 FROM runs ru WHERE ru.mutant_id = m.mutant_id "
     "AND " + FAIR + " AND NOT EXISTS (SELECT 1 FROM results r WHERE r.run_id = ru.run_id "
     "AND r.attribution IN ('infra', 'runner')) AND EXISTS (SELECT 1 FROM results r WHERE r.run_id = ru.run_id))"),
    ("A13-environment-recorded", "every fair run recorded EVERY REQ-10 key (kernel/distro/qdisc/nft for every "
     "inventoried VM, python, git_sha, git_dirty, chrony.offset, runs.clean_env, fw_version for every inventoried "
     "device) as text in its one valid representation (runner/evidence.check_environment: kernel release, single-line "
     "distro, Python version, 40-hex git_sha EQUAL to runs.git_sha, git_dirty/clean_env equal to the run row, a "
     "finite SNTP offset with >= 1 sample against witness-ctl inside the preflight clock gate, qdiscs of every lab "
     "interface, an nft table, x.y.z firmware); other records of the same facts (runs.kind, mutant, device builds) "
     "agree; no key is recorded twice under two spellings. A firmware version may read 'unavailable (<CATEGORY>: ...)'"
     " only in a mutant run, for the mutant device, which withheld it. Unfair runs are not evidence and not checked",
     None),
    ("A16-retry-attribution", "no result is pass or attributed to the device when one of its attempts was not a fair "
     "device test (outcome runner/infra; for rows before schema v4: unclassifiable or restart observed)",
     "SELECT DISTINCT r.result_id || ':' || r.case_id || '/' || coalesce(r.device_id, '(run)') || '@run' || r.run_id "
     "|| ' ' || r.verdict || '/' || r.attribution || ' attempt ' || a.attempt_no || ' ' || coalesce(a.outcome, "
     "CASE WHEN a.category IS NULL THEN 'unclassifiable' ELSE 'restart observed' END) "
     "FROM results r JOIN {ATT} a ON a.result_id = r.result_id WHERE r.attribution IN ('none', 'device') "
     "AND (a.outcome IN ('runner', 'infra') OR (a.outcome IS NULL AND (a.category IS NULL "
     "OR a.detail LIKE '%restart observed%')))"),
    ("A17-capture-flow-evidence", "no fair-run capture-flow record marks a flow expected on the wire with 0 "
     "packets; and for every CURRENT result (current_evidence: latest fair result per instance, A18's baseline, A14's "
     "trials, each mutant's latest valid run) recorded under the capture-flow check, the records are DERIVED from its "
     "exchanges (complete and consistent per A24, including 'nothing sent' only for its stated reason) and the case's "
     "capture contract (ctl capture always, field capture for fault cases), never trusted and never skipped: every "
     "dialled flow x required capture has exactly one record whose expectation matches the exchange facts, and no "
     "record is unaccounted for, also on a result whose exchanges are missing. A latest fair result recorded before "
     "the check is listed (F3's 5021 flow included)", None),
    ("A19-result-cardinality", "in every fair run each result is a well-formed catalog instance and no case instance "
     "has more than one result (pass/fail duplicates, in either order, are ambiguous evidence; rows are kept, "
     "never merged)", A19_CARDINALITY),
    ("A20-evidence-verified", "the bytes behind the current evidence are verified: every evidence file indexed for a "
     "current result (and its run's session files) exists with its recorded length and sha256, and every flow it "
     "dialled onto the wire is recounted from its hash-verified capture file(s) (runner/evidence.flow_packets, "
     "independent of tcpdump): present, and equal to the recorded count. Without an evidence root nothing is "
     "verified and this is violated", None),
    ("A21-reference-data", "the reference tables the SQL joins against equal their sources: requirements = "
     "docs/requirements.md, cases/kinds and case->requirement map and faults/predictions and mutants = "
     "runner/catalog.py, devices = inventory.yaml (a deleted device or case cannot shrink the required sets)", None),
    ("A22-store-integrity", "the store is internally consistent: SQLite integrity_check is ok, no row survives its "
     "deleted parent (foreign_key_check empty), and the migration record (which says when each obligation starts) "
     "agrees with the schema and with the rows each migration governs (acceptance contract I1.1)", None),
    ("A23-run-selection", "every run's status flags agree with its records (environment runs.clean_env, session "
     "preflight checks, the runner's recorded contamination cause); every fair run executed exactly its declared "
     "selection, one result per planned instance and none unplanned (schema-v5 run plan written before its first case, "
     "equal to its indexed plan file; earlier runs: their case evidence directories), with session checks and session "
     "evidence indexed; every case evidence directory belongs to a result and every decided result has its directory; "
     "with an evidence root, session/environment.json is hash-verified and compared with the environment table and "
     "run identity for every recorded session, including mutant and superseded runs (I1.2-I1.7, I10.4)", None),
    ("A24-evidence-chain", "every current result satisfies its case contract (runner/contract.py): attempt rows 1..n = "
     "results.attempts (runner cases 1..2, fault cases 1, gateway/record cases none), summary columns equal their "
     "attempts, a pass rests on one attempt with outcome ok and green pre/postflight checks; each attempt's exchanges "
     "are ord 1..k in the case's command grammar (a series stops early only at a non-pass or deadline-cut exchange), "
     "dial the case's target, are chronological, recompute the attempt category, send nothing only for their stated "
     "reason, and a PASS carries its response; required captures and evidence files are indexed; fault applications "
     "and measurements as the case records them (I4-I7, I10.2, I10.3)", None),
)


def _has(conn, table: str, column: str | None = None) -> bool:
    if column is None:
        return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone() is not None
    return any(r[1] == column for r in conn.execute(f"PRAGMA table_info({table})"))


def _sources(conn) -> dict[str, str]:
    """Table expressions for v4/v5 records; empty stand-ins on an older database (never migrated here: read-only)."""
    v4 = _has(conn, "capture_flows") and _has(conn, "attempts", "outcome")
    return {"{ATT}": "attempts" if v4 else "(SELECT *, NULL AS outcome, NULL AS predicates FROM attempts)",
            "{FLOWS}": "capture_flows" if v4 else ("(SELECT NULL AS result_id, NULL AS capture, NULL AS filter, "
                                                  "NULL AS expected, NULL AS packets, NULL AS detail WHERE 0)"),
            "{PLAN}": "run_plan" if _has(conn, "run_plan") else NO_PLAN}


def sql(conn, text: str) -> str:
    """`text` with the {ATT}/{FLOWS}/{PLAN} table expressions of this store."""
    for k, v in _sources(conn).items():
        text = text.replace(k, v)
    return text


def _dicts(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def commissioning_coverage(conn, run_id: int, inv: dict | None = None) -> list[tuple[str, str | None, int]]:
    """(case, INVENTORY device or None for run-level, number of results) for every REQUIRED commissioning instance."""
    values, params = db._inventory_values(inv, conn)
    return [tuple(r) for r in conn.execute(db.COMMISSIONING_COVERAGE.format(
        required=db._required_values(), inventory=values), {"run": run_id, **params}).fetchall()]


def planned_instances(conn, run_id: int) -> set[tuple[str, str | None]] | None:
    """The run's declared selection (schema-v5 run plan), or None when it recorded none (earlier runs)."""
    rows = C.plan_rows(conn).get(run_id)
    return set(rows) if rows else None


def coverage_status(cov, planned: set | None = None) -> str:
    """INCOMPLETE: a required instance the run PLANNED has no result (a lost result: the run is not skipped);
    PARTIAL: a required instance was not selected (a deliberately partial run, or an earlier run without a plan);
    AMBIGUOUS: every instance executed, one of them more than once (duplicate or conflicting results); COMPLETE:
    exactly one result each."""
    if any(n == 0 and planned is not None and (c, d) in planned for c, d, n in cov):
        return "INCOMPLETE"
    if any(n == 0 for *_, n in cov):
        return "PARTIAL"
    return "AMBIGUOUS" if any(n > 1 for *_, n in cov) else "COMPLETE"


def latest_complete_baseline(conn, inv: dict | None = None) -> int | None:
    """Latest fair baseline run that SELECTED every required commissioning instance: planned it (schema-v5 plan) or,
    for a run without a plan, executed it (>= 1 result). A run with duplicate or conflicting results, or a planned
    instance whose result is missing, is not skipped (second independent audit R-01, final verification RC-4: A18
    silently fell back to an older run): it is selected, and its commissioning gaps name the defect."""
    for (run_id,) in conn.execute("SELECT run_id FROM runs ru WHERE ru.kind = 'baseline' AND " + FAIR
                                  + " ORDER BY run_id DESC").fetchall():
        planned = planned_instances(conn, run_id)
        cov = commissioning_coverage(conn, run_id, inv)
        if all((n >= 1) if planned is None else ((c, d) in planned) for c, d, n in cov):
            return run_id
    return None


def environment_violations(conn, inv: dict) -> list[str]:
    """A13: '<run>:<key>=<why>' for every invalid REQ-10 record of a fair run (runner/evidence.check_environment)."""
    env: dict[int, dict] = defaultdict(dict)
    for run_id, key, value in conn.execute("SELECT run_id, key, value FROM environment"):
        env[run_id][key] = value
    out = []
    for run in _dicts(conn.execute("SELECT * FROM runs ru WHERE " + FAIR + " ORDER BY ru.run_id")):
        chk = EV.check_environment(env.get(run["run_id"], {}), run, inv)
        out += [f"{run['run_id']}:{k}={why}" for k, why in sorted(chk.problems.items())]
    return out


def reference_violations(conn, inv: dict) -> list[str]:
    """A21: differences between the reference tables and their sources (catalog, inventory, docs/requirements.md)."""
    out = []

    def cmp(what, want: dict, got: dict):
        out.extend(f"{what} {k}: missing from the database" for k in sorted(want.keys() - got.keys(), key=str))
        out.extend(f"{what} {k}: not in its source" for k in sorted(got.keys() - want.keys(), key=str))
        out.extend(f"{what} {k}: database {got[k]} <> source {want[k]}" for k in sorted(want.keys() & got.keys(), key=str)
                   if want[k] != got[k])

    reqs = REPO / "docs/requirements.md"
    want = set(db.requirements_from_md(reqs)) if reqs.exists() else {q for c in CASES for q in c.reqs}
    cmp("requirement", dict.fromkeys(want, ()), {r[0]: () for r in conn.execute("SELECT req_id FROM requirements")})
    cmp("case", {c.case_id: (c.kind,) for c in CASES},
        {r[0]: (r[1],) for r in conn.execute("SELECT case_id, kind FROM cases")})
    cmp("case->requirement", {(c.case_id, q): () for c in CASES for q in c.reqs},
        {tuple(r): () for r in conn.execute("SELECT case_id, req_id FROM case_requirements")})
    cmp("fault", {f.fault_id: (f.catalog_id, f.kind, f.expected_category) for f in FAULTS},
        {r[0]: tuple(r[1:]) for r in conn.execute("SELECT fault_id, catalog_id, kind, expected_category FROM faults")})
    cmp("mutant", {m.mutant_id: () for m in MUTANTS},
        {r[0]: () for r in conn.execute("SELECT mutant_id FROM mutants")} if _has(conn, "mutants") else {})
    cmp("device", {d["device_id"]: (d["hostname"], d["address"], d["port"], d["serial"], d["fw_version"])
                   for d in inv["devices"]},
        {r[0]: tuple(r[1:]) for r in conn.execute("SELECT device_id, hostname, expected_addr, port, expected_serial, "
                                                  "expected_fw FROM devices")})
    return out


def current_evidence(conn, fresh_runs: list[int], a18_run: int | None) -> dict[int, str]:
    """{result_id: why} for the results the acceptance claims rest on: every latest fair result of a case instance
    (A4, traceability), every result of the baseline A18 evaluates and of the fresh-clone trials A14 counts, and of
    each mutant's latest valid run. A17/A20 verify these. Superseded fair runs stay in the store and the report but,
    as in A4, neither stand in for nor block the current evidence."""
    cur = {r[0]: "latest" for r in conn.execute(sql(conn, LATEST_CURRENT))}
    for runs, why in (([a18_run] if a18_run is not None else [], "A18 baseline"), (fresh_runs, "A14 trial"),
                      ([r[0] for r in conn.execute(LATEST_VALID_MUTANT_RUNS)], "latest valid mutant run")):
        for run in runs:
            for (rid,) in conn.execute("SELECT result_id FROM results WHERE run_id = ?", (run,)):
                cur.setdefault(rid, why)
    return cur


def flow_plan(conn, current: dict[int, str], src: dict | None = None) -> dict[int, dict]:
    """Every result of `current` with its records (runner/contract.load), why it is current, and its derived flows
    (runner/contract.derived_flows; a result without exchanges has none and is NOT dropped: FV-01)."""
    out = C.load(conn, current)
    for rid, r in out.items():
        r["why"] = current[rid]
        r["flows"] = C.derived_flows(r)
    return out


def capture_flow_violations(conn, plan: dict[int, dict], src: dict) -> list[str]:
    """A17 (see its claim): no fair-run record of an expected flow holds 0 packets, and the current results' records
    match their derived flows (runner/contract.flow_record_violations)."""
    out = [r[0] for r in conn.execute(
        "SELECT 'run' || r.run_id || ' ' || r.case_id || '/' || coalesce(r.device_id, '(run)') || ': ' || f.capture "
        "|| ' capture holds ' || coalesce(f.packets, 'no file') || ' packets of ' || f.filter "
        f"FROM {src['{FLOWS}']} f JOIN results r USING (result_id) JOIN runs ru USING (run_id) WHERE " + FAIR
        + " AND f.expected = 1 AND coalesce(f.packets, 0) = 0 ORDER BY f.result_id, f.capture")]
    return out + C.flow_record_violations(conn, plan, {rid: p["why"] for rid, p in plan.items()})


def evidence_violations(conn, current: dict[int, str], plan: dict[int, dict], root, inv: dict | None = None) -> list[str]:
    """A20 (see its claim): runner/contract.bytes_violations over the current results."""
    return C.bytes_violations(conn, plan, root, inv)


def integrity_violations(conn) -> list[str]:
    """A22: SQLite's own consistency checks (an orphaned child is evidence whose parent was deleted)."""
    out = [f"integrity_check: {r[0]}" for r in conn.execute("PRAGMA integrity_check").fetchall() if r[0] != "ok"]
    rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    by = defaultdict(int)
    for r in rows:
        by[(r[0], r[2])] += 1
    return out + [f"[I1.1] {n} {t} row(s) reference a missing {parent} row" for (t, parent), n in sorted(by.items())] \
        + C.schema_record_violations(conn)


def trial_problems(conn, run_id: int, inv: dict | None = None, root=None) -> list[str]:
    """Why a fresh-clone baseline is NOT a successful clean baseline: commissioning gaps (coverage, verdicts,
    pre/postflight, identity, firmware, build, run state, evidence contract) and retried results (a retry is never
    clean)."""
    out = [f"{dev}: {g}" for dev, g in db.commissioning_gaps(conn, run_id, inv, root).items() if g]
    retried = [r[0] for r in conn.execute("SELECT case_id || '/' || coalesce(device_id, '(run)') FROM results "
                                          "WHERE run_id = ? AND attempts = 2", (run_id,))]
    out += [f"retried: {', '.join(retried)}"] if retried else []
    return out


def audit(conn: sqlite3.Connection, *, min_fresh_baselines: int = 5, ctl: str | None = None,
          field: str | None = None, evidence_root: str | Path | None = None, inventory: dict | None = None) -> list[dict]:
    """Every acceptance assertion over `conn` (read-only). `evidence_root` is the directory the evidence table's paths
    are relative to; without it A20 cannot verify any bytes and is violated. `inventory` defaults to inventory.yaml."""
    inv = inventory or EV.repo_inventory()
    vm = {v["role"]: v["name"] for v in inv["lab"]["vms"]}
    ctl, field = ctl or vm["ctl"], field or vm["field"]
    out, python = [], {}
    src = _sources(conn)
    instances = ", ".join(f"('{c.case_id}', {int(c.per_device)})" for c in CASES)
    for aid, claim, text in ASSERTIONS:
        if text is None:
            python[aid] = claim
            continue
        for k, v in {**src, "{instances}": instances}.items():
            text = text.replace(k, v)
        bad = [r[0] for r in conn.execute(text).fetchall()]
        out.append({"id": aid, "claim": claim, "ok": not bad, "violations": bad})
    fresh = fresh_trial_runs(conn, ctl, field)
    problems = {r: trial_problems(conn, r, inv, evidence_root) for r in fresh}
    good = [r for r in fresh if not problems[r]]
    revs = sorted({f"{(s or '?')[:10]}{'+dirty' if d else ''}" for s, d in conn.execute(
        "SELECT git_sha, git_dirty FROM runs WHERE run_id IN (SELECT value FROM json_each(?))",
        (runs_param(good),)).fetchall()}) if good else []
    out.append({"id": "A14-fresh-baselines", "claim": f">= {min_fresh_baselines} fresh-clone clean baselines (first fair "
                "baseline after each distinct golden restore), each COMPLETE (one result per required commissioning "
                "instance), all pass, no retry, commissioning every inventoried device",
                "ok": len(good) >= min_fresh_baselines,
                "violations": [f"run {r}: {'; '.join(p)}" for r, p in problems.items() if p]
                + ([] if len(good) >= min_fresh_baselines else [f"only {len(good)} successful: {good}"]),
                "runs": good, "source_revisions": revs})
    flaky = rows(conn, Q2_FLAKY, runs=runs_param(fresh))[0] if fresh else []
    out.append({"id": "A15-fresh-baselines-stable", "claim": "no case verdict/category differs across those runs "
                "(nondeterminism would be listed here, not hidden)", "ok": bool(fresh) and not flaky,
                "violations": [f"{r[0]}/{r[1]}: {r[4]}" for r in flaky] or ([] if fresh else ["no fresh runs"])})
    latest = latest_complete_baseline(conn, inv)
    gaps = db.commissioning_gaps(conn, latest, inv, evidence_root) if latest is not None else {}
    out.append({"id": "A18-commissioning-complete", "claim": "the latest fair baseline that selected EVERY required "
                "commissioning instance (planned it; a run without a plan: executed it), a run with duplicate, "
                "conflicting or planned-but-missing results is not skipped, commissions every "
                "device of inventory.yaml (catalog-defined prerequisites incl. a valid environment record, "
                "runner/db.py commissioning_gaps)", "ok": latest is not None and not any(gaps.values()),
                "violations": (["no fair baseline executed the complete commissioning set"] if latest is None else
                               [f"run {latest} {dev}: {g}" for dev, g in gaps.items() if g]), "run": latest})
    current = current_evidence(conn, good, latest)
    plan = flow_plan(conn, current, src)
    chain = C.result_violations(conn, current, inv)
    runs = C.run_violations(conn, inv, evidence_root)
    if evidence_root is None:
        runs.append("[I1.3/I1.5] plan files and case directories not verified: no evidence root given")
    for aid, bad in (("A13-environment-recorded", environment_violations(conn, inv)),
                     ("A17-capture-flow-evidence", capture_flow_violations(conn, plan, src)),
                     ("A20-evidence-verified", evidence_violations(conn, current, plan, evidence_root, inv)),
                     ("A21-reference-data", reference_violations(conn, inv)),
                     ("A22-store-integrity", integrity_violations(conn)),
                     ("A23-run-selection", runs),
                     ("A24-evidence-chain", [v for rid in sorted(chain) for v in chain[rid]])):
        out.append({"id": aid, "claim": python[aid], "ok": not bad, "violations": bad})
    out.sort(key=lambda a: int(a["id"].split("-")[0][1:]))
    return out


def main(argv=None) -> int:
    """python3 -m runner.analysis --db witness.db [--evidence-root DIR] [--json out.json]: print every acceptance
    assertion; exit 1 if any is violated (machine-checkable acceptance, no prose). The evidence root defaults to
    <db dir>/evidence when that directory exists (A20 verifies the bytes there)."""
    import argparse
    import sys
    from runner import db
    p = argparse.ArgumentParser(description=main.__doc__.splitlines()[0])
    p.add_argument("--db", required=True)
    p.add_argument("--evidence-root")
    p.add_argument("--json")
    a = p.parse_args(argv)
    root = Path(a.evidence_root) if a.evidence_root else Path(a.db).parent / "evidence"
    res = audit(db.connect(a.db), evidence_root=root if (a.evidence_root or root.is_dir()) else None)
    for r in res:
        print(f"{'HOLDS   ' if r['ok'] else 'VIOLATED'} {r['id']}: {r['claim']}"
              + ("" if r["ok"] else f" -> {r['violations'][:10]}"))
    if a.json:
        with open(a.json, "w") as f:
            json.dump(res, f, indent=1, default=str)
    print(f"{sum(r['ok'] for r in res)}/{len(res)} hold", file=sys.stderr)
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    raise SystemExit(main())
