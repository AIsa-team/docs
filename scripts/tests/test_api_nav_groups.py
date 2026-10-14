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
from regroup_api_reference import regroup_docs

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
        names |= {t['subgroup'] for t in config['groups'].values() if 'subgroup' in t}
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


if __name__ == '__main__':
    unittest.main()
