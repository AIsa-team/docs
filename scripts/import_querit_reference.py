"""Convert typed tables from Querit's official reference, without running page code."""
import hashlib
import json
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

from compose_openapi import digest

REFERENCE_URL = "https://www.querit.ai/en/docs/reference/post-for-coding-agents"
VERSION = "scripts/import_querit_reference.py@1"


def clean(value):
    return " ".join(value.split())


class ReferenceTables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sections = []
        self.section = None
        self.heading = None
        self.table = None
        self.row = None
        self.cell = None
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1
        if self.skip:
            return
        if tag in {"h1", "h2", "h3"}:
            self.heading = []
        elif tag == "table":
            if self.table is not None:
                raise ValueError("nested reference tables are unsupported")
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in {"td", "th"} and self.row is not None:
            self.cell = []
        elif tag in {"p", "li", "br"} and self.section is not None and self.table is None:
            self.section["text"].append("\n")

    def handle_data(self, value):
        if self.skip:
            return
        if self.heading is not None:
            self.heading.append(value)
        elif self.cell is not None:
            self.cell.append(value)
        elif self.section is not None and self.table is None:
            self.section["text"].append(value)

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip -= 1
            return
        if self.skip:
            return
        if tag in {"h1", "h2", "h3"} and self.heading is not None:
            self.section = {"title": clean("".join(self.heading)), "text": [], "tables": []}
            self.sections.append(self.section)
            self.heading = None
        elif tag in {"td", "th"} and self.cell is not None:
            self.row.append(clean("".join(self.cell)))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            if self.section is None:
                raise ValueError("reference table has no section")
            self.section["tables"].append(self.table)
            self.table = None

    def unique_section(self, name):
        matches = [section for section in self.sections if section["title"] == name]
        if len(matches) != 1:
            raise ValueError(f"expected one {name} section")
        return matches[0]


def typed_schema(type_name):
    alternatives = [value.strip() for value in type_name.split("|")]
    if len(alternatives) > 1:
        return {"anyOf": [typed_schema(value) for value in alternatives]}
    if type_name.endswith("[]"):
        return {"type": "array", "items": typed_schema(type_name[:-2])}
    if type_name not in {"string", "integer", "number", "boolean", "object"}:
        raise ValueError(f"unsupported official field type: {type_name}")
    return {"type": type_name}


def object_branch(schema):
    if schema.get("type") == "object":
        return schema
    branches = [branch for branch in schema.get("anyOf", []) if branch.get("type") == "object"]
    if len(branches) != 1:
        raise ValueError("nested field has no unique object parent")
    return branches[0]


def field_at(root, path):
    cursor = root
    for part in path.split("."):
        cursor = object_branch(cursor)["properties"][part]
    return cursor


def schema_from_tables(tables):
    root, fields = {"type": "object", "properties": {}}, {}
    if not tables:
        raise ValueError("official reference has no typed tables")
    for table in tables:
        if not table or table[0] not in (["Parameter", "Type", "Required", "Default", "Description"], ["Field", "Type", "Description"]):
            raise ValueError("unknown typed reference table columns")
        headers = table[0]
        for row in table[1:]:
            if len(row) != len(headers):
                raise ValueError("incomplete typed reference row")
            entry = dict(zip(headers, row))
            raw_name = entry.get("Parameter", entry.get("Field"))
            name = raw_name.removesuffix("[]")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", name) or name in fields:
                raise ValueError("invalid or duplicate official field path")
            schema = typed_schema(entry["Type"])
            if raw_name.endswith("[]") and schema.get("type") != "array":
                raise ValueError("array field name and type disagree")
            description = entry["Description"]
            schema["description"] = description
            required = entry.get("Required")
            if required not in (None, "Yes", "No"):
                raise ValueError("unknown required marker")
            default = entry.get("Default")
            if default not in (None, "—", "server default"):
                try:
                    value = json.loads(default)
                except ValueError:
                    if schema.get("type") != "string":
                        raise ValueError("unrecognized typed default") from None
                    value = default
                expected = {"integer": int, "number": (int, float), "boolean": bool, "string": str}.get(schema.get("type"))
                if expected is None or not isinstance(value, expected) or (schema.get("type") in ("integer", "number") and isinstance(value, bool)):
                    raise ValueError("default does not match official type")
                schema["default"] = value
            elif default == "server default":
                schema["description"] += ". Default: server default (value unspecified)."
            bounds = re.search(r"\bbetween (-?\d+) and (-?\d+)\b", description)
            if bounds and schema.get("type") in {"integer", "number"}:
                schema["minimum"], schema["maximum"] = map(int, bounds.groups())
            choices = re.search(r'Supported values: ((?:"[^"\n]+"(?:,\s*)?)+)', description)
            if choices and schema.get("type") == "string":
                schema["enum"] = re.findall(r'"([^"\n]+)"', choices[1])
            cursor = root
            parts = name.split(".")
            for part in parts[:-1]:
                cursor = object_branch(cursor).setdefault("properties", {}).setdefault(part, {"type": "object"})
            target = object_branch(cursor)
            if parts[-1] in target.setdefault("properties", {}):
                raise ValueError("official field overwrites an inferred parent")
            target["properties"][parts[-1]] = schema
            if required == "Yes":
                target.setdefault("required", []).append(parts[-1])
            fields[name] = schema
    return root, fields


def apply_documented_enums(text, fields):
    # The reference may shorten a nested path to a unique suffix. Resolve only
    # against fields actually parsed from its tables, never a provider map.
    for suffix, values in re.findall(r"(?m)^\s*([A-Za-z_][A-Za-z0-9_.]*) allowed values: ([^.\n]+)\.", text):
        matches = [name for name in fields if name == suffix or name.endswith("." + suffix)]
        if len(matches) != 1:
            raise ValueError("ambiguous documented enumeration field")
        schema = fields[matches[0]]
        target = schema.get("items") if schema.get("type") == "array" else schema
        if target.get("type") != "string":
            raise ValueError("unsupported documented enumeration type")
        choices = [value.strip() for value in values.split(",")]
        if "enum" in target and target["enum"] != choices:
            raise ValueError("conflicting documented enumerations")
        target["enum"] = choices


def convert_reference(raw):
    parser = ReferenceTables()
    parser.feed(raw.decode("utf-8"))
    overview = parser.unique_section("Overview")
    request = parser.unique_section("Request Body")
    response = parser.unique_section("Response Schema")
    overview_text = "".join(overview["text"])
    endpoints = re.findall(r"Endpoint:\s*(GET|POST|PUT|PATCH|DELETE)\s+(https://[^\s]+)", overview_text)
    if len(endpoints) != 1 or "Auth: Authorization: Bearer {API_KEY}" not in overview_text or "Content-Type: application/json" not in overview_text:
        raise ValueError("unsupported official endpoint/auth/media declaration")
    method, endpoint = endpoints[0]
    address = urlsplit(endpoint)
    if address.netloc != "api.querit.ai" or address.query or address.fragment:
        raise ValueError("official reference endpoint changed origin or path format")
    request_schema, fields = schema_from_tables(request["tables"])
    request_text = "\n".join(line.strip() for line in "".join(request["text"]).splitlines() if line.strip())
    apply_documented_enums(request_text, fields)
    response_schema, _ = schema_from_tables(response["tables"])
    response_text = clean("".join(response["text"]))
    operation = {"operationId": method.lower() + "_" + re.sub(r"\W+", "_", address.path).strip("_"),
                 "summary": "Search", "externalDocs": {"url": REFERENCE_URL},
                 "requestBody": {"required": bool(request_schema.get("required")), "description": request_text,
                                 "content": {"application/json": {"schema": request_schema}}},
                 "responses": {"200": {"description": "Official response table. " + response_text,
                                       "content": {"application/json": {"schema": response_schema}}}}}
    document = {"openapi": "3.1.0", "info": {"title": "Querit official Search API reference", "version": "1"},
                "servers": [{"url": address.scheme + "://" + address.netloc}],
                "security": [{"BearerAuth": []}], "components": {"securitySchemes": {"BearerAuth": {"type": "http", "scheme": "bearer"}}},
                "paths": {address.path: {method.lower(): operation}}}
    metadata = {"converter": VERSION, "source_pages": [{"url": REFERENCE_URL, "raw_content_hash": "sha256:" + hashlib.sha256(raw).hexdigest()}],
                "structured_source_hash": digest([overview, request, response]),
                "conversion_notes": "Types, explicit required/default values and nested fields come from official tables. Conditional plan limits and time syntax remain in source descriptions; unspecified defaults and response-field types are not inferred."}
    return document, metadata


def import_reference(fetch):
    return convert_reference(fetch(REFERENCE_URL))
