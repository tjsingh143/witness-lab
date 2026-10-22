# Witness independent engineering and acceptance audit

**Verdict: FAIL — material correctness defects remain.**

Audit date: 2026-10-17. Repository: `<original-home>/Desktop/Witness/witness-lab`. Reviewed HEAD: `04c0fb5`; reported final code: `633df97`. This was an independent verification exercise. No implementation, acceptance criteria, historical evidence, or Git history was repaired or replaced.

The lab is real and substantially implemented. Independently executed checks passed **185 unit tests on macOS, 185 on Ubuntu, 11 full-baseline VM tests, and 24 fault VM tests covering F1–F13**. Historical evidence supports five restored-environment baselines, a fresh-VM reproduction on this host, and detection of all six specified mutants. All 11,265 historical evidence-file hashes and lengths matched the database.

Those results do **not** establish complete acceptance. In a separate real-VM run containing only two HEALTH tests, the production report declared both devices commissioned and asserted that all commissioning cases passed. Other reproduced defects affect gateway recovery, the documented case deadline, retry attribution, request validation, acceptance assertions, and F3 packet evidence. Findings below comprise **one P1, six P2, and one P3; no P0 was found**. They are sufficient to reject the handoff statement that no mandatory item is failed or unverified.

## 1. Authority, method, and evidence boundaries

I read `PROJECT_BRIEF.md` before using the implementation's acceptance reports, then read `AGENTS.md` and `docs/implementation-state.md`. The matrix below was reconstructed from the brief, including its deliverables and definition of done, rather than copied from the existing matrix. The finalized protocol and requirements supply the brief's explicitly delegated contract details; they cannot excuse unmet original objectives.

The brief's SHA-256 remained `07a33a088939c9cc59ef4dbbfb12706ad17431d9eb4d8b5353feafdcea555baf`. The original database remained `95bb9f374da672813816eab72b7cc658356e542256bfd00891962e37337bbca1`, with maximum run ID 130. Original database inspections used SQLite `mode=ro`; deliberately modified database experiments used a disposable backup outside the repository.

Audit evidence is retained at **`/tmp/witness-independent-audit-20261017/`** on the Mac. Its `*.log` files record UTC timestamps, commands, return codes, and output. `vm/` contains the independently generated database, 406 indexed evidence files, and the additional protocol capture/transcript. The transferred archive `vm-evidence.tar` is 2,508,800 bytes, SHA-256 `7d5892d32117c0b57000bc3e8b171be1a4645d1cfe363d338d1ed6e57338a181`. The guest copies remain under `/tmp/witness-independent-audit-20261017*` on **witness-ctl**. These are audit artifacts, not additions to the original acceptance dataset. `/tmp` is temporary storage: this report embeds the important results and reproduction procedures, but those full audit transcripts/captures should be archived before temporary-file cleanup if long-term retention is wanted. Only this report was added to the repository, as requested.

Evidence labels used below:

| Label | Meaning |
|---|---|
| I | Independently executed during this audit, against the actual two VMs unless explicitly called loopback or synthetic. |
| H | Historical experiment independently checked against stored commands, raw rows, logs and/or captures; not rerun destructively. |
| S | Static implementation/test inspection. |
| PASS | Adequate evidence for the specific row's scope, not a global certification. |
| PARTIAL / FAIL | A stated limitation or confirmed finding prevents the broader acceptance claim. |

All live commands used the repository's private `LIMA_HOME=.lima.nosync` and explicitly named Witness guests. Before faults, I checked free space, VM identities/MACs, routes, isolation rules, device builds/modes, capture state, clock offset, and the working vsock recovery path. I inspected the fixture setup/finally teardown, allowlisted fault agent, process identity checks, guest dead-man timers, and scoped reset paths before running the existing suite. No host firewall/routes, unrelated service configuration, VM recreation, or Lima `vigil` operations were performed. No new mutant campaign or interruption experiment was needed to confirm the reported historical results.

## 2. Original-brief acceptance matrix

The matrix covers mandatory behavior and artifacts in §§2, 4–11 and 13–15. Time/effort estimates, role research, personal interview fluency, and the optional C port are not software acceptance requirements. Lima is an expressly allowed fallback; an installed 10-GiB guest disk versus the suggested approximately 15–20 GiB is not by itself a defect when the documented disk gate passes.

### Scope, topology, services, and reproducibility

| ID / brief | Mandatory requirement | Implementation / tests inspected | Actual evidence and disposition |
|---|---|---|---|
| B01 §§2,3,15 | Software simulation with real VM traffic; no hardware/firmware or product-identity overclaim | `README.md`, protocol, service names, generated report scope text | **PASS I/S:** Ubuntu processes and VM-to-VM TCP independently exercised. README correctly distinguishes simulation. Completion claims need correction per findings. |
| B02 §§4.3,5,13 | Protocol, inventory and numbered requirements precede tests | Git history; `docs/protocol.md`, `docs/requirements.md`, `inventory.yaml` | **PASS H/S:** specification commit `38e51d5` precedes test commit `ad86fd3` and runner commit `2daade0` in parent order. Do not infer development duration from equal/nearby commit timestamps. |
| B03 §§4.1,11 | Two Ubuntu 24.04 ARM64 VMs with dedicated VM-to-VM lab network | `scripts/lab_vms.sh`, provisioning, `docs/lab-record.md` | **PASS I:** `lima-witness-ctl` and `lima-witness-field`, ARM Ubuntu/Python 3.12.3, kernel `6.8.0-134-generic`, Lima/vz user-v2. VM status and environment transcripts retained. |
| B04 §4.1 | Devices on `field0` dummy interface at 10.77.2.11/.12; ctl static route via field | `provision_ctl.sh`, `provision_field.sh`, inventory, preflight | **PASS I:** ctl route `10.77.2.0/24 via 10.77.1.20 dev lab0`; field dummy addresses confirmed; route/ping gates green. Field owns the destinations locally; IP forwarding need not be enabled. |
| B05 §§4.1,6.3 | Hostname resolution through ctl `/etc/hosts`; distinguish names, addresses, ports | host-block provisioning; F3/F4/F7 tests | **PASS I:** both names resolve normally; swap and missing-name faults distinguish WRONG_IDENTITY and RESOLVE_FAIL. |
| B06 §§4.2,10 | Two separate systemd device services, journald, fault modes; survive restart and reboot; manual TCP session | `device/device.py`, template unit, `faultctl.py`; unit device tests; F1/F12 | **PASS I/H:** current services/listeners and restart tested live; historical `phase2-reboot-20261017T054216Z.log` shows both services active after VM boot with `NRestarts=0`. Device smoke/manual logs and independent raw TCP probes support manual operation. Reboot was not repeated in this audit. |
| B07 §4.2 | Gateway inventory, independent polling, last-seen state, `/inventory` and `/devices/<id>` | `gateway/gateway.py`, unit gateway API/concurrency tests, live C-GATEWAY | **PARTIAL I/S:** API and normal two-device behavior pass; hung-device isolation has meaningful unit assertions. Recovery edge case fails F-02 below. |
| B08 §§4.2,8 | Linux pytest runner, SQLite storage, scripts and SQL-generated Markdown reports | `runner/`, `tests/live/`, scripts | **PASS I/S:** actual ctl execution and isolated audit database; original seven reports reproduce from SQL except generation time. Result semantics have findings F-01/F-04/F-06. |
| B09 §§4.1,11,14 | No home-network/internet access after provisioning; faults confined to identified lab VMs/interfaces/processes | isolation nftables, no-default-route gates, identity/MAC checks, private Lima home, forced-command SSH | **PASS I/H/S for intended lab:** current output-drop rules, no IPv4 default/IPv6 routes, lab-only allows, no forwarding, vsock rescue confirmed. Historical isolation smoke includes denied external probes and deny-with-default-route test. No new external probe or host route/firewall mutation was required. This is not a hostile-tenant hypervisor security assessment. |
| B10 §§7.1,14 | Clean session preflight: qdisc, nft, services, route, hosts, clocks, disk | `scripts/preflight.sh`, live session fixture, fault-agent checks | **PASS I:** initial, pre-fault, post-fault and closing gates green; both VM roles checked, not inferred from a healthy socket. |
| B11 §§6.3,7.1,14 | Fixture teardown on failure; postflight; contamination retained and excluded; emergency recovery | `tests/live/conftest.py`, `runner/lab.py`, `faultctl.py`, `reset_lab.sh`, interruption scripts | **PASS I/H/S within exercised paths:** all 24 independent fault removals verified, all result postflights green. Historical TERM F2 and KILL F5 logs substantiate interruption recovery. SIGKILL cannot run Python finally; guest timers supply bounded eventual recovery. See residual limits. |
| B12 §§7.3,9,13 | Idempotent provisioning and provisioned golden copies | `lab_vms.sh`, provision scripts, stopped golden identities, trial/scratch logs | **PASS H/S:** second scratch provision completes successfully without reinstall/restart churn; restored trials carry distinct provenance. Not reprovisioned in this audit because the implementation must be preserved. |
| B13 §§7.3,13 | Five complete clean no-fault baselines from fresh/restored environments; investigate nondeterminism | trial restore/provision/baseline logs; SQL and raw exchanges | **PASS H for runs 99–103:** each has 11/11 distinct required instances passing, distinct restore IDs and both VM boot IDs. Run 105 adds a refreshed-golden validation. See restore-return-code caveat below. Machine checker is weaker than this evidence (F-06). |
| B14 §§9,10,13 | Tested reproduce-from-scratch path; usable approximately 10-minute README path | README, scratch creation/provision/idempotence/unit/suite/teardown logs | **PASS H on this host with cached image; unverified on another host:** new VM creation and runs 127–129 corroborate the documented path. No fresh-machine Lima installation or uncached download was proved. VMs were not recreated by this audit. |

### Protocol, commissioning, classification, and timing

| ID / brief | Mandatory requirement | Implementation / tests inspected | Actual evidence and disposition |
|---|---|---|---|
| B15 §4.3 | Owned TCP/5020 newline UTF-8 JSON protocol, 4096-byte bound, commands and echoed integer IDs | device parser/server; `runner/client.py`, `runner/classify.py`; client/device/classifier tests | **PARTIAL I/S:** runner framing, incremental reads, EOF/reset and wrong-ID paths are covered; real VM invalid UTF-8 and oversize requests rejected. Device accepts forbidden duplicate keys/raw CR (F-05). |
| B16 §4.4 | Inventory is source of expected identity, firmware, endpoint and commissioning eligibility | inventory loader/schema tests, `cases.identify`, `db.commissioned_devices` | **FAIL I:** correct full-run identity checks exist, but partial runs falsely commission (F-01). |
| REQ-01 §5 | IDENTIFY ≤500 ms with expected serial/identity/version | C-IDENTIFY; `classify` identity-before-latency logic | **PASS I/H for executed full cases:** independent baseline both devices PASS; historical raw payload cross-check found no wrong stock identity. F-01 prevents treating every reported commissioned set as proof. |
| REQ-02 §5 | Wrong identity yields WRONG_IDENTITY and is never commissioned | F7, M1; DB exclusion of observed WRONG_IDENTITY; relevant unit tests | **FAIL as an unconditional commissioning guarantee:** F7 and M1 detect known mismatches, but omitted identity testing is accepted as commissioning (F-01). Independent HEALTH-only run demonstrates the bypass without changing a device's identity. |
| REQ-03 §5 | HEALTH status ok, sensor true, ≤500 ms for commissioned devices | C-HEALTH, predicate validation, classifier schema | **PASS I/H for executed cases:** independent full and partial HEALTH tests pass; raw 216 fair-baseline HEALTH payloads checked. Complete prerequisite enforcement fails F-01. |
| REQ-04 §5 | Fresh READ timestamps within declared ±2-second window with synchronized VM clocks | C-READ-CLOCK, F13-skew; SNTP and chrony checks | **PASS I/H:** baseline fresh; +30s fault STALE_DATA; actual clock gate checked. Contract explicitly uses send−2 through receive+2, with monotonic durations and wall-clock sample timestamps. |
| REQ-05 §5 | Ten READs, strictly increasing seq, nondecreasing ts within process lifetime | C-READ-SERIES, bracketing HEALTH, F13-repeat, M2 | **PARTIAL I/S:** ten-read and seq-reuse stimuli pass their checks. Restart-window attribution can be overwritten by retry (F-04); gateway process-incarnation inference is incomplete (F-02). |
| REQ-06 §5 | Malformed responses classified MALFORMED, bounded/no crash, recorded result | classifier/client unit tests; F10 variants; M3/M4/M5 | **PASS I/H for specified malformed-response cases:** all three F10 variants passed independently; relevant mutants have actual malformed bytes. Broader documented case budget fails F-03; request-side defect is F-05. |
| REQ-07 §5 | Distinguish read/connect timeout from timely but slow valid response, record latency | F2/F4/F6/F8; client/classifier unit tests | **PASS I/H for network observations:** F6 300ms gives PASS_SLOW; 3000ms all-packet delay CONNECT_TIMEOUT; post-handshake delay READ_TIMEOUT. Overall-case contract separately fails F-03. |
| REQ-08 §5 | Restart healthy ≤10 s; gateway recovers within two poll intervals | F12, gateway unit restart test, gateway uptime handling | **FAIL I/S on a reproduced edge case (F-02):** standard live F12 passes; early restart can retain the previous process's sequence baseline beyond 4 s. |
| REQ-09 §5 | Gateway unreachable ≤3P, detection time recorded | GW-F1/GW-F5/GW-F8, concurrent pollers and monotonic transitions | **PASS I/H for tested failure modes:** independent four device-detection measurements 829.567–2287.395 ms, all ≤6000; historical 92 measurements 308.602–2393.385 ms. |
| REQ-10 §5 | Environment every run: both kernels/distros, Python, Git, device fw, qdisc/nft, clean flag | session environment collection, C-ENVIRONMENT, environment tables | **PASS I/H for checked complete baselines; acceptance enforcement PARTIAL:** actual final records present, but SQL assertion accepts missing/blank mandatory fields (F-06). Invalid/mutant runs retain unavailable values and failures rather than inventing firmware. |
| B17 §6.1 | Eleven distinct categories with precedence and useful diagnostics | `classify.py`, catalog, unit classifier/client tests, fault results | **PASS I/H/S for specified observations:** all 11 observed live across baseline/faults; malformed/identity/freshness precede latency. Unknown transport errors deliberately remain runner errors instead of a fabricated device category. Retry can lose that attribution (F-04). |
| B18 §6.2 | Separate connect/read timeouts; overall case bound; nothing unbounded | client deadlines, `cases.read_series/with_retry`, 75s fixture alarm | **FAIL I (loopback):** exchanges are bounded, but documented 30s case cap resets across retries; real execution took 31.637s without deadline error (F-03). This is not a claim of an infinite hang. |
| B19 §6.2 | At most one retry, only idempotent commands; preserve first/final; retry-only success is flake | `with_retry`, attempts/exchanges tables, `decide`, Q5/Q5b | **PARTIAL I/H/S:** attempt cap, retention and failure verdict work; runner/infra errors are misattributed after retry (F-04). Category-based Q5 also cannot represent every predicate-only first-attempt failure. |
| B20 §§6.2,9,12 | Explain budgets, timeout ambiguity and diagnostics | protocol §§5–7; SOP category table; RCA; fault captures | **PASS S/H:** documented rationale and stopped-vs-hung/drop/delay evidence are substantive. Claimed per-case hard cap is inaccurate (F-03). |
| B21 §§7.2,8 | Correct runner/infra/device blame; red preflight cannot blame device | DB CHECK constraints, fixture exceptions, decision functions | **PARTIAL I/S:** DB rejects device attribution on red preflight and pass-with-blame. First-attempt runner/infra failures incorrectly become device flakes (F-04). |

### Required fault catalog

All rows below were independently executed in **audit database run 2**, 24/24 tests, 11 deselected, 114.38 seconds. “Pass” means the intended fault was detected, not successful commissioning. Historical final-code run 119 and fresh-VM run 128 corroborate them. Implementations are in `runner/catalog.py`, `tests/live/test_faults.py`, `tests/live/test_gateway_cases.py`, their fixtures, and `scripts/faultctl.py`.

| Brief fault | Required stimulus / actual observed outcome | Evidence and remaining gap |
|---|---|---|
| F1 | Stop service → CONN_REFUSED; gateway unreachable → CONN_REFUSED | **PASS I:** FT-F1 and GW-F1; start/stop logs, TCP evidence, verified revert. |
| F2 | SIGSTOP → READ_TIMEOUT; SIGCONT teardown | **PASS I:** handshake/read distinction and bounded timeout; process identity checked. |
| F3 | Wrong inventory port 5021 → CONN_REFUSED | **PARTIAL I:** syscall classification and healthy 5020 control pass; captures omit 5021 traffic (F-07). |
| F4 | Unused 10.77.2.13 → CONNECT_TIMEOUT | **PASS I/H:** prediction committed before implementation/run; field does not own the destination and forwarding is disabled; the retained capture shows SYN retries without a response. |
| F5 | Delete ctl device-subnet route → NO_ROUTE | **PASS I/H:** no default route; error occurs locally, so absence of outgoing fault packets is expected. Gateway detects both devices. |
| F6 | 300ms netem → PASS_SLOW; 3000ms including SYN → CONNECT_TIMEOUT; 3000ms data-only → READ_TIMEOUT | **PASS I:** scoped lab0 device-source traffic; distinct handshake/read interpretations supported. |
| F7 | Name swap → WRONG_IDENTITY; additional missing-name variant → RESOLVE_FAIL | **PASS I:** original hosts block restored and postflight verified. |
| F8 | nft silent DROP → CONNECT_TIMEOUT; gateway unreachable | **PASS I:** scoped destination/port rule, no blanket guest/host disruption. |
| F9 | SYN reject/reset → CONN_REFUSED; established-data reject/reset → CONN_RESET | **PASS I:** both stages tested. |
| F10 | Malformed JSON, truncated line, wrong echoed ID → MALFORMED | **PASS I:** all three modes, bytes preserved, normal mode restored. |
| F11 | Mid-session FIN and RST → CONN_RESET | **PASS I:** handshakes/earlier successful exchanges distinguish mid-session close from refusal. |
| F12 | Service restart during polling → healthy within bound and gateway recovery | **PASS I for tested aged process:** device 2.697ms after restart returns, 546.024ms after command sent; gateway 832.948ms after first PASS HEALTH. **Requirement overall FAIL:** early restart counterexample F-02. |
| F13 | +30s clock skew; repeat sequence → STALE_DATA | **PASS I:** both variants, normal mode restored. |

F4/F5 predictions appear in `docs/lab-record.md` history at `fe85e80` before their tests. A real unpredicted result is retained: original run 54, GW-F1, expected CONN_REFUSED but observed CONN_RESET at about 413ms. The stop intersected a poll on an existing connection; this is documented rather than relabeled as the prediction. The fault catalog has **21 variants**, not the handoff's 20 (F-08).

### Mutants, SQL, evidence, and operator deliverables

| ID / brief | Mandatory requirement | Implementation / tests inspected | Actual evidence and disposition |
|---|---|---|---|
| B22 §§7.4,13 | Six actual broken builds; run suite, name violated requirement, report catch rate | `device/mutants.py`, mutant CLI, `analysis.MUTANT_RUNS`, unit mutants | **PASS H/S:** 6/6 distinct mutants, 30/30 valid runs detected; ten invalid runs preserved and excluded. Raw final-run reasons checked below; no live mutant was introduced by this audit. |
| B23 §8 | Normalized linked runs/environment/requirements/cases/devices/faults/results, not one result JSON blob | `runner/db.py` schema and migrations; unit constraints | **PASS I/S:** integrity check ok, no foreign-key violations; attempts/exchanges/evidence/measurements and many-to-many requirement mapping add useful normalization. JSON payloads supplement, not replace, normalized results. |
| B24 §8 Q1 | Failures by device and case across runs | `Q1_FAILURES`, report failure section | **PASS I/S:** query groups device/case/run-kind and retains fails/errors with run counts/range. |
| B25 §8 Q2 | Baseline flakiness across clean runs | `Q2_FLAKY`, fresh-run selection | **PASS I for difference detection; PARTIAL acceptance:** stable failure/absent cases do not constitute five successful baselines (F-06). Actual five trials were independently checked as complete and all-pass. |
| B26 §8 Q3 | Fault expected/observed categories and mismatch counts | `Q3_FAULT_MATCH` | **PASS I/H:** mismatches and unfair-run counts retained, including run 54; expected fault success is not a commissioned device. |
| B27 §8 Q4 | Detection min/median/max per fault | `MEDIAN_CTE`, `Q4_DETECTION`, measurements | **PASS I:** separate Python grouping and median calculation matched every SQL row; runner and gateway cases kept separate. Timing reference points explained below. |
| B28 §8 Q5 | Cases passing only on retry | `Q5_RETRY`, `Q5B_RETRIED`, `decide` | **PARTIAL S/I:** actual M6 retry-only success is correctly shown as fail/flake. Q5 selects category changes rather than first-attempt predicate success; F-04 illustrates lost invalid-window attribution even when first category is PASS. Q5b retains all retries. |
| B29 §8 Q6 | Infra results grouped by run; discard/exclusion visible | `Q6_INFRA`, FAIR filter, DB run flags | **PARTIAL I/S:** contaminated/unfinished/unclean and actual infra rows retained and excluded correctly; F-04 can prevent creation of the appropriate infra/runner attribution. |
| B30 §§8,9,10 | Raw logs, packet captures per fault case, numerical evidence tied to results | evidence table hashes, raw exchange BLOBs, capture filters, journals | **PARTIAL I/H:** 11,265 historical and 406 new indexed artifacts verified; F3 filter loses relevant packets (F-07). Hash integrity alone is not proof that a capture contains the tested flow. |
| B31 §§9.1–9.5 | Protocol, inventory, requirements, lab record, numbered commissioning SOP with category diagnostics | named files and their actual commands | **PASS S for presence and practical content:** substantial operator documentation; commissioning and timeout guarantees currently exceed implementation (F-01/F-03). |
| B32 §§5,9.6,13 | Complete generated REQ → cases → latest results traceability | catalog, `case_requirements`, report latest-fair-non-mutant SQL | **PASS I/S for structural completeness:** 10 requirements, 30 catalog cases, 33 mappings; no unmapped requirement/case. Case labels do not by themselves prove the entire requirement (notably REQ-08). |
| B33 §§9.7–9.9 | Baseline, fault and mutant reports from recorded results | `runner/report.py`, seven report outputs | **PASS I for regeneration and arithmetic; PARTIAL conclusions:** exact regeneration apart from timestamp; findings show that green report assertions are not full acceptance. |
| B34 §§9.10,13 | Evidence-backed RCA with symptom, timeline, wrong hypothesis, diagnosis and improvement | `docs/rca-001.md`, clock/pcap logs | **PASS H/S:** real chrony served-clock drift; paired packet timestamps differ about 1.427s, matching the diagnosis and added clock gate. This was not an invented illustrative incident. |
| B35 §§9.11,13,15 | README reproduction path and honest measured presentation | README, scratch logs, resume scope language | **PARTIAL H/S:** path tested with cached image and simulation stated honestly; unconditional completion and variant count need correction. No GitHub push/publication was performed. |
| B36 §§10,13 | All phase exits and full definition of done satisfied | Entire matrix, actual behavior and evidence | **FAIL:** meaningful experiments exist, but F-01–F-07 prevent unconditional acceptance. C port, TLS/SNMP/UI and personal interview fluency are outside this software verdict. |

## 3. Commands actually executed and results

Tests were run using the existing `.venv` and guest Python/pytest, without package installation or production edits. Routine read-only investigation used `rg`, `sed`, `nl`, `cat`, `git status/log/show/diff`, SQLite read-only queries, `df`, and guest diagnostic reads. Some exploratory `rg` paths/globs did not exist and returned nonzero; they were not test failures. The substantive independently executed commands are listed here. Complete argument lists and UTC times are in the named audit logs.

| Audit log / UTC start | Command or script | Observed result |
|---|---|---|
| `unit-mac.log` 17:59:12 | `.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit tests/test_inventory.py` | rc0, **185 passed in 9.92s**. Loopback/mocked unit checks, not VM evidence. |
| `vm-status.log` 17:59:13 | `scripts/lab_vms.sh status` | Both dedicated guests running, ssh via vsock; expected interfaces/addresses. |
| `preflight-initial.log` 17:59:26 | `scripts/lab_vms.sh preflight` | Both GREEN; field 6605MiB, ctl 6600MiB free; measured offset +0.000052s. Mac disk check: about 10GiB available. |
| `evidence.log` 18:00:24 | `.venv/bin/python /tmp/witness-independent-audit-20261017/evidence.py` | Original DB integrity/FKs and all indexed artifact hashes/lengths checked; disposable backup created. |
| `unit-guest.log` 18:00:25 | `scripts/lab_vms.sh unit` | rc0, **185 passed in 10.78s**, Python 3.12.3. |
| `inspect-ctl.log`, `inspect-field.log` 18:00:48–49 | Explicit private-home `limactl shell --workdir / witness-{ctl,field} -- python3 -` with `guest-inspect.py` | Read-only routes, nft, qdiscs, source metadata/hashes, disk and recovery socket checks. |
| `deployed-compare.log` | `compare-deployed.py` | All 36 ctl and 33 field deployed source-file hashes matched local counterparts. |
| `baseline-independent.log` 18:01:18 | Explicit guest pytest command below, `-m commissioning`, 180s outer timeout | rc0, **11 passed, 24 deselected, 39.65s**. Audit run 1, clean=1, contaminated=0. |
| `adversarial-unit.log` 18:02:01 | `adversarial.py` | Confirmed partial commissioning, retry-attribution and SQL assertion counterexamples. Synthetic/in-memory or disposable DB, not VM runs. |
| `gateway-restart.log` 18:02:40 | `gateway-restart.py` | Actual production DeviceServer/Gateway on Mac loopback: still stale after 4.310s following early restart. |
| `case-deadline.log` 18:02:41 | `case-deadline.py` | Actual loopback exchanges and retries took 31.637s, no 30s runner deadline error. |
| `protocol-vm.log` 18:03:06 | `vm-protocol.py` via explicit ctl shell | Six bounded request variants to each real device; duplicate keys/raw CR wrongly accepted, invalid UTF-8/oversize controls correctly rejected; packet capture retained. |
| `raw-crosscheck.log` 18:03:47 | `raw-crosscheck.py` | Independent median arithmetic matches; baseline provenance and mutant raw reasons inspected; seven reports match except generation time. |
| `preflight-before-faults.log` 18:04:03 | `scripts/lab_vms.sh preflight` | Both GREEN; ctl 6588MiB and field 6605MiB free; offset +0.000226s. |
| `faults-independent.log` 18:04:32 | Guest pytest below, `-m fault`, 220s outer timeout | rc0, **24 passed, 11 deselected, 114.38s**, finished 18:06:27Z. Audit run 2 clean=1, contaminated=0. |
| `f3-pcap.log`, `f3-field-pcap.log` | `tcpdump -nn -r results/evidence/run-119/FT-F3-WRONG-PORT__dev-a/capture{,-field}.pcap 'tcp port 5021'` (each file separately) | Both rc0, **no matching packets**. Same check on new audit run 2 ctl capture also has no matches. |
| `record-checks.log` 23:20:55 | `record-checks.py` | Restore/scratch log cross-check, catalog counts, 72 raw IDENTIFY +216 HEALTH +1440 READ validations with no stock-baseline payload errors. |
| `preflight-final.log` 23:23:37 | `scripts/lab_vms.sh preflight` | Both GREEN after resumed audit, no fault/capture left active. |
| `partial-baseline-vm.log` 23:23:57 | Guest pytest below, `-m commissioning -k test_health`, 90s outer timeout | rc0, **2 passed, 33 deselected, 8.99s**; audit run 3 clean and finished. Production query/report wrongly commissions both devices. |
| `fetch-audit.log` 23:24:11 | `fetch-audit.py`: explicit ctl `sudo tar -C /tmp -cf -` of the audit-named DB/evidence/protocol files, copied and safely extracted on Mac | rc0; archive hash above; 409 files. Original results were not fetched over or overwritten. |
| `new-results.log` 23:24:32 | `new-results.py` | New DB integrity ok; FK check empty; all 406 evidence hashes/lengths correct; 24/24 removals verified; run 3 commissioned set `['dev-a','dev-b']`; acceptance counterexample still 15/15. |
| `shellcheck-guest.log` 23:24:49 | Guest `shellcheck scripts/*.sh scripts/lib/*.sh scripts/witness-fault-ssh` | ShellCheck 0.9.0, rc0, no findings. |
| `postflight-closing.log` 23:25:45 | `scripts/lab_vms.sh preflight` | rc0, both GREEN, completed 23:25:46Z; recorded separately from suite teardown. |
| `gateway-restart-anchored.log` 23:31:47 | `gateway-restart-anchored.py` | Repeated the loopback counterexample with an explicit successful HEALTH immediately after restart: still stale 4.307s after that first PASS HEALTH. |

The live test command form actually used was:

```sh
env LIMA_HOME=<original-home>/Desktop/Witness/witness-lab/.lima.nosync \
  limactl shell --workdir /opt/witness-lab witness-ctl -- \
  sudo env PYTHONDONTWRITEBYTECODE=1 timeout --kill-after=10 180 \
  python3 -m pytest tests/live --live -p no:cacheprovider -rA \
  -m commissioning \
  --db /tmp/witness-independent-audit-20261017.db \
  --evidence-root /tmp/witness-independent-audit-20261017-evidence \
  --run-notes 'Independent audit: no-fault baseline; original results untouched'
```

The fault invocation replaced `180` with `220`, selected `-m fault`, and used notes `Independent audit: F1-F13 with inspected teardown and dead-man safeguards`. The partial invocation used `90`, selected `-m commissioning -k test_health`, and notes `Independent audit: HEALTH-only partial baseline, commissioning completeness counterexample`. A host logging wrapper imposed an additional 240s bound. Direct guest invocation avoided `suite`'s automatic source synchronization; deployed sources had already been hash-verified. These commands should only be repeated after the documented identity/preflight/safety checks, using a new audit-only output path.

## 4. Evidence integrity and claim reconciliation

### Database, artifacts, and arithmetic

The original database contains 130 runs, 1,315 results, 1,125 attempts, 3,904 exchanges, 1,126 measurements, and 11,265 evidence rows. There are 38 baseline runs (37 clean), 52 fault runs, and 40 mutant runs. The contaminated counts are respectively 1, 9 and 4; six fault runs are unfinished. These categories overlap and must not be summed as distinct discarded runs. Every indexed artifact exists and matches its recorded byte length and SHA-256. SQLite integrity is `ok`, and `foreign_key_check` is empty.

Ninety-six indexed pcaps are header-only: 67 C-ENVIRONMENT captures, 19 FT-F5 and two GW-F5 captures, plus eight early run-1 normal-case captures. Environment-only/no-route cases can legitimately emit no relevant packets; the early capture problem is retained in historical records. Empty file counts alone therefore do not prove fabrication or current capture failure. Conversely, a nonempty F3 capture can contain only unrelated gateway/control traffic: F-07 requires checking the actual tested port.

Independent Python grouping and `statistics.median` matched every Q4 SQL count/min/median/max. Historical fair gateway detections total 92: 69 for dev-a, 23 for dev-b; combined range 308.602–2393.385ms. Medians by device are 1515.098 and 1491.615ms. Seventeen F12 measurements give device-health-after-restart-return min/median/max 1.101/2.669/9.619ms, and gateway recovery 842.053/1001.980/1111.286ms. These are different clocks/reference events from fault probe durations; they should not be combined into a generic “latency” claim.

The independent F12 measured 2.697ms after `systemctl restart` returned, **546.024ms from sending that command**, and gateway recovery 832.948ms from first successful HEALTH. Thus the tiny first number is not the duration of restarting a process. The implementation records both reference points and bounds the command path too. Gateway fault detection records command-sent and applied-time variants on the ctl monotonic clock; the reported primary command-sent measurement is conservative relative to application time. API sampling is distinct from the gateway's internal transition timestamp. This normal timing evidence does not resolve F-02's missed early restart.

All seven generated Markdown/JSON outputs can be rebuilt from the original DB with identical content except generation timestamps. This supports report provenance, but does not independently validate the report algorithms. F-01 and F-06 demonstrate why the distinction matters.

### Five clean baselines and scratch reproduction

Original runs **99,100,101,102,103** each have the full 11 unique case/device instances, all pass, clean=1, uncontaminated, and no retry-only success. Both guests have distinct boot IDs for each trial; the restore identifiers are `20261017T130341Z-81188`, `20261017T130553Z-82102`, `20261017T130708Z-82926`, `20261017T130835Z-83781`, and `20261017T130939Z-84589`. Their source is `87d322b`, provisioned after restoring golden `06c92aa`. Run 105 additionally uses a refreshed `87d322b` golden without reprovisioning and also passes all 11.

The first restore command did return **rc1**, owing to the documented RETURN-trap bug; the log nevertheless shows both clones and restore provenance completed. Subsequent provision, preflight and baseline succeeded after the trap fix. Trials 2–5 show successful deletion/reclone of both dedicated working guests. This qualification is material to “five clean restores”: the first restore command itself was not a clean rc0, although the fresh environment and subsequent clean baseline are supported. See `results/logs/phase4-trial{1..5}-golden-restore-*` and matching provision/baseline logs, not just the summary report.

Fresh-VM logs `phase4-scratch-*` show originals moved aside, both VMs created from Ubuntu 24.04 ARM64 image release 20260705 (cached image SHA-256 `7df0201546f75b8bcc1044594c806c35749421ad3c9bc1be2a3ab806cfae39cc`), provision, a second successful provision, 185 unit tests, baseline run127 11/11, fault run128 24/24, and M4 run129 with five expected failing cases and six passing controls/run checks. Logs then restore the original guests and green preflight. Reuse of the image cache, existing Lima installation/network definitions, and copied results history is documented; this proves fresh guests on this host, not an independent fresh host or cold download.

The source metadata for runs127–130 and currently deployed guests is `496bcb8dffff523dcdd538f8fef8d96bbc2f7e3f`, not literally `633df97`. That object exists locally but is not on the current main ancestry. Restricted Git comparisons show no differences from `633df97` in device/gateway/runner/scripts/tests/inventory/dependency/config code; deployed file hashes also match. Consequently the runtime tests remain relevant, but the handoff should preserve this provenance explanation rather than describing every final run as literally stamped `633df97`. Five restored baselines likewise belong to the earlier source revision, with later full baseline/fault/mutant validation providing follow-up evidence.

### Mutants detected for their intended defects

The mutant validity query excludes unclean/contaminated/unfinished runs and runs with infra/runner-attributed results. Raw final-code cases show the intended fault rather than merely a red pytest exit. Stock-device control nonpasses are zero across the valid campaign.

| Mutant | Final original run | Raw observation independently inspected | Valid campaign runs detected |
|---|---|---|---|
| M1 other serial | 120 | IDENTIFY `serial=WIT-0002` for dev-a expected WIT-0001; WRONG_IDENTITY on both attempts | 4/4 |
| M2 sequence reuse after five | 121 | READ sequence 5→1; `seq_not_increasing:1<=5`; STALE_DATA | 5/5 |
| M3 no newline | 122 | Valid-looking JSON bytes without terminator (e.g. 86-byte IDENTIFY); incomplete-frame MALFORMED at bounded read completion | 5/5 |
| M4 wrong ID | 123; scratch129 | Response ID0 for request ID1; MALFORMED `wrong_id` | 6/6 |
| M5 temperature string | 124 | Raw `"temp_c":"22.85"`; MALFORMED `type:temp_c` | 5/5 |
| M6 every seventh request sleeps 2.5s | 125 | Empty response at 2s READ_TIMEOUT; field journal records `build=mutant:slow-7th slept=2.5s`; IDENTIFY retry PASS remains fail/FLAKE | 5/5 |

The ten excluded mutant runs are **77–82, 89–91,110**. Contamination/stale-connection checks, previous attribution behavior and leftover capture handling are documented; they were not deleted. Early harness races and infrastructure failures remain visible. Case-to-REQ mapping sometimes reports more than the direct defect (e.g. C-READ-CLOCK also detects M2's sequence defect); the raw stage/detail is the stronger explanation of why the mutant was caught.

### Cleanup and isolation evidence

`phase4-final-interrupt-TERM-f2-20261017T140637Z.log` shows SIGSTOP active, runner SIGTERM, verified SIGCONT and capture stop, then green preflight. `phase4-final2-interrupt-KILL-f5-20261017T141306Z.log` shows route deletion at 14:13:11.054Z, SIGKILL at 14:13:11.082Z, route recovery by the dead-man at 14:14:41.531Z, and later full green state after the bounded capture expires. Approximately 90.45 seconds of outage is consistent with the timer, not immediate finally cleanup. Failed earlier interruption/capture experiments are preserved, including the run110 contamination that motivated the final capture-idle gate.

The independent fault suite required no manual emergency reset: every application has verified removal and every case postflight is green. Closing preflight confirms the required route/hosts, stock normal devices, no fault nft table/netem/timer/capture, clock synchronization, and active gateway/recovery socket. These checks support safety within the expressly dedicated lab; they do not prove every possible SIGKILL/power-loss timing or malicious concurrent operator interaction.

## 5. Confirmed findings, ordered by severity

### F-01 — P1: A partial baseline falsely commissions devices

**Location:** `runner/db.py:429`, especially line442 and lines445–447; `runner/report.py:84` and line93. Supporting test gap: `tests/unit/test_db_cases.py:153` explicitly accepts an incomplete set.

**Affected requirements:** brief §4.4; REQ-01/02/03/04/05 prerequisites; §§9 and13 trustworthy commissioning report.

**Observed evidence:** `commissioned_devices()` only requires commissioning case IDs that already appear in the selected run. Missing run-level checks also do not disqualify it. An in-memory run with only C-HEALTH/dev-a returns `['dev-a']`. More decisively, independent real-VM audit run3 has exactly two C-HEALTH rows, no IDENTIFY/READ/GATEWAY/C-ENVIRONMENT case rows, yet returns `['dev-a','dev-b']`. `report.commissioning_section()` prints:

> Latest fair baseline run: **3**. Commissioned (all commissioning cases pass, no identity failure, run clean and uncontaminated): **dev-a, dev-b**. Not commissioned: none.

The session does issue IDENTIFY to collect firmware metadata (`tests/live/conftest.py:189`), but calls `classify(o)` without the expected identity and never turns this collection into the omitted commissioning verdicts. That collection does not close this gap.

**Reproduction:** after green preflight on the dedicated lab, use the audit command in §3 with `-m commissioning -k test_health` and a new `/tmp` DB/evidence directory. Open that DB read-only with `sqlite3.Row` and call `runner.db.commissioned_devices(conn, run_id)` and `runner.report.commissioning_section(conn)`. Alternatively insert a single passing C-HEALTH result into a clean finished in-memory baseline with the full catalog loaded, as retained in `adversarial.py`; no VM mutation is needed.

**Consequence:** an operator's normal pytest selection can certify devices whose identity, firmware, freshness and sequence behavior were never verified in that run. The independently tested devices happened to be healthy; this is evidence of an unsound decision rule, not a claim that a deliberately broken live device was commissioned during this audit. A wrong-identity or stale-data device can evade the omitted checks.

**Recommended correction:** define the complete required per-device and run-level case set independently of results present; require successful coverage of every required instance, and reject missing/incomplete/conflicting results. Distinguish partial runs in reporting. Add tests for single-case selection, missing environment/READ/gateway checks, aborted runs and mixed passing/failing duplicates. Do not weaken commissioning to mean “selected tests passed.”

### F-02 — P2: Early restart is missed and gateway recovery exceeds two intervals

**Location:** `gateway/gateway.py:105`–108 and `DeviceState.apply` at lines200–218. Existing restart test: `tests/unit/test_gateway.py:104`–118.

**Affected requirements:** REQ-08 and process-lifetime sequence semantics in §4.3/REQ-05.

**Observed evidence:** the gateway resets its prior sequence only when a new HEALTH uptime is numerically lower than the last sampled uptime. A process restarted soon after the first poll can have a *higher* uptime by the next poll, although its sequence restarted at1. A loopback test using the actual DeviceServer and Gateway with default P=2s recorded old uptime0.014/seq1001, restarted the simulator immediately, then recorded new uptime3.986/seq2 at 4.310s after the new listener was available. State remained `stale`, `restarts_detected=0`, `fresh=false`, despite HEALTH ok and current timestamps.

A second run explicitly anchored the documented recovery reference: an independent HEALTH probe returned PASS 0.001250s after the new listener started. **4.306885s after that first PASS HEALTH**, the gateway was still stale, with new uptime3.997/seq2 and no restart detected (`gateway-restart-anchored.log`). This excludes ambiguity about whether the bound began at listener startup or first successful HEALTH.

**Reproduction:** run the retained `/tmp/witness-independent-audit-20261017/gateway-restart-anchored.py`, or recreate these steps entirely on loopback: instantiate stock Device and advance its process sequence with 1000 `respond(n,'READ')` calls; start DeviceServer on an ephemeral loopback port and default Gateway targeting it; wait for first healthy state; stop/close that server and immediately start a fresh stock DeviceServer on the same port; verify `runner.cases.health` returns PASS; wait 4.3s and inspect `device_json('dev-a')`; stop/join pollers and close server in `finally`. The sequence setup is deliberately accelerated test data, not claimed VM traffic. It reproduces a valid process-lifetime boundary without changing the live lab.

**Consequence:** the new healthy process is compared against the old process's sequence, producing false stale state beyond the recovery limit. It can remain stale until its sequence overtakes the old value; that longer duration is an inference from the code, not a long-duration experiment. The normal restart tests age the old process first (`sleep(2.5*P)`), which ensures the simple uptime-decrease heuristic works and misses this boundary.

**Recommended correction:** track reliable process incarnation, or compare inferred boot time using elapsed monotonic time and a justified uncertainty policy. Do not blindly reset on every sequence regression, which would conceal M2. Add an early-restart regression with successful fresh samples and enforce the same two-interval bound.

### F-03 — P2: The documented 30-second case deadline does not include retry

**Location:** `runner/cases.py:96`–140, particularly per-invocation `t0` at102 and fresh second call at140; `tests/live/conftest.py:37` uses a separate 75s harness backstop. Contract: `docs/protocol.md:210` and `docs/requirements.md` fixed parameters.

**Affected requirements:** §6.2 overall per-case deadline; REQ-05/06 bounded case contract.

**Observed evidence:** actual loopback server responses delayed by1.3s each remain inside the2s read timeout. A bracketed ten-READ case makes12 exchanges, yields PASS_SLOW, and retries12 more. `with_retry(read_series(...))` took **31.636989s**; attempts were15703.752 and15682.692ms. Both categories PASS_SLOW; final decision was `fail/device`, not the documented deadline `error/runner`. Each attempt starts a new case clock, and each exchange can also overrun the remaining case budget because it is not clamped to it.

**Reproduction:** retained `case-deadline.py` subclasses stock Device only to sleep1.3s before `handle_line`, serves it on an ephemeral loopback socket, calls `with_retry(lambda no: read_series(host,port,10,bracket_health=True,no=no))`, prints monotonic elapsed time and `decide`, and closes the server in `finally`. No VM/network fault injection is involved. This script's full parameters are sufficient to reproduce using the unmodified production classes.

**Consequence:** a case can exceed the stated hard cap, while misreporting a deadline violation as a device failure. The75s outer fixture alarm still bounds gross hangs, so this finding does not assert unbounded execution.

**Recommended correction:** pass a single absolute monotonic deadline through setup, all exchanges, pause and retry; clamp each blocking operation to remaining time; preserve partial observations and record expiration with the documented runner attribution. Test the entire two-attempt path near the limit, not just a single read timeout.

### F-04 — P2: Retrying an invalid/runner attempt changes blame to the device

**Location:** `runner/cases.py:150`–170; related category-only retry query at `runner/analysis.py:84`–90.

**Affected requirements:** §7.2 attribution; §6.2 honest retries; §8 Q5/Q6.

**Observed evidence:** the production decision function considers only the final attempt for runner error or invalid restart window. In `adversarial-unit.log`, a first unclassifiable send-timeout attempt alone is `error/runner`; adding a successful second attempt changes it to `fail/device/FLAKE`. Likewise, a first attempt with `restart_observed=True` alone is `error/infra`, but followed by PASS becomes `fail/device/FLAKE`.

**Safe minimal reproduction (pure functions):**

```python
from runner.cases import Attempt, decide
from runner.classify import Observation, Classification
o = Observation('loopback-only', 1, 'READ', 1)
first = Attempt(1, [(o, Classification('PASS', 'latency'))],
                restart_observed=True, note='restart observed')
second = Attempt(2, [(o, Classification('PASS', 'latency'))])
print(decide([first], 'PASS', preflight_green=True))
print(decide([first, second], 'PASS', preflight_green=True))
# error/infra changes to fail/device
```

For the runner-error variant, replace the first classification with `Classification(None,'send','unclassifiable_send_error:timeout')` and remove the restart flag. These are synthetic attempts exercising production logic; no real VM send timeout is claimed.

**Consequence:** a device may be falsely blamed for a harness problem or an unfair observation window. Such an infra event is absent from Q6's infra grouping, and a mutant-validity filter based on result attribution can admit an invalid experiment. Original raw attempts remain available, and a flake is still a failing verdict; the defect is loss of correct attribution, not silent conversion to pass. Category-only Q5 additionally misses retry recovery from a PASS-category predicate failure (e.g. degraded HEALTH); Q5b is the fallback full retry list.

**Recommended correction:** establish attribution across all attempts, retaining runner/invalid-window causes when any attempt was not a fair device test. Either do not retry those attempts or preserve their result-level error attribution. Persist first-attempt predicate/verdict success so Q5 means “passed only on retry,” rather than merely “category changed to PASS.” Add tests for runner→PASS, restart-window→PASS and degraded-HEALTH→healthy retries.

### F-05 — P2: Device accepts request frames forbidden by the owned contract

**Location:** `device/device.py:117`–131, especially `json.loads` at120. Contract: `docs/protocol.md` §2, lines32/54, and bad-request handling §4.

**Affected requirements:** §4.3 explicit framing/contract and consistency of delivered protocol documentation. The runner's response parser correctly rejects these constructs; this is the device request side.

**Observed evidence:** bounded real TCP probes from ctl to **both** field device addresses accepted duplicate `id`, duplicate `cmd`, and raw carriage return with normal IDENTIFY responses. Examples:

```text
{"id":1,"id":2,"cmd":"IDENTIFY"}\n      -> successful IDENTIFY, id=2
{"id":1,"cmd":"READ","cmd":"IDENTIFY"}\n -> successful IDENTIFY, id=1
{"id":1,\r"cmd":"IDENTIFY"}\n           -> successful IDENTIFY, id=1
```

Here `\n` and `\r` denote actual bytes, not escaped JSON string content. Invalid UTF-8 and an oversize frame were rejected as controls. Evidence: `protocol-vm.log`, `vm/witness-independent-audit-20261017-protocol.pcap/.txt`.

**Reproduction:** after dedicated-lab preflight, from ctl use a Python socket with a2s timeout to send any exact frame above to10.77.2.11:5020 (and .12), then read the bounded reply and close. A host-only pure-function check is `Device.parse_request(b'{"id":1,"id":2,"cmd":"IDENTIFY"}')`, which returns `(2,'IDENTIFY',None)`.

**Consequence:** the documented strict receiver behavior is false; duplicate commands/IDs are interpreted by last-key-wins rather than rejected, creating ambiguity between producers/receivers. This is a protocol correctness defect within the lab, not a demonstrated external security exploit.

**Recommended correction:** apply the same duplicate-key and forbidden-byte rules on device requests as on runner responses, preserve bounded error handling, and add parser parity tests for duplicate keys, raw CR, encoding and framing boundaries.

### F-06 — P2: “15/15 acceptance” can remain green with missing environment or failing fresh baselines

**Location:** `runner/analysis.py:240`–246 (A13), lines250–264 (A14/A15), and historical-existence predicate A4 at208–211; interpretation in `docs/implementation-state.md:417`.

**Affected requirements:** REQ-10; §7.3 five successful clean baselines; §13 complete acceptance; §9 accurate reporting.

**Observed evidence:** A13 counts eight *families* of keys, not every required VM/device key or nonempty values. On a disposable copy, deleting field kernel/distro/qdisc/nft, dev-b firmware, git_dirty and chrony.offset, and blanking Python still gives A13 `ok=True`. Separately, changing every fresh-trial HEALTH verdict in runs99–103/105 to fail leaves **all15 acceptance assertions true**. A14 counts distinct restores, A15 checks differing verdicts, and A4 can rely on older unrelated passing runs. A consistently failing fresh trial set is not five successful baselines.

**Reproduction:** use SQLite backup from a read-only original connection into an in-memory or `/tmp` database, never the original. Run these independently and roll back each experiment:

```sql
DELETE FROM environment WHERE key IN
 ('kernel.witness-field','distro.witness-field','qdisc.witness-field',
  'nft.witness-field','fw_version.dev-b','git_dirty','chrony.offset');
UPDATE environment SET value='' WHERE key='python';
-- runner.analysis.audit(copy): A13 remains true
```

```sql
UPDATE results SET verdict='fail', attribution='device'
WHERE run_id IN (99,100,101,102,103,105) AND case_id='C-HEALTH';
-- runner.analysis.audit(copy): 15/15 remain true
```

These are adversarial data fixtures, not alterations to the retained results. The original fresh baselines really passed and their environment was separately checked; this finding concerns the validity of the automated completion gate and its interpretation.

**Consequence:** the acceptance CLI/report cannot substantiate the stronger “all mandatory requirements verified” claim. Stable failure and incomplete environment can receive a green gate.

**Recommended correction:** expand mandatory environment keys for both VMs/every device and validate nonempty/available values; require full case/device coverage, all successful verdicts and no flakes across each selected fresh baseline. Check the intended code revision or declare historical coverage separately. Keep existing descriptive assertions if useful, but add missing acceptance assertions and stop equating their current conjunction with full compliance.

### F-07 — P2: Wrong-port fault packet captures exclude the port under test

**Location:** `runner/lab.py:264` default BPF, `scripts/faultctl.py:570` field capture BPF, `runner/catalog.py:18` (`WRONG_PORT=5021`), and F3 live test/fixture.

**Affected requirements:** §§8–10 root-cause evidence, especially phase6 “pcap capture per case” and F3 refused-vs-unreachable diagnosis.

**Observed evidence:** both capture paths filter `tcp port 5020 or icmp`, while F3 connects to5021. Filtering original run119's ctl and field pcaps for `tcp port 5021` returns no packets; independently repeated F3 audit run2 likewise captures none. A nonempty file can contain gateway traffic on5020 and still lack the fault SYN/RST.

**Safe reproduction:**

```sh
tcpdump -nn -r results/evidence/run-119/FT-F3-WRONG-PORT__dev-a/capture.pcap 'tcp port 5021'
tcpdump -nn -r results/evidence/run-119/FT-F3-WRONG-PORT__dev-a/capture-field.pcap 'tcp port 5021'
```

Both exit successfully with no matching packets. Inspect the two fixed BPF expressions to confirm why. No live fault is necessary.

**Consequence:** the observed syscall/result supports CONN_REFUSED, but the advertised per-case packet evidence cannot independently show that tested flow's SYN/RST. This does not imply F3 was not executed.

**Recommended correction:** derive an allowlisted capture filter from the target endpoint and any control endpoints, including the fault's alternate port on both guests. Verify presence of the relevant flow for cases expected to emit packets; explicitly exempt local resolve/no-route failures. Keep historical deficient captures with an annotation rather than replacing evidence silently.

### F-08 — P3: Documented fault-variant count is off by one

**Location:** `README.md:97`, `docs/implementation-state.md:395`.

**Affected requirements:** §§9 and15 numerical/reporting accuracy.

**Observed evidence / reproduction:** `SELECT count(*) FROM faults` returns **21**; `runner.catalog.FAULTS` contains21 variants spanning13 catalog IDs. The README says “20 variants incl. F7-missing,” although that added variant brings the total to21. The24 live test instances include gateway reuse of faults, so24 is a separate count.

**Consequence:** minor inconsistent public-facing measurement, without changing the demonstrated13-fault coverage.

**Recommended correction:** use13 fault types,21 variants and24 fault-test instances consistently, preferably generated from the catalog/database.

## 6. Unverified items and residual risks

The audit did not create/restore/reboot VMs, rerun provisioning, kill the runner, reinstall dependencies, or rerun all six live mutants. Those historical claims were checked against retained logs, raw data and source, but remain historical observations. An independent cold-machine reproduction, image download, different Lima/macOS version, and another operator following the SOP were not tested. No evidence warrants claiming portability beyond the recorded environment.

The two adversarial timing tests used actual sockets and production classes on **Mac loopback**, not VM networking. They confirm deterministic code defects, but their numeric durations are not VM commissioning measurements. Retry-attribution and acceptance-gate counterexamples used synthetic attempts/disposable database fixtures. Real VM tests confirmed the partial-run report defect and request-parser defect. No source was patched to obtain a finding.

Current isolation checks and bounded teardown are credible for the intended single-operator lab. Exhaustive crash-at-every-instruction, power loss, concurrent-run interference and hypervisor escape testing are outside this audit. Host sleep/clock convergence remains an environmental sensitivity already documented by the implementation; the final current clock gates passed. The 90s fault dead-man and120s capture lifetime imply a recovery interval during which another run must remain blocked by preflight, not an instantaneous restoration guarantee.

Hash equality establishes correspondence between files and recorded evidence, not an independent cryptographic attestation that historical experiments occurred exactly as narrated. Here timestamps, boot IDs, raw sockets, journals, pcaps and independently repeated suites provide substantial corroboration. Missing coverage and incorrect predicates remain possible even when hashes and existing tests are green, as the confirmed findings show.

The audit did not perform a publication/secret-scanning certification, dependency vulnerability scan, hardware validation, or assess the owner's personal interview fluency. It neither pushed nor published anything. The software simulation scope must remain explicit.

## 7. GitHub/resume readiness and final state

**Witness is suitable for a transparently labeled engineering portfolio/work-in-progress repository, but not for an unconditional “complete, independently accepted, production-quality commissioning system” claim at these commits.** Before presenting it as complete, correct and regression-test F-01–F-07, correct the variant count/provenance wording, rerun affected VM acceptance cases, and retain this failed audit alongside subsequent verification. This report deliberately recommends corrections without applying them.

An honest current description can state: “Built a two-VM Ubuntu lab with Python sensor simulators, pytest fault injection, normalized SQLite evidence,13 fault types and11 observed categories; retained experiments detected6/6 deliberate mutants. Independent verification reproduced185 unit tests on each platform and the11-case baseline/24-case fault suite, and identified remaining commissioning and edge-case defects.” Do not turn the historical recovery ranges into a universal bound or call this physical hardware/embedded firmware testing.

The independent full baseline and all24 fault cases finished clean, every fault removal was verified, and closing full preflight was green. Stock device services, normal modes, expected route/hosts, gateway, clock checks, inactive fault/capture timers and vsock recovery access were restored/verified. The audit added only its temporary evidence and this report; the original results DB, brief and implementation are unchanged. No unrelated Lima instance or host networking configuration was operated on.

Final Git status:

```text
?? docs/independent-audit.md
```

No tracked file changes, staged changes, commit, push or publication. `final-preservation.log` in the audit evidence directory records the final status, unchanged brief/database hashes, source-revision comparisons and whitespace check after report creation.
