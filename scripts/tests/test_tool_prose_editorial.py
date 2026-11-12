import unittest
import csv
import json
import re
from pathlib import Path

from tool_prose_editorial import editorial_text, english_prose, NOTICE, WIRE_LITERAL_TEXT


class EditorialProseTests(unittest.TestCase):
    def test_credit_and_failure_claims_keep_functional_semantics(self):
        text = ('A "company not found" result returns HTTP 404 with a valid JSON body '
                'and is still billed 1 credit; only 429, 5xx, and network errors are not billed.')
        result = editorial_text(text, notice=True)
        self.assertIn('HTTP 404 with a valid JSON body', result)
        self.assertNotIn('billed 1 credit', result)
        self.assertNotIn('not billed', result)
        self.assertIn(NOTICE, result)
        self.assertEqual(editorial_text(result, notice=True), result)

    def test_feature_flags_and_constraints_survive_rate_removal(self):
        text = ('Request mobile enrichment. WARNING: a found mobile costs 10 credits '
                'and also includes email enrichment; allowed values: `false`.')
        result = editorial_text(text, notice=True)
        self.assertIn('email enrichment', result)
        self.assertIn('allowed values: `false`', result)
        self.assertNotIn('10 credits', result)

    def test_billing_words_are_not_a_keyword_deletion_policy(self):
        for text in ('Cast and crew credits; licence attribution credits.',
                     'Tax credits, company charges and airline refund quotes.',
                     'Product price is $25. The plan is Free.',
                     'Returns `credits_used`, `billing` and `refund` fields.',
                     'Ordinary description.\n'):
            self.assertEqual(editorial_text(text, notice=True), text)

    def test_native_billing_claim_is_not_an_upstream_claim(self):
        text = 'Paid: see x-aisa-pricing; charged only when the call succeeds.'
        self.assertEqual(editorial_text(text, native=True, notice=True), text)

    def test_english_prose_preserves_required_wire_literals(self):
        self.assertEqual(english_prose('Facebook公开数据: 商品搜索'), 'Facebook public data: Product search')
        literal = 'Use the literal prefix `内容类目#` and value `内容类目#美妆`.'
        self.assertEqual(english_prose(literal), literal)

    def test_catalog_explanations_are_english_with_explicit_wire_literal_exceptions(self):
        root = Path(__file__).resolve().parents[2]
        non_english = re.compile(r'[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]+')
        with (root / 'docs/tool-prose-coverage-20261112.csv').open() as stream:
            for row in csv.DictReader(stream):
                self.assertFalse(non_english.search(row['summary_after']), row['operation_id'])
                fragments = set(non_english.findall(row['description_after']))
                self.assertFalse(fragments - WIRE_LITERAL_TEXT, (row['operation_id'], fragments - WIRE_LITERAL_TEXT))

    def test_original_wire_examples_are_unchanged_by_editorial_corrections(self):
        from tool_prose_history import before_tool_prose_amendment
        root = Path(__file__).resolve().parents[2]
        rows = json.loads((root / 'docs/tool-prose-changes-20261112.json').read_text())
        nested = [row for row in rows if 'pointer' in row]
        self.assertTrue(nested)
        for row in nested:
            self.assertIn(row['pointer'][-1], ('summary', 'description'))
            self.assertFalse(set(map(str, row['pointer'])) & {'enum', 'default', 'example', 'examples'})
        for name in {row['source_file'] for row in nested}:
            before_tool_prose_amendment(root, name)

    def test_all_static_source_explanations_use_english_not_bilingual_region_notes(self):
        root = Path(__file__).resolve().parents[2]
        non_english = re.compile(r'[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]+')
        def visit(value):
            if isinstance(value, list):
                for child in value:
                    yield from visit(child)
            elif isinstance(value, dict):
                for key, child in value.items():
                    if key.startswith('x-') or key in ('example', 'examples', 'enum', 'default'):
                        continue
                    if key in ('summary', 'description') and isinstance(child, str):
                        yield child
                    elif isinstance(child, (dict, list)):
                        yield from visit(child)
        for path in (root / 'openapi/upstream').glob('*.json'):
            for text in visit(json.loads(path.read_text())):
                self.assertFalse(set(non_english.findall(text)) - WIRE_LITERAL_TEXT, (path, text))


if __name__ == '__main__':
    unittest.main()
