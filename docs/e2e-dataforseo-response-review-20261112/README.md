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
on subsequent acquisitions; the reviewed source mirror contains the fix now.

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

Google Organic has additional upstream result-contract defects: a closed base
schema conflicts with derived result fields, and nullable properties with a
non-nullable referenced oneOf branch still reject null. These remain failures,
tracked in [AIS-560](https://linear.app/aisateam/issue/AIS-560). This PR does not
relax those result contracts or claim every historical echo failure is resolved.

Per-operation input, response and billing evidence is preserved in
[Services #1234](https://github.com/AIsa-team/AIsaServices/pull/1234), under
`scripts/api-e2e/evidence/2026-11-13-dataforseo-recheck/`. This is candidate replay
against fresh live responses, not a deployment receipt. The live Action remains
red against the still-published contract; post-publication regression is pending.

Validation:

```sh
python -m unittest discover -s scripts/tests -p 'test_dataforseo_response_echo.py' -v
python -m unittest discover -s scripts/tests -p 'test_provider_request_example_quality.py' -v
```
