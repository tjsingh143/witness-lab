# Witness requirements (v1)

Status: **final for Phase 1**, written before any test code. Each requirement has an
ID, a measurable pass/fail rule and its evidence source. Categories, deadlines
and the verdict-vs-category distinction are defined in `docs/protocol.md`.
Every test case must trace to ≥1 REQ-ID, and every REQ-ID must have ≥1 case.

Fixed parameters used below (rationale in protocol.md section 7):
latency budget **500 ms**, connect timeout **1.0 s**, read timeout **2.0 s**,
per-case deadline **30 s**, clock window **±2.0 s**, gateway poll interval
**P = 2.0 s** (chosen so 3·P = 6 s detection is well under the 10 s restart budget
and the poller's per-device attempt deadline of 4 s fits within one interval with
two devices polled concurrently).

**Phase 3 correction (2026-10-17) of the rationale above, not of any value or REQ row:** a 4 s poll does
not fit inside a 2 s interval. What holds is: each device has its own poller, polls run on a fixed
2 s schedule and an overrunning poll skips the missed slots instead of queueing them, so a failure
that starts at time t is reported by a poll that starts no later than t + P and ends no later than
its 4 s deadline: detection ≤ P + 4 s = 6 s = 3·P (REQ-09) for every failure mode, timeouts
included. Recovery after the cause disappears needs one poll that starts afterwards: ≤ P + one
poll's duration < 2·P (REQ-08). Definitions: docs/protocol.md section 10.

| ID | Requirement | Pass rule (all must hold) | Fail / error | Evidence |
|---|---|---|---|---|
| REQ-01 | Each inventoried device answers IDENTIFY within 500 ms on the lab network, and its identity matches the inventory. | Clean run, no fault. For every device in `inventory.yaml`, the IDENTIFY attempt to its hostname observes **PASS** (not PASS_SLOW), so `latency_ms ≤ 500`, and `serial`, `device_id`, `fw_version` are byte-equal to the inventory row. | PASS_SLOW, any other category, or any field mismatch → `fail`. | results row per device, latency_ms, pcap |
| REQ-02 | A device whose reported identity does not match the inventory is reported as WRONG_IDENTITY and never counted as commissioned. | With fault F7 active (`dev-a.lab` → 10.77.2.12), the IDENTIFY to `dev-a.lab` observes **WRONG_IDENTITY** with detail naming `serial` and `device_id`. The run's commissioned-device set (query over results) does **not** contain `dev-a`. | Any other category, or `dev-a` counted commissioned → `fail`. | results, /etc/hosts snapshot, report query |
| REQ-03 | HEALTH returns `status: ok` and `sensor_ok: true` within 500 ms for a commissioned device. | For each device that passed REQ-01 in the same run: HEALTH observes **PASS** (`latency_ms ≤ 500`) with `status == "ok"` and `sensor_ok is true`. | Category ≠ PASS, `degraded`, or `sensor_ok false` → `fail` (category may still be PASS; see protocol.md section 8). | results, response JSON |
| REQ-04 | READ timestamps are within ±2 s of the runner's clock. | Preflight: field chrony has ctl selected and raw SNTP offset ctl↔field \|x\| < 100 ms (`scripts/lib/ntp_offset.py`). Then **10/10** READs per device satisfy `t_send − 2.0 s ≤ ts ≤ t_recv + 2.0 s`. | Any READ outside the window → STALE_DATA → `fail`. Preflight clock check red → `error`/`infra`. | results, `ntp_offset.py` + `chronyc sources` in environment |
| REQ-05 | Over 10 consecutive READs, `seq` strictly increases and `ts` does not go backwards. | 10 READs on one connection, one device, finished within the per-case deadline: for i = 2..10, `seq[i] > seq[i−1]` and `ts[i] ≥ ts[i−1]`. HEALTH `uptime_s` before and after shows no restart. | Violation → STALE_DATA → `fail`. Restart observed in window → `error`/`infra`. | results, response log |
| REQ-06 | Malformed responses are classified MALFORMED; the runner never crashes or hangs on them. | For each malformed stimulus (device modes `malformed`, `truncated`, `wrong-id`; mutants: no newline, wrong id, `temp_c` string): observed **MALFORMED**; the case completes in ≤ 30 s; the pytest process records a result row (no unhandled exception, no missing row). | Other category → `fail`. Hang past the deadline or harness exception → `error`/`runner` (and the requirement fails). | results, runner log, wall time |
| REQ-07 | A response slower than the read timeout is classified TIMEOUT. A response inside the timeout but over the latency budget is PASS_SLOW, with latency recorded. | (a) With a delay putting total latency in (500 ms, 2000 ms]: observed **PASS_SLOW**, with `latency_ms` recorded and inside that interval. (b) With a delay beyond the read timeout: observed **READ_TIMEOUT** (or CONNECT_TIMEOUT if the handshake itself exceeds 1.0 s; the case states which it expects), and the attempt returns within timeout + 0.5 s. | Wrong category, missing latency, or an unbounded wait → `fail`. | results, netem qdisc snapshot, pcap |
| REQ-08 | After a device service restart, the device is healthy again within 10 s and the gateway reports recovery within two poll intervals. | `t_restart` = when `systemctl restart witness-device@<x>` returns. The first PASS HEALTH arrives with `detection_ms ≤ 10000` from `t_restart`. The gateway's `GET /devices/<id>` shows the device reachable/healthy ≤ 2·P = 4.0 s after that first PASS HEALTH. | Either bound exceeded → `fail`. | results (`detection_ms`), gateway log, journalctl |
| REQ-09 | The gateway marks a device unreachable within 3 poll intervals of it going away, and the detection time is recorded. | `t_fault` = when the fault (F1 stop, F5 route delete or F8 drop) is applied. The gateway state for that device becomes unreachable with `detection_ms ≤ 3·P = 6000`, and `detection_ms` is non-null in results. | Not detected within 6 s, or detection_ms null → `fail`. | results, gateway API samples |
| REQ-10 | Every run records its environment. | The `environment` table for the run has non-empty values for: `kernel` and `distro` (both VMs), `python`, `git_sha`, `git_dirty`, `fw_version.<device>` for every device, `qdisc.<vm>` (`tc qdisc show`), `nft.<vm>` (`nft list ruleset`), `chrony.offset` (raw SNTP ctl↔field), and `runs.clean_env` is 0/1, never NULL. | Any key missing/empty → `fail` (the run itself is still kept). | environment rows |

## Traceability (derived, never hand-edited)

The table is **generated from SQLite** by `runner/report.py` into
`results/reports/commissioning-report.md` (section 3). The case catalog
(`runner/catalog.py`) is loaded into `cases` and the many-to-many `case_requirements`
table at the start of every run, and this file's REQ table is parsed into `requirements`,
so neither side is duplicated by hand.

Implemented derivation (Phase 2; replaces the planned one-REQ-per-case query):

```sql
SELECT q.req_id, q.text,
       (SELECT group_concat(cr.case_id, ', ') FROM case_requirements cr WHERE cr.req_id = q.req_id) AS cases
FROM requirements q ORDER BY q.req_id;
-- latest result per (case, device) for one REQ:
SELECT r.case_id, r.device_id, r.run_id, r.observed_category, r.verdict, r.attribution
FROM results r
WHERE r.result_id IN (SELECT max(result_id) FROM results GROUP BY case_id, device_id)
  AND r.case_id IN (SELECT case_id FROM case_requirements WHERE req_id = :req);
```

A REQ row without cases is a traceability gap and the report flags it. After Phase 2,
REQ-08 and REQ-09 (gateway) were the known gaps; Phase 3 added FT-F12-RESTART (REQ-08) and
C-GATEWAY, GW-F1/F5/F8-UNREACHABLE (REQ-09). The report shows no gaps.

**Phase 4 note (2026-10-17), derivation only; no REQ row changed.** The latest-result query above now
takes the latest result per (case, device) from *fair* runs only (finished, `clean_env = 1`, not
contaminated) and excludes mutant runs (`runs.kind = 'mutant'`, schema v3), so a deliberately broken
build or an unclean run can never appear as a requirement's latest evidence (`runner/report.py`
`LATEST_PER_CASE`). Coverage is also asserted in SQL (`runner/analysis.py` `ASSERTIONS` A1–A15: every REQ
has a case, every case a REQ, every case executed in a fair run, every REQ has passing fair evidence,
F1–F13 observed as predicted, all 11 categories observed live, five fresh-clone baselines), written to
`results/reports/acceptance-audit.md/.json`. New case FT-F7-NAME-MISSING (REQ-01) produces RESOLVE_FAIL.

**Independent-audit remediation note (2026-10-18), derivation and acceptance only; no REQ row changed.** The
audit (`docs/independent-audit.md`, verdict FAIL) showed two derivations weaker than the rows above:
- REQ-02's "commissioned-device set (query over results)" only required the commissioning cases a run happened to
  contain, so a HEALTH-only run commissioned both devices (F-01). The set is now `runner/db.py`
  `COMMISSIONING_GAPS`: every commissioning case of the catalog (`runner/catalog.py` `COMMISSIONING_REQUIRED`), per
  device and run-level, exactly one passing result each with green pre/postflight, a finished clean uncontaminated
  baseline, no WRONG_IDENTITY, recorded firmware equal to the inventory, stock build. A partial run commissions nothing.
- The acceptance assertions could stay green over missing REQ-10 values or failing fresh baselines (F-06). A13 now
  checks every REQ-10 key of the table above (both VMs, every device) for a non-empty valid value; A4 uses the
  latest fair result of every case instance; A14 counts only complete, all-pass, retry-free fresh-clone baselines;
  new A16 (retry attribution), A17 (dialled flow present in the captures), A18 (latest complete baseline
  commissions every device). The assertions are necessary machine checks over the evidence, not a certificate.
- REQ-05's restart window and REQ-08's gateway recovery use the corrected restart inference (protocol.md
  section 6, F-02); the 30 s per-case deadline of REQ-05/06 is one absolute deadline across retries (section 7, F-03).

**Second independent-audit remediation note (2026-10-19), derivation and acceptance only; no REQ row changed.** The
re-audit (`docs/independent-reaudit.md`, verdict FAIL, R-01/R-02) showed the derivations above were still weaker than
stated: REQ-10's "non-empty" was checked with SQL `trim()` (spaces only), so a tab/newline value, a garbage
`chrony.offset` or a `git_sha` contradicting the run row passed acceptance; a pass and a conflicting fail for one case
instance in one run were hidden by "latest = max(result_id)"; and the capture-flow check trusted whatever rows existed.
- REQ-10 is now one definition (`runner/evidence.py` `check_environment`) used by the live C-ENVIRONMENT case, by
  commissioning and by acceptance A13: the keys come from the inventory (every VM, every device), each value must be
  text in its one valid representation, and it must agree with the run row and with other records of the same fact.
  `fw_version.<device> = unavailable (<CATEGORY>: ...)` (the device withheld it) is honest only for the mutant device of
  a mutant run.
- Every case instance has exactly one result per run (A19); "latest" means every result of the latest fair run that
  recorded or planned the instance, so a conflicting duplicate is visible in either insertion order, and a run holding
  one is AMBIGUOUS: no device whose prerequisites include the duplicated instance is commissioned by it (A18 evaluates
  it instead of skipping to an older run).
- REQ-01's packet evidence: the capture-flow records of the current evidence are derived from the recorded exchanges and
  the case's capture contract (A17), and the bytes are verified: indexed sha256 and packets recounted from the capture
  files (A20). A21 checks that the reference tables equal the catalog and inventory.
- No obligation is derived from the evidence it constrains ([acceptance-contract.md](acceptance-contract.md), final
  independent verification FV-01/FV-02): each case's attempts, command grammar, dialled target, captures, evidence files,
  fault applications and measurements come from the catalog case contract (A24); each run's selection from its run plan,
  recorded before its first case (schema v5), or, for earlier runs, from its case evidence directories (A23); store
  integrity from SQLite's own checks (A22); the required devices from the inventory, also in standalone commissioning.
