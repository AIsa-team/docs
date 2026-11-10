"""Focused response-contract checks for the Financial analyst estimates route."""
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
PATH = "/apis/v1/financial/analyst-estimates"
PLACEHOLDER = "Successful response. The payload schema has not been reviewed yet."


class FinancialResponseBindingTest(unittest.TestCase):
    def test_public_documents_publish_the_reviewed_response(self):
        for filename in ("openapi/financial.json", "openapi/zh/financial.json"):
            with self.subTest(filename=filename):
                document = json.loads((ROOT / filename).read_text())
                operation = document["paths"][PATH]["get"]
                response = operation["responses"]["200"]
                self.assertNotEqual(response.get("description"), PLACEHOLDER)
                schema = response["content"]["application/json"]["schema"]
                if "$ref" in schema:
                    schema = document["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
                self.assertEqual(schema["type"], "object")
                self.assertIn("analyst_estimates", schema["properties"])
                self.assertEqual(operation["x-aisa-response-source"]["kind"], "upstream_success_contract")
                self.assertNotIn("x-aisa-response-pending", operation)

    def test_response_source_is_independent_and_bound_to_the_public_route(self):
        source = json.loads((ROOT / "openapi/upstream/response-financial-analyst-estimates.json").read_text())
        metadata = source["info"]["x-aisa-source"]
        self.assertIs(metadata["response_only"], True)
        self.assertEqual(list(source["paths"]), [PATH])
        self.assertNotIn("requestBody", source["paths"][PATH]["get"])
        self.assertIn("analyst_estimates", source["components"]["schemas"]["AnalystEstimatesResponse"]["properties"])

    def test_reference_contract_snapshots_drop_the_old_pending_marker(self):
        for filename in ("reference-contracts/financial.json", "reference-contracts/zh/financial.json"):
            with self.subTest(filename=filename):
                operation = json.loads((ROOT / filename).read_text())["paths"][PATH]["get"]
                self.assertNotIn("x-aisa-response-pending", operation)
                self.assertEqual(operation["x-aisa-response-source"]["kind"], "upstream_success_contract")


if __name__ == "__main__":
    unittest.main()
