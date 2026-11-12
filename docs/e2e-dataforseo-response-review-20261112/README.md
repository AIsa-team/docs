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

Validation:

```sh
python -m unittest discover -s scripts/tests -p 'test_dataforseo_response_echo.py' -v
python -m unittest discover -s scripts/tests -p 'test_provider_request_example_quality.py' -v
```
