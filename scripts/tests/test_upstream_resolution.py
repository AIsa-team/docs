import copy
import unittest

from jsonschema import Draft202012Validator
from test_runtime_contracts import facts, mirror, operation
from compose_openapi import compose, resolve, upstream_path_item


class UpstreamResolutionTests(unittest.TestCase):
    def test_server_precedence_and_variable_defaults(self):
        source = {"servers": [{"url": "https://example.test/api/{version}", "variables": {"version": {"default": "v3"}}}],
                  "paths": {"/ping": {"get": {}}}}
        self.assertIn("get", upstream_path_item(source, "/api/v3/ping"))
        self.assertIn("get", upstream_path_item(source, "/ping"))
        item = source["paths"]["/ping"]
        item["servers"] = [{"url": "/path"}]
        self.assertFalse(upstream_path_item(source, "/api/v3/ping"))
        self.assertIn("get", upstream_path_item(source, "/path/ping"))
        item["get"]["servers"] = [{"url": "/operation"}]
        self.assertFalse(upstream_path_item(source, "/path/ping"))
        self.assertIn("get", upstream_path_item(source, "/operation/ping"))
        item["get"]["servers"] = [{"url": "/{unknown}"}]
        self.assertFalse(upstream_path_item(source, "/guess/ping"))
        item["get"]["servers"] = []
        self.assertIn("get", upstream_path_item(source, "/ping"))

    def test_prefixed_composition_and_path_parameters(self):
        runtime, upstream = facts("provider"), mirror()
        operation(runtime)["x-aisa-upstream-path"] = "/v3/provider/test"
        operation(upstream).pop("servers")
        upstream["servers"] = [{"url": "https://example.test/v3"}, {"url": "https://backup.test/v3"}]
        upstream["paths"]["/provider/test"]["parameters"] = [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}]
        output, pending = compose(runtime, upstream)
        self.assertFalse(pending)
        self.assertIn("id", [p["name"] for p in operation(output)["parameters"]])

    def test_ambiguous_effective_path_is_pending(self):
        runtime, upstream = facts("provider"), mirror()
        upstream["paths"]["/test"] = {"post": copy.deepcopy(operation(upstream))}
        upstream["paths"]["/test"]["post"]["servers"] = [{"url": "/provider"}]
        output, pending = compose(runtime, upstream)
        self.assertFalse(output["paths"])
        self.assertEqual(pending[0]["reason"], "ambiguous upstream server-path operation")

    def test_schema_sibling_constraints_intersect_and_annotations_override(self):
        source = {"components": {"schemas": {"Count": {"type": "integer", "minimum": 2, "maximum": 10, "example": 3}}}}
        resolved = resolve({"$ref": "#/components/schemas/Count", "minimum": 0, "maximum": 5, "example": 4}, source)
        self.assertEqual(resolved["example"], 4)
        validator = Draft202012Validator(resolved)
        self.assertTrue(validator.is_valid(4))
        self.assertFalse(validator.is_valid(1))
        self.assertFalse(validator.is_valid(6))

    def test_mixed_ref_siblings_preserve_unowned_intersection(self):
        runtime, upstream = facts("mixed"), mirror()
        upstream["components"]["schemas"]["Body"] = {"type": "object", "properties": {"owned": {"type": "string"}, "count": {"type": "integer", "minimum": 2}}}
        operation(upstream)["requestBody"]["content"]["application/json"]["schema"].update({"properties": {"owned": {"maxLength": 4}, "count": {"maximum": 5}}})
        operation(runtime)["requestBody"] = {"content": {"application/json": {"schema": {"type": "object", "properties": {"owned": {"type": "integer"}}}}}}
        output, pending = compose(runtime, upstream)
        self.assertFalse(pending)
        schema = operation(output)["requestBody"]["content"]["application/json"]["schema"]
        self.assertEqual(schema["properties"]["owned"], {"type": "integer"})
        validator = Draft202012Validator(schema)
        self.assertTrue(validator.is_valid({"owned": 7, "count": 4}))
        self.assertFalse(validator.is_valid({"owned": 7, "count": 1}))
        self.assertFalse(validator.is_valid({"owned": 7, "count": 6}))

    def test_mixed_closed_allof_stays_pending_without_widening(self):
        runtime, upstream = facts("mixed"), mirror()
        upstream["components"]["schemas"]["Body"] = {"allOf": [{"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": False}, {"type": "object", "properties": {"b": {"type": "string"}}}]}
        operation(runtime)["requestBody"] = {"content": {"application/json": {"schema": {"properties": {"a": {"type": "integer"}}}}}}
        output, pending = compose(runtime, upstream)
        self.assertFalse(output["paths"])
        self.assertEqual(pending[0]["reason"], "mixed upstream allOf has branch-local additionalProperties")

    def test_non_schema_siblings_and_schema_scope_fail_closed(self):
        source = {"components": {"parameters": {"ID": {"name": "id", "in": "path"}}, "schemas": {"Body": {"type": "object"}}}}
        with self.assertRaisesRegex(ValueError, "non-schema"):
            resolve({"$ref": "#/components/parameters/ID", "required": True}, source)
        with self.assertRaisesRegex(ValueError, "scope"):
            resolve({"$ref": "#/components/schemas/Body", "$id": "other.json"}, source)


if __name__ == "__main__":
    unittest.main()
