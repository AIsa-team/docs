import hashlib
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

from openapi_spec_validator import validate

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from import_duffel_flights_reference import convert, OPERATIONS, SDK_HASHES
from import_duffel_reference import NextData

FIXTURE = Path(__file__).parent / 'fixtures/duffel-flights-reference-20261009.tar.gz'
FIXTURE_HASH = 'cbfe38ed1f5b7d23abc7a325ea60f7c40449d1807d442cc0a43fbde77757b677'


class DuffelFlightsReferenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.tmp.name)
        assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == FIXTURE_HASH
        with tarfile.open(FIXTURE) as archive:
            archive.extractall(cls.directory, filter='data')
        cls.source = convert(cls.directory, '2026-10-09T03:46:00Z')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def resource(self, slug):
        return json.loads(''.join(NextData((self.directory / (slug + '.html')).read_bytes()).parts))['props']['pageProps']['resource']

    def test_all_selected_request_declarations_are_copied_without_inference(self):
        for slug, selected in OPERATIONS.items():
            for item in self.resource(slug)['operations']:
                if item['slug'] not in selected:
                    continue
                method, path, _, body, _ = selected[item['slug']]
                operation = self.source['paths'][path][method.lower()]
                self.assertEqual(operation['parameters'], item['requestParameters'])
                if body:
                    request = operation['requestBody']
                    self.assertTrue(request['required'])
                    schema = request['content']['application/json']['schema']
                    self.assertEqual(schema['required'], ['data'])
                    self.assertEqual(schema['properties']['data'], item['bodyDataSchema'])
                else:
                    self.assertNotIn('requestBody', operation)

    def test_conditional_offer_request_payload_remains_untyped(self):
        for path, method in [('/air/offer_requests', 'post'), ('/air/offer_requests/{id}', 'get')]:
            response = self.source['paths'][path][method]['responses']['2XX']
            self.assertNotIn('content', response)
            self.assertIn('view=itineraries', response['description'])
        listing = self.source['paths']['/air/offer_requests']['get']['responses']['2XX']
        self.assertEqual(listing['content']['application/json']['schema']['properties']['data']['type'], 'array')

    def test_cancel_confirmation_uses_no_body_and_resource_model(self):
        operation = self.source['paths']['/air/order_cancellations/{id}/actions/confirm']['post']
        self.assertNotIn('requestBody', operation)
        response = operation['responses']['2XX']['content']['application/json']['schema']
        self.assertEqual(response['properties']['data'], self.resource('order-cancellations')['model'])
        self.assertNotIn('status', response['properties'])

    def test_rejects_changed_sdk_or_endpoint(self):
        name = next(iter(SDK_HASHES))
        path = self.directory / name
        original = path.read_bytes()
        try:
            path.write_bytes(original + b'\n')
            with self.assertRaisesRegex(ValueError, 'SDK authority hash mismatch'):
                convert(self.directory, '2026-10-09T03:46:00Z')
        finally:
            path.write_bytes(original)
        path = self.directory / 'orders.html'
        original = path.read_bytes()
        try:
            path.write_bytes(original.replace(b'https://api.duffel.com/air/orders', b'https://api.duffel.com/air/wrong_orders'))
            with self.assertRaisesRegex(ValueError, 'operation identity'):
                convert(self.directory, '2026-10-09T03:46:00Z')
        finally:
            path.write_bytes(original)

    def test_actual_converted_source_has_valid_openapi_and_13_operations(self):
        validate(self.source)
        self.assertEqual(sum(len(item) for item in self.source['paths'].values()), 13)
        self.assertEqual(self.source['info']['x-aisa-source']['kind'], 'manual')


if __name__ == '__main__':
    unittest.main()
