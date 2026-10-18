import copy
import hashlib
import json
from pathlib import Path
import unittest

from compose_openapi import compose
from audit_request_input_forwarding import audit_provider
from upstream_auth_transports import server_auth_headers, ORIGIN, SCHEMES

ROOT = Path(__file__).resolve().parents[2]


def fixture(path='/submit', scheme='polymarket_relayer_api_key', any_method=False):
    method = {'/submit': 'post', '/transactions': 'get', '/relayer/api/keys': 'get'}[path]
    sha = lambda text: hashlib.sha256(text.encode()).hexdigest()
    selector = json.dumps({'auth_location': 'header', 'credential_scheme': scheme,
                           'origin': ORIGIN}, sort_keys=True, separators=(',', ':'))
    descriptor = {'schema_version': 1, 'driver': 'polymarket_relayer_v1',
                  'scheme': scheme, 'credential_source': 'provider_configuration',
                  'upstream_method': method.upper(), 'upstream_origin_sha256': sha(ORIGIN),
                  'upstream_path_sha256': sha(path), 'public_selector_sha256': sha(selector)}
    source = json.loads((ROOT / 'openapi/upstream/polymarket-relayer.json').read_text())
    op = {'operationId': 'relayer_fixture', 'x-aisa-validation': 'provider',
          'x-aisa-status': 'enabled', 'x-aisa-passthrough': True,
          'x-aisa-upstream-path': path, 'x-aisa-upstream-auth': descriptor,
          'responses': {'200': {'description': 'Success'}}}
    public = '/apis/v1/polymarket-relayer' + path
    facts = {'openapi': '3.1.0', 'info': {'x-aisa-provider': 'polymarket-relayer',
             'x-aisa-document': {'facts_hash': 'fixture'}}, 'paths': {
             public: {'x-aisa-any' if any_method else method: op}}}
    return facts, source, op, public, method


class UpstreamAuthTransportsTests(unittest.TestCase):
    def test_actual_locked_source_both_server_schemes_compose_and_audit(self):
        for path in ('/submit', '/transactions'):
            for scheme in SCHEMES:
                for any_method in (False, True):
                    with self.subTest(path=path, scheme=scheme, any_method=any_method):
                        facts, source, runtime, public, method = fixture(path, scheme, any_method)
                        original = copy.deepcopy(source)
                        out, pending = compose(facts, source)
                        self.assertEqual(pending, [])
                        emitted = out['paths'][public][method]
                        self.assertEqual(emitted['x-aisa-upstream-auth'], runtime['x-aisa-upstream-auth'])
                        self.assertFalse(any(p.get('in') == 'header' for p in emitted.get('parameters', [])))
                        self.assertEqual(emitted['x-aisa-validation'], 'provider')
                        self.assertEqual(source, original)
                        rows = audit_provider('polymarket-relayer', facts, source, {}, {}, include_headers=True)
                        self.assertEqual([(r['status'], r['missing_header_inputs']) for r in rows], [('passed', [])])

    def test_absent_descriptor_and_2278_remain_blocked(self):
        for path in ('/submit', '/transactions', '/relayer/api/keys'):
            facts, source, runtime, public, method = fixture(path)
            del runtime['x-aisa-upstream-auth']
            _, pending = compose(facts, source)
            self.assertIn('source header parameters are not forwarded', pending[0]['reason'])
            rows = audit_provider('polymarket-relayer', facts, source, {}, {}, include_headers=True)
            self.assertEqual(rows[0]['status'], 'blocked')
        facts, source, runtime, public, method = fixture('/relayer/api/keys', any_method=True)
        _, pending = compose(facts, source)
        self.assertIn('server-auth transport', pending[0]['reason'])
        self.assertEqual(audit_provider('polymarket-relayer', facts, source, {}, {}, True)[0]['status'], 'source_unverified')

    def test_unknown_business_header_and_query_still_block(self):
        for location, name in [('header', 'X-Business-Account'), ('query', 'account')]:
            facts, source, runtime, public, method = fixture()
            source['paths']['/submit']['post']['parameters'].append({'in': location, 'name': name, 'schema': {'type': 'string'}})
            _, pending = compose(facts, source)
            self.assertIn(name, pending[0]['reason'])
            row = audit_provider('polymarket-relayer', facts, source, {}, {}, True)[0]
            self.assertEqual(row['status'], 'blocked')
            self.assertIn(name, row['missing_header_inputs' if location == 'header' else 'missing_query_inputs'])

    def test_real_business_forwarding_retained_and_auth_query_not_exempt(self):
        facts, source, runtime, public, method = fixture()
        business = {'in': 'header', 'name': 'X-Business-Account', 'schema': {'type': 'string'}}
        source['paths']['/submit']['post']['parameters'].append(business)
        runtime['x-aisa-caller-headers'] = ['X-Business-Account']
        output, pending = compose(facts, source)
        self.assertEqual(pending, [])
        self.assertIn(business, output['paths'][public][method]['parameters'])
        self.assertEqual(audit_provider('polymarket-relayer', facts, source, {}, {}, True)[0]['status'], 'passed')
        source['paths']['/submit']['post']['parameters'].append({'in': 'query', 'name': 'RELAYER_API_KEY', 'schema': {'type': 'string'}})
        self.assertIn('RELAYER_API_KEY', compose(facts, source)[1][0]['reason'])
        row = audit_provider('polymarket-relayer', facts, source, {}, {}, True)[0]
        self.assertEqual(row['missing_query_inputs'], ['RELAYER_API_KEY'])

    def test_closed_binding_mutations_rejected_by_both_consumers(self):
        changes = {
            'runtime_validation': lambda f,s,r: r.update({'x-aisa-validation': 'runtime'}),
            'unknown': lambda f,s,r: r['x-aisa-upstream-auth'].update(auth_ready=True),
            'null': lambda f,s,r: r['x-aisa-upstream-auth'].update(scheme=None),
            'bool': lambda f,s,r: r['x-aisa-upstream-auth'].update(schema_version=True),
            'fraction': lambda f,s,r: r['x-aisa-upstream-auth'].update(schema_version=1.0),
            'stale_selector': lambda f,s,r: r['x-aisa-upstream-auth'].update(scheme='polymarket_builder_hmac'),
            'unknown_scheme': lambda f,s,r: r['x-aisa-upstream-auth'].update(scheme='bearer'),
            'provider': lambda f,s,r: f['info'].update({'x-aisa-provider': 'other'}),
            'path': lambda f,s,r: r.update({'x-aisa-upstream-path': '/transactions'}),
            'method': lambda f,s,r: r['x-aisa-upstream-auth'].update(upstream_method='GET'),
            'origin': lambda f,s,r: s['servers'][0].update(url='https://other.invalid'),
            'operation_origin': lambda f,s,r: s['paths']['/submit']['post'].update(servers=[{'url': 'https://other.invalid'}]),
            'source': lambda f,s,r: s['info']['x-aisa-source'].update(url='https://other.invalid/spec'),
            'incomplete_selected_group': lambda f,s,r: s['paths']['/submit']['post']['parameters'].pop(),
            'required_unused_group': lambda f,s,r: s['paths']['/submit']['post']['parameters'][0].update(required=True),
            'selector_type': lambda f,s,r: r['x-aisa-upstream-auth'].update(public_selector_sha256=[]),
        }
        for name, change in changes.items():
            with self.subTest(name=name):
                facts, source, runtime, public, method = fixture()
                change(facts, source, runtime)
                _, pending = compose(facts, source)
                self.assertTrue(pending)
                self.assertEqual(audit_provider(facts['info']['x-aisa-provider'], facts, source, {}, {}, True)[0]['status'], 'source_unverified')

    def test_source_selected_group_does_not_hide_required_alternative(self):
        facts, source, runtime, _, method = fixture('/transactions', 'polymarket_builder_hmac')
        source['paths']['/transactions']['get']['parameters'][-1]['required'] = True
        with self.assertRaises(ValueError):
            server_auth_headers(runtime, 'polymarket-relayer', method, source, source['paths']['/transactions']['get'])


if __name__ == '__main__':
    unittest.main()
