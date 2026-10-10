"""End-to-end development jobs; every stage must finish before the next begins."""
from __future__ import annotations
import contextlib
import json
import time
import agent as a


def run_pipeline(name: str, map_name: str, configuration: str = 'release', quality: str = 'fast', models: list[str] | None = None, test_server: bool = True, package: bool = False) -> dict:
    """Submit build -> optional models -> map compile -> optional server smoke test -> optional local ZIP. Never publishes."""
    root, _ = a.project(name)
    a.slug(map_name)
    if not a.contained(root, 'mapsrc/' + map_name + '.vmf').is_file():
        raise a.AgentError('Create the map source before running a pipeline.')
    if configuration not in ('release', 'debug') or quality not in ('fast', 'final'):
        raise a.AgentError('Use release/debug and fast/final.')
    if not isinstance(test_server, bool) or not isinstance(package, bool):
        raise a.AgentError('test_server and package must be booleans.')
    if models is None:
        models = []
    if not isinstance(models, list) or len(models) > 16:
        raise a.AgentError('At most 16 project QC files are accepted.')
    for source in models:
        path = a.contained(root, source)
        if path.suffix.lower() != '.qc' or not path.is_file():
            raise a.AgentError('Each model input must be an existing project QC file.')
    return a.submit(name, 'pipeline', {'map_name': map_name, 'configuration': configuration, 'quality': quality,
                                     'models': models, 'test_server': test_server, 'package': package})


def pipeline_job(data: dict, out) -> dict:
    """Run outside the build lock; child workers take that lock for compilation."""
    name, params = data['project'], data['parameters']
    stages = []
    current = None
    deadline = time.monotonic() + 4 * 3600

    def record(stage):
        stages.append(stage)
        data['stages'] = stages
        a.atomic_json(a.job_file(data['job_id']), data)
        out.write((json.dumps(stage) + '\n').encode())
        out.flush()

    def wait(child):
        nonlocal current
        current = child['job_id']
        data['active_child'] = current
        a.atomic_json(a.job_file(data['job_id']), data)
        while time.monotonic() < deadline:
            status = a.get_job(current, 5)
            if status['state'] not in ('queued', 'running'):
                record({'operation': status['operation'], 'job_id': current, 'state': status['state'],
                        'artifacts': status.get('artifacts', []), 'error': status.get('error')})
                current = None
                data.pop('active_child', None)
                if status['state'] != 'succeeded':
                    raise a.AgentError('Pipeline stopped at ' + status['operation'] + ': ' + str(status.get('error', status['state'])))
                return
            time.sleep(0.4)
        raise a.AgentError('Pipeline exceeded its four-hour execution limit.')

    try:
        wait(a.build(name, params['configuration'], 'game'))
        for source in params['models']:
            wait(a.TOOLS['compile_model'](name, source))
        wait(a.compile_map(name, params['map_name'], params['quality']))
        if params['test_server']:
            from sdk_runtime import smoke_test
            result = smoke_test(name, params['map_name'])
            record({'operation': 'smoke_test', 'state': 'succeeded' if result.get('passed') else 'failed', 'result': result})
            if not result.get('passed'):
                raise a.AgentError('The server smoke test failed; packaging was not attempted.')
        archive = None
        if params['package']:
            archive = a.package_mod(name)
            record({'operation': 'package_mod', 'state': 'succeeded', 'result': archive})
        return {'stages': stages, 'package': archive, 'published': False,
                'scope': 'Compilation and optional dedicated-server load test; visual/gameplay QA remains separate.'}
    finally:
        if current:
            # Cancellation must not leave a queued/running compiler behind.
            for _ in range(30):
                with contextlib.suppress(Exception):
                    child = a.get_job(current, 1)
                    if child['state'] not in ('queued', 'running'):
                        break
                    if child['state'] == 'running':
                        a.cancel_job(current)
                        break
                time.sleep(0.1)


TOOLS = {'run_pipeline': run_pipeline}
