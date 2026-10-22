"""Case and fault catalog: the single place that maps cases to requirements.

Loaded into SQLite (cases, case_requirements, faults) at the start of every run, so
the traceability table is derived from the database, never hand-edited. Expected
categories for faults are PREDICTIONS written before the run (protocol.md section 7
for F6, docs/lab-record.md section 12 for F4/F5, committed before those faults first ran);
the observed category is recorded as observed, never forced to match.

Gateway cases (GW-*, C-GATEWAY, FT-F12) observe through the gateway's API: their observed
category is the category of the gateway's own poll, and detection/recovery times go to
results.detection_ms plus the measurements table.
"""

from __future__ import annotations

from dataclasses import dataclass

WRONG_PORT = 5021            # F3: nothing listens there on witness-field
UNUSED_ADDR = "10.77.2.13"   # F4: inside the device subnet, assigned to nothing
FAULT_DEVICE = "dev-a"       # every per-device fault case targets this device (instance a)


@dataclass(frozen=True)
class Case:
    case_id: str
    kind: str                 # commissioning | fault
    reqs: tuple[str, ...]
    description: str
    fault_id: str | None = None
    per_device: bool = True


@dataclass(frozen=True)
class Fault:
    fault_id: str
    catalog_id: str
    kind: str
    params: str
    expected_category: str
    description: str
    # TCP ports the fault makes the runner dial besides the inventory's device ports: the per-case captures on both
    # VMs must include them (independent audit F-07: F3's 5021 SYN/RST was filtered out by "tcp port 5020").
    capture_ports: tuple[int, ...] = ()


FAULTS = (
    Fault("F1", "F1", "service-stop", "vm=witness-field unit=witness-device@a action='systemctl stop'",
          "CONN_REFUSED", "Missing process: device service stopped; kernel answers SYN with RST."),
    Fault("F2", "F2", "sigstop", "vm=witness-field unit=witness-device@a signal=SIGSTOP (then SIGCONT)",
          "READ_TIMEOUT", "Hung process: listener socket still exists, kernel completes the handshake, no reply."),
    Fault("F6-300", "F6", "netem", "vm=witness-field dev=lab0 egress prio+flower tcp src 10.77.2.0/24:5020 all-flags netem delay 300ms",
          "PASS_SLOW", "Delayed packets (300 ms, device->runner direction incl. SYN-ACK): ~300 ms connect + ~300 ms response > 500 ms budget."),
    Fault("F6-3000", "F6", "netem", "vm=witness-field dev=lab0 egress prio+flower tcp src 10.77.2.0/24:5020 all-flags netem delay 3000ms",
          "CONNECT_TIMEOUT", "Delayed packets (3000 ms incl. SYN-ACK): handshake cannot finish inside the 1.0 s connect timeout (protocol.md section 7 prediction)."),
    Fault("F6-3000-data", "F6", "netem", "vm=witness-field dev=lab0 egress prio+flower tcp src 10.77.2.0/24:5020 tcp_flags !SYN netem delay 3000ms",
          "READ_TIMEOUT", "Delayed packets (3000 ms, post-handshake only): connect succeeds, response exceeds the 2.0 s read timeout."),
    Fault("F7", "F7", "hosts-swap", "vm=witness-ctl /etc/hosts managed block dev-a.lab -> 10.77.2.12",
          "WRONG_IDENTITY", "Name points at the wrong (healthy) device."),
    Fault("F7-missing", "F7", "hosts-remove", "vm=witness-ctl /etc/hosts managed block: dev-a.lab line removed",
          "RESOLVE_FAIL", "Naming failure (the F7 family, brief 4.1 'naming failure vs addressing failure'): the name "
          "has no /etc/hosts entry and the lab has no DNS server, so getaddrinfo fails before any packet is sent. "
          "Added in Phase 4 because no catalog fault produced RESOLVE_FAIL on the VMs."),
    Fault("F10-malformed", "F10", "device-mode", "vm=witness-field unit=witness-device@a mode=malformed",
          "MALFORMED", "Device emits invalid JSON (trailing comma)."),
    Fault("F10-truncated", "F10", "device-mode", "vm=witness-field unit=witness-device@a mode=truncated",
          "MALFORMED", "Device emits half a frame, then closes (FIN)."),
    Fault("F10-wrong-id", "F10", "device-mode", "vm=witness-field unit=witness-device@a mode=wrong-id",
          "MALFORMED", "Device echoes id+1: well-formed but uncorrelated."),
    Fault("F3", "F3", "inventory-port", f"runner's inventory copy: dev-a port {WRONG_PORT} (no VM state changed)",
          "CONN_REFUSED", "Wrong port in inventory: field's kernel answers the SYN to an unbound port with RST.",
          capture_ports=(WRONG_PORT,)),
    Fault("F4", "F4", "inventory-addr",
          f"inventory dev-a address {UNUSED_ADDR} (unused); vm=witness-ctl managed /etc/hosts block regenerated from it",
          "CONNECT_TIMEOUT", "Wrong address in inventory. Prediction (lab-record 12, before running): silent drop at "
          "witness-field (not local, forwarding off, no ICMP), so the handshake never completes."),
    Fault("F5", "F5", "route-delete", "vm=witness-ctl ip route del 10.77.2.0/24 via 10.77.1.20 dev lab0",
          "NO_ROUTE", "Missing route: connect() fails locally with ENETUNREACH (Phase 1 prediction)."),
    Fault("F8", "F8", "nft", "vm=witness-field table inet witness_fault_drop input: iifname lab0 ip daddr 10.77.2.11 "
          "tcp dport 5020 drop", "CONNECT_TIMEOUT", "Silent drop: the SYN is discarded, nothing answers."),
    Fault("F9", "F9", "nft", "vm=witness-field table inet witness_fault_reject input: iifname lab0 ip daddr 10.77.2.11 "
          "tcp dport 5020 reject with tcp reset (all segments incl. SYN)",
          "CONN_REFUSED", "Active reject of the SYN: RST from nft while the device still listens."),
    Fault("F9-data", "F9", "nft", "vm=witness-field table inet witness_fault_reject_data input: iifname lab0 ip daddr "
          "10.77.2.11 tcp dport 5020 tcp flags & (syn|rst|psh) == psh reject with tcp reset",
          "CONN_RESET", "Active reject after the handshake: the request segment is answered with RST."),
    Fault("F11-fin", "F11", "device-mode", "vm=witness-field unit=witness-device@a mode=close-after:2",
          "CONN_RESET", "Mid-session drop: after 2 responses the device closes with FIN instead of answering."),
    Fault("F11-rst", "F11", "device-mode", "vm=witness-field unit=witness-device@a mode=reset-after:2",
          "CONN_RESET", "Mid-session drop: after 2 responses the device aborts with RST (SO_LINGER 0)."),
    Fault("F12", "F12", "service-restart", "vm=witness-field systemctl restart witness-device@a while the gateway polls",
          "PASS", "Service restart: the device must be healthy again (first PASS HEALTH) within 10 s and the "
          "gateway must report recovery within 2 poll intervals (REQ-08)."),
    Fault("F13-skew", "F13", "device-mode", "vm=witness-field unit=witness-device@a mode=clock-skew:+30s",
          "STALE_DATA", "Skewed data: READ ts 30 s ahead of the runner's clock window."),
    Fault("F13-repeat-seq", "F13", "device-mode", "vm=witness-field unit=witness-device@a mode=repeat-seq",
          "STALE_DATA", "Replayed data: READ seq stops increasing (ts kept current)."),
)
DEVICE_MODES = {"F10-malformed": "malformed", "F10-truncated": "truncated", "F10-wrong-id": "wrong-id",
                "F11-fin": "close-after:2", "F11-rst": "reset-after:2",
                "F13-skew": "clock-skew:+30s", "F13-repeat-seq": "repeat-seq"}
NFT_KINDS = {"F8": "drop", "F9": "reject", "F9-data": "reject-data"}
FAULTS_BY_ID = {f.fault_id: f for f in FAULTS}

CASES = (
    Case("C-IDENTIFY", "commissioning", ("REQ-01",),
         "IDENTIFY by hostname observes PASS (<=500 ms) and device_id/serial/fw_version equal the inventory row."),
    Case("C-HEALTH", "commissioning", ("REQ-03",),
         "HEALTH observes PASS (<=500 ms) with status=ok and sensor_ok=true."),
    Case("C-READ-CLOCK", "commissioning", ("REQ-04",),
         "10 READs on one connection: every ts within [t_send-2 s, t_recv+2 s] of the runner clock."),
    Case("C-READ-SERIES", "commissioning", ("REQ-05",),
         "HEALTH, 10 READs, HEALTH on one connection: seq strictly increasing, ts non-decreasing, no restart."),
    Case("C-ENVIRONMENT", "commissioning", ("REQ-10",),
         "The run's environment rows hold every required REQ-10 key (inventory VMs and devices) in its valid "
         "representation, consistent with the run row (runner/evidence.check_environment).", per_device=False),
    Case("FT-F1-STOPPED", "fault", ("REQ-01",),
         "F1: with witness-device@a stopped, IDENTIFY dev-a.lab observes CONN_REFUSED (device not commissionable).",
         fault_id="F1"),
    Case("FT-F2-HUNG", "fault", ("REQ-07", "REQ-06"),
         "F2: with the device process SIGSTOPped, IDENTIFY observes READ_TIMEOUT and returns within read timeout + 0.5 s.",
         fault_id="F2"),
    Case("FT-F6-DELAY-300", "fault", ("REQ-07",),
         "F6 300 ms: observes PASS_SLOW with 500 < latency_ms <= 2000 recorded.", fault_id="F6-300"),
    Case("FT-F6-DELAY-3000", "fault", ("REQ-07",),
         "F6 3000 ms incl. SYN-ACK: observes CONNECT_TIMEOUT (handshake > 1.0 s) within connect timeout + 0.5 s.",
         fault_id="F6-3000"),
    Case("FT-F6-DELAY-3000-DATA", "fault", ("REQ-07",),
         "F6 3000 ms post-handshake only: observes READ_TIMEOUT within read timeout + 0.5 s.",
         fault_id="F6-3000-data"),
    Case("FT-F7-NAME-SWAP", "fault", ("REQ-02",),
         "F7: dev-a.lab resolves to 10.77.2.12; IDENTIFY observes WRONG_IDENTITY naming device_id and serial; dev-a not commissioned.",
         fault_id="F7"),
    Case("FT-F7-NAME-MISSING", "fault", ("REQ-01",),
         "F7 naming variant: dev-a.lab removed from /etc/hosts; IDENTIFY observes RESOLVE_FAIL (no SYN on the wire); "
         "dev-a is not commissionable by name while the device itself is healthy.", fault_id="F7-missing"),
    Case("FT-F10-MALFORMED", "fault", ("REQ-06",),
         "F10 malformed: IDENTIFY observes MALFORMED; case completes < 30 s with a result row.", fault_id="F10-malformed"),
    Case("FT-F10-TRUNCATED", "fault", ("REQ-06",),
         "F10 truncated: IDENTIFY observes MALFORMED (truncated); case completes < 30 s.", fault_id="F10-truncated"),
    Case("FT-F10-WRONG-ID", "fault", ("REQ-06",),
         "F10 wrong-id: IDENTIFY observes MALFORMED (wrong_id), never PASS; case completes < 30 s.", fault_id="F10-wrong-id"),
    # ---- Phase 3: remaining catalog faults (runner observation)
    Case("FT-F3-WRONG-PORT", "fault", ("REQ-01",),
         f"F3: inventory says dev-a port {WRONG_PORT}; IDENTIFY observes CONN_REFUSED (not commissionable from that "
         "inventory) while the real device keeps answering on 5020.", fault_id="F3"),
    Case("FT-F4-WRONG-ADDR", "fault", ("REQ-01", "REQ-07"),
         f"F4: inventory says dev-a is {UNUSED_ADDR} (unused); IDENTIFY observes the predicted CONNECT_TIMEOUT within "
         "connect timeout + 0.5 s; field counts the discarded SYNs (Ip InAddrErrors).", fault_id="F4"),
    Case("FT-F5-NO-ROUTE", "fault", ("REQ-01",),
         "F5: device route deleted on witness-ctl; IDENTIFY observes NO_ROUTE immediately (no SYN on the wire).",
         fault_id="F5"),
    Case("FT-F8-DROP", "fault", ("REQ-01", "REQ-07"),
         "F8: nft drops TCP 5020 to dev-a on witness-field; IDENTIFY observes CONNECT_TIMEOUT within connect "
         "timeout + 0.5 s; the SYN reaches field (field capture) and the nft counter rises.", fault_id="F8"),
    Case("FT-F9-REJECT", "fault", ("REQ-01",),
         "F9: nft rejects TCP 5020 to dev-a with tcp reset; IDENTIFY observes CONN_REFUSED while the device still "
         "listens.", fault_id="F9"),
    Case("FT-F9-REJECT-DATA", "fault", ("REQ-01",),
         "F9 data: nft rejects only the request segment with tcp reset; the handshake completes and IDENTIFY observes "
         "CONN_RESET with 0 response bytes.", fault_id="F9-data"),
    Case("FT-F11-CLOSE-FIN", "fault", ("REQ-05",),
         "F11 FIN: READ series on one connection; reads 1-2 PASS, read 3 observes CONN_RESET (EOF, 0 bytes); the "
         "series is not complete, so REQ-05 cannot pass on it.", fault_id="F11-fin"),
    Case("FT-F11-CLOSE-RST", "fault", ("REQ-05",),
         "F11 RST: as F11 FIN but the device aborts with RST; observes CONN_RESET (reset, 0 bytes).",
         fault_id="F11-rst"),
    Case("FT-F13-SKEW", "fault", ("REQ-04",),
         "F13 skew: READ ts 30 s ahead; observes STALE_DATA (ts_outside_window).", fault_id="F13-skew"),
    Case("FT-F13-REPEAT-SEQ", "fault", ("REQ-05",),
         "F13 repeat-seq: second READ repeats seq; observes STALE_DATA (seq_not_increasing).",
         fault_id="F13-repeat-seq"),
    # ---- Phase 3: gateway (REQ-08, REQ-09)
    Case("C-GATEWAY", "commissioning", ("REQ-09",),
         "Gateway control (no fault): GET /devices/<id> reports healthy, inventory identity and firmware, fresh READ, "
         "last_seen within 2 poll intervals, polls advancing at P; API error codes as documented. A detector that "
         "flags healthy devices would make REQ-09 meaningless."),
    Case("FT-F12-RESTART", "fault", ("REQ-08",),
         "F12: systemctl restart witness-device@a while the gateway polls; first PASS HEALTH <= 10 s after the restart "
         "returned; gateway reports the restarted device healthy <= 2 P after that; identity unchanged; seq/uptime "
         "reset (baseline reset, not STALE_DATA). Then an early second restart of the young new process (its "
         "successor may report a HIGHER uptime): the gateway must still detect it, never report STALE_DATA, and "
         "report healthy <= 2 P after its first PASS HEALTH.", fault_id="F12"),
    Case("GW-F1-UNREACHABLE", "fault", ("REQ-09",),
         "F1 via the gateway: dev-a stopped; gateway marks dev-a unreachable (CONN_REFUSED) <= 3 P after the fault "
         "command; dev-b stays healthy; dev-a healthy again <= 2 P after the revert.", fault_id="F1"),
    Case("GW-F5-UNREACHABLE", "fault", ("REQ-09",),
         "F5 via the gateway: route deleted; gateway marks both devices unreachable (NO_ROUTE) <= 3 P; both healthy "
         "again <= 2 P after the revert.", fault_id="F5"),
    Case("GW-F8-UNREACHABLE", "fault", ("REQ-09",),
         "F8 via the gateway: nft drop for dev-a; gateway marks dev-a unreachable (CONNECT_TIMEOUT) <= 3 P; dev-b "
         "stays healthy; dev-a healthy again <= 2 P after the revert.", fault_id="F8"),
)
CASES_BY_ID = {c.case_id: c for c in CASES}

def instance_device(case: Case) -> str | None:
    """The device of a case instance that is not parametrized by device: FAULT_DEVICE for a per-device (fault) case,
    None for a run-level case. tests/live/conftest.py records the run plan and the result with it."""
    return FAULT_DEVICE if case.per_device else None


# Everything a run must prove before it commissions a device (runner/db.py COMMISSIONING_GAPS): EVERY commissioning
# case of the catalog, per device or once per run. Derived from CASES, never from the results a run happened to
# record (independent audit F-01: a HEALTH-only run commissioned both devices).
COMMISSIONING_REQUIRED = tuple((c.case_id, c.per_device) for c in CASES if c.kind == "commissioning")


def counts(n_devices: int) -> dict[str, int]:
    """Catalog-derived counts quoted by the reports and README (independent audit F-08). Fault cases dial dev-a
    only, so each fault case is one live test instance; commissioning cases run per device or once per run."""
    return {"fault_types": len({f.catalog_id for f in FAULTS}), "fault_variants": len(FAULTS),
            "fault_test_instances": sum(1 for c in CASES if c.kind == "fault"),
            "commissioning_instances": sum(n_devices if per_dev else 1 for _, per_dev in COMMISSIONING_REQUIRED),
            "cases": len(CASES)}


@dataclass(frozen=True)
class Mutant:
    mutant_id: str
    spec: str            # device/mutants.py grammar; {other_serial} is filled from the inventory at deploy
    description: str
    predicted: str       # written BEFORE the first mutant run: which cases/REQs should catch it, and how


# Brief section 7.4. Deployed on dev-a (instance a) only; dev-b stays stock as the in-run control.
MUTANT_DEVICE = "dev-a"
MUTANTS = (
    Mutant("M1", "other-serial:{other_serial}", "returns the other device's serial in IDENTIFY",
           "C-IDENTIFY/dev-a WRONG_IDENTITY (REQ-01, REQ-02: never commissioned); C-GATEWAY/dev-a not healthy "
           "(gateway sees WRONG_IDENTITY)."),
    Mutant("M2", "seq-reuse", "reuses seq after 5 reads (seq 1..5 repeats)",
           "C-READ-CLOCK and C-READ-SERIES/dev-a STALE_DATA seq_not_increasing (REQ-05; 10 READs always span a "
           "wrap); C-GATEWAY/dev-a may also see STALE_DATA when one of its READs lands on a wrap."),
    Mutant("M3", "no-newline", "omits the trailing newline on every response",
           "Every dev-a exchange: bytes arrive but no frame end before the 2 s read timeout -> MALFORMED "
           "(incomplete:NB) in C-IDENTIFY/C-HEALTH/C-READ-*/dev-a (REQ-01, REQ-03, REQ-04, REQ-05; REQ-06 "
           "bounded); gateway dev-a unhealthy."),
    Mutant("M4", "off-by-one-id", "echoes the wrong id (id-1)",
           "Every dev-a exchange MALFORMED wrong_id (REQ-01, REQ-03, REQ-04, REQ-05); gateway dev-a unhealthy."),
    Mutant("M5", "temp-string", "reports temp_c as a string",
           "C-READ-CLOCK and C-READ-SERIES/dev-a MALFORMED (schema: temp_c type) (REQ-04, REQ-05); IDENTIFY and "
           "HEALTH unaffected; gateway dev-a unhealthy (its poll READs)."),
    Mutant("M6", "slow-7th", "sleeps 2.5 s on every 7th request (process-wide count)",
           "Nondeterministic by design: whichever exchange is the device's 7th/14th/... request (runner or gateway) "
           "gets READ_TIMEOUT (2.5 s > 2.0 s read timeout). Runner commissioning cases retry once, so a case can "
           "pass on retry and be reported FLAKE (fail) or fail twice. A READ series (10-12 requests) usually holds a "
           "multiple of 7 unless gateway polls interleave and take it, so C-READ-CLOCK/C-READ-SERIES/dev-a are the "
           "likeliest catchers (REQ-04/05); a run where no runner exchange draws a 7th request is a false negative."),
)
MUTANTS_BY_ID = {m.mutant_id: m for m in MUTANTS}


def mutant_spec(mutant_id: str, devices: list[dict]) -> str:
    other = next(d for d in devices if d["device_id"] != MUTANT_DEVICE)
    return MUTANTS_BY_ID[mutant_id].spec.format(other_serial=other["serial"])

# REQ-10 keys (docs/requirements.md). {vm} and {device} are expanded per run.
ENV_REQUIRED = ("kernel.{vm}", "distro.{vm}", "python", "git_sha", "git_dirty", "fw_version.{device}",
                "qdisc.{vm}", "nft.{vm}", "chrony.offset", "runs.clean_env")
