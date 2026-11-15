"""Spec #1285 R1: Runtime pagination and latency metadata survive composition."""
import copy
from pathlib import Path
import sys
import unittest
sys.path[:0] = [str(Path(__file__).resolve().parents[1])]
from compose_openapi import (compose, NON_PUBLIC_EXTENSIONS, PUBLIC_CONTRACT_EXTENSIONS,
                             merge_pagination_property, without_pagination_payload)
from release_gate_pagination import check_g6
from test_independent_response_sources import descriptor, index, response_source
from test_runtime_contracts import facts, operation

PAGINATION = {"style": "cursor", "request": {"param": "cursor", "in": "query", "size_param": "limit"},
              "ordering": "unstable", "item_id": "/id", "max_pages": 50}
ENVELOPE = {"type": "object", "additionalProperties": False, "required": ["has_more", "next_cursor", "next_param"],
            "properties": {"has_more": {"type": "boolean"}, "next_cursor": {"type": ["string", "null"]},
                           "next_param": {"type": "string", "const": "cursor"}}}
LATENCY = {"timeout_seconds": 45, "basis": "sweep_seed"}


def paginated(runtime, schema=None):
    op = operation(runtime)
    op["parameters"].append({"name": "cursor", "in": "query", "schema": {"type": "string"}})
    op["x-aisa-pagination"] = copy.deepcopy(PAGINATION)
    op["x-aisa-latency-class"] = "slow"
    op["x-aisa-latency"] = copy.deepcopy(LATENCY)
    op["responses"]["200"]["content"] = {"application/json": {"schema": schema or {
        "type": "object", "properties": {"aisa_pagination": copy.deepcopy(ENVELOPE)}}}}
    return runtime


def success_schema(document):
    return operation(document)["responses"]["200"]["content"]["application/json"]["schema"]


class PaginationCompositionTests(unittest.TestCase):
    def test_extensions_are_public_contract_not_provenance(self):
        self.assertFalse(PUBLIC_CONTRACT_EXTENSIONS & NON_PUBLIC_EXTENSIONS)

    def test_runtime_extensions_copy_unchanged_and_envelope_merges_into_source_schema(self):
        runtime = paginated(descriptor(facts()))
        doc, pending = compose(runtime, public_mirrors=index(response_source()))
        self.assertEqual(pending, [])
        actual = operation(doc)
        self.assertEqual(actual["x-aisa-pagination"], PAGINATION)
        self.assertEqual(actual["x-aisa-latency-class"], "slow")
        self.assertEqual(actual["x-aisa-latency"], LATENCY)
        self.assertNotIn("x-aisa-response-pending", actual)
        schema = success_schema(doc)
        # The reviewed source payload is kept; the envelope is added beside it.
        self.assertEqual(schema["properties"]["value"], {"type": "string"})
        self.assertEqual(schema["required"], ["value"])
        self.assertEqual(schema["properties"]["aisa_pagination"], ENVELOPE)
        self.assertEqual(check_g6(doc), [])
        # Idempotent against its own previous publication.
        self.assertEqual(compose(runtime, public_mirrors=index(response_source()), previous=doc), (doc, []))

    def test_retained_previous_payload_does_not_absorb_the_envelope(self):
        runtime = paginated(descriptor(facts()))
        first, _ = compose(runtime, public_mirrors=index(response_source()))
        plain = facts()
        operation(plain)["parameters"].append({"name": "cursor", "in": "query", "schema": {"type": "string"}})
        paged = paginated(facts())
        retained_plain, _ = compose(plain, previous=first)
        retained_paged, _ = compose(paged, previous=first)
        self.assertNotIn("aisa_pagination", success_schema(retained_plain)["properties"])
        self.assertEqual(success_schema(retained_paged)["properties"]["aisa_pagination"], ENVELOPE)
        self.assertEqual(operation(retained_paged)["x-aisa-response-source"],
                         operation(retained_plain)["x-aisa-response-source"])
        self.assertEqual(compose(paged, previous=retained_paged), (retained_paged, []))

    def test_pending_response_keeps_gap_and_still_declares_envelope(self):
        runtime = paginated(facts())
        doc, pending = compose(runtime)
        self.assertEqual(pending, [])
        self.assertIn("x-aisa-response-pending", operation(doc))
        self.assertEqual(success_schema(doc), {"type": "object", "properties": {"aisa_pagination": ENVELOPE}})
        # The envelope alone is never retained as a reviewed success payload.
        again, _ = compose(runtime, previous=doc)
        self.assertIn("x-aisa-response-pending", operation(again))
        self.assertNotIn("x-aisa-response-source", operation(again))

    def test_owned_runtime_schema_is_kept(self):
        owned = {"type": "object", "properties": {"items": {"type": "array"}, "aisa_pagination": copy.deepcopy(ENVELOPE)},
                 "required": ["items"]}
        runtime = paginated(facts(), owned)
        doc, _ = compose(runtime)
        self.assertEqual(success_schema(doc), owned)
        self.assertNotIn("x-aisa-response-pending", operation(doc))

    def test_merge_wraps_references_and_is_idempotent(self):
        response = {"description": "ok", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/List"}}}}
        merge_pagination_property(response, ENVELOPE)
        merged = copy.deepcopy(response)
        self.assertEqual(merged["content"]["application/json"]["schema"]["allOf"][0], {"$ref": "#/components/schemas/List"})
        merge_pagination_property(response, ENVELOPE)
        self.assertEqual(response, merged)
        self.assertEqual(without_pagination_payload(response)["content"]["application/json"]["schema"],
                         {"$ref": "#/components/schemas/List"})
        generic = {"description": "ok", "content": {"application/json": {"schema": {}}}}
        merge_pagination_property(generic, ENVELOPE)
        self.assertEqual(generic["content"]["application/json"]["schema"]["properties"], {"aisa_pagination": ENVELOPE})
        no_content = {"description": "empty", "x-aisa-no-content": True}
        merge_pagination_property(no_content, ENVELOPE)
        self.assertEqual(no_content, {"description": "empty", "x-aisa-no-content": True})

    def test_operation_without_declaration_is_unchanged(self):
        runtime = descriptor(facts())
        doc, _ = compose(runtime, public_mirrors=index(response_source()))
        self.assertFalse(PUBLIC_CONTRACT_EXTENSIONS & set(operation(doc)))
        self.assertNotIn("aisa_pagination", success_schema(doc)["properties"])


if __name__ == "__main__":
    unittest.main()
