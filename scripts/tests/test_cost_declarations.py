"""Execute the published parser against independent int64 wire cases."""
import re
import shlex
import os
import subprocess
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
PATTERN = r'\{/\* settled-cost-parser \*/\}\s*```python\n(.*?)\n```'
HEADER = 'X-AISA-Customer-Cost-Micros-USD'
# EN merged Usage Logs into the Console page; zh keeps its own page until the mirror.
USAGE_LOGS = {'': 'guides/dashboard/overview#usage-and-logs', 'zh/': 'guides/dashboard/usage-logs'}


class CostDeclarationTests(unittest.TestCase):
    def test_pricing_guides_use_the_actual_customer_cost_protocol(self):
        for prefix in ('', 'zh/'):
            with self.subTest(language=prefix):
                page = (ROOT / (prefix + 'guides/pricing.mdx')).read_text()
                self.assertIn(HEADER, page)
                self.assertIn('customer_cost_micros_usd', page)
                self.assertNotIn('X-AISA-Cost-Micros-USD', page)
                self.assertNotRegex(page, r'X-AISA-Cost-Mode:\s*settled')
                self.assertIn('/' + prefix + USAGE_LOGS[prefix], page)

    def test_bilingual_quote_and_execution_keep_the_same_request(self):
        for prefix in ('', 'zh/'):
            page = (ROOT / (prefix + 'guides/pricing.mdx')).read_text()
            blocks = re.findall(r'```bash\n(.*?)\n```', page, re.S)
            commands = [shlex.split(block.replace('\\\n', ' '))
                        for block in blocks if block.startswith('curl ')]
            self.assertEqual(len(commands), 2)
            quote, execute = commands
            for command in commands:
                self.assertIn('${AISA_REQUEST_URL:?Set AISA_REQUEST_URL}', command)
                self.assertIn('Authorization: Bearer ${AISA_API_KEY:?Set AISA_API_KEY}', command)
            self.assertIn('X-AISA-Cost-Mode: quote', quote)
            self.assertFalse(any('X-AISA-Cost-Mode' in part for part in execute))
            self.assertIn('X-AISA-Max-Price-USD: ${AISA_MAX_PRICE_USD:?Set AISA_MAX_PRICE_USD}', execute)

    def test_usage_examples_are_key_scoped_and_use_unix_seconds(self):
        for prefix in ('', 'zh/'):
            page = (ROOT / (prefix + USAGE_LOGS[prefix].split('#')[0] + '.mdx')).read_text()
            blocks = re.findall(r'```bash\n(.*?)\n```', page, re.S)
            example = next(block for block in blocks if '/v1/usage' in block)
            self.assertIn('int(time.time()) - 86400', example)
            for argument in ('start_time=$start_time', 'bucket_width=1d', 'scope=key'):
                self.assertIn(argument, example)
            for term in ('31', 'OAuth', 'totals.charged_micros_usd',
                         'totals.usage_value_micros_usd', '[start_time, end_time)'):
                self.assertIn(term, page)

    def test_execution_example_never_calls_curl_without_a_reviewed_limit(self):
        for prefix in ('', 'zh/'):
            page = (ROOT / (prefix + 'guides/pricing.mdx')).read_text()
            execute = next(block for block in re.findall(r'```bash\n(.*?)\n```', page, re.S)
                           if 'X-AISA-Max-Price-USD:' in block)
            # A shell function intercepts curl: no credentials or network are used.
            script = 'curl() { printf "CALLED\\n"; };\n' + execute
            env = {k: v for k, v in os.environ.items() if not k.startswith('AISA_')}
            env.update(AISA_API_KEY='test-only', AISA_REQUEST_URL='https://example.invalid')
            for value in (None, ''):
                candidate = dict(env)
                if value is not None:
                    candidate['AISA_MAX_PRICE_USD'] = value
                result = subprocess.run(['bash', '-c', script], env=candidate,
                                        text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('CALLED', result.stdout)
            env['AISA_MAX_PRICE_USD'] = '0.075'
            result = subprocess.run(['bash', '-c', script], env=env,
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, 'CALLED\n')

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
