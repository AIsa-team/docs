"""Verify exact Composio projection; no sample-derived business type claims."""
import copy
import json
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from compose_openapi import compose, digest
from runtime_registry import public_mirror_index


class ComposioFacebookResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.review = json.loads((ROOT / 'docs/current-source-review-20261110/facebook-eight-response-review.json').read_text())
        cls.mirrors = public_mirror_index(ROOT)
        cls.document, _ = compose(cls.review['runtime_facts'], public_mirrors=cls.mirrors, unreviewed_runtime=True)

    def test_five_customer_schemas_equal_provider_declared_business_envelopes(self):
        rows = [r for r in self.review['sources'] if r['method'] == 'post']
        self.assertEqual(len(rows), 5)
        for row in rows:
            source = json.loads((ROOT / row['envelope_source_file']).read_text())
            operation = source['paths'][row['path']]['post']
            self.assertEqual(set(operation), {'responses'})
            self.assertEqual(digest({'operation': operation, 'components': {}}), row['source_content_hash'])
            schema = self.document['paths'][row['path']]['post']['responses']['200']['content']['application/json']['schema']
            self.assertEqual(schema, row['official_outer_schema'])
            self.assertNotIn('properties', schema['properties']['data'])
            self.assertNotIn('type', schema['properties']['data'])
            validator = Draft202012Validator(schema)
            validator.validate({'code': 0, 'data': {'future_field': []}, 'message': None, 'recordTime': None})
            with self.assertRaises(ValidationError):
                validator.validate({'successful': True, 'data': {}})
            self.assertFalse(row['full_contract_verified'])

    def test_only_five_success_responses_change(self):
        selected = {(r['path'], 'post') for r in self.review['sources'] if r['method'] == 'post'}
        before, _ = compose(self.review['runtime_facts'], public_mirrors={k: v for k, v in self.mirrors.items() if k not in selected}, unreviewed_runtime=True)
        for path, item in self.document['paths'].items():
            for method, operation in item.items():
                old = before['paths'][path][method]
                if (path, method) not in selected:
                    self.assertEqual(operation, old)
                    continue
                exclude = {'responses', 'x-aisa-response-source', 'x-aisa-review'}
                self.assertEqual({k: v for k, v in operation.items() if k not in exclude},
                                 {k: v for k, v in old.items() if k not in exclude})
                self.assertEqual(operation['responses']['default'], old['responses']['default'])

    def test_transport_change_rejects_old_response_source(self):
        path = '/apis/v1/facebook/get-post-comments'
        for field in ['x-aisa-response-upstream-path-sha256', 'x-aisa-response-upstream-origin-sha256']:
            facts = copy.deepcopy(self.review['runtime_facts'])
            facts['paths'][path]['post'][field] = '0' * 64
            doc, _ = compose(facts, public_mirrors=self.mirrors, unreviewed_runtime=True)
            self.assertIn('x-aisa-response-pending', doc['paths'][path]['post'])


if __name__ == '__main__':
    unittest.main()
