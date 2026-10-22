"""Evidence validity checks shared by the live C-ENVIRONMENT case, commissioning (runner/db.py) and the acceptance
assertions (runner/analysis.py). Second independent audit, docs/independent-reaudit.md R-01/R-02: acceptance held over
whitespace-only or contradictory environment values and over capture-flow metadata it never checked against the
capture bytes.

- check_environment: one run's REQ-10 environment record against a definition that does NOT come from the rows
  present: the required keys are runner/catalog.ENV_REQUIRED expanded over the INVENTORY's VMs and devices, each key
  has one allowed representation, and the values must agree with the run row and with every other record of the
  same fact in that run.
- flow_packets: packets of one dialled TCP flow (runner/lab.flow_filter grammar) in a classic pcap, counted from the
  bytes with a parser of its own. tcpdump counted them when the case ran; acceptance recounts them independently.
- file_problem: an indexed evidence file is missing, or its bytes differ from the recorded length and sha256.
"""
from __future__ import annotations

import functools
import hashlib
import math
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

from runner.catalog import ENV_REQUIRED, MUTANT_DEVICE, mutant_spec
from runner.classify import CATEGORIES

REPO = Path(__file__).resolve().parents[1]
# scripts/preflight.sh clock-sync gate: |SNTP offset ctl vs field| < 0.1 s. A fair run (clean_env=1) that records an
# offset outside it contradicts its own green preflight.
CLOCK_SYNC_MAX_S = 0.1
WITHHELD = re.compile(r"unavailable \((?P<cat>[A-Z_]+): .+\)", re.S)
VERSION = re.compile(r"\d+\.\d+\.\d+")
_KERNEL = re.compile(r"\d+\.\d+\.\d+(?:[-+.~][0-9A-Za-z][0-9A-Za-z.+~-]*)?")
_PYTHON = re.compile(r"\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?\+?")
_SHA = re.compile(r"[0-9a-f]{40}")
_FLAG = re.compile(r"[01]")
_OFFSET = re.compile(r"offset_s=(?P<off>[+-]\d+\.\d+) delay_s=(?P<delay>\d+\.\d+) "
                     r"samples=(?P<ok>\d+)/(?P<n>\d+) server=(?P<server>\S+)")
_QDISC_LINE = re.compile(r"(?:(?P<ifc>[A-Za-z0-9_.-]+): )?qdisc \S+ \S.*")
_NFT_TABLE = re.compile(r"^table (?:ip|ip6|inet|arp|bridge|netdev) \S+ \{$", re.M)
_PRINTABLE_LINE = re.compile(r"[^\x00-\x1f\x7f]+")


@functools.lru_cache(maxsize=1)
def repo_inventory() -> dict:
    from scripts.lib import inventory
    return inventory.load(REPO / "inventory.yaml")


def required_env_keys(inv: dict) -> list[str]:
    """Every REQ-10 key a run must record: ENV_REQUIRED for each inventoried VM and device."""
    vms = [v["name"] for v in inv["lab"]["vms"]]
    devs = [d["device_id"] for d in inv["devices"]]
    out = []
    for k in ENV_REQUIRED:
        out += ([k.format(vm=v) for v in vms] if "{vm}" in k else
                [k.format(device=d) for d in devs] if "{device}" in k else [k])
    return out


@dataclass
class EnvCheck:
    problems: dict[str, str] = field(default_factory=dict)   # key -> why its record is not valid evidence
    withheld: set[str] = field(default_factory=set)          # fw_version keys the device withheld (valid form)

    @property
    def ok(self) -> bool:
        return not self.problems


def _single_line(v: str) -> bool:
    return v == v.strip() and bool(_PRINTABLE_LINE.fullmatch(v))


def check_environment(env: dict, run: dict, inv: dict | None = None) -> EnvCheck:
    """Validate one run's environment rows ({key: raw value}) against REQ-10 and the run row (git_sha, git_dirty,
    clean_env, kind, mutant_id). A firmware version recorded as 'unavailable (<CATEGORY>: <detail>)' is the device
    withholding it: always listed in `withheld`, and a problem unless the run is a mutant run and the key belongs to
    the mutant device (the stock control device and non-mutant runs have no such excuse)."""
    inv = inv or repo_inventory()
    out = EnvCheck()
    vms = {v["role"]: v for v in inv["lab"]["vms"]}

    def bad(k, why):
        out.problems.setdefault(k, why)

    # the same fact under two spellings of one key is an ambiguous record (environment's primary key is exact)
    norm: dict[str, list[str]] = {}
    for k in env:
        norm.setdefault("".join(str(k).split()).casefold(), []).append(str(k))
    for keys in norm.values():
        if len(keys) > 1:
            for k in keys:
                bad(k, f"ambiguous duplicate keys {sorted(keys)!r}")
    text = {}
    for k, v in env.items():
        if isinstance(v, str):
            text[k] = v
        else:
            bad(k, f"not text ({type(v).__name__} {v!r:.40})")

    def need(k):
        if k not in env:
            bad(k, "missing")
            return None
        return text.get(k)

    def same(k, value, what):
        v = text.get(k)
        if v is not None and v != value:
            bad(k, f"{v!r:.60} contradicts {what} {value!r}")

    for k in required_env_keys(inv):
        v = need(k)
        if v is None:
            continue
        if not v.strip():
            bad(k, "blank")
        elif k.startswith("kernel."):
            if not _KERNEL.fullmatch(v):
                bad(k, f"not a kernel release: {v!r:.60}")
        elif k.startswith("distro."):
            if not _single_line(v):
                bad(k, f"not a single printable line: {v!r:.60}")
        elif k == "python":
            if not _PYTHON.fullmatch(v):
                bad(k, f"not a Python version: {v!r:.60}")
        elif k == "git_sha":
            if not _SHA.fullmatch(v):
                bad(k, f"not a 40-hex git revision: {v!r:.60}")
            else:
                same(k, run.get("git_sha"), "runs.git_sha")
        elif k in ("git_dirty", "runs.clean_env"):
            col = "git_dirty" if k == "git_dirty" else "clean_env"
            if not _FLAG.fullmatch(v):
                bad(k, f"not 0|1: {v!r:.60}")
            else:
                same(k, None if run.get(col) is None else str(run.get(col)), f"runs.{col}")
        elif k == "chrony.offset":
            m = _OFFSET.fullmatch(v)
            if not m:
                bad(k, f"not 'offset_s=<+-f> delay_s=<f> samples=<ok>/<n> server=<addr>': {v!r:.60}")
            elif not (1 <= int(m["ok"]) <= int(m["n"])):
                bad(k, f"no valid sample ({m['ok']}/{m['n']})")
            elif m["server"] != vms["ctl"]["l2_address"]:
                bad(k, f"measured against {m['server']}, not witness-ctl {vms['ctl']['l2_address']}")
            elif not (math.isfinite(float(m["off"])) and abs(float(m["off"])) < CLOCK_SYNC_MAX_S) \
                    and int(run.get("clean_env") or 0) == 1:
                bad(k, f"offset {m['off']} s outside the preflight clock gate (|x| < {CLOCK_SYNC_MAX_S} s) of a "
                       "run recorded as clean")
        elif k.startswith("qdisc."):
            vm = k.split(".", 1)[1]
            lines = v.split("\n")
            ifcs = []
            for i, line in enumerate(lines):
                m = _QDISC_LINE.fullmatch(line)
                if not m or (i == 0 and not m["ifc"]):
                    bad(k, f"line {i + 1} is not '<interface>: qdisc ...': {line!r:.60}")
                    break
                if m["ifc"]:
                    ifcs.append(m["ifc"])
            want = {"lab0"} | ({inv["lab"]["device_interface"]} if vm == vms["field"]["name"] else set())
            if k not in out.problems and set(ifcs) != want:
                bad(k, f"qdisc record covers {sorted(ifcs)}, not the lab interfaces {sorted(want)}")
        elif k.startswith("nft."):
            if not _NFT_TABLE.search(v):
                bad(k, "no 'table <family> <name> {' in the recorded ruleset")
        elif k.startswith("fw_version."):
            dev = k.split(".", 1)[1]
            w = WITHHELD.fullmatch(v)
            if w and w["cat"] in CATEGORIES and w["cat"] != "PASS":
                out.withheld.add(k)
                if not (run.get("kind") == "mutant" and dev == MUTANT_DEVICE):
                    bad(k, f"withheld by the device ({v[:60]}) outside a mutant run's mutant device "
                           f"({MUTANT_DEVICE}): {run.get('kind')} run")
            elif not VERSION.fullmatch(v):
                bad(k, f"not a firmware version x.y.z or 'unavailable (<CATEGORY>: ...)': {v!r:.60}")

    # other records of facts the run row (or another record) already states: present -> must agree
    same("runs.kind", run.get("kind"), "runs.kind")
    same("mutant", run.get("mutant_id") or "none", "runs.mutant_id")
    want_build = {d["device_id"]: "stock" for d in inv["devices"]}
    if run.get("kind") == "mutant" and run.get("mutant_id"):
        try:
            want_build[MUTANT_DEVICE] = "mutant:" + mutant_spec(run["mutant_id"], inv["devices"])
        except KeyError:
            bad("mutant", f"unknown mutant {run['mutant_id']!r}")
    for d in inv["devices"]:
        k, kf = f"device_build.{d['device_id']}", f"device_build.{d['instance']}.{vms['field']['name']}"
        if k in text and kf in text and text[k] != text[kf]:
            bad(k, f"{text[k]!r} contradicts {kf}={text[kf]!r}")
        same(k, want_build[d["device_id"]], f"the {run.get('kind')} run's build")
    return out


# ---------------------------------------------------------------- packet evidence

_FLOW = re.compile(r"tcp and host (?P<addr>\d{1,3}(?:\.\d{1,3}){3}) and port (?P<port>\d+)(?: and port (?P<lport>\d+))?")


class PcapError(ValueError):
    pass


def flow_packets(pcap: bytes, flt: str) -> int:
    """Packets of `flt` ("tcp and host A and port P[ and port L]", runner/lab.flow_filter) in a classic pcap:
    IPv4 TCP with A as source or destination and P (and L) as a source or destination port, as tcpdump matches it.
    Ethernet and Linux cooked captures; anything else raises PcapError (the bytes cannot be verified)."""
    m = _FLOW.fullmatch(flt)
    if not m:
        raise PcapError(f"not a dialled-flow filter: {flt!r}")
    addr = bytes(int(x) for x in m["addr"].split("."))
    ports = {int(m["port"])} | ({int(m["lport"])} if m["lport"] else set())
    if len(pcap) < 24:
        raise PcapError("shorter than a pcap header")
    magic = pcap[:4]
    if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
        e = "<"
    elif magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
        e = ">"
    else:
        raise PcapError(f"not a classic pcap (magic {magic.hex()})")
    link = struct.unpack(e + "I", pcap[20:24])[0] & 0x0FFFFFFF
    if link == 1:            # Ethernet: ethertype at 12, IP at 14
        et_off, ip_off = 12, 14
    elif link == 113:        # Linux cooked (SLL): protocol at 14, IP at 16
        et_off, ip_off = 14, 16
    else:
        raise PcapError(f"unsupported link type {link}")
    n, off = 0, 24
    while off < len(pcap):
        if off + 16 > len(pcap):
            raise PcapError(f"truncated record header at byte {off}")
        incl = struct.unpack(e + "I", pcap[off + 8:off + 12])[0]
        pkt = pcap[off + 16:off + 16 + incl]
        if len(pkt) != incl:
            raise PcapError(f"truncated packet at byte {off}")
        off += 16 + incl
        if len(pkt) < ip_off + 20 or pkt[et_off:et_off + 2] != b"\x08\x00" or pkt[ip_off] >> 4 != 4:
            continue
        ihl = (pkt[ip_off] & 0x0F) * 4
        frag = struct.unpack(">H", pkt[ip_off + 6:ip_off + 8])[0] & 0x1FFF
        if pkt[ip_off + 9] != 6 or frag or len(pkt) < ip_off + ihl + 4:
            continue
        if addr not in (pkt[ip_off + 12:ip_off + 16], pkt[ip_off + 16:ip_off + 20]):
            continue
        sport, dport = struct.unpack(">HH", pkt[ip_off + ihl:ip_off + ihl + 4])
        if all(p in (sport, dport) for p in ports):
            n += 1
    return n


def file_problem(root: Path, rel: str, sha256: str, size: int) -> str | None:
    """None if `root/rel` exists with exactly the recorded length and sha256, else what is wrong."""
    p = Path(root) / rel
    if not p.is_file():
        return "missing"
    data = p.read_bytes()
    if len(data) != size or hashlib.sha256(data).hexdigest() != sha256:
        return f"differs from its index ({len(data)} B now, {size} B recorded)"
    return None
