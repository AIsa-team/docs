import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from public_surface_checks import check_surfaces, compare_llms, request_blocks, same_json


class SurfaceChecks(unittest.TestCase):
    def setUp(self):
        self.ref = 'a' * 40
        self.digest = 'b' * 64
        self.spec = {'openapi': '3.1.0', 'info': {'x-aisa-document': {'providers': {'example': {'document_hash': 'c' * 64}}}},
                     'paths': {'/example': {'get': {'parameters': [{'name': 'date', 'in': 'query', 'required': True}],
                         'requestBody': {'content': {'application/json': {'schema': {'properties': {
                             'description': {'type': 'integer', 'default': 9007199254740993},
                             'example': {'enum': ['live', 'historical']}}}}}}}}}}
        self.request = {'operationId': 'get_example', 'method': 'GET', 'path': '/example',
                        'parameters': [{'name': 'date', 'in': 'query', 'required': True}],
                        'requestBody': self.spec['paths']['/example']['get']['requestBody']}
        self.text = self.block(self.request)
        self.expected = request_blocks(self.text)
        self.payloads = {
            'website-json': json.dumps(self.spec).encode(), 'docs-json': json.dumps(self.spec).encode(),
            'mcp-version': json.dumps({'state': 'loaded', 'docsRefs': [self.ref], 'documentHashes': {'example': 'c' * 64}}).encode(),
            'website-llms': f'Declared API contract: {self.digest}; immutable Docs revision: {self.ref}. /openapi/openapi.json'.encode(),
            'docs-llms': b'OpenAPI /openapi/openapi.json',
            'docs-llms-full': self.text.encode(), 'mcp-llms': ('Loaded Docs revisions: ' + self.ref).encode()}

    def block(self, request, price='Published reference price: $0 USD per successful request.'):
        return '## Request contract\n\n````json\n' + json.dumps(request) + '\n````\n\n## Cost and request rules\n\n' + price + '\n'

    def check(self):
        return check_surfaces(self.spec, self.digest, {self.ref},
            read_bytes=lambda name, url: self.payloads[name], expected_requests=self.expected)

    def test_independently_declared_complete_surfaces_pass(self):
        result = self.check()
        self.assertEqual(result['missing_inputs'], [])
        self.assertEqual(result['mismatches'], [])
        self.assertEqual(result['observations']['docs-llms-full']['request_operations_compared'], 1)

    def test_json_business_property_names_and_large_numbers_are_not_filtered(self):
        changed = copy.deepcopy(self.spec)
        props = changed['paths']['/example']['get']['requestBody']['content']['application/json']['schema']['properties']
        props['description']['default'] = 9007199254740992
        self.payloads['website-json'] = json.dumps(changed).encode()
        self.assertIn('website-json:complete_openapi_mismatch', self.check()['mismatches'])
        self.assertFalse(same_json({'default': True}, {'default': 1}))

    def test_mintlify_fence_attributes_and_price_escapes_preserve_semantics(self):
        rendered = self.text.replace('````json', '````json theme={null}').replace('$0', r'\$0')
        self.assertEqual(compare_llms(self.expected, request_blocks(rendered)), [])

    def test_all_request_fields_and_price_change_fail(self):
        for field, value in [('method', 'POST'), ('path', '/other'), ('parameters', []), ('requestBody', {})]:
            with self.subTest(field=field):
                changed = {**self.request, field: value}
                self.assertTrue(compare_llms(self.expected, request_blocks(self.block(changed))))
        changed = request_blocks(self.block(self.request, 'Default request estimate: $0.012 USD (not a fixed price).'))
        self.assertTrue(any('price_summary_mismatch' in error for error in compare_llms(self.expected, changed)))
        # A correct duplicate must not hide a stale cost for the same declaration.
        duplicated = request_blocks(self.text + self.block(self.request, 'old price'))
        self.assertTrue(compare_llms(self.expected, duplicated))

    def test_unverified_mcp_cannot_pass_even_when_router_source_would_match(self):
        self.payloads['mcp-version'] = json.dumps({'state': 'unverified', 'docsRefs': [self.ref], 'documentHashes': {}}).encode()
        self.assertIn('mcp:loaded_provenance_unverified', self.check()['mismatches'])

    def test_missing_inputs_and_incomplete_llms_are_not_passed(self):
        del self.payloads['docs-json']
        self.payloads['docs-llms-full'] = b'Only the operation count, no schema.'
        result = self.check()
        self.assertTrue(result['missing_inputs'])
        self.assertTrue(any('request_missing' in error for error in result['mismatches']))
        self.payloads['docs-llms-full'] = b'## Request contract\n```json\n{invalid}\n```'
        self.assertTrue(any('docs-llms-full:unavailable' in error for error in self.check()['missing_inputs']))


if __name__ == '__main__':
    unittest.main()
