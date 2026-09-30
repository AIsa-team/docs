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
identity. Existing response schemas/examples remain a versioned fallback when
runtime supplies only a generic success response; errors and authentication are
never inherited. Explicit runtime response contracts supersede this fallback.
Editorial notes append to runtime constraint notes with stable deduplication.

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

`refresh-upstream.yml` stages official source updates monthly as a review PR.
It skips manual mirrors, avoids timestamp-only changes, and retains operations
removed upstream along with their reachable components. Retained operations are
explicitly listed in source provenance and the PR body. The workflow never merges
its own PR.

Scheduled/event pulls on main publish validated mirrors and coverage automatically;
`RUNTIME_CONTRACT_PUBLISH=false` pauses those publications. Manual dispatch defaults
to dry run and requires its publish input. Feature-branch dispatch remains a dry run. The reusable consumer-dispatch workflow sends the published
revision and consolidated hash to consumers after publication. Application
installation permissions and production endpoint deployment are operational
prerequisites, not inferred from local test success.

The daily `check-contract-revisions.yml` compares runtime per-catalog facts hashes
and provider document hashes reported by docs, the website agent card, MCP manifest
and Tool Router catalog metadata. A repeated mismatch on two consecutive checks
fails the workflow. Legacy sources without runtime hashes are counted separately;
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

PR CI runs both unit tests and `check_contract_candidate.py`. The latter checks
the actual PR documents/coverage and reproduces composition offline using the
existing public runtime cache, including category, index and per-catalog facts.
Fresh request declarations are compared with independent composition before any
previous document-hash reuse. Parameter/body/authentication drift fails even when
the candidate retains its old hash; editorial text and examples remain editable.
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
