"""Regression tests for Source content, archive, and local runtime automation."""
import io
import json
import socket
import struct
import tempfile
import threading
import unittest
import wave
import zipfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import agent as a
import sdk_content as c
import sdk_archives as v
import sdk_runtime as r

class ExtensionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.project=self.root/'projects/demo';self.game=self.project/'game/mod_hl2mp'
        self.game.mkdir(parents=True);(self.project/'mapsrc').mkdir();(self.project/'assetsrc').mkdir()
        a.atomic_json(self.project/'.source-agent/project.json',{'name':'demo','template':'hl2mp'})
        self.config={'workspace_root':str(self.root/'projects'),'runtime_root':str(self.root/'Source SDK Base 2013 Multiplayer'),'steam_root':str(self.root/'Steam'),'jobs':4,'map_tools':{},'asset_tools':{}}
        self.mock=patch.object(a,'cfg',return_value=self.config);self.mock.start()
        (self.game/'gameinfo.txt').write_text('GameInfo { FileSystem { SteamAppId 243750 SearchPaths { game |appid_243750|hl2/hl2_misc.vpk game |gameinfo_path|. } } }')
    def tearDown(self):self.mock.stop();self.temp.cleanup()
    def test_keyvalues_duplicate_outputs(self):
        source='// ignored\nroot { "path" "C:\\maps\\room" connections { OnTrigger "a,b,,0,-1" OnTrigger "c,d,,1,1" } }'
        tree=c.parse_kv(source);self.assertEqual(c.parse_kv(c.dump_kv(tree)),tree)
        self.assertEqual(len(c.val(c.val(tree,'root'),'connections')),2)
    def test_keyvalues_malformed(self):
        for text in ('x { y z','x "unfinished','}', 'x'):
            with self.assertRaises(a.AgentError):c.parse_kv(text)
    def test_compiler_game_spaces(self):
        proxy=c.compiler_game('demo',self.project/'.source-agent/compiler',False)
        tree=c.parse_kv((proxy/'gameinfo.txt').read_text());paths=c.val(c.val(c.val(tree,'GameInfo'),'FileSystem'),'SearchPaths')
        self.assertIn(['game',self.config['runtime_root']+'/hl2/hl2_misc.vpk'],paths)
        self.assertFalse(any(k=='SDK' for k,_ in paths))
        self.assertIn('|appid_243750|',(self.game/'gameinfo.txt').read_text())
    def test_compiler_game_windows(self):
        proxy=c.compiler_game('demo',self.project/'.source-agent/compiler',True)
        text=(proxy/'gameinfo.txt').read_text();tree=c.parse_kv(text)
        paths=c.val(c.val(c.val(tree,'GameInfo'),'FileSystem'),'SearchPaths')
        self.assertTrue(any('Source SDK Base' in value and value.startswith('Z:') for _,value in paths))
    def test_map_entity_add_and_stale_edit(self):
        data=a.generate_room('demo');new=c.edit_map_entity('demo','agent_test','',{'classname':'logic_relay','targetname':'test'},data['sha256'],[{'output':'OnTrigger','target':'thing','input':'Enable','parameter':'','delay':0,'times':-1}])
        info=c.inspect_map('demo','agent_test');self.assertEqual(info['brushes'],6)
        self.assertEqual(info['entities'][-1]['targetname'],'test')
        with self.assertRaises(a.AgentError):c.edit_map_entity('demo','agent_test','',{'classname':'light'},data['sha256'])
        self.assertTrue(Path(new['backup']).is_file())
    def test_map_property_id_protected(self):
        data=a.generate_room('demo')
        with self.assertRaises(a.AgentError):c.edit_map_entity('demo','agent_test','',{'id':'1','classname':'light'},data['sha256'])
    def test_texture_header_and_mipmaps(self):
        Image.new('RGBA',(8,4),(10,20,30,128)).save(self.project/'assetsrc/texture.png')
        result=c.compile_texture('demo','assetsrc/texture.png','test/texture');data=Path(result['path']).read_bytes()
        self.assertEqual(data[:4],b'VTF\0');self.assertEqual(struct.unpack_from('<II',data,4),(7,2))
        self.assertEqual(struct.unpack_from('<HH',data,16),(8,4));self.assertEqual(data[56],4)
        self.assertEqual(len(data),80+4*(8*4+4*2+2*1+1))
        self.assertTrue(struct.unpack_from('<I',data,20)[0]&0x2000)
        with self.assertRaises(a.AgentError):c.compile_texture('demo','assetsrc/texture.png','test/texture')
    def test_texture_non_power_two_rejected(self):
        Image.new('RGB',(3,3)).save(self.project/'assetsrc/bad.png')
        with self.assertRaises(a.AgentError):c.compile_texture('demo','assetsrc/bad.png','bad')
    def test_material_nested_proxies(self):
        result=c.create_material('demo','test/water','Water',{'$basetexture':'test/a','Proxies':{'Sine':{'sineperiod':1}}})
        tree=c.parse_kv(Path(result['path']).read_text());self.assertIsInstance(c.val(c.val(tree,'Water'),'Proxies'),list)
    def test_audio_canonical_header(self):
        path=self.project/'assetsrc/audio.wav'
        with wave.open(str(path),'wb') as f:
            f.setnchannels(1);f.setsampwidth(2);f.setframerate(22050);f.writeframes(b'\0\0'*2205)
        result=c.convert_sound('demo','assetsrc/audio.wav','test/tone')
        with wave.open(result['path'],'rb') as f:
            self.assertEqual(f.getframerate(),44100);self.assertEqual(f.getnframes(),4410);self.assertEqual(f.getsampwidth(),2)
        data=Path(result['path']).read_bytes();self.assertEqual(struct.unpack_from('<I',data,4)[0]+8,len(data))
    def test_vpk_roundtrip_and_mod_packaging(self):
        source=self.project/'bundle/materials/test';source.mkdir(parents=True);(source/'a.vmt').write_text('UnlitGeneric {}')
        result=v.pack_vpk('demo','bundle','test','Original test fixture')
        entries=v.parse_vpk(Path(result['path']).read_bytes());self.assertEqual(entries[0]['path'],'materials/test/a.vmt')
        archive=a.package_mod('demo')
        with zipfile.ZipFile(archive['archive']) as z:self.assertIn('demo/custom/test.vpk',z.namelist())
        Path(result['path']).write_bytes(b'modified outside registry')
        archive=a.package_mod('demo')
        with zipfile.ZipFile(archive['archive']) as z:self.assertNotIn('demo/custom/test.vpk',z.namelist())
    def test_vpk_truncated(self):
        for data in (b'',struct.pack('<3I',0x55aa1234,1,100),struct.pack('<3I',0x55aa1234,1,3)+b'a\0b'):
            with self.assertRaises(a.AgentError):v.parse_vpk(data)
    def test_vpk_reject_executable(self):
        folder=self.project/'bundle/materials';folder.mkdir(parents=True);(folder/'bad.exe').write_bytes(b'test')
        with self.assertRaises(a.AgentError):v.pack_vpk('demo','bundle','bad','test')
    def test_asset_provenance(self):
        Image.new('RGB',(2,2)).save(self.project/'assetsrc/tiny.png')
        result=c.import_asset('demo','assetsrc/tiny.png','materials/source/tiny.png','Original generated fixture')
        self.assertEqual(json.loads((self.project/'.source-agent/assets.json').read_text())['materials/source/tiny.png']['sha256'],result['sha256'])
        with self.assertRaises(a.AgentError):c.import_asset('demo','../secret.png','materials/secret.png','no')
    def test_rcon_fragmented_packet(self):
        sender,receiver=socket.socketpair();packet=r._packet(7,0,'hello')
        def transmit():
            for byte in packet:sender.send(bytes([byte]))
            sender.close()
        t=threading.Thread(target=transmit);t.start()
        try:self.assertEqual(r._recv_packet(receiver),(7,0,b'hello'))
        finally:receiver.close();t.join()
    def test_rcon_invalid_size(self):
        sender,receiver=socket.socketpair();sender.sendall(struct.pack('<i',2000000))
        try:
            with self.assertRaises(a.AgentError):r._recv_packet(receiver)
        finally:sender.close();receiver.close()
    def test_server_requires_binaries(self):
        with self.assertRaises(a.AgentError):r.start_server('demo','missing')
    def test_server_requires_managed_session(self):
        with self.assertRaises(a.AgentError):r.console_command('demo','status')
    def test_console_multiline_rejected(self):
        with self.assertRaises(a.AgentError):r.console_command('demo','status\nquit')
    def test_source_search(self):
        (self.project/'src').mkdir();(self.project/'src/test.cpp').write_text('test\nCUSTOM_ENTITY\n')
        result=r.search_source('demo','custom_entity');self.assertEqual(result['matches'][0]['line'],2)
    def test_bsp_bounds(self):
        folder=self.game/'maps';folder.mkdir();data=bytearray(1036);struct.pack_into('<4sI',data,0,b'VBSP',20);struct.pack_into('<4I',data,8,1036,50,0,0)
        (folder/'bad.bsp').write_bytes(data)
        with self.assertRaises(a.AgentError):c.inspect_bsp('demo','bad')

if __name__=='__main__':unittest.main(verbosity=2)
