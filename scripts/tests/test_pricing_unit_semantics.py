"""Customer estimates must not advertise internal cost units as sale prices."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pricing_prose import clean_document, pricing_summary
from readable_contract_notes import readable_block, update_readable_block
from runtime_localize_openapi_zh import localize_tree
from sales_catalog_projection import project_sales_catalog
from public_surface_checks import request_blocks

class PricingUnitSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.path = '/apis/v1/amazon/get-category-products-v1'
        # Freeze the reported declaration; a later legitimate price update in
        # the generated mirrors must not break this presentation regression.
        self.pricing = {'cost_contract': 'response_units', 'customer_multiplier': 1.0,
                        'customer_pricing': 'provider_cost_multiplier',
                        'default_request_estimate_usd': .01476, 'estimate_source': 'profile_seed',
                        'evidence_source': 'response_header', 'unit': 'provider_credit', 'unit_rate_usd': .000001}
        self.operation = {'operationId': 'amazon.get-category-products-v1',
                          'x-aisa-pricing': self.pricing,
                          'description': '<!-- aisa-pricing:start -->\nUsage-based billing; '
                                         'Default request estimate: $0.01476 USD (not a fixed price). '
                                         'Declared unit rate: $0.000001 USD per provider_credit.\n<!-- aisa-pricing:end -->',
                          'responses': {'200': {'description': 'OK'}}}
        self.source = {'openapi': '3.1.0', 'info': {'title': 'Pricing regression', 'version': '1'},
                       'paths': {self.path: {'get': self.operation}}}

    def test_amazon_estimate_is_prominent_without_a_micro_unit_sale_price(self):
        before = copy.deepcopy(self.pricing)
        for language, label, explanation in (
                ('en', 'Default request estimate: $0.01476 USD', 'actual usage'),
                ('zh', '默认请求预估费用：$0.01476 USD', '实际用量')):
            with self.subTest(language=language):
                summary = pricing_summary(self.pricing, language)
                self.assertIn(label, summary)
                self.assertIn(explanation, summary)
                self.assertNotIn('0.000001', summary)
                self.assertNotIn('provider_credit', summary)
                self.assertNotIn('Usage-based billing', summary)
                self.assertNotIn('按用量计费', summary)
        self.assertEqual(self.pricing, before)

    def test_generic_units_do_not_infer_money_items_or_success_billing(self):
        for rate in (0, .000001, .0001, .014):
            for evidence in ('response_header', 'response_body', 'request_snapshot'):
                with self.subTest(rate=rate, evidence=evidence):
                    pricing = dict(self.pricing, unit_rate_usd=rate, evidence_source=evidence,
                                   customer_multiplier=2)
                    text = pricing_summary(pricing)
                    self.assertIn('$0.01476 USD', text)  # Estimate is already published.
                    self.assertNotIn('$0.02952', text)
                    for unsupported in ('Declared unit rate', 'per successful request',
                                        'per result', 'per item', 'micro-USD', 'provider_credit'):
                        self.assertNotIn(unsupported, text)

    def test_supplier_rates_are_not_customer_unit_prices(self):
        for unit in ('tavily_credit', 'similarweb_credit', 'firecrawl_credit'):
            pricing = dict(self.pricing, unit=unit, unit_rate_usd=.075)
            for language in ('en', 'zh'):
                text = pricing_summary(pricing, language)
                self.assertIn('$0.01476', text)
                self.assertNotIn('$0.075', text)
                self.assertNotIn(unit, text)

    def test_page_shows_customer_price_and_request_without_supplier_fields(self):
        before = copy.deepcopy(self.operation)
        for language in ('en', 'zh'):
            context = dict(document=self.source, path=self.path, method='get', spec_path='openapi/amazon.json')
            text = readable_block(self.operation, language, **context)
            for internal in ('unit_rate_usd', 'customer_multiplier', 'provider_credit', 'cost_contract',
                             'micro-USD', 'Cost conversion', '成本换算', '公开参考倍率'):
                self.assertNotIn(internal, text)
            record = next(iter(request_blocks(text).values()))[0]
            self.assertNotIn('x-aisa-pricing', record['request'])
            self.assertEqual(record['price_summary'], pricing_summary(self.pricing, language))
            self.assertEqual(update_readable_block(text, self.operation, language, **context), text)
        self.assertEqual(self.operation, before)

    def test_fixed_customer_price_hides_supplier_math_from_customer_prose(self):
        for unit in ('provider_credit', 'firecrawl_credit'):
            pricing = dict(self.pricing, customer_pricing='fixed_success', unit=unit)
            operation = dict(self.operation, **{'x-aisa-pricing': pricing})
            for language, label in (('en', '$0.01476 USD per successful request'),
                                    ('zh', '每次成功请求 $0.01476 USD')):
                with self.subTest(unit=unit, language=language):
                    summary = pricing_summary(pricing, language)
                    text = readable_block(operation, language)
                    self.assertIn(label, summary)
                    self.assertIn(label, text)
                    for internal in ('0.000001', unit, 'response_units', 'multiplier', '倍率',
                                     'micro-USD', 'Cost conversion', '成本换算', 'not a fixed price',
                                     '不是固定价格', 'Default request reference estimate', '默认请求参考估价'):
                        self.assertNotIn(internal, text)
                        self.assertNotIn(internal, summary)
                    document = dict(self.source, paths={self.path: {'get': operation}})
                    full = readable_block(operation, language, document=document, method='get',
                                          path=self.path, spec_path='openapi/amazon.json')
                    record = next(iter(request_blocks(full).values()))[0]
                    self.assertNotIn('x-aisa-pricing', record['request'])

    def test_supplier_fixed_label_does_not_prove_a_fixed_customer_price(self):
        pricing = dict(self.pricing, cost_contract='fixed_success')
        for language in ('en', 'zh'):
            text = pricing_summary(pricing, language)
            self.assertIn('$0.01476', text)
            self.assertNotIn('per successful request', text)
            self.assertNotIn('每次成功请求', text)

    def test_openapi_localization_and_sales_replace_old_summary_without_metadata_drift(self):
        original = copy.deepcopy(self.source)
        document = clean_document(self.source)
        operation = document['paths'][self.path]['get']
        self.assertNotIn('Declared unit rate:', operation['description'])
        self.assertNotIn('provider cost', operation['description'])
        self.assertEqual(operation['x-aisa-pricing'], self.pricing)
        self.assertEqual(clean_document(document), document)
        localized = localize_tree(document, {'entries': {}}, allow_untranslated=True)
        translated = localized['paths'][self.path]['get']
        self.assertNotIn('上游成本', translated['description'])
        self.assertNotIn('声明的单位费率', translated['description'])
        self.assertEqual(translated['x-aisa-pricing'], self.pricing)
        sales = project_sales_catalog(document, 'a' * 64)['document']
        self.assertEqual(sales['paths'][self.path]['get']['description'], operation['description'])
        self.assertEqual(self.source, original)


if __name__ == '__main__':
    unittest.main()
