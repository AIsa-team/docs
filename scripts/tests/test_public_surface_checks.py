import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from public_surface_checks import check_surfaces, compare_llms, compare_mcp_sources, request_blocks, same_json


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
        self.payment = json.dumps({'openapi': '3.1.0', 'paths': {'/paid': {'get': {
            'parameters': [{'name': 'target', 'in': 'query', 'required': True}],
            'x-payment-info': {'price': {'amount': '0.08', 'currency': 'USD'}}}}}}).encode()
        self.payloads = {
            'mpp-json': self.payment,
            'website-json': json.dumps(self.spec).encode(), 'docs-json': json.dumps(self.spec).encode(),
            'docs-root-json': json.dumps(self.spec).encode(),
            'mcp-version': json.dumps({'state': 'loaded', 'docsRefs': [self.ref],
                'documentHashes': {'example': 'c' * 64},
                'sourceHashes': {'example': {'example.json': 'sha256:' + 'f' * 64}}}).encode(),
            'website-llms': f'Declared API contract: {self.digest}; immutable Docs revision: {self.ref}. https://raw.githubusercontent.com/AIsa-team/docs/{self.ref}/openapi.yaml https://aisa.one/openapi.json'.encode(),
            'docs-llms': ('OpenAPI /openapi/openapi.json ' + self.digest).encode(),
            'docs-llms-full': self.text.encode(), 'mcp-llms': ('Loaded Docs revisions: ' + self.ref).encode()}

    def block(self, request, price='Published reference price: $0 USD per successful request.'):
        return '## Request contract\n\n````json\n' + json.dumps(request) + '\n````\n\n## Cost and request rules\n\n' + price + '\n'

    def check(self):
        return check_surfaces(self.spec, self.digest, {self.ref},
            read_bytes=lambda name, url: self.payloads[name], expected_requests=self.expected,
            expected_payment=self.payment,
            expected_mcp_sources={'required': ['example.json'], 'allowed': {'example.json': 'sha256:' + 'f' * 64}})

    def test_mcp_requires_complete_raw_source_union_not_provider_named_modules(self):
        expected = {'required': ['one.json', 'two.json'],
                    'allowed': {'one.json': 'sha256:a', 'two.json': 'sha256:b', 'legacy.json': 'sha256:c'}}
        actual = {'sourceHashes': {'composite': {'one.json': 'sha256:a', 'two.json': 'sha256:b'},
                                  'alias': {'one.json': 'sha256:a'}, 'legacy': {'legacy.json': 'sha256:c'}}}
        self.assertEqual(compare_mcp_sources(expected, actual), [])
        for name, mutate, error in [
            ('missing', lambda a: a['sourceHashes']['composite'].pop('two.json'), 'two.json:source_file_missing'),
            ('stale', lambda a: a['sourceHashes']['composite'].update({'two.json': 'sha256:old'}), 'two.json:source_hash_mismatch'),
            ('unknown', lambda a: a['sourceHashes']['alias'].update({'unknown.json': 'sha256:a'}), 'unknown.json:unexpected_source_file'),
            ('conflict', lambda a: a['sourceHashes']['alias'].update({'one.json': 'sha256:wrong'}), 'one.json:conflicting_source_hash'),
            ('malformed', lambda a: a['sourceHashes'].update({'bad': []}), 'source_hashes_invalid'),
            ('unbound', lambda a: a.update(missingProvenance=['unknown']), 'loaded_provenance_unverified'),
        ]:
            with self.subTest(name=name):
                changed = copy.deepcopy(actual); mutate(changed)
                self.assertIn('mcp:' + error, compare_mcp_sources(expected, changed))
        for actual in ({}, {'sourceHashes': {}}):
            self.assertEqual(compare_mcp_sources(expected, actual), ['mcp:source_hashes_unverified'])

    def test_payment_subset_drift_is_detected_independently_of_other_surfaces(self):
        for field in ('price', 'parameters', 'method', 'path'):
            with self.subTest(field=field):
                changed = json.loads(self.payment)
                operation = changed['paths']['/paid']['get']
                if field == 'price':
                    operation['x-payment-info']['price']['amount'] = '0.02'
                elif field == 'parameters':
                    operation['parameters'][0]['required'] = False
                elif field == 'method':
                    changed['paths']['/paid'] = {'post': operation}
                else:
                    changed['paths'] = {'/wrong': {'get': operation}}
                self.payloads['mpp-json'] = json.dumps(changed).encode()
                self.payloads.pop('docs-json', None)
                result = self.check()
                self.assertIn('mpp-json:payment_contract_mismatch', result['mismatches'])
                self.assertTrue(result['missing_inputs'])

    def test_payment_mirror_requires_exact_bytes_and_missing_evidence_cannot_pass(self):
        self.payloads['mpp-json'] = self.payment + b'\n'
        result = self.check()
        self.assertIn('mpp-json:formal_bytes_mismatch', result['mismatches'])
        self.assertNotIn('mpp-json:payment_contract_mismatch', result['mismatches'])
        result = check_surfaces(self.spec, self.digest, {self.ref},
            read_bytes=lambda name, url: self.payloads[name], expected_requests=self.expected)
        self.assertIn('mpp-json:fixed_formal_discovery_missing', result['missing_inputs'])

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

    def test_llms_availability_cannot_be_omitted_or_changed(self):
        expected = request_blocks(self.block({**self.request, 'x-aisa-status': 'disabled'}))
        for status in (None, 'enabled'):
            changed = dict(self.request)
            if status is not None:
                changed['x-aisa-status'] = status
            self.assertTrue(any('request_declaration_mismatch' in error
                for error in compare_llms(expected, request_blocks(self.block(changed)))))
        self.assertEqual(compare_llms(expected, expected), [])

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

    def test_correct_copy_cannot_hide_stale_required_or_wrong_identity(self):
        stale = copy.deepcopy(self.request)
        stale['parameters'][0]['required'] = False
        for changed, code in [(stale, 'request_declaration_mismatch'),
                              ({**self.request, 'method': 'POST'}, 'unexpected_operation_identity'),
                              ({**self.request, 'path': '/wrong'}, 'unexpected_operation_identity')]:
            with self.subTest(changed=changed):
                observed = request_blocks(self.text + self.block(changed))
                self.assertTrue(any(code in error for error in compare_llms(self.expected, observed)))

    def test_only_explicitly_declared_alias_identities_are_accepted(self):
        alias = {**self.request, 'path': '/alias'}
        selected = request_blocks(self.text + self.block(alias))
        observed = request_blocks(self.text + self.block(alias) + self.text)
        self.assertEqual(compare_llms(selected, observed), [])
        unexpected = {**alias, 'method': 'POST'}
        observed = request_blocks(self.text + self.block(alias) + self.block(unexpected))
        self.assertTrue(any('unexpected_operation_identity' in error for error in compare_llms(selected, observed)))

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
