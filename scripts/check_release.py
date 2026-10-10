#!/usr/bin/env python3
"""Audit Git-index contents before publication. This is not a complete secret scanner."""
from __future__ import annotations
import ast
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PARTS = {'.venv', 'toolchain', 'backups', '.source-agent', '__pycache__', 'dist', 'build', '.ssh', '.codex'}
FORBIDDEN_NAMES = {'config.json', 'mcp-verification.json', 'verification.json', 'prepare_release_local.py'}
FORBIDDEN_EXTENSIONS = {'.so', '.dll', '.exe', '.vpk', '.bsp', '.mdl', '.vtf', '.wav', '.log', '.dmp', '.zip', '.gz', '.pyc'}
PATTERNS = {
    'GitHub credential': re.compile(rb'\bgh[pousr]_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b'),
    'private key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
    'AWS access key': re.compile(rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'local home path': re.compile(rb'/home/[A-Za-z0-9][A-Za-z0-9_.-]+/'),
}


def git(*args: str) -> bytes:
    return subprocess.check_output(['git', *args], cwd=ROOT)


def main() -> int:
    failures = []
    files = {}
    entries = git('ls-files', '--stage', '-z').split(b'\0')
    for record in entries:
        if not record:
            continue
        metadata, raw_path = record.split(b'\t', 1)
        mode, oid, stage = metadata.decode().split()
        name = raw_path.decode('utf-8')
        path = PurePosixPath(name)
        if stage != '0' or mode not in ('100644', '100755'):
            failures.append((name, 'symlink, submodule or unresolved index entry'))
            continue
        if any(part in FORBIDDEN_PARTS for part in path.parts) or path.name in FORBIDDEN_NAMES or path.name.startswith('.env') or path.suffix.lower() in FORBIDDEN_EXTENSIONS:
            failures.append((name, 'private/local/binary file must not be published'))
            continue
        data = git('cat-file', 'blob', oid)
        if len(data) > 1024 * 1024 or b'\0' in data:
            failures.append((name, 'not a small text source file'))
            continue
        try:
            data.decode('utf-8')
        except UnicodeDecodeError:
            failures.append((name, 'not UTF-8 text'))
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(data):
                failures.append((name, label))
        files[name] = data
    for required in ('LICENSE', 'agent.py', 'server.py', 'install.py', 'requirements.lock', 'plugin.json', 'mcp.json', 'README.md', 'SECURITY.md'):
        if required not in files:
            failures.append((required, 'required release file missing from index'))
    if 'agent.py' in files and 'plugin.json' in files:
        tree = ast.parse(files['agent.py'].decode())
        version = next((node.value.value for node in tree.body if isinstance(node, ast.Assign)
                        and any(isinstance(target, ast.Name) and target.id == 'VERSION' for target in node.targets)), None)
        manifest = json.loads(files['plugin.json'])
        if manifest.get('version') != version:
            failures.append(('plugin.json', 'version differs from agent.py'))
        if len(manifest['extensions']['com.openai']['interface']['shortDescription']) > 30:
            failures.append(('plugin.json', 'listing short description exceeds 30 characters'))
    if failures:
        for name, reason in failures:
            print(f'FAIL {name}: {reason}', file=sys.stderr)
        print('Publication audit failed. No matched secret values are printed.', file=sys.stderr)
        return 1
    print(json.dumps({'passed': True, 'tracked_text_files': len(files), 'source_bytes': sum(map(len, files.values())),
                      'scope': 'Git-index file boundary, common credential patterns and manifest version; not a complete security audit.'}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
