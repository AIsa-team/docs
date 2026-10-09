"""Published examples must retain actual gateway presenter compatibility shapes.

The fixture is captured from pinned Runtime code, not derived from these pages.
This test does not substitute for route, ledger, or production acceptance.
"""
import copy
import hashlib
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'scripts/tests/fixtures/runtime-errors-6d'
PATTERN = re.compile(
    r'\{/\* runtime-error: ([a-z_]+/[a-z_]+) \*/\}\s*'
    r'HTTP `(\d+)`([^\n]*)\s*```json\n(.*?)\n```', re.S)
CLASSES = {'authentication', 'parameters', 'budget', 'idempotency', 'upstream',
           'configuration_dependency'}


def validate_examples(text, cases):
    expected = {f'{c["class"]}/{c["variant"]}': c for c in cases}
    found = {}
    for name, status, headers, raw in PATTERN.findall(text):
        if name in found:
            raise ValueError('duplicate error example')
        found[name] = (int(status), headers, json.loads(raw))
    if set(found) != set(expected):
        raise ValueError('error example membership changed')
    for name, case in expected.items():
        status, headers, body = found[name]
        if status != case['status'] or body != case['body']:
            raise ValueError('runtime error example changed: ' + name)
        expected_header = case.get('request_id_header')
        if expected_header:
            if headers != '; `X-Request-ID: ' + expected_header + '`':
                raise ValueError('request ID header mismatch')
        elif headers:
            raise ValueError('invented response header')


class ErrorDeclarationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads((FIXTURE / 'presenters.json').read_text())
        cls.cases = cls.fixture['cases']
        cls.pages = [(ROOT / p).read_text() for p in
                     ('api-reference/errors.mdx', 'zh/api-reference/errors.mdx')]

    def test_both_languages_match_actual_six_class_presenters(self):
        self.assertEqual({c['class'] for c in self.cases}, CLASSES)
        self.assertEqual(len(self.cases), 9)
        for page in self.pages:
            validate_examples(page, self.cases)

    def test_capture_is_reproducible_and_runtime_revision_is_pinned(self):
        self.assertEqual(self.fixture['runtime_revision'],
                         '6d9648811441d08232096808fae7ac96e6816f64')
        self.assertEqual(hashlib.sha256((FIXTURE / 'capture_test.go').read_bytes()).hexdigest(),
                         self.fixture['capture_sha256'])
        self.assertEqual(len(self.fixture['files_sha256']), 5)
        for value in self.fixture['files_sha256'].values():
            self.assertRegex(value, r'^[a-f0-9]{64}$')

    def test_auth_string_and_parameter_no_code_are_not_upgraded_to_uniform_object(self):
        for index in (0, 1):
            changed = copy.deepcopy(self.cases)
            changed[index]['body'] = {'error': {'code': 'invalid_request', 'type': 'request_error'}}
            with self.assertRaisesRegex(ValueError, 'runtime error example changed'):
                validate_examples(self.pages[0], changed)

    def test_similarweb_compatibility_and_native_transport_status_are_preserved(self):
        for index, key, value in ((4, 'status', 400), (5, 'status', 503)):
            changed = copy.deepcopy(self.cases)
            changed[index][key] = value
            with self.assertRaisesRegex(ValueError, 'runtime error example changed'):
                validate_examples(self.pages[0], changed)
        changed = copy.deepcopy(self.cases)
        changed[4]['body']['error']['code'] = 'request_already_completed'
        with self.assertRaisesRegex(ValueError, 'runtime error example changed'):
            validate_examples(self.pages[0], changed)

    def test_dependency_request_id_is_preserved_without_inventing_ids_elsewhere(self):
        changed = self.pages[0].replace('; `X-Request-ID: example-request-id`', '')
        with self.assertRaisesRegex(ValueError, 'request ID header mismatch'):
            validate_examples(changed, self.cases)
        changed = self.pages[0].replace('HTTP `402`', 'HTTP `402`; `X-Request-ID: invented`')
        with self.assertRaisesRegex(ValueError, 'invented response header'):
            validate_examples(changed, self.cases)
        changed = copy.deepcopy(self.cases)
        changed[2]['body']['error']['request_id'] = 'invented'
        with self.assertRaisesRegex(ValueError, 'runtime error example changed'):
            validate_examples(self.pages[0], changed)

    def test_missing_added_duplicate_examples_are_rejected(self):
        page = self.pages[0]
        for changed in (page.replace('runtime-error: budget/estimate_cap', 'runtime-error: budget/new'),
                        page + '\n' + PATTERN.search(page).group(0)):
            with self.assertRaises(ValueError):
                validate_examples(changed, self.cases)

    def test_no_universal_envelope_or_unconditional_retry_promise(self):
        self.assertNotIn('always JSON with an `error` object', self.pages[0])
        self.assertNotIn('始终是包含 `error` 对象', self.pages[1])
        self.assertNotIn('All `GET` requests and most chat', self.pages[0])
        self.assertNotIn('所有 `GET` 请求和大多数聊天', self.pages[1])
        self.assertIn('including non-JSON errors', self.pages[0])
        self.assertIn('包括非 JSON 错误', self.pages[1])


if __name__ == '__main__':
    unittest.main()
