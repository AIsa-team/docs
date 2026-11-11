"""Replay the supported Duffel GET and keep incomplete POST variants pending."""
import copy
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

from openapi_spec_validator import validate

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import compose, has_response_payload
from import_duffel_reference import NextData, envelope
from runtime_registry import public_mirror_index

ROOT = Path(__file__).resolve().parents[2]
GET_PATH = "/apis/v1/duffel/flights/offer-requests/{id}"
POST_PATH = "/apis/v1/duffel/flights/offer-requests/create"
GET_SOURCE = "response-duffel-flights-get-offer-request-20261110.json"
POST_SOURCE = "response-duffel-flights-post-create-20261110.json"


class DuffelResponseBindingTest(unittest.TestCase):
    def source(self):
        return json.loads((ROOT / "openapi/upstream" / GET_SOURCE).read_text())

    def test_get_source_uses_the_declared_success_range_and_exact_binding(self):
        source = self.source()
        metadata = source["info"]["x-aisa-source"]
        self.assertEqual(metadata["kind"], "manual")
        self.assertEqual(metadata["path_space"], "public")
        self.assertIs(metadata["response_only"], True)
        self.assertRegex(metadata["upstream_path_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(metadata["upstream_origin_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(list(source["paths"]), [GET_PATH])
        operation = source["paths"][GET_PATH]["get"]
        self.assertNotIn("requestBody", operation)
        self.assertEqual(set(operation["responses"]), {"2XX"})
        response = operation["responses"]["2XX"]
        self.assertIn("view=offers", response["description"])
        self.assertIn("view=itineraries", response["description"])
        schema = response["content"]["application/json"]["schema"]
        self.assertEqual(schema["type"], "object")
        self.assertEqual(schema["required"], ["data"])

    def test_both_languages_keep_post_variants_and_pending_response(self):
        self.assertFalse((ROOT / "openapi/upstream" / POST_SOURCE).exists())
        for filename in ("openapi/duffel-flights.json", "openapi/zh/duffel-flights.json"):
            with self.subTest(filename=filename):
                document = json.loads((ROOT / filename).read_text())
                validate(document)
                get = document["paths"][GET_PATH]["get"]
                self.assertIn("2XX", get["responses"])
                self.assertNotIn("200", get["responses"])
                post = document["paths"][POST_PATH]["post"]
                view = next(p for p in post["parameters"] if p["name"] == "view")
                self.assertEqual(view["schema"]["enum"], ["offers", "itineraries"])
                self.assertEqual(view["schema"]["default"], "offers")
                self.assertFalse(has_response_payload(post["responses"]["200"]))
                self.assertNotIn("x-aisa-response-source", post)
                self.assertTrue(post.get("x-aisa-response-pending") or
                                post.get("x-aisa-review", {}).get("response") == "generic")

    def test_composer_closes_only_the_get_response_gap(self):
        mirrors = public_mirror_index(ROOT)
        original = json.loads((ROOT / "openapi/duffel-flights.json").read_text())
        upstream = json.loads((ROOT / "openapi/upstream/duffel-flights-official.json").read_text())
        for path, method in ((GET_PATH, "get"), (POST_PATH, "post")):
            with self.subTest(path=path):
                facts = copy.deepcopy(original)
                operation = facts["paths"][path][method]
                operation["responses"] = {"200": {"description": "Successful response"}}
                for key in ("x-aisa-response-source", "x-aisa-response-pending", "x-aisa-review"):
                    operation.pop(key, None)
                facts["paths"] = {path: {method: operation}}
                document, pending = compose(facts, upstream, public_mirrors=mirrors)
                self.assertEqual(pending, [])
                actual = document["paths"][path][method]
                if method == "get":
                    self.assertNotIn("200", actual["responses"])
                    self.assertIn("2XX", actual["responses"])
                    self.assertNotIn("x-aisa-response-pending", actual)
                    self.assertEqual(actual["x-aisa-response-source"]["source"]["content_hash"],
                                     self.source()["info"]["x-aisa-source"]["content_hash"])
                else:
                    self.assertNotIn("x-aisa-response-source", actual)
                    self.assertEqual(actual["x-aisa-response-pending"]["statuses"], ["200"])
                    self.assertEqual(actual["parameters"], operation["parameters"])

    def test_get_envelope_matches_official_model_and_pinned_sdk(self):
        fixture = ROOT / "scripts/tests/fixtures/duffel-flights-reference-20261009.tar.gz"
        with tempfile.TemporaryDirectory() as directory:
            with tarfile.open(fixture) as archive:
                archive.extractall(directory, filter="data")
            raw = (Path(directory) / "offer-requests.html").read_bytes()
            model = json.loads("".join(NextData(raw).parts))["props"]["pageProps"]["resource"]["model"]
            response = self.source()["paths"][GET_PATH]["get"]["responses"]["2XX"]
            self.assertEqual(response["content"]["application/json"]["schema"], envelope(model))
            client = (Path(directory) / "src__Client.ts").read_text()
            self.assertIn("!response.ok", client)


if __name__ == "__main__":
    unittest.main()
