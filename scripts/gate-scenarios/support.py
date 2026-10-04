#!/usr/bin/env python3
"""JSON preparation and assertions only. Network requests belong to the Bash runner."""
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
CASES = json.loads((HERE / 'cases.json').read_text())


def dump(value, path=None):
    text = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    if path:
        Path(path).write_text(text)
    else:
        print(text, end='')


def case(identifier):
    return next(c for c in CASES if c['id'] == identifier)


def credentials(principal):
    override = os.environ.get('GATE_TOKEN') if principal == os.environ.get('GATE_PRINCIPAL', 'support-agent') else None
    if override:
        return override
    base = os.environ.get('GATE_BASE_URL', 'https://ai-control-gate.ivbon.dev').rstrip('/')
    if base == 'https://ai-control-gate.ivbon.dev':
        path = HERE.parents[1] / 'secrets/staging-client/principals.json'
        if not path.is_file():
            raise ValueError('Missing staging client credentials; run sync-staging-auth.sh')
    elif urlsplit(base).hostname in ('localhost', '127.0.0.1', 'ai-control-proxy.localhost'):
        path = HERE.parents[1] / 'app/policy/principals.json'
    else:
        raise ValueError('Explicit GATE_TOKEN required for this Gate origin')
    registry = json.loads(path.read_text())
    return next(p['token'] for p in registry['principals'] if p['id'] == principal)


def auth(path, principal, mode):
    headers = ['Content-Type: application/json', 'Accept: application/json, text/event-stream']
    if mode != 'none':
        token = 'invalid-synthetic-token' if mode == 'bad' else credentials(principal)
        if any(c in token + principal for c in '\r\n'):
            raise ValueError('Invalid credential header')
        headers += [f'X-Action-Gate-Principal: {principal}', f'X-Action-Gate-Token: {token}']
    # curl reads headers from a private file: credentials never become command-line arguments.
    Path(path).write_text('\n'.join(headers) + '\n')


def prepare(identifier, dest, run):
    c = case(identifier)
    if c['group'] == 'mcp':
        params = {'name': c['tool'], 'arguments': c['arguments']} if c.get('tool') else {}
        if c.get('tool') and not c.get('omit_key'):
            params['_meta'] = {'actiongate.demo/operation_key': f'{run}-{identifier}'}
        data = {'jsonrpc': '2.0', 'id': identifier, 'method': 'tools/call' if c.get('tool') else 'tools/list', 'params': params}
    else:
        if c.get('malformed'):
            Path(dest).write_text('{"model":')
            return
        data = json.loads((HERE / c['request']).read_text())
        if data['model'] == '${OPENAI_MODEL}':
            data['model'] = os.environ.get('OPENAI_MODEL', '')
            if not data['model']:
                raise ValueError('Set OPENAI_MODEL to a model enabled in the Gate policy and provider account')
        if c.get('large'):
            data['input'] = 'Synthetic boundary test. ' * 50000
    dump(data, dest)


def response_ok(data, model=None):
    assert data.get('object') == 'response', 'Not an OpenAI Responses envelope'
    assert isinstance(data.get('id'), str) and data['id'], 'Missing response ID'
    assert data.get('status') == 'completed', 'Response did not complete (may need a larger output cap)'
    assert isinstance(data.get('output'), list) and data['output'], 'Missing typed output items'
    assert all(isinstance(x, dict) and 'type' in x for x in data['output']), 'Invalid output items'
    usage = data.get('usage')
    assert isinstance(usage, dict), 'Missing provider usage'
    for key in ('input_tokens', 'output_tokens', 'total_tokens'):
        assert isinstance(usage.get(key), int) and usage[key] >= 0, f'Invalid usage.{key}'
    assert usage['total_tokens'] == usage['input_tokens'] + usage['output_tokens'], 'Inconsistent usage'
    assert isinstance(data.get('model'), str) and data['model'], 'Missing returned model'
    # OpenAI can resolve an alias to a dated snapshot; equality is checked in Gate evidence.


def validate(c, code, raw):
    expect = c['expect']
    if code in (404, 405) and c['group'] != 'mcp':
        return 'BLOCKED', 'Model endpoint missing or route not available'
    if expect == 'stream_block':
        if code == 403:
            data = json.loads(raw)
            assert isinstance(data.get('error'), dict) and data['error'].get('message'), 'Missing output-block error'
        else:
            assert code == 200, f'Expected pre-stream 403 or SSE 200, got {code}'
            events = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith('data: ') and line[6:] != '[DONE]']
            assert any(e.get('type') in ('error','response.failed') for e in events), 'Missing terminal output-block event'
            assert not any(e.get('type') == 'response.completed' for e in events), 'Blocked stream completed successfully'
            deltas = ''.join(e.get('delta','') for e in events if e.get('type') == 'response.output_text.delta')
            for value in c.get('forbidden',[]):
                assert value not in json.dumps(events,ensure_ascii=False) and value not in deltas, 'Sensitive canary leaked before block'
    elif expect in ('stream', 'stream_clean'):
        assert code == 200, f'Expected SSE HTTP 200, got {code}'
        events = []
        for line in raw.splitlines():
            if line.startswith('data: ') and line[6:] != '[DONE]':
                events.append(json.loads(line[6:]))
        assert events and any(e.get('type') == 'response.created' for e in events), 'Missing response.created'
        assert not any(e.get('type') in ('error', 'response.failed', 'response.incomplete') for e in events), 'Stream failed'
        completed = [e for e in events if e.get('type') == 'response.completed']
        assert len(completed) == 1, 'Missing or duplicate terminal response.completed'
        response_ok(completed[0]['response'])
        deltas = ''.join(e.get('delta', '') for e in events if e.get('type') == 'response.output_text.delta')
        for value in c.get('forbidden', []):
            assert value not in json.dumps(events, ensure_ascii=False) and value not in deltas, 'Sensitive canary leaked through SSE'
    else:
        data = json.loads(raw)
        if expect in ('response', 'clean'):
            assert code == 200, f'Expected HTTP 200, got {code}'
            response_ok(data)
            for value in c.get('forbidden', []):
                assert value not in json.dumps(data, ensure_ascii=False), 'Sensitive canary in response'
        elif expect.startswith('mcp_'):
            assert code == 200, f'Expected MCP HTTP 200, got {code}'
            assert data.get('jsonrpc') == '2.0' and data.get('id') == c['id'], 'JSON-RPC correlation mismatch'
            result = data.get('result', {})
            if expect in ('mcp_hidden', 'mcp_invalid'):
                assert data.get('error', {}).get('code') == -32602, 'Expected typed JSON-RPC refusal'
            elif expect.startswith('mcp_catalog'):
                names = [t['name'] for t in result['tools']]
                assert 'documents_read' in names, 'Expected readable tool missing'
                if expect == 'mcp_catalog_readonly':
                    assert not set(names) & {'documents_update','outbox_send','tickets_create','tickets_transition'}, 'Write tool exposed'
            else:
                payload = result.get('structuredContent')
                assert isinstance(payload, dict), 'Missing structuredContent'
                if expect == 'mcp_denied':
                    assert result.get('isError') is True and payload.get('status') == 'denied', 'Expected policy denial'
                    assert payload.get('effect') == 'not_started', 'Denied call may have dispatched'
                else:
                    assert not result.get('isError') and payload.get('status') == 'succeeded', 'Tool did not succeed'
                    assert payload.get('operation_id'), 'Missing operation ID'
                    if expect == 'mcp_redacted':
                        assert payload.get('disclosure') == 'redacted', 'Expected redaction'
        else:
            allowed = {'unauthorized': [401], 'invalid': [400,422], 'denied': [403],
                       'too_large': [413], 'limited': [429], 'unavailable': [502,503], 'deadline': [408,504]}
            assert code in allowed[expect], f'Expected {allowed[expect]}, got {code}'
            assert data.get('error'), 'Missing error envelope'
            # Require OpenAI-shaped errors on the planned model endpoint.
            assert isinstance(data['error'], dict) and data['error'].get('message'), 'Expected structured error.message'
    for value in c.get('forbidden', []):
        inspected = json.dumps(json.loads(raw), ensure_ascii=False) if not expect.startswith('stream') else raw
        assert value not in inspected, 'Sensitive canary in client body'
    return 'OBSERVED', 'Client assertions passed; independent Gate evidence still required'


def check_result(identifier, folder, code, curl_exit):
    p = Path(folder)
    c = case(identifier)
    if int(curl_exit):
        status, reason = 'BLOCKED', f'Client transport failed (curl {curl_exit}); no policy conclusion'
    else:
        try:
            status, reason = validate(c, int(code), (p / 'response.body').read_text())
        except (AssertionError, ValueError, KeyError, TypeError) as exc:
            status, reason = 'FAIL', str(exc)
    dump({'case':identifier,'status':status,'reason':reason,'http_status':int(code or 0),
          'profile':c['profile'],'required_evidence':c['evidence']}, p / 'result.json')
    print(f'{identifier}: {status} — {reason}')
    return 1 if status == 'FAIL' else (2 if status == 'BLOCKED' else 0)


def check_files():
    ids = set()
    for c in CASES:
        assert c['id'] not in ids
        ids.add(c['id'])
        assert c['profile'] and c['evidence']
        if c['group'] != 'mcp':
            data = json.loads((HERE / c['request']).read_text())
            assert data['store'] is False and data['max_output_tokens'] <= 4096
            assert 'api_key' not in data and 'Authorization' not in data
    print(f'{len(CASES)} fixtures valid; no requests sent; this is not a live compatibility test')


def select(kind, value):
    selected = [c for c in CASES if kind == 'all' or c.get(kind) == value]
    if not selected:
        raise ValueError('No matching scenarios')
    for c in selected:
        print(c['id'])


def summary(folder):
    results = [json.loads(p.read_text()) for p in sorted(Path(folder).glob('*/result.json'))]
    totals = {s:sum(r['status'] == s for r in results) for s in ('OBSERVED','FAIL','BLOCKED')}
    dump({'results':results,'totals':totals,'security_verified':False},Path(folder)/'summary.json')
    print(json.dumps(totals))
    return 1 if totals['FAIL'] else (2 if totals['BLOCKED'] else 3)


def main():
    cmd, *a = sys.argv[1:]
    if cmd == 'check': check_files()
    elif cmd == 'list':
        for c in CASES: print(f"{c['id']:4} {c['group']:12} {c['profile']:23} {c['title']}")
    elif cmd == 'select': select(*a)
    elif cmd == 'field':
        c = case(a[0]); print(c.get(a[1], a[2] if len(a)>2 else ''))
    elif cmd == 'auth': auth(*a)
    elif cmd == 'prepare': prepare(*a)
    elif cmd == 'validate': return check_result(*a)
    elif cmd == 'summary': return summary(*a)
    else: raise ValueError(f'Unknown command {cmd}')
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, KeyError, StopIteration, AssertionError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(2)
