# User contract corrections (2026-10-12)

This candidate changes documentation inputs and publication code only. It does not
change Runtime routes, Profiles, pricing, credentials, or service readiness.

- Mintlify uses `api.examples.defaults: required` and `prefill: true` so the
  existing canonical request examples drive initial samples. A deployed preview
  must still verify the first visible/copied curl for the four reported GETs and
  Exa/Tavily POSTs; configuration alone is not rendering acceptance.
- Large repeated provenance records are interned under
  `info.x-aisa-source-provenance`. Each operation retains scalar identity plus a
  SHA-256 locator. `scripts/source_provenance.py` validates and losslessly
  rehydrates the original record. Composition, retained history, unified output,
  and publication readiness preserve/validate the map. FRED's 32 routes and full
  evidence remain present; the generated JSON is about 1.27 MB instead of 33.94
  MB. This removes redundant size but does not prove the cause of the hosted 404.
- YouTube's success response and referenced schemas come from the official
  SearchAPI YouTube OpenAPI snapshot, whose URL/raw hash are retained. Public
  request parameters, method, path, and error responses are unchanged.
- Six Similarweb response sources use 40 explicit scalar type/null declarations
  from endpoint-matched official pages. The exact leaf declarations and raw page
  hashes are recorded in `source-corrections-20261012.json` and the source record.
  Three `serp_features` fields assert only the proven array-or-null container:
  their element type remains **unconfirmed** because the official nested array
  declaration is incomplete and differs from observed string elements. The field
  description and `x-aisa-schema-status` expose this boundary; no item type is
  invented, and non-array scalars remain invalid.
- Eighteen old US-region response examples are removed from both the response
  sources and legacy mirror (36 copies). No old result is relabeled as WW.
- Exa's obsolete flat customer prices are removed; current pricing/quote remains
  the charge authority, and upstream `costDollars` is clearly separate.
- English and Chinese balance documentation includes available/frozen add-on
  credit and provider-scoped media promo credit, following Runtime's balance
  response and calculation. The illustrative sample arithmetic is checked.

Manual source amendments receive new content hashes. Existing review receipts
must not be reused for new hashes: independent review is recorded against the
immutable source commit before publication. Generated output uses the existing
locked Runtime facts, not an unversioned live merge.

Acceptance still requires the preview checks above, public FRED JSON delivery,
current source receipt validation, normal CI publication, and consumer convergence.
No production acceptance is implied by a local test or generation pass.
