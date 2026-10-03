import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime_consolidate_openapi import publication_yaml


class RuntimeYamlStringTests(unittest.TestCase):
    def fixture(self):
        # Real CNPJa identifier and TikHub profile hash, plus future implicit
        # scalar formats. Types and literal bytes must survive publication.
        return {'example': {'taxId': '06990590000123'},
                'x-aisa-revision': {'profile_ref': '2548e7534682'},
                'strings': ['2.548e7534685', '1e3', '0123', '0xFF', '1_000', '.NaN', '.inf',
                            'null', 'true', 'no', '2026-10-03', '12:34:56',
                            'line one\nline two\n', 'line one\nline two'],
                '007': '001', 'numbers': [123, 13.5], 'flags': [True, False, None]}

    def test_python_roundtrip_preserves_every_scalar_type_and_value(self):
        fixture = self.fixture()
        self.assertEqual(fixture, yaml.safe_load(publication_yaml(fixture)))
        # The dedicated dumper must not change the existing legacy serializer.
        self.assertEqual('plain\n...\n', yaml.dump('plain'))

    def test_actual_javascript_yaml_reader_preserves_numeric_shaped_strings(self):
        module = os.environ.get('RUNTIME_YAML_READER_MODULE')
        if not module:
            self.skipTest('actual js-yaml dependency is installed explicitly by code CI')
        fixture = self.fixture()
        code = "const yaml=require(process.argv[1]); const fs=require('node:fs'); process.stdout.write(JSON.stringify(yaml.load(fs.readFileSync(0,'utf8'))));"
        result = subprocess.run([os.environ.get('RUNTIME_YAML_NODE', 'node'), '-e', code, module],
                                input=publication_yaml(fixture), text=True,
                                capture_output=True, check=True)
        self.assertEqual(fixture, json.loads(result.stdout))


if __name__ == '__main__':
    unittest.main()
