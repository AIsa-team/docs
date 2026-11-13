# DataForSEO echoed request values

E2E found successful HTTP responses rejected by the published response schema at
`tasks[].data.additionalProperties`: string, number and array values were declared
as nullable objects. This field echoes request parameters; it does not contain a
homogeneous map of objects.

The evidence distinguishes three possible causes:

- References resolve successfully. The validator reaches the concrete shared
  `BaseResponseTaskInfo.data` property and reports a type mismatch.
- The immutable upstream OpenAPI revision `702356d7be30374c95c4353c32345c61c6d7c1df`
  already contains the restrictive placeholder. Its SHA-256 matches the previous
  October acquisition evidence, so this is not evidence of a new live protocol change.
- The AIsa source mirror preserves that upstream declaration. The official
  [anchors/live example](https://docs.dataforseo.com/v3/backlinks/anchors/live/)
  contains strings, an integer and arrays in `data`, agreeing with observed types.
  The upstream schema itself is inconsistent with its documented response.

The correction permits arbitrary JSON values only inside the existing nullable
object `BaseResponseTaskInfo.data`. Requests, typed result schemas and other
response constraints remain intact. A strict signature guard avoids overwriting
future structured upstream definitions. The importer applies the same correction
on subsequent acquisitions. The reviewed mirror itself changes in a separate
source-input PR (see "Change split" below).

Offline replay of the complete official anchors response fails before this change
and passes after it. Regression tests also reject a scalar/array `data` envelope,
reject an invalid status type, preserve unrelated response schemas, and check
idempotence and future upstream constraints. See `evidence.json` for source hashes.

This is a source correction for review, not a publication receipt. Existing
source pin policy, Runtime input selection, independent baseline checks and formal
publication gates remain required. Historical E2E failures are not rewritten as
passes. Other observed discrepancies, including null `tasks` and task item schemas,
are separate findings and are not covered by this fix.

## Scoped live regression, 2026-11-13

[Services Action 43443440911](https://github.com/AIsa-team/AIsaServices/actions/runs/43443440911)
repeated three previously failing requests with explicit, official-example inputs.
The requests passed request-schema validation before dispatch. All three returned
successful task statuses, correct request echoes and nonempty results. Response
cost times the published 1.0 multiplier, settlement headers and read-only ledger
rows agreed per request; both wallet batches reconciled and quotes debited zero.
Total settled cost was USD 0.052156.

The same captured responses were replayed against the published contract and a
candidate made by this repository's composer from the captured Runtime facts and
the source correction at `fd069ba31a95970594e517b2d06bc80a450bc873`:

| Operation | Published | Candidate | Settled USD |
| --- | --- | --- | --- |
| backlinks/anchors/live | FAIL | PASS | 0.024036 |
| dataforseo_labs/google/keyword_overview/live | FAIL | PASS | 0.024120 |
| serp/google/organic/live/advanced | FAIL | FAIL | 0.004000 |

The first two complete live response bodies are regression fixtures under
`scripts/tests/fixtures/dataforseo-live-20261113/`. They fail with the original
echo restriction and pass with this source correction. Negative controls still
reject an array-valued task data envelope and a string-valued task cost.

Google Organic exposed two further upstream result-contract defects, tracked in
[AIS-560](https://linear.app/aisateam/issue/AIS-560) and corrected below. This
change does not claim every historical DataForSEO failure is resolved.

Per-operation input, response and billing evidence is preserved in
[Services #1234](https://github.com/AIsa-team/AIsaServices/pull/1234), under
`scripts/api-e2e/evidence/2026-11-13-dataforseo-recheck/`. This is candidate replay
against fresh live responses, not a deployment receipt. The live Action remains
red against the still-published contract; post-publication regression is pending.

## Google Organic result contract (AIS-560), 2026-11-14

The same captured Organic response still failed after the echo correction. It
was minimized to exactly two upstream declaration patterns, both present in the
pinned revision `702356d7` and unchanged in the latest upstream `8f328672`
(2026-11-13), so this is not a recent protocol change:

1. **Closed polymorphic bases.** 33 item bases (`BaseSerpApiElementItem`, Labs,
   Merchant, Knowledge Graph, ...) declare `additionalProperties: false`. These
   are the only closed schemas in the whole source. 251 subtypes extend them through
   `allOf`, and 86 response use sites reference only the base, with subtypes listed
   solely in `discriminator.mapping`. In JSON Schema the closed base rejects every
   subtype field (`rank_group`, `domain`, nested `items`, ...), and an `items`
   that references only the base never validates subtype fields at all.
2. **Nullable references.** `{type: object, nullable: true, oneOf: [{$ref: X}]}`
   rejects `null` when `X` is an object: OpenAPI 3.0.3 limits `nullable` to the
   same object's `type`, so the composer's 3.0 to 3.1 conversion is correct and the
   source declaration is what's wrong. DataForSEO documents these fields as nullable
   (`refinement_chips`, `rectangle` unless `calculate_rectangles` is set,
   `about_this_result`, `faq`, `price`, nested `items`).

The importer (`import_dataforseo_filters.py@3`) corrects both, only in the
response graph (request and response component graphs are disjoint; request
schemas stay byte-identical), and only for the exact shapes above:

- open each closed base whose mapped subtypes all extend it through `allOf`;
- pin each subtype's mapped discriminator value (`enum`, `required`);
- rewrite each base-only use site as a `oneOf` of the mapped subtypes plus null,
  keeping the discriminator;
- add an explicit OpenAPI 3.0.3 null-only branch to a nullable single-reference
  wrapper whose target is an object. Untyped targets already admit null.

Field types, subtype selection, unknown or missing discriminator values, scalar
items and non-object values for nullable references stay rejected. Subtypes
remain as open as every other DataForSEO schema. Applying the rules to the pinned
upstream and to the reviewed mirror gives identical documents; both rules are
idempotent. On the reviewed source they open 32 bases, tag 248 subtypes, rewrite
86 use sites and add 3,113 null branches. The 33rd closed base is unreachable
from any operation. OpenAPI 3.0 validation of the mirror reports the same single
pre-existing duplicate `operationId` before and after.

The captured Organic response (`fixtures/.../organic-advanced.json`) fails on the
original source and passes after the correction, with negative controls. A
candidate composed from the corrected source and the captured Runtime facts
passes all three replayed operations (Anchors, Keyword Overview, Organic), with
business, price, ledger and wallet checks unchanged.

Known residual, not changed here: the official full Organic example returns
`product_considerations` `expanded_element` as an object (as the official field
table says), but the source declares an array. The live run contained no such
item; this is recorded on AIS-560 rather than fixed without live evidence.

## Change split

Docs CI admits a reviewed source-input change only when it contains mirrors,
schema-input receipts, review JSON and top-level tests, and no compiler code.
Therefore:

1. This change (code only): importer corrections, regression tests, fixtures and
   this evidence. It does not modify `openapi/upstream/dataforseo-official.json`.
2. Separate source-input PR, after this one merges: the mirror regenerated by these
   rules, its review JSON, `merged-source-reviews.json` and `docs/schema-inputs/`
   receipts, plus a replay test. Services then promotes the new Docs input bundle,
   and only after publication can the live E2E be rerun as a deployed regression.

Validation:

```sh
python -m unittest discover -s scripts/tests -p 'test_dataforseo_*.py' -v
python -m unittest discover -s scripts/tests -p 'test_provider_request_example_quality.py' -v
```
