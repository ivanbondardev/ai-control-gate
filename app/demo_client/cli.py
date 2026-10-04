"""Scenario client for the Action Gate MCP endpoint.

It is a small, explicit harness rather than a product client: the demonstration must not depend on
whether some third-party MCP host happens to support our operation-key extension.

What it does:

* talks to exactly one endpoint (Traefik ``/mcp``) with one transport principal;
* keeps a stable ``client_operation_key`` for a logical request, and can repeat or renew it;
* shows the decision, the effect, the disclosure and the receipt id of every call;
* refreshes the catalog explicitly before a task and after an operator change, because the profile
  does not push ``listChanged`` notifications.
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

OPERATION_KEY = 'actiongate.demo/operation_key'
DEFAULT_ENDPOINT = 'http://127.0.0.1/mcp'
PRINCIPAL_HEADER = 'X-Action-Gate-Principal'
TOKEN_HEADER = 'X-Action-Gate-Token'


def _credentials(principal_id, environ):
    """Local synthetic client tokens: the same checked-in registry the Gate authenticates against."""
    override = environ.get('DEMO_MCP_TOKEN')
    if override:
        return override
    path = (environ.get('DEMO_PRINCIPALS_FILE')
            or str(Path(__file__).resolve().parents[1] / 'policy' / 'principals.json'))
    document = json.loads(Path(path).read_text(encoding='utf-8'))
    for entry in document['principals']:
        if entry['id'] == principal_id:
            return entry['token']
    raise SystemExit(f'principal {principal_id!r} is not in {path}')


class Client:
    def __init__(self, endpoint, principal_id, token, *, timeout=30.0):
        self.endpoint = endpoint
        self.principal_id = principal_id
        self.token = token
        self.timeout = timeout

    def _http_client(self):
        import httpx2
        from mcp.client.streamable_http import create_mcp_http_client
        return create_mcp_http_client(
            headers={PRINCIPAL_HEADER: self.principal_id, TOKEN_HEADER: self.token},
            timeout=httpx2.Timeout(connect=2.0, read=self.timeout, write=self.timeout,
                                   pool=2.0))

    async def _session(self):
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        client = self._http_client()
        context = streamable_http_client(self.endpoint, http_client=client)
        read, write = await context.__aenter__()
        session_context = ClientSession(read, write)
        session = await session_context.__aenter__()
        return session, session_context, context, client

    async def list_tools(self):
        session, session_context, context, client = await self._session()
        try:
            await session.initialize()
            listing = await session.list_tools()
            return [{'name': tool.name, 'description': tool.description,
                     'mutation': not (tool.annotations.read_only_hint
                                      if tool.annotations else False),
                     'required': (tool.input_schema or {}).get('required', [])}
                    for tool in listing.tools]
        finally:
            await session_context.__aexit__(None, None, None)
            await context.__aexit__(None, None, None)
            await client.aclose()

    async def call(self, tool, arguments, *, operation_key=None, meta=None, tools_updated=False):
        session, session_context, context, client = await self._session()
        try:
            await session.initialize()
            if tools_updated:
                await session.list_tools()
            payload = dict(meta or {})
            if operation_key:
                payload[OPERATION_KEY] = operation_key
            result = await session.call_tool(tool, arguments, meta=payload or None)
            structured = result.structured_content
            return {'isError': bool(result.is_error), 'result': structured,
                    'text': '\n'.join(block.text for block in result.content
                                      if getattr(block, 'type', None) == 'text')}
        finally:
            await session_context.__aexit__(None, None, None)
            await context.__aexit__(None, None, None)
            await client.aclose()


def _print(payload, *, quiet=False):
    if quiet:
        return
    json.dump(payload, sys.stdout, indent=2, sort_keys=True, ensure_ascii=False, default=str)
    sys.stdout.write('\n')


def _summary(response):
    result = response.get('result') or {}
    return {'isError': response['isError'], 'status': result.get('status'),
            'decision': result.get('decision'), 'effect': result.get('effect'),
            'disclosure': result.get('disclosure'), 'operationId': result.get('operation_id'),
            'receiptId': result.get('receipt_id'), 'replayed': result.get('replayed'),
            'resourceId': result.get('resource_id'),
            'error': (result.get('error') or {}).get('code')}


def build_parser():
    parser = argparse.ArgumentParser(prog='demo_client', description=__doc__)
    parser.add_argument('--endpoint', default=os.environ.get('DEMO_MCP_ENDPOINT', DEFAULT_ENDPOINT))
    parser.add_argument('--principal', default='support-agent')
    parser.add_argument('--tool')
    parser.add_argument('--args', default='{}', help='JSON object with the tool arguments')
    parser.add_argument('--key', default=None, help='client operation key (default: generated)')
    parser.add_argument('--repeat-key', action='store_true',
                        help='repeat the last key from the run file instead of starting a new one')
    parser.add_argument('--refresh-tools', action='store_true',
                        help='list the catalog again before the call')
    parser.add_argument('--run-file', default=None,
                        help='file that remembers the last operation key of a scenario')
    parser.add_argument('command', choices=('tools', 'call', 'scenario'))
    return parser


def _remember(path, key):
    if not path:
        return
    Path(path).write_text(json.dumps({'last_key': key}), encoding='utf-8')


def _recall(path):
    if not path or not Path(path).exists():
        return None
    try:
        return json.loads(Path(path).read_text(encoding='utf-8')).get('last_key')
    except (OSError, ValueError):
        return None


def main(argv=None) -> int:
    arguments = build_parser().parse_args(argv)
    token = _credentials(arguments.principal, os.environ)
    client = Client(arguments.endpoint, arguments.principal, token)

    if arguments.command == 'tools':
        _print({'principal': arguments.principal, 'endpoint': arguments.endpoint,
                'tools': asyncio.run(client.list_tools())})
        return 0

    if arguments.command == 'scenario':
        return _scenario(client, arguments)

    tool = arguments.tool
    if not tool:
        raise SystemExit('--tool is required for the call command')
    try:
        call_arguments = json.loads(arguments.args)
    except ValueError as exc:
        raise SystemExit(f'--args is not valid JSON: {exc}') from exc
    key = arguments.key
    if arguments.repeat_key:
        key = _recall(arguments.run_file) or arguments.key
    if key is None:
        import uuid
        key = 'cli-' + uuid.uuid4().hex[:16]
    response = asyncio.run(client.call(tool, call_arguments, operation_key=key,
                                       tools_updated=arguments.refresh_tools))
    _remember(arguments.run_file, key)
    _print({'client': {'principal': arguments.principal, 'tool': tool,
                       'operationKey': key, 'arguments': call_arguments},
            'response': response, 'summary': _summary(response)})
    return 0 if not response['isError'] else 1


def _scenario(client, arguments):
    """The main demonstration story in one command, so a rehearsal is one line."""
    steps = [
        ('1. catalog', lambda: client.list_tools()),
        ('2. read KB-1042', lambda: client.call('documents_read', {'doc_id': 'KB-1042'},
                                                operation_key='scenario-read-1')),
        ('3. store a summary for the internal recipient',
         lambda: client.call('outbox_send',
                             {'to': 'colleague@acme.example', 'subject': 'Access reset summary',
                              'body': 'The two-factor reset procedure was verified and summarized.'},
                             operation_key='scenario-send-1')),
        ('4. attempt the external recipient',
         lambda: client.call('outbox_send',
                             {'to': 'recipient@external.example', 'subject': 'Access reset summary',
                              'body': 'The two-factor reset procedure was verified and summarized.'},
                             operation_key='scenario-send-2')),
        ('5. attempt to update the protected document',
         lambda: client.call('documents_update',
                             {'doc_id': 'KB-9000', 'content': 'Synthetic rewrite.',
                              'expected_version': 1},
                             operation_key='scenario-update-protected')),
    ]
    report = {'principal': arguments.principal, 'endpoint': arguments.endpoint, 'steps': []}
    for label, action in steps:
        try:
            outcome = asyncio.run(action())
        except Exception as exc:  # noqa: BLE001 - a protocol refusal is a result here
            report['steps'].append({'step': label, 'protocolError': f'{type(exc).__name__}: {exc}'})
            continue
        if isinstance(outcome, list):
            report['steps'].append({'step': label, 'tools': [tool['name'] for tool in outcome]})
        else:
            report['steps'].append({'step': label, 'summary': _summary(outcome),
                                    'result': outcome.get('result')})
    _print(report)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
