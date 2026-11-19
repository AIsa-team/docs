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
chuhaijiang/products/image-search chuhaijiang/products/search
chuhaijiang/upload/presigned-url dld/productBillboard dld/productSearch
echotik/batchProductDetail echotik/batchVideoDetail echotik/category/detail
echotik/category/l1 echotik/category/l2 echotik/category/l3 echotik/category/trend
echotik/influencer/detail echotik/influencer/trend echotik/listProduct
echotik/listProductVideo echotik/listSeller echotik/listSellerProduct echotik/listVideo
echotik/listVideoRank echotik/sellerDetail geekbi/temu/categoryList
geekbi/temu/goodsDetail geekbi/temu/goodsSearch geekbi/temu/mallSearch
googleTrend/getTrendByKeys kalodata/creator/rank kalodata/product/rank
jiimore/getNicheInfoByKeyword keepa/productSeries sellersprite/market/statistics sellersprite/productSearch
sif/asinKeywords sif/keywordOverview sif/keywordSummary sorftime/walmart/keywordResearch
tool-jungle-scout/keywords/by-keyword'''.split()


NEXT_ROUTES = '''chuhaijiang/ad-creative/ads/detail
chuhaijiang/ad-creative/ads/related-products
chuhaijiang/ad-creative/ads/search
chuhaijiang/ad-creative/creatives/detail
chuhaijiang/ad-creative/creatives/search
chuhaijiang/creators/detail
chuhaijiang/creators/rankings/agencies
chuhaijiang/creators/rankings/commercial
chuhaijiang/creators/rankings/growth
chuhaijiang/creators/related-lives
chuhaijiang/creators/related-products
chuhaijiang/creators/related-videos
chuhaijiang/creators/search
chuhaijiang/lives/detail
chuhaijiang/lives/related-products
chuhaijiang/lives/search
chuhaijiang/products/rankings/most-promoted
chuhaijiang/products/rankings/new-arrivals
chuhaijiang/products/rankings/top-selling
chuhaijiang/products/related-creators
chuhaijiang/products/related-lives
chuhaijiang/products/related-videos
chuhaijiang/products/reviews
chuhaijiang/sellers/detail
chuhaijiang/sellers/rankings/most-promoted
chuhaijiang/sellers/rankings/top-selling
chuhaijiang/sellers/related-creators
chuhaijiang/sellers/related-products
chuhaijiang/sellers/related-videos
chuhaijiang/sellers/search
chuhaijiang/videos/detail
chuhaijiang/videos/related-products
chuhaijiang/videos/reviews
chuhaijiang/videos/search
kalodata/creator/detail
kalodata/livestream/detail
kalodata/livestream/rank
kalodata/product/detail
kalodata/shop/detail
kalodata/shop/rank
kalodata/video/detail
kalodata/video/rank
echotik/getVideoDownloadUrl
echotik/listNewProductRank
geekbi/temu/categorySearch
geekbi/temu/keywordSearch
geekbi/temu/siteList
amazon/alexaSearch
amazon/opportunity/searchByMetrics
amazon/policyFeed
amazon/policyFeedDetail
jiimore/getNicheInfo
jiimore/getNicheInfoByAsin
jiimore/getNicheReviewFromKeyword
jiimore/pageAsinsByAsin
jiimore/productDiscovery
sellersprite/competitor-lookup
sellersprite/market/research
sellersprite/traffic/keyword
sif/asinSummary
tool-jungle-scout/keywords/historical-search-volume
tool-jungle-scout/keywords/share-of-voice
tool-jungle-scout/sales-estimates/query
googleTrend/getTrendByTime'''.split()
ROUTES += NEXT_ROUTES

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
    upload = paths['/apis/v1/linkfox/chuhaijiang/upload/presigned-url']['post']
    upload['x-aisa-pricing'] = {'kind': 'fixed_success', 'price_usd': 0.001}
    constraints = {
        'amazon/opportunity/searchByMetrics': {'limit': {'type': 'integer', 'minimum': 1, 'maximum': 200, 'default': 25}},
        'amazon/alexaSearch': {'prompts': {'type': 'array', 'minItems': 1, 'maxItems': 1, 'items': {'type': 'string', 'minLength': 1, 'maxLength': 255}}},
        'chuhaijiang/upload/presigned-url': {'fileName': {'type': 'string', 'minLength': 1}},
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

    def test_registry_and_108_source_routes_are_complete_and_pinned(self):
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
        self.assertEqual(len(document['paths']), 108)
        for path, item in document['paths'].items():
            with self.subTest(path=path):
                op, runtime = item['post'], self.facts['paths'][path]['post']
                for key in ('operationId', 'x-aisa-status', 'x-aisa-capabilities', 'x-aisa-pricing'):
                    self.assertEqual(op[key], runtime[key])
                self.assertNotIn('x-aisa-review', op)
                for media in (op['requestBody']['content']['application/json'],
                              op['responses']['200']['content']['application/json']):
                    schema = media['schema']
                    self.assertTrue(schema['properties'] or path.endswith('/geekbi/temu/siteList'))
                    Draft202012Validator.check_schema(schema)
                    self.assertTrue(media['examples'])
                    for example in media['examples'].values():
                        Draft202012Validator(schema).validate(example['value'])
                response = op['responses']['200']['content']['application/json']['schema']
                self.assertNotIn('required', response)
                # Jiimore explicitly documents costToken in the native HTTP body.
                if not path.endswith('/jiimore/getNicheInfoByKeyword') and path.removeprefix('/apis/v1/linkfox/') not in NEXT_ROUTES:
                    self.assertNotIn('costToken', response['properties'])
                for local in ('costCredit', '_cache', '_asyncTask', '_http_status'):
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
        # Supplementary provider tables must reach the field documentation,
        # rather than leave an unresolved "see below" in a generated page.
        for route, field, values in [
            ('alibaba1688/imageSearch', 'filter', ['1688Selection', 'TWFL']),
            ('alibaba1688/imageSearch', 'productCollectionId', ['262105288', '262185282']),
            ('amazon/product/detail', 'amazonDomain', ['amazon.com', 'amazon.com.be']),
            ('keepa/productSeries', 'domain', ['`1`', '`12`', 'string']),
            ('sellersprite/productSearch', 'dimensionType', ['EL15O', 'SPO', 'JP', 'CA']),
            ('sif/keywordSummary', 'condition', ['nfPosition', 'sbvKeywordCnt.in']),
        ]:
            description = body(route)['properties'][field]['description']
            for value in values:
                self.assertIn(value, description)
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

    def test_jiimore_market_contract_and_parameter_boundaries(self):
        op = self.composed()['paths']['/apis/v1/linkfox/jiimore/getNicheInfoByKeyword']['post']
        request = op['requestBody']['content']['application/json']['schema']
        validator = Draft202012Validator(request)
        validator.validate({'keyword': 'water bottle'})
        validator.validate({'keyword': 'water bottle', 'countryCode': 'DE', 'pageSize': 100,
                            'newProductRateT180': 0.5})
        for invalid in ({}, {'keyword': 'x' * 1001}, {'keyword': 'x', 'countryCode': 'GB'},
                        {'keyword': 'x', 'pageSize': 9}, {'keyword': 'x', 'pageSize': 101},
                        {'keyword': 'x', 'newProductRateT180': 50}):
            self.assertFalse(validator.is_valid(invalid), invalid)
        self.assertEqual(len(request['properties']), 45)
        self.assertEqual(len(request['properties']['sortField']['enum']), 27)
        response = op['responses']['200']['content']['application/json']['schema']['properties']
        market = response['data']['items']['properties']
        self.assertIn('unitsSoldWeekly', market)
        self.assertNotIn('unitsSoldT7', market)
        self.assertEqual(set(market['cpc']['properties']), {'high', 'medium', 'low'})
        self.assertEqual(response['columns']['items'], {})

    def test_new_batch_dependencies_nested_fields_and_limits(self):
        ops = self.composed()['paths']
        def request(route):
            return ops['/apis/v1/linkfox/' + route]['post']['requestBody']['content']['application/json']['schema']
        def response(route):
            return ops['/apis/v1/linkfox/' + route]['post']['responses']['200']['content']['application/json']['schema']['properties']
        self.assertEqual(len(NEXT_ROUTES), 64)
        self.assertEqual(len(set(ROUTES)), 108)
        for route in ('amazon/opportunity/reportByKeyword', 'keepa/productRequest', 'keepa/productSearch',
                      'sorftime/walmart/categoryMarket', 'sorftime/walmart/productAnalysis',
                      'tool-jungle-scout/keywords/by-asin', 'tool-jungle-scout/product-database/query',
                      'geekbi/temu/goodsImageSearch'):
            self.assertNotIn(route, ROUTES)
        metrics = request('amazon/opportunity/searchByMetrics')
        self.assertEqual(len(metrics['properties']), 59)
        self.assertEqual(metrics['properties']['limit']['default'], 25)
        for limit in (1, 25, 26, 200):
            Draft202012Validator(metrics).validate({'keyword': 'kettle', 'limit': limit})
        for limit in (0, 201, 1.5, '25', None):
            self.assertFalse(Draft202012Validator(metrics).is_valid({'keyword': 'kettle', 'limit': limit}))
        alexa = Draft202012Validator(request('amazon/alexaSearch'))
        alexa.validate({'prompts': ['best kettle']})
        for prompts in ([], ['one', 'two'], ['x' * 256], [None]):
            self.assertFalse(alexa.is_valid({'prompts': prompts}))
        self.assertEqual(request('geekbi/temu/siteList')['properties'], {})
        self.assertIn('/apis/v1/linkfox/chuhaijiang/creators/search',
                      request('chuhaijiang/creators/detail')['properties']['id']['description'])
        self.assertIn('regionId', request('geekbi/temu/keywordSearch')['properties'])
        self.assertEqual(set(response('jiimore/getNicheInfoByAsin')['nicheInfoVoList']['items']['properties']['cpc']['properties']), {'high', 'medium', 'low'})
        voice = response('tool-jungle-scout/keywords/share-of-voice')['shareOfVoice']['properties']
        self.assertIn('conversionRate', voice['topAsins']['items']['properties'])
        self.assertIn('organicBasicSov', voice['brands']['items']['properties'])
        self.assertIn('estimatedUnitsSold', response('tool-jungle-scout/sales-estimates/query')['salesEstimateList']['items']['properties']['dailyEstimates']['items']['properties'])
        order = request('sellersprite/competitor-lookup')['properties']
        self.assertNotIn('desc', order)
        self.assertIn('desc', order['order']['properties'])

    def test_public_projection_and_all_216_page_bindings(self):
        document = self.composed()
        for language in ('en', 'zh'):
            public = project(document, language=language)
            self.assertEqual(set(public['paths']), set(document['paths']))
            for path, item in public['paths'].items():
                self.assertTrue(item['post']['requestBody']['content']['application/json']['schema']['properties'] or path.endswith('/geekbi/temu/siteList'))
                self.assertTrue(item['post']['responses']['200']['content']['application/json']['schema']['properties'])
            localized = localize_tree(public, {'entries': {}}, allow_untranslated=True)
            self.assertEqual(strip_translatable(localized), strip_translatable(public))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'docs.json').write_text(json.dumps({'navigation': {'tabs': []}}))
            changes = {}
            generate_pages(root, 'linkfox', document, changes, page_references=[])
            pages = {str(p.relative_to(root)): text for p, text in changes.items() if p.suffix == '.mdx'}
            self.assertEqual(len(pages), 216)
            self.assertEqual(sum(p.startswith('zh/') for p in pages), 108)
            for page, text in pages.items():
                self.assertIn('POST /apis/v1/linkfox/', text)
                self.assertIn('openapi/zh/linkfox.json' if page.startswith('zh/') else 'openapi/linkfox.json', text)


if __name__ == '__main__':
    unittest.main()
