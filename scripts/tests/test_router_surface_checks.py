import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from router_surface_checks import (METADATA, SCHEMAS, PublicSchemaReader, canonical,
    check_router_surface, contract_fields, digest, fixed_router_contracts, in_scope, reference_targets)


class RouterSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.ref = 'a' * 40
        self.document = {
            'openapi': '3.1.0', 'servers': [{'url': 'https://api.aisa.one'}],
            'security': [{'Auth': []}],
            'components': {
                'securitySchemes': {'Auth': {'$ref': '#/components/securitySchemes/Bearer'},
                                   'Bearer': {'type': 'http', 'scheme': 'bearer'}},
                'schemas': {'Node': {'type': 'object', 'properties': {
                    'next': {'$ref': '#/components/schemas/Node'},
                    'count': {'type': 'integer', 'default': 9007199254740993}}}}},
            'paths': {'/item': {
                'parameters': [{'name': 'query', 'in': 'query', 'schema': {'type': 'string'}}],
                'get': {'operationId': 'get_item', 'description': 'Item details', 'summary': 'Read item',
                    'x-aisa-pricing': {'amount': 0.02, 'unit': 'request'},
                    'requestBody': {'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Node'}}}},
                    'responses': {'200': {'description': 'OK'}}}}}}
        self.expected = {'docs_ref': self.ref, 'excluded': [], 'provider_document_hashes': {'fixture': 'doc-hash'},
            'operations': {'get_item': {'source_file': 'openapi/fixture.json', 'source_hash': 'sha256:file-hash',
                'document_hash': 'doc-hash', 'method': 'GET', 'path': '/item',
                'fingerprints': {k: digest(v) for k, v in contract_fields(self.document, '/item', 'get').items()}}}}
        self.row = {'successful': True, 'documentation': {'openapi': copy.deepcopy(self.document),
            'provenance': {'docs_sha': self.ref, 'source_file': 'openapi/fixture.json',
                           'source_hash': 'sha256:file-hash', 'document_hash': 'doc-hash'}}}
        self.metadata = {'docs_commit': self.ref, 'build_id': 'build-1', 'provider_document_hashes': {'fixture': 'doc-hash'}}
        self.calls = []
        self.after = None

    def read(self, method, url, payload=None):
        self.calls.append((method, url, payload))
        if url == METADATA:
            return copy.deepcopy(self.after if self.after is not None and len(self.calls) > 1 else self.metadata)
        self.assertEqual((method, url), ('POST', SCHEMAS))
        self.assertEqual(payload, {'tools': ['get_item'], 'include_documentation': True,
                                  'include_arguments_schema': False, 'include_response_schema': False})
        return {'tools': {'get_item': copy.deepcopy(self.row)}}

    def audit(self):
        return check_router_surface('.', self.ref, read_json=self.read, expected=self.expected)

    def test_matching_contract_and_fixed_provenance(self):
        result = self.audit()
        self.assertEqual(result['missing_inputs'], [])
        self.assertEqual(result['mismatches'], [])
        self.assertEqual(result['verified_operations'], 1)
        self.assertEqual([method for method, _, _ in self.calls], ['GET', 'POST', 'GET'])

    def test_every_public_field_drift_is_detected(self):
        original = copy.deepcopy(self.row)
        for field in ('method', 'path', 'description', 'summary', 'x-aisa-pricing', 'parameters',
                      'requestBody', 'responses', 'security', 'servers', 'reference_targets'):
            with self.subTest(field=field):
                self.row = copy.deepcopy(original)
                document = self.row['documentation']['openapi']
                operation = document['paths']['/item']['get']
                if field == 'method':
                    document['paths']['/item']['post'] = document['paths']['/item'].pop('get')
                elif field == 'path':
                    document['paths']['/different'] = document['paths'].pop('/item')
                elif field == 'reference_targets':
                    document['components']['schemas']['Node']['properties']['count']['default'] = 9007199254740992
                elif field in ('security', 'servers'):
                    document[field] = []
                elif field == 'parameters':
                    operation[field] = [{'name': 'query', 'in': 'query', 'schema': {'type': 'integer'}}]
                else:
                    operation[field] = None
                self.assertIn('router-schema:get_item:' + field + '_mismatch', self.audit()['mismatches'])

    def test_unavailable_legacy_is_never_implicitly_excluded(self):
        self.row = {'successful': False, 'error': {'code': 'not_found'}}
        result = self.audit()
        self.assertEqual(result['verified_operations'], 0)
        self.assertIn('router-schema:get_item:unavailable', result['missing_inputs'])
        self.assertEqual(len(result['unavailable_operations']), 1)
        self.assertEqual(result['exclusions'], [])

    def test_wrong_provenance_and_mid_audit_rollover_fail(self):
        self.row['documentation']['provenance']['docs_sha'] = 'b' * 40
        self.after = {**self.metadata, 'build_id': 'build-2'}
        result = self.audit()
        self.assertIn('router-schema:get_item:docs_sha_mismatch', result['mismatches'])
        self.assertIn('router-schema:catalog_changed_during_audit', result['mismatches'])
        self.assertEqual(result['verified_operations'], 0)

    def test_unexpected_provider_is_not_hidden_by_matching_expected_hashes(self):
        self.metadata['provider_document_hashes']['stale'] = 'stale-hash'
        self.assertIn('router-schema:provider_membership_mismatch', self.audit()['mismatches'])
        self.assertEqual(len(self.calls), 1)

    def test_wrong_starting_version_does_not_query_schemas(self):
        self.metadata['docs_commit'] = 'b' * 40
        self.assertTrue(self.audit()['mismatches'])
        self.assertEqual(len(self.calls), 1)

    def test_proven_same_contract_ref_still_checks_fields_and_exact_batch_identity(self):
        self.metadata['docs_commit'] = 'b' * 40
        self.row['documentation']['provenance']['docs_sha'] = 'b' * 40
        def check():
            return check_router_surface('.', self.ref, expected=self.expected, read_json=self.read,
                                        accepted_refs={'b' * 40})
        self.assertEqual(check()['mismatches'], [])
        self.row['documentation']['openapi']['paths']['/item']['get']['description'] = 'wrong'
        self.assertIn('router-schema:get_item:description_mismatch', check()['mismatches'])
        self.row['documentation']['provenance']['docs_sha'] = self.ref
        self.assertIn('router-schema:get_item:docs_sha_mismatch', check()['mismatches'])

    def test_missing_or_malformed_metadata_and_batch_fail_closed(self):
        for malformed in (None, [], {'docs_commit': self.ref, 'build_id': 'build-1', 'provider_document_hashes': None}):
            with self.subTest(metadata=malformed):
                result = check_router_surface('.', self.ref, expected=self.expected, read_json=lambda *args: malformed)
                self.assertTrue(result['missing_inputs'] or result['mismatches'])
        result = check_router_surface('.', self.ref, expected=self.expected,
            read_json=lambda method, *args: self.metadata if method == 'GET' else {'tools': {}})
        self.assertEqual(result['verified_operations'], 0)
        self.assertTrue(result['missing_inputs'])

    def test_closure_follows_alias_auth_recursive_and_encoded_refs(self):
        document = copy.deepcopy(self.document)
        document['components']['schemas']['encoded/name'] = {'type': 'number'}
        document['paths']['/item']['get']['responses']['200']['content'] = {
            'application/json': {'schema': {'$ref': '#/components/schemas/encoded~1%6Eame'}}}
        targets = contract_fields(document, '/item', 'get')['reference_targets']
        self.assertEqual(set(targets), {'#/components/schemas/Node', '#/components/securitySchemes/Auth',
                                     '#/components/securitySchemes/Bearer', '#/components/schemas/encoded~1%6Eame'})

    def test_business_instances_and_property_names_are_not_references(self):
        declaration = {'properties': {name: {'type': 'string'} for name in ('$ref', 'security', 'links', 'discriminator')},
            'example': {'$ref': 'not-a-reference'}, 'default': {'$ref': 'not-a-reference'},
            'enum': [{'$ref': 'not-a-reference'}], 'x-private': {'$ref': 'not-a-reference'}}
        self.assertEqual(reference_targets(declaration, {}), {})

    def test_links_follow_operation_and_preserve_runtime_expression_instances(self):
        document = copy.deepcopy(self.document)
        document['paths']['/other'] = {'get': {'operationId': 'other', 'responses': {'200': {'description': 'Other'}}}}
        link = {'operationId': 'other', 'parameters': {'value': {'$ref': 'business-value'}}}
        closure = reference_targets({'responses': {'200': {'links': {'next': link}}}}, document)
        self.assertIn('#/paths/~1other/get', closure)
        with self.assertRaises(ValueError):
            reference_targets({'$ref': '#/components/schemas/Missing'}, document)

    def test_json_types_are_not_python_equal(self):
        self.assertNotEqual(digest(True), digest(1))
        self.assertNotEqual(digest(9007199254740993), digest(9007199254740992))

    def test_network_client_cannot_execute_tool_or_follow_other_origin(self):
        import time
        reader = PublicSchemaReader(time.monotonic() + 10)
        for method, url in [('POST', METADATA), ('GET', SCHEMAS), ('POST', 'https://tools.aisa.one/execute')]:
            with self.assertRaises(ValueError):
                reader(method, url)

    def test_discovery_scope_matches_router_root_servers_not_operation_override(self):
        document = copy.deepcopy(self.document)
        document['paths']['/item']['get']['servers'] = [{'url': 'https://other.example/v1'}]
        self.assertTrue(in_scope(document))
        document['servers'] = [{'url': 'https://api.aisa.one/v1'}]
        document['paths']['/item']['get']['servers'] = [{'url': 'https://api.aisa.one/apis/v1'}]
        self.assertFalse(in_scope(document))
        document.pop('servers')
        self.assertTrue(in_scope(document))
        document['servers'] = [{'url': 'https://api.aisa.one:443/apis/v1'}]
        self.assertFalse(in_scope(document))


class FixedSourceTests(unittest.TestCase):
    def test_hash_bound_source_scope_and_disabled_contracts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            def commit():
                subprocess.run(['git', 'add', '.'], cwd=root, check=True)
                subprocess.run(['git', '-c', 'user.name=Ken', '-c', 'user.email=ken@aisa.one',
                                'commit', '-qm', 'Fixture'], cwd=root, check=True)
                return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root).decode().strip()
            docs = {
                'fixture': {'openapi': '3.1.0', 'paths': {'/active': {'get': {'operationId': 'active'}},
                    '/retired': {'get': {'operationId': 'retired', 'x-aisa-status': 'disabled'}}}},
                'legacy': {'openapi': '3.1.0', 'servers': [{'url': 'https://api.aisa.one/v1'}],
                           'paths': {'/model': {'post': {'operationId': 'legacy'}}}},
                'openapi': {'paths': {'/duplicate': {'get': {'operationId': 'active'}}}}}
            hashes = {}
            (root / 'openapi').mkdir()
            for name, document in docs.items():
                path = 'openapi/' + name + '.json'
                raw = canonical(document)
                (root / path).write_bytes(raw)
                hashes[path] = hashlib.sha256(raw).hexdigest()
            (root / 'docs/publication').mkdir(parents=True)
            pointer = root / 'docs/publication/current.json'
            pointer.write_bytes(canonical({'status': 'passed', 'files_sha256': hashes}))
            ref = commit()
            result = fixed_router_contracts(root, ref)
            self.assertEqual(list(result['operations']), ['active'])
            self.assertEqual({row['reason'] for row in result['excluded']},
                             {'formal_operation_disabled', 'outside_router_api_server_scope'})
            (root / 'openapi/fixture.json').write_text('{}')
            self.assertEqual(list(fixed_router_contracts(root, ref)['operations']), ['active'])
            changed_ref = commit()
            with self.assertRaises(ValueError):
                fixed_router_contracts(root, changed_ref)
            with self.assertRaises(ValueError):
                fixed_router_contracts(root, 'main')


if __name__ == '__main__':
    unittest.main()
