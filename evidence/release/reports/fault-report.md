# Witness fault-injection results

Generated 2026-10-22T02:48:57.076Z from the SQLite results database only (no hand-entered results).

Scope: software-simulated sensor devices (Python processes) on a Linux VM, exercised over real TCP between two Ubuntu 24.04 VMs. This is not physical hardware or embedded firmware validation.

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
