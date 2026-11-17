"""Real replay sandbox cases collected by test_replay_sandbox, with no model.

PlayerBoundaryTest uses a portable stand-in, not a Unity engine. Native cases
require actual licensed-build artifacts and say so in their named skips.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from harness import sandbox as box, tree
from harness.unity import run as unity
from tests import test_unity_harness as fixture

ROOT=Path(__file__).resolve().parents[1]
PATCH=ROOT/'tests/fixtures/unity-sandbox-probe.patch'

# A standard-library counterpart of the C# canary, for real-process OS tests.
# No fixture/observer result here is represented as a native Unity measurement.
PROBE=r'''
def boundary_probe(argv):
    file = Path(__file__).with_name('probe.json')
    print('EXPECTRAIL_UNITY_UID '+str(os.geteuid())+':'+str(os.getegid()),flush=True)
    if not file.exists(): return
    c = json.loads(file.read_text()); success = False
    try:
        if c['mode']=='socket':
            import socket
            with socket.create_connection(('127.0.0.1',c['port']),timeout=1): pass
        elif c['mode']=='write': Path(c['outside']).write_text('probe')
        elif c['mode']=='policy':
            for name in ('spec','verifier'):
                with open(c[name],'rb') as f: f.read(1)
        elif c['mode']=='secret':
            assert b'EXPECTRAIL_SANDBOX_TEST_ONLY=fixture-value' in Path('/proc/'+str(c['secretPid'])+'/environ').read_bytes()
        elif c['mode']=='inputs':
            with file.open('ab'): pass
        else: raise ValueError('unknown synthetic probe')
        success=True
    except (OSError,AssertionError): pass
    print('EXPECTRAIL_UNITY_PROBE '+str(success).lower(),flush=True)
    if not success: sys.exit(73)

if __name__ == '__main__':
    boundary_probe(sys.argv[1:])
    sys.exit(main(sys.argv[1:]))
'''


def portable_player(folder, patches=()):
    folder=Path(folder);exe=folder/unity.PLAYER;exe.parent.mkdir(parents=True)
    source=fixture.FAKE.read_text()
    tail='if __name__ == "__main__":\n    sys.exit(main(sys.argv[1:]))'
    assert tail in source
    exe.write_text('#!/usr/bin/python3\n'+source.replace(tail,PROBE));exe.chmod(0o755)
    doc=unity.build_key(fixture.GAME,list(patches));doc['player']=unity.PLAYER
    (folder/'build.json').write_text(json.dumps(doc))
    return folder


def require_tool():
    tool,why=box.probe(True)
    if tool is None:
        reason='Bubblewrap/Unity replay display unavailable: '+str(why)
        if os.environ.get('EXPECTRAIL_SANDBOX_TESTS')=='required' or os.environ.get('EXPECTRAIL_UNITY_SANDBOX_TESTS')=='required':
            raise AssertionError(reason)
        raise unittest.SkipTest(reason)
    return tool


class PlayerBoundaryTest(unittest.TestCase):
    """Real processes in Bubblewrap, portable Unity-protocol stand-in only."""
    engine_label='portable Unity-protocol stand-in'
    @classmethod
    def setUpClass(cls): require_tool()

    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='expectrail-unity-boundary-');self.addCleanup(temp.cleanup)
        self.tmp=Path(temp.name)
        self.clean=portable_player(self.tmp/'clean')
        self.probe=portable_player(self.tmp/'probe',[PATCH])
        self.route=fixture.route(self.tmp)

    def replay(self, player, name, mode, patches=()):
        # A host display may be used by this non-rendering outside control; the
        # sandboxed command must ignore it and start its own Xvfb.
        with mock.patch.dict(os.environ,{'DISPLAY':':99'}):
            return unity.run(self.route,self.tmp/name,list(patches),player=player,sandbox=mode)

    def boundary(self, config):
        target=self.probe/'player/probe.json';target.write_text(json.dumps(config))
        control=self.replay(self.probe,'outside','off',[PATCH])
        self.assertEqual(control['isolation']['network'],'host')
        self.assertIn('EXPECTRAIL_UNITY_PROBE true',(self.tmp/'outside/unity.log').read_text())
        with self.assertRaises(SystemExit):self.replay(self.probe,'inside','require',[PATCH])
        self.assertFalse((self.tmp/'inside/replay.json').exists(),'a failed player cannot publish an accepted replay')
        self.assertIn('EXPECTRAIL_UNITY_PROBE false',(self.tmp/'inside/unity.log').read_text())
        print(json.dumps({'engine':self.engine_label,'case':config['mode'],
                          'outsideSucceeded':True,'insideSucceeded':False,'replayPublished':False}))

    def test_socket_is_denied_and_no_replay_is_published(self):
        from tests.test_replay_sandbox import Listener
        with Listener() as port:self.boundary({'mode':'socket','port':port})

    def test_outside_write_is_denied_and_no_replay_is_published(self):
        self.boundary({'mode':'write','outside':str(self.tmp/'outside-write')})
        self.assertEqual((self.tmp/'outside-write').read_text(),'probe')

    def test_actual_spec_and_verifier_reads_are_denied(self):
        self.boundary({'mode':'policy','spec':str(ROOT/'agents/specs/player-stays-above-ground.json'),
                       'verifier':str(ROOT/'expectrail/gate/record.py')})

    def test_synthetic_environment_secret_read_is_denied(self):
        with subprocess.Popen(['/usr/bin/python3','-c','import time; time.sleep(300)'],
                              env={'EXPECTRAIL_SANDBOX_TEST_ONLY':'fixture-value'}) as child:
            try:self.boundary({'mode':'secret','secretPid':child.pid})
            finally:child.terminate();child.wait(timeout=10)

    def test_runtime_input_is_readonly(self):self.boundary({'mode':'inputs'})

    def test_clean_frame_and_trace_hashes_are_unchanged(self):
        before=tree.digest(fixture.GAME,skip=unity.UNITY_IGNORE)
        plain=self.replay(self.clean,'plain','off')
        isolated=self.replay(self.clean,'isolated','require')
        self.assertTrue(plain['frameSha256'])
        self.assertEqual(unity.compare(plain,isolated),{'framesDiffer':[],'traceDiffers':False,'identical':True})
        self.assertEqual(isolated['isolation']['network'],'none')
        if self.engine_label.startswith('portable'):
            identity='EXPECTRAIL_UNITY_UID '+str(isolated['isolation']['uid'])+':'+str(isolated['isolation']['gid'])
            self.assertIn(identity,(self.tmp/'isolated/unity.log').read_text())
        self.assertEqual(tree.digest(fixture.GAME,skip=unity.UNITY_IGNORE),before)


class NativeUnityBoundaryTest(PlayerBoundaryTest):
    """The same cases on actual clean/probe Unity players, never a stand-in."""
    engine_label='native Unity'
    @classmethod
    def setUpClass(cls):
        cls.sources=[os.environ.get('EXPECTRAIL_UNITY_CLEAN_PLAYER'),os.environ.get('EXPECTRAIL_UNITY_PROBE_PLAYER')]
        if not all(cls.sources):
            reason='native Unity sandbox cases need EXPECTRAIL_UNITY_CLEAN_PLAYER and EXPECTRAIL_UNITY_PROBE_PLAYER from licensed builds'
            if os.environ.get('EXPECTRAIL_UNITY_SANDBOX_TESTS')=='required':raise AssertionError(reason)
            raise unittest.SkipTest(reason)
        require_tool()

    def setUp(self):
        keep=os.environ.get('EXPECTRAIL_UNITY_SANDBOX_EVIDENCE')
        if keep:
            self.tmp=Path(keep).resolve()/self._testMethodName;self.tmp.mkdir(parents=True,exist_ok=False)
            self.addCleanup(self.trim_evidence)
        else:
            temp=tempfile.TemporaryDirectory(prefix='expectrail-native-unity-');self.addCleanup(temp.cleanup);self.tmp=Path(temp.name)
        copies=[]
        for i,source in enumerate(self.sources):
            source=Path(source).resolve();dest=self.tmp/('player-'+str(i));dest.mkdir()
            tree.copy(source/'player',dest/'player',within=source/'player',skip=())
            (dest/'build.json').write_text(json.dumps(unity.read_build(source)));copies.append(dest)
        self.clean,self.probe=copies;self.route=fixture.route(self.tmp)

    def replay(self, player, name, mode, patches=()):
        # Native outside controls require their own real virtual display too.
        with mock.patch.dict(os.environ,{},clear=False):
            os.environ.pop('DISPLAY',None)
            return unity.run(self.route,self.tmp/name,list(patches),player=player,sandbox=mode)


    def trim_evidence(self):
        # Retain the actual accounts, trace bytes, frames and logs, never bulk
        # copies of the build/runtime/project or PlayerPrefs. CI uploads runs/.
        for name in ('player-0','player-1'):
            shutil.rmtree(self.tmp/name,ignore_errors=True)
        for folder in self.tmp.iterdir():
            if folder.is_dir():
                for name in ('work','home','player-output'):
                    shutil.rmtree(folder/name,ignore_errors=True)
