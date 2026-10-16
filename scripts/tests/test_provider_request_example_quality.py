import copy
import json
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import schema_30_to_31, fragment_30_to_31
from import_brave_reference import normalize_parameter_examples, normalize_body_examples
from import_dataforseo_filters import normalize_filters, remove_duplicate_batch_examples, VALUE
from import_upstream import normalize_relayer_address_example
from import_duffel_flights_reference import omit_invalid_passenger_example

ROOT = Path(__file__).resolve().parents[2]


class ProviderRequestExampleQualityTests(unittest.TestCase):
    def test_brave_drops_only_invalid_placeholders_and_decodes_declared_wire_values(self):
        boolean = {'in': 'query', 'name': 'spellcheck',
                   'schema': {'type': 'boolean', 'examples': ['', True, False]},
                   'examples': {'empty': {'value': ''}, 'yes': {'value': 'true'}, 'no': {'value': False}}}
        normalize_parameter_examples(boolean, {})
        self.assertEqual(boolean['schema']['examples'], [True, False])
        self.assertEqual(boolean['examples'], {'yes': {'value': True}, 'no': {'value': False}})
        array = {'in': 'query', 'name': 'result_filter',
                 'schema': {'type': 'array', 'items': {'type': 'string'}, 'description': 'A comma delimited string.'},
                 'examples': {'empty': {'value': ''}, 'single': {'value': 'web'}, 'pair': {'value': 'web,videos'}}}
        normalize_parameter_examples(array, {})
        self.assertEqual(array['examples'], {'single': {'value': ['web']}, 'pair': {'value': ['web', 'videos']}})
        self.assertEqual((array['style'], array['explode']), ('form', False))
        nullable_array = {'in': 'query', 'name': 'result_filter', 'schema': {
            'anyOf': [{'type': 'array', 'items': {'type': 'string'}}, {'type': 'null'}],
            'description': 'A comma delimited string.', 'examples': [['web'], None]}}
        normalize_parameter_examples(nullable_array, {})
        self.assertFalse(nullable_array['explode'])
        self.assertEqual(nullable_array['schema']['examples'], [['web'], None])
        string = {'in': 'query', 'name': 'freshness', 'schema': {'type': 'string'},
                  'examples': {'blank': {'value': ''}, 'literal': {'value': 'false'}}}
        original = copy.deepcopy(string)
        normalize_parameter_examples(string, {})
        self.assertEqual(string, original)
        unknown = {'in': 'query', 'name': 'other', 'schema': {'type': 'integer'},
                   'examples': {'invalid': {'value': 'unknown'}}}
        normalize_parameter_examples(unknown, {})
        self.assertEqual(unknown['examples']['invalid']['value'], 'unknown')

    def test_brave_body_examples_follow_local_refs_and_bound_cycles(self):
        schemas = {'Body': {'type': 'object', 'properties': {
            'spellcheck': {'type': 'boolean', 'examples': ['', False]},
            'child': {'$ref': '#/components/schemas/Body'}}}}
        normalize_body_examples({'$ref': '#/components/schemas/Body'}, schemas)
        self.assertEqual(schemas['Body']['properties']['spellcheck']['examples'], [False])
        self.assertEqual(schemas['Body']['properties']['child'], {'$ref': '#/components/schemas/Body'})

    def test_dataforseo_corrects_representation_without_erasing_other_constraints(self):
        original = {'openapi': '3.0.1', 'components': {'schemas': {
            'ExampleRequestInfo': {'type': 'object', 'required': ['target'], 'properties': {
                'target': {'type': 'string', 'minLength': 1},
                'filters': {'type': 'array', 'nullable': True, 'maxItems': 7,
                            'items': {'type': 'object', 'nullable': True}, 'description': 'Provider-specific operators.'},
                'relevant_pages_filters': {'type': 'array', 'items': {'type': 'string'}},
                'unrelated': {'type': 'array', 'items': {'type': 'object', 'nullable': True}},
            }}, 'ResultInfo': {'properties': {'filters': {'type': 'array', 'items': {'type': 'string'}}}},
        }}}
        result, changed = normalize_filters(original)
        self.assertEqual(set(changed), {('ExampleRequestInfo', 'filters'), ('ExampleRequestInfo', 'relevant_pages_filters')})
        self.assertEqual(result['components']['schemas']['ResultInfo'], original['components']['schemas']['ResultInfo'])
        for name, field in changed:
            before = original['components']['schemas'][name]['properties'][field]
            after = result['components']['schemas'][name]['properties'][field]
            self.assertEqual({k: v for k, v in after.items() if k != 'items'}, {k: v for k, v in before.items() if k != 'items'})
        schemas = {name: schema_30_to_31(value) for name, value in result['components']['schemas'].items()}
        root = {'$schema': 'https://json-schema.org/draft/2020-12/schema', 'components': {'schemas': schemas}}
        registry = Registry().with_resource('urn:filter-test', Resource.from_contents(root))
        validator = Draft202012Validator({'$ref': 'urn:filter-test#/components/schemas/ExampleRequestInfo/properties/filters'}, registry=registry)
        for value in [['rank', '>', 10], [['rank', 'in', [1, 2]], 'and', ['active', '=', True]], [None, {'value': [False, 0]}]]:
            self.assertTrue(validator.is_valid(value), value)
        self.assertFalse(validator.is_valid('rank > 10'))
        self.assertFalse(validator.is_valid(list(range(8))))  # Original maxItems retained.
        self.assertEqual(normalize_filters(result), (result, []))
        # Operator names/tuple arity are deliberately not guessed from generic JSON.
        self.assertTrue(validator.is_valid([['provider-specific-expression']]))

    def test_all_dataforseo_published_source_body_examples_match_their_declared_types(self):
        document = json.loads((ROOT / 'openapi/upstream/dataforseo-official.json').read_text())
        schemas = {name: schema_30_to_31(value) for name, value in document['components']['schemas'].items()}
        count = 0
        for path, item in document['paths'].items():
            for method, operation in item.items():
                if method not in {'get', 'post', 'put', 'patch', 'delete', 'options', 'head', 'trace'}:
                    continue
                for media in operation.get('requestBody', {}).get('content', {}).values():
                    schema = media.get('schema', {})
                    if 'example' not in schema:
                        continue
                    check = {**fragment_30_to_31({'schema': schema})['schema'], 'components': {'schemas': schemas}}
                    with self.subTest(path=path, method=method):
                        Draft202012Validator(check, registry=Registry()).validate(schema['example'])
                    count += 1
        self.assertGreater(count, 0)

    def test_relayer_omits_ellipsis_without_removing_address_constraints(self):
        parameter = {'in': 'header', 'name': 'RELAYER_API_KEY_ADDRESS',
                     'schema': {'$ref': '#/components/schemas/Address'}, 'example': '0xabc...'}
        document = {'paths': {'/relayer/api/keys': {'get': {'parameters': [parameter]}}},
                    'components': {'schemas': {'Address': {'type': 'string', 'pattern': '^0x[a-fA-F0-9]{40}$'}}}}
        original = copy.deepcopy(document)
        normalize_relayer_address_example(document)
        original['paths']['/relayer/api/keys']['get']['parameters'][0].pop('example')
        self.assertEqual(document, original)

    def test_wrong_scope_component_batch_examples_remain_on_the_parent(self):
        batch = [{'filters': [['rank', '>', 1]]}, {'filters': [['rank', '<', 10]]}]
        document = {'components': {'schemas': {'TaskRequestInfo': {'type': 'object', 'example': copy.deepcopy(batch)}}},
                    'paths': {'/x': {'post': {'requestBody': {'content': {'application/json': {'schema': {
                        'type': 'array', 'items': {'oneOf': [{'$ref': '#/components/schemas/TaskRequestInfo'}]},
                        'example': copy.deepcopy(batch)}}}}}}}}
        self.assertEqual(remove_duplicate_batch_examples(document), ['TaskRequestInfo'])
        self.assertNotIn('example', document['components']['schemas']['TaskRequestInfo'])
        self.assertEqual(document['paths']['/x']['post']['requestBody']['content']['application/json']['schema']['example'], batch)

    def test_duffel_removes_only_the_oneof_conflicting_sample(self):
        source = json.loads((ROOT / 'openapi/upstream/duffel-flights-official.json').read_text())
        data = source['paths']['/air/offer_requests']['post']['requestBody']['content']['application/json']['schema']['properties']['data']
        original = copy.deepcopy(data)
        data['properties']['passengers']['example'] = [{'age': 5, 'fare_type': 'contract_bulk_child'}]
        self.assertTrue(omit_invalid_passenger_example(data))
        self.assertEqual(data, original)


if __name__ == '__main__':
    unittest.main()
