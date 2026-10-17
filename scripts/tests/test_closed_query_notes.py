"""A source's query documentation must not promise inputs Runtime rejects."""
import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import compose
from test_runtime_contracts import facts, mirror, operation


class ClosedQueryNotesTests(unittest.TestCase):
    def fixture(self):
        runtime, upstream = facts('mixed'), mirror()
        operation(runtime)['x-aisa-query-policy'] = {'request_wins': False, 'ignore_undeclared': False}
        operation(runtime)['x-aisa-constraints'] = {'notes': ['Existing restriction'], 'retained': True}
        operation(upstream)['parameters'].append(
            {'name': 'next_max_id', 'in': 'query', 'required': False, 'schema': {'type': 'string'}})
        return runtime, upstream

    def test_exact_filtered_query_names_explain_closed_contract_without_changing_fields(self):
        runtime, upstream = self.fixture()
        original = copy.deepcopy((runtime, upstream))
        document, pending = compose(runtime, upstream)
        self.assertEqual(pending, [])
        actual = operation(document)
        note = actual['x-aisa-constraints']['notes'][-1]
        self.assertEqual(note, 'AIsa query restriction: only declared query parameters are accepted: switch. '
                         'Upstream-only query parameters next_max_id are not accepted by this AIsa endpoint.')
        self.assertIn(note, actual['description'])
        self.assertTrue(actual['description'].startswith('Runtime description'))
        self.assertEqual(actual['x-aisa-constraints']['notes'][0], 'Existing restriction')
        self.assertTrue(actual['x-aisa-constraints']['retained'])
        self.assertEqual((runtime, upstream), original)
        # Compare with the same old composition rule, which had no policy note.
        old = copy.deepcopy(runtime)
        operation(old).pop('x-aisa-query-policy')
        expected = operation(compose(old, upstream)[0])
        for field in ('parameters', 'requestBody', 'responses', 'security', 'x-aisa-pricing'):
            self.assertEqual(actual.get(field), expected.get(field), field)
        self.assertNotIn('provider_token', note)

    def test_ignore_open_custom_and_runtime_validation_paths_are_unchanged(self):
        for policy, validation in [
            ({'request_wins': False, 'ignore_undeclared': True}, 'mixed'),
            ({'request_wins': True, 'ignore_undeclared': False}, 'mixed'),
            ({}, 'mixed'),
            ({'request_wins': False, 'ignore_undeclared': False}, 'runtime'),
        ]:
            with self.subTest(policy=policy, validation=validation):
                runtime, upstream = self.fixture()
                operation(runtime)['x-aisa-query-policy'] = policy
                operation(runtime)['x-aisa-validation'] = validation
                actual = operation(compose(runtime, upstream)[0])
                self.assertNotIn('AIsa query restriction:', actual['description'])
                self.assertNotIn('x-aisa-notes', actual)

    def test_no_removed_query_or_header_only_does_not_add_a_note(self):
        runtime, upstream = self.fixture()
        operation(upstream)['parameters'] = [
            {'name': 'switch', 'in': 'query', 'schema': {'type': 'string'}},
            {'name': 'next_max_id', 'in': 'header', 'schema': {'type': 'string'}},
        ]
        self.assertNotIn('AIsa query restriction:', operation(compose(runtime, upstream)[0])['description'])


if __name__ == '__main__':
    unittest.main()
