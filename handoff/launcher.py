#!/usr/bin/env python3
"""Deterministic, serial recipient coordinator. Python stdlib only; no AI or host pip."""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import signal
import sqlite3
import subprocess
import sys
import tarfile
import time
import uuid
import zipfile

GIB = 1024**3
REVISION = 'f09aa6322e5b8d923b9219b5f90ba32f50b17c0a'
VMS = ('witness-ctl', 'witness-field')
GOLDENS = tuple(v + '-golden' for v in VMS)
GUEST = '/opt/witness-lab'
STORE = '/var/lib/witness/reproduction'
LIMA_URL = 'https://github.com/lima-vm/lima/releases/download/v2.2.0/lima-2.2.0-Darwin-arm64.tar.gz'
LIMA_SHA = 'bbdef91774885a0d05f7b048c4eb89ae2bcf3a0c252ae7ca7934e63df76d93c3'
# The dated Canonical URL now redirects to an HTTP archive. This is the same
# official archive bucket through its TLS S3 endpoint, with identical pinned bytes.
IMAGE_URL = 'https://s3.amazonaws.com/cloud-images-archive.ubuntu.com/releases/noble/release-20260705/ubuntu-24.04-server-cloudimg-arm64.img'
IMAGE_SHA = '7df0201546f75b8bcc1044594c806c35749421ad3c9bc1be2a3ab806cfae39cc'


class Blocked(RuntimeError):
    pass


class Failed(RuntimeError):
    pass


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''):
            h.update(b)
    return h.hexdigest()


def save(path, data):
    path = Path(path)
    tmp = path.with_name(path.name + '.new')
    with tmp.open('w') as f:
        json.dump(data, f, indent=2)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def contained(root, path):
    root, path = Path(root).resolve(), Path(path)
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise Failed('Escaping path or symlink: ' + str(path))
    return path


def verify_package(package):
    package = Path(package).resolve()
    expected = {}
    for line in (package/'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        p = Path(name)
        if p.is_absolute() or '..' in p.parts or name in expected or not re.fullmatch('[0-9a-f]{64}', digest):
            raise Failed('Malformed checksum manifest')
        expected[name] = digest
        file = contained(package, package/p)
        if not file.is_file() or sha(file) != digest:
            raise Failed('Package integrity failed: ' + name)
    actual = set()
    for p in package.rglob('*'):
        contained(package, p)
        if p.is_file() and p.name != 'SHA256SUMS':
            actual.add(p.relative_to(package).as_posix())
    if actual != set(expected):
        raise Failed('Unexpected or missing files in package')
    manifest = json.loads((package/'SOURCE_MANIFEST.json').read_text())
    if manifest['original_commit'] != REVISION:
        raise Failed('Unexpected source revision')
    for entry in manifest['files']:
        if sha(package/'source'/entry['path']) != entry['export_sha256']:
            raise Failed('Source content mismatch: '+entry['path'])
    return sha(package/'SOURCE_MANIFEST.json')


def resource_problem(sample, *, initial=False, allocation=0, swap_initial=None):
    if sample['ram_bytes'] < 16*GIB:
        return 'at least 16 GiB RAM required; lower resource execution is not qualified'
    # Stop at 12 GiB to preserve the absolute 10 GiB floor during bounded shutdown.
    need = max(40*GIB if initial else 12*GIB, allocation + 14*GIB if allocation else 0)
    if sample['free_bytes'] < need:
        return f"free disk {sample['free_bytes']/GIB:.2f} GiB < required {need/GIB:.2f} GiB"
    if sample['pressure'] > 2:
        return 'critical memory pressure'
    if sample['swap_mib'] > 4096:
        return 'swap usage exceeds 4 GiB'
    if swap_initial is not None and sample['swap_mib'] - swap_initial > 1024:
        return 'swap grew by more than 1 GiB; close workloads before resuming'
    return None


def route_conflicts(text):
    lab = [ipaddress.ip_network(f'10.77.{n}.0/24') for n in range(3)]
    found = []
    for line in text.splitlines():
        parts = line.split()
        if not parts or parts[0] in ('default', 'Destination', 'Internet:', 'Routing'):
            continue
        dest = parts[0]
        try:
            address, _, prefix = dest.partition('/')
            if not re.fullmatch(r'[0-9.]+', address):
                continue
            octets = address.split('.')
            if len(octets) < 4:
                address += '.0'*(4-len(octets))
                prefix = prefix or str(8*len(octets))
            net = ipaddress.ip_network(address + '/' + (prefix or '32'), strict=False)
            if net.prefixlen and any(net.overlaps(n) for n in lab):
                found.append(line)
        except ValueError:
            continue
    return found


def claim_work(work, manifest_hash):
    work = Path(work).absolute()
    if work.is_symlink():
        raise Blocked('Work directory is a symlink')
    if work.exists() and not (work/'.witness-owner.json').is_file():
        raise Blocked('Existing work directory has no Witness ownership marker; nothing overwritten')
    work.mkdir(mode=0o700, parents=False, exist_ok=True)
    marker = work/'.witness-owner.json'
    if marker.exists():
        contained(work, marker)
        owner = json.loads(marker.read_text())
        if owner.get('manifest') != manifest_hash or owner.get('revision') != REVISION:
            raise Blocked('Work directory belongs to a different package')
    else:
        owner = {'manifest': manifest_hash, 'revision': REVISION, 'id': str(uuid.uuid4()), 'created': now()}
        save(marker, owner)
    return owner


class Coordinator:
    def __init__(self, package, work):
        self.package, self.work = Path(package).resolve(), Path(work).absolute()
        self.owner = claim_work(self.work, verify_package(self.package))
        self.output = self.work/'output'
        self.output.mkdir(exist_ok=True)
        self.logs = self.output/'logs'
        self.logs.mkdir(exist_ok=True)
        self.lock = (self.work/'.lock').open('a')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            self.lock.close()
            raise Blocked('Another launcher holds this lab lock; do not run concurrent campaigns') from e
        self.statefile = self.output/'checkpoint.json'
        self.state = json.loads(self.statefile.read_text()) if self.statefile.exists() else {
            'revision': REVISION, 'owner': self.owner['id'], 'created': now(), 'steps': {}, 'attempts': [], 'vm_claims': {}}
        if self.state['owner'] != self.owner['id'] or self.state['revision'] != REVISION:
            raise Blocked('Checkpoint ownership/source mismatch')
        self.env = {k: v for k, v in os.environ.items() if k in ('HOME', 'USER', 'LOGNAME', 'TMPDIR', 'LANG', 'LC_ALL', 'TERM')}
        self.env.update(PATH='/usr/bin:/bin:/usr/sbin:/sbin', LIMA_HOME=str(self.work/'lima'),
                        LIMA_TEMPLATES_PATH=str(self.work/'tools/share/lima/templates'),
                        COPYFILE_DISABLE='1')
        self.lima = self.work/'tools/bin/limactl'
        self.swap_initial = None
        self.sample_at = 0
        self.sample_last = None
        self.command_no = len(list(self.logs.glob('*.json')))
        self.active = None
        self.in_safety = False

    def checkpoint(self):
        self.state['updated'] = now()
        save(self.statefile, self.state)

    def sample(self):
        def get(*args):
            return subprocess.check_output(args, text=True, timeout=10, env=self.env).strip()
        swap = get('/usr/sbin/sysctl', '-n', 'vm.swapusage')
        match = re.search(r'used = ([0-9.]+)M', swap)
        if not match:
            raise Blocked('Cannot interpret measured macOS swap usage')
        data = dict(utc=now(), ram_bytes=int(get('/usr/sbin/sysctl', '-n', 'hw.memsize')),
                    pressure=int(get('/usr/sbin/sysctl', '-n', 'kern.memorystatus_vm_pressure_level')),
                    free_bytes=shutil.disk_usage(self.work).free, swap_mib=float(match.group(1)), swap_raw=swap)
        with (self.output/'resources.jsonl').open('a') as f:
            f.write(json.dumps(data)+'\n')
        self.sample_last, self.sample_at = data, time.monotonic()
        if self.swap_initial is None:
            self.swap_initial = data['swap_mib']
        return data

    def gate(self, initial=False, allocation=0):
        why = resource_problem(self.sample(), initial=initial, allocation=allocation, swap_initial=self.swap_initial)
        if why:
            raise Blocked('RESOURCE GATE: '+why)

    def run(self, label, argv, limit=180, *, expected=(0,), data=None, binary_out=None, monitor=True):
        self.command_no += 1
        stem = self.logs/f'{self.command_no:05d}-{label}'
        meta = {'label': label, 'argv': [str(a) for a in argv], 'start': now(), 'timeout_s': limit}
        save(stem.with_suffix('.json'), meta)
        out_path = Path(binary_out) if binary_out else stem.with_suffix('.stdout')
        start = time.monotonic()
        reason = None
        try:
            with out_path.open('wb') as out, stem.with_suffix('.stderr').open('wb') as err:
                if data is not None:
                    inp = stem.with_suffix('.input')
                    inp.write_bytes(data)
                    inf = inp.open('rb')
                else:
                    inf = open(os.devnull, 'rb')
                try:
                    self.active = subprocess.Popen([str(a) for a in argv], cwd=self.package, env=self.env,
                                                   stdin=inf, stdout=out, stderr=err, start_new_session=True)
                    while self.active.poll() is None:
                        if time.monotonic()-start > limit:
                            reason = Failed(f'{label} exceeded {limit}s timeout')
                            break
                        if monitor and not self.in_safety and time.monotonic()-self.sample_at >= 5:
                            why = resource_problem(self.sample(), swap_initial=self.swap_initial)
                            if why:
                                reason = Blocked('RESOURCE MONITOR: '+why)
                                break
                        time.sleep(0.2)
                    if reason:
                        self.stop_process()
                        raise reason
                    rc = self.active.returncode
                    meta['exit_status'] = rc
                    if expected is not None and rc not in expected:
                        tail = stem.with_suffix('.stderr').read_text(errors='replace')[-2000:]
                        raise Failed(f'{label}: exit {rc}; see {stem.name}.stdout/.stderr\n'+tail)
                finally:
                    inf.close()
                    if data is not None:
                        inp.unlink(missing_ok=True)
            return out_path.read_text(errors='replace') if binary_out is None else out_path
        finally:
            if self.active is not None and self.active.poll() is None:
                self.stop_process()
            meta.update(end=now(), elapsed_s=time.monotonic()-start)
            if self.active is not None:
                meta['exit_status'] = self.active.returncode
            if reason:
                meta['termination_reason'] = str(reason)
            save(stem.with_suffix('.json'), meta)
            self.active = None

    def stop_process(self):
        try:
            os.killpg(self.active.pid, signal.SIGTERM)
            self.active.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(self.active.pid, signal.SIGKILL)
            self.active.wait(timeout=10)
        except ProcessLookupError:
            pass

    def ctl(self, label, *args, **kw):
        return self.run(label, [self.lima, *args], **kw)

    def gsh(self, vm, label, args, limit=180, **kw):
        if vm not in VMS:
            raise Failed('Refusing guest command on '+vm)
        workdir = '/' if label.startswith(('identity-', 'sync-')) else GUEST
        return self.ctl(label, 'shell', '--workdir', workdir, vm, '--', *args, limit=limit, **kw)

    def python(self, label, code, *args, **kw):
        return self.gsh(VMS[0], label, ['sudo', 'python3', '-c', code, *args], **kw)

    def step(self, name, function):
        prior = self.state['steps'].get(name, {})
        if prior.get('status') == 'PASS':
            print('Retained completed step:', name, flush=True)
            return
        print('Witness:', name, flush=True)
        self.gate()
        attempt = {'name': name, 'start': now(), 'id': str(uuid.uuid4())}
        self.state['attempts'].append(attempt)
        self.state['steps'][name] = {'status': 'RUNNING', 'attempt': attempt['id']}
        self.checkpoint()
        try:
            function()
            attempt['status'] = 'PASS'
            self.state['steps'][name] = {'status': 'PASS', 'attempt': attempt['id'], 'finished': now()}
        except BaseException as e:
            status = 'BLOCKED' if isinstance(e, (Blocked, KeyboardInterrupt)) else 'FAIL'
            attempt.update(status=status, error=str(e))
            self.state['steps'][name] = {'status': status, 'error': str(e), 'attempt': attempt['id']}
            raise
        finally:
            attempt['end'] = now()
            self.checkpoint()
            self.report()

    def tools(self):
        # No global install, brew upgrade, shell profile edit or host package manager operation.
        download = self.work/'lima-2.2.0.tar.gz'
        if not download.exists() or sha(download) != LIMA_SHA:
            self.run('download-lima', ['/usr/bin/curl', '-fL', '--proto', '=https', '--proto-redir', '=https', '--tlsv1.2', '--connect-timeout', '20',
                     '--max-time', '600', '--retry', '2', '-o', str(download), LIMA_URL], limit=650)
        if sha(download) != LIMA_SHA:
            raise Failed('Lima SHA-256 mismatch')
        tools = self.work/'tools'
        tools.mkdir(exist_ok=True)
        with tarfile.open(download, 'r:gz') as archive:
            archive.extractall(tools, filter='data')
        version = self.ctl('lima-version', '--version')
        if version.strip() != 'limactl version 2.2.0':
            raise Failed('Unexpected Lima binary version: '+version)
        self.run('tool-inventory', ['/bin/bash', '-c', 'for t in git brew python3; do command -v "$t" || true; done'], monitor=False)
        # Lima 2.2 ignores LIMA_CACHE_HOME and uses ~/Library/Caches/lima for URL
        # images. Supply a verified local image instead, avoiding that shared cache.
        image = self.work/'ubuntu-arm64.img'
        if not image.exists() or sha(image) != IMAGE_SHA:
            try:
                self.run('download-ubuntu', ['/usr/bin/curl', '-fL', '--proto', '=https', '--proto-redir', '=https', '--tlsv1.2', '--connect-timeout', '20',
                         '--max-time', '1800', '--retry', '2', '-o', str(image), IMAGE_URL], limit=1850)
            except Failed as e:
                raise Blocked('Pinned Ubuntu image download unavailable; no latest-image substitution. '+str(e)) from e
        if sha(image) != IMAGE_SHA:
            raise Failed('Ubuntu image SHA-256 mismatch')

    def assert_home(self):
        home = self.work/'lima'
        contained(self.work, home)
        home.mkdir(exist_ok=True)
        for vm in (*VMS, *GOLDENS):
            contained(home, home/vm)
        names = self.ctl('vm-inventory', 'list', '--format', '{{.Name}}').split()
        for name in names:
            if name not in (*VMS, *GOLDENS) or name not in self.state['vm_claims']:
                raise Blocked('Unclaimed/unrelated Lima instance in private home: '+name)
        return names

    def network_check(self):
        text = self.run('host-routes-readonly', ['/usr/sbin/netstat', '-rn', '-f', 'inet'])
        conflicts = route_conflicts(text)
        if conflicts:
            raise Blocked('Host/VPN route overlaps Witness 10.77.0/1/2 subnets: '+repr(conflicts)+'. Disconnect the conflicting VPN or use another host; no routes changed.')
        for name, subnet in [('witness-mgmt', '10.77.0.0/24'), ('witness', '10.77.1.0/24')]:
            lines = self.ctl('network-inventory', 'network', 'list', '--json')
            entries = [json.loads(x) for x in lines.splitlines() if x.strip()]
            entry = next((x for x in entries if x['name'] == name), None)
            if entry:
                actual = ipaddress.ip_network(str(entry['gateway'])+'/'+str(entry['netmask']), strict=False)
                if entry['mode'] != 'user-v2' or str(actual) != subnet:
                    raise Blocked('Conflicting private network: '+name)
            else:
                self.ctl('network-create', 'network', 'create', name, '--mode', 'user-v2', '--gateway', subnet.replace('.0/24', '.1/24'))

    def up(self):
        names = self.assert_home()
        self.network_check()
        for vm in VMS:
            if vm not in names:
                if vm not in self.state['vm_claims']:
                    self.state['vm_claims'][vm] = {'owner': self.owner['id'], 'created': now()}
                    self.checkpoint()  # claim before create: interrupted create is resumable
                mac = '52:55:55:77:01:' + ('10' if vm == VMS[0] else '20')
                template = (self.package/'source/config/lima/witness-vm.yaml.tmpl').read_text()
                template = template.replace('base:\n  - template:_images/ubuntu-24.04   # pinned release-20260705 arm64 image with sha256 digest',
                                            f'images:\n  - location: {json.dumps(str(self.work/"ubuntu-arm64.img"))}\n    arch: aarch64\n    digest: "sha256:{IMAGE_SHA}"')
                for key, val in {'@NAME@': vm, '@MAC@': mac, '@NETWORK@': 'witness', '@MGMT_NETWORK@': 'witness-mgmt'}.items():
                    template = template.replace(key, val)
                config = self.output/(vm+'.yaml')
                config.write_text(template)
                self.ctl('validate-config', 'validate', config)
                self.ctl('create-'+vm, 'create', '--tty=false', '--name', vm, config, limit=900)
            try:
                self.ctl('start-'+vm, 'start', '--tty=false', '--timeout', '600s', vm, limit=650)
            except Failed as e:
                raise Blocked('VM startup/virtualization prerequisite failed. Inspect the named Lima stderr; if macOS offers an approval, approve only that Lima binary and rerun the same command. '+str(e)) from e
        self.sync()

    def identity(self, vm):
        mac = '52:55:55:77:01:' + ('10' if vm == VMS[0] else '20')
        cmd = f'test "$(uname -s)" = Linux && test "$(uname -m)" = aarch64 && test "$(hostname)" = lima-{vm} && test "$(cat /sys/class/net/lab0/address)" = {mac} && systemd-detect-virt --vm'
        self.gsh(vm, 'identity-'+vm, ['sh', '-c', cmd])

    def sync(self):
        archive = self.work/'source-transfer.tar'
        with tarfile.open(archive, 'w') as tf:
            for p in sorted((self.package/'source').rglob('*')):
                if p.is_file():
                    tf.add(p, arcname=p.relative_to(self.package/'source'), recursive=False)
        for vm in VMS:
            self.identity(vm)
            cmd = 'set -eu; rm -rf /opt/witness-lab.new; mkdir /opt/witness-lab.new; tar -xf - -C /opt/witness-lab.new --no-same-owner; rm -rf /opt/witness-lab; mv /opt/witness-lab.new /opt/witness-lab'
            self.gsh(vm, 'sync-'+vm, ['sudo', 'sh', '-c', cmd], data=archive.read_bytes())
            manifest = json.loads((self.package/'SOURCE_MANIFEST.json').read_text())
            mapping = {entry['path']: entry['export_sha256'] for entry in manifest['files']}
            code = 'import hashlib,json,pathlib,sys;m=json.loads(sys.argv[1]);p=pathlib.Path("/opt/witness-lab");assert all(hashlib.sha256((p/k).read_bytes()).hexdigest()==v for k,v in m.items());print("guest source manifest verified",len(m))'
            self.gsh(vm, 'source-verify', ['sudo', 'python3', '-c', code, json.dumps(mapping)])
            stamp = f'git_sha={REVISION}\ngit_dirty=0\nsynced_at={now()}\nlima=limactl version 2.2.0\n'
            self.gsh(vm, 'source-stamp', ['sudo', 'tee', GUEST+'/.witness-source'], data=stamp.encode())
        helpers = self.work/'helper-transfer.tar'
        with tarfile.open(helpers, 'w') as tf:
            for name in ('guest_verify.py', 'interrupt_probe.py', 'deadline_probe.py'):
                tf.add(self.package/name, arcname=name)
        self.gsh(VMS[0], 'helper-dir', ['sudo', 'mkdir', '-p', '/opt/witness-handoff'])
        self.gsh(VMS[0], 'helpers', ['sudo', 'tar', '-xf', '-', '-C', '/opt/witness-handoff'], data=helpers.read_bytes())

    def provision(self):
        for vm, role in [(VMS[1], 'field'), (VMS[0], 'ctl')]:
            self.gsh(vm, 'base-'+role, ['sudo', 'bash', GUEST+'/scripts/provision_'+role+'.sh', '--stage', 'base'], limit=1650)
            log = self.work/'lima'/vm/'ha.stderr.log'
            if not log.exists() or 'Detected SSH server is listening on the vsock port' not in log.read_text(errors='replace'):
                self.ctl('restart-stop', 'stop', vm, limit=180)
                self.ctl('restart-vsock', 'start', '--tty=false', '--timeout', '600s', vm, limit=650)
            content = log.read_text(errors='replace')
            marks = re.findall('Detected SSH server is listening on the vsock port|SSH server does not seem to be running on vsock port', content)
            if not marks or not marks[-1].startswith('Detected'):
                raise Blocked('No confirmed vsock recovery path for '+vm+'; refusing network isolation. See Lima ha.stderr.log.')
        for vm, role in [(VMS[1], 'field'), (VMS[0], 'ctl')]:
            self.gsh(vm, 'provision-'+role, ['sudo', 'bash', GUEST+'/scripts/provision_'+role+'.sh', '--stage', 'all'], limit=1650)
        pub = self.gsh(VMS[0], 'runner-public-key', ['sudo', 'cat', '/var/lib/witness/runner/id_ed25519.pub'])
        if not pub.startswith('ssh-ed25519 '):
            raise Failed('Invalid runner public key')
        self.gsh(VMS[1], 'authorize-runner', ['sudo', 'tee', '/etc/witness/runner_key.pub'], data=pub.encode())
        self.gsh(VMS[1], 'agent', ['sudo', 'bash', GUEST+'/scripts/provision_field.sh', '--stage', 'agent'])
        hk = self.gsh(VMS[1], 'field-host-public-key', ['sudo', 'cat', '/etc/ssh/ssh_host_ed25519_key.pub'])
        known = '10.77.1.20 '+' '.join(hk.split()[:2])+'\n'
        self.gsh(VMS[0], 'pin-field', ['sudo', 'tee', '/var/lib/witness/runner/known_hosts'], data=known.encode())
        self.gsh(VMS[0], 'experiment-root', ['sudo', 'mkdir', '-p', STORE])
        self.verify_installed()
        self.preflight(wait=True)

    def verify_installed(self):
        installs = {
            VMS[1]: {'device/device.py':'/usr/local/lib/witness/device.py', 'device/mutants.py':'/usr/local/lib/witness/mutants.py',
                     'device/witness-device@.service':'/etc/systemd/system/witness-device@.service',
                     'scripts/faultctl.py':'/usr/local/sbin/witness-faultctl', 'scripts/witness-fault-ssh':'/usr/local/sbin/witness-fault-ssh'},
            VMS[0]: {**{p:'/usr/local/lib/witness-gateway/'+p for p in ('gateway/__init__.py', 'gateway/gateway.py',
                       'runner/__init__.py', 'runner/classify.py', 'runner/client.py', 'scripts/lib/inventory.py')},
                     'inventory.yaml':'/etc/witness/inventory.yaml', 'gateway/witness-gateway.service':'/etc/systemd/system/witness-gateway.service'}}
        for vm, mapping in installs.items():
            code = 'import pathlib,json,hashlib,sys;m=json.loads(sys.argv[1]);h=lambda p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest();r={k:{"source":h("/opt/witness-lab/"+k),"installed":h(v)} for k,v in m.items()};print(json.dumps(r,indent=2));assert all(v["source"]==v["installed"] for v in r.values())'
            self.gsh(vm, 'installed-source-hashes', ['sudo', 'python3', '-c', code, json.dumps(mapping)])

    def preflight(self, wait=False):
        end = time.monotonic() + (120 if wait else 0)
        while True:
            try:
                for vm, role in [(VMS[1], 'field'), (VMS[0], 'ctl')]:
                    self.gsh(vm, 'preflight-'+role, ['sudo', 'bash', GUEST+'/scripts/preflight.sh', '--role', role])
                return
            except Failed:
                if time.monotonic() >= end:
                    raise
                time.sleep(4)

    def space_for_pair(self):
        disks = []
        for vm in VMS:
            directory = self.work/'lima'/vm
            # Lima >=2.1 VZ uses disk; older layouts may expose a link to diffdisk.
            candidates = [directory/n for n in ('disk', 'diffdisk') if (directory/n).exists()]
            if not candidates:
                raise Blocked('Cannot measure VM disk logical size for '+vm)
            disk = candidates[0]
            contained(directory, disk.resolve())
            disks.append(dict(vm=vm, logical=disk.stat().st_size, allocated=disk.stat().st_blocks*512))
        peak = sum(max(x['logical'], 10*GIB) for x in disks)
        with (self.output/'restore-space.jsonl').open('a') as f:
            f.write(json.dumps({'utc': now(), 'disks': disks, 'additional_full_copy_bytes': peak,
                                'required_free_bytes': peak+14*GIB, 'copy_on_write_credit': 0})+'\n')
        self.gate(allocation=peak)

    def golden(self):
        self.preflight()
        self.space_for_pair()
        for vm in VMS:
            self.ctl('golden-stop', 'stop', vm, limit=180)
        names = self.assert_home()
        for vm, golden in zip(VMS, GOLDENS):
            if golden not in names:
                self.state['vm_claims'][golden] = {'owner': self.owner['id'], 'created': now()}
                self.checkpoint()
                self.ctl('golden-clone', 'clone', '--tty=false', vm, golden, limit=900)
            # Goldens never boot; record disk hashes while stopped for clone provenance.
            d = self.work/'lima'/golden
            disk = next(p for p in (d/'disk', d/'diffdisk') if p.exists())
            self.run('golden-disk-hash', ['/usr/bin/shasum', '-a', '256', disk], limit=600)
        for vm in VMS:
            self.ctl('golden-resume-active', 'start', '--tty=false', '--timeout', '600s', vm, limit=650)
        self.preflight(wait=True)

    def fetch(self):
        tar = self.work/'evidence-transfer.tar'
        self.gsh(VMS[0], 'fetch-evidence', ['sudo', 'tar', '-C', STORE, '-cf', '-', '.'],
                 limit=300, binary_out=tar)
        target = self.output/'evidence'
        target.mkdir(exist_ok=True)
        staging = self.work/('fetch-'+str(uuid.uuid4()))
        staging.mkdir()
        with tarfile.open(tar) as tf:
            tf.extractall(staging, filter='data')
        for database in staging.rglob('witness.db'):
            with sqlite3.connect(database.as_uri()+'?mode=ro', uri=True) as conn:
                if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise Failed('Transferred database is not intact: '+str(database))
        for p in sorted(staging.rglob('*')):
            contained(staging, p)
            if not p.is_file():
                continue
            rel = p.relative_to(staging)
            dest = contained(target, target/rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists() and sha(dest) != sha(p):
                if 'evidence' in rel.parts[1:]:
                    raise Failed('Previously fetched immutable evidence changed: '+str(rel))
                if dest.name == 'witness.db':
                    snapshots = self.output/'database-snapshots'
                    snapshots.mkdir(exist_ok=True)
                    backup = snapshots/(rel.parts[0]+'-'+sha(dest)+'.db')
                    if not backup.exists():
                        shutil.copyfile(dest, backup)
            staged = dest.with_name(dest.name+'.new')
            shutil.copyfile(p, staged)
            staged.replace(dest)
        shutil.rmtree(staging)  # exact newly allocated transfer directory, never a VM
        tar.unlink()

    def push(self):
        target = self.output/'evidence/main'
        if not (target/'witness.db').exists():
            return
        # If the host died before fetch, the surviving guest may have newer failure
        # records. Preserve that store BEFORE restoring the host's continuation.
        remote = self.python('continuation-check', 'import pathlib,sqlite3,json;p=pathlib.Path("'+STORE+'/main/witness.db");print(json.dumps({"exists":p.exists(),"max":sqlite3.connect(p.as_uri()+"?mode=ro",uri=True).execute("select coalesce(max(run_id),0) from runs").fetchone()[0] if p.exists() else 0}))')
        data = json.loads(remote)
        if data['exists']:
            with sqlite3.connect((target/'witness.db').as_uri()+'?mode=ro', uri=True) as conn:
                local = conn.execute('select coalesce(max(run_id),0) from runs').fetchone()[0]
            if data['max'] < local:
                raise Failed('Guest continuation is older than retained host database; refusing to overwrite either')
            self.fetch()
        archive = self.work/'master-transfer.tar'
        with tarfile.open(archive, 'w') as tf:
            tf.add(target/'witness.db', arcname='witness.db')
            tf.add(target/'evidence', arcname='evidence')
        self.gsh(VMS[0], 'main-dir', ['sudo', 'mkdir', '-p', STORE+'/main'])
        self.gsh(VMS[0], 'push-master', ['sudo', 'tar', '-xf', '-', '-C', STORE+'/main'], data=archive.read_bytes())
        archive.unlink()

    def verify(self, kind, store='main', count=0, **kw):
        return self.gsh(VMS[0], 'verify-'+kind, ['sudo', 'python3', '/opt/witness-handoff/guest_verify.py', STORE+'/'+store,
                                                kind, REVISION, '--count', str(count)], limit=600, **kw)

    def suite(self, kind, *, mutant=None, store='main', count=0):
        self.gsh(VMS[0], 'store-init', ['sudo', 'mkdir', '-p', STORE+'/'+store+'/evidence'])
        args = ['sudo', 'timeout', '--kill-after=10', '1200', 'python3', '-B', '-m', 'pytest', 'tests/live', '--live',
                '-p', 'no:cacheprovider', '-rA', '-m', 'fault' if kind == 'fault' else 'commissioning',
                '--db', STORE+'/'+store+'/witness.db', '--evidence-root', STORE+'/'+store+'/evidence',
                '--run-notes', 'external reproduction '+self.state['attempts'][-1]['id']]
        if mutant:
            args += ['--mutant', mutant]
        try:
            self.gsh(VMS[0], 'suite-'+(mutant or kind), args, limit=1230, expected=(1,) if mutant else (0,))
            self.verify('mutant' if mutant else kind, store, count)
        finally:
            self.fetch()

    def mutant(self, number):
        self.preflight()
        # Actual catalog specifies deployment modes; get these from source inside ctl.
        spec = self.python('mutant-spec', 'from runner.catalog import mutant_spec;from scripts.lib.inventory import load;import sys;print(mutant_spec(sys.argv[1],load("inventory.yaml")["devices"]))', number).strip()
        try:
            self.gsh(VMS[1], 'mutant-deploy', ['sudo', 'witness-faultctl', 'mutant', 'deploy', 'a', spec])
            self.suite('baseline', mutant=number)
        finally:
            self.gsh(VMS[1], 'mutant-stock-restore', ['sudo', 'witness-faultctl', 'mutant', 'restore', 'a'])
            self.preflight()

    def deadline(self, target, delay, body):
        label = ('deadline-f12-' if target.startswith('test_f12') else 'deadline-f5-')+str(delay)+'-'+str(body)
        store = label+'-'+self.state['attempts'][-1]['id']
        negative = delay == 1.5 and body == 1.5
        try:
            self.gsh(VMS[0], label, ['sudo', 'timeout', '--kill-after=10', '180', 'python3', '/opt/witness-handoff/deadline_probe.py',
                     str(delay), target, STORE+'/'+store, str(body)], limit=200, expected=(1,) if negative else (0,))
            if negative:
                self.verify('deadline', store)
            else:
                self.verify('control', store)
        finally:
            self.preflight()
            self.fetch()

    def interrupt(self, sig, fault):
        store = 'interrupt-'+sig+'-'+fault+'-'+self.state['attempts'][-1]['id']
        try:
            self.gsh(VMS[0], 'interrupt-'+sig+'-'+fault,
                     ['sudo', 'timeout', '--kill-after=10', '260', 'python3', '/opt/witness-handoff/interrupt_probe.py',
                      sig, fault, STORE+'/'+store], limit=280)
            self.suite('baseline', store=store)  # real detector session corroborates killed run
            self.verify('interruption', store)
            for vm in VMS:
                self.gsh(vm, 'recovery-native-journal', ['sudo', 'journalctl', '-u', 'witness-ctl-fault-deadman', '-u',
                         'witness-fault-deadman', '-u', 'witness-field-capture', '--since', '-8min', '--no-pager', '-o', 'short-iso-precise'])
            self.gsh(VMS[1], 'field-faultctl-recovery-log', ['sudo', 'cat', '/var/lib/witness/faultctl.log'])
        finally:
            self.fetch()

    def stop_pair(self):
        names = self.assert_home()
        for vm in VMS:
            if vm in names:
                self.ctl('stop-pair', 'stop', vm, limit=180, expected=(0,), monitor=False)

    def delete_pair(self):
        self.stop_pair()
        names = self.assert_home()
        for vm in VMS:
            if vm in names:
                self.ctl('delete-owned-disposable', 'delete', '--tty=false', vm, limit=180)

    def begin_replacement(self, name):
        op = self.state.get('replacement')
        if not op or op['name'] != name:
            self.space_for_pair()
            self.fetch()
            op = {'name': name, 'id': str(uuid.uuid4()), 'utc': now(), 'stage': 'delete'}
            self.state['replacement'] = op
            self.checkpoint()
        if op['stage'] == 'delete':
            self.delete_pair()  # safe to repeat after interruption between either deletion
            op['stage'] = 'create'
            self.checkpoint()
        return op

    def restore(self, trial):
        op = self.begin_replacement('restore-'+str(trial))
        names = self.assert_home()
        for vm, golden in zip(VMS, GOLDENS):
            if vm not in names:
                self.gate(allocation=10*GIB)
                self.ctl('restore-clone', 'clone', '--tty=false', golden, vm, limit=900)
        self.up()
        for vm, golden in zip(VMS, GOLDENS):
            provenance = f'golden-restore id={op["id"]} from={golden} golden_code={REVISION} restored_at={op["utc"]}\n'
            self.gsh(vm, 'restore-provenance', ['sudo', 'tee', '/var/lib/witness/provenance'], data=provenance.encode())
        self.provision()
        self.push()
        self.suite('baseline', count=trial)

    def fresh(self):
        self.begin_replacement('fresh-VM')
        self.up()  # create from the digest-pinned Ubuntu image, never from a golden
        self.provision()
        self.provision()
        self.smoke()
        self.unit()
        self.push()
        self.suite('baseline', count=5)
        self.suite('fault')
        self.preflight()

    def unit(self):
        self.gsh(VMS[0], 'ubuntu-unit', ['sudo', 'timeout', '--kill-after=10', '900', 'python3', '-B', '-m', 'pytest',
                 '-q', '-p', 'no:cacheprovider', 'tests/unit', 'tests/test_inventory.py'], limit=930)
        self.gsh(VMS[0], 'ubuntu-shellcheck', ['sh', '-c', 'cd /opt/witness-lab && shellcheck -x scripts/*.sh scripts/lib/*.sh'])

    def recovery(self):
        # A process that outlived an interrupted host launcher must finish or be stopped
        # BEFORE a reset. Limit this exact dedicated guest command family, then wait.
        names = self.assert_home()
        for vm in VMS:
            if vm not in names:
                continue
            status = self.ctl('recovery-status', 'list', '--format', '{{.Status}}', vm).strip()
            if status != 'Running':
                continue
            self.identity(vm)
            script = ('pkill -TERM -f "^python3 (-B )?(-m pytest tests/live|/opt/witness-handoff/(interrupt_probe|deadline_probe)\\.py)" || true; '
                      'for n in $(seq 1 30); do pgrep -f "^python3 (-B )?(-m pytest tests/live|/opt/witness-handoff/)" >/dev/null || exit 0; sleep 1; done; '
                      'pkill -KILL -f "^python3 (-B )?(-m pytest tests/live|/opt/witness-handoff/(interrupt_probe|deadline_probe)\\.py)" || true')
            if vm == VMS[0]:
                self.gsh(vm, 'recover-runner', ['sudo', 'sh', '-c', script], limit=45, monitor=False)
            role = 'ctl' if vm == VMS[0] else 'field'
            self.gsh(vm, 'recover-reset', ['sudo', 'bash', GUEST+'/scripts/reset_lab.sh', '--role', role], limit=180, monitor=False)

    def safety(self):
        if not self.lima.exists():
            self.state['safety'] = {'utc': now(), 'ok': True, 'detail': 'No Lima resources created'}
            return
        self.in_safety = True
        errors = []
        try:
            self.recovery()
            names = self.assert_home()
            if all(v in names for v in VMS):
                try:
                    exists = self.python('main-store-presence', 'import pathlib;print(pathlib.Path("'+STORE+'/main/witness.db").is_file())', monitor=False).strip()
                    if exists == 'True':
                        self.verify('full', count=5, expected=(0,1), monitor=False)
                    self.fetch()
                    self.preflight()
                except (Failed, Blocked) as e:
                    errors.append(str(e))
        except BaseException as e:
            errors.append(str(e))
        finally:
            try:
                names = self.assert_home()
                for vm in VMS:
                    if vm in names:
                        try:
                            self.ctl('safety-stop', 'stop', vm, limit=180, monitor=False)
                        except BaseException as e:
                            errors.append(str(e))
                statuses = self.ctl('final-stopped-inventory', 'list', '--format', '{{.Name}} {{.Status}}', monitor=False)
                if any(line.split()[-1] != 'Stopped' for line in statuses.splitlines() if line.strip()):
                    errors.append('Final private VM inventory is not entirely Stopped: '+statuses)
            except BaseException as e:
                errors.append(str(e))
        self.state['safety'] = {'utc': now(), 'ok': not errors, 'errors': errors}
        self.in_safety = False
        self.checkpoint()

    def report(self):
        steps = self.state['steps']
        full = self.output/'evidence/main/verification-full.json'
        audit = json.loads(full.read_text()) if full.exists() else None
        required = required_steps()
        complete = all(steps.get(s, {}).get('status') == 'PASS' for s in required)
        failed = any(s.get('status') == 'FAIL' for s in steps.values())
        safety = self.state.get('safety', {}).get('ok', False)
        verdict = ('FULL ACCEPTANCE VERIFIED' if complete and audit and audit['ok'] and safety else
                   'ACCEPTANCE FAILED' if failed else 'PARTIAL ACCEPTANCE — BLOCKED')
        self.state['verdict'] = verdict
        rows = ['# Witness recipient completion report', '', '**'+verdict+'**', '',
                'Generated UTC: '+now(), 'Source: `'+REVISION+'` (verified source snapshot; original history excluded).',
                'Software simulation with real VM network traffic. This report is self-generated, not an external professional certification.', '',
                '## Executed work', '', '| Requirement / experiment | Result |', '|---|---|']
        rows += [f'| {s} | {steps.get(s, {}).get("status", "UNTESTED")} |' for s in required]
        rows += ['', '## Requirement traceability', '', '| Requirement | Current evidence |', '|---|---|']
        cases = {'REQ-01':'C-IDENTIFY', 'REQ-02':'FT-F7-NAME-SWAP', 'REQ-03':'C-HEALTH', 'REQ-04':'C-READ-CLOCK / FT-F13-SKEW',
                 'REQ-05':'C-READ-SERIES / FT-F13-REPEAT-SEQ', 'REQ-06':'FT-F10-* / M3–M5', 'REQ-07':'FT-F2 / FT-F6-*',
                 'REQ-08':'FT-F12-RESTART', 'REQ-09':'C-GATEWAY / GW-F1/F5/F8', 'REQ-10':'C-ENVIRONMENT / every run session'}
        rows += [f'| {req} | {case}; see evidence/main/reports/traceability.md; '+('VERIFIED by full contract' if verdict == 'FULL ACCEPTANCE VERIFIED' else 'acceptance incomplete — consult actual case rows')+' |' for req, case in cases.items()]
        rows += ['', '## Acceptance contract', '', 'Canonical audit and all requirement/case rows: `evidence/main/acceptance.json`,',
                 '`evidence/main/reports/` and `evidence/main/witness.db`. Diagnostics remain separately identified negative experiments;',
                 'they are never counted as successful commissioning. All positive campaigns and five restores continue the same main database.', '']
        if audit:
            rows += ['| Assertion | Holds | Violations |', '|---|---|---|']
            rows += [f'| {x["id"]} | {x["ok"]} | {str(x["violations"]).replace("|", "/")} |' for x in audit['audit']]
        else:
            rows += ['Full database audit: UNTESTED or incomplete.']
        rows += ['', '## Errors, blockers and remaining work', '']
        rows += [f'- {a["name"]} ({a.get("start")}): {a.get("status", "RUNNING")}: {a.get("error", "")}'
                 for a in self.state['attempts'] if a.get('status') != 'PASS'] or ['No failed attempts recorded.']
        if self.state.get('fatal'):
            rows += ['Fatal/blocking condition: '+self.state['fatal']]
        rows += ['', '## Evidence and resources', '', 'All command argv, UTC start/end, elapsed time, exit code, stdout and stderr: `logs/`.',
                 'Measured host RAM, free disk, pressure and swap: `resources.jsonl`; full-copy restore sizing: `restore-space.jsonl`.',
                 'Package hash/ownership and resumable steps: `checkpoint.json`. Lab recovery/shutdown: '+json.dumps(self.state.get('safety', {'status':'UNTESTED'})),
                 'Ubuntu image digest and every dependency version/package are captured in provisioning logs and VM YAML.',
                 'Rerun the original launch command to resume. Share using RETURN_RESULTS.sh after reviewing the privacy note in HANDOFF.md.', '']
        (self.output/'COMPLETION_REPORT.md').write_text('\n'.join(rows))
        save(self.output/'completion.json', {'verdict': verdict, 'source': REVISION, 'required_steps': required,
                                           'checkpoint': self.state, 'audit': audit})
        return verdict

    def execute(self):
        self.state.pop('fatal', None)
        self.gate(initial=not self.state['steps'])
        self.step('dependencies', self.tools)
        self.assert_home()
        if self.state['steps'].get('provision', {}).get('status') == 'PASS':
            # Resume stopped VMs without redoing completed results. No new run is claimed.
            names = self.assert_home()
            if all(vm in names for vm in VMS):
                for vm in VMS:
                    self.ctl('resume-start', 'start', '--tty=false', '--timeout', '600s', vm, limit=650)
                self.recovery()
        self.step('provision', lambda: (self.up(), self.provision(), self.provision()))
        self.step('network-isolation-and-recovery-path', self.smoke)
        self.step('golden-clean-state', self.golden)
        self.step('ubuntu-unit-and-shellcheck', self.unit)
        self.step('acceptance-adversarial-verifier', lambda: self.gsh(VMS[0], 'contract-verifier',
                  ['sudo', 'timeout', '--kill-after=10', '3600', 'python3', '-B', 'scripts/verify_acceptance_contract.py',
                   '--json', STORE+'/contract-verifier.json'], limit=3630))
        self.step('stock-baseline-before-mutants', lambda: self.suite('baseline'))
        self.step('fault-catalog-21-variants-24-instances', lambda: self.suite('fault'))
        for mutant in range(1, 7):
            self.step('mutant-M'+str(mutant), lambda m=mutant: self.mutant('M'+str(m)))
        self.step('stock-baseline-after-mutants', lambda: self.suite('baseline'))
        for target, name in [('test_f12_restart_during_polls', 'F12'), ('test_gateway_detects_route_loss', 'F5')]:
            for delay, body in [(0, 0), (1.5, 0), (1.5, 1.5)]:
                self.step(f'deadline-{name}-{delay}-{body}', lambda t=target, d=delay, b=body: self.deadline(t, d, b))
        for sig, fault in [('TERM', 'f2'), ('KILL', 'f2'), ('KILL', 'f5')]:
            self.step('recovery-'+sig+'-'+fault, lambda s=sig, f=fault: self.interrupt(s, f))
        self.step('reset-selftest', self.reset_selftest)
        for trial in range(1, 6):
            self.step('independent-restore-'+str(trial), lambda n=trial: self.restore(n))
        self.step('fresh-VM-reproduction', self.fresh)
        self.step('final-24-assertion-audit', self.final_audit)

    def reset_selftest(self):
        # The existing host wrapper is not used (it assumes a host YAML venv).
        # Execute exactly its bounded, role-guarded dirty-state checks in the guests.
        def arm(role, unit):
            return f'systemctl stop {unit}.timer 2>/dev/null || true; systemctl reset-failed {unit}.timer {unit}.service 2>/dev/null || true; systemd-run --quiet --unit={unit} --on-active=90 --timer-property=AccuracySec=1s /bin/bash {GUEST}/scripts/reset_lab.sh --role {role}; systemctl is-active -q {unit}.timer; '
        field = f'source {GUEST}/scripts/lib/guest_common.sh; assert_lab_vm field; '+arm('field','witness-fault-deadman')+'nft add table ip witness_fault_selftest; tc qdisc add dev field0 root netem delay 5ms; systemctl kill -s STOP --kill-whom=main witness-device@a; ip addr del 10.77.2.12/24 dev field0'
        ctl = f'source {GUEST}/scripts/lib/guest_common.sh; assert_lab_vm ctl; '+arm('ctl','witness-ctl-fault-deadman')+'nft add table inet witness_fault_selftest; tc qdisc add dev lab0 root netem delay 5ms; ip route del 10.77.2.0/24'
        try:
            self.gsh(VMS[1], 'reset-dirty-field', ['sudo', 'bash', '-euc', field])
            self.gsh(VMS[0], 'reset-dirty-ctl', ['sudo', 'bash', '-euc', ctl])
            for vm, role in [(VMS[0], 'ctl'), (VMS[1], 'field')]:
                self.gsh(vm, 'required-RED-'+role, ['sudo', 'bash', GUEST+'/scripts/preflight.sh', '--role', role], expected=(1,))
        finally:
            self.recovery()
        self.preflight()

    def smoke(self):
        for vm, role in [(VMS[1], 'field'), (VMS[0], 'ctl')]:
            self.gsh(vm, 'native-isolation-smoke-'+role, ['sudo', 'bash', GUEST+'/scripts/lab-smoke.sh', '--role', role])
        try:
            self.gsh(VMS[0], 'management-route-remove', ['sudo', 'bash', GUEST+'/scripts/lab-smoke.sh', '--role', 'ctl', '--route-demo', 'remove'])
            for vm in VMS:
                self.identity(vm)  # fresh management connections while the device route is absent
        finally:
            self.gsh(VMS[0], 'management-route-restore', ['sudo', 'bash', GUEST+'/scripts/lab-smoke.sh', '--role', 'ctl', '--route-demo', 'restore'])
        self.preflight()

    def final_audit(self):
        try:
            self.verify('full', count=5)
        finally:
            self.fetch()


def required_steps():
    return ['dependencies', 'provision', 'network-isolation-and-recovery-path', 'golden-clean-state', 'ubuntu-unit-and-shellcheck', 'acceptance-adversarial-verifier',
            'stock-baseline-before-mutants', 'fault-catalog-21-variants-24-instances', *('mutant-M'+str(n) for n in range(1, 7)),
            'stock-baseline-after-mutants', *(f'deadline-{name}-{d}-{b}' for name in ('F12', 'F5') for d,b in ((0,0),(1.5,0),(1.5,1.5))),
            'recovery-TERM-f2', 'recovery-KILL-f2', 'recovery-KILL-f5', 'reset-selftest',
            *('independent-restore-'+str(n) for n in range(1, 6)), 'fresh-VM-reproduction', 'final-24-assertion-audit']


def return_archive(work):
    work = Path(work).resolve()
    output = work/'output'
    if not (output/'checkpoint.json').is_file():
        raise Blocked('No recipient checkpoint to return')
    name = work/('Witness-Return-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.zip')
    manifest = []
    partial = name.with_suffix('.zip.partial')
    with zipfile.ZipFile(partial, 'x', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(output.rglob('*')):
            contained(output, p)
            if not p.is_file():
                continue
            rel = p.relative_to(output).as_posix()
            if p.suffix in ('.pem', '.key', '.sock', '.input') or p.name.startswith(('id_', 'ssh_')):
                raise Failed('Unexpected credential/socket file in return evidence')
            if not (p.suffix in ('.md', '.json', '.jsonl', '.txt', '.stdout', '.stderr', '.db', '.pcap', '.yaml', '.log') or p.name == 'SHA256SUMS'):
                raise Failed('Unrecognized return file type: '+rel)
            data = p.read_bytes()
            if re.search(rb'-----BEGIN (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9]{32,}', data):
                raise Failed('Possible credential in return evidence: '+rel)
            manifest.append(hashlib.sha256(data).hexdigest()+'  '+rel)
            z.writestr('Witness-Return/'+rel, data)
        z.writestr('Witness-Return/RETURN_SHA256SUMS', '\n'.join(manifest)+'\n')
    partial.replace(name)
    print(str(name)+'\nSHA-256 '+sha(name))
    return name


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--consented', action='store_true')
    p.add_argument('--return', dest='return_only', action='store_true')
    p.add_argument('--report', action='store_true')
    p.add_argument('--bootstrap-log', type=Path)
    a = p.parse_args()
    package = Path(__file__).resolve().parent
    verify_package(package)
    if a.return_only:
        if not (a.work/'output/checkpoint.json').is_file():
            raise Blocked('No recipient checkpoint to return')
        claim_work(a.work, verify_package(package))
        with (a.work/'.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as e:
                raise Blocked('The campaign is still running; stop it and wait for cleanup before packaging a consistent return store') from e
            return_archive(a.work)
        return 0
    c = Coordinator(package, a.work)
    if a.bootstrap_log and a.bootstrap_log.is_file():
        shutil.copyfile(a.bootstrap_log, c.logs/('bootstrap-'+str(uuid.uuid4())+'.log'))
    if a.report:
        print(c.report())
        c.checkpoint()
        return 0
    if not a.consented:
        raise Blocked('Use RUN_ON_THIS_MAC.sh for informed consent')
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise Blocked('Requires native Apple Silicon macOS')
    rc = 0
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt('SIGTERM')))
    try:
        c.execute()
    except Blocked as e:
        c.state['fatal'] = str(e)
        print('BLOCKED:', e, file=sys.stderr)
        rc = 2
    except KeyboardInterrupt:
        c.state['fatal'] = 'Interrupted; completed steps retained. Rerun the same launch command.'
        rc = 130
    except Exception as e:
        c.state['fatal'] = str(e)
        print('FAILED:', e, file=sys.stderr)
        rc = 1
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        c.safety()
        verdict = c.report()
        c.checkpoint()
        print(verdict+'\nReport: '+str(c.output/'COMPLETION_REPORT.md'))
    return rc if rc else (0 if verdict == 'FULL ACCEPTANCE VERIFIED' else 2)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (Blocked, Failed) as e:
        print('Witness:', e, file=sys.stderr)
        raise SystemExit(2)
