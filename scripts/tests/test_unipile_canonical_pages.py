"""The first canonical Unipile release must resolve every producer page URL."""
from pathlib import Path
import sys
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contract_page_links import page_reference
from runtime_localize_openapi_zh import split_frontmatter


class UnipileCanonicalPagesTests(unittest.TestCase):
    def test_first_publication_urls_resolve_in_both_languages(self):
        root = Path(__file__).resolve().parents[2]
        aliases = [path for path in sorted((root / 'api-reference/unipile').glob('*-*.mdx'))
                   if page_reference(path.read_text())]
        self.assertGreaterEqual(len(aliases), 24)
        for alias in aliases:
            header, _ = split_frontmatter(alias.read_text())
            identity = yaml.safe_load(header)['x-aisa-operation-id']
            _, method, route = page_reference(alias.read_text())
            # Unipile is new to the frozen historical presentation inventory;
            # the canonical producer therefore uses its default ID-based URL.
            for prefix in ('', 'zh/'):
                page = root / f'{prefix}api-reference/unipile/{identity}.mdx'
                with self.subTest(identity=identity, language=prefix or 'en'):
                    self.assertTrue(page.is_file(), str(page.relative_to(root)))
                    text = page.read_text()
                    self.assertEqual(page_reference(text),
                        (f'openapi/{prefix}unipile.json', method, route))
                    header, _ = split_frontmatter(text)
                    self.assertEqual(yaml.safe_load(header)['x-aisa-operation-id'], identity)

    def test_managed_account_guide_does_not_reference_provider_only_schema(self):
        root = Path(__file__).resolve().parents[2]
        for prefix in ('', 'zh/'):
            text = (root / f'{prefix}api-reference/unipile/get_unipile-me-accounts.mdx').read_text()
            header, _ = split_frontmatter(text)
            values = yaml.safe_load(header)
            self.assertNotIn('openapi', values)
            self.assertNotIn('x-aisa-operation-id', values)
            self.assertIn('GET /apis/v1/unipile/me/accounts', text)
            self.assertIn('Authorization: Bearer YOUR_API_KEY', text)


if __name__ == '__main__':
    unittest.main()
