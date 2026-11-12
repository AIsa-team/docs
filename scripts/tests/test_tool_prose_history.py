import json
from pathlib import Path
import unittest

from tool_prose_history import before_tool_prose_amendment

ROOT = Path(__file__).resolve().parents[2]


class ToolProseHistoryTests(unittest.TestCase):
    def test_all_amended_sources_preserve_every_nonprose_declaration(self):
        rows = json.loads((ROOT / 'docs/tool-prose-changes-20261112.json').read_text())
        names = {row['source_file'] for row in rows}
        self.assertEqual(len(names), 42)
        for name in sorted(names):
            with self.subTest(source=name):
                before_tool_prose_amendment(ROOT, name)

    def test_standalone_gemini_changes_only_operation_prose(self):
        from compose_openapi import digest
        row = json.loads((ROOT / 'docs/tool-prose-static-gemini.json').read_text())
        document = json.loads((ROOT / row['source_file']).read_text())
        operation = document['paths'][row['path']][row['method']]
        for key in ('summary', 'description'):
            self.assertEqual(operation[key], row['after'][key])
            operation[key] = row['before'][key]
        if not row['before_description_present']:
            operation.pop('description')
        self.assertEqual(digest(document), row['base_document_hash'])

    def test_undeclared_schema_change_is_rejected(self):
        name = 'openapi/upstream/apollo.json'
        document = json.loads((ROOT / name).read_text())
        document['paths']['/unexpected'] = {'get': {'operationId': 'not-approved'}}
        with self.assertRaisesRegex(ValueError, 'content hash mismatch'):
            before_tool_prose_amendment(ROOT, name, document)

    def test_undocumented_prose_edit_is_rejected(self):
        name = 'openapi/upstream/apollo.json'
        document = json.loads((ROOT / name).read_text())
        operation = next(op for item in document['paths'].values() for method, op in item.items() if method in ('get', 'post'))
        operation['description'] = 'Unrecorded claim'
        with self.assertRaises(ValueError):
            before_tool_prose_amendment(ROOT, name, document)
