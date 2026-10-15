"""Actual saved acquisition and fixed Git inputs, with external origin auth mocked."""
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).parent))
import canonical_input_assessment as assessment
import fetch_runtime_release as fetch
from schema_input_bundle import canonical, sha, formal_input_paths, POLICY_PATH, REBINDING_PATH
from source_governance import initial_policy, acquisition_receipt, receipt_key
import test_runtime_contract_artifact as artifact_tests


class CanonicalInputTests(unittest.TestCase):
    now = datetime(2026, 10, 16, tzinfo=timezone.utc)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = initial_policy({'kind': 'provider_openapi', 'url': 'https://example.invalid/openapi.json',
            'content_hash': 'sha256:fixture', 'fetched_at': self.now.isoformat(), 'refresh_policy': 'automatic'})
        self.inputs = {'openapi/registry.yaml': b'providers: {example: {}}\n',
            POLICY_PATH: b'{}', REBINDING_PATH: b'{}',
            'openapi/upstream/example.json': canonical({'info': {'x-aisa-source': self.source}, 'paths': {}}),
            'openapi/example.json': b'{"paths":{}}', 'openapi/coverage.json': b'{"providers":{}}',
            'openapi/pending.json': b'{}'}
        self.pointer = {'contract_release': 'b' * 64, 'files_sha256': {name: sha(raw) for name, raw in self.inputs.items()}}
        for name, raw in self.inputs.items():
            self.write(name, raw)
        self.write('docs/publication/current.json', canonical(self.pointer))
        self.git('init', '-q')
        self.git('add', '.')
        self.git('-c', 'user.name=Ken', '-c', 'user.email=ken@aisa.one', 'commit', '-qm', 'Fixture')
        self.ref = self.git('rev-parse', 'HEAD').decode().strip()
        self.release = artifact_tests.CanonicalArtifactTests()
        self.release.setUp()
        self.release.manifest['docs_ref'] = self.ref
        self.release.seal()
        self.release.current['compiler_inputs'] = {key: self.release.manifest[key] for key in assessment.BINDINGS}
        self.saved = {'schema_version': 1, 'receipts': {
            receipt_key(self.source): acquisition_receipt(self.source, self.now)}, 'attempts': {}}
        self.write_receipts()
        self.provenance = {'expected_docs_ref': self.ref, 'contract_release': self.pointer['contract_release']}
        self.auth = patch.object(assessment, 'inspect_publication', return_value=self.provenance)
        self.auth_mock = self.auth.start()
        self.addCleanup(self.auth.stop)

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, stderr=subprocess.PIPE)

    def write(self, name, raw):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    def write_receipts(self):
        self.write('.cache/source-reviews.json', canonical(self.saved))

    def assess(self):
        with tempfile.TemporaryDirectory() as folder:
            facts = Path(folder) / 'facts'
            fetch.save(facts, self.release.acquire())
            return assessment.assess_canonical_inputs(self.root, facts, checked_at=self.now)

    def test_fixed_git_and_live_binding_with_original_source_clock(self):
        before = dict(self.inputs)
        result = self.assess()
        self.auth_mock.assert_called_once_with(self.root, self.ref, historical=True)
        self.assertEqual(result['compiler_inputs'], self.release.current['compiler_inputs'])
        self.assertEqual(result['frozen_input_files_sha256'], self.pointer['files_sha256'])
        self.assertEqual(result['source_checked_at'], self.now.isoformat())
        self.assertEqual(result['source_observations']['example.json']['freshness'], 'fresh')
        self.assertIn('final_provider_source_scope_and_expiry', result['remaining_gates'])
        self.assertNotIn('source_authorization_expires_at', result)
        self.assertEqual({name: (self.root / name).read_bytes() for name in before}, before)

    def test_missing_or_wrong_live_pin_rejected_even_if_artifact_is_valid(self):
        original = copy.deepcopy(self.release.current['compiler_inputs'])
        for value in [None, {}, {**original, 'bundle_manifest_sha256': '0' * 64},
                      {**original, 'generation': 3}, {**original, 'composer_revision': True}]:
            self.release.current['compiler_inputs'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.assess()

    def test_fixed_ref_origin_authentication_cannot_be_self_declared(self):
        self.auth_mock.side_effect = ValueError('Unsuccessful formal producer')
        with self.assertRaisesRegex(ValueError, 'Unsuccessful formal producer'):
            self.assess()

    def test_origin_pointer_binding_mismatch_rejected(self):
        self.provenance['contract_release'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'Authenticated formal pointer'):
            self.assess()

    def test_schema_policy_and_registry_changes_rejected(self):
        for name in ['openapi/upstream/example.json', 'openapi/registry.yaml', POLICY_PATH, REBINDING_PATH]:
            self.write(name, self.inputs[name] + b' ')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'Current schema or policy differs'):
                self.assess()
            self.write(name, self.inputs[name])

    def test_added_source_is_not_silently_outside_compiled_inventory(self):
        self.write('openapi/upstream/new.json', self.inputs['openapi/upstream/example.json'])
        with self.assertRaisesRegex(ValueError, 'membership differs'):
            self.assess()

    def test_deleted_source_and_symlink_rejected(self):
        name = 'openapi/upstream/example.json'
        path = self.root / name
        path.unlink()
        with self.assertRaises(ValueError):
            self.assess()
        path.symlink_to(self.root / 'openapi/example.json')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.assess()

    def test_unimplemented_overlay_rejected(self):
        self.write('openapi/overlays/example.yaml', b'{}')
        with self.assertRaisesRegex(ValueError, 'Overlay inputs'):
            self.assess()

    def test_old_or_failed_observations_never_renewed_by_build_pin(self):
        old = self.now - timedelta(days=2)
        self.saved['receipts'][receipt_key(self.source)] = acquisition_receipt(self.source, old)
        self.write_receipts()
        result = self.assess()
        self.assertEqual(result['source_observations']['example.json']['freshness'], 'overdue')
        self.assertEqual(result['source_observations']['example.json']['last_successful_review_at'], old.isoformat())
        self.saved['attempts'][receipt_key(self.source)] = {'status': 'fetch_failed', 'checked_at': self.now.isoformat()}
        self.write_receipts()
        self.assertEqual(self.assess()['source_observations']['example.json']['status'], 'fetch_failed')

    def test_input_selector_matches_existing_bundle_roles(self):
        paths = set(self.inputs) | {'openapi/zh/example.json', 'llms.txt', 'openapi/openapi.json',
                                  'docs/publication/current.json'}
        self.assertEqual(formal_input_paths(paths), set(self.inputs))


if __name__ == '__main__':
    unittest.main()
