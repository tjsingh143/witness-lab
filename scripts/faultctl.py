#!/usr/bin/env python3
"""witness-faultctl: the ONLY privileged entry point the runner (witness-ctl) has on witness-field.

Installed by provision_field.sh as /usr/local/sbin/witness-faultctl (root, 0755). The
runner reaches it as user witness-fault over SSH on lab0; authorized_keys forces
/usr/local/sbin/witness-fault-ssh, which runs `sudo -n witness-faultctl <words>`.
Every argument is validated here against an allow-list; there is no shell.

Safety rules (AGENTS.md):
- every call first asserts this is the inventoried witness-field VM (lab0 MAC, hostname,
  Ubuntu 24.04 aarch64 VM); nothing runs anywhere else;
- one lab fault at a time: `apply` refuses while any fault is active (fail closed);
- every `apply` arms a transient systemd dead-man timer (witness-fault-deadman) that runs
  `reset` after DEADMAN_S if the runner never reverts; `revert` disarms it once clean;
- SIGSTOP/SIGCONT act only on the witness-device@<i> MainPID, re-verified by cgroup,
  cmdline and /proc start time; a mismatch fails closed;
- netem is scoped by a flower filter to device-source TCP 5020 on lab0 egress, so the
  SSH control channel and chrony are not delayed;
- nft faults (F8/F9) live only in tables named witness_fault_*, hooked on input, and match
  only `iifname lab0 ip daddr <one device> tcp dport <its port>`: SSH, chrony and the other
  device are untouched;
- the field-side capture is a transient unit with RuntimeMaxSec, so it cannot outlive a crash;
- a mutant build (brief 7.4) is a RUNTIME drop-in under /run/systemd/system (gone after a reboot),
  deployed only while no fault is active, one instance at a time; `mutant restore`, `reset` and
  reset_lab.sh remove it. It is not a lab fault (the device is the system under test), so it is
  not in active_faults(), but preflight reports it RED unless the runner declared it.
Every action is appended to /var/lib/witness/faultctl.log. Output is one JSON object.

Usage: witness-faultctl status|check|preflight|env|snapshot|counters
       witness-faultctl journal INST SINCE_EPOCH
       witness-faultctl apply service-stop INST | apply sigstop INST | apply mode INST MODE
       witness-faultctl apply netem DELAY_MS all|data | apply nft drop|reject|reject-data INST
       witness-faultctl apply restart INST
       witness-faultctl revert service-stop INST | revert sigstop INST PID STARTTIME
       witness-faultctl revert mode INST | revert netem | revert nft | revert restart INST
       witness-faultctl capture start NAME [PORT...] | capture stop NAME
                        (TCP on the inventory device ports + up to 4 extra PORTs, and ICMP)
       witness-faultctl reset [deadman|manual]
       witness-faultctl mutant deploy INST SPEC | mutant restore INST     (brief 7.4; device/mutants.py)
       witness-faultctl preflight allow-mutant      (runner, declared mutant run only)
MODE: malformed | truncated | wrong-id | repeat-seq | close-after:N | reset-after:N (N 1-9)
      | clock-skew:+Ns | clock-skew:-Ns (N 1-3600); same grammar as device.py MODE_RE.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import re
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(os.environ.get("WIT_REPO", "/opt/witness-lab"))
sys.path.insert(0, str(REPO / "scripts" / "lib"))
import inventory  # noqa: E402  (scripts/lib/inventory.py)
sys.path.insert(0, str(REPO / "device"))
from mutants import valid_mutant  # noqa: E402  (device/mutants.py: same grammar the device enforces)

LAB_IF = "lab0"
DEADMAN_UNIT = "witness-fault-deadman"
DEADMAN_S = 90
AUDIT = Path("/var/lib/witness/faultctl.log")
DEVICE_PY = Path("/usr/local/lib/witness/device.py")
# Root-owned control dir for device fault modes. Never write into /run/witness-device-<i>/:
# it belongs to the device's DynamicUser, which could plant a symlink there (confused deputy).
CTL_DIR = Path("/run/witness-fault")
MODES = ("malformed", "truncated", "wrong-id", "repeat-seq")
MODE_RE = re.compile(r"^(?:(close-after|reset-after):([1-9])|clock-skew:([+-])([1-9][0-9]{0,3})s)$")
FAULT_NFT_PREFIX = "witness_fault"
# F8/F9: nft verdicts on input, appended to the per-device match. reject-data matches only
# segments with PSH set and SYN/RST clear (the request), so the handshake completes first.
NFT_KINDS = {
    "drop": "counter drop",
    "reject": "counter reject with tcp reset",
    "reject-data": "tcp flags & (syn | rst | psh) == psh counter reject with tcp reset",
}
CAPTURE_UNIT = "witness-field-capture"
CAPTURE_DIR = Path("/var/lib/witness/captures")
CAPTURE_MAX_S = 120
CAPTURE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")
CAPTURE_MAX_EXTRA = 4
PORT_RE = re.compile(r"^[1-9][0-9]{0,4}$")
# A device-port connection idle this long was left behind by a fault. It must exceed the longest wait any
# LIVE lab client can have on an established device connection: the gateway's poll deadline (4.0 s,
# runner/classify.py ATTEMPT_DEADLINE_S; one exchange may use all of it) and the runner's 2.0 s read timeout.
# Phase 3 used 1500 ms ("clients live for milliseconds"); Phase 4 mutant M3 (no newline) showed a live gateway
# poll waiting 2.0 s for a frame end flagged as stale: precheck RED -> reset -> the mutant under test was
# removed mid-run (runs 77-79, all contaminated and excluded). lab-record section 14.
STALE_IDLE_MS = 5000


class Refused(Exception):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def sh(*cmd: str, timeout: float = 10, check: bool = True) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise Refused(f"{' '.join(cmd)} -> rc={p.returncode}: {(p.stderr or p.stdout).strip()[:300]}")
    return p.stdout


def audit(msg: str) -> None:
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT.open("a", encoding="utf-8") as f:
        f.write(f"{now_iso()} caller={os.environ.get('SUDO_USER', 'root')} {msg}\n")


# ---------------------------------------------------------------- identity / inventory

INV = None


def assert_field_vm() -> dict:
    global INV
    if platform.system() != "Linux" or platform.machine() != "aarch64":
        raise Refused("not a Linux aarch64 guest")
    if subprocess.run(["systemd-detect-virt", "--vm", "--quiet"]).returncode != 0:
        raise Refused("not a VM")
    osr = dict(line.split("=", 1) for line in Path("/etc/os-release").read_text().splitlines() if "=" in line)
    if osr.get("ID") != "ubuntu" or osr.get("VERSION_ID", "").strip('"') != "24.04":
        raise Refused("not Ubuntu 24.04")
    INV = inventory.load(REPO / "inventory.yaml")
    vm = next(v for v in INV["lab"]["vms"] if v["role"] == "field")
    mac = Path(f"/sys/class/net/{LAB_IF}/address").read_text().strip()
    if mac != vm["mac"]:
        raise Refused(f"{LAB_IF} MAC {mac} != inventory {vm['mac']}; wrong VM")
    if platform.node() not in (vm["name"], f"lima-{vm['name']}"):
        raise Refused(f"hostname {platform.node()} is not {vm['name']}")
    return vm


def instances() -> dict[str, dict]:
    return {d["instance"]: d for d in INV["devices"]}


def inst_arg(i: str) -> dict:
    if i not in instances():
        raise Refused(f"unknown instance {i!r}")
    return instances()[i]


def unit(i: str) -> str:
    return f"witness-device@{i}.service"


# ---------------------------------------------------------------- state probes

def main_pid(i: str) -> int:
    return int(sh("systemctl", "show", "-p", "MainPID", "--value", unit(i)).strip() or 0)


def proc_stat(pid: int) -> tuple[str, str]:
    """(state letter, start time in clock ticks) from /proc/<pid>/stat."""
    raw = Path(f"/proc/{pid}/stat").read_text()
    rest = raw[raw.rindex(")") + 2:].split()
    return rest[0], rest[19]


def verify_device_pid(i: str, pid: int) -> None:
    """Fail closed unless pid is witness-device@i's main process running device.py for i."""
    if pid <= 1:
        raise Refused(f"{unit(i)} has no main process")
    cg = Path(f"/proc/{pid}/cgroup").read_text()
    if f"/system.slice/system-witness\\x2ddevice.slice/{unit(i)}" not in cg:
        raise Refused(f"pid {pid} is not in {unit(i)}'s cgroup")
    cmd = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    if str(DEVICE_PY).encode() not in cmd or b"--instance" not in cmd or cmd[cmd.index(b"--instance") + 1] != i.encode():
        raise Refused(f"pid {pid} cmdline is not device.py --instance {i}")


def device_mode(i: str) -> str | None:
    try:
        return json.loads(Path(f"/run/witness-device-{i}/state.json").read_text())["mode"]
    except (OSError, ValueError, KeyError):
        return None


def device_build(i: str) -> str | None:
    """`stock` or `mutant:SPEC` as reported by the running device (None: no state yet)."""
    try:
        return json.loads(Path(f"/run/witness-device-{i}/state.json").read_text()).get("build", "stock")
    except (OSError, ValueError):
        return None


def mutant_dropin(i: str) -> Path:
    return Path(f"/run/systemd/system/witness-device@{i}.service.d/50-witness-mutant.conf")


def builds() -> dict[str, str | None]:
    return {i: device_build(i) for i in instances()}


def listening(addr: str, port: int) -> bool:
    out = sh("ss", "-Hltn", f"src {addr}:{port}", check=False)
    return bool(out.strip())


def qdiscs(ifc: str) -> str:
    return sh("tc", "qdisc", "show", "dev", ifc, check=False).strip()


def fault_tables() -> list[str]:
    out = sh("nft", "list", "tables", check=False)
    return [f"{p[1]} {p[2]}" for p in (l.split() for l in out.splitlines())
            if len(p) == 3 and p[2].startswith(FAULT_NFT_PREFIX)]


def half_open() -> list[str]:
    """Device-port connections stuck in SYN-RECV. After a delayed-SYN-ACK fault the runner
    has given up, but this kernel keeps retransmitting the SYN-ACK (1 s, 2 s, ... backoff)
    until ctl answers RST, which would land in the NEXT case (observed in run 3)."""
    ports = sorted({d["port"] for d in INV["devices"]})
    flt = " or ".join(f"sport = :{p}" for p in ports)
    return [" ".join(l.split()) for l in sh("ss", "-Htan", "state", "syn-recv", f"( {flt} )", check=False).splitlines() if l.strip()]


def valid_mode(mode: str) -> bool:
    m = MODE_RE.match(mode)
    return mode in MODES or (m is not None and (m.group(1) is not None or int(m.group(4)) <= 3600))


def device_conns() -> list[dict]:
    """Every ESTABLISHED device-port socket with its idle times (ms, from `ss -i`)."""
    ports = sorted({d["port"] for d in INV["devices"]})
    flt = " or ".join(f"sport = :{p}" for p in ports)
    out, cur = [], None
    for line in sh("ss", "-Htni", "state", "established", f"( {flt} )", check=False).splitlines():
        if not line.strip():
            continue
        if not line[0].isspace():
            parts = line.split()
            cur = {"local": parts[-2], "peer": parts[-1], "line": " ".join(parts), "lastrcv": 0, "lastsnd": 0}
            out.append(cur)
        elif cur is not None:
            for k in ("lastrcv", "lastsnd"):
                m = re.search(rf"\b{k}:(\d+)", line)
                cur[k] = int(m.group(1)) if m else 0       # ss omits the field when it is 0 ms
    return out


def _is_stale(c: dict, min_idle_ms: int) -> bool:
    return c["lastrcv"] >= min_idle_ms and c["lastsnd"] >= min_idle_ms


def stale_conns(min_idle_ms: int = STALE_IDLE_MS) -> list[dict]:
    """ESTABLISHED device-port sockets that have received and sent nothing for min_idle_ms.
    After `reject-data` the handshake completed but the request was rejected on the way in,
    so the device keeps a connection whose peer has already been reset; it would idle-close
    (FIN) only after 30 s and land in a later case's capture. A live gateway/runner connection
    is idle at most for its read deadline (<= 4 s), below the threshold."""
    return [c for c in device_conns() if _is_stale(c, min_idle_ms)]


def drain_stale(timeout_s: float = STALE_IDLE_MS / 1000 + 1.0) -> list[str]:
    """After an nft revert: wait (bounded) until every established device connection has either
    closed or become stale, then abort the stale ones. Observed in run 33: the rejected F9-data
    connection was only 0.7 s idle at revert time, so a one-shot sweep missed it and the
    postflight (correctly) failed on it 1 s later."""
    killed, end = [], time.monotonic() + timeout_s
    while True:
        conns = device_conns()
        stale = [c for c in conns if _is_stale(c, STALE_IDLE_MS)]
        killed += [kill_conn(c) for c in stale]
        if len(stale) == len(conns) or time.monotonic() >= end:
            return killed
        time.sleep(0.1)


def kill_conn(c: dict) -> str:
    """Abort one exact 4-tuple (ss -K sends RST and closes; needs CONFIG_INET_DIAG_DESTROY)."""
    la, lp = c["local"].rsplit(":", 1)
    pa, pp = c["peer"].rsplit(":", 1)
    if not (lp.isdigit() and pp.isdigit()):
        raise Refused(f"bad socket address {c}")
    sh("ss", "-K", "-tn", "state", "established", f"( src {la}:{lp} and dst {pa}:{pp} )", check=False)
    return f"{c['local']}->{c['peer']} idle rcv={c.get('lastrcv')}ms snd={c.get('lastsnd')}ms"


def capture_active() -> bool:
    return sh("systemctl", "is-active", f"{CAPTURE_UNIT}.service", check=False).strip() in ("active", "activating")


def deadman_armed() -> bool:
    return sh("systemctl", "is-active", f"{DEADMAN_UNIT}.timer", check=False).strip() == "active"


def active_faults() -> list[str]:
    out = []
    for i in instances():
        if sh("systemctl", "is-active", unit(i), check=False).strip() != "active":
            out.append(f"service-inactive:{i}")
            continue
        pid = main_pid(i)
        if pid and proc_stat(pid)[0] == "T":
            out.append(f"sigstop:{i}:{pid}")
        m = device_mode(i)
        if m != "normal":
            out.append(f"mode:{i}={m}")
    for ifc in (LAB_IF, INV["lab"]["device_interface"]):
        if re.search(r"\b(netem|tbf|prio)\b", qdiscs(ifc)):
            out.append(f"qdisc:{ifc}")
    out += [f"nft:{t}" for t in fault_tables()]
    return out


# ---------------------------------------------------------------- dead-man

def deadman_arm(reason: str) -> None:
    sh("systemctl", "stop", f"{DEADMAN_UNIT}.timer", check=False)
    sh("systemctl", "reset-failed", f"{DEADMAN_UNIT}.timer", f"{DEADMAN_UNIT}.service", check=False)
    sh("systemd-run", f"--unit={DEADMAN_UNIT}", f"--on-active={DEADMAN_S}", "--timer-property=AccuracySec=1s",
       f"--description=Witness fault dead-man ({reason})", "/usr/local/sbin/witness-faultctl", "reset", "deadman")
    if not deadman_armed():
        raise Refused("dead-man timer did not arm")


def deadman_disarm() -> None:
    sh("systemctl", "stop", f"{DEADMAN_UNIT}.timer", check=False)
    sh("systemctl", "reset-failed", f"{DEADMAN_UNIT}.timer", check=False)


def disarm_if_clean() -> list[str]:
    left = active_faults()
    if not left:
        deadman_disarm()
    return left


# ---------------------------------------------------------------- faults

def wait_for(pred, timeout: float, step: float = 0.05) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(step)
    return pred()


def require_clean() -> None:
    left = active_faults()
    if left:
        raise Refused(f"another fault is active ({', '.join(left)}); one fault at a time")


def apply_service_stop(i: str) -> dict:
    d = inst_arg(i)
    require_clean()
    deadman_arm(f"service-stop {i}")
    sh("systemctl", "stop", unit(i), timeout=15)
    ok = wait_for(lambda: not listening(d["address"], d["port"]), 3)
    return {"applied_at": now_iso(), "verified": ok and sh("systemctl", "is-active", unit(i), check=False).strip() != "active",
            "detail": f"{unit(i)} {sh('systemctl', 'is-active', unit(i), check=False).strip()}; "
                      f"listening={listening(d['address'], d['port'])}"}


def start_and_wait(i: str) -> bool:
    d = inst_arg(i)
    sh("systemctl", "start", unit(i), timeout=20)   # Type=notify: returns after the device bound
    return wait_for(lambda: listening(d["address"], d["port"]) and device_mode(i) == "normal", 5)


def revert_service_stop(i: str) -> dict:
    inst_arg(i)
    ok = start_and_wait(i)
    return {"removed_at": now_iso(), "verified": ok, "remaining": disarm_if_clean(),
            "detail": f"{unit(i)} pid {main_pid(i)} listening={ok}"}


def apply_sigstop(i: str) -> dict:
    inst_arg(i)
    require_clean()
    pid = main_pid(i)
    verify_device_pid(i, pid)
    state, start = proc_stat(pid)
    deadman_arm(f"sigstop {i} pid {pid}")
    os.kill(pid, 19)   # SIGSTOP
    ok = wait_for(lambda: proc_stat(pid)[0] == "T", 2)
    return {"applied_at": now_iso(), "verified": ok, "pid": pid, "starttime": start,
            "detail": f"pid {pid} state {state}->{proc_stat(pid)[0]}"}


def revert_sigstop(i: str, pid_s: str, start_s: str) -> dict:
    inst_arg(i)
    if not pid_s.isdigit() or not start_s.isdigit():
        raise Refused("pid and starttime must be integers")
    pid = int(pid_s)
    if main_pid(i) != pid:
        raise Refused(f"{unit(i)} MainPID is {main_pid(i)}, not {pid}; refusing to signal")
    verify_device_pid(i, pid)
    state, start = proc_stat(pid)
    if start != start_s:
        raise Refused(f"pid {pid} start time {start} != {start_s} (pid reused); refusing")
    os.kill(pid, 18)   # SIGCONT
    ok = wait_for(lambda: proc_stat(pid)[0] != "T", 2)
    return {"removed_at": now_iso(), "verified": ok, "remaining": disarm_if_clean(),
            "detail": f"pid {pid} state {state}->{proc_stat(pid)[0]}"}


def ctl_dir() -> Path:
    """Create/verify the root-owned 0755 control directory (refuse a symlink or foreign owner)."""
    try:
        CTL_DIR.mkdir(mode=0o755)
    except FileExistsError:
        pass
    st = os.lstat(CTL_DIR)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
        raise Refused(f"{CTL_DIR} is not a root-owned, non-writable-by-others directory")
    return CTL_DIR


def set_mode(i: str, mode: str) -> bool:
    if sh("systemctl", "is-active", unit(i), check=False).strip() != "active":
        raise Refused(f"{unit(i)} not running")
    d = ctl_dir()
    fd = os.open(d / f".device-{i}.mode.tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(mode + "\n")
    os.replace(d / f".device-{i}.mode.tmp", d / f"device-{i}.mode")
    sh("systemctl", "kill", "-s", "HUP", "--kill-whom=main", unit(i))
    return wait_for(lambda: device_mode(i) == mode, 3)


def apply_mode(i: str, mode: str) -> dict:
    inst_arg(i)
    if not valid_mode(mode):
        raise Refused(f"mode must be one of {MODES}, close-after:N, reset-after:N or clock-skew:+Ns")
    require_clean()
    deadman_arm(f"mode {i} {mode}")
    ok = set_mode(i, mode)
    return {"applied_at": now_iso(), "verified": ok, "detail": f"{unit(i)} mode={device_mode(i)}"}


def revert_mode(i: str) -> dict:
    inst_arg(i)
    ok = set_mode(i, "normal")
    return {"removed_at": now_iso(), "verified": ok, "remaining": disarm_if_clean(),
            "detail": f"{unit(i)} mode={device_mode(i)}"}


def apply_netem(delay_s: str, scope: str) -> dict:
    if not delay_s.isdigit() or not 1 <= int(delay_s) <= 10000:
        raise Refused("delay must be 1..10000 ms")
    if scope not in ("all", "data"):
        raise Refused("scope must be all|data")
    require_clean()
    subnet = INV["lab"]["device_subnet"]
    ports = sorted({str(d["port"]) for d in INV["devices"]})
    if len(ports) != 1:
        raise Refused("netem filter expects one device port")
    deadman_arm(f"netem {delay_s}ms {scope}")
    # Band 4 (class 1:4) receives ONLY the filtered device traffic; the priomap is the
    # kernel default over bands 1-3, so all other traffic (SSH, chrony) is unaffected.
    sh("tc", "qdisc", "add", "dev", LAB_IF, "root", "handle", "1:", "prio", "bands", "4",
       "priomap", *"1 2 2 2 1 2 0 0 1 1 1 1 1 1 1 1".split())
    try:
        sh("tc", "qdisc", "add", "dev", LAB_IF, "parent", "1:4", "handle", "40:", "netem", "delay", f"{delay_s}ms")
        flt = ["tc", "filter", "add", "dev", LAB_IF, "parent", "1:", "protocol", "ip", "prio", "1", "flower",
               "ip_proto", "tcp", "src_ip", subnet, "src_port", ports[0]]
        if scope == "data":
            flt += ["tcp_flags", "0x0/0x2"]   # SYN bit clear: the SYN-ACK is not delayed
        sh(*flt, "classid", "1:4")
    except Refused:
        sh("tc", "qdisc", "del", "dev", LAB_IF, "root", check=False)
        raise
    q, f = qdiscs(LAB_IF), sh("tc", "filter", "show", "dev", LAB_IF)
    return {"applied_at": now_iso(), "verified": "netem" in q and "flower" in f, "detail": f"{q} || {' '.join(f.split())}"}


def revert_netem() -> dict:
    if re.search(r"\b(netem|prio)\b", qdiscs(LAB_IF)):
        sh("tc", "qdisc", "del", "dev", LAB_IF, "root")
    removed = now_iso()
    q = qdiscs(LAB_IF)
    before = half_open()
    drained = wait_for(lambda: not half_open(), 8, 0.2)   # next SYN-ACK retransmit -> ctl RST
    return {"removed_at": removed, "verified": not re.search(r"\b(netem|tbf|prio)\b", q) and drained,
            "remaining": disarm_if_clean(),
            "detail": f"{q}; half-open after delete: {before or 'none'}; drained={drained} at {now_iso()}"}


def apply_restart(i: str) -> dict:
    """F12: one-shot `systemctl restart`. Nothing stays applied; the dead-man covers a restart
    that leaves the unit down. Field-side timings are returned for REQ-08 evidence."""
    d = inst_arg(i)
    require_clean()
    old = main_pid(i)
    verify_device_pid(i, old)
    deadman_arm(f"restart {i} pid {old}")
    issued = now_iso()
    t0 = time.monotonic()
    sh("systemctl", "restart", unit(i), timeout=20)   # Type=notify: returns after the new process bound
    restart_ms = (time.monotonic() - t0) * 1000
    returned = now_iso()
    listening_at_return = listening(d["address"], d["port"])
    new = main_pid(i)
    ok = wait_for(lambda: listening(d["address"], d["port"]) and device_mode(i) == "normal", 5)
    return {"applied_at": issued, "returned_at": returned, "restart_ms": round(restart_ms, 1),
            "old_pid": old, "new_pid": new, "listening_at_return": listening_at_return,
            "verified": ok and new not in (0, old), "remaining": disarm_if_clean(),
            "detail": f"{unit(i)} pid {old}->{new} in {restart_ms:.1f} ms; listening at return={listening_at_return}"}


def revert_restart(i: str) -> dict:
    d = inst_arg(i)
    ok = listening(d["address"], d["port"]) or start_and_wait(i)
    return {"removed_at": now_iso(), "verified": ok and device_mode(i) == "normal", "remaining": disarm_if_clean(),
            "detail": f"{unit(i)} pid {main_pid(i)} listening={ok}"}


def nft_table(kind: str) -> str:
    return f"{FAULT_NFT_PREFIX}_{kind.replace('-', '_')}"


def apply_nft(kind: str, i: str) -> dict:
    if kind not in NFT_KINDS:
        raise Refused(f"nft kind must be one of {sorted(NFT_KINDS)}")
    d = inst_arg(i)
    require_clean()
    tbl = nft_table(kind)
    rule = f'iifname "{LAB_IF}" ip daddr {d["address"]} tcp dport {int(d["port"])} {NFT_KINDS[kind]} comment "witness {kind} {i}"'
    text = (f"table inet {tbl} {{\n  chain input {{\n    type filter hook input priority filter - 10; policy accept;\n"
            f"    {rule}\n  }}\n}}\n")
    deadman_arm(f"nft {kind} {i}")
    p = subprocess.run(["nft", "-f", "-"], input=text, capture_output=True, text=True, timeout=10)
    if p.returncode != 0:
        raise Refused(f"nft -f rc={p.returncode}: {p.stderr.strip()[:300]}")
    listed = sh("nft", "list", "table", "inet", tbl, check=False)
    return {"applied_at": now_iso(), "verified": f"witness {kind} {i}" in listed and tbl in " ".join(fault_tables()),
            "table": tbl, "detail": " ".join(listed.split())}


def revert_nft() -> dict:
    removed = []
    for t in fault_tables():
        fam, name = t.split()
        listed = sh("nft", "list", "table", fam, name, check=False)
        sh("nft", "delete", "table", fam, name)
        removed.append(" ".join(listed.split()))       # keeps the final counters
    at = now_iso()
    killed = drain_stale()
    left = stale_conns()
    return {"removed_at": at, "verified": not fault_tables() and not left, "remaining": disarm_if_clean(),
            "detail": f"deleted: {removed or 'none'}; stale device connections aborted: {killed or 'none'}"
                      f"{'; STILL STALE: ' + str(left) if left else ''}"}


def capture_filter(extra_ports: list[str]) -> str:
    """TCP on the inventory's device ports plus at most CAPTURE_MAX_EXTRA validated extra ports (the case fault's
    dialled port, e.g. F3's 5021; independent audit F-07), and ICMP. Nothing else is ever captured."""
    if len(extra_ports) > CAPTURE_MAX_EXTRA or not all(PORT_RE.match(p) for p in extra_ports):
        raise Refused(f"capture ports: at most {CAPTURE_MAX_EXTRA} decimal ports")
    ports = {int(d["port"]) for d in INV["devices"]} | {int(p) for p in extra_ports}
    if not all(0 < p < 65536 for p in ports):
        raise Refused("capture ports must be 1-65535")
    return "(" + " or ".join(f"tcp port {p}" for p in sorted(ports)) + ") or icmp"


def capture_start(name: str, extra_ports: list[str] = ()) -> dict:
    if not CAPTURE_NAME_RE.match(name):
        raise Refused("capture name must match [A-Za-z0-9_.-]{1,96}")
    bpf = capture_filter(list(extra_ports))
    sh("systemctl", "stop", f"{CAPTURE_UNIT}.service", check=False)
    sh("systemctl", "reset-failed", f"{CAPTURE_UNIT}.service", check=False)
    CAPTURE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    for old in CAPTURE_DIR.glob("*.pcap"):
        old.unlink()
    path = CAPTURE_DIR / f"{name}.pcap"
    since = f"{time.time():.3f}"
    sh("systemd-run", "--quiet", "--collect", f"--unit={CAPTURE_UNIT}", f"--property=RuntimeMaxSec={CAPTURE_MAX_S}",
       "--description=Witness field-side lab0 capture (bounded)",
       "/usr/bin/tcpdump", "-i", LAB_IF, "-nn", "-U", "--immediate-mode", "-Z", "root", "-s", "512",
       "-c", "5000", "-w", str(path), bpf)
    ok = wait_for(lambda: path.exists() and path.stat().st_size >= 24, 3)
    return {"started": ok, "since": since, "path": str(path), "max_s": CAPTURE_MAX_S, "filter": bpf}


def capture_stop(name: str) -> dict:
    if not CAPTURE_NAME_RE.match(name):
        raise Refused("capture name must match [A-Za-z0-9_.-]{1,96}")
    sh("systemctl", "stop", f"{CAPTURE_UNIT}.service", check=False, timeout=10)
    path = CAPTURE_DIR / f"{name}.pcap"
    if not path.exists():
        return {"stopped": True, "found": False}
    data = path.read_bytes()
    txt = sh("tcpdump", "-nn", "-tttt", "-A", "-r", str(path), check=False, timeout=20)
    stats = sh("journalctl", "-u", f"{CAPTURE_UNIT}.service", "-n", "6", "-o", "cat", "--no-pager", check=False)
    path.unlink()
    return {"stopped": True, "found": True, "bytes": len(data),
            "pcap_b64": base64.b64encode(data[:1_000_000]).decode() if len(data) <= 1_000_000 else None,
            "text": txt[:300_000], "tcpdump": stats.strip()[-600:]}


def counters() -> dict:
    """/proc/net/snmp Ip/Icmp/Tcp and IpExt counters: read-only evidence for silent drops
    (Ip InAddrErrors), ICMP generation (Icmp OutDestUnreachs) and RSTs (Tcp OutRsts)."""
    out = {}
    for f in ("/proc/net/snmp", "/proc/net/netstat"):
        lines = Path(f).read_text().splitlines()
        for hdr, val in zip(lines[::2], lines[1::2]):
            k, *names = hdr.split()
            _, *vals = val.split()
            if k.rstrip(":") in ("Ip", "Icmp", "Tcp", "IpExt"):
                for n, v in zip(names, vals):
                    out[f"{k.rstrip(':')}.{n}"] = int(v)
    return {"counters": out, "at": now_iso()}


def reset(reason: str) -> dict:
    out = []
    for i in instances():
        try:
            pid = main_pid(i)
            if pid and proc_stat(pid)[0] == "T":
                verify_device_pid(i, pid)
                os.kill(pid, 18)
                out.append(f"SIGCONT {pid}")
            if device_mode(i) not in (None, "normal"):
                set_mode(i, "normal")
                out.append(f"mode {i} normal")
        except (Refused, OSError) as e:
            out.append(f"{i}: {e}")
    p = subprocess.run(["bash", str(REPO / "scripts/reset_lab.sh"), "--role", "field"],
                       capture_output=True, text=True, timeout=120)
    out.append(f"reset_lab rc={p.returncode}")    # also removes mutant drop-ins (stock build restored)
    if capture_active():
        sh("systemctl", "stop", f"{CAPTURE_UNIT}.service", check=False)
        out.append("stopped field capture")
    try:
        out += [f"aborted stale {kill_conn(c)}" for c in stale_conns()]
    except (Refused, OSError, subprocess.SubprocessError) as e:
        out.append(f"stale-connection sweep failed: {e}")
    if reason == "deadman":
        sh("systemctl", "stop", f"{DEADMAN_UNIT}.timer", check=False)   # never stop our own service
    else:
        deadman_disarm()
    left = active_faults()
    return {"reason": reason, "actions": out, "reset_lab": p.stdout[-2000:] + p.stderr[-1000:],
            "remaining": left, "verified": not left and p.returncode == 0}


def mutant_deploy(i: str, spec: str) -> dict:
    """Restart instance i as a mutant build (runtime drop-in; the device validates SPEC again)."""
    d = inst_arg(i)
    if not valid_mutant(spec):
        raise Refused("mutant must be other-serial:SERIAL|seq-reuse|no-newline|off-by-one-id|temp-string|slow-7th")
    require_clean()
    other = {j: b for j, b in builds().items() if b != "stock" or mutant_dropin(j).exists()}
    if other:
        raise Refused(f"a mutant is already deployed ({other}); one at a time, restore it first")
    f = mutant_dropin(i)
    f.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    f.write_text("# witness-faultctl mutant deploy (runtime only; removed by mutant restore / reset_lab.sh / reboot)\n"
                 f"[Service]\nEnvironment=WITNESS_MUTANT={spec}\n")
    sh("systemctl", "daemon-reload", timeout=20)
    old = main_pid(i)
    sh("systemctl", "restart", unit(i), timeout=20)
    ok = wait_for(lambda: listening(d["address"], d["port"]) and device_build(i) == f"mutant:{spec}", 5)
    return {"applied_at": now_iso(), "verified": ok, "build": device_build(i), "old_pid": old, "new_pid": main_pid(i),
            "dropin": str(f), "detail": f"{unit(i)} pid {old}->{main_pid(i)} build={device_build(i)}"}


def mutant_restore(i: str) -> dict:
    """Back to the stock build: remove the drop-in, reload, restart, verify."""
    d = inst_arg(i)
    f = mutant_dropin(i)
    had = f.exists()
    if had:
        f.unlink()
        try:
            f.parent.rmdir()
        except OSError:
            pass
    sh("systemctl", "daemon-reload", timeout=20)
    if had or device_build(i) != "stock":
        sh("systemctl", "restart", unit(i), timeout=20)
    ok = wait_for(lambda: listening(d["address"], d["port"]) and device_build(i) == "stock"
                  and device_mode(i) == "normal", 5)
    env_left = sh("systemctl", "show", "-p", "Environment", "--value", unit(i), check=False).strip()
    return {"removed_at": now_iso(), "verified": ok and "WITNESS_MUTANT" not in env_left, "build": device_build(i),
            "pid": main_pid(i), "detail": f"{unit(i)} build={device_build(i)} dropin_removed={had} env={env_left!r}"}


# ---------------------------------------------------------------- read-only

def check() -> dict:
    """Quick postflight: fault state only (full preflight is `preflight`)."""
    checks = []

    def c(name, ok, detail):
        checks.append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})

    for i, d in instances().items():
        active = sh("systemctl", "is-active", unit(i), check=False).strip()
        pid = main_pid(i)
        st = proc_stat(pid)[0] if pid else "-"
        c(f"service-{i}", active == "active" and st != "T", f"{unit(i)} {active} pid {pid} state {st}")
        c(f"listen-{i}", listening(d["address"], d["port"]), f"{d['address']}:{d['port']}")
        m = device_mode(i)
        c(f"mode-{i}", m == "normal", f"mode={m}")
        # informational: the build is the system under test, so it never gates a case (the run's kind
        # is derived from it at session start, and a change during the run contaminates the run)
        checks.append({"name": f"build-{i}", "status": "PASS", "detail": f"build={device_build(i)}"})
    for ifc in (LAB_IF, INV["lab"]["device_interface"]):
        q = qdiscs(ifc)
        c(f"qdisc-{ifc}", bool(q) and not re.search(r"\b(netem|tbf|prio)\b", q), " ; ".join(q.splitlines()))
    ft = fault_tables()
    c("no-fault-nft", not ft, ",".join(ft) or "none")
    ho = half_open()
    c("no-half-open", not ho, "; ".join(ho) or "no SYN-RECV on device ports")
    st = stale_conns()
    c("no-stale-conn", not st, "; ".join(x["line"] for x in st) or f"no device connection idle >= {STALE_IDLE_MS} ms")
    c("capture-idle", not capture_active(), f"{CAPTURE_UNIT} {'RUNNING' if capture_active() else 'inactive'}")
    c("deadman-disarmed", not deadman_armed(), f"{DEADMAN_UNIT}.timer {'armed' if deadman_armed() else 'inactive'}")
    want = sorted(f"{d['address']}/{INV['lab']['device_subnet'].split('/')[1]}" for d in INV["devices"])
    got = sorted(re.findall(r"\binet (\S+)", sh("ip", "-4", "-o", "addr", "show", "dev",
                                                 INV["lab"]["device_interface"], check=False)))
    c("device-addrs", got == want, " ".join(got))
    return {"checks": checks, "green": all(x["status"] == "PASS" for x in checks)}


def preflight(allow_mutant: bool = False) -> dict:
    p = subprocess.run(["bash", str(REPO / "scripts/preflight.sh"), "--role", "field"]
                       + (["--allow-mutant"] if allow_mutant else []),
                       capture_output=True, text=True, timeout=90)
    checks = []
    for line in p.stdout.splitlines():
        parts = line.split(" ", 2)
        if parts[0] in ("PASS", "FAIL", "SKIP") and len(parts) >= 2:
            checks.append({"status": parts[0], "name": parts[1], "detail": parts[2] if len(parts) > 2 else ""})
    return {"checks": checks, "green": p.returncode == 0, "rc": p.returncode, "output": p.stdout[-6000:]}


def sha(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "missing"


def env() -> dict:
    osr = dict(line.split("=", 1) for line in Path("/etc/os-release").read_text().splitlines() if "=" in line)
    off = subprocess.run(["python3", str(REPO / "scripts/lib/ntp_offset.py"),
                          next(v["l2_address"] for v in INV["lab"]["vms"] if v["role"] == "ctl"),
                          "--samples", "4", "--timeout", "1"], capture_output=True, text=True, timeout=15)
    out = {
        "kernel": platform.release(),
        "distro": osr.get("PRETTY_NAME", "").strip('"'),
        "python": platform.python_version(),
        "systemd": sh("systemctl", "--version").splitlines()[0],
        "qdisc": "\n".join(f"{ifc}: {qdiscs(ifc)}" for ifc in (LAB_IF, INV["lab"]["device_interface"])),
        "nft": sh("nft", "list", "ruleset", check=False),
        "chrony.sources": sh("chronyc", "-n", "sources", check=False),
        "chrony.tracking": sh("chronyc", "-n", "tracking", check=False),
        "chrony.offset": off.stdout.strip() or f"no reply rc={off.returncode}",
        "device_py.sha256": sha(DEVICE_PY),
        "mutants_py.sha256": sha(DEVICE_PY.with_name("mutants.py")),
        "provenance": provenance(),
        "device_unit.sha256": sha(Path("/etc/systemd/system/witness-device@.service")),
        "faultctl.sha256": sha(Path("/usr/local/sbin/witness-faultctl")),
    }
    for i in instances():
        out[f"device_env.{i}"] = Path(f"/etc/witness/device-{i}.env").read_text() if Path(f"/etc/witness/device-{i}.env").exists() else "missing"
        out[f"device_pid.{i}"] = str(main_pid(i))
        out[f"device_build.{i}"] = str(device_build(i))
    return out


def provenance() -> str:
    """Same format as runner/lab.py provenance(): golden-restore record (if any) + boot id."""
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    try:
        text = " ".join(Path("/var/lib/witness/provenance").read_text().split())
    except OSError:
        text = "long-lived VM (no golden-restore record)"
    return f"{text} boot_id={boot}"


def snapshot() -> dict:
    return {
        "tc_qdisc": sh("tc", "-s", "qdisc", "show", "dev", LAB_IF, check=False),
        "tc_filter": sh("tc", "filter", "show", "dev", LAB_IF, check=False),
        "nft": sh("nft", "list", "ruleset", check=False),
        "ss": sh("ss", "-tanp", "sport = :5020 or dport = :5020", check=False),
        "ss_info": sh("ss", "-tni", "sport = :5020", check=False),
        "counters": " ".join(f"{k}={v}" for k, v in counters()["counters"].items()
                             if k in ("Ip.InReceives", "Ip.InAddrErrors", "IpExt.InNoRoutes", "Icmp.OutDestUnreachs",
                                      "Tcp.OutRsts", "Tcp.AttemptFails", "Tcp.EstabResets", "Tcp.InSegs")),
        "services": sh("systemctl", "--no-pager", "--lines=0", "status", *(unit(i) for i in instances()),
                       check=False, timeout=10),
        "active_faults": active_faults(),
    }


def journal(i: str, since: str) -> dict:
    inst_arg(i)
    if not re.fullmatch(r"\d{9,11}(\.\d+)?", since):
        raise Refused("since must be epoch seconds")
    return {"journal": sh("journalctl", "-u", unit(i), "--since", f"@{since}", "-o", "short-iso-precise",
                          "--no-pager", "-n", "400", check=False, timeout=15)}


# ---------------------------------------------------------------- dispatch

def dispatch(a: list[str]) -> dict:
    match a:
        case ["status"]:
            return {"active_faults": active_faults(), "deadman_armed": deadman_armed(),
                    "pids": {i: main_pid(i) for i in instances()}, "modes": {i: device_mode(i) for i in instances()},
                    "builds": builds(),
                    "capture_active": capture_active()}
        case ["check"]:
            return check()
        case ["preflight"]:
            return preflight()
        case ["preflight", "allow-mutant"]:
            return preflight(allow_mutant=True)
        case ["mutant", "deploy", i, spec]:
            return mutant_deploy(i, spec)
        case ["mutant", "restore", i]:
            return mutant_restore(i)
        case ["env"]:
            return env()
        case ["snapshot"]:
            return snapshot()
        case ["journal", i, since]:
            return journal(i, since)
        case ["apply", "service-stop", i]:
            return apply_service_stop(i)
        case ["apply", "sigstop", i]:
            return apply_sigstop(i)
        case ["apply", "mode", i, m]:
            return apply_mode(i, m)
        case ["apply", "netem", d, s]:
            return apply_netem(d, s)
        case ["apply", "nft", kind, i]:
            return apply_nft(kind, i)
        case ["apply", "restart", i]:
            return apply_restart(i)
        case ["revert", "nft"]:
            return revert_nft()
        case ["revert", "restart", i]:
            return revert_restart(i)
        case ["capture", "start", name, *ports]:
            return capture_start(name, ports)
        case ["capture", "stop", name]:
            return capture_stop(name)
        case ["counters"]:
            return counters()
        case ["revert", "service-stop", i]:
            return revert_service_stop(i)
        case ["revert", "sigstop", i, pid, st]:
            return revert_sigstop(i, pid, st)
        case ["revert", "mode", i]:
            return revert_mode(i)
        case ["revert", "netem"]:
            return revert_netem()
        case ["reset"] | ["reset", "manual"]:
            return reset("manual")
        case ["reset", "deadman"]:
            return reset("deadman")
    raise Refused(f"unknown command {' '.join(a)!r}")


def main(argv: list[str]) -> int:
    if os.geteuid() != 0:
        print(json.dumps({"ok": False, "error": "must run as root"}))
        return 2
    mutating = bool(argv) and argv[0] in ("apply", "revert", "reset", "capture", "mutant")
    try:
        assert_field_vm()
        out = dispatch(argv)
        out["ok"] = True
        if mutating:
            audit(f"{' '.join(argv)} -> ok verified={out.get('verified')}")
        print(json.dumps(out))
        return 0
    except (Refused, OSError, subprocess.SubprocessError, ValueError, KeyError, StopIteration) as e:
        if mutating:
            audit(f"{' '.join(argv)} -> REFUSED {e}")
        print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
