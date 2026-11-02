"""Web API response authority cannot widen the native request or tariff."""
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import compose, digest
from runtime_registry import public_mirror_index
from source_governance import policy_errors, receipt_key, validate_receipt
from scripts.tests.test_runtime_contracts import facts, operation

ROOT = Path(__file__).resolve().parents[2]
ORIGIN = 'https://webapi.oxylabs.io'


def native_facts(name):
    value = facts()
    op = operation(value)
    op.update(operationId='post_oxylabs_' + name, summary='Oxylabs Web API ' + name,
              parameters=[], **{
                  'x-aisa-upstream-path': '/v1/' + name,
                  'x-aisa-response-passthrough': True,
                  'x-aisa-response-upstream-path-sha256': hashlib.sha256(('/v1/' + name).encode()).hexdigest(),
                  'x-aisa-response-upstream-origin-sha256': hashlib.sha256(ORIGIN.encode()).hexdigest(),
                  'x-aisa-pricing': {'cost_contract': 'request_formula',
                                     'customer_pricing': 'fixed_success',
                                     'default_request_estimate_usd': 0.00145}})
    properties = ({'query': {'type': 'string', 'minLength': 1, 'maxLength': 2048},
                   'max_results': {'type': 'integer', 'minimum': 1, 'maximum': 20, 'default': 10}}
                  if name == 'search' else
                  {'url': {'type': 'string', 'format': 'uri', 'pattern': '^https://'},
                   'output': {'type': 'array', 'minItems': 1, 'maxItems': 2,
                              'items': {'type': 'string', 'enum': ['html', 'markdown']},
                              'default': ['html']},
                   'run_js': {'type': 'boolean', 'enum': [False], 'default': False}})
    schema = {'type': 'object', 'additionalProperties': False, 'properties': properties,
              'required': ['query' if name == 'search' else 'url']}
    op['requestBody'] = {'required': True, 'content': {'application/json': {'schema': schema}}}
    value['paths'] = {'/apis/v1/oxylabs/' + name: {'post': op}}
    return value


class OxylabsWebResponseTests(unittest.TestCase):
    def sources(self):
        return {name: json.loads((ROOT / 'openapi/upstream' /
                                ('response-oxylabs-web-' + name + '.json')).read_text())
                for name in ('search', 'scrape')}

    def schema(self, name):
        return self.sources()[name]['paths']['/apis/v1/oxylabs/' + name]['post']['responses']['200']['content']['application/json']['schema']

    def test_sources_have_exact_native_binding_and_no_request_or_billing_authority(self):
        for name, original in self.sources().items():
            document = copy.deepcopy(original)
            source = document['info'].pop('x-aisa-source')
            self.assertEqual(source['content_hash'], digest(document))
            self.assertEqual(policy_errors(source), [])
            self.assertTrue(source['response_only'])
            self.assertEqual(source['upstream_path_sha256'], hashlib.sha256(('/v1/' + name).encode()).hexdigest())
            self.assertEqual(source['upstream_origin_sha256'], hashlib.sha256(ORIGIN.encode()).hexdigest())
            self.assertEqual(source['url'], 'https://developers.oxylabs.io/products/web-api/' + name)
            self.assertEqual(set(document['paths']['/apis/v1/oxylabs/' + name]['post']), {'responses'})

    def test_composer_discovers_new_sources_and_preserves_request_identity_and_price(self):
        mirrors = public_mirror_index(ROOT)
        for name in self.sources():
            runtime = native_facts(name)
            doc, pending = compose(runtime, public_mirrors=mirrors)
            self.assertEqual(pending, [])
            actual, original = operation(doc), operation(runtime)
            self.assertNotIn('x-aisa-response-pending', actual)
            for key in ('requestBody', 'parameters', 'operationId', 'x-aisa-pricing', 'x-aisa-capabilities'):
                self.assertEqual(actual[key], original[key], key)
            self.assertNotIn('x-aisa-source', actual)
            self.assertEqual(actual['x-aisa-response-source']['source']['url'],
                             'https://developers.oxylabs.io/products/web-api/' + name)
            self.assertEqual(compose(runtime, public_mirrors=mirrors, previous=doc), (doc, []))
            request_schema = actual['requestBody']['content']['application/json']['schema']
            invalid = ({'query': 'test', 'source': 'google_search'} if name == 'search'
                       else {'url': 'https://example.com', 'run_js': True})
            self.assertFalse(Draft202012Validator(request_schema).is_valid(invalid))

    def test_classic_or_wrong_path_binding_cannot_supply_web_api_response(self):
        mirrors = public_mirror_index(ROOT)
        for name in self.sources():
            for field, wrong in [('x-aisa-response-upstream-origin-sha256', hashlib.sha256(b'https://data.oxylabs.io').hexdigest()),
                                 ('x-aisa-response-upstream-path-sha256', hashlib.sha256(b'/v1/queries').hexdigest())]:
                runtime = native_facts(name)
                operation(runtime)[field] = wrong
                doc, pending = compose(runtime, public_mirrors=mirrors)
                self.assertEqual(pending, [])
                self.assertIn('x-aisa-response-pending', operation(doc))

    def test_search_types_empty_results_and_optional_result_details(self):
        validator = Draft202012Validator(self.schema('search'))
        for body in [{'state': 'done', 'results': []},
                     {'state': 'done', 'status': 200, 'results': []},
                     {'state': 'done', 'results': [{'title': 'Example', 'outline': ['Snippet'], 'url': 'https://example.com', 'metadata': {'position': 1}}]}]:
            self.assertTrue(validator.is_valid(body), body)
        for body in [{'state': 'faulted', 'results': []}, {'state': 'done', 'results': [None]},
                     {'state': 'done', 'status': 400, 'results': []},
                     {'state': 'done', 'status': '200', 'results': []},
                     {'state': 'done'}, {'state': 'done', 'results': [{'outline': 'wrong'}]}]:
            self.assertFalse(validator.is_valid(body), body)

    def test_scrape_documented_and_observed_envelopes_and_null_unrequested_outputs(self):
        validator = Draft202012Validator(self.schema('scrape'))
        for marker in [{'status': 200}, {'state': 'done'}, {'status': 200, 'state': 'done'}]:
            for outputs in [{'html': '<html></html>', 'markdown': None},
                            {'html': None, 'markdown': '# Example'},
                            {'html': '', 'markdown': ''}]:
                body = {**marker, 'results': [{**outputs, 'json': None, 'screenshot': None}]}
                self.assertTrue(validator.is_valid(body), body)
        for body in [{'results': [{'html': 'x'}]}, {'status': 200, 'state': 'faulted', 'results': [{}]},
                     {'state': 'done', 'status': 500, 'results': [{}]}, {'status': 200, 'results': []},
                     {'status': 200, 'results': [None]}, {'status': 200, 'results': [{'html': False}]},
                     {'state': 'done', 'results': [{}]},
                     {'state': 'done', 'results': [{'html': None, 'markdown': None}]},
                     {'state': 'done', 'results': [{}, {'html': 'later output'}]}]:
            self.assertFalse(validator.is_valid(body), body)

    def test_original_review_receipts_bind_both_export_and_publisher_packets(self):
        context = json.loads((ROOT / 'docs/schema-inputs/context.json').read_text())
        packet_path = ROOT / context['source_receipts_path']
        self.assertEqual(context['source_receipts_sha256'], hashlib.sha256(packet_path.read_bytes()).hexdigest())
        packets = [json.loads(packet_path.read_text()),
                   json.loads((ROOT / 'docs/current-source-review-20261009/merged-source-reviews.json').read_text())]
        for document in self.sources().values():
            source = document['info']['x-aisa-source']
            for packet in packets:
                receipt = packet['receipts'].get(receipt_key(source))
                self.assertTrue(validate_receipt(source, receipt, datetime.now(timezone.utc)))


if __name__ == '__main__':
    unittest.main()
