"""Audit-only live F12/GW delay probe. Forward real API bytes unchanged on ctl loopback.

Does not alter the gateway, its pollers, guest routes or production source. Pytest's
ordinary fixtures perform the real VM fault and cleanup; separate DB for each run.
"""
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, '/opt/witness-lab')
import pytest
from runner import lab as L
from scripts.lib import inventory

delay = float(sys.argv[1])
body_delay = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0
target, root = sys.argv[2], Path(sys.argv[3])
root.mkdir(parents=True, exist_ok=True)
events = []
L.assert_ctl_vm(inventory.load('/opt/witness-lab/inventory.yaml'))


def event(kind, **kw):
    events.append(dict(kind=kind, mono=time.monotonic(), wall=time.time(), **kw))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        c = http.client.HTTPConnection('127.0.0.1', 8080, timeout=2)
        t0 = time.monotonic()
        try:
            c.request('GET', self.path)
            r = c.getresponse()
            raw = r.read()
            event('upstream_response', path=self.path, status=r.status, sha256=hashlib.sha256(raw).hexdigest(),
                  bytes=len(raw), upstream_elapsed=time.monotonic()-t0, delay_s=delay)
            time.sleep(delay)
            self.send_response(r.status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.flush()
            time.sleep(body_delay)
            self.wfile.write(raw)
            event('response_delivered', path=self.path)
        except (BrokenPipeError, ConnectionResetError):
            event('client_closed', path=self.path)
        finally:
            c.close()

    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
server.daemon_threads = True
worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
worker.start()


class Probe:
    @pytest.hookimpl(hookwrapper=True)
    def pytest_fixture_setup(self, fixturedef, request):
        outcome = yield
        if fixturedef.argname == 'lab':
            lab = outcome.get_result()
            lab.gw = L.Gateway(server.server_address)
            event('proxy_attached', addr=server.server_address, run_id=lab.run_id)

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_setup(self, item):
        event('setup_start', node=item.nodeid)
        outcome = yield
        event('setup_end', exception=str(outcome.excinfo))

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_call(self, item):
        event('body_start', node=item.nodeid)
        outcome = yield
        event('body_end', exception=str(outcome.excinfo))

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_teardown(self, item):
        event('teardown_start', node=item.nodeid)
        yield
        event('teardown_end', node=item.nodeid)


try:
    rc = pytest.main(['tests/live/test_gateway_cases.py::' + target, '--live', '-q', '-rA',
                      '-p', 'no:cacheprovider', '--db', str(root/'witness.db'),
                      '--evidence-root', str(root/'evidence'), '--run-notes', f'external reproduction deadline probe API delay={delay}'],
                     plugins=[Probe()])
finally:
    server.shutdown()
    server.server_close()
    worker.join(timeout=3)
    (root/'probe.json').write_text(json.dumps(dict(delay_s=delay, body_delay_s=body_delay, events=events), indent=2)+'\n')
    starts = [x['mono'] for x in events if x['kind']=='body_start']
    ends = [x['mono'] for x in events if x['kind']=='body_end']
    print('PROBE_BODY_SECONDS', ends[0]-starts[0] if starts and ends else None)
sys.exit(int(rc))
