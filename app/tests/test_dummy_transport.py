"""Dummy transport: authenticated MCP over Streamable HTTP plus the read-only status route.

These checks are the service half of the acceptance matrix items P05, P06 and A01: strict schema
before the handler, a unified protocol error for an unknown tool, no anonymous access to the
catalog, and metadata-only operation status for the Gate.
"""
import asyncio
import json
import os
import shutil
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

try:
    import uvicorn
    from mcp import ClientSession
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
    from dummy_mcp.common.storage import Store
    from dummy_mcp.documents.service import DocumentsService
    IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001 - reported as a skip
    IMPORT_ERROR = exc

TOKEN = 'local-dummy-service-token-for-tests'
HEADERS = {'X-Action-Gate-Service': 'gate-mcp', 'X-Action-Gate-Token': TOKEN}
RUN = 'run-0001'


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@unittest.skipIf(IMPORT_ERROR is not None, f'dummy transport unavailable: {IMPORT_ERROR}')
class DummyTransportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.mkdtemp(prefix='dummy-transport-')
        service = DocumentsService(Store('documents', os.path.join(cls.directory, 'documents.sqlite3')),
                                   hold_seconds=0.1)
        service.bootstrap(run_id=RUN)
        cls.service = service
        cls.port = free_port()
        app = service.build_app({'gate-mcp': TOKEN})
        config = uvicorn.Config(app, host='127.0.0.1', port=cls.port, log_level='error')
        cls.server = uvicorn.Server(config)
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        deadline = time.time() + 20
        while time.time() < deadline and not cls.server.started:
            time.sleep(0.05)
        if not cls.server.started:
            raise AssertionError('the dummy service did not start')

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=10)
        shutil.rmtree(cls.directory, ignore_errors=True)

    def url(self, path='/mcp'):
        return f'http://127.0.0.1:{self.port}{path}'

    def test_anonymous_caller_gets_no_catalog(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.url(), timeout=5)
        self.assertEqual(caught.exception.code, 401)
        # A POST without credentials is refused before the transport, so the catalog is unreachable.
        request = urllib.request.Request(
            self.url(), data=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}).encode(),
            headers={'Content-Type': 'application/json'})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 401)

    def test_health_is_public(self):
        with urllib.request.urlopen(self.url('/health/ready'), timeout=5) as response:
            self.assertEqual(json.loads(response.read())['status'], 'ready')

    def test_tools_list_and_call_over_the_sdk(self):
        result = asyncio.run(self._round_trip())
        self.assertEqual(sorted(result['tools']), ['read_document', 'search_documents',
                                                   'update_document'])
        update = result['schemas']['update_document']
        self.assertFalse(update['additionalProperties'])
        self.assertEqual(set(update['required']), {'doc_id', 'content', 'expected_version'})
        self.assertEqual(result['read']['content'].startswith('To reset two-factor'), True)
        self.assertEqual(result['read']['version'], 1)
        self.assertIn('Unknown tool: not_published', result['unknown_tool'])
        self.assertIn('Additional properties', result['extra_argument'])

    async def _round_trip(self):
        out = {}
        client = create_mcp_http_client(headers=HEADERS)
        async with streamable_http_client(self.url(), http_client=client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listing = await session.list_tools()
                out['tools'] = [tool.name for tool in listing.tools]
                out['schemas'] = {tool.name: tool.input_schema for tool in listing.tools}
                call = await session.call_tool('read_document', {'doc_id': 'KB-1042'},
                                               meta=self.meta('op-transport-read'))
                out['read'] = call.structured_content
                try:
                    await session.call_tool('not_published', {}, meta=self.meta('op-none'))
                    out['unknown_tool'] = 'unexpected success'
                except Exception as exc:  # noqa: BLE001 - the refusal is the assertion target
                    out['unknown_tool'] = f'{exc}'
                try:
                    await session.call_tool('read_document',
                                            {'doc_id': 'KB-1042', 'extra': True},
                                            meta=self.meta('op-extra'))
                    out['extra_argument'] = 'unexpected success'
                except Exception as exc:  # noqa: BLE001
                    out['extra_argument'] = f'{exc}'
        return out

    async def _read_once(self):
        client = create_mcp_http_client(headers=HEADERS)
        async with streamable_http_client(self.url(), http_client=client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await session.call_tool('read_document', {'doc_id': 'KB-1042'},
                                        meta=self.meta('op-transport-status'))

    @staticmethod
    def meta(operation_id):
        return {'actiongate.internal/operation_id': operation_id,
                'actiongate.internal/demo_run_id': RUN,
                'actiongate.internal/actor': 'support-agent'}

    def test_operation_status_requires_identity_and_is_metadata_only(self):
        # Independent of test order: this test creates the operation it then inspects.
        asyncio.run(self._read_once())
        request = urllib.request.Request(self.url('/operations/op-transport-status'), headers=HEADERS)
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read())
        self.assertEqual(payload['status'], 'committed')
        self.assertIn('receipt', payload)
        self.assertNotIn('content', json.dumps(payload))
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.url('/operations/op-transport-status'), timeout=5)
        self.assertEqual(caught.exception.code, 401)


if __name__ == '__main__':
    unittest.main()
