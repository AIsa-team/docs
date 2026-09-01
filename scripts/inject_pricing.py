#!/usr/bin/env python3
"""
Inject machine-readable `x-aisa-pricing` into every paid data-API operation
in the per-provider OpenAPI specs under openapi/*.json.

WHY
---
Agents calling AIsa data APIs previously had NO way to see per-call cost from
the spec — the OpenAPI documents carried zero price fields across ~700+
operations. This generator stamps each operation with an `x-aisa-pricing`
block sourced from the LIVE AIsa catalog API (the metering-v2-resolved price
the backend actually serves), so downstream agents/tooling can budget and
route by cost.

PRICE SOURCE
------------
openapi/_pricing_map.json — a committed snapshot of the public catalog API:

    https://api.aisa.one/info/apis/category   -> list of api_ids
    https://api.aisa.one/info/apis/<id>       -> endpoint_groups[].endpoints[]
                                                 each with method/path/pricing

`_pricing_map.json` is regenerable; see build_pricing_map() below (or the
one-shot fetch loop documented there). It is NOT sourced from the legacy
`integration_api_endpoints.pricing_json` field.

MATCHING
--------
Each spec file's operations resolve to an absolute provider-relative path the
SAME way scripts/consolidate_openapi.py derives it: the file's servers[0].url
delta below the /apis/v1 default server is prepended to each path key (e.g.
openapi-financial.json's server `…/apis/v1/financial` turns
`/financials/search/line-items` into `/financial/financials/search/line-items`).

The catalog normalizes almost every gateway route to GET (the AIsa relay
accepts GET/POST interchangeably), while the source specs use the provider's
native method (often POST). No catalog path carries divergent prices across
methods, so we match on (METHOD, path) first and fall back to path-only.

SKIPPED FILES
-------------
Pure-LLM / token-priced specs are skipped — their cost is per-token, not
per-call, so a flat per_request scalar would misrepresent them. Detection is
identical to consolidate's LLM test: the file's server is /v1 or /v1beta.
(account.json, openai-chat.json, claude-messages.json, gemini-openapi.json,
chat-image-generation.json, openai-images-generations.json, jina.json.)
The consolidated output file (openapi.json — Mintlify placeholder) is skipped.

SCHEMA — x-aisa-pricing
-----------------------
Flat per-request (default):
    {"model":"per_request","currency":"USD","price_usd":<normal>,
     "cost_tier":"<low|med|high>"}

  Cost tiers (documented cutoffs):
    low  : price_usd <= $0.01
    med  : price_usd <= $1.00
    high : price_usd  > $1.00

SimilarWeb (credit-metered, parameter-driven):
    {"model":"per_credit","currency":"USD","credit_price_usd":0.10,
     "credit_formula":"<per-endpoint>","cost_drivers":[...],
     "cost_tier":"<...>","example":"<...>"}

  SimilarWeb is billed in credits at $0.10/credit; a flat scalar hides the
  real, parameter-driven cost. Per-endpoint credit rates/formulas/examples
  come from the SimilarWeb rate model (vault/similarweb/*). cost_tier for SW
  uses the SAME cutoffs applied to a TYPICAL-call USD cost (typical credits ×
  $0.10). SW endpoints the catalog prices at $0 (snapshot/trend aggregators)
  are stamped per_credit with a note.

Idempotent: re-running overwrites any prior x-aisa-pricing.

Usage:
    python scripts/inject_pricing.py            # stamp specs in place
    python scripts/inject_pricing.py --rebuild-map   # refetch catalog first
"""

import argparse
import json
import os
import sys
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
OPENAPI_DIR = os.path.join(REPO_ROOT, "openapi")
PRICING_MAP_PATH = os.path.join(OPENAPI_DIR, "_pricing_map.json")

# Files that are not per-provider data-API specs.
SKIP_OUTPUT_FILES = {"openapi.json"}  # Mintlify/consolidated placeholder

# Same server test consolidate uses to detect LLM (token-priced) ops.
DEFAULT_SERVER_URL = "https://api.aisa.one/apis/v1"
LLM_SERVER_URLS = {
    "https://api.aisa.one/v1",
    "https://api.aisa.one/v1beta",
}

HTTP_METHODS = ("get", "post", "put", "patch", "delete")

CATALOG_CATEGORY_URL = "https://api.aisa.one/info/apis/category"
CATALOG_DETAIL_URL = "https://api.aisa.one/info/apis/{id}"

# ── Cost-tier cutoffs (USD per call) ─────────────────────────────────────
#   low  <= $0.01
#   med  <= $1.00
#   high  > $1.00
TIER_LOW_MAX = 0.01
TIER_MED_MAX = 1.00


def cost_tier(price_usd):
    """Bucket a per-call USD cost into low/med/high."""
    if price_usd <= TIER_LOW_MAX:
        return "low"
    if price_usd <= TIER_MED_MAX:
        return "med"
    return "high"


# ── SimilarWeb per-endpoint credit model ─────────────────────────────────
#
# $0.10 per credit. Rates/formulas/examples sourced from:
#   vault/similarweb/per-endpoint-rates-20260814.md   (official-doc rates)
#   vault/similarweb/sw-user-consumption-guide-20260817.md (examples + the
#     96cr-naked vs 1cr-narrowed timeseries anchor)
#
# Keyed by provider-relative OpenAPI path. `typical_usd` drives cost_tier and
# reflects a representative (not worst-case) call so the tier is honest for
# ordinary usage; the `example` string carries the naked-vs-narrowed range.
SW_CREDIT_PRICE_USD = 0.10

SW_DRIVER_TIMESERIES = [
    {"param": "metrics",
     "effect": "timeseries: default returns all ~8 metrics; specify only needed metrics"},
    {"param": "start_date/end_date",
     "effect": "timeseries: default full ~12 months; narrow the window"},
]
SW_DRIVER_LIST = [
    {"param": "limit",
     "effect": "list endpoints: credits = rate x rows; default 20 rows — lower it"},
]


def _sw(model_formula, drivers, typical_usd, example, credit_rate=None):
    block = {
        "model": "per_credit",
        "currency": "USD",
        "credit_price_usd": SW_CREDIT_PRICE_USD,
        "credit_formula": model_formula,
        "cost_drivers": drivers,
        "cost_tier": cost_tier(typical_usd),
        "example": example,
    }
    if credit_rate is not None:
        block["credit_rate"] = credit_rate
    return block


# path -> x-aisa-pricing block. Only SW paths that exist in the spec need entries.
SW_PRICING = {
    # ── Tier B: time-series (metrics x time-buckets) ──────────────────────
    "/similarweb/website/traffic-engagement": _sw(
        "credits = metrics_selected x time_buckets (1 credit / metric / month); default = all metrics x full window",
        SW_DRIVER_TIMESERIES, typical_usd=0.30,
        example="metrics=[visits] + 1 month = 1 credit ($0.10); naked call (all ~8 metrics x ~12 months) = up to 96 credits ($9.60). Always pass metrics + a date window.",
        credit_rate="1 credit / metric / month"),
    "/similarweb/website/ranking": _sw(
        "credits = months_in_window (1 credit / month)",
        SW_DRIVER_TIMESERIES, typical_usd=0.10,
        example="1 month = 1 credit ($0.10); 12 months = 12 credits ($1.20).",
        credit_rate="1 credit / month"),
    "/similarweb/website/ppc-spend": _sw(
        "credits = 5 x months_in_window (5 credits / month)",
        SW_DRIVER_TIMESERIES, typical_usd=0.50,
        example="1 month = 5 credits ($0.50); 12 months = 60 credits ($6.00). Narrow the date window.",
        credit_rate="5 credits / month"),
    "/similarweb/website/deduplicated-audience": _sw(
        "credits = months_in_window (1 credit / month)",
        SW_DRIVER_TIMESERIES, typical_usd=0.10,
        example="1 month = 1 credit ($0.10); 12 months = 12 credits ($1.20).",
        credit_rate="1 credit / month"),
    "/similarweb/website/marketing-channel-sources-legacy": _sw(
        "credits = 7 x results (time-series traffic-sources; reclassified from list)",
        SW_DRIVER_TIMESERIES, typical_usd=0.70,
        example="Traffic Sources ~7 credits/result ($0.70+). Legacy endpoint — reconciliation note: upstream may consume more than metered; prefer the non-legacy variant when possible.",
        credit_rate="7 credits / result"),

    # ── Tier A: row-billed lists (rate x rows, default 20 rows) ────────────
    "/similarweb/website/top-sites-ranking": _sw(
        "credits = ceil(1 x rows); default 20 rows",
        SW_DRIVER_LIST, typical_usd=2.00,
        example="20 rows = 20 credits ($2.00); limit=5 = 5 credits ($0.50).",
        credit_rate="1 credit / row"),
    "/similarweb/website/referrals": _sw(
        "credits = ceil(3 x rows); default 20 rows",
        SW_DRIVER_LIST, typical_usd=6.00,
        example="20 rows = 60 credits ($6.00); limit=5 = 15 credits ($1.50).",
        credit_rate="3 credits / row"),
    "/similarweb/website/ad-networks": _sw(
        "credits = ceil(3 x rows); default 20 rows",
        SW_DRIVER_LIST, typical_usd=6.00,
        example="20 rows = 60 credits ($6.00); limit=5 = 15 credits ($1.50).",
        credit_rate="3 credits / row"),
    "/similarweb/website/similar-sites": _sw(
        "credits = ceil(2 x rows); default 20 rows (SW hard cap 40)",
        SW_DRIVER_LIST, typical_usd=4.00,
        example="20 rows = 40 credits ($4.00); limit=5 = 10 credits ($1.00).",
        credit_rate="2 credits / row"),
    "/similarweb/website/audience-interest": _sw(
        "credits = ceil(5 x rows); default 20 rows",
        SW_DRIVER_LIST, typical_usd=10.00,
        example="20 rows = 100 credits ($10.00); limit=5 = 25 credits ($2.50). Expensive — clamp limit.",
        credit_rate="5 credits / row"),
    "/similarweb/website/popular-pages": _sw(
        "credits = ceil(3 x rows); default 20 rows",
        SW_DRIVER_LIST, typical_usd=6.00,
        example="20 rows = 60 credits ($6.00); limit=5 = 15 credits ($1.50).",
        credit_rate="3 credits / row"),
    "/similarweb/website/subdomains": _sw(
        "credits = ceil(2 x rows); default 20 rows",
        SW_DRIVER_LIST, typical_usd=4.00,
        example="20 rows = 40 credits ($4.00); limit=5 = 10 credits ($1.00).",
        credit_rate="2 credits / row"),
    "/similarweb/search/website-keywords": _sw(
        "credits = ceil(0.13 x rows); default 20 rows",
        SW_DRIVER_LIST, typical_usd=0.30,
        example="20 rows = 3 credits ($0.30); cheap keyword-family endpoint.",
        credit_rate="0.13 credits / row"),
    "/similarweb/search/keyword-competitors": _sw(
        "credits = ceil(0.07 x rows); default 20 rows",
        SW_DRIVER_LIST, typical_usd=0.20,
        example="20 rows = 2 credits ($0.20); cheap keyword-family endpoint.",
        credit_rate="0.07 credits / row"),
    "/similarweb/search/serp-players-aggregated": _sw(
        "credits = ceil(0.07 x rows); default 20 rows",
        SW_DRIVER_LIST, typical_usd=0.20,
        example="20 rows = 2 credits ($0.20).",
        credit_rate="0.07 credits / row"),
    "/similarweb/search/serp-players-timeseries": _sw(
        "credits = ceil(0.07 x rows) x time-buckets (SERP players over time)",
        SW_DRIVER_LIST + SW_DRIVER_TIMESERIES, typical_usd=0.20,
        example="20 rows x 1 bucket = 2 credits ($0.20); widening the date window multiplies by bucket count.",
        credit_rate="0.07 credits / row / bucket"),
    "/similarweb/search/landing-pages": _sw(
        "credits = ceil(0.10 x rows); default 20 rows",
        SW_DRIVER_LIST, typical_usd=0.20,
        example="20 rows = 2 credits ($0.20).",
        credit_rate="0.10 credits / row"),

    # ── Tier C: fixed / custom per request ────────────────────────────────
    "/similarweb/website/technologies": _sw(
        "credits = 10 (fixed per request; confirm multi-domain multiplier)",
        [{"param": "domains", "effect": "fixed 10 credits/request; multi-domain may multiply"}],
        typical_usd=1.00,
        example="1 request = 10 credits ($1.00).",
        credit_rate="10 credits / request (fixed)"),
    "/similarweb/website/demographics": _sw(
        "credits = 6 (fixed per request; aggregated merges age+gender)",
        [{"param": "domains", "effect": "fixed 6 credits/request"}],
        typical_usd=0.60,
        example="1 request = 6 credits ($0.60).",
        credit_rate="6 credits / request (fixed)"),
    "/similarweb/website/audience-overlap": _sw(
        "credits = domains - 1 (2 domains=1, 3=2, 4=3, 5=4)",
        [{"param": "domains", "effect": "credits = number_of_domains - 1"}],
        typical_usd=0.20,
        example="2 domains = 1 credit ($0.10); 5 domains = 4 credits ($0.40).",
        credit_rate="(domains - 1) credits / request"),

    # ── Catalog priced these at $0 (aggregator/snapshot views). Metered in ─
    #    credits like the rest; treat as low until a rate is published.
    "/similarweb/website-traffic-snapshot": _sw(
        "credits per underlying data pulled (catalog lists $0; treat as light aggregate)",
        SW_DRIVER_TIMESERIES, typical_usd=0.30,
        example="Aggregate snapshot view; catalog scalar is $0. Prefer explicit metrics + date window; cost tracks the underlying traffic-and-engagement pulls.",
        credit_rate="see traffic-and-engagement"),
    "/similarweb/website-traffic-trend": _sw(
        "credits per underlying data pulled (catalog lists $0; treat as light aggregate)",
        SW_DRIVER_TIMESERIES, typical_usd=0.30,
        example="Aggregate trend view; catalog scalar is $0. Prefer explicit metrics + date window; cost tracks the underlying traffic-and-engagement pulls.",
        credit_rate="see traffic-and-engagement"),
    "/similarweb/website-top-geographies": _sw(
        "credits = ceil(8 x rows) (traffic-geography family; default 20 rows)",
        SW_DRIVER_LIST, typical_usd=16.00,
        example="20 rows = 160 credits ($16.00) — the most expensive SW view; clamp limit and country filters hard.",
        credit_rate="8 credits / row"),
}


def is_similarweb_path(path):
    return path.startswith("/similarweb/")


# ── Catalog fetch / price-map build ──────────────────────────────────────

def _http_get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "aisa-docs-pricing/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_pricing_map():
    """Fetch the live catalog and build the (METHOD path)->entry price map.

    Regenerates openapi/_pricing_map.json. Key = "METHOD <rel-path>" where
    rel-path is the catalog gateway path with the leading /apis/v1 (or v2)
    stripped, so it matches the per-file OpenAPI provider-relative path.
    """
    from datetime import datetime, timezone

    cat = _http_get_json(CATALOG_CATEGORY_URL)
    ids = [a["id"] for a in cat.get("apis", [])]
    entries = {}
    gaps = []
    for api_id in ids:
        try:
            detail = _http_get_json(CATALOG_DETAIL_URL.format(id=api_id))
        except Exception as e:  # noqa: BLE001
            gaps.append(f"{api_id}: fetch failed ({e})")
            continue
        api = detail.get("api", {})
        groups = api.get("endpoint_groups")
        if not groups:
            gaps.append(f"{api_id}: no endpoint_groups")
            continue
        for g in groups:
            for e in g.get("endpoints") or []:
                method = e["method"].upper()
                full = e["path"]
                rel = full
                for pref in ("/apis/v1", "/apis/v2"):
                    if rel.startswith(pref):
                        rel = rel[len(pref):]
                        break
                entries[f"{method} {rel}"] = {
                    "method": method,
                    "path": rel,
                    "gateway_path": full,
                    "api_id": api_id,
                    "pricing": e.get("pricing") or {},
                }
    out = {
        "_note": (
            "Machine-readable price map for AIsa data-API operations. Keyed by "
            "'METHOD <provider-relative-path>' (catalog gateway path with the "
            "leading /apis/v1 or /apis/v2 stripped). Source: "
            "https://api.aisa.one/info/apis (metering-v2-resolved prices the "
            "backend serves). Regenerate: python scripts/inject_pricing.py "
            "--rebuild-map. Prices in USD."
        ),
        "_generated_at": datetime.now(timezone.utc).isoformat(),
        "_source": "https://api.aisa.one/info/apis",
        "_entry_count": len(entries),
        "prices": dict(sorted(entries.items())),
    }
    if gaps:
        out["_gaps"] = gaps
    with open(PRICING_MAP_PATH, "w") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"Rebuilt {PRICING_MAP_PATH}: {len(entries)} entries, "
          f"{len(gaps)} gaps", file=sys.stderr)
    return out


def load_pricing_map():
    with open(PRICING_MAP_PATH) as fh:
        data = json.load(fh)
    prices = data["prices"]
    by_key = prices
    by_path = {}
    for entry in prices.values():
        by_path.setdefault(entry["path"], entry)
    return by_key, by_path


# ── Format-preserving injection ──────────────────────────────────────────
#
# We add exactly ONE key (`x-aisa-pricing`) to each priced operation object.
# To keep diffs purely additive and avoid re-serializing (which would collapse
# or expand the source specs' mixed inline/expanded container styles), we
# insert the serialized pricing block as text immediately after each
# operation object's opening brace, at the operation's own indentation. The
# rest of every file stays byte-identical to the source.

def detect_indent(filepath):
    """Return the indent used by the file (int spaces)."""
    with open(filepath) as fh:
        for line in fh:
            stripped = line.lstrip(" ")
            if stripped and stripped != line:
                return len(line) - len(stripped)
    return 2


def _find_key_value_open(text, start, key):
    """Return the offset of the '{' opening the object value of `key`.

    Scans forward from `start` for the literal JSON string key (`"key"`),
    then the ':' and the next '{'. Keys are matched in document order, so a
    running cursor keeps matches unambiguous. Raises if not found.
    """
    needle = json.dumps(key)  # exact JSON-escaped key literal, incl. quotes
    i = text.index(needle, start)
    j = text.index(":", i + len(needle))
    k = text.index("{", j)
    return k


def _strip_existing_pricing(text, indent):
    """Remove any previously-injected x-aisa-pricing block (idempotency).

    Matches the exact block we emit: a `"x-aisa-pricing": { ... },` inserted
    right after an operation's opening brace. Uses brace matching so nested
    objects in the block are handled.
    """
    marker = '"x-aisa-pricing":'
    out = text
    while True:
        idx = out.find(marker)
        if idx == -1:
            return out
        # find the value '{' and its matching '}'
        b = out.index("{", idx)
        depth = 0
        p = b
        while p < len(out):
            c = out[p]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            p += 1
        end = p + 1
        # swallow exactly the single trailing comma we appended (plus any
        # spaces between the closing brace and it), but NOT the newline that
        # belongs to the following key.
        while end < len(out) and out[end] == " ":
            end += 1
        if end < len(out) and out[end] == ",":
            end += 1
        # remove the leading newline + indent that we inserted before the block
        ls = idx
        while ls > 0 and out[ls - 1] == " ":
            ls -= 1
        if ls > 0 and out[ls - 1] == "\n":
            ls -= 1
        out = out[:ls] + out[end:]
    return out


def _render_insert(block, text, op_open, indent):
    """Serialize `block` as the text inserted right after `op_open`'s '{'.

    The inserted lines are indented one level deeper than the operation
    object's own indentation, matching the file's existing style.
    """
    # Determine the operation object's base indentation from the line holding
    # its opening brace.
    line_start = text.rfind("\n", 0, op_open) + 1
    base_indent = len(text[line_start:op_open]) - len(text[line_start:op_open].lstrip(" "))
    child = " " * (base_indent + indent)
    body = json.dumps(block, indent=indent, ensure_ascii=False)
    # Re-indent every line of the block to sit at `child` depth.
    lines = body.split("\n")
    reindented = [lines[0]] + [child + ln for ln in lines[1:]]
    block_text = "\n".join(reindented)
    return f"\n{child}\"x-aisa-pricing\": {block_text},"


def file_server_url(spec):
    servers = spec.get("servers", [])
    return servers[0].get("url", "") if servers else ""


def path_prefix_for(spec):
    url = file_server_url(spec)
    if url in LLM_SERVER_URLS:
        return None  # signal: skip file
    if url.startswith(DEFAULT_SERVER_URL + "/"):
        return url[len(DEFAULT_SERVER_URL):]
    return ""


def build_pricing_block(method, rel_path, by_key, by_path):
    """Return (block, source_note) or (None, reason) if no price."""
    if is_similarweb_path(rel_path):
        block = SW_PRICING.get(rel_path)
        if block is not None:
            return dict(block), "similarweb-rate-model"
        # SW op with no rate-table match: fall back to catalog scalar.
        entry = by_key.get(f"{method} {rel_path}") or by_path.get(rel_path)
        if entry and entry["pricing"].get("normal") is not None:
            price = float(entry["pricing"]["normal"])
            return ({
                "model": "per_request",
                "currency": "USD",
                "price_usd": price,
                "cost_tier": cost_tier(price),
            }, "similarweb-no-rate-match-catalog-scalar")
        return None, "similarweb-unmatched"

    entry = by_key.get(f"{method} {rel_path}")
    match_kind = "exact"
    if entry is None:
        entry = by_path.get(rel_path)
        match_kind = "path-only"
    if entry is None:
        return None, "no-catalog-price"
    normal = entry["pricing"].get("normal")
    if normal is None:
        return None, "catalog-price-null"
    price = float(normal)
    return ({
        "model": "per_request",
        "currency": "USD",
        "price_usd": price,
        "cost_tier": cost_tier(price),
    }, match_kind)


def process_file(filename, by_key, by_path, report):
    filepath = os.path.join(OPENAPI_DIR, filename)
    with open(filepath) as fh:
        raw_text = fh.read()
    spec = json.loads(raw_text)

    prefix = path_prefix_for(spec)
    if prefix is None:
        report["skipped_llm_files"].append(filename)
        return False

    indent = detect_indent(filepath)
    # Idempotency: strip any prior injection so offsets are computed against
    # clean source and re-runs don't stack blocks.
    original_text = _strip_existing_pricing(raw_text, indent)

    # Collect (operation-object-open-brace-offset, pricing-block) insertions.
    # We locate each operation object in the ORIGINAL text and insert the
    # serialized pricing block right after its `{`, so the file stays
    # byte-for-byte identical except for the additive block. Idempotency:
    # any pre-existing x-aisa-pricing key is stripped first via a clean load.
    insertions = []  # list of (offset, text_to_insert)
    paths_obj = spec.get("paths", {})
    paths_cursor = _find_key_value_open(original_text, 0, "paths")

    for path, methods in paths_obj.items():
        if not isinstance(methods, dict):
            continue
        rel_path = prefix + path
        path_open = _find_key_value_open(original_text, paths_cursor, path)
        method_cursor = path_open
        for method, op in methods.items():
            if not isinstance(op, dict):
                continue
            op_open = _find_key_value_open(original_text, method_cursor, method)
            method_cursor = op_open
            if method not in HTTP_METHODS:
                continue
            block, note = build_pricing_block(
                method.upper(), rel_path, by_key, by_path)
            if block is None:
                report["unmatched"].append(
                    {"file": filename, "method": method.upper(),
                     "path": rel_path, "reason": note})
                continue
            insertions.append((op_open, _render_insert(block, original_text, op_open, indent)))
            report["matched"] += 1
            report["by_note"][note] = report["by_note"].get(note, 0) + 1
            if block["model"] == "per_credit":
                report["similarweb"] += 1

    if not insertions:
        return False

    # Apply insertions right-to-left so earlier offsets stay valid.
    new_text = original_text
    for offset, text in sorted(insertions, key=lambda x: -x[0]):
        new_text = new_text[:offset + 1] + text + new_text[offset + 1:]
    with open(filepath, "w") as fh:
        fh.write(new_text)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild-map", action="store_true",
                        help="Refetch the live catalog into openapi/_pricing_map.json first")
    args = parser.parse_args()

    if args.rebuild_map:
        build_pricing_map()

    by_key, by_path = load_pricing_map()

    report = {
        "matched": 0,
        "similarweb": 0,
        "unmatched": [],
        "skipped_llm_files": [],
        "by_note": {},
    }

    files = sorted(f for f in os.listdir(OPENAPI_DIR)
                   if f.endswith(".json") and f not in SKIP_OUTPUT_FILES
                   and not f.startswith("_"))
    touched = []
    for filename in files:
        if process_file(filename, by_key, by_path, report):
            touched.append(filename)

    print(f"Stamped x-aisa-pricing on {report['matched']} operations "
          f"({report['similarweb']} SimilarWeb per_credit) across "
          f"{len(touched)} files.", file=sys.stderr)
    print(f"  match kinds: {report['by_note']}", file=sys.stderr)
    print(f"  skipped LLM/token-priced files: {report['skipped_llm_files']}",
          file=sys.stderr)
    print(f"  unmatched operations (no catalog price): {len(report['unmatched'])}",
          file=sys.stderr)
    for u in report["unmatched"]:
        print(f"    - {u['file']} {u['method']} {u['path']} ({u['reason']})",
              file=sys.stderr)


if __name__ == "__main__":
    main()
