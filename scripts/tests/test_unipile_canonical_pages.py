"""The first canonical Unipile release must resolve every producer page URL."""
from pathlib import Path
import copy
import json
import shutil
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contract_page_links import page_reference
from runtime_localize_openapi_zh import split_frontmatter
from pull_openapi import generate_pages


class UnipileCanonicalPagesTests(unittest.TestCase):
    def test_projection_keeps_existing_category_and_hides_duplicate_aliases(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as folder:
            view = Path(folder)
            for name in ('docs.json', 'openapi/nav-groups.json', 'openapi/unipile.json',
                         'translations/openapi-nav-zh.json'):
                path = view / name; path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root / name, path)
            for prefix in ('', 'zh/'):
                for name in ('post_unipile-hosted-link', 'post_unipile_apis_v1_unipile_hosted_link'):
                    relative = f'{prefix}api-reference/unipile/{name}.mdx'
                    path = view / relative; path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(root / relative, path)
            def operation(identity):
                return {'operationId': identity, 'summary': identity, 'responses': {'200': {'description': 'OK'}},
                        'x-aisa-docs-url': 'https://aisa.one/docs/api-reference/unipile/' + identity}
            document = {'openapi': '3.1.0', 'info': {'title': 'Unipile (LinkedIn)'},
                        'paths': {'/apis/v1/unipile/hosted/link': {'post': operation('post_unipile_apis_v1_unipile_hosted_link')},
                                  '/apis/v1/unipile/accounts': {'get': operation('get_unipile_accounts')}}}
            original = copy.deepcopy(document)
            changes = {}
            generate_pages(view, 'unipile', document, changes,
                json.loads((view / 'openapi/unipile.json').read_text()),
                decorate_links=False, require_existing_links=True)
            self.assertEqual(document, original)
            docs = json.loads(changes[view / 'docs.json'])
            from api_nav_groups import nav_pages
            for language in docs['navigation']['languages']:
                prefix = 'zh/' if language['language'] == 'zh' else ''
                tab = next(t for t in language['tabs'] if t['tab'] in ('API Reference', 'API 参考'))
                self.assertNotIn('Unipile (LinkedIn)', [g['group'] for g in tab['groups']])
                category = next(g for g in tab['groups'] if g['group'] in ('Social & Media', '社交与媒体'))
                linkedin = next(g for g in category['pages'] if isinstance(g, dict) and g.get('group') == 'LinkedIn')
                accounts = next(g for g in linkedin['pages'] if isinstance(g, dict) and g.get('group') == 'Accounts')
                self.assertIn(prefix + 'api-reference/unipile/get_unipile_accounts', accounts['pages'])
                self.assertIn(prefix + 'api-reference/unipile/post_unipile-hosted-link', accounts['pages'])
                self.assertNotIn(prefix + 'api-reference/unipile/post_unipile_apis_v1_unipile_hosted_link', nav_pages(tab))
                self.assertEqual(len([p for p in nav_pages(tab) if '/unipile/' in p]), 26)

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
