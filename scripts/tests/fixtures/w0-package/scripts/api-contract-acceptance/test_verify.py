"""Negative checks for the acceptance gate, not tests of product internals."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("acceptance_verify", Path(__file__).with_name("verify.py"))
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


class OracleTests(unittest.TestCase):
    def test_boolean_numeric_drift_rejected(self):
        for actual, expected in ((False, 0), (True, 1), ({"s": False}, {"s": 0})):
            with self.subTest(actual=actual), self.assertRaises(ValueError):
                verify.assert_value({"v": actual}, {"pointer": "/v", "equals": expected})

    def test_absent_null_and_empty_differ(self):
        for actual in (None, {}, False):
            with self.subTest(actual=actual), self.assertRaises(ValueError):
                verify.assert_value({"v": actual}, {"pointer": "/v", "absent": True})

    def test_recursive_subset(self):
        verify.assert_value({"v": {"a": {"x": 1, "y": 2}, "b": 3}}, {"pointer": "/v", "subset": {"a": {"x": 1}}})

    def test_response_header_drop_rejected(self):
        _, expected = verify.verify_fixtures()
        actual = copy.deepcopy(expected)
        del actual["effective-get-widget"]["responses"]["200"]["headers"]
        with self.assertRaisesRegex(ValueError, "differs"):
            verify.compare_consumer(actual, expected)

    def test_missing_oracle_id_rejected(self):
        with self.assertRaises(ValueError):
            verify.compare_consumer({}, {"required": {}})

    def test_invalid_schema_example_decision_rejected(self):
        with self.assertRaises(ValueError):
            verify.verify_examples({"type": "string"}, [{"instance": 3, "valid": True}], standalone=True)

    def test_refs_in_reserved_property_names_preserved(self):
        doc = {"components": {"schemas": {"T": {"type": "object", "properties": {
            name: {"$ref": "#/components/schemas/Missing"} for name in ("value", "example", "default", "enum", "const")
        }, "default": {"$ref": "literal data"}}}}, "paths": {"/x": {"get": {"responses": {
            "default": {"$ref": "#/components/responses/Error"}
        }}}}}
        refs = verify.declared_refs(doc)
        self.assertEqual(len(refs), 6)
        self.assertFalse(any(ref == "literal data" for _, ref in refs))

    def test_named_example_ref_and_literal_value_are_distinct(self):
        doc = {"content": {"application/json": {"examples": {
            "shared": {"$ref": "#/components/examples/X"}, "value": {"value": {"$ref": "literal"}}
        }}}}
        self.assertEqual([ref for _, ref in verify.declared_refs(doc)], ["#/components/examples/X"])

    def test_ref_named_schema_and_property_are_names(self):
        doc = {"components": {"schemas": {"$ref": {"type": "string"}, "T": {
            "properties": {"$ref": {"$ref": "#/components/schemas/$ref"}}
        }}}}
        self.assertEqual([ref for _, ref in verify.declared_refs(doc)], ["#/components/schemas/$ref"])

    def test_archive_corruption_missing_and_traversal_rejected(self):
        data = b"{}"
        row = {"path": "input/facts/test.json", "bytes": 2, "sha256": verify.digest(data)}
        for name, content, rows in [(row["path"], b"[]", [row]), ("../escape", data, [row]), (row["path"], data, [row, {**row, "path": "missing"}])]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "data.tar.gz"
                with tarfile.open(path, "w:gz") as out:
                    info = tarfile.TarInfo(name)
                    info.size = len(content)
                    out.addfile(info, io.BytesIO(content))
                with self.assertRaises(ValueError):
                    verify.verify_archive(path, rows)


class FullAccountingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lock = verify.read_json(verify.PACKAGE / "manifest.json")
        cls.documents = verify.verify_archive(verify.ROOT / cls.lock["archive"]["path"], cls.lock["archive"]["files"])

    def test_unaccounted_endpoint_rejected(self):
        docs = dict(self.documents)
        name = "input/facts/inventory.json"
        docs[name] = self.documents[name] + [{"provider": "new", "path": "/new"}]
        with self.assertRaisesRegex(ValueError, "partition"):
            verify.verify_inventory(docs, self.lock["accounting_oracle"])

    def test_duplicate_or_changed_operation_identity_rejected(self):
        docs = dict(self.documents)
        name = "input/facts/agentmail.json"
        docs[name] = copy.deepcopy(docs[name])
        operations = [op for item in docs[name]["paths"].values() for method, op in item.items() if method in verify.METHODS]
        operations[0]["operationId"] = operations[1]["operationId"]
        with self.assertRaisesRegex(ValueError, "Operation IDs"):
            verify.verify_inventory(docs, self.lock["accounting_oracle"])

    def test_same_count_changed_debt_rejected(self):
        docs = dict(self.documents)
        name = "expected/openapi/coverage.json"
        docs[name] = copy.deepcopy(docs[name])
        row = next(row for rows in docs[name]["providers"].values() for row in rows if row["status"] == "pending")
        row["binding_hash"] = "changed-without-review"
        with self.assertRaisesRegex(ValueError, "debt identities"):
            verify.verify_inventory(docs, self.lock["accounting_oracle"])

    def test_swapped_operation_routes_rejected(self):
        docs = dict(self.documents)
        name = "input/facts/agentmail.json"
        docs[name] = copy.deepcopy(docs[name])
        ops = [op for item in docs[name]["paths"].values() for method, op in item.items() if method in verify.METHODS]
        ops[0]["operationId"], ops[1]["operationId"] = ops[1]["operationId"], ops[0]["operationId"]
        with self.assertRaisesRegex(ValueError, "route or status"):
            verify.verify_inventory(docs, self.lock["accounting_oracle"])

    def test_changed_inventory_status_rejected(self):
        docs = dict(self.documents)
        name = "input/facts/inventory.json"
        docs[name] = copy.deepcopy(docs[name])
        docs[name][0]["endpoint_status"] = "changed"
        with self.assertRaisesRegex(ValueError, "identity or status"):
            verify.verify_inventory(docs, self.lock["accounting_oracle"])


if __name__ == "__main__":
    unittest.main()
