# Facebook paired route and response review

The six public routes map to two different gateway integrations for the same
three JustOneAPI capabilities. They are not interchangeable version aliases.
The runtime facts used here pin compiler revision
`69282203059b8005534003e33889ff5a670cb336`; the local AIsaServices working tree is
on the older `02204d4266c93a1ff0ab1883b0531f402356814e`. The code review below
uses the pinned compiler commit, read without modifying either working tree.
This is not an independently verified deployed-image revision.

| Public suffix under `/apis/v1/facebook/` | Method and input | Provider and stored operation ID |
| --- | --- | --- |
| `get-post-comments` | POST JSON: required `post_id`; closed body/query | `composio`: `JUST_ONE_API_FACEBOOK_GET_POST_COMMENTS` |
| `get-post-comments-v1` | GET query: `postId`, optional `cursor` | `treg`: `justoneapi.x.facebook-get-post-comments-v1` |
| `get-profile-posts` | POST JSON: required `profile_id`; closed body/query | `composio`: `JUST_ONE_API_FACEBOOK_GET_PROFILE_POSTS` |
| `get-profile-posts-v1` | GET query: `profileId`, optional `cursor` | `treg`: `justoneapi.x.facebook-get-profile-posts-v1` |
| `search-post` | POST JSON: required `keyword`; closed body/query | `composio`: `JUST_ONE_API_FACEBOOK_SEARCH_POST` |
| `search-post-v1` | GET query: `keyword`, optional `cursor`, `startDate`, `endDate` | `treg`: `justoneapi.x.facebook-search-post-v1` |

POST input restrictions come from the captured immutable AIsa runtime facts.
GET parameter names and pagination/date capabilities come from the current
[Treg catalog](https://treg.to/catalog/providers/justoneapi) and its linked
JustOneAPI documentation. The GET runtime contract uses provider validation and
open query forwarding. This review did not execute pagination or date filters
on these six routes.

## Code correspondence

- Explicit public path mappings: [Composio entries](https://github.com/AIsa-team/AIsaServices/blob/69282203059b8005534003e33889ff5a670cb336/packages/integrationcatalog/vendors.json#L870) and [Treg entries](https://github.com/AIsa-team/AIsaServices/blob/69282203059b8005534003e33889ff5a670cb336/packages/integrationcatalog/vendors.json#L11067).
- [Public route selection](https://github.com/AIsa-team/AIsaServices/blob/69282203059b8005534003e33889ff5a670cb336/packages/publicroute/publicroute.go#L73) and [snapshot indexing](https://github.com/AIsa-team/AIsaServices/blob/69282203059b8005534003e33889ff5a670cb336/services/api-service/internal/integration/snapshot.go#L486) map each published path to its configured endpoint/provider. There are no six independent Facebook handlers.
- [Request wrapping](https://github.com/AIsa-team/AIsaServices/blob/69282203059b8005534003e33889ff5a670cb336/services/api-service/internal/httpapi/integration_gateway_body.go#L63) supplies the pinned Composio tool identity and places customer fields under `arguments`.
- [Connect execution](https://github.com/AIsa-team/AIsaServices/blob/69282203059b8005534003e33889ff5a670cb336/packages/composioconnect/connect.go#L50) converts that body into one MCP tool execution. The immutable POST response origin/path digests match `https://connect.composio.dev` and `/mcp`.
- [PublicResponse](https://github.com/AIsa-team/AIsaServices/blob/69282203059b8005534003e33889ff5a670cb336/packages/composioconnect/workbench.go#L151) returns the completed tool's `response.data`. The full Composio receipt/envelope is not the customer's response schema.
- [Public response dispatch](https://github.com/AIsa-team/AIsaServices/blob/69282203059b8005534003e33889ff5a670cb336/services/api-service/internal/httpapi/integration_gateway_body.go#L105) applies that Composio extraction; Treg does not take this branch.

Read-only Prometheus queries on 2026-11-10 also returned all six exact internal
operation paths under `integration_api_upstream_attempts_total`: the three
uppercase tool paths had `provider="composio"`; the three JustOneAPI `-v1` paths
had `provider="treg"`. These counters corroborate live provider/operation usage;
they do not establish exact database configuration or correlate individual
requests. No production database rows were read or changed.

## Response evidence and remaining eight-page debt

See [the full live check](facebook-tiktok-full-response-check-20261110.md).
Following the path-only `get-profile-id` correction, all eight existing Facebook
routes have successful samples; all share
`code`, `data`, `message`, `recordTime`, and `requestId`. The three GET routes
add `requestParams`, with string query values and a null body, contradicting the
objects declared by the official schema. Profile-post and search pairs share
observed result-item field names, but this does not establish full type,
requiredness, nullability, error, or pagination equivalence.

For the same alternate post input, POST comments returned zero items while GET
comments returned ten. Calls were not simultaneous; the cause is not established.
The POST comments and comment-replies samples were all empty, so their result-item
schemas cannot be derived from those executions. The initial `get-profile-id` full-URL fixture returned 502 twice. A follow-up
confirmed that the upstream requires a path only: `{"url":"/NASA"}` succeeded
with HTTP 200, `code: 0`, and a string `data.profile_id`. See
[the follow-up diagnosis](facebook-profile-id-diagnosis-20261110.json).

The CR still lacks complete machine-readable success schemas for all eight
routes. This change adds explicit response notes to their eight English and
eight Chinese pages: official outer fields, observed business fields, sample
limits, paired-route differences, and upstream links. It does not substitute
sample-inferred schemas or an empty object for the outstanding full schema
review. It does not mark the eight unresolved rows complete or alter the OpenAPI
placeholder, requests, prices, publication receipts, or runtime.

Completion requires a provider-authored business schema or another reviewed
contract with adequate evidence for the nested data, resolution of the GET
`requestParams` conflict, nonempty comment/reply coverage, and review of the observed `get-profile-id` business structure. A source file or a passing unconstrained `data: {}`
validator alone is not evidence of that completion.
