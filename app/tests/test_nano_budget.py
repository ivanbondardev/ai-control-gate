"""Reasoning completion allowance must be reserved before paid work or dispatch."""
from pathlib import Path
import unittest
from unittest.mock import patch

from action_gate.config_bundle import load_bundle
from action_gate.contracts import parse_invocation, parse_evaluation
from action_gate.detectors import DetectionOutcome, ProviderDetector, STATUS_AVAILABLE
from action_gate.gateway import Gateway
from action_gate.storage.memory import MemoryRepository

POLICY_DIR = Path(__file__).resolve().parents[1] / 'policy'


class RecordingRepository(MemoryRepository):
    def __init__(self):
        super().__init__()
        self.plans = []

    def reserve_budget(self, plan, limits):
        self.plans.append(plan)
        return super().reserve_budget(plan, limits)


class NanoBudgetTests(unittest.TestCase):
    def setUp(self):
        self.repository = RecordingRepository()
        self.gateway = Gateway(POLICY_DIR, self.repository, environ={
            'APP_HASH_SALT': 'test-salt',
            'DETECTOR_PROVIDER_BASE_URL': 'https://api.openai.com/v1',
            'DETECTOR_PROVIDER_API_KEY': 'synthetic-not-a-key',
            'DETECTOR_PROVIDER_MODEL': 'gpt-5-nano-2025-08-07',
        })
        self.bundle = load_bundle(POLICY_DIR)
        self.calls = []

        def detect(detector, text, direction, deadline=None):
            self.calls.append(direction)
            # Inspect the reservation at the instant paid work would begin.
            planned = self.repository.plans[-1]
            self.assertGreater(planned.tokens, detector.completion_token_cap)
            return DetectionOutcome(STATUS_AVAILABLE, 'provider', detector.detector,
                                    detector.profile_id, risk=0, category='benign',
                                    usage_tokens=20, usage_status='reported')

        patched = patch.object(ProviderDetector, 'detect', detect)
        patched.start()
        self.addCleanup(patched.stop)

    def test_input_and_output_reserve_cover_reasoning(self):
        request = parse_invocation({
            'idempotencyKey': 'nano-budget', 'service': 'document-desk',
            'action': 'documents.comment', 'input': {
                'documentId': 'handbook', 'text': 'Please review the summary.'},
            'model': 'demo-local', 'detectorProfile': 'provider-chat-v1',
        }, self.bundle)
        status, body = self.gateway.invoke(request, self.bundle.principals['operator-local'])
        self.assertEqual(status, 200)
        self.assertEqual(body['action']['outcome'], 'succeeded')
        self.assertEqual(self.calls, ['input', 'output'])
        for plan in self.repository.plans:
            semantic = [call for call in plan.calls if call.name.startswith('semantic_')]
            self.assertTrue(semantic)
            self.assertGreater(semantic[0].tokens, 1024)

    def test_evaluation_reserves_reasoning_before_provider(self):
        from action_gate.evaluation import EvaluationRunner
        request = parse_evaluation({
            'detectorProfile': 'provider-chat-v1',
            'cases': [{'id': 'nano', 'text': 'Ordinary test sample.'}],
        })
        status, body = EvaluationRunner(self.gateway).run(request)
        self.assertEqual(status, 200)
        self.assertTrue(self.calls)


if __name__ == '__main__':
    unittest.main()
