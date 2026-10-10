import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import agent

class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.workspace=self.root/'projects'
        self.project=self.workspace/'demo'
        self.game=self.project/'game/mod_hl2mp'
        self.game.mkdir(parents=True)
        (self.project/'src').mkdir()
        (self.project/'mapsrc').mkdir()
        agent.atomic_json(self.project/'.source-agent/project.json', {'name':'demo','template':'hl2mp'})
        self.config={'workspace_root':str(self.workspace),'steam_root':str(self.root/'Steam'),'map_tools':{}}
        self.patcher=patch.object(agent,'cfg',return_value=self.config)
        self.patcher.start()
        (self.game/'gameinfo.txt').write_text('"GameInfo" {}\n')
    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()
    def test_slug(self):
        self.assertEqual(agent.slug('my_game-1'),'my_game-1')
        for s in ('../etc','-bad','a/b','a;echo','UPPER','x'*49):
            with self.assertRaises(agent.AgentError): agent.slug(s)
    def test_traversal(self):
        for s in ('../secret','/etc/passwd','src/../../secret','.git/config','.source-agent/project.json'):
            with self.assertRaises(agent.AgentError): agent.read_text('demo',s)
    def test_symlink_outside(self):
        (self.root/'secret.txt').write_text('private')
        (self.project/'src/link.txt').symlink_to(self.root/'secret.txt')
        with self.assertRaises(agent.AgentError): agent.read_text('demo','src/link.txt')
    def test_symlink_internal_metadata(self):
        (self.project/'src/link.json').symlink_to(self.project/'.source-agent/project.json')
        with self.assertRaises(agent.AgentError): agent.read_text('demo','src/link.json')
    def test_write_and_backup(self):
        a=agent.write_text('demo','src/test.cpp','old\n')
        with self.assertRaises(agent.AgentError): agent.write_text('demo','src/test.cpp','new\n')
        with self.assertRaises(agent.AgentError): agent.write_text('demo','src/test.cpp','new\n','wrong')
        b=agent.write_text('demo','src/test.cpp','new\n',a['sha256'])
        self.assertEqual(Path(b['backup']).read_text(),'old\n')
        self.assertEqual(agent.read_text('demo','src/test.cpp')['text'],'new\n')
    def test_missing_expected_file(self):
        with self.assertRaises(agent.AgentError): agent.write_text('demo','src/missing.cpp','x','oldhash')
    def test_reject_shell_file(self):
        with self.assertRaises(agent.AgentError): agent.write_text('demo','src/run.sh','echo no')
    def test_reject_binary(self):
        with self.assertRaises(agent.AgentError): agent.write_text('demo','src/test.cpp','\x00')
    def test_map(self):
        result=agent.generate_room('demo')
        self.assertFalse(result['compiled'])
        text=Path(result['path']).read_text()
        self.assertEqual(text.count('solid\n{'),6)
        self.assertEqual(text.count('side\n{'),36)
        ids=re.findall(r'"id" "(\d+)"',text)
        self.assertEqual(len(ids),len(set(ids)))
        planes=re.findall(r'"plane" "([^"\n]+)"',text)
        us=re.findall(r'"uaxis" "\[([^]]+)\]',text)
        vs=re.findall(r'"vaxis" "\[([^]]+)\]',text)
        centers=[(0,0,-16),(0,0,272),(-528,0,128),(528,0,128),(0,-528,128),(0,528,128)]
        def sub(a,b): return tuple(x-y for x,y in zip(a,b))
        def dot(a,b): return sum(x*y for x,y in zip(a,b))
        def cross(a,b): return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
        for i,plane in enumerate(planes):
            pts=[tuple(map(float,p.split())) for p in re.findall(r'\(([^)]+)\)',plane)]
            n=cross(sub(pts[0],pts[1]),sub(pts[2],pts[1]))
            self.assertLess(dot(n,centers[i//6])-dot(n,pts[0]),0)
            self.assertEqual(dot(n,tuple(map(float,us[i].split()[:3]))),0)
            self.assertEqual(dot(n,tuple(map(float,vs[i].split()[:3]))),0)
        with self.assertRaises(agent.AgentError): agent.generate_room('demo')
    def test_missing_map_compilers(self):
        agent.generate_room('demo')
        with self.assertRaisesRegex(agent.AgentError,'vbsp, vvis, vrad'):
            agent.compile_map('demo','agent_test')
    def test_registration_idempotent(self):
        a=agent.register_mod('demo')
        self.assertEqual(a,agent.register_mod('demo'))
        self.assertTrue(Path(a['link']).is_symlink())
    def test_registration_collision(self):
        p=self.root/'Steam/steamapps/sourcemods/demo'
        p.mkdir(parents=True)
        with self.assertRaises(agent.AgentError): agent.register_mod('demo')
    def test_package_excludes_external_content(self):
        (self.root/'secret.txt').write_text('secret')
        (self.game/'secret.txt').symlink_to(self.root/'secret.txt')
        (self.game/'console.log').write_text('private logs')
        (self.game/'base.vpk').write_bytes(b'not redistributable')
        (self.game/'download').mkdir()
        (self.game/'download/a.txt').write_text('server download')
        data=agent.package_mod('demo')
        with zipfile.ZipFile(data['archive']) as z:
            names=z.namelist()
            self.assertIn('demo/gameinfo.txt',names)
            for excluded in ('demo/secret.txt','demo/console.log','demo/base.vpk','demo/download/a.txt'):
                self.assertNotIn(excluded,names)
        self.assertFalse(data['has_game_binaries'])
    def test_no_uncompiled_launch(self):
        with self.assertRaises(agent.AgentError): agent.launch('demo')
    def test_job_id(self):
        with self.assertRaises(agent.AgentError): agent.job_file('../../etc')
    def test_lock(self):
        with agent.lock(self.project/'.source-agent/test.lock'):
            with self.assertRaises(agent.AgentError):
                with agent.lock(self.project/'.source-agent/test.lock'): pass

if __name__=='__main__': unittest.main(verbosity=2)
