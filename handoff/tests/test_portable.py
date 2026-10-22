"""Packaging/control tests use temporary files and explicit fixtures, never real VMs."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

HANDOFF = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HANDOFF))
import launcher as L
import build_package as B


class Portable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='witness-extracted-different-name-')
        cls.root = Path(cls.temp.name)
        cls.zip = Path(os.environ.get('WITNESS_TEST_ZIP', str(HANDOFF.parent/'dist'/B.ZIP_NAME))).resolve()
        with zipfile.ZipFile(cls.zip) as z:
            for i in z.infolist():
                assert not Path(i.filename).is_absolute() and '..' not in Path(i.filename).parts
            z.extractall(cls.root)
            for i in z.infolist():
                p = cls.root/i.filename
                p.chmod((i.external_attr >> 16) & 0o777)
        cls.package = cls.root/B.ROOT_NAME

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='witness-wrapper-unit-')
        self.work = Path(self.tmp.name)/'isolated.nosync'

    def tearDown(self):
        self.tmp.cleanup()

    def coordinator(self):
        return L.Coordinator(self.package, self.work)

    def test_export_integrity_and_original_source(self):
        self.assertRegex(L.verify_package(self.package), '^[a-f0-9]{64}$')
        manifest = json.loads((self.package/'SOURCE_MANIFEST.json').read_text())
        self.assertEqual(manifest['original_commit'], L.REVISION)
        for entry in manifest['files']:
            if entry['path'].startswith(('device/', 'gateway/', 'runner/', 'tests/', 'scripts/')):
                self.assertEqual(entry['original_sha256'], entry['export_sha256'], entry['path'])
        self.assertEqual(L.sha(self.package/'source/PROJECT_BRIEF.md'), manifest['brief_sha256'])

    def test_no_evidence_disks_keys_or_symlinks(self):
        for path in self.package.rglob('*'):
            self.assertFalse(path.is_symlink())
            if path.is_file():
                self.assertFalse(path.suffix in ('.db', '.pcap', '.qcow2', '.img', '.pem', '.key', '.sock'))
                self.assertIsNone(B.SECRET.search(path.read_bytes()), str(path))
                self.assertIsNone(B.HOST_PATH.search(path.read_bytes()), str(path))
        self.assertFalse((self.package/'source/results').exists())

    def test_executable_permissions(self):
        for name in ('RUN_ON_THIS_MAC.sh', 'RETURN_RESULTS.sh', 'source/scripts/provision_ctl.sh'):
            self.assertTrue(os.access(self.package/name, os.X_OK))

    def test_shell_syntax_and_extracted_relative_paths(self):
        for path in self.package.rglob('*.sh'):
            subprocess.run(['/bin/bash', '-n', str(path)], check=True, capture_output=True)
        out = subprocess.check_output(['/bin/bash', str(self.package/'RUN_ON_THIS_MAC.sh'), '--verify'], cwd='/')
        self.assertIn(b'verified', out)

    def altered_package(self):
        p = Path(self.tmp.name)/'package-copy'
        shutil.copytree(self.package, p)
        return p

    def test_missing_source_file_rejected(self):
        p = self.altered_package()
        (p/'source/runner/client.py').unlink()
        with self.assertRaises(L.Failed):
            L.verify_package(p)

    def test_tampered_file_rejected(self):
        p = self.altered_package()
        (p/'source/inventory.yaml').write_text('wrong')
        with self.assertRaises(L.Failed):
            L.verify_package(p)

    def test_unexpected_extra_file_rejected(self):
        p = self.altered_package()
        (p/'unexpected.txt').write_text('extra')
        with self.assertRaises(L.Failed):
            L.verify_package(p)

    def test_escaping_symlink_rejected(self):
        p = self.altered_package()
        (p/'escape').symlink_to('/etc/passwd')
        with self.assertRaises(L.Failed):
            L.verify_package(p)

    def test_manifest_traversal_rejected(self):
        p = self.altered_package()
        (p/'SHA256SUMS').write_text('a'*64+'  ../outside\n')
        with self.assertRaises(L.Failed):
            L.verify_package(p)

    def test_unowned_directory_refused(self):
        self.work.mkdir()
        sentinel = self.work/'unrelated.txt'
        sentinel.write_text('preserve')
        with self.assertRaises(L.Blocked):
            self.coordinator()
        self.assertEqual(sentinel.read_text(), 'preserve')

    def test_work_symlink_refused(self):
        target = Path(self.tmp.name)/'other'
        target.mkdir()
        self.work.symlink_to(target)
        with self.assertRaises(L.Blocked):
            self.coordinator()

    def test_source_owner_mismatch_refused(self):
        L.claim_work(self.work, 'wrong-manifest')
        with self.assertRaises(L.Blocked):
            self.coordinator()

    def test_exclusive_lab_lock(self):
        c = self.coordinator()
        with self.assertRaises(L.Blocked):
            self.coordinator()
        c.lock.close()

    def test_isolated_environment_ignores_inherited_lima(self):
        with patch.dict(os.environ, {'LIMA_HOME':'/unrelated', 'WIT_LIMA_HOME':'/unrelated', 'SECRET_TEST':'hidden'}):
            c = self.coordinator()
        self.assertEqual(c.env['LIMA_HOME'], str(self.work/'lima'))
        self.assertNotIn('SECRET_TEST', c.env)
        self.assertNotIn('WIT_LIMA_HOME', c.env)
        c.lock.close()

    def sample(self, **changes):
        x = dict(ram_bytes=16*L.GIB, free_bytes=40*L.GIB, pressure=1, swap_mib=0)
        x.update(changes)
        return x

    def test_resource_supported_entry(self):
        self.assertIsNone(L.resource_problem(self.sample(), initial=True))

    def test_8gib_host_blocked(self):
        self.assertIn('16 GiB', L.resource_problem(self.sample(ram_bytes=8*L.GIB)))

    def test_15gib_disk_blocked(self):
        self.assertIn('disk', L.resource_problem(self.sample(free_bytes=15*L.GIB), initial=True))

    def test_floor_and_critical_pressure(self):
        self.assertIn('disk', L.resource_problem(self.sample(free_bytes=11*L.GIB)))
        self.assertIn('pressure', L.resource_problem(self.sample(pressure=4)))

    def test_swap_trend_and_absolute_gate(self):
        self.assertIn('grew', L.resource_problem(self.sample(swap_mib=1500), swap_initial=0))
        self.assertIn('exceeds', L.resource_problem(self.sample(swap_mib=4200)))

    def test_full_copy_gate_no_apfs_credit(self):
        self.assertIn('34.00', L.resource_problem(self.sample(free_bytes=33*L.GIB), allocation=20*L.GIB))
        self.assertIsNone(L.resource_problem(self.sample(free_bytes=34*L.GIB), allocation=20*L.GIB))

    def test_route_conflicts_include_vpn_aggregate(self):
        self.assertEqual(L.route_conflicts('default 192.168.1.1 UGSc\n192.168.1/24 link#2 UCS\n'), [])
        for line in ('10/8 10.0.0.1 UGSc', '10.77.1/24 link#3 UCS', '10.77.2.11 1.1.1.1 UH'):
            self.assertEqual(L.route_conflicts(line), [line])

    def test_unrelated_private_lima_instance_refused_without_deletion(self):
        c = self.coordinator()
        c.ctl = Mock(return_value='unrelated-vm\n')
        with self.assertRaises(L.Blocked):
            c.assert_home()
        self.assertEqual(c.ctl.call_count, 1)
        self.assertEqual(c.state['vm_claims'], {})
        c.lock.close()

    def test_same_named_but_unclaimed_instance_refused(self):
        c = self.coordinator()
        c.ctl = Mock(return_value='witness-ctl\n')
        with self.assertRaises(L.Blocked):
            c.assert_home()
        c.lock.close()

    def test_claimed_vm_symlink_is_refused(self):
        c = self.coordinator()
        home = c.work/'lima'
        home.mkdir()
        (home/'witness-ctl').symlink_to(Path(self.tmp.name), target_is_directory=True)
        c.state['vm_claims']['witness-ctl'] = {'owner':c.owner['id']}
        c.ctl = Mock()
        with self.assertRaises(L.Failed):
            c.assert_home()
        c.ctl.assert_not_called()
        c.lock.close()

    def test_atomic_checkpoint_and_resume_skips_success(self):
        c = self.coordinator()
        c.gate = Mock()
        action = Mock()
        c.step('dependencies', action)
        c.step('dependencies', action)
        self.assertEqual(action.call_count, 1)
        self.assertEqual(json.loads(c.statefile.read_text())['steps']['dependencies']['status'], 'PASS')
        self.assertFalse(c.statefile.with_suffix('.json.new').exists())
        c.lock.close()
        d = self.coordinator()
        d.step('dependencies', action)
        self.assertEqual(action.call_count, 1)
        d.lock.close()

    def test_blocked_retry_retains_attempt(self):
        c = self.coordinator()
        c.gate = Mock()
        with self.assertRaises(L.Blocked):
            c.step('provision', Mock(side_effect=L.Blocked('fixture resource blocker')))
        c.step('provision', Mock())
        self.assertEqual([a['status'] for a in c.state['attempts']], ['BLOCKED', 'PASS'])
        c.lock.close()

    def test_replacement_transaction_resumes_same_creation(self):
        c = self.coordinator()
        c.space_for_pair, c.fetch, c.delete_pair = Mock(), Mock(), Mock()
        first = c.begin_replacement('restore-1').copy()
        second = c.begin_replacement('restore-1').copy()
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(c.delete_pair.call_count, 1)
        c.lock.close()

    def test_replacement_interrupted_delete_is_retried(self):
        c = self.coordinator()
        c.space_for_pair, c.fetch = Mock(), Mock()
        c.delete_pair = Mock(side_effect=L.Blocked('fixture interruption'))
        with self.assertRaises(L.Blocked):
            c.begin_replacement('restore-1')
        identifier = c.state['replacement']['id']
        c.delete_pair = Mock()
        self.assertEqual(c.begin_replacement('restore-1')['id'], identifier)
        c.space_for_pair.assert_called_once()
        c.lock.close()

    def test_continuation_fetches_surviving_guest_before_push(self):
        c = self.coordinator()
        target = c.output/'evidence/main'
        (target/'evidence').mkdir(parents=True)
        import sqlite3
        with sqlite3.connect(target/'witness.db') as conn:
            conn.execute('create table runs(run_id integer)')
            conn.execute('insert into runs values(2)')
        c.python = Mock(return_value='{"exists":true,"max":3}')
        c.fetch, c.gsh = Mock(), Mock()
        c.push()
        c.fetch.assert_called_once()
        c.lock.close()

    def test_older_guest_cannot_overwrite_master(self):
        c = self.coordinator()
        target = c.output/'evidence/main'
        (target/'evidence').mkdir(parents=True)
        import sqlite3
        with sqlite3.connect(target/'witness.db') as conn:
            conn.execute('create table runs(run_id integer)')
            conn.execute('insert into runs values(2)')
        c.python = Mock(return_value='{"exists":true,"max":1}')
        c.fetch, c.gsh = Mock(), Mock()
        with self.assertRaises(L.Failed):
            c.push()
        c.fetch.assert_not_called()
        c.gsh.assert_not_called()
        c.lock.close()

    def test_initial_sync_uses_existing_root_workdir(self):
        c = self.coordinator()
        c.ctl = Mock()
        c.gsh('witness-ctl', 'identity-witness-ctl', ['true'])
        self.assertEqual(c.ctl.call_args.args[3], '/')
        c.gsh('witness-ctl', 'suite-baseline', ['true'])
        self.assertEqual(c.ctl.call_args.args[3], '/opt/witness-lab')
        c.lock.close()

    def test_command_logging_real_subprocess(self):
        c = self.coordinator()
        out = c.run('portable-command', [sys.executable, '-c', 'import sys;print("unit stdout");print("unit stderr",file=sys.stderr)'], monitor=False)
        self.assertIn('unit stdout', out)
        meta = json.loads(next(c.logs.glob('*.json')).read_text())
        self.assertEqual(meta['exit_status'], 0)
        self.assertIn('start', meta)
        self.assertIn('end', meta)
        self.assertIn('unit stderr', next(c.logs.glob('*.stderr')).read_text())
        c.lock.close()

    def test_command_timeout_is_failure_with_retained_exit(self):
        c = self.coordinator()
        with self.assertRaises(L.Failed):
            c.run('bounded-timeout', [sys.executable, '-c', 'import time;time.sleep(20)'], limit=0.1, monitor=False)
        meta = json.loads(next(c.logs.glob('*.json')).read_text())
        self.assertNotEqual(meta['exit_status'], 0)
        self.assertIn('timeout', meta['termination_reason'])
        c.lock.close()

    def test_monitor_block_terminates_child(self):
        c = self.coordinator()
        c.sample = Mock(return_value=self.sample(pressure=4))
        with self.assertRaises(L.Blocked):
            c.run('resource-stop', [sys.executable, '-c', 'import time;time.sleep(20)'])
        self.assertIsNone(c.active)
        c.lock.close()

    def test_safety_commands_can_run_when_resource_gate_is_red(self):
        c = self.coordinator()
        c.sample = Mock(return_value=self.sample(pressure=4))
        c.in_safety = True
        self.assertIn('cleanup', c.run('safety-unit', [sys.executable, '-c', 'print("cleanup")']))
        c.sample.assert_not_called()
        c.lock.close()

    def test_report_cannot_grant_full_without_all_experiments(self):
        c = self.coordinator()
        self.assertEqual(c.report(), 'PARTIAL ACCEPTANCE — BLOCKED')
        c.state['steps']['provision'] = {'status':'FAIL'}
        self.assertEqual(c.report(), 'ACCEPTANCE FAILED')
        self.assertIn('UNTESTED', (c.output/'COMPLETION_REPORT.md').read_text())
        c.lock.close()

    def test_return_archive_includes_only_output(self):
        c = self.coordinator()
        c.checkpoint()
        c.report()
        (c.work/'private-key').write_text('not for export')
        with contextlib.redirect_stdout(io.StringIO()):
            archive = L.return_archive(c.work)
        with zipfile.ZipFile(archive) as z:
            self.assertTrue(all(n.startswith('Witness-Return/') for n in z.namelist()))
            self.assertFalse(any('private-key' in n for n in z.namelist()))
            self.assertIn('Witness-Return/RETURN_SHA256SUMS', z.namelist())
        c.lock.close()

    def test_return_rejects_symlink(self):
        c = self.coordinator()
        c.checkpoint()
        (c.output/'escape.txt').symlink_to('/etc/passwd')
        with self.assertRaises(L.Failed):
            L.return_archive(c.work)
        c.lock.close()

    def test_return_rejects_credential_pattern(self):
        c = self.coordinator()
        c.checkpoint()
        (c.output/'unexpected.txt').write_text('ghp_'+'a'*36)
        with self.assertRaises(L.Failed):
            L.return_archive(c.work)
        c.lock.close()

    def test_entry_resource_refusal_is_non_destructive_on_builder(self):
        # The real builder has 8 GiB RAM: exercise the real shell gate, never consent.
        if sys.platform != 'darwin' or int(subprocess.check_output(['sysctl','-n','hw.memsize'])) >= 16*L.GIB:
            self.skipTest('Builder negative gate requires <16 GiB Mac')
        env = dict(os.environ, HOME=self.tmp.name)
        proc = subprocess.run(['/bin/bash', str(self.package/'RUN_ON_THIS_MAC.sh')], env=env, capture_output=True, timeout=30)
        self.assertEqual(proc.returncode, 2)
        self.assertIn(b'BLOCKED', proc.stderr)
        self.assertFalse((Path(self.tmp.name)/'Wit-f09aa63.nosync').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
