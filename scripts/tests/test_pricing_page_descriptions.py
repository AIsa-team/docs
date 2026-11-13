"""Exercise Mintlify-bound descriptions through the real canonical publisher."""
import copy
import json
import re
import unittest
from unittest.mock import patch

import yaml

import canonical_import
from pricing_prose import DESCRIPTION_HASH, refresh_page_description
import test_full_registry
import test_pricing_generation as fixtures
from runtime_localize_openapi_zh import split_frontmatter

OLD_REFERENCE_NOTE = ('<Warning>This existing API reference is preserved. Its parameter details have not yet '
                      'been verified for the currently available endpoint.</Warning>')


class PublishedPricingDescriptionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_full_registry.FullRegistryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.root
        fixtures.seed_old_pages(self.root)
        self.document = fixtures.pricing_document()
        self.raw = json.dumps(self.document).encode()
        (self.root / 'openapi/prices.json').write_bytes(self.raw)
        (self.root / 'llms.txt').write_text('Discovery\n')
        self.metadata = {'registry': {'providers': {'prices': {}}},
                         'coverage': {'providers': {'prices': []}},
                         'pending': {'providers': {'prices': []}}}
        # Published native pages have no description override. Mintlify falls
        # back to operation.description, including an old compiler's markers.
        for page in self.root.rglob('*.mdx'):
            page.write_text(re.sub(r'^description:.*\n', '', page.read_text(), flags=re.M))

    def project(self):
        outputs = canonical_import.project_surfaces(
            self.root, {'prices': self.raw}, self.raw, self.metadata)
        self.assertEqual(outputs['openapi/prices.json'], self.raw)
        self.assertEqual(outputs['openapi/openapi.json'], self.raw)
        for name, raw in outputs.items():
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        return outputs

    def test_old_canonical_descriptions_do_not_leak_into_page_metadata(self):
        for repeat in range(2):
            self.project()
            for name in fixtures.pricing_cases():
                for prefix in ('', 'zh/'):
                    with self.subTest(case=name, language=prefix):
                        page = self.root / f'{prefix}api-reference/prices/{name}.mdx'
                        header, _ = split_frontmatter(page.read_text())
                        metadata = yaml.safe_load(header)
                        description = metadata.get('description') or self.document['paths'][
                            '/apis/v1/prices/' + name]['get']['description']
                        self.assertNotIn('aisa-pricing:', description)
                        self.assertNotIn('provider_credit', description)
                        self.assertIn('Find records.', description)
            if repeat:
                self.assertEqual(first, fixtures.page_snapshot(self.root))
            first = fixtures.page_snapshot(self.root)

    def test_internal_pricing_pointer_is_replaced_by_the_customer_condition(self):
        pointer = 'Paid: see x-aisa-pricing; charged only when the call succeeds.'
        self.document['paths']['/apis/v1/prices/free']['get']['description'] = 'Find records. ' + pointer
        self.raw = json.dumps(self.document).encode()
        english = self.root / 'api-reference/prices/free.mdx'
        english.write_text(english.read_text() + '\n' + pointer + '\n\n```text\n' + pointer + '\n```\n')
        self.project()
        header, body = split_frontmatter(english.read_text())
        self.assertNotIn('x-aisa-pricing', yaml.safe_load(header)['description'])
        self.assertIn('Charged only when the call succeeds.', yaml.safe_load(header)['description'])
        self.assertEqual(body.count(pointer), 1)  # Literal examples remain intact.
        self.assertIn('Charged only when the call succeeds.', body)

    def test_reference_pages_are_refreshed_in_the_canonical_publisher(self):
        operation = copy.deepcopy(self.document['paths']['/apis/v1/prices/free']['get'])
        operation.update(operationId='sendMessage', summary='Send a message',
                         description='Send a message.\n\n' + fixtures.OLD_SUMMARY)
        operation['x-aisa-pricing'] = {'kind': 'fixed_request', 'customer_micros_usd': 100,
                                      'variants': {'twitter': {'kind': 'fixed_request',
                                                               'customer_micros_usd': 15000}}}
        operation.pop('x-aisa-docs-url', None)
        account = {'operationId': 'accountUsage', 'summary': 'Account usage',
                   'responses': {'200': {'description': 'Usage records'}}}
        document = {'openapi': '3.1.0', 'info': {'title': 'Reference', 'version': '1'},
                    'paths': {'/messages': {'post': operation}, '/usage': {'get': account}}}
        raw = json.dumps(document).encode()
        for prefix in ('', 'zh/'):
            spec = self.root / f'reference-contracts/{prefix}reference.json'
            spec.parent.mkdir(parents=True, exist_ok=True)
            spec.write_bytes(raw)
            for name, method in (('messages', 'POST'), ('usage', 'GET')):
                page = self.root / f'{prefix}api-reference/{name}.mdx'
                page.write_text('---\ntitle: Reference operation\nopenapi: "reference-contracts/'
                                + prefix + 'reference.json ' + method + ' /' + name + '"\n---\n'
                                + OLD_REFERENCE_NOTE + '\n\nManual usage instructions.\n')
        for repeat in range(2):
            self.project()
            for prefix, unavailable in (('', 'Billing method unavailable.'), ('zh/', '计费方式暂不可用。')):
                self.assertEqual((self.root / f'reference-contracts/{prefix}reference.json').read_bytes(), raw)
                page = (self.root / f'{prefix}api-reference/messages.mdx').read_text()
                self.assertIn('$0.0001', page)
                self.assertIn('$0.015', page)
                self.assertNotIn(OLD_REFERENCE_NOTE, page)
                self.assertIn('Manual usage instructions.', page)
                header, _ = split_frontmatter(page)
                self.assertEqual(yaml.safe_load(header)['description'], 'Send a message.')
                self.assertIn(unavailable, (self.root / f'{prefix}api-reference/usage.mdx').read_text())
            if repeat:
                self.assertEqual(first, fixtures.page_snapshot(self.root))
            first = fixtures.page_snapshot(self.root)

    def test_price_only_descriptions_get_a_nonempty_business_description(self):
        for old, pricing in ((fixtures.OLD_SUMMARY, {'cost_contract': 'response_units'}),
                             ('<!-- aisa-pricing:start --> No charge. <!-- aisa-pricing:end -->',
                              {'kind': 'no_customer_charge'}),
                             ('<!-- aisa-pricing:start --> Price not yet published; this operation is unavailable. '
                              '<!-- aisa-pricing:end -->', {'kind': 'unpriced'})):
            operation = {'operationId': 'list', 'summary': 'List records',
                         'description': old, 'x-aisa-pricing': pricing}
            for title, language in (('List records', 'en'), ('读取记录', 'zh')):
                with self.subTest(pricing=pricing, language=language):
                    source = '---\ntitle: ' + title + '\nopenapi: "openapi/p.json GET /records"\n---\n'
                    projected = refresh_page_description(source, operation, language)
                    header, _ = split_frontmatter(projected)
                    self.assertEqual(yaml.safe_load(header)['description'], title)
                    self.assertNotIn('aisa-pricing:', projected)
                    self.assertEqual(refresh_page_description(projected, operation, language), projected)

    def test_generated_descriptions_follow_sources_but_manual_edits_remain_owned_by_authors(self):
        source = '---\ntitle: Records\nopenapi: "openapi/p.json GET /records"\n---\n'
        operation = {'operationId': 'records', 'description': 'Find records.\n\n' + fixtures.OLD_SUMMARY}
        first = refresh_page_description(source, operation)
        operation['description'] = 'Find archived records.\n\n' + fixtures.OLD_SUMMARY
        second = refresh_page_description(first, operation)
        header, _ = split_frontmatter(second)
        self.assertEqual(yaml.safe_load(header)['description'], 'Find archived records.')
        edited = second.replace('description: "Find archived records."', 'description: "My usage guide."')
        preserved = refresh_page_description(edited, operation)
        header, _ = split_frontmatter(preserved)
        self.assertEqual(yaml.safe_load(header)['description'], 'My usage guide.')
        self.assertNotIn(DESCRIPTION_HASH, yaml.safe_load(header))
        self.assertEqual(refresh_page_description(preserved, operation), preserved)

    def test_generated_description_uses_the_existing_translation_catalog(self):
        source = '---\ntitle: 读取记录\nopenapi: "openapi/zh/p.json GET /records"\n---\n'
        operation = {'operationId': 'records', 'description': 'Find records.\n\n' + fixtures.OLD_SUMMARY}
        translated = refresh_page_description(source, operation, 'zh', lambda text: {'Find records.': '查找记录。'}[text])
        header, _ = split_frontmatter(translated)
        self.assertEqual(yaml.safe_load(header)['description'], '查找记录。')

    def test_reference_snapshot_keeps_missing_coverage_in_report_not_a_page_warning(self):
        import sync_prod_runtime_docs as prod
        self.project()
        config = json.loads((self.root / 'docs.json').read_text())
        for lang in config['navigation']['languages']:
            prefix = 'zh/' if lang['language'] == 'zh' else ''
            lang['tabs'][0]['groups'] = [{'group': 'Reference', 'pages': [prefix + 'api-reference/chat'] }]
            page = self.root / f'{prefix}api-reference/chat.mdx'
            spec = self.root / f'openapi/{prefix}chat.json'
            spec.parent.mkdir(parents=True, exist_ok=True)
            spec.write_text(json.dumps({'paths': {'/chat/completions': {'post': {'operationId': 'chat'}}}}))
            page.write_text('---\ntitle: Chat\nopenapi: "openapi/' + prefix
                            + 'chat.json POST /chat/completions"\n---\n' + OLD_REFERENCE_NOTE
                            + '\n\nCreates a model response.\n')
        (self.root / 'docs.json').write_text(json.dumps(config))
        result = prod.scope_presentation(self.root, {})
        self.assertGreaterEqual(result['preserved_historic_pages'], 2)
        for prefix in ('', 'zh/'):
            text = (self.root / f'{prefix}api-reference/chat.mdx').read_text()
            self.assertNotIn('parameter details have not', text)
            self.assertNotIn('尚待核实', text)
            self.assertNotIn('disabled', text)
            self.assertIn('Creates a model response.', text)

    def test_cleanup_preserves_disabled_notices_and_literal_examples(self):
        from readable_contract_notes import clean_reference_notices
        text = (OLD_REFERENCE_NOTE + '\n\nCurrently disabled.\n'
                '<Warning>This endpoint is disabled and cannot be called.</Warning>\n'
                '```text\n' + OLD_REFERENCE_NOTE + '\n```\n')
        result = clean_reference_notices(text)
        self.assertEqual(result.count(OLD_REFERENCE_NOTE), 1)
        self.assertIn('Currently disabled.', result)
        self.assertIn('This endpoint is disabled and cannot be called.', result)

    def test_standalone_translation_keeps_generated_description_refreshable(self):
        self.assert_standalone_description_refresh('Find records.', 'Find archived records.')

    def test_standalone_translation_tracks_quoted_multiline_generated_descriptions(self):
        self.assert_standalone_description_refresh('Find "current" records.\nUse \\filters.',
                                                  'Find "archived" records.\nUse \\other-filters.')

    def test_standalone_extraction_includes_generated_title_fallback(self):
        self.assert_standalone_description_refresh('Search "records"', 'Find archived records.',
                                                  title_fallback=True)

    def assert_standalone_description_refresh(self, initial, updated, title_fallback=False):
        import runtime_localize_openapi_zh as localization
        operation = self.document['paths']['/apis/v1/prices/free']['get']
        operation['description'] = ('' if title_fallback else initial + '\n\n') + fixtures.OLD_SUMMARY
        if title_fallback:
            operation.pop('summary', None)
        self.raw = json.dumps(self.document).encode()
        self.project()
        if title_fallback:
            english = self.root / 'api-reference/prices/free.mdx'
            text = re.sub(r'^title:.*$', lambda _: 'title: ' + json.dumps(initial),
                          english.read_text(), flags=re.M)
            english.write_text(refresh_page_description(text, operation))
        path = '/apis/v1/prices/free'
        self.document['paths'] = {path: self.document['paths'][path]}
        self.raw = json.dumps(self.document).encode()
        (self.root / 'openapi/prices.json').write_bytes(self.raw)
        for prefix in ('', 'zh/'):
            for page in (self.root / f'{prefix}api-reference/prices').glob('*.mdx'):
                if page.stem != 'free':
                    page.unlink()
        translations = {initial: '查找记录。\n使用筛选器。', updated: '查找归档记录。\n使用新筛选器。'}
        with patch.multiple(localization, ROOT=self.root, OPENAPI_DIR=self.root / 'openapi',
                            ZH_OPENAPI_DIR=self.root / 'openapi/zh', API_DIR=self.root / 'api-reference',
                            ZH_API_DIR=self.root / 'zh/api-reference',
                            CATALOG_PATH=self.root / 'translations/openapi-zh.json'):
            localization.extract()
            catalog = localization.load_catalog()
            self.assertIn(localization.key_for(initial), catalog['entries'])
            for entry in catalog['entries'].values():
                entry['translation'] = translations.get(entry['source'], entry['source'])
            localization.save_catalog(catalog)
            localization.generate()
            # The next source revision uses a separately translated new string.
            localization.add_entry(catalog, updated, 'next-source-revision')
            catalog['entries'][localization.key_for(updated)]['translation'] = translations[updated]
            localization.save_catalog(catalog)
        zh = self.root / 'zh/api-reference/prices/free.mdx'
        header, _ = split_frontmatter(zh.read_text())
        self.assertIn(DESCRIPTION_HASH, yaml.safe_load(header))
        self.document['paths'][path]['get']['description'] = updated + '\n\n' + fixtures.OLD_SUMMARY
        self.raw = json.dumps(self.document).encode()
        self.project()
        header, _ = split_frontmatter(zh.read_text())
        self.assertEqual(yaml.safe_load(header)['description'], translations[updated])


if __name__ == '__main__':
    unittest.main()
