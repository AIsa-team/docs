import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import model_pages
from model_pages import (FAMILIES_END, FAMILIES_START, TABLE_END, TABLE_START, expected_pages, families_table,
                         family_models, model_table, replace_block, snapshot_from)

ROOT = Path(__file__).resolve().parents[2]


def model(name, model_type='text', paths=('/v1/chat/completions',), status='priced'):
    return {'name': name, 'model_type': model_type, 'pricing_status': status,
            'routes': [{'path': path, 'method': 'POST'} for path in paths] + [{'path': '/v1/models', 'method': 'GET'}]}


PRICE_LIST = {'data': {'vendors': [
    {'vendor': 'Zeta', 'models': [model('zeta-1')]},
    {'vendor': 'Acme', 'models': [
        model('acme-10', paths=('/v1/responses', '/v1/chat/completions')),
        model('acme-9'),
        model('acme-clip', paths=('/v1/video/generations',)),
        model('acme-draw', paths=('/v1/images/edits', '/v1/images/generations')),
        model('acme-rank', 'embedding', ('/v1/rerank',)),
        model('acme-old', status='unavailable'),
    ]},
    {'vendor': 'Gone', 'models': [model('gone-1', status='unavailable')]},
]}}

CONFIG = {
    'families': [{'vendor': 'Acme', 'page': 'models/acme', 'name': {'en': 'Acme', 'zh': '阿克米'},
                  'provider': {'en': 'Acme Inc.', 'zh': '阿克米公司'}}],
    'notes': {'acme-9': {'en': 'Cheapest route', 'zh': '最便宜的路由'}},
}


class SnapshotTests(unittest.TestCase):
    def test_keeps_callable_models_sorted_by_id_with_post_routes_and_endpoint_types(self):
        snapshot = snapshot_from(PRICE_LIST)
        self.assertEqual([v['vendor'] for v in snapshot['vendors']], ['Acme', 'Zeta'])
        acme = snapshot['vendors'][0]['models']
        self.assertEqual([m['id'] for m in acme], ['acme-9', 'acme-10', 'acme-clip', 'acme-draw', 'acme-rank'])
        self.assertEqual(acme[1]['routes'], ['/v1/chat/completions', '/v1/responses'])
        self.assertEqual([m['type'] for m in acme], ['text', 'text', 'video', 'image', 'rerank'])
        self.assertEqual(acme[3]['routes'], ['/v1/images/generations', '/v1/images/edits'])


class TableTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = snapshot_from(PRICE_LIST)
        self.acme = self.snapshot['vendors'][0]['models']

    def test_model_table_adds_the_notes_column_only_when_a_model_has_a_note(self):
        en = model_table(self.acme, CONFIG['notes'], 'en').split('\n')
        self.assertEqual(en[0], '| Model ID | Type | Endpoints | Best for |')
        self.assertEqual(en[2], '| `acme-9` | Text | `/v1/chat/completions` | Cheapest route |')
        self.assertEqual(en[3], '| `acme-10` | Text | `/v1/chat/completions`, `/v1/responses` | — |')
        zh = model_table(self.acme, CONFIG['notes'], 'zh').split('\n')
        self.assertEqual(zh[3], '| `acme-10` | 文本 | `/v1/chat/completions`、`/v1/responses` | — |')
        self.assertEqual(model_table(self.acme, {}, 'en').split('\n')[0], '| Model ID | Type | Endpoints |')

    def test_families_table_lists_configured_families_first_and_others_without_a_link(self):
        en = families_table(self.snapshot, CONFIG, 'en').split('\n')
        self.assertEqual(en[2], '| [Acme](/models/acme) | Acme Inc. | 5 | Text, image, video, rerank |')
        self.assertEqual(en[3], '| Zeta | Zeta | 1 | Text |')
        zh = families_table(self.snapshot, CONFIG, 'zh').split('\n')
        self.assertEqual(zh[2], '| [阿克米](/zh/models/acme) | 阿克米公司 | 5 | 文本、图像、视频、重排序 |')

    def test_replace_block_needs_both_comments(self):
        self.assertEqual(replace_block(f'a\n{TABLE_START}\nold\n{TABLE_END}\nb', TABLE_START, TABLE_END, 'new'),
                         f'a\n{TABLE_START}\nnew\n{TABLE_END}\nb')
        with self.assertRaises(ValueError):
            replace_block('no block', TABLE_START, TABLE_END, 'new')


SPLIT_CONFIG = {
    'families': [
        {'vendor': 'Acme', 'page': 'models/acme', 'name': 'Acme'},
        {'vendor': 'Acme', 'page': 'models/acme-media', 'name': 'Acme Media', 'prefixes': ['ACME-CLIP', 'acme-draw']},
    ],
    'notes': {},
}


class SplitTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = snapshot_from(PRICE_LIST)

    def test_prefixed_family_takes_its_models_and_the_other_family_the_rest(self):
        shares = {family['page']: [m['id'] for m in models] for family, models in family_models(self.snapshot, SPLIT_CONFIG)}
        self.assertEqual(shares, {'models/acme': ['acme-9', 'acme-10', 'acme-rank'],
                                  'models/acme-media': ['acme-clip', 'acme-draw']})

    def test_families_table_counts_each_family(self):
        en = families_table(self.snapshot, SPLIT_CONFIG, 'en').split('\n')
        self.assertEqual(en[2:], ['| [Acme](/models/acme) | Acme | 3 | Text, rerank |',
                                  '| [Acme Media](/models/acme-media) | Acme | 2 | Image, video |',
                                  '| Zeta | Zeta | 1 | Text |'])

    def test_split_problems_block_the_check(self):
        lost = {'families': [{'vendor': 'Acme', 'page': 'models/acme', 'name': 'Acme', 'prefixes': ['acme-clip']}],
                'notes': {}}
        repeated = {'families': [dict(family, prefixes=['acme-']) for family in SPLIT_CONFIG['families']], 'notes': {}}
        empty = {'families': SPLIT_CONFIG['families'] + [
            {'vendor': 'Acme', 'page': 'models/none', 'name': 'None', 'prefixes': ['nothing']}], 'notes': {}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('models/acme.mdx', 'zh/models/acme.mdx', 'models/acme-media.mdx', 'zh/models/acme-media.mdx',
                         'models/none.mdx', 'zh/models/none.mdx'):
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text(f'{TABLE_START}\n{TABLE_END}\n')
            for name in ('guides/models.mdx', 'zh/guides/models.mdx'):
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text(f'{FAMILIES_START}\n{FAMILIES_END}\n')
            _, ok = expected_pages(root, self.snapshot, SPLIT_CONFIG)
            _, lost_problems = expected_pages(root, self.snapshot, lost)
            _, repeated_problems = expected_pages(root, self.snapshot, repeated)
            _, empty_problems = expected_pages(root, self.snapshot, empty)
        self.assertFalse([p for p in ok if model_pages.blocking(p)])
        self.assertIn('acme-9: on no family page of Acme; check the families\' prefixes', lost_problems)
        self.assertIn('acme-9: on more than one family page of Acme; check the families\' prefixes', repeated_problems)
        self.assertIn('models/none: no Acme model matches the page; check its prefixes', empty_problems)
        self.assertTrue(all(model_pages.blocking(p) for p in lost_problems + repeated_problems + empty_problems
                            if 'prefixes' in p))


class PageTests(unittest.TestCase):
    def test_expected_pages_fill_family_and_catalog_blocks_and_report_gaps(self):
        snapshot = snapshot_from(PRICE_LIST)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('models/acme.mdx', 'guides/models.mdx', 'zh/guides/models.mdx'):
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                start, end = (TABLE_START, TABLE_END) if name.startswith('models') else (FAMILIES_START, FAMILIES_END)
                (root / name).write_text(f'Intro.\n\n{start}\nstale\n{end}\n\nOutro.\n')
            pages, problems = expected_pages(root, snapshot, CONFIG)
        self.assertEqual(sorted(pages), ['guides/models.mdx', 'models/acme.mdx', 'zh/guides/models.mdx'])
        self.assertIn('| `acme-9` | Text |', pages['models/acme.mdx'])
        self.assertTrue(pages['models/acme.mdx'].endswith(f'{TABLE_END}\n\nOutro.\n'))
        self.assertIn('[Acme](/models/acme)', pages['guides/models.mdx'])
        self.assertEqual(problems, ['zh/models/acme.mdx: missing family page',
                                    'Zeta: on the price list without a family page; '
                                    'it is listed in the Model Catalog only'])

    def test_repository_pages_match_the_saved_snapshot(self):
        snapshot, config = model_pages.load(ROOT)
        pages, problems = expected_pages(ROOT, snapshot, config)
        self.assertFalse([p for p in problems if 'missing family page' in p])
        stale = [name for name, text in pages.items() if (ROOT / name).read_text() != text]
        self.assertEqual(stale, [])
        listed = {family['vendor'] for family in config['families']}
        self.assertTrue(listed <= {vendor['vendor'] for vendor in snapshot['vendors']})
        self.assertTrue(all(set(note) == {'en', 'zh'} for note in config['notes'].values()))


if __name__ == '__main__':
    unittest.main()
