"""Bounded Source VPK v1/v2 inspection and self-contained VPK v1 creation for project-owned assets."""
from __future__ import annotations
import collections
import io
import json
from pathlib import Path
import struct
import time
import zlib
import agent as a
from sdk_content import binary_write


def parse_vpk(data: bytes) -> list:
    if len(data)<12:raise a.AgentError('Truncated VPK header.')
    magic,version,size=struct.unpack_from('<3I',data)
    if magic!=0x55aa1234 or version not in (1,2):raise a.AgentError('Unsupported VPK header/version.')
    header=12 if version==1 else 28
    if header+size>len(data):raise a.AgentError('VPK directory tree exceeds file size.')
    pos=header;end=header+size;entries=[]
    def string():
        nonlocal pos
        stop=data.find(b'\0',pos,end)
        if stop<0:raise a.AgentError('Unterminated VPK tree string.')
        result=data[pos:stop].decode('utf-8',errors='strict');pos=stop+1;return result
    while True:
        extension=string()
        if not extension:break
        while True:
            folder=string()
            if not folder:break
            while True:
                filename=string()
                if not filename:break
                if pos+18>end:raise a.AgentError('Truncated VPK entry.')
                crc,preload,index,offset,length,terminator=struct.unpack_from('<IHHIIH',data,pos);pos+=18
                if terminator!=0xffff or pos+preload>end:raise a.AgentError('Invalid VPK entry.')
                pos+=preload
                if folder != ' ' and (folder.startswith(('/', '\\')) or ':' in folder):
                    raise a.AgentError('Absolute VPK folder path.')
                if any(char in filename for char in ('/', '\\', ':')):
                    raise a.AgentError('Invalid VPK filename.')
                name=('' if folder==' ' else folder+'/')+filename+('' if extension==' ' else '.'+extension)
                if name.startswith('/') or '..' in name.replace('\\','/').split('/'):raise a.AgentError('Unsafe VPK entry path.')
                if index==0x7fff and header+size+offset+length>len(data):raise a.AgentError('Inline VPK data exceeds file size.')
                entries.append({'path':name,'crc32':f'{crc:08x}','bytes':length+preload,'archive_index':index,'data_offset':offset,'preload_bytes':preload})
                if len(entries)>300000:raise a.AgentError('VPK contains too many entries.')
    return entries


def inspect_vpk(name: str, path: str, prefix: str = '', limit: int = 100) -> dict:
    """Read an owned project VPK directory, not installed Valve depots; validates inline offsets and paths."""
    root,_=a.project(name);p=a.contained(root,path)
    if p.suffix.lower()!='.vpk' or p.stat().st_size>512*1024*1024:raise a.AgentError('Expected a project VPK no larger than 512 MiB.')
    entries=parse_vpk(p.read_bytes());filtered=[e for e in entries if e['path'].startswith(prefix)]
    limit=max(1,min(limit,500))
    return {'entries':filtered[:limit],'total_entries':len(entries),'matched':len(filtered),'truncated':len(filtered)>limit}


def pack_vpk(name: str, source_directory: str, package_name: str, license_note: str, expected_sha256: str = '') -> dict:
    """Package a project asset directory into a loadable custom VPK and record it as an authored archive."""
    root,_=a.project(name);base=a.contained(root,source_directory);a.slug(package_name)
    if not base.is_dir() or not license_note.strip():raise a.AgentError('Supply a project asset directory and ownership/license note.')
    allowed={'.vmt','.vtf','.mdl','.vtx','.vvd','.phy','.ani','.wav','.mp3','.pcf','.vcd','.nut','.txt','.res','.cfg'}
    tree={};payload=bytearray();file_count=0
    for p in sorted(base.rglob('*')):
        if p.is_symlink():raise a.AgentError('Asset package must not contain symlinks.')
        if not p.is_file():continue
        a.contained(root,str(p.relative_to(root)))
        rel=p.relative_to(base)
        if p.suffix.lower() not in allowed:raise a.AgentError('Unsupported package entry: '+str(rel))
        if rel.parts[0] not in ('materials','models','sound','scripts','particles','resource','cfg','scenes'):raise a.AgentError('Package entries must be in Source content folders, not engine binaries.')
        data=p.read_bytes()
        if len(payload)+len(data)>128*1024*1024:raise a.AgentError('Package exceeds 128 MiB.')
        ext=p.suffix[1:];folder=str(rel.parent).replace('\\','/');stem=p.stem
        if '\0' in str(rel):raise a.AgentError('Invalid asset path.')
        tree.setdefault(ext,{}).setdefault(folder,[]).append((stem,zlib.crc32(data)&0xffffffff,len(payload),len(data)))
        payload.extend(data);file_count+=1
    if not file_count:raise a.AgentError('No assets to package.')
    directory=bytearray()
    def emit(text):directory.extend(text.encode('utf-8')+b'\0')
    for extension,folders in sorted(tree.items()):
        emit(extension)
        for folder,items in sorted(folders.items()):
            emit(folder)
            for stem,crc,offset,length in items:emit(stem);directory.extend(struct.pack('<IHHIIH',crc,0,0x7fff,offset,length,0xffff))
            emit('')
        emit('')
    emit('')
    data=struct.pack('<3I',0x55aa1234,1,len(directory))+directory+payload
    check=parse_vpk(data)
    if len(check)!=file_count:raise a.AgentError('VPK self-validation failed.')
    dest=a.game_path(name)/'custom'/(package_name+'.vpk')
    result=binary_write(name,str(dest.relative_to(root)),bytes(data),expected_sha256)
    manifest=root/'.source-agent/authored-vpks.json'
    with a.lock(root/'.source-agent/assets.lock'):
        items=json.loads(manifest.read_text()) if manifest.exists() else {}
        items[str(dest.relative_to(a.game_path(name)))]={'sha256':result['sha256'],'license_note':license_note,'files':file_count,'created':time.time()}
        a.atomic_json(manifest,items)
    return {**result,'files':file_count,'registered_for_mod_packaging':True}

TOOLS={fn.__name__:fn for fn in (inspect_vpk,pack_vpk)}
