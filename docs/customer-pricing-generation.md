# Customer pricing generation

Fix API-page pricing in the shared generator. Generated MDX is an output of the
normal publication workflow, not the source of pricing rules.

`customer_price_presentation.py` interprets published customer tariffs and
request estimates. `readable_contract_notes.py` writes one customer pricing
paragraph in the cost section. Supplier rates, credit units and multipliers
stay out of that paragraph and the expanded request declaration.

`pricing_prose.clean_page` removes obsolete generated summaries from page
frontmatter and body before adding the current managed block. Free and
unpublished summaries are removed too, even when they contain no amount.
Fenced examples are preserved. Composer cleans operation descriptions before
hashing, while localization uses the same presentation rules.

Credit-only supplier tariffs are cleaned too, including parameter descriptions,
cache notes and price-table cells. Cleaning removes the supplier amounts and
arithmetic while retaining parameter bounds, opt-in switches, cache metadata and
failure/billing conditions. Business credit balances, reviewed payload fields,
examples and machine pricing metadata remain data. Frozen real descriptions
and stage/canonical projection regressions cover this distinction.

Both `pull_openapi.stage` and `canonical_import.project_surfaces` use the shared
page renderer. The canonical consumer preserves verified native JSON bytes;
the producer must run the updated Composer to remove old native-description
summaries. A page-renderer change alone is not evidence that the publisher has
adopted a new compiler or that a deployed site has refreshed.

The dev workflow forces generation after script changes and commits the
validated outputs. Verify its generated commit and Mintlify deployment before
promoting the generator to production. Do not merge generated dev contracts or
dev deployment settings into main.

## Regression checks

```sh
PYTHONPATH=scripts:scripts/tests python -m unittest \
  scripts.tests.test_pricing_generation \
  scripts.tests.test_customer_price_presentation \
  scripts.tests.test_pricing_prose \
  scripts.tests.test_readable_contract_notes
```

The integration tests start with stale English and Chinese pages for 18 tariff
declarations, exercise actual composition and canonical projection, regenerate
twice, and change a source price. They require stable output, updated prices,
unchanged machine pricing metadata and no legacy pricing markers. Dev also
tests these families through `sync_dev_runtime.acquire` and `generate`.
