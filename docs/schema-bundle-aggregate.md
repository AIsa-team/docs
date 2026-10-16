# Offline complete JSON shadow, with presentation inputs

Schema bundle v2 adds a reviewed presentation input so the existing Composer
and existing aggregate consolidator can produce complete OpenAPI JSON offline.
This does not connect a worker, change production workflows, publish `current`,
renew source evidence, or complete W4 production ownership migration.

## Input and compatibility

The exporter defaults to v1, with unchanged output bytes. Select v2 explicitly:

```sh
python scripts/export_schema_input_bundle.py \
  --repo . --docs-ref <full-frozen-docs-sha> \
  --baseline-ref 78ef376841ead8cde10a79651958790be5a0531c \
  --source-receipts /trusted/original-source-reviews.json \
  --bundle-version 2 --output /artifacts/new-schema-bundle
```

Version 2 retains the original manifest fields and authority declaration, sets
`schema_version: 2`, and requires one additional member:
`presentation/page-bindings.json`, role `historical_presentation_bindings`.
Version 1 rejects that member. Both versions retain the exact independent
baseline, original schema/source receipts, original clocks, byte limits, and
external manifest-digest/Docs-ref trust requirements.

The presentation member has `schema_version: 1`, `docs_ref`,
`scope: historical_presentation_only_not_route_price_or_availability_authority`,
and a path-sorted `pages` array. Every row contains `path`, `sha256`, and
`binding`. A binding is either null for an examined page without an OpenAPI
reference, or exactly `{spec, method, path, operation_id}`. Paths include the
original `api-reference/...mdx` filename; methods are lowercase. There are no
prices, schemas, capabilities, execution permissions, or invented routes in
this input.

The exporter reads actual original MDX from the pinned Git commit, verifies its
hash against that commit's formal publication pointer, uses the shared existing
OpenAPI reference parser, and checks any explicit frontmatter operation ID
against the native canonical ID. Missing IDs on existing legacy pages use the
already declared native operation. No current working-tree MDX is read.

Offline verification checks the exact formal English API-page file/hash set,
legal operation references and IDs, duplicate/unsafe paths, and complete
coverage of the bundle's historical native operations. For native operations
with an existing documentation URL, the last sorted bound page must reproduce
that URL. This historical completeness check does not require a future new
Runtime operation to have a historical page.

Original MDX bytes are **not included**. A recorded page hash alone cannot
prove that the unavailable MDX contained the claimed binding. That association
comes from the trusted exporter and independently trusted manifest digest, not
an offline MDX-content replay. This matters particularly for the nine legacy
operations without native URLs. Supplying a newly computed digest from an
untrusted modified package does not supply authentication.

## Shared composition and output

Run the same `shadow_compile_bundle.py` CLI documented in
`schema-bundle-shadow.md`, passing the independently pinned v2 bundle digest.
Runtime acquisition receipt, manifest, closed provider graph, category binding,
and original clocks retain their existing checks. All private inputs are made
from verified bytes. No Git, network acquisition, or source review occurs.

The native page selector retains every bound historical page by canonical ID.
Provider/path moves retain those pages. Native primary links use the last
sorted page; aggregate links use the first, matching their existing production
rules. Genuinely new operations use the same shared slug/fallback selector as
the production page writer. Presentation mappings never create operations.

`build_unified_spec(root=..., page_links=...)` now accepts an explicit private
root and map. Its default production behavior remains unchanged. Shadow writes
the actual freshly composed native documents and final staged registry into
that private root, then calls the existing consolidator, x402 annotations,
mirror removal, and reference checks. It does not copy aggregation rules or
substitute the old input registry for updated Runtime display metadata.

V2 shadow output sets `schema_version: 2` and
`kind: aisa-offline-shadow-contract-graph`. It retains the existing explicit
offline/non-publication scope, native documents, readiness report, input
bindings, and sorted file hashes/sizes. It additionally contains
`aggregate/openapi.json`, sets `aggregate_generated: true` and
`aggregate_gap: null`; `pages_generated` remains false. The JSON is canonical
UTF-8 with a final newline. No YAML, locale, llms, MDX, or payment-discovery
output role is added. Old v1-only consumers must reject this version until
they explicitly support it.

V1 shadow retains its original schema version, native-only kind, output paths,
and explicit aggregate gap. Existing historical IDs without native URLs still
cannot migrate into composed providers without the missing presentation input.

## Validation

```sh
python -m unittest scripts.tests.test_presentation_page_bindings \
  scripts.tests.test_shadow_compile_bundle scripts.tests.test_schema_input_bundle
```

Tests cover actual source-byte/hash and frontmatter-ID disagreement, full page
inventory, invalid/missing/duplicate bindings, immutable native primary links,
first/last multi-page behavior, new IDs, provider/path moves, and an explicit
aggregator input that cannot scan MDX or alter the global production root.

The fixed 6fb export contains 207 members, 60,967,770 member bytes, and all
2,009 English API-page files (2,007 operation pages and two unbound pages).
Its manifest digest is
`17590e3c917bce9467d250e5abfb006bf828f62ad0d3e96d6e33929c89a65c31`.
Two exports matched. Re-exporting the default v1 still produced the original
`c8f2ceda7de703795d9577df5355cff74d1d11c1cf644a13d55337e621de941b` digest.

An actual v2 run with network and subprocess audit hooks forbidden reproduced
all 74 complete native documents and the full 2,007-operation aggregate from
fixed 6fb without filtering any native field. Aggregate JSON is 18,761,326 bytes
including its final newline. This is an offline equivalence result, not current
source freshness, live provider execution, or worker deployment acceptance.

Two final v2 shadow runs produced identical bytes for all 77 output files,
including manifest digest
`8ce3b3c1a5188dd65a6f41a889d6619203d974787fa3e1a6648829044f8efdca`.
They took about 51 seconds each; the acceptance process peak RSS was about
1.33 GiB including full-document comparison, not an isolated compiler measure.

A synthetic price-only fixture changed the Ahrefs domain-rating estimate from
0.08 to 0.08123 while preserving every schema-bundle byte. Only the Ahrefs native
document changed. In the full aggregate, the only changed fields were that
operation's estimate and generated price description plus three derived
provider hashes. This demonstrates new Runtime facts reaching the full output;
it does not claim the synthetic fixture is a genuine acquired Runtime release.
