"""Dummy-service runtime: validation, one commit, replay, conflict, fence and restart.

These tests exercise the service objects directly, without the MCP transport, so they run fast and
state the storage contract precisely. The transport-level checks live in test_dummy_transport.py.
"""
import json
import os
import shutil
import tempfile
import unittest

try:
    from dummy_mcp.common.contracts import ProtocolError, ServiceError
    from dummy_mcp.common.storage import Store
    from dummy_mcp.documents.service import DocumentsService
    from dummy_mcp.outbox.service import OutboxService
    from dummy_mcp.tickets.service import TicketsService
    IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001 - reported as a skip
    IMPORT_ERROR = exc

RUN = 'run-0001'


def meta(operation_id, actor='support-agent', run_id=RUN):
    return {'actiongate.internal/operation_id': operation_id,
            'actiongate.internal/demo_run_id': run_id,
            'actiongate.internal/actor': actor}


@unittest.skipIf(IMPORT_ERROR is not None, f'dummy runtime unavailable: {IMPORT_ERROR}')
class DummyRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix='dummy-test-')
        self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)

    def service(self, name, service_class):
        store = Store(name, os.path.join(self.directory, f'{name}.sqlite3'))
        service = service_class(store, hold_seconds=0.1)
        service.bootstrap(run_id=RUN)
        return service

    # -- documents -------------------------------------------------------------------
    def documents(self):
        return self.service('documents', DocumentsService)

    def test_read_and_update_versions(self):
        service = self.documents()
        read = service.dispatch('read_document', {'doc_id': 'KB-1042'}, meta('op-read-1'))
        self.assertEqual(read['version'], 1)
        self.assertTrue(read['receipt_id'].startswith('rcpt-'))
        update = service.dispatch('update_document',
                                  {'doc_id': 'KB-1042', 'content': 'New synthetic body.',
                                   'expected_version': 1}, meta('op-update-1'))
        self.assertEqual(update['version'], 2)
        again = service.dispatch('read_document', {'doc_id': 'KB-1042'}, meta('op-read-2'))
        self.assertEqual(again['content'], 'New synthetic body.')
        self.assertEqual(again['version'], 2)

    def test_version_conflict_is_business_error(self):
        service = self.documents()
        service.dispatch('update_document',
                         {'doc_id': 'KB-1042', 'content': 'First.', 'expected_version': 1},
                         meta('op-update-a'))
        with self.assertRaises(ServiceError) as caught:
            service.dispatch('update_document',
                             {'doc_id': 'KB-1042', 'content': 'Second.', 'expected_version': 1},
                             meta('op-update-b'))
        self.assertEqual(caught.exception.code, 'version_conflict')

    def test_replay_returns_receipt_without_second_commit(self):
        service = self.documents()
        first = service.dispatch('update_document',
                                 {'doc_id': 'KB-1042', 'content': 'Idempotent.', 'expected_version': 1},
                                 meta('op-update-c'))
        replay = service.dispatch('update_document',
                                  {'doc_id': 'KB-1042', 'content': 'Idempotent.', 'expected_version': 1},
                                  meta('op-update-c'))
        self.assertEqual(replay['receipt_id'], first['receipt_id'])
        self.assertTrue(replay['replayed'])
        state = service.snapshot()
        commits = [row for row in state['receipts'] if row['operation_id'] == 'op-update-c']
        self.assertEqual(len(commits), 1)

    def test_same_key_with_other_content_conflicts(self):
        service = self.documents()
        service.dispatch('update_document',
                         {'doc_id': 'KB-1042', 'content': 'One.', 'expected_version': 1},
                         meta('op-update-d'))
        with self.assertRaises(ServiceError) as caught:
            service.dispatch('update_document',
                             {'doc_id': 'KB-1042', 'content': 'Two.', 'expected_version': 2},
                             meta('op-update-d'))
        self.assertEqual(caught.exception.code, 'idempotency_conflict')

    def test_schema_is_strict(self):
        service = self.documents()
        with self.assertRaises(ProtocolError):
            service.dispatch('read_document', {'doc_id': 'KB-1042', 'extra': 1}, meta('op-s1'))
        with self.assertRaises(ProtocolError):
            service.dispatch('read_document', {'doc_id': 42}, meta('op-s2'))
        with self.assertRaises(ProtocolError):
            service.dispatch('search_documents', {'query': 'policy', 'limit': 0}, meta('op-s3'))
        with self.assertRaises(ProtocolError):
            service.dispatch('no_such_tool', {}, meta('op-s4'))
        with self.assertRaises(ProtocolError):
            service.dispatch('read_document', {'doc_id': 'KB-1042'}, {})
        with self.assertRaises(ServiceError):
            service.dispatch('read_document', {'doc_id': 'KB-9999'}, meta('op-s5'))

    def test_search_returns_ids_and_titles_only(self):
        service = self.documents()
        found = service.dispatch('search_documents', {'query': 'retention'}, meta('op-search'))
        self.assertEqual({row['doc_id'] for row in found['results']},
                         {'KB-9000', 'KB-INJECT-01'})
        self.assertNotIn('content', json.dumps(found))
        limited = service.dispatch('search_documents', {'query': 'retention', 'limit': 1},
                                   meta('op-search-limited'))
        self.assertEqual(limited['count'], 1)

    # -- restarts, runs and fences ------------------------------------------------------
    def test_restart_keeps_state_and_does_not_reseed(self):
        path = os.path.join(self.directory, 'documents.sqlite3')
        service = DocumentsService(Store('documents', path), hold_seconds=0.1)
        service.bootstrap(run_id=RUN)
        service.dispatch('update_document',
                         {'doc_id': 'KB-1042', 'content': 'Survives a restart.',
                          'expected_version': 1}, meta('op-restart'))
        restarted = DocumentsService(Store('documents', path), hold_seconds=0.1)
        run_id = restarted.bootstrap()
        self.assertEqual(run_id, RUN)
        read = restarted.dispatch('read_document', {'doc_id': 'KB-1042'}, meta('op-after-restart'))
        self.assertEqual(read['content'], 'Survives a restart.')
        self.assertEqual(read['version'], 2)

    def test_reset_starts_a_new_run_and_keeps_evidence(self):
        service = self.documents()
        service.dispatch('update_document',
                         {'doc_id': 'KB-1042', 'content': 'Run one body.', 'expected_version': 1},
                         meta('op-run1'))
        reset = service.store.reset_run('run-0002', service.seed)
        self.assertEqual(reset['previousRunId'], RUN)
        read = service.dispatch('read_document', {'doc_id': 'KB-1042'},
                                meta('op-run2', run_id='run-0002'))
        self.assertEqual(read['version'], 1)
        self.assertIn('recovery link', read['content'])
        with self.assertRaises(ServiceError) as caught:
            service.dispatch('read_document', {'doc_id': 'KB-1042'}, meta('op-late'))
        self.assertEqual(caught.exception.code, 'stale_run')
        old = service.snapshot(run_id=RUN)
        self.assertTrue(any(row['operation_id'] == 'op-run1' for row in old['receipts']))

    def test_fence_blocks_a_late_call(self):
        service = self.documents()
        service.store.fence_operation(operation_id='op-fenced', demo_run_id=RUN,
                                      actor='operator', note='unknown without receipt')
        with self.assertRaises(ServiceError) as caught:
            service.dispatch('read_document', {'doc_id': 'KB-1042'}, meta('op-fenced'))
        self.assertEqual(caught.exception.code, 'operation_fenced')
        status = service.store.operation_status('op-fenced')
        self.assertEqual(status['status'], 'no_effect')

    def test_fence_reports_an_existing_receipt(self):
        service = self.documents()
        service.dispatch('read_document', {'doc_id': 'KB-1042'}, meta('op-committed'))
        result = service.store.fence_operation(operation_id='op-committed', demo_run_id=RUN)
        self.assertEqual(result['outcome'], 'already_committed')

    # -- outbox ----------------------------------------------------------------------
    def outbox(self):
        return self.service('outbox', OutboxService)

    def test_outbox_stores_locally_and_enforces_ownership(self):
        service = self.outbox()
        stored = service.dispatch('send_message',
                                  {'to': 'colleague@acme.example', 'subject': 'Summary',
                                   'body': 'Synthetic summary.'}, meta('op-send-1'))
        self.assertEqual(stored['status'], 'succeeded')
        self.assertEqual(stored['message_status'], 'stored_locally')
        self.assertTrue(stored['message_id'].startswith('MSG-'))
        mine = service.dispatch('get_message', {'message_id': stored['message_id']},
                                meta('op-get-1', actor='support-agent'))
        self.assertEqual(mine['body'], 'Synthetic summary.')
        with self.assertRaises(ServiceError) as caught:
            service.dispatch('get_message', {'message_id': stored['message_id']},
                             meta('op-get-2', actor='observer-agent'))
        self.assertEqual(caught.exception.code, 'not_message_owner')
        listed = service.dispatch('list_messages', {}, meta('op-list-1', actor='observer-agent'))
        self.assertEqual(listed['count'], 0)

    def test_outbox_rejects_malformed_recipients(self):
        service = self.outbox()
        for index, address in enumerate(('Team <team@acme.example>', 'a@acme.example, b@acme.example',
                                         'bad\r\nBcc: x@acme.example', 'no-at-sign',
                                         'user@external.example\r\n')):
            with self.assertRaises(ServiceError) as caught:
                service.dispatch('send_message',
                                 {'to': address, 'subject': 'S', 'body': 'B'},
                                 meta(f'op-bad-{index}'))
            self.assertEqual(caught.exception.code, 'invalid_recipient')
        state = service.snapshot()
        self.assertEqual(state['state']['bodies']['stored'], 0)
        self.assertEqual({row['outcome'] for row in state['calls']}, {'invalid_recipient'})

    def test_outbox_is_idempotent(self):
        service = self.outbox()
        first = service.dispatch('send_message',
                                 {'to': 'colleague@acme.example', 'subject': 'S', 'body': 'B'},
                                 meta('op-send-2'))
        replay = service.dispatch('send_message',
                                  {'to': 'colleague@acme.example', 'subject': 'S', 'body': 'B'},
                                  meta('op-send-2'))
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['message_id'], first['message_id'])
        self.assertEqual(service.snapshot()['calls'][-1]['count'], 1)

    # -- tickets -----------------------------------------------------------------------
    def tickets(self):
        return self.service('tickets', TicketsService)

    def test_ticket_transition_invariant(self):
        service = self.tickets()
        moved = service.dispatch('transition_ticket',
                                 {'ticket_id': 'T-1001', 'target_status': 'in_progress',
                                  'expected_version': 1}, meta('op-transition-1'))
        self.assertEqual(moved['version'], 2)
        # open -> resolved is refused by the service even though the Gate could admit the call.
        with self.assertRaises(ServiceError) as caught:
            service.dispatch('transition_ticket',
                             {'ticket_id': 'T-9000', 'target_status': 'resolved',
                              'expected_version': 1}, meta('op-transition-2'))
        self.assertEqual(caught.exception.code, 'business_transition_invalid')
        # A backwards transition is refused as well.
        with self.assertRaises(ServiceError) as caught:
            service.dispatch('transition_ticket',
                             {'ticket_id': 'T-1001', 'target_status': 'open',
                              'expected_version': 2}, meta('op-transition-3'))
        self.assertEqual(caught.exception.code, 'business_transition_invalid')
        resolved = service.dispatch('transition_ticket',
                                    {'ticket_id': 'T-1001', 'target_status': 'resolved',
                                     'expected_version': 2}, meta('op-transition-4'))
        self.assertEqual(resolved['version'], 3)
        state = service.snapshot()
        self.assertEqual(len(state['state']['transitions']), 2)

    def test_ticket_create_assigns_a_new_id(self):
        service = self.tickets()
        created = service.dispatch('create_ticket',
                                   {'title': 'New synthetic case', 'description': 'Body'},
                                   meta('op-create-1'))
        self.assertEqual(created['ticket_id'], 'T-9001')
        self.assertEqual(created['ticket_status'], 'open')
        self.assertEqual(created['version'], 1)

    # -- faults ------------------------------------------------------------------------
    def test_business_error_fault_leaves_no_effect(self):
        service = self.documents()
        service.store.add_fault(mode='business_error_before_commit', tool='update_document')
        with self.assertRaises(ServiceError) as caught:
            service.dispatch('update_document',
                             {'doc_id': 'KB-1042', 'content': 'Never stored.',
                              'expected_version': 1}, meta('op-fault-1'))
        self.assertEqual(caught.exception.code, 'business_rejected')
        read = service.dispatch('read_document', {'doc_id': 'KB-1042'}, meta('op-fault-read'))
        self.assertEqual(read['version'], 1)

    def test_delay_before_commit_still_commits_once(self):
        service = self.documents()
        service.store.add_fault(mode='delay_before_commit', tool='update_document', delay_ms=150)
        result = service.dispatch('update_document',
                                  {'doc_id': 'KB-1042', 'content': 'Delayed but stored.',
                                   'expected_version': 1}, meta('op-fault-2'))
        self.assertEqual(result['version'], 2)
        self.assertEqual(service.store.operation_status('op-fault-2')['status'], 'committed')

    def test_fault_rules_expire_and_are_one_shot(self):
        service = self.documents()
        service.store.add_fault(mode='business_error_before_commit', remaining=1)
        with self.assertRaises(ServiceError):
            service.dispatch('read_document', {'doc_id': 'KB-1042'}, meta('op-fault-3'))
        # The rule was one-shot; the next call is served normally.
        self.assertEqual(service.dispatch('read_document', {'doc_id': 'KB-1042'},
                                          meta('op-fault-4'))['doc_id'], 'KB-1042')


if __name__ == '__main__':
    unittest.main()
