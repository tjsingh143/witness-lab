"""Loopback fake servers for unit tests. These prove runner logic only; they are not
evidence of VM-to-VM behaviour (that is tests/live, run on witness-ctl)."""
import socket
import struct
import threading

import pytest


class FakeServer:
    """Accepts connections on 127.0.0.1 and runs handler(conn, request_bytes) per connection."""

    def __init__(self, handler):
        self.handler = handler
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.stop = threading.Event()
        self.t = threading.Thread(target=self._loop, daemon=True)
        self.t.start()

    def _loop(self):
        self.sock.settimeout(0.1)
        while not self.stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except (socket.timeout, OSError):
                continue
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        try:
            conn.settimeout(5)
            buf = b""
            while b"\n" not in buf:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
            self.handler(conn, buf)
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def close(self):
        self.stop.set()
        self.sock.close()


def rst_close(conn):
    """Close with SO_LINGER 0: the kernel sends RST instead of FIN."""
    conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    conn.close()


@pytest.fixture
def fake():
    servers = []

    def make(handler):
        s = FakeServer(handler)
        servers.append(s)
        return s

    yield make
    for s in servers:
        s.close()
