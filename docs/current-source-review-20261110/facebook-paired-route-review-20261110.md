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
open query forwarding. The follow-up exercised GET profile-post and search pagination. Date filters
remain untested; see the current eight-route review below.

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

## Current response review

The [code and actual-request follow-up](facebook-eight-response-review.md)
supersedes the previous response-note-only status. Five POST response envelope
sources are now copied from Composio's own output definitions and projected
through AIsa's actual response adapter. Native JustOneAPI schemas are not used
as their public response source. The same schemas were returned for the official
Composio documentation's version 20261101_00 and latest.

Fifteen successful samples cover all eight routes. The eight POST samples match
those Composio envelopes. The seven GET samples reject the native requestParams
object declarations. POST comments and replies remain empty in all five calls.
Complete business field contracts remain unverified for all eight routes.
Unverified sample-derived types are not imported, and customer pages contain
only declared POST envelope fields. No merge or publication is authorized.
