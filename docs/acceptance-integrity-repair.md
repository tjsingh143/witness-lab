# Acceptance-integrity repair (FV-01 / FV-02 class)

Status: **repair COMPLETE against its gate (section 11); full-project acceptance NOT claimed** — it needs the
independent verification and the outstanding experiments listed in section 12. Every result below was executed;
nothing is inferred from older evidence.

Inputs: [independent-final-verification.md](independent-final-verification.md) (FAIL: FV-01 P2, FV-02 P3), both
earlier audits and remediation records, the ledger, and the code at HEAD `a6d487f`. The contract this repair
implements is [acceptance-contract.md](acceptance-contract.md).

## 1. Verified root causes (established before any production change)

Traced link by link from requirement to report (`runner/analysis.py`, `runner/db.py`, `runner/report.py`,
`tests/live/conftest.py`), against the real stores (`results/witness.db`, the latest `aa9e193` VM store) opened
read-only.

| # | Root cause | Where | Consequence (reproduced by the final verification) |
|---|---|---|---|
| RC-1 | **Obligations derived from the rows being verified.** The required capture flows of a result are computed from its surviving `attempts JOIN exchanges`; a result with no exchange rows is skipped (`if not x: continue`). | `analysis.flow_plan` | Deleting a result's exchanges removes its A17 record obligation and its A20 recount: missing field flow and packets=999 both 21/21 (FV-01). |
| RC-2 | **No cardinality between a result and its children.** `results.attempts` is never reconciled with attempt rows, attempts are never required to hold exchanges, and the exchange sequence is never compared with what the case executes. | A10/A16/A17 scope | A passing result survives with zero attempts or a truncated READ series (one READ kept of 12, still 21/21). |
| RC-3 | **Evidence verified only if indexed.** A20 checks the files that the `evidence` table lists; nothing states which files a case or session must have. Gateway-observed cases (no exchanges) have no capture obligation at all. | `analysis.evidence_violations` | Deleting index rows of C-GATEWAY, GW-* or session files: 21/21, both devices still commissioned. |
| RC-4 | **Selection over surviving results only.** "Latest fair result per instance" and "latest complete baseline" are chosen from the results that exist; the store records no declared test selection. | `LATEST_FAIR`, `latest_complete_baseline` | Deleting a newer result makes an older run's pass the "current" evidence (no record says the newer run executed it). |
| RC-5 | **Required devices taken from the database, not the inventory.** `COMMISSIONING_GAPS`/`COVERAGE` cross the catalog with the `devices` table. | `db.py`, `report.commissioning_table` | Deleting dev-b's rows: standalone commissioning "COMPLETE 6/6", dev-b silently absent (FV-02). |
| RC-6 | **Commissioning and report decide on verdicts alone.** `commissioning_gaps` trusts a pass verdict without its evidence chain, so the report can commission a device whose evidence acceptance would reject. | `db.commissioning_gaps`, `report.py` | C-GATEWAY index rows deleted: still commissioned. |

Common cause: **every obligation set was computed from the evidence under examination**, so removing evidence also
removed the obligation. Each previous fix hardened one query while keeping that structure. The repair moves every
obligation to a source that the verified rows cannot change: the catalog case contract (code), the inventory, a
declared run plan recorded before any case executes, and the evidence directories on disk.

Secondary findings confirmed: the report prose said an AMBIGUOUS run "commissions nothing" while the implemented and
tested rule is per device (FV-02 note); fairness flags (`clean_env`, `contaminated`) are checked against the run's
environment record only for runs that are already fair, so a flag change can remove a newer run from evidence.

## 2. Design chosen (smallest that closes the class)

See the contract for the invariants. Components: a catalog-derived **case contract** (attempt cardinality, command
grammar, dialled target, required captures/evidence files/fault applications/measurements, `runner/contract.py`); a
**run plan** (schema v5: `run_plan` rows + the indexed `session/plan.json`, written before the first case); **receipts**
(every executed case created `run-N/<case>__<device|run>/`; each must have its result, the only completeness anchor for
runs that predate the plan; checked equal on all 135 fair runs of the master before use); the **migration record** as
the authority for when an obligation starts, itself checked against the schema and the rows it governs; one verifier
module used by acceptance (A17, A20, A22-A24), commissioning and the report alike; append-only delete/update guards on
evidence tables (defence in depth, not proof).

Evaluated and not adopted: a write-before-I/O journal per exchange. Within a case the catalog grammar already fixes
which operations must exist and where they dial; a journal would have changed the live exchange path (client) that this
repair otherwise leaves untouched. Not adopted either: grandfathering runs without a plan (the absence would again be
read as "nothing was required"), or assuming that every earlier run selected its kind's full suite (false rejections:
the master holds genuinely partial F12 reruns 134-138 and 147-149).

## 3. Pre-repair counterexamples (executed, HEAD `a6d487f`)

| Counterexample | Pre-repair result | Post-repair result |
|---|---|---|
| FV-01: F3 exchanges + field flow row deleted (master copy) | 21/21 hold | A17, A24 violated |
| FV-01: F3 exchanges deleted, counts 999 | 21/21 hold | A17, A20, A24 violated |
| FV-01: F3 exchanges, attempts, flows, evidence index deleted | 21/21 hold | A20, A24 violated |
| FV-01: all C-GATEWAY / GW evidence index rows deleted | 21/21, both devices commissioned | A18, A20, A24; nobody commissioned |
| FV-01: session evidence index deleted | 21/21 | A18, A23; nobody commissioned |
| FV-01: C-READ-SERIES reduced to its first READ | 21/21 | A18, A24; dev-a not commissioned |
| FV-01: runner source port erased, flow widened and recounted | 21/21 | A18, A24 (I6) |
| FV-02: dev-b's rows deleted, standalone commissioning | "COMPLETE 6/6", dev-b absent | dev-b listed with every missing instance; 11 required |
| Newer baseline flagged unclean/contaminated by a bare edit (harness seed 37, genuinely failing store) | ACCEPTED (fell back to an older run) | A23 (I1.2) |
| Result of the newest baseline deleted (any of 11) | ACCEPTED via the older trial | A4, A18, A23 |

Harness against untouched HEAD with the final matrix (`red-head-final-matrix.{log,json}`): **328 checks, 167 false
acceptances**, 19 rejected only by an unrelated assertion, 15 attacks needing schema v5 N/A; the six legitimate
controls that exist before v5 held. (`red-prefix.*` is the first red run, before the matrix grew.) Report tests (FV-02 scope, ambiguous-run prose) and the new v5 unit tests fail on HEAD
(`red-head-unit-tests.log`, 11 failed).

## 4. Implementation

- `runner/contract.py` (new): the per-case contract and its verification: `result_violations` (I4-I7, I10.2/3),
  `run_violations` (I1.2-I1.5, I10.4), `flow_record_violations` (I8.1, never skips a result), `bytes_violations` (I7,
  I8.2 gateway polls, I9), `schema_record_violations` (I1.1), `commissioning_contract_gaps` (I10.5). Every violation
  names its invariant.
- `runner/analysis.py`: A4/`current_evidence` select the latest fair run that recorded **or planned** an instance
  (`LATEST_CURRENT`; a planned instance without a result is reported, never replaced); `latest_complete_baseline`
  selects by selection, not survival; A17/A20 delegate to the contract; new A22 (integrity, orphans, migration
  record), A23 (flags, plan, receipts, session evidence), A24 (evidence chain). `LATEST_FAIR` stays plain SQL for
  scripts written against schema v4.
- `runner/db.py`: schema v5 (`run_plan`, unique per instance; append-only guards), `record_plan`; commissioning SQL
  over the **inventory**; `commissioning_gaps` applies the contract (bytes and receipts with an evidence root).
- `runner/report.py`: the same selection and commissioning function; INCOMPLETE status; MISSING planned instances in
  traceability; the ambiguous-run prose states the implemented per-device rule.
- `tests/live/conftest.py`, `runner/catalog.py`: the session records the plan (every collected instance) and its
  `plan.json` before the first case; `FAULT_DEVICE`/`instance_device` shared by plan and case.

## 5. Independent test oracle and harness

`tests/contract/`: `refstore.py` builds valid reference stores through the production **writers** only (the calls the
live fixture records with) with packet counts and flow reasons computed by its own code; `oracle.py` shares no code
with any verifier: truth is its own SQL projection of every obligation-bearing record plus the SHA-256 of every
evidence file, and a store deviating from it is rejected (otherwise the variant's declared outcome stands);
`matrix.py` declares each attack, the invariant it breaks and the assertions that must report it before anything runs;
`harness.py` compares production (`runner.analysis.audit`) with both. Variants (legitimate controls): reference,
deadline-cut probe (exactly A4), genuinely partial newer run, superseded failure, genuine current failure (exactly A4,
A18), runs predating the plan. Randomised: seeded combinations of 2-5 attacks (+ benign edits), greedily shrunk on
failure; on the genuinely failing variant, removing evidence must never make the store acceptable. Self-test: six
deliberate weakenings of production (A24 off, A23 off, FV-01 skip, FV-02 device scope, plan-blind selection,
responses not re-read) must each make the suite fail. Command: `scripts/verify_acceptance_contract.py`.

Limits: the oracle judges mutations of known stores, not arbitrary stores; the matrix contains only attacks the
contract claims to detect (boundaries: docs/acceptance-contract.md).

## 6. Mutation matrix and harness results

Evidence: `results/acceptance-integrity-20261019/` (`logs/contract-harness-final-*`, `green.json`, red files above).
Matrix entries are grouped by the contract invariant they break; every REJECT entry names the assertion(s) that must
report it, and the oracle confirms independently that each attack deviates from the reference.

| Run | Controls | Declared mutations | Random combinations | Self-test weakenings |
|---|---|---|---|---|
| HEAD `a6d487f`, final matrix | 6/6 as declared (legacy variant needs v5) | 167 false acceptances, 19 caught only by an unrelated assertion, 15 N/A | 120 included in the counts | n/a (no contract module) |
| repair (`contract-harness-final-*`, `green.json`) | **7/7** exactly as declared | **202/202** as declared (oracle agrees) | **120/120** rejected; the failing variant never became acceptable | **8/8** weakenings detected |

Families covered (each against the reference or a control variant): every required result of the newest baseline and
current fault run in turn; every runner result's exchanges and attempts; one middle exchange; truncated series; flow
rows (one, one side, all); capture index rows (ctl, field, gateway, session); capture/session/case files deleted or
damaged; whole run; devices/cases/case->requirement rows (deleted, orphaned, changed); fault applications and
measurements; check rows; plan rows, plan files, migration records; duplicate results (both orders), attempts,
exchanges, fault events, capture index rows; contradictory environment and run flags; endpoint/port/device/capture-side
mismatches; attempt/exchange renumbering; packet counts 0/999/+1; unrelated traffic with re-hashed indexes; summary
columns rewritten over a genuine failure; benign edits (must still accept). Random combinations draw 2-5 attacks
(+ benign edits) from a pool covering every evidence table, seeds 0-59 on the reference and on the genuinely
failing variant (which must never become acceptable).

## 7. Earlier audits' reproductions, rerun on the final code (copies run from this evidence directory)

| Script | Result |
|---|---|
| final verification `fresh-omissions.py` (latest VM store) | FV-01 probes rejected (A17/A20/A24 beyond the store's own A12/A14/A15); FV-02: 11 required instances, dev-b with every gap, dev-a commissioned per device |
| final verification `adversarial.py` (60 master fixtures) | 49/49 negatives rejected as declared; master control accepted; all 7 former accepted gaps now rejected; 3 flag-only "unfair" controls now rejected by I1.2 (intended) |
| final verification `stores.py` | unchanged independent facts: 12,778 files, the 24 disclosed F12 mismatches, 264 tcpdump recounts agree |
| second audit `acceptance-edges.py`, `db-counterexamples.py` | every counterexample rejected; probes without an evidence root additionally report A20/A23 |
| second audit `compatibility-probe.py` | v3 copy read-only and unchanged; v3->v5 migration keeps every row; fails A17/A20 (as before), A23 (no evidence root), A24: its latest FT-F12 (run 128) predates the early-restart part of the case (one application, no early-restart measurements) |
| second remediation `acceptance_probes.py` (45) | 40 as before; 5 intended differences: 3 former controls (partial baseline made by deleting executed results whose directories remain; `contaminated=1` / `finished_at=NULL` by bare SQL) now rejected by A23; 2 forged no-wire justifications reported by A24 [I6] instead of A17 |
| second audit `retry-probe.py`, `gateway-probe.py` | unchanged runtime behaviour (retry attribution, early-restart recovery 1.97 s / 1.89 s) |
| the reviewer's 13 probe scripts | every counterexample rejected (`review-probes/after-fix.log`) |

## 8. Regression and real-store results

- macOS (Python 3.14.7): `pytest tests/unit tests/contract tests/test_inventory.py`: **685 passed** (391 unit, 294
  harness), `logs/unit-mac-final-*`. The earlier unit fixtures were rebuilt on the contract-complete writer (their old "complete" store had
  most results without attempts, exchanges or captures, which is exactly what the final verification criticised);
  expected messages gained invariant tags, the assertion count went from 21 to 24, three unfair-run fixtures were made
  realistic (an unfinished run has no teardown; a run contaminated after a red postflight has that failed check).
- New v5 unit tests (plan recording, append-only guards) fail on HEAD and pass now.
- Real stores, read-only copies, final code: master **24/24**; latest `aa9e193` VM store **21/24**, only A12/A14/A15
  (no mutant or fresh-clone runs in it), both identical to their pre-repair verdicts; source hashes unchanged
  (`f5f789eb...`, `d291b467...`).
- `cc-sast`: 28 (runner) + 11 (scripts) findings, all "formatted SQL" built from code constants with values bound;
  the inventory values of the commissioning SQL were changed to bound parameters. It scanned no file under `tests/`.

## 9. Independent review (one read-only reviewer, fresh context)

Input: the brief, this contract, the diff, the red/green harness results. The reviewer edited nothing, worked on
disposable copies and its own probe scripts (kept in `results/acceptance-integrity-20261019/review-probes/`), and
reported **11 reproduced defects** (2 P1, 4 P2, 5 P3), all attacks absent from the first matrix. Every finding was
evaluated against executable evidence and accepted; each was first added as a declared mutation or report test
(`matrix.review_findings`, `test_review8/9`), observed failing (15 false acceptances / missed invariants, 2 report
failures), then fixed:

| # | Finding (reviewer's counterexample) | Fix | Rule |
|---|---|---|---|
| 1 P1 | `finished_at = NULL` on the newest run hid its failure (fallback to an older run) | an unfinished run with a session postflight is a contradiction; a contamination flag must be corroborated | I1.2 |
| 2 P1 | plan rows deleted / table dropped, v5 migration moved or deleted, result + directory deleted, plan file untouched | an indexed plan file binds its run; plan files require migration 5 before them | I1.1, I1.3 |
| 3 P2 | gateway bound failure or F11 shape failure turned into a pass by one verdict flip | `results.predicates` (v5) records the whole decision; pass ⇒ all true, measurements within bounds, F11/F13 sequences as predicted | I4.5, I10.3 |
| 4 P2 | predicates erased (NULL) made "outcome ok" vacuous | v4+ predicates must be recorded and equal those re-derived from exchanges and response bytes | I4.6, I5.6 |
| 5 P2 | an evidence row re-pointed at the other side's or another result's capture | captures by exact name in their own case directory; no file indexed twice | I7, I9 |
| 6 P2 | commissioning ignored missing flow records | commissioning applies I8.1 | I10.5 |
| 7 P3 | devices row differing from the inventory still commissioned | a gap of that device | I3 |
| 8 P3 | report 4b showed an older pass for a planned-missing fault instance | same current selection, MISSING shown | I11 |
| 9 P3 | report said "A18 evaluates it" for a run A18 skips | the report names A18's run | I11 |
| 10 P3 | plan file of a superseded fair run deleted, accepted | plan file presence and hash checked for every fair run | I1.3 |
| 11 P3 | injector records (inventory/hosts/counters) not required | required per fault kind | I10.3 |

The reviewer's own probe scripts, rerun unchanged after the fixes (`review-probes/after-fix.log`), reject every one
of its counterexamples, including the real-master variant of finding 11 (A24). Its critique of the harness was also
taken: the reference writer now records distinct ctl/field capture bytes, the injector's per-kind files, measurement
bounds (including F13's predicted out-of-bound skew) and decision predicates, and a gateway-failure control variant was
added; the oracle still judges only the listed attacks (stated in section 5). The two unfair-run "controls" of the
earlier audits that flip a flag with bare SQL are now rejected by design (I1.2).

After the review, the self-test found one more weakness of the suite itself: with the decision predicates in place,
no attack isolated the re-reading of response bytes (I5.6), so disabling it went unnoticed. Two attacks only that check
can catch were added (decision predicates also rewritten true over a degraded HEALTH; a PASS IDENTIFY whose bytes name
the other device). Building the first exposed a **verifier crash** on a response stored as text instead of bytes; the
verifier now fails closed per result and per run (an unevaluable record is a violation, Rule 0), with a declared
type-corruption attack.

## 10. Live VM validation (separate store; the ctl master database was not written)

Commands and logs: `results/acceptance-integrity-20261019/logs/vm-*`; store copy with `vm/SHA256SUMS` (DB and pcaps on
disk, gitignored); reports generated from a copy in `vm/reports/`.

| Step | Result |
|---|---|
| Host before (01:19Z) | 6.9 GiB free (8.2 GiB after removing this work's own temp stores), swap 6956/8192 MiB; both Witness VMs already running; goldens and `vigil` stopped, untouched. Below the 10 GiB restore threshold: no clone, restore or fresh-clone trial attempted |
| Preflight before | GREEN on field and ctl (01:22Z) |
| Deploy (`lab_vms.sh sync`) | both guests `git_sha=7fca791…`, `git_dirty=0`; device/gateway/fault-control code unchanged, no service restarted |
| Unit suite, witness-ctl (Python 3.12.3) | **391 passed** |
| Contract harness, witness-ctl | pytest **254 passed** (20 seeds); `verify_acceptance_contract.py --seeds 20`: **249/249 agree, 8/8 weakenings detected, PASS**; its temp stores removed |
| Baseline, first attempt | stopped at session setup (`unable to open database file`: the new store's directory did not exist); before any preflight, fault or run row. Directory created; rerun |
| Baseline (`suite baseline --db /var/lib/witness/acceptance-integrity/…`) | run 1: **11/11 passed**, preflight GREEN, finished clean, uncontaminated |
| Fault suite (same store) | run 2: **24/24 passed**, clean, uncontaminated, no evidence-gap warning |
| v5 records written live | plan rows 11 and 24, both `session/plan.json` indexed, decision predicates on 35/35 results, migration 5 applied at store creation |
| Acceptance on witness-ctl (copy) and on the Mac (fetched copy, hash `1a213213…` equal on both sides) | **21/24** on both: only A12/A14/A15 (no mutant or fresh-clone runs in this store); A13, A17, A20-A24 hold on live evidence |
| Report from a copy | run 1 COMPLETE 11/11, commissions dev-a and dev-b; no planned-but-missing instance; embedded audit 21/24 — agrees with the SQL above |
| Final verification's probes on this live store | the v5 append-only guard first refused the probe's deletions; with the guards dropped (as an adversary would) every FV-01 probe is rejected (A17/A20/A23/A24); FV-02: 11 required instances, dev-b listed with each missing one, report "PARTIAL 6/11", A18/A21/A23 reject |
| Postflight (01:37Z) | GREEN on both; no tcpdump, pytest, Witness timer, netem qdisc or fault nft table on either guest; guests 6.0/6.2 GiB free |
| Host after | 6.2 GiB free |

## 11. Completion gate

| # | Condition | Status |
|---|---|---|
| 1 | Latest independently reproduced defects corrected | FV-01 (all 3 reproductions and the 7 accepted gaps) and FV-02 (+ prose) rejected/corrected on real and synthetic stores |
| 2 | Every evidence dependency accounted for | contract I1-I11 with the source of each obligation |
| 3 | No false acceptance or rejection across the suite's cases | 329/329 (macOS), 249/249 (Ubuntu); controls exactly as declared |
| 4 | Removing parent records cannot make acceptance greener | parent/child deletions in every table, orphans with keys off, and 60 seeded deletion combinations on a genuinely failing store: never acceptable |
| 5 | Reference-valid data still passes | reference variants; real master 24/24; live store 21/24 with only the absent-history classes |
| 6 | Original audit reproductions | expected post-fix results; five intended differences explained (section 7) |
| 7 | Unit and affected integration tests | 685 macOS, 391 + 254 Ubuntu, live baseline 11/11 and fault suite 24/24 |
| 8 | Raw evidence, SQL and reports agree | ctl and Mac audits and the generated report agree on the live store |
| 9 | Separate skeptical review, findings addressed | 11 findings reproduced, declared, fixed, rerun with the reviewer's own probes; the fixes themselves were not re-reviewed |
| 10 | Lab clean | postflight GREEN, no residue (section 10) |

Commits: `913e10a` (final verification preserved verbatim), `b9c334f` (repair), `7fca791` (temp-store cleanup, the
deployed revision), and the record/evidence commit that follows. The last commit also corrects the wording of A18's
claim (text only; behaviour identical to the deployed revision).

## 12. Outstanding (not done here; required for full-project acceptance)

- **Independent verification of this repair**: not self-certified.
- **Five fresh-clone baselines on the current revision** (A14): the historical trials are `87d322b`, pre-v4 and pre-v5;
  host headroom (6.2-8.2 GiB) stayed below the 10 GiB restore threshold. Continue as in
  docs/independent-reaudit-remediation.md section 8 once `df -h /` shows >= 10 GiB.
- **Mutant campaign on the current revision** (A12): the master's mutant runs are `3a9bbbc`, pre-v5.
- **Interruption, dead-man and reset recovery** after this repair (`interrupt-selftest TERM f2`, `KILL f5`,
  `reset-selftest`, each followed by preflight): not executed. The session now records its plan before the first case;
  a run killed afterwards is unfinished (aborted), which the contract handles, but this was not exercised live.
- **Whole-case deadline scope for gateway/F12 cases**: unchanged and unverified (final verification section 7).
- **Fresh-VM reproduction** of the current revision.
- The master's evidence is all pre-v5: its completeness rests on the case directories (receipts), its pre-v4 trials on
  categories, and every pre-v5 pass on its verdict for the case's own predicates — stated limits, not certifications.

## 13. Reproduce

```sh
.venv/bin/python scripts/verify_acceptance_contract.py            # contract + matrix + combinations + self-test
.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit tests/contract tests/test_inventory.py
.venv/bin/python results/acceptance-integrity-20261019/real_store_audit.py results/witness.db results/evidence
.venv/bin/python results/acceptance-integrity-20261019/auditor-reruns/adversarial.py     # writes beside itself
# lab (preflight GREEN first; separate store, the master DB is not written):
scripts/lab_vms.sh suite baseline --db /var/lib/witness/acceptance-integrity/witness.db \
  --evidence-root /var/lib/witness/acceptance-integrity/evidence
```

