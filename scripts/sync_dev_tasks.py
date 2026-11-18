#!/usr/bin/env python3
"""Generate the dev Task pages from the dev Task catalog.

Tasks (POST /v1/tasks/{task_id}) are published on dev before production, so
the production contract preview that sync_dev_runtime.py builds has none.
This script reads the public catalog of the dev API instead:

  GET {api}/v1/tasks                 the installed tasks
  GET {api}/v1/tasks/{id}[?lang=zh]  input contract, route values and the
                                     fields each returns, output schema,
                                     hit rule, billing mode, strategy

and writes, in English and Chinese:

  tasks/overview.mdx, tasks/<domain>-<name>.mdx   (zh/tasks/... mirrored)
  tasks/openapi.json, zh/tasks/openapi.json       one POST per task
  a "Tasks" group in the API Reference tab of docs.json

The pages live outside api-reference/ and openapi/, so the Runtime generator
neither rewrites their URLs nor marks them as unverified production
references. Every run rewrites all of them, so a removed task disappears.
When the catalog cannot be read, nothing is written and the saved pages stay.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API = "https://dev-api.aisa.one"
GROUP = {"en": "Tasks", "zh": "任务"}
API_TAB = {"en": "API Reference", "zh": "API 参考"}
DOMAIN = {"social": {"en": "Social", "zh": "社媒"}}
PLATFORM = {"tiktok": "TikTok", "youtube": "YouTube", "x": "X", "reddit": "Reddit", "instagram": "Instagram"}
EXAMPLE_URL = {
    "tiktok": "https://www.tiktok.com/@nasa/video/7300000000000000000",
    "youtube": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "x": "https://x.com/NASA/status/1800000000000000000",
    "reddit": "https://www.reddit.com/r/space/comments/1abcdef/example/",
    "instagram": "https://www.instagram.com/p/C0000000000/",
}
EXAMPLE_VALUE = {"handle": "nasa", "query": "coffee", "topic": "travel", "community": "space",
                 "user_id": "UCLA_DiR1FfKNvjuUpBHmylQ", "language": "en", "region": "US"}

COPY = {
    "en": {
        "overview_title": "Tasks",
        "overview_description": "One call per job: AIsa picks the data source, maps the answer to one schema and charges only when it finds something.",
        "dev_note": "Tasks are live on the dev API (`https://dev-api.aisa.one`) and not yet in production.",
        "intro": "A task is one job, such as *get a post* or *search profiles*, with one input contract and one output schema for every platform it covers. AIsa routes the call to a data source, falls back to another one when the first fails or finds nothing, and maps every answer to the same fields, so the result reads the same whichever source answered.",
        "tasks_heading": "Available tasks",
        "col_task": "Task", "col_does": "What it does", "col_platforms": "Platforms", "col_billing": "Billing",
        "fixed": "per found call", "per_unit": "per returned item",
        "call_heading": "Calling a task",
        "call_text": "Send `POST /v1/tasks/{task_id}` with your AIsa API key. The body has the task input and optional options:",
        "options_heading": "Options",
        "options": [
            ("strategy", "`auto` (default for most tasks): try sources in order and stop at the first answer. `waterfall`: continue to the next source after a miss. `merge`: ask sources in parallel and merge their fields. `compare`: return each source's result side by side under `result.by_source`. `any_hit`: report found when any source finds it."),
            ("max_providers", "Lower the number of sources a strategy may try."),
            ("providers", "`{\"only\": [...]}` or `{\"exclude\": [...]}` to restrict sources."),
            ("detail", "`full` attaches each source's raw response in `meta.raw`."),
        ],
        "response_heading": "Response",
        "response_text": "Every task answers HTTP 200 with the same envelope:",
        "response_fields": [
            ("status", "`found`, `partial` (found, some fields missing) or `not_found`."),
            ("result", "The task's result, as documented on its page. A list task returns `{\"items\": [...]}`."),
            ("meta.missing_fields", "Fields of the result that are null, and why."),
            ("meta.approximate_fields", "Counts the platform only shows rounded (for example 1.2K)."),
            ("meta.sources / meta.attempts", "Which source answered and what each attempt returned."),
            ("meta.delivered", "Whether the call delivered a result, and so whether it was charged."),
        ],
        "billing_heading": "Billing",
        "billing_text": "A call is charged only when it delivers: `not_found` is free. A `fixed` task charges one price per found call, whatever the strategy. A `per_unit` task charges per returned item, up to `limit`. The live price of a task is in `pricing` of `GET /v1/tasks/{task_id}`; `X-AISA-Max-Price-USD` caps it and `X-AISA-Cost-Mode: quote` returns the price without running the task.",
        "idempotency_heading": "Retries",
        "idempotency_text": "Send an `Idempotency-Key` to retry safely: a key is charged at most once. A charged key returns the first result for 24 hours (`Idempotent-Replayed: true`); a key whose earlier call was not charged runs again.",
        "errors_heading": "Errors",
        "errors": [
            ("400", "`invalid_request`, or `unsupported_route` with the platforms the task supports"),
            ("404", "`task_not_found`, with the closest task ids"),
            ("422", "`invalid_input`, or `provider_rejected_input` when the platform rejects the input"),
            ("502", "`all_providers_failed`: every source failed; not charged"),
        ],
        "discover_heading": "Discovering tasks",
        "discover_text": "`GET /v1/tasks` lists the tasks (`?q=` searches, `?domain=` filters). `GET /v1/tasks/{task_id}` returns the input contract, the platforms and the fields each returns, the output schema, billing and price. Add `?lang=zh` for Chinese descriptions.",
        "platforms_heading": "Platforms and fields",
        "platforms_text": "A field not listed for a platform is `null` on that platform.",
        "col_platform": "Platform", "col_fields": "Fields returned",
        "input_heading": "Input",
        "col_field": "Field", "col_type": "Type", "col_required": "Required", "col_description": "Description",
        "yes": "yes", "no": "no",
        "found_heading": "Found or not found",
        "found_any": "The call is `found` when the result has {fields}.",
        "found_all": "The call is `found` when the result has all of {fields}.",
        "found_list": "The call is `found` when it returns at least one item.",
        "billing_fixed": "`fixed`: one price per found call. `not_found` is not charged.",
        "billing_per_unit": "`per_unit`: charged per returned item, up to `limit` (default {default}, at most {max}). An empty list is not charged.",
        "example_heading": "Example",
        "schema_note": "The full output schema, with every field's meaning, is in the response section above.",
        "or": " or ", "and": ", ",
    },
    "zh": {
        "overview_title": "任务",
        "overview_description": "一个任务一次调用：AIsa 选择数据源，把结果映射成统一的结构，只在找到结果时收费。",
        "dev_note": "任务目前只在 dev API（`https://dev-api.aisa.one`）上线，生产环境尚未开放。",
        "intro": "一个任务对应一件事，例如*获取帖子*或*搜索账号*。同一个任务在它支持的所有平台上，输入契约和输出结构都一样。AIsa 把调用路由到数据源，第一个失败或没找到时换下一个，并把每个结果映射到同样的字段，所以无论哪个数据源回答，结果的含义都相同。",
        "tasks_heading": "可用任务",
        "col_task": "任务", "col_does": "用途", "col_platforms": "平台", "col_billing": "计费",
        "fixed": "按找到的调用", "per_unit": "按返回条数",
        "call_heading": "调用任务",
        "call_text": "用 AIsa API key 发送 `POST /v1/tasks/{task_id}`。请求体包含任务输入和可选的 options：",
        "options_heading": "Options",
        "options": [
            ("strategy", "`auto`（多数任务的默认值）：按顺序尝试数据源，拿到第一个答复就停止。`waterfall`：未命中时继续下一个数据源。`merge`：并行请求多个数据源并合并字段。`compare`：在 `result.by_source` 里并列返回每个数据源的结果。`any_hit`：任一数据源找到即为 found。"),
            ("max_providers", "降低一个策略最多尝试的数据源数量。"),
            ("providers", "`{\"only\": [...]}` 或 `{\"exclude\": [...]}`，限定数据源。"),
            ("detail", "`full` 会在 `meta.raw` 里附上每个数据源的原始响应。"),
        ],
        "response_heading": "响应",
        "response_text": "所有任务都返回 HTTP 200 和同样的外层结构：",
        "response_fields": [
            ("status", "`found`、`partial`（找到了，但部分字段缺失）或 `not_found`。"),
            ("result", "任务结果，见各任务页面。列表类任务返回 `{\"items\": [...]}`。"),
            ("meta.missing_fields", "结果里为 null 的字段及原因。"),
            ("meta.approximate_fields", "平台只显示约数的计数（例如 1.2K）。"),
            ("meta.sources / meta.attempts", "由哪个数据源回答，以及每次尝试的结果。"),
            ("meta.delivered", "这次调用是否交付了结果，即是否收费。"),
        ],
        "billing_heading": "计费",
        "billing_text": "只有交付了结果才收费：`not_found` 不收费。`fixed` 任务每次找到收一次固定价，与策略无关。`per_unit` 任务按返回的条数收费，最多到 `limit`。任务的实时价格在 `GET /v1/tasks/{task_id}` 的 `pricing` 里；`X-AISA-Max-Price-USD` 设定价格上限，`X-AISA-Cost-Mode: quote` 只报价、不执行。",
        "idempotency_heading": "重试",
        "idempotency_text": "带上 `Idempotency-Key` 可以安全重试：同一个 key 最多扣一次费。已扣费的 key 在 24 小时内返回第一次的结果（`Idempotent-Replayed: true`）；之前没有扣费的 key 会重新执行。",
        "errors_heading": "错误",
        "errors": [
            ("400", "`invalid_request`，或 `unsupported_route`（返回任务支持的平台）"),
            ("404", "`task_not_found`，返回最相近的任务 ID"),
            ("422", "`invalid_input`，或平台判定输入有误时的 `provider_rejected_input`"),
            ("502", "`all_providers_failed`：所有数据源都失败，不收费"),
        ],
        "discover_heading": "查找任务",
        "discover_text": "`GET /v1/tasks` 列出所有任务（`?q=` 搜索，`?domain=` 过滤）。`GET /v1/tasks/{task_id}` 返回输入契约、支持的平台及各平台返回的字段、输出结构、计费方式和价格。加 `?lang=zh` 返回中文说明。",
        "platforms_heading": "平台与字段",
        "platforms_text": "某个平台没有列出的字段，在该平台上为 `null`。",
        "col_platform": "平台", "col_fields": "返回的字段",
        "input_heading": "输入",
        "col_field": "字段", "col_type": "类型", "col_required": "必填", "col_description": "说明",
        "yes": "是", "no": "否",
        "found_heading": "找到与未找到",
        "found_any": "结果中有 {fields} 时为 `found`。",
        "found_all": "结果中 {fields} 都有时为 `found`。",
        "found_list": "至少返回一条时为 `found`。",
        "billing_fixed": "`fixed`：每次找到收一次固定价。`not_found` 不收费。",
        "billing_per_unit": "`per_unit`：按返回的条数收费，最多到 `limit`（默认 {default}，最多 {max}）。空列表不收费。",
        "example_heading": "示例",
        "schema_note": "完整的输出结构及每个字段的含义，见上方的响应部分。",
        "or": " 或 ", "and": "、",
    },
}


class CatalogUnavailable(Exception):
    pass


def get(api: str, path: str) -> dict:
    request = urllib.request.Request(api + path, headers={"Accept": "application/json", "User-Agent": "aisa-docs-dev-tasks"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise CatalogUnavailable(f"{path}: {error}") from error


def acquire(api: str) -> list[dict]:
    """Every task with its English and Chinese detail, sorted by id."""
    listing = get(api, "/v1/tasks")
    tasks = []
    for item in sorted(listing.get("data") or [], key=lambda t: t["task_id"]):
        en = get(api, f"/v1/tasks/{item['task_id']}")
        zh = get(api, f"/v1/tasks/{item['task_id']}?lang=zh")
        for detail in (en, zh):
            if not isinstance(detail.get("output"), dict) or "schema" not in detail["output"]:
                raise CatalogUnavailable(f"{item['task_id']}: the detail has no output schema yet")
        tasks.append({"en": en, "zh": zh})
    if not tasks:
        raise CatalogUnavailable("the catalog lists no task")
    return tasks


def slug(task_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", task_id.lower()).strip("-")


def page_path(language: str, name: str) -> str:
    return ("zh/" if language == "zh" else "") + "tasks/" + name


def mdx(text: str) -> str:
    """Escape prose for MDX: braces and angle brackets are syntax."""
    return re.sub(r"([{}<>])", lambda m: "\\" + m.group(1), text or "")


def pipe(text: str) -> str:
    return text.replace("|", "\\|")


def cell(text: str) -> str:
    return mdx(text).replace("|", "\\|").replace("\n", " ")


def input_schema(field: dict) -> dict:
    kind = field.get("type") or "string"
    schema: dict = {"type": "array", "items": {"type": "string"}} if kind == "string_array" else {"type": kind}
    for key, target in (("min", "minimum"), ("max", "maximum"), ("min_length", "minLength"), ("max_length", "maxLength")):
        if field.get(key) is not None:
            schema[target] = field[key]
    if field.get("enum"):
        schema["enum"] = field["enum"]
    if field.get("default") is not None:
        schema["default"] = field["default"]
    if field.get("description"):
        schema["description"] = field["description"]
    return schema


def example_input(detail: dict) -> dict:
    platform = None
    out: dict = {}
    for field in detail.get("input") or []:
        name = field["name"]
        if name == detail.get("route_by") and field.get("enum"):
            platform = field["enum"][0]
            routes = [r["value"] for r in detail.get("routes") or []]
            for preferred in routes:
                if preferred in field["enum"]:
                    platform = preferred
                    break
            out[name] = platform
        elif field.get("required"):
            out[name] = EXAMPLE_URL.get(platform or "", "https://example.com") if name == "url" else (
                field["enum"][0] if field.get("enum") else EXAMPLE_VALUE.get(name, name))
    if not any(f.get("required") and f["name"] != detail.get("route_by") for f in detail.get("input") or []):
        for name in ("handle", "url"):
            if any(f["name"] == name for f in detail.get("input") or []):
                out[name] = EXAMPLE_URL.get(platform or "", "https://example.com") if name == "url" else EXAMPLE_VALUE[name]
                break
    return out


def openapi(tasks: list[dict], language: str, api: str) -> dict:
    copy = COPY[language]
    paths = {}
    for task in tasks:
        detail = task[language]
        properties = {f["name"]: input_schema(f) for f in detail.get("input") or []}
        required = [f["name"] for f in detail.get("input") or [] if f.get("required")]
        body_input = {"type": "object", "properties": properties}
        if required:
            body_input["required"] = required
        envelope = {
            "type": "object",
            "required": ["task", "version", "status", "result", "meta"],
            "properties": {
                "task": {"type": "string", "const": detail["task_id"]},
                "version": {"type": "integer"},
                "status": {"type": "string", "enum": ["found", "partial", "not_found"]},
                "result": detail["output"]["schema"],
                "meta": {"type": "object", "properties": {
                    "sources": {"type": "array", "items": {"type": "object"}},
                    "attempts": {"type": "array", "items": {"type": "object"}},
                    "missing_fields": {"type": "object", "additionalProperties": {"type": "string"}},
                    "approximate_fields": {"type": "array", "items": {"type": "string"}},
                    "delivered": {"type": "boolean"},
                }},
            },
        }
        paths[detail["path"]] = {"post": {
            "operationId": "task_" + detail["task_id"].replace(".", "_"),
            "summary": detail["name"],
            "description": detail.get("description") or "",
            "tags": [GROUP[language]],
            "parameters": [{"name": "Idempotency-Key", "in": "header", "required": False, "schema": {"type": "string"}}],
            "requestBody": {"required": True, "content": {"application/json": {
                "schema": {"type": "object", "required": ["input"], "properties": {
                    "input": body_input,
                    "options": {"type": "object", "properties": {
                        "strategy": {"type": "string", "enum": ["auto", "waterfall", "merge", "compare", "any_hit"]},
                        "max_providers": {"type": "integer", "minimum": 1},
                        "detail": {"type": "string", "enum": ["full"]},
                    }},
                }},
                "example": {"input": example_input(detail)},
            }}},
            "responses": {"200": {"description": copy["response_text"].rstrip(":："), "content": {"application/json": {"schema": envelope}}}},
        }}
    return {
        "openapi": "3.1.0",
        "info": {"title": "AIsa Tasks", "version": "dev"},
        "servers": [{"url": api}],
        "security": [{"bearer": []}],
        "components": {"securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}}},
        "paths": paths,
    }


def platforms(detail: dict) -> str:
    return ", ".join(PLATFORM.get(r["value"], r["value"]) for r in detail.get("routes") or []) or "-"


def overview(tasks: list[dict], language: str) -> str:
    c = COPY[language]
    prefix = "/zh/tasks/" if language == "zh" else "/tasks/"
    lines = ["---", f"title: {json.dumps(c['overview_title'], ensure_ascii=False)}",
             f"description: {json.dumps(c['overview_description'], ensure_ascii=False)}", "---", "",
             f"<Note>{c['dev_note']}</Note>", "", c["intro"], "",
             f"## {c['tasks_heading']}", "",
             f"| {c['col_task']} | {c['col_does']} | {c['col_platforms']} | {c['col_billing']} |", "| --- | --- | --- | --- |"]
    for task in tasks:
        d = task[language]
        mode = (d.get("billing") or {}).get("mode", "fixed")
        lines.append(f"| [`{d['task_id']}`]({prefix}{slug(d['task_id'])}) | {cell(d['name'])} | {platforms(d)} | {c.get(mode, mode)} |")
    lines += ["", f"## {c['call_heading']}", "", c["call_text"], "", "```bash",
              "curl -sS https://dev-api.aisa.one/v1/tasks/social.get_post \\",
              "  -H \"Authorization: Bearer $AISA_API_KEY\" \\",
              "  -H 'Content-Type: application/json' \\",
              "  -d '{\"input\": {\"platform\": \"tiktok\", \"url\": \"" + EXAMPLE_URL["tiktok"] + "\"}, \"options\": {\"strategy\": \"auto\"}}'",
              "```", "", f"### {c['options_heading']}", "", f"| | |", "| --- | --- |"]
    lines += [f"| `{k}` | {pipe(v)} |" for k, v in c["options"]]
    lines += ["", f"## {c['response_heading']}", "", c["response_text"], "", "```json",
              json.dumps({"task": "social.get_post", "version": 1, "status": "found",
                          "result": {"platform": "tiktok", "post_id": "7300000000000000000", "views": 1200},
                          "meta": {"sources": [], "attempts": [], "missing_fields": {}, "approximate_fields": [], "delivered": True}},
                         indent=2), "```", "", "| | |", "| --- | --- |"]
    lines += [f"| `{k}` | {pipe(v)} |" for k, v in c["response_fields"]]
    lines += ["", f"## {c['billing_heading']}", "", c["billing_text"], "",
              f"## {c['idempotency_heading']}", "", c["idempotency_text"], "",
              f"## {c['errors_heading']}", "", "| HTTP | |", "| --- | --- |"]
    lines += [f"| {k} | {v} |" for k, v in c["errors"]]
    lines += ["", f"## {c['discover_heading']}", "", c["discover_text"], ""]
    return "\n".join(lines)


def task_page(detail: dict, language: str) -> str:
    c = COPY[language]
    spec = ("zh/" if language == "zh" else "") + "tasks/openapi.json"
    lines = ["---", f"openapi: \"{spec} POST {detail['path']}\"",
             f"title: {json.dumps(detail['name'], ensure_ascii=False)}",
             f"description: {json.dumps(detail.get('description') or '', ensure_ascii=False)}", "---", "",
             f"<Note>{c['dev_note']}</Note>", "", f"`{detail['task_id']}` · v{detail.get('version', 1)}", ""]
    if detail.get("routes"):
        lines += [f"## {c['platforms_heading']}", "", c["platforms_text"], "",
                  f"| {c['col_platform']} | {c['col_fields']} |", "| --- | --- |"]
        for route in detail["routes"]:
            lines.append(f"| {PLATFORM.get(route['value'], route['value'])} | {', '.join('`' + f + '`' for f in route['fields'])} |")
        lines.append("")
    lines += [f"## {c['input_heading']}", "",
              f"| {c['col_field']} | {c['col_type']} | {c['col_required']} | {c['col_description']} |", "| --- | --- | --- | --- |"]
    for field in detail.get("input") or []:
        kind = field.get("type", "")
        if field.get("enum"):
            kind += ": " + ", ".join(f"`{v}`" for v in field["enum"])
        lines.append(f"| `{field['name']}` | {kind} | {c['yes'] if field.get('required') else c['no']} | {cell(field.get('description', ''))} |")
    lines += ["", f"## {c['found_heading']}", ""]
    hit = detail.get("hit_rule") or {}
    output = detail["output"]
    if output.get("list"):
        lines.append(c["found_list"])
    elif hit.get("required"):
        lines.append(c["found_all"].format(fields=c["and"].join(f"`{f}`" for f in hit["required"])))
    elif hit.get("any_of"):
        lines.append(c["found_any"].format(fields=c["or"].join(f"`{f}`" for f in hit["any_of"])))
    billing = detail.get("billing") or {}
    lines += ["", f"## {c['billing_heading']}", ""]
    if billing.get("mode") == "per_unit":
        lines.append(c["billing_per_unit"].format(default=billing.get("default_limit", "-"), max=billing.get("max_limit", "-")))
    else:
        lines.append(c["billing_fixed"])
    lines += ["", f"## {c['example_heading']}", "", "```bash",
              f"curl -sS https://dev-api.aisa.one{detail['path']} \\",
              "  -H \"Authorization: Bearer $AISA_API_KEY\" \\",
              "  -H 'Content-Type: application/json' \\",
              "  -d '" + json.dumps({"input": example_input(detail)}, ensure_ascii=False) + "'",
              "```", "", c["schema_note"], ""]
    return "\n".join(lines)


def nav_group(tasks: list[dict], language: str) -> dict:
    by_domain: dict[str, list[str]] = {}
    for task in tasks:
        d = task[language]
        by_domain.setdefault(d["domain"], []).append(page_path(language, slug(d["task_id"])))
    pages: list = [page_path(language, "overview")]
    for domain, items in sorted(by_domain.items()):
        pages.append({"group": DOMAIN.get(domain, {}).get(language, domain.title()), "pages": items})
    return {"group": GROUP[language], "icon": "list-check", "pages": pages}


def place_group(docs: dict, tasks: list[dict]) -> None:
    for entry in docs["navigation"]["languages"]:
        language = entry["language"]
        if language not in GROUP:
            continue
        tab = next(t for t in entry["tabs"] if t["tab"] == API_TAB[language])
        groups = [g for g in tab["groups"] if g.get("group") != GROUP[language]]
        at = next((i + 1 for i, g in enumerate(groups) if g.get("group") in ("Overview", "概览")), 0)
        groups.insert(at, nav_group(tasks, language))
        tab["groups"] = groups


def write(root: Path, tasks: list[dict], api: str) -> list[str]:
    written = []
    for language in ("en", "zh"):
        folder = root / page_path(language, "")
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        files = {"overview.mdx": overview(tasks, language),
                 "openapi.json": json.dumps(openapi(tasks, language, api), indent=2, ensure_ascii=False) + "\n"}
        for task in tasks:
            files[slug(task[language]["task_id"]) + ".mdx"] = task_page(task[language], language)
        for name, text in files.items():
            (folder / name).write_text(text if text.endswith("\n") else text + "\n")
            written.append(page_path(language, name))
    docs_path = root / "docs.json"
    docs = json.loads(docs_path.read_text())
    place_group(docs, tasks)
    docs_path.write_text(json.dumps(docs, indent=2, ensure_ascii=False) + "\n")
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default=DEFAULT_API, help="API origin serving /v1/tasks")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        tasks = acquire(args.api.rstrip("/"))
    except CatalogUnavailable as error:
        print(f"warning: Task catalog unavailable, keeping the saved Task pages: {error}", file=sys.stderr)
        return 0
    written = write(args.root, tasks, args.api.rstrip("/"))
    print(f"wrote {len(written)} Task files for {len(tasks)} tasks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
