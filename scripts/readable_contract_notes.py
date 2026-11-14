"""Readable MDX projection of published metadata; never estimates a request price."""
from __future__ import annotations

import html
import json
import re

BEGIN = "{/* aisa-contract-details:start */}"
END = "{/* aisa-contract-details:end */}"
# Spec #1285 R1: shown when Runtime has no current production evidence for
# this operation's request example (x-aisa-verification.state == pending).
PENDING_NOTICE_EN = ("> **Request example pending verification.** The request example for this endpoint has not yet "
                     "been verified in production. Static examples describe the request format; replace sample values with your own. Check the estimated price with a "
                     "free quote request (`X-AISA-Cost-Mode: quote`) before running it.")
PENDING_NOTICE_ZH = ("> **请求示例待验证。** 此接口的请求示例尚未在生产环境验证。静态示例用于说明请求格式，请替换为自己的参数。"
                     "正式调用前，可用免费的报价模式（`X-AISA-Cost-Mode: quote`）查看预估费用。")


def strip_generated_block(text):
    return re.sub(r"\n\n" + re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n", "", text, flags=re.S)


def safe(value):
    """Metadata is text, never executable MDX or Markdown structure."""
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return ''.join(f"&#{ord(c)};" if c in '`*_[]{}<>|\\\n\r' else html.escape(c, quote=True) for c in value)


def code(value):
    """Literal inline code: no autolink, emphasis or MDX expression, so URLs keep raw `_` and `{}`."""
    value = re.sub(r"[\r\n]+", " ", value)
    fence = "`" * (1 + max((len(run) for run in re.findall(r"`+", value)), default=0))
    pad = " " if value[:1] == "`" or value[-1:] == "`" else ""
    return fence + pad + value + pad + fence


def request_details(operation, document, method, path, spec_path, language="en"):
    """Render effective request declarations and exact, cycle-safe ref closure."""
    zh = language == "zh"
    def t(en, cn): return cn if zh else en
    from compose_openapi import effective_object, effective_security, referenced_components
    def resolve(value):
        return effective_object(value, document)
    item = document.get("paths", {}).get(path, {})
    parameters = {}
    for value in item.get("parameters", []) + operation.get("parameters", []):
        value = resolve(value)
        parameters[(value.get("in"), value.get("name"))] = value
    request = {"operationId": operation.get("operationId"), "method": method.upper(), "path": path,
               "servers": operation.get("servers", item.get("servers", document.get("servers", []))),
               "parameters": list(parameters.values())}
    if "security" in operation or "security" in document:
        request["security"] = operation.get("security", document.get("security"))
    if "requestBody" in operation:
        request["requestBody"] = operation["requestBody"]
    if "x-aisa-status" in operation:
        request["x-aisa-status"] = operation["x-aisa-status"]
    # Reuse the composer's instance-aware closure: example/default values that
    # happen to contain a "$ref" are data, and discriminator mappings are refs.
    components = referenced_components(request, document)
    schemes, missing_schemes = effective_security(operation, document)
    if schemes:
        components.setdefault("securitySchemes", {}).update(schemes)
    if missing_schemes:
        request["x-aisa-documentation-limitations"] = [
            "unresolved_security_scheme:" + name for name in missing_schemes]
    if components:
        request["components"] = components
    lines = ["## " + t("Request contract", "请求规范"), "",
             "- **" + t("Method and path", "方法与路径") + ":** " + safe(method.upper() + " " + path)]
    if "x-aisa-status" in operation:
        lines.append("- **" + t("Availability", "可用状态") + ":** " + safe(operation["x-aisa-status"]))
    if operation.get("x-aisa-status") == "disabled":
        lines += ["", t("**This endpoint is disabled and cannot be called. Its historical request, schema and pricing declarations are retained for reference.**",
                        "**此接口已停用，无法调用。历史请求、schema 和价格声明仅保留供参考。**"), ""]
    for limitation in request.get("x-aisa-documentation-limitations", []):
        lines.append("- **" + t("Incomplete historical declaration (disabled)", "未启用的历史声明不完整") + ":** " + safe(limitation))
    for server in request["servers"]:
        if isinstance(server, dict) and isinstance(server.get("url"), str):
            lines.append("- **" + t("Request URL template", "请求 URL 模板") + ":** " + code(server["url"].rstrip("/") + path))
    for parameter in parameters.values():
        required = t("required", "必填") if parameter.get("required") else t("optional", "可选")
        lines.append("- **" + safe(parameter.get("name", "?")) + ":** " + safe(str(parameter.get("in", "?"))) + "; " + required)
    # Spec #1285 R1: projected catalogs link their customer-facing copy
    # (openapi-public/, provenance removed) instead of the formal file.
    from public_projection import link_catalogs, public_path
    lines += ["", "[" + t("Complete OpenAPI definition", "完整 OpenAPI 定义") + "](https://aisa.one/docs/" + public_path(spec_path, link_catalogs()) + ")", "",
              t("Effective request declaration (including authentication and referenced schemas):", "有效请求声明（包括认证和引用的 schema）："), ""]
    from public_projection import strip
    request = strip(request)
    serialized = json.dumps(request, ensure_ascii=False, indent=2, allow_nan=False)
    # A source string cannot terminate this fenced code block.
    fence = "`" * max(3, 1 + max((len(run) for run in re.findall(r"`+", serialized)), default=0))
    return lines + [fence + "json", serialized, fence, ""]


LATENCY_TYPICAL = {
    "fast": ("Typically returns within 10 seconds.", "通常 10 秒内返回。"),
    "slow": ("Typically returns within 30 seconds.", "通常 30 秒内返回。"),
    "very_slow": ("Typically takes longer than 30 seconds.", "通常需要 30 秒以上。"),
}


def pagination_and_latency_lines(operation, language="en"):
    """Public, supplier-neutral guidance from x-aisa-pagination and x-aisa-latency."""
    zh = language == "zh"
    def t(en, cn): return cn if zh else en
    def text(value): return safe(value) if isinstance(value, str) else ""
    lines = []
    pagination = operation.get("x-aisa-pagination")
    request = pagination.get("request") if isinstance(pagination, dict) else None
    param = request.get("param") if isinstance(request, dict) else None
    if isinstance(param, str) and param:
        where = request.get("in")
        location = (t(" (request body field)", "（请求体字段）") if where == "body"
                    else t(" (query parameter)", "（查询参数）") if where == "query" else "")
        lines += ["## " + t("Pagination", "翻页"), "",
                  "- " + text(t("Pass ", "把 ")) + code("aisa_pagination.next_cursor")
                  + text(t(" as ", " 作为 ")) + code(param) + text(location)
                  + text(t(" to fetch the next page; stop when ", ("" if location else " ") + "传入即可获取下一页；")) + code("aisa_pagination.has_more")
                  + text(t(" is false.", " 为 false 时停止。")),
                  "- " + text(t("The same values are returned in the ", "响应头 ")) + code("X-AISA-Has-More")
                  + text(t(" and ", " 与 ")) + code("X-AISA-Next-Cursor")
                  + text(t(" response headers.", " 返回相同的值。"))]
        if pagination.get("style") == "next_link":
            lines.append("- " + text(t("The cursor is an opaque value; pass it back unchanged.", "游标是不透明值，请原样传回。")))
        size_param = request.get("size_param")
        if isinstance(size_param, str) and size_param:
            lines.append("- " + text(t("Page size parameter: ", "页大小参数：")) + code(size_param))
        max_pages = pagination.get("max_pages")
        if type(max_pages) is int and max_pages > 0:
            lines.append("- " + text(t(f"At most {max_pages} pages can be fetched.", f"最多可获取 {max_pages} 页。")))
        if pagination.get("ordering") == "unstable":
            item_id = pagination.get("item_id")
            if isinstance(item_id, str) and item_id:
                lines.append("- " + text(t("Results may repeat across pages; de-duplicate by ", "结果可能跨页重复，请按 "))
                             + code(item_id) + text(t(".", " 去重。")))
            else:
                lines.append("- " + text(t("Results may repeat across pages; de-duplicate by a stable id.",
                                           "结果可能跨页重复，请按稳定的 ID 去重。")))
        lines.append("")
    latency = operation.get("x-aisa-latency")
    latency = latency if isinstance(latency, dict) else {}
    typical = LATENCY_TYPICAL.get(operation.get("x-aisa-latency-class"))
    timeout = latency.get("timeout_seconds")
    if typical or type(timeout) is int:
        lines += ["## " + t("Response time", "响应时间"), ""]
        if typical:
            lines.append("- " + text(t(*typical)))
        if type(timeout) is int:
            lines.append("- " + text(t(
                f"The server answers with a result or HTTP 503 within {timeout} seconds; set your client timeout slightly above that (for example {timeout + 5} seconds).",
                f"服务端会在 {timeout} 秒内返回结果或 HTTP 503；请把客户端超时设置得略高于此值（例如 {timeout + 5} 秒）。")))
        lines.append("")
    return lines


def readable_block(operation, language="en", translate=None, *, document=None, method=None, path=None, spec_path=None):
    zh = language == "zh"
    def t(en, cn): return cn if zh else en
    def line(label, value): return f"- **{label}:** {safe(value)}"
    pricing = operation.get("x-aisa-pricing") or {}
    # Historical disabled operations may legitimately have no runtime tariff.
    # Keep that absence out of the machine contract while still giving the
    # archive page an explicit customer-facing unavailable-price explanation.
    # Legacy labels describe a cost tier, not a published price or billing rule.
    # Keep unknown modern declarations distinct from this known historical shape.
    legacy_labels = isinstance(pricing, dict) and set(pricing) <= {"cost_tier", "model"}
    if operation.get("x-aisa-status") == "disabled" and (not pricing or legacy_labels):
        pricing = {"kind": "unpriced"}
    elif not pricing and (document is not None or operation.get("operationId") or "x-aisa-status" in operation):
        # Preserved references can have no Runtime tariff at all. Say so in
        # the page without inventing a price, free access, or disabled status.
        pricing = {"kind": "unknown"}
    constraints = operation.get("x-aisa-constraints") or {}
    notes = constraints.get("notes") or []
    observations = operation.get("x-aisa-observed-responses") or {}
    pending = (operation.get("x-aisa-verification") or {}).get("state") == "pending"
    behaviour = pagination_and_latency_lines(operation, language)
    if not pricing and not notes and not pending and not observations and not behaviour and document is None:
        return ""
    lines = [BEGIN, ""]
    if pending:
        lines += [PENDING_NOTICE_ZH if zh else PENDING_NOTICE_EN, ""]
    if document is not None:
        lines += request_details(operation, document, method, path, spec_path, language)
    if observations:
        lines += ["## " + t("Observed response structure", "已观察到的响应结构"), "",
                  t("The response observations below come from successful probes or sampled requests. They are partial: fields and types may vary, and no field is guaranteed to be present. Reviewed response definitions take precedence. No real response values are published.",
                    "以下结构来自探针或抽样请求的成功结果，只反映已观察到的部分：字段和类型可能变化，不保证每次都有。已有正式响应定义优先；这里不发布真实响应值。"), ""]
        for status, observation in sorted(observations.items()):
            lines += [line(t("HTTP status / last observed", "HTTP 状态 / 最近观察日期"), status + " / " + observation["last_observed"]), "",
                      "```json", json.dumps(observation["schema"], ensure_ascii=False, indent=2), "```", ""]
    if pricing or notes:
        lines += ["## " + t("Cost and request rules", "费用与请求规则"), ""]
    if pricing:
        from pricing_prose import pricing_summary
        summary = pricing_summary(pricing, language)
        # Paired currency signs would become inline math in Mintlify MDX.
        if summary.count("$") >= 2:
            summary = summary.replace("$", r"\$")
        lines += [summary, ""]
    if notes:
        lines += ["", "### " + t("Request constraints and usage notes", "请求约束与用量说明"), ""]
        for note in notes:
            if isinstance(note, str):
                if zh and translate:
                    note = translate(note)
                lines.append("- " + safe(note))
    if behaviour:
        lines += ([""] if lines[-1] != "" else []) + behaviour[:-1]
    lines += ["", END]
    return "\n".join(lines)


def update_readable_block(text, operation, language="en", translate=None, **context):
    block = readable_block(operation, language, translate, **context)
    if not block:
        return strip_generated_block(text)
    pattern = re.escape(BEGIN) + r".*?" + re.escape(END)
    if re.search(pattern, text, re.S):
        return re.sub(pattern, lambda _: block, text, flags=re.S)
    return text + "\n\n" + block + "\n"
