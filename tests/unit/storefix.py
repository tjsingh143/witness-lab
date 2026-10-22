"""Synthetic results stores for the commissioning and acceptance unit tests. Fixture data with known answers
(the shape of real runs, built from the catalog and inventory); never evidence of a lab result. Runs and results are
written by the acceptance-contract harness's writer (tests/contract/refstore.py), so every fixture result carries the
complete evidence chain the contract requires (docs/acceptance-contract.md) and a test's injected defect is the only
defect."""
import hashlib
import struct
from pathlib import Path

from runner import catalog, db, lab as L
from runner.classify import Classification, Observation
from scripts.lib import inventory
from tests.contract import refstore as R

REPO = Path(__file__).resolve().parents[2]
INV = inventory.load(REPO / "inventory.yaml")
DEVICES = [d["device_id"] for d in INV["devices"]]
CTL, FIELD = "witness-ctl", "witness-field"
SHA = "0123456789abcdef0123456789abcdef01234567"
QDISC = "qdisc fq_codel 0: root refcnt 2 limit 10240p flows 1024 quantum 1514 target 5ms interval 100ms"
NFT = "table inet witness_isolation {\n\tchain output {\n\t\ttype filter hook output priority filter; policy drop;\n\t}\n}\n"


def new_store(path, guarded: bool = False):
    """A fixture store. These tests tamper with recorded evidence on purpose, as an adversary would: the schema-v5
    append-only guards are dropped unless `guarded`."""
    c = db.connect(path)
    db.sync_reference(c, requirements=db.requirements_from_md(REPO / "docs/requirements.md"), devices=INV["devices"],
                      cases=catalog.CASES, faults=catalog.FAULTS, mutants=catalog.MUTANTS)
    if not guarded:
        for (name,) in c.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'").fetchall():
            c.execute(f'DROP TRIGGER "{name}"')
    return c


def env_ok(provenance: str | None = None, mutant: str | None = None, *, kind: str | None = None) -> dict:
    """Every REQ-10 key for both VMs and every device, with valid values in the representation the live session
    records (runner/lab.local_env, scripts/faultctl.py env), + device builds and optional provenance."""
    env = {"python": "3.12.3", "git_sha": SHA, "git_dirty": "0", "runs.clean_env": "1",
           "runs.kind": kind or ("mutant" if mutant else "baseline"), "mutant": mutant or "none",
           "chrony.offset": "offset_s=+0.000021 delay_s=0.000324 samples=4/4 server=10.77.1.10"}
    for vm in (CTL, FIELD):
        env.update({f"kernel.{vm}": "6.8.0-134-generic", f"distro.{vm}": "Ubuntu 24.04.4 LTS",
                    f"qdisc.{vm}": f"lab0: {QDISC}" + ("\nfield0: qdisc noqueue 0: root refcnt 2" if vm == FIELD else ""),
                    f"nft.{vm}": NFT})
        if provenance:
            env[f"provenance.{vm}"] = f"golden-restore id={provenance} boot_id={provenance}-{vm}"
    for d in INV["devices"]:
        env[f"fw_version.{d['device_id']}"] = d["fw_version"]
        env[f"device_build.{d['device_id']}"] = "stock"
    if mutant:
        env[f"device_build.{catalog.MUTANT_DEVICE}"] = "mutant:" + catalog.mutant_spec(mutant, INV["devices"])
    return env


def _builder(conn) -> R.Builder:
    """The contract-complete writer of tests/contract/refstore.py over this fixture store; evidence files go to
    <db dir>/evidence (the runner.analysis default)."""
    return R.Builder(conn=conn, root=Path(conn.execute("PRAGMA database_list").fetchone()[2]).parent / "evidence")


def result(conn, run, case, dev, *, verdict="pass", attribution="none", observed="PASS", expected="PASS",
           fault=None, attempts=1, first="same", preflight="green", postflight="green", detection=None,
           bare: bool = False) -> int:
    """One result recorded as the live case fixture records it (attempts and exchanges observing `first` then
    `observed`, captures, checks, evidence files), with the given result columns as the test states them. `bare`:
    the result row only, for a test that records its own attempts (or a malformed instance, which has no target)."""
    first = observed if first == "same" else first
    if bare or catalog.CASES_BY_ID[case].per_device != (dev is not None):
        rid = db.insert_result(conn, run_id=run, case_id=case, device_id=dev, fault_id=fault, expected=expected,
                               observed=observed, first_attempt=first, attempts=attempts, latency_ms=1.0,
                               detection_ms=detection, verdict=verdict, attribution=attribution, detail="fixture",
                               preflight=preflight, evidence_path=f"run-{run}/{case}__{dev or 'run'}",
                               observed_at=db.utcnow(), duration_ms=1.0)
        if postflight is not None:
            db.set_postflight(conn, rid, postflight == "green")
        return rid
    inst = R.observed_inst(case, dev, observed, first, attempts, verdict, attribution)
    inst.overrides = dict(expected=expected, observed=observed, first_attempt=first, attempts=attempts if inst.attempts
                          else 0, fault_id=fault, preflight=preflight, detection_ms=detection, postflight=postflight,
                          detail="fixture")
    return _builder(conn).instance(run, inst)


def baseline(conn, *, skip=(), provenance=None, finished=True, clean=1, env=None, kind="baseline",
             mutant=None) -> int:
    """One passing, contract-complete result for every REQUIRED commissioning instance (catalog) except the
    (case, device|None) pairs in `skip`, which the run does not select (its plan omits them); full REQ-10 environment
    unless `env` is given."""
    insts = [i for i in R.commissioning_set() if (i.case_id, i.device_id) not in skip]
    snapshot = dict(env_ok(provenance, mutant, kind=kind) if env is None else env)
    # The live session adds this key only to SQLite, via set_clean_env, after collecting its snapshot.
    snapshot.pop("runs.clean_env", None)
    return _builder(conn).run(f"baseline {provenance or ''}", kind, insts, mutant=mutant, provenance=provenance,
                              finished=finished, clean=bool(clean), env=snapshot)


def finish(conn, run: int) -> None:
    """Finish a run left unfinished by baseline(finished=False) the way the live session does (session postflight,
    its files, finish_run)."""
    _builder(conn).finish(run)


def fault_run(conn) -> int:
    """Every fault case once on dev-a, observed exactly as predicted (verdict pass), each fault application recorded
    with a verified removal (FT-F12 restarts twice)."""
    return _builder(conn).run("fault", "fault", R.fault_set(), env=env_ok(kind="fault"))


def mutant_runs(conn) -> list[int]:
    """One valid run per brief mutant, each catching it on dev-a (fail/device), dev-b stock passing."""
    out = []
    for m in catalog.MUTANTS:
        insts = [R.Inst("C-IDENTIFY", "dev-a", [[R.X("IDENTIFY", "malformed")]], verdict="fail", attribution="device"),
                 R.passing("C-IDENTIFY", "dev-b")]
        out.append(_builder(conn).run(m.mutant_id, "mutant", insts, mutant=m.mutant_id,
                                      env=env_ok(mutant=m.mutant_id)))
    return out


def accepted_store(conn) -> dict:
    """A store on which every acceptance assertion holds: five fresh-clone complete baselines, a full fault run,
    all six mutants caught, and a final complete baseline on the long-lived VMs; every result contract-complete."""
    fresh = [baseline(conn, provenance=f"r{i}") for i in range(1, 6)]
    return {"fresh": fresh, "fault": fault_run(conn), "mutants": mutant_runs(conn), "final": baseline(conn)}


# ---------------------------------------------------------------- dialled exchanges, captures, capture_flows

RUNNER_ADDR = "10.77.1.10"


def tcp_packet(src: str, dst: str, sport: int, dport: int, flags: int = 0x02, *, ethertype: bytes = b"\x08\x00",
               proto: int = 6, frag: int = 0) -> bytes:
    """One Ethernet/IPv4/TCP frame (checksums zero: nothing here validates them, neither does tcpdump -r)."""
    tcp = struct.pack(">HHIIBBHHH", sport, dport, 1, 0, 5 << 4, flags, 64240, 0, 0)
    ip = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp), 1, frag, 64, proto, 0,
                     bytes(int(x) for x in src.split(".")), bytes(int(x) for x in dst.split(".")))
    return b"\x52\x55\x55\x77\x01\x20" + b"\x52\x55\x55\x77\x01\x10" + ethertype + ip + tcp


def pcap_bytes(frames: list[bytes], *, link: int = 1, endian: str = "<") -> bytes:
    out = struct.pack(endian + "IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 512, link)
    for i, f in enumerate(frames):
        out += struct.pack(endian + "IIII", 1_760_000_000 + i, 0, len(f), len(f)) + f
    return out


def flow_frames(addr: str, port: int, lport: int, *, refused: bool = False) -> list[bytes]:
    """The packets of one dialled connection: SYN/RST for a refused connect, else a short established exchange."""
    if refused:
        return [tcp_packet(RUNNER_ADDR, addr, lport, port, 0x02), tcp_packet(addr, RUNNER_ADDR, port, lport, 0x14)]
    return [tcp_packet(RUNNER_ADDR, addr, lport, port, 0x02), tcp_packet(addr, RUNNER_ADDR, port, lport, 0x12),
            tcp_packet(RUNNER_ADDR, addr, lport, port, 0x18), tcp_packet(addr, RUNNER_ADDR, port, lport, 0x18),
            tcp_packet(RUNNER_ADDR, addr, lport, port, 0x11)]


def wire(conn, root: Path, rid: int, *, addr: str | None, port: int, lport: int | None = None, category: str = "PASS",
         stage: str | None = None, err: str | None = None, detail: str = "", sent: bool = True, extra=()) -> dict:
    """Replace the result's recorded observation with one dialled exchange, as the live case fixture records it
    (tests/live/conftest.py): the attempt and exchange, a ctl capture (+ field capture for fault cases) indexed as
    evidence, and the capture_flows rows with the packets counted from those files. `sent`=False writes captures holding none of the flow (local failure);
    `extra` frames (e.g. gateway polls) are added to every capture. Returns {capture: pcap path}."""
    run, case_id, dev = conn.execute("SELECT run_id, case_id, device_id FROM results WHERE result_id=?",
                                     (rid,)).fetchone()
    conn.execute("DELETE FROM exchanges WHERE attempt_id IN (SELECT attempt_id FROM attempts WHERE result_id=?)", (rid,))
    for t, extra_where in (("attempts", ""), ("capture_flows", ""), ("evidence", " AND kind IN ('pcap', 'pcap-field')")):
        conn.execute(f"DELETE FROM {t} WHERE result_id=?{extra_where}", (rid,))
    o = Observation(host=f"{dev}.lab", port=port, cmd="IDENTIFY", req_id=1, addr=addr, local_port=lport,
                    stage_failed=stage, error=err)
    db.insert_attempt(conn, rid, 1, category, stage, detail, db.utcnow(), 1.0,
                      [(o, Classification(category, stage or "identity", detail))], outcome="ok")
    caps = ["ctl"] + (["field"] if catalog.CASES_BY_ID[case_id].kind == "fault" else [])
    frames = (flow_frames(addr, port, lport or 40000, refused=lport is None) if sent and addr else []) + list(extra)
    paths = {}
    for cap in caps:
        p = root / f"run-{run}/{case_id}__{dev or 'run'}" / ("capture.pcap" if cap == "ctl" else "capture-field.pcap")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(pcap_bytes(frames))
        db.add_evidence(conn, run_id=run, result_id=rid, kind="pcap" if cap == "ctl" else "pcap-field", root=root,
                        path=p)
        paths[cap] = p
    for f in L.dialled_flows([(addr, port, lport, stage, err)]):
        bpf = L.flow_record_filter(f)
        for cap in caps:
            n = None if addr is None else sum(1 for fr in frames if _matches(fr, addr, port, lport))
            db.add_capture_flow(conn, rid, capture=cap, bpf=bpf, expected=f["expected"], packets=n, detail=f["why"])
    return paths


def _matches(frame: bytes, addr: str, port: int, lport: int | None) -> bool:
    a = bytes(int(x) for x in addr.split("."))
    sport, dport = struct.unpack(">HH", frame[34:38])
    return a in (frame[26:30], frame[30:34]) and port in (sport, dport) and (lport is None or lport in (sport, dport))


def reindex(conn, root: Path, path: Path) -> None:
    """Make the evidence index agree with a file's current bytes (an adversary who also rewrites the index)."""
    data = path.read_bytes()
    conn.execute("UPDATE evidence SET sha256=?, bytes=? WHERE path=?",
                 (hashlib.sha256(data).hexdigest(), len(data), str(path.relative_to(root))))
