#!/usr/bin/env python3
"""
Consolidate individual AIsa OpenAPI spec files into a single unified openapi.yaml.

Reads all JSON specs from the openapi/ directory, merges paths (with correct
server-path prefixes) and schemas, and outputs a single OpenAPI 3.1 YAML file
that includes the x402 (pay-per-call) surface:

  * Three top-level servers: /apis/v1 (Bearer), /apis/v2 (x402),
    /v1 (LLM, OpenAI-compatible).
  * Every paid data-API op carries an `x-x402` annotation pointing at
    its absolute /apis/v2 path and the open-source aisa-proxy gateway.
  * Every paid path is mirrored under `/apis/v2/{rel}` via a $ref to
    the relative op — single source of truth for parameters, responses,
    schemas, tags.
  * LLM ops are never mirrored at /apis/v2.
  * /services/aigc/* (async video generation) is denylisted from the
    mirror — the runtime gateway returns 404, not 402, so promising a
    /apis/v2 surface there would make the spec a liar.

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
    "apollo.json": "Sales Intelligence",
    "dataforseo.json": "SEO & Search Data",
    "agentmail.json": "Agent Email",
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
    "Sales Intelligence": "B2B contact and company enrichment, search, and outreach via Apollo.io",
    "SEO & Search Data": "SERP, keywords, backlinks, on-page, business listings, and AI optimization via DataForSEO",
    "Agent Email": "AI-agent email accounts, inboxes, threads, drafts, and message send/reply via AgentMail.to",
}

# Server URLs used by the unified spec — keep in sync with the
# `servers` list inside build_unified_spec().
DATA_API_SERVER_URL = "https://api.aisa.one/apis/v1"
DATA_API_X402_SERVER_URL = "https://api.aisa.one/apis/v2"
LLM_SERVER_URL = "https://api.aisa.one/v1"
X402_IMPLEMENTATION_URL = "https://github.com/AIsa-team/aisa-proxy"

# Path-prefix denylist for the v2 (x402) mirror.
#
# Some operations look mirrorable (non-LLM, no per-op /v1 override)
# but the runtime aisa-proxy gateway doesn't expose them at /apis/v2
# — probing those paths returns 404 instead of the expected x402 402
# challenge, which makes the spec a liar.
#
# Currently denylisted:
#   /services/aigc/* — async video-generation endpoints. Not in
#     aisa-proxy's pricing catalog; the payment lifecycle for async
#     long-running jobs differs from per-call x402 settlement.
#
# Add to this list only after confirming the runtime gateway returns
# 404 (not 402) for the endpoint at /apis/v2.
V2_MIRROR_DENYLIST_PREFIXES = ("/services/aigc/",)


def is_v2_excluded(path_key):
    """Return True if path_key is on the v2-mirror denylist."""
    return any(path_key.startswith(prefix) for prefix in V2_MIRROR_DENYLIST_PREFIXES)


def is_llm_op(operation):
    """Return True if the operation has an LLM /v1 server override."""
    if not isinstance(operation, dict):
        return False
    for s in operation.get("servers") or []:
        if isinstance(s, dict) and s.get("url") == LLM_SERVER_URL:
            return True
    return False


def json_pointer_escape(s):
    """JSON-pointer escape per RFC 6901: `~` → `~0`, `/` → `~1`."""
    return s.replace("~", "~0").replace("/", "~1")


def inject_x402_annotations(spec):
    """Annotate every data-API operation with `x-x402`.

    The signal for "this op is paid via x402" is absence of an LLM /v1
    server override AND not on the denylist. The annotation holds NO
    pricing — prices change upstream and live in the runtime HTTP 402
    challenge response. We expose only the absolute v2 path and link
    the open-source gateway implementation. Idempotent.
    """
    annotated = 0
    for path_key, ops in spec.get("paths", {}).items():
        if path_key.startswith("/apis/v2/"):
            continue  # mirrors get the annotation transitively via $ref
        excluded = is_v2_excluded(path_key)
        for method, op in ops.items():
            if not isinstance(op, dict):
                continue
            if method in ("parameters", "servers"):
                continue
            if excluded or is_llm_op(op):
                # Defensive: drop any stale annotation that shouldn't
                # be there (e.g., from a previous run before denylist).
                op.pop("x-x402", None)
                continue
            op["x-x402"] = {
                "path": f"/apis/v2{path_key}",
                "source": X402_IMPLEMENTATION_URL,
            }
            annotated += 1
    return annotated


def add_v2_path_mirrors(spec):
    """Add explicit `/apis/v2/{rel}` path-key mirrors for every paid op.

    Each mirror path-item carries:
      - a path-level `servers` override pointing at the bare host
        (`https://api.aisa.one`), so the absolute path key resolves
        correctly without colliding with the top-level /apis/v1 server;
      - operation entries that `$ref` the corresponding operation
        under the relative path key — single source of truth for
        parameters, responses, schemas, x-x402, tags.

    LLM ops are never mirrored. Denylisted paths are skipped (and any
    stale mirrors of denylisted/missing paths are garbage-collected).
    Idempotent.
    """
    mirrored = 0
    new_paths = {}
    # Set of relative paths that exist NOW (so we can garbage-collect
    # stale mirrors whose underlying path no longer exists).
    relative_paths = {
        p for p in spec.get("paths", {}) if not p.startswith("/apis/v2/")
    }

    for path_key, ops in spec.get("paths", {}).items():
        if path_key.startswith("/apis/v2/"):
            underlying = path_key[len("/apis/v2"):]
            if underlying not in relative_paths:
                continue  # stale mirror — drop
            if is_v2_excluded(underlying):
                continue  # mirror of a now-denylisted path — drop
        new_paths[path_key] = ops
        if path_key.startswith("/apis/v2/"):
            continue  # already a mirror, don't double-mirror
        if is_v2_excluded(path_key):
            continue  # not exposed at /apis/v2

        # Skip if every operation on this path is LLM-only.
        all_llm = True
        for method, op in ops.items():
            if not isinstance(op, dict):
                continue
            if method in ("parameters", "servers"):
                continue
            if not is_llm_op(op):
                all_llm = False
                break
        if all_llm:
            continue

        v2_path_key = f"/apis/v2{path_key}"
        if v2_path_key in new_paths:
            continue  # idempotent — already mirrored

        escaped_rel = json_pointer_escape(path_key)
        mirror = {
            "servers": [
                {
                    "url": "https://api.aisa.one",
                    "description": (
                        "AIsa root host (path key carries the /apis/v2 prefix)"
                    ),
                }
            ],
        }
        for method, op in ops.items():
            if not isinstance(op, dict):
                continue
            if method in ("parameters", "servers"):
                continue
            if is_llm_op(op):
                continue  # don't mirror LLM ops on mixed-method paths
            mirror[method] = {"$ref": f"#/paths/{escaped_rel}/{method}"}
        if len(mirror) == 1:
            continue  # only `servers`, no operations — nothing to mirror
        new_paths[v2_path_key] = mirror
        mirrored += 1
    spec["paths"] = new_paths
    return mirrored


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
        # Three-server setup. Data API ops inherit the top-level list,
        # so OpenAPI consumers can pick /apis/v1 (Bearer) or /apis/v2
        # (x402 pay-per-call) at call time. LLM ops have an
        # operation-level override that pins them to /v1.
        #
        #   * /apis/v1 — default server for data APIs (Bearer)
        #   * /apis/v2 — same data API surface, mirrored for x402
        #     pay-per-call. No registration; receive HTTP 402 challenge,
        #     settle with stablecoin micropayment. Spec: x402.org
        #   * /v1     — LLM inference (OpenAI-compatible)
        #
        # Path keys stay relative to whichever server applies, matching
        # the per-file spec convention.
        "servers": [
            {
                "url": "https://api.aisa.one/apis/v1",
                "description": (
                    "AIsa Data APIs (Bearer auth — register at https://aisa.one)"
                ),
            },
            {
                "url": "https://api.aisa.one/apis/v2",
                "description": (
                    "AIsa Data APIs (x402 pay-per-call) — same surface as "
                    "/apis/v1, mirrored. No registration; receive HTTP 402 "
                    "challenge, settle with stablecoin micropayment. "
                    "Spec: https://www.x402.org. "
                    "Open-source gateway implementation: "
                    "https://github.com/AIsa-team/aisa-proxy"
                ),
                # Non-standard `x-*` extension naming the open-source
                # gateway that serves this surface. Ignored by vanilla
                # OpenAPI parsers; tooling that walks
                # `servers[].x-implementation` can deep-link the repo.
                "x-implementation": "https://github.com/AIsa-team/aisa-proxy",
            },
            {
                "url": "https://api.aisa.one/v1",
                "description": "AIsa LLM Inference (OpenAI-compatible, Bearer auth)",
            },
        ],
        "security": [{"BearerAuth": []}],
        "tags": [],
        "paths": {},
        "components": {
            "securitySchemes": {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "AIsa API key. Get yours at https://aisa.one",
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

        # Detect which top-level server this file's paths resolve
        # against. /v1 specs need an operation-level `servers` override
        # in the unified spec; /apis/v1 specs use the default (first)
        # server and need no override. Path keys are kept RELATIVE in
        # the unified output, matching the per-file convention.
        #
        # When a file's server is a SUB-path of the unified default
        # server (e.g. `/apis/v1/financial`), prepend the delta to
        # each path key so the merged path resolves to the correct
        # absolute URL. Without this, `/financials/balance-sheets`
        # from a file with server `…/apis/v1/financial` collides at
        # the top level instead of becoming `/financial/financials/
        # balance-sheets`.
        servers = spec.get("servers", [])
        file_server_url = servers[0].get("url", "") if servers else ""
        is_llm = file_server_url == "https://api.aisa.one/v1"
        default_server_url = unified["servers"][0]["url"]
        path_prefix = ""
        if (
            file_server_url.startswith(default_server_url + "/")
            and not is_llm
        ):
            path_prefix = file_server_url[len(default_server_url):]

        # Merge paths — preserve relative path keys
        for path, methods in spec.get("paths", {}).items():
            for method, operation in methods.items():
                if isinstance(operation, dict):
                    operation["tags"] = [tag]
                    # Drop any per-op servers from the input file
                    operation.pop("servers", None)
                    # Add LLM-server override on operations from /v1
                    # files so OpenAPI consumers route them to /v1
                    # instead of the default /apis/v1.
                    if is_llm:
                        operation["servers"] = [
                            {"url": "https://api.aisa.one/v1"}
                        ]

            full_path = path_prefix + path

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

    # Layer x402 surface on top of the consolidated spec:
    #   1. Annotate every paid data-API op with `x-x402`.
    #   2. Add `/apis/v2/{rel}` path-item mirrors that $ref the
    #      relative op — single source of truth.
    # Order matters: x-x402 annotations must run BEFORE mirroring so
    # the annotation lives on the relative op and the $ref'd mirror
    # picks it up transitively.
    x402_annotated = inject_x402_annotations(unified)
    v2_mirrored = add_v2_path_mirrors(unified)

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
    print(
        f"  x402: {x402_annotated} ops annotated, "
        f"{v2_mirrored} /apis/v2/* mirrors added",
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

    # Prepend an autogeneration banner so anyone editing the served
    # file knows changes won't survive the next sync. YAML treats `#`
    # lines as comments, so this doesn't affect parsers.
    banner = (
        "# ──────────────────────────────────────────────────────────────────\n"
        "# AUTOGENERATED — do not edit by hand.\n"
        "#\n"
        "# Source of truth: AIsa-team/docs (openapi/*.json).\n"
        "# Producer:        scripts/consolidate_openapi.py\n"
        "# Sync workflow:   .github/workflows/sync-openapi.yml\n"
        "#\n"
        "# To change this file, edit the per-API spec under\n"
        "#   https://github.com/AIsa-team/docs/tree/main/openapi\n"
        "# and merge to main. The sync workflow regenerates and pushes\n"
        "# the consolidated spec to the website repo on every push.\n"
        "#\n"
        "# Direct edits here will be overwritten on the next sync.\n"
        "# ──────────────────────────────────────────────────────────────────\n"
    )
    output = banner + output

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
