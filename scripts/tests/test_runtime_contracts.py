import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import compose, digest
from pull_openapi import assert_identities, stage
import consolidate_openapi as consolidate


def facts(validation="runtime", method="post"):
    return {
        "openapi": "3.1.0", "servers": [{"url": "https://api.aisa.one"}],
        "security": [{"BearerAuth": []}],
        "components": {"securitySchemes": {"BearerAuth": {"type": "http", "scheme": "bearer"}}},
        "info": {"title": "Similarweb", "version": "1", "x-aisa-document": {"facts_hash": "sha256:facts", "generated_at": "2026-09-29"}},
        "paths": {"/apis/v1/similarweb/test": {method: {
            "operationId": "published_identity", "summary": "Runtime title", "description": "Runtime description",
            "x-aisa-validation": validation, "x-aisa-status": "enabled",
            "x-aisa-pricing": {"default_request_estimate_usd": 0.09},
            "x-aisa-capabilities": {"x402": False},
            "x-aisa-upstream-path": "/provider/test",
            "parameters": [{"name": "switch", "in": "query", "schema": {"type": "boolean", "default": False}}],
            "responses": {"200": {"description": "Success"}}
        }}}
    }


def mirror():
    return {
        "openapi": "3.1.0", "info": {"x-aisa-source": {"kind": "provider_openapi", "url": "https://provider.example/openapi.json", "fetched_at": "2026-09-29", "content_hash": "sha256:mirror", "converter": "fixture@1"}},
        "servers": [{"url": "https://secret-provider.example"}],
        "security": [{"Key": []}],
        "components": {"securitySchemes": {"Key": {"type": "apiKey", "in": "query", "name": "provider_token"}}, "schemas": {"Body": {"type": "object", "properties": {"email": {"type": "string"}}, "required": ["email"]}}},
        "paths": {"/provider/test": {"post": {
            "operationId": "upstream_identity", "summary": "Wrong title", "description": "Provider text",
            "servers": [{"url": "https://secret-provider.example"}], "security": [{"Key": []}],
            "parameters": [{"name": "switch", "in": "query", "schema": {"type": "string"}}, {"name": "provider_token", "in": "query", "schema": {"type": "string"}}],
            "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Body"}}}},
            "x-aisa-pricing": {"default_request_estimate_usd": 1000}
        }}}
    }


def operation(document):
    return next(op for item in document["paths"].values() for method, op in item.items())


class CompositionTests(unittest.TestCase):
    def test_runtime_authority_overlay_and_disabled(self):
        source = facts()
        operation(source)["x-aisa-status"] = "disabled"
        document, pending = compose(source, mirror(), {"published_identity": {"description": "Editorial", "x-aisa-notes": ["Latest completed month only"]}})
        self.assertFalse(pending)
        op = operation(document)
        self.assertEqual(op["operationId"], "published_identity")
        self.assertEqual(op["summary"], "Runtime title")
        self.assertEqual(op["description"], "Editorial")
        self.assertEqual(op["x-aisa-pricing"]["default_request_estimate_usd"], 0.09)
        self.assertEqual(op["x-aisa-status"], "disabled")
        self.assertEqual(op["x-aisa-constraints"]["notes"], ["Latest completed month only"])
        self.assertNotIn("requestBody", op)
        self.assertNotIn("document_hash", source["info"]["x-aisa-document"])

    def test_mixed_opaque_query_keeps_provider_body_and_removes_auth(self):
        document, pending = compose(facts("mixed"), mirror())
        self.assertFalse(pending)
        op = operation(document)
        self.assertEqual(op["parameters"], operation(facts())["parameters"])
        self.assertEqual(op["requestBody"]["content"]["application/json"]["schema"]["required"], ["email"])
        self.assertNotIn("secret-provider", json.dumps(document))
        self.assertNotIn("provider_token", json.dumps(document))
        self.assertNotIn("security", op)

    def test_mixed_body_allof_runtime_fields_override_without_intersection(self):
        runtime, upstream = facts("mixed"), mirror()
        operation(runtime)["requestBody"] = {"content": {"application/json": {"schema": {"type": "object", "properties": {"limit": {"type": "integer", "maximum": 5}}, "additionalProperties": True}}}}
        upstream["components"]["schemas"]["Body"] = {"allOf": [{"type": "object", "properties": {"limit": {"type": "string"}}, "required": ["limit"]}, {"type": "object", "properties": {"email": {"type": "string"}}, "required": ["email"]}]}
        document, pending = compose(runtime, upstream)
        self.assertFalse(pending)
        schema = operation(document)["requestBody"]["content"]["application/json"]["schema"]
        self.assertNotIn("allOf", schema)
        self.assertEqual(schema["properties"]["limit"], {"type": "integer", "maximum": 5})
        self.assertEqual(schema["required"], ["email"])
        self.assertIn("email", schema["properties"])

    def test_query_policy_does_not_expose_rejected_or_ignored_parameters(self):
        upstream = mirror()
        upstream["paths"]["/provider/test"]["post"]["parameters"].append({"name": "upstream_only", "in": "query", "schema": {"type": "integer"}})
        for ignore in (False, True):
            runtime = facts("mixed")
            operation(runtime)["x-aisa-query-policy"] = {"request_wins": False, "ignore_undeclared": ignore}
            document, pending = compose(runtime, upstream)
            self.assertFalse(pending)
            self.assertEqual([p["name"] for p in operation(document)["parameters"]], ["switch"])
        operation(runtime)["x-aisa-query-policy"]["request_wins"] = True
        document, _ = compose(runtime, upstream)
        self.assertEqual([p["name"] for p in operation(document)["parameters"]], ["switch", "upstream_only"])

    def test_nested_mixed_body_preserves_undeclared_provider_fields(self):
        runtime, upstream = facts("mixed"), mirror()
        operation(runtime)["requestBody"] = {"content": {"application/json": {"schema": {"type": "object", "properties": {"options": {"type": "object", "properties": {"limit": {"type": "integer"}}, "additionalProperties": True}}}}}}
        upstream["components"]["schemas"]["Body"] = {"type": "object", "properties": {"options": {"type": "object", "properties": {"limit": {"type": "string"}, "country": {"type": "string"}}, "required": ["country", "limit"]}}}
        document, pending = compose(runtime, upstream)
        self.assertFalse(pending)
        schema = operation(document)["requestBody"]["content"]["application/json"]["schema"]["properties"]["options"]
        self.assertEqual(schema["properties"], {"limit": {"type": "integer"}, "country": {"type": "string"}})
        self.assertEqual(schema["required"], ["country"])

    def test_unsupported_upstream_is_pending(self):
        for ref in ("https://provider.example/schema.json", "#/components/schemas/Body"):
            upstream = mirror()
            upstream["components"]["schemas"]["Body"] = {"$ref": ref}
            result, pending = compose(facts("provider"), upstream)
            self.assertEqual(result["paths"], {})
            self.assertEqual(len(pending), 1)
        result, pending = compose(facts("mixed"))
        self.assertEqual(result["paths"], {})
        self.assertEqual(pending[0]["reason"], "upstream operation missing")

    def test_any_preserves_identity_or_stays_pending(self):
        source = facts("provider", "x-aisa-any")
        result, pending = compose(source, mirror())
        self.assertFalse(pending)
        self.assertEqual(operation(result)["operationId"], "published_identity")
        upstream = mirror()
        upstream["paths"]["/provider/test"]["get"] = upstream["paths"]["/provider/test"]["post"]
        ambiguous, pending = compose(source, upstream)
        self.assertEqual(ambiguous["paths"], {})
        self.assertEqual(pending[0]["reason"], "ambiguous_method_identity")
        with self.assertRaises(ValueError):
            assert_identities(result, ambiguous)

    def test_hash_ignores_generation_time_and_tracks_inputs(self):
        source = facts()
        first, _ = compose(source)
        source["info"]["x-aisa-document"]["generated_at"] = "later"
        second, _ = compose(source)
        self.assertEqual(first["info"]["x-aisa-document"]["document_hash"], second["info"]["x-aisa-document"]["document_hash"])
        third, _ = compose(source, overlay={"published_identity": {"description": "New prose"}})
        self.assertNotEqual(first["info"]["x-aisa-document"]["document_hash"], third["info"]["x-aisa-document"]["document_hash"])
        source["info"]["x-aisa-document"]["facts_hash"] = "sha256:disabled"
        fourth, _ = compose(source)
        self.assertNotEqual(first["info"]["x-aisa-document"]["document_hash"], fourth["info"]["x-aisa-document"]["document_hash"])

    def test_overlay_rejects_structural_or_price_overrides(self):
        for entry in ({"summary": "oops"}, {"parameters": []}, {"description": "Costs $0.5"}, {"x-aisa-notes": "not a list"}):
            with self.assertRaises(ValueError):
                compose(facts(), overlay={"published_identity": entry})

    def test_provenance_is_required(self):
        upstream = mirror()
        upstream["info"] = {}
        with self.assertRaises(ValueError):
            compose(facts("provider"), upstream)


class PullTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "openapi").mkdir()
        (self.root / "facts").mkdir()
        (self.root / "openapi/registry.yaml").write_text("auto_register: false\nproviders:\n  similarweb: {}\n")
        (self.root / "facts/similarweb.json").write_text(json.dumps(facts()))
        (self.root / "docs.json").write_text(json.dumps({"navigation": {"languages": [{"language": language, "tabs": [{"tab": tab, "groups": []}]} for language, tab in (("en", "API Reference"), ("zh", "API 参考"))]}}))

    def tearDown(self):
        self.temp.cleanup()

    def write(self, changes):
        for path, text in changes.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    def test_dryrun_write_and_idempotent_pages(self):
        changes, summary = stage(self.root, self.root / "facts", "unused")
        self.assertFalse((self.root / "openapi/similarweb.json").exists())
        self.assertEqual(summary["similarweb"]["operations"], 1)
        self.write(changes)
        page = self.root / "api-reference/similarweb/published_identity.mdx"
        self.assertTrue(page.exists())
        self.assertTrue((self.root / "zh/api-reference/similarweb/published_identity.mdx").exists())
        page.write_text(page.read_text() + "\nHandwritten business prose.\n")
        changes, _ = stage(self.root, self.root / "facts", "unused")
        self.assertEqual(changes, {})
        self.assertIn("Handwritten business prose.", page.read_text())

    def test_first_cutover_reuses_legacy_page_and_preserves_prose(self):
        old = facts()
        old["servers"] = [{"url": "https://api.aisa.one/apis/v1"}]
        old["paths"] = {"/similarweb/test": old["paths"]["/apis/v1/similarweb/test"]}
        old["info"].pop("x-aisa-document")
        (self.root / "openapi/similarweb.json").write_text(json.dumps(old))
        page = self.root / "api-reference/similarweb/post_similarweb-test.mdx"
        page.parent.mkdir(parents=True)
        page.write_text('---\ntitle: "Published title"\nopenapi: "openapi/similarweb.json POST /similarweb/test"\n---\nBusiness prose.\n')
        changes, _ = stage(self.root, self.root / "facts", "unused")
        self.write(changes)
        self.assertIn("Business prose.", page.read_text())
        self.assertIn("POST /apis/v1/similarweb/test", page.read_text())
        self.assertFalse((page.parent / "published_identity.mdx").exists())
        from validate_api_reference_slugs import validate
        self.assertEqual(validate(self.root, generated_only=True), [])
        changes, _ = stage(self.root, self.root / "facts", "unused")
        self.assertEqual(changes, {})

    def test_disabled_notice_updates_without_losing_prose(self):
        changes, _ = stage(self.root, self.root / "facts", "unused")
        self.write(changes)
        page = self.root / "api-reference/similarweb/published_identity.mdx"
        page.write_text(page.read_text() + "Handwritten prose.\n")
        source = facts()
        operation(source)["x-aisa-status"] = "disabled"
        source["info"]["x-aisa-document"]["facts_hash"] = "sha256:disabled"
        (self.root / "facts/similarweb.json").write_text(json.dumps(source))
        changes, _ = stage(self.root, self.root / "facts", "unused")
        self.write(changes)
        self.assertIn("Currently disabled.", page.read_text())
        self.assertIn("Handwritten prose.", page.read_text())
        changes, _ = stage(self.root, self.root / "facts", "unused")
        self.assertEqual(changes, {})
        from validate_api_reference_slugs import validate
        self.assertEqual(validate(self.root), [])

    def test_identity_change_aborts_before_writing(self):
        changes, _ = stage(self.root, self.root / "facts", "unused", False)
        self.write(changes)
        published = (self.root / "openapi/similarweb.json").read_text()
        source = facts()
        operation(source)["operationId"] = "renamed"
        (self.root / "facts/similarweb.json").write_text(json.dumps(source))
        with self.assertRaises(ValueError):
            stage(self.root, self.root / "facts", "unused", False)
        self.assertEqual((self.root / "openapi/similarweb.json").read_text(), published)

    def test_304_still_recomposes_overlay(self):
        changes, _ = stage(self.root, self.root / "facts", "unused", False)
        self.write(changes)
        (self.root / "openapi/overlays").mkdir()
        (self.root / "openapi/overlays/similarweb.yaml").write_text("published_identity:\n  description: Changed editorial\n")
        with patch("pull_openapi.fetch_json", return_value=None) as fetch:
            changes, _ = stage(self.root, None, "http://localhost", False)
        self.assertIn('"sha256:facts"', fetch.call_args.args)
        document = json.loads(changes[self.root / "openapi/similarweb.json"])
        self.assertEqual(operation(document)["description"], "Changed editorial")


class ConsolidationTests(unittest.TestCase):
    def test_runtime_does_not_inherit_inferred_x402_or_wrong_server(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document, _ = compose(facts())
            (root / "similarweb.json").write_text(json.dumps(document))
            (root / "pending.json").write_text(json.dumps({"providers": {"bogus": []}}))
            with patch.object(consolidate, "OPENAPI_DIR", directory):
                unified = consolidate.build_unified_spec()
            consolidate.inject_x402_annotations(unified)
            op = operation(unified)
            self.assertNotIn("x-x402", op)
            self.assertEqual(op["servers"], [{"url": "https://api.aisa.one"}])
            self.assertEqual(list(unified["paths"]), ["/apis/v1/similarweb/test"])
            self.assertEqual(unified["info"]["x-aisa-document"]["providers"]["similarweb"]["facts_hash"], "sha256:facts")

    def test_legacy_inference_retained(self):
        legacy = {"paths": {"/old": {"get": {"operationId": "old"}}}}
        self.assertEqual(consolidate.inject_x402_annotations(legacy), 1)
        self.assertEqual(legacy["paths"]["/old"]["get"]["x-x402"]["path"], "/apis/v2/old")

    def test_component_collisions_rewrite_references(self):
        unified = {"components": {"schemas": {"Error": {"type": "string"}}}}
        spec = {"components": {"schemas": {"Error": {"type": "object"}}}, "paths": {"/foo": {"get": {"responses": {"400": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}}}}}}
        consolidate.merge_components(unified, spec, "similarweb.json")
        self.assertEqual(spec["paths"]["/foo"]["get"]["responses"]["400"]["content"]["application/json"]["schema"]["$ref"], "#/components/schemas/Similarweb_Error")
        self.assertIn("Similarweb_Error", unified["components"]["schemas"])


if __name__ == "__main__":
    unittest.main()
