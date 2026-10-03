import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_contract_candidate import assess_candidate, load_baseline, verified_retained_coverage
from pull_openapi import existing_page_references, main, stage
import pull_openapi


class CandidateReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'openapi').mkdir()
        self.facts = self.root / 'facts'
        self.facts.mkdir()
        (self.root / 'openapi/registry.yaml').write_text('auto_register: true\nproviders:\n  alpha: {}\n')
        (self.root / 'docs.json').write_text(json.dumps({'navigation': {'languages': [
            {'language': language, 'tabs': [{'tab': tab, 'groups': []}]}
            for language, tab in [('en', 'API Reference'), ('zh', 'API 参考')]]}}))
        self.fact = {'openapi': '3.1.0', 'servers': [{'url': 'https://api.aisa.one'}],
                     'info': {'title': 'Alpha', 'version': '1', 'x-aisa-document': {'facts_hash': 'sha256:alpha'}},
                     'paths': {'/apis/v1/alpha/read': {'get': {'operationId': 'alpha_read',
                         'summary': 'Read', 'x-aisa-validation': 'runtime', 'x-aisa-status': 'enabled',
                         'responses': {'200': {'description': 'Success', 'content': {
                             'application/json': {'schema': {'type': 'object'}}}}}}}}}
        self.index = {'providers': [{'id': 'alpha', 'endpoint_count': 1, 'operation_count': 1}],
                      'pending_providers': [], 'pending_endpoints': [],
                      'coverage': {'inventory_endpoint_count': 1, 'selected_endpoint_count': 1,
                                   'projected_endpoint_count': 1, 'pending_endpoint_count': 0,
                                   'excluded_endpoints': [],
                                   'projected_endpoints': [{'provider': 'alpha', 'path': '/apis/v1/alpha/read'}]}}
        self.write_facts()

    def tearDown(self):
        self.tmp.cleanup()

    def write_facts(self):
        (self.facts / 'alpha.json').write_text(json.dumps(self.fact))
        (self.facts / 'index.json').write_text(json.dumps(self.index))
        (self.facts / 'category.json').write_text(json.dumps({'apis': [{'id': p['id']} for p in self.index['providers']]}))

    def publish(self, *extra):
        with patch.object(sys, 'argv', ['pull_openapi.py', '--root', str(self.root),
                                       '--facts-dir', str(self.facts), '--write', *extra]), patch('builtins.print'):
            return main()

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.root, check=True, capture_output=True, text=True).stdout.strip()

    def baseline(self):
        self.git('init', '-q')
        self.git('config', 'user.name', 'Fixture Reviewer')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('add', 'openapi')
        self.git('commit', '-qm', 'Reviewed fixture coverage')
        return self.git('rev-parse', 'HEAD')

    def publish_official_fixture(self):
        op = self.fact['paths']['/apis/v1/alpha/read']['get']
        op.update({'x-aisa-validation': 'provider', 'x-aisa-upstream-path': '/read',
                   'x-aisa-query-policy': {'request_wins': True}, 'security': [{'Bearer': []}]})
        self.fact['components'] = {'securitySchemes': {'Bearer': {'type': 'http', 'scheme': 'bearer'}}}
        self.write_facts()
        (self.root / 'openapi/registry.yaml').write_text(
            'auto_register: true\nproviders:\n  alpha:\n    upstream: https://provider.example/openapi.json\n')
        (self.root / 'openapi/upstream').mkdir()
        source = {'openapi': '3.1.0', 'info': {'x-aisa-source': {
            'kind': 'provider_openapi', 'url': 'https://provider.example/openapi.json',
            'content_hash': 'sha256:fixture', 'fetched_at': '2026-09-30', 'converter': 'fixture@1'}},
            'paths': {'/read': {'get': {
                'parameters': [{'name': 'q', 'in': 'query', 'required': True, 'schema': {'type': 'integer'}}],
                'requestBody': {'required': True, 'content': {'application/json': {'schema': {
                    'type': 'object', 'required': ['query'], 'properties': {'query': {'type': 'string'}}}}}}}}}}
        (self.root / 'openapi/upstream/alpha.json').write_text(json.dumps(source))
        self.assertEqual(self.publish(), 0)
        return self.root / 'openapi/alpha.json'

    def test_online_cache_shape_replays_offline_without_network(self):
        self.assertEqual(self.publish(), 0)
        cached = self.root / '.cache/runtime-contracts'
        self.assertTrue((cached / 'category.json').exists())
        self.assertTrue((cached / 'index.json').exists())
        with patch('pull_openapi.fetch_json', side_effect=AssertionError('network')), \
             patch('pull_openapi.import_source', side_effect=AssertionError('network')):
            result = assess_candidate(self.root, cached)
        self.assertEqual(result['status'], 'passed', result)

    def test_missing_cache_is_not_assessed(self):
        result = assess_candidate(self.root, self.root / 'missing')
        self.assertEqual(result['status'], 'not_assessed')

    def test_actual_conflicting_documents_fail_before_regeneration(self):
        for provider in ('one', 'two'):
            document = copy.deepcopy(self.fact)
            document['paths'] = {f'/{provider}': {'get': {'operationId': 'conflicting'}}}
            (self.root / f'openapi/{provider}.json').write_text(json.dumps(document))
        result = assess_candidate(self.root, self.root / 'missing')
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['global_errors'])

    def test_actual_request_body_missing_is_not_hidden_by_regeneration(self):
        op = self.fact['paths']['/apis/v1/alpha/read']['get']
        op['requestBody'] = {'content': {'application/json': {'schema': {'type': 'object', 'properties': {'q': {'type': 'string'}}}}}}
        self.write_facts()
        self.assertEqual(self.publish(), 0)
        path = self.root / 'openapi/alpha.json'
        document = json.loads(path.read_text())
        del document['paths']['/apis/v1/alpha/read']['get']['requestBody']
        document['info']['x-aisa-document']['document_hash'] = 'sha256:modified-candidate'
        path.write_text(json.dumps(document))
        report = assess_candidate(self.root, self.facts)
        self.assertEqual(report['composed_candidate']['status'], 'passed', report)
        self.assertEqual(report['status'], 'failed')
        self.assertIn('missing_runtime_request_body', [e['code'] for e in report['providers']['alpha']['errors']])

    def test_actual_coverage_omission_is_not_hidden_by_regeneration(self):
        self.assertEqual(self.publish(), 0)
        (self.root / 'openapi/coverage.json').write_text(json.dumps({'providers': {'alpha': []}}))
        report = assess_candidate(self.root, self.facts)
        self.assertEqual(report['composed_candidate']['status'], 'passed')
        self.assertEqual(report['status'], 'failed')

    def test_global_failure_writes_nothing(self):
        self.index['coverage']['inventory_endpoint_count'] = 9
        self.write_facts()
        before = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(self.publish(), 3)
        after = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_missing_index_writes_nothing_even_when_pending(self):
        self.fact['paths']['/apis/v1/alpha/read']['get']['x-aisa-validation'] = 'provider'
        self.write_facts()
        (self.facts / 'index.json').unlink()
        self.assertEqual(self.publish(), 3)
        self.assertFalse((self.root / 'openapi/alpha.json').exists())

    def test_scheduled_new_pending_never_becomes_accepted_baseline(self):
        self.fact['paths']['/apis/v1/alpha/read']['get']['x-aisa-validation'] = 'provider'
        self.write_facts()
        self.assertEqual(self.publish(), 0)
        self.assertEqual(self.publish('--readiness-mode', 'pr'), 1)
        report = assess_candidate(self.root, self.facts)
        self.assertEqual(report['status'], 'failed')
        self.assertFalse(report['baseline_assessed'])
        self.assertEqual(len(report['providers']['alpha']['new_pending']), 1)

    def test_reviewed_revision_can_accept_exact_pending_without_auto_advancing(self):
        self.fact['paths']['/apis/v1/alpha/read']['get']['x-aisa-validation'] = 'provider'
        self.write_facts()
        self.assertEqual(self.publish(), 0)
        accepted = self.baseline()
        accepted_binding = load_baseline(self.root, accepted)['providers']['alpha'][0]['binding_hash']
        self.assertEqual(assess_candidate(self.root, self.facts, accepted)['status'], 'passed')
        self.fact['paths']['/apis/v1/alpha/read']['get']['x-aisa-upstream-path'] = '/changed'
        self.write_facts()
        self.assertEqual(self.publish(), 0)
        report = assess_candidate(self.root, self.facts, accepted)
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(len(report['providers']['alpha']['new_pending']), 1)
        self.assertEqual(load_baseline(self.root, accepted)['providers']['alpha'][0]['binding_hash'], accepted_binding)
        self.assertNotEqual(json.loads((self.root / 'openapi/coverage.json').read_text())['providers']['alpha'][0]['binding_hash'], accepted_binding)

    def test_symbolic_baseline_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'full reviewed Git'):
            load_baseline(self.root, 'HEAD')

    def test_index_pending_provider_does_not_block_available_provider(self):
        self.index['pending_providers'] = [{'id': 'unavailable', 'endpoint_count': 1}]
        self.index['pending_endpoints'] = [{'provider': 'unavailable', 'path': '/apis/v1/unavailable/read', 'reason': 'identity_unmapped'}]
        self.index['coverage'].update(inventory_endpoint_count=2, selected_endpoint_count=2, pending_endpoint_count=1)
        self.write_facts()
        self.assertEqual(self.publish(), 0)
        self.assertTrue((self.root / 'openapi/alpha.json').exists())
        coverage = json.loads((self.root / 'openapi/coverage.json').read_text())
        row = coverage['providers']['unavailable'][0]
        self.assertEqual(row['path'], '/apis/v1/unavailable/read')
        self.assertEqual(row['method'], 'ANY')
        self.assertEqual(row['publication_state'], 'retained')

    def test_candidate_cannot_invent_retained_history(self):
        self.fact['paths']['/apis/v1/alpha/read']['get']['x-aisa-validation'] = 'provider'
        self.write_facts()
        self.assertEqual(self.publish(), 0)
        accepted = self.baseline()
        self.assertEqual(assess_candidate(self.root, self.facts, accepted)['status'], 'passed')
        coverage_path = self.root / 'openapi/coverage.json'
        coverage = json.loads(coverage_path.read_text())
        coverage['providers']['alpha'][0]['publication_state'] = 'retained'
        coverage_path.write_text(json.dumps(coverage))
        document_path = self.root / 'openapi/alpha.json'
        document = json.loads(document_path.read_text())
        document['paths'] = copy.deepcopy(self.fact['paths'])
        document_path.write_text(json.dumps(document))
        report = assess_candidate(self.root, self.facts, accepted)
        self.assertEqual(report['status'], 'failed')
        self.assertIn('pending_published_as_complete', [error['code'] for error in report['providers']['alpha']['errors']])

    def test_actual_requiredness_and_type_changes_fail(self):
        op = self.fact['paths']['/apis/v1/alpha/read']['get']
        op['parameters'] = [{'name': 'q', 'in': 'query', 'required': True, 'schema': {'type': 'integer'}}]
        self.write_facts()
        self.assertEqual(self.publish(), 0)
        path = self.root / 'openapi/alpha.json'
        document = json.loads(path.read_text())
        parameter = document['paths']['/apis/v1/alpha/read']['get']['parameters'][0]
        parameter.update(required=False, schema={'type': 'string'})
        path.write_text(json.dumps(document))
        report = assess_candidate(self.root, self.facts)
        self.assertEqual(report['status'], 'failed')
        self.assertTrue(report['providers']['alpha']['errors'])

    def test_upstream_response_tampering_fails_without_document_hash_change(self):
        self.publish_official_fixture()
        op = self.fact['paths']['/apis/v1/alpha/read']['get']
        op['x-aisa-passthrough'] = True
        self.write_facts()
        source_path = self.root / 'openapi/upstream/alpha.json'
        source = json.loads(source_path.read_text())
        source['paths']['/read']['get']['responses'] = {'200': {'description': 'Current payload',
            'content': {'application/json': {'schema': {'type': 'integer'}}}}}
        source_path.write_text(json.dumps(source))
        self.assertEqual(self.publish(), 0)
        path = self.root / 'openapi/alpha.json'
        original = json.loads(path.read_text())
        for change in ('schema', 'missing', 'false_pending'):
            with self.subTest(change=change):
                document = copy.deepcopy(original)
                actual = document['paths']['/apis/v1/alpha/read']['get']
                if change == 'schema':
                    actual['responses']['200']['content']['application/json']['schema']['type'] = 'string'
                elif change == 'missing':
                    actual['responses']['200'].pop('content')
                else:
                    actual['x-aisa-response-pending'] = {'reason': 'invented uncertainty'}
                path.write_text(json.dumps(document))
                report = assess_candidate(self.root, self.facts)
                self.assertEqual(report['status'], 'failed', report)
                self.assertIn('composed_response_contract_mismatch', [e['code'] for e in report['providers']['alpha']['errors']])
                before = path.read_bytes()
                self.assertEqual(self.publish(), 1)
                self.assertEqual(path.read_bytes(), before)

    def test_upstream_request_tampering_fails_without_document_hash_change(self):
        path = self.publish_official_fixture()
        original = json.loads(path.read_text())
        for change in ('parameter', 'body', 'local_ref', 'inherited_parameter', 'public_auth'):
            with self.subTest(change=change):
                document = copy.deepcopy(original)
                item = document['paths']['/apis/v1/alpha/read']
                op = item['get']
                if change == 'parameter':
                    op['parameters'][0].update(required=False, schema={'type': 'string'})
                elif change == 'body':
                    op['requestBody']['required'] = False
                    op['requestBody']['content']['application/json']['schema']['properties']['query']['type'] = 'integer'
                elif change == 'local_ref':
                    document.setdefault('components', {}).setdefault('schemas', {})['CandidateQuery'] = {'type': 'string'}
                    op['parameters'][0]['schema'] = {'$ref': '#/components/schemas/CandidateQuery'}
                elif change == 'inherited_parameter':
                    item['parameters'] = op.pop('parameters')
                    item['parameters'][0]['required'] = False
                else:
                    op['security'] = []
                self.assertEqual(original['info']['x-aisa-document']['document_hash'],
                                 document['info']['x-aisa-document']['document_hash'])
                path.write_text(json.dumps(document))
                report = assess_candidate(self.root, self.facts)
                self.assertEqual(report['status'], 'failed', report)
                self.assertIn('composed_request_contract_mismatch', [e['code'] for e in report['providers']['alpha']['errors']])
                # Scheduled --write also checks the bytes selected by hash
                # reuse; it cannot publish corrupted history as fresh output.
                before = path.read_bytes()
                self.assertEqual(self.publish(), 1)
                self.assertEqual(path.read_bytes(), before)

    def test_upstream_editorial_changes_and_equivalent_local_refs_are_allowed(self):
        path = self.publish_official_fixture()
        document = json.loads(path.read_text())
        item = document['paths']['/apis/v1/alpha/read']
        op = item['get']
        op.update(description='Editorial operation prose', summary='Editorial title')
        item['parameters'] = op.pop('parameters')
        parameter = item['parameters'][0]
        parameter.update(description='Editorial parameter prose', example=123, style='form', explode=True)
        document.setdefault('components', {}).setdefault('schemas', {})['EquivalentQuery'] = {
            'type': 'integer', 'description': 'Editorial schema prose'}
        parameter['schema'] = {'$ref': '#/components/schemas/EquivalentQuery'}
        op['requestBody']['description'] = 'Editorial body prose'
        op['requestBody']['content']['application/json']['example'] = {'query': 'hello'}
        op['responses']['200']['description'] = 'Response-only editorial change'
        path.write_text(json.dumps(document))
        report = assess_candidate(self.root, self.facts)
        self.assertEqual(report['status'], 'passed', report)
        self.assertEqual(self.publish(), 0)

    def test_retained_reference_closure_and_inherited_auth_are_verified(self):
        document = copy.deepcopy(self.fact)
        document['components'] = {'schemas': {'Query': {'type': 'integer'}},
                                  'securitySchemes': {'Bearer': {'type': 'http', 'scheme': 'bearer'}}}
        document['security'] = [{'Bearer': []}]
        document['paths']['/apis/v1/alpha/read']['get']['requestBody'] = {
            'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Query'}}}}
        (self.root / 'openapi/alpha.json').write_text(json.dumps(document))
        coverage = {'providers': {'alpha': [{'path': '/apis/v1/alpha/read', 'method': 'GET',
                                            'status': 'pending', 'publication_state': 'retained'}]}}
        (self.root / 'openapi/coverage.json').write_text(json.dumps(coverage))
        published = self.baseline()
        verified = verified_retained_coverage(self.root, coverage, {'alpha': document}, published)
        self.assertEqual(verified['providers']['alpha'][0]['publication_state'], 'retained')
        for change in ('schema', 'authentication', 'inherited_parameter'):
            with self.subTest(change=change):
                altered = copy.deepcopy(document)
                if change == 'schema':
                    altered['components']['schemas']['Query']['type'] = 'string'
                elif change == 'authentication':
                    altered['components']['securitySchemes']['Bearer']['scheme'] = 'basic'
                else:
                    altered['paths']['/apis/v1/alpha/read']['parameters'] = [
                        {'name': 'q', 'in': 'query', 'required': True, 'schema': {'type': 'string'}}]
                checked = verified_retained_coverage(self.root, coverage, {'alpha': altered}, published)
                self.assertNotIn('publication_state', checked['providers']['alpha'][0])

    def test_mismatched_cache_hash_cannot_be_assessed_as_fresh(self):
        self.index['providers'][0]['facts_hash'] = 'sha256:alpha'
        self.write_facts()
        self.assertEqual(self.publish(), 0)
        cached = self.root / '.cache/runtime-contracts'
        changed = json.loads((cached / 'alpha.json').read_text())
        changed['info']['x-aisa-document']['facts_hash'] = 'sha256:stale'
        (cached / 'alpha.json').write_text(json.dumps(changed))
        report = assess_candidate(self.root, cached)
        self.assertNotEqual(report['status'], 'passed')
        self.assertTrue(report['providers']['alpha']['missing_inputs'])

    def test_each_page_reference_spec_is_parsed_once(self):
        (self.root / 'openapi/alpha.json').write_text(json.dumps(self.fact))
        pages = self.root / 'api-reference/alpha'
        pages.mkdir(parents=True)
        for i in range(20):
            (pages / f'page-{i}.mdx').write_text('---\nopenapi: "openapi/alpha.json GET /apis/v1/alpha/read"\n---\n')
        with patch('pull_openapi.read_json', wraps=pull_openapi.read_json) as reads:
            references = existing_page_references(self.root)
        self.assertEqual(len(references), 20)
        self.assertEqual(reads.call_count, 1)


if __name__ == '__main__':
    unittest.main()
