# Canonical import: candidate projection and validation

`scripts/canonical_import.py` implements the next candidate-only layer after
[canonical input assessment](canonical-input-assessment.md). It does not select
the production workflow path, publish a pointer, change consumer verifier pins,
or authorize a release. The existing production composition path remains the
default. The new evaluation is deliberately not accepted by the existing formal
exporter or receipt verifiers.

## Data flow and authority

1. `schema_input_view_files(repository, current_view, docs_ref, previous_ref)`
   authenticates the previous formal publication with the existing GitHub origin
   verifier. It checks the current native graph and registry against that exact
   publication's original Git bytes and manifest hashes. It selects frozen schema
   inputs with the same `formal_input_paths` helper as bundle export.
2. The caller creates a private input view from those fixed bytes. The input gate
   accepts a separate `repository` for Git provenance; its default remains the
   original workspace. It authenticates the compiled bundle's Docs ref, checks
   the API's independent live `compiler_inputs`, replays the saved acquisition,
   and preserves original source observations. The full bundle hash is approved
   by the independent deployed lock; it is not recomputed from Git alone.
3. `project_metadata` uses those fixed inputs, verified Runtime facts/category,
   the canonical native graph and producer readiness. It reuses registry
   discovery, grouped facts, coverage, response gaps, mirror attribution and
   legacy-row helpers. It never calls the Composer and never obtains new scope,
   pending state or source authorization from old coverage or pending files.
4. `project_surfaces` returns a relative-path-to-bytes mapping for a separate
   candidate workspace. It copies native and full aggregate JSON bytes exactly,
   uses existing MDX and locale projection, and renders YAML, llms discovery and
   sales discovery with existing helpers. Existing page selection must agree
   with canonical page URLs; a mismatch fails instead of changing producer links
   or hashes. Historical manual prose and locale aliases use the existing rules.
5. `assess_canonical_candidate` repeats the input checks, rereads original
   acquisition members against their verified hashes, derives metadata, and
   validates the candidate graph. The lower-level projection helpers assume
   verified inputs; they are not independent authorization boundaries.

No import helper downloads upstream schemas or creates a source review. GitHub
origin authentication in the high-level gate uses the existing verifier and may
access GitHub. This is not an offline or no-network authentication claim.

## Successive publications with one fixed bundle

The registry contains both schema configuration and Runtime-derived output.
Comparing its entire current byte sequence with the frozen bundle would reject a
second publication after the first changed a provider title or registered a new
Runtime provider. Ignoring display fields would instead permit arbitrary edits.

The importer reconstructs the only acceptable prior registry from the frozen
configuration plus the authenticated previous native graph. Titles and
descriptions must equal that graph's recorded values. New registrations require
the existing `auto_register` setting and canonical provider, catalog and facts
metadata. Legacy ownership additions are derived from original identities and
prior active canonical ownership with the existing matching rule. The complete
current registry must equal this reconstruction. Grouping, upstream selections,
unknown keys and arbitrary edits to derived fields still fail.

After validating that lineage, the private input view uses the original frozen
registry. The new Runtime graph independently derives the next output registry.
Thus a title or new-provider publication followed by a price-only publication can
reuse the same bundle without treating generated metadata as schema authority.
Changing actual schema configuration requires an updated reviewed input bundle.

## Candidate gates and remaining release work

The candidate evaluation is
`actual_publication_graph_and_runtime_canonical`; its scope is explicitly
`candidate_only_not_accepted_by_production_formal_export`. The report binds exact
native and aggregate hashes, input assessment, previous registry lineage,
original acquisition receipt, fixed reviewed baseline and publication file set.
It checks lossless YAML, llms discovery, sales discovery, managed request and
pricing blocks, locale and page identity rules, and the existing payment catalog.
It does not manufacture fresh payment evidence or regenerate the payment catalog.

The existing `source_report` and `source_expiry` run on the **new candidate native
graph and newly derived coverage**. The real receipt/attempt packet and assessment
clock remain unchanged. Global source failures fail the report; scoped failures
retain their existing provider-expiry behavior. Candidate expiry is labeled as
derived, unpublished authorization, not an active formal release.

Before production activation, the formal candidate/export/origin path must
explicitly accept and recheck this distinct assessment, including final metadata,
source authorization, payment evidence and live acquisition. Website, MCP and
Router receipt verifiers must support both precise evaluation shapes. MPP's
separately pinned Docs verifier code and workflow ref must be updated. A new Docs
main or formal commit alone does not deliver that verifier change. These switches
and consumer pin updates are outside this increment.

## Verification

```sh
PYTHONPATH=scripts/tests python -m unittest \
  scripts.tests.test_canonical_import \
  scripts.tests.test_canonical_input_assessment \
  scripts.tests.test_runtime_contracts \
  scripts.tests.test_publication_surface \
  scripts.tests.test_shadow_compile_bundle \
  scripts.tests.test_internal_publication_snapshot \
  scripts.tests.test_formal_receipt \
  scripts.tests.test_source_governance \
  scripts.tests.test_payment_publication
```

Regressions cover two consecutive publications against unchanged frozen inputs,
new-provider registration, arbitrary registry/schema mutations, old-metadata
poisoning, grouped facts, pending diagnostics, actual source scope and expiry,
page-link disagreement, exact canonical bytes, and acquisition changes after the
input check. Temporary Git fixtures mock only external origin authentication.

The separate full historical replay used fixed Docs
`6fbf9940d876920d7bae05de2e9df5b2f4c0a139`, its actual successful GitHub origin and
original source observations. It retained all 74 native JSON byte sequences and
the 2,007-operation aggregate; the existing publication surface validator checked
1,998 Runtime operations across 45 providers plus existing legacy blocks. All
109 payment operations passed their existing catalog gate. Newly derived coverage
matched the frozen original completely. Pending contents matched with only the
ordering of three retained Agentmail entries normalized.

That replay's future canonical Runtime acquisition and `compiler_inputs` are
synthetic fixture data. Its GitHub origin authentication is real, but it is not a
current Runtime publication, renewed source approval, or production deployment
test. The candidate report is not the capped public `contracts/readiness.json`;
the latter remains the original producer bytes.
