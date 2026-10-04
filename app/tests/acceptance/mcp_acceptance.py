"""Acceptance driver for the MCP slice: runs inside the stack and prints machine-readable evidence.

It talks to the Gate exactly like a customer client does — one endpoint, transport identity headers,
one operation key per logical request — and it never touches a dummy service directly for a business
effect. Phases that need a fault rule, a container restart or a policy activation are sequenced by
``scripts/demo-mcp-test.sh`` on the host, which calls the phases below in order and collects their
JSON output.

    docker compose exec -T gate-mcp python tests/acceptance/mcp_acceptance.py --phase p

Every check prints ``{"phase": ..., "checks": [{"id": ..., "ok": ..., "detail": ...}], "passed": n}``.
"""
import argparse
import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from demo_client.cli import Client, _credentials  # noqa: E402

ENDPOINT = os.environ.get('DEMO_MCP_ENDPOINT', 'http://127.0.0.1/mcp')


class Checks:
    def __init__(self, phase):
        self.phase = phase
        self.checks = []

    def check(self, identifier, ok, detail=None):
        self.checks.append({'id': identifier, 'ok': bool(ok), 'detail': detail})
        return ok

    def record(self, identifier, condition, detail=None):
        return self.check(identifier, condition, detail)

    def payload(self, extra=None, **kwargs):
        failed = [row['id'] for row in self.checks if not row['ok']]
        return {'phase': self.phase, 'checks': self.checks, 'failed': failed,
                'passed': len(self.checks) - len(failed), **(extra or {}), **kwargs}


def client(principal):
    return Client(ENDPOINT, principal, _credentials(principal, os.environ))


MAX_THROTTLE_RETRIES = 15


def call(principal, tool, arguments, *, key=None, meta=None, retry_throttled=True):
    """One client call.

    The demonstrated policy throttles an agent at 30 calls per minute. That refusal is explicit and
    carries a retry hint, so the harness waits for the hint and retries a bounded number of times
    instead of turning a correct refusal into a failed check. The retry keeps the same operation key,
    which is exactly how a client is supposed to behave.
    """
    attempts = 0
    while True:
        response = asyncio.run(client(principal).call(tool, arguments, operation_key=key, meta=meta))
        result = response.get('result') or {}
        code = (result.get('error') or {}).get('code')
        if not retry_throttled or code != 'policy_throttled' or attempts >= MAX_THROTTLE_RETRIES:
            return response
        attempts += 1
        # The demonstrated limit is a sliding minute window, so waiting out a fixed hint is not
        # enough: the harness retries until the window drains or the bounded attempts run out.
        time.sleep(2.0)


def tools(principal):
    return asyncio.run(client(principal).list_tools())


def result_of(response):
    return response.get('result') or {}


def protocol_error(principal, tool, arguments, *, key='probe-1'):
    """Return a description of how a call was refused, or None if it was executed.

    A protocol refusal raises; a policy or service refusal comes back as an error result. Both are
    reported here so a check can distinguish "refused" from "executed" without caring which layer
    refused.
    """
    try:
        response = call(principal, tool, arguments, key=key)
    except Exception as exc:  # noqa: BLE001 - the refusal itself is the observation
        return f'{type(exc).__name__}: {exc}'
    if response.get('isError'):
        code = (result_of(response).get('error') or {}).get('code')
        return f'tool result refused: {code}'
    return None


# ---------------------------------------------------------------------------------------
# P — protocol, identity and catalog
# ---------------------------------------------------------------------------------------
def phase_p(checks):
    support = tools('support-agent')
    names = sorted(tool['name'] for tool in support)
    checks.record('P01-catalog-multiple-services',
                  {'documents_read', 'documents_search', 'outbox_send', 'outbox_list'} <= set(names),
                  f'support-agent catalog: {names}')
    read = call('support-agent', 'documents_read', {'doc_id': 'KB-1042'}, key='acc-p01-read')
    checks.record('P01-real-call', result_of(read).get('status') == 'succeeded',
                  f"status={result_of(read).get('status')} receipt={result_of(read).get('receipt_id')}")
    checks.record('P01-core-fields',
                  all(result_of(read).get(field) is not None
                      for field in ('operation_id', 'receipt_id', 'decision', 'effect',
                                    'disclosure')),
                  {field: result_of(read).get(field)
                   for field in ('operation_id', 'receipt_id', 'decision', 'effect', 'disclosure')})

    observer = sorted(tool['name'] for tool in tools('observer-agent'))
    checks.record('P02-different-catalogs', 'documents_update' not in observer,
                  f'observer-agent catalog: {observer}')
    hidden = protocol_error('observer-agent', 'documents_update',
                            {'doc_id': 'KB-1042', 'content': 'x', 'expected_version': 1},
                            key='acc-p02-hidden')
    checks.record('P02-hidden-tool-not-dispatched',
                  hidden is not None and 'unknown' in hidden.lower(), hidden)
    unknown = protocol_error('support-agent', 'not_a_tool_at_all', {}, key='acc-p02-unknown')
    checks.record('P02-unknown-tool-same-shape',
                  unknown is not None and 'unknown' in unknown.lower(), unknown)

    request = urllib.request.Request(
        ENDPOINT, data=b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
        headers={'Content-Type': 'application/json',
                 'X-Action-Gate-Principal': 'support-agent',
                 'X-Action-Gate-Token': 'definitely-not-the-token'})
    try:
        urllib.request.urlopen(request, timeout=5)
        checks.check('P03-bad-credential-refused', False, 'the endpoint answered 200')
    except urllib.error.HTTPError as exc:
        checks.check('P03-bad-credential-refused', exc.code == 401, f'HTTP {exc.code}')
    except Exception as exc:  # noqa: BLE001
        checks.check('P03-bad-credential-refused', False, type(exc).__name__)

    for tool, arguments in (('documents_read', {'doc_id': 42}),
                            ('documents_read', {'doc_id': 'KB-1042', 'extra': True}),
                            ('documents_search', {'query': 'policy', 'limit': 0}),
                            ('documents_search', {'query': 'policy', 'limit': '2'})):
        failure = protocol_error('support-agent', tool, arguments, key=f'acc-p05-{tool}-{len(str(arguments))}')
        checks.check(f'P05-schema-{tool}-{sorted(arguments)}', failure is not None,
                     (failure or 'accepted')[:160])

    restricted = call('observer-agent', 'documents_read', {'doc_id': 'KB-RESTRICTED-01'},
                      key='acc-p06-restricted')
    detail = result_of(restricted)
    checks.record('P06-restricted-read-blocked',
                  detail.get('status') == 'denied' and detail.get('effect') == 'not_started',
                  f"status={detail.get('status')} effect={detail.get('effect')}")
    search = result_of(call('observer-agent', 'documents_search', {'query': 'restricted'},
                            key='acc-p06-search'))
    identifiers = [row['doc_id'] for row in search.get('results', [])]
    checks.record('P06-search-does-not-leak',
                  'KB-RESTRICTED-01' not in identifiers,
                  f'search results: {identifiers} filtered={search.get("filtered_count")}')
    return checks.payload()


# ---------------------------------------------------------------------------------------
# D — documents
# ---------------------------------------------------------------------------------------
def phase_d(checks):
    before = result_of(call('support-agent', 'documents_read', {'doc_id': 'KB-1042'},
                            key=f'acc-d02-read-{os.urandom(4).hex()}'))
    blocked = result_of(call('support-agent', 'documents_update',
                             {'doc_id': 'KB-1042', 'content': 'Synthetic acceptance rewrite.',
                              'expected_version': before.get('version')},
                             key=f'acc-d02-{os.urandom(4).hex()}'))
    checks.record('D02-update-blocked-before-the-change',
                  blocked.get('status') == 'denied' and blocked.get('effect') == 'not_started',
                  f"status={blocked.get('status')} decision={blocked.get('decision')}")
    after = result_of(call('support-agent', 'documents_read', {'doc_id': 'KB-1042'},
                           key=f'acc-d02-read2-{os.urandom(4).hex()}'))
    checks.record('D02-content-unchanged',
                  after.get('version') == before.get('version')
                  and after.get('content') == before.get('content'),
                  f"version was {before.get('version')}, is {after.get('version')}")

    protected = result_of(call('support-agent', 'documents_update',
                               {'doc_id': 'KB-9000', 'content': 'Synthetic rewrite.',
                                'expected_version': 1}, key=f'acc-d02b-{os.urandom(4).hex()}'))
    checks.record('D02-protected-document-blocked',
                  protected.get('status') == 'denied', f"status={protected.get('status')}")
    return checks.payload()


def phase_d_after_change(checks):
    """Runs after the operator policy change: the same call is now permitted for one document."""
    before = result_of(call('support-agent', 'documents_read', {'doc_id': 'KB-1042'},
                            key=f'acc-d01-read-{os.urandom(4).hex()}'))
    version = before.get('version')
    key = f'acc-d01-update-{os.urandom(4).hex()}'
    updated = result_of(call('support-agent', 'documents_update',
                             {'doc_id': 'KB-1042', 'content': 'Synthetic acceptance rewrite.',
                              'expected_version': version}, key=key))
    checks.record('D01-update-allowed-after-change',
                  updated.get('status') == 'succeeded' and updated.get('version') == version + 1,
                  f"status={updated.get('status')} version={updated.get('version')} "
                  f"receipt={updated.get('receipt_id')}")
    after = result_of(call('support-agent', 'documents_read', {'doc_id': 'KB-1042'},
                           key=f'acc-d01-read2-{os.urandom(4).hex()}'))
    checks.record('D01-content-and-version-persisted',
                  after.get('content') == 'Synthetic acceptance rewrite.'
                  and after.get('version') == version + 1,
                  f"version={after.get('version')}")

    stale = result_of(call('support-agent', 'documents_update',
                           {'doc_id': 'KB-1042', 'content': 'Second synthetic rewrite.',
                            'expected_version': version},
                           key=f'acc-d03-stale-{os.urandom(4).hex()}'))
    checks.record('D03-second-update-with-a-stale-version-fails',
                  stale.get('status') == 'failed' and stale.get('effect') == 'no_effect',
                  f"status={stale.get('status')} error={(stale.get('error') or {}).get('code')}")

    still_protected = result_of(call('support-agent', 'documents_update',
                                     {'doc_id': 'KB-9000', 'content': 'Synthetic rewrite.',
                                      'expected_version': 1},
                                     key=f'acc-d01-protected-{os.urandom(4).hex()}'))
    checks.record('D02-protected-document-still-blocked',
                  still_protected.get('status') == 'denied',
                  f"status={still_protected.get('status')}")
    observer = result_of(call('observer-agent', 'documents_search', {'query': 'two-factor'},
                              key=f'acc-d01-observer-{os.urandom(4).hex()}'))
    checks.record('D02-second-principal-gets-no-write',
                  'documents_update' not in [tool['name'] for tool in tools('observer-agent')],
                  f"observer search status={observer.get('status')}")
    return checks.payload()


# ---------------------------------------------------------------------------------------
# O — outbox
# ---------------------------------------------------------------------------------------
def phase_o(checks):
    internal = result_of(call('support-agent', 'outbox_send',
                              {'to': 'colleague@acme.example', 'subject': 'Acceptance summary',
                               'body': 'Synthetic acceptance summary.'},
                              key=f'acc-o01-in-{os.urandom(4).hex()}'))
    checks.record('O01-internal-recipient-stored',
                  internal.get('status') == 'succeeded' and internal.get('message_id'),
                  f"status={internal.get('status')} message={internal.get('message_id')}")

    external = result_of(call('support-agent', 'outbox_send',
                              {'to': 'recipient@external.example', 'subject': 'Acceptance summary',
                               'body': 'Synthetic acceptance summary.'},
                              key=f'acc-o01-out-{os.urandom(4).hex()}'))
    checks.record('O01-external-recipient-refused',
                  external.get('status') == 'denied' and external.get('effect') == 'not_started',
                  f"status={external.get('status')} decision={external.get('decision')}")

    spoofed = result_of(call('support-agent', 'outbox_send',
                             {'to': 'agent@acme.example.attacker.example', 'subject': 'S',
                              'body': 'B'}, key=f'acc-o02-spoof-{os.urandom(4).hex()}'))
    checks.record('O02-lookalike-domain-refused', spoofed.get('status') == 'denied',
                  f"status={spoofed.get('status')}")
    injected = result_of(call('support-agent', 'outbox_send',
                              {'to': 'agent@acme.example\r\nBcc: leak@external.example',
                               'subject': 'S', 'body': 'B'},
                              key=f'acc-o02-crlf-{os.urandom(4).hex()}'))
    checks.record('O02-crlf-refused', injected.get('status') in ('denied', 'failed'),
                  f"status={injected.get('status')} "
                  f"error={(injected.get('error') or {}).get('code')}")

    redacted = result_of(call('support-agent', 'outbox_send',
                              {'to': 'colleague@acme.example', 'subject': 'PII check',
                               'body': 'Escalation contact anna.kowalska@acme.example.'},
                              key=f'acc-o03-{os.urandom(4).hex()}'))
    stored = result_of(call('support-agent', 'outbox_get',
                            {'message_id': redacted.get('message_id')},
                            key=f'acc-o03-get-{os.urandom(4).hex()}')) \
        if redacted.get('message_id') else {}
    # The routing decision used the parsed domain of the real argument; the address in the returned
    # receipt is itself subject to output controls, so the exact recipient is verified on the service
    # side by scripts/demo-mcp-test.sh, which reads the stored row over a read-only connection.
    checks.record('O04-recipient-rule-and-field-scope',
                  redacted.get('status') == 'succeeded'
                  and redacted.get('to') in ('colleague@acme.example', '[EMAIL]'),
                  f"to={redacted.get('to')!r} (service-side value checked by the host script)")
    checks.record('O03-content-redacted-before-dispatch',
                  stored.get('status') == 'succeeded'
                  and '[REDACTED: EMAIL]' in stored.get('body', '')
                  and 'anna.kowalska@acme.example' not in json.dumps(stored),
                  f"stored body={stored.get('body')!r}")

    messages = result_of(call('support-agent', 'outbox_list', {'limit': 5},
                              key=f'acc-o04-list-{os.urandom(4).hex()}'))
    checks.record('O04-list-has-no-bodies',
                  'body' not in json.dumps(messages),
                  f"listed={messages.get('count')}")
    foreign = result_of(call('observer-agent', 'outbox_get',
                             {'message_id': internal.get('message_id') or 'MSG-NONE'},
                             key=f'acc-o04-foreign-{os.urandom(4).hex()}'))
    checks.record('P06-foreign-message-not-readable',
                  foreign.get('status') in ('denied', 'failed'),
                  f"status={foreign.get('status')} "
                  f"error={(foreign.get('error') or {}).get('code')}")
    return checks.payload()


# ---------------------------------------------------------------------------------------
# T — tickets (optional third service)
# ---------------------------------------------------------------------------------------
def phase_t(checks):
    catalog = [tool['name'] for tool in tools('support-agent')]
    if 'tickets_transition' not in catalog:
        checks.check('T-skipped', True, 'the tickets service is not running in this compose project')
        return checks.payload()
    created = result_of(call('support-agent', 'tickets_create',
                             {'title': 'Acceptance ticket', 'description': 'Synthetic acceptance case.'},
                             key=f'acc-t01-create-{os.urandom(4).hex()}'))
    ticket = created.get('ticket_id')
    checks.record('T01-create-ticket', created.get('status') == 'succeeded'
                  and created.get('ticket_status') == 'open' and created.get('version') == 1,
                  f"status={created.get('status')} ticket={ticket}")
    first = result_of(call('support-agent', 'tickets_transition',
                           {'ticket_id': ticket, 'target_status': 'in_progress',
                            'expected_version': 1}, key=f'acc-t01-{os.urandom(4).hex()}'))
    checks.record('T01-allowed-transition', first.get('status') == 'succeeded'
                  and first.get('version') == 2,
                  f"status={first.get('status')} ticket_status={first.get('ticket_status')} "
                  f"version={first.get('version')}")
    resolved = result_of(call('support-agent', 'tickets_transition',
                              {'ticket_id': ticket, 'target_status': 'resolved',
                               'expected_version': 2}, key=f'acc-t02-{os.urandom(4).hex()}'))
    checks.record('T02-policy-refusal-has-no-dispatch',
                  resolved.get('status') == 'denied' and resolved.get('effect') == 'not_started',
                  f"status={resolved.get('status')} decision={resolved.get('decision')}")
    business = result_of(call('operator-local', 'tickets_transition',
                              {'ticket_id': 'T-9000', 'target_status': 'resolved',
                               'expected_version': 1}, key=f'acc-t02b-{os.urandom(4).hex()}'))
    checks.record('T02-business-refusal-after-dispatch',
                  business.get('status') == 'failed'
                  and (business.get('error') or {}).get('code') == 'business_transition_invalid',
                  f"status={business.get('status')} "
                  f"error={(business.get('error') or {}).get('code')}")
    return checks.payload()


# ---------------------------------------------------------------------------------------
# R — idempotency, unknown outcome and reconciliation
# ---------------------------------------------------------------------------------------
def phase_r(checks):
    key = f'acc-r01-{os.urandom(4).hex()}'
    arguments = {'to': 'colleague@acme.example', 'subject': 'Idempotency check',
                 'body': 'Synthetic idempotency check.'}
    first = result_of(call('support-agent', 'outbox_send', arguments, key=key))
    replay = result_of(call('support-agent', 'outbox_send', arguments, key=key))
    checks.record('R01-repeat-returns-the-same-receipt',
                  first.get('receipt_id') and replay.get('receipt_id') == first.get('receipt_id')
                  and replay.get('replayed') is True,
                  f"first={first.get('receipt_id')} replay={replay.get('receipt_id')}")
    conflict = result_of(call('support-agent', 'outbox_send',
                              dict(arguments, body='Different synthetic body.'), key=key))
    checks.record('R01-same-key-other-payload-conflicts',
                  (conflict.get('error') or {}).get('code') == 'idempotency_conflict',
                  f"status={conflict.get('status')} "
                  f"error={(conflict.get('error') or {}).get('code')}")
    return checks.payload(operationKey=key, receiptId=first.get('receipt_id'),
                          operationId=first.get('operation_id'),
                          serviceOperationId=first.get('service_operation_id'))


def phase_unknown(checks, key=None):
    """Runs against a service that currently holds the response past the Gate deadline."""
    key = key or f'acc-r02-{os.urandom(4).hex()}'
    arguments = {'to': 'colleague@acme.example', 'subject': 'Lost response',
                 'body': 'Synthetic lost-response check.'}
    outcome = result_of(call('support-agent', 'outbox_send', arguments, key=key))
    checks.record('R02-lost-response-is-unknown',
                  outcome.get('status') == 'outcome_unknown' and outcome.get('effect') == 'unknown',
                  f"status={outcome.get('status')} operation={outcome.get('operation_id')}")
    repeat = result_of(call('support-agent', 'outbox_send', arguments, key=key))
    checks.record('R02-repeat-does-not-dispatch-again',
                  repeat.get('status') == 'outcome_unknown',
                  f"status={repeat.get('status')}")
    from action_gate.mcp_ops import McpOperator
    row = McpOperator().operations.get(outcome.get('operation_id')) or {}
    return checks.payload(operationKey=key, operationId=outcome.get('operation_id'),
                          serviceOperationId=row.get('upstream_operation_id'))


def phase_reconciled(checks, operation_id):
    status = json.loads(_run(['python', '-m', 'action_gate.mcp_ops', 'status',
                              '--operation-id', operation_id]))
    row = status.get('operation') or {}
    checks.record('R02-reconcile-found-the-receipt',
                  row.get('status') == 'succeeded' and row.get('receipt_id'),
                  f"status={row.get('status')} receipt={row.get('receipt_id')} "
                  f"disclosure={row.get('disclosure')}")
    return checks.payload(operationId=operation_id, row=row)


def _run(command):
    import subprocess
    return subprocess.run(command, capture_output=True, text=True, check=True).stdout


def phase_f(checks):
    response = call('support-agent', 'documents_read', {'doc_id': 'KB-PII-01'},
                    key=f'acc-f01-{os.urandom(4).hex()}')
    pii = result_of(response)
    encoded = json.dumps(response)
    checks.record('F01-output-redacted-in-every-representation',
                  pii.get('disclosure') == 'redacted'
                  and json.loads(response['text']) == pii
                  and 'anna.kowalska@acme.example' not in encoded
                  and '[EMAIL]' in encoded,
                  f"disclosure={pii.get('disclosure')} content={pii.get('content')!r}")
    adversarial = result_of(call('support-agent', 'documents_read', {'doc_id': 'KB-INJECT-01'},
                                 key=f'acc-f01b-{os.urandom(4).hex()}'))
    checks.record('F02-adversarial-output-withheld-after-commit',
                  adversarial.get('status') == 'succeeded'
                  and adversarial.get('disclosure') == 'withheld'
                  and 'IGNORE ALL PREVIOUS INSTRUCTIONS' not in json.dumps(adversarial),
                  f"status={adversarial.get('status')} disclosure={adversarial.get('disclosure')}")
    return checks.payload()


def phase_f2(checks):
    """Runs after the malformed-result fault: the effect happened, the content is not disclosed."""
    response = call('support-agent', 'documents_read', {'doc_id': 'KB-1042'},
                    key=f'acc-f02-malformed-{os.urandom(8).hex()}')
    candidate = result_of(response)
    checks.record('F02-malformed-result-withheld-after-commit',
                  candidate.get('status') == 'succeeded'
                  and candidate.get('effect') == 'succeeded'
                  and candidate.get('disclosure') == 'withheld'
                  and 'published schema' in candidate.get('reason', '')
                  and 'unexpected_field' not in json.dumps(response), candidate)
    from action_gate.mcp_ops import McpOperator
    row = McpOperator().operations.get(candidate.get('operation_id')) or {}
    return checks.payload(operation=candidate, operationId=candidate.get('operation_id'),
                          serviceOperationId=row.get('upstream_operation_id'))


def phase_audit(checks, operation_id):
    from action_gate.mcp_ops import McpOperator
    operator = McpOperator()
    row = operator.operations.get(operation_id)
    with operator.operations._cursor() as cursor:
        cursor.execute('SELECT operation_id, receipt_id, effect_outcome '
                       'FROM mcp_audit_events WHERE operation_id = %s', (operation_id,))
        events = cursor.fetchall()
    checks.record('A01-audit-correlates-gate-and-service',
                  bool(row) and row.get('receipt_id') and row.get('status') == 'succeeded'
                  and any(str(event[0]) == operation_id and event[1] == row['receipt_id']
                          and event[2] == 'succeeded' for event in events),
                  f'operation={operation_id} row={ {k: row.get(k) for k in ("status", "receipt_id", "resource_id")} if row else None }')
    counters = operator.operations.counters()
    checks.record('A01-counters-visible', 'byStatus' in counters, counters)
    return checks.payload(operationId=operation_id, receiptId=row.get('receipt_id') if row else None)


def phase_b(checks):
    """B01: the call limit refuses before the upstream hop, and the refusal is explicit."""
    key = f'acc-b01-{os.urandom(4).hex()}'
    arguments = {'doc_id': 'KB-1042'}
    throttled = None
    for _ in range(40):
        response = call('support-agent', 'documents_read', arguments, key=None,
                        retry_throttled=False)
        result = response.get('result') or {}
        if (result.get('error') or {}).get('code') == 'policy_throttled':
            throttled = result
            break
    checks.record('B01-rate-limit-refuses-before-dispatch',
                  throttled is not None
                  and throttled.get('effect') == 'not_started'
                  and throttled.get('disclosure') == 'none',
                  f"status={throttled.get('status') if throttled else None} "
                  f"reason={(throttled or {}).get('reason')}")
    attempts_before = None
    return checks.payload(operationKey=key)


PHASES = {
    'p': phase_p,
    'b': phase_b,
    'd': phase_d,
    'd-after': phase_d_after_change,
    'o': phase_o,
    't': phase_t,
    'r': phase_r,
    'f': phase_f,
    'f2': phase_f2,
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='mcp_acceptance')
    parser.add_argument('--phase', required=True, choices=sorted(PHASES) + ['unknown', 'reconciled',
                                                                           'audit'],
                        help='which part of the acceptance matrix to run')
    parser.add_argument('--operation-id', default=None)
    parser.add_argument('--key', default=None)
    arguments = parser.parse_args(argv)
    checks = Checks(arguments.phase)
    if arguments.phase == 'unknown':
        payload = phase_unknown(checks, arguments.key)
    elif arguments.phase == 'reconciled':
        payload = phase_reconciled(checks, arguments.operation_id)
    elif arguments.phase == 'audit':
        payload = phase_audit(checks, arguments.operation_id)
    else:
        payload = PHASES[arguments.phase](checks)
    json.dump(payload, sys.stdout, indent=2, sort_keys=True, ensure_ascii=False, default=str)
    sys.stdout.write('\n')
    return 0 if not payload.get('failed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
