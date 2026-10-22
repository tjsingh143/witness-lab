#!/usr/bin/env python3
"""F-05 (independent audit) probe: send request frames the device contract forbids, and controls, to BOTH real
devices from witness-ctl, with a bounded lab0 capture. Read-only for the lab: each stimulus is one short TCP
connection to a device's inventoried address:port (2 s timeouts); no fault, no mode, no VM state is changed.

Run on witness-ctl as root (the Capture class runs tcpdump), from the Mac:
    env LIMA_HOME=$PWD/.lima.nosync limactl shell --workdir /opt/witness-lab witness-ctl -- \
        sudo env PYTHONDONTWRITEBYTECODE=1 timeout 30 python3 scripts/remediation/vm_protocol_probe.py OUT_PREFIX
Prints one JSON line per stimulus (expected per docs/protocol.md sections 2 and 4.1 vs the actual reply) and a
summary line; exit 0 when every reply matches the contract, 1 otherwise. The first six stimuli are the
independent audit's (protocol-vm.log); the rest extend the same contract rules.
"""
import json
import pathlib
import socket
import sys
import time

sys.path.insert(0, "/opt/witness-lab")
from runner.lab import Capture, assert_ctl_vm  # noqa: E402
from scripts.lib.inventory import load  # noqa: E402

BAD_JSON = {"id": None, "error": "bad_json"}
# (name, frame bytes incl. the terminating \n, expected reply: "identify" = a normal IDENTIFY answer with id 1,
#  or the exact error object). \n and \r are real bytes, not JSON escapes.
STIMULI = [
    ("normal", b'{"id":1,"cmd":"IDENTIFY"}\n', "identify"),
    ("duplicate_id", b'{"id":1,"id":2,"cmd":"IDENTIFY"}\n', BAD_JSON),
    ("duplicate_cmd", b'{"id":1,"cmd":"READ","cmd":"IDENTIFY"}\n', BAD_JSON),
    ("carriage_return", b'{"id":1,\r"cmd":"IDENTIFY"}\n', BAD_JSON),
    ("invalid_utf8", b'{"id":1,"cmd":"\xff"}\n', BAD_JSON),
    ("oversize", b"x" * 4096 + b"\n", {"id": None, "error": "frame_too_long"}),
    # further contract cases (protocol.md section 2 rule 4, section 3, section 4.1)
    ("crlf_terminator", b'{"id":1,"cmd":"IDENTIFY"}\r\n', BAD_JSON),
    ("duplicate_same_value", b'{"id":1,"id":1,"cmd":"IDENTIFY"}\n', BAD_JSON),
    ("utf8_bom", b'\xef\xbb\xbf{"id":1,"cmd":"IDENTIFY"}\n', BAD_JSON),
    ("nan_constant", b'{"id":NaN,"cmd":"IDENTIFY"}\n', BAD_JSON),
    ("trailing_data", b'{"id":1,"cmd":"IDENTIFY"}{}\n', BAD_JSON),
    ("empty_frame", b"\n", BAD_JSON),
    ("tab_whitespace_ok", b'{"id":1,\t"cmd":"IDENTIFY"}\n', "identify"),
    ("unknown_key", b'{"id":1,"cmd":"IDENTIFY","x":1}\n', {"id": 1, "error": "bad_request"}),
    ("unknown_cmd", b'{"id":1,"cmd":"RESET"}\n', {"id": 1, "error": "unknown_cmd"}),
]


def main(prefix: str) -> int:
    inv = load("/opt/witness-lab/inventory.yaml")
    assert_ctl_vm(inv)
    cap = Capture(pathlib.Path(prefix + ".pcap")).start()
    bad = 0
    try:
        for dev in inv["devices"]:
            want_ident = {"id": 1, "device_id": dev["device_id"], "serial": dev["serial"], "model": "WSIM-1",
                          "fw_version": dev["fw_version"]}
            for name, frame, want in STIMULI:
                with socket.create_connection((dev["hostname"], dev["port"]), timeout=2) as s:
                    s.settimeout(2)
                    s.sendall(frame)
                    buf = b""
                    while b"\n" not in buf and len(buf) < 4096:
                        x = s.recv(4096 - len(buf))
                        if not x:
                            break
                        buf += x
                    lport = s.getsockname()[1]
                try:
                    got = json.loads(buf)
                except ValueError:
                    got = None
                exp = want_ident if want == "identify" else want
                ok = got == exp
                bad += not ok
                print(json.dumps({"at": round(time.time(), 6), "host": dev["hostname"], "local_port": lport,
                                  "stimulus": name, "frame_hex": frame[:64].hex(), "expected": exp,
                                  "reply": buf.decode(errors="replace").strip(), "match": ok}), flush=True)
    finally:
        print("CAPTURE", cap.stop(), flush=True)
    n = len(STIMULI) * len(inv["devices"])
    print(json.dumps({"stimuli": n, "matching_contract": n - bad, "violations": bad}), flush=True)
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/witness-remediation-protocol"))
