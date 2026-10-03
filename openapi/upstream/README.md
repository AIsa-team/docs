# Request contract mirrors

Existing AIsa specifications are imported here as explicit `kind: manual`
transitional request mirrors. Each records its immutable GitHub source URL,
content hash, revision time, converter and `path_space: public`. These are existing
handwritten AIsa contracts, not official upstream specifications. Matching uses
exact effective public paths and methods; no provider-prefix guessing is allowed.

Official provider imports use `kind: provider_openapi` with the original source
URL, acquisition timestamp, content hash and converter. Their paths match the
runtime `x-aisa-upstream-path`. The composer consumes request schema/prose and
success payloads only where runtime explicitly declares passthrough responses.
Exact public-route mirrors may supply the public success payload. Runtime-owned
response contracts always win; provider prices, authentication, response errors,
headers and links cannot override runtime facts. Missing response declarations
are reported separately and never become invented schemas.

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

## Versioned and private sources

Parallel beta events and Cloudsway full search use explicitly labeled historical
primary contracts. Their presence establishes request-document evidence, not
current upstream availability. Keep retirement/404 evidence in the route audit.

The Twitter delete wrapper is derived from the owning service's pinned request
DTO and handler. That source repository is private: its initial acquisition and
revision updates require an authorized repository reader. Routine composition
uses the checked-in mirror and does not require source credentials. The scheduled
refresh skips explicitly pinned private sources and reports them separately, so
they do not block review PRs for public-source updates. Reviewed public mappings
can explicitly opt into automatic refresh through their official converter. A
skipped source is not a fresh verification of the owning service.
