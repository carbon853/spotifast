#!/usr/bin/python3
"""Explicit source-only upstream integration, never a build or deployment."""
import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('local_pipeline', HERE / 'local.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
m = p.m
Error = m.Error
CONTROLS = re.compile(r'(^|/)(Cargo\.(toml|lock)|build\.rs|rust-toolchain[^/]*|AGENTS\.md|mise\.toml)|^\.cargo/|^\.github/|^packaging/|^native-packages')


class Rebase:
    def __init__(self, repo):
        self.repo = repo
        self.folder = repo.meta / 'scratch/rebase'
        self.state_file = self.folder / 'state.json'

    def state(self):
        if not self.state_file.exists():
            raise Error('no active rebase')
        return json.loads(self.state_file.read_text())

    def check(self):
        # Fetch objects only, with Repo's credential-free public HTTPS environment.
        self.repo.run('fetch', '--no-tags', '--no-recurse-submodules', m.UPSTREAM, 'HEAD')
        pin = self.repo.run('rev-parse', 'FETCH_HEAD^{commit}').decode().strip()
        changed = m.drift(self.repo.read_tree(self.repo.pin()), self.repo.read_tree(pin))
        log = self.repo.run('log', '--format=%h %s', self.repo.pin() + '..' + pin).decode()
        return {'recorded': self.repo.pin(), 'upstream_head': pin, 'commits': log.splitlines(),
                'changed_paths': changed, 'execution_controls': [n for n in changed if CONTROLS.search(n)],
                'decision': 'Review for security, Spotify compatibility, playback, reliability, performance or relevant UX. Documentation/formatting alone do not justify integration. No integration started.'}

    def start(self, ref):
        if self.folder.exists():
            raise Error('active rebase exists; continue or abort first')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*', ref) or '..' in ref:
            raise Error('invalid explicit ref')
        head = p.clean(self.repo)
        self.repo.run('fetch', '--no-tags', '--no-recurse-submodules', m.UPSTREAM, ref)
        pin = self.repo.run('rev-parse', 'FETCH_HEAD^{commit}').decode().strip()
        before = self.repo.read_tree(self.repo.pin())
        after = self.repo.read_tree(pin)
        self.folder.mkdir()
        (self.folder / 'source').mkdir()
        (self.folder / 'patches').mkdir()
        (self.folder / 'original').mkdir()
        names = self.repo.series()
        for name in names:
            shutil.copyfile(self.repo.meta / 'patches' / name, self.folder / 'original' / name)
        state = {'head': head, 'old_pin': self.repo.pin(), 'pin': pin, 'requested_ref': ref,
                 'names': names, 'patch_hashes': {n: p.sha(self.repo.meta / 'patches' / n) for n in names},
                 'index': 0, 'retained': [], 'before': self.repo.tree_id(after), 'phase': 'review', 'conflicts': []}
        self.repo.materialize({}, after, self.folder / 'source')
        changed = m.drift(before, after)
        (self.folder / 'upstream.diff').write_bytes(self.repo.diff(before, after))
        controls = [n for n in changed if CONTROLS.search(n)]
        (self.folder / 'execution-controls.diff').write_bytes(self.repo.diff(
            {n: before[n] for n in controls if n in before}, {n: after[n] for n in controls if n in after}))
        p.save(self.folder / 'review.json', {'pin': pin, 'execution_controls_reviewed': False,
                                            'reason': '', 'behavior_preserved': '', 'resolved_patches': {},
                                            'redundant_patches': {}})
        p.save(self.state_file, state)
        return {'state': state, 'next': 'Review upstream.diff and execution-controls.diff, record review.json, then continue. No downloaded code is executed.'}

    def unchanged(self, state):
        if p.clean(self.repo) != state['head'] or self.repo.pin() != state['old_pin']:
            raise Error('working checkout changed since start; preserve it and abort this candidate')
        if self.repo.series() != state['names'] or any(
                p.sha(self.repo.meta / 'patches' / n) != h for n, h in state['patch_hashes'].items()):
            raise Error('patch series changed since start')

    def review(self, state):
        review = json.loads((self.folder / 'review.json').read_text())
        if (review.get('pin') != state['pin'] or review.get('execution_controls_reviewed') is not True
                or not review.get('reason', '').strip() or not review.get('behavior_preserved', '').strip()):
            raise Error('complete review.json after reviewing dependencies, build scripts, execution controls and patch behavior')
        return review

    def apply_patch(self, state):
        before = self.repo.read_tree(state['before'])
        name = state['names'][state['index']]
        self.repo.run('read-tree', state['before'])
        patch = self.folder / 'original' / name
        try:
            self.repo.run('apply', '--cached', '--whitespace=nowarn', str(patch))
        except Error:
            self.repo.run('read-tree', state['before'])
            try:
                self.repo.run('apply', '--3way', '--cached', '--whitespace=nowarn', str(patch))
            except Error:
                # Materialize stage-zero results and explicit conflicts only. No checkout,
                # filters, hooks, source scripts, or external merge drivers are involved.
                entries = self.repo.run('ls-files', '--stage', '-z').split(b'\0')
                stages = {}
                for entry in entries:
                    if not entry:
                        continue
                    header, raw = entry.split(b'\t', 1)
                    mode, oid, stage = header.decode().split()
                    name_ = raw.decode()
                    m.safe_path(name_)
                    stages.setdefault(name_, {})[stage] = (mode, self.repo.run('cat-file', 'blob', oid))
                result = {}
                conflicts = []
                for name_, versions in stages.items():
                    if '0' in versions:
                        result[name_] = versions['0']
                        continue
                    conflicts.append(name_)
                    base = versions.get('1', ('100644', b''))
                    ours = versions.get('2', ('100644', b''))
                    theirs = versions.get('3', ('100644', b''))
                    if all(mode == '100644' or mode == '100755' for mode, _ in versions.values()) and all(b'\0' not in data for _, data in versions.values()):
                        paths = []
                        for label, data in [('ours', ours[1]), ('base', base[1]), ('theirs', theirs[1])]:
                            path = self.folder / label
                            path.write_bytes(data)
                            paths.append(str(path))
                        merge = subprocess.run(['/usr/bin/git', 'merge-file', '-p', '-L', 'upstream', '-L', 'patch-base', '-L', 'mod', *paths],
                                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=p.ENV)
                        if merge.returncode not in (0, 1):
                            raise Error('cannot render textual conflict')
                        result[name_] = (ours[0], merge.stdout)
                    else:
                        result[name_] = ours
                if not conflicts:
                    # An unmergeable new/deleted file may leave the index untouched.
                    # Do not silently drop that patch: ask for a complete manual application.
                    conflicts = ['manual application of ' + name]
                m.validate(result)
                self.repo.materialize(before, result, self.folder / 'source')
                state.update(phase='conflict', conflicts=conflicts)
                p.save(self.state_file, state)
                return False
        after = self.repo.read_tree(self.repo.run('write-tree').decode().strip())
        self.repo.materialize(before, after, self.folder / 'source')
        self.record_patch(state, before, after)
        return True

    def record_patch(self, state, before, after):
        name = state['names'][state['index']]
        patch = self.repo.diff(before, after)
        if not patch:
            if name == '0001-infrastructure.patch' or not self.review(state).get('redundant_patches', {}).get(name, '').strip():
                raise Error('redundant patch requires documented equivalence in review.json redundant_patches; initial infrastructure must remain')
        else:
            (self.folder / 'patches' / name).write_bytes(patch)
            state['retained'].append(name)
        state.update(index=state['index'] + 1, before=self.repo.tree_id(after), phase='replay', conflicts=[])
        p.save(self.state_file, state)

    def continue_(self, author_name=None, author_email=None):
        state = self.state()
        if state['phase'] in ('publishing', 'published'):
            raise Error('publication already started; inspect recovery.json and working tree before recovery')
        self.unchanged(state)
        review = self.review(state)
        if state['phase'] == 'conflict':
            name = state['names'][state['index']]
            if not review.get('resolved_patches', {}).get(name, '').strip():
                raise Error('record the conflict resolution and preserved behavior in review.json resolved_patches')
            after = self.repo.scan(self.folder / 'source')
            if any(re.search(br'^(<<<<<<<|=======|>>>>>>>)', data, re.M) for _, data in after.values()):
                raise Error('unresolved conflict markers')
            self.record_patch(state, self.repo.read_tree(state['before']), after)
        while state['index'] < len(state['names']):
            if not self.apply_patch(state):
                return {'state': state, 'next': 'Resolve only staging source, compare original patch intent with upstream, document resolution, then continue.'}
        # Independently replay regenerated patches before touching the working tree.
        expected = self.repo.read_tree(state['pin'])
        self.repo.run('read-tree', self.repo.tree_id(expected))
        for name in state['retained']:
            self.repo.run('apply', '--cached', '--whitespace=nowarn', str(self.folder / 'patches' / name))
            expected = self.repo.read_tree(self.repo.run('write-tree').decode().strip())
        if expected != self.repo.scan(self.folder / 'source'):
            raise Error('staging source differs from regenerated series')
        if not author_name or not author_email:
            state['phase'] = 'verified'
            p.save(self.state_file, state)
            return {'state': state, 'next': 'Candidate replay verified. Review source, then continue --author-name NAME --author-email EMAIL to publish one linear local commit. This does not build, push or install.'}
        self.unchanged(state)
        # Keep recovery refs and the full old patch metadata before multi-file writes.
        recovery = self.folder / 'recovery.json'
        p.save(recovery, {'head': state['head'], 'pin': state['old_pin'],
                          'instruction': 'If interrupted, preserve edits and restore root source and metadata from head, then restore the approved submodule with reviewed maintenance tooling. Never force-reset unrelated work.'})
        state['phase'] = 'publishing'
        p.save(self.state_file, state)
        # The existing updater preflights both destinations and never executes source.
        # Swap metadata only after complete replay; update resolves the already immutable SHA.
        try:
            for name in state['names']:
                if name in state['retained']:
                    shutil.copyfile(self.folder / 'patches' / name, self.repo.meta / 'patches' / name)
                else:
                    (self.repo.meta / 'patches' / name).unlink()
            m.atomic(self.repo.meta / 'series', ('\n'.join(state['retained']) + '\n').encode())
            # update() expects old source to match series: publish using its validated
            # materialization and pin metadata primitives directly, with recovery retained.
            old = self.repo.scan()
            old_base = self.repo.read_tree(state['old_pin'])
            new_base = self.repo.read_tree(state['pin'])
            self.repo.materialize(old, expected)
            self.repo.materialize(old_base, new_base, self.repo.root / 'lib/spotifast')
            subgit = self.repo.sub_gitdir()
            alternates = subgit / 'objects/info/alternates'
            existing = alternates.read_text().splitlines() if alternates.exists() else []
            objects = str(self.repo.gitdir / 'objects')
            if objects not in existing:
                m.atomic(alternates, ('\n'.join(existing + [objects]) + '\n').encode())
            m.atomic(subgit / 'HEAD', (state['pin'] + '\n').encode())
            self.repo.run('read-tree', state['pin'], index=subgit / 'index')
            p.save(self.repo.meta / 'upstream.json', {'url': m.UPSTREAM, 'revision': state['pin']})
            self.repo.verify()
            # Preserve review rationale in tracked maintenance history.
            history = self.repo.meta / 'rebases'
            history.mkdir(exist_ok=True)
            p.save(history / (state['pin'] + '.json'), review)
            changed = m.drift(old, expected)
            paths = [*changed, 'lib/spotifast', '.spotifast-mod/upstream.json', '.spotifast-mod/series',
                     '.spotifast-mod/rebases/' + state['pin'] + '.json',
                     *['.spotifast-mod/patches/' + name for name in state['names']]]
            p.git(self.repo.root, 'add', '--', *paths)
            p.git(self.repo.root, '-c', 'user.name=' + author_name, '-c', 'user.email=' + author_email,
                  'commit', '-m', 'Rebase local patch series onto upstream ' + state['pin'][:12])
            state['phase'] = 'published'
            state['commit'] = p.git(self.repo.root, 'rev-parse', 'HEAD').decode().strip()
            p.save(self.state_file, state)
        except BaseException:
            raise Error(f'publication interrupted; recovery metadata retained at {recovery}')
        result = {'commit': state['commit'], 'upstream': state['pin'], 'installed': False}
        shutil.rmtree(self.folder)
        return result

    def abort(self):
        state = self.state()
        if state['phase'] in ('publishing', 'published'):
            raise Error('publication started; retain recovery metadata and inspect before recovery')
        shutil.rmtree(self.folder)
        return 'candidate discarded; working checkout, upstream pin and installed app unchanged'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check', 'start', 'continue', 'abort'])
    parser.add_argument('ref', nargs='?')
    parser.add_argument('--author-name')
    parser.add_argument('--author-email')
    args = parser.parse_args()
    with open(HERE / 'lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        repo = m.Repo(HERE.parent)
        try:
            rebase = Rebase(repo)
            if args.command == 'start':
                if not args.ref:
                    raise Error('explicit upstream ref required')
                result = rebase.start(args.ref)
            elif args.command == 'continue':
                result = rebase.continue_(args.author_name, args.author_email)
            else:
                result = getattr(rebase, args.command)()
            print(json.dumps(result, indent=2))
        finally:
            repo.close()


if __name__ == '__main__':
    try:
        main()
    except (Error, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f'error: {error}', file=sys.stderr)
        sys.exit(1)
