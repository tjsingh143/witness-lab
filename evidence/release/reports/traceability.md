# Witness traceability: requirement -> case -> latest result

Generated 2026-10-22T02:48:57.076Z from the SQLite results database only (no hand-entered results).

Scope: software-simulated sensor devices (Python processes) on a Linux VM, exercised over real TCP between two Ubuntu 24.04 VMs. This is not physical hardware or embedded firmware validation.

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
