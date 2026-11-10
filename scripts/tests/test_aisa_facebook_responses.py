"""Check the actual generated customer documents, including concrete bad types."""
import copy
import json
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from compose_openapi import compose
from runtime_registry import public_mirror_index


class AisaCustomerResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.review = json.loads((ROOT / 'docs/current-source-review-20261110/aisa-customer-response-check.json').read_text())
        cls.document = json.loads((ROOT / 'openapi/facebook.json').read_text())
        cls.mirrors = public_mirror_index(ROOT)

    def media(self, row):
        return self.document['paths'][row['path']][row['method']]['responses']['200']['content']['application/json']

    def test_final_59_schemas_exist_and_examples_validate(self):
        count = 0
        for name in ['facebook', 'tiktok']:
            document = json.loads((ROOT / 'openapi' / (name + '.json')).read_text())
            zh = json.loads((ROOT / 'openapi/zh' / (name + '.json')).read_text())
            for path, item in document['paths'].items():
                for method, operation in item.items():
                    if method not in {'get', 'post'}:
                        continue
                    media = operation['responses']['200']['content']['application/json']
                    self.assertTrue(media['schema'], (name, path))
                    self.assertNotIn('payload schema has not been reviewed', operation['responses']['200']['description'])
                    validator = Draft202012Validator(media['schema'])
                    validator.check_schema(media['schema'])
                    for example in media.get('examples', {}).values():
                        if 'value' in example:
                            validator.validate(example['value'])
                    if 'example' in media:
                        validator.validate(media['example'])
                    # Localization may change prose, but never response types.
                    def structural(node):
                        if isinstance(node, dict):
                            return {k: structural(v) for k, v in node.items() if k not in {'description', 'summary'}}
                        return [structural(v) for v in node] if isinstance(node, list) else node
                    self.assertEqual(structural(media['schema']), structural(zh['paths'][path][method]['responses']['200']['content']['application/json']['schema']))
                    count += 1
        self.assertEqual(count, 59)

    def test_eight_business_shapes_are_in_final_documents_and_recompose(self):
        fresh, _ = compose(self.review['runtime_facts'], public_mirrors=self.mirrors, unreviewed_runtime=True)
        self.assertEqual(len(self.review['sources']), 8)
        self.assertTrue(all(row['nonempty_samples'] > 0 for row in self.review['sources']))
        for row in self.review['sources']:
            schema = self.media(row)['schema']
            self.assertEqual(schema, fresh['paths'][row['path']][row['method']]['responses']['200']['content']['application/json']['schema'])
            data = schema['oneOf'][0]['properties']['data']
            self.assertEqual(data['type'], 'object')
            if row['path'].endswith('/get-profile-id'):
                self.assertEqual(data['properties']['profile_id']['type'], 'string')
            else:
                self.assertEqual(data['properties']['results']['type'], 'array')
                self.assertTrue(data['properties']['results']['items']['properties'])

    def test_get_request_echo_matches_wire_types(self):
        for row in self.review['sources']:
            if row['method'] != 'get':
                continue
            media = self.media(row)
            value = copy.deepcopy(media['examples']['shape']['value'])
            validator = Draft202012Validator(media['schema'])
            validator.validate(value)
            value['requestParams']['body'] = {}
            with self.assertRaises(ValidationError):
                validator.validate(value)
            value['requestParams']['body'] = None
            name = next(iter(value['requestParams']['query']))
            value['requestParams']['query'][name] = {}
            with self.assertRaises(ValidationError):
                validator.validate(value)

    def test_comment_and_post_counters_have_their_actual_types(self):
        for slug, good, bad in [('get-post-comments', '2', 2), ('get-comment-replies', '2', 2), ('get-profile-posts', 2, '2')]:
            row = next(row for row in self.review['sources'] if row['path'].endswith('/' + slug))
            media = self.media(row)
            value = copy.deepcopy(media['examples']['shape']['value'])
            value['data']['results'] = [{'reactions_count': good}]
            validator = Draft202012Validator(media['schema'])
            validator.validate(value)
            value['data']['results'][0]['reactions_count'] = bad
            with self.assertRaises(ValidationError):
                validator.validate(value)

    def test_business_errors_do_not_inherit_success_data_types(self):
        for row in self.review['sources']:
            media = self.media(row)
            value = copy.deepcopy(media['examples']['shape']['value'])
            value.update(code=500, data='error detail')
            Draft202012Validator(media['schema']).validate(value)
            value['code'] = '500'
            with self.assertRaises(ValidationError):
                Draft202012Validator(media['schema']).validate(value)

    def test_runtime_request_prices_and_errors_stay_unchanged(self):
        baseline, _ = compose(self.review['runtime_facts'], public_mirrors={}, unreviewed_runtime=True)
        for row in self.review['sources']:
            operation = self.document['paths'][row['path']][row['method']]
            old = baseline['paths'][row['path']][row['method']]
            for key in ['requestBody', 'x-aisa-pricing', 'x-aisa-query-policy', 'x-aisa-status']:
                self.assertEqual(operation.get(key), old.get(key))
            self.assertEqual(operation['responses']['default'], old['responses']['default'])
            if row['method'] == 'get':
                self.assertNotIn('token', [p['name'] for p in operation['parameters']])

    def test_changed_transport_cannot_reuse_post_contract(self):
        path = '/apis/v1/facebook/get-post-comments'
        facts = copy.deepcopy(self.review['runtime_facts'])
        facts['paths'][path]['post']['x-aisa-response-upstream-origin-sha256'] = '0' * 64
        doc, _ = compose(facts, public_mirrors=self.mirrors, unreviewed_runtime=True)
        self.assertIn('x-aisa-response-pending', doc['paths'][path]['post'])


if __name__ == '__main__':
    unittest.main()
