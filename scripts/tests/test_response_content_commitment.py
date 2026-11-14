import copy
from pathlib import Path
import sys
import unittest
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).parent)]
from compose_openapi import compose,digest,validate_payment_capabilities
from test_independent_response_sources import descriptor,index,response_source
from test_runtime_contracts import facts,operation

class PublicResponseCommitmentTests(unittest.TestCase):
 def test_private_binding_becomes_reproducible_public_content_binding(self):
  private=descriptor(facts());mirrors=index(response_source())
  first,pending=compose(private,public_mirrors=mirrors);self.assertEqual(pending,[])
  commitment=operation(first)['x-aisa-response-contract-hash']
  public=copy.deepcopy(private);op=operation(public)
  for key in ('x-aisa-response-passthrough','x-aisa-response-upstream-origin-sha256','x-aisa-response-upstream-path-sha256'):op.pop(key,None)
  op['x-aisa-response-contract-hashes']={'POST':commitment}
  public['info']['x-aisa-document']['facts_hash']='final-public-input-hash'
  second,pending=compose(public,public_mirrors=mirrors);self.assertEqual(pending,[])
  self.assertEqual(operation(second)['responses'],operation(first)['responses'])
  self.assertEqual(compose(copy.deepcopy(public),public_mirrors=mirrors),(second,[]))
  self.assertEqual(second['info']['x-aisa-document']['facts_hash'],'final-public-input-hash')
  operation(public)['x-aisa-response-contract-hashes']={'POST':'sha256:'+'f'*64}
  failed,_=compose(public,public_mirrors=mirrors)
  self.assertIn('x-aisa-response-pending',operation(failed))
 def test_absent_reviewed_response_is_explicit_and_does_not_inherit_old_schema(self):
  private=descriptor(facts());first,_=compose(private,unreviewed_runtime=True)
  self.assertEqual(operation(first)['x-aisa-response-contract-hash'],digest({}))
  public=copy.deepcopy(private);op=operation(public)
  for key in ('x-aisa-response-passthrough','x-aisa-response-upstream-origin-sha256','x-aisa-response-upstream-path-sha256'):op.pop(key,None)
  op['x-aisa-response-contract-hash']=digest({})
  second,pending=compose(public,unreviewed_runtime=True,previous=first)
  self.assertEqual(pending,[]);self.assertNotIn('x-aisa-response-source',operation(second))

 def test_nil_capabilities_match_go_code_owned_descriptors(self):
  validate_payment_capabilities({'x-aisa-capabilities':None,'x-aisa-contract-source':'handler'})
  for invalid in (None,[],False,'',{'mpp':1}):
   with self.assertRaises(ValueError):validate_payment_capabilities({'x-aisa-capabilities':invalid})

 def test_transformed_and_empty_selection_never_adopt_mirror_payload(self):
  private=facts();operation(private)['x-aisa-response-passthrough']=False
  mirrors=index(response_source())
  first,_=compose(private,public_mirrors=mirrors)
  self.assertEqual(operation(first)['x-aisa-response-contract-hash'],digest({}))
  public=copy.deepcopy(private);op=operation(public);op.pop('x-aisa-response-passthrough')
  op['x-aisa-response-contract-hashes']={'POST':digest({})}
  second,_=compose(public,public_mirrors=mirrors)
  self.assertEqual(operation(first)['responses'],operation(second)['responses'])
  self.assertNotIn('x-aisa-response-source',operation(second))
 def test_public_selection_is_method_specific(self):
  private=descriptor(facts());mirrors=index(response_source())
  first,_=compose(private,public_mirrors=mirrors)
  public=copy.deepcopy(private);op=operation(public)
  for key in ('x-aisa-response-passthrough','x-aisa-response-upstream-origin-sha256','x-aisa-response-upstream-path-sha256'):op.pop(key,None)
  op['x-aisa-response-contract-hashes']={'GET':operation(first)['x-aisa-response-contract-hash']}
  second,pending=compose(public,public_mirrors=mirrors)
  self.assertEqual(second['paths'],{})
  self.assertIn('method-specific',pending[0]['reason'])
