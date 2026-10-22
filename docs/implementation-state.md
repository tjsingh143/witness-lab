# Witness implementation state (handoff ledger)

PROJECT_BRIEF.md is authoritative and unchanged:
`sha256 07a33a088939c9cc59ef4dbbfb12706ad17431d9eb4d8b5353feafdcea555baf` (re-measured 2026-10-17T14:31Z; last changed in 38e51d5).

## Phase ledger

| Phase | Status | Date | Notes |
|---|---|---|---|
| 1. Spec, VM network, provisioning | **COMPLETE** | 2026-10-17 | Two real Ubuntu 24.04 arm64 Lima/vz VMs, routed device subnet, isolation, preflight/reset/smoke verified. |
| 2. Device MVP, runner, SQLite, MVP faults | **COMPLETE** (scope limits below) | 2026-10-17 | Devices on witness-field, runner on witness-ctl, F1/F2/F6/F7/F10 live on the VMs, report from SQLite. Final evidence runs 20–24 on commit `06c92aa`. |
| 3. Gateway, all F1–F13, recovery | **COMPLETE** (scope limits below) | 2026-10-17 | Gateway on witness-ctl, all 13 catalog faults live with evidence, REQ-08/09 measured. Final evidence runs 64–67 on commit `4f2b2b0`. |
| 4. Repeated clean trials, mutants, docs, audit | **COMPLETE** (limits below) | 2026-10-17 | Six mutants live (6/6 caught), five+one fresh-clone baselines, from-scratch VMs, SQL analyses + 15 acceptance assertions, SOP/RCA/README/lab record. Final code `633df97`; final evidence runs 118–130. |
| Independent audit | **FAIL** (external) | 2026-10-17 | `docs/independent-audit.md` (GPT-6 Astra, kept verbatim, `3c8de6c`): one P1, six P2, one P3 (F-01..F-08). The Phase 4 claim "no mandatory item is FAILED or UNVERIFIED" was wrong. |
| Audit remediation | **REPAIRED, awaiting re-audit** | 2026-10-18 | All eight findings corrected with regression tests and post-fix evidence (`docs/independent-audit-remediation.md`). Code `0943fd5`; evidence runs 131–150 (132 infra). Not independently re-accepted. |
| Independent post-remediation re-audit | **FAIL** | 2026-10-18 | `docs/independent-reaudit.md`: seven original counterexamples fixed; F-06 remains incomplete, with confirmed false-green acceptance and capture-completeness defects. Independent units 279/279 on each platform, baseline 11/11, faults 24/24. Current fresh-clone and interruption/reset verification outstanding. No implementation repair. |
| Second-audit remediation (R-01/R-02) | **REPAIRED, awaiting independent review** | 2026-10-19 | `docs/independent-reaudit-remediation.md`: environment validation, result cardinality, derived capture-flow coverage and byte verification (A13/A17/A18 rebuilt, A19-A21 added); 45/45 adversarial probes as expected (41 rejected by the right assertions, 4 controls held) and the audit's unchanged scripts' counterexamples rejected; units 384/384 Mac and ctl; live baseline 11/11 and faults 24/24 on `aa9e193` (separate store). OPEN: five current-revision fresh baselines, interruption/reset, whole-case deadline scope. Not independently accepted. |

Phase 2 scope limits (honest, not hidden): REQ-08 and REQ-09 need the gateway (Phase 3), so the
traceability report flags them as gaps. The single-retry path is unit-tested only: no live case was
ever non-PASS on its first attempt, so no live retry happened. The golden-clone restore procedure is
written but not executed (it deletes a working VM).

## Host facts

- macOS 26.5.1 (25F80), arm64, 8 GiB RAM. Free disk **17 GiB** at the end of Phase 2 (it fluctuates with
  macOS purgeable space: 10 GiB at Phase 2 start, 16–17 GiB later). `.lima.nosync` holds the two lab VMs
  (~2.3 GiB allocated each) plus two APFS copy-on-write golden clones (~0 extra, measured with `df`).
- Lima **2.2.0**. No UTM, shellcheck or qemu on the Mac (shellcheck 0.9.0 runs in witness-ctl).
- Unrelated Lima instance `vigil` in `~/.lima` untouched. No 10.77 routes/interfaces on the Mac.
- Repo `.venv` (pyenv 3.14.7): pyyaml 6.0.3, pytest 9.1.1. Guests: Python 3.12.3, pytest 7.4.4, SQLite 3.45.1.

## Decisions (current; Phase 1 decisions 1–10 still hold)

1–10. See Phase 1 (unchanged): Lima vz, private LIMA_HOME, eth0 mgmt + lab0 static, addresses, vsock
      management, isolation, clock hierarchy (ctl guest agent → field chronyd), `witness_fault*` naming,
      protocol v1, F5 prediction NO_ROUTE.
11. **Runner on witness-ctl as root** (tcpdump, F7 edits `/etc/hosts`). Live tests refuse to run unless the
    host is the inventoried witness-ctl (lab0 MAC + hostname + VM + root).
12. **Control channel ctl → field = SSH over lab0** with a dedicated ed25519 key to user `witness-fault`,
    `authorized_keys` = `restrict,from="10.77.1.10",command="/usr/local/sbin/witness-fault-ssh"`, which runs
    `sudo -n witness-faultctl <words>`. faultctl re-asserts identity and allow-lists every word.
    `lab_vms.sh link` copies only public keys via the Mac.
13. **One fault at a time**, each `apply` arms a 90 s transient dead-man timer (field:
    `witness-fault-deadman` → `witness-faultctl reset deadman`; ctl F7: `witness-ctl-fault-deadman` →
    `reset_lab.sh --role ctl`). Revert disarms once clean. SIGTERM to the runner unwinds through the
    fixtures (one-shot handler); SIGKILL is covered by the dead-man.
14. **F6 scope**: netem on field `lab0` egress via `prio bands 4` + `flower` (src 10.77.2.0/24, sport 5020),
    optionally `tcp_flags 0x0/0x2` (post-handshake only). SSH/chrony are not delayed (chrony would
    otherwise be stepped by the asymmetric delay). preflight/reset treat `netem|tbf|prio` as fault qdiscs.
15. **Fault modes** (F10) are runtime-only: root writes `/run/witness-fault/device-<i>.mode` (root-owned
    0755 dir, written with O_NOFOLLOW) and SIGHUPs the device, which confirms in its own
    `/run/witness-device-<i>/state.json`. `ExecStartPre=+rm` clears the mode on every start. (Moved out of
    the device-owned directory after a security review: confused-deputy symlink risk.)
16. **Verdict ≠ category.** results stores expected/observed/first-attempt category, verdict and
    attribution independently. Schema CHECKs: verdict pass ⇒ attribution none; attribution device ⇒
    preflight green; observed ∈ the 11 categories or NULL. A red session preflight records every case as
    `error/infra` without probing; a red per-case precheck triggers a reset and `error/infra` if still red.
17. **Commissioning** comes only from a finished, clean, uncontaminated **baseline** run in which every
    commissioning case passed and no WRONG_IDENTITY was observed (`db.commissioned_devices`). Fault runs
    never commission. A run that never finished is marked contaminated/aborted by the next session.
18. **detection_ms** (runner level) = fault confirmed applied (faultctl returned) → attempt classified.
19. **git provenance**: `lab_vms.sh sync` writes `.witness-source` (sha, dirty excluding `results/`, Lima
    version) because the guest copy has no `.git`.
20. **SSH host keys pinned across boots**: `ssh_deletekeys: false` (Lima changes the instance-id every boot).
21. **Golden clones** `witness-{ctl,field}-golden` (stopped; never start alongside the originals: same lab0 MAC).

## Files (Phase 2)

| File | Purpose |
|---|---|
| `device/device.py`, `device/witness-device@.service` | device simulator + systemd template (Type=notify, DynamicUser, graceful stop) |
| `runner/classify.py` | strict frame/schema parsing, 11-category classifier, protocol constants |
| `runner/client.py` | bounded resolve/connect/read client (Observation = facts only) |
| `runner/cases.py` | attempts, single retry (flake = fail), verdict/attribution decision |
| `runner/catalog.py` | case ↔ REQ (M:N) and fault catalog with predicted categories |
| `runner/db.py` | schema v1 + migrations, inserts, `commissioned_devices`, `mark_aborted_runs` |
| `runner/lab.py` | ctl identity guard, FieldCtl SSH client, quick checks, Capture (tcpdump), F7 HostsSwap |
| `runner/report.py` | Markdown report: runs, commissioning, traceability, faults, Q1–Q6, env, known problems |
| `scripts/faultctl.py`, `scripts/witness-fault-ssh` | field fault agent + forced-command wrapper |
| `tests/unit/*` | 142 unit tests (incl. 21 inventory tests from Phase 1): classifier, client with loopback fakes, device, DB, verdicts, report |
| `tests/live/*` | live suite: session/case fixtures, `inject` fault fixture, 9 commissioning + 9 fault tests |
| `pytest.ini`, `tests/conftest.py` | markers, `--live` gate |
| changed: `scripts/{lab_vms,provision_field,provision_ctl,preflight,reset_lab}.sh`, `scripts/lib/guest_common.sh` | device/agent provisioning, link/unit/suite/report/fetch/interrupt-selftest, new checks, fixes |
| `results/reports/commissioning-report.md` | generated report (final) |
| `results/evidence/run-N/...` | text evidence (pcap text, journal, snapshots, command logs); `*.pcap` and `witness.db` are gitignored |

## Tests run (real; logs in `results/logs/`)

| Test | Result | Evidence |
|---|---|---|
| Lab revalidation at Phase 2 start (status + preflight both VMs) | PASS GREEN | `phase2-initial-status-preflight-*` |
| `compileall` + unit tests, Mac (Py 3.14 / pytest 9.1.1) | PASS 142 passed, 18 live skipped | `phase2-final-unit-mac-*`, rerun after every fix |
| `compileall` + unit tests inside witness-ctl (Py 3.12.3 / pytest 7.4.4) | PASS 142 | `phase2-final2-unit-guest-*` (one earlier FAIL was a root-owned pycache dir, harness only: `phase2-final-unit-guest-…054542Z`) |
| shellcheck 0.9.0 on all shell scripts (in witness-ctl) | PASS rc=0 (after fixing SC2086/SC2034) | `phase2-shellcheck-…054207Z` |
| Provisioning (devices, agent, key link) and idempotent rerun | PASS (rerun: nothing changed, no restarts) | `phase2-provision-*`, `phase2-final-provision-idempotent-*` |
| Hand `nc` sessions ctl → dev-a/dev-b over the route; error replies | PASS | `phase2-device-smoke-*` |
| Forced-command allow-list (`id`, injection attempts, bad mode/instance) | PASS all refused | `phase2-device-smoke-*` |
| Service restart (Type=notify, graceful SIGTERM 95 ms, seq/uptime reset) | PASS | `phase2-device-restart-*` |
| Reboot persistence (full stop/start, no re-provision): services up, preflight GREEN | PASS after each of 4 stop/starts (05:42, 05:52, 05:54, 05:58Z); the ctl→field SSH channel failed after the 05:52 one until the host-key fix | `phase2-reboot-*`, `phase2-golden-*`, `phase2-reboot2-hostkeys-*` |
| Control channel survives reboot without re-link (after host-key fix) | PASS (run 19) | `phase2-reboot2-hostkeys-*` |
| Live baseline suite (9 cases) | PASS: runs 1,2,8–10,13–15,19,20–22 all 9/9; **run 18 ERROR 9/9 infra** (host-key change, see defects) | `phase2-*suite-baseline*` |
| Live fault suite (9 cases) | PASS: runs 3,4,11,12,16,17,23,24 all 9/9 | `phase2-*suite-fault*` |
| Final evidence set on `06c92aa` | PASS: baseline 20–22, fault 23–24, clean_env=1, contaminated=0, final preflight GREEN | `phase2-final3-*` |
| Interrupt: SIGTERM mid-F2 | PASS: revert verified at +1 s, run finished, result error/runner | `phase2-interrupt-TERM-…053822Z` (first attempt …053747Z exposed the double-signal issue) |
| Interrupt: SIGKILL mid-F2 | PASS: dead-man SIGCONT at +90.9 s, preflight GREEN; run 7 marked aborted | `phase2-interrupt-KILL-*` |
| reset-selftest incl. SIGSTOP, device mode, prio+netem | PASS 3/3 + final (two earlier FAILs found bugs, below) | `phase2-reset-selftest-x3-*`, `phase2-final2-reset-selftest-*` |
| Fail-closed PID / one-fault rule | PASS all refused | `phase2-failclosed-pid-*` |
| Planted-symlink check for the mode file | PASS (root never followed it) | `phase2-modefile-symlink-check-*` |
| EOF vs RST packet evidence (loopback on ctl kernel) | PASS 4 patterns | `phase2-eof-vs-rst-loopback-*` |
| SQL over persisted records (runs, results, attempts, exchanges, checks, evidence, fault_events) | PASS | report + queries in this session |

### Observed fault results (final runs 23 and 24; all runs agree)

| Fault | Predicted | Observed | Timing (run 24) | Packet evidence |
|---|---|---|---|---|
| F1 stop | CONN_REFUSED | CONN_REFUSED | connect 0.4 ms | SYN → RST |
| F2 SIGSTOP | READ_TIMEOUT | READ_TIMEOUT | connect 1.0 ms, wait 2.0 s | full handshake + request ACKed, no reply; after SIGCONT reply → ctl RST |
| F6 300 ms (incl. SYN-ACK) | PASS_SLOW | PASS_SLOW | connect 304.6 + response 303.5 = 608.4 ms | netem counters: only device packets delayed |
| F6 3000 ms (incl. SYN-ACK) | CONNECT_TIMEOUT | CONNECT_TIMEOUT | 1006.8 ms | SYN, SYN retransmit at +1 s; later SYN-ACK → RST |
| F6 3000 ms post-handshake | READ_TIMEOUT | READ_TIMEOUT | connect 0.3 ms, 2.0 s | request retransmits, delayed response → RST |
| F7 hosts swap | WRONG_IDENTITY | WRONG_IDENTITY (`device_id,serial`) | 2.5 ms | dialled 10.77.2.12 |
| F10 malformed / truncated / wrong-id | MALFORMED | MALFORMED (`bad_json` / `truncated:eof:43B` / `wrong_id`) | 2–4 ms | truncated: 43 bytes then FIN |

No observation contradicted a prediction. The protocol.md §7 F6 prediction (SYN-ACK also delayed) was
confirmed and recorded there. F4/F5 predictions remain for Phase 3.

## Defects found and fixed in Phase 2 (each from real evidence)

1. tcpdump captured 0 packets in sub-second cases → `--immediate-mode` (run 1's 8 empty pcaps kept; the
   report's evidence-integrity query lists them).
2. F6-3000 half-open SYN-RECV connection leaked a retransmitted SYN-ACK into the next case's capture (run 3)
   → `revert netem` drains SYN-RECV (≤ 8 s) and the field quick check fails on any.
3. Device closed with unread data → RST could destroy the `frame_too_long` reply → bounded lingering close.
4. `reset_lab.sh` never SIGCONTed a stopped device: `xargs -I{}` unescaped the cgroup path's `\x2d`.
5. `tc … | grep -q` under pipefail raced SIGPIPE: the prio+netem tree survived one reset → capture first
   (same fix in two preflight checks).
6. Runner SIGTERM delivered twice (pkill + `timeout`), second interrupt hit teardown → one-shot handler;
   interrupted results now say why.
7. Root wrote the fault-mode file into the device-owned RuntimeDirectory (symlink confused deputy, found
   by an automated security review) → root-owned `/run/witness-fault`.
8. Field SSH host keys regenerated every boot (Lima instance-id) → run 18 infra RED → `ssh_deletekeys: false`.
   The first reboot test had hidden this because `provision` re-ran `link` afterwards.
9. Aborted runs were re-marked by every later run (run 7's notes repeat 11 times in the DB; history kept).
10. Smaller harness issues: guest pycache dir permissions, `git_dirty` counted untracked `results/`,
    `lab_vms.sh suite` word-split extra args (one rc=4 usage error, log kept).

## Lab state at the end of Phase 2 (superseded by the Phase 3 section below)

Both VMs Running (ssh=vsock), provisioned at `06c92aa`, preflight **GREEN** (05:59Z), no faults active,
no dead-man timers armed, device services `witness-device@a/b` active. Golden clones
`witness-ctl-golden`, `witness-field-golden` exist and are **Stopped** (must stay stopped while the
originals run). Results DB and evidence on ctl: `/var/lib/witness/results/` (copied to `results/` on the Mac).

## Risks / open items (end of Phase 2; see Phase 3 below for the current list)

- Phase 4 still owes "five clean baseline runs **from a fresh environment**" (golden restore) and the
  flake analysis; 12 clean baseline runs exist, Q2 (flakiness) is empty, but none started from a restored clone.
- The live retry path has never been exercised on the VMs (no first-attempt failures occurred).
- Golden restore procedure (docs/lab-record.md §11) is untested; after a restore, run `lab_vms.sh link` if
  field's host key differs from the pin.
- `detection_ms` is runner-level only; REQ-08/09 gateway detection is Phase 3.
- netem filter assumes no IP options (flower parses headers properly; fine for this lab).
- Disk: re-check `df -h /` before large captures or extra clones.

## Phase 3 handoff as written at the end of Phase 2 (done; kept for history)

1. `scripts/lab_vms.sh status` (both Running, ssh=vsock; golden clones Stopped), `scripts/lab_vms.sh preflight`
   (expect GREEN incl. `service-a/b`, `device-mode-a/b`, `listen-*`, `no-fault-deadman`).
2. Sanity: `scripts/lab_vms.sh unit` (142 pass), `scripts/lab_vms.sh suite baseline` and `suite fault` (9/9 each).
3. Gateway on witness-ctl (`gateway/gateway.py`, `witness-gateway.service`): reuse `runner/client.py` and
   `runner/classify.py` for polls (P = 2.0 s, per-device attempt ≤ 4 s, concurrent per device), monotonic
   timing. Add cases for REQ-08 (F12 restart; `systemctl restart` returns after bind because the unit is
   Type=notify) and REQ-09 (F1/F5/F8) to `runner/catalog.py`; the traceability gaps then close.
4. New faults go through `witness-faultctl` (add allow-listed `apply/revert` verbs; nft tables must be named
   `witness_fault*`; arm the dead-man; one fault at a time) or, on ctl, a reverting helper like `HostsSwap`
   with the ctl dead-man. F11/F13 need new device modes: add them to `MODES` in device.py and faultctl.
5. Write F4/F5 predictions into docs/lab-record.md with timestamps **before** running them.
6. Keep `inject` teardown semantics (snapshot → revert → verify → contaminate+reset if unverified) and
   per-case capture; after delayed-SYN-ACK style faults, drain half-open connections (see faultctl `half_open`).
7. Regenerate the report (`lab_vms.sh report && lab_vms.sh fetch`), update this ledger, commit.

## Phase 3 (COMPLETE, 2026-10-17)

Two sessions. Session 1 (06:05–06:40Z) verified the Phase 2 state (runs 25/26), committed the F4 prediction
(`fe85e80`, 06:19Z, before any F4/F5 code existed) and wrote most of the code; it stopped at a usage limit with a
handoff (`f744803`). Session 2 (09:01–11:45Z) finished, deployed and debugged on the VMs. Code: `4f2b2b0`.

### Decisions (Phase 3)

22. **Gateway = installed copy** (`/usr/local/lib/witness-gateway`: gateway/ + runner classify/client + inventory
    loader; inventory `/etc/witness/inventory.yaml`), restarted by provisioning only on change, like the devices.
    DynamicUser, 127.0.0.1:8080, Type=notify. It reuses the runner's client/classifier, so it has the same 11 categories.
23. **Polling** (protocol.md section 10): per-device thread, fixed-rate slots t0 + k·2 s on CLOCK_MONOTONIC, missed
    slots skipped, one connection per poll (IDENTIFY/HEALTH/READ) with a 4 s poll deadline, so detection ≤ P + 4 s =
    3P. No hysteresis: 1 failed poll = unreachable, 1 good poll = recovered. Restart = HEALTH uptime decreased
    (resets the freshness baseline). requirements.md got a dated correction of its "4 s fits in one interval" rationale.
24. **REQ-08/09 references** (all ctl CLOCK_MONOTONIC, shared by runner and gateway): REQ-09 detection and revert
    recovery measured from the command being *sent* (upper bound, never negative); REQ-08 from `apply restart`
    *returning* (as defined) and also from sent; both must be within bound. Gateway-observed cases are recorded
    with `attempts=0` and `decide_observed()`; the gateway is part of the system under test, so a violated
    bound is `device`.
25. **Schema v2** (compatible migration): `measurements` (name, value, unit, bound, clock, detail per result) and
    `exchanges.local_port` (ties an established exchange to its packets; connect-stage failures have none).
26. **Fault realisations**: F3 = runner's inventory copy only (no VM change; `gateway --once` cross-check); F4 =
    faulted inventory → ctl managed hosts block remapped to 10.77.2.13 (ctl dead-man); F5 = ctl route delete (ctl
    dead-man); F8/F9 = nft tables `witness_fault_{drop,reject,reject_data}` on field input, matching only lab0 + dev-a
    address + port (field dead-man); F11/F13 = runtime device modes; F12 = one-shot `apply restart`.
27. **Per fault case evidence**: ctl lab0 + field lab0 captures (field via transient unit, RuntimeMaxSec=120), field
    and ctl snapshots while the fault is applied, field SNMP counters (F4/F8/F9), device + gateway journals,
    apply/revert JSON, `timing.json`, command log; all registered in `evidence` with sha256.
28. **Clock fix**: ctl chronyd (-x) runs without a driftfile; preflight `clock-served` asserts the time ctl serves equals
    its system clock (< 10 ms). Field's SNTP gate alone could not see the served-time drift (lab-record section 13).
29. **Live runs wrapped in `caffeinate -i`** on the Mac (no settings changed; blocks idle sleep only while the
    command runs) after host sleep produced a real STALE_DATA window.
30. **GW cases assert the steady-state category** (a poll that started after the fault was confirmed applied) and
    record the transition poll's category in the detail (run 54: graceful-stop window gives CONN_RESET).

### Files (Phase 3)

| File | Purpose |
|---|---|
| `gateway/gateway.py`, `gateway/witness-gateway.service` | gateway (poller, state machine, API, `--once`) |
| `scripts/faultctl.py` | + nft drop/reject/reject-data, restart, modes close-after/reset-after/clock-skew/repeat-seq, capture, counters, stale-connection drain, checks `no-stale-conn`/`capture-idle` |
| `device/device.py` | + F11/F13 modes (`MODE_RE`, FIN vs SO_LINGER-0 RST close) |
| `runner/{client,classify,cases,db,catalog,lab,report}.py` | read_s per exchange + local_port; `decisive`, `decide_observed`; schema v2; F3–F13 catalog + cases; RouteDelete, FieldCapture, Gateway client, ctl snapshot; report coverage + measurement sections |
| `tests/live/{conftest,test_faults,test_gateway_cases}.py` | Injector (early revert), new fault kinds and cases, C-GATEWAY, GW-F1/F5/F8, FT-F12 |
| `tests/unit/test_gateway.py`, `tests/unit/test_{device,db_cases}.py` | 16 new unit tests (158 total) |
| `scripts/{provision_ctl,preflight,reset_lab,lab_vms}.sh` | gateway install, no ctl driftfile, `clock-served` + gateway checks, capture reset, `gw`, `interrupt-selftest … f5` |
| `docs/protocol.md` (section 10, F11/stop-window notes), `docs/requirements.md` (dated correction), `docs/lab-record.md` (sections 12–13) | spec and evidence |

### Tests run (real; logs `results/logs/phase3-*`)

| Test | Result | Evidence |
|---|---|---|
| Start-of-phase verification: status, preflight, unit 142, live runs 25 (9/9), 26 (9/9) | PASS | `phase3-initial-*` |
| Unit tests, Mac (Py 3.14) and witness-ctl (Py 3.12.3) | PASS 158 / 158 on `4f2b2b0` | `phase3-final-evidence-setup-*` |
| shellcheck 0.9.0, all scripts | PASS rc=0 (after one SC2016 annotation) | `phase3-shellcheck-*` |
| Provisioning (gateway install; idempotent rerun on `4f2b2b0`: nothing restarted, gateway pid 3710 kept all session) | PASS | `phase3-provision-*`, `phase3-final-evidence-setup-*` |
| First live runs of each new case (runs 27–35) | PASS, except run 33 contaminated (F9-data revert timing; fixed) | `phase3-dev-*`, `phase3-f4-first-run-*` |
| F4 against the committed prediction (run 32) | MATCHED: CONNECT_TIMEOUT 1009.9 ms, SYN seen on field, InAddrErrors +3, no ICMP | lab-record 13 |
| Full regression after each fix: 36/37, 44–47, 51–54, 58–61, 62/63 | PASS except run 47 (GW-F8 recovery reference) and run 54 (GW-F1 stop window): both investigated, harness fixed, failing rows kept | `phase3-full-*`, `phase3-final*-*` |
| GW repetition after each GW fix (runs 48–50, 55–57) | PASS 9/9 each set | `phase3-gw-*` |
| **Final evidence on `4f2b2b0` (git_dirty=0)**: baseline runs **64, 65** (11/11 each), fault runs **66, 67** (23/23 each) | **PASS**, clean_env=1, contaminated=0, no failed check | `phase3-FINAL-*` |
| interrupt-selftest TERM/KILL f2 (field) | PASS: TERM reverted in ~1 s; KILL by field dead-man at +91 s | `phase3-interrupt-*-f2-*` |
| interrupt-selftest TERM/KILL f5 (ctl route) | PASS (second attempt): TERM in ~1 s; KILL by ctl dead-man at +90.1 s. First attempt: my script aborted on `systemctl is-active` rc=4 and started the next run under a still-unwinding one (runs 38–40 marked aborted/contaminated by design) | `phase3-interrupt2-*-f5-*`, `phase3-interrupt-*-f5-*` |
| reset-selftest (incl. new checks) | PASS: RED with faults, GREEN after reset | `phase3-reset-selftest-*` |
| Clock defect: before/after the fix | before: `clock-served` FAIL 1.4445 s; after: 0.000 s, skew −1 ms | `phase3-chrony-*`, `phase3-clock-*` |
| SQL over persisted records, report regenerated | PASS; no traceability gaps; F1–F13 covered | `results/reports/commissioning-report.md` |

### Observed results (summary; full table, wire evidence and explanations in lab-record section 13)

Every catalog fault F1–F13 was applied on the real guest network and observed its expected category in the final
runs. Runner detection (fault applied → classified) in final runs 66/67: F3 0.7–1.0 ms, F4 1006–1012 ms, F5 1.9–4.0 ms,
F8 1004–1012 ms, F9 1.0–1.3 ms, F9-data 1.3–2.4 ms, F11 FIN 3.1–4.1 / RST 7.2–8.3 ms, F13 3.0–7.0 ms. REQ-09 (bound
6000 ms; 18 measurements per gateway case, runs 28–67): F1 372–2322, F5 309–1616, F8 1979–2374 ms; none over.
REQ-08 (12 runs 31–67): first PASS HEALTH 1.7–9.6 ms after the restart returned (bound 10 s); gateway saw the
restarted process 842–1111 ms later (bound 4 s). Exact values: report section 4b and SQL `measurements`.

### Defects found and fixed in Phase 3 (each from real evidence)

1. **ctl chronyd served time drifted 81 ppm from ctl's system clock** (Phase 1 design defect; +1.437 s found via
   cross-VM capture timestamps and gateway skew; invisible to the SNTP gate) → no driftfile + `clock-served`.
2. Gateway `freshness.skew_s` computed only for fresh READs (unit test) → computed for every schema-valid READ.
3. `revert nft` swept the orphaned F9-data socket once, too early (run 33 contaminated) → bounded drain.
4. Runner detection times for F3/F4/F8/F9 included post-probe evidence calls (runs 33/37) → taken right after the probe.
5. GW recovery measured from the revert call returning; gateway recovered 13 ms earlier (run 47 fail) → from command sent.
6. GW-F1 asserted a timing-conditional transition category (run 54: CONN_RESET in the graceful-stop window) →
   steady-state category asserted, transition recorded.
7. Live/unit test module basename collision (`test_gateway.py`) → `tests/live/test_gateway_cases.py`.
8. interrupt-selftest f5 aborted on `systemctl is-active` rc=4 and overlapped runs → tolerant check + wait for the runner.

### Scope limits and open items (honest)

- The single-retry path has still never fired live (no commissioning case was non-PASS on attempt 1); unit-tested only.
- Captures are per case on ctl lab0 (all cases) and field lab0 (fault cases); `local_port` exists only for
  established connections, so connect-stage failures (F3/F5/F8/F9) are matched to packets by time and address.
- Gateway polls run during every case, so captures, journals and READ seq gaps include gateway traffic (by design; local
  ports separate them). F6's netem is subnet-wide, so the gateway sees dev-b slow during F6.
- Host sleep can still disturb a run started during the ~20 s after a wake; session preflight gates the clocks, and
  runs from this Mac should be wrapped in `caffeinate -i`.
- Golden clones are the **Phase 2** state (no gateway, ctl still has the stale chrony drift file). After a restore,
  run `scripts/lab_vms.sh provision` before anything else: it installs the gateway and removes the drift file
  (`clock-served` would otherwise be RED). The clones were left untouched, as instructed.
- Mac free disk 12 GiB at the end (was 16 at the start; the lab VMs did not grow: ~2.3 GiB each, guest evidence 34 MiB;
  the difference is macOS-side). Each fault run adds ~0.6 MiB of text evidence.

### Lab state (end of Phase 3, 11:42Z)

Both VMs Running (ssh=vsock); golden clones Stopped. Preflight GREEN on both. witness-faultctl status: no active
faults, dead-man disarmed, no field capture running; ctl: no `witness_fault*` table, route present, no dead-man.
witness-gateway active (pid 3710, healthy 2/2), devices `witness-device@a/b` active, both modes normal.
Results: `/var/lib/witness/results` on ctl, copied to `results/` (DB and pcaps gitignored).

### Phase 4 handoff as written at the end of Phase 3 (done; kept for history)

1. `scripts/lab_vms.sh status && scripts/lab_vms.sh preflight` (expect GREEN incl. `clock-served`, `gateway`).
2. Five clean baseline runs **from a fresh environment** (golden restore, then `provision`, then `link` if the
   field host key differs), flake analysis (Q2), and the deliberate mutants (brief section 7.4).
3. Wrap long runs in `caffeinate -i`; keep one fault at a time; regenerate the report and fetch.
4. Docs owed by the brief: `docs/commissioning-sop.md`, `docs/rca-001.md` (strong candidates: the chrony served-time
   drift, or F4's silent drop), README reproduce-from-scratch.

## Phase 4 (COMPLETE, 2026-10-17 12:24–14:31Z, one session)

Brief re-measured unchanged: `sha256 07a33a08…555baf`. Start state verified independently before any change:
status/preflight GREEN, unit 158/158 (Mac and ctl), baseline run 68 11/11, fault run 69 23/23
(`results/logs/phase4-initial-*`). Mac free disk 11 GiB at start, 10 GiB at end.

### Decisions (Phase 4)

31. **Mutants** (`device/mutants.py`, M1–M6 in `runner/catalog.py` with predictions committed in `9de9813` before the
    first mutant run) are a build selected at process start by a **runtime** systemd drop-in written by
    `witness-faultctl mutant deploy` (gone after reboot; removed by `mutant restore` and `reset_lab.sh`). Deployed on
    dev-a only; dev-b stays stock as the in-run control. Not a lab fault (not in `active_faults`), but field preflight
    `device-build-<i>` is RED unless the runner declared the mutant.
32. **Schema v3**: `mutants` table, `runs.kind` gains `mutant` + `runs.mutant_id` (CHECK kind=mutant ⇔ mutant_id), via the
    documented SQLite table rebuild (FKs off, copy, drop, rename, `foreign_key_check`, same transaction as the
    migration record). The run kind is derived from the build the field **reports**; undeclared/mismatched builds are
    refused (exit 3, no run row). Mutant runs never commission and never appear as a requirement's latest evidence.
33. **Mutant detection rule**: a run is *valid* only if fair (finished, clean_env, uncontaminated) with no infra/runner
    result; detected = ≥ 1 `fail/device` on the mutant device. Infra errors never count as detection.
34. **"Fair" run** (finished ∧ clean_env ∧ ¬contaminated) is the evidence filter for Q2–Q4, traceability, coverage.
35. **Q4 median in SQL** with `row_number()` over the group, averaging positions (n+1)/2 and (n+2)/2.
36. **Acceptance as SQL**: `runner/analysis.py` ASSERTIONS A1–A15 (`python3 -m runner.analysis --db …`, exit 1 on any
    violation), written by `report` to `acceptance-audit.md/.json`.
37. **Provenance**: `golden-restore` writes `/var/lib/witness/provenance` in both guests; the runner records it per
    run (`provenance.<vm>` + boot id), so fresh-clone runs are identified in SQL, not by notes.
38. **Golden clones refreshed**: Phase 2 goldens kept as `*-golden-p2`; the VMs of fresh trial 5 (after its baseline,
    fault suite and reset self-test) became `*-golden`. All lab instances are `limactl protect`ed.
39. **F7-missing** (catalog F7 family, REQ-01): name removed from `/etc/hosts` → RESOLVE_FAIL, the only category no
    Phase 1–3 fault produced on the VMs.
40. **C-ENVIRONMENT attribution**: a firmware version withheld by the device (its session IDENTIFY failed) is `device`;
    any other missing key stays `runner`. Verdict unchanged.

### Files (Phase 4)

| File | Purpose |
|---|---|
| `device/mutants.py`, `device/device.py` | six mutant builds, `--mutant`/`WITNESS_MUTANT`, `build` in state.json |
| `scripts/faultctl.py` | `mutant deploy/restore`, builds in status/check/env, `preflight allow-mutant`, provenance, stale threshold 5 s |
| `scripts/preflight.sh`, `scripts/reset_lab.sh`, `scripts/provision_field.sh` | `device-build-*`, `capture-idle` (field), mutant removal on reset, install mutants.py |
| `scripts/lab_vms.sh` | `mutant deploy/restore/run`, `golden-restore`, `results-push`, fetch staleness guard, report → all files + audit, trap fix |
| `runner/analysis.py` (new), `runner/report.py` (rewritten), `runner/db.py` (v3), `runner/catalog.py`, `runner/lab.py` | SQL analyses/assertions; 7 report files; schema v3; F7-missing + MUTANTS; HostsSwap remove; provenance |
| `tests/live/conftest.py`, `tests/live/test_faults.py`, `tests/live/test_commissioning.py`, `tests/conftest.py` | `--mutant`, build checks, F7-missing case, C-ENVIRONMENT attribution |
| `tests/unit/test_mutants.py`, `tests/unit/test_analysis.py` (new), `tests/unit/test_db_cases.py` | 27 new unit tests (185 total incl. inventory) |
| `README.md`, `docs/commissioning-sop.md`, `docs/rca-001.md` (new); `docs/lab-record.md` §14; `docs/requirements.md` note | deliverables 4, 5, 10, 11 |
| `results/reports/{commissioning-report,traceability,baseline-report,fault-report,mutant-report,acceptance-audit}.md`, `acceptance-audit.json` | generated deliverables 6–9 |

### Tests run (real; logs `results/logs/phase4-*`)

| Test | Result | Evidence |
|---|---|---|
| compileall + unit, Mac (Py 3.14.7) | PASS 185 (+35 live skipped) on `633df97` | `phase4-final-unit-mac2-*` |
| unit in witness-ctl (Py 3.12.3) | PASS 185 ×5 on `633df97`; one earlier FAIL = my loopback fixture race (idle 0.5 s = read 0.5 s), fixed | `phase4-final-unit-guest-x5-*`, `phase4-final-unit-guest-20261017T140157Z.log` |
| shellcheck 0.9.0 (all scripts) + `bash -n` | PASS rc=0 | `phase4-final2-shellcheck-*` |
| provision twice (idempotence) | PASS: second run restarted/installed nothing (originals, fresh clones, scratch VMs) | `phase4-final-provision-idempotent-*`, `phase4-trial1-provision-idempotent-*`, `phase4-scratch-provision-idempotent-*` |
| Mutant tooling self-test (deploy, refusal of a 2nd, preflight RED/allow, restore, reset removes) | PASS | `phase4-mutant-tooling-selftest-*` |
| Runner refuses undeclared / mismatched mutant | PASS (exit 3, no run row) | `phase4-refuse-*` |
| Mutant campaign M1–M6 ×3 (runs 71–97) + final ×1 (120–125) + scratch M4 (129) | **6/6 caught, 30/30 valid runs detected, 0 control false alarms**; 10 invalid runs kept (77–79 stale-check, 80–82/89–91 old attribution, 110 leftover capture) | `mutant-report.md`, `phase4-mutant-*`, `phase4-final3-mutant-*` |
| Five fresh-clone baselines (Phase 2 golden + current code) | PASS 11/11 each: runs 99, 100, 101, 102, 103; + run 105 from the refreshed golden **without** provisioning | `phase4-trial{1..5}-*`, `phase4-newgolden-*`, report §6 |
| Fault suite on a fresh clone | PASS 24/24 run 104 | `phase4-fresh5-suite-fault-*` |
| From-scratch VMs (cloud image → up → provision ×2 → unit → baseline → fault → mutant) | PASS: runs 127 (11/11), 128 (24/24), 129 (M4 caught); up 33 s, provision 79 s | `phase4-scratch-*` |
| reset-selftest | PASS (RED with faults, GREEN after reset) on fresh clone and on originals | `phase4-fresh5-reset-selftest-*`, `phase4-final-reset-selftest-*` |
| interrupt-selftest TERM f2 / KILL f5 | PASS (TERM reverted in 1 s; KILL: ctl dead-man restored the route, full GREEN at 14:15:14Z after the field capture expired) | `phase4-final-interrupt-TERM-f2-*`, `phase4-final2-interrupt-KILL-f5-*` |
| Manual: gateway API (200/404/405), `ip route get`, `getent`, `ss`, bounded tcpdump of a hand IDENTIFY | PASS | `phase4-fresh5-manual-checks-*` |
| **Final evidence on `633df97`**: baseline 118, fault 119, mutants 120–125, post-mutant baseline 126; closing baseline 130 | PASS (11/11, 24/24, all six caught, 11/11, 11/11), all clean_env=1, contaminated=0 | `phase4-final3-*`, `phase4-closing-*` |
| SQL: report generation + acceptance assertions; DB `integrity_check` ok, `foreign_key_check` empty | **15/15 hold**; 130 runs (38 baseline, 52 fault, 40 mutant) | `phase4-closing-report-*`, `acceptance-audit.md` |
| Final clean state | preflight GREEN both; faultctl: no faults, no dead-man, builds stock, no capture; no `witness_fault*` table, no netem, no stopped process, no mutant drop-in, route present; Mac: 0 routes to 10.77 | `phase4-final-clean-state-*`, `phase4-closing-preflight-*` |

### Defects found and fixed in Phase 4 (each from real evidence)

1. Stale-connection check (1500 ms) flagged a live gateway poll waiting for M3's missing newline → precheck RED →
   reset removed the mutant mid-run (runs 77–79) → threshold 5000 ms > the 4.0 s poll deadline (`8002e08`).
2. C-ENVIRONMENT blamed the runner when the device withheld its firmware version (runs 80–82, 89–91) → `device` (`51cfe5a`).
3. Mutant report counted the run-level C-ENVIRONMENT row as a control-device false alarm → fixed (`9414585`).
4. `cmd_up` RETURN trap leaked into its caller → golden-restore rc=1 after success (`87d322b`).
5. A SIGKILLed runner's field capture (RuntimeMaxSec 120) outlived the self-test's GREEN preflight and contaminated
   the next run (110) → field preflight `capture-idle`, `mutant run` requires GREEN, f5 self-test waits (`633df97`).
6. Unit fixture race in my new M3 test → fixture idle timeout 3 s (`f525bad`).
7. macOS tar xattr headers in results-push (cosmetic) → `--no-xattrs --no-mac-metadata`.

### Final acceptance (PROJECT_BRIEF.md, requirement by requirement)

Evidence paths are under `results/`; "report §n" = `results/reports/commissioning-report.md`. Runs cited are fair.

| Item | Status | Evidence |
|---|---|---|
| REQ-01 IDENTIFY ≤ 500 ms, identity matches | **VERIFIED** | C-IDENTIFY pass both devices in fresh trials 99–103/105, final 118/126/130, scratch 127; negatives F1/F3/F4/F5/F7-missing/F8/F9 (run 119); M1/M3/M4 caught by it (report §3, §7) |
| REQ-02 wrong identity → WRONG_IDENTITY, never commissioned | **VERIFIED** | FT-F7-NAME-SWAP WRONG_IDENTITY naming `device_id,serial` + predicate `dev_a_not_commissioned` (run 119); M1 WRONG_IDENTITY runs never commission (A11, kind=mutant) |
| REQ-03 HEALTH ok/sensor_ok ≤ 500 ms | **VERIFIED** | C-HEALTH pass (same runs); M3/M4 caught by it |
| REQ-04 READ ts within ±2 s | **VERIFIED** | C-READ-CLOCK pass; preflight `clock-sync` + `clock-served` (RCA-001); F13-skew STALE_DATA; M2/M5/M6 caught |
| REQ-05 seq increasing, ts not backwards over 10 READs | **VERIFIED** | C-READ-SERIES pass; F11 FIN/RST, F13 repeat-seq; M2 (seq reuse) caught every run |
| REQ-06 malformed → MALFORMED, no crash/hang | **VERIFIED** | F10 malformed/truncated/wrong-id; mutants M3 (incomplete), M4 (wrong_id), M5 (schema) MALFORMED, every case bounded (M3 suite 44 s for 11 cases) |
| REQ-07 TIMEOUT vs PASS_SLOW with latency | **VERIFIED** | F6-300 PASS_SLOW 608.5–691.5 ms; F6-3000 CONNECT_TIMEOUT; F6-3000-data READ_TIMEOUT; F2 READ_TIMEOUT 2003–2027 ms (Q4) |
| REQ-08 restart: healthy ≤ 10 s, gateway ≤ 2 P | **VERIFIED** | FT-F12-RESTART: 17 measurements 1.1–9.6 ms; gateway recovery 842–1111 ms (bound 4000), 0 outside bound (report §4c) |
| REQ-09 gateway unreachable ≤ 3 P, recorded | **VERIFIED** | GW-F1/F5/F8: 92 detections 308.6–2393.4 ms (bound 6000), 0 outside; C-GATEWAY pass |
| REQ-10 environment recorded | **VERIFIED** | C-ENVIRONMENT pass in every fair baseline; A13 holds for every fair run; provenance + device build recorded |
| F1–F13 fault catalog | **VERIFIED** | A5 holds; 20 variants, latest fair results all observed = expected (report §4a/§4b, `fault-report.md`). *Correction 2026-10-18 (audit F-08): 21 variants (13 fault types, 24 live fault-test instances).* |
| 11 outcome categories | **VERIFIED** (all observed live) | A6 holds (RESOLVE_FAIL from F7-missing: runs 70, 104, 107, 119, 128) |
| Section 6.2 retry policy (≤ 1 retry, first attempt recorded, pass-on-retry = flake) | **VERIFIED live** | Q5: run 125 C-IDENTIFY READ_TIMEOUT → PASS reported `fail` FLAKE; Q5b retried rows (M6); A10 |
| 7.1 fixtures/preflight/postflight/contamination | **VERIFIED** | reset-selftest, interrupt TERM/KILL, contaminated runs 77–79/110 detected and excluded (Q6) |
| 7.2 attribution none/runner/infra/device | **VERIFIED** | A7, A8; infra rows only in red-preflight runs (Q6) |
| 7.3 five clean baselines from fresh environment | **VERIFIED** | runs 99–103 (+105), A14/A15, Q2 empty across all 38 baselines |
| 7.4 mutants, catch rate by requirement | **VERIFIED** | 6/6, 30/30, catching REQs per mutant (`mutant-report.md`) |
| Section 8 six queries (SQL) | **VERIFIED** | Q1–Q6 in `runner/analysis.py`, unit-tested on fixtures (`tests/unit/test_analysis.py`, median vs `statistics.median`) and run on the real store (report §5) |
| Deliverables 1–3 (protocol, inventory, requirements) | **VERIFIED** | `docs/protocol.md`, `inventory.yaml`, `docs/requirements.md` |
| 4 lab record | **VERIFIED** | `docs/lab-record.md` (§14 current facts and commands) |
| 5 commissioning SOP | **VERIFIED** | `docs/commissioning-sop.md` |
| 6 traceability table from SQLite | **VERIFIED** | `results/reports/traceability.md`; A1–A4 |
| 7 clean baseline report | **VERIFIED** | `results/reports/baseline-report.md` |
| 8 fault-injection results | **VERIFIED** | `results/reports/fault-report.md` |
| 9 mutant report | **VERIFIED** | `results/reports/mutant-report.md` |
| 10 RCA | **VERIFIED** | `docs/rca-001.md` (clock served-time drift; real logs, captures, commits) |
| 11 README, 10-minute path, honest scope | **VERIFIED** | `README.md`; path timed from trial logs; scratch path timed |
| §13 spec before test code | **VERIFIED** | root commit `38e51d5` (protocol, requirements, inventory); first test file in `ad86fd3` (same minute, inventory loader tests), runner tests in `2daade0` (+42 min) |
| §13 a fault observed ≠ prediction, explained | **VERIFIED** | run 54 GW-F1 CONN_RESET vs predicted CONN_REFUSED (graceful-stop window, protocol.md §5); M3 runs 77–79 (lab-record §14) |
| §13 reproduce-from-scratch tested on fresh VMs | **VERIFIED** | scratch VMs runs 127–129; golden-clone path ×6 |
| Honesty boundary | **VERIFIED** | README, SOP, reports and lab record state software simulation, no hardware/firmware |

No mandatory item is FAILED or UNVERIFIED.

*Superseded 2026-10-18: the independent audit (`docs/independent-audit.md`, verdict FAIL) disproved this statement (F-01..F-08: partial-run commissioning, early gateway restart, case deadline, retry attribution, device request parsing, acceptance gate, F3 captures, variant count). The table above is kept as written at the end of Phase 4; see the remediation section below.*

### Remaining limitations (honest)

- One Mac, one hypervisor (Lima/vz, not UTM); the "host-only" L2 is Lima's user-v2 switch. All timings are for
  this lab only.
- Gateway polls run during every case (by design): captures/journals include gateway traffic; F6's netem is
  subnet-wide, so dev-b is slow for the gateway during F6.
- Connect-stage failures (F3/F4/F5/F8/F9, RESOLVE_FAIL) have no established socket, so `exchanges.local_port` is NULL;
  they are matched to packets by time, destination and the SYN's source port in `capture.txt` (F5/RESOLVE_FAIL send
  no packet at all). Not resolvable without changing the client to bind before connect; documented, not changed.
- M6 (slow-7th) detection depends on request interleaving with the gateway; it was caught in every valid run, but
  which case catches it varies (lab-record §14 obs. 5).
- REQ-02's dedicated case is FT-F7 (a fault case); in mutant runs M1 is caught by REQ-01/REQ-09 cases, and its
  non-commissioning follows from the run kind.
- The scratch test used Lima's cached Ubuntu image (no download timed). `*.pcap` and `witness.db` are not in Git;
  the DB is on witness-ctl (`/var/lib/witness/results/witness.db`) and copied to `results/witness.db` by `fetch`
  (backups: `results/witness-backup-*.db`).

### Lab state (end of Phase 4, 14:31Z)

Active, protected: `witness-ctl`, `witness-field` (the originals; rebooted during Phase 4), preflight GREEN, no
fault, no mutant, no dead-man, no capture; gateway healthy 2/2; master DB max run 130 on ctl and Mac.
Stopped, protected: `witness-{ctl,field}-golden` (Phase 4 state), `witness-{ctl,field}-golden-p2` (Phase 2 state).
Unrelated `vigil` (`~/.lima`) untouched. Mac free disk 10 GiB.

### Reproduce / continue

```
scripts/lab_vms.sh status && scripts/lab_vms.sh preflight            # expect GREEN
scripts/lab_vms.sh unit                                               # 185 passed
caffeinate -i scripts/lab_vms.sh suite baseline                       # 11 passed
caffeinate -i scripts/lab_vms.sh suite fault                          # 24 passed
scripts/lab_vms.sh mutant run M1 1                                    # caught, stock restored, GREEN
scripts/lab_vms.sh report && scripts/lab_vms.sh fetch                 # results/reports/*, 15/15 assertions
# fresh environment: rename/unprotect the originals first (golden-restore refuses protected instances), then
scripts/lab_vms.sh golden-restore --yes && scripts/lab_vms.sh provision && scripts/lab_vms.sh results-push
```
Optional work not started (out of scope until requested): C device port, web UI, TLS, SNMP.

## Independent audit and remediation (2026-10-17/18)

Active phase: remediation of `docs/independent-audit.md` (FAIL, F-01..F-08), per the remediation brief given in
session (not a new project plan). Full record: **`docs/independent-audit-remediation.md`**. Brief unchanged
(`sha256 07a33a08…555baf`). The audit report is unchanged and its FAIL verdict stands; acceptance is for a fresh
independent reviewer.

### Decisions (remediation)

41. **Commissioning = catalog-complete** (`runner/db.py` `COMMISSIONING_GAPS`, `catalog.COMMISSIONING_REQUIRED`): every
    commissioning case once per device / once per run, all pass with green pre/postflight, fair baseline, no
    WRONG_IDENTITY, recorded firmware = inventory, stock build. Partial runs commission nothing and are labelled PARTIAL.
42. **Restart inference** (`runner/classify.restart_between`, gateway + runner): uptime decreased, or advanced less
    than ctl's monotonic clock surely advanced (tolerance 1 ms + 2 ms + 1000 ppm). Protocol v1 wire format unchanged.
43. **One case deadline** (`cases.case_deadline`, 30 s from the first attempt, contextvar; client clamps every step);
    expiry is unclassifiable -> `error/runner`, partial exchanges kept.
44. **Attribution over all attempts**; schema **v4**: `attempts.outcome/predicates`, `capture_flows`.
45. **Device request frames** obey protocol section 2 rule 4 (duplicate keys, `\r`, BOM, NaN, trailing data -> bad_json).
46. **Acceptance**: 18 assertions (A4/A13/A14 strengthened, A16-A18 new); audit works read-only on schema v3 copies.
47. **Captures** include the fault's own ports (`Fault.capture_ports`; faultctl `capture start NAME [PORT...]`);
    `capture_flows` records the dialled flow per capture (runner's ephemeral port when established).
48. **Evidence is never overwritten**: per-application evidence names (`F12.2`), `Lab.save` refuses to overwrite,
    the report re-hashes every indexed evidence file.

### Tests run (real; logs `results/logs/remediation-*`)

| Test | Result |
|---|---|
| Pre-fix reproduction of F-01..F-08 (audit scripts unchanged; VM probe for F-05; audit VM DB for F-01) | all eight reproduced |
| Unit tests macOS / witness-ctl on `0943fd5` | **PASS 279 / 279** (185 before) |
| ShellCheck 0.9.0 + `bash -n` | PASS |
| Provision (deploy), preflight | PASS, GREEN, `git_dirty=0` |
| F-05 VM probe both devices | 30/30 (pre-fix 20/30) |
| F-01 HEALTH-only run, separate DB on witness-ctl | nothing commissioned, PARTIAL 2/11 (pre-fix shape: both commissioned) |
| F-03 lab traffic, netem 1300 ms post-handshake | 30.006 s, `error/runner`, fault reverted |
| Baselines 131, 145, 150 | 11/11 each |
| Fault suites 133, 146 | 24/24 each; **run 132 error/infra** (field SSH stall under host memory pressure; kept) |
| FT-F12 incl. early restart 133-138, 146-149 | all pass; 5 real-VM early restarts with RISING uptime detected, recovery 927.5-1265.9 ms (bound 4000) |
| Mutants M1-M6 (runs 139-144, `3a9bbbc`) | 6/6 caught; campaign 36/36 valid runs detected |
| Acceptance on the real store | **18/18 hold**; both audit counterexamples now fail it |
| DB integrity / FKs; evidence re-hash | ok / empty; 12,778 rows, 24 differing = FT-F12 runs 133-138 (annotated, below) |
| Final clean state | GREEN; no fault, mutant, dead-man, capture, netem; goldens and `vigil` Stopped |

### Defects found during the remediation

1. Capture-flow filter also matched the gateway's polls -> keyed on the runner's ephemeral port (`c335c84`).
2. FT-F12's second restart overwrote four indexed evidence files per run in runs 133-138 (24 rows; results intact) ->
   fixed in `0943fd5`; `results/evidence/F12-overwritten-evidence-annotations.md`.
3. Run 132: field VM stalled while the Mac swapped (13.7/15.0 GiB); preflight RED, all `error/infra`, contaminated.
4. My own log wrappers under zsh: two misleading `rc=` lines and two steps that did not run; annotated and rerun.

### Open items / limitations (see the remediation document, section 6)

- Five fresh golden-restore baselines were **not** repeated on the remediated code (A14 rests on runs 99-103/105 at
  `87d322b`); the host ended with 1.8 GiB free disk under memory pressure.
- Mutants ran on `3a9bbbc` (final `0943fd5` differs in fault-evidence naming and the report only); interrupt and reset
  self-tests not rerun. `HEAD` after `0943fd5` changes docs, results and two comments only.
- F-02 residual timing blind spot; F-07 connect-stage flows identified by address:port.

### Lab state (end of remediation, 2026-10-18T01:15Z)

witness-ctl and witness-field Running, preflight GREEN, no fault/mutant/dead-man/capture, builds stock, gateway healthy;
master DB on ctl and the Mac: 150 runs, schema v4. Golden clones (`*-golden`, `*-golden-p2`) Stopped and untouched;
`vigil` untouched. Remediation artifacts outside Git: `~/Desktop/Witness/independent-audit-evidence-20261017/`,
`~/Desktop/Witness/remediation-evidence-20261018/` (both with `SHA256SUMS`).

### Next actionable step

A fresh independent reviewer re-runs `docs/independent-audit-remediation.md` section 7 and decides acceptance. If the
host regains disk headroom (>= 10 GiB free, `df -h /`), optionally repeat five golden-restore baselines on the
remediated code (`golden-restore` deletes and re-clones the working VMs: follow the Phase 4 "Reproduce /
continue" block, which unprotects/renames the originals first; then `provision`, `results-push`, `suite baseline`).

## Independent post-remediation re-audit — 2026-10-18

Final report: [independent-reaudit.md](independent-reaudit.md), verdict **FAIL**. This entry supersedes the
remediation's awaiting-re-audit status without rewriting its historical claims. Reviewed HEAD
`9f695e1a5f38a4df91ce1d18a92c8e3d20cd7c26`; both guests remain at
`0943fd5a3d6b31ec019fc55e09bdea3331cd9ed8` (runtime-equivalent comment differences verified).

Independent commands, UTC timestamps, exit codes, scripts, source comparisons, separate DB and raw captures are in
`results/independent-reaudit-20261018/`. The original brief, failed audit, remediation record, master DB and historical
captures were preserved. No implementation, deployment, commit, push or publication was performed.

- `.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit tests/test_inventory.py`: **279 passed** on Mac;
  the same suite inside witness-ctl: **279 passed**. Successful logs distinguish initial sandbox binding failures.
- `pytest tests/live --live -m commissioning` using `/tmp/witness-reaudit-20261018.db` and a separate evidence root:
  **11/11**; HEALTH-only selection **2/2 but no device commissioned**, PARTIAL 2/11.
- `pytest tests/live --live -m fault` on the same separate store: **24/24**; 25/25 fault removals verified (F12 twice).
  Actual F3 TCP 5021 SYN/RST packets present in both guest captures; 412 indexed audit evidence files all match.
- Original unchanged 31.637-second deadline reproduction now **30.003 seconds, error/runner**. Independent gateway
  early/rapid restart checks recover in 1.948/1.916 seconds from first PASS HEALTH; sequence reuse remains STALE_DATA.
  Actual live early F12 recovery 1273 ms with rising uptime. Independent parser VM checks **20/20**.
- F-01/02/03/04/05/07/08 original counterexamples corrected. F-06's exact two fixtures now reject, but additional
  valid-schema disposable fixtures still yield 18/18 HOLDS for whitespace-only environment values and conflicting
  duplicate run-level results. A17 also accepts a missing field capture-flow record. These are the FAIL basis;
  see R-01/R-02 and the report's precise scope limitations, including the broader case-deadline gap.
- Historical repaired mutants and ten F12 tests were inspected, not newly rerun in full. Exactly 24 disclosed F12
  evidence mismatches remain flagged; none are represented as intact. v3→v4 migration checked on an in-memory copy.
- Five current-revision fresh-environment baselines and fresh-VM reproduction **NOT EXECUTED**. Host available disk
  was 6.2–9.2 GiB during live work, later 7.0 GiB with heavy swap. At 14:23Z it read 12 GiB, swap 7508.38 MiB,
  pressure level 2; stable restore margin was not established. No clones were restored or created.
- A SIGKILL during capture startup left no observed capture; it did not establish mature capture-expiry or dead-man
  recovery. A second experiment stopped at initial field SSH preflight timeout before applying a fault. Planned
  SIGTERM/F2, SIGKILL/F5, dead-man/capture-expiry and reset self-tests remain **NOT EXECUTED** post-repair.

Closing state at 14:41–14:42Z: both dedicated guests Running, full preflight GREEN, builds stock/modes normal,
no faults/captures/test runners/Witness timers, gateway and vsock recovery healthy; guest free space 6535/6479 MiB.
All four goldens Stopped; unrelated `vigil` Stopped and untouched. Original master DB hash unchanged. Final Git changes
are this ledger, the re-audit report and audit-only evidence. No implementation repair was made.

Next work is a separately authorized repair/verification phase for R-01/R-02 and deadline scope, followed by safe
current-revision repeatability and interruption/reset verification. Until then, use a transparent work-in-progress
GitHub/resume description; do not claim unconditional independent acceptance.

## Second independent audit remediation (R-01/R-02) — 2026-10-19

Record: [independent-reaudit-remediation.md](independent-reaudit-remediation.md). Both audits and their reports are
kept verbatim (re-audit material committed alone in `cacfac7`). Repair `12f027e`; logs/reports `aa9e193` (deployed to
both VMs, `git_dirty=0`); later commits change only docs, evidence, `.gitignore` and a Mac-side check script.

- Root causes: A13 validated with SQL `trim()`/`LIKE`, no run-row consistency, device set from the store; `LATEST_FAIR`
  = `max(result_id)` hid an older conflicting row of the same run and A18 skipped runs with duplicates; A17 required only
  that some flow row exist and trusted `expected`/`packets`; no assertion read the capture bytes; reference tables were
  trusted (deleting dev-b gave 18/18).
- Fix: `runner/evidence.py` (`check_environment`, shared by the live C-ENVIRONMENT case, commissioning and A13;
  `flow_packets`, an independent pcap recount; `file_problem`); `LATEST_FAIR` = every result of the latest fair run of
  an instance; A18 evaluates AMBIGUOUS runs; A19 cardinality; A17 derived coverage; A20 bytes (needs `--evidence-root`,
  default `<db dir>/evidence`); A21 reference data; A5 prediction tie; A9 missing applications.
- H: pre-repair 38/45 probes not rejected as required (`reaudit-remediation-pre-acceptance-probes-*`); new tests on the
  pre-repair code 62 failed / 7 controls passed; post-repair 45/45 as expected (41 rejected by the right assertions, 4
  controls held) and the audit's counterexamples rejected; units **384 passed** (macOS 3.14.7) — `.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit tests/test_inventory.py`.
- DB: master store copy 21/21 with byte verification, 264/264 stored flow counts = independent recount = tcpdump;
  master hash `f5f789eb…d6dc` unchanged; reports regenerated from a verified copy. Superseded runs' known limits
  (run 131 keying, 24 F12 files, pre-F-07 F3 captures, Phase-2 runs without field captures) are listed, not gating.
- VM: `scripts/lab_vms.sh unit` **384 passed** on witness-ctl; `suite baseline` **11/11** (run 1) and `suite fault`
  **24/24** (run 2) on `aa9e193` into `/var/lib/witness/reaudit-remediation/` (copied to
  `results/reaudit-remediation-20261019/vm/`, SHA256SUMS); acceptance there 18/21 (no mutant/fresh-clone runs in that
  store). Postflight GREEN both 2026-10-19T03:30:20Z; goldens Stopped; no Mac route/firewall change.
- OPEN (exact steps in the record, section 8): five current-revision fresh-environment baselines and fresh-VM
  reproduction (host 9.4 GiB free, swap 7883/9216 MiB, pressure level 2 at 03:32Z: below the restore margin);
  post-repair SIGTERM/SIGKILL/dead-man/capture-expiry/reset self-tests (not executed); whole-case 30 s deadline scope.

Next: an independent reviewer re-runs section 9 of the record; when host headroom allows, the five fresh baselines and
the interruption/reset self-tests. Do not claim independent acceptance until a reviewer grants it.

## Independent final verification of second remediation — 2026-10-19

Report: [independent-final-verification.md](independent-final-verification.md). **Verdict FAIL** for the
acceptance-integrity recheck; full-project acceptance is also not granted. This entry preserves both earlier audits
and remediation records. No implementation, deployment, commit, push, publication, restore or new fault injection.

- Reviewed HEAD `a6d487f`; guest source trees stamp `aa9e193`, dirty=0. Compared 69 ctl and 66 field source/installed
  files. Installed gateway `runner/classify.py` retains `0943fd5` bytes differing only in a timing-range docstring;
  executable AST equality verified. No runtime drift found. The final commit changes only docs/evidence/ignore rules
  and the Mac verification script, as claimed.
- Exact R-01 environment/duplicate and R-02 missing-field/expected=0 fixtures now reject. Independently reran the
  unchanged auditor scripts and the remediation's **45/45** probes (41 invalid rejected, four controls accepted).
  Added 60 independent disposable experiments: 49 expected negative rejections, four controls, seven accepted gaps;
  all integrity OK/FKs empty. Original databases are opened read-only and unchanged.
- **FV-01 P2, remaining acceptance defect:** delete a current F3 result's exchange rows and its field-flow row:
  **21/21 HOLDS** on a master copy. Delete exchanges and set stored counts to 999: also 21/21, although independent
  tcpdump reads count four actual packets per F3 capture. `flow_plan` skips results without exchanges; A17/A20 then
  omit their obligations/recounts. The same gaps reproduce on the latest aa9e193 two-run data, adding no failures
  beyond its expected A12/A14/A15. Missing gateway/session evidence-index rows also escape detection.
- **FV-02 P3:** deleting inventoried dev-b's database rows makes standalone commissioning say COMPLETE 6/6 and omit
  dev-b. A18/A21 correctly reject the whole dataset; this is a standalone report/coverage discrepancy, not another
  all-green acceptance bypass. Report prose also overstates that every ambiguous run commissions nothing despite
  the intentionally per-device rule.
- New executions: units **384 passed macOS / 384 Ubuntu ctl**; unchanged full deadline loopback **30.002584 s,
  error/runner**; early/rapid-restart loopback recovery **1.972/1.927 s**, M2/F13 discrimination retained; independent
  retry decisions/Q5/Q6 correct. v3 read-only audit and twice-applied v4 migration preserve all original rows.
- Independently inspected latest stored aa9e193 baseline **11/11** and faults **24/24**, **25/25** removals; these
  suites were not rerun live in this audit. **394/394** files match, **58** independently derived capture/flow records
  (**54 expected**), **56/56** address-bearing counts equal tcpdump, including both F3 TCP5021 captures. Independently
  checked 48 baseline response records/40 READs. Master: 12,778 indexed files, exactly 24 disclosed historical F12
  mismatches, 264/264 address-bearing flow counts agree; historical limitations retained.
- E = `results/independent-final-20261019/`: commands, UTC timestamps, statuses, scripts, complete negative-fixture
  assertion results, source comparisons, byte verification, preservation manifest and final Git status.
- Closing lab 18:50:20–24Z: both preflights GREEN, stock/normal, no fault/capture/pytest/Witness timer, vsock active,
  correct isolation/routes; guest free space ctl 6481 MiB / field 6316 MiB. Four goldens Stopped; vigil untouched.
  Host 18:50:25Z: **6.3 GiB free, swap 8806.75/9216 MiB, pressure 2**; no resource-intensive VM experiment performed.

Remaining: repair and independently reject FV-01/FV-02 without weakening valid controls; resolve/test overall GW/F12
deadline scope (precise bounded continuation in the report); then five current-revision restored baselines,
fresh-VM reproduction, TERM/KILL/dead-man/mature-capture-expiry/reset checks after stable headroom. These remain
unexecuted, not implied by old baselines, ordinary fault teardown, or passing unit suites. Verification phase stops
here; no repair was authorized or undertaken in this phase.

## Acceptance-integrity repair (FV-01/FV-02 class) — 2026-10-19/20

Record: [acceptance-integrity-repair.md](acceptance-integrity-repair.md); contract:
[acceptance-contract.md](acceptance-contract.md). Repair COMPLETE against its gate; full-project acceptance NOT claimed.

- Root cause: every obligation set (required flows, files, devices, "latest" run) was derived from the rows being
  verified, so deleting evidence deleted the obligation. Now: catalog case contract (`runner/contract.py`), inventory,
  run plan (schema v5: `run_plan` + indexed `session/plan.json`, written before the first case), case directories as
  receipts, the migration record (checked against the schema), `results.predicates` (the decision basis). New A22
  (integrity/migration record), A23 (run flags/selection/receipts), A24 (evidence chain); A17/A20 never skip; A4/A18
  and the report select by plan; commissioning uses the inventory and the contract; the verifier fails closed.
- Test-first: `tests/contract/` (reference stores via production writers, independent oracle, 202 declared mutations,
  seeded combinations, 8 self-test weakenings) + `scripts/verify_acceptance_contract.py`. HEAD `a6d487f`: 167 false
  acceptances. Final: 329/329 agree, 8/8 weakenings detected (macOS); 249/249, 8/8 (witness-ctl).
- Independent read-only review: 11 reproduced defects of the first version, each declared, fixed, rerun with the
  reviewer's own probes (all rejected). The self-test then exposed a verifier crash on type-corrupted records (fixed:
  fail closed).
- Tests: macOS 685 passed (391 unit, 294 harness); witness-ctl 391 unit + 254 harness. Earlier audits' scripts rerun:
  all negatives rejected, all 7 previously accepted gaps rejected; 5 intended differences (flag-only "unfair" controls
  now rejected by I1.2; forged no-wire justifications reported by A24).
- Real stores (read-only copies): master 24/24; aa9e193 store 21/24 (A12/A14/A15); hashes unchanged.
- VM (`7fca791`, git_dirty=0, separate store `/var/lib/witness/acceptance-integrity`, copied to
  `results/acceptance-integrity-20261019/vm/` with SHA256SUMS): baseline run 1 **11/11**, fault run 2 **24/24**, both
  clean/uncontaminated; plans, plan files and decision predicates recorded live; acceptance 21/24 on ctl and Mac (only
  absent mutant/fresh-clone history); report agrees; FV-01/FV-02 probes rejected on this live store. Pre/postflight
  GREEN; no residual fault, capture, timer or runner; goldens and vigil untouched. Host 6.2 GiB free at the end.
- Commits: `913e10a` (final verification preserved verbatim, no co-author trailer per this task's instruction),
  `b9c334f` (repair), `7fca791` (deployed), record/evidence commit. Not pushed.

Remaining (OPEN, unexecuted): independent verification of this repair; five fresh-clone baselines and a mutant campaign
on the current revision (host below the 10 GiB restore threshold); interruption/dead-man/reset self-tests; whole-case
deadline scope for gateway/F12 cases; fresh-VM reproduction. The master's evidence predates v5 (receipts, category and
verdict bases are stated limits, not certifications).

## Independent evidence-contract verification — 2026-10-20

Report: [independent-contract-verification.md](independent-contract-verification.md). **Evidence-contract repair:
NOT VERIFIED. Full Witness project acceptance: FAILED**, with experimental coverage also incomplete. Read-only
verification at `4b1f658`; no implementation, deployment, VM interaction, fault injection, restore, commit or push.
Earlier reports and evidence remain unchanged. Evidence: `results/independent-contract-20261020/`.

- Original unfinished-run, disabled-plan and FV-01/FV-02 counterexamples now reject. Two new false positives remain:
  **IC-01**, a run's contamination note can name itself as the later run that detected its abort, making a current
  failing fixture 24/24 through older evidence; **IC-02**, deleting a required case-decision predicate and changing
  the verdict can accept a failing gateway case. Both confirmed with all 19 v5 guards intact; SQL, controls and
  complete assertion outputs retained. The reference oracle omits `results.predicates` from its projection.
- Full deterministic verifier completed successfully: **329/329 OK, 8/8 weakenings detected, exit 0**; existing log,
  JSON and completed process result inspected after the user's status request, without rerunning it. Earlier
  240-second verifier and 120-second unit attempts timed out and are not counted as passes.
- Actual macOS suites: **391 unit/inventory tests passed**, plus **5 focused commissioning/report tests passed**.
  Independent challenge: 23 store outcomes and one oracle check; original v5-store omission probes rerun.
- Retained `7fca791` live baseline/fault data: 11/11 and 24/24, 25/25 removals, 396 indexed files and 397 manifest
  entries match; 56 tcpdump counts agree, 58 independently derived flow records (54 expected), 10 gateway
  address/capture combinations nonempty, 48 decoded baseline responses/40 READs valid. Plans 11/24 precede results;
  all 35 decisions recorded. Audit remains expected 21/24 (A12/A14/A15); report agrees except documented A18 wording.
- Historical master remains v4, 24/24 under legacy rules, with the same 24 disclosed mismatches among 12,778 indexed
  files and 264 matching tcpdump recounts. Neither historical store nor original source/evidence was rewritten.
- PARTIAL 6/11 commissioning dev-a only is valid for a genuinely selected partial baseline; a failing partial run
  still violates A4. The handoff's omitted-device report did not supply an evidence root; its root-aware audit
  rejects the contradictory plan. Two-run store history failures are expected scope distinctions, not new defects.
- Host below restore threshold: 6.3 GiB initially, 4.4 GiB at 04:24Z; swap then 10643/11264 MiB, pressure 2.
  No guest was touched; retained preflight is historical, not a new live cleanliness certification. Audit-generated
  stores removed; logs, scripts and JSON retained.

Next: reject IC-01/IC-02 while retaining valid controls, then complete five current-revision restored baselines,
current mutants, interruption/dead-man/capture-expiry/reset recovery, gateway/F12 overall-deadline verification and
fresh-VM reproduction under safe resources. This verification phase is complete; repair remains unauthorized here.

## Evidence-contract remediation (IC-01/IC-02) — 2026-10-20

Record: [independent-contract-remediation.md](independent-contract-remediation.md). **IC-01 and IC-02 repaired and
verified; full Witness project acceptance NOT claimed.** Audit material committed verbatim and alone first
(`93c029b`); fix `b5873ff`; earlier audit conclusions above unchanged. Evidence:
`results/independent-contract-remediation-20261020/` (RED outputs in `red/`, the reviewer's probes in
`review-probes/`).

- IC-01: an abort marker must name a separate recorded run with a larger id and a strictly later start that recorded
  its session; a run that records a finish must show a teardown session record later than the detector's first
  session record (the runs row's own finished_at never proves the overlap). Auditor's self-abort: 24/24 -> 23/24
  (A23). The review's F1/F1b/F1c/F2 (forged finish, moved detector start, bare detector row; 24/24 on the first
  repair and on `4b1f658`) now 23/24 (A23). Master 24/24 (runs 7 and 38 still corroborated), live v5 21/24.
- IC-02: decision predicate names come from `contract.CASE_PREDICATES` (anchored to tests/live by an exact static
  rendering) plus the final attempt's derived names; partial sets only on a fail (F12); duplicate names unreadable;
  verdict must match its basis. Auditor's erasures: 24/24 -> 22/24 and 21/24; live-copy erasures 21/24 -> 19/24
  with dev-b no longer commissioned. All 35 live v5 decisions carry exactly the contract's names.
- Executed: unchanged auditor scripts (RED on `4b1f658`, after the fix); macOS **824 passed**; verifier **353/353,
  12/12 weakenings detected**; real stores read-only (master 24/24, live 21/24, hashes unchanged); live-store reports
  identical to the audit's regeneration but for the timestamp; Ubuntu witness-ctl (Python 3.12.3) unit **505 passed**,
  contract harness (20 seeds) **279 passed**, preflight and postflight GREEN, no residue. One full Mac run failed
  once on a same-millisecond tie (kept, fixed: strict ordering); one verifier run reported a broken weakening
  (kept, fixed in test code).
- Independent read-only review, two rounds: F1 (P1, IC-01 class) and F1c/F2 fixed; F4/F5/R2-2 and anchor blind spots
  fixed; R2-3 (sub-millisecond genuine overlaps without a record) stated as a fail-closed limit; R2-4 fabrication
  stated as a boundary. **Open, not fixed (outside IC-01/IC-02, pre-existing on `4b1f658`): F3**, a failing baseline
  relabelled kind=mutant with three environment rows reaches 24/24; the indexed session/environment.json still says
  baseline but its contents are not compared.
- Host: no restore/clone/campaign/fault experiment (5.6 GiB free at the end, below the 10 GiB restore threshold).

Next: decide F3 (compare the indexed environment record with the environment table/run kind, or state it as a
boundary), then the outstanding acceptance experiments: five current-revision restored baselines, current mutants,
interruption/dead-man/capture-expiry/reset recovery, gateway/F12 overall-deadline verification, fresh-VM
reproduction — when the host has >= 10 GiB free.

## F3 baseline-relabelling acceptance-integrity repair — 2026-10-20

Targeted repair **COMPLETE and verified**, started from clean `6bca0a3`; record:
[f3-acceptance-integrity-remediation.md](f3-acceptance-integrity-remediation.md). Evidence:
`results/f3-acceptance-remediation-20261020/`. This is the independent review's F3, not fault-catalog F3.

- Unchanged original reproduction executed before production changes: failing baseline **22/24** (A4/A18), then
  **24/24** after kind=mutant/M5 plus three environment edits. RED regressions **38 failed, 9 passed**. New I1.7
  compares the canonical indexed session environment bytes with the table/run identity before any run exclusion,
  for all kinds including mutants/superseded runs. Missing/invalid/duplicate/contradictory records reject. The
  table-only clean flag and early pre-v5 missing mutant/build format remain valid. No schema/live-writer change.
- Post-fix original reproduction **23/24, A23** with original failure/bytes preserved and all 19 guards retained.
  macOS full unit/inventory **563 passed**; old fixture omissions corrected without changing negative assertions.
  Full adversarial verifier **395/395 OK** (9 controls, 266 mutations, 120 seeded combinations), **13/13 weakenings
  detected**, exit 0. Disabling only the new F3 guard fails 36 mutation expectations, including the original bypass;
  last-wins JSON parsing fails both complete duplicate-session mutations as well as the earlier IC-02 case.
- Real source databases opened read-only: master **24/24**, v5 **21/24** (only A12/A14/A15). Reports equal audits;
  v4→v5 twice in memory preserves all original data, integrity OK/FKs empty. Original DB/session/brief hashes
  unchanged. New reports and full preserved-failure facts are under the evidence directory.
- One separate read-only Codex reviewer: **29/29** independent probes plus **16/16** final test-only checks; no
  reproducible F3 defect. Both disabled-helper and isolated last-wins parsing restore false acceptance in probes.
  Existing assertions in touched test modules independently confirmed unchanged. No guest or network action.
- Boundary: file/hash agreement is correspondence, not authenticity; coordinated rewriting of files, hashes and
  all metadata remains outside the evidence contract. Rootless commissioning is structural only; acceptance needs
  the evidence root. No full Witness acceptance claim. All separately outstanding experiments above remain open.

Final preservation/cleanup PASS (`logs/final-preservation.log`, `final-checks.json`): both original DB hashes,
all 152 session files and the authoritative brief unchanged; production hashes match the independent review;
the verifier's temporary fixture tree removed. The local scoped commit includes this ledger/record and evidence;
the final handoff reports its hash and working-tree status. Host before the verifier: **6.7 GiB free**, swap
**9706.06/10240 MiB**. No VM, `vigil`, restore/clone, host route or firewall, deployment, production data or push
touched. Full Witness acceptance is not claimed. Next actions remain the separate outstanding experiments above,
when resources permit; F3 is closed within the preserved-session-evidence contract.

## Independent F3 acceptance-integrity verification — 2026-10-20

Report: [independent-f3-verification.md](independent-f3-verification.md). **Verdict NOT VERIFIED** for the targeted
F3 correction at `f9dd5d6`. The original failing-baseline-to-mutant relabel is rejected by A23 (23/24), and valid
baseline/mutant controls retain their outcomes. A missing-session edge remains: a legitimately interrupted run with
20 recorded environment rows can lose its environment file and index on a disposable copy and still yield **24/24**.
`_session_environment` skips an unfair run with no index/file without considering those table rows. A second
disposable counterexample hides a failing latest baseline after adding an unfair-run marker and removing the same
session evidence; its broader status fabrication is stated separately in the report.

Executed locally: 15 focused disposable audit cases plus seven valid run-contract controls, **141 focused pytest
tests passed**, and two independently constructed edge probes; exact commands, UTC logs and the initial probe
expectation corrections are retained in `results/independent-f3-20261020/`. Read-only-backed master copy remains
24/24; retained v5 copy remains 21/24 (A12/A14/A15). No full acceptance verifier, VM run, deployment, production
code edit, historical-data edit, push or publication. Reassess the I1.7 exemption for interrupted runs after a
scoped repair; preserve the pre-environment interruption case and the existing valid controls. Final preservation
check at 22:24 UTC exited 0: HEAD, both original DB hashes, previously indexed session files and symlinks unchanged;
only this state file changed among pre-existing files. `git diff --check` was clean.

Preservation-check follow-up: the first `preservation-before` exited 1 at 20:27 UTC because the audit-only helper
followed a tracked symlink to an evidence directory and raised `IsADirectoryError` before any hash comparison.
`run.py` only recorded the subprocess failure; no Daybreak link is established by its log. The helper's existing
symlink-text hashing fix was confirmed; its fixed precheck had already passed at 20:59 UTC. The earlier manifest
was copied to `preservation-before-prior.json`, then the bounded `preservation-before-recheck` passed at 23:10 UTC:
15,583 entries, 896 session paths, both original DB hashes unchanged, prior remediation manifest matched. Only this
progress file differed between the two successful prechecks. The independent F3 verdict remains **NOT VERIFIED**
for the separate missing-session acceptance counterexample; details and commands are in the report.

## Targeted interrupted-session evidence repair — 2026-10-20

Started from `f9dd5d6`, preserving the uncommitted independent F3 report, ledger additions and
`results/independent-f3-20261020/` byte-for-byte. Evidence: `results/f3-interrupted-evidence-20261020/`.
The unchanged auditor `edge_probe.py` reproduced both 24/24 false acceptances before any production edit.
`counterexample-before-fix.json` retains the decisive interrupted run's unchanged lifecycle/check/result/plan
records, all 20 environment rows, removed snapshot/index and complete before/after audits. New regression RED:
11 failed, 17 passed.

**Specific repair COMPLETE and verified**; record:
[f3-interrupted-evidence-remediation.md](f3-interrupted-evidence-remediation.md). The exemption now applies only to
an unfinished session with no environment rows, case results, postflight, snapshot or index. Persisted collection
or later lifecycle facts independently require the snapshot/index before any fairness/kind exclusion; no missing
contents are fabricated. Preflight/plan-only early interruptions remain valid. No schema, writer or selection change.

- Unchanged original `edge_probe.py`: both omission attacks now **23/24, A23 I1.7**; interrupted valid control
  **24/24**, original latest failure **22/24 (A4/A18)**. All 20 environment rows and original failure facts retained.
- Focused old/new regressions **89 passed**; full Mac unit/inventory suite **594 passed**, including affected
  SQLite migration and report units. Full verifier **401/401 OK**, **14/14 weakenings detected**: 9 controls,
  272 mutations and 120 seeded combinations. Disabling only the new obligation specifically restores false
  acceptance for the interrupted run missing both snapshot and index. Previous F3 weakenings remain detected.
- One separate read-only reviewer: **32/32 independent probes**, no reproducible finding; final source hashes
  stable. Both removals, each minimal durable source, legitimate early interruptions and older-success fallback
  challenged. Initial review hash-check failure from a concurrent comment edit retained; frozen-source rerun passes.
- Read-only-backed real stores: master **24/24**, v5 **21/24** (only A12/A14/A15); reports equal direct audits;
  v4→v5 twice preserves all original columns/rows, integrity OK, no FK violations. Original F3 negative still rejects.
  Missing-session reports explicitly reject A23 while preserving all other run facts.
- Final preservation PASS: both original DBs, 896 prior-audit session paths, all 19 independent-audit files,
  symlinks and brief unchanged; no unexpected changes in either manifest; reviewed source hashes match; generated
  verifier fixture directory removed. Final disk **6.8 GiB available**, swap **10697.69/12288 MiB**.

The scoped local commit includes the previously uncommitted independent F3 audit unchanged, this repair and its
evidence. No push, VM, clone/restore, campaign, host network or `vigil` action. Full Witness acceptance is NOT
claimed. Coordinated removal/rewrite of every corroborating lifecycle and collection fact remains outside the
contract; separately outstanding project acceptance experiments above remain unexecuted. This bounded repair ends here.

## Overnight acceptance execution — 2026-10-21 (in progress)

Phase A completed from `592a481d4b1495c3a22953df0fcfc0d2a549b2c5`. Evidence/checkpoint:
`results/overnight-witness-20261021/execution-20261021T071813Z/`. Initial preservation manifest covers 15,879
existing source/result paths (symlinks recorded as links); the pre-existing overnight prompt and console log are
preserved. No historical database or result directory is used as a writable experiment store.

Initial resources: 16.48 GiB available, swap 2202.38 MiB; both protected originals and four goldens stopped.
Only the two originals were started (24.76 s, vsock management); initial preflight GREEN both (1.54 s), clock
offset -0.000075 s. Current code provisioned in 5.81 s. After start: 17.41 GiB available, swap 2371.25 MiB,
memory_pressure free 29%, raw pressure level 2. ARC21 Docker services active, unchanged; default Lima `vigil`
stopped, read-only inventory only. No host network or unrelated service change.

Phases E/F currently **BLOCKED — INSUFFICIENT HOST RESOURCES**: below the assignment's ordinary 20 GiB
clone/restore reserve; protected originals/goldens remain intact. No superior peak-space safety calculation yet.
Phase B/C work continues sequentially in an isolated guest store. First baseline invocation failed before session
creation (`sqlite3.OperationalError: unable to open database file`): new parent directory not yet created;
retained as an execution setup error, not a failed device test or a PASS. Resume details are in the checkpoint.

Phase C confirmed a material live runner defect before modification: audit-only F12 HTTP proxy, unchanged real
upstream bytes, 1.5 s header + 1.5 s body waits (each below the socket's 2 s timeout), recorded **PASS after
34.833 s body / 35.483 s case duration** on `592a481`. Zero-delay control PASS (3.749 s body); the prescribed
1.5 s whole-response delay also PASS (17.775 s). All had GREEN postflight and two verified F12 removals. The
old 75 s body alarm did not implement the 30 s overall case bound.

Focused correction: one 30 s timer starts before case quick checks/capture setup; its remaining deadline is
shared with probes/retries, and its alarm bounds direct gateway/fault operations. A timeout records error/runner
before safety teardown; completed F12 exchanges are retained and held connections closed. The alarm is disabled
before teardown so restoration can finish. Session startup and bounded safe teardown remain separately measured.
First repaired negative: **error/runner at 30007.302 ms** case duration (body 29.350 s, setup consumed the rest),
eight exchanges retained, two removals verified, clean=1/contaminated=0, GREEN postflight. These are diagnostic
dirty-tree controls, not final-revision commissioning; final controls and campaign follow the local repair commit.
Focused budget/probe/decision regressions **96 passed**; full Mac unit/inventory suite **598 passed in 198.87 s**
(`logs/full-unit-mac.log`). The contract verifier and
F3 protections are unchanged; no broad acceptance-system redesign or historical evidence edit.

Phase B baseline/fault and Phase D campaign completed on committed `872cf2956d8037b04f8e0bb9a12fd87a12cb6c03`,
guest source stamp dirty=0. Isolated main store `/var/lib/witness/overnight-20261021-071813/main/`:
run 1 baseline **11/11** (23.88 s), run 2 faults **24/24** (111.24 s), M1–M6 runs 3–8, run 9 restored-stock
baseline **11/11** (23.68 s). Each mutant has a finished clean uncontaminated run, zero runner/infra results,
at least one fail/device on dev-a, and zero nonpass results on stock dev-b: **6/6 caught**. Every stock restore
and postflight passed. Native-byte/SQL final cross-check still follows. These two stock baselines are existing-VM
controls, **not** fresh-clone repetitions.

Final committed-source cumulative-delay probes: F12 and GW-F5 both stop at the 30 s setup/body budget with
error/runner, clean=1/contaminated=0 and GREEN postflight (diagnostic expected failures in separate stores).
Post-repair normal F12/GW positive controls pass in run 2. Recovery phase continues: observed F2 SIGSTOP and both
mature captures before SIGTERM to exact runner PID; runner exited 2, restored clean state observed at +4.338 s,
full GREEN at +5.602 s. SIGKILL/dead-man paths currently in progress; see the durable checkpoint, not a PASS claim.

Recovery probes completed at `872cf29`: KILL/F2 GREEN +92.705 s, controller capture expired +59.71 s, SIGSTOP
cleared by field dead-man +90.30 s; KILL/F5 GREEN +121.390 s, controller capture expired +59.75 s, route restored
and controller timer inactive +90.95 s, independent field capture expired +119.81 s. Both active captures and
the actual fault were recorded before exact-PID kills. Orphan pcaps (82,803 / 43,918 bytes) retained. Reset self-test
RED with injected state, GREEN after reset (3.29 s); real detector baseline **11/11**; Ubuntu focused regressions
**127 passed**. No emergency reset used by the interruption probes.

Final data audit: the isolated main store is **22/24**, only A14/A15 (no fresh clones); interruption store's A23
holds, including both killed runs and genuine later detectors. Four historical guest DB hashes unchanged. The
negative F12 timeout store exposed a new writer-format defect: retained partial attempt category NULL with detail
`overall case deadline...` did not match the contract's `case_deadline_exhausted` marker, so A24 rejected its
summary as inconsistent with the completed PASS exchanges. Original data and rejection retained. Minimal follow-up
changes only that detail prefix and adds a regression anchored to `contract.DEADLINE`; verifier predicates are not
relaxed. Final-revision controls/campaign will use new `current/` stores, preserving all prior execution. No FULL
acceptance claim; E/F remain resource-blocked (15.40 GiB at the last gate, below the 20 GiB reserve).

### Overnight final result — PARTIAL ACCEPTANCE — BLOCKED

Final report: [overnight-acceptance-20261021.md](overnight-acceptance-20261021.md). Final tested code
`3d7a9f74c81f80a1a84f790f7aa01f5254e5aa0f`, guest source dirty=0. A new separate `current/` campaign reran
both stock baselines **11/11**, full faults **24/24** (25/25 removals), all six mutants (**6/6 caught**, no
runner/infra results or stock dev-b false alarms), both cumulative-delay deadline negatives, TERM/F2 and
KILL/F2/F5 recovery, reset and a real detector session. The corrected F12 deadline marker now satisfies A24;
the earlier rejected data is retained. Mac full unit/inventory **599 passed**, Ubuntu focused **128 passed**.

Proper guest/Mac audit **22/24**, reports equal: only A14/A15 fail for absent fresh-clone trials. Native independent
checks verify **914 indexed files**, **129 flow records**, **96 decoded baseline exchanges/80 READs**, actual mutant
defects and reconstructed gateway timings. Main run 9 commissions both devices; fault/mutant runs commission none.
Interruption/deadline stores remain partial/negative, with their real failures intact; A23/A24 hold for their
final records. The acceptance verifier/F3 implementation was unchanged; the 401-case harness was not rerun.

Final recovery: TERM/F2 GREEN +5.659 s; KILL/F2 GREEN +91.880 s (dead-man cleared fault by +90.228 s);
KILL/F5 GREEN +120.906 s (route restored +90.361 s, ctl capture expired +58.999 s, field capture expired
+119.297 s). Both active captures and actual faults were proven before exact-PID signals, orphan captures retained,
no emergency reset needed by these probes. Reset self-test RED→GREEN, subsequent commissioning **11/11**.

Guest archive and extraction retained **2313 files**, manifest and SHA-256 under E; four historical guest DB hashes
unchanged. At 08:09:50 UTC both protected Witness originals were stopped after GREEN postflight, stock builds,
healthy gateway and no active fault/capture/timer/runner. Four goldens stayed stopped; default-home `vigil` remained
stopped; ARC21/Docker/simulator untouched. No host route/firewall change, deployment, production-data write or push.

Five independent current fresh-clone baselines and fresh-VM reproduction are **BLOCKED — INSUFFICIENT HOST
RESOURCES**, not attempted. Lowest observed available disk **13.801 GiB** (08:20:22 UTC); peak sampled swap
**2487.50 MiB**, final **2270.56 MiB**. Ordinary 10 GiB floor retained; stable ≥20 GiB clone reserve never passed.
Do not count existing-VM controls or historical clones as these experiments. Exact resource-gated resume commands,
protected-original preservation and evidence continuation are in the final report; durable state is E/CHECKPOINT.md.

## Portable external reproduction package — 2026-10-21

Packaging implementation COMPLETE; external execution **UNTESTED**. This assignment did not run another local VM
acceptance campaign and does not close A14/A15 or the outstanding fresh-VM experiment. Historical functional counts
and blocked acceptance above remain unchanged.

`handoff/` implements an executable consent/bootstrap launcher, a serial stdlib coordinator, guest evidence checks,
deadline/interruption probes adapted from the executed overnight helpers, a source-snapshot builder, bounded native
smoke checker, tests, recipient message, detailed handoff and builder verification report. The included runtime is
exactly `f09aa6322e5b8d923b9219b5f90ba32f50b17c0a`; its device/gateway/runner/tests/provisioning files are unchanged
from `3d7a9f7`. No protocol, schema or acceptance predicate was changed. Packaging code is separate from that source.

The distributable is `dist/Witness-Reproduction-f09aa63-v1.zip`, built from 109 tracked source/specification/doc files
with original Git blob/original/export SHA-256 manifests. All historical results, original images/keys/caches,
ignored/untracked files and 453 evidence symlinks are excluded. Original-history scan: 13,988 blobs, 494 with absolute
home paths, zero credential-pattern matches; history is not exported. One historical documentation home-path
reference is redacted in the distributable only. The source snapshot cannot reconstruct full Git history; this
limitation is explicit. The immutable brief retains SHA-256 `07a33a088939c9cc59ef4dbbfb12706ad17431d9eb4d8b5353feafdcea555baf`.

Recipient flow uses a private owned/locked `~/Wit-f09aa63.nosync`, pinned Lima 2.2.0, the original pinned Ubuntu ARM64
image, actual guest provisioning twice, native isolation/management checks, units/adversarial verifier, baseline,
full faults, M1–M6 with stock controls, cumulative-deadline controls/negatives, exact-PID interruption/recovery and
reset checks, five distinct golden restorations and a new image-based VM pair. One newly generated main evidence
store continues through all positive campaigns/restores; diagnostic negatives are separately attributed. No original
passing database is shipped. Final reports require the actual 24-assertion audit and every wrapper experiment.

Entry gate: native Apple Silicon/macOS 13+, >=16 GiB RAM, >=40 GiB free; unsupported smaller hosts block. Each
restore additionally needs the measured logical pair size (>=20 GiB) + 14 GiB reserve/margin, with no APFS credit.
Monitoring stops at 12 GiB free, critical pressure, >4 GiB swap or >1 GiB swap growth; safety commands remain bounded
and operable under that red gate. Owned VMs only; no host routing/firewall, default Lima or Docker changes. Existing
supported Python is reused; otherwise a pinned signed Python.org installer requires explicit recipient consent and
bounded administrator authentication. Homebrew/Git/AI subscriptions are not required.

During verification, the original dated Ubuntu URL was found to redirect to an HTTP archive. The launcher instead
uses the same official archive bucket through HTTPS (`s3.amazonaws.com/cloud-images-archive.ubuntu.com`), whose HEAD
and SHA256SUMS match the unchanged original image pin. No latest-image or unverified transport fallback is used.
Lima's unsupported cache variable was replaced with a separately downloaded/hash-verified local image; the shared
user cache is not needed. Resume preserves newer guest records, prior DB snapshots and atomic transfers.

Executed locally (records: `results/handoff-build-20261021/`): **40 packaging/control tests**, **7 production-contract
fixture integration tests**, **149 focused source unit/inventory tests**, and **10 native non-VM smoke commands**,
all PASS. Native checks use the actual pinned official Lima binary in an empty temporary private home, configure
only its user-v2 network entries and validate both VZ YAML files. They extract into a differently named path with
spaces and execute the exact recipient command twice, exercising the actual 8 GiB host refusal before consent or
VM changes. Python installer signature/hash checked, installer not run. ZIP CRC/checksums, modes, relative paths,
tamper/missing-file failures, resource negatives, unrelated VM-name refusals, checkpoints, continuation preservation,
report verdicts and scoped return archives tested. No full VM campaign or original acceptance verifier rerun here.

Retained development failure: first native smoke's validation failed because its new private home lacked network
entries; harness fixed to create only those entries, then 10/10 PASS. This did not affect original VMs. Missing-keyword
and cache/continuation/cleanup review corrections are documented in `handoff/BUILDER_VERIFICATION.md`.

Preservation recheck: 15,880 original tracked/untracked source/evidence entries unchanged except declared
`.gitignore`/ledger changes; original overnight prompt/console/final-message files retained. No VM, unrelated
project/service, host network, push, deployment or publication operation. Full fresh-machine installation, GUI
permissions, live provisioning/faults/restores and recipient acceptance remain **UNTESTED** until the recipient runs
the package. Send the ZIP plus `dist/MESSAGE_TO_RECIPIENT.txt`; the launcher produces its own completion report and
`RETURN_RESULTS.sh` exports only the recipient's generated output, excluding VM state and credentials.

Release sealed after scoped implementation commit `97cf574` (no runtime changes):
`dist/Witness-Reproduction-f09aa63-v1.zip`, **1,084,525 bytes**, SHA-256
`32d2b7e00cb49f80861910b739cd1db3b1fc6ff645df767b363c5b5155157293`.
Final sealed-archive native smoke is **10/10 PASS** (`final-native/`), and the final wrapper rerun is **40/40 PASS**
(`final-wrapper-tests.log`). Source is self-contained as a clean snapshot; downloads/recipient permissions and real
VM execution remain as explicitly described in the handoff. Send this ZIP and `dist/MESSAGE_TO_RECIPIENT.txt`;
the adjacent `.zip.sha256` is an optional independent transport check. No upload or push occurred.

## Final bounded release — 2026-10-21

Release preparation began at `c3d27b8`, `main`, no remotes; GitHub CLI account `tjsingh143` verified. The user
explicitly authorized private GitHub creation, commits, push and a release reflecting partial acceptance.
This closes the bounded release assignment; it does not begin another development phase.

One resource preflight terminated both remaining experimental branches **BLOCKED — HOST RESOURCES**. Initial
14.090 GiB free / 3893.38 MiB swap / raw pressure 2 on the 8 GiB host, all guests stopped; later 13.307 GiB /
3975.25 MiB / pressure 2. The COW-aware planning budget is 18.013 GiB, including a 10 GiB floor, current golden
allocation as dirty-write allowance, swap, evidence and recovery. Maximum identified disposable-cache reclamation
would reach only 17.465 GiB initially and would not address memory pressure. No cache or VM operation was attempted.
All two originals and four goldens remain stopped/protected with identical disk inode/size/allocation/mtime.
See `docs/final-engineering-report.md` for the measured APFS probe, Lima 2.2 source review and calculation.

The real complete current store was audited and reports regenerated: **22/24**, only A14/A15 missing fresh
baselines/stability. No current fresh clones or current fresh-image VM reproduction were executed. Historical
11/11 commissioning, 24/24 faults, 6/6 mutants and interruption/reset results retain their recorded revision;
no historical trial was relabelled. Original overnight SHA256SUMS **2,527/2,527** verified.

New source/handoff tests **646 passed in 174.06 s**; sealed ZIP native checks **10/10 passed**, no VM boot.
Python AST **72 files**, shell syntax **11 files**, source equality for **75 functional/test/script files** against
`3d7a9f7`, report assertion equality, immutable brief hash, Git whitespace and `git fsck --full` passed. ShellCheck
is unavailable on the host and was not rerun on VMs. An initial release-only report comparison used the JSON
envelope instead of its `assertions` list; corrected once, both command logs retained. No product defect inferred.

README and obsolete start-here entry replaced with the finished project presentation. Added final engineering
report and three-scope reproduction guide; SOP resource/preservation instructions updated. The standard VM template
now explicitly uses the original pinned Ubuntu ARM64 digest via HTTPS, avoiding the retired URL's HTTP redirect;
native Lima validation of both roles and the HTTPS endpoint HEAD passed. Fresh boot/provisioning on this final
template is unverified. Device/gateway/runner/fault implementation, protocol and acceptance predicates are unchanged.

Original history scan: **48 commits, 14,083 blobs, 508 home-path blobs, 453 absolute tracked evidence symlinks**;
credential-pattern scans found zero matches. Git integrity passed, with harmless dangling local commits retained.
Publication uses a separate sanitized snapshot in `dist/github-release`, preserving original history/evidence
rather than rewriting it. Source/specs/tests, historical FAIL reports and small attributed evidence are included;
raw results/DBs/pcaps/images, original history, old agent phase prompts, personal paths and links are excluded.
Any publication-only redactions are recorded in the source/evidence manifests. Private publication and remote
commit/tag verification are recorded in the final release command evidence. Original pre-existing untracked
prompt/console/final-message files remain untouched and are excluded from publication.

Clean-publication installation was actually attempted: bundled Python 3.9 could not install pinned pytest, and
an unselected pyenv shim could not resolve 3.14; supported-version selection is now explicit in README/SOP/guide.
A fresh Python 3.14 venv installed requirements successfully. First broad snapshot run: **605 passed, one README
label failure, 40 missing-ZIP setup errors**. Corrected the catalog label and separated source-only 606 tests from
the 40 sealed-ZIP tests; focused README check and artifact-dependent 40 tests PASS. Failed commands retained.
Full synthetic adversarial self-test hit its **900 s bound (exit 124), no final verdict**, and was not retried;
its positively identified generated synthetic workdir was cleaned with a record. The real-evidence 22/24 audit
completed independently and is unchanged. Original source/test/runtime bytes remain unchanged.

Corrected source-only reproduction from the new isolated checkout/venv: **606 passed in 188.00 s**. Separate
ZIP-dependent checks: **40 passed in 2.21 s**. A publication-manifest review caught a regex literal incorrectly
redacted by the initial unpublished exporter; redaction is now documentation-only and executable byte equality
is mandatory. The initial candidate is retained in `dist/github-publication`; the final clean snapshot is
`dist/github-release`. No original history or runtime code was rewritten.

## Final presentation and Drive review — 2026-10-22 (Pacific)

Current presentation describes the final delivered Witness project without a person or AI creator byline.
The overview no longer uses preview or partial-acceptance release framing. The measured 22/24 acceptance
result, A14/A15 failures, separate fresh-image obligation, incomplete synthetic verifier and untested recipient
execution remain explicit in verification sections. No acceptance predicate, runtime/test file, original brief,
historical FAIL record or sealed release asset changes. The existing tag remains an archival identifier.

The uploaded Drive review contained 49 files. Its checksums, 22 exact archival copies, six literal excerpts,
36 source-backed claims and three SVGs were checked against the selected publication tree. Current navigation
is updated to observed Drive URLs. This is presentation/package verification, not a new VM campaign or runtime
suite. Source catalog/README consistency is checked for this documentation change. Export hashes are updated
in PUBLICATION_PROVENANCE.json; original hashes and source objects remain unchanged.
