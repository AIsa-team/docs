"""Canonical producer URLs and existing reader URLs must resolve together."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api_nav_groups import nav_pages
from pull_openapi import generate_pages


class CanonicalPageAliasesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.alias = 'api-reference/unipile/get_unipile-me'
        self.identity = 'get_unipile_linkedin_me'
        self.canonical = 'api-reference/unipile/' + self.identity
        self.route = '/apis/v1/unipile/linkedin/me'
        self.document = {
            'openapi': '3.1.0', 'info': {'title': 'Unipile (LinkedIn)'},
            'paths': {self.route: {'get': {
                'operationId': self.identity, 'summary': 'Own Profile',
                'x-aisa-docs-url': 'https://aisa.one/docs/' + self.canonical,
                'responses': {'200': {'description': 'OK'}},
            }}},
        }
        for prefix in ('', 'zh/'):
            page = self.root / (prefix + self.alias + '.mdx')
            page.parent.mkdir(parents=True)
            page.write_text('---\ntitle: "Own Profile"\n'
                f'x-aisa-operation-id: "{self.identity}"\n'
                f'openapi: "openapi/{prefix}unipile.json GET {self.route}"\n'
                '---\n\nKeep this account guidance.\n\n```bash\n'
                'curl "https://api.aisa.one/example" \\\n  -H "Authorization: Bearer $AISA_API_KEY"\n```\n')
        (self.root / 'openapi').mkdir()
        (self.root / 'openapi/unipile.json').write_text(json.dumps(self.document))
        (self.root / 'openapi/nav-groups.json').write_text(json.dumps({
            'categories': [{'name': 'Social & Media', 'groups': ['LinkedIn']}],
            'pages': [{'prefix': 'api-reference/unipile/',
                       'category': 'Social & Media', 'group': 'LinkedIn'}],
        }))
        self.docs = {'navigation': {'languages': [
            {'language': language, 'tabs': [{'tab': label, 'groups': [
                {'group': 'Social & Media', 'pages': [
                    {'group': 'LinkedIn', 'pages': [prefix + self.alias]}]}]}]}
            for language, label, prefix in (('en', 'API Reference', ''), ('zh', 'API 参考', 'zh/'))
        ]}}
        (self.root / 'docs.json').write_text(json.dumps(self.docs))

    def project(self):
        changes = {}
        generate_pages(self.root, 'unipile', self.document, changes,
            copy.deepcopy(self.document), decorate_links=False, require_existing_links=True)
        return changes

    def test_first_canonical_projection_preserves_aliases_prose_and_visible_navigation(self):
        original = copy.deepcopy(self.document)
        changes = self.project()
        self.assertEqual(self.document, original)
        for prefix in ('', 'zh/'):
            page = self.root / (prefix + self.canonical + '.mdx')
            self.assertIn(page, changes)
            self.assertIn('Keep this account guidance.', changes[page])
            self.assertIn('Authorization: Bearer $AISA_API_KEY', changes[page])
            self.assertTrue((self.root / (prefix + self.alias + '.mdx')).is_file())
        docs = json.loads(changes.get(self.root / 'docs.json', json.dumps(self.docs)))
        for language in docs['navigation']['languages']:
            prefix = 'zh/' if language['language'] == 'zh' else ''
            pages = nav_pages(language['tabs'][0])
            self.assertEqual(pages.count(prefix + self.alias), 1)
            self.assertNotIn(prefix + self.canonical, pages)

    def test_conflicting_existing_canonical_identity_is_rejected(self):
        page = self.root / (self.canonical + '.mdx')
        page.write_text('---\nx-aisa-operation-id: "different_operation"\n'
                        'openapi: "openapi/unipile.json GET /different"\n---\n')
        with self.assertRaisesRegex(ValueError, 'Canonical page binding'):
            self.project()

    def test_unrelated_producer_url_is_rejected_without_mutating_input(self):
        operation = self.document['paths'][self.route]['get']
        operation['x-aisa-docs-url'] = 'https://aisa.one/docs/api-reference/unipile/wrong'
        original = copy.deepcopy(self.document)
        with self.assertRaisesRegex(ValueError, 'Canonical page binding'):
            self.project()
        self.assertEqual(self.document, original)

    def test_new_account_operation_stays_in_existing_bilingual_linkedin_section(self):
        repository = Path(__file__).resolve().parents[2]
        (self.root / 'openapi/nav-groups.json').write_bytes(
            (repository / 'openapi/nav-groups.json').read_bytes())
        (self.root / 'translations').mkdir()
        (self.root / 'translations/openapi-nav-zh.json').write_text(json.dumps({
            'Social & Media': '社交与媒体', 'LinkedIn': 'LinkedIn'}))
        for language in self.docs['navigation']['languages']:
            linkedin = language['tabs'][0]['groups'][0]['pages'][0]
            linkedin['pages'] = [{'group': 'Accounts', 'pages': linkedin['pages']}]
        (self.root / 'docs.json').write_text(json.dumps(self.docs))
        identity = 'get_unipile_accounts'
        page = 'api-reference/unipile/' + identity
        self.document['paths']['/apis/v1/unipile/accounts'] = {'get': {
            'operationId': identity, 'summary': 'Account list', 'x-aisa-status': 'disabled',
            'x-aisa-docs-url': 'https://aisa.one/docs/' + page,
            'responses': {'200': {'description': 'OK'}},
        }}
        changes = self.project()
        docs = json.loads(changes[self.root / 'docs.json'])
        for language in docs['navigation']['languages']:
            prefix = 'zh/' if language['language'] == 'zh' else ''
            groups = language['tabs'][0]['groups']
            self.assertEqual(len(groups), 1)
            linkedin = groups[0]['pages'][0]
            self.assertEqual(linkedin['group'], 'LinkedIn')
            accounts = linkedin['pages'][0]
            self.assertEqual(accounts['group'], 'Accounts')
            self.assertIn(prefix + page, accounts['pages'])

    def test_price_cleanup_preserves_code_fence_boundaries_in_canonical_alias(self):
        for prefix in ('', 'zh/'):
            path = self.root / (prefix + self.alias + '.mdx')
            path.write_text(path.read_text() + '\nReference price: $0.01 USD per successful request.\n')
        changes = self.project()
        for prefix in ('', 'zh/'):
            text = changes[self.root / (prefix + self.canonical + '.mdx')]
            self.assertIn('Authorization: Bearer $AISA_API_KEY"\n```\n', text)
            self.assertNotIn('Reference price: $0.01', text)


if __name__ == '__main__':
    unittest.main()
