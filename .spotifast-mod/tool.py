#!/usr/bin/python3
"""Reviewed stdlib-only source patch maintenance. Run with python3 -I."""
import argparse
import fcntl
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile

UPSTREAM = 'https://github.com/crmne/spotifast.git'
RESERVED = {'.git', '.spotifast-mod', '.gitmodules', 'lib'}

class Error(Exception):
    pass

def safe_path(name):
    parts = name.split('/')
    if (not name or name.startswith('/') or any(p in ('', '.', '..') for p in parts)
            or any(p.lower() in RESERVED for p in parts)
            or any(ord(c) < 32 or ord(c) == 127 for c in name) or '\\' in name):
        raise Error(f'unsafe/reserved path: {name!r}')

def validate(tree):
    for name, (mode, data) in tree.items():
        safe_path(name)
        if mode not in ('100644', '100755', '120000'):
            raise Error(f'unsupported mode {mode}: {name!r}')
        for parent in PurePosixPath(name).parents:
            if str(parent) in tree:
                raise Error(f'file/symlink parent: {name!r}')
        if mode == '120000':
            target = data.decode('utf-8', 'strict')
            if not target or target.startswith('/') or '\\' in target or any(ord(c)<32 for c in target):
                raise Error(f'unsafe symlink: {name!r}')
            # Resolve every link in the chain, rejecting cycles and reserved destinations.
            todo = list(PurePosixPath(name).parent.parts) + target.split('/')
            done = []; seen = 0
            while todo:
                part = todo.pop(0)
                if part in ('', '.'):
                    continue
                if part == '..':
                    if not done:
                        raise Error(f'escaping symlink: {name!r}')
                    done.pop(); continue
                done.append(part)
                dest = '/'.join(done)
                safe_path(dest)
                if dest in tree and tree[dest][0] == '120000':
                    seen += 1
                    if seen > 40:
                        raise Error(f'symlink cycle: {name!r}')
                    nested = tree[dest][1].decode('utf-8')
                    if nested.startswith('/'):
                        raise Error(f'escaping symlink: {name!r}')
                    done.pop(); todo = nested.split('/') + todo

class Repo:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.meta = self.root / '.spotifast-mod'
        self.gitdir = self.root / '.git'
        if not self.gitdir.is_dir() or self.gitdir.is_symlink():
            raise Error('requires a regular checkout with a real .git directory')
        self.env = {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'LC_ALL': 'C',
                    'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
                    'GIT_TERMINAL_PROMPT': '0', 'GIT_ATTR_NOSYSTEM': '1'}
        scratch = self.meta / 'scratch'
        if self.meta.is_symlink() or scratch.is_symlink():
            raise Error('symlinked maintenance directory')
        scratch.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix='run-', dir=scratch)
        self.private = Path(self.tmp.name) / 'repo.git'
        self.run('init', '--bare', str(self.private), initial=True)
        self.env['GIT_OBJECT_DIRECTORY'] = str(self.gitdir / 'objects')
        self.index = Path(self.tmp.name) / 'index'
        self.env['GIT_INDEX_FILE'] = str(self.index)
        if (self.root/'lib/spotifast/.git').exists():
            self.env['GIT_ALTERNATE_OBJECT_DIRECTORIES'] = str(self.sub_gitdir()/'objects')
    def close(self):
        self.tmp.cleanup()
    def run(self, *args, data=None, initial=False, index=None):
        opts = ['-c','core.hooksPath=/dev/null','-c','core.fsmonitor=false',
                '-c','core.attributesFile=/dev/null','-c','init.templateDir=',
                '-c','protocol.allow=never','-c','protocol.https.allow=always',
                '-c','credential.helper=','-c','fetch.recurseSubmodules=false',
                '-c','submodule.recurse=false','-c','maintenance.auto=false',
                '-c','gc.auto=0','-c','core.quotePath=true']
        env = dict(self.env)
        if initial:
            env.pop('GIT_OBJECT_DIRECTORY', None)
            env.pop('GIT_INDEX_FILE', None)
            env.pop('GIT_ALTERNATE_OBJECT_DIRECTORIES', None)
        if index is not None:
            env['GIT_INDEX_FILE'] = str(index)
        cmd = ['/usr/bin/git', *opts]
        if not initial:
            cmd += ['--git-dir='+str(self.private)]
        p = subprocess.run(cmd+list(args), input=data, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, env=env, cwd=self.root)
        if p.returncode:
            raise Error(p.stderr.decode('utf-8', 'replace').strip())
        return p.stdout
    def read_tree(self, ref):
        entries = self.run('ls-tree', '-rz', ref).split(b'\0')
        tree = {}
        ids = []; names = []
        for item in entries:
            if not item: continue
            header, raw = item.split(b'\t', 1)
            mode, kind, oid = header.decode().split()
            name = raw.decode('utf-8')
            safe_path(name)
            if kind != 'blob': raise Error(f'unsupported upstream entry: {name}')
            ids.append(oid); names.append((name, mode))
        if ids:
            packed = self.run('cat-file', '--batch', data=('\n'.join(ids)+'\n').encode())
            pos = 0
            for name, mode in names:
                end = packed.index(b'\n', pos)
                size = int(packed[pos:end].split()[-1]); pos = end+1
                tree[name] = (mode, packed[pos:pos+size]); pos += size+1
        validate(tree)
        return tree
    def tree_id(self, tree):
        validate(tree)
        self.run('read-tree', '--empty')
        entries = b''
        for name, (mode, data) in sorted(tree.items()):
            oid = self.run('hash-object','-w','--stdin','--no-filters',data=data).strip()
            entries += mode.encode()+b' '+oid+b'\t'+name.encode()+b'\0'
        self.run('update-index','-z','--index-info',data=entries)
        return self.run('write-tree').decode().strip()
    def pin(self):
        pin = json.loads((self.meta/'upstream.json').read_text())['revision']
        if not re.fullmatch('[0-9a-f]{40}',pin): raise Error('invalid upstream pin')
        return pin
    def series(self):
        names=(self.meta/'series').read_text().splitlines()
        if len(set(names)) != len(names) or any(not re.fullmatch(r'[0-9]{4}-[a-z0-9][a-z0-9-]*\.patch',n) for n in names):
            raise Error('invalid/duplicate patch series')
        for name in names:
            if (self.meta/'patches'/name).is_symlink(): raise Error('symlinked patch')
        return names
    def replay(self, pin=None, names=None):
        tree=self.read_tree(pin or self.pin())
        self.run('read-tree', self.tree_id(tree))
        for name in (self.series() if names is None else names):
            try:
                self.run('apply','--cached','--whitespace=nowarn',str(self.meta/'patches'/name))
                tree=self.read_tree(self.run('write-tree').decode().strip())
            except Error as e:
                raise Error(f'patch {name} failed: {e}') from e
        return tree
    def staged_entries(self):
        entries={}
        for item in self.run('ls-files','--stage','-z',index=self.gitdir/'index').split(b'\0'):
            if not item: continue
            header,name=item.split(b'\t',1)
            mode,oid,stage=header.decode().split()
            if stage != '0': raise Error('resolve index conflicts first')
            entries[name.decode()]=(mode,oid)
        return entries
    def staged(self):
        return set(self.staged_entries())
    def staged_source(self):
        tree={}
        for name,(mode,oid) in self.staged_entries().items():
            if name.split('/')[0] in RESERVED: continue
            tree[name]=(mode,self.run('cat-file','blob',oid))
        validate(tree)
        return tree
    def scan(self, base=None):
        is_root = base is None or Path(base) == self.root
        base = self.root if base is None else Path(base)
        tree={}
        def visit(folder, prefix=''):
            for p in sorted(folder.iterdir()):
                name=prefix+p.name
                if not prefix and p.name in (RESERVED if is_root else {'.git'}): continue
                safe_path(name)
                mode=p.lstat().st_mode
                if stat.S_ISLNK(mode): tree[name]=('120000',os.readlink(p).encode())
                elif stat.S_ISDIR(mode): visit(p,name+'/')
                elif stat.S_ISREG(mode): tree[name]=('100755' if mode & 0o111 else '100644',p.read_bytes())
                else: raise Error(f'unsupported filesystem entry: {name!r}')
        visit(base); validate(tree); return tree
    def diff(self,a,b):
        return self.run('diff-tree','-p','--binary','--full-index','--no-renames',
                        '--no-ext-diff','--no-textconv','--src-prefix=a/','--dst-prefix=b/',
                        self.tree_id(a),self.tree_id(b),'--')
    def capture(self,name=None):
        names=self.series()
        if name is None and not names: raise Error('no patch to refresh')
        before=self.replay(names=names if name else names[:-1])
        current=self.scan()
        unexpected=set(current)-set(before)-self.staged()
        if unexpected: raise Error('stage new source files first: '+repr(sorted(unexpected)))
        patch=self.diff(before,current)
        if not patch: raise Error('no source changes')
        if name:
            if not re.fullmatch('[a-z0-9][a-z0-9-]*',name): raise Error('use a lowercase hyphenated name')
            filename=f'{len(names)+1:04d}-{name}.patch'
            if (self.meta/'patches'/filename).exists(): raise Error('patch already exists')
        else: filename=names[-1]
        atomic(self.meta/'patches'/filename,patch)
        if name: atomic(self.meta/'series', ('\n'.join(names+[filename])+'\n').encode())
        return filename
    def sub_gitdir(self):
        sub = self.root/'lib/spotifast'
        marker = sub/'.git'
        if (self.root/'lib').is_symlink() or sub.is_symlink() or marker.is_symlink():
            raise Error('symlinked submodule metadata')
        if marker.is_dir():
            return marker
        if marker.is_file():
            value = marker.read_text().strip()
            if not value.startswith('gitdir: '): raise Error('invalid submodule gitfile')
            target = (sub/value[8:]).resolve()
            if not target.is_relative_to(self.gitdir/'modules') or not target.is_dir():
                raise Error('submodule gitdir must be inside root .git/modules')
            candidate = self.gitdir/'modules'
            for part in target.relative_to(candidate).parts:
                if candidate.is_symlink(): raise Error('symlinked submodule gitdir parent')
                candidate = candidate/part
            return target
        raise Error('initialize only the approved lib/spotifast submodule first')
    def verify_submodule(self):
        subgit = self.sub_gitdir()
        if (subgit/'HEAD').read_text().strip() != self.pin():
            raise Error('submodule HEAD differs from the recorded pin (requires detached HEAD)')
        if self.scan(self.root/'lib/spotifast') != self.read_tree(self.pin()):
            raise Error('submodule source drift')
    def verify(self):
        self.verify_submodule()
        expected=self.replay(); actual=self.scan()
        changed=drift(expected,actual)
        if changed: raise Error('source drift: '+repr(changed))
        return expected
    def materialize(self, before, after, base=None):
        base=self.root if base is None else Path(base)
        validate(after)
        if self.scan(base) != before: raise Error('refusing to overwrite local source changes')
        # Preflight every ancestor and collision before the first write.
        for name in after:
            p=base/name
            for parent in p.parents:
                if parent == base: break
                if parent.is_symlink(): raise Error(f'symlink parent: {parent}')
                if parent.exists() and not parent.is_dir():
                    raise Error(f'parent is not a directory: {parent}')
            if p.is_dir() and not p.is_symlink(): raise Error(f'directory collision: {name}')
        for name in sorted(set(before)-set(after),reverse=True):
            (base/name).unlink()
        for name,(mode,data) in sorted(after.items()):
            if before.get(name)==(mode,data): continue
            p=base/name; p.parent.mkdir(parents=True,exist_ok=True)
            if p.is_symlink(): p.unlink()
            if mode=='120000':
                if p.exists(): p.unlink()
                p.symlink_to(data.decode())
            else:
                atomic(p,data,0o755 if mode=='100755' else 0o644)
    def apply(self):
        self.verify_submodule()
        expected=self.replay(); actual=self.scan()
        if actual==expected: return 'already matches (no-op)'
        pristine=self.read_tree(self.pin())
        if actual!=pristine: raise Error('refusing to overwrite local source changes; capture or restore them first')
        if self.staged_source() != actual:
            raise Error('refusing to overwrite staged source changes; index source differs')
        self.materialize(actual,expected)
        return 'applied'
    def update(self,ref):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*',ref) or '..' in ref:
            raise Error('invalid explicit ref')
        old=self.verify()
        if self.staged_source() != old:
            raise Error('stage or commit the captured source before updating; index source differs')
        subgit=self.sub_gitdir()
        sub=self.root/'lib/spotifast'
        if sub.is_symlink() or (self.root/'lib').is_symlink(): raise Error('symlinked submodule')
        old_base=self.read_tree(self.pin())
        if self.scan(sub)!=old_base: raise Error('submodule source drift')
        self.run('fetch','--no-tags','--no-recurse-submodules',UPSTREAM,ref)
        pin=self.run('rev-parse','FETCH_HEAD^{commit}').decode().strip()
        new=self.replay(pin=pin) # all conflicts and reserved paths fail before mutation
        new_base=self.read_tree(pin)
        # materialize is preflighted on both destinations before changing either.
        for base,tree in ((self.root,new),(sub,new_base)):
            for name in tree:
                for parent in (base/name).parents:
                    if parent==base: break
                    if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
                        raise Error(f'unsafe destination parent: {parent}')
                p=base/name
                if p.is_dir() and not p.is_symlink(): raise Error(f'directory collision: {name}')
        for path in (subgit/'HEAD', subgit/'objects/info/alternates'):
            for parent in path.parents:
                if parent == self.root: break
                if parent.is_symlink(): raise Error(f'symlinked metadata parent: {parent}')
            if path.is_symlink(): raise Error(f'symlinked metadata: {path}')
        self.materialize(old,new)
        self.materialize(old_base,new_base,sub)
        # The approved submodule shares the root object database through alternates.
        alternates=subgit/'objects/info/alternates'
        if alternates.is_symlink(): raise Error('symlinked submodule alternates')
        existing=alternates.read_text().splitlines() if alternates.exists() else []
        objects=str(self.gitdir/'objects')
        if objects not in existing:
            atomic(alternates,('\n'.join(existing+[objects])+'\n').encode())
        atomic(subgit/'HEAD',(pin+'\n').encode())
        atomic(self.meta/'upstream.json',(json.dumps({'url':UPSTREAM,'revision':pin},indent=2)+'\n').encode())
        return pin

def atomic(path,data,mode=0o644):
    path=Path(path)
    fd,tmp=tempfile.mkstemp(prefix='.mod-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f: f.write(data)
        os.chmod(tmp,mode); os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def drift(a,b):
    return sorted(k for k in set(a)|set(b) if a.get(k)!=b.get(k))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['status','capture','refresh','apply','verify','update','test'])
    parser.add_argument('argument',nargs='?')
    args=parser.parse_args()
    root=Path(__file__).resolve().parent.parent
    with open(root/'.spotifast-mod/lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        repo=Repo(root)
        try:
            if args.command=='status':
                print(json.dumps({'pin':repo.pin(),'series':repo.series(),
                                  'drift':drift(repo.replay(),repo.scan()),
                                  'submodule_head':(repo.sub_gitdir()/'HEAD').read_text().strip(),
                                  'unstaged_additions':sorted(set(repo.scan())-set(repo.replay())-repo.staged())},indent=2))
            elif args.command in ('capture','update'):
                if not args.argument: raise Error('argument required')
                print(getattr(repo,args.command)(args.argument))
            elif args.command=='refresh': print(repo.capture())
            elif args.command=='apply': print(repo.apply())
            elif args.command=='verify': repo.verify(); print('source matches pinned upstream + ordered patches')
            else:
                subprocess.run(['/usr/bin/python3','-I',str(repo.meta/'test_tool.py')],check=True,env=repo.env)
                repo.verify(); print('maintenance tests and replay verification passed')
        finally: repo.close()

if __name__=='__main__':
    try: main()
    except (Error,OSError,ValueError,subprocess.CalledProcessError) as e:
        print(f'error: {e}',file=sys.stderr); sys.exit(1)
