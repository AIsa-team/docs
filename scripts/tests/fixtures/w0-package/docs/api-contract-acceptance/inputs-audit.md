# W0 fixed-input audit

Audit date: 2026-10-01. Scope: read-only inspection of existing local evidence and five clean worktrees; no tests, network calls, production queries, publication, or baseline approval were performed. This document supports the completion spec's C01 and input-freezing requirements. It does not establish C14, source freshness, or an approved debt baseline.

## Immutable code references

| Repository | Inspected worktree | Full Git revision |
| --- | --- | --- |
| Runtime | `/private/tmp/aisa-contract-impl` | `dea1899f9833af083c822566420e21ea3a2c129e` |
| Docs | `/private/tmp/aisa-docs-contract` | `89296da5fac52ad51b360ca24005cc2f5a03daa0` |
| Website | `/private/tmp/aisa-landing-contract` | `87be2447689bf303de99eebc8f138336b8db242b` |
| MCP | `/private/tmp/aisa-mcp-contract` | `084c1cff6400409c2c893a017c8a34873595845e` |
| Router | `/private/tmp/aisa-tool-router-contract` | `c842fa0bad68afb5ed395d926b5210ddfc707604` |

Every inspected worktree had an empty `git status --short`. A durable manifest must bind exact bytes to these revisions and distinguish copied snapshot files from files obtained directly from Git. A local absolute path is provenance metadata, not a portable dependency.

## Saved input lineage

`/private/tmp/aisa-verify-full-contract-fixes-20261001.py` (3,062 bytes) reads `/private/tmp/aisa-readiness-full-catalog`, copies its `openapi`, `api-reference`, `zh`, and `docs.json`, then runs Docs `stage` using that source's `facts`. It imports scripts through an absolute temporary worktree path. It supplies the saved coverage as an offline diagnostic debt baseline and writes generated candidate files and diagnostic receipts to a new directory. It is useful historical replay evidence, but is not a portable W0 verifier or an independent expected graph.

The resulting `/private/tmp/aisa-five-gap-full-catalog-20261001` contains replay outputs, not new runtime observations. `/private/tmp/aisa-18-verify.py` similarly used `/private/tmp/aisa-production-contract-facts-20260930`. `/private/tmp/aisa-18-consumers/docs` contains older consumer input material; its 67 upstream JSON files are byte-identical to the later full snapshot. Consumer bundles, logs, and result files in `aisa-18-consumers` are derived evidence, not upstream authority.

The full input is a saved older production-derived projection with in-memory identity assignment, plus a reconstructed index. The existing `/private/tmp/aisa-readiness-docs-pr-body.md` explicitly says its endpoint list was reconstructed from the read-only identity manifest and separately checked against the new runtime index fixture. Byte comparison confirms that the 56 files in `aisa-readiness-full-catalog/facts` differ from `aisa-production-contract-facts-20260930` only in `index.json`: the newer index adds the 1,979 `coverage.projected_endpoints` entries. It is not a saved full-catalog HTTP response from the new runtime revision.

`facts/audit.json` records 2,162 database endpoints, 1,979 identities assigned in memory, no identity column, 183 unreviewed identity candidates in memory, zero production mutations, and a read-only transaction. Preserve that limitation. Do not infer that identity initialization was applied or approved.

The actual code fixtures remain separately reproducible from Runtime Git: `services/api-service/internal/httpapi/api_contract_e2e_test.go`, `api_contract_new_provider_e2e_test.go`, `api_contract_readiness_accounting_test.go`, and `services/backend-service/internal/service/integration_contract_e2e_test.go`. They exercise actual local runtime HTTP and local SQLite/management behavior. The accounting fixture has six endpoints with projected/pending/excluded outcomes; it is not the 2,162-endpoint snapshot. Docs `scripts/tests/test_full_catalog_cutover.py` labels itself a whole-documentation regression, not whole-runtime coverage.

## File schemas, counts, and hashes

All hashes below are SHA-256 of literal file bytes, distinct from canonical semantic hashes embedded in documents.

| File / set | Size / count | Byte SHA-256 |
| --- | --- | --- |
| `aisa-readiness-full-catalog/facts/category.json` | 1,239 bytes; object `apis`, 51 entries | `200947bd8f2bb5235a48f3dc49582b03fb54a45e7c692f8598236e981507be01` |
| `aisa-production-contract-facts-20260930/index.json` | 44,762 bytes; original index | `431e3aeb9283c19eb04cb883e3f00ba7a703fbbd67bc54599533ee509c720e0e` |
| `aisa-readiness-full-catalog/facts/index.json` | 205,944 bytes; reconstructed index | `89b9442608c27dce69ddcbb14cb2e55b0e7d298e9ad72fc70bdc1855d350906c` |
| `aisa-readiness-full-catalog/facts/inventory.json` | 640,234 bytes; array of 2,162 rows | `5ba12d319d58d973a11be0fbbb885a9ccd18fc019e3a6479df113e16f5d0d5a2` |
| `aisa-real-db-identity-manifest.json` | 775,011 bytes; 1,998 method identities / 1,979 provider-paths | `964010efa1bae167d9e5a1baa2c228ebcb7d8d640db73b2a6ababf7fda405d70` |
| `aisa-five-gap-full-catalog-20261001/docs.json` | 805,275 bytes | `10ac537e40633b86254df5f0e308c5634a5fb21db473e904a8e3108f540df0fb` |
| Saved `openapi/registry.yaml` | 7,766 bytes | `be7f319437a9427a0ceb740c960cba91424e2363e416e9deb434f4a527e6cc60` |
| Docs Git `openapi/registry.yaml` | 5,417 bytes | `5fef9b8434f9367b5ca6a1b35ed4617ed2ddaaf70df8485f3afa56585e764252` |
| Saved `openapi/coverage.json` | 955,352 bytes | `54c416a27422cd41e1070d6c8c6663fdc5bbb46207a02002f2a4aaf7b9f1ca77` |
| Saved `openapi/pending.json` | 25,162 bytes | `deaf4067220e42a2979609fd27c0fdcb01c55f42926fbd4321d1decc0b7267da` |
| Saved `openapi/coverage-sources.json` | 712,571 bytes | `c118d209bb56f5370a5bd164c9f1cac4bc83db3dc108250505c13c3c90701484` |

The 56 facts JSON files occupy 4,609,105 bytes: 52 provider OpenAPI documents plus category/index/inventory/audit. Index fields are `schema_version`, `providers`, `coverage`, `pending_endpoints`, and `pending_providers`. Provider entries contain `id`, `url`, `endpoint_count`, `operation_count`, and `facts_hash`. Projected rows contain only `provider` and `path`. Inventory rows contain `provider`, `path`, `provider_status`, `endpoint_status`, `kind`, `operation_id`, and `identity_reviewed`. The inventory has 54 provider keys, 1,975 synchronous V2 rows, four asynchronous rows, and 183 legacy rows; 1,881 endpoint rows are enabled and 281 disabled. Category membership, provider document membership, source membership, and endpoint membership are different denominators.

The real-db identity manifest fields are `schema_version` and `operations`; rows contain `provider_key`, `public_path`, `method`, `operation_id`, `source_file`, `source_sha256`, and optionally `initialize_unpublished`. Its 62 unique source files currently exist and all match their recorded SHA. There are 294 initialize-unpublished identities. Archive a portable projection or map the absolute source paths to exact Git/blob or archived-byte references; do not execute it as an import. The older `aisa-full-identity-manifest.json` has only 1,897 identities / 1,878 paths and is not the full denominator.

All 67 `openapi/upstream/*.json` mirrors are byte-identical across the earlier consumer fixture, full snapshot, and Docs Git revision. Their combined size is 20,424,085 bytes. Each has `info.x-aisa-source` with `kind`, `url`, `fetched_at`, `content_hash`, and `converter`. Further evidence fields vary. Source kinds are 49 manual and 18 provider OpenAPI; the existing refresh algorithm classifies `wrapper-twitter-delete.json` as pinned and `wrapper-cloudsway-smart.json` as automatic, resulting in 48 manual, 18 refreshable, one pinned. This classification does not prove owners, review deadlines, or current source freshness exist.

The saved registry differs from the pinned Git registry. Freeze the saved file explicitly when reproducing this snapshot. Do not silently replace it with the smaller Git file. Freeze the existing overlays (`youtube.yaml`, `similarweb.yaml`) and any referenced side inputs as exact files too.

The 42 composed provider documents occupy 19,644,529 bytes and contain 1,930 standard method operations, of which 1,918 have enabled status. Their `info.x-aisa-document` metadata includes protocol/schema/generator/composer versions, `facts_hash`, `document_hash`, `response_pending`, and `seed_month`. Runtime `facts_hash`, Docs `document_hash`, source `content_hash`, binding hash, and file byte hash have different scopes. Docs `compose_openapi.py` computes document hash from facts hash, upstream/overlay content, composer version, retained response payloads, public mirrors, and source bindings; copying a byte hash into that field would be incorrect.

## Exact endpoint / operation reconciliation

The independent saved inventory's 2,162 unique `(provider,path)` pairs equal the disjoint union of 1,979 selected and 183 explicitly excluded pairs. Both pending lists are empty. All exclusions are disabled legacy with reason `not_synchronous_v2`. This proves accounting of the saved input set; it does not independently prove the original database extraction had no omissions, the proposed identities are approved, or current live inventory is unchanged.

There are 1,987 facts paths and 1,991 facts operations. The +12 operations relative to 1,979 selected endpoint rows are exactly:

- Eight derived paths: Exa `/apis/v1/exa/agent/runs/{jobId}` and `/cancel`; Firecrawl `/apis/v1/firecrawl/batch-scrape/{jobId}` and `/cancel`, plus `/apis/v1/firecrawl/crawl/{jobId}` and `/cancel`; Oxylabs async `/apis/v1/oxylabs/llm/{jobId}` and `/cancel`.
- Four extra methods: each base submit/list path (`/apis/v1/exa/agent/runs`, `/apis/v1/firecrawl/batch-scrape`, `/apis/v1/firecrawl/crawl`, `/apis/v1/oxylabs/llm`) has GET and POST.

Facts status counts are 1,893 enabled and 98 disabled, with 945 `x-aisa-any` operation declarations. Concrete consumer method expansion must be reconciled separately; endpoint counts cannot substitute for it.

Coverage has 2,028 provider rows: 1,926 composed and 102 pending. The request debt is 12 enabled and 90 disabled according to the diagnostic replay receipt, with 62 response gaps reported separately. `pending.json` contains 106 rows because four retained history rows are also reported there. Those four explain exactly `1,930 = 1,926 + 4`: AgentMail GET `/apis/v1/agentmail/threads/search`, GET `/apis/v1/agentmail/inboxes/{inbox_id}/threads/search`, GET `/apis/v1/agentmail/inboxes/{inbox_id}/messages/search`, and CoinGecko GET `/apis/v1/coingecko/news`. There are 14 `legacy_operations` records overall. Treat retained history as explicit provenance, not newly composed runtime coverage.

Coverage row keys are `catalog`, `method`, `path`, `operation_id`, `status`, `validation`, `schema_source`, `binding_hash`, `reason`, and `reason_code`. Legacy rows use `source` plus identity/reason/status. Pending rows use method/path/operation ID/reason. `coverage-sources.json` is older source-path evidence with 49 providers and 1,878 operations; it is not the final full runtime denominator. Generated coverage and gaps can be replay observations and draft review inputs; none is an approved debt baseline merely because it is archived.

## Privacy and explicit archive allowlist

The scan read 56 facts JSON files and 67 upstream JSON files and emitted locations/counts rather than matched values. No database/Redis URI, private-key payload, AWS/GitHub token, JWT, or long literal Bearer credential was found. Facts also had no email/phone matches, credential-valued example/default/const/value, or URL with userinfo. These checks are scoped heuristics, not a proof that every possible secret encoding is absent.

The two PRIVATE KEY marker matches in `upstream/kalshi-official.json` occur in one 214-character description at `/components/schemas/GenerateApiKeyResponse/properties/private_key/description`. They describe PEM delimiters and contain no multiline base64 key payload. Preserve that prose. Tikhub proxy URL descriptions use `user` / `password` placeholders. Its password default is an obvious example. Polymarket API-key UUID examples are present in immutable public source fixtures, with no evidence of runtime credentials. Ordinary contract examples and public provider support contacts should remain intact.

One privacy ambiguity is a non-placeholder personal Gmail literal in `upstream/waveinflu.json` at `/components/schemas/EmailResult/properties/value/example`. Its original source file SHA is `df43c0250c4670856894f24ad953c3e38e717de978f297a8505e6fb660c912d7`. For a strict no-PII archive, replace only this string with `example@example.invalid`, record original and sanitized byte SHA plus the exact JSON pointer, and replay from that sanitized input. The same literal occurs in the saved generated provider document at `/components/schemas/Response8642D49664C4_EmailResult/properties/value/example`. Sanitization changes source bytes and potentially generated document hashes; compare against a freshly replayed sanitized candidate, not the unsanitized candidate's original hash. The fixture copy must be labeled sanitized, without claiming a new reviewed upstream revision. No source files were modified during this audit.

Use a manifest-selected archive, not a recursive copy of a worktree or temporary directory:

1. The 52 indexed provider facts plus category/index/inventory/audit; original old index only as lineage evidence.
2. Exact saved Docs registry, upstream source JSON set, referenced overlays, and explicitly selected historical provider documents needed for retained identity/response behavior.
3. Saved Docs navigation input where page/nav replay requires it. Generated provider documents/coverage/pending may be frozen as diagnostic comparison fixtures; mark them derived and do not install them as generated publication files or approved baseline.
4. Portable identity inventory/manifest metadata, with source references mapped to exact archived files or pinned Git blobs; no SQL or database environment.
5. Manifest schemas, checksums, replay tooling, and hand-reviewed expectations. Real runtime code fixtures stay under their pinned source references and retain a distinct fixture scope.

Exclude `.git`, `.env*`, readonly-query credentials, SQL write previews, SQLite/database files, browser/session data, logs, node_modules, Python environments/caches, consumer generated bundles, activation/source-lock candidates, and arbitrary provider account/config exports. These are neither required public contract inputs nor safe include-all material.

## Outstanding boundaries

The existing replay script grants unchanged debt through its own saved coverage; it cannot approve that debt. A new independent verifier must never import the pending-baseline decision from its candidate. Full inventory expectations should come from the separately frozen inventory and explicit lifecycle/method rules; semantic expectations require independent field-path/ref/inheritance review, not calling the composer projection twice. Replaying this snapshot can prove frozen accounting and cross-consumer preservation; it cannot prove C14, genuine source freshness, or zero unresolved request/response definitions.

The only identified archive privacy action is the Waveinflu example redaction under a strict no-PII requirement. The parent W0 package must record its final payload hashes, exact selection list, sanitization receipt, and reproducible command. Those artifacts were not created by this audit.
