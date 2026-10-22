"""witness-ctl side of the live lab: identity guard, checks, control channel, capture, F7.

Everything here runs ON witness-ctl as root (the runner is VM-A). witness-field is
reached only through `witness-faultctl` over SSH on lab0 (scripts/faultctl.py), which
re-checks its own identity and validates every argument. Nothing here touches macOS.
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import platform
import re
import select
import signal
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LAB_IF = "lab0"
CTL_DEADMAN = "witness-ctl-fault-deadman"
DEADMAN_S = 90
SSH_KEY = "/var/lib/witness/runner/id_ed25519"
KNOWN_HOSTS = "/var/lib/witness/runner/known_hosts"
HOSTS_BEGIN = "# BEGIN witness-lab (generated from inventory.yaml; edit there, not here)"
HOSTS_END = "# END witness-lab"
GATEWAY_UNIT = "witness-gateway"
GATEWAY_ADDR = ("127.0.0.1", 8080)
GATEWAY_LIB = Path("/usr/local/lib/witness-gateway")


class LabError(RuntimeError):
    """A lab operation failed. infra=True when the control channel itself is down."""

    def __init__(self, msg: str, infra: bool = False):
        super().__init__(msg)
        self.infra = infra


def run(cmd: list[str], timeout: float = 20, check: bool = False) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise LabError(f"{' '.join(cmd)} rc={p.returncode}: {(p.stderr or p.stdout).strip()[:300]}")
    return p


# ---------------------------------------------------------------- identity

def assert_ctl_vm(inv: dict) -> None:
    """Refuse to run live tests anywhere but the inventoried witness-ctl VM."""
    vm = next(v for v in inv["lab"]["vms"] if v["role"] == "ctl")
    if platform.system() != "Linux":
        raise LabError("live tests run only on witness-ctl (Linux guest), never on the Mac")
    if subprocess.run(["systemd-detect-virt", "--vm", "--quiet"]).returncode != 0:
        raise LabError("not a VM")
    mac = Path(f"/sys/class/net/{LAB_IF}/address").read_text().strip()
    if mac != vm["mac"]:
        raise LabError(f"{LAB_IF} MAC {mac} != inventory {vm['mac']}; wrong VM")
    if platform.node() not in (vm["name"], f"lima-{vm['name']}"):
        raise LabError(f"hostname {platform.node()} is not {vm['name']}")
    if os.geteuid() != 0:
        raise LabError("live tests need root on witness-ctl (tcpdump, /etc/hosts fault F7)")


# ---------------------------------------------------------------- field control channel

class FieldCtl:
    def __init__(self, address: str, user: str = "witness-fault"):
        self.address, self.user = address, user
        self.calls: list[dict] = []    # command log for evidence

    def __call__(self, *args: str, timeout: float = 30) -> dict:
        cmd = ["ssh", "-i", SSH_KEY, "-o", "BatchMode=yes", "-o", "ConnectTimeout=3",
               "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={KNOWN_HOSTS}",
               "-o", "ServerAliveInterval=2", "-o", "ServerAliveCountMax=3",
               f"{self.user}@{self.address}", *args]
        t0 = time.time()
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            self.calls.append({"t": t0, "args": args, "rc": "timeout"})
            raise LabError(f"faultctl {' '.join(args)}: ssh timed out after {timeout}s", infra=True) from None
        self.calls.append({"t": t0, "args": args, "rc": p.returncode, "ms": round((time.time() - t0) * 1000)})
        if p.returncode == 255:
            raise LabError(f"faultctl {' '.join(args)}: ssh transport failed: {p.stderr.strip()[:300]}", infra=True)
        try:
            out = json.loads(p.stdout)
        except ValueError:
            raise LabError(f"faultctl {' '.join(args)}: non-JSON reply rc={p.returncode}: "
                           f"{(p.stdout + p.stderr).strip()[:300]}") from None
        if not out.get("ok"):
            raise LabError(f"faultctl {' '.join(args)} refused: {out.get('error')}")
        return out


# ---------------------------------------------------------------- checks on ctl

def parse_check_lines(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        parts = line.split(" ", 2)
        if parts[0] in ("PASS", "FAIL", "SKIP") and len(parts) >= 2:
            out.append({"status": parts[0], "name": parts[1], "detail": parts[2] if len(parts) > 2 else ""})
    return out


def preflight_local() -> dict:
    p = run(["bash", str(REPO / "scripts/preflight.sh"), "--role", "ctl"], timeout=90)
    return {"checks": parse_check_lines(p.stdout), "green": p.returncode == 0, "output": p.stdout}


def hosts_block(inv: dict) -> str:
    rows = "\n".join(f"{d['address']}\t{d['hostname']}" for d in inv["devices"])
    return f"{HOSTS_BEGIN}\n{rows}\n{HOSTS_END}"


def current_hosts_block(text: str) -> str:
    m = re.search(re.escape(HOSTS_BEGIN) + r".*?" + re.escape(HOSTS_END), text, re.S)
    return m.group(0) if m else ""


def deadman_armed(unit: str = CTL_DEADMAN) -> bool:
    return run(["systemctl", "is-active", f"{unit}.timer"]).stdout.strip() == "active"


def quick_check_local(inv: dict) -> dict:
    """Fault-state postflight on ctl (fast; the full preflight runs per session)."""
    checks = []

    def c(name, ok, detail):
        checks.append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})

    subnet = inv["lab"]["device_subnet"]
    field_l2 = next(v["l2_address"] for v in inv["lab"]["vms"] if v["role"] == "field")
    r = run(["ip", "-4", "route", "show", subnet]).stdout.strip()
    c("device-route", r.startswith(f"{subnet} via {field_l2} dev {LAB_IF}"), r or "missing")
    blk = current_hosts_block(Path("/etc/hosts").read_text())
    c("hosts-block", blk == hosts_block(inv), "matches inventory" if blk == hosts_block(inv) else blk.replace("\n", " | "))
    q = run(["tc", "qdisc", "show", "dev", LAB_IF]).stdout.strip()
    c(f"qdisc-{LAB_IF}", bool(q) and not re.search(r"\b(netem|tbf|prio)\b", q), " ; ".join(q.splitlines()))
    t = [l for l in run(["nft", "list", "tables"]).stdout.splitlines() if " witness_fault" in l]
    c("no-fault-nft", not t, ",".join(t) or "none")
    c("deadman-disarmed", not deadman_armed(), f"{CTL_DEADMAN}.timer {'armed' if deadman_armed() else 'inactive'}")
    gw_active = run(["systemctl", "is-active", f"{GATEWAY_UNIT}.service"]).stdout.strip()
    try:
        code, body = Gateway().get("/inventory")
        ids = sorted(d["device_id"] for d in body.get("devices", []))
        ok = gw_active == "active" and code == 200 and ids == sorted(d["device_id"] for d in inv["devices"])
        c("gateway", ok, f"{GATEWAY_UNIT} {gw_active}; GET /inventory {code} devices={ids}")
    except (OSError, ValueError) as e:
        c("gateway", False, f"{GATEWAY_UNIT} {gw_active}; GET /inventory failed: {e}")
    return {"checks": checks, "green": all(x["status"] == "PASS" for x in checks)}


def reset_local() -> str:
    p = run(["bash", str(REPO / "scripts/reset_lab.sh"), "--role", "ctl"], timeout=120)
    run(["systemctl", "stop", f"{CTL_DEADMAN}.timer"])
    return f"rc={p.returncode} {p.stdout[-1500:]}{p.stderr[-500:]}"


# ---------------------------------------------------------------- ctl faults (F4, F5, F7)

def arm_ctl_deadman(what: str) -> None:
    """Transient 90 s timer: reset_lab.sh --role ctl rewrites the managed /etc/hosts block and
    restores the device route if this process dies before reverting a ctl-side fault."""
    run(["systemctl", "stop", f"{CTL_DEADMAN}.timer"])
    run(["systemctl", "reset-failed", f"{CTL_DEADMAN}.timer", f"{CTL_DEADMAN}.service"])
    run(["systemd-run", f"--unit={CTL_DEADMAN}", f"--on-active={DEADMAN_S}", "--timer-property=AccuracySec=1s",
         f"--description=Witness ctl fault dead-man ({what})", "/bin/bash", str(REPO / "scripts/reset_lab.sh"),
         "--role", "ctl"], check=True)
    if not deadman_armed():
        raise LabError(f"ctl dead-man did not arm for {what}")


def disarm_ctl_deadman() -> None:
    run(["systemctl", "stop", f"{CTL_DEADMAN}.timer"])
    run(["systemctl", "reset-failed", f"{CTL_DEADMAN}.timer"])


class RouteDelete:
    """F5: delete witness-ctl's route to the device subnet (via witness-field on lab0). Only that
    route: the lab0 connected route (SSH control channel to witness-field) and vsock management
    are untouched. The ctl dead-man restores it if the runner dies."""

    def __init__(self, inv: dict):
        self.subnet = inv["lab"]["device_subnet"]
        self.via = next(v["l2_address"] for v in inv["lab"]["vms"] if v["role"] == "field")
        self.probe = inv["devices"][0]["address"]

    def route(self) -> str:
        return run(["ip", "-4", "route", "show", self.subnet]).stdout.strip()

    def apply(self) -> str:
        if not self.route().startswith(f"{self.subnet} via {self.via} dev {LAB_IF}"):
            raise LabError(f"refusing F5: route is {self.route()!r}, not the inventoried one")
        arm_ctl_deadman("F5 route delete")
        run(["ip", "route", "del", self.subnet, "via", self.via, "dev", LAB_IF], check=True)
        g = run(["ip", "-4", "route", "get", self.probe])
        return f"route {self.subnet} deleted; ip route get {self.probe} -> rc={g.returncode} {(g.stdout + g.stderr).strip()}"

    def applied(self) -> bool:
        return not self.route() and run(["ip", "-4", "route", "get", self.probe]).returncode != 0

    def revert(self) -> bool:
        run(["ip", "route", "replace", self.subnet, "via", self.via, "dev", LAB_IF, "proto", "static"], check=True)
        disarm_ctl_deadman()
        return self.route().startswith(f"{self.subnet} via {self.via} dev {LAB_IF}")


class HostsSwap:
    """F7/F4: point one managed /etc/hosts name at another address (F7: the other device; F4:
    an unused address, i.e. the block regenerated from a faulted inventory), then restore the
    exact original bytes. to_addr=None removes the name's line instead (F7-missing: naming failure).
    A dead-man timer runs reset_lab.sh (which rewrites the managed block from inventory.yaml) if
    the runner dies before restoring."""

    def __init__(self, inv: dict, hostname: str, to_addr: str | None):
        self.inv, self.hostname, self.to_addr = inv, hostname, to_addr
        self.original: str | None = None

    def apply(self) -> str:
        text = Path("/etc/hosts").read_text()
        blk = current_hosts_block(text)
        if blk != hosts_block(self.inv):
            raise LabError("refusing F7: /etc/hosts managed block does not match inventory before the fault")
        dev = next(d for d in self.inv["devices"] if d["hostname"] == self.hostname)
        old_line = f"{dev['address']}\t{self.hostname}"
        new_line = f"{self.to_addr}\t{self.hostname}" if self.to_addr else ""
        if blk.count(old_line + "\n") != 1:
            raise LabError(f"refusing F7: line {old_line!r} not found exactly once")
        self.original = text
        arm_ctl_deadman(f"hosts {self.hostname} -> {self.to_addr or 'removed'}")
        new_blk = blk.replace(old_line + "\n", new_line + "\n" if new_line else "")
        _atomic_write(Path("/etc/hosts"), text.replace(blk, new_blk))
        return new_line or f"(removed {old_line!r})"

    def revert(self) -> bool:
        if self.original is not None:
            _atomic_write(Path("/etc/hosts"), self.original)
        disarm_ctl_deadman()
        return current_hosts_block(Path("/etc/hosts").read_text()) == hosts_block(self.inv)


def _atomic_write(path: Path, text: str) -> None:
    st = path.stat()
    tmp = path.with_name(path.name + ".witness.tmp")
    tmp.write_text(text)
    os.chmod(tmp, st.st_mode & 0o7777)
    os.chown(tmp, st.st_uid, st.st_gid)
    os.replace(tmp, path)


# ---------------------------------------------------------------- capture

def capture_filter(ports) -> str:
    """BPF of a per-case capture: TCP on exactly these ports (the inventory's device ports plus the case fault's
    extra ports, runner/catalog.Fault.capture_ports) and ICMP. Independent audit F-07: a fixed "tcp port 5020"
    dropped F3's dialled port 5021, so the capture held the gateway's polls but not the tested SYN/RST."""
    ps = sorted({int(p) for p in ports})
    if not ps or not all(0 < p < 65536 for p in ps):
        raise ValueError(f"capture ports must be 1-65535: {ps}")
    return "(" + " or ".join(f"tcp port {p}" for p in ps) + ") or icmp"


def flow_filter(addr: str, port: int, local_port: int | None = None) -> str:
    """BPF of one dialled TCP flow (both directions). With the runner's ephemeral port (known once the connection
    was established) it matches only that connection, not the gateway's polls to the same address:port."""
    import ipaddress
    ipaddress.IPv4Address(addr)
    if not all(0 < int(p) < 65536 for p in (port, local_port or 1)):
        raise ValueError(f"bad port {port}/{local_port}")
    return f"tcp and host {addr} and port {int(port)}" + (f" and port {int(local_port)}" if local_port else "")


def flow_record_filter(flow: dict) -> str:
    """capture_flows.filter of one dialled_flows() entry: its BPF, or, when the name never resolved (no address to
    filter on), a placeholder naming the port. Shared by the live recorder and the acceptance check (A17)."""
    if flow["addr"] is None:
        return f"(none: port {flow['port']}, no address)"
    return flow_filter(flow["addr"], flow["port"], flow["local_port"])


def dialled_flows(exchanges) -> list[dict]:
    """(addr, port, local_port, stage_failed, os_error) of a result's exchanges -> one entry per dialled connection
    (address, port and, when established, the runner's ephemeral port) with whether packets of it must be on the
    wire. Nothing is sent when the name never resolved (no address), when connect() failed locally with ENETUNREACH
    (F5: no route) or when the case deadline left no time to start; anything else put at least a SYN on lab0. A
    failed connect has no local port: its flow is the address:port, which the gateway's polls can share."""
    flows: dict[tuple, dict] = {}
    for addr, port, lport, stage, err in exchanges:
        f = flows.setdefault((addr, port, lport), {"addr": addr, "port": port, "local_port": lport,
                                                   "expected": False, "why": set()})
        if addr is None:
            f["why"].add(f"no address ({stage or 'resolve'} {err}): nothing can be sent")
        elif err == "not_started":
            f["why"].add("not started: case deadline")
        elif stage == "connect" and err == "ENETUNREACH":
            f["why"].add("ENETUNREACH: connect failed locally, nothing is sent")
        else:
            f["expected"] = True
            f["why"].add("dialled flow must be on the wire")
    return [dict(f, why="; ".join(sorted(f["why"]))) for _, f in
            sorted(flows.items(), key=lambda kv: (kv[0][0] or "", kv[0][1], kv[0][2] or 0))]


def count_packets(pcap: Path, bpf: str) -> int | None:
    """Packets in `pcap` matching `bpf` (tcpdump -r), or None if the file is missing or unreadable."""
    if not Path(pcap).exists():
        return None
    p = run(["tcpdump", "-nn", "-r", str(pcap), bpf], timeout=20)
    if p.returncode != 0:
        return None
    return sum(1 for line in p.stdout.splitlines() if line.strip())


class Capture:
    """Bounded tcpdump on ctl lab0 (both directions of every lab exchange cross it).
    --immediate-mode is required: without it libpcap (TPACKET_V3) delivers packets only
    when a ring block fills or times out, and a sub-second case ends before that
    (observed: "10 packets received by filter, 0 packets captured")."""

    def __init__(self, path: Path, bpf: str = "tcp port 5020 or icmp", max_s: int = 60, max_packets: int = 5000):
        self.path, self.bpf, self.max_s, self.max_packets = Path(path), bpf, max_s, max_packets
        self.proc: subprocess.Popen | None = None
        self.stderr = ""

    def start(self) -> "Capture":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen(
            ["timeout", "-s", "INT", "-k", "3", str(self.max_s), "tcpdump", "-i", LAB_IF, "-nn", "-U", "--immediate-mode", "-Z", "root",
             "-s", "512", "-c", str(self.max_packets), "-w", str(self.path), self.bpf],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        end = time.monotonic() + 5
        while time.monotonic() < end:
            r, _, _ = select.select([self.proc.stderr], [], [], 0.1)
            if r:
                line = self.proc.stderr.readline().decode(errors="replace")
                self.stderr += line
                if "listening on" in line:
                    return self
            if self.proc.poll() is not None:
                break
        self.stop()
        raise LabError(f"tcpdump did not start: {self.stderr.strip()[:300]}")

    def stop(self, linger_s: float = 0.3) -> Path | None:
        if self.proc is None:
            return None
        time.sleep(linger_s)              # let FIN/RST of the closing exchange land in the capture
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGINT)
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=3)
        self.stderr += self.proc.stderr.read().decode(errors="replace")
        self.proc = None
        if not self.path.exists():
            return None
        txt = self.path.with_suffix(".txt")
        p = run(["tcpdump", "-nn", "-tttt", "-A", "-r", str(self.path)], timeout=20)
        txt.write_text(p.stdout[:400_000] + ("\n[tcpdump] " + self.stderr.strip() + "\n" if self.stderr else ""))
        return txt


class FieldCapture:
    """tcpdump on witness-field lab0 through witness-faultctl (a transient unit bounded by
    RuntimeMaxSec on field). Shows whether a packet ARRIVED at field, which the ctl capture
    cannot (F4 silent drop, F8 nft drop vs. loss on the switch)."""

    def __init__(self, field: FieldCtl, name: str, path: Path, extra_ports: tuple[int, ...] = ()):
        self.field, self.name, self.path = field, re.sub(r"[^A-Za-z0-9_.-]", "_", name)[:96], Path(path)
        self.extra_ports = tuple(int(p) for p in extra_ports)      # added to field's inventory ports by faultctl
        self.started = False
        self.bpf: str | None = None

    def start(self) -> "FieldCapture":
        r = self.field("capture", "start", self.name, *map(str, self.extra_ports))
        self.bpf = r.get("filter")
        self.started = bool(r.get("started"))
        if not self.started:
            raise LabError(f"field capture did not start: {r}")
        return self

    def stop(self) -> tuple[Path | None, Path | None]:
        if not self.started:
            return None, None
        self.started = False
        time.sleep(0.3)
        r = self.field("capture", "stop", self.name, timeout=40)
        if not r.get("found"):
            return None, None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        pcap = None
        if r.get("pcap_b64"):
            self.path.write_bytes(base64.b64decode(r["pcap_b64"]))
            pcap = self.path
        txt = self.path.with_suffix(".txt")
        txt.write_text(r.get("text", "") + "\n[tcpdump on witness-field] " + r.get("tcpdump", "") + "\n")
        return pcap, txt


class Gateway:
    """Client for the gateway's HTTP API on witness-ctl (bounded: 2 s per request)."""

    def __init__(self, addr: tuple[str, int] = GATEWAY_ADDR, timeout: float = 2.0):
        self.addr, self.timeout = addr, timeout

    def request(self, method: str, path: str) -> tuple[int, dict, dict]:
        c = http.client.HTTPConnection(*self.addr, timeout=self.timeout)
        try:
            c.request(method, path)
            r = c.getresponse()
            raw = r.read()
            body = json.loads(raw) if raw else {}
            return r.status, body, dict(r.getheaders())
        finally:
            c.close()

    def get(self, path: str) -> tuple[int, dict]:
        code, body, _ = self.request("GET", path)
        return code, body

    def device(self, dev_id: str) -> dict:
        code, body = self.get(f"/devices/{dev_id}")
        if code != 200:
            raise LabError(f"gateway GET /devices/{dev_id} -> {code} {body}")
        return body

    def sample(self, dev_ids, until, timeout: float, period: float = 0.1) -> tuple[bool, list[dict]]:
        """Poll GET /devices/<id> for every id every `period` s until until({id: record}) is true
        or `timeout` s pass. Returns (reached, samples); each sample has the runner's own mono time."""
        samples, end = [], time.monotonic() + timeout
        while True:
            t = time.monotonic()
            recs = {d: self.device(d) for d in dev_ids}
            samples.append({"t_mono": round(t, 6), "records": {d: _brief(r) for d, r in recs.items()}})
            if until(recs):
                return True, samples
            if time.monotonic() >= end:
                return False, samples
            time.sleep(max(0.0, period - (time.monotonic() - t)))


def _brief(r: dict) -> dict:
    lp = r.get("last_poll") or {}
    return {"state": r["state"], "state_since_mono": r["state_since_mono"], "reachable": r["reachable"],
            "last_category": r["last_category"], "polls": r["polls"], "last_seen_mono": r["last_seen_mono"],
            "restarts_detected": r.get("restarts_detected"), "poll_started_mono": lp.get("started_mono"),
            "poll_detail": lp.get("detail")}


def ctl_snapshot(inv: dict) -> str:
    """witness-ctl view during a fault: routes, route lookups, names, sockets, qdisc, nft, gateway."""
    out = []

    def sec(title, cmd):
        p = run(cmd, timeout=10)
        out.append(f"== {title}\n$ {' '.join(cmd)}\n{(p.stdout + p.stderr).rstrip()}\n(rc={p.returncode})")

    sec("routes", ["ip", "-4", "route"])
    for d in inv["devices"]:
        sec(f"route get {d['address']}", ["ip", "-4", "route", "get", d["address"]])
        sec(f"resolve {d['hostname']}", ["getent", "ahostsv4", d["hostname"]])
    sec("sockets to device port", ["ss", "-tanpi", "dport = :5020"])
    sec("qdisc lab0", ["tc", "-s", "qdisc", "show", "dev", LAB_IF])
    sec("nft ruleset", ["nft", "list", "ruleset"])
    out.append("== /etc/hosts managed block\n" + current_hosts_block(Path("/etc/hosts").read_text()))
    try:
        out.append("== gateway GET /inventory\n" + json.dumps(Gateway().get("/inventory")[1], indent=1))
    except (OSError, ValueError) as e:
        out.append(f"== gateway GET /inventory failed: {e}")
    return "\n".join(out) + "\n"


def gateway_journal(since_epoch: float) -> str:
    return run(["journalctl", "-u", f"{GATEWAY_UNIT}.service", "--since", f"@{since_epoch:.3f}",
                "-o", "short-iso-precise", "--no-pager", "-n", "400"], timeout=15).stdout


def _sha(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "missing"


# ---------------------------------------------------------------- environment

def source_info() -> dict:
    """git sha/dirty written by `lab_vms.sh sync` (the guest copy has no .git)."""
    f = REPO / ".witness-source"
    out = {}
    if f.exists():
        for line in f.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def local_env() -> dict:
    osr = dict(l.split("=", 1) for l in Path("/etc/os-release").read_text().splitlines() if "=" in l)
    return {
        "kernel": platform.release(),
        "distro": osr.get("PRETTY_NAME", "").strip('"'),
        "qdisc": f"{LAB_IF}: " + run(["tc", "qdisc", "show", "dev", LAB_IF]).stdout.strip(),
        "nft": run(["nft", "list", "ruleset"]).stdout,
        "routes": run(["ip", "-4", "route"]).stdout,
        "hosts_block": current_hosts_block(Path("/etc/hosts").read_text()),
        "chrony.tracking": run(["chronyc", "-n", "tracking"]).stdout,
        "gateway_py.sha256": _sha(GATEWAY_LIB / "gateway/gateway.py"),
        "gateway_unit.sha256": _sha(Path(f"/etc/systemd/system/{GATEWAY_UNIT}.service")),
        "gateway.inventory_sha256": _sha(Path("/etc/witness/inventory.yaml")),
        "gateway.state": run(["systemctl", "show", "-p", "ActiveState,MainPID,NRestarts",
                              f"{GATEWAY_UNIT}.service"]).stdout.strip().replace("\n", " "),        "provenance": provenance(),
    }


PROVENANCE = Path("/var/lib/witness/provenance")


def provenance() -> str:
    """How this VM came to be (written by `lab_vms.sh golden-restore`), plus this boot's id, so a run
    started on a freshly restored clone is distinguishable in SQL from one on a long-lived VM."""
    try:
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        boot = "?"
    try:
        text = " ".join(PROVENANCE.read_text().split())
    except OSError:
        text = "long-lived VM (no golden-restore record)"
    return f"{text} boot_id={boot}"
