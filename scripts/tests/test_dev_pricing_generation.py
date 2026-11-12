"""All customer price families through the actual dev sync entrypoint."""
import copy
import json
import tempfile
from pathlib import Path
import unittest

import sync_dev_runtime as dev
from test_pricing_generation import (assert_customer_pages, page_snapshot,
                                     pricing_document, seed_old_pages)


class DevPricingGenerationTests(unittest.TestCase):
    def test_acquire_generate_and_regenerate_all_price_families(self):
        document = pricing_document()
        document['info']['x-aisa-document']['facts_hash'] = 'a' * 64
        original = copy.deepcopy(document)
        values = {'/info/openapi.json': {'providers': [{'id': 'prices', 'facts_hash': 'a' * 64}],
                                         'pending_providers': [], 'pending_endpoints': []},
                  '/info/openapi/prices.json': document,
                  '/info/apis/category': {'apis': [{'id': 'prices'}]}}

        def reader(path):
            return json.dumps(values[path]).encode(), {}

        files = dev.acquire(reader)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'openapi').mkdir()
            (root / 'openapi/registry.yaml').write_text('auto_register: true\nproviders: {}\n')
            (root / 'docs.json').write_text(json.dumps({'navigation': {'languages': [
                {'language': lang, 'tabs': [{'tab': tab, 'groups': []}]}
                for lang, tab in [('en', 'API Reference'), ('zh', 'API 参考')]]}}))
            seed_old_pages(root)
            for repeat in range(2):
                outputs, report = dev.generate(root, files)
                self.assertEqual(report['status'], 'generated')
                for name, raw in outputs.items():
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(raw)
                assert_customer_pages(self, root)
                if repeat:
                    self.assertEqual(first, page_snapshot(root))
                first = page_snapshot(root)
            published = json.loads(outputs['openapi/prices.json'])
            for path, item in document['paths'].items():
                self.assertEqual(published['paths'][path]['get']['x-aisa-pricing'], item['get']['x-aisa-pricing'])
        self.assertEqual(document, original)


if __name__ == '__main__':
    unittest.main()
