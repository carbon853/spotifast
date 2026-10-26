#!/usr/bin/python3
"""Fetch an exact fork commit and its one approved submodule; verify raw checkout.
Run this reviewed local script with python3 -I and a full commit SHA.
"""
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('maintenance',HERE/'tool.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
FORK='https://github.com/carbon853/spotifast.git'
MODULES=b'[submodule "spotifast"]\n\tpath = lib/spotifast\n\turl = https://github.com/crmne/spotifast.git\n\tupdate = checkout\n'

def check(revision):
    if not re.fullmatch('[0-9a-f]{40}',revision): raise m.Error('supply a full fork commit SHA')
    (HERE/'scratch').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=HERE/'scratch',prefix='fresh-') as tmp:
        root=Path(tmp)
        (root/'.spotifast-mod').mkdir()
        env={'PATH':'/usr/bin:/bin','HOME':'/nonexistent','GIT_CONFIG_GLOBAL':'/dev/null','GIT_CONFIG_NOSYSTEM':'1'}
        subprocess.run(['/usr/bin/git','-c','init.templateDir=','init','-q',str(root)],check=True,env=env)
        r=m.Repo(root)
        try:
            r.run('fetch','--no-tags','--no-recurse-submodules',FORK,revision)
            got=r.run('rev-parse','FETCH_HEAD^{commit}').decode().strip()
            if got!=revision: raise m.Error('fork commit mismatch')
            source={};metadata={};gitlink=None
            # Inspect every path/mode and blob before checkout; no fetched code runs.
            for item in r.run('ls-tree','-rz',revision).split(b'\0'):
                if not item:continue
                header,raw=item.split(b'\t',1);mode,kind,oid=header.decode().split();name=raw.decode()
                if name=='lib/spotifast' and mode=='160000' and kind=='commit':
                    gitlink=oid;continue
                if kind!='blob':raise m.Error('unexpected nested module: '+name)
                data=r.run('cat-file','blob',oid)
                if name=='.gitmodules':
                    if mode!='100644' or data!=MODULES:raise m.Error('unapproved submodule metadata')
                    metadata[name]=(mode,data)
                elif name.startswith('.spotifast-mod/'):
                    rel=name.split('/',1)[1];m.safe_path(rel)
                    if rel.split('/')[0] in ('scratch','local','lock','__pycache__') or mode!='100644':
                        raise m.Error('unexpected maintenance entry: '+name)
                    metadata[name]=(mode,data)
                else:
                    m.safe_path(name);source[name]=(mode,data)
            m.validate(source)
            if '.gitmodules' not in metadata or gitlink is None:raise m.Error('approved submodule missing')
            pin=json.loads(metadata['.spotifast-mod/upstream.json'][1])
            if pin!={'url':m.UPSTREAM,'revision':gitlink}:raise m.Error('submodule/pin mismatch')
            for name in ('tool.py','test_tool.py','fresh_check.py','local.py','rebase.py','test_local.py','visual_check.py'):
                if metadata['.spotifast-mod/'+name][1]!=(HERE/name).read_bytes():
                    raise m.Error('fresh maintenance code differs from reviewed code: '+name)
            r.materialize({},source)
            for name,(mode,data) in metadata.items():
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);m.atomic(p,data)
            r.run('read-tree',revision,index=root/'.git/index')
            m.atomic(root/'.git/HEAD',(revision+'\n').encode())
            sub=root/'lib/spotifast';sub.mkdir(parents=True)
            r.run('init',str(sub),initial=True)
            # Independently fetch only the approved submodule's exact commit.
            r.env['GIT_OBJECT_DIRECTORY']=str(sub/'.git/objects')
            r.run('fetch','--no-tags','--no-recurse-submodules',m.UPSTREAM,gitlink)
            if r.run('rev-parse','FETCH_HEAD^{commit}').decode().strip()!=gitlink:
                raise m.Error('submodule fetch mismatch')
            pristine=r.read_tree(gitlink)
            r.materialize({},pristine,sub)
            r.run('read-tree',gitlink,index=sub/'.git/index')
            m.atomic(sub/'.git/HEAD',(gitlink+'\n').encode())
            r.env['GIT_OBJECT_DIRECTORY']=str(root/'.git/objects')
            r.env['GIT_ALTERNATE_OBJECT_DIRECTORIES']=str(sub/'.git/objects')
            index=(root/'.git/index').read_bytes()
            r.verify()
            subprocess.run(['/usr/bin/python3','-I',str(root/'.spotifast-mod/tool.py'),'test'],
                           check=True,env=env)
            if index!=(root/'.git/index').read_bytes():raise m.Error('developer index changed')
            r.verify()
            print(json.dumps({'fresh_fork_commit':revision,'approved_submodule':gitlink,
                              'source_entries':len(source),'root_index_unchanged':True,
                              'maintenance_code_matches_reviewed_copy':True},indent=2))
        finally:r.close()

if __name__=='__main__':
    try:
        if len(sys.argv)!=2:raise m.Error(__doc__)
        check(sys.argv[1])
    except (m.Error,OSError,ValueError,KeyError,subprocess.CalledProcessError) as e:
        print('error:',e,file=sys.stderr);sys.exit(1)
