# Witness commissioning report

Generated 2026-10-22T02:48:57.076Z from the SQLite results database only (no hand-entered results).

Scope: software-simulated sensor devices (Python processes) on a Linux VM, exercised over real TCP between two Ubuntu 24.04 VMs. This is not physical hardware or embedded firmware validation.

## 1. Runs

| run | kind | mutant | git | dirty | clean_env | contaminated | started | finished | results | pass | fail | error | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | baseline |  | 3d7a9f74c8 | 0 | 1 | 0 | 2026-10-21T07:56:04.931Z | 2026-10-21T07:56:26.787Z | 11 | 11 | 0 | 0 | overnight final committed revision current-baseline |
| 2 | fault |  | 3d7a9f74c8 | 0 | 1 | 0 | 2026-10-21T07:57:47.683Z | 2026-10-21T07:59:36.560Z | 24 | 24 | 0 | 0 | overnight final committed revision current-faults |
| 3 | mutant | M1 | 3d7a9f74c8 | 0 | 1 | 0 | 2026-10-21T07:59:41.956Z | 2026-10-21T08:00:04.166Z | 11 | 9 | 2 | 0 | overnight current-revision mutant M1; dev-b stock control |
| 4 | mutant | M2 | 3d7a9f74c8 | 0 | 1 | 0 | 2026-10-21T08:00:11.149Z | 2026-10-21T08:00:33.672Z | 11 | 8 | 3 | 0 | overnight current-revision mutant M2; dev-b stock control |
| 5 | mutant | M3 | 3d7a9f74c8 | 0 | 1 | 0 | 2026-10-21T08:00:40.529Z | 2026-10-21T08:01:22.240Z | 11 | 5 | 6 | 0 | overnight current-revision mutant M3; dev-b stock control |
| 6 | mutant | M4 | 3d7a9f74c8 | 0 | 1 | 0 | 2026-10-21T08:01:29.436Z | 2026-10-21T08:01:52.691Z | 11 | 6 | 5 | 0 | overnight current-revision mutant M4; dev-b stock control |
| 7 | mutant | M5 | 3d7a9f74c8 | 0 | 1 | 0 | 2026-10-21T08:01:59.920Z | 2026-10-21T08:02:22.603Z | 11 | 8 | 3 | 0 | overnight current-revision mutant M5; dev-b stock control |
| 8 | mutant | M6 | 3d7a9f74c8 | 0 | 1 | 0 | 2026-10-21T08:02:29.409Z | 2026-10-21T08:03:02.276Z | 11 | 8 | 3 | 0 | overnight current-revision mutant M6; dev-b stock control |
| 9 | baseline |  | 3d7a9f74c8 | 0 | 1 | 0 | 2026-10-21T08:03:07.324Z | 2026-10-21T08:03:29.462Z | 11 | 11 | 0 | 0 | overnight final committed revision current-postmutant-baseline |

`clean_env` = both VMs' full preflight was GREEN at run start. `contaminated` = a postflight or session postflight was red, a fault revert was not verified, or the run never finished; such runs are listed but never used as evidence ("fair" = finished, clean, uncontaminated).

## 2. Commissioning status

A run commissions a device only if (runner/db.py `COMMISSIONING_GAPS`, the catalog's complete commissioning set, never just the cases a run happened to execute): it is a finished, clean (both preflights GREEN), uncontaminated baseline; EVERY commissioning case of the catalog (C-IDENTIFY, C-HEALTH, C-READ-CLOCK, C-READ-SERIES, C-ENVIRONMENT, C-GATEWAY) has exactly one result for the device (run-level cases once per run), each verdict pass with green precheck and postflight; no result in the run observed WRONG_IDENTITY for the device and no other result on it is non-pass; the firmware version the run recorded equals the inventory's; the device build is stock; the run's REQ-10 environment record is valid (runner/evidence.py); and the run and these results satisfy the evidence contract (docs/acceptance-contract.md: attempts, exchanges, captures, session evidence, plan; files and packet counts when the evidence directory is given). The devices are the inventory's, never only those the database still lists. The rule is per device: a duplicated per-device instance (an AMBIGUOUS run) blocks that device only; a duplicated run-level instance blocks every device.

Latest fair baseline run:

Run **9**: **COMPLETE** commissioning run (11/11 required instances executed). Commissioned by it: **dev-a, dev-b**.

| device | commissioned | unmet prerequisites |
|---|---|---|
| dev-a | yes |  |
| dev-b | yes |  |

Results of run 9:

| case | device | observed | first attempt | attempts | latency ms | verdict | attribution | detail |
|---|---|---|---|---|---|---|---|---|
| C-ENVIRONMENT | (run) |  |  | 0 |  | pass | none | 15/15 required environment keys valid |
| C-GATEWAY | dev-a | PASS | PASS | 0 |  | pass | none | observed=PASS expected=PASS [gateway dev-a: state=healthy polls=1229] |
| C-GATEWAY | dev-b | PASS | PASS | 0 |  | pass | none | observed=PASS expected=PASS [gateway dev-b: state=healthy polls=1275] |
| C-HEALTH | dev-a | PASS | PASS | 1 | 0.8 | pass | none | observed=PASS expected=PASS [latency: latency_ms=0.8] |
| C-HEALTH | dev-b | PASS | PASS | 1 | 1.2 | pass | none | observed=PASS expected=PASS [latency: latency_ms=1.2] |
| C-IDENTIFY | dev-a | PASS | PASS | 1 | 0.9 | pass | none | observed=PASS expected=PASS [latency: latency_ms=0.9] |
| C-IDENTIFY | dev-b | PASS | PASS | 1 | 1.0 | pass | none | observed=PASS expected=PASS [latency: latency_ms=1.0] |
| C-READ-CLOCK | dev-a | PASS | PASS | 1 | 0.9 | pass | none | observed=PASS expected=PASS [latency: latency_ms=0.2] |
| C-READ-CLOCK | dev-b | PASS | PASS | 1 | 1.2 | pass | none | observed=PASS expected=PASS [latency: latency_ms=0.2] |
| C-READ-SERIES | dev-a | PASS | PASS | 1 | 0.8 | pass | none | observed=PASS expected=PASS [latency: latency_ms=0.2] |
| C-READ-SERIES | dev-b | PASS | PASS | 1 | 1.0 | pass | none | observed=PASS expected=PASS [latency: latency_ms=0.2] |

Environment and contamination of run 9 (REQ-10; full rows in `environment`):

| key | value |
|---|---|
| device_build.dev-a | stock |
| device_build.dev-b | stock |
| distro.witness-ctl | Ubuntu 24.04.4 LTS |
| fw_version.dev-a | 1.0.0 |
| fw_version.dev-b | 1.0.0 |
| git_dirty | 0 |
| git_sha | 3d7a9f74c81f80a1a84f790f7aa01f5254e5aa0f |
| kernel.witness-ctl | 6.8.0-134-generic |
| kernel.witness-field | 6.8.0-134-generic |
| provenance.witness-ctl | long-lived VM (no golden-restore record) boot_id=271b70f0-25f1-4e08-a932-be0c721e5ef2 |
| provenance.witness-field | long-lived VM (no golden-restore record) boot_id=73735e43-4148-444f-8112-8b233219ff51 |
| python | 3.12.3 |
| qdisc.witness-ctl | lab0: qdisc fq_codel 0: root refcnt 2 limit 10240p flows 1024 quantum 1514 target 5ms interval 100ms memory_limit 32Mb ecn drop_batch 64 |
| qdisc.witness-field | lab0: qdisc fq_codel 0: root refcnt 2 limit 10240p flows 1024 quantum 1514 target 5ms interval 100ms memory_limit 32Mb ecn drop_batch 64 field0: qdisc noqueue 0: root refcnt 2 |
| runs.clean_env | 1 |

Fault and mutant runs never commission a device: a fault case whose expected failure was observed has verdict `pass` (the suite detected the fault), not a commissioned device.

## 3. Traceability (REQ -> cases -> latest fair result)

| REQ | requirement | cases | latest result per case/device (fair, non-mutant run) |
|---|---|---|---|
| REQ-01 | Each inventoried device answers IDENTIFY within 500 ms on the lab network, and its identit | C-IDENTIFY, FT-F1-STOPPED, FT-F7-NAME-MISSING, FT-F3-WRONG-PORT, FT-F4-WRONG-ADDR, FT-F5-NO-ROUTE, FT-F8-DROP, FT-F9-REJECT, FT-F9-REJECT-DATA | C-IDENTIFY/dev-a: pass (PASS) run 9 [run-9/C-IDENTIFY__dev-a](../evidence/run-9/C-IDENTIFY__dev-a/); C-IDENTIFY/dev-b: pass (PASS) run 9 [run-9/C-IDENTIFY__dev-b](../evidence/run-9/C-IDENTIFY__dev-b/); FT-F1-STOPPED/dev-a: pass (CONN_REFUSED) run 2 [run-2/FT-F1-STOPPED__dev-a](../evidence/run-2/FT-F1-STOPPED__dev-a/); FT-F3-WRONG-PORT/dev-a: pass (CONN_REFUSED) run 2 [run-2/FT-F3-WRONG-PORT__dev-a](../evidence/run-2/FT-F3-WRONG-PORT__dev-a/); FT-F4-WRONG-ADDR/dev-a: pass (CONNECT_TIMEOUT) run 2 [run-2/FT-F4-WRONG-ADDR__dev-a](../evidence/run-2/FT-F4-WRONG-ADDR__dev-a/); FT-F5-NO-ROUTE/dev-a: pass (NO_ROUTE) run 2 [run-2/FT-F5-NO-ROUTE__dev-a](../evidence/run-2/FT-F5-NO-ROUTE__dev-a/); FT-F7-NAME-MISSING/dev-a: pass (RESOLVE_FAIL) run 2 [run-2/FT-F7-NAME-MISSING__dev-a](../evidence/run-2/FT-F7-NAME-MISSING__dev-a/); FT-F8-DROP/dev-a: pass (CONNECT_TIMEOUT) run 2 [run-2/FT-F8-DROP__dev-a](../evidence/run-2/FT-F8-DROP__dev-a/); FT-F9-REJECT/dev-a: pass (CONN_REFUSED) run 2 [run-2/FT-F9-REJECT__dev-a](../evidence/run-2/FT-F9-REJECT__dev-a/); FT-F9-REJECT-DATA/dev-a: pass (CONN_RESET) run 2 [run-2/FT-F9-REJECT-DATA__dev-a](../evidence/run-2/FT-F9-REJECT-DATA__dev-a/) |
| REQ-02 | A device whose reported identity does not match the inventory is reported as WRONG_IDENTIT | FT-F7-NAME-SWAP | FT-F7-NAME-SWAP/dev-a: pass (WRONG_IDENTITY) run 2 [run-2/FT-F7-NAME-SWAP__dev-a](../evidence/run-2/FT-F7-NAME-SWAP__dev-a/) |
| REQ-03 | HEALTH returns `status: ok` and `sensor_ok: true` within 500 ms for a commissioned device. | C-HEALTH | C-HEALTH/dev-a: pass (PASS) run 9 [run-9/C-HEALTH__dev-a](../evidence/run-9/C-HEALTH__dev-a/); C-HEALTH/dev-b: pass (PASS) run 9 [run-9/C-HEALTH__dev-b](../evidence/run-9/C-HEALTH__dev-b/) |
| REQ-04 | READ timestamps are within ±2 s of the runner's clock. | C-READ-CLOCK, FT-F13-SKEW | C-READ-CLOCK/dev-a: pass (PASS) run 9 [run-9/C-READ-CLOCK__dev-a](../evidence/run-9/C-READ-CLOCK__dev-a/); C-READ-CLOCK/dev-b: pass (PASS) run 9 [run-9/C-READ-CLOCK__dev-b](../evidence/run-9/C-READ-CLOCK__dev-b/); FT-F13-SKEW/dev-a: pass (STALE_DATA) run 2 [run-2/FT-F13-SKEW__dev-a](../evidence/run-2/FT-F13-SKEW__dev-a/) |
| REQ-05 | Over 10 consecutive READs, `seq` strictly increases and `ts` does not go backwards. | C-READ-SERIES, FT-F11-CLOSE-FIN, FT-F11-CLOSE-RST, FT-F13-REPEAT-SEQ | C-READ-SERIES/dev-a: pass (PASS) run 9 [run-9/C-READ-SERIES__dev-a](../evidence/run-9/C-READ-SERIES__dev-a/); C-READ-SERIES/dev-b: pass (PASS) run 9 [run-9/C-READ-SERIES__dev-b](../evidence/run-9/C-READ-SERIES__dev-b/); FT-F11-CLOSE-FIN/dev-a: pass (CONN_RESET) run 2 [run-2/FT-F11-CLOSE-FIN__dev-a](../evidence/run-2/FT-F11-CLOSE-FIN__dev-a/); FT-F11-CLOSE-RST/dev-a: pass (CONN_RESET) run 2 [run-2/FT-F11-CLOSE-RST__dev-a](../evidence/run-2/FT-F11-CLOSE-RST__dev-a/); FT-F13-REPEAT-SEQ/dev-a: pass (STALE_DATA) run 2 [run-2/FT-F13-REPEAT-SEQ__dev-a](../evidence/run-2/FT-F13-REPEAT-SEQ__dev-a/) |
| REQ-06 | Malformed responses are classified MALFORMED; the runner never crashes or hangs on them. | FT-F2-HUNG, FT-F10-MALFORMED, FT-F10-TRUNCATED, FT-F10-WRONG-ID | FT-F10-MALFORMED/dev-a: pass (MALFORMED) run 2 [run-2/FT-F10-MALFORMED__dev-a](../evidence/run-2/FT-F10-MALFORMED__dev-a/); FT-F10-TRUNCATED/dev-a: pass (MALFORMED) run 2 [run-2/FT-F10-TRUNCATED__dev-a](../evidence/run-2/FT-F10-TRUNCATED__dev-a/); FT-F10-WRONG-ID/dev-a: pass (MALFORMED) run 2 [run-2/FT-F10-WRONG-ID__dev-a](../evidence/run-2/FT-F10-WRONG-ID__dev-a/); FT-F2-HUNG/dev-a: pass (READ_TIMEOUT) run 2 [run-2/FT-F2-HUNG__dev-a](../evidence/run-2/FT-F2-HUNG__dev-a/) |
| REQ-07 | A response slower than the read timeout is classified TIMEOUT. A response inside the timeo | FT-F2-HUNG, FT-F6-DELAY-300, FT-F6-DELAY-3000, FT-F6-DELAY-3000-DATA, FT-F4-WRONG-ADDR, FT-F8-DROP | FT-F2-HUNG/dev-a: pass (READ_TIMEOUT) run 2 [run-2/FT-F2-HUNG__dev-a](../evidence/run-2/FT-F2-HUNG__dev-a/); FT-F4-WRONG-ADDR/dev-a: pass (CONNECT_TIMEOUT) run 2 [run-2/FT-F4-WRONG-ADDR__dev-a](../evidence/run-2/FT-F4-WRONG-ADDR__dev-a/); FT-F6-DELAY-300/dev-a: pass (PASS_SLOW) run 2 [run-2/FT-F6-DELAY-300__dev-a](../evidence/run-2/FT-F6-DELAY-300__dev-a/); FT-F6-DELAY-3000/dev-a: pass (CONNECT_TIMEOUT) run 2 [run-2/FT-F6-DELAY-3000__dev-a](../evidence/run-2/FT-F6-DELAY-3000__dev-a/); FT-F6-DELAY-3000-DATA/dev-a: pass (READ_TIMEOUT) run 2 [run-2/FT-F6-DELAY-3000-DATA__dev-a](../evidence/run-2/FT-F6-DELAY-3000-DATA__dev-a/); FT-F8-DROP/dev-a: pass (CONNECT_TIMEOUT) run 2 [run-2/FT-F8-DROP__dev-a](../evidence/run-2/FT-F8-DROP__dev-a/) |
| REQ-08 | After a device service restart, the device is healthy again within 10 s and the gateway re | FT-F12-RESTART | FT-F12-RESTART/dev-a: pass (PASS) run 2 [run-2/FT-F12-RESTART__dev-a](../evidence/run-2/FT-F12-RESTART__dev-a/) |
| REQ-09 | The gateway marks a device unreachable within 3 poll intervals of it going away, and the d | C-GATEWAY, GW-F1-UNREACHABLE, GW-F5-UNREACHABLE, GW-F8-UNREACHABLE | C-GATEWAY/dev-a: pass (PASS) run 9 [run-9/C-GATEWAY__dev-a](../evidence/run-9/C-GATEWAY__dev-a/); C-GATEWAY/dev-b: pass (PASS) run 9 [run-9/C-GATEWAY__dev-b](../evidence/run-9/C-GATEWAY__dev-b/); GW-F1-UNREACHABLE/dev-a: pass (CONN_REFUSED) run 2 [run-2/GW-F1-UNREACHABLE__dev-a](../evidence/run-2/GW-F1-UNREACHABLE__dev-a/); GW-F5-UNREACHABLE/dev-a: pass (NO_ROUTE) run 2 [run-2/GW-F5-UNREACHABLE__dev-a](../evidence/run-2/GW-F5-UNREACHABLE__dev-a/); GW-F8-UNREACHABLE/dev-a: pass (CONNECT_TIMEOUT) run 2 [run-2/GW-F8-UNREACHABLE__dev-a](../evidence/run-2/GW-F8-UNREACHABLE__dev-a/) |
| REQ-10 | Every run records its environment. | C-ENVIRONMENT | C-ENVIRONMENT/(run): pass (n/a) run 9 [run-9/C-ENVIRONMENT__run](../evidence/run-9/C-ENVIRONMENT__run/) |

Traceability gaps (REQ without a case): **none**.

Cases without a requirement: **0**.

Case -> requirement map with fair (non-mutant) execution counts:

| case | kind | requirements | fair results | pass verdicts |
|---|---|---|---|---|
| C-ENVIRONMENT | commissioning | REQ-10 | 2 | 2 |
| C-GATEWAY | commissioning | REQ-09 | 4 | 4 |
| C-HEALTH | commissioning | REQ-03 | 4 | 4 |
| C-IDENTIFY | commissioning | REQ-01 | 4 | 4 |
| C-READ-CLOCK | commissioning | REQ-04 | 4 | 4 |
| C-READ-SERIES | commissioning | REQ-05 | 4 | 4 |
| FT-F1-STOPPED | fault | REQ-01 | 1 | 1 |
| FT-F10-MALFORMED | fault | REQ-06 | 1 | 1 |
| FT-F10-TRUNCATED | fault | REQ-06 | 1 | 1 |
| FT-F10-WRONG-ID | fault | REQ-06 | 1 | 1 |
| FT-F11-CLOSE-FIN | fault | REQ-05 | 1 | 1 |
| FT-F11-CLOSE-RST | fault | REQ-05 | 1 | 1 |
| FT-F12-RESTART | fault | REQ-08 | 1 | 1 |
| FT-F13-REPEAT-SEQ | fault | REQ-05 | 1 | 1 |
| FT-F13-SKEW | fault | REQ-04 | 1 | 1 |
| FT-F2-HUNG | fault | REQ-06, REQ-07 | 1 | 1 |
| FT-F3-WRONG-PORT | fault | REQ-01 | 1 | 1 |
| FT-F4-WRONG-ADDR | fault | REQ-01, REQ-07 | 1 | 1 |
| FT-F5-NO-ROUTE | fault | REQ-01 | 1 | 1 |
| FT-F6-DELAY-300 | fault | REQ-07 | 1 | 1 |
| FT-F6-DELAY-3000 | fault | REQ-07 | 1 | 1 |
| FT-F6-DELAY-3000-DATA | fault | REQ-07 | 1 | 1 |
| FT-F7-NAME-MISSING | fault | REQ-01 | 1 | 1 |
| FT-F7-NAME-SWAP | fault | REQ-02 | 1 | 1 |
| FT-F8-DROP | fault | REQ-01, REQ-07 | 1 | 1 |
| FT-F9-REJECT | fault | REQ-01 | 1 | 1 |
| FT-F9-REJECT-DATA | fault | REQ-01 | 1 | 1 |
| GW-F1-UNREACHABLE | fault | REQ-09 | 1 | 1 |
| GW-F5-UNREACHABLE | fault | REQ-09 | 1 | 1 |
| GW-F8-UNREACHABLE | fault | REQ-09 | 1 | 1 |

## 4. Fault-injection results

Catalog (runner/catalog.py; `faults` table agrees): **13 fault types** (brief F1-F13), **21 fault variants** (e.g. F6 has three, F7 two), **24 live fault-test instances** (fault cases; the gateway cases reuse F1/F5/F8) and 11 commissioning instances for 2 devices.

### 4a. Latest fair result per fault variant

| fault | catalog | run | case | expected | observed | verdict | connect ms | response ms | latency ms | detection ms | read end | local port | postflight | dialled-flow packets | evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| F1 | F1 | 2 | FT-F1-STOPPED | CONN_REFUSED | CONN_REFUSED | pass | 0.3 |  |  | 0.5 |  |  | green | ctl 4, field 4 | [run-2/FT-F1-STOPPED__dev-a](../evidence/run-2/FT-F1-STOPPED__dev-a/) |
| F1 | F1 | 2 | GW-F1-UNREACHABLE | CONN_REFUSED | CONN_REFUSED | pass |  |  |  | 2239.6 |  |  | green |  | [run-2/GW-F1-UNREACHABLE__dev-a](../evidence/run-2/GW-F1-UNREACHABLE__dev-a/) |
| F2 | F2 | 2 | FT-F2-HUNG | READ_TIMEOUT | READ_TIMEOUT | pass | 0.3 |  |  | 2014.1 | timeout | 38992 | green | ctl 11, field 11 | [run-2/FT-F2-HUNG__dev-a](../evidence/run-2/FT-F2-HUNG__dev-a/) |
| F3 | F3 | 2 | FT-F3-WRONG-PORT | CONN_REFUSED | CONN_REFUSED | pass | 0.2 |  |  | 0.5 |  |  | green | ctl 4, field 4 | [run-2/FT-F3-WRONG-PORT__dev-a](../evidence/run-2/FT-F3-WRONG-PORT__dev-a/) |
| F4 | F4 | 2 | FT-F4-WRONG-ADDR | CONNECT_TIMEOUT | CONNECT_TIMEOUT | pass | 1011.5 |  |  | 1012.9 |  |  | green | ctl 2, field 2 | [run-2/FT-F4-WRONG-ADDR__dev-a](../evidence/run-2/FT-F4-WRONG-ADDR__dev-a/) |
| F5 | F5 | 2 | FT-F5-NO-ROUTE | NO_ROUTE | NO_ROUTE | pass | 0.0 |  |  | 0.2 |  |  | green |  | [run-2/FT-F5-NO-ROUTE__dev-a](../evidence/run-2/FT-F5-NO-ROUTE__dev-a/) |
| F5 | F5 | 2 | GW-F5-UNREACHABLE | NO_ROUTE | NO_ROUTE | pass |  |  |  | 1585.9 |  |  | green |  | [run-2/GW-F5-UNREACHABLE__dev-a](../evidence/run-2/GW-F5-UNREACHABLE__dev-a/) |
| F6-300 | F6 | 2 | FT-F6-DELAY-300 | PASS_SLOW | PASS_SLOW | pass | 310.7 | 309.4 | 620.3 | 621.2 | newline | 50066 | green | ctl 10, field 10 | [run-2/FT-F6-DELAY-300__dev-a](../evidence/run-2/FT-F6-DELAY-300__dev-a/) |
| F6-3000 | F6 | 2 | FT-F6-DELAY-3000 | CONNECT_TIMEOUT | CONNECT_TIMEOUT | pass | 1003.4 |  |  | 1004.4 |  |  | green | ctl 20, field 20 | [run-2/FT-F6-DELAY-3000__dev-a](../evidence/run-2/FT-F6-DELAY-3000__dev-a/) |
| F6-3000-data | F6 | 2 | FT-F6-DELAY-3000-DATA | READ_TIMEOUT | READ_TIMEOUT | pass | 0.2 |  |  | 2009.5 | timeout | 49712 | green | ctl 8, field 8 | [run-2/FT-F6-DELAY-3000-DATA__dev-a](../evidence/run-2/FT-F6-DELAY-3000-DATA__dev-a/) |
| F7 | F7 | 2 | FT-F7-NAME-SWAP | WRONG_IDENTITY | WRONG_IDENTITY | pass | 0.3 | 0.4 | 0.8 | 1.2 | newline | 44426 | green | ctl 10, field 10 | [run-2/FT-F7-NAME-SWAP__dev-a](../evidence/run-2/FT-F7-NAME-SWAP__dev-a/) |
| F7-missing | F7 | 2 | FT-F7-NAME-MISSING | RESOLVE_FAIL | RESOLVE_FAIL | pass |  |  |  | 1.1 |  |  | green |  | [run-2/FT-F7-NAME-MISSING__dev-a](../evidence/run-2/FT-F7-NAME-MISSING__dev-a/) |
| F8 | F8 | 2 | FT-F8-DROP | CONNECT_TIMEOUT | CONNECT_TIMEOUT | pass | 1009.9 |  |  | 1010.6 |  |  | green | ctl 17, field 17 | [run-2/FT-F8-DROP__dev-a](../evidence/run-2/FT-F8-DROP__dev-a/) |
| F8 | F8 | 2 | GW-F8-UNREACHABLE | CONNECT_TIMEOUT | CONNECT_TIMEOUT | pass |  |  |  | 2353.9 |  |  | green |  | [run-2/GW-F8-UNREACHABLE__dev-a](../evidence/run-2/GW-F8-UNREACHABLE__dev-a/) |
| F9 | F9 | 2 | FT-F9-REJECT | CONN_REFUSED | CONN_REFUSED | pass | 0.3 |  |  | 0.9 |  |  | green | ctl 4, field 4 | [run-2/FT-F9-REJECT__dev-a](../evidence/run-2/FT-F9-REJECT__dev-a/) |
| F9-data | F9 | 2 | FT-F9-REJECT-DATA | CONN_RESET | CONN_RESET | pass | 0.2 |  |  | 0.6 | reset | 36140 | green | ctl 6, field 6 | [run-2/FT-F9-REJECT-DATA__dev-a](../evidence/run-2/FT-F9-REJECT-DATA__dev-a/) |
| F10-malformed | F10 | 2 | FT-F10-MALFORMED | MALFORMED | MALFORMED | pass | 0.2 | 1.2 | 1.4 | 1.8 | newline | 32834 | green | ctl 10, field 10 | [run-2/FT-F10-MALFORMED__dev-a](../evidence/run-2/FT-F10-MALFORMED__dev-a/) |
| F10-truncated | F10 | 2 | FT-F10-TRUNCATED | MALFORMED | MALFORMED | pass | 0.3 |  |  | 1.5 | eof | 53178 | green | ctl 10, field 10 | [run-2/FT-F10-TRUNCATED__dev-a](../evidence/run-2/FT-F10-TRUNCATED__dev-a/) |
| F10-wrong-id | F10 | 2 | FT-F10-WRONG-ID | MALFORMED | MALFORMED | pass | 0.3 | 1.3 | 1.6 | 2.1 | newline | 53204 | green | ctl 10, field 10 | [run-2/FT-F10-WRONG-ID__dev-a](../evidence/run-2/FT-F10-WRONG-ID__dev-a/) |
| F11-fin | F11 | 2 | FT-F11-CLOSE-FIN | CONN_RESET | CONN_RESET | pass | 0.2 | 1.7 | 2.0 | 3.4 | newline | 56536 | green | ctl 13, field 13 | [run-2/FT-F11-CLOSE-FIN__dev-a](../evidence/run-2/FT-F11-CLOSE-FIN__dev-a/) |
| F11-rst | F11 | 2 | FT-F11-CLOSE-RST | CONN_RESET | CONN_RESET | pass | 0.3 | 2.1 | 2.5 | 4.4 | newline | 56560 | green | ctl 11, field 11 | [run-2/FT-F11-CLOSE-RST__dev-a](../evidence/run-2/FT-F11-CLOSE-RST__dev-a/) |
| F12 | F12 | 2 | FT-F12-RESTART | PASS | PASS | pass | 0.2 | 1.8 | 1.1 | 1.5 | newline | 39866 | green | ctl 16, ctl 10, ctl 10, ctl 12, ctl 10, field 16, field 10, field 10, field 12, field 10 | [run-2/FT-F12-RESTART__dev-a](../evidence/run-2/FT-F12-RESTART__dev-a/) |
| F13-repeat-seq | F13 | 2 | FT-F13-REPEAT-SEQ | STALE_DATA | STALE_DATA | pass | 0.3 | 2.1 | 2.4 | 3.9 | newline | 60114 | green | ctl 12, field 12 | [run-2/FT-F13-REPEAT-SEQ__dev-a](../evidence/run-2/FT-F13-REPEAT-SEQ__dev-a/) |
| F13-skew | F13 | 2 | FT-F13-SKEW | STALE_DATA | STALE_DATA | pass | 0.3 | 1.7 | 2.0 | 4.5 | newline | 56588 | green | ctl 10, field 10 | [run-2/FT-F13-SKEW__dev-a](../evidence/run-2/FT-F13-SKEW__dev-a/) |

`dialled-flow packets`: packets of the flow the case dialled (address:port, both directions) in the ctl and field captures (`capture_flows`); empty = recorded before that check existed (independent audit F-07). A local failure that sends nothing (NO_ROUTE, RESOLVE_FAIL) has no expected flow.

`detection ms`: runner cases = fault confirmed applied (witness-faultctl returned) -> attempt classified; GW-* cases = fault command sent -> gateway state `unreachable` (REQ-09); FT-F12 = restart returned -> first PASS HEALTH (REQ-08). Expected categories are predictions recorded before the run. `local port` is empty when the connect itself failed (no established socket): such cases are matched to packets by time, address and the SYN's source port in the capture text.

### 4b. Fault catalog coverage (brief section 6.3, F1-F13)

| catalog | variant | fair results | pass verdicts | current evidence per case: expected / observed / verdict |
|---|---|---|---|---|
| F1 | F1 | 2 | 2 | FT-F1-STOPPED: CONN_REFUSED / CONN_REFUSED / pass (run 2); GW-F1-UNREACHABLE: CONN_REFUSED / CONN_REFUSED / pass (run 2) |
| F2 | F2 | 1 | 1 | FT-F2-HUNG: READ_TIMEOUT / READ_TIMEOUT / pass (run 2) |
| F3 | F3 | 1 | 1 | FT-F3-WRONG-PORT: CONN_REFUSED / CONN_REFUSED / pass (run 2) |
| F4 | F4 | 1 | 1 | FT-F4-WRONG-ADDR: CONNECT_TIMEOUT / CONNECT_TIMEOUT / pass (run 2) |
| F5 | F5 | 2 | 2 | FT-F5-NO-ROUTE: NO_ROUTE / NO_ROUTE / pass (run 2); GW-F5-UNREACHABLE: NO_ROUTE / NO_ROUTE / pass (run 2) |
| F6 | F6-300 | 1 | 1 | FT-F6-DELAY-300: PASS_SLOW / PASS_SLOW / pass (run 2) |
| F6 | F6-3000 | 1 | 1 | FT-F6-DELAY-3000: CONNECT_TIMEOUT / CONNECT_TIMEOUT / pass (run 2) |
| F6 | F6-3000-data | 1 | 1 | FT-F6-DELAY-3000-DATA: READ_TIMEOUT / READ_TIMEOUT / pass (run 2) |
| F7 | F7 | 1 | 1 | FT-F7-NAME-SWAP: WRONG_IDENTITY / WRONG_IDENTITY / pass (run 2) |
| F7 | F7-missing | 1 | 1 | FT-F7-NAME-MISSING: RESOLVE_FAIL / RESOLVE_FAIL / pass (run 2) |
| F8 | F8 | 2 | 2 | FT-F8-DROP: CONNECT_TIMEOUT / CONNECT_TIMEOUT / pass (run 2); GW-F8-UNREACHABLE: CONNECT_TIMEOUT / CONNECT_TIMEOUT / pass (run 2) |
| F9 | F9 | 1 | 1 | FT-F9-REJECT: CONN_REFUSED / CONN_REFUSED / pass (run 2) |
| F9 | F9-data | 1 | 1 | FT-F9-REJECT-DATA: CONN_RESET / CONN_RESET / pass (run 2) |
| F10 | F10-malformed | 1 | 1 | FT-F10-MALFORMED: MALFORMED / MALFORMED / pass (run 2) |
| F10 | F10-truncated | 1 | 1 | FT-F10-TRUNCATED: MALFORMED / MALFORMED / pass (run 2) |
| F10 | F10-wrong-id | 1 | 1 | FT-F10-WRONG-ID: MALFORMED / MALFORMED / pass (run 2) |
| F11 | F11-fin | 1 | 1 | FT-F11-CLOSE-FIN: CONN_RESET / CONN_RESET / pass (run 2) |
| F11 | F11-rst | 1 | 1 | FT-F11-CLOSE-RST: CONN_RESET / CONN_RESET / pass (run 2) |
| F12 | F12 | 1 | 1 | FT-F12-RESTART: PASS / PASS / pass (run 2) |
| F13 | F13-repeat-seq | 1 | 1 | FT-F13-REPEAT-SEQ: STALE_DATA / STALE_DATA / pass (run 2) |
| F13 | F13-skew | 1 | 1 | FT-F13-SKEW: STALE_DATA / STALE_DATA / pass (run 2) |

Fault application/removal (all runs):

| fault | applications | removals verified | first applied | last removed |
|---|---|---|---|---|
| F1 | 2 | 2 | 2026-10-21T07:57:49.705Z | 2026-10-21T07:59:12.518Z |
| F10-malformed | 1 | 1 | 2026-10-21T07:58:20.771Z | 2026-10-21T07:58:21.332Z |
| F10-truncated | 1 | 1 | 2026-10-21T07:58:23.963Z | 2026-10-21T07:58:24.559Z |
| F10-wrong-id | 1 | 1 | 2026-10-21T07:58:27.154Z | 2026-10-21T07:58:27.733Z |
| F11-fin | 1 | 1 | 2026-10-21T07:58:56.701Z | 2026-10-21T07:58:57.280Z |
| F11-rst | 1 | 1 | 2026-10-21T07:58:59.914Z | 2026-10-21T07:59:00.534Z |
| F12 | 2 | 2 | 2026-10-21T07:59:28.470Z | 2026-10-21T07:59:33.138Z |
| F13-repeat-seq | 1 | 1 | 2026-10-21T07:59:06.641Z | 2026-10-21T07:59:07.206Z |
| F13-skew | 1 | 1 | 2026-10-21T07:59:03.265Z | 2026-10-21T07:59:03.848Z |
| F2 | 1 | 1 | 2026-10-21T07:57:53.013Z | 2026-10-21T07:57:55.672Z |
| F3 | 1 | 1 | 2026-10-21T07:58:30.039Z | 2026-10-21T07:58:30.449Z |
| F4 | 1 | 1 | 2026-10-21T07:58:33.059Z | 2026-10-21T07:58:34.722Z |
| F5 | 2 | 2 | 2026-10-21T07:58:37.015Z | 2026-10-21T07:59:18.213Z |
| F6-300 | 1 | 1 | 2026-10-21T07:57:58.257Z | 2026-10-21T07:57:59.490Z |
| F6-3000 | 1 | 1 | 2026-10-21T07:58:02.191Z | 2026-10-21T07:58:04.003Z |
| F6-3000-data | 1 | 1 | 2026-10-21T07:58:07.941Z | 2026-10-21T07:58:10.593Z |
| F7 | 1 | 1 | 2026-10-21T07:58:12.969Z | 2026-10-21T07:58:14.225Z |
| F7-missing | 1 | 1 | 2026-10-21T07:58:16.550Z | 2026-10-21T07:58:18.221Z |
| F8 | 2 | 2 | 2026-10-21T07:58:40.176Z | 2026-10-21T07:59:25.477Z |
| F9 | 1 | 1 | 2026-10-21T07:58:45.120Z | 2026-10-21T07:58:46.003Z |
| F9-data | 1 | 1 | 2026-10-21T07:58:48.861Z | 2026-10-21T07:58:49.440Z |

### 4c. Gateway and recovery measurements (REQ-08, REQ-09), latest fair result per case/device

| case | device | run | observed | verdict | measurement | value | unit | bound | within | clock |
|---|---|---|---|---|---|---|---|---|---|---|
| C-GATEWAY | dev-a | 9 | PASS | pass | gateway_last_seen_age_ms | 1272.0 | ms | 4000.0 | yes | ctl-monotonic |
| C-GATEWAY | dev-a | 9 | PASS | pass | gateway_poll_duration_ms | 11.4 | ms | 4000.0 | yes | ctl-monotonic |
| C-GATEWAY | dev-a | 9 | PASS | pass | gateway_poll_period_ms | 1991.6 | ms |  |  | ctl-monotonic |
| C-GATEWAY | dev-b | 9 | PASS | pass | gateway_last_seen_age_ms | 933.0 | ms | 4000.0 | yes | ctl-monotonic |
| C-GATEWAY | dev-b | 9 | PASS | pass | gateway_poll_duration_ms | 9.1 | ms | 4000.0 | yes | ctl-monotonic |
| C-GATEWAY | dev-b | 9 | PASS | pass | gateway_poll_period_ms | 2005.3 | ms |  |  | ctl-monotonic |
| FT-F12-RESTART | dev-a | 2 | PASS | pass | device_healthy_after_restart_cmd_ms | 524.6 | ms | 10000.0 | yes | ctl-monotonic |
| FT-F12-RESTART | dev-a | 2 | PASS | pass | device_healthy_after_restart_ms | 1.5 | ms | 10000.0 | yes | ctl-monotonic |
| FT-F12-RESTART | dev-a | 2 | PASS | pass | early_restart_device_healthy_ms | 1.2 | ms | 10000.0 | yes | ctl-monotonic |
| FT-F12-RESTART | dev-a | 2 | PASS | pass | early_restart_gateway_recovery_api_observed_ms | 1579.0 | ms | 4000.0 | yes | ctl-monotonic |
| FT-F12-RESTART | dev-a | 2 | PASS | pass | early_restart_gateway_recovery_ms | 1487.3 | ms | 4000.0 | yes | ctl-monotonic |
| FT-F12-RESTART | dev-a | 2 | PASS | pass | early_restart_uptime_rise_s | 0.4 | s |  |  | device uptime_s (gateway samples) |
| FT-F12-RESTART | dev-a | 2 | PASS | pass | gateway_recovery_api_observed_ms | 1062.5 | ms | 4000.0 | yes | ctl-monotonic |
| FT-F12-RESTART | dev-a | 2 | PASS | pass | gateway_recovery_ms | 1062.4 | ms | 4000.0 | yes | ctl-monotonic |
| FT-F12-RESTART | dev-a | 2 | PASS | pass | health_probes_until_pass | 1.0 | count |  |  | ctl-monotonic |
| FT-F12-RESTART | dev-a | 2 | PASS | pass | restart_call_ms | 523.1 | ms |  |  | ctl-monotonic |
| FT-F12-RESTART | dev-a | 2 | PASS | pass | systemctl_restart_ms | 182.6 | ms |  |  | witness-field monotonic |
| FT-F13-SKEW | dev-a | 2 | STALE_DATA | pass | read_skew_s | 30.0 | s | 2.0 | NO | device ts vs runner realtime |
| FT-F4-WRONG-ADDR | dev-a | 2 | CONNECT_TIMEOUT | pass | field_Icmp.OutDestUnreachs_delta | 0.0 | count |  |  | witness-field /proc/net/snmp |
| FT-F4-WRONG-ADDR | dev-a | 2 | CONNECT_TIMEOUT | pass | field_Ip.InAddrErrors_delta | 2.0 | count |  |  | witness-field /proc/net/snmp |
| FT-F4-WRONG-ADDR | dev-a | 2 | CONNECT_TIMEOUT | pass | field_Tcp.OutRsts_delta | 0.0 | count |  |  | witness-field /proc/net/snmp |
| FT-F5-NO-ROUTE | dev-a | 2 | NO_ROUTE | pass | connect_ms | 0.0 | ms |  |  | ctl-monotonic |
| FT-F7-NAME-MISSING | dev-a | 2 | RESOLVE_FAIL | pass | resolve_ms | 1.1 | ms | 1000.0 | yes | ctl-monotonic |
| FT-F7-NAME-SWAP | dev-a | 2 | WRONG_IDENTITY | pass | gateway_wrong_identity_ms | 828.1 | ms | 6000.0 | yes | ctl-monotonic |
| FT-F8-DROP | dev-a | 2 | CONNECT_TIMEOUT | pass | field_Icmp.OutDestUnreachs_delta | 0.0 | count |  |  | witness-field /proc/net/snmp |
| FT-F8-DROP | dev-a | 2 | CONNECT_TIMEOUT | pass | field_Tcp.OutRsts_delta | 0.0 | count |  |  | witness-field /proc/net/snmp |
| GW-F1-UNREACHABLE | dev-a | 2 | CONN_REFUSED | pass | fault_apply_call_ms | 511.6 | ms |  |  | ctl-monotonic |
| GW-F1-UNREACHABLE | dev-a | 2 | CONN_REFUSED | pass | gateway_detection_from_applied_ms.dev-a | 1728.0 | ms |  |  | ctl-monotonic |
| GW-F1-UNREACHABLE | dev-a | 2 | CONN_REFUSED | pass | gateway_detection_ms.dev-a | 2239.6 | ms | 6000.0 | yes | ctl-monotonic |
| GW-F1-UNREACHABLE | dev-a | 2 | CONN_REFUSED | pass | gateway_recovery_after_revert_ms.dev-a | 1569.2 | ms | 4000.0 | yes | ctl-monotonic |
| GW-F1-UNREACHABLE | dev-a | 2 | CONN_REFUSED | pass | gateway_recovery_from_revert_returned_ms.dev-a | 1225.4 | ms |  |  | ctl-monotonic |
| GW-F1-UNREACHABLE | dev-a | 2 | CONN_REFUSED | pass | gateway_unreachable_api_observed_ms | 2329.5 | ms | 6000.0 | yes | ctl-monotonic |
| GW-F5-UNREACHABLE | dev-a | 2 | NO_ROUTE | pass | fault_apply_call_ms | 37.7 | ms |  |  | ctl-monotonic |
| GW-F5-UNREACHABLE | dev-a | 2 | NO_ROUTE | pass | gateway_detection_from_applied_ms.dev-a | 1548.2 | ms |  |  | ctl-monotonic |
| GW-F5-UNREACHABLE | dev-a | 2 | NO_ROUTE | pass | gateway_detection_from_applied_ms.dev-b | 1547.6 | ms |  |  | ctl-monotonic |
| GW-F5-UNREACHABLE | dev-a | 2 | NO_ROUTE | pass | gateway_detection_ms.dev-a | 1585.9 | ms | 6000.0 | yes | ctl-monotonic |
| GW-F5-UNREACHABLE | dev-a | 2 | NO_ROUTE | pass | gateway_detection_ms.dev-b | 1585.2 | ms | 6000.0 | yes | ctl-monotonic |
| GW-F5-UNREACHABLE | dev-a | 2 | NO_ROUTE | pass | gateway_recovery_after_revert_ms.dev-a | 1585.8 | ms | 4000.0 | yes | ctl-monotonic |
| GW-F5-UNREACHABLE | dev-a | 2 | NO_ROUTE | pass | gateway_recovery_after_revert_ms.dev-b | 1591.9 | ms | 4000.0 | yes | ctl-monotonic |
| GW-F5-UNREACHABLE | dev-a | 2 | NO_ROUTE | pass | gateway_recovery_from_revert_returned_ms.dev-a | 1568.5 | ms |  |  | ctl-monotonic |
| GW-F5-UNREACHABLE | dev-a | 2 | NO_ROUTE | pass | gateway_recovery_from_revert_returned_ms.dev-b | 1574.6 | ms |  |  | ctl-monotonic |
| GW-F5-UNREACHABLE | dev-a | 2 | NO_ROUTE | pass | gateway_unreachable_api_observed_ms | 1623.0 | ms | 6000.0 | yes | ctl-monotonic |
| GW-F8-UNREACHABLE | dev-a | 2 | CONNECT_TIMEOUT | pass | fault_apply_call_ms | 301.5 | ms |  |  | ctl-monotonic |
| GW-F8-UNREACHABLE | dev-a | 2 | CONNECT_TIMEOUT | pass | gateway_detection_from_applied_ms.dev-a | 2052.4 | ms |  |  | ctl-monotonic |
| GW-F8-UNREACHABLE | dev-a | 2 | CONNECT_TIMEOUT | pass | gateway_detection_ms.dev-a | 2353.9 | ms | 6000.0 | yes | ctl-monotonic |
| GW-F8-UNREACHABLE | dev-a | 2 | CONNECT_TIMEOUT | pass | gateway_recovery_after_revert_ms.dev-a | 563.0 | ms | 4000.0 | yes | ctl-monotonic |
| GW-F8-UNREACHABLE | dev-a | 2 | CONNECT_TIMEOUT | pass | gateway_recovery_from_revert_returned_ms.dev-a | 264.2 | ms |  |  | ctl-monotonic |
| GW-F8-UNREACHABLE | dev-a | 2 | CONNECT_TIMEOUT | pass | gateway_unreachable_api_observed_ms | 2407.3 | ms | 6000.0 | yes | ctl-monotonic |

`bound` is the requirement limit the value is compared with. For a fault case the value may be outside it by design (FT-F13-SKEW's READ is 30 s outside the ±2 s REQ-04 window: that is the expected observation). Gateway/REQ-08/09 values must be within.

All fair runs, bounded measurements:

| measurement | unit | n | min | max | bound | outside bound |
|---|---|---|---|---|---|---|
| device_healthy_after_restart_cmd_ms | ms | 1 | 524.6 | 524.6 | 10000.0 | 0 |
| device_healthy_after_restart_ms | ms | 1 | 1.5 | 1.5 | 10000.0 | 0 |
| early_restart_device_healthy_ms | ms | 1 | 1.2 | 1.2 | 10000.0 | 0 |
| early_restart_gateway_recovery_api_observed_ms | ms | 1 | 1579.0 | 1579.0 | 4000.0 | 0 |
| early_restart_gateway_recovery_ms | ms | 1 | 1487.3 | 1487.3 | 4000.0 | 0 |
| gateway_detection_ms.dev-a | ms | 3 | 1585.9 | 2353.9 | 6000.0 | 0 |
| gateway_detection_ms.dev-b | ms | 1 | 1585.2 | 1585.2 | 6000.0 | 0 |
| gateway_last_seen_age_ms | ms | 4 | 309.0 | 1272.0 | 4000.0 | 0 |
| gateway_poll_duration_ms | ms | 4 | 7.6 | 13.7 | 4000.0 | 0 |
| gateway_recovery_after_revert_ms.dev-a | ms | 3 | 563.0 | 1585.8 | 4000.0 | 0 |
| gateway_recovery_after_revert_ms.dev-b | ms | 1 | 1591.9 | 1591.9 | 4000.0 | 0 |
| gateway_recovery_api_observed_ms | ms | 1 | 1062.5 | 1062.5 | 4000.0 | 0 |
| gateway_recovery_ms | ms | 1 | 1062.4 | 1062.4 | 4000.0 | 0 |
| gateway_unreachable_api_observed_ms | ms | 3 | 1623.0 | 2407.3 | 6000.0 | 0 |
| gateway_wrong_identity_ms | ms | 1 | 828.1 | 828.1 | 6000.0 | 0 |
| read_skew_s | s | 1 | 30.0 | 30.0 | 2.0 | 1 |
| resolve_ms | ms | 1 | 1.1 | 1.1 | 1000.0 | 0 |

## 5. Analysis queries (PROJECT_BRIEF.md section 8; SQL in runner/analysis.py)

### Q1. Failures by device and case (all runs, by run kind)

| device | case_id | kind | fails | errors | attributions | observed | runs | first_run | last_run |
|---|---|---|---|---|---|---|---|---|---|
| (run) | C-ENVIRONMENT | mutant | 2 | 0 | device | - | 2 | 5 | 8 |
| dev-a | C-GATEWAY | mutant | 5 | 0 | device | WRONG_IDENTITY,STALE_DATA,MALFORMED | 5 | 3 | 7 |
| dev-a | C-HEALTH | mutant | 2 | 0 | device | MALFORMED | 2 | 5 | 6 |
| dev-a | C-IDENTIFY | mutant | 3 | 0 | device | WRONG_IDENTITY,MALFORMED | 3 | 3 | 6 |
| dev-a | C-READ-CLOCK | mutant | 5 | 0 | device | STALE_DATA,MALFORMED,READ_TIMEOUT | 5 | 4 | 8 |
| dev-a | C-READ-SERIES | mutant | 5 | 0 | device | STALE_DATA,MALFORMED,READ_TIMEOUT | 5 | 4 | 8 |

### Q2. Verdict/category differs across fair clean-baseline runs (flakiness, all baselines)

_none_

### Q3. Expected vs observed per fault, mismatch count

| catalog_id | fault_id | expected | observed | n_fair | mismatches_fair | n_unfair_runs | infra |
|---|---|---|---|---|---|---|---|
| F1 | F1 | CONN_REFUSED | CONN_REFUSED | 2 | 0 | 0 | 0 |
| F2 | F2 | READ_TIMEOUT | READ_TIMEOUT | 1 | 0 | 0 | 0 |
| F3 | F3 | CONN_REFUSED | CONN_REFUSED | 1 | 0 | 0 | 0 |
| F4 | F4 | CONNECT_TIMEOUT | CONNECT_TIMEOUT | 1 | 0 | 0 | 0 |
| F5 | F5 | NO_ROUTE | NO_ROUTE | 2 | 0 | 0 | 0 |
| F6 | F6-300 | PASS_SLOW | PASS_SLOW | 1 | 0 | 0 | 0 |
| F6 | F6-3000 | CONNECT_TIMEOUT | CONNECT_TIMEOUT | 1 | 0 | 0 | 0 |
| F6 | F6-3000-data | READ_TIMEOUT | READ_TIMEOUT | 1 | 0 | 0 | 0 |
| F7 | F7 | WRONG_IDENTITY | WRONG_IDENTITY | 1 | 0 | 0 | 0 |
| F7 | F7-missing | RESOLVE_FAIL | RESOLVE_FAIL | 1 | 0 | 0 | 0 |
| F8 | F8 | CONNECT_TIMEOUT | CONNECT_TIMEOUT | 2 | 0 | 0 | 0 |
| F9 | F9 | CONN_REFUSED | CONN_REFUSED | 1 | 0 | 0 | 0 |
| F9 | F9-data | CONN_RESET | CONN_RESET | 1 | 0 | 0 | 0 |
| F10 | F10-malformed | MALFORMED | MALFORMED | 1 | 0 | 0 | 0 |
| F10 | F10-truncated | MALFORMED | MALFORMED | 1 | 0 | 0 | 0 |
| F10 | F10-wrong-id | MALFORMED | MALFORMED | 1 | 0 | 0 | 0 |
| F11 | F11-fin | CONN_RESET | CONN_RESET | 1 | 0 | 0 | 0 |
| F11 | F11-rst | CONN_RESET | CONN_RESET | 1 | 0 | 0 | 0 |
| F12 | F12 | PASS | PASS | 1 | 0 | 0 | 0 |
| F13 | F13-repeat-seq | STALE_DATA | STALE_DATA | 1 | 0 | 0 | 0 |
| F13 | F13-skew | STALE_DATA | STALE_DATA | 1 | 0 | 0 | 0 |

### Q4. Detection time per fault and case (ms; fair runs; median computed in SQL)

| catalog_id | fault_id | case_id | n | min_ms | median_ms | max_ms |
|---|---|---|---|---|---|---|
| F1 | F1 | FT-F1-STOPPED | 1 | 0.5 | 0.5 | 0.5 |
| F1 | F1 | GW-F1-UNREACHABLE | 1 | 2239.6 | 2239.6 | 2239.6 |
| F2 | F2 | FT-F2-HUNG | 1 | 2014.1 | 2014.1 | 2014.1 |
| F3 | F3 | FT-F3-WRONG-PORT | 1 | 0.5 | 0.5 | 0.5 |
| F4 | F4 | FT-F4-WRONG-ADDR | 1 | 1012.9 | 1012.9 | 1012.9 |
| F5 | F5 | FT-F5-NO-ROUTE | 1 | 0.2 | 0.2 | 0.2 |
| F5 | F5 | GW-F5-UNREACHABLE | 1 | 1585.9 | 1585.9 | 1585.9 |
| F6 | F6-300 | FT-F6-DELAY-300 | 1 | 621.2 | 621.2 | 621.2 |
| F6 | F6-3000 | FT-F6-DELAY-3000 | 1 | 1004.4 | 1004.4 | 1004.4 |
| F6 | F6-3000-data | FT-F6-DELAY-3000-DATA | 1 | 2009.5 | 2009.5 | 2009.5 |
| F7 | F7 | FT-F7-NAME-SWAP | 1 | 1.2 | 1.2 | 1.2 |
| F7 | F7-missing | FT-F7-NAME-MISSING | 1 | 1.1 | 1.1 | 1.1 |
| F8 | F8 | FT-F8-DROP | 1 | 1010.6 | 1010.6 | 1010.6 |
| F8 | F8 | GW-F8-UNREACHABLE | 1 | 2353.9 | 2353.9 | 2353.9 |
| F9 | F9 | FT-F9-REJECT | 1 | 0.9 | 0.9 | 0.9 |
| F9 | F9-data | FT-F9-REJECT-DATA | 1 | 0.6 | 0.6 | 0.6 |
| F10 | F10-malformed | FT-F10-MALFORMED | 1 | 1.8 | 1.8 | 1.8 |
| F10 | F10-truncated | FT-F10-TRUNCATED | 1 | 1.5 | 1.5 | 1.5 |
| F10 | F10-wrong-id | FT-F10-WRONG-ID | 1 | 2.1 | 2.1 | 2.1 |
| F11 | F11-fin | FT-F11-CLOSE-FIN | 1 | 3.4 | 3.4 | 3.4 |
| F11 | F11-rst | FT-F11-CLOSE-RST | 1 | 4.4 | 4.4 | 4.4 |
| F12 | F12 | FT-F12-RESTART | 1 | 1.5 | 1.5 | 1.5 |
| F13 | F13-repeat-seq | FT-F13-REPEAT-SEQ | 1 | 3.9 | 3.9 | 3.9 |
| F13 | F13-skew | FT-F13-SKEW | 1 | 4.5 | 4.5 | 4.5 |

### Q5. Passed only after retry (reported as FLAKE, verdict fail)

_none_

### Q5b. Every retried result (first attempt not PASS)

| run_id | kind | mutant_id | case_id | device_id | first | second | verdict | first_detail | first_outcome | second_outcome | attribution |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 3 | mutant | M1 | C-IDENTIFY | dev-a | WRONG_IDENTITY | WRONG_IDENTITY | fail | serial serial=WIT-0002!=WIT-0001 | device | device | device |
| 4 | mutant | M2 | C-READ-CLOCK | dev-a | STALE_DATA | STALE_DATA | fail | seq_not_increasing:1<=5 | device | device | device |
| 4 | mutant | M2 | C-READ-SERIES | dev-a | STALE_DATA | STALE_DATA | fail | seq_not_increasing:1<=5 | device | device | device |
| 5 | mutant | M3 | C-HEALTH | dev-a | MALFORMED | MALFORMED | fail | incomplete:57B | device | device | device |
| 5 | mutant | M3 | C-IDENTIFY | dev-a | MALFORMED | MALFORMED | fail | incomplete:86B | device | device | device |
| 5 | mutant | M3 | C-READ-CLOCK | dev-a | MALFORMED | MALFORMED | fail | incomplete:78B | device | device | device |
| 5 | mutant | M3 | C-READ-SERIES | dev-a | MALFORMED | MALFORMED | fail | incomplete:57B | device | device | device |
| 6 | mutant | M4 | C-HEALTH | dev-a | MALFORMED | MALFORMED | fail | wrong_id | device | device | device |
| 6 | mutant | M4 | C-IDENTIFY | dev-a | MALFORMED | MALFORMED | fail | wrong_id | device | device | device |
| 6 | mutant | M4 | C-READ-CLOCK | dev-a | MALFORMED | MALFORMED | fail | wrong_id | device | device | device |
| 6 | mutant | M4 | C-READ-SERIES | dev-a | MALFORMED | MALFORMED | fail | wrong_id | device | device | device |
| 7 | mutant | M5 | C-READ-CLOCK | dev-a | MALFORMED | MALFORMED | fail | type:temp_c | device | device | device |
| 7 | mutant | M5 | C-READ-SERIES | dev-a | MALFORMED | MALFORMED | fail | type:temp_c | device | device | device |
| 8 | mutant | M6 | C-READ-CLOCK | dev-a | READ_TIMEOUT | READ_TIMEOUT | fail | no_bytes_by_deadline | device | device | device |
| 8 | mutant | M6 | C-READ-SERIES | dev-a | READ_TIMEOUT | READ_TIMEOUT | fail | no_bytes_by_deadline | device | device | device |

### Q6. Infra-attributed results / unclean, contaminated or unfinished runs (discard candidates)

_none_

## 6. Clean baselines (brief 7.3)

### 6a. Baseline runs started on freshly restored golden clones (provenance recorded by the runner)

_none_

Independent fresh-clone trials counted (first fair baseline per distinct restore): **0** -> runs none.

### 6c. All fair baseline runs (long-lived and fresh VMs): 2

| case_id | device | runs | passes | observed | retried | lat_min_ms | lat_median_ms | lat_max_ms |
|---|---|---|---|---|---|---|---|---|
| C-ENVIRONMENT | (run) | 2 | 2 | - | 0 |  |  |  |
| C-GATEWAY | dev-a | 2 | 2 | PASS | 0 |  |  |  |
| C-GATEWAY | dev-b | 2 | 2 | PASS | 0 |  |  |  |
| C-HEALTH | dev-a | 2 | 2 | PASS | 0 | 0.8 | 0.8 | 0.8 |
| C-HEALTH | dev-b | 2 | 2 | PASS | 0 | 1.0 | 1.1 | 1.2 |
| C-IDENTIFY | dev-a | 2 | 2 | PASS | 0 | 0.9 | 1.2 | 1.5 |
| C-IDENTIFY | dev-b | 2 | 2 | PASS | 0 | 1.0 | 1.2 | 1.3 |
| C-READ-CLOCK | dev-a | 2 | 2 | PASS | 0 | 0.9 | 1.2 | 1.4 |
| C-READ-CLOCK | dev-b | 2 | 2 | PASS | 0 | 0.9 | 1.1 | 1.2 |
| C-READ-SERIES | dev-a | 2 | 2 | PASS | 0 | 0.8 | 0.8 | 0.8 |
| C-READ-SERIES | dev-b | 2 | 2 | PASS | 0 | 0.8 | 0.9 | 1.0 |

## 7. Mutants (brief 7.4): deliberately broken device builds on dev-a, dev-b stock as control

| mutant_id | description | runs | valid_runs | detected_runs | outcome | catching_reqs | catching_cases | control_nonpass |
|---|---|---|---|---|---|---|---|---|
| M1 | returns the other device's serial in IDENTIFY | 1 | 1 | 1 | CAUGHT | REQ-01,REQ-09 | C-IDENTIFY:WRONG_IDENTITY,C-GATEWAY:WRONG_IDENTITY | 0 |
| M2 | reuses seq after 5 reads (seq 1..5 repeats) | 1 | 1 | 1 | CAUGHT | REQ-04,REQ-05,REQ-09 | C-READ-CLOCK:STALE_DATA,C-READ-SERIES:STALE_DATA,C-GATEWAY:STALE_DATA | 0 |
| M3 | omits the trailing newline on every response | 1 | 1 | 1 | CAUGHT | REQ-01,REQ-03,REQ-04,REQ-05,REQ-09 | C-IDENTIFY:MALFORMED,C-HEALTH:MALFORMED,C-READ-CLOCK:MALFORMED,C-READ-SERIES:MALFORMED,C-GATEWAY:MALFORMED | 0 |
| M4 | echoes the wrong id (id-1) | 1 | 1 | 1 | CAUGHT | REQ-01,REQ-03,REQ-04,REQ-05,REQ-09 | C-IDENTIFY:MALFORMED,C-HEALTH:MALFORMED,C-READ-CLOCK:MALFORMED,C-READ-SERIES:MALFORMED,C-GATEWAY:MALFORMED | 0 |
| M5 | reports temp_c as a string | 1 | 1 | 1 | CAUGHT | REQ-04,REQ-05,REQ-09 | C-READ-CLOCK:MALFORMED,C-READ-SERIES:MALFORMED,C-GATEWAY:MALFORMED | 0 |
| M6 | sleeps 2.5 s on every 7th request (process-wide count) | 1 | 1 | 1 | CAUGHT | REQ-04,REQ-05 | C-READ-CLOCK:READ_TIMEOUT,C-READ-SERIES:READ_TIMEOUT | 0 |

Mutants caught: **6/6** (6 tested). Run-level detection: **6/6** valid mutant runs had >= 1 device-attributed failure on dev-a. A run is valid only if it is fair and has no infra/runner-attributed result (an infrastructure error is never counted as a detection). `control_nonpass` = non-pass results on the stock device in valid runs (false alarms); run-level cases (C-ENVIRONMENT) are listed per run, never as a catch.

Predictions recorded before the first mutant run (`mutants.predicted`):

| mutant | spec | predicted catch |
|---|---|---|
| M1 | other-serial:{other_serial} | C-IDENTIFY/dev-a WRONG_IDENTITY (REQ-01, REQ-02: never commissioned); C-GATEWAY/dev-a not healthy (gateway sees WRONG_IDENTITY). |
| M2 | seq-reuse | C-READ-CLOCK and C-READ-SERIES/dev-a STALE_DATA seq_not_increasing (REQ-05; 10 READs always span a wrap); C-GATEWAY/dev-a may also see STALE_DATA when one of its READs lands on a wrap. |
| M3 | no-newline | Every dev-a exchange: bytes arrive but no frame end before the 2 s read timeout -> MALFORMED (incomplete:NB) in C-IDENTIFY/C-HEALTH/C-READ-*/dev-a (REQ-01, REQ-03, REQ-04, REQ-05; REQ-06 bounded); gateway dev-a unhealthy. |
| M4 | off-by-one-id | Every dev-a exchange MALFORMED wrong_id (REQ-01, REQ-03, REQ-04, REQ-05); gateway dev-a unhealthy. |
| M5 | temp-string | C-READ-CLOCK and C-READ-SERIES/dev-a MALFORMED (schema: temp_c type) (REQ-04, REQ-05); IDENTIFY and HEALTH unaffected; gateway dev-a unhealthy (its poll READs). |
| M6 | slow-7th | Nondeterministic by design: whichever exchange is the device's 7th/14th/... request (runner or gateway) gets READ_TIMEOUT (2.5 s > 2.0 s read timeout). Runner commissioning cases retry once, so a case can pass on retry and be reported FLAKE (fail) or fail twice. A READ series (10-12 requests) usually holds a multiple of 7 unless gateway polls interleave and take it, so C-READ-CLOCK/C-READ-SERIES/dev-a are the likeliest catchers (REQ-04/05); a run where no runner exchange draws a 7th request is a false negative. |

### Per mutant run

| run_id | mutant_id | fair | results | harness_or_infra | caught_cases | control_nonpass | run_level_nonpass | retried | catching |
|---|---|---|---|---|---|---|---|---|---|
| 3 | M1 | 1 | 11 | 0 | 2 | 0 | 0 | 1 | C-IDENTIFY:WRONG_IDENTITY(1st WRONG_IDENTITY) C-GATEWAY:WRONG_IDENTITY |
| 4 | M2 | 1 | 11 | 0 | 3 | 0 | 0 | 2 | C-READ-CLOCK:STALE_DATA(1st STALE_DATA) C-READ-SERIES:STALE_DATA(1st STALE_DATA) C-GATEWAY:STALE_DATA |
| 5 | M3 | 1 | 11 | 0 | 5 | 0 | 1 | 4 | C-IDENTIFY:MALFORMED(1st MALFORMED) C-HEALTH:MALFORMED(1st MALFORMED) C-READ-CLOCK:MALFORMED(1st MALFORMED) C-READ-SERIES:MALFORMED(1st MALFORMED) C-GATEWAY:MALFORMED |
| 6 | M4 | 1 | 11 | 0 | 5 | 0 | 0 | 4 | C-IDENTIFY:MALFORMED(1st MALFORMED) C-HEALTH:MALFORMED(1st MALFORMED) C-READ-CLOCK:MALFORMED(1st MALFORMED) C-READ-SERIES:MALFORMED(1st MALFORMED) C-GATEWAY:MALFORMED |
| 7 | M5 | 1 | 11 | 0 | 3 | 0 | 0 | 2 | C-READ-CLOCK:MALFORMED(1st MALFORMED) C-READ-SERIES:MALFORMED(1st MALFORMED) C-GATEWAY:MALFORMED |
| 8 | M6 | 1 | 11 | 0 | 2 | 0 | 1 | 2 | C-READ-CLOCK:READ_TIMEOUT(1st READ_TIMEOUT) C-READ-SERIES:READ_TIMEOUT(1st READ_TIMEOUT) |

### Every non-pass result in mutant runs (the evidence)

| mutant | run | case | device | first attempt | observed | verdict | attribution | detail | evidence |
|---|---|---|---|---|---|---|---|---|---|
| M1 | 3 | C-GATEWAY | dev-a | WRONG_IDENTITY | WRONG_IDENTITY | fail | device | observed=WRONG_IDENTITY expected=PASS [gateway dev-a: state=wrong_identity polls=1141]; failed predicates: identity_matches_inventory,state_healthy_reachable | [run-3/C-GATEWAY__dev-a](../evidence/run-3/C-GATEWAY__dev-a/) |
| M1 | 3 | C-IDENTIFY | dev-a | WRONG_IDENTITY | WRONG_IDENTITY | fail | device | observed=WRONG_IDENTITY expected=PASS [identity: serial serial=WIT-0002!=WIT-0001] | [run-3/C-IDENTIFY__dev-a](../evidence/run-3/C-IDENTIFY__dev-a/) |
| M2 | 4 | C-GATEWAY | dev-a | STALE_DATA | STALE_DATA | fail | device | observed=STALE_DATA expected=PASS [gateway dev-a: state=stale polls=1155]; failed predicates: read_fresh,state_healthy_reachable | [run-4/C-GATEWAY__dev-a](../evidence/run-4/C-GATEWAY__dev-a/) |
| M2 | 4 | C-READ-CLOCK | dev-a | STALE_DATA | STALE_DATA | fail | device | observed=STALE_DATA expected=PASS [freshness: seq_not_increasing:1<=5] | [run-4/C-READ-CLOCK__dev-a](../evidence/run-4/C-READ-CLOCK__dev-a/) |
| M2 | 4 | C-READ-SERIES | dev-a | STALE_DATA | STALE_DATA | fail | device | observed=STALE_DATA expected=PASS [freshness: seq_not_increasing:1<=5] | [run-4/C-READ-SERIES__dev-a](../evidence/run-4/C-READ-SERIES__dev-a/) |
| M3 | 5 | C-ENVIRONMENT | (run) |  |  | fail | device | 14/15 required environment keys valid; withheld by the device: fw_version.dev-a; failed: fw_version.dev-a | [run-5/C-ENVIRONMENT__run](../evidence/run-5/C-ENVIRONMENT__run/) |
| M3 | 5 | C-GATEWAY | dev-a | MALFORMED | MALFORMED | fail | device | observed=MALFORMED expected=PASS [gateway dev-a: state=protocol_error polls=1170]; failed predicates: state_healthy_reachable | [run-5/C-GATEWAY__dev-a](../evidence/run-5/C-GATEWAY__dev-a/) |
| M3 | 5 | C-HEALTH | dev-a | MALFORMED | MALFORMED | fail | device | observed=MALFORMED expected=PASS [read: incomplete:57B]; failed predicates: health_payload | [run-5/C-HEALTH__dev-a](../evidence/run-5/C-HEALTH__dev-a/) |
| M3 | 5 | C-IDENTIFY | dev-a | MALFORMED | MALFORMED | fail | device | observed=MALFORMED expected=PASS [read: incomplete:86B] | [run-5/C-IDENTIFY__dev-a](../evidence/run-5/C-IDENTIFY__dev-a/) |
| M3 | 5 | C-READ-CLOCK | dev-a | MALFORMED | MALFORMED | fail | device | observed=MALFORMED expected=PASS [read: incomplete:77B] | [run-5/C-READ-CLOCK__dev-a](../evidence/run-5/C-READ-CLOCK__dev-a/) |
| M3 | 5 | C-READ-SERIES | dev-a | MALFORMED | MALFORMED | fail | device | observed=MALFORMED expected=PASS [read: incomplete:57B] | [run-5/C-READ-SERIES__dev-a](../evidence/run-5/C-READ-SERIES__dev-a/) |
| M4 | 6 | C-GATEWAY | dev-a | MALFORMED | MALFORMED | fail | device | observed=MALFORMED expected=PASS [gateway dev-a: state=protocol_error polls=1184]; failed predicates: state_healthy_reachable | [run-6/C-GATEWAY__dev-a](../evidence/run-6/C-GATEWAY__dev-a/) |
| M4 | 6 | C-HEALTH | dev-a | MALFORMED | MALFORMED | fail | device | observed=MALFORMED expected=PASS [schema: wrong_id]; failed predicates: health_payload | [run-6/C-HEALTH__dev-a](../evidence/run-6/C-HEALTH__dev-a/) |
| M4 | 6 | C-IDENTIFY | dev-a | MALFORMED | MALFORMED | fail | device | observed=MALFORMED expected=PASS [schema: wrong_id] | [run-6/C-IDENTIFY__dev-a](../evidence/run-6/C-IDENTIFY__dev-a/) |
| M4 | 6 | C-READ-CLOCK | dev-a | MALFORMED | MALFORMED | fail | device | observed=MALFORMED expected=PASS [schema: wrong_id] | [run-6/C-READ-CLOCK__dev-a](../evidence/run-6/C-READ-CLOCK__dev-a/) |
| M4 | 6 | C-READ-SERIES | dev-a | MALFORMED | MALFORMED | fail | device | observed=MALFORMED expected=PASS [schema: wrong_id] | [run-6/C-READ-SERIES__dev-a](../evidence/run-6/C-READ-SERIES__dev-a/) |
| M5 | 7 | C-GATEWAY | dev-a | MALFORMED | MALFORMED | fail | device | observed=MALFORMED expected=PASS [gateway dev-a: state=protocol_error polls=1199]; failed predicates: state_healthy_reachable | [run-7/C-GATEWAY__dev-a](../evidence/run-7/C-GATEWAY__dev-a/) |
| M5 | 7 | C-READ-CLOCK | dev-a | MALFORMED | MALFORMED | fail | device | observed=MALFORMED expected=PASS [schema: type:temp_c] | [run-7/C-READ-CLOCK__dev-a](../evidence/run-7/C-READ-CLOCK__dev-a/) |
| M5 | 7 | C-READ-SERIES | dev-a | MALFORMED | MALFORMED | fail | device | observed=MALFORMED expected=PASS [schema: type:temp_c] | [run-7/C-READ-SERIES__dev-a](../evidence/run-7/C-READ-SERIES__dev-a/) |
| M6 | 8 | C-ENVIRONMENT | (run) |  |  | fail | device | 14/15 required environment keys valid; withheld by the device: fw_version.dev-a; failed: fw_version.dev-a | [run-8/C-ENVIRONMENT__run](../evidence/run-8/C-ENVIRONMENT__run/) |
| M6 | 8 | C-READ-CLOCK | dev-a | READ_TIMEOUT | READ_TIMEOUT | fail | device | observed=READ_TIMEOUT expected=PASS [read: no_bytes_by_deadline] | [run-8/C-READ-CLOCK__dev-a](../evidence/run-8/C-READ-CLOCK__dev-a/) |
| M6 | 8 | C-READ-SERIES | dev-a | READ_TIMEOUT | READ_TIMEOUT | fail | device | observed=READ_TIMEOUT expected=PASS [read: no_bytes_by_deadline] | [run-8/C-READ-SERIES__dev-a](../evidence/run-8/C-READ-SERIES__dev-a/) |

## 8. Acceptance assertions (SQL over the store; runner/analysis.py ASSERTIONS)

| id | claim | status | violations |
|---|---|---|---|
| A1-req-has-case | every requirement traces to >= 1 case | HOLDS |  |
| A2-case-has-req | every case traces to >= 1 requirement | HOLDS |  |
| A3-case-executed | every catalogued case has >= 1 result in a fair run | HOLDS |  |
| A4-req-current-evidence-passes | every requirement has fair non-mutant evidence and the LATEST such result of every instance of every case mapped to it passes; latest = the latest fair run that recorded or PLANNED the instance (older passing runs cannot stand in for a current failure or a planned result that is missing) | HOLDS |  |
| A5-fault-observed-as-predicted | every brief fault F1-F13 has a fair result whose observed category equals the recorded prediction (verdict pass; the result's expected category is the catalog's, not one rewritten to match) | HOLDS |  |
| A6-category-observed-live | each of the 11 outcome categories was observed on the VMs in a fair run | HOLDS |  |
| A7-no-device-blame-on-red-preflight | no result is attributed to the device while its preflight was red | HOLDS |  |
| A8-no-pass-with-blame | no pass verdict carries an attribution | HOLDS |  |
| A9-faults-removed | every recorded fault application in a finished run has a verified removal, and every decided (pass/fail) fault-case result of a fair run has a recorded application (no vacuous 'all removed' over missing records) | HOLDS |  |
| A10-retried-is-never-pass | a result that needed the retry is never verdict pass (a pass only on retry is a FLAKE: fail; with at most one retry, 2 attempts mean attempt 1 did not meet the case) | HOLDS |  |
| A11-mutant-runs-labelled | every run against a mutant build is kind=mutant with its mutant id (so it is never a baseline and never commissions a device) | HOLDS |  |
| A12-every-mutant-tested | each of the six brief mutants has >= 1 valid (fair, no infra/runner result) run | HOLDS |  |
| A13-environment-recorded | every fair run recorded EVERY REQ-10 key (kernel/distro/qdisc/nft for every inventoried VM, python, git_sha, git_dirty, chrony.offset, runs.clean_env, fw_version for every inventoried device) as text in its one valid representation (runner/evidence.check_environment: kernel release, single-line distro, Python version, 40-hex git_sha EQUAL to runs.git_sha, git_dirty/clean_env equal to the run row, a finite SNTP offset with >= 1 sample against witness-ctl inside the preflight clock gate, qdiscs of every lab interface, an nft table, x.y.z firmware); other records of the same facts (runs.kind, mutant, device builds) agree; no key is recorded twice under two spellings. A firmware version may read 'unavailable (<CATEGORY>: ...)' only in a mutant run, for the mutant device, which withheld it. Unfair runs are not evidence and not checked | HOLDS |  |
| A14-fresh-baselines | >= 5 fresh-clone clean baselines (first fair baseline after each distinct golden restore), each COMPLETE (one result per required commissioning instance), all pass, no retry, commissioning every inventoried device | **VIOLATED** | only 0 successful: [] |
| A15-fresh-baselines-stable | no case verdict/category differs across those runs (nondeterminism would be listed here, not hidden) | **VIOLATED** | no fresh runs |
| A16-retry-attribution | no result is pass or attributed to the device when one of its attempts was not a fair device test (outcome runner/infra; for rows before schema v4: unclassifiable or restart observed) | HOLDS |  |
| A17-capture-flow-evidence | no fair-run capture-flow record marks a flow expected on the wire with 0 packets; and for every CURRENT result (current_evidence: latest fair result per instance, A18's baseline, A14's trials, each mutant's latest valid run) recorded under the capture-flow check, the records are DERIVED from its exchanges (complete and consistent per A24, including 'nothing sent' only for its stated reason) and the case's capture contract (ctl capture always, field capture for fault cases), never trusted and never skipped: every dialled flow x required capture has exactly one record whose expectation matches the exchange facts, and no record is unaccounted for, also on a result whose exchanges are missing. A latest fair result recorded before the check is listed (F3's 5021 flow included) | HOLDS |  |
| A18-commissioning-complete | the latest fair baseline that selected EVERY required commissioning instance (planned it; a run without a plan: executed it), a run with duplicate, conflicting or planned-but-missing results is not skipped, commissions every device of inventory.yaml (catalog-defined prerequisites incl. a valid environment record, runner/db.py commissioning_gaps) | HOLDS |  |
| A19-result-cardinality | in every fair run each result is a well-formed catalog instance and no case instance has more than one result (pass/fail duplicates, in either order, are ambiguous evidence; rows are kept, never merged) | HOLDS |  |
| A20-evidence-verified | the bytes behind the current evidence are verified: every evidence file indexed for a current result (and its run's session files) exists with its recorded length and sha256, and every flow it dialled onto the wire is recounted from its hash-verified capture file(s) (runner/evidence.flow_packets, independent of tcpdump): present, and equal to the recorded count. Without an evidence root nothing is verified and this is violated | HOLDS |  |
| A21-reference-data | the reference tables the SQL joins against equal their sources: requirements = docs/requirements.md, cases/kinds and case->requirement map and faults/predictions and mutants = runner/catalog.py, devices = inventory.yaml (a deleted device or case cannot shrink the required sets) | HOLDS |  |
| A22-store-integrity | the store is internally consistent: SQLite integrity_check is ok, no row survives its deleted parent (foreign_key_check empty), and the migration record (which says when each obligation starts) agrees with the schema and with the rows each migration governs (acceptance contract I1.1) | HOLDS |  |
| A23-run-selection | every run's status flags agree with its records (environment runs.clean_env, session preflight checks, the runner's recorded contamination cause); every fair run executed exactly its declared selection, one result per planned instance and none unplanned (schema-v5 run plan written before its first case, equal to its indexed plan file; earlier runs: their case evidence directories), with session checks and session evidence indexed; every case evidence directory belongs to a result and every decided result has its directory; with an evidence root, session/environment.json is hash-verified and compared with the environment table and run identity for every recorded session, including mutant and superseded runs (I1.2-I1.7, I10.4) | HOLDS |  |
| A24-evidence-chain | every current result satisfies its case contract (runner/contract.py): attempt rows 1..n = results.attempts (runner cases 1..2, fault cases 1, gateway/record cases none), summary columns equal their attempts, a pass rests on one attempt with outcome ok and green pre/postflight checks; each attempt's exchanges are ord 1..k in the case's command grammar (a series stops early only at a non-pass or deadline-cut exchange), dial the case's target, are chronological, recompute the attempt category, send nothing only for their stated reason, and a PASS carries its response; required captures and evidence files are indexed; fault applications and measurements as the case records them (I4-I7, I10.2, I10.3) | HOLDS |  |

22/24 assertions hold. These are machine checks over the recorded evidence; they are necessary for acceptance, not a certificate of it.

## 9. Environment (REQ-10), latest run of each kind

Run 9 (baseline); full nft rulesets, routes and chrony tracking are in the `environment` table.

| key | value |
|---|---|
| chrony.offset | offset_s=+0.000059 delay_s=0.000329 samples=4/4 server=10.77.1.10 |
| chrony.sources.witness-field | MS Name/IP address         Stratum Poll Reach LastRx Last sample                ==============================... |
| device_build.a.witness-field | stock |
| device_build.b.witness-field | stock |
| device_build.dev-a | stock |
| device_build.dev-b | stock |
| device_pid.a.witness-field | 107513 |
| device_pid.b.witness-field | 666 |
| device_py.sha256.witness-field | bab03bc10e58f947bc6a4bbe9235e0a45edecb6f574c5b4365a8c7fcc5f19148 |
| device_unit.sha256.witness-field | 3ddd91ee65eaf17dd221966a5ea50f38ebf68ecc7113fe530c3dec5e4f25a5fa |
| distro.witness-ctl | Ubuntu 24.04.4 LTS |
| distro.witness-field | Ubuntu 24.04.4 LTS |
| faultctl.sha256.witness-field | 86ce7014beae863f8220b3ff4df1c0ebfb40b758785b9f0059aef3549e35855b |
| fw_version.dev-a | 1.0.0 |
| fw_version.dev-b | 1.0.0 |
| gateway.inventory_sha256.witness-ctl | 7cee4c33a6093c2cbc9461d941ac29a5c947a0f348608243f8681cf5547005e7 |
| gateway.state.witness-ctl | MainPID=2123 NRestarts=0 ActiveState=active |
| gateway_py.sha256.witness-ctl | d8e24747a221c8b4c5618a2663ce89c48aff8f8a72664b93004977792480dd64 |
| gateway_unit.sha256.witness-ctl | 39cf837c27c92dea6f91c14c55a159dd000be80caf5da052d40b1261ceb752b3 |
| git_dirty | 0 |
| git_sha | 3d7a9f74c81f80a1a84f790f7aa01f5254e5aa0f |
| hosts_block.witness-ctl | # BEGIN witness-lab (generated from inventory.yaml; edit there, not here) 10.77.2.11	dev-a.lab 10.77.2.12	dev-... |
| kernel.witness-ctl | 6.8.0-134-generic |
| kernel.witness-field | 6.8.0-134-generic |
| mutant | none |
| mutants_py.sha256.witness-field | 1a6f260fb6363766e45b710d80c4974d77a23aa65ee5a43558f358dfbe71c2a0 |
| provenance.witness-ctl | long-lived VM (no golden-restore record) boot_id=271b70f0-25f1-4e08-a932-be0c721e5ef2 |
| provenance.witness-field | long-lived VM (no golden-restore record) boot_id=73735e43-4148-444f-8112-8b233219ff51 |
| pytest | 7.4.4 |
| python | 3.12.3 |
| python.witness-field | 3.12.3 |
| qdisc.witness-ctl | lab0: qdisc fq_codel 0: root refcnt 2 limit 10240p flows 1024 quantum 1514 target 5ms interval 100ms memory_li... |
| qdisc.witness-field | lab0: qdisc fq_codel 0: root refcnt 2 limit 10240p flows 1024 quantum 1514 target 5ms interval 100ms memory_li... |
| runs.clean_env | 1 |
| runs.kind | baseline |
| source.lima | limactl version 2.2.0 |
| source.synced_at | 2026-10-21T08:03:04Z |
| systemd.witness-field | systemd 255 (255.4-1ubuntu8.16) |

Run 2 (fault); full nft rulesets, routes and chrony tracking are in the `environment` table.

| key | value |
|---|---|
| chrony.offset | offset_s=+0.000047 delay_s=0.000332 samples=4/4 server=10.77.1.10 |
| chrony.sources.witness-field | MS Name/IP address         Stratum Poll Reach LastRx Last sample                ==============================... |
| device_build.a.witness-field | stock |
| device_build.b.witness-field | stock |
| device_build.dev-a | stock |
| device_build.dev-b | stock |
| device_pid.a.witness-field | 75072 |
| device_pid.b.witness-field | 666 |
| device_py.sha256.witness-field | bab03bc10e58f947bc6a4bbe9235e0a45edecb6f574c5b4365a8c7fcc5f19148 |
| device_unit.sha256.witness-field | 3ddd91ee65eaf17dd221966a5ea50f38ebf68ecc7113fe530c3dec5e4f25a5fa |
| distro.witness-ctl | Ubuntu 24.04.4 LTS |
| distro.witness-field | Ubuntu 24.04.4 LTS |
| faultctl.sha256.witness-field | 86ce7014beae863f8220b3ff4df1c0ebfb40b758785b9f0059aef3549e35855b |
| fw_version.dev-a | 1.0.0 |
| fw_version.dev-b | 1.0.0 |
| gateway.inventory_sha256.witness-ctl | 7cee4c33a6093c2cbc9461d941ac29a5c947a0f348608243f8681cf5547005e7 |
| gateway.state.witness-ctl | MainPID=2123 NRestarts=0 ActiveState=active |
| gateway_py.sha256.witness-ctl | d8e24747a221c8b4c5618a2663ce89c48aff8f8a72664b93004977792480dd64 |
| gateway_unit.sha256.witness-ctl | 39cf837c27c92dea6f91c14c55a159dd000be80caf5da052d40b1261ceb752b3 |
| git_dirty | 0 |
| git_sha | 3d7a9f74c81f80a1a84f790f7aa01f5254e5aa0f |
| hosts_block.witness-ctl | # BEGIN witness-lab (generated from inventory.yaml; edit there, not here) 10.77.2.11	dev-a.lab 10.77.2.12	dev-... |
| kernel.witness-ctl | 6.8.0-134-generic |
| kernel.witness-field | 6.8.0-134-generic |
| mutant | none |
| mutants_py.sha256.witness-field | 1a6f260fb6363766e45b710d80c4974d77a23aa65ee5a43558f358dfbe71c2a0 |
| provenance.witness-ctl | long-lived VM (no golden-restore record) boot_id=271b70f0-25f1-4e08-a932-be0c721e5ef2 |
| provenance.witness-field | long-lived VM (no golden-restore record) boot_id=73735e43-4148-444f-8112-8b233219ff51 |
| pytest | 7.4.4 |
| python | 3.12.3 |
| python.witness-field | 3.12.3 |
| qdisc.witness-ctl | lab0: qdisc fq_codel 0: root refcnt 2 limit 10240p flows 1024 quantum 1514 target 5ms interval 100ms memory_li... |
| qdisc.witness-field | lab0: qdisc fq_codel 0: root refcnt 2 limit 10240p flows 1024 quantum 1514 target 5ms interval 100ms memory_li... |
| runs.clean_env | 1 |
| runs.kind | fault |
| source.lima | limactl version 2.2.0 |
| source.synced_at | 2026-10-21T07:57:45Z |
| systemd.witness-field | systemd 255 (255.4-1ubuntu8.16) |

Run 8 (mutant); full nft rulesets, routes and chrony tracking are in the `environment` table.

| key | value |
|---|---|
| chrony.offset | offset_s=+0.000041 delay_s=0.000305 samples=4/4 server=10.77.1.10 |
| chrony.sources.witness-field | MS Name/IP address         Stratum Poll Reach LastRx Last sample                ==============================... |
| device_build.a.witness-field | mutant:slow-7th |
| device_build.b.witness-field | stock |
| device_build.dev-a | mutant:slow-7th |
| device_build.dev-b | stock |
| device_pid.a.witness-field | 104813 |
| device_pid.b.witness-field | 666 |
| device_py.sha256.witness-field | bab03bc10e58f947bc6a4bbe9235e0a45edecb6f574c5b4365a8c7fcc5f19148 |
| device_unit.sha256.witness-field | 3ddd91ee65eaf17dd221966a5ea50f38ebf68ecc7113fe530c3dec5e4f25a5fa |
| distro.witness-ctl | Ubuntu 24.04.4 LTS |
| distro.witness-field | Ubuntu 24.04.4 LTS |
| faultctl.sha256.witness-field | 86ce7014beae863f8220b3ff4df1c0ebfb40b758785b9f0059aef3549e35855b |
| fw_version.dev-a | unavailable (READ_TIMEOUT: no_bytes_by_deadline) |
| fw_version.dev-b | 1.0.0 |
| gateway.inventory_sha256.witness-ctl | 7cee4c33a6093c2cbc9461d941ac29a5c947a0f348608243f8681cf5547005e7 |
| gateway.state.witness-ctl | MainPID=2123 NRestarts=0 ActiveState=active |
| gateway_py.sha256.witness-ctl | d8e24747a221c8b4c5618a2663ce89c48aff8f8a72664b93004977792480dd64 |
| gateway_unit.sha256.witness-ctl | 39cf837c27c92dea6f91c14c55a159dd000be80caf5da052d40b1261ceb752b3 |
| git_dirty | 0 |
| git_sha | 3d7a9f74c81f80a1a84f790f7aa01f5254e5aa0f |
| hosts_block.witness-ctl | # BEGIN witness-lab (generated from inventory.yaml; edit there, not here) 10.77.2.11	dev-a.lab 10.77.2.12	dev-... |
| kernel.witness-ctl | 6.8.0-134-generic |
| kernel.witness-field | 6.8.0-134-generic |
| mutant | M6 |
| mutants_py.sha256.witness-field | 1a6f260fb6363766e45b710d80c4974d77a23aa65ee5a43558f358dfbe71c2a0 |
| provenance.witness-ctl | long-lived VM (no golden-restore record) boot_id=271b70f0-25f1-4e08-a932-be0c721e5ef2 |
| provenance.witness-field | long-lived VM (no golden-restore record) boot_id=73735e43-4148-444f-8112-8b233219ff51 |
| pytest | 7.4.4 |
| python | 3.12.3 |
| python.witness-field | 3.12.3 |
| qdisc.witness-ctl | lab0: qdisc fq_codel 0: root refcnt 2 limit 10240p flows 1024 quantum 1514 target 5ms interval 100ms memory_li... |
| qdisc.witness-field | lab0: qdisc fq_codel 0: root refcnt 2 limit 10240p flows 1024 quantum 1514 target 5ms interval 100ms memory_li... |
| runs.clean_env | 1 |
| runs.kind | mutant |
| source.lima | limactl version 2.2.0 |
| source.synced_at | 2026-10-21T08:02:27Z |
| systemd.witness-field | systemd 255 (255.4-1ubuntu8.16) |

## 10. Known problems recorded in the database

Non-pass results outside mutant runs (mutant-run failures are in section 7):

_none_

Contaminated runs:

_none_

Failed checks (preflight/precheck/postflight):

_none_

Evidence integrity: packet captures that contain no packets although the case exchanged traffic:

_none_

Dialled-flow checks (`capture_flows`, independent audit F-07): 129 recorded, 125 expected on the wire, 125 of those present in their capture. Expected flows missing from a capture (any run):

_none_

Captures recorded before the check are not rewritten. The pre-remediation F3 captures filtered `tcp port 5020 or icmp` and hold none of the dialled port-5021 packets; they are kept and annotated in `results/evidence/F07-historical-capture-annotations.md`.

Evidence files checked against their recorded length and sha256: 914; missing or different: **0** (kept as recorded, never re-indexed; see the annotations in results/evidence/):

_none_
