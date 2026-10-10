#!/usr/bin/env python3
"""Install the local CLI/MCP wrapper without administrator or firewall changes."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
from agent import APP, CONFIG, atomic_json

IMAGE = 'registry.gitlab.steamos.cloud/steamrt/sniper/sdk:latest'


def find_steam(home: Path, preferred: Path | None = None):
    candidates = ([preferred] if preferred else []) + [home/'.local/share/Steam', home/'.steam/steam', home/'.var/app/com.valvesoftware.Steam/.local/share/Steam']
    for steam in candidates:
        roots = [steam]
        vdf = steam/'steamapps/libraryfolders.vdf'
        if vdf.is_file():
            roots += [Path(x.replace('\\\\', '\\')) for x in re.findall(r'"path"\s+"([^"\n]+)"', vdf.read_text())]
        for library in roots:
            manifest = library/'steamapps/appmanifest_243750.acf'
            if not manifest.is_file():
                continue
            match = re.search(r'"installdir"\s+"([^"\n]+)"', manifest.read_text())
            if match:
                runtime = library/'steamapps/common'/match[1]
                if (runtime/'hl2_linux64').is_file():
                    return steam.resolve(), runtime.resolve()
    return None


def tool_paths(directory: Path) -> dict:
    """Find only known compiler/editor names; never download or execute discovered files."""
    choices = {'vbsp': ('vbsp++', 'vbsp', 'vbspplusplus.exe', 'vbsp.exe'),
               'vvis': ('vvis++', 'vvis', 'vvisplusplus.exe', 'vvis.exe'),
               'vrad': ('vrad++', 'vrad', 'vradplusplus.exe', 'vrad.exe'),
               'studiomdl': ('studiomdl++', 'studiomdl', 'studiomdlplusplus.exe', 'studiomdl.exe'),
               'hammer': ('hammerplusplus.exe', 'hammer.exe'), 'hlmv': ('hlmv.exe',), 'faceposer': ('hlfaceposer.exe',)}
    result = {}
    for tool, names in choices.items():
        for filename in names:
            matches = sorted(p for p in directory.rglob(filename) if p.is_file())
            if matches:
                result[tool] = str(matches[0].resolve())
                break
    return result


def local_alias(path: Path, target: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if not path.is_symlink() or path.resolve() != target.resolve():
            raise SystemExit('Refusing to replace an unrelated content alias: ' + str(path))
    else:
        path.symlink_to(target.resolve(), target_is_directory=True)


def main():
    if sys.platform != 'linux' or sys.version_info < (3, 10):
        raise SystemExit('The local host must be Linux with Python 3.10 or newer.')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', help='Existing Valve SDK checkout')
    parser.add_argument('--steam-root', help='Steam client root (not steamapps)')
    parser.add_argument('--runtime', help='Source SDK Base 2013 Multiplayer installation')
    parser.add_argument('--workspace', help='New workspace path; existing workspace is preserved')
    parser.add_argument('--tools-dir', help='Directory containing separately obtained compatible compilers/editors')
    parser.add_argument('--server-runtime', help='Compatible directory containing srcds_linux64 and dedicated libraries')
    parser.add_argument('--image', default=IMAGE, help='Compiler image to resolve to an immutable digest for a new config')
    parser.add_argument('--pull-image', action='store_true', help='Explicitly download the compiler container if needed')
    args = parser.parse_args()
    home = Path.home()
    config = json.loads(CONFIG.read_text()) if CONFIG.is_file() else {}
    resolve = lambda value: Path(value).expanduser().resolve()
    sdk = resolve(args.sdk or config.get('sdk_root', home/'Development/source-sdk-2013'))
    if not (sdk/'src/devtools/bin/vpc').is_file():
        raise SystemExit('Clone ValveSoftware/source-sdk-2013 first, then pass --sdk PATH.')
    preferred = resolve(args.steam_root) if args.steam_root else None
    selected = find_steam(home, preferred)
    if args.runtime:
        runtime = resolve(args.runtime)
        steam = preferred or (selected[0] if selected else runtime.parent.parent.parent)
    elif selected:
        steam, runtime = selected
    elif config.get('runtime_root'):
        steam, runtime = resolve(config['steam_root']), resolve(config['runtime_root'])
    else:
        raise SystemExit('Install Source SDK Base 2013 Multiplayer (app 243750) through Steam first.')
    if not (runtime/'hl2_linux64').is_file():
        raise SystemExit('Selected runtime has no hl2_linux64: ' + str(runtime))
    if args.workspace and config.get('workspace_root') and resolve(args.workspace) != resolve(config['workspace_root']):
        raise SystemExit('Existing workspace differs; use a separate SOURCE_SDK_AGENT_CONFIG instead of moving projects implicitly.')
    if not shutil.which('podman'):
        raise SystemExit('Install rootless Podman before configuring C++ compilation.')
    if args.pull_image:
        subprocess.run(['podman', 'pull', args.image], check=True)
    if not config:
        try:
            digest = subprocess.check_output(['podman', 'image', 'inspect', args.image, '--format', '{{index .RepoDigests 0}}'], text=True).strip()
        except subprocess.CalledProcessError:
            raise SystemExit('Compiler image is not cached. Re-run with --pull-image or pull it with Podman first.')
        if '@sha256:' not in digest:
            raise SystemExit('Compiler image must resolve to an immutable registry digest.')
        workspace = resolve(args.workspace) if args.workspace else steam.parent/'source-sdk-agent/projects'
        workspace.mkdir(parents=True, exist_ok=True)
        config = {'sdk_root': str(sdk), 'steam_root': str(steam), 'runtime_root': str(runtime),
                  'steam_flatpak': '.var/app/com.valvesoftware.Steam' in str(steam), 'workspace_root': str(workspace),
                  'image': digest, 'jobs': min(4, os.cpu_count() or 2), 'memory_gib': 8, 'map_tools': {}, 'asset_tools': {}, 'editor_tools': {}}
    else:
        if args.sdk: config['sdk_root'] = str(sdk)
        if args.runtime: config['runtime_root'] = str(runtime)
        if args.steam_root:
            config['steam_root'] = str(steam)
            config['steam_flatpak'] = '.var/app/com.valvesoftware.Steam' in str(steam)
    if args.server_runtime:
        dedicated = resolve(args.server_runtime)
        if not (dedicated/'srcds_linux64').is_file():
            raise SystemExit('Dedicated runtime has no srcds_linux64.')
        config['server_runtime_root'] = str(dedicated)
    if args.tools_dir:
        directory = resolve(args.tools_dir)
        if not directory.is_dir():
            raise SystemExit('Tool directory does not exist.')
        for tool, path in tool_paths(directory).items():
            group = 'map_tools' if tool in ('vbsp', 'vvis', 'vrad') else 'editor_tools' if tool in ('hammer', 'hlmv', 'faceposer') else 'asset_tools'
            config.setdefault(group, {})[tool] = path
    python = APP/'.venv/bin/python'
    if not python.is_file():
        if shutil.which('uv'):
            subprocess.run(['uv', 'venv', '--python', sys.executable, str(APP/'.venv')], check=True)
        else:
            subprocess.run([sys.executable, '-m', 'venv', str(APP/'.venv')], check=True)
    requirements = APP/'requirements.lock'
    if not requirements.is_file(): requirements = APP/'requirements.txt'
    command = ['uv', 'pip', 'install', '--python', str(python)] if shutil.which('uv') else [str(python), '-m', 'pip', 'install']
    subprocess.run(command + ['-r', str(requirements)], check=True)
    # Short, stable aliases help native compilers handle Steam's space-containing paths.
    mounts = config.setdefault('content_mounts', {})
    for key, target in [('sdk', Path(config['runtime_root'])), ('projects', Path(config['workspace_root']))]:
        alias = home/'.local/share/source-sdk-agent/mounts'/key
        if key not in mounts:
            local_alias(alias, target)
            mounts[key] = str(alias)
    if CONFIG.exists():
        shutil.copy2(CONFIG, CONFIG.with_suffix('.before-install-' + str(time.time_ns()) + '.json'))
    atomic_json(CONFIG, config)
    CONFIG.chmod(0o600)
    bindir = home/'.local/bin'
    bindir.mkdir(parents=True, exist_ok=True)
    for name, entry in [('source-sdk', 'agent.py'), ('source-sdk-mcp', 'server.py')]:
        launcher = bindir/name
        text = '#!/bin/sh\nexec ' + shlex.quote(str(python)) + ' ' + shlex.quote(str(APP/entry)) + ' "$@"\n'
        if launcher.exists() and launcher.read_text() != text:
            raise SystemExit('Refusing to replace a different launcher: ' + str(launcher))
        launcher.write_text(text)
        launcher.chmod(0o755)
    print(json.dumps({'installed': str(APP), 'config': str(CONFIG), 'command': str(bindir/'source-sdk'),
                      'next': 'Run source-sdk doctor and source-sdk call capabilities.'}, indent=2))


if __name__ == '__main__':
    main()
