"""Pricing survives real composition and canonical page regeneration."""
import copy
import json
import unittest

import canonical_import
import test_full_registry
from test_customer_price_presentation import RESOURCE_PRICING, SOCIAL_PRICING
from test_runtime_contracts import operation


OLD_SUMMARY = ('<!-- aisa-pricing:start -->\n'
               'Declared unit rate: $0.000001 USD per provider_credit.\n'
               '<!-- aisa-pricing:end -->')


def pricing_cases():
    """Literal customer expectations; do not ask the renderer for its own oracle."""
    cases = {
        'success': ({'customer_pricing': 'fixed_success', 'default_request_estimate_usd': .012},
                    '$0.012 USD per successful request', '每次成功请求 $0.012 USD'),
        'job': ({'kind': 'fixed_request', 'estimate_source': 'configured_fixed_price',
                 'default_request_estimate_usd': .1}, '$0.1 USD per completed job', '每个完成的任务 $0.1 USD'),
        'resource': (copy.deepcopy(RESOURCE_PRICING), '$0.05 USD per delivered read', '每次成功交付查询 $0.05 USD'),
        'results': ({'cost_contract': 'response_count', 'default_request_estimate_usd': .1975},
                    'Charged for the actual billable results.', '按实际计费结果数量收费。'),
        'async': ({'kind': 'metered_result', 'customer_unit_price_usd': .005},
                  '$0.005 USD per billable unit', '每计费单位 $0.005 USD'),
        'social': (copy.deepcopy(SOCIAL_PRICING), 'an X post costs $0.015', 'X 普通帖子 $0.015 USD'),
        'model': ({'kind': 'model_catalog', 'description': 'Fixed price whatever n is.'},
                  'regardless of n; token-priced models charge for actual token usage', '不随 n 改变；按 token 定价的模型按实际用量收费'),
        'free': ({'kind': 'no_customer_charge'}, 'No additional charge for this operation.', '此操作不另收费。'),
        'archive': ({'kind': 'unpriced'}, 'Historical archive: disabled, cannot be called, and no price is published.',
                    '历史归档接口：已停用，不可调用，价格未发布。'),
        'unknown': ({'kind': 'future_tariff'}, 'Billing method unavailable.', '计费方式暂不可用。'),
        'adyntel': ({'cost_contract': 'response_units', 'estimate_source': 'unavailable',
                     'estimate_unavailable_reason': 'reference_request_unavailable'},
                    'A price estimate is not currently available.', '当前暂无预估金额。'),
    }
    for cost in ('fixed_success', 'request_formula', 'plan_units'):
        cases[cost] = ({'cost_contract': cost, 'default_request_estimate_usd': .08},
                       'Request pricing. Default request estimate: $0.08 USD.', '请求费用。 默认请求预估费用：$0.08 USD。')
    for cost in ('response_components', 'response_sku'):
        cases[cost] = ({'cost_contract': cost, 'default_request_estimate_usd': .3},
                       'Charged for the combined usage of the billable components.', '按各计费项目的实际用量合计收费。')
    for cost in ('response_usd', 'response_units'):
        cases[cost] = ({'cost_contract': cost, 'default_request_estimate_usd': .01476},
                       'Usage-based pricing. Default request estimate: $0.01476 USD.', '按实际用量收费。 默认请求预估费用：$0.01476 USD。')
    for pricing, _, _ in cases.values():
        pricing.update(customer_multiplier=3, unit_rate_usd=.000001, unit='provider_credit')
    return cases


def pricing_document():
    document = test_full_registry.contract('prices')
    template = copy.deepcopy(operation(document))
    document['paths'] = {}
    for name, (pricing, _, _) in pricing_cases().items():
        op = copy.deepcopy(template)
        op.update(operationId=name, description='Find records.\n\n' + OLD_SUMMARY)
        op['x-aisa-pricing'] = pricing
        op['x-aisa-docs-url'] = 'https://aisa.one/docs/api-reference/prices/' + name
        if name == 'archive':
            op['x-aisa-status'] = 'disabled'
        document['paths']['/apis/v1/prices/' + name] = {'get': op}
    return document


def seed_old_pages(root):
    for prefix in ('', 'zh/'):
        for name in pricing_cases():
            summary = OLD_SUMMARY
            if name in ('free', 'archive'):
                summary = ('<!-- aisa-pricing:start -->\n'
                           + ('No charge.' if name == 'free' else 'Price not yet published; this operation is unavailable.')
                           + '\n<!-- aisa-pricing:end -->')
            page = root / (prefix + 'api-reference/prices/' + name + '.mdx')
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text('---\ntitle: Records\ndescription: ' + json.dumps(OLD_SUMMARY)
                            + '\nopenapi: "openapi/' + prefix + 'prices.json GET /apis/v1/prices/' + name
                            + '"\nx-aisa-operation-id: ' + name + '\n---\n\nManual usage example.\n\n'
                            + summary + '\n')


def assert_customer_pages(test, root):
    for name, (_, english, chinese) in pricing_cases().items():
        for prefix, expected, heading in (('', english, '## Cost and request rules'),
                                           ('zh/', chinese, '## 费用与请求规则')):
            with test.subTest(operation=name, language=prefix or 'en'):
                text = (root / (prefix + 'api-reference/prices/' + name + '.mdx')).read_text()
                # Multi-price paragraphs escape dollars to avoid MDX math.
                test.assertIn(expected, text.replace('\\$', '$'))
                test.assertIn('Manual usage example.', text)
                test.assertEqual(text.count(heading), 1)
                for internal in ('aisa-pricing:', 'provider_credit', 'unit_rate_usd', 'customer_multiplier',
                                 'micro-USD', '0.000001', 'x-aisa-pricing'):
                    test.assertNotIn(internal, text)


def page_snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*.mdx')}


class PricingGenerationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_full_registry.FullRegistryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.root
        seed_old_pages(self.root)

    def test_real_stage_regenerates_all_families_and_follows_updated_source_prices(self):
        document = pricing_document()
        original = copy.deepcopy(document)
        self.fixture.sources({'prices': document})
        self.fixture.publish(self.fixture.pull()[0])
        assert_customer_pages(self, self.root)
        first = page_snapshot(self.root)
        self.fixture.publish(self.fixture.pull()[0])
        self.assertEqual(first, page_snapshot(self.root))
        published = json.loads((self.root / 'openapi/prices.json').read_text())
        for path, item in original['paths'].items():
            op = published['paths'][path]['get']
            self.assertEqual(op['x-aisa-pricing'], item['get']['x-aisa-pricing'])
            self.assertEqual(op['description'], 'Find records.')
            self.assertEqual(op['parameters'], item['get']['parameters'])
        self.assertEqual(document, original)

        # A subsequent source price change must replace the generated price.
        document['paths']['/apis/v1/prices/success']['get']['x-aisa-pricing']['default_request_estimate_usd'] = .024
        document['info']['x-aisa-document']['facts_hash'] += '-new-price'
        self.fixture.sources({'prices': document})
        self.fixture.publish(self.fixture.pull()[0])
        for prefix in ('', 'zh/'):
            text = (self.root / (prefix + 'api-reference/prices/success.mdx')).read_text()
            self.assertIn('$0.024', text)
            self.assertNotIn('$0.012', text)

    def test_canonical_projection_regenerates_pages_without_mutating_verified_contracts(self):
        document = pricing_document()
        # The producer cleans descriptions before hashing; the consumer must
        # preserve those verified bytes, while replacing old page descriptions.
        for item in document['paths'].values():
            item['get']['description'] = 'Find records.'
        raw = json.dumps(document).encode()
        (self.root / 'openapi/prices.json').write_bytes(raw)
        (self.root / 'llms.txt').write_text('Discovery\n')
        metadata = {'registry': {'providers': {'prices': {}}},
                    'coverage': {'providers': {'prices': []}}, 'pending': {'providers': {'prices': []}}}
        for repeat in range(2):
            outputs = canonical_import.project_surfaces(self.root, {'prices': raw}, raw, metadata)
            self.assertEqual(outputs['openapi/prices.json'], raw)
            self.assertEqual(outputs['openapi/openapi.json'], raw)
            for name, value in outputs.items():
                path = self.root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(value)
            assert_customer_pages(self, self.root)
            if repeat:
                self.assertEqual(first, page_snapshot(self.root))
            first = page_snapshot(self.root)

    def test_credit_tariffs_disappear_from_real_stage_and_canonical_pages(self):
        document = pricing_document()
        op = document['paths']['/apis/v1/prices/response_units']['get']
        op['parameters'] = [
            {'in': 'query', 'name': 'pageSize', 'schema': {'type': 'integer', 'minimum': 1, 'maximum': 100},
             'description': '1-100. THIS IS THE PRICE — 1 credit per company returned'},
            {'in': 'query', 'name': 'expand', 'schema': {'type': 'string', 'enum': ['workforce']},
             'description': 'Supported values: workforce (adds the workforce field; costs 5 credits per company).'},
        ]
        original = copy.deepcopy(document)
        for prefix in ('', 'zh/'):
            page = self.root / (prefix + 'api-reference/prices/response_units.mdx')
            with page.open('a') as handle:
                handle.write('\nHTTP 404 still returns a valid JSON body and is billed 1 credit; errors are not billed.\n')
        self.fixture.sources({'prices': document})
        for repeat in range(2):
            self.fixture.publish(self.fixture.pull()[0])
            for prefix in ('', 'zh/'):
                text = (self.root / (prefix + 'api-reference/prices/response_units.mdx')).read_text()
                self.assertNotIn('credit', text.lower())
                for preserved in ('1-100', 'workforce', 'HTTP 404', 'errors are not billed', '$0.01476'):
                    self.assertIn(preserved, text)
            if repeat:
                self.assertEqual(first, page_snapshot(self.root))
            first = page_snapshot(self.root)
        native_path = self.root / 'openapi/prices.json'
        raw = native_path.read_bytes()
        native = json.loads(raw)
        actual = native['paths']['/apis/v1/prices/response_units']['get']
        self.assertEqual(actual['x-aisa-pricing'], op['x-aisa-pricing'])
        for before, after in zip(op['parameters'], actual['parameters']):
            self.assertEqual(before['schema'], after['schema'])
        self.assertEqual(document, original)
        (self.root / 'llms.txt').write_text('Discovery\n')
        metadata = {'registry': {'providers': {'prices': {}}},
                    'coverage': {'providers': {'prices': []}}, 'pending': {'providers': {'prices': []}}}
        outputs = canonical_import.project_surfaces(self.root, {'prices': raw}, raw, metadata)
        self.assertEqual(outputs['openapi/prices.json'], raw)
        for prefix in ('', 'zh/'):
            name = prefix + 'api-reference/prices/response_units.mdx'
            page = outputs.get(name, (self.root / name).read_bytes()).decode()
            self.assertNotIn('credit', page.lower())
            self.assertIn('$0.01476', page)


if __name__ == '__main__':
    unittest.main()
