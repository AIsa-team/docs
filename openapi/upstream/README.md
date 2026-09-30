# Request contract mirrors

Existing AIsa specifications are imported here as explicit `kind: manual`
transitional request mirrors. Each records its immutable GitHub source URL,
content hash, revision time, converter and `path_space: public`. These are existing
handwritten AIsa contracts, not official upstream specifications. Matching uses
exact effective public paths and methods; no provider-prefix guessing is allowed.

Official provider imports use `kind: provider_openapi` with the original source
URL, acquisition timestamp, content hash and converter. Their paths match the
runtime `x-aisa-upstream-path`. The composer consumes request schema/prose only;
provider prices, authentication and response errors cannot override runtime facts.

Re-import existing docs explicitly with `scripts/import_existing_contracts.py`.
Do not replace these frozen inputs with newly generated outputs. Missing or
unsupported schemas remain visible in coverage/pending. No scheduled unreviewed
schema refresh is performed by the contract puller.

## Multiple operations at one upstream path

When a provider multiplexes operations at the same upstream path (for example,
SearchAPI uses a caller-supplied `engine`), a reviewed source entry may declare
`public_paths` in `openapi/registry.yaml`. This selects the official schema for
that public operation; it does not add a runtime default or change routing.
The selected source must still match the real upstream path and any runtime
selector. Required provider query parameters remain required caller inputs;
source suggestions are examples unless runtime declares a default. The source
binding participates in the document hash.

Airbnb and eBay search explicitly require callers to send `engine=airbnb` and
`engine=ebay_search`, respectively. These contracts describe those engine modes;
they do not claim the passthrough runtime rejects other engine values. The
runtime's authentication and charging rules remain unchanged.

A reviewed public mirror for a private wrapper binding may record
`upstream_path_sha256` in its source metadata. The composer verifies that digest
against runtime facts and reports a changed binding instead of applying the old
schema to a newly routed service. The private path itself stays out of the mirror.
