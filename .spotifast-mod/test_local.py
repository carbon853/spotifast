#!/usr/bin/python3
"""Maintenance fixtures only: synthetic packages and source; no app code runs."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent

def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

p = load('local_pipeline_tests', 'local.py')
r = load('rebase_tests', 'rebase.py')
f = load('fixtures', 'test_tool.py')
f.m = r.m


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=HERE / 'scratch')
        self.root = Path(self.temp.name)
        self.payload = self.root / 'payload'
        (self.payload / 'DEBIAN').mkdir(parents=True)
        (self.payload / 'DEBIAN/control').write_text('Package: spotifast\nVersion: 0.13.3\nArchitecture: amd64\nMaintainer: Test <test@example.invalid>\nDescription: fixture\n')
        for name, (_, mode) in p.PAYLOAD.items():
            path = self.payload / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'fixture, never execute\n')
            path.chmod(mode)
        self.deb = self.root / 'fixture.deb'

    def tearDown(self):
        self.temp.cleanup()

    def package(self):
        p.run(['dpkg-deb', '--root-owner-group', '--build', self.payload, self.deb])
        return p.inspect_deb(self.deb)

    def test_exact_payload_and_hashes(self):
        info = self.package()
        self.assertEqual(info['version'], '0.13.3')
        self.assertEqual(set(info['files']), set(p.PAYLOAD))
        self.assertEqual(info['package_sha256'], p.sha(self.deb))

    def test_script_extra_file_symlink_and_mode_rejected(self):
        for kind in ('script', 'extra', 'symlink', 'mode'):
            with self.subTest(kind=kind):
                path = self.payload / 'usr/bin/spotifast'
                original = path.read_bytes()
                extra = self.payload / ('DEBIAN/postinst' if kind == 'script' else 'usr/bin/other')
                if kind in ('script', 'extra'):
                    extra.write_text('do not run\n')
                    extra.chmod(0o755)
                elif kind == 'symlink':
                    path.unlink(); path.symlink_to('/etc/passwd')
                else:
                    path.chmod(0o4755)
                with self.assertRaises(p.Error):
                    self.package()
                if extra.exists(): extra.unlink()
                path.unlink(); path.write_bytes(original); path.chmod(0o755)

    def test_dependency_changes_are_rejected(self):
        for output in (b'Remv unrelated [1]\n', b'Inst spotifast (1 local)\nInst dep (2 local)\n', b''):
            with patch.object(p, 'run', return_value=output), self.assertRaises(p.Error):
                p.transaction(self.deb)
        with patch.object(p, 'run', return_value=b'Inst spotifast [0] (1 local)\n'):
            p.transaction(self.deb)

    def test_sandbox_has_no_host_home_session_or_network(self):
        args = p.sandbox(self.root, ['/usr/bin/true'])
        self.assertIn('--unshare-all', args)
        self.assertNotIn('--share-net', args)
        self.assertIn('--clearenv', args)
        for path in ('/run', '/home/lyon', '/etc', '/'):
            self.assertFalse(any(args[i:i+2] in (['--bind', path], ['--ro-bind', path]) for i in range(len(args))))
        p.run(args)

    def test_relaunch_keeps_configuration_locations_without_reading_files(self):
        overrides = {key: '/dummy/' + key for key in ('HOME', 'XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME')}
        with patch.dict(p.os.environ, overrides, clear=True):
            env = p.desktop_env()
        for key, value in overrides.items():
            self.assertEqual(env[key], value)
        self.assertTrue(all(name.startswith('usr/') for name in p.PAYLOAD))

    def test_smoke_refuses_generated_symlink_before_mounting(self):
        executable = self.root / 'generated'
        executable.symlink_to('/usr/bin/true')
        with patch.object(p, 'run') as run, self.assertRaisesRegex(p.Error, 'without symlink parents'):
            p.smoke(self.root, executable, 'fixture')
        run.assert_not_called()


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=HERE / 'scratch')
        self.root = Path(self.temp.name)
        self.pipeline = object.__new__(p.Pipeline)
        self.pipeline.store = self.root
        self.pipeline.journal = self.root / 'transaction.json'
        self.new = {'version': 'new'}
        self.old = {'version': 'old'}

    def tearDown(self):
        self.temp.cleanup()

    def test_baseline_build_cannot_replace_candidate_cached_executable(self):
        source = self.root / 'source'
        cargo = self.root / 'cargo'
        target = self.root / 'target'
        for folder in (source, cargo, target):
            folder.mkdir()
        (target / 'executable').write_text('candidate')
        (target / 'generated-link').symlink_to('/outside-the-build')
        self.pipeline.toolchain = self.root / 'toolchain'
        self.pipeline.repo = type('Repo', (), {
            'pin': lambda self: 'pin', 'read_tree': lambda self, pin: {},
            'materialize': lambda self, before, after, folder: None})()
        phases = []
        def fake_sandbox(work, command, **kwargs):
            return command, {dest: path for _, path, dest in kwargs['mounts']}
        def fake_run(args, **kwargs):
            command, mounts = args
            executable = mounts['/target'] / 'executable'
            if 'cargo' in command:
                if mounts['/source'].name == 'baseline':
                    self.assertTrue((mounts['/target'] / 'generated-link').is_symlink())
                    executable.write_text('baseline')
                else:
                    self.assertEqual(executable.read_text(), 'candidate')
            else:
                phase = command[-1]
                phases.append(phase)
                self.assertEqual(executable.read_text(), 'baseline' if phase == 'before' else 'candidate')
                for index in range(4):
                    (mounts['/evidence'] / f'{phase}-{index}.png').write_bytes(b'fixture')
        space = type('Disk', (), {'free': 100 * 1024**3})()
        with patch.object(p, 'sandbox', side_effect=fake_sandbox), patch.object(p, 'run', side_effect=fake_run), patch.object(p.shutil, 'disk_usage', return_value=space):
            hashes = self.pipeline.capture_demo(self.root, source, cargo, target)
        self.assertEqual(phases, ['before', 'after'])
        self.assertEqual(len(hashes), 8)
        self.assertEqual((target / 'executable').read_text(), 'candidate')
        self.assertFalse((self.root / 'baseline-target').exists())

    def test_shutdown_failure_never_installs(self):
        with patch.object(p, 'transaction'), patch.object(p, 'run'), patch.object(p, 'running', return_value=True), patch.object(p, 'quit_app', side_effect=p.Error('shutdown failed')), patch.object(p, 'package_install') as install:
            with self.assertRaisesRegex(p.Error, 'shutdown failed'):
                self.pipeline.replace('new.deb', self.new, 'old.deb', self.old, 'commit')
            install.assert_not_called()
            self.assertFalse(self.pipeline.journal.exists())

    def test_failed_install_and_failed_startup_restore_old_package(self):
        for failure in ('install', 'startup'):
            with self.subTest(failure=failure), patch.object(p, 'transaction'), patch.object(p, 'run'), patch.object(p, 'running', side_effect=[True, False]), patch.object(p, 'quit_app'), patch.object(p, 'verify_installed'), patch.object(p, 'smoke'), patch.object(p, 'package_install', side_effect=[p.Error('failed'), None] if failure == 'install' else None) as install, patch.object(p, 'launch_app', side_effect=[p.Error('failed'), None] if failure == 'startup' else None):
                with self.assertRaisesRegex(p.Error, 'previous package restored'):
                    self.pipeline.replace('new.deb', self.new, 'old.deb', self.old, 'commit')
                self.assertEqual([c.args[0] for c in install.call_args_list], ['new.deb', 'old.deb'])
                self.assertEqual(json.loads(self.pipeline.journal.read_text())['state'], 'recovered')

    def test_missing_rollback_prevents_replacement(self):
        with patch.object(self.pipeline, 'artifact', return_value=('new', self.new, {'commit': 'x'})), patch.object(self.pipeline, 'rollback_package', side_effect=p.Error('missing rollback')), patch.object(self.pipeline, 'replace') as replace:
            with self.assertRaisesRegex(p.Error, 'missing rollback'):
                self.pipeline.install('build')
            replace.assert_not_called()

    def test_dirty_source_and_invalid_build_ids_are_rejected(self):
        repo = type('Repo', (), {'root': self.root})()
        with patch.object(p, 'git', return_value=b' M source.rs'), self.assertRaisesRegex(p.Error, 'clean committed'):
            p.clean(repo)
        for value in ('../escape', '/tmp/file', 'x', ''):
            with self.assertRaisesRegex(p.Error, 'invalid build id'):
                self.pipeline.artifact(value)

    def test_failed_mismatched_and_tampered_artifacts_are_rejected(self):
        build_id = 'a' * 12 + '-20261026T000000Z'
        folder = self.root / 'builds' / build_id
        folder.mkdir(parents=True)
        packages = self.root / 'packages'
        packages.mkdir()
        package = packages / 'fixture.deb'
        package.write_bytes(b'never executed')
        self.pipeline.repo = type('Repo', (), {'pin': lambda self: 'pin', 'series': lambda self: []})()
        actual = {'version': '0.14.2', 'package_sha256': 'expected', 'files': {'usr/bin/spotifast': 'hash'}}
        valid = dict(actual, state='verified', commit='commit', upstream='pin', patches={}, package=str(package))
        for mutation in ({'state': 'failed'}, {'commit': 'other'}, {'upstream': 'other'},
                         {'patches': {'unexpected': 'hash'}}, {'package_sha256': 'tampered'}, {'files': {}}):
            with self.subTest(mutation=mutation):
                (folder / 'manifest.json').write_text(json.dumps(dict(valid, **mutation)))
                with patch.object(p, 'clean', return_value='commit'), patch.object(p, 'inspect_deb', return_value=actual), self.assertRaises(p.Error):
                    self.pipeline.artifact(build_id)


class RebaseTests(f.MaintenanceTests):
    def setup_candidate(self, conflicting=False):
        modified = dict(self.base, a=('100644', b'mod\n'))
        self.change(modified)
        self.r.capture('feature')
        self.stage(modified)
        upstream = dict(self.base, a=('100644', b'upstream\n')) if conflicting else dict(self.base, new=('100644', b'upstream\n'))
        new_pin = self.commit(upstream)
        rebase = r.Rebase(self.r)
        original_run = self.r.run
        def run(*args, **kwargs):
            if args[0] == 'fetch': return b''
            if args[:2] == ('rev-parse', 'FETCH_HEAD^{commit}'): return (new_pin + '\n').encode()
            return original_run(*args, **kwargs)
        with patch.object(r.p, 'clean', return_value='a' * 40), patch.object(self.r, 'run', side_effect=run):
            rebase.start('explicit-ref')
        review = {'pin': new_pin, 'execution_controls_reviewed': True, 'reason': 'reliability fix', 'behavior_preserved': 'feature retained', 'resolved_patches': {}}
        r.p.save(rebase.folder / 'review.json', review)
        return rebase, modified, review

    def test_clean_rebase_and_abort_preserve_root_pin_and_order(self):
        rebase, modified, _ = self.setup_candidate()
        with patch.object(r.p, 'clean', return_value='a' * 40):
            result = rebase.continue_()
        self.assertEqual(result['state']['phase'], 'verified')
        self.assertEqual(result['state']['names'], ['0001-feature.patch'])
        self.assertEqual(self.r.scan(), modified)
        self.assertEqual(self.r.pin(), self.pin)
        self.assertEqual((rebase.folder / 'source/a').read_bytes(), b'mod\n')
        rebase.abort()
        self.assertFalse(rebase.folder.exists())
        self.assertEqual(self.r.scan(), modified)

    def test_conflict_requires_resolution_record_and_replays_it(self):
        rebase, modified, review = self.setup_candidate(conflicting=True)
        with patch.object(r.p, 'clean', return_value='a' * 40):
            result = rebase.continue_()
            self.assertEqual(result['state']['phase'], 'conflict')
            self.assertEqual(self.r.scan(), modified)
            with self.assertRaisesRegex(r.Error, 'record the conflict'):
                rebase.continue_()
            review['resolved_patches']['0001-feature.patch'] = 'retained upstream and mod behavior'
            r.p.save(rebase.folder / 'review.json', review)
            with self.assertRaisesRegex(r.Error, 'conflict markers'):
                rebase.continue_()
            (rebase.folder / 'source/a').write_bytes(b'upstream and mod\n')
            self.assertEqual(rebase.continue_()['state']['phase'], 'verified')
            self.assertEqual(self.r.pin(), self.pin)
            self.assertEqual(self.r.scan(), modified)

    def test_review_gate_and_interrupted_publish_keep_recovery(self):
        rebase, _, review = self.setup_candidate()
        review['execution_controls_reviewed'] = False
        r.p.save(rebase.folder / 'review.json', review)
        with patch.object(r.p, 'clean', return_value='a' * 40), self.assertRaisesRegex(r.Error, 'complete review'):
            rebase.continue_()
        state = rebase.state(); state['phase'] = 'publishing'; r.p.save(rebase.state_file, state)
        with self.assertRaisesRegex(r.Error, 'recovery'):
            rebase.abort()
        self.assertTrue(rebase.folder.exists())

    def test_redundant_patch_needs_equivalence_and_preserves_order(self):
        rebase, _, review = self.setup_candidate(conflicting=True)
        with patch.object(r.p, 'clean', return_value='a' * 40):
            rebase.continue_()
            review['resolved_patches']['0001-feature.patch'] = 'upstream implements the same feature'
            r.p.save(rebase.folder / 'review.json', review)
            (rebase.folder / 'source/a').write_bytes(b'upstream\n')
            with self.assertRaisesRegex(r.Error, 'documented equivalence'):
                rebase.continue_()
            review['redundant_patches'] = {'0001-feature.patch': 'fixture: upstream text replaces the feature; exact source replay verified'}
            r.p.save(rebase.folder / 'review.json', review)
            state = rebase.continue_()['state']
            self.assertEqual(state['names'], ['0001-feature.patch'])
            self.assertEqual(state['retained'], [])
            self.assertEqual(state['phase'], 'verified')

    def test_capture_after_number_gap_uses_next_number(self):
        modified = dict(self.base, a=('100644', b'mod\n'))
        self.change(modified)
        self.r.capture('feature')
        patches = self.r.meta / 'patches'
        (patches / '0001-feature.patch').rename(patches / '0003-feature.patch')
        (self.r.meta / 'series').write_text('0003-feature.patch\n')
        self.change(dict(modified, a=('100644', b'another mod\n')))
        self.r.capture('next')
        self.assertEqual(self.r.series(), ['0003-feature.patch', '0004-next.patch'])

    def test_publication_makes_one_linear_commit_and_updates_submodule_index(self):
        rebase, modified, _ = self.setup_candidate()
        parent = self.commit(modified)
        r.p.git(self.root, 'update-ref', 'refs/heads/main', parent)
        r.p.git(self.root, 'symbolic-ref', 'HEAD', 'refs/heads/main')
        with patch.object(r.p, 'clean', return_value='a' * 40):
            result = rebase.continue_('Fixture', 'fixture@example.invalid')
        self.assertEqual(r.p.git(self.root, 'show', '-s', '--format=%P', result['commit']).decode().strip(), parent)
        self.assertEqual(self.r.pin(), result['upstream'])
        self.r.verify()
        self.assertEqual(self.r.run('write-tree', index=self.r.sub_gitdir() / 'index').decode().strip(), self.r.tree_id(self.r.read_tree(self.r.pin())))
        self.assertFalse(result['installed'])


if __name__ == '__main__':
    unittest.main()
