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
from urllib.parse import urlsplit, unquote

VERSION = "11"
METHODS = frozenset({"get", "put", "post", "delete", "patch", "options", "head", "trace"})
OVERLAY_KEYS = {"description", "x-aisa-notes"}
SCHEMA_ANNOTATIONS = {"description", "summary", "title", "example", "examples", "deprecated", "readOnly", "writeOnly"}
INSTANCE_FIELDS = {"example", "default", "enum", "const", "value"}
NAMED_CONTRACT_MAPS = {"properties", "patternProperties", "$defs", "definitions", "dependentSchemas", "schemas", "responses",
                      "headers", "parameters", "requestBodies", "securitySchemes", "examples", "links", "callbacks"}
# SDK code-generation overrides do not describe the public wire contract. Some
# consumers inspect references inside them, although OpenAPI validators ignore
# them. Keep the original in the upstream mirror, not the public projection.
NON_PUBLIC_EXTENSIONS = {"x-stainless-override-schema"}


def map_contract_children(node: dict, transform) -> dict:
    """Walk declarations without interpreting reference-shaped JSON instances."""
    result = {}
    for key, child in node.items():
        if key in NON_PUBLIC_EXTENSIONS:
            continue
        if key in INSTANCE_FIELDS or key.startswith("x-") or (key == "examples" and isinstance(child, list)):
            result[key] = copy.deepcopy(child)
        elif key == 'links' and isinstance(child, dict):
            links = {}
            for name, link in child.items():
                if isinstance(link, dict):
                    data = {k: copy.deepcopy(v) for k, v in link.items() if k in {'parameters', 'requestBody'}}
                    transformed = transform({k: v for k, v in link.items() if k not in data})
                    links[name] = {**transformed, **data} if isinstance(transformed, dict) else transformed
                else:
                    links[name] = transform(link)
            result[key] = links
        elif key in NAMED_CONTRACT_MAPS and isinstance(child, dict):
            result[key] = {name: transform(definition) for name, definition in child.items()}
        else:
            result[key] = transform(child)
    return result


class IdentityError(ValueError):
    pass


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def parameter_wire_default(parameter: dict) -> dict:
    """Normalize scalar URL/header defaults to their declared string wire type.

    Historic provider mirrors sometimes give a boolean or numeric default for
    a string parameter. HTTP serializes those scalars as text; body defaults
    and complex parameter values must not be coerced this way.
    """
    result = copy.deepcopy(parameter)
    schema = result.get("schema", {})
    if not isinstance(schema, dict):
        return result
    default = schema.get("default")
    if result.get("in") in {"query", "path", "header"} and schema.get("type") == "string" and isinstance(default, (bool, int, float)):
        schema["default"] = json.dumps(default, separators=(",", ":"), allow_nan=False)
    return result


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


def pointer_target(document: dict, ref: str) -> Any:
    if not isinstance(ref, str) or not ref.startswith("#/"):
        raise ValueError("unsupported external contract reference")
    target: Any = document
    for token in unquote(ref[2:]).split("/"):
        part = token.replace("~1", "/").replace("~0", "~")
        if isinstance(target, list):
            if not part.isdigit() or int(part) >= len(target):
                raise ValueError("unresolved contract reference: " + ref)
            target = target[int(part)]
        elif isinstance(target, dict) and part in target:
            target = target[part]
        else:
            raise ValueError("unresolved contract reference: " + ref)
    return target


def effective_object(value: dict, document: dict) -> dict:
    """Dereference an OpenAPI object without expanding its nested schemas."""
    if not isinstance(value, dict):
        raise ValueError("invalid public object declaration")
    result = copy.deepcopy(value)
    seen = set()
    while "$ref" in result:
        ref = result["$ref"]
        if ref in seen:
            raise ValueError("recursive public object reference: " + str(ref))
        seen.add(ref)
        target = pointer_target(document, ref)
        if not isinstance(target, dict):
            raise ValueError("public object reference must target an object")
        path_item = ref.startswith(('#/paths/', '#/components/pathItems/'))
        siblings = {k: v for k, v in result.items() if k != '$ref'} if path_item else (
            {} if document.get('openapi', '').startswith('3.0.') else
            {k: v for k, v in result.items() if k in {'summary', 'description'}})
        result = {**copy.deepcopy(target), **siblings}
    return result


def effective_parameters(path_item: dict, operation: dict, document: dict) -> list:
    """Operation parameters override Path Item parameters only at (in, name)."""
    selected = {}
    for raw in [*path_item.get("parameters", []), *operation.get("parameters", [])]:
        parameter = effective_object(raw, document)
        if not isinstance(parameter.get("name"), str) or parameter.get("in") not in {"path", "query", "header", "cookie"}:
            raise ValueError("parameter requires a declared name and location")
        selected[(parameter["in"], parameter["name"])] = parameter
    return list(selected.values())


def effective_public_operation(path_item: dict, operation: dict, document: dict) -> dict:
    result = copy.deepcopy(operation)
    parameters = effective_parameters(path_item, operation, document)
    if parameters or "parameters" in operation:
        result["parameters"] = parameters
    # Public servers/security remain at their declared scope. compose retains
    # the authoritative root and Path Item context, so inheritance remains exact
    # without injecting redundant operation fields into legacy public output.
    return result


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
        target = pointer_target(document, ref)
        if ref.startswith('#/components/links/'):
            target = map_contract_children({'links': {'target': target}},
                lambda child: resolve(child, document, stack + (ref,), preserve_recursive))['links']['target']
        else:
            target = resolve(target, document, stack + (ref,), preserve_recursive)
        siblings = map_contract_children({k: v for k, v in value.items() if k != "$ref"},
                                        lambda child: resolve(child, document, stack, preserve_recursive))
        if siblings:
            if ref.startswith("#/components/schemas/"):
                annotations = {k: v for k, v in siblings.items() if k in SCHEMA_ANNOTATIONS}
                constraints = {k: v for k, v in siblings.items() if k not in SCHEMA_ANNOTATIONS}
                if any(k in constraints for k in ("$id", "$schema", "$anchor", "$dynamicRef", "$dynamicAnchor")):
                    raise ValueError("unsupported upstream schema reference scope sibling")
                if constraints:
                    # JSON Schema ref siblings intersect; merging would discard
                    # limits, required fields or properties from either branch.
                    target = {"allOf": [target, constraints], **annotations}
                elif isinstance(target, dict):
                    target = {**target, **annotations}
                else:
                    target = {"allOf": [target], **annotations}
            else:
                if not isinstance(target, dict) or set(siblings) - {"description", "summary"}:
                    raise ValueError("upstream non-schema reference has incompatible siblings")
                target = {**target, **siblings}
        return target
    return map_contract_children(value, lambda child: resolve(child, document, stack, preserve_recursive))


def upstream_path_item(document: dict | None, upstream_path: str | None) -> dict:
    """Match literal or server-prefixed upstream paths without guessing prefixes."""
    if not document or not upstream_path:
        return {}
    selected = {}
    origins = {}
    for path, raw_item in document.get("paths", {}).items():
        # Selection only reads unmatched Path Items. Copying every operation
        # before matching made a full-catalog scan repeatedly clone the entire
        # supplier graph. Referenced items still need materialization.
        item = effective_object(raw_item, document) if '$ref' in raw_item else raw_item
        for method, operation in item.items():
            if method not in METHODS:
                continue
            servers = operation.get("servers", item.get("servers", document.get("servers", [])))
            effective_paths = {path}
            for server in servers or [{"url": "/"}]:
                prefix = urlsplit(server.get("url", "/")).path
                for name in re.findall(r"\{([^{}]+)\}", prefix):
                    default = server.get("variables", {}).get(name, {}).get("default")
                    if default is None:
                        # The literal path remains usable, but do not guess a
                        # variable server prefix from the caller's path.
                        prefix = None
                        break
                    prefix = prefix.replace("{" + name + "}", str(default))
                if prefix is not None:
                    effective_paths.add(prefix.rstrip("/") + path)
            if upstream_path not in effective_paths:
                continue
            if method in selected and origins[method] != path:
                raise ValueError("ambiguous upstream server-path operation")
            origins[method] = path
            selected[method] = {**copy.deepcopy(operation), "parameters": effective_parameters(item, operation, document)}
    return selected


def selector_value(selector):
    if not isinstance(selector, dict) or set(selector) != {"in", "name", "value", "mode"} or selector.get("in") != "query" or selector.get("name") != "engine" or selector.get("mode") not in {"fixed", "default"} or not isinstance(selector.get("value"), str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", selector["value"]):
        raise ValueError("invalid public upstream selector")
    return selector["value"]


def select_upstream_operations(sources, path, selector=None):
    """Keep source documents separate; select only matching official engine enums."""
    value = selector_value(selector) if selector is not None else None
    selected = {}
    for document in sources:
        for method, operation in upstream_path_item(document, path).items():
            if value is not None:
                parameters = [resolve(p, document) for p in operation.get("parameters", [])]
                candidates = [p for p in parameters if p.get("in") == "query" and p.get("name") == selector["name"]]
                if len(candidates) != 1:
                    continue
                schema = resolve(candidates[0].get("schema", {}), document)
                if not isinstance(schema, dict):
                    continue
                choices = [schema["const"]] if "const" in schema else schema.get("enum")
                if not isinstance(choices, list) or value not in choices:
                    continue
            if method in selected:
                raise ValueError("ambiguous upstream source for path and selector")
            selected[method] = (document, operation)
    return selected


def apply_upstream_selector(mirror, selector):
    if selector is None:
        return mirror
    value = selector_value(selector)
    result = copy.deepcopy(mirror)
    for parameter in list(result.get("parameters", [])):
        if parameter.get("in") != "query" or parameter.get("name") != selector["name"]:
            continue
        if selector["mode"] == "fixed":
            result["parameters"].remove(parameter)
        else:
            parameter["required"] = False
            # The transport allows another engine; the selected reference only
            # documents fields for the configured default, not other engines.
            parameter["schema"] = {"type": "string", "default": value}
            parameter["description"] = "Defaults to the endpoint's configured engine. The caller may override it; parameter contracts for other engines are not guaranteed by this document."
    return result


def referenced_components(value: Any, document: dict) -> dict:
    """Collect the finite reachable component graph without expanding cycles."""
    components = {}
    seen = set()
    openapi30 = document.get("openapi", "").startswith("3.0.")
    def visit(node):
        if isinstance(node, list):
            for item in node:
                visit(item)
        elif isinstance(node, dict):
            if '$dynamicRef' in node or '$recursiveRef' in node:
                raise ValueError('unsupported upstream dynamic reference scope')
            for mapped in node.get('discriminator', {}).get('mapping', {}).values():
                if not isinstance(mapped, str):
                    raise ValueError('invalid upstream discriminator reference')
                ref = mapped if mapped.startswith(('#', 'https://', 'http://')) else '#/components/schemas/' + mapped.replace('~', '~0').replace('/', '~1')
                visit({'$ref': ref})
            ref = node.get("$ref")
            if ref and ref not in seen:
                if not ref.startswith("#/components/"):
                    raise ValueError("unsupported external or non-component upstream reference")
                pointer_target(document, ref)
                parts = unquote(ref).split("/")
                if len(parts) < 4:
                    raise ValueError("invalid upstream component reference")
                section, name = (part.replace("~1", "/").replace("~0", "~") for part in parts[2:4])
                if section == "securitySchemes":
                    raise ValueError("provider security scheme is not a request schema")
                original = document["components"][section][name]
                definition = original
                if openapi30:
                    definition = schema_30_to_31(definition) if section == "schemas" else fragment_30_to_31(definition)
                seen.add(ref)
                components.setdefault(section, {})[name] = copy.deepcopy(original)
                visit({'links': {'target': definition}} if section == 'links' else definition)
            map_contract_children(node, visit)
    visit(fragment_30_to_31(value) if openapi30 else value)
    return components


def schema_30_to_31(schema: Any) -> Any:
    """Convert Schema Objects, never examples/defaults or property-name maps."""
    if not isinstance(schema, dict):
        return copy.deepcopy(schema)
    # OpenAPI 3.0 Reference Objects ignore siblings, unlike 3.1 schemas.
    if "$ref" in schema:
        return {"$ref": schema["$ref"]}
    result = copy.deepcopy(schema)
    for key in ("properties", "patternProperties", "$defs", "definitions"):
        if isinstance(result.get(key), dict):
            result[key] = {name: schema_30_to_31(child) for name, child in result[key].items()}
    for key in ("items", "additionalProperties", "not"):
        if key in result:
            result[key] = schema_30_to_31(result[key])
    for key in ("allOf", "anyOf", "oneOf"):
        if isinstance(result.get(key), list):
            result[key] = [schema_30_to_31(child) for child in result[key]]
    nullable = result.pop("nullable", False)
    if not isinstance(nullable, bool):
        raise ValueError("unsupported OpenAPI 3.0 nullable declaration")
    if nullable and "type" in result:
        if not isinstance(result["type"], str):
            raise ValueError("unsupported OpenAPI 3.0 type declaration")
        result["type"] = [result["type"], "null"]
    for bound in ("minimum", "maximum"):
        exclusive = "exclusive" + bound.capitalize()
        if exclusive not in result:
            continue
        flag = result.pop(exclusive)
        if not isinstance(flag, bool):
            raise ValueError("unsupported OpenAPI 3.0 exclusive bound")
        if flag:
            if bound not in result:
                raise ValueError("OpenAPI 3.0 exclusive bound is missing its limit")
            result[exclusive] = result.pop(bound)
    return result


def fragment_30_to_31(value: Any) -> Any:
    if isinstance(value, list):
        return [fragment_30_to_31(child) for child in value]
    if not isinstance(value, dict):
        return copy.deepcopy(value)
    result = map_contract_children(value, fragment_30_to_31)
    if "schema" in value:
        result["schema"] = schema_30_to_31(value["schema"])
    return result


def resolve_fragment(value: Any, document: dict, output: dict, namespace: str, preserve_refs: bool = False) -> Any:
    from runtime_consolidate_openapi import component_collision_prefix, merge_components
    selected = {"fragment": copy.deepcopy(value), "components": referenced_components(value, document)}
    if document.get("openapi", "").startswith("3.0."):
        selected["fragment"] = fragment_30_to_31(selected["fragment"])
        selected["components"] = {section: {name: schema_30_to_31(definition) if section == "schemas" else fragment_30_to_31(definition)
                                           for name, definition in entries.items()}
                                  for section, entries in selected["components"].items()}
    # Give the entire reachable graph one stable namespace, so recursive and
    # mutually-dependent definitions cannot capture another source's names.
    prefix = component_collision_prefix(namespace) + "_"
    renamed, target_names = {}, {}
    def escape(part):
        return part.replace("~", "~0").replace("/", "~1")
    for section, entries in selected["components"].items():
        for name in entries:
            target = name if name.startswith(prefix) else prefix + name
            target_names[(section, name)] = target
            renamed[f"#/components/{section}/{escape(name)}"] = f"#/components/{section}/{escape(target)}"
    def rewrite(node):
        if isinstance(node, list):
            return [rewrite(item) for item in node]
        if not isinstance(node, dict):
            return node
        result = map_contract_children(node, rewrite)
        if "$ref" in result:
            ref = result["$ref"]
            if isinstance(ref, str) and ref.startswith("#/components/"):
                parts = unquote(ref[2:]).split("/")
                if len(parts) >= 3:
                    base = "#/" + "/".join(parts[:3])
                    result["$ref"] = renamed.get(base, base) + ("/" + "/".join(parts[3:]) if len(parts) > 3 else "")
        if isinstance(result.get('discriminator'), dict) and isinstance(result['discriminator'].get('mapping'), dict):
            mapping = result['discriminator']['mapping']
            result['discriminator']['mapping'] = {name: rewrite({'$ref': target if target.startswith(('#', 'https://', 'http://')) else '#/components/schemas/' + escape(target)})['$ref']
                for name, target in mapping.items()}
        return result
    selected = rewrite(selected)
    selected["components"] = {section: {target_names[(section, name)]: definition for name, definition in entries.items()} for section, entries in selected["components"].items()}
    output.setdefault("components", {})
    merge_components(output, selected, namespace)
    return selected["fragment"] if preserve_refs else resolve(selected["fragment"], output, preserve_recursive=True)


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
    parts = [flatten_object(branch) for branch in schema.get("allOf", [])]
    if parts:
        all_names = set(props).union(*(set(part.get("properties", {})) for part in parts))
        for part in [schema, *parts]:
            if "unevaluatedProperties" in part:
                raise ValueError("mixed upstream allOf has unsupported unevaluatedProperties")
            if part.get("additionalProperties", True) is not True and set(part.get("properties", {})) != all_names:
                raise ValueError("mixed upstream allOf has branch-local additionalProperties")
    for part in parts:
        for name, field in part.pop("properties", {}).items():
            if name in props and props[name] != field:
                props[name] = {"allOf": [props[name], field]}
            else:
                props[name] = field
        required.update(part.pop("required", []))
        for key, value in part.items():
            if key in result and result[key] != value:
                if key in SCHEMA_ANNOTATIONS:
                    continue
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
    """Schema completeness is distinct from having a payload example to retain."""
    content = response.get("content", {})
    if not isinstance(content, dict):
        return False
    if not content:
        return response.get("x-aisa-no-content") is True
    return all(
        isinstance(media, dict) and isinstance(media.get("schema"), (dict, bool))
        for media in content.values()
    )


def has_response_payload(response: dict) -> bool:
    """Keep examples and partial declarations without claiming schema coverage."""
    content = response.get("content", {})
    return response.get("x-aisa-no-content") is True or isinstance(content, dict) and any(
        "schema" in media or "example" in media or "examples" in media
        for media in content.values()
        if isinstance(media, dict)
    )


def response_object(raw: dict, document: dict) -> dict:
    response, seen = raw, set()
    if not isinstance(response, dict):
        raise ValueError("invalid upstream response declaration")
    while "$ref" in response:
        ref = response["$ref"]
        if not ref.startswith("#/components/responses/") or ref in seen:
            raise ValueError("unsupported upstream response reference")
        seen.add(ref)
        name = ref.rsplit("/", 1)[1].replace("~1", "/").replace("~0", "~")
        response = document.get("components", {}).get("responses", {}).get(name)
        if not isinstance(response, dict):
            raise ValueError("unresolved upstream response reference: " + ref)
    return response


def source_success_responses(operation: dict, document: dict, output: dict, namespace: str, runtime_responses: dict) -> dict:
    """Copy payloads only; runtime owns error envelopes, headers and links."""
    result = {}
    for status, raw in operation.get("responses", {}).items():
        if not re.fullmatch(r"2(?:[0-9]{2}|XX)", str(status)):
            continue
        if has_response_payload(runtime_responses.get(str(status), {})):
            continue
        # Resolve a Response Object first, without importing headers or links.
        response = response_object(raw, document)
        if str(status) in {"204", "205"} and not response.get("content"):
            result[str(status)] = {"description": response.get("description", "No content"), "content": {}, "x-aisa-no-content": True}
            continue
        if has_response_payload(response):
            payload = {"description": response.get("description", "Successful response"),
                       "content": response.get("content", {})}
            if response.get("x-aisa-no-content") is True:
                payload["x-aisa-no-content"] = True
            result[str(status)] = resolve_fragment(payload, document, output, namespace, preserve_refs=True)
    return result


def published_success_responses(previous: dict | None) -> dict:
    """Read only documented success payloads; never inherit errors or auth.

    Response Object references are resolved here. Payload schemas are imported
    lazily only when used, so fresh contracts do not acquire unused old schemas.
    Retained payloads are content-addressed and feed document_hash below.
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
                resolved = response_object(response, previous)
                if has_response_payload(resolved):
                    # Do not copy legacy headers/links: runtime owns protocol.
                    responses[str(status)] = {
                        "description": resolved.get("description", "Successful response"),
                        "content": copy.deepcopy(resolved.get("content", {})),
                    }
                    if resolved.get("x-aisa-no-content") is True:
                        responses[str(status)]["x-aisa-no-content"] = True
            if responses:
                identity = (prefix + path, method, operation_id)
                if identity in result:
                    raise IdentityError(f"duplicate published response identity: {operation_id}")
                result[identity] = responses
    return result


def compose(facts: dict, upstream: dict | None = None, overlay: dict | None = None,
            previous: dict | None = None, public_mirrors: dict | None = None,
            source_bindings: dict | None = None) -> tuple[dict, list]:
    overlay = overlay or {}
    validate_overlay(overlay)
    if not isinstance(facts.get("paths"), dict) or not facts.get("openapi", "").startswith("3.1"):
        raise ValueError("runtime facts must be OpenAPI 3.1")
    meta = facts.get("info", {}).get("x-aisa-document", {})
    if not meta.get("facts_hash"):
        raise ValueError("runtime facts missing facts_hash")
    sources = upstream if isinstance(upstream, list) else ([upstream] if upstream else [])
    for document in sources:
        source = document.get("info", {}).get("x-aisa-source", {})
        if source.get("kind") not in {"manual", "provider_openapi"} or not all(source.get(k) for k in ("url", "fetched_at", "content_hash", "converter")):
            raise ValueError("upstream mirror requires complete x-aisa-source provenance")
    output = copy.deepcopy(facts)
    output["paths"] = {}
    pending: list[dict] = []
    published_responses = published_success_responses(previous)
    retained_responses = {}
    response_gaps = []
    facts_prefix = urlsplit((facts.get("servers") or [{"url": ""}])[0]["url"]).path.rstrip("/")
    public_mirrors = public_mirrors or {}
    source_bindings = source_bindings or {}
    used_mirrors = {}
    published_ids = {}
    previous_prefix = urlsplit(((previous or {}).get("servers") or [{"url": ""}])[0]["url"]).path.rstrip("/")
    for old_path, old_item in (previous or {}).get("paths", {}).items():
        for old_method, old_op in old_item.items():
            if old_method in METHODS:
                published_ids[(previous_prefix + old_path, old_method)] = old_op.get("operationId")
    ids: set[str] = set()
    auth_names = {"authorization", "x-api-key", "api-key"}
    for document in sources:
        for scheme in document.get("components", {}).get("securitySchemes", {}).values():
            if scheme.get("name"):
                auth_names.add(scheme["name"].lower())
    for path, raw_path_item in sorted(facts["paths"].items()):
        path_item = effective_object(raw_path_item, facts)
        public_context = {key: copy.deepcopy(value) for key, value in path_item.items()
                          if key not in METHODS and key not in {"x-aisa-any", "$ref"}}
        for method, runtime in sorted(path_item.items()):
            if method not in METHODS and method != "x-aisa-any":
                continue
            runtime = effective_public_operation(path_item, runtime, facts)
            base_id = runtime.get("operationId")
            if not base_id or runtime.get("x-aisa-status") not in {"enabled", "disabled"}:
                raise ValueError("runtime operation requires immutable operationId and status")
            validation = runtime.get("x-aisa-validation")
            if validation not in {"runtime", "provider", "mixed"}:
                raise ValueError("runtime operation has unknown validation boundary")
            public_path = facts_prefix + path
            bound_source = source_bindings.get(public_path)
            try:
                candidates = sources
                if bound_source:
                    candidates = [source for source in sources if source.get("info", {}).get("x-aisa-source", {}).get("url") == bound_source]
                    if len(candidates) != 1:
                        raise ValueError("public operation source binding must select exactly one locked source")
                upstream_matches = select_upstream_operations(candidates, runtime.get("x-aisa-upstream-path"), runtime.get("x-aisa-upstream-selector")) if validation != "runtime" or method == "x-aisa-any" else {}
                if bound_source and not upstream_matches:
                    raise ValueError("bound source does not match the runtime upstream path and selector")
                upstream_item = {key: value[1] for key, value in upstream_matches.items()}
            except (ValueError, TypeError, KeyError) as exc:
                pending.append({"operation_id": base_id, "path": path, "method": "ANY" if method == "x-aisa-any" else method.upper(), "reason": str(exc)})
                continue
            methods = sorted((set(upstream_item) & METHODS) | {m for p, m in public_mirrors if p == public_path}) if method == "x-aisa-any" else [method]
            if not methods:
                pending.append({"operation_id": base_id, "path": path, "method": "ANY", "reason": "upstream selector has no matching official operation" if runtime.get("x-aisa-upstream-selector") else "upstream operation missing"})
            for actual_method in methods:
                try:
                    mirror = {}
                    operation_source = {}
                    response_operation, response_document = {}, {}
                    if validation != "runtime" or method == "x-aisa-any":
                        if actual_method in upstream_item:
                            selected_document = upstream_matches[actual_method][0]
                            operation_source = selected_document.get("info", {}).get("x-aisa-source", {})
                            request_fields = {k: v for k, v in upstream_item[actual_method].items() if k in {"operationId", "summary", "description", "parameters", "requestBody"}}
                            request_fields["parameters"] = upstream_item.get("parameters", []) + request_fields.get("parameters", [])
                            mirror = resolve_fragment(request_fields, selected_document, output, "provider_" + digest(operation_source)[7:19] + ".json")
                            mirror = apply_upstream_selector(mirror, runtime.get("x-aisa-upstream-selector"))
                            if runtime.get("x-aisa-passthrough") is True:
                                response_operation = upstream_item[actual_method]
                                response_document = selected_document
                        elif (public_path, actual_method) in public_mirrors:
                            selected = public_mirrors[(public_path, actual_method)]
                            mirror = copy.deepcopy(selected["operation"])
                            operation_source = selected["source"]
                            expected_path_hash = operation_source.get("upstream_path_sha256")
                            if expected_path_hash and expected_path_hash != hashlib.sha256(runtime.get("x-aisa-upstream-path", "").encode()).hexdigest():
                                raise ValueError("public mirror upstream binding changed; review its source mapping")
                            used_mirrors[f"{actual_method} {public_path}"] = selected
                            if mirror.get("x-aisa-mirror-error"):
                                raise ValueError(mirror["x-aisa-mirror-error"])
                            mirror = resolve_fragment(mirror, {"openapi": selected.get("openapi", "3.1.0"), "components": selected.get("components", {})}, output, "manual_" + digest(operation_source)[7:19] + ".json")
                            response_operation = selected.get("response_operation", {})
                            response_document = {"openapi": selected.get("openapi", "3.1.0"), "components": selected.get("response_components", {})}
                        else:
                            raise ValueError("upstream operation missing")
                    operation = copy.deepcopy(runtime)
                    if runtime.get("x-aisa-identity-source") == "derived":
                        established_id = published_ids.get((public_path, actual_method))
                        if established_id:
                            operation["operationId"] = established_id
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
                        if bound_source and not runtime.get("x-aisa-upstream-selector"):
                            for parameter in mirror.get("parameters", []):
                                if parameter.get("in") == "query" and parameter.get("required") and isinstance(parameter.get("schema"), dict) and "default" in parameter["schema"]:
                                    # Required provider arguments are caller inputs, not
                                    # transport defaults. Keep the suggested value as an example.
                                    value = parameter["schema"].pop("default")
                                    parameter.setdefault("example", value)
                        if bound_source and not query_passthrough and any(p.get("in") == "query" and p.get("required") and (p["in"], p["name"]) not in runtime_fields for p in mirror.get("parameters", [])):
                            raise ValueError("bound source requires query parameters that runtime does not forward")
                        parameters = {
                            (p["in"], p["name"]): p for p in mirror.get("parameters", [])
                            if p.get("name", "").lower() not in auth_names
                            and (p.get("in") != "query" or query_passthrough or (p["in"], p["name"]) in runtime_fields)
                        }
                        parameters.update({(p["in"], p["name"]): copy.deepcopy(p) for p in runtime.get("parameters", [])})
                        if parameters:
                            operation["parameters"] = [parameter_wire_default(parameters[k]) for k in sorted(parameters)]
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
                    fresh = {}
                    response_error = None
                    try:
                        fresh = source_success_responses(response_operation, response_document, output, "response_" + digest(operation_source)[7:19] + ".json", runtime.get("responses", {}))
                    except (ValueError, KeyError, TypeError) as exc:
                        response_error = str(exc)
                    source_payloads = {}
                    response_identity = (facts_prefix + path, actual_method, operation_id)
                    old_responses = published_responses.get(response_identity, {})
                    if fresh and "200" not in fresh and runtime.get("x-aisa-passthrough") is True and not has_response_payload(operation.get("responses", {}).get("200", {})):
                        operation.get("responses", {}).pop("200", None)
                        old_responses = {status: response for status, response in old_responses.items() if status != "200"}
                    for status in sorted(set(old_responses) | set(fresh)):
                        response = fresh.get(status, old_responses.get(status))
                        runtime_response = operation.setdefault("responses", {}).get(status, {})
                        if not has_response_payload(runtime_response):
                            if status not in fresh:
                                response = resolve_fragment(response, previous, output, "published_responses.json", preserve_refs=True)
                            effective = copy.deepcopy(runtime_response)
                            effective["content"] = copy.deepcopy(response["content"])
                            if effective.get("description") in (None, "Success", "Successful response"):
                                effective["description"] = response["description"]
                            operation["responses"][status] = effective
                            if response.get("x-aisa-no-content") is True:
                                effective["x-aisa-no-content"] = True
                            payload = {"description": effective["description"], "content": effective["content"]}
                            if status in fresh:
                                source_payloads[status] = payload
                            else:
                                retained[status] = payload
                    if source_payloads:
                        operation["x-aisa-response-source"] = {"kind": "upstream_success_contract", "source": copy.deepcopy(operation_source),
                                                               "content_hash": digest(source_payloads)}
                    if retained:
                        retained_responses[operation_id] = retained
                        operation.setdefault("x-aisa-response-source", {
                            "kind": "published_success_contract",
                            "content_hash": digest(retained),
                        })
                    unknown = [str(status) for status, response in operation.get("responses", {}).items()
                               if re.fullmatch(r"2(?:[0-9]{2}|XX)", str(status))
                               and not (str(status) in {"204", "205"} and not response.get("content"))
                               and not has_response_contract(response)]
                    if unknown or response_error:
                        gap = {"operation_id": operation_id, "path": path, "method": actual_method.upper(),
                               "statuses": unknown, "reason": response_error or "public success response has no authoritative payload declaration"}
                        response_gaps.append(gap)
                        operation["x-aisa-response-pending"] = copy.deepcopy(gap)
                    if operation_id in ids:
                        raise IdentityError(f"duplicate operationId: {operation_id}")
                    ids.add(operation_id)
                    output["paths"].setdefault(path, copy.deepcopy(public_context))[actual_method] = operation
                except IdentityError:
                    raise
                except (ValueError, KeyError, TypeError) as exc:
                    pending.append({"operation_id": base_id, "path": path, "method": actual_method.upper(), "reason": str(exc)})
    document_meta = output["info"]["x-aisa-document"]
    document_meta["composer_version"] = VERSION
    document_meta["response_pending"] = response_gaps
    document_meta["document_hash"] = digest({"facts_hash": meta["facts_hash"], "upstream": upstream, "overlay": overlay, "composer_version": VERSION, "published_success_responses": retained_responses, "public_mirrors": used_mirrors, "source_bindings": source_bindings})
    return output, pending
