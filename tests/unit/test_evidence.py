"""runner/evidence.py (second independent audit R-01/R-02): the REQ-10 environment validator and the independent
packet recount used by acceptance. Synthetic values and pcaps with known answers; never lab evidence."""
import hashlib
import shutil

import pytest

from runner import evidence as EV, lab as L
from storefix import INV, QDISC, SHA, env_ok, flow_frames, pcap_bytes, tcp_packet

RUN = {"git_sha": SHA, "git_dirty": 0, "clean_env": 1, "kind": "baseline", "mutant_id": None}


def test_required_keys_come_from_the_inventory_not_the_store():
    keys = EV.required_env_keys(INV)
    assert len(keys) == 15 and len(set(keys)) == 15
    for vm in ("witness-ctl", "witness-field"):
        assert {f"kernel.{vm}", f"distro.{vm}", f"qdisc.{vm}", f"nft.{vm}"} <= set(keys)
    assert {"fw_version.dev-a", "fw_version.dev-b", "python", "git_sha", "git_dirty", "chrony.offset",
            "runs.clean_env"} <= set(keys)
    inv3 = {**INV, "devices": INV["devices"] + [{**INV["devices"][0], "device_id": "dev-c", "instance": "c"}]}
    assert "fw_version.dev-c" in EV.required_env_keys(inv3)
    assert EV.check_environment(env_ok(), RUN, inv3).problems == {"fw_version.dev-c": "missing"}


def test_valid_record_passes():
    chk = EV.check_environment(env_ok(), RUN, INV)
    assert chk.ok and not chk.withheld


@pytest.mark.parametrize("key,value,why", [
    ("python", "\t\n", "blank"),                                # the audit's R-01 value: SQL trim() kept it
    ("python", " ", "blank"),
    ("python", " 3.12.3", "not a Python version"),
    ("kernel.witness-field", "6.8.0-134-generic\n", "not a kernel release"),
    ("distro.witness-ctl", "Ubuntu\n24.04", "not a single printable line"),
    ("git_sha", "not-the-run-revision", "not a 40-hex git revision"),
    ("git_sha", "f" * 40, "contradicts runs.git_sha"),
    ("git_dirty", "1", "contradicts runs.git_dirty"),
    ("runs.clean_env", "0", "contradicts runs.clean_env"),
    ("chrony.offset", "offset_s=garbage", "not 'offset_s="),
    ("chrony.offset", "offset_s=nan delay_s=nan samples=0/4 server=10.77.1.10", "not 'offset_s="),
    ("chrony.offset", "offset_s=+0.000021 delay_s=0.000324 samples=0/4 server=10.77.1.10", "no valid sample"),
    ("chrony.offset", "offset_s=+0.000021 delay_s=0.000324 samples=4/4 server=10.77.1.20", "measured against"),
    ("chrony.offset", "offset_s=-0.250000 delay_s=0.000324 samples=4/4 server=10.77.1.10", "clock gate"),
    ("qdisc.witness-field", f"lab0: {QDISC}", "not the lab interfaces"),
    ("qdisc.witness-ctl", "lab0: ", "is not '<interface>: qdisc"),
    ("nft.witness-ctl", "# no ruleset\n", "no 'table"),
    ("fw_version.dev-b", "1.0", "not a firmware version"),
    ("fw_version.dev-a", "unavailable (None: unclassifiable)", "not a firmware version"),
    ("fw_version.dev-a", "unavailable (MALFORMED: incomplete:86B)", "withheld by the device"),
])
def test_invalid_values_are_rejected_for_the_right_reason(key, value, why):
    chk = EV.check_environment({**env_ok(), key: value}, RUN, INV)
    assert set(chk.problems) == {key} and why in chk.problems[key], chk.problems


def test_a_non_text_value_is_rejected():
    chk = EV.check_environment({**env_ok(), "python": b"3.12.3"}, RUN, INV)
    assert set(chk.problems) == {"python"} and chk.problems["python"].startswith("not text (bytes")


def test_the_same_fact_recorded_twice_must_agree():
    env = {**env_ok(), "python ": "2.7.18"}
    assert set(EV.check_environment(env, RUN, INV).problems) == {"python", "python "}
    for k, v, why in (("runs.kind", "fault", "contradicts runs.kind"), ("mutant", "M2", "contradicts runs.mutant_id"),
                      ("device_build.dev-a", "mutant:seq-reuse", "contradicts the baseline run's build"),
                      ("device_build.a.witness-field", "mutant:seq-reuse", "contradicts device_build.a.witness-field")):
        p = EV.check_environment({**env_ok(), k: v}, RUN, INV).problems
        assert len(p) == 1 and why in next(iter(p.values())), (k, p)
    agree = {**env_ok(), "runs.kind": "baseline", "mutant": "none", "device_build.a.witness-field": "stock"}
    assert EV.check_environment(agree, RUN, INV).ok


def test_withheld_firmware_only_for_the_mutant_device_of_a_mutant_run():
    run = {**RUN, "kind": "mutant", "mutant_id": "M3"}
    env = {**env_ok(mutant="M3"), "fw_version.dev-a": "unavailable (MALFORMED: incomplete:86B)"}
    chk = EV.check_environment(env, run, INV)
    assert chk.ok and chk.withheld == {"fw_version.dev-a"}           # honest record, still not a valid version
    chk = EV.check_environment({**env, "fw_version.dev-b": "unavailable (MALFORMED: x)"}, run, INV)
    assert set(chk.problems) == {"fw_version.dev-b"} and chk.withheld == {"fw_version.dev-a", "fw_version.dev-b"}
    stock = EV.check_environment({**env_ok(mutant="M3"), "device_build.dev-a": "stock"}, run, INV).problems
    assert set(stock) == {"device_build.dev-a"} and "mutant:no-newline" in stock["device_build.dev-a"]


def test_offset_outside_the_gate_is_not_a_contradiction_for_an_unclean_run():
    env = {**env_ok(), "chrony.offset": "offset_s=-0.250000 delay_s=0.000324 samples=4/4 server=10.77.1.10",
           "runs.clean_env": "0"}
    assert EV.check_environment(env, {**RUN, "clean_env": 0}, INV).ok


# ---------------------------------------------------------------- independent packet recount

A, P = "10.77.2.11", 5021


def test_flow_packets_counts_both_directions_of_the_flow():
    frames = flow_frames(A, P, 40000, refused=True) + flow_frames(A, 5020, 51000)
    data = pcap_bytes(frames)
    assert EV.flow_packets(data, L.flow_filter(A, P)) == 2
    assert EV.flow_packets(data, L.flow_filter(A, P, 40000)) == 2
    assert EV.flow_packets(data, L.flow_filter(A, P, 40001)) == 0
    assert EV.flow_packets(data, L.flow_filter(A, 5020)) == 5
    assert EV.flow_packets(data, L.flow_filter(A, 5020, 41000)) == 0      # gateway polls are not the runner's flow
    assert EV.flow_packets(data, L.flow_filter("10.77.2.12", P)) == 0


def test_flow_packets_ignores_what_tcpdump_would_not_match():
    frames = [tcp_packet("10.77.1.10", A, 40000, P, proto=1),               # ICMP, not TCP
              tcp_packet("10.77.1.10", A, 40000, P, frag=5),                # non-first fragment: no ports
              tcp_packet("10.77.1.10", A, 40000, P, ethertype=b"\x81\x00")]  # VLAN-tagged: not 'tcp' to tcpdump
    assert EV.flow_packets(pcap_bytes(frames), L.flow_filter(A, P)) == 0


def test_flow_packets_reads_other_classic_pcap_layouts():
    frames = flow_frames(A, P, 40000, refused=True)
    assert EV.flow_packets(pcap_bytes(frames, endian=">"), L.flow_filter(A, P)) == 2
    sll = [b"\x00\x00\x00\x01\x00\x06" + f[6:12] + b"\x00\x00" + f[12:] for f in frames]   # 16-byte cooked header
    assert EV.flow_packets(pcap_bytes(sll, link=113), L.flow_filter(A, P)) == 2


@pytest.mark.parametrize("data,why", [
    (b"\x0a\x0d\x0d\x0a" + bytes(40), "not a classic pcap"),               # pcapng
    (b"\xd4\xc3\xb2\xa1", "shorter than a pcap header"),
    (pcap_bytes([], link=105), "unsupported link type 105"),
    (pcap_bytes(flow_frames(A, P, 40000, refused=True))[:-3], "truncated packet"),
])
def test_unverifiable_bytes_raise(data, why):
    with pytest.raises(EV.PcapError, match=why):
        EV.flow_packets(data, L.flow_filter(A, P))


def test_flow_packets_rejects_a_filter_outside_the_record_grammar():
    with pytest.raises(EV.PcapError):
        EV.flow_packets(pcap_bytes([]), "tcp port 5021 or icmp")


@pytest.mark.skipif(shutil.which("tcpdump") is None, reason="tcpdump not installed")
def test_flow_packets_agrees_with_tcpdump(tmp_path):
    """The recorder counted with tcpdump (runner/lab.count_packets); the acceptance recount must agree on the same
    bytes, for refused and established flows, with and without the ephemeral port."""
    frames = (flow_frames(A, P, 40000, refused=True) + flow_frames(A, 5020, 41000) + flow_frames(A, 5020, 51000)
              + flow_frames("10.77.2.12", 5020, 42000) + [tcp_packet("10.77.1.10", A, 40000, P, proto=1)])
    p = tmp_path / "c.pcap"
    p.write_bytes(pcap_bytes(frames))
    for bpf in (L.flow_filter(A, P), L.flow_filter(A, P, 40000), L.flow_filter(A, 5020), L.flow_filter(A, 5020, 41000),
                L.flow_filter(A, 5020, 51000), L.flow_filter("10.77.2.12", 5020), L.flow_filter("10.77.2.13", 5020)):
        assert EV.flow_packets(p.read_bytes(), bpf) == L.count_packets(p, bpf), bpf


def test_file_problem(tmp_path):
    p = tmp_path / "f.txt"
    p.write_bytes(b"evidence")
    sha = hashlib.sha256(b"evidence").hexdigest()
    assert EV.file_problem(tmp_path, "f.txt", sha, 8) is None
    assert EV.file_problem(tmp_path, "f.txt", sha, 9).startswith("differs")
    assert EV.file_problem(tmp_path, "f.txt", "0" * 64, 8).startswith("differs")
    assert EV.file_problem(tmp_path, "g.txt", sha, 8) == "missing"
