"""Focused response-source replay for the Duffel routes previously showing empty schemas."""
import copy
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

from openapi_spec_validator import validate

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import compose
from import_duffel_reference import NextData
from runtime_registry import public_mirror_index

ROOT = Path(__file__).resolve().parents[2]
CASES = {
    "duffel-flights": [
        ("/apis/v1/duffel/flights/offer-requests/create", "post", "response-duffel-flights-post-create-20261110.json"),
        ("/apis/v1/duffel/flights/offer-requests/{id}", "get", "response-duffel-flights-get-offer-request-20261110.json"),
    ],
    "duffel-stays": [
        ("/apis/v1/duffel/stays/search-results/{id}", "get", "response-duffel-stays-get-search-result-20261110.json"),
        ("/apis/v1/duffel/stays/search-results/{id}/rates", "get", "response-duffel-stays-get-search-rates-20261110.json"),
    ],
}
PLACEHOLDER = "Successful response. The payload schema has not been reviewed yet."


class DuffelResponseBindingTest(unittest.TestCase):
    def test_response_sources_are_public_response_only_and_typed(self):
        mirrors = public_mirror_index(ROOT)
        for provider, routes in CASES.items():
            with self.subTest(provider=provider):
                spec = json.loads((ROOT / "openapi" / f"{provider}.json").read_text())
                validate(spec)
                for public_path, method, filename in routes:
                    source = json.loads((ROOT / "openapi" / "upstream" / filename).read_text())
                    metadata = source["info"]["x-aisa-source"]
                    self.assertEqual(metadata["kind"], "manual")
                    self.assertEqual(metadata["path_space"], "public")
                    self.assertIs(metadata["response_only"], True)
                    self.assertRegex(metadata["upstream_path_sha256"], r"^[0-9a-f]{64}$")
                    self.assertRegex(metadata["upstream_origin_sha256"], r"^[0-9a-f]{64}$")
                    self.assertEqual(list(source["paths"]), [public_path])
                    source_operation = source["paths"][public_path][method]
                    self.assertNotIn("requestBody", source_operation)
                    if public_path == "/apis/v1/duffel/flights/offer-requests/create":
                        view = next(parameter for parameter in spec["paths"][public_path][method]["parameters"]
                                    if parameter.get("name") == "view")
                        self.assertEqual(view["schema"]["enum"], ["offers"])
                        self.assertIn("itineraries", view["description"])
                        self.assertIn("not yet reviewed", view["description"])
                    response = source_operation["responses"]["200"]
                    schema = response["content"]["application/json"]["schema"]
                    self.assertEqual(schema.get("type"), "object")
                    self.assertIn("data", schema.get("required", []))
                    candidate = mirrors[(public_path, method)]["independent_response_candidates"]
                    self.assertEqual(len(candidate), 1)
                    self.assertIn("application/json", candidate[0]["response_operation"]["responses"]["200"]["content"])

    def test_recompose_clears_the_four_duffel_response_gaps(self):
        mirrors = public_mirror_index(ROOT)
        for provider, routes in CASES.items():
            with self.subTest(provider=provider):
                facts = json.loads((ROOT / "openapi" / f"{provider}.json").read_text())
                document, pending = compose(facts, public_mirrors=mirrors, unreviewed_runtime=True)
                route_set = {(row.get("path"), row.get("method", "").lower()) for row in pending}
                for path, method, _ in routes:
                    operation = document["paths"][path][method]
                    self.assertNotIn(PLACEHOLDER, operation["responses"]["200"]["description"])
                    self.assertIn("application/json", operation["responses"]["200"]["content"])
                    self.assertIn("schema", operation["responses"]["200"]["content"]["application/json"])
                    self.assertNotIn((path, method), route_set)
                    self.assertEqual(operation["x-aisa-response-source"]["kind"], "upstream_success_contract")

    def test_sources_retain_official_resource_models(self):
        fixtures = {
            "duffel-flights": (ROOT / "scripts/tests/fixtures/duffel-flights-reference-20261009.tar.gz", "offer-requests", "response-duffel-flights-get-offer-request-20261110.json"),
            "duffel-stays": (ROOT / "scripts/tests/fixtures/duffel-reference-20261008.tar.gz", "search-result", "response-duffel-stays-get-search-result-20261110.json"),
        }
        for provider, (fixture, slug, source_name) in fixtures.items():
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as directory:
                with tarfile.open(fixture) as archive:
                    archive.extractall(directory)
                raw = (Path(directory) / f"{slug}.html").read_bytes()
                model = json.loads("".join(NextData(raw).parts))["props"]["pageProps"]["resource"]["model"]
                source = json.loads((ROOT / "openapi/upstream" / source_name).read_text())
                schema = source["paths"][next(iter(source["paths"]))]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
                self.assertEqual(schema["properties"]["data"], model)


if __name__ == "__main__":
    unittest.main()
