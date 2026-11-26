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
import test_fetch_runtime_release as release_tests
from test_fetch_runtime_release import encoded
from fetch_runtime_release import sha, save
from task_pricing import pricing_markdown, usd


def detail(task_id="creators.search"):
    return {
        "task_id": task_id, "domain": task_id.split(".")[0], "method": "POST",
        "path": "/v1/tasks/" + task_id, "name": "Find creators", "description": "Test contract",
        "version": 1, "strategy": "merge", "billing": {"mode": "per_unit"},
        "pricing": {"kind": "per_unit", "revision": 2, "currency": "USD", "unit": "delivered_item",
                    "tiers_micros_usd": {"normal": 120000, "vip": 120000, "svip": 120000},
                    "apply_plan_multiplier": False, "plan_policy": {"version": "test", "team_ppm": 1000000, "builder_ppm": 1000000, "payg_ppm": 1000000},
                    "units": {"estimate_input": "limit", "unit_size": 1, "maximum_units": 100, "settlement": "delivered_units"}},
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
        self.assertNotIn("const", next(v for k, v in schemas.items() if k.startswith("creators.search_response.") and k.endswith("_Identity"))["properties"]["platform"])
        self.assertEqual("instagram", next(v for k, v in schemas.items() if k.startswith("creators.find_similar_response.") and k.endswith("_Identity"))["properties"]["platform"]["const"])
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
        self.assertEqual("#/components/schemas/Task", sync.component(schema, "Task")["Task"]["properties"]["parent"]["$ref"])

    def test_lifted_definitions_have_direct_component_refs_and_keep_recursion(self):
        schema = {"$ref": "#/$defs/Node", "$defs": {"Node": {
            "type": "object", "properties": {"child": {"$ref": "#/$defs/Node"}},
        }}}
        components = sync.component(schema, "creators.tree_response")
        self.assertEqual(2, len(components))
        root_ref = components["creators.tree_response"]["$ref"]
        node = components[root_ref.removeprefix("#/components/schemas/")]
        self.assertEqual(root_ref, node["properties"]["child"]["$ref"])
        self.assertNotIn("$defs", components["creators.tree_response"])

    def test_default_error_resolves_to_fields_and_annotations_are_not_schemas(self):
        d = detail()
        d["request_schema"]["$defs"]["Input"]["properties"]["definitions"] = {"type": "string"}
        d["request_schema"]["examples"] = [{"$ref": "literal-business-value", "$defs": "keep"}]
        doc = sync.openapi(tasks(d, detail("social.get_post")), "en", "https://dev-api.aisa.one")
        for task_id in ("creators.search", "social.get_post"):
            schema = doc["paths"]["/v1/tasks/" + task_id]["post"]["responses"]["default"]["content"]["application/json"]["schema"]
            while "$ref" in schema:
                self.assertEqual(4, len(schema["$ref"].split("/")))
                schema = sync.pointer(doc, schema["$ref"])
            self.assertIn("error", schema["properties"])
        root = doc["components"]["schemas"]["creators.search_request"]
        self.assertEqual(d["request_schema"]["examples"], root["examples"])
        fields = next(v["properties"] for k, v in doc["components"]["schemas"].items()
                      if k.startswith("creators.search_request.") and k.endswith("_Input"))
        self.assertEqual({"type": "string"}, fields["definitions"])

    def test_legal_underscore_names_keep_distinct_components_and_pages(self):
        ids = ("foo_bar.baz", "foo.bar_baz")
        rows = tasks(*(detail(task_id) for task_id in ids))
        doc = sync.openapi(rows, "en", "https://api.aisa.one")
        self.assertEqual(6, sum(k.count(".") == 1 for k in doc["components"]["schemas"]))
        self.assertEqual(2, len({method["post"]["operationId"] for method in doc["paths"].values()}))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs.json").write_text(json.dumps(navigation()))
            sync.write(root, rows, "https://api.aisa.one")
            for name in ("foo_bar-baz", "foo-bar_baz"):
                self.assertTrue((root / ("tasks/" + name + ".mdx")).is_file())
            self.assertEqual(6, len(sync.validate_publication(root)))


def release_fixture(catalog, *, missing=False):
    _, compiler, _, current, payload, _ = release_tests.PublicReleaseTests().fixture()
    if not missing:
        payload[sync.TASK_CATALOG] = encoded(catalog)
    current["files"] = [{"name": name, "media_type": "application/json", "sha256": sha(raw)}
                        for name, raw in sorted(payload.items())]
    manifest = {key: current[key] for key in ("schema_version", "source_digest", "compiler_revision", "files")}
    revision = sha(encoded(manifest))
    current["artifact_revision"] = revision
    calls = []
    def reader(path):
        calls.append(path)
        if path == "/public/api-contract/current":
            return encoded(current), {}
        if path == "/info/apis/category":
            return b'{"apis":[]}', {}
        prefix = "/public/api-contract/releases/" + revision + "/"
        if not path.startswith(prefix):
            raise AssertionError("Unexpected live Task read: " + path)
        raw = payload[path.removeprefix(prefix)]
        return raw, {"etag": '"' + sha(raw) + '"'}
    return current, payload, calls, reader


class AcquisitionTests(unittest.TestCase):
    def test_same_release_task_artifact_preserves_raw_counts_and_never_reads_live_tasks(self):
        current, _, calls, reader = release_fixture({"schema_version": 1, "tasks": tasks(detail())})
        rows, receipt = sync.acquire("https://dev-api.aisa.one", reader)
        self.assertEqual(rows, tasks(detail()))
        self.assertEqual(receipt["artifact_revision"], current["artifact_revision"])
        self.assertEqual(receipt["selected_endpoint_count"], 1)
        self.assertEqual(receipt["provider_count"], 1)
        self.assertFalse(any(path.startswith("/v1/tasks") for path in calls))
        self.assertEqual(calls.count("/public/api-contract/current"), 3)

    def test_valid_empty_withdraws_but_missing_or_malformed_artifact_does_not(self):
        _, _, _, reader = release_fixture({"schema_version": 1, "tasks": []})
        self.assertEqual(sync.acquire("https://dev-api.aisa.one", reader)[0], [])
        for catalog, missing in (({}, True), ({}, False), ({"schema_version": 1, "tasks": None}, False),
                                 ({"schema_version": True, "tasks": []}, False)):
            _, _, _, reader = release_fixture(catalog, missing=missing)
            with self.subTest(catalog=catalog, missing=missing), self.assertRaises(ValueError):
                sync.acquire("https://dev-api.aisa.one", reader)

    def test_incomplete_language_schema_or_mixed_prices_refuse_publication(self):
        for mutation in (lambda rows: rows[0].pop("zh"),
                         lambda rows: rows[0]["en"].pop("response_schema"),
                         lambda rows: rows[0]["zh"]["pricing"].update(revision=3)):
            rows = tasks(detail())
            mutation(rows)
            _, _, _, reader = release_fixture({"schema_version": 1, "tasks": rows})
            with self.assertRaises(ValueError):
                sync.acquire("https://api.aisa.one", reader)

    def test_bad_hash_stale_or_changed_revision_fails(self):
        for mutation in ("hash", "stale", "changed"):
            current, payload, calls, original = release_fixture({"schema_version": 1, "tasks": tasks(detail())})
            def reader(path):
                if mutation == "changed" and path == "/public/api-contract/current" and calls.count(path) == 2:
                    current["generation"] += 1
                raw, headers = original(path)
                if mutation == "hash" and path.endswith(sync.TASK_CATALOG):
                    raw += b" "
                return raw, headers
            if mutation == "stale":
                current["fresh"] = False
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                sync.acquire("https://api.aisa.one", reader)

    def test_existing_acquisition_reuses_the_formal_release_and_rejects_tampering(self):
        current, _, _, reader = release_fixture({"schema_version": 1, "tasks": tasks(detail())})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "facts"
            save(path, sync.acquire_release(current["artifact_revision"], current["compiler_revision"], reader))
            rows, receipt = sync.acquired_tasks(path)
            self.assertEqual(rows, tasks(detail()))
            self.assertEqual(receipt["artifact_revision"], current["artifact_revision"])
            (path / sync.TASK_CATALOG).write_bytes(b'{"schema_version":1,"tasks":[]}')
            with self.assertRaises(ValueError):
                sync.acquired_tasks(path)

    def test_unmanifested_task_file_cannot_be_attached_to_a_historical_release(self):
        current, _, _, reader = release_fixture({}, missing=True)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "facts"
            save(path, sync.acquire_release(current["artifact_revision"], current["compiler_revision"], reader))
            (path / "tasks").mkdir()
            (path / sync.TASK_CATALOG).write_bytes(encoded({"schema_version": 1, "tasks": tasks(detail())}))
            with self.assertRaisesRegex(ValueError, "no manifested Task catalog"):
                sync.acquired_tasks(path)
            root = Path(folder) / "site"
            root.mkdir()
            (root / "docs.json").write_text(json.dumps(navigation()))
            receipt = json.loads((path / "acquisition-receipt.json").read_text())
            sync.write(root, tasks(detail()), "https://api.aisa.one", receipt)
            with self.assertRaisesRegex(ValueError, "no manifested Task catalog"):
                sync.validate_release_publication(root, path, receipt)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "docs.json").write_text(json.dumps(navigation()))

    def test_bilingual_pages_omit_redundant_copy_and_keep_contract_metadata(self):
        d = detail("creators.find_contact")
        d["strategy"] = "waterfall"
        for api in ("https://api.aisa.one", "https://dev-api.aisa.one"):
            sync.write(self.root, tasks(d), api)
            for language in sync.LANGUAGES:
                page = (self.root / sync.page_path(language, "creators-find_contact.mdx")).read_text()
                body = page.split("---\n", 2)[2]
                overview = (self.root / sync.page_path(language, "overview.mdx")).read_text()
                for redundant in (d["task_id"], "· v1", api, "API origin", "API 地址", "Default strategy", "默认策略", "waterfall"):
                    self.assertNotIn(redundant, body)
                for redundant in (api, "API origin", "API 地址"):
                    self.assertNotIn(redundant, overview)
                self.assertIn(f'[`{d["task_id"]}`](/{sync.page_path(language, "creators-find_contact")})', overview)
                self.assertIn(sync.COPY[language]["contract"], body)
                self.assertIn(pricing_markdown(d, language), body)
                self.assertIn(f'POST {d["path"]}', page)
                self.assertNotIn("meta.raw", page)
                doc = json.loads((self.root / sync.page_path(language, "openapi.json")).read_text())
                self.assertEqual([{"url": api}], doc["servers"])
                self.assertEqual({key: d[key] for key in ("version", "strategy", "billing", "pricing")},
                                 doc["paths"][d["path"]]["post"]["x-aisa-task"])
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

    def test_formal_task_output_is_bound_to_exact_release_including_empty_catalog(self):
        for rows in (tasks(detail()), []):
            current, payload, _, reader = release_fixture({"schema_version": 1, "tasks": rows})
            actual, receipt = sync.acquire("https://api.aisa.one", reader)
            sync.write(self.root, actual, "https://api.aisa.one", receipt)
            with tempfile.TemporaryDirectory() as folder:
                facts = Path(folder)
                (facts / "tasks").mkdir()
                (facts / sync.TASK_CATALOG).write_bytes(payload[sync.TASK_CATALOG])
                sync.validate_release_publication(self.root, facts, receipt)
                from publication_surface import publication_hashes
                hashes = publication_hashes(self.root)
                self.assertIn("docs/task-runtime.json", hashes)
                self.assertEqual(bool(rows), "tasks/openapi.json" in hashes)
                changed = {**receipt, "artifact_revision": "d" * 64}
                with self.assertRaisesRegex(ValueError, "differs from"):
                    sync.validate_release_publication(self.root, facts, changed)
                if not rows:
                    sync.write(self.root, tasks(detail()), "https://api.aisa.one", receipt)
                    with self.assertRaisesRegex(ValueError, "membership differs"):
                        sync.validate_release_publication(self.root, facts, receipt)

    def test_missing_price_rules_preserve_saved_pages_and_navigation(self):
        sync.write(self.root, tasks(detail()), "https://api.aisa.one")
        before = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        bad = tasks(detail())
        bad[0]["zh"]["pricing"].pop("units")
        with self.assertRaisesRegex(ValueError, "unit accounting"):
            sync.write(self.root, bad, "https://api.aisa.one")
        self.assertEqual(before, {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})


class PricingTests(unittest.TestCase):
    def test_equal_tiers_show_one_customer_price_without_internal_labels(self):
        d = detail()
        for apply in (False, True):
            d["pricing"]["apply_plan_multiplier"] = apply
            for language, header in (("en", "Price (USD)"), ("zh", "价格 (USD)")):
                page = pricing_markdown(d, language)
                self.assertIn(header, page)
                self.assertEqual(1, page.count("0.12"))
                for hidden in ("normal (USD)", "vip (USD)", "svip (USD)", "revision", "价格版本", "team", "builder", "payg", "倍率", "multiplier"):
                    self.assertNotIn(hidden, page)

    def test_fixed_success_and_delivery_prices_have_amounts_units_and_quote_semantics(self):
        d = detail()
        for language, expected in (("en", "Per delivered item"), ("zh", "每条实际交付结果")):
            page = sync.task_page(d, language)
            self.assertIn("0.12", page)
            self.assertIn(expected, page)
        self.assertIn("quoting neither executes the Task nor reserves funds", sync.task_page(d, "en"))
        d["billing"] = {"mode": "fixed"}
        d["pricing"].update(kind="fixed_success", unit="successful_request", tiers_micros_usd={"normal": 10000000})
        d["pricing"].pop("units")
        self.assertIn("Per successful request | 10 |", pricing_markdown(d, "en"))
        self.assertEqual("0.000001", usd(1))
        self.assertEqual("0", usd(0))
        self.assertIn("正常查空不收费", pricing_markdown(d, "zh"))

    def test_parameter_table_never_presents_representative_base_as_every_input_price(self):
        d = detail("research.discover")
        d["pricing"]["tiers_micros_usd"] = {"normal": 999999}
        d["pricing"]["price_by"] = {"input": "platform", "values": {
            "alpha": {"normal": 1000}, "beta": {"normal": 120000}}}
        d["input"][0]["selector"] = "input.platform"
        page = pricing_markdown(d, "en")
        self.assertIn("input.platform = alpha | Per delivered item | 0.001", page)
        self.assertIn("input.platform = beta | Per delivered item | 0.12", page)
        self.assertNotIn("0.999999", page)
        d["pricing"]["price_by"]["unknown_uses_default_tiers"] = True
        self.assertIn("Other or omitted value | Per delivered item | 0.999999", pricing_markdown(d, "en"))

    def test_request_size_blocks_are_successful_request_prices_not_delivered_item_prices(self):
        d = detail("research.rankings")
        d["billing"] = {"mode": "fixed"}
        d["pricing"].update(kind="fixed_success", unit="successful_request", price_by={
            "input": "board", "values": {"monthly": {"normal": 98590}, "weekly": {"normal": 73400}},
            "request_scale": {"input": "limit", "values": ["monthly"], "unit_size": 10,
                              "max_quantity": 100, "round_up_micros_usd": 100}})
        d["pricing"].pop("units")
        page = pricing_markdown(d, "en")
        self.assertIn("board = monthly | Per 10 requested units | 0.09859", page)
        self.assertIn("board = weekly | Per successful request | 0.0734", page)
        self.assertIn("ceil(limit / 10)", page)
        self.assertIn("multiple of USD 0.0001", page)
        self.assertIn("successful partial result still charges the requested size", page)
        self.assertNotIn("Per delivered item", page)

    def test_requested_units_remain_explicit_without_unit_plan_multipliers(self):
        d = detail()
        d["pricing"].update(unit="requested_unit", apply_plan_multiplier=True)
        d["pricing"]["units"].update(estimate_input="characters", unit_size=1000, settlement="requested_units")
        page = pricing_markdown(d, "en")
        self.assertIn("ceil(characters / 1000)", page)
        self.assertIn("settles the requested units", page)
        self.assertNotIn("team", page)

    def test_unrepresented_price_differences_preserve_saved_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs.json").write_text(json.dumps(navigation()))
            sync.write(root, tasks(detail()), "https://api.aisa.one")
            saved = lambda: {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            before = saved()
            for difference in ("base", "parameter", "multiplier"):
                bad = tasks(detail())
                p = bad[0]["zh"]["pricing"]
                if difference == "base":
                    p["tiers_micros_usd"]["vip"] = 100000
                elif difference == "parameter":
                    p["price_by"] = {"input": "platform", "values": {"alpha": {"normal": 1000, "vip": 2000}}}
                else:
                    p["apply_plan_multiplier"] = True
                    p["plan_policy"]["team_ppm"] = 800000
                with self.assertRaisesRegex(ValueError, "explicit customer price presentation"):
                    sync.write(root, bad, "https://api.aisa.one")
                self.assertEqual(before, saved())

    def test_unsupported_missing_or_inconsistent_rules_are_refused(self):
        for mutation in (lambda p: p.pop("currency"), lambda p: p.pop("plan_policy"),
                         lambda p: p.update(kind="provider_cost_multiplier"),
                         lambda p: p["tiers_micros_usd"].update(normal=True),
                         lambda p: p["units"].update(unit_size=0),
                         lambda p: p["units"].update(settlement="requested_units")):
            d = detail()
            mutation(d["pricing"])
            with self.assertRaises(ValueError):
                pricing_markdown(d, "en")


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

    def test_people_domain_label_and_runtime_override(self):
        people_tasks = tasks(detail("people.enrich"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs.json").write_text(json.dumps(navigation()))
            sync.write(root, people_tasks, "https://api.aisa.one")
            docs = json.loads((root / "docs.json").read_text())
            by_lang = {e["language"]: e["tabs"][0]["groups"][1]["pages"][1]["group"] for e in docs["navigation"]["languages"]}
            self.assertEqual({"en": "People", "zh": "人物与联系"}, by_lang)

            overridden = copy.deepcopy(people_tasks)
            overridden[0]["en"]["domain_label"] = "People & Contacts"
            overridden[0]["zh"]["domain_label"] = "人与联系方式"
            sync.write(root, overridden, "https://api.aisa.one")
            docs = json.loads((root / "docs.json").read_text())
            by_lang = {e["language"]: e["tabs"][0]["groups"][1]["pages"][1]["group"] for e in docs["navigation"]["languages"]}
            self.assertEqual({"en": "People & Contacts", "zh": "人与联系方式"}, by_lang)

    def test_three_segment_platform_tasks_nest_by_domain_platform_and_keep_two_segment_flat(self):
        commerce_ids = (
            "commerce.alibaba-1688.get_product",
            "commerce.alibaba-1688.search_products",
            "commerce.amazon.get_product",
            "commerce.tiktok-shop.list_reviews",
        )
        other_ids = ("company.browse_funding_rounds", "creators.search")
        all_ids = sorted((*commerce_ids, *other_ids))
        self.assertEqual(all_ids, sync.catalog_ids({"data": [{"task_id": i} for i in reversed(all_ids)]}))
        for bad in ("commerce..get_product", "commerce.-bad.get_product", "commerce.bad-.get_product", "commerce.a.b.c", "single"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                sync.catalog_ids({"data": [{"task_id": bad}]})

        rows = tasks(*(detail(i) for i in all_ids))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs.json").write_text(json.dumps(navigation()))
            sync.write(root, rows, "https://dev-api.aisa.one")
            pages = sync.validate_publication(root, api="https://dev-api.aisa.one")
            self.assertEqual(2 * (len(all_ids) + 1), len(pages))

            docs = json.loads((root / "docs.json").read_text())
            by_lang = {e["language"]: e["tabs"][0]["groups"][1]["pages"] for e in docs["navigation"]["languages"]}
            self.assertEqual(
                [
                    "tasks/overview",
                    {
                        "group": "Commerce",
                        "pages": [
                            {"group": "1688", "pages": ["tasks/commerce-alibaba-1688-get_product", "tasks/commerce-alibaba-1688-search_products"]},
                            {"group": "Amazon", "pages": ["tasks/commerce-amazon-get_product"]},
                            {"group": "TikTok Shop", "pages": ["tasks/commerce-tiktok-shop-list_reviews"]},
                        ],
                    },
                    {"group": "Company", "pages": ["tasks/company-browse_funding_rounds"]},
                    {"group": "Creators", "pages": ["tasks/creators-search"]},
                ],
                by_lang["en"],
            )
            self.assertEqual(
                [
                    "zh/tasks/overview",
                    {
                        "group": "电商",
                        "pages": [
                            {"group": "1688", "pages": ["zh/tasks/commerce-alibaba-1688-get_product", "zh/tasks/commerce-alibaba-1688-search_products"]},
                            {"group": "Amazon", "pages": ["zh/tasks/commerce-amazon-get_product"]},
                            {"group": "TikTok Shop", "pages": ["zh/tasks/commerce-tiktok-shop-list_reviews"]},
                        ],
                    },
                    {"group": "Company", "pages": ["zh/tasks/company-browse_funding_rounds"]},
                    {"group": "达人", "pages": ["zh/tasks/creators-search"]},
                ],
                by_lang["zh"],
            )

    def test_numeric_price_by_keys_sort_numerically(self):
        d = detail("commerce.amazon.list_reviews")
        d["billing"] = {"mode": "fixed"}
        d["pricing"].update(
            kind="fixed_success",
            unit="successful_request",
            price_by={
                "input": "requested_review_pages",
                "values": {
                    "0": {"normal": 0},
                    "1": {"normal": 44000},
                    "2": {"normal": 84000},
                    "10": {"normal": 420000},
                },
            },
        )
        d["pricing"].pop("units")
        page = pricing_markdown(d, "en")
        positions = [page.index(f"requested_review_pages = {k} |") for k in ("0", "1", "2", "10")]
        self.assertEqual(sorted(positions), positions)


if __name__ == "__main__":
    unittest.main()
