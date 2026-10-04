import json
from pathlib import Path
import shutil
import tempfile
import unittest

from action_gate.config_bundle import ConfigurationError, load_bundle


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        source = Path(__file__).resolve().parents[1] / 'policy'
        for path in source.glob('*.json'):
            shutil.copy(path, self.root / path.name)

    def edit(self, name, mutate):
        path = self.root / name
        document = json.loads(path.read_text())
        mutate(document)
        path.write_text(json.dumps(document))

    def test_loads_and_hashes_every_component(self):
        bundle = load_bundle(self.root)
        self.assertEqual(bundle.bundle_id, 'local-default')
        self.assertEqual(set(bundle.components), {'contentPolicy', 'signatureFeed', 'services',
                                                  'budgets', 'detectors', 'principals'})
        self.assertEqual(len(bundle.release_hash), 64)
        self.assertIn('document-desk', bundle.services)

    def test_release_hash_changes_with_content(self):
        before = load_bundle(self.root).release_hash
        self.edit('policy.json', lambda doc: doc.update(block_sensitivity=0.5))
        self.assertNotEqual(before, load_bundle(self.root).release_hash)

    def test_duplicate_json_keys_are_rejected(self):
        (self.root / 'policy.json').write_text('{"version": 1, "version": 2}')
        with self.assertRaises(ConfigurationError):
            load_bundle(self.root)

    def test_missing_component_fails_closed(self):
        (self.root / 'services.json').unlink()
        with self.assertRaises(ConfigurationError):
            load_bundle(self.root)

    def test_component_path_traversal_is_rejected(self):
        self.edit('bundle.json', lambda doc: doc['components'].update(services='../services.json'))
        with self.assertRaises(ConfigurationError):
            load_bundle(self.root)

    def test_unknown_grant_role_is_rejected(self):
        self.edit('services.json', lambda doc: doc['services'][0]['actions'][0].update(grants=['root']))
        with self.assertRaises(ConfigurationError):
            load_bundle(self.root)

    def test_unknown_usage_may_not_be_reported_as_zero(self):
        self.edit('budgets.json', lambda doc: doc['estimation'].update(unknownUsageReportedAsZero=True))
        with self.assertRaises(ConfigurationError):
            load_bundle(self.root)

    def test_deadline_must_leave_room_for_output_reserve(self):
        self.edit('budgets.json', lambda doc: doc['reserve'].update(outputTimeMs=999999))
        with self.assertRaises(ConfigurationError):
            load_bundle(self.root)

    def test_provider_profile_requires_explicit_environment_keys(self):
        def strip(doc):
            doc['profiles'][1].pop('apiKeyEnv')
        self.edit('detectors.json', strip)
        with self.assertRaises(ConfigurationError):
            load_bundle(self.root)

    def test_duplicate_principal_token_is_rejected(self):
        self.edit('principals.json',
                  lambda doc: doc['principals'][1].update(token=doc['principals'][0]['token']))
        with self.assertRaises(ConfigurationError):
            load_bundle(self.root)

    def test_default_detector_must_exist(self):
        self.edit('detectors.json', lambda doc: doc.update(default='missing-profile'))
        with self.assertRaises(ConfigurationError):
            load_bundle(self.root)


if __name__ == '__main__':
    unittest.main()
