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


class ApolloObjectBodyTests(unittest.TestCase):
    def test_exact_fourteen_changes_preserve_source_history_and_clocks(self):
        review = json.loads((ROOT / 'docs/current-source-review-20261017/apollo-object-bodies-review.json').read_text())
        doc = json.loads((ROOT / review['source_file']).read_text())
        source = doc['info'].pop('x-aisa-source')
        for key in ('kind', 'url', 'fetched_at', 'owner', 'refresh_policy', 'review_period_days', 'policy_revision'):
            self.assertEqual(source[key], review['prior_source'][key])
        self.assertEqual(len({e['operation_id'] for e in review['edits']}), 14)
        undo_object_body_amendment(self, ROOT, doc, source)

    def test_array_and_object_inputs_survive_normal_composition(self):
        cases = [
            ('/apollo/accounts/bulk_create', {'accounts': [{'name': 'Example', 'domain': 'example.com'}]}, {'accounts': 'wrong'}),
            ('/apollo/contacts/bulk_create', {'contacts': [{'first_name': 'Example', 'last_name': 'Person'}]}, {'contacts': 'wrong'}),
            ('/apollo/accounts/search', {'account_stage_ids': ['stage_fixture']}, {'account_stage_ids': 'wrong'}),
            ('/apollo/contacts/search', {'contact_stage_ids': ['stage_fixture']}, {'contact_stage_ids': 'wrong'}),
        ]
        for path, valid, invalid in cases:
            with self.subTest(path=path):
                runtime = facts('provider', 'post')
                op = copy.deepcopy(operation(runtime))
                op.update(operationId='post_' + path.strip('/').replace('/', '_'), parameters=[],
                          **{'x-aisa-upstream-path': path.replace('/apollo', '/api/v1', 1),
                             'x-aisa-query-policy': {'request_wins': True}})
                runtime['paths'] = {'/apis/v1' + path: {'post': op}}
                doc, pending = compose(runtime, public_mirrors=public_mirror_index(ROOT))
                self.assertFalse(pending)
                schema = doc['paths']['/apis/v1' + path]['post']['requestBody']['content']['application/json']['schema']
                validator = Draft7Validator(schema)
                validator.validate(valid)
                self.assertFalse(validator.is_valid(invalid))


if __name__ == '__main__':
    unittest.main()
