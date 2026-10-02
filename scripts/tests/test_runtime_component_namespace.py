import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime_consolidate_openapi import merge_components, validate_reference_closure


class RuntimeComponentNamespaceTests(unittest.TestCase):
    def test_escaped_collision_preserves_old_and_new_targets(self):
        name = 'slash/name~value'
        old = {'type': 'integer'}
        new = {'type': 'object', 'properties': {'self': {'$ref': '#/components/schemas/slash~1name~0value'}}}
        result = {'components': {'schemas': {name: copy.deepcopy(old)}}}
        source = {'components': {'schemas': {name: copy.deepcopy(new)}},
                  'paths': {'/new': {'get': {'responses': {'200': {'content': {
                      'application/json': {'schema': {'$ref': '#/components/schemas/slash~1name~0value'}}}}}}}}}
        merge_components(result, source, 'provider.json')
        result['paths'] = source['paths']
        self.assertEqual(old, result['components']['schemas'][name])
        self.assertEqual('#/components/schemas/Provider_slash~1name~0value',
                         result['components']['schemas']['Provider_' + name]['properties']['self']['$ref'])
        self.assertEqual('#/components/schemas/Provider_slash~1name~0value',
                         result['paths']['/new']['get']['responses']['200']['content']['application/json']['schema']['$ref'])
        validate_reference_closure(result)

    def test_collision_changes_only_declarations_and_closes_discriminator_targets(self):
        literal = {'$ref': '#/components/schemas/Model', 'security': [{'Key': []}]}
        schema = {'type': 'object', 'discriminator': {'propertyName': 'kind', 'mapping': {
            'mapped': '#/components/schemas/Model', 'named': 'Model'}},
            'properties': {'child': {'$ref': '#/components/schemas/Model'},
                           'default': {'$ref': '#/components/schemas/Model'},
                           '$ref': {'type': 'string'}},
            **{name: copy.deepcopy(literal) for name in ('example', 'default', 'const')},
            'enum': [copy.deepcopy(literal)], 'examples': [copy.deepcopy(literal)]}
        source = {'openapi': '3.1.0', 'security': [{'Key': []}], 'paths': {}, 'components': {
            'schemas': {'Model': schema},
            'securitySchemes': {'Key': {'type': 'http', 'scheme': 'bearer'}},
            'links': {'Next': {'operationRef': '#/components/pathItems/Lookup/get',
                             'parameters': {'payload': copy.deepcopy(literal)},
                             'requestBody': copy.deepcopy(literal)}},
            'pathItems': {'Lookup': {'get': {'responses': {'204': {'description': 'No content'}}}}}}}
        result = {'components': {'schemas': {'Model': {'type': 'integer'}},
                                 'pathItems': {'Lookup': {'get': {'responses': {'200': {'description': 'Old'}}}}},
                                 'securitySchemes': {'Key': {'type': 'apiKey', 'in': 'header', 'name': 'key'}}}}
        merge_components(result, source, 'provider.json')
        result.update({k: v for k, v in source.items() if k != 'components'})
        actual = result['components']['schemas']['Provider_Model']
        for name in ('example', 'default', 'const', 'enum', 'examples'):
            self.assertEqual(schema[name], actual[name], name)
        self.assertEqual('#/components/schemas/Provider_Model', actual['properties']['child']['$ref'])
        self.assertEqual('#/components/schemas/Provider_Model', actual['properties']['default']['$ref'])
        self.assertEqual({'mapped': '#/components/schemas/Provider_Model',
                          'named': '#/components/schemas/Provider_Model'}, actual['discriminator']['mapping'])
        self.assertEqual([{'Provider_Key': []}], result['security'])
        self.assertEqual({'payload': literal}, result['components']['links']['Next']['parameters'])
        self.assertEqual(literal, result['components']['links']['Next']['requestBody'])
        self.assertEqual('#/components/pathItems/Provider_Lookup/get', result['components']['links']['Next']['operationRef'])
        validate_reference_closure(result)

    def test_literal_missing_refs_are_opaque_but_missing_declaration_is_rejected(self):
        document = {'components': {'schemas': {'Input': {'example': {'$ref': '#/missing'},
                                                'const': {'$ref': '#/missing'}}},
                                   'links': {'Next': {'parameters': {'body': {'$ref': '#/missing'}}}}}}
        validate_reference_closure(document)
        document['components']['schemas']['Input']['properties'] = {'child': {'$ref': '#/missing'}}
        with self.assertRaises(ValueError):
            validate_reference_closure(document)

    def test_discriminator_missing_mapping_is_rejected(self):
        document = {'components': {'schemas': {'Input': {'discriminator': {'mapping': {'missing': 'Missing'}}}}}}
        with self.assertRaises(ValueError):
            validate_reference_closure(document)


if __name__ == '__main__':
    unittest.main()
