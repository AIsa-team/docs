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
