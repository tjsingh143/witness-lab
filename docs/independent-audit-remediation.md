# Witness: remediation of the independent audit findings F-01 to F-08

Remediation window 2026-10-17T23:56Z to 2026-10-18T01:20Z (UTC), one session, on the same Mac and the same two
Lima VMs the audit used. **This document does not say Witness passed its audit.** The audit
(`docs/independent-audit.md`, verdict **FAIL**) is kept unchanged as the historical record; a fresh independent
reviewer decides acceptance. Every claim below is tied to a log under `results/logs/remediation-*`, a database row in
`results/witness.db` (copied from witness-ctl), or a commit.

Evidence labels: **H** = macOS host, loopback or synthetic data (proves code logic, not VM behaviour);
**VM** = executed on witness-ctl/witness-field over the lab network; **DB** = SQL over the recorded store.

## 0. Starting state and preservation

| Item | Value |
|---|---|
| Audited code | `633df97` (handoff `04c0fb5`); the working tree's runner/device/gateway/scripts/tests were byte-identical to `633df97` (`git diff --quiet`, logged) |
| Audit report | committed verbatim first, alone: `3c8de6c`, sha256 `db8aa70e4399807d3cc84179ce51b1cb7ef05589d9337610357ab9a368384f3c` |
| Audit artifacts | `/tmp/witness-independent-audit-20261017/` copied to `~/Desktop/Witness/independent-audit-evidence-20261017/` (outside Git): 454 files, `SHA256SUMS`, copy verified byte-identical; `vm-evidence.tar` sha256 `7d5892d3…a181` as in the audit |
| PROJECT_BRIEF.md | sha256 `07a33a088939c9cc59ef4dbbfb12706ad17431d9eb4d8b5353feafdcea555baf`, unchanged |
| Original results DB | `results/witness.db` sha256 `95bb9f37…bca1`, max run 130, before any remediation run |
| Lab | both VMs Running, preflight GREEN 23:56:53Z (`remediation-initial-preflight-*`); golden clones and `vigil` Stopped |
| Mac disk | 8.3 GiB free at start (see section 5: it fell to 1.8 GiB under host memory pressure) |

Commits: `7e255ed` (all eight repairs, tests, docs), `c335c84` (flow check keyed on the runner's port), `0943fd5`
(evidence-overwrite fix found during verification), `d125939`/`3a9bbbc`/`4969e30` (scripts and logs), then the
handoff commit with this document, reports and evidence text.

## 1. Summary

| Finding | Correction (main code) | Pre-fix reproduction (unchanged audit scripts where possible) | Post-fix result | Status |
|---|---|---|---|---|
| F-01 P1 partial run commissions | `runner/db.py` `COMMISSIONING_GAPS` over `catalog.COMMISSIONING_REQUIRED`; report PARTIAL/COMPLETE | H: HEALTH-only in-memory run -> `['dev-a']`; DB: audit VM run 3 -> `['dev-a','dev-b']` | H: `[]`; DB audit run 3: `[]`, PARTIAL 2/11; **VM**: new HEALTH-only run (separate DB) -> `[]` with every missing case listed | corrected, verified |
| F-02 P2 early restart missed | `runner/classify.restart_between` (gateway + runner) | H: gateway `stale` 4.305 s after first PASS HEALTH, `restarts_detected 0` | H: healthy, restart counted, 5/5 trials 1780-1822 ms at P=2 s; **VM**: FT-F12 early second restart, 5 runs where uptime ROSE, all detected, 927.5-1265.9 ms | corrected, verified |
| F-03 P2 deadline excludes retry | one absolute deadline (`cases.case_deadline`), clamped I/O (`client.Connection(case_deadline=)`) | H: 31.592 s, `fail/device` | H: 30.007 s and 30.0 s, `error/runner`; **VM**: netem 1300 ms on lab traffic, 30.006 s, `error/runner`, fault reverted | corrected, verified |
| F-04 P2 retry rewrites blame | `cases.decide` over all attempts; `attempts.outcome/predicates` (schema v4); Q5 predicate-based | H: runner->PASS and restart->PASS became `fail/device` FLAKE | H: `error/runner`, `error/infra`; degraded->healthy and device->PASS stay FLAKE; **VM**: M6 retry recorded with outcomes device->ok | corrected, verified |
| F-05 P2 device accepts forbidden requests | `device.Device.parse_request` frame rules = runner's | **VM**: 10/30 stimuli violated the contract on both devices | **VM**: 30/30 match on both devices | corrected, verified |
| F-06 P2 false-green acceptance | A4/A13/A14 strengthened; A16-A18 added; schema-tolerant audit | H/DB: both audit counterexamples left 15/15 true | DB: both now fail (A13 / A14); real store 18/18 hold | corrected, verified |
| F-07 P2 F3 captures miss 5021 | filters = inventory ports + `Fault.capture_ports`; `capture_flows` check; faultctl validates ports | H: run-119 ctl and field pcaps: 0 packets on 5021 (34/34 historical F3 captures) | **VM**: runs 133 and 146: 4 packets of 10.77.2.11:5021 in each capture (SYN/RST pairs); 260/260 expected flows present | corrected, verified; history annotated |
| F-08 P3 variant count | `catalog.counts()`; README and fault report quote it; unit test | README "20 variants" | 13 types / 21 variants / 24 live fault-test instances, catalog-derived | corrected |

Full regression on the final code (`0943fd5`): unit 279/279 on macOS and on witness-ctl; ShellCheck clean; baseline
runs 145 and 150 11/11; fault run 146 24/24; FT-F12 runs 147-149; mutants M1-M6 caught (runs 139-144 on `3a9bbbc`);
acceptance 18/18 on the real store; lab clean at the end. Details in section 4.

## 2. Findings

### F-01 (P1): a partial baseline commissioned devices

**Root cause.** `db.commissioned_devices` required only the commissioning cases that already had a result in the run
(`c.case_id IN (SELECT case_id FROM results WHERE run_id = r.run_id ...)`), so the required set shrank to whatever ran.
Missing run-level checks did not disqualify a device, and the unit test `test_commissioned_devices` encoded an incomplete
set as correct.

**Change.** `runner/catalog.py` `COMMISSIONING_REQUIRED` is derived from the case catalog (every commissioning case,
per device or run-level). `runner/db.py` `COMMISSIONING_GAPS` (one SQL statement) returns, per inventoried device, every
unmet prerequisite: run kind baseline, finished, clean, uncontaminated; for every required instance exactly one result,
verdict pass, preflight and postflight green (missing, duplicate and conflicting results are named); no WRONG_IDENTITY
on the device anywhere in the run; no other non-pass result on it; recorded `fw_version.<dev>` equal to the inventory;
`device_build.<dev>` = stock. `commissioned_devices` = devices with no gap. `COMMISSIONING_COVERAGE` counts executed
instances. `runner/report.py` section 2 states the rule, labels the latest fair baseline COMPLETE/PARTIAL with
`n/11` instances and a per-device "unmet prerequisites" column, and when it is partial also shows the latest COMPLETE
baseline. The old incomplete-set test was removed.

**Tests.** `tests/unit/test_commissioning_rule.py` (new, 24 tests; 11 of them remove one required instance each): the audit's HEALTH-only shapes
(one row and the VM run-3 shape), each of the 11 required instances missing in turn, duplicate pass+pass and pass+fail,
unfinished/unclean/contaminated/fault-kind runs, an aborted run marked by the next session, missing postflight and a
runner error on one device, WRONG_IDENTITY, withheld firmware, missing and mutant builds, report wording.
`tests/unit/test_acceptance.py` A18.

**Pre-fix.** `remediation-repro-pre-host-*`: in-memory HEALTH-only run commissioned `['dev-a']`.
`remediation-repro-pre-f01-auditdb-*`: on the auditor's real-VM DB (read-only) run 3 (two C-HEALTH rows only)
commissioned `['dev-a','dev-b']` and the report said "Commissioned (all commissioning cases pass…): dev-a, dev-b".

**Post-fix.** H: the audit's `adversarial.py` (unchanged except the path of its scratch DB copy) now prints
`commissioned= []`. DB: the auditor's run 3 gives
`[]` with five missing instances per device and "PARTIAL (2/11)"; their complete run 1 still commissions both
(`remediation-verify-f01-auditdb-*`). **VM** (`remediation-verify-f01-partial-run-vm-20261018T004212Z.log`): the audit's
command shape `-m commissioning -k test_health` into a separate test DB `/var/lib/witness/remediation/partial-commissioning.db`
(main DB untouched): 2 passed, run clean and finished, `commissioned_devices = []`, report "PARTIAL commissioning run
(2/11 required instances executed). Commissioned by it: none". The real store's latest complete baselines (131, 145,
150) commission both devices (A18).

**Re-evaluation of history.** Under the corrected rule 16 of the 40 fair baselines commission both devices (runs 98-105,
118, 126, 127, 130, 131, 145, 150 among them). Runs 1-68 do not: they predate the recorded device build (Phase 4) and
runs 1-25 also predate C-GATEWAY (Phase 3). That is the intended conservative consequence, not a rewrite: those runs
did not verify what the rule now requires.

**Limitation.** The required set is the current catalog; adding a commissioning case later makes older runs
non-commissioning (conservative by design).

### F-02 (P2): gateway missed an early restart

**Root cause.** `gateway.poll_once` inferred a restart only when HEALTH `uptime_s` was lower than the previous poll's.
An old process polled young (0.014 s) followed by a new process polled older (up to ~2 s) is not "lower", so the old
process's high seq stayed the freshness baseline: STALE_DATA until the new seq overtook it.

**Change.** `runner/classify.py` `HealthSample` + `restart_between(prev, cur)`: different processes iff the uptime
decreased, or it advanced less than the observer's monotonic clock *certainly* advanced between the two device-side
samples (start of the later exchange minus end of the earlier one) by more than 1 ms rounding + 2 ms slack + 1000 ppm
of the elapsed time. Same-process samples cannot trigger it within that rate bound, so seq reuse inside one process
stays STALE_DATA. The gateway keeps the last HEALTH sample with its exchange bounds, resets the seq baseline on a
detected restart and records `last_restart.rule` and the evidence (advance, elapsed bounds, shortfall, tolerance).
`read_series`'s bracketing HEALTHs use the same function. FT-F12 (catalog description updated, same case id) now
also restarts the young new process right after the gateway first saw it and asserts: detected, never `stale`,
healthy <= 2 P after its first PASS HEALTH, device healthy <= 10 s; it records the uptime rise.

**Tests.** `tests/unit/test_gateway.py`: rule cases (same process incl. rounding and a 400 ppm drift over an hour,
decrease, early restart with uptime rise and its exact shortfall, the documented blind spot); the audit's loopback
scenario with a REQ-08-shaped bound (`lr.mono - t_pass <= 2P`, rule `uptime_advanced_less_than_elapsed`, uptime after >
before, no `stale`); mutant M2 (seq-reuse) still goes `stale` with `restarts_detected == 0`. Existing restart, repeat-seq
and skew tests unchanged and passing.

**Pre-fix (H).** The audit's `gateway-restart-anchored.py`: `stale`, `seq_not_increasing:2<=1001`,
`restarts_detected 0`, 4.305 s after the first PASS HEALTH (`remediation-repro-pre-host-*`).

**Post-fix.** H: the same script, unchanged: `healthy`, `restarts_detected 1`, fresh seq 2 at 4.307 s. At production
timing (P = 2 s, `scripts/remediation/gateway_early_restart.py 5`): 5/5 trials, old uptime 0.009-0.037 s, new
1.785-1.827 s, rule `uptime_advanced_less_than_elapsed`, recovery 1779.8-1822.4 ms from the first PASS HEALTH, never
stale (`remediation-verify-post-host-*`). **VM** (FT-F12, measurements in `results/witness.db`):

| run | code | uptime rise (s) | rule | gateway recovery after 2nd restart (ms, bound 4000) | API observed (ms) | device healthy (ms, bound 10000) |
|---|---|---|---|---|---|---|
| 133 | c335c84 | -0.653 | uptime_decreased | 937.6 | 1042.0 | 17.0 |
| 134 | c335c84 | -0.164 | uptime_decreased | 1209.0 | 1263.3 | 6.0 |
| 135 | c335c84 | -0.031 | uptime_decreased | 1258.7 | 1282.6 | 2.5 |
| **136** | c335c84 | **+0.959** | uptime_advanced_less_than_elapsed | 927.5 | 966.7 | 10.6 |
| **137** | c335c84 | **+0.019** | uptime_advanced_less_than_elapsed | 1265.9 | 1271.8 | 3.7 |
| 138 | c335c84 | -0.155 | uptime_decreased | 992.1 | 1063.8 | 12.0 |
| 146 | 0943fd5 | -0.808 | uptime_decreased | 9.3 | 109.4 | 54.6 |
| **147** | 0943fd5 | **+0.409** | uptime_advanced_less_than_elapsed | 1241.3 | 1279.4 | 8.9 |
| **148** | 0943fd5 | **+0.758** | uptime_advanced_less_than_elapsed | 1171.2 | 1178.9 | 5.9 |
| **149** | 0943fd5 | **+0.690** | uptime_advanced_less_than_elapsed | 985.8 | 1061.7 | 9.6 |

Bold rows are real-VM early restarts the pre-remediation rule could not see. Run 136: the gateway last saw the young
process at uptime 0.078 s and seq 1; the new process's first gateway READ was seq 1 again, so the old code would have
reported a false STALE_DATA; the new rule found a 1.078 s shortfall against a 5.04 ms tolerance. All 10 FT-F12 runs
passed every predicate, including the first restart's existing REQ-08 bounds.

**Limitations.** Timing alone cannot identify a successor that started within (both HEALTH exchanges' durations +
tolerance) of the old process's start; protocol v1 has no incarnation id (`systemctl restart` on witness-field took 84.9-561.1 ms in the 27
FT-F12 runs recorded so far, exchanges ~1 ms). A clock-rate error beyond 1000 ppm (e.g. a chrony slew of a large offset, excluded by the preflight
clock gate) could make one poll report a false restart; its only effect is a baseline reset for that poll. Whether a
given FT-F12 run produces a rising uptime depends on where the restart lands in the 2 s poll schedule (5 of 10 runs).

### F-03 (P2): the 30 s per-case deadline did not include the retry

**Root cause.** `read_series` started its own clock (`t0`) per attempt, the retry got a fresh one, the check ran only
between exchanges, and no blocking step was clamped. A deadline overrun was also recorded as a failed predicate
(`within_case_deadline`), i.e. `fail/device`, not the documented `error/runner`.

**Change.** `runner/cases.py` `case_deadline()` (contextvar) yields one absolute `time.monotonic()` deadline; an
enclosing case's deadline always wins. `with_retry` owns it for attempt 1, the clamped 250 ms pause and the retry;
a standalone attempt opens its own. `runner/client.py` `Connection(case_deadline=…)` clamps resolve, connect, send and
read to the time left and marks `Observation.deadline_hit = "case"` when the case bound (not the stage's own timeout)
ended or prevented a step; `classify` returns no category for it (`case_deadline_exhausted:…`, partial bytes kept),
the attempt is `cut_by_deadline`, and `decide` returns `error/runner`. The gateway never passes a case deadline.

**Tests.** `tests/unit/test_case_deadline.py` (scaled loopback): the audit's shape with a 4 s deadline (attempt 1
PASS_SLOW kept, attempt 2 cut with partial exchanges, total <= 4.08 s, `error/runner`); a hung listener with 0.4 s left
(read clamped below the 2 s timeout); no time left (nothing sent, no retry); an unaffected fitting case; nested deadlines.

**Pre-fix (H).** The audit's `case-deadline.py`: 31.592 s, `fail/device` (`remediation-repro-pre-host-*`).

**Post-fix.** H: the same script, unchanged: 30.007 s, attempts 15753.7 + 13999.5 ms, categories PASS_SLOW / None,
`error/runner` "case deadline 30s exhausted … exchange 11/12". `scripts/remediation/case_deadline_30s.py` (full 30 s):
PASS. **VM** (`remediation-verify-f03-vm-netem-*`, `scripts/remediation/vm_case_deadline_netem.py`): `witness-faultctl
apply netem 1300 data` on witness-field (flower-scoped to device-source port 5020, post-handshake, dead-man armed),
production `with_retry(read_series(dev-a.lab, 10, bracketed))`: attempt 1 PASS_SLOW, 12 exchanges, 15758.6 ms, replies
1304-1317 ms; attempt 2 cut at exchange 11 by the case deadline; total **30.006 s**, `error/runner`; revert verified
(SYN-RECV drained), quick checks GREEN before and after. Capture text: `remediation-verify-f03-vm-netem-capture.txt`.

**Limitations.** The deadline bounds the probes of a case, not the fixture work around them (precheck over SSH,
capture start/stop, journals, gateway API sampling in GW/F12 cases); those have their own bounds and the 75 s
harness backstop. A slow device whose retry cannot finish inside 30 s is reported `error/runner` as documented; the
device's PASS_SLOW stays visible as the first-attempt category and attempt row.

### F-04 (P2): retrying an invalid attempt moved the blame to the device

**Root cause.** `decide` looked only at the final attempt for "unclassifiable" or "restart observed"; any first
attempt that was not ok followed by a PASS became a device FLAKE. Q5 compared categories only, so a PASS-category
predicate failure (degraded HEALTH) that recovered was invisible.

**Change.** `Attempt.outcome(expected)` = ok | device | runner (unclassifiable or cut by the deadline) | infra (restart
observed). `decide` returns `error/<attribution>` if any attempt is runner/infra, whatever the other saw; only fair
attempts yield pass, fail or FLAKE (FLAKE details now name a failed first-attempt predicate). Schema v4 (`runner/db.py`
migration 4) adds `attempts.outcome` and `attempts.predicates`, written for every attempt. `Q5_RETRY` selects attempt 1
outcome not ok and attempt 2 ok (category fallback only for rows before v4, labelled in `basis`); Q5b shows both
outcomes; A10 is "a retried result is never pass"; A16 flags any pass/device result over a runner/infra attempt
(legacy rows: unclassifiable or "restart observed").

**Tests.** `tests/unit/test_retry_attribution.py`: runner->PASS = `error/runner`, restart window->PASS = `error/infra`,
degraded HEALTH->healthy = FLAKE `fail/device`, device failure->PASS = FLAKE, device->runner/infra second attempt =
error, red preflight still infra, outcomes, persisted outcomes driving Q5 (the degraded case appears, a twice-failing
case does not), A16 on a v4 row and a legacy row.

**Pre-fix (H).** The audit's `adversarial.py`: both repros became `fail/device` FLAKE.
**Post-fix (H).** The same script: `error/runner` and `error/infra` after the retry, with the attempt history.
**VM/DB.** Mutant M6 run 144: C-IDENTIFY READ_TIMEOUT then PASS -> outcomes device, ok -> `fail/device` FLAKE, listed by
Q5 with basis "attempt outcome"; all other retried results in runs 139-144 are device/device. No historical result
(runs 1-130, 98 retries) had the misattribution: all were genuine mutant-device failures (A16 holds on history).

**Limitation.** Runner/infra-then-PASS and restart-window retries cannot be produced on the healthy VMs without
breaking the harness on purpose; they are verified by unit tests on the production decision code.

### F-05 (P2): the device accepted requests the contract forbids

**Root cause.** `Device.parse_request` called `json.loads` without a duplicate-key hook and never checked for `\r`;
`RecursionError` from deep nesting was not caught (the handler thread logged a traceback and closed without a reply).

**Change.** The device applies protocol section 2 rule 4 to requests exactly as the runner does to responses: `\r`
anywhere (incl. a CRLF terminator), UTF-8 BOM, invalid UTF-8, NaN/Infinity, duplicate keys, trailing data, non-object
-> `{"id": null, "error": "bad_json"}`; the connection stays open. Valid JSON of the wrong shape keeps
`bad_request`/`unknown_cmd` with the echoed id.

**Tests.** `tests/unit/test_device.py`: 13 forbidden frames -> bad_json (pure and via `handle_line`), parity with
`runner.classify.parse_frame` (every one is a FrameError there), valid variants still accepted (spaces, tab, key order,
max id), deep nesting -> bounded error reply on Python 3.12 and 3.14, and an on-socket sequence that keeps serving.

**Pre-fix (VM)** (`remediation-repro-pre-f05-vm-protocol-*`, `scripts/remediation/vm_protocol_probe.py` from ctl to both
devices): 10 of 30 stimuli violated the contract: duplicate id (answered as id 2), duplicate cmd, raw CR, CRLF,
duplicate-same-value on both devices. **Post-fix (VM)** (`remediation-verify-f05-vm-protocol-*`, same script, deployed
`7e255ed`): 30/30 replies match, exit 0; lab0 captures retained (`…-capture.txt`).

**Limitation.** None known for the contract cases listed; the device still trusts the 4096-byte framing bound (as before).

### F-06 (P2): the acceptance gate could be green over missing data and failing baselines

**Root cause.** A13 counted eight key *families* in any form; A14 counted distinct restore identifiers; A15 only looked
for variation; A4 accepted any historical pass.

**Change** (`runner/analysis.py`). A4: every requirement has fair non-mutant evidence and the latest such result of every
case instance mapped to it passes. A13: every REQ-10 key (both VMs' kernel/distro/qdisc/nft, python, git_sha, git_dirty
in {0,1}, chrony.offset in its recorded form, runs.clean_env equal to the run row, fw_version for every inventoried
device) present and non-empty; "unavailable (<category>…)" firmware accepted only in mutant runs. A14: only fresh-clone
baselines that are complete, all-pass, retry-free and commission every device count; violations name the reasons; the
counted runs' source revisions are reported. New A16 (retry attribution), A17 (every expected flow present in each
capture, and the latest fair result of every case that dialled a device has a flow record), A18 (the latest complete
fair baseline commissions every device). A v3 database is audited read-only with v4-only records treated as absent.

**Tests.** `tests/unit/test_acceptance.py`: a synthetic complete store passes all 18; both audit counterexamples
fail (A13 lists exactly the eight keys; A14 counts 0); blank, invalid, mismatched and withheld environment values;
partial, retried, red-postflight and unclean fresh trials; A4 latest-failure; A18 firmware mismatch; A17 missing and
empty flows; read-only audit of a v3 copy (file bytes unchanged).

**Pre-fix (DB).** The audit's counterexamples on a copy of the store: A13 true, all 15 true (`remediation-repro-pre-host-*`).
**Post-fix (DB).** `scripts/remediation/acceptance_counterexamples.py` on scratch copies of the pre-remediation store and
of the final store: counterexample 1 -> A13 violated (and A14/A18); counterexample 2 -> A14 violated
(`remediation-verify-post-host-*`, `remediation-verify-db-acceptance-*`); source DB hashes unchanged. On the real final
store all 18 assertions hold (`acceptance-audit.md`). Before the new runs, the historical store failed only A17
(no flow records yet).

**Provenance.** The A14 fresh-clone trials (99-103, 105) ran `87d322b`, before this remediation; the report states it.
The remediated code was verified on the long-lived VMs (runs 131-150, `git_dirty=0`, revisions in `runs.git_sha`).
Five new golden-restore trials on the remediated code were **not** run (see section 6).

### F-07 (P2): the F3 captures excluded the port under test

**Root cause.** Both capture paths used a fixed BPF `tcp port 5020 or icmp`; F3 dials 5021.

**Change.** `Fault.capture_ports` (F3: 5021); `runner/lab.capture_filter` builds `(tcp port <inventory ports> or tcp port
<fault ports>) or icmp` for the ctl capture; `witness-faultctl capture start NAME [PORT…]` accepts at most 4 validated
extra ports and always adds the inventory ports (nothing else is captured). After every case `capture_flows` (schema v4)
records each dialled flow (`dialled_flows`: address, port and, for established connections, the runner's ephemeral port)
per capture, whether packets were expected (not for an unresolved name, a local ENETUNREACH or a step the deadline never
started) and how many the capture holds. The fault report shows the counts; A17 gates them.

**Tests.** `tests/unit/test_capture.py`: filters, validation (incl. injection attempts), flow classification for F3/F4/F5/
F7-missing/F7-swap, the field agent's port validation, and counting packets of a synthetic pcap with tcpdump.

**Pre-fix.** Run 119 ctl/field captures: 0 packets on 5021 (`remediation-repro-pre-host-*`); all 34 historical F3
captures (runs <= 130) the same, now annotated in `results/evidence/F07-historical-capture-annotations.md` (files and
evidence rows unchanged). **Post-fix (VM).** Runs 133 and 146: ctl and field captures each hold 4 packets of
`10.77.2.11:5021`: two SYN -> RST pairs (the runner's probe and the `gateway --once` cross-check), e.g.
`10.77.1.10.34964 > 10.77.2.11.5021: Flags [S]` / `10.77.2.11.5021 > 10.77.1.10.34964: Flags [R.]` in both
`run-146/FT-F3-WRONG-PORT__dev-a/capture{,-field}.txt`. Across runs 131-150: 268 flow records, 260 expected, 260 present.
F5 (local ENETUNREACH) and F7-missing (no address) are recorded as not expected.

**Limitation.** A connect that failed has no local port, so its flow is identified by address:port and can include the
gateway's polls to the same endpoint (not for 5021, which only the runner and the cross-check dial).

### F-08 (P3): fault-variant count

**Change.** `runner/catalog.counts()`; README and the fault report quote 13 fault types, 21 fault variants, 24 live
fault-test instances (and 11 commissioning instances); the report cross-checks the `faults` table. The Phase 4 ledger
line in `docs/implementation-state.md` carries a dated correction instead of being rewritten.
**Test.** `test_catalog_counts_are_consistent_with_readme_and_report`.

## 3. Defects found during the remediation (kept, fixed, annotated)

1. **Capture-flow filter matched gateway polls** (run 131 commissioning flows counted every 5020 packet to the device):
   flows keyed on the runner's ephemeral port when known (`c335c84`).
2. **FT-F12 evidence overwrite** (runs 133-138, 24 evidence rows): the extended case applies F12 twice and the injector
   named evidence by fault id, so the second restart's `fault-apply/snapshot/snapshot-ctl/fault-revert` files replaced
   the first's after both were indexed. Found by re-hashing all evidence after fetch. Results, measurements and
   fault_events are complete; the four first-restart files per run are lost. Fixed in `0943fd5` (evidence and marks
   numbered per application, `Lab.save` never overwrites); the report now re-hashes every indexed file (12,778 checked
   on witness-ctl: exactly these 24 differ); annotation `results/evidence/F12-overwritten-evidence-annotations.md`.
   Runs 146-150 (final code) have no mismatch.
3. **Run 132 infra**: the field SSH control channel timed out at session start and end while the host was swapping
   (13.7 of 15.0 GiB swap used; other desktop apps incl. an iOS Simulator). The field journal shows the guest stalled
   (10 s login setup, four chrony clock steps, "time jumped backwards": `remediation-run132-field-journal.log`). The
   preflight was RED, all 24 cases `error/infra`, nothing probed, no fault applied, run marked contaminated; kept.
4. **Logging slips in my own wrappers** (zsh does not word-split unquoted variables): two logs printed `rc=` of a
   `$(date)` substitution, one script and one VM step did not run. Each log carries a dated NOTE; the steps were rerun
   and logged separately. No lab state was involved.

## 4. Regression run on the final code and lab state

| Check | Command / evidence | Result |
|---|---|---|
| Unit, macOS (Py 3.14.7) | `.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit tests/test_inventory.py` | **PASS 279** (185 before) |
| Unit, witness-ctl (Py 3.12.3) | `scripts/lab_vms.sh unit` on `0943fd5` | **PASS 279** |
| ShellCheck 0.9.0 + `bash -n` | in witness-ctl, all scripts (`remediation-deploy-checks-*`) | **PASS** rc 0 |
| Deploy | `scripts/lab_vms.sh provision` (devices and gateway restarted on changed code; no online window) | PASS, `git_dirty=0` |
| Baseline | runs 131 (`d125939`), 145 (`4969e30`), 150 (`0943fd5`) | **PASS 11/11** each, clean, uncontaminated |
| Fault suite F1-F13 + gateway | run 133 (`c335c84`), run 146 (`0943fd5`); run 132 infra (above) | **PASS 24/24** each |
| FT-F12 incl. early restart | runs 134-138, 147-149 | **PASS** 8/8 (+133, 146) |
| Mutants M1-M6 | `WIT_RUN_TAG=remediation scripts/lab_vms.sh mutant run Mx 1`, runs 139-144 (`3a9bbbc`) | **6/6 caught**, stock restored, GREEN after each; campaign total 36/36 valid runs detected |
| Protocol rejection (F-05) | `vm_protocol_probe.py` both devices | **30/30** |
| Partial-run commissioning (F-01) | separate DB on witness-ctl | **none commissioned**, PARTIAL 2/11 |
| 30 s deadline (F-03) | loopback 30 s + lab-traffic netem | **30.007 s / 30.006 s, error/runner** |
| Acceptance | `scripts/lab_vms.sh report` | **18/18 hold** on the real store |
| Corrupted acceptance data | `acceptance_counterexamples.py` on scratch copies | both **fail acceptance** as required |
| DB integrity | `PRAGMA integrity_check` / `foreign_key_check` | ok / empty; schema v4; 150 runs |
| Evidence integrity | report re-hash on witness-ctl | 12,778 rows, 24 known-annotated mismatches (section 3) |
| Final lab state | `remediation-final-clean-state-*` | preflight GREEN both; no fault, mutant, dead-man, capture, netem or `witness_fault*` table; route present; builds stock; no 10.77 route on the Mac; goldens and `vigil` Stopped |

Remediation VM artifacts outside `results/` (partial-run test DB, F-03/F-05 captures) are preserved outside Git in
`~/Desktop/Witness/remediation-evidence-20261018/` (`SHA256SUMS`; tar sha256 `0e960bb4…d235`).

## 5. Environment notes

- Host memory pressure: swap 13.7 of 15.0 GiB used during the session (8 GiB Mac; other applications, not the lab).
  macOS swap lives in the same APFS container, so free disk fell from 8.3 GiB to 1.8 GiB while the lab's own files grew
  by a few MiB. I stopped adding VM runs at that point. Re-check `df -h /` and `sysctl vm.swapusage` before more work.
- Remediation runs 131-150 are fair except run 132. Every run used `git_dirty=0` code from the commits above.

## 6. Remaining limitations and items not reverified (none of the eight findings is left OPEN)

- **Fresh-environment baselines were not repeated on the remediated code.** A14 still rests on the historical
  golden-restore trials 99-103/105 (`87d322b`). The remediation changed runner decisions, the device's request
  parser, the gateway's restart inference and capture/evidence bookkeeping; it was verified on the long-lived VMs.
  Repeating five golden restores needs disk headroom this host did not have at the end (1.8 GiB free).
- Mutants ran on `3a9bbbc`; the final `0943fd5` differs only in fault-evidence file naming and the report re-hash
  (no change on any path a mutant run executes besides `Lab.save`'s overwrite guard).
- Interrupt (TERM/KILL) and reset self-tests were not rerun; fixture teardown logic is unchanged apart from evidence
  naming and the capture-flow bookkeeping, which runs inside a `try` before the postflight.
- F-02 residual blind spot and F-07 connect-stage flow identification, as stated in those sections.
- The per-case deadline covers a case's probes, not fixture work (F-03 limitation).
- Not independently re-audited. Hash equality and green assertions are machine checks over recorded evidence, not
  certification; the next independent reviewer should re-run the commands in section 7.

## 7. Reproducing the verification

```sh
# host (no lab state touched)
.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit tests/test_inventory.py
.venv/bin/python ~/Desktop/Witness/independent-audit-evidence-20261017/gateway-restart-anchored.py   # audit script, unchanged
.venv/bin/python ~/Desktop/Witness/independent-audit-evidence-20261017/case-deadline.py              # audit script, unchanged
.venv/bin/python scripts/remediation/case_deadline_30s.py
.venv/bin/python scripts/remediation/gateway_early_restart.py 5
.venv/bin/python scripts/remediation/acceptance_counterexamples.py results/witness.db /tmp/witness-ce
# lab (after scripts/lab_vms.sh preflight is GREEN)
scripts/remediation/ctl.sh sudo python3 scripts/remediation/vm_protocol_probe.py /tmp/witness-protocol
scripts/remediation/ctl.sh sudo env PYTHONDONTWRITEBYTECODE=1 timeout 90 python3 -m pytest tests/live --live \
  -p no:cacheprovider -m commissioning -k test_health --db /tmp/partial.db --evidence-root /tmp/partial-ev
scripts/remediation/ctl.sh sudo python3 scripts/remediation/vm_case_deadline_netem.py /tmp/f03-netem
caffeinate -i scripts/lab_vms.sh suite baseline && caffeinate -i scripts/lab_vms.sh suite fault
scripts/lab_vms.sh report && scripts/lab_vms.sh fetch && scripts/lab_vms.sh preflight
```
