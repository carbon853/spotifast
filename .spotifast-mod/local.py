#!/usr/bin/python3
"""Reviewed local deployment. No source integration, hooks, mise or workflows."""
import argparse
import fcntl
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import urllib.request

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('maintenance', HERE / 'tool.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
Error = m.Error
RUST = '1.98.0'
TRIPLE = 'x86_64-unknown-linux-gnu'
ENV = {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'LC_ALL': 'C',
       'TMPDIR': str(HERE / 'scratch'),
       'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
       'GIT_TERMINAL_PROMPT': '0'}
PAYLOAD = {
    'usr/bin/spotifast': ('target/release/spotifast', 0o755),
    'usr/share/applications/spotifast.desktop': ('packaging/applications/spotifast.desktop', 0o644),
    'usr/share/icons/hicolor/scalable/apps/spotifast.svg': ('packaging/icons/spotifast.svg', 0o644),
    'usr/share/doc/spotifast/README.md': ('README.md', 0o644),
    'usr/share/licenses/spotifast/LICENSE': ('LICENSE', 0o644),
    'usr/share/spotifast/omarchy/spotifast-theme': ('contrib/omarchy/spotifast-theme', 0o755),
    'usr/share/spotifast/omarchy/spotifast.json.tpl': ('contrib/omarchy/spotifast.json.tpl', 0o644),
}
DEPS = ('libdbus-1-3, libc6 (>= 2.39), libgl1, libegl1, libxkbcommon0, '
        'libxkbcommon-x11-0, libwayland-client0, libwayland-cursor0, libwayland-egl1, '
        'libx11-6, libx11-xcb1, libxcursor1, libxi6, libxrandr2, libasound2t64, '
        'libpipewire-0.3-0t64 | libpipewire-0.3-0, libgcc-s1, libstdc++6')


def run(args, *, cwd=None, env=None, capture=True, data=None):
    p = subprocess.run([str(a) for a in args], cwd=cwd, env=env or ENV, input=data,
                       stdout=subprocess.PIPE if capture else None,
                       stderr=subprocess.PIPE if capture else None)
    if p.returncode:
        message = p.stderr.decode(errors='replace') if capture else 'see command output'
        raise Error(f'{args[0]} failed ({p.returncode}): {message.strip()}')
    return p.stdout if capture else b''


def sha(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, obj):
    m.atomic(path, (json.dumps(obj, indent=2, sort_keys=True) + '\n').encode())


def download(url, path):
    if not url.startswith('https://'):
        raise Error('HTTPS required')
    with urllib.request.urlopen(url, timeout=60) as response, open(path, 'wb') as out:
        shutil.copyfileobj(response, out)


def git(root, *args):
    return run(['/usr/bin/git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
                '-c', 'core.attributesFile=/dev/null', '-c', 'diff.external=',
                '--git-dir=' + str(root / '.git'), '--work-tree=' + str(root), *args])


def clean(repo):
    if git(repo.root, 'status', '--porcelain', '--untracked-files=all').strip():
        raise Error('requires a clean committed checkout')
    if git(repo.root, 'branch', '--show-current').strip() != b'main':
        raise Error('requires main')
    repo.verify()
    return git(repo.root, 'rev-parse', 'HEAD').decode().strip()


def installer_only_since(repo, built, current):
    """Keep an artifact's original provenance across reviewed installer repairs."""
    import ast

    if built == current:
        return True
    if not all(re.fullmatch(r'[0-9a-f]{40}', value) for value in (built, current)):
        return False
    try:
        git(repo.root, 'merge-base', '--is-ancestor', built, current)
        changed = git(repo.root, 'diff', '--name-only', '-z', built, current, '--').split(b'\0')
    except Error:
        return False
    allowed = {b'.spotifast-mod/local.py', b'.spotifast-mod/test_local.py', b'.spotifast-mod/README.md'}
    if any(path not in allowed for path in changed if path):
        return False
    # local.py also contains the build sandbox and compiler controls. Require
    # those definitions to remain identical, not merely the filename allowlist.
    def build_policy(revision):
        tree = ast.parse(git(repo.root, 'show', revision + ':.spotifast-mod/local.py'))
        tree.body = [node for node in tree.body if not (
            isinstance(node, ast.FunctionDef) and node.name in
            {'installer_only_since', 'transaction', 'package_install'})]
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == 'Pipeline':
                node.body = [method for method in node.body if not (
                    isinstance(method, ast.FunctionDef) and method.name in
                    {'artifact', 'install', 'replace', 'recover_previous', 'rollback'})]
        return ast.dump(tree, include_attributes=False)
    try:
        return build_policy(built) == build_policy(current)
    except (Error, SyntaxError):
        return False


def snapshot_index(repo, source):
    """Minimal independent Git metadata for repository checks, without host refs/config."""
    run(['git', '-c', 'init.templateDir=', 'init', '-q', source])
    repo.env.update(GIT_AUTHOR_NAME='Snapshot', GIT_AUTHOR_EMAIL='snapshot@localhost',
                    GIT_COMMITTER_NAME='Snapshot', GIT_COMMITTER_EMAIL='snapshot@localhost')
    commits = []
    for tree in (repo.read_tree(repo.pin()), repo.verify()):
        commits.append(repo.run('commit-tree', repo.tree_id(tree), data=b'Isolated source snapshot\n').decode().strip())
    pack = repo.run('pack-objects', '--stdout', '--revs', data=('\n'.join(commits) + '\n').encode())
    run(['git', '--git-dir=' + str(source / '.git'), 'index-pack', '--stdin'], data=pack)
    git(source, 'update-ref', 'refs/heads/baseline', commits[0])
    git(source, 'update-ref', 'refs/heads/main', commits[1])
    git(source, 'symbolic-ref', 'HEAD', 'refs/heads/main')
    git(source, 'read-tree', commits[1])


def acquire_docs(source, folder):
    """Download locked gems as data; no gem code runs during acquisition."""
    cache = folder / 'gem-cache'
    cache.mkdir(exist_ok=True)
    lock = (source / 'docs/Gemfile.lock').read_text()
    selected = {}
    for name, version, digest in re.findall(r'^  ([\w.-]+) \(([\w.-]+)\) sha256=([a-f0-9]{64})$', lock, re.M):
        native = version.endswith('-x86_64-linux-gnu')
        if native or (re.fullmatch(r'[0-9]+(?:\.[0-9A-Za-z]+)*', version) and name not in selected):
            selected[name] = (version, digest)
    bundler = lock.split('BUNDLED WITH\n', 1)[1].strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+', bundler):
        raise Error('unsupported Bundler pin')
    meta = cache / 'bundler.json'
    download('https://rubygems.org/api/v2/rubygems/bundler/versions/' + bundler + '.json', meta)
    selected['bundler'] = (bundler, json.loads(meta.read_text())['sha'])
    for name, (version, digest) in selected.items():
        path = cache / f'{name}-{version}.gem'
        if not path.exists() or sha(path) != digest:
            download('https://rubygems.org/downloads/' + path.name, path)
        if sha(path) != digest:
            raise Error('gem checksum mismatch: ' + name)
    return bundler


def check_docs(source, folder, bundler):
    docs = folder / 'docs-source'
    shutil.copytree(source / 'docs', docs)
    for name in ('gems', 'docs-output'):
        (folder / name).mkdir()
    mounts = [('--ro-bind', folder / 'gem-cache', '/gem-cache'),
              ('--bind', folder / 'gems', '/gems'), ('--bind', docs, '/docs'),
              ('--bind', folder / 'docs-output', '/docs-output')]
    cache = folder / 'gem-cache'
    gems = sorted(cache.glob('*.gem'), key=lambda path: (not path.name.startswith('rake-'), path.name))
    environment = ['env', 'GEM_HOME=/gems', 'GEM_PATH=/gems', 'BUNDLE_FROZEN=true',
                   'BUNDLE_APP_CONFIG=/home/build/bundle', 'BUNDLE_GEMFILE=/docs/Gemfile',
                   'PATH=/gems/bin:/usr/bin:/bin']
    run(sandbox(folder, [*environment, 'gem', 'install', '--local', '--ignore-dependencies', '--no-document',
                         '--install-dir', '/gems', *['/gem-cache/' + path.name for path in gems]],
                mounts=mounts), capture=False)
    run(sandbox(folder, [*environment, 'bundle', '_' + bundler + '_', 'exec', 'jekyll', 'build',
                         '--source', '/docs', '--destination', '/docs-output', '--disable-disk-cache'],
                mounts=mounts), capture=False)


def inspect_deb(path):
    """Read archives without extraction or executing package scripts."""
    fields = run(['dpkg-deb', '-f', path, 'Package', 'Version', 'Architecture']).decode()
    metadata = dict(line.split(': ', 1) for line in fields.splitlines())
    if metadata['Package'] != 'spotifast' or metadata['Architecture'] != 'amd64':
        raise Error('package must be spotifast/amd64')
    control = run(['dpkg-deb', '--ctrl-tarfile', path])
    with tarfile.open(fileobj=io.BytesIO(control)) as archive:
        for member in archive:
            if member.isdir():
                continue
            if not member.isfile() or member.name.removeprefix('./') not in {'control', 'md5sums'}:
                raise Error('package control scripts or unsupported entries refused')
    hashes = {}
    with tarfile.open(fileobj=io.BytesIO(run(['dpkg-deb', '--fsys-tarfile', path]))) as archive:
        for member in archive:
            name = member.name.removeprefix('./')
            if member.isdir():
                if name != '.' and not any(path.startswith(name.rstrip('/') + '/') for path in PAYLOAD):
                    raise Error('unsafe package directory')
                continue
            if (name not in PAYLOAD or name in hashes or not member.isfile()
                    or member.mode != PAYLOAD[name][1] or member.uid or member.gid):
                raise Error(f'unexpected package member: {member.name}')
            hashes[name] = hashlib.sha256(archive.extractfile(member).read()).hexdigest()
    if set(hashes) != set(PAYLOAD):
        raise Error('incomplete package payload')
    return {'version': metadata['Version'], 'package_sha256': sha(path), 'files': hashes}


def installed():
    result = run(['dpkg-query', '-W', '-f=${Version}\t${Architecture}\t${Status}', 'spotifast']).decode()
    version, arch, status = result.split('\t')
    if arch != 'amd64' or status != 'install ok installed':
        raise Error('requires installed spotifast/amd64')
    owner = run(['dpkg-query', '-S', '/usr/bin/spotifast']).decode().strip()
    if owner != 'spotifast: /usr/bin/spotifast':
        raise Error('unexpected executable ownership')
    return {'version': version, 'executable_sha256': sha('/usr/bin/spotifast')}


def transaction(package):
    output = run(['apt-get', '-s', '--no-remove', '--no-download', '--allow-downgrades',
                  '--reinstall', 'install', package]).decode()
    changed = [line for line in output.splitlines() if line.startswith(('Inst ', 'Remv ', 'Conf '))]
    if not any(line.startswith('Inst spotifast ') for line in changed) or any(
            not line.startswith(('Inst spotifast ', 'Conf spotifast ')) for line in changed):
        raise Error('dependency transaction must replace only spotifast:\n' + output)
    return output


def sandbox(work, command, *, network=False, mounts=(), toolchain=None):
    """No host home, root checkout, session sockets, credentials or app data."""
    work = Path(work)
    for name in ('tmp', 'home'):
        (work / name).mkdir(exist_ok=True)
    (work / 'home/runtime').mkdir(exist_ok=True, mode=0o700)
    identity = work / 'identity'
    identity.mkdir(exist_ok=True)
    (identity / 'passwd').write_text(f'build:x:{os.getuid()}:{os.getgid()}:Build:/home/build:/bin/sh\n')
    (identity / 'group').write_text(f'build:x:{os.getgid()}:\n')
    (identity / 'nsswitch.conf').write_text('passwd: files\ngroup: files\nhosts: files dns\n')
    (identity / 'hosts').write_text('127.0.0.1 localhost\n::1 localhost\n')
    (identity / 'machine-id').write_text('0123456789abcdef0123456789abcdef\n')
    args = ['/usr/bin/bwrap', '--die-with-parent', '--new-session', '--unshare-all']
    if network:
        args += ['--share-net']
    args += ['--ro-bind', '/usr', '/usr', '--symlink', 'usr/bin', '/bin',
             '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib64', '/lib64',
             '--proc', '/proc', '--dev', '/dev', '--dir', '/etc',
             '--bind', str(work / 'tmp'), '/tmp', '--bind', str(work / 'home'), '/home/build',
             '--clearenv', '--setenv', 'PATH', '/toolchain/bin:/usr/bin:/bin',
             '--setenv', 'HOME', '/home/build', '--setenv', 'LC_ALL', 'C.UTF-8',
             '--setenv', 'CARGO_HOME', '/cargo', '--setenv', 'CARGO_TARGET_DIR', '/target',
             '--setenv', 'CARGO_BUILD_JOBS', '2', '--setenv', 'CARGO_INCREMENTAL', '0',
             '--setenv', 'XDG_RUNTIME_DIR', '/home/build/runtime',
             '--setenv', 'XDG_CONFIG_HOME', '/home/build/config',
             '--setenv', 'XDG_STATE_HOME', '/home/build/state',
             '--setenv', 'XDG_CACHE_HOME', '/home/build/cache',
             '--setenv', 'GIT_CONFIG_NOSYSTEM', '1', '--setenv', 'GIT_CONFIG_GLOBAL', '/dev/null',
             '--setenv', 'GIT_TERMINAL_PROMPT', '0']
    for path in ('/etc/ld.so.cache', '/etc/alternatives', '/etc/fonts', '/etc/ssl/certs',
                 '/etc/os-release', '/etc/debian_version'):
        if Path(path).exists():
            args += ['--ro-bind', path, path]
    for path in identity.iterdir():
        args += ['--ro-bind', str(path), '/etc/' + path.name]
    if network:
        args += ['--ro-bind', '/etc/resolv.conf', '/etc/resolv.conf']
    if toolchain:
        args += ['--ro-bind', str(toolchain), '/toolchain']
    for flag, source, dest in mounts:
        args += [flag, str(source), dest]
    return args + ['--chdir', '/home/build', '--', *command]


def smoke(work, executable, version):
    """Start the production login window on a private X server and private bus."""
    executable = Path(executable).absolute()
    if executable.resolve() != executable or not executable.is_file():
        raise Error('smoke executable must be a regular file without symlink parents')
    script = '''import os, subprocess, time
os.makedirs('/home/build/runtime', mode=0o700, exist_ok=True)
assert subprocess.check_output(['/app', '--version'], text=True).strip() == 'spotifast VERSION'
assert '--demo' not in subprocess.check_output(['/app', '--help'], text=True)
x = subprocess.Popen(['Xvfb', ':91', '-screen', '0', '1280x800x24', '-nolisten', 'tcp'])
app = None
try:
    time.sleep(1)
    assert x.poll() is None, 'private X server failed'
    app = subprocess.Popen(['/app'], env={**os.environ, 'DISPLAY': ':91', 'LIBGL_ALWAYS_SOFTWARE': '1'})
    time.sleep(8)
    assert app.poll() is None, 'production startup failed'
finally:
    if app is not None and app.poll() is None:
        app.terminate()
        app.wait(timeout=10)
    x.terminate()
    x.wait(timeout=10)
'''.replace('VERSION', version)
    run(sandbox(work, ['dbus-run-session', '--', 'python3', '-I', '-c', script],
                mounts=[('--ro-bind', executable, '/app')]), capture=False)


class Pipeline:
    def __init__(self, repo):
        self.repo = repo
        self.store = repo.meta / 'local'
        if self.store.is_symlink():
            raise Error('symlinked deployment storage')
        self.store.mkdir(exist_ok=True, mode=0o700)
        self.toolchain = self.store / 'rustup/toolchains' / f'{RUST}-{TRIPLE}'
        self.journal = self.store / 'transaction.json'

    def reusable_cache(self):
        for record in sorted((self.store / 'builds').glob('*/manifest.json'), reverse=True):
            old = json.loads(record.read_text())
            folder = record.parent
            if (old.get('state') == 'failed' and old.get('toolchain') == RUST
                    and (folder / 'cargo').is_dir() and (folder / 'target').is_dir()
                    and (folder / 'source/Cargo.lock').read_bytes() == (self.repo.root / 'Cargo.lock').read_bytes()):
                return folder
        return None

    def prepare(self):
        """Acquisition only. The trusted rustup host tool runs in a separate sandbox."""
        if not (self.toolchain / 'bin/rustc').exists():
            rustup = Path.home() / '.cargo/bin/rustup'
            if not rustup.is_file():
                raise Error('install trusted rustup first')
            work = self.store / 'acquire'
            work.mkdir(exist_ok=True)
            runtime = self.store / 'rustup'
            runtime.mkdir(exist_ok=True)
            command = ['/usr/bin/env', 'RUSTUP_HOME=/rustup-home', '/rustup', 'toolchain', 'install',
                       RUST, '--profile', 'minimal', '--component', 'rustfmt,clippy', '--no-self-update']
            run(sandbox(work, command, network=True, mounts=[
                ('--ro-bind', rustup, '/rustup'), ('--bind', runtime, '/rustup-home')]), capture=False)
            shutil.rmtree(work)
        return self.rollback_package()

    def rollback_package(self):
        current = installed()
        folder = self.store / 'packages'
        folder.mkdir(exist_ok=True)
        for path in folder.glob('*.deb'):
            info = inspect_deb(path)
            if (info['version'] == current['version']
                    and info['files']['usr/bin/spotifast'] == current['executable_sha256']):
                return path, info
        version = current['version']
        if not re.fullmatch(r'\d+\.\d+\.\d+', version):
            raise Error('matching rollback package missing; restore the retained .deb before deploying')
        name = f'spotifast_{version}_amd64.deb'
        url = f'https://github.com/crmne/spotifast/releases/download/v{version}/'
        with tempfile.TemporaryDirectory(dir=self.store, prefix='rollback-') as tmp:
            tmp = Path(tmp)
            download(url + 'packaging-checksums.txt', tmp / 'checksums')
            entries = [line.split() for line in (tmp / 'checksums').read_text().splitlines()]
            expected = next((parts[0] for parts in entries if len(parts) == 2 and parts[1].lstrip('*') == name), None)
            if not expected:
                raise Error('rollback package absent from release checksums')
            download(url + name, tmp / name)
            if sha(tmp / name) != expected:
                raise Error('rollback checksum mismatch')
            info = inspect_deb(tmp / name)
            if info['version'] != version or info['files']['usr/bin/spotifast'] != current['executable_sha256']:
                raise Error('rollback does not match installed executable')
            for relative, digest in info['files'].items():
                if sha('/' + relative) != digest:
                    raise Error(f'installed package file differs: {relative}')
            shutil.copyfile(tmp / name, folder / name)
            return folder / name, info

    def doctor(self):
        problems = []
        try:
            commit = clean(self.repo)
        except Error as error:
            commit = None
            problems.append(str(error))
        for program in ('bwrap', 'cc', 'c++', 'cmake', 'pkg-config', 'dpkg-deb', 'dpkg-shlibdeps',
                        'dbus-run-session', 'gdbus', 'Xvfb', 'xdotool', 'ruby'):
            if not shutil.which(program, path=ENV['PATH']):
                problems.append('missing program: ' + program)
        for package in ('alsa', 'libpipewire-0.3', 'xkbcommon', 'wayland-client', 'gl', 'openssl', 'dbus-1'):
            try:
                run(['pkg-config', '--exists', package])
            except Error:
                problems.append('missing pkg-config dependency: ' + package)
        if not list(Path('/usr/lib').glob('llvm-*/lib/libclang.so*')):
            problems.append('missing libclang development library')
        if not list(Path('/usr/include').glob('ruby-*/ruby.h')):
            problems.append('missing ruby-dev headers for the documentation check')
        if not (self.toolchain / 'bin/rustc').exists():
            problems.append('pinned toolchain absent; run doctor --prepare')
        free = shutil.disk_usage(self.store).free
        cached = 0
        cache = self.reusable_cache()
        if cache:
            seen = set()
            for directory in ('target', 'cargo'):
                for path in (cache / directory).rglob('*'):
                    info = path.lstat()
                    identity = (info.st_dev, info.st_ino)
                    if identity not in seen:
                        cached += info.st_blocks * 512
                        seen.add(identity)
        required = max(8 * 1024**3, 20 * 1024**3 - cached)
        if free < required:
            problems.append(f'need {required / 1024**3:.1f} GiB free after accounting for reusable build cache')
        try:
            with tempfile.TemporaryDirectory(dir=self.store) as tmp:
                run(sandbox(tmp, ['/usr/bin/true']))
        except Error as error:
            problems.append('sandbox unavailable: ' + str(error))
        candidates = list((self.store / 'packages').glob('*.deb'))
        try:
            current = installed()
            if not any((info := inspect_deb(p))['version'] == current['version']
                       and info['files']['usr/bin/spotifast'] == current['executable_sha256'] for p in candidates):
                problems.append('matching rollback package absent; run doctor --prepare')
        except Error as error:
            problems.append(str(error))
        return {'commit': commit, 'upstream': self.repo.pin(), 'free_bytes': free,
                'reusable_cache_bytes': cached, 'required_free_bytes': required,
                'toolchain': RUST, 'features': ['default', 'milkdrop'], 'problems': problems}

    def build(self):
        commit = clean(self.repo)
        self.prepare()
        report = self.doctor()
        if report['problems']:
            raise Error(json.dumps(report, indent=2))
        build_id = commit[:12] + '-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
        folder = self.store / 'builds' / build_id
        folder.mkdir(parents=True)
        source = folder / 'source'
        source.mkdir()
        source_tree = self.repo.verify()
        self.repo.materialize({}, source_tree, source)
        previous = self.reusable_cache()
        if previous:
            # Preserve mtimes only for byte-identical snapshot files. Cargo sees
            # every snapshot at /source, so reviewed infrastructure-only edits
            # need not recompile the entire unchanged application.
            for name, (mode, data) in source_tree.items():
                old = previous / 'source' / name
                if mode != '120000' and old.is_file() and not old.is_symlink() and old.read_bytes() == data:
                    stamp = old.stat()
                    os.utime(source / name, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        snapshot_index(self.repo, source)
        cargo = folder / 'cargo'
        target = folder / 'target'
        # One lock serializes builds. Move failed-build caches into a fresh
        # snapshot, never share a writable target between simultaneous builds.
        if previous:
            shutil.move(previous / 'cargo', cargo)
            shutil.move(previous / 'target', target)
        cargo.mkdir(exist_ok=True); target.mkdir(exist_ok=True)
        mounts = [('--ro-bind', source, '/source'), ('--bind', cargo, '/cargo'), ('--bind', target, '/target')]
        manifest = {'build_id': build_id, 'commit': commit, 'upstream': self.repo.pin(),
                    'patches': {n: sha(self.repo.meta / 'patches' / n) for n in self.repo.series()},
                    'toolchain': RUST, 'features': ['default', 'milkdrop'], 'state': 'building'}
        save(folder / 'manifest.json', manifest)
        def execute(command, network=False):
            args = sandbox(folder, ['/usr/bin/env', 'CARGO_NET_OFFLINE=' + ('false' if network else 'true'),
                                   '/usr/bin/env', '--chdir=/source', *command],
                           network=network, mounts=mounts, toolchain=self.toolchain)
            run(args, capture=False)
        try:
            execute(['cargo', 'fetch', '--locked', '--target', TRIPLE], network=True)
            bundler = acquire_docs(source, folder)
            # Dependency acquisition is finished. No following command has network access.
            execute(['cargo', 'fmt', '--all', '--check'])
            for script in ('.github/scripts/check-dependency-sources.py',
                           '.github/scripts/check-review-evidence.py', 'packaging/test-launchers.py'):
                execute(['python3', '-I', script])
            execute(['python3', '-I', '.github/scripts/check-new-settings.py', '--base', 'baseline'])
            for features in ([], ['--all-features']):
                execute(['cargo', 'clippy', '--offline', '--locked', '--all-targets', *features, '--', '-D', 'warnings'])
                execute(['cargo', 'test', '--offline', '--locked', '--all-targets', *features])
            execute(['cargo', 'test', '--offline', '--locked', '--all-features', '--doc'])
            execute(['env', 'RUSTDOCFLAGS=-D warnings', 'cargo', 'doc', '--offline', '--locked', '--all-features', '--no-deps'])
            check_docs(source, folder, bundler)
            # Test executables are large and their checks are complete. Keep
            # libraries/proc macros cached for the upcoming demo build, but
            # reclaim these one-off binaries before adding another profile.
            for directory in ('deps', 'examples'):
                for path in (target / 'debug' / directory).iterdir():
                    if path.is_file() and not path.is_symlink() and not path.suffix and os.access(path, os.X_OK):
                        path.unlink()
            manifest['visual_evidence'] = self.capture_demo(folder, source, cargo, target)
            # These completed QA outputs are not production artifacts. Record
            # their result, then reclaim their private debug profile before the
            # separate release build. This never cleans another checkout/cache.
            manifest['checks'] = 'format, policies, default/all-feature clippy and tests, docs, demo captures passed'
            save(folder / 'manifest.json', manifest)
            shutil.rmtree(target / 'debug')
            # The production package is built without --all-features or demo.
            execute(['cargo', 'build', '--release', '--offline', '--locked', '--bin', 'spotifast'])
            version = tomllib.loads((source / 'Cargo.toml').read_text())['package']['version']
            execute(['/target/release/spotifast', '--version'])
            smoke(folder, target / 'release/spotifast', version)
            package_version = f'{version}+mod.{git(self.repo.root, "rev-list", "--count", commit).decode().strip()}.{commit[:12]}'
            package = self.package(folder, package_version)
            info = inspect_deb(package)
            transaction(package)
            manifest.update(info, state='verified', package=str(package), executable_sha256=info['files']['usr/bin/spotifast'])
            if clean(self.repo) != commit:
                raise Error('checkout changed while building')
            save(folder / 'manifest.json', manifest)
            # Only source/manifest/package survive; large one-off compile directories do not.
            for name in ('target', 'cargo', 'tmp', 'home', 'identity', 'baseline', 'gem-cache', 'gems', 'docs-source', 'docs-output'):
                shutil.rmtree(folder / name)
            return build_id
        except BaseException:
            manifest['state'] = 'failed'
            save(folder / 'manifest.json', manifest)
            raise

    def capture_demo(self, folder, source, cargo, target):
        evidence = folder / 'evidence'
        evidence.mkdir()
        baseline = folder / 'baseline'
        baseline.mkdir()
        self.repo.materialize({}, self.repo.read_tree(self.repo.pin()), baseline)
        # Each source snapshot owns its writable target. Reusing one target
        # across /source mounts can reuse the wrong application when the
        # candidate's source mtimes predate the baseline build. Copy the
        # completed dependency cache, never hard-link writable outputs.
        baseline_target = folder / 'baseline-target'
        copy_bytes = sum(path.stat().st_blocks * 512 for path in target.rglob('*')
                         if not path.is_symlink() and path.is_file())
        if shutil.disk_usage(folder).free < copy_bytes + 4 * 1024**3:
            raise Error('insufficient space for isolated baseline cache plus 4 GiB build headroom')
        # Build outputs are untrusted. Preserve links as links so copying never
        # follows a generated absolute symlink into the host filesystem.
        shutil.copytree(target, baseline_target, symlinks=True)
        for phase, inputs in [('before', baseline), ('after', source)]:
            ui_target = baseline_target if phase == 'before' else target
            ui_mounts = [('--ro-bind', inputs, '/source'), ('--bind', cargo, '/cargo'),
                         ('--bind', ui_target, '/target'), ('--bind', evidence, '/evidence'),
                         ('--ro-bind', HERE / 'visual_check.py', '/visual_check.py')]
            run(sandbox(folder, ['env', '--chdir=/source', 'cargo', 'build', '--offline',
                                 '--locked', '--features', 'demo', '--bin', 'spotifast'],
                        mounts=ui_mounts, toolchain=self.toolchain), capture=False)
            run(sandbox(folder, ['dbus-run-session', '--', 'python3', '-I', '/visual_check.py', phase],
                        mounts=ui_mounts, toolchain=self.toolchain), capture=False)
            if phase == 'before':
                shutil.rmtree(baseline_target)
        hashes = {}
        for path in evidence.glob('*.png'):
            if path.is_symlink() or not path.is_file() or path.resolve().parent != evidence.resolve():
                raise Error('unsafe generated visual evidence')
            hashes[path.name] = sha(path)
        if len(hashes) != 8:
            raise Error('incomplete visual evidence')
        return hashes

    def package(self, folder, version):
        root = folder / 'package-root'
        root.mkdir()
        for dest, (source, mode) in PAYLOAD.items():
            path = root / dest
            path.parent.mkdir(parents=True, exist_ok=True)
            origin = folder / source if source.startswith('target/') else folder / 'source' / source
            if origin.is_symlink() or not origin.resolve().is_relative_to(folder.resolve()) or not origin.is_file():
                raise Error('unsafe package input: ' + str(origin))
            shutil.copyfile(origin, path)
            path.chmod(mode)
        control = root / 'DEBIAN'
        control.mkdir()
        # dpkg-shlibdeps inspects ELF rather than executing it, retaining ABI version requirements.
        debian = folder / 'debian'
        debian.mkdir()
        (debian / 'control').write_text('Source: spotifast\nSection: sound\nPriority: optional\nMaintainer: Local fork <local@localhost>\n\nPackage: spotifast\nArchitecture: amd64\nDescription: Local Spotifast fork\n')
        inferred = run(['dpkg-shlibdeps', '-O', '-e' + str(root / 'usr/bin/spotifast')], cwd=folder).decode().strip()
        if not inferred.startswith('shlibs:Depends='):
            raise Error('missing ELF dependency information')
        dependencies = inferred.removeprefix('shlibs:Depends=') + ', ' + DEPS
        (control / 'control').write_text(f'Package: spotifast\nVersion: {version}\nArchitecture: amd64\nMaintainer: Local fork <local@localhost>\nDepends: {dependencies}\nDescription: Spotifast local fork with Liked Songs type-to-filter\n')
        destination = self.store / 'packages' / f'spotifast_{version}_amd64.deb'
        run(['dpkg-deb', '--root-owner-group', '--build', root, destination])
        shutil.rmtree(root); shutil.rmtree(debian)
        return destination

    def artifact(self, build_id):
        if not re.fullmatch(r'[0-9a-f]{12}-[0-9]{8}T[0-9]{6}Z', build_id):
            raise Error('invalid build id')
        manifest = json.loads((self.store / 'builds' / build_id / 'manifest.json').read_text())
        if manifest['state'] != 'verified' or not installer_only_since(self.repo, manifest['commit'], clean(self.repo)):
            raise Error('artifact is unverified or belongs to another source commit')
        if manifest.get('toolchain') != RUST or manifest.get('features') != ['default', 'milkdrop']:
            raise Error('artifact toolchain or production features mismatch')
        if manifest['upstream'] != self.repo.pin() or manifest['patches'] != {
                n: sha(self.repo.meta / 'patches' / n) for n in self.repo.series()}:
            raise Error('artifact source metadata mismatch')
        package = Path(manifest['package'])
        if package.parent != self.store / 'packages' or package.is_symlink():
            raise Error('invalid artifact location')
        actual = inspect_deb(package)
        if any(manifest.get(k) != v for k, v in actual.items()):
            raise Error('artifact checksum or payload mismatch')
        return package, actual, manifest

    def install(self, build_id):
        if self.journal.exists() and json.loads(self.journal.read_text())['state'] in ('installing', 'recovering'):
            raise Error('interrupted transaction; inspect status and use rollback first')
        package, info, manifest = self.artifact(build_id)
        previous, old_info = self.rollback_package()
        return self.replace(package, info, previous, old_info, manifest['commit'])

    def replace(self, package, info, previous, old_info, commit):
        transaction(package)
        transaction(previous)
        # Check privilege before asking the running app to quit.
        run(['sudo', '-n', 'true'])
        was_running = running()
        if was_running:
            quit_app()
        record = {'state': 'installing', 'package': str(package), 'info': info,
                  'previous': str(previous), 'previous_info': old_info,
                  'commit': commit, 'was_running': was_running}
        save(self.journal, record)
        try:
            package_install(package)
            verify_installed(info)
            with tempfile.TemporaryDirectory(dir=self.store, prefix='installed-smoke-') as work:
                smoke(work, Path('/usr/bin/spotifast'), info['version'].split('+mod.')[0])
            if was_running:
                launch_app()
            record['state'] = 'installed'
            save(self.journal, record)
        except BaseException as failure:
            record['state'] = 'recovering'
            save(self.journal, record)
            try:
                self.recover_previous(record)
            except BaseException as recovery:
                raise Error(f'installation failed: {failure}; recovery needs attention: {recovery}; journal: {self.journal}') from recovery
            raise Error(f'installation failed and previous package restored: {failure}') from failure
        return record

    def recover_previous(self, record):
        previous = Path(record['previous'])
        if inspect_deb(previous) != record['previous_info']:
            raise Error('rollback artifact changed')
        try:
            verify_installed(record['previous_info'])
        except Error:
            if running():
                quit_app()
            transaction(previous)
            package_install(previous)
            verify_installed(record['previous_info'])
        # A package manager can fail before changing any files. In that case
        # restore the original running state without another package operation.
        if record['was_running'] and not running():
            launch_app()
        record['state'] = 'recovered'
        save(self.journal, record)
        return record

    def rollback(self):
        record = json.loads(self.journal.read_text())
        if record['state'] in ('installing', 'recovering'):
            return self.recover_previous(record)
        previous = Path(record['previous'])
        old = inspect_deb(previous)
        if old != record['previous_info']:
            raise Error('rollback artifact changed')
        current = Path(record['package'])
        current_info = inspect_deb(current)
        if current_info != record['info']:
            raise Error('recorded current artifact changed')
        return self.replace(previous, old, current, current_info, None)


def desktop_env():
    # Only normal desktop actions use this. Preserve locale, proxy, audio and
    # XDG overrides as well as the session; never pass the build environment.
    # Values are neither inspected nor logged. Every build sandbox clears env.
    return os.environ.copy()


def running():
    p = subprocess.run(['pgrep', '-u', str(os.getuid()), '-x', 'spotifast'], env=ENV,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if p.returncode not in (0, 1):
        raise Error('cannot determine running application')
    return p.returncode == 0


def quit_app():
    run(['/usr/bin/gdbus', 'call', '--session', '--dest', 'org.mpris.MediaPlayer2.spotifast',
         '--object-path', '/org/mpris/MediaPlayer2', '--method', 'org.mpris.MediaPlayer2.Quit'], env=desktop_env())
    deadline = time.monotonic() + 15
    while running():
        if time.monotonic() > deadline:
            raise Error('graceful shutdown failed; package not replaced, app was not killed')
        time.sleep(0.25)


def launch_app():
    subprocess.Popen(['/usr/bin/spotifast'], env=desktop_env(), start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(5)
    if not running():
        raise Error('application exited during startup')


def package_install(package):
    # APT simulation validates dependencies first. Use dpkg for the exact local
    # file: APT 3.0 --no-download can leave local archive paths unresolved.
    # dpkg cannot acquire packages or choose a replacement from a repository.
    run(['sudo', '-n', 'dpkg', '--install', Path(package).resolve(strict=True)], capture=False)


def verify_installed(info):
    actual = installed()
    if actual['version'] != info['version'] or actual['executable_sha256'] != info['files']['usr/bin/spotifast']:
        raise Error('installed version/hash mismatch')
    for relative, digest in info['files'].items():
        if sha('/' + relative) != digest:
            raise Error('installed payload mismatch: ' + relative)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['doctor', 'build', 'install', 'deploy', 'status', 'rollback'])
    parser.add_argument('build_id', nargs='?')
    parser.add_argument('--prepare', action='store_true', help='doctor: acquire pinned toolchain and matching rollback package')
    args = parser.parse_args()
    with open(HERE / 'lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        repo = m.Repo(HERE.parent)
        try:
            pipeline = Pipeline(repo)
            if args.command == 'doctor':
                if args.prepare:
                    pipeline.prepare()
                report = pipeline.doctor()
                print(json.dumps(report, indent=2))
                return bool(report['problems'])
            if args.prepare:
                raise Error('--prepare is only for doctor')
            if args.command == 'status':
                result = {'installed': installed(), 'upstream': repo.pin(),
                          'transaction': json.loads(pipeline.journal.read_text()) if pipeline.journal.exists() else None}
            elif args.command == 'build':
                result = pipeline.build()
            elif args.command == 'deploy':
                result = pipeline.install(pipeline.build())
            elif args.command == 'install':
                if not args.build_id:
                    raise Error('build id required')
                result = pipeline.install(args.build_id)
            else:
                result = pipeline.rollback()
            print(json.dumps(result, indent=2))
        finally:
            repo.close()
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (Error, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f'error: {error}', file=sys.stderr)
        sys.exit(1)
