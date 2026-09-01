#!/usr/bin/env python3
"""
Inject machine-readable `x-aisa-pricing` into every paid data-API operation
in the per-provider OpenAPI specs under openapi/*.json.

WHY (audit correction — PR #92 rework)
--------------------------------------
The first version of this generator trusted the public catalog `/info/apis`
scalar (`pricing.normal`). An audit found that scalar is a STATIC FLOOR for
DYNAMIC endpoints (customer_pricing_kind == provider_cost_multiplier): the real
per-call charge scales with the provider response size (rows/results/tweets),
so a flat `per_request` price understated cost by up to ~1000x (e.g. semrush
domain-vs-domain floors at $0.72 but really bills up to $14.40). Several
SimilarWeb credit rates were also wrong versus the metering contract.

This version re-derives EVERY value from DB ground truth (see
scripts/build_pricing_map.py) and branches on the endpoint's customer pricing
kind, emitting one of three models.

PRICE SOURCE
------------
openapi/_pricing_map.json — now CONTRACT-SOURCED (not the /info/apis catalog):
  * integration_customer_pricing_profile_revisions -> kind + tier/multiplier
  * integration_metering_profile_revisions         -> SimilarWeb credit rates
  * usage_logs                                      -> real cost distribution
Keyed by provider-relative gateway path (endpoint inner_uri minus /apis/v1|v2).
Rebuild with scripts/build_pricing_map.py.

MATCHING
--------
Each spec file's operations resolve to a provider-relative path the SAME way
scripts/consolidate_openapi.py derives it: the file's servers[0].url delta
below the /apis/v1 default server is prepended to each path key. We match the
map by that path (the map is keyed by path, method-agnostic — the gateway
accepts GET/POST interchangeably and no path carries divergent prices).

SKIPPED FILES
-------------
Pure-LLM / token-priced specs are skipped (server /v1 or /v1beta). The
consolidated output file (openapi.json) is skipped.

SCHEMA — x-aisa-pricing (branched on customer_pricing_kind)
-----------------------------------------------------------
1. fixed_success -> flat:
   {"model":"per_request","currency":"USD","price_usd":<tier>,"cost_tier":..}

2. provider_cost_multiplier (DYNAMIC) / firecrawl metered_result:
   {"model":"dynamic","currency":"USD","basis":"provider_cost x <mult>",
    "nominal_usd":<pricing_json.normal or min observed>,
    "observed_usd":{"min":..,"p50":..,"p95":..,"max":..},
    "cost_drivers":[{"param":..,"effect":..}],"cost_tier":"variable",
    "note":"nominal_usd is a static reference, NOT a guaranteed minimum; actual
            charge = provider_cost x multiplier and can be higher or lower"}
   (observed_usd carries min+max whenever >=1 successful charge exists; p50/p95
    only when >=20 samples; observed_usd omitted entirely when 0 samples.)

3. SimilarWeb credit-metered -> per_credit:
   {"model":"per_credit","currency":"USD","credit_price_usd":0.10,
    "credit_formula":..,"credit_rate":..,"cost_drivers":[..],
    "cost_tier":..,"example":..}

Cost tiers (USD/call): low <= $0.01, med <= $1.00, high > $1.00. Dynamic ops
use "variable".

Idempotent: re-running strips any prior x-aisa-pricing before re-injecting.

Usage:
    python scripts/inject_pricing.py            # stamp specs in place
"""

import argparse
import json
import os
import sys

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

SW_CREDIT_PRICE_USD = 0.10

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


# ── Contract-sourced pricing map ─────────────────────────────────────────
#
# openapi/_pricing_map.json is produced by scripts/build_pricing_map.py from DB
# ground truth. Each entry (keyed by provider-relative gateway path) carries a
# `kind` we branch on:
#   fixed_success            -> flat per_request
#   provider_cost_multiplier -> dynamic (floor + multiplier + observed range)
#   metered_result           -> dynamic (firecrawl crawl/batch; provider-metered)
#   credit_based             -> SimilarWeb per_credit


def load_pricing_map():
    with open(PRICING_MAP_PATH) as fh:
        data = json.load(fh)
    return data["prices"]


DYNAMIC_NOTE = ("nominal_usd is a static reference, NOT a guaranteed minimum; "
                "actual charge = provider_cost x multiplier and can be higher "
                "or lower")
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


def build_pricing_block(rel_path, prices):
    """Return (block, note) or (None, reason) from the contract-sourced map.

    Branches on the map entry's `kind` (== customer_pricing_kind, sourced from
    the customer pricing / metering contracts) to emit one of the three
    x-aisa-pricing models.
    """
    entry = prices.get(rel_path)
    if entry is None:
        return None, "no-contract-price"
    kind = entry["kind"]

    if kind == "fixed_success":
        price = float(entry["price_usd"])
        block = {
            "model": "per_request",
            "currency": "USD",
            "price_usd": price,
            "cost_tier": entry.get("cost_tier", cost_tier(price)),
        }
        if entry.get("note"):
            block["note"] = entry["note"]
        return block, "fixed_success"

    if kind == "credit_based":  # SimilarWeb
        block = {
            "model": "per_credit",
            "currency": "USD",
            "credit_price_usd": SW_CREDIT_PRICE_USD,
            "credit_formula": entry["credit_formula"],
            "credit_rate": entry["credit_rate"],
            "cost_drivers": entry["cost_drivers"],
            "cost_tier": entry["cost_tier"],
            "example": entry["example"],
        }
        return block, "credit_based"

    if kind in ("provider_cost_multiplier", "metered_result"):
        mult = entry.get("multiplier")
        if mult is not None:
            basis = f"provider_cost x {mult:g}"
        else:  # firecrawl metered_result: provider-reported units
            basis = "provider_cost (metered per result unit)"
        # Ordered so nominal_usd / observed_usd read together after basis.
        ordered = {
            "model": "dynamic",
            "currency": "USD",
            "basis": basis,
            "nominal_usd": entry.get("nominal_usd"),
        }
        # observed_usd: min/max always present when >=1 charge; p50/p95 only
        # when >=20 samples (both shapes produced by build_pricing_map.py).
        if "observed_usd" in entry:
            ordered["observed_usd"] = entry["observed_usd"]
        ordered["cost_drivers"] = entry["cost_drivers"]
        ordered["cost_tier"] = "variable"
        ordered["note"] = DYNAMIC_NOTE
        return ordered, ("metered_result" if mult is None else "provider_cost_multiplier")

    return None, f"unknown-kind:{kind}"


def process_file(filename, prices, report):
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
            block, note = build_pricing_block(rel_path, prices)
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
            elif block["model"] == "dynamic":
                report["dynamic"] += 1

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
                        help="Rebuild openapi/_pricing_map.json from DB dumps first "
                             "(runs scripts/build_pricing_map.py)")
    args = parser.parse_args()

    if args.rebuild_map:
        import subprocess
        subprocess.run([sys.executable,
                        os.path.join(SCRIPT_DIR, "build_pricing_map.py")], check=True)

    prices = load_pricing_map()

    report = {
        "matched": 0,
        "dynamic": 0,
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
        if process_file(filename, prices, report):
            touched.append(filename)

    print(f"Stamped x-aisa-pricing on {report['matched']} operations "
          f"({report['dynamic']} dynamic, {report['similarweb']} SimilarWeb "
          f"per_credit) across {len(touched)} files.", file=sys.stderr)
    print(f"  model kinds: {report['by_note']}", file=sys.stderr)
    print(f"  skipped LLM/token-priced files: {report['skipped_llm_files']}",
          file=sys.stderr)
    print(f"  unmatched operations (no contract price): {len(report['unmatched'])}",
          file=sys.stderr)
    for u in report["unmatched"]:
        print(f"    - {u['file']} {u['method']} {u['path']} ({u['reason']})",
              file=sys.stderr)


if __name__ == "__main__":
    main()
