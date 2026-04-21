#!/usr/bin/env python3
"""
Consolidate individual AIsa OpenAPI spec files into a single unified openapi.yaml.

Reads all JSON specs from the openapi/ directory, merges paths (with correct
server-path prefixes) and schemas, and outputs a single OpenAPI 3.1 YAML file.

Usage:
    python scripts/consolidate_openapi.py [--output path/to/openapi.yaml]

If --output is omitted, writes to stdout.
"""

import argparse
import json
import os
import sys
from urllib.parse import urlparse

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
OPENAPI_DIR = os.path.join(REPO_ROOT, "openapi")

# The Mintlify placeholder spec — skip it
SKIP_FILES = {"openapi.json"}

# Map each spec file to a category tag
FILE_TAG_MAP = {
    "openai-chat.json": "AI Models",
    "gemini-openapi.json": "AI Models",
    "claude-messages.json": "AI Models",
    "perplexity-openapi.json": "AI Models",
    "openai-images-generations.json": "Image Generation",
    "chat-image-generation.json": "Image Generation",
    "aliyun-video.json": "Video Generation",
    "twitter-user-batch_01.json": "Twitter / X",
    "twitter-user-batch_02.json": "Twitter / X",
    "twitter-tweet-batch_01.json": "Twitter / X",
    "twitter-tweet-batch_02.json": "Twitter / X",
    "twitter-actions.json": "Twitter / X",
    "twitter-communities.json": "Twitter / X",
    "twitter-list.json": "Twitter / X",
    "twitter-trend.json": "Twitter / X",
    "youte-search.json": "YouTube Search",
    "tavily.json": "Web & News Search",
    "platform-txyz-openapi.json": "Scholar Search",
    "openapi-financial.json": "Financial Data",
    "analyst-estimates.json": "Financial Data",
    "macro_snapshot.json": "Financial Data",
    "coingecko.json": "Crypto Data",
    "polymarket-openapi.json": "Prediction Markets",
    "kalshi-openapi.json": "Prediction Markets",
    "matching-markets-openapi.json": "Prediction Markets",
}

TAG_DESCRIPTIONS = {
    "AI Models": "Access 50+ LLMs via OpenAI-compatible, Anthropic, and Google Gemini interfaces",
    "Image Generation": "Generate and edit images using AI models",
    "Video Generation": "Generate videos using AI models (Wan family)",
    "Twitter / X": "Read, search, and interact with Twitter/X — profiles, tweets, communities, trends, and engagement",
    "YouTube Search": "Search YouTube videos",
    "Web & News Search": "Search the web and news via Tavily",
    "Scholar Search": "Search academic papers and research",
    "Financial Data": "Stock prices, financials, analyst estimates, SEC filings, and macro data",
    "Crypto Data": "Cryptocurrency prices, markets, and exchange data via CoinGecko",
    "Prediction Markets": "Query prediction markets — Polymarket, Kalshi, and matching markets",
}


def load_spec(filepath):
    with open(filepath, "r") as f:
        return json.load(f)


def build_unified_spec():
    """Merge all individual specs into one OpenAPI 3.1 document."""
    unified = {
        "openapi": "3.1.0",
        "info": {
            "title": "AIsa API",
            "description": (
                "Capability layer for the agentic economy. "
                "Models, skills, payments, and deployment — everything AI agents "
                "need to reason, act, and transact. "
                "This spec consolidates all AIsa API endpoints into a single reference."
            ),
            "version": "1.0.0",
            "contact": {
                "name": "AIsa",
                "url": "https://aisa.one",
                "email": "developer@aisa.one",
            },
            "license": {"name": "MIT", "url": "https://opensource.org/licenses/MIT"},
            "termsOfService": "https://aisa.one/tos",
        },
        "servers": [
            {"url": "https://api.aisa.one", "description": "AIsa Production API"}
        ],
        "security": [{"BearerAuth": []}],
        "tags": [],
        "paths": {},
        "components": {
            "securitySchemes": {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "AIsa API key. Get yours at https://marketplace.aisa.one",
                }
            },
            "schemas": {},
        },
    }

    tags_seen = set()
    files = sorted(os.listdir(OPENAPI_DIR))

    for filename in files:
        if filename in SKIP_FILES or not filename.endswith(".json"):
            continue

        filepath = os.path.join(OPENAPI_DIR, filename)
        tag = FILE_TAG_MAP.get(filename, "Other")

        try:
            spec = load_spec(filepath)
        except Exception as e:
            print(f"  SKIP {filename}: {e}", file=sys.stderr)
            continue

        # Register tag
        if tag not in tags_seen:
            tags_seen.add(tag)
            unified["tags"].append(
                {"name": tag, "description": TAG_DESCRIPTIONS.get(tag, "")}
            )

        # Determine path prefix from the spec's server URL
        # e.g. https://api.aisa.one/v1 → /v1
        # e.g. https://api.aisa.one/apis/v1 → /apis/v1
        servers = spec.get("servers", [])
        path_prefix = ""
        if servers:
            parsed = urlparse(servers[0].get("url", ""))
            if parsed.path and parsed.path != "/":
                path_prefix = parsed.path.rstrip("/")

        # Merge paths
        for path, methods in spec.get("paths", {}).items():
            full_path = path_prefix + path

            for method, operation in methods.items():
                if isinstance(operation, dict):
                    operation["tags"] = [tag]
                    operation.pop("servers", None)

            if full_path in unified["paths"]:
                for method, operation in methods.items():
                    if method not in unified["paths"][full_path]:
                        unified["paths"][full_path][method] = operation
            else:
                unified["paths"][full_path] = methods

        # Merge component schemas (prefix on collision)
        for schema_name, schema_def in (
            spec.get("components", {}).get("schemas", {}).items()
        ):
            if schema_name in unified["components"]["schemas"]:
                prefix = (
                    filename.replace(".json", "")
                    .replace("-", "_")
                    .title()
                    .replace("_", "")
                )
                unified["components"]["schemas"][f"{prefix}_{schema_name}"] = schema_def
            else:
                unified["components"]["schemas"][schema_name] = schema_def

    # Sort tags alphabetically
    unified["tags"].sort(key=lambda t: t["name"])
    return unified


def main():
    parser = argparse.ArgumentParser(
        description="Consolidate AIsa OpenAPI specs into a single YAML file"
    )
    parser.add_argument(
        "--output", "-o", default=None, help="Output file path (default: stdout)"
    )
    args = parser.parse_args()

    unified = build_unified_spec()

    # Stats
    num_paths = len(unified["paths"])
    num_ops = sum(
        len([m for m in methods if m in ("get", "post", "put", "patch", "delete")])
        for methods in unified["paths"].values()
    )
    num_schemas = len(unified["components"]["schemas"])
    print(
        f"Consolidated: {num_paths} paths, {num_ops} operations, "
        f"{num_schemas} schemas, {len(unified['tags'])} tags",
        file=sys.stderr,
    )

    # Custom YAML representer for multiline strings
    def str_representer(dumper, data):
        if "\n" in data:
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
        return dumper.represent_scalar("tag:yaml.org,2002:str", data)

    yaml.add_representer(str, str_representer)

    output = yaml.dump(
        unified,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=120,
    )

    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output)
        size_kb = os.path.getsize(args.output) / 1024
        print(f"Written to: {args.output} ({size_kb:.1f} KB)", file=sys.stderr)
    else:
        sys.stdout.write(output)


if __name__ == "__main__":
    main()
