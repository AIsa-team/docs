import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare_composio_public_reference import prepare, schema_components, schema_digest
from compose_openapi import compose
from runtime_registry import public_mirror_index
from source_governance import policy_errors, validate_receipt
from test_runtime_contracts import facts
from datetime import datetime, timezone


class ConnectPublicReferenceTests(unittest.TestCase):
    def inputs(self):
        route = '/apis/v1/demo/lookup'
        vendors = {'vendors': [{'provider_key': 'composio', 'group': 'demo', 'operations': ['DEMO_LOOKUP'], 'routes': {'DEMO_LOOKUP': route}}]}
        metadata = {'DEMO_LOOKUP': {'tool_slug': 'DEMO_LOOKUP', 'input_schema': {'type': 'object', 'required': ['name'],
            'properties': {'name': {'type': 'string', 'minLength': 2}, 'mode': {'$ref': '#/$defs/Mode'}},
            '$defs': {'Mode': {'type': 'string', 'enum': ['one', 'two']}}}}}
        runtime = facts('provider')
        old = next(v for item in runtime['paths'].values() for k,v in item.items() if k in {'get','post'})
        old.update(operationId='demo.lookup', **{'x-aisa-status': 'enabled', 'x-aisa-validation': 'provider'})
        for key in ['parameters', 'x-aisa-upstream-path', 'x-aisa-upstream-selector', 'x-aisa-request-query', 'x-aisa-request-headers']:
            old.pop(key, None)
        old['requestBody'] = {'required': False, 'content': {'application/json': {'schema': {'type': 'object', 'additionalProperties': True}}}}
        runtime['servers'] = [{'url':'https://api.aisa.one'}]
        runtime['paths'] = {route:{'post':old}}
        return vendors, metadata, {'demo':runtime}

    def prepare(self, *args):
        return prepare(*args, metadata_sha256='a'*64, routes_sha256='b'*64, fetched_at='unknown historical capture time',
                       bindings={slug:{'tool_slug':slug,'input_schema_sha256':schema_digest(row['input_schema'])} for slug,row in args[1].items()})

    def test_captured_description_survives_import_and_composer_fallback(self):
        vendors, metadata, runtime = self.inputs()
        description = 'Look up a named record. Requires name; mode selects one or two.'
        metadata['DEMO_LOOKUP']['description'] = description
        fact = runtime['demo']['paths']['/apis/v1/demo/lookup']['post']
        fact['description'] = ''
        doc, _ = self.prepare(vendors, metadata, runtime)
        self.assertEqual(doc['paths']['/apis/v1/demo/lookup']['post']['description'], description)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'openapi/upstream').mkdir(parents=True)
            (root / 'openapi/upstream/connector.json').write_text(json.dumps(doc))
            mirrors = public_mirror_index(root)
            composed, pending = compose(runtime['demo'], public_mirrors=mirrors)
            self.assertEqual(pending, [])
            self.assertIn(description, composed['paths']['/apis/v1/demo/lookup']['post']['description'])
            fact['description'] = 'Runtime-owned updated instructions.'
            composed, _ = compose(runtime['demo'], public_mirrors=mirrors)
            actual = composed['paths']['/apis/v1/demo/lookup']['post']['description']
            self.assertIn(fact['description'], actual)
            self.assertNotIn(description, actual)

    def test_invalid_description_is_not_coerced_into_prose(self):
        vendors, metadata, runtime = self.inputs()
        metadata['DEMO_LOOKUP']['description'] = {'unexpected': 'object'}
        with self.assertRaisesRegex(ValueError, 'description must be text'):
            self.prepare(vendors, metadata, runtime)

    def test_http_entry_accepts_root_arguments_with_closed_references(self):
        vendors, metadata, runtime = self.inputs()
        original = copy.deepcopy(metadata)
        doc, report = self.prepare(vendors,metadata,runtime)
        op=doc['paths']['/apis/v1/demo/lookup']['post']
        body=op['requestBody']['content']['application/json']['schema']
        self.assertEqual(body, {'$ref': '#/components/schemas/connect_DEMO_LOOKUP'})
        self.assertNotIn('tool_slug', body)
        self.assertTrue(op['requestBody']['required'])
        schema=doc['components']['schemas']['connect_DEMO_LOOKUP']
        reference=schema['properties']['mode']['$ref']
        self.assertEqual(reference.count('/'),3)
        self.assertEqual(doc['components']['schemas'][reference.rsplit('/',1)[1]], {'type':'string','enum':['one','two']})
        self.assertEqual(schema['required'],['name'])
        self.assertEqual(metadata,original)
        self.assertNotIn('responses',op)
        self.assertFalse(report['formal_publication'])
        self.assertEqual(report['source_review_receipts_created'],0)
        self.assertFalse(policy_errors(doc['info']['x-aisa-source']))
        self.assertFalse(validate_receipt(doc['info']['x-aisa-source'],None,datetime.now(timezone.utc)))

    def test_real_composer_uses_source_without_claiming_responses(self):
        vendors,metadata,runtime=self.inputs();doc,_=self.prepare(vendors,metadata,runtime)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'openapi/upstream').mkdir(parents=True)
            (root/'openapi/upstream/connector.json').write_text(json.dumps(doc))
            composed,pending=compose(runtime['demo'],public_mirrors=public_mirror_index(root))
        self.assertEqual(pending,[])
        operation=composed['paths']['/apis/v1/demo/lookup']['post']
        self.assertIn('requestBody',operation)
        rendered=json.dumps(operation['requestBody'])
        self.assertNotIn('tool_slug',rendered)
        self.assertNotIn('enable_auto_workbench_offload',rendered)
        self.assertNotIn('content',operation['responses']['200'])

    def test_empty_http_body_uses_actual_empty_argument_validity(self):
        for constraint, expected in [({}, False), ({'minProperties':1}, True),
                                     ({'required':['name']}, True)]:
            vendors, metadata, runtime = self.inputs()
            schema = metadata['DEMO_LOOKUP']['input_schema']
            schema.pop('required'); schema.update(constraint)
            doc, _ = self.prepare(vendors, metadata, runtime)
            self.assertEqual(doc['paths']['/apis/v1/demo/lookup']['post']['requestBody']['required'], expected)

    def test_public_response_projects_only_declared_data_with_original_refs(self):
        vendors, metadata, runtime = self.inputs()
        output = {'type':'object','required':['data','successful'],
                  'properties':{'successful':{'type':'boolean'},'data':{'$ref':'#/$defs/Result'}},
                  '$defs':{'Result':{'type':'object','required':['answer'],'properties':{'answer':{'type':'integer'}}}}}
        metadata['DEMO_LOOKUP']['output_schema'] = output
        bindings={'DEMO_LOOKUP':{'tool_slug':'DEMO_LOOKUP',
            'input_schema_sha256':schema_digest(metadata['DEMO_LOOKUP']['input_schema']),
            'output_schema_sha256':schema_digest(output)}}
        doc,report=prepare(vendors,metadata,runtime,metadata_sha256='a'*64,routes_sha256='b'*64,
            fetched_at='unknown historical capture',bindings=bindings,include_responses=True)
        self.assertEqual(report['response_operations_added'],1)
        ref=doc['paths']['/apis/v1/demo/lookup']['post']['responses']['200']['content']['application/json']['schema']
        validation={'$ref':ref['$ref'],'components':doc['components']}
        validator=Draft202012Validator(validation)
        self.assertTrue(validator.is_valid({'answer':42}))
        self.assertFalse(validator.is_valid({'data':{'answer':42},'successful':True}))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'openapi/upstream').mkdir(parents=True)
            (root/'openapi/upstream/source.json').write_text(json.dumps(doc))
            composed,pending=compose(runtime['demo'],public_mirrors=public_mirror_index(root))
        self.assertEqual(pending,[])
        self.assertIn('content',composed['paths']['/apis/v1/demo/lookup']['post']['responses']['200'])
        bindings['DEMO_LOOKUP']['output_schema_sha256']='c'*64
        doc,report=prepare(vendors,metadata,runtime,metadata_sha256='a'*64,routes_sha256='b'*64,
            fetched_at='unknown historical capture',bindings=bindings,include_responses=True)
        self.assertEqual(report['response_operations_added'],0)
        self.assertNotIn('responses',doc['paths']['/apis/v1/demo/lookup']['post'])

    def test_capture_must_match_applied_production_input_pin(self):
        vendors,metadata,runtime=self.inputs()
        with self.assertRaisesRegex(ValueError,'No enabled exact public routes'):
            prepare(vendors,metadata,runtime,metadata_sha256='a'*64,routes_sha256='b'*64,fetched_at='unknown',
                    bindings={'DEMO_LOOKUP':{'tool_slug':'DEMO_LOOKUP','input_schema_sha256':'c'*64}})
        self.assertNotEqual(schema_digest({'minimum':1}),schema_digest({'minimum':1.0}))

    def test_recursive_definition_is_hoisted_without_losing_identity(self):
        schema={'type':'object','$defs':{'Node':{'type':'object','properties':{'next':{'$ref':'#/$defs/Node'}}}},
                'properties':{'root':{'$ref':'#/$defs/Node'}}}
        components=schema_components(schema,'tree')
        reference=components['tree']['properties']['root']['$ref']
        node=components[reference.rsplit('/',1)[1]]
        self.assertEqual(node['properties']['next']['$ref'],reference)
        self.assertEqual(len(components),2)

    def test_missing_metadata_stays_omitted(self):
        vendors,metadata,runtime=self.inputs()
        route='/apis/v1/demo/missing';vendors['vendors'][0]['routes']['DEMO_MISSING']=route
        vendors['vendors'][0]['operations'].append('DEMO_MISSING')
        runtime['demo']['paths'][route]={'post':{'operationId':'demo.missing','x-aisa-status':'enabled'}}
        doc,report=self.prepare(vendors,metadata,runtime)
        self.assertNotIn(route,doc['paths']);self.assertEqual(report['omitted'][0]['reason'],'metadata_missing')

    def test_inline_oneof_preserves_bad_discriminator_only_as_annotation(self):
        schema = {'oneOf': [
            {'title': title, 'type': 'object', 'required': ['mode', field],
             'properties': {'mode': {'const': mode}, field: {'type': 'string', 'minLength': 1}}}
            for title, mode, field in [('A', 'a', 'name'), ('B', 'b', 'code')]],
            'discriminator': {'propertyName': 'mode', 'mapping': {'a': '#/$defs/A', 'b': '#/$defs/B'}}}
        converted = schema_components(schema, 'choice')['choice']
        self.assertEqual(converted['oneOf'], schema['oneOf'])
        self.assertEqual(converted['x-aisa-source-discriminator'], schema['discriminator'])
        self.assertNotIn('discriminator', converted)
        self.assertNotIn('$defs', converted)
        original_validator, converted_validator = map(Draft202012Validator, (schema, converted))
        for sample in ({'mode':'a','name':'yes'}, {'mode':'b','code':'yes'}, {},
                       {'mode':'a','name':''}, {'mode':'a','code':'wrong'}, {'mode':'c','code':'wrong'}):
            with self.subTest(sample=sample):
                self.assertEqual(original_validator.is_valid(sample), converted_validator.is_valid(sample))
        invalid = copy.deepcopy(schema); invalid['oneOf'][1]['properties']['code']['$ref'] = '#/$defs/missing'
        with self.assertRaisesRegex(ValueError, 'Unresolved schema reference'):
            schema_components(invalid, 'choice')
        invalid = copy.deepcopy(schema); invalid['discriminator']['mapping']['c'] = '#/$defs/C'
        with self.assertRaisesRegex(ValueError, 'Incomplete inline'):
            schema_components(invalid, 'choice')

    def test_tool_identity_or_route_inventory_mismatch_rejects(self):
        vendors,metadata,runtime=self.inputs();metadata['DEMO_LOOKUP']['tool_slug']='OTHER'
        with self.assertRaisesRegex(ValueError,'tool identity'):self.prepare(vendors,metadata,runtime)
        vendors,metadata,runtime=self.inputs();vendors['vendors'][0]['operations']=[]
        with self.assertRaisesRegex(ValueError,'inventory'):self.prepare(vendors,metadata,runtime)

    def test_external_dangling_or_dynamic_references_are_not_guessed(self):
        for schema in ({'$ref':'https://example.com/schema'}, {'$ref':'#/missing'}, {'$id':'https://example.com/schema'}, {'$dynamicRef':'#node'}, {'discriminator':{'mapping':{'x':'#/$defs/missing'}}}):
            with self.subTest(schema=schema),self.assertRaises(ValueError):schema_components(schema,'example')

if __name__ == '__main__':unittest.main()
