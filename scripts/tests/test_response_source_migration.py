"""Explicit reviewed migration fixture, never approval of real provider schemas."""
import copy
import json
from pathlib import Path
import sys
import unittest
sys.path[:0]=[str(Path(__file__).resolve().parents[1])]
import prepare_response_source_migration as migration
from compose_openapi import compose
from test_independent_response_sources import descriptor, index
from test_runtime_contracts import facts, operation


class ResponseMigrationTests(unittest.TestCase):
    def inputs(self):
        current=descriptor(facts())
        old=copy.deepcopy(current)
        operation(old)['responses']={'200':{'description':'Public typed response','content':{'application/json':{'schema':{'type':'object','properties':{'value':{'type':'string'}},'required':['value']}}}}}
        old['servers']=[{'url':'https://api.aisa.one/apis/v1'}]
        old['paths']={'/similarweb/test':next(iter(old['paths'].values()))}
        raw=json.dumps(old).encode()
        review=migration.plan(raw,current,'https://github.com/AIsa-team/docs/blob/'+'a'*40+'/openapi/provider.json','a'*40)
        return raw,current,review

    def reviewed(self):
        raw,current,review=self.inputs()
        review['source_verified_at']='2026-10-09T00:00:00Z'
        review['rows'][0].update(review_decision=migration.DECISION,review_evidence='Synthetic fixture: source response and unchanged transport explicitly compared.')
        return raw,current,review

    def test_default_plan_does_not_migrate_without_per_route_review(self):
        raw,current,review=self.inputs()
        self.assertFalse(review['source_approved'])
        self.assertEqual(review['rows'][0]['status'],'review_required')
        self.assertEqual(migration.prepare(raw,current,review),{})

    def test_reviewed_source_preserves_response_and_does_not_supply_request(self):
        raw,current,review=self.reviewed()
        documents=migration.prepare(raw,current,review)
        self.assertEqual(len(documents),1)
        source=next(iter(documents.values()))
        self.assertEqual(set(operation(source)),{'responses'})
        before=copy.deepcopy(operation(current))
        doc,pending=compose(current,public_mirrors=index(source))
        self.assertEqual(pending,[]);self.assertNotIn('x-aisa-response-pending',operation(doc))
        self.assertEqual(operation(doc)['responses']['200']['content'],operation(json.loads(raw))['responses']['200']['content'])
        for key,value in before.items():
            if key!='responses':self.assertEqual(operation(doc)[key],value)
        self.assertEqual(compose(current,public_mirrors=index(source),previous=doc),(doc,[]))

    def test_transport_request_identity_or_source_drift_invalidates_review(self):
        for change in ('path','origin','request','identity','response','bytes'):
            raw,current,review=self.reviewed()
            if change=='path':operation(current)['x-aisa-response-upstream-path-sha256']='b'*64
            elif change=='origin':operation(current)['x-aisa-response-upstream-origin-sha256']='b'*64
            elif change=='request':operation(current)['parameters'][0]['schema']['type']='string'
            elif change=='identity':operation(current)['operationId']='changed'
            elif change=='response':review['rows'][0]['success_contract_sha256']='sha256:wrong'
            else:raw += b'\n'
            with self.assertRaises(ValueError,msg=change):migration.prepare(raw,current,review)

    def test_transformed_example_only_or_identity_mismatch_remain_blocked(self):
        for change in ('transformed','example','identity'):
            raw,current,review=self.inputs();old=json.loads(raw)
            if change=='transformed':operation(current)['x-aisa-response-passthrough']=False
            elif change=='identity':operation(current)['operationId']='other'
            else:operation(old)['responses']['200']['content']['application/json']={'example':{'value':'x'}}
            result=migration.plan(json.dumps(old).encode(),current,review['source_url'],review['source_revision'])
            self.assertEqual(result['rows'][0]['status'],'blocked')

    def test_duplicate_incomplete_or_automatic_approval_is_rejected(self):
        for change in ('duplicate','evidence','approval','time'):
            raw,current,review=self.reviewed()
            if change=='duplicate':review['rows'].append(copy.deepcopy(review['rows'][0]))
            elif change=='evidence':review['rows'][0]['review_evidence']=''
            elif change=='approval':review['source_approved']=True
            else:review.pop('source_verified_at')
            with self.assertRaises(ValueError,msg=change):migration.prepare(raw,current,review)

if __name__=='__main__':unittest.main()
