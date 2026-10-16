import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import compose, digest
from runtime_registry import public_mirror_index

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'openapi/upstream/apollo.json'
# Runtime Profiles for endpoints 2437 and 2438 declare exactly these query
# fields, reject any other query parameter and forward an opaque body.
RUNTIME_QUERY = ['reveal_phone_number', 'run_waterfall_email', 'run_waterfall_phone', 'webhook_url']
IDENTITY = ['domain', 'email', 'first_name', 'hashed_email', 'id', 'last_name', 'linkedin_url', 'name', 'organization_name']


def runtime_facts():
    parameters = [{'name': name, 'in': 'query', 'required': False,
                   'schema': {'type': 'string'} if name == 'webhook_url' else {'type': 'boolean', 'default': False}}
                  for name in RUNTIME_QUERY]
    paths = {}
    for suffix, operation_id in (('match', 'post_apollo_people_match'), ('bulk_match', 'post_apollo_people_bulk_match')):
        paths['/apis/v1/apollo/people/' + suffix] = {'post': {
            'operationId': operation_id, 'x-aisa-validation': 'mixed', 'x-aisa-status': 'enabled',
            'x-aisa-query-policy': {'request_wins': False, 'ignore_undeclared': False},
            'x-aisa-pricing': {'default_request_estimate_usd': 0.17775},
            'parameters': copy.deepcopy(parameters),
            'responses': {'200': {'description': 'Success'}}}}
    return {'openapi': '3.1.0', 'servers': [{'url': 'https://api.aisa.one'}],
            'info': {'title': 'Apollo', 'version': '1', 'x-aisa-document': {'facts_hash': 'sha256:apollo-people'}},
            'paths': paths}


class ApolloPeopleRequestLocationTests(unittest.TestCase):
    def setUp(self):
        self.source = json.loads(SOURCE.read_text())

    def test_amended_source_has_new_content_identity(self):
        document = copy.deepcopy(self.source)
        source = document['info'].pop('x-aisa-source')
        self.assertEqual(source['content_hash'], digest(document))
        self.assertNotEqual(source['content_hash'], source['prior_source']['content_hash'])
        self.assertEqual(source['policy_revision'], source['prior_source']['policy_revision'])

    def test_source_query_matches_runtime_and_inputs_are_in_body(self):
        single = self.source['paths']['/apollo/people/match']['post']
        self.assertEqual(sorted(p['name'] for p in single['parameters'] if p['in'] == 'query'), RUNTIME_QUERY)
        schema = single['requestBody']['content']['application/json']['schema']
        self.assertTrue(single['requestBody']['required'])
        self.assertEqual(schema['minProperties'], 1)
        self.assertEqual(sorted(schema['properties']), sorted(IDENTITY + ['reveal_personal_emails']))
        bulk = self.source['paths']['/apollo/people/bulk_match']['post']
        self.assertEqual(sorted(p['name'] for p in bulk['parameters'] if p['in'] == 'query'), RUNTIME_QUERY)
        bulk_schema = bulk['requestBody']['content']['application/json']['schema']
        self.assertEqual(sorted(bulk_schema['properties']), ['details', 'reveal_personal_emails'])
        self.assertEqual(sorted(bulk_schema['properties']['details']['items']['properties']), IDENTITY)

    def test_published_people_match_lets_callers_identify_a_person(self):
        document, pending = compose(runtime_facts(), public_mirrors=public_mirror_index(ROOT))
        self.assertEqual(pending, [])
        single = document['paths']['/apis/v1/apollo/people/match']['post']
        self.assertEqual(sorted(p['name'] for p in single['parameters']), RUNTIME_QUERY)
        body = single['requestBody']['content']['application/json']['schema']
        self.assertTrue(set(IDENTITY) <= set(body['properties']))
        bulk = document['paths']['/apis/v1/apollo/people/bulk_match']['post']
        self.assertIn('reveal_personal_emails', bulk['requestBody']['content']['application/json']['schema']['properties'])


if __name__ == '__main__':
    unittest.main()
