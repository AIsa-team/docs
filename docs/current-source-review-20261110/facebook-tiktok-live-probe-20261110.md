# Facebook and TikTok live response verification

Three authenticated requests through `https://api.aisa.one` on 2026-11-10
returned HTTP 200 with `application/json`. All three actual response bodies
validated against the composed candidate schemas without schema errors.
This provides sample evidence for two of the 51 candidate operations.

| Operation | Case | Records | Schema result |
| --- | --- | ---: | --- |
| `GET /apis/v1/facebook/events` | First page | 12 events | Match |
| `GET /apis/v1/facebook/events` | Returned cursor used for next page | 12 events | Match |
| `GET /apis/v1/tiktok/collections/videos` | First page | 5 videos | Match |

The Facebook next page contained nine new event IDs and three repeated IDs;
the continuation cursor changed. This demonstrates continuation, not a
guarantee of duplicate-free pagination. The TikTok collection ID matched the
request, with `hasMore: false` and `nextCursor: null`. There was no
`lookupStatus` field. Both routes returned a `data`/`meta` envelope.

The sum of the three customer settlement headers was USD 0.042. This is a
reported settlement amount, not an independent wallet or rate reconciliation.

The [machine-readable evidence](facebook-tiktok-live-probe-20261110.json)
records response and candidate-schema digests, field names and validation
results. It excludes credentials, request IDs, opaque cursors and raw payloads.
The [source review](facebook-tiktok-response-review.json) remains the provenance
record for the provider-authored definitions and examples.

The other 49 candidate operations and eight unresolved Facebook operations
were not called. Empty results and error responses were not tested. TikTok
pagination was not tested because this sample returned no next cursor.
Passing these samples does not establish that every live response matches the
schema. The PR remains a draft pending further review and user approval;
these checks do not authorize merging, promotion or publication.
