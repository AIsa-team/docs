"""G6 structural gate for pagination and latency declarations (Spec #1285 R1)."""
import copy
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path[:0] = [str(Path(__file__).resolve().parents[1])]
from release_gate_pagination import check_g6, main


def envelope(param):
    return {"type": "object", "additionalProperties": False, "required": ["has_more", "next_cursor", "next_param"],
            "properties": {"has_more": {"type": "boolean"}, "next_cursor": {"type": ["string", "null"]},
                           "next_param": {"type": "string", "const": param}}}


def good_document():
    return {
        "openapi": "3.1.0", "info": {"title": "fixture", "version": "1"},
        "components": {
            "parameters": {"Cursor": {"name": "cursor", "in": "query", "schema": {"type": "string"}}},
            "schemas": {
                "SearchBody": {"allOf": [{"$ref": "#/components/schemas/Base"},
                                         {"type": "object", "properties": {"page": {"type": "integer"}}}]},
                "Base": {"type": "object", "properties": {"query": {"type": "string"}}},
                "Users": {"type": "object", "properties": {"users": {"type": "array"}}},
            }},
        "paths": {
            "/users/search": {
                "parameters": [{"$ref": "#/components/parameters/Cursor"}],
                "get": {
                    "operationId": "users_search",
                    "parameters": [{"name": "limit", "in": "query", "schema": {"type": "integer"}}],
                    "x-aisa-pagination": {"style": "cursor", "request": {"param": "cursor", "in": "query", "size_param": "limit"},
                                          "ordering": "unstable", "item_id": "/id"},
                    "x-aisa-latency-class": "fast", "x-aisa-latency": {"timeout_seconds": 30, "basis": "observed"},
                    "responses": {"200": {"description": "ok", "content": {"application/json": {"schema": {
                        "allOf": [{"$ref": "#/components/schemas/Users"},
                                  {"type": "object", "properties": {"aisa_pagination": envelope("cursor")}}]}}}}}}},
            "/posts/search": {"post": {
                "operationId": "posts_search",
                "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/SearchBody"}}}},
                "x-aisa-pagination": {"style": "page", "request": {"param": "page", "in": "body"}, "ordering": "stable", "max_pages": 10},
                "x-aisa-latency": {"timeout_seconds": 95, "basis": "default"},
                "responses": {"200": {"description": "ok", "content": {"application/json": {"schema": {
                    "type": "object", "properties": {"items": {"type": "array"}, "aisa_pagination": envelope("page")}}}}}}}},
            "/web/search": {"get": {
                "operationId": "web_search",
                "parameters": [{"name": "aisa_cursor", "in": "query", "schema": {"type": "string"}}],
                "x-aisa-pagination": {"style": "next_link", "request": {"param": "aisa_cursor", "in": "query"}, "ordering": "unstable"},
                "x-aisa-latency-class": "very_slow", "x-aisa-latency": {"timeout_seconds": 60, "basis": "family"},
                "responses": {"200": {"description": "ok", "content": {"application/json": {"schema": {
                    "type": "object", "properties": {"aisa_pagination": envelope("aisa_cursor")}}}}}}}},
            # Undeclared pagination is not a finding.
            "/profile": {"get": {"operationId": "profile", "parameters": [{"name": "cursor", "in": "query"}],
                                 "responses": {"200": {"description": "ok"}}}},
        }}


def codes(document):
    return [(f["operation_id"], f["code"]) for f in check_g6(document)]


class G6Tests(unittest.TestCase):
    def test_good_document_passes_without_mutation(self):
        document = good_document()
        before = copy.deepcopy(document)
        self.assertEqual(check_g6(document), [])
        self.assertEqual(document, before)

    def test_declared_query_param_missing(self):
        document = good_document()
        del document["paths"]["/users/search"]["parameters"]
        self.assertEqual(codes(document), [("users_search", "pagination_param_undeclared")])

    def test_query_param_declared_in_other_location(self):
        document = good_document()
        document["paths"]["/web/search"]["get"]["parameters"][0]["in"] = "header"
        self.assertEqual(codes(document), [("web_search", "pagination_param_undeclared")])

    def test_body_param_missing(self):
        document = good_document()
        document["components"]["schemas"]["SearchBody"]["allOf"].pop()
        self.assertEqual(codes(document), [("posts_search", "pagination_param_undeclared")])

    def test_wrong_next_param_const(self):
        document = good_document()
        schema = document["paths"]["/posts/search"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
        schema["properties"]["aisa_pagination"] = envelope("cursor")
        finding = check_g6(document)
        self.assertEqual([(f["operation_id"], f["code"]) for f in finding], [("posts_search", "pagination_next_param_mismatch")])
        self.assertEqual(set(finding[0]), {"gate", "operation_id", "path", "method", "code", "detail"})
        self.assertEqual((finding[0]["path"], finding[0]["method"]), ("/posts/search", "POST"))

    def test_next_link_with_other_param(self):
        document = good_document()
        op = document["paths"]["/web/search"]["get"]
        op["parameters"][0]["name"] = "next"
        op["x-aisa-pagination"]["request"]["param"] = "next"
        op["responses"]["200"]["content"]["application/json"]["schema"]["properties"]["aisa_pagination"] = envelope("next")
        self.assertEqual(codes(document), [("web_search", "pagination_next_link_param")])

    def test_missing_envelope(self):
        for variant in ("no_property", "no_content"):
            document = good_document()
            response = document["paths"]["/web/search"]["get"]["responses"]["200"]
            if variant == "no_property":
                response["content"]["application/json"]["schema"]["properties"].pop("aisa_pagination")
            else:
                response.pop("content")
            self.assertEqual(codes(document), [("web_search", "pagination_envelope_missing")], variant)

    def test_bad_timeout(self):
        for value in (29, 96, 45.0, "45", None, True):
            document = good_document()
            document["paths"]["/users/search"]["get"]["x-aisa-latency"]["timeout_seconds"] = value
            self.assertEqual(codes(document), [("users_search", "latency_timeout_invalid")], value)

    def test_timeout_is_optional(self):
        # Runtime omits timeout_seconds while no synchronous budget is enforced.
        document = good_document()
        document["paths"]["/users/search"]["get"]["x-aisa-latency"].pop("timeout_seconds")
        self.assertEqual(codes(document), [])

    def test_bad_enums(self):
        document = good_document()
        op = document["paths"]["/users/search"]["get"]
        op["x-aisa-pagination"]["style"] = "token"
        op["x-aisa-pagination"]["ordering"] = "random"
        op["x-aisa-latency-class"] = "medium"
        self.assertEqual(sorted(code for _, code in codes(document)),
                         ["latency_class_invalid", "pagination_ordering_invalid", "pagination_style_invalid"])

    def test_cli_blocks_by_default_and_rollback_switch_reports_only(self):
        bad = good_document()
        bad["paths"]["/users/search"]["get"]["x-aisa-latency"]["timeout_seconds"] = 120
        with tempfile.TemporaryDirectory() as directory:
            good_path, bad_path, yaml_path = (Path(directory) / name for name in ("good.json", "bad.json", "bad.yaml"))
            good_path.write_text(json.dumps(good_document()))
            bad_path.write_text(json.dumps(bad))
            yaml_path.write_text(json.dumps(bad))  # JSON is valid YAML
            def run(*args, env=None):
                out = io.StringIO()
                with redirect_stdout(out), patch.dict("os.environ", env or {}, clear=False):
                    status = main([str(a) for a in args])
                return status, json.loads(out.getvalue())
            with patch.dict("os.environ", {"AISA_G6_REPORT_ONLY": ""}):
                self.assertEqual(run(good_path)[0], 0)
                status, report = run(bad_path)
                self.assertEqual(status, 1)
                self.assertTrue(report["blocking"])
                self.assertEqual(report["findings"][0]["code"], "latency_timeout_invalid")
                self.assertEqual(run(yaml_path)[0], 1)
                status, report = run(bad_path, "--rollback-report-only")
                self.assertEqual(status, 0)
                self.assertFalse(report["blocking"])
                self.assertEqual(len(report["findings"]), 1)
                self.assertEqual(run(bad_path, env={"AISA_G6_REPORT_ONLY": "1"})[0], 0)


if __name__ == "__main__":
    unittest.main()
