#!/usr/bin/env python3
"""
Build openapi/_pricing_map.json from AIsa metering GROUND TRUTH (DB 34),
NOT from the public /info/apis catalog.

WHY (audit correction)
----------------------
The prior map trusted the catalog `/info/apis` scalar (`pricing.normal`). For
dynamic endpoints (customer_pricing_kind == provider_cost_multiplier) that
scalar is a STATIC FLOOR, not the real per-call charge — the true cost scales
with the provider response size (rows/results/tweets). And several SimilarWeb
credit rates in the catalog disagreed with the metering contract. This builder
re-derives every value from the contract tables so the docs match what the
backend actually bills.

SOURCES (all DB 34, MySQL)
--------------------------
- integration_api_endpoints                       : id, provider_id, inner_uri,
    config_json (MeteredV2 binding: customer_pricing_profile/-revision,
    profile_key/-revision, or the firecrawl metered_result schema),
    pricing_json (static floor).
- integration_customer_pricing_profile_revisions  : contract_json.kind
    (fixed_success | provider_cost_multiplier) and .tiers (micros for fixed,
    multiplier*1e6 for the dynamic kind).
- integration_metering_profile_revisions          : contract_json.cost_contract
    for SimilarWeb credit derivation
    (kind=response_count: units_per_count/unit_scale/maximum_units;
     kind=plan_units: plan_units.fixed_units | {input|inputs, input_multiplier}).
- usage_logs                                       : real customer_cost_micros_usd
    distribution per endpoint (status=success) → floor/p50/p95/max for dynamic.

This script is NOT self-fetching; the maintainer runs the four queries (see
scripts/README or the task doc) and drops the JSON dumps next to it, then runs
this to emit openapi/_pricing_map.json. The committed map is the artifact
inject_pricing.py consumes.

Key of each entry = provider-relative gateway path (endpoint.inner_uri with the
leading /apis/v1 or /apis/v2 stripped) — this matches the per-file OpenAPI path.
"""
import json
import os
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
OPENAPI_DIR = os.path.join(REPO_ROOT, "openapi")
PRICING_MAP_PATH = os.path.join(OPENAPI_DIR, "_pricing_map.json")

# DB dump inputs (produced by the four ground-truth queries).
DUMP_DIR = os.environ.get("PRICING_DUMP_DIR", "/tmp")
EPROWS = os.path.join(DUMP_DIR, "eprows.json")           # endpoints + parsed config
CPP = os.path.join(DUMP_DIR, "cpp_contracts.json")        # customer pricing contracts
SW_MET = os.path.join(DUMP_DIR, "sw_metering.json")       # SW metering contracts
USAGE_HIST = os.path.join(DUMP_DIR, "usage_hist.json")    # cost histogram per endpoint

CREDIT_PRICE_USD = 0.10  # SimilarWeb: provider $0.075/credit x 1.333 customer mult.

PROV = {51: "twitter", 58: "tavily", 63: "firecrawl", 65: "coingecko",
        67: "agentmail", 74: "apollo", 80: "similarweb", 81: "exa",
        84: "edinet", 87: "oxylabs", 88: "ahrefs", 89: "semrush"}


def gw(inner):
    for p in ("/apis/v1", "/apis/v2"):
        if inner.startswith(p):
            return inner[len(p):]
    return inner


def load_json(p):
    with open(p) as fh:
        return json.load(fh)


# ── SimilarWeb credit model from the metering cost_contract ───────────────
def sw_credit_model(cc):
    """Return (credit_rate_str, credit_formula, cost_drivers, example, tier_hint).

    Derived purely from integration_metering_profile_revisions.cost_contract:
      response_count: credits = ceil(rows * units_per_count / unit_scale),
                      capped at maximum_units  → per-row rate.
      plan_units:     fixed_units → fixed credits; or
                      credits = input_multiplier * product(inputs)
                      (inputs in {metrics, periods}).
    """
    kind = cc.get("kind")
    if kind == "response_count":
        # credits = ceil(rows * units_per_count / unit_scale); maximum_units
        # caps the ROW COUNT (config_cost.go: count > MaximumUnits -> reject),
        # NOT the credit total. So the worst-case charge = ceil(rate * mx).
        upc = cc.get("units_per_count", 1) or 1
        scale = cc.get("unit_scale", 1) or 1
        rate = upc / scale
        mx = cc.get("maximum_units")
        rate_str = _fmt_rate(rate)
        formula = (f"credits = ceil({rate_str} x rows)"
                   + (f"; rows capped at {mx}" if mx else ""))
        drivers = [{"param": "limit",
                    "effect": (f"charge scales with rows returned at {rate_str} "
                               f"credit/row" + (f"; at most {mx} rows are billed" if mx else ""))}]
        # representative call: full page (default/cap 20 rows, or the cap).
        rows_full = mx if mx else 20
        cr_full = _ceil(rate * rows_full)
        cr_5 = _ceil(rate * 5)
        example = (f"{rows_full} rows = {cr_full} credit{'s' if cr_full != 1 else ''} "
                   f"(${cr_full * CREDIT_PRICE_USD:.2f}); "
                   f"limit=5 = {cr_5} credit{'s' if cr_5 != 1 else ''} "
                   f"(${cr_5 * CREDIT_PRICE_USD:.2f})")
        return (rate_str + " / row" + (f" (max {mx} rows)" if mx else ""),
                formula, drivers, example, cr_full * CREDIT_PRICE_USD)
    if kind == "plan_units":
        pu = cc.get("plan_units", {})
        if "fixed_units" in pu:
            f = pu["fixed_units"]
            return (f"{f} credits (fixed)",
                    f"credits = {f} (fixed per request)",
                    [{"param": "(none)", "effect": "flat per-request credit charge"}],
                    f"1 request = {f} credits (${f * CREDIT_PRICE_USD:.2f})",
                    f * CREDIT_PRICE_USD)
        inputs = pu.get("inputs") or ([pu["input"]] if pu.get("input") else [])
        mult = pu.get("input_multiplier", 1)
        # build a human unit like "metric x month" / "month"
        unit = " x ".join("month" if i == "periods" else i.rstrip("s") for i in inputs)
        rate_str = (f"{mult} credit" if mult == 1 else f"{mult} credits") + f" / ({unit})"
        formula = f"credits = {mult} x " + " x ".join(inputs)
        drivers = [{"param": i,
                    "effect": ("number of months in the date window"
                               if i == "periods" else
                               "number of metrics requested")}
                   for i in inputs]
        # representative: 1 of each input
        cr = mult
        example = (f"minimal ({' + '.join('1 ' + ('month' if i=='periods' else i.rstrip('s')) for i in inputs)})"
                   f" = {cr} credit{'s' if cr != 1 else ''} (${cr * CREDIT_PRICE_USD:.2f}); "
                   f"cost grows with " + " and ".join(inputs) + ".")
        return rate_str, formula, drivers, example, cr * CREDIT_PRICE_USD
    return None, None, None, None, None


def _fmt_rate(r):
    if r == int(r):
        return str(int(r))
    return ("%g" % r)


def _ceil(x):
    import math
    return int(math.ceil(x - 1e-9))


def cost_tier(usd):
    if usd is None:
        return "variable"
    if usd <= 0.01:
        return "low"
    if usd <= 1.00:
        return "med"
    return "high"


# ── Dynamic cost-driver hint per provider ────────────────────────────────
DYNAMIC_DRIVER = {
    "twitter": {"param": "result count",
                "effect": "charge scales with number of tweets/users returned"},
    "semrush": {"param": "display_limit (rows)",
                "effect": "charge scales with number of rows returned (up to display_limit)"},
    "firecrawl": {"param": "pages/results scraped",
                  "effect": "charge scales with number of pages/results the provider returns"},
    "exa": {"param": "numResults / contents",
            "effect": "charge scales with number of results and content pulls returned"},
    "tavily": {"param": "results / pages",
               "effect": "charge scales with number of results (search) or pages (crawl/extract) returned"},
    "apollo": {"param": "records returned",
               "effect": "charge scales with number of records enriched/returned"},
}


# Contract-fixed endpoints that carry a documented reduced-unit floor. Ahrefs
# domain-rating bills $0.08 normally but a reduced ~$0.02 for self / already
# verified-domain lookups (confirmed in usage_logs: 20000 vs 80000 micros).
FIXED_NOTE = {
    "/ahrefs/site-explorer/domain-rating": (
        "self / already-verified-domain lookups bill ~$0.02 (reduced-unit floor); "
        "$0.08 otherwise"
    ),
}


def build():
    eprows = load_json(EPROWS)
    cpp = load_json(CPP)
    swmet = load_json(SW_MET)
    usage = load_json(USAGE_HIST) if os.path.exists(USAGE_HIST) else []

    cidx = {}
    for c in cpp:
        cidx[(c["pricing_profile_key"], c["revision"])] = json.loads(c["contract_json"])
    midx = {}
    for m in swmet:
        midx[(m["profile_key"], m["revision"])] = json.loads(m["contract_json"])

    # usage histogram -> per gateway-path {floor,p50,p95,max,distinct}
    hist = {}
    for r in usage:
        hist.setdefault(r["gw"], []).append((int(r["c"]), int(r["freq"])))
    ustats = {}
    for g, pairs in hist.items():
        pairs.sort()
        total = sum(f for _, f in pairs)
        vals = [c for c, _ in pairs]
        # expand percentiles from the frequency table
        def pct(p):
            target = p * total
            acc = 0
            for c, f in pairs:
                acc += f
                if acc >= target:
                    return c
            return pairs[-1][0]
        ustats[g] = {
            "min": vals[0] / 1e6, "max": vals[-1] / 1e6,
            "p50": pct(0.50) / 1e6, "p95": pct(0.95) / 1e6,
            "distinct": len(vals), "n": total,
        }

    prices = {}
    for x in eprows:
        pid = x["pid"]
        g = gw(x["inner"])
        pj = x.get("pricing_json")
        if isinstance(pj, str) and pj:
            pj = json.loads(pj)
        pj = pj or {}
        floor = pj.get("normal")

        # firecrawl metered_result endpoints (crawl/batch-scrape): dynamic by
        # provider-reported unit cost; no customer multiplier contract.
        cbm = x.get("cbm")
        cj = cidx.get((x.get("cpp"), x.get("cpr")))
        kind = cj["kind"] if cj else (cbm or None)

        if pid == 80:  # SimilarWeb -> per_credit from metering contract
            m = midx.get((x["pk"], x["pr"]))
            if not m:
                continue
            cc = m.get("cost_contract", {})
            rate_str, formula, drivers, example, typ_usd = sw_credit_model(cc)
            if rate_str is None:
                continue
            prices[g] = {
                "kind": "credit_based",
                "customer_pricing_kind": cj["kind"] if cj else "provider_cost_multiplier",
                "metering_kind": cc.get("kind"),
                "credit_rate": rate_str,
                "credit_formula": formula,
                "cost_drivers": drivers,
                "example": example,
                "cost_tier": cost_tier(typ_usd),
                "contract_source": f"integration_metering_profile_revisions {x['pk']} rev{x['pr']}",
            }
            continue

        if kind == "fixed_success":
            tier = cj["tiers"]["normal"] / 1e6
            e = {
                "kind": "fixed_success",
                "customer_pricing_kind": "fixed_success",
                "price_usd": tier,
                "cost_tier": cost_tier(tier),
                "contract_source": f"integration_customer_pricing_profile_revisions {x['cpp']} rev{x['cpr']} (tier normal={cj['tiers']['normal']} micros)",
            }
            note = FIXED_NOTE.get(g)
            if note:
                e["note"] = note
            prices[g] = e
            continue

        if kind == "provider_cost_multiplier":
            mult = cj["tiers"]["normal"] / 1e6
            entry = {
                "kind": "provider_cost_multiplier",
                "customer_pricing_kind": "provider_cost_multiplier",
                "multiplier": round(mult, 6),
                "floor_usd": floor,
                "cost_drivers": [DYNAMIC_DRIVER.get(PROV.get(pid, ""),
                                 {"param": "response size",
                                  "effect": "charge scales with provider response size"})],
                "contract_source": f"integration_customer_pricing_profile_revisions {x['cpp']} rev{x['cpr']} (multiplier={cj['tiers']['normal']}/1e6); floor from pricing_json.normal",
            }
            u = ustats.get(g)
            if u and u["n"] >= 20:
                entry["typical_usd"] = {"p50": u["p50"], "p95": u["p95"]}
                entry["max_observed_usd"] = u["max"]
                entry["min_observed_usd"] = u["min"]
                entry["usage_n"] = u["n"]
                if floor is None:
                    entry["floor_usd"] = u["min"]
            prices[g] = entry
            continue

        if cbm == "metered_result":  # firecrawl crawl / batch-scrape
            entry = {
                "kind": "provider_cost_multiplier",
                "customer_pricing_kind": "metered_result",
                "multiplier": None,
                "floor_usd": floor,
                "cost_drivers": [{"param": "pages/results returned",
                                  "effect": "charge scales with provider-reported units (pages/results); metered_result billing"}],
                "contract_source": f"integration_api_endpoints.config_json (customer_billing_mode=metered_result, provider_unit_cost); floor from pricing_json.normal",
            }
            u = ustats.get(g)
            if u and u["n"] >= 20:
                entry["typical_usd"] = {"p50": u["p50"], "p95": u["p95"]}
                entry["max_observed_usd"] = u["max"]
                entry["min_observed_usd"] = u["min"]
                entry["usage_n"] = u["n"]
                if floor is None:
                    entry["floor_usd"] = u["min"]
            prices[g] = entry
            continue

        # otherwise: no resolvable contract -> record floor only if present.
        if floor is not None:
            prices[g] = {
                "kind": "fixed_success",
                "customer_pricing_kind": kind or "unknown",
                "price_usd": floor,
                "cost_tier": cost_tier(floor),
                "contract_source": "pricing_json.normal (no customer-pricing contract row resolved)",
            }

    out = {
        "_note": (
            "CONTRACT-SOURCED price map for AIsa data-API operations. Keyed by "
            "provider-relative gateway path (endpoint inner_uri minus /apis/v1|v2). "
            "Re-derived from DB ground truth: customer pricing contracts "
            "(fixed_success | provider_cost_multiplier) + SimilarWeb metering "
            "contracts (credit rates) + usage_logs (real cost distribution for "
            "dynamic endpoints). This REPLACES the earlier /info/apis catalog "
            "snapshot, whose scalars were static floors for dynamic endpoints and "
            "carried wrong SimilarWeb credit rates. Prices in USD."
        ),
        "_source": "MySQL DB 34: integration_api_endpoints + integration_customer_pricing_profile_revisions + integration_metering_profile_revisions + usage_logs",
        "_generated_at": datetime.now(timezone.utc).isoformat(),
        "_credit_price_usd": CREDIT_PRICE_USD,
        "_entry_count": len(prices),
        "prices": dict(sorted(prices.items())),
    }
    with open(PRICING_MAP_PATH, "w") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"Wrote {PRICING_MAP_PATH}: {len(prices)} entries")


if __name__ == "__main__":
    build()
