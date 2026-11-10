# Pricing unit semantics audit, 2026-11-10 (AIS-484)

The shared pricing renderer presented an internal cost conversion rate as
`Declared unit rate: $0.000001 USD per provider_credit`. For Amazon category
products this is a micro-USD conversion, not a product count or a request price.
The correction separates a declared fixed customer price from supplier cost
accounting. Generic supplier units are never advertised as a customer unit price.
The matching runtime tariff proposal is tracked in AIS-484; this renderer does
not change pricing configuration or turn an estimate into a fixed tariff.

## Inventory and scope

Audit base: Docs main `1a9abc583837db1e77c7832b26806d83d3ab7e30`.
The consolidated reference `openapi/openapi.json` has SHA-256
`4345931039fe9ba7835c981b59fd994155daa71a962853229589f99cddf4e`.
Count each method/path once in that file. Do not add the provider shards or
Chinese mirrors to the operation count.

| Population | Operations |
| --- | ---: |
| All reference operations | 6,446 |
| Generic `provider_credit` rate presented as a unit price | 3,707 |
| Same `$0.000001 / provider_credit` wording as the reported example | 1,377 |
| Of those, evidence in response headers | 722 |
| Of those, evidence in response bodies | 655 |
| Other named unit rates (including real business credits) | 42 |

The 1,377 exact matches span 107 catalog IDs and are enabled in this snapshot.
The literal wording also occurs in 1,377 English and 1,377 Chinese MDX pages:
2,754 pages in total. This is a documentation inventory, not a finding of 1,377
incorrect charges. An evidence location does not by itself identify a provider
or establish that its unit is money.

The wider 3,707-operation generic-unit population has these declared rates:

| Rate in USD | Operations |
| --- | ---: |
| 0.000001 | 1,377 |
| 0.0001 | 2,063 |
| 0.014 | 232 |
| 0 | 34 |
| 0.00001 | 1 |

Those other rates are not classified as erroneous. In particular, zero upstream
cost does not imply a zero customer price. The public reference contains real
named units such as `similarweb_credit`, `tavily_credit` and `firecrawl_credit`.
Their rates remain visible for variable pricing; a declared fixed customer price
does not show supplier rate arithmetic in its public price prose.

Reproduce the inventory without network or database access:

```sh
python scripts/audit_pricing_unit_prose.py --inventory /tmp/ais484-inventory.json
```

This counts the current reference mirrors in the repository, not every deployed
consumer. The fetched public [Amazon definition](https://aisa.one/docs/openapi/amazon.json)
matched the repository's Amazon JSON. The separate public root `openapi.yaml`
contained 2,011 operations and none of these micro-rate entries when checked;
it is not interchangeable with the full reference inventory. No production
database query or paid API execution was performed.

## Rendering change

For a declared fixed customer tariff, the customer-facing summary is:

> Published reference price: $0.01476 USD per successful request. Account-specific pricing and final settlement may differ.

> 公开参考价格：每次成功请求 $0.01476 USD。 最终费用以账户适用价格及实际结算为准。

Its readable price block omits the internal multiplier, supplier unit/rate,
cost contract, receipt source and supplier request-estimation formulas. The
complete machine-readable declaration remains unchanged. Request constraints
and a supported account quote remain available.

The inspected [Amazon category products](https://aisa.one/docs/api-reference/amazon/amazon-get-category-products-v1)
declaration still says `provider_cost_multiplier`. Until its runtime price
binding is promoted and republished, this renderer must accurately show:

> Default request estimate: $0.01476 USD (not a fixed price). Billed from provider cost multiplied by the applicable customer multiplier. Account-specific pricing and final settlement may differ.

> 默认请求预估费用：$0.01476 USD（不是固定价格）。 按上游成本乘以适用的用户倍率计费。 最终费用以账户适用价格及实际结算为准。

For variable-price declarations, the body retains `unit_rate_usd=0.000001` and `unit=provider_credit` under
**Cost conversion details**, explaining that these parameters alone do not
state a customer price per request or result. The complete JSON declaration is
unchanged. Generic units move out of the short price summary at every numeric
rate; no currency, result-count or fixed-success semantics are inferred.

The `provider_cost_multiplier` customer pricing declaration now controls the
customer-facing explanation instead of the technical `response_units` cost
contract implying a business usage meter. Named credit rates remain in the
summary, explicitly labelled **Provider cost rate** when this pricing mode is
declared. Existing fixed-supplier summaries are preserved: a deterministic
supplier tariff times a constant customer-tier multiplier can also yield a
fixed price. This change does not reclassify those operations without further
runtime evidence. Free, unavailable and event branches retain their meaning.
Estimates are not multiplied a second time.

For this particular Treg route, the upstream
[cost-header contract](https://treg.to/integrate.md) explains the micro-USD
conversion: `X-Treg-Cost-Micro: 14760` means `14760 * 0.000001 = 0.01476 USD`.
That interpretation is not applied to other operations based merely on their
rate or generic unit label. Adding precise provider-specific billing semantics
to a generic summary requires an explicit declaration from the source contract.

## Validation and publication

Seven regression tests cover the reported wording and the fixed-price behavior.
They cover English/Chinese summaries, readable MDX, OpenAPI descriptions and
the sales projection; generic units at several rates; actual named credits,
including one priced at 0.000001; a non-1 customer multiplier; fixed customer
prices with zero cost; metadata preservation and idempotent regeneration.
The fixed-price case first failed against the original renderer because fixed
tariffs leaked supplier arithmetic. A separate regression preserves existing
fixed-supplier summaries even when the customer tariff uses a constant multiplier.

An offline projection of all 6,446 operations changes 4,377 summaries, including
the clearer explanation of provider-cost pricing. It removes all 3,707 ambiguous
generic-unit price summaries and preserves every non-description operation
field. English/Chinese Amazon pages were regenerated in scratch files and
verified idempotent. A separate scratch preview uses the proposed fixed tariff;
it is not evidence of a live price change. This is a renderer check, not
publication acceptance.

Validation completed with Python 3.12:

- Full `scripts/tests` suite: 1,180 tests, passed, 3 skipped. The initial shallow
  clone lacked historical objects used by 14 existing tests; fetching repository
  history resolved those errors without changing tests or acceptance inputs.
- Pricing regression tests and 14 readable-contract tests: passed.
- Payment discovery check, frozen W0 integrity and 11 W3 policy tests: passed.
- Frozen full-catalog composition with pages and idempotent replay: passed.
- Navigation, generated API slugs and production reference-page checks: passed.

The frozen diagnostic still reports its existing content gaps and failed formal
readiness; passing the offline code checks does not waive those publication gates.

This PR changes generators, tests and audit documentation. It does not hand-edit
generated mirrors, change Runtime accounting, or manufacture publication review
receipts. After merge, the existing `pull-openapi` workflow includes generator
changes in its input hash and regenerates the mirrors through the normal gates.
The website and formal exports are only updated after that publication succeeds.
