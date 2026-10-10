"""Owned local Source server sessions, console control, source search and capability reporting."""
from __future__ import annotations
import contextlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import struct
import subprocess
import time
import uuid
import agent as a
from sdk_content import compiler_game, parse_kv, dump_kv, val, setval


def search_source(name: str, query: str, directory: str = 'src', limit: int = 60) -> dict:
    """Search literal text within project source, with bounded file sizes/results and no external symlink traversal."""
    root,_=a.project(name); base=a.contained(root,directory,True)
    if not query or len(query)>300:raise a.AgentError('Query must be 1–300 characters.')
    results=[]; limit=max(1,min(int(limit),200)); visited=0
    for p in base.rglob('*'):
        if not p.is_file() or p.is_symlink() or p.suffix.lower() not in a.TEXT_EXT:continue
        try:p=a.contained(root,str(p.relative_to(root)))
        except a.AgentError:continue
        if p.stat().st_size>4*1024*1024:continue
        visited+=1
        for line_no,line in enumerate(p.read_text(errors='replace').splitlines(),1):
            if query.lower() in line.lower():
                results.append({'path':str(p.relative_to(root)),'line':line_no,'text':line[:800]})
                if len(results)>=limit:return {'matches':results,'truncated':True,'files_scanned':visited}
    return {'matches':results,'truncated':False,'files_scanned':visited}


def session_path(name: str) -> Path:
    root,_=a.project(name); folder=root/'.source-agent/sessions';folder.mkdir(parents=True,exist_ok=True);folder.chmod(0o700)
    return folder/'server.json'


def load_session(name: str) -> dict:
    path=session_path(name)
    if not path.is_file():raise a.AgentError('This project has no managed server session.')
    return json.loads(path.read_text())


def alive(data: dict) -> bool:
    pid=data.get('pid')
    if not pid or a.proc_start(pid)!=data.get('process_start'):return False
    try:
        p=Path(f'/proc/{pid}')
        return p.stat().st_uid==os.getuid() and (p/'stat').read_text().rsplit(')',1)[1].split()[0]!='Z'
    except OSError:return False


def _recv_exact(sock: socket.socket, count: int) -> bytes:
    out=b''
    while len(out)<count:
        part=sock.recv(count-len(out))
        if not part:raise a.AgentError('Source RCON connection closed unexpectedly.')
        out+=part
    return out


def _recv_packet(sock: socket.socket) -> tuple:
    size=struct.unpack('<i',_recv_exact(sock,4))[0]
    if not 10<=size<=1024*1024:raise a.AgentError('Invalid RCON packet length.')
    packet=_recv_exact(sock,size)
    if packet[-2:]!=b'\x00\x00':raise a.AgentError('Invalid RCON packet terminator.')
    request_id,kind=struct.unpack_from('<ii',packet)
    return request_id,kind,packet[8:-2]


def _packet(request_id: int, kind: int, text: str) -> bytes:
    data=struct.pack('<ii',request_id,kind)+text.encode('utf-8')+b'\x00\x00'
    return struct.pack('<i',len(data))+data


def _rcon(data: dict, command: str, timeout: float = 3.0) -> dict:
    if data.get('host')!='127.0.0.1' or not 1024<=int(data['port'])<=65535:raise a.AgentError('Only a managed loopback server is supported.')
    with socket.create_connection(('127.0.0.1',data['port']),timeout=timeout) as s:
        s.settimeout(timeout);s.sendall(_packet(41,3,data['password']))
        for _ in range(6):
            rid,kind,body=_recv_packet(s)
            if rid==-1:raise a.AgentError('RCON authentication failed.')
            if kind==2 and rid==41:break
        else:raise a.AgentError('No RCON authentication response.')
        s.sendall(_packet(42,2,command));s.sendall(_packet(43,0,''))
        parts=[];total=0;complete=False
        while total<512*1024:
            try:rid,kind,body=_recv_packet(s)
            except (socket.timeout, a.AgentError):break
            if rid==43:complete=True;break
            if rid==42:parts.append(body);total+=len(body)
        return {'response':b''.join(parts).decode(errors='replace'),'response_complete':complete}


def start_server(name: str, map_name: str, port: int = 28015, max_players: int = 8) -> dict:
    """Start a private loopback-only, insecure developer server for a compiled managed mod. No public listing or firewall changes."""
    root,_=a.project(name);game=a.game_path(name);a.slug(map_name)
    if not 1024<=int(port)<=65000 or not 1<=int(max_players)<=32:raise a.AgentError('Use port 1024–65000 and 1–32 players.')
    if not (game/'bin/linux64/server.so').is_file():raise a.AgentError('Compile the game/server target first.')
    if not a.contained(game,'maps/'+map_name+'.bsp').is_file():raise a.AgentError('Compile the project map first.')
    metadata=session_path(name)
    with a.lock(root/'.source-agent/server.lock'):
        if metadata.exists() and alive(json.loads(metadata.read_text())):raise a.AgentError('This project already has a managed server; stop it first.')
        for kind in (socket.SOCK_STREAM,socket.SOCK_DGRAM):
            with socket.socket(socket.AF_INET,kind) as s:
                try:s.bind(('127.0.0.1',int(port)))
                except OSError as exc:raise a.AgentError('Requested loopback port is already in use.') from exc
        sid=uuid.uuid4().hex;runtime=Path(a.cfg().get('server_runtime_root',a.cfg()['runtime_root']));folder=metadata.parent/sid
        folder.mkdir(mode=0o700)
        proxy=compiler_game(name,folder/'game',False)
        tree=parse_kv((proxy/'gameinfo.txt').read_text());fs=val(val(tree,'GameInfo'),'FileSystem');search=val(fs,'SearchPaths')
        search.insert(0,['game+mod+mod_write+game_write',str(proxy)])
        setval(search,'default_write_path',str(proxy))
        # SDK modules link unsuffixed libraries; dedicated depots ship _srv names.
        # Keep compatibility links private to this session, never modify Steam depots.
        libs=folder/'lib';libs.mkdir()
        for library in (runtime/'bin/linux64').glob('*_srv.so'):
            (libs/library.name.replace('_srv.so','.so')).symlink_to(library)
        config = a.cfg()
        candidates = [Path(config['steamclient_path'])] if config.get('steamclient_path') else []
        candidates += [a.APP/'toolchain/steamcmd/linux64/steamclient.so',
                       Path(config['steam_root'])/'ubuntu12_64/steamclient.so',
                       Path(config['steam_root'])/'linux64/steamclient.so',
                       runtime/'bin/linux64/steamclient.so']
        steamclient = next((p for p in candidates if p.is_file()), None)
        if steamclient: (libs/'steamclient.so').symlink_to(steamclient)
        modbin=proxy/'bin/linux64';modbin.mkdir(parents=True)
        for module in (game/'bin/linux64').glob('*.so'):
            (modbin/module.name).symlink_to(module)
        (modbin/'server_srv.so').symlink_to(game/'bin/linux64/server.so')
        setval(search,'gamebin',str(proxy/'bin'))
        (proxy/'gameinfo.txt').write_text(dump_kv(tree));(proxy/'cfg').mkdir()
        password=secrets.token_urlsafe(32)
        cfg=proxy/'cfg/source_agent_server.cfg'
        cfg.write_text('hostname "Source SDK Agent Development"\nsv_lan 1\ntv_enable 0\nsv_cheats 1\nsv_hibernate_when_empty 0\nrcon_password "'+password+'"\n')
        cfg.chmod(0o600)
        env={**os.environ,'LD_LIBRARY_PATH':str(libs)+':'+str(runtime/'bin/linux64'),'SteamAppId':'243750','SteamGameId':'243750'}
        cmd=[str(runtime/'srcds_linux64'),'-console','-insecure','-nomaster','-norestart','-ip','127.0.0.1','-port',str(port),'-game',str(proxy),'+sv_lan','1','+tv_enable','0','+maxplayers',str(max_players),'+map',map_name,'+exec','source_agent_server.cfg']
        log=folder/'server.log'
        with log.open('wb') as out:
            process=subprocess.Popen(cmd,cwd=runtime,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=subprocess.STDOUT,start_new_session=True)
        data={'session_id':sid,'project':name,'pid':process.pid,'process_start':a.proc_start(process.pid),'host':'127.0.0.1','port':port,'password':password,'map':map_name,'log':str(log),'game_proxy':str(proxy),'started':time.time()}
        a.atomic_json(metadata,data);metadata.chmod(0o600)
    return {'session_id':sid,'pid':process.pid,'host':'127.0.0.1','port':port,'map':map_name,'started':True,'ready':False,'note':'Call server_status for map-load and RCON readiness. This is not a visual playtest.'}


def server_status(name: str, lines: int = 50) -> dict:
    """Check owned process identity, RCON readiness, current map and a redacted bounded server log."""
    data=load_session(name);running=alive(data);response=None;error=None
    if running:
        try:response=_rcon(data,'status',1.5)
        except (OSError,a.AgentError) as exc:error=str(exc)
    path=Path(data['log']);text=''
    if path.exists():
        with path.open('rb') as f:
            f.seek(max(0,path.stat().st_size-50000));text='\n'.join(f.read().decode(errors='replace').splitlines()[-max(1,min(lines,200)):])
    text=text.replace(data['password'],'<redacted>')
    return {'session_id':data['session_id'],'running':running,'ready':bool(response and 'map' in response['response'].lower()),'host':'127.0.0.1','port':data['port'],'status':response,'rcon_error':error,'log_tail':text}


def console_command(name: str, command: str) -> dict:
    """Send a Source console command to this tool's own local developer server (never to another server)."""
    if not isinstance(command,str) or not command.strip() or len(command.encode())>3500 or any(x in command for x in ('\x00','\r','\n')):raise a.AgentError('Use a nonempty single-line console command, at most 3500 bytes.')
    data=load_session(name)
    if not alive(data):raise a.AgentError('The managed server is not running.')
    result=_rcon(data,command)
    result['response']=result['response'].replace(data['password'],'<redacted>')
    return result


def stop_server(name: str) -> dict:
    """Stop only this project's exact managed server process, with PID-reuse protection."""
    root,_=a.project(name)
    with a.lock(root/'.source-agent/server.lock'):
        data=load_session(name)
        if not alive(data):return {'stopped':True,'was_running':False}
        with contextlib.suppress(OSError,a.AgentError):_rcon(data,'quit',1)
        until=time.monotonic()+4
        while alive(data) and time.monotonic()<until:time.sleep(.1)
        if alive(data):os.killpg(data['pid'],signal.SIGTERM)
        until=time.monotonic()+3
        while alive(data) and time.monotonic()<until:time.sleep(.1)
        if alive(data):os.killpg(data['pid'],signal.SIGKILL)
        data['stopped']=time.time();a.atomic_json(session_path(name),data);session_path(name).chmod(0o600)
    return {'stopped':not alive(data),'session_id':data['session_id']}


def smoke_test(name: str, map_name: str, port: int = 28015, timeout_seconds: int = 45) -> dict:
    """Launch a local server, assert it loads the requested map and answers RCON, then always stop it."""
    if not 5<=int(timeout_seconds)<=120:raise a.AgentError('Timeout must be 5–120 seconds.')
    start_server(name,map_name,port);end=time.monotonic()+timeout_seconds;result={}
    try:
        while time.monotonic()<end:
            result=server_status(name,30)
            if not result['running']:break
            if result['ready']:
                body=result['status']['response'];matched=bool(re.search(r'\bmap\s*:\s*'+re.escape(map_name)+r'\b',body))
                result={'passed':matched,'map':map_name,'rcon_status':body,'session_id':result['session_id'],'scope':'Dedicated-server loading and RCON only; not visual/gameplay QA.'}
                break
            time.sleep(.5)
        else:result={'passed':False,'error':'Timed out waiting for map/RCON readiness.','last_status':result}
        if 'passed' not in result:result={'passed':False,'last_status':result}
    finally:result['cleanup']=stop_server(name)
    root,_=a.project(name);report=root/'.source-agent/verification'/('smoke-'+str(time.time_ns())+'.json');a.atomic_json(report,result)
    return {**result,'report':str(report)}


def capabilities() -> dict:
    """Report implemented versus installed/tested Source capabilities without implying private engine-source access."""
    c=a.cfg();content=c.get('map_tools',{});assets=c.get('asset_tools',{});editors=c.get('editor_tools',{})
    def ready(d,k):return bool(d.get(k) and Path(d[k]).is_file())
    report=a.APP/'verification.json'
    return {'version':a.VERSION,'templates':['hl2mp','tf'],'cpp_targets':['game','client','server','launcher','shaders','plugin'],
            'map_authoring':['VMF source','sealed-room generation','structured cuboid brushes','entity keyvalues','entity I/O','entity removal','raw displacement source edits'],
            'map_compile':{k:ready(content,k) for k in ('vbsp','vvis','vrad')},
            'assets':{'vtf_mipmapped_rgba':True,'vmt_materials_and_proxies':True,'pcm_wav':bool(shutil.which('ffmpeg')),'studiomdl':ready(assets,'studiomdl'),'vpk_pack_and_inspect':True},
            'workflow':['build-model-map-test-package pipeline'],
            'runtime':['private dedicated server','authenticated loopback RCON','map-load smoke test','server logs','Steam client launch request'],
            'editors':{k:ready(editors,k) for k in ('hammer','hlmv','faceposer')},
            'verification':json.loads(report.read_text()) if report.is_file() else {},
            'limits':['Public Source SDK game code, not Valve private engine internals.','Windows C++ builds require a separately configured Windows/MSVC environment.','Singleplayer branch is not configured.','A build or server smoke test does not certify visual quality, gameplay, or arbitrary assets.']}


def discover_toolchain(apply: bool = False) -> dict:
    """Find compiler/editor executables only in known Source tool and Steam depot directories; optionally save their paths."""
    c=a.cfg();roots=[a.APP/'toolchain',Path(c['steam_root'])/'steamapps/content/app_243750',Path(c['runtime_root'])]
    names={'vbsp':['vbsp++','vbspplusplus.exe','vbsp.exe'],'vvis':['vvis++','vvisplusplus.exe','vvis.exe'],'vrad':['vrad++','vradplusplus.exe','vrad.exe'],'studiomdl':['studiomdl++','studiomdlplusplus.exe','studiomdl.exe'],'vtex':['vtex.exe'],'hammer':['hammerplusplus.exe','hammer.exe'],'hlmv':['hlmv.exe'],'faceposer':['hlfaceposer.exe']}
    results={}
    for tool,candidates in names.items():
        matches=[]
        for base in roots:
            if base.exists():
                for filename in candidates:
                    matches.extend(p for p in base.rglob(filename) if p.is_file() and not p.is_symlink())
        if matches:
            # Prefer Valve stock tools for SDK compatibility unless explicitly configured otherwise.
            matches.sort(key=lambda p:(p.name!=candidates[-1],len(str(p))))
            results[tool]=str(matches[0])
    if apply:
        backup=a.CONFIG.with_suffix('.before-tool-discovery-'+str(time.time_ns())+'.json');shutil.copy2(a.CONFIG,backup)
        for tool,path in results.items():
            group='map_tools' if tool in ('vbsp','vvis','vrad') else 'editor_tools' if tool in ('hammer','hlmv','faceposer') else 'asset_tools'
            c.setdefault(group,{})[tool]=path
        a.atomic_json(a.CONFIG,c)
    return {'found':results,'saved':apply,'note':'File presence is not a successful compiler/editor execution test.'}

TOOLS={fn.__name__:fn for fn in (search_source,start_server,server_status,console_command,stop_server,smoke_test,capabilities,discover_toolchain)}
