import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import api_nav_groups
from api_nav_groups import nav_pages, regroup
from pull_openapi import generate_pages
from regroup_api_reference import regroup_docs, platform_rows, platform_index, index_pages, INDEX_PAGE

ROOT = Path(__file__).resolve().parents[2]

CONFIG = {
    'categories': [
        {'name': 'Overview', 'icon': 'compass', 'groups': []},
        {'name': 'Search & Research', 'icon': 'magnifying-glass', 'groups': ['Tavily', 'Exa']},
        {'name': 'Finance & Crypto', 'icon': 'chart-line', 'groups': ['Financial Data', 'Polymarket']},
    ],
    'groups': {
        'Overview': {'category': 'Overview'},
        'Search API': {'category': 'Search & Research', 'group': 'Tavily'},
        'Exa API': {'category': 'Search & Research', 'group': 'Exa'},
        'Financial API': {'category': 'Finance & Crypto', 'group': 'Financial Data'},
        'Akta': {'category': 'Finance & Crypto', 'group': 'Financial Data', 'subgroup': 'Private Market Data (Akta)'},
        'Polymarket Clob': {'category': 'Finance & Crypto', 'group': 'Polymarket', 'subgroup': 'CLOB'},
        'Fixture': {'category': 'Finance & Crypto', 'group': 'Polymarket', 'subgroup': 'CLOB'},
    },
    'pages': [{'prefix': 'api-reference/search/post_exa-', 'category': 'Search & Research', 'group': 'Exa'}],
}

LABELS = {
    'Overview': '概览', 'Search & Research': '搜索与研究', 'Finance & Crypto': '金融与加密',
    'Tavily': 'Tavily', 'Exa': 'Exa', 'Financial Data': '金融数据', 'Polymarket': 'Polymarket',
    'Private Market Data (Akta)': '私募市场数据（Akta）', 'CLOB': 'CLOB', 'Earnings': '财报收益',
}

LEGACY = [
    {'group': 'Overview', 'pages': ['api-reference']},
    {'group': 'Search API', 'pages': ['api-reference/search/post_tavily-search', 'api-reference/search/post_exa-search']},
    {'group': 'Financial API', 'pages': [{'group': 'Earnings', 'pages': ['api-reference/financial/earnings']}]},
    {'group': 'Exa API', 'pages': ['api-reference/search/post_exa-search', 'api-reference/exa/agent-runs']},
    {'group': 'Polymarket Clob', 'pages': ['api-reference/polymarket-clob/book']},
    {'group': 'Akta', 'pages': ['api-reference/akta/company']},
    {'group': 'Brand New', 'pages': ['api-reference/brand-new/one']},
]


def docs_for(groups):
    zh = json.loads(json.dumps(groups).replace('"api-reference', '"zh/api-reference'))
    return {'navigation': {'languages': [
        {'language': 'en', 'tabs': [{'tab': 'Docs', 'groups': []}, {'tab': 'API Reference', 'icon': 'code', 'groups': groups}]},
        {'language': 'zh', 'tabs': [{'tab': 'API 参考', 'groups': zh}]},
    ]}}


def api_groups(docs, language):
    block = next(b for b in docs['navigation']['languages'] if b['language'] == language)
    return next(t for t in block['tabs'] if t['tab'] in {'API Reference', 'API 参考'})['groups']


class RegroupTests(unittest.TestCase):
    def test_builds_categories_merges_vendors_and_keeps_unmapped_last(self):
        groups, unmapped = regroup(copy.deepcopy(LEGACY), CONFIG)
        self.assertEqual(unmapped, ['Brand New'])
        self.assertEqual([g['group'] for g in groups], ['Overview', 'Search & Research', 'Finance & Crypto', 'Brand New'])
        self.assertEqual(groups[1]['icon'], 'magnifying-glass')
        search = {g['group']: g['pages'] for g in groups[1]['pages']}
        self.assertEqual(search, {
            'Tavily': ['api-reference/search/post_tavily-search'],
            'Exa': ['api-reference/search/post_exa-search', 'api-reference/exa/agent-runs'],
        })
        finance = groups[2]['pages']
        self.assertEqual([g['group'] for g in finance], ['Financial Data', 'Polymarket'])
        self.assertEqual([g['group'] for g in finance[0]['pages']], ['Earnings', 'Private Market Data (Akta)'])
        self.assertEqual(finance[1]['pages'], [{'group': 'CLOB', 'pages': ['api-reference/polymarket-clob/book']}])

    def test_page_set_is_preserved_without_duplicates_and_rerun_is_a_fixed_point(self):
        groups, _ = regroup(copy.deepcopy(LEGACY), CONFIG)
        pages = nav_pages(groups)
        self.assertEqual(set(pages), set(nav_pages(LEGACY)))
        self.assertEqual(len(pages), len(set(pages)))
        again, _ = regroup(copy.deepcopy(groups), CONFIG)
        self.assertEqual(again, groups)

    def test_chinese_tab_mirrors_english_with_labels(self):
        docs, _ = regroup_docs(docs_for(copy.deepcopy(LEGACY[:-1])), CONFIG, LABELS)
        en, zh = api_groups(docs, 'en'), api_groups(docs, 'zh')
        self.assertEqual(nav_pages(zh), ['zh/' + page for page in nav_pages(en)])
        self.assertEqual([g['group'] for g in zh], ['概览', '搜索与研究', '金融与加密'])
        self.assertEqual(zh[2]['pages'][0]['pages'][1]['group'], '私募市场数据（Akta）')

    def test_missing_chinese_label_fails_before_writing(self):
        labels = dict(LABELS)
        del labels['CLOB']
        with self.assertRaisesRegex(KeyError, 'CLOB'):
            regroup_docs(docs_for(copy.deepcopy(LEGACY[:-1])), CONFIG, labels)

    def test_config_rejects_group_outside_its_category(self):
        config = copy.deepcopy(CONFIG)
        config['groups']['Bad'] = {'category': 'Overview', 'group': 'Exa'}
        with self.assertRaisesRegex(ValueError, 'not listed'):
            api_nav_groups.validate(config)

    def test_repository_config_is_valid_and_labelled(self):
        config = api_nav_groups.load(ROOT)
        labels = json.loads((ROOT / 'translations/openapi-nav-zh.json').read_text())
        names = {name for c in config['categories'] for name in [c['name'], *c['groups']]}
        targets = list(config['groups'].values()) + list(config.get('paths', {}).values()) + config.get('pages', [])
        names |= {t['subgroup'] for t in targets if 'subgroup' in t}
        names |= {config['section']['name']} if config.get('section') else set()
        self.assertEqual(sorted(name for name in names if not labels.get(name)), [])


class GeneratePagesPlacementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'openapi').mkdir()
        (self.root / 'translations').mkdir()
        (self.root / 'openapi/nav-groups.json').write_text(json.dumps(CONFIG))
        (self.root / 'translations/openapi-nav-zh.json').write_text(json.dumps(LABELS, ensure_ascii=False))
        groups, _ = regroup(copy.deepcopy(LEGACY[:1] + LEGACY[2:3]), CONFIG)
        self.write_docs(groups)

    def write_docs(self, groups):
        docs = docs_for(groups)
        docs, _ = regroup_docs(docs, CONFIG, LABELS) if groups else (docs, [])
        (self.root / 'docs.json').write_text(json.dumps(docs, ensure_ascii=False))

    def generate(self, title, provider='fixture'):
        document = {'openapi': '3.1.0', 'info': {'title': title, 'x-aisa-document': {'document_hash': 'h'}},
                    'paths': {'/one': {'get': {'operationId': 'one', 'responses': {'200': {'description': 'OK'}}}}}}
        changes = {}
        generate_pages(self.root, provider, document, changes)
        return json.loads(changes[self.root / 'docs.json'])

    def test_mapped_provider_creates_vendor_subgroup_in_category_order(self):
        docs = self.generate('Fixture')
        en, zh = api_groups(docs, 'en'), api_groups(docs, 'zh')
        self.assertEqual([g['group'] for g in en], ['Overview', 'Finance & Crypto'])
        self.assertEqual([g['group'] for g in en[1]['pages']], ['Financial Data', 'Polymarket'])
        self.assertEqual(en[1]['pages'][1]['pages'], [{'group': 'CLOB', 'pages': ['api-reference/fixture/one']}])
        self.assertEqual([g['group'] for g in zh[1]['pages']], ['金融数据', 'Polymarket'])
        self.assertEqual(zh[1]['pages'][1]['pages'], [{'group': 'CLOB', 'pages': ['zh/api-reference/fixture/one']}])

    def test_mapped_provider_reuses_existing_nested_group(self):
        docs = self.generate('Akta')
        financial = api_groups(docs, 'en')[1]['pages'][0]
        self.assertEqual([g['group'] for g in financial['pages']], ['Earnings', 'Private Market Data (Akta)'])
        self.assertEqual(financial['pages'][1]['pages'], ['api-reference/fixture/one'])
        self.assertEqual(api_groups(docs, 'zh')[1]['pages'][0]['pages'][1]['pages'], ['zh/api-reference/fixture/one'])

    def test_new_category_is_inserted_in_configured_position(self):
        docs = self.generate('Exa API')
        self.assertEqual([g['group'] for g in api_groups(docs, 'en')], ['Overview', 'Search & Research', 'Finance & Crypto'])
        self.assertEqual([g['group'] for g in api_groups(docs, 'zh')], ['概览', '搜索与研究', '金融与加密'])

    def test_unmapped_provider_falls_back_to_top_level_group(self):
        docs = self.generate('Unmapped Provider')
        en = api_groups(docs, 'en')
        self.assertEqual(en[-1], {'group': 'Unmapped Provider', 'pages': ['api-reference/fixture/one']})
        self.assertEqual(api_groups(docs, 'zh')[-1]['pages'], ['zh/api-reference/fixture/one'])

    def test_without_config_titles_append_top_level_groups(self):
        (self.root / 'openapi/nav-groups.json').unlink()
        docs = self.generate('Fixture')
        self.assertEqual(api_groups(docs, 'en')[-1], {'group': 'Fixture', 'pages': ['api-reference/fixture/one']})


# Category -> platform navigation: categories sit in one collapsible section,
# a vendor's per-platform groups move to that platform, unmapped titles go to
# the fallback category, and third-party vendors follow a platform's own pages.
PLATFORM_CONFIG = {
    'section': {'name': 'Browse by category', 'icon': 'layer-group'},
    'fallback': 'Other',
    'vendors': ['TikHub'],
    'categories': [
        {'name': 'Overview', 'icon': 'compass', 'top': True, 'groups': []},
        {'name': 'Commerce', 'icon': 'cart-shopping', 'groups': ['Amazon']},
        {'name': 'Social', 'icon': 'hashtag', 'groups': ['TikTok', 'Douyin', 'Cross-platform']},
        {'name': 'Other', 'icon': 'ellipsis', 'groups': []},
    ],
    'groups': {'TikHub API': {'category': 'Social', 'group': 'Cross-platform'}},
    'paths': {
        'Social & Media': {'category': 'Social'},
        'Social & Media/TikHub': {'category': 'Social'},
        'Social & Media/TikHub/TikTok': {'category': 'Social', 'group': 'TikTok', 'subgroup': 'TikHub'},
        'Social & Media/TikHub/Douyin': {'category': 'Social', 'group': 'Douyin'},
        'Social & Media/TikHub/Douyin/Extended': {'category': 'Social', 'group': 'Douyin'},
    },
    'pages': [{'prefix': 'api-reference/tikhub/get_tikhub-tiktok-', 'category': 'Social', 'group': 'TikTok', 'subgroup': 'TikHub'}],
}

PLATFORM_LABELS = {
    'Overview': '概览', 'Browse by category': '按分类浏览', 'Commerce': '电商', 'Social': '社媒', 'Other': '其他',
    'Amazon': 'Amazon', 'TikTok': 'TikTok', 'Douyin': '抖音', 'Cross-platform': '跨平台', 'TikHub': 'TikHub',
    'Core': '核心', 'Brand New': 'Brand New',
}

PLATFORM_LEGACY = [
    {'group': 'Overview', 'icon': 'compass', 'pages': ['api-reference', INDEX_PAGE]},
    {'group': 'Social & Media', 'pages': [{'group': 'TikHub', 'pages': [
        {'group': 'TikTok', 'pages': [{'group': 'Core', 'pages': ['api-reference/tikhub/get_tikhub-tiktok-one']}]},
        {'group': 'Douyin', 'pages': [{'group': 'Extended', 'pages': ['api-reference/tikhub/get_tikhub-douyin-one']}]},
    ]}]},
    {'group': 'TikTok', 'pages': ['api-reference/tiktok/videos']},
    {'group': 'Amazon', 'pages': ['api-reference/amazon/product']},
    {'group': 'Brand New', 'pages': ['api-reference/brand-new/one']},
]


class PlatformNavigationTests(unittest.TestCase):
    def regrouped(self):
        groups, unmapped = regroup(copy.deepcopy(PLATFORM_LEGACY), PLATFORM_CONFIG)
        self.assertEqual(unmapped, ['Brand New'])
        return groups

    def test_categories_sit_in_one_section_and_only_top_categories_stay_top_level(self):
        groups = self.regrouped()
        self.assertEqual([g['group'] for g in groups], ['Overview', 'Browse by category'])
        self.assertEqual(groups[1]['icon'], 'layer-group')
        self.assertEqual([c['group'] for c in groups[1]['pages']], ['Commerce', 'Social', 'Other'])
        self.assertTrue(all(isinstance(c, dict) for c in groups[1]['pages']))

    def test_vendor_platform_groups_move_to_platforms_and_vendors_follow_own_pages(self):
        social = self.regrouped()[1]['pages'][1]
        tiktok, douyin = social['pages']
        self.assertEqual(tiktok, {'group': 'TikTok', 'pages': ['api-reference/tiktok/videos', {'group': 'TikHub', 'pages': [
            {'group': 'Core', 'pages': ['api-reference/tikhub/get_tikhub-tiktok-one']}]}]})
        # A single structural child is flattened by its path rule.
        self.assertEqual(douyin, {'group': 'Douyin', 'pages': ['api-reference/tikhub/get_tikhub-douyin-one']})

    def test_unmapped_group_goes_to_fallback_category(self):
        other = self.regrouped()[1]['pages'][2]
        self.assertEqual(other, {'group': 'Other', 'icon': 'ellipsis', 'pages': [
            {'group': 'Brand New', 'pages': ['api-reference/brand-new/one']}]})

    def test_platform_regroup_keeps_pages_and_is_a_fixed_point(self):
        groups = self.regrouped()
        self.assertEqual(sorted(nav_pages(groups)), sorted(nav_pages(PLATFORM_LEGACY)))
        again, unmapped = regroup(copy.deepcopy(groups), PLATFORM_CONFIG)
        self.assertEqual((again, unmapped), (groups, []))

    def test_index_lists_platforms_a_to_z_with_category_first_page_and_count(self):
        docs, _ = regroup_docs(docs_for(copy.deepcopy(PLATFORM_LEGACY)), PLATFORM_CONFIG, PLATFORM_LABELS)
        rows = platform_rows(docs, PLATFORM_CONFIG)
        self.assertEqual([(r['name'], r['category'], r['first'], r['count']) for r in rows], [
            ('Amazon', 'Commerce', 'api-reference/amazon/product', 1),
            ('Brand New', 'Other', 'api-reference/brand-new/one', 1),
            ('Douyin', 'Social', 'api-reference/tikhub/get_tikhub-douyin-one', 1),
            ('TikTok', 'Social', 'api-reference/tiktok/videos', 2),
        ])
        en = platform_index(docs, PLATFORM_CONFIG, PLATFORM_LABELS, 'en')
        self.assertIn('| [TikTok](/api-reference/tiktok/videos) | Social | 2 |', en)
        self.assertIn('## D', en)
        zh = platform_index(docs, PLATFORM_CONFIG, PLATFORM_LABELS, 'zh')
        self.assertIn('| [抖音（Douyin）](/zh/api-reference/tikhub/get_tikhub-douyin-one) | 社媒 | 1 |', zh)
        self.assertEqual(sorted(index_pages(docs, PLATFORM_CONFIG, PLATFORM_LABELS)),
                         [INDEX_PAGE + '.mdx', 'zh/' + INDEX_PAGE + '.mdx'])


class PlatformPlacementTests(GeneratePagesPlacementTests):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'openapi').mkdir()
        (self.root / 'translations').mkdir()
        (self.root / 'openapi/nav-groups.json').write_text(json.dumps(PLATFORM_CONFIG))
        (self.root / 'translations/openapi-nav-zh.json').write_text(json.dumps(PLATFORM_LABELS, ensure_ascii=False))
        groups, _ = regroup(copy.deepcopy(PLATFORM_LEGACY[:4]), PLATFORM_CONFIG)
        docs, _ = regroup_docs(docs_for(groups), PLATFORM_CONFIG, PLATFORM_LABELS)
        (self.root / 'docs.json').write_text(json.dumps(docs, ensure_ascii=False))

    def page_document(self, title, path):
        return {'openapi': '3.1.0', 'info': {'title': title, 'x-aisa-document': {'document_hash': 'h'}},
                'paths': {path: {'get': {'operationId': 'one', 'responses': {'200': {'description': 'OK'}}}}}}

    def test_unmapped_provider_goes_to_fallback_category_in_both_languages(self):
        docs = self.generate('Unmapped Provider')
        en, zh = api_groups(docs, 'en'), api_groups(docs, 'zh')
        self.assertEqual([g['group'] for g in en], ['Overview', 'Browse by category'])
        self.assertEqual(en[1]['pages'][-1]['pages'], [{'group': 'Unmapped Provider', 'pages': ['api-reference/fixture/one']}])
        self.assertEqual(zh[1]['group'], '按分类浏览')
        self.assertEqual(zh[1]['pages'][-1]['group'], '其他')
        self.assertEqual(zh[1]['pages'][-1]['pages'][0]['pages'], ['zh/api-reference/fixture/one'])

    def test_page_rule_places_a_vendor_page_on_its_platform_before_title_mapping(self):
        from pull_openapi import generate_pages
        (self.root / 'api-reference/tikhub').mkdir(parents=True)
        changes = {}
        # The page name comes from the existing operation page, so make one.
        (self.root / 'api-reference/tikhub/get_tikhub-tiktok-two.mdx').write_text(
            '---\ntitle: Two\nopenapi: "openapi/tikhub.json GET /tiktok/two"\nx-aisa-operation-id: "one"\n---\n')
        generate_pages(self.root, 'tikhub', self.page_document('TikHub API', '/tiktok/two'), changes)
        docs = json.loads(changes[self.root / 'docs.json'])
        tiktok = api_groups(docs, 'en')[1]['pages'][1]['pages'][0]
        self.assertEqual(tiktok['pages'][0], 'api-reference/tiktok/videos')
        self.assertEqual(tiktok['pages'][1]['group'], 'TikHub')
        self.assertEqual(tiktok['pages'][1]['pages'][-1], 'api-reference/tikhub/get_tikhub-tiktok-two')

    # The inherited tests assume the flat fixture configuration.
    test_mapped_provider_creates_vendor_subgroup_in_category_order = None
    test_mapped_provider_reuses_existing_nested_group = None
    test_new_category_is_inserted_in_configured_position = None
    test_unmapped_provider_falls_back_to_top_level_group = None
    test_without_config_titles_append_top_level_groups = None


if __name__ == '__main__':
    unittest.main()
