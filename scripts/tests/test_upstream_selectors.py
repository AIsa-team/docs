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

from catalog_fixture import catalog_root
ROOT = catalog_root()


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

    def test_explicit_source_binding_keeps_caller_engine_required(self):
        for index, engine in enumerate(('airbnb', 'ebay_search')):
            source = selected_facts()
            operation(source).pop('x-aisa-upstream-selector')
            path = next(iter(source['paths']))
            binding = {path: upstreams()[index]['info']['x-aisa-source']['url']}
            original = copy.deepcopy(source)
            document, pending = compose(source, upstreams(), source_bindings=binding)
            self.assertEqual(pending, [])
            params = {p['name']: p for p in operation(document)['parameters']}
            self.assertTrue(params['engine']['required'])
            self.assertEqual(params['engine']['schema']['enum'], [engine])
            self.assertNotIn('default', params['engine']['schema'])
            self.assertEqual(params['engine']['example'], engine)
            self.assertNotIn('api_key', params)
            self.assertNotIn('x-aisa-upstream-selector', operation(document))
            self.assertEqual(source, original)
            self.assertEqual(operation(document)['operationId'], operation(source)['operationId'])
            self.assertEqual(operation(document)['x-aisa-pricing'], operation(source)['x-aisa-pricing'])

    def test_source_binding_is_part_of_document_identity(self):
        source = selected_facts()
        operation(source).pop('x-aisa-upstream-selector')
        path = next(iter(source['paths']))
        outputs = [compose(source, upstreams(), source_bindings={path: document['info']['x-aisa-source']['url']})[0] for document in upstreams()]
        self.assertNotEqual(outputs[0]['info']['x-aisa-document']['document_hash'], outputs[1]['info']['x-aisa-document']['document_hash'])

    def test_public_mirror_binding_change_is_explicitly_pending(self):
        import hashlib
        source = selected_facts('youtube')
        path = next(iter(source['paths']))
        mirror = {'operation': {'operationId': 'old_id', 'parameters': []}, 'source': {'kind': 'manual', 'path_space': 'public', 'url': 'https://example.test/source', 'upstream_path_sha256': hashlib.sha256(b'/api/v1/search').hexdigest()}, 'components': {}}
        document, pending = compose(source, upstreams(), public_mirrors={(path, 'get'): mirror})
        self.assertEqual(pending, [])
        operation(source)['x-aisa-upstream-path'] = '/different-binding'
        document, pending = compose(source, upstreams(), public_mirrors={(path, 'get'): mirror})
        self.assertEqual(document['paths'], {})
        self.assertIn('binding changed', pending[0]['reason'])

    def test_source_binding_cannot_override_runtime_path_or_selector(self):
        for mutation in ('path', 'selector', 'query'):
            source = selected_facts('airbnb')
            operation(source).pop('x-aisa-upstream-selector')
            path = next(iter(source['paths']))
            binding = {path: upstreams()[0]['info']['x-aisa-source']['url']}
            if mutation == 'path':
                operation(source)['x-aisa-upstream-path'] = '/not-the-upstream-route'
            elif mutation == 'selector':
                operation(source)['x-aisa-upstream-selector'] = {'in': 'query', 'name': 'engine', 'value': 'ebay_search', 'mode': 'fixed'}
            else:
                operation(source)['x-aisa-query-policy']['request_wins'] = False
            document, pending = compose(source, upstreams(), source_bindings=binding)
            self.assertEqual(document['paths'], {})
            self.assertEqual(len(pending), 1)
            self.assertIn('bound source', pending[0]['reason'])

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

    def test_real_catalog_sources_bind_without_inventing_runtime_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'openapi/upstream').mkdir(parents=True)
            (root/'facts').mkdir()
            registry = yaml.safe_load((ROOT/'openapi/registry.yaml').read_text())
            entry = registry['providers']['youtube']
            entry = {'upstream': entry['upstream']}
            (root/'openapi/registry.yaml').write_text(yaml.safe_dump({'auto_register': True, 'providers': {'youtube': entry}}))
            facts_doc = selected_facts()
            base = copy.deepcopy(operation(facts_doc))
            base.pop('x-aisa-upstream-selector')
            facts_doc['paths'] = {}
            for index, config in enumerate(entry['upstream']):
                document = upstreams()[index]
                (root/'openapi/upstream'/config['file']).write_text(json.dumps(document))
                public_path = config['public_paths'][0]
                op = copy.deepcopy(base)
                op['operationId'] = 'search_' + str(index)
                facts_doc['paths'][public_path] = {'x-aisa-any': op}
            (root/'facts/category.json').write_text(json.dumps({'apis': [{'id': 'youtube'}]}))
            (root/'facts/youtube.json').write_text(json.dumps(facts_doc))
            (root/'docs.json').write_text(json.dumps({'navigation': {'languages': []}}))
            with patch('pull_openapi.import_source', side_effect=AssertionError('locked source fetched')):
                changes, summary = stage(root, root/'facts', 'unused', with_pages=False)
            self.assertEqual(summary['youtube']['operations'], 2)
            self.assertEqual(summary['youtube']['pending'], 0)
            composed = json.loads(changes[root/'openapi/youtube.json'])
            for path, item in composed['paths'].items():
                op = item['get']
                engine = next(p for p in op['parameters'] if p['name'] == 'engine')
                self.assertTrue(engine['required'])
                self.assertNotIn('x-aisa-upstream-selector', op)
