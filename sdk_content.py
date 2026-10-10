"""Source content creation, compiler staging, diagnostics, and verified asset output."""
from __future__ import annotations
import collections
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import time
import uuid
import wave
import zipfile
import agent as a

# A VMF is an ordered KeyValues tree: duplicate keys (entity outputs) must survive edits.
def parse_kv(text: str) -> list:
    if len(text) > 16 * 1024 * 1024:
        raise a.AgentError('KeyValues input exceeds 16 MiB.')
    tokens = []
    i = 0
    while i < len(text):
        if text[i].isspace(): i += 1; continue
        if text.startswith('//', i):
            end = text.find('\n', i); i = len(text) if end < 0 else end + 1; continue
        if text[i] in '{}': tokens.append(text[i]); i += 1; continue
        if text[i] == '"':
            i += 1; value = ''
            while i < len(text) and text[i] != '"':
                if text[i] == '\\' and i + 1 < len(text) and text[i+1] in ('"', '\\'):
                    i += 1
                value += text[i]; i += 1
            if i == len(text): raise a.AgentError('Unterminated KeyValues string.')
            tokens.append(('s', value)); i += 1
        else:
            end = i
            while end < len(text) and not text[end].isspace() and text[end] not in '{}': end += 1
            tokens.append(('s', text[i:end])); i = end
    cursor = 0
    def block(nested=False, depth=0):
        nonlocal cursor
        if depth > 64: raise a.AgentError('KeyValues nesting exceeds 64 levels.')
        out = []
        while cursor < len(tokens):
            token = tokens[cursor]; cursor += 1
            if token == '}':
                if not nested: raise a.AgentError('Unexpected closing brace.')
                return out
            if not isinstance(token, tuple) or cursor == len(tokens): raise a.AgentError('Expected a KeyValues pair.')
            value = tokens[cursor]; cursor += 1
            if value == '{': value = block(True, depth + 1)
            elif isinstance(value, tuple): value = value[1]
            else: raise a.AgentError('Expected a value or block.')
            out.append([token[1], value])
        if nested: raise a.AgentError('Unclosed KeyValues block.')
        return out
    return block()

def quote(value: str) -> str:
    text = str(value)
    if '\x00' in text or '\n' in text or '\r' in text: raise a.AgentError('KeyValues values must be single-line text.')
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'

def dump_kv(tree: list, depth: int = 0) -> str:
    output = ''
    for key, value in tree:
        indent = '\t' * depth
        if isinstance(value, list): output += indent + quote(key) + '\n' + indent + '{\n' + dump_kv(value, depth+1) + indent + '}\n'
        else: output += indent + quote(key) + ' ' + quote(value) + '\n'
    return output

def val(tree: list, key: str, default=None):
    return next((v for k,v in tree if k.lower() == key.lower()), default)

def setval(tree: list, key: str, value):
    for pair in tree:
        if pair[0].lower() == key.lower(): pair[1] = value; return
    tree.append([key,value])

def _map(name: str, map_name: str):
    root,_ = a.project(name); a.slug(map_name)
    path = a.contained(root, 'mapsrc/' + map_name + '.vmf')
    return root, path, parse_kv(path.read_text())

def inspect_map(name: str, map_name: str) -> dict:
    """Inspect VMF entities, brushes, connections, unique IDs, and spawn points; not a leak test."""
    root,path,tree = _map(name,map_name)
    counts=collections.Counter(); ids=[]; entities=[]
    def walk(items):
        for k,v in items:
            if k.lower() == 'id' and isinstance(v,str): ids.append(v)
            if isinstance(v,list): counts[k.lower()] += 1; walk(v)
    walk(tree)
    for key,fields in tree:
        if key.lower()=='entity':
            entities.append({'id':val(fields,'id'),'classname':val(fields,'classname'), 'origin':val(fields,'origin'), 'targetname':val(fields,'targetname'), 'connections':val(fields,'connections',[])})
    duplicate=[k for k,n in collections.Counter(ids).items() if n > 1]
    warnings=[]
    if duplicate: warnings.append('Duplicate IDs: '+', '.join(duplicate[:20]))
    if not any((e['classname'] or '').startswith('info_player') for e in entities): warnings.append('No player spawn point.')
    return {'path':str(path),'sha256':a.sha(path.read_bytes()),'brushes':counts['solid'],'sides':counts['side'], 'entities':entities[:500], 'entity_count':len(entities),'warnings':warnings,'leak_test':'Requires VBSP compilation.'}

def edit_map_entity(name: str, map_name: str, entity_id: str, properties: dict, expected_sha256: str, connections: list | None = None) -> dict:
    """Add an entity (empty entity_id) or update one, preserving geometry and duplicate I/O outputs."""
    root,path,tree = _map(name,map_name)
    if a.sha(path.read_bytes()) != expected_sha256: raise a.AgentError('Map changed; read its current hash before editing.')
    if not isinstance(properties,dict) or len(properties)>100: raise a.AgentError('At most 100 entity properties are accepted.')
    if any(str(key).lower() == 'id' for key in properties): raise a.AgentError('IDs are assigned by the editor, not through properties.')
    fields=None
    if entity_id:
        fields=next((v for k,v in tree if k=='entity' and val(v,'id')==str(entity_id)),None)
        if fields is None: raise a.AgentError('Entity ID not found.')
    else:
        existing=[int(x) for x in re.findall(r'"id"\s+"(\d+)"',path.read_text())]
        fields=[['id',str(max(existing,default=0)+1)]]; tree.append(['entity',fields])
    for k,v in properties.items(): quote(k); quote(v); setval(fields,str(k),str(v))
    if not val(fields,'classname'): raise a.AgentError('Entity requires a classname.')
    if connections is not None:
        if len(connections)>200: raise a.AgentError('At most 200 outputs are accepted.')
        pairs=[]
        for c in connections:
            if set(c) != {'output','target','input','parameter','delay','times'}: raise a.AgentError('Output requires output,target,input,parameter,delay,times.')
            if any(',' in str(c[x]) for x in ('target','input','parameter')): raise a.AgentError('Comma is reserved by the output format.')
            pairs.append([str(c['output']), ','.join(str(c[x]) for x in ('target','input','parameter','delay','times'))])
        setval(fields,'connections',pairs)
    return a.write_text(name,str(path.relative_to(root)),dump_kv(tree),expected_sha256)

def binary_write(name: str, relative: str, data: bytes, expected_sha256: str = '') -> dict:
    root,_=a.project(name); dest=a.contained(root,relative)
    if len(data)>128*1024*1024: raise a.AgentError('Asset exceeds 128 MiB.')
    with a.lock(root/'.source-agent/edit.lock'):
        backup=None
        if dest.exists():
            if not expected_sha256 or a.sha(dest.read_bytes())!=expected_sha256: raise a.AgentError('Asset exists; supply its current SHA-256.')
            backup=root/'.source-agent/backups'/(str(time.time_ns())+'_'+dest.name)
            backup.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(dest,backup)
        elif expected_sha256: raise a.AgentError('Expected existing asset is missing.')
        dest.parent.mkdir(parents=True,exist_ok=True)
        tmp=dest.with_name('.'+dest.name+'.'+uuid.uuid4().hex+'.tmp'); tmp.write_bytes(data); tmp.replace(dest)
    return {'path':str(dest),'bytes':len(data),'sha256':a.sha(data),'backup':str(backup) if backup else None}

def asset_path(value: str) -> str:
    if not isinstance(value,str) or not re.fullmatch(r'[a-zA-Z0-9_/-]{1,160}',value) or any(p in ('','..','.') for p in value.split('/')):
        raise a.AgentError('Use a relative asset name containing letters, numbers, underscores, hyphens and slash-separated folders.')
    return value

def create_material(name: str, material_name: str, shader: str = 'LightmappedGeneric', parameters: dict | None = None, expected_sha256: str = '') -> dict:
    """Create a VMT for any named Source shader, including material parameters and nested proxies."""
    asset_path(material_name)
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',shader): raise a.AgentError('Invalid shader name.')
    def pairs(d,depth=0):
        if depth>8 or not isinstance(d,dict) or len(d)>100: raise a.AgentError('Invalid material parameter structure.')
        return [[str(k), pairs(v,depth+1) if isinstance(v,dict) else str(v)] for k,v in d.items()]
    root,_=a.project(name); game=a.game_path(name)
    return a.write_text(name,str((game/'materials'/(material_name+'.vmt')).relative_to(root)),dump_kv([[shader,pairs(parameters or {})]]),expected_sha256)

def compile_texture(name: str, source: str, texture_name: str, expected_sha256: str = '') -> dict:
    """Convert a project PNG/TGA/JPEG/BMP to a mipmapped Source VTF 7.2 RGBA8888 texture (uncompressed)."""
    from PIL import Image, ImageStat
    root,_=a.project(name); src=a.contained(root,source); asset_path(texture_name)
    if src.suffix.lower() not in ('.png','.tga','.jpg','.jpeg','.bmp'): raise a.AgentError('Supported texture inputs: PNG,TGA,JPEG,BMP.')
    with Image.open(src) as im:
        if max(im.size)>4096 or min(im.size)<1: raise a.AgentError('Texture dimensions must be 1–4096.')
        w,h=im.size
        if w&(w-1) or h&(h-1): raise a.AgentError('Source texture dimensions must be powers of two; resize the source explicitly.')
        base=im.convert('RGBA')
    mips=[base]
    while mips[-1].width>1 or mips[-1].height>1:
        last=mips[-1]; mips.append(last.resize((max(1,last.width//2),max(1,last.height//2)),Image.Resampling.LANCZOS))
    flags=0x2000 if base.getchannel('A').getextrema()[0]<255 else 0
    header=bytearray(80)
    struct.pack_into('<4sIIIHHIHH',header,0,b'VTF\0',7,2,80,w,h,flags,1,0)
    means=ImageStat.Stat(base.convert('RGB')).mean
    struct.pack_into('<3f',header,32,*(x/255 for x in means))
    struct.pack_into('<fIBIBBH',header,48,1.0,0,len(mips),0xffffffff,0,0,1)
    data=bytes(header)+b''.join(im.tobytes() for im in reversed(mips))
    dest=a.game_path(name)/'materials'/(texture_name+'.vtf')
    return {**binary_write(name,str(dest.relative_to(root)),data,expected_sha256),'width':w,'height':h,'mipmaps':len(mips),'format':'VTF 7.2 RGBA8888','compressed':False}

def convert_sound(name: str, source: str, sound_name: str, mono: bool = True, expected_sha256: str = '') -> dict:
    """Convert project audio to Source-friendly 44.1 kHz, signed 16-bit PCM WAV through FFmpeg."""
    root,_=a.project(name); src=a.contained(root,source); asset_path(sound_name)
    if src.suffix.lower() not in ('.wav','.mp3','.ogg','.flac','.aiff'): raise a.AgentError('Unsupported audio input.')
    if not shutil.which('ffmpeg'): raise a.AgentError('FFmpeg is not installed.')
    result=subprocess.run(['ffmpeg','-nostdin','-v','error','-protocol_whitelist','file,pipe','-i',str(src),'-t','600','-vn','-ar','44100','-ac','1' if mono else '2','-c:a','pcm_s16le','-f','wav','pipe:1'],capture_output=True,timeout=120)
    if result.returncode: raise a.AgentError(result.stderr.decode(errors='replace')[-2000:])
    # A streamed WAV has sentinel length fields. Rewrite a seekable canonical header.
    with wave.open(io.BytesIO(result.stdout),'rb') as reader:
        params=reader.getparams(); frames=reader.readframes(44100*601)
    output=io.BytesIO()
    with wave.open(output,'wb') as writer: writer.setparams(params._replace(nframes=len(frames)//(params.nchannels*params.sampwidth))); writer.writeframes(frames)
    dest=a.game_path(name)/'sound'/(sound_name+'.wav')
    return binary_write(name,str(dest.relative_to(root)),output.getvalue(),expected_sha256)

def import_asset(name: str, source: str, destination: str, license_note: str, expected_sha256: str = '') -> dict:
    """Copy an asset staged inside this project into its game directory and record its provenance."""
    root,_=a.project(name); src=a.contained(root,source); game=a.game_path(name)
    dst=a.contained(game,destination)
    allowed={'.png','.tga','.jpg','.jpeg','.bmp','.vtf','.vmt','.mdl','.vvd','.vtx','.phy','.ani','.wav','.mp3','.ogg','.pcf','.vcd','.dmx','.smd','.vta','.qc','.qci'}
    if src.suffix.lower() not in allowed or dst.suffix.lower()!=src.suffix.lower(): raise a.AgentError('Unsupported asset format or mismatched extension.')
    if not license_note.strip() or len(license_note)>1000: raise a.AgentError('Supply a brief ownership/license note.')
    result=binary_write(name,str(dst.relative_to(root)),src.read_bytes(),expected_sha256)
    manifest=root/'.source-agent/assets.json'
    with a.lock(root/'.source-agent/assets.lock'):
        data=json.loads(manifest.read_text()) if manifest.exists() else {}
        data[str(dst.relative_to(game))]={'source':source,'sha256':result['sha256'],'license_note':license_note,'time':time.time()}
        a.atomic_json(manifest,data)
    return result

def inspect_bsp(name: str, map_name: str) -> dict:
    """Validate BSP header/lump bounds and summarize compiled geometry, entities, lighting and embedded files."""
    a.slug(map_name); path=a.contained(a.game_path(name),'maps/'+map_name+'.bsp'); data=path.read_bytes()
    if len(data)<1036 or data[:4]!=b'VBSP': raise a.AgentError('Invalid Source BSP header.')
    version=struct.unpack_from('<I',data,4)[0]; lumps=[]
    for i in range(64):
        off,size,ver,code=struct.unpack_from('<4I',data,8+16*i)
        if size and (off<1036 or off+size>len(data)): raise a.AgentError(f'Lump {i} lies outside the BSP.')
        lumps.append({'index':i,'offset':off,'bytes':size,'version':ver,'compression_code':code})
    entities=data[lumps[0]['offset']:lumps[0]['offset']+lumps[0]['bytes']].decode(errors='replace')
    embedded=[]; pak=lumps[40]
    if pak['bytes']:
        try:
            with zipfile.ZipFile(io.BytesIO(data[pak['offset']:pak['offset']+pak['bytes']])) as z: embedded=z.namelist()
        except zipfile.BadZipFile: embedded=['<invalid embedded ZIP>']
    return {'path':str(path),'sha256':a.sha(data),'bsp_version':version,'bytes':len(data),'entity_count':entities.count('"classname"'),'entity_text':entities[:24000],'lighting_bytes':lumps[8]['bytes']+lumps[53]['bytes'],'visibility_bytes':lumps[4]['bytes'],'embedded_files':embedded[:300],'nonempty_lumps':[l for l in lumps if l['bytes']]}

def diagnose_job(job_id: str) -> dict:
    """Extract actionable compiler errors, leak messages and missing assets from a bounded job log."""
    data=a.get_job(job_id,300); text=data.get('log_tail',''); matches=[]
    for line in text.splitlines():
        if re.search(r'error:|fatal error|\bleaked\b|could not|cannot |failed|not found|missing|warning:',line,re.I): matches.append(line[:1500])
    return {'job_id':job_id,'state':data['state'],'error':data.get('error'),'diagnostics':matches[-60:],'log_tail_only':True}

def compiler_environment() -> dict:
    c=a.cfg(); prefix=Path(c.get('wine_prefix',str(Path(c['workspace_root'])/'.wine-sdk-tools')))
    return {**os.environ,'WINEPREFIX':str(prefix),'WINEDEBUG':'-all','WINEDLLOVERRIDES':'mscoree,mshtml=','DISPLAY':os.environ.get('DISPLAY',':0')}

def windows_path(path: Path) -> str:
    # Dedicated Wine prefix keeps its standard Z: mapping to the host root.
    return 'Z:' + str(path.resolve()).replace('/','\\')

def compiler_game(name: str, directory: Path, windows: bool = True) -> Path:
    game=a.game_path(name); config=a.cfg(); mounts=config.get('content_mounts',{}); runtime=Path(mounts.get('sdk',config['runtime_root']))
    if mounts.get('projects'):
        _,meta=a.project(name);game=Path(mounts['projects'])/name/'game'/('mod_'+meta['template'])
    directory.mkdir(parents=True,exist_ok=True)
    # Parse before substitution: unquoted Source tokens become paths containing spaces.
    # Rewriting raw text first would split "Source SDK Base ..." into bogus keys.
    tree=parse_kv((game/'gameinfo.txt').read_text())
    convert=windows_path if windows else lambda p:str(p.absolute())
    separator='\\' if windows else '/'
    replacements={'|appid_243750|':convert(runtime)+separator,
                  '|gameinfo_path|':convert(game)+separator,
                  '|all_source_engine_paths|':convert(runtime)+separator}
    tfroot=mounts.get('tf2',config.get('tf_runtime_root'))
    if tfroot: replacements['|appid_440|']=convert(Path(tfroot))+separator
    def rewrite(items):
        for pair in items:
            if isinstance(pair[1],list):rewrite(pair[1])
            else:
                for token,value in replacements.items():pair[1]=pair[1].replace(token,value)
    rewrite(tree)
    paths=val(val(val(tree,'GameInfo'),'FileSystem'),'SearchPaths')
    paths.insert(0,['game',convert(game)])
    (directory/'gameinfo.txt').write_text(dump_kv(tree))
    return directory

def compile_model(name: str, source: str) -> dict:
    """Compile a project QC/SMD/DMX model using configured StudioMDL and stage outputs before installation."""
    root,_=a.project(name); qc=a.contained(root,source)
    if qc.suffix.lower()!='.qc' or not qc.is_file(): raise a.AgentError('Model input must be a project QC file.')
    if not Path(a.cfg().get('asset_tools',{}).get('studiomdl','/missing')).is_file(): raise a.AgentError('StudioMDL is not configured.')
    text=qc.read_text()
    match=re.search(r'(?im)^\s*\$modelname\s+"?([^"\r\n]+)',text)
    if not match: raise a.AgentError('QC requires $modelname.')
    target=match[1].strip().replace('\\','/')
    a.contained(a.game_path(name)/'models',target)
    if not target.endswith('.mdl'): raise a.AgentError('$modelname must end in .mdl.')
    # Source import paths must not escape the project; no absolute $cd/$include references.
    for token in re.findall(r'"([^"\n]+)"',text):
        if token.startswith(('/', '\\')) or re.match(r'^[A-Za-z]:',token) or '..' in token.replace('\\','/').split('/'):
            raise a.AgentError('QC contains an absolute or parent-relative path; use project-local model sources.')
    return a.submit(name,'compile_model',{'source':source,'model_name':target})

def content_job(data: dict, out, execute) -> list:
    name=data['project']; root,_=a.project(name); c=a.cfg(); jid=data['job_id']
    staging=root/'.source-agent/content-builds'/jid; staging.mkdir(parents=True)
    params=data['parameters']; artifacts=[]
    if data['operation']=='compile_map':
        map_name=params['map_name']; vmf=staging/(map_name+'.vmf')
        shutil.copy2(a.contained(root,'mapsrc/'+map_name+'.vmf'),vmf)
        for tool in ('vbsp','vvis','vrad'):
            exe=Path(c['map_tools'][tool]); is_windows=exe.suffix.lower()=='.exe'
            game=compiler_game(name,staging/'compiler-game',is_windows)
            target=vmf if tool=='vbsp' else vmf.with_suffix('.bsp')
            flags=['-threads',str(c.get('jobs',4))] if tool in ('vvis','vrad') else []
            if params['quality']=='fast' and tool in ('vvis','vrad'):flags+=['-fast']
            if tool=='vrad':flags+=['-both']
            env=compiler_environment() if is_windows else dict(os.environ)
            if is_windows:
                flags+=['-game',windows_path(game),windows_path(target)]
                args=['wine',str(exe),*flags]
                if shutil.which('xvfb-run'):args=['xvfb-run','-a',*args]
            else:
                env['LD_LIBRARY_PATH']=str(exe.parent) if exe.name.endswith('++') else str(exe.parent)+':'+str(Path(c['runtime_root'])/'bin/linux64')
                args=[str(exe),*flags,'-game',str(game),str(target)]
            execute(args,out,exe.parent,env,1800)
        bsp=vmf.with_suffix('.bsp')
        if not bsp.is_file() or bsp.read_bytes()[:4]!=b'VBSP':raise a.AgentError('Compiler produced no valid BSP.')
        text=(a.jobs_root()/(jid+'.log')).read_text(errors='replace')
        if re.search(r'\*+\s*leaked\s*\*+',text,re.I):raise a.AgentError('Map leaked; BSP was not installed.')
        destination=a.game_path(name)/'maps'/bsp.name
        previous=a.sha(destination.read_bytes()) if destination.exists() else ''
        artifacts.append(binary_write(name,str(destination.relative_to(root)),bsp.read_bytes(),previous))
    elif data['operation']=='compile_model':
        exe=Path(c['asset_tools']['studiomdl']); is_windows=exe.suffix.lower()=='.exe'
        game=compiler_game(name,staging/'compiler-game',is_windows)
        # Add staging as first writable mod so the compiler cannot replace existing model files.
        tree=parse_kv((game/'gameinfo.txt').read_text()); fs=val(val(tree,'GameInfo'),'FileSystem'); search=val(fs,'SearchPaths')
        loc=windows_path(game) if is_windows else str(game)
        search.insert(0,['game+mod+mod_write+game_write',loc]); setval(search,'default_write_path',loc)
        (game/'models').mkdir(exist_ok=True); (game/'gameinfo.txt').write_text(dump_kv(tree))
        qc=a.contained(root,params['source']); env=compiler_environment() if is_windows else dict(os.environ)
        if is_windows:
            args=['wine',str(exe),'-nop4','-game',windows_path(game),windows_path(qc)]
            if shutil.which('xvfb-run'):args=['xvfb-run','-a',*args]
        else:
            env['LD_LIBRARY_PATH']=str(exe.parent) if exe.name.endswith('++') else str(exe.parent)+':'+str(Path(c['runtime_root'])/'bin/linux64'); args=[str(exe),'-nop4','-game',str(game),str(qc)]
        execute(args,out,qc.parent,env,1200)
        mdl=game/'models'/params['model_name']
        if not mdl.exists() or mdl.read_bytes()[:4]!=b'IDST':raise a.AgentError('StudioMDL did not produce the expected valid MDL in staging.')
        for p in (game/'models').rglob('*'):
            if p.is_file() and not p.is_symlink():
                dest=a.game_path(name)/'models'/p.relative_to(game/'models'); previous=a.sha(dest.read_bytes()) if dest.exists() else ''
                artifacts.append(binary_write(name,str(dest.relative_to(root)),p.read_bytes(),previous))
    else:raise a.AgentError('Unknown content build operation.')
    return artifacts

TOOLS={fn.__name__:fn for fn in (inspect_map,edit_map_entity,create_material,compile_texture,convert_sound,import_asset,inspect_bsp,diagnose_job,compile_model)}
