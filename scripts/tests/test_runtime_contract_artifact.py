import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).parent))
import fetch_runtime_release as fetch
import runtime_contract_artifact as contract
from shadow_compile_bundle import load_runtime
import test_fetch_runtime_release as public_tests
from test_fetch_runtime_release import encoded


def native():
    return {'openapi': '3.1.0', 'info': {'title': 'Fixture', 'version': '1'},
            'paths': {'/request': {'get': {'operationId': 'canonical', 'responses': {'200': {'description': 'OK'}}}}}}


class CanonicalArtifactTests(unittest.TestCase):
    def setUp(self):
        _, self.compiler, _, self.current, self.contents, _ = public_tests.PublicReleaseTests().fixture()
        self.contents.update({'contracts/native/example.json': encoded(native()),
                             contract.AGGREGATE: encoded(native()), contract.READINESS: encoded({
                                 'status': 'passed', 'global_errors': [], 'missing_inputs': [], 'blocked_providers': []})})
        self.manifest = {'protocol_version': contract.PROTOCOL, 'generation': self.current['generation'],
            'source_digest': self.current['source_digest'], 'compiler_revision': self.compiler,
            'bundle_manifest_sha256': 'd' * 64, 'docs_ref': 'e' * 40,
            'composer_revision': 'f' * 40, 'source_manifest_sha256': 'a' * 64}
        self.seal()

    def seal(self):
        self.manifest['files'] = [{'path': name, 'bytes': len(raw), 'sha256': fetch.sha(raw)}
                                 for name, raw in sorted(self.contents.items())
                                 if name.startswith('contracts/') and name != contract.MANIFEST]
        self.contents[contract.MANIFEST] = encoded(self.manifest)
        self.outer()

    def outer(self):
        self.current['files'] = [{'name': name, 'media_type': 'application/json', 'sha256': fetch.sha(raw)}
                                 for name, raw in sorted(self.contents.items())]
        manifest = {key: self.current[key] for key in ('schema_version', 'source_digest', 'compiler_revision', 'files')}
        self.revision = fetch.sha(encoded(manifest))
        self.current['artifact_revision'] = self.revision

    def reader(self, path):
        if path == '/public/api-contract/current':
            return encoded(self.current), {}
        if path == '/info/apis/category':
            return b'{"apis":[{"id":"example"}]}', {}
        prefix = '/public/api-contract/releases/' + self.revision + '/'
        self.assertTrue(path.startswith(prefix))
        raw = self.contents[path[len(prefix):]]
        return raw, {'etag': '"' + fetch.sha(raw) + '"'}

    def acquire(self):
        return fetch.acquire(self.revision, self.compiler, self.reader)

    def test_acquisition_retains_full_bytes_but_stage_only_gets_original_facts(self):
        original = self.contents.copy()
        result = self.acquire()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'acquired'
            fetch.save(root, result)
            for name, raw in original.items():
                self.assertEqual((root / name).read_bytes(), raw)
            self.assertEqual((root / 'example.json').read_bytes(), original['providers/example.json'])
            self.assertFalse((root / 'openapi.json').exists())
            facts, binding = load_runtime(root, artifact_revision=self.revision, compiler_revision=self.compiler,
                                         receipt_sha256=fetch.sha((root / 'acquisition-receipt.json').read_bytes()))
            self.assertEqual(set(facts), {'index.json', 'example.json', 'category.json'})
            self.assertEqual(facts['example.json'], original['providers/example.json'])
            self.assertNotIn('bundle_approved', binding)
            receipt_path = root / 'acquisition-receipt.json'
            receipt = json.loads(receipt_path.read_bytes())
            receipt.pop('canonical_validation')
            receipt_path.write_bytes(encoded(receipt))
            with self.assertRaisesRegex(ValueError, 'Canonical acquisition validation differs'):
                load_runtime(root, artifact_revision=self.revision, compiler_revision=self.compiler,
                             receipt_sha256=fetch.sha(receipt_path.read_bytes()))

    def test_fact_only_receipt_has_no_canonical_claim(self):
        revision, compiler, reader, *_ = public_tests.PublicReleaseTests().fixture()
        self.assertNotIn('canonical_validation', fetch.acquire(revision, compiler, reader)[-1])

    def test_canonical_roles_cannot_relax_fact_graph(self):
        value = json.loads(self.contents['index.json'])
        value['providers'] = []
        self.contents['index.json'] = encoded(value)
        self.outer()
        with self.assertRaisesRegex(ValueError, 'unindexed provider'):
            self.acquire()

    def test_partial_or_unknown_roles_rejected(self):
        original = self.contents.copy()
        for name in (contract.MANIFEST, contract.AGGREGATE, contract.READINESS, 'contracts/native/example.json'):
            self.contents = {key: raw for key, raw in original.items() if key != name}
            self.outer()
            with self.subTest(missing=name), self.assertRaises(ValueError):
                self.acquire()
        self.contents = original
        for name in ('contracts/other.json', 'contracts/native/../escape.json', 'contracts/native/upperCase.json'):
            self.contents[name] = b'{}'
            self.outer()
            with self.subTest(extra=name), self.assertRaises(ValueError):
                self.acquire()
            self.contents.pop(name)

    def test_manifest_protocol_identity_and_pins_rejected_after_outer_rehash(self):
        original = copy.deepcopy(self.manifest)
        for key, bad in [('protocol_version', 'shadow-v2'), ('generation', True), ('generation', 2 ** 64),
                         ('generation', 42), ('source_digest', 'b' * 64), ('compiler_revision', 'c' * 40),
                         ('bundle_manifest_sha256', 'd' * 40), ('docs_ref', '../main'),
                         ('composer_revision', True), ('source_manifest_sha256', '')]:
            self.manifest = {**original, key: bad}
            self.seal()
            with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                self.acquire()

    def test_inner_inventory_length_hash_sort_and_duplicates_rejected(self):
        original = copy.deepcopy(self.manifest)
        for mutate in (lambda x: x['files'].pop(), lambda x: x['files'].reverse(),
                       lambda x: x['files'].append(x['files'][0]),
                       lambda x: x['files'][0].update(bytes=True),
                       lambda x: x['files'][0].update(sha256='0' * 64),
                       lambda x: x['files'][0].update(path=contract.MANIFEST),
                       lambda x: x.update(fresh=True)):
            value = copy.deepcopy(original)
            mutate(value)
            self.contents[contract.MANIFEST] = encoded(value)
            self.outer()
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.acquire()

    def test_native_and_aggregate_identity_closure_not_field_equivalence(self):
        value = native()
        value['paths']['/request']['get']['operationId'] = 'wrong'
        self.contents[contract.AGGREGATE] = encoded(value)
        self.seal()
        with self.assertRaisesRegex(ValueError, 'identities differ'):
            self.acquire()
        value['paths']['/request']['get']['operationId'] = 'canonical'
        value['paths']['/request']['get']['summary'] = 'Reader does not independently recompose fields'
        self.contents[contract.AGGREGATE] = encoded(value)
        self.seal()
        self.acquire()  # Integrity/identity scope is explicit, never semantic equivalence.

    def test_native_global_ids_unique_and_shared_v2_mirror_scope(self):
        self.contents['contracts/native/second.json'] = encoded(native())
        self.seal()
        with self.assertRaisesRegex(ValueError, 'identities overlap'):
            self.acquire()
        self.contents.pop('contracts/native/second.json')
        value = native()
        value['paths']['/apis/v2/request'] = {'get': {'operationId': 'mirror'}}
        self.contents['contracts/native/example.json'] = encoded(value)
        self.seal()
        self.acquire()
        self.contents[contract.AGGREGATE] = encoded(value)
        self.seal()
        with self.assertRaisesRegex(ValueError, 'v2 mirrors'):
            self.acquire()

    def test_path_item_reference_chains_are_resolved_before_identity_comparison(self):
        value = native()
        value['components'] = {'pathItems': {'actual/part': value['paths']['/request'],
                                            'alias': {'$ref': '#/components/pathItems/actual%7E1part'}}}
        value['paths']['/request'] = {'$ref': '#/components/pathItems/alias'}
        self.contents['contracts/native/example.json'] = encoded(value)
        self.contents[contract.AGGREGATE] = encoded(value)
        self.seal()
        self.acquire()
        self.assertEqual(contract.operation_ids(value), {'canonical'})
        value['components']['pathItems']['actual/part']['get']['operationId'] = 'wrong'
        self.contents[contract.AGGREGATE] = encoded(value)
        self.seal()
        with self.assertRaisesRegex(ValueError, 'identities differ'):
            self.acquire()
        value['components']['pathItems']['actual/part'] = {'$ref': '#/components/pathItems/alias'}
        self.contents[contract.AGGREGATE] = encoded(value)
        self.seal()
        with self.assertRaisesRegex(ValueError, 'recursive public object'):
            self.acquire()

    def test_security_requirements_are_closed_or_exact_disabled_legacy_debt(self):
        for status, state in [(None, None), ('enabled', 'retained_legacy'), ('disabled', None)]:
            value = native()
            operation = value['paths']['/request']['get']
            operation['security'] = [{'MissingScheme': []}]
            operation['x-aisa-documentation-limitations'] = ['unresolved_security_scheme:MissingScheme']
            if status:
                operation['x-aisa-status'] = status
            if state:
                operation['x-aisa-contract-state'] = state
            self.contents['contracts/native/example.json'] = encoded(value)
            self.contents[contract.AGGREGATE] = encoded(value)
            self.seal()
            with self.subTest(status=status, state=state), self.assertRaisesRegex(ValueError, 'security scheme'):
                self.acquire()
        operation['x-aisa-contract-state'] = 'retained_legacy'
        self.contents['contracts/native/example.json'] = encoded(value)
        self.contents[contract.AGGREGATE] = encoded(value)
        self.seal()
        receipt = self.acquire()[-1]
        validation = receipt['canonical_validation']
        self.assertEqual(validation['security_status'], 'historical_debt')
        self.assertEqual(len(validation['historical_security_debt']), 2)
        for row in validation['historical_security_debt']:
            self.assertEqual({k: v for k, v in row.items() if k != 'document'},
                {'provider': 'example', 'path': '/request', 'method': 'GET',
                 'operation_id': 'canonical', 'scheme': 'MissingScheme'})
        value['security'] = [{'MissingRoot': []}]
        self.contents[contract.AGGREGATE] = encoded(value)
        self.seal()
        with self.assertRaisesRegex(ValueError, 'security scheme'):
            self.acquire()

    def test_auth_aliases_resolve_and_schema_security_properties_are_data(self):
        value = native()
        value['security'] = [{'Auth': []}]
        value['components'] = {'securitySchemes': {'Auth': {'$ref': '#/components/securitySchemes/Concrete'},
            'Concrete': {'type': 'http', 'scheme': 'bearer'}}, 'schemas': {'Business': {'type': 'object',
                'properties': {'security': {'type': 'array', 'default': [{'NotAuth': []}]}},
                'example': {'security': [{'NotAuth': []}]}}}}
        self.contents['contracts/native/example.json'] = encoded(value)
        self.contents[contract.AGGREGATE] = encoded(value)
        self.seal()
        self.assertEqual(self.acquire()[-1]['canonical_validation']['security_status'], 'passed')
        value['components']['securitySchemes']['Concrete'] = {'$ref': '#/components/securitySchemes/Auth'}
        self.contents[contract.AGGREGATE] = encoded(value)
        self.seal()
        with self.assertRaisesRegex(ValueError, 'recursive public object'):
            self.acquire()

    def test_refs_are_context_aware_and_business_examples_preserved(self):
        value = native()
        value['components'] = {'schemas': {'Input': {'type': 'object', 'example': {'$ref': '../business'}}}}
        self.contents['contracts/native/example.json'] = encoded(value)
        self.seal()
        self.acquire()
        value['components']['schemas']['Input']['properties'] = {'x': {'$ref': '#/components/schemas/missing'}}
        self.contents['contracts/native/example.json'] = encoded(value)
        self.seal()
        with self.assertRaises(ValueError):
            self.acquire()

    def test_json_precision_duplicate_keys_and_readiness_fail_closed(self):
        original = self.contents.copy()
        for raw in (b'{"openapi":"3.1.0","openapi":"3.0.3"}',
                    b'{"x":1e999}', b'{"x":0.1234567890123456789}', b'{"x":NaN}'):
            self.contents = original.copy()
            self.contents[contract.AGGREGATE] = raw
            self.seal()
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.acquire()
        self.contents = original
        self.contents[contract.READINESS] = encoded({'status': 'passed', 'global_errors': ['not ready'],
                                                    'missing_inputs': [], 'blocked_providers': []})
        self.seal()
        with self.assertRaisesRegex(ValueError, 'readiness'):
            self.acquire()

    def test_size_exception_is_exact_and_total_limit_stays_enforced(self):
        value = native()
        value['info']['description'] = 'x' * (8 << 20)
        raw = encoded(value)
        self.contents[contract.AGGREGATE] = raw
        self.seal()
        self.acquire()
        with patch.object(contract, 'MAX_AGGREGATE', 8 << 20), self.assertRaises(ValueError):
            self.acquire()
        self.contents['contracts/native/example.json'] = raw
        self.seal()
        with self.assertRaises(ValueError):
            self.acquire()
        self.contents['contracts/native/example.json'] = encoded(native())
        self.seal()
        with patch.object(fetch, 'MAX_TOTAL', 8 << 20), self.assertRaises(ValueError):
            self.acquire()
        for name in (contract.MANIFEST, contract.READINESS):
            self.contents[name] = b' ' * ((1 << 20) + 1)
            self.outer()
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.acquire()

    def test_http_reader_large_limit_only_for_exact_aggregate_release_path(self):
        response = Mock()
        response.status = 200
        response.headers = {}
        response.read.return_value = b'{}'
        reader = fetch.PublicReader('https://api.aisa.one', float('inf'))
        reader.opener = MagicMock()
        reader.opener.open.return_value.__enter__.return_value = response
        for path, limit in [(f'/public/api-contract/releases/{self.revision}/contracts/openapi.json', 32 << 20),
                            (f'/public/api-contract/releases/{self.revision}/contracts/readiness.json', 1 << 20),
                            (f'/public/api-contract/releases/{self.revision}/providers/openapi.json', 8 << 20),
                            ('/unknown/contracts/openapi.json', 8 << 20)]:
            reader(path)
            response.read.assert_called_with(limit + 1)


if __name__ == '__main__':
    unittest.main()
