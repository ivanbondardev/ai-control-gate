"""M00 protocol smoke: prove the pinned SDK profile end to end over Streamable HTTP.

The test starts a low-level MCP server with the same construction the runtime uses, connects the
real SDK client, and checks the negotiated revision, the raw JSON Schema round trip, a real tool
call, `_meta` delivery, structured content and the unified refusal for an unknown tool.

It skips when the MCP SDK is not installed, so the default unit suite still runs on a bare host.
"""
import asyncio
import contextlib
import json
import socket
import threading
import time
import unittest

try:  # pragma: no cover - exercised by the skip branch on a host without the SDK
    import uvicorn
    from mcp import ClientSession, types
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
    from mcp.server.lowlevel import Server
    from mcp.server.transport_security import TransportSecuritySettings
    from mcp.shared.exceptions import MCPError
    SDK_IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001 - any import failure means "profile not installed"
    SDK_IMPORT_ERROR = exc

PROFILE_REVISION = '2025-11-25'
INPUT_SCHEMA = {
    'type': 'object',
    'properties': {'value': {'type': 'string', 'minLength': 1}},
    'required': ['value'],
    'additionalProperties': False,
}
OUTPUT_SCHEMA = {
    'type': 'object',
    'properties': {'status': {'type': 'string'}, 'value': {'type': 'string'}},
    'required': ['status', 'value'],
    'additionalProperties': False,
}


@unittest.skipIf(SDK_IMPORT_ERROR is not None, f'MCP SDK unavailable: {SDK_IMPORT_ERROR}')
class McpProfileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seen = []
        tool = types.Tool(name='probe', description='Profile probe.', inputSchema=INPUT_SCHEMA,
                          outputSchema=OUTPUT_SCHEMA)

        async def on_list_tools(context, params):
            return types.ListToolsResult(tools=[tool])

        async def on_call_tool(context, params):
            cls.seen.append({'name': params.name, 'arguments': params.arguments, 'meta': params.meta})
            if params.name != 'probe':
                raise MCPError(types.INVALID_PARAMS, 'Unknown or unavailable tool')
            value = (params.arguments or {}).get('value')
            payload = {'status': 'succeeded', 'value': value}
            return types.CallToolResult(
                content=[types.TextContent(type='text', text=json.dumps(payload))],
                structuredContent=payload)

        server = Server(name='profile-probe', version='0.0.1',
                        on_list_tools=on_list_tools, on_call_tool=on_call_tool)
        app = server.streamable_http_app(
            json_response=True, stateless_http=True,
            transport_security=TransportSecuritySettings(
                allowed_hosts=['*'], allowed_origins=['*'], enable_dns_rebinding_protection=False))
        cls.port = _free_port()
        config = uvicorn.Config(app, host='127.0.0.1', port=cls.port, log_level='error')
        cls.server = uvicorn.Server(config)
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        deadline = time.time() + 20
        while time.time() < deadline and not cls.server.started:
            time.sleep(0.05)
        if not cls.server.started:
            raise AssertionError('the probe server did not start')

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=10)

    def test_profile(self):
        result = asyncio.run(self._run())
        self.assertEqual(result['protocol'], PROFILE_REVISION)
        self.assertEqual(result['tools'][0]['input_schema'], INPUT_SCHEMA)
        self.assertEqual(result['tools'][0]['output_schema'], OUTPUT_SCHEMA)
        self.assertEqual(result['call']['structured_content'], {'status': 'succeeded', 'value': 'x'})
        self.assertFalse(result['call']['is_error'])
        self.assertEqual(result['call']['content'][0]['text'], '{"status": "succeeded", "value": "x"}')
        self.assertEqual(result['meta_seen'], {'actiongate.demo/operation_key': 'key-1'})
        self.assertIn('Unknown or unavailable tool', result['unknown_tool'])
        self.assertEqual(result['ping'], True)

    async def _run(self):
        url = f'http://127.0.0.1:{self.port}/mcp'
        out = {}
        client = create_mcp_http_client(headers={'X-Action-Gate-Principal': 'support-agent',
                                                 'X-Action-Gate-Token': 'ignored-by-the-probe'})
        async with streamable_http_client(url, http_client=client) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                out['protocol'] = init.protocol_version
                listing = await session.list_tools()
                out['tools'] = [t.model_dump(mode='json', exclude_none=True) for t in listing.tools]
                call = await session.call_tool('probe', {'value': 'x'},
                                               meta={'actiongate.demo/operation_key': 'key-1'})
                out['call'] = call.model_dump(mode='json', exclude_none=True)
                out['meta_seen'] = self.seen[-1]['meta']
                try:
                    await session.call_tool('not_published', {})
                    out['unknown_tool'] = 'unexpected success'
                except Exception as exc:  # noqa: BLE001 - the refusal is the assertion target
                    out['unknown_tool'] = f'{type(exc).__name__}: {exc}'
                out['ping'] = (await session.send_ping()) is not None
        return out

    def test_unauthenticated_get_opens_no_stream(self):
        import urllib.error
        import urllib.request
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f'http://127.0.0.1:{self.port}/mcp', timeout=5)
        self.assertIn(caught.exception.code, (400, 405, 406))


def _free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


if __name__ == '__main__':
    unittest.main()
