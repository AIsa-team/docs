# Runtime documentation content sources

Documentation has three sources with different authority. The Composer produces
one immutable generation from them; Docs imports that generation rather than
reading live response samples or editing generated schemas independently.

| Content | Authority | Update path |
| --- | --- | --- |
| Purpose, usage explanation, field meaning, limitations | Reviewed editorial overlay and independently bound upstream reference | Normal source review / Docs PR; static prose precedes title-like runtime fallback |
| Public request validation, pricing, availability, capabilities, pagination and latency | Metering V2 and code-owned handler contracts | Runtime source fingerprint, worker compilation, immutable publication |
| Previously undocumented response structure | Successful probe responses and sampled customer responses after public egress | Bounded structural observation, frozen runtime input, worker compilation, Docs import |

Response observations do not establish a complete contract. They contain field
names and JSON types, no real examples, values, account IDs, request IDs or exact
customer timestamps. Field names themselves may contain user data. Automatic inference therefore
emits only a reviewed vocabulary of common API field names (including case and
snake/camel spelling variants); unfamiliar keys and oversized dictionaries stay
undocumented open objects. Extend the vocabulary through normal source review,
not by automatically learning names from customer values. Do not infer required fields, enum
values, formats or numeric bounds from samples. Independent official or owned
response declarations always win. Docs labels observed structures in both languages
and preserves the separately declared schema when one exists.

The collector reuses existing daily probe/customer sampling. It adds no provider
requests. Structure is inferred before replay scrubbing so numeric IDs remain
numeric; old scrubbed replay bodies cannot safely bootstrap this evidence. Each
observation is bound to endpoint/provider IDs, public method/path, upstream route,
endpoint/provider configuration and base URL. Method and HTTP status are separate;
an ANY route's GET evidence cannot document its POST response. Config/route changes
invalidate the binding. No binding hash is exported in the observation extension.

Within a matching binding, repeated samples add optional structure and union
observed types. Missing fields do not imply deletion. Nodes expire after 30 UTC
days without observation, and expired observed schemas are never retained as
reviewed historical response sources by the Composer. Collection is bounded to a
1 MiB response, 256 structural nodes, depth 12 and 32 KiB of structural evidence;
the existing index capacity and TTL remain in force. Limits may leave documentation
partial. Observations never change validation, billing, routing or result rules.

Publication reads the evidence once and freezes only the projected structure,
origin kind and observation date. Those bytes enter the source digest, so a new
shape or expiry triggers a new generation even without a configuration write.
A failed Redis read refuses publication refresh and keeps the last publication;
it does not erase evidence or affect a customer's request. Documentation therefore
changes atomically with the runtime artifact, not in place after publication.

Public pages and their OpenAPI downloads use the customer projection. Internal
formal files remain build inputs and are excluded from Mintlify for projected
catalogs. Both generation and localization understand the projected page references.

Rollout requires the Docs Composer code pin to be on main before the Services
build can consume it. The reviewed input bundle and review receipt clocks are not
renewed by this feature. New observations appear only after the updated API/worker
collect real successful responses and the normal publication/import workflow runs.
