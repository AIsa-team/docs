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
from upstream_auth_transports import server_auth_headers, request_auth_headers
from urllib.parse import urlsplit, unquote

VERSION = "31"
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


def descriptive_text(editorial, runtime, mirror):
    """Static prose explains the API; runtime declarations still own its behavior."""
    if editorial.get("description"):
        return editorial["description"]
    parts = [mirror.get("description"), runtime.get("description")]
    parts = [text.strip() for text in parts if isinstance(text, str) and text.strip()
             and text.strip() != runtime.get("summary", "").strip()]
    return "\n\n".join(dict.fromkeys(parts)) or runtime.get("description")


def apply_observed_responses(operation):
    """Fill missing schemas from immutable runtime evidence, never from local samples.

    Reviewed/owned payloads win. Observed shapes are explicitly partial and cannot
    assert required fields, enums, formats, bounds or production example values.
    """
    observations = operation.get("x-aisa-observed-responses", {})
    if not isinstance(observations, dict):
        raise ValueError("invalid observed response facts")
    applied = []
    for status, observation in observations.items():
        if (not re.fullmatch(r"2[0-9]{2}", status) or not isinstance(observation, dict)
                or set(observation) != {"schema", "completeness", "last_observed", "origins"}
                or observation["completeness"] != "observed"):
            raise ValueError("invalid observed response facts")
        def validate_shape(schema, depth=0):
            if (not isinstance(schema, dict) or depth > 13
                    or set(schema) - {"type", "properties", "items", "additionalProperties"}):
                raise ValueError("observed responses must contain only structural facts")
            if schema.get("additionalProperties", True) is not True:
                raise ValueError("observed objects must stay open")
            for name, child in schema.get("properties", {}).items():
                if not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$-]{0,63}", name):
                    raise ValueError("invalid observed response property")
                validate_shape(child, depth + 1)
            if "items" in schema:
                validate_shape(schema["items"], depth + 1)
        validate_shape(observation["schema"])
        response = operation.setdefault("responses", {}).setdefault(status, {"description": "Successful response"})
        # A declared empty object/array is still an official schema. Observations
        # remain available in the extension, but never rewrite that declaration.
        if has_response_payload(response):
            continue
        response["content"] = {"application/json": {"schema": copy.deepcopy(observation["schema"])}}
        response["description"] = ("Observed successful JSON response. This partial structure comes from successful "
                                   "probe or sampled requests; fields and types may vary. No field is guaranteed "
                                   "to be present. Last observed: " + observation["last_observed"] + ".")
        response["x-aisa-response-observation"] = {k: copy.deepcopy(v) for k, v in observation.items() if k != "schema"}
        applied.append(status)
    return applied


def validate_payment_capabilities(operation: dict) -> None:
    """Keep optional Runtime payment method declarations closed and exact.

    Missing declarations retain the historical facts behavior. Method lists
    restrict an existing true capability; they never enable a payment surface.
    """
    if "x-aisa-capabilities" not in operation:
        return
    capabilities = operation["x-aisa-capabilities"]
    # Go code-owned descriptors with no capabilities serialize a nil map.
    if capabilities is None and operation.get("x-aisa-contract-source") == "handler":
        return
    # Code-owned handlers publish scope/shape identity in this same Runtime
    # envelope. Preserve it without interpreting it as payment enablement.
    text_fields = {"max_price", "idempotency", "capability", "required_scope",
                   "publish_scope", "scope_rule", "shape"}
    allowed = {"mpp", "mpp_methods", "x402", "x402_methods", "quote"} | text_fields
    if not isinstance(capabilities, dict) or set(capabilities) - allowed:
        raise ValueError("invalid runtime payment capabilities")
    for name in ("mpp", "x402"):
        if name in capabilities and type(capabilities[name]) is not bool:
            raise ValueError("runtime payment capability must be boolean")
        field = name + "_methods"
        if field in capabilities:
            methods = capabilities[field]
            if (not isinstance(methods, list) or len(methods) > len(METHODS)
                    or any(type(method) is not str or method.lower() not in METHODS
                           or method != method.upper() for method in methods)
                    or len(set(methods)) != len(methods)):
                raise ValueError("invalid runtime payment method declaration")
    for name in text_fields:
        if name in capabilities and not isinstance(capabilities[name], str):
            raise ValueError("invalid runtime payment capability text")
    if "quote" in capabilities:
        quote = capabilities["quote"]
        if (not isinstance(quote, dict)
                or set(quote) - {"header", "value", "supported", "reason", "endpoint"}
                or any(name in quote and not isinstance(quote[name], str)
                       for name in ("header", "value", "reason", "endpoint"))
                or "supported" in quote and type(quote["supported"]) is not bool):
            raise ValueError("invalid runtime quote capability")


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



def effective_security(operation: dict, document: dict) -> tuple[dict, list[str]]:
    """Resolve effective auth; retain only the established disabled legacy debt."""
    requirements = operation.get("security", document.get("security", []))
    if not isinstance(requirements, list):
        raise ValueError("invalid public security requirements")
    schemes = document.get("components", {}).get("securitySchemes", {})
    if not isinstance(schemes, dict):
        raise ValueError("invalid public security schemes")
    selected, missing = {}, []
    for requirement in requirements:
        if not isinstance(requirement, dict):
            raise ValueError("invalid public security requirement")
        for name, scopes in requirement.items():
            if not isinstance(scopes, list) or any(not isinstance(scope, str) for scope in scopes):
                raise ValueError("invalid public security scopes")
            scheme = schemes.get(name)
            if scheme is None:
                if operation.get("x-aisa-status") == "disabled" and operation.get("x-aisa-contract-state") == "retained_legacy":
                    missing.append(name)
                    continue
                raise ValueError("unresolved request security scheme: " + name)
            selected[name] = effective_object(scheme, document)
    return selected, missing


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
    if 'x-aisa-request-auth' in operation:
        # Do not let normal OpenAPI parameter merging erase ambiguous credential declarations.
        for scope in (path_item, operation):
            seen = set()
            for raw in scope.get('parameters', []):
                parameter = effective_object(raw, document)
                name = parameter.get('name', '').lower()
                if parameter.get('in') == 'header' and name in {'relayer_api_key', 'relayer_api_key_address'}:
                    if name in seen:
                        raise ValueError('duplicate caller-auth parameter')
                    seen.add(name)
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
                # Different pointers into one component's $defs share the same
                # finite component graph. Validate every pointer above, but walk
                # the complete component only once, including recursive schemas.
                if name not in components.get(section, {}):
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


def retain_source_annotations(declared: dict, source: dict) -> dict:
    """Runtime owns constraints; missing descriptive annotations retain their source."""
    result = copy.deepcopy(declared)
    runtime_values = declared.get("schema", declared)
    source_values = source.get("schema", source)
    for key in ("description", "summary", "title"):
        if key not in result and key in source:
            annotation = copy.deepcopy(source[key])
            if (isinstance(annotation, str) and isinstance(runtime_values, dict) and isinstance(source_values, dict)
                    and "default" in runtime_values and "default" in source_values
                    and runtime_values["default"] != source_values["default"]
                    and isinstance(source_values["default"], (str, int, float, bool))
                    and isinstance(runtime_values["default"], (str, int, float, bool))):
                # The source's usage guidance is useful, but its explicitly
                # labelled default must follow the public Runtime declaration.
                before = str(source_values["default"])
                value = runtime_values["default"]
                after = value if isinstance(value, str) else json.dumps(value)
                annotation = re.sub(r'(\bdefault(?: value)?(?: is| of|:)?\s+)' + re.escape(before) + r'(?![\w.])',
                                    lambda match: match[1] + after, annotation, flags=re.I)
            result[key] = annotation
    # Different wire types can legitimately need different examples. A source
    # suggestion never becomes a Runtime default or changes requiredness.
    same_type = "type" in declared and source.get("type") == declared["type"]
    integer_example = (declared.get("type") == "integer" and source.get("type") == "number"
                       and isinstance(source.get("example"), int) and not isinstance(source["example"], bool))
    ignored = SCHEMA_ANNOTATIONS | {"default"}
    source_constraints = {key: value for key, value in source.items() if key not in ignored}
    runtime_constraints = {key: value for key, value in declared.items() if key not in ignored}
    if integer_example:
        source_constraints["type"] = "integer"
    # Same type alone cannot prove an example respects a narrower bound or enum.
    # Keep uncertain examples out rather than adding a second schema validator.
    if (same_type or integer_example) and source_constraints == runtime_constraints:
        for key in ("example", "examples"):
            if key not in result and key in source and (same_type or key == "example"):
                result[key] = copy.deepcopy(source[key])
    return result


def retain_provider_parameter_guidance(parameter: dict, source: dict) -> dict:
    """Present missing supplier restrictions without inventing Runtime validation.

    A query value may intentionally use a Runtime string schema while the
    supplier describes an integer/date. Reattaching JSON Schema bounds or
    defaults would change the Runtime contract or constrain the wrong type.
    Keep that supplier declaration in the field's visible guidance instead.
    """
    declared, upstream = parameter.get('schema'), source.get('schema')
    if not isinstance(declared, dict) or not isinstance(upstream, dict):
        return parameter
    keys = ('enum', 'const', 'default', 'format', 'minimum', 'maximum',
            'exclusiveMinimum', 'exclusiveMaximum', 'multipleOf', 'pattern',
            'minLength', 'maxLength', 'minItems', 'maxItems', 'uniqueItems')
    missing = {key: copy.deepcopy(upstream[key]) for key in keys
               if key in upstream and key not in declared}
    if not missing:
        return parameter
    if 'type' in upstream:
        missing = {'type': copy.deepcopy(upstream['type']), **missing}
    note = 'Provider reference (supplier schema): `' + json.dumps(
        missing, sort_keys=True, ensure_ascii=False, separators=(',', ':')) + '`.'
    result = copy.deepcopy(parameter)
    description = result.get('description') or declared.get('description') or ''
    if note in description:
        return result
    result['description'] = description.rstrip() + ('\n\n' if description else '') + note
    return result


def provider_required(source_required: bool, declared: dict, schema: dict, name: str, constrained: set) -> bool:
    """Whether a provider-required field the Runtime declares as optional stays required.

    The Runtime marks a field required only where it validates it. Under provider
    or mixed validation the provider still rejects a call without it, so callers
    must send it, unless the Runtime supplies a default or governs it with a
    cross-field rule (required_any_of, conditional requirements).
    """
    return (source_required and not declared.get("required") is True
            and "default" not in (schema if isinstance(schema, dict) else {})
            and name not in constrained)


def forwards_undeclared_query(runtime: dict) -> bool:
    """Read the Runtime forwarding fact independently of target-value precedence.

    OpenQuery preserves fixed target values while forwarding undeclared caller
    parameters. It is distinct from TargetQueryRequestWins; the owning Runtime
    compiler prohibits combining it with request-wins or ignore-undeclared.
    """
    policy = runtime.get('x-aisa-query-policy', {})
    if not isinstance(policy, dict) or any(type(value) is not bool for value in policy.values()):
        raise ValueError('invalid runtime query forwarding policy')
    if policy.get('open_query') is True and (policy.get('request_wins') is True or policy.get('ignore_undeclared') is True):
        raise ValueError('conflicting runtime open-query forwarding policy')
    return policy.get('open_query') is True or policy.get('request_wins') is True


def constrained_names(runtime: dict) -> set:
    """Field names the Runtime's cross-field constraints refer to."""
    names = set()

    def visit(node, in_group=False):
        if isinstance(node, dict):
            names.update(node[key] for key in ("name", "selector") if isinstance(node.get(key), str))
            for key, value in node.items():
                visit(value, in_group or key == "required_any_of")
        elif isinstance(node, list):
            for value in node:
                visit(value, in_group)
        elif in_group and isinstance(node, str):
            names.add(node)
    constraints = runtime.get("x-aisa-constraints", {})
    for key, value in (constraints.items() if isinstance(constraints, dict) else ()):
        if key != "notes":
            visit({key: value})
    return names


def merge_object(upstream: dict, declared: dict, constrained: set = frozenset(), kept: list | None = None,
                 prefix: str = "") -> dict:
    # Rechecking an already composed body must preserve identical Runtime-owned
    # cross-field rules. They are reapplied below, after provider field merging.
    # Different or extra source rules still go through the strict flattener.
    source = upstream
    if (isinstance(upstream, dict) and "allOf" in declared
            and upstream.get("allOf") == declared["allOf"]):
        source = {key: value for key, value in upstream.items() if key != "allOf"}
    # A supplier can forbid combining two inputs that the Runtime forwards
    # without declaring. Preserve that exclusion only when it cannot override
    # any Runtime-owned field or cross-field rule. Other conditionals still
    # fail in flatten_object rather than guessing their precedence.
    exclusion = source.get("not") if isinstance(source, dict) else None
    excluded = exclusion.get("required") if isinstance(exclusion, dict) else None
    provider_exclusion = (
        isinstance(exclusion, dict) and set(exclusion) == {"required"}
        and isinstance(excluded, list) and len(excluded) == 2
        and all(isinstance(name, str) for name in excluded)
        and len(set(excluded)) == 2
        and set(excluded) <= set(source.get("properties", {}))
        and not set(excluded).intersection(declared.get("properties", {}))
        and not {prefix + name for name in excluded}.intersection(constrained)
        and declared.get("additionalProperties", True) is True
        and not any(key in declared for key in (
            "not", "allOf", "anyOf", "oneOf", "if", "then", "else",
            "dependentSchemas", "dependentRequired", "patternProperties")))
    if provider_exclusion:
        source = {key: value for key, value in source.items() if key != "not"}
    merged = flatten_object(source)
    names = set(declared.get("properties", {}))
    source_required = set(merged.get("required", []))
    if declared.get("additionalProperties") is False:
        rejected = source_required - names
        if rejected:
            raise ValueError("source body requires inputs rejected by runtime: "
                             + ", ".join(sorted(prefix + name for name in rejected)))
        # A mixed operation can have a closed request and a provider-owned
        # response. Provider-only inputs must not reopen the Runtime body.
        merged["properties"] = {name: value for name, value in merged.get("properties", {}).items()
                                if name in names}
        merged["additionalProperties"] = False
    required = (source_required - names) | set(declared.get("required", []))
    for name, value in declared.get("properties", {}).items():
        if name not in required and provider_required(name in source_required, {}, value, prefix + name, constrained):
            required.add(name)
            if kept is not None:
                kept.append(prefix + name)
        original = merged.setdefault("properties", {}).get(name, {})
        if (value.get("properties") or value.get("additionalProperties") is False) and isinstance(original, dict) and original.get("type", "object") == "object":
            merged["properties"][name] = merge_object(original, value, constrained, kept, prefix + name + ".")
        elif (value.get("type") == "array" and value.get("items") == {}
              and isinstance(original, dict) and original.get("type") == "array"
              and isinstance(original.get("items"), dict)):
            # Runtime owns this array and its bounds, but an explicit empty
            # items schema makes no declaration about the provider's children.
            merged["properties"][name] = retain_source_annotations(value, original)
            merged["properties"][name]["items"] = copy.deepcopy(original["items"])
        else:
            merged["properties"][name] = retain_source_annotations(value, original) if isinstance(original, dict) else copy.deepcopy(value)
    merged.pop("required", None)
    if required:
        merged["required"] = sorted(required)
    for key, value in declared.items():
        if key not in {"properties", "required", "additionalProperties", "type"}:
            merged[key] = copy.deepcopy(value)
    if provider_exclusion:
        merged["not"] = copy.deepcopy(exclusion)
    return merged


def merge_body(upstream: dict, runtime: dict, constrained: set = frozenset(), kept: list | None = None) -> dict:
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
        if not declared.get("properties") and declared.get("additionalProperties") is not False:
            continue
        original["schema"] = merge_object(original.get("schema", {}), declared, constrained, kept)
        # Upstream request examples describe the complete body. Runtime examples
        # only cover declared fields and must not replace the complete example.
    return result


# Publication of Runtime operations without reviewed inputs. The generic schema
# claims only that the success body is JSON; it never describes its fields.
UNREVIEWED_RUNTIME_POLICY = "unreviewed-runtime-v1"
# Runtime-owned public contract metadata (Spec #1285 R1). These are part of the
# customer contract, not provenance: the composer copies them from Runtime
# facts unchanged and every public projection (Mintlify, llms, MCP) keeps them.
PUBLIC_CONTRACT_EXTENSIONS = frozenset({"x-aisa-pagination", "x-aisa-latency-class", "x-aisa-latency"})
PAGINATION_PROPERTY = "aisa_pagination"
_PAGINATION_WRAPPER_KEYS = {"type", "properties", "additionalProperties", "required"}


def runtime_pagination_property(runtime: dict) -> dict | None:
    """The gateway-added ``aisa_pagination`` property of the Runtime 200 schema."""
    if not isinstance(runtime.get("x-aisa-pagination"), dict):
        return None
    schema = (runtime.get("responses", {}).get("200", {}).get("content", {})
              .get("application/json", {}).get("schema"))
    properties = schema.get("properties") if isinstance(schema, dict) else None
    value = properties.get(PAGINATION_PROPERTY) if isinstance(properties, dict) else None
    return copy.deepcopy(value) if isinstance(value, dict) else None


def is_pagination_wrapper(schema: Any) -> bool:
    """A schema that only declares the gateway pagination envelope."""
    return (isinstance(schema, dict) and set(schema) <= _PAGINATION_WRAPPER_KEYS
            and schema.get("type", "object") == "object"
            and isinstance(schema.get("properties"), dict) and set(schema["properties"]) == {PAGINATION_PROPERTY}
            and set(schema.get("required", [])) <= {PAGINATION_PROPERTY})


def without_pagination_payload(response: dict) -> dict:
    """Remove the gateway ``aisa_pagination`` envelope from a success response.

    Runtime declares ``aisa_pagination`` on otherwise payload-less 200
    responses. That declaration must not suppress the reviewed source payload,
    and a previously published envelope must not become part of a retained
    success contract (it is re-merged from Runtime facts on every compose).
    A pagination-only payload is dropped entirely.
    """
    if not isinstance(response, dict):
        return response
    media = response.get("content", {}).get("application/json") if isinstance(response.get("content"), dict) else None
    schema = media.get("schema") if isinstance(media, dict) else None
    if not isinstance(schema, dict):
        return response
    result = copy.deepcopy(response)
    target = result["content"]["application/json"]
    if is_pagination_wrapper(schema):
        if set(response["content"]) == {"application/json"} and set(media) == {"schema"}:
            result.pop("content")
        else:
            target.pop("schema")
    elif set(schema) == {"allOf"} and isinstance(schema["allOf"], list) and len(schema["allOf"]) == 2 \
            and is_pagination_wrapper(schema["allOf"][1]):
        target["schema"] = copy.deepcopy(schema["allOf"][0])
    elif isinstance(schema.get("properties"), dict) and PAGINATION_PROPERTY in schema["properties"]:
        target["schema"]["properties"].pop(PAGINATION_PROPERTY)
    else:
        return response
    return result


def merge_pagination_property(response: dict, prop: dict) -> None:
    """Merge Runtime's ``aisa_pagination`` into the effective 200 JSON schema (idempotent)."""
    if not isinstance(response, dict) or "$ref" in response or response.get("x-aisa-no-content") is True:
        return
    content = response.get("content")
    if not content:
        content = response["content"] = {"application/json": {}}
    media = content.get("application/json")
    if not isinstance(media, dict):
        # A non-JSON payload cannot carry the envelope; release_gate_pagination reports it.
        return
    schema = media.get("schema", {})
    wrapper = {"type": "object", "properties": {PAGINATION_PROPERTY: copy.deepcopy(prop)}}
    if schema is True or schema == {}:
        media["schema"] = wrapper
    elif isinstance(schema, dict) and isinstance(schema.get("allOf"), list) and set(schema) == {"allOf"} \
            and schema["allOf"] and is_pagination_wrapper(schema["allOf"][-1]):
        schema["allOf"][-1] = wrapper
    elif isinstance(schema, dict) and not ({"$ref", "allOf", "anyOf", "oneOf", "not", "if"} & set(schema)) \
            and schema.get("type", "object") == "object":
        schema.setdefault("properties", {})[PAGINATION_PROPERTY] = copy.deepcopy(prop)
    elif isinstance(schema, dict):
        media["schema"] = {"allOf": [schema, wrapper]}


UNREVIEWED_SUCCESS_SCHEMA = {}
UNREVIEWED_SUCCESS_DESCRIPTION = "Successful response. The payload schema has not been reviewed yet."


def is_unreviewed_request(operation: dict) -> bool:
    review = operation.get("x-aisa-review")
    return isinstance(review, dict) and review.get("status") == "unreviewed" and review.get("request") == "runtime_binding"


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
            payload = copy.deepcopy(payload)
            for media in payload.get("content", {}).values():
                schema = media.get("schema") if isinstance(media, dict) else None
                if isinstance(schema, dict) and schema.get("x-aisa-schema-completeness") == "documented-fields-only":
                    # The full field table remains in the response description.
                    # Raw discovery metadata stays in the reviewed source input.
                    schema.pop("x-aisa-provider-response", None)
                    if schema.get("description") == payload.get("description"):
                        schema.pop("description", None)
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
                resolved = without_pagination_payload(response_object(response, previous))
                if resolved.get("x-aisa-response-observation") or operation.get("x-aisa-review", {}).get("response") == "generic":
                    continue  # Expired observations and placeholders are not reviewed source contracts.
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


def incomplete_source_diagnostic(sources: list, upstream_path: str, method: str,
                                 selector: dict | None = None) -> dict:
    """Explain an omitted definition without supplying request/method authority.

    Keep the historical reason classification: changing display diagnostics must
    not change an approved pending fingerprint or turn pending into a contract.
    """
    if selector or not upstream_path:
        return {}
    details = []
    for document in sources:
        source = document.get("info", {}).get("x-aisa-source", {})
        references = source.get("pending_references", [])
        if not isinstance(references, list) or source.get("response_only") is True:
            continue
        for reference in references:
            if not isinstance(reference, dict) or reference.get("path") != upstream_path:
                continue
            declared_method = reference.get("method")
            reason = reference.get("reason")
            if (not isinstance(declared_method, str) or declared_method.lower() not in METHODS
                    or method != "ANY" and declared_method.lower() != method.lower()
                    or not isinstance(reason, str) or not reason.strip()):
                continue
            detail = {"path": upstream_path, "method": declared_method.upper(),
                      "reason": reason, "source_url": source["url"]}
            if detail not in details:
                details.append(detail)
    if not details:
        return {}
    details.sort(key=lambda item: (item["source_url"], item["method"], item["reason"]))
    return {"reason": "source definition incomplete: " + "; ".join(item["reason"] for item in details)
            + " (upstream operation missing from imported definitions)",
            "source_definition_diagnostics": details}


def compose(facts: dict, upstream: dict | None = None, overlay: dict | None = None,
            previous: dict | None = None, public_mirrors: dict | None = None,
            source_bindings: dict | None = None, *, unreviewed_runtime: bool = False) -> tuple[dict, list]:
    """Compose one provider from Runtime facts and reviewed sources.

    ``unreviewed_runtime`` publishes a Runtime operation that has no reviewed
    source operation from its own Runtime binding (identity, status, method,
    path, pricing, declared parameters and body) instead of leaving it pending,
    and gives an enabled operation without a reviewed success payload an
    explicitly generic JSON schema. Such operations carry ``x-aisa-review`` so
    consumers can tell them apart from reviewed contracts. Public ANY routes,
    source-bound credentials and reviewed operations are unchanged.
    """
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
        if "response_only" in source and type(source["response_only"]) is not bool:
            raise ValueError("upstream response_only marker must be boolean")
        if source.get("kind") not in {"manual", "provider_openapi"} or not all(source.get(k) for k in ("url", "fetched_at", "content_hash", "converter")):
            raise ValueError("upstream mirror requires complete x-aisa-source provenance")
    output = copy.deepcopy(facts)
    output["paths"] = {}
    pending: list[dict] = []
    published_responses = published_success_responses(previous)
    retained_responses = {}
    response_gaps = []
    facts_prefix = urlsplit((facts.get("servers") or [{"url": ""}])[0]["url"]).path.rstrip("/")
    from runtime_registry import runtime_metadata_mirrors
    public_mirrors = runtime_metadata_mirrors(facts, upstream, public_mirrors)
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
            validate_payment_capabilities(runtime)
            base_id = runtime.get("operationId")
            if not base_id or runtime.get("x-aisa-status") not in {"enabled", "disabled"}:
                raise ValueError("runtime operation requires immutable operationId and status")
            validation = runtime.get("x-aisa-validation")
            if validation not in {"runtime", "provider", "mixed"}:
                raise ValueError("runtime operation has unknown validation boundary")
            public_path = facts_prefix + path
            bound_source = source_bindings.get(public_path)
            try:
                candidates = [source for source in sources if source.get("info", {}).get("x-aisa-source", {}).get("response_only") is not True]
                if bound_source:
                    candidates = [source for source in candidates if source.get("info", {}).get("x-aisa-source", {}).get("url") == bound_source]
                    if len(candidates) != 1:
                        raise ValueError("public operation source binding must select exactly one locked source")
                upstream_matches = select_upstream_operations(candidates, runtime.get("x-aisa-upstream-path"), runtime.get("x-aisa-upstream-selector")) if validation != "runtime" or method == "x-aisa-any" or "x-aisa-request-auth" in runtime else {}
                if bound_source and not upstream_matches:
                    raise ValueError("bound source does not match the runtime upstream path and selector")
                upstream_item = {key: value[1] for key, value in upstream_matches.items()}
            except (ValueError, TypeError, KeyError) as exc:
                pending.append({"operation_id": base_id, "path": path, "method": "ANY" if method == "x-aisa-any" else method.upper(), "reason": str(exc)})
                continue
            methods = sorted((set(upstream_item) & METHODS) | {m for (p, m), candidate in public_mirrors.items() if p == public_path and not candidate.get("response_only")}) if method == "x-aisa-any" else [method]
            if not methods:
                pending.append({"operation_id": base_id, "path": path, "method": "ANY", "reason": "upstream selector has no matching official operation" if runtime.get("x-aisa-upstream-selector") else "upstream operation missing",
                                **incomplete_source_diagnostic(candidates, runtime.get("x-aisa-upstream-path"), "ANY", runtime.get("x-aisa-upstream-selector"))})
            for actual_method in methods:
                try:
                    mirror = {}
                    selected_document = {}
                    operation_source = {}
                    response_operation, response_document = {}, {}
                    unreviewed_request = False
                    if validation != "runtime" or method == "x-aisa-any" or "x-aisa-request-auth" in runtime:
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
                        elif (public_path, actual_method) in public_mirrors and not public_mirrors[(public_path, actual_method)].get("response_only"):
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
                        elif unreviewed_runtime and method != "x-aisa-any" and "x-aisa-request-auth" not in runtime:
                            # No reviewed source operation: the Runtime binding is the
                            # only request authority, exactly as for validation=runtime.
                            # A disabled operation keeps its Runtime status, so disabling
                            # an unreviewed route never withholds the whole artifact.
                            unreviewed_request = True
                        else:
                            raise ValueError("upstream operation missing")
                    server_auth = server_auth_headers(runtime, facts.get("info", {}).get("x-aisa-provider"), actual_method, selected_document, mirror)
                    request_auth = request_auth_headers(runtime, facts.get("info", {}).get("x-aisa-provider"), actual_method, selected_document, mirror, public_path=public_path)
                    operation = copy.deepcopy(runtime)
                    observed_methods = operation.pop("x-aisa-observed-response-methods", {})
                    if method == "x-aisa-any" and observed_methods:
                        operation["x-aisa-observed-responses"] = copy.deepcopy(observed_methods.get(actual_method.upper(), {}))
                    pagination_property = runtime_pagination_property(runtime)
                    runtime_responses = runtime.get("responses", {})
                    if pagination_property is not None and isinstance(operation.get("responses", {}).get("200"), dict):
                        # Runtime adds only the envelope; the payload comes from reviewed sources.
                        operation["responses"]["200"] = without_pagination_payload(operation["responses"]["200"])
                        runtime_responses = {**runtime_responses, "200": operation["responses"]["200"]}
                    capabilities = operation.get("x-aisa-capabilities") or {}
                    for payment in ("mpp", "x402"):
                        if payment + "_methods" in capabilities:
                            capabilities[payment] = (capabilities.get(payment) is True
                                and actual_method.upper() in capabilities[payment + "_methods"])
                    # Direct Runtime identity, before public ANY expansion or retained
                    # published aliases. Consumers must not guess this binding.
                    operation["x-aisa-runtime-operation"] = {
                        "operation_id": base_id, "method": "ANY" if method == "x-aisa-any" else method.upper(),
                        "path": public_path}
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
                    if validation != "runtime" and not unreviewed_request:
                        runtime_fields = {(p["in"], p["name"]) for p in runtime.get("parameters", [])}
                        query_passthrough = forwards_undeclared_query(runtime)
                        if bound_source and not runtime.get("x-aisa-upstream-selector"):
                            for parameter in mirror.get("parameters", []):
                                if parameter.get("in") == "query" and parameter.get("required") and isinstance(parameter.get("schema"), dict) and "default" in parameter["schema"]:
                                    # Required provider arguments are caller inputs, not
                                    # transport defaults. Keep the suggested value as an example.
                                    value = parameter["schema"].pop("default")
                                    parameter.setdefault("example", value)
                        if bound_source and not query_passthrough and any(p.get("in") == "query" and p.get("required") and (p["in"], p["name"]) not in runtime_fields for p in mirror.get("parameters", [])):
                            raise ValueError("bound source requires query parameters that runtime does not forward")
                        unforwarded_query = sorted({
                            p["name"] for p in mirror.get("parameters", [])
                            if p.get("in") == "query"
                            and p.get("name", "").lower() not in auth_names
                            and not query_passthrough
                            and (p["in"], p["name"]) not in runtime_fields
                        })
                        if unforwarded_query:
                            raise ValueError("source query parameters are not forwarded by runtime: "
                                             + ", ".join(unforwarded_query))
                        caller_headers = runtime.get("x-aisa-caller-headers", [])
                        if not isinstance(caller_headers, list) or not all(isinstance(name, str) for name in caller_headers):
                            raise ValueError("invalid runtime caller-header forwarding declaration")
                        forwarded_headers = {"accept", *(name.lower() for name in caller_headers)}
                        unforwarded_headers = sorted({
                            p["name"] for p in mirror.get("parameters", [])
                            if p.get("in") == "header"
                            and p.get("name", "").lower() not in auth_names | server_auth | request_auth | forwarded_headers
                        })
                        if unforwarded_headers:
                            raise ValueError("source header parameters are not forwarded by runtime: "
                                             + ", ".join(unforwarded_headers))
                        parameters = {
                            (p["in"], p["name"]): p for p in mirror.get("parameters", [])
                            if p.get("name", "").lower() not in auth_names
                            and not (p.get("in") == "header" and p.get("name", "").lower() in server_auth)
                            and (p.get("in") != "query" or query_passthrough or (p["in"], p["name"]) in runtime_fields)
                        }
                        constrained = constrained_names(runtime)
                        # Provider-required inputs the Runtime declares optional but does not validate.
                        kept_required = []
                        for parameter in runtime.get("parameters", []):
                            key = (parameter["in"], parameter["name"])
                            original = parameters.get(key, {})
                            merged = retain_source_annotations(parameter, original)
                            if isinstance(parameter.get("schema"), dict) and isinstance(original.get("schema"), dict):
                                merged["schema"] = retain_source_annotations(parameter["schema"], original["schema"])
                            if provider_required(original.get("required") is True, parameter, parameter.get("schema"),
                                                 parameter["name"], constrained):
                                merged["required"] = True
                                kept_required.append(f'{parameter["in"]}:{parameter["name"]}')
                            parameters[key] = retain_provider_parameter_guidance(merged, original)
                        if parameters:
                            operation["parameters"] = [parameter_wire_default(parameters[k]) for k in sorted(parameters)]
                        if mirror.get("requestBody") or runtime.get("requestBody"):
                            body_kept = []
                            operation["requestBody"] = merge_body(mirror.get("requestBody", {}), runtime.get("requestBody", {}),
                                                                  constrained, body_kept)
                            kept_required.extend(f"body:{name}" for name in body_kept)
                        if kept_required:
                            # Required because the provider rejects calls without them; the Runtime
                            # does not validate these, so consumers can tell the two apart.
                            operation["x-aisa-provider-required"] = sorted(kept_required)
                        operation["x-aisa-source"] = copy.deepcopy(operation_source)
                    editorial = overlay.get(operation["operationId"], overlay.get(base_id, {}))
                    description = descriptive_text(editorial, runtime, mirror)
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
                    response_source = operation_source
                    # Runtime explicitly attests unchanged response transport.
                    # This authority is independent from request validation and
                    # never discovers methods or contributes request fields.
                    descriptor_present = any(k in runtime for k in ("x-aisa-response-passthrough", "x-aisa-response-upstream-path-sha256", "x-aisa-response-upstream-origin-sha256", "x-aisa-response-contract-hash", "x-aisa-response-contract-hashes"))
                    if descriptor_present:
                        response_operation, response_document = {}, {}
                        transport = runtime.get("x-aisa-response-passthrough")
                        path_hash = runtime.get("x-aisa-response-upstream-path-sha256")
                        origin_hash = runtime.get("x-aisa-response-upstream-origin-sha256")
                        commitments = runtime.get("x-aisa-response-contract-hashes", {})
                        if not isinstance(commitments, dict):
                            raise ValueError("invalid public response contract fingerprint map")
                        commitment = commitments.get(actual_method.upper(), runtime.get("x-aisa-response-contract-hash"))
                        if commitments and commitment is None:
                            raise ValueError("missing method-specific public response contract fingerprint")
                        if commitment is not None:
                            operation.pop("x-aisa-response-contract-hashes", None)
                            operation["x-aisa-response-contract-hash"] = commitment
                        if commitment is not None:
                            # Public replay binds the already selected response *content*,
                            # never an enumerable supplier host/path hash. The first
                            # internal pass still validates the private transport binding.
                            selected = public_mirrors.get((public_path, actual_method), {})
                            choices = selected.get("independent_response_candidates", [])
                            if not choices and selected.get("source", {}).get("upstream_path_sha256"):
                                choices = [selected]
                            matches = []
                            if not isinstance(commitment, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", commitment):
                                response_error = "invalid public response contract fingerprint"
                            else:
                                for choice in ([] if commitment == digest({}) else choices):
                                    candidate_source = choice["source"]
                                    candidate_document = {"openapi": choice.get("openapi", "3.1.0"),
                                                          "components": choice.get("response_components", {})}
                                    candidate = source_success_responses(choice.get("response_operation", {}),
                                        candidate_document, copy.deepcopy(output),
                                        "response_" + digest(candidate_source)[7:19] + ".json", runtime_responses)
                                    if digest(candidate) == commitment:
                                        matches.append(choice)
                                if len(matches) == 1:
                                    selected_response = matches[0]
                                    response_operation = selected_response.get("response_operation", {})
                                    response_document = {"openapi": selected_response.get("openapi", "3.1.0"),
                                                         "components": selected_response.get("response_components", {})}
                                    response_source = selected_response["source"]
                                    used_mirrors[f"response {actual_method} {public_path}"] = selected_response
                                elif commitment != digest({}):
                                    response_error = "public response contract fingerprint is missing or ambiguous in reviewed inputs"
                        elif type(transport) is not bool:
                            response_error = "runtime response transport flag is missing or invalid"
                        elif transport is True:
                            selected = public_mirrors.get((public_path, actual_method), {})
                            choices = selected.get("independent_response_candidates", [])
                            if not choices and selected.get("source", {}).get("upstream_path_sha256"):
                                choices = [selected]
                            if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in (path_hash, origin_hash)):
                                response_error = "runtime response path or origin binding hash is missing or invalid"
                            elif choices:
                                if len(choices) != 1 or choices[0].get("source", {}).get("upstream_path_sha256") != path_hash or choices[0].get("source", {}).get("upstream_origin_sha256") != origin_hash:
                                    response_error = "independent response source binding is ambiguous or changed"
                                else:
                                    selected_response = choices[0]
                                    response_operation = selected_response.get("response_operation", {})
                                    response_document = {"openapi": selected_response.get("openapi", "3.1.0"),
                                                         "components": selected_response.get("response_components", {})}
                                    response_source = selected_response["source"]
                                    used_mirrors[f"response {actual_method} {public_path}"] = selected_response
                        elif any(k in runtime for k in ("x-aisa-response-upstream-path-sha256", "x-aisa-response-upstream-origin-sha256")):
                            response_error = "transformed response must not declare passthrough binding hashes"
                    try:
                        fresh = source_success_responses(response_operation, response_document, output, "response_" + digest(response_source)[7:19] + ".json", runtime_responses)
                    except (ValueError, KeyError, TypeError) as exc:
                        response_error = str(exc)
                    if "x-aisa-response-passthrough" in runtime:
                        operation["x-aisa-response-contract-hash"] = digest(fresh)
                    source_payloads = {}
                    if not editorial.get("description") and not mirror.get("description") and response_operation.get("description"):
                        operation["description"] = descriptive_text(editorial, runtime, response_operation)
                    response_identity = (facts_prefix + path, actual_method, operation_id)
                    old_responses = {} if descriptor_present else published_responses.get(response_identity, {})
                    if fresh and "200" not in fresh and (runtime.get("x-aisa-passthrough") is True or runtime.get("x-aisa-response-passthrough") is True or operation.get("x-aisa-response-contract-hash")) and not has_response_payload(operation.get("responses", {}).get("200", {})):
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
                        operation["x-aisa-response-source"] = {"kind": "upstream_success_contract", "source": copy.deepcopy(response_source),
                                                               "content_hash": digest(source_payloads)}
                    if retained:
                        retained_responses[operation_id] = retained
                        operation.setdefault("x-aisa-response-source", {
                            "kind": "published_success_contract",
                            "content_hash": digest(retained),
                        })
                    observed_statuses = apply_observed_responses(operation)
                    unknown = [str(status) for status, response in operation.get("responses", {}).items()
                               if re.fullmatch(r"2(?:[0-9]{2}|XX)", str(status))
                               and not (str(status) in {"204", "205"} and not response.get("content"))
                               and not has_response_contract(response)]
                    unreviewed_response = []
                    if (unreviewed_runtime and unknown and not response_error
                            and operation.get("x-aisa-status") == "enabled"):
                        for status in unknown:
                            generic = operation["responses"][status]
                            if not isinstance(generic, dict) or "$ref" in generic:
                                continue
                            # Keep reviewed media types and their official examples; only
                            # the missing payload schema becomes explicitly generic.
                            content = generic.get("content") if isinstance(generic.get("content"), dict) else {}
                            kept = {}
                            for media, item in content.items():
                                item = copy.deepcopy(item) if isinstance(item, dict) else {}
                                item.setdefault("schema", copy.deepcopy(UNREVIEWED_SUCCESS_SCHEMA))
                                kept[media] = item
                            generic["content"] = kept or {"application/json": {"schema": copy.deepcopy(UNREVIEWED_SUCCESS_SCHEMA)}}
                            generic["description"] = UNREVIEWED_SUCCESS_DESCRIPTION
                            unreviewed_response.append(status)
                        unknown = [status for status in unknown if status not in unreviewed_response]
                    if unreviewed_request or unreviewed_response or observed_statuses:
                        operation["x-aisa-review"] = {
                            "status": "unreviewed",
                            "request": "runtime_binding" if unreviewed_request else "reviewed_source",
                            "response": ("observed" if observed_statuses else "generic" if unreviewed_response else
                                         "pending" if unknown or response_error else "reviewed_source"),
                        }
                    if unknown or response_error:
                        gap = {"operation_id": operation_id, "path": path, "method": actual_method.upper(),
                               "statuses": unknown, "reason": response_error or "public success response has no authoritative payload declaration"}
                        response_gaps.append(gap)
                        operation["x-aisa-response-pending"] = copy.deepcopy(gap)
                    if pagination_property is not None and "200" in operation.get("responses", {}):
                        # After gap detection: the envelope never counts as a reviewed payload.
                        merge_pagination_property(operation["responses"]["200"], pagination_property)
                    if operation_id in ids:
                        raise IdentityError(f"duplicate operationId: {operation_id}")
                    ids.add(operation_id)
                    output["paths"].setdefault(path, copy.deepcopy(public_context))[actual_method] = operation
                except IdentityError:
                    raise
                except (ValueError, KeyError, TypeError) as exc:
                    diagnostic = incomplete_source_diagnostic(candidates, runtime.get("x-aisa-upstream-path"), actual_method.upper(), runtime.get("x-aisa-upstream-selector")) if str(exc) == "upstream operation missing" else {}
                    pending.append({"operation_id": base_id, "path": path, "method": actual_method.upper(), "reason": str(exc), **diagnostic})
    document_meta = output["info"]["x-aisa-document"]
    document_meta["composer_version"] = VERSION
    document_meta["response_pending"] = response_gaps
    hash_inputs = {"facts_hash": meta["facts_hash"], "upstream": upstream, "overlay": overlay, "composer_version": VERSION, "published_success_responses": retained_responses, "public_mirrors": used_mirrors, "source_bindings": source_bindings}
    if unreviewed_runtime:
        hash_inputs["unreviewed_runtime"] = UNREVIEWED_RUNTIME_POLICY
    document_meta["document_hash"] = digest(hash_inputs)
    from playground_examples import add_get_code_sample, add_body_code_sample, apply_example_verification
    for path, item in output["paths"].items():
        for method, operation in item.items():
            if method in METHODS:
                if not apply_example_verification(operation):
                    continue
                if method == "get":
                    add_get_code_sample(operation, path, operation.get("servers", item.get("servers", output.get("servers", []))))
                elif method in {"post", "put", "patch"}:
                    add_body_code_sample(operation, method, path, operation.get("servers", item.get("servers", output.get("servers", []))))
    from source_provenance import compact_document
    from pricing_prose import clean_document
    from customer_wording import apply as customer_wording
    output = customer_wording(clean_document(output))
    return compact_document(output), pending
