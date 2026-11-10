"""Replay reviewed social response sources against captured immutable Runtime facts."""
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

REVIEW = ROOT / 'docs/current-source-review-20261110/facebook-tiktok-response-review.json'


class SocialFetchResponseSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.review = json.loads(REVIEW.read_text())
        cls.sources = {row['file']: json.loads((ROOT / row['file']).read_text())
                       for row in cls.review['sources']}
        reviewed = {(row['path'], row['method']) for row in cls.review['sources']}
        cls.mirrors = {key: value for key, value in public_mirror_index(ROOT).items() if key in reviewed}

    def test_exact_reviewed_operations_keep_original_provider_declarations(self):
        self.assertEqual(len(self.sources), 51)
        self.assertEqual(len(self.review['unresolved']), 8)
        for row in self.review['sources']:
            with self.subTest(path=row['path']):
                doc = self.sources[row['file']]
                operation = doc['paths'][row['path']][row['method']]
                self.assertEqual(set(operation), {'responses'})
                self.assertEqual(digest(operation['responses']), row['upstream_success_responses_sha256'])
                self.assertEqual(digest({'operation': operation, 'components': doc.get('components', {})}),
                                 row['source_content_hash'])
                self.assertTrue(doc['info']['x-aisa-source']['response_only'])
                self.assertEqual(set(operation['responses']), {'200'})

    def test_actual_composition_changes_only_reviewed_success_responses(self):
        example_count = 0
        for catalog, facts in self.review['runtime_facts'].items():
            before, before_pending = compose(facts, public_mirrors={}, unreviewed_runtime=True)
            after, pending = compose(facts, public_mirrors=self.mirrors, unreviewed_runtime=True)
            self.assertEqual(pending, before_pending)
            expected = {(row['path'], row['method']) for row in self.review['sources'] if row['catalog'] == catalog}
            changed = set()
            for path, item in after['paths'].items():
                for method, operation in item.items():
                    original = before['paths'][path][method]
                    with self.subTest(path=path, method=method):
                        if (path, method) not in expected:
                            self.assertEqual(operation, original)
                            continue
                        changed.add((path, method))
                        self.assertNotIn('x-aisa-response-pending', operation)
                        self.assertNotIn('x-aisa-review', operation)
                        self.assertEqual(operation['responses']['default'], original['responses']['default'])
                        exclude = {'responses', 'x-aisa-response-source', 'x-aisa-review'}
                        self.assertEqual({k: v for k, v in operation.items() if k not in exclude},
                                         {k: v for k, v in original.items() if k not in exclude})
                        media = operation['responses']['200']['content']['application/json']
                        schema = media['schema']
                        self.assertEqual(set(schema['required']), {'data', 'meta'})
                        Draft202012Validator.check_schema(schema)
                        validator = Draft202012Validator(schema)
                        examples = list(media.get('examples', {}).values())
                        if 'example' in media:
                            examples.append({'value': media['example']})
                        for example in examples:
                            if 'value' in example:
                                validator.validate(example['value'])
                                example_count += 1
            self.assertEqual(changed, expected)
        self.assertGreater(example_count, 100)

    def test_featured_responses_preserve_pagination_and_nullable_fields(self):
        for catalog, path, collection in [
                ('facebook', '/apis/v1/facebook/events', 'events'),
                ('tiktok', '/apis/v1/tiktok/collections/videos', 'videos')]:
            doc, _ = compose(self.review['runtime_facts'][catalog], public_mirrors=self.mirrors,
                             unreviewed_runtime=True)
            media = doc['paths'][path]['get']['responses']['200']['content']['application/json']
            payload = media['schema']['properties']['data']
            self.assertEqual(payload['properties'][collection]['type'], 'array')
            self.assertIn('id', payload['properties'][collection]['items']['required'])
            page = payload['properties']['page']
            self.assertEqual(set(page['required']), {'hasMore', 'nextCursor'})
            Draft202012Validator(page).validate({'hasMore': False, 'nextCursor': None})
            with self.assertRaises(ValidationError):
                Draft202012Validator(page).validate({'hasMore': 'false', 'nextCursor': None})
            self.assertIn('empty', media['examples'])
        self.assertNotIn('lookupStatus', payload['properties'])

    def test_changed_transport_cannot_reuse_the_reviewed_response(self):
        path = '/apis/v1/facebook/events'
        for key in ['x-aisa-response-upstream-path-sha256', 'x-aisa-response-upstream-origin-sha256']:
            facts = copy.deepcopy(self.review['runtime_facts']['facebook'])
            facts['paths'][path]['get'][key] = '0' * 64
            doc, _ = compose(facts, public_mirrors=self.mirrors, unreviewed_runtime=True)
            operation = doc['paths'][path]['get']
            self.assertIn('x-aisa-response-pending', operation)
            self.assertNotIn('content', operation['responses']['200'])


if __name__ == '__main__':
    unittest.main()
