"""Synthetic next-projection contract tests; immutable W0 inputs stay untouched."""
import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
sys.path[:0] = [str(Path(__file__).resolve().parents[1])]
from compose_openapi import compose
from runtime_registry import public_mirror_index
from test_runtime_contracts import facts, operation

PATH_HASH = hashlib.sha256(b'/provider/test').hexdigest()
ORIGIN_HASH = hashlib.sha256(b'https://provider.example').hexdigest()


def response_source(method='post', response_only=True):
    return {'openapi':'3.1.0','info':{'x-aisa-source':{
        'kind':'manual','url':'https://reference.example/response','fetched_at':'2026-10-08',
        'content_hash':'sha256:response-fixture','converter':'synthetic-next-projection@1',
        'path_space':'public','response_only':response_only,'upstream_path_sha256':PATH_HASH,'upstream_origin_sha256':ORIGIN_HASH}},
        'paths':{'/apis/v1/similarweb/test':{method:{
            # Deliberately adversarial request metadata must not leak into runtime.
            'operationId':'wrong_identity','requestBody':{'content':{'application/json':{'schema':{'type':'integer'}}}},
            'parameters':[{'name':'wrong','in':'query','schema':{'type':'string'}}],
            'responses':{'200':{'description':'Typed response','content':{'application/json':{
                'schema':{'type':'object','properties':{'value':{'type':'string'}},'required':['value']}}}}}}}}}


def index(*documents):
    with tempfile.TemporaryDirectory() as directory:
        return public_mirror_index(Path(directory), {str(i)+'.json':doc for i,doc in enumerate(documents)})


def descriptor(runtime):
    operation(runtime)['x-aisa-response-passthrough']=True
    operation(runtime)['x-aisa-response-upstream-path-sha256']=PATH_HASH
    operation(runtime)['x-aisa-response-upstream-origin-sha256']=ORIGIN_HASH
    return runtime


class IndependentResponseTests(unittest.TestCase):
    def test_runtime_get_and_post_enrich_only_response_from_bound_source(self):
        for method in ('get','post'):
            with self.subTest(method=method):
                runtime=descriptor(facts('runtime',method))
                operation(runtime)['requestBody']={'content':{'application/json':{'schema':{'type':'string'}}}}
                original=copy.deepcopy(operation(runtime))
                doc,pending=compose(runtime,public_mirrors=index(response_source(method)))
                self.assertEqual(pending,[])
                actual=operation(doc)
                self.assertNotIn('x-aisa-response-pending',actual)
                for key,value in original.items():
                    if key!='responses':self.assertEqual(actual[key],value)
                self.assertNotIn('x-aisa-source',actual)
                self.assertEqual(actual['x-aisa-response-source']['source']['content_hash'],'sha256:response-fixture')
                self.assertEqual(compose(runtime,public_mirrors=index(response_source(method)),previous=doc),(doc,[]))

    def test_absent_invalid_changed_hash_flag_and_method_keep_response_pending(self):
        variants=[{}, {'x-aisa-response-upstream-path-sha256':PATH_HASH},
            {'x-aisa-response-passthrough':True},
            {'x-aisa-response-passthrough':True,'x-aisa-response-upstream-path-sha256':'bad'},
            {'x-aisa-response-passthrough':True,'x-aisa-response-upstream-path-sha256':'0'*64},
            {'x-aisa-response-passthrough':1,'x-aisa-response-upstream-path-sha256':PATH_HASH},
            {'x-aisa-response-passthrough':False}]
        for extra in variants:
            runtime=facts();operation(runtime).update(extra)
            doc,pending=compose(runtime,public_mirrors=index(response_source()))
            self.assertEqual(pending,[])
            self.assertIn('x-aisa-response-pending',operation(doc))
            self.assertEqual(operation(doc)['parameters'],operation(runtime)['parameters'])
        doc,pending=compose(descriptor(facts()),public_mirrors=index(response_source('get')))
        self.assertEqual(pending,[]);self.assertIn('x-aisa-response-pending',operation(doc))

    def test_response_source_change_changes_document_hash(self):
        runtime=descriptor(facts());source=response_source()
        first,_=compose(runtime,public_mirrors=index(source))
        changed=copy.deepcopy(source)
        changed['paths']['/apis/v1/similarweb/test']['post']['responses']['200']['content']['application/json']['schema']['properties']['value']['type']='integer'
        changed['info']['x-aisa-source']['content_hash']='sha256:changed-response-fixture'
        second,_=compose(runtime,public_mirrors=index(changed))
        self.assertNotEqual(first['info']['x-aisa-document']['document_hash'],second['info']['x-aisa-document']['document_hash'])
        self.assertEqual(compose(runtime,public_mirrors=index(changed),previous=second),(second,[]))

    def test_invalid_upstream_response_only_marker_is_not_request_authority(self):
        for marker in (1,'true'):
            source=response_source();source['info']['x-aisa-source']['response_only']=marker
            source['info']['x-aisa-source'].pop('path_space')
            source['paths']={'/provider/test':next(iter(source['paths'].values()))}
            with self.assertRaisesRegex(ValueError,'response_only marker must be boolean'):
                compose(facts('provider','x-aisa-any'),source)

    def test_declared_status_and_explicit_no_content_are_preserved(self):
        for status,response in [('201',{'description':'Created','content':{'application/json':{'schema':{'type':'string'}}}}),
                                ('200',{'description':'Explicitly empty','x-aisa-no-content':True})]:
            source=response_source()
            source['paths']['/apis/v1/similarweb/test']['post']['responses']={status:response}
            doc,pending=compose(descriptor(facts()),public_mirrors=index(source))
            self.assertEqual(pending,[]);self.assertNotIn('x-aisa-response-pending',operation(doc))
            self.assertEqual(set(operation(doc)['responses']),{status})
            if status=='200':self.assertTrue(operation(doc)['responses']['200']['x-aisa-no-content'])

    def test_origin_change_missing_origin_and_source_origin_mismatch_fail_closed(self):
        for change in ('runtime_changed','runtime_missing','source_changed'):
            runtime=descriptor(facts());source=response_source()
            if change=='runtime_changed':operation(runtime)['x-aisa-response-upstream-origin-sha256']='0'*64
            elif change=='runtime_missing':operation(runtime).pop('x-aisa-response-upstream-origin-sha256')
            else:source['info']['x-aisa-source']['upstream_origin_sha256']='0'*64
            doc,pending=compose(runtime,public_mirrors=index(source))
            self.assertEqual(pending,[])
            self.assertIn('x-aisa-response-pending',operation(doc))
            self.assertNotIn('content',operation(doc)['responses']['200'])

    def test_response_only_never_discovers_any_method_or_completes_request(self):
        source=response_source()
        for validation,method in [('runtime','x-aisa-any'),('provider','x-aisa-any'),('provider','post'),('mixed','post')]:
            runtime=descriptor(facts(validation,method))
            doc,pending=compose(runtime,source,public_mirrors=index(source))
            self.assertTrue(pending,(validation,method))
            self.assertEqual(doc['paths'],{})
        # Also exclude an upstream-shaped response-only source from method discovery.
        upstream=copy.deepcopy(source);upstream['paths']={'/provider/test':next(iter(source['paths'].values()))}
        doc,pending=compose(descriptor(facts('provider','x-aisa-any')),upstream)
        self.assertEqual(doc['paths'],{});self.assertTrue(pending)

    def test_existing_any_request_contract_and_response_have_separate_sources(self):
        request=response_source(response_only=False)
        request['info']['x-aisa-source'].update(url='https://reference.example/request',content_hash='sha256:request-fixture')
        request_op=next(iter(request['paths'].values()))['post']
        request_op['responses']={'200':{'description':'unknown'}}
        request_op['requestBody']={'content':{'application/json':{'schema':{'type':'string'}}}}
        runtime=descriptor(facts('runtime','x-aisa-any'))
        operation(runtime)['requestBody']=copy.deepcopy(request_op['requestBody'])
        baseline,_=compose(runtime,public_mirrors=index(request))
        for docs in [(request,response_source()),(response_source(),request)]:
            doc,pending=compose(runtime,public_mirrors=index(*docs))
            self.assertEqual(pending,[])
            for key,value in operation(baseline).items():
                if key not in {'responses','x-aisa-response-pending','x-aisa-response-source'}:
                    self.assertEqual(operation(doc)[key],value)
            self.assertNotIn('x-aisa-response-pending',operation(doc))
            self.assertEqual(operation(doc)['x-aisa-response-source']['source']['content_hash'],'sha256:response-fixture')

    def test_ambiguous_response_sources_do_not_erase_valid_request(self):
        source=response_source();other=copy.deepcopy(source)
        other['info']['x-aisa-source']['url']='https://reference.example/other'
        doc,pending=compose(descriptor(facts()),public_mirrors=index(source,other))
        self.assertEqual(pending,[])
        self.assertIn('ambiguous',operation(doc)['x-aisa-response-pending']['reason'])
        self.assertNotIn('content',operation(doc)['responses']['200'])

    def test_transformed_denial_blocks_legacy_source_and_previous_but_keeps_runtime_schema(self):
        source=response_source(response_only=False)
        runtime=facts('provider');operation(runtime)['x-aisa-passthrough']=True
        operation(runtime)['x-aisa-query-policy']={'request_wins':True}
        published,pending=compose(runtime,public_mirrors=index(source))
        self.assertEqual(pending,[]);self.assertNotIn('x-aisa-response-pending',operation(published))
        operation(runtime)['x-aisa-response-passthrough']=False
        doc,pending=compose(runtime,public_mirrors=index(source),previous=published)
        self.assertEqual(pending,[]);self.assertIn('x-aisa-response-pending',operation(doc))
        self.assertNotIn('content',operation(doc)['responses']['200'])
        own={'type':'string'}
        operation(runtime)['responses']['200']['content']={'application/json':{'schema':own}}
        doc,pending=compose(runtime,public_mirrors=index(source),previous=published)
        self.assertEqual(pending,[]);self.assertNotIn('x-aisa-response-pending',operation(doc))
        self.assertEqual(operation(doc)['responses']['200']['content']['application/json']['schema'],own)

    def test_changed_descriptor_cannot_reuse_previous_response(self):
        runtime=descriptor(facts());source=response_source()
        published,_=compose(runtime,public_mirrors=index(source))
        operation(runtime)['x-aisa-response-upstream-path-sha256']='0'*64
        doc,pending=compose(runtime,public_mirrors=index(source),previous=published)
        self.assertEqual(pending,[]);self.assertIn('x-aisa-response-pending',operation(doc))
        self.assertNotIn('content',operation(doc)['responses']['200'])

    def test_index_rejects_unbound_or_invalid_response_only_marker(self):
        for field,value in [('response_only',1),('upstream_path_sha256','bad')]:
            source=response_source();source['info']['x-aisa-source'][field]=value
            with self.assertRaises(ValueError):index(source)


if __name__=='__main__':unittest.main()
