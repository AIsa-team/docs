import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from compose_openapi import compose
from pull_openapi import stage
from test_runtime_contracts import facts, operation

ROOT=Path(__file__).resolve().parents[2]


def upstreams():
    return [json.loads((ROOT/'openapi/upstream'/name).read_text()) for name in ('searchapi-airbnb.json','searchapi-ebay-search.json')]


def selected_facts(engine='airbnb',mode='default'):
    doc=facts('provider','x-aisa-any')
    op=operation(doc)
    op['x-aisa-upstream-path']='/api/v1/search'
    op['x-aisa-query-policy']={'request_wins':mode=='default'}
    op['x-aisa-upstream-selector']={'in':'query','name':'engine','value':engine,'mode':mode}
    return doc


class UpstreamSelectorTests(unittest.TestCase):
    def test_real_official_sources_remain_separate_and_override_is_not_constrained(self):
        for engine,present,absent in [('airbnb','check_in_date','ebay_domain'),('ebay_search','ebay_domain','check_in_date')]:
            source=selected_facts(engine)
            document,pending=compose(source,upstreams())
            self.assertEqual(pending,[])
            op=operation(document)
            params={p['name']:p for p in op['parameters']}
            self.assertIn(present,params)
            self.assertNotIn(absent,params)
            self.assertNotIn('api_key',params)
            self.assertEqual(params['engine']['schema'],{'type':'string','default':engine})
            self.assertFalse(params['engine']['required'])
            self.assertIn('override',params['engine']['description'])
            self.assertIn('not guaranteed',params['engine']['description'])
            self.assertEqual(op['operationId'],operation(source)['operationId'])
            self.assertEqual(op['x-aisa-pricing'],operation(source)['x-aisa-pricing'])

    def test_fixed_engine_is_supplied_by_runtime(self):
        doc,pending=compose(selected_facts(mode='fixed'),upstreams())
        self.assertEqual(pending,[])
        self.assertNotIn('engine',[p['name'] for p in operation(doc).get('parameters',[])])

    def test_missing_invalid_and_ambiguous_selectors_fail_closed(self):
        for engine in ['absent_engine','secret value']:
            doc,pending=compose(selected_facts(engine),upstreams())
            self.assertEqual(doc['paths'],{})
            self.assertEqual(len(pending),1)
        facts_without_selector=selected_facts()
        operation(facts_without_selector).pop('x-aisa-upstream-selector')
        doc,pending=compose(facts_without_selector,upstreams())
        self.assertEqual(doc['paths'],{})
        self.assertIn('ambiguous',pending[0]['reason'])
        doc,pending=compose(selected_facts(),[upstreams()[0],copy.deepcopy(upstreams()[0])])
        self.assertEqual(doc['paths'],{})
        self.assertIn('ambiguous',pending[0]['reason'])

    def test_explicit_public_mirror_still_covers_other_engines(self):
        source=selected_facts('youtube')
        path=next(iter(source['paths']))
        public={(path,'get'):{'operation':{'operationId':'existing_public_identity','parameters':[{'name':'video_id','in':'query','schema':{'type':'string'}}]},'source':{'kind':'manual','path_space':'public','url':'https://example.test/published','content_hash':'sha256:manual','fetched_at':'2026-09-30','converter':'test'},'components':{}}}
        doc,pending=compose(source,upstreams(),public_mirrors=public)
        self.assertEqual(pending,[])
        self.assertIn('video_id',[p['name'] for p in operation(doc)['parameters']])

    def test_registry_list_uses_both_locked_sources_without_refetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'openapi/upstream').mkdir(parents=True)
            (root/'facts').mkdir()
            configurations=[]
            for index,document in enumerate(upstreams()):
                name=f'source-{index}.json'
                (root/'openapi/upstream'/name).write_text(json.dumps(document))
                configurations.append({'file':name,'url':document['info']['x-aisa-source']['url']})
            (root/'openapi/registry.yaml').write_text(yaml.safe_dump({'auto_register':True,'providers':{'alpha':{'upstream':configurations}}}))
            (root/'facts/category.json').write_text(json.dumps({'apis':[{'id':'alpha'}]}))
            (root/'facts/alpha.json').write_text(json.dumps(selected_facts()))
            (root/'docs.json').write_text(json.dumps({'navigation':{'languages':[]}}))
            with patch('pull_openapi.import_source',side_effect=AssertionError('locked source fetched')):
                changes,summary=stage(root,root/'facts','unused')
            self.assertEqual(summary['alpha']['operations'],1)
            self.assertEqual(summary['alpha']['pending'],0)
            self.assertTrue(changes)
