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
import runtime_consolidate_openapi as consolidate


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

    def test_editorial_notes_append_without_losing_runtime_constraints(self):
        source = facts()
        runtime_notes = ["Monthly granularity only.", "Maximum range is 12 months."]
        operation(source)["x-aisa-constraints"] = {"notes": runtime_notes, "required_any_of": [["start", "end"]]}
        editorial = {"published_identity": {"x-aisa-notes": ["Monthly granularity only.", "Use the latest published month.", "Use the latest published month."]}}
        document, pending = compose(source, overlay=editorial)
        self.assertFalse(pending)
        constraints = operation(document)["x-aisa-constraints"]
        self.assertEqual(constraints["notes"], [*runtime_notes, "Use the latest published month."])
        self.assertEqual(constraints["required_any_of"], [["start", "end"]])
        self.assertEqual(operation(source)["x-aisa-constraints"]["notes"], runtime_notes)
        self.assertEqual(compose(source, overlay=editorial)[0], document)
        # Malformed runtime input must not be silently coerced into characters.
        operation(source)["x-aisa-constraints"]["notes"] = "not a list"
        malformed, pending = compose(source, overlay=editorial)
        self.assertFalse(malformed["paths"])
        self.assertEqual(pending[0]["reason"], "runtime constraint notes must be a list of text")

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
        for ref in ("https://provider.example/schema.json", "#/components/schemas/Missing"):
            upstream = mirror()
            upstream["components"]["schemas"]["Body"] = {"$ref": ref}
            result, pending = compose(facts("provider"), upstream)
            self.assertEqual(result["paths"], {})
            self.assertEqual(len(pending), 1)
        result, pending = compose(facts("mixed"))
        self.assertEqual(result["paths"], {})
        self.assertEqual(pending[0]["reason"], "upstream operation missing")

    def test_any_preserves_published_methods_and_derives_new_method_ids(self):
        source = facts("provider", "x-aisa-any")
        result, pending = compose(source, mirror())
        self.assertFalse(pending)
        self.assertEqual(operation(result)["operationId"], "published_identity")
        upstream = mirror()
        upstream["paths"]["/provider/test"]["get"] = upstream["paths"]["/provider/test"]["post"]
        expanded, pending = compose(source, upstream, previous=result)
        self.assertFalse(pending)
        methods = expanded["paths"]["/apis/v1/similarweb/test"]
        self.assertEqual(methods["post"]["operationId"], "published_identity")
        self.assertEqual(methods["get"]["operationId"], "get_published_identity")
        assert_identities(result, expanded)
        missing, pending = compose(source)
        self.assertFalse(missing["paths"])
        self.assertEqual(pending[0]["reason"], "upstream operation missing")

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

    def test_version_two_notes_are_repaired_once_with_unchanged_inputs(self):
        source = facts()
        runtime_notes = ["Monthly granularity only.", "Maximum range is 12 months."]
        operation(source)["x-aisa-constraints"] = {"notes": runtime_notes}
        (self.root / "facts/similarweb.json").write_text(json.dumps(source))
        overlay_dir = self.root / "openapi/overlays"
        overlay_dir.mkdir()
        overlay_dir.joinpath("similarweb.yaml").write_text(
            "published_identity:\n  x-aisa-notes:\n    - Use the latest published month.\n")
        # Recreate the published v2 hash and its old notes-overwrite behavior.
        with patch("compose_openapi.VERSION", "2"):
            old_changes, _ = stage(self.root, self.root / "facts", "unused")
        output = self.root / "openapi/similarweb.json"
        old_document = json.loads(old_changes[output])
        operation(old_document)["x-aisa-constraints"]["notes"] = ["Use the latest published month."]
        old_changes[output] = json.dumps(old_document, indent=2, ensure_ascii=False) + "\n"
        self.write(old_changes)
        old_hash = old_document["info"]["x-aisa-document"]["document_hash"]

        changes, summary = stage(self.root, self.root / "facts", "unused")
        self.assertTrue(summary["similarweb"]["changed"])
        repaired = json.loads(changes[output])
        self.assertNotEqual(repaired["info"]["x-aisa-document"]["document_hash"], old_hash)
        self.assertEqual(operation(repaired)["x-aisa-constraints"]["notes"],
                         [*runtime_notes, "Use the latest published month."])
        self.write(changes)
        for _ in range(2):
            changes, summary = stage(self.root, self.root / "facts", "unused")
            self.assertEqual(changes, {})
            self.assertFalse(summary["similarweb"]["changed"])

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
        from validate_runtime_api_reference_slugs import validate
        self.assertEqual(validate(self.root, generated_only=True), [])
        changes, _ = stage(self.root, self.root / "facts", "unused")
        self.assertEqual(changes, {})

    def test_pin_real_legacy_23_restores_bytes_pages_and_localized_references(self):
        import re
        import subprocess
        from types import SimpleNamespace
        from runtime_localize_openapi_zh import split_frontmatter
        from pull_openapi import normalize_paths, operations
        from validate_runtime_api_reference_slugs import validate

        repository = Path(__file__).resolve().parents[2]
        raw = subprocess.check_output(["git", "show", "3a00a91:openapi/similarweb.json"], cwd=repository, text=True, timeout=15)
        legacy = json.loads(raw)
        page_paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", "3a00a91", "api-reference/similarweb"], cwd=repository, text=True, timeout=15).splitlines()
        for name in page_paths:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(subprocess.check_output(["git", "show", f"3a00a91:{name}"], cwd=repository, timeout=15))
        output = self.root / "openapi/similarweb.json"
        output.write_text(raw)
        runtime = normalize_paths(legacy)
        runtime["openapi"] = "3.1.0"
        runtime["servers"] = [{"url": "https://api.aisa.one"}]
        runtime["info"]["x-aisa-document"] = {"facts_hash": "sha256:same23"}
        for _, _, op in operations(runtime):
            op["x-aisa-validation"] = "runtime"
            op["x-aisa-status"] = "enabled"
            op["summary"] = "Runtime " + op["operationId"]
        (self.root / "facts/similarweb.json").write_text(json.dumps(runtime))
        self.write(stage(self.root, self.root / "facts", "unused")[0])
        pages = list((self.root / "api-reference/similarweb").glob("*.mdx")) + list((self.root / "zh/api-reference/similarweb").glob("*.mdx"))
        self.assertEqual(len(pages), 46)
        for page in pages:
            page.write_text(page.read_text() + "\nKeep handwritten prose.\n")
        bodies = {page: split_frontmatter(page.read_text())[1] for page in pages}
        (self.root / "openapi/registry.yaml").write_text("auto_register: false\nproviders:\n  similarweb:\n    pin: 3a00a91\n")
        with patch("pull_openapi.subprocess.run", return_value=SimpleNamespace(stdout=raw)), patch("pull_openapi.fetch_json", side_effect=AssertionError("pin must remain offline")):
            changes, summary = stage(self.root, None, "unused")
            self.assertTrue(summary["similarweb"]["changed"])
            self.assertIsNone(summary["similarweb"]["document_hash"])
            self.write(changes)
            self.assertEqual(output.read_text(), raw)
            self.assertEqual(validate(self.root, generated_only=True), [])
            self.assertEqual(len(list((self.root / "api-reference/similarweb").glob("*.mdx"))), 23)
            self.assertEqual(len(list((self.root / "zh/api-reference/similarweb").glob("*.mdx"))), 23)
            for page in pages:
                self.assertEqual(split_frontmatter(page.read_text())[1], bodies[page])
                reference = json.loads(re.search(r"^openapi:\s*(.*)$", page.read_text(), re.M)[1])
                name, method, path = reference.split()
                document = json.loads((self.root / name).read_text())
                self.assertNotIn("x-aisa-document", document["info"])
                self.assertEqual(document["paths"][path][method.lower()]["operationId"], legacy["paths"][path][method.lower()]["operationId"])
            for _ in range(2):
                changes, summary = stage(self.root, None, "unused")
                self.assertEqual(changes, {})
                self.assertFalse(summary["similarweb"]["changed"])

    def test_generated_pin_remains_supported_and_refuses_removed_routes(self):
        from types import SimpleNamespace
        self.write(stage(self.root, self.root / "facts", "unused")[0])
        output = self.root / "openapi/similarweb.json"
        pinned = output.read_text()
        source = facts()
        operation(source)["summary"] = "New title"
        source["info"]["x-aisa-document"]["facts_hash"] = "sha256:new-title"
        (self.root / "facts/similarweb.json").write_text(json.dumps(source))
        self.write(stage(self.root, self.root / "facts", "unused")[0])
        (self.root / "openapi/registry.yaml").write_text("auto_register: false\nproviders:\n  similarweb:\n    pin: abcdef1\n")
        with patch("pull_openapi.subprocess.run", return_value=SimpleNamespace(stdout=pinned)):
            self.write(stage(self.root, None, "unused")[0])
            self.assertEqual(output.read_text(), pinned)
            self.assertEqual(stage(self.root, None, "unused")[0], {})
            published = json.loads(output.read_text())
            published["paths"]["/apis/v1/similarweb/new-route"] = copy.deepcopy(published["paths"]["/apis/v1/similarweb/test"])
            published["paths"]["/apis/v1/similarweb/new-route"]["post"]["operationId"] = "new-published-id"
            output.write_text(json.dumps(published))
            before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
            with self.assertRaisesRegex(ValueError, "published identity changed or disappeared"):
                stage(self.root, None, "unused")
            self.assertEqual({p: p.read_bytes() for p in before}, before)

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
        from validate_runtime_api_reference_slugs import validate
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




class PublishedResponseTests(unittest.TestCase):
    def test_fallback_is_content_addressed_idempotent_and_never_copies_errors(self):
        previous, runtime = facts(), facts()
        old = operation(previous)
        old["responses"] = {
            "200": {"description": "Published result", "headers": {"Legacy": {"schema": {"type": "string"}}},
                    "content": {"application/json": {"schema": {"type": "object", "properties": {"value": {"type": "integer"}}}, "example": {"value": 7}}}},
            "400": {"description": "Old incompatible error", "content": {"application/json": {"schema": {"type": "string"}}}},
        }
        operation(runtime)["responses"]["200"]["headers"] = {"Current": {"schema": {"type": "integer"}}}
        operation(runtime)["responses"]["default"] = {"description": "Current runtime error"}
        first, pending = compose(runtime, previous=previous)
        self.assertFalse(pending)
        success = operation(first)["responses"]["200"]
        self.assertEqual(success["content"], old["responses"]["200"]["content"])
        self.assertEqual(set(success["headers"]), {"Current"})
        self.assertNotIn("400", operation(first)["responses"])
        self.assertEqual(operation(first)["responses"]["default"], operation(runtime)["responses"]["default"])
        self.assertEqual(operation(first)["x-aisa-response-source"]["kind"], "published_success_contract")
        second, _ = compose(runtime, previous=first)
        third, _ = compose(runtime, previous=second)
        self.assertEqual(first, second)
        self.assertEqual(second, third)
        changed = copy.deepcopy(previous)
        operation(changed)["responses"]["200"]["content"]["application/json"]["example"]["value"] = 8
        edited, _ = compose(runtime, previous=changed)
        self.assertNotEqual(first["info"]["x-aisa-document"]["document_hash"], edited["info"]["x-aisa-document"]["document_hash"])
        # The response fallback requires both the route and immutable ID to match.
        moved = copy.deepcopy(runtime)
        moved["paths"] = {"/new": next(iter(moved["paths"].values()))}
        relocated, _ = compose(moved, previous=previous)
        self.assertNotIn("x-aisa-response-source", operation(relocated))
        self.assertNotIn("content", operation(relocated)["responses"]["200"])
        # Once runtime supplies a real payload contract it becomes authoritative.
        operation(runtime)["responses"]["200"]["content"] = {"application/json": {"schema": {"type": "array"}}}
        authoritative, _ = compose(runtime, previous=first)
        self.assertEqual(operation(authoritative)["responses"]["200"]["content"], operation(runtime)["responses"]["200"]["content"])
        self.assertNotIn("x-aisa-response-source", operation(authoritative))


class FullSimilarwebCutoverTests(unittest.TestCase):
    def test_all_published_routes_titles_payloads_and_unified_defaults_survive(self):
        import shutil
        import subprocess
        from urllib.parse import urlsplit
        from compose_openapi import METHODS, resolve
        from runtime_localize_openapi_zh import key_for
        from pull_openapi import operations
        from validate_runtime_api_reference_slugs import validate

        repository = Path(__file__).resolve().parents[2]
        # Read the actual pre-cutover publication, without duplicating its
        # response schemas in another fixture file. The pull workflow checks
        # out full history; later generated endpoints must not alter this case.
        baseline = "3a00a91"
        page_paths = subprocess.check_output([
            "git", "ls-tree", "-r", "--name-only", baseline, "api-reference/similarweb",
        ], cwd=repository, text=True, timeout=15).splitlines()
        baseline_files = {
            name: subprocess.check_output(["git", "show", f"{baseline}:{name}"], cwd=repository, timeout=15)
            for name in ["openapi/similarweb.json", *page_paths]
        }
        previous = json.loads(baseline_files["openapi/similarweb.json"])
        published = list(operations(previous))
        self.assertEqual(len(published), 23, "exercise the actual entire initial Similarweb catalog")
        legacy_prefix = urlsplit(previous["servers"][0]["url"]).path.rstrip("/")
        runtime = facts()
        runtime["paths"] = {}
        plans = {"payg": 1.5, "similarweb_payg": 2.0, "builder": 1.2, "team": 1.0, "display_plan": "similarweb_payg", "version": "actual-policy-fixture"}
        capabilities = {"quote": {"header": "X-AISA-Cost-Mode", "value": "quote"}, "max_price": "X-AISA-Max-Price-USD", "idempotency": "Idempotency-Key"}
        runtime["info"]["x-aisa-plans"] = plans
        runtime["info"]["x-aisa-capabilities"] = capabilities
        for path, method, old in published:
            op = copy.deepcopy(operation(facts()))
            op["operationId"] = old["operationId"]
            op["summary"] = "Runtime " + old.get("summary", old["operationId"])
            op["description"] = "Current runtime prose"
            op["parameters"] = [{"in": "query", "name": "runtime_query", "schema": {"type": "string"}}]
            op["x-aisa-pricing"] = {"default_request_estimate_usd": 0.15, "customer_multiplier": 2.0}
            op["responses"]["default"] = {"description": "Current runtime error"}
            runtime["paths"].setdefault(legacy_prefix + path, {})[method] = op

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative, content in baseline_files.items():
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
            for relative in ("openapi/registry.yaml", "openapi/overlays/similarweb.yaml", "docs.json", "translations/openapi-zh.json"):
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                from catalog_fixture import catalog_root
                source_root = catalog_root() if relative.startswith('openapi/') else repository
                shutil.copyfile(source_root / relative, destination)
            (root / "openapi/registry.yaml").write_text("auto_register: false\nproviders:\n  similarweb: {}\n")
            original_pages = set((root / "api-reference/similarweb").glob("*.mdx"))
            original_bodies = {p: p.read_text().split("---", 2)[2] for p in original_pages}
            (root / "facts").mkdir()
            facts_path = root / "facts/similarweb.json"
            facts_path.write_text(json.dumps(runtime))

            def publish(changes):
                for path, text in changes.items():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(text)

            changes, summary = stage(root, root / "facts", "unused")
            self.assertEqual(summary["similarweb"]["operations"], 23)
            self.assertEqual(summary["similarweb"]["pending"], 0)
            publish(changes)
            generated = json.loads((root / "openapi/similarweb.json").read_text())
            self.assertEqual(validate(root, generated_only=True), [])
            self.assertEqual(set((root / "api-reference/similarweb").glob("*.mdx")), original_pages)
            for path, method, old in published:
                current = generated["paths"][legacy_prefix + path][method]
                self.assertEqual(current["operationId"], old["operationId"])
                from compose_openapi import resolve_fragment
                expected_output = {"components": {}}
                expected = resolve_fragment({"content": old["responses"]["200"]["content"]}, previous, expected_output, "expected.json")
                self.assertEqual(resolve(current["responses"]["200"], generated)["content"], expected["content"])
                self.assertEqual(current["responses"]["default"], {"description": "Current runtime error"})
                self.assertEqual(current["parameters"], runtime["paths"][legacy_prefix + path][method]["parameters"])
                self.assertEqual(current["x-aisa-pricing"], runtime["paths"][legacy_prefix + path][method]["x-aisa-pricing"])
            for page in original_pages:
                self.assertEqual(page.read_text().split("---", 2)[2], original_bodies[page])
                self.assertIn('title: "Runtime ', page.read_text())
            changes, _ = stage(root, root / "facts", "unused")
            self.assertEqual(changes, {}, "retained success payloads must not change the hash on the next pull")

            # Summary updates refresh both locales without changing page URLs or prose.
            changed_path, changed_method, changed_op = next(operations(runtime))
            changed_op["summary"] = "Updated Endpoint Title"
            runtime["info"]["x-aisa-document"]["facts_hash"] = "sha256:updated-title"
            facts_path.write_text(json.dumps(runtime))
            catalog_path = root / "translations/openapi-zh.json"
            catalog = json.loads(catalog_path.read_text())
            catalog["entries"][key_for("Updated Endpoint Title")] = {"source": "Updated Endpoint Title", "translation": "已更新的端点标题"}
            catalog_path.write_text(json.dumps(catalog))
            target = next(page for page in original_pages if f"{changed_method.upper()} {changed_path}" in page.read_text())
            zh_target = root / "zh" / target.relative_to(root)
            target.write_text(target.read_text() + "\nKeep English prose.\n")
            zh_target.write_text(zh_target.read_text() + "\n保留中文正文。\n")
            changes, _ = stage(root, root / "facts", "unused")
            publish(changes)
            self.assertIn('title: "Updated Endpoint Title"', target.read_text())
            self.assertIn('title: "已更新的端点标题"', zh_target.read_text())
            self.assertIn("Keep English prose.", target.read_text())
            self.assertIn("保留中文正文。", zh_target.read_text())
            self.assertEqual(set((root / "api-reference/similarweb").glob("*.mdx")), original_pages)
            self.assertEqual(validate(root, generated_only=True), [])
            changes, _ = stage(root, root / "facts", "unused")
            self.assertEqual(changes, {}, "third pull must not churn hashes, fallback payloads or titles")

            with patch.object(consolidate, "OPENAPI_DIR", str(root / "openapi")):
                unified = consolidate.build_unified_spec()
            inherited = unified["info"]["x-aisa-document"]["providers"]["similarweb"]
            self.assertEqual(inherited["x-aisa-plans"], plans)
            self.assertEqual(inherited["x-aisa-capabilities"], capabilities)
            self.assertEqual(len(unified["paths"]), 23)
            for path, method, op in operations(unified):
                self.assertEqual(op["x-aisa-provider"], "similarweb")
                self.assertEqual(op["x-aisa-capabilities"]["quote"], capabilities["quote"])
                self.assertFalse(op["x-aisa-capabilities"]["x402"])
                policy = unified["info"]["x-aisa-document"]["providers"][op["x-aisa-provider"]]["x-aisa-plans"]
                self.assertEqual(op["x-aisa-pricing"]["default_request_estimate_usd"] * policy[policy["display_plan"]], 0.30)
                self.assertIn("content", op["responses"]["200"])

class PublicationWorkflowTests(unittest.TestCase):
    def test_only_main_can_publish_while_feature_dispatch_still_stages(self):
        import yaml
        workflow = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github/workflows/pull-openapi.yml").read_text())
        steps = workflow["jobs"]["compose"]["steps"]
        publish = next(step for step in steps if step.get("id") == "publish")
        stage_step = next(step for step in steps if step.get("name") == "Stage contracts")
        self.assertNotIn("if", stage_step, "feature branches must retain dry-run staging")
        self.assertNotIn("if", workflow["jobs"]["compose"], "do not disable the whole dry-run job")
        cases = [
            ("refs/heads/main", "workflow_dispatch", True, "false", "true", True),
            ("refs/heads/feature", "workflow_dispatch", True, "true", "true", False),
            ("refs/heads/main", "workflow_dispatch", False, "true", "true", False),
            ("refs/heads/main", "schedule", False, "true", "true", True),
            ("refs/heads/main", "schedule", False, "false", "true", False),
            ("refs/heads/main", "workflow_dispatch", True, "true", "false", False),
        ]
        for ref, event, manual, configured, available, expected in cases:
            with self.subTest(ref=ref, event=event, manual=manual, configured=configured, available=available):
                # The tested workflow expression uses only literals, comparisons
                # and boolean operators; substitute its actual event inputs.
                condition = publish["if"]
                for name, value in {"github.ref": ref, "github.event_name": event,
                                    "inputs.publish": manual, "vars.RUNTIME_CONTRACT_PUBLISH": configured,
                                    "steps.pull.outputs.available": available}.items():
                    condition = condition.replace(name, repr(value))
                condition = condition.replace("&&", "and").replace("||", "or").replace(" == true", " == True")
                self.assertEqual(eval(condition, {"__builtins__": {}}), expected)


if __name__ == "__main__":
    unittest.main()
