# Runtime contract pipeline

`openapi/registry.yaml` is the output registry. `auto_register: true` discovers
catalog IDs from `/info/apis/category`; a new catalog gets `<catalog>.json`
without a manual registration. New operations inside an existing catalog are
composed on every pull. A `group: [catalog-a, catalog-b]` entry combines those
catalogs into one output and excludes members from duplicate auto-registration.
The initial registry includes all 49 observed catalogs; the 11 Open-Meteo
catalogs share one output. Discovery remains active for future providers.

```sh
python3 -m pip install 'PyYAML>=6,<7' 'jsonschema>=4.23,<5' 'openapi-spec-validator>=0.7,<0.8'
python3 -m unittest discover -s scripts/tests -v
python3 scripts/pull_openapi.py --facts-dir /path/to/facts       # dry run
python3 scripts/pull_openapi.py --facts-dir /path/to/facts --write
python3 scripts/pull_openapi.py                               # public API dry run
```

Offline facts contain `category.json` and `<catalog>.json` OpenAPI 3.1 documents.
Optional `inventory/<catalog>.json` catalog responses let the coverage report
list individual endpoints when that catalog's runtime projection is unavailable.
Runtime facts require `info.x-aisa-document.facts_hash`. Public facts use the
root server and full paths. `x-aisa-any` is a path-item extension, not a method.

Each output operation has `x-aisa-catalog-id` identifying its original runtime
catalog. Grouped policies remain under `info.x-aisa-catalogs[catalog]`; the
consolidated spec retains them under
`info.x-aisa-document.providers[output].catalogs`. Provider metadata also includes
`catalog_ids`, `display_name`, description, plans, capabilities and source kind.
Every consolidated operation identifies its source output with `x-aisa-provider`.
`x-aisa-docs-url` is emitted only when an existing MDX reference can be matched;
it points to the actual `https://aisa.one/docs/...` page, never an invented slug.

## Request schemas and published compatibility

Runtime identity, parameters it validates, status, prices, protocol and capabilities
remain authoritative. Provider/mixed request fields require a matching upstream
mirror. Official mirrors match `x-aisa-upstream-path`; transitional manual mirrors
with `path_space: public` match the exact effective public path and method.
They do not guess provider prefixes or rename parameter placeholders.
Missing mirrors, external request references and unsupported mixed
constraints remain pending with explicit reasons. No schema is invented from
catalog descriptions. A runtime price estimate may be unavailable; absence does
not mean zero, and quote remains the request-specific pricing authority.

All 47 existing specifications are imported under `openapi/upstream/` as
**manual** sources with the immutable original GitHub URL, source content hash,
revision time and converter version. They are not represented as official
provider specifications. The importer is repeatable against a chosen revision:

```sh
python3 scripts/import_existing_contracts.py --revision <docs-commit> --write
python3 scripts/audit_public_coverage.py --inventory /path/to/public-inventory \
  --output openapi/coverage-sources.json
```

Six additional official machine specifications are imported with
`kind: provider_openapi`: Polymarket Gamma, CLOB, Data, Relayer and Bridge, and
Parallel. Their source URLs come from the providers' own documentation indexes.
They are matched only using runtime `x-aisa-upstream-path`; the public inventory
alone cannot certify this mapping. Import a reviewed source explicitly with
`scripts/import_upstream.py --provider <catalog> --url <official-url> --write`.

The source audit measures available request mirrors only. It does not prove
runtime validation or deployment. The recorded 2026-09-29 public inventory has
1,878 endpoints in 49 catalogs: 1,676 exact-path manual mirrors are available
and 202 are absent. Legal recursive schemas retain local references and their
reachable namespaced component definitions. Some absent
mirrors are unnecessary once a complete declarative runtime contract exists.
The actual production facts endpoint must be deployed before a full live
projection can be verified.

ANY methods come from matching mirrors. Each previously published method keeps
its operation ID; new methods get deterministic distinct IDs within the 56-character
tool limit. The base endpoint ID never replaces a different published method's
identity. Explicit runtime success response contracts remain authoritative.
For `x-aisa-passthrough: true`, current matching provider success payloads take
precedence over historical published payloads. Exact public-route mirrors may
also declare the public response; an upstream wrapper is never assumed to have
the same output shape. Errors, headers, links and authentication are not inherited.
Historical success schemas/examples remain a labeled, versioned fallback when
no current authority supplies the payload. Unknown response declarations and
unresolved response references appear in `x-aisa-response-pending` and provider
metadata `response_pending`, separately from request pending. These are source
gaps, not execution failures or additional endpoint admission gates. A complete
request publication is not a claim of complete response documentation.
204/205 No Content and explicitly unconstrained JSON schemas are valid responses.
Editorial notes append to runtime constraint notes with stable deduplication.

OpenAPI 3.0 Schema Objects are converted to 3.1 before use: nullable types and
exclusive numeric bounds retain their semantics, and 3.0 reference siblings are
ignored as required by that dialect. JSON instance data in defaults and examples
is preserved even when it contains a literal `$ref`. Recursive schema definitions
remain namespaced local references. Unsupported declarations remain reported.
Provider SDK code-generation overrides (`x-stainless-override-schema`) stay in
the upstream mirror and are omitted from the public projection. They are not
public wire schemas; retaining their private references can prevent consumers
from loading otherwise valid contracts. Public `x-aisa-*` metadata and literal
JSON examples/defaults remain intact.

The puller finds existing pages by effective public route, across old split
files. It keeps their slugs and prose and updates their OpenAPI references to
the new output. Successful operations move out of old split specs; unsupported
or out-of-scope legacy operations remain. Registry `legacy_sources` records old
spec stems, and their complete immutable content remains in the manual mirrors.
Consumers can use those original operation IDs to preserve hand-authored theme
include selections without expanding the theme to every operation in a new file.

English titles follow runtime summaries; Chinese titles and schemas use the
existing translation catalog, with English fallback. No paid/model translation
runs in this pipeline. New pages/navigation are additive. Disabled operations
retain their page and a managed status notice.

The `Test runtime contracts` workflow runs the same regression suite for pull
requests that change contract sources, scripts, workflows or reference pages.
It uses local fixtures and checked-in mirrors without production credentials,
publishing or provider calls. An optional cached FRED reference audit may skip
when that local cache is absent; it does not disable the rest of the suite.

## Coverage and failure behavior

`openapi/coverage.json` lists every observed runtime operation as composed or
pending, with its catalog, route, method, identity, validation boundary and schema
source. It also lists retained legacy operations outside composed contracts.
`openapi/pending.json` carries actionable per-provider failures. A provider that
cannot retain a published identity keeps its old spec/pages; the failure is
reported without blocking independent providers. Grouped outputs are preserved
as a unit if a member's facts are unavailable. Reports do not label old retained
specifications as newly verified runtime contracts.

`pin: <docs-commit>` restores the original bytes, including handwritten documents
without runtime hashes. Page references follow the pinned server/path convention.
A pin that removes or changes a published route identity is rejected before writes.
Pinning a 23-route version after publishing 29 routes therefore requires an explicit
documentation migration. Repeated pulls of the same pin produce no changes.

Runtime ETags cache facts under ignored `.cache/runtime-contracts`. Overlays and
mirrors are recomposed after 304; facts, consumed mirrors, retained response
contracts and composer version enter `document_hash`. `generated_at` alone never
causes churn. Imports remain explicit, reviewed source changes; existing mirrors are not silently refreshed during composition. For a new
passthrough provider, setting `upstream: https://.../openapi.json` (or an object
with `url`) in its registry entry imports the initial official mirror automatically.
No additional consumer registration or manual import command is required. A changed
source URL triggers a new staged import. Download/validation failures retain the
previous publication and are reported as pending.

`refresh-upstream.yml` stages official source updates daily as a review PR.
It skips manual mirrors, avoids timestamp-only changes, and retains operations
removed upstream along with their reachable components. Retained operations are
historical evidence, not a claim that the provider still serves them. Pinned
sources remain unchanged until their owner supplies a reviewed revision update.
The workflow never merges its own PR or rewrites runtime bindings.

Before retaining removals, `upstream_semantics.py` compares effective method/path
and inherited server bindings, request parameters/body, requiredness, types,
constraints and serialization, effective authentication/security schemes, and
response declarations. Local references and path/operation inheritance are
resolved. Prose/examples and reordering unordered schema declarations do not
produce semantic changes. Added/removed/changed declarations require review;
Local recursive schema graphs are compared through memoized declaration pairs,
including reachable constraints and reference siblings. External, dynamic,
non-schema recursive and unsupported reference scopes remain explicitly uncertain.
`declarations_unchanged` reports only the compared declarations, and compatibility
is always `not_assessed`; this is not an upstream execution probe.

The refresh report records source URLs, content hashes, fetch times and source
age. Source acquisition failure preserves the previous file and reports the
failure class plus prior evidence; it does not refresh its age or claim a fresh
contract. Successful updates can still form a review PR when another source
fails, and the workflow remains failed for that acquisition error. The full
field diff is uploaded as the `upstream-contract-review` workflow artifact;
the PR body contains a compact summary rather than an unbounded report.

Scheduled/event pulls on main publish validated mirrors and coverage automatically;
`RUNTIME_CONTRACT_PUBLISH=false` pauses those publications. Manual dispatch defaults
to dry run and requires its publish input. Feature-branch dispatch remains a dry run. The reusable consumer-dispatch workflow sends the published
revision and consolidated hash to consumers after publication. Application
installation permissions and production endpoint deployment are operational
prerequisites, not inferred from local test success.

The hourly `check-contract-revisions.yml` compares runtime per-catalog facts hashes
and provider document hashes reported by docs, the website agent card, MCP manifest
and Tool Router catalog metadata. Missing runtime catalogs, pending projections,
missing publication evidence and hash mismatches all enter the existing consecutive
check state; the same issue on two consecutive checks fails the workflow. A healthy
check clears it. Legacy sources without runtime hashes are counted separately;
they are never reported as successfully compared runtime contracts.


Handler-owned and historical operations
---------------------------------------
The runtime contract index also drives discovery, so asynchronous and disabled
providers do not depend on the marketing catalog. Code-owned lifecycle routes
use the real installed profile descriptors; derived lifecycle IDs retain the
existing published ID at the same method/path. Full operation IDs must be unique;
legacy IDs that share a 56-character prefix remain unchanged.

An operation whose path is absent from the complete runtime provider document
keeps its old page and identity with `x-aisa-status: disabled` and
`x-aisa-contract-pending: not_in_runtime_contract`. This does not hide a missing
schema or identity change on a path still present in runtime facts: those remain
pending or block the affected provider. Inactive historical pages cannot block
otherwise valid current contracts from refreshing.

An upstream registry entry can set `file: provider-official.json` to select a
reviewed official mirror while retaining the original public-route mirror for
old identities and response schemas. Paths match the effective OpenAPI server
prefix with operation/path/root precedence; ambiguous matches fail closed.
Official reference converters record source hashes and never infer types from
example responses. Refreshes run through the same reviewed upstream workflow.

## Publication readiness checks

`contract_readiness.py` checks the actual public operation graph, runtime endpoint
accounting, exact coverage outcomes and runtime-owned request declarations. It is
a pure assessment and cannot change routing, admission, authentication or billing.
Endpoint counts remain separate from ANY method expansion and async/Batch
lifecycle operation counts. Runtime `coverage.projected_endpoints` supplies the
configured endpoint evidence, including source paths that differ from public
lifecycle paths.

`pull_openapi.py` assesses staged outputs before any file writes. Structural
errors, incomplete global evidence and index/facts hash mismatches cannot be
reported as successful fresh publication. Explicitly unavailable providers keep
their last published files; unaffected providers can refresh. New unresolved
operations remain absent from complete contracts and appear in coverage/pending
reports. `--readiness-mode pr` additionally fails for newly introduced or changed
pending operations.

Accepted pending debt comes from `--baseline-ref`, a full independently reviewed
Git SHA containing coverage. The workflow reads `RUNTIME_CONTRACT_BASELINE_REF`;
it does not advance it when a scheduled run writes new pending entries. Without
that reference, no unresolved operation gets an existing-pending exemption. The
initial baseline is a review decision, not a claim that pending contracts work.
Comparison uses operation identity, binding and stable failure classification;
whole-source content hashes and error wording do not become endpoint identities.
Bindings include the reachable local request-schema graph, so changing a type
behind an unchanged reference name cannot preserve an accepted pending entry.

PR CI always runs the fixed-input code regression job. Changes to generated
contracts, sources, reference pages or navigation additionally run the artifact
job and `check_contract_candidate.py`; mixed changes require both jobs. The latter checks
the actual PR documents/coverage and reproduces composition offline using the
existing public runtime cache, including category, index and per-catalog facts.
Fresh request and response declarations are compared with independent composition
before any previous document-hash reuse. Parameter/body/authentication and response
payload/protocol drift fails even when the candidate retains its old hash;
editorial text and examples remain editable.
It never fetches production or invents missing fixtures. Missing evidence produces
`not_assessed` and a nonzero exit. Existing pre-rollout caches without endpoint
evidence are insufficient; seed the cache from the new runtime before treating
this check as acceptance.

Retained contents are verified against an independently selected published Git
revision (`--published-ref`, PR base/before SHA in CI). Comparison includes local
reference closures, inherited parameters and authentication declarations. The
candidate cannot certify a newly added operation as historical by setting a flag.
This historical-content reference grants no pending-debt exemption.

Examples, using separately selected reviewed revisions:

```sh
python scripts/check_contract_candidate.py \
  --baseline-ref "$REVIEWED_BASELINE_SHA" \
  --published-ref "$PUBLISHED_DOCS_SHA" \
  --report /tmp/contract-readiness.json
python scripts/pull_openapi.py --write \
  --baseline-ref "$REVIEWED_BASELINE_SHA" \
  --readiness-report /tmp/contract-readiness.json
```

Readiness reports are workflow artifacts. `passed` describes declarations and
accounting; it is not execution capability or upstream uptime evidence. Existing
LLM-only legacy source overlaps are listed separately, while conflicts involving
managed integration outputs and all identity collisions block publication.

## Publication convergence acceptance

`check_contract_revisions.py` compares public runtime facts, docs, website, MCP
and Router metadata. Scheduled monitoring uses the same mismatches and missing
inputs as the convergence assessment, with its existing two-consecutive-failure
escalation. Missing catalogs cannot stay green indefinitely; recovery clears their
state. A separate strict mode fails on the first
missing input or mismatch and never updates that monitor state:

```sh
python scripts/check_contract_revisions.py --acceptance \
  --expected-docs-ref "$PUBLISHED_DOCS_SHA" \
  --report /tmp/public-contract-convergence.json
```

The expected revision must be an independently selected full immutable docs SHA.
Empty or entirely legacy docs metadata cannot pass acceptance. Every runtime
catalog must have docs metadata; runtime projections still pending are unassessed.
MCP and Router must report the exact selected docs revision as well as matching
provider hashes. Unavailable surfaces produce a dated `not_assessed` report and a
nonzero exit, even if another surface is healthy.

For offline verification, add `--evidence-dir DIR` containing public metadata in
`runtime.json`, `website.json`, `mcp.json` and `router.json`. The manual existing
workflow exposes the same acceptance mode and retains the report as an artifact.
This verifies public contract convergence. It does not invoke upstream provider
operations, prove execution support or establish provider availability, and it
cannot change production configuration.

## Source ownership and exact debt

Each `info.x-aisa-source` declares a repository maintainer owner, authority URL,
refresh policy, policy revision and review period. The frozen acceptance inventory
has 48 manual sources, 18 automatic sources and one pinned source. These policies
are proposed test inputs until separately reviewed and published. Existing and
future endpoints using a reviewed source inherit its policy. A new supplier still
needs one authoritative source. After activation, automatic acquisition runs daily;
manual and
pinned reviews expire after at most 30 days. A newer pinned-revision signal blocks
freshness until reviewed. Missing declarations or receipts cannot pass readiness.

Receipts live outside published contracts in `.cache/source-reviews.json` and
dated workflow reports. They are keyed by source hash and policy revision. A
successful unchanged official acquisition updates the receipt without rewriting
the mirror or its `fetched_at`. A local file reread is not a review. Manual/pinned
confirmation requires official evidence, an attributed reviewer and an immutable
review reference. No receipt is created by migrating policy metadata. `fresh`
describes maintenance evidence, never provider execution compatibility.

`coverage.json` version 2 records request and response debt independently.
Acceptance compares exact operation identity, method/path, runtime status,
binding/profile, stable reason and the relevant reachable source declarations.
Source-wide hashes, fetch timestamps, unrelated schemas and editorial text do not
invalidate unrelated debt. Changed bindings or referenced constraints do. Response
debt additionally binds success statuses and the public response graph. Equal
counts with different gaps fail; old baselines missing these fingerprints grant
no exemption. Baselines are selected by reviewed Git SHA and never auto-advanced.

Formal artifact checks restore runtime facts and attributed source receipts,
recompose independently and check the actual candidate before publication.
Missing evidence returns `not_assessed` with exit 3; it cannot become success.
Code checks need no production cache or unpublished runtime deployment. A green
code job does not approve a debt baseline, source review, production identity
import, consumer pin or deployment.

`test-runtime-contracts.yml` retains the existing `contracts` required check as
the final summary of code checks and all applicable artifact checks.
`artifact-contracts` is additional whenever the fixed base-to-head Git
diff changes any `openapi/` file (including source policy metadata and deleted
files), `openapi.yaml`, localized reference pages or `docs.json`. An unknown base
requires the artifact check; an invalid revision fails classification. Replay
the same classifier with:

```sh
python scripts/contract_change_scope.py --base "$PR_BASE_SHA" --head "$PR_HEAD_SHA"
```

For the initial rollout, submit compiler/governance code, their fixtures and CI
as a code-only change first. Keep the 67 source-policy migrations and any
regenerated coverage/spec/pages in a separate artifact change until real runtime
facts, source reviews and the independently approved debt baseline exist. A
mixed change runs both checks and cannot use the code-only result to publish.
The summary fails when classification fails or omits a scope, the code job fails,
or an applicable formal artifact job fails or is skipped. Code-only changes need
no formal evidence. Repository administrators must verify that required-check
configuration includes `contracts` and does not separately make an
evidence-dependent check mandatory for unrelated code-only changes. This document
does not change branch protection.

The initial code change contains no source mirrors, registry, generated specs or
pages. Catalog-dependent tests read the immutable sanitized W0 package under
`scripts/tests/fixtures/w0-package`, verify its archive hash and extract only its
input tree into a temporary directory. The proposed source-policy fixture lives
outside that unchanged W0 package; it creates no real review receipts. Production
composition and formal assessment do not read these fixtures.

New pull, refresh and convergence-monitor workflows are manual-only in this code
change. The existing `sync-openapi.yml` workflow is preserved. W4 separately
reviews and enables the documented schedules, dispatch integration and formal
publication path after its real inputs exist. Merging generator code does not
activate those maintenance workflows or advance a consumer source pin.

The existing consolidator, localization and slug-validation scripts also retain
their main-branch bytes. New runtime tooling explicitly uses
`runtime_consolidate_openapi.py`, `runtime_localize_openapi_zh.py` and
`validate_runtime_api_reference_slugs.py`. This avoids changing the existing sync
workflow's legacy publication while merging the new code. The unified discovery
aggregate keeps its legacy routing format; per-provider native documentation is
the complete contract. Formal assessment separately rejects unresolved local
declaration references in the aggregate. Namespace changes preserve literal JSON
in examples/default/enum/const and Link inputs, and update discriminator mappings.

When a pull actually acquires a new automatic source, it retains that receipt in
the non-public cache even if an unrelated candidate gate blocks publication.
Dry runs do not save it. The pull workflow saves receipt history on failure as
well as success, so the next assessment can restore that acquisition. This does
not write a blocked candidate, approve a source policy or create manual reviews;
hash/policy-bound receipts only qualify for their exact source declaration.

```sh
python scripts/refresh_upstream.py --audit-only --report /tmp/source-review.json
python scripts/check_contract_candidate.py --source-receipts /path/to/receipts.json \
  --baseline-ref "$REVIEWED_BASELINE_SHA" --published-ref "$PUBLISHED_DOCS_SHA" \
  --report /tmp/formal-contract-readiness.json
```

## W3 fixed inputs and dormant activation

The W3 code gate also generates the actual EN/ZH schemas, MDX and navigation
from fixed inputs. `publication_surface.py` compares protocol structure while
allowing translated prose, checks each page's declared operation ID and ensures
both navigation trees reach the same runtime operations. The formal checker
uses that same read-only validator and binds every actual schema/page/navigation
file in its receipt. Existing page aliases follow their published operation ID
when a path is normalized; their URLs and prose remain intact.

The runtime aggregate quotes all single-line JSON strings explicitly, retaining
multiline block strings. This preserves identifiers with leading zeros and
exponent-shaped profile hashes across Python and JavaScript YAML readers without
changing their source values. Code CI exercises the producer serializer with
Node 22 and js-yaml 4.1.1 in addition to the complete fixed candidate checks.

Runtime JSON source readers reject a decimal or exponent token when conversion
to a finite Python float would change its decimal value. Unsupported precision,
overflow, underflow, NaN and Infinity raise `unsupported_numeric_precision`
before publication; automatic discovery records the gap as pending and retains
the last good contract. Integer tokens remain integers. JSON sources use the JSON
parser directly. YAML sources reject ambiguous plain numeric, boolean and date
scalars instead of relying on YAML 1.1 coercion: use an actual JSON source for
numbers, or quote a scalar when the authority intends it to be a string. This
guard does not add an arbitrary precision serialization format.

```sh
python scripts/tests/w3_verification/prepare_full_catalog.py --docs-root . \
  --archive scripts/tests/fixtures/w0-package/scripts/api-contract-acceptance/data/full-catalog.tar.gz \
  --with-pages --output /tmp/docs-code-candidate
python scripts/publication_surface.py --root /tmp/docs-code-candidate/candidate
```

The extra legacy MDX fixture and page identity index contain exact data from the
W0 fixed Docs revision, with separate hashes and provenance. They fill only the
temporary test candidate; they do not alter W0 or become production authority.
The generated `diagnostic-docs.lock.json` binds actual aggregate bytes and marks
the result unapproved and non-activatable. Its code SHA is not a publication SHA.

`contract_activation.json` defaults to `activation_enabled: false`. The 10-minute
pull and hourly monitor schedule definitions stay dormant unless both the tracked
plan and `RUNTIME_CONTRACT_ACTIVATION_ENABLED=true` are enabled by the release
owner. Manual dry-run defaults remain available. Activated monitoring requires
an independently selected `RUNTIME_CONTRACT_EXPECTED_DOCS_REF` and recorded
`RUNTIME_CONTRACT_BUDGET_START`; missing/invalid inputs fail before fetching.
Scheduled recovery selects that exact Git source and validates its aggregate
hash. The original budget start is retained: 3600 seconds for a candidate and
14400 seconds for convergence, with the first deadline breach failing immediately.
After an on-time complete observation, the monitor retains its latency for that
exact Docs SHA, aggregate hash, budget start and phase while rechecking all live
surfaces. A new version/start or a later mismatch cannot reuse that healthy
result. Strict acceptance ignores the monitor cache.
Operator/CDN limits and real normal/lost-dispatch timing receipts remain W4 work.
The legacy `sync-openapi` writer exits 3 when a runtime registry exists, directing
publication to the single strictly assessed `pull-openapi` path. Without a
registry, its existing legacy consolidator and outputs remain unchanged.

## Resolving a missing contract

A pending entry is an intake item, not a diagnosis that the API is broken.
Use the operation ID, actual upstream binding and reported missing declaration
to find its owner and source. Check, in order, the current handler/request type,
official OpenAPI, the provider's official reference/source repository, and a
versioned official legacy contract for an exact legacy path. A documentation
page slug or similar path is not a verified upstream alias.

Distinguish source acquisition, conversion and binding failures. Repair an
importer when the official declaration is present but its syntax is unsupported.
For multiplexed APIs, an explicit reviewed source binding selects the documented
caller mode and retains its required inputs; it must not invent a runtime default.
If no authority defines a parameter's type or required status, record that exact
uncertainty for provider clarification or authorized request validation.

A known 404/410 or deprecation is an endpoint maintenance issue. Keep its evidence
separate from missing-schema items and propose the exact route/provider change
with its authentication, request, response and pricing implications. Publishing a
schema for a differently named replacement does not repair the configured route.
The documentation pipeline does not silently rewrite production bindings.

Close an item only after composition, OpenAPI validation and relevant consumer
search/details checks pass. An existing published contract remains available as
historical evidence during unresolved refreshes; new operations without a valid
contract stay pending. Changes to runtime execution or production configuration
use their normal separate review/deployment process.

## Repairing missing historical locale pricing

For a ZH mirror that only lacks an existing root `x-aisa-pricing` object,
use the bounded localization command with an explicitly selected immutable
publication base. It defaults to a dry-run; add `--write` to save the reviewed
additions:

```sh
python scripts/runtime_localize_openapi_zh.py sync-alias-pricing \
  --published-ref cf10c7c23c44b2a7666f2d1946cad106a42e326d
python scripts/runtime_localize_openapi_zh.py sync-alias-pricing \
  --published-ref cf10c7c23c44b2a7666f2d1946cad106a42e326d --write
python -m unittest discover -s scripts/tests -p 'test_alias_pricing_sync.py' -v
python -m unittest discover -s scripts/tests -p 'test_identity_compatibility.py' -v
```

The command verifies all historical alias operations and shared spec wire
contexts (servers, security, reusable schemas and path-level parameters) before
writing any file. Other operations remain outside this bounded repair.
Missing root pricing, conflicting locale
pricing, changed route/method/identity, or other wire differences reject the
whole batch. Examples, enum, const and default literals remain significant.
Only missing locale pricing is copied, exactly from root; root specs, prose,
pages, identity metadata and historical Git proof bytes remain unchanged.
This repair does not add approval, publish a receipt, or enable activation.
