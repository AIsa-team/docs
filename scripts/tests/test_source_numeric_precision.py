import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from source_json import UnsupportedNumericPrecision
from import_upstream import import_source
from pull_openapi import read_json, fetch_json, stage, main
from runtime_consolidate_openapi import load_spec
from test_runtime_contracts import facts, operation


class SourceNumericPrecisionTests(unittest.TestCase):
    def document(self, token):
        return ('{"openapi":"3.1.0","info":{"title":"Source"},"paths":{"/one":{"get":'
                '{"responses":{"200":{"description":"Success","content":{"application/json":'
                '{"schema":{"type":"number","example":' + token + '}}}}}}}}}').encode()

    def test_actual_import_uses_json_types_and_rejects_unsupported_precision(self):
        for token in ('0.125', '1e3', '1.0000000000000002'):
            with self.subTest(token=token), patch('import_upstream.urlopen', side_effect=lambda *a, **k: io.BytesIO(self.document(token))):
                document = import_source('precision', 'https://example.invalid/openapi.json')
                actual = document['paths']['/one']['get']['responses']['200']['content']['application/json']['schema']['example']
                self.assertEqual(actual, float(token))
                self.assertIsInstance(actual, float)
        for token in ('1.0000000000000001', '1e400', '1e-400', 'NaN', 'Infinity'):
            with self.subTest(token=token), patch('import_upstream.urlopen', side_effect=lambda *a, **k: io.BytesIO(self.document(token))):
                with self.assertRaisesRegex(UnsupportedNumericPrecision, 'unsupported_numeric_precision'):
                    import_source('precision', 'https://example.invalid/openapi.json')

    def test_yaml_keeps_supported_types_but_rejects_ambiguous_or_unsupported_scalars(self):
        template = 'openapi: 3.1.0\ninfo: {title: Source}\npaths: {}\nvalue: %s\n'
        for token, expected in [('0.125', 0.125), ('true', True), ("'1e400'", '1e400'), ("'0123'", '0123')]:
            with patch('import_upstream.urlopen', return_value=io.BytesIO((template % token).encode())):
                self.assertEqual(import_source('precision', 'https://example.invalid/openapi.yaml')['value'], expected)
        for token in ('1.0000000000000001', '1.0e+400', '1e400', '0123', '0129', '.inf', 'yes', '2026-10-03'):
            with self.subTest(token=token), patch('import_upstream.urlopen', return_value=io.BytesIO((template % token).encode())):
                with self.assertRaisesRegex(ValueError, 'unsupported_(numeric_precision|yaml_scalar)'):
                    import_source('precision', 'https://example.invalid/openapi.yaml')

    def test_all_actual_json_entrypoints_reject_bad_numbers_before_publication(self):
        for token in ('1.0000000000000001', '1e400'):
            raw = self.document(token)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'source.json'; path.write_bytes(raw)
                for reader in (read_json, load_spec):
                    with self.subTest(token=token, reader=reader.__name__), self.assertRaisesRegex(UnsupportedNumericPrecision, 'unsupported_numeric_precision'):
                        reader(path)
            with patch('pull_openapi.urlopen', return_value=io.BytesIO(raw)):
                with self.assertRaisesRegex(UnsupportedNumericPrecision, 'unsupported_numeric_precision'):
                    fetch_json('https://example.invalid/facts')

    def test_actual_pull_composition_and_aggregate_keep_supported_values_and_last_good(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'openapi').mkdir(); (root / 'facts').mkdir()
            registry = 'providers:\n  similarweb:\n    upstream: https://example.invalid/openapi.json\n'
            (root / 'openapi/registry.yaml').write_text('auto_register: false\n' + registry)
            # Acquire a real source through the actual importer, then consume
            # its exact bound response declaration through pull and publishing.
            raw = self.document('0.125').replace(b'"/one"', b'"/provider/test"').replace(b'"get":', b'"post":')
            with patch('import_upstream.urlopen', return_value=io.BytesIO(raw)):
                imported = import_source('similarweb', 'https://example.invalid/openapi.json')
            (root / 'openapi/upstream').mkdir()
            (root / 'openapi/upstream/similarweb.json').write_text(json.dumps(imported))
            source = facts('mixed')
            operation(source)['x-aisa-passthrough'] = True
            operation(source)['parameters'][0]['schema'] = {'type': 'number', 'default': 0.125}
            input_path = root / 'facts/similarweb.json'; input_path.write_text(json.dumps(source))
            changes, _ = stage(root, root/'facts', 'unused', with_pages=False)
            for path, text in changes.items():
                path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
            canonical = root / 'openapi/similarweb.json'
            self.assertEqual(operation(load_spec(canonical))['parameters'][0]['schema']['default'], 0.125)
            self.assertEqual(operation(load_spec(canonical))['responses']['200']['content']['application/json']['schema']['example'], 0.125)
            output = root / 'openapi.yaml'
            subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1]/'runtime_consolidate_openapi.py'),
                            '--root', str(root), '--output', str(output)], check=True, capture_output=True)
            self.assertEqual(operation(yaml.safe_load(output.read_text()))['parameters'][0]['schema']['default'], 0.125)
            self.assertEqual(operation(yaml.safe_load(output.read_text()))['responses']['200']['content']['application/json']['schema']['example'], 0.125)
            before = {path: path.read_bytes() for path in (canonical, output)}
            for token in ('1.0000000000000001', '1e400'):
                input_path.write_text(json.dumps(source).replace('0.125', token))
                with patch.object(sys, 'argv', ['pull', '--root', str(root), '--facts-dir', str(root/'facts'), '--skip-pages', '--write']), patch('sys.stderr', new_callable=io.StringIO) as error:
                    self.assertEqual(main(), 1)
                    self.assertIn('unsupported_numeric_precision', error.getvalue())
                self.assertEqual(before, {path: path.read_bytes() for path in before})
                # Automatic discovery reports a concrete pending gap rather
                # than marking this unsupported input newly complete.
                (root/'openapi/registry.yaml').write_text('auto_register: true\n' + registry)
                (root/'facts/category.json').write_text('{"apis":[{"id":"similarweb"}]}')
                pending_changes, summary = stage(root, root/'facts', 'unused', with_pages=False)
                pending = json.loads(pending_changes[root/'openapi/pending.json'])
                self.assertIn('unsupported_numeric_precision', str(pending['providers']['similarweb']))
                self.assertFalse(summary['similarweb']['changed'])
                self.assertNotIn(canonical, pending_changes)
                (root/'openapi/registry.yaml').write_text('auto_register: false\n' + registry)


if __name__ == '__main__':
    unittest.main()
