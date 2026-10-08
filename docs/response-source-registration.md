# Response source registration

The 26 JSON files named `openapi/upstream/response-*.json` are actual inputs to
`runtime_registry.public_mirror_index`, not extra response facts or published
OpenAPI outputs. They register 25 existing public success declarations (20
Similarweb, 4 Firecrawl, 1 Twitter batch) and the official typed Similarweb
segments response. No registry provider entry is needed for public mirrors.

`response-source-registration.json` binds each file to the previously prepared
candidate byte hash and preserves its source URL/content hash and exact upstream
origin/path digests. Only source ownership and refresh policy metadata was added.
Schemas, public routes, methods, transport pins and original provenance are
unchanged. Segments uses manual review, since this static converter input has no
automatic acquisition path. Independent declaration reviews and attributed
receipts are included below; publication approval remains separate.

These routes already have explicit GET/POST methods and runtime-owned requests
in the captured read-only metadata. No production `contract_json`, endpoint
`config_json`, Profile revision/reference or identity needs changing for response
selection. The new Runtime producer computes its response transport descriptors
from the existing binding; the Docs composer matches the registered source by
public route, method, origin hash and full executor path hash. Request, identity
and pricing authority remain with Runtime. A missing or different descriptor
leaves response debt open.

Twitter post remains excluded: its current immutable Profile uses `ANY` and a
response-only source cannot establish POST request-method authority. Do not
change its Profile method, rebind it, or remove this guard to use the candidate.
The owning route provides a possible independent method source for separate
review; its dynamic request body is not a typed request schema.

The independent review checked pinned raw source evidence and issued the normal
hash/policy-bound declaration receipts. The remaining step is to compose against
untouched facts from the new Runtime producer for the actual
production inventory, retaining all mismatches. The available W0 facts predate
these descriptors; the earlier derived shadow inputs are not current facts and
were not replayed for this change. The empty staging publication does not prove
these production routes.

Local verification covers strict OpenAPI validity of all 26 input documents,
actual source-loader membership, response-only request exclusion, policy validity,
and unchanged candidate schemas/transport pins. It does not claim current-facts
composition, publication, deployment or wire replay.

## Independent review completion

The 26 declarations now have hash/policy-bound attributed receipts in
`response-source-review-receipts.json`, backed by immutable review commit
`b90226fd6580bea02cd13b6048ce50ac65e97499`. The historical 25 retain exactly their published success schemas;
Segments was independently fetched and regenerated from current official typed
documentation. Use `--source-receipts docs/response-source-review-receipts.json`
when assessing this candidate. This explicit input does not replace other source
receipts or bypass the current Runtime/full-catalog publication gates.
