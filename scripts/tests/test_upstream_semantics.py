import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from upstream_semantics import compare_contracts, LocalSchemaComparison


def document():
    return {'openapi': '3.1.0', 'info': {'title': 'Fixture', 'version': '1'},
            'paths': {'/search': {'get': {'operationId': 'search',
                'responses': {'200': {'description': 'Success', 'content': {'application/json': {
                    'schema': {'type': 'object', 'properties': {'value': {'type': 'string'}}}}}}}}}}}


class SemanticTests(unittest.TestCase):
    def comparison(self, mutate):
        before = document()
        after = copy.deepcopy(before)
        mutate(after)
        return compare_contracts(before, after)

    def test_added_required_input_requires_review(self):
        report = self.comparison(lambda doc: doc['paths']['/search']['get'].update(parameters=[
            {'name': 'query', 'in': 'query', 'required': True, 'schema': {'type': 'string', 'minLength': 1}}]))
        self.assertEqual(report['status'], 'review_required')
        self.assertEqual(report['compatibility'], 'not_assessed')
        change = report['changed'][0]['changes'][0]
        self.assertEqual(change['field'], '/request/parameters')
        self.assertTrue(change['after'][0]['required'])

    def test_method_path_and_server_changes_visible(self):
        before = document()
        before['servers'] = [{'url': 'https://api.test/v1'}]
        after = copy.deepcopy(before)
        after['paths']['/new'] = {'post': after['paths'].pop('/search')['get']}
        report = compare_contracts(before, after)
        self.assertEqual(report['added'][0]['operation'], 'POST /new')
        self.assertEqual(report['removed'][0]['operation'], 'GET /search')
        after = copy.deepcopy(before)
        after['servers'][0]['url'] = 'https://api.test/v2'
        self.assertEqual(compare_contracts(before, after)['changed'][0]['changes'][0]['field'], '/binding/servers')

    def test_operation_server_overrides_path_and_root(self):
        before = document()
        before['servers'] = [{'url': 'https://api.test/v1'}]
        before['paths']['/search']['servers'] = [{'url': '/path'}]
        before['paths']['/search']['get']['servers'] = [{'url': '/operation'}]
        after = copy.deepcopy(before)
        after['servers'][0]['url'] = '/root-change'
        after['paths']['/search']['servers'][0]['url'] = '/path-change'
        self.assertEqual(compare_contracts(before, after)['status'], 'declarations_unchanged')

    def test_path_parameter_ref_with_operation_override(self):
        before = document()
        before['components'] = {'parameters': {'Query': {'name': 'query', 'in': 'query', 'schema': {'type': 'integer'}}}}
        before['paths']['/search']['parameters'] = [{'$ref': '#/components/parameters/Query'}]
        before['paths']['/search']['get']['parameters'] = [{'name': 'query', 'in': 'query', 'schema': {'type': 'string'}}]
        after = copy.deepcopy(before)
        after['components']['parameters']['Query']['schema']['type'] = 'boolean'
        self.assertEqual(compare_contracts(before, after)['status'], 'declarations_unchanged')
        after['paths']['/search']['get']['parameters'][0]['explode'] = False
        self.assertEqual(compare_contracts(before, after)['status'], 'review_required')

    def test_equivalent_explicit_parameter_defaults(self):
        before = document()
        before['paths']['/search']['get']['parameters'] = [{'name': 'query', 'in': 'query', 'schema': {'type': 'string'}}]
        after = copy.deepcopy(before)
        after['paths']['/search']['get']['parameters'][0].update(required=False, deprecated=False,
            allowEmptyValue=False, allowReserved=False, style='form', explode=True)
        self.assertEqual(compare_contracts(before, after)['status'], 'declarations_unchanged')

    def test_referenced_body_constraints_and_response_ref_changes(self):
        before = document()
        before['components'] = {'schemas': {'Body': {'type': 'object', 'properties': {'count': {'type': 'integer', 'minimum': 0}}}}}
        before['paths']['/search']['get']['requestBody'] = {'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Body'}}}}
        after = copy.deepcopy(before)
        after['components']['schemas']['Body']['properties']['count']['minimum'] = 1
        after['paths']['/search']['get']['requestBody']['required'] = True
        fields = {row['field'] for row in compare_contracts(before, after)['changed'][0]['changes']}
        self.assertIn('/request/body/required', fields)
        self.assertIn('/request/body/content/application~1json/schema/properties/count/minimum', fields)
        before['paths']['/search']['get']['responses']['200']['content']['application/json']['schema'] = {'$ref': '#/components/schemas/Body'}
        self.assertTrue(any(row['field'].startswith('/responses/') for row in compare_contracts(before, after)['changed'][0]['changes']))

    def test_root_security_changes_and_operation_override(self):
        before = document()
        before['security'] = [{'Key': []}]
        before['components'] = {'securitySchemes': {'Key': {'type': 'apiKey', 'in': 'header', 'name': 'X-Key'}}}
        after = copy.deepcopy(before)
        after['components']['securitySchemes']['Key']['name'] = 'X-New-Key'
        fields = {row['field'] for row in compare_contracts(before, after)['changed'][0]['changes']}
        self.assertIn('/authentication/schemes/Key/name', fields)
        before['paths']['/search']['get']['security'] = []
        after['paths']['/search']['get']['security'] = []
        self.assertEqual(compare_contracts(before, after)['status'], 'declarations_unchanged')

    def test_missing_scheme_is_uncertain(self):
        report = self.comparison(lambda doc: doc.update(security=[{'Missing': []}]))
        self.assertEqual(report['status'], 'uncertain')
        self.assertIn('missing_security_scheme', report['uncertain'][0]['after'])
        self.assertEqual(report['removed'], [])

    def test_prose_examples_and_unordered_constraints_ignored(self):
        before = document()
        schema = before['paths']['/search']['get']['responses']['200']['content']['application/json']['schema']
        schema.update(required=['value', 'other'], properties={'value': {'type': 'string', 'enum': ['a', 'b']}, 'other': {'type': 'string'}})
        after = copy.deepcopy(before)
        operation = after['paths']['/search']['get']
        operation.update(description='changed', summary='new', tags=['New'], externalDocs={'url': 'https://docs.test/new'})
        operation['responses']['200']['description'] = 'Better prose'
        target = operation['responses']['200']['content']['application/json']['schema']
        target['required'].reverse()
        target['properties']['value']['enum'].reverse()
        target['properties']['value']['examples'] = ['sample']
        self.assertEqual(compare_contracts(before, after)['status'], 'declarations_unchanged')

    def test_property_names_matching_annotation_names_are_contracts(self):
        before = document()
        schema = before['paths']['/search']['get']['responses']['200']['content']['application/json']['schema']
        schema['properties'] = {'description': {'type': 'string'}, 'example': {'type': 'string'}}
        after = copy.deepcopy(before)
        after['paths']['/search']['get']['responses']['200']['content']['application/json']['schema']['properties']['description']['type'] = 'integer'
        self.assertEqual(compare_contracts(before, after)['status'], 'review_required')

    def test_literal_object_values_not_cleaned_as_prose(self):
        before = document()
        schema = before['paths']['/search']['get']['responses']['200']['content']['application/json']['schema']
        schema['const'] = {'description': 'before'}
        schema['default'] = {'example': 'before'}
        schema['enum'] = [{'title': 'before'}]
        for key, field in [('const', 'description'), ('default', 'example'), ('enum', 'title')]:
            with self.subTest(key=key):
                after = copy.deepcopy(before)
                target = after['paths']['/search']['get']['responses']['200']['content']['application/json']['schema'][key]
                if key == 'enum': target = target[0]
                target[field] = 'after'
                self.assertEqual(compare_contracts(before, after)['status'], 'review_required')

    def test_boolean_to_number_instances_are_changes_including_recursive_targets(self):
        for key in ('enum', 'default', 'const'):
            for recursive in (False, True):
                before = self.recursive_document() if recursive else document()
                schema = (before['components']['schemas']['Node']['properties']['value'] if recursive
                          else before['paths']['/search']['get']['responses']['200']['content']['application/json']['schema'])
                schema[key] = [True, False] if key == 'enum' else {'literal': [True, False]}
                after = copy.deepcopy(before)
                target = (after['components']['schemas']['Node']['properties']['value'] if recursive
                          else after['paths']['/search']['get']['responses']['200']['content']['application/json']['schema'])
                target[key] = [1, 0] if key == 'enum' else {'literal': [1, 0]}
                with self.subTest(key=key, recursive=recursive):
                    report = compare_contracts(before, after)
                    self.assertEqual(report['uncertain'], [])
                    self.assertEqual(len(report['changed']), 1)

    def test_ref_sibling_intersection_detected(self):
        before = document()
        before['components'] = {'schemas': {'Value': {'type': 'integer', 'minimum': 0}}}
        before['paths']['/search']['get']['parameters'] = [{'name': 'q', 'in': 'query', 'schema': {'$ref': '#/components/schemas/Value', 'maximum': 5}}]
        after = copy.deepcopy(before)
        after['paths']['/search']['get']['parameters'][0]['schema']['maximum'] = 4
        self.assertEqual(compare_contracts(before, after)['status'], 'review_required')

    def test_external_and_dynamic_refs_uncertain(self):
        for schema in [{'$ref': 'https://api.test/private.json#/Value'}, {'$dynamicRef': '#node'}]:
            with self.subTest(schema=schema):
                before = document()
                before['components'] = {'schemas': {'Node': {'type': 'object', 'properties': {'next': {'$ref': '#/components/schemas/Node'}}}}}
                before['paths']['/search']['get']['responses']['200']['content']['application/json']['schema'] = schema
                report = compare_contracts(before, copy.deepcopy(before))
                self.assertEqual(report['status'], 'uncertain')
                self.assertEqual(report['compatibility'], 'not_assessed')
                self.assertEqual(report['changed'], [])

    def recursive_document(self):
        value = document()
        value['components'] = {'schemas': {'Node': {'type': 'object', 'properties': {
            'value': {'type': 'integer', 'minimum': 0},
            'next': {'$ref': '#/components/schemas/Node'}}}}}
        value['paths']['/search']['get']['responses']['200']['content']['application/json']['schema'] = {'$ref': '#/components/schemas/Node'}
        return value

    def test_recursive_local_schema_is_compared_without_compatibility_claim(self):
        before = self.recursive_document()
        report = compare_contracts(before, copy.deepcopy(before))
        self.assertEqual(report['status'], 'declarations_unchanged')
        self.assertEqual(report['uncertain'], [])
        self.assertEqual(report['compatibility'], 'not_assessed')
        after = copy.deepcopy(before)
        after['components']['schemas']['Node']['properties']['value']['minimum'] = 1
        report = compare_contracts(before, after)
        self.assertEqual(report['status'], 'review_required')
        self.assertEqual(report['uncertain'], [])
        self.assertTrue(any(row['field'].endswith('/value/minimum') for row in report['changed'][0]['changes']))

    def test_mutual_recursive_graph_compares_reachable_constraint(self):
        before = self.recursive_document()
        schemas = before['components']['schemas']
        schemas['Node']['properties']['next'] = {'$ref': '#/components/schemas/Other'}
        schemas['Other'] = {'type': 'object', 'properties': {
            'back': {'$ref': '#/components/schemas/Node'}, 'value': {'type': 'string', 'maxLength': 4}}}
        after = copy.deepcopy(before)
        after['components']['schemas']['Other']['properties']['value']['maxLength'] = 3
        report = compare_contracts(before, after)
        self.assertEqual(report['uncertain'], [])
        self.assertEqual(len(report['changed']), 1)

    def test_equal_reference_lists_do_not_hide_multiple_changed_targets(self):
        before = self.recursive_document()
        before['components']['schemas']['Other'] = {'type': 'integer', 'maximum': 9}
        after = copy.deepcopy(before)
        after['components']['schemas']['Node']['properties']['value']['minimum'] = 1
        after['components']['schemas']['Other']['maximum'] = 8
        view = {'oneOf': [{'$ref': '#/components/schemas/Node'},
                          {'$ref': '#/components/schemas/Other'}]}
        changes = LocalSchemaComparison(before, after).changes(copy.deepcopy(view), copy.deepcopy(view))
        fields = {row['field'] for row in changes}
        self.assertTrue(any(field.endswith('/value/minimum') for field in fields))
        self.assertTrue(any(field.endswith('/maximum') for field in fields))

    def test_recursive_array_items_and_oneof_target_changes_are_reported(self):
        before = self.recursive_document()
        schema = before['paths']['/search']['get']['responses']['200']['content']['application/json']['schema']
        schema.clear()
        schema.update({'type': 'array', 'items': {'oneOf': [{'$ref': '#/components/schemas/Node'}]}})
        after = copy.deepcopy(before)
        after['components']['schemas']['Node']['properties']['value']['minimum'] = 1
        report = compare_contracts(before, after)
        self.assertEqual(report['uncertain'], [])
        self.assertEqual(len(report['changed']), 1)

    def test_recursive_component_rename_and_unreachable_edit_are_not_wire_changes(self):
        before = self.recursive_document()
        after = copy.deepcopy(before)
        node = after['components']['schemas'].pop('Node')
        node['properties']['next']['$ref'] = '#/components/schemas/Renamed'
        after['components']['schemas']['Renamed'] = node
        after['components']['schemas']['Unreachable'] = {'type': 'boolean'}
        after['paths']['/search']['get']['responses']['200']['content']['application/json']['schema']['$ref'] = '#/components/schemas/Renamed'
        self.assertEqual(compare_contracts(before, after)['status'], 'declarations_unchanged')

    def test_recursive_ref_sibling_constraints_and_literals_remain_visible(self):
        before = self.recursive_document()
        node = before['components']['schemas']['Node']
        node['properties']['next']['maxProperties'] = 5
        node['default'] = {'$ref': 'literal-value', 'description': 'before'}
        for mutation in ('sibling', 'literal'):
            after = copy.deepcopy(before)
            if mutation == 'sibling':
                after['components']['schemas']['Node']['properties']['next']['maxProperties'] = 4
            else:
                after['components']['schemas']['Node']['default']['description'] = 'after'
            with self.subTest(mutation=mutation):
                report = compare_contracts(before, after)
                self.assertEqual(report['uncertain'], [])
                self.assertEqual(len(report['changed']), 1)

    def test_recursive_schema_property_names_are_not_opaque_instances(self):
        before = self.recursive_document()
        before['components']['schemas']['Node']['properties']['default'] = {'$ref': '#/components/schemas/Other'}
        before['components']['schemas']['Other'] = {'type': 'string', 'maxLength': 4}
        after = copy.deepcopy(before)
        after['components']['schemas']['Other']['maxLength'] = 3
        self.assertEqual(compare_contracts(before, after)['status'], 'review_required')

    def test_ref_named_property_is_not_a_reference_edge(self):
        before = self.recursive_document()
        before['components']['schemas']['Node']['properties']['$ref'] = {'type': 'string'}
        after = copy.deepcopy(before)
        after['components']['schemas']['Node']['properties']['$ref']['type'] = 'boolean'
        report = compare_contracts(before, after)
        self.assertEqual(report['uncertain'], [])
        self.assertEqual(len(report['changed']), 1)

    def test_invalid_edges_inside_recursive_graph_remain_uncertain(self):
        for ref in ('https://api.test/private.json', '#/components/schemas/Missing'):
            before = self.recursive_document()
            before['components']['schemas']['Node']['properties']['other'] = {'$ref': ref}
            with self.subTest(ref=ref):
                self.assertEqual(compare_contracts(before, copy.deepcopy(before))['status'], 'uncertain')
        before = document()
        before['components'] = {'responses': {'Loop': {'$ref': '#/components/responses/Loop'}}}
        before['paths']['/search']['get']['responses']['200'] = {'$ref': '#/components/responses/Loop'}
        self.assertEqual(compare_contracts(before, copy.deepcopy(before))['status'], 'uncertain')
        before = self.recursive_document()
        before['components']['schemas']['Node'] = {'$ref': '#/components/schemas/Node'}
        self.assertEqual(compare_contracts(before, copy.deepcopy(before))['status'], 'uncertain')

    def test_deprecation_and_protocol_extensions_require_review(self):
        for field, value in [('deprecated', True), ('x-protocol', {'description': 'signed'})]:
            report = self.comparison(lambda doc: doc['paths']['/search']['get'].update({field: value}))
            self.assertEqual(report['status'], 'review_required')

    def test_dependency_field_names_are_not_annotations(self):
        before = document()
        schema = before['paths']['/search']['get']['responses']['200']['content']['application/json']['schema']
        schema['dependentRequired'] = {'description': ['value']}
        after = copy.deepcopy(before)
        after['paths']['/search']['get']['responses']['200']['content']['application/json']['schema']['dependentRequired']['description'] = ['other']
        self.assertEqual(compare_contracts(before, after)['status'], 'review_required')

    def test_dialect_change_uncertain(self):
        report = self.comparison(lambda doc: doc.update(openapi='3.0.3'))
        self.assertEqual(report['status'], 'uncertain')
        self.assertEqual(report['uncertain'][0]['reason'], 'declaration_dialect_changed')

    def test_path_item_refs_do_not_hide_methods(self):
        before = document()
        before['components'] = {'pathItems': {'Search': before['paths']['/search']}}
        before['paths']['/search'] = {'$ref': '#/components/pathItems/Search'}
        after = copy.deepcopy(before)
        after['components']['pathItems']['Search']['get']['operationId'] = 'new-id'
        self.assertEqual(compare_contracts(before, after)['changed'][0]['changes'][0]['field'], '/identity/operationId')

    def test_uncertain_one_method_does_not_hide_other_method(self):
        before = document()
        before['paths']['/search']['post'] = {'responses': {'200': {'$ref': 'https://api.test/response'}}}
        after = copy.deepcopy(before)
        after['paths']['/search']['get']['operationId'] = 'changed'
        report = compare_contracts(before, after)
        self.assertEqual(len(report['changed']), 1)
        self.assertEqual(len(report['uncertain']), 1)


if __name__ == '__main__':
    unittest.main()
