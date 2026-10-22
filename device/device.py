#!/usr/bin/env python3
"""Witness device simulator: one simulated networked environmental sensor.

Software simulation over real TCP (no hardware, no firmware). Implements
docs/protocol.md v1: newline-framed strict JSON on TCP, IDENTIFY / HEALTH / READ.
Runs as systemd template unit witness-device@<instance> on witness-field, one
process per device, each bound only to its own inventoried address.

Usage:
  device.py [--instance a] [--device-id dev-a --serial WIT-0001 --fw-version 1.0.0
            --bind 10.77.2.11 --port 5020 --model WSIM-1] [--run-dir DIR] [--mode-file PATH]
Identity/bind options default to WITNESS_* environment variables (systemd
EnvironmentFile=/etc/witness/device-%i.env).

Per-process state: READ `seq` starts at 1 and increments by 1 for every READ served,
shared across connections; `uptime_s` is monotonic time since process start;
temp_c/rh_pct are a deterministic function of seq (repeatable runs).

Controlled fault modes (runtime only): `normal`; F10 `malformed` (invalid JSON),
`truncated` (half a frame, then FIN), `wrong-id` (echoes id+1); F11 `close-after:N`
(after N responses on a connection, close it with FIN instead of answering the next
request) and `reset-after:N` (same, but abort with RST via SO_LINGER 0); F13
`clock-skew:+Ns` (READ ts shifted by N seconds) and `repeat-seq` (READ seq stops
increasing; ts stays current, so only the sequence rule is violated). The mode is
read on SIGHUP from --mode-file, which lives in the ROOT-owned control directory
/run/witness-fault/ (the device can read it, never write it, so root never writes
into a directory this process controls). The device confirms the mode in
<run-dir>/state.json (its own RuntimeDirectory). The unit's ExecStartPre deletes the
mode file as root, so a fresh process is always `normal`.

Mutant builds (brief section 7.4, device/mutants.py): `--mutant SPEC` (WITNESS_MUTANT) selects a
deliberately broken build for the whole process lifetime; state.json reports `build`.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import signal
import socket
import socketserver
import struct
import sys
import threading
import time
from datetime import datetime, timezone

try:                       # repo: device.mutants; installed: /usr/local/lib/witness/mutants.py
    from . import mutants
except ImportError:
    import mutants

MAX_FRAME = 4096
ID_MAX = 2147483647
COMMANDS = ("IDENTIFY", "HEALTH", "READ")
MODES = ("normal", "malformed", "truncated", "wrong-id", "repeat-seq")
# Parameterised modes; witness-faultctl validates the same grammar before writing a mode.
MODE_RE = re.compile(r"^(?:(close-after|reset-after):([1-9])|clock-skew:([+-])([1-9][0-9]{0,3})s)$")
IDLE_TIMEOUT_S = 30.0

log = logging.getLogger("witness-device")


def rfc3339_now(clock=time.time) -> str:
    t = clock()
    dt = datetime.fromtimestamp(t, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _reject_constant(name: str):
    raise ValueError(f"non-JSON constant {name}")


def _pairs_no_dupes(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError(f"duplicate key {k!r}")
        out[k] = v
    return out


def _enc(obj: dict) -> bytes:
    return (json.dumps(obj, separators=(",", ":"), allow_nan=False) + "\n").encode()


def valid_mode(mode: str) -> bool:
    m = MODE_RE.match(mode)
    return mode in MODES or (m is not None and (m.group(1) or int(m.group(4)) <= 3600))


def _mode_arg(mode: str, name: str) -> int | None:
    """N for close-after:N / reset-after:N, signed seconds for clock-skew; None otherwise."""
    m = MODE_RE.match(mode)
    if not m:
        return None
    if name in ("close-after", "reset-after"):
        return int(m.group(2)) if m.group(1) == name else None
    if name == "clock-skew" and m.group(3):
        return int(m.group(4)) * (1 if m.group(3) == "+" else -1)
    return None


class Device:
    """Protocol logic, independent of sockets (unit-testable)."""

    def __init__(self, device_id: str, serial: str, model: str, fw_version: str,
                 clock=time.time, mono=time.monotonic, mutant: "mutants.Mutant | None" = None, sleep=time.sleep):
        self.identity = {"device_id": device_id, "serial": serial, "model": model, "fw_version": fw_version}
        self._clock, self._mono, self._sleep = clock, mono, sleep
        self.mutant = mutant
        self._started = mono()
        self._lock = threading.Lock()
        self._seq = 0
        self.mode = "normal"
        self.mode_since = rfc3339_now(clock)
        base = int(serial[-4:]) if serial[-4:].isdigit() else 0
        self._temp0 = 21.0 + (base % 5)
        self._rh0 = 40.0 + (base % 7)

    # -- request parsing (device side is lenient only in what it reports, not in what it accepts)
    @staticmethod
    def parse_request(line: bytes):
        """One request frame without its \\n -> (id, cmd, None) or (id|None, None, error_code).
        Frame rules of docs/protocol.md section 2, the same ones the runner applies to responses
        (runner/classify.parse_frame): strict UTF-8 without BOM, no \\r anywhere, one JSON object, no
        NaN/Infinity, no duplicate keys, nothing after the object. A frame that breaks them is `bad_json`
        with id null: with a duplicate "id" or "cmd" there is no single request to answer."""
        if b"\r" in line or line.startswith(b"\xef\xbb\xbf"):
            return None, None, "bad_json"
        try:
            obj = json.loads(line.decode("utf-8"), parse_constant=_reject_constant, object_pairs_hook=_pairs_no_dupes)
        except (UnicodeDecodeError, ValueError, RecursionError):
            return None, None, "bad_json"
        if not isinstance(obj, dict):
            return None, None, "bad_json"
        rid = obj.get("id")
        rid = rid if type(rid) is int and 0 <= rid <= ID_MAX else None
        if rid is None or set(obj) != {"id", "cmd"} or type(obj["cmd"]) is not str:
            return rid, None, "bad_request"
        if obj["cmd"] not in COMMANDS:
            return rid, None, "unknown_cmd"
        return rid, obj["cmd"], None

    @property
    def build(self) -> str:
        return self.mutant.build if self.mutant else "stock"

    def respond(self, rid: int, cmd: str) -> dict:
        if cmd == "IDENTIFY":
            return {"id": rid, **(self.mutant.identity(self.identity) if self.mutant else self.identity)}
        if cmd == "HEALTH":
            return {"id": rid, "status": "ok", "uptime_s": round(self._mono() - self._started, 3), "sensor_ok": True}
        mode = self.mode
        skew = _mode_arg(mode, "clock-skew") or 0
        with self._lock:
            if mode != "repeat-seq" or self._seq == 0:
                self._seq += 1
            seq = self.mutant.seq(self._seq) if self.mutant else self._seq
            ts = rfc3339_now(lambda: self._clock() + skew)
        return {"id": rid, "seq": seq, "ts": ts,
                "temp_c": round(self._temp0 + 1.5 * math.sin(seq / 10.0), 2),
                "rh_pct": round(self._rh0 + 5.0 * math.cos(seq / 15.0), 2)}

    def handle_line(self, line: bytes, served: int = 0) -> tuple[bytes, str | None, str]:
        """One request frame (without \\n) -> (response bytes, close, log note).
        served = responses already sent on this connection. close is None (keep open),
        "fin" (graceful close after sending the bytes) or "rst" (abort: SO_LINGER 0)."""
        mut = self.mutant
        slept = mut.delay_s() if mut else 0.0
        if slept:
            self._sleep(slept)
        frame, close, note = self._handle_line(line, served)
        if mut:
            frame = mut.frame(frame)
            note += f" build={mut.build}" + (f" slept={slept}s" if slept else "")
        return frame, close, note

    def _handle_line(self, line: bytes, served: int) -> tuple[bytes, str | None, str]:
        rid, cmd, err = self.parse_request(line)
        if err:
            return _enc({"id": rid, "error": err}), None, f"error={err}"
        mode = self.mode
        for name, how in (("close-after", "fin"), ("reset-after", "rst")):
            n = _mode_arg(mode, name)
            if n is not None and served >= n:
                return b"", how, f"cmd={cmd} id={rid} mode={mode} served={served}: {how} instead of a response"
        resp = self.respond(rid, cmd)
        if self.mutant:
            resp = self.mutant.response(resp, cmd)
        if mode == "wrong-id":
            resp["id"] = rid + 1 if rid < ID_MAX else 0
        frame = _enc(resp)
        if mode == "malformed":
            # A trailing comma before the closing brace: invalid JSON, everything else intact.
            frame = frame[:-2] + b",}\n"
        elif mode == "truncated":
            return frame[: max(1, len(frame) // 2)], "fin", f"cmd={cmd} id={rid} mode=truncated"
        return frame, None, f"cmd={cmd} id={rid} mode={mode}"


def _lingering_close(sock, budget_s: float = 1.0) -> None:
    """Half-close, then discard unread request bytes (bounded). Closing a socket with
    unread data makes the kernel send RST instead of FIN, which can destroy the reply
    we just sent before the peer reads it (observed in tests/unit/test_device.py)."""
    try:
        sock.shutdown(socket.SHUT_WR)
        end = time.monotonic() + budget_s
        while (left := end - time.monotonic()) > 0:
            sock.settimeout(left)
            if not sock.recv(65536):
                break
    except OSError:
        pass


class _Handler(socketserver.BaseRequestHandler):
    server: "DeviceServer"

    def setup(self):
        self.server.track(self.request, True)
        self.peer = "%s:%d" % self.client_address[:2]
        log.info("conn open peer=%s", self.peer)

    def finish(self):
        self.server.track(self.request, False)

    def handle(self):
        dev, sock = self.server.device, self.request
        sock.settimeout(self.server.idle_timeout)
        buf = b""
        reason = "peer_closed"
        served = 0
        abort = False
        try:
            while not self.server.stopping:
                try:
                    chunk = sock.recv(MAX_FRAME)
                except socket.timeout:
                    reason = "idle_timeout"
                    return
                if not chunk:
                    return
                buf += chunk
                while True:
                    nl = buf.find(b"\n")
                    if nl == -1 and len(buf) < MAX_FRAME:
                        break
                    if nl == -1 or nl + 1 > MAX_FRAME:
                        sock.sendall(_enc({"id": None, "error": "frame_too_long"}))
                        reason = "frame_too_long"
                        _lingering_close(sock)
                        return
                    line, buf = buf[:nl], buf[nl + 1:]
                    out, close, note = dev.handle_line(line, served)
                    if out:
                        sock.sendall(out)
                        served += 1
                    log.info("req peer=%s %s bytes=%d", self.peer, note, len(out))
                    if close:
                        reason = f"fault_mode_close:{close}"
                        abort = close == "rst"
                        return
        except OSError as e:
            reason = f"os_error:{e.__class__.__name__}"
        finally:
            if abort:
                # F11 reset-after: SO_LINGER {on, 0} makes close() send RST and discard
                # queued data. shutdown() must NOT run first (it would send FIN).
                try:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                except OSError:
                    pass
                sock.close()        # socketserver's later shutdown/close of this socket are no-ops
            else:
                try:
                    sock.shutdown(socket.SHUT_WR)   # FIN after any bytes already queued
                except OSError:
                    pass
            log.info("conn close peer=%s reason=%s", self.peer, reason)


class DeviceServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, addr, device: Device, idle_timeout: float = IDLE_TIMEOUT_S):
        self.device, self.idle_timeout = device, idle_timeout
        self.stopping = False
        self._conns: set = set()
        self._conns_lock = threading.Lock()
        super().__init__(addr, _Handler)

    def track(self, sock, add: bool):
        with self._conns_lock:
            (self._conns.add if add else self._conns.discard)(sock)

    def close_all(self):
        with self._conns_lock:
            conns = list(self._conns)
        for s in conns:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def sd_notify(msg: str) -> None:
    path = os.environ.get("NOTIFY_SOCKET")
    if not path:
        return
    if path.startswith("@"):
        path = "\0" + path[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
        s.connect(path)
        s.sendall(msg.encode())


class ModeControl:
    """mode file -> device.mode on SIGHUP; <run-dir>/state.json confirms."""

    def __init__(self, device: Device, run_dir: str | None, started_at: str, mode_file: str | None = None):
        self.device, self.run_dir, self.started_at = device, run_dir, started_at
        self.mode_file = mode_file
        self.error = None

    def reload(self):
        if not self.mode_file:
            return
        path = self.mode_file
        try:
            with open(path, encoding="ascii") as f:
                want = f.read().strip()
        except FileNotFoundError:
            want = "normal"
        except (OSError, UnicodeDecodeError) as e:
            want, self.error = None, f"unreadable mode file: {e}"
        if want is not None and not valid_mode(want):
            self.error = f"unknown mode {want!r}; keeping {self.device.mode}"
            want = None
        if want is not None:
            self.error = None
            if want != self.device.mode:
                self.device.mode = want
                self.device.mode_since = rfc3339_now()
        if self.error:
            log.error("fault mode: %s", self.error)
        else:
            log.log(logging.INFO if self.device.mode == "normal" else logging.WARNING,
                    "fault mode now %s", self.device.mode)
        self.write_state()

    def write_state(self):
        if not self.run_dir:
            return
        state = {"pid": os.getpid(), "device_id": self.device.identity["device_id"],
                 "build": self.device.build, "mode": self.device.mode, "mode_since": self.device.mode_since,
                 "mode_error": self.error, "started_at": self.started_at}
        tmp = os.path.join(self.run_dir, ".state.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, os.path.join(self.run_dir, "state.json"))


def bind_with_wait(addr, device, wait_s: float) -> DeviceServer:
    """The address lives on dummy field0 (networkd); at boot it may appear after us."""
    deadline = time.monotonic() + wait_s
    while True:
        try:
            return DeviceServer(addr, device)
        except OSError as e:
            if e.errno != 99 or time.monotonic() > deadline:   # 99 = EADDRNOTAVAIL
                raise
            time.sleep(0.5)


def main(argv=None) -> int:
    env = os.environ.get
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--instance", default=env("WITNESS_INSTANCE", "x"))
    p.add_argument("--device-id", default=env("WITNESS_DEVICE_ID"))
    p.add_argument("--serial", default=env("WITNESS_SERIAL"))
    p.add_argument("--model", default=env("WITNESS_MODEL", "WSIM-1"))
    p.add_argument("--fw-version", default=env("WITNESS_FW_VERSION"))
    p.add_argument("--bind", default=env("WITNESS_BIND"))
    p.add_argument("--port", type=int, default=int(env("WITNESS_PORT", "5020")))
    p.add_argument("--run-dir", default=env("RUNTIME_DIRECTORY"))
    p.add_argument("--mode-file", default=env("WITNESS_MODE_FILE"))
    p.add_argument("--bind-wait", type=float, default=30.0)
    p.add_argument("--mutant", default=env("WITNESS_MUTANT") or None,
                   help="deliberately broken build (device/mutants.py); lab use only")
    a = p.parse_args(argv)
    missing = [k for k in ("device_id", "serial", "fw_version", "bind") if not getattr(a, k)]
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
    if missing:
        log.error("missing identity/bind settings: %s", ", ".join(missing))
        return 2
    if a.bind in ("0.0.0.0", "", "::"):
        log.error("refusing wildcard bind; each device binds only its own address")
        return 2

    if a.mutant is not None and not mutants.valid_mutant(a.mutant):
        log.error("unknown mutant %r", a.mutant)
        return 2
    device = Device(a.device_id, a.serial, a.model, a.fw_version,
                    mutant=mutants.Mutant(a.mutant) if a.mutant else None)
    if device.mutant:
        log.warning("MUTANT BUILD %s: deliberately broken device (brief section 7.4); not a commissionable build",
                    device.mutant.spec)
    started_at = rfc3339_now()
    srv = bind_with_wait((a.bind, a.port), device, a.bind_wait)
    ctl = ModeControl(device, a.run_dir, started_at, a.mode_file)
    ctl.reload()   # a fresh process is always normal unless the run dir already holds a mode

    def on_term(signum, _frame):
        if srv.stopping:
            return
        srv.stopping = True
        log.info("signal %s: graceful shutdown", signal.Signals(signum).name)
        threading.Thread(target=srv.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)
    signal.signal(signal.SIGHUP, lambda *_: ctl.reload())
    log.info("listening %s:%d device_id=%s serial=%s fw=%s build=%s pid=%d", a.bind, a.port,
             a.device_id, a.serial, a.fw_version, device.build, os.getpid())
    sd_notify("READY=1\nSTATUS=listening %s:%d" % (a.bind, a.port))
    try:
        srv.serve_forever(poll_interval=0.2)
    finally:
        srv.server_close()        # stop accepting: new SYNs now get RST
        srv.close_all()           # in-flight connections see FIN
        log.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
