# Customer pricing generator (AIS-484), updated 2026-11-11

The generated price block must tell customers what they pay, without teaching
supplier-cost conversion or asking them to multiply internal factors. A fixed
customer tariff and a supplier reservation estimate are different authorities.
This PR changes the shared generator, not production pricing or generated pages.

## Rendering contract

`customer_price_presentation.py` classifies the existing published declaration.
`pricing_prose.py` uses it for OpenAPI summaries; `readable_contract_notes.py`
uses it for English and Chinese page blocks. Localization and sales projection
therefore receive the same price meaning.

| Declaration | Customer display |
| --- | --- |
| Explicit customer fixed-success | Published amount per successful request |
| Fixed-request customer micro-USD | Converted customer amount per success |
| Resource delivered read | Normal-tier amount per delivered read; entity/page unit definition; no-delivery rule; computed stored-result amount |
| Price variants | Each option's price; disabled options unavailable |
| Configured fixed async job | Published amount per completed job |
| Request formula/plan units/supplier fixed snapshot | Request-dependent reference estimate; no claim that an estimator is a fixed tariff |
| Response count | Actual billable results and reference request estimate |
| Response components/SKUs | Combined measured usage and reference request estimate |
| Response money/units | Reference request estimate and actual-usage settlement |
| Async metered result | Explicit customer unit price even when the total depends on the request |
| Successful event | Published per-target amounts, draft/failure and charge-refusal conditions |
| Model catalog | Model/options and request/token/second semantics; no invented model price |
| No customer charge | No additional charge for this operation |
| Historical disabled archive | Disabled, cannot be called, and no price is published; retained only for reference |
| Unknown pricing kind/cost rule | Billing method unavailable; any published request estimate stays an estimate without an inferred settlement rule |

Existing customer reference estimates and unit amounts are never multiplied a
second time. Supplier `unit_rate_usd`, including named credits, is not a customer
unit tariff. Missing business-unit meaning is not inferred from response-array
lengths. The generic unit wording on an async tariff remains "billable unit"
where Runtime does not publish a more specific customer unit.

Resource cache amounts use the integer customer price and declared basis-point
share, rounded upward to micro-USD as Runtime does. A share of zero publishes no cache-hit
price and disables store reuse, so no stored-result offer is shown. These are normal-tier reference amounts, not a guarantee for
all account plans. Social's declared 15-minute/6-hour free cache windows and
failure/unknown waivers remain visible; those conditions are not invented for
other operations. Social event amounts come from the current declaration, not
hard-coded constants. Changed or unrecognized event descriptions are preserved
as escaped text rather than silently reusing stale prices. Recognizing an event
price clause does not discard the rest of the declaration. If a publication
target's charge is refused for insufficient balance or the request's maximum
price, only that target fails while other targets continue publishing. Resource
prices retain their unit definition: an entity with at least one requested field,
or one page of a result set.

## Amazon example

The inspected declaration for `GET /apis/v1/amazon/get-category-products-v1`
has a customer reference estimate of $0.01476 and uses receipt-based settlement.
Its $0.000001 supplier unit rate does not price a returned product.

English generated summary:

> Usage-based pricing. Default request estimate: $0.01476 USD. The final charge depends on actual usage. Your account price may differ; use a request quote where supported.

Chinese generated summary:

> 按实际用量收费。默认请求预估费用：$0.01476 USD。最终费用以实际用量为准。账户适用价格可能不同；支持报价的接口可按实际请求获取报价。

An explicit fixed customer binding instead produces "$0.01476 USD per successful
request". This PR does not activate that alternative or depend on changing the
Amazon binding to improve the current wording.

## Public data and regeneration

The managed page block omits supplier rates, multipliers, receipt sources,
reservation formulas and raw pricing from the embedded Request contract.
Authentication, request parameters, schema closure and request constraints stay
visible. Complete machine-readable OpenAPI and sales-catalog pricing metadata
remain unchanged for existing consumers; this PR does not claim to remove those
public fields from the machine API.

Composer version 29 forces regeneration when source facts are unchanged. Old
price blocks are replaced, and later price updates replace prior amounts. Tests
exercise the actual facts-stage entrypoint and canonical page projection;
canonical native/aggregate bytes remain byte-identical to their producer input.
The canonical consumer cannot repair an older producer's OpenAPI summary by
rewriting authenticated bytes. Services must separately pin the merged Composer
code and source-manifest hash before publishing artifacts with these summaries.
No Services lock, schema-input pin, source review clock, generated mirror,
publication receipt, production price, SQL or paid endpoint is changed here.

## Review and validation

The originating requirement is the user's 2026-11-11 instruction: classify the
billing rules in the common generator, show customer prices without internal
calculation logic, create/update a PR only, and do not merge main.

On the checked-in 6,446-operation reference graph, the offline projection changes
6,436 descriptions. Both languages were scanned for supplier conversion/multiplier
copy; original `x-aisa-pricing` values are preserved and a second clean pass is
identical. This is a repository reference inventory, not a new production price
or settlement audit. The separate Runtime audit counted 6,409 operations because
Runtime ANY operations and Docs concrete-method expansion use different scopes.

Focused tests cover every rule family, invalid/zero amounts, exact decimal and
large-integer formatting, cache rounding, disabled variants, event price changes,
model units, unchanged raw metadata, safe MDX, price updates, stale-block
replacement and facts/canonical regeneration. Run:

```sh
PYTHONPATH=scripts/tests python -m unittest \
  scripts.tests.test_customer_price_presentation \
  scripts.tests.test_pricing_unit_semantics \
  scripts.tests.test_pricing_prose \
  scripts.tests.test_readable_contract_notes \
  scripts.tests.test_unified_surfaces
python -m unittest discover -s scripts/tests -v
```

The existing frozen-catalog, payment-discovery and publication checks remain
required. Passing generator tests does not mean the changes are merged,
deployed, or already visible on the website.
