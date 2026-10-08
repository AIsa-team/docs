import copy
import json
from pathlib import Path
from catalog_fixture import catalog_root
import sys
import tempfile
import unittest

from jsonschema import Draft202012Validator
from openapi_spec_validator import validate

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import compose, resolve, resolve_fragment
from runtime_registry import public_mirror_index
from test_runtime_contracts import facts, mirror, operation


class SchemaResponseContractsTests(unittest.TestCase):
    def test_parallel_sdk_override_is_not_a_public_contract_dependency(self):
        source = json.loads((catalog_root() / 'openapi/upstream/parallel.ai.json').read_text())
        parameters = [parameter for item in source['paths'].values() for method, op in item.items()
                      if method in ('get', 'post') for parameter in op.get('parameters', [])
                      if 'x-stainless-override-schema' in parameter.get('schema', {})]
        self.assertTrue(parameters, 'exercise the checked-in official Parallel declaration')
        original = copy.deepcopy(parameters)
        output = {}
        selected = resolve_fragment({'parameters': parameters}, source, output, 'parallel-sdk.json')
        self.assertNotIn('x-stainless-override-schema', json.dumps(selected))
        self.assertNotIn('ParallelBeta', json.dumps(output))
        for before, after in zip(parameters, selected['parameters']):
            expected = copy.deepcopy(before)
            expected['schema'].pop('x-stainless-override-schema')
            self.assertEqual(after, expected, 'public header wire semantics must remain intact')
        self.assertEqual(parameters, original, 'do not alter the authoritative upstream mirror')

    def test_sdk_extension_filter_does_not_rewrite_literal_json_or_aisa_metadata(self):
        upstream = mirror()
        literal = {'x-stainless-override-schema': {'$ref': '#/components/schemas/Literal'},
                   '$ref': 'https://example.test/literal'}
        upstream['components']['schemas']['Body']['example'] = literal
        upstream['components']['schemas']['Body']['x-aisa-notes'] = ['Keep this metadata']
        upstream['components']['schemas']['Body']['x-stainless-override-schema'] = {
            '$ref': '#/components/schemas/NotAWireDependency'}
        document, pending = compose(facts('provider'), upstream)
        self.assertFalse(pending)
        schema = operation(document)['requestBody']['content']['application/json']['schema']
        self.assertEqual(schema['example'], literal)
        self.assertEqual(schema['x-aisa-notes'], ['Keep this metadata'])
        self.assertNotIn('x-stainless-override-schema', schema)

    def test_openapi30_nullable_bounds_refs_and_literal_examples(self):
        upstream = mirror()
        upstream['openapi'] = '3.0.3'
        upstream['components']['schemas']['Body'] = {
            'type': 'object', 'required': ['value'], 'properties': {
                'value': {'type': 'string', 'nullable': True},
                'score': {'type': 'number', 'minimum': 2, 'exclusiveMinimum': True,
                          'maximum': 5, 'exclusiveMaximum': False},
                'child': {'$ref': '#/components/schemas/Child'},
                'nullable': {'type': 'boolean'},
            },
            'example': {'value': None, 'nullable': True, 'schema': {'nullable': True}},
        }
        upstream['components']['schemas']['Child'] = {'type': 'string', 'nullable': True}
        document, pending = compose(facts('provider'), upstream)
        self.assertFalse(pending)
        schema = operation(document)['requestBody']['content']['application/json']['schema']
        validator = Draft202012Validator(schema)
        for instance in ({'value': None}, {'value': 'ok', 'child': None, 'score': 3}):
            self.assertTrue(validator.is_valid(instance), instance)
        for instance in ({'value': 1}, {'value': 'ok', 'score': 2}, {'value': 'ok', 'score': 6}):
            self.assertFalse(validator.is_valid(instance), instance)
        self.assertEqual(schema['example'], upstream['components']['schemas']['Body']['example'])
        self.assertEqual(schema['properties']['nullable'], {'type': 'boolean'})
        self.assertEqual(schema['properties']['score']['exclusiveMinimum'], 2)
        self.assertNotIn('exclusiveMaximum', schema['properties']['score'])
        validate(document)
        self.assertEqual(compose(facts('provider'), upstream)[0], document)

    def test_31_nullable_extension_and_instance_data_are_not_reinterpreted(self):
        upstream = mirror()
        upstream['components']['schemas']['Body'] = {'type': 'object', 'properties': {
            'value': {'type': 'string', 'nullable': True}}, 'default': {'schema': {'nullable': True}}}
        document, pending = compose(facts('provider'), upstream)
        self.assertFalse(pending)
        schema = operation(document)['requestBody']['content']['application/json']['schema']
        self.assertEqual(schema, upstream['components']['schemas']['Body'])

    def test_30_ignored_reference_siblings_are_not_traversed(self):
        upstream = mirror()
        upstream['openapi'] = '3.0.3'
        upstream['components']['schemas']['Body'] = {'$ref': '#/components/schemas/Value',
            'not': {'$ref': 'https://example.test/ignored-schema'}}
        upstream['components']['schemas']['Value'] = {'type': 'string'}
        schema = operation(upstream)['requestBody']['content']['application/json']['schema']
        schema['allOf'] = [{'$ref': 'https://example.test/also-ignored'}]
        document, pending = compose(facts('provider'), upstream)
        self.assertFalse(pending)
        self.assertEqual(operation(document)['requestBody']['content']['application/json']['schema'], {'type': 'string'})

    def test_reference_shaped_json_instances_and_schema_property_names_survive(self):
        for version in ('3.0.3', '3.1.0'):
            with self.subTest(version=version):
                upstream = mirror()
                upstream['openapi'] = version
                literal = {'$ref': 'https://example.test/literal', 'nested': {'$ref': '#/components/schemas/Body'}}
                upstream['components']['schemas']['Body'] = {'type': 'object', 'properties': {
                    'default': {'$ref': '#/components/schemas/Value'},
                    'enum': {'$ref': '#/components/schemas/Value'}}, 'example': literal, 'default': literal}
                upstream['components']['schemas']['Value'] = {'type': 'string'}
                operation(upstream)['requestBody']['content']['application/json']['examples'] = {'sample': {'value': literal}}
                document, pending = compose(facts('provider'), upstream)
                self.assertFalse(pending)
                media = operation(document)['requestBody']['content']['application/json']
                self.assertEqual(media['schema']['example'], literal)
                self.assertEqual(media['schema']['default'], literal)
                self.assertEqual(media['examples']['sample']['value'], literal)
                self.assertEqual(media['schema']['properties']['default'], {'type': 'string'})
                self.assertEqual(media['schema']['properties']['enum'], {'type': 'string'})

    def test_explicit_passthrough_response_updates_and_new_operation_use_current_source(self):
        runtime, upstream = facts('provider'), mirror()
        operation(runtime)['x-aisa-passthrough'] = True
        operation(upstream)['responses'] = {'200': {'description': 'Current payload',
            'headers': {'Provider-Secret': {'schema': {'type': 'string'}}},
            'content': {'application/json': {'schema': {'type': 'integer'}, 'example': 8}}},
            '400': {'description': 'Provider error'}}
        previous = copy.deepcopy(runtime)
        operation(previous)['responses']['200']['content'] = {'application/json': {'schema': {'type': 'string'}}}
        operation(runtime)['responses']['200']['headers'] = {'X-Request-ID': {'schema': {'type': 'string'}}}
        operation(runtime)['responses']['default'] = {'description': 'Runtime error'}
        for history in (None, previous):
            with self.subTest(history=history is not None):
                document, pending = compose(runtime, upstream, previous=history)
                self.assertFalse(pending)
                op = operation(document)
                self.assertEqual(op['responses']['200']['content'], operation(upstream)['responses']['200']['content'])
                self.assertEqual(op['responses']['200']['headers'], operation(runtime)['responses']['200']['headers'])
                self.assertEqual(op['responses']['default'], {'description': 'Runtime error'})
                self.assertNotIn('400', op['responses'])
                self.assertEqual(op['x-aisa-response-source']['kind'], 'upstream_success_contract')
                self.assertFalse(document['info']['x-aisa-document']['response_pending'])
                self.assertEqual(compose(runtime, upstream, previous=document)[0], document)

    def test_upstream_response_cannot_override_runtime_payload_or_unknown_wrapper(self):
        runtime, upstream = facts('provider'), mirror()
        operation(upstream)['responses'] = {'200': {'content': {'application/json': {'schema': {'type': 'integer'}}}}}
        document, pending = compose(runtime, upstream)
        self.assertFalse(pending)
        self.assertNotIn('content', operation(document)['responses']['200'])
        self.assertTrue(operation(document)['x-aisa-response-pending'])
        self.assertTrue(document['info']['x-aisa-document']['response_pending'])
        operation(runtime)['x-aisa-passthrough'] = True
        operation(runtime)['responses']['200']['content'] = {'application/json': {'schema': {'type': 'object'}}}
        document, pending = compose(runtime, upstream)
        self.assertFalse(pending)
        self.assertEqual(operation(document)['responses']['200']['content'], operation(runtime)['responses']['200']['content'])
        self.assertNotIn('x-aisa-response-source', operation(document))
        operation(upstream)['responses']['200'] = {'$ref': 'https://example.test/unused-response'}
        document, pending = compose(runtime, upstream)
        self.assertFalse(pending)
        self.assertNotIn('x-aisa-response-pending', operation(document))

    def test_response_references_and_30_schema_semantics(self):
        runtime, upstream = facts('provider'), mirror()
        operation(runtime)['x-aisa-passthrough'] = True
        upstream['openapi'] = '3.0.3'
        upstream['components']['schemas']['Result'] = {'type': 'string', 'nullable': True}
        upstream['components']['responses'] = {'Success': {'description': 'OK', 'content': {
            'application/json': {'schema': {'$ref': '#/components/schemas/Result'}}}}}
        operation(upstream)['responses'] = {'200': {'$ref': '#/components/responses/Success'}}
        document, pending = compose(runtime, upstream)
        self.assertFalse(pending)
        schema = resolve(operation(document)['responses']['200']['content']['application/json']['schema'], document)
        self.assertTrue(Draft202012Validator(schema).is_valid(None))
        self.assertFalse(operation(document).get('x-aisa-response-pending'))

    def test_no_content_and_explicit_unconstrained_schema_are_declared_responses(self):
        for status, response in (('204', {'description': 'No Content'}),
                                 ('200', {'description': 'Any JSON', 'content': {'application/json': {'schema': {}}}})):
            with self.subTest(status=status):
                runtime, upstream = facts('provider'), mirror()
                operation(runtime)['x-aisa-passthrough'] = True
                operation(upstream)['responses'] = {status: response}
                document, pending = compose(runtime, upstream)
                self.assertFalse(pending)
                self.assertNotIn('x-aisa-response-pending', operation(document))
                self.assertEqual(set(operation(document)['responses']), {status})

    def test_fresh_recursive_response_does_not_import_unused_historical_components(self):
        runtime, upstream = facts('provider'), mirror()
        operation(runtime)['x-aisa-passthrough'] = True
        upstream['components']['schemas']['Result'] = {'type': 'object', 'properties': {
            'next': {'$ref': '#/components/schemas/Result'}}}
        operation(upstream)['responses'] = {'200': {'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Result'}}}}}
        first, pending = compose(runtime, upstream)
        self.assertFalse(pending)
        second, pending = compose(runtime, upstream, previous=first)
        self.assertFalse(pending)
        self.assertEqual(first, second)

    def test_missing_response_reference_is_reported_without_hiding_valid_request(self):
        runtime, upstream = facts('provider'), mirror()
        operation(runtime)['x-aisa-passthrough'] = True
        operation(upstream)['responses'] = {'200': {'$ref': '#/components/responses/Missing'}}
        document, pending = compose(runtime, upstream)
        self.assertFalse(pending)
        self.assertIn('requestBody', operation(document))
        self.assertIn('Missing', operation(document)['x-aisa-response-pending']['reason'])

    def test_public_mirror_dialect_and_current_success_response(self):
        public = mirror()
        public['openapi'] = '3.0.3'
        public['servers'] = [{'url': 'https://api.aisa.one'}]
        public['info']['x-aisa-source'].update(kind='manual', path_space='public')
        public['components']['schemas']['Body']['properties']['email']['nullable'] = True
        source_op = operation(public)
        public['components']['schemas']['Result'] = {'type': 'string', 'nullable': True}
        source_op['responses'] = {'200': {
            'headers': {'Ignored-Header': {'$ref': 'https://example.test/ignored-header'}},
            'links': {'Ignored-Link': {'$ref': 'https://example.test/ignored-link'}},
            'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Result'}}}}}
        public['paths'] = {'/apis/v1/similarweb/test': {'post': source_op}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'openapi/upstream').mkdir(parents=True)
            (root / 'openapi/upstream/public.json').write_text(json.dumps(public))
            runtime = facts('provider')
            document, pending = compose(runtime, public_mirrors=public_mirror_index(root))
        self.assertFalse(pending)
        op = operation(document)
        self.assertTrue(Draft202012Validator(op['requestBody']['content']['application/json']['schema']).is_valid({'email': None}))
        self.assertTrue(Draft202012Validator(resolve(op['responses']['200']['content']['application/json']['schema'], document)).is_valid(None))
        self.assertEqual(op['x-aisa-response-source']['source']['kind'], 'manual')
