# Upstream mirrors

Provider and mixed operations require a reviewed `<provider>.json` OpenAPI mirror.
Its `info.x-aisa-source` must contain `kind` (`provider_openapi` or `manual`),
`url`, `fetched_at`, `content_hash`, and `converter`. The composer never fetches
upstream URLs or external references. Missing or unsupported operations enter
`openapi/pending.json` and are not exposed to consumers.

Mirrors are not populated by copying existing AIsa documentation: that could
reintroduce handwritten prices and confuse AIsa routes with provider routes.
Provider imports and monthly reviewed refreshes follow after the initial
Similarweb rollout. Recursive references and mixed-body conditional unions need
a converter that produces a supported schema; they fail closed into pending.
