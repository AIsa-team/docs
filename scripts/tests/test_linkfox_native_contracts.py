"""Linkfox source contracts through the existing Composer and bilingual pages."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

import yaml
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import compose, digest
from public_projection import project
from pull_openapi import generate_pages
from runtime_localize_openapi_zh import localize_tree, strip_translatable
from runtime_registry import source_configurations

ROOT = Path(__file__).resolve().parents[2]
# Independent public route inventory: adding a source cannot silently omit a route.
ROUTES = '''alibaba1688/imageSearch alibaba1688/productDetail amazon/product/detail
amazon/reviews/list amazon/search amazon/searchByImage chuhaijiang/products/detail
chuhaijiang/products/image-search dld/productBillboard dld/productSearch
echotik/batchProductDetail echotik/batchVideoDetail echotik/category/detail
echotik/category/l1 echotik/category/l2 echotik/category/l3 echotik/category/trend
echotik/influencer/detail echotik/influencer/trend echotik/listProduct
echotik/listProductVideo echotik/listSeller echotik/listSellerProduct echotik/listVideo
echotik/listVideoRank echotik/sellerDetail geekbi/temu/categoryList
geekbi/temu/goodsDetail geekbi/temu/goodsSearch geekbi/temu/mallSearch
googleTrend/getTrendByKeys kalodata/creator/rank kalodata/product/rank
keepa/productSeries sellersprite/market/statistics sellersprite/productSearch
sif/asinKeywords sif/keywordOverview sif/keywordSummary sorftime/walmart/keywordResearch
tool-jungle-scout/keywords/by-keyword'''.split()


def runtime_facts():
    paths = {}
    for index, route in enumerate(ROUTES):
        paths['/apis/v1/linkfox/' + route] = {'post': {
            'operationId': 'linkfox_test_' + str(index), 'summary': route,
            'x-aisa-status': 'enabled', 'x-aisa-validation': 'provider',
            'x-aisa-passthrough': True, 'x-aisa-upstream-path': '/' + route,
            'x-aisa-capabilities': {'mpp': False, 'x402': False},
            'x-aisa-pricing': {'kind': 'provider_cost_multiplier', 'unit': 'credit',
                               'unit_rate_usd': 0.002, 'customer_multiplier': 1,
                               'default_request_estimate_usd': 0.01},
            'requestBody': {'required': True, 'content': {'application/json': {
                'schema': {'type': 'object', 'additionalProperties': True}}}},
            'responses': {'200': {'description': 'Successful response'}}}}
    constraints = {
        'amazon/product/detail': {'asins': {'type': 'string', 'minLength': 1}},
        'amazon/reviews/list': {f'star{i}Num': {'type': 'integer', 'minimum': 0, 'maximum': 100} for i in range(1, 6)},
        'amazon/search': {'includeSellerSpriteData': {'type': 'boolean', 'enum': [False], 'default': False}},
        'keepa/productSeries': {field: {'type': 'integer', 'enum': [0, 1]} for field in ('showPriceFba', 'showPriceFbm', 'showPricePrime')},
        'sorftime/walmart/keywordResearch': {'operation': {'type': 'string', 'default': 'detail', 'enum': [
            'detail', 'marketQuery', 'searchByName', 'searchProducts', 'productKeywords', 'relatedKeywords', 'favoriteAdd', 'favoriteList']}},
        'tool-jungle-scout/keywords/by-keyword': {'needCount': {'type': 'integer', 'minimum': 1, 'maximum': 50, 'default': 20}},
    }
    for route, fields in constraints.items():
        op = paths['/apis/v1/linkfox/' + route]['post']
        op['x-aisa-validation'] = 'mixed'
        op['requestBody']['content']['application/json']['schema']['properties'] = fields
    return {'openapi': '3.1.0', 'info': {'title': 'Linkfox', 'version': 'test',
            'x-aisa-provider': 'linkfox', 'x-aisa-document': {'facts_hash': 'test'}},
            'servers': [{'url': 'https://api.aisa.one'}], 'paths': paths,
            'security': [{'bearerAuth': []}], 'components': {'securitySchemes': {
                'bearerAuth': {'type': 'http', 'scheme': 'bearer'}}}}


class LinkfoxNativeContractsTest(unittest.TestCase):
    def setUp(self):
        self.source = json.loads((ROOT / 'openapi/upstream/linkfox-native.json').read_text())
        self.facts = runtime_facts()

    def composed(self):
        document, pending = compose(self.facts, self.source, unreviewed_runtime=True)
        self.assertEqual(pending, [])
        self.assertEqual(document['info']['x-aisa-document']['response_pending'], [])
        return document

    def test_baseline_reproduces_missing_request_and_response(self):
        before, _ = compose(self.facts, unreviewed_runtime=True)
        op = before['paths']['/apis/v1/linkfox/geekbi/temu/categoryList']['post']
        self.assertFalse(op['requestBody']['content']['application/json']['schema'].get('properties'))
        self.assertEqual(op['responses']['200']['content']['application/json']['schema'], {})
        after = self.composed()['paths']['/apis/v1/linkfox/geekbi/temu/categoryList']['post']
        self.assertIn('parentCatId', after['requestBody']['content']['application/json']['schema']['properties'])
        self.assertIn('categories', after['responses']['200']['content']['application/json']['schema']['properties'])

    def test_registry_and_41_source_routes_are_complete_and_pinned(self):
        entry = yaml.safe_load((ROOT / 'openapi/registry.yaml').read_text())['providers']['linkfox']
        rows, _ = source_configurations('linkfox', entry)
        source = self.source['info']['x-aisa-source']
        self.assertEqual(rows, [(source['url'], 'linkfox-native.json')])
        self.assertEqual(set(self.source['paths']), {'/' + route for route in ROUTES})
        unsigned = copy.deepcopy(self.source)
        del unsigned['info']['x-aisa-source']
        self.assertEqual(source['content_hash'], digest(unsigned))
        for reference in source['references']:
            self.assertRegex(reference['url'], r'https://github.com/linkfox-ai/linkfox-skills/blob/[a-f0-9]{40}/skills/.+/references/api.md')
            self.assertRegex(reference['raw_content_hash'], r'^sha256:[a-f0-9]{64}$')

    def test_every_request_response_example_and_runtime_authority(self):
        document = self.composed()
        validate(document)
        self.assertEqual(len(document['paths']), 41)
        for path, item in document['paths'].items():
            with self.subTest(path=path):
                op, runtime = item['post'], self.facts['paths'][path]['post']
                for key in ('operationId', 'x-aisa-status', 'x-aisa-capabilities', 'x-aisa-pricing'):
                    self.assertEqual(op[key], runtime[key])
                self.assertNotIn('x-aisa-review', op)
                for media in (op['requestBody']['content']['application/json'],
                              op['responses']['200']['content']['application/json']):
                    schema = media['schema']
                    self.assertTrue(schema['properties'])
                    Draft202012Validator.check_schema(schema)
                    self.assertTrue(media['examples'])
                    for example in media['examples'].values():
                        Draft202012Validator(schema).validate(example['value'])
                response = op['responses']['200']['content']['application/json']['schema']
                self.assertNotIn('required', response)
                for local in ('costToken', 'costCredit', '_cache', '_asyncTask', '_http_status'):
                    self.assertNotIn(local, response['properties'])

    def test_required_business_fields_and_gateway_constraints_survive(self):
        ops = self.composed()['paths']
        def body(route):
            return ops['/apis/v1/linkfox/' + route]['post']['requestBody']['content']['application/json']['schema']
        for route, required in [('amazon/reviews/list', ['asin']), ('keepa/productSeries', ['asin', 'domain']),
                                ('tool-jungle-scout/keywords/by-keyword', ['marketplace', 'searchTerms'])]:
            for field in required:
                self.assertIn(field, body(route)['required'])
        jungle = body('tool-jungle-scout/keywords/by-keyword')['properties']['needCount']
        self.assertEqual((jungle['minimum'], jungle['maximum'], jungle['default']), (1, 50, 20))
        self.assertEqual(body('amazon/search')['properties']['includeSellerSpriteData']['enum'], [False])
        self.assertNotIn('favoriteChange', body('sorftime/walmart/keywordResearch')['properties']['operation']['enum'])
        for field in ('name', 'keyword', 'productId', 'pattern'):
            self.assertIn(field, body('sorftime/walmart/keywordResearch')['properties'])
        reviews = ops['/apis/v1/linkfox/amazon/reviews/list']['post']
        self.assertIn('b222e5f4e88586a36b0f3799a8840dc4918c61a5', self.source['paths']['/amazon/reviews/list']['post']['externalDocs']['url'])
        response = reviews['responses']['200']['content']['application/json']['schema']['properties']
        self.assertIn('reviewId', response['data']['items']['properties'])
        self.assertNotIn('taskId', response)

    def test_alternative_inputs_and_walmart_response_variants(self):
        ops = self.composed()['paths']
        for route in ('alibaba1688/imageSearch', 'echotik/batchProductDetail', 'echotik/batchVideoDetail', 'echotik/influencer/detail'):
            schema = ops['/apis/v1/linkfox/' + route]['post']['requestBody']['content']['application/json']['schema']
            self.assertFalse(Draft202012Validator(schema).is_valid({}), route)
        op = ops['/apis/v1/linkfox/sorftime/walmart/keywordResearch']['post']
        response = op['responses']['200']['content']['application/json']['schema']
        for value in (None, [], ['folder'], 0, {'Keyword': 'water bottle'}, [{'Keyword': 'water bottle'}]):
            Draft202012Validator(response).validate({'errcode': 200, 'code': 200, 'data': {'value': value}})
        examples = op['requestBody']['content']['application/json']['examples']
        self.assertEqual({e['value']['operation'] for e in examples.values()}, {
            'marketQuery', 'searchByName', 'searchProducts', 'detail', 'productKeywords',
            'relatedKeywords', 'favoriteAdd', 'favoriteList'})

    def test_public_projection_and_all_82_page_bindings(self):
        document = self.composed()
        for language in ('en', 'zh'):
            public = project(document, language=language)
            self.assertEqual(set(public['paths']), set(document['paths']))
            for path, item in public['paths'].items():
                self.assertTrue(item['post']['requestBody']['content']['application/json']['schema']['properties'])
                self.assertTrue(item['post']['responses']['200']['content']['application/json']['schema']['properties'])
            localized = localize_tree(public, {'entries': {}}, allow_untranslated=True)
            self.assertEqual(strip_translatable(localized), strip_translatable(public))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'docs.json').write_text(json.dumps({'navigation': {'tabs': []}}))
            changes = {}
            generate_pages(root, 'linkfox', document, changes, page_references=[])
            pages = {str(p.relative_to(root)): text for p, text in changes.items() if p.suffix == '.mdx'}
            self.assertEqual(len(pages), 82)
            self.assertEqual(sum(p.startswith('zh/') for p in pages), 41)
            for page, text in pages.items():
                self.assertIn('POST /apis/v1/linkfox/', text)
                self.assertIn('openapi/zh/linkfox.json' if page.startswith('zh/') else 'openapi/linkfox.json', text)


if __name__ == '__main__':
    unittest.main()
