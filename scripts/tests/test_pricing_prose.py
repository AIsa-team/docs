import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pricing_prose import (clean_text, clean_document, clean_page, pricing_summary, remove_price_summary,
                           strip_price_summary, PRICE_BEGIN, PRICE_END, NOTICE, NOTICE_ZH)
from compose_openapi import compose
from test_runtime_contracts import facts, operation, mirror

ROOT = Path(__file__).resolve().parents[2]


class PricingProseTests(unittest.TestCase):
    def test_price_parenthetical_and_upstream_billing_sentences_leave_no_stub(self):
        lead = 'Unlike search this works for any tweet\nvisible to the connected account.'
        text = (lead + '\n\nBilled as an X posts read ($0.005). Repeat lookups of the same tweet within the same UTC day\n'
                'are charged once.\n\nNext paragraph.')
        result = clean_text(text, add_notice=False)
        self.assertEqual(result, lead + '\n\nNext paragraph.')
        self.assertEqual(clean_text(result, add_notice=False), result)
        self.assertEqual(clean_text('Lead. Charged per lookup ($0.005).\nNext.', add_notice=False), 'Lead.\nNext.')
        self.assertEqual(clean_text('Lead ($0.01/call). Repeat calls are billed once. Then this.', add_notice=False), 'Lead. Then this.')
        # A parenthetical inside a sentence with other content keeps the sentence.
        self.assertEqual(clean_text('Returns a JSON error body and is still billed 1 credit ($0.00528).', add_notice=False),
                         'Returns a JSON error body and is still billed.')
        self.assertEqual(clean_text('Gift ID list, recommend 50/call for best value ($0.025), auto-process first 50', add_notice=False),
                         'Gift ID list, recommend 50/call for best value, auto-process first 50')
        # Without a price claim the text is not touched; other charge rules stay.
        self.assertEqual(clean_text('If the connection fails, the request is billed once.'), 'If the connection fails, the request is billed once.')
        self.assertEqual(clean_text('Billed $0.02 per call. Failed calls are not charged. Each target is charged separately, only once it is published.', add_notice=False),
                         'Failed calls are not charged. Each target is charged separately, only once it is published.')
        self.assertEqual(clean_text(NOTICE, add_notice=False), '')
        self.assertEqual(clean_text(NOTICE_ZH, 'zh', add_notice=False), '')


    def test_reviewed_response_field_tables_preserve_business_prices(self):
        from runtime_localize_openapi_zh import localize_tree, key_for
        paths = {
            '/apis/v1/littlecaesars-com/restaurants/get-delivery-fee',
            '/apis/v1/notion-com/developer-documentation/get-pricing',
            '/apis/v1/play-google-com/media/app',
        }
        # Freeze reviewed descriptions independently of mutable publication inputs.
        # Source: dcb6397a9, openapi/upstream/alexandria-contract-part-*.json.
        descriptions = json.loads((ROOT / 'scripts/tests/fixtures/reviewed-business-price-descriptions.json').read_text())
        self.assertEqual(descriptions.keys(), paths)
        for path, text in descriptions.items():
            with self.subTest(path=path):
                response = {'description': text, 'content': {'application/json': {'schema': {
                    'type': 'object', 'x-aisa-schema-completeness': 'documented-fields-only'}}}}
                document = {'paths': {path: {'post': {'operationId': 'test',
                    'description': 'Billed $0.02 per call.', 'responses': {'200': response}}}}}
                cleaned = clean_document(document)
                self.assertEqual(cleaned['paths'][path]['post']['responses']['200'], response)
                self.assertNotIn('$0.02', cleaned['paths'][path]['post']['description'])
                self.assertEqual(clean_document(cleaned), cleaned)
                translated = '响应字段。\n\n' + text
                catalog = {'entries': {key_for(text): {'source': text, 'translation': translated}}}
                localized = localize_tree(cleaned, catalog, allow_untranslated=True)
                self.assertEqual(localized['paths'][path]['post']['responses']['200']['description'], translated)


    def test_price_tracks_runtime_in_the_page_cost_section_not_the_description(self):
        # Mintlify shows the operation description under the page title, so a
        # price there leads the page. Pages show it in their cost section.
        from readable_contract_notes import readable_block
        from runtime_localize_openapi_zh import localize_tree
        from sales_catalog_projection import project_sales_catalog
        runtime = facts()
        operation(runtime)['description'] = 'Domain Rating. Billed $0.02 per successful call.'
        operation(runtime)['x-aisa-pricing'] = {'cost_contract': 'fixed_success', 'customer_pricing': 'fixed_success', 'default_request_estimate_usd': .08}
        document, _ = compose(runtime)
        public = operation(document)
        self.assertNotIn('$0.02', public['description'])
        self.assertNotIn('$0.08', public['description'])
        self.assertIn('Published reference price: $0.08 USD per successful request.', readable_block(public))
        localized = localize_tree(document, {'entries': {}}, allow_untranslated=True)
        self.assertNotIn('$0.08', operation(localized)['description'])
        self.assertIn('公开参考价格：每次成功请求 $0.08 USD。', readable_block(public, 'zh'))
        sales = project_sales_catalog(document, 'a' * 64)['document']
        self.assertEqual(operation(sales)['description'], public['description'])
        self.assertEqual(operation(sales)['x-aisa-pricing'], public['x-aisa-pricing'])
        self.assertEqual(clean_document(document), document)
        operation(document)['x-aisa-pricing']['default_request_estimate_usd'] = .12
        updated = clean_document(document)
        self.assertNotIn('$', operation(updated)['description'])
        self.assertIn('$0.12 USD per successful request', readable_block(operation(updated)))
        operation(updated).pop('x-aisa-pricing')
        self.assertNotIn('$0.12', readable_block(operation(updated)))

    def test_cleanup_preserves_openapi_top_level_order(self):
        source = {
            'openapi': '3.1.0',
            'info': {'title': 'Example'},
            'paths': {'/records': {'get': {'operationId': 'records', 'description': 'Billed $0.02 per call.'}}},
            'security': [{'bearerAuth': []}],
            'servers': [{'url': 'https://api.aisa.one'}],
        }
        self.assertEqual(list(clean_document(source)), list(source))

    def test_localized_price_only_description_keeps_protocol_shape(self):
        from runtime_localize_openapi_zh import localize_tree, strip_translatable
        source = {
            'paths': {'/twitter': {'get': {
                'operationId': 'twitter_get',
                'description': 'A request reference price is not currently available; use a request quote where supported. Account-specific pricing and final settlement may differ.',
                'x-aisa-pricing': {'reference_unavailable': True},
            }}}
        }
        localized = localize_tree(source, {'entries': {}}, allow_untranslated=True)
        self.assertIn('description', localized['paths']['/twitter']['get'])
        self.assertEqual(localized['paths']['/twitter']['get']['description'], '')
        self.assertEqual(strip_translatable(source), strip_translatable(localized))

    def test_legacy_description_summaries_and_markers_are_removed(self):
        # Mintlify renders an HTML comment in an OpenAPI description as text.
        pricing = {'cost_contract': 'fixed_success', 'customer_pricing': 'fixed_success', 'default_request_estimate_usd': .08}
        legacy = ('Agoda Hotel Rates\n\n' + PRICE_BEGIN + '\nPublished reference price: $0.05 USD per successful request.'
                  ' Account-specific pricing and final settlement may differ.\n' + PRICE_END)
        operation = remove_price_summary({'description': legacy, 'x-aisa-pricing': pricing})
        self.assertEqual(operation['description'], 'Agoda Hotel Rates')
        self.assertEqual(remove_price_summary(copy.deepcopy(operation)), operation)
        usage = ('Get a video\n\n' r'Usage-based billing; Default request estimate: \$0.154 USD (not a fixed price). '
                 r'Declared unit rate: \$0.014 USD per provider_credit. Account-specific pricing and final settlement may differ.')
        self.assertEqual(remove_price_summary({'description': usage, 'x-aisa-pricing': {}})['description'], 'Get a video')
        zh = ('酒店价格\n\n按用量计费；默认请求预估费用：\\$0.02 USD（不是固定价格）。 声明的单位费率：每 provider_credit '
              '\\$0.02 USD。 最终费用以账户适用价格及实际结算为准。')
        self.assertEqual(remove_price_summary({'description': zh})['description'], '酒店价格')
        # A description that was only a price is dropped, not left empty.
        only = remove_price_summary({'description': 'A request reference price is not currently available; use a request '
                                     'quote where supported. Account-specific pricing and final settlement may differ.'})
        self.assertNotIn('description', only)
        # Only a trailing generated paragraph is a summary; hand-written prose stays.
        prose = 'Default request estimate: see the quote endpoint.\n\nReturns rates.'
        self.assertEqual(strip_price_summary(prose), prose)
        # The pricing notice that replaced a stale rate goes once a price is declared.
        noticed = remove_price_summary({'description': 'Search. ' + NOTICE, 'x-aisa-pricing': pricing})
        self.assertEqual(noticed['description'], 'Search.')

    def test_legacy_notice_migration_preserves_code_examples(self):
        from pricing_prose import LEGACY_NOTICES
        for notice in LEGACY_NOTICES:
            example = '```json\n' + json.dumps({'description': notice}) + '\n```'
            self.assertEqual(clean_text(example), example)
            text = notice + '\n\n' + example
            cleaned = clean_text(text)
            self.assertIn(example, cleaned)
            self.assertNotIn('x-aisa-pricing', cleaned.split('```')[0])

    def test_frontmatter_legacy_summaries_leave_business_text_and_are_idempotent(self):
        for summary in ('No charge.', 'No additional charge for this operation.',
                        'Price not yet published; this operation is unavailable.',
                        PRICE_BEGIN + ' No charge. ' + PRICE_END,
                        'Usage-based pricing. Default request estimate: $0.1 USD. '
                        'Your account price may differ; use a request quote where supported.'):
            description = 'Get ads.\n\n' + summary
            page = '---\ntitle: Ads\ndescription: ' + json.dumps(description) + '\n---\n\nBusiness body.\n'
            cleaned = clean_page(page)
            import yaml
            self.assertEqual(yaml.safe_load(cleaned.split('---')[1])['description'], 'Get ads.')
            self.assertEqual(clean_page(cleaned), cleaned)
            self.assertTrue(cleaned.endswith('Business body.\n'))

    def test_fixed_zero_usage_units_and_missing_prices_have_distinct_labels(self):
        fixed = pricing_summary({'customer_pricing': 'fixed_success', 'default_request_estimate_usd': .08, 'customer_multiplier': 2})
        self.assertIn('Published reference price: $0.08 USD per successful request.', fixed)
        self.assertNotIn('$0.16', fixed)
        free = pricing_summary({'kind': 'no_customer_charge'})
        self.assertEqual(free, 'No additional charge for this operation.')
        usage = {'cost_contract': 'response_count', 'default_request_estimate_usd': 1.275, 'unit_rate_usd': .075, 'unit': 'similarweb_credit'}
        self.assertIn('Charged for the actual billable results.', pricing_summary(usage))
        self.assertIn('Default request estimate: $1.275 USD.', pricing_summary(usage))
        self.assertIn('按实际计费结果数量收费。', pricing_summary(usage, 'zh'))
        for unit in ('provider_credit', 'similarweb_credit', 'new_unit'):
            for language in ('en', 'zh'):
                summary = pricing_summary({**usage, 'unit': unit}, language)
                self.assertNotIn(unit, summary)
                self.assertNotIn('$0.075', summary)
        self.assertIn('Usage-based pricing.', pricing_summary({'cost_contract': 'response_usd', 'default_request_estimate_usd': .02}))
        missing = pricing_summary({'default_request_estimate_usd': .08, 'reference_unavailable': True}, 'zh')
        self.assertIn('计费方式暂不可用。', missing)
        self.assertNotIn('$', missing)
        for value in (None, True, -1, float('inf'), float('nan'), '0.08'):
            self.assertNotIn('$', pricing_summary({'default_request_estimate_usd': value}))

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
