import copy
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mintlify_response_schema import normalize_response_refs


def operation(branches):
    return {'responses': {'200': {'content': {'application/json': {'schema': {'allOf': branches}}}}}}


class MintlifyResponseTests(unittest.TestCase):
    ref = '#/components/schemas/Payload'

    def test_closed_and_conflicting_intersections_retain_validation_results(self):
        for closed in (True, False):
            fields = {'value': {'type': 'integer'}}
            component = {'type': 'object', 'properties': fields, 'additionalProperties': not closed}
            for overlay in ({'page': {'type': 'integer'}}, {'value': {'type': 'string'}}):
                branches = [{'$ref': self.ref, 'properties': {}}, {'type': 'object', 'properties': overlay}]
                op = operation(branches)
                shape = {'allOf': branches, 'components': {'schemas': {'Payload': component}}}
                before = copy.deepcopy(shape)
                self.assertTrue(normalize_response_refs(op))
                self.assertEqual(branches, [{'$ref': self.ref}, before['allOf'][1]])
                self.assertFalse(normalize_response_refs(op))
                for value in ({}, {'value': 2}, {'value': '2'}, {'page': 1}, {'value': 2, 'page': 1}):
                    with self.subTest(closed=closed, overlay=overlay, value=value):
                        self.assertEqual(Draft202012Validator(before).is_valid(value),
                                         Draft202012Validator(shape).is_valid(value))

    def test_other_constraints_and_data_are_preserved(self):
        branches = [{'$ref': self.ref}, {'$ref': self.ref, 'properties': {'value': False}},
                    {'$ref': self.ref, 'properties': {}, 'additionalProperties': False},
                    {'$ref': 'https://example.org/schema', 'properties': {}}, False]
        op = operation(branches)
        op['responses']['200']['content']['application/json']['example'] = {'allOf': [{'$ref': self.ref, 'properties': {}}]}
        before = copy.deepcopy(op)
        self.assertFalse(normalize_response_refs(op))
        self.assertEqual(op, before)
