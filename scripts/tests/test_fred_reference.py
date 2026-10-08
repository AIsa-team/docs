import hashlib
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from import_fred_reference import INDEX, import_reference, parse_reference, official_url, reference_identity, response_evidence, Tree, OfficialRedirectHandler
from compose_openapi import compose, digest
from jsonschema import Draft202012Validator, FormatChecker

from catalog_fixture import catalog_root
ROOT = catalog_root()


def reference(extra=''):
    return ('''<div id="content-container"><h1>fred/example</h1><h2>Description</h2><p>Example query.</p>
    <h2>Examples</h2><h4>Request (HTTPS GET)</h4><pre>https://api.stlouisfed.org/fred/example?api_key=demo</pre>
    <h2>Parameters</h2><h3>api_key</h3><ul><li>32 character alpha-numeric lowercase string, required</li></ul>
    <h3>limit</h3><p>Maximum results.</p><ul><li>integer between 1 and 1000, optional, default: 1000</li></ul>
    ''' + extra + '</div>').encode()


class FredReferenceTest(unittest.TestCase):
    def test_date_defaults_are_constants_not_prose(self):
        _, op=parse_reference(reference('<h3>date</h3><ul><li>YYYY-MM-DD formatted string, optional, default: First day of the year</li></ul>'), INDEX+'example.html')
        self.assertNotIn('default',op['parameters'][-1]['schema'])
        for item in self.document()['paths'].values():
            for parameter in item['get']['parameters']:
                schema=parameter['schema']
                if 'default' in schema:
                    Draft202012Validator(schema, format_checker=FormatChecker()).validate(schema['default'])

    def test_structured_constraints_and_authentication(self):
        path, op = parse_reference(reference(), INDEX+'example.html')
        self.assertEqual(path, '/fred/example')
        limit = op['parameters'][1]
        self.assertEqual(limit['schema'], {'type':'integer','minimum':1,'maximum':1000,'default':1000})
        self.assertFalse(limit['required'])
        self.assertTrue(op['parameters'][0]['required'])
        self.assertEqual(op['security'], [{'fred_api_key':[]}])
        self.assertNotIn('content', op['responses']['200'])

    def test_unknown_type_and_requiredness_fail_closed(self):
        for declaration in ('opaque, required', 'string', 'integer greater than 4, required'):
            with self.subTest(declaration=declaration), self.assertRaises(ValueError):
                parse_reference(reference('<h3>future</h3><ul><li>'+declaration+'</li></ul>'), INDEX+'example.html')

    def test_enum_and_explicit_default_without_required_word(self):
        _, op = parse_reference(reference('''<h3>order</h3><ul><li>On of the following strings: 'asc', 'desc'.</li><li>optional, default: asc</li></ul><h3>category</h3><ul><li>integer, default: 0 (root category)</li></ul>'''), INDEX+'example.html')
        self.assertEqual(op['parameters'][2]['schema'], {'type':'string','enum':['asc','desc'],'default':'asc'})
        self.assertEqual(op['parameters'][3]['schema']['default'],0)
        self.assertFalse(op['parameters'][3]['required'])

    def test_nested_official_enum_and_conditional_default(self):
        _, op = parse_reference(reference('''
            <h3>region_type</h3><ul><li>string, required</li>
            <li>One of the following values:<ul><li>state</li><li>country</li></ul></li></ul>
            <h3>order_by</h3><ul><li>One of the following strings: 'search_rank', 'series_id'.</li>
            <li>optional, default: If search_type is 'full_text', the default is 'search_rank'.</li></ul>
            '''), INDEX+'example.html')
        region, order = op['parameters'][-2:]
        self.assertEqual(region['schema'], {'type': 'string', 'enum': ['state', 'country']})
        self.assertTrue(region['required'])
        self.assertNotIn('default', order['schema'])
        self.assertIn("If search_type is 'full_text'", order['description'])

    def test_nested_enum_does_not_guess_values_from_prose(self):
        with self.assertRaisesRegex(ValueError, 'unsupported nested enum'):
            parse_reference(reference('''<h3>region_type</h3><ul><li>string, required</li>
                <li>One of the following values:<ul><li>state (US states)</li></ul></li></ul>'''),
                INDEX+'example.html')

    def test_index_discovers_future_route_and_records_unknown_reference(self):
        index = b'<a href="example.html">fred/example</a><a href="future.html">fred/future</a>'
        future = reference().replace(b'fred/example', b'fred/future').replace(b'integer between 1 and 1000, optional, default: 1000',b'opaque, required')
        content = {INDEX:index, INDEX+'example.html':reference(), INDEX+'future.html':future}
        doc = import_reference('fred', fetcher=content.__getitem__)
        self.assertEqual(list(doc['paths']), ['/fred/example'])
        source = doc['info']['x-aisa-source']
        self.assertEqual(len(source['references']),2)
        self.assertEqual(len(source['pending_references']),1)
        self.assertEqual(source['pending_references'][0]['sha256'], hashlib.sha256(future).hexdigest())
        self.assertEqual(source['kind'],'provider_openapi')

    def test_source_and_method_validation(self):
        for url in ('http://fred.stlouisfed.org/docs/api/fred/', 'https://evil.example/docs/api/fred/', INDEX+'?key=foo'):
            with self.assertRaises(ValueError): official_url(url)
        with self.assertRaises(ValueError): parse_reference(reference().replace(b'HTTPS GET',b'HTTPS POST'), INDEX+'example.html')
        with self.assertRaises(ValueError): parse_reference(reference(), INDEX+'other.html')

    def test_locked_sources_account_for_every_discovered_reference(self):
        source = self.document()['info']['x-aisa-source']
        document=self.document()
        expected=digest({**document,'info':{k:v for k,v in document['info'].items() if k!='x-aisa-source'}})
        self.assertEqual(source['content_hash'],expected)
        self.assertTrue(expected.startswith('sha256:'))
        self.assertEqual(len(source['references']),35)
        self.assertEqual(len(source['pending_references']),3)
        self.assertEqual(len(self.document()['paths']),32)
        self.assertEqual({p['url'] for p in source['pending_references']}, {
            INDEX+'series_search.html', 'https://fred.stlouisfed.org/docs/api/geofred/shapes.html',
            'https://fred.stlouisfed.org/docs/api/geofred/regional_data.html'})
        self.assertEqual({p['reason'] for p in source['pending_references']}, {
            'search_text: required/optional is not stated',
            'shape: required/optional is not stated',
            'frequency: required/optional is not stated'})
        for row in source['references']:
            self.assertRegex(row['sha256'],r'^[0-9a-f]{64}$')
            official_url(row['url'])

    def test_real_composer_strips_provider_key_and_preserves_runtime_identity(self):
        upstream = self.document()
        paths={}
        for index,path in enumerate(upstream['paths']):
            paths['/apis/v1/fred/'+str(index)]={'x-aisa-any':{
                'operationId':'any_fred_'+str(index), 'x-aisa-status':'enabled', 'x-aisa-validation':'provider',
                'x-aisa-upstream-path':path,'x-aisa-query-policy':{'request_wins':True},
                'x-aisa-pricing':{'default_request_estimate_usd':0.00001}, 'responses':{'200':{'description':'Success'}}}}
        facts={'openapi':'3.1.0','info':{'x-aisa-document':{'facts_hash':'fixture'}},'paths':paths}
        document,pending=compose(facts,upstream)
        self.assertEqual(pending,[])
        self.assertEqual(len(document['paths']),32)
        for path,item in document['paths'].items():
            op=item['get']
            self.assertFalse(any(p['name']=='api_key' for p in op.get('parameters',[])))
            self.assertEqual(op['operationId'],paths[path]['x-aisa-any']['operationId'])
            self.assertEqual(op['x-aisa-pricing'],paths[path]['x-aisa-any']['x-aisa-pricing'])

    def test_official_cached_sources_reproduce_locked_operations(self):
        directory=os.environ.get('AISA_FRED_REFERENCE_CACHE')
        if not directory:self.skipTest('set AISA_FRED_REFERENCE_CACHE to downloaded official HTML directory')
        def fetcher(url):
            name='index.html' if url==INDEX else ('geofred_' if '/geofred/' in url else '')+url.rsplit('/',1)[-1]
            return (Path(directory)/name).read_bytes()
        fresh=import_reference('fred',fetcher=fetcher)
        # Current static reference bytes/examples may advance. Request
        # semantics remain compared to the locked baseline without treating
        # that baseline as approval or requiring historical HTML byte identity.
        self.assertEqual(set(fresh['paths']),set(self.document()['paths']))
        for path, item in fresh['paths'].items():
            for key in ('parameters','security','externalDocs'):
                self.assertEqual(item['get'][key],self.document()['paths'][path]['get'][key])
            for media in item['get']['responses']['200'].get('content',{}).values():
                self.assertNotIn('schema',media)
        evidence=fresh['info']['x-aisa-source']['operation_identity_evidence']
        self.assertEqual(len(evidence),35)
        self.assertEqual(sum(x['request_status']=='pending' for x in evidence),3)
        self.assertEqual({x['method'] for x in evidence},{'GET'})
        declarations=[field for row in evidence for field in row['response_evidence']['field_declarations']]
        self.assertEqual(len(declarations),24)
        self.assertEqual(sum(bool(row['response_evidence']['field_declarations']) for row in evidence),17)
        self.assertEqual({row['attribute'] for row in declarations},{'link','notes'})
        self.assertTrue(all(row['required'] is False and row['media_type']=='text/xml' for row in declarations))
        facts=json.loads((ROOT/'facts/fred.json').read_text())
        public,pending=compose(facts,fresh)
        self.assertEqual(len(pending),3)
        self.assertEqual(len(public['info']['x-aisa-document']['response_pending']),32)
        self.assertTrue(any('examples' in media for item in public['paths'].values()
                            for op in item.values() for response in op.get('responses',{}).values()
                            for media in response.get('content',{}).values()))


    def test_redirect_is_rejected_before_following_business_or_other_host(self):
        from urllib.request import Request
        handler=OfficialRedirectHandler()
        for destination in ('https://api.stlouisfed.org/fred/series', 'https://evil.example/docs/api/fred/'):
            with self.subTest(url=destination),self.assertRaises(ValueError):
                handler.redirect_request(Request(INDEX),None,302,'Found',{},destination)

    def test_identity_survives_missing_parameter_declaration_without_partial_operation(self):
        raw=reference('<h3>search_text</h3><p>Words to search for.</p>')
        index=b'<a href="example.html">fred/example</a>'
        document=import_reference('fred',fetcher={INDEX:index,INDEX+'example.html':raw}.__getitem__)
        self.assertEqual(document['paths'],{})
        evidence=document['info']['x-aisa-source']['operation_identity_evidence']
        self.assertEqual(evidence[0]['path'],'/fred/example')
        self.assertEqual(evidence[0]['method'],'GET')
        self.assertEqual(evidence[0]['request_status'],'pending')
        self.assertEqual(evidence[0]['request_reason'],'search_text: required/optional is not stated')
        self.assertNotIn('operation_id',evidence[0])

    def test_geofred_path_requires_exact_official_reference_url(self):
        raw=reference().replace(b'fred/example',b'geofred/series/data')
        good='https://fred.stlouisfed.org/docs/api/geofred/series_data.html'
        self.assertEqual(reference_identity(raw,good)[2],'/geofred/series/data')
        for bad in (INDEX+'example.html','https://fred.stlouisfed.org/docs/api/geofred/series_group.html'):
            with self.subTest(url=bad),self.assertRaisesRegex(ValueError,'GeoFRED'):
                reference_identity(raw,bad)

    def test_official_response_examples_keep_strings_and_never_infer_schema(self):
        raw=b'''<div id="content-container"><h2>Examples</h2><h3>JSON</h3>
        <h4>Request (HTTPS GET)</h4><pre>https://api.stlouisfed.org/fred/example?api_key=demo</pre>
        <h4>Response</h4><pre>{"note":"two  spaces", "count":2, "items":[]}</pre>
        <h2>Parameters</h2><p>The HTTP Content-Type is application/json.</p></div>'''
        evidence=response_evidence(Tree(raw).root)
        self.assertEqual(set(evidence['content']),{'application/json'})
        media=evidence['content']['application/json']
        self.assertEqual(media['examples']['official_1']['value']['note'],'two  spaces')
        self.assertNotIn('schema',media)
        self.assertFalse(evidence['schema_inferred'])
        self.assertEqual(evidence['schema_status'],'not_declared_in_reference')

    def test_malformed_duplicate_and_nonfinite_response_examples_remain_pending(self):
        for sample in ('{"x":1,"x":2}','{"x":NaN}','{"x": ...}'):
            raw=('<div><h3>JSON</h3><h4>Response</h4><pre>'+sample+'</pre></div>').encode()
            with self.subTest(sample=sample):
                evidence=response_evidence(Tree(raw).root)
                self.assertEqual(evidence['content'],{})
                self.assertEqual(evidence['pending'][0]['reason'],'official JSON response example is not valid JSON')
                self.assertRegex(evidence['pending'][0]['example_sha256'],r'^[a-f0-9]{64}$')

    def test_only_explicit_response_xml_attribute_optionality_is_retained(self):
        raw=b'''<div><h3>XML</h3><h4>Response</h4>
        <pre>&lt;release notes="sample" other="1"/&gt;</pre>
        <p>The release tag's link and notes attributes are optional.</p>
        <h3>JSON</h3><h4>Response</h4><pre>{"release":{"notes":"sample"}}</pre>
        <p>The series tag's notes attribute is optional.</p>
        <h2>Parameters</h2><p>The source tag's link attribute is optional.</p></div>'''
        evidence=response_evidence(Tree(raw).root)
        self.assertEqual([(row['element'],row['attribute'],row['required'])
                          for row in evidence['field_declarations']],
                         [('release','link',False),('release','notes',False)])
        self.assertEqual({row['media_type'] for row in evidence['field_declarations']},{'text/xml'})
        self.assertTrue(all('type' not in row for row in evidence['field_declarations']))
        self.assertNotIn('schema',evidence['content']['text/xml'])
        self.assertFalse(evidence['schema_inferred'])

    def test_xml_example_dtd_is_never_loaded(self):
        raw=b'<div><h3>XML</h3><h4>Response</h4><pre>&lt;!DOCTYPE x SYSTEM "https://example.com/private"&gt;&lt;x/&gt;</pre></div>'
        evidence=response_evidence(Tree(raw).root)
        self.assertEqual(evidence['content'],{})
        self.assertEqual(evidence['pending'][0]['reason'],'XML declarations are unsupported')

    def test_examples_do_not_silently_satisfy_composer_payload_schema_gate(self):
        source=self.document()
        source=json.loads(json.dumps(source))
        path=next(iter(source['paths']))
        content=b'<div><h3>JSON</h3><h4>Response</h4><pre>{"items":[]}</pre></div>'
        evidence=response_evidence(Tree(content).root)
        source['paths'][path]['get']['responses']['200']['content']=evidence['content']
        source['paths'][path]['get']['x-aisa-response-evidence']=evidence
        facts={'openapi':'3.1.0','info':{'x-aisa-document':{'facts_hash':'fixture'}},'paths':{
            '/apis/v1/fred/example':{'x-aisa-any':{'operationId':'fixture_preserved','x-aisa-status':'enabled',
                'x-aisa-passthrough':True,'x-aisa-validation':'provider','x-aisa-upstream-path':path,
                'x-aisa-query-policy':{'request_wins':True},'responses':{'200':{'description':'Success'}}}}}}
        document,pending=compose(facts,source)
        self.assertEqual(pending,[])
        self.assertEqual(document['paths']['/apis/v1/fred/example']['get']['operationId'],'fixture_preserved')
        self.assertEqual(len(document['info']['x-aisa-document']['response_pending']),1)
        response=document['paths']['/apis/v1/fred/example']['get']['responses']['200']
        self.assertEqual(response['content']['application/json']['examples']['official_1']['value'],{'items':[]})
        self.assertNotIn('schema',response['content']['application/json'])

    @staticmethod
    def document():
        return json.loads((ROOT/'openapi/upstream/fred-official.json').read_text())


if __name__=='__main__': unittest.main()
