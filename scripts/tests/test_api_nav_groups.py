import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import api_nav_groups
import regroup_api_reference
from api_nav_groups import nav_pages, regroup
from pull_openapi import generate_pages
from regroup_api_reference import (regroup_docs, platform_rows, platform_index, index_pages, INDEX_PAGE,
                                   category_rows, category_cards, card_body, CARDS_START, CARDS_END)

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

    def test_preserved_dev_navigation_checks_indexes_without_regrouping(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'openapi').mkdir()
            (root / 'translations').mkdir()
            (root / 'openapi/nav-groups.json').write_text(json.dumps(CONFIG))
            (root / 'translations/openapi-nav-zh.json').write_text(json.dumps(LABELS))
            docs = docs_for([{'group': 'Overview', 'pages': [INDEX_PAGE]},
                             {'group': 'New provider', 'pages': ['api-reference/new/lookup']}])
            original = json.dumps(docs, indent=2, ensure_ascii=False) + '\n'
            (root / 'docs.json').write_text(original)
            for name, text in index_pages(docs, CONFIG, LABELS, root).items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text)
            args = ['regroup_api_reference.py', '--root', str(root), '--check', '--preserve-navigation']
            with patch.object(sys, 'argv', args):
                self.assertEqual(regroup_api_reference.main(), 0)
                self.assertEqual((root / 'docs.json').read_text(), original)
                (root / (INDEX_PAGE + '.mdx')).write_text('stale index')
                self.assertEqual(regroup_api_reference.main(), 1)
            with patch.object(sys, 'argv', args[:-1]):
                with self.assertRaisesRegex(KeyError, 'New provider'):
                    regroup_api_reference.main()


    def test_preserved_navigation_rejects_missing_or_duplicate_language_pages(self):
        docs = docs_for([{'group': 'New provider', 'pages': ['api-reference/new/lookup']}])
        for missing in (False, True):
            changed = copy.deepcopy(docs)
            zh = api_groups(changed, 'zh')[0]['pages']
            zh.clear() if missing else zh.append(zh[0])
            with self.subTest(missing=missing), self.assertRaises(AssertionError):
                regroup_api_reference.validate_preserved_navigation(changed)

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
        targets = (list(config['groups'].values()) + list(config.get('paths', {}).values())
                   + config.get('pages', []) + config.get('operations', []))
        names |= {t['subgroup'] for t in targets if 'subgroup' in t}
        names |= set(config.get('vendors', [])) | set(config.get('first_party', []))
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

    def test_category_cards_follow_the_sidebar_with_platforms_and_counts(self):
        docs, _ = regroup_docs(docs_for(copy.deepcopy(PLATFORM_LEGACY)), PLATFORM_CONFIG, PLATFORM_LABELS)
        self.assertEqual([(r['name'], r['icon'], r['first'], r['platforms'], r['count'])
                          for r in category_rows(docs, PLATFORM_CONFIG)], [
            ('Commerce', 'cart-shopping', 'api-reference/amazon/product', ['Amazon'], 1),
            ('Social', 'hashtag', 'api-reference/tiktok/videos', ['TikTok', 'Douyin'], 3),
            ('Other', 'ellipsis', 'api-reference/brand-new/one', ['Brand New'], 1),
        ])
        en = category_cards(docs, PLATFORM_CONFIG, PLATFORM_LABELS, 'en')
        self.assertTrue(en.startswith(CARDS_START + '\n<CardGroup cols={2}>') and en.endswith('</CardGroup>\n' + CARDS_END))
        self.assertIn('  <Card title="Social" icon="hashtag" href="/api-reference/tiktok/videos">\n'
                      '    TikTok and Douyin. 3 endpoints.\n  </Card>', en)
        self.assertIn('    Amazon. 1 endpoint.', en)
        zh = category_cards(docs, PLATFORM_CONFIG, PLATFORM_LABELS, 'zh')
        self.assertIn('  <Card title="社媒" icon="hashtag" href="/zh/api-reference/tiktok/videos">\n'
                      '    TikTok 和抖音，共 3 个端点。', zh)

    def test_card_body_names_six_platforms_then_counts_the_rest(self):
        row = {'platforms': ['Douyin', 'A', 'B', 'C', 'D', 'E', 'F', 'G'], 'count': 1234}
        self.assertEqual(card_body(row, PLATFORM_LABELS, 'en'),
                         'Douyin, A, B, C, D, E, and 2 more platforms. 1,234 endpoints.')
        self.assertEqual(card_body(row, PLATFORM_LABELS, 'zh'), '抖音、A、B、C、D、E 等 8 个平台，共 1,234 个端点。')
        # One name left over is shown rather than counted.
        row['platforms'] = row['platforms'][:7]
        self.assertEqual(card_body(row, PLATFORM_LABELS, 'en'),
                         'Douyin, A, B, C, D, E, and F. 1,234 endpoints.')
        row['platforms'] = ['Amazon', 'Douyin']
        self.assertEqual(card_body(row, PLATFORM_LABELS, 'zh'), 'Amazon 和抖音，共 1,234 个端点。')

    def test_index_pages_refresh_only_the_card_block_of_pages_that_have_one(self):
        docs, _ = regroup_docs(docs_for(copy.deepcopy(PLATFORM_LEGACY)), PLATFORM_CONFIG, PLATFORM_LABELS)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'resources').mkdir()
            (root / 'resources/data-apis.mdx').write_text(f'Intro.\n\n{CARDS_START}\nstale\n{CARDS_END}\n\nOutro.\n')
            (root / 'zh/resources').mkdir(parents=True)
            (root / 'zh/resources/data-apis.mdx').write_text('No card block.\n')
            pages = index_pages(docs, PLATFORM_CONFIG, PLATFORM_LABELS, root)
        self.assertNotIn('zh/resources/data-apis.mdx', pages)
        text = pages['resources/data-apis.mdx']
        self.assertTrue(text.startswith('Intro.\n\n' + CARDS_START + '\n<CardGroup'))
        self.assertTrue(text.endswith(CARDS_END + '\n\nOutro.\n'))
        self.assertNotIn('stale', text)
        self.assertIn('TikTok and Douyin. 3 endpoints.', text)


# `operations` rules split one provider's endpoints across platforms by path.
OPERATION_CONFIG = copy.deepcopy(PLATFORM_CONFIG)
OPERATION_CONFIG['first_party'] = ['AIsa Social']
OPERATION_CONFIG['categories'][1]['groups'] += ['1688', 'AIsa commerce']
OPERATION_CONFIG['categories'][2]['groups'] += ['AIsa Social']
OPERATION_CONFIG['operations'] = [
    {'spec': 'aisa-commerce', 'pattern': '^/commerce/amazon/', 'category': 'Commerce', 'group': 'Amazon'},
    {'spec': 'aisa-commerce', 'pattern': '^/commerce/1688/', 'category': 'Commerce', 'group': '1688'},
    {'spec': 'aisa-social', 'pattern': '^/social/tiktok/', 'category': 'Social', 'group': 'TikTok', 'subgroup': 'AIsa Social'},
    {'spec': 'aisa-social', 'pattern': '^/social/posts', 'category': 'Social', 'group': 'AIsa Social', 'subgroup': 'Posts'},
    {'spec': 'aisa-social', 'pattern': '^/social/accounts', 'category': 'Social', 'group': 'AIsa Social', 'subgroup': 'Accounts'},
]

OPERATION_LABELS = {**PLATFORM_LABELS, '1688': '1688', 'AIsa commerce': 'AIsa 电商', 'AIsa Social': 'AIsa Social',
                    'Posts': '帖子', 'Accounts': '账户', 'Misc': '其他接口'}

OPERATION_LEGACY = PLATFORM_LEGACY[:4] + [
    {'group': 'AIsa commerce', 'pages': [
        'api-reference/aisa-commerce/get_amazon-search', 'api-reference/aisa-commerce/get_1688-search',
        'api-reference/aisa-commerce/get_status']},
    {'group': 'AIsa Social', 'pages': [
        {'group': 'Misc', 'pages': ['api-reference/aisa-social/get_tiktok-insights']},
        'api-reference/aisa-social/get_accounts', 'api-reference/aisa-social/post_posts']},
]

OPERATIONS = {
    'api-reference/aisa-commerce/get_amazon-search': ('aisa-commerce', '/commerce/amazon/search'),
    'api-reference/aisa-commerce/get_1688-search': ('aisa-commerce', '/commerce/1688/search'),
    'api-reference/aisa-commerce/get_status': ('aisa-commerce', '/status'),
    'api-reference/aisa-social/get_tiktok-insights': ('aisa-social', '/social/tiktok/insights'),
    'api-reference/aisa-social/get_accounts': ('aisa-social', '/social/accounts'),
    'api-reference/aisa-social/post_posts': ('aisa-social', '/social/posts'),
    # The same path in another document does not match a rule for this one.
    'api-reference/amazon/product': ('amazon', '/commerce/1688/product'),
}


class OperationRuleTests(unittest.TestCase):
    def regrouped(self):
        groups, unmapped = regroup(copy.deepcopy(OPERATION_LEGACY), OPERATION_CONFIG, OPERATIONS)
        self.assertEqual(unmapped, [])
        return {c['group']: c for c in groups[1]['pages']}

    def test_operation_rules_move_a_providers_pages_to_their_platforms(self):
        commerce = self.regrouped()['Commerce']
        self.assertEqual(commerce['pages'], [
            {'group': 'Amazon', 'pages': ['api-reference/amazon/product', 'api-reference/aisa-commerce/get_amazon-search']},
            {'group': '1688', 'pages': ['api-reference/aisa-commerce/get_1688-search']},
            {'group': 'AIsa commerce', 'pages': ['api-reference/aisa-commerce/get_status']},
        ])

    def test_a_page_leaves_its_kept_subgroup_and_an_empty_subgroup_is_dropped(self):
        social = self.regrouped()['Social']
        aisa = next(g for g in social['pages'] if g['group'] == 'AIsa Social')
        self.assertEqual([g['group'] for g in aisa['pages']], ['Posts', 'Accounts'])
        self.assertNotIn('Misc', json.dumps(social))

    def test_first_party_subgroups_sit_between_own_pages_and_vendors(self):
        social = self.regrouped()['Social']
        self.assertEqual([g['group'] for g in social['pages']], ['TikTok', 'Douyin', 'AIsa Social'])
        tiktok = social['pages'][0]['pages']
        self.assertEqual(tiktok[0], 'api-reference/tiktok/videos')
        self.assertEqual([g['group'] for g in tiktok[1:]], ['AIsa Social', 'TikHub'])
        self.assertEqual(tiktok[1]['pages'], ['api-reference/aisa-social/get_tiktok-insights'])

    def test_operation_regroup_keeps_pages_and_is_a_fixed_point(self):
        groups, _ = regroup(copy.deepcopy(OPERATION_LEGACY), OPERATION_CONFIG, OPERATIONS)
        self.assertEqual(sorted(nav_pages(groups)), sorted(nav_pages(OPERATION_LEGACY)))
        again, unmapped = regroup(copy.deepcopy(groups), OPERATION_CONFIG, OPERATIONS)
        self.assertEqual((again, unmapped), (groups, []))

    def test_regroup_docs_reads_operations_from_page_frontmatter(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for page, (spec, path) in OPERATIONS.items():
                (root / page).parent.mkdir(parents=True, exist_ok=True)
                (root / (page + '.mdx')).write_text(f'---\nopenapi: "openapi/{spec}.json GET {path}"\n---\n')
            docs, _ = regroup_docs(docs_for(copy.deepcopy(OPERATION_LEGACY)), OPERATION_CONFIG, OPERATION_LABELS, root)
        expected, _ = regroup(copy.deepcopy(OPERATION_LEGACY), OPERATION_CONFIG, OPERATIONS)
        self.assertEqual(api_groups(docs, 'en'), expected)
        zh_social = api_groups(docs, 'zh')[1]['pages'][1]
        self.assertEqual([g['group'] for g in zh_social['pages'][-1]['pages']], ['帖子', '账户'])

    def test_config_rejects_an_operation_rule_without_a_spec_or_pattern(self):
        for broken in ({'pattern': '^/x', 'category': 'Commerce'}, {'spec': 'x', 'category': 'Commerce'}):
            config = copy.deepcopy(OPERATION_CONFIG)
            config['operations'].append(broken)
            with self.assertRaisesRegex(ValueError, 'spec and a pattern'):
                api_nav_groups.validate(config)


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

    def test_operation_rule_places_a_new_page_by_its_path(self):
        (self.root / 'openapi/nav-groups.json').write_text(json.dumps(OPERATION_CONFIG))
        (self.root / 'translations/openapi-nav-zh.json').write_text(json.dumps(OPERATION_LABELS, ensure_ascii=False))
        (self.root / 'api-reference/aisa-commerce').mkdir(parents=True)
        (self.root / 'api-reference/aisa-commerce/get_amazon-two.mdx').write_text(
            '---\ntitle: Two\nopenapi: "openapi/aisa-commerce.json GET /commerce/amazon/two"\nx-aisa-operation-id: "one"\n---\n')
        changes = {}
        generate_pages(self.root, 'aisa-commerce', self.page_document('AIsa commerce', '/commerce/amazon/two'), changes)
        docs = json.loads(changes[self.root / 'docs.json'])
        amazon = api_groups(docs, 'en')[1]['pages'][0]['pages'][0]
        self.assertEqual(amazon, {'group': 'Amazon', 'pages': [
            'api-reference/amazon/product', 'api-reference/aisa-commerce/get_amazon-two']})
        zh_amazon = api_groups(docs, 'zh')[1]['pages'][0]['pages'][0]
        self.assertEqual(zh_amazon['pages'][-1], 'zh/api-reference/aisa-commerce/get_amazon-two')
        self.assertNotIn('AIsa commerce', [g['group'] for g in api_groups(docs, 'en')[1]['pages'][0]['pages']])

    # The inherited tests assume the flat fixture configuration.
    test_mapped_provider_creates_vendor_subgroup_in_category_order = None
    test_mapped_provider_reuses_existing_nested_group = None
    test_new_category_is_inserted_in_configured_position = None
    test_unmapped_provider_falls_back_to_top_level_group = None
    test_without_config_titles_append_top_level_groups = None


if __name__ == '__main__':
    unittest.main()
