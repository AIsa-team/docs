import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pricing_prose import clean_text, clean_document, clean_page, pricing_summary, PRICE_BEGIN, NOTICE
from compose_openapi import compose
from test_runtime_contracts import facts, operation, mirror

ROOT = Path(__file__).resolve().parents[2]


class PricingProseTests(unittest.TestCase):
    def test_visible_price_tracks_runtime_in_openapi_localization_pages_and_sales(self):
        from readable_contract_notes import readable_block
        from runtime_localize_openapi_zh import localize_tree
        from sales_catalog_projection import project_sales_catalog
        runtime = facts()
        operation(runtime)['description'] = 'Domain Rating. Billed $0.02 per successful call.'
        operation(runtime)['x-aisa-pricing'] = {'cost_contract': 'fixed_success', 'default_request_estimate_usd': .08}
        document, _ = compose(runtime)
        public = operation(document)
        self.assertIn('Published reference price: $0.08 USD per successful request.', public['description'])
        self.assertNotIn('$0.02', public['description'])
        self.assertIn('$0.08 USD', readable_block(public))
        localized = localize_tree(document, {'entries': {}}, allow_untranslated=True)
        self.assertIn('每次成功请求 $0.08 USD', operation(localized)['description'])
        self.assertIn('每次成功请求 $0.08 USD', readable_block(public, 'zh'))
        sales = project_sales_catalog(document, 'a' * 64)['document']
        self.assertEqual(operation(sales)['description'], public['description'])
        self.assertEqual(clean_document(document), document)
        operation(document)['x-aisa-pricing']['default_request_estimate_usd'] = .12
        updated = clean_document(document)
        description = operation(updated)['description']
        self.assertIn('$0.12 USD', description)
        self.assertNotIn('$0.08', description)
        self.assertEqual(description.count(PRICE_BEGIN), 1)
        operation(updated).pop('x-aisa-pricing')
        self.assertNotIn('$0.12', operation(clean_document(updated))['description'])

    def test_fixed_zero_usage_units_and_missing_prices_have_distinct_labels(self):
        fixed = pricing_summary({'cost_contract': 'fixed_success', 'default_request_estimate_usd': .08, 'customer_multiplier': 2})
        self.assertIn('$0.08 USD per successful request', fixed)
        self.assertNotIn('$0.16', fixed)
        free = pricing_summary({'cost_contract': 'explicit_zero', 'customer_pricing': 'fixed_success', 'default_request_estimate_usd': 0})
        self.assertIn('$0 USD per successful request', free)
        usage = pricing_summary({'cost_contract': 'response_count', 'default_request_estimate_usd': 1.275, 'unit_rate_usd': .075, 'unit': 'similarweb_credit'})
        self.assertIn('estimate: $1.275 USD (not a fixed price)', usage)
        self.assertIn('$0.075 USD per similarweb_credit', usage)
        self.assertNotIn('per row', usage)
        for value in (None, True, -1, float('inf'), float('nan'), '0.08'):
            self.assertNotIn('$', pricing_summary({'default_request_estimate_usd': value}))
        self.assertNotIn('$', pricing_summary({'default_request_estimate_usd': .08, 'reference_unavailable': True}))

    def test_page_rate_table_and_translation_cannot_restore_stale_prices(self):
        from readable_contract_notes import update_readable_block
        from runtime_localize_openapi_zh import translation, key_for
        page = '---\ntitle: Enrichment\n---\n\n| Section | Credits | Price |\n|---|---|---|\n| funding | 3 | $0.24 |\n'
        op = {'x-aisa-pricing': {'default_request_estimate_usd': .08}}
        result = update_readable_block(clean_page(page), op)
        self.assertNotIn('$0.24', result)
        self.assertIn('| funding | 3 |', result)
        self.assertIn('0.08', result)
        self.assertEqual(update_readable_block(clean_page(result), op), result)
        source = 'Domain rating'
        catalog = {'entries': {key_for(source): {'source': source, 'translation': '查询域名。每次收费 $0.02。'}}}
        self.assertNotIn('$0.02', translation(catalog, source))

    def test_page_notice_never_lands_inside_a_component_or_glued_to_a_fence(self):
        page = ('---\ntitle: Cancel\n---\nLead.\n\nReference price: $0.02 USD per successful request.\n\n'
                '## Example\n\n<CodeGroup>\n```bash REST\ncurl x\n```\n</CodeGroup>\n')
        result = clean_page(page)
        self.assertNotIn('$0.02', result)
        self.assertIn('\n```bash REST\n', result)
        self.assertNotIn(NOTICE + '```', result)
        self.assertLess(result.index(NOTICE), result.index('## Example'))
        self.assertEqual(result.count(NOTICE), 1)
        self.assertEqual(clean_page(result), result)

    def test_runtime_pricing_wins_over_old_prose_without_mutating_inputs(self):
        runtime, upstream = facts('provider'), mirror()
        operation(runtime).pop('description')
        operation(runtime)['x-aisa-pricing'] = {'default_request_estimate_usd': .08}
        operation(upstream)['description'] = 'Domain Rating. Billed $0.02 per successful call; 4xx/5xx are not charged.'
        originals = copy.deepcopy((runtime, upstream))
        document, pending = compose(runtime, upstream)
        self.assertFalse(pending)
        result = operation(document)
        self.assertNotIn('$0.02', result['description'])
        self.assertIn('4xx/5xx are not charged', result['description'])
        self.assertEqual(result['x-aisa-pricing'], {'default_request_estimate_usd': .08})
        self.assertEqual((runtime, upstream), originals)

    def test_declarations_only_and_arbitrarily_named_properties(self):
        sample = {'description': 'Billed $9 per call', '$ref': 'literal', 'price': '$9'}
        doc = {'paths': {'/price': {'get': {'description': 'Billed $2 per call.',
            'x-aisa-pricing': sample, 'x-aisa-source': sample,
            'responses': {'200': {'description': 'Billed $2 per call.',
                'content': {'application/json': {'example': sample, 'schema': {
                    'type': 'object', 'properties': {'description': {
                        'type': 'string', 'description': 'Billed $3 per call.',
                        'default': sample, 'examples': [sample], 'enum': [sample]}}}}}}}}}}}
        before = copy.deepcopy(doc)
        out = clean_document(doc)['paths']['/price']['get']
        self.assertEqual(out['x-aisa-pricing'], sample)
        self.assertEqual(out['x-aisa-source'], sample)
        media = out['responses']['200']['content']['application/json']
        self.assertEqual(media['example'], sample)
        prop = media['schema']['properties']['description']
        for field, value in [('default', sample), ('examples', [sample]), ('enum', [sample])]:
            self.assertEqual(prop[field], value)
        self.assertNotIn('$3', prop['description'])
        self.assertEqual(doc, before)

    def test_real_money_semantics_and_code_examples_are_unchanged(self):
        for filename, path in [
            ('kalshi-official', ('paths', '/fcm/positions/transfers', 'post', 'description')),
            ('polymarket-data', ('components', 'schemas', 'ComboPosition', 'properties', 'realized_payout_usdc', 'description')),
            ('dataforseo-official', ('components', 'schemas', 'MerchantAmazonProductsTaskPostRequestInfo', 'properties', 'search_param', 'description')),
            ('financial-official', ('components', 'schemas', 'AgentCheckoutLinkRequest', 'properties', 'amount_to_add', 'description')),
        ]:
            value = json.loads((ROOT / f'openapi/upstream/{filename}.json').read_text())
            for part in path:
                value = value[part]
            self.assertEqual(clean_text(value), value, filename)
        sample = '1 USD = 1,000,000 micros.\n```json\n{"description":"Billed $9 per call"}\n```'
        self.assertEqual(clean_text(sample), sample)

    def test_parameter_defaults_model_names_and_row_limits_survive(self):
        text = 'optional field; default value: falseNote: you will be charged extra $0.002 for using this parameter; if absent charges are returned.'
        out = clean_text(text)
        self.assertIn('default value: false', out)
        self.assertIn('if absent', out)
        out = clean_text('Billed per returned data row at $0.45 per row (up to 20 rows; header row excluded); 4xx/5xx are not charged.')
        self.assertIn('up to 20 rows; header row excluded', out)
        self.assertNotIn('excluded)', out)
        self.assertIn('`seedream` is supported', clean_text('`seedream` is billed at $0.036 per request.'))
        source = json.loads((ROOT / 'openapi/upstream/openai-images-generations.json').read_text())
        original = next(iter(source['paths'].values()))['post']['requestBody']['content']['application/json']['schema']['properties']['model']['description']
        result = clean_text(original)
        for model in ('seedream-5-0-260128', 'wan2.7-image', 'wan2.7-image-pro', 'gpt-image-2'):
            self.assertIn(model, result)

    def test_real_sources_are_idempotent_and_sources_stay_intact(self):
        for path in (ROOT / 'openapi/upstream').glob('*.json'):
            source = json.loads(path.read_text())
            original = copy.deepcopy(source)
            result = clean_document(source)
            self.assertEqual(clean_document(result), result, path.name)
            self.assertEqual(source, original, path.name)
        self.assertNotIn('flat', clean_text('Billed at a flat $0.012 per request.'))

    def test_real_search_filter_examples_and_batch_rules_survive_rate_cleanup(self):
        source = json.loads((ROOT / 'openapi/upstream/dataforseo-official.json').read_text())
        text = source['components']['schemas']['MerchantGoogleProductsTaskPostRequestInfo']['properties']['search_param']['description']
        self.assertEqual(clean_text(text), text)
        source = json.loads((ROOT / 'openapi/upstream/tikhub.json').read_text())
        schema = source['components']['schemas']['BatchGiftQuery']
        for text in (schema['properties']['gift_ids']['description'],
                     source['paths']['/tikhub/tiktok/web/fetch_gift_names_by_ids']['post']['requestBody']['content']['application/json']['schema']['description']):
            result = clean_text(text)
            self.assertNotIn('$0.025', result)
            self.assertIn('50', result)
            self.assertEqual(result.count('first 50'), text.count('first 50'))
            self.assertEqual(clean_text(result), result)

    def test_conditional_provider_usage_warning_survives_without_static_amount(self):
        text = 'Note: you will be charged extra $0.002 for using this parameter; if absent charges are returned.'
        result = clean_text(text)
        self.assertIn('provider usage may increase for using this parameter', result)
        self.assertIn('if absent charges are returned', result)
        self.assertNotIn('$0.002', result)
        self.assertEqual(clean_text(result), result)

    def test_suffix_dollar_rates_preserve_mixed_batch_and_usage_instructions(self):
        self.assertNotIn('0.02$', clean_text('- Price: 0.02$ / time'))
        batch = '- Batch Get Video Information, up to 50 videos at a time, this interface charges a fixed price of 0.001$ * 50 = 0.05$ each time.'
        result = clean_text(batch)
        self.assertIn('up to 50 videos at a time', result)
        self.assertNotIn('0.001$', result)
        variable = '- Charged by the number of live rooms queried, 0.025$ per live room, please try to query 50 live rooms to avoid wasting API call counts.'
        result = clean_text(variable)
        self.assertIn('Provider usage depends on the number of live rooms queried', result)
        self.assertIn('query 50 live rooms', result)
        self.assertNotIn('0.025$', result)

    def test_free_claim_reconciles_only_positive_fixed_customer_pricing(self):
        text = 'Resolve an industry from free text. Free, suitable as health check.'
        for pricing, replace in (
                ({'customer_pricing': 'fixed_success', 'cost_contract': 'explicit_zero', 'default_request_estimate_usd': .001}, True),
                ({'cost_contract': 'explicit_zero', 'default_request_estimate_usd': .001}, False),
                ({'customer_pricing': 'usage', 'default_request_estimate_usd': .001}, False),
                ({'customer_pricing': 'fixed_success', 'default_request_estimate_usd': 0}, False),
                ({'customer_pricing': 'fixed_success', 'default_request_estimate_usd': .001, 'reference_unavailable': True}, False)):
            with self.subTest(pricing=pricing):
                result = clean_document({'paths': {'/test': {'get': {
                    'operationId': 'test', 'description': text, 'x-aisa-pricing': pricing}}}})
                description = result['paths']['/test']['get']['description']
                self.assertIn('from free text', description)
                self.assertEqual('Free, suitable' not in description, replace)
                self.assertEqual(clean_document(result), result)


if __name__ == '__main__':
    unittest.main()
