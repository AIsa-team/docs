import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft7Validator
from compose_openapi import compose, digest
from runtime_registry import public_mirror_index
from test_runtime_contracts import facts, operation
from apollo_source_history import undo_object_body_amendment

ROOT = Path(__file__).resolve().parents[2]


class ApolloBulkUpdateRequestTests(unittest.TestCase):
    def test_exact_supplier_body_and_only_one_operation_changed(self):
        review = json.loads((ROOT / 'docs/current-source-review-20261017/apollo-bulk-update-request-review.json').read_text())
        doc = json.loads((ROOT / review['source_file']).read_text())
        source = doc['info'].pop('x-aisa-source')
        self.assertEqual(source['content_hash'], digest(doc))
        source = undo_object_body_amendment(self, ROOT, doc, source)
        self.assertEqual(source['prior_source'], review['prior_source'])
        for key in ('kind', 'url', 'fetched_at', 'owner', 'refresh_policy', 'review_period_days', 'policy_revision'):
            self.assertEqual(source[key], review['prior_source'][key])
        body = doc['paths'][review['source_path']]['post']['requestBody']
        self.assertEqual(body, review['official_request_body'])
        self.assertEqual(digest(body), review['official_request_body_sha256'])
        doc['paths'][review['source_path']]['post']['requestBody'] = copy.deepcopy(review['previous_request_body'])
        self.assertEqual(digest(doc), review['prior_source']['content_hash'])

    def test_normal_composition_accepts_shared_or_individual_update_arrays(self):
        runtime = facts('provider', 'post')
        op = copy.deepcopy(operation(runtime))
        op.update(operationId='post_apollo_accounts_bulk_update', parameters=[],
                  **{'x-aisa-upstream-path': '/api/v1/accounts/bulk_update',
                     'x-aisa-query-policy': {'request_wins': True}})
        runtime['paths'] = {'/apis/v1/apollo/accounts/bulk_update': {'post': op}}
        document, pending = compose(runtime, public_mirrors=public_mirror_index(ROOT))
        self.assertFalse(pending)
        body = document['paths']['/apis/v1/apollo/accounts/bulk_update']['post']['requestBody']
        self.assertTrue(body['required'])
        validator = Draft7Validator(body['content']['application/json']['schema'])
        validator.validate({'account_ids': ['account_fixture'], 'owner_id': 'owner_fixture', 'async': False})
        validator.validate({'account_attributes': [{'id': 'account_fixture', 'name': 'Example'}]})
        for invalid in ({'account_ids': 'account_fixture'}, {'account_attributes': 'fixture'},
                        {'account_attributes': [{'name': 'missing id'}]}):
            self.assertFalse(validator.is_valid(invalid), invalid)


if __name__ == '__main__':
    unittest.main()
