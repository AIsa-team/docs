import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft7Validator
from compose_openapi import compose
from runtime_registry import public_mirror_index
from test_runtime_contracts import facts, operation
from apollo_source_history import undo_query_array_amendment

ROOT = Path(__file__).resolve().parents[2]


class ApolloQueryArrayTests(unittest.TestCase):
    def test_three_exact_id_array_edits_and_source_history(self):
        doc = json.loads((ROOT / 'openapi/upstream/apollo.json').read_text())
        source = doc['info'].pop('x-aisa-source')
        review = json.loads((ROOT / 'docs/current-source-review-20261017/apollo-query-arrays-review.json').read_text())
        self.assertEqual(len(review['edits']), 3)
        undo_query_array_amendment(self, ROOT, doc, source)
        for key in ('kind', 'url', 'fetched_at', 'owner', 'refresh_policy', 'review_period_days', 'policy_revision'):
            self.assertEqual(source[key], review['prior_source'][key])

    def test_normal_composer_keeps_required_array_query_location(self):
        review = json.loads((ROOT / 'docs/current-source-review-20261017/apollo-query-arrays-review.json').read_text())
        for edit in review['edits']:
            path = edit['pointer'][1]
            with self.subTest(path=path):
                runtime = facts('provider', 'post')
                op = copy.deepcopy(operation(runtime))
                op.update(operationId=edit['operation_id'], parameters=[],
                          **{'x-aisa-upstream-path': path.replace('/apollo', '/api/v1', 1),
                             'x-aisa-query-policy': {'request_wins': True}})
                runtime['paths'] = {'/apis/v1' + path: {'post': op}}
                document, pending = compose(runtime, public_mirrors=public_mirror_index(ROOT))
                self.assertFalse(pending)
                parameters = document['paths']['/apis/v1' + path]['post']['parameters']
                p = next(p for p in parameters if p['name'] == edit['parameter_name'])
                self.assertEqual(p['in'], 'query')
                self.assertTrue(p['required'])
                validator = Draft7Validator(p['schema'])
                validator.validate(['id_one', 'id_two'])
                self.assertFalse(validator.is_valid('one_comma_separated_string'))


if __name__ == '__main__':
    unittest.main()
