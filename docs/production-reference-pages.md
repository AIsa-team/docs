# Updating production API reference pages

Production reference pages use the existing dev page-generation approach: the
Runtime supplies the execution facts, the existing Composer supplies only
verified parameter descriptions, and missing descriptions remain pending.
A successful page update is not a complete formal contract publication.

Production's public `/info/openapi.json` currently serves its last immutable
formal release when `CONTRACT_PUBLICATION_SERVE_ENABLED` is enabled. It can lag
the active catalog. Do not copy dev's public acquisition step or disable the
production publication flags just to obtain newer facts.

## Acquire and verify the production snapshot

Use the existing `aisa-infra` read-only `integration-catalog-export.yml` workflow
with `kind=publication` and the exact running Services source SHA. It reads
`/internal/api-contract/source`, exports one snapshot from a revision-pinned API
Pod, and verifies that the source remains unchanged. Verify the workflow source,
run attempt, artifact digest and export receipt before using its output.

Materialize the original DTO with the existing Go `PublicationSnapshot`
validator. Preserve the original file bytes and resulting sorted `snapshot.json`
envelope. Record its SHA256, generation, source digest and compiler revision.
Never edit these pins or facts to make a candidate pass.

Keep an operator-verified acquisition observation with the workflow run and
attempt, workflow source revision, build window containing acquisition, artifact digest, and
these same four pins. The optional `--acquisition-receipt` attaches this limited
production observation to the page receipt; it does not upgrade the offline
snapshot adapter binding into formal release approval.

## Generate and review

Run `scripts/sync_prod_runtime_docs.py` with the verified materialized directory
and the four independent pins, for example:

```bash
python scripts/sync_prod_runtime_docs.py \
  --snapshot-dir /path/to/verified-production-snapshot \
  --snapshot-sha256 "$SNAPSHOT_SHA256" \
  --generation "$SNAPSHOT_GENERATION" \
  --source-digest "$SNAPSHOT_SOURCE_DIGEST" \
  --compiler-revision "$SERVICES_REVISION" \
  --acquisition-receipt /path/to/verified-export-observation.json \
  --write --report /path/to/private-generation-report.json
```

The generator verifies all snapshot members and hashes, composes in a private
workspace, preserves the existing navigation, and checks English and Chinese
page references against their local schema, path, method and operation identity.
It does not call suppliers, use API keys, or acquire facts from development.

Review the generated diff with this output allowlist:

- `reference-contracts/*.json` and `reference-contracts/zh/*.json`;
- `api-reference/**/*.mdx` and `zh/api-reference/**/*.mdx`;
- `docs.json` and `docs/prod-runtime.json`.

The `reference-contracts` directory serves the human reference pages' local
OpenAPI definitions. It is outside `openapi/**`, so the legacy OpenAPI sync and
formal consumer workflows are not triggered by these generated definitions.
The report declares `formal_publication: false` and retains partial/pending
status. Historical pages retain user-readable notices where current parameter
details are not yet verified. Missing definitions are never invented.

Keep `openapi.yaml`, `openapi/**`, `docs/publication/**`, existing formal receipts,
and sales-catalog exports byte-identical. Updating human pages changes the
current checkout's presentation surface; it does not create a new same-commit
formal receipt. Formal release verification remains bound to the existing release-origin
commit; current-head consumers continue reading the unchanged formal exports
and evidence.

Merge the reviewed page candidate through the normal Docs main website release.
Do not invoke `dispatch-contract-consumers`, update Runtime `current`, or label
this candidate a formal contract release. Continue missing-source work through
the existing formal publication process separately.
