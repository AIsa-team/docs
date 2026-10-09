import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from refresh_upstream import preserve_removed, refresh

class RefreshTests(unittest.TestCase):
    def test_retention_never_replaces_new_parent_with_rewritten_old_dependency(self):
        from compose_openapi import resolve
        from upstream_semantics import compare_contracts
        response = {'responses': {'200': {'description': 'ok', 'content': {
            'application/json': {'schema': {'$ref': '#/components/schemas/Parent'}}}}}}
        old = {'info': {'x-aisa-source': {}}, 'paths': {
            '/removed': {'get': copy.deepcopy(response)},
            '/current': {'get': copy.deepcopy(response)}}, 'components': {'schemas': {
                'Parent': {'type': 'object', 'properties': {'child': {'$ref': '#/components/schemas/Child'}}},
                'Child': {'type': 'string'}}}}
        new = copy.deepcopy(old)
        del new['paths']['/removed']
        new['components']['schemas']['Child'] = {'type': 'integer'}
        expected_new = copy.deepcopy(new)
        candidate, removed = preserve_removed(old, new, 'provider.json')
        self.assertEqual(candidate['components']['schemas']['Parent'], expected_new['components']['schemas']['Parent'])
        self.assertEqual(candidate['components']['schemas']['Child'], {'type': 'integer'})
        for path, wanted in (('/current', 'integer'), ('/removed', 'string')):
            schema = candidate['paths'][path]['get']['responses']['200']['content']['application/json']['schema']
            self.assertEqual(resolve(schema, candidate)['properties']['child']['type'], wanted)
        self.assertEqual(new, expected_new)
        self.assertEqual(removed, ['GET /removed'])
        delta = compare_contracts(old, candidate)
        self.assertEqual([row['operation'] for row in delta['changed']], ['GET /current'])
        self.assertEqual(delta['removed'], [])

    def test_retention_isolates_recursive_ancestor_dependencies(self):
        from runtime_consolidate_openapi import merge_components
        old = {'components': {'schemas': {
            'A': {'properties': {'b': {'$ref': '#/components/schemas/B'}}},
            'B': {'properties': {'a': {'$ref': '#/components/schemas/A'}, 'value': {'$ref': '#/components/schemas/Value'}}},
            'Value': {'type': 'string'}}}}
        new = copy.deepcopy(old)
        new['components']['schemas']['Value'] = {'type': 'integer'}
        expected = copy.deepcopy(new)
        merge_components(new, old, 'old.json')
        for name, value in expected['components']['schemas'].items():
            self.assertEqual(new['components']['schemas'][name], value)
        self.assertEqual(new['components']['schemas']['Old_A']['properties']['b']['$ref'], '#/components/schemas/Old_B')
        self.assertEqual(new['components']['schemas']['Old_B']['properties']['a']['$ref'], '#/components/schemas/Old_A')
        self.assertEqual(new['components']['schemas']['Old_B']['properties']['value']['$ref'], '#/components/schemas/Old_Value')
        self.assertEqual(new['components']['schemas']['Old_Value']['type'], 'string')

    def test_deleted_upstream_operation_retains_its_renamed_components(self):
        old = {'paths': {'/old': {'get': {'operationId': 'old', 'responses': {'200': {'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Body'}}}}}}}}, 'components': {'schemas': {'Body': {'type': 'string'}}}}
        new = {'info': {'x-aisa-source': {'kind': 'provider_openapi'}}, 'paths': {'/new': {'get': {'operationId': 'new'}}}, 'components': {'schemas': {'Body': {'type': 'integer'}}}}
        result, removed = preserve_removed(old, new, 'provider.json')
        self.assertEqual(removed, ['GET /old'])
        self.assertEqual(result['components']['schemas']['Body']['type'], 'integer')
        ref = result['paths']['/old']['get']['responses']['200']['content']['application/json']['schema']['$ref'].split('/')[-1]
        self.assertEqual(result['components']['schemas'][ref]['type'], 'string')
        self.assertNotIn('/old', new['paths'])

    def test_private_pin_does_not_block_public_or_mapped_source_refresh(self):
        import json
        import tempfile
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'openapi/upstream').mkdir(parents=True)
            for name, kind, policy in [('private', 'provider_openapi', 'pinned'), ('public', 'provider_openapi', None), ('mapped', 'manual', 'automatic')]:
                source = {'kind': kind, 'url': 'https://example.test/' + name, 'content_hash': 'old'}
                if policy: source['refresh_policy'] = policy
                (root/'openapi/upstream'/(name+'.json')).write_text(json.dumps({'info': {'x-aisa-source': source}, 'paths': {}}))
            def acquire(name, url):
                self.assertNotEqual(name, 'private')
                return {'info': {'x-aisa-source': {'kind': 'provider_openapi' if name == 'public' else 'manual', 'content_hash': 'new'}}, 'paths': {}}
            fetch = Mock(side_effect=acquire)
            changes, report = refresh(root, fetch)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(len(changes), 2)
            self.assertEqual(report['failed'], {})
            self.assertIn('private', report['pinned'])
            self.assertEqual(set(report['updated']), {'public', 'mapped'})

    def test_failure_reports_prior_age_and_does_not_block_other_staged_updates(self):
        import json
        import tempfile
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'openapi/upstream').mkdir(parents=True)
            before = {'info': {'x-aisa-source': {'kind': 'provider_openapi',
                'url': 'https://example.test/schema', 'content_hash': 'old',
                'fetched_at': '2026-09-29T12:00:00+00:00', 'converter': 'fixture@1'}}, 'paths': {}}
            for name in ('failed', 'success'):
                (root/'openapi/upstream'/(name+'.json')).write_text(json.dumps(before))
            def acquire(name, url):
                if name == 'failed':
                    raise OSError('This error may include private acquisition details')
                updated = copy.deepcopy(before)
                updated['info']['x-aisa-source']['content_hash'] = 'new'
                return updated
            changes, report = refresh(root, acquire, datetime(2026, 9, 30, 12, tzinfo=timezone.utc))
            self.assertEqual(len(changes), 1)
            failure = report['failed']['failed']
            self.assertEqual(failure['status'], 'source_preserved')
            self.assertEqual(failure['failure'], 'OSError')
            self.assertEqual(failure['previous']['source_age_seconds'], 86400)
            self.assertEqual(failure['previous']['content_hash'], 'old')
            self.assertNotIn('private', json.dumps(report))
            self.assertEqual(json.loads((root/'openapi/upstream/failed.json').read_text()), before)

    def test_same_content_keeps_source_file_timestamp_and_records_fetch(self):
        import json
        import tempfile
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'openapi/upstream').mkdir(parents=True)
            before = {'info': {'x-aisa-source': {'kind': 'provider_openapi',
                'url': 'https://example.test/schema', 'content_hash': 'same',
                'fetched_at': '2026-09-29T12:00:00+00:00'}}, 'paths': {}}
            path = root/'openapi/upstream/provider.json'
            path.write_text(json.dumps(before))
            updated = copy.deepcopy(before)
            updated['info']['x-aisa-source']['fetched_at'] = '2026-09-30T12:00:00+00:00'
            changes, report = refresh(root, lambda *_: updated, datetime(2026, 9, 30, 12, tzinfo=timezone.utc))
            self.assertEqual(changes, {})
            self.assertEqual(report['checked']['provider']['status'], 'source_unchanged')
            self.assertEqual(report['checked']['provider']['previous']['source_age_seconds'], 86400)
            self.assertEqual(report['checked']['provider']['fetched']['source_age_seconds'], 0)
            self.assertEqual(json.loads(path.read_text()), before)

    def test_removal_is_compared_before_historical_retention(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'openapi/upstream').mkdir(parents=True)
            before = {'info': {'x-aisa-source': {'kind': 'provider_openapi',
                'url': 'https://example.test/schema', 'content_hash': 'old'}},
                'paths': {'/old': {'get': {'operationId': 'old', 'responses': {}}}}}
            path = root/'openapi/upstream/provider.json'
            path.write_text(json.dumps(before))
            updated = copy.deepcopy(before)
            updated['info']['x-aisa-source']['content_hash'] = 'new'
            updated['paths'] = {}
            changes, report = refresh(root, lambda *_: updated)
            comparison = report['updated']['provider']['semantic_changes']
            self.assertEqual(comparison['removed'][0]['operation'], 'GET /old')
            retained = json.loads(changes[path])
            self.assertIn('/old', retained['paths'])
            self.assertEqual(report['updated']['provider']['removed_upstream_but_retained'], ['GET /old'])
        candidate_comparison = report['updated']['provider']['candidate_semantic_changes']
        self.assertEqual(candidate_comparison['removed'], [])
        self.assertEqual(candidate_comparison['changed'], [])

    def test_retained_operation_preserves_prior_inherited_auth_and_servers(self):
        before = {'servers': [{'url': 'https://api.test/old'}], 'security': [{'Key': []}],
            'paths': {'/old': {'get': {'operationId': 'old', 'responses': {}}}},
            'components': {'securitySchemes': {'Key': {'type': 'apiKey', 'in': 'header', 'name': 'X-Old'}}}}
        updated = {'info': {'x-aisa-source': {}}, 'servers': [{'url': 'https://api.test/new'}],
            'security': [{'Key': []}], 'paths': {},
            'components': {'securitySchemes': {'Key': {'type': 'apiKey', 'in': 'header', 'name': 'X-New'}}}}
        retained, _ = preserve_removed(before, updated, 'provider.json')
        operation = retained['paths']['/old']['get']
        self.assertEqual(operation['servers'], before['servers'])
        scheme = next(iter(operation['security'][0]))
        self.assertEqual(retained['components']['securitySchemes'][scheme]['name'], 'X-Old')
        self.assertEqual(retained['components']['securitySchemes']['Key']['name'], 'X-New')

    def test_retained_method_does_not_inherit_new_path_parameters(self):
        before = {'paths': {'/shared': {'parameters': [{'in': 'query', 'name': 'old', 'schema': {'type': 'string'}}],
            'get': {'operationId': 'old', 'responses': {}}}}}
        updated = {'info': {'x-aisa-source': {}}, 'paths': {'/shared': {
            'parameters': [{'in': 'query', 'name': 'new', 'schema': {'type': 'integer'}}],
            'post': {'operationId': 'new', 'responses': {}}}}}
        retained, _ = preserve_removed(before, updated, 'provider.json')
        item = retained['paths']['/shared']
        self.assertNotIn('parameters', item)
        self.assertEqual([p['name'] for p in item['get']['parameters']], ['old'])
        self.assertEqual([p['name'] for p in item['post']['parameters']], ['new'])
        self.assertIn('parameters', updated['paths']['/shared'])

    def test_removed_path_item_reference_is_retained(self):
        before = {'paths': {'/old': {'$ref': '#/components/pathItems/Old'}},
            'components': {'pathItems': {'Old': {'get': {'operationId': 'old', 'responses': {}}}}}}
        updated = {'info': {'x-aisa-source': {}}, 'paths': {}}
        retained, removed = preserve_removed(before, updated, 'provider.json')
        self.assertEqual(removed, ['GET /old'])
        self.assertEqual(retained['paths']['/old']['get']['operationId'], 'old')
