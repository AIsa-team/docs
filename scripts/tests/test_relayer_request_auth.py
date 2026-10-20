import copy
import hashlib
import unittest
from test_upstream_auth_transports import fixture
from compose_openapi import compose, VERSION
from audit_request_input_forwarding import audit_provider
from upstream_auth_transports import ORIGIN, REQUEST_PUBLIC_PATH, REQUEST_PATH, REQUEST_HEADERS


def caller_fixture():
    facts, source, runtime, public, method = fixture(REQUEST_PATH)
    del runtime['x-aisa-upstream-auth']
    facts['paths'][REQUEST_PUBLIC_PATH] = facts['paths'].pop(public)
    public = REQUEST_PUBLIC_PATH
    runtime['x-aisa-request-auth'] = dict(schema_version=1,
        driver='polymarket_relayer_key_list_caller_v1', scheme='polymarket_relayer_api_key',
        credential_source='caller_request_headers', upstream_method='GET',
        upstream_origin_sha256=hashlib.sha256(ORIGIN.encode()).hexdigest(),
        upstream_path_sha256=hashlib.sha256(REQUEST_PATH.encode()).hexdigest(),
        required_headers=list(REQUEST_HEADERS))
    runtime['parameters'] = [
        dict(name='RELAYER_API_KEY', **{'in': 'header'}, required=True,
             schema=dict(type='string', minLength=1, maxLength=4096)),
        dict(name='RELAYER_API_KEY_ADDRESS', **{'in': 'header'}, required=True,
             schema=dict(type='string', pattern='^0x[0-9a-fA-F]{40}$'))]
    return facts, source, runtime, public, method


class RelayerRequestAuthTests(unittest.TestCase):
    def test_exact_caller_pair_kept_required_and_platform_security_unchanged(self):
        f,s,r,p,m=caller_fixture()
        f['security']=[{'bearerAuth':[]}]
        f['components']={'securitySchemes':{'bearerAuth':{'type':'http','scheme':'bearer'}}}
        original=copy.deepcopy(s)
        out,pending=compose(f,s)
        self.assertEqual(pending,[])
        op=out['paths'][p]['get']
        self.assertEqual(op['operationId'],r['operationId'])
        self.assertEqual(op['x-aisa-runtime-operation'],dict(operation_id=r['operationId'],method='GET',path=p))
        self.assertEqual({v['name'] for v in op['parameters']},set(REQUEST_HEADERS))
        self.assertTrue(all(v['required'] is True for v in op['parameters']))
        self.assertEqual(out['security'],f['security'])
        self.assertEqual(s,original)
        rows=audit_provider('polymarket-relayer',f,s,{}, {},True)
        self.assertEqual([(v['status'],v['missing_header_inputs']) for v in rows],[('passed',[])])
        self.assertEqual(VERSION,'26')

    def test_closed_descriptor_and_complete_required_pair_mutations_fail(self):
        changes={
          'extra':lambda f,s,r:r['x-aisa-request-auth'].update(auth_ready=True),
          'null':lambda f,s,r:r['x-aisa-request-auth'].update(required_headers=None),
          'wrongheader':lambda f,s,r:r['x-aisa-request-auth'].update(required_headers=['Authorization']),
          'wrongscheme':lambda f,s,r:r['x-aisa-request-auth'].update(scheme='polymarket_builder_hmac'),
          'providercredential':lambda f,s,r:r['x-aisa-request-auth'].update(credential_source='provider_configuration'),
          'bool':lambda f,s,r:r['x-aisa-request-auth'].update(schema_version=True),
          'float':lambda f,s,r:r['x-aisa-request-auth'].update(schema_version=1.0),
          'origin':lambda f,s,r:r['x-aisa-request-auth'].update(upstream_origin_sha256='a'*64),
          'upstream':lambda f,s,r:r.update({'x-aisa-upstream-path':'/transactions'}),
          'source':lambda f,s,r:s['info']['x-aisa-source'].update(url='https://untrusted.invalid'),
          'server':lambda f,s,r:s['servers'][0].update(url='https://untrusted.invalid'),
          'missingrequired':lambda f,s,r:r['parameters'][0].update(required=False),
          'address':lambda f,s,r:r['parameters'][1]['schema'].update(pattern='.*'),
          'missingmirror':lambda f,s,r:s['paths'][REQUEST_PATH]['get']['parameters'].pop(),
        }
        for name,change in changes.items():
            with self.subTest(name=name):
                f,s,r,p,m=caller_fixture();change(f,s,r)
                self.assertTrue(compose(f,s)[1])
                self.assertEqual(audit_provider('polymarket-relayer',f,s,{}, {},True)[0]['status'],'source_unverified')

    def test_unknown_business_header_query_and_other_routes_not_exempt(self):
        for location,name in [('header','X-Account'),('query','account')]:
            f,s,r,p,m=caller_fixture()
            s['paths'][REQUEST_PATH]['get']['parameters'].append(dict(name=name, **{'in':location},schema={'type':'string'}))
            self.assertIn(name,compose(f,s)[1][0]['reason'])
            self.assertEqual(audit_provider('polymarket-relayer',f,s,{}, {},True)[0]['status'],'blocked')
        for path in ['/submit','/transactions']:
            f,s,r,p,m=caller_fixture();r['x-aisa-upstream-path']=path
            self.assertTrue(compose(f,s)[1])
        f,s,r,p,m=caller_fixture();f['info']['x-aisa-provider']='other'
        self.assertTrue(compose(f,s)[1])
        f,s,r,p,m=caller_fixture();f['paths']['/apis/v1/other']=f['paths'].pop(p)
        self.assertTrue(compose(f,s)[1])

    def test_absent_descriptor_remains_missing_forwarding_not_business_whitelist(self):
        f,s,r,p,m=caller_fixture();del r['x-aisa-request-auth'];r['parameters']=[]
        self.assertIn('source header parameters',compose(f,s)[1][0]['reason'])
        self.assertEqual(audit_provider('polymarket-relayer',f,s,{}, {},True)[0]['status'],'blocked')

    def test_runtime_owned_body_does_not_skip_credential_source_checks(self):
        f,s,r,p,m=caller_fixture();r['x-aisa-validation']='runtime'
        out,pending=compose(f,s);self.assertEqual(pending,[])
        self.assertEqual(out['paths'][p]['get']['parameters'],r['parameters'])
        r['x-aisa-request-auth']['credential_source']='provider_configuration'
        self.assertTrue(compose(f,s)[1])
        self.assertEqual(audit_provider('polymarket-relayer',f,s,{}, {},True)[0]['status'],'source_unverified')

    def test_duplicate_raw_declarations_reject_before_parameter_merge(self):
        f,s,r,p,m=caller_fixture()
        r['parameters'].append(copy.deepcopy(r['parameters'][0]))
        with self.assertRaisesRegex(ValueError,'duplicate caller-auth'):
            compose(f,s)
        with self.assertRaisesRegex(ValueError,'duplicate caller-auth'):
            audit_provider('polymarket-relayer',f,s,{}, {},True)

    def test_actual_published_key_listing_identity_is_retained(self):
        import json
        from pathlib import Path
        from pull_openapi import assert_identities
        f,s,r,p,m=caller_fixture()
        previous=json.loads((Path(__file__).resolve().parents[2]/'openapi/polymarket-relayer.json').read_text())
        old=previous['paths'][p]['get']
        r['operationId']=old['operationId']
        out,pending=compose(f,s,previous=previous)
        self.assertEqual(pending,[])
        previous['paths']={p:{'get':old}}
        assert_identities(previous,out)
        self.assertEqual(out['paths'][p]['get']['operationId'],old['operationId'])
        broken=copy.deepcopy(out);broken['paths'][p]['get']['operationId']='changed_identity'
        with self.assertRaisesRegex(ValueError,'published identity changed'):
            assert_identities(previous,broken)
