# Witness — remediation of the independent evidence-contract verification (IC-01, IC-02)

Status: **repair of IC-01 and IC-02 COMPLETE** — both confirmed bypasses (and the review's counterexamples of the
same classes) are rejected, the new adversarial tests pass, every valid control keeps its outcome, and no regression
was found (section 3). **Full Witness project acceptance is NOT claimed**: the audit's outstanding experiments remain
unexecuted (section 7), and the independent review of this repair found one further, pre-existing run-identity
defect outside IC-01/IC-02 (F3, section 5) that is open. Commits: `93c029b` (audit material, verbatim), `b5873ff`
(fix, tests, contract), then this record with its evidence and the ledger entry.

Input: [independent-contract-verification.md](independent-contract-verification.md) (repair NOT VERIFIED; IC-01 P1,
IC-02 P2) at audited revision `4b1f658`. The audit's report, ledger entry and evidence were committed verbatim and
alone first (`93c029b`; report sha256 `cd969fd2…be7`). Scope: exactly those two defects (and the oracle gap the audit
attributed to IC-02), their regression coverage, and the verifier's ability to detect them. Evidence directory
**E2**: [results/independent-contract-remediation-20261020](../results/independent-contract-remediation-20261020/).
Command logs there are written by the auditor's own recorder (`E2/run.py`: UTC start/end, argv, exit code, elapsed
time, output). Every result below was executed; synthetic stores are fixtures, never lab observations.

## 0. Starting state, resources, preservation

| Item | Value |
|---|---|
| HEAD at start | `4b1f658`; working tree: the audit's ledger entry, report and evidence (untracked); no earlier work for this task |
| Host | 3.8 GiB free on `/`, swap 11473/12288 MiB at start; during the work 4.8–5.3 GiB free, swap ~10.2/11.3 GiB, 31 % memory free |
| Host at the end | 5.6 GiB free, swap 10204/11264 MiB, 31 % memory free; this work's temporary stores removed (fixture stores in temporary directories, the guest harness `--basetemp`) |
| Decision | no restore, clone, fresh-clone trial, campaign or fault experiment; `witness-ctl` and `witness-field` were already running (goldens and `vigil` stopped, untouched) |
| Preserved | `PROJECT_BRIEF.md` `07a33a08…5baf`; master `results/witness.db` `f5f789eb…d6dc` and live v5 store `1a213213…6f32f67` opened only `mode=ro` and copied to memory, hashes rechecked in every log; the audit's files untouched — its scripts were run from byte-identical copies in E2 (sha256 equal) because they write their outputs beside themselves |

## 1. IC-01 — a run certified its own abort

**Original failing reproduction** (unchanged auditor scripts on `4b1f658`; `E2/red/confirm-red.log`,
`E2/red/challenge-red.log`). Current-failure reference store: **22/24** (A4, A18; A18 on run 14). After
`UPDATE runs SET contaminated = 1, notes = notes || ' | aborted: never finished (detected by run ' || run_id || ')'
WHERE run_id = 14`: **24/24**, A18 on the older green run 5, all 19 triggers retained. Same edit on the deadline-cut
fault run: 24/24.

**Root cause.** `contract._contamination_cause` corroborated an abort marker when the cited run's start lay inside
the aborted run's interval (`det >= started_at` and `finished_at >= det`), using only the two `runs` rows. The run's
own start satisfies it by construction — the run was its own witness. The independent review of the first repair
showed the same circularity one column over: the run's own `finished_at`, in the same row as the flag, could claim
that it was still running when a genuine later run started (review F1/F1b: one UPDATE, 24/24), and the detector's
`started_at` or a bare inserted `runs` row could do the same (F1c, F2). Further: only the first marker was read,
times were never validated (a missing start raised `TypeError`), and the writer (`db.mark_aborted_runs`) excluded
only the detecting run itself, not newer runs. Selection then did what it does for a genuinely unfair run: the
current failure left A4/A18 through status metadata alone.

**Corrected invariant (contract I1.2).** Every `aborted: never finished (detected by run N)` marker must name a run
N that (1) is a separate recorded run, never the run itself; (2) has a larger run id and a strictly later recorded
start, both in the runner's time form; (3) recorded its session — at least one append-only session record (`checks`
or `evidence` row without a result), the first of which the live session writes right after marking; and (4) found
the run unfinished: no finish, or a finish after N's start **whose own last session record (its teardown) is later
than N's first session record**. The runs row's `finished_at` never proves the overlap; equal times cannot order two
sessions. Every marker must hold. Master run 38's genuine overlap (SIGTERM self-test: teardown records
45.210–45.218Z after run 39's first record 45.087Z) and run 7's two markers (runs 17, 18) stay corroborated. An
uncorroborated abort violates A23 naming the run; the full report shows it (`A23 VIOLATED | run 14: [I1.2]
contaminated as aborted, but run 14 cannot have found it unfinished: it names itself as the later session`).

**Code.** `runner/contract.py`: `_contamination_cause` checks every marker through the new `_abort_unconfirmed`
(each condition with its own message); `_runs_checked` computes each run's first/last session record time from
`checks.checked_at` and `evidence.created_at` over all runs. `runner/db.py` `mark_aborted_runs`: only runs with a
smaller id than the detecting session (`run_id < ?`). Selection (`FAIR`) is unchanged by design: a corroborated
abort still removes a run from evidence (the audit's valid unfinished/partial controls stay accepted); a forged one
makes the store unacceptable.

**New adversarial coverage.** `tests/unit/test_abort_corroboration.py` (27 tests): self-reference; unknown
detector; earlier detector, equal start, larger id with an earlier start; legitimate later detection; detection
during the teardown (run 38, with its real record times); finish before detection; finish moved after the detector's
start with no later session record (F1); detector start moved inside the run (F1c); same-millisecond records; a
detector with no session record (F2); five missing/malformed timestamp cases; every marker must hold (run 7; a
self-citing second marker). Store level, through `analysis.audit`: the auditor's baseline counterexample and the
fault-run variant; F1 on a fault run followed by the next session; F1b (baseline then fault run, normal campaign
order); F1c; F2 (bare inserted detector row); a killed failing run marked by the next session (valid control: all
24 hold, A18 = that session); a killed run's marker rewritten to cite itself; the writer never marking a newer run.
Harness: control variant `aborted-detected` (killed run holding a genuine failure, found by the next session:
acceptable) and eleven declared IC-01 mutations (the auditor's SQL on the newest baseline and on the current fault
run, unknown and earlier detectors, the killed run's marker rewritten to itself, a self-citing marker added, a finish
before detection, the detector's start moved earlier, review F1, F1c and F2) — each must violate A23. The oracle now
projects each run's cited detectors. Self-test weakenings: the pre-repair interval rule; the overlap taken from the
`runs` rows instead of the session records.

**Original reproduction after the repair** (`E2/confirm-final.log`, `E2/challenge-final.log`; the identical
`*-after` logs are from the first repair): self-abort **23/24, A23** (was 24/24); self-abort-on-fault **23/24, A23**
(was 24/24). The reviewer's unchanged probes `review-probes/p1*`, `p2*`: each now **23/24, A23** (were 24/24).
Controls unchanged: failing control 22/24 (A4, A18); green, partial-valid and unfinished-valid 24/24;
partial-failing 23/24 (A4) — exactly as the audit recorded them.

## 2. IC-02 — a deleted decision predicate removed its own obligation

**Original failing reproduction** (`E2/red/confirm-red.log`, `E2/red/challenge-red.log`). Copy of the live v5 store,
`UPDATE results SET predicates = '{}'` for run 1 C-GATEWAY/dev-b: **21/24** (only the store's A12/A14/A15), both
devices commissioned. From a synthetic API failure (19/24, dev-a only), `json_remove(predicates,
'$.api_unknown_device_404')` with verdict pass: **21/24**, dev-b commissioned. Reference stores:
gateway-predicate-erasure and erase-all-decision-predicates **24/24**; the oracle saw **no deviation** when the
predicates were erased.

**Root cause.** `contract._decision` validated `results.predicates` only as recorded: any boolean dictionary
passed, including `{}`; the only names it required were the final attempt's, and gateway-observed and record cases
have no runner attempt. No source independent of the row said which predicates a case decides on — deleting a name
deleted its check (the FV-01 pattern, inside the decision record). Non-timing predicates (API status codes,
identity, firmware, freshness) exist nowhere else, so measurement bounds could not stand in. In the same record,
`json.loads` keeps the last of two equal names (a `false` followed by a `true` reads `true`), and a fail verdict was
never checked against its basis. In the harness, the oracle's projection omitted `results.predicates` and the
reference writer recorded a placeholder name instead of the live names.

**Which predicates must exist independently of the rows** (`runner/contract.py`): `CASE_PREDICATES` — for every
case, the names its live test records with its verdict (`tests/live`: `extra_predicates` of `case.finish`, the
predicates of `finish_observed`): C-GATEWAY's 15; GW-F1/F5/F8 per observed device (`{dev}_unreachable_within_3P`,
`{dev}_category_<prediction>`, `{dev}_recovered_within_2P_of_revert`, `{other}_stayed_healthy`,
`api_observed_within_3P`; GW-F5 observes both devices and leaves none to stay healthy); FT-F12's 13; each runner
fault case's own; C-ENVIRONMENT one per REQ-10 key (`runner/evidence.required_env_keys`, the function the live case
uses). `PARTIAL_PREDICATES`: the set a case that stopped before its observation was complete records instead, valid
only on a fail (FT-F12: `pre_restart_connection` when the old process could not be reached). Attempt-level names
(`status_ok`/`sensor_ok` or `health_payload`, `reads_complete`) come from the final attempt's exchanges and response
bytes (`derived_predicates`), as before.

**Corrected invariant (contract I4.5).** A decided v5 result's decision holds exactly the attempt-derived names
plus the case's names (`case_predicates(case, device, inventory)`); a fail may hold a declared partial set instead;
C-ENVIRONMENT may add contradictory other records only as `false`; a name recorded twice is unreadable; and the
verdict is the one its recorded basis yields — a pass needs every predicate true (unchanged), and a fail over
observed = expected, every predicate true and (runner cases) one attempt with outcome `ok` is a contradiction. The
check lives in `_result`, so A24 (current evidence) and commissioning (A18, the report) apply it alike.

**Code.** `runner/contract.py`: `CASE_PREDICATES`, `PARTIAL_PREDICATES`, `case_predicates`, `_predicate_record`
(strict reader), `_decision` (names, partial sets, verdict basis). Harness: `refstore.OWN_PREDICATES` (its own copy
of the live names; every decided fixture result records them; realistic gateway-bound, API and withheld-firmware
failures), control variant `gateway-api-failure` (a non-timing gateway failure with every bound met: A4, A18),
`oracle.py` projects the predicate pairs in name order with duplicates kept (order is benign; a duplicate, erased or
relabelled name is a deviation).

**Anchoring the names to the live code.** `tests/unit/test_decision_predicates.py` parses `tests/live/test_*.py`:
for each `@pytest.mark.case` function it renders every `case.finish`/`finish_observed` predicate set exactly —
helper parameters bound to the literal arguments the case passes, f-string loop variables bound to their `for`
sequence, helper-level values such as `expected = catalog.FAULTS_BY_ID[fault_id].expected_category` evaluated — and
requires the contract's full set to equal the complete decision (the call recording `preds`) and its partial sets the
others, for every catalog case and instance device; the reference writer's copy likewise. Shapes it cannot render
exactly (a name recorded conditionally, a dict under another name, an f-string conversion, two literal decisions)
fail the test instead of being misread; the C-ENVIRONMENT key computation and the attempt-level names are pinned to
their writers. All 35 decisions of the retained live v5 store carry exactly the contract's names (0 mismatches).

**New adversarial coverage.** `tests/unit/test_decision_predicates.py` (87 tests): the anchor (2 × 30 cases, catalog
completeness, writer pins, four unrenderable shapes, rendered GW categories/devices, F11 ends, F12 split); live
gateway decision accepted; `{}`; the auditor's API failure (a valid fail), then its false predicate erased with the
verdict flipped; a duplicated name (`false` then `true`); a renamed name; reordered names (benign); a non-boolean
value; a fault case's own predicate; GW-F5's per-device names; partial observations that are complete records of a
fail (C-HEALTH refused → `health_payload`, a READ series stopped early, FT-F12 before the restart) and the F12
partial set never supporting a pass; C-ENVIRONMENT (every REQ-10 key, a contradictory record as false on a fail, an
extra true key); a fail over an all-true gateway basis and over a passing runner attempt; genuine runner failures
(degraded HEALTH on both attempts, FLAKE) keep their basis; acceptance level: the accepted fixture store records the
live names and holds 24/24, `{}` on its C-GATEWAY/dev-b violates A24 and A18 and commissions only dev-a, the
auditor's flip violates A24 and A18. Harness: ten declared IC-02 mutations (C-GATEWAY/dev-b erased; the auditor's
erase-all SQL; the auditor's API-failure deletion with the verdict flipped, and the same failure shadowed by a later
duplicate or renamed; FT-F3's own predicate; GW-F5's dev-b names; F12's partial set on a pass; a REQ-10 key; a fail
over an all-true basis), one benign reorder, and an oracle test (erased, duplicated and relabelled decisions deviate;
reordered does not). Self-test weakenings: the pre-repair `_decision` (names from the row); duplicate names read as
their last record.

**Original reproduction after the repair** (`E2/confirm-final.log`, `E2/challenge-final.log`): live copy, all 15
predicates deleted: **19/24, A18 and A24 added, dev-b no longer commissioned** (was 21/24, both); live copy, the
synthetic API failure erased and flipped: **19/24, A18 and A24, dev-a only** (was 21/24, dev-b commissioned);
gateway-predicate-erasure **22/24** (A18, A24; was 24/24); erase-all-decision-predicates **21/24** (A14, A18, A24;
was 24/24); oracle projection: a deviation (was none). Controls unchanged (actual v5 store 21/24, synthetic API
failure 19/24). One intended difference: the auditor's synthetic `gateway-failure-control` records 2 of the 15 names
on its fail, so it now also violates A24 (21/24 instead of 22/24; rejected before and after).

## 3. Verification (repository root, `.venv/bin/python`, Python 3.14.7, macOS)

| # | Command | Result |
|---|---|---|
| 1 | `E2/run.py confirm-red …`, `challenge-red …` on `4b1f658` before any change | both findings reproduced exactly (sections 1, 2) |
| 2 | `-m pytest tests/unit/test_abort_corroboration.py tests/unit/test_decision_predicates.py` before the fix (`E2/logs/red-new-tests.log`) | **89 failed, 11 passed**; the 11 are the valid controls. Review regressions before their fix (`red-review-ic01.log`): the four store-level F1/F1b/F1c/F2 tests failed on their assertions |
| 3 | the two files after the fixes | **27 + 87 passed** |
| 4 | `E2/run.py logs/unit-contract-mac-final-2 1800 … -m pytest -q -p no:cacheprovider tests/unit tests/contract tests/test_inventory.py` | **824 passed** in 217 s, exit 0, on the committed code (685 before this repair). Earlier full runs kept: 807 passed (first repair), 1 failed / 817 passed (`unit-contract-mac-after-review-1-tie-failure.log`: the same-millisecond tie, then fixed), 819 passed (before the anchor hardening) |
| 5 | unchanged auditor scripts `confirm.py`, `challenge.py`, `original-fresh-omissions.py` (`E2/*-final.log`) | sections 1, 2; the FV-01/FV-02 omission probes print output identical to the audit's log apart from timestamps |
| 6 | `results/acceptance-integrity-20261019/real_store_audit.py` on master and live v5 (`E2/logs/real-store-*-final.log`, JSON in E2) | master **24/24** (per-assertion verdicts identical to the prior record), live v5 **21/24** (only A12/A14/A15); sources unchanged |
| 7 | reports regenerated from a memory copy of the live store (`E2/regenerated-live-reports/`) | all six identical to the audit's `4b1f658` regeneration except the generation timestamp |
| 8 | `E2/run.py logs/verifier-full-final 3300 … scripts/verify_acceptance_contract.py --json E2/verifier-final.json` | **PASS, exit 0: 353/353 checks OK** (9 controls, 224 declared mutations, 2 × 60 seeded combinations) in 784 s; **12/12 weakenings detected** (IC-01 interval rule: 7 mutations fail; review F1 overlap from the runs rows: 3; IC-02 names from the row: 10; duplicate names: 1). Earlier attempts kept: first repair 350/350 with 11/11 (`verifier-full-before-review.log`); final code, first attempt **353/353 OK but RESULT FAIL** — the IC-01 interval weakening still had the pre-review signature, crashed into the verifier's fail-closed path and so weakened nothing, reported "NOT DETECTED" (`verifier-full-final-1-broken-weakening.log`); the weakening (test code only) was corrected and the verifier rerun |
| 9 | `cc-sast --changed .` (`E2/logs/cc-sast-changed.log`) | 33 findings, none on a line this repair added (pre-existing formatted SQL from code constants, and the auditor's script copies) |
| 10 | witness-ctl / witness-field, Ubuntu 24.04, guest Python 3.12.3 (`E2/logs/vm-*`) | preflight **GREEN** on both (06:33Z); `lab_vms.sh sync` of `b5873ff`, `git_dirty=0` on both (no service restarted; device, gateway and preflight code unchanged by this repair); `lab_vms.sh unit`: **505 passed** (= the Mac's unit + inventory count); `tests/contract` with 20 seeds under a removed `--basetemp`: **279 passed**; postflight **GREEN** on both (06:38Z); no pytest/tcpdump process, no harness temp, no netem qdisc or fault nft table left (`vm-residue-after.log`). No fault was injected and no suite run against the devices |

## 4. Independent review (one read-only reviewer, fresh context, two rounds)

Input: the brief's invariants via the audit, the contract, the exact diff (`E2/review-input.diff`, then
`E2/review-followup.diff`). The reviewer edited nothing in the repository, worked on disposable reference stores and
memory copies, and kept its probes and logs in `E2/review-probes/`.

| Finding | Reviewer's counterexample | Resolution |
|---|---|---|
| F1 P1 (IC-01 class) | fault run's `finished_at` moved 1 ms after the genuine next run's start + marker: 23/24 → 24/24; F1b the same on a failing baseline followed by a fault run (A18 fell back to run 5, commissioning dev-a) | reproduced (also on `4b1f658`); overlap now proven only by append-only session records (I1.2 (4)); RED tests then fix; probes now 23/24 (A23) |
| F1c P2 | the detector's `started_at` moved 1 ms after the failing run's start | same fix (the detector's first session record decides); 23/24 (A23) |
| F2 (boundary) | bare inserted `runs` row as the detector | the detector must have a session record; 23/24 (A23) |
| F3 P1, outside IC-01/IC-02 | failing baseline relabelled `kind='mutant'` + three `environment` rows: 22/24 → 24/24 (the hash-verified `session/environment.json` still says baseline) | reproduced on `4b1f658` too: **pre-existing run-identity defect, not a regression, not fixed here — open** (section 5) |
| F4 P3 | the anchor treated `{}` as any text: wrong GW-F8 category, GW-F5 without dev-b, F11 FIN with RST names, F12 partial name in the full set all passed | exact rendering; the four wrong sets detected (`E2/anchor-sensitivity.py`, exit 0) |
| F5 P3 | boundary said no other record holds a case predicate's value — untrue for `zero_response_bytes`, `detail_*` | wording corrected (the verifier does not recompute them) |
| R2-1 | under `>=` a same-millisecond tie accepted F1 (about 10 of 104 fixture pairs tie) | strict `>`; tie test added (found independently by the full suite, `…-1-tie-failure.log`) |
| R2-2 P3 | contract said "no earlier than", code "later than" | wording corrected |
| R2-3 (safe side) | a detector killed between marking and its first record, or a run finishing between its last record and `finish_run` as the next session starts (sub-millisecond windows, concurrent sessions only): genuine, rejected | stated in the contract as a fail-closed limit (no record shows the overlap); live session code unchanged |
| R2-4 (boundary) | INSERTed session records (a teardown check, or a detector row with a check) corroborate a forged abort whatever their status | stated in the contract's boundaries |
| anchor blind spots P3 | four synthetic shapes not used in `tests/live` misrendered silently | the anchor now fails on them (4 tests); env and attempt names pinned to their writers |

Rejected attacks the reviewer tried (logs `p4_*`, `r2_*`): IC-02 with unicode-escaped duplicates, `[]`, a JSON
string, NULL, renamed names (whitespace, case), BLOB, `"true"`/`1`, nested objects, observed NULL, fail → error;
partial sets on passes; GW category/stayed-healthy renames; C-ENVIRONMENT extra names; a genuine marker plus an
earlier-run marker. Legitimate data (live v5 21/24 with 0 decision violations, master 24/24, `aborted-detected`
24/24) accepted on the strict code.

## 5. Open finding outside this repair (not fixed, not claimed)

**F3 (review, P1 by its severity scale): a failing baseline relabelled as a mutant run leaves acceptance.** `UPDATE
runs SET kind='mutant', mutant_id='M5'` plus the three environment rows A13 compares (`runs.kind`, `mutant`,
`device_build.dev-a`) takes the current-failure store from 22/24 to 24/24 (A18 on run 5), on this repair and on the
audited `4b1f658` alike (`E2/review-probes/p3_baseline_relabelled_mutant.*`; the `4b1f658` rerun used an exported
copy of that revision). The run's indexed, hash-verified `session/environment.json` still records `runs.kind`
baseline, but the verifier never compares its contents with the table. It concerns run identity (selection excludes
mutant runs), not abort corroboration or decision predicates, so it was left for a decision rather than fixed under
this scope.

## 6. Limits of this repair

Unchanged contract boundaries (now stated explicitly): a coordinated rewrite of a status and its corroborating
records, including fabricated session records for an abort; a forged value self-consistent with every record,
including a false case predicate rewritten `true` under its own name (the gateway's API checks exist nowhere else);
the audit's boundary probe `unfinished-postflight-index-erasure` (finish cleared together with both classes of
postflight records) stays accepted. Fail-closed limit: a genuine abort whose overlap no session record shows (R2-3)
is rejected. `planned_at`/`user_version` edits remain accepted (the audit found no obligation lost).

## 7. Outstanding for full-project acceptance (unchanged, not executed here)

Five clean restored-environment baselines on the final revision; a current-revision mutant campaign; interruption,
dead-man, capture-expiry and reset recovery; gateway/F12 whole-case deadline verification; fresh-VM reproduction
(audit section 6) — blocked by host resources (below the 10 GiB restore threshold) — and the open F3.
