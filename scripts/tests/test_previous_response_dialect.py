import copy
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator
from openapi_spec_validator import validate

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import compose, resolve
from runtime_registry import previous_for_facts
from test_runtime_contracts import facts, operation


class PreviousResponseDialectTests(unittest.TestCase):
    def test_openapi30_inline_success_fallback_preserves_nullable_and_bounds(self):
        runtime, old = facts('runtime'), facts('runtime')
        old['openapi'] = '3.0.3'
        operation(runtime)['responses']['200']['headers'] = {
            'X-Request-ID': {'schema': {'type': 'string'}}}
        operation(old)['responses']['200'].update(
            headers={'Historical': {'schema': {'type': 'integer'}}},
            content={'application/json': {'schema': {
                'type': 'number', 'nullable': True, 'minimum': 2,
                'exclusiveMinimum': True}}})
        previous = previous_for_facts(runtime, {'provider': old}, 'provider')
        document, pending = compose(runtime, previous=previous)
        response = operation(document)['responses']['200']
        schema = response['content']['application/json']['schema']
        validator = Draft202012Validator(schema)
        self.assertTrue(validator.is_valid(None))
        self.assertTrue(validator.is_valid(3))
        self.assertFalse(validator.is_valid(2))
        self.assertNotIn('nullable', schema)
        self.assertFalse(pending)
        self.assertEqual(operation(document)['operationId'], operation(runtime)['operationId'])
        self.assertEqual(operation(document)['x-aisa-status'], operation(runtime)['x-aisa-status'])
        self.assertEqual(response['headers'], operation(runtime)['responses']['200']['headers'])
        self.assertEqual(previous['paths'][next(iter(old['paths']))]['post']['responses']['200']['headers'],
                         operation(old)['responses']['200']['headers'])
        validate(document)
        republished = previous_for_facts(runtime, {'provider': document}, 'provider')
        self.assertEqual(compose(runtime, previous=republished)[0], document)

    def test_openapi30_reachable_response_refs_convert_without_touching_unused_components(self):
        runtime, old = facts('runtime'), facts('runtime')
        old['openapi'] = '3.0.3'
        old['components'].setdefault('schemas', {})['Result'] = {'type': 'object', 'properties': {
            'value': {'type': 'string', 'nullable': True},
            'next': {'$ref': '#/components/schemas/Result'}}}
        unused = {'type': 'number', 'exclusiveMinimum': 7}
        old['components']['schemas']['Unused'] = copy.deepcopy(unused)
        old['components']['responses'] = {'Success': {
            'description': 'Success', 'content': {'application/json': {
                'schema': {'$ref': '#/components/schemas/Result'}}}}}
        operation(old)['responses']['200'] = {'$ref': '#/components/responses/Success'}
        previous = previous_for_facts(runtime, {'old_filename': old}, 'provider')
        self.assertEqual(previous['components']['schemas']['Unused'], unused)
        document, pending = compose(runtime, previous=previous)
        self.assertFalse(pending)
        schema = resolve(operation(document)['responses']['200']['content']['application/json']['schema'],
                         document, preserve_recursive=True)
        self.assertEqual(schema['properties']['value'], {'type': ['string', 'null']})
        validator = Draft202012Validator({'allOf': [schema], 'components': document['components']})
        self.assertTrue(validator.is_valid({'value': None, 'next': {'value': None}}))
        self.assertFalse(validator.is_valid({'value': None, 'next': {'value': 3}}))
        validate(document)
        self.assertEqual(document, compose(runtime, previous=previous)[0])
        for _ in range(3):
            republished = previous_for_facts(runtime, {'provider': document}, 'provider')
            repeated, pending = compose(runtime, previous=republished)
            self.assertFalse(pending)
            self.assertEqual(document, repeated)

    def test_openapi31_historical_schema_extensions_are_unchanged(self):
        runtime, old = facts('runtime'), facts('runtime')
        schema = {'type': 'string', 'nullable': True}
        operation(old)['responses']['200']['content'] = {'application/json': {'schema': schema}}
        previous = previous_for_facts(runtime, {'provider': old}, 'provider')
        document, pending = compose(runtime, previous=previous)
        self.assertFalse(pending)
        self.assertEqual(operation(document)['responses']['200']['content']['application/json']['schema'], schema)


if __name__ == '__main__':
    unittest.main()
