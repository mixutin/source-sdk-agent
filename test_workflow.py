"""Portable workflow, structured-editor, and installer regression tests."""
import io
from pathlib import Path
import unittest
from unittest.mock import patch
import agent as a
import sdk_content as c
import sdk_editor as e
import sdk_workflow as w
import test_extensions as fixtures
from install import tool_paths


class WorkflowTests(unittest.TestCase):
    setUp = fixtures.ExtensionTests.setUp
    tearDown = fixtures.ExtensionTests.tearDown

    def test_add_brush_and_ids(self):
        source = a.generate_room('demo')
        result = e.add_brush('demo', 'agent_test', [-32, 64, 0], [32, 128, 32], source['sha256'])
        info = c.inspect_map('demo', 'agent_test')
        self.assertEqual((info['brushes'], info['sides']), (7, 42))
        self.assertEqual(info['warnings'], [])
        self.assertTrue(Path(result['backup']).is_file())
        tree = c.parse_kv(Path(result['path']).read_text())
        solid = c.val(tree, 'world')[-1][1]
        import re
        center = (0, 96, 16)
        for key, side in solid:
            if key != 'side': continue
            p, q, r = [tuple(map(float, point.split())) for point in re.findall(r'\(([^)]+)\)', c.val(side, 'plane'))]
            u = tuple(x-y for x, y in zip(p, q)); v = tuple(x-y for x, y in zip(r, q))
            normal = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
            self.assertLess(sum(n*(x-y) for n, x, y in zip(normal, center, p)), 0)

    def test_brush_bad_coordinates(self):
        result = a.generate_room('demo')
        for minimum, maximum in [([0, 0], [1, 1, 1]), ([0, 0, 0], [0, 1, 1]),
                                 ([float('nan'), 0, 0], [1, 1, 1]), ([0, 0, 0], [17000, 1, 1]),
                                 ([False, 0, 0], [1, 1, 1]), ([0, 0, 0], [float('inf'), 1, 1])]:
            with self.assertRaises(a.AgentError):
                e.add_brush('demo', 'agent_test', minimum, maximum, result['sha256'])
        self.assertEqual(c.inspect_map('demo', 'agent_test')['sha256'], result['sha256'])

    def test_brush_stale_hash(self):
        a.generate_room('demo')
        with self.assertRaises(a.AgentError):
            e.add_brush('demo', 'agent_test', [0, 0, 0], [1, 1, 1], 'stale')

    def test_remove_entity_keeps_world(self):
        source = a.generate_room('demo')
        info = c.inspect_map('demo', 'agent_test')
        result = e.remove_map_entity('demo', 'agent_test', info['entities'][-1]['id'], source['sha256'])
        final = c.inspect_map('demo', 'agent_test')
        self.assertEqual(final['brushes'], 6)
        self.assertEqual(final['entity_count'], info['entity_count'] - 1)
        self.assertTrue(Path(result['backup']).exists())

    def test_world_cannot_be_removed_as_entity(self):
        source = a.generate_room('demo')
        with self.assertRaises(a.AgentError):
            e.remove_map_entity('demo', 'agent_test', '1', source['sha256'])

    def test_map_id_case_insensitive(self):
        source = a.generate_room('demo')
        for key in ('id', 'ID', 'Id'):
            with self.assertRaises(a.AgentError):
                c.edit_map_entity('demo', 'agent_test', '', {key: '1', 'classname': 'light'}, source['sha256'])

    def test_unconfigured_editor(self):
        for editor in ('hammer', 'hlmv', 'faceposer', 'shell'):
            with self.assertRaises(a.AgentError): e.open_editor('demo', editor)

    def test_pipeline_requires_map(self):
        with self.assertRaises(a.AgentError): w.run_pipeline('demo', 'missing')

    def test_pipeline_validated_submission(self):
        a.generate_room('demo')
        with patch.object(a, 'submit', return_value={'job_id': 'test'}) as submit:
            result = w.run_pipeline('demo', 'agent_test', package=True)
            self.assertEqual(result['job_id'], 'test')
            self.assertEqual(submit.call_args.args[1], 'pipeline')
            self.assertTrue(submit.call_args.args[2]['test_server'])
        for args in ({'configuration': 'bad'}, {'quality': 'ultra'}, {'models': 'foo'},
                     {'models': ['../private.qc']}, {'package': 'yes'}, {'test_server': 1}):
            with self.assertRaises(a.AgentError): w.run_pipeline('demo', 'agent_test', **args)

    def data(self):
        return {'job_id': 'c'*32, 'project': 'demo', 'state': 'running', 'parameters': {
            'map_name': 'agent_test', 'configuration': 'release', 'quality': 'fast',
            'models': [], 'test_server': True, 'package': True}}

    def test_pipeline_stops_on_failed_build(self):
        with patch.object(a, 'build', return_value={'job_id': 'a'*32}), \
             patch.object(a, 'get_job', return_value={'state': 'failed', 'operation': 'build', 'error': 'compile failed'}), \
             patch.object(a, 'compile_map') as compile_map, patch.object(a, 'package_mod') as package:
            with self.assertRaises(a.AgentError): w.pipeline_job(self.data(), io.BytesIO())
            compile_map.assert_not_called(); package.assert_not_called()

    def test_pipeline_complete_order(self):
        statuses = [{'state': 'succeeded', 'operation': 'build'}, {'state': 'succeeded', 'operation': 'compile_map'}]
        with patch.object(a, 'build', return_value={'job_id': 'a'*32}), \
             patch.object(a, 'compile_map', return_value={'job_id': 'b'*32}), \
             patch.object(a, 'get_job', side_effect=statuses), \
             patch('sdk_runtime.smoke_test', return_value={'passed': True}), \
             patch.object(a, 'package_mod', return_value={'archive': 'local.zip'}):
            result = w.pipeline_job(self.data(), io.BytesIO())
            self.assertEqual([s['operation'] for s in result['stages']], ['build', 'compile_map', 'smoke_test', 'package_mod'])
            self.assertFalse(result['published'])

    def test_pipeline_failed_smoke_never_packages(self):
        statuses = [{'state': 'succeeded', 'operation': 'build'}, {'state': 'succeeded', 'operation': 'compile_map'}]
        with patch.object(a, 'build', return_value={'job_id': 'a'*32}), \
             patch.object(a, 'compile_map', return_value={'job_id': 'b'*32}), \
             patch.object(a, 'get_job', side_effect=statuses), \
             patch('sdk_runtime.smoke_test', return_value={'passed': False}), \
             patch.object(a, 'package_mod') as package:
            with self.assertRaises(a.AgentError): w.pipeline_job(self.data(), io.BytesIO())
            package.assert_not_called()

    def test_pipeline_cancellation_reaches_child(self):
        with patch.object(a, 'build', return_value={'job_id': 'a'*32}), \
             patch.object(a, 'get_job', side_effect=[InterruptedError('cancel'), {'state': 'running'}]), \
             patch.object(a, 'cancel_job') as cancel:
            with self.assertRaises(InterruptedError): w.pipeline_job(self.data(), io.BytesIO())
            cancel.assert_called_once_with('a'*32)

    def test_doctor_unconfigured(self):
        with patch.object(a, 'cfg', side_effect=a.AgentError('not configured')):
            result = a.doctor()
            self.assertFalse(result['configured']); self.assertFalse(result['ready_for_cpp'])

    def test_installer_prefers_native_tools(self):
        tools = self.root/'tools'; tools.mkdir()
        for filename in ('vbsp++', 'vbsp.exe', 'studiomdl++', 'hammer.exe'):
            (tools/filename).write_bytes(b'fixture')
        result = tool_paths(tools)
        self.assertEqual(Path(result['vbsp']).name, 'vbsp++')
        self.assertIn('studiomdl', result); self.assertIn('hammer', result)


if __name__ == '__main__': unittest.main(verbosity=2)
