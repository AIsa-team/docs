import copy
import html
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from public_surface_checks import compare_llms
from rendered_page_checks import check_rendered_pages, select_pages, visible_contract


class RenderedPageChecks(unittest.TestCase):
    def setUp(self):
        self.request = {'operationId': 'get_example', 'method': 'GET', 'path': '/example',
                        'parameters': [{'name': 'id', 'in': 'query', 'required': True}],
                        'x-aisa-status': 'disabled',
                        'x-aisa-pricing': {'reference_price': 0.08},
                        'components': {'schemas': {'Input': {'properties': {
                            'description': {'const': 9007199254740993},
                            'example': {'const': '``` <script> & literal'}}}}}}
        self.identity = ('get_example', 'GET', '/example')
        self.expected = {self.identity: [{'request': self.request, 'price_summary': 'Reference: $0.08 USD.'}]}

    def page(self, request=None, *, zh=False, notice=True, price='Reference: $0.08 USD.'):
        request = self.request if request is None else request
        heading = '请求规范' if zh else 'Request contract'
        cost = '费用与请求规则' if zh else 'Cost and request rules'
        warning = '此接口已停用，无法调用' if zh else 'This endpoint is disabled and cannot be called'
        # Actual Mintlify shape: an anchor adds a zero-width character to the
        # heading, Shiki spans wrap JSON, and paragraphs use span[data-as=p].
        return ('<h2><a>\u200b</a><span>' + heading + '</span></h2>' +
                ('<strong>' + warning + '</strong>' if notice else '') +
                '<pre><code><span>' + html.escape(json.dumps(request)) + '</span></code></pre>' +
                '<h2><span>' + cost + '</span></h2><span data-as="p"><span>' +
                price + '</span></span><span data-as="p">Later explanatory paragraph.</span>')

    def test_visible_bilingual_json_and_first_price_paragraph(self):
        for zh in (False, True):
            with self.subTest(zh=zh):
                _, actual = visible_contract(self.page(zh=zh).encode())
                self.assertEqual(compare_llms(self.expected, actual), [])

    def test_correct_hydration_cannot_conceal_stale_or_missing_body(self):
        changed = {**self.request, 'x-aisa-status': 'enabled'}
        hidden = ''.join('<' + tag + '>' + self.page() + '</' + tag + '>'
                         for tag in ('script', 'style', 'template', 'noscript'))
        for body in (self.page(changed), ''):
            with self.subTest(body_present=bool(body)):
                _, actual = visible_contract((hidden + body).encode())
                self.assertTrue(compare_llms(self.expected, actual))

    def test_hidden_markup_cannot_substitute_for_visible_declarations(self):
        for attribute in ('hidden', 'hidden="false"', 'style="display: none"',
                          'style="color:red; visibility: hidden !important;"'):
            with self.subTest(attribute=attribute):
                raw = ('<div ' + attribute + '><section>' + self.page() +
                       '</section></div><p>Unrelated visible body.</p>').encode()
                result = check_rendered_pages({'api-reference/example.mdx': self.expected},
                                              read_bytes=lambda *_: raw)
                self.assertEqual(result['status'], 'failed')
                self.assertTrue(any('request_missing' in error for error in result['mismatches']))
                self.assertTrue(any('disabled_notice_missing' in error for error in result['mismatches']))
                # A hidden sibling must not suppress subsequent visible text.
                _, actual = visible_contract(raw + self.page().encode())
                self.assertEqual(compare_llms(self.expected, actual), [])

    def test_method_price_parameter_and_schema_drift_are_not_ignored(self):
        mutations = [lambda r: r.update(method='POST'),
                     lambda r: r.update(path='/wrong'),
                     lambda r: r['parameters'][0].update(required=False),
                     lambda r: r['x-aisa-pricing'].update(reference_price=0.02),
                     lambda r: r['components']['schemas']['Input']['properties']['description'].update(const=9007199254740992)]
        for mutation in mutations:
            changed = copy.deepcopy(self.request)
            mutation(changed)
            self.assertTrue(compare_llms(self.expected, visible_contract(self.page(changed).encode())[1]))
        self.assertTrue(compare_llms(self.expected, visible_contract(self.page(price='$0.02').encode())[1]))

    def test_a_correct_visible_duplicate_cannot_hide_a_stale_one(self):
        changed = {**self.request, 'x-aisa-status': 'enabled'}
        self.assertTrue(compare_llms(self.expected,
            visible_contract((self.page() + self.page(changed)).encode())[1]))

    def test_disabled_notice_must_be_visible_and_localized(self):
        pages = {'zh/api-reference/example.mdx': self.expected}
        raw = ('<script>此接口已停用，无法调用</script>' + self.page(zh=True, notice=False)).encode()
        result = check_rendered_pages(pages, read_bytes=lambda *_: raw)
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(any('disabled_notice_missing' in error for error in result['mismatches']))

    def test_sampling_covers_both_locale_tails_and_all_disabled_pages(self):
        enabled = {self.identity: [{'request': {**self.request, 'x-aisa-status': 'enabled'}, 'price_summary': None}]}
        pages = {prefix + 'api-reference/' + str(i).zfill(4) + '.mdx': enabled
                 for prefix in ('', 'zh/') for i in range(1999)}
        pages['zh/api-reference/1997.mdx'] = self.expected
        selected = select_pages(pages)
        self.assertLess(len(selected), len(pages))
        self.assertIn('zh/api-reference/1998.mdx', selected)
        self.assertIn('api-reference/0000.mdx', selected)
        self.assertIn('zh/api-reference/1997.mdx', selected)
        self.assertEqual(select_pages(pages, full=True), sorted(pages))

    def test_missing_page_never_passes_or_claims_complete_inventory(self):
        def unavailable(*_):
            raise TimeoutError()
        result = check_rendered_pages({'api-reference/example.mdx': self.expected},
                                      read_bytes=unavailable, full=True)
        self.assertEqual(result['status'], 'not_assessed')
        self.assertFalse(result['full_inventory_checked'])
        self.assertEqual(result['coverage']['en'], {'inventory': 1, 'selected': 1, 'observed': 0})


if __name__ == '__main__':
    unittest.main()
