# Keepa response fields on the human reference pages

The response sources registered in #362 were not connected to the website:
all 26 Keepa pages still selected the older formal `openapi/keepa.json` or
its Chinese counterpart, where successful responses had empty schemas.

This update uses the existing [human reference publication boundary](../production-reference-pages.md).
The 13 response contracts are composed from the already reviewed sources and
the published Keepa facts, then projected to `reference-contracts/` using
`sync_prod_runtime_docs.publication_outputs`. The existing page generator
preserves the page URLs, identities, request declarations and navigation.

The public immutable facts, native document and manifest were downloaded and
checked against the same fresh Runtime current pointer before and after the
acquisition. The facts exactly match `keepa-response-review.json`; the native
document exactly matches the pre-update formal Keepa document. This is scoped
evidence for the existing Keepa endpoints, not a new private catalog snapshot
or a complete formal contract publication. Pins and output hashes are recorded
in `keepa-response-pages.json`.

Generation uses `runtime_registry.combine_facts`, the existing response-source
loader and `compose_openapi.compose`, followed by `pull_openapi.generate_pages`
and the existing human-reference output projection. Only `responses`,
`x-aisa-response-source` and `x-aisa-review` differ between the old and new
operations. Default error responses and every request, pricing, routing and
authentication declaration are preserved. Formal exports and receipts remain
byte-identical; their separate Runtime input promotion is still pending.

Validation:

```sh
PYTHONPATH=scripts/tests python -m unittest scripts.tests.test_keepa_response_sources scripts.tests.test_prod_runtime_docs
python scripts/check_nav_integrity.py
python scripts/validate_runtime_api_reference_slugs.py --generated-only
python scripts/validate_prod_reference_pages.py
```

The page-binding regression failed on all 26 original pages and passes with
the new references. Both new files also pass OpenAPI 3.1 validation. Deployment
and the rendered website must be checked separately after merging.
