"""Independent W0 public-contract oracle through the actual Docs composer.

Expected graphs are hand-reviewed fixed files, never produced by composer or
reference resolver helpers. Synthetic data is repo-local and offline.
"""
import copy
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import compose_openapi as target

FIXTURES = pathlib.Path(__file__).parent / 'fixtures' / 'w1-acceptance'

def fixture(name):
    return json.loads((FIXTURES / name).read_text())

def pointer(document, path):
    value = document
    for token in path.lstrip('/').split('/'):
        part = token.replace('~1', '/').replace('~0', '~')
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value

class PublicContextTests(unittest.TestCase):
    def facts(self):
        facts = fixture('public-contract-3.1.json')
        facts['info']['x-aisa-document'] = {'facts_hash': 'sha256:synthetic-public-facts'}
        for item in facts['paths'].values():
            for method, operation in item.items():
                if method in target.METHODS:
                    operation.update({'x-aisa-validation': 'runtime', 'x-aisa-status': 'enabled'})
        return facts

    def test_effective_context_against_independent_oracle(self):
        facts = self.facts()
        composed, pending = target.compose(facts)
        self.assertEqual(pending, [])
        expected = fixture('public-contract-3.1.expected.json')['consumer_expectations'][0]['expected']
        actual = composed['paths']['/widgets/{id}']['get']
        for key in ('operationId', 'parameters', 'servers', 'security', 'responses'):
            with self.subTest(key=key):
                self.assertEqual(actual.get(key, composed.get(key)) if key in ('servers', 'security') else actual[key], expected[key])
        self.assertEqual(composed['paths']['/widgets/{id}']['parameters'], facts['paths']['/widgets/{id}']['parameters'])
        self.assertEqual(composed['paths']['/widgets']['post']['servers'], [{'url': 'https://public.example.invalid/upload', 'description': 'Public operation route'}])
        self.assertEqual(composed['paths']['/widgets']['servers'], [{'url': 'https://public.example.invalid/path', 'description': 'Public path route'}])
        self.assertEqual(composed['paths']['/widgets/{id}']['delete']['security'], [])
        self.assertEqual(composed['webhooks'], facts['webhooks'])
        self.assertEqual(composed['paths']['/widgets']['post']['callbacks'], facts['paths']['/widgets']['post']['callbacks'])
        self.assertEqual(facts, self.facts(), 'composer mutates authoritative source')

    def test_runtime_path_item_reference_keeps_public_context(self):
        facts = self.facts()
        original = facts['paths']['/widgets/{id}']
        original['summary'] = 'Public path family'
        facts['components']['pathItems'] = {'WidgetPath': copy.deepcopy(original)}
        facts['paths']['/widgets/{id}'] = {'$ref': '#/components/pathItems/WidgetPath'}
        composed, pending = target.compose(facts)
        self.assertEqual(pending, [])
        self.assertEqual(composed['paths']['/widgets/{id}']['summary'], 'Public path family')
        self.assertEqual(composed['paths']['/widgets/{id}']['get']['parameters'], fixture('public-contract-3.1.expected.json')['consumer_expectations'][0]['expected']['parameters'])

    def test_public_parameter_boolean_schema_is_preserved(self):
        for schema in (True, False):
            parameter = {'name': 'anything', 'in': 'query', 'schema': schema}
            self.assertEqual(target.parameter_wire_default(parameter), parameter)

    def test_parameter_reference_dialect_does_not_override_wire_name(self):
        for version in ('3.0.3', '3.1.0'):
            document = {'openapi': version, 'components': {'parameters': {'Q': {
                'name': 'q', 'in': 'query', 'schema': {'type': 'string'}, 'description': 'original'}}}}
            item = {'parameters': [{'$ref': '#/components/parameters/Q', 'name': 'ignored', 'description': 'override'}]}
            result = target.effective_parameters(item, {}, document)[0]
            self.assertEqual(result['name'], 'q')
            self.assertEqual(result['description'], 'original' if version.startswith('3.0') else 'override')

    def test_link_literals_and_dependent_schema_names_are_not_refs_or_annotations(self):
        document = {'openapi': '3.1.0', 'components': {'schemas': {
            'Q': {'dependentSchemas': {'default': {'$ref': '#/components/schemas/R'}}},
            'R': {'type': 'string'}}, 'links': {'Next': {'operationId': 'next',
                'parameters': {'q': {'$ref': 'literal'}}, 'requestBody': {'$ref': 'literal'}}}}}
        fragment = {'schema': {'$ref': '#/components/schemas/Q'}, 'links': {'Next': {'$ref': '#/components/links/Next'}}}
        components = target.referenced_components(fragment, document)
        self.assertIn('R', components['schemas'])
        result = target.resolve(fragment, document, preserve_recursive=True)
        self.assertEqual(result['links']['Next']['parameters']['q'], {'$ref': 'literal'})
        self.assertEqual(result['links']['Next']['requestBody'], {'$ref': 'literal'})

    def test_discriminator_mapping_closure_and_dynamic_scope_fail_closed(self):
        document = {'openapi': '3.1.0', 'components': {'schemas': {'Root': {
            'discriminator': {'propertyName': 'kind', 'mapping': {'a': 'Target', 'b': '#/components/schemas/Target'}}},
            'Target': {'type': 'object', 'properties': {'kind': {'const': 'a'}}}}}}
        output = {}
        fragment = target.resolve_fragment({'schema': {'$ref': '#/components/schemas/Root'}}, document, output, 'source.json', preserve_refs=True)
        root_ref = fragment['schema']['$ref']
        root = target.pointer_target(output, root_ref)
        for ref in root['discriminator']['mapping'].values():
            self.assertEqual(target.pointer_target(output, ref), document['components']['schemas']['Target'])
        with self.assertRaisesRegex(ValueError, 'dynamic reference scope'):
            target.referenced_components({'schema': {'$dynamicRef': '#node'}}, document)

    def test_upstream_parameter_override_does_not_duplicate_selector(self):
        source = {'openapi': '3.1.0', 'servers': [{'url': 'https://private.example.invalid/root'}],
                  'components': {'parameters': {'Engine': {'in': 'query', 'name': 'engine', 'schema': {'enum': ['old']}}}},
                  'paths': {'/resource': {'parameters': [{'$ref': '#/components/parameters/Engine'}, {'in': 'header', 'name': 'engine', 'schema': {'type': 'string'}}],
                            'get': {'parameters': [{'in': 'query', 'name': 'engine', 'schema': {'enum': ['selected']}}], 'responses': {'400': {'description': 'Private error'}}, 'security': [{'Private': []}]}}}}
        selected = target.select_upstream_operations([source], '/root/resource', {'in': 'query', 'name': 'engine', 'value': 'selected', 'mode': 'fixed'})
        self.assertIn('get', selected)
        parameters = selected['get'][1]['parameters']
        self.assertEqual(len(parameters), 2)
        self.assertEqual(parameters[0]['schema'], {'enum': ['selected']})
        self.assertEqual(parameters[1]['in'], 'header')

    def test_independent_oas30_conversion_oracle(self):
        source = fixture('public-contract-3.0.json')
        expected = fixture('public-contract-3.0.expected.json')
        for case in expected['consumer_expectations']:
            with self.subTest(case=case['id']):
                actual = target.schema_30_to_31(pointer(source, case['source_ref']['pointer']))
                self.assertEqual(actual, case['expected'])
                from jsonschema import Draft202012Validator
                validator = Draft202012Validator(actual)
                for example in case.get('schema_examples', []):
                    self.assertEqual(validator.is_valid(example['instance']), example['valid'])

    def test_namespace_pointer_tails_and_escaped_component_names(self):
        source = fixture('public-contract-3.1.json')
        value = {'schema': {'$ref': '#/components/schemas/EscapedDefinitions/$defs/a~1b~0c'},
                 'example': {'$ref': 'literal example data'},
                 'examples': {'named': {'value': {'$ref': 'literal named data'}}}}
        output = {}
        resolved = target.resolve_fragment(value, source, output, 'w0.json', preserve_refs=True)
        self.assertEqual(resolved['schema']['$ref'], '#/components/schemas/W0_EscapedDefinitions/$defs/a~1b~0c')
        self.assertEqual(resolved['example'], value['example'])
        self.assertEqual(resolved['examples'], value['examples'])
        self.assertEqual(pointer(output, resolved['schema']['$ref'][1:]), {'type': 'string', 'pattern': '^escaped$'})
        source['components']['schemas']['a/b~c'] = {'type': 'boolean'}
        nested = target.resolve_fragment({'schema': {'$ref': '#/components/schemas/a~1b~0c'}}, source, output, 'w0.json', preserve_refs=True)
        self.assertEqual(nested['schema']['$ref'], '#/components/schemas/W0_a~1b~0c')
        self.assertEqual(output['components']['schemas']['W0_a/b~c'], {'type': 'boolean'})

    def test_bad_pointer_tail_fails_explicitly(self):
        source = fixture('public-contract-3.1.json')
        with self.assertRaises((ValueError, KeyError)):
            target.resolve_fragment({'schema': {'$ref': '#/components/schemas/EscapedDefinitions/$defs/missing'}}, source, {}, 'w0.json', preserve_refs=True)

if __name__ == '__main__':
    unittest.main()
