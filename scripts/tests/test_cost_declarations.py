"""Execute the published parser against independent int64 wire cases."""
import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
PATTERN = r'\{/\* settled-cost-parser \*/\}\s*```python\n(.*?)\n```'
HEADER = 'X-AISA-Customer-Cost-Micros-USD'


class CostDeclarationTests(unittest.TestCase):
    def setUp(self):
        self.pages = [(ROOT / p).read_text() for p in ('api-reference.mdx', 'zh/api-reference.mdx')]
        code = [re.findall(PATTERN, p, re.S) for p in self.pages]
        self.assertEqual([len(c) for c in code], [1, 1])
        self.assertEqual(code[0], code[1])
        ns = {}
        exec(compile(code[0][0], '<published-cost-example>', 'exec'), ns)
        self.parse = ns['settled_customer_cost']

    def test_missing_zero_and_charge_are_distinct(self):
        self.assertIsNone(self.parse({}))
        self.assertEqual(self.parse({HEADER: '0'}),
                         {'customer_cost_micros_usd': 0, 'cost_usd_exact': '0.000000'})
        self.assertEqual(self.parse({HEADER: '314'}),
                         {'customer_cost_micros_usd': 314, 'cost_usd_exact': '0.000314'})

    def test_full_int64_precision_without_float_conversion(self):
        for raw, expected in [('9007199254740993', '9007199254.740993'),
                              ('9223372036854775807', '9223372036854.775807')]:
            with self.subTest(raw=raw):
                self.assertEqual(self.parse({HEADER: raw}),
                    {'customer_cost_micros_usd': int(raw), 'cost_usd_exact': expected})

    def test_bad_wire_values_cannot_be_reported_as_zero(self):
        for raw in ['-1', '+1', '1.2', 'NaN', '١', '', '9223372036854775808', True, False]:
            with self.subTest(raw=raw):
                self.assertIsNone(self.parse({HEADER: raw}))

    def test_quote_cap_or_provider_cost_is_not_a_customer_debit(self):
        self.assertIsNone(self.parse({'X-AISA-Max-Price-USD': '1.00',
            'X-AISA-Provider-Cost-Micros-USD': '123', 'estimated_cost_micros_usd': 1000000}))

    def test_bilingual_unknown_estimate_and_browser_boundaries_are_explicit(self):
        required = [
            ['missing does not mean free', 'not proof of a', 'Provider-cost headers are not part',
             'cost remains absent', 'numeric display', 'including zero',
             'depend on the deployed version', 'Do not assume every MCP deployment'],
            ['缺失不等于免费', '不是已经扣费的证明', '不在通用浏览器 CORS 暴露列表内',
             '未知费用保持缺失', '极大数值可能被舍入', '包括零', '取决于实际部署版本',
             '不要假定每个 MCP 部署']]
        for page, terms in zip(self.pages, required):
            for term in terms:
                self.assertIn(term, page)
            self.assertIn('Access-Control-Expose-Headers', page)
            self.assertNotIn('every response contains', page)
            self.assertNotIn('每次响应都包含', page)


if __name__ == '__main__':
    unittest.main()
