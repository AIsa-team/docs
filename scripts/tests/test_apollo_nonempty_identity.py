import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft7Validator
from compose_openapi import digest
from source_governance import policy_errors


ROOT = Path(__file__).resolve().parents[2]


class ApolloNonemptyIdentityTests(unittest.TestCase):
    def test_flags_and_empty_values_cannot_stand_in_for_identity(self):
        review = json.loads((ROOT / 'docs/current-source-review-20261017/apollo-nonempty-identity-review.json').read_text())
        doc = json.loads((ROOT / review['source_file']).read_text())
        schema = doc['paths'][review['source_path']]['post']['requestBody']['content']['application/json']['schema']
        validator = Draft7Validator(schema)
        for value in ({}, {'reveal_personal_emails': True}, {'reveal_personal_emails': False},
                      {field: '' for field in review['identity_fields']},
                      {'name': '', 'reveal_personal_emails': True}):
            with self.subTest(value=value):
                self.assertFalse(validator.is_valid(value))
        for field in review['identity_fields']:
            validator.validate({field: 'identity', 'reveal_personal_emails': False})
        validator.validate({'name': 'Tim Zheng', 'domain': 'apollo.io'})
        validator.validate({'email': 'person@example.com', 'name': ''})
        self.assertEqual(schema['anyOf'], review['added_anyOf'])

    def test_only_the_existing_client_identity_rule_is_completed(self):
        review = json.loads((ROOT / 'docs/current-source-review-20261017/apollo-nonempty-identity-review.json').read_text())
        doc = json.loads((ROOT / review['source_file']).read_text())
        source = doc['info'].pop('x-aisa-source')
        self.assertEqual(source['content_hash'], digest(doc))
        later = json.loads((ROOT / 'docs/current-source-review-20261017/apollo-bulk-update-request-review.json').read_text())
        self.assertEqual(source['prior_source'], later['prior_source'])
        self.assertEqual(doc['paths'][later['source_path']]['post']['requestBody'], later['official_request_body'])
        doc['paths'][later['source_path']]['post']['requestBody'] = copy.deepcopy(later['previous_request_body'])
        source = source['prior_source']
        self.assertEqual(source['content_hash'], digest(doc))
        self.assertEqual(source['prior_source'], review['prior_source'])
        self.assertFalse(policy_errors(source))
        for key in ('kind', 'url', 'fetched_at', 'owner', 'refresh_policy', 'review_period_days', 'policy_revision'):
            self.assertEqual(source[key], review['prior_source'][key])
        schema = doc['paths'][review['source_path']]['post']['requestBody']['content']['application/json']['schema']
        schema.pop('anyOf')
        self.assertEqual(digest(doc), review['unchanged_declarations_sha256'])


if __name__ == '__main__':
    unittest.main()
