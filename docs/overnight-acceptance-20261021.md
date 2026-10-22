# Witness overnight acceptance execution — 2026-10-21

**Verdict: PARTIAL ACCEPTANCE — BLOCKED.** Functional commissioning, all catalog faults, six mutants,
deadline enforcement, interruption/dead-man/capture expiry, and reset/recovery were executed on real VMs.
Five independent fresh-clone baselines and fresh-VM reproduction remain **BLOCKED — INSUFFICIENT HOST RESOURCES**.
They were not attempted, and ordinary baselines are not substituted for them. Full acceptance is not granted.

This is Python device simulation with real TCP traffic between Ubuntu VMs, not hardware or embedded firmware testing.

## Revision, environment and evidence

- Initial HEAD: `592a481d4b1495c3a22953df0fcfc0d2a549b2c5`, branch `main`.
- First deadline repair and campaign: `872cf2956d8037b04f8e0bb9a12fd87a12cb6c03`.
- **Final tested code: `3d7a9f74c81f80a1a84f790f7aa01f5254e5aa0f`**, guest source stamps `git_dirty=0`.
  The final documentation/evidence commit changes no tested runtime code. Nothing was pushed or deployed externally.
- Mac: macOS 26.5.1 (25F80), arm64, 8 GiB RAM, Python 3.14.7. Lima 2.2.0/vz, private `.lima.nosync`.
  Guests: Ubuntu 24.04 arm64, kernel 6.8.0-134-generic, Python 3.12.3, pytest 7.4.4; 1 vCPU/1 GiB each.
  `witness-ctl` lab0 `10.77.1.10`; `witness-field` lab0 `10.77.1.20`, field0 `10.77.2.11/.12`.
  Vsock recovery access, isolation, route, services and raw clock offset were checked by actual pre/postflight.
- **E** below means `results/overnight-witness-20261021/execution-20261021T071813Z/`.
  Its `CHECKPOINT.md`, command logs, manifests and scripts preserve exact arguments, UTC start/end, timeout,
  exit status and elapsed time. `vm/current/` is the final functional campaign; `vm/current-interruptions/`
  contains the crash tests. Other stores preserve earlier controls, failures and repairs separately.
- The 23,628 KiB guest transfer retained 2,313 files. Archive SHA-256:
  `2269b46c41ad14d9a65a2549d40ccbba0e3c4574562e6f7b822f090f704b7cc7`.
  Binary DBs/pcaps/archive remain on disk under the repository's ignore rules; manifests and text evidence are retained.

## Completed execution and actual outcomes

| Activity on final code | Actual result | Evidence under E |
|---|---|---|
| Stock commissioning before/after mutants | **11/11 each**, current runs 1 and 9; both devices commissioned, no retries | `vm/current/reports/commissioning-report.md`, baseline logs |
| Full fault suite | **24/24**, run 2; 21 variants across F1–F13, all 11 categories; 25/25 verified removals | `vm/current/reports/fault-report.md`, `logs/current-faults.log` |
| M1–M6 sequential campaign | **6/6 caught** by fail/device on dev-a; zero runner/infra results and zero stock dev-b false alarms; every restore/postflight green | `vm/current/reports/mutant-report.md`, `current-mutant-invocations.json` |
| F12 cumulative HTTP delay | **error/runner**, not commissioning PASS; result persisted at 30,009.495 ms; partial exchanges retained; A23/A24 hold | `vm/deadline-current-split/`, integrity/postflight logs |
| Gateway/F5 cumulative HTTP delay | **error/runner**; result persisted at 30,013.153 ms; route restored; A23/A24 hold | `vm/deadline-current-gw-split/` |
| SIGTERM during F2 | Exact runner PID signalled after SIGSTOP and both active captures observed; exit 2; clean state +4.397 s, GREEN +5.659 s | `vm/current-interruptions/TERM-f2-events.json` |
| SIGKILL during F2 | Exit -9; ctl capture expired +58.950 s; field dead-man cleared fault/capture by +90.228 s; GREEN +91.880 s; orphan pcap 84,009 bytes retained | `vm/current-interruptions/KILL-f2-events.json`, orphan capture, `field-deadman.log` |
| SIGKILL during F5 | Actual route deletion, armed timer and both captures observed before kill; ctl capture expired +58.999 s; route restored/timer inactive +90.361 s; field capture expired +119.297 s; GREEN +120.906 s; orphan pcap 43,916 bytes retained | `vm/current-interruptions/KILL-f5-events.json`, orphan capture, `ctl-deadman.log`, `field-capture.log` |
| Emergency reset self-test | Deliberately dirty preflight **RED**, reset, both **GREEN**; exit 0 | `logs/current-reset-selftest.log` |
| Genuine later detector session | **11/11**; actual subsequent sessions corroborate both aborted KILL runs | `vm/current-interruptions/`, A23 |
| Final macOS unit/inventory suite | **599 passed**, 177.15 s | `logs/full-unit-mac-current.log` |
| Final Ubuntu focused checks | **128 passed**, including deadline, decision predicates and interrupted-session evidence | `logs/current-ubuntu-focused.log` |

The deadline remains configured at **30.0 s**. The measured error-row persistence above occurred 9.5/13.2 ms
later; this is recorded overhead, not an enlarged deadline or a claim of hard real-time precision. Setup/capture
startup and the observation/decision share the budget; bounded safety teardown and session startup are measured
separately. Whole pytest processes took longer because cleanup must finish after expiry. See protocol §7.

## Requirement-by-requirement evidence matrix

All rows below describe functional verification in the existing VMs. The separate fresh-environment obligations
remain open. Case predicates and thresholds were not weakened.

| Requirement | Required predicate and actual observation | Final evidence / remaining work |
|---|---|---|
| REQ-01 | Each inventory identity matches and IDENTIFY ≤500 ms; both baselines pass. Across all 96 independently decoded baseline exchanges, maximum latency **1.507 ms** | Current runs 1/9, C-IDENTIFY; captures and `requirement-crosscheck-current.json`; fresh repetitions still required by §7.3 |
| REQ-02 | F7 answers with dev-b's ID/serial at dev-a's name, classified WRONG_IDENTITY; fault run commissions nothing | Run 2 FT-F7-NAME-SWAP; independent response check; `final-guest-check.json` commissioned-by-run map |
| REQ-03 | HEALTH status ok/sensor true and ≤500 ms for each device | Runs 1/9 C-HEALTH, decoded response bytes |
| REQ-04 | Raw clock preflight green; ten READs/device within ±2 s; skew fault detected | Runs 1/9 C-READ-CLOCK, run 2 FT-F13-SKEW; **80** baseline READs independently checked across clock/series cases |
| REQ-05 | Ten increasing seq/nondecreasing timestamps per series, bracketed healthy uptime with no restart | Runs 1/9 C-READ-SERIES; `baseline-uptime-window-check.json` checks both HEALTHs and one journal PID per window; M2 and repeat-seq negatives |
| REQ-06 | Malformed/truncated/wrong-id and M3/M4/M5 classified MALFORMED; bounded completion with recorded results | Run 2 FT-F10 cases and mutants 5/6/7; no missing result; current A24 and deadline negatives |
| REQ-07 | 300 ms scoped netem → PASS_SLOW with latency; 3000 ms → CONNECT_TIMEOUT or post-handshake READ_TIMEOUT; F2 → READ_TIMEOUT | Run 2 FT-F6 variants/F2, qdisc/snapshot/packet evidence and measurements |
| REQ-08 | Restart HEALTH ≤10 s, gateway recovery ≤4 s, including early restart with rising uptime | Run 2 F12: first HEALTH **1.547 ms** after return (**524.620 ms** from command); gateway **1062.394 ms**; early HEALTH **1.182 ms**, gateway **1487.332 ms**, API observed **1579.025 ms**; uptime rose **0.421 s**, detected by elapsed-time rule |
| REQ-09 | Gateway unreachable ≤6 s with recorded detection; stock control healthy | Run 2 GW-F1/F5/F8: independently derived detections **1585.218–2353.897 ms**; C-GATEWAY passes in runs 1/9 |
| REQ-10 | Complete valid environment, source/build facts, qdisc/nft/clock and clean flag; session file/table correspondence | Every current run; A13/A23; 13 installed code/unit/inventory files checked against provisioning source; all guest Python source hashes match Mac |
| Brief §6.2/7.1/7.2 | Bounded retries, preserved first outcome, correct attribution and safe recovery | Current attempts/results, deadline negatives, three interruption probes, reset test; injected failures never commission |
| Brief §7.3/13 | **Five independent fresh-clone baselines**, distinct verified restores, all 11 instances, retry-free; report variability | **BLOCKED: 0 executed in this assignment.** Runs 1/9 are ordinary controls; historical `87d322b` clone trials are not current proof |
| Brief §7.4 | Each of six intended broken behaviors detected against stock control | Current runs 3–8, native payload/journal checks and generated catching-REQ table |
| Brief §8/9 | SQL analyses, traceability, commissioning/fault/mutant reports, SOP/RCA | Generated current reports; existing protocol/requirements/inventory/SOP/RCA preserved. Historical run-54 graceful-stop surprise remains historical evidence, not a newly invented prediction |
| Brief §13 | Reproduce from scratch on **fresh VMs** without destroying originals | **BLOCKED, unexecuted.** Existing VMs and all four goldens preserved |

## Acceptance and independent cross-check

The proper acceptance audit is **22/24** on both Ubuntu and macOS, with identical assertion records and report
embeddings. Only **A14 fresh baselines** and **A15 fresh-baseline stability** fail. No reduced baseline count or
other acceptance override was used. Current run 9 commissions dev-a/dev-b; runs 2–8 commission **none**.

The separate read-only checker uses SQL, raw JSON responses, file hashes and native `tcpdump`, independently of
the production audit's predicates. It verified **914 indexed files**, **129 derived flow records**, baseline
response/clock/sequence facts, all six actual mutant defects and gateway timings recalculated from saved API
records and monotonic marks. Missing-address/no-wire records remain explicit. See
`E/requirement-crosscheck-current.json`, `baseline-uptime-window-check.json` and `installed-source-check.json`.

Interruption and deadline stores are intentionally partial/negative: their overall audits do **not** pass.
Their coverage/history failures and error rows are preserved. A23/A24 hold for the final interrupted/timeout
records; no missing session evidence was fabricated. The full 401-case adversarial harness was not rerun:
acceptance implementation, verifier and contract fixtures remain unchanged from `592a481`; current unit checks
and real-store audits exercised the modified live writer and the retained F3 protections. No external reviewer
or sub-agent was used.

## Failures found, repaired and retained

1. On `592a481`, the prescribed zero/1.5 s whole-response F12 controls passed. Separately delaying HTTP headers
   and body by 1.5 s each (real upstream JSON unchanged, each wait below the socket timeout) produced **PASS after
   34.833 s body / 35.483 s case**, exposing the missing overall bound. `872cf29` applies one setup/body budget,
   records runner expiry before safety cleanup and retains partial F12 observations/connections.
2. The first repaired negative's partial-attempt detail did not use `case_deadline_exhausted`; A24 rejected NULL
   category versus completed PASS exchanges. `3d7a9f7` fixes only this marker and adds a contract-anchored regression.
   A full separate final-revision campaign was then executed. Earlier failing data/reports remain unchanged.
3. The first isolated baseline invocation failed before session creation because its DB parent did not exist.
   The directory was created and the baseline rerun. It is retained as a setup error, not a device failure or pass.

No genuine unresolved functional acceptance failure was observed on the final campaign. Fresh-environment
experiments remain unknown; this statement does not predict that they will pass.

## Resources, preservation and final state

Initial available disk **16.480 GiB**, swap **2202.38 MiB**. At campaign end disk **15.079 GiB**, swap
**2326.56 MiB**. Lowest observed available disk across all samples: **13.802 GiB**
(08:20:22 UTC, after shutdown and final checks). Final swap **2270.56 MiB**. Peak sampled swap **2487.50 MiB**; raw pressure level
2 during VM work, 1 after stopping; reported free-memory percentage 29–37% during VM work, 51% after stop.
No rapid swap escalation or timing-invalidating VM stall was observed. Both ordinary 10 GiB floor and bounded
serial workload were maintained. See `E/resource-summary.json` and original sample logs for exact times.

The ordinary **20 GiB clone/restore reserve never passed**. Each guest disk has 10 GiB logical capacity;
existing allocation and historical APFS clone behavior do not establish a generous peak dirty-write/restore
reserve here. No disk-heavy operation was attempted on an unsupported estimate. Neither VM images, snapshots,
caches, Docker/ARC21, simulator assets nor other projects were removed to make room.

Original tracked/untracked results, database copies, session evidence, audit reports and symlinks are checked
against the pre-execution manifest. The authoritative brief retains SHA-256
`07a33a088939c9cc59ef4dbbfb12706ad17431d9eb4d8b5353feafdcea555baf`. Four historical guest database hashes
match their pre-execution values. See `E/final-preservation.json` and `SHA256SUMS` for the completed seal.
Preservation passed for **15,879 initial paths** with only the explicitly recorded source/document changes;
the external console log grew by append only and retains its initial hashed prefix. **2,527 evidence files**
were sealed; the checkpoint, active preservation log and later Git logs are explicitly outside that seal.

Both protected working Witness VMs are **Stopped** (08:09:50 UTC); all four goldens stayed Stopped.
Before shutdown: stock/normal devices, gateway healthy 2/2, correct route/hosts/isolation, no active fault,
injector, capture, dead-man or test runner; full preflight GREEN. The unrelated `vigil` remained Stopped;
ARC21's twelve Docker services remained running. No host route/firewall change, unrelated process kill,
production-data change, deployment, push or publication was performed.

## Reproduce completed checks and resume blocked work

From the repository root (the acceptance command is expected to exit **1**, naming A14/A15):

```sh
E="$PWD/results/overnight-witness-20261021/execution-20261021T071813Z"
.venv/bin/python "$E/crosscheck.py" current
.venv/bin/python -m runner.analysis --db "$E/vm/current/witness.db" --evidence-root "$E/vm/current/evidence"
.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit tests/test_inventory.py
# Actual next step for the blocked experiments:
.venv/bin/python "$E/run.py" resume-resource-gate 180 .venv/bin/python "$E/host_snapshot.py" resume-resource-gate
```

Do not start the next block until available space is stably ≥20 GiB, with an evidenced peak-space reserve above
the 10 GiB floor and acceptable memory/swap trend. The following commands are **resume instructions, not executed
evidence**. Keep the originals protected: rename them aside while stopped; do not unprotect/delete them.

```sh
set -euo pipefail
export LIMA_HOME="$PWD/.lima.nosync"
R="$PWD/results/fresh-resume-20261021"; S="$R/store"; G=/var/lib/witness/fresh-resume-20261021
mkdir -p "$S"
cp -p "$E/vm/current/witness.db" "$S/witness.db"
cp -Rp "$E/vm/current/evidence" "$S/evidence"
r() { label="$1"; limit="$2"; shift 2; .venv/bin/python "$E/run.py" "resume-$label" "$limit" "$@"; }
r initial-space-guard 30 .venv/bin/python -c 'import os,subprocess;v=os.statvfs(".");assert v.f_bavail*v.f_frsize>=20*1024**3;assert int(subprocess.check_output(["sysctl","-n","kern.memorystatus_vm_pressure_level"]))<=2'
r preserve-ctl 60 limactl rename --tty=false witness-ctl witness-ctl-preserved-20261021
r preserve-field 60 limactl rename --tty=false witness-field witness-field-preserved-20261021
# If a protected rename is refused, stop and preserve it; never substitute deletion/unprotection.
for trial in 1 2 3 4 5; do
  # Re-measure resources before EACH restore; stop if the reserve/pressure gate fails.
  r "resources-$trial" 180 .venv/bin/python "$E/host_snapshot.py" "resume-resources-$trial" || break
  r "space-guard-$trial" 30 .venv/bin/python -c 'import os,subprocess;v=os.statvfs(".");assert v.f_bavail*v.f_frsize>=20*1024**3;assert int(subprocess.check_output(["sysctl","-n","kern.memorystatus_vm_pressure_level"]))<=2' || break
  r "restore-$trial" 1250 caffeinate -i scripts/lab_vms.sh golden-restore --yes || break
  r "provision-$trial" 600 scripts/lab_vms.sh provision || break
  r "mkdir-$trial" 30 limactl shell --workdir / witness-ctl -- sudo mkdir -p "$G" || break
  r "upload-$trial" 120 bash -o pipefail -c 'COPYFILE_DISABLE=1 tar --no-xattrs --no-mac-metadata -C "$1" -cf - witness.db evidence | limactl shell --workdir / witness-ctl -- sudo tar -C "$2" -xf -' _ "$S" "$G" || break
  r "baseline-$trial" 240 caffeinate -i scripts/lab_vms.sh suite baseline --db "$G/witness.db" --evidence-root "$G/evidence" --run-notes "fresh independent restore $trial" || break
  r "download-$trial" 120 bash -o pipefail -c 'limactl shell --workdir / witness-ctl -- sudo tar -C "$2" -cf - witness.db evidence | tar -C "$1" -xf -' _ "$S" "$G" || break
  cp -p "$S/witness.db" "$R/completed-trial-$trial.db"
  r "verify-$trial" 120 .venv/bin/python -c 'import sqlite3,sys;from pathlib import Path;from runner import analysis as A;p=Path(sys.argv[1]);c=sqlite3.connect((p/"witness.db").as_uri()+"?mode=ro",uri=True);c.row_factory=sqlite3.Row;t=A.fresh_trial_runs(c,"witness-ctl","witness-field");assert len(t)==int(sys.argv[2]);assert c.execute("PRAGMA integrity_check").fetchone()[0]=="ok";assert not c.execute("PRAGMA foreign_key_check").fetchall();assert not A.trial_problems(c,t[-1],root=p/"evidence")' "$S" "$trial" || break
done
.venv/bin/python -m runner.report --db "$S/witness.db" --evidence-root "$S/evidence" --out-dir "$R/reports"
.venv/bin/python -m runner.analysis --db "$S/witness.db" --evidence-root "$S/evidence" --json "$R/acceptance.json"
```

For fresh-VM reproduction, **after** those archives are verified and the original pair is still safely preserved,
stop and remove only that identified disposable pair, then run the README scratch procedure: `up`, `provision`
twice, `preflight`, `unit`, baseline and fault suites with a new isolated DB/evidence root, then copy/hash all
provisioning and execution evidence before cleanup. Use the same bounded recorder and repeat the resource gate;
do not destroy the preserved originals. The precise next lifecycle commands are:

```sh
r fresh-stop 180 scripts/lab_vms.sh stop
r fresh-space-guard 30 .venv/bin/python -c 'import os,subprocess;v=os.statvfs(".");assert v.f_bavail*v.f_frsize>=20*1024**3;assert int(subprocess.check_output(["sysctl","-n","kern.memorystatus_vm_pressure_level"]))<=2'
r fresh-disposable-destroy 180 scripts/lab_vms.sh destroy --yes
r fresh-up 1250 caffeinate -i scripts/lab_vms.sh up
r fresh-provision 1200 scripts/lab_vms.sh provision
r fresh-idempotence 600 scripts/lab_vms.sh provision
r fresh-preflight 200 scripts/lab_vms.sh preflight
r fresh-unit 600 scripts/lab_vms.sh unit
F=/var/lib/witness/fresh-reproduction-20261021
r fresh-mkdir 30 limactl shell --workdir / witness-ctl -- sudo mkdir -p "$F/evidence"
r fresh-baseline 240 caffeinate -i scripts/lab_vms.sh suite baseline --db "$F/witness.db" --evidence-root "$F/evidence"
r fresh-faults 360 caffeinate -i scripts/lab_vms.sh suite fault --db "$F/witness.db" --evidence-root "$F/evidence"
```

After each future experiment, retain its actual result and recovery evidence. Only verified execution of both
remaining activities, plus the final evidence cross-check, can change this report's blocked verdict.
