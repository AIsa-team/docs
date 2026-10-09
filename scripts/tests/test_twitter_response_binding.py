"""Source binding regression; synthetic runtime facts do not assert live publication."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from compose_openapi import compose
from runtime_registry import public_mirror_index
from source_governance import policy_errors
ROOT=Path(__file__).resolve().parents[2]
PATH='/apis/v1/twitter/post_twitter'
SOURCE='response-aisa-twitter-post.json'
def source():return json.loads((ROOT/'openapi/upstream'/SOURCE).read_text())
def facts():
 s=source()['info']['x-aisa-source']
 return {'openapi':'3.1.0','info':{'x-aisa-document':{'facts_hash':'synthetic'}},'servers':[{'url':'https://api.aisa.one'}],'paths':{PATH:{'x-aisa-any':{'operationId':'postTwitter','x-aisa-status':'enabled','x-aisa-validation':'runtime','x-aisa-response-passthrough':True,'x-aisa-response-upstream-path-sha256':s['upstream_path_sha256'],'x-aisa-response-upstream-origin-sha256':s['upstream_origin_sha256'],'requestBody':{'required':True,'content':{'application/json':{'schema':{'type':'object','properties':{'text':{'type':'string'}}}}}},'x-aisa-pricing':{'default_request_estimate_usd':0.12},'responses':{'200':{'description':'Successful response'}}}}}}
class TwitterBindingTests(unittest.TestCase):
 def test_static_source_contains_no_request_authority_or_fake_receipt(self):
  doc=source();s=doc['info']['x-aisa-source'];self.assertTrue(s['response_only']);self.assertEqual(set(doc['paths'][PATH]['post']),{'responses'});self.assertEqual(policy_errors(s),[]);self.assertNotIn('reviewer',s)
 def test_existing_independent_post_mirror_closes_only_response(self):
  mirrors=public_mirror_index(ROOT);baseline=public_mirror_index(ROOT,{SOURCE:{}})
  self.assertFalse(baseline[(PATH,'post')].get('response_only'));self.assertTrue(baseline[(PATH,'post')]['operation'].get('requestBody'))
  before,bp=compose(facts(),public_mirrors=baseline);after,ap=compose(facts(),public_mirrors=mirrors)
  self.assertEqual(bp,ap);self.assertEqual(ap,[]);self.assertEqual(len(before['info']['x-aisa-document']['response_pending']),1);self.assertEqual(after['info']['x-aisa-document']['response_pending'],[])
  excluded={'responses','x-aisa-response-pending','x-aisa-response-source'}
  self.assertEqual({k:v for k,v in before['paths'][PATH]['post'].items() if k not in excluded},{k:v for k,v in after['paths'][PATH]['post'].items() if k not in excluded})
 def test_response_source_alone_cannot_choose_any_method(self):
  with tempfile.TemporaryDirectory() as tmp:
   mirrors=public_mirror_index(Path(tmp),{SOURCE:source()});doc,pending=compose(facts(),public_mirrors=mirrors)
  self.assertEqual(doc['paths'],{});self.assertEqual(len(pending),1);self.assertEqual(pending[0]['method'],'ANY')
 def test_wrong_origin_or_path_stays_pending(self):
  for key in ('x-aisa-response-upstream-path-sha256','x-aisa-response-upstream-origin-sha256'):
   runtime=facts();runtime['paths'][PATH]['x-aisa-any'][key]='0'*64
   doc,pending=compose(runtime,public_mirrors=public_mirror_index(ROOT));self.assertEqual(pending,[]);self.assertEqual(len(doc['info']['x-aisa-document']['response_pending']),1)
