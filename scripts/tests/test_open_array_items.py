"""Mixed arrays retain provider children only for explicit empty Runtime items."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import compose, merge_object
from test_runtime_contracts import facts, mirror, operation


class OpenArrayItemsTests(unittest.TestCase):
    def test_nested_provider_fields_and_refs_survive_without_mutating_inputs(self):
        runtime, source = facts('mixed'), mirror()
        item = {'type': 'object', 'properties': {
            'role': {'type': 'string', 'enum': ['user', 'assistant']},
            'content': {'type': 'string'},
            'name': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
        }, 'required': ['role', 'content']}
        source['components']['schemas']['Message'] = item
        source['components']['schemas']['Body'] = {'type': 'object', 'properties': {
            'options': {'type': 'object', 'properties': {
                'messages': {'type': 'array', 'items': {'$ref': '#/components/schemas/Message'},
                             'minItems': 5, 'maxItems': 100}}}}}
        declared_array = {'type': 'array', 'items': {}, 'minItems': 1, 'maxItems': 20}
        operation(runtime)['requestBody'] = {'required': True, 'content': {
            'application/json': {'schema': {'type': 'object', 'properties': {
                'options': {'type': 'object', 'properties': {'messages': declared_array},
                            'additionalProperties': True}}, 'additionalProperties': True}}}}
        before = copy.deepcopy((runtime, source))
        result, pending = compose(runtime, source)
        self.assertEqual(pending, [])
        actual = operation(result)['requestBody']['content']['application/json']['schema']['properties']['options']['properties']['messages']
        self.assertEqual({k: v for k, v in actual.items() if k != 'items'},
                         {k: v for k, v in declared_array.items() if k != 'items'})
        target = actual['items']
        if '$ref' in target:
            target = result['components']['schemas'][target['$ref'].split('/')[-1]]
        self.assertEqual(target, item)
        self.assertEqual((runtime, source), before)

    def test_runtime_item_constraints_remain_authoritative(self):
        provider = {'type': 'array', 'items': {'type': 'object', 'properties': {
            'role': {'type': 'string'}}}, 'maxItems': 100}
        for items in ({'type': 'string'}, {'enum': ['only']}, False, True):
            with self.subTest(items=items):
                declared = {'type': 'array', 'items': items, 'minItems': 1, 'maxItems': 2}
                result = merge_object({'properties': {'messages': provider}},
                                      {'properties': {'messages': declared}})
                self.assertEqual(result['properties']['messages'], declared)

    def test_provider_array_type_must_match_and_missing_items_is_unchanged(self):
        declared = {'type': 'array', 'items': {}, 'maxItems': 2}
        for provider in ({'type': 'object', 'items': {'type': 'string'}},
                         {'type': 'string'}, {'items': {'type': 'string'}}):
            with self.subTest(provider=provider):
                result = merge_object({'properties': {'values': provider}},
                                      {'properties': {'values': declared}})
                self.assertEqual(result['properties']['values'], declared)
        without_items = {'type': 'array', 'minItems': 1}
        result = merge_object({'properties': {'values': {'type': 'array', 'items': {'type': 'string'}}}},
                              {'properties': {'values': without_items}})
        self.assertEqual(result['properties']['values'], without_items)


if __name__ == '__main__':
    unittest.main()
