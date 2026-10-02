#!/usr/bin/env python3
"""Verify the W0 evidence package. This does not approve a product or release.

No implementation module is imported. No HTTP request or database access occurs.
Consumer adapters must emit their actual results separately for exact comparison.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

from jsonschema import Draft202012Validator
from openapi_spec_validator import validate as validate_openapi
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "docs/api-contract-acceptance"
FIXTURES = Path(__file__).parent / "fixtures"
METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace", "x-aisa-any"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(Path(path).read_text())


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pointer(document, value):
    require(value == "" or value.startswith("/"), f"Not a JSON pointer: {value}")
    current = document
    for token in value.split("/")[1:] if value else []:
        key = token.replace("~1", "/").replace("~0", "~")
        current = current[int(key)] if isinstance(current, list) else current[key]
    return current


def same(actual, expected):
    """JSON equality, including booleans distinct from numeric zero/one."""
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(actual, dict) and isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(same(actual[k], expected[k]) for k in actual)
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(same(a, e) for a, e in zip(actual, expected))
    if type(actual) is not type(expected) and not (isinstance(actual, (int, float)) and isinstance(expected, (int, float))):
        return False
    return actual == expected


def subset(actual, expected):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and subset(actual[k], v) for k, v in expected.items())
    return same(actual, expected)


def declared_refs(document):
    """Walk reference objects, not literal instance data in examples/defaults."""
    found = []
    def walk(value, path="", context="openapi"):
        if isinstance(value, dict):
            if context not in {"schema_map", "example_map", "object_map"} and "$ref" in value:
                require(isinstance(value["$ref"], str), f"Reference must be a string at {path}")
                found.append((path + "/$ref", value["$ref"]))
            for key, child in value.items():
                if (context == "schema" and key in {"example", "examples", "default", "enum", "const"}) or (context == "example" and key == "value"):
                    continue
                if context not in {"schema_map", "example_map"} and key == "example":
                    continue
                next_path = path + "/" + key.replace("~", "~0").replace("/", "~1")
                child_context = context
                if context == "schema_map":
                    child_context = "schema"
                elif context == "example_map":
                    child_context = "example"
                elif context == "object_map":
                    child_context = "openapi"
                elif key == "schema":
                    child_context = "schema"
                elif next_path == "/components/schemas" or (context == "schema" and key in {"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"}):
                    child_context = "schema_map"
                elif key == "examples" and context != "schema":
                    child_context = "example_map"
                elif context == "openapi" and (key in {"paths", "responses", "headers", "links", "callbacks", "webhooks", "content"}
                                                or path == "/components"):
                    child_context = "object_map"
                walk(child, next_path, child_context)
        elif isinstance(value, list):
            for i, child in enumerate(value):
                walk(child, path + "/" + str(i), context)
    walk(document)
    return found


def assert_value(document, assertion):
    modes = [k for k in ("equals", "subset", "absent") if k in assertion]
    require(len(modes) == 1, "Assertion must have exactly one comparison mode")
    try:
        actual = pointer(document, assertion["pointer"])
    except (KeyError, IndexError):
        require(assertion.get("absent") is True, f"Missing {assertion['pointer']}")
        return
    if modes[0] == "absent":
        raise ValueError(f"Expected absent: {assertion['pointer']}")
    if modes[0] == "equals":
        require(same(actual, assertion["equals"]), f"Value differs at {assertion['pointer']}")
    else:
        require(isinstance(actual, dict), "Subset comparison needs an object")
        require(subset(actual, assertion["subset"]),
                f"Subset differs at {assertion['pointer']}")


def verify_examples(document, examples, standalone=False):
    registry = Registry().with_resource("urn:aisa:fixture", Resource(document, DRAFT202012))
    for row in examples:
        schema = document if standalone else {"$ref": "urn:aisa:fixture#" + row["schema_pointer"]}
        validator = Draft202012Validator(schema, registry=registry)
        require(validator.is_valid(row["instance"]) == row["valid"], "Example validity differs from fixed oracle")


def verify_fixtures():
    expectations, cases, assertions, examples, validated_documents = {}, set(), 0, 0, 0
    for path in sorted(FIXTURES.glob("*.expected.json")):
        manifest = read_json(path)
        require(manifest["format_version"] == 1, "Unsupported oracle format")
        document = read_json(FIXTURES / manifest["fixture"])
        negatives = {row["ref"]: row for row in manifest.get("negative_expectations", [])}
        if not negatives:
            validate_openapi(document)
            validated_documents += 1
        for source_pointer, reference in declared_refs(document):
            if reference.startswith("#/"):
                try:
                    pointer(document, reference[1:])
                except (KeyError, IndexError):
                    require(reference in negatives and negatives[reference]["reason"] == "missing_local_target",
                            f"Undeclared missing fixture reference at {source_pointer}")
            else:
                require(reference in negatives and negatives[reference]["reason"] == "external_target_not_in_frozen_inputs",
                        f"Unexpected external fixture reference at {source_pointer}")
        for case in manifest["cases"]:
            require(case["id"] not in cases, "Duplicate fixture case ID")
            cases.add(case["id"])
            require(bool(case["criteria"]), "Case without acceptance criteria")
            source = case.get("source_ref", {})
            if source.get("file"):
                pointer(read_json(FIXTURES / source["file"]), source["pointer"])
            for assertion in case.get("assertions", []):
                assert_value(document, assertion)
                assertions += 1
            verify_examples(document, case.get("schema_examples", []))
            examples += len(case.get("schema_examples", []))
        for expectation in manifest.get("consumer_expectations", []):
            require(expectation["id"] not in expectations, "Duplicate consumer expectation ID")
            source = expectation.get("source_ref", {})
            if source.get("file"):
                pointer(read_json(FIXTURES / source["file"]), source["pointer"])
            if expectation.get("schema_examples"):
                verify_examples(expectation["expected"], expectation["schema_examples"], standalone=True)
                examples += len(expectation["schema_examples"])
            expectations[expectation["id"]] = expectation["expected"]
        for negative in negatives.values():
            require(negative["id"] not in expectations, "Duplicate negative oracle ID")
            require(pointer(document, negative["source_ref"]["pointer"]) == negative["ref"], "Negative reference differs")
            require(negative["expected"]["complete"] is False and negative["must_not"], "Negative oracle silently complete")
            expectations[negative["id"]] = negative["expected"]
    require(cases and expectations, "Fixture or consumer oracle is empty")
    return {"cases": len(cases), "assertions": assertions, "schema_examples": examples,
            "positive_openapi_documents": validated_documents, "consumer_expectations": len(expectations)}, expectations


def compare_consumer(actual, expected):
    require(set(actual) == set(expected), "Missing or extra consumer expectation IDs")
    for key in expected:
        require(same(actual[key], expected[key]), f"Consumer output differs: {key}")


def verify_archive(archive, entries):
    expected = {row["path"]: row for row in entries}
    require(len(expected) == len(entries), "Duplicate archived path")
    documents = {}
    seen = set()
    with tarfile.open(archive, "r:gz") as source:
        for member in source:
            name = PurePosixPath(member.name)
            require(member.isfile() and not name.is_absolute() and ".." not in name.parts,
                    "Unsafe archive member")
            require(member.name in expected and member.name not in seen, "Unexpected or duplicate archive file")
            row = expected[member.name]
            data = source.extractfile(member).read()
            require(len(data) == row["bytes"] and digest(data) == row["sha256"], f"Archive hash mismatch: {member.name}")
            seen.add(member.name)
            if member.name.startswith("input/facts/") or member.name.startswith("expected/openapi/"):
                if member.name.endswith(".json"):
                    documents[member.name] = json.loads(data)
    require(seen == set(expected), "Missing archived files")
    return documents


def verify_inventory(documents, oracle):
    facts = "input/facts/"
    index, inventory = documents[facts + "index.json"], documents[facts + "inventory.json"]
    key = lambda row: (row["provider"], row["path"])
    all_rows = {key(row) for row in inventory}
    require(len(all_rows) == len(inventory), "Duplicate inventory identity")
    coverage = index["coverage"]
    buckets = [coverage["projected_endpoints"], coverage["excluded_endpoints"], index["pending_endpoints"]]
    flattened = [key(row) for bucket in buckets for row in bucket]
    require(len(flattened) == len(set(flattened)) and set(flattened) == all_rows, "Inventory partition differs")
    require(len(inventory) == oracle["inventory_endpoints"], "Inventory endpoint count differs")
    require(digest(json.dumps(sorted(inventory, key=lambda r: key(r)), sort_keys=True, separators=(",", ":")).encode()) == oracle["inventory_rows_sha256"], "Inventory identity or status association differs")
    require([len(x) for x in buckets] == oracle["partition_counts"], "Partition count differs")
    ids, fact_paths, operations, identity_rows = [], set(), [], []
    for provider in index["providers"]:
        document = documents[facts + provider["id"] + ".json"]
        require(document["info"]["x-aisa-document"]["facts_hash"] == provider["facts_hash"], "Index facts hash differs")
        provider_ops = [(p, m, op) for p, item in document["paths"].items()
                        for m, op in item.items() if m in METHODS]
        require(len(provider_ops) == provider["operation_count"], "Provider operation count differs")
        require(sum(row["provider"] == provider["id"] for row in buckets[0]) == provider["endpoint_count"], "Provider projected endpoint count differs")
        fact_paths.update((provider["id"], p) for p in document["paths"])
        ids.extend(op["operationId"] for p, m, op in provider_ops)
        operations.extend(provider_ops)
        identity_rows.extend([provider["id"], p, m, op["operationId"], op.get("x-aisa-status")] for p, m, op in provider_ops)
    projected = {key(row) for row in buckets[0]}
    require(projected <= fact_paths, "Projected route missing from facts")
    require(fact_paths - projected == {tuple(row) for row in oracle["derived_paths"]}, "Derived route accounting differs")
    require(len(ids) == len(set(ids)) == oracle["fact_operations"], "Operation IDs missing, duplicated, or changed count")
    require(digest(json.dumps(sorted(ids), separators=(",", ":")).encode()) == oracle["operation_id_set_sha256"], "Operation identity set differs")
    require(digest(json.dumps(sorted(identity_rows), separators=(",", ":")).encode()) == oracle["operation_identity_rows_sha256"], "Operation route or status association differs")
    managed = [v for p, v in documents.items() if p.startswith("expected/openapi/")
               and v.get("info", {}).get("x-aisa-document", {}).get("composer_version") == "9"]
    composed = [(p, m, op) for doc in managed for p, item in doc["paths"].items()
                for m, op in item.items() if m in METHODS]
    require(len(managed) == oracle["composed_documents"] and len(composed) == oracle["composed_operations"], "Output accounting differs")
    debt = [dict(provider=provider, **row) for provider, rows in documents["expected/openapi/coverage.json"]["providers"].items()
            for row in rows if row["status"] == "pending"]
    response_debt = [dict(provider=doc["info"].get("x-aisa-provider", ""), **row)
                     for doc in managed for row in doc["info"]["x-aisa-document"].get("response_pending", [])]
    require(len(debt) == oracle["request_gaps"] and len(response_debt) == oracle["response_gaps"], "Frozen debt counts differ")
    require(digest(json.dumps(debt, sort_keys=True, separators=(",", ":")).encode()) == oracle["request_debt_sha256"], "Frozen request debt identities differ")
    require(digest(json.dumps(response_debt, sort_keys=True, separators=(",", ":")).encode()) == oracle["response_debt_sha256"], "Frozen response debt identities differ")
    request_statuses = Counter()
    for row in debt:
        fact = documents[facts + row.get("catalog", row["provider"]) + ".json"]
        item = fact["paths"][row["path"]]
        op = item.get(row["method"].lower(), item.get("x-aisa-any", {}))
        request_statuses[op.get("x-aisa-status", "unknown")] += 1
    require(dict(request_statuses) == {"enabled": oracle["enabled_request_gaps"], "disabled": oracle["disabled_request_gaps"]}, "Request gap status accounting differs")
    response_statuses = Counter(doc["paths"][row["path"]][row["method"].lower()].get("x-aisa-status", "unknown")
                                for doc in managed for row in doc["info"]["x-aisa-document"].get("response_pending", []))
    require(dict(response_statuses) == oracle["response_gap_status_counts"], "Response gap status accounting differs")
    return {"inventory_endpoints": len(inventory), "projected_endpoints": len(projected),
            "fact_operations": len(operations), "composed_operations": len(composed),
            "request_gaps": len(debt), "response_gaps": len(response_debt)}


def verify_gates():
    checks, budgets, scenarios = (read_json(PACKAGE / name) for name in ("checks.json", "budgets.json", "scenarios.json"))
    ids = [row["id"] for row in checks["checks"]]
    require(len(ids) == len(set(ids)), "Duplicate gate ID")
    covered = set()
    for row in checks["checks"]:
        require(row["owner_role"] and row["commands"], "Gate without owner or command")
        require(row["current_status"] != "passed" or row.get("evidence"), "Passed gate without evidence")
        covered.update(row["acceptance_cases"])
    require({f"C{i:02}" for i in range(1, 15)} <= covered, "Acceptance criteria missing gate assignment")
    require(budgets["frozen_targets"], "No frozen budget")
    require({f"C{i:02}" for i in range(1, 15)} <= {row["criterion"] for row in scenarios["cases"]}, "Missing acceptance scenario")
    require(all(row["expected"] and row["owner_role"] and row["inputs"] for row in scenarios["cases"]), "Incomplete scenario")
    return {"mapped_criteria": 14, "checks": len(ids), "scenarios": len(scenarios["cases"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--consumer-output", type=Path,
                        help="Actual W1 adapter outputs keyed by oracle ID; never generate this from expected files")
    args = parser.parse_args()
    lock = read_json(PACKAGE / "manifest.json")
    require(digest((ROOT / lock["specification"]["path"]).read_bytes()) == lock["specification"]["sha256"], "Frozen specification differs")
    actual_members = {p.relative_to(ROOT).as_posix()
                      for directory in lock["package_roots"] for p in (ROOT / directory).rglob("*")
                      if p.is_file() and "__pycache__" not in p.parts
                      and p.relative_to(ROOT).as_posix() not in lock["excluded_package_files"]
                      and p != ROOT / lock["archive"]["path"]}
    require(actual_members == {row["path"] for row in lock["package_files"]}, "Package file membership differs")
    for row in lock["package_files"]:
        require(digest((ROOT / row["path"]).read_bytes()) == row["sha256"], f"Package file differs: {row['path']}")
    archive = ROOT / lock["archive"]["path"]
    require(digest(archive.read_bytes()) == lock["archive"]["sha256"], "Archive digest differs")
    documents = verify_archive(archive, lock["archive"]["files"])
    accounting = verify_inventory(documents, lock["accounting_oracle"])
    fixture_result, expectations = verify_fixtures()
    gates = verify_gates()
    if args.consumer_output:
        compare_consumer(read_json(args.consumer_output), expectations)
    result = {"scope": "W0 package integrity and independent oracle self-check; not product or release acceptance",
              "package_status": "passed", "catalog_accounting": accounting, "fixture_oracle": fixture_result,
              "gate_mapping": gates, "consumer_status": "passed_supplied_output_only" if args.consumer_output else "not_assessed",
              "release_status": "not_assessed", "content_status": "pending_debt", "known_blockers": lock["known_blockers"]}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, IndexError) as error:
        raise SystemExit(f"FAIL: {error}") from error
