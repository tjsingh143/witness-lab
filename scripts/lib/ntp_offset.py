#!/usr/bin/env python3
"""Measure this host's clock offset against an NTP server (witness-ctl's chronyd).

Plain SNTP (RFC 4330) four-timestamp exchange, independent of the local chronyd's
own model: offset = ((t2 - t1) + (t3 - t4)) / 2, delay = (t4 - t1) - (t3 - t2).
Positive offset = the SERVER is ahead of this host. Of N bounded queries the
minimum-delay sample is reported (least queueing error).

Usage: ntp_offset.py SERVER [--samples N] [--timeout S]
Prints: offset_s=<float> delay_s=<float> samples=<ok>/<N> server=<addr>
Exit 0 on at least one valid sample, 1 otherwise.
"""
from __future__ import annotations

import argparse
import socket
import struct
import sys
import time

NTP_EPOCH_DELTA = 2208988800  # seconds from 1900-01-01 to 1970-01-01


def _to_ntp(t: float) -> bytes:
    secs = int(t) + NTP_EPOCH_DELTA
    frac = int((t % 1) * 2**32)
    return struct.pack("!II", secs, frac)


def _from_ntp(b: bytes) -> float:
    secs, frac = struct.unpack("!II", b)
    return secs - NTP_EPOCH_DELTA + frac / 2**32


def query(server: str, timeout: float) -> tuple[float, float] | None:
    pkt = bytearray(48)
    pkt[0] = (0 << 6) | (4 << 3) | 3  # LI=0, VN=4, mode=3 (client)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        t1 = time.time()
        pkt[40:48] = _to_ntp(t1)  # transmit timestamp, echoed back as originate
        s.sendto(bytes(pkt), (server, 123))
        try:
            data, _ = s.recvfrom(512)
        except socket.timeout:
            return None
        t4 = time.time()
    if len(data) < 48 or data[0] & 0x7 != 4 or data[24:32] != bytes(pkt[40:48]):
        return None  # not a server reply to THIS request
    if data[1] == 0:
        return None  # stratum 0 = kiss-o'-death / unsynchronised
    t2, t3 = _from_ntp(data[32:40]), _from_ntp(data[40:48])
    return ((t2 - t1) + (t3 - t4)) / 2, (t4 - t1) - (t3 - t2)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("server")
    ap.add_argument("--samples", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=1.0)
    a = ap.parse_args(argv)
    got = []
    for i in range(a.samples):
        r = query(a.server, a.timeout)
        if r is not None:
            got.append(r)
        if i + 1 < a.samples:
            time.sleep(0.2)
    if not got:
        print(f"offset_s=nan delay_s=nan samples=0/{a.samples} server={a.server}")
        return 1
    off, delay = min(got, key=lambda r: r[1])
    print(f"offset_s={off:+.6f} delay_s={delay:.6f} samples={len(got)}/{a.samples} server={a.server}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
