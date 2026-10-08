import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import digest
from import_brave_reference import INDEX_URL, ORIGIN, convert_specs, decode_api_spec, import_reference, load_reference
from import_upstream import import_source


def payload(spec):
    pool = []
    def encode(value):
        index = len(pool)
        pool.append(None)
        pool[index] = ({key: encode(child) for key, child in value.items()} if isinstance(value, dict)
                       else [encode(child) for child in value] if isinstance(value, list) else value)
        return index
    encode({"apiSpec": spec})
    return {"nodes": [{"data": [{"ignored_session_field": 1}, "must not be decoded"]}, {"data": pool}]}


def spec(method="GET"):
    return {"method": method, "path": "/v1/search", "operationId": "search_" + method.lower(),
            "serverUrl": "https://api.search.brave.com/res", "tagDisplayName": "Search", "summary": "",
            "authParams": [{"name": "x-subscription-token", "in": "header"}], "headerParams": [], "pathParams": [],
            "queryParams": [{"name": "q", "in": "query", "required": True, "schema": {"type": "string", "minLength": 1}, "examples": ["hello"]}],
            "requestBody": None, "responses": [{"statusCode": "200", "description": "Success", "schema": {"$ref": "#/components/schemas/Result"}}],
            "schemas": {"Result": {"type": "object", "properties": {"value": {"type": "string"}}}},
            "codeSamples": [], "methodVariants": [{"href": "/api-reference/search/get"}, {"href": "/api-reference/search/post"}]}


class BraveReferenceTests(unittest.TestCase):
    def test_decodes_only_plain_schema_data_and_omits_undefined(self):
        original = spec()
        encoded = payload(original)
        self.assertEqual(decode_api_spec(encoded), original)
        encoded["nodes"][1]["data"][1]["optional"] = -1
        self.assertNotIn("optional", decode_api_spec(encoded))
        for value in (["Set", 0], {"cycle": 1}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                decode_api_spec({"nodes": [{"data": [{"apiSpec": 1}, value]}]})

    def test_discovery_follows_variants_and_hashes_only_structured_sources(self):
        get, post = spec(), spec("POST")
        post["queryParams"] = []
        post["requestBody"] = {"required": True, "schema": {"type": "object", "required": ["q"], "properties": {"q": {"type": "string"}}}}
        post["codeSamples"] = [{"source": "Content-Type: application/json"}]
        sources = {INDEX_URL: f"[Search]({ORIGIN}/api-reference/search/get/index.html.md)".encode(),
                   ORIGIN + "/api-reference/search/get/__data.json": json.dumps(payload(get)).encode(),
                   ORIGIN + "/api-reference/search/post/__data.json": json.dumps(payload(post)).encode()}
        document, source = import_reference(sources.__getitem__)
        self.assertEqual(set(document["paths"]["/v1/search"]), {"get", "post"})
        operation = document["paths"]["/v1/search"]["get"]
        self.assertEqual(operation["parameters"][0]["schema"]["minLength"], 1)
        self.assertEqual(operation["parameters"][0]["examples"], {"0": {"value": "hello"}})
        self.assertEqual(document["paths"]["/v1/search"]["post"]["requestBody"]["content"]["application/json"]["schema"], post["requestBody"]["schema"])
        self.assertEqual(len(source["source_pages"]), 2)
        self.assertNotIn("ignored_session_field", json.dumps(document) + json.dumps(source))

    def test_conflicts_and_discovery_outside_official_site_fail_closed(self):
        a, b = spec(), spec("POST")
        b["schemas"]["Result"]["type"] = "string"
        with self.assertRaisesRegex(ValueError, "component"):
            convert_specs({"a": a, "b": b})
        a["methodVariants"] = [{"href": "https://untrusted.example/api-reference/other"}]
        with self.assertRaisesRegex(ValueError, "official API reference"):
            import_reference(lambda url: f"[Search]({ORIGIN}/api-reference/search/get/index.html.md)".encode() if url == INDEX_URL else json.dumps(payload(a)).encode())

    def test_importer_dispatch_retains_refresh_provenance(self):
        document = convert_specs({"official": spec()})
        with patch("import_upstream.import_reference", return_value=(copy.deepcopy(document), {"converter": "reference@1", "source_pages": []})):
            imported = import_source("brave-official", INDEX_URL)
        source = imported["info"].pop("x-aisa-source")
        self.assertEqual(source["url"], INDEX_URL)
        self.assertEqual(source["content_hash"], digest(imported))
        self.assertEqual(source["converter"], "reference@1")

    def test_type_changed_literals_cannot_hide_source_conflicts(self):
        for field in ("default", "enum", "examples", "const"):
            with self.subTest(field=field):
                a, b = spec(), spec("POST")
                a["schemas"]["Result"][field] = [True] if field in ("enum", "examples") else True
                b["schemas"]["Result"][field] = [1] if field in ("enum", "examples") else 1
                with self.assertRaisesRegex(ValueError, "component"):
                    convert_specs({"a": a, "b": b})
        a, b = spec(), spec()
        a["queryParams"][0]["schema"]["default"] = True
        b["queryParams"][0]["schema"]["default"] = 1
        with self.assertRaisesRegex(ValueError, "operation"):
            convert_specs({"a": a, "b": b})

    def test_reference_json_rejects_duplicate_and_non_json_numbers(self):
        for raw in (b'{"nodes":[],"nodes":[]}', b'{"nodes":[NaN]}', b'{"nodes":[Infinity]}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                load_reference(raw)
        malformed = payload(spec())
        malformed["nodes"][1]["data"].append(float("nan"))
        malformed["nodes"][1]["data"][1]["unexpected"] = len(malformed["nodes"][1]["data"]) - 1
        with self.assertRaises(ValueError):
            decode_api_spec(malformed)


if __name__ == "__main__":
    unittest.main()
