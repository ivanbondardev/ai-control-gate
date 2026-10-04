"""Unified reporting must retain IDs, scope, paging and estimates without raw content."""
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

from action_gate.contracts import ContractError
from action_gate.operator_reporting import OperatorReporting
from action_gate.panel_service import PanelService
from action_gate.storage.memory import MemoryRepository
from action_gate.storage.operations import MemoryOperations
from reporting_fixtures import seed_reporting_owners


class OperatorReportingTests(unittest.TestCase):
    def setUp(self):
        self.repo = MemoryRepository()
        self.panel = PanelService(self.repo)
        self.ops = MemoryOperations()
        self.reporting = OperatorReporting(self.repo, self.panel, self.ops)
        self.window = ('2000-01-01T00:00:00.000Z', '2100-01-01T00:00:00.000Z')
        self.own, self.other = seed_reporting_owners(self.repo)
        self.event = self.panel.dispatch('POST', '/invoke', {'idempotencyKey': 'report-test',
            'request': {'agent': 'support-bot', 'dir': 'input', 'target': 'llama3.1:8b',
                        'text': 'Hello reporting'}}, SimpleNamespace(id='operator-local', role='operator'))[1]
        self.ops.operations['mcp-test'] = {'id': 'mcp-test', 'created_at': datetime.now(timezone.utc),
            'principal_id': 'agent-local', 'published_tool': 'documents.read', 'decision': 'allow',
            'status': 'outcome_unknown', 'policy_version': 1, 'dispatch_started_at': datetime.now(timezone.utc),
            'receipt_id': None, 'result_document': {'secret': 'must not appear'}}

    def test_summary_export_same_ids_and_no_raw_content(self):
        report = self.reporting.report(*self.window)
        self.assertEqual(report['total'], 4)
        self.assertEqual(report['bySource'], {'panel': 1, 'mcp': 1, 'legacy': 2})
        rows, cursor = [], None
        while True:
            page = self.reporting.audit_page(*self.window, 1, cursor)
            rows.extend(page['events'])
            cursor = page['nextCursor']
            if not cursor:
                break
        self.assertEqual(len(rows), len({str(r['event_id']) for r in rows}))
        self.assertEqual({r['invocation_id'] for r in rows}, {r['invocation_id'] for r in report['records']})
        self.assertNotIn('must not appear', str(rows))
        self.assertNotIn('Hello reporting', str(rows))
        self.assertEqual(next(r for r in rows if r.get('source') == 'mcp')['action_outcome'], 'outcome_unknown')

    def test_principal_window_kind_and_cursor_isolation(self):
        report = self.reporting.report(*self.window, 'agent-local')
        self.assertEqual({r['invocation_id'] for r in report['records']}, {self.own, 'mcp-test'})
        self.assertEqual(self.reporting.report('2000-01-01T00:00:00.000Z', '2001-01-01T00:00:00.000Z')['total'], 0)
        page = self.reporting.audit_page(*self.window, 1, filters={'kind': 'panel_outcome'})
        self.assertEqual([r['invocation_id'] for r in page['events']], [self.event['id']])
        with self.assertRaises(ContractError):
            self.reporting.audit_page(*self.window, 1, 'invalid-token')
        cursor = self.reporting.audit_page(*self.window, 1)['nextCursor']
        with self.assertRaises(ContractError):
            self.reporting.audit_page(*self.window, 1, cursor, {'principal_id': 'agent-local'})

    def test_provider_usage_is_separate_from_synthetic_estimates(self):
        record = self.repo.get_invocation(self.own)
        record.update(service_id='openai', action_id='responses',
                      response={'model': 'test-model', 'usage': {'total_tokens': 37}})
        self.repo.save_invocation(record)
        report = self.reporting.report(*self.window)
        model = next(g for g in report['byAgentModel'] if g['source'] == 'model')
        self.assertEqual(model['model'], 'test-model')
        self.assertEqual(model['providerReportedTokens'], 37)
        self.assertEqual(model['syntheticEstimatedTokens'], 0)
        self.assertEqual(model['unknownModelUsage'], 0)
