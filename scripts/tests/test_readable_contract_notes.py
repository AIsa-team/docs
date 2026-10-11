import copy
import html
import json
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from readable_contract_notes import readable_block, update_readable_block, strip_generated_block, formula_text
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

    def test_exact_large_numbers_and_unknown_formula(self):
        self.assertIn('9007199254740993', readable_block({'x-aisa-pricing': {'maximum_units': 9007199254740993}}))
        self.assertIsNone(formula_text({'input': 'q', 'unknown_operator': 2}))
        self.assertEqual(formula_text({'inputs':['a','b'], 'unit_scale': 3, 'input_multiplier': 2, 'fixed_units': 1}), '1 + (ceil((a × b) / 3)) × 2')

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
                self.assertIn('Reservation input (public mapping not declared)', block)
                self.assertNotIn('Public request parameter', block)

    def test_public_reservation_and_bilingual_projection(self):
        op = {'parameters':[{'name':'limit','in':'query'}], 'x-aisa-pricing':{'reserve_plan_units':{'input':'limit','input_multiplier':3}}, 'x-aisa-constraints':{'notes':['Source note']}}
        self.assertIn('Public request parameter', readable_block(op))
        zh = readable_block(op, 'zh', lambda _: '来源说明')
        self.assertIn('公开请求参数', zh)
        self.assertIn('来源说明', zh)
        self.assertNotIn('Source note', zh)

    def test_real_generic_drivers_show_dates_defaults_and_counting(self):
        spec = json.loads((ROOT/'openapi/similarweb.json').read_text())
        op = spec['paths']['/apis/v1/similarweb/website/traffic-engagement']['get']
        block = readable_block(op)
        for text in ['metrics × periods', 'including repeated entries', 'query.start', 'Estimator fallback periods (does not make required dates optional)', 'monthly']:
            self.assertIn(text, block)

    def test_root_server_has_no_universal_mirror_promise(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(consolidate, 'OPENAPI_DIR', directory):
            document = consolidate.build_unified_spec()
        description = document['servers'][1]['description']
        self.assertNotIn('same surface as', description)
        self.assertIn('explicitly supported operations only', description)
        self.assertIn('servers and x402 capability declaration', description)

    def test_scaled_reservation_does_not_invent_evaluation_order(self):
        plan = {'input':'limit', 'input_multiplier':100000, 'unit_scale':1000000, 'unit_rounding':'ceil'}
        op = {'x-aisa-pricing':{'units_per_count':100000, 'reserve_plan_units':plan}}
        rendered = readable_block(op)
        self.assertNotIn('Units per returned count', rendered)
        self.assertIn('Count multiplier before declared scaling', rendered)
        self.assertIn('Declared scaling divisor', rendered)
        self.assertIn('1000000', rendered)
        self.assertIn('Declared rounding', rendered)
        self.assertNotIn('ceil((', rendered)
        self.assertIn('supporting X-AISA-Cost-Mode: quote', rendered)
        self.assertEqual(formula_text(dict(plan, fixed_units=1)), '1 + (ceil((limit) / 1000000)) × 100000')

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

    def test_real_firecrawl_json_body_limit_is_public(self):
        spec = json.loads((ROOT/'openapi/firecrawl.json').read_text())
        op = next(op for item in spec['paths'].values() for op in item.values()
                  if isinstance(op, dict) and op.get('operationId') == 'post_firecrawl_search')
        rendered = readable_block(op)
        self.assertIn('Public request parameter', rendered)
        self.assertNotIn('public mapping not declared', rendered)
        unknown = {'requestBody': {'$ref':'#/components/requestBodies/Request'},
                   'x-aisa-pricing': {'reserve_plan_units': {'input':'limit','input_multiplier':2}}}
        self.assertIn('public mapping not declared', readable_block(unknown))

    def test_guides_distinguish_reference_quote_settlement(self):
        for prefix in ['', 'zh/']:
            guide = (ROOT/(prefix+'guides/pricing.mdx')).read_text()
            for field in ['billing_multiplier_ppm','1,000,000','X-AISA-Cost-Mode: settled','cost_estimate','customer_cost_micros_usd']:
                self.assertIn(field, guide)
