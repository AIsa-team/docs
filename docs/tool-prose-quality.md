# Tool prose: source ownership and delivery

## Architecture correction

AIsaServices #1288 is being refactored to maintain prose at its owning source.
The former central runtime amendment catalog and its generator-time replacement
logic have been removed. This repository's amendment-generation script and exact
billing-replacement table have also been removed. Neither is a publication input.

The existing `tool-prose-coverage-20261112.csv` and adjacent JSON retain the
reviewed before/after wording proposals for 6,468 public operations. They are
**audit records, not proof that all proposed text is in the maintained source or
published**. The historical `runtime_entries` count of 5,605 refers to the removed
amendment catalog. Do not report it as delivered source changes.

## Maintained sources

- Static Docs: `openapi/upstream/*.json`, the existing reviewed static source
  metadata, and the standalone Gemini source. Changes remain in those files.
  The exact amendment record identifies 2,156 static operations in 44 source
  files plus 138 nested or introductory text fields. These counts overlap with
  the operation inventory; they must not be added together.
- Dynamic code-defined APIs: AIsaServices' Social, Commerce, Ads and Connector
  definitions and the async lifecycle generator. Docs consumes their normal
  generated Runtime contracts.
- Gateway catalog APIs: AIsaServices' existing reviewed import inventory owns
  names and descriptions. Its normal generator emits the existing catalog;
  the existing insert-only import persists descriptions for newly created rows.
- Existing database-defined APIs: `IntegrationAPIEndpoint.Name` and
  `Description` are authoritative. A repository edit does not update these
  records. An exact current-row export is required to prepare and review
  guarded database changes. These updates are not yet applied.
- Provider display titles: existing vendor definitions or provider database
  fields. A display-title edit must not rename a route or operation ID.

After source changes are applied, use the normal Runtime publication and Docs
composition chain. There is no Docs-side override for dynamic API prose.

## Editorial policy and regression evidence

API summary/description explanations, including parameter and response prose,
are English. Preserve the separate `zh` site and Chinese wire enum values,
response keys and necessary literal examples. Language tests explicitly
recognize those protocol literals; they do not translate them.

Unverified upstream per-record credits, rates, free-failure and refund promises
have been removed from the reviewed wording and static sources. Preserve usage
counters, HTTP semantics, limits and inputs; refer to applicable AIsa pricing
and request quotes. Verified native contract-owned charging semantics are not
supplier advertisements and remain intact.

The static history tests reverse only declared summary/description edits and
compare the original full document, preserving paths, IDs, schemas, examples,
prices and source provenance. The editorial tests inspect the actual static
sources as well as the explicitly labeled historical wording proposals.

Twelve historical proposals remain bounded to their declared purpose because
additional input/output evidence is unavailable. The evidence record in
`scripts/data/tool-prose-purpose-evidence.json` is audit-only, not runtime code.

Polymarket v1 migration remains excluded. Its independent source-maintenance
readiness failure must be reported separately, not bypassed or relabeled green.
