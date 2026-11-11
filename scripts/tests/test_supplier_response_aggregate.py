"""Keep reviewed supplier operations callable through the aggregate contract."""
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "docs/current-source-review-20261110/supplier-response-batch.json"


class SupplierResponseAggregateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.aggregate = json.loads((ROOT / "openapi/openapi.json").read_text())
        cls.rows = json.loads(INVENTORY.read_text())["operations"]
        cls.providers = {
            name: json.loads((ROOT / "openapi" / f"{name}.json").read_text())
            for name in {row["provider"] for row in cls.rows}
        }

    def test_aggregate_preserves_effective_request_urls(self):
        for row in self.rows:
            with self.subTest(provider=row["provider"], path=row["path"]):
                provider = self.providers[row["provider"]]
                path, method = row["path"], row["method"].lower()
                native_item = provider["paths"][path]
                aggregate_item = self.aggregate["paths"][path]
                native = native_item[method]
                aggregate = aggregate_item[method]
                native_servers = native.get("servers", native_item.get("servers", provider.get("servers", [])))
                aggregate_servers = aggregate.get("servers", aggregate_item.get("servers", self.aggregate.get("servers", [])))
                expected = [server["url"].rstrip("/") + path for server in native_servers]
                actual = [server["url"].rstrip("/") + path for server in aggregate_servers]
                self.assertTrue(expected)
                self.assertEqual(actual, expected)
                self.assertTrue(all("/apis/v1/apis/v1/" not in url for url in actual))

    def test_aggregate_preserves_authentication_ownership_and_status(self):
        for row in self.rows:
            with self.subTest(provider=row["provider"], path=row["path"]):
                provider = self.providers[row["provider"]]
                path, method = row["path"], row["method"].lower()
                native = provider["paths"][path][method]
                aggregate = self.aggregate["paths"][path][method]
                self.assertEqual(
                    aggregate.get("security", self.aggregate.get("security", [])),
                    native.get("security", provider.get("security", [])),
                )
                self.assertEqual(aggregate["x-aisa-provider"], row["provider"])
                owner = self.aggregate["info"]["x-aisa-document"]["providers"][row["provider"]]["registry_provider"]
                self.assertEqual(aggregate.get("x-aisa-registry-provider"), owner)
                self.assertEqual(aggregate["x-aisa-status"], native["x-aisa-status"])

    def test_inventory_does_not_count_unreviewed_responses_as_completed(self):
        inventory = json.loads(INVENTORY.read_text())
        declared = 0
        identities = set()
        for row in self.rows:
            identity = (row["provider"], row["path"], row["method"])
            self.assertNotIn(identity, identities)
            identities.add(identity)
            operation = self.providers[row["provider"]]["paths"][row["path"]][row["method"].lower()]
            reviewed = bool(operation.get("x-aisa-response-source")) and not (
                operation.get("x-aisa-response-pending")
                or operation.get("x-aisa-review", {}).get("response") == "generic"
            )
            with self.subTest(identity=identity):
                self.assertEqual(row["response_status"], "declared" if reviewed else "unreviewed")
                if not reviewed:
                    self.assertIsNone(row["source_kind"])
                    self.assertTrue(row["response_reason"])
            declared += reviewed
        self.assertEqual(inventory["counts"]["paths"], len(identities))
        self.assertEqual(inventory["counts"]["response_declarations"], declared)
        self.assertEqual(inventory["counts"]["response_pending"], len(identities) - declared)


if __name__ == "__main__":
    unittest.main()
