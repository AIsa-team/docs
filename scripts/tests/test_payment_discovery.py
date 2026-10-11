import copy
import hashlib
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('discovery', ROOT / 'scripts/generate_payment_discovery.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PaymentDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.evidence = json.loads((ROOT / 'discovery/payment-evidence.json').read_text())
        self.raw = (ROOT / self.evidence['source']).read_bytes()
        self.source = json.loads(self.raw)

    def test_catalog_preserves_contract_and_removes_account_auth(self):
        doc = module.build(self.source, self.evidence, self.raw)
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

    def test_legacy_evidence_retains_exact_byte_binding(self):
        evidence = copy.deepcopy(self.evidence)
        evidence.pop('source_semantic_binding')
        module.build(self.source, evidence, self.raw)
        with self.assertRaises(ValueError):
            module.build(self.source, evidence, self.raw + b' ')

    def test_metadata_only_regeneration_preserves_catalog(self):
        expected = module.build(self.source, self.evidence, self.raw)
        source = copy.deepcopy(self.source)
        source['info']['x-aisa-document']['composer_version'] = 999
        source['info']['x-aisa-document']['document_hash'] = 'regenerated'
        raw = json.dumps(source, sort_keys=True).encode()
        self.assertEqual(module.build(source, self.evidence, raw), expected)
        self.assertEqual(module.build(self.source, self.evidence, self.raw + b' '), expected)

    def test_real_source_changes_require_review(self):
        path = self.evidence['operations'][0]['path']
        changes = [
            ('servers', lambda s: s.update(servers=[{'url': 'https://invalid.test'}])),
            ('routes', lambda s: s['paths'].pop(path)),
            ('auth', lambda s: s.update(security=[])),
            ('capabilities', lambda s: s['paths'][path]['get']['x-aisa-capabilities'].update(mpp=False)),
            ('pricing', lambda s: s['paths'][path]['get']['x-aisa-pricing'].update(unit_rate=99)),
            ('request', lambda s: s['paths'][path]['get'].update(parameters=[])),
            ('response', lambda s: s['paths'][path]['get'].update(responses={})),
            ('components', lambda s: s.update(components={})),
            ('facts_hash', lambda s: s['info']['x-aisa-document'].update(facts_hash='changed')),
            ('nested_document_hash', lambda s: s['paths'][path]['get'].update(document_hash='changed')),
        ]
        for name, mutate in changes:
            with self.subTest(name=name):
                source = copy.deepcopy(self.source)
                mutate(source)
                raw = json.dumps(source).encode()
                with self.assertRaisesRegex(ValueError, 'Source changed'):
                    module.build(source, self.evidence, raw)

    def test_invalid_semantic_bindings_fail_closed_even_when_raw_matches(self):
        for binding in [
            None, {}, {'algorithm': 'unknown', 'sha256': 'a' * 64},
            {'algorithm': module.SEMANTIC_BINDING_ALGORITHM, 'sha256': 'bad'},
            {'algorithm': module.SEMANTIC_BINDING_ALGORITHM, 'sha256': 'a' * 64},
            dict(self.evidence['source_semantic_binding'], excluded_paths=['paths']),
        ]:
            evidence = copy.deepcopy(self.evidence)
            evidence['source_semantic_binding'] = binding
            with self.subTest(binding=binding), self.assertRaises(ValueError):
                module.build(self.source, evidence, self.raw)

    def test_source_object_must_match_bytes(self):
        source = copy.deepcopy(self.source)
        source['info']['title'] = 'not in bytes'
        with self.assertRaisesRegex(ValueError, 'does not match'):
            module.build(source, self.evidence, self.raw)

    def test_invalid_evidence_is_rejected(self):
        for field, value in [('amount', '0.00044'), ('currency', ''), ('method', 'x402')]:
            evidence = copy.deepcopy(self.evidence)
            evidence['operations'][0]['offer'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                module.build(self.source, evidence, self.raw)

    def test_disabled_mpp_is_not_published(self):
        path = self.evidence['operations'][0]['path']
        self.source['paths'][path]['get']['x-aisa-capabilities']['mpp'] = False
        raw = json.dumps(self.source).encode()
        evidence = copy.deepcopy(self.evidence)
        evidence['source_semantic_binding']['sha256'] = module.source_semantic_sha256(self.source)
        with self.assertRaisesRegex(ValueError, 'does not advertise MPP'):
            module.build(self.source, evidence, raw)

    def test_unresolved_response_ref_fails(self):
        self.source['components']['schemas'] = {}
        raw = json.dumps(self.source).encode()
        evidence = copy.deepcopy(self.evidence)
        evidence.pop('source_semantic_binding')
        evidence['source_sha256'] = hashlib.sha256(raw).hexdigest()
        with self.assertRaises(KeyError):
            module.build(self.source, evidence, raw)


if __name__ == '__main__':
    unittest.main()
