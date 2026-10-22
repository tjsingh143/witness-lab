# Witness: Linux Device Commissioning and Fault-Injection Lab

**Project brief** | Tj (Taij Singh) | Drafted October 14, 2026
**Status:** not started
**Effort:** MVP about 25-40 hours; full version about 55-90 hours (more if Linux/VM fundamentals are new)

---

## 1. Name

**Witness.** In industrial commissioning, a *witness test* is a test run against written requirements while someone observes and signs off on the result. That is exactly what this lab does: it takes a written requirement, runs it against devices on a real network, records what was expected and what was actually observed, and produces evidence someone else can check. The name also describes the core design rule of the project: the runner is a witness, not a judge. It records first, then classifies, and it never collapses "I didn't get an answer" into a single generic failure.

Folder: `~/Desktop/Witness/`. Suggested repo name: `witness-lab`.

---

## 2. Purpose

Build the missing complement to the application portfolio: evidence that you can

1. deploy and administer software components across real Linux machines,
2. diagnose network and device behavior with standard tools, and
3. turn a written requirement into a repeatable automated test with traceable results.

The existing portfolio already covers data/analysis (Charpy study), full-stack product work (KirtanCut, Arc21), and security assurance (Attest). None of it shows Linux service administration, sockets, routing, or test engineering against a device. Witness fills that gap.

**Honesty boundary (non-negotiable).** This is software simulation with real network traffic between real virtual machines. It is not physical electronics validation and it is not embedded firmware. The Earnest Project (Arduino C/C++, calibration equations, threshold comparison) and the West Advanced role remain described exactly as they were; Witness is what later lets you speak to TCP and Linux specifics honestly, because you will have built and broken them yourself.

---

## 3. Why this project, for these roles (research summary)

**Schneider Electric, Software Engineer Intern, NetBotz team, Andover MA (Summer 2027).** This is the primary target. Schneider's past posting for this team describes NetBotz 750/755 as an IoT device for monitoring data centers, built on a stack of Embedded Linux, C daemons, Java, JavaScript and PostgreSQL, with intern work centered on expanding functionality, customer issues, security vulnerabilities and technical debt. The listed duties include testing NetBotz systems and software and fixing defects, and the posting asks for "the desire to learn software engineering and computer networking." A 2027-cycle summary lists Java, JavaScript or C plus Linux and Git, and says this req targets freshman or sophomore students.

The NetBotz 750 itself supports DHCP, DNS, HTTPS, SMTP, SNMP v1/v3, SSHv2, TCP/IP and TLS 1.2, exposes a REST API, and alerts by email or SNMP based on user-definable sensor thresholds. It is commissioned onto a network as a single-IP appliance with sensor pods behind it. Witness mirrors that *class* of system in miniature: a gateway that knows which devices should exist at which addresses, devices that report identity, health and timestamped readings, and a commissioning process that checks reality against the expected inventory. (Do not name or imitate the Schneider product in the project itself. Describe it generically as "networked environmental sensor devices.")

**Granite River Labs, Hardware Engineering Intern, Santa Clara.** GRL describes its internship as hands-on exposure to "testing, diagnosing, and developing automated test solutions" for signal integrity, protocol and system application-level challenges. Witness speaks to the protocol/system-level and automated-test parts. It does not speak to the instrument side (scopes, VNAs). The GRL deadline is October 31, 2026, so Witness will at most be at an early stage for that application; do not list it as complete.

**Secondary fit.** LLNL Computing intern (Linux, testing, rigor), BAE Software Engineering Intern I, and any validation/test or DevOps-adjacent posting.

---

## 4. What you are building

### 4.1 Topology

Two Ubuntu Server 24.04 LTS (ARM64) virtual machines on your MacBook, connected by a host-only network so the lab cannot touch your home network or the internet once provisioned.

```
           macOS host (UTM, host-only network)
  +---------------------------+        +------------------------------+
  | VM-A  "witness-ctl"       |        | VM-B  "witness-field"        |
  |  - gateway (inventory +   |  L2    |  - device A  10.77.2.11:5020 |
  |    poller + HTTP API)     |<------>|  - device B  10.77.2.12:5020 |
  |  - test runner (pytest)   | hostonly|   (addresses on a dummy     |
  |  - SQLite results DB      |        |    interface "field0")       |
  |  - tcpdump captures       |        |  - tc/netem, nftables faults |
  |  route: 10.77.2.0/24 via  |        |  - systemd: witness-device@  |
  |         VM-B's address    |        |                              |
  +---------------------------+        +------------------------------+
```

Why this shape:

- **Real routing, not just a shared LAN.** The devices live on their own subnet (10.77.2.0/24) attached to VM-B. VM-A only reaches them because you add a static route through VM-B. Deleting that route is one of your faults, and it fails differently from a dead process.
- **Real process boundaries.** Device processes run as systemd services on a different machine than the runner. "Is the process running" and "is the network path working" become separate questions with separate evidence.
- **Hostnames on top of addresses.** The runner and gateway address devices by name (`dev-a.lab`, `dev-b.lab`) resolved through `/etc/hosts` on VM-A. This lets you demonstrate the difference between a naming failure and an addressing failure (Section 6, fault F7).

### 4.2 Components

| Component | Runs on | Language | Job |
|---|---|---|---|
| Device simulator | VM-B (2 instances) | Python (optional C port later) | Answers IDENTIFY, HEALTH, READ over TCP. Has a built-in fault mode switch. |
| Gateway | VM-A | Python | Holds the expected inventory, polls each device on an interval, records last-seen state, serves `GET /inventory` and `GET /devices/<id>` over HTTP. |
| Test runner | VM-A | Python + pytest | Provisions a scenario, injects a fault, sends commands, collects responses/logs/pcaps, classifies the outcome, writes results to SQLite. |
| Results store | VM-A | SQLite | Normalized tables for runs, environment, cases, devices, faults, results. |
| Setup/teardown | both | bash | Idempotent provisioning, reset, preflight checks. |
| Reports | VM-A | Python | Commissioning report (Markdown) and traceability table generated from SQL queries. |

### 4.3 Device protocol (write this first, before code)

Keep it small and explicit. A suggested starting contract, which you should edit and own:

- **Transport:** TCP, port 5020. One request per line, one response per line.
- **Framing:** UTF-8 JSON object terminated by `\n`. Maximum line length 4096 bytes. Anything longer, non-UTF-8, non-JSON, or missing required fields is *malformed*.
- **Request:** `{"id": <int>, "cmd": "IDENTIFY" | "HEALTH" | "READ"}`
- **Response:** must echo the same `id`. A response with the wrong `id` is a protocol error, not a pass.
- **IDENTIFY →** `{"id", "device_id", "serial", "model", "fw_version"}`
- **HEALTH →** `{"id", "status": "ok"|"degraded", "uptime_s", "sensor_ok": bool}`
- **READ →** `{"id", "seq": <int, strictly increasing per process lifetime>, "ts": "<RFC 3339 UTC>", "temp_c": <float>, "rh_pct": <float>}`

Writing the contract first matters because every later classification ("malformed", "wrong identity", "stale data") is only meaningful relative to a written definition. In interviews this is the answer to "how did you know it was wrong?"

### 4.4 Expected inventory

A small file (`inventory.yaml`, also loaded into SQLite) that is the source of truth for commissioning:

| device_id | hostname | expected address | port | expected serial | expected fw |
|---|---|---|---|---|---|
| dev-a | dev-a.lab | 10.77.2.11 | 5020 | WIT-0001 | 1.0.0 |
| dev-b | dev-b.lab | 10.77.2.12 | 5020 | WIT-0002 | 1.0.0 |

Commissioning a device means proving that the thing answering at the expected address is the expected device, running the expected version, producing sane, fresh data.

---

## 5. Requirements (draft; finalize before writing tests)

Write six to ten requirements in your own words before implementing any test. Each must be testable, have a number, and have a pass/fail rule. Starting draft:

| ID | Requirement |
|---|---|
| REQ-01 | Each inventoried device answers IDENTIFY within 500 ms on the lab network, and its `serial` matches the inventory. |
| REQ-02 | A device whose reported identity does not match the inventory is reported as WRONG_IDENTITY and never counted as commissioned. |
| REQ-03 | HEALTH returns `status: ok` and `sensor_ok: true` within 500 ms for a commissioned device. |
| REQ-04 | READ timestamps are within ±2 s of the runner's clock (both VMs time-synced). |
| REQ-05 | Over 10 consecutive READs, `seq` strictly increases and `ts` does not go backwards. |
| REQ-06 | Malformed responses are classified MALFORMED; the runner never crashes or hangs on them. |
| REQ-07 | A response slower than the read timeout is classified TIMEOUT. A response inside the timeout but over the latency budget is PASS_SLOW, with latency recorded. |
| REQ-08 | After a device service restart, the device is healthy again within 10 s and the gateway reports recovery within two poll intervals. |
| REQ-09 | The gateway marks a device unreachable within 3 poll intervals of it going away, and the detection time is recorded. |
| REQ-10 | Every run records its environment: kernel, distro, Python version, git commit, device fw versions, active qdiscs and firewall rules, and whether the run started from a clean environment. |

Every test case in the suite must trace to at least one REQ-ID, and every REQ-ID must have at least one test. That mapping is the traceability table (Section 9).

---

## 6. Outcome categories and fault injection

### 6.1 Outcome categories (the core of the project)

The runner classifies every observation into exactly one category. The point is that each category has a different likely root cause and a different next diagnostic step.

| Category | What the runner saw | Typical causes |
|---|---|---|
| PASS | Correct, timely, well-formed, right identity | n/a |
| PASS_SLOW | Correct but over latency budget | Load, netem delay under the timeout |
| RESOLVE_FAIL | Hostname did not resolve | Missing `/etc/hosts` / DNS entry |
| NO_ROUTE | `EHOSTUNREACH` / `ENETUNREACH` | Missing route, interface down |
| CONN_REFUSED | `ECONNREFUSED` (TCP RST) | Host reachable, nothing listening on that port |
| CONNECT_TIMEOUT | No SYN-ACK within connect timeout | Silent drop (firewall DROP, dead host, wrong address behind a router) |
| READ_TIMEOUT | Connected, but no response line in time | Hung/stopped process, delay larger than timeout, app-level deadlock |
| CONN_RESET | Connection closed or reset mid-exchange | Process crashed or restarted, firewall reject with reset |
| MALFORMED | Bytes arrived, but violate the contract | Bad JSON, truncated line, missing fields, wrong `id` echo |
| WRONG_IDENTITY | Valid response from the wrong device | Swapped address, stale name mapping, address reuse |
| STALE_DATA | Valid response, but `seq`/`ts` violate REQ-04/05 | Clock skew, replayed or cached data |

**Why a timeout alone does not identify the root cause** (have this answer cold): a timeout only says "nothing I was waiting for arrived before my deadline." At least five different situations produce it: a firewall silently dropping packets, a route that sends packets into a host that discards them, a process that is stopped but whose listening socket still exists, a network delay longer than the timeout, or an application deadlock. Separating connect timeout from read timeout already splits these into two groups. A concrete example you will reproduce: if you `kill -STOP` a device process, the kernel still completes the TCP handshake for its listening socket (connections queue in the backlog), so `connect()` succeeds and only the read times out. A process that has *exited* instead gives an immediate RST (CONN_REFUSED). Same "it didn't answer," completely different evidence. The packet capture and the device's `journalctl` log are what turn a timeout into a diagnosis.

### 6.2 Timeout and retry policy

- Separate **connect timeout** (e.g. 1.0 s) and **read timeout** (e.g. 2.0 s), plus an overall per-case deadline. Nothing in the runner may block without a bound.
- Retries: at most one retry, only for idempotent commands (all three are idempotent here), and **record the first-attempt outcome as well as the final one.** Retries that silently convert failures into passes are how real test suites hide intermittent faults. If a case passed only on retry, it is reported as a flake, not a pass.
- Write down why you chose each number. "500 ms because the lab is a single hop on one machine; production would be measured first" is a fine answer.

### 6.3 Fault catalog

Every fault is applied only inside the lab VMs, applied by a fixture, and removed in that fixture's teardown even if the test fails. MVP needs four; the full version covers all.

| ID | Fault | How to inject | Expected category |
|---|---|---|---|
| F1 | Missing process | `systemctl stop witness-device@a` | CONN_REFUSED |
| F2 | Hung process | `kill -STOP <pid>` (then `-CONT`) | READ_TIMEOUT |
| F3 | Wrong port in inventory | inventory points to 5021 | CONN_REFUSED |
| F4 | Wrong address in inventory | inventory points to 10.77.2.13 (unused) | Predict first, then observe and explain |
| F5 | Missing route | `ip route del 10.77.2.0/24` on VM-A | NO_ROUTE or CONNECT_TIMEOUT (find out which, and why) |
| F6 | Delayed packets | `tc qdisc add dev <if> root netem delay 300ms` (and 3000ms) on VM-B | PASS_SLOW / READ_TIMEOUT |
| F7 | Name points at the wrong device | swap `dev-a.lab` to 10.77.2.12 in `/etc/hosts` | WRONG_IDENTITY |
| F8 | Silent drop | nftables rule dropping TCP 5020 | CONNECT_TIMEOUT |
| F9 | Active reject | nftables rule rejecting with TCP reset | CONN_REFUSED / CONN_RESET |
| F10 | Malformed data | device fault mode `malformed`, `truncated`, `wrong-id` | MALFORMED |
| F11 | Mid-session drop | device fault mode `close-after:N` | CONN_RESET |
| F12 | Service restart | `systemctl restart` during a polling window | Recovery time per REQ-08 |
| F13 | Stale/skewed data | device fault mode `clock-skew:+30s` or `repeat-seq` | STALE_DATA |

**MVP set:** F1, F2, F6, F10. They cover the four outcomes the brief requires the operator to distinguish: no response, wrong device identity (add F7 as soon as possible), malformed data, delayed response.

For F4 and F5, write your prediction in the lab notebook before running. Whether you see an ICMP error or a silent timeout depends on how VM-B handles a packet for an address it doesn't own and whether it forwards; figuring that out with `tcpdump` is the learning.

**netem note.** `tc ... netem` needs the `sch_netem` kernel module. If `sudo modprobe sch_netem` fails on your VM's kernel, install `linux-modules-extra-$(uname -r)`. Apply netem to VM-B's lab-facing interface, and remember it affects all traffic on that interface, including your SSH session; filtering by port is a stretch goal.

---

## 7. Repeatability, isolation, and blame attribution

### 7.1 Fixtures that reset state

- A session-scoped fixture verifies the lab is clean at start: no netem qdiscs, no lab nftables rules, both device services active, route present, `/etc/hosts` matches inventory, clocks synced.
- Each fault fixture applies its fault and **always** reverts it in teardown (`yield` fixtures with `try/finally`).
- After each case, a postflight check confirms the revert worked. If it didn't, every later result in that run is suspect, and the run is marked contaminated.

### 7.2 Separating runner bug, infrastructure failure, and device failure

Every non-PASS result gets an `attribution` field:

| Attribution | Rule |
|---|---|
| **runner** | An exception came from harness code itself (parse bug, fixture bug, assertion in the wrong place), or the result could not be classified at all. |
| **infra** | Preflight failed: VM-B not pingable, route missing when it should exist, leftover qdisc, clocks out of sync, disk full. The device was never fairly tested. |
| **device** | Preflight was green, the fault (if any) was the intended one, and the device's behavior violated a requirement. |

A result attributed to "device" while preflight was red is a false alarm, and your reports should make that impossible.

### 7.3 Clean-environment reruns

- Provisioning scripts are idempotent: running them twice produces the same state.
- Keep a provisioned "golden" copy of each VM (UTM can clone a VM) so a clean environment is minutes away.
- Baseline: run the full suite five times from clean with no faults. Any case that does not pass all five times is nondeterministic and gets investigated and written up before fault results are trusted.

### 7.4 Proving the suite can fail

Add deliberately broken device builds ("mutants"), selected with a flag:

- returns the other device's serial,
- reuses `seq` after 5 reads,
- omits the trailing newline,
- echoes the wrong `id`,
- reports `temp_c` as a string,
- sleeps 2.5 s on every 7th request.

Run the suite against each. Report how many mutants were caught and by which requirement. A suite that never fails proves nothing; this is the evidence that yours detects what it claims to.

---

## 8. Results database

Store normalized rows, not a JSON blob, so SQL can answer real questions.

```sql
CREATE TABLE runs (
  run_id INTEGER PRIMARY KEY, started_at TEXT, finished_at TEXT,
  git_sha TEXT, clean_env INTEGER, contaminated INTEGER, notes TEXT);
CREATE TABLE environment (
  run_id INTEGER REFERENCES runs, key TEXT, value TEXT);   -- kernel, python, fw versions, qdiscs...
CREATE TABLE requirements (req_id TEXT PRIMARY KEY, text TEXT);
CREATE TABLE cases (
  case_id TEXT PRIMARY KEY, req_id TEXT REFERENCES requirements, description TEXT);
CREATE TABLE devices (
  device_id TEXT PRIMARY KEY, hostname TEXT, expected_addr TEXT, port INTEGER,
  expected_serial TEXT, expected_fw TEXT);
CREATE TABLE faults (fault_id TEXT PRIMARY KEY, kind TEXT, params TEXT);
CREATE TABLE results (
  result_id INTEGER PRIMARY KEY, run_id INTEGER REFERENCES runs,
  case_id TEXT REFERENCES cases, device_id TEXT REFERENCES devices,
  fault_id TEXT REFERENCES faults,
  expected_category TEXT, observed_category TEXT,
  first_attempt_category TEXT, attempts INTEGER,
  latency_ms REAL, detection_ms REAL,
  verdict TEXT CHECK (verdict IN ('pass','fail','error')),
  attribution TEXT CHECK (attribution IN ('none','runner','infra','device')),
  evidence_path TEXT, observed_at TEXT);
```

Queries the report must run (write these yourself; they are interview material):

1. Failures by device and case across all runs.
2. Cases whose verdict differs across clean baseline runs (flakiness).
3. For each fault, expected vs observed category, with mismatch count.
4. Detection time per fault: min, median, max.
5. Cases that passed only after retry.
6. Results attributed to infra, grouped by run, to show which runs should be discarded.

---

## 9. Deliverables

1. **Protocol contract** (`docs/protocol.md`).
2. **Expected inventory** (`inventory.yaml`).
3. **Requirements list** (`docs/requirements.md`).
4. **Lab record** (`docs/lab-record.md`): VM names, interfaces, addresses, routes, ports, service names, process versions, and the exact restart/stop/status commands for every component.
5. **Commissioning SOP** (`docs/commissioning-sop.md`): numbered steps an operator would follow to bring a new device online and confirm it, including what to check when each category appears.
6. **Traceability table**: REQ-ID → case IDs → latest result, generated from SQLite.
7. **Clean baseline report**: five clean runs, nondeterminism noted.
8. **Fault-injection results**: expected vs observed category and detection time for each fault.
9. **Mutant report**: which broken builds were caught, by which requirement.
10. **One root-cause report** (`docs/rca-001.md`): pick one real surprise you hit (F4 or F5 are good candidates), and write symptom, timeline, evidence (log excerpts and a pcap screenshot or `tcpdump` text), root cause, why the first hypothesis was wrong, and the fix or detection improvement.
11. **README** with a 10-minute reproduce-from-scratch path and an honest scope statement.

---

## 10. Build plan

Hours assume the work is new to you; they are estimates, not measurements.

| Phase | Work | Hours | Done when |
|---|---|---|---|
| 0. Paper first | Protocol, inventory, REQ-01..10, outcome categories | 3-4 | You can explain each category's likely cause without notes |
| 1. VMs and network | Install UTM, two Ubuntu Server ARM64 VMs, host-only network, static addresses, dummy interface on VM-B, static route on VM-A, `/etc/hosts`, time sync | 5-8 | `ping 10.77.2.11` from VM-A works, and you can explain why |
| 2. Device service | Python device, systemd template unit `witness-device@.service`, logs to journald, fault-mode switch | 4-6 | Both devices survive restart and reboot; `nc` session works by hand |
| 3. Runner core | Socket client with bounded timeouts, parser, classifier, SQLite writer | 5-7 | Every category in 6.1 can be produced by a hand-written fake |
| 4. MVP faults | Fixtures for F1, F2, F6, F10; preflight/postflight; first report | 5-8 | Clean run + 4 faults reproducible from a fresh clone |
| **MVP total** | | **~25-35** | |
| 5. Gateway | Poller, inventory API, detection-time measurement, F12 | 5-8 | REQ-08 and REQ-09 measured |
| 6. Remaining faults | F3-F5, F7-F9, F11, F13; pcap capture per case | 8-12 | Full fault table filled in with observed results |
| 7. Mutants and baseline | Broken builds, 5x clean baseline, flake analysis | 5-8 | Mutant catch rate reported |
| 8. Docs | SOP, RCA, traceability, README | 8-12 | A stranger could reproduce it |
| 9. Optional C device | Port device to C with `poll()`, same contract, same suite | 8-15 | Suite passes unchanged against the C build |

At 8-10 hours a week alongside classes, the MVP is roughly 3-4 weeks.

---

## 11. Tools and environment

- **Host:** your Apple Silicon MacBook.
- **Hypervisor:** UTM (free, wraps QEMU and Apple's virtualization framework). Use **Ubuntu Server 24.04 LTS for ARM64**, not the x86 image. Give each VM 1-2 GB RAM and ~15-20 GB disk.
- **Network mode:** **Host Only** for the lab network (VM-to-VM and host access, no internet). Temporarily add a Shared Network adapter, or switch modes, only while installing packages, then remove it. Do **not** use "Emulated VLAN": each VM gets its own private VLAN in that mode, so the VMs cannot see each other.
- **Known UTM risks to check on day one:** users have reported Bridged mode failing to boot on some newer Macs, the host-only/shared subnet changing between sessions, and, after a recent macOS update, network-mode changes hanging for every mode except Emulated VLAN. Mitigations: use static addresses on the lab network and record them; verify VM-to-VM ping before building anything else. If UTM's VM-to-VM networking won't work on your macOS version, fall back to **Lima**, which you already have installed, using its user-mode v2 network that lets VMs reach each other (verify against current Lima docs before relying on it). Record whichever you use in the lab record.
- **On the VMs:** `iproute2` (`ip`, `ss`, `tc`), `nftables`, `tcpdump`, `curl`, `netcat-openbsd`, `chrony`, `sqlite3`, Python 3.12 with `pytest`. Open captures in Wireshark on the Mac.
- **Diagnostics you should be fluent in by the end:** `ip addr`, `ip route get <addr>`, `ss -ltnp`, `systemctl status`, `journalctl -u ... --since`, `tcpdump -nn -i <if> port 5020`, `tc qdisc show`, `nft list ruleset`, `getent hosts dev-a.lab`.
- **Cost:** $0. No hardware purchase.

### Suggested repo layout

```
witness-lab/
  README.md
  inventory.yaml
  docs/            protocol.md  requirements.md  lab-record.md
                   commissioning-sop.md  rca-001.md
  device/          device.py  mutants.py  witness-device@.service
  gateway/         gateway.py  witness-gateway.service
  runner/          client.py  classify.py  db.py  report.py
  tests/           conftest.py  test_commissioning.py  test_faults.py
  scripts/         provision_ctl.sh  provision_field.sh  reset_lab.sh  preflight.sh
  results/         witness.db  captures/  reports/
```

---

## 12. Understand for interviews

Build each of these into the lab so you can answer from something you saw, not something you read.

- **Processes and services:** what systemd does on `restart` vs `stop`; how `kill -STOP` differs from `kill -TERM`; where logs go; how to tell a crashed service from a stopped one.
- **Sockets and ports:** listening vs connected sockets; what `ss -ltnp` shows; why `ECONNREFUSED` is fast and a DROP is slow.
- **Routing:** how VM-A decides where to send 10.77.2.11 (`ip route get`); what changes when the route is deleted; host vs network unreachable.
- **TCP behavior:** the three-way handshake; RST vs FIN; why a stopped process can still accept connections; what a packet capture of each fault looks like.
- **DNS vs addressing:** name → address → host → port → process → correct device. F7 shows a perfectly healthy device being the *wrong* device because the name pointed at it.
- **Timeouts and retries:** connect vs read timeout; why you bound everything; how retries hide flakes; why you record the first attempt.
- **Deterministic tests and isolation:** fixtures that always revert; preflight; clean-environment reruns; why shared state causes order-dependent failures.
- **False alarms:** how infra problems masquerade as device failures, and how attribution prevents it.
- **Diagnostics:** the order you check things in and why (name, route, port, process, response, content).
- **SQL:** the six queries in Section 8, written by you.
- **The timeout question:** Section 6.1, in your own words.

---

## 13. Validation checklist (definition of done)

- [ ] Requirements, protocol and inventory written before any test code (commit history shows it).
- [ ] Traceability table: every REQ has ≥1 case, every case maps to a REQ.
- [ ] Five clean baseline runs from a fresh environment; nondeterminism reported, not hidden.
- [ ] Fault results table with expected vs observed category and detection time for each fault.
- [ ] At least one fault whose observed result differed from your prediction, explained.
- [ ] Mutant suite run; catch rate reported.
- [ ] SQL queries compare failures by device, case and run.
- [ ] Commissioning SOP and one evidence-backed root-cause report.
- [ ] Reproduce-from-scratch instructions tested once on fresh VMs.

---

## 14. Risks

| Risk | Mitigation |
|---|---|
| UTM networking on your macOS version | Verify VM-to-VM ping in Phase 1 before writing code; Lima fallback. |
| netem module missing | `linux-modules-extra-$(uname -r)`. |
| Fault left applied after a crash | Teardown in `finally`, postflight checks, `reset_lab.sh`, contaminated-run flag. |
| SSH session lost when netem/nftables applied | Scope rules to port 5020; keep the UTM console window as a backup way in. |
| Scope creep (TLS, SNMP, web UI) | Out of scope until the full checklist is done. |
| Overclaiming on applications | Use the resume framing below; never call it firmware or hardware validation. |

---

## 15. Resume and application framing (fill numbers in only after you measure them)

Draft line, to be finalized with real results:

> **Witness: Linux Device Commissioning and Fault-Injection Lab** (Python, pytest, bash, SQLite, Linux networking)
> Built a two-VM Linux lab with simulated networked sensor devices, a gateway inventory service and a pytest runner that commissions devices against [N] written requirements; injected [N] fault types (stopped/hung processes, route loss, packet delay, firewall drops, malformed data, identity mismatch) and classified outcomes into [N] distinct categories with [measured] detection times; caught [x/y] deliberately broken device builds; results traced requirement-to-test in normalized SQLite.

Interview one-liner: "I wanted to prove I could take a requirement, deploy the thing on real Linux machines, break it on purpose, and tell the difference between the device being wrong, the network being wrong, and my test being wrong."

---

## Sources

- Schneider Electric NetBotz software intern posting (Summer 2025 version, via The Muse): https://themuse.com/jobs/schneiderelectric/software-engineering-intern
- Schneider Electric internship guide, 2027 cycle summary (Extern): https://www.extern.com/post/schneider-electric-internship-guide
- NetBotz Rack Monitor 750 brochure (APC): https://www.apc.com/salestools/SBRN-B7CKMD/SBRN-B7CKMD_R0_EN.pdf
- NetBotz 750 REST API forum thread (Schneider community): https://community.se.com/t5/EcoStruxure-IT-Forum/Netbotz-750-REST-API/td-p/373290
- Granite River Labs Hardware Engineering Internship: https://www.graniteriverlabs.com/en-us/careers/open-positions/hardware-engineering-internship
- UTM network settings documentation: https://docs.getutm.app/settings-qemu/devices/network/network
- UTM VM setup on Apple Silicon, host-only networking (Portland State course page): https://web.cecs.pdx.edu/~dmcgrath/courses/vms_on_macos.html
- UTM issues on bridged mode and network-mode changes: https://github.com/utmapp/UTM/issues/7658 , https://github.com/utmapp/UTM/discussions/7926 , https://github.com/utmapp/UTM/issues/5128
- sch_netem module requirement (tcconfig troubleshooting): https://tcconfig.readthedocs.io/en/latest/_sources/pages/troubleshooting.rst.txt
