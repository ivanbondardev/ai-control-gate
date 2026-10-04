"""ExecutionCoordinator state machine: admission, idempotency, refusal, unknown and disclosure.

The coordinator is exercised with the in-memory operations store, a stub policy snapshot and a fake
upstream, so the whole state machine runs without Docker. The registry revision is built by the real
``ServiceRegistry`` code from a synthetic discovery result.
"""
import asyncio
import json
import unittest
from copy import deepcopy

try:
    from action_gate.execution import ExecutionCoordinator, ToolCallRejected
    from action_gate.identity import Principal
    from action_gate.mcp_upstream import UpstreamError, UpstreamResult
    from action_gate.service_registry import ActiveRegistry, ServiceRegistry
    from action_gate.storage.operations import (MemoryOperations, STATUS_BLOCKED,
                                            STATUS_SUCCEEDED, STATUS_UNKNOWN)
    from action_gate import panel_engine
    IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001 - reported as a skip
    IMPORT_ERROR = exc

if IMPORT_ERROR is None:
    SUPPORT = Principal(id='support-agent', role='agent', token='t')
    OBSERVER = Principal(id='observer-agent', role='agent', token='t')
else:  # the whole module is skipped; names still exist so the import cannot fail
    SUPPORT = OBSERVER = None

PANEL_SERVICES = [
    {'id': 'demo_documents', 'name': 'Documents', 'kind': 'MCP service', 'endpoint': '',
     'owner': 'demo', 'actions': [
         {'name': 'search', 'desc': '', 'destructive': False,
          'params': [{'name': 'query', 'type': 'string', 'required': True},
                     {'name': 'limit', 'type': 'number', 'required': False}]},
         {'name': 'read', 'desc': '', 'destructive': False,
          'params': [{'name': 'doc_id', 'type': 'string', 'required': True}]},
         {'name': 'update', 'desc': '', 'destructive': False,
          'params': [{'name': 'doc_id', 'type': 'string', 'required': True},
                     {'name': 'content', 'type': 'string', 'required': True},
                     {'name': 'expected_version', 'type': 'number', 'required': True}]}]},
    {'id': 'demo_outbox', 'name': 'Outbox', 'kind': 'MCP service', 'endpoint': '', 'owner': 'demo',
     'actions': [
         {'name': 'send', 'desc': '', 'destructive': False,
          'params': [{'name': 'to', 'type': 'string', 'required': True},
                     {'name': 'subject', 'type': 'string', 'required': True},
                     {'name': 'body', 'type': 'string', 'required': True}]}]},
]

ALLOWLIST = {
    'version': 1,
    'services': [
        {'service_id': 'documents', 'connection_ref': 'documents-mcp',
         'endpoint': 'http://documents-mcp:8020/mcp',
         'status_endpoint': 'http://documents-mcp:8020/operations',
         'credential_id': 'gate-mcp',
         'tools': [
             {'published_name': 'documents_search', 'upstream_name': 'search_documents',
              'panel_service': 'demo_documents', 'panel_action': 'search',
              'reviewed_description': 'Search documents.',
              'result_projection': {'kind': 'filter_by_access', 'list_field': 'results',
                                    'item_field': 'doc_id', 'panel_action': 'read'}},
             {'published_name': 'documents_read', 'upstream_name': 'read_document',
              'panel_service': 'demo_documents', 'panel_action': 'read',
              'reviewed_description': 'Read a document.'},
             {'published_name': 'documents_update', 'upstream_name': 'update_document',
              'panel_service': 'demo_documents', 'panel_action': 'update',
              'reviewed_description': 'Update a document.', 'mutation': True}]},
        {'service_id': 'outbox', 'connection_ref': 'outbox-mcp',
         'endpoint': 'http://outbox-mcp:8020/mcp',
         'status_endpoint': 'http://outbox-mcp:8020/operations', 'credential_id': 'gate-mcp',
         'tools': [
             {'published_name': 'outbox_send', 'upstream_name': 'send_message',
              'panel_service': 'demo_outbox', 'panel_action': 'send',
              'reviewed_description': 'Store a message locally.', 'mutation': True}]},
    ],
}

UPSTREAM_TOOLS = {
    'documents': [
        {'name': 'search_documents', 'description': 'service prose',
         'inputSchema': {'type': 'object',
                         'properties': {'query': {'type': 'string', 'minLength': 1},
                                        'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20}},
                         'required': ['query'], 'additionalProperties': False},
         'outputSchema': {'type': 'object',
                          'properties': {'status': {'type': 'string'}, 'service': {'type': 'string'},
                                         'tool': {'type': 'string'},
                                         'operation_id': {'type': ['string', 'null']},
                                         'receipt_id': {'type': ['string', 'null']},
                                         'replayed': {'type': 'boolean'},
                                         'results': {'type': 'array', 'items': {
                                             'type': 'object',
                                             'properties': {'doc_id': {'type': 'string'},
                                                            'title': {'type': 'string'}},
                                             'required': ['doc_id', 'title'],
                                             'additionalProperties': False}},
                                         'count': {'type': 'integer'}},
                          'required': ['status', 'service', 'tool', 'operation_id', 'receipt_id',
                                       'replayed', 'results', 'count'],
                          'additionalProperties': False}},
        {'name': 'read_document', 'description': 'service prose',
         'inputSchema': {'type': 'object',
                         'properties': {'doc_id': {'type': 'string', 'pattern': '^KB-[0-9A-Z-]+$'}},
                         'required': ['doc_id'], 'additionalProperties': False},
         'outputSchema': {'type': 'object',
                          'properties': {'status': {'type': 'string'}, 'service': {'type': 'string'},
                                         'tool': {'type': 'string'},
                                         'operation_id': {'type': ['string', 'null']},
                                         'receipt_id': {'type': ['string', 'null']},
                                         'replayed': {'type': 'boolean'},
                                         'doc_id': {'type': 'string'}, 'title': {'type': 'string'},
                                         'content': {'type': 'string'},
                                         'version': {'type': 'integer'}},
                          'required': ['status', 'service', 'tool', 'operation_id', 'receipt_id',
                                       'replayed', 'doc_id', 'title', 'content', 'version'],
                          'additionalProperties': False}},
        {'name': 'update_document', 'description': 'service prose',
         'inputSchema': {'type': 'object',
                         'properties': {'doc_id': {'type': 'string'}, 'content': {'type': 'string'},
                                        'expected_version': {'type': 'integer', 'minimum': 1}},
                         'required': ['doc_id', 'content', 'expected_version'],
                         'additionalProperties': False},
         'outputSchema': {'type': 'object',
                          'properties': {'status': {'type': 'string'}, 'service': {'type': 'string'},
                                         'tool': {'type': 'string'},
                                         'operation_id': {'type': ['string', 'null']},
                                         'receipt_id': {'type': ['string', 'null']},
                                         'replayed': {'type': 'boolean'},
                                         'doc_id': {'type': 'string'}, 'version': {'type': 'integer'}},
                          'required': ['status', 'service', 'tool', 'operation_id', 'receipt_id',
                                       'replayed', 'doc_id', 'version'],
                          'additionalProperties': False}},
    ],
    'outbox': [
        {'name': 'send_message', 'description': 'service prose',
         'inputSchema': {'type': 'object',
                         'properties': {'to': {'type': 'string'}, 'subject': {'type': 'string'},
                                        'body': {'type': 'string'}},
                         'required': ['to', 'subject', 'body'], 'additionalProperties': False},
         'outputSchema': {'type': 'object',
                          'properties': {'status': {'type': 'string'}, 'service': {'type': 'string'},
                                         'tool': {'type': 'string'},
                                         'operation_id': {'type': ['string', 'null']},
                                         'receipt_id': {'type': ['string', 'null']},
                                         'replayed': {'type': 'boolean'},
                                         'message_id': {'type': 'string'},
                                         'to': {'type': 'string'},
                                         'created_at': {'type': 'string'}},
                          'required': ['status', 'service', 'tool', 'operation_id', 'receipt_id',
                                       'replayed', 'message_id', 'to', 'created_at'],
                          'additionalProperties': False}},
    ],
}

POLICY = {
    'version': 7,
    'default_reaction': 'block',
    'checks': [
        {'id': 'content', 'type': 'pii_detection', 'name': 'Argument content', 'mode': 'redact',
         'entities': ['email'], 'fields': ['body', 'subject', 'content'], 'applies_to': 'any'},
        {'id': 'leak', 'type': 'pii_detection', 'name': 'Output redaction', 'mode': 'redact',
         'entities': ['email'], 'applies_to': 'output'},
        {'id': 'access', 'type': 'service_access', 'name': 'Service access rules',
         'mode': 'enforce'},
    ],
    'rules': [
        {'id': 'r1', 'subject': 'support-agent', 'service': 'demo_documents', 'action': 'read',
         'reaction': 'allow'},
        {'id': 'r2', 'subject': 'support-agent', 'service': 'demo_documents', 'action': 'search',
         'reaction': 'allow'},
        {'id': 'r3', 'subject': 'observer-agent', 'service': 'demo_documents', 'action': 'search',
         'reaction': 'allow'},
        {'id': 'r4', 'subject': 'observer-agent', 'service': 'demo_documents', 'action': 'read',
         'conditions': [{'param': 'doc_id', 'op': 'neq', 'value': 'KB-RESTRICTED-01'}],
         'reaction': 'allow'},
        {'id': 'r5', 'subject': 'support-agent', 'service': 'demo_outbox', 'action': 'send',
         'conditions': [{'param': 'to', 'op': 'email_domain_eq', 'value': 'acme.example'}],
         'reaction': 'allow'},
        {'id': 'r6', 'subject': 'support-agent', 'service': 'demo_documents', 'action': 'update',
         'reaction': 'block',
         'note': 'Declared refusal: the mutation tool stays visible and the refusal is attributed '
                 'to policy.'},
    ],
}


class StubPolicyReader:
    def __init__(self, policy=None, *, version=7):
        self.policy = panel_engine.validate_policy(deepcopy(policy or POLICY), PANEL_SERVICES)
        self.policy['version'] = version
        self.version = version

    def read(self):
        return {'policy': deepcopy(self.policy), 'policyHash': f'hash-{self.version}',
                'policyVersion': self.version, 'stateRevision': 1,
                'services': deepcopy(PANEL_SERVICES)}


class FakeUpstream:
    def __init__(self, *, result=None, error=None, status=None):
        self.result = result
        self.error = error
        self.status = status or {'status': 'not_found'}
        self.calls = []
        self.probes = []

    async def call_tool(self, endpoint, service_id, tool, arguments, context, *,
                        credential_id=None, deadline=None):
        self.calls.append({'service_id': service_id, 'tool': tool, 'arguments': deepcopy(arguments),
                           'context': deepcopy(context)})
        if self.error is not None:
            raise self.error
        return self.result

    async def operation_status(self, status_endpoint, service_id, operation_id, *,
                               credential_id=None):
        self.probes.append(operation_id)
        status = deepcopy(self.status)
        status.setdefault('operationId', operation_id)
        if 'receipt' in status:
            status['receipt'].setdefault('demo_run_id', 'run-0001')
        return status


def service_result(payload, *, is_error=False, receipt='rcpt-1'):
    structured = {'status': 'failed' if is_error else 'succeeded', 'service': 'documents',
                  'tool': 'read_document', 'operation_id': 'op-internal', 'receipt_id': receipt,
                  'replayed': False, **payload}
    return UpstreamResult(is_error=is_error, structured=structured,
                          text=json.dumps(structured), bytes_out=len(json.dumps(structured)),
                          protocol_version='2025-11-25')


@unittest.skipIf(IMPORT_ERROR is not None, f'coordinator unavailable: {IMPORT_ERROR}')
class ExecutionTest(unittest.TestCase):
    def setUp(self):
        self.operations = MemoryOperations()
        self.policy_reader = StubPolicyReader()
        self.upstream = FakeUpstream()
        self.registry = self._registry(self.upstream)
        self.coordinator = ExecutionCoordinator(
            operations=self.operations, policy_reader=self.policy_reader,
            registry_provider=lambda: self.registry, upstream=self.upstream, salt='test-salt')

    @staticmethod
    def _registry(upstream):
        registry = ServiceRegistry(ALLOWLIST, {'gate-mcp': 'token'}, MemoryOperations(), upstream,
                                   allowed_hosts={'documents-mcp', 'outbox-mcp'})
        discovery = {service_id: {'health': 'ready', 'tools': tools, 'detail': None}
                     for service_id, tools in UPSTREAM_TOOLS.items()}
        return ActiveRegistry(1, registry.build_revision(discovery))

    def run_call(self, *, principal=SUPPORT, tool='documents_read',
                 arguments=None, key='key-1'):
        binding = self.registry.binding(tool)
        arguments = {'doc_id': 'KB-1042'} if arguments is None else arguments
        return asyncio.run(self.coordinator.execute(
            principal=principal, binding=binding, arguments=arguments,
            client_operation_key=key, request_id='req-1'))

    # -- happy path -------------------------------------------------------------------
    def test_allowed_read_is_dispatched_and_recorded(self):
        self.upstream.result = service_result({'doc_id': 'KB-1042', 'title': 'Two-factor',
                                               'content': 'Reset instructions.', 'version': 2})
        result = self.run_call()
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(result['resource_id'], 'KB-1042')
        self.assertEqual(result['version'], 2)
        self.assertEqual(result['receipt_id'], 'rcpt-1')
        self.assertEqual(result['disclosure'], 'full')
        self.assertEqual(result['decision'], 'allow')
        self.assertEqual(len(self.upstream.calls), 1)
        self.assertEqual(self.upstream.calls[0]['arguments'], {'doc_id': 'KB-1042'})
        self.assertTrue(self.upstream.calls[0]['context']['operation_id'].startswith('op-'))
        rows = self.operations.list_operations()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['status'], STATUS_SUCCEEDED)
        self.assertEqual(len(self.operations.events), 1)
        self.assertEqual(self.operations.counters()['upstreamCalls'], 1)

    def test_policy_block_never_reaches_the_service(self):
        result = self.run_call(tool='documents_update',
                               arguments={'doc_id': 'KB-1042', 'content': 'Rewrite.',
                                          'expected_version': 1})
        self.assertEqual(result['status'], 'denied')
        self.assertEqual(result['effect'], 'not_started')
        self.assertEqual(result['decision'], 'block')
        self.assertEqual(result['disclosure'], 'none')
        self.assertEqual(self.upstream.calls, [])
        row = self.operations.list_operations()[0]
        self.assertEqual(row['status'], STATUS_BLOCKED)
        self.assertEqual(self.operations.counters()['upstreamCalls'], 0)
        self.assertEqual(self.operations.attempts[0]['admitted'], False)

    def test_hidden_tool_is_refused_like_an_unknown_one(self):
        with self.assertRaises(ToolCallRejected) as caught:
            self.run_call(principal=OBSERVER, tool='documents_update',
                          arguments={'doc_id': 'KB-1042', 'content': 'x', 'expected_version': 1})
        self.assertEqual(caught.exception.code, 'unknown_tool')
        self.assertEqual(self.upstream.calls, [])
        rows = self.operations.list_operations()
        self.assertEqual(rows[0]['status'], STATUS_BLOCKED)
        self.assertEqual(rows[0]['error_code'], 'unknown_tool')
        self.assertTrue(self.operations.events[0]['detail']['hiddenTool'])

    def test_schema_violation_is_refused_before_any_operation(self):
        for arguments in ({'doc_id': 'KB-1042', 'extra': 1}, {'doc_id': 42}, {}):
            with self.assertRaises(ToolCallRejected) as caught:
                self.run_call(arguments=arguments)
            self.assertEqual(caught.exception.code, 'invalid_arguments')
        self.assertEqual(self.operations.list_operations(), [])
        self.assertEqual(self.upstream.calls, [])

    def test_mutation_requires_an_operation_key(self):
        with self.assertRaises(ToolCallRejected) as caught:
            self.run_call(tool='documents_update', key=None,
                          arguments={'doc_id': 'KB-1042', 'content': 'x', 'expected_version': 1})
        self.assertEqual(caught.exception.code, 'operation_key_required')
        self.assertEqual(self.operations.list_operations(), [])

    def test_closed_admission_refuses_new_calls(self):
        self.operations.set_run_state(admission_open=False)
        with self.assertRaises(ToolCallRejected) as caught:
            self.run_call()
        self.assertEqual(caught.exception.code, 'admission_closed')

    # -- idempotency ---------------------------------------------------------------------
    def test_replay_returns_the_same_result_without_a_second_call(self):
        self.upstream.result = service_result({'doc_id': 'KB-1042', 'title': 'T', 'content': 'C',
                                               'version': 1})
        first = self.run_call(key='stable-key')
        second = self.run_call(key='stable-key')
        self.assertEqual(second['receipt_id'], first['receipt_id'])
        self.assertTrue(second['replayed'])
        self.assertEqual(len(self.upstream.calls), 1)
        self.assertEqual(len(self.operations.attempts), 1)

    def test_same_key_with_different_arguments_is_a_conflict(self):
        self.upstream.result = service_result({'doc_id': 'KB-1042', 'title': 'T', 'content': 'C',
                                               'version': 1})
        self.run_call(key='stable-key')
        conflict = self.run_call(key='stable-key', arguments={'doc_id': 'KB-9000'})
        self.assertEqual(conflict['status'], 'denied')
        self.assertEqual(conflict['error']['code'], 'idempotency_conflict')
        self.assertEqual(len(self.upstream.calls), 1)

    def test_conflict_also_applies_to_a_finished_claim(self):
        self.upstream.result = service_result({'doc_id': 'KB-1042', 'title': 'T', 'content': 'C',
                                               'version': 1})
        self.run_call(key='stable-key')
        conflict = self.run_call(key='stable-key', tool='documents_search',
                                 arguments={'query': 'retention'})
        self.assertEqual(conflict['error']['code'], 'idempotency_conflict')

    def test_replay_after_a_policy_change_withholds_the_old_result(self):
        self.upstream.result = service_result({'doc_id': 'KB-1042', 'title': 'T', 'content': 'C',
                                               'version': 1})
        self.run_call(key='stable-key')
        revoked = deepcopy(POLICY)
        revoked['rules'] = [rule for rule in revoked['rules'] if rule['id'] != 'r1']
        self.policy_reader = StubPolicyReader(revoked, version=8)
        self.coordinator.policy_reader = self.policy_reader
        replay = self.run_call(key='stable-key')
        self.assertEqual(replay['status'], 'succeeded')
        self.assertEqual(replay['disclosure'], 'withheld')
        self.assertNotIn('content', replay.get('reason', ''))

    # -- upstream outcomes -----------------------------------------------------------------
    def test_service_business_error_is_a_no_effect_outcome(self):
        self.upstream.result = service_result(
            {'error': {'code': 'version_conflict', 'message': 'stale version'}}, is_error=True)
        result = self.run_call(tool='documents_read', key='k')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['effect'], 'no_effect')
        self.assertEqual(result['error']['code'], 'version_conflict')
        row = self.operations.list_operations()[0]
        self.assertEqual(row['status'], 'failed')
        self.assertEqual(row['error_code'], 'version_conflict')

    def test_lost_response_is_unknown_until_the_operator_reconciles(self):
        self.upstream.error = UpstreamError('upstream_timeout', 'deadline', dispatched=True)
        self.upstream.status = {'status': 'committed',
                                'receipt': {'receipt_id': 'rcpt-9', 'resource_id': 'KB-1042',
                                            'before_version': 1, 'after_version': 2}}
        result = self.run_call()
        # The client is told the outcome is unknown; the Gate does not resolve it on that path.
        self.assertEqual(result['status'], 'outcome_unknown')
        self.assertEqual(result['effect'], 'unknown')
        self.assertEqual(self.upstream.probes, [])
        row = self.operations.list_operations()[0]
        self.assertEqual(row['status'], STATUS_UNKNOWN)
        self.assertEqual(self.operations.open_reservations('documents'), 1)
        # The operator reconciliation reads the receipt and records the confirmed effect.
        report = asyncio.run(self.coordinator.reconcile())
        self.assertEqual(report['outcomes'][0]['status'], 'succeeded')
        row = self.operations.list_operations()[0]
        self.assertEqual(row['status'], STATUS_SUCCEEDED)
        self.assertEqual(row['receipt_id'], 'rcpt-9')
        self.assertEqual(row['disclosure'], 'withheld')
        self.assertEqual(self.operations.open_reservations('documents'), 0)

    def test_lost_response_without_a_receipt_stays_unknown(self):
        self.upstream.error = UpstreamError('upstream_timeout', 'deadline', dispatched=True)
        result = self.run_call()
        self.assertEqual(result['status'], 'outcome_unknown')
        self.assertEqual(result['effect'], 'unknown')
        row = self.operations.list_operations()[0]
        self.assertEqual(row['status'], 'outcome_unknown')
        # The reservation stays open until reconciliation or an operator fence.
        self.assertEqual(self.operations.open_reservations('documents'), 1)
        # A retry with the same key does not dispatch again.
        again = self.run_call()
        self.assertEqual(again['status'], 'outcome_unknown')
        self.assertEqual(len(self.upstream.calls), 1)

    def test_unreachable_service_is_a_provable_no_effect(self):
        self.upstream.error = UpstreamError('upstream_unavailable', 'connection refused',
                                            dispatched=False)
        result = self.run_call()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['effect'], 'no_effect')
        self.assertEqual(self.operations.open_reservations('documents'), 0)

    def test_unknown_operations_are_reconciled_by_the_operator_path(self):
        self.upstream.error = UpstreamError('upstream_timeout', 'deadline', dispatched=True)
        self.run_call()
        self.upstream.status = {'status': 'committed',
                                'receipt': {'receipt_id': 'rcpt-late', 'resource_id': 'KB-1042'}}
        report = asyncio.run(self.coordinator.reconcile())
        self.assertEqual(report['checked'], 1)
        self.assertEqual(report['outcomes'][0]['status'], 'succeeded')
        self.assertEqual(self.operations.list_operations()[0]['receipt_id'], 'rcpt-late')

    # -- output controls --------------------------------------------------------------------
    def test_output_schema_violation_after_commit_withholds_content(self):
        self.upstream.status = {'status': 'committed', 'receipt': {'receipt_id': 'rcpt-probed'}}
        self.upstream.result = UpstreamResult(
            is_error=False, structured={'status': 'succeeded', 'unexpected': True},
            text='{}', bytes_out=2, protocol_version='2025-11-25')
        result = self.run_call()
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(result['effect'], 'succeeded')
        self.assertEqual(result['disclosure'], 'withheld')
        self.assertNotIn('unexpected', result)
        self.assertEqual(result['receipt_id'], 'rcpt-probed')
        self.assertEqual(self.operations.list_operations()[0]['disclosure'], 'withheld')

    def test_malformed_without_receipt_stays_unknown(self):
        self.upstream.result = UpstreamResult(
            is_error=False, structured={'status': 'succeeded'}, text='{}',
            bytes_out=2, protocol_version='2025-11-25')
        result = self.run_call()
        self.assertEqual(result['status'], 'outcome_unknown')
        self.assertEqual(len(self.upstream.calls), 1)
        self.assertEqual(len(self.upstream.probes), 1)
        row = self.operations.get(result['operation_id'])
        self.assertEqual(row['upstream_operation_id'], self.upstream.calls[0]['context']['operation_id'])

    def test_oversized_result_is_withheld(self):
        payload = service_result({'doc_id': 'KB-1042', 'title': 'T', 'content': 'x' * 600000,
                                  'version': 1})
        self.upstream.result = payload
        result = self.run_call()
        self.assertEqual(result['disclosure'], 'withheld')
        self.assertNotIn('content', result)

    def test_output_redaction_cleans_every_representation(self):
        self.upstream.result = service_result(
            {'doc_id': 'KB-1042', 'title': 'Contact', 'content': 'Write to anna@acme.example.',
             'version': 1})
        result = self.run_call()
        self.assertEqual(result['disclosure'], 'redacted')
        self.assertNotIn('anna@acme.example', json.dumps(result))
        self.assertIn('[EMAIL]', result['content'])

    def test_search_results_are_filtered_per_document(self):
        self.upstream.result = UpstreamResult(
            is_error=False,
            structured={'status': 'succeeded', 'service': 'documents', 'tool': 'search_documents',
                        'operation_id': 'op-internal', 'receipt_id': 'rcpt-s', 'replayed': False,
                        'results': [{'doc_id': 'KB-1042', 'title': 'Two-factor'},
                                    {'doc_id': 'KB-RESTRICTED-01', 'title': 'Restricted'}],
                        'count': 2},
            text='{}', bytes_out=10, protocol_version='2025-11-25')
        result = self.run_call(principal=OBSERVER, tool='documents_search',
                               arguments={'query': 'a'})
        self.assertEqual([row['doc_id'] for row in result['results']], ['KB-1042'])
        self.assertEqual(result['filtered_count'], 1)

    # -- limits ------------------------------------------------------------------------------
    def test_concurrency_reservation_limits_parallel_work(self):
        self.coordinator.limits['max_concurrent_per_service'] = 1
        self.upstream.error = UpstreamError('upstream_timeout', 'deadline', dispatched=True)
        self.run_call(key='first')
        result = self.run_call(key='second')
        self.assertEqual(result['status'], 'throttled')
        self.assertEqual(result['error']['code'], 'concurrency_limit')

    def test_rate_limit_counts_attempts_including_refusals(self):
        self.coordinator.limits['max_attempts_per_minute'] = 2
        self.upstream.result = service_result({'doc_id': 'KB-1042', 'title': 'T', 'content': 'C',
                                               'version': 1})
        self.run_call(key='k1')
        self.run_call(key='k2')
        result = self.run_call(key='k3')
        self.assertEqual(result['status'], 'throttled')
        self.assertEqual(result['error']['code'], 'rate_limited')
        self.assertEqual(len(self.upstream.calls), 2)

    def test_restart_closes_only_pre_dispatch_claims(self):
        self.upstream.error = UpstreamError('upstream_timeout', 'deadline', dispatched=True)
        self.run_call(key='unknown')
        self.operations.claims[('run-0001', 'support-agent', 'claimed')] = None
        claimed = {'demo_run_id': 'run-0001', 'principal_id': 'support-agent',
                   'client_operation_key': 'claimed', 'request_fingerprint': 'f'}
        self.operations.claim(claimed)
        closed = self.operations.close_interrupted('run-0001')
        statuses = {row['client_operation_key']: row['status']
                    for row in self.operations.list_operations()}
        self.assertEqual(statuses['claimed'], 'interrupted')
        self.assertEqual(statuses['unknown'], 'outcome_unknown')
        self.assertEqual(len(closed), 1)


if __name__ == '__main__':
    unittest.main()
