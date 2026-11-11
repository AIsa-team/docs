# Customer pricing on dev API pages

This change targets `dev`, following the production rollback. Review it in a PR
whose base is `dev`. It does not change service billing, upstream prices, the
production publisher, or `main`. Generated preview output is not a deployment.

## Presentation contract

Use one pricing paragraph in the existing **Cost and request rules** section
(and its Chinese counterpart). Keep the operation and frontmatter descriptions
about the API's purpose. Remove obsolete generated price summaries and HTML
pricing markers from those descriptions. Free and unpublished prices are plain
text, not placeholders.

The generator resolves these families from the published Runtime declaration:

| Declaration | Customer presentation |
| --- | --- |
| Explicit customer fixed-success price | USD per successful request |
| Configured fixed-price async job | USD per completed job |
| Resource delivered read | USD per delivered read; entity/page definition, empty reads free, stored-result price when offered |
| Request formula or planned units | Default request estimate; no arithmetic for the reader |
| Result count | Actual billable results and the available request estimate |
| Components or SKU | Combined billable component usage and the available estimate |
| Response usage | Actual usage and the available request estimate |
| Async with explicit customer unit price | USD per billable unit, settled when the job completes |
| Social events | Published target prices and failure, refusal, pending and once-only settlement conditions |
| Model catalog | Declared model/options/token/time dimensions; never invent a model price |
| No customer charge | No additional charge for this operation |
| Unpriced historical operation | Historical archive: disabled, cannot be called, and no price is published |
| Unknown rule | Billing method unavailable; do not infer usage billing or disable an operation |

Customer totals and unit prices are already priced by Runtime. Do not apply a
multiplier again. A fixed supplier cost alone is not a fixed customer tariff.
Only an explicit customer price can be presented as a tariff. Missing,
unavailable, invalid and zero prices must remain distinct.

Keep machine-readable pricing metadata intact in the OpenAPI contract, but
exclude it from the page's expanded request declaration and explanatory prose.
Do not show supplier rates, provider credits, customer multipliers, reservation
formulas or micro-USD conversion instructions in API-page pricing. Preserve
request fields, authentication, constraints and examples.

## Adyntel regression

The public dev declaration for Google Ads Transparency has a response-usage
cost contract and an unavailable request estimate. Its `$0.000001` supplier
unit rate is not a customer request price. The page must say usage-based pricing
with no currently available estimate, without displaying that supplier amount
or unit. It must not fabricate a fixed price.

The regression test exercises the actual `sync_dev_runtime.acquire` and
`generate` path with a frozen declaration, checks English and Chinese pages,
and regenerates them to verify that the old summary cannot return. Family
regressions also cover monetary rounding, zero/missing amounts, Social
conditions and unchanged machine metadata.

## Generation and publication

The dev workflow forces generation when generator scripts change. The Composer
version changes so a same-facts regeneration also refreshes presentation.
Subsequent runs must be idempotent. A dev PR is reviewed before merging; the
existing dev generator and separate Mintlify project publish after that merge.
An Actions check alone is not evidence that the dev site has deployed.

Run the offline checks documented in [dev deployment](dev-deployment.md).
For the focused regressions:

```sh
PYTHONPATH=scripts/tests python -m unittest \
  scripts.tests.test_customer_price_presentation \
  scripts.tests.test_dev_customer_pricing \
  scripts.tests.test_pricing_prose \
  scripts.tests.test_readable_contract_notes \
  scripts.tests.test_unified_surfaces -v
```
