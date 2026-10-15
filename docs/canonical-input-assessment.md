# Canonical consumption: input gate and next steps

The target is one complete Runtime canonical producer. This increment only adds
`assess_canonical_inputs(root, facts, source_receipts=..., checked_at=...)` and
fixtures. It neither imports files nor enables production workflows, authorizes
publication, changes consumer pins, or claims complete canonical deployment.

## Independent bindings

The API's deployed, tracked Composer lock will expose `compiler_inputs` on live
`current` with exactly these fields: `protocol_version`,
`bundle_manifest_sha256`, `docs_ref`, `composer_revision`, and
`source_manifest_sha256`. All must match `contracts/manifest.json`. The existing
outer `source_digest` and `compiler_revision` must already match the artifact;
generation remains live publication/receipt state, never immutable bytes. This
is meaningful only when the API emits its own compiled lock and makes freshness
conditional on that match. Copying fields out of the artifact is insufficient.
The producer implementation is separate; missing live bindings fail closed now.

The gate replays the actual saved acquisition, checks strict current-before/after
semantics, and records both exact current hashes and the original receipt hash.
A later formal exporter must repeat these checks, including the live binding;
existing acquisition receipt fields alone do not bind optional current metadata.

`publication_origin.inspect_publication(..., historical=True)` authenticates the
fixed `docs_ref` through existing main ancestry, successful producer run/attempt,
origin, and original formal report artifact checks. Historical verification uses
the original publication clock; it does not renew current source authorization.
The trusted fixed Git pointer's `files_sha256` selects the full schema input set
with the same `formal_input_paths` helper used by bundle export and verification.
Every selected original Git blob is rehashed. Current upstream source membership,
bytes, registry and reviewed policies must match the compiled input exactly;
missing files, extra sources, symlinks, and unsupported overlays fail closed.
Historical compatibility native files are verified at the fixed ref, not compared
to current native output, which legitimately changes with Runtime facts.

Here `root` means the input workspace before import. If metadata projection
changes registry display fields, a later exporter must revalidate the preserved
input view bound to its assessed base and separately validate the resulting
registry. Generated output must not be passed off as the original schema input.
Upstream and reviewed policy bytes remain unchanged by rendering.

No extra upstream inventory or per-run 60 MB bundle download is needed. This does
**not** recompute the full bundle manifest digest from Git: original external
source receipts and derived export attestations are not all Git members. The
independent live lock approves that digest and its Docs/Composer binding; the
trusted bundle exporter establishes the association before build activation.

## Source observation boundary

The gate uses the actual source receipt/attempt packet at the requested assessment
time and returns each original observation without refreshing timestamps. Source
policy errors fail. Old, unknown or failed observations remain old, unknown or
failed even when build pins match. They do not become approved because this
input-association gate passes. The returned scope explicitly excludes current
source authorization and lists the remaining gates.

Provider attribution and expiry are deliberately excluded here. Existing
`source_report` uses native provenance plus coverage provider membership; before
canonical import these could describe the previous graph. Final canonical native
and coverage projection must recompute the existing source scope, failure and
expiry rules before any formal publication can pass. No broader exemption or new
source-review clock is introduced.

## Next implementation boundary

1. Reuse current stage helpers to derive registry, coverage and pending metadata
   from Runtime facts and the imported canonical graph. Current canonical
   `readiness.json` has readiness findings, not a complete registry/coverage
   projection; retaining old metadata is insufficient. Do not recompose schema to
   replace Runtime output or create another endpoint inventory.
2. Copy native and full aggregate original bytes, render YAML losslessly and use
   existing MDX, localization, llms, sales and payment projections. Verify exact
   imported native/aggregate bytes and all projection semantics independently.
3. Add an explicit `actual_publication_graph_and_runtime_canonical` assessment
   with a mandatory `canonical_runtime_import` subgate. Keep the existing offline
   composition evaluation and behavior intact. Candidate/export/origin validation
   must recheck the distinct required subgates, acquisition and final source scope.
   Keep bindings in the already hash-bound formal report, not a new public file.
4. Before enabling that assessment, update Website, MCP and Router receipt
   verifiers to strictly accept the two supported evaluation shapes. MPP separately
   pins Docs verifier code at `5b6736dc...`; update its reviewed lock and workflow
   code ref. A new Docs formal commit does not update that verifier. Preserve the
   current producer job identity and normal publication/notification chain.

## Validation

Run `PYTHONPATH=scripts/tests python -m unittest
scripts.tests.test_canonical_input_assessment scripts.tests.test_schema_input_bundle`.
The tests use real temporary Git commits and actual reader acquisition fixtures;
only external successful GitHub origin authentication is mocked. They reject
missing/different live locks, invalid source provenance, changed schemas/registry/
policies, added or deleted sources, symlinks and overlays. They preserve overdue
and failed source observations and explicitly leave publication gates pending.
No test fabricates production availability of `compiler_inputs`.
