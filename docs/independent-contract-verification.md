# Witness — independent evidence-contract verification

Reviewed 2026-10-20 UTC against **4b1f658099f4592c052471ca0c3ae2f9916c2332**, including repairs `b9c334f` and `7fca791`.

**A. Evidence-contract repair: NOT VERIFIED.** The original unfinished-run, disabled-plan, FV-01 and FV-02 counterexamples are corrected. Two additional, reproduced false positives remain: a run can corroborate its own purported abort, and deleting a required case-decision predicate can remove its obligation. Both reproduce with all schema-v5 guards enabled. Passing the supplied verifier does not close this defect class.

**B. Full Witness project acceptance: FAILED.** The confirmed acceptance defects prevent sign-off; experimental coverage is also incomplete. This does not mean the retained live baseline or expected-fault suite failed. Their recorded **11/11 and 24/24** results withstand the evidence checks below.

This was read-only verification of production and original evidence. No implementation change, deployment, VM fault injection, restore, commit, push or publication occurred. All altered databases are disposable synthetic counterexamples or in-memory copies, never claimed as live observations. Witness remains software simulation with real VM network traffic, not hardware or firmware validation.

Evidence directory **E**: [results/independent-contract-20261020](../results/independent-contract-20261020/). Command logs retain UTC start/end, argv, timeout result, exit status and output. Scripts, SQL mutations, assertion failures and regenerated reports are retained there.

## 1. Review scope and source of obligations

Read the immutable brief, AGENTS.md, acceptance contract, repair record, previous independent final verification, implementation ledger, production verifier/writers/report, live fixtures, schema migrations, reference builder, oracle, matrix and verifier self-tests. Inspected actual Git history. The checkout was initially clean. `4b1f658` changes the A18 claim text from “executed” to “selected”; its executable acceptance behavior matches `7fca791`. The initial specification commit is `38e51d5`, before the implementation commits.

| Obligation | Actual authority and enforcement | Independent result |
|---|---|---|
| Required devices and commissioning instances | `inventory.yaml`; `catalog.COMMISSIONING_REQUIRED`; inventory VALUES in `db.py`, not surviving device rows | Deleting dev-b does not shrink 11 required instances or omit dev-b from the report |
| Required cases, operations and attempt limits | Catalog plus `contract.CaseContract`, SERIES/F12 grammar and target rules | Missing attempts/exchanges, shortened series, endpoint changes and reordered exchanges reject in the supplied matrix; original FV-01 rejects independently |
| Declared execution selection | Collected pytest instances → `db.record_plan` → run_plan rows and indexed session/plan.json, before case execution | Missing/disabled/contradictory plans reject; actual live plans contain 11 and 24 instances and precede the first recorded results |
| Executed-instance receipts | Case directories and run directories under the supplied evidence root | Missing parent records and orphaned directories reject; a planned missing result cannot silently become an older result |
| Schema-era obligations | schema_migrations checked against features, plan files/rows, capture records and attempt outcomes | Removing/moving v5 migration records together with disabling the plan still rejects |
| Capture sides and packet data | Case contract requires ctl capture and, for fault cases, field capture; validated exchanges determine flows; inventory determines gateway poll targets | Missing capture indexes/sides, forged counts, empty rehashed packet files and absent flows reject; independent recounts agree on original live data |
| Run exclusion from current evidence | Fairness predicate plus `_contamination_cause` corroboration | **Unsound: IC-01** |
| Case-decision predicate completeness | `results.predicates` JSON, checked by `_decision`; attempt predicates separately derived from exchanges | **Unsound: IC-02. Required case-level keys are not independently specified** |

The schema-v5 append-only triggers are useful protection against accidental mutation, but they are not the proof. The two findings below require only allowed UPDATEs of runs/results, with no trigger removal, foreign-key disabling, file rewrite or hash rewrite.

## 2. Confirmed defects

### IC-01 — P1: a run can certify its own abort and hide its current failure

Location: [runner/contract.py](../runner/contract.py), `_contamination_cause`, **lines 835–839**, and the unfair-run skip at **784–785**. Selection uses `FAIR` and `LATEST_RUN` in [runner/analysis.py](../runner/analysis.py), **lines 47 and 249–253**. The actual writer, `db.mark_aborted_runs`, **lines 394–403**, explicitly excludes the detecting run itself.

Minimal reproduction on the deterministic `current-failure` reference store, with its real synthetic evidence tree supplied:

```sql
UPDATE runs
SET contaminated = 1,
    notes = notes || ' | aborted: never finished (detected by run '
                  || run_id || ')'
WHERE run_id = 14;
```

Before: the latest baseline, run 14, has a genuine fixture HEALTH failure on both attempts. Acceptance is **22/24**, with A4 and A18 violated; A18 selects run 14. After this single statement: **24/24 HOLDS**; A18 selects older green run **5**. All failure results, exchanges, plans, finished_at, postflight checks and evidence bytes remain unchanged. `integrity_check=ok`, foreign-key violations empty, **19/19 triggers retained**.

The function accepts any referenced run whose start lies within the alleged aborted run's interval. Referencing the run itself satisfies that comparison by construction. It is not a subsequent session and cannot have detected its own earlier unfinished run. The report and current-evidence selection then exclude the failing baseline. A separate deadline-cut fault-run fixture becomes **24/24** through the same edit, falling back to the older fault run.

Affected invariants: **I1.2**, **I10.1**, and the A4/A18/A23 selection guarantee. This is not the declared boundary of fabricating an independent failed check or consistently replacing an entire evidence tree: the verifier accepts a circular witness within the same run row. The failure is removal of acceptance obligations by changing status metadata.

Reproduce: `E/challenge.py` (`self-abort`, `self-abort-on-fault`) and `E/confirm.py`. Evidence: [confirm.log](../results/independent-contract-20261020/confirm.log), [confirm.json](../results/independent-contract-20261020/confirm.json), and `self-abort-commissioning.md`/`self-abort-traceability.md` in E.

### IC-02 — P2: deleting case-decision keys makes a failing decision acceptable

Location: [runner/contract.py](../runner/contract.py), `_decision`, **lines 362–383**. It accepts any boolean-valued dictionary, including `{}`, checks only surviving values and final-attempt keys, and has no independent required set for case-level predicates. Gateway-observed cases have no runner attempt to supply missing keys. The live C-GATEWAY test records **15** predicates at [tests/live/test_gateway_cases.py](../tests/live/test_gateway_cases.py), **lines 91–110**, including API behavior not represented by a timing bound.

Minimal missing-evidence reproduction on an in-memory copy of the retained v5 live store:

```sql
UPDATE results SET predicates = '{}'
WHERE run_id = 1 AND case_id = 'C-GATEWAY' AND device_id = 'dev-b';
```

All 15 decision predicates disappear. Acceptance remains **21/24**, failing only the store's expected A12/A14/A15 history checks. **A18 and A24 still hold; both devices remain commissioned**, with original files and 19 triggers intact.

To establish a false positive over an actual failure rather than only missing metadata, the independent fixture records an API failure (`api_unknown_device_404=false`) with observed protocol category PASS and valid measurements. The live test explicitly makes this a failing verdict. From that failing control:

```sql
UPDATE results
SET verdict = 'pass', attribution = 'none',
    predicates = json_remove(predicates, '$.api_unknown_device_404')
WHERE run_id = 14 AND case_id = 'C-GATEWAY' AND device_id = 'dev-b';
```

The complete reference store changes from **22/24** (A4/A18 reject) to **24/24**, commissioning both devices. Repeated with all 15 authentic predicate names on a copy of the live store: the deliberately introduced API-failure control is **19/24**, commissioning only dev-a; removing that false key and changing the verdict returns **21/24**, commissioning dev-b as well. This is a synthetic negative fixture, not a claim that the live gateway returned a wrong HTTP status.

Affected invariants: **Rule 0**, **I4.5**, **I10.5**. A missing key must not mean the case never required that check. This does not depend on forging packet data or reconstructing every corroborating record; a single result-row update erases part of the v5 decision basis. Measurement-bound checks cannot catch a non-timing predicate.

Evidence: [challenge.json](../results/independent-contract-20261020/challenge.json) (`gateway-failure-control`, `gateway-predicate-erasure`), [confirm.json](../results/independent-contract-20261020/confirm.json), and `live-copy-predicate-erasure-report.md` in E. Both `challenge.py` and `confirm.py` are standalone reproductions.

**Related verifier-test gap:** [tests/contract/oracle.py](../tests/contract/oracle.py), **lines 27–28**, omits `results.predicates` from its results projection. Independently erasing only that JSON produces **zero oracle deviations and ACCEPT**. The oracle includes attempt predicates, which is insufficient for gateway cases. The reference builder also substitutes fixture-specific case predicates for the live key set. This explains a coverage hole; it is not a third production finding.

## 3. Latest corrections and additional challenges

The exact original `finished_at=NULL` attack now violates A23 because session postflight remains recorded, even though A18 selects older evidence. The original attacks deleting all plans or dropping run_plan, moving/deleting migration 5, and deleting a failing result and its directory while leaving the indexed plan file intact now violate A22/A23. These fixes are effective against their original inputs.

The original FV-01 missing-exchange/missing-field-flow and missing-exchange/999-count attacks were rerun on the retained **7fca791 v5 store**, through a copy of the previous auditor script whose output directory is E. They now add A17/A24 and, for the forged counts, A20. Four real F3 TCP5021 packets exist on each side. Gateway/session evidence-index removal also rejects. FV-02 retains all 11 required instances, explicitly names dev-b's gaps, and rejects overall acceptance.

The independent challenge retained **23 store outcomes plus one oracle projection check**, separately from the supplied matrix. These include valid and failing controls, new partial/unfinished controls, the two original plan attacks, missing parents, a missing planned result, a reparented plan index, invalid plan device scope, an empty rehashed field pcap with downgraded counts, text packet counts and the new findings. Exact SQL and complete violation lists are in `challenge.json`.

Scope discipline: changing finished_at and also deleting both classes of postflight records accepts an unfinished-looking store; raw files remain. This is retained as a boundary probe, not a separate finding, because it rewrites status together with its corroborating records. Accepted planned_at/user_version-only edits did not establish disappearance of an acceptance obligation and are not reported as additional defects. No claim of resistance to coordinated wholesale reconstruction or authentic source-stamp forgery is made.

## 4. Supplied verifier, oracle and actual executions

The matrix has **202 entries: 198 negative mutations and four benign edits**, plus seven control variants. It covers record omissions, orphaned children, duplicate result orders, device/reference loss, plan/migration removal, flags, attempt/operation cardinality, source ports, capture-side requirements, counts, byte corruption, measurements and the original review findings. Random combinations use reproducible seeds **0–59**, on both the valid and current-failure stores: 120 combinations.

The oracle shares no production verifier functions, but it is a projection/file-hash comparison with a constructed fixture and declared variant verdict. It does not independently interpret arbitrary evidence stores or prove that the fixture implements every live obligation. Its omitted decision field above was independently demonstrated. The eight weakening tests detect their chosen removed checks; they do not prove completeness of checks that were never implemented. In particular, the decision/bounds weakening is detected by the declared timing-bound failure, while the missing non-timing predicate escapes.

| Executed command, using `.venv/bin/python` from repository root | Result / evidence |
|---|---|
| `scripts/verify_acceptance_contract.py --json E/verifier-complete.json --workdir E/verifier-work` | **PASS, exit 0; 329/329 OK; 8/8 weakenings detected**, elapsed 627.13 s; `verifier-complete.log/.json` |
| `-m pytest -q -p no:cacheprovider tests/unit tests/test_inventory.py --basetemp=E/pytest-final` | **391 passed**, 131.40 s; `unit-complete.log` |
| `-m pytest -q -p no:cacheprovider tests/contract/test_acceptance_contract.py -k 'standalone or ambiguous or report or review8 or review9' --basetemp=E/report-test-tmp` | **5 passed, 289 deselected**; `report-tests.log` |
| `E/challenge.py` and `E/confirm.py` | New counterexamples and valid controls above; no original evidence written |
| `E/original-fresh-omissions.py` | Original auditor's v5-store omissions rejected; `original-fresh-omissions.log` |
| `E/stores.py latest-v5 …` and `E/stores.py master …` | Read-only DB, indexed-file, independent exchange-derived flow and tcpdump checks; corresponding `*-raw-store.log` |
| `E/final_facts.py` | Manifest, source hashes, gateway packets, plans/provenance and report consistency; `final-facts-complete.log` |

The first verifier attempt hit its **240 s outer timeout**; the first unit attempt hit **120 s**. Neither is counted as a pass. The subsequent bounded runs completed. When asked about background verifier PIDs 39144/39145, I inspected the existing log, JSON and recorded exit status and collected the finished tool session: **completed successfully, not timed out**. It was not rerun. The first report-comparison helper stopped on the documented A18 wording change; its corrected comparison verified that the timestamp and that claim wording were the only differences. These audit-helper outcomes remain in E.

## 5. Retained live evidence and reporting semantics

The latest retained VM store is `results/acceptance-integrity-20261019/vm/store/witness.db`, SHA-256 **1a21321380c2c4d28b93680973120073eb410ed59d47cabbe778210896f32f67**. It is schema v5, with run 1 baseline and run 2 fault suite stamped `7fca79161f4bb9ea834d2192525889fb4756165d`, dirty=0, clean and uncontaminated. These are inspected prior VM executions, not suites newly run by this audit.

- **396/396 indexed files** match size/hash; **397/397 manifest entries**, including the DB, match.
- Plans contain **11/24 instances**, agree between rows and files, and precede the first results; **35/35 decisions** have recorded predicates. `live-plans.json` retains exact times.
- Independently derived **58 flow records**, **54 expected on wire**, agree with stored requirements; all **56 address-bearing counts** agree with tcpdump. Both F3 captures hold the expected TCP5021 traffic. All **10 independently checked gateway address/capture combinations** contain packets.
- Independently decoded **48 baseline responses**, including **40 READs**: echoed IDs, device identity, healthy payloads, sequence progression and timestamp checks hold. **25/25** recorded fault removals are verified.
- Seven environment-recorded source hashes per run match the current device, gateway, fault controller, unit files, mutants and inventory files. No new claim of inspecting currently installed guest files is made.
- Acceptance is **21/24**, with only **A12/A14/A15** violated. Regenerated commissioning report agrees with the retained report except generation time and the documented `4b1f658` A18 claim wording. Baseline run 1 is COMPLETE 11/11 and commissions both devices.

**A two-run store can legitimately pass its baseline and fault tests while failing project-history assertions.** A12 needs mutants; A14/A15 need restored-environment trials. Missing those campaigns is not a defect in the two executed suites and was not counted as one.

**PARTIAL 6/11 commissioning dev-a only is consistent with the brief.** Commissioning proves each inventoried device's identity/health/fresh data, with shared run-level prerequisites. The independent valid partial baseline selected dev-a's five cases plus C-ENVIRONMENT; the report says PARTIAL 6/11, dev-a yes, dev-b no. A new failing partial baseline still violates A4; it cannot silently replace its failed instance with an older pass even though A18 evaluates the latest fully selected baseline.

The handoff's omitted-device artifact was generated by `report.commissioning_section(c)` **without an evidence root**. Its own prose conditions byte/plan-file verification on supplying that root. Its PARTIAL/dev-a result therefore is not a certificate of the contradictory retained v5 plan file. The full root-aware audit correctly rejects that altered dataset through A18/A21/A23. The valid partial-control result above was also verified **with** its evidence root.

The historical master remains schema **v4** and returns **24/24** under the current verifier's legacy rules. Independently checked **12,778 indexed files**, finding exactly the **24 already disclosed F12 mismatches**; all **264** stored address-bearing counts agree with tcpdump. Historical run 131's broad flow keying remains disclosed, not newly certified. The master hash is unchanged: **f5f789ebc223d553416f9fc2fdc68693688250bd34f80ea855a113f70474d6dc**.

Those historical passes do **not** gain v5 guarantees: pre-v5 completeness uses directory receipts, pre-v4 attempts may use category rather than outcome, and pre-v5 case predicates rest on verdicts. Historical restored trials remain `87d322b`; mutant runs 139–144 remain `3a9bbbc`. The contract states these limits and the report calls machine assertions necessary rather than sufficient for acceptance. They cannot establish current-revision repeatability, mutant detection or a v5 decision record that was never recorded.

## 6. Mandatory work versus defects; stop decision

IC-01 and IC-02 are confirmed code defects. The following are separately **unexecuted acceptance work**, not inferred runtime failures:

| Required evidence | Why it remains mandatory before full acceptance |
|---|---|
| Five clean restored-environment baselines on the final revision | Brief §§7.3/13 explicitly require five; historical trials predate relevant runner/evidence changes |
| Current-revision mutant campaign and catch-rate report | Brief §§7.4/13 require demonstrating the suite can fail; old pre-v5 mutants do not exercise the repaired decision/evidence path |
| Interruption, dead-man, mature capture-expiry and reset recovery | Brief §§6.3/7.1/14 require reliable fault removal and isolation; ordinary 25/25 teardown does not exercise interruption during the changed session/evidence path |
| Gateway/F12 whole-case deadline verification and scope resolution | Brief §6.2 requires an overall per-case bound. The earlier shared-probe fix and ordinary fast cases do not establish aggregate gateway/fixture bounds; no new overrun is alleged here |
| Fresh-VM reproduction of the final revision | Explicit brief §13 checklist item, separate from restoring existing goldens |

Resource measurements: initially **6.3 GiB free**, swap **8211.75/9216 MiB**, pressure **2**; at 04:24 UTC **4.4 GiB free**, swap **10643.12/11264 MiB**, pressure **2**. The documented 10 GiB restore threshold was not met. No VM was created/restored or interacted with by this audit; no new preflight or cleanliness certificate is claimed. The retained 01:37:57–58Z preflight is GREEN on both dedicated guests. Local bounded verification and offline capture reads introduce no lab fault state. Generated fixture stores were removed; retained logs and scripts reproduce the findings.

Final preservation check: original master and v5-store hashes unchanged, HEAD unchanged, and the only modified tracked file is the required append to `docs/implementation-state.md`; the report and E are new. `final-preservation.log` records removal of this audit's fixture stores, including the first timed-out verifier's identified temporary directory. Closing host sample: **4.6 GiB free**, swap **10398.06/11264 MiB**, pressure **2**. Production and previous audit reports remain untouched.

The engineering decision is bounded: **do not sign off the repair yet**. Reject the self-referential abort and missing-required-predicate counterexamples while preserving the valid partial/unfinished and legacy controls; then perform the listed acceptance experiments when resources permit. This audit stops after the confirmed violations and requested evidence checks. It does not authorize an implementation cycle or expand the scope into a speculative general audit.
