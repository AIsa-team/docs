#!/usr/bin/env python3
"""Validate that SimilarWeb's human and machine pricing surfaces stay aligned."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

from generate_similarweb_pricing_docs import (
    EXPECTED_OPERATION_IDS,
    ROOT,
    SETTLEMENT_RESPONSE_HEADERS,
    SOURCE_PATH,
    check_outputs,
    category,
    collect_operations,
    expected_outputs,
    load_source,
    provider_controlled_drivers,
)


LLMS_PATH = ROOT / "llms.txt"
AGENT_QUICKSTART_PATH = ROOT / "agent-quickstart.mdx"
ZH_AGENT_QUICKSTART_PATH = ROOT / "zh" / "agent-quickstart.mdx"
PRICING_OVERVIEW_PATH = ROOT / "guides" / "pricing.mdx"
PER_CALL_PATH = ROOT / "guides" / "pricing" / "per-call-api-pricing.mdx"
ZH_PRICING_OVERVIEW_PATH = ROOT / "zh" / "guides" / "pricing.mdx"
ZH_PER_CALL_PATH = ROOT / "zh" / "guides" / "pricing" / "per-call-api-pricing.mdx"
EVALUATE_PRICING_PATH = ROOT / "evaluate" / "pricing.mdx"
ZH_EVALUATE_PRICING_PATH = ROOT / "zh" / "evaluate" / "pricing.mdx"


def fail(message: str) -> None:
    raise SystemExit(f"pricing contract check failed: {message}")


def check_checked_in_surfaces(source: dict[str, Any]) -> None:
    stale = check_outputs(expected_outputs(source))
    if stale:
        paths = ", ".join(str(path.relative_to(ROOT)) for path in stale)
        fail(f"generated surfaces are stale: {paths}; run generate_similarweb_pricing_docs.py --write")

    operations = collect_operations(source)
    for operation in operations:
        endpoint = ROOT / "api-reference" / "similarweb" / f"{operation.endpoint_slug}.mdx"
        if not endpoint.exists():
            fail(f"{operation.operation_id} has no endpoint documentation page")
        source_operation = source["paths"][operation.path][operation.method]
        description = source_operation["description"]
        response = source_operation.get("responses", {}).get("200")
        if not isinstance(response, dict) or response.get("headers") != SETTLEMENT_RESPONSE_HEADERS:
            fail(f"{operation.operation_id} lacks the generated settlement response headers")
        if "/agent-quickstart#paid-api-approval-first" not in description:
            fail(f"{operation.operation_id} does not route agents to the paid-API approval-first contract")
        uncontrolled = provider_controlled_drivers(operation)
        if category(operation) == "rows" and uncontrolled:
            if "does not accept `limit`" not in description:
                fail(f"{operation.operation_id} does not disclose that limit is unavailable")
            if "; limit=" in description:
                fail(f"{operation.operation_id} renders a non-callable limit example as request syntax")
        if category(operation) == "dimensions" and uncontrolled and not operation.parameter_names.intersection({"metrics", "start_date", "end_date"}):
            if "provider-controlled dimensions" not in description:
                fail(f"{operation.operation_id} does not disclose provider-controlled pricing dimensions")
            if "documentation does not publish an upper bound" not in description or "not an approval cap" not in description:
                fail(f"{operation.operation_id} presents a provider-controlled lower bound as an approval cap")

    llms = LLMS_PATH.read_text(encoding="utf-8")
    for marker in ("<IMPORTANT id=\"paid-api-approval-first\">", "explicit approval", "price discovery", "x-aisa-pricing", "/v1/models", "MCP discovery", "SimilarWeb is a classic"):
        if marker not in llms:
            fail(f"llms.txt lacks paid-API approval-first marker: {marker}")
    for path, markers in (
        (AGENT_QUICKSTART_PATH, ("<IMPORTANT id=\"paid-api-approval-first\">", "explicit approval", "price discovery", "published pricing source", "/v1/models", "MCP discovery", "Classic example — SimilarWeb")),
        (ZH_AGENT_QUICKSTART_PATH, ("<IMPORTANT id=\"paid-api-approval-first\">", "明确批准", "价格发现", "公开计价来源", "/v1/models", "MCP discovery", "典型场景 — SimilarWeb")),
    ):
        content = path.read_text(encoding="utf-8")
        for marker in markers:
            if marker not in content:
                fail(f"{path.relative_to(ROOT)} lacks SimilarWeb approval-first marker: {marker}")
    similar_sites = next(operation for operation in operations if operation.operation_id == "get_similarweb_similar_sites")
    endpoint_url = f"https://aisa.one/docs/api-reference/similarweb/{similar_sites.endpoint_slug}"
    if endpoint_url not in llms:
        fail("llms.txt SimilarWeb API family link does not resolve to the SimilarSites endpoint page")

    english_overview = PRICING_OVERVIEW_PATH.read_text(encoding="utf-8")
    chinese_overview = ZH_PRICING_OVERVIEW_PATH.read_text(encoding="utf-8")
    if "All non-LLM APIs use a fixed per-request billing model." in english_overview:
        fail("English pricing overview still classifies every non-LLM API as fixed-price")
    if "所有非 LLM API 使用固定的按请求计费模型。" in chinese_overview:
        fail("Chinese pricing overview still classifies every non-LLM API as fixed-price")

    for path in (PRICING_OVERVIEW_PATH, PER_CALL_PATH, ZH_PRICING_OVERVIEW_PATH, ZH_PER_CALL_PATH):
        content = path.read_text(encoding="utf-8").lower()
        if "similarweb" not in content or "endpoint" not in content:
            fail(f"{path.relative_to(ROOT)} does not route formula-priced APIs to endpoint documentation")

    for path, markers in (
        (EVALUATE_PRICING_PATH, ("any paid or potentially high-cost API", "explicit approval", "SimilarWeb is a classic")),
        (ZH_EVALUATE_PRICING_PATH, ("任何付费或可能高成本的 API", "明确批准", "SimilarWeb 是动态成本的典型场景")),
    ):
        content = path.read_text(encoding="utf-8")
        for marker in markers:
            if marker not in content:
                fail(f"{path.relative_to(ROOT)} lacks the SimilarWeb no-probe exception: {marker}")


def check_consolidated_openapi(source: dict[str, Any], generated_path: Path) -> None:
    with generated_path.open(encoding="utf-8") as stream:
        generated = yaml.safe_load(stream)
    if not isinstance(generated, dict) or not isinstance(generated.get("paths"), dict):
        fail("generated OpenAPI has no paths object")

    for operation in collect_operations(source):
        expected = operation.pricing
        generated_operation = generated["paths"].get(operation.path, {}).get(operation.method, {})
        actual = generated_operation.get("x-aisa-pricing")
        if actual != expected:
            fail(f"generated OpenAPI did not preserve x-aisa-pricing for {operation.path}")
        response = generated_operation.get("responses", {}).get("200")
        if not isinstance(response, dict) or response.get("headers") != SETTLEMENT_RESPONSE_HEADERS:
            fail(f"generated OpenAPI did not preserve settlement headers for {operation.path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--generated",
        type=Path,
        help="optional consolidated OpenAPI YAML to compare with the source",
    )
    args = parser.parse_args()

    source = load_source()
    operations = collect_operations(source)
    if len(operations) != len(EXPECTED_OPERATION_IDS):
        fail("unexpected SimilarWeb operation inventory")
    check_checked_in_surfaces(source)
    if args.generated:
        check_consolidated_openapi(source, args.generated)
    print(f"pricing contract check passed: {len(operations)} SimilarWeb operations")


if __name__ == "__main__":
    main()
