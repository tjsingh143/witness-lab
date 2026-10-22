# Witness — independent post-remediation re-audit

**Verdict: FAIL.** Reviewed on 2026-10-18. The original commissioning, restart, retry-deadline, attribution, parser, capture-filter and counting counterexamples are corrected. The acceptance checker still returns **18/18 HOLDS for independently constructed invalid evidence**, including conflicting results and a missing required capture-flow record. These are reproducible correctness defects in the acceptance mechanism, not failures inferred from historical infrastructure incidents.

Independent execution passed **279 unit tests on macOS, 279 on Ubuntu, the 11-instance VM baseline, and all 24 VM fault instances**. These successes are substantial, but do not override the acceptance defects. Five fresh-environment baselines on the repaired implementation and post-repair fault-interruption/reset recovery remain outstanding. Even without the confirmed defects, those gaps would prevent PASS.

## 1. Authority, revisions and preservation

The immutable authority is [PROJECT_BRIEF.md](../PROJECT_BRIEF.md). I read it, the repository instructions, [original failed audit](independent-audit.md), [remediation record](independent-audit-remediation.md), implementation ledger, protocol/requirements/lab documentation, relevant production code and test fixtures. I examined the changes from failed-audit code `633df97` to HEAD, including the intermediate capture and evidence-naming corrections. No implementation repair was made during this audit.

| Item | Independently established value |
|---|---|
| Reviewed Git HEAD and documentation revision | `9f695e1a5f38a4df91ce1d18a92c8e3d20cd7c26` |
| Both deployed guest source revisions | `0943fd5a3d6b31ec019fc55e09bdea3331cd9ed8`, source metadata `git_dirty=0` |
| Deployment timestamps | ctl `2026-10-18T01:13:45Z`; field `01:13:47Z` |
| Relevant history | failed implementation `633df97`; original audit `3c8de6c`; main repair `7e255ed`; capture correction `c335c84`; overwrite correction `0943fd5`; final documentation `9f695e1` |
| Historical repaired mutant runs 139–144 | `3a9bbbccf35f7cf1889ccbad4158806a98417414` |
| Historical fresh baselines 99–103, 105 | `87d322b82d9936bc40d8eca49079169710d54457` |

Deployed-file hashes were compared with the checkout and the deployed Git object, rather than trusting `.witness-source` alone. All 44 inspected ctl files and 41 field files matched either HEAD or the two comment-only differences in `runner/classify.py` and `scripts/remediation/gateway_early_restart.py` at `0943fd5`; installed device/gateway code was included. Thus the VM results exercise the reviewed runtime behavior, although their literal source stamp is `0943fd5`. No synchronization or deployment occurred.

The initial tracked working tree was clean. The audit created its own evidence directory, this report and a ledger update. It did not alter the original audit, remediation document, brief, historical DB or captures. Preserved SHA-256 values:

```text
PROJECT_BRIEF.md
07a33a088939c9cc59ef4dbbfb12706ad17431d9eb4d8b5353feafdcea555baf
docs/independent-audit.md
db8aa70e4399807d3cc84179ce51b1cb7ef05589d9337610357ab9a368384f3c
docs/independent-audit-remediation.md
a8581ff0509372c7a916a6ba77357e0cf47e1d5c648fd36e17e7d1f01dd6c255
results/witness.db (also /var/lib/witness/results/witness.db on ctl)
f5f789ebc223d553416f9fc2fdc68693688250bd34f80ea855a113f70474d6dc
```

Evidence root **E** below means [results/independent-reaudit-20261018](../results/independent-reaudit-20261018/). Each named execution log contains UTC start/end, exact argv, output, elapsed time and exit code. `core-diff.patch`, `evidence-diff.patch`, `deployed-inspection.log`, `final-lab-state.log` and `preservation-final.log` retain provenance. The audit VM DB is `E/vm/witness-reaudit-20261018.db`; its evidence root is the sibling `witness-reaudit-20261018-evidence/`. It is distinct from the master store.

## 2. Safety gate and execution boundaries

Before live testing, I checked disk/memory/swap, Lima status, guest identities, source hashes, isolation, recovery access, preflight, faults, modes/builds, timers/captures and both guest filesystems. Only the two dedicated private-Lima guests were operated: ctl lab0 `52:55:55:77:01:10`, `10.77.1.10`; field lab0 `52:55:55:77:01:20`, `10.77.1.20`, with dummy field0 device addresses `.2.11/.2.12`. Both had no default route, the scoped isolation rules, forwarding disabled and active vsock recovery access. Initial guest free space was about 6.4 GiB each.

| Host observation, UTC | Available disk (`df -h /`) | Swap used / allocated | Pressure level |
|---|---:|---:|---:|
| Initial gate | 6.2 GiB | 12709.88 / 13312 MiB | 2 |
| 07:12 resumed gate | 9.2 GiB | 10829.19 / 11264 MiB | 2 |
| 07:21 before interruption | 8.0 GiB | 11606.69 / 12288 MiB | 2 |
| 07:24 after control stall | 7.0 GiB | 12114.38 / 13312 MiB | 2 |
| 14:23 closing resource measurement | 12 GiB | 7508.38 / 8192 MiB | 2 |

These are separate measurements, not a claim of stable capacity. Logs: `resources-initial.log`, `resources-resumed.log`, `resources-before-interruption.log`, `resources-after-stall.log`, `resources-final.log`. The host has 8 GiB RAM. No golden restore, new VM, large capture or unrelated-file deletion occurred. The later 12 GiB observation did not establish sustained headroom plus a restore safety margin, and memory pressure persisted. The capture artifacts fetched for this audit fit in a 3,450,880-byte tar, SHA-256 `e85fb511ddb5ec6beaa04f2704bd86b84804c58475253775242a6352531c27bd`.

At 07:23, an interruption experiment's **initial** ctl-to-field SSH preflight timed out before it created a runner or applied a fault. I stopped further fault/mutant experiments. Recovery-channel preflight subsequently passed. This is an observed infrastructure limitation, not evidence that fault cleanup failed. `orphan-capture-ready-vm.log` retains the failure; `postflight-after-stall.log` and `preflight-final.log` retain successful later checks.

## 3. Finding-by-finding disposition

“FIXED” in this table means the original defect and specified counterexample are corrected within the stated evidence. It is not a universal guarantee for every untested timing or infrastructure condition.

| Finding | Status | Independent result |
|---|---|---|
| F-01 P1 partial baseline commissions | **FIXED** | Live HEALTH-only audit run 2 passes 2 tests but commissions no device and reports PARTIAL 2/11. Missing-case, aborted, contaminated, failed-environment and duplicate-result fixtures reject the affected devices. |
| F-02 P2 early restart inference | **FIXED** | Original production-class reproduction now recovers; additional measured early and rapid restart checks recover within 2P. Live F12 includes a rising-uptime early restart and passes. Timing ambiguity remains explicitly bounded by the observations below. |
| F-03 P2 deadline reset on retry | **FIXED** for original defect | Unchanged original 31.637-second loopback counterexample completes in 30.003 seconds with error/runner. Retry shares the original deadline. A universal 30-second cap across fixture/GW/F12 work is **not established**. |
| F-04 P2 retry attribution | **FIXED** | Independent runner→PASS, infra→PASS, degraded→healthy and device-failure→PASS fixtures give correct distinct outcomes and Q5/Q6 behavior. |
| F-05 P2 forbidden request frames | **FIXED** | Production parser checks and 20 bounded live probes across both devices reject forbidden frames while retaining valid handling. |
| F-06 P2 false-green acceptance | **NOT FIXED completely** | Both exact original fixtures now fail acceptance. Additional valid-schema fixtures still produce 18/18 over invalid environment values and conflicting duplicate results. See R-01. |
| F-07 P2 missing TCP 5021 capture | **FIXED** | Independent F3 pcaps on both guests contain the actual 5021 SYN/RST pairs. New A17 completeness checking has a separate confirmed defect, R-02. |
| F-08 P3 fault count | **FIXED** | Catalog and SQL agree: 13 types, 21 variants, 24 live fault instances; current public prose distinguishes them. Historical incorrect counts remain identified as corrections. |

### F-01 — completeness, per-device and run-level gates

`runner/db.py` derives required instances from `catalog.COMMISSIONING_REQUIRED`. The new query demands exactly one passing result per mandatory device case and run-level case, green pre/postflight, finished clean uncontaminated baseline, correct recorded firmware and stock build. It does not infer completeness from the selected pytest cases.

Independently executed run 1 is COMPLETE 11/11 and commissions both devices; run 2 is HEALTH-only, PARTIAL 2/11 and commissions neither. The generated report displays the partial latest run separately from the earlier complete run. Independent fixtures remove identity, environment, READ-clock, READ-series or gateway cases; mark the run unfinished/contaminated; fail environment; or make its postflight red. Each rejects commissioning as appropriate. A conflicting duplicate HEALTH result blocks dev-a while allowing fully qualified dev-b. A conflicting run-level environment result blocks both. Raw environment-value validation is a different weakness, reported under F-06/R-01; commissioning trusts the recorded passing C-ENVIRONMENT result.

Evidence: `partial-vm.log`, `db-counterexamples-rerun.log`, `acceptance-edges.log`, `independent-reports/commissioning-report.md`. Some missing-case fixtures deliberately remove parent result rows in an in-memory backup with foreign-key enforcement off; those test query shapes, not valid database ingestion. The additional acceptance fixtures in `acceptance-edges.py` have foreign keys enabled and empty `foreign_key_check`; the HEALTH-only counterexample was independently run on the VMs.

### F-02 — restart inference and stale-data discrimination

The repair compares uptime advance with monotonic observation intervals, including uncertainty/tolerance, instead of accepting only decreasing uptime as a restart. The unchanged original `gateway-restart-anchored.py` now shows healthy with one detected restart at its 4.304-second observation. That late observation alone does **not** prove the 4-second bound, so I added `gateway-probe.py` using production DeviceServer/Gateway classes at P=2 seconds.

Single early replacement: previously observed uptime 0.029 s, next uptime 1.952 s, observed healthy recovery **1.947690 s from first PASS HEALTH**. Three rapid replacements before the next poll: healthy recovery **1.916294 s**, uptime rises 0.013→1.916 s. These establish recovery to the current process; one poll cannot count all three unseen intermediate incarnations. Production M2 sequence reuse yielded PASS×5 then STALE_DATA×3, with zero false restarts. F13 repeat-seq yielded PASS then STALE_DATA×7, also zero false restarts.

Independent live F12 audit run 3 measured ordinary gateway recovery 742.648 ms, API observation 833.752 ms; early recovery 1273.239 ms, API observation 1346.046 ms, all from the specified first-PASS-HEALTH reference. Early uptime increased by 0.496 s, exercising the original failing direction. Device HEALTH after restart return was 8.003 ms (626.825 ms from command send); the second restart's HEALTH was 3.767 ms after return. These are distinct reference events, not interchangeable restart durations.

Ambiguous synthetic observations representing a 2 ms restart within timing tolerance are intentionally not inferred as a restart. There is no protocol incarnation identifier; a universal restart guarantee in indistinguishable observations is unsupported. Same-process and clear-early-restart controls behaved correctly. Evidence: `original-gateway.log`, `gateway-edgecases.log`, `independent-vm-integrity.log`, retained gateway JSON/measurements.

### F-03 — shared probe deadline, with a scope limit

The unchanged original `case-deadline.py` now runs the slow 12-exchange/retry shape in **30.003028 s**: attempts 15699.893 and 14047.567 ms, first category PASS_SLOW, final unclassifiable deadline exhaustion, verdict **error/runner**. Approximately 3 ms of scheduling overhead is not a renewed budget. The second attempt stops during exchange 11/12. This is independently executed Mac loopback evidence, not a new VM netem reproduction.

Source inspection confirms one `ContextVar` monotonic deadline in `with_retry`, nested attempts retaining the earlier deadline, a clamped retry pause, and propagation to resolver wait, connect, send and read. Partial observations remain recorded; deadline exhaustion is not blamed on the device. The unit suite also tests shorter residual blocking-operation bounds.

**Scope limitation:** fixtures, capture/journal collection and SSH calls have their own bounds. GW/F12 cases also contain direct `Connection`/`single` calls and gateway sampling without the shared case context (`tests/live/test_gateway_cases.py`). The remediation explicitly discloses this and a separate harness backstop. The original retry-reset bug is fixed, but the user's stronger complete-case 30-second guarantee cannot be inferred from it. I did not reproduce a current whole-GW/F12 overrun and do not present that possible overrun as a measured defect. See `original-deadline.log` and the reviewed deadline/call sites.

### F-04 — outcomes, predicates and SQL

Independent production `Attempt`, `decide`, persistence and query checks (`retry-probe.py/.log`) yielded:

| First attempt → final attempt | Final verdict/attribution | Q5 / Q6 |
|---|---|---|
| Unclassifiable runner error → PASS | error / runner | Q5 retains runner→ok; Q6 correctly does not call it infrastructure |
| Restart-invalid window → PASS | error / infra | Q5 retains infra→ok; Q6 includes the infrastructure-affected run |
| PASS category with failed HEALTH predicate → healthy | fail / device, FLAKE | Q5 finds it despite equal PASS categories; no Q6 infra row |
| Genuine READ_TIMEOUT → PASS | fail / device, FLAKE | Q5 retains device→ok; no Q6 infra row |

First/final categories remain observations, separate from predicate/outcome/verdict. Stored v4 outcomes drive Q5; pre-v4 fallback is labelled and cannot recover predicate detail that was never stored. Historical repaired M6 run 144 independently inspected raw data also supports READ_TIMEOUT→PASS as a device flake. Runner/infra-to-PASS scenarios were fixtures, not artificially damaged live infrastructure.

### F-05 — parser symmetry and live bytes

Independent parser checks reject duplicate keys, raw CR/CRLF, invalid UTF-8 and BOM. Live checks on each device additionally test oversize, valid maximum ID, permissible whitespace and an exactly 4096-byte valid frame: **10 probes per device, 20/20 expected responses**. Bad JSON returns the bounded error response and allows a following valid HEALTH on the same connection; oversize closes as specified. Request and response hex are retained, including the boundary bytes. Oversize enforcement belongs to the production socket handler, not `parse_request` alone. No acceptance is inferred merely from a parser unit result. Evidence: `parser-pure.log`, `protocol-vm.log`, `protocol-probe.py`; the 279-test suites also cover production parser symmetry.

### F-07/F-08 — actual captures and actual counts

Capture setup includes inventory ports plus the fault's extra endpoint port. In audit run 3, the F3 ctl capture contains two SYN/RST pairs to/from `10.77.2.11:5021`; the field capture contains the same four packets. `tcpdump -nn -r` independently recounted the stored filters: **60 flow records, 56 marked expected, all 56 present; 58 address-bearing records recounted, zero count discrepancies**. Two address-less rows have no filter to recount. Four non-expected records include legitimate no-wire conditions; the test does not require packets for failed resolution/local route rejection. Other faults retain captures and passing evidence checks.

Historical repaired F3 runs 133 and 146 likewise contain four 5021 packets in each guest capture. Historical 268 flow rows were checked, 264 recounted, all stored counts matched; 260 expected flows were present. Connect-stage failures lack a retained local port and are checked at address/port granularity, so such counts are weaker attribution than established connections keyed by ephemeral port. Crucially F3's 5021 endpoint differs from normal gateway polling at 5020.

Catalog and database counts independently return **13 distinct catalog IDs / 21 variants / 24 fault test instances**. Gateway cases reuse F1/F5/F8; 24 is not a variant count. README/current generated reports are consistent. Original audit/history were preserved rather than rewritten to erase the former 20-variant claim. Evidence: `independent-vm-integrity.log`, `historical-integrity.log`, current catalog, SQL and generated reports.

## 4. Confirmed remaining/new findings

The following are evidence-validity counterexamples in disposable in-memory backups, not allegations that the retained real runs contained the fabricated values. This is the same adversarial acceptance-checking method used in the original audit. The source database was opened read-only; its hash is unchanged.

### R-01 — P2: acceptance still admits invalid mandatory evidence and conflicting complete runs (F-06 incomplete)

Affected code: `runner/analysis.py:228`–240 (A13), `:225`–226 (LATEST_FAIR), `:344`–349 (latest complete baseline), `:392` onward (A18). Exact reproductions are in `E/acceptance-edges.py` and `db-counterexamples.py`.

Minimal environment reproduction, against a disposable copy of the retained store:

```sql
UPDATE environment SET value=char(9)||char(10)
WHERE run_id=150 AND key='python';
```

`analysis.audit(copy)` returns **18/18 HOLDS**, both devices still commissioned. The production live environment predicate for this exact value, `bool(value.strip())`, is false. SQL `trim(value)` only strips ordinary spaces here. Similarly `chrony.offset='offset_s=garbage'` and a `git_sha` contradicting the run's revision are accepted. A13 claims valid mandatory values, but verifies only selected surface properties.

The duplicate reproduction copies the run-150 C-ENVIRONMENT result twice, omitting its primary key: first with `verdict='fail', attribution='runner'`, then with `verdict='pass', attribution='none'`. The original passing row also remains. The schema allows all three run-level rows; foreign keys remain valid. **All 18 assertions hold.** Commissioning correctly rejects run 150, but A4 takes only the maximum result ID and A18 silently falls back to run 145 because exact-one coverage excludes the newer duplicated run. Thus the acceptance gate hides the very inconsistency that the commissioning query detects.

Both exact original F-06 reproductions are now rejected: missing required fields gives 15/18; uniformly failing fresh HEALTH results gives 17/18 (A14 rejects them). That is progress, but it does not close the broader false-green acceptance defect. The current report's warning that assertions are necessary rather than sufficient is appropriate; it does not make these individual false-positive claims correct.

### R-02 — P2: A17 accepts a missing required guest capture-flow check

Affected code: `runner/analysis.py:298`–309. Minimal disposable-copy reproduction:

```sql
DELETE FROM capture_flows
WHERE capture='field' AND result_id IN (
  SELECT result_id FROM results
  WHERE run_id=146 AND case_id='FT-F3-WRONG-PORT'
);
```

Result: **18/18 HOLDS**, empty `foreign_key_check`. Only the ctl 5021 flow record remains. A17 checks that some flow record exists for the result; it does not derive and require every capture × actual dialled flow. Deleting all records correctly fails, but deleting one required guest does not. Changing the same F3 flow records to `expected=0, packets=0` also passes: expectedness is trusted rather than independently established by the assertion.

The actual new F3 packets are present and F-07's filter defect is fixed. R-02 concerns whether future missing/partial evidence would be detected. It does not claim that current capture counts are invented. Minimal reproducer/output: `acceptance-edges.py/.log`, `db-counterexamples-rerun.log`.

## 5. What the 18 assertions actually establish

I examined their queries, not just their aggregate result. The real historical master gives 18/18; the separate audit-only store gives **15/18**, correctly lacking mutant and fresh-clone evidence (A12/A14/A15). That is an honest incomplete evidence set, not a failed live baseline.

| Assertions | Scope and limitation |
|---|---|
| A1/A2 | Catalog traceability, not execution quality. |
| A3 | Some fair result per case; not complete per-device or current-revision coverage. |
| A4 | Latest stored fair non-mutant result per case/device; duplicate conflicts can be hidden (R-01), and evidence may span revisions/runs. |
| A5/A6 | Historical existential coverage of 13 types and 11 categories; not every current variant on the reviewed revision. |
| A7/A8/A11 | Useful consistency checks but substantially repeat schema constraints; they are not independent empirical validations. |
| A9 | Verified removal recorded for recorded applications in finished runs; does not prove immediate SIGKILL cleanup or identify every unrecorded orphan. |
| A10/A16 | Retried results and invalid-attempt attribution; independently exercised with production decisions and SQL. |
| A12 | At least one valid nonempty run per mutant; not necessarily complete coverage or a detected mutant. Raw mutant outcomes require separate inspection. |
| A13 | Required-key coverage improved; value/provenance holes remain (R-01). |
| A14/A15 | Complete successful fresh trials and stable categories/verdicts; revisions are reported, not constrained to reviewed code. Stable uniformly failing runs can satisfy A15 alone but A14 now rejects them. |
| A17 | Checks present row counts and existence of some record; incomplete per-capture coverage can pass (R-02). |
| A18 | Commissioning for the newest exact-one complete fair baseline; can skip a newer conflicting duplicated run (R-01). |

Contaminated runs are deliberately excluded. Marking run 150 contaminated makes it commission nobody and selects older fair evidence; that is not itself a defect. Historical infra run 132 was correctly retained as contaminated/error-infra and is not a reason for this FAIL verdict.

## 6. Regression and evidence integrity

The unit suites were independently rerun, including assertions for deadlines, retry decisions, parser symmetry, gateway freshness and new schema/report behavior. I also used independent fixtures and unchanged original reproductions to avoid relying solely on remediation-written tests.

| Executed check | Result and retained command log in E |
|---|---|
| macOS units | `python -m pytest -q -p no:cacheprovider tests/unit tests/test_inventory.py`: **279 passed, 32.09 s**, `unit-mac-unsandboxed.log` |
| Ubuntu ctl units | Same suite on guest: **279 passed, 28.13 s**, `unit-ubuntu.log` |
| Full current VM baseline | `tests/live --live -m commissioning --db /tmp/witness-reaudit-20261018.db --evidence-root /tmp/witness-reaudit-20261018-evidence`: **11/11, 37.53 s**, `baseline-vm.log`, run 1 |
| HEALTH-only VM baseline | Same isolated store, `-k test_health`: **2/2, 12.78 s**, no commissioning, `partial-vm.log`, run 2 |
| Full current VM faults | Same store, `-m fault`: **24/24, 159.03 s**, `faults-vm.log`, run 3 |
| Production-class original/independent edge probes | Deadline, restart, retry and parser results above; logs named in §3 |
| Independent raw baseline check | 48 saved responses parsed without production classifier; IDs/identity/firmware, HEALTH payloads, 40 READ timestamps and all four 10-READ sequence series checked, `raw-observations-rerun.log` |
| Fault cleanup and run validity | 25/25 fault applications have verified removal (F12 applies twice); all case pre/postflight green; 578/182/1150 PASS checks in runs 1/2/3 |
| Audit database/evidence | SQLite integrity OK, FK check empty; **412/412 hashes and lengths match**, `independent-vm-integrity.log` |
| Historical database/evidence | Integrity OK/FKs empty; 12,778 indexed files checked, **exactly 24 disclosed mismatches**, `historical-integrity.log` |
| Actual old-schema compatibility | Read-only analysis of original v3 DB works and reports absent flow evidence; twice migrating an in-memory backup to v4 preserves every pre-existing row/column and FK validity, `compatibility-probe.log` |
| Report integrity warnings | Independently inserted missing-file and wrong-hash fixtures both flagged; regenerated historical report flags all 24 known mismatches; independent VM report flags zero |

Schema migration preserved 130 runs, 1,315 results, 1,125 attempts, 3,904 exchanges, 11,265 evidence rows and all other old tables. Separately, all **11,265 pre-remediation evidence reference rows are exactly equal** to the original auditor's v3 snapshot. Historical bytes remain distinguishable from new audit evidence by separate roots/DBs and source revisions.

The disclosed overwrite incident is real: four first-F12-application files in each of runs 133–138 were replaced, giving 24 mismatched indexed records. The old indexed hashes were not rewritten to disguise that loss. `results/evidence/F12-overwritten-evidence-annotations.md` and the remediation document retain disclosure; regenerated reports flag the loss. Those 24 original files are **not intact evidence**. The remaining results/measurements and second-restart observations support a narrower historical assessment. Current `Lab.save` avoids existing names and repeated injection uses numbered names; current audit F12 has no mismatches. I did not certify concurrent writers or every raw capture-path collision scenario.

The historical six repaired mutant runs 139–144 were inspected individually, including raw response hex, first/final attempt data, environmental withholding and control-device results. They support 6/6 detections: M1 wrong serial, M2 reused sequence, M3 incomplete newline framing, M4 wrong echoed ID, M5 string temperature and M6 delayed/no-response timeout. Independent byte predicates corroborate these in `mutant-byte-check-independent-seq.log`, including an actual 5→1 sequence decrease within each affected attempt. No dev-b failure was found in those six runs; run-level environment failures for withheld dev-a firmware remain legitimate mutant evidence. The historical full campaign query reports 36 valid detected runs. **I did not execute a new six-mutant VM campaign**; the repaired campaign is stamped `3a9bbbc`, with later relevant changes confined to evidence naming/report handling rather than device mutation logic. Current production M2 was independently exercised on loopback.

The claim of ten successful repaired F12 tests is supported as **historical** runs 133–138 and 146–149, with their recorded measurements; five had rising early uptime. The 24 overwritten files qualify the first six runs' evidence integrity. Runs 146–149 on `0943fd5` have no such loss. This audit adds one independently executed F12 containing two restarts, rather than claiming to have independently repeated all ten.

The remediation's broader claim of actual VM reproduction of seven original findings is not adopted as an independently repeated seven-finding campaign. I did not deploy the failed revision. This audit's current live, loopback, fixture and historical-evidence checks are explicitly distinguished above; the 30-second netem reproduction, for example, remains remediation evidence rather than a newly executed VM check here.

## 7. Mandatory requirements and remaining verification

| Requirement group | Current assessment |
|---|---|
| Dedicated Linux VM topology, isolation, device/gateway services, inventory and recovery access | Independently verified in preflight, deployed source inspection and closing state. Software simulation over real VM TCP, not physical hardware/embedded firmware. |
| REQ-01/02 identity and wrong-identity exclusion | Current full baseline and F7 pass; historical M1 supports mutation detection; F-01 completeness fixed. |
| REQ-03 healthy device | Current raw payloads and baseline pass; degraded retry fixture retains failure. |
| REQ-04/05 timestamps and sequence | Current 40 READs independently inspected; F13-skew/repeat pass; M2 discrimination and invalid restart-window attribution tested. |
| REQ-06/07 malformed/timeout/slow classifications | Current full fault suite and parser probes pass; shared retry-probe budget fixed, broader case-budget scope remains limited (§3). |
| REQ-08 restart recovery | Current live ordinary/early F12 and independent production-class examples meet measured bounds; ambiguous incarnation observations remain a known limitation. |
| REQ-09 gateway unreachable detection and unaffected device | All current GW-F1/F5/F8 cases pass, including timing and control-device predicates. |
| REQ-10 environment | Current audit runs have recorded environment and green checks. Acceptance of deliberately invalid evidence remains defective (R-01). |
| Full F1–F13 fault suite and packet evidence | Independently executed 24/24, actual packet recounts; A17 completeness defect remains (R-02). |
| SQLite traceability, Q1–Q6 and generated reports | Reproduced and inspected; retry Q5/Q6 and migration independently checked; acceptance is not reliable enough for final signoff. |
| Six deliberately broken devices detected | Supported by inspected repaired historical campaign; no new complete VM campaign. |
| Five fresh-environment baselines on repaired implementation | **NOT EXECUTED / OUTSTANDING.** Historical `87d322b` trials do not prove repeatability of changes to parser, gateway, runner, schema and evidence handling. |
| Fresh-VM/from-scratch reproduction of repaired revision | **NOT EXECUTED.** Historical earlier-code reproduction remains valid for its scope, not promoted to current-code proof. |
| Post-repair interruption/reset/dead-man/capture expiry | **INCOMPLETE**, as detailed below. |

Five new distinct fresh/restored trials on the repaired revision are required for unqualified final acceptance. One successful baseline on the long-lived guests is insufficient. They must use isolated audit storage, authenticated dedicated VM identities, protected recovery originals, a verified restore procedure, and enough **stable** disk/memory headroom. Never start duplicate-MAC goldens alongside the originals. No restore operation was attempted during this audit.

For interruption recovery, I inspected the one-shot SIGTERM teardown, 90-second guest dead-man timers, field capture lifetime and ctl `timeout` wrapper, reset paths and preflight capture checks. I executed one bounded SIGKILL probe during capture startup. The runner was killed; the observed capture processes were already gone on subsequent checks, and preflight was green. This startup-race outcome **does not prove** expiration of a mature orphan capture or dead-man cleanup after an applied fault. The isolated orphan DB retains an unfinished run with zero results, which is correctly ineligible as commissioning evidence.

A second attempt to wait for established capture readiness stopped at its initial field-control preflight timeout. It applied no fault. The later planned SIGTERM/F2, SIGKILL/F5, dead-man expiry, mature capture expiry and reset self-test were **NOT EXECUTED**. Prepared `interrupt-probe.py` and `mutant-probe.py` are not test results. Ordinary 25/25 fault removal is independently supported; immediate cleanup after SIGTERM and bounded recovery after SIGKILL are different properties and remain separately outstanding. Field preflight has an explicit active-capture gate; the proposed ctl-orphan counterexample was inconclusive and is **not** reported as a confirmed defect.

Audit-harness failures are also retained: the initial sandboxed Mac suite could not bind sockets and passed after authorization; an audit helper originally named `inspect.py` shadowed the standard library and was renamed before a successful rerun; the first raw-mutant inspector incorrectly disallowed legitimate run-level environment failures and was corrected. These are audit harness issues, not product findings. Failed logs remain alongside successful reruns; no skipped procedure is represented as passed.

## 8. Closing state and readiness

Closing guest inspection at **14:41:40Z**, then full preflight at **14:42:13–14Z**, found both Witness VMs Running and GREEN, stock device builds, normal modes, gateway healthy, expected routes/hosts, correct isolation, no active fault, no tcpdump/pytest process, no Witness timer and no field capture. Guest free space: ctl **6535 MiB**, field **6479 MiB**. Vsock recovery remained active. All four private golden instances remained Stopped. Unrelated default-Lima **vigil remained Stopped and was never operated**. No Mac routes/firewall/service configuration was changed; the closing route inventory has no 10.77 lab route.

Last recorded host resources at 14:23Z were **12 GiB available, 7508.38 MiB swap used, pressure level 2**; these are timestamped observations, not a promise that resources remain stable. The original ctl/master DB hash still matches the preserved hash. The final Git state contains only this new report, the appended implementation-state entry and audit-only evidence; HEAD is unchanged. No code was repaired, no commit was made, and nothing was pushed or published.

**GitHub readiness:** suitable as a transparently labelled engineering portfolio/work in progress with this FAIL report and the historical records retained. It is not ready for an unconditional “complete” or “independently accepted” release claim. Publishing was not performed.

**Resume readiness:** an accurate claim can describe a two-VM Linux sensor simulation, Python/pytest/SQLite evidence, 13 fault types and 21 variants, independently reproduced 279 tests on each platform plus an 11-instance baseline and 24-instance fault suite, with historical detection of six deliberate mutants. Do not claim full acceptance, current five-clone repeatability, fully revalidated interruption recovery, production readiness or physical embedded-hardware testing.

Final acceptance requires resolving R-01/R-02, independently verifying their counterexamples and affected reports, clarifying/testing the complete-case deadline scope, and completing current-revision repeatability and interruption/reset checks under safe host conditions. No repairs were undertaken in this independent audit.
