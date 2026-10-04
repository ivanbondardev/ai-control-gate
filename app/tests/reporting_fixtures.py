"""Distinct synthetic owners for reporting isolation regressions."""
from uuid import uuid4


def seed_reporting_owners(repository):
    own_id, other_id = str(uuid4()), str(uuid4())
    for invocation_id, principal, private in ((own_id, 'agent-local', False),
                                               (other_id, 'operator-local', True)):
        repository.save_invocation({
            'invocation_id': invocation_id, 'idempotency_key': 'summary-' + invocation_id,
            'principal_id': principal, 'principal_role': 'operator' if private else 'agent',
            'service_id': 'document-desk',
            'action_id': 'documents.comment' if private else 'documents.read',
            'request_hash': 'synthetic', 'release_hash': 'synthetic-release',
            'decision': 'redact' if private else 'allow',
            'action_outcome': 'failed' if private else 'succeeded',
            'disclosure': 'withheld' if private else 'full',
            'reasons': ['private_reason' if private else 'own_reason'],
            'findings': ['private_finding' if private else 'own_finding'],
            'semantic_status': 'unavailable' if private else 'available',
            'semantic_risk': None, 'detector_profile': 'baseline-offline-v1',
            'latency_ms': 999 if private else 11, 'dry_run': private,
            'budget_scope': 'global-daily', 'response': {'replayed': private},
        })
        repository.append_events([
            {'invocation_id': invocation_id, 'seq': sequence, 'kind': 'input_controls',
             'decision': 'redact' if private else 'allow', 'reasons': [], 'findings': [],
             'detail': {}}
            for sequence in range(1, 3 if private else 2)])
        repository.record_effect({
            'invocation_id': invocation_id, 'service_id': 'document-desk',
            'action_id': 'documents.comment' if private else 'documents.read',
            'outcome': 'failed' if private else 'succeeded', 'result_bytes': 0, 'detail': {},
        })
    return own_id, other_id


def assert_owned_report(test, report, last_event_at):
    test.assertEqual(report['invocations'], {'total': 1, 'allowed': 1, 'redacted': 0,
                                            'blocked': 0, 'dryRun': 0, 'replayed': 0})
    test.assertEqual(report['outcomes'], {'succeeded': 1, 'notStarted': 0, 'unknown': 0, 'failed': 0})
    test.assertEqual(report['disclosure'], {'full': 1, 'redacted': 0, 'withheld': 0, 'none': 0})
    test.assertEqual(report['semantic'], {'available': 1, 'unavailable': 0, 'disabled': 0, 'notRun': 0})
    test.assertEqual(report['topReasons'], [{'value': 'own_reason', 'count': 1}])
    test.assertEqual(report['topFindings'], [{'value': 'own_finding', 'count': 1}])
    test.assertEqual(report['dispatch'], {'documents.read': 1})
    test.assertEqual(report['dispatchByDecision'], {'allow': 1})
    test.assertEqual(report['latency']['total'], {'n': 1, 'p50': 11, 'p95': 11, 'max': 11})
    test.assertEqual(report['events'], 1)
    test.assertEqual(report['lastEventAt'], last_event_at)
