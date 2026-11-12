# Shared generator alignment with PR #334

This dev change adopts the shared generation code from Docs PR #334 at
`5032a4fc6df15d7c21856e71b1cc693502eb5bd4`. It does not merge main, change a
Runtime deployment, or copy production contracts into dev.

The same customer tariff renderer was already present on both branches, but
that did not prove the same generated result. Dev still removed business prices
from reviewed response field tables, retained obsolete supplier billing prose,
and removed price-only localized description fields from the protocol shape.
Its Composer and page binding implementation also preceded main's fixes.

## Shared code boundary

These modules must match the pinned PR version byte for byte:

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

The common `project_surfaces` and `retired_page_references` functions in
`canonical_import.py` also match the PR. Its other functions verify production
canonical acquisitions and are outside this page-generation alignment.

Dev retains its public facts reader, presentation scoping, source-review and
deferral policies, registry/source inputs, and deployment workflows. Production
canonical acquisition, release authentication and publication remain separate.
The new optional unreviewed-composition support stays disabled in dev's normal
generation context; missing sources are not made publishable by this change.
Retirement support uses each environment's own existing policy files.

Generated MDX and OpenAPI files are produced by the normal dev build after merge.
They are not edited or committed in the generator PR.

## Acceptance

Run the new regressions together with the existing real entrypoint tests:

```sh
PYTHONPATH=scripts:scripts/tests python -m unittest \
  scripts.tests.test_shared_generator_alignment \
  scripts.tests.test_provider_response_compaction \
  scripts.tests.test_page_identity_cache \
  scripts.tests.test_pricing_generation \
  scripts.tests.test_dev_customer_pricing \
  scripts.tests.test_dev_pricing_generation
```

They cover business-price preservation in both languages, obsolete supplier
claims, stable localized protocol shape, rechecking cross-field constraints,
recursive response graphs, source provenance, stable page identities, and the
18 customer-pricing declarations. The full offline suite, frozen acceptance
inputs, dev generation and deployment are also required before promotion.

Compare the shared file bytes and the two canonical projection functions
against the pinned reference. Run the common staging entrypoint from both
versions against the same saved dev facts and page inputs, then regenerate the
dev output to check stability. Equality of price renderer tests alone is not
evidence that the surrounding generator matches.
