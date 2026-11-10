import copy
import html
import json
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
        self.assertTrue(updated.endswith(tail))
        self.assertLess(updated.index('aisa-contract-details:start'), updated.index('User prose after block.'))
        self.assertIn('0.15', updated)
        self.assertEqual(update_readable_block(updated, changed), updated)

    def test_paired_currency_is_literal_mdx_without_changing_contract_prices(self):
        from pricing_prose import pricing_summary
        from public_surface_checks import request_blocks, compare_llms
        operation = {"operationId": "price", "x-aisa-pricing": {
            "default_request_estimate_usd": 0.3, "customer_unit_price_usd": 0.075,
            "kind": "metered_result"}}
        document = {"paths": {"/price": {"get": operation}}}
        before = copy.deepcopy(document)
        for language in ("en", "zh"):
            context = dict(document=document, method="get", path="/price", spec_path="openapi/p.json")
            block = readable_block(operation, language, **context)
            self.assertIn(r"\$0.3 USD", block)
            self.assertIn(r"\$0.075 USD", block)
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

    def test_internal_estimator_details_are_absent_but_request_notes_remain(self):
        spec = json.loads((ROOT/'openapi/similarweb.json').read_text())
        for route in ['website-traffic-trend', 'website-traffic-snapshot', 'website-top-geographies']:
            op = spec['paths']['/apis/v1/similarweb/'+route]['get']
            for language in ['en','zh']:
                block = readable_block(op, language)
                for note in op['x-aisa-constraints']['notes']:
                    self.assertIn(note, block)
                self.assertIn('0.', block)
                for internal in ('Reservation input', 'metrics × periods', 'Count multiplier', 'unit_scale'):
                    self.assertNotIn(internal, block)
        op = {'x-aisa-pricing': {'maximum_units': 9007199254740993, 'reserve_plan_units': {'input': 'limit'}},
              'x-aisa-constraints': {'notes': ['Source note']}}
        zh = readable_block(op, 'zh', lambda _: '来源说明')
        self.assertIn('来源说明', zh)
        self.assertNotIn('9007199254740993', zh)
        self.assertNotIn('limit', zh)

    def test_root_server_has_no_universal_mirror_promise(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(consolidate, 'OPENAPI_DIR', directory):
            document = consolidate.build_unified_spec()
        description = document['servers'][1]['description']
        self.assertNotIn('same surface as', description)
        self.assertIn('explicitly supported operations only', description)
        self.assertIn('servers and x402 capability declaration', description)

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

    def test_real_firecrawl_keeps_request_schema_without_reservation_math(self):
        spec = json.loads((ROOT/'openapi/firecrawl.json').read_text())
        for path, item in spec['paths'].items():
            for method, op in item.items():
                if not isinstance(op, dict) or op.get('operationId') not in ['post_firecrawl_search', 'post_firecrawl_map']:
                    continue
                rendered = readable_block(op, document=spec, method=method, path=path, spec_path='openapi/firecrawl.json')
                self.assertIn('"limit"', rendered)
                self.assertNotIn('reserve_plan_units', rendered)
                self.assertNotIn('input_multiplier', rendered)

    def test_guides_distinguish_reference_quote_settlement(self):
        for prefix in ['', 'zh/']:
            guide = (ROOT/(prefix+'guides/pricing.mdx')).read_text()
            for field in ['billing_multiplier_ppm','1,000,000','X-AISA-Customer-Cost-Micros-USD','cost_estimate','customer_cost_micros_usd']:
                self.assertIn(field, guide)
