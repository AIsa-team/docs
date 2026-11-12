"""Readable MDX projection of published metadata; never estimates a request price."""
from __future__ import annotations

import html
import json
import re

BEGIN = "{/* aisa-contract-details:start */}"
END = "{/* aisa-contract-details:end */}"


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
    revision = document.get("info", {}).get("x-aisa-document", {})
    if revision.get("facts_hash"):
        lines.append("- **" + t("Runtime facts", "Runtime 事实版本") + ":** " + safe(revision["facts_hash"]))
    lines += ["", "[" + t("Complete OpenAPI definition", "完整 OpenAPI 定义") + "](https://aisa.one/docs/" + spec_path + ")", "",
              t("Effective request declaration (including authentication and referenced schemas):", "有效请求声明（包括认证和引用的 schema）："), ""]
    serialized = json.dumps(request, ensure_ascii=False, indent=2, allow_nan=False)
    # A source string cannot terminate this fenced code block.
    fence = "`" * max(3, 1 + max((len(run) for run in re.findall(r"`+", serialized)), default=0))
    return lines + [fence + "json", serialized, fence, ""]


def readable_block(operation, language="en", translate=None, *, document=None, method=None, path=None, spec_path=None):
    zh = language == "zh"
    def t(en, cn): return cn if zh else en
    pricing = operation.get("x-aisa-pricing") or {}
    # Historical disabled operations may legitimately have no runtime tariff.
    # Keep that absence out of the machine contract while still giving the
    # archive page an explicit customer-facing unavailable-price explanation.
    # Legacy labels describe a cost tier, not a published price or billing rule.
    # Keep unknown modern declarations distinct from this known historical shape.
    legacy_labels = isinstance(pricing, dict) and set(pricing) <= {"cost_tier", "model"}
    if operation.get("x-aisa-status") == "disabled" and (not pricing or legacy_labels):
        pricing = {"kind": "unpriced"}
    constraints = operation.get("x-aisa-constraints") or {}
    notes = constraints.get("notes") or []
    if not pricing and not notes and document is None:
        return ""
    lines = [BEGIN, ""]
    if document is not None:
        lines += request_details(operation, document, method, path, spec_path, language)
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
