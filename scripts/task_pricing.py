"""Render the public Task customer price contract; never infer supplier prices."""
from decimal import Decimal
import re


def text(value):
    return re.sub(r"([{}<>`])", r"\\\1", str(value)).replace("|", "\\|").replace("\n", " ")


def integer(value, *, positive=False):
    if type(value) is not int or value < (1 if positive else 0):
        raise ValueError("Invalid Task price or quantity")
    return value


def usd(micros):
    value = format(Decimal(integer(micros)) / Decimal(1_000_000), "f")
    return value.rstrip("0").rstrip(".") if "." in value else value


def tiers(value):
    if not isinstance(value, dict) or not value or any(not isinstance(key, str) or not key for key in value):
        raise ValueError("Missing Task price tiers")
    for amount in value.values():
        integer(amount)
    return value


def field(detail, name):
    if not isinstance(name, str) or not name:
        raise ValueError("Missing Task pricing input")
    return next((f.get("selector") or f["name"] for f in detail.get("input", []) if f.get("name") == name), name)


def price_selection_sort_key(item):
    key = item[0]
    if isinstance(key, str) and key.isdigit():
        return (0, int(key), key)
    return (1, 0, str(key))


def pricing_markdown(detail, language):
    """Refuse incomplete/unknown billing semantics before replacing any pages."""
    zh = language == "zh"
    p = detail.get("pricing")
    if not isinstance(p, dict) or p.get("currency") != "USD" or type(p.get("apply_plan_multiplier")) is not bool:
        raise ValueError("Task requires the complete published USD customer price contract")
    integer(p.get("revision"), positive=True)
    kind, unit = p.get("kind"), p.get("unit")
    if (kind, unit) not in {("fixed_success", "successful_request"), ("per_unit", "delivered_item"), ("per_unit", "requested_unit")}:
        raise ValueError("Unsupported Task customer pricing kind or unit")
    if (detail.get("billing") or {}).get("mode") != {"fixed_success": "fixed", "per_unit": "per_unit"}[kind]:
        raise ValueError("Task billing and customer price disagree")
    base = tiers(p.get("tiers_micros_usd"))
    labels = {
        "successful_request": "每次成功请求" if zh else "Per successful request",
        "delivered_item": "每条实际交付结果" if zh else "Per delivered item",
        "requested_unit": "每个请求单位" if zh else "Per requested unit",
    }
    price_by = p.get("price_by")
    rows, scale = [], None
    if price_by is not None:
        if not isinstance(price_by, dict) or not isinstance(price_by.get("values"), dict) or not price_by["values"]:
            raise ValueError("Invalid Task parameter prices")
        selector = field(detail, price_by.get("input"))
        for value, rates in sorted(price_by["values"].items(), key=price_selection_sort_key):
            if not isinstance(value, str) or not value:
                raise ValueError("Invalid Task price selection")
            rows.append((f"{selector} = {value}", tiers(rates), value))
        fallback = price_by.get("unknown_uses_default_tiers", False)
        if type(fallback) is not bool:
            raise ValueError("Invalid Task price fallback")
        if fallback:
            rows.append(("其他或未提供值" if zh else "Other or omitted value", base, None))
        scale = price_by.get("request_scale")
        if scale is not None:
            if kind != "fixed_success" or not isinstance(scale, dict):
                raise ValueError("Unsupported Task request size pricing")
            field(detail, scale.get("input"))
            for key in ("unit_size", "max_quantity", "round_up_micros_usd"):
                integer(scale.get(key), positive=True)
            if (not isinstance(scale.get("values"), list) or not scale["values"] or
                    any(value not in price_by["values"] for value in scale["values"])):
                raise ValueError("Invalid Task scaled price selections")
    else:
        rows.append(("所有有效输入" if zh else "All valid inputs", base, None))
    headers = ["输入", "计价单位", "价格 (USD)"] if zh else ["Input", "Price unit", "Price (USD)"]
    lines = ["| " + " | ".join(headers) + " |", "| --- | --- | --- |"]
    for selection, rates, value in rows:
        amounts = set(rates.values())
        if len(amounts) != 1:
            raise ValueError("Different Task tier prices require an explicit customer price presentation")
        label = labels[unit]
        if scale and value in scale["values"]:
            label = (f"每 {scale['unit_size']} 个请求单位" if zh else f"Per {scale['unit_size']} requested units")
        lines.append("| " + " | ".join([text(selection), label, usd(amounts.pop())]) + " |")
    lines.append("")
    if price_by and not price_by.get("unknown_uses_default_tiers", False):
        lines.append("仅表内参数值有价格；未列出的值不会回退到基础价格。" if zh else
                     "Only the listed values are priced; other values do not fall back to the catalog base price.")
    if kind == "per_unit":
        units = p.get("units")
        if not isinstance(units, dict):
            raise ValueError("Missing Task unit accounting")
        estimate = field(detail, units.get("estimate_input"))
        size = integer(units.get("unit_size"), positive=True)
        maximum = integer(units.get("maximum_units"), positive=True)
        settlement = units.get("settlement")
        if settlement != {"delivered_item": "delivered_units", "requested_unit": "requested_units"}[unit]:
            raise ValueError("Task price unit and settlement disagree")
        if zh:
            lines.append(f"执行时按 `ceil({text(estimate)} / {size})` 个单位预扣，最多 {maximum} 个单位。")
            lines.append("按实际交付数量结算，上限为预扣数量；未使用的预扣金额释放。" if settlement == "delivered_units" else
                         "成功请求按请求单位数量结算，不按实际交付条数结算。")
        else:
            lines.append(f"Execution reserves for `ceil({text(estimate)} / {size})` units, up to {maximum} units.")
            lines.append("Settlement uses delivered units, capped at reserved units; unused reservation is released." if settlement == "delivered_units" else
                         "A successful request settles the requested units, rather than the number of delivered items.")
    if scale:
        quantity = text(field(detail, scale["input"]))
        rounding = usd(scale["round_up_micros_usd"])
        values = ", ".join(text(value) for value in scale["values"])
        if zh:
            lines.append(f"对于 {values}：请求价格 = `ceil({quantity} / {scale['unit_size']}) × 所选单价`，总额向上取整到 USD {rounding} 的倍数；请求数量上限 {scale['max_quantity']}。成功返回较少结果仍按请求数量计价。")
        else:
            lines.append(f"For {values}: request price = `ceil({quantity} / {scale['unit_size']}) × selected unit price`, rounded up once to a multiple of USD {rounding}; maximum requested quantity {scale['max_quantity']}. A successful partial result still charges the requested size.")
    lines.append("成功交付才收费；正常查空不收费。" if zh else "Successful delivery is charged; a normal empty result is not charged.")
    policy = p.get("plan_policy")
    if not isinstance(policy, dict):
        raise ValueError("Missing Task plan policy")
    if p["apply_plan_multiplier"]:
        for name in ("team", "builder", "payg"):
            ppm = integer(policy.get(name + "_ppm"), positive=True)
            if ppm != 1_000_000:
                raise ValueError("Non-unit Task plan multiplier requires an explicit customer price presentation")
    return "\n".join(lines) + "\n"
