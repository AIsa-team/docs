# Shared generator alignment for PR #334

PR #334 consolidates the customer-pricing fixes and subsequent reviewed dev
fixes against dev commit `8221cf5a83721f7c05012ad5b603078af3c9199f`.
The main baseline for this consolidation is
`a95a9bef6b2f9e0290e05c2b9af955065ddaf3ea`.
These pins describe code and source-input alignment, not a production rollout.

## Consolidated fixes

| Dev PRs | Behavior in #334 |
| --- | --- |
| #332, #333, #336, #340, #345 | Customer tariff classification; archived unpriced operations; removal of obsolete English and Chinese descriptions and pricing markers; preservation of business-price response fields and machine declarations; shared composition and page projection. These were already present in #334. |
| #346 | Reviewed Alexandria request/response sources and Firecrawl passthrough response schemas, with provenance, review evidence and schema/example regressions. |
| #347 | Runtime closed request bodies stay closed, including nested and empty objects. Required supplier inputs rejected by Runtime fail composition. Optional preserved-navigation validation is available without changing main's default navigation mode. |
| #348 | Disabled historical pricing containing only `cost_tier`/`model` labels renders the archive explanation in both languages. Enabled unknown declarations remain unknown; real tariffs remain intact. The verified reader's 64 MiB aggregate bound was already present on main. |
| #349 | A bounded 1,024-member canonical inventory supports the complete catalog. Tests cover a 568-provider release, the exact inventory limit, overflow rejection and independent file-size limits. |
| #350 | Five Alexandria schema corrections use the recorded production evidence. Composition preserves the reviewed exclusion between two supplier-only forwarded fields while rejecting conflicts with Runtime-owned fields or rules. |

The twelve source files from #346/#350 were imported from the pinned dev bytes.
Final review replaced four recorded production response examples with synthetic
illustrations in three Alexandria files, as required by README. Their schemas
and recorded response digests are unchanged. The sanitization review records
old/new hashes; three new receipts cover the revised examples. The eleven
original imported receipts and all unrelated main receipts/observations are
preserved. Nine source files still match dev byte for byte. The production
requests described in the imported review records were performed during those
reviews, not again during consolidation.

## Shared code boundary

These modules match the pinned dev version byte for byte, except that
`runtime_consolidate_openapi.py` now writes the aggregate JSON compactly to stay
within GitHub's single-file limit. `pull_openapi.py` also restores the temporary
operation binding when staging an archived alias, so retirement is reapplied
before writing and repeated generation cannot add request/pricing blocks back.
Both small exceptions have regressions; the JSON values and published machine
contracts are unchanged:

- `scripts/customer_price_presentation.py`
- `scripts/readable_contract_notes.py`
- `scripts/pricing_prose.py`
- `scripts/runtime_localize_openapi_zh.py`
- `scripts/compose_openapi.py`
- `scripts/pull_openapi.py`
- `scripts/runtime_registry.py`
- `scripts/runtime_consolidate_openapi.py`
- `scripts/contract_readiness.py`
- `scripts/publication_surface.py`
- `scripts/human_api_retirements.py`
- `scripts/retirement_pages.py`
- `scripts/runtime_contract_artifact.py`
- `scripts/fetch_runtime_release.py`

The shared `project_surfaces` and `retired_page_references` functions in
`canonical_import.py` also match. Its remaining functions enforce production
acquisition and publication rules. `regroup_api_reference.py` includes dev's
optional preserved-navigation validation while retaining main's additional
`reference-contracts` page-binding support. Main-only regression tests are
retained alongside the added dev regressions.

## Environment-specific fixes

The dev preview fixes from #348/#349 remain in `sync_dev_runtime.py` and the dev
workflow: acquiring production facts for dev, retaining production API origins
with dev schema links, distinguishing absent/unverified references from disabled
operations, removing stale dev notices, normalizing retained history before
hashing when switching sources, and forcing generation when the source changes.
Main does not invoke that preview entrypoint. Copying it or dev's generated
outputs into main would not exercise main's canonical publication path.

Main keeps its own workflows, deployment settings, source authorization policy
and formal publication receipts. After the initial CI failure, the complete PR
candidate is regenerated through the shared Composer and page renderer, including
its navigation, discovery catalogs and aggregates. These are reviewed candidate
outputs, not a formal publication. The reviewed schema-input context now includes
the complete existing source-evidence packet for these sources. This PR does not
merge the dev branch wholesale or modify a Runtime deployment.

## Acceptance and rollout boundary

Run the full offline suite and existing frozen-input/catalog acceptance checks.
The focused regressions include:

```sh
PYTHONPATH=scripts:scripts/tests python -m unittest \
  scripts.tests.test_pricing_generation \
  scripts.tests.test_customer_price_presentation \
  scripts.tests.test_pricing_prose \
  scripts.tests.test_readable_contract_notes \
  scripts.tests.test_shared_generator_alignment \
  scripts.tests.test_runtime_contracts \
  scripts.tests.test_contract_readiness \
  scripts.tests.test_provider_contract_sources \
  scripts.tests.test_alexandria_production_schemas \
  scripts.tests.test_fetch_runtime_release \
  scripts.tests.test_runtime_contract_artifact \
  scripts.tests.test_api_nav_groups
```

Pricing integration tests exercise composition and canonical page projection for
18 declarations, repeated generation and changed prices. Source regressions
check 2,063 Alexandria bindings, their schema/examples, four Firecrawl response
sources and the five separately reviewed Alexandria operations.

The production canonical consumer preserves verified native JSON bytes. Its
producer must adopt the updated Composer and source inputs before old native
descriptions can disappear from production. A green offline suite or dev's
raw-facts preview cannot prove that adoption. Adding reviewed sources also
activates the existing artifact-readiness check; do not bypass it or manufacture
publication receipts. PR #334 is ready for review at the author's request; merge
and production publication remain gated by their applicable acceptance checks.

The four dev catalog-identity conflicts, seven retained references outside the
raw-provider index and two Adyntel operations without Runtime reference estimates
are separate observed limitations, not fixes claimed by this consolidation.
