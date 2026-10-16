import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import generate_payment_discovery as module
from payment_fixture import FIXTURES, install_payment_fixture

ROOT = Path(__file__).resolve().parents[2]


class PaymentDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.evidence = json.loads((FIXTURES / 'evidence-v2.json').read_text())
        self.raw = (FIXTURES / 'source-v3.json').read_bytes()
        self.source = json.loads(self.raw)
        self.path = self.evidence['operations'][0]['path']

    def build(self, source=None, evidence=None):
        source = self.source if source is None else source
        return module.build(source, evidence or self.evidence, json.dumps(source).encode())

    def rebind(self, source):
        evidence = copy.deepcopy(self.evidence)
        evidence['source_semantic_binding'] = module.projection_binding(source, evidence)
        return evidence

    def test_catalog_preserves_contract_and_removes_account_auth(self):
        doc = self.build()
        self.assertEqual(len(doc['paths']), 3)
        self.assertNotIn('security', doc)
        self.assertNotIn('securitySchemes', doc['components'])
        for path, item in doc['paths'].items():
            op = item['get']
            self.assertEqual(op['parameters'], self.source['paths'][path]['get']['parameters'])
            self.assertEqual(op['responses']['200'], self.source['paths'][path]['get']['responses']['200'])
            self.assertIn('402', op['responses'])
            self.assertNotIn('x-aisa-pricing', op)
            self.assertEqual(op['x-payment-info']['offers'][0]['amount'], '440')
            self.assertEqual(op['x-payment-info']['price'], {
                'mode': 'fixed', 'currency': 'USD', 'amount': '0.00044'})
            self.assertEqual(op['x-payment-info']['protocols'][0]['mpp']['method'], 'tempo')
        self.assertTrue(doc['info']['x-guidance'])
        self.assertEqual(doc['info']['contact']['email'], 'developer@aisa.one')
        for item in doc['paths'].values():
            self.assertNotIn('requestBody', item['get'])

    def test_invalid_usd_price_is_rejected(self):
        path = self.evidence['operations'][0]['path']
        for price in [None, 'NaN', 'Infinity', -1]:
            self.source['paths'][path]['get']['x-aisa-pricing']['default_request_estimate_usd'] = price
            with self.subTest(price=price), self.assertRaises(ValueError):
                module.build(self.source, self.evidence, self.raw)

    def test_legacy_frozen_evidence_retains_exact_byte_and_semantic_binding(self):
        evidence = json.loads((FIXTURES / 'evidence-v1.json').read_text())
        raw = (FIXTURES / 'source-v2.json').read_bytes()
        source = json.loads(raw)
        module.build(source, evidence, raw)
        evidence.pop('source_semantic_binding')
        module.build(source, evidence, raw)
        with self.assertRaises(ValueError):
            module.build(source, evidence, raw + b' ')

    def test_actual_generation_transition_preserves_observations_and_catalog(self):
        before = json.loads((FIXTURES / 'evidence-v1.json').read_text())
        raw = (FIXTURES / 'source-v2.json').read_bytes()
        old = module.build(json.loads(raw), before, raw)
        # This is the exact old-pass/new-fail transition behind a51129d.
        with self.assertRaisesRegex(ValueError, 'Source changed'):
            module.build(self.source, before, self.raw)
        self.assertEqual(self.evidence['operations'], before['operations'])
        self.assertEqual(self.evidence['source_sha256'], before['source_sha256'])
        self.assertEqual(self.build(), old)

    def test_unrelated_changes_do_not_need_new_manual_evidence(self):
        reviewed = {row['path'] for row in self.evidence['operations']}
        unrelated = next(p for p, item in self.source['paths'].items() if p not in reviewed and 'get' in item)
        mutations = [
            lambda s: s['info']['x-aisa-document'].update(composer_version=999, generator_version=999,
                                                        document_hash='changed', facts_hash='changed'),
            lambda s: s['paths'][unrelated]['get'].update(description='Unrelated edit'),
            lambda s: s['components']['schemas'].update(UnusedSchema={'type': 'string'}),
            lambda s: s['paths'].update({'/new-unrelated': {'get': {'operationId': 'new'}}}),
            lambda s: s['paths'][self.path]['get']['x-aisa-capabilities'].update(mpp_methods=['GET']),
        ]
        expected = self.build()
        for mutate in mutations:
            source = copy.deepcopy(self.source); mutate(source)
            with self.subTest(mutation=mutate):
                self.assertEqual(self.build(source), expected)

    def test_relevant_changes_require_review_with_field_diagnostic(self):
        changes = [
            ('servers', lambda s: s.update(servers=[{'url': 'https://invalid.test'}])),
            ('security', lambda s: s.update(security=[])),
            ('mpp_method_enabled', lambda s: s['paths'][self.path]['get']['x-aisa-capabilities'].update(mpp_methods=['POST'])),
            ('x-aisa-status', lambda s: s['paths'][self.path]['get'].update({'x-aisa-status': 'disabled'})),
            ('x-aisa-pricing', lambda s: s['paths'][self.path]['get']['x-aisa-pricing'].update(unit_rate=99)),
            ('x-aisa-revision', lambda s: s['paths'][self.path]['get']['x-aisa-revision'].update(profile_ref='different')),
            ('x-aisa-upstream-path', lambda s: s['paths'][self.path]['get'].update({'x-aisa-upstream-path': '/other'})),
            ('parameters', lambda s: s['paths'][self.path]['get'].update(parameters=[])),
            ('responses', lambda s: s['paths'][self.path]['get'].update(responses={})),
        ]
        for field, mutate in changes:
            source = copy.deepcopy(self.source); mutate(source)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'Reviewed payment contract changed:.*' + field):
                self.build(source)
        source = copy.deepcopy(self.source); source['paths'].pop(self.path)
        with self.assertRaisesRegex(ValueError, 'Reviewed operation missing'):
            self.build(source)

    def test_method_restriction_cannot_be_bypassed_by_reviewing_new_hash(self):
        for methods in ([], ['POST'], None, 'GET', ['GET', 1], ['GET', 'INVALID']):
            source = copy.deepcopy(self.source)
            source['paths'][self.path]['get']['x-aisa-capabilities']['mpp_methods'] = methods
            with self.subTest(methods=methods), self.assertRaisesRegex(ValueError, 'MPP support for GET'):
                self.build(source, self.rebind(source))
        source = copy.deepcopy(self.source)
        source['paths'][self.path]['get']['x-aisa-capabilities']['mpp'] = False
        with self.assertRaisesRegex(ValueError, 'MPP support'):
            self.build(source, self.rebind(source))
        source = copy.deepcopy(self.source); source['paths'][self.path]['get']['x-aisa-status'] = 'disabled'
        with self.assertRaisesRegex(ValueError, 'not enabled'):
            self.build(source, self.rebind(source))

    def test_selected_schema_closure_and_effective_auth_are_bound(self):
        projection = module.contract_projection(self.source, self.evidence)
        selected = projection['operations']['GET ' + self.path]
        schema = next(iter(selected['components']['schemas']))
        source = copy.deepcopy(self.source); source['components']['schemas'][schema]['type'] = 'null'
        with self.assertRaisesRegex(ValueError, 'Reviewed payment contract changed:.*components'):
            self.build(source)
        source = copy.deepcopy(self.source)
        name = next(iter(selected['security_schemes']))
        source['components']['securitySchemes'][name]['scheme'] = 'basic'
        with self.assertRaisesRegex(ValueError, 'Reviewed payment contract changed:.*security_schemes'):
            self.build(source)
        for ref in ('#/components/schemas/Missing', 'https://external.invalid/schema'):
            source = copy.deepcopy(self.source)
            source['paths'][self.path]['get']['responses']['200']['content']['application/json']['schema'] = {'$ref': ref}
            with self.subTest(ref=ref), self.assertRaisesRegex(ValueError, 'reference'):
                self.build(source)

    def test_invalid_bindings_and_object_byte_mismatch_fail_closed(self):
        for binding in (None, {}, {'algorithm': 'unknown', 'sha256': 'a' * 64},
                        dict(self.evidence['source_semantic_binding'], sha256='a' * 64),
                        dict(self.evidence['source_semantic_binding'], excluded_paths=['paths'])):
            evidence = copy.deepcopy(self.evidence); evidence['source_semantic_binding'] = binding
            with self.subTest(binding=binding), self.assertRaises(ValueError):
                self.build(evidence=evidence)
        source = copy.deepcopy(self.source); source['info']['title'] = 'not in bytes'
        with self.assertRaisesRegex(ValueError, 'does not match'):
            module.build(source, self.evidence, self.raw)

    def test_invalid_observed_offer_rejected_without_refresh(self):
        for field, value in [('amount', '0.00044'), ('currency', ''), ('method', 'x402')]:
            evidence = copy.deepcopy(self.evidence); evidence['operations'][0]['offer'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.build(evidence=evidence)

    def test_candidate_recovery_and_repeat_preserve_last_good_until_valid(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); install_payment_fixture(root)
            output = root / 'discovery/openapi.json'; original = output.read_bytes()
            provider = root / self.evidence['source']; source = json.loads(provider.read_text())
            source['paths'][self.path]['get']['x-aisa-capabilities']['mpp_methods'] = ['POST']
            provider.write_text(json.dumps(source))
            with self.assertRaises(ValueError): module.candidate(root)
            self.assertEqual(output.read_bytes(), original)
            provider.write_bytes(self.raw)
            self.assertEqual(module.verify_payment_catalog(root)['status'], 'passed')
            self.assertEqual(module.candidate(root), module.candidate(root))

    def test_workflow_checks_and_stages_payment_after_generation_before_export(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/pull-openapi.yml').read_text())
        steps = workflow['jobs']['compose']['steps']
        index = {step.get('name'): i for i, step in enumerate(steps)}
        self.assertLess(index['Consolidate generated contracts'], index['Generate payment discovery from the same staged contracts'])
        self.assertLess(index['Generate payment discovery from the same staged contracts'], index['Check formal artifact readiness before publication'])
        self.assertLess(index['Check formal artifact readiness before publication'], index['Export the passed same-commit publication pointer'])
        stage = next(s['run'] for s in steps if s.get('id') == 'prepare')
        for file in module.PAYMENT_FILES:
            self.assertIn(file, stage)


if __name__ == '__main__':
    unittest.main()
