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
| Operations with revised text | 5,314 |
| Existing prose preserved | 1,154 |
| Guarded Runtime prose identities | 5,290 |
| Static source operations amended | 1,867 |
| Static source files amended | 43 |

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

For 900 operations the available contract only establishes a purpose, without
usable named request or response fields. Their wording stays within that declared
purpose and provider context. This is complete coverage of the available evidence,
not a claim of 900 newly verified upstream schemas or individual live execution.
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
a separate test proves that no non-prose declaration changed in any of 43 files.

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
