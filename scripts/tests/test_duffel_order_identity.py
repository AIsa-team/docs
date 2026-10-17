"""Get Flight Order keeps its own identity and the official Duffel declaration."""
import hashlib
import json
from pathlib import Path
import re
import sys
import tarfile
import tempfile
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from identity_compatibility import operations, validate_document_identities
from import_duffel_reference import NextData, ORIGIN, envelope
from readable_contract_notes import BEGIN, END, readable_block
from runtime_localize_openapi_zh import split_frontmatter
from source_json import loads
from validate_runtime_api_reference_slugs import validate as validate_slugs

REPO = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).parent / 'fixtures/duffel-flights-reference-20261009.tar.gz'
FIXTURE_HASH = 'cbfe38ed1f5b7d23abc7a325ea60f7c40449d1807d442cc0a43fbde77757b677'
SPEC = 'openapi/duffel.json'
ROUTE = '/duffel/flights/orders/{id}'
PAGE = 'api-reference/duffel/get_duffel-flights-orders-id.mdx'
# domain.NewIntegrationOperationID("GET", "duffel-flights", "/apis/v1/duffel/flights/orders/{id}")
ORDER_ID = 'get_duffel_flights_apis_v1_duffel_flights_orders_id'
CHANGE_REQUEST_ID = 'get_duffel_order_change_request'
CHANGE_REQUEST_ROUTE = ('/apis/v1/duffel/flights/order-change-requests/{id}', 'GET')


def provider_documents():
    return {path.stem: json.loads(path.read_text()) for path in sorted((REPO / 'openapi').glob('*.json'))
            if path.name != 'openapi.json'}


def document(prefix, paths):
    return {'openapi': '3.0.3', 'info': {'title': 't', 'version': '1'}, 'servers': [{'url': 'https://api.aisa.one' + prefix}],
            'paths': {path: {'get': {'operationId': identity, 'responses': {}}} for path, identity in paths.items()}}


class RouteOwnerTests(unittest.TestCase):
    def test_borrowed_identity_on_a_second_route_is_rejected(self):
        runtime = document('', {'/apis/v1/duffel/flights/order-change-requests/{id}': CHANGE_REQUEST_ID})
        legacy = document('/apis/v1', {'/duffel/flights/order-change-requests/{id}': CHANGE_REQUEST_ID,
                                       '/duffel/flights/orders/{id}': CHANGE_REQUEST_ID})
        with self.assertRaisesRegex(ValueError, 'multiple route owners: ' + CHANGE_REQUEST_ID):
            validate_document_identities({'duffel-flights': runtime, 'duffel': legacy}, None)

    def test_legacy_and_runtime_copies_of_one_route_may_share_its_identity(self):
        runtime = document('', {'/apis/v1/duffel/flights/order-change-requests/{id}': CHANGE_REQUEST_ID})
        legacy = document('/apis/v1', {'/duffel/flights/order-change-requests/{id}': CHANGE_REQUEST_ID,
                                       '/duffel/flights/orders/{id}': ORDER_ID})
        validate_document_identities({'duffel-flights': runtime, 'duffel': legacy}, None)

    def test_current_sources_have_one_route_per_identity(self):
        owners = {}
        for value in provider_documents().values():
            for path, method, operation in operations(value):
                if operation.get('operationId'):
                    owners.setdefault(operation['operationId'], set()).add((path, method))
        self.assertEqual(owners[CHANGE_REQUEST_ID], {CHANGE_REQUEST_ROUTE})
        self.assertEqual(owners[ORDER_ID], {('/apis/v1' + ROUTE, 'GET')})
        self.assertEqual({key for key, routes in owners.items() if len(routes) > 1}, set())


class OfficialOrderDeclarationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == FIXTURE_HASH
        with tempfile.TemporaryDirectory() as directory, tarfile.open(FIXTURE) as archive:
            archive.extractall(directory, filter='data')
            raw = (Path(directory) / 'orders.html').read_bytes()
        cls.resource = loads(''.join(NextData(raw).parts))['props']['pageProps']['resource']
        [cls.official] = [item for item in cls.resource['operations'] if item['slug'] == 'get-order-by-id']
        cls.document = json.loads((REPO / SPEC).read_text())
        cls.operation = cls.document['paths'][ROUTE]['get']

    def test_official_binding_is_the_order_resource_read(self):
        self.assertEqual(self.official['endpoint'], {'method': 'GET', 'uri': ORIGIN + '/air/orders/{id}'})
        self.assertEqual(self.official['requestHeaders'].get('Duffel-Version'), 'v2')
        self.assertNotIn('bodyDataSchema', self.official)

    def test_request_and_response_are_projected_without_inference(self):
        self.assertEqual(self.operation['operationId'], ORDER_ID)
        self.assertEqual(self.operation['parameters'], self.official['requestParameters'])
        self.assertNotIn('requestBody', self.operation)
        self.assertEqual(set(self.operation['responses']), {'2XX'})
        schema = self.operation['responses']['2XX']['content']['application/json']['schema']
        self.assertEqual(schema, envelope(self.resource['model']))
        self.assertEqual(schema['properties']['data']['description'], 'An order represents a booking with an airline')

    def test_order_prose_no_longer_describes_change_requests(self):
        text = json.dumps([self.operation['summary'], self.operation['description'],
                           self.operation['responses']['2XX']['description']]).lower()
        self.assertNotIn('change', text)
        self.assertIn('order', text)

    def test_page_identity_and_readable_contract_match_the_source(self):
        text = (REPO / PAGE).read_text()
        header = yaml.safe_load(split_frontmatter(text)[0])
        self.assertEqual(header['openapi'], f'{SPEC} GET {ROUTE}')
        self.assertEqual(header['x-aisa-operation-id'], ORDER_ID)
        expected = readable_block(self.operation, 'en', document=self.document, method='get', path=ROUTE, spec_path=SPEC)
        self.assertEqual(re.findall(re.escape(BEGIN) + r'.*?' + re.escape(END), text, re.S), [expected])
        self.assertEqual(self.slug_errors(text), [])

    def test_page_identity_mismatch_is_reported(self):
        text = (REPO / PAGE).read_text().replace(ORDER_ID, CHANGE_REQUEST_ID, 1)
        self.assertTrue(any('identity differs' in error for error in self.slug_errors(text)))

    def slug_errors(self, text):
        # Only this page and its source: the full-repository check is the CI step.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'openapi').mkdir()
            (root / SPEC).write_bytes((REPO / SPEC).read_bytes())
            (root / PAGE).parent.mkdir(parents=True)
            (root / PAGE).write_text(text)
            return validate_slugs(root, generated_only=True)


if __name__ == '__main__':
    unittest.main()
