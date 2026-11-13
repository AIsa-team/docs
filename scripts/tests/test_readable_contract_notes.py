import copy
import html
import json
import re
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from readable_contract_notes import readable_block, update_readable_block, strip_generated_block
import runtime_consolidate_openapi as consolidate

ROOT = Path(__file__).resolve().parents[2]

class ReadableNotesTests(unittest.TestCase):

    def test_absent_pricing_is_explicit_without_guessing_price_or_availability(self):
        for status in (None, 'enabled', 'disabled'):
            for value in (None, {}):
                operation = {'operationId': 'reference'}
                if status is not None:
                    operation['x-aisa-status'] = status
                if value is not None:
                    operation['x-aisa-pricing'] = value
                original = copy.deepcopy(operation)
                for language in ('en', 'zh'):
                    text = readable_block(operation, language)
                    if status == 'disabled':
                        self.assertIn('历史归档接口' if language == 'zh' else 'Historical archive', text)
                    else:
                        self.assertIn('计费方式暂不可用' if language == 'zh' else 'Billing method unavailable', text)
                        self.assertNotIn('disabled', text)
                        self.assertNotIn('已停用', text)
                    self.assertNotIn('$', text)
                    self.assertNotIn('No additional charge', text)
                self.assertEqual(operation, original)

    def test_disabled_legacy_labels_are_not_a_published_tariff(self):
        legacy = {'cost_tier': 'low', 'model': 'per_request'}
        for language, archive, unknown in (
                ('en', 'Historical archive: disabled, cannot be called, and no price is published.', 'Billing method unavailable.'),
                ('zh', '历史归档接口：已停用，不可调用，价格未发布。', '计费方式暂不可用。')):
            operation = {'x-aisa-status': 'disabled', 'x-aisa-pricing': copy.deepcopy(legacy)}
            before = copy.deepcopy(operation)
            self.assertIn(archive, readable_block(operation, language))
            self.assertNotIn(unknown, readable_block(operation, language))
            self.assertEqual(operation, before)
            operation['x-aisa-status'] = 'enabled'
            self.assertIn(unknown, readable_block(operation, language))
            operation.update({'x-aisa-status': 'disabled', 'x-aisa-pricing': {
                'kind': 'fixed_request', 'customer_micros_usd': 5000}})
            self.assertIn('$0.005', readable_block(operation, language))
            self.assertNotIn(archive, readable_block(operation, language))

    def test_safety_idempotence_and_preserve_prose(self):
        op = {'x-aisa-pricing': {'default_request_estimate_usd': .075}, 'x-aisa-constraints': {'notes': ['<script>{danger}</script> `x`\n## forged']}}
        original = copy.deepcopy(op)
        prose = '---\ntitle: test\n---\n\nUser prose.\n'
        generated = update_readable_block(prose, op)
        self.assertEqual(update_readable_block(generated, op), generated)
        self.assertEqual(strip_generated_block(generated), prose)
        self.assertEqual(update_readable_block(generated, {}), prose)
        self.assertNotIn('<script>', generated)
        self.assertNotIn('{danger}', generated)
        self.assertNotIn('\n## forged', generated)
        self.assertEqual(op, original)
        tail = '\nUser prose after block.\n'
        changed = copy.deepcopy(op)
        changed['x-aisa-pricing']['default_request_estimate_usd'] = .15
        updated = update_readable_block(generated + tail, changed)
        self.assertEqual(strip_generated_block(updated), prose + tail)
        self.assertLess(updated.index('User prose after block.'), updated.index('aisa-contract-details:start'))
        self.assertIn('0.15', updated)
        self.assertEqual(update_readable_block(updated, changed), updated)

    def test_price_card_is_only_published_for_known_customer_amounts(self):
        prose = '---\ntitle: Test\n---\n\nEndpoint overview.\n\n## Example\n\nExample request.\n'
        known = {'operationId': 'known', 'x-aisa-pricing': {'kind': 'fixed_request', 'customer_micros_usd': 14760,
                                                            'estimate_source': 'configured_fixed_price'}}
        context = {'document': {'paths': {'/known': {'get': known}}}, 'method': 'get',
                   'path': '/known', 'spec_path': 'openapi/test.json'}
        rendered = update_readable_block(prose, known, **context)
        self.assertIn('aisa-price-card:start', rendered)
        self.assertIn('<Info>', rendered)
        self.assertIn('$0.01476 USD per completed job', rendered)
        self.assertLess(rendered.index('aisa-price-card:start'), rendered.index('Endpoint overview.'))
        self.assertLess(rendered.index('Endpoint overview.'), rendered.index('Cost and request rules'))
        self.assertLess(rendered.index('Cost and request rules'), rendered.index('Request contract'))

        unknown_op = {'operationId': 'unknown'}
        unknown_context = {'document': {'paths': {'/unknown': {'get': unknown_op}}}, 'method': 'get',
                           'path': '/unknown', 'spec_path': 'openapi/test.json'}
        unknown = update_readable_block(prose, unknown_op, **unknown_context)
        self.assertNotIn('aisa-price-card:', unknown)
        self.assertNotIn('<Info>', unknown)
        self.assertLess(unknown.index('Endpoint overview.'), unknown.index('Cost and request rules'))

        estimated_op = {'operationId': 'estimated',
                        'x-aisa-pricing': {'kind': 'future_tariff', 'default_request_estimate_usd': .1}}
        estimated = update_readable_block(prose, estimated_op, **unknown_context)
        self.assertIn('<Info>', estimated)
        self.assertIn('Default request estimate: $0.1 USD.', estimated)

    def test_multi_price_cards_use_literal_dollars_and_hide_disabled_tariffs(self):
        from readable_contract_notes import price_card_block
        from test_customer_price_presentation import SOCIAL_PRICING
        op = {'x-aisa-pricing': copy.deepcopy(SOCIAL_PRICING)}
        for language in ('en', 'zh'):
            card = price_card_block(op, language)
            for amount in (r'\$0.015', r'\$0.200', r'\$0.01'):
                self.assertIn(amount, card)
        op['x-aisa-status'] = 'disabled'
        self.assertEqual(price_card_block(op), '')

    def test_paired_currency_is_literal_mdx_without_changing_contract_prices(self):
        from pricing_prose import pricing_summary
        from public_surface_checks import request_blocks, compare_llms
        operation = {"operationId": "price", "x-aisa-pricing": {
            "kind": "metered_result", "default_request_estimate_usd": 0.3, "customer_unit_price_usd": 0.075}}
        document = {"paths": {"/price": {"get": operation}}}
        before = copy.deepcopy(document)
        for language in ("en", "zh"):
            context = dict(document=document, method="get", path="/price", spec_path="openapi/p.json")
            block = readable_block(operation, language, **context)
            self.assertIn(r"\$0.3", block)
            self.assertIn(r"\$0.075", block)
            canonical = pricing_summary(operation["x-aisa-pricing"], language)
            self.assertNotIn(r"\$", canonical)
            parsed = request_blocks(block)
            record = next(iter(parsed.values()))[0]
            self.assertEqual(record["price_summary"], canonical)
            self.assertNotIn("x-aisa-pricing", record["request"])
            # Mintlify exports either literal or escaped dollars to Markdown.
            self.assertEqual(compare_llms(parsed, request_blocks(block.replace(r"\$", "$"))), [])
            self.assertEqual(update_readable_block(block, operation, language, **context), block)
        self.assertEqual(document, before)
        for pricing in ({"default_request_estimate_usd": 0.3}, {"reference_unavailable": True}):
            for language in ("en", "zh"):
                canonical = pricing_summary(pricing, language)
                block = readable_block({"x-aisa-pricing": pricing}, language)
                self.assertIn(canonical, block)
                self.assertNotIn(r"\$", block)

    def test_disabled_operation_without_price_gets_archive_copy_without_mutating_contract(self):
        operation = {'operationId': 'retired', 'x-aisa-status': 'disabled'}
        before = copy.deepcopy(operation)
        block = readable_block(operation)
        self.assertIn('Historical archive: disabled, cannot be called, and no price is published.', block)
        self.assertEqual(operation, before)

    def test_request_url_template_is_literal_code_not_escaped_autolink(self):
        # A bare URL is autolinked by Mintlify, which keeps character references
        # such as &#95; in both the link text and the href.
        path = "/apis/v1/dataforseo/ai_optimization/{task_id}/locations_and_languages"
        operation = {"operationId": "op"}
        document = {"servers": [{"url": "https://api.aisa.one/"}], "paths": {path: {"get": operation}}}
        for language, label in (("en", "Request URL template"), ("zh", "请求 URL 模板")):
            block = readable_block(operation, language, document=document, method="get", path=path, spec_path="openapi/p.json")
            line = next(row for row in block.splitlines() if row.startswith("- **" + label))
            self.assertEqual(line, "- **" + label + ":** `https://api.aisa.one" + path + "`")
            self.assertEqual(update_readable_block(block, operation, language, document=document, method="get", path=path, spec_path="openapi/p.json"), block)
        from readable_contract_notes import code
        self.assertEqual(code("a`b"), "``a`b``")
        self.assertEqual(code("`a"), "`` `a ``")
        self.assertEqual(code("a\nb"), "`a b`")

    def test_internal_reservation_and_unknown_formula_are_not_public_copy(self):
        pricing = {'maximum_units': 9007199254740993, 'request_cost_drivers': {'formula': {'input': 'q', 'unknown_operator': 2}}}
        rendered = readable_block({'x-aisa-pricing': pricing})
        self.assertIn('Billing method unavailable.', rendered)
        self.assertNotIn('9007199254740993', rendered)
        self.assertNotIn('unknown_operator', rendered)

    def test_managed_notes_and_internal_reserve_not_public(self):
        spec = json.loads((ROOT/'openapi/similarweb.json').read_text())
        for route in ['website-traffic-trend', 'website-traffic-snapshot', 'website-top-geographies']:
            op = spec['paths']['/apis/v1/similarweb/'+route]['get']
            for language in ['en','zh']:
                block = readable_block(op, language)
                for note in op['x-aisa-constraints']['notes']:
                    self.assertIn(note, block)
                self.assertIn('0.', block)
            if route == 'website-top-geographies':
                block = readable_block(op)
                self.assertNotIn('Reservation input', block)
                self.assertNotIn('Public request parameter', block)

    def test_public_reservation_and_bilingual_projection(self):
        op = {'parameters':[{'name':'limit','in':'query'}], 'x-aisa-pricing':{'reserve_plan_units':{'input':'limit','input_multiplier':3}}, 'x-aisa-constraints':{'notes':['Source note']}}
        self.assertNotIn('Public request parameter', readable_block(op))
        zh = readable_block(op, 'zh', lambda _: '来源说明')
        self.assertNotIn('公开请求参数', zh)
        self.assertIn('来源说明', zh)
        self.assertNotIn('Source note', zh)

    def test_real_generic_drivers_do_not_expose_internal_arithmetic(self):
        spec = json.loads((ROOT/'openapi/similarweb.json').read_text())
        op = spec['paths']['/apis/v1/similarweb/website/traffic-engagement']['get']
        block = readable_block(op)
        for text in ['metrics × periods', 'Estimator fallback periods', 'unit_scale', 'customer_multiplier']:
            self.assertNotIn(text, block)
        for note in op.get('x-aisa-constraints', {}).get('notes', []):
            self.assertIn(note, html.unescape(block))

    def test_root_server_has_no_universal_mirror_promise(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(consolidate, 'OPENAPI_DIR', directory):
            document = consolidate.build_unified_spec()
        description = document['servers'][1]['description']
        self.assertNotIn('same surface as', description)
        self.assertIn('explicitly supported operations only', description)
        self.assertIn('servers and x402 capability declaration', description)

    def test_scaled_reservation_is_not_customer_arithmetic(self):
        plan = {'input':'limit', 'input_multiplier':100000, 'unit_scale':1000000, 'unit_rounding':'ceil'}
        op = {'x-aisa-pricing':{'cost_contract': 'plan_units', 'default_request_estimate_usd': .25,
                               'units_per_count':100000, 'reserve_plan_units':plan}}
        rendered = readable_block(op)
        self.assertIn('Default request estimate: $0.25 USD.', rendered)
        for text in ('Count multiplier', 'scaling divisor', '1000000', 'rounding', 'ceil('):
            self.assertNotIn(text, rendered)
        self.assertIn('use a request quote where supported', rendered)

    def test_same_facts_new_composer_regenerates_and_then_is_idempotent(self):
        from test_runtime_contracts import PullTests
        fixture = PullTests()
        fixture.setUp()
        try:
            from pull_openapi import stage
            with patch('compose_openapi.VERSION', '17'):
                old, _ = stage(fixture.root, fixture.root/'facts', 'unused')
            fixture.write(old)
            page = fixture.root/'api-reference/similarweb/published_identity.mdx'
            page.write_text(strip_generated_block(page.read_text()))
            changes, summary = stage(fixture.root, fixture.root/'facts', 'unused')
            self.assertTrue(summary['similarweb']['changed'])
            self.assertIn('Cost and request rules', changes[page])
            fixture.write(changes)
            self.assertEqual(stage(fixture.root, fixture.root/'facts', 'unused')[0], {})
        finally:
            fixture.tearDown()

    def test_source_notes_translate_without_changing_machine_metadata(self):
        import runtime_localize_openapi_zh as localization
        catalog = json.loads((ROOT/'translations/openapi-zh.json').read_text())
        note = 'The result limit is fixed at 10 and cannot be overridden.'
        op = {'x-aisa-constraints':{'notes':[note]}}
        self.assertEqual(localization.localize_tree(op, catalog), op)
        self.assertIn(note, [text for _, text in localization.iter_spec_strings(op)])
        result = readable_block(op, 'zh', lambda value: localization.translation(catalog, value))
        self.assertIn('结果数量限制固定为 10，不能覆盖。', result)
        self.assertNotIn(note, result)

    def test_pending_response_does_not_hide_known_request_constraint(self):
        from test_runtime_contracts import facts, operation
        from compose_openapi import compose
        runtime = facts(method='get')
        op = operation(runtime)
        op['parameters'] = [{'name':'age_bucket', 'in':'query', 'required':True,
                             'schema':{'type':'string','enum':['18','25','35','45','55','65']}}]
        op['x-aisa-response-passthrough'] = True
        op['x-aisa-constraints'] = {'notes':['Select one age bucket; age_bucket must be provided exactly once.']}
        result, pending = compose(runtime)
        published = operation(result)
        self.assertIn('x-aisa-response-pending', published)
        self.assertEqual(published['parameters'], op['parameters'])
        self.assertIn('age_bucket must be provided exactly once', html.unescape(readable_block(published)))
        self.assertNotIn('content', published['responses']['200'])

    def test_real_firecrawl_keeps_request_limits_without_pricing_plans(self):
        spec = json.loads((ROOT/'openapi/firecrawl.json').read_text())
        for operation_id in ['post_firecrawl_search', 'post_firecrawl_map']:
            path, method, op = next((path, method, op) for path, item in spec['paths'].items() for method, op in item.items()
                      if isinstance(op, dict) and op.get('operationId') == operation_id)
            rendered = readable_block(op, document=spec, method=method, path=path, spec_path='openapi/firecrawl.json')
            request = json.loads(re.search(r'```json\n(.*?)\n```', rendered, re.S)[1])
            self.assertIn('requestBody', request)
            self.assertNotIn('x-aisa-pricing', request)
            self.assertNotIn('public mapping not declared', rendered)

    def test_guides_distinguish_reference_quote_settlement(self):
        for prefix in ['', 'zh/']:
            guide = (ROOT/(prefix+'guides/pricing.mdx')).read_text()
            for field in ['billing_multiplier_ppm','1,000,000','X-AISA-Customer-Cost-Micros-USD','cost_estimate','customer_cost_micros_usd']:
                self.assertIn(field, guide)
