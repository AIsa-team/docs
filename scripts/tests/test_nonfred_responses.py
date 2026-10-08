import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wrapper_twitter_reference as twitter
import wrapper_cloudsway_reference as cloudsway
import import_byteplus_response_reference as byteplus
import import_similarweb_response_reference as similarweb
from compose_openapi import compose, has_response_contract
from jsonschema import Draft202012Validator
from test_runtime_contracts import facts, operation
FIXTURES = Path(__file__).parent / 'fixtures'


class NonFredResponseTests(unittest.TestCase):
    def test_owning_twitter_model_is_typed_opaque_data_not_inferred_result(self):
        routes = (FIXTURES/'wrapper_twitter_routes.py.txt').read_bytes() + b'\n@router.post("/post_twitter", response_model=ApiResponse)\nasync def post_tweet(request):\n    pass\n'
        schemas = (FIXTURES/'wrapper_twitter_schemas.py.txt').read_bytes()
        paths = twitter.response_reference(routes, schemas)
        self.assertEqual(set(paths), {'/delete_twitter', '/post_twitter'})
        for item in paths.values():
            schema = item['post']['responses']['200']['content']['application/json']['schema']
            validator = Draft202012Validator(schema)
            for data in [None, {'data': {'id': 'a'}, 'future': [True, 1]}]:
                self.assertTrue(validator.is_valid({'code': 200, 'msg': 'ok', 'data': data}))
            for payload in [{'msg': 'ok'}, {'code': '200', 'msg': 'ok'}, {'code': 200, 'msg': 'ok', 'data': []}]:
                self.assertFalse(validator.is_valid(payload))
            self.assertNotIn('id', schema['properties']['data']['anyOf'][0])

    def test_twitter_model_or_response_model_drift_rejected(self):
        routes=(FIXTURES/'wrapper_twitter_routes.py.txt').read_bytes()
        schemas=(FIXTURES/'wrapper_twitter_schemas.py.txt').read_bytes()
        for r,s in [(routes,schemas.replace(b'code: int', b'code: str')),
                    (routes,schemas.replace(b'data: Optional[dict[str, Any]] = None',b'data: Any = None')),
                    (routes.replace(b'response_model=ApiResponse',b'response_model=Other'),schemas)]:
            with self.assertRaises(ValueError): twitter.response_reference(r,s)

    def test_twitter_response_status_and_serialization_changes_fail_closed(self):
        routes=(FIXTURES/'wrapper_twitter_routes.py.txt').read_bytes()
        schemas=(FIXTURES/'wrapper_twitter_schemas.py.txt').read_bytes()
        for keyword in [b'status_code=201',b'response_class=PlainTextResponse',b'response_model_exclude_none=True']:
            with self.assertRaises(ValueError):
                twitter.response_reference(routes.replace(b'response_model=ApiResponse',b'response_model=ApiResponse, '+keyword),schemas)
        routes += b'\n@router.post("/post_twitter", response_model=ApiResponse)\nasync def post_tweet(request):\n    pass\n'
        doc,_=twitter.convert_reference(routes,schemas)
        self.assertNotIn('/post_twitter',doc['paths'])
        self.assertIn('/post_twitter',twitter.response_reference(routes,schemas))

    def test_cloudsway_declared_types_and_optional_fields(self):
        doc,_=cloudsway.convert_reference((FIXTURES/'wrapper_cloudsway_smart.html').read_bytes())
        response=doc['paths']['/apis/v1/search/smart']['get']['responses']['200']
        self.assertTrue(has_response_contract(response))
        schema=response['content']['application/json']['schema'];Draft202012Validator.check_schema(schema)
        fields=schema['properties']['webPages']['properties']['value']['items']['properties']
        self.assertEqual(fields['contentCrawled']['type'], 'boolean')
        self.assertEqual(fields['score']['type'], 'number')
        self.assertNotIn('items', fields['imageList'])
        self.assertNotIn('required', schema)
        validator=Draft202012Validator(schema)
        self.assertTrue(validator.is_valid({'webPages':{'value':[{'contentCrawled':True,'score':.2}]}}))
        self.assertFalse(validator.is_valid({'webPages':{'value':[{'contentCrawled':'true'}]}}))

    def test_cloudsway_missing_or_ambiguous_response_stays_rejected(self):
        raw=(FIXTURES/'wrapper_cloudsway_smart.html').read_bytes()
        for variant in [raw[:raw.index(b'<h1>Response')],raw.replace(b'<td>Bool</td>',b'<td>String</td>'),raw.replace(b'webPages.value.score',b'webPages.value.unknown')]:
            with self.assertRaises(ValueError):cloudsway.convert_reference(variant)

    def test_pullposts_types_required_and_no_sample_inference(self):
        doc,meta=byteplus.convert_reference((FIXTURES/'byteplus-pullposts-response.html').read_bytes())
        response=doc['paths']['/']['post']['responses']['200'];self.assertFalse(has_response_contract(response))
        result=doc['components']['schemas']['PullPostsResult'];Draft202012Validator.check_schema(result)
        self.assertEqual(set(result['required']),{'HasMore','NextPageToken','ItemDocs'})
        post=result['properties']['ItemDocs']['items'];self.assertEqual(set(post['required']),{'PostID','Url','PublishTime'})
        self.assertNotIn('MainDomain',post['properties'])
        self.assertEqual(post['properties']['RiskType']['items'],{'type':'string'})
        self.assertEqual(set(doc['paths']),{'/'})
        self.assertNotIn('CreateMonitorTask',json.dumps(doc))

    def test_pullposts_changed_version_required_type_duplicate_fail_closed(self):
        raw=(FIXTURES/'byteplus-pullposts-response.html').read_bytes()
        for variant in [raw.replace(b'2026\\\\-03\\\\-24',b'2026\\\\-03\\\\-25'),raw.replace(b'HasMore |bool |Yes',b'HasMore |bool |No'),raw.replace(b'PostID |string',b'PostID |int'),raw.replace(b'|HasMore |bool |Yes',b'|Unknown |bool |Yes')]:
            with self.assertRaises(ValueError):byteplus.convert_reference(variant)

    def test_similarweb_explicit_graph_preserves_nullable_enum_and_required(self):
        path='/v5/segment-analysis/segments/traffic-and-engagement'
        raw=(FIXTURES/'similarweb-segments-response.html').read_bytes()
        doc,_=similarweb.convert_reference(raw,path,'https://docs.similarweb.com/api-v5/segment-analysis/segments/traffic-and-engagement')
        schema=doc['paths'][path]['get']['responses']['200']['content']['application/json']['schema']
        Draft202012Validator.check_schema(schema)
        request=schema['properties']['meta']['properties']['request']
        self.assertEqual(request['required'],['segment'])
        self.assertEqual(request['properties']['country']['type'],['string','null'])
        self.assertEqual(request['properties']['format']['enum'],['json','xml'])
        self.assertEqual(schema['properties']['data']['items']['properties']['visits']['type'],['number','null'])
        self.assertNotIn('default',request['properties']['segment'])

    def test_similarweb_named_arrays_and_unrepresented_semantics_fail_closed(self):
        node={'valueType':'array','items':[{'name':'date','valueType':'string'}]}
        with self.assertRaisesRegex(ValueError,'named child'):similarweb.field_schema(node,'data')
        for bad in [{'valueType':'object','options':{'additionalProperties':False}},
                    {'valueType':'object','additionalProperties':False},
                    {'valueType':'array','items':[]},
                    {'valueType':'string','complexItems':[{'value':'x'}]},
                    {'valueType':'string','options':{'style':'form'}},
                    {'valueType':'string','options':{'nullable':1}}]:
            with self.assertRaises(ValueError):similarweb.field_schema(bad,'data')
        with self.assertRaisesRegex(ValueError,'endpoint mismatch'):
            similarweb.convert_reference((FIXTURES/'similarweb-segments-response.html').read_bytes(),'/wrong','https://docs.similarweb.com/api-v5/x')

    def test_composition_reduces_only_response_debt_preserves_identity_price(self):
        doc,_=cloudsway.convert_reference((FIXTURES/'wrapper_cloudsway_smart.html').read_bytes())
        runtime=facts('provider');op=operation(runtime);path=next(iter(runtime['paths']))
        op['x-aisa-passthrough']=True;op['x-aisa-upstream-path']='/apis/v1/search/smart';op['responses']={'200':{'description':'unknown'}}
        runtime['paths']={path:{'get':op}}
        before,pending_before=compose(runtime)
        doc['info']['x-aisa-source']={'kind':'manual','url':cloudsway.REFERENCE_URL,'fetched_at':'2026-10-08','content_hash':'sha256:fixture','converter':cloudsway.VERSION}
        after,pending_after=compose(runtime,doc)
        actual=after['paths'][path]['get']
        self.assertEqual(actual['operationId'],op['operationId']);self.assertEqual(actual['x-aisa-pricing'],op['x-aisa-pricing'])
        self.assertTrue(has_response_contract(actual['responses']['200']))
        self.assertEqual(len(after['info']['x-aisa-document']['response_pending']),0)
        # Without a source this provider-owned operation is request-pending;
        # with its original request-only source the response gap is explicit.
        old=copy.deepcopy(doc)
        old['paths']['/apis/v1/search/smart']['get']['responses']['200']={'description':'unknown'}
        old_document,_=compose(runtime,old)
        self.assertEqual(len(old_document['info']['x-aisa-document']['response_pending']),1)
        self.assertLess(len(pending_after),len(pending_before))
        runtime_op=next(iter(runtime['paths'][path].values()))
        runtime_op['x-aisa-validation']='runtime'
        runtime_op.pop('x-aisa-passthrough',None)
        runtime_op['requestBody']={'content':{'application/json':{'schema':{'type':'string'}}}}
        preserved,_=compose(runtime,doc)
        self.assertEqual(len(preserved['info']['x-aisa-document']['response_pending']),1)
        self.assertEqual(preserved['paths'][path]['get']['requestBody'],runtime_op['requestBody'])


if __name__=='__main__':unittest.main()
