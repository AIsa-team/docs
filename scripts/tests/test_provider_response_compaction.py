import copy
import json
import tempfile
import unittest
from pathlib import Path
from scripts.compose_openapi import source_success_responses, referenced_components
from scripts.runtime_registry import public_mirror_index


class ProviderResponseCompactionTests(unittest.TestCase):
    def test_field_table_examples_and_constraints_survive_without_audit_duplicates(self):
        schema = {'not': {'type': 'null'}, 'description': 'Documented field table',
                  'x-aisa-schema-completeness': 'documented-fields-only',
                  'x-aisa-provider-response': {'fields': [{'name': 'name', 'type': 'string'}]}}
        response = {'description': 'Documented field table', 'content': {'application/json': {
            'schema': schema, 'examples': {'provider': {'value': {'name': 'example'}}}}}}
        operation = {'responses': {'200': response}}
        original = copy.deepcopy(operation)
        result = source_success_responses(operation, {}, {}, 'test', {})['200']
        self.assertEqual(result['description'], response['description'])
        self.assertEqual(result['content']['application/json']['examples'], response['content']['application/json']['examples'])
        expected = {k: v for k, v in schema.items() if k not in ('description', 'x-aisa-provider-response')}
        self.assertEqual(result['content']['application/json']['schema'], expected)
        self.assertEqual(operation, original)
        schema['description'] = 'Distinct payload guidance'
        result = source_success_responses(operation, {}, {}, 'test', {})['200']
        self.assertEqual(result['content']['application/json']['schema']['description'], 'Distinct payload guidance')

    def test_many_recursive_definitions_share_one_component_walk(self):
        ref = '#/components/schemas/Owned/$defs/'
        definitions = {f'N{i}': {'type': 'object', 'properties': {
            'next': {'$ref': ref + f'N{(i + 1) % 200}'}}} for i in range(200)}
        component = {'$defs': definitions, '$ref': ref + 'N0'}
        document = {'openapi': '3.1.0', 'components': {'schemas': {'Owned': component}}}
        selected = referenced_components({'schema': {'$ref': ref + 'N0'}}, document)
        self.assertEqual(selected, document['components'])
        self.assertIsNot(selected['schemas']['Owned'], component)
        definitions['N199']['properties']['missing'] = {'$ref': ref + 'Missing'}
        with self.assertRaises(ValueError):
            referenced_components({'schema': {'$ref': ref + 'N0'}}, document)

    def test_public_source_keeps_content_binding_without_repeating_all_operation_audits(self):
        source = {'kind': 'manual', 'path_space': 'public', 'url': 'https://example.com/reference',
                  'fetched_at': '2026-11-11T00:00:00Z', 'content_hash': 'sha256:reviewed',
                  'converter': 'reviewed', 'operation_evidence': [{'path': '/example', 'profile_ref': 'recorded'}]}
        doc = {'openapi': '3.1.0', 'info': {'x-aisa-source': source}, 'paths': {'/example': {
            'post': {'operationId': 'example', 'responses': {'200': {'description': 'OK'}}}}}}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'openapi/upstream').mkdir(parents=True)
            path = root / 'openapi/upstream/example.json'; path.write_text(json.dumps(doc))
            result = public_mirror_index(root)[('/example', 'post')]
            self.assertEqual(result['source']['content_hash'], source['content_hash'])
            self.assertNotIn('operation_evidence', result['source'])
            self.assertEqual(json.loads(path.read_text()), doc)


if __name__ == '__main__':
    unittest.main()
