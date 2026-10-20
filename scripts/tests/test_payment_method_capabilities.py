import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import compose
from pull_openapi import generate_pages
from runtime_consolidate_openapi import build_unified_spec, inject_x402_annotations
from test_runtime_contracts import facts, mirror, operation


class PaymentMethodCapabilitiesTests(unittest.TestCase):
    def fixture(self, capabilities):
        runtime, upstream = facts("provider", "x-aisa-any"), mirror()
        operation(runtime)["x-aisa-capabilities"] = copy.deepcopy(capabilities)
        item = upstream["paths"]["/provider/test"]
        item["get"] = copy.deepcopy(item["post"])
        item["get"].pop("requestBody")
        for op in item.values():
            op["responses"] = {"200": {"description": "Success", "content": {
                "application/json": {"schema": {"type": "object"}}}}}
        return runtime, upstream

    def test_native_to_composed_aggregate_and_pages_use_exact_payment_methods(self):
        capabilities = {"mpp": True, "mpp_methods": ["GET"],
                        "x402": True, "x402_methods": ["POST"]}
        runtime, upstream = self.fixture(capabilities)
        original = copy.deepcopy(runtime)
        document, pending = compose(runtime, upstream)
        self.assertEqual(pending, [])
        self.assertEqual(runtime, original)
        path = "/apis/v1/similarweb/test"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "openapi").mkdir()
            (root / "openapi/similarweb.json").write_text(json.dumps(document))
            (root / "docs.json").write_text(json.dumps({"navigation": {"languages": []}}))
            aggregate = build_unified_spec(root=root)
            inject_x402_annotations(aggregate)
            changes = {}
            generate_pages(root, "similarweb", document, changes, decorate_links=False)
            pages = {name: text for name, text in changes.items() if name.suffix == ".mdx"}
            self.assertEqual(len(pages), 4)  # English and Chinese for both methods.
            for method, mpp, x402 in (("get", True, False), ("post", False, True)):
                with self.subTest(method=method):
                    op = document["paths"][path][method]
                    actual = aggregate["paths"][path][method]
                    expected = {**capabilities, "mpp": mpp, "x402": x402}
                    self.assertEqual(op["x-aisa-capabilities"], expected)
                    self.assertEqual(actual["x-aisa-capabilities"], expected)
                    self.assertEqual(actual["operationId"], op["operationId"])
                    self.assertEqual(actual["x-aisa-pricing"], op["x-aisa-pricing"])
                    self.assertEqual(op["x-aisa-runtime-operation"]["method"], "ANY")
                    self.assertNotIn("x-x402", actual)  # No legacy inferred surface.
                    matching = [text for text in pages.values()
                                if f' {method.upper()} {path}"' in text]
                    self.assertEqual(len(matching), 2)
                    for text in matching:
                        self.assertIn(op["operationId"], text)
                        self.assertIn('"method": "' + method.upper() + '"', text)
                        self.assertIn('"default_request_estimate_usd": 0.09', text)

    def test_method_lists_never_enable_false_or_missing_capability(self):
        for value in (False, None):
            capabilities = {"x402_methods": ["GET"], "mpp_methods": ["GET"]}
            if value is not None:
                capabilities.update(mpp=value, x402=value)
            runtime, upstream = self.fixture(capabilities)
            document, pending = compose(runtime, upstream)
            self.assertFalse(pending)
            for op in document["paths"]["/apis/v1/similarweb/test"].values():
                self.assertIs(op["x-aisa-capabilities"]["mpp"], False)
                self.assertIs(op["x-aisa-capabilities"]["x402"], False)

    def test_empty_list_denies_all_and_absent_list_preserves_legacy_facts(self):
        for capabilities in ({"mpp": True, "x402": True},
                             {"mpp": True, "mpp_methods": [], "x402": True, "x402_methods": []}):
            runtime, upstream = self.fixture(capabilities)
            document, pending = compose(runtime, upstream)
            self.assertFalse(pending)
            for op in document["paths"]["/apis/v1/similarweb/test"].values():
                expected = {**capabilities}
                if "x402_methods" in capabilities:
                    expected.update(mpp=False, x402=False)
                self.assertEqual(op["x-aisa-capabilities"], expected)

    def test_explicit_method_also_obeys_capability_list_without_changing_identity(self):
        runtime = facts("runtime", "post")
        operation(runtime)["x-aisa-capabilities"] = {"mpp": True, "mpp_methods": ["GET"],
                                                   "x402": True, "x402_methods": ["GET"]}
        document, pending = compose(runtime)
        self.assertFalse(pending)
        self.assertEqual(operation(document)["operationId"], "published_identity")
        self.assertFalse(operation(document)["x-aisa-capabilities"]["mpp"])
        self.assertFalse(operation(document)["x-aisa-capabilities"]["x402"])

    def test_payment_lists_reject_types_duplicates_unknown_and_nonuppercase_methods(self):
        invalid = (None, True, 1, "GET", {"GET": True}, [None], [True], [{}],
                   ["GET", "GET"], ["get"], ["Get"], ["GET "], ["CONNECT"],
                   ["ANY"], ["GET"] * 9)
        for field in ("mpp_methods", "x402_methods"):
            for value in invalid:
                with self.subTest(field=field, value=value):
                    runtime, upstream = self.fixture({"mpp": True, "x402": True, field: value})
                    with self.assertRaises(ValueError):
                        compose(runtime, upstream)

    def test_capabilities_are_closed_and_typed_without_coercing_untrusted_values(self):
        invalid = (None, [], True, {"unknown": True}, {"x402_Methods": ["GET"]},
                   {"x402": 1}, {"mpp": "true"}, {"max_price": None}, {"idempotency": []},
                   {"quote": None}, {"quote": {"unknown": True}},
                   {"quote": {"supported": 1}}, {"quote": {"endpoint": False}})
        for value in invalid:
            with self.subTest(value=value):
                runtime, upstream = self.fixture(value)
                with self.assertRaises(ValueError):
                    compose(runtime, upstream)
        runtime, upstream = self.fixture({"x402": True, "x402_methods": ["POST", "GET"],
            "quote": {"header": "X-AISA-Cost-Mode", "value": "quote", "supported": True},
            "max_price": "X-AISA-Max-Price-USD", "idempotency": "Idempotency-Key"})
        document, pending = compose(runtime, upstream)
        self.assertFalse(pending)
        self.assertEqual(operation(document)["x-aisa-capabilities"]["x402_methods"], ["POST", "GET"])

    def test_payment_metadata_cannot_close_unforwarded_supplier_auth_headers(self):
        runtime, upstream = self.fixture({"mpp": True, "mpp_methods": ["GET"],
                                         "x402": True, "x402_methods": ["POST"]})
        for op in upstream["paths"]["/provider/test"].values():
            op["parameters"].append({"name": "RELAYER_API_KEY", "in": "header",
                                     "schema": {"type": "string"}})
        document, pending = compose(runtime, upstream)
        self.assertEqual(document["paths"], {})
        self.assertEqual(len(pending), 2)
        self.assertTrue(all(row["reason"] ==
            "source header parameters are not forwarded by runtime: RELAYER_API_KEY" for row in pending))


if __name__ == "__main__":
    unittest.main()
