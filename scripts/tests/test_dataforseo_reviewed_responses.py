import copy
import json
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import resolve, schema_30_to_31

ROOT = Path(__file__).resolve().parents[2]
MIRROR = ROOT / 'openapi/upstream/dataforseo-official.json'
REVIEW = ROOT / 'docs/current-source-review-20261114/dataforseo-response-review.json'


def response_validator(document, path):
    schema = document['paths'][path]['post']['responses']['200']['content']['application/json']['schema']
    return Draft202012Validator(schema_30_to_31(resolve(schema, document)))


class DataforseoReviewedResponseTests(unittest.TestCase):
    """Live AIsa responses replayed against the reviewed DataForSEO source."""

    @classmethod
    def setUpClass(cls):
        cls.document = json.loads(MIRROR.read_text())
        cls.review = json.loads(REVIEW.read_text())
        cls.observed = {o['upstream_path']: o for o in cls.review['live_observations']}

    def test_review_binds_this_exact_source(self):
        source = self.document['info']['x-aisa-source']
        self.assertEqual(self.review['source_hash_after'], source['content_hash'])
        self.assertEqual(self.review['policy_revision'], source['policy_revision'])
        self.assertEqual(source['converter'], 'scripts/import_dataforseo_filters.py@3')
        for key, value in self.review['corrections'].items():
            if key in source:
                self.assertEqual(source[key], value, key)

    def test_complete_live_responses_pass(self):
        self.assertEqual(set(self.observed), {
            '/v3/backlinks/anchors/live', '/v3/dataforseo_labs/google/keyword_overview/live',
            '/v3/serp/google/organic/live/advanced'})
        for path, observation in self.observed.items():
            with self.subTest(path):
                self.assertEqual((observation['http_status'], observation['business']), (200, 'PASS'))
                response_validator(self.document, path).validate(observation['response'])

    def test_result_constraints_still_reject_wrong_values(self):
        path = '/v3/serp/google/organic/live/advanced'
        check = response_validator(self.document, path)
        response = self.observed[path]['response']
        items = response['tasks'][0]['result'][0]['items']
        organic = next(i for i, item in enumerate(items) if item['type'] == 'organic')
        graph = next(i for i, item in enumerate(items) if item['type'] == 'knowledge_graph')

        def item(r, index):
            return r['tasks'][0]['result'][0]['items'][index]

        for label, mutate in [
            ('echo data envelope', lambda r: r['tasks'][0].__setitem__('data', ['not-an-object'])),
            ('task cost type', lambda r: r['tasks'][0].__setitem__('cost', 'invalid')),
            ('organic rank_group type', lambda r: item(r, organic).__setitem__('rank_group', '1')),
            ('organic domain type', lambda r: item(r, organic).__setitem__('domain', 5)),
            ('unknown item type', lambda r: item(r, organic).__setitem__('type', 'not_a_serp_item')),
            ('missing item type', lambda r: item(r, organic).pop('type')),
            ('refinement_chips type', lambda r: r['tasks'][0]['result'][0].__setitem__('refinement_chips', 'x')),
            ('rectangle type', lambda r: item(r, organic).__setitem__('rectangle', 5)),
            ('nested knowledge graph item tag', lambda r: item(r, graph)['items'][0].__setitem__('type', 'organic')),
            ('scalar item', lambda r: r['tasks'][0]['result'][0]['items'].append('x')),
        ]:
            with self.subTest(label):
                instance = copy.deepcopy(response)
                mutate(instance)
                self.assertFalse(check.is_valid(instance))

    def test_request_schemas_keep_their_declared_shapes(self):
        schemas = self.document['components']['schemas']
        mode = schemas['BacklinksBacklinksLiveRequestInfo']['properties']['custom_mode']
        self.assertNotIn('enum', json.dumps(mode))
        organic = schemas['SerpGoogleOrganicLiveAdvancedRequestInfo']
        self.assertNotIn('discriminator', json.dumps(organic))


if __name__ == '__main__':
    unittest.main()
