"""Reference evidence store for the acceptance-contract harness (docs/acceptance-contract.md).

Builds a complete, valid results store and its evidence directory from a declarative description, through the
production WRITERS only (runner/db.py, the calls tests/live/conftest.py records with). No verifier code is used here.
Every record and capture is synthetic fixture data with known answers, never evidence of a lab result.

Reference composition (run order): five fresh-clone baselines T1-T5, an older full fault run F0, the current full
fault run F, one run per brief mutant M1-M6 (each caught on dev-a; M6 as a retry FLAKE), the final baseline B.
Variants add or replace runs to form the legitimate controls (deadline cut, genuinely partial run, superseded
failure, genuine current failure, gateway bound and API failures, a killed run found by the next session, runs that
predate the run plan). Every decided result records the decision predicates the live case records (OWN_PREDICATES).
"""
from __future__ import annotations

import inspect
import json
import struct
from dataclasses import dataclass, field
from pathlib import Path

from runner import catalog, db
from runner.classify import Classification, Observation
from scripts.lib import inventory

REPO = Path(__file__).resolve().parents[2]
INV = inventory.load(REPO / "inventory.yaml")
DEV = {d["device_id"]: d for d in INV["devices"]}
DEVICES = [d["device_id"] for d in INV["devices"]]
VMS = {v["role"]: v for v in INV["lab"]["vms"]}
CTL, FIELD = VMS["ctl"]["name"], VMS["field"]["name"]
RUNNER_ADDR = VMS["ctl"]["l2_address"]
SHA = "0123456789abcdef0123456789abcdef01234567"
QDISC = "qdisc fq_codel 0: root refcnt 2 limit 10240p flows 1024 quantum 1514 target 5ms interval 100ms"
NFT = "table inet witness_isolation {\n\tchain output {\n\t\ttype filter hook output priority filter; policy drop;\n\t}\n}\n"
FAULT_DEVICE = "dev-a"
HAS_PLAN = hasattr(db, "record_plan")          # schema v5 (run plan); absent before the repair
HAS_DECISION = "predicates" in inspect.signature(db.insert_result).parameters   # v5 results.predicates
# files the live Injector writes when it applies a fault of each kind (tests/live/conftest.py), per application
FAULT_KIND_FILES = {"inventory-addr": ("counters", "hosts", "inventory"), "nft": ("counters",),
                    "hosts-swap": ("hosts",), "hosts-remove": ("hosts",), "inventory-port": ("inventory",)}
# a passing FT-F13-SKEW records its READ 30 s outside REQ-04's 2 s window: that IS the predicted observation
OUTSIDE_BOUND_ON_PASS = {("FT-F13-SKEW", "read_skew_s")}

# measurements each case records before its verdict (tests/live), expanded per affected device
MEASUREMENTS = {
    "C-GATEWAY": ("gateway_last_seen_age_ms", "gateway_poll_period_ms", "gateway_poll_duration_ms"),
    "FT-F12-RESTART": ("device_healthy_after_restart_ms", "device_healthy_after_restart_cmd_ms", "restart_call_ms",
                       "systemctl_restart_ms", "health_probes_until_pass", "gateway_recovery_ms",
                       "gateway_recovery_api_observed_ms", "early_restart_device_healthy_ms",
                       "early_restart_gateway_recovery_ms", "early_restart_gateway_recovery_api_observed_ms",
                       "early_restart_uptime_rise_s"),
    "FT-F13-SKEW": ("read_skew_s",),
    "FT-F4-WRONG-ADDR": ("field_Ip.InAddrErrors_delta", "field_Icmp.OutDestUnreachs_delta", "field_Tcp.OutRsts_delta"),
    "FT-F5-NO-ROUTE": ("connect_ms",),
    "FT-F7-NAME-MISSING": ("resolve_ms",),
    "FT-F7-NAME-SWAP": ("gateway_wrong_identity_ms",),
    "FT-F8-DROP": ("field_Tcp.OutRsts_delta", "field_Icmp.OutDestUnreachs_delta"),
}
GW_AFFECTED = {"GW-F1-UNREACHABLE": ["dev-a"], "GW-F5-UNREACHABLE": ["dev-a", "dev-b"],
               "GW-F8-UNREACHABLE": ["dev-a"]}
for _c, _devs in GW_AFFECTED.items():
    MEASUREMENTS[_c] = tuple(f"{m}.{x}" for x in _devs for m in (
        "gateway_detection_ms", "gateway_detection_from_applied_ms", "gateway_recovery_after_revert_ms",
        "gateway_recovery_from_revert_returned_ms")) + ("fault_apply_call_ms", "gateway_unreachable_api_observed_ms")
GATEWAY_FILES = {"C-GATEWAY": 1, "GW-F1-UNREACHABLE": 1, "GW-F5-UNREACHABLE": 1, "GW-F8-UNREACHABLE": 1,
                 "FT-F12-RESTART": 2, "FT-F3-WRONG-PORT": 1, "FT-F7-NAME-SWAP": 1, "FT-F7-NAME-MISSING": 1}
SAMPLES_FILES = {"GW-F1-UNREACHABLE": 1, "GW-F5-UNREACHABLE": 1, "GW-F8-UNREACHABLE": 1, "FT-F12-RESTART": 2}
# the case's own predicates each live case records with its verdict (tests/live: extra_predicates of case.finish,
# the predicates of finish_observed; C-ENVIRONMENT one per REQ-10 key), written here from the live tests, not taken
# from the verifier (tests/unit/test_decision_predicates.py anchors both copies to tests/live)
OWN_PREDICATES = {
    "C-GATEWAY": ("api_inventory_200_lists_inventory", "gateway_inventory_is_repo_inventory", "poll_interval_is_2s",
                  "state_healthy_reachable", "identity_matches_inventory", "firmware_matches_inventory", "health_ok",
                  "read_fresh", "last_seen_within_2P", "polls_advancing", "poll_period_is_P",
                  "no_consecutive_failures", "api_unknown_device_404", "api_bad_id_400", "api_post_405_with_allow"),
    "C-ENVIRONMENT": tuple(f"{k}.{vm}" for k in ("kernel", "distro", "qdisc", "nft") for vm in (CTL, FIELD))
    + ("python", "git_sha", "git_dirty", "chrony.offset", "runs.clean_env") + tuple(f"fw_version.{d}" for d in DEVICES),
    "FT-F12-RESTART": ("first_pass_health_within_10s", "gateway_recovery_within_2P", "gateway_detected_restart",
                       "new_pid", "held_connection_reset_by_old_process", "identity_unchanged_after_restart",
                       "seq_restarted", "new_process_by_uptime", "early_restart_new_pid",
                       "early_restart_healthy_within_10s", "early_restart_gateway_detected",
                       "early_restart_gateway_recovery_within_2P", "early_restart_never_stale"),
    "FT-F2-HUNG": ("returned_within_read_timeout_plus_0.5s", "within_case_deadline"),
    "FT-F6-DELAY-300": ("latency_recorded_in_(500,2000]",),
    "FT-F6-DELAY-3000": ("connect_returned_within_timeout_plus_0.5s",),
    "FT-F6-DELAY-3000-DATA": ("returned_within_read_timeout_plus_0.5s",),
    "FT-F7-NAME-SWAP": ("detail_names_serial_and_device_id", "dialled_address_was_other_device",
                        "dev_a_not_commissioned", "gateway_flags_wrong_identity_within_3P"),
    "FT-F7-NAME-MISSING": ("no_address_resolved", "failed_before_resolve_timeout",
                           "gateway_sees_resolve_fail_within_3P"),
    "FT-F10-MALFORMED": ("detail_bad_json", "within_case_deadline"),
    "FT-F10-TRUNCATED": ("detail_truncated", "within_case_deadline"),
    "FT-F10-WRONG-ID": ("detail_wrong_id", "within_case_deadline"),
    "FT-F3-WRONG-PORT": ("dialled_port_5021", "device_answers_on_inventoried_port", "gateway_once_agrees_CONN_REFUSED"),
    "FT-F4-WRONG-ADDR": ("dialled_unused_address", "connect_returned_within_timeout_plus_0.5s"),
    "FT-F5-NO-ROUTE": ("failed_before_connect_timeout", "errno_ENETUNREACH"),
    "FT-F8-DROP": ("connect_returned_within_timeout_plus_0.5s",),
    "FT-F9-REJECT": ("device_process_still_running",),
    "FT-F9-REJECT-DATA": ("handshake_completed", "zero_response_bytes"),
    "FT-F11-CLOSE-FIN": ("two_reads_then_reset", "read_end_eof", "detail_eof_before_response", "zero_response_bytes",
                         "series_incomplete_not_pass"),
    "FT-F11-CLOSE-RST": ("two_reads_then_reset", "read_end_reset", "detail_reset_before_response",
                         "zero_response_bytes", "series_incomplete_not_pass"),
    "FT-F13-SKEW": ("first_read_stale_by_+30s",),
    "FT-F13-REPEAT-SEQ": ("first_read_pass_second_stale", "detail_seq_not_increasing"),
}
for _c, _devs in GW_AFFECTED.items():
    _cat = catalog.FAULTS_BY_ID[catalog.CASES_BY_ID[_c].fault_id].expected_category
    OWN_PREDICATES[_c] = tuple(f"{x}_{p}" for x in _devs for p in ("unreachable_within_3P", f"category_{_cat}",
                                                                    "recovered_within_2P_of_revert")) \
        + tuple(f"{x}_stayed_healthy" for x in DEVICES if x not in _devs) + ("api_observed_within_3P",)


def case_predicates(case_id: str) -> tuple[str, ...]:
    """The case's own predicate names as the live case records them for the fixture's instances (fault cases on
    FAULT_DEVICE)."""
    return OWN_PREDICATES.get(case_id, ())


# ---------------------------------------------------------------- exchange kinds -> recorded fields + wire frames

@dataclass
class X:
    """One planned exchange of an attempt. kind: ok slow refused ctimeout noroute resolve rtimeout reset malformed
    wrongid stale degraded notstarted. conn: connection index within the attempt (same index = same connection)."""
    cmd: str
    kind: str = "ok"
    conn: int = 0


ESTABLISHED = {"ok", "slow", "rtimeout", "reset", "malformed", "wrongid", "stale", "degraded"}
CATEGORY = {"ok": "PASS", "slow": "PASS_SLOW", "refused": "CONN_REFUSED", "ctimeout": "CONNECT_TIMEOUT",
            "noroute": "NO_ROUTE", "resolve": "RESOLVE_FAIL", "rtimeout": "READ_TIMEOUT", "reset": "CONN_RESET",
            "malformed": "MALFORMED", "wrongid": "WRONG_IDENTITY", "stale": "STALE_DATA", "degraded": "PASS",
            "notstarted": None}


def tcp_frame(src: str, dst: str, sport: int, dport: int, flags: int) -> bytes:
    tcp = struct.pack(">HHIIBBHHH", sport, dport, 1, 0, 5 << 4, flags, 64240, 0, 0)
    ip = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp), 1, 0, 64, 6, 0,
                     bytes(int(x) for x in src.split(".")), bytes(int(x) for x in dst.split(".")))
    return b"\x52\x55\x55\x77\x01\x20\x52\x55\x55\x77\x01\x10\x08\x00" + ip + tcp


def pcap(frames: list[bytes], t0: int = 1_760_000_000) -> bytes:
    out = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 512, 1)
    for i, f in enumerate(frames):
        out += struct.pack("<IIII", t0 + i, 0, len(f), len(f)) + f
    return out


def pcap_frames(data: bytes) -> list[bytes]:
    """The frames of a classic little-endian pcap this module wrote."""
    out, off = [], 24
    while off < len(data):
        incl = struct.unpack("<I", data[off + 8:off + 12])[0]
        out.append(data[off + 16:off + 16 + incl])
        off += 16 + incl
    return out


def matches(frame: bytes, addr: str, port: int, lport: int | None) -> bool:
    """The generator's own flow matcher (Ethernet/IPv4/TCP frames it built itself)."""
    a = bytes(int(x) for x in addr.split("."))
    sport, dport = struct.unpack(">HH", frame[34:38])
    return a in (frame[26:30], frame[30:34]) and port in (sport, dport) and (lport is None or lport in (sport, dport))


def payload(cmd: str, req_id: int, dev: dict, kind: str, seq: int) -> bytes:
    if kind == "malformed":
        return b'{"id": ' + str(req_id).encode() + b', "device_id": "x",}\n'
    if cmd == "IDENTIFY":
        d = DEV[next(x for x in DEVICES if x != dev["device_id"])] if kind == "wrongid" else dev
        obj = {"id": req_id, "device_id": d["device_id"], "serial": d["serial"], "model": "WIT-SIM",
               "fw_version": d["fw_version"]}
    elif cmd == "HEALTH":
        obj = {"id": req_id, "status": "degraded" if kind == "degraded" else "ok", "uptime_s": 100.0 + seq,
               "sensor_ok": True}
    else:
        obj = {"id": req_id, "seq": seq if kind != "stale" else 1, "ts": "2026-10-19T12:00:00.000Z",
               "temp_c": 21.5, "rh_pct": 40.0}
    return (json.dumps(obj, separators=(",", ":")) + "\n").encode()


# ---------------------------------------------------------------- instance descriptions

@dataclass
class Inst:
    case_id: str
    device_id: str | None
    attempts: list[list[X]] = field(default_factory=list)   # runner cases
    verdict: str = "pass"
    attribution: str = "none"
    observed: str | None = "auto"       # gateway cases: the gateway's category
    outcomes: list[str] | None = None   # per attempt; default derived (ok when category == expected)
    predicates: list[dict] | None = None
    decisive: int | None = None         # F12
    detail: str = "fixture"
    overrides: dict = field(default_factory=dict)   # result columns set as given (fixtures injecting an anomaly)
    measurements: dict | None = None    # {name: (value, bound)} recorded whatever the verdict (default: on pass)
    case_predicates: dict | None = None  # predicates the verdict was decided on, beyond the final attempt's


def target(case_id: str, device_id: str | None) -> tuple[str, str | None, int]:
    """(hostname, address, port) the case dials, as the live fixtures fault it (Injector in tests/live/conftest.py)."""
    d = DEV[device_id]
    host, addr, port = d["hostname"], d["address"], d["port"]
    fid = catalog.CASES_BY_ID[case_id].fault_id
    if fid == "F3":
        port = catalog.WRONG_PORT
    elif fid == "F4":
        addr = catalog.UNUSED_ADDR
    elif fid == "F7":
        addr = DEV[next(x for x in DEVICES if x != device_id)]["address"]
    elif fid == "F7-missing":
        addr = None
    return host, addr, port


def expected_of(case_id: str) -> str | None:
    c = catalog.CASES_BY_ID[case_id]
    if c.fault_id:
        return catalog.FAULTS_BY_ID[c.fault_id].expected_category
    return None if case_id == "C-ENVIRONMENT" else "PASS"


GATEWAY_CASES = {"C-GATEWAY", *GW_AFFECTED}
SINGLE = {"FT-F1-STOPPED": "refused", "FT-F2-HUNG": "rtimeout", "FT-F6-DELAY-300": "slow",
          "FT-F6-DELAY-3000": "ctimeout", "FT-F6-DELAY-3000-DATA": "rtimeout", "FT-F7-NAME-SWAP": "wrongid",
          "FT-F7-NAME-MISSING": "resolve", "FT-F10-MALFORMED": "malformed", "FT-F10-TRUNCATED": "malformed",
          "FT-F10-WRONG-ID": "malformed", "FT-F3-WRONG-PORT": "refused", "FT-F4-WRONG-ADDR": "ctimeout",
          "FT-F5-NO-ROUTE": "noroute", "FT-F8-DROP": "ctimeout", "FT-F9-REJECT": "refused",
          "FT-F9-REJECT-DATA": "reset"}


def passing(case_id: str, device_id: str | None) -> Inst:
    """The instance as a correct device under a correctly applied fault records it (verdict pass)."""
    if case_id in GATEWAY_CASES or case_id == "C-ENVIRONMENT":
        return Inst(case_id, device_id)
    series = {"C-IDENTIFY": [X("IDENTIFY")], "C-HEALTH": [X("HEALTH")],
              "C-READ-CLOCK": [X("READ")] * 10,
              "C-READ-SERIES": [X("HEALTH")] + [X("READ")] * 10 + [X("HEALTH")],
              "FT-F11-CLOSE-FIN": [X("READ"), X("READ"), X("READ", "reset")],
              "FT-F11-CLOSE-RST": [X("READ"), X("READ"), X("READ", "reset")],
              "FT-F13-SKEW": [X("READ", "stale")],
              "FT-F13-REPEAT-SEQ": [X("READ"), X("READ", "stale")],
              "FT-F12-RESTART": [X("HEALTH"), X("READ"), X("READ", "reset"), X("HEALTH", conn=1),
                                 X("IDENTIFY", conn=2), X("READ", conn=3), X("HEALTH", conn=3), X("HEALTH", conn=4)]}
    if case_id in SINGLE:
        return Inst(case_id, device_id, [[X("IDENTIFY", SINGLE[case_id])]])
    inst = Inst(case_id, device_id, [list(series[case_id])])
    if case_id == "FT-F12-RESTART":
        inst.decisive = 3
    return inst


def predicates_for(case_id: str, xs: list[X], complete: bool) -> dict:
    """What runner/cases.py stores as attempts.predicates for this attempt."""
    if case_id == "C-HEALTH":
        x = xs[0]
        if CATEGORY[x.kind] in ("PASS", "PASS_SLOW"):
            return {"status_ok": x.kind != "degraded", "sensor_ok": True}
        return {"health_payload": False}
    if case_id in ("C-READ-CLOCK", "C-READ-SERIES", "FT-F11-CLOSE-FIN", "FT-F11-CLOSE-RST", "FT-F13-SKEW",
                   "FT-F13-REPEAT-SEQ"):
        return {"reads_complete": True} if complete else {}
    return {}


# ---------------------------------------------------------------- writer

class Builder:
    def __init__(self, path: Path | None = None, root: Path | None = None, *, conn=None, legacy_runs: int = 0):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.legacy_left = legacy_runs
        if conn is not None:                         # an existing fixture store (tests/unit/storefix.py)
            self.conn = conn
        elif legacy_runs:                            # first runs on a v4 store, then the v5 migration
            full = db.MIGRATIONS
            db.MIGRATIONS = full[:4]
            try:
                self.conn = db.connect(path)
            finally:
                db.MIGRATIONS = full
        else:
            self.conn = db.connect(path)
        if conn is None:
            db.sync_reference(self.conn, requirements=db.requirements_from_md(REPO / "docs/requirements.md"),
                              devices=INV["devices"], cases=catalog.CASES, faults=catalog.FAULTS,
                              mutants=catalog.MUTANTS)
        self.t = 1_760_000_000.0
        self.lport = 40000
        self.runs: dict[str, int] = {}

    def tick(self, dt: float = 0.01) -> float:
        self.t += dt
        return self.t

    def save(self, run: int, rel: str, data: bytes | str, kind: str, rid: int | None) -> None:
        p = self.root / f"run-{run}" / rel
        n = 2
        while p.exists():        # as tests/live/conftest.py Lab.save: never overwrite a file that may be indexed
            p = p.with_name(f"{Path(rel).stem}.dup{n}{Path(rel).suffix}")
            n += 1
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode())
        db.add_evidence(self.conn, run_id=run, result_id=rid, kind=kind, root=self.root, path=p)

    def env(self, kind: str, mutant: str | None, provenance: str | None, withheld: bool) -> dict:
        env = {"python": "3.12.3", "pytest": "9.1.1", "git_sha": SHA, "git_dirty": "0", "runs.clean_env": "1",
               "runs.kind": kind, "mutant": mutant or "none",
               "chrony.offset": f"offset_s=+0.000021 delay_s=0.000324 samples=4/4 server={RUNNER_ADDR}"}
        for vm in (CTL, FIELD):
            env.update({f"kernel.{vm}": "6.8.0-134-generic", f"distro.{vm}": "Ubuntu 24.04.4 LTS",
                        f"qdisc.{vm}": f"lab0: {QDISC}" + ("\nfield0: qdisc noqueue 0: root refcnt 2" if vm == FIELD
                                                           else ""), f"nft.{vm}": NFT})
            if provenance:
                env[f"provenance.{vm}"] = f"golden-restore id={provenance} boot_id={provenance}-{vm}"
        for d in INV["devices"]:
            env[f"fw_version.{d['device_id']}"] = d["fw_version"]
            env[f"device_build.{d['device_id']}"] = "stock"
        if mutant:
            env[f"device_build.{catalog.MUTANT_DEVICE}"] = "mutant:" + catalog.mutant_spec(mutant, INV["devices"])
            if withheld:
                env[f"fw_version.{catalog.MUTANT_DEVICE}"] = "unavailable (MALFORMED: incomplete:86B)"
        return env

    def checks(self, run: int, phase: str, rid: int | None, fail: bool = False) -> None:
        for vm, names in ((CTL, ("route", "hosts")), (FIELD, ("netem", "nft", "devices"))):
            db.add_checks(self.conn, run, phase, vm, [{"name": n, "status": "FAIL" if fail and n == "route" else "PASS",
                                                       "detail": "fixture"} for n in names], rid)

    def run(self, label: str, kind: str, insts: list[Inst], *, mutant: str | None = None,
            provenance: str | None = None, withheld: bool = False, finished: bool = True, clean: bool = True,
            env: dict | None = None) -> int:
        if self.legacy_left == 0 and self.conn.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] < len(db.MIGRATIONS):
            db.migrate(self.conn)
        run = db.start_run(self.conn, kind=kind, git_sha=SHA, git_dirty=0, clean_env=int(clean), runner_host="fixture",
                           notes=label, mutant_id=mutant)
        self.runs[label] = run
        self.checks(run, "preflight", None, fail=not clean)
        self.save(run, "session/preflight-ctl.txt", "ctl preflight GREEN\n", "preflight", None)
        self.save(run, "session/preflight-field.txt", "field preflight GREEN\n", "preflight", None)
        if HAS_PLAN and self.legacy_left == 0:
            text = db.record_plan(self.conn, run, [(i.case_id, i.device_id) for i in insts])
            self.save(run, "session/plan.json", text, "plan", None)
        env = self.env(kind, mutant, provenance, withheld) if env is None else env
        db.put_env(self.conn, run, env)
        db.set_clean_env(self.conn, run, clean)
        self.save(run, "session/environment.json", json.dumps(env, indent=1, sort_keys=True), "environment", None)
        for inst in insts:
            self.instance(run, inst)
        if finished:
            self.finish(run)
        if self.legacy_left:
            self.legacy_left -= 1
        return run

    def finish(self, run: int) -> None:
        """The session teardown (tests/live/conftest.py `lab`): session postflight, its files, then finish_run. A run
        that never finished (killed) has none of it."""
        self.checks(run, "session-postflight", None)
        self.save(run, "session/postflight-ctl.txt", "ctl postflight GREEN\n", "postflight", None)
        self.save(run, "session/postflight-field.txt", "field postflight GREEN\n", "postflight", None)
        self.save(run, "session/field-commands.jsonl", '{"cmd": "status"}\n', "command-log", None)
        db.finish_run(self.conn, run)

    # -- one case instance, recorded as the live `case` fixture records it
    def instance(self, run: int, inst: Inst) -> int:
        spec = catalog.CASES_BY_ID[inst.case_id]
        dev = inst.device_id
        expected = expected_of(inst.case_id)
        host, addr, port = target(inst.case_id, dev) if dev else (None, None, None)
        rel = f"{inst.case_id}__{dev or 'run'}"
        frames: list[bytes] = []
        attempts = []                                  # (no, category, outcome, preds, [(Observation, Classif)])
        seq = 0
        for no, xs in enumerate(inst.attempts, 1):
            conns: dict[int, dict] = {}
            recorded = []
            for x in xs:
                c = conns.get(x.conn)
                if c is None:
                    self.lport += 1
                    c = conns[x.conn] = {"lport": self.lport, "next": 1, "frames": [], "open": False}
                cat = CATEGORY[x.kind]
                o = Observation(host=host, port=port, cmd=x.cmd, req_id=c["next"], addr=addr)
                o.t_start_wall = self.tick()
                detail = x.kind
                if x.kind == "notstarted":
                    o.addr, o.stage_failed, o.error = None, "resolve", "not_started"
                    detail = "case_deadline_exhausted:not_started:no time left"
                elif x.kind == "resolve" or addr is None:
                    o.addr, o.stage_failed, o.error = None, "resolve", "gaierror:-3"
                elif x.kind in ("refused", "ctimeout", "noroute"):
                    o.stage_failed, o.error = "connect", {"refused": "ECONNREFUSED", "ctimeout": "timeout",
                                                           "noroute": "ENETUNREACH"}[x.kind]
                    sp = 33000 + len(frames)
                    if x.kind == "refused":
                        frames += [tcp_frame(RUNNER_ADDR, addr, sp, port, 0x02), tcp_frame(addr, RUNNER_ADDR, port, sp, 0x14)]
                    elif x.kind == "ctimeout":
                        frames += [tcp_frame(RUNNER_ADDR, addr, sp, port, 0x02)] * 3
                else:
                    o.local_port = c["lport"]
                    if not c["open"]:
                        c["frames"] += [tcp_frame(RUNNER_ADDR, addr, c["lport"], port, 0x02),
                                        tcp_frame(addr, RUNNER_ADDR, port, c["lport"], 0x12),
                                        tcp_frame(RUNNER_ADDR, addr, c["lport"], port, 0x10)]
                        c["open"] = True
                    o.t_send_wall = self.tick()
                    c["frames"].append(tcp_frame(RUNNER_ADDR, addr, c["lport"], port, 0x18))
                    seq += 1
                    if x.kind in ("rtimeout",):
                        o.stage_failed, o.error, o.end = "read", "timeout", "timeout"
                    elif x.kind == "reset":
                        o.stage_failed, o.error, o.end = "read", "ECONNRESET", "reset"
                        c["frames"].append(tcp_frame(addr, RUNNER_ADDR, port, c["lport"], 0x14))
                    else:
                        o.data = payload(x.cmd, c["next"], DEV[dev], x.kind, seq)
                        o.end = "newline"
                        o.t_recv_wall = self.tick()
                        o.latency_ms = o.response_ms = 650.0 if x.kind == "slow" else 2.0
                        c["frames"].append(tcp_frame(addr, RUNNER_ADDR, port, c["lport"], 0x18))
                    c["next"] += 1
                o.duration_ms = 3.0
                recorded.append((o, Classification(cat, "fixture", detail)))
            for c in conns.values():
                if c["open"]:
                    c["frames"] += [tcp_frame(RUNNER_ADDR, addr, c["lport"], port, 0x11),
                                    tcp_frame(addr, RUNNER_ADDR, port, c["lport"], 0x11)]
                frames += c["frames"]
            cats = [c.category for _, c in recorded]
            cut = any(x.kind == "notstarted" for x in xs)
            if cut:
                cat = None
            elif inst.decisive is not None:
                cat = cats[inst.decisive]
            else:
                cat = next((c for c in cats if c not in ("PASS", "PASS_SLOW")), "PASS_SLOW" if "PASS_SLOW" in cats
                           else "PASS")
            # runner/cases.read_series sets reads_complete only when the series ran to its end
            full = {"C-READ-CLOCK": 10, "C-READ-SERIES": 12, "FT-F11-CLOSE-FIN": 10, "FT-F11-CLOSE-RST": 10,
                    "FT-F13-SKEW": 3, "FT-F13-REPEAT-SEQ": 3}.get(inst.case_id)
            preds = (inst.predicates[no - 1] if inst.predicates else
                     predicates_for(inst.case_id, xs, complete=full is None or len(xs) == full))
            if inst.outcomes:
                outcome = inst.outcomes[no - 1]
            else:
                outcome = "runner" if cat is None else ("ok" if cat == expected and all(preds.values()) else "device")
            attempts.append((no, cat, outcome, preds, recorded))
        runner_case = bool(inst.attempts)
        if runner_case:
            observed, first = attempts[-1][1], attempts[0][1]
        elif inst.case_id == "C-ENVIRONMENT":
            observed = first = None
        else:
            observed = first = expected if inst.observed == "auto" else inst.observed
        cols = dict(run_id=run, case_id=inst.case_id, device_id=dev, fault_id=spec.fault_id, expected=expected,
                    observed=observed, first_attempt=first, attempts=len(attempts),
                    latency_ms=2.0 if runner_case else None, detection_ms=5.0 if spec.fault_id else None,
                    verdict=inst.verdict, attribution=inst.attribution, detail=inst.detail, preflight="green",
                    evidence_path=f"run-{run}/{rel}", observed_at=db.utcnow(), duration_ms=10.0)
        postflight = inst.overrides.pop("postflight", "green")
        cols.update(inst.overrides)
        has_col = any(c[1] == "predicates" for c in self.conn.execute("PRAGMA table_info(results)"))
        if HAS_DECISION and has_col and inst.verdict in ("pass", "fail"):
            # what the live Case records: the final attempt's predicates plus the case's own (extra/gateway) ones
            final = attempts[-1][3] if attempts else {}
            cols["predicates"] = {**final, **(inst.case_predicates if inst.case_predicates is not None
                                              else dict.fromkeys(case_predicates(inst.case_id), inst.verdict == "pass"))}
        rid = db.insert_result(self.conn, **cols)
        self.checks(run, "precheck", rid)
        for no, cat, outcome, preds, recorded in attempts:
            deciding = next((c for _, c in recorded if c.category not in ("PASS", "PASS_SLOW")), recorded[-1][1])
            db.insert_attempt(self.conn, rid, no, cat, deciding.stage, deciding.detail, db.wall_to_iso(self.tick()),
                              5.0, recorded, outcome=outcome, predicates=preds)
        # captures: the gateway polls every inventoried device during every case (noise on the same address:port)
        polls = []
        # the gateway polls every device during every case; with the device route deleted (F5) none reaches the wire
        for d in ([] if spec.fault_id == "F5" and spec.case_id.startswith("FT-") else DEVICES):
            self.lport += 1
            a, p = DEV[d]["address"], DEV[d]["port"]
            polls += [tcp_frame(RUNNER_ADDR, a, self.lport, p, 0x02), tcp_frame(a, RUNNER_ADDR, p, self.lport, 0x12),
                      tcp_frame(RUNNER_ADDR, a, self.lport, p, 0x18), tcp_frame(a, RUNNER_ADDR, p, self.lport, 0x18),
                      tcp_frame(RUNNER_ADDR, a, self.lport, p, 0x11)]
        all_frames = frames + polls
        caps = ["ctl"] + (["field"] if spec.kind == "fault" else [])
        for cap in caps:
            name = "capture.pcap" if cap == "ctl" else "capture-field.pcap"
            self.save(run, f"{rel}/{name}", pcap(all_frames, 1_760_000_000 if cap == "ctl" else 1_760_000_500),
                      "pcap" if cap == "ctl" else "pcap-field", rid)
            self.save(run, f"{rel}/{name[:-5]}.txt", f"{len(all_frames)} packets\n",
                      "pcap-text" if cap == "ctl" else "pcap-field-text", rid)
        # capture_flows: one record per dialled flow (runner/lab.dialled_flows semantics) per capture
        if runner_case and db.SCHEMA_VERSION >= 4:
            flows: dict[tuple, bool] = {}
            why_of: dict[tuple, str] = {}
            for _, _, _, _, recorded in attempts:
                for o, _ in recorded:
                    key = (o.addr, o.port, o.local_port)
                    on_wire = o.addr is not None and o.error not in ("not_started", "ENETUNREACH")
                    flows[key] = flows.get(key, False) or on_wire
                    why_of[key] = ("dialled flow must be on the wire" if on_wire else
                                   f"no address ({o.stage_failed} {o.error}): nothing can be sent" if o.addr is None
                                   else "ENETUNREACH: connect failed locally, nothing is sent"
                                   if o.error == "ENETUNREACH" else "not started: case deadline")
            for (a, p, lp), on_wire in flows.items():
                bpf = (f"(none: port {p}, no address)" if a is None else
                       f"tcp and host {a} and port {p}" + (f" and port {lp}" if lp else ""))
                n = None if a is None else sum(1 for f in all_frames if matches(f, a, p, lp))
                why = why_of[(a, p, lp)]
                for cap in caps:
                    db.add_capture_flow(self.conn, rid, capture=cap, bpf=bpf, expected=on_wire, packets=n,
                                        detail=why)
        apps = 2 if spec.fault_id == "F12" else (1 if spec.fault_id else 0)
        for k in range(1, apps + 1):
            tag = spec.fault_id if k == 1 else f"{spec.fault_id}.{k}"
            self.save(run, f"{rel}/fault-apply-{tag}.json", '{"verified": true}', "fault-apply", rid)
            self.save(run, f"{rel}/snapshot-during-{tag}.txt", "snapshot\n", "snapshot", rid)
            self.save(run, f"{rel}/snapshot-ctl-during-{tag}.txt", "snapshot\n", "snapshot", rid)
            self.save(run, f"{rel}/fault-revert-{tag}.json", '{"verified": true}', "fault-revert", rid)
            db.add_fault_event(self.conn, run_id=run, result_id=rid, fault_id=spec.fault_id,
                               vm=CTL if spec.fault_id in ("F5", "F7", "F7-missing", "F3", "F4") else FIELD,
                               applied_at=db.utcnow(), removed_at=db.utcnow(), removal_verified=True, detail="fixture")
        fault = catalog.FAULTS_BY_ID.get(spec.fault_id)
        for kind in (FAULT_KIND_FILES.get(fault.kind, ()) if fault else ()):
            self.save(run, f"{rel}/{kind}-{spec.fault_id}.txt", f"{kind}\n", kind, rid)
        for k in range(GATEWAY_FILES.get(inst.case_id, 0)):
            self.save(run, f"{rel}/gateway-{k}.json", '{"state": "healthy"}', "gateway", rid)
        for k in range(SAMPLES_FILES.get(inst.case_id, 0)):
            self.save(run, f"{rel}/gateway-samples-{k}.jsonl", '{"t": 0}\n', "gateway-samples", rid)
        recorded_m = inst.measurements if inst.measurements is not None else (
            {n: ((30.0, 2.0) if (inst.case_id, n) in OUTSIDE_BOUND_ON_PASS else (12.5, 6000.0))
             for n in MEASUREMENTS.get(inst.case_id, ())} if inst.verdict == "pass" else {})
        for name, (value, bound) in recorded_m.items():
            db.add_measurement(self.conn, rid, name, value, bound=bound, detail="fixture")
        self.save(run, f"{rel}/journal-witness-gateway.txt", "journal\n", "journal", rid)
        if dev:
            self.save(run, f"{rel}/journal-witness-device@{DEV[dev]['instance']}.txt", "journal\n", "journal", rid)
        self.save(run, f"{rel}/field-commands.jsonl", "\n", "command-log", rid)
        self.save(run, f"{rel}/timing.json", '{"clock": "fixture"}', "timing", rid)
        self.checks(run, "postflight", rid)
        if postflight is not None:
            db.set_postflight(self.conn, rid, postflight == "green")
        return rid


KIND_OF = {"PASS": "ok", "PASS_SLOW": "slow", "CONN_REFUSED": "refused", "CONNECT_TIMEOUT": "ctimeout",
           "NO_ROUTE": "noroute", "RESOLVE_FAIL": "resolve", "READ_TIMEOUT": "rtimeout", "CONN_RESET": "reset",
           "MALFORMED": "malformed", "WRONG_IDENTITY": "wrongid", "STALE_DATA": "stale", None: "notstarted"}


def observed_inst(case_id: str, dev: str | None, observed: str | None, first: str | None, attempts: int,
                  verdict: str, attribution: str) -> Inst:
    """An instance whose attempts observed `first` then `observed` (as the live case records them): the passing
    exchanges, with the observing exchange changed to that category (a READ series stops there)."""
    base = passing(case_id, dev)
    if not base.attempts:
        return Inst(case_id, dev, verdict=verdict, attribution=attribution, observed=observed)
    good = base.attempts[0]
    good_cat = next((CATEGORY[x.kind] for x in good if CATEGORY[x.kind] not in ("PASS", "PASS_SLOW")),
                    "PASS_SLOW" if any(x.kind == "slow" for x in good) else "PASS")

    def attempt(cat):
        if cat == good_cat or case_id == "FT-F12-RESTART":
            return list(good)
        i = 1 if len(good) > 1 else 0
        return list(good[:i]) + [X(good[i].cmd, KIND_OF[cat])]
    cats = ([first] if attempts == 2 else []) + [observed]
    return Inst(case_id, dev, [attempt(c) for c in cats], verdict=verdict, attribution=attribution,
                decisive=base.decisive)


def commissioning_set(fail: dict | None = None) -> list[Inst]:
    out = []
    for case_id, per_dev in catalog.COMMISSIONING_REQUIRED:
        for dev in (DEVICES if per_dev else [None]):
            out.append((fail or {}).get((case_id, dev)) or passing(case_id, dev))
    return out


def fault_set(only=None, replace: dict | None = None) -> list[Inst]:
    return [(replace or {}).get(c.case_id) or passing(c.case_id, FAULT_DEVICE)
            for c in catalog.CASES if c.kind == "fault" and (only is None or c.case_id in only)]


def mutant_insts(mutant_id: str) -> tuple[list[Inst], bool]:
    """Each mutant caught on dev-a as runner/catalog.py predicts it (simplified to its first catching case);
    dev-b, the stock control, passes. M6: a FLAKE (attempt 1 READ_TIMEOUT at the 7th request, retry passes)."""
    a = catalog.MUTANT_DEVICE
    fails, withheld = {}, False
    if mutant_id == "M1":
        fails[("C-IDENTIFY", a)] = Inst("C-IDENTIFY", a, [[X("IDENTIFY", "wrongid")], [X("IDENTIFY", "wrongid")]],
                                        verdict="fail", attribution="device")
        fails[("C-GATEWAY", a)] = Inst("C-GATEWAY", a, verdict="fail", attribution="device", observed="WRONG_IDENTITY")
    elif mutant_id == "M6":
        fails[("C-READ-SERIES", a)] = Inst("C-READ-SERIES", a, [
            [X("HEALTH")] + [X("READ")] * 5 + [X("READ", "rtimeout")],
            [X("HEALTH")] + [X("READ")] * 10 + [X("HEALTH")]], verdict="fail", attribution="device",
            detail="FLAKE: attempt 1 READ_TIMEOUT, passed only on retry")
    else:
        fails[("C-IDENTIFY", a)] = Inst("C-IDENTIFY", a, [[X("IDENTIFY", "malformed")], [X("IDENTIFY", "malformed")]],
                                        verdict="fail", attribution="device")
        if mutant_id == "M3":            # the device withheld its firmware version: C-ENVIRONMENT fail/device
            withheld = True
            fails[("C-ENVIRONMENT", None)] = Inst("C-ENVIRONMENT", None, verdict="fail", attribution="device",
                                                  case_predicates={**dict.fromkeys(case_predicates("C-ENVIRONMENT"),
                                                                                   True), f"fw_version.{a}": False})
    return commissioning_set(fails), withheld


def degraded_health(dev: str) -> Inst:
    """A genuine device failure: HEALTH answers PASS-framed but status degraded, on both attempts (fail/device)."""
    return Inst("C-HEALTH", dev, [[X("HEALTH", "degraded")], [X("HEALTH", "degraded")]], verdict="fail",
                attribution="device")


def deadline_cut(case_id: str) -> Inst:
    """The case deadline left no time to start the probe: nothing sent, unclassifiable, error/runner."""
    return Inst(case_id, FAULT_DEVICE, [[X("IDENTIFY", "notstarted")]], verdict="error", attribution="runner",
                detail="case deadline 30s exhausted")


@dataclass
class Ref:
    db: Path
    root: Path
    runs: dict[str, int]
    variant: str
    expected_failures: frozenset    # assertions this valid variant legitimately violates (empty = acceptable)


VARIANTS = {
    "reference": "complete valid store: 5 fresh baselines, superseded F0 + current fault run, 6 caught mutants, B",
    "deadline-cut": "current FT-F2 never started (case deadline): error/runner, nothing on the wire",
    "partial-latest": "a newer fault run that declared and executed only FT-F12",
    "superseded-failure": "an older fair baseline with a genuine C-HEALTH failure, superseded by B",
    "current-failure": "B's C-HEALTH/dev-a genuinely fails (degraded, both attempts): A4 and A18 must reject",
    "legacy": "T1-T5 and F0 recorded before the run-plan migration (schema v4), the rest after",
    "gateway-failure": "B's C-GATEWAY/dev-b fails on a recorded bound (last seen 5000 ms > 4000 ms): A4 and A18 reject",
    "gateway-api-failure": "B's C-GATEWAY/dev-b fails on a non-timing predicate only (unknown device not answered "
                           "404), every bound met: A4 and A18 reject",
    "aborted-detected": "after B, a baseline killed mid-run (no teardown) holding a genuine failure, found unfinished "
                        "by the next session, whose complete baseline then stands: acceptable",
}


def gateway_failure(dev: str) -> Inst:
    """The gateway saw the device (observed PASS) but a REQ-09 bound failed: the failure is in a case predicate and
    a measurement, not in any runner attempt (tests/live test_gateway_reports_device_healthy)."""
    m = {n: (12.5, 6000.0) for n in MEASUREMENTS["C-GATEWAY"]}
    m["gateway_last_seen_age_ms"] = (5000.0, 4000.0)
    return Inst("C-GATEWAY", dev, verdict="fail", attribution="device", observed="PASS", measurements=m,
                case_predicates={**dict.fromkeys(case_predicates("C-GATEWAY"), True), "last_seen_within_2P": False})


def gateway_api_failure(dev: str) -> Inst:
    """The gateway saw the device healthy within every bound, but its API answered an unknown device with something
    other than 404: the failure is recorded only in that case predicate (no measurement can show it)."""
    return Inst("C-GATEWAY", dev, verdict="fail", attribution="device", observed="PASS",
                measurements={n: (12.5, 6000.0) for n in MEASUREMENTS["C-GATEWAY"]},
                case_predicates={**dict.fromkeys(case_predicates("C-GATEWAY"), True), "api_unknown_device_404": False})


def build(dirpath: Path, variant: str = "reference") -> Ref:
    dirpath.mkdir(parents=True, exist_ok=True)
    b = Builder(dirpath / "witness.db", dirpath / "evidence", legacy_runs=6 if variant == "legacy" else 0)
    expected: set[str] = set()
    if variant == "superseded-failure":
        b.run("S", "baseline", commissioning_set({("C-HEALTH", "dev-a"): degraded_health("dev-a")}))
    for i in range(1, 6):
        b.run(f"T{i}", "baseline", commissioning_set(), provenance=f"r{i}")
    b.run("F0", "fault", fault_set())
    if variant == "deadline-cut":
        b.run("F", "fault", fault_set(replace={"FT-F2-HUNG": deadline_cut("FT-F2-HUNG")}))
        expected.add("A4")
    else:
        b.run("F", "fault", fault_set())
    for m in catalog.MUTANTS:
        insts, withheld = mutant_insts(m.mutant_id)
        b.run(m.mutant_id, "mutant", insts, mutant=m.mutant_id, withheld=withheld)
    if variant == "partial-latest":
        b.run("F12only", "fault", fault_set(only={"FT-F12-RESTART"}))
    if variant == "current-failure":
        b.run("B", "baseline", commissioning_set({("C-HEALTH", "dev-a"): degraded_health("dev-a")}))
        expected |= {"A4", "A18"}
    elif variant == "gateway-failure":
        b.run("B", "baseline", commissioning_set({("C-GATEWAY", "dev-b"): gateway_failure("dev-b")}))
        expected |= {"A4", "A18"}
    elif variant == "gateway-api-failure":
        b.run("B", "baseline", commissioning_set({("C-GATEWAY", "dev-b"): gateway_api_failure("dev-b")}))
        expected |= {"A4", "A18"}
    else:
        b.run("B", "baseline", commissioning_set())
    if variant == "aborted-detected":             # the next session marks the killed run (tests/live/conftest.py lab)
        b.run("K", "baseline", commissioning_set({("C-HEALTH", "dev-a"): degraded_health("dev-a")}), finished=False)
        b.run("N", "baseline", commissioning_set())
        db.mark_aborted_runs(b.conn, b.runs["N"])
    b.conn.commit()
    b.conn.close()
    return Ref(dirpath / "witness.db", dirpath / "evidence", b.runs, variant, frozenset(expected))
