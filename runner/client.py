"""Strict, bounded TCP client for the Witness device protocol (docs/protocol.md v1).

Records facts, never judges: every call returns an Observation (runner/classify.py)
describing what happened at each stage, and classification is a separate step.
Every blocking step has a bound: resolve 1.0 s (getaddrinfo in a helper thread),
connect 1.0 s, read 2.0 s from the request being sent, 4.0 s per attempt overall.
A frame is read only up to the first \\n or MAX_FRAME bytes, never beyond.
An optional absolute case deadline (time.monotonic() value, runner/cases.py) clamps every
one of those steps to the time the case has left; a step it cuts short, or that cannot
start, is marked `deadline_hit="case"` (unclassifiable: the device was not at fault).
"""
from __future__ import annotations

import errno as _errno
import json
import socket
import threading
import time
from dataclasses import dataclass
from typing import Callable

from runner.classify import (ATTEMPT_DEADLINE_S, CONNECT_TIMEOUT_S, MAX_FRAME, READ_TIMEOUT_S,
                             RESET_ERRNOS, RESOLVE_TIMEOUT_S, Observation)


@dataclass(frozen=True)
class Deadlines:
    resolve_s: float = RESOLVE_TIMEOUT_S
    connect_s: float = CONNECT_TIMEOUT_S
    read_s: float = READ_TIMEOUT_S
    attempt_s: float = ATTEMPT_DEADLINE_S


Resolver = Callable[[str, int], list]


def _default_resolver(host: str, port: int) -> list:
    return socket.getaddrinfo(host, port, family=socket.AF_INET, type=socket.SOCK_STREAM)


def resolve(host: str, port: int, timeout: float, resolver: Resolver = _default_resolver):
    """Return (ipv4 address | None, error | None, elapsed_ms). Bounded by `timeout`:
    getaddrinfo has no timeout of its own, so it runs in a daemon thread."""
    box: dict = {}

    def work():
        try:
            box["res"] = resolver(host, port)
        except Exception as e:  # gaierror, UnicodeError, ... are all "did not resolve"
            box["err"] = f"{type(e).__name__}:{getattr(e, 'errno', '')}"

    t0 = time.monotonic()
    th = threading.Thread(target=work, name=f"resolve-{host}", daemon=True)
    th.start()
    th.join(timeout)
    ms = (time.monotonic() - t0) * 1000
    if th.is_alive():
        return None, "timeout", ms
    if "err" in box:
        return None, box["err"], ms
    for fam, _, _, _, sa in box.get("res") or []:
        if fam == socket.AF_INET:
            return sa[0], None, ms
    return None, "no_ipv4_address", ms


class Connection:
    """One TCP connection carrying sequential exchanges (no pipelining).

    open() performs resolve + connect and returns None on success or a failed
    Observation for the first command. exchange() sends one request and reads one frame.
    """

    def __init__(self, host: str, port: int, deadlines: Deadlines = Deadlines(),
                 resolver: Resolver = _default_resolver,
                 sock_factory: Callable[[], socket.socket] | None = None,
                 case_deadline: float | None = None):
        self.host, self.port, self.dl = host, port, deadlines
        self.case_deadline = case_deadline       # absolute time.monotonic(); None = no case bound
        self._resolver = resolver
        self._sock_factory = sock_factory or (lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM))
        self.sock: socket.socket | None = None
        self.addr: str | None = None
        self.next_id = 1
        self._buf = b""
        self._t0_mono: float | None = None
        self._t0_wall: float | None = None
        self._connect_start: float | None = None
        self.resolve_ms: float | None = None
        self.connect_ms: float | None = None
        self.local_port: int | None = None
        self._exchanges = 0
        self.dead = False

    def case_left(self) -> float | None:
        """Seconds the case has left (may be <= 0), or None without a case deadline."""
        return None if self.case_deadline is None else self.case_deadline - time.monotonic()

    def _bound(self, own_s: float) -> tuple[float, bool]:
        """(timeout to use, True if the case deadline rather than the stage's own bound sets it)."""
        left = self.case_left()
        if left is not None and left < own_s:
            return max(0.001, left), True
        return max(0.001, own_s), False

    # -- setup
    def open(self, first_cmd: str) -> Observation | None:
        self._t0_mono, self._t0_wall = time.monotonic(), time.time()
        left = self.case_left()
        if left is not None and left <= 0:
            return self._fail("resolve", first_cmd, "not_started", deadline_hit="case")
        resolve_s, by_case = self._bound(self.dl.resolve_s)
        addr, err, self.resolve_ms = resolve(self.host, self.port, resolve_s, self._resolver)
        if addr is None:
            if err == "timeout" and by_case:
                return self._fail("resolve", first_cmd, "timeout", deadline_hit="case")
            return self._fail("resolve", first_cmd, err)
        self.addr = addr
        s = self._sock_factory()
        remaining = self.dl.attempt_s - (time.monotonic() - self._t0_mono)
        connect_s, by_case = self._bound(min(self.dl.connect_s, remaining))
        s.settimeout(connect_s)
        c0 = time.monotonic()
        try:
            s.connect((addr, self.port))
        except (socket.timeout, TimeoutError):
            self.connect_ms = (time.monotonic() - c0) * 1000
            s.close()
            return self._fail("connect", first_cmd, "timeout", deadline_hit="case" if by_case else None)
        except OSError as e:
            self.connect_ms = (time.monotonic() - c0) * 1000
            s.close()
            return self._fail("connect", first_cmd, _errno.errorcode.get(e.errno, type(e).__name__), e.errno)
        self.connect_ms = (time.monotonic() - c0) * 1000
        self._connect_start = c0   # latency of the first exchange is measured from here
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        try:
            self.local_port = s.getsockname()[1]
        except OSError:
            self.local_port = None
        self.sock = s
        return None

    def _fail(self, stage, cmd, err, eno=None, deadline_hit: str | None = None) -> Observation:
        self.dead = True
        return Observation(host=self.host, port=self.port, cmd=cmd, req_id=self.next_id,
                           addr=self.addr, local_port=self.local_port, stage_failed=stage, error=err, errno=eno,
                           t_start_wall=self._t0_wall, resolve_ms=self.resolve_ms,
                           connect_ms=self.connect_ms, deadline_hit=deadline_hit,
                           duration_ms=(time.monotonic() - self._t0_mono) * 1000)

    # -- exchange
    def exchange(self, cmd: str, read_s: float | None = None) -> Observation:
        """read_s (optional) tightens this exchange's read deadline below dl.read_s, e.g. so
        several exchanges share one overall budget (the gateway's per-poll deadline)."""
        if self.sock is None:
            raise RuntimeError("exchange() on a connection that is not open")
        first = self._exchanges == 0
        self._exchanges += 1
        req_id = self.next_id
        self.next_id += 1
        obs = Observation(host=self.host, port=self.port, cmd=cmd, req_id=req_id, addr=self.addr,
                          local_port=self.local_port, first_on_connection=first,
                          t_start_wall=self._t0_wall if first else time.time(),
                          resolve_ms=self.resolve_ms if first else None,
                          connect_ms=self.connect_ms if first else None)
        x0 = time.monotonic()
        left = self.case_left()
        if left is not None and left <= 0:
            # the case has no time left: the request is not sent at all
            obs.stage_failed, obs.error, obs.deadline_hit = "send", "not_started", "case"
            self.dead = True
            return self._finish(obs, x0)
        frame = (json.dumps({"id": req_id, "cmd": cmd}, separators=(",", ":")) + "\n").encode()
        obs.t_send_wall = time.time()
        sent_mono = time.monotonic()
        # Overall attempt bound applies to the first exchange (resolve+connect+read).
        read_s = self.dl.read_s if read_s is None else min(self.dl.read_s, read_s)
        if first:
            read_s = min(read_s, self.dl.attempt_s - (sent_mono - self._t0_mono))
        read_s, by_case = self._bound(read_s)
        deadline = sent_mono + read_s
        try:
            self.sock.settimeout(max(0.001, deadline - time.monotonic()))
            self.sock.sendall(frame)
        except (socket.timeout, TimeoutError):
            obs.stage_failed, obs.error = "send", "timeout"
            obs.deadline_hit = "case" if by_case else None
            self.dead = True
            return self._finish(obs, x0)
        except OSError as e:
            obs.stage_failed, obs.error, obs.errno = "send", _errno.errorcode.get(e.errno, type(e).__name__), e.errno
            self.dead = True
            return self._finish(obs, x0)
        buf = self._buf
        while True:
            nl = buf.find(b"\n", 0, MAX_FRAME)
            if nl != -1:
                obs.data, self._buf = buf[:nl + 1], buf[nl + 1:]
                obs.end = "newline"
                obs.t_recv_wall = time.time()
                done = time.monotonic()
                obs.response_ms = (done - sent_mono) * 1000
                obs.latency_ms = (done - self._connect_start) * 1000 if first else obs.response_ms
                break
            if len(buf) >= MAX_FRAME:
                obs.data, obs.end = buf[:MAX_FRAME], "oversize"
                self.dead = True
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                obs.data, obs.end = buf, "timeout"
                obs.deadline_hit = "case" if by_case else None
                self.dead = True
                break
            try:
                self.sock.settimeout(remaining)
                chunk = self.sock.recv(MAX_FRAME - len(buf))
            except (socket.timeout, TimeoutError):
                obs.data, obs.end = buf, "timeout"
                obs.deadline_hit = "case" if by_case else None
                self.dead = True
                break
            except OSError as e:
                obs.data = buf
                obs.errno, obs.error = e.errno, _errno.errorcode.get(e.errno, type(e).__name__)
                obs.end = "reset" if e.errno in RESET_ERRNOS else "error"
                self.dead = True
                break
            if not chunk:
                obs.data, obs.end = buf, "eof"
                self.dead = True
                break
            buf += chunk
        return self._finish(obs, x0)

    def _finish(self, obs: Observation, x0: float) -> Observation:
        obs.duration_ms = (time.monotonic() - (self._t0_mono if obs.first_on_connection else x0)) * 1000
        return obs

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None


def single(host: str, port: int, cmd: str, deadlines: Deadlines = Deadlines(),
           resolver: Resolver = _default_resolver, sock_factory=None,
           case_deadline: float | None = None) -> Observation:
    """One fresh connection, one exchange, closed afterwards."""
    conn = Connection(host, port, deadlines, resolver, sock_factory, case_deadline)
    try:
        failed = conn.open(cmd)
        return failed if failed is not None else conn.exchange(cmd)
    finally:
        conn.close()
