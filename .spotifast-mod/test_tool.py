#!/usr/bin/python3
"""Maintenance-only fixtures: no application or dependency code is executed."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('maintenance', HERE/'tool.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=HERE/'scratch',prefix='test-')
        self.root=Path(self.tmp.name)
        (self.root/'.spotifast-mod/patches').mkdir(parents=True)
        (self.root/'.spotifast-mod/series').write_text('')
        env={'PATH':'/usr/bin:/bin','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null'}
        subprocess.run(['/usr/bin/git','-c','init.templateDir=','init','-q',str(self.root)],check=True,env=env)
        self.r=m.Repo(self.root)
        self.r.env.update(GIT_AUTHOR_NAME='Fixture',GIT_AUTHOR_EMAIL='fixture@example.invalid',
                          GIT_COMMITTER_NAME='Fixture',GIT_COMMITTER_EMAIL='fixture@example.invalid',
                          GIT_AUTHOR_DATE='2000-01-01T00:00:00Z',GIT_COMMITTER_DATE='2000-01-01T00:00:00Z')
        self.base={'a':('100644',b'base\n'),'remove':('100644',b'delete me\n')}
        self.pin=self.commit(self.base)
        self.pinfile=self.root/'.spotifast-mod/upstream.json'
        self.pinfile.write_text(json.dumps({'url':m.UPSTREAM,'revision':self.pin}))
        self.r.materialize({},self.base)
        self.stage(self.base)
        self.submodule()
    def tearDown(self):
        self.r.close();self.tmp.cleanup()
    def commit(self,tree):
        return self.r.run('commit-tree',self.r.tree_id(tree),data=b'fixture\n').decode().strip()
    def stage(self,tree):
        self.r.run('read-tree',self.r.tree_id(tree),index=self.root/'.git/index')
    def change(self,tree):
        self.r.materialize(self.r.scan(),tree)
    def test_multiple_binary_modes_symlinks_and_determinism(self):
        first={'a':('100755',b'one\n'),'binary':('100644',b'\0\xffbinary\n'),
               'safe link':('120000',b'a'), '$(touch SENTINEL); file':('100644',b'weird name\n')}
        self.change(first);self.stage(first)
        index=(self.root/'.git/index').read_bytes()
        self.r.capture('first');patch=(self.r.meta/'patches/0001-first.patch').read_bytes()
        self.r.capture();self.assertEqual(patch,(self.r.meta/'patches/0001-first.patch').read_bytes())
        second=dict(first,a=('100755',b'two\n'))
        self.change(second);self.r.capture('second');self.assertEqual(self.r.verify(),second)
        self.assertEqual(index,(self.root/'.git/index').read_bytes())
        self.change(self.base);self.assertEqual(self.r.apply(),'applied');self.assertEqual(self.r.scan(),second)
        before=(self.root/'a').stat().st_mtime_ns
        self.assertIn('no-op',self.r.apply());self.assertEqual(before,(self.root/'a').stat().st_mtime_ns)
        self.assertFalse((self.root/'SENTINEL').exists())
    def test_untracked_and_dirty_protection(self):
        (self.root/'new').write_text('new')
        with self.assertRaisesRegex(m.Error,'stage new'):self.r.capture('new')
        with self.assertRaisesRegex(m.Error,'source drift'):self.r.verify()
        with self.assertRaisesRegex(m.Error,'overwrite local'):self.r.apply()
        self.assertEqual((self.root/'new').read_text(),'new')
    def test_refresh_latest_only(self):
        (self.root/'a').write_text('one\n');self.r.capture('one')
        first=(self.r.meta/'patches/0001-one.patch').read_bytes()
        (self.root/'a').write_text('two\n');self.r.capture('two')
        (self.root/'a').write_text('three\n');self.r.capture()
        self.assertEqual(first,(self.r.meta/'patches/0001-one.patch').read_bytes());self.r.verify()
    def test_reserved_traversal_and_control_names(self):
        for name in ['../escape','/absolute','a/../../x','.git/config','.gitmodules',
                     '.spotifast-mod/tool.py','lib/spotifast/a','x/.GiT/config','a\nb','a\\b','a//b']:
            with self.subTest(name=name),self.assertRaises(m.Error):m.validate({name:('100644',b'x')})
    def test_symlink_escape_chain_cycle_and_parent(self):
        cases=[{'link':('120000',b'../outside')},{'link':('120000',b'/etc/passwd')},
               {'link':('120000',b'.git/config')},{'a':('120000',b'b'),'b':('120000',b'../../escape')},
               {'a':('120000',b'b'),'b':('120000',b'a')},
               {'link':('120000',b'a'),'link/x':('100644',b'x')}]
        for tree in cases:
            with self.subTest(tree=tree),self.assertRaises(m.Error):m.validate(tree)
        m.validate({'d/link':('120000',b'../a'),'a':('100644',b'ok')})
    def test_malicious_patch_is_only_in_temporary_index(self):
        changed=dict(self.base,innocent=('100644',b'bad\n'))
        patch=self.r.diff(self.base,changed)
        for path in [b'../escape',b'.spotifast-mod/tool.py',b'.git/config',b'lib/spotifast/a']:
            (self.r.meta/'patches/0001-bad.patch').write_bytes(patch.replace(b'innocent',path))
            (self.r.meta/'series').write_text('0001-bad.patch\n')
            with self.assertRaisesRegex(m.Error,'0001-bad.patch'):self.r.replay()
            self.assertEqual(self.r.scan(),self.base)
    def test_symlink_patch_rejected_without_materialization(self):
        patch=self.r.diff(self.base,dict(self.base,link=('120000',b'a')))
        patch=patch.replace(b'+a\n',b'+/outside\n')
        (self.r.meta/'patches/0001-link.patch').write_bytes(patch)
        (self.r.meta/'series').write_text('0001-link.patch\n')
        with self.assertRaises(m.Error):self.r.apply()
        self.assertFalse((self.root/'link').exists())
    def test_hooks_filters_diff_fsmonitor_and_environment_do_not_execute(self):
        sentinel=self.root/'SENTINEL'
        command=f'touch {sentinel}'
        (self.root/'.git/config').write_text(f'''[core]
 hooksPath = {self.r.meta}/hooks
 fsmonitor = {command}
[filter "evil"]
 clean = {command}
 smudge = {command}
 process = {command}
 required = true
[diff]
 external = {command}
[diff "evil"]
 textconv = {command}
[submodule "evil"]
 update = !{command}
''')
        (self.root/'hooks').mkdir();hook=self.root/'hooks/post-checkout';hook.write_text('#!/bin/sh\n'+command);hook.chmod(0o755)
        # Keep fixture hook files outside the source scan.
        (self.root/'hooks').rename(self.r.meta/'hooks')
        (self.root/'.gitattributes').write_text('* filter=evil diff=evil\n')
        self.stage(self.r.scan());self.r.capture('attributes');self.r.verify()
        self.change(self.base);self.r.apply();self.r.verify()
        self.assertFalse(sentinel.exists())
    def submodule(self):
        sub=self.root/'lib/spotifast'
        if sub.exists(): return sub
        sub.mkdir(parents=True)
        self.r.run('init',str(sub),initial=True)
        (sub/'.git/objects/info/alternates').write_text(str(self.root/'.git/objects')+'\n')
        (sub/'.git/HEAD').write_text(self.pin+'\n')
        self.r.materialize({},self.base,sub)
        return sub
    def fake_fetch(self,newpin):
        original=self.r.run
        def run(*args,**kwargs):
            if args[0]=='fetch':return b''
            if args==('rev-parse','FETCH_HEAD^{commit}'):return (newpin+'\n').encode()
            return original(*args,**kwargs)
        self.r.run=run
    def test_upstream_conflict_leaves_checkout_pin_and_index_unchanged(self):
        sub=self.submodule();(self.root/'a').write_text('local feature\n');self.r.capture('feature');self.stage(self.r.scan())
        current=self.r.scan();before=self.pinfile.read_bytes();index=(self.root/'.git/index').read_bytes()
        incoming=self.commit(dict(self.base,a=('100644',b'upstream change\n')));self.fake_fetch(incoming)
        with self.assertRaisesRegex(m.Error,'0001-feature.patch'):self.r.update('main')
        self.assertEqual(current,self.r.scan());self.assertEqual(before,self.pinfile.read_bytes())
        self.assertEqual(index,(self.root/'.git/index').read_bytes());self.assertEqual(self.r.scan(sub),self.base)
    def test_successful_update_and_dirty_submodule(self):
        sub=self.submodule();new=dict(self.base,upstream=('100644',b'new\n'))
        incoming=self.commit(new);self.fake_fetch(incoming)
        (sub/'a').write_text('dirty')
        with self.assertRaisesRegex(m.Error,'submodule source drift'):self.r.update('main')
        (sub/'a').write_bytes(self.base['a'][1])
        self.assertEqual(self.r.update('main'),incoming);self.r.verify()
        self.assertEqual(self.r.scan(sub),new);self.assertEqual((sub/'.git/HEAD').read_text().strip(),incoming)
    def test_staged_only_changes_block_update(self):
        self.stage(dict(self.base,a=('100644',b'staged only')))
        self.fake_fetch(self.pin)
        with self.assertRaisesRegex(m.Error,'index source differs'):self.r.update('main')
        self.assertEqual(self.r.scan(),self.base)
    def test_unmerged_index_is_not_captured(self):
        oid=self.r.run('hash-object','-w','--stdin',data=b'x').strip()
        self.r.run('update-index','--index-info',data=b'0 '+b'0'*40+b'\ta\n',index=self.root/'.git/index')
        self.r.run('update-index','--index-info',data=b'100644 '+oid+b' 1\ta\n',index=self.root/'.git/index')
        with self.assertRaisesRegex(m.Error,'index conflicts'):self.r.capture('conflict')
    def test_gitfile_submodule_supported(self):
        sub=self.root/'lib/spotifast'
        target=self.root/'.git/modules/spotifast';target.parent.mkdir()
        (sub/'.git').rename(target)
        (sub/'.git').write_text('gitdir: ../../.git/modules/spotifast\n')
        self.r.verify()
        new=self.commit(dict(self.base,new=('100644',b'new')));self.fake_fetch(new)
        self.r.update('main');self.r.verify()
        self.assertEqual((target/'HEAD').read_text().strip(),new)
    def test_upstream_reserved_paths_never_replace_tooling(self):
        # Construct an adversarial commit without using our validating tree builder.
        self.r.run('read-tree',self.pin)
        oid=self.r.run('hash-object','-w','--stdin',data=b'evil').decode().strip()
        self.r.run('update-index','--add','--cacheinfo','100644',oid,'.spotifast-mod/tool.py')
        incoming=self.r.run('commit-tree',self.r.run('write-tree').decode().strip(),data=b'bad').decode().strip()
        self.fake_fetch(incoming);before=self.pinfile.read_bytes()
        with self.assertRaisesRegex(m.Error,'reserved'):self.r.update('main')
        self.assertEqual(self.pinfile.read_bytes(),before);self.assertEqual(self.r.scan(),self.base)
    def test_symlink_parent_preflight_does_not_write_outside(self):
        # A safe internal link cannot be replaced by a directory implicitly.
        linked=dict(self.base,d=('120000',b'.'))
        self.change(linked)
        after=dict(self.base,**{'d/new':('100644',b'new')})
        with self.assertRaisesRegex(m.Error,'symlink parent'):self.r.materialize(linked,after)
        self.assertEqual(self.r.scan(),linked);self.assertFalse((self.root/'new').exists())
    def test_pin_can_live_only_in_approved_submodule_object_database(self):
        sub=self.root/'lib/spotifast/.git'
        (sub/'objects/info/alternates').unlink()
        # A future upstream commit is not necessarily an ancestor of fork HEAD.
        source=self.root/'.git/objects'/self.pin[:2]/self.pin[2:]
        target=sub/'objects'/self.pin[:2]/self.pin[2:]
        target.parent.mkdir(exist_ok=True);shutil.copyfile(source,target);source.unlink()
        self.r.close();self.r=m.Repo(self.root)
        self.r.verify()
    def test_series_validation(self):
        for series in ['../bad\n','0001-x.patch\n0001-x.patch\n','/tmp/x\n']:
            (self.r.meta/'series').write_text(series)
            with self.assertRaises(m.Error):self.r.series()

if __name__=='__main__':unittest.main(verbosity=2)
