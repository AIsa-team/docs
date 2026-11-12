# Main promotion of reviewed provider documentation

This candidate consolidates dev PRs #346, #347 and #350, including the required response-preservation changes from #337, #338 and #339. It starts from main `a95a9bef6b2f9e0290e05c2b9af955065ddaf3ea`. The verified dev output is `2b57134829af6817878989332d1141fc326396c5`.

The reviewed inputs cover 2,063 Alexandria operations and refresh four Firecrawl passthrough responses. The broader inventory and upstream review remain in `provider-contract-review.json`; the five production probes remain in `alexandria-live-schema-review.json`. These are reviewed static contracts, with the documented-fields-only boundary retained where the supplier does not guarantee presence or a complete response schema.

## Page generation

The production reference generator on main, `scripts/sync_prod_runtime_docs.py`, recomposed the full catalog from the public production facts in immutable release `f3dd779b1323726549ea86ac4a22d64f58c78c33f8bcf8c8010ff42e5d3c8d8b`, generation 13850. Every downloaded facts file was checked against its manifest SHA and ETag, with an unchanged fresh current pointer before and after. This is a facts-subset acquisition for page generation, not formal canonical-release acceptance.

Only pages matching the 2,067 reviewed route/method pairs and their referenced contracts were selected from the generator output: 4,134 English/Chinese pages and 704 reference-contract files. Their hashes are recorded in [the promotion evidence](main-promotion-review.json). Existing navigation includes every selected page. These reference files let the pages display the reviewed schemas without asserting that Runtime has adopted this candidate as its formal compiler/source authority.

The sole semantic difference from the verified dev output is `/apis/v1/people-data-labs/company/enrich`. Dev marked that catalog blocked and retained a historic Runtime handler contract. The main candidate uses the current production mixed Alexandria operation, profile `9d71cee78359`, which is also the route already present in main's formal document. It must not be replaced by dev's historic handler envelope. Both language comparisons are recorded explicitly in the evidence.

## Validation

- 1,204 unit tests passed, with one existing skip; 11 policy-fixture tests and frozen-package integrity passed.
- Frozen-catalog generation repeated with zero changed files. Its known content debt remains a diagnostic result, not publication approval.
- All 2,067 operation pairs were checked against the verified dev contracts in both languages. The sole historical-route difference is explained above; no unexplained differences or success-response placeholders remain in these page contracts.
- All 11 complete successful production payloads from the five earlier probes validate against the final English and Chinese composed response schemas: 22 checks. All five Runtime profile bindings still match current production. No new paid business requests were made for promotion.
- The 4,134 selected pages resolve to their intended operation; navigation and all 4,214 main reference-page definitions pass validation.

Formal publication readiness is assessed separately by the existing PR workflow against current Runtime authority. A page-generation check or the earlier dev deployment does not approve main publication. This PR is for review and must not be merged automatically.
