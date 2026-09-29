#!/usr/bin/env python3
"""Pure composition of runtime facts, a provenance-bearing mirror and editorial text.

Never derives prices, identities, status or capabilities from a provider mirror.
Unsupported/missing upstream contracts fail closed into the pending list.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlsplit

VERSION = "4"
METHODS = frozenset({"get", "put", "post", "delete", "patch", "options", "head", "trace"})
OVERLAY_KEYS = {"description", "x-aisa-notes"}


class IdentityError(ValueError):
    pass


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def validate_overlay(overlay: dict) -> None:
    for operation_id, entry in overlay.items():
        if not isinstance(entry, dict) or set(entry) - OVERLAY_KEYS:
            raise ValueError(f"overlay {operation_id}: only description and x-aisa-notes are allowed")
        if "description" in entry and not isinstance(entry["description"], str):
            raise ValueError(f"overlay {operation_id}: description must be text")
        notes = entry.get("x-aisa-notes", [])
        if not isinstance(notes, list) or not all(isinstance(n, str) for n in notes):
            raise ValueError(f"overlay {operation_id}: notes must be a list of text")
        prose = json.dumps(entry)
        if re.search(r"(?:\$\s*\d|\b(?:USD|US\$)\s*\d|\d\s*(?:USD|dollars?)\b)", prose, re.I):
            raise ValueError(f"overlay {operation_id}: prices belong to runtime facts")
        if re.search(r'"(?:parameters|properties|requestBody|schema)"\s*:', prose):
            raise ValueError(f"overlay {operation_id}: parameter definitions belong to contracts")


def resolve(value: Any, document: dict, stack: tuple = (), preserve_recursive: bool = False) -> Any:
    """Resolve selected mirror references, never fetching arbitrary remote URLs."""
    if isinstance(value, list):
        return [resolve(v, document, stack, preserve_recursive) for v in value]
    if not isinstance(value, dict):
        return value
    if "$ref" in value:
        ref = value["$ref"]
        if not ref.startswith("#/"):
            raise ValueError("unsupported external upstream reference")
        if ref in stack:
            if preserve_recursive:
                return copy.deepcopy(value)
            raise ValueError("unsupported recursive upstream reference")
        target: Any = document
        for part in ref[2:].split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        target = resolve(target, document, stack + (ref,), preserve_recursive)
        siblings = {k: resolve(v, document, stack, preserve_recursive) for k, v in value.items() if k != "$ref"}
        if siblings:
            if not isinstance(target, dict):
                raise ValueError("upstream reference has incompatible siblings")
            if any(key in target and target[key] != value and key not in {"description", "summary", "title"} for key, value in siblings.items()):
                raise ValueError("upstream reference has conflicting sibling constraints")
            target = {**target, **siblings}
        return target
    return {k: resolve(v, document, stack, preserve_recursive) for k, v in value.items()}



def referenced_components(value: Any, document: dict) -> dict:
    """Collect the finite reachable component graph without expanding cycles."""
    components = {}
    seen = set()
    def visit(node):
        if isinstance(node, list):
            for item in node:
                visit(item)
        elif isinstance(node, dict):
            ref = node.get("$ref")
            if ref and ref not in seen:
                if not ref.startswith("#/components/"):
                    raise ValueError("unsupported external or non-component upstream reference")
                parts = ref.split("/")
                if len(parts) < 4:
                    raise ValueError("invalid upstream component reference")
                section, name = (part.replace("~1", "/").replace("~0", "~") for part in parts[2:4])
                if section == "securitySchemes":
                    raise ValueError("provider security scheme is not a request schema")
                definition = document["components"][section][name]
                seen.add(ref)
                components.setdefault(section, {})[name] = copy.deepcopy(definition)
                visit(definition)
            for item in node.values():
                visit(item)
    visit(value)
    return components


def resolve_fragment(value: Any, document: dict, output: dict, namespace: str) -> Any:
    from consolidate_openapi import component_collision_prefix, merge_components
    selected = {"fragment": copy.deepcopy(value), "components": referenced_components(value, document)}
    # Give the entire reachable graph one stable namespace, so recursive and
    # mutually-dependent definitions cannot capture another source's names.
    prefix = component_collision_prefix(namespace) + "_"
    renamed = {}
    for section, entries in selected["components"].items():
        for name in entries:
            target = name if name.startswith(prefix) else prefix + name
            renamed[f"#/components/{section}/{name}"] = f"#/components/{section}/{target}"
    def rewrite(node):
        if isinstance(node, list):
            return [rewrite(item) for item in node]
        if not isinstance(node, dict):
            return node
        return {key: renamed.get(item, item) if key == "$ref" else rewrite(item) for key, item in node.items()}
    selected = rewrite(selected)
    selected["components"] = {section: {renamed[f"#/components/{section}/{name}"].rsplit("/", 1)[1]: definition for name, definition in entries.items()} for section, entries in selected["components"].items()}
    output.setdefault("components", {})
    merge_components(output, selected, namespace)
    return resolve(selected["fragment"], output, preserve_recursive=True)


def flatten_object(schema: dict) -> dict:
    """Flatten object allOf before applying runtime field authority.

    allOf is intersection, not override: appending a runtime schema would retain
    stale constraints for the very same field. Complex unions stay pending until
    the upstream converter can represent them without guessing precedence.
    """
    if not isinstance(schema, dict) or schema.get("type", "object") != "object":
        raise ValueError("mixed body requires an object schema")
    if any(key in schema for key in ("oneOf", "anyOf", "not", "if", "then", "else", "dependentSchemas", "dependentRequired", "patternProperties")):
        raise ValueError("mixed upstream object has unsupported conditional constraints")
    result = {k: copy.deepcopy(v) for k, v in schema.items() if k != "allOf"}
    props = result.setdefault("properties", {})
    required = set(result.pop("required", []))
    for branch in schema.get("allOf", []):
        part = flatten_object(branch)
        for name, field in part.pop("properties", {}).items():
            if name in props and props[name] != field:
                raise ValueError("upstream allOf has conflicting property constraints")
            props[name] = field
        required.update(part.pop("required", []))
        for key, value in part.items():
            if key in result and result[key] != value:
                raise ValueError(f"upstream allOf has incompatible {key}")
            result[key] = value
    if required:
        result["required"] = sorted(required)
    return result


def merge_object(upstream: dict, declared: dict) -> dict:
    merged = flatten_object(upstream)
    names = set(declared.get("properties", {}))
    required = (set(merged.get("required", [])) - names) | set(declared.get("required", []))
    for name, value in declared.get("properties", {}).items():
        original = merged.setdefault("properties", {}).get(name, {})
        if value.get("properties") and isinstance(original, dict) and original.get("type", "object") == "object":
            merged["properties"][name] = merge_object(original, value)
        else:
            merged["properties"][name] = copy.deepcopy(value)
    merged.pop("required", None)
    if required:
        merged["required"] = sorted(required)
    for key, value in declared.items():
        if key not in {"properties", "required", "additionalProperties", "type"}:
            merged[key] = copy.deepcopy(value)
    return merged


def merge_body(upstream: dict, runtime: dict) -> dict:
    if not runtime:
        return copy.deepcopy(upstream)
    if not upstream:
        raise ValueError("mixed body missing upstream requestBody")
    result = copy.deepcopy(upstream)
    result["required"] = bool(upstream.get("required") or runtime.get("required"))
    for media, contract in runtime.get("content", {}).items():
        original = result.get("content", {}).get(media)
        if original is None:
            raise ValueError(f"mixed body missing upstream media type {media}")
        declared = contract.get("schema", {})
        if not declared.get("properties"):
            continue
        original["schema"] = merge_object(original.get("schema", {}), declared)
        # Upstream request examples describe the complete body. Runtime examples
        # only cover declared fields and must not replace the complete example.
    return result


def has_response_contract(response: dict) -> bool:
    return any(
        media.get("schema") or "example" in media or "examples" in media
        for media in response.get("content", {}).values()
        if isinstance(media, dict)
    )


def published_success_responses(previous: dict | None, output: dict | None = None) -> dict:
    """Read only documented success payloads; never inherit errors or auth.

    References are resolved against the published source before extracting the
    response contract, so old component names cannot collide with runtime ones.
    The retained payload is content-addressed and feeds document_hash below.
    """
    result = {}
    if not previous:
        return result
    prefix = urlsplit((previous.get("servers") or [{"url": ""}])[0]["url"]).path.rstrip("/")
    for path, path_item in previous.get("paths", {}).items():
        for method, operation in path_item.items():
            if method not in METHODS:
                continue
            operation_id = operation.get("operationId")
            if not operation_id:
                continue
            responses = {}
            for status, response in operation.get("responses", {}).items():
                if not re.fullmatch(r"2(?:[0-9]{2}|XX)", str(status)):
                    continue
                resolved = resolve_fragment(response, previous, output, "published_responses.json") if output is not None else resolve(response, previous)
                if has_response_contract(resolved):
                    # Do not copy legacy headers/links: runtime owns protocol.
                    responses[str(status)] = {
                        "description": resolved.get("description", "Successful response"),
                        "content": copy.deepcopy(resolved["content"]),
                    }
            if responses:
                identity = (prefix + path, method, operation_id)
                if identity in result:
                    raise IdentityError(f"duplicate published response identity: {operation_id}")
                result[identity] = responses
    return result


def compose(facts: dict, upstream: dict | None = None, overlay: dict | None = None,
            previous: dict | None = None, public_mirrors: dict | None = None) -> tuple[dict, list]:
    overlay = overlay or {}
    validate_overlay(overlay)
    if not isinstance(facts.get("paths"), dict) or not facts.get("openapi", "").startswith("3.1"):
        raise ValueError("runtime facts must be OpenAPI 3.1")
    meta = facts.get("info", {}).get("x-aisa-document", {})
    if not meta.get("facts_hash"):
        raise ValueError("runtime facts missing facts_hash")
    source = (upstream or {}).get("info", {}).get("x-aisa-source", {})
    if upstream and (source.get("kind") not in {"manual", "provider_openapi"} or not all(source.get(k) for k in ("url", "fetched_at", "content_hash", "converter"))):
        raise ValueError("upstream mirror requires complete x-aisa-source provenance")
    output = copy.deepcopy(facts)
    output["paths"] = {}
    pending: list[dict] = []
    published_responses = published_success_responses(previous, output)
    retained_responses = {}
    facts_prefix = urlsplit((facts.get("servers") or [{"url": ""}])[0]["url"]).path.rstrip("/")
    public_mirrors = public_mirrors or {}
    used_mirrors = {}
    published_ids = {}
    previous_prefix = urlsplit(((previous or {}).get("servers") or [{"url": ""}])[0]["url"]).path.rstrip("/")
    for old_path, old_item in (previous or {}).get("paths", {}).items():
        for old_method, old_op in old_item.items():
            if old_method in METHODS:
                published_ids[(previous_prefix + old_path, old_method)] = old_op.get("operationId")
    ids: set[str] = set()
    auth_names = {"authorization", "x-api-key", "api-key"}
    for scheme in (upstream or {}).get("components", {}).get("securitySchemes", {}).values():
        if scheme.get("name"):
            auth_names.add(scheme["name"].lower())
    for path, path_item in sorted(facts["paths"].items()):
        for method, runtime in sorted(path_item.items()):
            if method not in METHODS and method != "x-aisa-any":
                continue
            base_id = runtime.get("operationId")
            if not base_id or runtime.get("x-aisa-status") not in {"enabled", "disabled"}:
                raise ValueError("runtime operation requires immutable operationId and status")
            validation = runtime.get("x-aisa-validation")
            if validation not in {"runtime", "provider", "mixed"}:
                raise ValueError("runtime operation has unknown validation boundary")
            upstream_item = (upstream or {}).get("paths", {}).get(runtime.get("x-aisa-upstream-path"), {})
            public_path = facts_prefix + path
            methods = sorted((set(upstream_item) & METHODS) | {m for p, m in public_mirrors if p == public_path}) if method == "x-aisa-any" else [method]
            if not methods:
                pending.append({"operation_id": base_id, "path": path, "method": "ANY", "reason": "upstream operation missing"})
            for actual_method in methods:
                try:
                    mirror = {}
                    operation_source = source
                    if validation != "runtime" or method == "x-aisa-any":
                        if upstream and actual_method in upstream_item:
                            request_fields = {k: v for k, v in upstream_item[actual_method].items() if k in {"operationId", "summary", "description", "parameters", "requestBody"}}
                            request_fields["parameters"] = upstream_item.get("parameters", []) + request_fields.get("parameters", [])
                            mirror = resolve_fragment(request_fields, upstream, output, "provider_" + digest(source)[7:19] + ".json")
                        elif (public_path, actual_method) in public_mirrors:
                            selected = public_mirrors[(public_path, actual_method)]
                            mirror = copy.deepcopy(selected["operation"])
                            operation_source = selected["source"]
                            used_mirrors[f"{actual_method} {public_path}"] = selected
                            if mirror.get("x-aisa-mirror-error"):
                                raise ValueError(mirror["x-aisa-mirror-error"])
                            mirror = resolve_fragment(mirror, {"components": selected.get("components", {})}, output, "manual_" + digest(operation_source)[7:19] + ".json")
                        else:
                            raise ValueError("upstream operation missing")
                    operation = copy.deepcopy(runtime)
                    if method == "x-aisa-any":
                        published_id = published_ids.get((public_path, actual_method))
                        if not published_id and operation_source.get("path_space") == "public":
                            published_id = mirror.get("operationId")
                        if published_id:
                            operation["operationId"] = published_id
                        elif len(methods) > 1:
                            candidate = f"{actual_method}_{base_id}"
                            operation["operationId"] = candidate if len(candidate) <= 56 else candidate[:49] + "_" + hashlib.sha256(f"{actual_method} {public_path}".encode()).hexdigest()[:6]
                    if validation != "runtime":
                        runtime_fields = {(p["in"], p["name"]) for p in runtime.get("parameters", [])}
                        query_passthrough = runtime.get("x-aisa-query-policy", {}).get("request_wins", False)
                        parameters = {
                            (p["in"], p["name"]): p for p in mirror.get("parameters", [])
                            if p.get("name", "").lower() not in auth_names
                            and (p.get("in") != "query" or query_passthrough or (p["in"], p["name"]) in runtime_fields)
                        }
                        parameters.update({(p["in"], p["name"]): copy.deepcopy(p) for p in runtime.get("parameters", [])})
                        if parameters:
                            operation["parameters"] = [parameters[k] for k in sorted(parameters)]
                        if mirror.get("requestBody") or runtime.get("requestBody"):
                            operation["requestBody"] = merge_body(mirror.get("requestBody", {}), runtime.get("requestBody", {}))
                        operation["x-aisa-source"] = copy.deepcopy(operation_source)
                    editorial = overlay.get(operation["operationId"], overlay.get(base_id, {}))
                    description = editorial.get("description") or runtime.get("description") or mirror.get("description")
                    if description:
                        operation["description"] = description
                    notes = editorial.get("x-aisa-notes", [])
                    if notes:
                        operation["x-aisa-notes"] = copy.deepcopy(notes)
                        constraints = operation.setdefault("x-aisa-constraints", {})
                        if not isinstance(constraints, dict):
                            raise ValueError("runtime constraints must be an object")
                        runtime_notes = constraints.get("notes", [])
                        if not isinstance(runtime_notes, list) or not all(isinstance(note, str) for note in runtime_notes):
                            raise ValueError("runtime constraint notes must be a list of text")
                        constraints["notes"] = list(dict.fromkeys([*runtime_notes, *notes]))
                    operation_id = operation["operationId"]
                    retained = {}
                    response_identity = (facts_prefix + path, actual_method, operation_id)
                    for status, response in published_responses.get(response_identity, {}).items():
                        runtime_response = operation.setdefault("responses", {}).get(status, {})
                        if not has_response_contract(runtime_response):
                            effective = copy.deepcopy(runtime_response)
                            effective["content"] = copy.deepcopy(response["content"])
                            if effective.get("description") in (None, "Success", "Successful response"):
                                effective["description"] = response["description"]
                            operation["responses"][status] = effective
                            retained[status] = {"description": effective["description"], "content": effective["content"]}
                    if retained:
                        retained_responses[operation_id] = retained
                        operation["x-aisa-response-source"] = {
                            "kind": "published_success_contract",
                            "content_hash": digest(retained),
                        }
                    if operation_id[:56] in ids:
                        raise IdentityError(f"operationId prefix collision: {operation_id}")
                    ids.add(operation_id[:56])
                    output["paths"].setdefault(path, {})[actual_method] = operation
                except IdentityError:
                    raise
                except (ValueError, KeyError, TypeError) as exc:
                    pending.append({"operation_id": base_id, "path": path, "method": actual_method.upper(), "reason": str(exc)})
    document_meta = output["info"]["x-aisa-document"]
    document_meta["composer_version"] = VERSION
    document_meta["document_hash"] = digest({"facts_hash": meta["facts_hash"], "upstream": upstream, "overlay": overlay, "composer_version": VERSION, "published_success_responses": retained_responses, "public_mirrors": used_mirrors})
    return output, pending
