# Complete tool prose coverage

This change covers the complete union of the checked-in Docs inventory at
`5ebac5c42f5c9d5bb1a725f6c1e7376c39e829d0` and the public Runtime metadata
captured on 2026-11-12. All 560 Runtime provider reads completed successfully.
The coverage unit is a public operation; grouped Runtime identities can expand
into more than one HTTP method. Provider-file count and Runtime-provider count
therefore differ.

| Coverage | Count |
|---|---:|
| Public operations assessed | 6,468 |
| Operations with revised text | 5,630 |
| Existing prose preserved | 838 |
| Guarded Runtime prose identities | 5,596 |
| Static source operations amended | 2,089 |
| Static source files amended | 44 |

The static and dynamic counts overlap; do not add them as independent tools.
`tool-prose-coverage-20261112.csv` contains every operation, old/new prose,
source identity, disposition and delivery location. CSV display cells normalize trailing line whitespace; exact source bytes remain identified by their hashes and amendment records. The adjacent JSON contains
per-provider counts. `tool-prose-static-gemini.json` records the standalone Gemini change; `tool-prose-changes-20261112.json` records the exact static
source amendments and their evidence.

## Wording rules and limits

Readable titles and substantive descriptions are retained. Machine-style titles
use the existing Purpose statement when available and retain platform/API-surface
context. Short ambiguous titles gain the existing provider display name.
Missing or summary-only descriptions include the existing purpose plus declared
required inputs, important optional inputs, constraints and response field names.
Supplier examples and credentials are not copied. Optional body properties remain
conditional. Generic response envelopes do not become invented domain fields.
Long original text, caveats, pagination, login-cookie and account requirements
are retained in full; concise purpose/input guidance is placed first.

The follow-up fixes grouped title repetitions (including all 15 AgentMail cases),
array items, conditional schema alternatives, allOf requirements, operation-level
parameter overrides and named response fields inside data envelopes. 446 brief
existing descriptions gain missing required-input guidance while retaining their
original text. Relative to the preceding revision, 311 additional operations change.

Of the previous 903 purpose-only operations, 26 now use additional declared schema
detail and 865 use exactly bound source descriptions: 143 from the pinned Treg
revision and 722 from 264 public Alexandria provider pages. The excerpts, exact
public identity, original title, source URL and captured source SHA-256 are in
`scripts/data/tool-prose-purpose-evidence.json`. This is capability documentation,
not new request/response schema approval or live API verification. Treg excerpts
omit two upstream billing statements that do not establish AIsa prices.

12 operations still have only their declared purpose; they remain explicitly
marked `bounded_to_declared_purpose` in the CSV and JSON. Their missing detailed
source evidence is not replaced with invented parameters or output guarantees.
The process combines deterministic contract extraction and explicit individual
wording; it is not a claim that every tool received independent manual review.

A shared ANY Runtime identity receives explicitly labeled GET and POST sections
when its published methods have different input guidance. The 11 independently
maintained/retained static operations keep their existing prose. All future
operator prose edits take precedence over the Runtime amendment. Its request,
response and referenced-schema fingerprint must also match the captured Runtime
structure. Docs mirror changes need their normal independent source review.

## Source ownership and publication

The AIsaServices companion changes generated contract text, not endpoint database
rows or management UI text. This Docs PR changes manual source inputs and keeps
captured Composio descriptions during import. Runtime description precedence
remains intact. Source acquisition clocks and original provenance are preserved;
the new prose layer records its original document hash and exact change manifest.
Historical schema tests validate and undo that layer before their older checks;
a separate test proves that no non-prose declaration changed in any of 44 files.

The standalone, unbound Gemini contract also receives its missing description, with an exact non-prose hash check. Its Chinese copy, translation memory, aggregate OpenAPI and derived catalog hashes are synchronized. Other generated provider JSON/pages are not rewritten. The normal reviewed source
bundle, Runtime contract publication and Docs projection are still required for
customer-facing adoption. Source-review receipts, production data, prices,
request/response schemas and routing are not modified by this work. Local tests
are not deployment or search ranking evidence.

## Reproduction and validation

```sh
python3 scripts/audit_tool_prose.py --output /tmp/tool-prose-audit
python3 scripts/prepare_tool_prose.py --docs-ref 5ebac5c42f5c9d5bb1a725f6c1e7376c39e829d0 \
  --runtime-dir /path/to/public-runtime-capture \
  --services-root /path/to/AIsaServices --output /tmp/tool-prose-prepared
PYTHONPATH=scripts python3 -m unittest discover -s scripts/tests -q
```

In AIsaServices, `scripts/tool-prose-fingerprints` adds the exact fingerprint using
the same implementation as generation. Full captured-catalog replay is available
through `AISA_PROSE_RUNTIME_SNAPSHOT` in `packages/apicontract` tests. Tests cover
later prose edits, schema drift, reference cycles, identity mismatches, no changes
to non-prose fields and facts-hash updates.

CI failures must be resolved or reported without weakening publication checks.
The response comparison resolves discriminator mapping targets and recursive
references by contract rather than generated component namespace. This avoids a
false Supadata mismatch after prose changes the source hash; changed targets and
constraints still fail validation.

The official Polymarket Data v1 specification URL currently returns 404; its
source-maintenance gate remains blocking. The official documentation index now
links a v2 specification, which is not evidence that the existing v1 contract is
unchanged. No source-review receipt is invented and no schema migration is
included in this prose change.

## Review follow-up and publication limits

The preparation step removes U+200B/U+200C/U+200D/U+FEFF export artifacts and
rejects the exact pricing placeholder `默认价格配置` as useful prose. Explicit
Runtime `Free` statements survive the known `See the published pricing`
projection substitution; no prices or billing rules change.

The companion AIsaServices PR now includes Social/Commerce PR #1278. Those
newer code-owned descriptions win over this captured prose amendment through
the existing exact-before guard. The CSV remains the dated capture comparison,
not a claim that old snapshot text overrides the merged resource descriptions.

`response_contract` is a distinct checker fix in commit cad0b7de3, retained here
because changing a source prose hash changes generated component namespaces.
It warrants specific review. Tests reject a changed discriminator mapping key,
a different mapping target, altered target constraints, missing/external targets,
and handle recursive reference graphs; namespace-only renames compare equal.

Composio conversion produces an offline source-review candidate, not published
or trusted agent policy. It creates zero review receipts. Imported prose and
schema descriptions remain external data; source hashing, independent review,
and publication qualification still apply. Keyword stripping or Markdown
quotation cannot make hostile text inert and would corrupt legitimate API
instructions. No such security guarantee is claimed. Agent consumers must treat
tool documentation as data subordinate to their own trusted instructions.

Only Gemini's standalone published translation is changed in this PR. Other
changes are source inputs. On future projection `pull_openapi.py` explicitly
allows untranslated fields and uses the new English source for missing exact
source-string translations; it does not reuse stale translations. Strict
`runtime_localize_openapi_zh.py generate` instead fails on missing translations.
Completing Chinese translations is required before claiming Chinese coverage.

Internal audit files are explicitly excluded by `.mintignore`; GitHub retains
the full review trail. Polymarket source-maintenance evidence continues to block
formal publication; no approval or successful acquisition is fabricated.

## Remaining source-detail gaps

These are the complete 12 purpose-only cases after the follow-up. A richer public contract or exact-bound source description is still required.

| Provider | Operation |
|---|---|
| api-ninjas | `api-ninjas.bitcoin` |
| hackernews | `hackernews.maxitem` |
| hackernews | `hackernews.updates` |
| job-search | `job-search.glassdoor-realtime-list-salary-filters` |
| twelvedata | `twelvedata.etfs-type` |
| twelvedata | `twelvedata.get-technical-indicators-list` |
| youtube | `youtube.shorts.trending` |
| financial | `any_financial_apis_v1_financial_crypto_prices` |
| financial | `any_financial_apis_v1_financial_crypto_prices_snapshot` |
| financial | `getEarningsPressReleases` |
| financial | `getSegmentedRevenues` |
| financial | `getInstitutionalOwnership` |
