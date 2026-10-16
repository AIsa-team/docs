# Offline native-graph shadow compiler

This W4 component reuses the existing Python Composer with a verified schema
input bundle and a separately pinned, previously acquired Runtime snapshot.
It produces the complete native provider/legacy graph for offline comparison.
It does not connect a worker, change a production compiler, create a formal
publication receipt, renew source reviews, or update `current`.

## CLI and artifact

Use the existing Docs Python environment. All paths below are explicit caller
inputs; the tool does not discover a Git checkout or fetch missing data.

```sh
python scripts/shadow_compile_bundle.py \
  --bundle /inputs/schema-bundle \
  --bundle-sha256 <independently-trusted-bundle-manifest-sha256> \
  --docs-ref <full-frozen-docs-sha> \
  --runtime /inputs/original-runtime-acquisition \
  --artifact-revision <full-runtime-artifact-sha256> \
  --compiler-revision <full-runtime-compiler-sha> \
  --runtime-receipt-sha256 <independently-trusted-acquisition-receipt-sha256> \
  --output /artifacts/new-shadow-directory
```

The Runtime directory is the original output of `fetch_runtime_release.py`,
including `current-before.json`, `current-after.json`, `acquisition-receipt.json`,
`category.json`, `index.json`, and `providers/*.json`. The immutable manifest
hash, every file hash, complete provider/index graph, and existing 8 MiB file /
64 MiB total limits are checked. The unversioned category is separately bound
by the caller-pinned original acquisition receipt. Flat provider duplicates in
the caller directory are never consumed. A private flat facts directory is
created from verified manifest bytes.

The original receipt and before/after `fresh: true` records describe a past
acquisition. They do not prove current freshness. No network revalidation or
new observation timestamp is generated. The package's original source review
clock is preserved and replayed; its review TTL is not renewed. The command
requires independently trusted pins, as described in `schema-input-bundle.md`.

Output must be a new directory under an existing parent. Files are written in
a temporary sibling and atomically renamed only after existing readiness gates
pass. No pre-existing output is replaced. On a failed compile there is no new
result directory. Output contains:

| Path | Meaning |
| --- | --- |
| `native/<name>.json` | Complete native canonical provider or historical legacy document |
| `readiness.json` | Existing Composer readiness result, including reviewed deferrals |
| `manifest.json` | Deterministic shadow inventory, input bindings, hashes, and scope limitations |

The manifest has `schema_version: 1`,
`kind: aisa-offline-shadow-native-graph`,
`scope: existing_composer_offline_shadow_only_not_formal_publication`,
`bundle`, `runtime`, `providers_recomposed`, and a sorted `files` array containing
`path`, `sha256`, and `bytes`. It explicitly declares `pages_generated: false`,
`aggregate_generated: false`, and the aggregate input gap. No `report.json` or
formal receipt is emitted. Standard output is one JSON result with status,
scope, document/provider counts, and manifest SHA-256. A rejected input exits
nonzero. Runtime metrics are kept outside the deterministic artifact.

The `compile_shadow(...)` Python API implements the same boundary as the CLI.
Its composition implementation is shared with the explicitly separate
[internal snapshot shadow adapter](internal-snapshot-shadow.md); this public
entry point retains all original acquisition and independent-pin requirements.
`load_bundle(...)` returns verified bytes and the verified `BundleHistory`;
all composition inputs are materialized privately from these bytes. The shadow
path explicitly supplies history, uses `offline=True` and `with_pages=False`,
and disables reuse of prior documents based on equal `document_hash`. It must
return independently composed provider documents even when their new hashes
match the previous publication. Legacy documents remain part of the complete
native graph under the existing ownership/retirement rules.

## Shared links and production compatibility

`contract_page_links.py` extracts the existing page-selection and link/hash
projection into shared pure functions. The production page writer still reads
its existing MDX references and preserves **all** historical page names in
sorted order, with the last selected page serving as the native primary URL.
New IDs use the existing provider/slug convention. Stable canonical IDs retain
their URLs when paths or provider ownership move. Historical locale aliases
remain identity compatibility and do not create another route.

Shadow compilation obtains primary URL bindings from the verified historical
native documents. It recomputes derived document hashes from the new Composer
hash and selected links; it never copies an old document hash to claim parity.
An existing historical ID without a native URL cannot silently acquire a
guessed URL when it migrates into a composed provider: bundle v1 rejects that
transition until an explicit page inventory input is supported. A genuinely
new ID can use the normal slug rule; uncomposed legacy documents remain intact.

Production `stage(...)` defaults and `acquire(...)` behavior remain unchanged.
Runtime acquisition and offline verification share the same extracted
`validate_release_files` graph check. Neither the production workflow nor its
network/receipt semantics is changed by this component.

## Verified scope and remaining boundary

Two complete offline runs against the frozen 6fb schema bundle and Runtime
generation 864 reproduced all **74 native documents**, including 45 freshly
composed providers. All native JSON values matched, including request/response
schemas, billing parameters, HTTP methods, 1,998 documentation URLs, 45 derived
document hashes, and all 27 historical alias proofs. No link/hash fields were
filtered from the comparison. Both runs generated manifest
`924e4538e4642ec33e3582fe262ba7201bf7f49e1d767d736dfdb43e79aa27d8` and identical
output bytes. Python audit hooks rejected network and subprocess/Git calls
during these tests; the implementation itself needed neither.

Measured complete API runs took 48.619 and 49.237 seconds and peaked at
1,393,380 KiB (about 1.33 GiB) lifetime peak RSS in each independent Python
acceptance process, read at API return before loading the comparison graph.
This includes bundle validation, private inputs, the original/native composed
graphs, and output serialization. It is not an isolated CLI child measurement. This is not the
earlier core-only timing/RSS measurement, a worker capacity guarantee, or a
production deployment measurement.

Focused tests cover new IDs, multiple historical pages and primary selection,
path/provider moves, aliases, missing historical URLs, Runtime pins and hash
tampering, category binding, limits, and unchanged-hash cache masking. Existing
page/identity/acquisition regressions also pass. Independent old/new production
page-writer comparisons covered four combinations of multiple pages, new IDs,
moved paths/providers, and link decoration on/off; native documents, EN/ZH MDX,
and navigation bytes were identical.

This artifact does **not** yet reproduce aggregate OpenAPI JSON/YAML, localized
documents, `llms.txt`, pages, payment discovery, or formal publication metadata.
The current aggregate consolidator still reads an MDX page-reference map;
schema bundle v1 supplies only native primary URLs. Of the current 2,007 page
bindings, 1,998 match native URLs and nine legacy operations have MDX-only URLs.
Completing that boundary needs a reviewed presentation-binding input and an
explicit-input interface to the existing consolidator. It must not introduce
a second consolidation algorithm or infer the missing historical links.

Validation commands:

```sh
PYTHONPATH=scripts/tests python -m unittest \
  scripts.tests.test_shadow_compile_bundle \
  scripts.tests.test_schema_input_bundle \
  scripts.tests.test_fetch_runtime_release \
  scripts.tests.test_identity_compatibility \
  scripts.tests.test_runtime_contracts
```
