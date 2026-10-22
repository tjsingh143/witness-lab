#!/usr/bin/env python3
"""Bounded native packaging smoke. No VM starts/creates or host network mutations."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile

from launcher import sha, verify_package, REVISION, IMAGE_SHA, LIMA_SHA


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--zip', type=Path, required=True)
    p.add_argument('--lima-archive', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    steps = []

    def record(label, argv, expected=(0,), env=None, limit=60):
        start = dt.datetime.now(dt.timezone.utc).isoformat()
        t0 = time.monotonic()
        result = subprocess.run([str(s) for s in argv], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=limit)
        meta = {'argv': [str(s) for s in argv], 'utc_start': start, 'utc_end': dt.datetime.now(dt.timezone.utc).isoformat(),
                'timeout_s': limit, 'elapsed_s': time.monotonic()-t0, 'exit_status': result.returncode,
                'ok': result.returncode in expected}
        (a.out/(label+'.stdout')).write_bytes(result.stdout)
        (a.out/(label+'.stderr')).write_bytes(result.stderr)
        (a.out/(label+'.json')).write_text(json.dumps(meta, indent=2)+'\n')
        steps.append({'label':label, **meta})
        if not meta['ok']:
            raise RuntimeError(label+': '+result.stderr.decode(errors='replace'))
        return result

    if sha(a.lima_archive) != LIMA_SHA:
        raise RuntimeError('Unverified Lima archive')
    with tempfile.TemporaryDirectory(prefix='Witness portable extraction with spaces ') as raw:
        root = Path(raw)
        extracted = root/'new and different name'
        extracted.mkdir()
        with zipfile.ZipFile(a.zip) as z:
            if z.testzip():
                raise RuntimeError('ZIP CRC failure')
            for entry in z.infolist():
                path = Path(entry.filename)
                if path.is_absolute() or '..' in path.parts or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                    raise RuntimeError('Unsafe archive member')
            z.extractall(extracted)
            for entry in z.infolist():
                (extracted/entry.filename).chmod((entry.external_attr >> 16) & 0o777)
        package = extracted/'Witness-Reproduction-f09aa63'
        manifest_hash = verify_package(package)
        record('shell-checksum-verification', ['/bin/bash', package/'RUN_ON_THIS_MAC.sh', '--verify'])
        record('launcher-cli-help', [sys.executable, package/'launcher.py', '--help'])
        # Native CLI validation only, with an empty, dedicated Lima home.
        tools = root/'tools'
        tools.mkdir()
        with tarfile.open(a.lima_archive) as tf:
            tf.extractall(tools, filter='data')
        env = {k: v for k,v in os.environ.items() if k in ('PATH','HOME','USER','LOGNAME','TMPDIR')}
        env['LIMA_HOME'] = str(root/'empty-lima-home')
        cli = tools/'bin/limactl'
        record('official-lima-version', [cli, '--version'], env=env)
        record('empty-private-vm-inventory', [cli, 'list', '--format', '{{.Name}}'], env=env)
        for network, subnet in [('witness-mgmt','10.77.0.1/24'), ('witness','10.77.1.1/24')]:
            record('private-network-config-'+network, [cli, 'network', 'create', network, '--mode', 'user-v2', '--gateway', subnet], env=env)
        # Use the exact coordinator's template substitutions (local image, fixed inventory MACs).
        template = (package/'source/config/lima/witness-vm.yaml.tmpl').read_text()
        template = template.replace('base:\n  - template:_images/ubuntu-24.04   # pinned release-20260705 arm64 image with sha256 digest',
                                    f'images:\n  - location: "{root}/ubuntu-arm64.img"\n    arch: aarch64\n    digest: "sha256:{IMAGE_SHA}"')
        for vm, mac in [('witness-ctl','52:55:55:77:01:10'),('witness-field','52:55:55:77:01:20')]:
            config = template
            for key,value in {'@NAME@':vm,'@MAC@':mac,'@NETWORK@':'witness','@MGMT_NETWORK@':'witness-mgmt'}.items():
                config = config.replace(key,value)
            path = root/(vm+'.yaml')
            path.write_text(config)
            record('native-config-validate-'+vm, [cli,'validate',path], env=env)
        # Execute the exact recipient message through its real RAM refusal on this 8 GiB host.
        home = root/'message-home'
        downloads = home/'Downloads'
        downloads.mkdir(parents=True)
        import shutil
        shutil.copyfile(a.zip, downloads/a.zip.name)
        command = next(s for s in (package/'MESSAGE_TO_RECIPIENT.txt').read_text().splitlines() if s.startswith('/bin/bash -c'))
        message_env = dict(os.environ, HOME=str(home))
        if int(subprocess.check_output(['sysctl','-n','hw.memsize'])) < 16*1024**3:
            result = record('exact-recipient-command-resource-refusal', ['/bin/bash','-c',command], expected=(2,), env=message_env)
            if b'BLOCKED' not in result.stderr or (home/'Wit-f09aa63.nosync').exists():
                raise RuntimeError('Resource refusal did not preserve host state')
            record('same-command-repeat-safe', ['/bin/bash','-c',command], expected=(2,), env=message_env)
        report = {'zip_sha256':sha(a.zip), 'source':REVISION, 'source_manifest_sha256':manifest_hash,
                  'checks':steps, 'vm_campaign':'UNTESTED: no VM was started or created'}
        (a.out/'native-verification.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({'checks':len(steps),'all_pass':all(s['ok'] for s in steps),'vm_campaign':report['vm_campaign']}))


if __name__ == '__main__':
    main()
