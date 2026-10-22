# F3 interrupted-run evidence omission repair

Status: **targeted repair COMPLETE and verified**. This is a bounded follow-up to
[independent-f3-verification.md](independent-f3-verification.md) at `f9dd5d6`, not full Witness acceptance.
Evidence directory: `results/f3-interrupted-evidence-20261020/` (E). Commands use the bounded `E/run.py`
recorder, retaining UTC start/end, arguments, timeout, exit status and output. All new execution is local synthetic
verification or read-only-backed historical-store verification, never new VM commissioning.

## Original failure and preserved reproduction

The unchanged `results/independent-f3-20261020/edge_probe.py` was executed before changing production code:
`E/logs/original-edge-red.log`. Its legitimate `aborted-detected` control passed 24/24. Deleting only interrupted
run K's canonical `session/environment.json` and its environment evidence-index row still passed **24/24**.
All **20 environment rows** remained. Run kind/status, checks, plans and results were unchanged; SQLite integrity
was `ok`, with no foreign-key violations. The script's broader unfair-run counterexample also falsely passed 24/24.

`E/preserve_counterexample.py` separately retains the decisive before-fix facts in
`E/counterexample-before-fix.json`: the complete run/environment/check/result/plan records, removed snapshot text
and index, and both complete 24/24 audits. The script intentionally asserts the old failure, and is not a green test.
Original independent-audit scripts, logs, manifests and report are preserved verbatim.

## Root cause and focused change

`contract._session_environment` exempted any unfair run with neither an index nor a physical snapshot. Its early
return ignored the already-loaded environment table. `_runs_checked` then skipped fair-run session cardinality
checks. A20's selected indexed-file checks could not restore an obligation that had disappeared with its index.

The helper now exempts only an **unfinished** session without any durable collection facts, snapshot or index.
Environment rows (even a single table-only clean flag), case results, session postflight or a recorded finish each
require the canonical session snapshot and index, independently of the index under validation. `_runs_checked`
passes result/postflight progress into the helper before excluding unfair, mutant or superseded runs. It reuses
the existing postflight calculation; no schema, writer, run-selection or architecture change is needed.

| Recorded situation | Contract behavior |
|---|---|
| Unfinished run, preflight/plan only, no environment/results/postflight/snapshot/index | Genuine precollection interruption permitted |
| Environment persisted, interruption before snapshot save/index, or later snapshot/index loss | A23 I1.7 rejects as unverified |
| Snapshot absent, index retained | A23 rejects unreadable file |
| Index absent, snapshot retained | A23 rejects missing canonical index |
| Both absent, environment or later lifecycle facts retained | A23 rejects missing canonical index |
| Snapshot/index hash, contents or database facts disagree | Existing F3 checks reject |
| Complete baseline/mutant or compatible historical session | Existing contract outcome preserved |

No missing contents are inferred or fabricated. A18 may still describe an older passing baseline when a newer run
is legitimately unfair; A23 rejects the **dataset** if that newer run lacks mandatory evidence. It cannot become an
accepted dataset through fallback. The acceptance contract now states this obligation explicitly.

## Test-driven verification

Before production changes, the new `tests/unit/test_interrupted_environment.py` suite produced **11 failed,
17 passed** (`E/logs/targeted-red.log`). After the fix, the focused old/new session suites produced **89 passed**
(`E/logs/targeted-green.log`). Coverage includes the exact audit counterexample and unchanged facts, each single
omission, both omissions, interrupted/newer failed runs, a newer unfair failure with older successful selection,
minimal persisted environment, results-only and finish-only obligations, rooted/rootless structural checks,
precollection interruption with a real plan and later detector, baseline/all six mutants, historical controls,
snapshot/index disagreement, report consistency and isolated weakening sensitivity.

`tests/contract/matrix.py` adds six declared I1.7 mutations covering snapshot/index/both omissions on the interrupted
and current-failure fixtures. The independent oracle already records the environment/evidence/file differences;
it needs no modification. `scripts/verify_acceptance_contract.py` adds a weakening that restores only the old unfair
run exemption, keeping all earlier F3 comparisons enabled. The targeted sensitivity test sees `FALSE_ACCEPT` under
that weakening and correct rejection after restoring the protection.

The **unchanged** auditor script after the fix (`E/logs/original-edge-green.log`) rejects both omissions with
**23/24, A23 I1.7**, while its unmodified interrupted control remains **24/24** and its original failed baseline
remains **22/24, A4/A18**. Twenty environment rows remain in each attacked run; original failing results are retained.

One separate read-only reviewer independently executed **32/32 probes**, exit 0 at 23:21:22–23:21:58 UTC
(`E/review/probes.py`, `E/review/probes.json`, `E/review/logs/independent-probes-final.log`). No reproducible finding
within this repair. The reviewer directly deleted both records with all other run facts unchanged, isolated each
durable obligation (including postflight checks and indexes separately), tested early interruptions and fallback,
kept all valid controls, and independently restored the old early return to recover 24/24 false acceptance.
Final reviewed source hashes were stable; `runner/contract.py` SHA-256:
`e49466e66f31e2c52047e744324fedb6534a1bb5f5e195ce2ff8affe859f5228`.
The first review run's exit 1 is retained: its final hash check observed a concurrent matrix section-comment edit;
all behavioral assertions had passed. The final frozen-source rerun above passed. Temporary review fixtures were
removed. The reviewer wrote only review evidence, not production or tests.

Executed checks (arguments after `.venv/bin/python -B E/run.py <log> <timeout>`):

| Command | Actual result |
|---|---|
| `.venv/bin/python -B -m pytest -q -p no:cacheprovider tests/unit tests/test_inventory.py` | **594 passed**, 284.32 s; `logs/unit-mac.log`, including affected SQLite schema/migration and report units |
| `.venv/bin/python -B E/verify_stores.py` | **PASS**, 19.25 s; `logs/retained-stores-reports-compatibility.log` |
| `.venv/bin/python -B scripts/verify_acceptance_contract.py --json E/verifier-full.json` | **401/401 OK**, **14/14 weakenings detected**, exit 0, 1638.2 s; `logs/verifier-full.log` |

The compatibility script opens original sources read-only and backs up into memory. Master remains **24/24**;
retained v5 store remains **21/24** with exactly its expected A12/A14/A15 omissions. Their reports embed exactly
the direct audits, and both latest baselines still commission both inventory devices. Applying the v4→v5 migration
twice in memory preserves every original table column and row, original migration records, integrity `ok` and
empty foreign-key checks. All original database/session/brief hashes remain unchanged.
The original F3 relabelled-baseline negative still rejects A23, preserving failing result rows and snapshot bytes.
New interrupted-omission reports also explicitly show A23/I1.7 violation, and their embedded audits equal direct
audits (`E/interrupted-missing-session-reports/`). No historical report is overwritten.

The full verifier ran once with its default 60 seeds per base: 9 controls, 272 declared mutations and 120 seeded
combinations. All six new omission mutations meet their A23 expectations. The new isolated weakening is detected
specifically by `F3 omission: aborted-detected missing snapshot and index` (one matrix expectation fails with
false acceptance). Disabling the whole original F3 comparison is detected by 40 mutations; duplicate-name parsing
weakening remains detected by three. No prior protection or negative expectation was removed or relaxed.

Final preservation passed (`E/logs/final-preservation.log`, `E/final-preservation.json`): no unexpected change among
13,608 initial tracked/untracked entries and the prior audit's 15,583 hashed entries; both original databases,
896 prior-audit session paths, symlinks and all 19 independent-audit artifact files retain their original hashes.
The reviewed production/test hashes still match. The observed verifier temporary fixture directory was removed.
Runtime: macOS Python **3.14.7**, SQLite **3.51.0**. Final resources: **6.8 GiB available**, swap
**10697.69/12288 MiB used** (`E/logs/resources-*-final.log`). No unrelated file was deleted to obtain space.

The scoped local commit contains the correction, regressions, harness, contract/ledger/this record and retained
audit/repair evidence. Its hash and clean Git status are reported in the final handoff; no push is authorized or
performed. Whitespace checks cover source, tests, docs and generated reports; raw command logs and the initial
ledger diff are preserved verbatim and excluded because their diagnostic/context lines may contain trailing spaces.
The exit gate is met: the unchanged omission reproduction rejects, valid controls keep their outcomes, the
adversarial verifier detects disabling the new protection, all targeted checks pass and the separate reviewer
found no reproducible defect. This closes this specific repair only.

## Preservation and boundaries

Initial `df -h /`: **8.4 GiB available**. `sysctl vm.swapusage`: **9349.12/10240 MiB used**. The declared `.venv`
and pinned `requirements-dev.txt` are used; no dependencies are installed. Heavy suites run sequentially.
`E/preservation-before.json` hashes tracked and pre-existing untracked inputs, including the independent F3 audit;
the audit's retained manifest additionally covers ignored historical databases and indexed evidence.

The verification establishes correspondence with durable surviving records, not authenticity against coordinated
rewriting/deletion of all lifecycle, environment, index and file facts. A plan precedes collection and alone cannot
prove collection happened. Rootless commissioning remains structural; full acceptance requires evidence bytes.
Historical pre-v5 missing mutant/build keys and the actual writer's table-only clean flag remain supported.

No VM, clone/restore, fault campaign, host route/firewall, credentials, unrelated project, `vigil`, deployment or
push is part of this repair. Previously outstanding Witness acceptance experiments remain separate and unexecuted.
