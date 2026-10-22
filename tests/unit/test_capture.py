"""Independent audit F-07: per-case capture filters include every port the case dials (F3's 5021), stay narrow
(TCP on those ports + ICMP, nothing else), and each dialled flow is classified as expected on the wire or not.
Pure functions and the field agent's argument validation; the real captures are checked on the VMs."""
import importlib.util
import shutil
import struct
from pathlib import Path

import pytest

from runner import catalog
from runner.lab import capture_filter, count_packets, dialled_flows, flow_filter
from scripts.lib import inventory

REPO = Path(__file__).resolve().parents[2]
INV = inventory.load(REPO / "inventory.yaml")


def test_ctl_filter_includes_the_fault_port_and_nothing_else():
    ports = [d["port"] for d in INV["devices"]]
    assert capture_filter(ports) == "(tcp port 5020) or icmp"
    assert catalog.FAULTS_BY_ID["F3"].capture_ports == (catalog.WRONG_PORT,) == (5021,)
    assert capture_filter(ports + list(catalog.FAULTS_BY_ID["F3"].capture_ports)) == \
        "(tcp port 5020 or tcp port 5021) or icmp"
    assert all(f.capture_ports == () for f in catalog.FAULTS if f.fault_id != "F3")
    for bad in ([], [0], [70000], ["5020; rm"]):
        with pytest.raises((ValueError, TypeError)):
            capture_filter(bad)


def test_flow_filter_validates_its_inputs():
    assert flow_filter("10.77.2.11", 5021) == "tcp and host 10.77.2.11 and port 5021"
    assert flow_filter("10.77.2.11", 5020, 43210) == "tcp and host 10.77.2.11 and port 5020 and port 43210"
    for addr, port, lport in (("dev-a.lab", 5020, None), ("10.77.2.11 or 1", 5020, None), ("10.77.2.11", 0, None),
                              ("10.77.2.11", 5020, 70000)):
        with pytest.raises(ValueError):
            flow_filter(addr, port, lport)


def test_dialled_flows_expected_on_the_wire_or_explicitly_not():
    rows = [("10.77.2.11", 5021, None, "connect", "ECONNREFUSED"),     # F3: SYN out, RST back
            ("10.77.2.13", 5020, None, "connect", "timeout"),          # F4: SYNs out, nothing back
            ("10.77.2.11", 5020, None, "connect", "ENETUNREACH"),      # F5: refused locally, nothing sent
            (None, 5020, None, "resolve", "gaierror:-2"),              # F7-missing: no address
            ("10.77.2.12", 5020, 40001, None, None), ("10.77.2.12", 5020, 40001, None, None),   # F7 swap, 2 exchanges
            ("10.77.2.11", 5020, 40002, None, None)]                   # another established connection
    got = {(f["addr"], f["port"], f["local_port"]): (f["expected"], f["why"]) for f in dialled_flows(rows)}
    assert len(got) == 6
    assert got[("10.77.2.11", 5021, None)][0] and got[("10.77.2.13", 5020, None)][0]
    assert got[("10.77.2.12", 5020, 40001)][0] and got[("10.77.2.11", 5020, 40002)][0]
    assert got[("10.77.2.11", 5020, None)] == (False, "ENETUNREACH: connect failed locally, nothing is sent")
    assert got[(None, 5020, None)][0] is False and "no address" in got[(None, 5020, None)][1]
    # one unexpected and one expected exchange on the same flow: packets are expected
    assert dialled_flows([("10.77.2.11", 5020, None, "connect", "ENETUNREACH"),
                          ("10.77.2.11", 5020, None, "connect", "timeout")])[0]["expected"]


def test_field_agent_capture_filter_validates_ports(monkeypatch):
    monkeypatch.setenv("WIT_REPO", str(REPO))
    spec = importlib.util.spec_from_file_location("faultctl_capture_under_test", REPO / "scripts/faultctl.py")
    fc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fc)
    fc.INV = INV
    assert fc.capture_filter([]) == "(tcp port 5020) or icmp"
    assert fc.capture_filter(["5021"]) == "(tcp port 5020 or tcp port 5021) or icmp"
    for bad in (["0"], ["99999"], ["5021", "x"], ["50 21"], ["-1"], ["1", "2", "3", "4", "5"], ["5021;id"]):
        with pytest.raises(fc.Refused):
            fc.capture_filter(bad)


def _pcap(path: Path, packets: list[bytes]) -> None:
    out = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)          # LINKTYPE_ETHERNET
    for i, p in enumerate(packets):
        out += struct.pack("<IIII", 1700000000 + i, 0, len(p), len(p)) + p
    path.write_bytes(out)


def _syn(dst: str, dport: int) -> bytes:
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 40, 1, 0, 64, 6, 0, bytes([10, 77, 1, 10]),
                     bytes(int(x) for x in dst.split(".")))
    tcp = struct.pack("!HHIIBBHHH", 40000, dport, 1, 0, 0x50, 0x02, 64240, 0, 0)
    return b"\x52\x55\x55\x77\x01\x20" + b"\x52\x55\x55\x77\x01\x10" + b"\x08\x00" + ip + tcp


@pytest.mark.skipif(shutil.which("tcpdump") is None, reason="tcpdump not installed")
def test_count_packets_reads_the_flow_out_of_a_pcap(tmp_path):
    p = tmp_path / "c.pcap"
    _pcap(p, [_syn("10.77.2.11", 5020), _syn("10.77.2.11", 5021), _syn("10.77.2.11", 5021)])
    assert count_packets(p, flow_filter("10.77.2.11", 5021)) == 2
    assert count_packets(p, flow_filter("10.77.2.11", 5021, 40000)) == 2       # _syn's source port
    assert count_packets(p, flow_filter("10.77.2.11", 5021, 40001)) == 0
    assert count_packets(p, flow_filter("10.77.2.12", 5021)) == 0
    assert count_packets(tmp_path / "missing.pcap", flow_filter("10.77.2.11", 5021)) is None
