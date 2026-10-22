# Witness: remediation of the second independent audit (R-01, R-02)

Remediation window 2026-10-19T02:51Z to 03:35Z (UTC), one session, same Mac and the same two dedicated Lima VMs.
**This document does not say Witness passed independent acceptance.** The re-audit
(`docs/independent-reaudit.md`, verdict **FAIL**) and the first audit (`docs/independent-audit.md`, **FAIL**) are kept
unchanged; a fresh independent reviewer decides. Every claim below names a log under
`results/logs/reaudit-remediation-*` (UTC start/end, argv, output, elapsed time, exit code), a commit, or a store.

Evidence labels: **H** = macOS host on disposable copies or fixture stores (proves checker logic, not VM behaviour);
**VM** = executed on witness-ctl/witness-field; **DB** = SQL over a recorded store.

## 0. Starting state and preservation

| Item | Value |
|---|---|
| HEAD at start | `9f695e1`; working tree: the re-audit's ledger entry (`docs/implementation-state.md`), `docs/independent-reaudit.md`, `results/independent-reaudit-20261018/` (untracked), `.serena/` (tool state) |
| Audit material | committed **verbatim and alone** first: `cacfac7` (report sha256 `5ca4eb08fc0ae8426d0b325971ac78a520ec616676a57330e18ac62d33ae288b`, its ledger entry, 439 text evidence files). Its binary `audit-vm-evidence.tar` and `vm/*.db` stay on disk, now gitignored, never edited |
| Immutable / prior records | `PROJECT_BRIEF.md` `07a33a08…5baf`, `docs/independent-audit.md` `db8aa70e…4f3c`, `docs/independent-audit-remediation.md` `a8581ff0…c255`: equal to the re-audit's recorded hashes before and after this work |
| Master store | `results/witness.db` `f5f789eb…d6dc` (150 runs): opened only read-only or as copies; unchanged at the end (checked in every probe/verification log). The ctl master DB was not written |
| Host at start | 7.8 GiB free (`df -h /`), swap 9947/11264 MiB used, memory pressure level 2 |

Commits: `cacfac7` audit material; `12f027e` repair + tests + scripts; `aa9e193` host logs, regenerated reports,
README/requirements notes (**deployed** to both VMs, `git_dirty=0`); then this record, the VM evidence and logs, the
ledger update and `.gitignore` (no runner/device/gateway/test change after `aa9e193`).

## 1. Disposition of every re-audit item

| Re-audit item | Re-audit status | This remediation |
|---|---|---|
| R-01 P2: invalid environment evidence accepted (F-06 incomplete) | confirmed defect | **REPAIRED**, verified (sections 2, 6) |
| R-01 P2: conflicting duplicate run results accepted (F-06 incomplete) | confirmed defect | **REPAIRED**, verified (section 3) |
| R-02 P2: A17 accepts a missing guest capture-flow record / trusts `expected` | confirmed defect | **REPAIRED**, verified (section 4) |
| F-01, F-02, F-03 (original defect), F-04, F-05, F-07, F-08 | FIXED | unchanged code paths; regression intact (section 6) |
| F-03 scope: whole-case 30 s bound for fixture/GW/F12 work | scope limitation, not a measured defect | **OPEN, unverified** (section 8) |
| Five fresh-environment baselines on the repaired revision | NOT EXECUTED | **OPEN**: host headroom still inadequate (section 8) |
| Post-repair SIGTERM/SIGKILL interruption, dead-man, mature capture expiry, reset self-test | NOT EXECUTED | **OPEN**: not executed; fixture teardown unchanged by this repair (section 8) |
| Fresh-VM reproduction of the repaired revision | NOT EXECUTED | **OPEN** (section 8) |
| Holes of the same class found while repairing (section 5) | not in the report | **REPAIRED**, regression-tested |

## 2. R-01a: invalid environment evidence

**Reproduction (H, pre-repair).** The re-audit's unchanged scripts on disposable copies
(`reaudit-remediation-pre-audit-{acceptance-edges,db-counterexamples}-*`): `python` = TAB+LF, `chrony.offset =
offset_s=garbage` and `git_sha = not-the-run-revision` in run 150 each gave **18/18 HOLDS** with both devices
commissioned; the live predicate `bool(value.strip())` rejected the same value. Independent probes
(`reaudit-remediation-pre-acceptance-probes-*`) found more of the same class accepted: NaN offset, an offset outside
the preflight clock gate, another 40-hex `git_sha`, `git_dirty` contradicting the run row, a BLOB value, a garbage
kernel release, a field qdisc record without `field0`, an nft record without a table, `runs.kind`/device-build records
contradicting the run, a near-duplicate key (`'python '`), and a withheld firmware version for the stock control device
in a mutant run.

**Root cause.** A13 (`runner/analysis.py` before `12f027e`) tested `trim(value) = ''` (SQLite trims spaces only),
`LIKE 'offset_s=%'`, `NOT IN ('0','1')`; nothing compared `git_sha`/`git_dirty` with the run row or checked any other
representation; the per-device keys came from the `devices` table (the rows being audited). Commissioning trusted
the recorded C-ENVIRONMENT pass. The live case used a third, different predicate. Missing records failed; invalid,
contradictory and ambiguous ones did not.

**Correction.** `runner/evidence.py` `check_environment(env, run, inventory)` is the single definition, used by the
live C-ENVIRONMENT case (`tests/live/test_commissioning.py`), by `db.commissioning_gaps` (an invalid record is a gap:
"environment record invalid: ...") and by A13:
- required keys = `catalog.ENV_REQUIRED` expanded over the **inventory's** VMs and devices (15 keys);
- each value must be text (BLOB rejected) in one representation: kernel release, single printable line distro, Python
  version, 40-hex `git_sha` **equal to `runs.git_sha`**, `git_dirty`/`runs.clean_env` 0|1 **equal to the run row**,
  `offset_s=<±f> delay_s=<f> samples=<ok>/<n> server=<witness-ctl l2 address>` with `1 <= ok <= n` and, for a run
  recorded as clean, `|offset| < 0.1 s` (the preflight clock gate), qdisc lines covering `lab0` (+ `field0` on
  witness-field), an `nft` record with a `table … {` line, firmware `x.y.z`;
- other records of the same fact must agree when present (`runs.kind`, `mutant`, `device_build.<dev>` vs the run kind
  and mutant spec, `device_build.<dev>` vs `device_build.<instance>.witness-field`); two spellings of one key are an
  ambiguous duplicate;
- `fw_version.<dev> = unavailable (<CATEGORY>: …)` is listed as withheld; it is honest (not an A13 problem) only for
  the mutant device of a mutant run. In the live case a withheld version still fails C-ENVIRONMENT with attribution
  device, as before. Unfair runs are not evidence and are not checked by A13; they never commission.

Checked against history before wiring it in: all **135 fair runs** of the master store pass; only unfair runs 18 and
132 (infra, known) have problems; 18 fair mutant runs carry the legitimate withheld dev-a version.

## 3. R-01b: conflicting duplicate results

**Reproduction (H, pre-repair).** The re-audit's fixture (two extra run-150 C-ENVIRONMENT rows, fail then pass):
**18/18 HOLDS**, A18 silently used run 145. Probes: pass-then-fail order was caught by A4 only, fail-then-pass by
nothing; a device-level C-HEALTH conflict likewise; an identical pass duplicate and a run-level case recorded for a
device were accepted.

**Root cause.** `LATEST_FAIR` was `max(result_id)` per (case, device): the newest of two conflicting rows of the same
run hid the other, so the outcome depended on insertion order. `latest_complete_baseline` required exactly one result
per instance, so a run WITH a duplicate was skipped in favour of an older run. No assertion constrained cardinality.
`commissioning_gaps` itself was already correct (it names duplicates), but acceptance never looked at that run.

**Correction.** `LATEST_FAIR` = every result of the latest fair non-mutant run of the instance (both conflicting rows
are current, in either order; the traceability, fault and measurement report tables use the same definition and show
both). A18 evaluates the latest fair baseline that EXECUTED every required instance; one with duplicates is reported
**AMBIGUOUS** (report section 2) and its gaps name the duplicates. New **A19**: in every fair run each result is a
well-formed catalog instance (per-device case ↔ device set) and no instance has more than one result; rows are listed,
never merged or deleted. Q2's `runs` column counts distinct runs.

## 4. R-02: incomplete capture-flow evidence

**Reproduction (H, pre-repair).** The re-audit's deletion of the field flow record of run-146 FT-F3 and its
`expected=0, packets=0` rewrite: **18/18 HOLDS**. Probes: deleting the ctl side, retargeting the filter to the
gateway's port 5020, forging a "nothing sent" reason (ENETUNREACH on a CONN_REFUSED exchange, or no address after a
connect), deleting a current mutant run's records, and four byte-level tamperings (packets stripped from the capture
with the index re-hashed, a missing capture file, a hash mismatch, a capture not indexed) were all accepted; no
evidence root was needed at all.

**Root cause.** A17 required that SOME flow row exist for a latest result (`NOT EXISTS … f.result_id = r.result_id`)
and trusted the stored `expected` and `packets`; it did not derive which records the exchanges and the case's capture
contract require, and acceptance never looked at the capture bytes.

**Correction.**
- **A17** derives, for every CURRENT result (`analysis.current_evidence`: the latest fair result(s) of every case
  instance, every result of A18's baseline and of A14's counted trials, each mutant's latest valid run), the flows from
  ALL its attempts' exchanges with the same `runner/lab.dialled_flows` the recorder uses, and the captures from the
  case contract in `tests/live/conftest.py` (ctl capture always, field capture for fault cases). Every flow x capture
  needs a record with that filter (`lab.flow_record_filter`, now shared with the recorder) whose `expected` equals the
  derived value; a no-packet flow needs a reason consistent with the exchange's own classification (no address only
  after a failed or deadline-skipped resolve, ENETUNREACH only with NO_ROUTE, `not_started` only for a case-deadline
  cut); unaccounted records are listed. Whether a run is under the check comes from the migration record
  (`schema_migrations` v4 `applied_at`), not from which rows exist. Any fair run's expected flow with 0 packets is still
  listed. Legitimate F5 (NO_ROUTE) and F7-missing (RESOLVE_FAIL) records stay accepted, with their reasons.
- New **A20** verifies the bytes behind the current evidence: every indexed evidence file of a current result and the
  session files of its run exist with the recorded length and sha256, and every expected flow is recounted from the
  hash-verified ctl/field capture file by `evidence.flow_packets` (a classic-pcap parser of its own, Ethernet/SLL,
  IPv4/TCP, independent of tcpdump): present, and equal to the recorded count. Without an evidence root A20 is
  violated ("not verified"); `python3 -m runner.analysis` defaults to `<db dir>/evidence`, the report passes its root.

## 5. Holes of the same class found while repairing

| Hole | Pre-repair (probe) | Correction |
|---|---|---|
| Deleting dev-b (results, then its `devices` row) shrank every per-device requirement | 18/18, "commissions every inventoried device" with dev-a only | **A21**: `requirements`, `cases`, `case_requirements`, `faults` (id, catalog id, kind, prediction), `mutants`, `devices` must equal docs/requirements.md, the catalog and inventory.yaml; A18 names an inventoried device absent from `devices` |
| Deleting a case (C-GATEWAY) | A14/A18 failed only incidentally | A21 names the missing case and mappings |
| A result's `expected_category` rewritten to match its observation | A5 held | A5 also requires `r.expected_category = faults.expected_category` |
| A fault-case result with no recorded fault application | A9 held vacuously | A9 lists decided (pass/fail) fault results of fair runs without an application (none in history) |
| Report prose "A partial run commissions nothing" | wrong when only another device's instance is missing (per-device rule) | wording corrected; the rule (audit-accepted F-01) unchanged |

## 6. Verification

| Check | Command / evidence | Result |
|---|---|---|
| Probes before repair (H) | `acceptance_probes.py` on a copy of the master store + scratch evidence root, `pre-acceptance-probes-*` | **38 of 45 not rejected as required**: 32 fully accepted (18/18), 6 caught only partly (e.g. A13 without the commissioning consequence, A4 in one insertion order only); 7 matched (3 the old checker caught, 4 controls) |
| Audit scripts before repair (H) | unchanged `acceptance-edges.py`, `db-counterexamples.py`, `pre-audit-*` | reproduced exactly: 18/18 for whitespace env, conflicting duplicates, missing field flow |
| New regression tests vs pre-repair code (H) | `git archive 9f695e1` + only the new tests/fixtures + a keyword shim, `pre-fix-new-regression-tests-*` | **62 failed, 7 passed** (the 7 = controls: 4 unfair-run cases, partial-run fallback, legitimate no-packet F5/F7, superseded-run scope) |
| Probes after repair (H) | same script, `post-acceptance-probes-*` | **45/45 as expected: 41 rejected by the expected assertions, 4 controls held; master copy 21/21** |
| Audit scripts after repair (H) | unchanged, `post-audit-*` | whitespace env → A13+A18; conflicting duplicates → A4+A18+A19; missing field flow → A17; `expected=0` → A17; contaminated run 150 → nothing but A20 (their scripts pass no evidence root, so bytes are "not verified") |
| v3 compatibility (H) | unchanged `compatibility-probe.py`, `post-audit-compatibility-probe-*` | v3 DB audited read-only, bytes unchanged; only A17 (no v4 records) and A20 (no root) violated; v3→v4 migration twice preserves every row |
| Unit, macOS (Py 3.14.7) | `.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit tests/test_inventory.py`, `post-unit-mac-*` | **PASS 384** (279 before; +65 `test_acceptance_evidence.py`, +36 `test_evidence.py`, +4 commissioning) |
| Unit, witness-ctl (Py 3.12.3) | `scripts/lab_vms.sh unit` on `aa9e193`, `vm-unit-ctl-*` | **PASS 384** (tcpdump cross-check ran on both platforms) |
| Master store (DB, verified copy) | `verify_stores.py`, `post-verify-stores-*` | integrity ok, FK clean, v4, 150 runs; **21/21 hold** with byte verification (167 current results, 145 derived flows, 1,186 indexed files); **264/264** stored flow counts = independent recount = tcpdump |
| Audit's separate VM store (DB) | same | 18/21: A12/A14/A15 (no mutant/fresh-clone runs in it), as the re-audit classified; 58/58 recounts agree |
| Reports | `runner.report` + `runner.analysis --evidence-root` on a hash-verified copy, `post-regenerate-reports-*` | `results/reports/*` regenerated: 21/21; evidence re-hash still flags exactly the 24 disclosed F12 files; master DB hash unchanged |
| Deploy (VM) | `scripts/lab_vms.sh sync`, `vm-sync-*` | both guests `git_sha=aa9e193…`, `git_dirty=0`; changed files' sha256 equal to the Mac's; no service restarted (device, gateway, faultctl code unchanged) |
| Live baseline (VM) | `suite baseline --db /var/lib/witness/reaudit-remediation/…`, `vm-suite-baseline-*` | **11/11**, run 1 clean, uncontaminated: the new C-ENVIRONMENT validator accepts the real record |
| Live fault suite (VM) | `suite fault` same store, `vm-suite-fault-*` | **24/24**, run 2 clean, uncontaminated; 25/25 fault removals verified; 54/54 expected flows present (F3: 4 packets of 10.77.2.11:5021 in each capture); F12 early restart uptime +0.7 s, gateway recovery 1493.1 ms (bound 4000) |
| Acceptance on the new store | on witness-ctl `vm-acceptance-ctl-*`; on the Mac `post-verify-remediation-vm-store-*` | 18/21 on both (A12/A14/A15 absent classes); A13/A17/A19/A20/A21 hold on fresh VM evidence; 56/56 recounts agree |
| R-01/R-02 counterexamples on the fresh store (H on VM data) | `fresh_store_counterexamples.py`, `post-fresh-store-counterexamples-*` | all 7 rejected by the expected assertions; unmodified copy holds |
| Static analysis | `cc-sast --changed`, `post-cc-sast-changed-*` | 45 "formatted SQL" findings: SQL text built from code constants (`FAIR`, `LATEST_FAIR`, table names) with values bound as `?`/`json_each`; several pre-existing; none takes external input. Triaged not exploitable; no change |
| Lab state after (VM) | `vm-postflight-*` | preflight **GREEN** both (capture-idle, no-fault-deadman, no-fault-nft, qdiscs, stock builds, normal modes, routes, isolation, vsock); goldens Stopped |

## 7. Historical evidence under the stricter checks (reported, not rewritten, not gating)

The gating scope is the current evidence (section 4), as A4 already scoped "latest". `verify_stores.py` also runs the
same derivation over every superseded fair result (`post-verify-stores-grouped-*`) and finds only disclosed limits:
run 131's 8 flow records keyed address:port before `c335c84` (its capture bytes do hold the runner's own flows);
the 24 overwritten FT-F12 files of runs 133–138; 40 dialled flows absent from captures of runs 1, 37–69, 104, 107,
119, 128 (Phase-2 capture start-up and the pre-F-07 port-5020-only F3 filter); 81 Phase-2 fault results (runs 3–26)
recorded before field captures existed. None is rewritten or re-indexed.

## 8. Remaining blockers and exact continuation (OPEN)

- **Five fresh-environment baselines on the repaired revision: OPEN.** Host at the end: 9.4 GiB free, swap 7883/9216
  MiB, memory pressure level 2 (03:32Z); the restore procedure needs >= 10 GiB free plus margin and stable memory. No
  restore or clone was attempted. Continue only when `df -h /` shows >= 10 GiB and pressure is normal: follow the
  Phase 4 "Reproduce / continue" block of `docs/implementation-state.md` (`golden-restore --yes` deletes and re-clones
  the working VMs), then `provision`, `results-push`, `suite baseline` five times, `report`, `fetch`; A14 must then
  count >= 5 trials on the current revision.
- **Interruption/reset recovery after the repair: OPEN, NOT EXECUTED.** Fixture teardown, dead-man timers and reset
  paths were not changed by this repair. Continue with `scripts/lab_vms.sh interrupt-selftest TERM f2`,
  `interrupt-selftest KILL f5` and `reset-selftest`, each followed by `scripts/lab_vms.sh preflight` (must be GREEN).
- **Whole-case 30 s bound for fixture/GW/F12 work: OPEN, unverified.** The re-audit reported it as a scope limitation,
  not a measured overrun; the retry deadline repair stands; nothing here changes or tests it.
- **Fresh-VM reproduction of the repaired revision: OPEN** (same headroom requirement).
- The pre-repair probe set was run with the expectation `{A13, A18, A21}` for `ref_device_removed`; after analysis the
  expectation was corrected to `{A18, A21}` (deleting a device's rows leaves the environment rows intact, so A13
  correctly holds). Pre-repair the probe held 18/18 under either expectation.

## 9. Reproducing the verification

```sh
.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit tests/test_inventory.py
.venv/bin/python scripts/reaudit_remediation/acceptance_probes.py results/witness.db results/evidence /tmp/probes
.venv/bin/python scripts/reaudit_remediation/verify_stores.py /tmp/verify results/witness.db:results/evidence \
  results/reaudit-remediation-20261019/vm/witness-reaudit-remediation.db:results/reaudit-remediation-20261019/vm/evidence
.venv/bin/python results/independent-reaudit-20261018/acceptance-edges.py          # the audit's, unchanged
.venv/bin/python -m runner.analysis --db <copy of results/witness.db> --evidence-root results/evidence
# lab, after scripts/lab_vms.sh preflight is GREEN (separate store; the master DB is not written):
scripts/lab_vms.sh suite baseline --db /var/lib/witness/reaudit-remediation/x.db --evidence-root /var/lib/witness/reaudit-remediation/ev
```
