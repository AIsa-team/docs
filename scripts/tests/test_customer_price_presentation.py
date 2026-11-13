"""Tariff families, monetary boundaries and full-generation regressions."""
from decimal import Decimal
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from customer_price_presentation import price_family, pricing_summary


# Runtime declarations from Social publication and Commerce resource reads.
SOCIAL_PRICING = {
    'kind': 'metered_event', 'meter': 'social.post.published',
    'description': (
        'Publication is metered under social.post.published:<platform>. '
        'Each platform target is charged separately, only once it is published: '
        'an X post costs $0.015, or $0.200 when its effective text contains a URL '
        '(media URLs do not select the text-URL price); a post on any other platform costs $0.01. '
        'One post may target X together with other platforms. '
        "A failed target is not charged, and a target whose own charge is refused (insufficient balance or the request's maximum price) fails alone while the other targets publish. "
        'Draft creation is free. '
        "Accepted or unknown responses remain pending; only verified native publication settles each target's charge once. "
        'Send X-AISA-Cost-Mode: quote to get the total before publishing.'),
}
RESOURCE_PRICING = {
    'kind': 'fixed_request', 'customer_micros_usd': 50000, 'cache_hit_share_bps': 10000,
    'description': (
        'Charged once per delivered read: an entity with at least one requested field, or one page of a result set. '
        'A read that delivers nothing is not charged. '
        'A read answered from stored values is charged the cache-hit share of the price. '
        'Variants are priced by the route parameters they fix.'),
}


class CustomerPricePresentationTests(unittest.TestCase):
    def test_customer_price_overrides_supplier_kind_and_is_not_multiplied_again(self):
        for cost in ('explicit_zero', 'fixed_success', 'response_units', 'response_usd',
                     'response_count', 'request_formula', 'plan_units', 'response_components'):
            p = dict(customer_pricing='fixed_success', cost_contract=cost,
                     default_request_estimate_usd=.012345, customer_multiplier=3,
                     unit_rate_usd=.000001, unit='provider_credit')
            for language in ('en', 'zh'):
                with self.subTest(cost=cost, language=language):
                    text = pricing_summary(p, language)
                    self.assertIn('$0.012345', text)
                    self.assertNotIn('$0.037035', text)
                    self.assertNotIn('provider_credit', text)
                    self.assertNotIn('预估', text)
                    self.assertNotIn('estimate', text)

    def test_dynamic_families_keep_estimates_and_never_guess_customer_units(self):
        cases = {'fixed_success': 'request_dependent', 'request_formula': 'request_dependent',
                 'plan_units': 'request_dependent', 'response_count': 'result_dependent',
                 'response_usd': 'usage', 'response_units': 'usage',
                 'response_components': 'components', 'response_sku': 'components'}
        for cost, family in cases.items():
            p = dict(customer_pricing='provider_cost_multiplier', cost_contract=cost,
                     default_request_estimate_usd=.3, customer_multiplier=2,
                     unit_rate_usd=.01, unit='firecrawl_credit')
            self.assertEqual(price_family(p), family)
            for language in ('en', 'zh'):
                text = pricing_summary(p, language)
                self.assertIn('$0.3', text)
                for forbidden in ('$0.6', '$0.01', 'firecrawl_credit', 'per successful request', '每次成功请求'):
                    self.assertNotIn(forbidden, text)
            self.assertIn('estimate', pricing_summary(p))
        self.assertNotIn('$0', pricing_summary({'cost_contract': 'plan_units', 'unit_rate_usd': 0}))

    def test_unknown_rules_do_not_claim_usage_billing_or_disable_the_operation(self):
        for declaration in ({'kind': 'future_tariff'}, {'cost_contract': 'future_cost'},
                            {'kind': 'future_tariff', 'cost_contract': 'response_units'},
                            {'customer_pricing': 'provider_cost_multiplier'}):
            for amount in (None, 0, .1):
                pricing = dict(declaration, default_request_estimate_usd=amount)
                self.assertEqual(price_family(pricing), 'unknown')
                for language in ('en', 'zh'):
                    text = pricing_summary(pricing, language)
                    self.assertIn('计费方式暂不可用' if language == 'zh' else 'Billing method unavailable', text)
                    for forbidden in ('actual usage', 'Usage-based', '实际用量', 'operation is unavailable', '此操作暂不可用'):
                        self.assertNotIn(forbidden, text)
                    if amount is not None:
                        self.assertIn('默认请求预估费用' if language == 'zh' else 'Default request estimate', text)
                        self.assertIn('$0 USD' if amount == 0 else '$0.1 USD', text)

    def test_resource_cache_rounding_variants_and_zero_share(self):
        p = {'kind': 'fixed_request', 'customer_micros_usd': 101, 'cache_hit_share_bps': 2500}
        text = pricing_summary(p)
        self.assertIn('$0.000101 USD per delivered read', text)
        self.assertIn('Stored result: $0.000026 USD', text)
        self.assertIn('delivers nothing is not charged', text)
        self.assertIn('Stored result: $0.000101 USD', pricing_summary(dict(p, cache_hit_share_bps=10000)))
        for share in (0, -1, True, 10001, '2500'):
            self.assertNotIn('Stored result:', pricing_summary(dict(p, cache_hit_share_bps=share)))
        variants = {'kind': 'fixed_request', 'variants': {
            'a': {'kind': 'fixed_request', 'customer_micros_usd': 5000, 'status': 'enabled'},
            'b': {'kind': 'fixed_request', 'customer_micros_usd': 12000},
            'c': {'kind': 'fixed_request', 'customer_micros_usd': 999999, 'status': 'disabled'},
            '<unsafe>{name}': {'kind': 'fixed_request', 'customer_micros_usd': 3000},
        }}
        text = pricing_summary(variants)
        self.assertIn('a: Published reference price: $0.005', text)
        self.assertIn('b: Published reference price: $0.012', text)
        self.assertIn('c: unavailable', text)
        self.assertNotIn('$0.999999', text)
        self.assertNotIn('<unsafe>', text)
        self.assertNotIn('{name}', text)

    def test_fixed_async_and_customer_unit_amounts_are_independent_of_request_estimate(self):
        fixed = {'kind': 'fixed_request', 'default_request_estimate_usd': .1,
                 'estimate_source': 'configured_fixed_price'}
        self.assertIn('$0.1 USD per completed job', pricing_summary(fixed))
        metered = {'kind': 'metered_result', 'customer_unit_price_usd': .005,
                   'estimate_source': 'unavailable', 'estimate_unavailable_reason': 'request_dependent_units'}
        self.assertIn('$0.005 USD per billable unit', pricing_summary(metered))
        self.assertNotIn('not currently available', pricing_summary(metered))
        self.assertNotIn('per completed job', pricing_summary(metered))

    def test_missing_invalid_and_zero_are_distinct(self):
        for value in (None, True, -1, float('nan'), float('inf'), '0.1'):
            for key in ('default_request_estimate_usd', 'customer_unit_price_usd', 'customer_micros_usd'):
                self.assertNotIn('$', pricing_summary({'kind': 'fixed_request', key: value}))
        for p in ({'kind': 'unpriced', 'default_request_estimate_usd': 0},
                  {'customer_pricing': 'fixed_success', 'default_request_estimate_usd': .3, 'reference_unavailable': True}):
            self.assertNotIn('$', pricing_summary(p))
        self.assertEqual(
            pricing_summary({'kind': 'unpriced'}, 'en'),
            'Historical archive: disabled, cannot be called, and no price is published.')
        self.assertEqual(
            pricing_summary({'kind': 'unpriced'}, 'zh'),
            '历史归档接口：已停用，不可调用，价格未发布。')
        self.assertIn('$0 USD per successful request', pricing_summary({'customer_pricing': 'fixed_success', 'default_request_estimate_usd': 0}))
        self.assertIn('No additional charge', pricing_summary({'kind': 'no_customer_charge'}))
        self.assertIn('$9007199254.740993', pricing_summary({'kind': 'fixed_request', 'customer_micros_usd': 9007199254740993}))
        self.assertIn('$0.000000001', pricing_summary({'customer_unit_price_usd': Decimal('0.000000001')}))

    def test_social_event_rates_are_sourced_and_preserve_customer_conditions(self):
        description = ('Publication is metered under social.post.published:<platform>. Each platform target is charged separately, '
                       'only once it is published: an X post costs $0.017, or $0.220 when its effective text contains a URL '
                       '(media URLs do not select the text-URL price); a post on any other platform costs $0.02. '
                       'A failed target is not charged. Draft creation is free.')
        p = {'kind': 'metered_event', 'meter': 'social.post.published', 'description': description}
        for language in ('en', 'zh'):
            text = pricing_summary(p, language)
            for amount in ('$0.017', '$0.220', '$0.02'):
                self.assertIn(amount, text)
            self.assertNotIn('social.post.published', text)
            self.assertNotIn('$0.015', text)
            self.assertNotIn('No additional charge', text)
        self.assertIn('A failed target is not charged. Draft creation is free.', pricing_summary(p))
        self.assertIn('发布失败的目标不收费。 创建草稿免费。', pricing_summary(p, 'zh'))

    def test_social_preserves_new_conditions_and_does_not_invent_waivers(self):
        extra = ' Additional condition: <plan> customers pay $0.003 per scheduled target.'
        pricing = dict(SOCIAL_PRICING, description=SOCIAL_PRICING['description'] + extra)
        for language in ('en', 'zh'):
            text = pricing_summary(pricing, language)
            self.assertIn('Additional condition: &#60;plan&#62; customers pay $0.003 per scheduled target.', text)
            self.assertNotIn('<plan>', text)
            self.assertNotIn('social.post.published', text)
        pricing['description'] = pricing['description'].replace('Draft creation is free.', '')
        self.assertNotIn('Draft creation is free', pricing_summary(pricing))
        self.assertNotIn('草稿', pricing_summary(pricing, 'zh'))

    def test_customer_conditions_survive_document_and_page_generation(self):
        from pricing_prose import clean_document
        from readable_contract_notes import readable_block
        cases = [
            (SOCIAL_PRICING,
             ('insufficient balance', 'maximum price', 'fails alone while the other targets publish', 'charge once'),
             ('余额不足', '请求最高限价', '仅该目标失败，其他目标继续发布', '每个目标仅结算一次')),
            (RESOURCE_PRICING,
             ('at least one requested field', 'one page of a result set', '$0.05'),
             ('至少一个请求字段', '一页结果集', '$0.05')),
            ({'kind': 'future_tariff', 'default_request_estimate_usd': .1},
             ('Billing method unavailable', 'Default request estimate: $0.1'),
             ('计费方式暂不可用', '默认请求预估费用：$0.1')),
            ({'kind': 'unpriced'},
             ('Historical archive: disabled, cannot be called, and no price is published.',),
             ('历史归档接口：已停用，不可调用，价格未发布。',)),
        ]
        for pricing, english, chinese in cases:
            with self.subTest(kind=pricing['kind']):
                source = {'paths': {'/example': {'post': {
                    'operationId': 'example', 'description': 'Example request.', 'x-aisa-pricing': pricing}}}}
                document = clean_document(source)
                operation = document['paths']['/example']['post']
                self.assertEqual(operation['x-aisa-pricing'], pricing)
                self.assertEqual(clean_document(document), document)
                self.assertEqual(operation['description'], 'Example request.')
                for language, expected in [('en', english), ('zh', chinese)]:
                    page = readable_block(operation, language, document=document, method='post',
                                          path='/example', spec_path='openapi/example.json')
                    for text in expected:
                        self.assertIn(text, page.replace(r'\$', '$'))
                    self.assertNotIn('x-aisa-pricing', page)
                if pricing['kind'] == 'future_tariff':
                    self.assertNotIn('actual usage', operation['description'])

    def test_cache_conditions_and_model_units_remain_customer_visible(self):
        p = {'kind': 'fixed_request', 'customer_micros_usd': 1000,
             'description': 'Failed or unknown outcomes are not charged. Repeated identical requests within 6 hours are served from cache at no charge.'}
        self.assertIn('within 6 hours are free', pricing_summary(p))
        self.assertIn('6 小时', pricing_summary(p, 'zh'))
        plain = pricing_summary(dict(p, description=''))
        self.assertNotIn('cache', plain)
        for description, expected in [('whatever n is', 'regardless of n'),
                                      ('per second, per request or by tokens', 'per second'), ('', 'selected model')]:
            self.assertIn(expected, pricing_summary({'kind': 'model_catalog', 'description': description}))

    def test_same_plan_action_price_preserves_failure_waiver_without_account_variation(self):
        pricing = {
            'kind': 'fixed_request', 'customer_micros_usd': 300,
            'description': (
                'This is the price on every plan; no plan multiplier applies. '
                'A run that did not succeed is never charged: refused before it is sent, '
                'failed in the app, or with an unknown outcome.'),
        }
        for language in ('en', 'zh'):
            text = pricing_summary(pricing, language)
            self.assertIn('$0.0003', text)
            self.assertIn('所有套餐价格相同' if language == 'zh' else 'same price applies on every plan', text)
            self.assertIn('失败或结果未知时不收费' if language == 'zh' else 'Failed or unknown outcomes are not charged', text)
            for forbidden in ('may differ', '可能不同', 'multiplier', '倍率'):
                self.assertNotIn(forbidden, text)

    def test_free_operations_preserve_separate_ad_spend_and_existing_job_settlement(self):
        cases = [
            ('Ad spend is billed by the ad platform to the connected ad account, never by AIsa.',
             'billed separately by the ad platform', '广告平台'),
            ("No new customer charge is authorized by this lifecycle operation; cancellation may complete an existing job's settlement.",
             'settle charges for the existing job', '任务已产生的费用'),
            ("Reading a task is free; the task's charge settles when it ends.",
             "task's charge is settled when it ends", '任务本身的费用'),
        ]
        for description, english, chinese in cases:
            pricing = {'kind': 'no_customer_charge', 'description': description}
            self.assertIn(english, pricing_summary(pricing))
            self.assertIn(chinese, pricing_summary(pricing, 'zh'))
        for description in ('', None):
            self.assertEqual(pricing_summary({'kind': 'no_customer_charge', 'description': description}),
                             'No additional charge for this operation.')

    def test_full_generator_replaces_stale_prices_and_remains_idempotent(self):
        from test_runtime_contracts import PullTests
        from pull_openapi import stage
        fixture = PullTests()
        fixture.setUp()
        try:
            # Use the real stage entrypoint: English, Chinese, descriptions and MDX.
            changes, _ = stage(fixture.root, fixture.root/'facts', 'unused')
            fixture.write(changes)
            page = fixture.root/'api-reference/similarweb/published_identity.mdx'
            before = page.read_text()
            page.write_text(before.replace('## Cost and request rules', '## OLD_HAND_EDIT'))
            changes, _ = stage(fixture.root, fixture.root/'facts', 'unused')
            self.assertNotIn('OLD_HAND_EDIT', changes[page])
            self.assertNotIn('customer_multiplier', changes[page])
            fixture.write(changes)
            self.assertEqual(stage(fixture.root, fixture.root/'facts', 'unused')[0], {})
        finally:
            fixture.tearDown()

    def test_canonical_page_projection_preserves_bytes_but_uses_new_price_renderer(self):
        from canonical_import import project_surfaces
        from test_runtime_contracts import PullTests
        from pull_openapi import stage
        fixture = PullTests()
        fixture.setUp()
        try:
            changes, _ = stage(fixture.root, fixture.root/'facts', 'unused')
            fixture.write(changes)
            native = (fixture.root/'openapi/similarweb.json').read_bytes()
            (fixture.root/'llms.txt').write_text('# Test discovery\n')
            for prefix in ('', 'zh/'):
                page = fixture.root/(prefix + 'api-reference/similarweb/published_identity.mdx')
                page.write_text(page.read_text().replace('## Cost and request rules', '## OLD_HAND_EDIT')
                                .replace('## 费用与请求规则', '## OLD_HAND_EDIT'))
            metadata = {'registry': {'providers': {'similarweb': {}}}, 'coverage': {}, 'pending': {}}
            projected = project_surfaces(fixture.root, {'similarweb': native}, native, metadata)
            self.assertEqual(projected['openapi/similarweb.json'], native)
            self.assertEqual(projected['openapi/openapi.json'], native)
            pages = [raw.decode() for path, raw in projected.items() if path.endswith('.mdx')]
            self.assertTrue(pages)
            for text in pages:
                self.assertNotIn('OLD_HAND_EDIT', text)
                self.assertNotIn('customer_multiplier', text)
                self.assertNotIn('Cost conversion', text)
        finally:
            fixture.tearDown()


if __name__ == '__main__':
    unittest.main()
