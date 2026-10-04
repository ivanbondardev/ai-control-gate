"""Content control tests.

The gate is bound to one validated snapshot, so these tests edit documents and rebuild the
snapshot explicitly. Two of them pin the release invariant: a gate built from one snapshot never
observes a later edit, and an invalid document set is refused before it can reach an invocation.
"""
import copy
import json
from pathlib import Path
import unittest

from action_gate.config_bundle import ConfigurationError
from action_gate.content import ContentGate, Signal, validate_documents
from action_gate.snapshot import snapshot_from_documents

POLICY_DIR = Path(__file__).resolve().parents[1] / 'policy'


def fixture_documents():
    def read(name):
        return json.loads((POLICY_DIR / name).read_text())

    return {
        'contentPolicy': read('policy.json'),
        'signatureFeed': read('signatures.json'),
        'services': read('services.json'),
        'budgets': read('budgets.json'),
        'detectors': read('detectors.json'),
        'principals': read('principals.json'),
    }


class ContentTests(unittest.TestCase):
    def setUp(self):
        self.documents = fixture_documents()
        self.seen = []

        def detector(text):
            self.seen.append(text)
            return Signal(0.1, 'test-double')

        self.detector = detector
        self.rebuild()

    # ``gate`` is always bound to the *current* snapshot, so a test that rebuilds the documents
    # cannot accidentally keep evaluating the previous release.
    @property
    def gate(self):
        return self.snapshot.content_gate(self.detector)

    def rebuild(self):
        """Rebuild the snapshot from the current documents.

        Nothing is reloaded implicitly: a test that edits a document must call this, exactly like
        an operator who activates a new release.
        """
        self.snapshot = snapshot_from_documents(copy.deepcopy(self.documents))

    def update_policy(self, **kwargs):
        """Edit the policy document and rebuild - a file edit is never picked up implicitly."""
        self.documents['contentPolicy'].update(kwargs)
        self.rebuild()
        return self.gate

    def test_benign_input_and_output(self):
        for direction in ('input', 'output'):
            result = self.gate.inspect('Summarize quarterly revenue.', direction=direction)
            self.assertEqual(result.decision, 'allow')

    def test_redaction_precedes_detector(self):
        text = 'Email alice@example.org; card 4111 1111 1111 1111.'
        result = self.gate.inspect(text)
        self.assertEqual(result.decision, 'redact')
        self.assertNotIn('alice', result.text)
        self.assertNotIn('4111', result.text)
        self.assertEqual(self.seen, [result.text])

    def test_secret_blocks_without_detector(self):
        self.assertEqual(self.gate.inspect('api_key=abcdefghijklm').decision, 'block')
        self.assertEqual(self.seen, [])

    def test_threshold_change_requires_a_new_snapshot(self):
        self.assertEqual(self.gate.inspect('alice@example.org').decision, 'redact')
        self.update_policy(block_sensitivity=0.4)
        self.assertEqual(self.gate.inspect('alice@example.org').decision, 'block')

    def test_signature_change_requires_a_new_snapshot(self):
        self.assertEqual(self.gate.inspect('new exploit').decision, 'allow')
        feed = self.documents['signatureFeed']
        feed['signatures'].append({'id': 'new', 'literal': 'new exploit',
                                   'description': 'Test indicator'})
        self.rebuild()
        result = self.gate.inspect('new exploit')
        self.assertEqual(result.decision, 'block')
        self.assertIn('new', result.findings)

    def test_a_live_snapshot_never_changes_underneath_an_invocation(self):
        """The release an invocation pinned is the release it finishes with."""
        pinned = self.snapshot
        gate = pinned.content_gate(self.detector)
        self.assertEqual(gate.inspect('new exploit').decision, 'allow')
        # Another operator activates a stricter feed and threshold mid-call.
        self.documents['signatureFeed']['signatures'].append(
            {'id': 'new', 'literal': 'new exploit', 'description': 'Added concurrently'})
        self.documents['contentPolicy']['block_sensitivity'] = 0.4
        self.rebuild()
        self.assertEqual(gate.inspect('new exploit').decision, 'allow',
                         'the pinned snapshot must not observe a concurrent activation')
        self.assertEqual(self.gate.inspect('new exploit').decision, 'block',
                         'a new snapshot must observe it')
        self.assertEqual(gate.policy_hash, pinned.component_hashes['contentPolicy'])

    def test_invalid_documents_never_build_a_snapshot(self):
        for mutate in ('empty', 'truncated', 'nan', 'bool'):
            documents = fixture_documents()
            if mutate == 'empty':
                documents['contentPolicy'] = {}
            elif mutate == 'truncated':
                documents['contentPolicy'] = {'version': 1}
            elif mutate == 'nan':
                documents['contentPolicy']['semantic_threshold'] = float('nan')
            else:
                documents['contentPolicy']['max_text_bytes'] = True
            with self.assertRaises(ConfigurationError):
                snapshot_from_documents(documents)
        # The valid fixture still builds, so the loop above is not passing for a fixed reason.
        snapshot_from_documents(fixture_documents())

    def test_unicode_signature(self):
        self.assertEqual(self.gate.inspect('ｐｉｃｋｌｅ.ｌｏａｄｓ(').decision, 'block')
        self.assertEqual(self.gate.inspect('pickle.\u200bloads(').decision, 'block')

    def test_missing_semantics_is_explicit(self):
        self.detector = None
        result = self.gate.inspect('Hello')
        self.assertEqual(result.decision, 'block')
        self.assertEqual(result.semantic_status, 'unavailable')
        self.update_policy(semantic_unavailable='allow_degraded')
        result = self.gate.inspect('Hello')
        self.assertEqual(result.decision, 'allow')
        self.assertIn('semantic_unavailable_allowed_by_policy', result.reasons)

    def test_bad_signals_fail_closed(self):
        for signal in (Signal(float('nan'), 'test'), Signal(True, 'test'), Signal(2, 'test'), None):
            self.detector = lambda text: signal
            self.assertEqual(self.gate.inspect('Hello').decision, 'block')

    def test_semantic_threshold(self):
        self.detector = lambda text: Signal(0.8, 'test-double')
        self.assertEqual(self.gate.inspect('Hello').decision, 'block')
        self.update_policy(semantic_threshold=0.9)
        self.assertEqual(self.gate.inspect('Hello').decision, 'allow')

    def test_model_and_size(self):
        self.assertEqual(self.gate.inspect('Hello', model='untrusted').reasons, ('model_not_allowed',))
        self.update_policy(max_text_bytes=4)
        self.assertEqual(self.gate.inspect('Hello').reasons, ('text_size_limit',))

    def test_disable_control_and_missing_feed(self):
        self.update_policy(controls={'pii': True, 'secrets': True, 'semantic': True,
                                     'signatures': False})
        # A disabled control does not require a feed document at all.
        self.documents['signatureFeed'] = {}
        self.rebuild()
        self.assertEqual(self.gate.inspect('pickle.loads(').decision, 'allow')

    def test_no_sensitive_text_in_block_result(self):
        result = self.gate.inspect('password=abcdefghijk')
        self.assertNotIn('abcdefghijk', json.dumps(result.as_dict()))
        self.assertIsNone(result.text)

    def test_overlapping_patterns_do_not_leak(self):
        self.update_policy(block_sensitivity=1)
        result = self.gate.inspect('+48123456789 alice@example.org')
        self.assertEqual(result.text, '[REDACTED] [REDACTED]')

    def test_invalid_unicode(self):
        self.assertEqual(self.gate.inspect('\ud800').reasons, ('invalid_unicode',))

    def test_validate_documents_is_pure(self):
        """The import path and the file path run the same validator."""
        policy = fixture_documents()['contentPolicy']
        feed = fixture_documents()['signatureFeed']
        signatures = validate_documents(policy, feed)
        self.assertEqual(len(signatures), len(feed['signatures']))
        self.assertEqual(validate_documents(dict(policy, controls=dict(policy['controls'],
                                                                      signatures=False)), {}), ())
        with self.assertRaises(ConfigurationError):
            validate_documents(dict(policy, version=2), feed)

    def test_from_paths_still_reads_files(self):
        gate = ContentGate.from_paths(POLICY_DIR / 'policy.json', POLICY_DIR / 'signatures.json',
                                     self.detector)
        self.assertEqual(gate.inspect('Summarize quarterly revenue.').decision, 'allow')


if __name__ == '__main__':
    unittest.main()
