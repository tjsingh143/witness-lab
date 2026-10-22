"""Exact-PID live interruption and mature capture/dead-man observation on ctl.

Separate experiment store. No changes to historical DB, production source or host
networking. Retains real active-fault/capture proof before signal, and recovery
observations before any emergency reset. Outer caller must enforce a 250 s bound.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time

sys.path.insert(0, '/opt/witness-lab')
from runner import lab as L
from scripts.lib import inventory

sig_name, fault, root_arg = sys.argv[1:]
assert sig_name in ('TERM', 'KILL') and fault in ('f2', 'f5')
root = Path(root_arg)
root.mkdir(parents=True, exist_ok=True)
inv = inventory.load('/opt/witness-lab/inventory.yaml')
L.assert_ctl_vm(inv)
field = L.FieldCtl('10.77.1.20')
events = []
proc = None
passed = False


def emit(kind, **kw):
    event = dict(kind=kind, mono=time.monotonic(), wall=time.time(), **kw)
    events.append(event)
    print(json.dumps(event), flush=True)
    (root/f'{sig_name}-{fault}-events.json').write_text(json.dumps(events, indent=2)+'\n')


def local_state():
    procs = L.run(['ps', '-eo', 'pid,ppid,args']).stdout.splitlines()
    caps = [x.strip() for x in procs if 'tcpdump -i lab0' in x and str(root/'evidence') in x]
    route = L.run(['ip', '-4', 'route', 'show', '10.77.2.0/24']).stdout.strip()
    timer = L.deadman_armed()
    return dict(route=route, ctl_timer=timer, ctl_captures=caps)


try:
    ctl_pf, fld_pf = L.preflight_local(), field('preflight', timeout=100)
    assert ctl_pf['green'] and fld_pf['green'], (ctl_pf, fld_pf)
    emit('preflight_green', source=L.source_info())
    selector = 'f2_sigstop' if fault=='f2' else 'test_gateway_detects_route_loss'
    cmd = ['python3', '-m', 'pytest', 'tests/live', '--live', '-q', '-rA', '-p', 'no:cacheprovider',
           '-m', 'fault', '-k', selector, '--db', str(root/'witness.db'), '--evidence-root', str(root/'evidence'),
           '--run-notes', f'external reproduction interrupt {sig_name} {fault}']
    with (root/f'{sig_name}-{fault}-pytest.log').open('x') as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                cwd='/opt/witness-lab', start_new_session=True)
        emit('runner_started', pid=proc.pid, argv=cmd)
        end = time.monotonic()+45
        while time.monotonic()<end:
            assert proc.poll() is None, 'runner exited before signal'
            local = local_state()
            st = field('status')
            active = (any(x.startswith('sigstop:') for x in st['active_faults']) if fault=='f2'
                      else not local['route'] and local['ctl_timer'])
            if active and local['ctl_captures'] and st['capture_active']:
                emit('active_before_signal', field=st, local=local)
                break
            time.sleep(0.05)
        else:
            raise AssertionError('never observed intended active fault and both mature captures')
        sent = time.monotonic()
        os.kill(proc.pid, getattr(signal, 'SIG'+sig_name))
        emit('signal_sent', signal=sig_name, pid=proc.pid)
        rc = proc.wait(timeout=60)
        emit('runner_exited', rc=rc, elapsed_since_signal=time.monotonic()-sent)
        assert (rc==-9 if sig_name=='KILL' else rc!=0), rc
        end = sent+160
        last = None
        while time.monotonic()<end:
            st, local = field('status'), local_state()
            state = dict(field=st, local=local)
            if state != last:
                emit('recovery_observation', elapsed_since_signal=time.monotonic()-sent, **state)
                last = state
            if (not st['active_faults'] and not st['deadman_armed'] and not st['capture_active']
                    and not local['ctl_timer'] and local['route'].startswith('10.77.2.0/24 via 10.77.1.20 dev lab0')
                    and not local['ctl_captures']):
                break
            time.sleep(0.5)
        else:
            raise AssertionError('natural recovery/capture expiry did not complete within 160s')
    pf1, pf2 = L.preflight_local(), field('preflight', timeout=100)
    emit('postflight', ctl=pf1, field=pf2)
    assert pf1['green'] and pf2['green']
    # RuntimeMaxSec leaves the expired field capture in its scratch directory.
    # Retrieve it NOW, before a later capture start discards scratch files.
    if sig_name == 'KILL':
        with sqlite3.connect(root/'witness.db') as conn:
            run_id = conn.execute('SELECT max(run_id) FROM runs').fetchone()[0]
        case_id = 'FT-F2-HUNG' if fault=='f2' else 'GW-F5-UNREACHABLE'
        orphan = field('capture', 'stop', f'run{run_id}-{case_id}-dev-a', timeout=40)
        assert orphan.get('found') and orphan.get('pcap_b64'), 'orphan capture evidence missing'
        raw = base64.b64decode(orphan['pcap_b64'])
        path = root/f'{sig_name}-{fault}-orphan-field.pcap'
        path.write_bytes(raw)
        path.with_suffix('.txt').write_text(orphan.get('text','')+'\n'+orphan.get('tcpdump',''))
        emit('orphan_capture_retained', path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    emit('PASS', elapsed_since_signal=time.monotonic()-sent)
    passed = True
finally:
    if proc is not None and proc.poll() is None:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)
        emit('emergency_runner_kill')
    if not passed:
        emit('emergency_reset', field=field('reset', timeout=150), ctl=L.reset_local())
    emit('journals', ctl=L.run(['journalctl','-u','witness-ctl-fault-deadman','--since','-6min','--no-pager','-o','short-iso-precise']).stdout,
         field=field('journal','a', str(time.time()-360)))
