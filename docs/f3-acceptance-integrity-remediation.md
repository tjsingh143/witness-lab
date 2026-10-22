# F3 baseline-relabelling acceptance-integrity remediation

Status: **repair COMPLETE against the targeted verification gate**. This is the independent review's F3 finding, not the fault
catalog's wrong-port F3. Full Witness acceptance is not claimed. Started from clean HEAD `6bca0a3` on 2026-10-20;
the previous Claude session had left F3 open. No prior implementation or evidence was discarded.

Evidence directory: `results/f3-acceptance-remediation-20261020/` (E below). Every logged command has UTC start/end,
arguments, exit code and elapsed time through `E/run.py`. Synthetic references are test fixtures, not VM results.

## Reproduction and RED

Unchanged original: `results/independent-contract-remediation-20261020/review-probes/p3_baseline_relabelled_mutant.py`,
run through `E/run.py logs/original-f3-red 180 .venv/bin/python <script>`; log retained. It builds the original
`current-failure` fixture and backs up to disposable memory databases. All 19 original v5 triggers remain enabled.

| State | Acceptance | Selection |
|---|---|---|
| Original latest baseline B (run 14), degraded HEALTH on both attempts | 22/24; A4, A18 violated | A18 run 14 |
| `runs.kind='mutant', mutant_id='M5'` only | 23/24; A13 violated | A18 falls back to run 5 |
| Plus environment `runs.kind`, `mutant`, `device_build.dev-a` made consistent | **24/24 false acceptance** | A18 run 5 |

`integrity_check=ok`, no foreign-key violations; no evidence file/hash or result was changed. The hash-verified
session environment still says baseline. A4 excludes the reclassified run; A18 selects an older passing baseline.
The mutant history already has a valid M5, so the added mutant-labelled failure also satisfies its detection check.

Before changing production, the new regression suite was executed (`logs/targeted-red.log`): **38 failed, 9 passed,
1 deselected**. Failures include the original false acceptance, other kind changes, inconsistent metadata, missing
identity/REQ-10 fields, malformed/duplicate JSON and standalone commissioning. The deselected test deliberately
disables the new helper, which did not yet exist. Existing index-cardinality guards account for six passing negative
cases; three valid controls also pass. First post-change run: **48 passed** (`logs/targeted-green.log`). Additional
writer-format and mixed-run controls were then added without changing the negative expectations.

## Root cause and correction

`analysis.environment_violations` (A13) compared environment rows only against other mutable database records.
`contract._runs_checked` (A23) required a session environment index but did not read its contents. A20 checked file
hashes only for selected current evidence. Changing a baseline's kind and its redundant environment rows could thus
remove the failing run from A4/A18 without any assertion examining the contradictory preserved session facts.

`runner/contract.py` now loads all environment records and the relevant environment indexes in `_runs_checked`,
then calls `_session_environment` before excluding any run by kind or fairness. The helper enforces I1.7:

- Exactly one run-level `environment` index at `run-N/session/environment.json`; duplicate, retagged, reparented
  or cross-run paths reject. Every fair run needs it; an interrupted session that never wrote its environment does
  not. An existing environment of an unfair run is still checked.
- Read the bytes once, verify their length and SHA-256, then parse that same byte string with duplicate-name
  rejection (including JSON-escaped duplicate names). Only an object of text values is valid.
- Compare the complete snapshot map with the table, including source/provenance, firmware and build records.
  Compare recorded kind/source stamp/mutant/clean flag directly with the run row. Require identity and fair-run
  REQ-10 keys; v5 sessions and mutants require mutant/build keys.
- Preserve actual writer formats: `db.set_clean_env` adds `runs.clean_env` only to SQLite after collecting the
  JSON snapshot; the snapshot may omit that key. Early pre-v5 non-mutant files may omit mutant/build metadata.
  Every key they do record must agree. No schema or live-writer change is needed.

The shared run-contract path also gates root-aware standalone commissioning and reports. `runner/analysis.py`
updates A23's claim. `docs/acceptance-contract.md` states the source, I1.7 and exact boundary.

`tests/contract/matrix.py` adds reproducible F3 mutations consumed by both pytest and
`scripts/verify_acceptance_contract.py`; the script adds a deliberate disabling of `_session_environment`.
`tests/unit/test_session_environment.py` checks the original unchanged result/bytes, independent oracle deviation,
the declared mutations, standalone commissioning, valid controls, the real writer's table-only clean flag, early
historical formats and a legitimate mixed run. The oracle already projects the metadata and file hashes
independently; it required no change for F3.

The older `tests/unit/storefix.py` explicitly supplied environment dictionaries missing `runs.kind` and `mutant`.
They now record the live writer's fields with the appropriate baseline/fault/mutant kind; its baseline writer also
uses the actual table-only clean flag format. Three existing test modules pass the correct kind or preserve the
specific invalid stock-build case they test. The A18 wrong-firmware test now constructs that firmware observation
consistently in the session and table instead of also injecting a second, unrelated integrity defect. Its exact
expected A18 rejection is unchanged. No negative assertion or acceptance requirement was relaxed.

Duplicate-name mutations retain a complete otherwise valid snapshot with a contradictory first value and a matching
last value. An isolated last-wins parser weakening must therefore make those tests falsely accept, independently
of the full helper disabling. These are stronger fixtures than the initial RED duplicate objects with missing keys.

Changed files/functions:

| File | Change |
|---|---|
| `runner/contract.py` | `_runs_checked`, new `_session_environment` (shared acceptance/commissioning path) |
| `runner/analysis.py` | `ASSERTIONS` A23 claim |
| `scripts/verify_acceptance_contract.py` | `_weakenings` F3 check; `main` prints bounded-run stage progress |
| `tests/contract/matrix.py` | `build_matrix`, `relabel_run`, `session_edit`, `_erase_session_key`, `session_environment_findings` |
| `tests/unit/test_session_environment.py` | 58 focused regressions and controls |
| `tests/unit/storefix.py` | `env_ok`, `baseline`, `fault_run` fixture fidelity |
| `tests/unit/test_abort_corroboration.py`, `test_decision_predicates.py`, `test_evidence.py`, `test_acceptance.py` | setup corrected; existing assertions unchanged |
| `docs/acceptance-contract.md`, this record, `docs/implementation-state.md`, E | contract, completed state and retained verification/review evidence |

## Verification and independent review

Executed from the repository root with `.venv/bin/python` (macOS Python 3.14.7):

| Command (arguments after `E/run.py <log> <timeout>`) | Result |
|---|---|
| `.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit tests/test_inventory.py` | **563 passed**, 176.64 s; `logs/unit-mac-final.log`; loopback binding required sandbox escalation |
| unchanged original F3 reproduction script | **23/24, A23** after the three environment edits (was 24/24); run-only edit **22/24, A13/A23**; `logs/original-f3-green.log`; all 19 guards retained |
| `.venv/bin/python E/verify_stores.py` | **PASS**, `logs/retained-stores-reports-schema.log`; master **24/24**, v5 **21/24** (only A12/A14/A15); original hashes unchanged; reports equal direct audits; v4→v5 twice preserves every original table column and row, integrity OK/FKs empty |
| `.venv/bin/python scripts/verify_acceptance_contract.py --json E/verifier-full.json` | **395/395 OK**, **13/13 weakenings detected**, exit 0, 1178 s; 9 controls + 266 declared mutations + 120 combinations (60 seeds on each base); `logs/verifier-full.log` |
| `.venv/bin/python E/finish.py` | **PASS**, `logs/final-preservation.log`, `final-checks.json`; both original databases, all 152 session files and the brief unchanged; reviewed production hashes still match; verifier's temporary fixture tree removed |

The final 58 new unit tests cover 42 declared F3 mutations plus the unchanged-failure/hash check, three reference
controls, standalone commissioning, disabled-helper sensitivity, isolated duplicate-reader sensitivity, seven
actual-writer baseline/mutant formats, the early historical format and a legitimate mixed run. The complete
verifier consumes the same mutations alongside its original matrix and independent oracle.

Intermediate failures are retained, not counted as passes: `logs/unit-contract-mac.log` **51 failed, 855 passed,
17 errors** (socket sandbox restrictions plus the incomplete old synthetic environments); its contract harness
portion passed. `logs/unit-mac-unsandboxed.log` **19 failed, 543 passed**, run while the old fixture setup was still
loaded (all socket failures resolved). `logs/fixture-corrections.log` **1 failed, 232 passed**: the A18 wrong-fw
fixture had also made an inconsistent session/table pair. It now records the wrong firmware consistently; its
exact rejection assertion is unchanged. The final complete macOS unit run above passes after all corrections.

One separate read-only Codex reviewer, the same reviewer for the follow-up, independently executed **29/29** probes
(`review/independent-probes-final.log`, JSON and script retained), then **16/16** final test-only checks
(`review/final-test-followup.log`). No confirmed reproducible defect. It challenged excluded kinds, ambiguous and
misleading indexes, source metadata rewrites, unfair sessions, invalid/duplicate JSON and all six mutant controls;
checked all 150 historical and two retained v5 snapshots; and showed the original bypass returns when only the new
helper is disabled. The follow-up showed complete duplicate-key objects reject only with strict parsing, and used
AST comparison against `6bca0a3` to establish that every existing assert expression in the four touched test modules
is unchanged. Production hashes remained unchanged between reviews. Temporary review fixtures were removed.

Generated reports are in `master-reports/`, `live-v5-reports/` and `relabelled-baseline-reports/` under E. Their
embedded audits equal direct audits exactly; the valid real baselines still commission both inventory devices.
The relabelled fixture can still show older run 5 as a per-run passing baseline, but its commissioning and
acceptance reports explicitly show **A23 VIOLATED, I1.7**, including the preserved-session disagreement. That is a
rejected dataset, not project acceptance. `f3-preserved-failure.json` retains the original failing rows, session
content/hash and complete before/after assertions; no result or preserved session byte changed in the attack.

The new F3 weakening alone is detected by **36 mutations**, including the original failed baseline relabelled as
mutant/fault/mixed. The duplicate-reader weakening is detected by the earlier IC-02 case plus both new complete
F3 duplicate objects (**3 mutations**). These checks reject a deliberately weakened implementation; they do not
merely compare output with the production SQL. All 42 declared F3 mutations pass their negative expectations on
the actual implementation. The fixture oracle independently records the metadata and preserved file changes.

The targeted gate is met: the original F3 manipulation rejects; valid reference/legacy data retains its outcome;
the adversarial verifier detects removing the protection; all affected regressions pass; and the separate review
found no confirmed remaining F3 counterexample. The scoped local commit includes this record, the ledger,
implementation, regression/verifier changes and retained evidence. Its exact hash and working-tree status are
reported in the final handoff; no push is part of this repair.

Git whitespace validation covers source, tests, docs, generated reports and review artifacts. Raw pytest logs under
`E/logs/*.log` are excluded from that formatting check because pytest emits trailing whitespace in failure
tracebacks; the initial staged check flagged it. Their original bytes are retained rather than reformatted.

## Integrity boundary and remaining project work

Session bytes corroborate metadata while preserved. The index and its hash live in the same mutable database:
matching them proves correspondence, not authenticity. The snapshot has no signed run id/start/hostname or
contamination cause; its canonical path associates it with its run. A coordinated rewrite of the file, hash and
all corresponding metadata is outside the original evidence contract. Without an evidence root, standalone
commissioning checks structure only; full acceptance rejects absent byte verification. No cryptographic claim is made.

The historical master is schema v4; its older evidence/decision limits and the 24 disclosed historical F12
mismatches are preserved. Initial source hashes and environment-map compatibility checks are in
`E/source-preservation-initial.json`. Host initially: 6.2 GiB available, swap 10217.56/11264 MiB. All work is host-side;
no VM, guest preflight, fault campaign, restore/clone, host network change, deployment or push is performed.

Final resource sample (`E/resources-final.log`): **5.7 GiB available**, swap **9738.31/11264 MiB**. The full verifier's
temporary stores were verified removed. No unrelated file was deleted to gain headroom.

Five fresh-clone baselines, current-revision mutants, interruption/dead-man/reset experiments, gateway/F12 deadline
verification and fresh-VM reproduction remain separate, unexecuted acceptance activities. `vigil` is untouched.
