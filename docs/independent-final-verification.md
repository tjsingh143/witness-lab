# Witness — independent verification of the second remediation

**Verdict: FAIL.** Reviewed 2026-10-19 UTC, against HEAD `a6d487f85643bd24a847b4ed743a45cd7e430a18` and the deployed `aa9e193` implementation. The exact R-01 and R-02 counterexamples are corrected. Environment validation and duplicate-result selection withstand the independent checks below. However, **acceptance still returns 21/21 over incomplete and contradictory capture evidence when the corresponding exchange rows are absent**. This material acceptance-integrity defect prevents passing the remediation recheck, independently of the outstanding full-project experiments.

Full-project acceptance is also **not granted**. Five current-revision golden-restore baselines, current fresh-VM reproduction, post-repair interruption/dead-man/capture-expiry/reset verification, and resolution of the gateway-case deadline scope remain outstanding. Resource limits are an additional constraint, not the reason for the confirmed FAIL. No implementation repair, deployment, commit, push, publication, VM restore, or new fault injection occurred.

## 1. Authority, revision and evidence boundaries

The authority remains [PROJECT_BRIEF.md](../PROJECT_BRIEF.md), read with [AGENTS.md](../AGENTS.md), both prior audits and both remediation records, the implementation ledger, protocol, requirements and inventory. Earlier verdicts and evidence were preserved. This is software simulation over real VM networking, not physical hardware or embedded firmware validation.

Evidence root **E** means [results/independent-final-20261019](../results/independent-final-20261019/). Its command logs record UTC start/end, exact argv, elapsed time, exit code and output. Independent SQL experiments use in-memory backups of read-only source databases. Their altered rows are **synthetic counterexamples**, never represented as real VM observations. `adversarial-results.json` retains all 21 assertion results for each of 60 independently constructed experiments.

| State | Independently established fact |
|---|---|
| Initial checkout | Clean; HEAD `a6d487f85643bd24a847b4ed743a45cd7e430a18` |
| Remediation history | `12f027e`: acceptance implementation/tests; `aa9e193`: verification evidence/reports/documentation; `a6d487f`: documentation, evidence, `.gitignore`, and `scripts/reaudit_remediation/fresh_store_counterexamples.py` |
| Guest source trees | Both `.witness-source` files: `aa9e193e4a1dbf255a3788f4515afed5aff91866`, dirty=0, synchronized `2026-10-19T03:28:06Z` |
| Deployed-file comparison | 69 ctl files and 66 field files checked, including source/tests/scripts, inventory and installed service libraries. All match `aa9e193` and HEAD except the installed gateway copy of `runner/classify.py`, described below |
| Installed gateway exception | Its SHA-256 `b3e6debb…6b252` equals `0943fd5`. Git diff shows only an updated timing range in a docstring; executable ASTs after removing docstrings are equal. This is an older byte revision with equivalent executable behavior, not a byte-identical current installation |
| Historical master | 150 runs; schema v4; latest baseline 150 and fault suite 146 are stamped `0943fd5`, not `aa9e193` |
| Latest remediation VM store | Separate baseline run 1 and fault run 2, both stamped `aa9e193`; stored under `results/reaudit-remediation-20261019/vm/` |
| Historical restored trials | Runs 99–103 and 105 remain stamped `87d322b`; they are not current-revision trials |
| Historical repaired mutants | Runs 139–144 remain stamped `3a9bbbc`; no new mutant campaign was performed |

Evidence: `provenance-complete.log`, `source-ctl.txt`, `source-field.txt`, `final-commit-files.txt`, `stored-evidence.log`. The initial provenance script assumed byte equality and stopped on the installed docstring difference; `deployed-provenance.log` preserves that failure. The corrected audit helper explicitly verifies the historical bytes and executable equivalence. Neither installation was changed.

## 2. Safety gate and actual execution scope

Only the two private-Lima Witness guests were inspected or used for tests. Identity/preflight verified ctl lab0 MAC `52:55:55:77:01:10`, address `10.77.1.10`, and field lab0 MAC `52:55:55:77:01:20`, address `10.77.1.20`, with device addresses `10.77.2.11/.12` on dummy `field0`. Both had no default route, isolation rules, forwarding disabled, stock devices, normal modes and active vsock recovery. Their initial available storage exceeded 6 GiB.

| UTC measurement | Host disk available | Swap used / allocated, MiB | Pressure |
|---|---:|---:|---:|
| 03:44:21, initial | 9.5 GiB | 8170.44 / 9216 | 2 |
| 18:48:00, after continuation | 6.6 GiB | 7966.69 / 9216 | 2 |
| 18:50:25, closing live work | 6.3 GiB | 8806.75 / 9216 | 2 |

These are separate measurements, not continuous monitoring. The documented restore threshold is at least 10 GiB free plus margin and stable memory. It was not met. No clone, golden restore, large capture, interruption fault, or full new live fault suite was attempted. The latest baseline/fault suite was independently inspected from its retained raw store and captures, as permitted by this task; **11/11 and 24/24 below are inspected remediation executions, not newly executed VM suites in this audit**.

The actual new VM work was the Ubuntu unit suite, read-only provenance/state inspection and preflight. macOS unit tests and loopback regressions are identified separately. The first sandboxed guest read was denied by Lima socket permissions (`guest-state-initial.log`); it was rerun with authorization (`guest-state-authorized.log`). This was a tool permission failure, not a lab preflight failure.

## 3. Second re-audit findings: disposition

| Finding / acceptance assertion | Disposition and evidence |
|---|---|
| R-01a: whitespace, malformed and contradictory environment evidence; A13 and commissioning | **Original defect corrected.** Unchanged auditor scripts now reject whitespace Python, malformed offset and revision mismatch. Independently removing each of all 15 specification/inventory-derived keys, or replacing it with tab/CR/newline/space, violates A13 and A18 and commissions neither device. Additional invalid versions, wrong clock server, run-metadata contradictions, normalized duplicate key and improper withholding also reject. See `original-acceptance-edges.log`, `original-db-counterexamples.log`, `independent-adversarial.log` |
| R-01b: contradictory duplicates hidden by last result ID or older complete run; A4/A18/A19 | **Original defect corrected.** Pass/pass, pass/fail and fail/pass duplicate insertions for C-HEALTH and C-ENVIRONMENT reject. `LATEST_FAIR` returns every row of the newest fair run of that instance, including both contradictory rows. A18 selects the duplicated complete run; it does not fall back to 145. A19 rejects cardinality regardless of order. Evidence includes selected SQL rows in `adversarial-results.json` |
| R-02: delete one required guest flow | **Exact reproduction corrected; broader class still open.** With exchanges intact, removing either ctl or field flow violates A17. Removing the exchanges as well bypasses A17 and A20; FV-01 below |
| R-02: change `expected=0, packets=0` | **Exact reproduction corrected.** Derived expectation violates A17; independent byte recount also violates A20 for the modified counts. Missing actual packets after a scratch pcap rewrite and re-hash violate A20. See the rerun 45-probe log |
| Missing inventory device discovered during remediation | **Whole acceptance gate corrected, standalone commissioning/report still incomplete.** A18 explicitly names absent dev-b and A21 rejects the changed reference table. The underlying commissioning coverage/report still shrinks to 6/6 and omits dev-b; FV-02 below |

Environment checks are shared by live C-ENVIRONMENT, `commissioning_gaps` and A13 through `runner/evidence.check_environment`. Required keys come from `ENV_REQUIRED` expanded over `inventory.yaml`, not the database's existing environment/device rows. Exact duplicate environment keys are constrained by the schema primary key; alternate whitespace/case spellings are rejected by the validator. Invalid BLOB, NaN/out-of-gate clock data, malformed kernel/qdisc/nft forms, contradictory builds/run kind and withheld stock-control firmware are exercised by the reproduced 45 probes and production unit tests. Legitimate withheld firmware on a mutant's mutant device remains distinguishable from successful commissioning.

Unfinished, unclean and contaminated runs commission nobody and are excluded as fair evidence. Falling back to an older fair complete baseline in those cases, or after a genuinely partial latest run, is intentional. A partial run can still commission a device whose own prerequisites and all run-level prerequisites are complete; it cannot commission a device with missing prerequisites. The unchanged auditor HEALTH-only and missing-case fixtures still reject the affected commissioning claims. A contradiction in a fair complete run cannot be hidden through that fallback.

## 4. Confirmed remaining defects

### FV-01 — P2: missing observations disable capture completeness and recounting

Affected code: `runner/analysis.py:474` (`flow_plan`), especially lines 495–497; `capture_flow_violations` at 518; `evidence_violations` at 547, especially its plan-driven loop at 571. This is a remaining acceptance-integrity defect, not a finding that the real retained capture files were fabricated.

Minimal reproduction on a disposable copy of the master, with its real evidence root supplied:

```sql
DELETE FROM exchanges
WHERE attempt_id IN (
  SELECT attempt_id FROM attempts WHERE result_id IN (
    SELECT result_id FROM results
    WHERE run_id=146 AND case_id='FT-F3-WRONG-PORT'
  )
);
DELETE FROM capture_flows
WHERE capture='field' AND result_id IN (
  SELECT result_id FROM results
  WHERE run_id=146 AND case_id='FT-F3-WRONG-PORT'
);
```

**Observed: 21/21 HOLDS; integrity_check `ok`; foreign_key_check empty.** A17's original missing-field-flow violation disappears solely because the exchanges are gone. The passing result and its declared attempt remain. The newest applicable result is still selected; this is not exclusion of an unfair or superseded run.

A second minimal variant deletes the same exchanges and sets both stored capture counts to **999**. All 21 assertions again hold, although independent `tcpdump` reads establish **four packets in each actual F3 capture**. Thus A20 is not recounting an existing current capture-flow record once the exchange join is empty. Positive counts evade A17's separate zero-count SQL check.

Both defects also reproduce on a disposable copy of the **latest `aa9e193` store**, F3 result 22: only the expected missing historical classes A12/A14/A15 fail. With exchanges intact, the missing field record adds A17; deleting exchanges removes that violation. This rules out an explanation based on pre-v4 history or the older master revision. See `fresh-omissions.log`.

Further independently executed counterexamples expose the same missing-data boundary:

| Fixture | Actual result |
|---|---|
| Remove F3 exchanges, attempts, flow rows and evidence-index rows, preserving its passing result | Master 21/21 |
| Remove all latest C-GATEWAY evidence-index rows | Master 21/21; both devices still commissioned |
| Remove latest baseline session evidence-index rows | Master 21/21 |
| Remove evidence-index rows for GW fault cases and C-GATEWAY in the latest VM store | No additional failure beyond A12/A14/A15 |
| Retain only the first READ of dev-a's latest C-READ-SERIES exchange record, preserving its other same-connection observations | Master 21/21; both devices still commissioned |
| Erase an established HEALTH connection's local port and broaden/recount its flow filter | Master 21/21 despite the pcap still containing the source port |

The READ and source-port fixtures establish additional limits of trusting the surviving observation subset; they do not claim a new live ten-READ failure or that a different connection actually supplied this HEALTH fixture's packets. The F3 missing-flow and 999-count counterexamples alone establish the material defect.

Root cause: the required plan is derived only from surviving `attempts JOIN exchanges` rows; no exchanges leads to `continue`. There is no gate tying `results.attempts` to child-attempt count, requiring the relevant direct-probe observations, or retaining capture obligations independently of those observations. Genuine gateway-observation cases intentionally have no direct exchanges and are also absent from that plan. A20 verifies **indexed** files but does not require a complete evidence index for those cases or sessions. Deleting an index row makes that file disappear from verification. A19 constrains result instances, not their observation/evidence children; A21 checks reference tables and cannot close this gap.

Required closure is verification of complete observation/capture obligations independently of the rows under examination, with correct exceptions for C-ENVIRONMENT and gateway-observation cases. The above negative fixtures must reject while legitimate no-wire F5/F7 records and old-schema limitations remain honestly represented. No repair was attempted.

### FV-02 — P3: standalone commissioning coverage still loses an inventoried device

Affected code: `runner/db.py:476` and `:523` construct required instances from the database `devices` table; `runner/report.py:99` uses those results without the inventory-completeness guard added inside A18.

On a foreign-key-valid copy of the latest VM store, remove dev-b's dependent results/evidence and its `devices` row, leaving the authoritative inventory unchanged. `commissioning_gaps(conn,1)` returns only `{'dev-a': None}`. The production commissioning section reports:

> Run **1**: **COMPLETE** commissioning run (6/6 required instances executed). Commissioned by it: **dev-a**.

There is no dev-b row or missing prerequisite in that table. Its proper 11-instance requirement has shrunk. **A18 and A21 do reject the overall dataset**, so this is a misleading standalone completeness/reporting result, not another 21/21 bypass. Dev-a's own completed prerequisites are not disputed. Evidence: `fresh-omissions.py/.log` and `omitted-device-commissioning.md`.

A related prose inconsistency remains: the commissioning rule says an AMBIGUOUS run “commissions nothing,” while the per-device implementation can legitimately commission the unaffected device. The independent duplicated dev-a fixture returns dev-b only, and the unit test explicitly expects that behavior. The narrative should describe the implemented per-device rule consistently.

## 5. The 21 acceptance assertions

Actual unmodified stores: master **21/21**; latest remediation two-run store **18/21**, failing only A12/A14/A15. The latter is the correct outcome for absent mutant/fresh-clone history. Supplying no evidence root, or a nonexistent one, correctly violates A20; this is not a regression.

| Assertion | Independent assessment of its actual scope |
|---|---|
| A1 requirement→case | Holds; reference completeness additionally depends on A21 |
| A2 case→requirement | Holds; mappings independently compared to catalog by A21 |
| A3 case executed | Some fair result per catalog case; not every device/current revision or complete raw observations |
| A4 latest evidence passes | Duplicate-order defect fixed; selects all rows of latest fair non-mutant run per instance. Still trusts verdicts and may combine runs/revisions |
| A5 predicted fault observed | Existential F1–F13 coverage; result prediction now tied to fault catalog. Does not require every variant on current revision |
| A6 categories observed | Historical existential coverage of all 11 categories; not proof of a complete current campaign |
| A7 no device blame on red preflight | Holds; also enforced by schema constraint |
| A8 no pass with blame | Holds; also enforced by schema constraint |
| A9 faults removed | Holds for recorded applications; missing decided fault application is rejected. Does not certify crash recovery of an unrecorded/orphan process |
| A10 retry never pass | Holds for recorded result attempt count; missing child attempts are not independently rejected |
| A11 mutant labels | Run kind/ID consistency; actual build provenance still needs supporting records/source inspection |
| A12 every mutant tested | Master holds; latest two-run store correctly fails. Requires a nonempty fair run without runner/infra results, not a complete or caught mutant by itself |
| A13 environment recorded | Original failures corrected; values/forms/metadata/key set checked by shared validator. Internal agreement is not independent proof that a self-consistently rewritten source stamp is authentic |
| A14 fresh baselines | Historical complete/all-pass/retry-free trials count; source revisions are disclosed, not restricted to HEAD. Does not establish current-revision repeatability |
| A15 stable fresh baselines | Compares verdict/category variation; A14 supplies the successful-completeness condition. Latest two-run store correctly lacks these trials |
| A16 retry attribution | Production decisions and Q5/Q6 independently rechecked; depends on retained attempts |
| A17 capture coverage | Exact R-02 deletions/expected=0 corrected when observations survive; **unsound for absent exchanges**, FV-01 |
| A18 complete commissioning | Conflicting complete run no longer skipped; invalid environment rejects; missing inventoried device explicitly rejected. Still trusts result/child evidence completeness |
| A19 cardinality | Correct for fair result instances and duplicate orders; does not enforce attempt/exchange/evidence cardinality |
| A20 bytes verified | Hashes/counts catch modified or missing indexed files and pcap contents for planned flows; **plan/index omissions bypass mandatory evidence**, FV-01 |
| A21 reference data | Correctly rejects omitted devices/cases and changed reference facts; does not validate evidence-child completeness |

Their conjunction is therefore **necessary but insufficient** for the claimed project acceptance. This conclusion is supported by the executed all-green negative datasets, not just by theoretical concerns about forged provenance. Historical evidence is intentionally scoped; contaminated runs stay retained and excluded. No existing historical contamination is relabelled as a new failure.

## 6. Actual independent commands, regressions and evidence checks

All commands ran from the repository root using its existing `.venv`, pinned `requirements-dev.txt` and pytest configuration. No dependencies were installed. Prefix **P** below means `.venv/bin/python`; command logs in E contain the exact wrapping command and timeout.

| Command / check actually executed | Outcome; log |
|---|---|
| `P -m pytest -q -p no:cacheprovider tests/unit tests/test_inventory.py` | **384 passed, 38.91 s**, macOS; `unit-mac.log` |
| `scripts/remediation/ctl.sh sudo env PYTHONDONTWRITEBYTECODE=1 timeout --kill-after=5 90 python3 -m pytest -q -p no:cacheprovider tests/unit tests/test_inventory.py` | **384 passed, 43.39 s**, actual Ubuntu ctl; `unit-ubuntu.log` |
| `P scripts/reaudit_remediation/acceptance_probes.py results/witness.db results/evidence results/independent-final-20261019/probe-files` | **45/45 expectations reproduced: 41 invalid rejected, four controls accepted**; `remediation-probes.log` |
| `P results/independent-reaudit-20261018/acceptance-edges.py` | Unchanged auditor reproductions reject; original 11,265 evidence-index rows exactly preserved; `original-acceptance-edges.log` |
| `P results/independent-reaudit-20261018/db-counterexamples.py` | Unchanged original missing-env/failing-fresh/partial/duplicate probes reject appropriately; `original-db-counterexamples.log` |
| `P results/independent-final-20261019/adversarial.py` | **60 independent fixtures**: 49 expected negative rejections, four valid controls, seven accepted gap probes. Every fixture integrity OK/FKs empty; `independent-adversarial.log`, full JSON results |
| `P results/independent-final-20261019/fresh-omissions.py` | Same residual omissions reproduced on latest VM data; omitted-device reporting discrepancy confirmed; `fresh-omissions.log` |
| `P results/independent-final-20261019/stores.py` | Independent hashes, flow derivation, endpoint checks, `tcpdump` reads and raw baseline payload checks; `stored-evidence.log` |
| `P results/independent-reaudit-20261018/compatibility-probe.py` | Real v3 opened read-only; only absent v4 flow/root assertions fail; two migrations preserve all original rows/columns and FKs; report flags synthetic missing/wrong-hash files; `compatibility.log` |
| `P results/independent-reaudit-20261018/original-case-deadline.py` | Unchanged full-size loopback regression: **30.002584 s**, PASS_SLOW then deadline exhaustion, **error/runner**; `original-deadline.log` |
| `P results/independent-reaudit-20261018/gateway-probe.py` | Loopback production classes: early replacement recovery **1.971689 s**, three rapid replacements **1.927387 s**, both ≤4 s; M2/F13 remain STALE_DATA with no false restart; `gateway-regression.log` |
| `P results/independent-reaudit-20261018/retry-probe.py` | Runner→PASS remains error/runner; infra→PASS error/infra; degraded/device→PASS fail/device flake; Q5/Q6 correct; `retry-regression.log` |
| `scripts/lab_vms.sh preflight` | GREEN both at start and end; `preflight-initial.log`, `preflight-final.log` |

The new negative tests do call production `analysis.audit`, `commissioned_devices`, report functions and the shared validator. They are substantive regression tests, not assertions against canned report text alone. Their coverage nevertheless omits FV-01: `test_acceptance_evidence.py` wires only selected fixture results to actual exchanges/pcaps; deleting all observations or the index for no-direct-exchange cases is not covered. Its “complete wired store” control can pass with most other results unwired. The 45 probes similarly remove flow records while retaining their observation parents; their successful reproduction does not establish parent/index completeness. This audit did not rerun the implementer's pre-fix 62-failure experiment or deploy historical defective code.

Independent stored-evidence results:

- **Master:** integrity OK, FKs empty; 12,778 indexed files re-hashed, exactly **24 disclosed historical F12 mismatches** in runs 133–138. All 264 address-bearing stored flow counts agree with `tcpdump`. Independently derived v4 coverage is 268 capture/flow records, 260 expected on wire; the only metadata-filter discrepancy is the already disclosed eight broad source-port filters in run 131. No new actual endpoint discrepancy was found.
- **Latest remediation VM store:** integrity OK, FKs empty; **394/394 indexed files** match; **58 independently derived capture/flow records, 54 expected**, no coverage/endpoint mismatch; **56/56 address-bearing counts** agree with `tcpdump` (two address-less records are not countable TCP filters). Both F3 pcaps contain the actual two SYN/RST pairs on TCP 5021. The required ctl/field sides were derived from the case contract and raw attempts/exchanges without production flow-planning helpers.
- The stored baseline has **11 passing instances**, commissions dev-a/dev-b, and has valid environment data. Independent JSON decoding checks **48 actual response records, including 40 READs**, IDs, identity/firmware, HEALTH, ten-READ series order, and send/receive-relative timestamp windows. The stored fault run has **24 passing expected-fault instances**, with **25/25 recorded removals** (F12 twice). These are successful fault detections, not commissioning passes.
- Source hashes are unchanged: master `f5f789ebc223d553416f9fc2fdc68693688250bd34f80ea855a113f70474d6dc`; latest VM store `d291b467bfb7ca589d297f0d8384ee3d0f6bea10dd759e8c5cee92a531707f84`.
- The old v3 snapshot remains `f57e5983965897b7158fb2bbfc252039aac1f0ca929a44c773124b72b8f1a24b`. Migration preserved 130 runs, 1,315 results, 1,125 attempts, 3,904 exchanges, 11,265 evidence rows and every other original table. Old missing flow evidence is reported rather than fabricated.

Historical limitations remain intact: the 24 overwritten F12 files are not certified as intact; pre-F-07 captures cannot prove absent 5021 traffic; early Phase-2 runs without field captures do not acquire them retroactively. The scoped current checks may hold while those older limitations are still reported. Superseded evidence is not silently repaired or promoted to current-revision proof.

Earlier findings remain as follows:

| Finding | Current disposition |
|---|---|
| F-01 partial baseline | Original counterexample remains fixed; FV-02 qualifies standalone inventory completeness |
| F-02 early restart | No regression in units/independent loopback; latest stored live F12 also passes. Timing-indistinguishable incarnations remain a disclosed protocol limitation |
| F-03 retry deadline reset | Original 31.6-second counterexample corrected to 30.003-second runner deadline error; wider GW/fixture scope remains open below |
| F-04 retry attribution | Independent production decision/persistence/SQL fixtures pass |
| F-05 forbidden request frames | Both complete unit suites pass production parser/socket tests; deployed device code matches the prior repaired source. No new live raw-frame campaign claimed |
| F-06 false-green acceptance | **Still open**, FV-01, despite corrected original environment/duplicate reproductions |
| F-07 TCP 5021 capture | Actual stored ctl/field packets independently verified; acceptance completeness is separately defective |
| F-08 fault count | Catalog/reference validation and units support 13 types, 21 variants, 24 live fault instances |

## 7. Remaining full-project work and bounded deadline reproduction

**Five clean current-revision restored baselines remain mandatory.** Brief §§7.3/13 requires five fresh-environment baselines. Historical `87d322b` trials cannot establish repeatability of the later parser, restart, deadline, schema and evidence changes. After repair and sufficient stable host resources, use the documented protected-original/golden procedure, never start duplicate-MAC originals and clones together, then perform five distinct restore/provision/baseline trials. Retain each source revision, restore and boot provenance, all 11 instances, no retry, clean pre/postflight, DB and capture evidence. Use separate verification outputs. A14's historical total alone is not a current-revision gate. A fresh-VM/from-scratch reproduction of the repaired revision is separately outstanding; the cached-image historical test retains its narrower validity.

**Interruption, dead-man timer, capture expiry and reset should be repeated.** The latest repair does not change fault-control implementation, but capture-flow work runs during teardown before postflight, and the earlier evidence-handling changes have not had complete post-repair crash-path verification. Normal recorded removal does not prove these paths. Once headroom and recovery access are safe, run:

```sh
scripts/lab_vms.sh interrupt-selftest TERM f2
scripts/lab_vms.sh preflight
scripts/lab_vms.sh interrupt-selftest KILL f5
scripts/lab_vms.sh preflight
scripts/lab_vms.sh reset-selftest
scripts/lab_vms.sh preflight
```

Retain process/timer timestamps and results before/after; prove the fault and both captures are active before sending the signal. Observe eventual SIGKILL recovery beyond the configured 90-second dead-man interval with a finite outer guard, plus mature ctl/field capture expiry. Require no remaining fault/qdisc/nft rule, running capture, timer or runner, and GREEN preflight. Do not infer mature orphan expiry from a kill during capture startup. These procedures were **not executed** in this audit.

**Gateway-case deadline: scope not yet established.** The immutable brief §6.2 requires an overall per-case deadline and bounded waits, but gives no fixed numeric overall value. The finalized requirements header says 30 seconds; protocol §7 calls it a hard cap for multi-request cases and explicitly starts the repaired probe deadline at the first attempt. The shared retry/probe deadline is independently verified. GW/F12 functions directly use HTTP sampling, `Connection`/`single`, sleeps and fault commands without that shared context. The fixture installs a **75-second alarm around the yielded test body**, after capture setup, and cancels it before evidence collection/postflight. Individual operations also have bounds. Therefore neither a universal 30-second whole-case guarantee nor a single deadline over all fixture setup/teardown is established by the verified retry fix. No current live GW/F12 overrun is claimed here.

A precise bounded next experiment is:

1. On the identified ctl, after resource/recovery/preflight checks, run only `tests/live/test_gateway_cases.py::test_f12_restart_during_polls` using an audit-only DB/evidence directory. An audit-only pytest wrapper records monotonic case setup, first attempt, test-body return/exception, teardown completion and result attribution; it does not edit production files.
2. Route only that wrapper's `lab.gw` HTTP client through a local ephemeral-port proxy to ctl `127.0.0.1:8080`. Forward real JSON unchanged; hold each complete response for **1.5 seconds**, below the client's 2-second per-request timeout. Keep normal gateway pollers and guest networking unchanged. Record the exact request count and every delay. Run a no-delay control first. This challenges cumulative GW observation work while preserving real upstream observations.
3. Give the pytest subprocess a **100-second outer timeout with 5-second kill grace**, retain the normal 75-second harness alarm and guest dead-man timers, and always stop the proxy. Stop additional experiments on timeout or red postflight; observe/recover the dedicated lab and record preflight afterward.
4. Assess the separately measured intervals: does the first-attempt-to-result path stop at 30 seconds with error/runner, does only the 75-second body backstop fire, and do setup/teardown complete within a documented aggregate bound? Requirement failures caused by the delay are injected failures, never baseline successes. Do not equate a short control run with a worst-case bound.

This experiment is a defined continuation, **not an executed result or installed plugin**. Deadline scope must be resolved against the immutable brief before unconditional acceptance; documentation cannot silently remove the overall-bound requirement.

## 8. Closing state and exact acceptance path

Final preflight was GREEN on field at **18:50:20Z** and ctl at **18:50:21Z**. Guest state inspection completed **18:50:24Z**: both working guests Running, stock device builds, normal modes, expected route and host mappings, no active faults, no tcpdump/pytest process, no Witness timers, active vsock recovery. Guest preflight free space: ctl **6481 MiB**, field **6316 MiB**. All four golden instances were Stopped; unrelated `vigil` was Stopped and never operated. No host route/firewall or unrelated service configuration was changed. The ctl master DB hash still matched the original.

The closing host sample at **18:50:25Z** was **6.3 GiB available**, **8806.75/9216 MiB swap**, pressure **2**. Stop resource-dependent experiments until stable headroom exists. No unrelated files were deleted to create space.

The preservation manifest covers 14,058 pre-existing files (tracked files plus retained DB/pcap files). The final comparison verifies that only the required append to `docs/implementation-state.md` changed; every other original file in that manifest remains identical. `preservation-final-verified.log` records that comparison and final Git status. The first final-record helper completed preservation checks but failed its later catalog import; that audit-helper failure remains in `preservation-final.log` and was corrected without a product change. Final Git changes are this new report, the appended ledger entry and E; implementation and prior reports remain unchanged, HEAD remains `a6d487f`.

The remaining acceptance path is bounded: correct and independently reject FV-01's missing-parent/index/count fixtures; make standalone commissioning inventory completeness explicit (FV-02); retain the existing valid controls and all original evidence; resolve/test gateway-case deadline scope; then complete current-revision restored-baseline, fresh-VM and interruption/reset evidence under safe conditions. Reassess the resulting complete dataset and its provenance. Passing the current 384-test suites or 45-probe set is not a substitute for those steps.
