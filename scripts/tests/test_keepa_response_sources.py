"""Replay the published Keepa facts through the real response-source loader."""
import copy
import json
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from compose_openapi import compose
from runtime_registry import public_mirror_index
from source_governance import policy_errors


class KeepaResponseSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        review = json.loads((ROOT / 'docs/current-source-review-20261113/keepa-response-review.json').read_text())
        cls.facts = review['runtime_facts']
        cls.mirrors = {key: value for key, value in public_mirror_index(ROOT).items()
                       if key[0].startswith('/apis/v1/keepa/')}

    def test_published_operations_have_typed_responses_without_changing_requests(self):
        before, before_pending = compose(self.facts, public_mirrors={})
        after, pending = compose(self.facts, public_mirrors=self.mirrors)
        self.assertEqual(len(after['paths']), 13)
        self.assertEqual(pending, before_pending)
        for path, item in after['paths'].items():
            for method, operation in item.items():
                with self.subTest(path=path, method=method):
                    media = operation['responses']['200'].get('content', {}).get('application/json', {})
                    schema = media.get('schema', {})
                    self.assertEqual(schema.get('type'), 'object', 'Keepa response must not be an empty schema')
                    self.assertIn('tokensConsumed', schema['properties'])
                    self.assertGreater(len(schema['properties']), 6)
                    Draft202012Validator.check_schema(schema)
                    self.assertIn('x-aisa-response-source', operation)
                    original = before['paths'][path][method]
                    excluded = {'responses', 'x-aisa-response-source', 'x-aisa-response-pending'}
                    self.assertEqual({k: v for k, v in operation.items() if k not in excluded},
                                     {k: v for k, v in original.items() if k not in excluded})
                    self.assertEqual(operation['responses']['default'], original['responses']['default'])

    def test_all_sources_are_response_only_and_bound_to_runtime_transport(self):
        self.assertEqual(len(self.mirrors), 13)
        for (path, method), entry in self.mirrors.items():
            with self.subTest(path=path):
                self.assertTrue(entry['response_only'])
                candidates = entry['independent_response_candidates']
                self.assertEqual(len(candidates), 1)
                source = candidates[0]['source']
                self.assertEqual(policy_errors(source), [])
                operation = self.facts['paths'][path][method]
                for suffix in ('path', 'origin'):
                    self.assertEqual(source[f'upstream_{suffix}_sha256'],
                                     operation[f'x-aisa-response-upstream-{suffix}-sha256'])

    def test_changed_transport_or_transformed_response_does_not_reuse_schema(self):
        for field, value in [('x-aisa-response-upstream-path-sha256', '0' * 64),
                             ('x-aisa-response-upstream-origin-sha256', '0' * 64),
                             ('x-aisa-response-passthrough', False)]:
            facts = copy.deepcopy(self.facts)
            for item in facts['paths'].values():
                for operation in item.values():
                    operation[field] = value
                    if value is False:
                        operation.pop('x-aisa-response-upstream-path-sha256')
                        operation.pop('x-aisa-response-upstream-origin-sha256')
            after, _ = compose(facts, public_mirrors=self.mirrors)
            for path, item in after['paths'].items():
                for method, operation in item.items():
                    with self.subTest(field=field, path=path):
                        self.assertNotIn('x-aisa-response-source', operation)
                        self.assertFalse(operation['responses']['200'].get('content', {}).get('application/json', {}).get('schema'))


if __name__ == '__main__':
    unittest.main()
