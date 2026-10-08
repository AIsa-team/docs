import hashlib
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from openapi_spec_validator import validate

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from import_duffel_reference import convert, page, NextData, SDK_HASHES
from compose_openapi import compose, upstream_path_item

FIXTURE = Path(__file__).parent / 'fixtures/duffel-reference-20261008.tar.gz'
FIXTURE_HASH = '82d6d97df3b7530557aeaf4b0cd61fda621d9b66373f57816f8be059473eab5b'


class DuffelReferenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.tmp.name)
        if hashlib.sha256(FIXTURE.read_bytes()).hexdigest() != FIXTURE_HASH:
            raise ValueError('official fixture changed')
        with tarfile.open(FIXTURE) as archive:
            archive.extractall(cls.directory, filter='data')
        cls.source = convert(cls.directory, '2026-10-08T09:15:20Z')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_preserves_official_schema_without_example_inference(self):
        model = page((self.directory / 'search.html').read_bytes(), 'search')['model']
        schema = self.source['paths']['/stays/search']['post']['responses']['2XX']['content']['application/json']['schema']
        self.assertEqual(schema['properties']['data'], model)
        self.assertEqual(schema['required'], ['data'])
        self.assertNotIn('status', schema['properties'])
        self.assertNotIn('headers', schema['properties'])
        self.assertNotIn('required', schema['properties']['data'])

    def test_array_and_optional_metadata_from_sdk(self):
        response = self.source['paths']['/stays/bookings']['get']['responses']['2XX']
        schema = response['content']['application/json']['schema']
        self.assertEqual(schema['properties']['data']['type'], 'array')
        self.assertEqual(schema['properties']['meta']['properties']['after'], {'type': 'string', 'nullable': True})

    def test_converted_source_is_valid_openapi_30(self):
        validate(self.source)

    def test_rejects_changed_sdk_authority(self):
        path = self.directory / next(iter(SDK_HASHES))
        original = path.read_bytes()
        try:
            path.write_bytes(original + b'\n')
            with self.assertRaisesRegex(ValueError, 'SDK authority hash'):
                convert(self.directory, '2026-10-08T09:15:20Z')
        finally:
            path.write_bytes(original)

    def test_rejects_duplicate_or_wrong_version_next_data(self):
        raw = (self.directory / 'search.html').read_bytes()
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            NextData(raw + raw)
        with self.assertRaisesRegex(ValueError, 'version mismatch'):
            page(raw.replace(b'"version":"v2"', b'"version":"v1"'), 'search')

    def test_does_not_alias_get_search_result_or_get_rates_to_post(self):
        self.assertFalse(upstream_path_item(self.source, '/stays/search_results/{id}'))
        self.assertFalse(upstream_path_item(self.source, '/stays/search_results/{id}/rates'))
        self.assertEqual(list(self.source['paths']['/stays/search_results/{search_result_id}/actions/fetch_all_rates']), ['post'])

    def test_only_alpha_renames_cancel_parameter(self):
        operation = self.source['paths']['/stays/bookings/{id}/actions/cancel']['post']
        self.assertEqual(operation['x-aisa-reference-path'], '/stays/bookings/{booking_id}/actions/cancel')
        self.assertEqual(operation['parameters'][0]['name'], 'id')

    def test_synthetic_composer_preserves_nullable_and_missing_route(self):
        # These are synthetic projection inputs, never claimed as Runtime facts.
        facts = {'openapi': '3.1.0', 'info': {'title': 'Synthetic', 'version': '1',
                 'x-aisa-document': {'facts_hash': 'synthetic'}}, 'paths': {}}
        for path, method in [('/stays/quotes/{id}', 'get'), ('/stays/search', 'post'),
                             ('/stays/search_results/{id}', 'get')]:
            facts['paths'][path] = {method: {'operationId': 'test' + str(len(facts['paths'])),
                'x-aisa-status': 'enabled', 'x-aisa-validation': 'provider',
                'x-aisa-upstream-path': path, 'x-aisa-passthrough': True,
                'responses': {'200': {'description': 'Pending'}}}}
        result, pending = compose(facts, [self.source])
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]['path'], '/stays/search_results/{id}')
        request = result['paths']['/stays/search']['post']['requestBody']
        self.assertEqual(request['content']['application/json']['schema']['required'], ['data'])
        schema = result['paths']['/stays/quotes/{id}']['get']['responses']['2XX']['content']['application/json']['schema']
        self.assertEqual(schema['properties']['meta']['properties']['after']['type'], ['string', 'null'])


if __name__ == '__main__':
    unittest.main()
