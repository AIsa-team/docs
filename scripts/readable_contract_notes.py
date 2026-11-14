"""Readable MDX projection of published metadata; never estimates a request price."""
from __future__ import annotations

import html
import json
import re

BEGIN = "{/* aisa-contract-details:start */}"
END = "{/* aisa-contract-details:end */}"
PRICE_CARD_BEGIN = "{/* aisa-price-card:start */}"
PRICE_CARD_END = "{/* aisa-price-card:end */}"


def split_frontmatter(text):
    """Split a page without importing the locale generator (avoids a cycle)."""
    if not text.startswith('---\n'):
        raise ValueError('MDX is missing frontmatter')
    match = re.search(r'\n---(?:\n|$)', text[4:])
    if not match:
        raise ValueError('MDX frontmatter is not closed')
    start = 4 + match.start()
    body_start = 4 + match.end()
    return text[4:start], text[body_start:]

LEGACY_REFERENCE_NOTICES = (
    'This API reference has not been updated for the currently available endpoint.',
    '该接口文档尚未完成更新。',
    'This existing API reference is preserved. Its parameter details have not yet been verified for the currently available endpoint.',
    '此页面保留原有接口文档，当前可用接口的参数说明尚待核实。',
)


def clean_reference_notices(text):
    """Keep source-coverage diagnostics in reports, not endpoint instructions."""
    from pricing_prose import FENCES
    chunks = FENCES.split(text)
    pattern = r'<Warning>(?:' + '|'.join(map(re.escape, LEGACY_REFERENCE_NOTICES)) + r')</Warning>[ \t]*\n{0,2}'
    for index in range(0, len(chunks), 2):
        chunks[index] = re.sub(pattern, '', chunks[index])
    return ''.join(chunks)


def strip_generated_block(text):
    text = re.sub(r"^" + re.escape(PRICE_CARD_BEGIN) + r".*?" + re.escape(PRICE_CARD_END) + r"\n*", "\n", text, flags=re.S)
    text = re.sub(r"^" + re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n*", "\n", text, flags=re.S)
    text = re.sub(r"\n{1,2}" + re.escape(PRICE_CARD_BEGIN) + r".*?" + re.escape(PRICE_CARD_END) + r"\n", "\n", text, flags=re.S)
    return re.sub(r"\n{1,2}" + re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n", "\n", text, flags=re.S)


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
        lines += ["", t("**This endpoint is disabled and cannot be called. Its historical request and schema details are retained for reference; pricing is not published.**",
                        "**此接口已停用，无法调用。历史请求和 schema 仅保留供参考，当前未发布价格。**"), ""]
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
    # A disabled operation is an archive regardless of whether an old
    # x-aisa-pricing object survived in the historical contract.  That object
    # is provenance for internal review, not a current customer tariff.
    # Always replace it in the presentation layer so archived pages cannot
    # publish stale amounts after regeneration.
    if operation.get("x-aisa-status") == "disabled":
        pricing = {"kind": "unpriced"}
    elif not pricing and (document is not None or operation.get("operationId") or "x-aisa-status" in operation):
        # Preserved references can have no Runtime tariff at all. Say so in
        # the page without inventing a price, free access, or disabled status.
        pricing = {"kind": "unknown"}
    constraints = operation.get("x-aisa-constraints") or {}
    notes = constraints.get("notes") or []
    if not pricing and not notes and document is None:
        return ""
    lines = [BEGIN, ""]
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
    if document is not None:
        lines += request_details(operation, document, method, path, spec_path, language)
    lines += ["", END]
    return "\n".join(lines)


def price_card_block(operation, language="en"):
    """A managed price card; absent prices never become a headline warning."""
    from customer_price_presentation import customer_price_card
    if operation.get('x-aisa-status') == 'disabled':
        return ''  # Historical prices stay with the explicit archive details.
    card_summary = customer_price_card(operation.get('x-aisa-pricing') or {}, language)
    if not card_summary:
        return ''
    if card_summary.count('$') >= 2:
        card_summary = card_summary.replace('$', r'\$')
    return '\n'.join((PRICE_CARD_BEGIN, '', '<Info>', card_summary, '</Info>', '', PRICE_CARD_END))


def update_readable_block(text, operation, language="en", translate=None, **context):
    from pricing_prose import refresh_page_description
    text = refresh_page_description(clean_reference_notices(text), operation, language, translate)
    block = readable_block(operation, language, translate, **context)
    card = price_card_block(operation, language)
    if not block and not card:
        return strip_generated_block(text)
    if not text.startswith('---\n') and text.strip() == block.strip():
        return text
    text = strip_generated_block(text)
    if not text.startswith('---\n'):
        if not block:
            return text
        return text.rstrip() + "\n\n" + block + "\n"
    # Put only the concise customer price card below frontmatter. Detailed
    # pricing and the request contract remain after the authored endpoint
    # explanation, so readers see the overview and examples first.
    header, body = split_frontmatter(text)
    body = body.rstrip()
    if block:
        body += ('\n\n' if body else '') + block
    result = '---\n' + header + '\n---\n'
    if card:
        result += '\n' + card + '\n'
    if body:
        # Preserve authored leading whitespace exactly; the next generation
        # must not rewrite a legacy page merely because a managed block moved.
        result += body + '\n'
    return result
