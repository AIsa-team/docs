"""Regression coverage for the two live SERP request bodies verified against AIsa.

Run: python -m unittest discover -s scripts/tests -v
Dependencies: pyyaml, jsonschema. No API calls or credentials are required.
"""

import json
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

from consolidate_openapi import build_unified_spec
from localize_openapi_zh import strip_translatable


PATHS = (
    "/dataforseo/serp/google/organic/live/advanced",
    "/dataforseo/serp/google/maps/live/advanced",
)


class DataForSEOLiveRequestBodiesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.specs = {
            language: json.loads((ROOT / name).read_text())
            for language, name in (
                ("en", "openapi/dataforseo.json"),
                ("zh", "openapi/zh/dataforseo.json"),
            )
        }
        cls.unified = build_unified_spec()

    def test_request_body_is_array_of_task_objects(self):
        for language, spec in self.specs.items():
            for path in PATHS:
                with self.subTest(language=language, path=path):
                    body = spec["paths"][path]["post"]["requestBody"]
                    self.assertTrue(body["required"])
                    schema = body["content"]["application/json"]["schema"]
                    Draft202012Validator.check_schema(schema)
                    self.assertEqual(schema["type"], "array")
                    self.assertNotIn("properties", schema)
                    self.assertEqual(schema["items"]["type"], "object")
                    self.assertEqual(schema["items"]["required"], ["keyword"])
                    self.assertEqual(schema["items"]["properties"]["keyword"]["type"], "string")

    def test_single_task_examples_are_valid_arrays(self):
        for language, spec in self.specs.items():
            for path in PATHS:
                with self.subTest(language=language, path=path):
                    media = spec["paths"][path]["post"]["requestBody"]["content"]["application/json"]
                    self.assertIsInstance(media["example"], list)
                    self.assertEqual(len(media["example"]), 1)
                    Draft202012Validator(media["schema"]).validate(media["example"])

    def test_bare_object_and_invalid_tasks_are_rejected(self):
        for language, spec in self.specs.items():
            for path in PATHS:
                schema = spec["paths"][path]["post"]["requestBody"]["content"]["application/json"]["schema"]
                for invalid in ({"keyword": "sushi"}, ["sushi"], [{}], [{"keyword": 123}]):
                    with self.subTest(language=language, path=path, invalid=invalid):
                        self.assertFalse(Draft202012Validator(schema).is_valid(invalid))

    def test_english_and_chinese_request_contracts_match(self):
        for path in PATHS:
            with self.subTest(path=path):
                bodies = [spec["paths"][path]["post"]["requestBody"] for spec in self.specs.values()]
                context = ("paths", path, "post", "requestBody")
                self.assertEqual(strip_translatable(bodies[0], context), strip_translatable(bodies[1], context))

    def test_consolidation_preserves_array_contract_and_example(self):
        for path in PATHS:
            with self.subTest(path=path):
                source = self.specs["en"]["paths"][path]["post"]["requestBody"]
                consolidated = self.unified["paths"][path]["post"]["requestBody"]
                self.assertEqual(consolidated, source)
                self.assertEqual(consolidated["content"]["application/json"]["schema"]["type"], "array")


if __name__ == "__main__":
    unittest.main()
