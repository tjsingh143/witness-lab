# Witness mutant report

Generated 2026-10-22T02:48:57.076Z from the SQLite results database only (no hand-entered results).

Scope: software-simulated sensor devices (Python processes) on a Linux VM, exercised over real TCP between two Ubuntu 24.04 VMs. This is not physical hardware or embedded firmware validation.

## 7. Mutants (brief 7.4): deliberately broken device builds on dev-a, dev-b stock as control

| mutant_id | description | runs | valid_runs | detected_runs | outcome | catching_reqs | catching_cases | control_nonpass |
|---|---|---|---|---|---|---|---|---|
| M1 | returns the other device's serial in IDENTIFY | 1 | 1 | 1 | CAUGHT | REQ-01,REQ-09 | C-IDENTIFY:WRONG_IDENTITY,C-GATEWAY:WRONG_IDENTITY | 0 |
| M2 | reuses seq after 5 reads (seq 1..5 repeats) | 1 | 1 | 1 | CAUGHT | REQ-04,REQ-05,REQ-09 | C-READ-CLOCK:STALE_DATA,C-READ-SERIES:STALE_DATA,C-GATEWAY:STALE_DATA | 0 |
| M3 | omits the trailing newline on every response | 1 | 1 | 1 | CAUGHT | REQ-01,REQ-03,REQ-04,REQ-05,REQ-09 | C-IDENTIFY:MALFORMED,C-HEALTH:MALFORMED,C-READ-CLOCK:MALFORMED,C-READ-SERIES:MALFORMED,C-GATEWAY:MALFORMED | 0 |
| M4 | echoes the wrong id (id-1) | 1 | 1 | 1 | CAUGHT | REQ-01,REQ-03,REQ-04,REQ-05,REQ-09 | C-IDENTIFY:MALFORMED,C-HEALTH:MALFORMED,C-READ-CLOCK:MALFORMED,C-READ-SERIES:MALFORMED,C-GATEWAY:MALFORMED | 0 |
| M5 | reports temp_c as a string | 1 | 1 | 1 | CAUGHT | REQ-04,REQ-05,REQ-09 | C-READ-CLOCK:MALFORMED,C-READ-SERIES:MALFORMED,C-GATEWAY:MALFORMED | 0 |
| M6 | sleeps 2.5 s on every 7th request (process-wide count) | 1 | 1 | 1 | CAUGHT | REQ-04,REQ-05 | C-READ-CLOCK:READ_TIMEOUT,C-READ-SERIES:READ_TIMEOUT | 0 |

Mutants caught: **6/6** (6 tested). Run-level detection: **6/6** valid mutant runs had >= 1 device-attributed failure on dev-a. A run is valid only if it is fair and has no infra/runner-attributed result (an infrastructure error is never counted as a detection). `control_nonpass` = non-pass results on the stock device in valid runs (false alarms); run-level cases (C-ENVIRONMENT) are listed per run, never as a catch.

Predictions recorded before the first mutant run (`mutants.predicted`):

| mutant | spec | predicted catch |
|---|---|---|
| M1 | other-serial:{other_serial} | C-IDENTIFY/dev-a WRONG_IDENTITY (REQ-01, REQ-02: never commissioned); C-GATEWAY/dev-a not healthy (gateway sees WRONG_IDENTITY). |
| M2 | seq-reuse | C-READ-CLOCK and C-READ-SERIES/dev-a STALE_DATA seq_not_increasing (REQ-05; 10 READs always span a wrap); C-GATEWAY/dev-a may also see STALE_DATA when one of its READs lands on a wrap. |
| M3 | no-newline | Every dev-a exchange: bytes arrive but no frame end before the 2 s read timeout -> MALFORMED (incomplete:NB) in C-IDENTIFY/C-HEALTH/C-READ-*/dev-a (REQ-01, REQ-03, REQ-04, REQ-05; REQ-06 bounded); gateway dev-a unhealthy. |
| M4 | off-by-one-id | Every dev-a exchange MALFORMED wrong_id (REQ-01, REQ-03, REQ-04, REQ-05); gateway dev-a unhealthy. |
| M5 | temp-string | C-READ-CLOCK and C-READ-SERIES/dev-a MALFORMED (schema: temp_c type) (REQ-04, REQ-05); IDENTIFY and HEALTH unaffected; gateway dev-a unhealthy (its poll READs). |
| M6 | slow-7th | Nondeterministic by design: whichever exchange is the device's 7th/14th/... request (runner or gateway) gets READ_TIMEOUT (2.5 s > 2.0 s read timeout). Runner commissioning cases retry once, so a case can pass on retry and be reported FLAKE (fail) or fail twice. A READ series (10-12 requests) usually holds a multiple of 7 unless gateway polls interleave and take it, so C-READ-CLOCK/C-READ-SERIES/dev-a are the likeliest catchers (REQ-04/05); a run where no runner exchange draws a 7th request is a false negative. |

### Per mutant run

| run_id | mutant_id | fair | results | harness_or_infra | caught_cases | control_nonpass | run_level_nonpass | retried | catching |
|---|---|---|---|---|---|---|---|---|---|
| 3 | M1 | 1 | 11 | 0 | 2 | 0 | 0 | 1 | C-IDENTIFY:WRONG_IDENTITY(1st WRONG_IDENTITY) C-GATEWAY:WRONG_IDENTITY |
| 4 | M2 | 1 | 11 | 0 | 3 | 0 | 0 | 2 | C-READ-CLOCK:STALE_DATA(1st STALE_DATA) C-READ-SERIES:STALE_DATA(1st STALE_DATA) C-GATEWAY:STALE_DATA |
| 5 | M3 | 1 | 11 | 0 | 5 | 0 | 1 | 4 | C-IDENTIFY:MALFORMED(1st MALFORMED) C-HEALTH:MALFORMED(1st MALFORMED) C-READ-CLOCK:MALFORMED(1st MALFORMED) C-READ-SERIES:MALFORMED(1st MALFORMED) C-GATEWAY:MALFORMED |
| 6 | M4 | 1 | 11 | 0 | 5 | 0 | 0 | 4 | C-IDENTIFY:MALFORMED(1st MALFORMED) C-HEALTH:MALFORMED(1st MALFORMED) C-READ-CLOCK:MALFORMED(1st MALFORMED) C-READ-SERIES:MALFORMED(1st MALFORMED) C-GATEWAY:MALFORMED |
| 7 | M5 | 1 | 11 | 0 | 3 | 0 | 0 | 2 | C-READ-CLOCK:MALFORMED(1st MALFORMED) C-READ-SERIES:MALFORMED(1st MALFORMED) C-GATEWAY:MALFORMED |
| 8 | M6 | 1 | 11 | 0 | 2 | 0 | 1 | 2 | C-READ-CLOCK:READ_TIMEOUT(1st READ_TIMEOUT) C-READ-SERIES:READ_TIMEOUT(1st READ_TIMEOUT) |

### Every non-pass result in mutant runs (the evidence)

| mutant | run | case | device | first attempt | observed | verdict | attribution | detail | evidence |
|---|---|---|---|---|---|---|---|---|---|
| M1 | 3 | C-GATEWAY | dev-a | WRONG_IDENTITY | WRONG_IDENTITY | fail | device | observed=WRONG_IDENTITY expected=PASS [gateway dev-a: state=wrong_identity polls=1141]; failed predicates: identity_matches_inventory,state_healthy_reachable | [run-3/C-GATEWAY__dev-a](../evidence/run-3/C-GATEWAY__dev-a/) |
| M1 | 3 | C-IDENTIFY | dev-a | WRONG_IDENTITY | WRONG_IDENTITY | fail | device | observed=WRONG_IDENTITY expected=PASS [identity: serial serial=WIT-0002!=WIT-0001] | [run-3/C-IDENTIFY__dev-a](../evidence/run-3/C-IDENTIFY__dev-a/) |
| M2 | 4 | C-GATEWAY | dev-a | STALE_DATA | STALE_DATA | fail | device | observed=STALE_DATA expected=PASS [gateway dev-a: state=stale polls=1155]; failed predicates: read_fresh,state_healthy_reachable | [run-4/C-GATEWAY__dev-a](../evidence/run-4/C-GATEWAY__dev-a/) |
| M2 | 4 | C-READ-CLOCK | dev-a | STALE_DATA | STALE_DATA | fail | device | observed=STALE_DATA expected=PASS [freshness: seq_not_increasing:1<=5] | [run-4/C-READ-CLOCK__dev-a](../evidence/run-4/C-READ-CLOCK__dev-a/) |
| M2 | 4 | C-READ-SERIES | dev-a | STALE_DATA | STALE_DATA | fail | device | observed=STALE_DATA expected=PASS [freshness: seq_not_increasing:1<=5] | [run-4/C-READ-SERIES__dev-a](../evidence/run-4/C-READ-SERIES__dev-a/) |
| M3 | 5 | C-ENVIRONMENT | (run) |  |  | fail | device | 14/15 required environment keys valid; withheld by the device: fw_version.dev-a; failed: fw_version.dev-a | [run-5/C-ENVIRONMENT__run](../evidence/run-5/C-ENVIRONMENT__run/) |
| M3 | 5 | C-GATEWAY | dev-a | MALFORMED | MALFORMED | fail | device | observed=MALFORMED expected=PASS [gateway dev-a: state=protocol_error polls=1170]; failed predicates: state_healthy_reachable | [run-5/C-GATEWAY__dev-a](../evidence/run-5/C-GATEWAY__dev-a/) |
| M3 | 5 | C-HEALTH | dev-a | MALFORMED | MALFORMED | fail | device | observed=MALFORMED expected=PASS [read: incomplete:57B]; failed predicates: health_payload | [run-5/C-HEALTH__dev-a](../evidence/run-5/C-HEALTH__dev-a/) |
| M3 | 5 | C-IDENTIFY | dev-a | MALFORMED | MALFORMED | fail | device | observed=MALFORMED expected=PASS [read: incomplete:86B] | [run-5/C-IDENTIFY__dev-a](../evidence/run-5/C-IDENTIFY__dev-a/) |
| M3 | 5 | C-READ-CLOCK | dev-a | MALFORMED | MALFORMED | fail | device | observed=MALFORMED expected=PASS [read: incomplete:77B] | [run-5/C-READ-CLOCK__dev-a](../evidence/run-5/C-READ-CLOCK__dev-a/) |
| M3 | 5 | C-READ-SERIES | dev-a | MALFORMED | MALFORMED | fail | device | observed=MALFORMED expected=PASS [read: incomplete:57B] | [run-5/C-READ-SERIES__dev-a](../evidence/run-5/C-READ-SERIES__dev-a/) |
| M4 | 6 | C-GATEWAY | dev-a | MALFORMED | MALFORMED | fail | device | observed=MALFORMED expected=PASS [gateway dev-a: state=protocol_error polls=1184]; failed predicates: state_healthy_reachable | [run-6/C-GATEWAY__dev-a](../evidence/run-6/C-GATEWAY__dev-a/) |
| M4 | 6 | C-HEALTH | dev-a | MALFORMED | MALFORMED | fail | device | observed=MALFORMED expected=PASS [schema: wrong_id]; failed predicates: health_payload | [run-6/C-HEALTH__dev-a](../evidence/run-6/C-HEALTH__dev-a/) |
| M4 | 6 | C-IDENTIFY | dev-a | MALFORMED | MALFORMED | fail | device | observed=MALFORMED expected=PASS [schema: wrong_id] | [run-6/C-IDENTIFY__dev-a](../evidence/run-6/C-IDENTIFY__dev-a/) |
| M4 | 6 | C-READ-CLOCK | dev-a | MALFORMED | MALFORMED | fail | device | observed=MALFORMED expected=PASS [schema: wrong_id] | [run-6/C-READ-CLOCK__dev-a](../evidence/run-6/C-READ-CLOCK__dev-a/) |
| M4 | 6 | C-READ-SERIES | dev-a | MALFORMED | MALFORMED | fail | device | observed=MALFORMED expected=PASS [schema: wrong_id] | [run-6/C-READ-SERIES__dev-a](../evidence/run-6/C-READ-SERIES__dev-a/) |
| M5 | 7 | C-GATEWAY | dev-a | MALFORMED | MALFORMED | fail | device | observed=MALFORMED expected=PASS [gateway dev-a: state=protocol_error polls=1199]; failed predicates: state_healthy_reachable | [run-7/C-GATEWAY__dev-a](../evidence/run-7/C-GATEWAY__dev-a/) |
| M5 | 7 | C-READ-CLOCK | dev-a | MALFORMED | MALFORMED | fail | device | observed=MALFORMED expected=PASS [schema: type:temp_c] | [run-7/C-READ-CLOCK__dev-a](../evidence/run-7/C-READ-CLOCK__dev-a/) |
| M5 | 7 | C-READ-SERIES | dev-a | MALFORMED | MALFORMED | fail | device | observed=MALFORMED expected=PASS [schema: type:temp_c] | [run-7/C-READ-SERIES__dev-a](../evidence/run-7/C-READ-SERIES__dev-a/) |
| M6 | 8 | C-ENVIRONMENT | (run) |  |  | fail | device | 14/15 required environment keys valid; withheld by the device: fw_version.dev-a; failed: fw_version.dev-a | [run-8/C-ENVIRONMENT__run](../evidence/run-8/C-ENVIRONMENT__run/) |
| M6 | 8 | C-READ-CLOCK | dev-a | READ_TIMEOUT | READ_TIMEOUT | fail | device | observed=READ_TIMEOUT expected=PASS [read: no_bytes_by_deadline] | [run-8/C-READ-CLOCK__dev-a](../evidence/run-8/C-READ-CLOCK__dev-a/) |
| M6 | 8 | C-READ-SERIES | dev-a | READ_TIMEOUT | READ_TIMEOUT | fail | device | observed=READ_TIMEOUT expected=PASS [read: no_bytes_by_deadline] | [run-8/C-READ-SERIES__dev-a](../evidence/run-8/C-READ-SERIES__dev-a/) |
