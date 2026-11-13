"""Keep the oversized download outside Mint without hiding API page sources."""
import json
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]


class MintStaticExclusionTests(unittest.TestCase):
    def test_only_aggregate_is_excluded_and_canonical_redirect_is_retained(self):
        patterns = [line.strip() for line in (ROOT / '.mintignore').read_text().splitlines()
                    if line.strip() and not line.lstrip().startswith('#')]
        self.assertEqual(patterns, ['/openapi.yaml', '/openapi/openapi.json'])
        redirects = json.loads((ROOT / 'docs.json').read_text())['redirects']
        for source in ('/openapi.json', '/openapi/openapi.json'):
            self.assertIn({'source': source, 'destination': 'https://aisa.one/openapi.json', 'permanent': True}, redirects)
        self.assertTrue((ROOT / 'openapi.yaml').is_file())
        config = json.loads((ROOT / 'docs.json').read_text())
        self.assertEqual([item for item in config['redirects']
                          if item['source'] == '/openapi.yaml'], [{
            'source': '/openapi.yaml',
            'destination': 'https://aisa.one/openapi.yaml',
            'permanent': True,
        }])
        self.assertNotIn('openapi.yaml', json.dumps(config['navigation']))

    def test_all_bilingual_api_page_sources_remain_available(self):
        for directory in ('api-reference', 'zh/api-reference'):
            count = 0
            for page in (ROOT / directory).rglob('*.mdx'):
                text = page.read_text()
                if not text.startswith('---\n'):
                    continue
                frontmatter = yaml.safe_load(text.split('---', 2)[1]) or {}
                reference = frontmatter.get('openapi')
                if not isinstance(reference, str):
                    continue
                source = reference.split()[0]
                self.assertNotEqual(source.lstrip('/'), 'openapi.yaml', str(page))
                self.assertTrue((ROOT / source).is_file(), str(page))
                count += 1
            self.assertGreater(count, 0, directory)


if __name__ == '__main__':
    unittest.main()
