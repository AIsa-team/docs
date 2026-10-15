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


def formula_text(formula):
    if not isinstance(formula, dict) or set(formula) - {"input", "inputs", "fixed_units", "unit_scale", "input_multiplier", "unit_rounding"}:
        return None
    if formula.get("unit_rounding") not in (None, "ceil"):
        return None
    names = formula.get("inputs", [formula["input"]] if "input" in formula else [])
    if not isinstance(names, list) or any(not isinstance(n, str) for n in names):
        return None
    expression = " × ".join(names)
    if expression and formula.get("unit_scale") not in (None, 0):
        expression = f"ceil(({expression}) / {formula['unit_scale']})"
    if expression and "input_multiplier" in formula:
        expression = f"({expression}) × {formula['input_multiplier']}"
    return " + ".join(str(v) for v in [formula.get("fixed_units", ""), expression] if v != "") or None


def request_details(operation, document, method, path, spec_path, language="en"):
    """Render effective request declarations and exact, cycle-safe ref closure."""
    zh = language == "zh"
    def t(en, cn): return cn if zh else en
    from compose_openapi import effective_object, referenced_components
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
    if "x-aisa-pricing" in operation:
        request["x-aisa-pricing"] = operation["x-aisa-pricing"]
    # Reuse the composer's instance-aware closure: example/default values that
    # happen to contain a "$ref" are data, and discriminator mappings are refs.
    components = referenced_components(request, document)
    for requirement in request.get("security", []):
        for name in requirement:
            scheme = document.get("components", {}).get("securitySchemes", {}).get(name)
            if scheme is None:
                if operation.get("x-aisa-status") == "disabled" and operation.get("x-aisa-contract-state") == "retained_legacy":
                    request.setdefault("x-aisa-documentation-limitations", []).append("unresolved_security_scheme:" + name)
                    continue
                raise ValueError("unresolved request security scheme: " + name)
            components.setdefault("securitySchemes", {})[name] = effective_object(scheme, document)
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
            lines.append("- **" + t("Request URL template", "请求 URL 模板") + ":** " + safe(server["url"].rstrip("/") + path))
    for parameter in parameters.values():
        required = t("required", "必填") if parameter.get("required") else t("optional", "可选")
        lines.append("- **" + safe(parameter.get("name", "?")) + ":** " + safe(str(parameter.get("in", "?"))) + "; " + required)
    revision = document.get("info", {}).get("x-aisa-document", {})
    if revision.get("facts_hash"):
        lines.append("- **" + t("Runtime facts", "Runtime 事实版本") + ":** " + safe(revision["facts_hash"]))
    lines += ["", "[" + t("Complete OpenAPI definition", "完整 OpenAPI 定义") + "](https://aisa.one/docs/" + spec_path + ")", "",
              t("Effective request and pricing declaration (including authentication and referenced schemas):", "有效请求与价格声明（包括认证和引用的 schema）："), ""]
    serialized = json.dumps(request, ensure_ascii=False, indent=2, allow_nan=False)
    # A source string cannot terminate this fenced code block.
    fence = "`" * max(3, 1 + max((len(run) for run in re.findall(r"`+", serialized)), default=0))
    return lines + [fence + "json", serialized, fence, ""]


def readable_block(operation, language="en", translate=None, *, document=None, method=None, path=None, spec_path=None):
    zh = language == "zh"
    def t(en, cn): return cn if zh else en
    def line(label, value): return f"- **{label}:** {safe(value)}"
    pricing = operation.get("x-aisa-pricing") or {}
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
        lines += [t("Published reference values are not an account-specific quote or a settled charge. For endpoints supporting X-AISA-Cost-Mode: quote, obtain a free quote for your exact request before execution; reconcile the settled cost with response metadata and Usage Logs. USD amounts use 1,000,000 integer micro-USD per dollar.", "公开参考值不是你的账户报价或最终扣费。对于支持 X-AISA-Cost-Mode: quote 的接口，执行前请针对完整请求获取免费报价；执行后通过响应费用元数据和 Usage Logs 核对结算费用。1 USD 等于 1,000,000 个整数 micro-USD。"), ""]
        labels = {
            "default_request_estimate_usd": t("Default request reference estimate (USD)", "默认请求参考估价（USD）"),
            "unit_rate_usd": t("Declared unit rate (USD)", "声明的单位费率（USD）"),
            "unit": t("Billing unit", "计费单位"),
            "cost_contract": t("Cost contract", "计费依据"),
            "customer_multiplier": t("Published reference multiplier", "公开参考倍率"),
            "units_per_count": t("Count multiplier before declared scaling", "缩放前的计数倍率"),
            "maximum_units": t("Declared maximum count/units", "声明的最大计数或单位数"),
            "unit_rounding": t("Unit rounding", "单位取整"),
            "unit_scale": t("Unit scaling divisor", "单位缩放除数"),
            "evidence_source": t("Settlement evidence source", "结算证据来源"),
        }
        lines += [line(label, pricing[key]) for key, label in labels.items() if key in pricing]
        if "units_per_count" in pricing:
            lines += [t("The count multiplier is not a standalone credit or USD price. Apply only the scaling and rounding explicitly declared by this contract; use a supported quote for the complete request.", "计数倍率本身不是 credit 单价或 USD 价格。只采用本定义明确声明的缩放和取整规则；完整请求的费用请使用接口支持的报价功能确认。"), ""]
        for key, heading in [("request_cost_drivers", t("Declared request billing units", "声明的请求计费单位")), ("reserve_plan_units", t("Reservation units (not settled usage)", "预留单位（不是结算用量）"))]:
            declaration = pricing.get(key)
            if not isinstance(declaration, dict):
                continue
            formula = declaration.get("formula") if key == "request_cost_drivers" else declaration
            expression = formula_text(formula) if (key == "request_cost_drivers" and declaration.get("kind") == "plan_units") or (key == "reserve_plan_units" and not formula.get("unit_scale")) else None
            lines += ["", "### " + heading, ""]
            lines += [line(t("Units", "单位数"), expression)] if expression else [t("See the complete definition for this declaration; no formula is inferred here.", "请查看完整定义中的声明；此处不推测公式。")]
            if key == "reserve_plan_units":
                # Public projection does not carry every discriminator needed for
                # Runtime's scaled response-count special case. Show source terms
                # without inventing an evaluation order.
                if formula.get("unit_scale"):
                    for name, label in [("fixed_units", t("Fixed units", "固定单位数")), ("input_multiplier", t("Declared input multiplier", "声明的输入倍率")), ("unit_scale", t("Declared scaling divisor", "声明的缩放除数")), ("unit_rounding", t("Declared rounding", "声明的取整规则"))]:
                        if name in formula:
                            lines.append(line(label, formula[name]))
                names = (formula or {}).get("inputs", [(formula or {}).get("input")])
                public = {p.get("name") for p in operation.get("parameters", []) if isinstance(p, dict)}
                # Only direct public JSON properties are unambiguous here. A
                # missing mapping is not evidence that a complex body is private.
                body_schema = operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
                public.update(body_schema.get("properties", {}))
                for name in names:
                    if isinstance(name, str):
                        lines.append(line(t("Public request parameter" if name in public else "Reservation input (public mapping not declared)", "公开请求参数" if name in public else "预留输入（未声明公开映射）"), name))
            for item in declaration.get("inputs", []) if key == "request_cost_drivers" else []:
                if not isinstance(item, dict):
                    continue
                def field(key):
                    value = item.get(key) or {}
                    return f"{value.get('source', '?')}.{value.get('selector', '?')}"
                kind = item.get("kind")
                if kind == "array_length":
                    detail = t(f"Number of entries in {field('field')}, including repeated entries.", f"{field('field')} 的元素数，包括重复项。")
                elif kind == "integer":
                    detail = t(f"Integer value of {field('field')}.", f"{field('field')} 的整数值。")
                elif kind == "calendar_buckets":
                    detail = t(f"Inclusive periods from {field('start')} to {field('end')}; granularity: {field('granularity')}. Daily: inclusive days; weekly: inclusive days / 7 rounded up; monthly: inclusive calendar months.", f"{field('start')} 到 {field('end')} 的时间段数，包含两端；粒度：{field('granularity')}。日：包含两端的天数；周：天数除以 7 向上取整；月：包含两端的日历月数。")
                else:
                    detail = t("See the complete definition; this input is not interpreted here.", "请查看完整定义；此处不解释该输入。")
                lines.append(line(safe(item.get("name", "input")), detail))
                for name, label in [("allowed_granularities", t("Allowed granularities", "允许粒度")), ("default_buckets", t("Estimator fallback periods (does not make required dates optional)", "估价器后备时间段数（不代表必填日期可以省略）")), ("min", t("Minimum", "最小值")), ("max", t("Maximum", "最大值"))]:
                    if name in item:
                        lines.append(line(label, item[name]))
                if item.get("open_end_boolean"):
                    lines.append(line(t("Open-end rule", "开放日期规则"), t(f"When {field('open_end_boolean')} is true, an omitted start becomes the first day of the current UTC month; the end becomes its last day. An explicit start is retained.", f"{field('open_end_boolean')} 为 true 时，省略的开始日期使用当前 UTC 月第一天，结束日期使用该月最后一天；保留显式开始日期。")))
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
