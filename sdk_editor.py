"""Structured VMF geometry editing and optional local Source editor launchers."""
from __future__ import annotations
import math
import os
from pathlib import Path
import subprocess
import time
import agent as a
from sdk_content import _map, asset_path, compiler_environment, compiler_game, dump_kv, val, windows_path


def _next_id(tree: list) -> int:
    ids = []
    def walk(items):
        for key, value in items:
            if isinstance(value, list):
                walk(value)
            elif key.lower() == 'id':
                try:
                    ids.append(int(value))
                except (ValueError, TypeError):
                    raise a.AgentError('Map contains a non-integer ID.')
    walk(tree)
    return max(ids, default=0) + 1


def add_brush(name: str, map_name: str, minimum: list[float], maximum: list[float], expected_sha256: str, material: str = 'dev/dev_measuregeneric01', entity_id: str = '') -> dict:
    """Add a correctly wound cuboid to the world or an existing brush entity, with a hash-checked backup."""
    root, path, tree = _map(name, map_name)
    if a.sha(path.read_bytes()) != expected_sha256:
        raise a.AgentError('Map changed; read its current SHA-256 before editing.')
    asset_path(material)
    if len(material) > 127:
        raise a.AgentError('Material path exceeds the supported map limit.')
    for point in (minimum, maximum):
        if not isinstance(point, list) or len(point) != 3:
            raise a.AgentError('Each corner must have three coordinates.')
        if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or abs(v) >= 16384 for v in point):
            raise a.AgentError('Coordinates must be finite numbers inside +/-16384.')
    if any(lo >= hi for lo, hi in zip(minimum, maximum)):
        raise a.AgentError('Each minimum coordinate must be less than its maximum.')
    parent = next((v for k, v in tree if k.lower() == 'world'), None)
    if entity_id:
        parent = next((v for k, v in tree if k.lower() == 'entity' and val(v, 'id') == str(entity_id)), None)
        if parent is not None and not str(val(parent, 'classname', '')).startswith(('func_', 'trigger_')):
            raise a.AgentError('Geometry may only be attached to a func_ or trigger_ brush entity.')
    if parent is None:
        raise a.AgentError('The target world/brush entity was not found.')
    x, y, z = minimum
    X, Y, Z = maximum
    faces = [((x,y,Z),(X,y,Z),(X,Y,Z)), ((x,Y,z),(X,Y,z),(X,y,z)),
             ((x,y,z),(x,y,Z),(x,Y,Z)), ((X,Y,z),(X,Y,Z),(X,y,Z)),
             ((X,y,z),(X,y,Z),(x,y,Z)), ((x,Y,z),(x,Y,Z),(X,Y,Z))]
    index = _next_id(tree)
    solid = [['id', str(index)]]
    for side, points in enumerate(faces):
        points = (points[1], points[0], points[2])
        plane = ' '.join('(' + ' '.join(format(float(v), '.9g') for v in p) + ')' for p in points)
        u = '[0 1 0 0] 0.25' if side in (2, 3) else '[1 0 0 0] 0.25'
        v = '[0 -1 0 0] 0.25' if side < 2 else '[0 0 -1 0] 0.25'
        solid.append(['side', [['id', str(index + side + 1)], ['plane', plane], ['material', material],
                              ['uaxis', u], ['vaxis', v], ['rotation', '0'], ['lightmapscale', '16'], ['smoothing_groups', '0']]])
    parent.append(['solid', solid])
    result = a.write_text(name, str(path.relative_to(root)), dump_kv(tree), expected_sha256)
    return {**result, 'brush_id': str(index), 'sides': 6, 'compiled': False}


def remove_map_entity(name: str, map_name: str, entity_id: str, expected_sha256: str) -> dict:
    """Remove one VMF entity by ID, keeping geometry elsewhere intact and retaining an undo backup."""
    root, path, tree = _map(name, map_name)
    if a.sha(path.read_bytes()) != expected_sha256:
        raise a.AgentError('Map changed; supply its current SHA-256.')
    found = [i for i, (key, fields) in enumerate(tree) if key.lower() == 'entity' and val(fields, 'id') == str(entity_id)]
    if len(found) != 1:
        raise a.AgentError('Expected exactly one matching entity; no changes were made.')
    del tree[found[0]]
    return {**a.write_text(name, str(path.relative_to(root)), dump_kv(tree), expected_sha256),
            'removed_entity': str(entity_id), 'warning': 'Review outputs in other entities that targeted the removed entity.'}


def open_editor(name: str, editor: str = 'hammer', path: str = '') -> dict:
    """Request a configured Hammer/HLMV/Faceposer window for this project; does not claim GUI automation or successful startup."""
    root, _ = a.project(name)
    if editor not in ('hammer', 'hlmv', 'faceposer'):
        raise a.AgentError('Choose hammer, hlmv, or faceposer.')
    configured = a.cfg().get('editor_tools', {}).get(editor)
    if not configured or not Path(configured).is_file():
        raise a.AgentError('This editor is not installed/configured. Set editor_tools.' + editor + ' to its licensed executable.')
    source = a.contained(root, path) if path else None
    expected = {'hammer': '.vmf', 'hlmv': '.mdl', 'faceposer': '.vcd'}[editor]
    if source and (not source.is_file() or source.suffix.lower() != expected):
        raise a.AgentError('This editor expects an existing project ' + expected + ' file.')
    executable = Path(configured)
    windows = executable.suffix.lower() == '.exe'
    folder = root / '.source-agent/editors' / str(time.time_ns())
    proxy = compiler_game(name, folder / 'game', windows)
    convert = windows_path if windows else str
    command = (['wine', str(executable)] if windows else [str(executable)]) + ['-game', convert(proxy)]
    if source:
        command.append(convert(source))
    environment = compiler_environment() if windows else dict(os.environ)
    with (folder / 'editor.log').open('wb') as output:
        process = subprocess.Popen(command, cwd=executable.parent, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
    return {'editor': editor, 'pid': process.pid, 'launch_requested': True, 'verified_running': False,
            'log': str(folder / 'editor.log'), 'note': 'Editor UI interaction and Wine compatibility must be checked separately.'}


TOOLS = {fn.__name__: fn for fn in (add_brush, remove_map_entity, open_editor)}
