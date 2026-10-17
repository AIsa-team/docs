import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft7Validator
from compose_openapi import compose, digest
from runtime_registry import public_mirror_index
from test_runtime_contracts import facts, operation
from apollo_source_history import undo_contact_bulk_body_amendment

ROOT = Path(__file__).resolve().parents[2]


class ApolloContactBulkBodyTests(unittest.TestCase):
    def test_only_request_location_and_schema_change(self):
        review = json.loads((ROOT / 'docs/current-source-review-20261017/apollo-contact-bulk-body-review.json').read_text())
        doc = json.loads((ROOT / review['source_file']).read_text())
        source = doc['info'].pop('x-aisa-source')
        op = copy.deepcopy(doc['paths'][review['source_path']]['post'])
        self.assertNotIn('parameters', op)
        self.assertEqual(op.pop('requestBody'), review['official_request_body'])
        prior = copy.deepcopy(review['prior_operation'])
        prior.pop('parameters', None)
        self.assertEqual(op, prior)
        undo_contact_bulk_body_amendment(self, ROOT, doc, source)
        for key in ('kind', 'url', 'fetched_at', 'owner', 'refresh_policy', 'review_period_days', 'policy_revision'):
            self.assertEqual(source[key], review['prior_source'][key])

    def test_normal_composition_has_required_body_and_structured_ids(self):
        runtime = facts('provider', 'post')
        op = copy.deepcopy(operation(runtime))
        op.update(operationId='post_apollo_contacts_bulk_update', parameters=[],
                  **{'x-aisa-upstream-path': '/api/v1/contacts/bulk_update',
                     'x-aisa-query-policy': {'request_wins': True}})
        runtime['paths'] = {'/apis/v1/apollo/contacts/bulk_update': {'post': op}}
        document, pending = compose(runtime, public_mirrors=public_mirror_index(ROOT))
        self.assertFalse(pending)
        op = document['paths']['/apis/v1/apollo/contacts/bulk_update']['post']
        self.assertFalse(op.get('parameters'))
        self.assertTrue(op['requestBody']['required'])
        validator = Draft7Validator(op['requestBody']['content']['application/json']['schema'])
        validator.validate({'contact_ids': ['contact_fixture'], 'owner_id': 'owner_fixture'})
        validator.validate({'contact_attributes': [{'id': 'contact_fixture', 'title': 'Example'}]})
        self.assertFalse(validator.is_valid({'contact_ids': 'wrong_type'}))
        self.assertFalse(validator.is_valid({'contact_attributes': [{'title': 'missing_id'}]}))


if __name__ == '__main__':
    unittest.main()
