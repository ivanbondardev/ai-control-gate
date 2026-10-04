"""Regression tests for operator recovery: only service evidence can establish no effect."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

try:
    from action_gate.mcp_ops import McpOperator
    from action_gate.storage.operations import MemoryOperations, OperationsError
    ERROR = None
except ImportError as exc:
    ERROR = exc


@unittest.skipIf(ERROR, str(ERROR))
class RecoveryTest(unittest.TestCase):
    def setUp(self):
        self.ops = MemoryOperations()
        self.row = self.ops.claim(dict(demo_run_id='run-0001', principal_id='support-agent',
            client_operation_key='recovery', request_fingerprint='f', published_tool='outbox_send',
            upstream_tool='send_message', service_id='outbox'))['row']
        self.ops.mark_dispatch_started(self.row['id'], 'lease', 30, 'op-different')
        self.ops.finish(self.row['id'], {'status': 'outcome_unknown'})
        self.operator = McpOperator.__new__(McpOperator)
        self.operator.operations = self.ops
        binding = SimpleNamespace(service_id='outbox', status_endpoint='http://outbox/operations',
                                  credential_id='gate-mcp')
        self.operator.registry_service = SimpleNamespace(active=lambda: SimpleNamespace(binding=lambda _: binding))
        self.operator.upstream = SimpleNamespace(operation_status=AsyncMock())
        self.operator.coordinator = SimpleNamespace(_probe_receipt=AsyncMock(return_value={'receipt_id': 'rcpt-1'}))

    def test_fence_resolves_upstream_id_and_requires_evidence(self):
        self.assertEqual(self.operator.fence_target(self.row['id'])['upstreamOperationId'], 'op-different')
        for status in ({'operationId': 'op-different', 'status': 'not_found'},
                       {'operationId': 'wrong', 'status': 'no_effect'},
                       {'operationId': 'op-different', 'status': 'no_effect',
                        'fence': {'demo_run_id': 'wrong', 'kind': 'cancelled_no_effect'}}):
            self.operator.upstream.operation_status.return_value = status
            with self.assertRaises(SystemExit):
                self.operator.confirm_fence(self.row['id'])
            self.assertEqual(self.ops.get(self.row['id'])['status'], 'outcome_unknown')

    def test_confirmed_fence_closes_operation(self):
        self.operator.upstream.operation_status.return_value = {
            'operationId': 'op-different', 'status': 'no_effect',
            'fence': {'demo_run_id': 'run-0001', 'kind': 'cancelled_no_effect'}}
        self.assertEqual(self.operator.confirm_fence(self.row['id'])['status'], 'failed')
        self.assertEqual(self.ops.events[-1]['effect_outcome'], 'no_effect')

    def test_commit_wins_over_fence(self):
        self.operator.upstream.operation_status.return_value = {
            'operationId': 'op-different', 'status': 'committed',
            'receipt': {'demo_run_id': 'run-0001', 'receipt_id': 'rcpt-1'}}
        self.assertEqual(self.operator.confirm_fence(self.row['id'])['status'], 'succeeded')
        self.operator.coordinator._probe_receipt.assert_awaited_once()
        self.assertEqual(self.ops.events, [])

    def test_closed_admission_rejects_stale_claim(self):
        self.ops.set_run_state(admission_open=False)
        with self.assertRaises(OperationsError):
            self.ops.claim(dict(self.row, client_operation_key='new'))
