import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import compose, digest
from import_querit_reference import REFERENCE_URL, convert_reference
from import_upstream import import_source
from test_runtime_contracts import facts, operation


def html(extra=""):
    return ('''<script>throw new Error("must never run");</script>
<h2>Overview</h2><p>Endpoint: POST https://api.querit.ai/v1/search</p>
<p>Auth: Authorization: Bearer {API_KEY}</p><p>Content-Type: application/json</p>
<h2>Request Body</h2>
<table><tr><th>Parameter</th><th>Type</th><th>Required</th><th>Default</th><th>Description</th></tr>
<tr><td>input</td><td>string</td><td>Yes</td><td>—</td><td>Input text.</td></tr>
<tr><td>count</td><td>integer</td><td>No</td><td>server default</td><td>Result count.</td></tr>
<tr><td>enabled</td><td>boolean</td><td>No</td><td>false</td><td>Flag.</td></tr>
<tr><td>options</td><td>boolean | object</td><td>No</td><td>—</td><td>Options.</td></tr>
''' + extra + '''</table>
<table><tr><th>Field</th><th>Type</th><th>Description</th></tr>
<tr><td>options.length</td><td>integer</td><td>Length between 100 and 8000.</td></tr>
<tr><td>options.locale.names</td><td>string[]</td><td>Allowed names.</td></tr></table>
<p>locale.names allowed values: english, french.</p>
<h2>Response Schema</h2><table><tr><th>Field</th><th>Type</th><th>Description</th></tr>
<tr><td>result.items[]</td><td>object[]</td><td>Result items.</td></tr></table>
<p>Item fields are optional; do not guess their types.</p>
<h2>Error Handling</h2><table><tr><th>HTTP</th><th>Meaning</th></tr><tr><td>400</td><td>Invalid</td></tr></table>''').encode()


class QueritReferenceTests(unittest.TestCase):
    def test_typed_tables_preserve_required_defaults_union_and_nested_limits(self):
        document, source = convert_reference(html())
        op = operation(document)
        schema = op["requestBody"]["content"]["application/json"]["schema"]
        self.assertEqual(schema["required"], ["input"])
        self.assertNotIn("default", schema["properties"]["count"])
        self.assertIs(schema["properties"]["enabled"]["default"], False)
        validator = Draft202012Validator(schema)
        self.assertTrue(validator.is_valid({"input": "test", "options": True}))
        self.assertTrue(validator.is_valid({"input": "test", "options": {"length": 300, "locale": {"names": ["french"]}}}))
        for invalid in [{}, {"input": 5}, {"input": "test", "options": {"length": 99}}, {"input": "test", "options": {"locale": {"names": ["unknown"]}}}]:
            self.assertFalse(validator.is_valid(invalid), invalid)
        response = op["responses"]["200"]["content"]["application/json"]["schema"]
        self.assertEqual(response["properties"]["result"]["properties"]["items"]["items"]["type"], "object")
        self.assertNotIn("throw", json.dumps(document))
        self.assertEqual(source["source_pages"][0]["url"], REFERENCE_URL)
        self.assertTrue(source["source_pages"][0]["raw_content_hash"].startswith("sha256:"))

    def test_new_field_is_discovered_without_a_handwritten_name_map(self):
        row = '<tr><td>future_field</td><td>integer</td><td>Yes</td><td>2</td><td>New official field.</td></tr>'
        document, _ = convert_reference(html(row))
        schema = operation(document)["requestBody"]["content"]["application/json"]["schema"]
        self.assertEqual(schema["properties"]["future_field"]["default"], 2)
        self.assertIn("future_field", schema["required"])

    def test_changed_types_columns_and_ambiguous_field_constraints_fail_closed(self):
        cases = [html().replace(b'<td>integer</td>', b'<td>mystery</td>', 1),
                 html().replace(b'<th>Required</th>', b'<th>Maybe</th>'),
                 html().replace(b'<td>Yes</td>', b'<td>Conditional</td>'),
                 html().replace(b'<td>false</td>', b'<td>10</td>'),
                 html().replace(b'locale.names allowed values:', b'unknown.names allowed values:')]
        for source in cases:
            with self.subTest(source=source[:80]), self.assertRaises(ValueError):
                convert_reference(source)

    def test_import_dispatch_and_runtime_price_identity_are_preserved(self):
        document, metadata = convert_reference(html())
        with patch("import_upstream.import_querit_reference", return_value=(copy.deepcopy(document), metadata)):
            upstream = import_source("querit-official", REFERENCE_URL)
        imported = copy.deepcopy(upstream)
        provenance = imported["info"].pop("x-aisa-source")
        self.assertEqual(provenance["content_hash"], digest(imported))
        runtime = facts("provider")
        operation(runtime)["x-aisa-upstream-path"] = "/v1/search"
        output, pending = compose(runtime, upstream)
        self.assertFalse(pending)
        self.assertEqual(operation(output)["operationId"], operation(runtime)["operationId"])
        self.assertEqual(operation(output)["x-aisa-pricing"], operation(runtime)["x-aisa-pricing"])
        self.assertIn("requestBody", operation(output))


if __name__ == "__main__":
    unittest.main()
