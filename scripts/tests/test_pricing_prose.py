import copy
import json
import re
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pricing_prose import (clean_text, clean_document, clean_page, pricing_summary, strip_price_summary,
                           add_price_summary, markdown_safe, SETTLEMENT, NO_CHARGE, LEGACY_PRICE_BEGIN,
                           LEGACY_PRICE_END, NOTICE)
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
        self.assertNotIn('<!--', public['description'])
        localized = localize_tree(document, {'entries': {}}, allow_untranslated=True)
        self.assertIn('每次成功请求 $0.08 USD', operation(localized)['description'])
        self.assertNotIn('<!--', operation(localized)['description'])
        self.assertEqual(operation(localized)['description'].count(SETTLEMENT['zh']), 1)
        self.assertIn('每次成功请求 $0.08 USD', readable_block(public, 'zh'))
        sales = project_sales_catalog(document, 'a' * 64)['document']
        self.assertEqual(operation(sales)['description'], public['description'])
        self.assertEqual(clean_document(document), document)
        operation(document)['x-aisa-pricing']['default_request_estimate_usd'] = .12
        updated = clean_document(document)
        description = operation(updated)['description']
        self.assertIn('$0.12 USD', description)
        self.assertNotIn('$0.08', description)
        self.assertEqual(description.count(SETTLEMENT['en']), 1)
        self.assertNotIn('<!--', description)
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

    def test_native_operation_kinds_publish_no_charge_fixed_and_event_prices(self):
        free = {'kind': 'no_customer_charge', 'description': 'Included with your connected social accounts: AIsa does not charge per call.'}
        self.assertEqual(pricing_summary(free), 'No charge.')
        self.assertEqual(pricing_summary(free, 'zh'), '不收费。')
        for micros, amount in ((1000, '$0.001'), (5000, '$0.005'), (15000, '$0.015'), (0, '$0')):
            fixed = {'kind': 'fixed_request', 'customer_micros_usd': micros, 'customer_pricing_ref': 'social.x.v1.pricing@1',
                     'description': 'Charged once on success at the bound customer pricing revision.'}
            self.assertEqual(pricing_summary(fixed), f'Published reference price: {amount} USD per successful request. '
                                                     'Account-specific pricing and final settlement may differ.')
            self.assertIn(f'每次成功请求 {amount} USD', pricing_summary(fixed, 'zh'))
        event = {'kind': 'metered_event', 'meter': 'social.post.published',
                 'description': 'Each platform target is charged separately, only once it is published: an X post costs $0.015; a post on any other platform costs $0.01.'}
        self.assertEqual(pricing_summary(event), event['description'] + ' Account-specific pricing and final settlement may differ.')
        unavailable = 'A request reference price is not currently available'
        # A resource read is charged per delivered read; a variant has its own price.
        for pricing in ({'kind': 'fixed_request', 'customer_micros_usd': 50000, 'cache_hit_share_bps': 10000},
                        {'kind': 'fixed_request', 'customer_micros_usd': 1000, 'variants': {'twitter': {'kind': 'fixed_request', 'customer_micros_usd': 15000}}},
                        {'kind': 'fixed_request', 'customer_micros_usd': True},
                        {'kind': 'fixed_request', 'customer_micros_usd': '1000'},
                        {'kind': 'fixed_request', 'customer_micros_usd': -1},
                        {'kind': 'metered_event', 'meter': 'social.post.published'},
                        {'kind': 'unpriced', 'description': 'No price is published for this operation yet.'}):
            with self.subTest(pricing=pricing):
                self.assertIn(unavailable, pricing_summary(pricing))
        # An explicit Runtime estimate keeps its existing label.
        self.assertIn('Default request estimate: $0.1 USD (not a fixed price)', pricing_summary(
            {'kind': 'fixed_request', 'default_request_estimate_usd': .1, 'estimate_source': 'configured_fixed_price'}))
        stale = LEGACY_PRICE_BEGIN + '\n' + unavailable + '; use a request quote where supported. Account-specific pricing and final settlement may differ.\n' + LEGACY_PRICE_END
        paid = {'kind': 'fixed_request', 'customer_micros_usd': 15000, 'customer_pricing_ref': 'social.x.v1.pricing@1'}
        for pricing, expected in ((free, 'No charge.'), (paid, 'Published reference price: $0.015 USD per successful request.')):
            with self.subTest(pricing=pricing):
                document = {'paths': {'/social': {'get': {'operationId': 'social', 'description': 'Lead.\n\n' + stale, 'x-aisa-pricing': pricing}}}}
                result = clean_document(document)
                description = result['paths']['/social']['get']['description']
                self.assertIn(expected, description)
                self.assertNotIn(unavailable, description)
                self.assertEqual(description, 'Lead.\n\n' + pricing_summary(pricing))
                self.assertNotIn('aisa-pricing:', description)
                self.assertEqual(result['paths']['/social']['get']['x-aisa-pricing'], pricing)
                self.assertEqual(clean_document(result), result)

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
                         'Returns a JSON error body and is still billed 1 credit.')
        self.assertEqual(clean_text('Gift ID list, recommend 50/call for best value ($0.025), auto-process first 50', add_notice=False),
                         'Gift ID list, recommend 50/call for best value, auto-process first 50')
        # Without a price claim the text is not touched; other charge rules stay.
        self.assertEqual(clean_text('If the connection fails, the request is billed once.'), 'If the connection fails, the request is billed once.')
        self.assertEqual(clean_text('Billed $0.02 per call. Failed calls are not charged. Each target is charged separately, only once it is published.', add_notice=False),
                         'Failed calls are not charged. Each target is charged separately, only once it is published.')

    def test_event_price_placeholders_are_inline_code_for_mdx(self):
        from readable_contract_notes import readable_block
        pricing = {'kind': 'metered_event', 'meter': 'social.post.published',
                   'description': 'Publication is metered under social.post.published:<platform>. An X post costs $0.015 (<platform> x).'}
        summary = pricing_summary(pricing)
        self.assertTrue(summary.startswith('Publication is metered under `social.post.published:<platform>`. '
                                           'An X post costs $0.015 (`<platform>` x).'))
        self.assertIsNone(re.search(r'<platform>(?!`)', summary))
        block = readable_block({'x-aisa-pricing': pricing})
        self.assertIn('`social.post.published:<platform>`', block)

    def test_generated_paragraph_has_no_markup_and_is_replaced_on_every_run(self):
        # Mintlify shows an operation description as the page subtitle when the
        # page has no frontmatter description; HTML comments appear there as text.
        variants = [
            {'cost_contract': 'fixed_success', 'default_request_estimate_usd': .001},
            {'cost_contract': 'explicit_zero', 'customer_pricing': 'fixed_success', 'default_request_estimate_usd': 0},
            {'cost_contract': 'response_count', 'default_request_estimate_usd': .014, 'unit_rate_usd': .014, 'unit': 'provider_credit'},
            {'cost_contract': 'request_formula', 'default_request_estimate_usd': 1.275},
            {'default_request_estimate_usd': .08},
            {'default_request_estimate_usd': .08, 'reference_unavailable': True},
            {'estimate_source': 'unavailable', 'unit_rate_usd': .5, 'unit': 'row'},
            {'kind': 'no_customer_charge', 'description': 'Included with your connected social accounts.'},
            {'kind': 'fixed_request', 'customer_micros_usd': 15000},
            {'kind': 'unpriced', 'description': 'No price is published for this operation yet.'},
            {'kind': 'metered_event', 'meter': 'social.post.published',
             'description': 'Publication is metered under social.post.published:<platform>.\n\nAn X post costs $0.015; any other platform costs $0.01.'},
        ]
        for language in ('en', 'zh'):
            for pricing in variants:
                with self.subTest(language=language, pricing=pricing):
                    summary = pricing_summary(pricing, language)
                    self.assertTrue(summary == NO_CHARGE[language] or summary.endswith(SETTLEMENT[language]))
                    self.assertNotIn('\n', summary)
                    prose = re.sub(r'`[^`]*`', '', summary)
                    self.assertNotIn('<', prose)
                    shown = markdown_safe(summary)
                    # Two unescaped currency signs outside inline code would render as inline math.
                    self.assertLessEqual(len(re.findall(r'(?<!\\)\$', re.sub(r'`[^`]*`', '', shown))), 1)
                    self.assertEqual(re.findall(r'`[^`]*`', shown), re.findall(r'`[^`]*`', summary))
                    for lead in ('', 'Lead.\n\n### Return:\n- Data'):
                        op = add_price_summary({'operationId': 'x', 'description': lead, 'x-aisa-pricing': pricing}, language)
                        self.assertEqual(op['description'], (lead + '\n\n' + shown).strip())
                        self.assertEqual(strip_price_summary(op['description']), lead)
                        self.assertEqual(add_price_summary(dict(op), language), op)

    def test_changed_runtime_pricing_replaces_the_previous_paragraph(self):
        # A metered event paragraph is Runtime's own text, so the previous one is
        # recognized by its ending even after Runtime rewords it.
        steps = [{'kind': 'metered_event', 'description': 'An X post costs $0.015.'},
                 {'kind': 'metered_event', 'description': 'Each target is charged once it is published: $0.02 for X.'},
                 {'kind': 'no_customer_charge'},
                 {'cost_contract': 'fixed_success', 'default_request_estimate_usd': .005}]
        for language in ('en', 'zh'):
            op = {'operationId': 'x', 'description': 'Lead.'}
            for pricing in steps:
                with self.subTest(language=language, pricing=pricing):
                    op['x-aisa-pricing'] = pricing
                    add_price_summary(op, language)
                    self.assertEqual(op['description'], 'Lead.\n\n' + markdown_safe(pricing_summary(pricing, language)))

    def test_only_a_final_generated_paragraph_is_removed(self):
        for text in ('Lead.\n\nPublished reference price: $0.08 USD per successful request.',
                     'Published reference price: $0.08 USD per successful request. Account-specific pricing and final settlement may differ.\n\nTrailing note.',
                     'Lead. No charge.',
                     'Lead.\n\nNo charge applies to retries.',
                     'Lead.\n\nNo charge.\n\nTrailing note.'):
            with self.subTest(text=text):
                self.assertEqual(strip_price_summary(text), text)

    def test_legacy_marked_blocks_are_rewritten_once_without_markers(self):
        from runtime_localize_openapi_zh import localize_tree
        def legacy(body):
            return LEGACY_PRICE_BEGIN + '\n' + body + '\n' + LEGACY_PRICE_END
        old = pricing_summary({'cost_contract': 'fixed_success', 'default_request_estimate_usd': .08})
        pricing = {'cost_contract': 'fixed_success', 'default_request_estimate_usd': .12}
        for lead in ('', 'Douyin (app/v3).\n\n### Purpose:\n- Get data'):
            with self.subTest(lead=lead):
                description = (lead + '\n\n' + legacy(old)).strip()
                document = {'paths': {'/p': {'get': {'operationId': 'p', 'description': description, 'x-aisa-pricing': pricing}}}}
                result = clean_document(document)
                text = result['paths']['/p']['get']['description']
                self.assertEqual(text, (lead + '\n\n' + pricing_summary(pricing)).strip())
                self.assertNotIn('aisa-pricing:', text)
                self.assertEqual(clean_document(result), result)
                localized = localize_tree(document, {'entries': {}}, allow_untranslated=True)
                zh = localized['paths']['/p']['get']['description']
                self.assertEqual(zh, (lead + '\n\n' + pricing_summary(pricing, 'zh')).strip())
                self.assertNotIn('aisa-pricing:', zh)
        zh_legacy = legacy(pricing_summary({'default_request_estimate_usd': .08}, 'zh'))
        self.assertEqual(strip_price_summary('导语。\n\n' + zh_legacy), '导语。')

if __name__ == '__main__':
    unittest.main()
