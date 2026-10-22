# Witness commissioning SOP

Operator procedure for bringing a (simulated) networked sensor device online in the Witness lab and proving
it is the expected device, running the expected version, producing sane fresh data, and visible to the
gateway. **Scope:** the devices are Python processes simulating environmental sensors on a Linux VM
(witness-field); the network traffic between the two Ubuntu 24.04 VMs is real. Nothing here validates
physical electronics or embedded firmware.

Conventions: commands marked **Mac** run from the repo root on the macOS host; **ctl** / **field** run inside
the VM (`LIMA_HOME=$PWD/.lima.nosync limactl shell witness-ctl` or `witness-field`). Expected values come from
`inventory.yaml` (dev-a = `dev-a.lab` 10.77.2.11:5020 WIT-0001 fw 1.0.0; dev-b = `dev-b.lab` 10.77.2.12:5020
WIT-0002 fw 1.0.0). Outcome categories and timeouts are defined in `docs/protocol.md` (sections 5 and 7);
requirements in `docs/requirements.md`.

Release note (2026-10-21): current acceptance is **22/24**, with current fresh-clone trials and fresh-VM
reproduction resource-blocked. Older executed trials below are historical. Start with
[reproduction.md](reproduction.md) for the three verification scopes and current resource budgets.
Before manual Lima commands on the Mac, set `export LIMA_HOME="$PWD/.lima.nosync"` from the repository root.

## A. Provision the lab (once, or after a rebuild)

1. **Mac:** confirm prerequisites: `limactl --version` (validated: 2.2.0), `df -h .`, memory pressure and swap.
   Plan for 16 GiB RAM / 40 GiB free at entry; keep ≥10 GiB free plus measured peak-write and recovery reserve.
   An 8 GiB host is not qualified for the full campaign. Complete
   `python3.14 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`.
2. **Mac:** for a new lab, create the two VMs: `scripts/lab_vms.sh up`. Golden restoration (section F) deletes
   the identified disposable pair: preserve originals and evidence, verify resources and recovery access first.
   Never run a golden clone and the lab VM of the same name at once (same lab0 MAC).
3. **Mac:** provision (idempotent; installs devices, gateway, fault agent, isolation, clocks, routes, names):
   `scripts/lab_vms.sh provision`. Run it a second time: nothing should restart.
4. **Mac:** `scripts/lab_vms.sh status` must show both VMs `Running ssh=vsock`, ctl `lab0 10.77.1.10/24`,
   field `lab0 10.77.1.20/24` and `field0 10.77.2.11/24 10.77.2.12/24`.

## B. Inspect before testing (preflight)

5. **Mac:** `scripts/lab_vms.sh preflight`. Both VMs must print `PREFLIGHT GREEN`. Any `FAIL` line means the
   environment, not the device, is wrong: fix it first (section E). Key checks and what a FAIL means:
   - `identity`: wrong VM; stop.
   - `no-fault-nft`, `qdisc-*`, `no-fault-deadman`, `device-mode-*`, `device-build-*`: leftover fault or
     mutant; run `scripts/lab_vms.sh reset`.
   - `clock-source`, `clock-sync`, `clock-served`: clocks not trustworthy; REQ-04 cannot be judged (see RCA-001).
   - `device-route`, `hosts-block`, `resolve-*`, `route-get-*`, `ping-*`: routing or naming broken.
   - `gateway`: gateway service down or its API not answering.
6. **ctl:** look at the path by hand, in this order (each step only makes sense if the previous one passed):
   1. name: `getent hosts dev-a.lab` → `10.77.2.11`;
   2. route: `ip route get 10.77.2.11` → `via 10.77.1.20 dev lab0`;
   3. host/port: `nc -vz -w2 dev-a.lab 5020`;
   4. process (**field**): `systemctl status witness-device@a`, `ss -ltnp 'sport = :5020'`;
   5. response: `printf '{"id":1,"cmd":"IDENTIFY"}\n' | nc -q1 -w2 dev-a.lab 5020`;
   6. content: the reply's `device_id`, `serial`, `fw_version` equal the inventory row.

## C. Deploy or update a device

7. Add or edit the device row in `inventory.yaml` (device_id, hostname, address inside 10.77.2.0/24, port,
   serial, fw_version, instance). Unit-check the file: `.venv/bin/python -m pytest -q tests/test_inventory.py`.
8. **Mac:** `scripts/lab_vms.sh provision`: generates `/etc/witness/device-<i>.env`, adds the address to
   `field0`, enables `witness-device@<i>`, regenerates the managed `/etc/hosts` block on ctl and the gateway's
   inventory, and restarts only what changed.
9. **field:** `systemctl status witness-device@<i>` is `active (running)`;
   `journalctl -u witness-device@<i> -n 5` shows `listening <addr>:5020 ... build=stock`.

## D. Test (commission)

10. **Mac:** run the commissioning suite against the real devices from witness-ctl:
    `caffeinate -i scripts/lab_vms.sh suite baseline --run-notes "<why>"`. It refuses to run if a device
    reports a mutant build (section G) and records an `error/infra` row for every case if preflight is RED.
11. Read the result: `scripts/lab_vms.sh report && scripts/lab_vms.sh fetch`, then
    `results/reports/commissioning-report.md` section 2. A device is **commissioned** only if the latest
    *fair* baseline run (finished, clean, uncontaminated) has `pass` for every commissioning case on it
    (C-IDENTIFY REQ-01, C-HEALTH REQ-03, C-READ-CLOCK REQ-04, C-READ-SERIES REQ-05, C-GATEWAY REQ-09) and
    C-ENVIRONMENT (REQ-10), with no WRONG_IDENTITY observed for it (REQ-02).
    **Run the complete suite; never a selection.** Since the independent-audit remediation (F-01) the decision
    requires *every* commissioning case of the catalog exactly once (not only the cases that ran), green pre- and
    postflight for each, the recorded firmware equal to the inventory and a stock build. A run made with `-k` or
    one marker subset is reported **PARTIAL** with the missing cases listed, and commissions nothing; the report
    then also shows the latest COMPLETE baseline. The per-device "unmet prerequisites" column says what to fix.
12. A retry that passed is a **FLAKE** (verdict `fail`): treat it as a failure and investigate (Q5 in the
    report). Repeat the baseline: brief 7.3 asks for five clean runs before trusting fault results.
    A retried result that is `error/runner` or `error/infra` means attempt 1 was not a fair device test
    (unclassifiable, cut by the 30 s case deadline, or a restart in the window): fix the harness/lab, not the
    device. Q5 shows each attempt's own outcome.
13. Optional fault verification: `caffeinate -i scripts/lab_vms.sh suite fault` (F1–F13 + gateway cases); each
    fault is applied by a fixture, reverted in `finally`, and covered by a 90 s dead-man timer.

## E. Diagnose each observed category

Use the category in the result row (`observed`), the `detail`, and the per-case evidence directory
`results/evidence/run-N/<case>__<device>/` (`capture.txt`, `capture-field.txt` for faults, journals,
snapshots, `timing.json`). Attribution tells you whose problem it is: `infra` = environment (preflight or
precheck red: the device was never fairly tested), `device` = the device violated a requirement under a green
preflight, `runner` = the harness itself failed.

| Category | What the runner saw | Check next (in this order) | Typical cause in this lab |
|---|---|---|---|
| PASS | correct, ≤ 500 ms, well-formed, right identity | nothing; compare `latency_ms` with earlier runs | — |
| PASS_SLOW | correct, 500 ms < latency ≤ read timeout | `tc -s qdisc show dev lab0` (field), `connect_ms` vs `response_ms` in `exchanges`, CPU load | netem delay (F6-300), overloaded VM |
| RESOLVE_FAIL | name did not resolve (no packet sent) | ctl: `getent hosts <name>`, managed block in `/etc/hosts`, `scripts/lab_vms.sh preflight` `hosts-block` | name missing from `/etc/hosts` (F7-missing); the lab has no DNS server |
| NO_ROUTE | `ENETUNREACH`/`EHOSTUNREACH` at connect, within ms | ctl: `ip route get <addr>`, `ip -4 route` (want `10.77.2.0/24 via 10.77.1.20 dev lab0`), lab0 up | device route deleted (F5); lab0 down |
| CONN_REFUSED | RST to the SYN (fast) | field: `systemctl status witness-device@<i>`, `ss -ltn 'sport = :5020'`, `nft list ruleset`; inventory port | service stopped (F1), wrong port (F3), nft reject (F9) — `ss` LISTEN + RST = firewall, no LISTEN = process |
| CONNECT_TIMEOUT | no SYN-ACK within 1.0 s | capture: SYN with no reply? field capture: did the SYN arrive? `nstat`/`/proc/net/snmp` `InAddrErrors`; `nft list ruleset`; `tc qdisc` | silent drop (F8), unused address behind the router (F4: `InAddrErrors` rises, no ICMP), SYN-ACK delayed > 1 s (F6-3000) |
| READ_TIMEOUT | connected, no response byte within 2.0 s | field: process state `ps -o stat -p <pid>` (`T` = stopped), journal (did the request arrive?), `tc qdisc`; capture: request ACKed but no reply | SIGSTOP (F2), delay > 2 s after the handshake (F6-3000-data), slow build (mutant M6) |
| CONN_RESET | connection closed/reset before a full response | capture `[F.]` vs `[R]` from the device; journal `conn close ... reason=`; nft counters; `systemctl status` restarts | mid-session close (F11), nft reject of data (F9-data), process stopped/restarted mid-exchange (F1/F12 window) |
| MALFORMED | bytes arrived but violate the contract | `detail`: `bad_json`, `truncated:*`, `incomplete:*` (no newline before the deadline), `wrong_id`, `schema:*`; `exchanges.response` holds the raw bytes | device fault modes (F10), broken builds (mutants M3/M4/M5) |
| WRONG_IDENTITY | valid reply from a different device | `detail` names the mismatching fields; ctl `getent hosts <name>`, `exchanges.addr` (which address was dialled), inventory row | name points at the other device (F7), address reuse, wrong serial in the build (mutant M1) |
| STALE_DATA | valid reply, but `ts` outside ±2 s or `seq` not increasing | `detail` (`ts_outside_window:±Ns` / `seq_not_increasing:a<=b`); preflight `clock-*` lines; `chronyc tracking` on both VMs; HEALTH `uptime_s` (restart?) | clock skew (F13 skew, RCA-001), replayed/repeated seq (F13 repeat-seq, mutant M2) |

Rules that prevent false alarms:
- A red preflight/precheck makes the result `error/infra`; never re-label it a device failure.
- A timeout alone does not name a cause (brief 6.1): CONNECT_TIMEOUT vs READ_TIMEOUT already splits the
  candidates; the capture (`capture.txt`, `capture-field.txt`) and `journalctl -u witness-device@<i>` decide.
- An exchange whose connect failed has no local port (`exchanges.local_port` is NULL): match it to packets by
  time, address and the SYN's source port in `capture.txt`.

## F. Reset and recover

14. **Mac:** `scripts/lab_vms.sh reset` removes every lab fault on both VMs (nft `witness_fault*` tables, fault
    qdiscs, the ctl route/hosts block, device modes, SIGSTOP, mutant drop-ins, field captures, dead-man timers),
    then `scripts/lab_vms.sh preflight` must be GREEN. `scripts/lab_vms.sh reset-selftest` proves it.
15. If a VM's management session fails: `limactl stop <vm> && limactl start <vm>` (runtime faults and mutant
    drop-ins live under `/run` and vanish), then `reset` and `preflight` (the ctl `/etc/hosts` block persists).
16. Clean environment from scratch: `scripts/lab_vms.sh golden-restore --yes` (deletes the current lab VMs;
    `limactl protect` refuses protected ones), then `scripts/lab_vms.sh provision`, `scripts/lab_vms.sh
    results-push` (continue the master results DB), `preflight`, suites. Verified five times in Phase 4.

## G. Prove the suite can fail (mutants)

17. **Mac:** `scripts/lab_vms.sh mutant run M1..M6 [reps]` deploys a deliberately broken build on dev-a
    (runtime drop-in), runs the commissioning suite declared as that mutant (run kind `mutant`, never a
    baseline, never commissions), restores the stock build and requires preflight GREEN. Results:
    `results/reports/mutant-report.md`. `scripts/lab_vms.sh mutant restore` / `reset` remove a stuck mutant.
