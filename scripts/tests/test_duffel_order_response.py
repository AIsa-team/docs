import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import compose
from prepare_duffel_order_response import prepare, SOURCE_FILE, PUBLIC_PATH
from runtime_registry import public_mirror_index
from source_governance import policy_errors

ROOT = Path(__file__).resolve().parents[2]


class DuffelOrderResponseTests(unittest.TestCase):
    def setUp(self):
        self.raw = (ROOT / SOURCE_FILE).read_bytes()
        self.sources = prepare(self.raw)
        self.source = next(iter(self.sources.values()))
        source = self.source['info']['x-aisa-source']
        self.runtime = {'openapi': '3.1.0', 'info': {'x-aisa-document': {'facts_hash': 'synthetic'}},
                        'servers': [{'url': 'https://api.aisa.one'}], 'paths': {PUBLIC_PATH: {'get': {
                            'operationId': 'get_duffel_flights_apis_v1_duffel_flights_orders_id',
                            'x-aisa-status': 'enabled', 'x-aisa-validation': 'runtime',
                            'x-aisa-response-passthrough': True,
                            'x-aisa-response-upstream-path-sha256': source['upstream_path_sha256'],
                            'x-aisa-response-upstream-origin-sha256': source['upstream_origin_sha256'],
                            'x-aisa-pricing': {'default_request_estimate_usd': 0.005},
                            'parameters': [{'name': 'id', 'in': 'path', 'required': True,
                                            'schema': {'type': 'string'}}],
                            'responses': {'200': {'description': 'Successful response'}}}}}}

    def mirrors(self):
        with tempfile.TemporaryDirectory() as folder:
            return public_mirror_index(Path(folder), self.sources)

    def test_committed_binding_reproduces_and_preserves_exact_official_response(self):
        for name, document in self.sources.items():
            self.assertEqual(json.loads((ROOT / 'openapi/upstream' / name).read_text()), document)
        official = json.loads(self.raw)['paths']['/air/orders/{id}']['get']
        operation = self.source['paths'][PUBLIC_PATH]['get']
        self.assertEqual(operation['responses'], official['responses'])
        self.assertEqual(policy_errors(self.source['info']['x-aisa-source']), [])
        self.assertNotIn('requestBody', operation)
        self.assertNotIn('operationId', operation)
        self.assertTrue(all(p['in'] == 'path' for p in operation['parameters']))

    def test_pinned_source_rejects_even_whitespace_changes(self):
        with self.assertRaisesRegex(ValueError, 'source bytes changed'):
            prepare(self.raw + b' ')

    def test_actual_composer_closes_response_without_changing_request_identity_or_price(self):
        before, pending = compose(self.runtime)
        after, after_pending = compose(self.runtime, public_mirrors=self.mirrors())
        self.assertEqual(pending, after_pending)
        self.assertEqual(len(before['info']['x-aisa-document']['response_pending']), 1)
        self.assertEqual(after['info']['x-aisa-document']['response_pending'], [])
        old, new = before['paths'][PUBLIC_PATH]['get'], after['paths'][PUBLIC_PATH]['get']
        for key in ('operationId', 'parameters', 'x-aisa-pricing'):
            self.assertEqual(old[key], new[key])
        self.assertIn('content', new['responses']['2XX'])
        self.assertNotIn('200', new['responses'])
        self.assertEqual(compose(self.runtime, public_mirrors=self.mirrors(), previous=after), (after, []))

    def test_changed_path_origin_or_transformed_transport_remains_untyped(self):
        for key, value in [('x-aisa-response-upstream-path-sha256', '0' * 64),
                           ('x-aisa-response-upstream-origin-sha256', '0' * 64),
                           ('x-aisa-response-passthrough', False)]:
            with self.subTest(key=key):
                runtime = copy.deepcopy(self.runtime)
                runtime['paths'][PUBLIC_PATH]['get'][key] = value
                result, _ = compose(runtime, public_mirrors=self.mirrors())
                self.assertEqual(len(result['info']['x-aisa-document']['response_pending']), 1)
                self.assertNotIn('content', result['paths'][PUBLIC_PATH]['get']['responses']['200'])
