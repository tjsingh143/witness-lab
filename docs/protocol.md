# Witness device protocol contract (v1)

Status: **final for Phase 1**, written before any device, runner or test code.
Every classification the runner makes ("malformed", "wrong identity", "stale")
is defined relative to this document. Changes require a version bump and a note
in `docs/implementation-state.md`.

Scope honesty: the "device" is a Python process simulating a networked
environmental sensor on a Linux VM. Traffic is real TCP between two VMs; nothing
here is physical hardware or embedded firmware.

## 1. Transport

| Item | Rule |
|---|---|
| Transport | TCP, IPv4, port **5020** on the device's inventoried address (`inventory.yaml`). |
| Listener | Each device process binds only its own address (`10.77.2.11:5020`, `10.77.2.12:5020`), never `0.0.0.0`. |
| Sessions | A connection carries zero or more request/response exchanges, strictly sequential: the client sends one request frame and waits for its response frame before sending the next. No pipelining. |
| Concurrency | A device serves multiple concurrent connections (gateway poller + runner). Per-process counters (`seq`, `uptime_s`) are shared across connections. |
| Idle close | The device closes a connection idle for **30 s** (FIN). The runner closes its connection at the end of every case. |
| Client close | Either side may close at a frame boundary. A close in the middle of an exchange is classified (section 5). |

## 2. Framing

1. A **frame** is the bytes up to and including the first `\n` (0x0A).
2. Maximum frame length is **4096 bytes including the `\n`** (4095 bytes of payload).
   A receiver that has buffered 4096 bytes without seeing `\n` stops reading:
   the frame is *oversize* and **MALFORMED**. It does not wait for the deadline.
3. The payload is strict **UTF-8** (no BOM, no overlong forms, no surrogates).
   Invalid UTF-8 is **MALFORMED**.
4. The payload is one JSON value per RFC 8259 and must be an **object**. The receiver rejects:
   `NaN`, `Infinity` and `-Infinity` (not JSON), duplicate keys, trailing data
   after the object, and a `\r` anywhere in the frame. Plain JSON whitespace (space or tab) around tokens is allowed.
5. Empty frame (`\n` alone) is **MALFORMED**.
6. **Truncation/EOF:** if the peer closes (FIN or RST) after sending ≥1 byte of a
   frame but before its `\n`, the response is **MALFORMED** (truncated). If the peer
   closes before sending any byte of the response, it is **CONN_RESET**.
7. **Missing newline, connection held open:** if the read deadline expires with
   ≥1 buffered response byte and no `\n`, the result is **MALFORMED** (incomplete
   frame), not READ_TIMEOUT, because bytes did arrive. Zero buffered bytes at the
   deadline is **READ_TIMEOUT**.

## 3. Strict JSON types

| Contract type | Accepted JSON | Rejected (MALFORMED) |
|---|---|---|
| `int` | JSON number token with no fraction or exponent, `-2^53 < n < 2^53` | `true`/`false`, `1.0`, `1e3`, `"1"`, `null` |
| `number` | JSON integer or fraction token, finite | booleans, strings, `null`, `NaN`/`Infinity` |
| `bool` | `true` / `false` only | `0`, `1`, `"true"`, `null` |
| `string` | JSON string, non-empty unless stated | numbers, `null`, empty string |

Python note for implementers: `bool` is a subclass of `int`, so checks must be
`type(v) is int`, never `isinstance(v, int)`. Parse with
`json.loads(..., parse_constant=<raise>, object_pairs_hook=<reject duplicates>)`.

**Unknown keys are MALFORMED.** The contract is exact; a device that adds keys
has changed its contract and must bump the protocol version.

## 4. Messages

### 4.1 Request (client → device)

```json
{"id": 17, "cmd": "IDENTIFY"}
```

| Key | Type | Rule |
|---|---|---|
| `id` | int | `0 ≤ id ≤ 2147483647`. The client increments it per request within a connection. |
| `cmd` | string | Exactly `"IDENTIFY"`, `"HEALTH"` or `"READ"` (case-sensitive). |

Device handling of a bad request (the runner never sends one in normal cases).
The device replies with `{"id": <echoed int or null>, "error": "<code>"}` and keeps the
connection open. Codes: `bad_json`, `bad_request`, `unknown_cmd`. An oversize request gets
`{"id": null, "error": "frame_too_long"}` and then the device closes the connection,
because it cannot find the next frame boundary reliably. **The runner classifies an
`error` reply to a valid request as MALFORMED** (detail `device_error`).

**Remediation note (2026-10-18, independent audit F-05; contract unchanged, implementation corrected).** Until
then the device accepted request frames that section 2 forbids: duplicate keys were resolved last-key-wins
(`{"id":1,"id":2,...}` answered as id 2) and a raw `\r` (also a CRLF terminator) was accepted. The device now
applies section 2 rule 4 to requests exactly as the runner applies it to responses: duplicate keys, `\r` anywhere,
a UTF-8 BOM, `NaN`/`Infinity`, trailing data after the object and invalid UTF-8 are answered
`{"id": null, "error": "bad_json"}` (id null: with a duplicate `id` there is no single request to answer) and the
connection stays open. Valid JSON with the wrong shape stays `bad_request`/`unknown_cmd` with the echoed id.

### 4.2 Responses (device → client)

Each response **must echo the request `id`** with the same integer value. A
well-formed response with a different `id` is **MALFORMED** (detail `wrong_id`),
never a pass.

**IDENTIFY**
```json
{"id": 1, "device_id": "dev-a", "serial": "WIT-0001", "model": "WSIM-1", "fw_version": "1.0.0"}
```
| Key | Type | Rule |
|---|---|---|
| `device_id` | string | `^[a-z0-9-]{1,32}$` |
| `serial` | string | `^WIT-[0-9]{4}$` |
| `model` | string | non-empty, ≤64 chars. Recorded, not matched against the inventory. |
| `fw_version` | string | `^[0-9]+\.[0-9]+\.[0-9]+$` |

**HEALTH**
```json
{"id": 2, "status": "ok", "uptime_s": 431.27, "sensor_ok": true}
```
| Key | Type | Rule |
|---|---|---|
| `status` | string | `"ok"` or `"degraded"` |
| `uptime_s` | number | `0 ≤ uptime_s < 3.2e9`. Seconds since this process started (monotonic clock). |
| `sensor_ok` | bool | |

**READ**
```json
{"id": 3, "seq": 42, "ts": "2026-10-16T21:15:03.120Z", "temp_c": 22.4, "rh_pct": 41.8}
```
| Key | Type | Rule |
|---|---|---|
| `seq` | int | `1 ≤ seq < 2^53`. The first READ served by a process returns `seq ≥ 1`. Each later READ served by the same process returns a strictly larger `seq`. Gaps are allowed, because counters are shared across connections. |
| `ts` | string | RFC 3339 UTC, exactly `YYYY-MM-DDTHH:MM:SS[.f{1,6}]Z` (uppercase `T` and `Z`; numeric offsets such as `+00:00` are rejected). The sample time from the device's realtime clock. |
| `temp_c` | number | Sane bounds **−40.0 ≤ temp_c ≤ 85.0** (common industrial sensor rating). |
| `rh_pct` | number | Sane bounds **0.0 ≤ rh_pct ≤ 100.0**. |

A value outside the sane bounds breaks the contract, so it is **MALFORMED** (detail
`out_of_range`). Physically impossible data is not a valid reading.

## 5. Observed-category classification

The runner records **one observed category per attempt**, taken from the brief's
11 categories (no others):

`PASS, PASS_SLOW, RESOLVE_FAIL, NO_ROUTE, CONN_REFUSED, CONNECT_TIMEOUT,
READ_TIMEOUT, CONN_RESET, MALFORMED, WRONG_IDENTITY, STALE_DATA`

Classification follows the path a request takes: *name → route → connect → read →
frame → schema → identity → freshness → latency*. The **first stage that fails
decides the category.** Later stages are not evaluated, so exactly one category
is produced.

| # | Stage | Observation | Category |
|---|---|---|---|
| 1 | resolve | `getaddrinfo(hostname)` raises, returns no IPv4 address, or exceeds 1.0 s | RESOLVE_FAIL |
| 2 | connect | `connect()` fails `EHOSTUNREACH` or `ENETUNREACH` (incl. ICMP unreachable received during the handshake) | NO_ROUTE |
| 3 | connect | `connect()` fails `ECONNREFUSED` (RST answering our SYN) | CONN_REFUSED |
| 4 | connect | no handshake completion within the connect timeout | CONNECT_TIMEOUT |
| 5 | read | ≥1 response byte buffered and peer FIN/RST before `\n`, or deadline hit with a partial frame, or 4096 bytes without `\n` | MALFORMED (`truncated` / `incomplete` / `oversize`) |
| 6 | read | `ECONNRESET`/`EPIPE` on send/recv, or EOF, with 0 response bytes | CONN_RESET |
| 7 | read | 0 response bytes by the read deadline, connection still open | READ_TIMEOUT |
| 8 | frame | non-UTF-8, invalid JSON, non-object, NaN/Infinity, duplicate key, `\r`, empty | MALFORMED |
| 9 | schema | first failure in this order: `id` missing/mistyped → `id` ≠ request → `error` key present → required key missing → wrong type → out of domain/range → unknown key | MALFORMED (detail = first failure) |
| 10 | identity | IDENTIFY `device_id`, `serial` or `fw_version` ≠ inventory row for the hostname/address dialled | WRONG_IDENTITY (detail lists mismatched fields) |
| 11 | freshness | READ `ts` outside the clock window, or `seq` ≤ previous / `ts` < previous within one process lifetime (section 6) | STALE_DATA |
| 12 | latency | otherwise; `latency_ms` > 500 (budget) | PASS_SLOW |
| 13 | latency | otherwise | PASS |

Notes on edge cases:
- Any other `connect()` errno (`EADDRNOTAVAIL`, `ENETDOWN`, …) and any exception
  the classifier did not anticipate is **not** forced into a category. The attempt
  is recorded as unclassifiable, with verdict `error` and attribution `runner`, so a
  human sees it. `ENETDOWN` caused by a deliberately downed interface is mapped
  only if a later protocol version adds it to row 2.
- Malformed-field precedence (row 9) only changes the *detail* string. The category is
  MALFORMED either way. Fixing the order makes evidence reproducible.
- Firmware mismatch with the correct serial is WRONG_IDENTITY (detail `fw_version`).
  Commissioning means "the expected device *running the expected version*" (brief
  4.4). Firmware matching is **exact string equality**, not semver compatibility.
- HEALTH `status:"degraded"` or `sensor_ok:false` is a well-formed, truthful
  answer. The observed category is PASS/PASS_SLOW, and the **REQ-03 case verdict is fail**.
  See section 8 for why a category is not a verdict.
- **Mid-session close (F11, observed in Phase 3).** After complete exchanges on a connection, a
  close before any byte of the next response is CONN_RESET whether it is a FIN or a RST
  (row 6). The detail tells them apart: FIN → `read_end=eof`, detail `eof_before_response`; RST →
  `read_end=reset`, detail `reset_before_response`. ≥1 byte before the close is MALFORMED
  (`truncated:<eof|reset>:<n>B`, row 5). Live: `close-after:2` showed `[F.]` and `reset-after:2`
  showed `[R.]` in place of the third response (runs 59/61). The exchanges before the close stay
  PASS and are recorded; the attempt's category is the first non-pass exchange.
- **Stopping service vs stopped service (observed in Phase 3).** During witness-device's graceful
  stop (~115 ms: SIGTERM until the listening socket closes) the listener still completes handshakes
  but no longer accepts; the queued connection is reset when the listener closes, giving
  **CONN_RESET**, not CONN_REFUSED. Once the process has exited a SYN gets RST → CONN_REFUSED.
  Seen by a gateway poll in run 54 (GW-F1) and during F12 restarts. F1's expected CONN_REFUSED is
  the steady state.

## 6. Clock and sequence rules

- One clock writer per VM, hierarchy macOS → `witness-ctl` → `witness-field`
  (`docs/lab-record.md` section 8). `witness-ctl` serves its clock with chrony (local stratum,
  `-x`), and `witness-field`'s chronyd follows it. Preflight requires field's chrony to
  have ctl selected, and the **raw SNTP offset** of ctl vs field (`scripts/lib/ntp_offset.py`)
  to have magnitude < 100 ms. (Revised in Phase 1 from "`chronyc tracking` offset" after
  measurement showed modelled chrony offsets can read ~0 while the true offset was 25–35 ms.)
- **Clock window (REQ-04):** let `t_send`/`t_recv` be the runner's realtime
  clock when the READ was sent and when its `\n` arrived. The read is fresh iff
  `t_send − 2.0 s ≤ ts ≤ t_recv + 2.0 s`.
- **Monotonicity (REQ-05):** across READs from the same process, `seq` strictly
  increases and `ts` is non-decreasing. The runner compares only against the
  previous READ it received from that device in the same case.
- **Restart semantics:** a process restart (`systemctl restart`, crash +
  `Restart=on-failure`) resets `uptime_s` to ~0 and `seq` to start again at ≥1.
  Open connections are closed (in-flight exchange → CONN_RESET/MALFORMED per section 5).
  While no process listens, connects are refused (CONN_REFUSED).
  A `seq` decrease is **STALE_DATA unless a restart was observed**, meaning a HEALTH
  `uptime_s` lower than the previous HEALTH from the same case. In that case the window is
  invalid: the case is recorded verdict `error`, attribution `infra` (an
  unplanned restart), not a device STALE_DATA failure. Cases that deliberately
  restart (REQ-08, F12) reset their monotonicity baseline at the restart.
- **Restart inference, corrected 2026-10-18 (independent audit F-02).** "Uptime lower than the previous HEALTH"
  misses an *early* restart: an old process sampled young (e.g. 0.014 s) can be followed by a new process sampled
  older (e.g. 1.6 s). The rule used by the runner and the gateway is now `runner/classify.restart_between`: two
  HEALTH answers come from different processes iff the uptime **decreased**, or it **advanced less than the
  observer's monotonic clock certainly advanced between the two device-side samples** (start of the later exchange
  minus end of the earlier one), by more than the uncertainty: 1 ms uptime rounding + 2 ms slack + 1000 ppm of
  the elapsed time (each kernel bounds NTP frequency correction at 500 ppm). Two samples of one process are never
  flagged within that rate bound, so a repeated or reused `seq` inside one process (F13 `repeat-seq`, mutant M2)
  stays STALE_DATA. Residual blind spot: a successor that started within the two exchanges' durations + tolerance
  of the old process's start (protocol v1 has no incarnation id); `systemctl restart` took 84.9-561.1 ms on
  witness-field in the 27 FT-F12 runs recorded so far, against ~1 ms exchanges.

## 7. Deadlines and retries (finite by construction)

| Bound | Value | Why |
|---|---|---|
| resolve timeout | 1.0 s | `/etc/hosts` lookup is local and should be ~µs. 1 s bounds a misconfigured resolver. |
| connect timeout | 1.0 s | Single virtual hop on one Mac, RTT expected < 1 ms (to be measured in Phase 2). Linux's initial SYN RTO is 1 s, so one lost SYN is a CONNECT_TIMEOUT, not a silent retransmit-and-pass. |
| read timeout | 2.0 s | From request sent to `\n` received. 4× the latency budget. It leaves room for the 300 ms netem fault, and the 2.5 s mutant and the 3000 ms fault exceed it. |
| latency budget | 500 ms | Measured from `connect()` start to response `\n` for the first exchange on a fresh connection (an operator's "did it answer within 500 ms"). `connect_ms` and `response_ms` are also recorded separately. Single hop on one machine; production would be measured first. |
| per-attempt deadline | 4.0 s | resolve + connect + read. |
| per-case deadline | 30 s | Hard cap for multi-request cases (10 READs × worst 2 s + slack). Expiry → verdict `error`, attribution `runner`. |
| retries | ≤ 1 | Only for commissioning (no-fault) cases, only for idempotent commands (all three are). Each retry uses a new connection after a 250 ms pause. The first-attempt category is always recorded. |

A case that is non-PASS on attempt 1 and PASS on attempt 2 is a **flake**, so its
verdict is `fail`, never `pass`, and it is queryable as
`first_attempt_category <> observed_category AND attempts = 2`. Fault cases are
never retried, because the first observation *is* the measurement.

**Corrections 2026-10-18 (independent audit F-03 and F-04).**
- *The 30 s per-case deadline is one absolute deadline.* It starts with the case's first attempt and bounds every
  resolve, connect, request and read of every attempt, the 250 ms retry pause and the retry; each blocking step is
  clamped to the time left (`runner/cases.case_deadline`, `runner/client.Connection(case_deadline=...)`). Before,
  each attempt restarted the clock and an exchange could overrun it: 12 replies of 1.3 s ran 31.6 s and ended
  `fail/device`. A step the deadline cuts short (or that has no time left to start) is kept with its partial bytes,
  classified unclassifiable (`case_deadline_exhausted:...`) and the result is `error/runner`, as the table says.
- *Attribution is decided over all attempts.* Each attempt gets its own outcome (`attempts.outcome`): `ok`,
  `device` (a fair observation that violated the case, including a PASS category with a failed predicate such as
  `status:"degraded"`), `runner` (unclassifiable or cut by the deadline) or `infra` (restart observed). If any
  attempt was not a fair device test, the result is `error` with that attribution, whatever the other attempt saw:
  a runner/infra problem never becomes a device FLAKE (before: `error/runner` + PASS retry gave `fail/device`).
- *"Passed only on retry" is a predicate fact:* attempt 1 outcome not `ok` and attempt 2 outcome `ok`
  (`runner/analysis.Q5_RETRY`). The category comparison above missed a degraded HEALTH that recovered; it is kept
  only for rows recorded before schema v4 (no stored outcome).

**Whole live-case correction, 2026-10-21.** A real-VM F12 experiment with an audit-only HTTP proxy
delaying headers and body by 1.5 s each recorded PASS after a 34.833 s test body. Individual socket
timeouts and the old 75 s body alarm did not enforce the 30 s overall limit. The live case now starts
one 30 s monotonic budget at `Case` creation, before quick checks and capture startup, and applies it
through the test body and decision (including fault commands, gateway HTTP, reconnects, sleeps and
retries). Probe/retry contexts inherit its remaining time; a real-time alarm also bounds direct calls.
Expiry records `error/runner`, retaining F12's completed exchanges, never PASS or a device failure.
The alarm is disabled before safety teardown so reverts cannot be interrupted by an expired observation
budget. Session preflight/environment collection and post-decision evidence/postflight are separate
bounded harness operations; elapsed setup, body, decision and cleanup are reported separately. The
30 s bound is not a claim that an entire pytest process, including session startup and safe cleanup,
finishes in 30 s. This strengthens the existing bound without increasing any protocol timeout.

Prediction for Phase 3, not yet verified: `tc qdisc ... root netem delay` on
VM-B's interface also delays the SYN-ACK. If so, a 300 ms delay is expected to
give PASS_SLOW (≈300 ms connect + ≈300 ms response > 500 ms). A 3000 ms delay is
expected to give **CONNECT_TIMEOUT**, not READ_TIMEOUT, under a 1.0 s connect timeout,
unless the fault is scoped to post-handshake packets. The F6 fixture must
record which way it was scoped, and the observation must be compared with this
prediction.

**Observed in Phase 2 (2026-10-17, runs 3 and 4, evidence `results/evidence/run-{3,4}/FT-F6-*`).**
The F6 fixture scopes netem to witness-field `lab0` egress with a `prio` root and a `flower`
filter on TCP source port 5020 from 10.77.2.0/24 (so SSH and chrony are not delayed).
- 300 ms, all packets incl. SYN-ACK: connect ≈ 306 ms + response ≈ 306 ms ⇒ latency ≈ 612–616 ms
  ⇒ **PASS_SLOW**, as predicted (the SYN-ACK *is* delayed).
- 3000 ms, all packets: connect gives up at ≈ 1007 ms ⇒ **CONNECT_TIMEOUT**, as predicted. The
  capture shows the client's SYN retransmission at +1.0 s and, after the qdisc is removed, field's
  retransmitted SYN-ACK answered by a RST from ctl (the half-open connection lingers in SYN-RECV).
- 3000 ms, post-handshake only (`tcp_flags 0x0/0x2`, SYN-ACK not delayed): connect ≈ 0.3 ms,
  no bytes by 2.0 s ⇒ **READ_TIMEOUT**. This variant is how REQ-07(b) observes READ_TIMEOUT.

## 8. Case verdict vs observed category

- **Observed category** = what the network/device did on one attempt (section 5).
  It is a fact about the observation.
- **Expected category** = what the case predicts: PASS for commissioning cases,
  the fault catalog's prediction for fault cases.
- **Verdict** (`pass`/`fail`/`error`) = did the case's requirement hold:
  - `pass`: observed matches expected **and** all requirement predicates hold
    (e.g. REQ-03 `status=="ok"`, REQ-01 serial match, REQ-05 ordering).
  - `fail`: preflight green and the observation contradicts the expectation or a
    predicate. Attribution is `device` (or `runner` if a postflight/harness check shows
    the harness is at fault).
  - `error`: the case could not be fairly evaluated (preflight red → `infra`,
    harness exception/unclassifiable → `runner`).
- A fault case whose expected failure was observed (e.g. F1 → CONN_REFUSED) has
  verdict `pass`, meaning *the suite detected the fault*. It **never** marks the device
  commissioned. Commissioning status comes only from no-fault cases that observed PASS
  in a clean, uncontaminated run.

## 9. Firmware/version and restart summary

- The inventory is the authority: `device_id`, `serial`, `fw_version` must match the row
  selected by the hostname or address dialled.
- A device restart must not change identity fields. After a restart, a new
  `fw_version` without an inventory update is WRONG_IDENTITY.
- REQ-08: after `systemctl restart`, HEALTH must be `ok` within 10 s, measured from
  the restart command returning to the first PASS HEALTH.

## 10. Gateway (Phase 3; device protocol v1 unchanged)

The gateway (`gateway/gateway.py`, unit `witness-gateway.service` on witness-ctl, DynamicUser) is
a second, independent poller that uses the runner's client and classifier, so it applies the same
11 categories and the same rules.

| Item | Definition |
|---|---|
| Inventory | `/etc/witness/inventory.yaml`, installed by provisioning from the repo's `inventory.yaml`; its sha256 is in `GET /inventory` and in REQ-10 env. |
| Poll | One fresh TCP connection to `<hostname>:<port>` carrying IDENTIFY → HEALTH → READ; resolve 1.0 s, connect 1.0 s, read 2.0 s per exchange, and **one poll deadline of 4.0 s** over all of it. Category = first non-pass exchange. |
| Schedule | One thread per device. Poll k starts at `t0 + k·P` on CLOCK_MONOTONIC, P = 2.0 s (fixed rate). An overrunning poll makes the poller skip the missed slots (`skipped_slots`), never queue them, so at most one poll per device is in flight. Hence detection of any failure ≤ P + 4.0 s = 6 s = 3·P. |
| Freshness | READ judged against ctl's clock window (section 6) and against the gateway's previous READ of that device. A HEALTH `uptime_s` lower than the previous poll's is a **detected restart** (`restarts_detected`, `last_restart`) and resets the seq/ts baseline before that poll's READ is judged. **Corrected 2026-10-18 (audit F-02):** a restart is detected by `restart_between` (section 6) against the last successful HEALTH, so an early restart whose new uptime is *higher* is also detected; `last_restart` records the `rule` and its evidence (uptime advance, elapsed bounds, tolerance). |
| States | `unknown`; `healthy` (PASS and HEALTH ok/sensor ok); `degraded` (PASS_SLOW or HEALTH not ok); `wrong_identity`; `protocol_error` (MALFORMED); `stale` (STALE_DATA); `unreachable` (RESOLVE_FAIL, NO_ROUTE, CONN_REFUSED, CONNECT_TIMEOUT, READ_TIMEOUT, CONN_RESET); `error` (unclassifiable). Every poll decides (no hysteresis): one failed poll = unreachable, one good poll = recovered. |
| Recorded per device | state + since, reachable, last poll (exchanges, category, local port, duration), last_seen (last poll with a complete frame), last_ok, identity + mismatch list, firmware reported/expected/ok, health, freshness (seq, ts, skew_s), consecutive failures/ok, outages (open, last with duration), restarts, last 50 transitions. All `*_mono` = time.monotonic() on witness-ctl. |

HTTP API on `127.0.0.1:8080` (ctl only), JSON bodies, `Cache-Control: no-store`:

| Request | Response |
|---|---|
| `GET /inventory` | 200 `{gateway: {poll_interval_s, poll_deadline_s, now_mono, inventory_sha256, ...}, devices: [{device_id, state, reachable, last_category, last_seen, identity_ok, polls, ...}], summary: {state: n}}` |
| `GET /devices/<id>` | 200 full record (above) + `now_mono`; 404 `{"error":"unknown_device"}`; 400 `{"error":"bad_device_id"}` if the id does not match `^[a-z0-9-]{1,32}$` |
| any other path | 404 `{"error":"not_found"}` |
| POST/PUT/DELETE/PATCH/OPTIONS | 405 `{"error":"method_not_allowed"}` with `Allow: GET, HEAD` |

Measurement references for REQ-08/09 (`tests/live/test_gateway_cases.py`), all on ctl's CLOCK_MONOTONIC:
- REQ-09 detection = gateway transition to `unreachable` − fault command **sent** (upper bound, never
  negative). The same transition − "fault confirmed applied" is also recorded and can be negative,
  because the fault takes effect during the apply call.
- REQ-08: `t_restart` = `witness-faultctl apply restart` returned on ctl; detection = first PASS HEALTH −
  t_restart (also recorded from the command being sent). Gateway recovery = gateway poll that first saw the new
  process (`last_restart.mono`) − first PASS HEALTH, and the runner's API sample time − first PASS HEALTH.
- Recovery after a revert = gateway transition back to healthy − revert command **sent** (run 47: the
  gateway recovered 13 ms before the revert call returned).

Attribution for gateway cases: the gateway is part of the system under test for REQ-08/09 and C-GATEWAY,
so a violated bound is `device` (system under test), not `runner`. Harness exceptions are still `runner`, and
a red preflight (which includes the gateway check) is `infra`.
