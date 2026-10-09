import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sales_catalog_projection import (SALES_CATALOG_PATH, project_sales_catalog,
                                      sales_catalog_bytes, verify_sales_catalog)
from publication_surface import publication_hashes


class SalesProjectionTests(unittest.TestCase):
    def fixture(self):
        return {'openapi': '3.1.0', 'info': {'title': 'Catalog', 'version': '1',
            'x-aisa-document': {'providers': {'p': {'display_name': 'Provider', 'source': 'runtime',
                'catalog_ids': ['p'], 'document_hash': 'hash', 'catalogs': {'p': {'private_unused': 'omit'}},
                'unselected': 'omit'}}}}, 'servers': [{'url': 'https://api.example.invalid'}],
            'paths': {'/read': {'servers': [{'url': 'https://api.example.invalid/base'}],
                'get': {'operationId': 'read', 'summary': 'Read', 'description': 'Public description',
                    'x-aisa-provider': 'p', 'x-aisa-status': 'enabled',
                    'x-aisa-revision': {'profile_ref': '709335695e33'},
                    'x-aisa-pricing': {'default_request_estimate_usd': 0, 'cost_contract': 'fixed_success'},
                    'x-aisa-runtime-operation': {'operation_id': 'native_any', 'method': 'ANY'},
                    'parameters': [{'name': 'q'}], 'requestBody': {'huge': 'body'},
                    'responses': {'200': {'description': 'unknown'}}, 'security': [{'bearer': []}]},
                'post': {'operationId': 'disabled', 'x-aisa-status': 'disabled'}},
                '/missing-method': {'description': 'No invented operation'}},
            'components': {'schemas': {'Huge': {'properties': {'a': {'type': 'string'}}}}}}

    def test_projection_keeps_exact_metadata_types_identity_and_status(self):
        full = self.fixture(); original = copy.deepcopy(full)
        wrapper = project_sales_catalog(full, 'a' * 64)
        doc = wrapper['document']; op = doc['paths']['/read']['get']
        self.assertEqual(full, original)
        self.assertEqual(op['x-aisa-revision']['profile_ref'], '709335695e33')
        self.assertIs(type(op['x-aisa-revision']['profile_ref']), str)
        self.assertEqual(op['x-aisa-pricing']['default_request_estimate_usd'], 0)
        self.assertEqual(op['x-aisa-runtime-operation'], full['paths']['/read']['get']['x-aisa-runtime-operation'])
        self.assertEqual(doc['paths']['/read']['post']['x-aisa-status'], 'disabled')
        self.assertEqual(doc['paths']['/missing-method'], {})
        self.assertEqual(doc['servers'], full['servers'])
        self.assertEqual(doc['paths']['/read']['servers'], full['paths']['/read']['servers'])
        self.assertEqual(doc['info']['x-aisa-document']['providers']['p']['catalogs'], {'p': {}})
        for field in ('parameters', 'requestBody', 'responses', 'security'): self.assertNotIn(field, op)
        self.assertNotIn('components', doc)
        self.assertNotIn('unselected', doc['info']['x-aisa-document']['providers']['p'])

    def test_whole_bundle_hash_changes_even_if_only_schema_changes(self):
        full = self.fixture()
        first = json.loads(sales_catalog_bytes(full, b'first full graph'))
        second = json.loads(sales_catalog_bytes(full, b'changed full graph'))
        self.assertEqual(first['document'], second['document'])
        self.assertNotEqual(first['openapi_sha256'], second['openapi_sha256'])

    def test_deterministic_projection_and_exact_manifest_membership(self):
        full = self.fixture(); raw = b'complete original bundle'
        payload = sales_catalog_bytes(full, raw)
        self.assertEqual(payload, sales_catalog_bytes(full, raw))
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); path = root / SALES_CATALOG_PATH; path.parent.mkdir(parents=True)
            with self.assertRaises(ValueError): verify_sales_catalog(root, full, raw)
            path.write_bytes(payload)
            self.assertEqual(verify_sales_catalog(root, full, raw), hashlib.sha256(payload).hexdigest())
            self.assertEqual(publication_hashes(root)[SALES_CATALOG_PATH], hashlib.sha256(payload).hexdigest())
            for field in ('x-aisa-pricing', 'x-aisa-revision', 'x-aisa-runtime-operation'):
                changed = json.loads(payload); changed['document']['paths']['/read']['get'][field] = {}
                path.write_text(json.dumps(changed))
                with self.assertRaises(ValueError): verify_sales_catalog(root, full, raw)
            path.write_bytes(payload)
            with self.assertRaises(ValueError): verify_sales_catalog(root, full, b'different complete bytes')


if __name__ == '__main__': unittest.main()
