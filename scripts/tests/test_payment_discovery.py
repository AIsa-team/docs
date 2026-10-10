import copy
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

    def test_changed_source_requires_review(self):
        with self.assertRaises(ValueError):
            module.build(self.source, self.evidence, self.raw + b' ')

    def test_invalid_evidence_is_rejected(self):
        for field, value in [('amount', '0.00044'), ('currency', ''), ('method', 'x402')]:
            evidence = copy.deepcopy(self.evidence)
            evidence['operations'][0]['offer'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                module.build(self.source, evidence, self.raw)

    def test_disabled_mpp_is_not_published(self):
        path = self.evidence['operations'][0]['path']
        self.source['paths'][path]['get']['x-aisa-capabilities']['mpp'] = False
        with self.assertRaises(ValueError):
            module.build(self.source, self.evidence, self.raw)

    def test_unresolved_response_ref_fails(self):
        self.source['components']['schemas'] = {}
        with self.assertRaises(KeyError):
            module.build(self.source, self.evidence, self.raw)


if __name__ == '__main__':
    unittest.main()
