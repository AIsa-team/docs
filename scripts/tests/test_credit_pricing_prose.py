"""Supplier credit prices must not compete with the customer tariff."""
import copy
import json
from pathlib import Path
import unittest

from pricing_prose import clean_document, clean_page, clean_text
from runtime_localize_openapi_zh import key_for, localize_tree


class CreditPricingProseTests(unittest.TestCase):
    def test_reviewed_catalog_credit_claims_and_transcription_conditions(self):
        fixture = Path(__file__).parent / 'fixtures/supplier-credit-descriptions.json'
        cases = json.loads(fixture.read_text())['cases']
        self.assertEqual(len(cases), 29)
        for row in cases:
            with self.subTest(page=row['page'], text=row['before'][:60]):
                result = clean_text(row['before'], add_notice=False)
                self.assertTrue(result.strip())
                self.assertNotRegex(result.lower(), r'credits?|ceil\(|price dial|cost dial|this is the price')
                self.assertEqual(clean_text(result, add_notice=False), result)
                if row['before'].startswith('Paid opt-in'):
                    for rule in ("literal query value 'true'", 'Defaults to false', 'Over 120 seconds',
                                 'no fixed duration cap', 'does not force AI', 'get_transcript=true',
                                 'use_ai_as_fallback=true', 'remain synchronous', 'at least 30 seconds',
                                 'not guaranteed', 'Provider reference (supplier schema)'):
                        self.assertIn(rule, result)
                if row['before'].startswith('If we have a response in the cache'):
                    for rule in ('return the cached response', '"cached": true', '"cached_at"',
                                 'Otherwise, scrape a live result', 'https://docs.scrapecreators.com/caching'):
                        self.assertIn(rule, result)

    def test_real_credit_claims_keep_request_rules(self):
        cases = [
            ('1-100. THIS IS THE PRICE — 1 credit per company returned', ['1-100']),
            ('Expandable response fields. Supported values: `workforce` (adds the `workforce` field; costs 5 credits per company).',
             ['Expandable response fields', '`workforce`', 'adds the `workforce` field']),
            ('If we have a response in the cache that is this many days old or newer, return the cached response (0 credits, with "cached": true and a "cached_at" timestamp). Otherwise, scrape a live result (1 credit).',
             ['return the cached response', '"cached": true', '"cached_at"', 'scrape a live result']),
            ('Request mobile enrichment. WARNING: a found mobile costs 10 credits and also includes email enrichment.',
             ['Request mobile enrichment', 'also includes email enrichment']),
            ('Return only records with a verified mobile. Setting true enables enrich_mobile and may cost 10 credits per found mobile.',
             ['Return only records with a verified mobile', 'Setting true enables enrich_mobile']),
            ('Request 1-2 companies per call, costing 50 credits per returned company. PDL supports 1-100 upstream, but Exchange authorization is capped at 100 credits, so callers must use size 1 or 2.',
             ['Request 1-2 companies per call', 'callers must use size 1 or 2']),
            ('field groups to return; technographics adds 2 credits when data is returned',
             ['field groups to return', 'technographics']),
            ('true returns the enriched profile instead of just the profile URL — and DOUBLES the price to 2 credits',
             ['true returns the enriched profile instead of just the profile URL']),
            ('COST DIAL — rows to return; default 100 at 10 credits each = 1,000 credits',
             ['rows to return', 'default 100']),
            ('Maximum similar-company records on this page (1-50). Each returned record costs 1 credit; default 5.',
             ['Maximum similar-company records on this page (1-50)', 'default 5']),
            ('Start with 10 (the default): 1 and 10 both cost 1 credit. Non-empty pages cost ceil(limit/10) credits even when partially filled. Tested values: 1, 10, 20, 50; 30 is rejected.',
             ['Start with 10 (the default)', 'Tested values: 1, 10, 20, 50', '30 is rejected']),
            ('Set to true to include replies for every returned comment. This always costs 15 credits because each comment requires a separate Instagram replies request. You will still be charged 15 credits if no replies are returned. This is much slower and may time out at 29 seconds.',
             ['Set to true to include replies', 'if no replies are returned', 'may time out at 29 seconds']),
            ('返回 1-100 家公司；每家公司消耗 1 credit。空结果不收费。', ['返回 1-100 家公司', '空结果不收费']),
            ('每次查询扣除 2 积分。最多返回 50 条记录。', ['最多返回 50 条记录']),
        ]
        for text, retained in cases:
            for language in ('en', 'zh'):
                with self.subTest(text=text, language=language):
                    result = clean_text(text, language, add_notice=False)
                    self.assertNotRegex(result.lower(), r'credits?|积分|ceil\(|price dial|cost dial|this is the price|doubles the price')
                    for value in retained:
                        self.assertIn(value, result)
                    self.assertEqual(clean_text(result, language, add_notice=False), result)

    def test_billing_outcomes_survive_without_supplier_units(self):
        text = ('**Billing: per call (1 credit per lookup).** The "not registered" **HTTP 404** result '
                'returns a valid JSON body and is still billed 1 credit ($0.00528); only 429, 5xx, '
                'and network errors are not billed. A 400 validation error is a client-side rejection.')
        result = clean_text(text, add_notice=False)
        for value in ('HTTP 404', 'valid JSON body', 'still billed', 'only 429, 5xx, and network errors are not billed',
                      '400 validation error is a client-side rejection'):
            self.assertIn(value, result)
        self.assertNotRegex(result, r'credit|\$0\.00528')

    def test_business_credits_and_examples_are_not_api_rates(self):
        for text in ('Account balance: 100 credits.', 'The course grants 3 credits.',
                     'A tax credit of 500 credits is recorded in the ledger.',
                     'Return the credit score and credit limit.',
                     '```json\n{"description":"Costs 5 credits per company."}\n```'):
            self.assertEqual(clean_text(text), text)
        response = {'description': 'Carbon credits cost 3 credits per unit.', 'content': {
            'application/json': {'schema': {'type': 'object', 'x-aisa-schema-completeness': 'documented-fields-only'}}}}
        op = {'operationId': 'lookup', 'description': 'Lookup. Costs 1 credit per request.',
              'x-aisa-pricing': {'cost_contract': 'response_count', 'unit': 'provider_credit',
                                 'unit_rate_usd': .000001, 'default_request_estimate_usd': .0098},
              'parameters': [{'in': 'query', 'name': 'size', 'schema': {'type': 'integer', 'minimum': 1, 'maximum': 100},
                              'description': '1-100. THIS IS THE PRICE — 1 credit per company returned'}],
              'responses': {'200': response}, 'example': {'description': 'Costs 5 credits per company.'}}
        document = {'paths': {'/lookup': {'get': op}}}
        original = copy.deepcopy(document)
        cleaned = clean_document(document)
        actual = cleaned['paths']['/lookup']['get']
        self.assertEqual(document, original)
        self.assertEqual(actual['x-aisa-pricing'], op['x-aisa-pricing'])
        self.assertEqual(actual['responses'], op['responses'])
        self.assertEqual(actual['example'], op['example'])
        self.assertEqual(actual['parameters'][0]['schema'], op['parameters'][0]['schema'])
        self.assertNotIn('credit', actual['parameters'][0]['description'])
        source = actual['parameters'][0]['description']
        catalog = {'entries': {key_for(source): {'source': source,
                    'translation': '返回 1-100 家公司；每家公司消耗 1 credit。'}}}
        localized = localize_tree(cleaned, catalog, allow_untranslated=True)
        self.assertNotIn('credit', localized['paths']['/lookup']['get']['parameters'][0]['description'])
        self.assertEqual(clean_document(cleaned), cleaned)

    def test_page_billing_prose_and_price_table_are_cleaned_but_example_is_unchanged(self):
        example = '```json\n{"credits": 10}\n```'
        page = ('---\ntitle: Lookup\n---\n\nBilled 1 credit per lookup.\n\n'
                '| Operation | Price |\n| --- | --- |\n| Lookup | 1 credit per call |\n\n' + example + '\n')
        for language in ('en', 'zh'):
            result = clean_page(page, language)
            self.assertIn(example, result)
            self.assertNotIn('1 credit', result)
            self.assertIn('Lookup', result)
            self.assertEqual(clean_page(result, language), result)
