"""Real temporary Git input promotion; approval/Runtime fixtures are not live evidence."""
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).parent)]
import canonical_input_assessment as assessment
import canonical_import as importer
import export_schema_input_bundle as exporter
import fetch_runtime_release as fetch
import schema_input_bundle as bundle
import check_reviewed_schema_inputs as gate
from contract_change_scope import git_changed_paths, is_reviewed_input_change
from source_governance import initial_policy, acquisition_receipt, receipt_key, source_report
import test_runtime_contract_artifact as runtime_fixture


class ReviewedInputTests(unittest.TestCase):
    now = datetime(2026, 10, 16, tzinfo=timezone.utc)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'repo'
        self.root.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Ken')
        self.git('config', 'user.email', 'ken@aisa.one')
        self.write('.gitignore', b'.cache/\n')
        self.baseline = bundle.canonical({'providers': {'one': []}})
        # The independent baseline fixture is injected at this one Git boundary;
        # every candidate/history/source byte and ancestry check uses actual Git.
        original_read = exporter.GitSource.read
        baseline = self.baseline
        def read(source, ref, name):
            return baseline if ref == bundle.REVIEWED_BASELINE and name == 'openapi/coverage.json' else original_read(source, ref, name)
        self.start(patch.object(exporter.GitSource, 'read', read))
        self.start(patch.object(bundle, 'REVIEWED_BASELINE_SHA256', bundle.sha(self.baseline)))
        self.registry = b'providers:\n  one:\n    display_name: One\n    description: ""\n    upstream: {url: "https://example.invalid/source.json", file: one.json}\n'
        self.write('openapi/registry.yaml', self.registry)
        self.source = initial_policy({'kind': 'provider_openapi', 'url': 'https://example.invalid/source.json',
            'content_hash': 'sha256:' + '1' * 64, 'refresh_policy': 'automatic',
            'fetched_at': self.now.isoformat(), 'converter': 'fixture@1'})
        self.upstream = {'openapi': '3.1.0', 'info': {'x-aisa-source': self.source}, 'paths': {
            '/request': {'get': {'operationId': 'one', 'parameters': [
                {'name': 'query', 'in': 'query', 'required': False, 'schema': {'type': 'string'}}],
                'responses': {'200': {'description': 'OK', 'content': {
                    'application/json': {'schema': {'type': 'object'}}}}}}}}}
        self.write('openapi/upstream/one.json', bundle.canonical(self.upstream))
        native = copy.deepcopy(self.upstream)
        native['info'] = {'title': 'One', 'description': '', 'x-aisa-provider': 'one',
                          'x-aisa-document': {'facts_hash': 'a' * 64}, 'x-aisa-catalogs': {'one': {}}}
        native['servers'] = [{'url': 'https://api.aisa.one'}]
        self.write('openapi/one.json', bundle.canonical(native))
        self.write('openapi/coverage.json', self.baseline)
        self.write('openapi/pending.json', b'{"providers":{"one":[]}}')
        checkout = Path(__file__).resolve().parents[2]
        for name in (bundle.POLICY_PATH, bundle.REBINDING_PATH):
            self.write(name, (checkout / name).read_bytes())
        self.write('api-reference/one.mdx', b'---\nopenapi: "openapi/one.json GET /request"\n---\n')
        paths = [p.relative_to(self.root).as_posix() for p in self.root.rglob('*') if p.is_file() and '.git' not in p.parts]
        self.hashes = {name: bundle.sha((self.root / name).read_bytes()) for name in paths}
        report = {'status': 'passed', 'baseline_ref': bundle.REVIEWED_BASELINE, 'baseline_assessed': True,
                  'source_governance': source_report(self.root, self.receipts(self.source)['receipts'], checked_at=self.now)}
        self.write('docs/publication/formal-contract-readiness.json', bundle.canonical(report))
        pointer = {'schema_version': 1, 'status': 'passed', 'runtime': {}, 'files_sha256': self.hashes,
            'formal_readiness': {'path': 'docs/publication/formal-contract-readiness.json',
                                'sha256': bundle.sha(bundle.canonical(report))}}
        pointer['contract_release'] = bundle.sha(bundle.canonical({k: pointer[k] for k in
            ('schema_version', 'runtime', 'files_sha256')}).rstrip(b'\n'))
        self.release = pointer['contract_release']
        self.write('docs/publication/current.json', bundle.canonical(pointer))
        self.formal = self.commit('Historical compatibility fixture, not live formal provenance')
        # This is a new reviewed-input fixture, with its own real fixture receipt;
        # no generated native/current publication is changed to make it pass.
        self.source = initial_policy({**self.source, 'content_hash': 'sha256:' + '2' * 64})
        self.upstream['info']['x-aisa-source'] = self.source
        self.upstream['paths']['/request']['get']['parameters'][0]['required'] = True
        self.write('openapi/upstream/one.json', bundle.canonical(self.upstream))
        self.saved = self.receipts(self.source)
        raw = bundle.canonical(self.saved)
        self.write(bundle.INPUT_RECEIPTS_PATH, raw)
        self.context = {'schema_version': 1, 'kind': 'aisa-reviewed-schema-input-context',
            'historical_formal_ref': self.formal, 'source_receipts_path': bundle.INPUT_RECEIPTS_PATH,
            'source_receipts_sha256': bundle.sha(raw), 'source_checked_at': self.now.isoformat()}
        self.write(bundle.INPUT_CONTEXT_PATH, bundle.canonical(self.context))
        self.ref = self.commit('Reviewed input fixture; no formal publication')
        self.write('.cache/source-reviews.json', raw)

    def start(self, patcher):
        result = patcher.start(); self.addCleanup(patcher.stop); return result

    def write(self, name, raw):
        path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, stderr=subprocess.PIPE)

    def commit(self, message):
        self.git('add', '.'); self.git('commit', '-qm', message)
        return self.git('rev-parse', 'HEAD').decode().strip()

    def receipts(self, source, when=None):
        return {'schema_version': 1, 'receipts': {receipt_key(source): acquisition_receipt(source, when or self.now)}, 'attempts': {}}

    def export(self, name='bundle'):
        output = Path(self.temp.name) / name
        result = exporter.export_reviewed_bundle(self.root, self.ref, output)
        return result, output

    def load(self, output, result):
        return bundle.load_bundle(output, expected_manifest_sha256=result['manifest_sha256'], expected_docs_ref=self.ref)

    def test_new_schema_deterministic_without_new_formal_or_actions(self):
        with patch('publication_origin.inspect_publication', side_effect=AssertionError('No old Actions lookup')):
            first, one = self.export('one'); second, two = self.export('two')
            self.assertEqual(first, second)
            self.assertEqual({p.relative_to(one): p.read_bytes() for p in one.rglob('*') if p.is_file()},
                             {p.relative_to(two): p.read_bytes() for p in two.rglob('*') if p.is_file()})
            verified = self.load(one, first)
        current = bundle.strict_json(verified.contents['input/openapi/upstream/one.json'])
        old = bundle.strict_json(verified.contents['input/openapi/one.json'])
        self.assertTrue(current['paths']['/request']['get']['parameters'][0]['required'])
        self.assertFalse(old['paths']['/request']['get']['parameters'][0]['required'])
        self.assertEqual(verified.validation['current_source_freshness'], 'not_assessed')
        self.assertEqual(verified.validation['source_checked_at'], self.now.isoformat())
        self.assertEqual(self.git('show', self.ref + ':docs/publication/current.json'),
                         self.git('show', self.formal + ':docs/publication/current.json'))
        with self.assertRaisesRegex(ValueError, 'Reviewed input refs require bundle v3'):
            exporter.export_bundle(self.root, self.ref, bundle.REVIEWED_BASELINE,
                self.root / bundle.INPUT_RECEIPTS_PATH, Path(self.temp.name) / 'v2', bundle_version=2)

    def test_context_receipt_paths_hashes_and_external_bundle_pin_are_closed(self):
        result, output = self.export()
        with self.assertRaisesRegex(ValueError, 'caller trust pin'):
            bundle.load_bundle(output, expected_manifest_sha256='0' * 64, expected_docs_ref=self.ref)
        for change in ({'source_receipts_path': '../escape'}, {'source_receipts_sha256': '0' * 64},
                       {'kind': 'formal_publication'}, {'schema_version': True}, {'extra': True}):
            self.write(bundle.INPUT_CONTEXT_PATH, bundle.canonical({**self.context, **change}))
            self.ref = self.commit('Invalid recipe fixture')
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.export('bad-' + str(len(change)) + '-' + self.ref[:8])

    def test_unsupported_inputs_policy_tamper_and_unsafe_git_blobs_fail(self):
        self.write('openapi/overlays/one.json', b'{}'); self.ref = self.commit('Forbidden overlay')
        with self.assertRaisesRegex(ValueError, 'Overlay inputs'): self.export()
        (self.root / 'openapi/overlays/one.json').unlink()
        self.upstream['info']['x-aisa-source']['owner'] = 'unreviewed-new-owner'
        self.write('openapi/upstream/one.json', bundle.canonical(self.upstream)); self.ref = self.commit('Stale policy revision')
        with self.assertRaisesRegex(ValueError, 'source policy'): self.export()

    def bind_runtime(self):
        result, _ = self.export()
        release = runtime_fixture.CanonicalArtifactTests(); release.setUp()
        self.addCleanup(release.doCleanups)
        release.manifest.update(docs_ref=self.ref, bundle_manifest_sha256=result['manifest_sha256'])
        release.seal()
        release.current['compiler_inputs'] = {key: release.manifest[key] for key in assessment.BINDINGS}
        facts = Path(self.temp.name) / 'facts'; fetch.save(facts, release.acquire())
        return facts, release, result

    def test_input_assessment_binds_new_git_identity_and_preserves_current_receipts(self):
        facts, release, result = self.bind_runtime()
        with patch.object(assessment, 'inspect_publication', side_effect=AssertionError('R is not formal')):
            observed = assessment.assess_canonical_inputs(self.root, facts, checked_at=self.now)
        self.assertEqual(observed['schema_version'], 2)
        self.assertNotIn('source_formal_provenance', observed)
        self.assertNotIn('source_pointer_sha256', observed)
        self.assertEqual(observed['source_input_provenance']['expected_docs_ref'], self.ref)
        self.assertEqual(observed['frozen_input_files_sha256'][bundle.INPUT_CONTEXT_PATH], observed['input_context_sha256'])
        old = self.now - timedelta(days=2)
        current = self.receipts(self.source, old)
        self.write('.cache/source-reviews.json', bundle.canonical(current))
        observed = assessment.assess_canonical_inputs(self.root, facts, checked_at=self.now)
        self.assertEqual(observed['source_observations']['one.json']['last_successful_review_at'], old.isoformat())
        self.assertEqual(observed['source_observations']['one.json']['freshness'], 'overdue')
        self.assertNotEqual(observed['source_receipts_sha256'],
                            observed['source_input_provenance']['input_source_receipts_sha256'])
        self.write(bundle.INPUT_CONTEXT_PATH, bundle.canonical(self.context) + b' ')
        with self.assertRaisesRegex(ValueError, 'Current schema or policy differs'):
            assessment.assess_canonical_inputs(self.root, facts, checked_at=self.now)

    def test_reviewed_registry_delta_is_distinct_from_old_formal_history(self):
        self.registry = self.registry.replace(b'https://example.invalid/source.json', b'https://example.invalid/next.json')
        self.write('openapi/registry.yaml', self.registry)
        self.source = initial_policy({**self.source, 'url': 'https://example.invalid/next.json'})
        self.upstream['info']['x-aisa-source'] = self.source
        self.write('openapi/upstream/one.json', bundle.canonical(self.upstream))
        raw = bundle.canonical(self.receipts(self.source)); self.write(bundle.INPUT_RECEIPTS_PATH, raw)
        self.context['source_receipts_sha256'] = bundle.sha(raw)
        self.write(bundle.INPUT_CONTEXT_PATH, bundle.canonical(self.context))
        self.ref = self.commit('Explicitly reviewed registry/source change')
        result, _ = self.export()
        pins = {'docs_ref': self.ref, 'bundle_manifest_sha256': result['manifest_sha256']}
        auth = {'expected_docs_ref': self.formal, 'contract_release': self.release}
        with patch('publication_origin.inspect_publication', return_value=auth) as authenticated:
            files, lineage = importer.schema_input_view_files(self.root, self.root, self.ref, self.formal, compiler_inputs=pins)
        authenticated.assert_called_once_with(self.root, self.formal, historical=True)
        self.assertEqual(files['openapi/registry.yaml'], self.registry)
        self.write('openapi/registry.yaml', self.registry + b'unknown: true\n')
        with patch('publication_origin.inspect_publication', return_value=auth), self.assertRaisesRegex(ValueError, 'prior assessed projection'):
            importer.schema_input_view_files(self.root, self.root, self.ref, self.formal, compiler_inputs=pins)

    def facts_fixture(self):
        from test_fetch_runtime_release import encoded
        fact = bundle.strict_json(self.git('show', self.formal + ':openapi/one.json'))
        fact['info'].update(version='1', **{'x-aisa-document': {'facts_hash': 'c' * 64}})
        operation = fact['paths']['/request']['get']
        operation.update({'x-aisa-validation': 'provider', 'x-aisa-status': 'enabled',
            'x-aisa-upstream-path': '/request', 'summary': 'One',
            'x-aisa-query-policy': {'request_wins': True},
            'x-aisa-pricing': {'default_request_estimate_usd': 0.08}})
        operation.pop('parameters')  # Provider owns the declared request schema.
        index = {'pending_endpoints': [], 'pending_providers': [],
            'providers': [{'id': 'one', 'facts_hash': 'c' * 64, 'endpoint_count': 1, 'operation_count': 1}],
            'coverage': {'selected_endpoint_count': 1, 'projected_endpoint_count': 1,
                         'pending_endpoint_count': 0, 'inventory_endpoint_count': 1, 'excluded_endpoints': [],
                         'projected_endpoints': [{'provider': 'one', 'path': '/request'}]}}
        payload = {'index.json': encoded(index), 'providers/one.json': encoded(fact)}
        manifest = {'schema_version': 1, 'source_digest': 'a' * 64, 'compiler_revision': 'b' * 40,
            'files': [{'name': name, 'media_type': 'application/json', 'sha256': bundle.sha(raw)}
                      for name, raw in sorted(payload.items())]}
        revision = bundle.sha(encoded(manifest))
        current = {**manifest, 'artifact_revision': revision, 'fresh': True,
                   'generation': 3, 'published_generation': 3}
        def read(path):
            if path == '/public/api-contract/current': return encoded(current), {}
            if path == '/info/apis/category': return encoded({'apis': [{'id': 'one'}]}), {}
            raw = payload[path.removeprefix('/public/api-contract/releases/' + revision + '/')]
            return raw, {'etag': '"' + bundle.sha(raw) + '"'}
        facts = Path(self.temp.name) / 'gate-facts'
        fetch.save(facts, fetch.acquire(revision, manifest['compiler_revision'], read))
        return facts

    def test_git_scope_through_real_input_gate_export_and_existing_composer(self):
        self.assertTrue(is_reviewed_input_change(git_changed_paths(self.root, self.formal)))
        facts = self.facts_fixture()
        output = Path(self.temp.name) / 'assessed'
        with patch.object(gate, 'inspect_publication', return_value={'expected_docs_ref': self.formal}):
            result = gate.assess_reviewed_input(self.root, facts, self.formal, output, checked_at=self.now)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['scope'], 'reviewed_input_candidate_only_not_formal_publication_or_promotion')
        compiled = bundle.strict_json((output / 'candidate/native/one.json').read_bytes())
        self.assertTrue(compiled['paths']['/request']['get']['parameters'][0]['required'])
        self.assertEqual(compiled['paths']['/request']['get']['x-aisa-pricing']['default_request_estimate_usd'], 0.08)
        self.assertFalse((output / 'current.json').exists())
        self.write('docs/publication/release-origin.json', b'{}')
        self.commit('Input mixed with fake public origin')
        self.assertFalse(is_reviewed_input_change(git_changed_paths(self.root, self.formal)))
        with self.assertRaisesRegex(ValueError, 'closed source-only'):
            gate.assess_reviewed_input(self.root, facts, self.formal, Path(self.temp.name) / 'mixed', checked_at=self.now)

    def test_input_gate_checks_current_authorization_and_reuses_unchanged_real_receipt(self):
        facts = self.facts_fixture()
        with patch.object(gate, 'inspect_publication', return_value={'expected_docs_ref': self.formal}):
            with self.assertRaisesRegex(ValueError, 'Current input source authorization'):
                gate.assess_reviewed_input(self.root, facts, self.formal,
                    Path(self.temp.name) / 'expired', checked_at=self.now + timedelta(days=2))
            previous = self.ref
            receipt = (self.root / bundle.INPUT_RECEIPTS_PATH).read_bytes()
            self.write('openapi/registry.yaml', self.registry.replace(b'display_name: One', b'display_name: Reviewed'))
            # This is another assessment instant, not a new successful review.
            self.context['source_checked_at'] = (self.now + timedelta(seconds=1)).isoformat()
            self.write(bundle.INPUT_CONTEXT_PATH, bundle.canonical(self.context))
            self.ref = self.commit('Registry-only fixture input update')
            paths = git_changed_paths(self.root, previous)
            self.assertNotIn(bundle.INPUT_RECEIPTS_PATH, paths)
            self.assertTrue(is_reviewed_input_change(paths))
            result = gate.assess_reviewed_input(self.root, facts, previous,
                Path(self.temp.name) / 'registry', checked_at=self.now + timedelta(seconds=1))
        self.assertEqual((self.root / bundle.INPUT_RECEIPTS_PATH).read_bytes(), receipt)
        self.assertEqual(result['source_governance']['sources']['one.json']['last_successful_review_at'], self.now.isoformat())


if __name__ == '__main__': unittest.main()
