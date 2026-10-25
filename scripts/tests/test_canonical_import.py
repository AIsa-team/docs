"""Projection must preserve Runtime bytes and derive fresh metadata, without compose."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).parent))
import canonical_import as importer
from schema_input_bundle import canonical, sha, POLICY_PATH, REBINDING_PATH
from source_governance import initial_policy, acquisition_receipt, receipt_key, source_report
from export_contract_publication import source_expiry
import test_publication_surface as surfaces


def document(provider='one', title='Original', price=1):
    return {'openapi': '3.1.0', 'info': {'title': title, 'description': '', 'x-aisa-provider': provider,
        'x-aisa-document': {'facts_hash': 'a' * 64, 'document_hash': 'sha256:fixture'},
        'x-aisa-catalogs': {provider: {}}}, 'servers': [{'url': 'https://api.aisa.one'}],
        'paths': {'/request': {'get': {'operationId': 'one', 'x-aisa-status': 'enabled',
            'x-aisa-pricing': {'default_request_estimate_usd': price},
            'responses': {'200': {'description': 'OK', 'content': {'application/json': {'schema': {'type': 'string'}}}}}}}}}


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'openapi/upstream').mkdir(parents=True)
        self.registry = {'auto_register': True, 'providers': {'one': {'display_name': 'Original', 'description': ''}}}
        self.write_registry()
        self.native = {'one': document()}
        (self.root / 'openapi/one.json').write_bytes(canonical(self.native['one']))
        self.facts = {'one': document()}
        self.index = {'providers': [{'id': 'one'}]}
        self.category = {'apis': [{'id': 'one'}]}
        self.readiness = {'status': 'passed', 'global_errors': [], 'missing_inputs': [], 'blocked_providers': [],
            'providers': {'one': {'existing_pending': [], 'deferred_pending': [], 'new_pending': []}}}

    def write_registry(self):
        (self.root / 'openapi/registry.yaml').write_text(yaml.safe_dump(self.registry))

    def project(self):
        with patch('compose_openapi.compose', side_effect=AssertionError('must not compose')), \
             patch('pull_openapi.compose', side_effect=AssertionError('must not compose')):
            return importer.project_metadata(self.root, self.facts, self.index, self.category, self.native, self.readiness)

    def test_metadata_ignores_old_coverage_and_pending_and_preserves_inputs(self):
        (self.root / 'openapi/coverage.json').write_bytes(b'{"providers":{"wrong":[]}}')
        (self.root / 'openapi/pending.json').write_bytes(b'{"providers":{"wrong":["fake"]}}')
        before = copy.deepcopy((self.facts, self.native, self.readiness))
        result = self.project()
        self.assertEqual(set(result['coverage']['providers']), {'one'})
        self.assertEqual(result['pending'], {'providers': {'one': []}})
        self.assertEqual((self.facts, self.native, self.readiness), before)
        self.assertEqual(result['coverage']['providers']['one'][0]['status'], 'composed')

    def test_response_identity_policy_mode_is_shared_by_canonical_projection(self):
        from types import SimpleNamespace
        from gap_evidence import gap_key
        self.native['one']['paths']['/request']['get']['responses'] = {'200': {'description': 'unknown'}}
        self.facts['one']['paths']['/request']['get']['responses'] = {'200': {'description': 'unknown'}}
        # The production loader authenticates exact record bytes. This fixture
        # exercises projection wiring, independently of Composer and the loader.
        with patch('deferred_definitions.load_deferred_definitions',
                   return_value=SimpleNamespace(response_v2_keys={'mode-marker'})):
            first = self.project()
            op = self.facts['one']['paths']['/request']['get']
            op['parameters'] = [{'name': 'new', 'in': 'query', 'schema': {'type': 'string'}}]
            second = self.project()
        old = first['coverage']['response_gaps']['one'][0]
        new = second['coverage']['response_gaps']['one'][0]
        self.assertIn('response_runtime_binding_hash', old)
        self.assertEqual(gap_key(old), gap_key(new))
        self.assertNotEqual(old['source_binding_hash'], new['source_binding_hash'])
        self.assertNotIn('response_runtime_binding_hash', self.project()['coverage']['response_gaps']['one'][0])

    def test_group_facts_share_existing_combiner(self):
        self.registry['providers'] = {'one': {'group': ['alpha', 'beta']}}
        self.write_registry()
        alpha, beta = document('alpha'), document('beta')
        beta['paths'] = {'/second': {'get': {**beta['paths']['/request']['get'], 'operationId': 'two'}}}
        self.facts = {'alpha': alpha, 'beta': beta}
        self.index = {'providers': [{'id': 'alpha'}, {'id': 'beta'}]}
        self.category = {'apis': [{'id': 'alpha'}, {'id': 'beta'}]}
        self.native['one']['paths'].update(beta['paths'])
        result = self.project()
        self.assertEqual({row['catalog'] for row in result['coverage']['providers']['one']}, {'alpha', 'beta'})
        self.assertEqual(result['registry']['providers']['one']['display_name'], 'one')

    def test_missing_fact_or_readiness_provider_cannot_be_retained_as_success(self):
        self.facts = {}
        with self.assertRaisesRegex(ValueError, 'group input missing'):
            self.project()
        self.facts = {'one': document()}
        self.readiness['providers']['unbound'] = {}
        with self.assertRaisesRegex(ValueError, 'provider scope differs'):
            self.project()

    def test_retained_pending_comes_from_new_native_and_ordinary_pending_fails(self):
        operation = self.native['one']['paths']['/request']['get']
        operation.update({'x-aisa-status': 'disabled', 'x-aisa-contract-state': 'retained_legacy',
                          'x-aisa-contract-pending': 'not_in_runtime_contract'})
        result = self.project()
        self.assertEqual(result['pending']['providers']['one'][0]['reason'], 'not_in_runtime_contract')
        del operation['x-aisa-contract-state']
        with self.assertRaisesRegex(ValueError, 'Unsupported canonical pending'):
            self.project()

    def test_two_publications_change_title_then_only_price_without_new_schema_bundle(self):
        frozen, originals = copy.deepcopy(self.registry), copy.deepcopy(self.native)
        self.facts['one']['info']['title'] = 'New Runtime title'
        self.native['one']['info']['title'] = 'New Runtime title'
        first = self.project()
        restored = importer.validate_derived_registry(frozen, first['registry'], originals, self.native)
        self.assertEqual(restored, frozen)
        # Second compilation still uses the unchanged fixed input registry.
        self.facts['one']['paths']['/request']['get']['x-aisa-pricing']['default_request_estimate_usd'] = 2
        self.native['one']['paths']['/request']['get']['x-aisa-pricing']['default_request_estimate_usd'] = 2
        second = self.project()
        self.assertEqual(first['registry'], second['registry'])
        self.assertEqual(importer.validate_derived_registry(frozen, second['registry'], originals, self.native), frozen)

    def test_registry_unknown_schema_and_unproven_derived_edits_fail(self):
        for key, value in [('display_name', 'forged'), ('description', 'forged'), ('group', ['other']),
                           ('upstream', 'https://example.invalid/schema'), ('unknown', True), ('legacy_sources', ['forged'])]:
            changed = copy.deepcopy(self.registry)
            changed['providers']['one'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                importer.validate_derived_registry(self.registry, changed, self.native, self.native)

    def test_runtime_new_provider_then_price_only_derives_default_registration(self):
        frozen, originals = copy.deepcopy(self.registry), copy.deepcopy(self.native)
        new = document('new', 'New API')
        new['paths'] = {'/new': {'get': {**new['paths']['/request']['get'], 'operationId': 'new'}}}
        self.facts['new'] = copy.deepcopy(new)
        self.native['new'] = new
        self.index['providers'].append({'id': 'new'})
        self.category['apis'].append({'id': 'new'})
        self.readiness['providers']['new'] = {}
        first = self.project()
        self.assertEqual(set(first['registry']['providers']), {'one', 'new'})
        self.assertEqual(importer.validate_derived_registry(frozen, first['registry'], originals, self.native), frozen)
        self.native['new']['paths']['/new']['get']['x-aisa-pricing']['default_request_estimate_usd'] = 2
        self.facts['new'] = copy.deepcopy(self.native['new'])
        second = self.project()
        self.assertEqual(first['registry'], second['registry'])
        forged = copy.deepcopy(second['registry'])
        forged['providers']['new']['upstream'] = 'https://example.invalid/schema'
        with self.assertRaises(ValueError):
            importer.validate_derived_registry(frozen, forged, originals, self.native)

    def test_final_source_scope_and_expiry_follow_new_coverage_not_stale_metadata(self):
        now = datetime(2026, 10, 16, tzinfo=timezone.utc)
        observed = {}
        sources = {}
        for name in ('scoped', 'global'):
            source = initial_policy({'kind': 'provider_openapi', 'url': 'https://example.invalid/' + name,
                'content_hash': 'sha256:' + name, 'refresh_policy': 'automatic'})
            sources[name] = source
            (self.root / ('openapi/upstream/' + name + '.json')).write_bytes(canonical({'info': {'x-aisa-source': source}, 'paths': {}}))
            at = now - timedelta(hours=25 if name == 'scoped' else 1)
            observed[receipt_key(source)] = acquisition_receipt(source, at)
        self.native['one']['paths']['/request']['get']['x-aisa-source'] = sources['scoped']
        (self.root / 'openapi/one.json').write_bytes(canonical(self.native['one']))
        (self.root / 'openapi/coverage.json').write_bytes(canonical({'providers': {'old': []}}))
        self.assertEqual(source_report(self.root, observed, checked_at=now)['status'], 'failed')
        projected = self.project()
        (self.root / 'openapi/coverage.json').write_bytes(canonical(projected['coverage']))
        governance = source_report(self.root, observed, checked_at=now)
        self.assertEqual(governance['source_scope']['sources']['scoped.json'], ['one'])
        self.assertEqual(governance['status'], 'passed')
        expiry, provider_expiry = source_expiry({'source_governance': governance, 'providers': {'one': {}}}, now)
        self.assertEqual(provider_expiry['one'], (now - timedelta(hours=1)).isoformat())
        self.assertGreater(datetime.fromisoformat(expiry), now)


class RegistryReplayTests(unittest.TestCase):
    setUp = MetadataTests.setUp
    write_registry = MetadataTests.write_registry
    project = MetadataTests.project
    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, stderr=subprocess.PIPE)

    def seal_publication(self, contract_release):
        names = ['openapi/registry.yaml', 'openapi/one.json']
        pointer = {'contract_release': contract_release,
                   'files_sha256': {name: sha((self.root / name).read_bytes()) for name in names}}
        path = self.root / 'docs/publication/current.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical(pointer))
        self.git('add', '.')
        self.git('-c', 'user.name=Ken', '-c', 'user.email=ken@aisa.one', 'commit', '-qm', 'Fixture publication')
        return self.git('rev-parse', 'HEAD').decode().strip()

    def reviewed_provider_registration(self):
        self.git('init', '-q')
        previous = self.seal_publication('a' * 64)
        prior_native = (self.root / 'openapi/one.json').read_bytes()
        self.registry['providers']['new'] = {'display_name': 'New API', 'description': ''}
        self.write_registry()
        for name in ('context.json', 'source-receipts.json'):
            path = self.root / 'docs/schema-inputs' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'{}\n')
        (self.root / 'openapi/new.json').write_bytes(canonical(document('new', 'Draft only')))
        self.git('add', '.')
        self.git('-c', 'user.name=Ken', '-c', 'user.email=ken@aisa.one',
                 'commit', '-qm', 'Reviewed provider registration')
        revision = self.git('rev-parse', 'HEAD').decode().strip()
        # Input loading/authentication is tested separately. This seam receives
        # a verified bundle whose compatibility document is the original one.
        bundle = SimpleNamespace(contents={
            'input/openapi/registry.yaml': (self.root / 'openapi/registry.yaml').read_bytes(),
            'input/openapi/one.json': prior_native,
        })
        return previous, revision, bundle

    def reviewed_input_view(self, previous, revision, bundle):
        with patch('publication_origin.inspect_publication', return_value={
                'expected_docs_ref': previous, 'contract_release': 'a' * 64}), \
             patch('canonical_input_assessment.load_reviewed_inputs', return_value=bundle):
            return importer.schema_input_view_files(self.root, self.root, revision, previous,
                compiler_inputs={'docs_ref': revision, 'bundle_manifest_sha256': 'b' * 64})

    def test_reviewed_new_provider_draft_is_not_used_as_a_formal_input(self):
        previous, revision, bundle = self.reviewed_provider_registration()
        files, _ = self.reviewed_input_view(previous, revision, bundle)
        self.assertNotIn('openapi/new.json', files)
        self.assertEqual(files['openapi/one.json'], bundle.contents['input/openapi/one.json'])

    def test_reviewed_registration_still_rejects_unregistered_extra_native(self):
        previous, revision, bundle = self.reviewed_provider_registration()
        (self.root / 'openapi/rogue.json').write_bytes(canonical(document('rogue')))
        with self.assertRaisesRegex(ValueError, 'Current native graph differs'):
            self.reviewed_input_view(previous, revision, bundle)

    def test_reviewed_registration_still_rejects_changes_to_prior_native_bytes(self):
        previous, revision, bundle = self.reviewed_provider_registration()
        path = self.root / 'openapi/one.json'
        path.write_bytes(path.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'Prior native publication differs'):
            self.reviewed_input_view(previous, revision, bundle)

    def test_reviewed_registration_still_rejects_missing_prior_native(self):
        previous, revision, bundle = self.reviewed_provider_registration()
        (self.root / 'openapi/one.json').unlink()
        with self.assertRaises((ValueError, OSError)):
            self.reviewed_input_view(previous, revision, bundle)

    def test_unreviewed_extra_native_still_requires_prior_formal_membership(self):
        self.git('init', '-q')
        previous = self.seal_publication('a' * 64)
        (self.root / 'openapi/new.json').write_bytes(canonical(document('new')))
        with patch('publication_origin.inspect_publication', return_value={
                'expected_docs_ref': previous, 'contract_release': 'a' * 64}), \
             self.assertRaisesRegex(ValueError, 'Current native graph differs'):
            importer.schema_input_view_files(self.root, self.root, previous, previous)

    def test_two_real_git_publication_views_restore_same_frozen_schema_registry(self):
        self.git('init', '-q')
        frozen = self.seal_publication('a' * 64)
        frozen_registry = (self.root / 'openapi/registry.yaml').read_bytes()
        self.facts['one']['info']['title'] = 'Runtime title changed'
        self.native['one']['info']['title'] = 'Runtime title changed'
        first = self.project()
        (self.root / 'openapi/one.json').write_bytes(canonical(self.native['one']))
        (self.root / 'openapi/registry.yaml').write_text(yaml.safe_dump(first['registry']))
        first_ref = self.seal_publication('b' * 64)
        with patch('publication_origin.inspect_publication', return_value={
                'expected_docs_ref': first_ref, 'contract_release': 'b' * 64}):
            files, _ = importer.schema_input_view_files(self.root, self.root, frozen, first_ref)
        self.assertEqual(files['openapi/registry.yaml'], frozen_registry)
        # No new schema bundle or source receipt is created for the price change.
        self.native['one']['paths']['/request']['get']['x-aisa-pricing']['default_request_estimate_usd'] = 2
        (self.root / 'openapi/one.json').write_bytes(canonical(self.native['one']))
        second_ref = self.seal_publication('c' * 64)
        with patch('publication_origin.inspect_publication', return_value={
                'expected_docs_ref': second_ref, 'contract_release': 'c' * 64}):
            second_files, _ = importer.schema_input_view_files(self.root, self.root, frozen, second_ref)
        self.assertEqual(files, second_files)
        self.assertEqual(second_files['openapi/registry.yaml'], frozen_registry)
        changed = copy.deepcopy(first['registry'])
        changed['providers']['one']['group'] = ['different']
        (self.root / 'openapi/registry.yaml').write_text(yaml.safe_dump(changed))
        bad_ref = self.seal_publication('d' * 64)
        with patch('publication_origin.inspect_publication', return_value={
                'expected_docs_ref': bad_ref, 'contract_release': 'd' * 64}), \
             self.assertRaisesRegex(ValueError, 'fixed schema configuration'):
            importer.schema_input_view_files(self.root, self.root, frozen, bad_ref)


class AcquiredBytesTests(unittest.TestCase):
    def test_post_assessment_current_member_receipt_and_category_changes_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            member, category = b'{"paths":{}}', b'{"apis":[]}'
            before = canonical({'files': [{'name': 'index.json', 'sha256': sha(member)}]})
            receipt = canonical({'category_sha256': sha(category)})
            originals = {'current-before.json': before, 'current-after.json': before,
                'acquisition-receipt.json': receipt, 'index.json': member, 'category.json': category}
            for name, raw in originals.items():
                (root / name).write_bytes(raw)
            assessment = {'current_before_sha256': sha(before), 'current_after_sha256': sha(before),
                          'runtime_acquisition_sha256': sha(receipt)}
            self.assertEqual(importer.acquired_members(root, assessment)['index.json'], member)
            for name, raw in originals.items():
                (root / name).write_bytes(raw + b' ')
                with self.subTest(name=name), self.assertRaises(ValueError):
                    importer.acquired_members(root, assessment)
                (root / name).write_bytes(raw)


class SurfaceProjectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = surfaces.PublicationSurfaceTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        (self.root / 'llms.txt').write_text('Discovery\n')
        self.raw = {'fixture': (self.root / 'openapi/fixture.json').read_bytes()}
        self.metadata = {'registry': {'providers': {'fixture': {}}}, 'coverage': {'providers': {'fixture': []}},
                         'pending': {'providers': {'fixture': []}}}

    def test_exact_native_bytes_retained_and_page_semantics_revalidated(self):
        original = copy.deepcopy(self.raw)
        changes = importer.project_surfaces(self.root, self.raw, self.raw['fixture'], self.metadata)
        self.assertEqual(changes['openapi/fixture.json'], self.raw['fixture'])
        self.assertEqual(changes['openapi/openapi.json'], self.raw['fixture'])
        self.assertEqual(self.raw, original)
        for name, raw in changes.items():
            path = self.root / name;path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes(raw)
        self.assertEqual(surfaces.validate_surfaces(self.root)['operations'], 1)

    def test_projected_gate_rejects_changed_runtime_bytes_metadata_or_sources(self):
        for name in (POLICY_PATH, REBINDING_PATH):
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'{}')
        # Immutable input view remains distinct from the output being reviewed.
        with tempfile.TemporaryDirectory() as folder:
            import shutil
            projected = Path(folder) / 'projected'
            shutil.copytree(self.root, projected)
            changes = importer.project_surfaces(self.root, self.raw, self.raw['fixture'], self.metadata)
            for name, raw in changes.items():
                path = projected / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
            def check():
                return importer.assess_projected_candidate(self.root, projected, self.raw, self.raw['fixture'],
                    self.metadata, baseline_coverage={'providers': {}}, published_ref=None,
                    source_receipts={'receipts': {}}, checked_at=datetime.now(timezone.utc))
            for name, changed, error in [
                ('openapi/fixture.json', self.raw['fixture'] + b' ', 'native bytes differ'),
                ('openapi/openapi.json', self.raw['fixture'] + b' ', 'aggregate bytes differ'),
                ('openapi/coverage.json', b'{"providers":{"old":[]}}', 'metadata differs'),
                (POLICY_PATH, b'{"different":true}', 'source authority inputs')]:
                path = projected / name; previous = path.read_bytes(); path.write_bytes(changed)
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, error):
                    check()
                path.write_bytes(previous)

    def test_mismatched_canonical_page_url_rejected_without_rewriting_producer(self):
        value = json.loads(self.raw['fixture'])
        value['paths']['/one']['get']['x-aisa-docs-url'] = 'https://aisa.one/docs/wrong'
        self.raw['fixture'] = canonical(value)
        with self.assertRaisesRegex(ValueError, 'Canonical page binding differs'):
            importer.project_surfaces(self.root, self.raw, self.raw['fixture'], self.metadata)


if __name__ == '__main__':
    unittest.main()
