# DataForSEO publication unblock: implementation and validation

## Implemented

The official YAML importer preserves plain date-like scalars as JSON strings.
For example, the provider's `datetime_from: 2026-48-12` remains exactly
`"2026-48-12"`; the importer does not correct or certify the example. Explicit
`!!timestamp` tags remain unsupported. Duplicate keys, unsafe object tags,
ambiguous numbers, non-finite values and unsupported numeric precision still
fail closed. PyYAML's global loader is unchanged. The importer version is 3.

The DataForSEO mirror is imported from the actual official source and its
maintenance policy returns to automatic acquisition every 24 hours. A separate
fetch of immutable upstream revision
`702356d7be30374c95c4353c32345c61c6d7c1df` was parsed and compared with the fetched
master document; the declarations are identical. The receipt records the real
acquisition time, source content hash and maintenance policy hash. It does not
renew any other source's receipt.

`dataforseo-review.json` records source hashes, exact component changes and
operation-level comparison results. There is one added operation, six changed
operations, no removed operations and no uncertain comparisons. The six changes
include response type corrections/removal and removal of two optional fields
from both Google Local Finder requests. These are published provider declaration
changes, not a claim of live execution or backward compatibility.

The new POST `/v3/dataforseo_labs/google/historical_search_volume/live` has the
upstream array request body and complete reference closure. Upstream describes
required keywords and alternative location/language fields in prose but omits
machine-readable `required` constraints. This import preserves that limitation;
it does not invent request validation.

## Actual candidate verification

Inputs:

- Docs base: `a5602a2841afebc48da49471ddf80e9f417cf03b`.
- Existing reviewed debt baseline: `78ef376841ead8cde10a79651958790be5a0531c`.
- Runtime artifact: `ab2f7346cefe5658eceb70e9296e54a73aa022b866c0a3f199ed2ed4a6e17074`.
- Runtime compiler: `61f788ae67374a1a0d63281e9d1610f31494c0c6`.
- Runtime acquisition completed: `2026-10-15T14:00:21Z`.

The candidate was generated in a separate worktree with the existing full page
and localization pipeline. No generated graph was committed as a shortcut for
the formal publisher. No production mutation or paid provider request was made.

Results:

- 628 unit tests pass; three existing checks requiring the official FRED HTML cache
  or the JavaScript YAML dependency are skipped in this local environment.
- Stage readiness: passed, zero blocked providers. DataForSEO has no new pending
  request or response declarations.
- Repeating full generation against the same acquisition changes zero files.
- Aggregate: 2,007 operations and 1,966 paths.
- DataForSEO: 455 to 491 operations; 36 additions; 98 structured price changes.
- Duffel Flights: six structured price/estimate changes.
- Ahrefs Domain Rating: generated English description contains the Runtime
  `$0.08 USD per successful request` summary.
- Formal candidate readiness: passed, no global errors or missing inputs.
- Payment discovery remains its existing reviewed three-operation pilot and
  passes its current binding check; this is not the 109-operation expansion.

The local candidate uses committed receipts, not GitHub's newer acquisition
cache. Other automatic sources consequently have provider-scoped overdue
observations. Existing formal policy allows publication of the graph while
consumers suppress affected providers. DataForSEO is fresh. This local pass is
not evidence that all provider freshness budgets or online consumer convergence
have passed. The scheduled publisher restores its real acquisition cache before
assessment; release and consumer checks remain necessary after merge.

Reproduction (set `FACTS` to a complete immutable acquisition and use a clean
candidate worktree):

```sh
python -m unittest discover -s scripts/tests -v
python scripts/prepare_source_receipts.py \
  --reviewed docs/current-source-review-20261009/merged-source-reviews.json \
  --cache .cache/source-reviews.json
python scripts/pull_openapi.py --write --facts-dir "$FACTS" \
  --baseline-ref 78ef376841ead8cde10a79651958790be5a0531c \
  --readiness-report /tmp/stage-readiness.json
python scripts/runtime_consolidate_openapi.py --output openapi.yaml
python scripts/generate_payment_discovery.py
python scripts/check_contract_candidate.py --facts-dir "$FACTS" \
  --baseline-ref 78ef376841ead8cde10a79651958790be5a0531c \
  --published-ref a5602a2841afebc48da49471ddf80e9f417cf03b \
  --report /tmp/formal-readiness.json
```

## MPP expansion dependency

The existing multi-provider builder in `scripts/payment_catalog.py` already
supports reviewed GET/POST contracts, per-method Runtime capabilities, quote
revision matching, reference closure and observed unauthenticated 402 terms.
The default `generate_payment_discovery.py` / `candidate()` path still uses the
three-operation Polymarket evidence. Changing only that allowlist would bypass
its required evidence rather than unify publication.

AIsaServices main `61f788ae` contains 149 reviewed allowlist entries in
`packages/mppcatalog/allowlist.json`; schema/runtime eligibility reduces that
set. The live API catalog's 109 operations cannot substitute for the reviewed
production quote plan, matching observed 402 evidence or exact source bindings.
Those production plan/evidence inputs are not committed in Docs. The Runtime
facts include capability and pricing revision references, but do not expose the
complete reviewed PAYG quote plan used by the existing v2 builder.

To complete this part without changing payment enablement:

1. Recover the actual production rollout's `plan.json`, `evidence.json` and
   schema bindings, or obtain a fresh read-only quote plan with the existing
   backend command. Do not apply/rollback payment flags.
2. Bind the plan to the same Runtime acquisition and composed operations.
   Reuse the existing unauthenticated challenge probe if current observations
   are needed; paid execution remains out of scope.
3. Make the explicit reviewed v2 bundle the default candidate input and include
   its exact files in the formal publication manifest. Use semantic operation
   bindings so unrelated editorial regeneration does not invalidate payment
   evidence. Keep quote and method/capability checks fail-closed.
4. Compare the generated subset with API `/openapi.json`, listing exclusions
   and revision/quote mismatches instead of hardcoding a target count of 109.

This PR intentionally does not turn on payments, synthesize quote/evidence
records, accept new debt, or remove formal readiness gates.

## Candidate CI acquisition repair

PR #184 exposed a second, independent blocker in the artifact CI job. It read
Runtime pins from main's last-good Docs publication (`906ecf50...`, compiler
`cfbe0505...`) and passed them to an acquisition helper that requires a fresh
matching current pointer. Runtime had advanced, so the real CI run
`38752364325`, job `116481991348`, failed before downloading artifacts with
`Current release does not match fresh pinned revision`. The same command failed
locally. Adding generated files alone cannot resolve this cycle.

The artifact CI job now uses the existing trusted public `--current` discovery
path, as the formal publisher and source-review workflow already do. It still
checks actual PR bytes, independent debt/identity baselines and all formal
gates. No generated file, formal receipt or acquisition validation was changed
by this CI repair. A source-only PR remains incomplete until its actual generated
candidate is committed and assessed. If Runtime moves again, regenerate and
review; CI must not silently regenerate away a stale PR graph.

The targeted change-scope, acquisition and receipt-preparation suites pass
27 tests, including new assertions that current discovery rejects stale or
unpublished Runtime generations and CI never writes/regenerates candidate
artifacts before checking them.
