#!/usr/bin/env python3
"""Generate SimilarWeb's human-readable pricing surfaces from OpenAPI metadata.

`x-aisa-pricing` is the only source of monetary facts. This script renders the
English and Chinese pricing guides plus the pricing disclosure shown on each
SimilarWeb endpoint page. Run with ``--write`` when the metadata changes and
``--check`` in CI to prevent a hand-edited guide or endpoint description from
drifting from the machine-readable contract.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "openapi" / "similarweb.json"
GUIDE_PATH = ROOT / "guides" / "pricing" / "similarweb.mdx"
ZH_GUIDE_PATH = ROOT / "zh" / "guides" / "pricing" / "similarweb.mdx"
API_REFERENCE_DIR = ROOT / "api-reference" / "similarweb"

EXPECTED_OPERATION_IDS = frozenset(
    {
        "get_similarweb_traffic_engagement",
        "get_similarweb_ranking",
        "get_similarweb_ppc_spend",
        "get_similarweb_top_sites_ranking",
        "get_similarweb_marketing_channel_sources_legacy",
        "get_similarweb_referrals",
        "get_similarweb_ad_networks",
        "get_similarweb_similar_sites",
        "get_similarweb_demographics",
        "get_similarweb_deduplicated_audience",
        "get_similarweb_audience_interest",
        "get_similarweb_audience_overlap",
        "get_similarweb_technologies",
        "get_similarweb_popular_pages",
        "get_similarweb_subdomains",
        "get_similarweb_keyword_competitors",
        "get_similarweb_keywords",
        "get_similarweb_serp_players_timeseries",
        "get_similarweb_serp_players_aggregated",
        "get_similarweb_landing_pages",
        "get_similarweb_website_traffic_snapshot",
        "get_similarweb_website_traffic_trend",
        "get_similarweb_website_top_geographies",
    }
)

DISCLOSURE_START = "<!-- AISA-GENERATED-SIMILARWEB-PRICING:START -->"
DISCLOSURE_END = "<!-- AISA-GENERATED-SIMILARWEB-PRICING:END -->"
DISCLOSURE_PATTERN = re.compile(
    rf"\n*{re.escape(DISCLOSURE_START)}.*?{re.escape(DISCLOSURE_END)}\n*",
    re.DOTALL,
)
OPENAPI_REFERENCE_PATTERN = re.compile(
    r'^openapi:\s+"openapi/similarweb\.json (?P<method>[A-Z]+) (?P<path>[^"]+)"$',
    re.MULTILINE,
)
HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})
SETTLEMENT_RESPONSE_HEADERS: dict[str, dict[str, Any]] = {
    "X-AISA-Estimated-Credits": {
        "description": "Pre-authorization credit estimate for this accepted request. It is an estimate, not a quote or authorization to make a request.",
        "schema": {"type": "number", "format": "float"},
    },
    "X-AISA-Accounted-Credits": {
        "description": "Credits settled for the completed response. Present only when the gateway records settled usage.",
        "schema": {"type": "number", "format": "float"},
    },
    "X-AISA-Price-USD": {
        "description": "USD amount settled for the completed response. Present only when the gateway records settled usage.",
        "schema": {"type": "number", "format": "float"},
    },
}
CREDIT_EXAMPLE_RE = re.compile(r"(?P<credits>\d+(?:\.\d+)?) credits? \(\$(?P<usd>\d+(?:\.\d+)?)\)")


@dataclass(frozen=True)
class Operation:
    """A SimilarWeb operation together with its #92 pricing contract."""

    path: str
    method: str
    operation_id: str
    endpoint_slug: str
    summary: str
    pricing: dict[str, Any]
    parameter_names: frozenset[str]

    @property
    def anchor(self) -> str:
        endpoint = self.path.rsplit("/", 1)[-1]
        return endpoint if self.method == "get" else f"{self.method}-{endpoint}"

    @property
    def endpoint_url(self) -> str:
        return f"/api-reference/similarweb/{self.endpoint_slug}"


def fail(message: str) -> None:
    raise ValueError(f"SimilarWeb pricing generation failed: {message}")


def load_source() -> dict[str, Any]:
    with SOURCE_PATH.open(encoding="utf-8") as stream:
        source = json.load(stream)
    if not isinstance(source, dict):
        fail("openapi/similarweb.json is not an object")
    return source


def validate_pricing(path: str, pricing: Any) -> dict[str, Any]:
    if not isinstance(pricing, dict):
        fail(f"{path} has no x-aisa-pricing object")

    required = {
        "model",
        "currency",
        "credit_price_usd",
        "credit_formula",
        "credit_rate",
        "cost_drivers",
        "cost_tier",
        "example",
    }
    missing = sorted(required - pricing.keys())
    if missing:
        fail(f"{path} is missing pricing keys: {', '.join(missing)}")
    if pricing["model"] != "per_credit":
        fail(f"{path} has unsupported pricing model {pricing['model']!r}")
    if pricing["currency"] != "USD":
        fail(f"{path} must use USD")
    if not isinstance(pricing["credit_price_usd"], (int, float)) or pricing["credit_price_usd"] <= 0:
        fail(f"{path} must have a positive credit_price_usd")
    for field in ("credit_formula", "credit_rate", "cost_tier", "example"):
        if not isinstance(pricing[field], str) or not pricing[field].strip():
            fail(f"{path} has an empty {field}")
    if not isinstance(pricing["cost_drivers"], list) or not pricing["cost_drivers"]:
        fail(f"{path} needs at least one cost driver")
    for driver in pricing["cost_drivers"]:
        if not isinstance(driver, dict):
            fail(f"{path} has a non-object cost driver")
        for field in ("param", "effect"):
            if not isinstance(driver.get(field), str) or not driver[field].strip():
                fail(f"{path} has an invalid cost driver {field}")
    examples = list(CREDIT_EXAMPLE_RE.finditer(pricing["example"]))
    if not examples:
        fail(f"{path} example has no parseable credits-to-USD amount")
    credit_price = Decimal(str(pricing["credit_price_usd"]))
    for match in examples:
        try:
            credits = Decimal(match.group("credits"))
            documented_usd = Decimal(match.group("usd"))
        except InvalidOperation as error:
            raise AssertionError("credit example regex must only capture decimals") from error
        expected_usd = credits * credit_price
        if documented_usd != expected_usd:
            fail(
                f"{path} example has ${documented_usd} for {credits} credits; "
                f"expected ${expected_usd} at ${credit_price} per credit"
            )
    return pricing


def api_reference_pages() -> dict[tuple[str, str], str]:
    pages: dict[tuple[str, str], str] = {}
    for page in API_REFERENCE_DIR.glob("*.mdx"):
        match = OPENAPI_REFERENCE_PATTERN.search(page.read_text(encoding="utf-8"))
        if not match:
            continue
        path = match.group("path")
        method = match.group("method").lower()
        key = (path, method)
        if key in pages:
            fail(f"duplicate endpoint page for {method.upper()} {path}")
        pages[key] = page.stem
    return pages


def collect_operations(source: dict[str, Any]) -> list[Operation]:
    paths = source.get("paths")
    if not isinstance(paths, dict):
        fail("source OpenAPI has no paths object")

    reference_pages = api_reference_pages()
    operations: list[Operation] = []
    seen_ids: set[str] = set()
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method not in HTTP_METHODS:
                continue
            if not isinstance(operation, dict):
                fail(f"{method.upper()} {path} is not an operation object")
            if "x-aisa-pricing" not in operation:
                fail(f"{method.upper()} {path} has no x-aisa-pricing object")

            operation_id = operation.get("operationId")
            summary = operation.get("summary")
            description = operation.get("description")
            if not isinstance(operation_id, str) or not operation_id:
                fail(f"{method.upper()} {path} has no operationId")
            if not isinstance(summary, str) or not summary:
                fail(f"{method.upper()} {path} has no summary")
            if not isinstance(description, str) or not description:
                fail(f"{method.upper()} {path} has no description")
            if operation_id in seen_ids:
                fail(f"duplicate operationId {operation_id}")
            seen_ids.add(operation_id)
            endpoint_slug = reference_pages.get((path, method))
            if not endpoint_slug:
                fail(f"{method.upper()} {path} has no API reference page")

            parameters = operation.get("parameters", [])
            if not isinstance(parameters, list):
                fail(f"{method.upper()} {path} has invalid parameters")
            parameter_names = frozenset(
                parameter["name"]
                for parameter in parameters
                if isinstance(parameter, dict) and isinstance(parameter.get("name"), str)
            )
            operations.append(
                Operation(
                    path=path,
                    method=method,
                    operation_id=operation_id,
                    endpoint_slug=endpoint_slug,
                    summary=summary,
                    pricing=validate_pricing(f"{method.upper()} {path}", operation["x-aisa-pricing"]),
                    parameter_names=parameter_names,
                )
            )

    found_ids = {operation.operation_id for operation in operations}
    missing = sorted(EXPECTED_OPERATION_IDS - found_ids)
    unexpected = sorted(found_ids - EXPECTED_OPERATION_IDS)
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing operation IDs: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected operation IDs: {', '.join(unexpected)}")
        fail("; ".join(details))
    if len(operations) != len(EXPECTED_OPERATION_IDS):
        fail(f"expected exactly {len(EXPECTED_OPERATION_IDS)} pricing operations, found {len(operations)}")
    return operations


def category(operation: Operation) -> str:
    driver_names = {driver["param"] for driver in operation.pricing["cost_drivers"]}
    if driver_names == {"(none)"}:
        return "fixed"
    if "limit" in driver_names:
        return "rows"
    return "dimensions"


def price(value: float | int) -> str:
    return f"${value:.2f}"


def drivers_en(operation: Operation) -> str:
    return "; ".join(
        f"`{driver['param']}`: {driver['effect']}"
        for driver in operation.pricing["cost_drivers"]
    )


def effect_zh(effect: str) -> str:
    exact = {
        "number of metrics requested": "请求的指标数量",
        "number of months in the date window": "日期范围内的月份数",
        "flat per-request credit charge": "每次请求固定 credit 费用",
    }
    if effect in exact:
        return exact[effect]
    row_match = re.fullmatch(
        r"charge scales with rows returned at (.+) credit/row; at most (\d+) rows are billed",
        effect,
    )
    if row_match:
        return f"按返回行数以 {row_match.group(1)} credit/行累积计费，最多计 {row_match.group(2)} 行"
    fail(f"cannot localize an unknown cost-driver effect: {effect!r}")


def drivers_zh(operation: Operation) -> str:
    return "；".join(
        f"`{driver['param']}`：{effect_zh(driver['effect'])}"
        for driver in operation.pricing["cost_drivers"]
    )


def driver_is_controllable(operation: Operation, driver_name: str) -> bool:
    if driver_name == "periods":
        return {"start_date", "end_date"}.issubset(operation.parameter_names)
    return driver_name in operation.parameter_names


def controllable_drivers(operation: Operation) -> list[str]:
    return [
        driver["param"]
        for driver in operation.pricing["cost_drivers"]
        if driver["param"] != "(none)" and driver_is_controllable(operation, driver["param"])
    ]


def provider_controlled_drivers(operation: Operation) -> list[str]:
    return [
        driver["param"]
        for driver in operation.pricing["cost_drivers"]
        if driver["param"] != "(none)" and not driver_is_controllable(operation, driver["param"])
    ]


def display_example_en(operation: Operation) -> tuple[str, str]:
    raw_example = operation.pricing["example"]
    uncontrolled = provider_controlled_drivers(operation)
    if category(operation) == "rows" and uncontrolled:
        exposure, _, _ = raw_example.partition("; limit=")
        return (
            "Published maximum-exposure example",
            f"`{exposure}`. The source's `limit=...` text is a metering illustration only; "
            "this endpoint does not accept `limit`.",
        )
    if category(operation) == "dimensions" and uncontrolled:
        names = ", ".join(f"`{name}`" for name in uncontrolled)
        return (
            "Provider-controlled lower-bound example",
            f"`{raw_example.rstrip('.')}`. {names} are provider-controlled for this endpoint, not caller-selectable request parameters.",
        )
    return "Current schedule example", f"`{raw_example}`"


def display_example_zh(operation: Operation) -> tuple[str, str]:
    raw_example = operation.pricing["example"]
    uncontrolled = provider_controlled_drivers(operation)
    if category(operation) == "rows" and uncontrolled:
        exposure, _, _ = raw_example.partition("; limit=")
        return (
            "公开最大成本暴露示例",
            f"`{exposure}`。源数据中的 `limit=...` 仅用于说明计量，不是该端点接受的 `limit` 参数。",
        )
    if category(operation) == "dimensions" and uncontrolled:
        names = "、".join(f"`{name}`" for name in uncontrolled)
        return (
            "Provider 控制的最低示例",
            f"`{raw_example.rstrip('.')}`。对于该端点，{names} 由 provider 控制，不能由调用方作为请求参数选择。",
        )
    return "当前公开示例", f"`{raw_example}`"


def control_en(operation: Operation) -> str:
    operation_category = category(operation)
    if operation_category == "fixed":
        return "The published credit charge is fixed for this request type."
    if operation_category == "rows":
        if "limit" in operation.parameter_names:
            return "Use the smallest meaningful `limit`; returned rows drive the credit cost."
        return (
            "This row-priced operation has no documented `limit` parameter and does not accept `limit`. Do not promise that a caller can reduce "
            "its cost with `limit`; use the documented example and cap as the exposure of one accepted request."
        )
    controllable = controllable_drivers(operation)
    uncontrolled = provider_controlled_drivers(operation)
    if not controllable:
        names = ", ".join(f"`{name}`" for name in uncontrolled)
        return (
            f"The formula includes provider-controlled dimensions ({names}) that are not accepted request parameters. "
            "The documentation does not publish an upper bound, so the example is a lower bound, not an approval cap. "
            "Do not execute this operation under the approval-first contract until a documented maximum is available."
        )
    control_names = ", ".join(
        "the `start_date`/`end_date` range" if name == "periods" else f"`{name}`"
        for name in controllable
    )
    result = f"Cost varies with {control_names}; set the smallest required scope and obtain a budget decision before execution."
    if uncontrolled:
        names = ", ".join(f"`{name}`" for name in uncontrolled)
        result += f" {names} remain provider-controlled."
    return result


def control_zh(operation: Operation) -> str:
    operation_category = category(operation)
    if operation_category == "fixed":
        return "该类请求的公开 credit 费用是固定的。"
    if operation_category == "rows":
        if "limit" in operation.parameter_names:
            return "返回行数决定 credit 费用；请使用足以回答问题的最小 `limit`。"
        return (
            "该端点按返回行数计费，但没有已记录的 `limit` 参数。不要承诺调用方可通过 `limit` 降低费用；"
            "应把公开示例和上限视为一次被接受请求的成本暴露。"
        )
    controllable = controllable_drivers(operation)
    uncontrolled = provider_controlled_drivers(operation)
    if not controllable:
        names = "、".join(f"`{name}`" for name in uncontrolled)
        return (
            f"公式包含由 provider 控制且不能作为请求参数传入的维度（{names}）。"
            "文档没有公开上限，因此示例只是最低值，不能作为批准上限。"
            "在有已记录的最大上限前，不得按先批准后执行合同调用该端点。"
        )
    control_names = "、".join(
        "`start_date`/`end_date` 日期范围" if name == "periods" else f"`{name}`"
        for name in controllable
    )
    result = f"费用会随 {control_names} 变化；执行前请缩小到必要范围并取得预算确认。"
    if uncontrolled:
        names = "、".join(f"`{name}`" for name in uncontrolled)
        result += f" {names} 仍由 provider 控制。"
    return result


def mode_en(operation: Operation) -> str:
    return {
        "fixed": "fixed per request",
        "rows": "returned-row credit pricing",
        "dimensions": "request-dimension credit pricing",
    }[category(operation)]


def mode_zh(operation: Operation) -> str:
    return {
        "fixed": "固定每请求 credit 计费",
        "rows": "按返回行数 credit 计费",
        "dimensions": "按请求维度 credit 计费",
    }[category(operation)]


def generated_disclosure(operation: Operation) -> str:
    pricing = operation.pricing
    example_label, example = display_example_en(operation)
    return "\n".join(
        (
            DISCLOSURE_START,
            "**Pricing (generated from `x-aisa-pricing`):** "
            f"`{pricing['credit_rate']}` at `{price(pricing['credit_price_usd'])}` per credit. "
            f"Formula: `{pricing['credit_formula']}`. Cost drivers: {drivers_en(operation)}. "
            f"{example_label}: {example}",
            "",
            f"**IMPORTANT:** {control_en(operation)} "
            f"Read [SimilarWeb Pricing & Cost Control](/guides/pricing/similarweb#{operation.anchor}) "
            "before a paid request.",
            DISCLOSURE_END,
        )
    )


def strip_generated_disclosure(description: str) -> str:
    matches = list(DISCLOSURE_PATTERN.finditer(description))
    if len(matches) > 1:
        fail("an operation description contains multiple generated pricing disclosures")
    return DISCLOSURE_PATTERN.sub("", description).rstrip()


def render_source(source: dict[str, Any], operations: list[Operation]) -> str:
    rendered = copy.deepcopy(source)
    for operation in operations:
        target = rendered["paths"][operation.path][operation.method]
        base_description = strip_generated_disclosure(target["description"])
        target["description"] = f"{base_description}\n\n{generated_disclosure(operation)}\n"
        responses = target.get("responses")
        if not isinstance(responses, dict) or not isinstance(responses.get("200"), dict):
            fail(f"{operation.method.upper()} {operation.path} has no 200 response for settlement headers")
        responses["200"]["headers"] = copy.deepcopy(SETTLEMENT_RESPONSE_HEADERS)

    source_metadata = {
        (operation.path, operation.method): operation.pricing for operation in collect_operations(source)
    }
    rendered_metadata = {
        (operation.path, operation.method): rendered["paths"][operation.path][operation.method]["x-aisa-pricing"]
        for operation in operations
    }
    if rendered_metadata != source_metadata:
        fail("generation attempted to change x-aisa-pricing metadata")
    return json.dumps(rendered, indent=2, ensure_ascii=False) + "\n"


def operation_section_en(operation: Operation) -> str:
    pricing = operation.pricing
    example_label, example = display_example_en(operation)
    return "\n".join(
        (
            f'<span id="{operation.anchor}"></span>',
            f"### [{operation.summary}]({operation.endpoint_url})",
            "",
            f"- **Pricing mode:** {mode_en(operation)}.",
            f"- **Credit rate:** `{pricing['credit_rate']}` at `{price(pricing['credit_price_usd'])}` per credit.",
            f"- **Formula:** `{pricing['credit_formula']}`.",
            f"- **Cost drivers:** {drivers_en(operation)}.",
            f"- **{example_label}:** {example}",
            f"- **Control:** {control_en(operation)}",
            "",
        )
    )


def operation_section_zh(operation: Operation) -> str:
    pricing = operation.pricing
    example_label, example = display_example_zh(operation)
    return "\n".join(
        (
            f'<span id="{operation.anchor}"></span>',
            f"### [{operation.summary}]({operation.endpoint_url})",
            "",
            f"- **计费方式：** {mode_zh(operation)}。",
            f"- **Credit 费率：** `{pricing['credit_rate']}`，每 credit `{price(pricing['credit_price_usd'])}`。",
            f"- **公式：** `{pricing['credit_formula']}`。",
            f"- **费用驱动因素：** {drivers_zh(operation)}。",
            f"- **{example_label}：** {example}",
            f"- **控制方式：** {control_zh(operation)}",
            "",
        )
    )


def render_guide_en(operations: list[Operation]) -> str:
    groups = (
        ("dimensions", "Request-dimension pricing"),
        ("rows", "Returned-row pricing"),
        ("fixed", "Fixed per-request pricing"),
    )
    parts = [
        "---",
        "title: SimilarWeb Pricing & Cost Control",
        "excerpt: >-",
        "  Machine-derived SimilarWeb credit formulas, examples, and cost controls",
        "  for people and agents before a paid request.",
        "---",
        "",
        "SimilarWeb is a paid data API with credit-based pricing. Its catalog display value is not always a fixed, request-specific quote.",
        "",
        "<Warning>",
        "  **IMPORTANT — approval-first:** A SimilarWeb data endpoint is not price discovery. Before any data request, use the matching `x-aisa-pricing` disclosure to state the exact scope, formula, and documented maximum exposure; then obtain explicit user approval for that scope and cap. Never send an unapproved probe, test, or \"just check\" request. Docs, `/v1/models`, and MCP discovery are allowed discovery surfaces.",
        "</Warning>",
        "",
        "This page is generated from each endpoint's `x-aisa-pricing` object in the [machine-readable OpenAPI](https://aisa.one/openapi.yaml). It intentionally does not maintain a second hand-authored rate schedule.",
        "",
        "## How settlement works",
        "",
        "SimilarWeb uses a two-phase credit model: the gateway can report a pre-authorization estimate in `X-AISA-Estimated-Credits`, then reports settled usage in `X-AISA-Accounted-Credits` and `X-AISA-Price-USD`. The provider-level API contract says that only successful, non-empty responses are billed. These formulas and examples describe the published schedule; they are not a server-authoritative quote endpoint.",
        "",
        "Do not treat a catalog `pricing.normal` value of `0` as a free SimilarWeb request.",
        "",
    ]
    for group, heading in groups:
        members = [operation for operation in operations if category(operation) == group]
        if not members:
            continue
        parts.extend((f"## {heading}", ""))
        for operation in members:
            parts.append(operation_section_en(operation).rstrip())
            parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def render_guide_zh(operations: list[Operation]) -> str:
    groups = (
        ("dimensions", "按请求维度计费"),
        ("rows", "按返回行数计费"),
        ("fixed", "固定每请求计费"),
    )
    parts = [
        "---",
        "title: SimilarWeb 价格与成本控制",
        "excerpt: >-",
        "  从机器可读合同自动生成的 SimilarWeb credit 公式、示例与成本控制说明，",
        "  供人和 Agent 在付费请求前使用。",
        "---",
        "",
        "SimilarWeb 是付费数据 API，采用 credit 计费。目录展示值并不总是某次请求的固定、精确报价。",
        "",
        "<Warning>",
        "  **重要（IMPORTANT，先批准后执行）：** SimilarWeb 数据 endpoint 不是价格发现入口。发起任何数据请求前，请使用匹配的 `x-aisa-pricing` 说明明确 scope、公式和已记录的最大成本暴露，再取得用户对该 scope 与上限的明确批准。绝不能发送未经批准的 probe、test 或“先探一下”请求；docs、`/v1/models` 和 MCP discovery 可以作为发现入口。",
        "</Warning>",
        "",
        "本页从 [机器可读 OpenAPI](https://aisa.one/openapi.yaml) 中每个端点的 `x-aisa-pricing` 对象自动生成，故意不维护第二份手写费率表。",
        "",
        "## 如何结算",
        "",
        "SimilarWeb 使用两阶段 credit 模型：网关可以在 `X-AISA-Estimated-Credits` 中返回预授权估算，然后在 `X-AISA-Accounted-Credits` 和 `X-AISA-Price-USD` 中报告最终结算用量。provider 级 API 合同说明只有成功且非空的响应会计费。这里的公式和示例描述公开计价表，并不是服务端权威的报价接口。",
        "",
        "不要把目录中的 `pricing.normal = 0` 当成 SimilarWeb 免费调用。",
        "",
    ]
    for group, heading in groups:
        members = [operation for operation in operations if category(operation) == group]
        if not members:
            continue
        parts.extend((f"## {heading}", ""))
        for operation in members:
            parts.append(operation_section_zh(operation).rstrip())
            parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def expected_outputs(source: dict[str, Any]) -> dict[Path, str]:
    operations = collect_operations(source)
    return {
        SOURCE_PATH: render_source(source, operations),
        GUIDE_PATH: render_guide_en(operations),
        ZH_GUIDE_PATH: render_guide_zh(operations),
    }


def check_outputs(outputs: dict[Path, str]) -> list[Path]:
    return [path for path, expected in outputs.items() if not path.exists() or path.read_text(encoding="utf-8") != expected]


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write generated pricing surfaces")
    mode.add_argument("--check", action="store_true", help="fail if generated pricing surfaces are stale")
    args = parser.parse_args()

    outputs = expected_outputs(load_source())
    stale = check_outputs(outputs)
    if args.check:
        if stale:
            rendered_paths = ", ".join(str(path.relative_to(ROOT)) for path in stale)
            raise SystemExit(f"SimilarWeb pricing surfaces are stale: {rendered_paths}. Run --write.")
        print(f"SimilarWeb pricing surfaces are current: {len(EXPECTED_OPERATION_IDS)} operations")
        return

    for path in stale:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(outputs[path], encoding="utf-8")
        print(f"updated {path.relative_to(ROOT)}")
    if not stale:
        print(f"SimilarWeb pricing surfaces already current: {len(EXPECTED_OPERATION_IDS)} operations")


if __name__ == "__main__":
    main()
