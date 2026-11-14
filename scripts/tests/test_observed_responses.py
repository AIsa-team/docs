import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from compose_openapi import compose, descriptive_text, published_success_responses
from test_unreviewed_runtime_publication import facts, operation, upstream, ops

OBS={'200':{'schema':{'type':'object','additionalProperties':True,'properties':{'rows':{'type':'array','items':{'type':'object','additionalProperties':True,'properties':{'id':{'type':'integer'}}}}}},'completeness':'observed','last_observed':'2026-11-13','origins':['customer','probe']}}

class ObservedResponses(unittest.TestCase):
 def build(self,obs=OBS,responses=None,previous=None):
  op=operation('x.search',validation='runtime',**{'x-aisa-observed-responses':copy.deepcopy(obs)})
  if responses is not None:op['responses']=responses
  return compose(facts({'/apis/v1/x/search':{'post':op}}),upstream({}),previous=previous,unreviewed_runtime=True)
 def test_composition_marks_partial_and_preserves_pricing(self):
  doc,pending=self.build();self.assertEqual(pending,[])
  op=ops(doc)[('/apis/v1/x/search','post')];response=op['responses']['200']
  self.assertEqual(response['content']['application/json']['schema'],OBS['200']['schema'])
  self.assertIn('partial',response['description']);self.assertEqual(op['x-aisa-review']['response'],'observed')
  self.assertEqual(op['x-aisa-pricing']['unit_rate_usd'],.01)
 def test_official_schema_wins(self):
  official={'200':{'description':'Declared','content':{'application/json':{'schema':{'type':'string'}}}}}
  doc,_=self.build(responses=official);self.assertEqual(ops(doc)[('/apis/v1/x/search','post')]['responses'],official)
 def test_old_observation_is_not_retained_as_authority(self):
  previous,_=self.build();self.assertEqual(published_success_responses(previous),{})
  doc,_=self.build(obs={},previous=previous)
  response=ops(doc)[('/apis/v1/x/search','post')]['responses']['200']
  self.assertNotIn('x-aisa-response-observation',response)
  self.assertNotIn('id',str(response['content']))
 def test_instance_values_cannot_enter_schema(self):
  bad=copy.deepcopy(OBS);bad['200']['schema']['example']={'token':'SECRET'}
  doc,pending=self.build(obs=bad);self.assertTrue(pending);self.assertNotIn('SECRET',str(doc))
 def test_static_prose_is_not_shadowed_by_runtime_title(self):
  runtime={'summary':'Search','description':'Search'}
  self.assertEqual(descriptive_text({},runtime,{'description':'Search across indexed pages. Supply q to select terms.'}),'Search across indexed pages. Supply q to select terms.')
  self.assertEqual(descriptive_text({'description':'Reviewed editorial'},runtime,{'description':'Source'}),'Reviewed editorial')

 def test_any_method_samples_do_not_leak_to_sibling_method(self):
  op=operation('x.search',validation='provider',**{'x-aisa-observed-response-methods':{'GET':copy.deepcopy(OBS)}})
  doc,pending=compose(facts({'/apis/v1/x/search':{'x-aisa-any':op}}),upstream({'/v1/search':{'get':{'operationId':'getSearch'},'post':{'operationId':'postSearch'}}}),unreviewed_runtime=True)
  self.assertEqual(pending,[])
  self.assertIn('x-aisa-response-observation',doc['paths']['/apis/v1/x/search']['get']['responses']['200'])
  self.assertNotIn('x-aisa-response-observation',doc['paths']['/apis/v1/x/search']['post']['responses']['200'])
 def test_bilingual_readable_observations_are_marked_and_value_free(self):
  from readable_contract_notes import readable_block
  for language,marker in [('en','partial'),('zh','只反映已观察到的部分')]:
   text=readable_block({'x-aisa-observed-responses':OBS},language)
   self.assertIn(marker,text);self.assertIn('2026-11-13',text);self.assertIn('"integer"',text)
