# Consume the acquired Runtime canonical graph

The existing `pull-openapi.yml` workflow selects its path from the completely
verified acquisition. There is no second producer service, endpoint inventory,
schema fetching loop or manual canonical-mode flag.

`runtime_publication.py mode` replays the saved acquisition before returning one
of two values. Fact-only artifacts retain the existing pull, consolidation and
offline candidate checks. Artifacts with a verified canonical role set use the
canonical importer. Corrupt, incomplete or unbound canonical inputs stop the
workflow; they never fall back to local composition.

## Canonical path

1. Select the current assessed Git HEAD and last attributed formal publication.
   Authenticate the latter at its original publication clock and reconstruct
   the fixed schema input view, including verified registry lineage. An expired
   predecessor cannot authorize the new release; it is only historical input
   provenance. New source authorization is checked later from actual evidence.
2. Validate the independently exposed live build lock against the complete
   Runtime acquisition, then reread original member bytes against their hashes.
   Derive coverage, pending and registry from canonical declarations and facts
   through the shared helpers. Enforce the independently reviewed baseline.
3. Project existing pages, locale documents, YAML, llms discovery and sales
   discovery. Native and full aggregate JSON retain the exact producer bytes.
   Canonical page URL disagreement fails rather than rewriting producer hashes.
   All output paths are checked before writing any staging files; no pointer is
   written at this stage. No Composer or aggregate builder is invoked.
4. Run the existing real payment observation and payment discovery generation,
   followed by page reference validation. These steps run for both modes.
5. Run the [formal canonical assessment](canonical-formal-compatibility.md),
   including the final metadata/source scope and expiry. The existing exporter
   independently replays the entire assessment before creating or retaining the
   same-commit pointer. It cannot promote the staging report to a formal receipt.
6. Preserve the existing local commit, original origin/clock, immutable schema
   supply upload, assessed-main CAS push and consumer notification sequence.
   Concurrent main or Runtime movement still blocks the release and retains
   last-good publication. Existing concurrency does not cancel a running producer.

The workflow grants `actions: read` and supplies its existing GitHub token only
where original producer artifacts must be authenticated. No new secret, external
token or service is introduced. The fact-only mode does not acquire new schema
bundle requirements. The canonical mode requires the complete verified graph and
live compiled binding; missing prerequisites are explicit failures.

## Rollout boundary

This workflow change is the actual consumer-path activation. Merge it only after
the compatible formal verifier and all four consumer code paths/pins described in
the handoff are ready. Runtime must expose its deployed build lock independently
and publish the complete canonical graph through the existing artifact mechanism.
Changing a workflow variable cannot make an old or partial artifact canonical.
Do not present a historical fixture as evidence that production prerequisites
already exist.

## Validation

```sh
PYTHONPATH=scripts/tests python -m unittest \
  scripts.tests.test_runtime_publication \
  scripts.tests.test_contract_activation \
  scripts.tests.test_schema_bundle_supply \
  scripts.tests.test_canonical_formal \
  scripts.tests.test_canonical_import
```

Tests use actual fact-only/canonical saved acquisition fixtures, reject corrupt
canonical bytes, verify no fallback or writes on unverified input, require the
reviewed baseline and preserve failure reports. The extracted workflow shell is
executed for both modes, an unknown mode and a failing canonical command: failure
must propagate without executing the old Composer path. Workflow assertions keep
payment, slug validation, export, origin, supply, CAS and notification boundaries.

The separate full historical stage replay calls the actual staging API with the
Composer, old stage and aggregate builder patched to raise if invoked. It uses
real historical 6fb GitHub provenance and original source clocks with a synthetic
future Runtime artifact. Native and aggregate outputs are compared by original
bytes. This is staging validation, not a live payment probe, production publication
or renewed source approval.
The replay passed in 94.642 seconds, preserving all 75 native/aggregate byte
sequences and matching all 4,289 publication files of the separately validated
formal projection. The focused and neighboring suite passed 216 tests.
