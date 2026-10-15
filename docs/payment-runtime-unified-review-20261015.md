# Runtime-owned payment discovery publication

## Problem and ownership

The normal Docs publisher generated only the original three-route Polymarket
pilot. Production served a separately generated, already enabled multi-provider
MPP catalogue. The existing optional multi-provider generator required a private
historical plan and whole-provider byte hashes; using it unchanged would make
ordinary Runtime price updates require repeated manual payment reviews.

Keep one Runtime and the existing Docs publisher. Runtime's unauthenticated
HTTP 402 challenge is the payment quote authority. The immutable Runtime
snapshot supplies enabled status, exact methods, fixed-success eligibility,
upstream target and contract/pricing revisions. The normal reviewed Docs
composition supplies request/response schemas. No request estimate is converted
into a payment price, and no second pricing plan is maintained by Docs.

## Reviewed enrollment and observed comparison

The private production rollout marked `published` supplied the initial scope.
Its original plan and published report/output hashes were checked; the plan's
allowlist digest matched the compact Go JSON encoding of the versioned
allowlist. Neither the private plan nor its database IDs, previous flags or
configuration bindings are published here. Their hashes are retained only as
historical review provenance, not ongoing mathematical quote authority.

The actual published subset contains 109 operations over 101 paths, across 14
providers. These are observation results, never constants or enablement rules.
All operation IDs are preserved. Initial independent no-credential 402 probes
matched the historical plan amounts for every operation. The current snapshot
also matched enabled status, MPP method, fixed-success billing, target and all
three revision fields for every selected operation.

The machine-readable companion review compares the previous deployed catalogue
with the current complete schemas, including reachable components. After
resolving reference namespaces and excluding display annotations, only these
previously reviewed source changes affect wire declarations:

- Financial `GET /financials` and `GET /financials/cash-flow-statements` gain
  optional `exchange` (`LSE`) and `isin` query parameters.
- Querit `POST /search` adds `russian` to the language include enum.

There are no successful response constraint changes or payment-term changes in
this comparison. The source review is
`docs/current-source-review-20261015/financial-kalshi-querit-review.json`.
Brave component namespaces, discriminator references and examples changed
without changing the resolved response constraints. Polymarket positions and
Search smart also serialize unchanged numeric defaults/bounds as `1.0`/`0.0`/`10.0`
instead of integer JSON tokens; their declared number constraints are equivalent.
These two representation differences remain visible in the companion diff.
Existing pending upstream
work is not accepted or cleared by this payment publication.

## Acquisition and generation contract

1. Acquire and validate the complete immutable fresh Runtime release using the
   existing `fetch_runtime_release.py --current` protocol.
2. Stage normal Docs contracts with the existing source reviews, preserved
   history and readiness gates.
3. `refresh_payment_publication.py` reads the committed reviewed scope. It never
   enumerates new routes from capabilities and never changes payment flags.
   All scoped methods must still be enabled, MPP-capable, fixed-success and bound
   to the same reviewed upstream targets in the acquired Runtime documents.
4. Re-read public Runtime `current` before and after all observations. Both
   manifests must be fresh, fully published, valid and exactly equal to the
   acquired snapshot. A changed generation/revision, stale response or failure
   aborts the refresh.
5. Send only unauthenticated GET or POST requests to the fixed production
   origin, with `X-MPP-Discovery: true`; POST sends `{}` and path placeholders
   use `discovery`. Redirects and proxy settings are disabled. No API key,
   Authorization header or payment credential is sent. The server's auth path
   returns its challenge before upstream execution or payment authorization.
6. Require actual 402 responses with Tempo `charge`, the reviewed chain/token,
   six decimal USD denomination, a positive integer amount and a valid observed
   timestamp/expiry interval. Keep the real expiry; it is not a renewable claim
   that an old challenge can still be paid. Clients must obtain a new challenge.
7. Bind those observed terms to the selected current source contracts, full
   reference closure and Runtime revisions. Request methods, parameters, bodies,
   responses, security, fixed billing and MPP flags remain checked. Examples,
   defaults and unknown extensions are data, not hidden reference declarations.
8. Offline `generate_payment_discovery.py` and `--check` read the reviewed v3
   evidence bundle and make no network requests. They publish the complete
   selected schema with the actual observed payment amount, preserving deployed
   operation IDs and namespacing components per operation.
9. The existing formal artifact check, graph hashing, single-parent publication
   and consumer notification remain mandatory. No formal pointer is fabricated
   by this implementation or review.

The original optional plan-based v2 command remains available with its original
explicit semantics. The default v3 path makes no ongoing base-times-multiplier,
paid execution, provider execution or settlement claim.

## Automatic updates and unchanged observations

Within the fixed scope, Runtime price/revision changes cause a real challenge
refresh and automatic evidence rebinding. Schema changes follow the main Docs
source review/readiness rules; they do not introduce another payment-specific
manual approval queue. Scope additions, target changes, unsupported methods or
unknown settlement assets still require deliberate review. Disabling or removing
a selected Runtime operation fails closed; withdrawing it requires an explicit
reviewed scope edit and never happens silently.

When contracts and payment terms are unchanged, the publisher retains the exact
existing evidence bytes, observation timestamps and publication identity. Fresh
observations, including their real new expiry, go only to the `payment-observation`
run artifact. An unrelated Runtime release or refreshed provider bookkeeping
alone does not renew payment evidence or acceptance budgets.

Every acquisition/validation failure leaves committed evidence and discovery
files untouched and fails the existing producer run before publication. The
last successfully published release remains live. This does not add a new
partial-publication or last-good protocol; a payment acquisition failure can
still block that producer attempt and must remain visible.

## Formal graph and consumer compatibility

Only the existing `discovery/payment-evidence.json` and
`discovery/openapi.json` paths are used. Website's receipt verifier/archive
reader, Router's `verify_formal_docs.py`, and MCP's
`verify_producer_receipt.py` validate the complete discovery pair and exact
file hashes without interpreting the internal payment evidence version.
No extra manifest path or consumer schema migration is required. The Docs
producer is responsible for the v3 semantics before issuing its formal receipt.

The public `api.aisa.one/openapi.json` is currently served by the Services/nginx
rollout static file. This PR does not deploy or replace that file, and the current
Docs notification targets do not synchronize it. Consuming the formally bound
Docs discovery artifact at that existing deployment boundary remains a separate
explicit integration step; this PR alone does not claim end-to-end updates of
that public payment catalogue.

## Validation

Payment tests cover default generation and verification; real-quote price
changes without a new plan; unchanged observation identity preservation;
missing evidence; bad assets, expiry and amounts; network and snapshot failures;
fixed target enforcement; disabled/mismatched capabilities; nested reference
closure; and reference-shaped examples/extensions. Existing pilot and explicit
v2 plan tests remain applicable.

Commands:

```sh
python -m unittest discover -s scripts/tests -p 'test_payment*.py'
python scripts/generate_payment_discovery.py --check
python -m unittest discover -s scripts/tests
```

Current validation: the complete formal candidate passed with no global errors,
missing inputs or scoped source failures. A second actual 402 collection kept
publication bytes unchanged. The successful observation window spanned 16.0
seconds from first to last request start within the 180-second acquisition
deadline. Three consumer graph readers accepted all 4,289 real candidate files
including the v3 evidence. These are offline graph compatibility checks, not a
claim of authenticated producer receipt or deployment.

The accompanying PR records the final test and deterministic replay results. Production 402 checks are metadata observations only; no paid upstream
execution or settlement has been tested.
