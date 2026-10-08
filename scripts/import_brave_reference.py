"""Convert Brave's official structured reference data; never execute page scripts."""
import copy
import json
import re
from urllib.parse import urlsplit

from compose_openapi import METHODS, digest
from source_json import loads as source_json_loads

INDEX_URL = "https://api-dashboard.search.brave.com/llms.txt"
ORIGIN = "https://api-dashboard.search.brave.com"
VERSION = "scripts/import_brave_reference.py@2"


def canonical(value):
    """Compare wire declarations without Python's True == 1 coercion."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def load_reference(raw):
    def members(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate official reference member")
            result[key] = value
        return result
    source_json_loads(raw)  # Reject non-JSON and unsupported numeric precision.
    return json.loads(raw, object_pairs_hook=members)


def decode_api_spec(payload):
    """Decode only apiSpec's plain-data devalue graph, ignoring page/session data."""
    pools = [node["data"] for node in payload.get("nodes", [])
             if isinstance(node, dict) and isinstance(node.get("data"), list)
             and node["data"] and isinstance(node["data"][0], dict)
             and "apiSpec" in node["data"][0]]
    if len(pools) != 1:
        raise ValueError("expected exactly one official apiSpec data graph")
    pool, memo, active = pools[0], {}, set()
    undefined = object()

    def decode(index):
        if type(index) is not int or index < -1 or index >= len(pool):
            raise ValueError("unsupported reference data index")
        if index == -1:  # devalue's undefined marker, used by optional fields
            return undefined
        if index in active:
            raise ValueError("cyclic reference data is unsupported")
        if index in memo:
            return memo[index]
        active.add(index)
        value = pool[index]
        if isinstance(value, dict):
            result = {key: decoded for key, child in value.items() if (decoded := decode(child)) is not undefined}
        elif isinstance(value, list):
            # Typed values (Set, Date, custom reducers) are not OpenAPI JSON.
            if value and isinstance(value[0], str):
                raise ValueError("unsupported typed reference data")
            result = [decode(child) for child in value]
            if any(child is undefined for child in result):
                raise ValueError("undefined array item in reference data")
        elif value is None or type(value) in (str, int, float, bool):
            result = value
        else:
            raise ValueError("unsupported reference data value")
        active.remove(index)
        memo[index] = result
        return result

    result = decode(pool[0]["apiSpec"])
    canonical(result)  # Also validate callers supplying a decoded Python graph.
    return result


def reference_url(url):
    if url.startswith("/"):
        url = ORIGIN + url
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != urlsplit(ORIGIN).netloc or not parts.path.startswith("/api-reference/") or parts.query or parts.fragment:
        raise ValueError("reference discovery left the official API reference")
    return url.removesuffix("/index.html.md").removesuffix("/__data.json").rstrip("/")


def convert_specs(rows):
    document = {"openapi": "3.1.0", "info": {"title": "Brave Search API official reference", "version": "1"},
                "paths": {}, "components": {"schemas": {}, "securitySchemes": {}}}
    for url, spec in sorted(rows.items()):
        method, path = spec["method"].lower(), spec["path"]
        if method not in METHODS or not path.startswith("/") or not spec["serverUrl"].startswith("https://"):
            raise ValueError("invalid official operation identity")
        operation = {"operationId": spec["operationId"], "servers": [{"url": spec["serverUrl"]}],
                     "summary": spec.get("summary", "").strip() or spec["tagDisplayName"],
                     "description": spec.get("description", ""), "deprecated": spec.get("deprecated", False),
                     "externalDocs": {"url": url}, "parameters": [], "responses": {}}
        for param in [*spec["pathParams"], *spec["queryParams"], *spec["headerParams"]]:
            param = copy.deepcopy(param)
            examples = param.pop("examples", None)
            if examples:
                if isinstance(examples, list):
                    param["examples"] = {str(i): {"value": value} for i, value in enumerate(examples)}
                elif isinstance(examples, dict):
                    param["examples"] = examples
                else:
                    raise ValueError("unsupported official parameter examples")
            operation["parameters"].append(param)
        auth = {}
        for param in spec["authParams"]:
            scheme = {"type": "apiKey", "in": param["in"], "name": param["name"]}
            name = param["name"]
            previous = document["components"]["securitySchemes"].setdefault(name, scheme)
            if canonical(previous) != canonical(scheme):
                raise ValueError("conflicting official authentication schema")
            auth[name] = []
        if auth:
            operation["security"] = [auth]
        # This reference documents JSON bodies/responses. Preserve its schema
        # graph verbatim; do not infer fields from examples or rendered prose.
        body = spec["requestBody"]
        if body is not None:
            if not any("application/json" in sample.get("source", "") for sample in spec["codeSamples"]):
                raise ValueError("official request body has no JSON media evidence")
            operation["requestBody"] = {key: body[key] for key in ("required", "description") if key in body}
            operation["requestBody"]["content"] = {"application/json": {"schema": body["schema"]}}
        for response in spec["responses"]:
            operation["responses"][str(response["statusCode"])] = {
                "description": response["description"],
                "content": {"application/json": {"schema": response["schema"]}}}
        existing = document["paths"].setdefault(path, {}).setdefault(method, operation)
        if canonical(existing) != canonical(operation):
            raise ValueError("conflicting official operation documents")
        for name, schema in spec["schemas"].items():
            existing = document["components"]["schemas"].setdefault(name, schema)
            if canonical(existing) != canonical(schema):
                raise ValueError("conflicting official component definitions")
    return document


def import_reference(fetch):
    index = fetch(INDEX_URL).decode("utf-8")
    urls = {reference_url(url) for url in re.findall(r"https://api-dashboard\.search\.brave\.com/api-reference/[^)\s]+", index)}
    if not urls:
        raise ValueError("official reference index has no API pages")
    rows = {}
    while urls - rows.keys():
        url = sorted(urls - rows.keys())[0]
        if len(rows) >= 250:
            raise ValueError("official reference discovery exceeded its bound")
        spec = decode_api_spec(load_reference(fetch(url + "/__data.json")))
        rows[url] = spec
        urls.update(reference_url(variant["href"]) for variant in spec["methodVariants"])
    document = convert_specs(rows)
    source_pages = [{"url": url + "/__data.json", "content_hash": digest(spec)} for url, spec in sorted(rows.items())]
    return document, {"converter": VERSION, "source_pages": source_pages,
                      "source_index_hash": digest(index), "structured_source_hash": digest(rows)}
