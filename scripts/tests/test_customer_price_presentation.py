"""Tariff families, monetary boundaries and full-generation regressions."""
from decimal import Decimal
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from customer_price_presentation import price_family, pricing_summary


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

    def test_resource_cache_rounding_variants_and_zero_share(self):
        p = {'kind': 'fixed_request', 'customer_micros_usd': 101, 'cache_hit_share_bps': 2500}
        text = pricing_summary(p)
        self.assertIn('$0.000101 USD per delivered read', text)
        self.assertIn('Stored result: $0.000026 USD', text)
        self.assertIn('delivers nothing is not charged', text)
        for share in (0, 10000):
            self.assertIn('Stored result: $0.000101 USD', pricing_summary(dict(p, cache_hit_share_bps=share)))
        for share in (-1, True, 10001, '2500'):
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
        self.assertIn('Drafts and failed targets are not charged', pricing_summary(p))
        self.assertIn('草稿和发布失败的目标不收费', pricing_summary(p, 'zh'))

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
