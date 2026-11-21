"""Synthetic contract fixtures exercise transformation; no business calls run."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sync_tasks as sync


def detail(task_id="creators.search"):
    return {
        "task_id": task_id, "domain": task_id.split(".")[0], "method": "POST",
        "path": "/v1/tasks/" + task_id, "name": "Find creators", "description": "Test contract",
        "version": 1, "strategy": "merge", "billing": {"mode": "per_unit"},
        "input": [{"name": "platform", "type": "string", "enum": ["tiktok", "instagram"]}],
        "request_schema": {"$ref": "#/$defs/Request", "$defs": {
            "Request": {"type": "object", "required": ["input"], "properties": {"input": {"$ref": "#/$defs/Input"}}},
            "Input": {"type": "object", "properties": {"platform": {"enum": ["tiktok", "instagram"]}, "countries": {"type": "array", "maxItems": 2, "items": {"enum": ["US", "GB"]}}},
                      "allOf": [{"if": {"required": ["countries"]}, "then": {"required": ["platform"], "properties": {"platform": {"const": "tiktok"}}}}]},
        }},
        "response_schema": {"$ref": "#/$defs/Response", "$defs": {
            "Response": {"type": "object", "properties": {"result": {"anyOf": [{"$ref": "#/$defs/Identity"}, {"type": "null"}]}, "meta": {"type": "object", "additionalProperties": False, "properties": {"delivered": {"type": "boolean"}}}}},
            "Identity": {"type": "object", "properties": {"platform": {"type": "string"}}},
        }},
        "error_schema": {"$ref": "#/$defs/Error", "$defs": {"Error": {
            "type": "object", "required": ["error"], "properties": {"error": {
                "type": "object", "required": ["code", "retry_hint"], "properties": {
                    "code": {"enum": ["invalid_input", "task_unavailable"]},
                    "retry_hint": {"enum": ["never", "after_delay", "reconcile_first"]},
                },
            }},
        }}},
    }


def tasks(*details):
    return [{"en": d, "zh": copy.deepcopy(d)} for d in details]


def navigation():
    return {"navigation": {"languages": [{"language": lang, "tabs": [{"tab": sync.COPY[lang]["tab"], "groups": [{"group": sync.COPY[lang]["overview"], "pages": ["existing-page"]}]}]} for lang in sync.LANGUAGES]}}


class SchemaTests(unittest.TestCase):
    def test_complete_contracts_preserve_constraints_and_relocate_refs(self):
        doc = sync.openapi(tasks(detail()), "en", "https://api.aisa.one")
        schema = doc["paths"]["/v1/tasks/creators.search"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        resource = Resource.from_contents({"$schema": "https://json-schema.org/draft/2020-12/schema", **doc})
        validator = Draft202012Validator({"$ref": "urn:test" + schema["$ref"]}, registry=Registry().with_resource("urn:test", resource))
        self.assertTrue(validator.is_valid({"input": {"platform": "tiktok", "countries": ["US"]}}))
        for value in ({"countries": ["US"]}, {"platform": "instagram", "countries": ["US"]}, {"platform": "tiktok", "countries": ["US", "GB", "US"]}, {"platform": "tiktok", "countries": ["XX"]}):
            self.assertFalse(validator.is_valid({"input": value}), value)
        def refs(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    sync.pointer(doc, value["$ref"])
                for child in value.values():
                    refs(child)
            elif isinstance(value, list):
                for child in value:
                    refs(child)
        refs(doc)
        self.assertIn("default", doc["paths"]["/v1/tasks/creators.search"]["post"]["responses"])
        self.assertNotIn("502", doc["paths"]["/v1/tasks/creators.search"]["post"]["responses"])

    def test_schema_scopes_do_not_collide_between_tasks_or_sections(self):
        one, two = detail(), detail("creators.find_similar")
        two["response_schema"]["$defs"]["Identity"]["properties"]["platform"]["const"] = "instagram"
        doc = sync.openapi(tasks(one, two), "en", "https://api.aisa.one")
        schemas = doc["components"]["schemas"]
        self.assertNotIn("const", schemas["creators.search_response"]["$defs"]["Identity"]["properties"]["platform"])
        self.assertEqual("instagram", schemas["creators.find_similar_response"]["$defs"]["Identity"]["properties"]["platform"]["const"])
        self.assertEqual("#/$defs/Request", one["request_schema"]["$ref"])

    def test_social_fallback_keeps_json_schema_and_does_not_invent_options(self):
        d = detail("social.search_profiles")
        del d["request_schema"]
        d["input"] = [{"name": "filter", "required": True, "type": "object", "json_schema": {"type": "object", "oneOf": [{"required": ["url"]}, {"required": ["handle"]}]}}]
        schema = sync.request_schema(d)
        self.assertEqual(d["input"][0]["json_schema"], schema["properties"]["input"]["properties"]["filter"])
        self.assertEqual(["filter"], schema["properties"]["input"]["required"])
        self.assertNotIn("options", schema["properties"])

    def test_broken_external_and_resource_scoped_refs_are_refused(self):
        for schema in ({"$ref": "#/$defs/Missing"}, {"$ref": "https://example.invalid/schema"}, {"$id": "urn:test", "type": "object"}):
            with self.subTest(schema=schema), self.assertRaises((ValueError, KeyError)):
                sync.component(schema, "Task")

    def test_recursive_local_refs_remain_finite(self):
        schema = {"type": "object", "properties": {"parent": {"$ref": "#"}}}
        self.assertEqual("#/components/schemas/Task", sync.component(schema, "Task")["properties"]["parent"]["$ref"])

    def test_legal_underscore_names_keep_distinct_components_and_pages(self):
        ids = ("foo_bar.baz", "foo.bar_baz")
        rows = tasks(*(detail(task_id) for task_id in ids))
        doc = sync.openapi(rows, "en", "https://api.aisa.one")
        self.assertEqual(6, len(doc["components"]["schemas"]))
        self.assertEqual(2, len({method["post"]["operationId"] for method in doc["paths"].values()}))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs.json").write_text(json.dumps(navigation()))
            sync.write(root, rows, "https://api.aisa.one")
            for name in ("foo_bar-baz", "foo-bar_baz"):
                self.assertTrue((root / ("tasks/" + name + ".mdx")).is_file())
            self.assertEqual(6, len(sync.validate_publication(root)))


class AcquisitionTests(unittest.TestCase):
    def test_empty_catalog_is_authoritative_but_malformed_is_not(self):
        with patch.object(sync, "get", return_value={"data": []}) as get:
            self.assertEqual([], sync.acquire("https://api.aisa.one"))
            self.assertEqual(2, get.call_count)
        for listing in ({}, {"data": None}, {"data": [{}]}, {"data": [{"task_id": "../bad"}]}):
            with self.subTest(listing=listing), self.assertRaises(ValueError):
                sync.catalog_ids(listing)

    def test_disabled_tasks_are_not_read_and_only_get_is_used(self):
        d = detail()
        listing = {"data": [{"task_id": d["task_id"]}]}
        with patch.object(sync, "get", side_effect=[listing, d, copy.deepcopy(d), listing]) as get:
            self.assertEqual(1, len(sync.acquire("https://api.aisa.one")))
            self.assertEqual(["/v1/tasks", "/v1/tasks/creators.search?lang=en", "/v1/tasks/creators.search?lang=zh", "/v1/tasks"], [call.args[1] for call in get.call_args_list])

    def test_missing_public_schema_refuses_before_writing(self):
        d = detail()
        del d["response_schema"]
        with patch.object(sync, "get", side_effect=[{"data": [{"task_id": d["task_id"]}]}, d]), self.assertRaisesRegex(ValueError, "missing response_schema"):
            sync.acquire("https://api.aisa.one")

    def test_catalog_change_refuses_partial_publication(self):
        d = detail()
        with patch.object(sync, "get", side_effect=[{"data": [{"task_id": d["task_id"]}]}, d, d, {"data": []}]), self.assertRaisesRegex(ValueError, "availability changed"):
            sync.acquire("https://api.aisa.one")


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "docs.json").write_text(json.dumps(navigation()))

    def test_bilingual_pages_use_selected_origin_and_no_private_metadata(self):
        for api in ("https://api.aisa.one", "https://dev-api.aisa.one"):
            sync.write(self.root, tasks(detail()), api)
            for language in sync.LANGUAGES:
                page = (self.root / sync.page_path(language, "creators-search.mdx")).read_text()
                self.assertIn(api, page)
                self.assertNotIn("meta.raw", page)
                doc = json.loads((self.root / sync.page_path(language, "openapi.json")).read_text())
                self.assertEqual([{"url": api}], doc["servers"])
            docs = json.loads((self.root / "docs.json").read_text())
            self.assertEqual("existing-page", docs["navigation"]["languages"][0]["tabs"][0]["groups"][0]["pages"][0])

    def test_empty_catalog_withdraws_both_languages_and_navigation(self):
        sync.write(self.root, tasks(detail()), "https://api.aisa.one")
        sync.write(self.root, [], "https://api.aisa.one")
        for language in sync.LANGUAGES:
            self.assertFalse((self.root / sync.page_path(language, "")).exists())
        self.assertEqual(navigation(), json.loads((self.root / "docs.json").read_text()))

    def test_validation_failure_keeps_complete_previous_publication(self):
        sync.write(self.root, tasks(detail()), "https://api.aisa.one")
        before = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        bad = tasks(detail())
        bad[0]["zh"]["response_schema"] = {"$ref": "#/$defs/broken"}
        with self.assertRaises(KeyError):
            sync.write(self.root, bad, "https://api.aisa.one")
        self.assertEqual(before, {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_repeated_generation_is_deterministic_and_removes_old_task(self):
        sync.write(self.root, tasks(detail(), detail("creators.find_similar")), "https://api.aisa.one")
        sync.write(self.root, tasks(detail()), "https://api.aisa.one")
        self.assertFalse((self.root / "tasks/creators-find_similar.mdx").exists())
        before = (self.root / "docs.json").read_bytes()
        sync.write(self.root, tasks(detail()), "https://api.aisa.one")
        self.assertEqual(before, (self.root / "docs.json").read_bytes())


class DynamicTests(unittest.TestCase):
    def test_new_domain_and_every_contract_change_are_dynamic(self):
        original = tasks(detail())
        variants = []
        for field, value in (("description", "New description"), ("pricing", {"revision": 2, "tiers_micros_usd": {"default": 120000}}), ("input", [{"name": "new_field", "type": "string"}]), ("request_schema", {"type": "object"}), ("error_schema", {"type": "object"})):
            changed = copy.deepcopy(original)
            changed[0]["en"][field] = value
            variants.append(changed)
        for changed in variants:
            self.assertNotEqual(sync.catalog_hash(original), sync.catalog_hash(changed))
        added = detail("research.find_sources")
        doc = sync.openapi(tasks(detail(), added), "en", "https://api.aisa.one")
        self.assertEqual({"/v1/tasks/creators.search", "/v1/tasks/research.find_sources"}, set(doc["paths"]))
        priced = copy.deepcopy(original)
        priced[0]["en"]["pricing"] = {"revision": 2, "tiers_micros_usd": {"default": 120000}}
        priced_doc = sync.openapi(priced, "en", "https://api.aisa.one")
        self.assertEqual(priced[0]["en"]["pricing"], priced_doc["paths"]["/v1/tasks/creators.search"]["post"]["x-aisa-task"]["pricing"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs.json").write_text(json.dumps(navigation()))
            sync.write(root, tasks(added), "https://api.aisa.one")
            self.assertTrue((root / "tasks/research-find_sources.mdx").is_file())
            self.assertIn("Research", (root / "docs.json").read_text())


if __name__ == "__main__":
    unittest.main()
