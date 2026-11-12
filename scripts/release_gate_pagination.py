#!/usr/bin/env python3
"""Release gate G6: structural consistency of pagination and latency declarations.

Spec #1285 R1 (design-r1-pagination-latency.md §2.4, §2.6). G6 blocks a
release from the start: any finding fails the gate. ``--rollback-report-only``
(or ``AISA_G6_REPORT_ONLY=1``) exists only as a rollback switch and must not be
used as an observation period.

Checks, per operation that declares ``x-aisa-pagination``:

* ``style`` is one of cursor / page / offset / next_link;
* ``request.param`` is a declared parameter of the operation (path-level plus
  operation-level parameters, same ``in``) or, for ``in: body``, a property of
  the ``application/json`` request body schema (local ``$ref`` and ``allOf``
  resolved);
* ``next_link`` uses ``aisa_cursor`` in the query;
* ``ordering`` is stable / unstable; optional ``max_pages`` is a positive int;
* the 200 ``application/json`` schema has an ``aisa_pagination`` property whose
  ``next_param`` const equals ``request.param``.

Per operation that declares ``x-aisa-latency``: ``timeout_seconds`` is an int in
[30, 95]. ``x-aisa-latency-class`` (when present) is fast / slow / very_slow.

An operation without ``x-aisa-pagination`` is not a finding: undeclared does not
block.

Import contract for ``scripts/release_gate.py``::

    from release_gate_pagination import check_g6
    findings = check_g6(document)  # list of {operation_id, path, method, code, detail}

``check_g6`` is pure (no I/O) and never mutates ``document``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

GATE = "G6"
METHODS = ("get", "put", "post", "delete", "patch", "options", "head", "trace")
PAGINATION_STYLES = frozenset({"cursor", "page", "offset", "next_link"})
PAGINATION_ORDERING = frozenset({"stable", "unstable"})
REQUEST_LOCATIONS = frozenset({"query", "body"})
LATENCY_CLASSES = frozenset({"fast", "slow", "very_slow"})
LATENCY_BASES = frozenset({"observed", "probe", "sweep_seed", "family", "default"})
TIMEOUT_MIN_SECONDS, TIMEOUT_MAX_SECONDS = 30, 95
NEXT_LINK_PARAM = "aisa_cursor"
ENVELOPE = "aisa_pagination"
ROLLBACK_ENV = "AISA_G6_REPORT_ONLY"


def resolve(value: Any, document: dict, seen: frozenset = frozenset()) -> Any:
    """Follow local JSON-pointer references; unresolved or cyclic ones yield None."""
    while isinstance(value, dict) and isinstance(value.get("$ref"), str):
        ref = value["$ref"]
        if not ref.startswith("#/") or ref in seen:
            return None
        seen = seen | {ref}
        target: Any = document
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, dict) or part not in target:
                return None
            target = target[part]
        value = target
    return value


def schema_properties(schema: Any, document: dict, seen: frozenset = frozenset()) -> dict:
    """Properties of an object schema, including allOf members (later members win)."""
    schema = resolve(schema, document, seen)
    if not isinstance(schema, dict) or id(schema) in seen:
        return {}
    seen = seen | {id(schema)}
    properties: dict = {}
    for member in schema.get("allOf", []) if isinstance(schema.get("allOf"), list) else []:
        properties.update(schema_properties(member, document, seen))
    if isinstance(schema.get("properties"), dict):
        properties.update(schema["properties"])
    return properties


def json_media_schema(holder: Any, document: dict) -> Any:
    holder = resolve(holder, document)
    content = holder.get("content") if isinstance(holder, dict) else None
    media = content.get("application/json") if isinstance(content, dict) else None
    return media.get("schema") if isinstance(media, dict) else None


def declared_parameters(path_item: dict, operation: dict, document: dict) -> set:
    declared = set()
    for raw in list(path_item.get("parameters") or []) + list(operation.get("parameters") or []):
        parameter = resolve(raw, document)
        if isinstance(parameter, dict) and isinstance(parameter.get("name"), str):
            declared.add((parameter.get("in"), parameter["name"]))
    return declared


def check_pagination(declaration: Any, path_item: dict, operation: dict, document: dict) -> list[tuple[str, str]]:
    if not isinstance(declaration, dict):
        return [("pagination_invalid", "x-aisa-pagination must be an object")]
    problems = []
    style = declaration.get("style")
    if style not in PAGINATION_STYLES:
        problems.append(("pagination_style_invalid", f"style {style!r} is not one of {sorted(PAGINATION_STYLES)}"))
    ordering = declaration.get("ordering")
    if ordering not in PAGINATION_ORDERING:
        problems.append(("pagination_ordering_invalid", f"ordering {ordering!r} is not one of {sorted(PAGINATION_ORDERING)}"))
    if "max_pages" in declaration and (type(declaration["max_pages"]) is not int or declaration["max_pages"] < 1):
        problems.append(("pagination_max_pages_invalid", "max_pages must be a positive integer"))
    if "item_id" in declaration and not (isinstance(declaration["item_id"], str) and declaration["item_id"].startswith("/")):
        problems.append(("pagination_item_id_invalid", "item_id must be a JSON pointer"))
    request = declaration.get("request")
    if not isinstance(request, dict):
        return problems + [("pagination_request_invalid", "request must be an object with param and in")]
    param, location = request.get("param"), request.get("in")
    if not isinstance(param, str) or not param:
        return problems + [("pagination_request_invalid", "request.param must be a non-empty string")]
    if location not in REQUEST_LOCATIONS:
        problems.append(("pagination_request_invalid", f"request.in {location!r} is not one of {sorted(REQUEST_LOCATIONS)}"))
    if style == "next_link" and (param != NEXT_LINK_PARAM or location != "query"):
        problems.append(("pagination_next_link_param", f"next_link must use {NEXT_LINK_PARAM!r} in query, not {param!r} in {location!r}"))
    if location == "query" and ("query", param) not in declared_parameters(path_item, operation, document):
        problems.append(("pagination_param_undeclared", f"query parameter {param!r} is not declared by the operation"))
    elif location == "body" and param not in schema_properties(json_media_schema(operation.get("requestBody"), document), document):
        problems.append(("pagination_param_undeclared", f"request body property {param!r} is not declared by the operation"))
    size_param = request.get("size_param")
    if size_param is not None and not (isinstance(size_param, str) and size_param):
        problems.append(("pagination_request_invalid", "request.size_param must be a non-empty string when present"))
    responses = operation.get("responses") if isinstance(operation.get("responses"), dict) else {}
    success = json_media_schema(responses.get("200"), document)
    envelope = resolve(schema_properties(success, document).get(ENVELOPE), document) if success is not None else None
    if not isinstance(envelope, dict):
        problems.append(("pagination_envelope_missing", f"200 application/json schema has no {ENVELOPE} property"))
    else:
        next_param = resolve(schema_properties(envelope, document).get("next_param"), document)
        const = next_param.get("const") if isinstance(next_param, dict) else None
        if const != param:
            problems.append(("pagination_next_param_mismatch", f"{ENVELOPE}.next_param const {const!r} != request.param {param!r}"))
    return problems


def check_latency(operation: dict) -> list[tuple[str, str]]:
    problems = []
    if "x-aisa-latency-class" in operation and operation["x-aisa-latency-class"] not in LATENCY_CLASSES:
        problems.append(("latency_class_invalid", f"x-aisa-latency-class {operation['x-aisa-latency-class']!r} is not one of {sorted(LATENCY_CLASSES)}"))
    if "x-aisa-latency" not in operation:
        return problems
    latency = operation["x-aisa-latency"]
    if not isinstance(latency, dict):
        return problems + [("latency_invalid", "x-aisa-latency must be an object")]
    timeout = latency.get("timeout_seconds")
    if type(timeout) is not int or not TIMEOUT_MIN_SECONDS <= timeout <= TIMEOUT_MAX_SECONDS:
        problems.append(("latency_timeout_invalid", f"timeout_seconds {timeout!r} must be an integer in [{TIMEOUT_MIN_SECONDS}, {TIMEOUT_MAX_SECONDS}]"))
    if "basis" in latency and latency["basis"] not in LATENCY_BASES:
        problems.append(("latency_basis_invalid", f"basis {latency['basis']!r} is not one of {sorted(LATENCY_BASES)}"))
    return problems


def check_g6(document: dict) -> list[dict]:
    """Return every G6 finding of an OpenAPI document; an empty list passes."""
    findings = []
    paths = document.get("paths") if isinstance(document, dict) else None
    for path, raw_item in sorted((paths or {}).items()):
        path_item = resolve(raw_item, document)
        if not isinstance(path_item, dict):
            continue
        for method in METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            problems = []
            if "x-aisa-pagination" in operation:
                problems += check_pagination(operation["x-aisa-pagination"], path_item, operation, document)
            problems += check_latency(operation)
            findings += [{"gate": GATE, "operation_id": operation.get("operationId"), "path": path,
                          "method": method.upper(), "code": code, "detail": detail} for code, detail in problems]
    return findings


def load_document(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        import yaml
        return yaml.safe_load(text)
    return json.loads(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("document", type=Path, help="OpenAPI document (.json, .yaml or .yml)")
    parser.add_argument("--rollback-report-only", action="store_true",
                        help="rollback switch only: print findings but exit 0")
    args = parser.parse_args(argv)
    findings = check_g6(load_document(args.document))
    report_only = args.rollback_report_only or os.environ.get(ROLLBACK_ENV) == "1"
    print(json.dumps({"gate": GATE, "blocking": not report_only, "findings": findings},
                     ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if findings and not report_only else 0


if __name__ == "__main__":
    sys.exit(main())
