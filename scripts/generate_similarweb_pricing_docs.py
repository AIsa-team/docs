#!/usr/bin/env python3
"""Derive concise SimilarWeb endpoint price notices from x-aisa-pricing."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
SOURCE_PATH = ROOT / "openapi" / "similarweb.json"
HTTP_METHODS = {"delete", "get", "head", "options", "patch", "post", "put", "trace"}
LEGACY_DISCLOSURE = re.compile(
    r"\n*<!-- AISA-GENERATED-SIMILARWEB-PRICING:START -->.*?"
    r"<!-- AISA-GENERATED-SIMILARWEB-PRICING:END -->\s*",
    re.DOTALL,
)
NOTICE = re.compile(
    r"\n{2}\*\*Pricing \(from `x-aisa-pricing`\):\*\*.*?(?=\n{2}|\Z)",
    re.DOTALL,
)


def fail(message: str) -> None:
    raise SystemExit(f"SimilarWeb pricing disclosure: {message}")


def price_usd(value: Any, location: str) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        fail(f"{location} has an invalid credit_price_usd")
    return f"${value:.2f}"


def required_text(pricing: dict[str, Any], field: str, location: str) -> str:
    value = pricing.get(field)
    if not isinstance(value, str) or not value.strip():
        fail(f"{location} has no {field}")
    return value.strip()


def notice(pricing: dict[str, Any], location: str) -> str:
    return (
        "**Pricing (from `x-aisa-pricing`):** "
        f"`{required_text(pricing, 'credit_rate', location)}` at "
        f"`{price_usd(pricing.get('credit_price_usd'), location)}` per credit. "
        f"Formula: `{required_text(pricing, 'credit_formula', location)}`. "
        "Before a paid data call, follow "
        "[Agent Quickstart](/agent-quickstart#paid-api-approval-first) and obtain explicit approval."
    )


def without_prior_notice(description: str) -> str:
    return NOTICE.sub("", LEGACY_DISCLOSURE.sub("", description)).rstrip()


def render(source: dict[str, Any]) -> str:
    paths = source.get("paths")
    if not isinstance(paths, dict):
        fail("OpenAPI source has no paths object")

    operation_count = 0
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            if not isinstance(operation, dict):
                fail(f"{method.upper()} {path} is not an operation object")
            pricing = operation.get("x-aisa-pricing")
            description = operation.get("description")
            location = f"{method.upper()} {path}"
            if not isinstance(pricing, dict):
                fail(f"{location} has no x-aisa-pricing object")
            if not isinstance(description, str) or not description.strip():
                fail(f"{location} has no description")
            operation["description"] = f"{without_prior_notice(description)}\n\n{notice(pricing, location)}\n"
            operation_count += 1

    if operation_count == 0:
        fail("OpenAPI source has no HTTP operations")
    return json.dumps(source, indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="refresh endpoint disclosures")
    mode.add_argument("--check", action="store_true", help="fail when disclosures are stale")
    args = parser.parse_args()

    expected = render(json.loads(SOURCE_PATH.read_text(encoding="utf-8")))
    current = SOURCE_PATH.read_text(encoding="utf-8")
    if args.check:
        if current != expected:
            fail("endpoint disclosures are stale; run scripts/generate_similarweb_pricing_docs.py --write")
        print("SimilarWeb pricing disclosures are current")
        return

    if current == expected:
        print("SimilarWeb pricing disclosures already current")
        return
    SOURCE_PATH.write_text(expected, encoding="utf-8")
    print(f"updated {SOURCE_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
