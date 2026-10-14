import copy
import unittest
from playground_examples import add_get_code_sample, add_body_code_sample

class PlaygroundExamplesTests(unittest.TestCase):
    def test_get_complete_named_scenario_replaces_bad_default(self):
        op = {'parameters': [
            {'name': 'q', 'in': 'query', 'required': True, 'examples': {'default': {'value': 'a & b'}, 'minimal': {'value': 'other'}}, 'schema': {'type': 'string'}},
            {'name': 'limit', 'in': 'query', 'examples': {'default': {'value': 1}}, 'schema': {'type': 'integer', 'default': 100}},
            {'name': 'country', 'in': 'query', 'examples': {'default': {'value': 'ww'}}, 'schema': {'type': 'string'}}]}
        add_get_code_sample(op, '/search', [{'url': 'https://api.aisa.one'}])
        source = op['x-codeSamples'][0]['source']
        self.assertIn('q=a+%26+b&limit=1&country=ww', source)
        self.assertNotIn('other', source)
        self.assertEqual(op['parameters'][1]['schema']['default'], 100)
        self.assertEqual(op['x-codeSamples'][0]['lang'], 'text')
        self.assertIn(chr(92) + '\n', source)
        add_get_code_sample(op, '/search', [{'url': 'https://api.aisa.one'}])
        self.assertEqual(len(op['x-codeSamples']), 1)

    def test_unknown_required_and_complex_serialization_are_not_invented(self):
        for schema, examples in [({'type': 'string'}, {}), ({'type': 'array'}, {'default': {'value': ['one','two']}})]:
            op = {'parameters': [{'name': 'q', 'in': 'query', 'required': True, 'schema': schema, 'examples': examples}]}
            add_get_code_sample(op, '/search', [{'url': 'https://api.aisa.one'}])
            self.assertNotIn('x-codeSamples', op)

    def test_unsupported_scenarios_keep_existing_samples(self):
        from copy import deepcopy
        base = {'parameters': [{'name': 'q', 'in': 'query', 'required': True, 'example': 'q', 'schema': {'type': 'string'}}], 'x-codeSamples': [{'lang': 'Bash', 'source': 'maintained'}]}
        for extra in [ {'requestBody': {'required': True}}, {'parameters': [dict(base['parameters'][0], content={'application/json':{}})]}, {'parameters': base['parameters'] + [{'name': 'X-Mode', 'in': 'header', 'examples': {'default': {'value': 'yes'}}}]} ]:
            op=deepcopy(base); op.update(extra); original=deepcopy(op); add_get_code_sample(op, '/search', [{'url':'https://api.aisa.one'}]); self.assertEqual(op,original)
        op=deepcopy(base); op['parameters'][0]['style']='simple'; add_get_code_sample(op,'/search',[{'url':'https://api.aisa.one'}]); self.assertEqual(len(op['x-codeSamples']),1)
        op=deepcopy(base); add_get_code_sample(op,'/search',[{'url':'https://api.aisa.one'}]); self.assertEqual(op['x-codeSamples'][1],base['x-codeSamples'][0])

    def test_body_sample_preserves_complete_instance_without_optional_placeholders(self):
        schema={'type':'object','properties':{'query':{'type':'string','example':'known'},'optional':{'type':'array','items':{'type':'string'}},'nested':{'type':'object','properties':{'enabled':{'oneOf':[{'type':'boolean'},{'type':'string'}],'example':False}},'required':['enabled']}},'required':['query','nested'], 'example':{'query':'known','nested':{'enabled':False}}}
        op={'requestBody':{'content':{'application/json':{'schema':schema}}}}
        add_body_code_sample(op,'post','/search',[{'url':'https://api.aisa.one'}])
        import shlex, json
        argv=shlex.split(op['x-codeSamples'][0]['source'].split('\n',1)[1].replace(chr(92)+'\n',''))
        body=json.loads(argv[argv.index('--data')+1]);self.assertEqual(body,{'query':'known','nested':{'enabled':False}})
        self.assertNotIn('<string>',op['x-codeSamples'][0]['source'])
        op['requestBody']['content']['application/json']['examples']={'default':{'value':{'query':'complete','optional':['real']}}}
        add_body_code_sample(op,'post','/search',[{'url':'https://api.aisa.one'}]);self.assertIn('complete',op['x-codeSamples'][0]['source']);self.assertNotIn('nested',op['x-codeSamples'][0]['source'])

    def test_exa_simple_mode_survives_normal_page_regeneration(self):
        import tempfile
        from pathlib import Path
        import json
        from pull_openapi import generate_pages
        root_source = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'docs.json').write_text(json.dumps({'navigation': {}}))
            for prefix in ('', 'zh/'):
                page = 'api-reference/search/post_exa-search.mdx'
                target = root / (prefix + page)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text((root_source / (prefix + page)).read_text())
            operation = {'operationId': 'post_exa_search', 'summary': 'Search', 'responses': {'200': {'description': 'OK'}}}
            doc = {'info': {'x-aisa-document': {'document_hash': 'example'}}, 'paths': {'/apis/v1/exa/search': {'post': operation}}}
            changes = {}
            generate_pages(root, 'exa', doc, changes, doc,
                page_references=[('openapi/exa.json', '', '/apis/v1/exa/search', 'post', 'api-reference/search/post_exa-search')])
            for prefix in ('', 'zh/'):
                target = root / (prefix + 'api-reference/search/post_exa-search.mdx')
                text = changes.get(target, target.read_text())
                self.assertIn('playground: simple', text.split('---')[1])
                self.assertIn('<Note>', text)

if __name__ == '__main__': unittest.main()
