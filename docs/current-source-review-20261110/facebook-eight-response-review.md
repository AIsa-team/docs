# Facebook response review: code and actual requests

Five POST routes now have exact Composio-declared response envelope candidates.
They are not JustOneAPI native response copies. The complete nested business
contracts for the eight routes are still not verified, and this PR is not ready
to publish those as complete definitions.

The [evidence packet](facebook-eight-response-review.json) contains official
schemas, their acquisition hashes, code hashes, 15 successful AIsa request
observations and exact schema-error paths. It contains no raw production bodies,
request IDs, cursors or credentials. The cumulative Facebook/TikTok check now
contains 100 calls, including the earlier checks and five additional requests.

## Confirmed calling chains

- Five POST operations use Composio Connect. AIsa wraps customer parameters in
  tool arguments, then returns the completed tool's `response.data` through
  `composioconnect.PublicResponse`. The Composio receipt and `successful` wrapper
  are not part of the public response.
- Three GET `-v1` operations use Treg. They do not take the Composio extraction
  branch. Their schemas cannot be substituted for the POST schemas.
- Code inspection and both passing package test suites use exact revision
  `69282203059b8005534003e33889ff5a670cb336`, the compiler revision advertised by
  the current immutable Runtime release. The deployed application image revision
  was not independently verified.

## Composio-specific verification

The [Composio toolkit reference](https://docs.composio.dev/toolkits/just_one_api)
lists version `20261101_00`. All five tools were fetched from the official docs
metadata API with both `version=latest` and `version=20261101_00`. Their input
and output schemas are identical across those requests. The versioned metadata
omits the separate Instant pricing metadata returned by `latest`.

The five official output schemas declare a tool wrapper whose `data` references
the business envelope. The public candidates copy that referenced schema exactly:
required integer `code`, required unconstrained `data`, required string-or-null
`message` and `recordTime`, and optional string `requestId`. No nested properties,
requiredness or nullable allowances were inferred from samples.

The public docs proxy does not attest the deployed session's exact metadata
version. Matching this public metadata does not replace a pinned-binding readback.

## Actual request coverage

All paths below are under `/apis/v1/facebook/`.

| Route | Integration | Successful samples | Nonempty business result | Remaining gap |
| --- | --- | ---: | --- | --- |
| POST `get-comment-replies` | Composio | 2 | No | No nonempty reply item; nested contract absent |
| POST `get-post-comments` | Composio | 3 | No | No nonempty comment item; nested contract absent |
| POST `get-profile-id` | Composio | 1 | Yes | `profile_id` observed as string; nested contract absent |
| POST `get-profile-posts` | Composio | 1 | Yes | Nested contract absent |
| POST `search-post` | Composio | 1 | Yes | Nested contract absent |
| GET `get-post-comments-v1` | Treg | 3 | Yes | Native request echo schema conflicts; nested contract absent |
| GET `get-profile-posts-v1` | Treg | 2 | Yes, including next page | Same schema gaps |
| GET `search-post-v1` | Treg | 2 | Yes, including next page | Same schema gaps; date filters not exercised |

All eight Composio POST samples match the projected official envelope. All seven
Treg GET samples fail the native JustOneAPI envelope because `requestParams.query`
values are strings and `requestParams.body` is null, whereas the native schema
declares objects. This mismatch is specific to the GET chain, not evidence of a
Composio output-schema mismatch.

The observed comment `reactions_count` is a string, while the observed post field
is an integer. These observations remain evidence; they do not establish a common
contract, complete variants or mandatory fields. Nonempty GET comment samples are
not used to fill either POST comment-item schema.

## Publication status

Five official envelope sources are registered, with Composio transport hashes and
regression tests. Three GET schema sources remain unregistered. All eight nested
business contracts remain open. Sample-inferred candidate schemas were removed;
review uncertainty was moved out of the customer pages. The five POST pages now
describe only officially declared outer fields.

No response transport, input validation, pricing, production configuration,
publication receipt or main branch was changed. Keep the PR draft. Full business
completion requires a versioned Composio output contract or an explicit AIsa
business response model, plus separate resolution of the Treg GET conflicts.
