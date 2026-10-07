import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from import_upstream import import_source


class SourceYamlScalarTests(unittest.TestCase):
    def import_yaml(self, body):
        raw = ('openapi: 3.1.0\ninfo: {title: Source}\npaths: {}\n' + body).encode()
        with patch('import_upstream.urlopen', return_value=io.BytesIO(raw)):
            return import_source('source', 'https://source.invalid/openapi.yaml')

    def test_real_polymarket_token_example_and_boolean_words_keep_wire_types(self):
        # Current official CLOB source uses this exact unquoted string example.
        body = '''components:
  schemas:
    ClobToken:
      properties:
        o: {type: string, example: Yes}
words: [Yes, YES, yes, No, NO, no, On, ON, on, Off, OFF, off, y, Y, n, N, '=']
flags: [true, True, TRUE, false, False, FALSE]
'''
        document = self.import_yaml(body)
        self.assertEqual(document['components']['schemas']['ClobToken']['properties']['o']['example'], 'Yes')
        self.assertEqual(document['words'], ['Yes', 'YES', 'yes', 'No', 'NO', 'no', 'On', 'ON', 'on',
                                            'Off', 'OFF', 'off', 'y', 'Y', 'n', 'N', '='])
        self.assertEqual(document['flags'], [True, True, True, False, False, False])
        self.assertTrue(all(type(value) is bool for value in document['flags']))

    def test_explicit_boolean_tags_do_not_allow_yaml11_coercion(self):
        for token in ('!!bool Yes', '!!bool on', '!!bool no'):
            with self.subTest(token=token), self.assertRaisesRegex(ValueError, 'unsupported_yaml_scalar'):
                self.import_yaml('value: ' + token + '\n')

    def test_yaml12_words_do_not_mutate_global_safe_loader(self):
        self.import_yaml('value: Yes\n')
        self.assertIs(yaml.safe_load('value: Yes')['value'], True)

    def test_exact_json_types_and_quoted_scalar_bytes_survive(self):
        document = self.import_yaml("values: [0, -2, 0.125, false, null, '0123', '1e400', '2026-10-03']\n")
        self.assertEqual(document['values'], [0, -2, 0.125, False, None, '0123', '1e400', '2026-10-03'])
        self.assertEqual([type(value) for value in document['values']],
                         [int, int, float, bool, type(None), str, str, str])

    def test_ambiguous_numbers_and_dates_still_fail_closed(self):
        for token in ('0123', '0xFF', '1_000', '1:20', '.nan', '.inf', '1e400',
                      '1e-400', '1.0000000000000001', '2026-10-03'):
            with self.subTest(token=token), self.assertRaisesRegex(ValueError, 'unsupported_'):
                self.import_yaml('value: ' + token + '\n')

    def test_explicit_duplicate_json_member_names_rejected_at_any_depth(self):
        for body in ('value: 1\nvalue: 2\n', 'value: {x: 1, x: 2}\n',
                     "value: {200: a, '200': b}\n", "value: {true: a, 'true': b}\n"):
            with self.subTest(body=body), self.assertRaisesRegex(ValueError, 'duplicate_yaml_mapping_key'):
                self.import_yaml(body)

    def test_response_status_codes_become_exact_json_member_names(self):
        document = self.import_yaml('responses: {200: {description: Success}, 204: {description: Empty}}\n')
        self.assertEqual(set(document['responses']), {'200', '204'})

    def test_legitimate_merge_overrides_and_nested_merge_references_preserved(self):
        document = self.import_yaml('''base: &base {x: 1, y: yes}
derived: &derived {<<: *base, x: 2}
value: {<<: *derived, y: no}
''')
        self.assertEqual(document['base'], {'x': 1, 'y': 'yes'})
        self.assertEqual(document['derived'], {'x': 2, 'y': 'yes'})
        self.assertEqual(document['value'], {'x': 2, 'y': 'no'})

    def test_merge_does_not_hide_duplicate_explicit_members(self):
        for body in ('base: &base {x: 1}\nvalue: {<<: *base, x: 2, x: 3}\n',
                     'value: {<<: {x: 1, x: 2}}\n',
                     'base: &base {x: 1}\nvalue: {<<: {<<: *base, x: 2, x: 3}}\n'):
            with self.subTest(body=body), self.assertRaisesRegex(ValueError, 'duplicate_yaml_mapping_key'):
                self.import_yaml(body)

    def test_inline_nested_merge_with_reused_anchor_is_valid(self):
        document = self.import_yaml('''base: &base {x: 1, y: yes}
value: {<<: &derived {<<: *base, x: 2}}
other: {<<: *derived, y: no}
''')
        self.assertEqual(document['value'], {'x': 2, 'y': 'yes'})
        self.assertEqual(document['other'], {'x': 2, 'y': 'no'})

    def test_complex_keys_and_unsafe_object_tags_are_rejected(self):
        for body in ('value: {[a, b]: 1}\n', 'value: !!python/object/apply:os.system [echo unsafe]\n'):
            with self.subTest(body=body), self.assertRaises((ValueError, yaml.YAMLError)):
                self.import_yaml(body)

    def test_external_ref_is_retained_without_any_ref_fetch(self):
        raw = b'openapi: 3.1.0\ninfo: {title: Source}\npaths: {}\nvalue: {$ref: "https://source.invalid/private.json"}\n'
        with patch('import_upstream.urlopen', return_value=io.BytesIO(raw)) as fetch:
            document = import_source('source', 'https://source.invalid/openapi.yaml')
        self.assertEqual(document['value'], {'$ref': 'https://source.invalid/private.json'})
        self.assertEqual(fetch.call_count, 1)

    def test_actual_javascript_reader_agrees_on_yaml12_words_and_merge(self):
        module = os.environ.get('RUNTIME_YAML_READER_MODULE')
        if not module:
            self.skipTest('actual js-yaml dependency is installed explicitly by code CI')
        body = 'base: &base {x: 1}\nvalue: {<<: *base, x: 2}\nwords: [Yes, no, on, OFF]\nflags: [true, FALSE]\nresponses: {200: {description: Success}}\n'
        raw = 'openapi: 3.1.0\ninfo: {title: Source}\npaths: {}\n' + body
        code = "const y=require(process.argv[1]);const fs=require('node:fs');process.stdout.write(JSON.stringify(y.load(fs.readFileSync(0,'utf8'))));"
        result = subprocess.run([os.environ.get('RUNTIME_YAML_NODE', 'node'), '-e', code, module],
                                input=raw, text=True, capture_output=True, check=True)
        python = self.import_yaml(body)
        python['info'].pop('x-aisa-source')
        self.assertEqual(python, json.loads(result.stdout))


if __name__ == '__main__':
    unittest.main()
