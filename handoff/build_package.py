#!/usr/bin/env python3
"""Build from an immutable Git source revision, never from ignored VM/evidence trees."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from launcher import REVISION, sha, verify_package, IMAGE_URL, IMAGE_SHA, LIMA_URL, LIMA_SHA

ROOT_NAME = 'Witness-Reproduction-f09aa63'
ZIP_NAME = ROOT_NAME+'-v1.zip'
SECRET = re.compile(rb'-----BEGIN (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----\s+[A-Za-z0-9+/=\r\n]{80,}|gh[pousr]_[A-Za-z0-9]{30,}|(?:AKIA|ASIA)[A-Z0-9]{16}|sk-[A-Za-z0-9]{32,}')
HOST_PATH = re.compile(rb'/Users/[^/\s`"\x27]+')


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args])


def history_audit(repo):
    listing = git(repo, 'rev-list', '--objects', '--all').decode().splitlines()
    names = dict((s.split(' ', 1)+[''])[:2] for s in listing)
    proc = subprocess.Popen(['git', '-C', str(repo), 'cat-file', '--batch'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    scanned = 0
    hits, path_count = [], 0
    for oid in names:
        proc.stdin.write((oid+'\n').encode())
        proc.stdin.flush()
        header = proc.stdout.readline().decode().split()
        if len(header) != 3:
            raise RuntimeError('Invalid git object response')
        size = int(header[2])
        data = proc.stdout.read(size)
        if proc.stdout.read(1) != b'\n':
            raise RuntimeError('Truncated Git object')
        if header[1] == 'blob':
            scanned += 1
            path_count += bool(HOST_PATH.search(data))
            if SECRET.search(data):
                hits.append({'object': oid, 'path': names[oid]})
    proc.stdin.close()
    proc.wait(timeout=10)
    # No blob contents, author emails, remote URLs or secret values enter the report.
    return {'reachable_blobs_scanned': scanned, 'blobs_with_absolute_home_paths': path_count,
            'possible_secret_objects': hits, 'history_exported': False}


def build(repo, out, verification=None):
    repo, out = Path(repo).resolve(), Path(out).absolute()
    out.mkdir(parents=True, exist_ok=True)
    target = out/ROOT_NAME
    if target.exists():
        if not (target/'.witness-distribution-build').is_file():
            raise RuntimeError('Refusing to overwrite an unrelated directory: '+str(target))
        shutil.rmtree(target)  # only this builder's exact staged artifact; never a lab/work directory
    target.mkdir()
    (target/'.witness-distribution-build').write_text('Witness distribution stage v1\n')
    source = target/'source'
    source.mkdir()
    files, excluded, redactions = [], [], []
    tree = git(repo, 'ls-tree', '-rz', REVISION).split(b'\0')
    for row in tree:
        if not row:
            continue
        meta, name_bytes = row.split(b'\t', 1)
        mode, kind, oid = meta.decode().split()
        name = name_bytes.decode()
        if name.startswith('results/') or mode == '120000':
            excluded.append({'path': name, 'mode': mode, 'object': oid})
            continue
        if kind != 'blob' or Path(name).is_absolute() or '..' in Path(name).parts:
            raise RuntimeError('Unexpected Git tree member')
        data = git(repo, 'cat-file', 'blob', oid)
        original = hashlib.sha256(data).hexdigest()
        if SECRET.search(data):
            raise RuntimeError('Possible credential in export candidate: '+name)
        if HOST_PATH.search(data):
            if not name.startswith('docs/'):
                raise RuntimeError('Machine-specific path in source candidate: '+name)
            data = HOST_PATH.sub(b'<original-home>', data)
            redactions.append(name)
        path = source/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(0o755 if mode == '100755' else 0o644)
        files.append({'path': name, 'git_blob': oid, 'git_mode': mode,
                      'original_sha256': original, 'export_sha256': hashlib.sha256(data).hexdigest()})
    manifest = {'format': 'Witness clean source snapshot v1', 'original_commit': REVISION,
                'last_tested_runtime_commit': '3d7a9f74c81f80a1a84f790f7aa01f5254e5aa0f',
                'builder_commit': git(repo, 'rev-parse', 'HEAD').decode().strip(),
                'brief_sha256': sha(source/'PROJECT_BRIEF.md'), 'files': files,
                'documentation_home_path_redactions': redactions,
                'excluded': ['All results/ (historical stores, pcaps, console logs and evidence links)',
                             '.git history and personal author metadata', 'Ignored/untracked content, original Lima disks/keys, caches and venvs'],
                'history_limitation': 'This snapshot recovers runnable source and original blob identities, not the original Git repository history.'}
    (target/'SOURCE_MANIFEST.json').write_text(json.dumps(manifest, indent=2)+'\n')
    (target/'EXCLUDED_TRACKED_MANIFEST.json').write_text(json.dumps(excluded, indent=2)+'\n')
    audit = history_audit(repo)
    ignored = git(repo, 'ls-files', '--others', '--ignored', '--exclude-standard', '-z').split(b'\0')
    untracked = git(repo, 'ls-files', '--others', '--exclude-standard', '-z').split(b'\0')
    (out/'BUILDER_INPUT_INVENTORY.json').write_text(json.dumps({
        'ignored_path_count':sum(bool(x) for x in ignored), 'untracked_path_count':sum(bool(x) for x in untracked),
        'policy':'Every ignored/untracked path is excluded; no credential/image contents read or copied'
    }, indent=2)+'\n')
    audit.update(ignored_or_untracked_exported=False, tracked_symlinks_excluded=sum(x['mode']=='120000' for x in excluded))
    (target/'EXPORT_AUDIT.json').write_text(json.dumps(audit, indent=2)+'\n')
    (target/'DEPENDENCIES.json').write_text(json.dumps({
        'lima': {'version':'2.2.0', 'url':LIMA_URL, 'sha256':LIMA_SHA, 'install':'private workspace'},
        'ubuntu': {'release':'24.04 ARM64 release-20260705', 'url':IMAGE_URL, 'sha256':IMAGE_SHA, 'cache':'verified local file; no shared Lima cache'},
        'python_if_missing': {'version':'3.13.9', 'url':'https://www.python.org/ftp/python/3.13.9/python-3.13.9-macos11.pkg',
                              'sha256':'dafebf62b8737f341f6b7eca2d6d1153a50a6b1bfbfa4b8aaf0e62adc73e5017',
                              'signer':'Python Software Foundation (BMM5U3QVKW)', 'supported_existing':'3.12–3.14'},
        'ubuntu_apt':'Signed Ubuntu repositories; exact installed versions recorded, not a frozen OS build'
    }, indent=2)+'\n')
    (target/'RELEVANT_COMMITS.txt').write_bytes(git(repo, 'log', '--reverse', '--format=%H %s', REVISION))
    helpers = ['RUN_ON_THIS_MAC.sh', 'RETURN_RESULTS.sh', 'launcher.py', 'guest_verify.py', 'deadline_probe.py',
               'interrupt_probe.py', 'HANDOFF.md', 'MESSAGE_TO_RECIPIENT.txt', 'BUILDER_VERIFICATION.md']
    for name in helpers:
        shutil.copyfile((verification if name == 'BUILDER_VERIFICATION.md' and verification else repo/'handoff'/name), target/name)
        (target/name).chmod(0o755 if name.endswith('.sh') else 0o644)
    for p in target.rglob('*'):
        if p.is_symlink() or not p.is_file() and not p.is_dir():
            raise RuntimeError('Unsupported packaged object: '+str(p))
        if p.is_file() and SECRET.search(p.read_bytes()):
            raise RuntimeError('Possible secret in package: '+str(p.relative_to(target)))
    sums = ''.join(sha(p)+'  '+p.relative_to(target).as_posix()+'\n' for p in sorted(target.rglob('*')) if p.is_file())
    (target/'SHA256SUMS').write_text(sums)
    verify_package(target)
    zip_path = out/ZIP_NAME
    timestamp = dt.datetime.fromtimestamp(int(git(repo, 'show', '-s', '--format=%ct', REVISION)), dt.timezone.utc)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(target.rglob('*')):
            if p.is_file():
                info = zipfile.ZipInfo(ROOT_NAME+'/'+p.relative_to(target).as_posix(), timestamp.timetuple()[:6])
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | (0o755 if p.stat().st_mode & 0o111 else 0o644)) << 16
                z.writestr(info, p.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    info = {'zip': str(zip_path), 'bytes': zip_path.stat().st_size, 'sha256': sha(zip_path),
            'packaged_files': len(list(target.rglob('*'))), 'source_files': len(files), 'source_revision': REVISION}
    (out/(ZIP_NAME+'.sha256')).write_text(info['sha256']+'  '+ZIP_NAME+'\n')
    (out/'RELEASE.json').write_text(json.dumps(info, indent=2)+'\n')
    shutil.copyfile(target/'MESSAGE_TO_RECIPIENT.txt', out/'MESSAGE_TO_RECIPIENT.txt')
    print(json.dumps(info, indent=2))
    return zip_path


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    build(a.repo, a.out)
