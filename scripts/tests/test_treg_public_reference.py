import copy
from pathlib import Path
import sys
import unittest
from jsonschema import Draft202012Validator
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prepare_treg_public_reference import field_schema, public_request


class TregPublicRequestTests(unittest.TestCase):
    def test_upstream_path_slots_are_public_query(self):
        operation=public_request({'path':'/items/{id}','input':{'pathParams':{'id':{'type':'string','required':True}},
            'queryParams':{'limit':{'type':'integer','required':False,'min':1,'max':20}}}})
        self.assertEqual([p['in']for p in operation['parameters']],['query','query'])
        self.assertTrue(operation['parameters'][0]['required'])
        self.assertEqual(operation['parameters'][1]['schema'],{'type':'integer','minimum':1,'maximum':20})

    def test_typed_array_uses_item_enum_and_cardinality(self):
        schema=field_schema({'type':'array[string]','enum':['a','b'],'min':1,'maxItems':2,'required':True})
        self.assertEqual(schema,{'type':'array','items':{'type':'string','enum':['a','b']},'minItems':1,'maxItems':2})
        validate=Draft202012Validator(schema)
        self.assertTrue(validate.is_valid(['a','b']))
        self.assertFalse(validate.is_valid(['c']))
        self.assertFalse(validate.is_valid([]))

    def test_body_allowlist_closes_fields_and_requires_nonempty_string(self):
        source={'body_allowlist':True,'input':{'body':{'name':{'type':'string','required':True},'n':{'type':'integer'}}}}
        schema=public_request(source)['requestBody']['content']['application/json']['schema']
        validator=Draft202012Validator(schema)
        self.assertTrue(validator.is_valid({'name':'a','n':0}))
        for value in ({'name':''},{'name':None},{'name':'a','other':1},{}):self.assertFalse(validator.is_valid(value))
        source['input']['body']['name']['required']=False
        request=public_request(source)['requestBody']
        self.assertTrue(request['required'])
        self.assertTrue(Draft202012Validator(request['content']['application/json']['schema']).is_valid({}))

    def test_omits_unmodeled_operation_constraints(self):
        for constraint in ('platform_request','strict_query','managed_resource','body_required_any','team_label','unknown_gate'):
            source={constraint:True,'input':{'queryParams':{'q':{'type':'string'}}}}
            with self.subTest(constraint=constraint),self.assertRaises(ValueError):public_request(source)

    def test_unknown_shapes_do_not_become_empty_schema(self):
        for schema in ({'type':'anything'},{'type':'array'},{'type':'array[object]'},{'type':'object'},
                       {'type':'string','max':5},{'type':'array[string]','item_required_any':['x']},
                       {'type':'string','required':['x']}):
            with self.subTest(schema=schema),self.assertRaises(ValueError):field_schema(schema)
        self.assertEqual(field_schema({'type':'object','additionalProperties':True}),
                         {'type':'object','additionalProperties':True})

    def test_query_objects_and_form_are_not_assumed_to_use_json(self):
        for source in ({'input':{'queryParams':{'q':{'type':'array[string]'}}}},
                       {'input':{'bodyType':'form','body':{'q':{'type':'string'}}}},
                       {'path':'/x/{id}','input':{'queryParams':{'q':{'type':'string'}}}}):
            with self.subTest(source=source),self.assertRaises(ValueError):public_request(source)

if __name__=='__main__':unittest.main()
