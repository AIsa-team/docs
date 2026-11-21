#!/usr/bin/env python3
"""Publish bilingual Task docs from the public catalog, separately from Raw APIs.

Only GET /v1/tasks and GET /v1/tasks/{id} are used. All schemas are supplied by
Services. A valid empty catalog withdraws pages; acquisition/schema failure
preserves the previous publication and exits nonzero. No Task is executed.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = ("en", "zh")
COPY = {
    "en": {
        "group": "Tasks", "tab": "API Reference", "overview": "Overview",
        "intro": "Each Task has one input contract and a normalized result. The API chooses sources using the task's strategy. Availability and fields depend on the selected input; a backup source is not guaranteed.",
        "source": "API origin", "list": "Available tasks", "task": "Task", "description": "Description",
        "contract": "The request and response panels use the schemas published by this API. Conditional requirements and allowed combinations are part of the request schema. Check the complete schema before combining filters or identities.",
        "billing": "Billing", "price": "Obtain an input-specific quote by sending the same request with `X-AISA-Cost-Mode: quote`; this does not execute the Task. Use `X-AISA-Max-Price-USD` to cap the price. The catalog's base price is not a quote for every platform or input.",
        "retry": "Use an `Idempotency-Key` when executing a Task. For errors, inspect `error.code`, `error.request_id`, `error.retryable` and `error.retry_hint`. A reconciliation hint requires checking the existing request before retrying; do not assume a pending settlement is a refund.",
        "fixed": "Charged per successful delivery; an empty result is not charged.",
        "per_unit": "Charged per delivered item, not the requested limit. The quote reserves for the requested quantity; settlement uses the actual delivered quantity.",
        "success": "Successful delivery or a normal empty result", "error": "Error; use the returned HTTP status and retry guidance",
        "strategy": "Default strategy", "social": "Social", "creators": "Creators",
    },
    "zh": {
        "group": "任务", "tab": "API 参考", "overview": "概览",
        "intro": "每个任务使用统一的输入契约和结果结构。API 按任务策略选择数据源；可用能力和字段取决于具体输入，不保证每组条件都有备用来源。",
        "source": "API 地址", "list": "可用任务", "task": "任务", "description": "说明",
        "contract": "上方请求和响应面板使用此 API 发布的 Schema。条件必填和参数组合限制属于请求契约；组合筛选条件或账号身份前，请查看完整 Schema。",
        "billing": "计费", "price": "发送相同请求并带上 `X-AISA-Cost-Mode: quote`，获取与输入对应的报价，此操作不执行任务。用 `X-AISA-Max-Price-USD` 设置价格上限。目录基础价格不代表所有平台或输入的具体报价。",
        "retry": "执行任务时使用 `Idempotency-Key`。错误时查看 `error.code`、`error.request_id`、`error.retryable` 和 `error.retry_hint`。提示先核对结算时，应先查询原请求再决定是否重试；不能把待结算当作已退款。",
        "fixed": "按成功交付计费；正常查空不收费。",
        "per_unit": "按实际交付条数收费，不按请求的 limit 收费。报价按请求数量预扣，结算按实际交付数量计算。",
        "success": "成功交付或正常查空", "error": "错误；以实际 HTTP 状态和重试指引为准",
        "strategy": "默认策略", "social": "社媒", "creators": "达人",
    },
}


def get(api: str, path: str) -> dict:
    request = urllib.request.Request(api + path, headers={"Accept": "application/json", "User-Agent": "aisa-docs-tasks"})
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise ValueError(f"{path}: expected an object")
    return result


def catalog_ids(listing: dict) -> list[str]:
    if not isinstance(listing.get("data"), list):
        raise ValueError("Task catalog has no data array")
    ids = [row.get("task_id") for row in listing["data"] if isinstance(row, dict)]
    if len(ids) != len(listing["data"]) or any(not isinstance(i, str) or not re.fullmatch(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*", i) for i in ids) or len(ids) != len(set(ids)):
        raise ValueError("Task catalog contains invalid or duplicate identities")
    if len({slug(task_id) for task_id in ids}) != len(ids):
        raise ValueError("Task identities collide in documentation paths")
    return sorted(ids)


def acquire(api: str) -> list[dict]:
    ids = catalog_ids(get(api, "/v1/tasks"))
    tasks = []
    for task_id in ids:
        task = {}
        for language in LANGUAGES:
            detail = get(api, f"/v1/tasks/{task_id}?lang={language}")
            if detail.get("task_id") != task_id or detail.get("method") != "POST" or detail.get("path") != f"/v1/tasks/{task_id}":
                raise ValueError(f"{task_id}: inconsistent Task identity")
            for key in ("response_schema", "error_schema"):
                if not isinstance(detail.get(key), dict) or not detail[key]:
                    raise ValueError(f"{task_id}: missing {key}; deploy the shared public contract first")
            task[language] = detail
        tasks.append(task)
    if catalog_ids(get(api, "/v1/tasks")) != ids:
        raise ValueError("Task availability changed during acquisition; retry on the next run")
    return tasks


def catalog_hash(tasks: list[dict]) -> str:
    return hashlib.sha256(json.dumps(tasks, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def request_schema(detail: dict) -> dict:
    if isinstance(detail.get("request_schema"), dict) and detail["request_schema"]:
        return copy.deepcopy(detail["request_schema"])
    # Older Social details publish individual metering field contracts. Preserve
    # their JSON Schema constraints, without inventing provider/options policy.
    properties, required = {}, []
    for field in detail["input"]:
        schema = copy.deepcopy(field.get("json_schema") or {})
        if not schema:
            kind = field.get("type", "string")
            schema = {"type": "array", "items": {"type": "string"}} if kind == "string_array" else {"type": kind}
        for key, target in (("min", "minimum"), ("max", "maximum"), ("min_length", "minLength"), ("max_length", "maxLength"), ("enum", "enum"), ("default", "default"), ("description", "description")):
            if field.get(key) is not None:
                schema[target] = field[key]
        properties[field["name"]] = schema
        if field.get("required"):
            required.append(field["name"])
    return {"type": "object", "required": ["input"], "properties": {"input": {"type": "object", "properties": properties, "required": required}}}


def pointer(document: dict, ref: str):
    if not ref.startswith("#/"):
        raise ValueError(f"Only local JSON pointers are supported: {ref}")
    value = document
    for token in ref[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def component(schema: dict, name: str) -> dict:
    """Lift referenced schemas into components understood by the docs renderer.

    Keep a finite reference graph, rather than recursively inlining objects.
    Mintlify does not render references into nested $defs, even in OpenAPI 3.1.
    All conditions and reference siblings retain their original semantics.
    """
    from jsonschema import Draft202012Validator
    Draft202012Validator.check_schema(schema)
    targets = {"#": schema}

    def map_schemas(value, transform):
        if not isinstance(value, dict):
            return value
        out = dict(value)
        for key, child in value.items():
            if key in ("$defs", "definitions", "properties", "patternProperties", "dependentSchemas"):
                out[key] = {field: map_schemas(item, transform) for field, item in child.items()}
            elif key in ("allOf", "anyOf", "oneOf", "prefixItems"):
                out[key] = [map_schemas(item, transform) for item in child]
            elif key in ("items", "additionalProperties", "unevaluatedProperties", "unevaluatedItems",
                         "contains", "propertyNames", "if", "then", "else", "not", "contentSchema"):
                out[key] = map_schemas(child, transform)
        return transform(out)

    def discover(value):
        if any(key in value for key in ("$id", "$anchor", "$dynamicRef")):
            raise ValueError("Schema resource identifiers require explicit support before publication")
        if "$ref" in value:
            ref = value["$ref"]
            targets[ref] = schema if ref == "#" else pointer(schema, ref)
        return value

    map_schemas(schema, discover)
    names = {"#": name}
    for index, ref in enumerate(sorted(set(targets) - {"#"})):
        label = re.sub(r"[^a-zA-Z0-9_-]", "_", ref.rsplit("/", 1)[-1])
        # Task component roots have one dot; lifted definitions have two, so
        # they cannot collide with another valid Task/section root.
        names[ref] = f"{name}.{index}_{label}"

    def relocate(value):
        value.pop("$defs", None)
        value.pop("definitions", None)
        if "$ref" in value:
            value["$ref"] = "#/components/schemas/" + names[value["$ref"]]
        return value

    return {names[ref]: map_schemas(target, relocate) for ref, target in targets.items()}



def openapi(tasks: list[dict], language: str, api: str) -> dict:
    schemas, paths = {}, {}
    c = COPY[language]
    for task in tasks:
        detail = task[language]
        stem = detail["task_id"]
        for kind, schema in (("request", request_schema(detail)), ("response", detail["response_schema"]), ("error", detail["error_schema"])):
            schemas.update(component(schema, stem + "_" + kind))
        ref = lambda kind: {"$ref": "#/components/schemas/" + stem + "_" + kind}
        paths[detail["path"]] = {"post": {
            "operationId": "task_" + stem, "summary": detail["name"], "description": detail.get("description", ""),
            "tags": [c["group"]],
            "parameters": [{"name": "Idempotency-Key", "in": "header", "schema": {"type": "string"}}],
            "requestBody": {"required": True, "content": {"application/json": {"schema": ref("request")}}},
            "responses": {"200": {"description": c["success"], "content": {"application/json": {"schema": ref("response")}}},
                          "default": {"description": c["error"], "content": {"application/json": {"schema": ref("error")}}}},
        }}
        # Preserve published billing metadata without interpreting a base tier
        # as the quote for every platform/parameter combination.
        paths[detail["path"]]["post"]["x-aisa-task"] = {
            key: copy.deepcopy(detail[key]) for key in ("version", "status", "strategy", "billing", "pricing") if key in detail
        }
    result = {"openapi": "3.1.0", "info": {"title": "AIsa Tasks", "version": "1"}, "servers": [{"url": api}],
              "security": [{"bearer": []}], "components": {"schemas": schemas, "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}}}, "paths": paths}
    from openapi_spec_validator import validate as validate_openapi
    validate_openapi(result)
    return result


def page_path(language: str, name: str) -> str:
    return ("zh/" if language == "zh" else "") + "tasks/" + name


def slug(task_id: str) -> str:
    return task_id.replace(".", "-")


def prose(text: str) -> str:
    return re.sub(r"([{}<>])", r"\\\1", text).replace("|", "\\|").replace("\n", " ")


def task_page(detail: dict, language: str, api: str) -> str:
    c = COPY[language]
    front = f'---\nopenapi: "{page_path(language, "openapi.json")} POST {detail["path"]}"\ntitle: {json.dumps(detail["name"], ensure_ascii=False)}\n---\n'
    billing = (detail.get("billing") or {}).get("mode")
    return front + f'\n`{detail["task_id"]}` · v{detail.get("version", 1)}\n\n{c["source"]}: `{api}`\n\n{c["contract"]}\n\n{c["strategy"]}: `{prose(detail.get("strategy", ""))}`\n\n## {c["billing"]}\n\n' + (c[billing] + "\n\n" if billing in ("fixed", "per_unit") else "") + c["price"] + "\n\n" + c["retry"] + "\n"


def overview(tasks: list[dict], language: str, api: str) -> str:
    c = COPY[language]
    lines = ["---", "title: " + json.dumps(c["group"], ensure_ascii=False), "---", "", c["intro"], "", f'{c["source"]}: `{api}`', "", f'## {c["list"]}', "", f'| {c["task"]} | {c["description"]} |', '| --- | --- |']
    for task in tasks:
        d = task[language]
        lines.append(f'| [`{d["task_id"]}`](/{page_path(language, slug(d["task_id"]))}) | {prose(d["name"])} |')
    return "\n".join(lines) + "\n"


def write(root: Path, tasks: list[dict], api: str) -> None:
    # Render/validate everything before touching the saved publication.
    files = {}
    for language in LANGUAGES:
        if tasks:
            files[page_path(language, "openapi.json")] = json.dumps(openapi(tasks, language, api), indent=2, ensure_ascii=False) + "\n"
            files[page_path(language, "overview.mdx")] = overview(tasks, language, api)
            for task in tasks:
                detail = task[language]
                files[page_path(language, slug(detail["task_id"]) + ".mdx")] = task_page(detail, language, api)
    docs = json.loads((root / "docs.json").read_text())
    for entry in docs["navigation"]["languages"]:
        language = entry["language"]
        if language not in LANGUAGES:
            continue
        c = COPY[language]
        tab = next(t for t in entry["tabs"] if t["tab"] == c["tab"])
        groups = [g for g in tab["groups"] if g.get("group") != c["group"]]
        if tasks:
            by_domain = {}
            for task in tasks:
                d = task[language]
                by_domain.setdefault(d["domain"], []).append(page_path(language, slug(d["task_id"])))
            group = {"group": c["group"], "icon": "list-check", "pages": [page_path(language, "overview")] + [{"group": c.get(domain, domain.title()), "pages": pages} for domain, pages in sorted(by_domain.items())]}
            at = next((i + 1 for i, g in enumerate(groups) if g.get("group") == c["overview"]), 0)
            groups.insert(at, group)
        tab["groups"] = groups
    for language in LANGUAGES:
        folder = root / page_path(language, "")
        if folder.exists():
            shutil.rmtree(folder)
    for path, text in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    (root / "docs.json").write_text(json.dumps(docs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def validate_publication(root: Path) -> set[str]:
    """Validate Task page bindings before the existing formal publisher exports."""
    from openapi_spec_validator import validate as validate_openapi
    pages = set()
    paths_by_language = []
    for language in LANGUAGES:
        folder = root / page_path(language, "")
        if not folder.exists():
            paths_by_language.append(set())
            continue
        document = json.loads((folder / "openapi.json").read_text())
        validate_openapi(document)
        expected = {"overview.mdx", "openapi.json"}
        paths = set(document["paths"])
        if not paths or document.get("servers") != [{"url": "https://api.aisa.one"}]:
            raise ValueError("Production Task publication requires a nonempty production contract")
        for path, methods in document["paths"].items():
            task_id = path.removeprefix("/v1/tasks/")
            if path != "/v1/tasks/" + task_id or not re.fullmatch(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*", task_id) or set(methods) != {"post"}:
                raise ValueError("Invalid Task operation in publication")
            name = slug(task_id) + ".mdx"
            expected.add(name)
            binding = f'openapi: "{page_path(language, "openapi.json")} POST {path}"'
            if binding not in (folder / name).read_text().splitlines():
                raise ValueError("Task page does not bind its published operation")
        if {p.name for p in folder.iterdir()} != expected:
            raise ValueError("Task publication contains missing or stale files")
        pages.update(page_path(language, name.removesuffix(".mdx")) for name in expected if name.endswith(".mdx"))
        paths_by_language.append(paths)
    if paths_by_language[0] != paths_by_language[1]:
        raise ValueError("Task languages publish different operations")
    from publication_surface import navigation_pages
    docs = json.loads((root / "docs.json").read_text())
    task_nav = [p for p in navigation_pages(docs) if p.startswith(("tasks/", "zh/tasks/"))]
    if len(task_nav) != len(set(task_nav)) or set(task_nav) != pages:
        raise ValueError("Task navigation differs from its verified pages")
    return pages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="https://api.aisa.one", choices=("https://api.aisa.one", "https://dev-api.aisa.one"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--expected-hash", default="", help="Refuse changes since the publication plan")
    args = parser.parse_args()
    tasks = acquire(args.api)
    if args.expected_hash and catalog_hash(tasks) != args.expected_hash:
        raise ValueError("Task contracts changed since planning; retry from fresh inputs")
    write(args.root, tasks, args.api)
    print(f"Published local docs for {len(tasks)} Tasks from {args.api}; no Tasks executed")


if __name__ == "__main__":
    main()
