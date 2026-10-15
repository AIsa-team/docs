import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from payment_catalog import build_catalog, digest
from probe_payment_discovery import parse_challenge


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.allowlist, self.quotes, self.observed = [], [], []
        for provider, method in [('alpha', 'GET'), ('beta', 'POST')]:
            path = '/apis/v1/' + provider
            op = {'operationId': 'search', 'x-aisa-status': 'enabled', 'x-aisa-capabilities': {'mpp': True, 'mpp_methods': [method]},
                  'x-aisa-upstream-path': '/search', 'x-aisa-revision': {'profile_ref': 'fixed@1', 'customer_pricing_ref': 'price@1', 'plan_policy_version': 'policy'},
                  'x-aisa-pricing': {'cost_contract': 'fixed_success'},
                  'responses': {'200': {'$ref': '#/components/responses/Result'}}}
            if method == 'POST':
                op['requestBody'] = {'required': True, 'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Input'}}}}
            else:
                op['parameters'] = [{'name': 'q', 'in': 'query', 'required': True, 'style': 'form', 'explode': False,
                                     'schema': {'type': 'array', 'items': {'type': 'string', 'enum': ['one', 'two']}, 'default': ['one']}}]
            source = {'paths': {path: {method.lower(): op}}, 'components': {
                'schemas': {'Input': {'type': 'object', 'required': ['q'], 'properties': {'q': {'type': 'string', 'default': provider}}}},
                'responses': {'Result': {'description': 'ok', 'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Input'}}}}}}}
            raw = json.dumps(source).encode()
            (self.root / (provider + '.json')).write_bytes(raw)
            spec = {'provider': provider, 'method': method, 'path': path, 'target': '/search', 'source': provider + '.json', 'source_sha256': digest(raw)}
            self.allowlist.append(spec)
            self.quotes.append({'operation': spec, 'base_micros_usd': 137, 'payg_multiplier_ppm': 1200000, 'price_micros_usd': 165,
                                'profile_sha256': 'profile', 'pricing_sha256': 'pricing', 'profile_ref': 'fixed@1', 'customer_pricing_ref': 'price@1', 'plan_policy_version': 'policy'})
            self.observed.append({'provider': provider, 'method': method, 'path': path, 'source_sha256': digest(raw),
                                  'status': 402, 'observed_at': '2026-10-12T00:00:00Z', 'expires': '2026-10-12T00:05:00Z', 'chain_id': 4217, 'decimals': 6,
                                  'offer': {'method': 'tempo', 'intent': 'charge', 'currency': '0x20C000000000000000000000b9537d11c60E8b50', 'amount': '165', 'description': 'query'}})
        self.plan = json.dumps({'version': 1, 'entries': self.quotes}).encode()
        self.evidence = {'version': 2, 'environment': 'production', 'server': 'https://api.aisa.one',
                         'runtime_plan_sha256': digest(self.plan), 'operations': self.observed}

    def build(self):
        return build_catalog(self.root, self.allowlist, self.evidence, self.plan)

    def test_schema_collisions_and_real_inputs(self):
        doc, report = self.build()
        self.assertEqual(len(report['included']), 2)
        get = doc['paths']['/apis/v1/alpha']['get']
        post = doc['paths']['/apis/v1/beta']['post']
        self.assertNotIn('requestBody', get)
        self.assertFalse(get['parameters'][0]['explode'])
        self.assertEqual(get['parameters'][0]['schema']['default'], ['one'])
        self.assertTrue(post['requestBody']['required'])
        self.assertEqual(post['requestBody']['content']['application/json']['schema']['$ref'], '#/components/schemas/beta_174725b552aa__Input')
        self.assertEqual(doc['components']['schemas']['alpha_0921f3dfaf21__Input']['properties']['q']['default'], 'alpha')
        self.assertEqual(doc['components']['schemas']['beta_174725b552aa__Input']['properties']['q']['default'], 'beta')
        self.assertEqual(post['x-payment-info']['price']['amount'], '0.000165')

    def test_runtime_validated_hidden_target_uses_pinned_plan(self):
        path = self.root / 'alpha.json'
        source = json.loads(path.read_bytes())
        op = source['paths']['/apis/v1/alpha']['get']
        del op['x-aisa-upstream-path']
        op['x-aisa-validation'] = 'runtime'
        raw = json.dumps(source).encode()
        path.write_bytes(raw)
        self.observed[0]['source_sha256'] = digest(raw)
        self.assertEqual(len(self.build()[1]['included']), 2)
        self.quotes[0]['operation'] = dict(self.quotes[0]['operation'], target='/wrong')
        self.plan = json.dumps({'version': 1, 'entries': self.quotes}).encode()
        self.evidence['runtime_plan_sha256'] = digest(self.plan)
        with self.assertRaises(ValueError):
            self.build()

    def test_explicit_schema_blockers_are_reported(self):
        blockers = [{'provider': 'fred', 'method': 'GET', 'path': '/fred',
                     'blocked_reason': 'missing_authoritative_success_response_schema'}]
        _, report = build_catalog(self.root, self.allowlist, self.evidence, self.plan, blockers)
        self.assertEqual(report['providers']['fred'], {'included': 0, 'excluded': 1})
        self.assertEqual(report['excluded'][0]['reason'], blockers[0]['blocked_reason'])

    def test_terms_and_source_fail_closed(self):
        for field, value in [('chain_id', 1), ('decimals', 18), ('status', 200), ('source_sha256', 'changed')]:
            original = self.observed[0][field]
            self.observed[0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.build()
            self.observed[0][field] = original
        self.observed[0]['offer']['amount'] = '164'
        with self.assertRaises(ValueError):
            self.build()

    def test_excluded_and_missing_evidence(self):
        self.observed.pop()
        _, report = self.build()
        self.assertEqual(report['providers']['beta']['included'], 0)
        self.assertEqual(report['excluded'][0]['reason'], 'missing_production_challenge_evidence')
        self.allowlist[0]['provider'] = 'tikhub'
        with self.assertRaises(ValueError):
            self.build()

    def test_staging_not_published(self):
        self.evidence['environment'] = 'staging'
        with self.assertRaises(ValueError):
            self.build()

    def test_disabled_and_method_mismatch(self):
        path = self.root / 'alpha.json'
        raw = json.loads(path.read_bytes())
        raw['paths']['/apis/v1/alpha']['get']['x-aisa-capabilities']['mpp_methods'] = ['POST']
        data = json.dumps(raw).encode(); path.write_bytes(data)
        self.observed[0]['source_sha256'] = digest(data)
        with self.assertRaises(ValueError):
            self.build()


if __name__ == '__main__':
    unittest.main()
