"""Hermetic MCP handshake/tool-call test. No Steam installation, account, or running engine is required."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from agent import APP, TOOLS, atomic_json


class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_protocol_and_project_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root/'projects/demo'
            game = project/'game/mod_hl2mp'
            game.mkdir(parents=True)
            (game/'gameinfo.txt').write_text('"GameInfo" { game "Protocol Test" }\n')
            atomic_json(project/'.source-agent/project.json', {'name': 'demo', 'template': 'hl2mp'})
            config = root/'config.json'
            atomic_json(config, {'workspace_root': str(root/'projects'), 'steam_root': str(root/'steam'),
                                 'sdk_root': str(root/'sdk-missing'), 'runtime_root': str(root/'runtime-missing'),
                                 'image': 'registry.invalid/source-sdk-agent/test:missing', 'jobs': 2, 'memory_gib': 4,
                                 'map_tools': {}, 'asset_tools': {}, 'editor_tools': {}})
            params = StdioServerParameters(command=sys.executable, args=[str(APP/'server.py')],
                                          env={**os.environ, 'SOURCE_SDK_AGENT_CONFIG': str(config)})
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    listing = await session.list_tools()
                    names = {tool.name for tool in listing.tools}
                    self.assertEqual(names, set(TOOLS))
                    health = await session.call_tool('doctor', {})
                    self.assertFalse(health.isError)
                    self.assertFalse(json.loads(health.content[0].text)['ready_for_cpp'])
                    source = await session.call_tool('read_text', {'name': 'demo', 'path': 'game/mod_hl2mp/gameinfo.txt'})
                    self.assertFalse(source.isError)
                    self.assertIn('Protocol Test', source.content[0].text)
                    bad = await session.call_tool('read_text', {'name': 'demo', 'path': '../../outside.txt'})
                    self.assertTrue(bad.isError)
                    created = await session.call_tool('write_text', {'name': 'demo', 'path': 'src/protocol.cpp', 'content': '// original fixture\n'})
                    self.assertFalse(created.isError)
                    stale = await session.call_tool('write_text', {'name': 'demo', 'path': 'src/protocol.cpp', 'content': '// stale overwrite\n'})
                    self.assertTrue(stale.isError)
                    self.assertEqual((project/'src/protocol.cpp').read_text(), '// original fixture\n')


if __name__ == '__main__': unittest.main(verbosity=2)
