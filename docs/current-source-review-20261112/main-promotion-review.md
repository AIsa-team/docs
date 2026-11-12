# Complete main candidate for reviewed provider contracts

This candidate consolidates dev PRs #346, #347 and #350 and their response-preservation dependencies from #337, #338 and #339. The main baseline is `14b828ce39bf17a15f53eb31c497514ca534e0ca`; the verified dev output is `2b57134829af6817878989332d1141fc326396c5`.

The source changes cover 2,063 Alexandria operations and four Firecrawl passthrough responses. The complete inventory/upstream review is recorded in `provider-contract-review.json`; the five production-probed operations are recorded in `alexandria-live-schema-review.json`. These remain reviewed static contracts, with documented-fields-only bounds where upstream evidence does not guarantee complete payload shape or requiredness.

## Coherent candidate generation

The existing `pull_openapi.stage` and `runtime_consolidate_openapi.py` rebuild the affected native documents and pages in both languages, together with the complete coverage, pending metadata, registry, YAML/JSON aggregates, llms discovery and sales projection. Unrelated native documents, navigation and pages retain main's reviewed bytes. The affected pages bind to `openapi/` documents and their readable request declarations match those same documents. The 2,067 reviewed operation pairs have 4,134 matching English/Chinese pages and 704 native contract files.

The full native candidate uses the existing `unreviewed_runtime` mode used by the independent candidate checker. It retains explicit review status for unrelated incomplete source descriptions rather than inventing reviewed supplier contracts. No accepted-debt baseline or readiness rule changes.

Local inputs are the original 561 production index/provider files from immutable release `f3dd779b1323726549ea86ac4a22d64f58c78c33f8bcf8c8010ff42e5d3c8d8b`, generation 13850. Every file's SHA256 matches the independently acquired manifest retained by CI run `43198560553`. This is a local candidate replay, not a new formal acquisition. The PR workflow reacquires fresh current independently before checking the new commit.

The JSON aggregate uses compact serialization, matching Runtime's existing representation. It contains every declaration and is 65,595,183 bytes, below the existing 64 MiB role limit. YAML and JSON are checked against the same reconstructed graph. The publication pointer, formal readiness/acquisition receipts and frozen schema-input bundle remain byte-identical to main; the normal publisher remains responsible for future formal exports.

## Validation

- All 1,204 unit tests passed, with one existing skip. The aggregate/YAML focused regressions also passed.
- The original `check_contract_candidate.py` passed against the verified production facts and independently configured baseline `78ef376841ead8cde10a79651958790be5a0531c`: no global errors, blocked providers, source-governance failures or page/aggregate mismatches. Its publication-surface check covers 551 Runtime provider documents and 6,448 operations. The local result is candidate validation; fresh acquisition is still required in CI.
- All 2,067 targeted operation pairs have both language pages and no unreviewed-success placeholder. Their page/contract hashes and the complete aggregate/index hashes are in [the evidence record](main-promotion-review.json).
- The two minimized regressions exercise the actual Wikipedia native document and pages. Both now pass: request/response composition agrees with the committed contract, and the actual bilingual pages bind to that contract.
- The five previously probed production Runtime profiles still match. The final native schemas pass 44 recorded request-case checks and 22 complete successful-response checks, reusing all 11 successful production payloads in both languages. Wayback URI syntax relies on the original actual 400/200 pair rather than an optional local format validator. No additional business API calls were made.
- Navigation, canonical slugs, the 80 existing independent production-reference pages and all 109 payment-discovery operations pass their checks.

People Data Labs company/enrich follows the current production mixed Alexandria route (profile `9d71cee78359`), already present on main. Dev's blocked catalog retained an older handler contract; that historical envelope is not the basis for this candidate.

This PR does not export a new publication pointer or merge main. Its CI result must be checked on the latest commit before review/merge.
